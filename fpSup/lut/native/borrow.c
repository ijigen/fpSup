/* borrow.c -- the big work areas, borrowed only while one is in use (Bei 2026-11-07).
 *
 * Camera 2026-11-07: with the whole 6 MB (the active cube's 4 MiB prepared table, the
 * conversion's 0x90000 and the fit samples) resident in the sup's block, MOV recording
 * froze the camera at its start -- the stock movie allocation from the same class failed;
 * the same build with the asset area cut to 2.3 MB recorded.  Now the block holds what is
 * read at steady state (the ISP sets, the COLOR tile being copied, the small conv state)
 * and these come from the firmware allocator the loader itself uses (sloader4.c: heap
 * class 0, FUN_c001d038 / FUN_c001d2b8), each returned as soon as its job ends:
 *   asset   a cube parsed for one load (pick, boot check, render API, a fit)  cfg->asset_cap
 *   fit     lvb_fit's samples and curves (struct lvb_fitmem)                 lvb.c
 *   conv    the conversion's work (struct conv_work), conv_start .. finish   conv.c
 * Never while recording (library_busy: the movie's allocation comes first); a refusal or
 * an allocator failure is an error of the operation (Convert failed, the load's NO_MEMORY),
 * never a wait.  CPU-only memory (file I/O goes through the block's io scratch), so it is
 * used at the cached alias, on whole 64-byte lines of its own, and the caches are cleaned
 * and invalidated (publish: FUN_c000e91c, all of L1 + L2) after the borrow and before the
 * return -- no dirty line of ours may later land on the next owner's data.  Whoever
 * returns an area clears every pointer into it (s->asset, the conv pointers). */
#define LB_HEAP  0xC001CF78u
#define LB_GET   0xC001D038u
#define LB_FREE  0xC001D2B8u
#define LB_LINE  64u

static void *lb_heap(void) { return FW(LB_HEAP, void *(*)(u32))(0); }
static u8 *lut_borrow(struct lut4_state *s, struct lut_area *b, u32 n) {
    if (b->raw) return b->p;                              /* held already: the same area */
    if (!n || library_busy()) { s->borrow_refused++; return 0; }
    void *h = lb_heap();
    u32 size = ((n + LB_LINE - 1u) & ~(LB_LINE - 1u)) + 2u * LB_LINE;
    u8 *raw = h ? FW(LB_GET, void *(*)(void *, u32, u32, u32, u32))(h, size, 0, 0, 0) : 0;
    if (!raw) { s->borrow_failed++; return 0; }
    u32 ub = ((u32)(uintptr_t)raw + LB_LINE - 1u) & ~(LB_LINE - 1u);
    if (ub >= 0x40000000u && ub < 0x80000000u) ub += 0x80000000u;   /* the cached alias (SL_ALIAS) */
    s->svc->publish(s->svc);                              /* whatever the cache held for these lines goes */
    b->raw = raw; b->p = (u8 *)(uintptr_t)ub; b->n = n;
    s->borrows++;
    return b->p;
}
static void lut_return(struct lut4_state *s, struct lut_area *b) {
    if (!b->raw) return;
    void *raw = b->raw;
    b->raw = 0; b->p = 0; b->n = 0;
    s->svc->publish(s->svc);                              /* ours written back before it is anyone's */
    FW(LB_FREE, void (*)(void *, void *))(lb_heap(), raw);
    s->returns++;
}
