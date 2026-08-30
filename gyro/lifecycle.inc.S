/* Native clip lifecycle adapters for profilegen.S.
 *
 * This file is included into the PGEN translation unit.  It performs only RAM
 * observation plus a single F_VOL lookup at each native begin edge.  It never
 * opens a file and never runs in the gyro callback.
 *
 * O_LC_STATE has one writer: this PGEN task.
 *   0 idle
 *   1 CDNG opening; an attached callback may buffer in RAM
 *   3 native clip committed/final boundary
 *   4 media established; an attached writer may create the .GYR
 *   6 publication in progress; the callback must not attach
 *
 * The callback never modifies this word.  It claims S_FILE and latches
 * O_LC_GEN into O_LC_ATTACH.  Publication uses state 6 plus a second S_FILE
 * check, so the two cores either attach the old generation or publish the new
 * one; neither needs an exclusive access against the DMA-backed pool.
 */

pg_boundary_watch:
    push    {r4, r5, r6, r7, r8, r9, r11, lr}
    ldr     r11, [r10, #O_LC_FLAGS]

    ldr_addr r0, XMP_FOBJ_PTR
    ldr     r5, [r0]
    cmp     r5, #0
    bne     pg_lc_cdng
    orr     r11, r11, #1                @ observed XMP inactive
    str     r11, [r10, #O_LC_FLAGS]

    ldr_addr r0, MOV_ACTIVE_PTR
    ldrb    r0, [r0]
    cmp     r0, #0
    bne     pg_lc_mov
    orr     r11, r11, #2                @ observed MOV inactive
    str     r11, [r10, #O_LC_FLAGS]

    /* Neither native adapter is active.  A CDNG which never established its
     * first DNG can stop immediately.  An established CDNG waits for the
     * manager's AddTakeNo commit; MOV active falls only after ImageSave. */
    ldr     r6, [r10, #O_LC_STATE]
    cmp     r6, #1
    beq     pg_lc_final
    cmp     r6, #4
    beq     pg_lc_native_was_running
    bne     pg_lc_out
pg_lc_native_was_running:
    ldr     r0, [r10, #O_LC_KIND]
    cmp     r0, #1
    bne     pg_lc_final                   @ MOV catalog-active fell
    bl      pg_cdng_committed
    cmp     r0, #0
    beq     pg_lc_out
pg_lc_final:
    mov     r0, #3
    dmb     ish
    str     r0, [r10, #O_LC_STATE]
    b       pg_lc_out

/* CDNG OPENING: XMP allocation is early, so it only starts RAM buffering.
 * TopFile confirms that the first DNG was really created. */
pg_lc_cdng:
    mov     r4, #1
    ldr     r6, [r10, #O_LC_STATE]
    cmp     r6, #1
    beq     pg_lc_cdng_pending
    cmp     r6, #4
    beq     pg_lc_cdng_established

    /* A failed XMP open can leave the same nonzero pointer behind. */
    cmp     r6, #3
    bne     pg_lc_publish_cdng
    tst     r11, #1
    bne     pg_lc_publish_cdng
    ldr     r0, [r10, #O_LC_TOKEN]
    cmp     r0, r5
    bne     pg_lc_publish_cdng
    bl      pg_top_hash
    ldr     r1, [r10, #O_LC_TOP_HASH]
    cmp     r0, r1
    beq     pg_lc_out

pg_lc_publish_cdng:
    ldr     r0, [r10, #S_FILE]
    cmp     r0, #0
    bne     pg_lc_out
    /* Own publication before either blocking volume lookup.  A stale callback
     * which already saw phase 1/4 claims S_FILE, re-reads phase 6 and backs out;
     * the second check below catches the opposite ordering. */
    mov     r0, #6
    str     r0, [r10, #O_LC_STATE]
    dmb     ish
    ldr     r0, [r10, #S_FILE]
    cmp     r0, #0
    bne     pg_lc_publish_cancel
    bl      pg_current_volume
    mov     r8, r0
    cmp     r8, #1
    beq     pg_lc_cdng_volume_ok
    cmp     r8, #5
    bne     pg_lc_publish_cancel
pg_lc_cdng_volume_ok:
    ldr_addr r0, XMP_FOBJ_PTR
    ldr     r0, [r0]
    cmp     r0, r5
    bne     pg_lc_publish_cancel
    bl      pg_current_volume
    cmp     r0, r8                       @ stable lookup, not old token/new volume
    bne     pg_lc_publish_cancel
    ldr_addr r0, XMP_FOBJ_PTR
    ldr     r0, [r0]
    cmp     r0, r5                       @ the second lookup may also have blocked
    bne     pg_lc_publish_cancel
    mov     r0, r8
    bl      pg_manager_for_volume
    mov     r7, r0

    /* Mirror RecordFilePathMgrCinema v4's candidate calculation. */
    ldr     r9, [r7, #0x10]
    ldr_addr r0, SETTINGS_PTR
    ldr     r0, [r0]
    cmp     r0, #0
    beq     pg_lc_cdng_saved_max
    ldrb    r0, [r0, #0x5D5]
    cmp     r0, #0                       @ AutoRstFlg ignores saved maximum
    bne     pg_lc_cdng_take_ready
pg_lc_cdng_saved_max:
    ldr     r0, [r7, #0x2C]
    cmp     r0, r9
    movhi   r9, r0
pg_lc_cdng_take_ready:
    add     r9, r9, #1
    mov     r0, r7
    mov     r1, r9
    bl      pg_path_from_manager
    str     r8, [r10, #O_LC_VOLUME]
    str     r4, [r10, #O_LC_KIND]
    str     r5, [r10, #O_LC_TOKEN]
    str     r9, [r10, #O_LC_TAKE]
    mov     r0, #0
    str     r0, [r10, #O_LC_OPEN_TICKS]
    str     r0, [r10, #O_LC_COMMIT_POLLS]
    cmp     r6, #0                       @ first attach: stale TopFile baseline
    bne     pg_lc_cdng_baseline_ready
    bl      pg_top_hash
    str     r0, [r10, #O_LC_TOP_HASH]
pg_lc_cdng_baseline_ready:
    bic     r11, r11, #1
    str     r11, [r10, #O_LC_FLAGS]
    ldr     r0, [r10, #O_LC_GEN]
    add     r0, r0, #1
    str     r0, [r10, #O_LC_GEN]
    mov     r0, #1
    dmb     ish
    str     r0, [r10, #O_LC_STATE]
    b       pg_lc_out

pg_lc_publish_cancel:
    dmb     ish
    str     r6, [r10, #O_LC_STATE]
    b       pg_lc_out

pg_lc_cdng_pending:
    ldr     r0, [r10, #O_LC_KIND]
    cmp     r0, #1
    bne     pg_lc_final
    ldr     r0, [r10, #O_LC_TOKEN]
    cmp     r0, r5
    bne     pg_lc_final
    bl      pg_cdng_poll_top
    b       pg_lc_out

pg_lc_cdng_established:
    ldr     r0, [r10, #O_LC_KIND]
    cmp     r0, #1
    bne     pg_lc_final
    ldr     r0, [r10, #O_LC_TOKEN]
    cmp     r0, r5
    bne     pg_lc_final
    bl      pg_cdng_poll_top              @ stable change catches a missed gap
    b       pg_lc_out

/* MOV begin occurs after the deep open succeeds.  Its exact native pathInfo is
 * retained until ImageSave, so copy the basename and never infer at stop. */
pg_lc_mov:
    mov     r4, #2
    ldr_addr r0, MOV_PATHINFO_PTR
    ldr     r5, [r0]
    cmp     r5, #0
    beq     pg_lc_out
    add     r7, r5, #4
    mov     r8, r7                        @ last component seen
    mov     r9, #0x30
pg_lc_mov_scan:
    ldrb    r0, [r7], #1
    cmp     r0, #0
    beq     pg_lc_mov_scanned
    cmp     r0, #92
    moveq   r8, r7
    subs    r9, r9, #1
    bne     pg_lc_mov_scan
    b       pg_lc_out                     @ unterminated native path
pg_lc_mov_scanned:
    mov     r0, r8
    bl      pg_valid_id
    cmp     r0, #0
    beq     pg_lc_out

    ldr     r6, [r10, #O_LC_STATE]
    cmp     r6, #4
    beq     pg_lc_mov_compare
    cmp     r6, #0
    beq     pg_lc_publish_mov
    cmp     r6, #3
    bne     pg_lc_final                   @ supersede a pending CDNG safely
    tst     r11, #2
    bne     pg_lc_publish_mov
    ldr     r0, [r10, #O_LC_TOKEN]
    cmp     r0, r5
    bne     pg_lc_publish_mov
    mov     r0, r8
    bl      pg_id_matches_path
    cmp     r0, #0
    bne     pg_lc_out                     @ same stale MOV generation
    b       pg_lc_publish_mov

pg_lc_mov_compare:
    ldr     r0, [r10, #O_LC_KIND]
    cmp     r0, #2
    bne     pg_lc_final
    ldr     r0, [r10, #O_LC_TOKEN]
    cmp     r0, r5
    bne     pg_lc_final
    mov     r0, r8
    bl      pg_id_matches_path
    cmp     r0, #0
    bne     pg_lc_out
    b       pg_lc_final

pg_lc_publish_mov:
    /* Keep the exact native basename in registers across F_VOL.  pathInfo may
     * be reused in place at ImageSave or by a rapid next take; never copy from
     * that mutable object after the blocking lookup. */
    ldr     r9, [r8]
    ldr     r4, [r8, #4]
    ldr     r0, [r10, #S_FILE]
    cmp     r0, #0
    bne     pg_lc_out
    mov     r0, #6
    str     r0, [r10, #O_LC_STATE]
    dmb     ish
    ldr     r0, [r10, #S_FILE]
    cmp     r0, #0
    bne     pg_lc_publish_cancel
    bl      pg_current_volume
    mov     r7, r0
    cmp     r7, #1
    beq     pg_lc_mov_volume_ok
    cmp     r7, #5
    bne     pg_lc_publish_cancel
pg_lc_mov_volume_ok:
    bl      pg_lc_mov_still_same
    cmp     r0, #0
    beq     pg_lc_publish_cancel
    bl      pg_current_volume
    cmp     r0, r7                       @ reject a hotplug/route change mid-snapshot
    bne     pg_lc_publish_cancel
    bl      pg_lc_mov_still_same          @ the second lookup may also have blocked
    cmp     r0, #0
    beq     pg_lc_publish_cancel
    mov     r0, r9
    mov     r1, r4
    bl      pg_path_from_id
    str     r7, [r10, #O_LC_VOLUME]
    mov     r0, #2
    str     r0, [r10, #O_LC_KIND]
    str     r5, [r10, #O_LC_TOKEN]
    mov     r0, #0
    str     r0, [r10, #O_LC_TAKE]
    str     r0, [r10, #O_LC_OPEN_TICKS]
    str     r0, [r10, #O_LC_COMMIT_POLLS]
    bic     r11, r11, #2
    str     r11, [r10, #O_LC_FLAGS]
    ldr     r0, [r10, #O_LC_GEN]
    add     r0, r0, #1
    str     r0, [r10, #O_LC_GEN]
    mov     r0, #4
    dmb     ish
    str     r0, [r10, #O_LC_STATE]

pg_lc_out:
    pop     {r4, r5, r6, r7, r8, r9, r11, pc}

/* r5=pathInfo token, r8=basename pointer, r9/r4=latched basename words.
 * Returns one only while the native MOV object still names that exact clip. */
pg_lc_mov_still_same:
    ldr_addr r0, MOV_ACTIVE_PTR
    ldrb    r0, [r0]
    cmp     r0, #0
    moveq   r0, #0
    bxeq    lr
    ldr_addr r0, MOV_PATHINFO_PTR
    ldr     r0, [r0]
    cmp     r0, r5
    movne   r0, #0
    bxne    lr
    ldr     r0, [r8]
    cmp     r0, r9
    movne   r0, #0
    bxne    lr
    ldr     r0, [r8, #4]
    cmp     r0, r4
    movne   r0, #0
    bxne    lr
    mov     r0, #1
    bx      lr

/* First differing hash is only a candidate; a second identical 5 ms poll is
 * required so a partially copied TopFile cannot split a take. */
pg_cdng_poll_top:
    push    {r4, r5, r6, lr}
    ldr     r5, [r10, #O_LC_STATE]
    bl      pg_top_hash
    mov     r4, r0
    ldr     r0, [r10, #O_LC_TOP_HASH]
    cmp     r4, r0
    bne     pg_cdng_top_changed
    mov     r0, #0
    str     r0, [r10, #O_LC_COMMIT_POLLS]
    cmp     r5, #1
    bne     pg_cdng_top_out
    ldr     r0, [r10, #O_LC_OPEN_TICKS]
    add     r0, r0, #1
    str     r0, [r10, #O_LC_OPEN_TICKS]
    cmp     r0, #400                     @ bound failed XMP allocation to 2 s
    blo     pg_cdng_top_out
    b       pg_cdng_top_boundary
pg_cdng_top_changed:
    ldr     r0, [r10, #O_LC_COMMIT_POLLS]
    cmp     r0, r4
    beq     pg_cdng_top_stable
    str     r4, [r10, #O_LC_COMMIT_POLLS]
    b       pg_cdng_top_out
pg_cdng_top_stable:
    cmp     r5, #1
    bne     pg_cdng_top_boundary
    ldr_addr r0, TOP_FILE
    bl      pg_id_matches_path
    cmp     r0, #0
    beq     pg_cdng_top_boundary
    str     r4, [r10, #O_LC_TOP_HASH]
    mov     r0, #0
    str     r0, [r10, #O_LC_OPEN_TICKS]
    str     r0, [r10, #O_LC_COMMIT_POLLS]
    /* PGEN is the sole phase writer.  Attachment is a separate generation
     * latch, so promotion is an ordinary release publication. */
    mov     r0, #4
    dmb     ish
    str     r0, [r10, #O_LC_STATE]
    b       pg_cdng_top_out
pg_cdng_top_boundary:
    mov     r0, #3
    dmb     ish
    str     r0, [r10, #O_LC_STATE]
pg_cdng_top_out:
    pop     {r4, r5, r6, pc}

/* XMP falls before ImageSave/AddTakeNo.  Two observations after the manager
 * reaches the latched take replace the old blind one-second delay. */
pg_cdng_committed:
    push    {r4, r5, r6, lr}
    ldr     r0, [r10, #O_LC_VOLUME]
    bl      pg_manager_for_volume
    ldr     r4, [r0, #0x10]
    ldr     r5, [r10, #O_LC_TAKE]
    ldr     r1, [r10, #O_LC_COMMIT_POLLS]
    add     r1, r1, #1
    str     r1, [r10, #O_LC_COMMIT_POLLS]
    cmp     r4, r5
    blo     pg_cdng_commit_timeout
    cmp     r1, #2
    movhs   r0, #1
    movlo   r0, #0
    pop     {r4, r5, r6, pc}
pg_cdng_commit_timeout:
    cmp     r1, #400                     @ bounded catalog failure fallback
    movhs   r0, #1
    movlo   r0, #0
    pop     {r4, r5, r6, pc}

pg_current_volume:
    push    {r4, lr}
    ldr_addr ip, F_MGR
    blx     ip
    mov     r1, #0
    ldr_addr ip, F_VOL
    blx     ip
    pop     {r4, pc}

pg_manager_for_volume:
    cmp     r0, #5
    beq     pg_manager_ssd
    ldr_addr r0, PATH_MGR_SD
    bx      lr
pg_manager_ssd:
    ldr_addr r0, PATH_MGR_SSD
    bx      lr

/* r0=manager, r1=current take. */
pg_path_from_manager:
    push    {r4, r5, r6, lr}
    mov     r4, r0
    mov     r5, r1
    add     r6, r10, #O_PATH
    movw    r0, #0x475C
    movt    r0, #0x5259                 @ "\\GYR"
    str     r0, [r6]
    movw    r0, #0x5C4F                 @ "O\\"
    strh    r0, [r6, #4]
    ldrb    r0, [r4, #8]
    strb    r0, [r6, #6]
    add     r0, r6, #7
    ldr     r1, [r4, #0x0C]
    bl      pg_put_decimal_3
    mov     r0, #'_'
    strb    r0, [r6, #10]
    add     r0, r6, #11
    mov     r1, r5
    bl      pg_put_decimal_3
    b       pg_path_suffix

/* r0/r1 are the two latched words of an exact native Addd_ddd basename. */
pg_path_from_id:
    push    {r4, r5, r6, lr}
    mov     r4, r0
    mov     r5, r1
    add     r6, r10, #O_PATH
    movw    r0, #0x475C
    movt    r0, #0x5259
    str     r0, [r6]
    movw    r0, #0x5C4F
    strh    r0, [r6, #4]
    str     r4, [r6, #6]
    str     r5, [r6, #10]
pg_path_suffix:
    mov     r0, #'.'
    strb    r0, [r6, #14]
    mov     r0, #'G'
    strb    r0, [r6, #15]
    mov     r0, #'Y'
    strb    r0, [r6, #16]
    mov     r0, #'R'
    strb    r0, [r6, #17]
    mov     r0, #0
    strb    r0, [r6, #18]
    pop     {r4, r5, r6, pc}

pg_put_decimal_3:
    mov     r2, #'0'
pg_put_decimal_hundreds:
    cmp     r1, #100
    blo     pg_put_decimal_tens_start
    sub     r1, r1, #100
    add     r2, r2, #1
    b       pg_put_decimal_hundreds
pg_put_decimal_tens_start:
    strb    r2, [r0], #1
    mov     r2, #'0'
pg_put_decimal_tens:
    cmp     r1, #10
    blo     pg_put_decimal_ones
    sub     r1, r1, #10
    add     r2, r2, #1
    b       pg_put_decimal_tens
pg_put_decimal_ones:
    strb    r2, [r0], #1
    add     r1, r1, #'0'
    strb    r1, [r0]
    bx      lr

pg_top_hash:
    ldr_addr r1, TOP_FILE
    movw    r0, #5381
    mov     r2, #31
pg_top_hash_loop:
    ldrb    r3, [r1], #1
    add     r0, r0, r0, lsl #5
    eor     r0, r0, r3
    subs    r2, r2, #1
    bne     pg_top_hash_loop
    bx      lr

pg_valid_id:
    ldrb    r1, [r0]
    cmp     r1, #'A'
    blo     pg_valid_id_bad
    cmp     r1, #'Z'
    bhi     pg_valid_id_bad
    mov     r2, #1
pg_valid_id_reel:
    cmp     r2, #4
    beq     pg_valid_id_sep
    ldrb    r1, [r0, r2]
    cmp     r1, #'0'
    blo     pg_valid_id_bad
    cmp     r1, #'9'
    bhi     pg_valid_id_bad
    add     r2, r2, #1
    b       pg_valid_id_reel
pg_valid_id_sep:
    ldrb    r1, [r0, #4]
    cmp     r1, #'_'
    bne     pg_valid_id_bad
    mov     r2, #5
pg_valid_id_take:
    cmp     r2, #8
    beq     pg_valid_id_good
    ldrb    r1, [r0, r2]
    cmp     r1, #'0'
    blo     pg_valid_id_bad
    cmp     r1, #'9'
    bhi     pg_valid_id_bad
    add     r2, r2, #1
    b       pg_valid_id_take
pg_valid_id_good:
    mov     r0, #1
    bx      lr
pg_valid_id_bad:
    mov     r0, #0
    bx      lr

pg_id_matches_path:
    push    {r4, lr}
    add     r1, r10, #O_PATH
    add     r1, r1, #6
    mov     r2, #8
pg_id_compare:
    ldrb    r3, [r0], #1
    ldrb    r4, [r1], #1
    cmp     r3, r4
    bne     pg_id_no_match
    subs    r2, r2, #1
    bne     pg_id_compare
    mov     r0, #1
    pop     {r4, pc}
pg_id_no_match:
    mov     r0, #0
    pop     {r4, pc}
