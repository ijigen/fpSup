.syntax unified
.arm
.text

/* ============================================================================
 * fpGyroSup, the edition that writes the Gyroflow log itself.
 * ============================================================================
 *
 * The stream underneath is Base's, unchanged: the same hooks fill the same
 * blocks with the same eight-byte records, and the same "a block is full"
 * event hands one to the same task.  Everything in writer_core.inc.S is shared
 * with Base and none of it knows which edition it is in.
 *
 * Three functions differ, and they are the three the core calls without
 * looking inside:
 *
 *   writer_openfile   opens \GYRO\A001_037.gcsv and writes the header
 *   writer_put        turns a block of records into rows and writes those
 *   writer_closefile  sends out the row still held, corrects the drop count,
 *                     and lets the destructor close the file
 *
 * So no .GYR is produced.  The records still exist -- they are what fills the
 * blocks -- but they never reach the card; the text does, one write per block.
 * 16 KiB is the trigger unit, not the write size: it is where "the buffer is
 * full" happens, and what gets written is whatever that block turned into.
 *
 * Formatting here rather than in a hook is the whole point of it being here at
 * all: this is a task at priority 6 with the entire block in front of it and
 * the stream in order.  A hook is an interrupt that sees one sample.
 * ========================================================================== */

#include "writer_core.inc.S"

/* --------------------------------------------------------------- the file */

/* writer_openfile -- open the log for the take that is starting.
 *
 * take_path builds \GYRO\A001_037.GYR from the object the camera names clips
 * from; only the extension differs here, and it is four bytes.
 */
    .global writer_openfile
writer_openfile:
    push    {r4, r5, r6, lr}
#ifdef DRY_RUN
    movw    ip, #:lower16:T_FOPEN
    movt    ip, #:upper16:T_FOPEN
    mov     r0, #1
    str     r0, [ip]
    pop     {r4, r5, r6, lr}
    bx      lr
#endif
    movw    r4, #:lower16:T_FOBJ
    movt    r4, #:upper16:T_FOBJ
    ldr     r4, [r4]
    cmp     r4, #0
    beq     9f

    movw    ip, #:lower16:F_MGR
    movt    ip, #:upper16:F_MGR
    blx     ip
    mov     r1, #0
    movw    ip, #:lower16:F_VOL
    movt    ip, #:upper16:F_VOL
    blx     ip
    mov     r5, r0                      @ the volume: the ctor's, and the name's
    bl      take_path
    mov     r6, r0

    /* "\GYRO\A001_037" is fourteen bytes; the extension is ours. */
    mov     r0, #'.'
    strb    r0, [r6, #14]
    mov     r0, #'g'
    strb    r0, [r6, #15]
    mov     r0, #'c'
    strb    r0, [r6, #16]
    mov     r0, #'s'
    strb    r0, [r6, #17]
    mov     r0, #'v'
    strb    r0, [r6, #18]
    mov     r0, #0
    strb    r0, [r6, #19]

    mov     r1, r5
    mov     r0, r4
    movw    ip, #:lower16:F_CTOR
    movt    ip, #:upper16:F_CTOR
    blx     ip

    mov     r0, r4
    mov     r1, r6
    mov     r2, #F_MODE_AUD
    movw    ip, #:lower16:F_OPEN
    movt    ip, #:upper16:F_OPEN
    blx     ip
    /* If it did not open, it did not open: \GYRO has to already exist on the
     * volume being recorded to, and putting it there is the user's business.
     * See Base's copy of this for the two ways we tried doing it ourselves and
     * what each of them cost. */
    movw    ip, #:lower16:T_FOPEN
    movt    ip, #:upper16:T_FOPEN
    str     r0, [ip]
    cmp     r0, #0
    beq     8f

    mov     r0, r4
    movw    ip, #:lower16:F_STAMP
    movt    ip, #:upper16:F_STAMP
    blx     ip

    /* t starts at zero and nothing is held over from the last take. */
    mov     r0, #0
    movw    ip, #:lower16:G_ROW
    movt    ip, #:upper16:G_ROW
    str     r0, [ip]
    movw    ip, #:lower16:G_HELD_OK
    movt    ip, #:upper16:G_HELD_OK
    str     r0, [ip]

    bl      gcsv_header
    b       9f

8:  mov     r0, r4                      @ it did not open: do not leave it built
    mov     r1, #2
    movw    ip, #:lower16:F_DTOR
    movt    ip, #:upper16:F_DTOR
    blx     ip

9:  pop     {r4, r5, r6, lr}
    bx      lr

/* gcsv_header -- build the header in the text buffer and write it.
 *
 * Two constant halves with the clip's eight characters between them.  The drop
 * count is six fixed-width digits inside the first half, rewritten when the
 * take closes -- fixed width so the rewrite moves nothing after it.
 */
gcsv_header:
    push    {r4, r5, r6, lr}
    movw    r4, #:lower16:G_TEXT
    movt    r4, #:upper16:G_TEXT
    ldr     r4, [r4]
    cmp     r4, #0
    beq     9f
    mov     r5, r4

    mov     r0, #G_OFF_HEAD1
    bl      blob_at
    mov     r1, r5
    bl      put_str
    mov     r5, r0

    mov     r0, #G_OFF_PATH
    bl      blob_at
    add     r6, r0, #6                  @ past "\GYRO\"
    mov     r1, #8
1:  ldrb    r0, [r6], #1
    strb    r0, [r5], #1
    subs    r1, r1, #1
    bne     1b

    mov     r0, #G_OFF_HEAD2
    bl      blob_at
    mov     r1, r5
    bl      put_str
    mov     r5, r0

    sub     r2, r5, r4
    movw    ip, #:lower16:T_POS
    movt    ip, #:upper16:T_POS
    str     r2, [ip]                    @ the file is at the end of the header
    movw    r0, #:lower16:T_FOBJ
    movt    r0, #:upper16:T_FOBJ
    ldr     r0, [r0]
    mov     r1, r4
    movw    ip, #:lower16:F_WRITE
    movt    ip, #:upper16:F_WRITE
    blx     ip
9:  pop     {r4, r5, r6, lr}
    bx      lr

/* put_str -- r0 = a NUL-terminated string, r1 = destination.  Returns it
 * advanced.  The two header halves are the only strings here. */
put_str:
    push    {r4, lr}
1:  ldrb    r4, [r0], #1
    cmp     r4, #0
    beq     2f
    strb    r4, [r1], #1
    b       1b
2:  mov     r0, r1
    pop     {r4, lr}
    bx      lr

/* -------------------------------------------------------------- the block */

/* writer_put -- r4 = the job.  Turn its records into rows and write them.
 *
 * One write, whatever the block turned into -- about 45 KB.  The loop is still
 * here because the formatter takes a budget, but the budget is a whole block's
 * worth so it runs once.
 *
 * It used to write 16 KiB at a time, which sounded right and was not: 16 KiB is
 * the size at which a buffer is declared full, not a write size.  Base's block
 * became one 16 KiB write because a block of records is 16 KiB; a block of rows
 * is three times that, and writing it in three took the card lock three times
 * as often.  With that in it a take stopped by itself at 2:18; the camera has
 * recorded on this card for years without doing that.
 *
 * There is no seek.  Base seeks because a dropped block leaves a hole of known
 * size; a row has no fixed size, so a dropped block here is simply rows that
 * are not there -- and because t is the sample number, the gap says so itself.
 */
    .global writer_put
writer_put:
    push    {r5, r6, r7, r8, r9, lr}
    ldr     r5, [r4, #J_PTR]
    ldr     r6, [r4, #J_LEN]
    lsr     r6, r6, #3                  @ records
    cmp     r6, #0
    beq     9f
    movw    r7, #:lower16:G_TEXT
    movt    r7, #:upper16:G_TEXT
    ldr     r7, [r7]
    cmp     r7, #0
    beq     9f

1:  mov     r0, r5
    mov     r1, r6
    mov     r2, r7
    movw    r3, #:lower16:TEXT_BYTES
    movt    r3, #:upper16:TEXT_BYTES
    add     r3, r7, r3                  @ one past the last byte it may use
    bl      gcsv_format
    mov     r8, r0                      @ where the text ended
    sub     r9, r6, r1                  @ records it got through
    mov     r6, r1                      @ records still to do
    add     r5, r5, r9, lsl #3

    subs    r2, r8, r7
    beq     2f
#ifndef DRY_RUN
    mov     r1, r7
    movw    r0, #:lower16:T_FOBJ
    movt    r0, #:upper16:T_FOBJ
    ldr     r0, [r0]
    movw    ip, #:lower16:F_WRITE
    movt    ip, #:upper16:F_WRITE
    blx     ip
    movw    ip, #:lower16:T_WRC
    movt    ip, #:upper16:T_WRC
    str     r0, [ip]
#else
    movw    ip, #:lower16:T_WRC
    movt    ip, #:upper16:T_WRC
    mov     r0, #1
    str     r0, [ip]
#endif
    sub     r2, r8, r7
    movw    ip, #:lower16:T_BYTES
    movt    ip, #:upper16:T_BYTES
    ldr     r0, [ip]
    add     r0, r0, r2
    str     r0, [ip]
    movw    ip, #:lower16:T_POS
    movt    ip, #:upper16:T_POS
    ldr     r0, [ip]
    add     r0, r0, r2
    str     r0, [ip]
    movw    ip, #:lower16:T_WRITES
    movt    ip, #:upper16:T_WRITES
    ldr     r0, [ip]
    add     r0, r0, #1
    str     r0, [ip]

2:  cmp     r9, #0
    beq     9f                          @ it consumed nothing: no more room and
                                        @ no more progress, so stop rather than
                                        @ spin
    cmp     r6, #0
    bne     1b

9:  pop     {r5, r6, r7, r8, r9, lr}
    bx      lr

/* --------------------------------------------------------------- the end */

/* writer_closefile -- the take is over.
 *
 * The row still held goes out, the drop count in the note becomes the real one,
 * and the destructor closes the file.  Audio never calls F_CLOSE itself: the
 * destructor's first act is FUN_c0366020, which is F_CLOSE, so calling both
 * goes through that path twice.
 */
    .global writer_closefile
writer_closefile:
    push    {r4, r5, r6, lr}
    movw    r6, #:lower16:T_STAGE
    movt    r6, #:upper16:T_STAGE
    mov     r0, #0x21
    str     r0, [r6]

    movw    r4, #:lower16:T_FOPEN
    movt    r4, #:upper16:T_FOPEN
    ldr     r5, [r4]
    cmp     r5, #0
    beq     9f
#ifdef DRY_RUN
    mov     r0, #0
    str     r0, [r4]
    mov     r0, #0x25
    str     r0, [r6]
    pop     {r4, r5, r6, lr}
    bx      lr
#endif

    /* Whatever row is still held.  Without this the last sample of every take
     * is the one that never arrives. */
    movw    r5, #:lower16:G_TEXT
    movt    r5, #:upper16:G_TEXT
    ldr     r5, [r5]
    cmp     r5, #0
    beq     2f
    mov     r0, r5
    bl      gcsv_last
    subs    r2, r0, r5
    beq     2f
    mov     r1, r5
    movw    r0, #:lower16:T_FOBJ
    movt    r0, #:upper16:T_FOBJ
    ldr     r0, [r0]
    movw    ip, #:lower16:F_WRITE
    movt    ip, #:upper16:F_WRITE
    blx     ip

2:  /* The note's drop count, in place.  Six digits wide whatever it says, so
     * nothing after it moves. */
    movw    r5, #:lower16:G_TEXT
    movt    r5, #:upper16:G_TEXT
    ldr     r5, [r5]
    cmp     r5, #0
    beq     3f
    movw    r0, #:lower16:B_DROPS
    movt    r0, #:upper16:B_DROPS
    ldr     r0, [r0]
    mov     r1, r5
    bl      put_u32_6
    movw    r0, #:lower16:T_FOBJ
    movt    r0, #:upper16:T_FOBJ
    ldr     r0, [r0]
    mov     r1, #NOTE_DROPS_AT
    mov     r2, #0
    movw    ip, #:lower16:F_SEEK
    movt    ip, #:upper16:F_SEEK
    blx     ip
    movw    r0, #:lower16:T_FOBJ
    movt    r0, #:upper16:T_FOBJ
    ldr     r0, [r0]
    mov     r1, r5
    mov     r2, #NOTE_DROPS_N
    movw    ip, #:lower16:F_WRITE
    movt    ip, #:upper16:F_WRITE
    blx     ip

3:  mov     r0, #0x24
    str     r0, [r6]
    movw    r5, #:lower16:T_FOBJ
    movt    r5, #:upper16:T_FOBJ
    ldr     r5, [r5]
    mov     r0, r5
    mov     r1, #2
    movw    ip, #:lower16:F_DTOR
    movt    ip, #:upper16:F_DTOR
    blx     ip
    mov     r0, #0x25
    str     r0, [r6]
    mov     r0, #0
    str     r0, [r4]

9:  pop     {r4, r5, r6, lr}
    bx      lr

/* ------------------------------------------------------------ the header */

/* Everything before the six digits is a constant, which is what lets the close
 * rewrite them at NOTE_DROPS_AT without moving a byte. */
    .global gcsv_head1
gcsv_head1:
    .asciz  "GYROFLOW IMU LOG\nversion,1.3\nid,sigma_fp_v502_internal_icm20321\norientation,xyz\nnote,fpGyroSup Base; dropped_blocks=000000\nfwversion,SIGMA fp 5.02\nvideofilename,"
    .balign 4

/* tscale is the sample period and t is the sample number, so nothing rounds and
 * nothing drifts.  gscale and ascale are the sensors' own counts to units; the
 * columns carry the counts unconverted. */
    .global gcsv_head2
gcsv_head2:
    .asciz  "\ntscale,0.0004000854\ngscale,0.000137923\nascale,0.0009765625\nt,gx,gy,gz,ax,ay,az\n"
    .balign 4

#include "gcsv_rows.S"
