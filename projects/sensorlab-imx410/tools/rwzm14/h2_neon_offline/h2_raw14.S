/* Offline proof only. No camera calls, loader, hook, or DMA integration.
 * int h2_raw14_u16_row(uint16_t *dst, const uint16_t *src, uint32_t width)
 * AAPCS ARM state. Little-endian, right-justified RAW14 in u16 containers.
 * width must be a multiple of 16 input samples, or this returns -1 unchanged.
 * width == 0 succeeds without touching either buffer. No packed RAW14 support.
 * Source and destination must be disjoint and >= 2-byte aligned.
 * Per Bayer group [x0,x1,x2,x3] => [(x0+x2+1)/2,(x1+x3+1)/2].
 * Row phase is preserved; no combination between rows. Only d0-d3 clobbered.
 * Caches, ownership, actual scheduling and input format are caller concerns.
 */
.syntax unified
.arch armv7-a
.fpu neon
.arm
.text
.align 2
.global h2_raw14_u16_row
.type h2_raw14_u16_row, %function
h2_raw14_u16_row:
    tst r2, #15
    bne .Linvalid
    cmp r2, #0
    beq .Ldone
.Lloop:
    vld2.32 {d0-d3}, [r1]!
    vrhadd.u16 q0, q0, q1
    vst1.16 {d0-d1}, [r0]!
    subs r2, r2, #16
    bne .Lloop
.Ldone:
    mov r0, #0
    bx lr
.Linvalid:
    mvn r0, #0
    bx lr
.size h2_raw14_u16_row, .-h2_raw14_u16_row
