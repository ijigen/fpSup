.syntax unified
.arm
.text

/* Recording-time media phase probe.
 *
 * C03660E8 is the shared MediaFile write entry.  Its first instruction is
 * replaced by a branch here.  The trampoline recreates that displaced push,
 * runs the untouched body at C03660EC, and regains control only after the body
 * has released its media lock.  The original result and callee-saved registers
 * are returned unchanged.
 *
 * Nothing here performs media I/O.  While S_ACTIVE == 1 it records, in RAM:
 *
 *   - writes >= 1 MiB as the CinemaDNG hold interval;
 *   - full GYR block writes through pool+0x6400 as the contender;
 *   - the first four and rolling last four GYR calls as
 *       { bit31=DNG busy, low31=phase us, total F_WRITE duration us }.
 *
 * logger_phase.S appends those existing 64 state bytes as a GFT6 record only
 * after recording has ended.  The probe therefore adds no diagnostic write
 * during the take and does not change the 16 KiB GYR block size.
 */

.equ POOL_PTR,       0xC3757A7C
.equ O_STATE,        0x6000
.equ O_FOBJ,         0x0400
.equ S_ACTIVE,       0x04
.equ S_MAGIC,        0x64
.equ S_DNG_START,    0x70       /* diagnostic alias of S_STOP_T0 */
.equ S_DNG_END,      0x74       /* diagnostic alias of S_STOP_T1 */
.equ S_DNG_BUSY,     0x78       /* diagnostic alias of S_STOP_BLOCKS */
.equ S_TRACE_N,      0xA4       /* diagnostic alias of S_MODE_N */
.equ S_TRACE,        0xB0       /* diagnostic alias of S_MODE_HIST */
.equ O_LC_KIND,      0x15C
.equ STATE_MAGIC,    0x41534736 /* "6GSA" word: logger's 'SAG6' bytes */

.equ F_WRITE_BODY,   0xC03660EC
.equ TICK_US,        0xC002B6E0
.equ DNG_MIN,        0x00100000
.equ GYR_MIN,        0x00003000
.equ GYR_MAX,        0x00004100

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

.macro STATE reg
    LDA     \reg, POOL_PTR
    ldr     \reg, [\reg]
    add     \reg, \reg, #O_STATE
.endm

.global phase_write_entry
phase_write_entry:
    /* Private frame: original r0-r3, scratch/marker, and the real return LR.
     * Twenty-four bytes preserve the stack alignment seen by F_WRITE_BODY. */
    push    {r0, r1, r2, r3, r12, lr}
    mov     r0, #0
    str     r0, [sp, #16]              @ marker: 0 other, 1 DNG, or trace ptr

    LDA     r3, POOL_PTR
    ldr     r3, [r3]
    cmp     r3, #0
    beq     phase_call_real
    add     r3, r3, #O_STATE
    ldr     r0, [r3, #S_MAGIC]
    LDA     r1, STATE_MAGIC
    cmp     r0, r1
    bne     phase_call_real
    ldr     r0, [r3, #S_ACTIVE]
    cmp     r0, #1
    bne     phase_call_real
    ldr     r0, [r3, #O_LC_KIND]
    cmp     r0, #1                     @ this diagnostic is CDNG-only
    bne     phase_call_real

    ldr     r2, [sp, #8]               @ original len
    cmp     r2, #DNG_MIN
    bhs     phase_dng_enter

    /* Only full streamed GYR blocks.  The 8/64/32-byte close records use the
     * same object but must not displace the rolling tail of the trace. */
    ldr     r0, [sp]                    @ original file object
    add     r1, r3, #O_FOBJ
    cmp     r0, r1
    bne     phase_call_real
    movw    r0, #:lower16:GYR_MIN
    cmp     r2, r0
    blo     phase_call_real
    movw    r0, #:lower16:GYR_MAX
    cmp     r2, r0
    bhi     phase_call_real

    LDA     ip, TICK_US
    blx     ip
    str     r0, [sp, #12]              @ this GYR call's entry tick
    STATE   r3
    ldr     r1, [r3, #S_DNG_BUSY]
    dmb     ish                         @ pair the flag with its edge timestamp
    ldr     r2, [r3, #S_DNG_END]
    sub     r2, r0, r2                 @ one origin: previous DNG return edge
    cmp     r1, #0
    orrne   r2, r2, #0x80000000

    ldr     r1, [r3, #S_TRACE_N]       @ zero-based write number
    add     ip, r1, #1
    str     ip, [r3, #S_TRACE_N]
    cmp     r1, #4
    subhs   r1, r1, #4
    andhs   r1, r1, #3
    addhs   r1, r1, #4                 @ slots 4..7 are the rolling tail
    add     r3, r3, #S_TRACE
    add     r3, r3, r1, lsl #3
    str     r2, [r3]
    mov     r2, #0
    str     r2, [r3, #4]
    str     r3, [sp, #16]              @ duration destination after F_WRITE
    b       phase_call_real

phase_dng_enter:
    mov     r0, #1
    str     r0, [sp, #16]
    LDA     ip, TICK_US
    blx     ip
    STATE   r3
    str     r0, [r3, #S_DNG_START]
    dmb     ish
    mov     r0, #1
    str     r0, [r3, #S_DNG_BUSY]

phase_call_real:
    /* Restore the three real arguments. F_WRITE overwrites r3 before reading
     * it, but restore it too so the trampoline is exact at the boundary. */
    ldmia   sp, {r0, r1, r2, r3}
    adr     ip, phase_after_real
    push    {r4, r5, r6, r7, ip}       @ displaced: push {r4-r7, lr}
    LDA     ip, F_WRITE_BODY
    bx      ip

phase_after_real:
    /* F_WRITE_BODY popped back here; our private frame is again at SP. */
    str     r0, [sp]                    @ preserve the real return value
    ldr     r3, [sp, #16]
    cmp     r3, #0
    beq     phase_return
    cmp     r3, #1
    beq     phase_dng_leave

    LDA     ip, TICK_US
    blx     ip
    ldr     r1, [sp, #12]
    sub     r0, r0, r1
    ldr     r3, [sp, #16]
    str     r0, [r3, #4]
    b       phase_return

phase_dng_leave:
    LDA     ip, TICK_US
    blx     ip
    STATE   r3
    str     r0, [r3, #S_DNG_END]
    dmb     ish
    mov     r0, #0
    str     r0, [r3, #S_DNG_BUSY]

phase_return:
    ldr     r0, [sp]
    ldr     lr, [sp, #20]
    add     sp, sp, #24
    bx      lr
