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

/* Base is the stream and nothing else, so the mode hook -- and with it the
 * orientation of what gets recorded -- belongs to this edition only.  The
 * core arms it if this is defined and does not know what it is for.
 *
 * The guard is not decoration.  build_base_card.sections() leaves the mode
 * section out of a base card, so defining this for both editions would arm
 * 0xC0058310 to branch at MODE_AT -- into cave bytes nobody wrote.  That is
 * the shape of the four-byte patch that once branched into the middle of the
 * logger.  It happened here on 2026-09-20, when base and gcsv became one
 * source and this define came along for the ride. */
#ifndef FPGYRO_EDITION_BASE
#define WANT_MODE_HOOK 1
#endif

#include "writer_core.inc.S"

/* ---- what the edition changes ------------------------------------------- *
 *
 * One source, two products.  Base was a separate file (`ring_task.S`) and that
 * is precisely why it went stale: the profile size fix of 2026-09-19 landed in
 * gcsv and base kept writing the menu's size for another day.  A flag cannot
 * be forgotten the way a second file can.
 *
 * The three axes, and nothing else differs:
 *
 *   where    base writes to the volume's ROOT.  Not a folder -- people forget
 *            to make it and report the log missing, and making one at record
 *            start is what froze the camera on every SSD take (see clip_path).
 *            The ladder already had this: rung 1 is the root, so base simply
 *            starts one rung down.
 *   what     base writes the records exactly as the producers left them.  No
 *            text, no re-ordering: the tag in each record already says whether
 *            it is gyro or accelerometer, so nothing has to be separated out.
 *   header   20 bytes, holding only what a reader cannot work out for itself.
 *            Everything descriptive -- mode, size, lens -- is in the .json,
 *            which is the same file, in the same format, in both editions.
 */
#ifdef FPGYRO_EDITION_BASE
.equ LOG_EXT,     'G'       /* .GYR */
.equ RUNG_FIRST,  1         /* the root; rung 0 is the clip folder */
.equ GYR_HDR_BYTES, 20
#else
.equ LOG_EXT,     'g'       /* .gcsv */
.equ RUNG_FIRST,  0
#endif

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

    /* Start at the top of the ladder, and record what happens on each rung:
     * an SSD take cannot be watched from the host, because the camera has one
     * USB socket and the SSD is in it. */
    mov     r0, #RUNG_FIRST
    SHAREDAT    ip, O_G_FALLBACK
    str     r0, [ip]
#ifdef FPGYRO_EDITION_BASE
    mov     r0, #0                      @ gcsv's first rung IS zero, so only
                                        @ base has to put it back
#endif
    SHAREDAT    ip, O_D_OPEN1
    str     r0, [ip]
    str     r0, [ip, #4]                @ D_OPEN2
    str     r0, [ip, #8]                @ D_OPEN3

    movw    ip, #:lower16:F_MGR
    movt    ip, #:upper16:F_MGR
    blx     ip
    mov     r1, #0
    movw    ip, #:lower16:F_VOL
    movt    ip, #:upper16:F_VOL
    blx     ip
    mov     r5, r0                      @ the volume: the ctor's, and the name's
    SHAREDAT    ip, O_D_VOL
    str     r0, [ip]
    bl      take_path

#ifndef FPGYRO_EDITION_BASE
    /* Rung 0: beside the clip, on the volume being recorded to.  Base skips it:
     * its log goes to the root, so there is nothing to try first. */
    mov     r0, #LOG_EXT
    bl      clip_path
    mov     r6, r0
    bl      dbg_path                    @ keep it; the next attempt overwrites
    mov     r1, r5
    bl      try_open
    SHAREDAT    ip, O_D_OPEN1
    str     r0, [ip]
    cmp     r0, #0
    bne     7f
#endif

    /* Rung 1: \fpSupGYRO on the same volume -- an SSD take's log belongs with
     * the SSD's footage, not on whatever card happens to be in the slot. */
    mov     r0, #1
    SHAREDAT    ip, O_G_FALLBACK
    str     r0, [ip]
    mov     r0, #LOG_EXT
    bl      clip_path
    mov     r6, r0
    mov     r1, r5
    bl      try_open
    SHAREDAT    ip, O_D_OPEN2
    str     r0, [ip]
    cmp     r0, #0
    bne     7f

    /* Rung 2: \fpSupGYRO on the SD card.  Nothing of the take is written to a
     * camera volume when an HDMI recorder has it, and this is the rung that
     * still gives the log somewhere to go. */
    mov     r0, #2
    SHAREDAT    ip, O_G_FALLBACK
    str     r0, [ip]
    mov     r5, #VOL_SD
    mov     r0, #LOG_EXT
    bl      clip_path
    mov     r6, r0
    mov     r1, r5
    bl      try_open
    SHAREDAT    ip, O_D_OPEN3
    str     r0, [ip]

7:  movw    ip, #:lower16:T_FOPEN
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
    SHAREDAT    ip, O_G_ROW
    str     r0, [ip]
    SHAREDAT    ip, O_G_HELD_OK
    str     r0, [ip]

    /* Orientation is not decided here.  Clearing the attitude gate at record
     * start was tried and the first frame of a portrait take still read
     * Orientation 8 with this code demonstrably run, so whatever consumes it
     * has consumed it by now.  mode_hook.S does it at the STILL/CINE switch
     * instead, which is minutes earlier. */

#ifdef FPGYRO_EDITION_BASE
    bl      gyr_header
#else
    bl      gcsv_header
#endif
    bl      gcsv_json_write
    b       9f

8:  /* Nothing is built: try_open gives the object back on every rung it
     * fails, so there is nothing left to destroy here. */

9:  pop     {r4, r5, r6, lr}
    bx      lr


/* try_open -- r4 = the file object, r6 = the path, r1 = the volume.  Returns
 * the open result in r0, and leaves NOTHING built when it fails, so the next
 * rung can construct again.  A file object left constructed after a failed
 * open is the \LENS.DAT trap: every later open fails too. */
try_open:
    push    {r7, lr}
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
    mov     r7, r0
    cmp     r7, #0
    bne     1f
    mov     r0, r4
    mov     r1, #2
    movw    ip, #:lower16:F_DTOR
    movt    ip, #:upper16:F_DTOR
    blx     ip
1:  mov     r0, r7
    pop     {r7, lr}
    bx      lr


/* dbg_path -- keep the first path we tried, because the next rung overwrites
 * the buffer and an SSD take cannot be watched while it happens. */
dbg_path:
    push    {r0, lr}
    SHAREDAT    r1, O_D_PATH
    mov     r2, r6
    mov     r3, #48
1:  ldrb    r0, [r2], #1
    strb    r0, [r1], #1
    subs    r3, r3, #1
    beq     2f
    cmp     r0, #0
    bne     1b
2:  pop     {r0, lr}
    bx      lr

/* clip_path -- the log's path, beside the clip.  r0 = 'g' for the .gcsv or
 * 'j' for the .json; returns the path.
 *
 *   CinemaDNG   \CINEMA\A001_037\A001_037.gcsv
 *   MOV         \CINEMA\A001_037.gcsv
 *
 * A CinemaDNG take is a folder of frames and the sidecars belong inside it; a
 * MOV take is one file and they belong beside it.  Which one is happening is
 * twelve bytes past the frame size in the settings block the dimensions
 * already come from -- 0 is CinemaDNG, 1 is MOV -- so this costs one load and
 * needs no new address.
 *
 * Nothing is created here.  \CINEMA and the clip's folder are the camera's
 * own, made before this runs, which is why this edition needs no folder of its
 * own and no mkdir on the record path.
 */
    .global clip_path
clip_path:
    push    {r4, r5, r6, r7, r8, lr}
    mov     r7, r0                      @ 'g' or 'j'

    mov     r0, #G_OFF_PATH
    bl      blob_at
    mov     r6, r0

    /* The fallback is the root of the volume: one character, no folder to
     * make, and no second copy of the name.  Making a directory at record
     * start is what froze the camera on every SSD take. */
    SHAREDAT    r8, O_G_FALLBACK
    ldr     r8, [r8]
    cmp     r8, #0
    beq     0f
    mov     r0, #'\\'
    strb    r0, [r6], #1
    b       1f

0:  movw    r0, #0x435C
    movt    r0, #0x4E49                 @ "\\CIN"
    str     r0, [r6]
    movw    r0, #0x4D45
    movt    r0, #0x5C41                 @ "EMA\\"
    str     r0, [r6, #4]
    add     r6, r6, #8

1:  mov     r0, #G_OFF_CLIP
    bl      blob_at
    mov     r4, r0
    bl      copy_clip                   @ r6 advances past the eight characters
    cmp     r8, #0
    bne     2f                          @ the fallback has no folder of its own

    /* CinemaDNG puts the frames in a folder of their own; the sidecars go in
     * with them, so the name appears twice. */
    movw    ip, #:lower16:F_CAMSETTING
    movt    ip, #:upper16:F_CAMSETTING
    blx     ip
    cmp     r0, #0
    beq     2f
    ldr     r0, [r0, #SETTING_FORMAT]
    cmp     r0, #FORMAT_CDNG
    bne     2f
    mov     r0, #'\\'
    strb    r0, [r6], #1
    bl      copy_clip

2:  mov     r0, #'.'
    strb    r0, [r6], #1
    mov     r0, r7
    strb    r0, [r6], #1                @ LOG_EXT or 'j'
    cmp     r7, #LOG_EXT
    bne     4f
#ifdef FPGYRO_EDITION_BASE
    mov     r0, #'Y'                    @ .GYR
    strb    r0, [r6], #1
    mov     r0, #'R'
    strb    r0, [r6], #1
#else
    mov     r0, #'c'                    @ .gcsv
    strb    r0, [r6], #1
    mov     r0, #'s'
    strb    r0, [r6], #1
    mov     r0, #'v'
    strb    r0, [r6], #1
#endif
    b       3f
4:  mov     r0, #'s'
    strb    r0, [r6], #1
    mov     r0, #'o'
    strb    r0, [r6], #1
    mov     r0, #'n'
    strb    r0, [r6], #1
3:  mov     r0, #0
    strb    r0, [r6]
    mov     r0, #G_OFF_PATH
    bl      blob_at
    pop     {r4, r5, r6, r7, r8, lr}
    bx      lr

/* copy_clip -- r4 = the clip name, r6 = where it goes.  Advances r6. */
copy_clip:
    push    {r0, r1, r2, lr}
    mov     r1, #0
1:  ldrb    r0, [r4, r1]
    cmp     r0, #0
    beq     2f
    strb    r0, [r6], #1
    add     r1, r1, #1
    b       1b
2:  pop     {r0, r1, r2, lr}
    bx      lr

#ifdef FPGYRO_EDITION_BASE
/* gyr_header -- twenty bytes, and only what a reader cannot work out itself.
 *
 *   0x00  magic       0x9F5BEB0D
 *   0x04  period_ps   400085400
 *   0x08  gscale      0.000137923f
 *   0x0C  ascale      0.0009765625f
 *   0x10  orient      0x007A7978   "xyz", all three axes negated
 *                     then 8-byte records to the end of the file
 *
 * The magic is the first four bytes of the SHA-256 of the format's own spec,
 * little-endian:
 *
 *   fpSup gyro stream: le; hdr magic,period_ps,gscale,ascale,orient; rec i16 x,y,tag,z
 *
 * A hash rather than a version number that counts up, because a counter has to
 * be taught to every reader every time it moves.  These four fields make the
 * file describe itself, so a recalibration changes the VALUES and the magic
 * stays put -- nothing downstream needs touching.  Only the LAYOUT changing
 * earns a new magic, and then the spec line above is what is re-hashed.
 *
 * Why these five and nothing else: each one is needed to READ the records.
 * period_ps because position is the only clock -- a record's place in the
 * stream is its time, and the old header's integer 400 us was fast by 0.085 us
 * on every sample, 3.4 ms of drift across forty seconds.  orient because the
 * axes are remapped and negated, and a reader that assumed otherwise would be
 * wrong in a way no check would catch.  Everything descriptive -- mode, frame
 * size, lens, exposure -- is in the .json, which is the same file in the same
 * format in both editions.
 *
 * Dropped from the sixty-four byte v7 header: clip id (it is the filename),
 * volume and payload (the file's own size is the payload), the drop count
 * (integrity tracking belongs to hdmi-raw), mode and width and height (the
 * .json), exposure_us (nothing computed with it -- two viewers printed it as
 * "1/50", and the DNG's EXIF has it per frame, which is better).
 */
.equ GYR_MAGIC,   0x9F5BEB0D
.equ GYR_ASCALE,  0x3A800000    /* 0.0009765625 = 2^-10, the accelerometer LSB */

gyr_header:
    push    {r4, r5, r6, lr}            @ r6 is unused: the frame has to stay
                                        @ 8-aligned across the F_WRITE below
    SHAREDAT    r4, O_G_TEXT
    ldr     r4, [r4]
    cmp     r4, #0
    beq     9f

    movw    r5, #:lower16:GYR_MAGIC
    movt    r5, #:upper16:GYR_MAGIC
    str     r5, [r4]
    movw    r5, #:lower16:GYR_PERIOD_PS
    movt    r5, #:upper16:GYR_PERIOD_PS
    str     r5, [r4, #4]
    movw    r5, #:lower16:GYR_GSCALE
    movt    r5, #:upper16:GYR_GSCALE
    str     r5, [r4, #8]
    movw    r5, #:lower16:GYR_ASCALE
    movt    r5, #:upper16:GYR_ASCALE
    str     r5, [r4, #12]
    movw    r5, #:lower16:GYR_ORIENT
    movt    r5, #:upper16:GYR_ORIENT
    str     r5, [r4, #16]

    mov     r2, #GYR_HDR_BYTES
    movw    ip, #:lower16:T_POS
    movt    ip, #:upper16:T_POS
    str     r2, [ip]                    @ the file is at the end of the header
    movw    ip, #:lower16:B_OFF
    movt    ip, #:upper16:B_OFF
    str     r2, [ip]                    @ and so is the first block.  Here, not
                                        @ in take_open: --dropfile after a
                                        @ freeze opens nothing and closes what
                                        @ is there, and an owner further out
                                        @ stamped the PREVIOUS take's length.
    movw    r0, #:lower16:T_FOBJ
    movt    r0, #:upper16:T_FOBJ
    ldr     r0, [r0]
    mov     r1, r4
    movw    ip, #:lower16:F_WRITE
    movt    ip, #:upper16:F_WRITE
    blx     ip
9:  pop     {r4, r5, r6, lr}
    bx      lr
#endif

/* gcsv_header -- build the header in the text buffer and write it.
 *
 * Two constant halves with the clip's eight characters between them.  The drop
 * count is six fixed-width digits inside the first half, rewritten when the
 * take closes -- fixed width so the rewrite moves nothing after it.
 */
gcsv_header:
    push    {r4, r5, r6, lr}
    SHAREDAT    r4, O_G_TEXT
    ldr     r4, [r4]
    cmp     r4, #0
    beq     9f
    mov     r5, r4

    mov     r0, #G_OFF_HEAD1
    bl      blob_at
    mov     r1, r5
    bl      put_str
    mov     r5, r0

    /* The eight characters of the clip, from the buffer take_path built them
     * in -- not from the path.  This used to skip six bytes into the path,
     * which is the length of Base's "\GYRO\"; this edition's path is
     * "\CINEMA\A001_011\A001_011.gcsv" and six bytes in is "A\A001_0",
     * which is what every take of this edition has written.  Gyroflow matches
     * a log to a clip by this name.  The clip buffer is the same in both
     * editions, so nothing can skip the wrong distance into it. */
    mov     r0, #G_OFF_CLIP
    bl      blob_at
    mov     r6, r0
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
#ifdef FPGYRO_EDITION_BASE
    /* Zero copy.  The records go to the card as the producers wrote them --
     * nothing formatted, nothing re-ordered, nothing separated out, because
     * the tag inside each record already says which sensor it came from.
     * That is the whole of what this edition does differently with a block.
     *
     * It seeks rather than appends, and the seek is the point: a job that
     * never gets a descriptor vanishes, and appending would move every record
     * after it earlier in the file by the length of the hole.  In a format
     * whose whole claim is that position IS time, that rewrites the timeline
     * and nothing in the file shows it.  Comparing J_OFF against T_POS catches
     * it, and T_SEEKS counts how often. */
    push    {r4, r5, r6, lr}
    movw    r5, #:lower16:T_POS
    movt    r5, #:upper16:T_POS
    ldr     r6, [r5]
    ldr     r0, [r4, #J_OFF]
    cmp     r6, r0
    beq     2f
#ifndef DRY_RUN
    movw    r1, #:lower16:T_FOBJ
    movt    r1, #:upper16:T_FOBJ
    ldr     r1, [r1]
    mov     r2, r0
    mov     r0, r1
    mov     r1, r2
    mov     r2, #0                      @ from the start of the file
    movw    ip, #:lower16:F_SEEK
    movt    ip, #:upper16:F_SEEK
    blx     ip
#endif
    movw    ip, #:lower16:T_SEEKS
    movt    ip, #:upper16:T_SEEKS
    ldr     r0, [ip]
    add     r0, r0, #1
    str     r0, [ip]                    @ every one of these is a job that was lost
    ldr     r0, [r4, #J_OFF]

2:  ldr     r6, [r4, #J_LEN]
    add     r0, r0, r6
    str     r0, [r5]                    @ where the file is once this lands
    cmp     r6, #0
    beq     8f
    ldr     r5, [r4, #J_PTR]
#ifndef DRY_RUN
    mov     r2, r6
    mov     r1, r5
    movw    r0, #:lower16:T_FOBJ
    movt    r0, #:upper16:T_FOBJ
    ldr     r0, [r0]
    movw    ip, #:lower16:F_WRITE
    movt    ip, #:upper16:F_WRITE
    blx     ip
    BLOBBASE ip                         @ one base, four counters
    str     r0, [ip, #O_T_WRC]
#else
    BLOBBASE ip
    mov     r0, #1
    str     r0, [ip, #O_T_WRC]
#endif
    ldr     r0, [ip, #O_T_BYTES]
    add     r0, r0, r6
    str     r0, [ip, #O_T_BYTES]
    ldr     r0, [ip, #O_T_WRITES]
    add     r0, r0, #1
    str     r0, [ip, #O_T_WRITES]
8:  pop     {r4, r5, r6, lr}
    bx      lr
#else
    push    {r5, r6, r7, r8, r9, lr}
    ldr     r5, [r4, #J_PTR]
    ldr     r6, [r4, #J_LEN]
    lsr     r6, r6, #3                  @ records
    cmp     r6, #0
    beq     9f
    SHAREDAT    r7, O_G_TEXT
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
    BLOBBASE ip                         @ one base for the counters below
    str     r0, [ip, #O_T_WRC]
#else
    BLOBBASE ip
    mov     r0, #1
    str     r0, [ip, #O_T_WRC]
#endif
    sub     r2, r8, r7
    ldr     r0, [ip, #O_T_BYTES]
    add     r0, r0, r2
    str     r0, [ip, #O_T_BYTES]
    ldr     r0, [ip, #O_T_WRITES]
    add     r0, r0, #1
    str     r0, [ip, #O_T_WRITES]
    movw    ip, #:lower16:T_POS             @ still a cave word: next group
    movt    ip, #:upper16:T_POS
    ldr     r0, [ip]
    add     r0, r0, r2
    str     r0, [ip]

2:  cmp     r9, #0
    beq     9f                          @ it consumed nothing: no more room and
                                        @ no more progress, so stop rather than
                                        @ spin
    cmp     r6, #0
    bne     1b

9:  pop     {r5, r6, r7, r8, r9, lr}
    bx      lr
#endif

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
    BLOBBASE r6                         @ r6 carries the base through the close
    mov     r0, #0x21
    str     r0, [r6, #O_T_STAGE]


    movw    r4, #:lower16:T_FOPEN
    movt    r4, #:upper16:T_FOPEN
    ldr     r5, [r4]
    cmp     r5, #0
    beq     9f
#ifdef DRY_RUN
    mov     r0, #0
    str     r0, [r4]
    mov     r0, #0x25
    str     r0, [r6, #O_T_STAGE]
    pop     {r4, r5, r6, lr}
    bx      lr
#endif

#ifndef FPGYRO_EDITION_BASE
    /* Neither of these is base's.  It holds no row -- there is no formatting
     * to hold one back from -- and it has no note to rewrite: the drop count
     * lived in the gcsv header's text, and base's twenty bytes carry only what
     * is needed to READ the file.  Integrity tracking is hdmi-raw's. */
    /* Whatever row is still held.  Without this the last sample of every take
     * is the one that never arrives. */
    SHAREDAT    r5, O_G_TEXT
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
    SHAREDAT    r5, O_G_TEXT
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

#endif
3:  mov     r0, #0x24
    str     r0, [r6, #O_T_STAGE]
    movw    r5, #:lower16:T_FOBJ
    movt    r5, #:upper16:T_FOBJ
    ldr     r5, [r5]
    mov     r0, r5
    mov     r1, #2
    movw    ip, #:lower16:F_DTOR
    movt    ip, #:upper16:F_DTOR
    blx     ip
    mov     r0, #0x25
    str     r0, [r6, #O_T_STAGE]
    mov     r0, #0
    str     r0, [r4]

9:  pop     {r4, r5, r6, lr}
    bx      lr

/* ------------------------------------------------------------ the header */

#ifndef FPGYRO_EDITION_BASE
/* Base writes twenty binary bytes, so neither of these strings nor the row
 * formatter behind them is any use to it -- and a symbol it carries but never
 * calls is one the routine table would hand out. */

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
#endif

/* Both editions, even though only gcsv formats rows: gcsv_json.S reaches into
 * this file for dec_pairs_at and put_u32, and base writes a .json too.  The
 * formatter itself is dead weight in a base build and the pool has room for
 * it; splitting two helpers out to save that is a change with more ways to be
 * wrong than bytes to gain. */
#include "gcsv_rows.S"
#include "gcsv_json.S"
#include "gcsv_dist.S"
