/* ============================================================================
 * The lens profile, written by the camera at the top of the take.
 * ============================================================================
 *
 * Same shape as the .gcsv beside it: \GYRO\A001_037.json, built in the text
 * buffer and written once.  It goes out at record start, right after the log's
 * header and before any frames are flowing, because that is the quietest the
 * card gets during a take -- and because the sensor mode can only be read while
 * the camera is in one.
 *
 * Nothing here touches the lens bus.  A bus read is seven hundred milliseconds
 * and takes the mount's mutex; the firmware keeps the mounted lens's name and
 * focal length in its own singleton, and that is where these come from.
 *
 * WHY THERE ARE NO FLOATS
 *
 * The numbers that look like floats are integers in thousandths.  The readout
 * time, the frame rate, the focal length in pixels and the crop factor are all
 * computed as milli-units and printed as "<whole>.<three digits>" -- so a core
 * with no divide instruction and no FPU produces 29.970 and 2426.740 exactly,
 * and nothing rounds twice.
 *
 * WHERE THE NUMBERS COME FROM
 *
 * The camera's own tables, through the same two accessors `imager` uses:
 *
 *     F_TIMING(MODE_OBJ, mode)  +4 hmax, +6 tail cycles, +8 vmax lines
 *     F_GEOM  (MODE_OBJ, mode)  +4 readout width, +8 lines read, +0x44 binning
 *
 *     readout us = hmax * lines / 72          (72 MHz sensor clock)
 *     fps milli  = 72e6 / (hmax * (vmax-1) + tail)
 *     covered    = readout width * binning, capped at the active area
 *     crop milli = 6000 * 1000 / covered
 *     focal px   = frame_w * focal_mm / (35.9 * covered / 6000)
 *
 * The distortion coefficients are zero.  The camera has real ones for a lens it
 * knows and v1.4 writes them; that is the next piece, not this one, and a
 * profile with the readout time right is already the part that matters for
 * rolling shutter.
 * ========================================================================== */

.equ MODE_OBJ,       0xC343B588     /* FUN_c0322e88(); the accessors take it  */
.equ F_TIMING,       0xC0320FC8     /* (obj, mode) -> the timing row          */
.equ F_GEOM,         0xC0321028     /* (obj, mode) -> the geometry row        */
.equ F_LENS_INFO,    0xC03341C8     /* -> the lens singleton, no bus traffic  */
.equ O_LENS_NAME,    0x24           /* blank padded, not NUL terminated       */
.equ O_LENS_FOCAL,   0x68           /* tenths of a millimetre                 */
.equ LENS_NAME_MAX,  32
.equ SENSOR_HZ_MHZ,  72
.equ SENSOR_ACTIVE_W, 6000
.equ SENSOR_MM10,    359            /* 35.9 mm across the active area         */
.equ JSON_FOBJ_OFF,  0x800          /* inside the file object's reserved page */

/* S "text" -- emit a constant.  The text rides after the call and js walks it
 * out of lr, then rounds lr up past it.  One instruction and no pointer. */
.macro S text
    bl      js
    .asciz  "\text"
    .balign 4
.endm

/* r9 is the cursor everything writes through. */

js:
1:  ldrb    r0, [lr], #1
    cmp     r0, #0
    strbne  r0, [r9], #1
    bne     1b
    add     lr, lr, #3
    bic     lr, lr, #3
    bx      lr

/* ji -- r0 = unsigned, emitted at the cursor. */
ji: push    {r1, lr}
    mov     r1, r9
    bl      put_u32
    mov     r9, r0
    pop     {r1, lr}
    bx      lr

/* jm -- r0 = thousandths, emitted as "<whole>.<three digits>". */
jm: push    {r4, r5, r6, lr}
    movw    r1, #1000
    mov     r4, r0
    bl      udiv_1000                   @ r0 = whole, r1 = the rest
    mov     r5, r1
    bl      ji
    mov     r0, #'.'
    strb    r0, [r9], #1
    mov     r0, r5
    mov     r1, r9
    bl      put_u32_3
    mov     r9, r0
    pop     {r4, r5, r6, lr}
    bx      lr

/* jhalf -- r0 = a length, emitted as its half: "968.0" or "968.5".
 * The principal point is the frame's centre and lens_profile.py writes it as a
 * float, so an odd dimension has to come out .5 rather than be rounded away. */
jhalf:
    push    {r4, lr}
    mov     r4, r0
    lsr     r0, r0, #1
    bl      ji
    mov     r0, #'.'
    strb    r0, [r9], #1
    tst     r4, #1
    mov     r0, #'0'
    movne   r0, #'5'
    strb    r0, [r9], #1
    pop     {r4, lr}
    bx      lr

/* udiv_1000 -- r0 / 1000 -> r0, remainder in r1.  The one divisor this file
 * needs that is not a hundred. */
udiv_1000:
    movw    r2, #0x4DD3
    movt    r2, #0x1062                 @ 0x10624DD3
    umull   r3, r2, r0, r2
    lsr     r2, r2, #6                  @ r2 = r0 / 1000, checked over 0..4e6
    mov     r3, #1000
    mls     r1, r2, r3, r0
    mov     r0, r2
    bx      lr

/* put_u32_3 -- r0 = 0..999, r1 = destination.  Three digits, zero padded. */
put_u32_3:
    push    {r4, r5, r6, lr}
    mov     r4, r1
    mov     r5, r0
    movw    r1, #0x851F
    movt    r1, #0x51EB                 @ 0x51EB851F
    umull   ip, r1, r5, r1
    lsr     r1, r1, #5                  @ r1 = value / 100
    add     r0, r1, #'0'
    strb    r0, [r4], #1
    add     ip, r1, r1, lsl #2
    sub     r5, r5, ip, lsl #4
    sub     r5, r5, ip, lsl #2          @ value - 100 * (value / 100)
    mov     r0, r5
    mov     r1, r4
    bl      put_u32_2
    pop     {r4, r5, r6, lr}
    bx      lr

/* put_u32_2 -- r0 = 0..99, r1 = destination.  Two digits, zero padded. */
put_u32_2:
    push    {r4, lr}
    mov     r4, r1
    mov     r1, r0
    bl      dec_pairs_at
    add     r0, r0, r1, lsl #1
    ldrh    r0, [r0]
    strb    r0, [r4], #1
    lsr     r0, r0, #8
    strb    r0, [r4], #1
    mov     r0, r4
    pop     {r4, lr}
    bx      lr

/* ------------------------------------------------------------- the numbers */

/* udiv32 -- r0 / r1 -> r0, remainder r1.  Shift and subtract; the values here
 * are small enough that a reciprocal per divisor is not worth the constants. */
udiv32:
    push    {r4, lr}
    mov     r2, #0
    mov     r3, #1
    cmp     r1, #0
    beq     9f
1:  cmp     r1, r0
    lslls   r1, r1, #1
    lslls   r3, r3, #1
    bls     1b
2:  cmp     r0, r1
    subhs   r0, r0, r1
    addhs   r2, r2, r3
    lsrs    r3, r3, #1
    lsr     r1, r1, #1
    bne     2b
    mov     r1, r0
    mov     r0, r2
9:  pop     {r4, lr}
    bx      lr

/* udiv64_32 -- (r1:r0) / r2 -> r0.  The quotient fits a word here: the largest
 * is a focal length in thousandths of a pixel.  Needed because focal_px wants
 * frame_w * focal_tenths * 6000000 over its divisor, and that numerator passes
 * four billion for any real lens; pre-dividing to stay in 32 bits costs half a
 * percent on a cropped mode, which is a visible stabilisation error. */
udiv64_32:
    push    {r4, lr}
    mov     r3, #0
    mov     r4, #32
1:  lsls    r0, r0, #1
    adcs    r1, r1, r1
    lsl     r3, r3, #1
    cmp     r1, r2
    subhs   r1, r1, r2
    addhs   r3, r3, #1
    subs    r4, r4, #1
    bne     1b
    mov     r0, r3
    pop     {r4, lr}
    bx      lr

/* j_timing / j_geom -- r0 = mode -> the camera's own row for it. */
j_timing:
    push    {r4, lr}
    mov     r1, r0
    movw    r0, #:lower16:MODE_OBJ
    movt    r0, #:upper16:MODE_OBJ
    movw    ip, #:lower16:F_TIMING
    movt    ip, #:upper16:F_TIMING
    blx     ip
    pop     {r4, lr}
    bx      lr

j_geom:
    push    {r4, lr}
    mov     r1, r0
    movw    r0, #:lower16:MODE_OBJ
    movt    r0, #:upper16:MODE_OBJ
    movw    ip, #:lower16:F_GEOM
    movt    ip, #:upper16:F_GEOM
    blx     ip
    pop     {r4, lr}
    bx      lr

/* j_covered -- r0 = mode -> the sensor columns the mode images. */
j_covered:
    push    {r4, lr}
    bl      j_geom
    ldr     r1, [r0, #4]                @ readout width
    ldr     r2, [r0, #0x44]             @ horizontal binning
    cmp     r2, #0
    moveq   r2, #1
    mul     r0, r1, r2
    movw    r1, #:lower16:SENSOR_ACTIVE_W
    cmp     r0, r1
    movhi   r0, r1                      @ a mode reading past the active area
    pop     {r4, lr}                    @ still images only the active area
    bx      lr

/* j_readout_us -- r0 = mode -> the rolling shutter, microseconds. */
j_readout_us:
    push    {r4, r5, r6, lr}
    mov     r4, r0
    bl      j_timing
    ldrh    r5, [r0, #4]                @ hmax, sensor clocks a line
    mov     r0, r4
    bl      j_geom
    ldr     r1, [r0, #8]                @ the lines actually read out
    mul     r0, r5, r1
    add     r0, r0, #SENSOR_HZ_MHZ / 2  @ round, so 219 comes out 7256 not 7255
    mov     r1, #SENSOR_HZ_MHZ
    bl      udiv32
    pop     {r4, r5, r6, lr}
    bx      lr

/* j_fps_milli -- r0 = mode -> the frame rate x 1000, so 29.97 is 29970.
 * The geometry row's own field is rounded to a whole number and cannot tell
 * 29.97 from 30. */
j_fps_milli:
    push    {r4, r5, r6, lr}
    bl      j_timing
    ldrh    r4, [r0, #4]                @ hmax
    ldrh    r5, [r0, #6]                @ tail cycles
    ldrh    r6, [r0, #8]                @ vmax lines
    sub     r6, r6, #1
    mul     r6, r4, r6
    add     r6, r6, r5                  @ cycles in one frame
    cmp     r6, #0
    beq     9f
    /* 72e6 * 1000 does not fit a word, so the quotient and the remainder are
     * scaled apart: q*1000 + (rem*1000)/cycles. */
    movw    r0, #0xA200
    movt    r0, #0x044A                 @ 72,000,000
    mov     r1, r6
    bl      udiv32
    mov     r4, r0
    mov     r0, r1
    mov     r1, #1000
    mul     r0, r0, r1
    mov     r1, r6
    bl      udiv32
    mov     r1, #1000
    mla     r0, r4, r1, r0
    pop     {r4, r5, r6, lr}
    bx      lr
9:  mov     r0, #0
    pop     {r4, r5, r6, lr}
    bx      lr

/* j_crop_milli -- r0 = mode -> the crop factor x 1000. */
j_crop_milli:
    push    {r4, lr}
    bl      j_covered
    cmp     r0, #0
    movweq  r0, #1000
    beq     9f
    mov     r1, r0
    movw    r0, #:lower16:6000000
    movt    r0, #:upper16:6000000       @ SENSOR_ACTIVE_W * 1000
    bl      udiv32
9:  pop     {r4, lr}
    bx      lr

/* j_focal_milli -- r0 = mode, r1 = frame width, r2 = focal in tenths of a mm
 * -> the focal length in thousandths of a pixel.
 *
 *   focal_px = frame_w * focal_mm / (35.9 mm * covered / 6000)
 *            = frame_w * focal_tenths * 6000000 / (359 * covered)   [x1000]
 */
j_focal_milli:
    push    {r4, r5, r6, r7, r8, lr}
    mov     r5, r1
    mov     r6, r2
    bl      j_covered
    cmp     r0, #0
    beq     9f
    mov     r7, #SENSOR_MM10
    mul     r7, r7, r0                  @ the divisor: 359 * covered
    umull   r0, r1, r5, r6              @ frame_w * focal_tenths
    movw    r2, #:lower16:6000000
    movt    r2, #:upper16:6000000
    umull   r3, r4, r0, r2
    mla     r4, r1, r2, r4              @ (r4:r3) = that, times six million
    mov     r0, r3
    mov     r1, r4
    mov     r2, r7
    bl      udiv64_32
    pop     {r4, r5, r6, r7, r8, lr}
    bx      lr
9:  mov     r0, #0
    pop     {r4, r5, r6, r7, r8, lr}
    bx      lr

/* j_lens -- r0 = where to put the name.  Returns r0 = the focal in tenths.
 *
 * The name is blank padded rather than terminated, so it is copied up to
 * LENS_NAME_MAX and the trailing spaces are dropped.  No bus traffic: this is
 * the firmware's own singleton. */
j_lens:
    push    {r4, r5, r6, lr}
    mov     r4, r0
    movw    ip, #:lower16:F_LENS_INFO
    movt    ip, #:upper16:F_LENS_INFO
    blx     ip
    cmp     r0, #0
    beq     8f
    mov     r5, r0
    add     r6, r5, #O_LENS_NAME
    mov     r2, #0                      @ how much is not blank
    mov     r3, #0
1:  ldrb    r1, [r6, r3]
    cmp     r1, #0
    beq     2f
    strb    r1, [r4, r3]
    cmp     r1, #' '
    addne   r2, r3, #1                  @ the last thing that was not a space
    add     r3, r3, #1
    cmp     r3, #LENS_NAME_MAX
    blo     1b
2:  cmp     r2, #0
    bne     3f
    mov     r1, #'-'                    @ no lens, or a nameless one
    strb    r1, [r4]
    mov     r2, #1
3:  mov     r1, #0
    strb    r1, [r4, r2]
    ldr     r0, [r5, #O_LENS_FOCAL]
    pop     {r4, r5, r6, lr}
    bx      lr
8:  mov     r1, #'-'
    strb    r1, [r4]
    mov     r1, #0
    strb    r1, [r4, #1]
    mov     r0, #0
    pop     {r4, r5, r6, lr}
    bx      lr

/* j_dims -- the frame the take is recording, from the camera's settings.
 * Returns r0 = width, r1 = height, or zeros.  Not 0xC37CE210: that one holds
 * {1936, 1090, ...} at 1080p, reads zero at UHD, and read zero right through a
 * 35 s take here.  CameraMgrSetting has it while the camera is idle too. */
j_dims:
    push    {r4, lr}
    movw    ip, #:lower16:F_CAMSETTING
    movt    ip, #:upper16:F_CAMSETTING
    blx     ip
    cmp     r0, #0
    beq     9f
    add     r0, r0, #SETTING_DIMS
    ldr     r1, [r0, #4]
    ldr     r0, [r0]
    cmp     r0, #640
    blo     9f
    cmp     r1, #360
    blo     9f
    movw    ip, #0x2000
    cmp     r0, ip
    bhi     9f
    cmp     r1, ip
    bhi     9f
    add     r0, r0, #DNG_PAD_W          @ a CinemaDNG frame is sixteen wider
    add     r1, r1, #DNG_PAD_H          @ and ten taller than the menu says
    pop     {r4, lr}
    bx      lr
9:  mov     r0, #0
    mov     r1, #0
    pop     {r4, lr}
    bx      lr

/* gcsv_json_write -- build the profile and put it beside the log.
 *
 * Called from writer_openfile once the log's header is out, so the text buffer
 * is free and no frames are flowing yet.  Everything it needs is a register
 * read or a call into the camera's own tables; nothing touches the lens bus.
 *
 * A missing piece is a missing profile, not a broken one: no dimensions, no
 * mode, or no file object and it writes nothing at all.
 */
    .global gcsv_json_write
gcsv_json_write:
    push    {r4, r5, r6, r7, r8, r9, r10, r11, ip, lr}

    movw    r4, #:lower16:G_TEXT
    movt    r4, #:upper16:G_TEXT
    ldr     r4, [r4]
    cmp     r4, #0
    beq     90f
    mov     r9, r4                      @ the cursor
    add     r11, r4, #0x1000            @ the lens name lives past the json

    bl      j_dims
    cmp     r0, #0
    beq     90f
    mov     r5, r0                      @ width
    mov     r6, r1                      @ height

    movw    ip, #:lower16:SENSOR_MODE_FN
    movt    ip, #:upper16:SENSOR_MODE_FN
    blx     ip
    mov     r7, r0                      @ the mode the take is in
    cmp     r7, #0
    beq     90f

    mov     r0, r11
    bl      j_lens
    /* The focal the correction data was measured at, not the one on the
     * barrel: a SIGMA 40mm Art says 40.0 and calibrates at 39.4, and the
     * camera matrix wants the second -- it is the scale that turns a gyro
     * angle into pixels, so an error there over-corrects every rotation. */
    bl      pg_dist_focal
    mov     r8, r0                      @ the focal length, tenths of a mm

    S "{\n  \"name\": \"SIGMA fp - "
    mov     r0, r11
    bl      j_name
    S " - "
    mov     r0, r5
    bl      ji
    S "x"
    mov     r0, r6
    bl      ji
    S " @"
    mov     r0, r7
    bl      j_fps_milli
    bl      jm
    S " (mode "
    mov     r0, r7
    bl      ji
    S ")\",\n  \"calibrated_by\": \"SIGMA fp, on the camera\",\n"
    S "  \"camera_brand\": \"SIGMA\",\n  \"camera_model\": \"fp\",\n  \"lens_model\": \""
    mov     r0, r11
    bl      j_name
    S "\",\n  \"camera_setting\": \""
    mov     r0, r5
    bl      ji
    S "x"
    mov     r0, r6
    bl      ji
    S " @"
    mov     r0, r7
    bl      j_fps_milli
    bl      jm
    S " CinemaDNG\",\n"

    S "  \"calib_dimension\": {\"w\": "
    mov     r0, r5
    bl      ji
    S ", \"h\": "
    mov     r0, r6
    bl      ji
    S "},\n  \"orig_dimension\": {\"w\": "
    mov     r0, r5
    bl      ji
    S ", \"h\": "
    mov     r0, r6
    bl      ji
    S "},\n  \"output_dimension\": {\"w\": "
    mov     r0, r5
    bl      ji
    S ", \"h\": "
    mov     r0, r6
    bl      ji
    S "},\n  \"identifier\": \"sigma_fp_mode"
    mov     r0, r7
    bl      ji
    S "_"
    mov     r0, r5
    bl      ji
    S "x"
    mov     r0, r6
    bl      ji
    S "\",\n  \"calibrator_version\": \"1.5.0\",\n  \"compatible_settings\": [],\n"

    S "  \"frame_readout_time\": "
    mov     r0, r7
    bl      j_readout_us
    bl      jm
    S ",\n  \"frame_readout_direction\": \"TopToBottom\",\n"
    S "  \"input_horizontal_stretch\": 1.0,\n  \"input_vertical_stretch\": 1.0,\n"
    S "  \"num_images\": 0,\n  \"fps\": "
    mov     r0, r7
    bl      j_fps_milli
    bl      jm
    S ",\n  \"focal_length\": "
    mov     r0, r8
    mov     r1, #100
    mul     r0, r0, r1                  @ tenths of a mm as thousandths
    bl      jm
    S ",\n  \"crop_factor\": "
    mov     r0, r7
    bl      j_crop_milli
    bl      jm
    S ",\n  \"global_shutter\": false,\n  \"asymmetrical\": false,\n"

    S "  \"fisheye_params\": {\n    \"RMS_error\": 0.0,\n    \"camera_matrix\": [["
    mov     r0, r7
    mov     r1, r5
    mov     r2, r8
    bl      j_focal_milli
    mov     r8, r0                      @ focal_px x 1000, which the fit adjusts
    bl      j_dist_prepare              @ by folding the lens's magnification in
    mov     r10, r8
    mov     r0, r10
    bl      jm
    S ", 0.0, "
    mov     r0, r5
    bl      jhalf
    S "], [0.0, "
    mov     r0, r10
    bl      jm
    S ", "
    mov     r0, r6
    bl      jhalf
    S "], [0.0, 0.0, 1.0]],\n"
    S "    \"distortion_coeffs\": ["
    bl      j_dist_emit
    S "]\n  },\n"
    S "  \"sync_settings\": {},\n  \"official\": false\n}\n"

    sub     r6, r9, r4                  @ how much there is
    bl      j_open
    cmp     r0, #0
    beq     90f
    mov     r5, r0
    mov     r1, r4
    mov     r2, r6
    mov     r0, r5
    movw    ip, #:lower16:F_WRITE
    movt    ip, #:upper16:F_WRITE
    blx     ip
    mov     r0, r5
    mov     r1, #2
    movw    ip, #:lower16:F_DTOR
    movt    ip, #:upper16:F_DTOR
    blx     ip

90: pop     {r4, r5, r6, r7, r8, r9, r10, r11, ip, lr}
    bx      lr

/* j_name -- r0 = the NUL-terminated lens name, emitted at the cursor. */
j_name:
    push    {r4, lr}
1:  ldrb    r4, [r0], #1
    cmp     r4, #0
    beq     2f
    strb    r4, [r9], #1
    b       1b
2:  pop     {r4, lr}
    bx      lr

/* j_open -- the profile's own file, beside the log.  Returns the object or 0.
 *
 * writer_path still holds \GYRO\A001_037.gcsv, so only the extension changes;
 * the object goes in the page already reserved for the log's. */
j_open:
    push    {r4, r5, r6, lr}
    movw    r4, #:lower16:T_FOBJ
    movt    r4, #:upper16:T_FOBJ
    ldr     r4, [r4]
    cmp     r4, #0
    beq     9f
    add     r4, r4, #JSON_FOBJ_OFF

    mov     r0, #'j'
    bl      clip_path                   @ the same path with a different suffix
    cmp     r0, #0
    beq     9f
    mov     r5, r0

    /* The same disk the gcsv went to.  clip_path already gave us the same
     * folder; getting the volume from F_VOL again would send the json to the
     * SSD while the gcsv sat on the SD, and a log without its profile is half
     * a take. */
    movw    ip, #:lower16:G_FALLBACK
    movt    ip, #:upper16:G_FALLBACK
    ldr     ip, [ip]
    cmp     ip, #2
    moveq   r1, #VOL_SD
    beq     1f
    movw    ip, #:lower16:F_MGR
    movt    ip, #:upper16:F_MGR
    blx     ip
    mov     r1, #0
    movw    ip, #:lower16:F_VOL
    movt    ip, #:upper16:F_VOL
    blx     ip
    mov     r1, r0
1:  mov     r0, r4
    movw    ip, #:lower16:F_CTOR
    movt    ip, #:upper16:F_CTOR
    blx     ip

    mov     r0, r4
    mov     r1, r5
    mov     r2, #F_MODE_AUD
    movw    ip, #:lower16:F_OPEN
    movt    ip, #:upper16:F_OPEN
    blx     ip
    mov     r6, r0

    cmp     r6, #0
    beq     8f
    mov     r0, r4
    pop     {r4, r5, r6, lr}
    bx      lr

8:  mov     r0, r4                      @ it did not open: give the object back
    mov     r1, #2
    movw    ip, #:lower16:F_DTOR
    movt    ip, #:upper16:F_DTOR
    blx     ip
9:  mov     r0, #0
    pop     {r4, r5, r6, lr}
    bx      lr
