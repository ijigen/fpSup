/* Included after the QS rules: the menu calls the SAME setters and lists.
 * All native work is on the UI thread through the container's leave callback.
 * The stock setting enums never receive a private menu index.
 *
 * v0.7.1test (live v1 item 3 froze the camera on a RES pick): a change event of the popup list (slm_changed,
 * slm_format_changed) runs inside the stock list's own commit action sequence. There it only records the selection
 * and queues variable posts (C0593F30 / C0593FE0 only enqueue, GUI_QUEUE_FULL). It never pushes / commits (LV
 * reload, carrier setter), never runs ap_idle (NBR glyph load) and never rewrites a modelCSV: the model notify
 * C05D83A8(type 1) rebuilds every bound list synchronously (C05CE8A0 deletes and recreates the item instances) --
 * the very popup whose commit is still executing. The owed work runs at the next leave() (layout load). */
#ifndef SLM_RUNTIME_H
#define SLM_RUNTIME_H
static const char SLM_VALUE[3][12] = {"SLM_Dc", "SLM_Res", "SLM_Fps"};
static const char SLM_PICK[3][16] = {"SLM_PickDc", "SLM_PickRes", "SLM_PickFps"};
static const char SLM_COUNT[3][12] = {"SLM_DcN", "SLM_ResN", "SLM_FpsN"};
static const char SLM_LOCK[3][16] = {"EXCL_SLM_Dc", "EXCL_SLM_Res", "EXCL_SLM_Fps"};
static const char SLM_SUMMARY[3][16] = {"SLM_DcText", "SLM_ResText", "SLM_FpsText"};
static const char SLM_MODEL[2][8] = {"SLM_RES", "SLM_FPS"};

static volatile char *slm_request(void)
{ return (volatile char *)(uintptr_t)(SLM_PAGE + SLM_REQUEST_OFFSET); }
static void slm_cancel_go(struct st *st)
{ if (st->menu.ready) *slm_request() = 0; }
static int slm_format_locked(void)
{ return ((ap_fw1)AP_GET_FMT)(((ap_fw0)AP_GET_OBJ)()) != 0; }

static void slm_row_set(struct slm_row *r, const char *text, u32 a, u32 b, u32 enabled, u32 custom)
{
    r->a = a; r->b = b; r->enabled = enabled; r->custom = custom;
    put_s(r->text, 0, SLM_TEXT, text);
}

/* the three row summaries into `bank` (the GUI keeps only the string pointer: write the bank it is not showing) */
static void slm_summaries(struct st *st, u32 bank)
{
    struct slm_state *m = &st->menu;
    for (u32 k = 0; k < 3u; k++) {
        const char *v = sq_value(&st->arg[k][0]);
        put_s(m->summary[bank][k], 0, SLM_TEXT, v && (u8)*v < 128u ? v : "--");
    }
    m->bank = bank;
}

static void slm_build(struct st *st)
{
    struct slm_state *m = &st->menu;
    struct sel *s = &st->s;
    u32 bank = m->bank ^ 1u, w, h;
    int dc = dc_preset(s->dcw, s->dch);
    for (u32 i = 0; i < N_DC; i++) slm_row_set(&m->row[0][i], DCN[i], DCW[i], DCH[i], 1, 0);
    slm_row_set(&m->row[0][N_DC], "CUSTOM", 0, 0, 1, 1);
    m->count[0] = N_DC + 1u;
    m->current[0] = dc >= 0 ? (u32)dc : N_DC;
    res_now(st, &w, &h);
    int ri = res_hit(st, w, h);       /* also populates st->list */
    u32 nr = st->n_list;
    if (nr >= 12u) { m->result = 20; return; }      /* the RES page holds 12 rows (slm_page.py SPEC cap; 0.0.6test: was 10) */
    for (u32 i = 0; i < nr; i++)
        slm_row_set(&m->row[1][i], st->list[i].lab, st->list[i].w, st->list[i].h, 1, 0);
    slm_row_set(&m->row[1][nr], "CUSTOM", 0, 0, 1, 1);
    m->count[1] = nr + 1u;
    m->current[1] = ri >= 0 ? (u32)ri : nr;
    fps_list(st);
    struct rat selected = {s->fps_n, s->fps_d};
    u32 nf = 0, fi = 0xFFFFFFFFu, ci = 0xFFFFFFFFu, have_custom = 0;
    for (u32 i = 0; i < st->n_fl; i++) if (st->fl_e[i].custom) have_custom = 1;
    u32 limit = SLM_ROWS - (have_custom ? 0u : 1u);
    for (u32 i = 0; i < st->n_fl; i++) {
        const struct fent *e = &st->fl_e[i];
        if (st->n_fl > limit && !e->std && !e->custom && !same(e->f, selected)) continue;
        if (nf >= SLM_ROWS) { m->result = 21; return; }
        struct slm_row *r = &m->row[2][nf];
        slm_row_set(r, "", e->f.n, e->f.d, !e->na, e->custom);
        if (e->custom) {
            ci = nf;
            u32 n = put_s(r->text, 0, SLM_TEXT, "CUSTOM ");
            f3_put(r->text, n, SLM_TEXT, e->f);
        } else fmt_rate(r->text, SLM_TEXT, e);
        if (same(e->f, selected)) fi = nf;
        nf++;
    }
    if (!nf) { slm_row_set(&m->row[2][0], "Unavailable", 0, 0, 0, 0); nf = 1; }
    if (!have_custom) {
        if (nf >= SLM_ROWS) { m->result = 21; return; }
        ci = nf;
        slm_row_set(&m->row[2][nf++], "CUSTOM", selected.n, selected.d, has_q(st), 1);
    }
    m->count[2] = nf;
    m->current[2] = fi < nf ? fi : has_q(st) && ci < nf ? ci : 0;
    slm_summaries(st, bank);
}

typedef u32 (*slm_fn1)(uintptr_t);
typedef u32 (*slm_fn2)(uintptr_t, uintptr_t);
typedef u32 (*slm_fn3)(uintptr_t, uintptr_t, uintptr_t);
static void slm_post(const char *name, u32 v)
{ ((slm_fn3)0xC0593F30u)(0, (uintptr_t)name, v); }
static uintptr_t slm_lookup(uintptr_t app, const char *name, u32 type)
{
    uintptr_t d = 0, r = W(app + 0x888u);
    if (!r || (r & 3u)) return 0;
    if (((slm_fn3)0xC05DB419u)(r + 0x60u, (uintptr_t)name, (uintptr_t)&d) || !d || (d & 3u)) return 0;
    return W(d) == type && sq_eq((const char *)(uintptr_t)W(d + 4u), name) ? d : 0;
}
static uintptr_t slm_variable(uintptr_t app, const char *name, u32 type, u32 initial)
{
    uintptr_t d = slm_lookup(app, name, type);
    if (!d) {
        u32 def[3] = {type, (u32)(uintptr_t)name, initial};
        if (((slm_fn3)0xC05DB309u)(app, 1, (uintptr_t)def)) return 0;
        d = slm_lookup(app, name, type);
    }
    return d;
}

/* v0.7.2test (live2 SS2784: the FPS row "1000" showed 關閉): a modelCSV TEXT cell that equals a .nloc string id is
 * drawn as that string (id 1000 = Off; the stock ids are 4 digits, or 4 digits + "_..."), any other text as it
 * stands.  A row text of exactly four digits gets ".0" so it stays a literal. */
static const char *slm_cell_text(const char *t, char *buf, u32 cap)
{
    u32 n = 0;
    while (t[n] >= '0' && t[n] <= '9') n++;
    if (n != 4u || t[n]) return t;
    u32 k = put_s(buf, 0, cap, t);
    put_s(buf, k, cap, ".0");
    return buf;
}

/* Native modelCSV copies cell text. Reject every other interface before edits. */
static u32 slm_model(struct st *st, u32 k)
{
    struct slm_state *m = &st->menu;
    uintptr_t app = W(0xC37B7048u), res = 0, inst = 0, f = 0;
    u32 have = 0, rows = 0;
    if (((slm_fn3)0xC05E0321u)(app, (uintptr_t)SLM_MODEL[k - 1u], (uintptr_t)&res) || !res) return 30;
    if (((slm_fn2)0xC05D8BD9u)(res, (uintptr_t)&have)) return 31;
    if (!have && ((slm_fn1)0xC05D8B79u)(res)) return 32;
    if (((slm_fn2)0xC05D8BF9u)(res, (uintptr_t)&inst) || !inst) return 33;
    if (((slm_fn2)0xC05D8359u)(inst, (uintptr_t)&f) || !f || (f & 3u)) return 34;
    if (W(f + 0x14u) != 0xC05F4861u || W(f + 0x18u) != 0xC05F4879u ||
        W(f + 0x30u) != 0xC05F4929u || W(f + 0x34u) != 0xC05F4941u || W(f + 0x38u) != 0xC05F4959u) return 35;
    if (((slm_fn2)W(f + 0x14u))(inst, (uintptr_t)&rows)) return 36;
    if (rows > SLM_ROWS) return 37;
    if (rows && ((slm_fn3)W(f + 0x38u))(inst, 0, rows)) return 38;
    for (u32 i = 0; i < m->count[k]; i++) {
        struct slm_row *r = &m->row[k][i];
        char no[12]; put_u(no, 0, sizeof no, i + 1u);
        if (((slm_fn3)W(f + 0x34u))(inst, i, 1) || ((slm_fn2)W(f + 0x18u))(inst, i)) return 39;
        char lit[SLM_TEXT + 2];
        const char *cell[6] = {no, slm_cell_text(r->text, lit, sizeof lit), "Popup", "blank", r->enabled ? "1" : "0", r->enabled ? "2" : "0"};
        for (u32 c = 0; c < 6u; c++) if (((slm_fn3)W(f + 0x30u))(inst, c, (uintptr_t)cell[c])) return 40;
    }
    u32 changed = 1;
    return ((slm_fn2)0xC05D83A9u)(inst, (uintptr_t)&changed) ? 41 : 0;
}

static void slm_publish(struct st *st, u32 lock);
static void slm_sync(struct st *st)
{
    struct slm_state *m = &st->menu;
    if (!m->ready) return;
    if (busy() || slm_format_locked()) {
        for (u32 k = 0; k < 3u; k++) slm_post(SLM_LOCK[k], 1);
        return;
    }
    slm_build(st);
    if (m->result) return;
    m->owed = 0;                                      /* the rows the event-time picks left stale are rebuilt */
    u32 lock = busy() || slm_format_locked();
    if (!lock) {
        m->result = slm_model(st, 1);
        if (!m->result) m->result = slm_model(st, 2);
        if (m->result) lock = 1;
    }
    slm_publish(st, lock);
}
/* the private variables for the rows slm_build / slm_model just made (v0.7.0test: split out of slm_sync so the
 * first-MENU setup does not build and write both native models a second time) */
static void slm_publish(struct st *st, u32 lock)
{
    struct slm_state *m = &st->menu;
    for (u32 k = 0; k < 3u; k++) slm_post(SLM_LOCK[k], lock);
    if (lock) return;
    for (u32 k = 0; k < 3u; k++) {
        slm_post(SLM_COUNT[k], m->count[k] - 1u); /* native List.max-value: last valid index */
        m->sent[k] = m->current[k];
        slm_post(SLM_VALUE[k], m->current[k]);
        ((slm_fn3)0xC0593FE0u)(0, (uintptr_t)SLM_SUMMARY[k], (uintptr_t)m->summary[m->bank][k]);
    }
    m->updates++;
}

/* is a row of a (possibly stale) list still offered under the current selection? (pure: QS lists only) */
static int slm_row_valid(struct st *st, u32 k, const struct slm_row *r)
{
    if (k == 0u) return 1;                            /* the DC presets do not depend on anything */
    if (k == 1u) return res_hit(st, r->a, r->b) >= 0;
    cell_now(st);
    fps_list(st);
    for (u32 i = 0; i < st->n_fl; i++)
        if (same(st->fl_e[i].f, (struct rat){r->a, r->b})) return !st->fl_e[i].na;
    return 0;
}

static int slm_pick(struct st *st, u32 k, u32 row)
{
    struct slm_state *m = &st->menu;
    if (k >= 3u || row >= m->count[k] || busy() || slm_format_locked() || !m->row[k][row].enabled) { m->rejected++; return 0; }
    struct slm_row r = m->row[k][row];
    if (r.custom) {
        const struct qsc_api *api = st->svc->find(st->svc, QSC_ID);
        /* v0.7.0test: FPS CUSTOM opens the FPS sub-QS on its FINE tile (container API 6), DC / RES their sub-QS */
        if (!api || api->magic != QSC_API_MAGIC || api->version < (k == 2u ? 6u : 5u) || !api->open) { m->rejected++; return 0; }
        if (!api->open(api, st->f[k].sup_id, FN_NAME[k], k == 2u ? QSC_OPEN_SUB_AT(0) : QSC_OPEN_SUB)) {
            m->rejected++; return 0;
        }
        if (k == 2u) { st->s.fps_n = r.a; st->s.fps_d = r.b; st->dirty = 1; }
        volatile char *request = slm_request();
        request[0] = 'Q'; request[1] = 'S'; request[2] = 0;
        slm_post("SLM_Go", ++m->go); m->opened++;
        return 1;
    }
    /* an earlier pick in this menu visit may have left this list stale (its native model is rebuilt at leave()):
     * the row must still be offered under the selection as it is now */
    if (m->owed && !slm_row_valid(st, k, &r)) { m->rejected++; return 0; }
    if (k == 0) { set_dc(st, (int)r.a, (int)r.b); st->s.daw = r.a; st->s.dah = r.b; }
    else if (k == 1) { set_res(st, (int)r.a, (int)r.b); st->s.raw = r.a; st->s.rah = r.b; }
    else { st->s.fps_n = r.a; st->s.fps_d = r.b; st->s.fine = 0; st->dirty = 1; }
    m->picks++;
    /* v0.7.1test: record only. The push (commit, LV reload), ap_idle and the native models wait for leave() */
    m->owed++;
    m->current[k] = m->sent[k] = row;                 /* the stock list commit already set SLM_x to this row */
    slm_summaries(st, m->bank ^ 1u);
    for (u32 j = 0; j < 3u; j++)                      /* queued string posts: the rows read the new values */
        ((slm_fn3)0xC0593FE0u)(0, (uintptr_t)SLM_SUMMARY[j], (uintptr_t)m->summary[m->bank][j]);
    return 1;
}

static u32 slm_changed(uintptr_t d)
{
    struct st *st = sq_ctx();
    struct slm_state *m = &st->menu;
    if (!m->ready || m->sending) return 0;
    for (u32 k = 0; k < 3u; k++) if (d == m->desc[k]) {
        u32 v = W(d + 8u);
        if (v < 0x80000000u) slm_pick(st, k, v);
        break;
    }
    return 0;
}

/* A native page change-event forwards format updates to a private pulse.
 * MV_RecordingFormat's one native callback belongs to the stock controller.
 * v0.7.1test: the format popup's commit is still running -- only the queued lock / value posts. The rows do not
 * depend on the format (and nothing can change the selection while it locks them), so the models stay current. */
static u32 slm_format_changed(uintptr_t d)
{
    struct st *st = sq_ctx();
    if (W(d + 8u) == 1u && st->menu.ready) slm_publish(st, busy() || slm_format_locked() || st->menu.result);
    return 0;
}

/* Defer NBR/model registration to the first UI layout callback. Pages switch
 * only after the private variables, CSV resources and initial model exist. */
static void slm_idle(struct st *st)
{
    struct slm_state *m = &st->menu;
    if (m->ready) { slm_sync(st); return; }
    if (m->attempted || busy()) return;
    uintptr_t app = W(0xC37B7048u);
    if (!app || (app & 3u) || !W(app + 0x888u) || !fst_reader()) return;
    m->attempted = 1;
    u32 t_setup = ap_now_us(), t_x;
    slm_build(st);
    if (m->result) return;
    const struct sl4_header *hd = (const struct sl4_header *)st->block;
    /* Definitions retain their names as well as the summary text. Protect
     * the complete resident file (private names/pack/page) and state text. */
    if (st->svc->borrow(st->svc, m, m + 1) != SL_OK ||
        st->svc->borrow(st->svc, st->block, st->block + hd->file_len) != SL_OK) { m->result = 50; return; }
    for (u32 k = 0; k < 3u; k++) {
        m->desc[k] = slm_variable(app, SLM_PICK[k], 0, 0xFFFFFFFFu);
        if (!m->desc[k] || !slm_variable(app, SLM_VALUE[k], 0, m->current[k]) ||
            !slm_variable(app, SLM_COUNT[k], 0, m->count[k] - 1u) ||
            !slm_variable(app, SLM_LOCK[k], 0, 1) ||
            !slm_variable(app, SLM_SUMMARY[k], 2, (u32)(uintptr_t)m->summary[m->bank][k])) {
            m->result = 51; return;
        }
        m->sent[k] = m->current[k];
    }
    if (!slm_variable(app, "SLM_FpsFocus", 0, 0) || !slm_variable(app, "SLM_Go", 0, 0) ||
        !slm_variable(app, "SLM_Refresh", 0, 0xFFFFFFFFu)) { m->result = 51; return; }
    typedef u32 (*load_fn)(uintptr_t, const void *, u32, uintptr_t *);
    if (((load_fn)0xC05E84D9u)(app, SLM_PACK, sizeof SLM_PACK, &m->reader) || !m->reader) { m->result = 52; return; }
    t_x = ap_now_us();
    m->result = slm_model(st, 1);
    if (!m->result) m->result = slm_model(st, 2);
    st->lt[13] = ap_now_us() - t_x;                   /* v0.7.0test timing: both native models */
    if (m->result) return;
    struct uia_outcome out;
    t_x = ap_now_us();
    m->result = fpui_stock_apply(st->svc, SLM_PAGE, sizeof SLM_PAGE, &out);
    st->lt[12] = ap_now_us() - t_x;                   /* the two page copies */
    if (m->result) { m->result += 100u; return; }
    /* v0.7.21test (Bei 11-03, choice c): a custom clip's playback HUD hides the misleading FHD label -- the
     * Playback page's blank Resolution frame (apply/pb_page.py), selected only for a non-stock clip; stock clips
     * keep frames 0/1/2.  Its own result: a failure leaves the stock label and never the menu. */
    if (st->ap_init_rc == AP_OK && st->pb_ui_result != UIA_OK) {
        struct uia_outcome pb;
        st->pb_ui_result = fpui_stock_apply(st->svc, AP_PB_PAGE, sizeof AP_PB_PAGE, &pb);
        if (st->pb_ui_result == UIA_OK) ap_pb_ctl(st->ap_mem, 2, AP_PB_PAGE_FRAME);
    }
    *slm_request() = 0; /* type3 change events fire again on page construction */
    for (u32 k = 0; k < 3u; k++)
        ((slm_fn3)0xC0560FB0u)(0xC37B7048u, (uintptr_t)SLM_PICK[k], (uintptr_t)slm_changed);
    ((slm_fn3)0xC0560FB0u)(0xC37B7048u, (uintptr_t)"SLM_Refresh", (uintptr_t)slm_format_changed);
    m->ready = 1;
    /* the rows and both models above are current: publish them (v0.6.0 ran slm_sync here, building them again) */
    slm_publish(st, busy() || slm_format_locked());
    st->lt[14] = ap_now_us() - t_setup;
}
#endif
