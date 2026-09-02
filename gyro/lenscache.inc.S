/* Early JSON helpers for profilegen.S (r39b/r39d).
 *
 * Included into every PGEN build; only the native-lifecycle boundary watch
 * drives the early write.  Everything here runs in the writer task. */

/* r39b: the writer's 5 ms poll also keeps the lens cache warm while idle and
 * writes a take's JSON as soon as the take is established.  Both preserve
 * r4-r8; pg_build saves what it uses. */
pg_post_owner:                          /* r0 = 1 if this task may build/write a JSON now */
    ldr     r0, [r10, #S_POST_BUSY]
    cmp     r0, #1
    moveq   r0, #1
    bxeq    lr
    movw    r0, #:lower16:PG_LCACHE
    movt    r0, #:upper16:PG_LCACHE
    add     r0, r10, r0
    ldr     r0, [r0, #LC_EARLY]
    cmp     r0, #1
    moveq   r0, #1
    movne   r0, #0
    bx      lr

/* r0 = queue job -> r0 = 1 when that job's clip is the take whose JSON the
 * early write already produced (J_PATH equals O_PATH and the write succeeded). */
pg_json_early_done:
    push    {r4, r5, lr}
    movw    r4, #:lower16:PG_LCACHE
    movt    r4, #:upper16:PG_LCACHE
    add     r4, r10, r4
    ldr     r1, [r4, #LC_JSON_RES]
    cmp     r1, #0
    beq     8f
    add     r1, r0, #J_PATH
    add     r2, r10, #O_PATH
    mov     r3, #20
7:  ldrb    r5, [r1], #1
    ldrb    ip, [r2], #1
    cmp     r5, ip
    bne     8f
    subs    r3, r3, #1
    bne     7b
    ldr     r0, [r4, #LC_JSON_SKIP]
    add     r0, r0, #1
    str     r0, [r4, #LC_JSON_SKIP]
    mov     r0, #1
    pop     {r4, r5, pc}
8:  mov     r0, #0
    pop     {r4, r5, pc}

pg_json_early:
    push    {r4, r5, r6, r7, r8, lr}
    movw    r4, #:lower16:PG_LCACHE
    movt    r4, #:upper16:PG_LCACHE
    add     r4, r10, r4
    ldr     r0, [r4, #LC_MAGIC]
    ldr_addr r1, LC_MAGIC_V
    cmp     r0, r1
    beq     1f
    mov     r0, #0                      @ first sight of this pool: clear the block
    str     r0, [r4, #LC_JSON_GEN]
    str     r0, [r4, #LC_EARLY]
    str     r0, [r4, #LC_JSON_RES]
    str     r0, [r4, #LC_JSON_SEQ]
    str     r0, [r4, #LC_JSON_SKIP]
    str     r1, [r4, #LC_MAGIC]
1:
    ldr     r0, [r10, #S_ACTIVE]
    cmp     r0, #1
    bne     9f
    ldr     r0, [r10, #O_LC_STATE]
    cmp     r0, #4                      @ first DNG confirmed: the folder exists
    bne     9f
    ldr     r0, [r10, #S_FILE]
    cmp     r0, #2                      @ the gcsv is open
    bne     9f
    ldr     r0, [r10, #S_MODE_RUN]
    cmp     r0, #0                      @ the mode sampled at the first block
    beq     9f
    ldr     r0, [r10, #S_POST_BUSY]
    cmp     r0, #0
    bne     9f
    ldr     r0, [r4, #LC_JSON_GEN]
    ldr     r1, [r10, #O_LC_ATTACH]
    cmp     r0, r1
    beq     9f                          @ this take's JSON is already written
    ldr_addr ip, F_LENS_INFO
    blx     ip
    cmp     r0, #0
    beq     9f
    ldrb    r0, [r0, #LI_NAME]
    cmp     r0, #0x20
    blo     9f                          @ no lens name yet: the stop path will retry
    ldr     r0, [r10, #O_LC_ATTACH]
    str     r0, [r4, #LC_JSON_GEN]
    ldr     r0, [r10, #S_MODE_RUN]
    str     r0, [r10, #O_POST_MODE]
    mov     r0, #0
    str     r0, [r10, #O_POST_W]        @ pg_setting_dims fills these
    str     r0, [r10, #O_POST_H]
    ldr     r0, [r10, #O_LC_VOLUME]
    str     r0, [r10, #O_POST_VOLUME]
    mov     r0, #1
    str     r0, [r4, #LC_EARLY]
    bl      pg_build
    str     r0, [r4, #LC_JSON_RES]
    mov     r0, #0
    str     r0, [r4, #LC_EARLY]
    ldr     r0, [r10, #S_NEXTSEQ]
    str     r0, [r4, #LC_JSON_SEQ]
9:  pop     {r4, r5, r6, r7, r8, pc}

