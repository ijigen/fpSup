.syntax unified
.arm
.text
/* ============================================================================
 * recprobe — do everything the gyro logger reads while recording, and nothing
 *            it writes.
 * ============================================================================
 *
 * The logger takes the camera down the moment recording starts, and the idle
 * path is fine, so the fault is somewhere in the recording path. That path both
 * reads a chain of firmware pointers and copies into buffers; this does the
 * first half only. Survive a recording and the fault is in the copy; freeze and
 * it is in the reads, and the marker says which one.
 *
 * Scratch at 0xC072E800, above this code and below the shell:
 *      +0x00  calls
 *      +0x04  furthest marker reached
 *      +0x08  recording flag from LensIsTr+0x157
 *      +0x0C  ring base
 *      +0x10  ring head
 *      +0x14  timestamp
 *      +0x18  path manager: camera letter, reel, clip
 * ========================================================================== */

.equ HOOK_TARGET,   0xC01EC6F9
.equ SCRATCH,       0xC072E800
.equ REC_STATE,     0xC035B2D0     /* -> LensIsTr singleton; +0x157 is the flag */
.equ GYRO_DESC_PTR, 0xC31E3FCC
.equ PATH_MGR_SD,   0xC3438400
.equ TICK_US,       0xC002B6E0

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

/* r6, not r0 -- r0 carries the value the routine just returned, and marking
 * with it destroyed the pointer the next instruction dereferences. And keep the
 * furthest marker rather than the last, or the idle calls after a recording
 * erase what the recording reached. */
.macro MARK n
    mov     r6, #\n
    ldr     r7, [r4, #4]
    cmp     r6, r7
    strhi   r6, [r4, #4]
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
    MARK    1

    LDA     ip, REC_STATE
    blx     ip
    MARK    2
    ldrb    r5, [r0, #0x157]
    str     r5, [r4, #8]
    MARK    3
    cmp     r5, #0
    beq     out

    LDA     r0, GYRO_DESC_PTR
    ldr     r0, [r0]
    MARK    4
    ldr     r8, [r0, #0x60]
    str     r8, [r4, #0x0C]
    MARK    5
    ldr     r5, [r8]
    str     r5, [r4, #0x10]
    MARK    6

    /* Record what the stack actually looks like here, then force it aligned
     * before calling out.  AAPCS promises eight bytes at a call; a callback
     * entered from the firmware's own interior does not have to keep that
     * promise, and 0xC002B6E0 handles a 64-bit microsecond value -- one LDRD on
     * a four-aligned stack is a data abort, in the thread that feeds the
     * display, which is what "花屏" looks like. */
    /* OR it in, do not store it: this runs fifty times a second and the idle
     * calls after a recording would otherwise overwrite whatever the recording
     * saw. The same mistake hid the recording flag one round ago. */
    mov     r0, sp
    and     r0, r0, #7
    ldr     r6, [r4, #0x24]
    orr     r0, r0, r6
    str     r0, [r4, #0x24]

    mov     r5, sp
    bic     sp, sp, #7
    LDA     ip, TICK_US
    blx     ip
    mov     sp, r5
    str     r0, [r4, #0x14]
    MARK    7

    /* Once, on the first recording callback -- which is what the logger does.
     * Reading it fifty times a second is not a faithful model of
     * recording_started, and the clip number is exactly what the firmware is
     * updating at the moment recording begins. */
    ldr     r0, [r4, #0x28]
    cmp     r0, #0
    bne     out
    mov     r0, #1
    str     r0, [r4, #0x28]

    LDA     r8, PATH_MGR_SD
    ldrb    r0, [r8, #8]
    ldr     r1, [r8, #0x0C]
    ldr     r2, [r8, #0x10]
    str     r0, [r4, #0x18]
    str     r1, [r4, #0x1C]
    str     r2, [r4, #0x20]
    MARK    8

out:
    mov     r0, r11
    pop     {r3, r4, r5, r6, r7, r8, r9, r10, r11, pc}
