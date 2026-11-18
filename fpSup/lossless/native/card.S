.syntax unified
.arm
.text
@ entry is at offset 0; not global, so every adr to it resolves here
/* ============================================================================
 * fpLossless TEST card: launcher and hook shims.
 * ============================================================================
 *
 * Built by lossless/build_card.py, which appends the compiled C (card.c and
 * the modules it links, one translation unit, no relocations) at `c_base` and
 * passes every C entry's offset in. Nothing here names an address of its own
 * choosing in the cave: the veneers come off the cave's bump allocator at
 * boot, as gyro's do (writer_core.inc.S s_hook), and the hook sites are
 * journaled by stage2 because the builder declares each as a 4-byte section
 * holding the firmware's own word (SUP_BUILD_RULES §4).
 *
 * THE LAUNCHER runs where the file landed (a destination-zero section). It
 * asks the allocator for its own block, copies the whole blob there, zeroes
 * the state after it, publishes D/I, calls the resident init -- and only then
 * arms, all or nothing: every site must still hold its stock word and the cave
 * must have room for every veneer, or not one site is written.
 * ========================================================================== */

.equ H_GET,        0xC001D740    /* (desc, class, size, 0): gsup_launch.S    */
.equ H_ADDR,       0xC001D7F0    /* (desc) -> address                         */
.equ USER_CLASS,   0             /* NOT class 10: that is the frames' pool    */
.equ F_DCACHE,     0xC000E91C
.equ F_ICACHE,     0xC000EABC
.equ CAVE_BUMP,    0xC072E060
.equ CAVE_END,     0xC072EFB4    /* the park stub: nothing may reach it       */
.equ VENEER_LDR,   0xE51FF004    /* ldr pc, [pc, #-4]                          */
.equ CARD_MAGIC,   0x43504C46    /* "FLPC": how a host finds the state        */

.equ SITE_REC,     0xC03A33C8
.equ STOCK_REC,    0xEBFFFC1A    /* bl C03A2438                               */
.equ SITE_ARRIVE,  0xC038BFF0
.equ STOCK_ARRIVE, 0xE12FFF33    /* blx r3 -- the creator's vtable call       */
.equ SITE_STOP,    0xC0398D88
.equ STOCK_STOP,   0xE92D49F0    /* push {r4-r8, fp, lr}: the entry           */
.equ SITE_FLUSH,   0xC03A5490
.equ STOCK_FLUSH,  0xEB0BD652    /* bl C069ADE0                               */
.equ SITE_PLAY,    0xC05C0EA4    /* the player's frame read, after its f_read */
.equ STOCK_PLAY,   0xE595201C    /* ldr r2, [r5, #0x1c]                       */
.equ SITE_READ,    0xC05C0EA0    /* the player's f_read of a frame file       */
.equ STOCK_READ,   0xEBF6946E    /* bl C0366060                               */
.equ REAL_READ,    0xC0366060
.equ SITE_GATE,    0xC05BD984    /* the player: are enough frames ready to start? */
.equ STOCK_GATE,   0xEB0015F7    /* bl C05C3168                               */
.equ REAL_GATE,    0xC05C3168
.equ SITE_CLIP,    0xC05BDDAC    /* clip open: the first frame's size stored  */
.equ STOCK_CLIP,   0xE58430A0    /* str r3, [r4, #0xa0]                       */
.equ SITE_END,     0xC05C2E90    /* the player's pool freed: entry            */
.equ STOCK_END,    0xE92D4070    /* push {r4, r5, r6, lr}                     */
.equ END_RESUME,   0xC05C2E94
.equ SITE_POOL,    0xC05C2D10    /* the player's pool made: entry             */
.equ STOCK_POOL,   0xE92D44F0    /* push {r4, r5, r6, r7, sl, lr}             */
.equ POOL_RESUME,  0xC05C2D14
.equ CREATOR_ENQ,  0xC037DD50
.equ STOP_RESUME,  0xC0398D8C
.equ REAL_FLUSH,   0xC069ADE0
.equ SITE_EVENT,   0xC038BD08    /* dispatcher, after its frame lookup        */
.equ STOCK_EVENT,  0xE594300C    /* ldr r3, [r4, #0xc]                        */
.equ EVENT_RESUME, 0xC038BD0C
.equ SITE_DISCARD, 0xC037DEF8    /* each frame popped by C037DEE0             */
.equ STOCK_DISCARD,0xEB000042    /* bl C037E008                               */
.equ REAL_DISCARD, 0xC037E008

/* Passed in by the builder: BLOB_LEN, BLOCK_BYTES, STATE_OFF and the C
 * entry offsets from c_base (Thumb, bit 0 set). */

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

/* The resident address of a label: its staging address plus r11, the
 * distance from where the file landed to the block. The pc-relative distance
 * is a word beside the code, so any distance assembles (adr's immediate ran
 * out once the player's three shims were added). */
.macro RESIDENT reg, label
    ldr     \reg, 8f
9:  add     \reg, pc, \reg
    add     \reg, \reg, r11
    b       7f
8:  .word   \label - 9b - 8
7:
.endm

#if V3
.equ SVC_CLAIM,    8             /* struct sl_svc (fp_usb_shell/v3/sloader.h) */
.equ SVC_RES,      12
.equ SVC_NEXT,     16
.equ SVC_CAVE,     20
.equ SL_CHAIN,     1
.equ SL_EXCL,      2
.equ SL_SHARED_UI, 3
.equ ENGINE,       0x300D0000    /* the lossless engine: claim_res id         */
.equ CAVE_BYTES,   112
.equ REAL_PREPARE, 0xC03A2438

/* An insertion site with a layer below: the site must already branch the
 * way ours would (`form`: b or bl), and then our shim ends in that layer
 * instead of replaying the stock instruction. Stock: nothing to do. */
.macro LAYER site, stock, form, resume, replay, alt
    LDA     r0, \site
    ldr     r1, [r0]
    LDA     r2, \stock
    cmp     r1, r2
    beq     3f
    and     r2, r1, #0xFF000000
    cmp     r2, #\form
    bne     out
    mov     r1, r0
    bl      below
    cmp     r0, #0
    beq     out
    RESIDENT r1, \resume
    str     r0, [r1]
    RESIDENT r1, \replay
    RESIDENT r2, \alt
    ldr     r2, [r2]
    str     r2, [r1]
3:
.endm
#endif

entry:
#if V3
    /* Loader v3 (projects/usb-shell-sup/notes/LOADER_V3.md §4): the 加載器
     * read this file into a block of its own and zeroed the rest of it, so
     * the code already runs where it stays: no allocation, no copy. r0 = the
     * block (its FSB1 header), r1 = the service table. Every decision is
     * made before anything is written -- claims, the layers below, the
     * cave -- and a refusal returns SL_RELEASE having written nothing. */
    push    {r3, r4, r5, r6, r7, r8, r9, r10, r11, lr}   @ ten: 8-aligned
    mov     r10, r1                     @ r10 = the service table
    mov     r9, r2                      @ r9 = this sup's own path (service v2)
    adr     r5, entry                   @ r5 = the resident base
    mov     r11, #0                     @ RESIDENT: resident = here
    tst     r5, #7
    bne     out

    /* 1. claim every site, then the engine */
    RESIDENT r6, claims
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
    mov     r0, r10
    LDA     r1, ENGINE
    mov     r2, #SL_EXCL
    ldr     ip, [r10, #SVC_RES]
    blx     ip
    cmp     r0, #0
    bne     out

    /* 2. the layers below. A claim put every first-claimed site back to
     * stock, so a site that is not stock now was written by a sup loaded
     * before this one, this boot. REC: the C calls C03A2438 itself, so only
     * stock may be below it. The two call sites call whatever is below. */
    LDA     r1, SITE_REC
    bl      below
    LDA     r1, REAL_PREPARE
    cmp     r0, r1
    bne     out
    LDA     r1, SITE_FLUSH
    bl      below
    cmp     r0, #0
    beq     out
    RESIDENT r1, flush_real
    str     r0, [r1]
    LDA     r1, SITE_DISCARD
    bl      below
    cmp     r0, #0
    beq     out
    RESIDENT r1, discard_real
    str     r0, [r1]
    LDA     r1, SITE_READ
    bl      below
    cmp     r0, #0
    beq     out
    RESIDENT r1, read_real
    str     r0, [r1]
    LDA     r1, SITE_GATE
    bl      below
    cmp     r0, #0
    beq     out
    RESIDENT r1, gate_real
    str     r0, [r1]
    LAYER   SITE_STOP,  STOCK_STOP,  0xEA000000, stop_resume,  stop_replay,  alt_stop
    LAYER   SITE_END,   STOCK_END,   0xEA000000, end_resume,   end_replay,   alt_end
    LAYER   SITE_POOL,  STOCK_POOL,  0xEA000000, pool_resume,  pool_replay,  alt_pool
    LAYER   SITE_EVENT, STOCK_EVENT, 0xEA000000, event_resume, event_replay, alt_event
    LAYER   SITE_PLAY,  STOCK_PLAY,  0xEB000000, play_next,    play_replay,  alt_play

    /* 3. the veneers' cave block: the host record stays at +32 */
    mov     r0, r10
    mov     r1, #CAVE_BYTES
    ldr     ip, [r10, #SVC_CAVE]
    blx     ip
    movs    r8, r0                      @ r8 = our cave block
    beq     out
#else
    push    {r3, r4, r5, r6, r7, r8, r9, r10, r11, lr}   @ ten: 8-aligned
    sub     sp, sp, #16                 @ the allocator descriptor, kept:
                                        @ this block is never freed
    mov     r0, sp
    mov     r1, #USER_CLASS
    LDA     r2, BLOCK_BYTES
    mov     r3, #0
    LDA     ip, H_GET
    blx     ip
    mov     r0, sp
    LDA     ip, H_ADDR
    blx     ip
    movs    r5, r0                      @ r5 = the resident base
    beq     out                         @ refused: stand down, camera is stock
    tst     r5, #7
    bne     out

    adr     r6, entry
    sub     r11, r5, r6                 @ r11 = resident - staging

    /* copy the whole blob -- this code included -- to the block */
    mov     r7, r5
    LDA     r8, BLOB_LEN
1:  ldr     ip, [r6], #4
    str     ip, [r7], #4
    subs    r8, r8, #4
    bne     1b
    /* zero the rest: the card state lives at STATE_OFF */
    LDA     r8, BLOCK_BYTES
    add     r8, r5, r8
    mov     ip, #0
2:  cmp     r7, r8
    strlo   ip, [r7], #4
    blo     2b
#endif

#if V3
    /* Run from the CACHED alias. The loader's USER block is NonCacheBuffer:
     * VA 0x4xxxxxxx is normal NON-cacheable (MMU 0x45044C02), so every
     * instruction of this code and every access to its state went to DRAM
     * (2026-10-13: the trailer's ~9.5k instructions took 1.18 ms per frame).
     * The same physical memory is mapped cacheable, executable, at VA +
     * 0x80000000 (0xC0..0xFF -> PA 0x40..0x7F, 0x4xx45C06), the window the
     * firmware's own code and heap live in. Nothing in this block is handed
     * to a DMA master. From here on every resident address is the cached one:
     * the state, the C entries, the shims the veneers name, the host record.
     * Clean+invalidate first, so the cached alias holds no stale line. */
    LDA     ip, F_DCACHE
    blx     ip
    cmp     r5, #0x40000000
    blo     1f
    cmp     r5, #0x80000000
    bhs     1f
    add     r5, r5, #0x80000000
    mov     r11, #0x80000000            @ RESIDENT: the cached alias of here
1:
#endif

    /* the resident words the shims read: the state, and each C entry */
    LDA     r6, STATE_OFF
    add     r6, r5, r6                  @ r6 = the card state
    RESIDENT r4, c_base                 @ r4 = the resident C text
    RESIDENT r0, g_card
    str     r6, [r0]
    RESIDENT r0, w_rec
    LDA     ip, OFF_REC
    add     ip, r4, ip
    str     ip, [r0]
    RESIDENT r0, w_arrive
    LDA     ip, OFF_ARRIVE
    add     ip, r4, ip
    str     ip, [r0]
    RESIDENT r0, w_stop
    LDA     ip, OFF_STOP
    add     ip, r4, ip
    str     ip, [r0]
    RESIDENT r0, w_flush
    LDA     ip, OFF_FLUSH
    add     ip, r4, ip
    str     ip, [r0]
    RESIDENT r0, w_task
    LDA     ip, OFF_TASK
    add     ip, r4, ip
    str     ip, [r0]
    RESIDENT r0, w_play
    LDA     ip, OFF_PLAY
    add     ip, r4, ip
    str     ip, [r0]
    RESIDENT r0, w_clip
    LDA     ip, OFF_CLIP
    add     ip, r4, ip
    str     ip, [r0]
    RESIDENT r0, w_end
    LDA     ip, OFF_END
    add     ip, r4, ip
    str     ip, [r0]
    RESIDENT r0, w_pool
    LDA     ip, OFF_POOL
    add     ip, r4, ip
    str     ip, [r0]
    RESIDENT r0, w_made
    LDA     ip, OFF_MADE
    add     ip, r4, ip
    str     ip, [r0]
    RESIDENT r0, w_read
    LDA     ip, OFF_READ
    add     ip, r4, ip
    str     ip, [r0]
    RESIDENT r0, w_gate
    LDA     ip, OFF_GATE
    add     ip, r4, ip
    str     ip, [r0]
    RESIDENT r0, w_written
    LDA     ip, OFF_WRITTEN
    add     ip, r4, ip
    str     ip, [r0]
    RESIDENT r0, w_event
    LDA     ip, OFF_EVENT
    add     ip, r4, ip
    str     ip, [r0]
    RESIDENT r0, w_discard
    LDA     ip, OFF_DISCARD
    add     ip, r4, ip
    str     ip, [r0]
    RESIDENT r0, w_observe
    LDA     ip, OFF_OBSERVE
    add     ip, r4, ip
    str     ip, [r0]

    LDA     ip, F_DCACHE
    blx     ip
    LDA     ip, F_ICACHE
    blx     ip

    /* the resident init, in the resident copy; the fifth argument, the path
     * of this sup's file (0 on a v2 card), on the stack */
    sub     sp, sp, #8
#if V3
    str     r9, [sp]
#if V4
    str     r10, [sp, #4]               @ sixth: the service table (the row, file_is)
#endif
#else
    mov     ip, #0
    str     ip, [sp]
#endif
    mov     r0, r6
    mov     r1, r5
    LDA     r2, BLOCK_BYTES
    RESIDENT r3, task_shim              @ the codec task's entry
    LDA     ip, OFF_INIT
    add     ip, r4, ip
    blx     ip
    add     sp, sp, #8
    cmp     r0, #0
    bne     out

#if !V3
    /* ---- arm: every site stock, or none ---------------------------- */
    LDA     r0, SITE_REC
    LDA     r1, STOCK_REC
    ldr     r2, [r0]
    cmp     r2, r1
    bne     out
    LDA     r0, SITE_ARRIVE
    LDA     r1, STOCK_ARRIVE
    ldr     r2, [r0]
    cmp     r2, r1
    bne     out
    LDA     r0, SITE_STOP
    LDA     r1, STOCK_STOP
    ldr     r2, [r0]
    cmp     r2, r1
    bne     out
    LDA     r0, SITE_FLUSH
    LDA     r1, STOCK_FLUSH
    ldr     r2, [r0]
    cmp     r2, r1
    bne     out
    LDA     r0, SITE_PLAY
    LDA     r1, STOCK_PLAY
    ldr     r2, [r0]
    cmp     r2, r1
    bne     out
    LDA     r0, SITE_CLIP
    LDA     r1, STOCK_CLIP
    ldr     r2, [r0]
    cmp     r2, r1
    bne     out
    LDA     r0, SITE_READ
    LDA     r1, STOCK_READ
    ldr     r2, [r0]
    cmp     r2, r1
    bne     out
    LDA     r0, SITE_GATE
    LDA     r1, STOCK_GATE
    ldr     r2, [r0]
    cmp     r2, r1
    bne     out
    LDA     r0, SITE_END
    LDA     r1, STOCK_END
    ldr     r2, [r0]
    cmp     r2, r1
    bne     out
    LDA     r0, SITE_POOL
    LDA     r1, STOCK_POOL
    ldr     r2, [r0]
    cmp     r2, r1
    bne     out
    LDA     r0, SITE_EVENT
    LDA     r1, STOCK_EVENT
    ldr     r2, [r0]
    cmp     r2, r1
    bne     out
    LDA     r0, SITE_DISCARD
    LDA     r1, STOCK_DISCARD
    ldr     r2, [r0]
    cmp     r2, r1
    bne     out

    /* The host record stays at +32. Player veneers at +48, diagnostics at
     * +80; all are owned by this launcher's single 96-byte cave block. */
    LDA     r7, CAVE_BUMP
    ldr     r8, [r7]                    @ r8 = our cave block
    tst     r8, #3
    bne     out
    add     r9, r8, #112
    LDA     r10, CAVE_END
    cmp     r9, r10
    bhi     out                         @ the cave is full: arm nothing
    cmp     r8, #0xC0000000
    blo     out
    str     r9, [r7]

#endif

    LDA     r0, VENEER_LDR
    str     r0, [r8, #0]
    RESIDENT r1, rec_shim
    str     r1, [r8, #4]
    str     r0, [r8, #8]
    RESIDENT r1, arrive_shim
    str     r1, [r8, #12]
    str     r0, [r8, #16]
    RESIDENT r1, stop_shim
    str     r1, [r8, #20]
    str     r0, [r8, #24]
    RESIDENT r1, flush_shim
    str     r1, [r8, #28]
    LDA     r0, CARD_MAGIC
    str     r0, [r8, #32]               @ how a host finds the state
    str     r6, [r8, #36]
    str     r5, [r8, #40]               @ and the resident base
    LDA     r0, BLOB_LEN
    str     r0, [r8, #44]
    LDA     r0, VENEER_LDR
    str     r0, [r8, #48]
    RESIDENT r1, play_shim
    str     r1, [r8, #52]
    str     r0, [r8, #56]
    RESIDENT r1, clip_shim
    str     r1, [r8, #60]
    str     r0, [r8, #64]
    RESIDENT r1, end_shim
    str     r1, [r8, #68]
    str     r0, [r8, #72]
    RESIDENT r1, pool_shim
    str     r1, [r8, #76]
    str     r0, [r8, #80]
    RESIDENT r1, event_shim
    str     r1, [r8, #84]
    str     r0, [r8, #88]
    RESIDENT r1, discard_shim
    str     r1, [r8, #92]
    str     r0, [r8, #96]
    RESIDENT r1, read_shim
    str     r1, [r8, #100]
    str     r0, [r8, #104]
    RESIDENT r1, gate_shim
    str     r1, [r8, #108]

    LDA     ip, F_DCACHE
    blx     ip
    LDA     ip, F_ICACHE
    blx     ip

    /* the site words, last */
    LDA     r0, SITE_REC
    add     r1, r8, #0
    mov     r2, #0xEB000000             @ bl
    bl      encode
    LDA     r0, SITE_ARRIVE
    add     r1, r8, #8
    mov     r2, #0xEB000000             @ bl: sets lr exactly as blx r3 did
    bl      encode
    LDA     r0, SITE_STOP
    add     r1, r8, #16
    mov     r2, #0xEA000000             @ b: the caller's lr must survive
    bl      encode
    LDA     r0, SITE_FLUSH
    add     r1, r8, #24
    mov     r2, #0xEB000000             @ bl
    bl      encode
    LDA     r0, SITE_PLAY
    add     r1, r8, #48
    mov     r2, #0xEB000000             @ bl: lr was spent on the f_read call
    bl      encode
    LDA     r0, SITE_CLIP
    add     r1, r8, #56
    mov     r2, #0xEB000000             @ bl: lr was spent on the size call
    bl      encode
    LDA     r0, SITE_END
    add     r1, r8, #64
    mov     r2, #0xEA000000             @ b: the caller's lr must survive
    bl      encode
    LDA     r0, SITE_POOL
    add     r1, r8, #72
    mov     r2, #0xEA000000             @ b: the caller's lr must survive
    bl      encode
    LDA     r0, SITE_EVENT
    add     r1, r8, #80
    mov     r2, #0xEA000000             @ b: a displaced load, preserve lr
    bl      encode
    LDA     r0, SITE_DISCARD
    add     r1, r8, #88
    mov     r2, #0xEB000000             @ bl: continue into the real cleanup
    bl      encode
    LDA     r0, SITE_READ
    add     r1, r8, #96
    mov     r2, #0xEB000000             @ bl: the read, or ours in its place
    bl      encode
    LDA     r0, SITE_GATE
    add     r1, r8, #104
    mov     r2, #0xEB000000             @ bl: the player's own answer first, then ours
    bl      encode

    /* Last of all, the header template's observer (card.c fpl_card_observer):
     * a list entry, not a site -- it only does anything for a take the hooks
     * above admitted. */
    RESIDENT r0, g_card
    ldr     r0, [r0]
    RESIDENT r1, obs_shim
    RESIDENT r2, c_base
    LDA     ip, OFF_OBSERVER
    add     ip, r2, ip
    blx     ip

    LDA     ip, F_DCACHE
    blx     ip
    LDA     ip, F_ICACHE
    blx     ip

#if V3
    mov     r0, #0                      @ SL_KEEP
    pop     {r3, r4, r5, r6, r7, r8, r9, r10, r11, pc}
out:                                    @ nothing written: SL_RELEASE
    LDA     ip, F_DCACHE                @ no dirty line of the cached alias
    blx     ip                          @ may outlive the freed block
    mov     r0, #1
    pop     {r3, r4, r5, r6, r7, r8, r9, r10, r11, pc}

/* below: r0 = chain_next(svc, r1 = site, ARM) -- where the site's branch goes
 * now, 0 when it is not a branch. */
below:
    push    {r4, lr}
    mov     r0, r10
    mov     r2, #0
    ldr     ip, [r10, #SVC_NEXT]
    blx     ip
    pop     {r4, pc}
#else
out:
    add     sp, sp, #16
    mov     r0, #0
    pop     {r3, r4, r5, r6, r7, r8, r9, r10, r11, pc}
#endif

/* encode: [r0] = r2 | ((r1 - r0 - 8) >> 2 & 0xFFFFFF). Signed: the veneer
 * may lie below the site. */
encode:
    sub     r3, r1, r0
    sub     r3, r3, #8
    asr     r3, r3, #2
    bic     r3, r3, #0xFF000000
    orr     r3, r3, r2
    str     r3, [r0]
    bx      lr

/* ---- the shims, reached through the veneers ------------------------------ */

/* C03A33C8: bl C03A2438(camera, request). The Movie task's internal stack
 * can be 4 mod 8 here. Align the C entry and preserve the incoming SP/LR. */
rec_shim:
    push    {r4, lr}
    mov     r4, sp
rec_align:
    bic     sp, sp, #7
    ldr     r2, g_card
    ldr     ip, w_rec
    blx     ip
    mov     sp, r4
    pop     {r4, pc}

/* C038BFF0: blx r3 with r3 = creator->vtable[0x10]. Only the creator enqueue
 * we know is ours to take; anything else is called exactly as it would have
 * been, with lr already pointing after the site. */
arrive_shim:
    LDA     ip, CREATOR_ENQ
    cmp     r3, ip
    bxne    r3
    ldr     r3, g_card
    ldr     ip, w_arrive
    bx      ip

/* C0398D88 entry: our stop first, then the displaced first instruction, then
 * the rest of the original. Six registers: the stack stays 8-aligned. */
stop_shim:
    push    {r0, r1, r2, r3, ip, lr}
    mov     r1, r0                      @ the stop kind: 1 and 9 are checks
    ldr     r0, g_card
    ldr     ip, w_stop
    blx     ip
    pop     {r0, r1, r2, r3, ip, lr}
stop_replay:
    push    {r4, r5, r6, r7, r8, fp, lr}   @ STOCK_STOP, executed here
    ldr     pc, stop_resume

/* C03A5490: C069ADE0(writer, frame) returns a 64-bit byte count in r0:r1.
 * Keep all four incoming argument registers for the real call, then observe
 * the result. The native function has two arguments and no stack arguments.
 * This internal site can arrive with SP%8=4: explicitly align every new C
 * call, and return with the exact incoming SP and native r0:r1/flags. */
flush_shim:
    push    {r0, r1, r2, r3, r4, r5, ip, lr}
    mov     r5, sp
    bic     sp, sp, #7
    ldr     r1, g_card
    ldr     ip, w_flush
    blx     ip
    ldmia   r5, {r0, r1, r2, r3}
    ldr     ip, flush_real
    blx     ip
    stmia   r5, {r0, r1, r2, r3}
    mrs     r4, cpsr
written_high:
    mov     r2, r1
    mov     r1, r0
    ldr     r0, g_card
    ldr     ip, w_written
    blx     ip
    msr     cpsr_f, r4
    mov     sp, r5
    pop     {r0, r1, r2, r3, r4, r5, ip, pc}

/* C038BD08: r4=message, r6=the dispatcher's already-looked-up frame or 0.
 * Replay the load and preserve the flags and LR of this non-call site. */
event_shim:
    push    {r0, r1, r2, r3, r4, r5, ip, lr}
    mov     r5, sp
event_align:
    bic     sp, sp, #7
    sub     sp, sp, #8
    mrs     ip, cpsr
    str     ip, [sp]
    mov     r0, r4
    mov     r1, r6
    ldr     r2, g_card
    ldr     ip, w_event
    blx     ip
    ldr     ip, [sp]
    msr     cpsr_f, ip
    mov     sp, r5
    pop     {r0, r1, r2, r3, r4, r5, ip, lr}
event_replay:
    ldr     r3, [r4, #0xc]             @ STOCK_EVENT
    ldr     pc, event_resume

/* C037DEF8: r0=creator, r1=one popped frame. C037DEE0 pushed four words;
 * its caller's LR is at the ORIGINAL SP+12, not this site's own LR. */
discard_shim:
    push    {r0, r1, r2, r3, r4, r5, ip, lr}
    mov     r5, sp
    bic     sp, sp, #7
discard_caller:
    ldr     r2, [r5, #44]              @ original SP+12
    ldr     r3, g_card
    ldr     ip, w_discard
    blx     ip
    mov     sp, r5
    pop     {r0, r1, r2, r3, r4, r5, ip, lr}
    ldr     pc, discard_real          @ original cleanup, exactly once

/* C05C0EA4, right after the player's f_read of a frame file: r5 is its slot
 * (+0x14 buffer, +0x18 capacity, +0x1c bytes read). Ours first, then the
 * displaced load, back to C05C0EA8 through the lr the site's bl set. */
play_shim:
    push    {r0, r1, r2, r3, ip, lr}
    mov     r0, r5
    mov     r2, r4                      @ the reader: the path at +0x80
    ldr     r1, g_card
    ldr     ip, w_play
    blx     ip
    pop     {r0, r1, r2, r3, ip, lr}
play_replay:
    ldr     r2, [r5, #0x1c]             @ STOCK_PLAY, executed here
    bx      lr

/* C05C0EA0: bl C0366060(file, buffer, capacity, &read) -- r5 the slot, r4 the
 * reader. When the slot already holds this file (read ahead while the engine
 * decoded the frame before), the read is skipped: the site ignores r0. Else
 * the real read (or the layer below), which returns to the site. */
read_shim:
    push    {r0, r1, r2, r3, ip, lr}
    mov     r0, r5
    ldr     r1, g_card
    mov     r2, r4
    ldr     ip, w_read
    blx     ip
    cmp     r0, #0
    pop     {r0, r1, r2, r3, ip, lr}
    bxne    lr
    ldr     pc, read_real

/* C05BD984: bl C05C3168(pool) -- r4 the player, the result in r0: nonzero
 * lets a buffering player start. The player's own answer first (or the layer
 * below), then ours, which may only turn a yes into a not yet. */
gate_shim:
    push    {r4, r5, r6, lr}
    mov     r5, r0
    ldr     ip, gate_real
    blx     ip
    mov     r3, r0
    mov     r2, r4
    mov     r1, r5
    ldr     r0, g_card
    ldr     ip, w_gate
    blx     ip
    pop     {r4, r5, r6, pc}

/* C05BDDAC: str r3, [r4, #0xa0] -- r3 the first frame file's size, r4 the
 * player, r6 the clip's file descriptor. The size stored is ours to say. */
clip_shim:
    push    {r0, r1, r2, r3, ip, lr}
    ldr     r0, g_card
    mov     r1, r4
    mov     r2, r6
    ldr     ip, w_clip
    blx     ip
    str     r0, [sp, #12]               @ becomes r3
    pop     {r0, r1, r2, r3, ip, lr}
    str     r3, [r4, #0xa0]             @ STOCK_CLIP, executed here
    bx      lr

/* C05C2E90 entry: the player's buffers are about to be freed. Ours (the
 * decoder's scratch) first, then the displaced push and the original. */
end_shim:
    push    {r0, r1, r2, r3, ip, lr}
    ldr     r0, g_card
    ldr     ip, w_end
    blx     ip
    pop     {r0, r1, r2, r3, ip, lr}
end_replay:
    push    {r4, r5, r6, lr}            @ STOCK_END, executed here
    ldr     pc, end_resume

/* C05C2D10 entry: the player is about to make its buffer pool (taking the
 * RAW pool until it is empty). The decoder's scratch first, then the
 * displaced push and the original. */
pool_shim:
    push    {r0, r1, r2, r3, ip, lr}
    mov     r3, lr                      @ where the player goes on
    mov     r2, r1                      @ the file size its buffers are for
    mov     r1, r0                      @ its pool object
    ldr     r0, g_card
    ldr     ip, w_pool
    blx     ip
    cmp     r0, #0
    pop     {r0, r1, r2, r3, ip, lr}
    adrne   lr, pool_made               @ the original returns to us (2026-11-18)
pool_replay:
    push    {r4, r5, r6, r7, sl, lr}    @ STOCK_POOL, executed here
    ldr     pc, pool_resume

/* C05C2D10 has returned (void; sp as at its call): its buffers are made.
 * Ours, which hands back the address the player called from. */
pool_made:
    push    {r4, lr}
    ldr     r0, g_card
    ldr     ip, w_made
    blx     ip
    mov     ip, r0
    pop     {r4, lr}
    bx      ip

/* The CinemaDNG tag Subject's observer, vtable +0xC: r0 = the observer,
 * r1 = the DataPool. Called by FUN_c0055fe0 in the notifying task with no
 * known stack alignment. Returns 1 always: 0 would take it off the list. */
obs_shim:
    push    {r4, lr}
    mov     r4, sp
    bic     sp, sp, #7
    mov     r0, r1
    ldr     r1, g_card
    ldr     ip, w_observe
    blx     ip
    mov     sp, r4
    mov     r0, #1
    pop     {r4, pc}

/* The codec task's entry (tk_sta_tsk). The body takes the state and never
 * returns: a task cannot be ended in this firmware. */
task_shim:
    ldr     r0, g_card
    ldr     ip, w_task
    bx      ip

    .align  2
g_card:      .word 0
w_rec:       .word 0
w_arrive:    .word 0
w_stop:      .word 0
w_flush:     .word 0
w_task:      .word 0
w_play:      .word 0
w_clip:      .word 0
w_end:       .word 0
w_pool:      .word 0
w_made:      .word 0
w_read:      .word 0
w_gate:      .word 0
w_written:   .word 0
w_event:     .word 0
w_discard:   .word 0
w_observe:   .word 0
stop_resume: .word STOP_RESUME
flush_real:  .word REAL_FLUSH
end_resume:  .word END_RESUME
pool_resume: .word POOL_RESUME
event_resume:.word EVENT_RESUME
discard_real:.word REAL_DISCARD
read_real:   .word REAL_READ
gate_real:   .word REAL_GATE
#if V3
play_next:   .word 0
/* A layer below an insertion site: the stock instruction we would replay is
 * already replayed by that layer, so ours becomes `ldr pc, <its target>`. */
alt_stop:    .word 0xE59FF000 | (stop_resume - stop_replay - 8)
alt_end:     .word 0xE59FF000 | (end_resume - end_replay - 8)
alt_pool:    .word 0xE59FF000 | (pool_resume - pool_replay - 8)
alt_event:   .word 0xE59FF000 | (event_resume - event_replay - 8)
alt_play:    .word 0xE59FF000 | (play_next - play_replay - 8)
/* Lossless RAW ON/OFF as saved in this file (card.c FPL_SETTINGS_OFF): the
 * codec task rewrites these 16 bytes in place on the card.  v3: built OFF.
 * v4: built ON -- a fresh install records with Lossless (user 2026-10-24). */
    .align 2
settings:
#if V4
    .word 0x54534C46, 1, 1, 0x54534C46 ^ 1 ^ 1 ^ 0xFFFFFFFF
#else
    .word 0x54534C46, 1, 0, 0x54534C46 ^ 1 ^ 0 ^ 0xFFFFFFFF
#endif
/* What this sup changes: { address, stock word, kind }. The stock words are
 * checked against the reference image by build_v3_lossless.py. */
claims:
#if V4
    .word 12                            @ the string sites are the v4 core's
#else
    .word 15
#endif
    .word SITE_REC,     STOCK_REC,     SL_CHAIN
    .word SITE_ARRIVE,  STOCK_ARRIVE,  SL_EXCL     @ replaces blx r3: not a branch
    .word SITE_STOP,    STOCK_STOP,    SL_CHAIN
    .word SITE_FLUSH,   STOCK_FLUSH,   SL_CHAIN
    .word SITE_PLAY,    STOCK_PLAY,    SL_CHAIN
    .word SITE_CLIP,    STOCK_CLIP,    SL_EXCL     @ the size stored is ours to say
    .word SITE_END,     STOCK_END,     SL_CHAIN
    .word SITE_POOL,    STOCK_POOL,    SL_CHAIN
    .word SITE_EVENT,   STOCK_EVENT,   SL_CHAIN
    .word SITE_DISCARD, STOCK_DISCARD, SL_CHAIN
    .word SITE_READ,    STOCK_READ,    SL_CHAIN
    .word SITE_GATE,    STOCK_GATE,    SL_CHAIN
#if !V4
    .word 0xC05E5B58,   0x3FFFF1B1,    SL_SHARED_UI   @ uishare string layers
    .word 0xC05E61C8,   0x428A6942,    SL_SHARED_UI
    .word 0xC05E61E0,   0x69406902,    SL_SHARED_UI
#endif
#endif
    .align  3
c_base:
    /* the compiled C is appended here by build_card.py */
