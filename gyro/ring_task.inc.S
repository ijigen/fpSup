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

.equ TMO_FEVR,       -1

/* Descriptor for tk_cre_tsk, 32 bytes.  itskpri must be 1..32 and stksz at
 * least 0x100, or it returns E_PAR (-17). */
.equ D_EXINF,        0x00
.equ D_TSKATR,       0x04           /* 0x41                                   */
.equ D_TASK,         0x08           /* direct ARM entry                       */
.equ D_ITSKPRI,      0x0C
.equ D_STKSZ,        0x10
.equ D_DSNAME,       0x14           /* eight bytes                            */

.equ WRITER_PRI,     6              /* what AudF_W and SRecFile run at        */
.equ WRITER_STKSZ,   0x2000         /* what AudF_W asks for                   */

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
.equ T_DRAINED,      0xC072E0C8     /* records the writer has taken           */
.equ T_MAXSPAN,      0xC072E0CC     /* the largest it ever found waiting.  If
                                     * this approaches the ring's capacity the
                                     * writer is falling behind, which is the
                                     * one failure the depth is there to stop
                                     * and the one number that says so.      */     /* what the mailbox create returned       */
