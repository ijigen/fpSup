.syntax unified
.arm
.text
/* ============================================================================
 * ljtime — time the lossless-JPEG engine from inside the still path.
 * ============================================================================
 *
 * The one number the compressed-CinemaDNG question hangs on is the engine's
 * real sustained Mpix/s, and the firmware's own pixels/32000 is a watchdog
 * deadline with roughly nine times' margin -- it proves the engine is faster
 * than 32 Mpix/s and nothing else.
 *
 * Calling the engine cold does not work: the power domain refuses the request
 * (FUN_c0708c60 -> -99) and so does clock domain 5, measured on hardware
 * 2026-08-30. The still path already owns both, so this measures from inside
 * it instead of trying to take them.
 *
 * Installed by replacing one word -- the `bl 0xC05A6920` at 0xC037E7AC -- with
 * a bl to `enc_timed`. Everything about the call is preserved: r0 goes in
 * untouched, the return value comes back untouched, and the caller at
 * 0xC037E7B0 cannot tell the difference.
 *
 * The clock is FUN_c002b6e0, which the gyro logger has used as its batch
 * timestamp for every take it has ever written. Borrowing a proven one beats
 * finding a new one.
 *
 * Results at SLOT, read over USB after a still:
 *      +0x00  t0            +0x04  t1
 *      +0x08  engine result (1 = success)
 *      +0x0C  width         +0x10  height
 *      +0x14  call count -- so a stale slot cannot be read as a fresh result
 *      +0x18  bitdepth code +0x1C  tileW        +0x20  tileH
 *
 * The last three matter because the fit's x-variable is the TILE-ALIGNED pixel
 * count, not width*height: the engine pads edge tiles to full size and codes
 * them (its own timeout is computed on the aligned count). The padding fraction
 * varies with aspect ratio -- 2.7% at 3:2, 6.4% at 16:9 -- which is the same
 * order as the effect being measured, so it cannot be left to assumption.
 *
 * SLOT can be overridden at assembly time with -DSLOT=0x... . The default sits
 * inside the gyro logger's resident range (0xC072E064..0xC072EFAC); check what
 * is actually resident before using it.
 */

#ifndef SLOT
#define SLOT 0xC072E080
#endif

.equ CLOCK,  0xC002B6E0          /* the logger's batch timestamp */
.equ ENCODE, 0xC05A6920          /* what the still path meant to call */

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

.global enc_timed
enc_timed:
    push    {r4, r5, r6, lr}
    mov     r4, r0                      @ &encStruct, kept for the geometry

    LDA     ip, CLOCK
    blx     ip
    mov     r5, r0

    mov     r0, r4
    LDA     ip, ENCODE
    blx     ip
    mov     r6, r0                      @ the caller's return value

    LDA     ip, CLOCK
    blx     ip

    LDA     r1, SLOT
    str     r5, [r1, #0]
    str     r0, [r1, #4]
    str     r6, [r1, #8]
    ldr     r2, [r4]
    str     r2, [r1, #12]
    ldr     r2, [r4, #4]
    str     r2, [r1, #16]
    ldr     r2, [r4, #8]                @ bitdepth code
    str     r2, [r1, #24]
    ldr     r2, [r4, #12]               @ tileW
    str     r2, [r1, #28]
    ldr     r2, [r4, #16]               @ tileH
    str     r2, [r1, #32]
    ldr     r2, [r1, #20]
    add     r2, r2, #1
    str     r2, [r1, #20]

    mov     r0, r6
    pop     {r4, r5, r6, pc}
