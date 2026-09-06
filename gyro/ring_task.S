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
    movw    r1, #:lower16:T_PKT
    movt    r1, #:upper16:T_PKT
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

    /* Clear the doorbell BEFORE looking at the work.  Anything a producer adds
     * from here on is guaranteed to ring again; the other order can lose the
     * last batch of a take. */
    movw    ip, #:lower16:T_DOOR
    movt    ip, #:upper16:T_DOOR
    mov     r1, #0
    str     r1, [ip]

    movw    ip, #:lower16:T_WAKES
    movt    ip, #:upper16:T_WAKES
    ldr     r1, [ip]
    add     r1, r1, #1
    str     r1, [ip]

    bl      writer_drain
    b       1b

8:  movw    ip, #:lower16:T_RECV_RC
    movt    ip, #:upper16:T_RECV_RC
    str     r0, [ip]
9:  movw    r0, #1000
    movw    ip, #:lower16:TK_DLY_TSK
    movt    ip, #:upper16:TK_DLY_TSK
    blx     ip
    b       9b

/* ------------------------------------------------------------------ drain */

/* Write everything the producers have put in, straight out of the ring.
 *
 * This is the whole point of the shape: F_WRITE takes a pointer and a length,
 * so the source is the ring itself.  Audio does the same -- its writer receives
 * {offset, pointer, length} and writes from the pointer it was handed.  Nothing
 * is copied and nothing is formatted here; turning the records into gcsv text
 * belongs after the take, or this task stops being IO-bound and starts holding
 * the card lock while it does arithmetic.
 *
 * A span that runs over the end of the ring becomes two writes.  Audio expresses
 * that as two jobs; with a head and a tail it is an `if`.
 */
    .global writer_drain
writer_drain:
    push    {r4, r5, r6, r7, r8, r9, r10, lr}

    movw    r4, #:lower16:T_FOPEN
    movt    r4, #:upper16:T_FOPEN
    ldr     r4, [r4]
    cmp     r4, #0
    beq     9f                          @ no file yet: leave the ring alone

    movw    ip, #:lower16:STREAM_INDEX
    movt    ip, #:upper16:STREAM_INDEX
    ldr     r5, [ip]                    @ head, in records
    movw    ip, #:lower16:STREAM_TAIL
    movt    ip, #:upper16:STREAM_TAIL
    ldr     r6, [ip]
    subs    r7, r5, r6                  @ span
    beq     9f

    /* More than the ring holds means the producers wrapped past us and the
     * oldest records are gone.  Count exactly how many and take the newest
     * that still exist -- silently writing the wrapped ring would put garbage
     * in the file and hide the only failure the depth exists to prevent. */
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
    ldr     r8, [ip]                    @ the ring's base
    cmp     r8, #0
    beq     9f

    movw    r0, #:lower16:RING_MASK
    movt    r0, #:upper16:RING_MASK
    and     r9, r6, r0
    lsl     r9, r9, #3                  @ first byte of the span
    lsl     r10, r7, #3                 @ bytes in it

    /* min(bytes, to the end of the ring) */
    movw    r0, #:lower16:RING_BYTES
    movt    r0, #:upper16:RING_BYTES
    sub     r0, r0, r9
    cmp     r10, r0
    movlo   r0, r10

    add     r1, r8, r9                  @ straight into the ring
    mov     r2, r0
    mov     r4, r0                      @ remember how much went first
    bl      writer_put

    subs    r2, r10, r4
    beq     3f
    movw    ip, #:lower16:T_WRAPS
    movt    ip, #:upper16:T_WRAPS
    ldr     r0, [ip]
    add     r0, r0, #1
    str     r0, [ip]
    mov     r1, r8                      @ the rest, from the ring's start
    bl      writer_put

3:  movw    ip, #:lower16:STREAM_TAIL
    movt    ip, #:upper16:STREAM_TAIL
    str     r5, [ip]                    @ taken

    movw    ip, #:lower16:T_DRAINED
    movt    ip, #:upper16:T_DRAINED
    ldr     r0, [ip]
    add     r0, r0, r7
    str     r0, [ip]
    movw    ip, #:lower16:T_MAXSPAN
    movt    ip, #:upper16:T_MAXSPAN
    ldr     r0, [ip]
    cmp     r7, r0
    strhi   r7, [ip]

9:  pop     {r4, r5, r6, r7, r8, r9, r10, lr}
    bx      lr

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

    /* Start from now, not from record zero.  While the file was closed the
     * drain returned early without moving the tail, so the head has run away
     * from it -- opening without this makes the very first write a whole
     * ring's worth of stale records, and counts the rest as lost. */
    movw    ip, #:lower16:STREAM_INDEX
    movt    ip, #:upper16:STREAM_INDEX
    ldr     r0, [ip]
    movw    ip, #:lower16:STREAM_TAIL
    movt    ip, #:upper16:STREAM_TAIL
    str     r0, [ip]
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
    movw    r4, #:lower16:T_FOPEN
    movt    r4, #:upper16:T_FOPEN
    ldr     r5, [r4]
    cmp     r5, #0
    beq     9f

    bl      writer_drain

    movw    r6, #:lower16:T_FOBJ
    movt    r6, #:upper16:T_FOBJ
    ldr     r6, [r6]
    mov     r0, r6
    movw    ip, #:lower16:F_CLOSE
    movt    ip, #:upper16:F_CLOSE
    blx     ip
    mov     r0, r6
    mov     r1, #2
    movw    ip, #:lower16:F_DTOR
    movt    ip, #:upper16:F_DTOR
    blx     ip
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
