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
.equ STREAM_VSUM,    0xC072E1B0     /* u32, gyro samples across every gap
                                     * between exposures in the take.
                                     *
                                     * VMIN turned out to be a bad instrument:
                                     * one transient at the 59.94 -> 30 mode
                                     * change put a zero gap in and destroyed
                                     * it, while VMAX read a clean 84.  A sum
                                     * over 663 gaps is not moved by one
                                     * outlier, and the frame period is not an
                                     * integer anyway -- 2500/29.97 is 83.417,
                                     * so the gaps alternate 83 and 84 and only
                                     * a mean can say which way it leans.    */
.equ STREAM_VNF,     0xC072E1B4     /* u32, gaps counted into VSUM           */
.equ STREAM_VSHORT,  0xC072E1B8     /* u32, gaps too short to be a frame      */
.equ VD_GAP_FLOOR,   64             /* A real frame gap is 83 or 84 samples.
                                     * Vd sometimes fires twice for one frame
                                     * -- 674 gaps came back with a max of 84
                                     * and a mean of 80.5, which needs about
                                     * twenty-three near-zero gaps in the set,
                                     * and matches the 953-Vd-to-900-frame
                                     * excess seen on the card.  A doubled
                                     * interrupt splits a gap into 0 and 84,
                                     * so dropping the short half keeps the
                                     * real period intact rather than averaging
                                     * a fiction.                             */
.equ STREAM_VOMAX,   0xC072E1BC     /* u32, the LONGEST of the gaps that were
                                     * too short to be a frame.  If it is
                                     * zero, every excluded gap was exactly
                                     * zero and the 64-sample threshold made no
                                     * judgement at all -- which is the one
                                     * soft spot in the measurement, so it is
                                     * worth a word to close it.
                                     *
                                     * VMIN is now the minimum over the LONG
                                     * gaps only.  With VMAX that pins the set:
                                     * if min is 83 and max is 84 then every
                                     * long gap was one or the other, and how
                                     * many of each follows from the sum with
                                     * no assumption left --
                                     *     n84 = VSUM - 83*VNF
                                     *     n83 = VNF - n84                   */
.equ STREAM_V0_GC,   0xC072E1C0     /* u32, STREAM_GCOUNT at the first sensor
                                     * Vd after recording began.  THE anchor:
                                     * the gyro sample the take's first frame
                                     * was read out against.  Vd is the
                                     * exposure side of the pipeline -- a frame
                                     * reaches the card hundreds of buffered
                                     * milliseconds later, so the file write is
                                     * the wrong end to measure from.        */
.equ STREAM_VCOUNT,  0xC072E1C4     /* u32, Vd since the start re-armed it.
                                     * Vd free-runs in liveview, so the count
                                     * is meaningless unless something resets
                                     * it -- the record-start hook does.     */
.equ STREAM_V1_N,    0xC072E1C8     /* u32, STREAM_VCOUNT at the stop.  Vd
                                     * keeps running once the take ends, so
                                     * reading the live count later counts
                                     * liveview frames as the take's.        */
.equ STREAM_VPREV,   0xC072E1CC     /* u32, ring head at the previous Vd      */
.equ STREAM_R1_GC,   0xC072E1D0     /* u32, STREAM_GCOUNT when recording ended */
.equ STREAM_R1_N,    0xC072E1D4     /* u32, times that has happened            */
.equ STREAM_VMIN,    0xC072E1D8     /* u32, shortest gap between two exposures,
                                     * in gyro samples.  With VMAX this is the
                                     * measurement everything else has been
                                     * inferred from: samples per frame against
                                     * the sensor's own cadence, with no host
                                     * clock and no write pipeline in it.
                                     * min == max means one rate throughout.  */
.equ STREAM_VMAX,    0xC072E1DC
.equ STREAM_R0_HEAD, 0xC072E1E0     /* u32, ring head offset at record start   */
.equ STREAM_V0_HEAD, 0xC072E1E4     /* u32, ring head offset at the first
                                     * exposure.  These two differ by the real
                                     * anchor, to 400 us -- the gyro counter
                                     * could only ever say "within one 20 ms
                                     * batch".                               */
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
.equ STREAM_INDEX,   0xC072E1F8     /* u32, monotonic; both producers claim it */
.equ STREAM_GCOUNT,  0xC072E1FC     /* u32, gyro records only -- the rate ruler */
.equ STREAM_RING,    0xC072E1A0     /* u32, the ring's ABSOLUTE base.  Not a
                                     * constant: the real buffer lives in the
                                     * pool, whose address is only known at
                                     * run time, so the deployer resolves it
                                     * once and every producer loads it.
                                     * 0 means "use the bench ring below".   */
.equ STREAM_TAIL,    0xC072E1A4     /* u32, records the writer has taken      */
.equ STREAM_SIGFN,   0xC072E1A8     /* u32, writer_signal's address, or 0     */
.equ STREAM_BASE,    0xC072E200     /* the bench ring, when STREAM_RING is 0  */
.equ STREAM_COUNT,   32             /* The bench ring, and only a fallback: the
                                     * producers use it when STREAM_RING is 0,
                                     * which is before the pool buffer exists.
                                     * 256 bytes is enough to be valid, and the
                                     * cave needs the rest for the writer.    */
.equ STREAM_MASK,    (STREAM_COUNT - 1)

/* The real ring, out of the pool.  16384 records is 128 KiB and 6.5 seconds at
 * 2500 Hz -- nine times the worst card stall this project has measured (692 ms)
 * and the same idea as the audio path's forty seconds of headroom, scaled to
 * our tiny data rate.
 *
 * pool+0x20000: 896 KB there is free and 224 of 224 markers survived a
 * recording start, which is the property that matters -- memory from the
 * firmware's allocator freezes the camera when held across one. */
.equ RING_RECORDS,   16384
.equ RING_MASK,      (RING_RECORDS - 1)
.equ RING_BYTES,     (RING_RECORDS * 8)
.equ RING_POOL_OFF,  0x20000

/* Ring the doorbell only when this much is waiting.  The producer runs every
 * 20 ms; waking the writer that often would put 50 small writes a second
 * through the one card lock, which is the opposite of what the audio path
 * does.  1024 records is 8 KiB, about every 400 ms at 2500 Hz. */
.equ RING_CHUNK,     1024

.equ TAG_GYRO,       0
.equ TAG_ACCEL,      1
.equ TAG_FRAME,      2
.equ TAG_START,      3
.equ TAG_STOP,       4
.equ TAG_VD,         5

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
.equ O_VSUM,        -0x10
.equ O_VNF,         -0x0C
.equ O_VSHORT,      -0x08
.equ O_VOMAX,       -0x04
.equ O_V0_GC,        0x00
.equ O_VCOUNT,       0x04
.equ O_V1_N,         0x08
.equ O_VPREV,        0x0C
.equ O_R1_GC,        0x10
.equ O_R1_N,         0x14
.equ O_VMIN,         0x18
.equ O_VMAX,         0x1C
.equ O_R0_HEAD,      0x20
.equ O_V0_HEAD,      0x24
.equ O_GCOUNT,       0x3C

.if (STREAM_STATE + O_VSUM)   != STREAM_VSUM
.error "O_VSUM does not point at STREAM_VSUM"
.endif
.if (STREAM_STATE + O_VNF)    != STREAM_VNF
.error "O_VNF does not point at STREAM_VNF"
.endif
.if (STREAM_STATE + O_VSHORT) != STREAM_VSHORT
.error "O_VSHORT does not point at STREAM_VSHORT"
.endif
.if (STREAM_STATE + O_VOMAX)  != STREAM_VOMAX
.error "O_VOMAX does not point at STREAM_VOMAX"
.endif
.if (STREAM_STATE + O_V0_GC)  != STREAM_V0_GC
.error "O_V0_GC does not point at STREAM_V0_GC"
.endif
.if (STREAM_STATE + O_VCOUNT) != STREAM_VCOUNT
.error "O_VCOUNT does not point at STREAM_VCOUNT"
.endif
.if (STREAM_STATE + O_V1_N)   != STREAM_V1_N
.error "O_V1_N does not point at STREAM_V1_N"
.endif
.if (STREAM_STATE + O_GCOUNT) != STREAM_GCOUNT
.error "O_GCOUNT does not point at STREAM_GCOUNT"
.endif
.if (STREAM_STATE + O_R0_HEAD) != STREAM_R0_HEAD
.error "O_R0_HEAD does not point at STREAM_R0_HEAD"
.endif
.if (STREAM_STATE + O_V0_HEAD) != STREAM_V0_HEAD
.error "O_V0_HEAD does not point at STREAM_V0_HEAD"
.endif

.equ VPREV_FROZEN,   0xFFFFFFFF   /* the stop hook writes this so liveview Vd
                                   * stops folding its own, much shorter,
                                   * intervals into the take's min and max  */

/* Where a record goes.  One place, because four producers index this ring and
 * a fifth copy of the arithmetic is a fifth chance to get the mask wrong.
 *
 * \idx is the claimed index, \out comes back as the record's address.  When
 * STREAM_RING is zero the bench ring in the cave is used instead, so the hooks
 * work before the pool buffer exists. */
.macro ring_slot idx, out, tmp
    movw    \out, #:lower16:STREAM_RING
    movt    \out, #:upper16:STREAM_RING
    ldr     \out, [\out]
    cmp     \out, #0
    movweq  \tmp, #STREAM_MASK
    movwne  \tmp, #:lower16:RING_MASK
    movtne  \tmp, #:upper16:RING_MASK
    and     \idx, \idx, \tmp
    movweq  \out, #:lower16:STREAM_BASE
    movteq  \out, #:upper16:STREAM_BASE
    add     \out, \out, \idx, lsl #3
.endm

.equ STREAM_JPOOL,   0xC072E19C     /* u32, our MPoolFixed of job descriptors */
.equ STREAM_POSTED,  0xC072E1AC     /* u32, records already handed to the
                                     * writer.  The producer owns this; the
                                     * writer never touches the ring's indices
                                     * at all, exactly as the audio writer does
                                     * not -- it writes the pointer and length
                                     * it was given and nothing else.        */

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
.equ J_SEQ,          0x10           /* which job this is, for reading back    */
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
.equ T_STOPSENT,     0xC072E15C     /* shared with ring_task.inc.S */
.equ T_OPENFN,       0xC072EA64     /* shared with ring_task.inc.S: -> take_open  */
.equ T_CLOSEFN,      0xC072EA68     /* shared with ring_task.inc.S: -> take_close */
.equ T_WANT,         0xC072E194     /* shared with ring_task.inc.S: 1 = a take
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
