/* PreCap's row on the fpSup page (loader v4).
 *
 * Called from precap.S's entry: r0 = the row area inside the sup's block,
 * r1 = the state base, r2 = svc.  Returns page_add's result; a <0 result is
 * not fatal -- the hooks work without a row.
 *
 * Only svc->page_add is used.  The fpSup page keeps the row pointer, so the
 * row, its strings and everything they point at must stay resident: they live
 * in the sup's block, which is why the entry returns SL_KEEP.
 *
 * The switch is ON at every boot (the user 2026-10-27: 默认 ON, 装上就生效).
 * It is deliberately not saved: pre-capture changes how many frames a burst
 * produces, so each session starts from a known state.
 *
 * Built -fropi, no data section: every string is written from immediates.
 */
#include <stdint.h>

typedef uint32_t u32;

struct sl_row {                             /* sloader4.h, first 32 bytes used */
    uint16_t kind;
    uint16_t n_choices;
    const char *title;
    const char *value;
    int (*get)(void *);
    int (*set)(void *, int);
    const char *const *choices;
    int (*open)(void *);
    void *arg;
};

#define SL_ROW_TOGGLE 2
#define PAGE_ADD      0x40u                 /* struct sl_svc, byte offset */
#define SVC_VERSION   0x00u
#define SVC_PAGE_ADD  0x40u

/* precap.S's state offsets */
#define P_PRE         0x50u
#define P_ON          0x9Cu

struct pc_row {
    struct sl_row row;
    const char *choices[2];
    u32 title[4];                           /* "PreCap", NUL-terminated     */
    u32 off[1];                             /* "OFF"                        */
    u32 on[1];                              /* "ON"                         */
    u32 *switch_on;                         /* precap.S P_ON                */
    void *state;
};

static int row_get(void *arg)
{
    struct pc_row *p = (struct pc_row *)arg;
    return *p->switch_on != 0;
}

static int row_set(void *arg, int v)
{
    struct pc_row *p = (struct pc_row *)arg;
    if (v != 0 && v != 1) return 1;
    *p->switch_on = (u32)v;
    return 0;
}

int precap_row_install(struct pc_row *p, u32 state, const void *svc)
{
    u32 api = *(const u32 *)((const char *)svc + SVC_VERSION);
    int (*page_add)(const void *, const struct sl_row *);
    if (!svc || api < 5u) return -3;        /* SL_BADARG */
    page_add = *(int (**)(const void *, const struct sl_row *))
               ((const char *)svc + SVC_PAGE_ADD);
    if (!page_add) return -3;

    p->title[0] = 0x43657250u;              /* "PreC" */
    p->title[1] = 0x00007061u;              /* "ap"   -> "PreCap" */
    p->off[0] = 0x0046464Fu;                /* "OFF"  */
    p->on[0] = 0x00004E4Fu;                 /* "ON"   */
    p->choices[0] = (const char *)p->off;
    p->choices[1] = (const char *)p->on;
    p->switch_on = (u32 *)(uintptr_t)(state + P_ON);
    p->state = (void *)(uintptr_t)state;

    p->row.kind = SL_ROW_TOGGLE;
    p->row.n_choices = 2;
    p->row.title = (const char *)p->title;
    p->row.value = 0;
    p->row.get = row_get;
    p->row.set = row_set;
    p->row.choices = p->choices;
    p->row.open = 0;
    p->row.arg = p;
    return page_add(svc, &p->row);
}
