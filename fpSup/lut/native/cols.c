/* LUT 是 COL-Share 的客戶(fpSup/colshare/colshare.h,Bei 2026-11-07 §9.1)。
 *
 * COLOR 清單的列、GUI 表、setter、±框、CSV/圖示複本與 ISP root 的共用指標字都歸 COL-Share;
 * LUT 只報上「開著、設定好、轉過檔的 cube」(≤ CL_MAX 列,library 順序)、它們的名字與圖示、
 * 強度(amount <-> -5..0),並交出每列選到時 root 要寫的記錄(lvb.c 擬合好的表)。
 * LUT 自己專屬的點(DNG 六點與兩張表 dng.c、MakerNote 0x124/0x12D/0x34/0x129 與 YGAM lvb.c)
 * 在 attached() 才裝:沒有 COL-Share 就沒有列,也不裝任何點(Manager 照常、顯示原因)。
 * 載入順序:COL-Share 在前(檔名序)-> entry 裡 add();在後 -> provide(COLS_TAG),等它撈。
 *
 * 2026-11-10(Bei):12 列。列數上限 = lut_room():COL-Share v3 的 room()(12 − 其他客戶的列,RAW-View 在 = 11);
 * Manager 不讓「開著」的 LUT 超過它(color_ui.c)。晚到的客戶(例:先開了 12 個 LUT,之後才啟用 RAW-View)
 * 讓 rows() 的 max 變小:照 library 順序,前面的放進清單,後面的(L->over 個)不出現、Manager 標成「沒有列」。
 * 我們是 v3 客戶:COL-Share 抄完圖示後叫 icon(COLS_NONE),畫圖示用的借來的記憶體(import.c)就還回去。 */
#define LUT_ORDER    100u                   /* 列序:RAW-View 0 在前(Bei 11-07 #3) */
#define VENEER_IP    0xE59FC000u            /* ldr ip, [pc]; ldr pc, [pc]; .word context; .word stub */
#define VENEER_PC    0xE59FF000u
static u32 cl_bl(u32 site, u32 dest) { return 0xEB000000u | (((dest - site - 8u) >> 2) & 0xFFFFFFu); }
static int dng_install(struct lut4_state *s);
static int lvb_install(struct lut4_state *s);

static void lc_name(const char *name, char *out) {       /* the file name without .cube (COL-Share makes it printable) */
    u32 len = 0;
    while (len < 64u && name[len]) len++;
    if (len >= 5u) { const char *e = name + len - 5u;
        if (e[0] == '.' && (e[1] | 32) == 'c' && (e[2] | 32) == 'u' && (e[3] | 32) == 'b' && (e[4] | 32) == 'e') len -= 5u; }
    if (len > 31u) len = 31u;
    for (u32 i = 0; i < len; i++) out[i] = name[i];
    out[len] = 0;
}
static int lc_on(struct lut4_state *s, u32 i) {         /* a COLOR row if there is room: on, set up, converted */
    const struct lib_entry *e = &s->library->entries[i];
    return (e->flags & 1u) && (e->flags & LIB_READY) == LIB_READY && supported(e->color, e->gamma) && conv_ok(s, i);
}
static u32 lc_rows(void *arg, struct cols_row *out, u32 max) {
    struct lut4_state *s = arg; struct lut_cols *L = &s->cols;
    u32 n = 0, over = 0;
    for (u32 i = 0; s->library && i < s->library->h.count; i++) {
        if (!lc_on(s, i)) continue;
        if (n >= CL_MAX || n >= max) { over++; continue; }   /* no room: list order decides (the last ones wait) */
        const struct lib_entry *e = &s->library->entries[i];
        L->map[n] = i;
        lc_name(e->name, L->names[n]);
        out[n].key = i; out[n].name = L->names[n]; out[n].eff_min = -5; out[n].eff_max = 0; out[n].flags = 0;
        n++;
    }
    L->n = n; L->over = over;
    return n;
}
/* Entry i's row (1-based), 0 = none. */
static u32 lc_row_of(struct lut4_state *s, u32 i) {
    for (u32 j = 0; j < s->cols.n; j++) if (s->cols.map[j] == i) return j + 1u;
    return 0;
}
/* How many LUTs may be on: COL-Share's room for us (v3), 4 with an older one, CL_MAX without one (no rows anyway). */
static u32 lut_room(struct lut4_state *s) {
    struct lut_cols *L = &s->cols;
    if (!L->attached) return CL_MAX;
    if (L->api->version < COLS_API_V3 || !L->api->room) return CL_OLD_MAX;
    u32 r = L->api->room(L->api, API_ID);
    return r < CL_MAX ? r : CL_MAX;
}
static const u8 *lc_icon(void *arg, u32 key, u32 *len) {
    if (key == COLS_NONE) { imp_icon_done(arg); return 0; }   /* v3: COL-Share copied every tile */
    const u8 *slot = imp_icon_slot(arg, key);            /* import.c draws the tile into a borrowed slot */
    if (!slot) return 0;
    *len = slot[0] | (u32)slot[1] << 8 | (u32)slot[2] << 16 | (u32)slot[3] << 24;
    return slot + 4;
}
static u32 lc_picked(void *arg) {
    struct lut4_state *s = arg;
    return s->library && s->library->h.active < s->library->h.count ? s->library->h.active + 1u : 0;
}
static void lc_on_pick(void *arg, u32 key) {
    struct lut4_state *s = arg;
    u32 want = key == COLS_NONE ? LIB_NONE : key;
    if (s->library && want != s->library->h.active) library_pick(s, want);
}
static int lc_strength_get(void *arg, u32 key) {
    struct lut4_state *s = arg;
    if (!s->library || key >= s->library->h.count) return 0;
    u32 a = s->library->entries[key].amount;
    return a >= 100u ? 0 : -(int)((100u - a + 19u) / 20u);
}
static void lc_strength_set(void *arg, u32 key, int v) {
    struct lut4_state *s = arg;
    if (!s->library || key >= s->library->h.count || v < -5 || v > 0) return;
    struct lib_entry *e = &s->library->entries[key];
    u32 amount = (u32)(100 + 20 * v);
    if (amount != e->amount && library_update(s, key, e->color, e->gamma, amount, e->flags) == OK && s->library->h.active == key)
        s->amount = amount;
}
static void lvb_preview(struct lut4_state *s, u32 key);
static void lc_preview(void *arg, u32 key) { lvb_preview(arg, key); }
/* COL-Share took us (our entry: add(); or its entry: we loaded first).  Our own points now, then the records. */
static void lc_attached(void *arg, const struct cols_api *api) {
    struct lut4_state *s = arg; struct lut_cols *L = &s->cols;
    if (L->attached) return;
    L->api = api; L->attached = 1;
    s->clist_result = 0; s->api.clist = 0;
    s->dng_result = LUT_BISECT == 2 ? 0x99u : (u32)dng_install(s);       /* 0 = DNGs carry the active cube's matrix */
    s->lvb_result = LUT_BISECT == 2 || LUT_BISECT == 3 ? 0x99u : (u32)lvb_install(s);   /* 0 = the ISP can take the active LUT */
    lvb_refresh(s);
}
/* From the entry, last: nothing after it may release us (COL-Share keeps our pointers). */
static void cols_join(struct lut4_state *s) {
    struct lut_cols *L = &s->cols; struct cols_client *c = &L->client;
    const struct sl_svc *svc = s->svc;
    L->magic = LC_MAGIC;
    c->magic = COLS_CLIENT_MAGIC; c->sup_id = API_ID; c->order = LUT_ORDER;
    c->box = 0;                                           /* v2's: none, the plain -5..0 box */
    c->preview = lc_preview;                              /* v3: the cursor's row, built when it lands there (lvb.c) */
    c->rows = lc_rows; c->icon = lc_icon; c->picked = lc_picked; c->on_pick = lc_on_pick;
    c->strength_get = lc_strength_get; c->strength_set = lc_strength_set; c->attached = lc_attached; c->arg = s;
    s->clist_result = 8u;                                 /* no COL-Share (yet): no COLOR rows */
    if (LUT_BISECT == 1 || !s->library) { s->clist_result = LUT_BISECT == 1 ? 0x99u : 1u; s->api.clist = s->clist_result; return; }
    const struct cols_api *api = (const struct cols_api *)svc->find(svc, COLS_ID);
    /* v3 (icon(COLS_NONE) after the tiles) with a v3 COL-Share; v1 with an older one (it refuses api 3) */
    c->api = api && api->magic == COLS_API_MAGIC && api->version >= COLS_API_V3 ? COLS_API_V3 : COLS_API_V1;
    if (api && api->magic == COLS_API_MAGIC && api->version >= COLS_API_V1) {
        int rc = api->add(api, c);
        if (rc != SL_OK && !L->attached) s->clist_result = 0x10u | ((u32)rc & 0xFu);
    } else if (svc->provide(svc, COLS_TAG(API_ID), c) != SL_OK) s->clist_result = 9u;
    s->api.clist = s->clist_result;
}
/* The rows follow the library (was clist_sync): COL-Share re-reads ours, then the ISP sets and records. */
static void cols_sync(struct lut4_state *s) {
    struct lut_cols *L = &s->cols;
    if (L->attached) L->api->changed(L->api, API_ID);
    imp_icon_done(s);                                     /* an older COL-Share does not say icon(COLS_NONE) */
    lvb_refresh(s);
}
