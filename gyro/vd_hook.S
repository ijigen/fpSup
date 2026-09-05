.syntax unified
.arm

#include "imu_stream.inc.S"

/* The exposure side: one record per sensor Vd.
 *
 * Gyro data has to line up with when light hit the sensor, not with when a
 * frame reached the card.  CinemaDNG is a 96 MB/s buffered write, so the file
 * lands hundreds of milliseconds after the exposure and by a margin that is not
 * fixed -- anchoring on the file write would fold the whole write pipeline into
 * the gyro timeline, which is the error we are trying to remove, not measure.
 *
 * So: the sensor's own vertical-drive frame interrupt, IRQ 0x79, handler
 * FUN_c0125478.  notes/TELEMETRY_HOOK.md 1B has it as "exactly per-Vd,
 * phase-locked to the frame", found through the AF thread's per-frame wake.
 *
 *     c0125478  E92D 4130   push.w {r4, r5, r8, lr}   Thumb
 *     c012547c  F648 14C0   movw   r4, #0x89C0
 *     c0125480  F2CC 341D   movt   r4, #0xC31D        <- displaced
 *     c0125484  6860        ldr    r0, [r4, #4]
 *
 * The handler is Thumb, so the branch is a Thumb BLX -- encoded by hand and
 * checked by decoding the firmware's own bl at c0125494, which resolves to
 * FUN_c0128e50 exactly as the decompilation says.  BLX needs a 4-byte aligned
 * target, which is why this sits where it does.
 *
 * IRQ context.  No syscalls, no blocking, no clock read: LDREX/STREX and stores
 * only.  A task caught mid-sequence just retries its STREX, which is what the
 * instruction pair is for.
 *
 * Vd free-runs in liveview, so a bare "first Vd" latch would capture whatever
 * frame happened to follow the injection.  The record-start hook zeroes the
 * count, so the first Vd after that is the take's first frame -- and that gyro
 * sample is the anchor everything else has been inferred from.
 */

.equ VD_SITE,      0xC0125480
.equ VD_SITE_ORIG, 0x341DF2CC       /* movt r4, #0xC31D -- as a little-endian
                                     * WORD, which is the two Thumb halfwords
                                     * the other way round from how they are
                                     * written.  `mem get` sees this; the
                                     * disassembly shows F2CC 341D.          */

    .global vd_hook
vd_hook:
    push    {r0, r1, r2, r3, ip, lr}

    movw    ip, #:lower16:STREAM_STATE
    movt    ip, #:upper16:STREAM_STATE

    ldr     r2, [ip, #O_VCOUNT]
    add     r0, r2, #1
    str     r0, [ip, #O_VCOUNT]
    ldr     r3, [ip, #O_GCOUNT]         @ the take's length still comes from here

    cmp     r2, #0
    bne     3f
    /* The take's first exposure.  Both rulers: the batch counter for the
     * take's length, the ring head for the anchor and the frame period. */
    str     r3, [ip, #O_V0_GC]
    gyro_head r3, r0
    str     r3, [ip, #O_V0_HEAD]
    str     r3, [ip, #O_VPREV]
    mvn     r0, #0x80000000             @ 0x7FFFFFFF, so the first gap wins
    str     r0, [ip, #O_VMIN]
    mov     r0, #0
    str     r0, [ip, #O_VMAX]
    str     r0, [ip, #O_VSUM]
    str     r0, [ip, #O_VNF]
    str     r0, [ip, #O_VSHORT]
    str     r0, [ip, #O_VOMAX]
    b       4f

3:  /* Gyro samples since the previous exposure -- the frame period, measured
     * in the sensor's own cadence with no clock of any kind in it. */
    ldr     r0, [ip, #O_VPREV]
    cmn     r0, #1                      @ VPREV_FROZEN: the take is over
    beq     4f
    gyro_head r3, r1
    sub     r1, r3, r0                  @ head moves eight bytes a sample
    cmp     r1, #0
    addlt   r1, r1, #GYRO_RING_SPAN     @ it wraps every 240 ms
    lsr     r1, r1, #3
    str     r3, [ip, #O_VPREV]

    /* Only gaps long enough to be a frame go into the mean.  A doubled
     * interrupt shows up as a near-zero gap next to a full one; averaging both
     * halves in would report a frame period that never happened.
     *
     * min and max describe the long gaps ONLY.  A min taken over everything is
     * whatever the doubled interrupt left, which is no use; over the long gaps
     * it says what the shortest real frame was, and that is what makes the set
     * checkable. */
    cmp     r1, #VD_GAP_FLOOR
    blo     5f
    ldr     r0, [ip, #O_VMIN]
    cmp     r1, r0
    strlo   r1, [ip, #O_VMIN]
    ldr     r0, [ip, #O_VMAX]
    cmp     r1, r0
    strhi   r1, [ip, #O_VMAX]
    ldr     r0, [ip, #O_VSUM]
    add     r0, r0, r1
    str     r0, [ip, #O_VSUM]
    ldr     r0, [ip, #O_VNF]
    add     r0, r0, #1
    str     r0, [ip, #O_VNF]
    b       4f
5:  ldr     r0, [ip, #O_VSHORT]
    add     r0, r0, #1
    str     r0, [ip, #O_VSHORT]
    ldr     r0, [ip, #O_VOMAX]
    cmp     r1, r0
    strhi   r1, [ip, #O_VOMAX]

4:  movw    ip, #:lower16:STREAM_INDEX
    movt    ip, #:upper16:STREAM_INDEX
1:  ldrex   r0, [ip]
    add     r1, r0, #1
    strex   r3, r1, [ip]
    cmp     r3, #0
    bne     1b

    ring_slot r0, r1, r3

    strh    r2, [r1]                    @ x = which Vd of this take
    mov     r0, #0
    strh    r0, [r1, #2]
    strh    r0, [r1, #6]
    mov     r0, #TAG_VD
    strh    r0, [r1, #4]                @ last: the tag publishes the record

    pop     {r0, r1, r2, r3, ip, lr}
    movt    r4, #0xC31D                 @ the displaced instruction
    bx      lr                          @ lr has bit 0 set: back to Thumb
