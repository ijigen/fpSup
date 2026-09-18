.syntax unified
.arm
.text

/* OG4K-4000 V5.02 experimental core. No installed hooks or fixed code/state cave.
 * ABI entry points are exercised in an ARM emulator. A future firmware adapter
 * must quiesce the capture pipeline before transition and supply validated
 * request/DNG fields. IRQ masking alone does not quiesce DMA or another CPU.
 *
 * transition(r0=state[4], r1=action): 0=off, 1=on, 2=boot recovery.
 * state = {magic, enabled, error, busy}. Return 0 on success, error otherwise.
 * Preflight refusal leaves state untouched. Successful rollback restores the
 * prior selection; failed rollback invalidates magic and requires recovery.
 * Recovery accepts only stock/our known words, restores stock, clears state.
 * Runtime pointers are not retained. Code hooks are outside this module.
 *
 * record_canvas(r0=private canvas[65], r1=request[9]):
 * request={magic, selected, profile, mode, fps_num, fps_den, bits, crop, cine}.
 * playback_canvas(r0=private canvas[65], r1=frame[10]):
 * frame={magic, compression, bits, W,H, cropX,cropY, cropW,cropH, stripBytes}.
 * Canvas entries return 1 if changed, 0 for unrelated input, 2 on donor mismatch.
 * Both entries validate all predicates before their first canvas write.
 */
.equ MAGIC, 0x4B34474F
.equ TIMING, 0xC0B59D04
.equ T0, 0x047901BD
.equ T1, 0x00081A54

.macro LDA reg, value
    movw \reg, #:lower16:\value
    movt \reg, #:upper16:\value
.endm

.global transition
transition:
    push {r4-r10, lr}
    sub sp, sp, #40                  @ snapshots, one per guarded word
    mov r4, r0
    mov r5, r1
    mrs r9, cpsr
    orr r3, r9, #0xC0
    msr cpsr_c, r3
    cmp r5, #2
    bhi bad_request
    cmp r4, #0
    beq bad_pointer
    tst r4, #3
    bne bad_pointer
    cmp r5, #2
    beq timing_guard
    ldr r0, [r4]
    LDA r1, MAGIC
    cmp r0, r1
    bne bad_request
    ldr r0, [r4, #12]
    cmp r0, #0
    bne bad_request
    ldr r8, [r4, #4]
    cmp r8, #1
    bhi bad_request
timing_guard:
    /* A foreign fps patch must not be silently kept as "24p". */
    LDA r0, TIMING
    ldr r1, [r0]
    LDA r2, T0
    cmp r1, r2
    bne bad_timing
    ldr r1, [r0, #4]
    LDA r2, T1
    cmp r1, r2
    bne bad_timing
    adr r6, frontend
    mov r7, #0
preflight:
    ldm r6, {r0-r2}                  @ address, stock, full height
    ldr r3, [r0]
    str r3, [sp, r7, lsl #2]
    cmp r5, #2
    beq known_word
    cmp r8, #0
    moveq r2, r1
    cmp r3, r2
    bne bad_word
    b preflight_next
known_word:
    cmp r3, r1
    cmpne r3, r2
    bne bad_word
preflight_next:
    add r6, r6, #12
    add r7, r7, #1
    cmp r7, #10
    blo preflight

    mov r0, #0
    str r0, [r4, #4]                @ withdraw before changing shared data
    mov r0, #1
    str r0, [r4, #12]
    dmb sy
    adr r6, frontend
    mov r7, #0
apply:
    ldm r6, {r0-r2}
    cmp r5, #1
    movne r2, r1
    str r2, [r0]
    dmb sy
    ldr r3, [r0]
    cmp r3, r2
    bne rollback
    add r6, r6, #12
    add r7, r7, #1
    cmp r7, #10
    blo apply
    LDA r0, MAGIC
    str r0, [r4]
    mov r0, #0
    str r0, [r4, #8]
    str r0, [r4, #12]
    dmb sy
    cmp r5, #1
    moveq r0, #1
    str r0, [r4, #4]                @ publish only after every readback passed
    dmb sy
    mov r0, #0
    b transition_return
rollback:
    /* Restore the complete pre-transaction snapshot, with readback. */
    adr r6, frontend
    add r6, r6, #108
    mov r7, #9
    mov r10, #4                     @ failed write, rollback succeeded
rollback_loop:
    ldr r0, [r6]
    ldr r1, [sp, r7, lsl #2]
    str r1, [r0]
    dmb sy
    ldr r2, [r0]
    cmp r1, r2
    movne r10, #5                   @ rollback itself failed
    sub r6, r6, #12
    subs r7, r7, #1
    bpl rollback_loop
    mov r0, #0
    str r0, [r4, #12]
    str r10, [r4, #8]
    cmp r10, #5
    beq recovery_required
    cmp r5, #2
    beq recovery_required            @ old boot state may have been a mixture
    dmb sy
    str r8, [r4, #4]                @ successful rollback restores prior state
    dmb sy
    mov r0, r10
    b transition_return
recovery_required:
    str r0, [r4]                    @ invalidate magic; normal requests refuse
    str r0, [r4, #4]
    dmb sy
    mov r0, r10
    b transition_return
bad_word:
    mov r0, #2
    b transition_return
bad_timing:
    mov r0, #3
    b transition_return
bad_request:
    mov r0, #1
    b transition_return
bad_pointer:
    mov r0, #1
transition_return:
    /* Restore original IRQ/FIQ masks without changing the return flags. */
    mrs r1, cpsr
    bic r1, r1, #0xC0
    and r9, r9, #0xC0
    orr r1, r1, r9
    msr cpsr_c, r1
    add sp, sp, #40
    pop {r4-r10, pc}

.align 2
frontend:
    .word 0xC0B5B6C8,3412,4042
    .word 0xC0B5B6D8,3412,4042
    .word 0xC0B5B6E8,3412,4042
    .word 0xC0B5B714,1,2
    .word 0xC0B5D43C,8,0
    .word 0xC0B5D440,0x016001FB,0x002601FB
    .word 0xC0B5D444,3768,4084
    .word 0xC0B5D450,0x0004C003,0x00040003
    .word 0xC0B59D0C,0x016217B8,0x002817B8
    .word 0xC0B59D10,3766,4082

.global record_canvas
record_canvas:
    push {r4-r8, lr}
    mov r4, r0
    orr r2, r0, r1
    tst r2, #3
    bne unrelated
    cmp r0, #0
    cmpne r1, #0
    beq unrelated
    adr r5, record_request
    mov r6, #9
record_request_loop:
    ldr r2, [r1], #4
    ldr r3, [r5], #4
    cmp r2, r3
    bne unrelated
    subs r6, r6, #1
    bne record_request_loop
    /* This is the RAW12 p429 donor, including its separate preview fields. */
    ldr r2, [r4, #0x80]
    cmp r2, #7
    bne donor_error
    ldr r2, [r4, #0x84]
    cmp r2, #7
    bne donor_error
    ldr r2, [r4, #0x3C]
    cmp r2, #0
    bne donor_error
    adr r5, record_pairs
    mov r6, #8
record_guard:
    ldm r5, {r0-r2}
    ldr r3, [r4, r0]
    cmp r3, r1
    bne donor_error
    add r5, r5, #12
    subs r6, r6, #1
    bne record_guard
    adr r5, record_pairs
    mov r6, #8
record_apply:
    ldm r5, {r0-r2}
    str r2, [r4, r0]
    add r5, r5, #12
    subs r6, r6, #1
    bne record_apply
    dmb sy
    mov r0, #1
    pop {r4-r8, pc}
unrelated:
    mov r0, #0
    pop {r4-r8, pc}
donor_error:
    mov r0, #2
    pop {r4-r8, pc}

.align 2
record_request:
    .word MAGIC,1,429,151,24,1,12,0,1
record_pairs:
    .word 0x00,3856,4016
    .word 0x04,2170,2676
    .word 0x24,3840,4000
    .word 0x2C,2160,2666
    .word 0xDC,3856,4016
    .word 0xE4,2170,2676
    .word 0x64,1600,1536
    .word 0xD4,1600,1536

.global playback_canvas
playback_canvas:
    push {r4-r8, lr}
    mov r4, r0
    orr r2, r0, r1
    tst r2, #3
    bne unrelated
    cmp r0, #0
    cmpne r1, #0
    beq unrelated
    adr r5, playback_frame
    mov r6, #10
playback_frame_loop:
    ldr r2, [r1], #4
    ldr r3, [r5], #4
    cmp r2, r3
    bne unrelated
    subs r6, r6, #1
    bne playback_frame_loop
    /* Recognize a native RAW12 movie playback canvas; never a still or codec. */
    ldr r2, [r4, #0x80]
    LDA r3, 0x10007
    cmp r2, r3
    bne donor_error
    ldr r2, [r4, #0x44]
    cmp r2, #1
    bne donor_error
    ldr r2, [r4, #0x3C]
    cmp r2, #0
    bne donor_error
    /* p71 UHD12 playback donor only. FHD p73 retains 2x reduction factors;
     * sharing its geometry is not enough to prove the same display behavior. */
    ldr r2, [r4, #0x0C]
    movw r3, #3856
    cmp r2, r3
    bne donor_error
    ldr r2, [r4, #0x10]
    movw r3, #2170
    cmp r2, r3
    bne donor_error
    LDA r3, 0x3F800000
    ldr r2, [r4, #0xFC]
    cmp r2, r3
    bne donor_error
    ldr r2, [r4, #0x100]
    cmp r2, r3
    bne donor_error
    adr r5, playback_pairs
    mov r6, #13
playback_apply:
    ldm r5!, {r0,r2}
    str r2, [r4, r0]
    subs r6, r6, #1
    bne playback_apply
    dmb sy
    mov r0, #1
    pop {r4-r8, pc}
.align 2
playback_frame:
    /* C0135D40/DB8 last-row packing adds 8 bytes for this exact raster. */
    .word MAGIC,1,12,4016,2676,8,5,4000,2666,16120232
playback_pairs:
    .word 0x1C,2
    .word 0x0C,4016
    .word 0x10,2676
    .word 0xD8,4016
    .word 0xE0,2676
    .word 0x20,4000
    .word 0x28,2666
    .word 0xF4,4016
    .word 0xF8,2676
    .word 0x60,1024
    .word 0xD0,1024
    .word 0x64,1024
    .word 0xD4,1024
