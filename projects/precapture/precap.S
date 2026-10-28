/* PreCap -- 預錄連拍 as a loader v4 sup.
 *
 * Dev history: projects/precapture/ (P1 observer -> P4 shutter mute), on-camera
 * 2026-10-27.  This file is the shipped form: the same resident logic, but the
 * hooks are claimed through the loader (svc->claim) instead of the shared
 * AutoRun's cave, the state lives in the sup's own block, and the switch is a
 * row on the fpSup page (fpsup/precap_row.c, called from here).
 *
 * Behaviour (unchanged from the on-camera build):
 *   - key dispatch (C02DC108): S1 ON, and F_KIND(3) == 9 (high-speed
 *     continuous) -> raise pre-capture, inject S2 ON.  S1 OFF / S2 OFF / 10 s
 *     timeout -> give the ring back.
 *   - the two HIGHCONT frame hand-offs (C038F0E8 / C038F174): while
 *     pre-capturing, keep the newest 4 frames in a ring, one格 per 167 ms,
 *     replacing the newest格 inside the interval; nothing reaches YUV.
 *   - physical S2 ON while pre-capturing -> hand the ring to the firmware
 *     (C037AF20) in time order, then stop pre-capturing.
 *   - the SRec shutter-sound call (C03817D4): silent while pre-capturing.
 *
 * Position-independent: adr and pc-relative ldr only, no data section.  The
 * loader zeroes the rest of the block, so `pc_state` starts all zero.
 */
.syntax unified
.arm
.text

.equ SL4_HDR_LEN, 48                /* build_v4.SL4_HEADER_LEN */
.equ SL_OK,       0
.equ SL_KEEP,     0                 /* block stays: the fpSup page points into it */
.equ SL_RELEASE,  1                 /* drop the block (refusal) */
.equ SL_EXCL,     2

.equ SVC_CLAIM,   8
.equ SVC_PUBLISH, 24

.equ F_TICK_US,  0xC002B6E0
.equ F_KIND,     0xC0397B30
.equ F_KEYMON,   0xC02DBAF0
.equ F_ENQ,      0xC02DBBE8
.equ F_DISP,     0xC02DC138
.equ F_JOBDB,    0xC0374220
.equ F_JOBGET,   0xC03753C0
.equ F_CAP,      0xC03A4620
.equ F_REFUND,   0xC03A46B8
.equ F_RAWOBJ,   0xC0377348
.equ F_DROPRW,   0xC0377730
.equ F_DROPJB,   0xC0375030
.equ F_ENQUEUE,  0xC037AF20
.equ F_SOUND,    0xC03818F8
.equ F_ICACHE,   0xC000EABC
.equ SVC_CAVE,    20

.equ SITE_A,     0xC038F0E8
.equ SITE_B,     0xC038F174
.equ SITE_D,     0xC02DC108
.equ SITE_S,     0xC03817D4
.equ ORIG_A,     0xE12FFF33
.equ ORIG_B,     0xE12FFF33
.equ ORIG_D,     0xEB00000A
.equ ORIG_S,     0xEB000047

.equ OFFS_CODE,    SL4_HDR_LEN      /* code starts after the loader's header */
.equ OFFS_STATE,   (precap_state - precap_entry)
.equ OFFS_STUB_A, (stub_a - precap_entry)
.equ OFFS_STUB_B, (stub_b - precap_entry)
.equ OFFS_STUB_D, (disp_stub - precap_entry)
.equ OFFS_STUB_S, (mute_stub - precap_entry)

.equ VENEER_N,    4
.equ KEEP_N,      4
.equ TIMEOUT_US,  10000000
.equ INTERVAL,    167000
.equ JOB_RESV,    0xFFC
.equ JOB_ID,      0x10FC

/* the keep ring: {timestamp us, job id, yuv, site} */
.equ P_KEEP,      0x00
.equ P_COUNT_A,   0x40
.equ P_COUNT_B,   0x44
.equ P_SEQ,       0x48
.equ P_RING_N,    0x4C
.equ P_PRE,       0x50
.equ P_T0,        0x54
.equ P_TMO,       0x58
.equ P_INJ,       0x5C
.equ P_S1C,       0x60
.equ P_TMOF,      0x64
.equ P_DISP,      0x68
.equ P_GATE,      0x6C
.equ P_HELD,      0x70
.equ P_DROPPED,   0x74
.equ P_EVICTED,   0x78
.equ P_COMMITTED, 0x7C
.equ P_ABANDONED, 0x80
.equ P_ORIGIN,    0x84
.equ P_LOCK,      0x88
.equ P_HEAD,      0x8C
.equ P_N,         0x90
.equ P_MUTED,     0x94
.equ P_PLAYED,    0x98
.equ P_ON,        0x9C
.equ P_STATE_N,   0xA0
.equ PC_ROW_OFF,  0xA0

.macro LDA reg, value
    movw    \reg, #:lower16:(\value)
    movt    \reg, #:upper16:(\value)
.endm

/* ---- the sup's entry ------------------------------------------------------
 * stage2: r0 = block, r1 = svc.  Claim the four sites, build four 8-byte cave
 * veneers (loader v4's own shape: sloader4.c ui_early), patch each site with a
 * `bl veneer`, publish, then install the fpSup-page row. */
precap_entry:
    push    {r4-r11, lr}
    sub     sp, sp, #12                 /* scratch + keep SP 8-aligned */

    mov     r8, r0                      @ the block (for the page row)
    mov     r5, r1                      @ svc
    ldr     r9, [r1]                    @ svc->version: claim and page_add need v5+
    cmp     r9, #5
    blo     e_release
    LDA     r4, OFFS_STATE              @ the state lives past the code, not at
    add     r4, r8, r4                  @ the block's start: the header and the
                                        @ code occupy the first bytes.

    mov     r0, #1
    str     r0, [r4, #P_ON]             @ the switch: ON at every boot

    LDA     r1, SITE_A
    LDA     r2, ORIG_A
    bl      claim_one
    cmp     r0, #SL_OK
    bne     e_release
    LDA     r1, SITE_B
    LDA     r2, ORIG_B
    bl      claim_one
    cmp     r0, #SL_OK
    bne     e_release
    LDA     r1, SITE_D
    LDA     r2, ORIG_D
    bl      claim_one
    cmp     r0, #SL_OK
    bne     e_release
    LDA     r1, SITE_S
    LDA     r2, ORIG_S
    bl      claim_one
    cmp     r0, #SL_OK
    bne     e_release

    /* The block the loader gives us sits ~2 GB from the firmware, so `bl`
     * cannot reach the stubs.  Each site therefore gets `bl veneer` (the veneer
     * is the loader's cave, near the firmware and in reach) and the veneer does
     * `ldr pc, [pc, #-4]` + the stub's absolute address. */
    mov     r0, r5
    mov     r1, #(4 * 8)                @ four 8-byte veneers
    ldr     ip, [r5, #SVC_CAVE]
    blx     ip
    cmp     r0, #0
    beq     e_release
    mov     r7, r0                      @ the cave

    LDA     r9, 0xE51FF004              @ ldr pc, [pc, #-4]
    str     r9, [r7]
    str     r9, [r7, #8]
    str     r9, [r7, #16]
    str     r9, [r7, #24]
    LDA     r10, OFFS_CODE              @ the stubs are code, not state: reach
    add     r10, r8, r10                @ them from the block, plus the header
    LDA     r9, OFFS_STUB_A
    add     r9, r10, r9
    str     r9, [r7, #4]
    LDA     r9, OFFS_STUB_B
    add     r9, r10, r9
    str     r9, [r7, #12]
    LDA     r9, OFFS_STUB_D
    add     r9, r10, r9
    str     r9, [r7, #20]
    LDA     r9, OFFS_STUB_S
    add     r9, r10, r9
    str     r9, [r7, #28]

    LDA     r1, SITE_A
    mov     r2, r7
    bl      arm_site
    LDA     r1, SITE_B
    add     r2, r7, #8
    bl      arm_site
    LDA     r1, SITE_D
    add     r2, r7, #16
    bl      arm_site
    LDA     r1, SITE_S
    add     r2, r7, #24
    bl      arm_site

    mov     r0, r5
    ldr     ip, [r5, #SVC_PUBLISH]
    blx     ip
    LDA     ip, F_ICACHE
    blx     ip

    /* the fpSup-page row (optional: the hooks work without it) */
    LDA     r0, PC_ROW_OFF
    add     r0, r8, r0                  @ the row area, inside the block
    mov     r1, r4                      @ the state (what get/set poke at)
    mov     r2, r5
    bl      row_thunk

    mov     r0, #SL_KEEP                @ the row points into this block
    add     sp, sp, #12
    pop     {r4-r11, pc}
e_release:
    mov     r0, #SL_RELEASE
    add     sp, sp, #12
    pop     {r4-r11, pc}

/* claim(svc, addr, 4, &stock, SL_EXCL).  The 5th argument goes at [sp], so the
 * stock word sits one word above it and r3 points at it.  r5 = svc. */
claim_one:
    str     r2, [sp, #4]                @ the stock word
    mov     r3, #SL_EXCL
    str     r3, [sp]                    @ the 5th argument
    add     r3, sp, #4                  @ &stock
    mov     r0, r5
    mov     r2, #4
    mov     r6, lr                      @ blx clobbers lr; keep the return address
    ldr     ip, [r5, #SVC_CLAIM]
    blx     ip
    bx      r6

/* patch one site with `bl target`: r1 = site, r2 = target.
 * The displacement is (target - site - 8) / 4, a signed 24-bit field.  `asr`
 * keeps the sign, so the subsequent mask only has to drop the eight cond/opcode
 * bits. */
arm_site:
    sub     r2, r2, r1
    sub     r2, r2, #8
    asr     r2, r2, #2
    bic     r2, r2, #0xFF000000
    orr     r2, r2, #0xEB000000
    str     r2, [r1]
    bx      lr

/* ---- frame hooks ---------------------------------------------------------
 * r0 = Yuv, r1 = task id, r3 = the original enqueue.  Keep or drop the frame
 * while pre-capturing, otherwise tail-call the original. */
/* Every stub starts with `mov rX, pc` so the base can be derived without a
 * literal pool: in ARM, pc reads as the instruction's address + 8, so
 * `OFFS_<stub> + 8` is exactly the value in rX, measured from the code start. */
stub_a:
    mov     r5, pc
    push    {r0-r8, lr}
    mov     r4, #0
    LDA     r9, (OFFS_STUB_A + 8)
    b       frame_common
stub_b:
    mov     r5, pc
    push    {r0-r8, lr}
    mov     r4, #1
    LDA     r9, (OFFS_STUB_B + 8)
frame_common:
    sub     r5, r5, r9                  @ r5 = the code start
    LDA     r9, OFFS_CODE
    sub     r5, r5, r9                  @ r5 = the block
    LDA     r9, OFFS_STATE
    add     r5, r5, r9                  @ r5 = the state
    mov     r6, r1                      @ task id
    ldr     r7, [sp]                    @ Yuv
    LDA     ip, F_TICK_US
    blx     ip
    mov     r8, r0                      @ now

    add     r2, r5, r4, lsl #2
    ldr     r1, [r2, #P_COUNT_A]
    add     r1, r1, #1
    str     r1, [r2, #P_COUNT_A]
    ldr     r1, [r5, #P_SEQ]
    add     r1, r1, #1
    str     r1, [r5, #P_SEQ]

    ldr     r1, [r5, #P_PRE]
    cmp     r1, #0
    beq     f_pass

    bl      acquire
    ldr     r1, [r5, #P_PRE]
    cmp     r1, #0
    beq     f_rel_pass

    ldr     r1, [r5, #P_TMO]
    cmp     r1, #0
    bne     3f
    ldr     r2, [r5, #P_T0]
    sub     r2, r8, r2
    LDA     r3, TIMEOUT_US
    cmp     r2, r3
    blo     3f
    mov     r1, #1
    str     r1, [r5, #P_TMO]
    ldr     r1, [r5, #P_TMOF]
    add     r1, r1, #1
    str     r1, [r5, #P_TMOF]
    mov     r0, #0
    str     r0, [r5, #P_PRE]
    mov     r0, r6
    bl      drop_one
    ldr     r1, [r5, #P_ABANDONED]
    add     r1, r1, #1
    str     r1, [r5, #P_ABANDONED]
    bl      abandon_ring
    bl      release
    LDA     ip, F_KEYMON
    blx     ip
    mov     r1, #7
    LDA     ip, F_ENQ
    blx     ip
    b       f_skip
3:
    bl      keep_or_drop
    bl      release
    b       f_skip

f_rel_pass:
    bl      release
f_pass:
    pop     {r0-r8, lr}
    bx      r3
f_skip:
    pop     {r0-r8, lr}
    bx      lr

/* r5 = state, r8 = now, r6 = id, r7 = yuv, r4 = site */
keep_or_drop:
    push    {r4-r8, lr}
    ldr     r0, [r5, #P_N]
    cmp     r0, #0
    beq     k_add
    ldr     r1, [r5, #P_ORIGIN]
    sub     r1, r8, r1
    LDA     r2, INTERVAL
    cmp     r1, r2
    bhs     k_add
    /* inside the interval: replace the newest slot */
    ldr     r1, [r5, #P_HEAD]
    add     r1, r1, r0
    sub     r1, r1, #1
    and     r1, r1, #(KEEP_N - 1)
    add     r2, r5, #P_KEEP
    add     r2, r2, r1, lsl #4
    ldr     r0, [r2, #4]
    bl      drop_one
    ldr     r1, [r5, #P_DROPPED]
    add     r1, r1, #1
    str     r1, [r5, #P_DROPPED]
    ldr     r0, [r5, #P_N]
    ldr     r1, [r5, #P_HEAD]
    add     r1, r1, r0
    sub     r1, r1, #1
    and     r1, r1, #(KEEP_N - 1)
    b       k_store
k_add:
    ldr     r0, [r5, #P_N]
    cmp     r0, #KEEP_N
    bne     k_push
    ldr     r1, [r5, #P_HEAD]
    add     r2, r5, #P_KEEP
    add     r2, r2, r1, lsl #4
    ldr     r0, [r2, #4]
    bl      drop_one
    ldr     r1, [r5, #P_EVICTED]
    add     r1, r1, #1
    str     r1, [r5, #P_EVICTED]
    ldr     r1, [r5, #P_HEAD]
    add     r1, r1, #1
    and     r1, r1, #(KEEP_N - 1)
    str     r1, [r5, #P_HEAD]
    ldr     r0, [r5, #P_N]
    sub     r0, r0, #1
    str     r0, [r5, #P_N]
k_push:
    str     r8, [r5, #P_ORIGIN]
    ldr     r0, [r5, #P_N]
    ldr     r1, [r5, #P_HEAD]
    add     r1, r1, r0
    and     r1, r1, #(KEEP_N - 1)
    add     r0, r0, #1
    str     r0, [r5, #P_N]
    ldr     r0, [r5, #P_HELD]
    add     r0, r0, #1
    str     r0, [r5, #P_HELD]
k_store:
    add     r2, r5, #P_KEEP
    add     r2, r2, r1, lsl #4
    str     r8, [r2]
    str     r6, [r2, #4]
    str     r7, [r2, #8]
    str     r4, [r2, #12]
    pop     {r4-r8, pc}

/* ---- drop / commit the ring (caller holds the lock; r5 = state) ---------- */
abandon_ring:
    push    {r4-r8, lr}
    ldr     r4, [r5, #P_N]
    ldr     r6, [r5, #P_HEAD]
    mov     r8, #0
a_loop:
    cmp     r8, r4
    bhs     a_done
    add     r1, r6, r8
    and     r1, r1, #(KEEP_N - 1)
    add     r2, r5, #P_KEEP
    add     r2, r2, r1, lsl #4
    ldr     r0, [r2, #4]
    bl      drop_one
    ldr     r1, [r5, #P_ABANDONED]
    add     r1, r1, #1
    str     r1, [r5, #P_ABANDONED]
    add     r8, r8, #1
    b       a_loop
a_done:
    mov     r0, #0
    str     r0, [r5, #P_N]
    str     r0, [r5, #P_HEAD]
    pop     {r4-r8, pc}

commit_ring:
    push    {r4-r8, lr}
    ldr     r4, [r5, #P_N]
    ldr     r6, [r5, #P_HEAD]
    mov     r8, #0
c_loop:
    cmp     r8, r4
    bhs     c_done
    add     r1, r6, r8
    and     r1, r1, #(KEEP_N - 1)
    add     r2, r5, #P_KEEP
    add     r2, r2, r1, lsl #4
    ldr     r0, [r2, #8]
    ldr     r1, [r2, #4]
    bl      commit_one
    ldr     r1, [r5, #P_COMMITTED]
    add     r1, r1, #1
    str     r1, [r5, #P_COMMITTED]
    add     r8, r8, #1
    b       c_loop
c_done:
    mov     r0, #0
    str     r0, [r5, #P_N]
    str     r0, [r5, #P_HEAD]
    pop     {r4-r8, pc}

/* r0 = task id: the firmware's three-step "raw error" path, copied verbatim. */
drop_one:
    push    {r4, r5, r6, lr}
    mov     r4, r0
    cmp     r4, #0x60
    bhs     d9
    LDA     ip, F_JOBDB
    blx     ip
    mov     r5, r0
    mov     r1, r4
    LDA     ip, F_JOBGET
    blx     ip
    cmp     r0, #0
    beq     d9
    mov     r6, r0
    LDA     ip, F_CAP
    blx     ip
    movw    r1, #:lower16:JOB_RESV
    movt    r1, #:upper16:JOB_RESV
    ldr     r1, [r6, r1]
    mov     r2, #0
    LDA     ip, F_REFUND
    blx     ip
    LDA     ip, F_RAWOBJ
    blx     ip
    mov     r1, r4
    LDA     ip, F_DROPRW
    blx     ip
    mov     r0, r5
    mov     r1, r4
    mov     r6, #0
    LDA     ip, F_DROPJB
    blx     ip
d9: pop     {r4, r5, r6, pc}

/* r0 = yuv, r1 = task id */
commit_one:
    push    {r4, r5, r6, lr}
    mov     r4, r0
    mov     r5, r1
    cmp     r5, #0x60
    bhs     c9
    LDA     ip, F_JOBDB
    blx     ip
    mov     r1, r5
    LDA     ip, F_JOBGET
    blx     ip
    cmp     r0, #0
    beq     c9
    mov     r0, r4
    mov     r1, r5
    mov     r2, #1
    LDA     ip, F_ENQUEUE
    blx     ip
c9: pop     {r4, r5, r6, pc}

/* Single core: SWP is atomic across thread switches; ldrex/strex is not usable
 * through this assembler. */
acquire:
    add     r2, r5, #P_LOCK
    mov     r1, #1
0:  swp     r0, r1, [r2]
    cmp     r0, #0
    bne     0b
    bx      lr

release:
    mov     r0, #0
    str     r0, [r5, #P_LOCK]
    bx      lr

/* ---- key dispatch -------------------------------------------------------- */
disp_stub:
    mov     r7, pc
    push    {r4-r8, lr}
    mov     r4, r0                      @ keymon
    lsl     r5, r1, #0                  @ the key code stays in r5
    LDA     r9, (OFFS_STUB_D + 8)
    sub     r6, r7, r9                  @ the code start
    LDA     r9, OFFS_CODE
    sub     r6, r6, r9                  @ the block
    LDA     r9, OFFS_STATE
    add     r6, r6, r9                  @ the state

    ldr     r0, [r6, #P_DISP]
    add     r0, r0, #1
    str     r0, [r6, #P_DISP]

    cmp     r5, #4
    beq     d_s1
    cmp     r5, #5
    beq     d_s1off
    cmp     r5, #6
    beq     d_s2on
    cmp     r5, #7
    beq     d_s2off
    b       d_orig

d_s2on:
    ldr     r0, [r6, #P_PRE]
    cmp     r0, #0
    beq     d_orig
    mov     r0, #0
    str     r0, [r6, #P_PRE]
    mov     r5, r6
    bl      acquire
    bl      commit_ring
    bl      release
    mov     r5, #6
    b       d_orig

d_s2off:
    ldr     r0, [r6, #P_PRE]
    cmp     r0, #0
    beq     d_orig
    mov     r0, #0
    str     r0, [r6, #P_PRE]
    mov     r5, r6
    bl      acquire
    bl      abandon_ring
    bl      release
    mov     r5, #7
    b       d_orig

d_s1off:
    ldr     r0, [r6, #P_PRE]
    cmp     r0, #0
    beq     d_orig
    mov     r0, #0
    str     r0, [r6, #P_PRE]
    ldr     r0, [r6, #P_S1C]
    add     r0, r0, #1
    str     r0, [r6, #P_S1C]
    mov     r5, r6
    bl      acquire
    bl      abandon_ring
    bl      release
    mov     r0, r4
    mov     r1, #7
    LDA     ip, F_DISP
    blx     ip
    mov     r0, r4
    mov     r1, #5
    LDA     ip, F_DISP
    blx     ip
    b       d_done

d_s1:
    ldr     r0, [r6, #P_PRE]
    cmp     r0, #0
    bne     d_orig
    ldr     r0, [r6, #P_ON]             @ the fpSup-page switch
    cmp     r0, #0
    beq     d_orig

    mov     r0, #3
    mov     r1, #0
    LDA     ip, F_KIND
    blx     ip
    cmp     r0, #9
    beq     7f
    and     r2, r0, #0xFF
    orr     r2, r2, #0x100             @ gate: F_KIND is not 9
    b       d_refuse
7:  mov     r0, #1
    str     r0, [r6, #P_GATE]
    mov     r0, r4
    mov     r1, #4
    LDA     ip, F_DISP
    blx     ip
    mov     r5, r6
    bl      acquire
    mov     r0, #0
    str     r0, [r6, #P_N]
    str     r0, [r6, #P_HEAD]
    LDA     ip, F_TICK_US
    blx     ip
    str     r0, [r6, #P_T0]
    mov     r0, #1
    str     r0, [r6, #P_PRE]
    mov     r0, #0
    str     r0, [r6, #P_TMO]
    ldr     r0, [r6, #P_INJ]
    add     r0, r0, #1
    str     r0, [r6, #P_INJ]
    bl      release
    mov     r0, r4
    mov     r1, #6
    LDA     ip, F_DISP
    blx     ip
    b       d_done

d_refuse:
    str     r2, [r6, #P_GATE]
d_orig:
    mov     r0, r4
    mov     r1, r5
    LDA     ip, F_DISP
    blx     ip
d_done:
    pop     {r4-r8, pc}

/* ---- shutter sound ------------------------------------------------------- */
mute_stub:
    mov     r2, pc
    LDA     r3, (OFFS_STUB_S + 8)
    sub     r2, r2, r3                  @ the code start
    LDA     r3, OFFS_CODE
    sub     r2, r2, r3                  @ the block
    LDA     r3, OFFS_STATE
    add     r2, r2, r3                  @ the state
    ldr     r3, [r2, #P_PRE]
    cmp     r3, #0
    bne     m_mute
    ldr     r3, [r2, #P_PLAYED]
    add     r3, r3, #1
    str     r3, [r2, #P_PLAYED]
    LDA     ip, F_SOUND
    bx      ip
m_mute:
    ldr     r3, [r2, #P_MUTED]
    add     r3, r3, #1
    str     r3, [r2, #P_MUTED]
    bx      lr

/* ---- the fpSup-page row unit, compiled from precap_row.c ------------------ */
/* .incbin puts it in .text; ROW_INSTALL is precap_row_install's Thumb offset
 * inside that blob (the builder assembles the C first). */
.align 2
row_unit:
    .incbin ROW_BIN
.align 2
row_thunk:
    ldr     ip, row_target_rel
9:  add     ip, pc, ip
    bx      ip
row_target_rel:
    .word   row_unit + (ROW_INSTALL | 1) - (9b + 8)   @ bit0 = Thumb

/* ---- data, in .text so it travels with the code -------------------------- */
.align 2
precap_state:
    .space P_STATE_N
    .align 2
pc_name:
    .asciz  "PreCap"
    .align 2
row_space:
    .space 0x80
