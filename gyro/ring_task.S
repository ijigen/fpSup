.syntax unified
.arm

#include "ring_task.inc.S"
#include "imu_stream.inc.S"

/* ------------------------------------------------------------------ task */

    .global writer_task
writer_task:
    /* r0 = exinf.  Never returns: tk_ext_tsk is not isolated in this firmware
     * (notes/TASK_ABI_VERIFIED.md), so a task here lives for the session. */
1:  movw    r0, #:lower16:T_MBX
    movt    r0, #:upper16:T_MBX
    ldr     r0, [r0]
    movw    r1, #:lower16:T_JOBSLOT
    movt    r1, #:upper16:T_JOBSLOT
    mvn     r2, #0                      @ TMO_FEVR
    movw    ip, #:lower16:MBX_RECV
    movt    ip, #:upper16:MBX_RECV
    blx     ip

    /* An error return would otherwise spin this loop at priority 6, which
     * starves the whole camera and costs a battery pull.  There is no way to
     * exit a task, so the backstop parks in a long delay instead, leaving the
     * reason readable and the camera alive. */
    cmp     r0, #0
    bne     8f

    movw    ip, #:lower16:T_WAKES
    movt    ip, #:upper16:T_WAKES
    ldr     r1, [ip]
    add     r1, r1, #1
    str     r1, [ip]

    /* Open the file if a take has asked for one.  This runs before the job is
     * looked at, so the empty job a producer sends to knock finds a file
     * already open by the time anything needs to be written. */
    bl      writer_reconcile

    /* The message IS the job.  Write what it says, then give the descriptor
     * back -- which is also giving the queue slot back.  This is the whole of
     * the audio writer's loop, and it looks at nothing else: not the ring's
     * indices, not a flag on the side. */
    movw    ip, #:lower16:T_JOBSLOT
    movt    ip, #:upper16:T_JOBSLOT
    ldr     r4, [ip]
    cmp     r4, #0
    beq     1b

    ldr     r0, [r4, #J_STOP]
    cmp     r0, #0
    bne     3f

    ldr     r1, [r4, #J_PTR]
    ldr     r2, [r4, #J_LEN]
    cmp     r2, #0
    beq     2f
    bl      writer_put
2:  bl      writer_release
    b       1b

    /* The stop job.  Everything posted before it has been written, because it
     * came through the same queue behind them. */
3:  bl      writer_release
    bl      writer_closefile
    b       1b

8:  movw    ip, #:lower16:T_RECV_RC
    movt    ip, #:upper16:T_RECV_RC
    str     r0, [ip]
9:  movw    r0, #1000
    movw    ip, #:lower16:TK_DLY_TSK
    movt    ip, #:upper16:TK_DLY_TSK
    blx     ip
    b       9b

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

/* Hand the writer everything the producers have added since last time, as jobs.
 *
 * This is the audio path's shape exactly: the PRODUCER side works out what is
 * ready, takes a descriptor per contiguous piece, fills in a pointer and a
 * length, and sends it.  The writer never looks at the ring's indices -- it
 * writes what it was handed and frees the descriptor.  A span that runs over
 * the end of the ring is two jobs, which is how audio expresses it too.
 *
 * The pool is the queue.  When it is empty there is nothing to post with, so
 * the records simply stay in the ring and the next call carries a bigger span;
 * mpool counts the refusal, and that count is the back-pressure signal.
 *
 * Called from the gyro producer -- task context, where a syscall is proven
 * safe.  The Vd hook is an interrupt and never comes here.
 */
    .global writer_post
writer_post:
    push    {r4, r5, r6, r7, r8, r9, r10, lr}

    movw    r4, #:lower16:STREAM_JPOOL
    movt    r4, #:upper16:STREAM_JPOOL
    ldr     r4, [r4]
    cmp     r4, #0
    beq     9f                          @ no pool yet

    /* No file yet, but one is wanted: post an empty job purely to wake the
     * writer, which opens it before it looks at what the job says.  Without
     * this the two sides deadlock -- the writer blocks until a job arrives,
     * and nothing posts a job until the file is open. */
    movw    ip, #:lower16:T_FOPEN
    movt    ip, #:upper16:T_FOPEN
    ldr     ip, [ip]
    cmp     ip, #0
    bne     1f
    movw    ip, #:lower16:T_WANT
    movt    ip, #:upper16:T_WANT
    ldr     ip, [ip]
    cmp     ip, #0
    beq     9f                          @ not wanted either: nothing to do
    mov     r0, #0
    mov     r1, #0
    mov     r2, #0
    bl      writer_make_job             @ an empty job is just a knock
    b       9f
1:

    movw    ip, #:lower16:STREAM_INDEX
    movt    ip, #:upper16:STREAM_INDEX
    ldr     r5, [ip]                    @ head
    movw    ip, #:lower16:STREAM_POSTED
    movt    ip, #:upper16:STREAM_POSTED
    ldr     r6, [ip]
    subs    r7, r5, r6                  @ records not yet handed over
    beq     8f                          @ nothing to write; still check for stop

    /* Cap at the ring: past that the oldest are already overwritten. */
    movw    r0, #:lower16:RING_RECORDS
    movt    r0, #:upper16:RING_RECORDS
    cmp     r7, r0
    bls     2f
    sub     r1, r7, r0
    movw    ip, #:lower16:T_LOST
    movt    ip, #:upper16:T_LOST
    ldr     r2, [ip]
    add     r2, r2, r1
    str     r2, [ip]
    sub     r6, r5, r0
    mov     r7, r0

2:  movw    ip, #:lower16:STREAM_RING
    movt    ip, #:upper16:STREAM_RING
    ldr     r8, [ip]
    cmp     r8, #0
    beq     9f

    movw    r0, #:lower16:RING_MASK
    movt    r0, #:upper16:RING_MASK
    and     r9, r6, r0
    lsl     r9, r9, #3                  @ first byte
    lsl     r10, r7, #3                 @ bytes in the span

    movw    r0, #:lower16:RING_BYTES
    movt    r0, #:upper16:RING_BYTES
    sub     r0, r0, r9
    cmp     r10, r0
    movlo   r0, r10                     @ min(span, to the end of the ring)

    add     r1, r8, r9
    mov     r2, r0
    mov     r0, #0
    bl      writer_make_job
    cmp     r0, #0
    beq     9f                          @ the pool is empty: try again next time

    /* Whatever ran past the end of the ring becomes a second job. */
    movw    r0, #:lower16:RING_BYTES
    movt    r0, #:upper16:RING_BYTES
    sub     r0, r0, r9
    cmp     r10, r0
    bls     3f
    sub     r2, r10, r0
    mov     r1, r8
    mov     r0, #0
    bl      writer_make_job
    movw    ip, #:lower16:T_WRAPS
    movt    ip, #:upper16:T_WRAPS
    ldr     r0, [ip]
    add     r0, r0, #1
    str     r0, [ip]

3:  movw    ip, #:lower16:STREAM_POSTED
    movt    ip, #:upper16:STREAM_POSTED
    str     r5, [ip]                    @ handed over

    /* The take may be over.  The stop goes through the SAME queue, after every
     * job above, so the writer cannot see it before it has written them --
     * ordering by construction, which is the point of doing it this way rather
     * than with a flag the writer reads on the side. */
8:  movw    ip, #:lower16:T_WANT
    movt    ip, #:upper16:T_WANT
    ldr     r0, [ip]
    cmp     r0, #0
    bne     9f
    movw    ip, #:lower16:T_STOPSENT
    movt    ip, #:upper16:T_STOPSENT
    ldr     r0, [ip]
    cmp     r0, #0
    bne     9f                          @ already sent one
    mov     r1, #0
    mov     r2, #0
    mov     r0, #1                      @ stop
    bl      writer_make_job
    cmp     r0, #0
    beq     9f                          @ no descriptor; the next call retries
    movw    ip, #:lower16:T_STOPSENT
    movt    ip, #:upper16:T_STOPSENT
    mov     r0, #1
    str     r0, [ip]

9:  pop     {r4, r5, r6, r7, r8, r9, r10, lr}
    bx      lr

/* writer_make_job(r0 = stop flag, r1 = ptr, r2 = len) -> r0 = 1 posted, 0 not.
 * Clobbers r0-r3, ip. */
writer_make_job:
    /* Eight: r6 carries the length across the allocation, so nothing has to be
     * pushed mid-routine.  Two single pushes to "keep it even" leave the stack
     * misaligned between them, which is the shape that has already frozen this
     * camera once. */
    push    {r1, r2, r3, r4, r5, r6, ip, lr}
    mov     r4, r0
    mov     r5, r1
    mov     r6, r2

    movw    r0, #:lower16:STREAM_JPOOL
    movt    r0, #:upper16:STREAM_JPOOL
    ldr     r0, [r0]
    bl      mpool_alloc
    cmp     r0, #0
    beq     8f                          @ pool empty: the caller retries later

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
    pop     {r1, r2, r3, r4, r5, r6, ip, lr}
    bx      lr

8:  mov     r0, #0
    pop     {r1, r2, r3, r4, r5, r6, ip, lr}
    bx      lr

/* -------------------------------------------------------------- reconcile */

/* Open or close the file to match what the recording asked for.
 *
 * The hooks that know a take has begun or ended run in firmware callbacks, so
 * all they do is set a word.  This is the task side of that: the heavy work,
 * on a stack that has room for it, in a context that is allowed to block.
 */
    .global writer_reconcile
writer_reconcile:
    push    {r4, r5, r6, lr}
    movw    r4, #:lower16:T_WANT
    movt    r4, #:upper16:T_WANT
    ldr     r4, [r4]
    movw    r5, #:lower16:T_FOPEN
    movt    r5, #:upper16:T_FOPEN
    ldr     r5, [r5]

    cmp     r4, #0
    beq     2f
    cmp     r5, #0
    bne     9f                          @ wanted and open: nothing to do
    bl      writer_openfile             @ the tail was latched by the hook
    b       9f

2:  /* Closing is NOT done here.  It is done when the stop job comes out of the
     * queue, behind every write of that take -- which is the whole reason the
     * stop travels as a job rather than as a flag read on the side. */

9:  pop     {r4, r5, r6, lr}
    bx      lr

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

/* writer_put(r1 = source, r2 = bytes).  Clobbers r0, r3, ip. */
writer_put:
    push    {r1, r2, r3, lr}
    movw    r0, #:lower16:T_FOBJ
    movt    r0, #:upper16:T_FOBJ
    ldr     r0, [r0]
    movw    ip, #:lower16:F_WRITE
    movt    ip, #:upper16:F_WRITE
    blx     ip
    movw    ip, #:lower16:T_WRC
    movt    ip, #:upper16:T_WRC
    str     r0, [ip]
    pop     {r1, r2, r3, lr}
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
    bx      lr

/* --------------------------------------------------------------- creator */

    .global make_writer
make_writer:
    push    {r4, r5, r6, r7, r8, lr}

    movw    r5, #:lower16:T_ID
    movt    r5, #:upper16:T_ID

    /* The mailbox first: the task waits on it the moment it starts. */
    movw    r4, #:lower16:T_PKT
    movt    r4, #:upper16:T_PKT
    mov     r0, #0
    str     r0, [r4]
    mov     r1, #1
    str     r1, [r4, #4]
    str     r0, [r4, #8]
    str     r0, [r4, #12]
    mov     r0, r4
    movw    ip, #:lower16:MBX_CREATE
    movt    ip, #:upper16:MBX_CREATE
    blx     ip
    str     r0, [r5, #0x1C]             @ T_MBX_RC
    cmp     r0, #0
    ble     9f
    movw    r1, #:lower16:T_MBX
    movt    r1, #:upper16:T_MBX
    str     r0, [r1]

    movw    r4, #:lower16:T_DESC
    movt    r4, #:upper16:T_DESC
    mov     r0, #0
    str     r0, [r4, #D_EXINF]
    mov     r0, #0x41
    str     r0, [r4, #D_TSKATR]
    movw    r0, #:lower16:T_ENTRY
    movt    r0, #:upper16:T_ENTRY
    ldr     r0, [r0]                    @ placed by the deploy script
    cmp     r0, #0
    beq     9f                          @ refuse rather than start at zero
    str     r0, [r4, #D_TASK]
    mov     r0, #WRITER_PRI
    str     r0, [r4, #D_ITSKPRI]
    movw    r0, #WRITER_STKSZ
    str     r0, [r4, #D_STKSZ]
    /* dsname "GYRW"; 'G' is the first byte in memory, so the word is
     * 0x57525947. */
    movw    r0, #0x5947
    movt    r0, #0x5752
    str     r0, [r4, #D_DSNAME]
    mov     r0, #0
    str     r0, [r4, #(D_DSNAME + 4)]

    str     r0, [r5, #0x0C]             @ T_WAKES
    str     r0, [r5, #0x10]             @ T_SIGNALS
    str     r0, [r5, #0x08]             @ T_STA_RC

    /* Clear the doorbell.  A producer can ring it before the mailbox exists --
     * opening the file without a task is enough -- and then it stays rung and
     * every later signal is skipped, so the writer is never woken again. */
    movw    r0, #:lower16:T_DOOR
    movt    r0, #:upper16:T_DOOR
    mov     r1, #0
    str     r1, [r0]
    mov     r0, #0

    mov     r0, r4
    movw    ip, #:lower16:TK_CRE_TSK
    movt    ip, #:upper16:TK_CRE_TSK
    blx     ip
    str     r0, [r5, #0x04]             @ T_CRE_RC
    cmp     r0, #0
    ble     9f
    str     r0, [r5, #0x00]             @ T_ID

    mov     r1, #0
    movw    ip, #:lower16:TK_STA_TSK
    movt    ip, #:upper16:TK_STA_TSK
    blx     ip
    str     r0, [r5, #0x08]             @ T_STA_RC, 0 = started

9:  pop     {r4, r5, r6, r7, r8, lr}
    bx      lr

/* ---------------------------------------------------------------- signal */

/* What a producer calls when the ring has work.  Task context only -- the Vd
 * hook is an interrupt and must never reach this.
 *
 * The doorbell is claimed with LDREX/STREX because two producers can ring it,
 * and because a second message while one is queued would need a second packet
 * for the kernel to link.  Losing that ring costs nothing: the writer clears
 * the doorbell before it reads the ring, so whatever arrives after is covered
 * by the message already in flight. */
    .global writer_signal
writer_signal:
    push    {r0, r1, r2, r3, ip, lr}

    movw    ip, #:lower16:T_DOOR
    movt    ip, #:upper16:T_DOOR
1:  ldrex   r0, [ip]
    cmp     r0, #0
    bne     8f                          @ already ringing
    mov     r1, #1
    strex   r2, r1, [ip]
    cmp     r2, #0
    bne     1b

    movw    r1, #:lower16:T_SIGNALS
    movt    r1, #:upper16:T_SIGNALS
    ldr     r2, [r1]
    add     r2, r2, #1
    str     r2, [r1]

    movw    r0, #:lower16:T_MBX
    movt    r0, #:upper16:T_MBX
    ldr     r0, [r0]
    cmp     r0, #0
    ble     8f
    movw    r1, #:lower16:T_PKT
    movt    r1, #:upper16:T_PKT
    movw    ip, #:lower16:MBX_SEND
    movt    ip, #:upper16:MBX_SEND
    blx     ip

8:  pop     {r0, r1, r2, r3, ip, lr}
    bx      lr

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
    mov     r2, #F_MODE_RW
    movw    ip, #:lower16:F_OPEN
    movt    ip, #:upper16:F_OPEN
    blx     ip
    movw    ip, #:lower16:T_FOPEN
    movt    ip, #:upper16:T_FOPEN
    str     r0, [ip]
    cmp     r0, #0
    beq     8f

    /* The tail is NOT touched here.  Whoever asked for the file to be opened
     * decides where the take starts: the record hook latches it at the instant
     * recording begins, which is up to a doorbell earlier than this runs.
     * Moving it here would throw those records away. */
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
writer_path:
    .asciz  "\\GYRO\\RINGTEST.BIN"
    .align  2

/* The job pool, in the same blob so the calls resolve without a relocation
 * the loader here cannot apply. */
#include "mpool.S"
