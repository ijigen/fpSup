/* The Gyroflow lens profile, built on the camera.
 *
 * This lives in the bufmem pool, not in the injection cave: it only runs when a
 * take has finished, it needs a kilobyte of template text, and the cave has
 * eight bytes left.  Code runs from the pool once the data cache has been
 * cleaned -- FUN_c000e91c, verified.
 *
 * Everything it needs comes from the camera.  Nothing is precomputed on a host:
 *
 *   timing row   FUN_c0320FC8(obj, mode)   +4 hmax, +6 tail, +8 vmax   (u16)
 *   geometry row FUN_c0321028(obj, mode)   +4 w, +8 h, +0x44 binH,
 *                                          +0x48 binV, +0x40 fps       (u32)
 *   rolling shutter  = hmax * h / 72       microseconds, 72 MHz sensor clock
 *   exact frame rate = 72e6 / (hmax * (vmax - 1) + tail)
 *
 * All five verified live against the host tables: 106 -> 10.556 ms,
 * 8 -> 6.160, 111 -> 7.828, 219 -> 7.256, 123 -> 21.325.
 */
    .syntax unified
    .arm

.macro ldr_addr reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm


.equ MODE_OBJ,   0xC343B588   /* FUN_c0322e88(); the accessors take it       */
.equ F_TIMING,   0xC0320FC8   /* (obj, mode) -> the timing row               */
.equ F_GEOM,     0xC0321028   /* (obj, mode) -> the geometry row             */
.equ SENSOR_HZ_MHZ, 72        /* the sensor clock, in MHz: cycles -> us      */

/* ---------------------------------------------------------------------------
 * udiv32 -- r0 / r1 -> r0, remainder in r1.  Clobbers r2, r3.
 *
 * Written out rather than borrowed: the compiler turned every constant divisor
 * in the firmware into a magic multiply, so there is no helper to call, and the
 * divisors here are not all constant.
 * ------------------------------------------------------------------------- */
    .global udiv32
udiv32:
    cmp     r1, #0
    moveq   r0, #0
    bxeq    lr
    mov     r2, #0                      /* quotient */
    mov     r3, #1                      /* the bit it is placing */
1:  cmp     r1, r0
    bhs     2f
    tst     r1, #0x80000000             /* never shift the divisor off the top */
    bne     2f
    lsl     r1, r1, #1
    lsl     r3, r3, #1
    b       1b
2:  cmp     r0, r1
    subhs   r0, r0, r1
    addhs   r2, r2, r3
    lsrs    r3, r3, #1
    lsr     r1, r1, #1
    bne     2b
    mov     r1, r0                      /* remainder */
    mov     r0, r2
    bx      lr

/* ---------------------------------------------------------------------------
 * pg_readout_us -- r0 = mode -> the rolling shutter in microseconds.
 * ------------------------------------------------------------------------- */
    .global pg_readout_us
pg_readout_us:
    push    {r4, r5, r6, lr}
    mov     r4, r0
    ldr_addr r0, MODE_OBJ
    mov     r1, r4
    ldr_addr ip, F_TIMING
    blx     ip
    ldrh    r5, [r0, #4]                /* hmax, in sensor clocks per line */
    ldr_addr r0, MODE_OBJ
    mov     r1, r4
    ldr_addr ip, F_GEOM
    blx     ip
    ldr     r1, [r0, #8]                /* the lines actually read out */
    mul     r0, r5, r1
    add     r0, r0, #SENSOR_HZ_MHZ / 2  /* round, so 219 comes out 7256 not 7255 */
    mov     r1, #SENSOR_HZ_MHZ
    bl      udiv32
    pop     {r4, r5, r6, pc}

/* ---------------------------------------------------------------------------
 * pg_fps_milli -- r0 = mode -> the frame rate x 1000, so 29.97 comes back
 * as 29970.  The geometry row's own +0x40 is rounded to a whole number and
 * cannot tell 29.97 from 30.
 * ------------------------------------------------------------------------- */
    .global pg_fps_milli
pg_fps_milli:
    push    {r4, r5, r6, r7, r8, lr}
    mov     r7, r0                      /* the mode; the calls below take r0 */
    ldr_addr r0, MODE_OBJ
    mov     r1, r7
    ldr_addr ip, F_TIMING
    blx     ip
    ldrh    r4, [r0, #4]                /* hmax */
    ldrh    r5, [r0, #6]                /* tail cycles */
    ldrh    r6, [r0, #8]                /* vmax lines */
    sub     r6, r6, #1
    mul     r6, r4, r6
    add     r6, r6, r5                  /* cycles in one frame */

    /* 72e6 * 1000 does not fit in a word, so the quotient and the remainder
     * are scaled separately: q*1000 + (rem*1000)/cycles.  The remainder is
     * smaller than the divisor, and cycles * 1000 stays inside a word for
     * every rate the sensor has. */
    movw    r0, #0xA200
    movt    r0, #0x044A                 /* 72,000,000 */
    mov     r1, r6
    bl      udiv32
    mov     r4, r0                      /* whole frames per second */
    mov     r0, r1                      /* what was left over */
    mov     r1, #1000
    mul     r0, r0, r1
    mov     r1, r6
    bl      udiv32
    mov     r1, #1000
    mla     r0, r4, r1, r0
    pop     {r4, r5, r6, r7, r8, pc}

/* ---------------------------------------------------------------------------
 * udiv64_32 -- (r1:r0) / r2 -> r0.  The quotient must fit in a word, which it
 * does here: the largest is a focal length in thousandths of a pixel.
 *
 * Needed because focal_px wants frame_w * focal_tenths * 6000000 over its
 * divisor, and that numerator passes four billion for any real lens.  Doing it
 * in 32 bits by pre-dividing costs half a percent of the focal length on a
 * cropped mode, which is a visible stabilisation error, so it is done properly.
 * ------------------------------------------------------------------------- */
    .global udiv64_32
udiv64_32:
    push    {r4, r5, r6, lr}
    mov     r3, #0                      /* quotient */
    mov     r4, #32
3:  lsls    r0, r0, #1
    adcs    r1, r1, r1
    lsl     r3, r3, #1
    cmp     r1, r2
    subhs   r1, r1, r2
    addhs   r3, r3, #1
    subs    r4, r4, #1
    bne     3b
    mov     r0, r3
    pop     {r4, r5, r6, pc}

/* ---------------------------------------------------------------------------
 * pg_focal_milli -- r0 = mode, r1 = the frame width in pixels,
 *                   r2 = the focal length in tenths of a millimetre
 *                -> the focal length in thousandths of a pixel.
 *
 *   covered = readout width x horizontal binning, capped at the active area:
 *             3032 columns binned 2 cover 6064, which is the whole sensor
 *   focal_px = frame_w * focal_mm / (35.9 mm * covered / 6000)
 *            = frame_w * focal_tenths * 6000000 / (359 * covered)   [x1000]
 * ------------------------------------------------------------------------- */
.equ SENSOR_ACTIVE_W,  6000
.equ SENSOR_ACTIVE_MM10, 359          /* 35.9 mm, in tenths */

    .global pg_focal_milli
pg_focal_milli:
    push    {r4, r5, r6, r7, r8, lr}
    mov     r5, r1                      /* frame width */
    mov     r6, r2                      /* focal, tenths of a mm */
    mov     r7, r0                      /* mode */
    ldr_addr r0, MODE_OBJ
    mov     r1, r7
    ldr_addr ip, F_GEOM
    blx     ip
    ldr     r1, [r0, #4]                /* readout width */
    ldr     r2, [r0, #0x44]             /* horizontal binning */
    cmp     r2, #0
    moveq   r2, #1
    mul     r4, r1, r2                  /* sensor columns covered */
    movw    r0, #:lower16:SENSOR_ACTIVE_W
    cmp     r4, r0
    movhi   r4, r0                      /* a mode reading past the active area
                                         * still only images the active area */
    /* (frame_w * focal_tenths) * 6000000, as a 64-bit product */
    mul     r0, r5, r6
    movw    r1, #:lower16:6000000
    movt    r1, #:upper16:6000000
    umull   r0, r1, r0, r1
    mov     r2, #SENSOR_ACTIVE_MM10
    mul     r2, r2, r4
    lsr     r3, r2, #1                  /* round to nearest: truncating costs a
                                         * fiftieth of a pixel on a cropped mode */
    adds    r0, r0, r3
    adc     r1, r1, #0
    bl      udiv64_32
    pop     {r4, r5, r6, r7, r8, pc}

/* ===========================================================================
 * The text.  r9 is the write pointer throughout.
 * ========================================================================= */

/* Emit the NUL-terminated string written inline after the call, so the profile
 * reads in the source in the order it lands on the card. */
    .global pg_es
pg_es:
4:  ldrb    r0, [lr], #1
    cmp     r0, #0
    strbne  r0, [r9], #1
    bne     4b
    add     lr, lr, #3
    bic     lr, lr, #3
    bx      lr

/* r0 = value -> decimal.  Divide by ten the way the firmware's own code does,
 * since there is no divide instruction to lean on. */
    .global pg_ei
pg_ei:
    push    {r4, r5, r6, lr}
    sub     sp, sp, #16
    mov     r6, #0
    mov     r5, r0
1:  movw    r0, #0xCCCD
    movt    r0, #0xCCCC
    umull   r1, r0, r5, r0
    lsr     r0, r0, #3
    add     r1, r0, r0, lsl #2
    sub     r1, r5, r1, lsl #1
    add     r1, r1, #'0'
    strb    r1, [sp, r6]
    add     r6, r6, #1
    mov     r5, r0
    cmp     r5, #0
    bne     1b
2:  subs    r6, r6, #1
    blt     3f
    ldrb    r1, [sp, r6]
    strb    r1, [r9], #1
    b       2b
3:  add     sp, sp, #16
    pop     {r4, r5, r6, pc}

/* r0 = value x 1000 -> "n.nnn".  Three places is a hundredth of a pixel and a
 * thousandth of a millisecond, which is finer than either number is known. */
    .global pg_em
pg_em:
    push    {r4, lr}
    mov     r1, #1000
    bl      udiv32
    mov     r4, r1
    bl      pg_ei
    mov     r0, #'.'
    strb    r0, [r9], #1
    mov     r0, r4
    mov     r1, #100
    bl      udiv32
    add     r0, r0, #'0'
    strb    r0, [r9], #1
    mov     r0, r1
    mov     r1, #10
    bl      udiv32
    add     r0, r0, #'0'
    strb    r0, [r9], #1
    add     r1, r1, #'0'
    strb    r1, [r9], #1
    pop     {r4, pc}

/* ===========================================================================
 * pg_build -- r10 = the logger's state block.  Builds the profile for the mode
 * the take ran in and writes it beside the clip.  Returns 1 if a file was
 * written.
 *
 * Nothing here comes from a host.  The lens is read off the mount, the mode's
 * geometry and timing out of the firmware's own tables, and the numbers are
 * formatted here.
 * ========================================================================= */
.equ S_POST_BUSY,  0xA0
.equ S_ACTIVE,     0x04
.equ S_NEXTSEQ,    0x18        /* blocks sealed so far in this take        */
.equ S_MODE_RUN,   0xA8        /* the mode sampled at the first block      */
.equ S_FILE,       0x08
.equ S_DROPPED,    0x14
.equ S_STOP,       0x60
.equ S_START_US,   0x88
.equ S_POST_COUNT, 0xAC
.equ S_GCSV_FN,    0xF8
.equ S_POOL_TRIED, 0xFC
.equ S_READ_N,     0x8C
.equ O_PATH,       0x100
.equ O_POST_PATH,  0x120
.equ O_POST_START, 0x140
.equ O_POST_MODE,  0x144
.equ O_POST_W,     0x148
.equ O_POST_H,     0x14C
.equ O_POST_VOLUME, 0x150
.equ O_LC_STATE,   0x154      /* PGEN-owned: 0 idle, 1 pending, 3 final,
                                 4 established, 6 publishing                  */
.equ O_LC_VOLUME,  0x158
.equ O_LC_KIND,    0x15C      /* 1 CDNG, 2 MOV */
.equ O_LC_FLAGS,   0x160
.equ O_LC_TOKEN,   0x164
.equ O_LC_TOP_HASH, 0x168
.equ O_LC_OPEN_TICKS, 0x16C
.equ O_LC_GEN,     0x170      /* PGEN-owned publication generation           */
.equ O_LC_TAKE,    0x174
.equ O_LC_COMMIT_POLLS, 0x178
.equ O_LC_ATTACH,  0x17C      /* callback-owned attached generation          */
/* Default-build aliases keep the previously field-tested geometry watcher
 * buildable until the native adapter is explicitly enabled. */
.equ O_BOUNDARY_COUNT, O_LC_STATE
.equ O_BOUNDARY_START, O_LC_VOLUME
.equ O_GCSV_PATH,  0x180
.equ O_FOBJ,       0x400
.equ O_FOBJ2,      0x800
.equ O_WORK,       0x1A000
.equ O_BP_DIAG,    0x40000
.equ BP_FLUSH_TOTAL, 0x08
.equ BP_BLOCKS,      0x0C
.equ BP_BLOCKS_3,    0x10
.equ BP_DROP_FORMAT, 0x14
.equ BP_DROP_WRITE,  0x18
.equ BP_DROP_SLEEP,  0x1C
.equ BP_DROP_OTHER,  0x20
.equ O_READ,       0x5B000
.equ O_TOP7,       0x6B000
.equ O_REC_SCRATCH, O_TOP7+0x90
.equ R_START,      0x00
.equ R_MODE,       0x04
.equ R_W,          0x08
.equ R_H,          0x0C
.equ R_VER,        0x10
.equ R_SIZE_H,     0x14
.equ R_RECOVERED,  0x18
.equ R_KIND,       0x1C
.equ O_POST_QUEUE, 0x2A0
.equ Q_HEAD,       0x00
.equ Q_DROPPED,    0x04
.equ Q_JOBS,       0x10
.equ Q_CAP,        7
.equ J_FLAGS,      0x00
.equ J_ATTEMPTS,   0x04
.equ J_CLOSE_TICK, 0x08
.equ J_START_US,   0x0C
.equ J_MODE,       0x10
.equ J_W,          0x14
.equ J_H,          0x18
.equ J_PATH,       0x1C
.equ POST_RETRIES, 12
.equ PG_TEXT,      0xF8800      /* from r12: the profile text            */
.equ PG_LENS,      0xF9800      /* from r12: what the lens hands back    */
/* Early-JSON bookkeeping (r39b/r39d), past the 4 KiB the bus name block can
 * occupy.  LC_MAGIC guards against whatever the pool held. */
.equ PG_LCACHE,    0xFA800      /* PG_LENS + 0x1000: offsets below stay 12-bit  */
.equ F_LENS_INFO,  0xC03341C8   /* firmware lens-info singleton getter (-> 0xC3464980) */
.equ LI_NAME,      0x24         /* space-padded model name                       */
.equ LI_NAME_LEN,  60
.equ LI_FOCAL,     0x68         /* focal length, tenths of a mm (400 = 40.0 mm)  */
.equ LC_JSON_GEN,  0x150        /* O_LC_ATTACH generation whose JSON was written early */
.equ LC_EARLY,     0x154        /* 1 while pg_build runs inside a take           */
.equ LC_JSON_RES,  0x158        /* last early pg_build result                    */
.equ LC_JSON_SEQ,  0x15C        /* S_NEXTSEQ when the early JSON was written     */
.equ LC_MAGIC,     0x160
.equ LC_JSON_SKIP, 0x164        /* stop-time JSON jobs skipped because of an early write */
.equ LC_MAGIC_V,   0x3148434C   /* "LCH1" */
.equ GEOMETRY,     0xC37CE210   /* {frame width, height, bytes} */

.equ F_LENS_CTX,   0xC03554A0
.equ F_LENS_READ,  0xC0355DE0
.equ B_FOCAL,      0x0D
.equ B_NAME,       0x2D

/* Native system-status manager.  Category 0x80 is a 68-byte object at
 * snapshot +0x7c.  Its byte 2 is MovieSaving: the core recording manager
 * rejects CinemaDNG start while it is nonzero, and the power-off waiter also
 * waits for it to clear.  Always publish through F_SYS_STATUS_UPDATE80 so
 * every native observer is notified; never write the snapshot directly. */
.equ F_SYS_STATUS_MGR,      0xC00178D8
.equ F_SYS_STATUS_SNAPSHOT, 0xC0017AC8
.equ F_SYS_STATUS_UPDATE80, 0xC0017CA0
.equ SYS_STATUS_80_OFF,     0x7C
.equ SYS80_STILL_EXPOSING,  0
.equ SYS80_STILL_SAVING,    1
.equ SYS80_MOVIE_SAVING,    2
.equ SYS80_STILL_PROCESSING, 3
.equ SYS80_CAPTURE_AUX,     4
.equ SYS80_MOVIE_RECORDING, 8
.equ SYS80_WORDS,           17

.equ F_MGR,        0xC0444658
.equ F_VOL,        0xC0444698
.equ F_CTOR,       0xC0365E90
.equ F_OPEN,       0xC0365FB0
.equ F_READ,       0xC0366060
.equ F_WRITE,      0xC03660E8
.equ F_CLOSE,      0xC0366020
.equ F_DTOR,       0xC0365ED0
.equ F_OPEN_SIZE,  0xC0366680
.equ F_PATH_SIZE,  0xC03665F8
.equ F_SEEK,       0xC03661E0
.equ F_DIR_CTOR,   0xC0366918
.equ F_DIR_DTOR,   0xC0366940
.equ F_DIR_OPEN,   0xC0366990
.equ F_DIR_MKDIR,  0xC03669C0
.equ F_DIR_NEXT,   0xC03669F8
.equ LENS_REGION,  0xC2F2D876
.equ RECOVERED,    0x80000000

.equ XMP_FOBJ_PTR, 0xC358E140
.equ TOP_FILE,     0xC358E148
.equ MOV_ACTIVE_PTR, 0xC35A952C
.equ MOV_PATHINFO_PTR, 0xC358DB8C
.equ MOV_BUSY_PTR, 0xC38D2DE8
.equ PATH_MGR_SD,  0xC3438400
.equ PATH_MGR_SSD, 0xC3438398
.equ SETTINGS_PTR, 0xC3075230

.macro rec_ptr reg
    movw    \reg, #:lower16:O_REC_SCRATCH
    movt    \reg, #:upper16:O_REC_SCRATCH
    add     \reg, r10, \reg
.endm

#ifdef FPGYRO_NATIVE_LIFECYCLE
/* r0 = 1 acquire, 0 release -> r0 = one only when this call changed byte 2.
 *
 * The firmware's native writers use this same read-copy-modify-publish
 * sequence.  Acquire is deliberately conservative: it refuses to overwrite
 * any live capture/save state.  MovieSaving is the recording manager's own
 * start gate, unlike the UI-only WaitEncoding experiment in r10/r11, and the
 * normal power-off waiter also observes it.  The scheduler's local ownership
 * flag makes release possible only after a successful zero-to-one acquire.
 *
 * The 72-byte frame keeps the public ABI's eight-byte stack alignment while
 * holding the native 68-byte category object. */
pg_native_movie_saving_set:
    push    {r4, r5, r6, r7, r8, lr}
    mov     r8, r0
    sub     sp, sp, #72
    ldr_addr ip, F_SYS_STATUS_MGR
    blx     ip
    mov     r5, r0
    ldr_addr ip, F_SYS_STATUS_SNAPSHOT
    blx     ip
    add     r1, r0, #SYS_STATUS_80_OFF
    mov     r2, sp
    mov     r3, #SYS80_WORDS
pg_native_movie_saving_copy:
    ldr     r4, [r1], #4
    str     r4, [r2], #4
    subs    r3, r3, #1
    bne     pg_native_movie_saving_copy

    ldrb    r0, [sp, #SYS80_MOVIE_SAVING]
    cmp     r8, #0
    beq     pg_native_movie_saving_release

    /* Acquiring while any native capture/save owner is live could publish a
     * stale copy over a just-starting recording.  The logger already waits on
     * these fields; repeat the check inside the copied transaction. */
    cmp     r0, #0
    bne     pg_native_movie_saving_unchanged
    ldrb    r1, [sp, #SYS80_STILL_EXPOSING]
    ldrb    r2, [sp, #SYS80_STILL_SAVING]
    orr     r1, r1, r2
    ldrb    r2, [sp, #SYS80_STILL_PROCESSING]
    orr     r1, r1, r2
    ldr     r2, [sp, #SYS80_CAPTURE_AUX]
    orr     r1, r1, r2
    ldrb    r2, [sp, #SYS80_MOVIE_RECORDING]
    orrs    r1, r1, r2
    bne     pg_native_movie_saving_unchanged

    /* Take a second native snapshot immediately before publication.  This
     * closes the long copy/check portion of the hand-off window without ever
     * reading or writing the manager's backing storage directly. */
    mov     r0, r5
    ldr_addr ip, F_SYS_STATUS_SNAPSHOT
    blx     ip
    add     r0, r0, #SYS_STATUS_80_OFF
    ldrb    r1, [r0, #SYS80_STILL_EXPOSING]
    ldrb    r2, [r0, #SYS80_STILL_SAVING]
    orr     r1, r1, r2
    ldrb    r2, [r0, #SYS80_MOVIE_SAVING]
    orr     r1, r1, r2
    ldrb    r2, [r0, #SYS80_STILL_PROCESSING]
    orr     r1, r1, r2
    ldr     r2, [r0, #SYS80_CAPTURE_AUX]
    orr     r1, r1, r2
    ldrb    r2, [r0, #SYS80_MOVIE_RECORDING]
    orrs    r1, r1, r2
    bne     pg_native_movie_saving_unchanged

    mov     r0, #1
    strb    r0, [sp, #SYS80_MOVIE_SAVING]
    b       pg_native_movie_saving_publish

pg_native_movie_saving_release:
    cmp     r0, #1
    bne     pg_native_movie_saving_unchanged
    mov     r0, #0
    strb    r0, [sp, #SYS80_MOVIE_SAVING]

pg_native_movie_saving_publish:
    mov     r0, r5
    mov     r1, sp
    ldr_addr ip, F_SYS_STATUS_UPDATE80
    blx     ip
    mov     r0, #1
    b       pg_native_movie_saving_done

pg_native_movie_saving_unchanged:
    mov     r0, #0
pg_native_movie_saving_done:
    add     sp, sp, #72
    pop     {r4, r5, r6, r7, r8, pc}
#endif

/* Queue scheduler entry used by logger.S.  It lives here because the injection
 * cave is fixed-size, while the separately loaded PGEN region has ample room. */
    .global pg_post_process
pg_post_process:
    cmp     r0, #1
    beq     pg_boundary_watch
    push    {r4, r5, r6, r7, r8, lr}
    mov     r7, #0                      @ owns native processing state
#ifdef FPGYRO_RECOVERY
    /* Run the bounded recovery scan once after PGEN loads, before normal RAM
     * jobs.  It creates \GYRO on the selected SD/SSD when needed. */
    ldr     r0, [r10, #S_POOL_TRIED]
    cmp     r0, #1
    bne     pg_post_next
    ldr     r0, [r10, #S_POST_COUNT]
    cmp     r0, #0
    bne     pg_post_next
    bl      pg_recovery_scan
#elif defined(FPGYRO_NATIVE_LIFECYCLE)
    /* Native lifecycle without boot recovery is the first on-camera test
     * configuration.  Mark the one-shot as complete so the idle writer does
     * not call this empty scheduler on every 5 ms poll. */
    ldr     r0, [r10, #S_POOL_TRIED]
    cmp     r0, #1
    moveq   r0, #2
    streq   r0, [r10, #S_POOL_TRIED]
#endif
pg_post_next:
    /* Once the native-XMP gate has admitted us, keep S_POST_BUSY asserted and
     * finish each take as one transaction: GYR is already closed, then this
     * same writer task makes that take's GCSV and JSON before advancing the
     * queue. */
    dmb     ish
    ldr     r0, [r10, #S_POST_BUSY]
    cmp     r0, #1
    bne     pg_post_out
    ldr     r0, [r10, #S_FILE]
    cmp     r0, #0
    bne     pg_post_out
    ldr     r6, [r10, #S_POST_COUNT]
    cmp     r6, #0
    beq     pg_post_out
#ifdef FPGYRO_NATIVE_LIFECYCLE
    /* Take the camera's real capture/power inhibitor before any generator can
     * yield.  It stays owned across every 5 ms GCSV yield, every retry, JSON,
     * and every queued take. */
    cmp     r7, #0
    bne     pg_post_locked
    mov     r0, #1
    bl      pg_native_movie_saving_set
    cmp     r0, #0
    beq     pg_post_out
    mov     r7, #1

    /* A callback may have published cancellation in the few instructions
     * before the native update.  Recheck under the inhibitor and use the one
     * common release path if it won. */
    dmb     ish
    ldr     r0, [r10, #S_POST_BUSY]
    cmp     r0, #1
    bne     pg_post_out
    ldr     r0, [r10, #S_FILE]
    cmp     r0, #0
    bne     pg_post_out
    ldr     r6, [r10, #S_POST_COUNT]
    cmp     r6, #0
    beq     pg_post_out
pg_post_locked:
#endif
    add     r4, r10, #O_POST_QUEUE
    ldr     r2, [r4, #Q_HEAD]
    add     r5, r2, r2, lsl #1
    add     r5, r4, r5, lsl #4
    add     r5, r5, #Q_JOBS
    ldr     r0, [r5, #J_FLAGS]
    ubfx    r1, r0, #16, #8
    cmp     r1, #2                       @ MOV target resolver is not defined yet
    orreq   r0, r0, #3                   @ keep GYR; never guess a CDNG sidecar path
    streq   r0, [r5, #J_FLAGS]
    tst     r0, #1
    beq     pg_post_gcsv

pg_post_json_head:
    bl      pg_post_snapshot
    ldr     r4, [r5, #J_FLAGS]
    tst     r4, #2
    bne     pg_post_json_done
    /* r39b: a take whose JSON was already written during recording (same
     * clip as O_PATH, early write reported success) needs nothing here. */
    mov     r0, r5
    bl      pg_json_early_done
    cmp     r0, #0
    orrne   r4, r4, #2
    strne   r4, [r5, #J_FLAGS]
    bne     pg_post_json_done
    bl      pg_build
    cmp     r0, #0
#ifdef FPGYRO_RECOVERY
    beq     pg_post_json_done
    mov     r0, #'J'
    bl      pg_marker_write
    cmp     r0, #0
#endif
    orrne   r4, r4, #2
    strne   r4, [r5, #J_FLAGS]
pg_post_json_done:
    and     r0, r4, #3
    cmp     r0, #3
    beq     pg_post_dequeue
    ldr     r0, [r10, #S_POST_BUSY]
    cmp     r0, #1
    bne     pg_post_out
    ldr     r0, [r5, #J_ATTEMPTS]
    add     r0, r0, #1
    str     r0, [r5, #J_ATTEMPTS]
    cmp     r0, #POST_RETRIES
    blo     pg_post_next              @ retry inside the same protected run
    add     r4, r10, #O_POST_QUEUE
    ldr     r0, [r4, #Q_DROPPED]
    add     r0, r0, #1
    str     r0, [r4, #Q_DROPPED]
    b       pg_post_dequeue

pg_post_gcsv:
    bl      pg_post_snapshot
    ldr     r4, [r5, #J_FLAGS]
    ldr     ip, [r10, #S_GCSV_FN]
    cmp     ip, #0
    moveq   r0, #0
    blxne   ip
    cmp     r0, #0
    beq     pg_post_gcsv_failed
#ifdef FPGYRO_RECOVERY
    mov     r0, #'G'
    bl      pg_marker_write
    cmp     r0, #0
    beq     pg_post_gcsv_failed
#endif
    orr     r4, r4, #1
    str     r4, [r5, #J_FLAGS]
    mov     r0, #0                     @ JSON gets its own full retry budget
    str     r0, [r5, #J_ATTEMPTS]
    b       pg_post_next               @ next file, without the outer 1 s gap
pg_post_gcsv_failed:
    ldr     r0, [r10, #S_POST_BUSY]
    cmp     r0, #1
    bne     pg_post_out                 @ cancellation is not a failed attempt
    ldr     r0, [r5, #J_ATTEMPTS]
    add     r0, r0, #1
    str     r0, [r5, #J_ATTEMPTS]
    cmp     r0, #POST_RETRIES
    blo     pg_post_next              @ retry inside the same protected run
    orr     r4, r4, #1                  @ exhausted: let later GCSVs proceed
    str     r4, [r5, #J_FLAGS]
    add     r4, r10, #O_POST_QUEUE
    ldr     r0, [r4, #Q_DROPPED]
    add     r0, r0, #1
    str     r0, [r4, #Q_DROPPED]
    b       pg_post_next               @ do not strand later valid jobs

pg_post_dequeue:
    add     r4, r10, #O_POST_QUEUE
    ldr     r0, [r4, #Q_HEAD]
    add     r0, r0, #1
    cmp     r0, #Q_CAP
    moveq   r0, #0
    str     r0, [r4, #Q_HEAD]
    ldr     r0, [r10, #S_POST_COUNT]
    sub     r0, r0, #1
    dmb     ish
    str     r0, [r10, #S_POST_COUNT]
    b       pg_post_next
pg_post_out:
#ifdef FPGYRO_NATIVE_LIFECYCLE
    cmp     r7, #0
    beq     pg_post_pop
    mov     r0, #0
    bl      pg_native_movie_saving_set
    mov     r7, #0
pg_post_pop:
#endif
    pop     {r4, r5, r6, r7, r8, pc}

#ifndef FPGYRO_NATIVE_LIFECYCLE
/* Previous field build, retained as the default until the native adapters are
 * explicitly approved for the camera image. */
/* A RAM-only boundary detector for the writer task.  MovieRecording can remain
 * asserted between two clips, but the DNG geometry stays zero throughout that
 * gap.  Twenty consecutive 5 ms polls reject a transient zero.  The callback
 * never reads a manager or opens a file; it only consumes ACTIVE 3. */
pg_boundary_watch:
    ldr     r0, [r10, #S_ACTIVE]
    cmp     r0, #2
    beq     pg_boundary_wait_live
    cmp     r0, #1
    bxne    lr

    ldr     r1, [r10, #S_START_US]
    ldr     r2, [r10, #O_BOUNDARY_START]
    cmp     r1, r2
    beq     pg_boundary_same_take
    str     r1, [r10, #O_BOUNDARY_START]
    mov     r2, #0
    str     r2, [r10, #O_BOUNDARY_COUNT]
pg_boundary_same_take:
    ldr_addr r1, GEOMETRY
    ldr     r1, [r1]
    cmp     r1, #0
    beq     pg_boundary_zero
    mov     r1, #1                   @ armed only after real DNG geometry appeared
    str     r1, [r10, #O_BOUNDARY_COUNT]
    bx      lr
pg_boundary_zero:
    ldr     r0, [r10, #S_FILE]
    cmp     r0, #2
    bxne    lr
    ldr     r0, [r10, #S_STOP]
    cmp     r0, #0
    bxne    lr
    ldr     r1, [r10, #O_BOUNDARY_COUNT]
    cmp     r1, #0                   @ geometry has not come alive yet
    bxeq    lr
    add     r1, r1, #1
    str     r1, [r10, #O_BOUNDARY_COUNT]
    cmp     r1, #21                  @ 20 zero polls = 100 ms
    bxlo    lr
    add     r2, r10, #S_ACTIVE
    dmb     ish
    ldrex   r0, [r2]
    cmp     r0, #1
    bne     pg_boundary_clrex
    mov     r0, #3
    strex   r1, r0, [r2]
    cmp     r1, #0
    bne     pg_boundary_out
    dmb     ish
    b       pg_boundary_out
pg_boundary_clrex:
    clrex
pg_boundary_out:
    bx      lr

/* ACTIVE 2 means the old GYR is sealing.  Do not let the callback start the
 * replacement until the next clip's geometry is genuinely live. */
pg_boundary_wait_live:
    ldr_addr r1, GEOMETRY
    ldr     r1, [r1]
    cmp     r1, #0
    bxeq    lr
    mov     r0, #0
    dmb     ish
    str     r0, [r10, #S_ACTIVE]
    bx      lr
#else
#include "lifecycle.inc.S"
#ifdef FPGYRO_RECOVERY
#include "recovery.inc.S"
#endif
#endif

/* r5 = queue job.  Copy every field generators use out of the ring before
 * calling either of them; the callback is then free to prepare the next take. */
pg_post_snapshot:
    add     r1, r5, #J_PATH
    add     r2, r10, #O_POST_PATH
    mov     r3, #20
1:  ldrb    r0, [r1], #1
    strb    r0, [r2], #1
    subs    r3, r3, #1
    bne     1b
    ldr     r0, [r5, #J_START_US]
    str     r0, [r10, #O_POST_START]
    ldr     r0, [r5, #J_MODE]
    str     r0, [r10, #O_POST_MODE]
    ldr     r0, [r5, #J_W]
    str     r0, [r10, #O_POST_W]
    ldr     r0, [r5, #J_H]
    str     r0, [r10, #O_POST_H]
    ldr     r0, [r5, #J_FLAGS]
    ubfx    r1, r0, #8, #8
    str     r1, [r10, #O_POST_VOLUME]
    lsr     r0, r0, #31
    rec_ptr ip
    str     r0, [ip, #R_RECOVERED]

    /* Rebuild this job's JSON path as well.  GCSV-first scheduling may process
     * a later queue entry before returning to the head's profile, so the shared
     * O_GCSV_PATH can belong to a different clip by then. */
    ldr_addr r0, 0x6E6F736A              @ "json"
    b       pg_cinema_path

/* r0 = four extension bytes in little endian. */
pg_cinema_path:
    push    {r4, lr}
    mov     r4, r0
    add     r0, r10, #O_GCSV_PATH
    movw    r1, #0x435C
    movt    r1, #0x4E49                 @ "\\CIN"
    str     r1, [r0]
    movw    r1, #0x4D45
    movt    r1, #0x5C41                 @ "EMA\\"
    str     r1, [r0, #4]
    add     r1, r10, #O_POST_PATH
    add     r1, r1, #6                  @ clip name after "\\GYRO\\"
    add     r2, r0, #8
    add     r3, r0, #17
    mov     ip, #0
2:  ldrb    r0, [r1, ip]
    strb    r0, [r2, ip]
    strb    r0, [r3, ip]
    add     ip, ip, #1
    cmp     ip, #8
    blo     2b
    add     r0, r10, #O_GCSV_PATH
    mov     r1, #92
    strb    r1, [r0, #16]
    mov     r1, #'.'
    strb    r1, [r0, #25]
    str     r4, [r0, #26]
    mov     r1, #0
    strb    r1, [r0, #30]
    dmb     ish
    pop     {r4, pc}

.macro S text
    bl      pg_es
    .asciz  "\text"
    .align  2
.endm

/* r0 = a NUL-terminated string in memory -> emitted, trailing blanks trimmed.
 * The mount pads names out with spaces. */
    .global pg_esb
pg_esb:
    push    {r4, lr}
    mov     r1, r9
    mov     r4, #40                     /* the block is not terminated anywhere
                                         * near the name: it runs on into the
                                         * lens's binary tables, which is what
                                         * put four kilobytes in the first one */
5:  cmp     r4, #0
    beq     6f
    ldrb    r2, [r0], #1
    cmp     r2, #0x20                   /* stop at anything unprintable */
    blo     6f
    cmp     r2, #0x7E
    bhi     6f
    cmp     r2, #34                     /* and at what JSON would need escaped */
    beq     6f
    cmp     r2, #92
    beq     6f
    strb    r2, [r9], #1
    sub     r4, r4, #1
    b       5b
6:  cmp     r9, r1
    bls     7f
    ldrb    r2, [r9, #-1]
    cmp     r2, #' '
    subeq   r9, r9, #1
    beq     6b
7:  pop     {r4, pc}


/* Frame geometry for the JSON, the way the camera itself derives it: the movie
 * image-size setting in the live CameraMgrSetting block (the shell's `setting
 * readcam` copies this same block to 0xC3758B98, which is why that mirror read
 * 1920x1080 on the shell card and 0 on a release card) plus the CinemaDNG
 * border of 16 columns and 10 rows (1936x1090, 3856x2170).  No media access,
 * no lens bus.  Returns r0 = width, r1 = height,
 * both zero if the setting is not a plausible size. */
.equ F_CAMSETTING,   0xC0206E98   /* CameraMgrSetting singleton; the live block is at +0x40 */
pg_setting_dims:
    push    {r4, lr}
    ldr_addr ip, F_CAMSETTING
    blx     ip
    cmp     r0, #0
    beq     79f
    add     r2, r0, #0x40               /* FUN_c0207088: the parameter block; .h at +0, .v at +4 */
    ldr     r0, [r2]
    ldr     r1, [r2, #4]
    cmp     r0, #640
    blo     79f
    cmp     r1, #360
    blo     79f
    cmp     r0, #0x2000
    bhi     79f
    cmp     r1, #0x2000
    bhi     79f
    add     r0, r0, #16
    add     r1, r1, #10
    pop     {r4, pc}
79: mov     r0, #0
    mov     r1, #0
    pop     {r4, pc}

    .global pg_build
pg_build:
    push    {r4, r5, r6, r7, r8, r9, r11, lr}
    bl      pg_post_owner
    cmp     r0, #0
    beq     pg_fail
    ldr     r4, [r10, #O_POST_MODE]
    cmp     r4, #0
    beq     pg_fail
    ldr     r5, [r10, #O_POST_W]        /* take's immutable frame width  */
    ldr     r6, [r10, #O_POST_H]        /* take's immutable frame height */
    cmp     r5, #0
    cmpne   r6, #0
    bne     41f
    /* The latched GEOMETRY global is unreliable in stream mode (0x0 across
     * whole takes).  Derive the frame the way the camera does: setting + border. */
    bl      pg_setting_dims
    mov     r5, r0
    mov     r6, r1
41: cmp     r5, #0
    beq     pg_fail
    cmp     r6, #0
    beq     pg_fail

#ifdef FPGYRO_RECOVERY
    /* A reboot may change the mounted lens.  Recovered JSON is allowed only
     * when the live correction region still matches the one in this GYR. */
    rec_ptr ip
    ldr     r0, [ip, #R_RECOVERED]
    cmp     r0, #0
    beq     pg_lens_ready
    bl      pg_lens_region_matches
    cmp     r0, #0
    beq     pg_fail
pg_lens_ready:
#endif

    /* The lens.  Seven hundred milliseconds each and they take the mount's
     * mutex, which is why none of this happens while a take is running.
     * r39b: the idle poll keeps focal + name cached in PG_LENS with a
     * LENS_REGION fingerprint; when it still matches the mounted lens the bus
     * is not touched at all, which is what lets a take write its JSON early. */
    movw    r11, #:lower16:PG_LENS
    movt    r11, #:upper16:PG_LENS
    add     r11, r10, r11
    add     r8, r11, #0x1000            /* the LC_* block, PG_LCACHE */
    /* r39d: the firmware keeps the mounted lens's name and focal length in
     * its own lens-info singleton (FUN_c03341c8 -> 0xC3464980: name at +0x24,
     * space padded; focal length at +0x68 in tenths of a mm).  Same bytes the
     * bus blocks give, without the bus. */
    ldr_addr ip, F_LENS_INFO
    blx     ip
    cmp     r0, #0
    beq     45f
    mov     r9, r0
    ldrb    r0, [r9, #LI_NAME]
    cmp     r0, #0x20
    blo     45f                         /* nothing mounted or not yet read */
    cmp     r0, #0x7E
    bhi     45f
    add     r1, r9, #LI_NAME
    add     r2, r11, #0x80
    mov     r3, #LI_NAME_LEN
47: ldrb    r0, [r1], #1
    strb    r0, [r2], #1
    subs    r3, r3, #1
    bne     47b
    mov     r0, #0
    strb    r0, [r2]
    ldr     r7, [r9, #LI_FOCAL]         /* focal length, tenths of a mm */
    cmp     r7, #10
    blo     45f
    cmp     r7, #0x10000
    bhs     45f
    b       46f
45: ldr     r0, [r8, #LC_EARLY]
    cmp     r0, #0
    bne     pg_fail                     /* inside a take: never touch the bus */
    ldr_addr ip, F_LENS_CTX
    blx     ip
    mov     r8, r0
    mov     r0, r8
    mov     r1, #B_FOCAL
    mov     r2, r11
    ldr_addr ip, F_LENS_READ
    blx     ip
    cmp     r0, #0
    beq     pg_fail
    ldr     r0, [r10, #S_POST_BUSY]
    cmp     r0, #1
    bne     pg_fail
    ldrb    r7, [r11]                   /* big-endian: the mount protocol is */
    ldrb    r0, [r11, #1]
    orr     r7, r0, r7, lsl #8          /* focal length, tenths of a mm */
    cmp     r7, #10
    blo     pg_fail
    mov     r0, r8
    mov     r1, #B_NAME
    add     r2, r11, #0x80
    ldr_addr ip, F_LENS_READ
    blx     ip
    cmp     r0, #0
    beq     pg_fail
    ldr     r0, [r10, #S_POST_BUSY]
    cmp     r0, #1
    bne     pg_fail
46:
    movw    r9, #:lower16:PG_TEXT
    movt    r9, #:upper16:PG_TEXT
    add     r9, r10, r9
    mov     r11, r9                     /* where the text starts */

    S "{\n  \"name\": \"SIGMA fp - "
    movw    r0, #:lower16:PG_LENS
    movt    r0, #:upper16:PG_LENS
    add     r0, r10, r0
    add     r0, r0, #0x80
    bl      pg_esb
    S " - "
    mov     r0, r5
    bl      pg_ei
    S "x"
    mov     r0, r6
    bl      pg_ei
    S " @"
    mov     r0, r4
    bl      pg_fps_milli
    bl      pg_em
    S " (mode "
    mov     r0, r4
    bl      pg_ei
    S ")\",\n  \"calibrated_by\": \"SIGMA fp, on the camera\",\n"
    S "  \"camera_brand\": \"SIGMA\",\n  \"camera_model\": \"fp\",\n  \"lens_model\": \""
    movw    r0, #:lower16:PG_LENS
    movt    r0, #:upper16:PG_LENS
    add     r0, r10, r0
    add     r0, r0, #0x80
    bl      pg_esb
    S "\",\n  \"camera_setting\": \""
    mov     r0, r5
    bl      pg_ei
    S "x"
    mov     r0, r6
    bl      pg_ei
    S " CinemaDNG\",\n"
    bl      pg_dims
    S "  \"identifier\": \"sigma_fp_mode"
    mov     r0, r4
    bl      pg_ei
    S "_"
    mov     r0, r5
    bl      pg_ei
    S "x"
    mov     r0, r6
    bl      pg_ei
    S "\",\n  \"calibrator_version\": \"1.5.0\",\n  \"compatible_settings\": [],\n"
    S "  \"frame_readout_time\": "
    mov     r0, r4
    bl      pg_readout_us
    bl      pg_em
    S ",\n  \"frame_readout_direction\": \"TopToBottom\",\n"
    S "  \"input_horizontal_stretch\": 1.0,\n  \"input_vertical_stretch\": 1.0,\n"
    S "  \"num_images\": 0,\n  \"fisheye_params\": {\n    \"RMS_error\": 0.0,\n"
    S "    \"camera_matrix\": [["
    mov     r0, r4
    mov     r1, r5
    mov     r2, r7
    bl      pg_focal_milli
    mov     r8, r0                      /* keep it for the second row */
    bl      pg_em
    S ", 0.0, "
    mov     r0, r5
    mov     r1, #1000
    mul     r0, r0, r1
    lsr     r0, r0, #1
    bl      pg_em
    S "], [0.0, "
    mov     r0, r8
    bl      pg_em
    S ", "
    mov     r0, r6
    mov     r1, #1000
    mul     r0, r0, r1
    lsr     r0, r0, #1
    bl      pg_em
    S "], [0.0, 0.0, 1.0]],\n"
    S "    \"distortion_coeffs\": [0.0, 0.0, 0.0, 0.0]\n  },\n"
#ifdef FPGYRO_BACKPRESSURE_PROBE
    movw    r3, #:lower16:O_BP_DIAG
    movt    r3, #:upper16:O_BP_DIAG
    add     r3, r10, r3
    S "  \"fpgyrosup_backpressure\": {\"slots\": 3, \"blocks\": "
    ldr     r0, [r3, #BP_BLOCKS]
    bl      pg_ei
    S ", \"flushes\": "
    ldr     r0, [r3, #BP_FLUSH_TOTAL]
    bl      pg_ei
    S ", \"blocks_3plus\": "
    ldr     r0, [r3, #BP_BLOCKS_3]
    bl      pg_ei
    S ", \"dropped_total\": "
    ldr     r0, [r10, #S_DROPPED]
    bl      pg_ei
    S ", \"drop_format\": "
    ldr     r0, [r3, #BP_DROP_FORMAT]
    bl      pg_ei
    S ", \"drop_write\": "
    ldr     r0, [r3, #BP_DROP_WRITE]
    bl      pg_ei
    S ", \"drop_sleep\": "
    ldr     r0, [r3, #BP_DROP_SLEEP]
    bl      pg_ei
    S ", \"drop_other\": "
    ldr     r0, [r3, #BP_DROP_OTHER]
    bl      pg_ei
    S "},\n"
#endif
    S "  \"sync_settings\": {},\n  \"official\": false\n}\n"

    sub     r8, r9, r11                 /* how much text there is */
    bl      pg_post_owner
    cmp     r0, #0
    beq     pg_fail
    bl      pg_write
    pop     {r4, r5, r6, r7, r8, r9, r11, pc}
pg_fail:
    mov     r0, #0
    pop     {r4, r5, r6, r7, r8, r9, r11, pc}

/* The three dimension objects, which are the same three numbers each time. */
pg_dims:
    push    {r4, lr}
    S "  \"calib_dimension\": {\"w\": "
    mov     r0, r5
    bl      pg_ei
    S ", \"h\": "
    mov     r0, r6
    bl      pg_ei
    S "},\n  \"orig_dimension\": {\"w\": "
    mov     r0, r5
    bl      pg_ei
    S ", \"h\": "
    mov     r0, r6
    bl      pg_ei
    S "},\n  \"output_dimension\": {\"w\": "
    mov     r0, r5
    bl      pg_ei
    S ", \"h\": "
    mov     r0, r6
    bl      pg_ei
    S "},\n"
    pop     {r4, pc}

/* \CLIP.gcsv -> \CLIP.json, then the text out.  r8 = length, r11 = start. */
pg_write:
    push    {r4, r5, r6, lr}
    add     r4, r10, #O_GCSV_PATH
    movw    r0, #0x736A                 /* 'j' 's' -- the gcsv's own path, with */
    strh    r0, [r4, #26]               /* the extension changed in place; both */
    movw    r0, #0x6E6F                 /* are four letters, so nothing shifts  */
    strh    r0, [r4, #28]
    mov     r0, #0
    strb    r0, [r4, #30]

#ifdef FPGYRO_NATIVE_LIFECYCLE
    bl      pg_post_owner
    cmp     r0, #0
    beq     pg_write_no_volume
    ldr     r1, [r10, #O_POST_VOLUME]
    cmp     r1, #1
    beq     pg_write_volume_ok
    cmp     r1, #5
    bne     pg_write_no_volume
pg_write_volume_ok:
#else
    ldr_addr ip, F_MGR
    blx     ip
    mov     r1, #0
    ldr_addr ip, F_VOL
    blx     ip
    mov     r1, r0
#endif
    add     r0, r10, #O_FOBJ2
    ldr_addr ip, F_CTOR
    blx     ip
    add     r0, r10, #O_FOBJ2
    mov     r1, r4
    mov     r2, #7
    ldr_addr ip, F_OPEN
    blx     ip
    cmp     r0, #0
    bne     8f
    /* Built but never opened: destroy it, or the file system keeps the object
     * and the next open of anything can fail. */
    add     r0, r10, #O_FOBJ2
    mov     r1, #2
    ldr_addr ip, F_DTOR
    blx     ip
    mov     r0, #0
    pop     {r4, r5, r6, pc}
#ifdef FPGYRO_NATIVE_LIFECYCLE
pg_write_no_volume:
    mov     r0, #0
    pop     {r4, r5, r6, pc}
#endif
8:  add     r0, r10, #O_FOBJ2
    mov     r1, r11
    mov     r2, r8
    ldr_addr ip, F_WRITE
    blx     ip
    mov     r6, r0
    add     r0, r10, #O_FOBJ2
    ldr_addr ip, F_CLOSE
    blx     ip
    add     r0, r10, #O_FOBJ2
    mov     r1, #2
    ldr_addr ip, F_DTOR
    blx     ip
    bl      pg_post_owner
    cmp     r0, #0
    movne   r0, r6
    pop     {r4, r5, r6, pc}

/* Idle lens cache + early JSON: helpers used by pg_build in every build. */
#include "lenscache.inc.S"
