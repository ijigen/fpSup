/* lens_read.S — call CmdRead(lens_mgr=0xC347CB14, addr, len, dest, 0) to read lens memory.
 * Injected in cave, invoked via `call`. addr/len from scratch; data -> dest_buf; ret -> scratch+8. */
.syntax unified
.arm
.text
.global _start
_start:
    push  {r4-r11, lr}
    ldr   r0, .Lscr
    ldr   r1, [r0, #0]        @ addr
    ldr   r2, [r0, #4]        @ len
    ldr   r3, .Ldest         @ dest_buf
    mov   r4, #0
    push  {r4}               @ param_5 (flag=0) on stack
    movw  r0, #0xCB14
    movt  r0, #0xC347        @ lens_mgr = 0xC347CB14
    ldr   ip, .Lcmdread
    blx   ip                 @ CmdRead(mgr, addr, len, dest, 0)
    add   sp, sp, #4         @ pop param_5
    ldr   r1, .Lscr
    str   r0, [r1, #8]       @ ret code
    pop   {r4-r11, lr}
    bx    lr
.align 2
.Lscr:     .word 0xC072FF00
.Ldest:    .word 0xC072FA00
.Lcmdread: .word 0xC0355BE0
