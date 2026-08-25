/* imu_snapshot.S — one-call IMU gather, injected into the worker cave via `mem set`.
 * Entry via worker `call <addr>` (blx, r0=STATE). No absolute code refs -> position
 * independent (PC-relative literal loads + movw only). Writes a fixed result block that
 * the host drains in ONE `mem read`. No firmware hook, no autorun change.
 *
 * Result @0xC072F240 (in cave, mem-readable):
 *   +0x00 i16 accel X   (0xC377790C)     +0x0C i16 gyro X (latest ring sample)
 *   +0x02 i16 accel Y   (0xC377790E)     +0x0E i16 gyro Y
 *   +0x04 i16 accel Z   (0xC3777910)     +0x10 i16 gyro Z
 *   +0x06 i16 pad                        +0x12 i16 pad
 *   +0x08 u32 gyro head                  +0x14 u32 magic 'IMU0'=0x494D5530
 * Code blob @0xC072F200 (~120B); result @0xC072F300 (clear of code).
 */
.syntax unified
.arm
.text
.global _start
_start:
    push  {r4-r7}               @ AAPCS: worker calls via blx, r4-r11 MUST be preserved
    ldr   r2, .Lresult          @ result base
    ldr   r1, .Laccel           @ MMA8452Q cache
    ldrsh r3, [r1]              @ accel X
    ldrsh r4, [r1, #2]          @ accel Y
    ldrsh r5, [r1, #4]          @ accel Z
    strh  r3, [r2]
    strh  r4, [r2, #2]
    strh  r5, [r2, #4]
    ldr   r1, .Lgmbox           @ 0xC31E3FCC
    ldr   r1, [r1]              @ P = 0x2E006004
    ldr   r6, [r1, #0x60]       @ rb = ring_base
    ldr   r7, [r6]             @ cursor = *(rb): ABSOLUTE ptr = latest_sample_start + 4
    str   r7, [r2, #8]         @ store cursor (debug/host cross-check)
    sub   r3, r7, #4           @ latest_sample_start (lands on rb+4+n*8)
    ldrsh r4, [r3]             @ gyro X
    ldrsh r5, [r3, #2]         @ gyro Y
    ldrsh r0, [r3, #6]         @ gyro Z (X,Y,pad,Z @ 0,2,4,6)
    strh  r4, [r2, #0x0C]
    strh  r5, [r2, #0x0E]
    strh  r0, [r2, #0x10]
    ldr   r3, .Lmagic
    str   r3, [r2, #0x14]
    pop   {r4-r7}               @ restore callee-saved before return
    bx    lr
.align 2
.Lresult: .word 0xC072F300
.Laccel:  .word 0xC377790C
.Lgmbox:  .word 0xC31E3FCC
.Lmagic:  .word 0x494D5530
