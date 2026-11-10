@ SIGMA fp 5.02 -- rear wheel (CMDDIAL2) decoder v6, Thumb-2.
@ NOTES.md sections 21-22.  Reference model: wheel_model.V6 (exactly this).
@ (v3.1, the previous card: dial2_fast_v31.S; v3: dial2_fast_v3.S)
@
@ Wheel: Shinmei TSW-26 (encoder + 5-way push).  12 detents = one full A/B
@ cycle each; rest = both open.  A = pins 10-7, B = pins 10-4: a shared
@ common terminal, whose bounce opens both contacts at once.
@ ADC ch 0 (A) / ch 1 (B), pull-ups: open = 4095, closed ~0.
@     clockwise:      B closes first ... A opens last      = +1
@     anticlockwise:  A closes first ... B opens last      = -1
@
@ v6 = v1 optimized.  The 12.5-14 ms poll almost never lands inside a bounce,
@ so the POLL decides when a click starts and ends; the INTERRUPTS decide its
@ direction (which contact closed first, which opened last) and count fast
@ spins (v3.1's rule, unchanged):
@   poll sees the wheel away   -> gate on; clicks are held
@   poll sees rest, gate on    -> one click in the direction of (first to
@                                 close since the last polled rest, last
@                                 single contact to open); if the irqs counted
@                                 >= 2 clicks that way, all of them (fast)
@   poll sees rest, gate off   -> the irqs' clicks: they happened entirely
@                                 between two polls (fast spin)
@
@ Region 0xC02E1CE8..0xC02E1EC8 (120 words), only dial 2's vtable reaches it.
@   +0x00 dial2_poll (Thumb; vtable +0x10 = 0xC02E1CE9, called by blx)
@   +0x90 dial2_irq  (ARM stub at 0xC02E1D78, where the stock irq chain's
@         ARM `bl` lands; it jumps to the Thumb irq code)
@ Object fields:
@   +0x08 s      state, A bit 0, B bit 1 (1 = open)
@   +0x0c ff     contact that closed first in this excursion (1 A, 2 B, 0 ?)
@   +0x10 lr     contact that opened last (1 A, 2 B, 0 both at once)
@   +0x14 flags  bit 0 away, bit 1 both-closed passed, bit 2 a poll saw the
@                current rest, bit 3 a poll saw the rest this excursion left
@                from (v3); bit 4 gate (a poll saw the wheel away); bits 5-6
@                first to close since the last polled rest; bits 7-8 last
@                single contact to open into rest
@   +0x18 count  clicks counted by the irq rule, not yet handed out

        .syntax unified
        .text
        .equ    ADC0,   0x301502c0          @ ch0 bits 0-15, ch1 bits 16-31; +0x30 cmp out
        .equ    LO,     1200                @ below: closed
        .equ    HI,     2896                @ above: open (0xB50: a Thumb-2 immediate)
        .equ    S,  0x08
        .equ    FF, 0x0c
        .equ    LR, 0x10
        .equ    FL, 0x14
        .equ    CNT, 0x18

        .thumb
@ ---------------------------------------------------------------------
@ dial2_poll(r0 = obj, r1 = int *out) -> 1            DialDet poll
@ ---------------------------------------------------------------------
        .global dial2_poll
        .type   dial2_poll, %function
        .thumb_func
dial2_poll:
        push    {r4-r7, lr}
        mrs     r6, cpsr
        cpsid   i
        ldr     r2, [r0, #S]
        movw    r3, #:lower16:ADC0
        movt    r3, #:upper16:ADC0
        ldr     r3, [r3]                    @ ADC ch0 | ch1 << 16
        uxth    r4, r3
        movs    r5, #1
        bl      .Lband                      @ A
        lsrs    r4, r3, #16
        movs    r5, #2
        bl      .Lband                      @ B
        bl      .Lstep
        ldr     r2, [r0, #FL]
        ldr     r3, [r0, #S]
        cmp     r3, #3
        beq     1f
        orr     r2, r2, #0x10               @ away: gate on, hold the clicks
        str     r2, [r0, #FL]
        movs    r3, #0
        b       9f
1:      ldr     r3, [r0, #CNT]              @ out = irq clicks
        tst     r2, #0x10
        beq     8f                          @ gate off: clicks between two polls
        ubfx    r4, r2, #5, #2              @ f = first to close
        ubfx    r5, r2, #7, #2              @ l = last single contact to open
        movs    r7, #0                      @ d
        cbz     r4, 3f
        cmp     r4, r5
        beq     6f                          @ came back the way it left
        cmp     r4, #2
        b       5f
3:      cbz     r5, 6f
        cmp     r5, #1                      @ only l: A last = clockwise
5:      ite     eq
        moveq   r7, #1
        movne   r7, #-1
6:      mul     r4, r3, r7                  @ irqs counted >= 2 the same way: keep
        cmp     r4, #2
        it      lt
        movlt   r3, r7
8:      movs    r4, #0
        str     r4, [r0, #CNT]
        and     r2, r2, #0xF
        orr     r2, r2, #4                  @ a poll saw this rest; gate off
        str     r2, [r0, #FL]
9:      msr     cpsr_c, r6
        str     r3, [r1]
        movs    r0, #1
        pop     {r4-r7, pc}

        .balign 4
        .arm
        .org    0x90                        @ = 0xC02E1D78 (dial2_edge)
@ ---------------------------------------------------------------------
@ dial2_irq(r0 = obj, r1 = ch)    ARM, reached by the stock chain's `bl`
@ ---------------------------------------------------------------------
        .global dial2_irq
dial2_irq:
        add     r12, pc, #(.Lirq - . - 8 + 1)   @ Thumb code right after; lr untouched
        bx      r12

        .thumb
.Lirq:  push    {r4-r7, lr}
        mrs     r6, cpsr
        cpsid   i
        ldr     r2, [r0, #S]
        movw    r3, #:lower16:ADC0
        movt    r3, #:upper16:ADC0
        ldr     r7, [r3, #0x30]             @ comparator out: A bit 0, B bit 16
        ldr     r3, [r3]                    @ ADC ch0 | ch1 << 16
        cbnz    r1, 1f
        lsrs    r4, r3, #16                 @ irq on A: B from the ADC band
        movs    r5, #2
        bl      .Lband
        bic     r2, r2, #1
        and     r7, r7, #1
        orr     r2, r2, r7                  @ A from the comparator
        b       2f
1:      uxth    r4, r3                      @ irq on B: A from the ADC band
        movs    r5, #1
        bl      .Lband
        bic     r2, r2, #2
        ubfx    r7, r7, #16, #1
        orr     r2, r2, r7, lsl #1          @ B from the comparator
2:      bl      .Lstep
        msr     cpsr_c, r6
        pop     {r4-r7, pc}                 @ interworking return to the ARM chain

@ step: r0 = obj, r2 = new state.  Uses r3, r4, r5, r7, r12.  (r0, r1, r6 kept)
.Lstep: ldr     r3, [r0, #S]                @ prev
        cmp     r2, r3
        it      eq
        bxeq    lr
        str     r2, [r0, #S]
        ldr     r7, [r0, #FL]
        bics    r4, r2, r3                  @ rose
        beq     1f
        cmp     r4, #3
        it      eq
        moveq   r4, #0
        str     r4, [r0, #LR]               @ lr (both at once: unknown)
        cmp     r2, #3
        bne     1f
        cbz     r4, 1f
        bic     r7, r7, #0x180
        orr     r7, r7, r4, lsl #7          @ last single contact to open
1:      cmp     r3, #3
        bne     2f
        bic     r4, r3, r2                  @ leaving rest: fell
        cmp     r4, #3
        it      eq
        moveq   r4, #0
        str     r4, [r0, #FF]               @ ff (both at once: unknown)
        tst     r7, #0x60
        it      eq
        orreq   r7, r7, r4, lsl #5          @ sticky first to close
        and     r4, r7, #4
        bic     r7, r7, #0xF
        orr     r7, r7, r4, lsl #1          @ start polled := rest polled
        orr     r7, r7, #1                  @ away
        cmp     r2, #0
        it      eq
        orreq   r7, r7, #2                  @ both closed at once
        b       7f
2:      tst     r7, #1
        beq     7f                          @ not tracking a click
        eor     r4, r3, r2
        cmp     r2, #0
        it      ne
        cmpne   r4, #3
        it      eq
        orreq   r7, r7, #2                  @ state 0, or 1 <-> 2 directly
        cmp     r2, #3
        bne     7f
        mov     r12, r7                     @ back at rest: flags of this excursion
        bic     r7, r7, #0xF
        str     r7, [r0, #FL]
        tst     r12, #2
        it      eq
        bxeq    lr                          @ never both closed: spring-back
        ldr     r4, [r0, #FF]
        ldr     r3, [r0, #LR]
        cbnz    r4, 4f
        cbz     r3, 9f                      @ neither known
        tst     r12, #8
        beq     9f                          @ only lr, after an unpolled rest: no
        rsb     r4, r3, #3                  @ only lr: A opened last = B closed first
        b       5f
4:      cmp     r4, r3
        beq     9f                          @ came back the way it left
5:      cmp     r4, #2
        ite     eq
        moveq   r5, #1                      @ B closed first: clockwise, +1
        movne   r5, #-1                     @ A closed first: anticlockwise, -1
        ldr     r4, [r0, #CNT]
        add     r4, r4, r5
        str     r4, [r0, #CNT]
9:      bx      lr
7:      str     r7, [r0, #FL]
        bx      lr

@ band: r2 = state, r4 = ADC value, r5 = bit.  Uses nothing else.
.Lband: cmp     r4, #LO
        it      lo
        biclo   r2, r2, r5
        cmp     r4, #HI
        it      hi
        orrhi   r2, r2, r5
        bx      lr

        .balign 4                           @ the card writes whole words
