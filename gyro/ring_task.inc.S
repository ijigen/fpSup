/* The dedicated writer task, and the kernel objects that drive it.
 *
 * Modelled on the audio file writer, because that is the one path in this
 * firmware that provably never drops under recording load.  Reading
 * AudioFileWriter::v1 @0xC01FBD40 and AudF_W @0xC01FD380, its properties are:
 *
 *     priority 6            equal to the video writer, above everything else
 *     stack 0x2000
 *     a deep ring           8 MB, about forty seconds of audio
 *     blocking, immediate   it waits on a MAILBOX with an infinite timeout and
 *                           runs the instant a message arrives
 *
 * Ours had none of them: priority 28, a 32 KiB double buffer, and a 5 ms poll.
 *
 * ---------------------------------------------------------------------------
 * Two things here were taken from the firmware after the notes turned out to
 * be wrong, and both would have frozen the camera.
 *
 * FIRST: every TK-OS stub has the same eight instructions and keeps its 32-bit
 * service ID at stub+0x20 --
 *
 *     push {r4} / add r4, sp, #4 / push {lr} / ldr ip, [pc, #0xc]
 *     bl <dispatcher> / pop {lr} / pop {r4} / bx lr / .word <service>
 *
 * -- and notes/STREAM_DROP_INVESTIGATION.md recorded three stubs twelve bytes
 * too high, which is the `ldr ip` inside the stub rather than its entry.
 *
 * SECOND, and worse: that note called services 0x11 and 0x12 slp_tsk and
 * wup_tsk.  They are not.  Calling 0x11 with a timeout returned E_ID (-18) on
 * the camera, which is what a call that wants a TASK ID says when handed -1 --
 * 0x11/0x12 are get_reg/set_reg.  Rather than hunt for the right function
 * codes, this uses the objects the audio writer itself uses, which is closer to
 * the brief anyway:
 *
 *     0x26  create   FUN_c01f88a4(&packet)          packet = {0, 1, 0, 0}
 *     0x28  send     FUN_c01f8d48(id, msg)          0 = ok
 *     0x29  receive  FUN_c01f8b74(id, &out, tmout)  0 = ok, -50 = timeout
 *
 * A mailbox message must be real memory: the kernel writes a link word into
 * the packet it is given.  Sending a constant would corrupt whatever that
 * address happens to be.
 *
 * There is also a trap in task creation, from notes/TASK_ABI_VERIFIED.md:
 * cre_tsk 0xC01F885C / sta_tsk 0xC01F8D90 are the CYC thread pair, which always
 * pass stksz=0 and a fixed trampoline.  The main path is the one below.
 */

.equ TK_CRE_TSK,     0xC0016A58     /* 0x80010100  id = f(&desc)              */
.equ TK_STA_TSK,     0xC0016BC0     /* 0x80030200  f(id, 0) -> 0 = ok         */
.equ TK_DLY_TSK,     0xC01F89C4     /* 0x80460100  f(ms)                      */
.equ MBX_CREATE,     0xC01F88A4     /* 0x80260100  id = f(&packet)            */
.equ MBX_SEND,       0xC01F8D48     /* 0x80280200  f(id, msg) -> 0 = ok       */
.equ MBX_RECV,       0xC01F8B74     /* 0x80290300  f(id, &out, tmout)         */

/* The rest of the set, read out of the syscall table rather than guessed:
 * the trampoline at 0xC00011D0 indexes *(0xC0001568) by the service id, and
 * every stub carries its id at stub+0x20.  See notes and [[tkos-thread-pool]].
 *
 * tk_ext_tsk (id 0x04) and tk_exd_tsk (0x05) are the only gap in the table --
 * a task cannot end ITSELF here.  Everything else audio does to its writer is
 * available, including terminating and deleting it from another task. */
.equ TK_DEL_TSK,     0xC01F897C     /* 0x80020100  f(id)                      */
.equ TK_TER_TSK,     0xC01F8E44     /* 0x80060100  f(id)                      */
.equ TK_SLP_TSK,     0xC01F8D00     /* 0x80130100  f(tmout)                   */
.equ TK_WUP_TSK,     0xC01F8ED4     /* 0x80140100  f(id)                      */
.equ FLG_CREATE,     0xC00169EC     /* 0x80200100  id = f(&packet)            */
.equ FLG_DELETE,     0xC0016AA0     /* 0x80210100  f(id)                      */
.equ FLG_SET,        0xC0016B9C     /* 0x80220200  f(id, ptn)                 */
.equ FLG_CLEAR,      0xC00169C8     /* 0x80230200  f(id, ptn)                 */
.equ FLG_WAIT,       0xC0016C08     /* 0x80240500  f(id,ptn,mode,&out,tmout)  */
.equ MBX_DELETE,     0xC0682FA4     /* 0x80270100  f(id)                      */

/* The T_CFLG XC_Thread.cpp hands tk_cre_flg, copied field for field from
 * 0xC0B98830: attr TA_TPRI|TA_WMUL|TA_DSNAME, initial pattern 1, name OsPool.
 * The pattern starts SET and the take clears it; the worker sets it again when
 * its body returns, and that is what the joiner waits for. */
.equ FLGATR,         0x49
.equ FLG_DONE,       1              /* the bit the body sets on its way out   */
.equ FLG_KEEP,       0xFFFFFFFE     /* clr_flg ANDs, so this clears bit 0     */

.equ TMO_FEVR,       -1
.equ JOIN_TMO,       8000           /* ms.  Audio joins with TMO_FEVR; we cannot,
                                     * because our join runs inside a firmware
                                     * callback and an infinite wait there is a
                                     * battery pull.  8 s is ten times the worst
                                     * card write this project has measured.  */

/* Descriptor for tk_cre_tsk, 32 bytes.  itskpri must be 1..32 and stksz at
 * least 0x100, or it returns E_PAR (-17). */
.equ D_EXINF,        0x00
.equ D_TSKATR,       0x04           /* 0x41                                   */
.equ D_TASK,         0x08           /* direct ARM entry                       */
.equ D_ITSKPRI,      0x0C
.equ D_STKSZ,        0x10
.equ D_DSNAME,       0x14           /* eight bytes                            */

.equ WRITER_PRI,     6              /* what AudF_W and SRecFile run at        */
.equ WRITER_STKSZ,   0x2000         /* AudF_W's.  It was 0x4000, on the grounds
                                     * that SRecFile uses 0x4000 for the same SD
                                     * path -- but the thread pool asks the
                                     * kernel for the stack at record start, and
                                     * the one parameter we passed differently
                                     * from audio was this one.  Audio's value
                                     * is the one that is known to work at that
                                     * moment.                                */

/* XC_Thread.cpp's own thread pool, used as audio uses it rather than
 * reimplemented.  FUN_c036e108 news a 0x14-byte object, creates the completion
 * flag, builds the T_CTSK with FUN_c036efe8 as the entry and starts it; the
 * worker then sleeps until a body is attached.  Everything the hand-written
 * version did -- the flag, tk_cre_tsk, tk_sta_tsk, the parking, the wup/ter/del
 * -- is inside these four calls. */
.equ XT_CREATE,      0xC036E108     /* f(&holder, pri, stksz, name8)          */
.equ XT_ATTACH,      0xC036E1B8     /* f(&holder, bodyobj): attach and wake   */
.equ XT_JOIN,        0xC036E1F8     /* f(&holder): tk_wai_flg, TMO_FEVR       */
.equ XT_DESTROY,     0xC036E168     /* f(&holder, 2): join, wup, ter, del     */

/* The take's own objects.  Audio builds file, thread and mailbox together at
 * record start and destroys all three at stop; these are the words that hold
 * them for one take.  Above everything else in the cave, clear of the
 * measuring accel build at 0xC072E900..0xC072EA04. */
.equ W_THREAD,       0xC072EC00     /* the holder XT_CREATE fills             */
.equ W_BODYOBJ,      0xC072EC04     /* our body object: one word, its vtable  */
.equ W_JOINRC,       0xC072EC08     /* reserved                               */
.equ W_OPENS,        0xC072EC0C     /* takes built                            */
.equ W_CLOSES,       0xC072EC10     /* takes torn down                        */
.equ W_STAGE,        0xC072EC14     /* how far the build or the teardown got  */
.equ W_VT,           0xC072EC20     /* 16 bytes.  The pool worker calls slot
                                     * +0xC of whatever object it is handed;
                                     * that is the whole interface, so this is
                                     * the whole class.  The deployer writes
                                     * writer_body into +0xC because only it
                                     * knows where the pool landed.          */
.equ W_VT_SLOT,      0x0C

/* Placed by the deployer, the way STREAM_SIGFN is: the record hooks live in the
 * cave and these live in the pool, so the address is only known at deploy. */
.equ T_OPENFN,       0xC072EC30     /* -> take_open                           */
.equ T_CLOSEFN,      0xC072EC34     /* -> take_close                          */

/* Below the accel hook, clear of the stream's own words at 0xC072E1B0. */
.equ T_DESC,         0xC072E080     /* 32 bytes, the task descriptor          */
.equ T_PKT,          0xC072E0A0     /* 32 bytes, the mailbox message.  Real
                                     * memory, because the kernel links it.   */
/* T_DOOR and writer_signal are gone.  They were a doorbell of my own
 * design: a flag claimed with LDREX, a fixed packet, a producer ringing
 * it.  Audio has nothing of the kind -- sending the job IS the wake-up,
 * and the message IS the work.  Nothing had called writer_signal since
 * the job queue went in; it was a leftover from the wrong design. */
.equ T_MBX,          0xC072E0C4     /* the mailbox id                         */

.equ T_ID,           0xC072E0D0     /* the task id                            */
.equ T_CRE_RC,       0xC072E0D4
.equ T_STA_RC,       0xC072E0D8
.equ T_WAKES,        0xC072E0DC     /* times the task woke                    */
.equ T_SIGNALS,      0xC072E0E0     /* times a producer rang the doorbell     */
.equ T_ENTRY,        0xC072E0E4     /* the task body, placed by the deployer  */
.equ T_RECV_RC,      0xC072E0E8     /* what receive returned when it stopped
                                     * returning zero                         */
.equ T_POS,          0xC072EC18     /* where the file is, in bytes.  Audio keeps
                                     * this at writer+0x14; it is the other half
                                     * of J_OFF.                              */
.equ T_SEEKS,        0xC072EC1C     /* times the two disagreed -- every one of
                                     * these is a job that never made it       */
.equ T_MBX_RC,       0xC072E0EC     /* what the mailbox create returned       */

/* ---- the card write ---------------------------------------------------- */

/* The same file object the audio writer uses.  XC_MediaFile::Write is where
 * every write on this camera funnels through, and it takes and releases the one
 * non-preemptible card lock, so writing from here is writing exactly the way
 * audio does.  F_WRITE(object, source, length) -- the source is a pointer, and
 * ours points straight into the ring.  Nothing is copied. */
/* The allocator, used the way DspAudioDevice::v5 uses it: ask at capture
 * start, give it back at capture stop.
 *
 * FUN_c001cf78(class) returns the channel; the class list is the name table at
 * 0xC0727CBC -- 0 USER, 1 OSD, 2 IMAGE, 3 LVIEW, 4 MOVIMAGE, 5 MOVLVIEW,
 * 6 MOVAUDIO, 7 MOVWORK, 8 MOVSOFT, 9 YUV, 10 RAW, 11 JPEG, 12 FILEINF,
 * 13 MOVPLAYSOFT, 14 RAW_SUB.
 *
 * Two of those names settle which one is ours.  Audio asks for class 6, and 6
 * is MOVAUDIO.  And the freeze this project spent a week on was movRec's
 * class 10 allocation failing -- 10 is RAW, the CinemaDNG frame buffer.  So the
 * rule "do not take a channel the recorder needs" has a number now: not 10.
 *
 * USER is the generic one, and it is where AutoRun's `memmgr bufmem get` took
 * our own megabyte from, so it is a channel we already know tolerates us.
 *
 * The fifth argument of the get is the CALLER, not a flag: the allocator
 * records it, and `memmgr bufchk` prints it as the ld: column.  Passing zero
 * makes it use the return address, which is what everyone else does. */
.equ MEM_HEAP,       0xC001CF78     /* f(class) -> channel                    */
.equ MEM_GET,        0xC001D038     /* f(channel, size, align, &got, caller)  */
.equ MEM_FREE,       0xC001D2B8     /* f(channel, ptr)                        */
.equ MEM_CLASS,      0              /* USER                                   */

.equ F_MGR,          0xC0444658
.equ F_VOL,          0xC0444698
.equ F_CTOR,         0xC0365E90
.equ F_OPEN,         0xC0365FB0
.equ F_WRITE,        0xC03660E8
.equ F_SEEK,         0xC03661E0     /* what AudioFileWriter::v1 calls when the
                                     * job's offset and its own position
                                     * disagree.  vtable +0x1C, takes the card
                                     * lock like every other media call.      */
.equ F_CLOSE,        0xC0366020
.equ F_DTOR,         0xC0365ED0
.equ F_MODE_RW,      7              /* overwrites; 0x402 fails when it exists */
.equ F_MODE_AUD,     6              /* what AudF_W opens with                 */
/* Where the camera keeps the name of the clip it is about to record.
 * RecordFilePathMgrCinema, one object per volume: +0x08 the camera letter,
 * +0x0C the reel, +0x10 the take it is on, +0x2C the highest it remembers.
 * The saved maximum only counts when AutoRstFlg is clear.  lifecycle.inc.S
 * has been naming the shipping logger's files from these four for months. */
/* The .GYR header, version 7.  Sixty-four bytes, then nothing but records.
 *
 * GFS6 could not carry this stream: it puts a CRC and a count in front of every
 * block and keeps gyro and accel in separate regions, and both of those mean
 * touching the payload.  The payload here goes to the card exactly as the
 * producers left it, so everything the reader needs is in one header at the
 * front and the records are one flat interleaved array behind it.
 *
 *   0x00 "GFS7"      0x04 version     0x08 period_ps    0x0C gscale (float)
 *   0x10 orientation 0x14 clip id (8) 0x1C volume
 *   0x20 payload     0x24 dropped     0x28 sensor mode  0x2C exposure_us
 *   0x30 width       0x34 height      0x38 -            0x3C -
 */
.equ HDR_BYTES,      64
.equ H_MAGIC,        0x00
.equ H_VERSION,      0x04
.equ H_PERIOD_PS,    0x08
.equ H_GSCALE,       0x0C
.equ H_ORIENT,       0x10
.equ H_CLIP,         0x14
.equ H_VOLUME,       0x1C
.equ H_PAYLOAD,      0x20
.equ H_DROPPED,      0x24
.equ H_MODE,         0x28
.equ H_EXPOSURE,     0x2C
.equ H_WIDTH,        0x30
.equ H_HEIGHT,       0x34
.equ GYR_VERSION,    7

/* 400.0854 us, in picoseconds = 2499.466 Hz.
 *
 * Two rulers with nothing in common agreed: a 600 s host-clock count fitted
 * over 21 points gave 2499.520 +/- 0.018 Hz, and 2863 frame intervals measured
 * against the camera's OWN sensor gave 2499.466 -- 0.0021% apart.  The frame
 * ruler is the one written here, because it is the clock the video is on.
 * (They also pin each other: 2499.520 / 83.3989 samples per frame = 29.9709,
 * and 29.97 is 29.97003 -- the frame rate is derived, not assumed.)
 *
 * The old header carried an integer 400 us, fast by 0.085 us on every sample:
 * 3.4 ms of drift across a forty-second take, and it keeps growing. */
.equ GYR_PERIOD_PS,  400085400
.equ GYR_GSCALE,     0x39109F6C     /* 0.000137923 dps per LSB                */
.equ GYR_ORIENT,     0x007A7978     /* "xyz", all three axes negated          */

/* What the take was shot in, for the lens profile.  FUN_c032c720() is what
 * `imager mode_now` prints; FUN_c030c7f0() is the exposure AF consumes.  Both
 * read as nothing useful when idle, so they can only be taken at record start. */
.equ SENSOR_MODE_FN, 0xC032C720
.equ EXPOSURE_FN,    0xC030C7F0
/* The output size, from the camera's own settings rather than a recording-time
 * scratch word.  0xC37CE210 was the obvious-looking source and it is a trap:
 * notes say it holds {1936, 1090, 3244544} at 1080p and reads zero at UHD, and
 * it read zero right through a 35 s take here.  CameraMgrSetting has it while
 * the camera is idle, so there is no race to lose -- FUN_c0206e98() returns the
 * singleton and the live block is at +0x40, .h at +0 and .v at +4.  A
 * CinemaDNG frame is sixteen wider and ten taller than the menu says.
 *
 * This is profilegen.S's pg_setting_dims, bounds and all, because it is the
 * same question and it already had the right answer. */
.equ F_CAMSETTING,   0xC0206E98
.equ SETTING_DIMS,   0x40
.equ DNG_PAD_W,      16
.equ DNG_PAD_H,      10

/* Where the pool is, and what we put in it.  The pool is the camera's DMA
 * buffer -- the firmware allocates it at boot, so its address is only knowable
 * at boot, which is why the release places code there by OFFSET and stage2
 * adds the base.  The three offsets are the deployer's, unchanged, so the card
 * build and the USB build put everything in the same places. */
.equ FRAMEBUF,       0xC3757A7C
.equ CODE_POOL_OFF,  0x44000
.equ JPOOL_POOL_OFF, 0x43000
.equ FOBJ_POOL_OFF,  0x42000

/* The three hook sites and the words that arm them.  Computed here rather than
 * carried as data: the sites and the cave addresses are both build-time
 * constants, so the branch and the code it reaches cannot disagree -- which is
 * exactly how the orientation stub once branched into the middle of the logger. */
.equ ACCEL_SITE,     0xC050D4C8
.equ ACCEL_AT,       0xC072E200
.equ START_SITE,     0xC03790B8
.equ START_AT,       0xC072E4E0
.equ STOP_SITE,      0xC038C484
.equ STOP_AT,        0xC072E620
.equ ARM_ACCEL, 0xEB000000 | (((ACCEL_AT - ACCEL_SITE - 8) >> 2) & 0xFFFFFF)
.equ ARM_START, 0xEB000000 | (((START_AT - START_SITE - 8) >> 2) & 0xFFFFFF)
.equ ARM_STOP,  0xEB000000 | (((STOP_AT  - STOP_SITE  - 8) >> 2) & 0xFFFFFF)

.equ W_VT_BODY,      W_VT + W_VT_SLOT   /* the slot the pool worker calls */
/* The gcsv writer's state, in the gap the space provider left when it moved
 * above the writer words: 0xC072E8F4..0xC072EBA0 is 684 bytes of nothing.
 *
 * G_ROW is `t` -- the sample number, which is the whole of the clock because
 * tscale is the sample period.  Per take, so take_open clears it.
 * G_HELD is one row held back by a record, so a reading can land on the sample
 * it followed; it survives a block boundary because blocks are a card-sized
 * unit and a row is not. */
.equ G_ROW,          0xC072E940
.equ G_HELD,         0xC072E944     /* 8 bytes, then the flag at +8            */
.equ G_HELD_OK,      0xC072E94C
.equ G_TEXT,         0xC072E950     /* the text buffer the block turns into    */
/* The fingerprint of the blob the camera actually holds.  place_code writes
 * it; every command that calls into the pool checks it.  See _verify_placed. */
.equ T_FINGER,       0xC072E954
.equ G_WORDS,        6

/* Where each entry of gsup_offsets is.  blob_at turns one into an address. */
.equ G_OFF_BODY,     0x00
.equ G_OFF_OPEN,     0x04
.equ G_OFF_CLOSE,    0x08
.equ G_OFF_POST,     0x0C
.equ G_OFF_JOBS,     0x10
.equ G_OFF_BLOCKS,   0x14
.equ G_OFF_BOOT,     0x18
.equ G_OFF_PATH,     0x1C
.equ G_OFF_HEADER,   0x20
.equ G_OFF_HEAD1,    0x24
.equ G_OFF_HEAD2,    0x28

/* Where the six fixed-width digits of the drop count sit in the gcsv header.
 * Everything before them is a constant, so the close can rewrite them in place
 * without moving a byte -- the same trick the .GYR header uses. */
.equ NOTE_DROPS_AT,  116
.equ NOTE_DROPS_N,   6

.equ F_CACHE,        0xC000E91C     /* clean+invalidate, so written code is real */

.equ PATH_MGR_SD,    0xC3438400
.equ PATH_MGR_SSD,   0xC3438398
.equ SETTINGS_PTR,   0xC3075230
.equ O_AUTORSTFLG,   0x5D5

.equ F_STAMP,        0xC0369310     /* XC_MediaFileSdCard::v13, vtable +0x3C:
                                     * the call AudF_W makes right after the
                                     * open.  Takes the card lock and stamps  */

.equ T_FOBJ,         0xC072E0F8     /* the file object, placed by the deployer */
.equ T_FOPEN,        0xC072E0FC     /* non-zero once it is open               */
/* T_BYTES and friends used to sit at 0xC072E180, in what was then a gap
 * above the accel hook.  The gate that stops the producers touching the
 * ring when nothing is recording made that hook 140 bytes and took the gap
 * back, so the five counters moved to 0xC072E8E0 -- beside the accel
 * measurement block, in cave nothing else claims.  Moving the counters was
 * the cheap half of that choice: moving the hook instead would have changed
 * which addresses we write, which is exactly the variable a freeze
 * postmortem cannot afford. */
/* How much of take_open to run.  The build is five steps and they cannot be
 * told apart from outside once the camera is down -- a full freeze takes USB
 * with it, so W_STAGE is unreadable afterwards.  This is the same ladder idea
 * one level in: one word, no rebuild, no reboot between tries.
 *
 *   1  the blocks, from the allocator
 *   2  + the file: F_CTOR, F_OPEN, the stamp
 *   3  + the mailbox
 *   4  + the thread, built but not attached
 *   5  + attached and running        (the whole thing)
 */
.equ T_BUILD,        0xC072EC54
.equ T_TEARDOWN,     0xC072EC58     /* 0 = take_close does nothing and leaves
                                     * the take standing for the shell to
                                     * dismantle later.  Splits "open at
                                     * record start" from "close at record
                                     * stop", which are the two halves of
                                     * the smallest step and froze together. */

.equ T_JSEQ,         0xC072EC48     /* jobs posted, so a dump can see order   */
.equ T_JOBSLOT,      0xC072EC4C     /* where MBX_RECV leaves the descriptor   */
.equ T_STAGE,        0xC072E198     /* how far the close got.  A wedge that
                                     * leaves a number behind is a bisect; one
                                     * that leaves nothing is another reboot
                                     * spent guessing. */
.equ T_WANT,         0xC072EC50     /* 1 = a take wants the file, 0 = it does
                                     * not.  The recording hooks set this and
                                     * nothing else: opening a file is far too
                                     * heavy for a firmware callback, and those
                                     * two contexts have never been shown safe
                                     * for a syscall.  The writer reconciles it
                                     * on its next wake, at most a doorbell
                                     * away -- about 400 ms, against a ring
                                     * that holds 6.6 seconds. */
.equ T_BYTES,        0xC072E8E0     /* in the gap between the accel hook and
                                     * the stream's own words; the accel hook
                                     * grew into 0xC072E140 when the ring base
                                     * became a variable.                    */     /* bytes written                          */
.equ T_WRITES,       0xC072E8E4     /* F_WRITE calls                          */
.equ T_WRC,          0xC072E8E8     /* what the last one returned             */
.equ T_LOST,         0xC072E8EC     /* records overwritten before we took them.
                                     * The one number that says the ring is
                                     * too shallow; it must stay zero.       */
.equ T_WRAPS,        0xC072E8F0     /* spans that had to be split at the end  */     /* what the mailbox create returned       */
.equ T_DRAINED,      0xC072E0C8     /* records the writer has taken           */
.equ T_MAXSPAN,      0xC072E0CC     /* the largest it ever found waiting.  If
                                     * this approaches the ring's capacity the
                                     * writer is falling behind, which is the
                                     * one failure the depth is there to stop
                                     * and the one number that says so.      */     /* what the mailbox create returned       */
