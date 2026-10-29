.syntax unified
.arm
.text
/* ============================================================================
 * binfilt — res-custom's CRCT bin recipe (ogc_binfilt.c, SEC_BINFILT) for the
 * isp_custom test install.  Position independent: data is pc-relative.
 *
 *   path  hook 0xC0325228 (CRCT path selector, r1 = in, r2 = out): after the
 *         stock selector, when in+0x10/+0x14 are the recipe's bins:
 *           branch C (out+8 == 4) already applies Hbin2 -> a horizontal /3
 *           on the main pipe (out+0x24 == 3) would be a second one: make it 1
 *           out+0x48 = the soft/std mode bit
 *   k1/k2 hook 0xC032DDE8 / 0xC032DE68, just before the two reduction-record
 *         writers (blx 0xC0635DB0 / DC8, r1 = sp+8): their 3-tap kernels
 *           H: [s, 64-2s, s]/64      s = 21 16 11 8 4 0      (kh 0..5)
 *           V: [s, 4096-2s, s]/4096  s = 1365 1024 683 512 256 0 (kv 0..5)
 *
 * cfg (ogc's packing): 0x800 valid, 0x200 bin_h 3, 0x400 bin_v 3, 0x100 mode,
 * bits 0-2 kh, 4-6 kv.  0 = everything stock.  Sites are 8-byte
 * `ldr pc, [pc, #-4]` + address (ix_card.S form); the two words overwritten
 * at each site are replayed here, none is pc-relative.
 * ========================================================================== */
.global path
path:
    push    {r0, r1, r2, r4, r5, lr}
    bl      path_replay
    str     r0, [sp]                    @ the selector's return value
    ldr     r1, [sp, #4]                @ in
    ldr     r2, [sp, #8]                @ out
    ldr     r4, cfg
    tst     r4, #0x800
    beq     9f
    tst     r4, #0x600
    beq     9f
    tst     r4, #0x200
    movne   r5, #3
    moveq   r5, #1
    ldr     ip, [r1, #0x10]
    cmp     ip, r5
    bne     9f
    tst     r4, #0x400
    movne   r5, #3
    moveq   r5, #1
    ldr     ip, [r1, #0x14]
    cmp     ip, r5
    bne     9f
    ldr     ip, [r2, #8]
    cmp     ip, #4
    bne     1f
    ldr     ip, [r1, #0x10]
    cmp     ip, #3
    bne     1f
    ldr     ip, [r2, #0x24]
    cmp     ip, #3
    moveq   ip, #1
    streq   ip, [r2, #0x24]
1:  lsr     ip, r4, #8
    and     ip, ip, #1
    str     ip, [r2, #0x48]
    ldr     ip, hits_path
    add     ip, ip, #1
    str     ip, hits_path
9:  pop     {r0, r1, r2, r4, r5, pc}

path_replay:
    push    {r4, r5, r6, r7}            @ stock 0xC0325228
    mov     r5, r0                      @ stock 0xC032522C
    ldr     pc, resume_path

.global k1
k1:
    push    {r0, r1, r2, r3, r4, lr}
    add     r1, sp, #(24 + 8)           @ the caller's sp + 8
    bl      kernel
    pop     {r0, r1, r2, r3, r4, lr}
    ldrb    r0, [sp, #2]                @ stock 0xC032DDE8
    add     r1, sp, #8                  @ stock 0xC032DDEC
    ldr     pc, resume_k1

.global k2
k2:
    push    {r0, r1, r2, r3, r4, lr}
    add     r1, sp, #(24 + 8)
    bl      kernel
    pop     {r0, r1, r2, r3, r4, lr}
    ldrb    r0, [sp, #3]                @ stock 0xC032DE68
    add     r1, sp, #8                  @ stock 0xC032DE6C
    ldr     pc, resume_k2

/* r1 = the reduction record; uses r0, r2-r4, ip */
kernel:
    ldr     r3, cfg
    tst     r3, #0x800
    bxeq    lr
    ldr     ip, hits_k
    add     ip, ip, #1
    str     ip, hits_k
    tst     r3, #0x200
    beq     2f
    and     r0, r3, #7
    adr     ip, htab
    ldrb    r0, [ip, r0]                @ side
    rsb     r2, r0, #64
    sub     r2, r2, r0                  @ middle
    strb    r0, [r1, #0x29]
    strb    r2, [r1, #0x2a]
    strb    r0, [r1, #0x2b]
    add     ip, r1, #0x1c
    mov     r4, #4
1:  strb    r0, [ip]
    strb    r2, [ip, #1]
    strb    r0, [ip, #2]
    add     ip, ip, #3
    subs    r4, r4, #1
    bne     1b
2:  tst     r3, #0x400
    bxeq    lr
    lsr     r0, r3, #4
    and     r0, r0, #7
    lsl     r0, r0, #1
    adr     ip, vtab
    ldrh    r0, [ip, r0]
    rsb     r2, r0, #4096
    sub     r2, r2, r0
    add     ip, r1, #8
    mov     r4, #3
3:  strh    r0, [ip]
    strh    r2, [ip, #2]
    strh    r0, [ip, #4]
    add     ip, ip, #6
    subs    r4, r4, #1
    bne     3b
    bx      lr

.align 2
htab:       .byte 21, 16, 11, 8, 4, 0, 0, 0
vtab:       .short 1365, 1024, 683, 512, 256, 0, 0, 0
resume_path: .word 0xC0325230
resume_k1:  .word 0xC032DDF0
resume_k2:  .word 0xC032DE70
.global cfg
cfg:        .word 0
.global hits_path
hits_path:  .word 0
.global hits_k
hits_k:     .word 0
