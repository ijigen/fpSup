.syntax unified
.arm
.text
/* ============================================================================
 * lvout — res-custom's main-output-descriptor hook (ogc.c ogc_out, og3kout)
 * for the isp_custom test install.  Position independent: data is pc-relative.
 *
 *   out   hook 0xC0437E98 = XC_LiveViewDispParam::v5 (r0 = the pairs, r1 = idx):
 *         stock is `return *(r0 + idx * 8)`, the descriptor {W, H, 0, 0, W, H,
 *         x, fmt, cap, 1, v} every LV channel is built from (FUN_c0436d98).
 *         A rule {idx, addr, W, H} matching the firmware's descriptor answers a
 *         private copy instead: filled once from it (ogc_out's way: the stock
 *         descriptor is a shared live buffer and is never written), its W/H
 *         (+0x00/+0x04/+0x10/+0x14) replaced by the record's aspect.
 *
 * Why REC needs its own rule (notes in isp_custom.py LVOUT_*): the configurator
 * XC_LiveViewConfiguratorW71c1::v5 (C043C090) gives a route-table entry
 * (C0BE5810/59B0/5B50) the movie disp param, config+0x460, whose idx 0 is the
 * static 1920x1080 at 0xC2F21494.  res-custom's picker answers entries from
 * its own table, so the range checks miss and it falls (log 0x511) to
 * config+0x268 -- the still param, 1620x1080 + 320x213: that is its 3:2 REC.
 * isp_custom keeps the stock entry, so the descriptor is replaced here.
 *
 * Rules: NRULE x RULE bytes, idx 0xFFFFFFFF = unused; addr 0 = any address.
 * The site is the 8-byte `ldr pc, [pc, #-4]` + address (ix_card.S form); the
 * two words overwritten are replayed here, neither is pc-relative.
 * ========================================================================== */
.equ NRULE, 3
.equ R_IDX, 0
.equ R_ADDR, 4
.equ R_W, 8
.equ R_H, 12
.equ R_NW, 16
.equ R_NH, 20
.equ R_FILLED, 24
.equ R_TPL, 28                          @ 11 words
.equ R_HITS, 72
.equ RULE, 80

.global out
out:
    push    {r4, r5, r6, lr}            @ even: the caller's 8-alignment holds
    cmp     r1, #0
    cmpne   r1, #2
    bne     8f
    ldr     r2, [r0, r1, lsl #3]        @ d: what the stock function would answer
    sub     ip, r2, #0xC0000000
    cmp     ip, #0x04000000             @ ogc_out's guard: d in 0xC0000000..0xC3FFFFFF
    bhs     8f
    adr     r3, rules_at
    mov     r4, #NRULE
1:  ldr     ip, [r3, #R_IDX]
    cmp     ip, r1
    bne     2f
    ldr     ip, [r3, #R_ADDR]
    cmp     ip, #0
    beq     3f
    cmp     ip, r2
    bne     2f
3:  ldr     ip, [r3, #R_W]
    ldr     r5, [r2]
    cmp     ip, r5
    bne     2f
    ldr     ip, [r3, #R_H]
    ldr     r5, [r2, #4]
    cmp     ip, r5
    beq     4f
2:  add     r3, r3, #RULE
    subs    r4, r4, #1
    bne     1b
8:  pop     {r4, r5, r6, lr}
    push    {r4, r5, lr}                @ stock 0xC0437E98
    mov     r5, r0                      @ stock 0xC0437E9C
    ldr     pc, resume

4:  ldr     ip, [r3, #R_FILLED]
    cmp     ip, #0
    bne     6f
    add     r5, r3, #R_TPL
    mov     r4, #11
5:  ldr     ip, [r2], #4
    str     ip, [r5], #4
    subs    r4, r4, #1
    bne     5b
    ldr     ip, [r3, #R_NW]
    str     ip, [r3, #(R_TPL + 0x00)]
    str     ip, [r3, #(R_TPL + 0x10)]
    ldr     ip, [r3, #R_NH]
    str     ip, [r3, #(R_TPL + 0x04)]
    str     ip, [r3, #(R_TPL + 0x14)]
    dmb                                 @ the copy is whole before it is published
    mov     ip, #1
    str     ip, [r3, #R_FILLED]
6:  ldr     ip, [r3, #R_HITS]
    add     ip, ip, #1
    str     ip, [r3, #R_HITS]
    add     r0, r3, #R_TPL
    pop     {r4, r5, r6, pc}

.align 2
resume:     .word 0xC0437EA0
.global rules
rules:
rules_at:                               @ local: adr takes no global symbol
    .rept NRULE
    .word   0xFFFFFFFF, 0, 0, 0, 0, 0, 0
    .space  44
    .word   0, 0
    .endr
