/* The gcsv builder, moved out of the injection cave into the pool.
 *
 * The cave is under four kilobytes and was down to four bytes free. None of
 * this runs while a take is in progress -- it turns the .GYR that was just
 * closed into a Gyroflow log -- so it has no business sharing three thousand
 * bytes with a 2500 Hz callback.
 *
 * Position independent: internal calls are `bl`, everything else is an absolute
 * firmware address or an offset from r10, so it runs wherever it is placed.
 * Entered through a four instruction trampoline in the cave that reads the
 * address out of the state block; zero there means nothing was placed and no
 * gcsv is written, which is visible where branching through a zero would not.
 *
 * open_file and close_file are copied rather than called across: the cave's
 * copies move every time the logger is rebuilt.
 */
    .syntax unified
    .arm

.macro ldr_addr reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

.equ POOL_PTR,        0xC3757A7C
.equ O_STATE,         0x6000      /* r10 points here                        */
.equ O_PATH,          0x0100      /* from r10                               */
.equ O_HEADER,        0x0200
.equ O_FOBJ,          0x0400
.equ O_FOBJ2,         0x0800      /* the gcsv, open while the .GYR is read back */
.equ O_GCSV_PATH,     0x0180      /* its path, beside the .GYR's                */
.equ O_BUF_A,         0x1000
.equ O_BUF_B,         0x5000
.equ BUF_SIZE,        0x00004000
.equ BLOCK_HEADER,    32
.equ PAYLOAD_CAP,     0x00003FE0
.equ F_MGR,           0xC0444658
.equ F_VOL,           0xC0444698
.equ F_CTOR,          0xC0365E90
.equ F_OPEN,          0xC0365FB0
.equ F_READ,          0xC0366060
.equ F_WRITE,         0xC03660E8
.equ F_CLOSE,         0xC0366020
.equ F_DTOR,          0xC0365ED0
.equ ACCEL_CACHE,     0xC377790C  /* i16 X, Y, Z, axis-remapped by the firmware */
.equ ACCEL_REC,       12          /* u32 us, i16 x, i16 y, i16 z, i16 pad       */
.equ ACCEL_ZONE,      0x0400      /* the accel records grow in their own end of  */
.equ ACCEL_BASE,      0x3C00      /* the buffer: BUF_SIZE - ACCEL_ZONE           */
.equ GYRO_CAP,        0x3BE0      /* ACCEL_BASE - BLOCK_HEADER                   */
.equ O_TEXT,          0x1A000     /* pool+0x20000: the gcsv's text, at the stop.
                                     It used to borrow O_BUF_B, which is sixteen
                                     kilobytes, so the text went to the card every
                                     fifteen -- forty writes for one take, landing
                                     while the camera finalises its own clip. The
                                     recording is over by then and the pool has
                                     896 KB nobody uses, verified across a
                                     recording 224 markers out of 224.          */
.equ TEXT_FLUSH,      0x4000      /* 16 KiB. It was 256, to make three writes of
                                     what had been forty -- but each of those
                                     three held the volume for as long as it took
                                     to put a quarter megabyte on the card, and
                                     the camera's own file task cannot preempt a
                                     mutex. Short holds beat few holds when
                                     something at priority 6 is waiting.        */
.equ ACC_VARS,        0x10000     /* pool: +0 ptr, +4 left, +8 x, +12 y, +16 z.
                                   * From r10, not PC-relative: the routines
                                   * that touch these are more than an `adr`
                                   * apart in the blob.
                                   *
                                   * In the middle of the gap between the block
                                   * buffers (which end at 0x9000) and O_TEXT
                                   * (0x1A000). Two earlier spots came back as
                                   * garbage: 0x19C00 is inside pgenload's file
                                   * object, which is bigger than the kilobyte
                                   * assumed for it, and 0x9000 is the block
                                   * buffers' own boundary.                   */
.equ O_READ,          0x5B000     /* pool+0x61000, past the text buffer         */
.equ READ_SIZE,       0x10000     /* 64 KiB, for the same reason as TEXT_FLUSH   */
.equ O_PROFILE,       0x9000      /* the gap between the block buffers and the
                                   * gcsv's text: 68 KiB, which is where the
                                   * whole \LENS.DAT goes -- one Gyroflow profile
                                   * per sensor mode the camera can record in.
                                   * A single profile would have to be told which
                                   * mode to expect, and would quietly write
                                   * nothing on any other. The table cannot.   */
.equ PROFILE_MAX,     0x10000      /* what tableload.S reads in, so a directory
                                   * entry past it is refused rather than read */
.equ PROFILE_MAGIC,   0x5441444C  /* "LDAT", the same file lensdat.py leaves on
                                   * the card: header, directory, then the text */
.equ PROFILE_DIR,     48          /* the directory follows the header           */
.equ O_END,           0xF000      /* the logger owns r10-0x6000 .. +0xF000 */
.equ HOOK_SITE,       0xC00D0794  /* where the callback branches here from     */
.equ HOOK_ORIG,       0xFA046FD7  /* the instruction it replaced               */
.equ PATH_MGR_SD,     0xC3438400
.equ GYRO_DESC_PTR,   0xC31E3FCC
.equ S_THREAD,        0x00
.equ S_ACTIVE,        0x04
.equ S_FILE,          0x08  /* 0 closed, 1 open request, 2 open, 3 close request */
.equ S_INDEX,         0x0C
.equ S_HEAD,          0x10
.equ S_DROPPED,       0x14
.equ S_NEXTSEQ,       0x18
.equ S_ERROR,         0x1C
.equ S_A_STATE,       0x20  /* 0 empty, 1 filling, 2 ready, 3 writing */
.equ S_A_FIRST,       0x28
.equ S_A_LAST,        0x2C
.equ S_A_SEQ,         0x30
.equ S_A_FLAGS,       0x34
.equ S_A_GYRO,        0x38        /* gyro bytes alone; count must not include accel */
.equ S_A_ACC,         0x3C        /* accel record COUNT, in the zone at the end     */
.equ S_B_STATE,       0x40
.equ S_B_FIRST,       0x48
.equ S_B_LAST,        0x4C
.equ S_B_SEQ,         0x50
.equ S_B_FLAGS,       0x54
.equ S_B_GYRO,        0x58
.equ S_B_ACC,         0x5C
.equ S_STOP,          0x60
.equ S_MAGIC,         0x64        /* 'S6G6' once the block has been initialised */
.equ S_LIMIT,         0x68        /* one past the end of the buffer being filled */
.equ S_CLAMPED,       0x6C        /* bytes copy_span refused to write past it   */
.equ S_STOP_T0,       0x70        /* TickTimer when the stop was noticed        */
.equ S_STOP_T1,       0x74        /* TickTimer when the file was closed         */
.equ S_STOP_BLOCKS,   0x78        /* blocks still to write when the stop landed */
.equ S_PARK,          0x7C        /* host asks the writer to step out of the cave */
.equ S_PARKED,        0x80        /* writer confirms it is parked                 */
.equ S_WRITER_PC,     0x84
.equ S_START_US,      0x88        /* the header buffer is reused for the footer */
.equ S_RD_END,        0x90        /* end of the valid data in the read buffer   */
.equ S_RD_EOF,        0x94
.equ S_GEOM_W,        0x98        /* the recording geometry, read at record start */
.equ S_GEOM_H,        0x9C
.equ S_MODE_LATE,     0xA0        /* the mode, re-read once recording is going  */
.equ S_MODE_N,        0xA4        /* entries used in the mode history below       */
.equ S_DELAY,         0xF4        /* polls to wait before touching the card   */
.equ S_JSON_FN,       0xF0        /* the profile generator, in the pool       */
.equ S_JSON_WANT,     0xAC        /* the profile is owed, and will be written on
                                   * an idle poll rather than at the stop      */
.equ S_MODE_RUN,      0xA8        /* the mode while the file was open and no stop
                                   * pending -- the take's own mode, where the
                                   * last sample of all lands after the stop with
                                   * the camera already back in live view        */
.equ S_MODE_HIST,     0xB0        /* 8 x {TickTimer, mode}; ends at 0xF0, and the
                                   * state block has to stay under O_PATH = 0x100 */
.equ MODE_OBJ,        0xC343B588  /* FUN_c0322e88() returns this; verified live.
                                   * +4 is the mode now, +8 the one before it --
                                   * the pair the firmware's own --mode_change--
                                   * trace prints in ImagerMode.cpp. Reading the
                                   * words directly skips the lazy-singleton
                                   * getter, so this is two loads and safe to do
                                   * on the writer's 5 ms poll. */
.equ F_MODE_NOW,      0xC032C720  /* () -> the current sensor mode enum         */
.equ GEOMETRY,        0xC37CE210  /* {width, height, frame bytes} while recording */        /* the .GYR has nothing more to give          */
.equ S_READ_N,        0x8C        /* where read() drops its byte count          */        /* where to resume once the body is replaced    */
.equ PARK_STUB,       0xC072EFB4  /* as high as it fits: the payload grew into the
                                   * old 0xC072EF00, and code that overwrites the
                                   * stub while the writer is parked in it is a
                                   * freeze. Moving it needs two loads -- one that
                                   * still ends below the old address, then the
                                   * real one. See templates/park.S              */


/* Close a file and destroy its object: r0 = the object's offset from r10.
 * The other half of open_file, and copied just as often. */
close_file:
    push    {r4, lr}
    mov     r4, r0
    add     r0, r10, r4
    ldr_addr     ip, F_CLOSE
    blx     ip
    add     r0, r10, r4
    mov     r1, #2
    ldr_addr     ip, F_DTOR
    blx     ip
    pop     {r4, pc}

/* Open a file: r0 = the file object's offset from r10, r1 = the path, r2 = the
 * mode.  Returns what F_OPEN returned -- zero means it did not open.
 *
 * Three copies of the same six calls, and a fourth wanted for the profile.  The
 * cave is a fixed nine hundred and fifty words and the copies were most of what
 * was left of it; the sequence has never varied, so there was nothing to lose
 * by naming it. */
open_file:
    push    {r4, r5, r6, lr}
    mov     r4, r0
    mov     r5, r1
    mov     r6, r2
    ldr_addr     ip, F_MGR
    blx     ip
    mov     r1, #0
    ldr_addr     ip, F_VOL
    blx     ip
    mov     r1, r0
    add     r0, r10, r4
    ldr_addr     ip, F_CTOR
    blx     ip
    add     r0, r10, r4
    mov     r1, r5
    mov     r2, r6
    ldr_addr     ip, F_OPEN
    blx     ip
    cmp     r0, #0
    popne   {r4, r5, r6, pc}
    /* It did not open -- but F_CTOR above built the object, and every caller
     * used to branch away and leave it built. A file object that is never
     * destroyed wedges the file system: that is what happened to \LENS.DAT,
     * which could not be opened again by anything until the camera was power
     * cycled, with the card light on. Opens rarely fail, and the damage does
     * not heal, which is exactly the shape of a freeze that only sometimes
     * happens. Destroying it here fixes all four callers at once. */
    add     r0, r10, r4
    mov     r1, #2
    ldr_addr     ip, F_DTOR
    blx     ip
    mov     r0, #0
    pop     {r4, r5, r6, pc}



/* ==========================================================================
 * put_int — r0 signed value, r1 destination.  Returns the destination advanced.
 *
 * No hardware divide on this core, and repeated subtraction on a fifteen-million
 * microsecond timestamp is not a plan, so the divide by ten is the usual
 * reciprocal multiply: n/10 = (n * 0xCCCCCCCD) >> 35.
 * ========================================================================== */
put_int:
    push    {r4, r5, r6, r7, r8, lr}
    mov     r4, r1
    mov     r5, r0
    cmp     r5, #0
    bge     30f
    mov     r6, #'-'
    strb    r6, [r4], #1
    rsb     r5, r5, #0
30:
    sub     sp, sp, #16
    mov     r8, sp
    mov     r6, #0
31:
    movw    r0, #0xCCCD
    movt    r0, #0xCCCC
    umull   r1, r0, r5, r0
    lsr     r0, r0, #3                  @ r0 = r5 / 10
    add     r1, r0, r0, lsl #2
    sub     r1, r5, r1, lsl #1          @ r5 - 10*(r5/10)
    add     r1, r1, #'0'
    strb    r1, [r8, r6]
    add     r6, r6, #1
    mov     r5, r0
    cmp     r5, #0
    bne     31b
32:
    subs    r6, r6, #1
    blt     33f
    ldrb    r1, [r8, r6]
    strb    r1, [r4], #1
    b       32b
33:
    add     sp, sp, #16
    mov     r0, r4
    pop     {r4, r5, r6, r7, r8, pc}

/* r0 = source (NUL-terminated), r1 = destination.  Returns it advanced. */
put_str:
    push    {r4, lr}
34: ldrb    r4, [r0], #1
    cmp     r4, #0
    beq     35f
    strb    r4, [r1], #1
    b       34b
35: mov     r0, r1
    pop     {r4, pc}


/* Sits here rather than with the other literals at the end: the routine that
 * reaches it does so with `adr`, and the file outgrew that instruction's
 * range. What precedes this returns, so nothing falls into it. */
gcsv_dir:
    .ascii  "\\CINEMA\\"
    .align  2

/* ==========================================================================
 * gcsv_build — turn the .GYR just written into a Gyroflow .GCSV beside it.
 *
 * Runs in the writer thread, after the .GYR is closed, with both halves free.
 * The samples are long gone from memory by then -- that is what streaming means
 * -- so the file is read back a block at a time rather than held.
 *
 * This is deliberately not on the gyro callback. The earlier logger built its
 * text there and blocked it for the better part of a second, which is how it
 * missed the next take's start: the callback cannot see ACTIVE go 0 to 1 while
 * it is inside itself. Here the callback sets a flag and returns in microseconds.
 *
 * gscale and the orientation are literals rather than formatted: they are
 * compile-time constants, and formatting a float in ARM to match what the host
 * decoder writes is a lot of code for a string that never changes.
 * ========================================================================== */
gcsv_build:
    push    {r3, r4, r5, r6, r7, r8, r9, r10, r11, lr}

    /* \A001_018.GYR -> \CINEMA\A001_018\A001_018.gcsv.
     *
     * Beside the frames, not at the root of the card: three files with the
     * clip's name in a folder of nine hundred DNGs is where someone looks for
     * them. The .GYR stays at the root -- it is written while the camera is
     * filling that same folder, and adding our directory updates to that is the
     * one moment worth not touching.
     *
     *   0        \
     *   1..7     CINEMA\
     *   8..15    the clip name
     *   16       \
     *   17..24   the clip name again
     *   25       .
     *   26..29   gcsv, which json_build overwrites with json -- same length
     *   30       the terminator */
    add     r1, r10, #O_GCSV_PATH
    adr     r0, gcsv_dir
    ldm     r0, {r2, r3}
    stm     r1, {r2, r3}
    add     r0, r10, #O_PATH
    add     r0, r0, #6                  @ past "\\GYRO\\"
    add     r2, r1, #8
    add     r3, r1, #17
    mov     ip, #8
40: ldrb    r4, [r0], #1
    strb    r4, [r2], #1
    strb    r4, [r3], #1
    subs    ip, ip, #1
    bne     40b
    mov     r4, #92
    strb    r4, [r1, #16]
    mov     r4, #'.'
    strb    r4, [r1, #25]
    movw    r4, #0x6367              @ 'g' then 'c'
    strh    r4, [r1, #26]
    movw    r4, #0x7673              @ 's' then 'v'
    strh    r4, [r1, #28]
    mov     r4, #0
    strb    r4, [r1, #30]

    /* The .GYR, for reading. */
    mov     r0, #O_FOBJ
    add     r1, r10, #O_PATH
    mov     r2, #1
    bl      open_file
    cmp     r0, #0
    beq     gcsv_out

    /* The .CSV, for writing. */
    mov     r0, #O_FOBJ2
    add     r1, r10, #O_GCSV_PATH
    mov     r2, #7
    bl      open_file
    cmp     r0, #0
    beq     gcsv_close_gyr

    /* Header, with the clip name lifted out of the path. */
    movw    r6, #:lower16:O_TEXT
    movt    r6, #:upper16:O_TEXT
    add     r6, r10, r6
    mov     r5, r6
    adr     r0, gcsv_head1
    mov     r1, r5
    bl      put_str
    mov     r5, r0
    add     r0, r10, #O_PATH
    add     r0, r0, #6                  @ past "\\GYRO\\"
    mov     r1, r5
41: ldrb    r2, [r0], #1
    cmp     r2, #'.'
    beq     42f
    cmp     r2, #0
    beq     42f
    strb    r2, [r1], #1
    b       41b
42: mov     r5, r1
    adr     r0, gcsv_head2
    mov     r1, r5
    bl      put_str
    mov     r5, r0

    /* Skip the file header. */
    add     r0, r10, #O_FOBJ
    add     r1, r10, #O_BUF_A
    mov     r2, #160
    add     r3, r10, #S_READ_N
    ldr_addr     ip, F_READ
    blx     ip

    ldr     r11, [r10, #S_START_US]     @ not the header: writer_close put the
                                        @ GFE6 footer there before this ran, and
                                        @ every timestamp came out negative

    add     r0, r10, #O_READ
    mov     r4, r0
    str     r0, [r10, #S_RD_END]        @ nothing buffered yet
    mov     r0, #0
    str     r0, [r10, #S_RD_EOF]
    b       gcsv_refill

/* --- slide the partial block to the front, top the buffer up -------------- */
gcsv_refill:
    /* The old path read a 32-byte header and then the payload, per block: two
     * card operations for every 766 ms of take. Measured at 29 ms each -- one
     * second of stop path for a 26 s clip, and twenty-three seconds for ten
     * minutes. The card is not the reason: the camera loads a 31 MB DNG into
     * memory in 0.17 s, at 183 MB/s. It was being asked for sixteen kilobytes
     * at a time.
     *
     * 624 KiB a go instead. A block can straddle the end of a read, so whatever
     * is left over slides to the front and the next read lands behind it --
     * which is how this avoids needing seek, whose semantics here are unknown. */
    add     r7, r10, #O_READ
    ldr     r8, [r10, #S_RD_END]
    subs    r8, r8, r4                  @ leftover bytes
    movlo   r8, #0
    cmp     r4, r7
    beq     41f                         @ already at the front
    mov     r9, #0
40: cmp     r9, r8
    bhs     41f
    ldrb    r0, [r4, r9]
    strb    r0, [r7, r9]
    add     r9, r9, #1
    b       40b
41:
    ldr     r0, [r10, #S_RD_EOF]
    cmp     r0, #0
    bne     42f
    mov     r0, #0                      @ a failed read may leave this stale, and
    str     r0, [r10, #S_READ_N]        @ a stale count is a buffer of old bytes
    add     r0, r10, #O_FOBJ
    add     r1, r7, r8
    movw    r2, #:lower16:READ_SIZE
    movt    r2, #:upper16:READ_SIZE
    sub     r2, r2, r8                  @ room behind the leftover
    add     r3, r10, #S_READ_N
    ldr_addr     ip, F_READ
    blx     ip
    mov     r0, #5                      @ and give the card back between reads,
    movw    ip, #0x05D8                 @ for the same reason as the writes
    movt    ip, #0xC037
    blx     ip
    ldr     r0, [r10, #S_READ_N]
    cmp     r0, #0
    moveq   r1, #1
    streq   r1, [r10, #S_RD_EOF]        @ short read: that was the last of it
    add     r8, r8, r0
42:
    mov     r4, r7
    add     r0, r7, r8
    str     r0, [r10, #S_RD_END]

gcsv_block:
    ldr     r0, [r10, #S_RD_END]
    sub     r0, r0, r4                  @ bytes available at r4
    cmp     r0, #BLOCK_HEADER
    blo     43f
    ldr     r1, [r4]
    movw    r2, #0x4647
    movt    r2, #0x3642                 @ GFB6
    cmp     r1, r2
    bne     gcsv_flush_last             @ not a block: stop here
    ldr     r2, [r4, #24]               @ payload bytes
    add     r2, r2, #BLOCK_HEADER
    cmp     r0, r2
    bhs     44f                         @ the whole block is in the buffer
43: ldr     r0, [r10, #S_RD_EOF]
    cmp     r0, #0
    bne     gcsv_flush_last             @ a truncated tail, and no more file
    b       gcsv_refill
44:
    ldr     r8, [r4, #16]               @ gyro samples
    ldr     r9, [r4, #8]                @ first timestamp
    sub     r9, r9, r11                 @ relative to record start

    movw    r3, #:lower16:ACC_VARS
    movt    r3, #:upper16:ACC_VARS
    add     r3, r10, r3

    /* This block's records follow its gyro samples; the top half of flags
     * counts them, and each is twelve bytes -- absolute microseconds, then
     * x, y, z as halfwords with one of padding. */
    ldr     r1, [r4, #20]
    lsr     r1, r1, #16
    str     r1, [r3, #4]
    add     r0, r4, #BLOCK_HEADER
    add     r0, r0, r8, lsl #3
    str     r0, [r3]

    /* Seed from the first record of the take. Its timestamp is a little after
     * the first gyro sample, so the catch-up below would have nothing to accept
     * and the opening rows would carry zero gravity -- not a measurement, and
     * the fusion would have to recover from it. Keyed on the block sequence, so
     * nothing has to be reset between takes. */
    ldr     ip, [r4, #4]
    cmp     ip, #0
    bne     7f
    cmp     r1, #0
    beq     7f
    ldrsh   ip, [r0, #4]
    str     ip, [r3, #8]
    ldrsh   ip, [r0, #6]
    str     ip, [r3, #12]
    ldrsh   ip, [r0, #8]
    str     ip, [r3, #16]
7:
    add     r7, r4, #BLOCK_HEADER       @ the samples themselves
    add     r4, r4, r2                  @ and the next block

gcsv_sample:
    cmp     r8, #0
    beq     9f

    mov     r0, r9
    mov     r1, r5
    bl      put_int
    mov     r5, r0
    mov     r0, #','
    strb    r0, [r5], #1
    ldrsh   r0, [r7]
    mov     r1, r5
    bl      put_int
    mov     r5, r0
    mov     r0, #','
    strb    r0, [r5], #1
    ldrsh   r0, [r7, #2]
    mov     r1, r5
    bl      put_int
    mov     r5, r0
    mov     r0, #','
    strb    r0, [r5], #1
    ldrsh   r0, [r7, #6]                @ z sits past the pad
    mov     r1, r5
    bl      put_int
    mov     r5, r0
    mov     r0, #','
    strb    r0, [r5], #1

    movw    r3, #:lower16:ACC_VARS
    movt    r3, #:upper16:ACC_VARS
    add     r3, r10, r3

    /* Catch the accelerometer up to this sample, then hold. A hundred readings
     * a second against the gyro's 2500: one covers twenty-five rows. Held
     * rather than interpolated -- at that rate the error is small, and a
     * made-up reading is harder to argue with than a stale one when the horizon
     * comes out wrong. */
5:  ldr     r1, [r3, #4]
    cmp     r1, #0
    beq     6f
    ldr     r0, [r3]
    ldr     ip, [r0]
    sub     ip, ip, r11
    cmp     ip, r9
    bhi     6f
    ldrsh   ip, [r0, #4]
    str     ip, [r3, #8]
    ldrsh   ip, [r0, #6]
    str     ip, [r3, #12]
    ldrsh   ip, [r0, #8]
    str     ip, [r3, #16]
    add     r0, r0, #12
    str     r0, [r3]
    sub     r1, r1, #1
    str     r1, [r3, #4]
    b       5b
6:
    /* The accelerometer's axes are not the gyro's, and gcsv carries one
     * orientation for both -- so the rotation happens here. Verified on
     * A001_006: as the firmware hands them over, levelling the horizon needed a
     * roll of about -95 degrees; a quarter turn the other way puts gravity
     * where Gyroflow looks for it. */
    ldr     r0, [r3, #12]
    mov     r1, r5
    bl      put_int
    mov     r5, r0
    mov     r0, #','
    strb    r0, [r5], #1
    movw    r3, #:lower16:ACC_VARS
    movt    r3, #:upper16:ACC_VARS
    add     r3, r10, r3
    ldr     r0, [r3, #8]
    rsb     r0, r0, #0
    mov     r1, r5
    bl      put_int
    mov     r5, r0
    mov     r0, #','
    strb    r0, [r5], #1
    movw    r3, #:lower16:ACC_VARS
    movt    r3, #:upper16:ACC_VARS
    add     r3, r10, r3
    ldr     r0, [r3, #16]
    mov     r1, r5
    bl      put_int
    mov     r5, r0
    mov     r0, #10
    strb    r0, [r5], #1

    add     r7, r7, #8
    sub     r8, r8, #1
    movw    r0, #400
    add     r9, r9, r0

    /* Flush well before the end: one line is at most about forty bytes. */
    sub     r0, r5, r6
    movw    r1, #:lower16:TEXT_FLUSH
    movt    r1, #:upper16:TEXT_FLUSH
    cmp     r0, r1
    blo     gcsv_sample
    bl      gcsv_flush
    b       gcsv_sample

    /* This block's samples are done. Anything still in its accelerometer array
     * arrived after its last gyro sample, so it is older than the next block's
     * first one: take the last of them now, while the record is still in the
     * buffer. Doing it when the next block opens read through a pointer into
     * data the refill had already moved, and put a reading of 7593 -- four
     * times gravity -- into the file. */
9:
    movw    r3, #:lower16:ACC_VARS
    movt    r3, #:upper16:ACC_VARS
    add     r3, r10, r3
    ldr     r1, [r3, #4]
    cmp     r1, #0
    beq     gcsv_block
    ldr     ip, [r3]
    sub     r1, r1, #1
    add     ip, ip, r1, lsl #3
    add     ip, ip, r1, lsl #2          @ twelve bytes a record
    ldrsh   r1, [ip, #4]
    str     r1, [r3, #8]
    ldrsh   r1, [ip, #6]
    str     r1, [r3, #12]
    ldrsh   r1, [ip, #8]
    str     r1, [r3, #16]
    mov     r1, #0
    str     r1, [r3, #4]
    b       gcsv_block

gcsv_flush_last:
    bl      gcsv_flush
    mov     r0, #O_FOBJ2
    bl      close_file
gcsv_close_gyr:
    mov     r0, #O_FOBJ
    bl      close_file
gcsv_out:
    pop     {r3, r4, r5, r6, r7, r8, r9, r10, r11, pc}

/* Write out whatever is in the text buffer and rewind it. */
gcsv_flush:
    push    {r0, r1, r2, lr}
    sub     r2, r5, r6
    cmp     r2, #0
    beq     43f
    add     r0, r10, #O_FOBJ2
    mov     r1, r6
    ldr_addr     ip, F_WRITE
    blx     ip
    mov     r5, r6
    /* Yield between chunks.
     *
     * Bisection, 2026-08-29: no logger 7 takes clean; .GYR only 9 clean;
     * .GYR plus the profile 8 clean; with this function, the camera froze
     * roughly one take in four with its own SPP_metadata.xmp left empty. The
     * profile is nine hundred bytes and never froze anything. This reads a
     * quarter megabyte back and writes six hundred kilobytes, and doing that in
     * one uninterrupted run is what the camera cannot survive -- shortening
     * each call was not enough, because they still came back to back with
     * nothing else able to get a turn in between.
     *
     * Five milliseconds a chunk costs about a fifth of a second over the whole
     * file. Nothing is waiting for it. */
    mov     r0, #5
    movw    ip, #0x05D8
    movt    ip, #0xC037
    blx     ip
43: pop     {r0, r1, r2, pc}


gcsv_head1:
    .asciz  "GYROFLOW IMU LOG\nversion,1.3\nid,sigma_fp_v502_internal_icm20321\norientation,xyz\nfwversion,SIGMA fp 5.02\nvideofilename,"
    .align  2
gcsv_head2:
    .asciz  "\ntscale,0.000001\ngscale,0.000137923\nascale,0.0009765625\nt,gx,gy,gz,ax,ay,az\n"
    .align  2

