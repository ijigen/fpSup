.syntax unified
.arm
.text

/*
 * Power/clock-only one-shot at the verified live FHD call C0722AFC.
 *
 * This validates the already-observed FHD segment arguments, but does not
 * modify the DNG or segment.  It does not allocate memory, call a codec wrapper,
 * or write codec globals.  It answers only whether this exact writer task can
 * acquire and release power domain 3 and clock domain 5 while the codec is idle.
 *
 * Cleanup is ownership-aware:
 *   power-on failed  -> release nothing
 *   clock-on failed  -> release power only
 *   clock-on worked  -> release clock; release power only if clock-off worked
 *
 * The last rule matches the firmware's own teardown.  Cutting power after a
 * failed clock-off could leave an enabled clock feeding an unpowered domain.
 *
 * The call-site word is restored before the first firmware call.  The original
 * args/LR are restored and FUN_c069ac88 is always tail-called.
 */

.equ HOOK_SITE,       0xC0722AFC
.equ HOOK_ORIG,       0xEBFDE061
.equ REAL_WRITE,      0xC069AC88
.equ STATE,           0xC072F700
.equ DONE_MAGIC,      0x454E4F44
.equ PREFLIGHT_MAGIC, 0x52575050       /* "PPWR" little-endian */

.equ F_PWR,           0xC0708C61       /* Thumb */
.equ F_CLK,           0xC07095A9       /* Thumb */
.equ CODEC_MODE,      0xC37CF87C

.equ EXPECTED_LR,     0xC0722B00
.equ EXPECTED_LEN,    0x00318200
.equ TIFF_MAGIC,      0x002A4949
.equ PIXEL_OFFSET,    0x00013400

/* First nine words retain exact_dng_writer_probe's transaction contract. */
.equ S_COUNT,         0x00
.equ S_R0,            0x04
.equ S_R1,            0x08
.equ S_R2,            0x0C
.equ S_LR,            0x10
.equ S_BUF,           0x14
.equ S_LEN,           0x18
.equ S_DONE,          0x1C
.equ S_RESTORED,      0x20
.equ S_PHASE,         0x24             /* 0 = power preflight */
.equ S_STAGE,         0x28
.equ S_ERROR,         0x2C
.equ S_CODEC_MODE,    0x30
.equ S_SRC,           0x34
.equ S_CLEANUP_ERROR, 0x38
.equ S_PWR_ON,        0x68
.equ S_CLK_ON,        0x6C
.equ S_CLK_OFF,       0x70
.equ S_PWR_OFF,       0x74
.equ S_PREFLIGHT,     0xD4

.equ ERR_KIND,        1
.equ ERR_SEG_PTR,     2
.equ ERR_LR,          3
.equ ERR_LENGTH,      4
.equ ERR_BUFFER,      5
.equ ERR_TIFF,        6
.equ ERR_SRC_ALIGN,   7
.equ ERR_MODE_BUSY,   8
.equ ERR_RESTORE,     9
.equ ERR_PWR_ON,      13
.equ ERR_CLK_ON,      14
.equ ERR_CLK_OFF,     15
.equ ERR_PWR_OFF,     16

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

.global probe_entry
probe_entry:
    push    {r0, r1, r2, r3, r4, r5, r12, lr}

    LDA     r4, STATE
    ldr     r12, [r4, #S_COUNT]
    add     r12, r12, #1
    str     r12, [r4, #S_COUNT]
    cmp     r12, #1
    bne     tail_call

    str     r0, [r4, #S_R0]
    str     r1, [r4, #S_R1]
    str     r2, [r4, #S_R2]
    str     lr, [r4, #S_LR]
    mov     r0, #1
    str     r0, [r4, #S_STAGE]

    /* Restore first: a later failure cannot leave future frames hooked. */
    LDA     r1, HOOK_SITE
    LDA     r2, HOOK_ORIG
    str     r2, [r1]
    ldr     r12, [r1]
    str     r12, [r4, #S_RESTORED]
    mov     r0, #2
    str     r0, [r4, #S_STAGE]

    cmp     r12, r2
    bne     restore_failed

    /* -1 means "not called", distinct from a successful zero return. */
    mvn     r0, #0
    str     r0, [r4, #S_PWR_ON]
    str     r0, [r4, #S_CLK_ON]
    str     r0, [r4, #S_CLK_OFF]
    str     r0, [r4, #S_PWR_OFF]

    /* Gate the probe to the exact FHD CinemaDNG shape seen live. */
    ldr     r0, [r4, #S_R2]
    cmp     r0, #2
    bne     wrong_kind

    ldr     r1, [r4, #S_R1]
    cmp     r1, #0
    beq     bad_seg_ptr
    tst     r1, #3
    bne     bad_seg_ptr

    LDA     r12, EXPECTED_LR
    ldr     r0, [r4, #S_LR]
    cmp     r0, r12
    bne     wrong_lr

    ldr     r5, [r1]
    str     r5, [r4, #S_BUF]
    cmp     r5, #0
    beq     bad_buffer
    ldr     r0, [r1, #4]
    str     r0, [r4, #S_LEN]
    LDA     r12, EXPECTED_LEN
    cmp     r0, r12
    bne     wrong_length

    ldr     r0, [r5]
    LDA     r12, TIFF_MAGIC
    cmp     r0, r12
    bne     wrong_tiff

    LDA     r0, PIXEL_OFFSET
    adds    r5, r5, r0
    bcs     bad_src_alignment
    str     r5, [r4, #S_SRC]
    /* Source is word aligned already; bits 2..9 complete the 1 KB test. */
    tst     r5, #0x3FC
    bne     bad_src_alignment

    LDA     r12, CODEC_MODE
    ldr     r0, [r12]
    str     r0, [r4, #S_CODEC_MODE]
    cmp     r0, #0
    bne     codec_busy

    mov     r0, #3
    str     r0, [r4, #S_STAGE]

    mov     r0, #4
    str     r0, [r4, #S_STAGE]
    mov     r0, #1
    LDA     r12, F_PWR
    blx     r12
    str     r0, [r4, #S_PWR_ON]
    cmp     r0, #0
    bne     power_on_failed

    mov     r0, #5
    str     r0, [r4, #S_STAGE]
    mov     r0, #5
    mov     r1, #1
    LDA     r12, F_CLK
    blx     r12
    str     r0, [r4, #S_CLK_ON]
    cmp     r0, #0
    bne     cleanup_power_after_clock_failure

    mov     r0, #6
    str     r0, [r4, #S_STAGE]
    mov     r0, #5
    mov     r1, #0
    LDA     r12, F_CLK
    blx     r12
    str     r0, [r4, #S_CLK_OFF]
    cmp     r0, #0
    bne     clock_off_failed

    mov     r0, #7
    str     r0, [r4, #S_STAGE]
    mov     r0, #0
    LDA     r12, F_PWR
    blx     r12
    str     r0, [r4, #S_PWR_OFF]
    cmp     r0, #0
    bne     power_off_failed

    LDA     r0, PREFLIGHT_MAGIC
    str     r0, [r4, #S_PREFLIGHT]
    b       finish

cleanup_power_after_clock_failure:
    mov     r0, #ERR_CLK_ON
    str     r0, [r4, #S_ERROR]
    mov     r0, #7
    str     r0, [r4, #S_STAGE]
    mov     r0, #0
    LDA     r12, F_PWR
    blx     r12
    str     r0, [r4, #S_PWR_OFF]
    cmp     r0, #0
    beq     finish
    mov     r0, #ERR_PWR_OFF
    str     r0, [r4, #S_CLEANUP_ERROR]
    b       finish

restore_failed:
    mov     r0, #ERR_RESTORE
    str     r0, [r4, #S_ERROR]
    b       finish
wrong_kind:
    mov     r0, #ERR_KIND
    str     r0, [r4, #S_ERROR]
    b       finish
bad_seg_ptr:
    mov     r0, #ERR_SEG_PTR
    str     r0, [r4, #S_ERROR]
    b       finish
wrong_lr:
    mov     r0, #ERR_LR
    str     r0, [r4, #S_ERROR]
    b       finish
wrong_length:
    mov     r0, #ERR_LENGTH
    str     r0, [r4, #S_ERROR]
    b       finish
bad_buffer:
    mov     r0, #ERR_BUFFER
    str     r0, [r4, #S_ERROR]
    b       finish
wrong_tiff:
    mov     r0, #ERR_TIFF
    str     r0, [r4, #S_ERROR]
    b       finish
bad_src_alignment:
    mov     r0, #ERR_SRC_ALIGN
    str     r0, [r4, #S_ERROR]
    b       finish
codec_busy:
    mov     r0, #ERR_MODE_BUSY
    str     r0, [r4, #S_ERROR]
    b       finish

power_on_failed:
    mov     r0, #ERR_PWR_ON
    str     r0, [r4, #S_ERROR]
    b       finish
clock_off_failed:
    mov     r0, #ERR_CLK_OFF
    str     r0, [r4, #S_ERROR]
    b       finish
power_off_failed:
    mov     r0, #ERR_PWR_OFF
    str     r0, [r4, #S_ERROR]

finish:
    dmb     sy
    LDA     r0, DONE_MAGIC
    str     r0, [r4, #S_DONE]

tail_call:
    pop     {r0, r1, r2, r3, r4, r5, r12, lr}
    ldr     pc, [pc, #-4]
    .word   REAL_WRITE
