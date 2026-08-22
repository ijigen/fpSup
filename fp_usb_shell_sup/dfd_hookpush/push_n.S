.syntax unified
.arm
.global _start
/* push_N: r0=STATE. args STATE+0x70=N, +0x74=buffer, +0x78=framesize.
 * 迴圈 N 次:arm ctx4 TRB(bufptr/size/ctrl=0x813)→ StartTransfer(9) → wait(4).
 * FN_WAIT 每幀擋到 host bulk-IN 收完才 re-arm → 同步、無 stall、無 usleep。*/
_start:
    push {r4-r8, lr}
    mov  r4, r0
    ldr  r7, [r4, #0x70]      @ N
    ldr  r8, [r4, #0x74]      @ buffer
    ldr  r6, [r4, #0x78]      @ framesize
.ploop:
    movw r0, #0x3274
    movt r0, #0xC31E          @ CTX4_TBL 0xC31E3274
    ldr  r5, [r0]            @ bus-alias TRB
    str  r8, [r5]            @ bufptr
    mov  r0, #0
    str  r0, [r5, #4]       @ BPTRH
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
    pop  {r4-r8, pc}
