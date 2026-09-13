.syntax unified
.arm
.text

/*
 * One-shot FHD codec probe at the verified live call C0722AFC.
 *
 * PHASE=0 is the required context preflight: allocate one aligned 4 MiB block,
 * prove the non-overlapping codec layout, and acquire/release power 3 + clock 5.
 * PHASE=1 performs one encode into that allocation and discards the result.
 * The live installer refuses PHASE=1 until the PHASE=0 context result has been
 * reviewed explicitly.
 *
 * Neither phase stores through the DNG buffer or the segment pointer.  The
 * original buffer is source-only, seg[1] remains 0x318200, and the real
 * FUN_c069ac88 is tail-called with its original r0-r3/r12/LR.
 *
 * Codec layout inside the single allocator-owned block:
 *
 *   handle + 000000 .. 304FFF   compressed output/work, cap 0x305000
 *   handle + 305000              overrun guard
 *   handle + 306000 .. 30602F   final 12-word size table (init[7])
 *   handle + 306030              table guard
 *   handle + 306400 .. 30642F   codec temporary size table
 *   handle + 306430              temporary-table guard
 *
 * F_GET is asked for 0x400 alignment directly.  The low 0x4xxxxxxx handle is
 * handed to the codec; FUN_c001b668's cached 0xCxxxxxxx alias is never used.
 */

#ifndef PHASE
#define PHASE 0
#endif

.equ HOOK_SITE,       0xC0722AFC
.equ HOOK_ORIG,       0xEBFDE061
.equ REAL_WRITE,      0xC069AC88
.equ STATE,           0xC072F700
.equ DONE_MAGIC,      0x454E4F44
.equ GUARD_MAGIC,     0xA55AA55A

.equ WIDTH,           1936
.equ HEIGHT,          1090
.equ DEPTH,           0
.equ TILE_W,          512
.equ TILE_H,          512
.equ TILE_COUNT,      12
.equ DNG_LEN,         0x318200
.equ PIXEL_OFF,       0x13400
.equ RAW_BYTES,       0x304CB0
.equ ALLOC_SIZE,      0x400000
.equ WORK_CAP,        0x305000
.equ TABLE_OFF,       0x306000
.equ TABLE_TMP_OFF,   0x306400

.equ F_ALLOC,         0xC001CF78
.equ F_GET,           0xC001D038
.equ F_INIT,          0xC05A6890
.equ F_ENC,           0xC05A6920
.equ F_SIZE,          0xC05A6990
.equ F_CLOCK,         0xC002B6E0
.equ F_PWR,           0xC0708C61       /* Thumb */
.equ F_CLK,           0xC07095A9       /* Thumb */

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
.equ S_PHASE,         0x24
.equ S_STAGE,         0x28
.equ S_ERROR,         0x2C
.equ S_ALLOCATOR,     0x30
.equ S_HANDLE,        0x34
.equ S_ALLOC_END,     0x38
.equ S_WORK_BASE,     0x3C
.equ S_WORK_END,      0x40
.equ S_WORK_GUARD,    0x44
.equ S_TABLE_BASE,    0x48
.equ S_TABLE_TMP,     0x4C
.equ S_T0,            0x50
.equ S_T1,            0x54
.equ S_INIT_RET,      0x58
.equ S_ENC_RET,       0x5C
.equ S_SIZE_RET,      0x60
.equ S_COMP_SIZE,     0x64
.equ S_PWR_ON,        0x68
.equ S_CLK_ON,        0x6C
.equ S_CLK_OFF,       0x70
.equ S_PWR_OFF,       0x74
.equ S_HDR_BEFORE,    0x78
.equ S_HDR_AFTER,     0x7C
.equ S_PIX0_BEFORE,   0x80
.equ S_PIX0_AFTER,    0x84
.equ S_PIXN_BEFORE,   0x88
.equ S_PIXN_AFTER,    0x8C
.equ S_LEN_AFTER,     0x90
.equ S_GUARD_WORK,    0x94
.equ S_GUARD_TABLE,   0x98
.equ S_GUARD_TMP,     0x9C
.equ S_TILE_COUNT,    0xA0
.equ S_TILE0,         0xA4             /* 12 words, through +0xD0 */

.equ ERR_KIND,        1
.equ ERR_SEG_NULL,    2
.equ ERR_LENGTH,      3
.equ ERR_BUF_NULL,    4
.equ ERR_TIFF,        5
.equ ERR_SRC_ALIGN,   6
.equ ERR_ALLOCATOR,   7
.equ ERR_ALLOC,       8
.equ ERR_ALIAS,       9
.equ ERR_ALIGN,       10
.equ ERR_RANGE,       11
.equ ERR_OVERLAP,     12
.equ ERR_PWR_ON,      13
.equ ERR_CLK_ON,      14
.equ ERR_CLK_OFF,     15
.equ ERR_PWR_OFF,     16
.equ ERR_INIT,        17
.equ ERR_ENCODE,      18
.equ ERR_SIZE_CALL,   19
.equ ERR_SIZE_RANGE,  20
.equ ERR_GUARD,       21
.equ ERR_SOURCE,      22

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

.macro FAIL code, target
    mov     r0, #\code
    str     r0, [r4, #S_ERROR]
    b       \target
.endm

.global probe_entry
probe_entry:
    /* 12 words: preserve every register used here and keep SP 8-byte aligned. */
    push    {r0, r1, r2, r3, r4, r5, r6, r7, r8, r10, r12, lr}

    LDA     r4, STATE
    ldr     r3, [r4, #S_COUNT]
    add     r3, r3, #1
    str     r3, [r4, #S_COUNT]
    cmp     r3, #1
    bne     tail_call

    str     r0, [r4, #S_R0]
    str     r1, [r4, #S_R1]
    str     r2, [r4, #S_R2]
    str     lr, [r4, #S_LR]
    mov     r5, r1
    mov     r0, #PHASE
    str     r0, [r4, #S_PHASE]
    mov     r0, #1
    str     r0, [r4, #S_STAGE]

    /* Restore before any pointer dereference or firmware call. */
    LDA     r7, HOOK_SITE
    LDA     r8, HOOK_ORIG
    str     r8, [r7]
    ldr     r8, [r7]
    str     r8, [r4, #S_RESTORED]
    mov     r0, #2
    str     r0, [r4, #S_STAGE]

    cmp     r2, #2
    bne     bad_kind
    cmp     r5, #0
    beq     bad_seg
    ldr     r6, [r5]
    ldr     r7, [r5, #4]
    str     r6, [r4, #S_BUF]
    str     r7, [r4, #S_LEN]
    LDA     r0, DNG_LEN
    cmp     r7, r0
    bne     bad_length
    cmp     r6, #0
    beq     bad_buf
    ldr     r0, [r6]
    str     r0, [r4, #S_HDR_BEFORE]
    LDA     r1, 0x002A4949
    cmp     r0, r1
    bne     bad_tiff
    LDA     r0, PIXEL_OFF
    add     r7, r6, r0                 /* source pixels, read-only */
    LDA     r0, 0x3FF
    tst     r7, r0
    bne     bad_src_align

    ldr     r0, [r7]
    str     r0, [r4, #S_PIX0_BEFORE]
    LDA     r1, RAW_BYTES - 4
    ldr     r0, [r7, r1]
    str     r0, [r4, #S_PIXN_BEFORE]
    mov     r0, #3
    str     r0, [r4, #S_STAGE]

    /* One allocator-owned block, directly aligned by F_GET's third argument. */
    mov     r0, #0
    LDA     r12, F_ALLOC
    blx     r12
    str     r0, [r4, #S_ALLOCATOR]
    cmp     r0, #0
    beq     bad_allocator
    mov     r8, r0

    sub     sp, sp, #8
    mov     r0, r8
    LDA     r1, ALLOC_SIZE
    LDA     r2, 0x400
    mov     r3, #0
    str     r3, [sp]                   /* fifth argument */
    LDA     r12, F_GET
    blx     r12
    add     sp, sp, #8
    mov     r8, r0                     /* low DMA handle, also work/output */
    str     r8, [r4, #S_HANDLE]
    cmp     r8, #0
    beq     bad_alloc
    mov     r0, r8, lsr #30
    cmp     r0, #1                     /* require 0x4xxxxxxx..0x7xxxxxxx */
    bne     bad_alias
    LDA     r0, 0x3FF
    tst     r8, r0
    bne     bad_align

    LDA     r0, ALLOC_SIZE
    adds    r1, r8, r0
    bcs     bad_range
    str     r1, [r4, #S_ALLOC_END]
    str     r8, [r4, #S_WORK_BASE]
    LDA     r0, WORK_CAP
    adds    r2, r8, r0
    bcs     bad_range
    str     r2, [r4, #S_WORK_END]
    str     r2, [r4, #S_WORK_GUARD]
    LDA     r0, TABLE_OFF
    adds    r3, r8, r0
    bcs     bad_range
    str     r3, [r4, #S_TABLE_BASE]
    LDA     r0, TABLE_TMP_OFF
    adds    r0, r8, r0
    bcs     bad_range
    str     r0, [r4, #S_TABLE_TMP]
    add     r12, r0, #0x34
    cmp     r12, r1
    bhi     bad_range

    /* Allocator range must be disjoint from the original DNG segment. */
    ldr     r0, [r4, #S_LEN]
    adds    r0, r6, r0
    bcs     bad_range
    cmp     r1, r6
    bls     ranges_ok
    cmp     r0, r8
    bls     ranges_ok
    b       bad_overlap

ranges_ok:
    LDA     r12, GUARD_MAGIC
    str     r12, [r2]
    str     r12, [r3, #0x30]
    ldr     r0, [r4, #S_TABLE_TMP]
    str     r12, [r0, #0x30]
    mov     r0, #4
    str     r0, [r4, #S_STAGE]

#if PHASE == 0
    /* Context-only. Do not pre-stage these calls before a later F_ENC; that
     * wrapper owns its own balanced power/clock/IRQ sequence. */
    mov     r0, #1
    LDA     r12, F_PWR
    blx     r12
    str     r0, [r4, #S_PWR_ON]
    cmp     r0, #0
    bne     preflight_pwr_failed

    mov     r0, #5
    mov     r1, #1
    LDA     r12, F_CLK
    blx     r12
    str     r0, [r4, #S_CLK_ON]
    cmp     r0, #0
    bne     preflight_clk_failed

    mov     r0, #5
    mov     r1, #0
    LDA     r12, F_CLK
    blx     r12
    str     r0, [r4, #S_CLK_OFF]

    mov     r0, #0
    LDA     r12, F_PWR
    blx     r12
    str     r0, [r4, #S_PWR_OFF]
    ldr     r1, [r4, #S_CLK_OFF]
    cmp     r1, #0
    bne     preflight_bad_clk_off
    cmp     r0, #0
    bne     preflight_bad_pwr_off
    mov     r0, #5
    str     r0, [r4, #S_STAGE]
    b       finish_checked

preflight_clk_failed:
    mov     r0, #0
    LDA     r12, F_PWR
    blx     r12
    str     r0, [r4, #S_PWR_OFF]
    FAIL    ERR_CLK_ON, finish_checked
preflight_pwr_failed:
    FAIL    ERR_PWR_ON, finish_checked
preflight_bad_clk_off:
    FAIL    ERR_CLK_OFF, finish_checked
preflight_bad_pwr_off:
    FAIL    ERR_PWR_OFF, finish_checked
#else
    /* Build initStruct (9 words) and encStruct (5 words) in a 64-byte frame. */
    sub     sp, sp, #0x40
    LDA     r0, WIDTH
    str     r0, [sp, #0x00]
    str     r0, [sp, #0x28]
    LDA     r0, HEIGHT
    str     r0, [sp, #0x04]
    str     r0, [sp, #0x2C]
    mov     r0, #DEPTH
    str     r0, [sp, #0x08]
    str     r0, [sp, #0x30]
    LDA     r0, TILE_W
    str     r0, [sp, #0x0C]
    str     r0, [sp, #0x10]
    str     r0, [sp, #0x34]
    str     r0, [sp, #0x38]
    str     r7, [sp, #0x14]            /* src = original pixels; read-only */
    str     r8, [sp, #0x18]            /* init[6] compressed output/work */
    ldr     r0, [r4, #S_TABLE_BASE]
    str     r0, [sp, #0x1C]            /* init[7] size-table base */
    mov     r0, #0
    str     r0, [sp, #0x20]

    mov     r0, sp
    LDA     r12, F_INIT
    blx     r12
    str     r0, [r4, #S_INIT_RET]
    cmp     r0, #1
    bne     encode_init_failed
    mov     r0, #5
    str     r0, [r4, #S_STAGE]

    LDA     r12, F_CLOCK
    blx     r12
    str     r0, [r4, #S_T0]
    add     r0, sp, #0x28
    LDA     r12, F_ENC
    blx     r12
    str     r0, [r4, #S_ENC_RET]
    LDA     r12, F_CLOCK
    blx     r12
    str     r0, [r4, #S_T1]
    ldr     r0, [r4, #S_ENC_RET]
    cmp     r0, #1
    bne     encode_call_failed
    mov     r0, #6
    str     r0, [r4, #S_STAGE]

    add     r0, r4, #S_TILE0
    mov     r1, #1
    LDA     r12, F_SIZE
    blx     r12
    str     r0, [r4, #S_SIZE_RET]
    cmp     r0, #1
    bne     encode_size_failed

    add     r3, r4, #S_TILE0
    mov     r2, #TILE_COUNT
    mov     r1, #0
sum_sizes:
    ldr     r0, [r3], #4
    adds    r1, r1, r0
    bcs     encode_size_range
    subs    r2, r2, #1
    bne     sum_sizes
    str     r1, [r4, #S_COMP_SIZE]
    cmp     r1, #0
    beq     encode_size_range
    LDA     r0, WORK_CAP
    cmp     r1, r0
    bhi     encode_size_range
    mov     r0, #TILE_COUNT
    str     r0, [r4, #S_TILE_COUNT]
    mov     r0, #7
    str     r0, [r4, #S_STAGE]
    add     sp, sp, #0x40
    b       finish_checked

encode_init_failed:
    add     sp, sp, #0x40
    FAIL    ERR_INIT, finish_checked
encode_call_failed:
    add     sp, sp, #0x40
    FAIL    ERR_ENCODE, finish_checked
encode_size_failed:
    add     sp, sp, #0x40
    FAIL    ERR_SIZE_CALL, finish_checked
encode_size_range:
    add     sp, sp, #0x40
    FAIL    ERR_SIZE_RANGE, finish_checked
#endif

finish_checked:
    ldr     r0, [r4, #S_WORK_GUARD]
    ldr     r1, [r0]
    str     r1, [r4, #S_GUARD_WORK]
    ldr     r0, [r4, #S_TABLE_BASE]
    ldr     r2, [r0, #0x30]
    str     r2, [r4, #S_GUARD_TABLE]
    ldr     r0, [r4, #S_TABLE_TMP]
    ldr     r3, [r0, #0x30]
    str     r3, [r4, #S_GUARD_TMP]
    LDA     r0, GUARD_MAGIC
    cmp     r1, r0
    cmpeq   r2, r0
    cmpeq   r3, r0
    beq     finish_source
    ldr     r1, [r4, #S_ERROR]
    cmp     r1, #0
    moveq   r1, #ERR_GUARD
    streq   r1, [r4, #S_ERROR]

finish_source:
    ldr     r0, [r6]
    str     r0, [r4, #S_HDR_AFTER]
    ldr     r1, [r7]
    str     r1, [r4, #S_PIX0_AFTER]
    LDA     r2, RAW_BYTES - 4
    ldr     r2, [r7, r2]
    str     r2, [r4, #S_PIXN_AFTER]
    ldr     r3, [r5, #4]
    str     r3, [r4, #S_LEN_AFTER]
    ldr     r12, [r4, #S_HDR_BEFORE]
    cmp     r0, r12
    ldreq   r12, [r4, #S_PIX0_BEFORE]
    cmpeq   r1, r12
    ldreq   r12, [r4, #S_PIXN_BEFORE]
    cmpeq   r2, r12
    LDA     r12, DNG_LEN
    cmpeq   r3, r12
    beq     complete
    ldr     r1, [r4, #S_ERROR]
    cmp     r1, #0
    moveq   r1, #ERR_SOURCE
    streq   r1, [r4, #S_ERROR]
    b       complete

bad_kind:       FAIL ERR_KIND, complete
bad_seg:        FAIL ERR_SEG_NULL, complete
bad_length:     FAIL ERR_LENGTH, complete
bad_buf:        FAIL ERR_BUF_NULL, complete
bad_tiff:       FAIL ERR_TIFF, complete
bad_src_align:  FAIL ERR_SRC_ALIGN, complete
bad_allocator:  FAIL ERR_ALLOCATOR, finish_source
bad_alloc:      FAIL ERR_ALLOC, finish_source
bad_alias:      FAIL ERR_ALIAS, finish_source
bad_align:      FAIL ERR_ALIGN, finish_source
bad_range:      FAIL ERR_RANGE, finish_source
bad_overlap:    FAIL ERR_OVERLAP, finish_source

complete:
    mov     r0, #8
    str     r0, [r4, #S_STAGE]
    LDA     r0, DONE_MAGIC
    str     r0, [r4, #S_DONE]

tail_call:
    pop     {r0, r1, r2, r3, r4, r5, r6, r7, r8, r10, r12, lr}
    ldr     pc, [pc, #-4]
    .word   REAL_WRITE
