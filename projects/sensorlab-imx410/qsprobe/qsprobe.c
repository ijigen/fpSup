/* SensorLab-IMX410 QS probe: four new functions (DC / RES / FPS / QUAL) in the
 * stock custom-QS editor's list, staged so the mechanism can be checked on the
 * camera one step at a time.  NOT the product: no QS page frames (NBU), no
 * behaviour behind the ids.  Research: projects/qs-touch/notes/
 * QS_ADD_FUNCTION_RESEARCH.md; this probe: README.md next to this file.
 *
 *   stage 1  the editor CSV rows (Y2_3_CINE*.cvm, + the list maximum)
 *   stage 2  + the UI <-> internal converter layer (UI 49.. <-> internal 54..)
 *   stage 3  + the save swap: our internal ids never reach the settings flash
 *            (placeholder in the serialised image, the truth in this BIN's
 *            record, put back after boot), and the RecommendedSetting reader
 *            (QR code) sees the placeholder too
 *
 * One source, the stage is a word of the host-made config (build_qsprobe.py).
 * Loader v4 (fpSup/loader-v4/sloader4.h), -fropi Thumb, .text only: no
 * .rodata, no division, no struct copies.  Firmware Ver.5.02. */
#include <stdint.h>
#include "sloader4.h"
#include "fpui_stock.c"

typedef uint32_t u32;
typedef uint8_t u8;
#define USED __attribute__((used))
#define W(a) (*(volatile u32 *)(uintptr_t)(a))
#define B8(a) (*(volatile u8 *)(uintptr_t)(a))

/* ---- firmware (Ver.5.02) --------------------------------------------------- */
#define CONV_GET     0xC058C4D0u  /* FUN_c058c4d0: builds once, returns the singleton */
#define CONV         0xC37B7724u  /* {0x44, vtable}                                   */
#define CONV_VT      0xC37B7728u
#define VT_STOCK     0xC2DEAD7Cu
#define VT_PRE       8u           /* the two words before the vtable, copied too      */
#define VT_BYTES     0x55Cu
#define VT_CINE      0x344u       /* MenuValueConverterBase v207: CINE {internal, ui}  */
#define TAB_MAX      96u          /* pairs: 51 stock + every layer's                   */
#define SAVE_SITE    0xC0088C60u  /* MenuSettingStorage::v2: bl FUN_c0088660(store, image) */
#define SAVE_STOCK   0xEBFFFE7Eu
#define REC_SITE     0xC053DBF8u  /* FUN_c053db98 (RecommendedSetting): bl FUN_c0061b08 */
#define REC_STOCK    0xEBEC8FC2u
#define FV_SITE      0xC05E5BECu  /* the shared file redirect (fv_handler.S)          */
#define FV_STOCK     0x60681840u
#define STORE        0xC31AE3B0u  /* MenuSettingStorage_w71c1 (FUN_c008acf0)          */
#define STORE_IMG_A  0xCu         /* the image v2 serialises (0x4F00 bytes)           */
#define STORE_IMG_B  0x58D4u      /* the other one FUN_c008b258 may hand out          */
#define STORE_SEL    0xB19Cu      /* byte: 0 = A                                      */
#define QS_ARR0      0x23E8u      /* FUN_c00b70b0: item 0xD3's eight slots, two sets  */
#define QS_ARR1      0x2700u
#define SETTINGS_GET 0xC0057AE8u
#define IS_CINE      0xC0058340u
#define QS_GET       0xC0061B08u
#define TO_UI        0xC06C7B28u
#define POST_INT     0xC0593F30u
#define QS_NAME0     0xC2DEE70Eu  /* "MV_QSMENU_QS1", +0x10 each (v288's strings)     */
#define F_CTOR  0xC0365E90u
#define F_OPEN  0xC0365FB0u
#define F_READ  0xC0366060u
#define F_WRITE 0xC03660E8u
#define F_SEEK  0xC03661E0u
#define F_CLOSE 0xC0366020u
#define F_DTOR  0xC0365ED0u
#define MOV_SELECTOR   0xC347D1D4u  /* res-custom busy(): recording / writer active */
#define MOVREC_DEFAULT 0xC347E08Fu
#define MOVREC_SEL21   0xC3476609u
#define XMP_FOBJ_PTR   0xC358E140u
#define MOV_ACTIVE     0xC35A952Cu
#define VENEER_LDR_PC  0xE51FF004u  /* ldr pc, [pc, #-4]: the next word (interworking) */

#define CFG_MAGIC 0x31505351u     /* "QSP1" */
#define ST_MAGIC  0x4E555251u     /* "QRUN" */
#define REC_MAGIC 0x31525351u     /* "QSR1" */
#define NSLOT     16u             /* two sets of eight                                */
#define REC_WORDS 20u             /* magic, placeholder, 16 slots, sum, 0             */
#define REC_SUM   18u
#define FO_BYTES  0x800u
#define DMA_BYTES (FO_BYTES + 0x200u)
#define NCSV      4u
#define KEY_LEN   10u             /* "#QSPKEYn##" -> ten decimal digits               */

enum { QF_NO_EMIT = 1u };         /* stage 3: do not re-post MV_QSMENU_QSn after restore */

/* The host's config, at block + 48 (build_qsprobe.py CFG). */
struct cfg {
    u32 magic, stage, n_ids, int_base, ui_base, placeholder;
    u32 fpui_off[2], fpui_len[2];
    u32 fv_entry, fv_table_word;
    u32 csv_stock[NCSV];
    u32 label_off[4];             /* 0: the CSV carries a stock KEY instead           */
    u32 rec_off, state_off, dma_off, flags;
};

/* Install results (st.result): 0 = everything this stage has is in. */
enum { R_OK = 0, R_CLAIM_VT = 1, R_PREV_VT = 2, R_COLLIDE = 3, R_CLAIM_SAVE = 4,
       R_CLAIM_REC = 5, R_CHAIN = 6, R_CAVE = 7 };

struct st {
    u32 magic, stage, result, csv_result, csv_op, key_patched;   /* 0..20 */
    const struct sl_svc *svc;                                     /* 24 */
    const u8 *block;
    const struct cfg *cfg;
    const char *path;
    u32 n, ibase, ubase, ph;                                      /* 40 */
    /* stage 2 */
    u32 prev_vt, prev_cine, src, src_n, tab_ok, tab_n, collide;   /* 56 */
    u32 vt[(VT_PRE + VT_BYTES) / 4u];                             /* 84 */
    u32 tab[2u * TAB_MAX];
    /* stage 3 */
    u32 next_save, next_rec, veneer;
    u32 saves, foreign, sanitized, rec_hits, restored, stale;
    u32 writes, write_fails, write_why, busy_skips;
    u32 rec[NSLOT];               /* what the BIN holds (read at boot, then written)  */
    u32 rec_valid, fv_claimed, emitted;
};

/* ---- the state pointer: a word in the code (writable at the cached alias) ---- */
__attribute__((noinline)) static u32 qp_ctx_at(void)
{
    u32 at;
    __asm__ volatile("adr %0, 1f\n\tb 2f\n\t.balign 4\n1:\t.word 0\n2:" : "=r"(at));
    return at;
}
static struct st *qp_ctx(void) { return (struct st *)(uintptr_t)W(qp_ctx_at()); }

typedef u32 (*fn0)(void);
typedef u32 (*fn1)(u32);
typedef u32 (*fn2)(u32, u32);
typedef u32 (*fn3)(u32, u32, u32);
typedef u32 (*fn4)(u32, u32, u32, u32);

static int ours_int(const struct st *s, u32 v) { return v - s->ibase < s->n; }
static int ours_ui(const struct st *s, u32 v) { return v - s->ubase < s->n; }
static u32 arr(u32 i) { return (i < 8u ? QS_ARR0 : QS_ARR1) + 4u * (i & 7u); }
static u32 bl_to(u32 site, u32 dest) { return 0xEB000000u | (((dest - site - 8u) >> 2) & 0xFFFFFFu); }
static u32 rec_sum(const u32 *w)
{
    u32 h = 2166136261u;
    for (u32 i = 0; i < REC_SUM; i++) {
        u32 v = w[i];
        for (u32 b = 0; b < 4u; b++) { h = (h ^ (v & 0xFFu)) * 16777619u; v >>= 8; }
    }
    return h;
}

/* ===== stage 2: the converter layer ======================================== */
/* The CINE table the firmware asks for (vtable +0x344, `blx`, r0 = converter,
 * r1 = where the table goes, returns the pair count): the layer below's pairs,
 * then ours.  Rebuilt only when the layer below hands out another table. */
static u32 qp_build(struct st *s, u32 prev, u32 n)
{
    s->tab_ok = 0;
    if (!prev || (prev & 3u) || n > TAB_MAX - s->n) return 0;
    for (u32 i = 0; i < n; i++) {
        u32 a = W(prev + 8u * i), b = W(prev + 8u * i + 4u);
        if (ours_int(s, a) || ours_ui(s, b)) { s->collide++; return 0; }
        s->tab[2u * i] = a;
        s->tab[2u * i + 1u] = b;
    }
    for (u32 j = 0; j < s->n; j++) {
        s->tab[2u * (n + j)] = s->ibase + j;
        s->tab[2u * (n + j) + 1u] = s->ubase + j;
    }
    s->tab_n = n + s->n;
    s->src = prev;
    s->src_n = n;
    s->tab_ok = 1;
    return 1;
}

static USED u32 qp_cine(u32 conv, u32 *out)
{
    struct st *s = qp_ctx();
    u32 prev = 0, n = ((u32 (*)(u32, u32 *))s->prev_cine)(conv, &prev);
    if ((s->tab_ok && prev == s->src && n == s->src_n) || qp_build(s, prev, n)) {
        *out = (u32)(uintptr_t)s->tab;
        return s->tab_n;
    }
    *out = prev;
    return n;
}

/* ===== stage 3: the save swap ============================================== */
static int busy(void)
{
    u32 sel = W(MOV_SELECTOR) == 0x21u ? MOVREC_SEL21 : MOVREC_DEFAULT;
    return B8(sel) || W(XMP_FOBJ_PTR) || B8(MOV_ACTIVE);
}

/* The record into this sup's own BIN, in place (open 7 = overwrite without
 * truncating), then read back.  Never creates: the file must still be this
 * sup (its 48-byte header) -- sup-writeback-must-not-create. */
static u32 qp_write(struct st *s, const u32 *slots)
{
    const struct sl_svc *svc = s->svc;
    u32 fo = (u32)(uintptr_t)svc->uncached(svc, s->block + s->cfg->dma_off);
    u32 buf = fo + FO_BYTES, back = buf + 0x100u, ok = 0, got = 0;
    if (svc->file_is(svc, s->path, s->block, SL4_HEADER_LEN) != SL_OK) return 2;
    W(buf) = REC_MAGIC;
    W(buf + 4u) = s->ph;
    for (u32 i = 0; i < NSLOT; i++) W(buf + 8u + 4u * i) = slots[i];
    {
        u32 tmp[REC_SUM];
        for (u32 i = 0; i < REC_SUM; i++) tmp[i] = W(buf + 4u * i);
        W(buf + 4u * REC_SUM) = rec_sum(tmp);
    }
    W(buf + 4u * (REC_SUM + 1u)) = 0;
    ((fn2)F_CTOR)(fo, 1);
    if (((fn3)F_OPEN)(fo, (u32)(uintptr_t)s->path, 7)) {
        if (((fn3)F_SEEK)(fo, s->cfg->rec_off, 0) &&
            ((fn3)F_WRITE)(fo, buf, 4u * REC_WORDS) &&
            ((fn3)F_SEEK)(fo, s->cfg->rec_off, 0)) {
            for (u32 i = 0; i < REC_WORDS; i++) W(back + 4u * i) = 0xFFFFFFFFu;
            ((fn4)F_READ)(fo, back, 4u * REC_WORDS, (u32)(uintptr_t)&got);
            ok = got == 4u * REC_WORDS;
            for (u32 i = 0; ok && i < REC_WORDS; i++) if (W(back + 4u * i) != W(buf + 4u * i)) ok = 0;
        }
        ((fn1)F_CLOSE)(fo);
    }
    ((fn2)F_DTOR)(fo, 2);
    return ok ? 0 : 3;
}

static void qp_record(struct st *s, const u32 *slots)
{
    u32 same = 1;
    for (u32 i = 0; i < NSLOT; i++) if (slots[i] != s->rec[i]) same = 0;
    if (same) return;
    if (busy()) { s->busy_skips++; return; }
    u32 why = qp_write(s, slots);
    s->write_why = why;
    if (why) { s->write_fails++; return; }
    s->writes++;
    for (u32 i = 0; i < NSLOT; i++) s->rec[i] = slots[i];
}

/* Replaces `bl FUN_c0088660(store, image)` in v2 (power-off save, shell `menu
 * save`): the image FUN_c0088660 copies into the flash buffer holds the
 * placeholder where we hold our ids; RAM gets them back right after. */
static USED u32 qp_save(u32 store, u32 image)
{
    struct st *s = qp_ctx();
    u32 old[NSLOT], slots[NSLOT], mask = 0, mine = image == STORE + STORE_IMG_A;
    s->saves++;
    for (u32 i = 0; i < NSLOT; i++) {
        slots[i] = 0;
        if (!mine) continue;
        u32 a = image + arr(i), v = W(a);
        if (ours_int(s, v)) { old[i] = v; slots[i] = v; W(a) = s->ph; mask |= 1u << i; }
    }
    if (!mine) s->foreign++;
    u32 r = ((fn2)s->next_save)(store, image);
    for (u32 i = 0; i < NSLOT; i++)
        if (mask & (1u << i)) { W(image + arr(i)) = old[i]; s->sanitized++; }
    if (mine) qp_record(s, slots);
    return r;
}

/* Replaces `bl FUN_c0061b08(settings, k)` in the RecommendedSetting getter:
 * its export table has no entry for our ids (FUN_c0548208 asserts and loops). */
static USED u32 qp_rec(u32 settings, u32 k)
{
    struct st *s = qp_ctx();
    u32 v = ((fn2)s->next_rec)(settings, k);
    if (ours_int(s, v)) { s->rec_hits++; return s->ph; }
    return v;
}

/* After boot: the record says which slots were ours at the last save; a slot
 * that still holds the placeholder gets its id back. */
static void qp_restore(struct st *s)
{
    const u32 *r = (const u32 *)(s->block + s->cfg->rec_off);
    u32 tmp[REC_SUM];
    for (u32 i = 0; i < REC_SUM; i++) tmp[i] = r[i];
    if (r[0] != REC_MAGIC || r[1] != s->ph || r[REC_SUM] != rec_sum(tmp)) return;
    for (u32 i = 0; i < NSLOT; i++) if (r[2u + i] && !ours_int(s, r[2u + i])) return;
    s->rec_valid = 1;
    u32 img = STORE + (B8(STORE + STORE_SEL) ? STORE_IMG_B : STORE_IMG_A);
    for (u32 i = 0; i < NSLOT; i++) {
        u32 id = r[2u + i];
        s->rec[i] = id;
        if (!id) continue;
        if (W(img + arr(i)) == s->ph) { W(img + arr(i)) = id; s->restored++; }
        else s->stale++;                 /* changed while we were away: theirs now */
    }
}

static void qp_emit(struct st *s)
{
    s->emitted++;
    u32 set = ((fn0)SETTINGS_GET)();
    if (((fn1)IS_CINE)(set) != 1u) return;
    for (u32 k = 0; k < 8u; k++) {
        u32 v = ((fn2)QS_GET)(((fn0)SETTINGS_GET)(), k);
        u32 ui = ((fn2)TO_UI)(CONV, v);
        ((fn3)POST_INT)(0, QS_NAME0 + 0x10u * k, ui);
    }
}

/* ===== the editor's CSV rows (all stages) =================================== */
static u32 qp_table(const struct cfg *c)
{
    u32 w = W(FV_SITE), hw1 = w & 0xFFFFu, hw2 = w >> 16, s, j1, j2, i1, i2, off;
    if ((hw1 & 0xF800u) != 0xF000u || (hw2 & 0xD000u) != 0x9000u) return 0;
    s = (hw1 >> 10) & 1u; j1 = (hw2 >> 13) & 1u; j2 = (hw2 >> 11) & 1u;
    i1 = 1u ^ (j1 ^ s); i2 = 1u ^ (j2 ^ s);
    off = s << 24 | i1 << 23 | i2 << 22 | (hw1 & 0x3FFu) << 12 | (hw2 & 0x7FFu) << 1;
    if (s) off |= 0xFE000000u;
    u32 veneer = FV_SITE + 4u + off, entry, table;
    if (veneer & 3u) return 0;
    entry = W(veneer + 4u);
    if (entry & 3u) return 0;
    table = W(entry - c->fv_entry + c->fv_table_word);
    return !table || (table & 3u) || W(table) != 0x56465346u ? 0 : table;
}

/* "#QSPKEYn##" in each copy -> the label's string id (its uncached address,
 * fpsup-ui's rule), ten decimal digits: ids are 0x40000000..0x7FFFFFFF. */
static u32 qp_keys(struct st *s)
{
    const struct cfg *c = s->cfg;
    u32 table = qp_table(c), done = 0, pw[KEY_LEN];
    if (!table) return 0;
    pw[KEY_LEN - 1u] = 1;
    for (u32 d = KEY_LEN - 1u; d > 0; d--) pw[d - 1u] = pw[d] * 10u;
    for (u32 f = 0; f < NCSV; f++) {
        u32 n = W(table + 8u), copy = 0, size = 0;
        for (u32 e = 0; e < n && e < 256u; e++)
            if (W(table + 16u + 12u * e) == c->csv_stock[f]) {
                copy = W(table + 20u + 12u * e);
                size = W(table + 24u + 12u * e);
            }
        for (u32 i = 0; copy && i + KEY_LEN <= size; i++) {
            u32 p = copy + i;
            if (B8(p) != '#' || B8(p + 1u) != 'Q' || B8(p + 2u) != 'S' || B8(p + 3u) != 'P' ||
                B8(p + 4u) != 'K' || B8(p + 5u) != 'E' || B8(p + 6u) != 'Y' || B8(p + 8u) != '#' ||
                B8(p + 9u) != '#')
                continue;
            u32 k = B8(p + 7u) - '0';
            if (k >= 4u || !c->label_off[k]) continue;
            u32 id = (u32)(uintptr_t)(s->block + c->label_off[k]) - SL_ALIAS;
            for (u32 d = 0; d < KEY_LEN; d++) {
                u32 digit = 0;
                while (id >= pw[d]) { id -= pw[d]; digit++; }
                B8(p + d) = (u8)('0' + digit);
            }
            done++;
        }
    }
    return done;
}

static void qp_csv(struct st *s)
{
    const struct cfg *c = s->cfg;
    const struct sl_svc *svc = s->svc;
    struct uia_outcome o;
    u32 w = W(FV_SITE);
    /* the redirect site: claimed with whoever else did (raw-view: SHARED_UI);
     * a foreign hook nobody claimed is left to its owner */
    /* the labels are handed to the firmware by id: it must never free them */
    if (c->label_off[0] && svc->borrow(svc, s->block, s->block + c->state_off) != SL_OK) {
        s->csv_result = 0x10;
        return;
    }
    if (w == FV_STOCK || svc->holder(svc, FV_SITE, 0))
        s->fv_claimed = svc->claim(svc, FV_SITE, 4, &(u32){FV_STOCK}, SL_SHARED_UI) == SL_OK;
    for (u32 b = 0; b < 2u; b++) {
        if (!c->fpui_len[b]) continue;
        u32 r = fpui_stock_apply(svc, s->block + c->fpui_off[b], c->fpui_len[b], &o);
        if (r != UIA_OK) { s->csv_result = r | (b + 1u) << 8; s->csv_op = o.op; return; }
    }
    s->key_patched = qp_keys(s);
    svc->publish(svc);
}

/* ===== entry ================================================================= */
static void hex8(char *p, u32 v)
{
    for (u32 i = 0; i < 8u; i++) {
        u32 d = (v >> (28u - 4u * i)) & 0xFu;
        p[i] = (char)(d < 10u ? '0' + d : 'A' + d - 10u);
    }
}
static void qp_log(struct st *s)
{
    char line[40];
    u32 n = 0;
    line[n++] = 'Q'; line[n++] = 'S'; line[n++] = 'P'; line[n++] = ' ';
    line[n++] = (char)('0' + s->stage); line[n++] = ' ';
    hex8(line + n, s->result << 16 | s->csv_result); n += 8; line[n++] = ' ';
    hex8(line + n, s->prev_vt); n += 8; line[n++] = ' ';
    hex8(line + n, s->restored << 16 | s->key_patched); n += 8;
    line[n] = 0;
    if (s->svc->log) s->svc->log(s->svc, line);
}

static int qp_fail(struct st *s, u32 why)
{
    s->result = why;
    qp_log(s);
    return SL_RELEASE;        /* nothing written yet but claims: the loader undoes them */
}

USED int sup_entry(void *block, const struct sl_svc *svc, const char *path)
{
    const struct sl4_header *h = (const struct sl4_header *)block;
    const struct cfg *c = (const struct cfg *)((const u8 *)block + SL4_HEADER_LEN);
    if (svc->version < 6u || c->magic != CFG_MAGIC || c->stage - 1u > 2u || c->n_ids - 1u >= 8u ||
        c->state_off < h->file_len || c->state_off + sizeof(struct st) > c->dma_off ||
        (c->dma_off & 63u) || c->dma_off + DMA_BYTES > h->block_size ||
        (c->stage == 3u && (c->rec_off + 4u * REC_WORDS > h->file_len || (c->rec_off & 3u))))
        return SL_RELEASE;
    struct st *s = (struct st *)((u8 *)block + c->state_off);
    s->magic = ST_MAGIC; s->stage = c->stage; s->svc = svc; s->block = (const u8 *)block; s->cfg = c;
    s->path = path; s->n = c->n_ids; s->ibase = c->int_base; s->ubase = c->ui_base; s->ph = c->placeholder;
    W(qp_ctx_at()) = (u32)(uintptr_t)s;
    svc->publish(svc);

    /* 1. claims (any refusal: RELEASE, nothing written) */
    if (c->stage >= 2u) {
        ((fn0)CONV_GET)();                                  /* built before we look at it */
        if (svc->claim(svc, CONV_VT, 4, &(u32){VT_STOCK}, SL_CHAIN) != SL_OK) return qp_fail(s, R_CLAIM_VT);
    }
    if (c->stage >= 3u) {
        if (svc->claim(svc, SAVE_SITE, 4, &(u32){SAVE_STOCK}, SL_CHAIN) != SL_OK) return qp_fail(s, R_CLAIM_SAVE);
        if (svc->claim(svc, REC_SITE, 4, &(u32){REC_STOCK}, SL_CHAIN) != SL_OK) return qp_fail(s, R_CLAIM_REC);
    }

    /* 2. prepare: the converter copy (on whatever layer is there now) */
    if (c->stage >= 2u) {
        u32 prev = W(CONV_VT);
        if (!prev || (prev & 3u) || prev < 0xC0000000u || !W(prev + VT_CINE)) return qp_fail(s, R_PREV_VT);
        for (u32 i = 0; i < (VT_PRE + VT_BYTES) / 4u; i++) s->vt[i] = W(prev - VT_PRE + 4u * i);
        s->prev_vt = prev;
        s->prev_cine = W(prev + VT_CINE);
        u32 t = 0, n = ((u32 (*)(u32, u32 *))s->prev_cine)(CONV, &t);
        if (!qp_build(s, t, n)) return qp_fail(s, s->collide ? R_COLLIDE : R_PREV_VT);
        s->vt[(VT_PRE + VT_CINE) / 4u] = (u32)(uintptr_t)&qp_cine;
    }
    if (c->stage >= 3u) {
        s->next_save = svc->chain_next(svc, SAVE_SITE, 0);
        s->next_rec = svc->chain_next(svc, REC_SITE, 0);
        if (!s->next_save || !s->next_rec) return qp_fail(s, R_CHAIN);
        u32 v = svc->cave_alloc(svc, 16);
        if (!v || (v & 7u)) return qp_fail(s, R_CAVE);
        W(v) = VENEER_LDR_PC; W(v + 4u) = (u32)(uintptr_t)&qp_save;
        W(v + 8u) = VENEER_LDR_PC; W(v + 12u) = (u32)(uintptr_t)&qp_rec;
        s->veneer = v;
        svc->publish(svc);
        /* 3. the save swap before anything can hold our ids */
        W(SAVE_SITE) = bl_to(SAVE_SITE, v);
        W(REC_SITE) = bl_to(REC_SITE, v + 8u);
        svc->publish(svc);
        qp_restore(s);
    }
    /* 4. the converter */
    if (c->stage >= 2u) {
        svc->publish(svc);
        W(CONV_VT) = (u32)(uintptr_t)&s->vt[VT_PRE / 4u];
        svc->publish(svc);
        if (c->stage >= 3u && s->restored && !(c->flags & QF_NO_EMIT)) qp_emit(s);
    }
    /* 5. the editor's rows (a failure leaves the rest in) */
    qp_csv(s);
    qp_log(s);
    return SL_KEEP;
}
