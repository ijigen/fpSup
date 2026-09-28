.syntax unified
.arm
.text

/*
 * Mode-gated 3032x2012 canvas hook -- isolation-safe successor to rowpatch_v4.
 *
 * WHY THIS EXISTS
 * ---------------
 * rowpatch_v4 gates ONLY on the geometry row being 1936x1090, so it also fires
 * for other FHD CinemaDNG framerates (e.g. FHD/25) that build the same row and
 * stretches them to 3032x2012 against a sensor that is not the open-gate mode --
 * the corruption of those modes.
 *
 * THE GATE, MEASURED ON HARDWARE (SIGMA fp Ver.5.02, 2026-09-10, USB shell):
 *   The FieldAngle build selector r5 is 175 for FHD/29.97 CinemaDNG (open gate)
 *   and 180 for FHD/25 CinemaDNG. Verified stable across standby AND an actual
 *   take: the hook fired 474x during a ~3s open-gate record, r5 == 175 every
 *   time. r5 is passed straight into the hook so it is correct at hook time --
 *   unlike 0xC343B590, which only becomes 117 mid-take and made the hook never
 *   fire (that was the bug that broke open gate).
 *
 * So: rewrite only when armed AND the row is 1936x1090 AND r5 == 175. Every
 * other framerate/mode falls through as a no-op and records exactly as stock.
 *
 * ABI (unchanged from v4):
 *   r4 = FieldAngle object, r4+0x5C = geometry row, r5 = selector.
 *   Hook site 0xC043A19C uses BL; displaced instruction is `mov r0,r4`.
 *   Returns through LR after replaying it.
 */

.equ LOG,            0xC072FA00     /* telemetry: [0]=hits [4]=selector [8..]=orig */
.equ ROW,            0x5C
.equ SEL_OPENGATE,   175            /* measured FHD/29.97 CinemaDNG selector (0xAF) */
.equ ARMED,          0xC072FA10     /* controller flag: nonzero = feature on */

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

.macro PUT off, val
    movw    r3, #\val
    movw    r0, #\off
    str     r3, [r1, r0]
.endm

.global entry
entry:
    push    {r0, r1, r2, r3, ip, lr}
    add     r1, r4, #ROW
    LDA     ip, LOG

    /* Gate 1: controller must have the feature armed. */
    LDA     r0, ARMED
    ldr     r0, [r0]
    cmp     r0, #0
    beq     out

    /* Gate 2: the shipping FHD CinemaDNG row only. */
    ldr     r3, [r1]
    movw    r0, #1936
    cmp     r3, r0
    bne     out
    ldr     r3, [r1, #4]
    movw    r0, #1090
    cmp     r3, r0
    bne     out

    /* Gate 3 (the isolation fix): open-gate selector only. Measured on hardware:
     * 175 = FHD/29.97 CinemaDNG (open gate), 180 = FHD/25. Any other framerate
     * that builds a 1936x1090 row falls through untouched and records as stock. */
    movw    r0, #SEL_OPENGATE
    cmp     r5, r0
    bne     out

    /* Preserve the first pre-overwrite producer fields for diagnosis. */
    ldr     r0, [ip]
    cmp     r0, #0
    bne     patch
    str     r5, [ip, #4]
    movw    r0, #0x0D8
    ldr     r3, [r1, r0]
    str     r3, [ip, #8]
    movw    r0, #0x0E0
    ldr     r3, [r1, r0]
    str     r3, [ip, #12]

patch:
    PUT     0x000, 3032       /* base */
    PUT     0x004, 2012
    PUT     0x024, 3008       /* active; yields crop origin (12,6) */
    PUT     0x02C, 2000
    PUT     0x0D8, 3032       /* producer-side width/height pair */
    PUT     0x0E0, 2012
    PUT     0x0DC, 3032       /* size-getter override */
    PUT     0x0E4, 2012
    PUT     0x0F4, 3032       /* input */
    PUT     0x0F8, 2012

    ldr     r3, [ip]
    add     r3, r3, #1
    str     r3, [ip]

out:
    pop     {r0, r1, r2, r3, ip, lr}
    mov     r0, r4
    bx      lr
