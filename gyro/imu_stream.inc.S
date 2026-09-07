/* One ordered stream, one record shape.
 *
 *      0   i16  x
 *      2   i16  y
 *      4   i16  tag     0 = gyroscope, 1 = accelerometer
 *      6   i16  z
 *
 * Eight bytes either way, and the tag is the only thing that separates them.
 *
 * There is no per-record timestamp, and that is the point.  The gyro runs on a
 * strictly uniform 2500 Hz hardware grid, so a gyro record's position in the
 * stream already says when it happened: one step back is 400 us earlier.  The
 * clock reads that used to stand in for this come from a TickTimer call made
 * inside the callback, which lags the last sample by however long the callback
 * took to arrive -- nought to a millisecond of jitter, which the old seam
 * arithmetic then had to spend code undoing.  A per-record timestamp would have
 * sprayed that jitter across every row instead of the block boundary.  So the
 * grid is the time base and one anchor per block places the whole run.
 *
 * The accelerometer has no grid of its own -- the firmware publishes it at
 * about 47 Hz, unevenly -- so it does not get a time of its own either.  It is
 * appended where it happens, between two gyro records, and it belongs to the
 * row it lands next to.  The reader advances 400 us on tag 0 and does not
 * advance on tag 1.
 *
 * The one honest cost: the gyro producer runs in the firmware's GyroData
 * callback, measured at 50.0 Hz -- 1170 drains in 23.378 s -- so it appends a
 * whole 20 ms batch at once, at the end of the 20 ms it covers.  An
 * accelerometer record that arrives between two callbacks is appended at its own
 * true instant, but the gyro record it lands against is the last one of the
 * batch that has already been drained.  So the reader dates it to the start of
 * the interval it actually arrived in: nought to twenty milliseconds EARLY, ten
 * on average.  Early, not late -- the gyro records are what run behind, and the
 * accelerometer inherits their lag.
 *
 * The accelerometer only ever feeds a gravity vector at 47 Hz, which does not
 * move in 20 ms, so this is left as it is rather than paid for.  It is written
 * down because "position implies time" is a claim and this is the size of the
 * claim's error.  It is also fixable for free if it ever matters: the hook could
 * latch the firmware ring's head along with the sample, and the gyro producer
 * splice the record in at that position inside the batch instead of after it.
 *
 * tag 2 is a video frame exposure.  Not a row either, and it carries no time of
 * its own -- it IS a time, the one the clip is cut on.  Its position says which
 * gyro sample the frame was exposed against, so both of the questions that
 * matter -- how many samples per frame, and which sample is frame zero -- are
 * read straight out of the stream rather than computed from a clock.
 *
 * Note what this does NOT claim.  Audio is in sync with video without knowing
 * an accurate start time at all: both begin filling at the same event, so any
 * common offset is invisible inside the clip.  By the same argument, a gyro
 * stream that begins at that event needs no timestamp either.  So the 470-570
 * ms our anchor is out by is not evidence that the factory's start point is
 * late -- it has never been established which side is late, and the marker is
 * here to settle that by measurement rather than to assume it.
 */

/* Provisional home: the logger's own injection cave, with no logger loaded.
 * When the two producers are assembled into the real thing, these move to the
 * buffer declared out of the pool the way the audio writer declares its own. */
.equ STREAM_R1_GC,   0xC072E1D0     /* u32, STREAM_GCOUNT when recording ended */
.equ STREAM_R1_N,    0xC072E1D4     /* u32, times that has happened            */
.equ STREAM_DRAINFN, 0xC072EC40     /* -> gyro_drain, placed by the deployer   */
.equ STREAM_FLUSHFN, 0xC072EC44    /* -> stream_flush, placed by the deployer */
.equ STREAM_R0_HEAD, 0xC072E1E0     /* u32, ring head offset at record start   */
.equ STREAM_R0_GC,   0xC072E1E8     /* u32, STREAM_GCOUNT when the audio file
                                     * writer was constructed.  Beside F0_GC
                                     * this is the whole experiment: the gap
                                     * between them is how far our start point
                                     * sits from the take's first exposure,
                                     * measured in gyro samples of 400 us --
                                     * a number, where the 470-570 ms has only
                                     * ever been an inference from Gyroflow's
                                     * auto-sync.
                                     *
                                     * MEASURED 2026-09-06, two takes: the gap
                                     * between R0 and R1 tracked the take -- an
                                     * 11 s take gave 11.38 s, a 3 s take gave
                                     * 4.40 s -- and 0xC01FBA28 fired first
                                     * both times.  So that one is the start
                                     * and 0xC01FB880 is the end, which is the
                                     * opposite of what the call sites read
                                     * like.  movRec tears the running monitor
                                     * audio down when recording begins; the
                                     * state machine's case 1 builds it back up
                                     * when recording ends.                   */
.equ STREAM_R0_N,    0xC072E1EC     /* u32, times that has happened            */
.equ STREAM_GHEAD,   0xC072E1F0     /* u32, gyro ring head we have consumed    */
.equ STREAM_PADBAD,  0xC072E1F4     /* u32, gyro samples whose pad was not 0   */
.equ STREAM_GCOUNT,  0xC072E1FC     /* u32, gyro records only -- the rate ruler */
.equ STREAM_CLAIMFN, 0xC072EC38     /* -> stream_claim, placed by the deployer */
.equ STREAM_COMMITFN,0xC072EC3C     /* -> stream_commit                        */     /* u32, gyro records only -- the rate ruler */
.equ STREAM_SIGFN,   0xC072E1A8     /* u32, writer_signal's address, or 0     */

/* The real ring, out of the pool.  16384 records is 128 KiB and 6.5 seconds at
 * 2500 Hz -- nine times the worst card stall this project has measured (692 ms)
 * and the same idea as the audio path's forty seconds of headroom, scaled to
 * our tiny data rate.
 *
 * pool+0x20000: 896 KB there is free and 224 of 224 markers survived a
 * recording start, which is the property that matters -- memory from the
 * firmware's allocator freezes the camera when held across one. */

/* The buffers, as AudF_W has them: separate allocations, and "full" is not a
 * number anyone computes -- it is this block being used up.
 *
 * DspAudioDevice::v5 asks the class 6 heap for two 16 KiB blocks, hands both to
 * the DSP, and the DSP raises a completion when one of them ends.  The boundary
 * is the allocation's own size; there is no index, no mask and no modulo, and
 * nothing anywhere tests "have we reached a multiple of something".
 *
 * We had one big allocation tiled into sixteen by arithmetic, and that meant
 * "full" was still a calculation -- just one that had moved out of the
 * producer.  These are real blocks now.  stream_claim hands out what is left of
 * the current one, and when nothing is left, that block is done: the same
 * subtraction that decides how much to give also decides that it is over.
 *
 * 16 KiB is audio's block size, so a write is the size a write is on this
 * camera.  Eight of them, not two, because audio's producer can be throttled by
 * its hardware and ours cannot: a DSP that overruns is audio's problem to size
 * for, and it sized for 85 ms.  Ours is 0.8 s a block and 6.6 s in total.
 */
.equ BUF_N,          8
.equ BUF_BYTES,      0x4000                 /* what AudF_W's blocks are        */
.equ BUF_RECORDS,    (BUF_BYTES / 8)

.equ B_PTR,          0xC072EBA0             /* BUF_N words: the allocations    */
.equ B_BUSY,         0xC072EBC0             /* BUF_N words: 0 free, 1 with the
                                             * writer.  Audio has no such flag
                                             * -- its DSP simply reuses its two
                                             * blocks on schedule and the writer
                                             * has to keep up.  Ours cannot be
                                             * throttled, so a block that is
                                             * still being written must not be
                                             * refilled: that is a drop, and a
                                             * drop we can count.             */
.equ B_CUR,          0xC072EBE0             /* which block is filling, -1 none */
.equ B_FILL,         0xC072EBE4             /* records claimed in it           */
.equ B_DONE,         0xC072EBE8             /* records written into it         */
.equ B_OFF,          0xC072EBEC             /* file offset of its first byte    */
.equ B_DROPS,        0xC072EBF0             /* times no block was free          */
.equ B_HANDED,       0xC072EBF4             /* blocks handed to the writer      */
.equ T_JBLK,         0xC072EBF8             /* the block writer_post is about to
                                             * describe.  One producer posts, so
                                             * a word is enough and it saves
                                             * threading a fifth argument through
                                             * a hand-written call.            */             /* blocks handed to the writer      */

.equ B_NONE,         -1

/* Masking interrupts is how MPoolFixed::v1 and ::v2 protect their free list
 * (FUN_c001cce0 / XC_INTR__v0), and it is what these need too.
 *
 * Audio's producer is one DSP callback and needs nothing.  Ours has two
 * callers in two different tasks -- the accelerometer driver, and the recorder
 * when it commits a stop and the tail of the take has to come out of the
 * coprocessor's ring before the file closes.  B_CUR, B_FILL and B_DONE are read
 * and written together, so a task switch between them hands out the same space
 * twice.
 *
 * The old design got away with none of this because it claimed a single
 * monotonic word with LDREX.  Blocks need three words, and three words need a
 * lock. */
.macro st_lock saved
    mrs     \saved, cpsr
    orr     r12, \saved, #0xC0
    msr     cpsr_c, r12
.endm

.macro st_unlock saved
    mrs     r12, cpsr
    bic     r12, r12, #0xC0
    and     \saved, \saved, #0xC0
    orr     r12, \saved, r12
    msr     cpsr_c, r12
.endm

.equ TAG_GYRO,       0
.equ TAG_ACCEL,      1
.equ TAG_START,      3
.equ TAG_STOP,       4

/* Every state word lives in one 64-byte block, so a hook that touches several
 * of them loads the base once and indexes.  The .if guards below are the whole
 * point of writing it twice: an offset that drifts from its address would be a
 * hook quietly reading someone else's counter. */
.equ GYRO_DESC_PTR,  0xC31E3FCC     /* -> P; P+0x60 -> the firmware's ring    */
.equ GYRO_RING_SPAN, 0x12C0         /* 600 records of eight bytes             */

/* The ring's head, as a byte offset into it.
 *
 * STREAM_GCOUNT is no use for anything finer than a batch: the gyro producer
 * adds a whole 20 ms callback's worth at once, so two exposures 33 ms apart
 * read as gaps of 0, 50, 50, 0 -- quantised to twelve times the thing being
 * measured.  The head is written by the coprocessor at 2500 Hz, so it moves
 * eight bytes per sample and resolves 400 us.
 *
 * It wraps every 240 ms.  Fine for a gap between exposures; useless for the
 * length of a take, which is what GCOUNT stays for. */
.macro gyro_head reg, tmp
    movw    \reg, #:lower16:GYRO_DESC_PTR
    movt    \reg, #:upper16:GYRO_DESC_PTR
    ldr     \reg, [\reg]
    cmp     \reg, #0
    ldrne   \tmp, [\reg, #0x60]
    ldrne   \reg, [\tmp]
    subne   \reg, \reg, \tmp
    moveq   \reg, #0
.endm

.equ STREAM_STATE,   0xC072E1C0
.equ O_R0_HEAD,      0x20
.equ O_GCOUNT,       0x3C


.equ VPREV_FROZEN,   0xFFFFFFFF   /* the stop hook writes this so liveview Vd
                                   * stops folding its own, much shorter,
                                   * intervals into the take's min and max  */

/* Where a record goes.  One place, because four producers index this ring and
 * a fifth copy of the arithmetic is a fifth chance to get the mask wrong.
 *
 * \idx is the claimed index, \out comes back as the record's address.  When
 * STREAM_RING is zero the bench ring in the cave is used instead, so the hooks
 * work before the pool buffer exists. */

.equ STREAM_JPOOL,   0xC072E19C     /* u32, our MPoolFixed of job descriptors */

/* A job, 24 bytes -- the same payload size the firmware's own
 * MPoolFixed<24,32> hands out to the audio path.
 *
 * The pool IS the queue: taking a descriptor is taking a queue slot, and an
 * empty pool is a full queue.  That is the back-pressure signal, for free, in
 * the form the firmware already trusts. */
/* Offset 0 is NOT ours.
 *
 * tk_snd_mbx takes a message that must begin with T_MSG -- the kernel's own
 * queue link, one word at offset 0, which it writes into while the message is
 * queued.  The audio writer's descriptor leaves that word alone and starts its
 * fields at +4; ours had J_PTR sitting on it, so we were storing a ring address
 * in the kernel's list pointer and the kernel was storing a list pointer in our
 * ring address.  That is the whole of it: it froze the camera five seconds into
 * a take even with every card call stubbed out, because it was never about the
 * card.
 *
 * Nothing here writes J_MSGQ.  It is declared only so the layout says why the
 * gap exists. */
.equ J_MSGQ,         0x00           /* the kernel's.  Do not touch.           */
.equ J_OFF,          0x04           /* where in the file this belongs         */
.equ J_PTR,          0x08           /* straight into the ring                 */
.equ J_LEN,          0x0C           /* bytes                                  */
.equ J_BLK,          0x10           /* which block, so the writer can free it */
.equ J_STOP,         0x14           /* 1 = the take is over, close after this  */
.equ J_SIZE,         24

/* The field order is AudioFileWriter's, not one of ours: +4, +8, +0xC and
 * +0x14 are the words FUN_c01fbc80 fills and AudioFileWriter::v1 reads.
 *
 * J_OFF is the field we did not have, and it is not decoration.  Our jobs used
 * to be a pure append -- "copy this many bytes from here" -- so a job that
 * could not get a descriptor (the counters have read back thousands of those)
 * simply vanished, and every record after it moved earlier in the file by the
 * length of the hole.  In a format whose whole claim is that position IS time,
 * that silently rewrites the timeline and nothing downstream can tell.
 *
 * Carrying the offset means a lost job leaves a hole exactly where it belonged
 * and every record after it keeps its own time.  Audio's writer compares the
 * offset against its running file position and seeks when they disagree; so
 * does ours now.  (The decompilation of v1 reads +4 as an end offset in the
 * matching branch and as a start offset in the seeking one; we implement the
 * evident intent -- a start offset -- because the property we need is the hole
 * in the right place.) */

.equ JOB_COUNT,      32             /* what audio's pool holds                */

.equ T_FOPEN,        0xC072E0FC     /* shared with ring_task.inc.S */
.equ T_OPENFN,       0xC072EC30     /* shared with ring_task.inc.S: -> take_open  */
.equ T_CLOSEFN,      0xC072EC34     /* shared with ring_task.inc.S: -> take_close */
.equ T_WANT,         0xC072EC50     /* shared with ring_task.inc.S: 1 = a take
                                     * wants the file.  Declared in both because
                                     * the producers and the writer are placed
                                     * by different scripts; the deployers check
                                     * the two agree. */

.equ HEAD_UNARMED,   0xFFFFFFFF

/* ---- can the accelerometer hook carry the drain on its own? -------------- *
 *
 * The 20 ms callback we borrow is a level/body-motion detector: it hands us no
 * gyro data, only a moment at which to go and copy the ring.  The accelerometer
 * hook could do that job instead, and doing it THERE would place the tag 1
 * record exactly rather than 0-20 ms early, because the ring would be drained
 * in the same breath as the record is appended.
 *
 * That only works if the accelerometer fires often enough.  The firmware ring
 * holds 600 records = 240 ms; a gap longer than that overwrites samples we
 * never took, and -- this is the dangerous part -- head-minus-cursor cannot
 * tell that apart from an ordinary wrap, so the loss would be silent.
 *
 * So measure before deciding.  These five words are pure observation: the accel
 * hook already runs, and all it does extra is note how many gyro samples piled
 * up since its own previous visit.  That number IS the batch an accel-only
 * drain would have had to move, measured on the coprocessor's own 400 us grid
 * rather than assumed from a nominal rate.
 *
 * ACC_MAX is the number that decides it.  A mean near 53 says "about 47 Hz";
 * only the maximum says whether the worst gap has margin against 600.
 */
.equ ACC_STATE,      0xC072E8C0     /* the block, so a reader takes it in one  */
.equ ACC_GHEAD,      0xC072E8C0     /* ring head at the previous accel visit   */
.equ ACC_MAX,        0xC072E8C4     /* largest gap seen, in records            */
.equ ACC_COUNT,      0xC072E8C8     /* accel visits that measured a gap        */
.equ ACC_SUM,        0xC072E8CC     /* records across every gap -> the mean    */
.equ ACC_OVER,       0xC072E8D0     /* gaps at or past ACC_DANGER              */
.equ ACC_WORDS,      5

/* 500 records = 200 ms, five sixths of the ring.  Anything at or past this is
 * already too close to call safe, whether or not it lost a sample. */
.equ ACC_DANGER,     500

.equ ACC_O_GHEAD,    0x00
.equ ACC_O_MAX,      0x04
.equ ACC_O_COUNT,    0x08
.equ ACC_O_SUM,      0x0C
.equ ACC_O_OVER,     0x10

.if ACC_GHEAD + ACC_O_MAX   != ACC_MAX
.err
.endif
.if ACC_GHEAD + ACC_O_COUNT != ACC_COUNT
.err
.endif
.if ACC_GHEAD + ACC_O_SUM   != ACC_SUM
.err
.endif
.if ACC_GHEAD + ACC_O_OVER  != ACC_OVER
.err
.endif
