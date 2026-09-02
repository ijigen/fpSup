/* The gcsv builder, moved out of the injection cave into the pool.
 *
 * The cave is under four kilobytes and was down to four bytes free. None of
 * the shipping post-read formatter runs while a take is in progress.  The
 * GCSV-only experiment compiles the alternate command entry below: the same
 * writer task feeds it sealed RAM blocks, while the 2500 Hz callback continues
 * to do no formatting and no media calls.  Either build belongs in the pool;
 * neither belongs in the injection cave.
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
.equ O_POST_PATH,     0x0120
.equ O_POST_START,    0x0140
.equ O_POST_VOLUME,   0x0150      /* snapshotted from J_FLAGS[15:8] */
.equ O_LC_VOLUME,     0x0158      /* native recording volume, while streaming */
.equ O_STREAM_STATE,  0x01A0      /* bounded streaming state before O_HEADER */
.equ ST_OPEN,         0x00
.equ ST_TEXT_N,       0x04
.equ ST_ACC_X,        0x08
.equ ST_ACC_Y,        0x0C
.equ ST_ACC_Z,        0x10
.equ ST_IO_RESULT,    0x14
.equ ST_ACC_TEXT_N,   0x18        /* cached "ax,ay,az" byte count */
.equ ST_ACC_TEXT,     0x1C        /* 24 bytes; worst case needs 19 */
.equ ST_ACC_DIRTY,    0x34        /* raw accel changed since text was built */
.equ ST_NEXT_EXPECT,  0x3C        /* take-relative time the next row should carry if
                                     the stream is continuous; 0 = first block.  Lives
                                     in the dormant third slot record's unused +4 word
                                     (0x1DC): two-slot only, never S_C_STATE at 0x1D8. */
.equ ST_PREV_DROPPED, 0x40        /* S_DROPPED as of the previous block (0x1E0, dormant
                                     S_C_FIRST in two-slot).  Unchanged = the grid is
                                     continuous, whatever the anchor's latency.         */
.equ O_HEADER,        0x0200
.equ O_FOBJ,          0x0400
.equ O_FOBJ2,         0x0800      /* the gcsv, open while the .GYR is read back */
.equ O_GCSV_PATH,     0x0180      /* its path, beside the .GYR's                */
#ifdef FPGYRO_GCSV_STREAM
.equ O_BUF_A,         0x1000
.equ O_BUF_B,         0x30000
.equ O_BUF_C,         0x38000
.equ BUF_SIZE,        0x00008000
.equ PAYLOAD_CAP,     0x00007FE0
.equ GYRO_SAMPLE_CAP, 0x00000EFC
.equ ACCEL_REC_CAP,   170
#else
.equ O_BUF_A,         0x1000
.equ O_BUF_B,         0x5000
.equ BUF_SIZE,        0x00004000
.equ PAYLOAD_CAP,     0x00003FE0
.equ GYRO_SAMPLE_CAP, 0x0000077C
.equ ACCEL_REC_CAP,   85
#endif
.equ BLOCK_HEADER,    32
.equ F_MGR,           0xC0444658
.equ F_VOL,           0xC0444698
.equ F_CTOR,          0xC0365E90
.equ F_OPEN,          0xC0365FB0
.equ F_READ,          0xC0366060
.equ F_WRITE,         0xC03660E8
.equ F_CLOSE,         0xC0366020
.equ F_DTOR,          0xC0365ED0
.equ F_SEEK,          0xC03661E0
.equ ACCEL_CACHE,     0xC377790C  /* i16 X, Y, Z, axis-remapped by the firmware */
.equ ACCEL_REC,       12          /* u32 us, i16 x, i16 y, i16 z, i16 pad       */
#ifdef FPGYRO_GCSV_STREAM
.equ ACCEL_ZONE,      0x0800      /* twice the duration needs twice the records */
.equ ACCEL_BASE,      0x7800      /* 32 KiB buffer - ACCEL_ZONE                  */
.equ GYRO_CAP,        0x77E0      /* ACCEL_BASE - BLOCK_HEADER                   */
#else
.equ ACCEL_ZONE,      0x0400      /* the accel records grow in their own end of */
.equ ACCEL_BASE,      0x3C00      /* 16 KiB buffer - ACCEL_ZONE                  */
.equ GYRO_CAP,        0x3BE0      /* ACCEL_BASE - BLOCK_HEADER                   */
#endif
.equ O_TEXT,          0x1A000     /* pool+0x20000: the gcsv's text, at the stop.
                                     It used to borrow O_BUF_B, which is sixteen
                                     kilobytes, so the text went to the card every
                                     fifteen -- forty writes for one take, landing
                                     while the camera finalises its own clip. The
                                     recording is over by then and the pool has
                                     896 KB nobody uses, verified across a
                                     recording 224 markers out of 224.          */
#ifdef FPGYRO_GCSV_STREAM
.equ TEXT_FLUSH,      0x10000     /* r28: shorten the recording-time filesystem
                                     hold. r15's older formatter could not keep
                                     up at this call rate; r23 removed its three
                                     signed divisions and the three-slot queue
                                     now measures that trade-off directly.       */
#else
.equ TEXT_FLUSH,      0x10000     /* Keep the non-streaming post-read converter
                                     unchanged; it runs after recording.         */
#endif
.equ ACC_VARS,        0x10000     /* pool: +0 ptr, +4 left, +8 x, +12 y, +16 z.
                                   * From r10, not PC-relative: the routines
                                   * that touch these are more than an `adr`
                                   * apart in the blob.
                                   *
                                   * In the middle of the gap between the block
                                   * shipping buffers / streaming A and O_TEXT
                                   * (0x1A000). Two earlier spots came back as
                                   * garbage: 0x19C00 is inside pgenload's file
                                   * object, which is bigger than the kilobyte
                                   * assumed for it, and 0x9000 is the block
                                   * buffers' own boundary.                   */
.equ O_READ,          0x5B000     /* pool+0x61000, past the text buffer         */
.equ O_BP_DIAG,       0x40000     /* r24 RAM-only back-pressure counters       */
.equ BP_PHASE,        0x00
.equ BP_FLUSH_CUR,    0x04
.equ BP_FLUSH_TOTAL,  0x08
.equ BP_BLOCKS,       0x0C
.equ BP_BLOCKS_3,     0x10
.equ BP_DROP_FORMAT,  0x14
.equ BP_DROP_WRITE,   0x18
.equ BP_DROP_SLEEP,   0x1C
.equ BP_DROP_OTHER,   0x20
.equ READ_SIZE,       0x10000     /* 64 KiB, for the same reason as TEXT_FLUSH   */
.equ O_PROFILE,       0x9000      /* after the shipping blocks / streaming A;
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
.equ O_END,           0xF000      /* end of the injection-adjacent legacy region */
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
.equ S_POST_BUSY,     0xA0        /* 1 running, 2 cancelled by a new take       */
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
#ifdef FPGYRO_GCSV_STREAM
    /* The streaming entry runs while S_FILE is OPEN and S_POST_BUSY is zero.
     * Use the volume latched by the native lifecycle instead of the later
     * queue snapshot.  This is the same explicit-volume constructor used by
     * logger.S, so an unplugged SSD never spills a sidecar onto SD. */
    ldr     r1, [r10, #O_LC_VOLUME]
    cmp     r1, #1
    beq     gcsv_open_volume_ok
    cmp     r1, #5
    bne     gcsv_open_no_volume
#elif defined(FPGYRO_NATIVE_LIFECYCLE)
    ldr     r0, [r10, #S_POST_BUSY]
    cmp     r0, #1
    bne     gcsv_open_no_volume
    ldr     r1, [r10, #O_POST_VOLUME]
    cmp     r1, #1
    beq     gcsv_open_volume_ok
    cmp     r1, #5
    bne     gcsv_open_no_volume
#else
    ldr_addr     ip, F_MGR
    blx     ip
    mov     r1, #0
    ldr_addr     ip, F_VOL
    blx     ip
    mov     r1, r0
#endif
gcsv_open_volume_ok:
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
#if defined(FPGYRO_NATIVE_LIFECYCLE) || defined(FPGYRO_GCSV_STREAM)
gcsv_open_no_volume:
    mov     r0, #0
    pop     {r4, r5, r6, pc}
#endif



/* ==========================================================================
 * Decimal formatters.
 *
 * This core has no hardware divide.  Dividing by a power of two would be one
 * shift, but decimal needs an exact reciprocal multiply:
 *
 *     n / 100 = (n * 0x51EB851F) >> 37
 *
 * Two digits at a time halves the long timestamp's loop count.  Sensor values
 * are different: all of them are bounded signed 16-bit values, so a 40 KiB
 * table of 0000..9999 removes the reciprocal multiply altogether.  The table
 * fits in the PGEN loader's otherwise-unused 64 KiB code window; it does not
 * consume the recording buffers or grow with recording duration.
 *
 * put_gyro3 keeps the table address across X/Y/Z and emits their trailing
 * commas in one call.  put_i16 remains as the same lookup path for the low-rate
 * accelerometer refresh and the non-streaming converter.
 * The old generic formatter pushed six registers, allocated a reverse buffer
 * and rebuilt the /10 constant once for every digit -- about 620,000 heavy
 * calls for the sensor columns of a forty-second take.
 *
 * Timestamps have their own unsigned entry.  The previous signed entry emitted
 * a minus sign after 0x7fffffff us (35:47.483648), even though a one-hour GCSV
 * timestamp is a valid u32.
 * ========================================================================== */

/* r0 = unsigned u32, r1 = destination.  Returns the destination advanced. */
put_uint:
    cmp     r0, #10
    bhs     put_uint_two
    add     r2, r0, #'0'
    strb    r2, [r1]
    add     r0, r1, #1
    bx      lr
put_uint_two:
    cmp     r0, #100
    bhs     put_uint_many
    adr     ip, dec_pairs
    add     ip, ip, r0, lsl #1
    ldrh    r2, [ip]
    strh    r2, [r1]
    add     r0, r1, #2
    bx      lr
put_uint_many:
    push    {r4, r5, r6, r7, r8}
    sub     sp, sp, #12                 @ at most four reversed digit pairs
    mov     r4, r1
    mov     r5, r0
    mov     r6, #0
    movw    r7, #0x851F
    movt    r7, #0x51EB                 @ exact unsigned /100 reciprocal
    adr     r8, dec_pairs
put_uint_pair_loop:
    umull   r0, r1, r5, r7
    lsr     r1, r1, #5                  @ quotient
    mov     ip, #100
    mls     r0, r1, ip, r5              @ remainder
    add     ip, r8, r0, lsl #1
    ldrh    r0, [ip]
    add     ip, sp, r6, lsl #1
    strh    r0, [ip]
    add     r6, r6, #1
    mov     r5, r1
    cmp     r5, #100
    bhs     put_uint_pair_loop
    cmp     r5, #10
    bhs     put_uint_first_pair
    add     r0, r5, #'0'
    strb    r0, [r4], #1
    b       put_uint_reverse
put_uint_first_pair:
    add     ip, r8, r5, lsl #1
    ldrh    r0, [ip]
    strh    r0, [r4], #2
put_uint_reverse:
    subs    r6, r6, #1
    blt     put_uint_done
    add     ip, sp, r6, lsl #1
    ldrh    r0, [ip]
    strh    r0, [r4], #2
    b       put_uint_reverse
put_uint_done:
    mov     r0, r4
    add     sp, sp, #12
    pop     {r4, r5, r6, r7, r8}
    bx      lr

/* r0 = gyro record, r1 = destination.  Emit offsets 0, 2, 6 with commas. */
put_gyro3:
    push    {r4, r5, r6, r7, r8, lr}
    mov     r4, r0
    mov     r5, r1
    adr     r6, dec_quads
    movw    r7, #10000
    mov     r8, #3

put_gyro3_axis:
    ldrsh   r0, [r4]
    cmp     r0, #0
    bge     put_gyro3_abs
    mov     ip, #'-'
    strb    ip, [r5], #1
    rsb     r0, r0, #0
put_gyro3_abs:
    cmp     r0, #10
    blo     put_gyro3_one
    cmp     r0, #100
    blo     put_gyro3_two
    movw    ip, #1000
    cmp     r0, ip
    blo     put_gyro3_three
    cmp     r0, r7
    blo     put_gyro3_four

    /* 10000..32768: the first digit is only 1, 2 or 3. */
    mov     r2, #'0'
put_gyro3_lead:
    add     r2, r2, #1
    sub     r0, r0, r7
    cmp     r0, r7
    bhs     put_gyro3_lead
    strb    r2, [r5], #1
put_gyro3_four:
    ldr     r1, [r6, r0, lsl #2]
    strb    r1, [r5], #1
    lsr     ip, r1, #8
    strb    ip, [r5], #1
    lsr     ip, r1, #16
    strb    ip, [r5], #1
    lsr     ip, r1, #24
    strb    ip, [r5], #1
    b       put_gyro3_axis_done
put_gyro3_three:
    ldr     r1, [r6, r0, lsl #2]
    lsr     r1, r1, #8
    strb    r1, [r5], #1
    lsr     ip, r1, #8
    strb    ip, [r5], #1
    lsr     ip, r1, #16
    strb    ip, [r5], #1
    b       put_gyro3_axis_done
put_gyro3_two:
    ldr     r1, [r6, r0, lsl #2]
    lsr     r1, r1, #16
    strb    r1, [r5], #1
    lsr     ip, r1, #8
    strb    ip, [r5], #1
    b       put_gyro3_axis_done
put_gyro3_one:
    add     r1, r0, #'0'
    strb    r1, [r5], #1
put_gyro3_axis_done:
    mov     ip, #','
    strb    ip, [r5], #1
    subs    r8, r8, #1
    beq     put_gyro3_done
    add     r4, r4, #2
    cmp     r8, #1
    addeq   r4, r4, #2                 @ skip the pad before native Z
    b       put_gyro3_axis
put_gyro3_done:
    mov     r0, r5
    pop     {r4, r5, r6, r7, r8, pc}

/* r0 = signed sensor value in [-32768, 32768], r1 = destination. */
put_i16:
    cmp     r0, #0
    bge     put_i16_abs
    mov     ip, #'-'
    strb    ip, [r1], #1
    rsb     r0, r0, #0
put_i16_abs:
    cmp     r0, #10
    blo     put_i16_one
    cmp     r0, #100
    blo     put_i16_two
    movw    ip, #1000
    cmp     r0, ip
    blo     put_i16_three
    movw    r3, #10000
    cmp     r0, r3
    blo     put_i16_four

    mov     r2, #'0'
put_i16_lead:
    add     r2, r2, #1
    sub     r0, r0, r3
    cmp     r0, r3
    bhs     put_i16_lead
    strb    r2, [r1], #1
put_i16_four:
    adr     r3, dec_quads
    ldr     r2, [r3, r0, lsl #2]
    strb    r2, [r1], #1
    lsr     ip, r2, #8
    strb    ip, [r1], #1
    lsr     ip, r2, #16
    strb    ip, [r1], #1
    lsr     ip, r2, #24
    strb    ip, [r1], #1
    mov     r0, r1
    bx      lr
put_i16_three:
    adr     r3, dec_quads
    ldr     r2, [r3, r0, lsl #2]
    lsr     r2, r2, #8
    strb    r2, [r1], #1
    lsr     ip, r2, #8
    strb    ip, [r1], #1
    lsr     ip, r2, #16
    strb    ip, [r1], #1
    mov     r0, r1
    bx      lr
put_i16_two:
    adr     r3, dec_quads
    ldr     r2, [r3, r0, lsl #2]
    lsr     r2, r2, #16
    strb    r2, [r1], #1
    lsr     ip, r2, #8
    strb    ip, [r1], #1
    mov     r0, r1
    bx      lr
put_i16_one:
    add     r2, r0, #'0'
    strb    r2, [r1], #1
    mov     r0, r1
    bx      lr

/* Little-endian halfwords copy each decimal pair directly into the text. */
dec_pairs:
    .ascii  "0001020304050607080910111213141516171819"
    .ascii  "2021222324252627282930313233343536373839"
    .ascii  "4041424344454647484950515253545556575859"
    .ascii  "6061626364656667686970717273747576777879"
    .ascii  "8081828384858687888990919293949596979899"
    .balign 4

/* Four zero-padded ASCII digits per aligned word.  The assembler generates
 * this at build time, so the source and PGEN package do not need a separate
 * asset whose version could drift. */
dec_quads:
    .set    dec_quad_value, 0
    .rept   10000
    .byte   '0' + ((dec_quad_value / 1000) % 10)
    .byte   '0' + ((dec_quad_value / 100) % 10)
    .byte   '0' + ((dec_quad_value / 10) % 10)
    .byte   '0' + (dec_quad_value % 10)
    .set    dec_quad_value, dec_quad_value + 1
    .endr
    .balign 4

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
 * Runs in the writer thread, after the .GYR is closed, with all raw slots free.
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
#ifdef FPGYRO_GCSV_STREAM
/* Streaming command ABI, all in the existing writer task:
 *   r0=1  open this take's GCSV and stage its header
 *   r0=2, r1=one sealed logger block  format it into the bounded text buffer
 *   r0=3  flush and close normally
 *   r0=4  abort/close after a media failure
 *
 * The gyro callback still only copies raw samples into three fixed 32 KiB
 * slots in this build.
 * Formatting and every media call stay here, off the 2500 Hz callback.  No GYR
 * file is opened in this build: the block header is only a convenient in-RAM
 * contract between logger.S and this routine. */
gcsv_build:
    push    {r3, r4, r5, r6, r7, r8, r9, r10, r11, lr}
    cmp     r0, #1
    beq     gcsv_stream_open
    cmp     r0, #2
    beq     gcsv_stream_block
    cmp     r0, #3
    beq     gcsv_stream_close
    cmp     r0, #4
    beq     gcsv_stream_abort
    b       gcsv_stream_fail

gcsv_stream_open:
    add     r7, r10, #O_STREAM_STATE
    ldr     r0, [r7, #ST_OPEN]
    cmp     r0, #0
    bne     gcsv_stream_fail

    /* Build \CINEMA\A001_018\A001_018.gcsv from the lifecycle identity path.
     * The first DNG has established this directory before logger.S requests an
     * open, so no directory creation or take-number inference happens here. */
    add     r1, r10, #O_GCSV_PATH
    adr     r0, gcsv_dir
    ldm     r0, {r2, r3}
    stm     r1, {r2, r3}
    add     r0, r10, #O_PATH
    add     r0, r0, #6
    add     r2, r1, #8
    add     r3, r1, #17
    mov     ip, #8
gcsv_stream_path_id:
    ldrb    r4, [r0], #1
    strb    r4, [r2], #1
    strb    r4, [r3], #1
    subs    ip, ip, #1
    bne     gcsv_stream_path_id
    mov     r4, #92
    strb    r4, [r1, #16]
    mov     r4, #'.'
    strb    r4, [r1, #25]
    movw    r4, #0x6367                 @ "gc"
    strh    r4, [r1, #26]
    movw    r4, #0x7673                 @ "sv"
    strh    r4, [r1, #28]
    mov     r4, #0
    strb    r4, [r1, #30]

    mov     r0, #O_FOBJ
    add     r1, r10, #O_GCSV_PATH
    mov     r2, #7
    bl      open_file
    cmp     r0, #0
    beq     gcsv_stream_fail

    /* Keep the small header in RAM.  The first card write is a full 32 KiB
     * chunk after recording has settled, not a tiny directory-adjacent write
     * in CinemaDNG's start-up window. */
    movw    r6, #:lower16:O_TEXT
    movt    r6, #:upper16:O_TEXT
    add     r6, r10, r6
    mov     r5, r6
    bl      gcsv_get_head1
    mov     r1, r5
    bl      put_str
    mov     r5, r0
    add     r0, r10, #O_PATH
    add     r0, r0, #6
    mov     r1, r5
gcsv_stream_header_id:
    ldrb    r2, [r0], #1
    cmp     r2, #'.'
    beq     gcsv_stream_header_tail
    cmp     r2, #0
    beq     gcsv_stream_header_tail
    strb    r2, [r1], #1
    b       gcsv_stream_header_id
gcsv_stream_header_tail:
    mov     r5, r1
    bl      gcsv_get_head2
    mov     r1, r5
    bl      put_str
    mov     r5, r0
    sub     r0, r5, r6
    str     r0, [r7, #ST_TEXT_N]
    mov     r0, #0
    str     r0, [r7, #ST_ACC_X]
    str     r0, [r7, #ST_ACC_Y]
    str     r0, [r7, #ST_ACC_Z]
    mov     r0, #1
    str     r0, [r7, #ST_ACC_DIRTY]
    str     r0, [r7, #ST_NEXT_EXPECT]
    str     r0, [r7, #ST_PREV_DROPPED]
    bl      gcsv_stream_acc_refresh
    mov     r0, #1
    dmb     ish
    str     r0, [r7, #ST_OPEN]
    b       gcsv_stream_return

gcsv_stream_block:
    mov     r4, r1
    cmp     r4, #0
    beq     gcsv_stream_fail
    add     r0, r10, #O_STREAM_STATE
    ldr     r1, [r0, #ST_OPEN]
    cmp     r1, #1
    bne     gcsv_stream_fail
#ifdef FPGYRO_BACKPRESSURE_PROBE
    /* Keep phase accounting in pool-resident PGEN, not the already-full
     * injection cave.  Only the writer touches these words; the callback reads
     * BP_PHASE and owns the four drop counters. */
    movw    r3, #:lower16:O_BP_DIAG
    movt    r3, #:upper16:O_BP_DIAG
    add     r3, r10, r3
    mov     ip, #0
    str     ip, [r3, #BP_FLUSH_CUR]
    ldr     ip, [r3, #BP_BLOCKS]
    add     ip, ip, #1
    str     ip, [r3, #BP_BLOCKS]
    mov     ip, #1
    str     ip, [r3, #BP_PHASE]
    dmb     ish
#endif

    ldr     r8, [r4, #16]               @ gyro sample count
    movw    r0, #:lower16:GYRO_SAMPLE_CAP
    cmp     r8, r0
    bhi     gcsv_stream_fail
    ldr     r9, [r4, #8]
    ldr     r11, [r10, #S_START_US]
    sub     r9, r9, r11                  @ unsigned time since record start

    /* Seam continuity.  Each block's anchor comes from the callback's TickTimer
     * read, which trails the last sample by its own latency (0..1 ms), so block
     * seams jittered by up to ~0.5 ms and the timeline carried that latency.
     * The sensor is a strict 2500 Hz grid: when this block's first row lands
     * (no drop between the two seals, per the counts latched at seal time) near where it said the next row should be,
     * continue that grid.  A real drop is at least one whole batch (~20 ms) and
     * is left as the hole it is; S_DROPPED stays the authoritative count. */
    add     r2, r10, #O_STREAM_STATE
    ldr     r1, [r4, #28]                @ drops as of THIS block's seal (header CRC word)
    ldr     r3, [r2, #ST_PREV_DROPPED]
    str     r1, [r2, #ST_PREV_DROPPED]   @ previous block's seal count, for the next seam
    ldr     r0, [r2, #ST_NEXT_EXPECT]
    cmp     r0, #0
    beq     51f                          @ first block of the take: keep the anchor
    cmp     r1, r3
    bne     51f                          @ samples were dropped since the last block: a real hole
    cmp     r8, #2
    addhs   r1, r9, #200                 @ first row = pair midpoint ...
    movlo   r1, r9                       @ ... or a lone sample at the anchor
    sub     r3, r1, r0
    cmp     r3, #0
    rsblt   r3, r3, #0                   @ |first row - expected|
    cmp     r3, #0x10000                 @ sanity only (65 ms): the seal counts are exact,
    bhi     51f                          @ so this never decides a real seam
    sub     r9, r9, r1
    add     r9, r9, r0                   @ shift the anchor so the first row is exact
51:

    movw    r3, #:lower16:ACC_VARS
    movt    r3, #:upper16:ACC_VARS
    add     r3, r10, r3
    ldr     r1, [r4, #20]
    lsr     r1, r1, #16                  @ accelerometer record count
    cmp     r1, #ACCEL_REC_CAP
    bhi     gcsv_stream_fail
    mov     ip, r8, lsl #3
    add     r0, r1, r1, lsl #1
    add     ip, ip, r0, lsl #2
    ldr     r0, [r4, #24]
    cmp     ip, r0                       @ reject a torn/inconsistent RAM block
    bne     gcsv_stream_fail
    str     r1, [r3, #4]
    /* Streaming never packs the accelerometer zone down for a GYR write. */
    movw    r0, #:lower16:ACCEL_BASE
    add     r0, r4, r0
    str     r0, [r3]

    /* Convert each roughly 47 Hz accel timestamp to take-relative once.  r16
     * subtracted S_START_US again while the same held record was inspected by
     * about 53 successive gyro rows.  The block is ephemeral in this build, so
     * normalising its private accel zone in place is safe. */
    mov     r2, r1
gcsv_stream_acc_time_loop:
    cmp     r2, #0
    beq     gcsv_stream_acc_time_done
    ldr     ip, [r0]
    sub     ip, ip, r11
    str     ip, [r0], #ACCEL_REC
    subs    r2, r2, #1
    bne     gcsv_stream_acc_time_loop
gcsv_stream_acc_time_done:
    ldr     r0, [r3]                     @ restore the first accel record
    add     r11, r10, #O_STREAM_STATE    @ hot-loop state pointer

    /* Seed gravity from the first accelerometer record of the take. */
    ldr     ip, [r4, #4]
    cmp     ip, #0
    bne     gcsv_stream_seeded
    cmp     r1, #0
    beq     gcsv_stream_seeded
    ldrsh   ip, [r0, #4]
    mov     r2, r11
    str     ip, [r2, #ST_ACC_X]
    ldrsh   ip, [r0, #6]
    str     ip, [r2, #ST_ACC_Y]
    ldrsh   ip, [r0, #8]
    str     ip, [r2, #ST_ACC_Z]
    mov     ip, #1
    str     ip, [r2, #ST_ACC_DIRTY]
gcsv_stream_seeded:
    /* r4 no longer needs the sealed block.  Keep the accel cursor live across
     * the 2500 Hz loop instead of rebuilding its 20-bit pool address per row. */
    add     r7, r4, #BLOCK_HEADER
    mov     r4, r3
    movw    r6, #:lower16:O_TEXT
    movt    r6, #:upper16:O_TEXT
    add     r6, r10, r6
    add     r0, r10, #O_STREAM_STATE
    ldr     r5, [r0, #ST_TEXT_N]
    add     r5, r6, r5

gcsv_stream_sample:
    cmp     r8, #0
    beq     gcsv_stream_acc_tail

    /* 1250 Hz output: average two adjacent 2500 Hz samples per row.  This is a
     * two-tap anti-alias box filter, not decimation-by-drop: (s0+s1)>>1 halts
     * vibration above the new 625 Hz Nyquist before the rate is halved, so no
     * high-frequency energy folds back into Gyroflow's integration band.  The
     * native sample is x@0, y@2, pad@4, z@6 (put_gyro3's layout); the eight-byte
     * averaged sample is built on the stack and read the same way.  A lone final
     * sample (odd block count) is emitted un-averaged at its own timestamp. */
    sub     sp, sp, #8
    cmp     r8, #1
    beq     gcsv_stream_single
    ldrsh   r0, [r7]
    ldrsh   r1, [r7, #8]
    add     r0, r0, r1
    asr     r0, r0, #1
    strh    r0, [sp]
    ldrsh   r0, [r7, #2]
    ldrsh   r1, [r7, #10]
    add     r0, r0, r1
    asr     r0, r0, #1
    strh    r0, [sp, #2]
    ldrsh   r0, [r7, #6]
    ldrsh   r1, [r7, #14]
    add     r0, r0, r1
    asr     r0, r0, #1
    strh    r0, [sp, #6]
    add     r0, r9, #200                 @ midpoint timestamp of the averaged pair
    add     r1, r0, #800
    str     r1, [r11, #ST_NEXT_EXPECT]   @ next pair sits 800 us on
    b       gcsv_stream_emit
gcsv_stream_single:
    ldrsh   r0, [r7]
    strh    r0, [sp]
    ldrsh   r0, [r7, #2]
    strh    r0, [sp, #2]
    ldrsh   r0, [r7, #6]
    strh    r0, [sp, #6]
    mov     r0, r9
    add     r1, r0, #600
    str     r1, [r11, #ST_NEXT_EXPECT]   @ lone tail: next pair midpoint is 600 us on
gcsv_stream_emit:
    mov     r1, r5
    bl      put_uint
    mov     r5, r0
    mov     r0, #','
    strb    r0, [r5], #1
    mov     r0, sp
    mov     r1, r5
    bl      put_gyro3
    mov     r5, r0
    add     sp, sp, #8

    /* Consume accelerometer records up to this gyro timestamp, then hold. */
gcsv_stream_acc_catchup:
    ldr     r1, [r4, #4]
    cmp     r1, #0
    beq     gcsv_stream_acc_ready
    ldr     r0, [r4]
    ldr     ip, [r0]
    cmp     ip, r9
    bhi     gcsv_stream_acc_ready
    mov     r2, r11
    ldrsh   ip, [r0, #4]
    str     ip, [r2, #ST_ACC_X]
    ldrsh   ip, [r0, #6]
    str     ip, [r2, #ST_ACC_Y]
    ldrsh   ip, [r0, #8]
    str     ip, [r2, #ST_ACC_Z]
    mov     ip, #1
    str     ip, [r2, #ST_ACC_DIRTY]
    add     r0, r0, #ACCEL_REC
    str     r0, [r4]
    sub     r1, r1, #1
    str     r1, [r4, #4]
    b       gcsv_stream_acc_catchup

gcsv_stream_acc_ready:
    /* Sparse accelerometer.  Emit the three accel columns only on a row that
     * consumed a new ~47 Hz record (ST_ACC_DIRTY, set by the catchup above).
     * A row with no new sample ends after gz with NO trailing comma, which
     * Gyroflow reads as a gyro-only row.  It must not be "...,gz,," -- the empty
     * fields would parse as three zeroes.  Decimation already halved the rows;
     * this removes the accel text repeated across the ~25 rows between samples. */
    mov     r3, r11
    ldr     r0, [r3, #ST_ACC_DIRTY]
    cmp     r0, #0
    beq     gcsv_stream_acc_fourcol
    bl      gcsv_stream_acc_refresh

    /* New accel: put_gyro3 already left a comma after gz, so it is the separator
     * before the cached ax,ay,az fragment. */
    mov     r3, r11
    add     r1, r3, #ST_ACC_TEXT
    ldr     r2, [r3, #ST_ACC_TEXT_N]
    /* ST_ACC_TEXT is word-aligned, but the line destination need not be.  Read
     * four cached bytes at once and keep byte stores on the potentially
     * unaligned destination.  Only enter when all four bytes belong to the
     * fragment; the exact 0..3-byte tail stays bytewise. */
    cmp     r2, #4
    blo     gcsv_stream_acc_text_tail
gcsv_stream_acc_text_copy4:
    ldr     r0, [r1], #4
    strb    r0, [r5], #1
    lsr     ip, r0, #8
    strb    ip, [r5], #1
    lsr     ip, r0, #16
    strb    ip, [r5], #1
    lsr     ip, r0, #24
    strb    ip, [r5], #1
    sub     r2, r2, #4
    cmp     r2, #4
    bhs     gcsv_stream_acc_text_copy4
gcsv_stream_acc_text_tail:
    cmp     r2, #0
    beq     gcsv_stream_acc_newline
gcsv_stream_acc_text_copy1:
    ldrb    r0, [r1], #1
    strb    r0, [r5], #1
    subs    r2, r2, #1
    bne     gcsv_stream_acc_text_copy1
    b       gcsv_stream_acc_newline
gcsv_stream_acc_fourcol:
    sub     r5, r5, #1                   @ overwrite put_gyro3's trailing comma after gz
gcsv_stream_acc_newline:
    mov     r0, #10
    strb    r0, [r5], #1

    cmp     r8, #2                       @ same test the head used: pair vs lone tail
    blo     gcsv_stream_step_one
    add     r7, r7, #16
    sub     r8, r8, #2
    add     r9, r9, #800
    b       gcsv_stream_flushchk
gcsv_stream_step_one:
    add     r7, r7, #8
    sub     r8, r8, #1
    add     r9, r9, #400
gcsv_stream_flushchk:
    sub     r0, r5, r6
    cmp     r0, #TEXT_FLUSH
    blo     gcsv_stream_sample
    bl      gcsv_stream_flush
    cmp     r0, #0
    beq     gcsv_stream_fail
    b       gcsv_stream_sample

gcsv_stream_acc_tail:
    /* Preserve the final accelerometer value before the producer reuses this
     * half.  The next block then starts with a valid held value. */
    ldr     r1, [r4, #4]
    cmp     r1, #0
    beq     gcsv_stream_block_done
    ldr     ip, [r4]
    sub     r1, r1, #1
    add     ip, ip, r1, lsl #3
    add     ip, ip, r1, lsl #2
    mov     r2, r11
    ldrsh   r1, [ip, #4]
    str     r1, [r2, #ST_ACC_X]
    ldrsh   r1, [ip, #6]
    str     r1, [r2, #ST_ACC_Y]
    ldrsh   r1, [ip, #8]
    str     r1, [r2, #ST_ACC_Z]
    mov     r1, #1
    str     r1, [r2, #ST_ACC_DIRTY]
    mov     r1, #0
    str     r1, [r4, #4]
    b       gcsv_stream_block_done

/* Rebuild the held accelerometer columns only when a 47 Hz cache record moves.
 * The state has 96 bytes before O_HEADER; the worst signed triple occupies 19. */
gcsv_stream_acc_refresh:
    push    {r4, r5, r6, lr}
    add     r4, r10, #O_STREAM_STATE
    add     r5, r4, #ST_ACC_TEXT
    mov     r6, r5

    ldr     r0, [r4, #ST_ACC_Y]         @ native Y -> gcsv X
    mov     r1, r5
    bl      put_i16
    mov     r5, r0
    mov     r0, #','
    strb    r0, [r5], #1

    ldr     r0, [r4, #ST_ACC_X]         @ native X -> negative gcsv Y
    rsb     r0, r0, #0
    mov     r1, r5
    bl      put_i16
    mov     r5, r0
    mov     r0, #','
    strb    r0, [r5], #1

    ldr     r0, [r4, #ST_ACC_Z]
    mov     r1, r5
    bl      put_i16
    mov     r5, r0

    sub     r0, r5, r6
    str     r0, [r4, #ST_ACC_TEXT_N]
    mov     r0, #0
    str     r0, [r4, #ST_ACC_DIRTY]
    pop     {r4, r5, r6, pc}

gcsv_stream_block_done:
    sub     r1, r5, r6
    mov     r0, r11
    str     r1, [r0, #ST_TEXT_N]
#ifdef FPGYRO_BACKPRESSURE_PROBE
    movw    r3, #:lower16:O_BP_DIAG
    movt    r3, #:upper16:O_BP_DIAG
    add     r3, r10, r3
    ldr     ip, [r3, #BP_FLUSH_CUR]
    cmp     ip, #3
    blo     gcsv_stream_probe_block_done
    ldr     ip, [r3, #BP_BLOCKS_3]
    add     ip, ip, #1
    str     ip, [r3, #BP_BLOCKS_3]
gcsv_stream_probe_block_done:
    mov     ip, #0
    str     ip, [r3, #BP_PHASE]
    dmb     ish
#endif
    mov     r0, #1
    b       gcsv_stream_return

gcsv_stream_close:
    add     r7, r10, #O_STREAM_STATE
    ldr     r0, [r7, #ST_OPEN]
    cmp     r0, #1
    bne     gcsv_stream_fail
    movw    r6, #:lower16:O_TEXT
    movt    r6, #:upper16:O_TEXT
    add     r6, r10, r6
    ldr     r5, [r7, #ST_TEXT_N]
    add     r5, r6, r5
    bl      gcsv_stream_flush
    cmp     r0, #0
    beq     gcsv_stream_fail
    mov     r0, #O_FOBJ
    bl      close_file
    mov     r0, #0
    str     r0, [r7, #ST_TEXT_N]
#ifdef FPGYRO_BACKPRESSURE_PROBE
    movw    r3, #:lower16:O_BP_DIAG
    movt    r3, #:upper16:O_BP_DIAG
    add     r3, r10, r3
    str     r0, [r3, #BP_PHASE]
#endif
    dmb     ish
    str     r0, [r7, #ST_OPEN]
    mov     r0, #1
    b       gcsv_stream_return

gcsv_stream_abort:
    add     r7, r10, #O_STREAM_STATE
    ldr     r0, [r7, #ST_OPEN]
    cmp     r0, #1
    bne     gcsv_stream_abort_clear
    mov     r0, #O_FOBJ
    bl      close_file
gcsv_stream_abort_clear:
    mov     r0, #0
    str     r0, [r7, #ST_TEXT_N]
#ifdef FPGYRO_BACKPRESSURE_PROBE
    movw    r3, #:lower16:O_BP_DIAG
    movt    r3, #:upper16:O_BP_DIAG
    add     r3, r10, r3
    str     r0, [r3, #BP_PHASE]
    dmb     ish
#endif
    dmb     ish
    str     r0, [r7, #ST_OPEN]
    mov     r0, #1
    b       gcsv_stream_return

/* r5=current text end, r6=text base.  Full chunks are written only at complete
 * line boundaries; the five millisecond yield remains the same proven media
 * pacing as r14. */
gcsv_stream_flush:
    push    {r1, r2, r3, lr}
    sub     r2, r5, r6
    cmp     r2, #0
    moveq   r0, #1
    beq     gcsv_stream_flush_out
    add     r0, r10, #O_FOBJ
    mov     r1, r6
#ifdef FPGYRO_BACKPRESSURE_PROBE
    movw    r3, #:lower16:O_BP_DIAG
    movt    r3, #:upper16:O_BP_DIAG
    add     r3, r10, r3
    ldr     ip, [r3, #BP_FLUSH_CUR]
    add     ip, ip, #1
    str     ip, [r3, #BP_FLUSH_CUR]
    ldr     ip, [r3, #BP_FLUSH_TOTAL]
    add     ip, ip, #1
    str     ip, [r3, #BP_FLUSH_TOTAL]
    mov     ip, #2
    str     ip, [r3, #BP_PHASE]
    dmb     ish
#endif
    ldr_addr ip, F_WRITE
    blx     ip
    add     r3, r10, #O_STREAM_STATE
    str     r0, [r3, #ST_IO_RESULT]     @ sleep is free to clobber r0-r3
    mov     r5, r6
    add     r0, r10, #O_STREAM_STATE
    mov     r1, #0
    str     r1, [r0, #ST_TEXT_N]
#ifdef FPGYRO_BACKPRESSURE_PROBE
    movw    r3, #:lower16:O_BP_DIAG
    movt    r3, #:upper16:O_BP_DIAG
    add     r3, r10, r3
    mov     ip, #3
    str     ip, [r3, #BP_PHASE]
    dmb     ish
#endif
    mov     r0, #5
    movw    ip, #0x05D8
    movt    ip, #0xC037
    blx     ip
#ifdef FPGYRO_BACKPRESSURE_PROBE
    movw    r3, #:lower16:O_BP_DIAG
    movt    r3, #:upper16:O_BP_DIAG
    add     r3, r10, r3
    mov     ip, #1
    str     ip, [r3, #BP_PHASE]
    dmb     ish
#endif
    add     r3, r10, #O_STREAM_STATE
    ldr     r0, [r3, #ST_IO_RESULT]
gcsv_stream_flush_out:
    pop     {r1, r2, r3, pc}

gcsv_stream_fail:
#ifdef FPGYRO_BACKPRESSURE_PROBE
    movw    r3, #:lower16:O_BP_DIAG
    movt    r3, #:upper16:O_BP_DIAG
    add     r3, r10, r3
    mov     ip, #0
    str     ip, [r3, #BP_PHASE]
    dmb     ish
#endif
    mov     r0, #0
gcsv_stream_return:
    pop     {r3, r4, r5, r6, r7, r8, r9, r10, r11, pc}

#else
gcsv_build:
    push    {r3, r4, r5, r6, r7, r8, r9, r10, r11, lr}
    ldr     r0, [r10, #S_POST_BUSY]
    cmp     r0, #1
    bne     gcsv_fail_return

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
    add     r0, r10, #O_POST_PATH
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
    add     r1, r10, #O_POST_PATH
    mov     r2, #1
    bl      open_file
    cmp     r0, #0
    beq     gcsv_fail_return

    /* The .CSV, for writing. */
    mov     r0, #O_FOBJ2
    add     r1, r10, #O_GCSV_PATH
    mov     r2, #7
    bl      open_file
    cmp     r0, #0
    beq     gcsv_close_gyr_fail

    /* Header, with the clip name lifted out of the path. */
    movw    r6, #:lower16:O_TEXT
    movt    r6, #:upper16:O_TEXT
    add     r6, r10, r6
    mov     r5, r6
    bl      gcsv_get_head1
    mov     r1, r5
    bl      put_str
    mov     r5, r0
    add     r0, r10, #O_POST_PATH
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
    bl      gcsv_get_head2
    mov     r1, r5
    bl      put_str
    mov     r5, r0

    /* Skip the file header. */
    mov     r0, #0
    str     r0, [r10, #S_READ_N]
    add     r0, r10, #O_FOBJ
    movw    r1, #:lower16:O_READ
    movt    r1, #:upper16:O_READ
    add     r1, r10, r1
    mov     r2, #160
    add     r3, r10, #S_READ_N
    ldr_addr     ip, F_READ
    blx     ip
    ldr     r0, [r10, #S_POST_BUSY]
    cmp     r0, #1
    bne     gcsv_fail_both
    ldr     r0, [r10, #S_READ_N]
    cmp     r0, #160
    bne     gcsv_fail_both
    movw    r1, #:lower16:O_READ
    movt    r1, #:upper16:O_READ
    add     r1, r10, r1
    ldr     r0, [r1]
    movw    r2, #0x4647
    movt    r2, #0x3653                 @ GFS6
    cmp     r0, r2
    bne     gcsv_fail_both
    ldr     r11, [r1, #16]              @ source header owns the time origin
    ldr     r0, [r1, #4]
    cmp     r0, #3
    beq     gcsv_v3_seek
    cmp     r0, #4
    beq     gcsv_header_ready
    cmp     r0, #5
    bne     gcsv_fail_both
#ifdef FPGYRO_NATIVE_LIFECYCLE
    ldrb    r0, [r1, #28]
    ldr     r2, [r10, #O_POST_VOLUME]
    cmp     r0, r2
    bne     gcsv_fail_both
    ldrb    r0, [r1, #29]
    cmp     r0, #1                      @ MOV sidecars are intentionally skipped
    bne     gcsv_fail_both
#endif
    b       gcsv_header_ready

gcsv_v3_seek:
    /* v3 has no 96-byte persisted lens region; the first GFB starts at 64. */
    add     r0, r10, #O_FOBJ
    mov     r1, #64
    mov     r2, #0
    ldr_addr ip, F_SEEK
    blx     ip
    cmp     r0, #0
    beq     gcsv_fail_both
gcsv_header_ready:

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
     * 64 KiB a go instead. A block can straddle the end of a read, so whatever
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
    ldr     r1, [r10, #S_POST_BUSY]
    cmp     r1, #1
    bne     gcsv_fail_both
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
    beq     45f
    movw    r2, #0x4647
    movt    r2, #0x364D                 @ GFM6: normal end-of-blocks record
    cmp     r1, r2
    beq     gcsv_flush_last
    movt    r2, #0x3654                 @ GFT6: phase-probe end-of-blocks record
    cmp     r1, r2
    beq     gcsv_flush_last
    movt    r2, #0x3645                 @ GFE6 (accept old captures without GFM6)
    cmp     r1, r2
    beq     gcsv_flush_last
    b       gcsv_fail_both              @ damaged magic is not a successful tail
45:
    ldr     r2, [r4, #24]               @ payload bytes
    movw    r1, #:lower16:PAYLOAD_CAP
    cmp     r2, r1
    bhi     gcsv_fail_both
    add     r2, r2, #BLOCK_HEADER
    cmp     r0, r2
    bhs     44f                         @ the whole block is in the buffer
43: ldr     r0, [r10, #S_RD_EOF]
    cmp     r0, #0
    bne     gcsv_flush_last             @ a truncated tail, and no more file
    b       gcsv_refill
44:
    ldr     r8, [r4, #16]               @ gyro samples
    movw    r0, #:lower16:GYRO_SAMPLE_CAP
    cmp     r8, r0
    bhi     gcsv_fail_both
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
    cmp     r1, #ACCEL_REC_CAP
    bhi     gcsv_fail_both
    /* Header counts must describe the payload exactly.  Without this check a
     * torn block can turn one damaged word into billions of formatter loops or
     * a read beyond O_READ. */
    mov     ip, r8, lsl #3
    add     r0, r1, r1, lsl #1
    add     ip, ip, r0, lsl #2
    ldr     r0, [r4, #24]
    cmp     ip, r0
    bne     gcsv_fail_both
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
    bl      put_uint
    mov     r5, r0
    mov     r0, #','
    strb    r0, [r5], #1
    ldrsh   r0, [r7]
    mov     r1, r5
    bl      put_i16
    mov     r5, r0
    mov     r0, #','
    strb    r0, [r5], #1
    ldrsh   r0, [r7, #2]
    mov     r1, r5
    bl      put_i16
    mov     r5, r0
    mov     r0, #','
    strb    r0, [r5], #1
    ldrsh   r0, [r7, #6]                @ z sits past the pad
    mov     r1, r5
    bl      put_i16
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
    bl      put_i16
    mov     r5, r0
    mov     r0, #','
    strb    r0, [r5], #1
    movw    r3, #:lower16:ACC_VARS
    movt    r3, #:upper16:ACC_VARS
    add     r3, r10, r3
    ldr     r0, [r3, #8]
    rsb     r0, r0, #0
    mov     r1, r5
    bl      put_i16
    mov     r5, r0
    mov     r0, #','
    strb    r0, [r5], #1
    movw    r3, #:lower16:ACC_VARS
    movt    r3, #:upper16:ACC_VARS
    add     r3, r10, r3
    ldr     r0, [r3, #16]
    mov     r1, r5
    bl      put_i16
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
    cmp     r0, #0
    beq     gcsv_fail_both
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
    cmp     r0, #0
    beq     gcsv_fail_both
    mov     r0, #O_FOBJ2
    bl      close_file
    mov     r0, #O_FOBJ
    bl      close_file
    mov     r0, #1
    pop     {r3, r4, r5, r6, r7, r8, r9, r10, r11, pc}

gcsv_fail_both:
    mov     r0, #O_FOBJ2
    bl      close_file
gcsv_close_gyr_fail:
    mov     r0, #O_FOBJ
    bl      close_file
gcsv_fail_return:
    mov     r0, #0
    pop     {r3, r4, r5, r6, r7, r8, r9, r10, r11, pc}

/* Write out whatever is in the text buffer and rewind it. */
gcsv_flush:
    push    {r1, r2, r3, lr}
    sub     r2, r5, r6
    cmp     r2, #0
    moveq   r0, #1
    beq     43f
    add     r0, r10, #O_FOBJ2
    mov     r1, r6
    ldr_addr     ip, F_WRITE
    blx     ip
    mov     r3, r0
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
     * r14 keeps the five milliseconds but halves the number of calls and yields:
     * a 5.39 MB one-minute GCSV goes from about 329 chunks to 165. */
    mov     r0, #5
    movw    ip, #0x05D8
    movt    ip, #0xC037
    blx     ip
    ldr     r0, [r10, #S_POST_BUSY]
    cmp     r0, #1
    moveq   r0, r3
    movne   r0, #0
43: pop     {r1, r2, r3, pc}
#endif


gcsv_get_head1:
    adr     r0, gcsv_head1
    bx      lr
gcsv_get_head2:
    adr     r0, gcsv_head2
    bx      lr
gcsv_head1:
    .asciz  "GYROFLOW IMU LOG\nversion,1.3\nid,sigma_fp_v502_internal_icm20321\norientation,xyz\nfwversion,SIGMA fp 5.02\nvideofilename,"
    .align  2
gcsv_head2:
    .asciz  "\ntscale,0.000001\ngscale,0.000137923\nascale,0.0009765625\nt,gx,gy,gz,ax,ay,az\n"
    .align  2
