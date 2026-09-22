pg_recovery_scan:
    push    {r3-r11, lr}
    movw    r4, #:lower16:O_READ
    movt    r4, #:upper16:O_READ
    add     r4, r10, r4                  @ four-byte directory wrapper
    add     r5, r4, #0x10                @ 0x238-byte directory entry
    movw    r6, #:lower16:O_TOP7
    movt    r6, #:upper16:O_TOP7
    add     r6, r10, r6                  @ seven {key,name[16]} records
    mov     r7, #0                       @ retained name count
    mov     r11, #0                      @ 0=failed, 1=open, 2=cancel, 3=created

    ldr     r0, [r10, #S_POST_BUSY]
    cmp     r0, #1
    bne     pg_recovery_cancel

    /* Follow the same currently routed movie volume as logger.S.  This is not
     * an SD-card enum: USB SSD recording may return a different media id. */
    ldr_addr ip, F_MGR
    blx     ip
    mov     r1, #0
    ldr_addr ip, F_VOL
    blx     ip
    str     r0, [r10, #O_POST_VOLUME]   @ bind every recovered job to this volume
    mov     r1, r0
    mov     r0, r4
    ldr_addr ip, F_DIR_CTOR
    blx     ip

    mov     r0, #0
    mov     r1, r5
    movw    r2, #0x238
1:  str     r0, [r1], #4
    subs    r2, r2, #4
    bne     1b

    /* Build "\\GYRO" in pool RAM so the directory API sees a normal pointer. */
    add     r1, r10, #O_POST_PATH
    movw    r0, #0x475C                  @ "\\G"
    strh    r0, [r1]
    movw    r0, #0x5259                  @ "YR"
    strh    r0, [r1, #2]
    mov     r0, #'O'
    strb    r0, [r1, #4]
    mov     r0, #0
    strb    r0, [r1, #5]
    mov     r0, r4
    ldr_addr ip, F_DIR_OPEN
    blx     ip
    cmp     r0, #0
    bne     pg_recovery_dir_open

    /* A fresh current volume may not have the logger directory yet.  Create
     * it using the same volume-bound directory object; an empty directory is a
     * completed scan, while a mkdir failure remains retryable. */
    mov     r0, r4
    add     r1, r10, #O_POST_PATH
    mov     r2, #0
    ldr_addr ip, F_DIR_MKDIR
    blx     ip
    cmp     r0, #0
    movne   r11, #3
    b       pg_recovery_dir_close

pg_recovery_dir_open:
    mov     r11, #1
pg_recovery_enum:
    ldr     r0, [r10, #S_POST_BUSY]
    cmp     r0, #1
    bne     pg_recovery_enum_cancel
    mov     r0, r4
    mov     r1, r5
    ldr_addr ip, F_DIR_NEXT
    blx     ip
    cmp     r0, #0
    beq     pg_recovery_dir_close
    ldr     r0, [r5, #0x218]
    tst     r0, #0x10                    @ never rank a directory
    bne     pg_recovery_enum
    ldr     r0, [r5, #0x234]
    cmp     r0, #0
    bne     pg_recovery_enum_rank       @ every >=4 GiB file clears the minimum
    ldr     r0, [r5, #0x230]
    cmp     r0, #192                     @ v4/v5 header+region + final footer
    blo     pg_recovery_enum
pg_recovery_enum_rank:
    mov     r0, r5
    bl      pg_name_key
    cmp     r0, #0
    beq     pg_recovery_enum
    mov     r1, r5
    mov     r2, r7
    mov     r3, r6
    bl      pg_top7_insert
    mov     r7, r0
    b       pg_recovery_enum

pg_recovery_enum_cancel:
    mov     r11, #2
pg_recovery_dir_close:
    mov     r0, r4
    mov     r1, #2
    ldr_addr ip, F_DIR_DTOR
    blx     ip
    cmp     r11, #0
    beq     pg_recovery_cancel
    cmp     r11, #2
    beq     pg_recovery_cancel
    cmp     r11, #3
    beq     pg_recovery_done

    /* O_TOP7 is intentionally outside O_READ, which each footer probe reuses. */
    mov     r8, #0
pg_recovery_loop:
    cmp     r8, r7
    bhs     pg_recovery_done
    ldr     r0, [r10, #S_POST_BUSY]
    cmp     r0, #1
    bne     pg_recovery_cancel
    add     r9, r8, r8, lsl #2
    add     r9, r6, r9, lsl #2          @ record = base + index * 20

    add     r2, r10, #O_POST_PATH
    movw    r0, #0x475C                  @ "\\G"
    strh    r0, [r2]
    movw    r0, #0x5259                  @ "YR"
    strh    r0, [r2, #2]
    movw    r0, #0x5C4F                  @ "O\\"
    strh    r0, [r2, #4]
    add     r1, r9, #4
    add     r2, r2, #6
    mov     r3, #13
2:  ldrb    r0, [r1], #1
    strb    r0, [r2], #1
    subs    r3, r3, #1
    bne     2b
    mov     r0, #0
    strb    r0, [r2]

    add     r0, r10, #O_POST_PATH
    bl      pg_queue_has_path
    cmp     r0, #0
    bne     pg_recovery_next

    ldr     r4, [r9]
    add     r0, r10, #O_POST_PATH
    lsr     r1, r4, #20                  @ camera letter
    ubfx    r2, r4, #10, #10            @ reel
    ubfx    r3, r4, #0, #10             @ clip
    bl      pg_probe_gyr
    mov     r4, r0
    ldr     r0, [r10, #S_POST_BUSY]
    cmp     r0, #1
    bne     pg_recovery_cancel
    cmp     r4, #0
    beq     pg_recovery_next
    and     r0, r4, #3
    cmp     r0, #3
    beq     pg_recovery_next

    ldr     r9, [r10, #S_POST_COUNT]
    cmp     r9, #Q_CAP
    bhs     pg_recovery_cancel            @ retry the scan after this queue drains
    add     r11, r10, #O_POST_QUEUE
    ldr     r0, [r11, #Q_HEAD]
    add     r0, r0, r9
    cmp     r0, #Q_CAP
    subhs   r0, r0, #Q_CAP
    add     r0, r0, r0, lsl #1
    add     r0, r11, r0, lsl #4
    add     r11, r0, #Q_JOBS
    str     r4, [r11, #J_FLAGS]
    mov     r0, #0
    str     r0, [r11, #J_ATTEMPTS]
    str     r0, [r11, #J_CLOSE_TICK]
    add     ip, r6, #0x90
    ldr     r0, [ip, #R_START]
    str     r0, [r11, #J_START_US]
    ldr     r0, [ip, #R_MODE]
    str     r0, [r11, #J_MODE]
    ldr     r0, [ip, #R_W]
    str     r0, [r11, #J_W]
    ldr     r0, [ip, #R_H]
    str     r0, [r11, #J_H]
    add     r1, r10, #O_POST_PATH
    add     r2, r11, #J_PATH
    mov     r3, #20
1:  ldrb    r0, [r1], #1
    strb    r0, [r2], #1
    subs    r3, r3, #1
    bne     1b
    add     r9, r9, #1
    dmb     ish
    str     r9, [r10, #S_POST_COUNT]

pg_recovery_next:
    add     r8, r8, #1
    b       pg_recovery_loop
pg_recovery_done:
    mov     r0, #2
    dmb     ish
    str     r0, [r10, #S_POOL_TRIED]
pg_recovery_cancel:
    pop     {r3-r11, pc}

/* Exact UTF-16LE "Addd_ddd.GYR" -> sortable camera/reel/clip key, or zero. */
pg_name_key:
    ldrh    r1, [r0]
    cmp     r1, #'A'
    blo     9f
    cmp     r1, #'Z'
    bhi     9f
    ldrh    ip, [r0, #8]
    cmp     ip, #'_'
    bne     9f
    ldrh    ip, [r0, #16]
    cmp     ip, #'.'
    bne     9f
    ldrh    ip, [r0, #18]
    cmp     ip, #'G'
    bne     9f
    ldrh    ip, [r0, #20]
    cmp     ip, #'Y'
    bne     9f
    ldrh    ip, [r0, #22]
    cmp     ip, #'R'
    bne     9f
    ldrh    ip, [r0, #24]
    cmp     ip, #0
    bne     9f

    mov     r2, #0
    mov     r3, #0
    ldrh    ip, [r0, #2]
    sub     ip, ip, #'0'
    cmp     ip, #9
    bhi     9f
    mov     r2, ip
    ldrh    ip, [r0, #4]
    sub     ip, ip, #'0'
    cmp     ip, #9
    bhi     9f
    add     r2, r2, r2, lsl #2
    add     r2, ip, r2, lsl #1
    ldrh    ip, [r0, #6]
    sub     ip, ip, #'0'
    cmp     ip, #9
    bhi     9f
    add     r2, r2, r2, lsl #2
    add     r2, ip, r2, lsl #1

    ldrh    ip, [r0, #10]
    sub     ip, ip, #'0'
    cmp     ip, #9
    bhi     9f
    mov     r3, ip
    ldrh    ip, [r0, #12]
    sub     ip, ip, #'0'
    cmp     ip, #9
    bhi     9f
    add     r3, r3, r3, lsl #2
    add     r3, ip, r3, lsl #1
    ldrh    ip, [r0, #14]
    sub     ip, ip, #'0'
    cmp     ip, #9
    bhi     9f
    add     r3, r3, r3, lsl #2
    add     r3, ip, r3, lsl #1

    lsl     r1, r1, #20
    orr     r0, r1, r2, lsl #10
    orr     r0, r0, r3
    bx      lr
9:  mov     r0, #0
    bx      lr

/* r0=key, r1=UTF-16 name, r2=count, r3=top base -> updated count.
 * Records remain descending; equal tuples are kept once. */
pg_top7_insert:
    push    {r4-r10, lr}
    mov     r4, r0
    mov     r5, r1
    mov     r6, r2
    mov     r7, r3
    mov     r8, #0
1:  cmp     r8, r6
    bhs     3f
    add     r9, r8, r8, lsl #2
    add     r9, r7, r9, lsl #2
    ldr     r0, [r9]
    cmp     r4, r0
    beq     8f
    bhi     3f
    add     r8, r8, #1
    b       1b
3:  cmp     r8, #Q_CAP
    bhs     8f
    mov     r10, r6
    cmp     r10, #Q_CAP
    addlo   r10, r10, #1
    sub     r0, r10, #1
4:  cmp     r0, r8
    bls     6f
    add     r9, r0, r0, lsl #2
    add     r9, r7, r9, lsl #2
    sub     r1, r9, #20
    mov     r2, #5
5:  ldr     r3, [r1], #4
    str     r3, [r9], #4
    subs    r2, r2, #1
    bne     5b
    sub     r0, r0, #1
    b       4b
6:  add     r9, r8, r8, lsl #2
    add     r9, r7, r9, lsl #2
    str     r4, [r9], #4
    mov     r2, #13
7:  ldrh    r3, [r5], #2
    strb    r3, [r9], #1
    subs    r2, r2, #1
    bne     7b
    mov     r0, r10
    pop     {r4-r10, pc}
8:  mov     r0, r6
    pop     {r4-r10, pc}

/* r0=path; return 1 if that immutable path is already queued. */
pg_queue_has_path:
    push    {r4-r8, lr}
    mov     r8, r0
    ldr     r6, [r10, #S_POST_COUNT]
    add     r4, r10, #O_POST_QUEUE
    ldr     r5, [r4, #Q_HEAD]
6:  cmp     r6, #0
    beq     9f
    add     r7, r5, r5, lsl #1
    add     r7, r4, r7, lsl #4
    add     r7, r7, #Q_JOBS+J_PATH
    mov     r0, #0
7:  ldrb    r1, [r8, r0]
    ldrb    r2, [r7, r0]
    cmp     r1, r2
    bne     8f
    add     r0, r0, #1
    cmp     r0, #19
    blo     7b
    mov     r0, #1
    pop     {r4-r8, pc}
8:  add     r5, r5, #1
    cmp     r5, #Q_CAP
    moveq   r5, #0
    sub     r6, r6, #1
    b       6b
9:  mov     r0, #0
    pop     {r4-r8, pc}

/* r0=GYR path, r1/r2/r3=expected camera/reel/clip.  Return recovered flags. */
pg_probe_gyr:
    push    {r3-r11, lr}
    mov     r4, r0
    mov     r5, r1
    mov     r6, r2
    mov     r7, r3
    mov     r0, #O_FOBJ
    mov     r1, r4
    mov     r2, #1
    bl      pg_open_file
    cmp     r0, #0
    beq     19f
    add     r0, r10, #O_FOBJ
    ldr_addr ip, F_OPEN_SIZE
    blx     ip
    cmn     r0, #1
    cmneq   r1, #1
    beq     18f
    mov     r8, r0
    rec_ptr ip
    str     r1, [ip, #R_SIZE_H]
    cmp     r1, #0
    bne     pg_probe_size_ok
    cmp     r0, #192
    blo     18f
pg_probe_size_ok:

    mov     r0, #0
    str     r0, [r10, #S_READ_N]
    add     r0, r10, #O_FOBJ
    movw    r1, #:lower16:O_READ
    movt    r1, #:upper16:O_READ
    add     r1, r10, r1
    mov     r2, #160
    add     r3, r10, #S_READ_N
    ldr_addr ip, F_READ
    blx     ip
    ldr     r0, [r10, #S_READ_N]
    cmp     r0, #160
    bne     18f
    movw    r9, #:lower16:O_READ
    movt    r9, #:upper16:O_READ
    add     r9, r10, r9
    ldr     r0, [r9]
    ldr_addr r1, 0x36534647             @ GFS6
    cmp     r0, r1
    bne     18f
    ldr     r0, [r9, #4]
    rec_ptr ip
    str     r0, [ip, #R_VER]
    cmp     r0, #5
    beq     pg_probe_v5_identity
    cmp     r0, #3                      @ v3/v4 use numeric identity words
    blo     18f
    cmp     r0, #4
    bhi     18f
    mov     r0, #1                       @ legacy formats are CDNG-only
    rec_ptr ip
    str     r0, [ip, #R_KIND]
    ldr     r0, [r9, #20]
    cmp     r0, r5
    bne     18f
    ldr     r0, [r9, #24]
    cmp     r0, r6
    bne     18f
    ldr     r0, [r9, #28]
    cmp     r0, r7
    bne     18f
    b       pg_probe_identity_ok

pg_probe_v5_identity:
    add     r0, r9, #20                 @ v5 stores TopFile's first 8 ASCII bytes
    add     r1, r10, #O_POST_PATH
    add     r1, r1, #6
    mov     r2, #8
pg_probe_v5_compare:
    ldrb    r3, [r0], #1
    ldrb    ip, [r1], #1
    cmp     r3, ip
    bne     18f
    subs    r2, r2, #1
    bne     pg_probe_v5_compare
    ldrb    r0, [r9, #28]                @ explicit recording volume
    ldr     r1, [r10, #O_POST_VOLUME]
    cmp     r0, r1
    bne     18f
    ldrb    r0, [r9, #29]                @ 1 CDNG, 2 MOV
    cmp     r0, #1
    blo     18f
    cmp     r0, #2
    bhi     18f
    rec_ptr ip
    str     r0, [ip, #R_KIND]
pg_probe_identity_ok:
    ldr     r0, [r9, #16]
    rec_ptr ip
    str     r0, [ip, #R_START]
    str     r0, [r10, #O_POST_START]    @ marker validation uses this snapshot

    subs    r1, r8, #32
    ldr     r2, [ip, #R_SIZE_H]
    sbc     r2, r2, #0
    add     r0, r10, #O_FOBJ
    ldr_addr ip, F_SEEK
    blx     ip
    cmp     r0, #0
    beq     18f
    mov     r0, #0
    str     r0, [r10, #S_READ_N]
    add     r0, r10, #O_FOBJ
    add     r1, r9, #160
    mov     r2, #32
    add     r3, r10, #S_READ_N
    ldr_addr ip, F_READ
    blx     ip
    ldr     r0, [r10, #S_READ_N]
    cmp     r0, #32
    bne     18f
    add     r11, r9, #160
    ldr     r0, [r11]
    ldr_addr r1, 0x36454647             @ GFE6
    cmp     r0, r1
    bne     18f
    ldr     r0, [r11, #20]
    rec_ptr ip
    str     r0, [ip, #R_MODE]
    ldr     r0, [r11, #24]
    str     r0, [ip, #R_W]
    ldr     r0, [r11, #28]
    str     r0, [ip, #R_H]
    mov     r0, #O_FOBJ
    bl      pg_close_file

    movw    r8, #0
    movt    r8, #0x8000                 @ recovered selector
    ldr     r0, [r10, #O_POST_VOLUME]
    orr     r8, r8, r0, lsl #8
    rec_ptr ip
    ldr     r0, [ip, #R_KIND]
    orr     r8, r8, r0, lsl #16
    cmp     r0, #2
    orreq   r8, r8, #3                   @ keep MOV GYR; no guessed sidecar path
    beq     17f
    mov     r0, #'G'
    bl      pg_marker_valid
    cmp     r0, #0
    beq     13f
    ldr_addr r0, 0x76736367             @ "gcsv"
    bl      pg_cinema_path
    add     r0, r10, #O_GCSV_PATH
    bl      pg_file_nonempty
    cmp     r0, #0
    orrne   r8, r8, #1
13:
    rec_ptr ip
    ldr     r0, [ip, #R_VER]
    cmp     r0, #3
    orreq   r8, r8, #2                  @ v3 has no persisted lens region
    beq     17f
    ldr     r0, [ip, #R_W]
    cmp     r0, #0
    orreq   r8, r8, #2                  @ zero geometry: GCSV only
    beq     17f
    ldr     r0, [ip, #R_H]
    cmp     r0, #0
    orreq   r8, r8, #2
    beq     17f
    mov     r0, #'J'
    bl      pg_marker_valid
    cmp     r0, #0
    beq     17f
    ldr_addr r0, 0x6E6F736A             @ "json"
    bl      pg_cinema_path
    add     r0, r10, #O_GCSV_PATH
    bl      pg_file_nonempty
    cmp     r0, #0
    orrne   r8, r8, #2
17: mov     r0, r8
    pop     {r3-r11, pc}
18: mov     r0, #O_FOBJ
    bl      pg_close_file
19: mov     r0, #0
    pop     {r3-r11, pc}

/* Shared file-object helpers. */
pg_open_file:
    push    {r4-r8, lr}
    mov     r4, r0
    mov     r5, r1
    mov     r6, r2
    ldr     r0, [r10, #S_POST_BUSY]
    cmp     r0, #1
    bne     pg_open_no_volume
    ldr     r1, [r10, #O_POST_VOLUME]
    cmp     r1, #1
    beq     pg_open_volume_ok
    cmp     r1, #5
    bne     pg_open_no_volume
pg_open_volume_ok:
    add     r0, r10, r4
    ldr_addr ip, F_CTOR
    blx     ip
    add     r0, r10, r4
    mov     r1, r5
    mov     r2, r6
    ldr_addr ip, F_OPEN
    blx     ip
    cmp     r0, #0
    popne   {r4-r8, pc}
    add     r0, r10, r4
    mov     r1, #2
    ldr_addr ip, F_DTOR
    blx     ip
    mov     r0, #0
    pop     {r4-r8, pc}
pg_open_no_volume:
    mov     r0, #0
    pop     {r4-r8, pc}

pg_close_file:
    push    {r4, lr}
    mov     r4, r0
    add     r0, r10, r4
    ldr_addr ip, F_CLOSE
    blx     ip
    add     r0, r10, r4
    mov     r1, #2
    ldr_addr ip, F_DTOR
    blx     ip
    pop     {r4, pc}

/* r0='G' or 'J'; build \\GYRO\\clip.GOK/JOK in O_WORK. */
pg_marker_path:
    movw    r1, #:lower16:O_WORK
    movt    r1, #:upper16:O_WORK
    add     r1, r10, r1
    add     r2, r10, #O_POST_PATH
    mov     r3, #19
20: ldrb    ip, [r2], #1
    strb    ip, [r1], #1
    subs    r3, r3, #1
    bne     20b
    movw    r1, #:lower16:O_WORK
    movt    r1, #:upper16:O_WORK
    add     r1, r10, r1
    strb    r0, [r1, #15]
    movw    r2, #0x4B4F                 @ "OK"
    strh    r2, [r1, #16]
    mov     r2, #0
    strb    r2, [r1, #18]
    bx      lr

/* Validate the 8-byte marker: kind,"OK4",start_us. */
pg_marker_valid:
    push    {r4-r8, lr}
    mov     r4, r0
    bl      pg_marker_path
    mov     r0, #O_FOBJ
    mov     r2, #1
    bl      pg_open_file
    cmp     r0, #0
    beq     24f
    mov     r0, #0
    str     r0, [r10, #S_READ_N]
    add     r0, r10, #O_FOBJ
    movw    r1, #:lower16:O_WORK+0x20
    movt    r1, #:upper16:O_WORK+0x20
    add     r1, r10, r1
    mov     r2, #8
    add     r3, r10, #S_READ_N
    ldr_addr ip, F_READ
    blx     ip
    mov     r0, #O_FOBJ
    bl      pg_close_file
    ldr     r0, [r10, #S_READ_N]
    cmp     r0, #8
    bne     24f
    movw    r5, #:lower16:O_WORK+0x20
    movt    r5, #:upper16:O_WORK+0x20
    add     r5, r10, r5
    ldrb    r0, [r5]
    cmp     r0, r4
    bne     24f
    ldrb    r0, [r5, #1]
    cmp     r0, #'O'
    bne     24f
    ldrb    r0, [r5, #2]
    cmp     r0, #'K'
    bne     24f
    ldrb    r0, [r5, #3]
    cmp     r0, #'4'
    bne     24f
    ldr     r0, [r5, #4]
    ldr     r1, [r10, #O_POST_START]
    cmp     r0, r1
    moveq   r0, #1
    movne   r0, #0
    pop     {r4-r8, pc}
24: mov     r0, #0
    pop     {r4-r8, pc}

/* Commit one successful stage, then read it back before publishing RAM flags. */
pg_marker_write:
    push    {r4-r8, lr}
    mov     r4, r0
    bl      pg_marker_path
    movw    r5, #:lower16:O_WORK+0x20
    movt    r5, #:upper16:O_WORK+0x20
    add     r5, r10, r5
    strb    r4, [r5]
    movw    r0, #0x4B4F                 @ "OK"
    strh    r0, [r5, #1]
    mov     r0, #'4'
    strb    r0, [r5, #3]
    ldr     r0, [r10, #O_POST_START]
    str     r0, [r5, #4]
    mov     r0, #O_FOBJ
    mov     r2, #7
    bl      pg_open_file
    cmp     r0, #0
    beq     27f
    add     r0, r10, #O_FOBJ
    mov     r1, r5
    mov     r2, #8
    ldr_addr ip, F_WRITE
    blx     ip
    mov     r6, r0
    mov     r0, #O_FOBJ
    bl      pg_close_file
    cmp     r6, #0
    beq     27f
    ldr     r0, [r10, #S_POST_BUSY]
    cmp     r0, #1
    bne     27f
    mov     r0, r4
    bl      pg_marker_valid
    pop     {r4-r8, pc}
27: mov     r0, #0
    pop     {r4-r8, pc}

/* r0=path; return 1 only for a non-empty target. */
pg_file_nonempty:
    push    {r4-r8, lr}
    mov     r4, r0
    mov     r0, #O_FOBJ
    mov     r1, r4
    mov     r2, #1
    bl      pg_open_file
    cmp     r0, #0
    beq     29f
    add     r0, r10, #O_FOBJ
    ldr_addr ip, F_OPEN_SIZE
    blx     ip
    mov     r5, r0
    mov     r6, r1
    mov     r0, #O_FOBJ
    bl      pg_close_file
    cmn     r5, #1                       @ missing/error is exactly -1:-1
    cmneq   r6, #1
    moveq   r0, #0
    beq     30f
    orrs    r0, r5, r6
    movne   r0, #1
    moveq   r0, #0
30: pop     {r4-r8, pc}
29: mov     r0, #0
    pop     {r4-r8, pc}

/* Recovered JSON must not borrow metadata from a lens mounted after the take.
 * The v4/v5 GYR persists 96 bytes from LENS_REGION at file offset 64.  Compare
 * the stable first 68 bytes exactly at build time; this is the fingerprint
 * gate, not a scan-time hint that could become stale after a lens swap. */
pg_lens_region_matches:
    push    {r4-r8, lr}
    mov     r0, #O_FOBJ
    add     r1, r10, #O_POST_PATH
    mov     r2, #1
    bl      pg_open_file
    cmp     r0, #0
    beq     34f
    mov     r0, #0
    str     r0, [r10, #S_READ_N]
    add     r0, r10, #O_FOBJ
    movw    r1, #:lower16:O_READ
    movt    r1, #:upper16:O_READ
    add     r1, r10, r1
    mov     r2, #132                    @ header 64 + stable fingerprint 68
    add     r3, r10, #S_READ_N
    ldr_addr ip, F_READ
    blx     ip
    mov     r0, #O_FOBJ
    bl      pg_close_file
    ldr     r0, [r10, #S_POST_BUSY]
    cmp     r0, #1
    bne     34f
    ldr     r0, [r10, #S_READ_N]
    cmp     r0, #132
    bne     34f
    movw    r4, #:lower16:O_READ
    movt    r4, #:upper16:O_READ
    add     r4, r10, r4
    ldr     r0, [r4]
    ldr_addr r1, 0x36534647             @ GFS6
    cmp     r0, r1
    bne     34f
    ldr     r0, [r4, #4]
    cmp     r0, #4
    blo     34f
    cmp     r0, #5
    bhi     34f
    add     r4, r4, #64
    ldr_addr r5, LENS_REGION
    mov     r6, #68
33: ldrb    r0, [r4], #1
    ldrb    r1, [r5], #1
    cmp     r0, r1
    bne     34f
    subs    r6, r6, #1
    bne     33b
    mov     r0, #1
    pop     {r4-r8, pc}
34: mov     r0, #0
    pop     {r4-r8, pc}

/* r5 = queue job.  Copy every field generators use out of the ring before
 * calling either of them; the callback is then free to prepare the next take. */
