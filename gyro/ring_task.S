.syntax unified
.arm

#include "ring_task.inc.S"
#include "imu_stream.inc.S"

/* ------------------------------------------------------------------ task */

/* There is no hand-written wrapper any more.
 *
 * FUN_c036efe8, the firmware's own pool worker, is the wrapper: it sleeps,
 * calls slot +0xC of whatever object it has been handed, and when that call
 * RETURNS it sets the completion flag and sleeps again.  writer_body is that
 * slot.  Everything the hand-written writer_entry did -- the flag, the parking,
 * being terminated from outside -- the firmware now does, exactly as it does it
 * for AudF_W.
 */

/* The body.  AudioFileWriter::v1 @0xC01FBD40, instruction for instruction:
 *
 *     while (true) {
 *         rcv_mbx(mbx, &msg, TMO_FEVR);
 *         if (msg->stop) break;
 *         F_WRITE(file, msg->ptr, msg->len);
 *         release(msg);
 *     }
 *     release(msg);
 *
 * It does not open the file and it does not close it.  The file was open before
 * this task existed and is closed after it has finished, both by whoever built
 * the take -- which is what the return is for.
 */
writer_body:
    push    {r4, lr}

1:  movw    r0, #:lower16:T_MBX
    movt    r0, #:upper16:T_MBX
    ldr     r0, [r0]
    cmp     r0, #0
    beq     8f
    movw    r1, #:lower16:T_JOBSLOT
    movt    r1, #:upper16:T_JOBSLOT
    mvn     r2, #0                      @ TMO_FEVR
    movw    ip, #:lower16:MBX_RECV
    movt    ip, #:upper16:MBX_RECV
    blx     ip

    /* An error return would spin this loop at priority 6, which starves the
     * camera.  Leaving is now a real option -- the wrapper above catches it --
     * so leave, with the reason in a word. */
    cmp     r0, #0
    bne     8f

    movw    ip, #:lower16:T_WAKES
    movt    ip, #:upper16:T_WAKES
    ldr     r1, [ip]
    add     r1, r1, #1
    str     r1, [ip]

    movw    ip, #:lower16:T_JOBSLOT
    movt    ip, #:upper16:T_JOBSLOT
    ldr     r4, [ip]
    cmp     r4, #0
    beq     1b

    ldr     r0, [r4, #J_STOP]
    cmp     r0, #0
    bne     3f

    ldr     r2, [r4, #J_LEN]
    cmp     r2, #0
    beq     2f
    bl      writer_put                  @ r4 = the job
2:  bl      writer_release
    b       1b

3:  bl      writer_release
    pop     {r4, lr}
    bx      lr

8:  movw    ip, #:lower16:T_RECV_RC
    movt    ip, #:upper16:T_RECV_RC
    str     r0, [ip]
    pop     {r4, lr}
    bx      lr

/* Build the job pool's free list.  Called once, through the borrowed shell
 * handler, before anything can take a descriptor. */
    .global mpool_init_jobs
mpool_init_jobs:
    push    {r4, lr}
    movw    r0, #:lower16:STREAM_JPOOL
    movt    r0, #:upper16:STREAM_JPOOL
    ldr     r0, [r0]
    cmp     r0, #0
    beq     9f
    mov     r1, #J_SIZE
    mov     r2, #JOB_COUNT
    bl      mpool_init
9:  pop     {r4, lr}
    bx      lr

/* --------------------------------------------------------------- posting */

/* writer_post(r0 = the first record of the buffer that just filled).
 *
 * stream_commit calls this and nothing else does.  There is no span to work
 * out, no threshold to compare against, no backlog to bound and no wrap to
 * split: a buffer is a fixed length, it tiles the ring exactly, and it is
 * whole by the time this runs.  Everything that used to be here -- POSTED, the
 * chunk cap, the LOST accounting, the second job for the part that ran past the
 * end -- existed to make a threshold poll behave, and the poll is gone.
 */
    .global writer_post
writer_post:
    push    {r4, r5, r6, r7, ip, lr}
    mov     r4, r0

    movw    r0, #:lower16:T_FOPEN
    movt    r0, #:upper16:T_FOPEN
    ldr     r0, [r0]
    cmp     r0, #0
    beq     9f                          @ no file yet: this buffer is dropped,
                                        @ and J_OFF will leave its hole behind

    movw    r5, #:lower16:STREAM_RING
    movt    r5, #:upper16:STREAM_RING
    ldr     r5, [r5]
    cmp     r5, #0
    beq     9f

    movw    r6, #:lower16:RING_MASK
    movt    r6, #:upper16:RING_MASK
    and     r6, r4, r6
    add     r1, r5, r6, lsl #3          @ where the buffer starts, in the ring

    movw    r2, #:lower16:BUF_BYTES
    movt    r2, #:upper16:BUF_BYTES

    movw    r3, #:lower16:STREAM_TAIL
    movt    r3, #:upper16:STREAM_TAIL
    ldr     r3, [r3]
    sub     r3, r4, r3
    lsl     r3, r3, #3                  @ where it belongs in the file

    mov     r0, #0                      @ not a stop
    bl      writer_make_job

9:  pop     {r4, r5, r6, r7, ip, lr}
    bx      lr

/* writer_make_job(r0 = stop flag, r1 = ptr, r2 = len) -> r0 = 1 posted, 0 not.
 * Clobbers r0-r3, ip. */
writer_make_job:
    /* Eight: r6 carries the length across the allocation, so nothing has to be
     * pushed mid-routine.  Two single pushes to "keep it even" leave the stack
     * misaligned between them, which is the shape that has already frozen this
     * camera once. */
    push    {r1, r2, r3, r4, r5, r6, r7, lr}
    mov     r4, r0
    mov     r5, r1
    mov     r6, r2
    mov     r7, r3                      @ where in the file it belongs

    movw    r0, #:lower16:STREAM_JPOOL
    movt    r0, #:upper16:STREAM_JPOOL
    ldr     r0, [r0]
    bl      mpool_alloc
    cmp     r0, #0
    beq     8f                          @ pool empty: the caller retries later

    str     r7, [r0, #J_OFF]
    str     r5, [r0, #J_PTR]
    str     r6, [r0, #J_LEN]
    str     r4, [r0, #J_STOP]
    movw    ip, #:lower16:T_JSEQ
    movt    ip, #:upper16:T_JSEQ
    ldr     r1, [ip]
    str     r1, [r0, #J_SEQ]
    add     r1, r1, #1
    str     r1, [ip]

    mov     r1, r0                      @ the message is the descriptor
    movw    r0, #:lower16:T_MBX
    movt    r0, #:upper16:T_MBX
    ldr     r0, [r0]
    cmp     r0, #0
    beq     8f
    movw    ip, #:lower16:MBX_SEND
    movt    ip, #:upper16:MBX_SEND
    blx     ip
    mov     r0, #1
    pop     {r1, r2, r3, r4, r5, r6, r7, lr}
    bx      lr

8:  mov     r0, #0
    pop     {r1, r2, r3, r4, r5, r6, r7, lr}
    bx      lr

/* -------------------------------------------------------------- reconcile */

/* Give a descriptor back, and the queue slot with it. */
writer_release:
    push    {r0, r1, r2, r3, ip, lr}
    movw    r0, #:lower16:STREAM_JPOOL
    movt    r0, #:upper16:STREAM_JPOOL
    ldr     r0, [r0]
    movw    r1, #:lower16:T_JOBSLOT
    movt    r1, #:upper16:T_JOBSLOT
    ldr     r1, [r1]
    bl      mpool_free
    pop     {r0, r1, r2, r3, ip, lr}
    bx      lr

/* The ring-walking drain that came before the job queue is gone.  It read the
 * ring's indices and decided what to write; in the audio shape the producer
 * decides that and the writer only carries out what a job says.  Keeping both
 * would have been two owners of the same tail. */

/* writer_put(r4 = the job).  AudioFileWriter::v1's two branches.
 *
 * If the job says it belongs exactly where the file already is, write straight
 * through.  If it does not -- which means a job in between never made it --
 * seek to where it says first, so the gap stays a gap of the right size instead
 * of every later record sliding earlier.
 */
writer_put:
    push    {r4, r5, r6, lr}
    movw    r5, #:lower16:T_POS
    movt    r5, #:upper16:T_POS
    ldr     r6, [r5]
    ldr     r0, [r4, #J_OFF]
    cmp     r6, r0
    beq     2f

#ifndef DRY_RUN
    movw    r1, #:lower16:T_FOBJ
    movt    r1, #:upper16:T_FOBJ
    ldr     r1, [r1]
    mov     r2, r0
    mov     r0, r1
    mov     r1, r2
    mov     r2, #0                      @ from the start of the file
    movw    ip, #:lower16:F_SEEK
    movt    ip, #:upper16:F_SEEK
    blx     ip
#endif
    movw    ip, #:lower16:T_SEEKS
    movt    ip, #:upper16:T_SEEKS
    ldr     r0, [ip]
    add     r0, r0, #1
    str     r0, [ip]                    @ every one of these is a job that was lost
    ldr     r0, [r4, #J_OFF]

2:  ldr     r2, [r4, #J_LEN]
    add     r0, r0, r2
    str     r0, [r5]                    @ where the file is once this lands

#ifndef DRY_RUN
    ldr     r1, [r4, #J_PTR]
    movw    r0, #:lower16:T_FOBJ
    movt    r0, #:upper16:T_FOBJ
    ldr     r0, [r0]
    movw    ip, #:lower16:F_WRITE
    movt    ip, #:upper16:F_WRITE
    blx     ip
    movw    ip, #:lower16:T_WRC
    movt    ip, #:upper16:T_WRC
    str     r0, [ip]
#else
    /* Everything except the card.  The path is otherwise identical -- the same
     * post, the same descriptor, the same mailbox, the same wake, the same
     * release -- so a run that survives here and dies without the flag has
     * narrowed the trouble to the card calls and nothing else. */
    movw    ip, #:lower16:T_WRC
    movt    ip, #:upper16:T_WRC
    mov     r0, #1
    str     r0, [ip]
#endif
    ldr     r2, [r4, #J_LEN]
    movw    ip, #:lower16:T_BYTES
    movt    ip, #:upper16:T_BYTES
    ldr     r0, [ip]
    add     r0, r0, r2
    str     r0, [ip]
    movw    ip, #:lower16:T_WRITES
    movt    ip, #:upper16:T_WRITES
    ldr     r0, [ip]
    add     r0, r0, #1
    str     r0, [ip]
    pop     {r4, r5, r6, lr}
    bx      lr

/* The mailbox, exactly as FUN_c036d8e0 makes audio's: exinf 0, attr 1, and a
 * name the kernel ignores because TA_DSNAME is not set.  Nothing else is built
 * here -- the thread belongs to XC_Thread.cpp now. */
    .global make_writer
make_writer:
    push    {r4, lr}
    movw    r4, #:lower16:T_PKT
    movt    r4, #:upper16:T_PKT
    mov     r0, #0
    str     r0, [r4]                    @ exinf
    mov     r1, #1
    str     r1, [r4, #4]                @ mbxatr
    str     r0, [r4, #8]
    str     r0, [r4, #12]
    mov     r0, r4
    movw    ip, #:lower16:MBX_CREATE
    movt    ip, #:upper16:MBX_CREATE
    blx     ip
    movw    r1, #:lower16:T_MBX_RC
    movt    r1, #:upper16:T_MBX_RC
    str     r0, [r1]
    cmp     r0, #0
    ble     9f
    movw    r1, #:lower16:T_MBX
    movt    r1, #:upper16:T_MBX
    str     r0, [r1]
9:  pop     {r4, lr}
    bx      lr


/* ------------------------------------------------------------- the take */

/* Build a take, in AudF_W's order (@0xC01FD380):
 *
 *     F_CTOR(file, volume)
 *     FUN_c036e108(&thread, 6, 0x2000, "AudF_W")   -- built, not running
 *     tk_cre_mbx
 *     F_OPEN(file, path, 6)
 *     stamp the file
 *     FUN_c036e1b8(&thread, this)                  -- attach and wake
 *
 * The one departure from that order is that F_CTOR and F_OPEN happen together
 * here, before the thread is built rather than around it.  Nothing observes the
 * difference: the thread does not run until the attach, which is last either
 * way.  Splitting our open in two to match the line order would add a failure
 * path for no behaviour.
 */
    .global take_open
take_open:
    push    {r4, r5, r6, lr}
    movw    r4, #:lower16:W_STAGE
    movt    r4, #:upper16:W_STAGE
    mov     r0, #0x01
    str     r0, [r4]

    movw    r0, #:lower16:T_FOPEN
    movt    r0, #:upper16:T_FOPEN
    ldr     r0, [r0]
    cmp     r0, #0
    bne     9f                          @ a take is already built

    bl      writer_openfile
    movw    r0, #:lower16:T_FOPEN
    movt    r0, #:upper16:T_FOPEN
    ldr     r0, [r0]
    cmp     r0, #0
    mov     r0, #0x02
    str     r0, [r4]                    @ neither mov nor str touches the flags
    beq     9f

    movw    r0, #:lower16:T_POS
    movt    r0, #:upper16:T_POS
    mov     r1, #0
    str     r1, [r0]                    @ a fresh file starts at byte zero
    movw    r0, #:lower16:T_SEEKS
    movt    r0, #:upper16:T_SEEKS
    str     r1, [r0]

    bl      make_writer                 @ the mailbox
    movw    r0, #:lower16:T_MBX
    movt    r0, #:upper16:T_MBX
    ldr     r0, [r0]
    cmp     r0, #0
    mov     r0, #0x03
    str     r0, [r4]
    ble     9f

    /* The object the pool worker will call.  Its whole interface is slot +0xC
     * of the vtable its first word points at, so this is the whole class: one
     * word, and a table the deployer put writer_body into. */
    movw    r0, #:lower16:W_BODYOBJ
    movt    r0, #:upper16:W_BODYOBJ
    movw    r1, #:lower16:W_VT
    movt    r1, #:upper16:W_VT
    str     r1, [r0]

    movw    r0, #:lower16:W_THREAD
    movt    r0, #:upper16:W_THREAD
    mov     r1, #WRITER_PRI
    movw    r2, #WRITER_STKSZ
    adr     r3, writer_name
    movw    ip, #:lower16:XT_CREATE
    movt    ip, #:upper16:XT_CREATE
    blx     ip
    mov     r0, #0x04
    str     r0, [r4]

    movw    r0, #:lower16:W_THREAD
    movt    r0, #:upper16:W_THREAD
    ldr     r1, [r0]
    cmp     r1, #0
    beq     9f                          @ the pool refused: leave it unstarted
    movw    r1, #:lower16:W_BODYOBJ
    movt    r1, #:upper16:W_BODYOBJ
    ldr     r1, [r1]
    movw    ip, #:lower16:XT_ATTACH
    movt    ip, #:upper16:XT_ATTACH
    blx     ip                          @ the writer is running from here

    mov     r0, #0x05
    str     r0, [r4]
    movw    r0, #:lower16:W_OPENS
    movt    r0, #:upper16:W_OPENS
    ldr     r1, [r0]
    add     r1, r1, #1
    str     r1, [r0]

9:  pop     {r4, r5, r6, lr}
    bx      lr


/* Tear a take down, in AudioFileRecordingObserver::v0's order (@0xC01FBB18):
 *
 *     post the stop job     -- through the SAME queue as every write
 *     FUN_c036e1f8(&thread) -- wait for the body to return
 *     the file's destructor -- close, and only now
 *     FUN_c036e168(&thread, 2) -- wake, terminate, delete, delete the flag
 *
 * The join is the firmware's, so it is TMO_FEVR, as audio's is.  The one guard
 * is above it: if the stop job could not be posted there is nothing to wait
 * for, and waiting anyway would hang the recorder's task for ever.
 */
    .global take_close
take_close:
    push    {r4, r5, r6, lr}
    movw    r4, #:lower16:W_STAGE
    movt    r4, #:upper16:W_STAGE
    mov     r0, #0x11
    str     r0, [r4]

    movw    r0, #:lower16:T_FOPEN
    movt    r0, #:upper16:T_FOPEN
    ldr     r0, [r0]
    cmp     r0, #0
    beq     9f

    mov     r0, #1                      @ J_STOP
    mov     r1, #0
    mov     r2, #0
    mov     r3, #0
    bl      writer_make_job
    cmp     r0, #0
    mov     r0, #0x12
    str     r0, [r4]
    beq     9f                          @ never posted: nothing to wait for

    movw    r5, #:lower16:W_THREAD
    movt    r5, #:upper16:W_THREAD
    ldr     r0, [r5]
    cmp     r0, #0
    beq     3f
    mov     r0, r5
    movw    ip, #:lower16:XT_JOIN
    movt    ip, #:upper16:XT_JOIN
    blx     ip
3:  mov     r0, #0x13
    str     r0, [r4]

    bl      writer_closefile
    mov     r0, #0x14
    str     r0, [r4]

    ldr     r0, [r5]
    cmp     r0, #0
    beq     4f
    mov     r0, r5
    mov     r1, #2                      @ do not delete the holder: it is ours
    movw    ip, #:lower16:XT_DESTROY
    movt    ip, #:upper16:XT_DESTROY
    blx     ip
    mov     r0, #0
    str     r0, [r5]
4:  mov     r0, #0x15
    str     r0, [r4]

    movw    r5, #:lower16:T_MBX
    movt    r5, #:upper16:T_MBX
    ldr     r0, [r5]
    cmp     r0, #0
    ble     5f
    movw    ip, #:lower16:MBX_DELETE
    movt    ip, #:upper16:MBX_DELETE
    blx     ip
    mov     r0, #0
    str     r0, [r5]

5:  mov     r0, #0x16
    str     r0, [r4]
    movw    r0, #:lower16:W_CLOSES
    movt    r0, #:upper16:W_CLOSES
    ldr     r1, [r0]
    add     r1, r1, #1
    str     r1, [r0]

9:  pop     {r4, r5, r6, lr}
    bx      lr

    .align  2
writer_name:
    .asciz  "GYRW"
    .space  3
    .align  2


/* ------------------------------------------------------------- the file */

/* Open the file the ring drains into.  The same six calls the logger and the
 * audio writer both make, in the same order:
 *
 *     F_MGR()          the media manager
 *     F_VOL(mgr, 0)    the volume it is currently writing to
 *     F_CTOR(obj, vol) build the file object
 *     F_OPEN(obj, path, mode)
 *
 * Mode 7 overwrites; 0x402 fails when the file already exists, which is a
 * latent bug rather than a safety feature.
 *
 * If the open fails the object is destroyed.  A file object left constructed
 * wedges the file system -- that is what happened to \LENS.DAT, which nothing
 * could open again until the camera was power cycled.
 */
    .global writer_openfile
writer_openfile:
    push    {r4, r5, r6, lr}
#ifdef DRY_RUN
    /* No file object is built and nothing touches the volume.  T_FOPEN is what
     * every other decision reads, so setting it is enough to make the rest of
     * the machinery behave exactly as it would with a real file. */
    movw    ip, #:lower16:T_FOPEN
    movt    ip, #:upper16:T_FOPEN
    mov     r0, #1
    str     r0, [ip]
    pop     {r4, r5, r6, lr}
    bx      lr
#endif
    movw    r4, #:lower16:T_FOBJ
    movt    r4, #:upper16:T_FOBJ
    ldr     r4, [r4]
    cmp     r4, #0
    beq     9f

    movw    ip, #:lower16:F_MGR
    movt    ip, #:upper16:F_MGR
    blx     ip
    mov     r1, #0
    movw    ip, #:lower16:F_VOL
    movt    ip, #:upper16:F_VOL
    blx     ip
    mov     r1, r0
    mov     r0, r4
    movw    ip, #:lower16:F_CTOR
    movt    ip, #:upper16:F_CTOR
    blx     ip

    mov     r0, r4
    adr     r1, writer_path
    mov     r2, #F_MODE_AUD             @ 6, the mode AudF_W opens with
    movw    ip, #:lower16:F_OPEN
    movt    ip, #:upper16:F_OPEN
    blx     ip
    movw    ip, #:lower16:T_FOPEN
    movt    ip, #:upper16:T_FOPEN
    str     r0, [ip]
    cmp     r0, #0
    beq     8f

    /* What AudF_W does next, and we did not: XC_MediaFileSdCard::v13, vtable
     * +0x3C, which takes the card lock and stamps the file.  Copied because the
     * instruction is to copy, and because a file the firmware has stamped is a
     * file the firmware's own bookkeeping has seen. */
    mov     r0, r4
    movw    ip, #:lower16:F_STAMP
    movt    ip, #:upper16:F_STAMP
    blx     ip

    /* The tail is NOT touched here.  Whoever asked for the file to be opened
     * decides where the take starts: the record hook latches it at the instant
     * recording begins. */
    b       9f

8:

    mov     r0, r4                      @ it did not open: do not leave it built
    mov     r1, #2
    movw    ip, #:lower16:F_DTOR
    movt    ip, #:upper16:F_DTOR
    blx     ip

9:  pop     {r4, r5, r6, lr}
    bx      lr

/* Take whatever is still in the ring, then close.  Draining first is not a
 * nicety: the last span of a take is the one a stop path most easily loses. */
    .global writer_closefile
writer_closefile:
    push    {r4, r5, r6, lr}
    movw    r6, #:lower16:T_STAGE
    movt    r6, #:upper16:T_STAGE
    mov     r0, #0x21
    str     r0, [r6]                    @ entered

    movw    r4, #:lower16:T_FOPEN
    movt    r4, #:upper16:T_FOPEN
    ldr     r5, [r4]
    cmp     r5, #0
    beq     9f
#ifdef DRY_RUN
    mov     r0, #0
    str     r0, [r4]                    @ nothing was opened; nothing to close
    mov     r0, #0x25
    str     r0, [r6]                    @ the stage the real path ends on
    pop     {r4, r5, r6, lr}
    bx      lr
#endif

    /* No drain here.  Everything of this take was written as jobs, and the
     * stop job came out of the queue behind all of them -- draining again
     * would write the whole ring a second time. */
    mov     r0, #0x23
    str     r0, [r6]                    @ about to close

    movw    r6, #:lower16:T_FOBJ
    movt    r6, #:upper16:T_FOBJ
    ldr     r6, [r6]                    @ r6 stops being T_STAGE here
    mov     r0, r6
    movw    ip, #:lower16:F_CLOSE
    movt    ip, #:upper16:F_CLOSE
    blx     ip
    movw    ip, #:lower16:T_STAGE
    movt    ip, #:upper16:T_STAGE
    mov     r0, #0x24
    str     r0, [ip]                    @ closed, about to destroy
    mov     r0, r6
    mov     r1, #2
    movw    ip, #:lower16:F_DTOR
    movt    ip, #:upper16:F_DTOR
    blx     ip
    movw    ip, #:lower16:T_STAGE
    movt    ip, #:upper16:T_STAGE
    mov     r0, #0x25
    str     r0, [ip]                    @ destroyed, all the way through
    mov     r0, #0
    str     r0, [r4]

9:  pop     {r4, r5, r6, lr}
    bx      lr

/* ------------------------------------------------------------- self test */

/* Open, write one small span straight out of the ring, close -- all in the
 * caller's context.  Fired through the borrowed shell handler, this separates
 * the two things the priority 6 task does at once:
 *
 *     if this works, F_WRITE with a pointer into the pool ring is fine and the
 *     problem is the task -- its stack, or its context;
 *     if this wedges, the write itself is the problem and the task is innocent.
 *
 * Every result goes in a word before the next step runs, so a wedge still says
 * how far it got.
 */
    .global writer_selftest
writer_selftest:
    push    {r4, r5, r6, lr}

    movw    r4, #:lower16:T_WRC
    movt    r4, #:upper16:T_WRC
    mov     r0, #0x11
    str     r0, [r4]                    @ reached the entry

    bl      writer_openfile
    movw    r5, #:lower16:T_FOPEN
    movt    r5, #:upper16:T_FOPEN
    ldr     r5, [r5]
    cmp     r5, #0
    moveq   r0, #0x12                   @ the open failed
    streq   r0, [r4]
    beq     9f
    mov     r0, #0x13
    str     r0, [r4]                    @ open done, about to write

    movw    r6, #:lower16:STREAM_RING
    movt    r6, #:upper16:STREAM_RING
    ldr     r6, [r6]
    cmp     r6, #0
    moveq   r0, #0x14
    streq   r0, [r4]
    beq     8f

    mov     r1, r6                      @ straight out of the ring
    movw    r2, #1024
    movw    r0, #:lower16:T_FOBJ
    movt    r0, #:upper16:T_FOBJ
    ldr     r0, [r0]
    movw    ip, #:lower16:F_WRITE
    movt    ip, #:upper16:F_WRITE
    blx     ip
    mov     r1, r0
    mov     r0, #0x15
    str     r0, [r4]                    @ the write returned
    movw    r0, #:lower16:T_BYTES
    movt    r0, #:upper16:T_BYTES
    str     r1, [r0]                    @ ... and this is what it said

8:  bl      writer_closefile
    mov     r0, #0x16
    str     r0, [r4]                    @ closed, all the way through

9:  pop     {r4, r5, r6, lr}
    mov     r0, #0
    bx      lr

    .align  2
/* The path.  Reserved long enough for the deployer to write a different name
 * over it: mode 7 does NOT truncate on this camera whatever the tools say, so
 * a fixed name accumulates every session's writes on top of each other and the
 * file stops being one stream.  A take needs its own file -- which the real
 * logger does per clip anyway. */
writer_path:
    .asciz  "\\GYRO\\RINGTEST.BIN"
    .space  12
    .align  2

/* The job pool, in the same blob so the calls resolve without a relocation
 * the loader here cannot apply. */
#include "mpool.S"
