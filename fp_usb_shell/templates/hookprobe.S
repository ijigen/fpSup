.syntax unified
.arm
.text
/* ============================================================================
 * hookprobe — the smallest thing that can sit in the gyro callback.
 * ============================================================================
 *
 * Call what was displaced, count, return.  Nothing else.  When a hook takes the
 * camera down there is no way to read anything back, so the way to find out
 * which part did it is to start from the part that cannot and add one piece at
 * a time.
 *
 * It also answers a question worth knowing on its own: how often the site
 * actually fires. The counter is readable while it runs.
 *
 *      0xC072F5F0  call count
 *      0xC072F5F4  the value the displaced routine returned, most recently
 *
 * Load at 0xC072DE64 and point 0xC00D0794 at it.
 * ========================================================================== */

.equ HOOK_TARGET, 0xC01EC6F9      /* what the displaced BLX called (thumb) */
.equ COUNT,       0xC072F5F0

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

.global probe
probe:
    /* Ten registers keeps the stack 8-byte aligned across the call. */
    push    {r3, r4, r5, r6, r7, r8, r9, r10, r11, lr}

    LDA     ip, HOOK_TARGET
    blx     ip
    mov     r11, r0

    LDA     r4, COUNT
    ldr     r5, [r4]
    add     r5, r5, #1
    str     r5, [r4]
    str     r11, [r4, #4]

    mov     r0, r11
    pop     {r3, r4, r5, r6, r7, r8, r9, r10, r11, pc}
