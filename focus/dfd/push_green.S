.syntax unified
.arm
.global _start
/* push_N_green: r0=STATE. STATE+0x70=N, +0x78=framesize.
 * 每幀:讀 green ptr(0xC3404768)→ 驗證 0x40000000..0x60000000 → 有效直接 arm ctx4 指向它
 * (零拷貝 DMA);無效推 fallback 0x50000000。StartTransfer(9)+wait(4) 同步 host。*/
_start:
    push {r4-r9, lr}
    mov  r4, r0
    ldr  r7, [r4, #0x70]      @ N
    ldr  r6, [r4, #0x78]      @ framesize
.ploop:
    movw r0, #0x4768
    movt r0, #0xC340          @ green slot1 bufptr addr
    ldr  r8, [r0]            @ green ptr
    movw r0, #0x0000
    movt r0, #0x4000          @ 0x40000000
    cmp  r8, r0
    blo  .Lfb
    movw r0, #0x0000
    movt r0, #0x6000          @ 0x60000000
    cmp  r8, r0
    blo  .Lgood
.Lfb:
    movw r8, #0x0000
    movt r8, #0x5000          @ fallback 0x50000000
.Lgood:
    movw r0, #0x3274
    movt r0, #0xC31E          @ CTX4_TBL
    ldr  r5, [r0]
    str  r8, [r5]            @ bufptr = green (zero-copy)
    mov  r0, #0
    str  r0, [r5, #4]
    str  r6, [r5, #8]       @ size
    movw r0, #0x0813
    str  r0, [r5, #0xc]     @ ctrl
    dsb
    mov  r0, #9
    movw r12, #0x6B81
    movt r12, #0xC01E        @ FN_STARTX
    blx  r12
    mov  r0, #4
    movw r1, #50000
    movw r12, #0x4E81
    movt r12, #0xC01E        @ FN_WAIT
    blx  r12
    subs r7, r7, #1
    bne  .ploop
    mov  r0, #0
    pop  {r4-r9, pc}
