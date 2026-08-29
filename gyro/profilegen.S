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
.equ S_MODE_RUN,   0xA8
.equ O_GCSV_PATH,  0x180
.equ O_FOBJ2,      0x800
.equ PG_TEXT,      0xF8800      /* from r10: the profile text            */
.equ PG_LENS,      0xF9800      /* from r10: what the lens hands back    */
.equ GEOMETRY,     0xC37CE210   /* {frame width, height, bytes} */

.equ F_LENS_CTX,   0xC03554A0
.equ F_LENS_READ,  0xC0355DE0
.equ B_FOCAL,      0x0D
.equ B_NAME,       0x2D

.equ F_MGR,        0xC0444658
.equ F_VOL,        0xC0444698
.equ F_CTOR,       0xC0365E90
.equ F_OPEN,       0xC0365FB0
.equ F_WRITE,      0xC03660E8
.equ F_CLOSE,      0xC0366020
.equ F_DTOR,       0xC0365ED0

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

    .global pg_build
pg_build:
    push    {r4, r5, r6, r7, r8, r9, r11, lr}
    ldr     r4, [r10, #S_MODE_RUN]
    cmp     r4, #0
    beq     pg_fail
    ldr_addr r0, GEOMETRY
    ldr     r5, [r0]                    /* frame width  */
    ldr     r6, [r0, #4]                /* frame height */
    cmp     r5, #0
    beq     pg_fail
    cmp     r6, #0
    beq     pg_fail

    /* The lens.  Seven hundred milliseconds each and they take the mount's
     * mutex, which is why none of this happens while a take is running. */
    movw    r11, #:lower16:PG_LENS
    movt    r11, #:upper16:PG_LENS
    add     r11, r10, r11
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
    S "  \"sync_settings\": {},\n  \"official\": false\n}\n"

    sub     r8, r9, r11                 /* how much text there is */
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

    ldr_addr ip, F_MGR
    blx     ip
    mov     r1, #0
    ldr_addr ip, F_VOL
    blx     ip
    mov     r1, r0
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
8:  add     r0, r10, #O_FOBJ2
    mov     r1, r11
    mov     r2, r8
    ldr_addr ip, F_WRITE
    blx     ip
    add     r0, r10, #O_FOBJ2
    ldr_addr ip, F_CLOSE
    blx     ip
    add     r0, r10, #O_FOBJ2
    mov     r1, #2
    ldr_addr ip, F_DTOR
    blx     ip
    mov     r0, #1
    pop     {r4, r5, r6, pc}
