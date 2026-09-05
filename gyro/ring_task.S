.syntax unified
.arm

#include "ring_task.inc.S"

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
    b       1b

8:  movw    ip, #:lower16:T_RECV_RC
    movt    ip, #:upper16:T_RECV_RC
    str     r0, [ip]
9:  movw    r0, #1000
    movw    ip, #:lower16:TK_DLY_TSK
    movt    ip, #:upper16:TK_DLY_TSK
    blx     ip
    b       9b

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
