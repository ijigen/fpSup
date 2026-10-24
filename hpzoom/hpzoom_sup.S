/* ============================================================================
 * HpZoom -- half-press magnification for manual lenses, as a Loader v3 sup.
 *
 * For a lens with no electronic contacts the stock camera magnifies only
 * after the OK button, and a half-press of the shutter (S1) cancels the
 * magnification.  This sup reverses that for manual focus: in MF mode with
 * Auto Magnification OFF, S1 half-press turns magnification on and releasing
 * S1 turns it off.  While magnified, the live view is switched to B&W so
 * focus peaking stands out; the still capture stays colour.
 *
 * Mechanism (proven on camera, 2026-10-01, firmware 5.02):
 *
 *   - post_hook (event poster, after its queue push): on S1-down with the
 *     zoom machine pre-event in Normal, post the magnify-toggle event (OK).
 *     The same S1-down is already queued, and the stock magnify behaviour
 *     ("S1 while magnified unmagnifies") does the release side for free:
 *     S1-down while NOT magnified posts OK (magnify on); S1-down while
 *     magnified is left alone (stock turns it off).  Gates: FocusMode == MF
 *     (0xC0059D18) and CM_MFMAG_AutoMagnify == OFF (0xC31B3774) -- ON means an
 *     electronic lens, where native auto-magnify keeps working.
 *   - poster_hook (event poster entry): on S1-down records the pre-queue zoom
 *     state; on S2-down writes the colour fields into the live monofilter
 *     records (the capture pipe inherits them, so the still is colour) and
 *     inhibits the per-frame assert until S2-up.
 *   - cs_hook (change_state entry): captures the zoom machine pointer.
 *   - apply_hook (live-view applier, ~200/s): while the zoom machine is in
 *     MfZoom (state 4; full-screen and PIP alike) re-asserts the grayscale
 *     fields into BOTH live records at 0xC341399C+0x10/+0x1b0.  The pipe
 *     consumes them every frame, so the magnify reconfig's colour write is
 *     overwritten within a frame -- no commit, no extra reconfig.
 *
 * Dead window: the first S1 press after a cold boot predates cs_hook's
 * capture of the machine pointer (change_state runs after the hooks arm,
 * the camera reached Normal before it).  cap_machine == 0 then implies "not
 * in MfZoom", so post_hook also posts when pre_zoom == 0xFFFFFFFF.
 *
 * All four sites are insertion hooks entered by `bl`; each body ends by
 * replaying the displaced instruction, or -- when a CHAIN layer was below at
 * load -- by jumping to that layer (which replays instead).  Claims first,
 * writes last, SL_RELEASE with nothing written on any refusal.
 * ========================================================================== */
.syntax unified
.arm
.text

.equ SVC_CLAIM,   8                 /* struct sl_svc (fp_usb_shell/v3/sloader.h) */
.equ SVC_NEXT,    16
.equ SVC_CAVE,    20
.equ SVC_PUBLISH, 24
.equ SVC_LOG,     28
.equ SL_CHAIN,    1

.equ F_POSTER,     0xC02DBBE8       /* poster(singleton, code): queue push */
.equ F_GETCTX,     0xC0057AE8       /* () -> settings context */
.equ F_GETFM,      0xC0059D18       /* (ctx) -> focus mode; 2 = MF */
.equ AUTOMAG_CELL, 0xC31B3774       /* CM_MFMAG_AutoMagnify storage; 0 = OFF */
.equ PIC_STRUCT,   0xC341399C       /* pic module struct; live records at
                                     * +0x10 and +0x1b0 (416 bytes each) */

.equ EVT_S1_DOWN,  0x04
.equ EVT_S1_UP,    0x05
.equ EVT_S2_DOWN,  0x06
.equ EVT_S2_UP,    0x07
.equ EVT_OK,       0x1C             /* the magnify-toggle button event */

.equ SITE_POSTER,  0xC02DBBF0       /* poster +4:  mov r4, r0 */
.equ STOCK_POSTER, 0xE1A04000
.equ SITE_CS,      0xC04819DC       /* change_state +4: mov r4, r0 */
.equ STOCK_CS,     0xE1A04000
.equ SITE_POST,    0xC02DBC10       /* poster +40, after the push: add sp, sp, #4 */
.equ STOCK_POST,   0xE28DD004
.equ SITE_APPLY,   0xC02BAD0C       /* live-view applier +4: sub sp, sp, #0x64 */
.equ STOCK_APPLY,  0xE24DD064

.equ VENEER_LDR,   0xE51FF004       /* ldr pc, [pc, #-4] */
.equ CAVE_BYTES,   32               /* four veneers */

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

/* The address of a label in this block: a pc-relative word, so any distance
 * assembles (adr's immediate runs out past the hook bodies).  Unique macro
 * labels (\@): the hook bodies use the small numeric labels themselves. */
.macro REL reg, label
    ldr     \reg, .Lrel_lit\@
.Lrel_add\@:
    add     \reg, pc, \reg
    b       .Lrel_done\@
.Lrel_lit\@:
    .word   \label - .Lrel_add\@ - 8
.Lrel_done\@:
.endm

/* write the pattern-2 grayscale scalar fields into both live records.
 * r3 = PIC_STRUCT.  Clobbers r1, r2. */
.macro WRITE_GRAY
    mov     r1, #1
    mov     r2, #0
    str     r1, [r3, #0x40]     @ A +0x30
    str     r1, [r3, #0xac]     @ A +0x9c
    strb    r2, [r3, #0xb0]     @ A +0xa0
    str     r2, [r3, #0x128]    @ A +0x118
    strb    r1, [r3, #0x104]    @ A +0xf4
    strb    r1, [r3, #0x12c]    @ A +0x11c
    strb    r1, [r3, #0x12e]    @ A +0x11e
    strb    r1, [r3, #0x12f]    @ A +0x11f
    str     r1, [r3, #0x1e0]    @ B +0x30
    str     r1, [r3, #0x24c]    @ B +0x9c
    strb    r2, [r3, #0x250]    @ B +0xa0
    str     r2, [r3, #0x2c8]    @ B +0x118
    strb    r1, [r3, #0x2a4]    @ B +0xf4
    strb    r1, [r3, #0x2cc]    @ B +0x11c
    strb    r1, [r3, #0x2ce]    @ B +0x11e
    strb    r1, [r3, #0x2cf]    @ B +0x11f
.endm

/* write the pattern-0 colour scalar fields into both live records.
 * r3 = PIC_STRUCT.  Clobbers r1, r2. */
.macro WRITE_COLOR
    mov     r1, #1
    mov     r2, #0
    str     r2, [r3, #0x40]     @ A +0x30
    str     r2, [r3, #0xac]     @ A +0x9c
    str     r2, [r3, #0x128]    @ A +0x118
    strb    r2, [r3, #0x104]    @ A +0xf4
    strb    r2, [r3, #0x12e]    @ A +0x11e
    strb    r2, [r3, #0x12f]    @ A +0x11f
    strb    r1, [r3, #0x12c]    @ A +0x11c
    str     r2, [r3, #0x1e0]    @ B +0x30
    str     r2, [r3, #0x24c]    @ B +0x9c
    str     r2, [r3, #0x2c8]    @ B +0x118
    strb    r2, [r3, #0x2a4]    @ B +0xf4
    strb    r2, [r3, #0x2ce]    @ B +0x11e
    strb    r2, [r3, #0x2cf]    @ B +0x11f
    strb    r1, [r3, #0x2cc]    @ B +0x11c
.endm

/* A CHAIN layer below an insertion site: remember where the site's branch
 * goes now, and replace our replay of the stock instruction with a jump to
 * that layer (which replays instead).  0: we are the first layer. */
.macro LAYER site, replay, nextw, altw
    mov     r0, r10
    LDA     r1, \site
    mov     r2, #0                      @ ARM
    ldr     ip, [r10, #SVC_NEXT]
    blx     ip
    cmp     r0, #0
    beq     3f
    REL     r1, \nextw
    str     r0, [r1]
    REL     r1, \replay
    REL     r2, \altw
    ldr     r2, [r2]
    str     r2, [r1]
3:
.endm

/* ------------------------------------------------------------------- entry */
entry:                              @ (block = r0, svc = r1, path = r2)
    push    {r4, r5, r6, r7, r8, r9, r10, lr}
    mov     r10, r1                     @ the service table

    /* 1. claim every site; any refusal -> SL_RELEASE, nothing written */
    REL     r6, claims
    ldr     r7, [r6], #4
1:  ldr     r1, [r6]                    @ address
    mov     r2, #4
    add     r3, r6, #4                  @ its stock word, from this table
    ldr     r0, [r6, #8]                @ kind: the fifth argument
    sub     sp, sp, #8
    str     r0, [sp]
    mov     r0, r10
    ldr     ip, [r10, #SVC_CLAIM]
    blx     ip
    add     sp, sp, #8
    cmp     r0, #0
    bne     out
    add     r6, r6, #12
    subs    r7, r7, #1
    bne     1b

    /* 2. the layers below.  A claim put every first-claimed site back to
     * stock, so a site that branches now was written by a sup loaded before
     * this one, this boot. */
    LAYER   SITE_POSTER, poster_replay, poster_next, alt_poster
    LAYER   SITE_CS,     cs_replay,     cs_next,     alt_cs
    LAYER   SITE_POST,   post_replay,   post_next,   alt_post
#ifndef NO_BW
    LAYER   SITE_APPLY,  apply_replay,  apply_next,  alt_apply
#endif

    /* 3. the veneers */
    mov     r0, r10
    mov     r1, #CAVE_BYTES
    ldr     ip, [r10, #SVC_CAVE]
    blx     ip
    movs    r8, r0
    beq     out
    LDA     r0, VENEER_LDR
    str     r0, [r8, #0]
    REL     r1, poster_hook
    str     r1, [r8, #4]
    str     r0, [r8, #8]
    REL     r1, cs_hook
    str     r1, [r8, #12]
    str     r0, [r8, #16]
    REL     r1, post_hook
    str     r1, [r8, #20]
#ifndef NO_BW
    str     r0, [r8, #24]
    REL     r1, apply_hook
    str     r1, [r8, #28]
#endif

    /* the code and the patched replays first, publish, arm the sites last */
    mov     r0, r10
    ldr     ip, [r10, #SVC_PUBLISH]
    blx     ip
    LDA     r0, SITE_POSTER
    add     r1, r8, #0
    bl      encode_bl
    LDA     r0, SITE_CS
    add     r1, r8, #8
    bl      encode_bl
    LDA     r0, SITE_POST
    add     r1, r8, #16
    bl      encode_bl
#ifndef NO_BW
    LDA     r0, SITE_APPLY
    add     r1, r8, #24
    bl      encode_bl
#endif
    mov     r0, r10
    ldr     ip, [r10, #SVC_PUBLISH]
    blx     ip

    mov     r0, r10
    REL     r1, log_s
    ldr     ip, [r10, #SVC_LOG]
    blx     ip

    mov     r0, #0                      @ SL_KEEP
    pop     {r4, r5, r6, r7, r8, r9, r10, pc}
out:
    mov     r0, #1                      @ SL_RELEASE
    pop     {r4, r5, r6, r7, r8, r9, r10, pc}

/* encode_bl: [r0] = bl r1.  Signed displacement: the veneer may lie below
 * the site.  Clobbers r3. */
encode_bl:
    sub     r3, r1, r0
    sub     r3, r3, #8
    asr     r3, r3, #2
    bic     r3, r3, #0xFF000000
    orr     r3, r3, #0xEB000000
    str     r3, [r0]
    bx      lr

/* read_zoom() -> r0 = current zoom state id, or 0xFFFFFFFF.
 * machine = cap_machine; current ref = [machine+4]; id = [ref].
 * Every hop range-checked.  Clobbers r0, r1. */
read_zoom:
    push    {lr}
    REL     r0, cap_machine
    ldr     r0, [r0]
    bl      sane
    beq     9f
    ldr     r0, [r0, #4]
    bl      sane
    beq     9f
    ldr     r0, [r0]
    pop     {pc}
9:  mov     r0, #0xFFFFFFFF
    pop     {pc}

/* sane(r0): Z clear when r0 names camera RAM we will dereference.
 * Clobbers the flags only. */
sane:
    cmp     r0, #0xC0000000
    blo     1f
    LDA     ip, 0xC4000000
    cmp     r0, ip
    blo     2f
1:  movs    r0, #0
2:  bx      lr

/* --------------------------------------------------------------- the hooks */

/* poster_hook(singleton, code) -- 0xC02DBBF0, one instruction past the
 * poster's prologue; lr = site+4 from the patching bl.  On S1-down records
 * the pre-queue zoom state (the consumer has not seen this event yet).  On
 * S2-down writes the colour fields into the live records (the capture pipe
 * builds later and inherits them) and inhibits the per-frame assert until
 * S2-up.  Displaced: mov r4, r0. */
poster_hook:
    push    {r0, r1, r2, r3, ip, lr}
#ifndef NO_BW
    cmp     r1, #EVT_S2_DOWN
    beq     5f
    cmp     r1, #EVT_S2_UP
    beq     7f
#endif
    cmp     r1, #EVT_S1_DOWN
    bne     9f
    bl      read_zoom
    REL     r3, pre_zoom
    str     r0, [r3]
    b       9f
#ifndef NO_BW
5:  @ S2 down: capture imminent -- colour the live records, stop asserting.
    mov     r2, #2
    REL     r3, bw_state
    str     r2, [r3]
    LDA     r3, PIC_STRUCT
    WRITE_COLOR
    b       9f
7:  @ S2 up: re-arm.
    mov     r2, #0
    REL     r3, bw_state
    str     r2, [r3]
#endif
9:  pop     {r0, r1, r2, r3, ip, lr}
poster_replay:
    mov     r4, r0                      @ displaced
    bx      lr

/* cs_hook(machine, new_id, param) -- 0xC04819DC, past change_state's
 * prologue.  Captures the machine pointer.  Displaced: mov r4, r0. */
cs_hook:
    push    {r0, r1, r2, r3, ip, lr}
    REL     r2, cap_machine
    str     r0, [r2]
    pop     {r0, r1, r2, r3, ip, lr}
cs_replay:
    mov     r4, r0                      @ displaced
    bx      lr

/* post_hook -- 0xC02DBC10, right after the poster's queue push;
 * r4 = singleton, r5 = code (still live).  Displaced: add sp, sp, #4. */
post_hook:
    push    {r0, r1, r2, r3, ip, lr}
    cmp     r5, #EVT_S1_DOWN
    bne     9f
    REL     r2, pre_zoom
    ldr     r3, [r2]
    cmp     r3, #1                      @ Normal: the usual case (never when
    beq     1f                          @ the user magnified manually first).
    cmn     r3, #1                      @ 0xFFFFFFFF: machine pointer not yet
    bne     9f                          @ captured -- the camera reached Normal
1:                                      @ before our hooks armed, so pre-MfZoom
                                        @ by definition; post, and OK's
                                        @ immediacy carries the first press.
    LDA     r3, AUTOMAG_CELL
    ldr     r3, [r3]
    cmp     r3, #0                      @ Auto Magnification must be OFF:
    bne     9f                          @ ON means an electronic lens; native
                                        @ auto-magnify keeps working there
    LDA     ip, F_GETCTX
    blx     ip
    LDA     ip, F_GETFM
    blx     ip                          @ r0 = FocusMode
    cmp     r0, #2                      @ MF only -- never in AF modes
    bne     9f
    mov     r0, r4                      @ singleton
    mov     r1, #EVT_OK
    LDA     ip, F_POSTER
    blx     ip                          @ queue the magnify toggle
9:  pop     {r0, r1, r2, r3, ip, lr}
post_replay:
    add     sp, sp, #4                  @ displaced
    bx      lr

#ifndef NO_BW
/* apply_hook -- 0xC02BAD0C, one instruction past the per-frame live-view
 * applier's prologue (fires ~200/s).  While the zoom machine is in MfZoom,
 * re-assert the grayscale fields into both live records -- the pipe consumes
 * them continuously, so the magnify reconfig's colour write is overwritten
 * within a frame, with no commit and no extra reconfig.  Any other state
 * clears the capture inhibit and writes nothing.  Displaced: sub sp,sp,#0x64. */
apply_hook:
    push    {r0, r1, r2, r3, ip, lr}
    bl      read_zoom
    cmp     r0, #4                      @ MfZoom (full-screen and PIP alike)
    bne     8f
    REL     r3, bw_state
    ldr     r2, [r3]
    cmp     r2, #2                      @ capture in flight: stay colour
    beq     9f
    LDA     r3, PIC_STRUCT
    WRITE_GRAY
    b       9f
8:  @ not magnified: clear the capture inhibit (S2-up may have fired while
    @ the camera had already dropped magnification)
    REL     r3, bw_state
    mov     r2, #0
    str     r2, [r3]
9:  pop     {r0, r1, r2, r3, ip, lr}
apply_replay:
    sub     sp, sp, #0x64               @ displaced
    bx      lr
#endif

/* ------------------------------------------------------------------- data */
    .align 2
cap_machine: .word 0
pre_zoom:    .word 0
#ifndef NO_BW
bw_state:    .word 0                  @ 0 = normal, 2 = capture inhibit
#endif
poster_next: .word 0
cs_next:     .word 0
post_next:   .word 0
#ifndef NO_BW
apply_next:  .word 0
#endif
alt_poster:  .word 0xE59FF000 | (poster_next - poster_replay - 8)
alt_cs:      .word 0xE59FF000 | (cs_next - cs_replay - 8)
alt_post:    .word 0xE59FF000 | (post_next - post_replay - 8)
#ifndef NO_BW
alt_apply:   .word 0xE59FF000 | (apply_next - apply_replay - 8)
#endif
log_s:       .asciz "hpzoom: armed"

/* What this sup changes: { address, stock word, kind }.  The stock words are
 * checked against the reference image by build_v3_hpzoom.py. */
    .align 2
claims:
#ifdef NO_BW
    .word 3
#else
    .word 4
#endif
    .word SITE_POSTER, STOCK_POSTER, SL_CHAIN
    .word SITE_CS,     STOCK_CS,     SL_CHAIN
    .word SITE_POST,   STOCK_POST,   SL_CHAIN
#ifndef NO_BW
    .word SITE_APPLY,  STOCK_APPLY,  SL_CHAIN
#endif
