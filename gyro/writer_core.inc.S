.syntax unified
.arm
.text

/* ============================================================================
 * The writer, the parts every edition shares.
 * ============================================================================
 *
 * Both fpGyroSup editions run the same stream: the same hooks fill the same
 * blocks, the same "a block is full" event hands one to the same task, and the
 * same take is built and torn down around it.  What differs is only what the
 * writer does with a block once it has one -- Base writes it as it stands, and
 * the gcsv edition turns it into text first -- so that, and the file it opens
 * and closes, is what each edition supplies:
 *
 *     writer_put        one job: the block, however it is meant to reach the card
 *     writer_openfile   the name and whatever belongs at the front of the file
 *     writer_closefile  whatever belongs at the end of it
 *
 * Nothing here knows which edition it is in, and take_open and take_close are
 * unchanged by the split: they call the three above and never look inside them,
 * which is why the difference between the editions is three functions and not a
 * fork of the writer.
 *
 * This file is included, not assembled: the edition file supplies the three and
 * includes this for everything else.
 * ========================================================================== */

#include "ring_task.inc.S"
#include "imu_stream.inc.S"

/* The routine table, at the top of the blob so its address IS the blob's.
 *
 * gsup_boot needs to turn six symbols into addresses, and the blob is
 * position-independent -- it is placed at pool + 0x44000 and nothing in it
 * knows that number until boot.  `adr` cannot reach a table six hundred bytes
 * away (the distance has to be an eight-bit rotated immediate and 0x258 is
 * not), and the assembler has no `.word <label>`.  At offset zero there is
 * nothing to reach: the base is already in a register.
 *
 * The card builder patches these; zero means it did not, and gsup_boot then
 * wires everything to the top of the blob, which fails at once rather than
 * subtly.
 */
    .global gsup_offsets
gsup_offsets:
    .word   0       @ +0x00  writer_body
    .word   0       @ +0x04  take_open
    .word   0       @ +0x08  take_close
    .word   0       @ +0x0C  writer_post
    .word   0       @ +0x10  mpool_init_jobs
    .word   0       @ +0x14  blocks_open
    .word   0       @ +0x18  gsup_boot -- the cave trampoline reads this one
    .word   0       @ +0x1C  writer_path
    .word   0       @ +0x20  writer_header
    .word   0       @ +0x24  the first half of the gcsv header (that edition)
    .word   0       @ +0x28  the second half (that edition)

/* blob_at -- r0 = a byte offset into gsup_offsets.  Returns that entry as an
 * address in this blob.
 *
 * The blob is position independent and its buffers used to be reached with
 * `adr`.  That instruction's reach is an eight-bit rotated immediate, so it
 * depends on how far apart two things happen to land -- and it broke three
 * times in one day: once when blocks_open was inserted, once when
 * make_gyro_dir was, and once when the writer was split into a core and an
 * edition.  Each time the fix was to shuffle the file, which is not a fix.
 *
 * The table at the top of the blob already exists, the builder already patches
 * it, and the pool pointer is a fixed address.  Two loads and an add, and
 * nothing depends on layout again.
 */
    .global blob_at
blob_at:
    movw    ip, #:lower16:FRAMEBUF
    movt    ip, #:upper16:FRAMEBUF
    ldr     ip, [ip]
    cmp     ip, #0
    beq     9f
    add     ip, ip, #CODE_POOL_OFF
    ldr     r0, [ip, r0]
    add     r0, r0, ip
    bx      lr
9:  mov     r0, #0
    bx      lr

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

    /* And the text buffer, which is not in the row and would otherwise be the
     * one block a free-and-take cycle leaks every time round. */
    movw    r4, #:lower16:G_TEXT
    movt    r4, #:upper16:G_TEXT
    ldr     r1, [r4]
    cmp     r1, #0
    beq     9f
    mov     r0, r5
    movw    ip, #:lower16:MEM_FREE
    movt    ip, #:upper16:MEM_FREE
    blx     ip
    mov     r0, #0
    str     r0, [r4]

9:  pop     {r4, r5, r6, lr}
    bx      lr


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
    /* One more, and it is not a stream block: the gcsv edition turns a block
     * of records into text somewhere before it writes it, and that somewhere
     * has to be asked for at boot like everything else -- record start is the
     * wrong side of the line.  Base does not use it and pays sixteen kilobytes
     * out of the seventeen megabytes the channel has free, which is cheaper
     * than two allocation paths. */
    mov     r0, r5
    movw    r1, #:lower16:TEXT_BYTES
    movt    r1, #:upper16:TEXT_BYTES
    mov     r2, #0
    mov     r3, #0
    mov     ip, #0
    push    {ip, lr}
    movw    ip, #:lower16:MEM_GET
    movt    ip, #:upper16:MEM_GET
    blx     ip
    add     sp, sp, #8
    movw    ip, #:lower16:G_TEXT
    movt    ip, #:upper16:G_TEXT
    str     r0, [ip]

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

    /* The drop and hand counts describe THIS take, and this take is what the
     * header reports.  B_OFF is not here: take_header sets it, because opening
     * the file is what starts one. */
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

    mov     r0, #G_OFF_PATH
    bl      blob_at
    mov     r6, r0
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

/* The job pool, in the same blob so the calls resolve without a relocation
 * the loader here cannot apply. */
/* --------------------------------------------------------------- the boot */

/* gsup_boot -- everything the two deploy scripts do, done by the camera.
 *
 * Runs once, from the VSHL entry, with the camera idle at the end of boot.  It
 * is in the POOL rather than the cave because the cave has no room for it and
 * because it belongs with the code it is wiring up; a forty-byte trampoline in
 * the cave reads the pool pointer and branches here.
 *
 * The order is the deploy scripts' order, and it matters: everything is wired
 * and every buffer is in hand BEFORE a single hook is armed.  An armed hook
 * that reaches a word nobody has written yet is a freeze, and the camera at
 * this moment has no USB shell to be repaired with.
 *
 * If the allocator will not give the buffers, nothing is armed at all -- the
 * camera boots as an ordinary camera and the only sign is that no .GYR appears.
 * That is the right failure: a card that half-works is worse than one that does
 * not, because the take is gone either way and only one of them is obvious.
 *
 * The offsets it needs are patched into gsup_offsets by the card builder, which
 * is the only thing that knows where each routine landed in the blob.
 */
    .global gsup_boot
gsup_boot:
    push    {r4, r5, r6, r7, r8, lr}

    movw    r4, #:lower16:FRAMEBUF
    movt    r4, #:upper16:FRAMEBUF
    ldr     r4, [r4]                    @ r4 = the pool
    cmp     r4, #0
    beq     9f                          @ no pool: arm nothing

    add     r6, r4, #CODE_POOL_OFF      @ r6 = this blob, and the table is at its
    mov     r5, r6                      @ top -- see gsup_offsets

    /* The body, in the vtable slot the firmware's pool worker calls, and in a
     * word so a reader can see what it was given. */
    ldr     r0, [r5, #0]
    add     r0, r0, r6
    movw    r1, #:lower16:W_VT_BODY
    movt    r1, #:upper16:W_VT_BODY
    str     r0, [r1]
    movw    r1, #:lower16:T_ENTRY
    movt    r1, #:upper16:T_ENTRY
    str     r0, [r1]

    ldr     r0, [r5, #4]                @ take_open
    add     r0, r0, r6
    movw    r1, #:lower16:T_OPENFN
    movt    r1, #:upper16:T_OPENFN
    str     r0, [r1]

    ldr     r0, [r5, #8]                @ take_close
    add     r0, r0, r6
    movw    r1, #:lower16:T_CLOSEFN
    movt    r1, #:upper16:T_CLOSEFN
    str     r0, [r1]

    ldr     r0, [r5, #12]               @ writer_post
    add     r0, r0, r6
    movw    r1, #:lower16:STREAM_SIGFN
    movt    r1, #:upper16:STREAM_SIGFN
    str     r0, [r1]

    add     r0, r4, #FOBJ_POOL_OFF
    movw    r1, #:lower16:T_FOBJ
    movt    r1, #:upper16:T_FOBJ
    str     r0, [r1]
    add     r0, r4, #JPOOL_POOL_OFF
    movw    r1, #:lower16:STREAM_JPOOL
    movt    r1, #:upper16:STREAM_JPOOL
    str     r0, [r1]

    /* Every word the deploy scripts clear, cleared here.  A soft power cycle
     * can leave the cave holding the last session's values. */
    mov     r0, #0
    movw    r1, #:lower16:T_FOPEN
    movt    r1, #:upper16:T_FOPEN
    str     r0, [r1]
    movw    r1, #:lower16:T_WANT
    movt    r1, #:upper16:T_WANT
    str     r0, [r1]
    movw    r1, #:lower16:T_STAGE
    movt    r1, #:upper16:T_STAGE
    str     r0, [r1]
    movw    r1, #:lower16:T_POS
    movt    r1, #:upper16:T_POS
    str     r0, [r1]
    movw    r1, #:lower16:T_JSEQ
    movt    r1, #:upper16:T_JSEQ
    str     r0, [r1]
    movw    r1, #:lower16:T_JOBSLOT
    movt    r1, #:upper16:T_JOBSLOT
    str     r0, [r1]
    movw    r1, #:lower16:W_THREAD
    movt    r1, #:upper16:W_THREAD
    str     r0, [r1]
    movw    r1, #:lower16:T_MBX
    movt    r1, #:upper16:T_MBX
    str     r0, [r1]

    /* The release builds and tears down the whole take.  The ladders are the
     * bisection's, and there is nothing left to bisect. */
    mov     r0, #5
    movw    r1, #:lower16:T_BUILD
    movt    r1, #:upper16:T_BUILD
    str     r0, [r1]
    movw    r1, #:lower16:T_TEARDOWN
    movt    r1, #:upper16:T_TEARDOWN
    str     r0, [r1]

    /* The free list, before anything can take a descriptor from it. */
    ldr     r0, [r5, #16]               @ mpool_init_jobs
    add     r0, r0, r6
    blx     r0

    /* The buffers.  Before the movie path takes what it needs, which is the
     * whole reason this is at boot and not at record start. */
    ldr     r0, [r5, #20]               @ blocks_open
    add     r0, r0, r6
    blx     r0
    movw    r0, #:lower16:B_PTR
    movt    r0, #:upper16:B_PTR
    ldr     r0, [r0]
    cmp     r0, #0
    beq     9f                          @ refused: arm nothing

    /* Only now.  Three words, then the cache, so the firmware fetches the
     * branches and not what was there before them. */
    movw    r0, #:lower16:ACCEL_SITE
    movt    r0, #:upper16:ACCEL_SITE
    movw    r1, #:lower16:ARM_ACCEL
    movt    r1, #:upper16:ARM_ACCEL
    str     r1, [r0]
    movw    r0, #:lower16:START_SITE
    movt    r0, #:upper16:START_SITE
    movw    r1, #:lower16:ARM_START
    movt    r1, #:upper16:ARM_START
    str     r1, [r0]
    movw    r0, #:lower16:STOP_SITE
    movt    r0, #:upper16:STOP_SITE
    movw    r1, #:lower16:ARM_STOP
    movt    r1, #:upper16:ARM_STOP
    str     r1, [r0]
    movw    ip, #:lower16:F_CACHE
    movt    ip, #:upper16:F_CACHE
    blx     ip

9:  pop     {r4, r5, r6, r7, r8, lr}
    bx      lr

#include "mpool.S"
