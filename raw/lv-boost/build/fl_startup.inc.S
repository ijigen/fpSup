/* One startup selection in task context. No settings calls from ISP hooks.
 * Private diagnostics: +50 state (0 waiting, 1 applied, 2 user cancelled,
 * 3 applying, 4 verification failed, 5 saved disabled), +54 task id, +58 start result.
 * The firmware has no proven task-exit wrapper; park after the one-shot.
 * This uses the same yielding delay and task ABI as the USB shell worker. */
.align 2
fl_start:
    PADR    r4
    mov     r5, #0
fl_wait:
    mov     r0, #100
    ldr     ip, =0xC01F89C4
    blx     ip
    ldr     r0, [r4, #0x50]
    cmp     r0, #0
    bne     fl_park
    FL_STILL r0
    movne   r5, #0
    bne     fl_wait
    /* Require one second of uninterrupted stable STILL, not an early boot
     * status word. No change in CINE, playback or a lever transition. */
    add     r5, r5, #1
    cmp     r5, #10
    blo     fl_wait
    ldr     ip, =0xC0057AE8        @ native settings facade (same as shell)
    blx     ip
    mov     r6, r0
    cmp     r6, #0
    moveq   r5, #0
    beq     fl_wait
    /* Recheck after obtaining the facade; a user selection cancels us. */
    ldr     r0, [r4, #0x50]
    cmp     r0, #0
    bne     fl_park
    FL_STILL r0
    movne   r5, #0
    bne     fl_wait
    mov     r0, #3
    str     r0, [r4, #0x50]
    mov     r0, #17               @ same private selection as GUI row 16
    str     r0, [r4, #P_PEND]
    mov     r0, r6
    mov     r1, #12               @ native OFF; LV Boost owns private flag
    mov     r2, #1
    ldr     ip, =0xC005C958        @ native SetColorMode, with notifications
    blx     ip
    mov     r0, r6
    ldr     ip, =0xC005C990        @ read back native color, no retry loop
    blx     ip
    cmp     r0, #12
    bne     fl_failed
    ldr     r0, [r4, #P_FLAG]
    cmp     r0, #1
    bne     fl_failed
    mov     r0, #1
    str     r0, [r4, #0x50]
    mov     r3, r4
    LV_SAVE_SETTINGS
    b       fl_park
fl_failed:
    mov     r0, #0
    str     r0, [r4, #P_PEND]
    mov     r0, #4
    str     r0, [r4, #0x50]
fl_park:
    movw    r0, #60000
    ldr     ip, =0xC01F89C4
    blx     ip
    b       fl_park
    .ltorg
