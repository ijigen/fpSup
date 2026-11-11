/* LUT4 -- Loader v4 development sup, Ver.5.02.
 *
 * Owns only its loader block. No firmware hooks, native ring writes, task,
 * DNG metadata writes or pretend Live View activation. render() is a bounded
 * reference processor for caller-owned, detached XYZ D65 Q20 samples.
 * The future ISP/CPU backend must establish frame ownership and calibration.
 *
 * All code/private data run cached; only the 8 KiB file object/read scratch
 * uses svc->uncached(). Copy completed reads into private cached LUT storage.
 * Entry returns. Rows, strings, callbacks, API and LUT survive staging free.
 */
#include "sloader4.h"
#include "lut4.h"
#include "fpsup_ui.c"
typedef uint32_t u32;
typedef uint64_t u64;
typedef uint16_t u16;
typedef int32_t i32;
typedef int64_t i64;
typedef uint8_t u8;
#define USED __attribute__((used))
#define Q 1048576
#define ONE 16777216u
#define CURVE_N (27u*256u+1u)
#define MAX_ASSET 0x400000u
#define MAX_NODE (1024*Q)
#define MAX_LINEAR (128*Q)
#define API_ID 0x3454554Cu                  /* LUT4 */
#define CFG_MAGIC 0x3443544Cu               /* LTC4 */
#define FILE_MAGIC 0x31554C46u              /* FLU1 */
#define FW(a, t) ((t)(uintptr_t)(a))
enum { OK=0, NO_FILE=-10, BAD_ASSET=-11, MODEL_PENDING=-12,
       NO_BACKEND=-13, BAD_INPUT=-14, NO_ACTIVE=-15, SAVE_FAILED=-16, RECORD_BUSY=-17,
       NO_MEMORY=-18 };                    /* borrow.c: recording, or the allocator said no */
#include "library4.h"
#include "cols.h"
struct lut4_state;
static int conv_ok(struct lut4_state *,u32);   /* conv.c: entry i has its .JFT */
static u32 conv_score(struct lut4_state *,u32);  /* conv.c: its .JFT match % + 1, 0 = none */
static int library_busy(void);                 /* library4.c: recording (borrow.c refuses then) */
struct lut_area { void *raw; u8 *p; u32 n; };  /* borrow.c: one borrowed area (raw = the allocator's pointer) */

/* Build-resolved offsets, all relative to the owned FSB4 block. */
struct cfg { u32 magic, state_off, io_off, asset_off, asset_cap, strings_off, strings_n, library_off, clist_off,
             icons_off, import_off, lvb_off, conv_off, chk_off; };   /* conv: conv.c's work region; chk: its ColorChecker (Q20) */   /* icons: import.c's COLOR tiles; lvb: lvb.c's region */
struct asset {
    u32 magic, version, header_len, total, checksum, n1, n3, curve_n;
    u32 matrix_off, curve_off, one_off, three_off, color, gamma, strength, output;
    i32 range1[9], range3[9];                /* low[3], high[3], reserved[3] */
    u8 source_sha256[32]; char title[64]; u8 reserved[24];
};
struct lut4_state {
    struct lut4_api api;
    const struct sl_svc *svc; const struct cfg *cfg; void *block;
    struct asset *asset;
    i32 file_status, last_error;
    u32 color, gamma, amount, rendered, outside1, outside3;
    struct sl_row rows[8];
    const char *colors[8], *common[6], *blackmagic[2], *amounts[5], *file_choices[1];
    const char *color_groups[3], *gamma_groups[2], *bmd_group[1], *amount_groups[2];
    struct sl_row home;
    const void *ui;
    u32 ui_page, ui_popup, ui_header;
    char ui_pager[8];
    struct lib_catalog *library;
    const char *self_path;
    u8 library_guard[64];
    char library_path[96];
    u32 ui_view, edit_index, ui_back_page, ui_focus, ui_goseq;
    u32 ui_marks;                      /* color_ui.c mark_lists: each list's step, 4 bits apiece (0 = written) */
    struct sl_row enabled_row, set_rows[2];
    const char *manager_choices[3];
    u32 ui_result; char ui_title[24];
    u32 ui_cache[240];                 /* color_ui.c: the last value / text posted per variable, + 1 (MV_COUNT <= this:
                                        * 11-05 163 vars in 160 slots wrote into clist below -> COLOR fell back to OFF) */
    struct lut_cols cols;              /* cols.c: our rows in COL-Share's COLOR list */
    u32 clist_result;                  /* api.clist: 0 = COL-Share has us; 8 none on the card (yet) */
    struct dng_ctx { struct lut4_state *s; u32 wrap, original, kind; } dng[3];   /* dng.c: one per writer function */
    u32 dng_result, dng_calls;         /* dng.c: 0 = the six DNG sites are ours; calls through them */
    struct {                           /* lvb.c: the active LUT on the ISP */
        u32 magic;                     /* LVB_MAGIC: the tests find the struct by it */
        u32 ready, installed, keyed, result, fits, key[5], shift, calls124, calls12d;
        i32 mat[9];                    /* table order, Q9 */
        u32 calls34, poffs;
        struct dng_ctx ctx[4];         /* 0x124, 0x12D, 0x34, 0x129 */
        u32 poff[4];                   /* the power-off object: {vt = poff - 8, stub, state, routine} */
        u32 jfts, ygam_posts;          /* sets built from a .JFT; YGAM writes after the stock one */
        u32 jft_why[4];                /* [0]: the last set's .JFT, why it was not used: 1xxxx read (count), 2 header, 3 cube, 4 key, 5 fnv, 6.. tables; 0 used */
        u32 fail_key[7], failed;       /* 2026-11-10: the key whose set could not be made (not tried again until it changes) */
        u32 sets, set_returns;         /* sets made (borrowed) / given back */
        u32 previews, preview_fail;    /* cursor previews built from a .JFT / not possible (no current .JFT, recording, memory) */
    } lvb;
    u32 lvb_result;                    /* lvb_install: 0 = the root words and DNG sites are ours */
    struct {                           /* conv.c: one conversion at a time */
        u32 magic;                     /* CONV_MAGIC: the tests find it */
        u32 state, index, base, pct, err, err_task, ticks, runs, done, last, iters;   /* iters: 0 = CONV_DIRECT_ITERS (tests: 1) */
        int tid;
        u32 color, gamma, amount, matrix, stats[3];
        u8 sha[32];                    /* the entry's identity: +16 of the file holds [0..7]; its name (lvb_jpath) all of it */
    } conv;
    u32 library_hidden;                /* library4.c: entries kept after library->h.count, their file gone (2026-11-06) */
    struct lut_area b_asset, b_fit, b_conv;   /* borrow.c: the areas borrowed now (library mode's asset, lvb's fit, conv) */
    struct lut_area b_set;             /* 2026-11-10 (Bei): the ISP set of the active (picked) row */
    struct lut_area b_prev;            /* ... and of the row the COLOR cursor previews (lvb_preview), while the menu is open */
    struct lut_area b_icon, b_jbuf;    /* a COLOR tile while COL-Share copies it; a .JFT being read */
    u32 borrows, returns, borrow_refused, borrow_failed;
};
_Static_assert(sizeof(struct lut4_state)<=4096,"state reservation");
_Static_assert(sizeof(struct asset)==256,"asset header");
static int library_update(struct lut4_state *,u32,u32,u32,u32,u32);
static int library_enabled(struct lut4_state *,u32,u32);
static int library_pick(struct lut4_state *,u32);
static void library_init(struct lut4_state *);
static struct lib_entry *edited(struct lut4_state *s) {
    return s->library && s->ui_view==VIEW_SETTINGS && s->edit_index<s->library->h.count
        ?&s->library->entries[s->edit_index]:0;
}
static u32 edit_color(struct lut4_state *s) { struct lib_entry *e=edited(s);return e?e->color:s->color; }
static u32 edit_gamma(struct lut4_state *s) { struct lib_entry *e=edited(s);return e?e->gamma:s->gamma; }
static u32 edit_amount(struct lut4_state *s) { struct lib_entry *e=edited(s);return e?e->amount:s->amount; }

static void copy(void *dst, const void *src, u32 n) {
    u8 *d=dst; const u8 *s=src; for(u32 i=0;i<n;i++) d[i]=s[i];
}
static const char *string(struct lut4_state *s, u32 index) {
    const u32 *offsets=(const u32 *)((uintptr_t)s->block+s->cfg->strings_off);
    return (const char *)s->block+offsets[index];
}
static int supported(u32 color,u32 gamma) { return color<8 && color!=2 && gamma<6 && gamma!=4; }
static u32 hash(const u8 *p,u32 n) {
    u32 h=2166136261u;
    for(u32 i=0;i<n;i++) h=(h^((i>=16 && i<20)?0:p[i]))*16777619u;
    return h;
}
static int validate(struct asset *a,u32 capacity) {
    if(capacity<sizeof *a || a->magic!=FILE_MAGIC || a->version!=1 || a->header_len!=sizeof *a ||
       a->total>capacity || a->total<sizeof *a || a->curve_n!=CURVE_N || a->output!=1 ||
       !supported(a->color,a->gamma) || a->strength>100 || a->strength%25u ||
       (a->n1 && (a->n1<2 || a->n1>4096)) || (a->n3 && (a->n3<2 || a->n3>65)) ||
       (!a->n1 && !a->n3) || !a->title[0] || a->title[63]) return BAD_ASSET;
    u32 m=sizeof *a, c=m+8*9*4, next=c+6*2*CURVE_N*4;
    if(a->matrix_off!=m || a->curve_off!=c || a->one_off!=(a->n1?next:0)) return BAD_ASSET;
    next+=a->n1*3*4;
    if(a->three_off!=(a->n3?next:0)) return BAD_ASSET;
    next+=a->n3*a->n3*a->n3*3*4;
    if(a->total!=next || hash((const u8 *)a,next)!=a->checksum) return BAD_ASSET;
    for(u32 k=0;k<2;k++) {
        const i32 *r=k?a->range3:a->range1;
        for(u32 j=0;j<3;j++) if(r[j]<-MAX_LINEAR || r[j+3]>MAX_LINEAR ||
            r[j]>=r[j+3] || r[j+6]) return BAD_ASSET;
    }
    const i32 *mat=(const i32 *)((uintptr_t)a+m);
    for(u32 i=0;i<8*9;i++) if(mat[i]<-16*Q || mat[i]>16*Q) return BAD_ASSET;
    const i32 *nodes=(const i32 *)((uintptr_t)a+c+6*2*CURVE_N*4);
    for(u32 i=0;i<(a->n1+a->n3*a->n3*a->n3)*3;i++)
        if(nodes[i]<-MAX_NODE || nodes[i]>MAX_NODE) return BAD_ASSET;
    return OK;
}

#include "borrow.c"

static int read_asset_path(struct lut4_state *s,const char *path) {
    const struct sl_svc *v=s->svc;
    u8 *io=v->uncached(v,(u8 *)s->block+s->cfg->io_off), *buf=io+4096;
    struct asset *a=(struct asset *)((u8 *)s->block+s->cfg->asset_off);
    u32 got=0; int result=NO_FILE;
    FW(0xC0365E90u,void (*)(void *,u32))(io,1);
    if(FW(0xC0365FB0u,u32 (*)(void *,const char *,u32))(io,path,1)) {
        FW(0xC0366060u,u32 (*)(void *,void *,u32,u32 *))(io,buf,sizeof *a,&got);
        result=BAD_ASSET;
        if(got==sizeof *a) {
            copy(a,buf,sizeof *a);
            if(a->total>=sizeof *a && a->total<=s->cfg->asset_cap) {
                u32 pos=sizeof *a;
                while(pos<a->total) {
                    u32 n=a->total-pos; if(n>4096) n=4096;
                    got=0;
                    FW(0xC0366060u,u32 (*)(void *,void *,u32,u32 *))(io,buf,n,&got);
                    if(got!=n) break;
                    copy((u8 *)a+pos,buf,n); pos+=n;
                }
                if(pos==a->total) {
                    got=0;
                    FW(0xC0366060u,u32 (*)(void *,void *,u32,u32 *))(io,buf,1,&got);
                    if(!got) result=validate(a,s->cfg->asset_cap);
                }
            }
        }
        FW(0xC0366020u,void (*)(void *))(io);
    }
    FW(0xC0365ED0u,void (*)(void *,u32))(io,2);
    if(result==OK) { s->asset=a; s->color=a->color; s->gamma=a->gamma; s->amount=a->strength; }
    return result;
}

static i32 curve(struct lut4_state *s,i32 value,u32 gamma) {
    if(gamma==3 || !value) return value;
    u32 mag=(u32)(value<0?-value:value);
    u32 e=0; for(u32 p=mag;p>1;p>>=1) e++;
    u32 base=1u<<e, index=e*256u, frac=0;
    if(e>=8) { u32 shift=e-8; index+=(mag-base)>>shift;
        frac=((mag-base)&((1u<<shift)-1u))<<(24-shift); }
    else index+=(mag-base)<<(8-e);
    const i32 *t=(const i32 *)((u8 *)s->asset+s->asset->curve_off)+
                (gamma*2u+(value<0?1u:0u))*CURVE_N;
    i64 y=t[index];
    if(frac) y+=(((i64)t[index+1]-t[index])*frac)>>24;
    return (i32)y;
}
static int matrix(struct lut4_state *s,const i32 *xyz,u32 color,i32 *out) {
    const i32 *m=(const i32 *)((u8 *)s->asset+s->asset->matrix_off)+9*color;
    for(u32 j=0;j<3;j++) {
        i64 sum=0; for(u32 k=0;k<3;k++) sum+=(i64)m[j*3+k]*xyz[k];
        sum>>=20;
        if(sum < -MAX_LINEAR || sum > MAX_LINEAR) return BAD_INPUT;
        out[j]=(i32)sum;
    }
    return OK;
}
static uint64_t coordinate(i32 x,const i32 *range,u32 c,u32 n,u32 *outside) {
    i32 low=range[c], high=range[c+3];
    if(x<low || x>high) (*outside)++;
    if(x<=low) return 0;
    if(x>=high) return (uint64_t)(n-1)*ONE;
    u32 rem=(u32)(x-low), span=(u32)(high-low), q=0;
    for(u32 i=0;i<24;i++) { rem<<=1; q<<=1; if(rem>=span) { rem-=span; q++; } }
    return (uint64_t)q*(n-1);
}
static void lookup(struct lut4_state *s,i32 *rgb) {
    struct asset *a=s->asset;
    if(a->n1) {
        const i32 *t=(const i32 *)((u8 *)a+a->one_off);
        for(u32 c=0;c<3;c++) {
            uint64_t p=coordinate(rgb[c],a->range1,c,a->n1,&s->outside1);
            u32 i=(u32)(p>>24), f=(u32)p&(ONE-1);
            if(i==a->n1-1) { i--; f=ONE; }
            rgb[c]=(i32)(((i64)t[i*3+c]*(ONE-f)+(i64)t[(i+1)*3+c]*f)>>24);
        }
    }
    if(a->n3) {
        const i32 *t=(const i32 *)((u8 *)a+a->three_off);
        u32 n=a->n3, idx[3], f[3], order[3]={0,1,2};
        for(u32 c=0;c<3;c++) {
            u32 p=coordinate(rgb[c],a->range3,c,n,&s->outside3); idx[c]=p>>24; f[c]=p&(ONE-1);
            if(idx[c]==n-1) { idx[c]--; f[c]=ONE; }
        }
        for(u32 i=1;i<3;i++) for(u32 j=i;j && f[order[j]]>f[order[j-1]];j--) {
            u32 temp=order[j]; order[j]=order[j-1]; order[j-1]=temp;
        }
        u32 weights[4]={ONE-f[order[0]],f[order[0]]-f[order[1]],f[order[1]]-f[order[2]],f[order[2]]};
        i64 sum[3]={0,0,0};
        for(u32 v=0;v<4;v++) {
            if(v) idx[order[v-1]]++;
            u32 p=((idx[2]*n+idx[1])*n+idx[0])*3;
            for(u32 c=0;c<3;c++) sum[c]+=(i64)t[p+c]*weights[v];
        }
        for(u32 c=0;c<3;c++) rgb[c]=(i32)(sum[c]>>24);
    }
}

static int color_get(void *arg) { return (int)(edit_color(arg)%3u); }
static int color_group_get(void *arg) { return (int)(edit_color(arg)/3u); }
static int gamma_get(void *arg) { return (int)(edit_gamma(arg)%3u); }
static int gamma_group_get(void *arg) {
    struct lut4_state *s=arg; return edit_color(s)==2?0:(int)(edit_gamma(s)/3u);
}
static int amount_get(void *arg) {
    u32 amount=edit_amount(arg); return (int)((amount/25u)%3u);
}
static int amount_group_get(void *arg) { return (int)(edit_amount(arg)/75u); }
static int monitor_get(void *arg) { (void)arg; return 0; }
static int file_get(void *arg) { (void)arg; return 0; }
static int file_set(void *arg,int v) { (void)arg; return v?SL_BADARG:OK; }
static void color_ui_refresh(struct lut4_state *s);
static void refresh(struct lut4_state *s) { color_ui_refresh(s); }
static void lvb_refresh(struct lut4_state *);
static void choices(struct lut4_state *s) {
    /* v4's native home-page popup has at most three items. Grouping keeps
     * every one of the 8 gamuts / 6 gammas / 5 strengths reachable. */
    u32 color=edit_color(s),gamma=edit_gamma(s),amount=edit_amount(s);
    s->rows[2].choices=s->colors+(color/3u)*3; s->rows[2].n_choices=(uint16_t)(color>=6?2:3);
    s->rows[3].choices=color==2?s->bmd_group:s->gamma_groups;
    s->rows[3].n_choices=(uint16_t)(color==2?1:2);
    s->rows[4].choices=color==2?s->blackmagic:s->common+(gamma/3u)*3;
    s->rows[4].n_choices=(uint16_t)(color==2?2:3);
    s->rows[6].choices=amount>=75?s->amounts+3:s->amounts;
    s->rows[6].n_choices=(uint16_t)(amount>=75?2:3);
    struct lib_entry *e=edited(s);
    s->rows[2].value=e && !(e->flags&LIB_SPACE)?string(s,53):0;
    s->rows[4].value=e && !(e->flags&LIB_GAMMA)?string(s,53):0;
    if(e) s->file_choices[0]=string(s,(e->flags&LIB_READY)!=LIB_READY?53u:!supported(e->color,e->gamma)?54u:e->flags&1u?51u:52u);
    s->set_rows[1].choices=edit_color(s)==2?s->blackmagic:s->common;
    s->set_rows[1].n_choices=(uint16_t)(edit_color(s)==2?2:6);
    s->set_rows[0].value=e && !(e->flags&LIB_SPACE)?string(s,53):0;
    s->set_rows[1].value=e && !(e->flags&LIB_GAMMA)?string(s,53):0;
    lvb_refresh(s);                    /* every state change ends here: the ISP follows the active entry */
}
static USED int lut4_select(struct lut4_state *s,u32 color,u32 gamma) {
    if(color>=8 || gamma>=(color==2?2u:6u)) return SL_BADARG;
    s->color=color; s->gamma=gamma;
    choices(s);
    if(s->file_status==OK) s->file_choices[0]=string(s,supported(color,gamma)?27u:30u);
    refresh(s);
    return s->last_error=supported(color,gamma)?OK:MODEL_PENDING;
}
static int color_set(void *arg,int v) {
    struct lut4_state *s=arg; u32 gamma=edit_gamma(s),before=edit_color(s);
    if(v<0 || v>=s->rows[2].n_choices) return SL_BADARG;
    u32 color=(before/3u)*3+(u32)v;
    if((before==2)!=(color==2)) gamma=0;
    struct lib_entry *e=edited(s);
    if(e) return library_update(s,s->edit_index,color,gamma,e->amount,
        (e->flags|LIB_SPACE)&((before==2)!=(color==2)?~LIB_GAMMA:~0u));
    lut4_select(s,color,gamma); return OK;       /* pending is a visible selection, never a substitute */
}
static int color_group_set(void *arg,int v) {
    struct lut4_state *s=arg;
    if(v<0 || v>2) return SL_BADARG;
    struct lib_entry *e=edited(s);
    if(e) return library_update(s,s->edit_index,(u32)v*3,e->color==2?0:e->gamma,e->amount,
                               (e->flags|LIB_SPACE)&(e->color==2?~LIB_GAMMA:~0u));
    lut4_select(s,(u32)v*3,s->color==2?0:s->gamma); return OK;
}
static int gamma_set(void *arg,int v) {
    struct lut4_state *s=arg;
    if(v<0 || v>=s->rows[4].n_choices) return SL_BADARG;
    struct lib_entry *e=edited(s);
    if(e) return library_update(s,s->edit_index,e->color,(e->color==2?0:(e->gamma/3u)*3)+(u32)v,e->amount,e->flags|LIB_GAMMA);
    lut4_select(s,s->color,(s->color==2?0:(s->gamma/3u)*3)+(u32)v); return OK;
}
static int gamma_group_set(void *arg,int v) {
    struct lut4_state *s=arg;
    if(v<0 || v>=(edit_color(s)==2?1:2)) return SL_BADARG;
    struct lib_entry *e=edited(s);
    if(e) return library_update(s,s->edit_index,e->color,e->color==2?e->gamma:(u32)v*3,e->amount,e->flags|LIB_GAMMA);
    lut4_select(s,s->color,s->color==2?s->gamma:(u32)v*3); return OK;
}
/* The settings page (AEL on a manager row): the two rows the user asked for,
 * each choice by its own index -- color space (8) and Gamma (6, or the two
 * Blackmagic ones), the Gamma list following the color space. */
static int set_color_get(void *arg) { return (int)edit_color(arg); }
static int set_gamma_get(void *arg) { return (int)edit_gamma(arg); }
static int set_color_set(void *arg,int v) {
    struct lut4_state *s=arg; struct lib_entry *e=edited(s);
    if(!e || v<0 || v>=8) return SL_BADARG;
    u32 color=(u32)v,bmd=(e->color==2)!=(color==2);    /* Blackmagic has its own Gammas */
    return library_update(s,s->edit_index,color,bmd?0:e->gamma,e->amount,(e->flags|LIB_SPACE)&(bmd?~LIB_GAMMA:~0u));
}
static int set_gamma_set(void *arg,int v) {
    struct lut4_state *s=arg; struct lib_entry *e=edited(s);
    if(!e || v<0 || v>=(e->color==2?2:6)) return SL_BADARG;
    return library_update(s,s->edit_index,e->color,(u32)v,e->amount,e->flags|LIB_GAMMA);
}
static USED int lut4_strength(struct lut4_state *s,u32 amount) {
    if(amount>100 || amount%25u) return SL_BADARG;
    s->amount=amount; choices(s); refresh(s); return OK;
}
static int amount_set(void *arg,int v) {
    struct lut4_state *s=arg;
    struct lib_entry *e=edited(s);
    if(e) return v<0 || v>=s->rows[6].n_choices?SL_BADARG:
        library_update(s,s->edit_index,e->color,e->gamma,(e->amount/75u)*75u+(u32)v*25u,e->flags);
    return v<0 || v>=s->rows[6].n_choices?SL_BADARG:lut4_strength(s,(s->amount/75u)*75u+(u32)v*25u);
}
static int amount_group_set(void *arg,int v) {
    struct lut4_state *s=arg;struct lib_entry *e=edited(s);
    if(e) return v<0 || v>1?SL_BADARG:library_update(s,s->edit_index,e->color,e->gamma,v?75u:0u,e->flags);
    return v<0 || v>1?SL_BADARG:lut4_strength(arg,v?75:0);
}
static USED int lut4_enable(struct lut4_state *s,u32 on) {
    if(on>1) return SL_BADARG;
    return s->last_error=on?NO_BACKEND:OK;
}
static int monitor_set(void *arg,int v) { return v<0?SL_BADARG:lut4_enable(arg,(u32)v); }
static USED int lut4_status(struct lut4_state *s,struct lut4_status *out) {
    if(!out || ((uintptr_t)out&3)) return SL_BADARG;
    out->version=1; out->asset_status=s->file_status;
    out->model_status=supported(s->color,s->gamma)?OK:MODEL_PENDING;
    if(s->library && (s->library->h.active>=s->library->h.count ||
       (s->library->entries[s->library->h.active].flags&LIB_READY)!=LIB_READY))out->model_status=MODEL_PENDING;
    out->live_view_connected=0; out->color=s->color; out->gamma=s->gamma; out->strength_percent=s->amount;
    out->rendered_samples=s->rendered; out->outside_1d_channels=s->outside1; out->outside_3d_channels=s->outside3;
    out->last_error=s->last_error; return OK;
}

static int render_core(struct lut4_state *s,const i32 *xyz,i32 *out,u32 count) {
    if(s->file_status!=OK) return s->last_error=s->file_status;
    if(s->library && (s->library->h.active>=s->library->h.count ||
       (s->library->entries[s->library->h.active].flags&LIB_READY)!=LIB_READY)) return s->last_error=MODEL_PENDING;
    if(!supported(s->color,s->gamma)) return s->last_error=MODEL_PENDING;
    if(!xyz || !out || !count || count>4096 || ((uintptr_t)xyz&3) || ((uintptr_t)out&3)) return s->last_error=BAD_INPUT;
    uintptr_t first=(uintptr_t)xyz, dest=(uintptr_t)out, bytes=count*12u;
    if(first+bytes<first || dest+bytes<dest || (first!=dest && first<dest+bytes && dest<first+bytes)) return s->last_error=BAD_INPUT;
    /* A bad later sample must not leave a partially transformed destination. */
    for(u32 i=0;i<count;i++) {
        i32 temp[3];
        for(u32 c=0;c<3;c++) if(xyz[i*3+c]<-64*Q || xyz[i*3+c]>64*Q) return s->last_error=BAD_INPUT;
        if(matrix(s,xyz+i*3,s->color,temp)!=OK || matrix(s,xyz+i*3,6,temp)!=OK) return s->last_error=BAD_INPUT;
    }
    s->outside1=s->outside3=0;
    for(u32 i=0;i<count;i++) {
        i32 look[3], baseline[3];
        matrix(s,xyz+i*3,s->color,look); matrix(s,xyz+i*3,6,baseline);
        for(u32 c=0;c<3;c++) {
            if(baseline[c]<0) baseline[c]=0; if(baseline[c]>Q) baseline[c]=Q;
            baseline[c]=curve(s,baseline[c],1);
            look[c]=curve(s,look[c],s->gamma);
        }
        if(s->amount) lookup(s,look);
        for(u32 c=0;c<3;c++) {
            /* Split before multiplying: bounded 32-bit /100, no EABI
             * soft-float or 64-bit division helper in the resident image. */
            i32 delta=look[c]-baseline[c], whole=delta/100, rem=delta-whole*100;
            out[i*3+c]=baseline[c]+whole*(i32)s->amount+(rem*(i32)s->amount)/100;
        }
    }
    s->rendered+=count; return s->last_error=OK;
}
static int library_load_index(struct lut4_state *,u32);
/* The API's render.  A library build keeps no cube between operations (borrow.c): the
 * active one is loaded into a borrowed area for this call and the area returned after;
 * the running colour / gamma / strength (lut4_select / lut4_strength) stay as they are.
 * Inside a fit (lvb.c, conv.c) the asset is loaded already. */
static USED int lut4_render(struct lut4_state *s,const i32 *xyz,i32 *out,u32 count) {
    if(!s->cfg->library_off || s->asset || s->file_status!=OK || !s->library ||
       s->library->h.active>=s->library->h.count ||
       (s->library->entries[s->library->h.active].flags&LIB_READY)!=LIB_READY ||
       !supported(s->color,s->gamma)) return render_core(s,xyz,out,count);   /* its own refusals */
    u32 k_color=s->color,k_gamma=s->gamma,k_amount=s->amount;
    if(!lut_borrow(s,&s->b_asset,s->cfg->asset_cap)) return s->last_error=library_busy()?RECORD_BUSY:NO_MEMORY;
    int rc=library_load_index(s,s->library->h.active);
    s->color=k_color; s->gamma=k_gamma; s->amount=k_amount;
    if(rc==OK) rc=render_core(s,xyz,out,count);
    else { s->file_status=OK; s->last_error=rc; }      /* the selection stands; this call failed */
    lut_return(s,&s->b_asset); s->asset=0;
    return rc;
}

#include "library4.c"
#include "color_ui.c"
#include "import.c"
#ifndef LUT_BISECT
#define LUT_BISECT 0                         /* diagnostic builds only (MOV freeze, 2026-11-06): 1 no COL-Share client, 2 + no DNG / lvb, 3 + no lvb */
#endif
#include "cols.c"
#include "dng.c"
#include "lvb.c"
#include "conv.c"
static int lut4_pick(struct lut4_state *s,u32 index) { return library_pick(s,index); }

USED int sup_entry(void *block,const struct sl_svc *svc,const char *path) {
    (void)path;
    const struct sl4_header *h=block;
    const struct cfg *cfg=(const struct cfg *)((u8 *)block+SL4_HEADER_LEN);
    if(svc->version<6 || cfg->magic!=CFG_MAGIC || cfg->strings_n!=125 ||
       cfg->state_off<h->file_len || cfg->state_off+sizeof(struct lut4_state)>cfg->io_off ||
       cfg->io_off+8192u!=cfg->icons_off || cfg->asset_cap>MAX_ASSET || cfg->asset_cap<sizeof(struct asset) ||
       (cfg->library_off ? cfg->asset_off!=0                           /* library: borrowed (borrow.c) */
                         : cfg->asset_off<cfg->icons_off || cfg->asset_off+cfg->asset_cap>h->block_size) ||
       (cfg->lvb_off && (!cfg->library_off || cfg->lvb_off<cfg->icons_off || (cfg->lvb_off&31u) ||
                         cfg->lvb_off+LVB_CAP>h->block_size)) ||
       (cfg->conv_off && (!cfg->lvb_off || cfg->conv_off<cfg->lvb_off+LVB_CAP || (cfg->conv_off&31u) ||
                          cfg->conv_off+CONV_CAP>h->block_size || !cfg->chk_off || (cfg->chk_off&3u) ||
                          cfg->chk_off+72u*12u>h->file_len))) return SL_RELEASE;
    struct lut4_state *s=(struct lut4_state *)((u8 *)block+cfg->state_off);
    s->svc=svc; s->cfg=cfg; s->block=block; s->color=6; s->gamma=1; s->amount=100;
    s->self_path=svc->self_path(svc,block);
    library_init(s);
    s->last_error=s->file_status;
    s->api.magic=API_ID; s->api.version=2; s->api.state=s;
    s->conv.magic=0x31564E43u;               /* conv.c CONV_MAGIC */
    s->api.select=lut4_select; s->api.strength=lut4_strength; s->api.enable=lut4_enable; s->api.render=lut4_render;
    s->api.status=lut4_status; s->api.pick=lut4_pick;
    for(u32 i=0;i<8;i++) s->colors[i]=string(s,6+i);
    for(u32 i=0;i<6;i++) s->common[i]=string(s,14+i);
    for(u32 i=0;i<2;i++) s->blackmagic[i]=string(s,20+i);
    for(u32 i=0;i<5;i++) s->amounts[i]=string(s,22+i);
    for(u32 i=0;i<3;i++) s->color_groups[i]=string(s,34+i);
    for(u32 i=0;i<2;i++) {
        s->gamma_groups[i]=string(s,37+i); s->amount_groups[i]=string(s,40+i);
    }
    s->bmd_group[0]=string(s,39);
    for(u32 i=0;i<3;i++)s->manager_choices[i]=string(s,48+i);
    s->file_choices[0]=string(s,s->file_status==OK?27u:s->file_status==NO_FILE?28u:29u);
    for(u32 i=0;i<8;i++) { s->rows[i].arg=s; s->rows[i].kind=SL_ROW_LIST; }
    s->rows[0].title=string(s,1); s->rows[1].title=string(s,31); s->rows[2].title=string(s,2);
    s->rows[3].title=string(s,32); s->rows[4].title=string(s,3);
    s->rows[5].title=string(s,33); s->rows[6].title=string(s,4); s->rows[7].title=string(s,5);
    s->rows[0].choices=s->file_choices; s->rows[0].n_choices=1; s->rows[0].get=file_get; s->rows[0].set=file_set;
    s->rows[1].choices=s->color_groups; s->rows[1].n_choices=3; s->rows[1].get=color_group_get; s->rows[1].set=color_group_set;
    s->rows[2].get=color_get; s->rows[2].set=color_set;
    s->rows[3].get=gamma_group_get; s->rows[3].set=gamma_group_set;
    s->rows[4].get=gamma_get; s->rows[4].set=gamma_set;
    s->rows[5].choices=s->amount_groups; s->rows[5].n_choices=2; s->rows[5].get=amount_group_get; s->rows[5].set=amount_group_set;
    s->rows[6].get=amount_get; s->rows[6].set=amount_set;
    s->rows[7].kind=SL_ROW_TOGGLE; s->rows[7].get=monitor_get; s->rows[7].set=monitor_set;
    for(u32 i=0;i<2;i++) { s->set_rows[i].arg=s; s->set_rows[i].kind=SL_ROW_LIST; s->set_rows[i].title=string(s,94+i); }
    s->set_rows[0].choices=s->colors; s->set_rows[0].n_choices=8;
    s->set_rows[0].get=set_color_get; s->set_rows[0].set=set_color_set;
    s->set_rows[1].choices=s->common; s->set_rows[1].n_choices=6;
    s->set_rows[1].get=set_gamma_get; s->set_rows[1].set=set_gamma_set;
    choices(s);
    if(svc->provide(svc,API_ID,&s->api)!=SL_OK) return SL_RELEASE;
    s->home.kind=SL_ROW_JUMP; s->home.title=string(s,46);   /* "LUT manager": the only fpSup row */
    s->home.open=color_open; s->home.arg=s;
    if(svc->page_add(svc,&s->home)<0) return SL_RELEASE;
    /* Native labels and the pager stay in our block; protect them as well as
     * the private FT4S file's strings. No registered pointer may be freed. */
    int borrowed=svc->borrow(svc,block,(u8 *)block+cfg->io_off);
    if(borrowed==SL_BADARG) return SL_KEEP; /* core built without UI: data-only API */
    if(borrowed!=SL_OK) return SL_RELEASE;
    color_ui_init(s);
    cols_join(s);                            /* COL-Share: our COLOR rows; DNG / ISP points in lc_attached */
    lvb_refresh(s);
    return SL_KEEP;
}
