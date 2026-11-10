/* QSTest: a tiny QS container client (projects/qs-container/qsc.h), so the
 * container can be tried without SensorLab.  Its functions come from the
 * host's config (build_qstest.py; default two: "QS Test A" / "QS Test B"); the
 * table is filled at entry (-fropi: no pointers in data) and provided under
 * QSC_TAG(sup_id).  Nothing else: no hooks, no claims.
 *
 * A function whose config flag Q_DEMO is set (default: A) is a counter: its QS
 * value is "N=<count>", the dial adjusts it, and AEL opens two sub-items:
 * "Count" (the same counter, dialled) and "Toggle" (Off / On, any dial step
 * flips it), "Ratio" (a lock icon; the dial flips it); v0.2.1 adds the small line,
 * the footer (C0..C4; the Count spinner; Toggle OFF | ON) and the lock.  Q_LOCK adds QSC_F_LOCK_REC (default: A).  Other functions (B)
 * show their label as value, take no dial and have no sub-QS.  Values live
 * in RAM only. */
#include <stdint.h>
#include "sloader4.h"
#include "qsc.h"

typedef uint32_t u32;
#define USED __attribute__((used))

#define CFG_MAGIC 0x31545351u          /* "QST1" */
enum { Q_DEMO = 1u, Q_LOCK = 2u, Q_FINE = 4u,    /* Q_FINE (API 4): a fine-mode counter "QS Test C" */
       Q_GO = 8u,                                /* API 7: AEL opens a stock page (QSC_F_GO); config bits 8..11 =
                                                    the target (0: QSC_GO_READQR) */
       Q_DIAL = 16u };                           /* API 8: QSC_F_DIAL_HINT on the function */
#ifdef QST_API3
#define QST_MAGIC QSC_TABLE_MAGIC
#else
#define QST_MAGIC QSC_TABLE_MAGIC4
#endif
struct cfg {
    u32 magic, sup_id, n, state_off;
    u32 name_off[QSC_MAX], label_off[QSC_MAX], icon_off[QSC_MAX], flags[QSC_MAX];
    u32 sub_label_off[3], on_off, off_off;     /* "Count", "Toggle", "Ratio", "On", "Off" */
    u32 step_off, locked_off, free_off, opt_off[5];   /* "STEP 1", "LOCK", "FREE", "C0".."C4" */
};
struct demo { int count; u32 toggle, lock, fine, fines, unfines, last_step; char text[QSC_VALUE];
              const char *on, *off, *step, *opt[5], *locked, *free; };
struct st {
    struct qsc_func f[QSC_MAX];
    struct qsc_table t;
    u32 leaves;
    struct qsc_sub sub[QSC_MAX][3];
    struct qsc_subs subs[QSC_MAX];
    struct demo d[QSC_MAX];
};

static const char *qt_value(void *arg) { return (const char *)arg; }

/* "N=<count>" without division (-fropi blocks have no libgcc). */
static const char *qt_count_text(void *arg)
{
    struct demo *d = (struct demo *)arg;
    int v = d->count;
    u32 n = 0, started = 0;
    d->text[n++] = 'N';
    d->text[n++] = '=';
    if (v < 0) { d->text[n++] = '-'; v = -v; }
    for (int p = 1000; p; p = p == 1000 ? 100 : p == 100 ? 10 : p == 10 ? 1 : 0) {
        int digit = 0;
        while (v >= p) { v -= p; digit++; }
        if (digit || started || p == 1) { d->text[n++] = (char)('0' + digit); started = 1; }
    }
    d->text[n] = 0;
    return d->text;
}

static int qt_count_adjust(void *arg, int step)
{
    struct demo *d = (struct demo *)arg;
    d->last_step = (u32)step;
    d->count += step;
    if (d->count > 999) d->count = 0;
    if (d->count < 0) d->count = 999;
    return 0;
}

static u32 qt_mod5(int v) { while (v >= 5) v -= 5; return (u32)v; }

/* A: "STEP 1" under the value; the footer lists C0..C4, the current one = count mod 5. */
static const char *qt_count_small(void *arg, uint32_t *flags) { (void)flags; return ((struct demo *)arg)->step; }
static uint32_t qt_count_footer(void *arg, struct qsc_foot *f)
{
    struct demo *d = (struct demo *)arg;
    for (u32 k = 0; k < 5u; k++) f->label[k] = d->opt[k];
    f->n = 5;
    f->cur = qt_mod5(d->count);
    return 5;
}
/* the "Count" sub-item: a numeric spinner footer */
static uint32_t qt_count_spin(void *arg, struct qsc_foot *f)
{
    f->label[0] = qt_count_text(arg);
    f->n = 1;
    f->spin = 1;
    return 1;
}

static const char *qt_toggle_text(void *arg)
{
    struct demo *d = (struct demo *)arg;
    return d->toggle ? d->on : d->off;
}

static int qt_toggle_adjust(void *arg, int step)
{
    struct demo *d = (struct demo *)arg;
    (void)step;
    d->toggle ^= 1u;
    return 0;
}

/* "Toggle": footer OFF | ON; its small line ("STEP 1") is approximate while On */
static uint32_t qt_toggle_footer(void *arg, struct qsc_foot *f)
{
    struct demo *d = (struct demo *)arg;
    f->label[0] = d->off;
    f->label[1] = d->on;
    f->small[1] = d->step;
    f->approx = 2u;
    f->n = 2;
    f->cur = d->toggle;
    return 2;
}
static const char *qt_toggle_small(void *arg, uint32_t *flags)
{
    struct demo *d = (struct demo *)arg;
    if (d->toggle) *flags |= QSC_T_APPROX;
    return d->step;
}

/* C (Q_FINE, API 4): AEL toggles fine mode; the footer is C0..C4 with C1 grey ("no C1"), C2 custom (yellow),
 * C3 marked; in fine mode a spinner of the count, marked when the count is a multiple of 5. */
static int qt_fine(void *arg, int on)
{
    struct demo *d = (struct demo *)arg;
    d->fine = on ? 1u : 0u;
    if (on) d->fines++; else d->unfines++;
    return 1;
}
static uint32_t qt_fine_footer(void *arg, struct qsc_foot *f)
{
    struct demo *d = (struct demo *)arg;
    if (d->fine) {
        f->label[0] = qt_count_text(arg);
        f->n = 1;
        f->spin = 1;
        f->mark = qt_mod5(d->count < 0 ? -d->count : d->count) == 0 ? 1u : 0u;
        return 1;
    }
    for (u32 k = 0; k < 5u; k++) f->label[k] = d->opt[k];
    f->small[1] = d->off;
    f->grey = 2u; f->custom = 4u; f->mark = 8u;
    f->n = 5;
    f->cur = qt_mod5(d->count < 0 ? -d->count : d->count);
    return 5;
}
static void qt_leave(void *arg) { ((struct st *)arg)->leaves++; }

/* Q_GO (API 7): fine(arg, 1) is the go request -- counted in fines, answered with `toggle` (1 at entry: go);
 * fine(arg, 0) would be counted in unfines (the container must never call it for a GO function). */
static int qt_go(void *arg, int on)
{
    struct demo *d = (struct demo *)arg;
    if (on) d->fines++; else d->unfines++;
    return (int)d->toggle;
}

/* "Ratio": a lock / unlock icon instead of its title; the dial flips it */
static int qt_lock_state(void *arg) { return ((struct demo *)arg)->lock ? QSC_LOCK_SHUT : QSC_LOCK_OPEN; }
static const char *qt_lock_text(void *arg) { struct demo *d = (struct demo *)arg; return d->lock ? d->locked : d->free; }
static int qt_lock_adjust(void *arg, int step) { (void)step; ((struct demo *)arg)->lock ^= 1u; return 0; }

USED int sup_entry(void *block, const struct sl_svc *svc, const char *path)
{
    const struct sl4_header *h = (const struct sl4_header *)block;
    const struct cfg *c = (const struct cfg *)((const uint8_t *)block + SL4_HEADER_LEN);
    (void)path;
    if (svc->version < 5u || c->magic != CFG_MAGIC || !c->n || c->n > QSC_MAX ||
        c->state_off < h->file_len || c->state_off + sizeof(struct st) > h->block_size)
        return SL_RELEASE;
    struct st *s = (struct st *)((uint8_t *)block + c->state_off);
    const char *b = (const char *)block;
    for (u32 i = 0; i < c->n; i++) {
        struct qsc_func *f = &s->f[i];
        const char *nm = b + c->name_off[i];
        f->sup_id = c->sup_id;
        for (u32 k = 0; k < QSC_NAME; k++) f->name[k] = nm[k];
        f->label = b + c->label_off[i];
        f->icon = c->icon_off[i] ? b + c->icon_off[i] : 0;
        f->flags = QSC_F_CINE | ((c->flags[i] & Q_LOCK) ? QSC_F_LOCK_REC : 0u);
        if (c->flags[i] & Q_DIAL) f->flags |= QSC_F_DIAL_HINT;
        f->state = 0;
        f->small = 0;
        f->footer = 0;
        f->reserved = 0;
        if (c->flags[i] & Q_GO) {
            struct demo *d = &s->d[i];
            u32 go = (c->flags[i] & QSC_GO_MASK) >> 8;
            d->count = 0; d->fine = 0; d->fines = 0; d->unfines = 0; d->toggle = 1;
            f->value = qt_count_text;
            f->adjust = 0;
            f->fine = qt_go;
            f->flags |= QSC_F_TITLE | QSC_F_GO(go ? go : QSC_GO_READQR);
            f->arg = d;
            f->sub = 0;
            continue;
        }
        if (c->flags[i] & Q_FINE) {
            struct demo *d = &s->d[i];
            d->count = 0; d->fine = 0; d->off = b + c->off_off;
            for (u32 k = 0; k < 5u; k++) d->opt[k] = b + c->opt_off[k];
            f->value = qt_count_text;
            f->adjust = qt_count_adjust;
            f->footer = qt_fine_footer;
            f->fine = qt_fine;
            f->flags |= QSC_F_TITLE;
            f->arg = d;
            f->sub = 0;
            continue;
        }
        for (u32 j = 0; j < 3u; j++) {
            s->sub[i][j].reserved = 0;
            s->sub[i][j].icon = 0; s->sub[i][j].small = 0; s->sub[i][j].footer = 0; s->sub[i][j].lock = 0;
        }
        if (c->flags[i] & Q_DEMO) {
            struct demo *d = &s->d[i];
            d->count = 0; d->toggle = 0; d->lock = 1; d->on = b + c->on_off; d->off = b + c->off_off;
            d->step = b + c->step_off; d->locked = b + c->locked_off; d->free = b + c->free_off;
            for (u32 k = 0; k < 5u; k++) d->opt[k] = b + c->opt_off[k];
            f->value = qt_count_text;
            f->adjust = qt_count_adjust;
            f->small = qt_count_small;
            f->footer = qt_count_footer;
            f->arg = d;
            s->sub[i][0].label = b + c->sub_label_off[0];
            s->sub[i][0].value = qt_count_text;
            s->sub[i][0].adjust = qt_count_adjust;
            s->sub[i][0].footer = qt_count_spin;
            s->sub[i][0].arg = d;
            s->sub[i][1].label = b + c->sub_label_off[1];
            s->sub[i][1].value = qt_toggle_text;
            s->sub[i][1].adjust = qt_toggle_adjust;
            s->sub[i][1].small = qt_toggle_small;
            s->sub[i][1].footer = qt_toggle_footer;
            s->sub[i][1].arg = d;
            s->sub[i][2].label = b + c->sub_label_off[2];
            s->sub[i][2].value = qt_lock_text;
            s->sub[i][2].adjust = qt_lock_adjust;
            s->sub[i][2].lock = qt_lock_state;
            s->sub[i][2].arg = d;
            s->subs[i].n = 3;
            s->subs[i].item = s->sub[i];
            f->sub = &s->subs[i];
        } else {
            f->value = qt_value;
            f->adjust = 0;
            f->arg = (void *)f->label;
            f->sub = 0;
        }
    }
    s->t.magic = QST_MAGIC;
    s->t.n = c->n;
    s->t.f = s->f;
    s->leaves = 0;
#ifndef QST_API3
    s->t.leave = qt_leave;
    s->t.leave_arg = s;
#endif
    svc->publish(svc);
    return svc->provide(svc, QSC_TAG(c->sup_id), &s->t) == SL_OK ? SL_KEEP : SL_RELEASE;
}
