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
.equ WRITER_STKSZ,   0x4000         /* AudF_W asks for 0x2000, but SRecFile --
                                     * the VIDEO file writer, which pushes far
                                     * more through the same XC_MediaFile --
                                     * asks for 0x4000.  The SD path is deep
                                     * and 8 KiB is the cheaper thing to be
                                     * wrong about.                          */

/* The take's own objects.  Audio builds file, thread and mailbox together at
 * record start and destroys all three at stop; these are the words that hold
 * them for one take.  Above everything else in the cave, clear of the
 * measuring accel build at 0xC072E900..0xC072EA04. */
.equ W_FLG,          0xC072EA10     /* the completion flag id                 */
.equ W_FLGRC,        0xC072EA14     /* what tk_cre_flg returned               */
.equ W_JOINRC,       0xC072EA18     /* what the join returned                 */
.equ W_TERRC,        0xC072EA1C
.equ W_DELRC,        0xC072EA20
.equ W_OPENS,        0xC072EA24     /* takes built                            */
.equ W_CLOSES,       0xC072EA28     /* takes torn down                        */
.equ W_STAGE,        0xC072EA2C     /* how far the build or the teardown got  */
.equ W_PKT,          0xC072EA40     /* 32 bytes, the T_CFLG                   */
.equ W_SCRATCH,      0xC072EA60     /* where tk_wai_flg leaves the pattern    */

/* Placed by the deployer, the way STREAM_SIGFN is: the record hooks live in the
 * cave and these live in the pool, so the address is only known at deploy. */
.equ T_OPENFN,       0xC072EA64     /* -> take_open                           */
.equ T_CLOSEFN,      0xC072EA68     /* -> take_close                          */

/* Below the accel hook, clear of the stream's own words at 0xC072E1B0. */
.equ T_DESC,         0xC072E080     /* 32 bytes, the task descriptor          */
.equ T_PKT,          0xC072E0A0     /* 32 bytes, the mailbox message.  Real
                                     * memory, because the kernel links it.   */
.equ T_DOOR,         0xC072E0C0     /* 0 = the doorbell is not ringing.  The
                                     * message says only "there is work"; the
                                     * work itself is the ring's indices, so a
                                     * second message while one is queued would
                                     * buy nothing and would need a second
                                     * packet.                                */
.equ T_MBX,          0xC072E0C4     /* the mailbox id                         */

.equ T_ID,           0xC072E0D0     /* the task id                            */
.equ T_CRE_RC,       0xC072E0D4
.equ T_STA_RC,       0xC072E0D8
.equ T_WAKES,        0xC072E0DC     /* times the task woke                    */
.equ T_SIGNALS,      0xC072E0E0     /* times a producer rang the doorbell     */
.equ T_ENTRY,        0xC072E0E4     /* the task body, placed by the deployer  */
.equ T_RECV_RC,      0xC072E0E8     /* what receive returned when it stopped
                                     * returning zero                         */
.equ T_MBX_RC,       0xC072E0EC     /* what the mailbox create returned       */

/* ---- the card write ---------------------------------------------------- */

/* The same file object the audio writer uses.  XC_MediaFile::Write is where
 * every write on this camera funnels through, and it takes and releases the one
 * non-preemptible card lock, so writing from here is writing exactly the way
 * audio does.  F_WRITE(object, source, length) -- the source is a pointer, and
 * ours points straight into the ring.  Nothing is copied. */
.equ F_MGR,          0xC0444658
.equ F_VOL,          0xC0444698
.equ F_CTOR,         0xC0365E90
.equ F_OPEN,         0xC0365FB0
.equ F_WRITE,        0xC03660E8
.equ F_CLOSE,        0xC0366020
.equ F_DTOR,         0xC0365ED0
.equ F_MODE_RW,      7              /* overwrites; 0x402 fails when it exists */
.equ F_MODE_AUD,     6              /* what AudF_W opens with                 */
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
.equ T_STOPSENT,     0xC072E15C     /* one stop job per take, not one a wake  */
.equ T_JSEQ,         0xC072E160     /* jobs posted, so a dump can see order   */
.equ T_JOBSLOT,      0xC072E164     /* where MBX_RECV leaves the descriptor   */
.equ T_STAGE,        0xC072E198     /* how far the close got.  A wedge that
                                     * leaves a number behind is a bisect; one
                                     * that leaves nothing is another reboot
                                     * spent guessing. */
.equ T_WANT,         0xC072E194     /* 1 = a take wants the file, 0 = it does
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
