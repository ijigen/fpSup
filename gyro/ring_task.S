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

/* writer_post(r0 = the block, r1 = its length, r2 = where it belongs in the
 * file, r3 = which block it is).
 *
 * stream_commit calls this when a block is used up, and nothing else calls it.
 * There is no span to work out, no threshold, no backlog to bound and no wrap
 * to split: it is handed a whole allocation that is finished with.
 */
    .global writer_post
writer_post:
    push    {r4, r5, r6, r7, ip, lr}
    mov     r5, r0
    mov     r6, r1
    mov     r7, r2
    movw    ip, #:lower16:T_JBLK
    movt    ip, #:upper16:T_JBLK
    str     r3, [ip]

    movw    r0, #:lower16:T_FOPEN
    movt    r0, #:upper16:T_FOPEN
    ldr     r0, [r0]
    cmp     r0, #0
    beq     9f                          @ no file: the block is dropped, and
                                        @ J_OFF leaves its hole behind

    mov     r1, r5
    mov     r2, r6
    mov     r3, r7
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
    movw    ip, #:lower16:T_JBLK
    movt    ip, #:upper16:T_JBLK
    ldr     r1, [ip]
    str     r1, [r0, #J_BLK]            @ so the writer can hand the block back
    movw    ip, #:lower16:T_JSEQ
    movt    ip, #:upper16:T_JSEQ
    ldr     r1, [ip]
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

    /* The block goes back to the producer first.  Audio has nothing like this:
     * its DSP owns its two buffers outright and simply overwrites them on
     * schedule.  Ours cannot be throttled, so the producer must be told when a
     * block is safe to refill -- and until it is told, it counts a drop rather
     * than writing over data the card has not seen. */
    movw    r0, #:lower16:T_JOBSLOT
    movt    r0, #:upper16:T_JOBSLOT
    ldr     r0, [r0]
    cmp     r0, #0
    beq     1f
    ldr     r1, [r0, #J_LEN]
    cmp     r1, #0
    beq     1f                          @ the stop job holds no block
    ldr     r1, [r0, #J_BLK]
    cmp     r1, #BUF_N
    bhs     1f
    movw    r2, #:lower16:B_BUSY
    movt    r2, #:upper16:B_BUSY
    mov     r3, #0
    str     r3, [r2, r1, lsl #2]

1:  movw    r0, #:lower16:STREAM_JPOOL
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
/* Give every block we hold back to the allocator.  Used by the teardown and by
 * a build that could not get them all. */
free_blocks:
    push    {r4, r5, r6, lr}
    mov     r0, #MEM_CLASS
    movw    ip, #:lower16:MEM_HEAP
    movt    ip, #:upper16:MEM_HEAP
    blx     ip
    cmp     r0, #0
    beq     9f
    mov     r5, r0
    mov     r6, #0
    movw    r4, #:lower16:B_PTR
    movt    r4, #:upper16:B_PTR
1:  ldr     r1, [r4, r6, lsl #2]
    cmp     r1, #0
    beq     2f
    mov     r0, r5
    movw    ip, #:lower16:MEM_FREE
    movt    ip, #:upper16:MEM_FREE
    blx     ip
    mov     r0, #0
    str     r0, [r4, r6, lsl #2]
2:  add     r6, r6, #1
    cmp     r6, #BUF_N
    blo     1b
9:  pop     {r4, r5, r6, lr}
    bx      lr


/* blocks_open -- ask the allocator for the row, once, with the camera idle.
 *
 * Called through the borrowed shell handler at deploy time.  Everything the
 * take does afterwards assumes these exist; take_open declines if they do not.
 */
/* blocks_open -- ask the allocator for the row, once, with the camera idle.
 *
 * The rule is not "do not allocate across a recording": it is that the
 * allocation has to come BEFORE the movie path takes what it needs.  This runs
 * through the borrowed shell handler at deploy time, which is as far before as
 * it is possible to be.
 *
 * Audio can afford to ask at capture start because it asks class 6, MOVAUDIO,
 * which is nobody else's.  We ask class 0, the generic one, so we ask early and
 * hold it for the session.
 *
 * All or nothing: a half-built row is a row with a hole in it, and the producer
 * would drop into that hole for good.
 */
    .global blocks_open
blocks_open:
    push    {r4, r5, r6, r7, ip, lr}

    movw    r0, #:lower16:B_PTR
    movt    r0, #:upper16:B_PTR
    ldr     r0, [r0]
    cmp     r0, #0
    bne     9f                          @ already ours

    mov     r0, #MEM_CLASS
    movw    ip, #:lower16:MEM_HEAP
    movt    ip, #:upper16:MEM_HEAP
    blx     ip
    cmp     r0, #0
    beq     9f
    mov     r5, r0                      @ the channel
    mov     r6, #0

1:  mov     r0, r5
    movw    r1, #:lower16:BUF_BYTES
    movt    r1, #:upper16:BUF_BYTES
    mov     r2, #0
    mov     r3, #0
    mov     ip, #0
    push    {ip, lr}                    @ the fifth argument, and the alignment
    movw    ip, #:lower16:MEM_GET
    movt    ip, #:upper16:MEM_GET
    blx     ip
    add     sp, sp, #8
    cmp     r0, #0
    beq     2f                          @ refused: give back what we took
    movw    ip, #:lower16:B_PTR
    movt    ip, #:upper16:B_PTR
    str     r0, [ip, r6, lsl #2]
    movw    ip, #:lower16:B_BUSY
    movt    ip, #:upper16:B_BUSY
    mov     r1, #0
    str     r1, [ip, r6, lsl #2]
    add     r6, r6, #1
    cmp     r6, #BUF_N
    blo     1b
    b       3f

2:  bl      free_blocks
    b       9f

3:  /* Nothing is filling yet, and the file starts at byte zero. */
    movw    ip, #:lower16:B_CUR
    movt    ip, #:upper16:B_CUR
    mvn     r0, #0
    str     r0, [ip]
    mov     r0, #0
    movw    ip, #:lower16:B_FILL
    movt    ip, #:upper16:B_FILL
    str     r0, [ip]
    movw    ip, #:lower16:B_DONE
    movt    ip, #:upper16:B_DONE
    str     r0, [ip]
    movw    ip, #:lower16:B_OFF
    movt    ip, #:upper16:B_OFF
    str     r0, [ip]
    movw    ip, #:lower16:B_DROPS
    movt    ip, #:upper16:B_DROPS
    str     r0, [ip]
    movw    ip, #:lower16:B_HANDED
    movt    ip, #:upper16:B_HANDED
    str     r0, [ip]

9:  pop     {r4, r5, r6, r7, ip, lr}
    bx      lr


    .global blocks_close
blocks_close:
    push    {r4, lr}
    bl      free_blocks
    pop     {r4, lr}
    bx      lr


    .global take_open
take_open:
    push    {r4, r5, r6, r7, ip, lr}
    movw    r4, #:lower16:W_STAGE
    movt    r4, #:upper16:W_STAGE
    mov     r0, #0x01
    str     r0, [r4]

    movw    r0, #:lower16:T_FOPEN
    movt    r0, #:upper16:T_FOPEN
    ldr     r0, [r0]
    cmp     r0, #0
    bne     9f                          @ a take is already built

    /* The blocks are already ours.  Nothing is asked of the allocator here.
     *
     * The rule is not "do not allocate across a recording" -- it is that the
     * allocation has to come BEFORE the movie path takes what it needs.  By the
     * time this hook runs, movRec is already tearing the monitor audio down and
     * the recorder is about to ask class 10 (RAW) for its frame buffers, so
     * this is the wrong side of that line.
     *
     * blocks_open does it at deploy time instead, with the camera idle and no
     * recording anywhere near.  Audio can ask at capture start because it asks
     * class 6, which is MOVAUDIO and is nobody else's; we ask class 0, which is
     * the generic one, so we ask early and hold it. */
    movw    r0, #:lower16:B_PTR
    movt    r0, #:upper16:B_PTR
    ldr     r0, [r0]
    cmp     r0, #0
    mov     r0, #0x06
    str     r0, [r4]
    beq     9f                          @ blocks_open has not run

    /* Each take is its own file, so each take starts at the top of one.  The
     * first sixty-four bytes are the header, and B_OFF is where the first block
     * will say it belongs -- carrying the last take's B_OFF over is how two
     * takes used to end up layered into one file.  The drop and hand counts go
     * with it: they describe this take now, and this take is what the header
     * reports. */
    movw    r0, #:lower16:B_OFF
    movt    r0, #:upper16:B_OFF
    mov     r1, #HDR_BYTES
    str     r1, [r0]
    movw    r0, #:lower16:B_DROPS
    movt    r0, #:upper16:B_DROPS
    mov     r1, #0
    str     r1, [r0]
    movw    r0, #:lower16:B_HANDED
    movt    r0, #:upper16:B_HANDED
    str     r1, [r0]

    movw    r0, #:lower16:T_BUILD
    movt    r0, #:upper16:T_BUILD
    ldr     r7, [r0]
    cmp     r7, #1
    blo     9f

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

    cmp     r7, #2
    blo     9f
    bl      make_writer                 @ the mailbox
    movw    r0, #:lower16:T_MBX
    movt    r0, #:upper16:T_MBX
    ldr     r0, [r0]
    cmp     r0, #0
    mov     r0, #0x03
    str     r0, [r4]
    ble     9f

    cmp     r7, #3
    blo     9f

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
    cmp     r7, #4
    blo     9f
    /* The ADDRESS of the body object, not its contents.  The worker does
     * (**(code **)(**(int **)(holder + 8) + 0xc))(): it stores this pointer as
     * B, reads *B for the vtable, and calls vtable+0xC.  W_BODYOBJ is the body
     * -- one word holding &W_VT -- so B must be &W_BODYOBJ.  Passing its value
     * (&W_VT) made the worker read W_VT[0], which nothing ever writes, as a
     * vtable: the instant it was woken it called a garbage pointer.  Build 3,
     * which never wakes it, ran; every build that woke it died on the spot,
     * at either site, with either stack. */
    movw    r1, #:lower16:W_BODYOBJ
    movt    r1, #:upper16:W_BODYOBJ
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

9:  pop     {r4, r5, r6, r7, ip, lr}
    bx      lr


    .align  2
writer_name:
    .asciz  "GYRW"
    .space  3
    .align  2

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

    /* How far to tear down.  The teardown is five steps and only one of them
     * can hang for ever -- the join is TMO_FEVR, so a worker that never sets
     * the completion flag stops cDevt_stop where it stands, and SRecFile is
     * waiting on that task.  A full freeze takes USB with it, so W_STAGE cannot
     * be read afterwards; the only way to tell the five apart is to run n of
     * them.
     *
     *   1  post the stop job
     *   2  + join
     *   3  + delete the mailbox
     *   4  + destroy the thread
     *   5  + close the file          (the whole thing)
     *
     * That is AudioFileWriter::v0's order, not the one this comment used to
     * claim: the writer leaves the system first, the file goes last.
     */
    movw    r0, #:lower16:T_TEARDOWN
    movt    r0, #:upper16:T_TEARDOWN
    ldr     r6, [r0]
    cmp     r6, #0
    beq     9f                          @ leave it all standing; --close later

    /* Each piece is undone only if it was built: the build is a ladder now and
     * a half-built take must still give everything back. */
    movw    r0, #:lower16:T_MBX
    movt    r0, #:upper16:T_MBX
    ldr     r0, [r0]
    cmp     r0, #0
    ble     4f                          @ no mailbox: no stop job, no join

    movw    r0, #:lower16:W_THREAD
    movt    r0, #:upper16:W_THREAD
    ldr     r0, [r0]
    cmp     r0, #0
    beq     4f                          @ no thread: nothing to wait for

    /* The tail, before the marker.  The stop message carries no data --
     * AudioFileWriter::v1 breaks on J_STOP before it writes, and the four
     * words audio copies into that message (DAT_c07e3dc8) are zeros -- so
     * the part-filled block has to arrive as an ordinary job ahead of it.
     * Audio's DSP says which of its buffers is last; nothing says that to
     * us, so the end of the take says it.  One mailbox, so the order holds.
     *
     * Off until the space provider is on: at stage 2 there are no blocks to
     * flush and the pointer is zero. */
    movw    ip, #:lower16:STREAM_FLUSHFN
    movt    ip, #:upper16:STREAM_FLUSHFN
    ldr     ip, [ip]
    cmp     ip, #0
    blxne   ip

    mov     r0, #1                      @ J_STOP
    mov     r1, #0
    mov     r2, #0
    mov     r3, #0
    bl      writer_make_job
    cmp     r0, #0
    mov     r0, #0x12
    str     r0, [r4]
    beq     9f                          @ never posted: nothing to wait for
    cmp     r6, #2
    blo     9f

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
    cmp     r6, #3
    blo     9f

    /* AudioFileWriter::v0's order, and it is not the one we had:
     *
     *     FUN_c036d930(mbx)        delete the mailbox
     *     FUN_c036e168(thread, 2)  destroy the thread
     *     XC_MediaFile::v0(file)   and only now the file, whose destructor
     *                              closes it itself
     *
     * We closed first and collected the thread and the mailbox afterwards.
     * Every teardown that reached the close froze the camera at that
     * instant; every one that stopped before it ran the take.  Audio takes
     * the writer out of the system before it touches the file, so nothing
     * priority 6 is left standing when the volume lock is taken in the task
     * SRecFile is waiting on. */
    movw    r5, #:lower16:T_MBX
    movt    r5, #:upper16:T_MBX
    ldr     r0, [r5]
    cmp     r0, #0
    ble     4f
    movw    ip, #:lower16:MBX_DELETE
    movt    ip, #:upper16:MBX_DELETE
    blx     ip
    mov     r0, #0
    str     r0, [r5]

4:  mov     r0, #0x14
    str     r0, [r4]
    cmp     r6, #4
    blo     9f

    movw    r5, #:lower16:W_THREAD
    movt    r5, #:upper16:W_THREAD
    ldr     r0, [r5]
    cmp     r0, #0
    beq     5f
    mov     r0, r5
    mov     r1, #2                      @ do not delete the holder: it is ours
    movw    ip, #:lower16:XT_DESTROY
    movt    ip, #:upper16:XT_DESTROY
    blx     ip
    mov     r0, #0
    str     r0, [r5]

5:  mov     r0, #0x15
    str     r0, [r4]
    cmp     r6, #5
    blo     9f

    bl      writer_closefile

    /* The blocks stay.  They were taken before the movie path took anything
     * and they are given back only when the whole thing is torn down --
     * blocks_close, from the shell, never from the stop path. */

6:  mov     r0, #0x16
    str     r0, [r4]
    movw    r0, #:lower16:W_CLOSES
    movt    r0, #:upper16:W_CLOSES
    ldr     r1, [r0]
    add     r1, r1, #1
    str     r1, [r0]

9:  pop     {r4, r5, r6, lr}
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
    mov     r5, r0                      @ the volume: the ctor's, and the name's
    bl      take_path
    mov     r6, r0
    mov     r1, r5
    mov     r0, r4
    movw    ip, #:lower16:F_CTOR
    movt    ip, #:upper16:F_CTOR
    blx     ip

    mov     r0, r4
    mov     r1, r6
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

    mov     r0, r5                      @ still the volume
    bl      take_header

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

    /* What the header could not know at open.  The join is done and the mailbox
     * and the thread are gone, so the file is ours again. */
    adr     r0, writer_header
    movw    r1, #:lower16:B_OFF
    movt    r1, #:upper16:B_OFF
    ldr     r1, [r1]
    sub     r1, r1, #HDR_BYTES
    str     r1, [r0, #H_PAYLOAD]
    movw    r1, #:lower16:B_DROPS
    movt    r1, #:upper16:B_DROPS
    ldr     r1, [r1]
    str     r1, [r0, #H_DROPPED]
    bl      put_header

    /* The destructor and nothing else.  AudioFileWriter::v0 calls
     * XC_MediaFile::v0 and never F_CLOSE, because the destructor closes the
     * file itself -- FUN_c0366020 is its first act.  Calling F_CLOSE first put
     * us through that path twice: once for real, and once as a no-op on an
     * object whose handle we had already nulled.  Audio goes through it once. */
    movw    r6, #:lower16:T_FOBJ
    movt    r6, #:upper16:T_FOBJ
    ldr     r6, [r6]                    @ r6 stops being T_STAGE here
    movw    ip, #:lower16:T_STAGE
    movt    ip, #:upper16:T_STAGE
    mov     r0, #0x24
    str     r0, [ip]                    @ about to destroy
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

    movw    r6, #:lower16:B_PTR
    movt    r6, #:upper16:B_PTR
    ldr     r6, [r6]                    @ the first block, if a take built any
    cmp     r6, #0
    moveq   r0, #0x14
    streq   r0, [r4]
    beq     8f

    mov     r1, r6                      @ straight out of the block
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
/* take_path -- the name of the take that is starting.  r0 = the volume F_VOL
 * returned; returns r0 = the path.
 *
 * The camera decides what a clip is called, and there is exactly one place it
 * decides it: RecordFilePathMgrCinema.  This is lifecycle.inc.S's arithmetic
 * against the same two objects, because a gyro log named anything else is a
 * log nobody can match to a clip.  The saved maximum at +0x2C only counts when
 * AutoRstFlg is clear -- with it set the camera restarts numbering and the
 * remembered high-water mark would name the file after a clip that is not the
 * one being shot. */
take_path:
    push    {r4, r5, r6, lr}
    cmp     r0, #5
    beq     1f
    movw    r4, #:lower16:PATH_MGR_SD
    movt    r4, #:upper16:PATH_MGR_SD
    b       2f
1:  movw    r4, #:lower16:PATH_MGR_SSD
    movt    r4, #:upper16:PATH_MGR_SSD

2:  ldr     r5, [r4, #0x10]             @ the take the manager is on
    movw    r0, #:lower16:SETTINGS_PTR
    movt    r0, #:upper16:SETTINGS_PTR
    ldr     r0, [r0]
    cmp     r0, #0
    beq     3f
    ldrb    r0, [r0, #O_AUTORSTFLG]
    cmp     r0, #0
    bne     4f                          @ numbering restarts: ignore the maximum
3:  ldr     r0, [r4, #0x2C]
    cmp     r0, r5
    movhi   r5, r0
4:  add     r5, r5, #1                  @ the one about to be recorded

    adr     r6, writer_path
    movw    r0, #0x475C
    movt    r0, #0x5259                 @ "\\GYR"
    str     r0, [r6]
    movw    r0, #0x5C4F                 @ "O\\"
    strh    r0, [r6, #4]
    ldrb    r0, [r4, #8]                @ the camera letter
    strb    r0, [r6, #6]
    add     r0, r6, #7
    ldr     r1, [r4, #0x0C]             @ the reel
    bl      put_dec3
    mov     r0, #'_'
    strb    r0, [r6, #10]
    add     r0, r6, #11
    mov     r1, r5
    bl      put_dec3
    mov     r0, #'.'
    strb    r0, [r6, #14]
    mov     r0, #'G'
    strb    r0, [r6, #15]
    mov     r0, #'Y'
    strb    r0, [r6, #16]
    mov     r0, #'R'
    strb    r0, [r6, #17]
    mov     r0, #0
    strb    r0, [r6, #18]
    mov     r0, r6
    pop     {r4, r5, r6, lr}
    bx      lr

/* take_header -- fill in the sixty-four bytes and put them at the front.
 *
 * r0 = the volume.  Called from writer_openfile with the file open and no
 * writer task in existence yet, so the file position is ours alone.
 *
 * Sensor mode, exposure and geometry read as nothing while the camera is idle.
 * Record start is the only moment they can be taken, which is why they are
 * taken here and not by the shell afterwards.
 */
take_header:
    push    {r4, r5, r6, lr}
    adr     r4, writer_header
    mov     r5, r0

    movw    r0, #0x4647
    movt    r0, #0x3753                 @ "GFS7"
    str     r0, [r4, #H_MAGIC]
    mov     r0, #GYR_VERSION
    str     r0, [r4, #H_VERSION]
    movw    r0, #:lower16:GYR_PERIOD_PS
    movt    r0, #:upper16:GYR_PERIOD_PS
    str     r0, [r4, #H_PERIOD_PS]
    movw    r0, #:lower16:GYR_GSCALE
    movt    r0, #:upper16:GYR_GSCALE
    str     r0, [r4, #H_GSCALE]
    movw    r0, #:lower16:GYR_ORIENT
    movt    r0, #:upper16:GYR_ORIENT
    str     r0, [r4, #H_ORIENT]
    str     r5, [r4, #H_VOLUME]

    /* The clip id, straight out of the name take_path just built: the two are
     * the same eight characters by construction, so there is no second place
     * for them to disagree. */
    adr     r0, writer_path
    ldr     r1, [r0, #6]
    str     r1, [r4, #H_CLIP]
    ldr     r1, [r0, #10]
    str     r1, [r4, #H_CLIP + 4]

    mov     r0, #0
    str     r0, [r4, #H_PAYLOAD]        @ filled in at close
    str     r0, [r4, #H_DROPPED]
    str     r0, [r4, #0x38]
    str     r0, [r4, #0x3C]

    movw    ip, #:lower16:SENSOR_MODE_FN
    movt    ip, #:upper16:SENSOR_MODE_FN
    blx     ip
    str     r0, [r4, #H_MODE]
    movw    ip, #:lower16:EXPOSURE_FN
    movt    ip, #:upper16:EXPOSURE_FN
    blx     ip
    str     r0, [r4, #H_EXPOSURE]
    mov     r0, #0
    str     r0, [r4, #H_WIDTH]
    str     r0, [r4, #H_HEIGHT]
    movw    ip, #:lower16:F_CAMSETTING
    movt    ip, #:upper16:F_CAMSETTING
    blx     ip
    cmp     r0, #0
    beq     1f
    add     r0, r0, #SETTING_DIMS
    ldr     r1, [r0]
    ldr     r2, [r0, #4]
    /* Refuse anything that is not a plausible frame rather than write a
     * number the profile would then be built on. */
    cmp     r1, #640
    blo     1f
    cmp     r2, #360
    blo     1f
    movw    r0, #0x2000
    cmp     r1, r0
    bhi     1f
    cmp     r2, r0
    bhi     1f
    add     r1, r1, #DNG_PAD_W
    add     r2, r2, #DNG_PAD_H
    str     r1, [r4, #H_WIDTH]
    str     r2, [r4, #H_HEIGHT]
1:

    mov     r0, r4
    bl      put_header
    pop     {r4, r5, r6, lr}
    bx      lr

/* put_header -- seek to zero and write the sixty-four bytes.  Nothing else is
 * touching the file when this runs: at open the writer task does not exist yet,
 * at close the join has already collected it. */
put_header:
    push    {r4, r5, r6, lr}
    mov     r5, r0
#ifndef DRY_RUN
    movw    r4, #:lower16:T_FOBJ
    movt    r4, #:upper16:T_FOBJ
    ldr     r4, [r4]
    mov     r0, r4
    mov     r1, #0
    mov     r2, #0
    movw    ip, #:lower16:F_SEEK
    movt    ip, #:upper16:F_SEEK
    blx     ip
    mov     r0, r4
    mov     r1, r5
    mov     r2, #HDR_BYTES
    movw    ip, #:lower16:F_WRITE
    movt    ip, #:upper16:F_WRITE
    blx     ip
#endif
    movw    ip, #:lower16:T_POS
    movt    ip, #:upper16:T_POS
    mov     r0, #HDR_BYTES
    str     r0, [ip]                    @ the file is at the end of the header
    pop     {r4, r5, r6, lr}
    bx      lr

/* r0 = where to write, r1 = 0..999.  Three digits, no division: the same
 * routine lifecycle.inc.S uses. */
put_dec3:
    mov     r2, #'0'
1:  cmp     r1, #100
    blo     2f
    sub     r1, r1, #100
    add     r2, r2, #1
    b       1b
2:  strb    r2, [r0], #1
    mov     r2, #'0'
3:  cmp     r1, #10
    blo     4f
    sub     r1, r1, #10
    add     r2, r2, #1
    b       3b
4:  strb    r2, [r0], #1
    add     r1, r1, #'0'
    strb    r1, [r0]
    bx      lr

/* Filled in at every take_open.  Twenty bytes is "\\GYRO\\A001_037.GYR" and
 * its NUL exactly; the rest is slack so a longer scheme does not have to move
 * anything. */
writer_path:
    .space  32
    .align  2

/* The header, rebuilt at every take_open and rewritten at every close. */
writer_header:
    .space  HDR_BYTES
    .align  2

/* The job pool, in the same blob so the calls resolve without a relocation
 * the loader here cannot apply. */
#include "mpool.S"
