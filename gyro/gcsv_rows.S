.syntax unified
.arm
.text

#include "imu_stream.inc.S"
#include "ring_task.inc.S"

/* ============================================================================
 * A block of records, as gcsv rows.  Runs in the writer, not in a hook.
 * ============================================================================
 *
 * The producers are not touched by any of this.  The accelerometer hook and the
 * gyro drain still write the same eight-byte records into the same block, the
 * block still becomes the writer's when it fills, and the interrupt path is the
 * one that ran eleven minutes with nothing dropped.  What changes is what the
 * writer does when it wakes: it used to hand the block to F_WRITE as it stood,
 * and now it turns it into text first.
 *
 * Which is where this belongs.  The writer is a task at priority 6 with the
 * whole block in front of it and the stream in order; a hook is an interrupt
 * that sees one sample and has no business formatting anything.
 *
 * Seeing the stream in order is also what makes the accelerometer land right.
 * A reading is written into the block AFTER the gyro samples it came after --
 * that is the drain-then-append order the hook has always used -- so a row is
 * held back by one record: when the next record is a reading, the held row
 * carries it; when the next record is another sample, the held row goes out
 * plain.  The reading ends up on the sample it followed, which is where it
 * happened, and nothing has to be patched after it is written.
 *
 * A row held at the end of a block stays held, in G_HELD, and goes out at the
 * head of the next one.  Blocks are a card-sized unit, not a sample-sized one.
 *
 * TWO RULES, both from gcsvgen.S -- the only things taken from v1.4, and both
 * are rules rather than code:
 *
 *   1. A row with no reading ends after gz with NO trailing comma.  It must not
 *      be "...,gz,,": the empty fields parse as three ZEROES, and the file
 *      still opens and still looks right.
 *
 *   2. The accelerometer's axes are not the gyro's and gcsv carries one
 *      orientation string for both, so the quarter turn happens here: native Y
 *      becomes gcsv X, native X negated becomes gcsv Y, Z stays Z.
 *
 * Nothing is scaled.  The columns carry the sensor's own counts, exactly as the
 * records carried them, and gscale and ascale in the header are what turn them
 * into units.  Only the alphabet changes.
 *
 * t is the sample number, because tscale is the sample period.  No timestamp is
 * computed, so none can round and none can drift.
 * ========================================================================== */

/* Worst case for one row: ten digits of t, then three of "-32768," and three
 * more for the reading, then a newline.  Fifty-four; sixty-four with room. */
.equ ROW_MAX,        64

/* ------------------------------------------------------------------ digits */

/* Two decimal digits an entry, little-endian, so one strh emits both. */
    .balign 2
dec_pairs:
    .ascii  "0001020304050607080910111213141516171819"
    .ascii  "2021222324252627282930313233343536373839"
    .ascii  "4041424344454647484950515253545556575859"
    .ascii  "6061626364656667686970717273747576777879"
    .ascii  "8081828384858687888990919293949596979899"
    .balign 4

/* put_u32 -- r0 = value, r1 = destination.  Returns the destination advanced.
 *
 * No hardware divide on this core, so /100 is the exact reciprocal multiply
 * (n * 0x51EB851F) >> 37, two digits a turn.  Digits arrive least significant
 * first, so they are built backwards in a stack scratch and copied forward.
 *
 * v1.4 spends forty kilobytes on a 0000..9999 table to avoid this.  It had
 * reason to: it formats a whole take in one pass and counted 620,000 calls.
 * This formats about four numbers per sample, spread across the take, and the
 * table would buy a few microseconds a second for forty kilobytes.
 *
 * The arithmetic was checked against Python over every value from 0 to 19999,
 * every power of ten, every 2^k-1, and sixty thousand random 32-bit values.
 */
    .global put_u32
put_u32:
    push    {r4, r5, r6, lr}
    sub     sp, sp, #16
    add     r4, sp, #12                 @ one past the end; digits grow down
    adr     r5, dec_pairs

1:  cmp     r0, #100
    blo     2f
    movw    r6, #0x851F
    movt    r6, #0x51EB
    umull   ip, r6, r0, r6
    lsr     r6, r6, #5                  @ r6 = value / 100
    add     ip, r6, r6, lsl #2          @ 5q
    sub     r0, r0, ip, lsl #4          @ -80q  } value - 100q, no multiply
    sub     r0, r0, ip, lsl #2          @ -20q  }
    add     ip, r5, r0, lsl #1
    ldrh    ip, [ip]
    sub     r4, r4, #2
    strh    ip, [r4]
    mov     r0, r6
    b       1b

2:  cmp     r0, #10
    blo     3f
    add     ip, r5, r0, lsl #1
    ldrh    ip, [ip]
    sub     r4, r4, #2
    strh    ip, [r4]
    b       4f
3:  add     ip, r0, #'0'
    sub     r4, r4, #1
    strb    ip, [r4]

4:  add     r5, sp, #12                 @ copy forward into the row
5:  ldrb    ip, [r4], #1
    strb    ip, [r1], #1
    cmp     r4, r5
    blo     5b

    mov     r0, r1
    add     sp, sp, #16
    pop     {r4, r5, r6, lr}
    bx      lr

/* put_i16 -- r0 = signed value, r1 = destination.  Returns it advanced. */
    .global put_i16
put_i16:
    push    {r4, lr}
    cmp     r0, #0
    bge     1f
    mov     r4, #'-'
    strb    r4, [r1], #1
    rsb     r0, r0, #0
1:  bl      put_u32
    pop     {r4, lr}
    bx      lr

/* ------------------------------------------------------------------- rows */

/* gcsv_emit -- r0 = the sample, r1 = the reading or zero, r2 = destination.
 *
 * Both point at eight-byte records in the stream's own layout: x at +0, y at
 * +2, z at +6.  Returns the destination advanced.  Consumes one t.
 */
    .global gcsv_emit
gcsv_emit:
    push    {r4, r5, r6, r7, r8, lr}
    mov     r4, r0
    mov     r7, r1
    mov     r5, r2

    movw    r6, #:lower16:G_ROW
    movt    r6, #:upper16:G_ROW
    ldr     r0, [r6]
    add     ip, r0, #1
    str     ip, [r6]
    mov     r1, r5
    bl      put_u32
    mov     r5, r0

    mov     r0, #','
    strb    r0, [r5], #1
    ldrsh   r0, [r4]
    mov     r1, r5
    bl      put_i16
    mov     r5, r0
    mov     r0, #','
    strb    r0, [r5], #1
    ldrsh   r0, [r4, #2]
    mov     r1, r5
    bl      put_i16
    mov     r5, r0
    mov     r0, #','
    strb    r0, [r5], #1
    ldrsh   r0, [r4, #6]                @ z sits past the tag, as in the ring
    mov     r1, r5
    bl      put_i16
    mov     r5, r0

    cmp     r7, #0
    beq     9f                          @ no reading: end after gz, and end
                                        @ there -- ",," is three zeroes, not
                                        @ three blanks

    mov     r0, #','
    strb    r0, [r5], #1
    ldrsh   r0, [r7, #2]                @ native Y -> gcsv X
    mov     r1, r5
    bl      put_i16
    mov     r5, r0
    mov     r0, #','
    strb    r0, [r5], #1
    ldrsh   r0, [r7]                    @ native X negated -> gcsv Y
    rsb     r0, r0, #0
    mov     r1, r5
    bl      put_i16
    mov     r5, r0
    mov     r0, #','
    strb    r0, [r5], #1
    ldrsh   r0, [r7, #6]                @ Z is Z
    mov     r1, r5
    bl      put_i16
    mov     r5, r0

9:  mov     r0, #'\n'
    strb    r0, [r5], #1
    mov     r0, r5
    pop     {r4, r5, r6, r7, r8, lr}
    bx      lr

/* gcsv_format -- r0 = the records, r1 = how many, r2 = destination,
 *                r3 = one past the last byte that may be written.
 *
 * Returns r0 = the destination advanced, r1 = how many records are LEFT --
 * the caller subtracts, which costs it one instruction and costs this a
 * register it does not have.
 * One pass, in order, holding one row back so a reading can land on the sample
 * it followed; whatever is still held when the records run out stays held for
 * the next call, block boundary or not.
 *
 * It stops when fewer than ROW_MAX bytes are left rather than when the buffer
 * is exactly full, so a row is never cut in half.  The caller writes what it
 * got, moves along by what was consumed, and comes back -- which is how a
 * 16 KiB block of records becomes three 16 KiB writes of text without the
 * write size, the one number audio and eleven minutes of camera agree on,
 * changing at all.
 */
    .global gcsv_format
gcsv_format:
    push    {r4, r5, r6, r7, r8, lr}
    mov     r4, r0
    mov     r5, r1
    mov     r6, r2
    mov     r7, r3
    sub     r7, r7, #ROW_MAX            @ the last place a row may start
    movw    r8, #:lower16:G_HELD
    movt    r8, #:upper16:G_HELD

1:  cmp     r5, #0
    beq     9f
    cmp     r6, r7
    bhi     9f                          @ no room for another row
    ldrsh   r0, [r4, #4]
    cmp     r0, #TAG_ACCEL
    beq     3f

    /* A sample.  Whatever was held had no reading after it, so it goes out
     * plain, and this one takes its place. */
    bl      2f
    ldr     r0, [r4]
    ldr     r1, [r4, #4]
    str     r0, [r8]
    str     r1, [r8, #4]
    mov     r0, #1
    str     r0, [r8, #8]                @ G_HELD_OK
    b       4f

3:  /* A reading.  It came after the held sample, so that row carries it. */
    ldr     r0, [r8, #8]
    cmp     r0, #0
    beq     4f                          @ nothing held: the row it belongs to
                                        @ went out with the previous block
    mov     r0, r8
    mov     r1, r4
    mov     r2, r6
    bl      gcsv_emit
    mov     r6, r0
    mov     r0, #0
    str     r0, [r8, #8]

4:  add     r4, r4, #8
    sub     r5, r5, #1
    b       1b

2:  /* Send the held row out with no reading, if there is one. */
    push    {r0, r1, r2, lr}
    ldr     r0, [r8, #8]
    cmp     r0, #0
    beq     8f
    mov     r0, r8
    mov     r1, #0
    mov     r2, r6
    bl      gcsv_emit
    mov     r6, r0
    mov     r0, #0
    str     r0, [r8, #8]
8:  pop     {r0, r1, r2, lr}
    bx      lr

9:  mov     r0, r6
    mov     r1, r5                      @ what is left, not what was taken
    pop     {r4, r5, r6, r7, r8, lr}
    bx      lr

/* gcsv_last -- r0 = destination.  Returns it advanced.
 *
 * The take is over: send out whatever row is still held.  Without this the very
 * last sample of every take is the one that never arrives, which is the kind of
 * thing nobody notices until they are looking for something else.
 */
    .global gcsv_last
gcsv_last:
    push    {r4, r5, r6, lr}
    mov     r6, r0
    movw    r5, #:lower16:G_HELD
    movt    r5, #:upper16:G_HELD
    ldr     r0, [r5, #8]
    cmp     r0, #0
    beq     9f
    mov     r0, r5
    mov     r1, #0
    mov     r2, r6
    bl      gcsv_emit
    mov     r6, r0
    mov     r0, #0
    str     r0, [r5, #8]
9:  mov     r0, r6
    pop     {r4, r5, r6, lr}
    bx      lr
