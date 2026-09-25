.syntax unified
.arm
.text
/* Four-box completion, called by stage2 before the staging buffer is freed.
 * Included immediately after stage2's local .Ls2_splash_finish label.
 * Native osdfile ABI: (printf_ctx, 6, {path, flag, monitor, w, h, offset}).
 * Original build displayed the artwork on hardware, but clear-only restoration
 * left static UI missing and stale artwork flashing (user report 2026-09-24).
 * The force-redraw correction below is not yet hardware verified.
 * File/allocation errors return from osdfile; UI restoration still runs.
 * WIDTH/HEIGHT/offset/delay come from the same module that generates the asset.
 * Native redraw request is source-confirmed in blk_c05.c: CYC_DRAW returns the
 * existing manager; 0xC0527DD8(manager, group, 1) sets that group's clear mode
 * to transparent under the controller mutex and marks the group pending.
 * Clear + wake alone does NOT invalidate the UI's per-buffer dirty rectangles.
 * Use the firmware's ReqForceDraw packet via 0xC0527E68: byte 0 queues all
 * groups, byte 1 sets DrawThread flag 0x10 -> draw context[1] -> Uic mode 2.
 * Mode 2 seeds a full rectangle into the native buffer-history ring, so later
 * buffers are repaired too. Priority -1 and callback 0 change neither.
 * The restored native draw task owns the actual clear/redraw/present sequence;
 * no callback or retained pointer may refer to this temporary staging image.
 */
.macro UI_ADDR reg, value
    movw \reg, #:lower16:\value
    movt \reg, #:upper16:\value
.endm
.macro UI_CALL target
    UI_ADDR r8, \target
    blx r8
.endm
    @ Keep string addresses close to setup: ARM ADR has an encoded immediate.
    b ui_begin
ui_no_output:
    mov r0, #0
    bx lr
.balign 4
ui_path:   .asciz "\\FPSUPUI\\4.BIN"
ui_zero:   .asciz "0"
ui_width:  .asciz SPLASH_WIDTH_TEXT
ui_height: .asciz SPLASH_HEIGHT_TEXT
ui_offset: .asciz SPLASH_OFFSET_TEXT
.balign 4
ui_begin:
    push {r4, r5, r6, r7, r8, lr}
    sub sp, sp, #32                    @ context + six argv pointers, 8-aligned
    adr r0, ui_no_output
    str r0, [sp]                       @ native handler only reads ctx[0]
    mov r4, sp
    adr r0, ui_path
    str r0, [sp, #4]
    adr r0, ui_zero
    str r0, [sp, #8]
    str r0, [sp, #12]
    adr r0, ui_width
    str r0, [sp, #16]
    adr r0, ui_height
    str r0, [sp, #20]
    adr r0, ui_offset
    str r0, [sp, #24]
    mov r6, #3
1:  mov r0, r4
    mov r1, #6
    add r2, sp, #4
    UI_CALL 0xC03E4270                 @ direct osdfile; no nested dispatcher
    subs r6, r6, #1
    bne 1b
    movw r0, #SPLASH_HOLD_MS
    UI_CALL 0xC03705D8                 @ native sleep(ms); yields, no new task
    add sp, sp, #32
    UI_ADDR r0, 0xC0528700
    ldr r1, [r0]
    UI_ADDR r2, 0xE12FFF1E
    cmp r1, r2                        @ do not remove a foreign hook
    bne 2f
    UI_ADDR r1, 0xE92D4BF0
    str r1, [r0]
    UI_CALL 0xC000E91C                 @ publish restored firmware D then I
    UI_CALL 0xC000EABC
    UI_CALL 0xC05278F8                 @ CYC_DRAW: existing native manager
    mov r4, r0
    mov r1, #0
    mov r2, #1
    UI_CALL 0xC0527DD8                 @ main layer: native transparent clear
    mov r0, r4
    mov r1, #1
    mov r2, #1
    UI_CALL 0xC0527DD8                 @ sublayer: native transparent clear
    mov r0, r4
    adr r1, ui_redraw_request
    UI_CALL 0xC0527E68                 @ native full repaint, not incremental wake
2:
    mov r0, #0
    pop {r4, r5, r6, r7, r8, pc}
ui_redraw_request:
    .word 0x00000101, 0xFFFFFFFF, 0   @ native ReqForceDraw, no retained callback
