/* LExpo inner entry + one-shot live-view hook: refresh the shutter-speed
 * picker once the GUI is up.
 *
 * The picker list is pull-based and its boot-time build predates this sup,
 * and the dial widget caches the list count at creation -- a load-time
 * rebuild alone leaves the dial capped (one rung past the old top, an
 * off-by-one in the widget's cached bound).  The camera's own refresh path
 * is the wrapper 0xC049D6D0(ctrl, mode) that StandbyStateProc runs on
 * standby (re)entry: rebuild (force=0, change-gated on the context compare)
 * -> if changed, post the "B1_1_2_Speed"/"CM_ShutterSpeedItem" list-changed
 * event with the new items+count, then re-sync the dial selection.
 *
 * So: at sup-load time, claim the live-view applier site (0xC02BAD0C,
 * SL_CHAIN -- HpZoom layers the same site) and arm a ONE-SHOT hook.  The
 * first LV frame means the GUI is up; the hook calls the controller
 * accessor and the wrapper once, then passes through forever.  No load-time
 * rebuild on purpose: it would cache the widened context, the wrapper's
 * change gate would then see "no change", and the widget event would never
 * post.
 *
 * patch_sup calls inner_entry AFTER the patch word is written.
 * r0 = own address, r1 = svc. */
.syntax unified
.arm
.text

.equ SVC_CLAIM,   8                 /* struct sl_svc (fp_usb_shell/v3/sloader.h) */
.equ SVC_NEXT,    16
.equ SVC_CAVE,    20
.equ SVC_PUBLISH, 24

.equ SITE_LV,    0xC02BAD0C         /* live-view applier +4: sub sp, sp, #0x64 */
.equ STOCK_LV,   0xE24DD064
.equ F_CTRL,     0xC049D448         /* () -> controller singleton 0xC3766ADC */
.equ F_WRAP,     0xC049D6D0         /* (ctrl, mode): rebuild + list-changed event */
.equ VENEER_LDR, 0xE51FF004         /* ldr pc, [pc, #-4] */

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

/* The address of a label in this block: a pc-relative word, so any distance
 * assembles.  Unique macro labels (\@): the hook body uses numeric labels. */
.macro REL reg, label
    ldr     \reg, .Lrel_lit\@
.Lrel_add\@:
    add     \reg, pc, \reg
    b       .Lrel_done\@
.Lrel_lit\@:
    .word   \label - .Lrel_add\@ - 8
.Lrel_done\@:
.endm

inner_entry:                        @ (own = r0, svc = r1)
    push    {r4, r5, r10, lr}
    mov     r10, r1                     @ the service table

    /* claim the LV site (CHAIN); refusal -> leave it stock, keep the patch */
    mov     r0, r10
    LDA     r1, SITE_LV
    mov     r2, #4
    REL     r3, stock_lv
    mov     r4, #1                      @ SL_CHAIN
    sub     sp, sp, #8
    str     r4, [sp]
    ldr     ip, [r10, #SVC_CLAIM]
    blx     ip
    add     sp, sp, #8
    cmp     r0, #0
    bne     9f

    /* a layer below?  The claim put a first-claimed site back to stock, so
     * a site that branches now was written by a sup loaded before this one. */
    mov     r0, r10
    LDA     r1, SITE_LV
    mov     r2, #0                      @ ARM
    ldr     ip, [r10, #SVC_NEXT]
    blx     ip
    cmp     r0, #0
    beq     1f
    REL     r1, lv_next
    str     r0, [r1]
    REL     r1, lv_replay
    REL     r2, alt_lv
    ldr     r2, [r2]
    str     r2, [r1]
1:
    /* the veneer */
    mov     r0, r10
    mov     r1, #8
    ldr     ip, [r10, #SVC_CAVE]
    blx     ip
    movs    r4, r0
    beq     9f
    LDA     r0, VENEER_LDR
    str     r0, [r4]
    REL     r1, lv_hook
    str     r1, [r4, #4]

    /* code first, publish, arm the site last */
    mov     r0, r10
    ldr     ip, [r10, #SVC_PUBLISH]
    blx     ip
    LDA     r0, SITE_LV                 @ [SITE_LV] = bl veneer
    sub     r3, r4, r0
    sub     r3, r3, #8
    asr     r3, r3, #2
    bic     r3, r3, #0xFF000000
    orr     r3, r3, #0xEB000000
    str     r3, [r0]
    mov     r0, r10
    ldr     ip, [r10, #SVC_PUBLISH]
    blx     ip
9:  pop     {r4, r5, r10, pc}

/* lv_hook -- 0xC02BAD0C, one instruction past the LV applier's prologue.
 * r0..r3 are live (consumed at +0x10/+0x14/+0x18 and possibly a 4th arg);
 * lr is the patching bl's site+4.  One-shot: the first LV frame means the
 * GUI is up.  Displaced: sub sp, sp, #0x64. */
lv_hook:
    push    {r0, r1, r2, r3, ip, lr}
    REL     r3, lv_done
    ldr     r2, [r3]
    cmp     r2, #0
    bne     8f
    mov     r2, #1
    str     r2, [r3]
    LDA     ip, F_CTRL
    blx     ip                          @ r0 = controller
    mov     r1, #1                      @ mode 1: the stills standby list
    LDA     ip, F_WRAP
    blx     ip                          @ rebuild + list-changed event + re-sync
8:  pop     {r0, r1, r2, r3, ip, lr}
lv_replay:
    sub     sp, sp, #0x64               @ displaced
    bx      lr

/* ------------------------------------------------------------------- data */
    .align 2
stock_lv:  .word STOCK_LV
lv_done:   .word 0                      @ the BIN is re-read every boot, so
                                        @ this is 0 at every load
lv_next:   .word 0
alt_lv:    .word 0xE59FF000 | (lv_next - lv_replay - 8)
