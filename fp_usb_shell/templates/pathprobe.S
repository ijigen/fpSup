.syntax unified
.arm
.text
/* ============================================================================
 * pathprobe — read the path manager from the callback, with nothing else in it.
 * ============================================================================
 *
 * Six runs now say the same thing: a probe that reads 0xC3438400 inside the
 * gyro callback takes the camera down, and one that does not survives. The
 * shell reads the same address without trouble -- but from a task, not from
 * here.
 *
 * So read it unconditionally, recording or not. If that is enough to freeze,
 * the address is unreachable from this context and nothing about recording
 * matters; if it is not, the fault is timing around record start, and no amount
 * of staring at the loads will show it.
 *
 *      0xC072E800  calls
 *      +0x04       camera letter, +0x08 reel, +0x0C clip
 * ========================================================================== */

.equ HOOK_TARGET, 0xC01EC6F9
.equ SCRATCH,     0xC072E800
.equ PATH_MGR_SD, 0xC3438400

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

.global probe
probe:
    push    {r3, r4, r5, r6, r7, r8, r9, r10, r11, lr}
    LDA     ip, HOOK_TARGET
    blx     ip
    mov     r11, r0

    LDA     r4, SCRATCH
    ldr     r0, [r4]
    add     r0, r0, #1
    str     r0, [r4]

    LDA     r8, PATH_MGR_SD
    ldrb    r0, [r8, #8]
    ldr     r1, [r8, #0x0C]
    ldr     r2, [r8, #0x10]
    str     r0, [r4, #4]
    str     r1, [r4, #8]
    str     r2, [r4, #0x0C]

    mov     r0, r11
    pop     {r3, r4, r5, r6, r7, r8, r9, r10, r11, pc}
