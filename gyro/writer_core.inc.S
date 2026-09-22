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
    .word   0       @ +0x2C  writer_clip
    /* The four the cave used to answer for itself.  stream_space.S and
     * gyro_drain.S are sections of this blob now, so where they are is not
     * known until the pool is -- exactly like take_open above. */
    /* The hook bodies.  gsup_boot takes eight bytes from the cave allocator for
     * each and writes a veneer that jumps here.  Nothing else needs a slot: the
     * drain and the space provider are reached by an ordinary `bl` now. */
    .word   0       @ +0x30  accel_hook
    .word   0       @ +0x34  rec_start
    .word   0       @ +0x38  rec_stop
    .word   0       @ +0x3C  mode_hook (that edition only)

/* Shared state, reached through the pool pointer rather than pc-relatively.
 *
 * A pc-relative load reaches +/-4095 FROM THE INSTRUCTION, which is enough when
 * a word's only users sit together -- the stream cursors do, beside the hooks.
 * These do not: the writer's counters are touched from the core down here and
 * from the edition's own code four kilobytes further on, and no single place
 * satisfies both.
 *
 * So the anchor is the one the blob already has.  FRAMEBUF is a firmware word,
 * not a cave word, and blob_at has read the base out of it since the buffers
 * stopped being reachable with `adr`:
 *
 *     BLOBBASE ip                      four instructions, once per function
 *     ldr  r0, [ip, #O_T_BYTES]        one per access, from anywhere in the blob
 *
 * Now the +/-4095 is measured from the BLOB BASE, so a block in the first four
 * kilobytes is reachable by every function in it however far apart they are.
 * The cost is four instructions at the top of a function and one per access, so
 * it pays from the third word touched; a function touching one word is better
 * off pc-relative, and the stream cursors stayed that way.
 *
 * Nothing here is named in the cave.  FRAMEBUF is at a fixed firmware address
 * that every gyro source has read for as long as there has been a pool. */
    .align  2
g_shared:
g_t_bytes:  .word   0       /* bytes the writer has put on the card           */
g_t_writes: .word   0       /* times it has written                           */
g_t_wrc:    .word   0       /* what the last write returned                   */
g_t_lost:   .word   0       /* records dropped                                */
g_t_wraps:  .word   0       /* ring wraps                                     */
g_t_stage:  .word   0       /* how far the close got                          */

.equ O_T_BYTES,  g_t_bytes  - gsup_offsets
.equ O_T_WRITES, g_t_writes - gsup_offsets
.equ O_T_WRC,    g_t_wrc    - gsup_offsets
.equ O_T_LOST,   g_t_lost   - gsup_offsets
.equ O_T_WRAPS,  g_t_wraps  - gsup_offsets
.equ O_T_STAGE,  g_t_stage  - gsup_offsets

/* The job pool is not a word either: it is a fixed offset from the same pool
 * the blob sits in, so it can be worked out instead of stored -- which leaves
 * nothing to initialise and nothing to go stale.  JPOOL_POOL_OFF is one page
 * below CODE_POOL_OFF. */
.macro JPOOLAT reg
    BLOBBASE \reg
    sub     \reg, \reg, #(CODE_POOL_OFF - JPOOL_POOL_OFF)
.endm

.macro BLOBBASE reg
    movw    \reg, #:lower16:FRAMEBUF
    movt    \reg, #:upper16:FRAMEBUF
    ldr     \reg, [\reg]
    add     \reg, \reg, #CODE_POOL_OFF
.endm

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
    JPOOLAT r0
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

    JPOOLAT r0
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

1:  JPOOLAT r0
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
     * Called directly: the space provider is a section of this blob, so there
     * is no pointer to be zero and nothing to guard. */
    bl      stream_flush

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

    BLOBBASE r4                         @ r4 carries the base through the probe
    mov     r0, #0x11
    str     r0, [r4, #O_T_WRC]          @ reached the entry

    bl      writer_openfile
    movw    r5, #:lower16:T_FOPEN
    movt    r5, #:upper16:T_FOPEN
    ldr     r5, [r5]
    cmp     r5, #0
    moveq   r0, #0x12                   @ the open failed
    streq   r0, [r4, #O_T_WRC]
    beq     9f
    mov     r0, #0x13
    str     r0, [r4, #O_T_WRC]                    @ open done, about to write

    movw    r6, #:lower16:B_PTR
    movt    r6, #:upper16:B_PTR
    ldr     r6, [r6]                    @ the first block, if a take built any
    cmp     r6, #0
    moveq   r0, #0x14
    streq   r0, [r4, #O_T_WRC]
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
    str     r0, [r4, #O_T_WRC]          @ the write returned
    str     r1, [r4, #O_T_BYTES]        @ ... and this is what it said

8:  bl      writer_closefile
    mov     r0, #0x16
    str     r0, [r4, #O_T_WRC]                    @ closed, all the way through

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

    /* The eight characters, and only those.  Where the file goes is the
     * edition's business -- Base puts it in \\GYRO, the gcsv edition puts it
     * beside the clip -- and the two agree on nothing except this name, which
     * is the part that took the manager arithmetic to work out. */
    mov     r0, #G_OFF_CLIP
    bl      blob_at
    mov     r6, r0
    ldrb    r0, [r4, #8]                @ the camera letter
    strb    r0, [r6]
    mov     r0, r6
    add     r0, r0, #1
    ldr     r1, [r4, #0x0C]             @ the reel
    bl      put_dec3
    mov     r0, #'_'
    strb    r0, [r6, #4]
    add     r0, r6, #5
    mov     r1, r5
    bl      put_dec3
    mov     r0, #0
    strb    r0, [r6, #8]
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
    .space  48
    .align  2

/* The eight characters the camera calls this take, and a NUL.  take_path fills
 * it; each edition builds its own path around it. */
    .global writer_clip
writer_clip:
    .space  12
    .align  2

/* The job pool, in the same blob so the calls resolve without a relocation
 * the loader here cannot apply. */
/* --------------------------------------------------------------- the boot */

/* gsup_boot -- everything the two deploy scripts do, done by the camera.
 *
 * Runs once, from the card's entry, with the camera idle at the end of boot.  It
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

    /* The four call-through words are gone.
     *
     * They existed because a hook in the cave could not name a body the build
     * could not place -- a pointer was the only way across.  Hook and body are
     * sections of the same blob now, so the assembler resolves the branch:
     * nothing to fill in, nothing to load, nothing to guard against being zero,
     * and four fewer words in the cave. */
    add     r0, r4, #FOBJ_POOL_OFF
    movw    r1, #:lower16:T_FOBJ
    movt    r1, #:upper16:T_FOBJ
    str     r0, [r1]

    /* Every word the deploy scripts clear, cleared here.  A soft power cycle
     * can leave the cave holding the last session's values. */
    mov     r0, #0

    /* The blocks first, and this is the one that matters most.  blocks_open
     * returns early when B_PTR already holds something -- "already ours" --
     * which is right within a boot and catastrophic across one: the power
     * switch does not clear RAM, so the cave still names the LAST session's
     * eight buffers, while the firmware's allocator has been reinitialised and
     * considers every one of them free.  Skipping the allocation then leaves us
     * writing the stream into memory the recorder is about to be given.  The
     * first take after a warm restart still worked; the second was recording
     * into buffers that had been handed to something else, and stopped by
     * itself.  Only a cold boot fixed it, because only a cold boot cleared
     * B_PTR.
     *
     * B_BUSY goes with it (a stale one marks a block we no longer own as
     * in use) and so does G_TEXT, which is a ninth allocation with the same
     * lifetime. */
    movw    r1, #:lower16:B_PTR
    movt    r1, #:upper16:B_PTR
    mov     r2, #BUF_N
7:  str     r0, [r1], #4
    subs    r2, r2, #1
    bne     7b
    movw    r1, #:lower16:B_BUSY
    movt    r1, #:upper16:B_BUSY
    mov     r2, #BUF_N
7:  str     r0, [r1], #4
    subs    r2, r2, #1
    bne     7b
    movw    r1, #:lower16:G_TEXT
    movt    r1, #:upper16:G_TEXT
    str     r0, [r1]

    movw    r1, #:lower16:T_FOPEN
    movt    r1, #:upper16:T_FOPEN
    str     r0, [r1]
    movw    r1, #:lower16:T_WANT
    movt    r1, #:upper16:T_WANT
    str     r0, [r1]
    BLOBBASE r1
    str     r0, [r1, #O_T_STAGE]
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
#ifdef WANT_MODE_HOOK
    /* The cave outlives a re-place, so a stale count from the last blob would
     * read as "the hook fired" when it did not.  Zero is never fired. */
    movw    r1, #:lower16:G_MODE_N
    movt    r1, #:upper16:G_MODE_N
    str     r0, [r1]
#endif

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

    /* Each hook: eight bytes from the cave's allocator, the veneer written
     * into them, and the site armed to branch there -- in that order, per
     * hook, so a site is never armed over a landing point that does not exist.
     *
     * The F_CACHE below publishes all of it: the veneers are instructions the
     * firmware is about to fetch, and so are the branch words. */
    ldr     r0, [r5, #48]               @ accel_hook
    movw    r1, #:lower16:ACCEL_SITE
    movt    r1, #:upper16:ACCEL_SITE
    bl      s_hook
    ldr     r0, [r5, #52]               @ rec_start
    movw    r1, #:lower16:START_SITE
    movt    r1, #:upper16:START_SITE
    bl      s_hook
    ldr     r0, [r5, #56]               @ rec_stop
    movw    r1, #:lower16:STOP_SITE
    movt    r1, #:upper16:STOP_SITE
    bl      s_hook
#ifdef WANT_MODE_HOOK
    ldr     r0, [r5, #60]               @ mode_hook
    movw    r1, #:lower16:MODE_SITE
    movt    r1, #:upper16:MODE_SITE
    bl      s_hook
#endif

    movw    ip, #:lower16:F_CACHE
    movt    ip, #:upper16:F_CACHE
    blx     ip

#ifdef WANT_MODE_HOOK
    /* And the mode we were loaded INTO.  The hook fires when the mode is set,
     * and a camera that booted from this card straight into cine has already
     * had it set -- so without this, its takes are portrait until somebody
     * flips the switch and back.
     *
     * Two things this deliberately does not do.  It does not call FUN_c0057ae8
     * to find the object, because that CONSTRUCTS it when it is missing and
     * whether its subsystem is up this early is not known; it names the object
     * and first checks that what the object points at is a plausible address
     * at all.  An object that has not been built yet is zeroed memory, so a
     * zero is the reading that means "too early"; measured live, it is
     * 0xC31AC59C, which is RAM and not ROM -- an earlier version of this check
     * insisted on ROM and refused every time.  And it only ever writes a zero:
     * FUN_c0365328 starts the level gauge only when this byte is still clear,
     * so a one written here before that runs would turn the gauge off for
     * good.
     *
     * The call itself was run on the camera on its own, by hand, before it was
     * put in a boot path -- a fault here is a camera that will not start with
     * the card in the slot. */
    movw    r0, #:lower16:MODE_OBJ
    movt    r0, #:upper16:MODE_OBJ
    ldr     r1, [r0]
    cmp     r1, #0
    beq     9f
    lsr     r1, r1, #28
    cmp     r1, #0xC
    bne     9f
    movw    ip, #:lower16:F_MODE_GET
    movt    ip, #:upper16:F_MODE_GET
    blx     ip
    movw    r1, #:lower16:G_MODE
    movt    r1, #:upper16:G_MODE
    str     r0, [r1]                    @ readable afterwards, like the hook's
    mov     r2, #1
    str     r2, [r1, #4]
    cmp     r0, #MODE_CINE
    bne     9f                          @ stills: leave the camera's own value
    mov     r0, #0
    movw    r1, #:lower16:LEVEL_GATE
    movt    r1, #:upper16:LEVEL_GATE
    strb    r0, [r1]
#endif

9:  pop     {r4, r5, r6, r7, r8, lr}
    bx      lr

/* s_hook -- give one hook its veneer and arm its site.
 *
 *   r0 = the body's offset in this blob, or zero if this edition has none
 *   r1 = the firmware site the `bl` is written over
 *   r6 = the blob's base, as everywhere else in gsup_boot
 *
 * THE CAVE ADDRESS IS NOT A BUILD CONSTANT ANY MORE.  It is eight bytes taken
 * from the cave's bump allocator at boot, which is the whole point: a card that
 * is not on the SD card asks for nothing and holds no addresses, instead of a
 * range reserved for a feature the user may not have wanted.  The branch word
 * has to be computed here for the same reason -- until the allocator answers,
 * nobody knows what the firmware should branch to.
 *
 * Refused, or no body: the site is left exactly as the firmware wrote it.  A
 * hook that cannot be given a landing point must not be armed.
 *
 *     ldr pc, [pc, #-4]        the veneer, eight bytes
 *     .word <body>             filled in below
 *
 * pc reads as the instruction plus eight, so [pc,#-4] is the word straight
 * after.  It touches no register and not lr, so the body returns to the
 * firmware with `bx lr` and the caller cannot tell there was a hop. */
s_hook:
    cmp     r0, #0
    bxeq    lr
    push    {r4, r5, r7, lr}            @ four: the stack stays 8-aligned
    add     r4, r0, r6                  @ the body
    mov     r5, r1                      @ the site

    movw    r7, #:lower16:CAVE_BUMP
    movt    r7, #:upper16:CAVE_BUMP
    ldr     r0, [r7]
    adds    r1, r0, #8
    movw    r2, #:lower16:CAVE_ARENA_END
    movt    r2, #:upper16:CAVE_ARENA_END
    cmp     r1, r2
    bhi     9f                          @ the cave is full: arm nothing
    str     r1, [r7]

    movw    r2, #:lower16:VENEER_LDR
    movt    r2, #:upper16:VENEER_LDR
    str     r2, [r0]
    str     r4, [r0, #4]

    /* bl <veneer>, written over the site.  (dest - site - 8) >> 2, twenty-four
     * bits, and the top byte is the opcode.  asr, not lsr: the veneer can be
     * below the site and the offset is signed. */
    sub     r1, r0, r5
    sub     r1, r1, #8
    asr     r1, r1, #2
    bic     r1, r1, #0xFF000000
    orr     r1, r1, #0xEB000000
    str     r1, [r5]

9:  pop     {r4, r5, r7, pc}

#include "mpool.S"

/* The space provider and the gyro drain, in the blob rather than in the cave.
 *
 * Nothing in the firmware branches to either of them: the hooks reach them
 * through STREAM_CLAIMFN/COMMITFN/FLUSHFN/DRAINFN, four words in the cave that
 * somebody fills in.  So the only reason they were in the cave was that the
 * build knew where they were, and 1,108 bytes of the payload window went on
 * code nothing could jump to -- in a window that is 3,920 bytes with its
 * largest free run at 1,368 (measured 2026-09-22).
 *
 * Here they cost the pool, which is a megabyte, and gsup_boot fills the four
 * words in from the routine table the same way it fills in take_open and
 * writer_post.  The hooks that read them are armed at the END of gsup_boot, so
 * a word is never read before it is written.
 *
 * They still assemble on their own -- imu_stream_deploy places neither now,
 * but the files are what the USB deploy and the card share, and the guard in
 * imu_stream.inc.S is what lets them be both. */
/* The stream's cursors, in the blob beside the code that moves them.
 *
 * They were nine words in the cave at fixed build-time addresses, and the only
 * things that touch them are our own hooks -- which are sections of this blob
 * now.  So they live here, and `ldr r0, g_ghead` is one pc-relative
 * instruction: no movw/movt pair, no register to spare, and nothing named in
 * the cave.  Three instructions became one.
 *
 * Two things fall out of the move for free.  They are re-read from the card on
 * every boot, so a soft power cycle cannot leave last session's values behind
 * -- which is the class of bug that had the logger writing into buffers the
 * recorder already owned.  And two cards each get their own, by construction.
 *
 * BESIDE THE HOOKS, not at the top of the blob.  A pc-relative load reaches
 * +/-4095 and the first attempt put this next to the routine table, 4,276
 * bytes from gyro_drain -- the assembler refused, which is the right way to
 * find out.  What decides where a block of state goes is the reach of the code
 * that uses it, so each group sits with its own users. */
    .align  2
g_state:    .word   0       /* the stream's own state word                    */
g_r1_gc:    .word   0       /* GCOUNT when recording ended                    */
g_r1_n:     .word   0       /* times that has happened                        */
g_r0_head:  .word   0       /* ring head offset at record start               */
g_r0_gc:    .word   0       /* GCOUNT when the audio file opened              */
g_r0_n:     .word   0       /* times that has happened                        */
g_ghead:    .word   0       /* gyro ring head we have consumed                */
g_padbad:   .word   0       /* records whose pad was not what we assume       */
g_gcount:   .word   0       /* gyro records seen -- the rate ruler            */

#include "stream_space.S"
#include "gyro_drain.S"

/* The hook stubs, in the blob rather than in the cave.
 *
 * The firmware branches to these with `bl`, which reaches 32 MB -- and the pool
 * is two gigabytes away, so the LANDING POINT has to stay in the cave.  Only
 * the landing point: gsup_boot writes an eight-byte veneer at each of the four
 * cave addresses and the body lives here.  536 bytes of cave become 32.
 *
 * Nothing in these three files is position-dependent -- no `adr`, no literal
 * pool, no pc-relative load, every address a movw/movt pair -- so they run
 * wherever the allocator put the blob.  Checked, not assumed.
 *
 * rec_trigger.S is included twice because the record start and stop hooks are
 * one source with one `#ifdef`; each include defines its own symbol. */
#include "accel_hook.S"
#include "rec_trigger.S"
#define REC_STOP 1
#include "rec_trigger.S"
#undef REC_STOP
#ifdef WANT_MODE_HOOK
#include "mode_hook.S"
#endif
