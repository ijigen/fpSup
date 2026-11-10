/* SensorLab-IMX410 QS client (sup_id SL41) v0.7.0test: DC, RES, FPS, RECIPE, FORMAT,
 * MB/s and QR on the Quick Set page, through the QS container (projects/qs-container/qsc.h, API 6: v0.3.1).
 * v0.7.0test: FPS gets a sub-QS (FPS + FINE, Bei 10-30 A): the old in-place fine mode is the FINE tile; the tuned
 * rate joins the list when the focus leaves FINE (the container's blur()); the menu's FPS CUSTOM opens it on FINE.
 * 0.0.2test (Bei 11-07): AEL on the main QS's FPS tile is the in-place fine mode again (fine(), no page change); the
 * FPS sub-QS stays, reached only from the menu's FPS CUSTOM.  Needs the container's API 9 (fine + sub on one function);
 * an older container keeps the v0.7 behaviour (AEL opens the sub-QS).
 * v0.5.0test: the apply step (../apply/ap.c, ABI 2) installs the selection on the sensor and the ISP from the QS
 * change events (adjust / fine) and at leave(); notes/APPLY_DESIGN.md §11-§12.
 * v0.6.0test adds native menu lists, menu-to-CUSTOM opening, native QS slot replacement,
 * and playback geometry/HUD handling. The BIN settings record remains version 2.
 *
 * Behaviour = projects/sensorlab-imx410/preview/dcres.html (the spec Bei signed off) and QS_DC_RES_SPEC.md: this file
 * is that page's logic line for line (the names in the comments are the page's), with every JavaScript double
 * reproduced exactly -- the core's integer IEEE emulation (dratio / dmul / ddiv_int, js_fixed_d = toFixed / Math.round)
 * or an exact rational where the double cannot differ -- so the tests can require the page's visible state, string
 * for string (test_slqs.py runs the page in node).
 *
 *   recipes  core_qualities_tol(DC, RES, uncapped, 2 %) on the camera for any DC x RES (the C core, bit for bit
 *            quality.py), kept per cell in a 4-entry cache.  A recipe: hm, VMAX floor lo, merge mh x mv, AD,
 *            ISP bins, sensor crop scw x sch -> sw x sh, its own visible size, RWZM, rolling shutter.
 *   DC       presets OG..SQ, WIDTH / HEIGHT / RATIO (locked aspect remembered at lock / preset time)
 *   RES      clean ratios + 1K..6K (+ FHD / UHD on HD), K label remembered by name, ratio kept on small DCs,
 *            a custom RES kept per crop; shows the selected recipe's visible size (yellow when short)
 *   FPS      common rates to 1000 (unreachable grey and skipped), recipe maxima marked, fine mode (AEL) on the
 *            VMAX grid of every preset recipe, one tuned rate kept (v0.7.0test: the FINE tile of the FPS sub-QS)
 *   RECIPE   presets (ISP 1x1) with RS; sub-QS ADC, SENSOR HDC / VDC / HBIN / VBIN, ISP HBIN / VBIN (kernels,
 *            SOFT / STD shared); the user's choice kept while the effective recipe falls back
 *   FORMAT   DNG 12 / 14 bit from the effective recipe's AD; MOV grey.  0.0.3test: the stock bit depth (menu BIT row,
 *            MV_DNGQuality) 8 / 10 bit records that depth (the picker answers TAB1 / TAB2): FORMAT / MB/s / defaultPick
 *            use it (out_bits); "RAW bit" (12) keeps the recipe's own 12 / 14
 *            0.0.4test (Bei 11-08): the FORMAT dial picks it too -- 8bit / 10bit / <own>bit (RAW bit), MOV grey -- by the
 *            menu BIT row's stock setter (depth_set), so the menu and the QS show one setting
 *   MB/s     uncompressed / predicted lossless rate and the medium's duty (notes/MBPS_TILE_RESEARCH.md)
 *   QR       Main QS: the mode as a URL (notes/QR_QS_RESEARCH.md §3.4), our V5-L encoder, drawn inside the QR tile
 * All seven are locked while recording (QSC_F_LOCK_REC).  The selection lives in this BIN's own record, written at
 * the container's leave() (a layout load), never per dial step, never creating the file.
 *
 * Built as one unit with the core (#include core.c); build_slqs.py moves the read-only data into .text (-fropi,
 * PC-relative) because the loader maps .text only.  No division operator: udiv64.  Firmware Ver.5.02. */
#include "core.c"
#include "sloader4.h"
#include "qsc.h"
#include "ap.c"                                 /* ../apply (build_slqs.py -I): the apply unit (one unit with the core, as ap.h says) */
#include "fpui_stock.c"
#include "pb_page.h"
#include "slm_state.h"
#include "slm_page.h"

typedef uint32_t u32;
typedef uint16_t u16;
typedef uint8_t u8;
typedef int32_t s32;
#define USED __attribute__((used))
#define W(a) (*(volatile u32 *)(uintptr_t)(a))

#define F_CTOR  0xC0365E90u
#define F_OPEN  0xC0365FB0u
#define F_READ  0xC0366060u
#define F_WRITE 0xC03660E8u
#define F_SEEK  0xC03661E0u
#define F_CLOSE 0xC0366020u
#define F_DTOR  0xC0365ED0u
#define FO_BYTES 0x800u
#define MOV_SELECTOR   0xC347D1D4u            /* recording (the container's busy()) */
#define MOVREC_DEFAULT 0xC347E08Fu
#define MOVREC_SEL21   0xC3476609u
#define XMP_FOBJ_PTR   0xC358E140u
#define MOV_ACTIVE     0xC35A952Cu

#define CFG_MAGIC 0x32344C53u                 /* "SL42" */
#define REC_MAGIC 0x32514C53u                 /* "SLQ2" */
#define REC_VERSION 2u
#define N_DC    6u
#define N_RAT   5u
#define N_KL    11u                           /* 1K..6K (7), UHD, FHD, 1x2, 1x3 (0.0.6test: anamorphic merge presets) */
#define N_KHD   9u                            /* KL_* below this: the K and HD presets */
#define VM_ROWS 10                            /* 0.0.6test: the ÷6 preset's spare rows (quality.py VM_ROWS; page binH) */
#define N_MEM   8u
#define N_LIST  16u
#define N_STD   29u
#define N_FPS   (N_STD + 2u * MAXR + 2u)
#define MAXR    80u                           /* recipes per DC x RES kept (the core gives at most CORE_MAX_QUAL) */
#define N_CACHE 4u
#define WMIN 256
#define HMIN 144
#define WMAX 6048
#define HMAX 4040
#define TXT 64u
#define FT 64u
#define VMAX_MAX CD_VMAX_MAX
#define TOL_NUM 1u                            /* the visible tolerance: 2 % (QS_DC_RES_SPEC 看到的尺寸與寬容) */
#define TOL_DEN 50u
/* QR (v0.4.1test, notes/QR_QS_RESEARCH.md): our own encoder (version 5-L, 37 x 37, byte mode, best of 8 masks) into a
 * module matrix, drawn by our DrawingObserver inside the QR tile itself on the main OSD layer (1024 x 682 ARGB4444).
 * The drawing path (live7 2026-10-29: group 0 drew into a buffer that was never presented):
 *   - FUN_c0528178(g) = 1 only for groups 2 and 3: only they commit and present (FUN_c0528700 after the observers);
 *   - the GUI's observer is the UIC draw handler 0xC38D3D0C (UicContentsIfBase::v16 returns it), in group 2;
 *   - so we register in the group that holds it, in a later slot (observers run in slot order), and draw last;
 *   - the UIC draw handler's +0x1C (UicDrawHandler::v5) returns 0: no front -> back copy; each of the three rotating
 *     buffers keeps what was drawn into it, and UIC repaints only what it changed.  So the pixels under the code are
 *     saved (one shadow, what UIC drew there) and put back into every buffer that held the code before we stop. */
#define QR_URL      "https://ijigen.github.io/fpSup/sensor_lab_imx410/#"
#define QR_CHARS    37u                       /* 213 data bits + CRC-8 + 1 pad = 222 = 37 x 6 */
#define QR_VER      5u
#define QR_N        37u                       /* 4 x 5 + 17 */
#define QR_DATA_CW  108u                      /* V5-L: 134 codewords, 1 block, 26 EC */
#define QR_EC_CW    26u
#define QR_QZ       2u                        /* quiet zone, modules (Bei 10-29: >= 2) */
#define QRD_BYTES   9600u                     /* >= sizeof(struct qrd) (qrdec.c; asserted after its include) */
#define UIC_DRAW    0xC38D3D0Cu               /* the GUI's DrawingObserver (UicContentsIfBase::v16) */
#define DRAW_CTRL   0xC3783020u               /* the DrawController (CYC_DRAW()->+4) */
#define DRAW_LAYERS 0xC3783078u               /* ctrl + 0x58: 4 x {layer, ...} */
#define DRAW_COUNT  0xC3783068u               /* ctrl + 0x48: observers per group (3 slots, FUN_c0528300 asserts at 3) */
#define F_OBS_ADD   0xC0528300u               /* (ctrl, group, obs): first empty slot; calls obs->vt[0x10] */
#define F_OBS_DEL   0xC05283D8u               /* (ctrl, group, obs): calls obs->vt[0x14] */
#define F_DRAW_REQ  0xC05284E8u               /* (ctrl, group): redraw request (GuiAdjust::v10 after registering) */
#define QS_STATE_FN 0xC05666A0u               /* FUN_c05666a0(): the QS GUI state; +0xBC = the focused tile's internal id */
#define QS_GET_FN   0xC0061B08u               /* (settings, k): the CINE layout's slot k (internal id) */
#define SETTINGS_FN 0xC0057AE8u
#define QS_SUB_ID0  70u                       /* internal ids >= 70: the container's temporary sub-QS (70..77) */
#define QSC_UI_BASE 49u                       /* qsct.c UI_BASE / INT_BASE: api->ui_id() -> the internal tile id */
#define QSC_INT_BASE 54u
#define F_MUTEX_LOCK   0xC0010298u            /* (guard[2], mutex): DrawController's lock, as FUN_c0528700 takes it */
#define F_MUTEX_UNLOCK 0xC00102D0u            /* (guard[2], 2) */
#define UIC_OWNER     0xC37859E0u             /* UIC_DRAW + 8 while UicContentsIfBase v10/v11 publish a QS page */
#define UIC_OWNER_VT  0xC0D1D6C4u             /* its vtable */
#define UIC_RECS      0xC37B7060u             /* C055F0F0() + 0x18: ten 0x20-byte {+4 base, +0x10 w, +0x14 h, +0x18 mode} */
#define UIC_RECS_END  0xC37B71A0u
#define OSD_W 1024u
#define OSD_H 682u
/* the QS tiles on that layer (live6 2693 / live7 2726, 1024 x 682): 4 x 2 tiles of 256 x 223 at x 256 c, y 77 / 308; the
 * focus box is the tile's own rectangle, 4 px wide at the sides, 5 px at the top and bottom */
#define TILE_W 256u
#define TILE_H 223u
#define TILE_Y0 77u
#define TILE_DY 231u
#define TILE_BX 4u
#define TILE_BY 5u
#define QR_SIDE_MAX (TILE_H - 2u * TILE_BY - 2u)  /* 211: the inside of the focus box, 1 px clear */
#define QR_SHADOW 44100u                          /* (37 + 4) x 5 = 205 px square: 42 025 px, +slack */
#define ARGB_WHITE 0xFFFFu
#define ARGB_BLACK 0xF000u
#define LL_MAX_FRAME 16777216u                    /* the lossless sup refuses a frame over 16 MiB (MBPS research §6.5) */

enum { F_DC, F_RES, F_FPS, F_RECIPE, F_FORMAT, F_MBPS, F_QR, N_FN };
enum { K_AD, K_SCW, K_SCH, K_MH, K_MV, K_HB, K_VB, N_PARAM };   /* PARAMS order (ADC second, Bei 10-29) */

/* ---------------------------------------------------------------------------------------------- tables */
static const u16 DCW[N_DC] = {6048, 6048, 4192, 3952, 2096, 4032};
static const u16 DCH[N_DC] = {4040, 3402, 2358, 2624, 1240, 4032};
static const char DCN[N_DC][6] = {"OG", "HD", "S35", "APS-C", "S16", "SQ"};
static const u8 RAT_N[N_RAT] = {1, 2, 1, 1, 1}, RAT_D[N_RAT] = {1, 3, 2, 3, 6};
static const u16 KL_W[N_KL] = {1024, 2048, 3072, 3584, 4096, 5120, 6144, 3840, 1920, 0, 0};
static const u16 KL_H[N_KL] = {0, 0, 0, 0, 0, 0, 0, 2160, 1080, 2, 3};   /* 1x2 / 1x3: the DC height divisor */
static const char KL_N[N_KL][5] = {"1K", "2K", "3K", "3.5K", "4K", "5K", "6K", "UHD", "FHD", "1x2", "1x3"};
static const u8 DIVK[8] = {1, 2, 3, 4, 5, 6, 8, 12};
/* STD: the common rates, as the page writes them (String(f)) and as exact rationals n / d */
static const u32 STD_N[N_STD] = {23976, 24, 25, 2997, 30, 47952, 48, 50, 5994, 60, 72, 90, 96, 100, 11988, 120, 144,
                                 150, 180, 200, 23976, 240, 300, 360, 400, 480, 500, 600, 1000};
static const u16 STD_D[N_STD] = {1000, 1, 1, 100, 1, 1000, 1, 1, 100, 1, 1, 1, 1, 1, 100, 1, 1, 1, 1, 1, 100, 1, 1, 1,
                                 1, 1, 1, 1, 1};
static const char STD_S[N_STD][8] = {"23.976", "24", "25", "29.97", "30", "47.952", "48", "50", "59.94", "60", "72",
                                     "90", "96", "100", "119.88", "120", "144", "150", "180", "200", "239.76", "240",
                                     "300", "360", "400", "480", "500", "600", "1000"};
static const char HW_MODES[9][4] = {"1x1", "1x2", "1x3", "2x1", "2x2", "2x3", "3x2", "3x3", "3x6"};  /* no 3x1 (§72) */
static const char KERN[6][9] = {"1,1,1", "1,2,1", "1,4,1", "1,6,1", "1,14,1", "0,1,0"};
static const char MODE[2][5] = {"SOFT", "STD"};
#ifndef SL_LE
#define SL_LE "<"                            /* U+2264 is not in the fp font (live5 drew "?") */
#endif
static const char SUB_LABEL[7][12] = {"ADC", "DC WIDTH", "DC HEIGHT", "SENSOR HBIN", "SENSOR VBIN", "ISP HBIN",
                                      "ISP VBIN"};
static const char FN_LABEL[N_FN][10] = {"DC", "RES", "SL FPS", "RECIPE", "SL FORMAT", "MB/s", "QR"};
static const char FN_NAME[N_FN][7] = {"DC", "RES", "FPS", "RECIPE", "FORMAT", "MBPS", "QR"};
static const char FN_ICON[N_FN][21] = {"menu_crop", "menu_cine_resolution", "menu_cine_fps", "", "menu_cine_format", "", ""};

/* ---------------------------------------------------------------------------------------------- state */
struct rat { u32 n, d; };                     /* a rate n / d fps: a common rate, or CLK / (hm x VMAX) */
struct rcp {                                  /* one recipe (quality.py case) of a DC x RES */
    u16 hm, lo, mh, mv, ad, hb, vb, scw, sch, sw, sh, vis_w, vis_h, zh, zv, key, win_w, win_h, rec_w, rec_h;
    u32 rs_us;
};
struct cell { u32 dcw, dch, rw, rh, used, used_n; s32 n; struct rcp r[MAXR]; };   /* used_n: compute serial */

struct sel {                                  /* the page's S, less the UI state: the record */
    u32 dcw, dch, dclock, reslock, daw, dah, raw, rah;
    u32 rat, resk, custom, cw, ch;
    u32 nmem, mem[N_MEM][4];
    u32 fps_n, fps_d, fc_n, fc_d, fine;
    u32 rq, rd_ok, rd[N_PARAM];
    u32 kh, kv, km;
};

struct fent { struct rat f; u8 std, mark, custom, na; };   /* fpsList() */
struct ritem { u16 w, h; u8 ratio, kl; char lab[6]; char div[8]; };   /* resList() */

struct st {
#ifdef AP_REC_DELAY_TEST
    struct ap_rd rd;                          /* 0.0.2test TEST build: first (block + state_off; build json rec_delay) */
#endif
    const struct sl_svc *svc;
    const u8 *block;
    u32 rec_off, dma_off;
    struct sel s;
    u32 dirty, loaded, writes, write_fails, write_why, leaves, applies, computes, hits, fallbacks;
    /* the QS side */
    struct qsc_func f[N_FN];
    struct qsc_sub sub[N_FN][7];
    struct qsc_subs subs[N_FN];
    struct qsc_table t;
    u8 arg[N_FN][8];                          /* (function, item) <- &arg[f][j] */
    char v[N_FN][8][TXT], sm[N_FN][8][TXT];
    char fl[N_LIST][FT], fs[N_LIST][FT];
    /* the recipes */
    struct cell cache[N_CACHE];
    u32 tick;
    const struct rcp *memo;                   /* cur_recipe() memo */
    u32 memo_ok, memo_key[5 + N_PARAM];
    struct cell *cur;                         /* the cell of res() (refreshed by cell_now) */
    core_quality scratch[CORE_MAX_QUAL];
    struct ritem list[N_LIST];
    u32 n_list;
    struct fent fl_e[N_FPS];
    u32 n_fl;
    /* MB/s: the recording medium, read once per QS visit (validation/2026-10-29-media LOG §5) */
    struct { u32 read_at, ok, ssd, ssd_ready, ssd_mnt, sd_mnt, sd_mode, ms_a, ms_raw, ms_b; } md;
    u32 md_force;                             /* sq_test 11: 1 + (ssd << 8 | sd_mode) replaces the camera reads */
    /* the apply hook (sq_apply): what the later step will install */
    struct { u32 valid, dcw, dch, rw, rh, key, hm, vmax, fps_n, fps_d, kh, kv, km; s32 ri; } applied;
    /* v0.5.0test: the apply unit (ap.h) -- its state + veneers, the last selection handed to it, its status */
    u8 ap_mem[AP_MEM_BYTES] __attribute__((aligned(8)));
    struct ap_sel ap_last;
    struct ap_status ap_st;
    s32 ap_init_rc, ap_rc;
    u32 ap_pushes, ap_boot_owed;
    u32 pb_ui_result;
    struct slm_state menu;
    /* QR: prepared by its main QS tile; the draw observer checks the native QS owner. */
    struct qr {
        u32 on, force, group, shows, hides, draws, enc_ret, why, n, scale, x0, y0, side, reg, tile, slot, gui_slot;
        u32 have_sh, nbuf, buf[4], restores, mask;
        u32 info[24];                         /* sq_test 14 */
        struct qobs { const u32 *vt; struct st *st; } obs;
        u32 vt[8];
        char code[QR_CHARS + 3u], url[96];
        u8 cw[QR_DATA_CW + QR_EC_CW], gen[QR_EC_CW];
        u8 mat[QR_N * QR_N + 3u], fn[QR_N * QR_N + 3u], best[QR_N * QR_N + 3u];
        u8 live[QR_N * QR_N + 3u], prior[4][QR_N * QR_N + 3u];
        u32 qs;
        u16 sh[QR_SHADOW] __attribute__((aligned(8)));   /* what UIC drew under the code (one copy: every buffer has the same) */
    } qr;
    /* v0.7.0test (appended): leave() timing, microseconds (the firmware tick), for the first-MENU probe (sq_test 29):
     *  0..4  the first leave: total / apply push (the commit inside) / HUD idle / menu bridge / record write
     *  5..7  the largest total, the last total, leaves timed
     *  8..11 the first leave's start / end and its push's start / end, absolute tick (compare with the container's)
     * 12..14 the menu setup (once): fpui_stock_apply / both slm_model / the whole setup
     * 15     pushes skipped while paused (sq_test 30) */
    u32 lt[16];
    u32 push_pause;                           /* sq_test 30: 1 = stock and no push until 0 (survives leave(), not a reboot) */
    /* v0.7.32test (appended): QR scan through SIGMA's "Load from QR Code" page (notes/QR_SCAN_DESIGN.md §11) */
    struct scan {
        u32 dvt[5];                           /* our copy of XC_QrCode's vtable: slot 3 = sl_qr_dec */
        u32 vt_ok, vt_why;                    /* the MenuQrCodeReadHandler slots are ours (1) / why not */
        u32 on_page, armed, arms, arm_refused, disarms;
        u32 decodes, ours, ours_ok, results, sensorlab, invalid, accepted, refused, applied, to_qs, goes;   /* to_qs: v0.7.34 (was oks) */
        u32 pending, last, last_at, diff, unpack_rc;   /* last: 1 applied, 2 refused, 3 invalid code; pending (0.0.2test):
                                                         1 = an applied scan's commit is owed to the page exit (v73) */
        u32 f[27];                            /* the accepted code's fields (pending) / the last one (N_QF) */
        char code[QR_CHARS + 3u];
        u8 out[QR_DATA_CW];
        u8 qd[QRD_BYTES] __attribute__((aligned(8)));   /* struct qrd (qrdec.c), the decoder's work */
    } scan;
    /* v0.7.35test (appended): the recorded selection applied after boot without MENU / QS (sq_test 46) */
    struct boot {
        s32 task;                             /* the poller's task id (< 1: none) */
        u32 var_ok, polls, ready_polls, posts, runs, done, why, last_rc, last_post, tries, stable;
        u32 stby_ok, stby_enters;             /* v0.7.36test: the standby screen's enter hook is ours / ran */
        u32 lv_load;                          /* v0.7.37test: ap_lv_at_load at sup_entry (1 = LV was already up) */
        s32 entry_rc;                         /* v0.7.37test: the commit at sup_entry (RES-Custom's way); -99 none */
        u32 tramp[2] __attribute__((aligned(8)));   /* the task's ARM entry: ldr pc, [pc, #-4]; sq_boot_task | 1 */
    } boot;
    /* 0.0.3test (appended): the stock CinemaDNG bit depth (8 / 10 / 12), read once per layout like the medium */
    struct { u32 read_at, ok, bits; } bd;
};
#ifdef SL_STATE_RESERVE
_Static_assert(sizeof(struct st) <= SL_STATE_RESERVE, "struct st outgrew STATE_RESERVE (build_slqs.py)");
#endif

/* struct copies: the compiler calls these (no libgcc on the camera); byte loops, volatile so they stay loops */
void __aeabi_memcpy(void *d, const void *s, unsigned n)
{
    volatile u8 *o = d;
    const u8 *i = s;
    while (n--) *o++ = *i++;
}
void __aeabi_memcpy4(void *d, const void *s, unsigned n) { __aeabi_memcpy(d, s, n); }
void __aeabi_memcpy8(void *d, const void *s, unsigned n) { __aeabi_memcpy(d, s, n); }
void __aeabi_memclr(void *d, unsigned n) { volatile u8 *o = d; while (n--) *o++ = 0; }
void __aeabi_memclr4(void *d, unsigned n) { __aeabi_memclr(d, n); }
void __aeabi_memclr8(void *d, unsigned n) { __aeabi_memclr(d, n); }

__attribute__((noinline)) static u32 sq_ctx_at(void)
{
    u32 at;
    __asm__ volatile("adr %0, 1f\n\tb 2f\n\t.balign 4\n1:\t.word 0\n2:" : "=r"(at));
    return at;
}
static struct st *sq_ctx(void) { return (struct st *)(uintptr_t)W(sq_ctx_at()); }

/* ---------------------------------------------------------------------------------------------- helpers */
static u32 udiv(u32 n, u32 d) { return d ? (u32)udiv64(n, d, 0) : 0; }
static int a16i(int x) { return x < 0 ? -(int)udiv((u32)(-x + 15), 16u) * 16 : (int)(udiv((u32)x, 16u) * 16u); }
static int evi(int x) { return x < 0 ? -(int)(((u32)(-x) + 1u) & ~1u) : x & ~1; }
static int sq_min(int a, int b) { return a < b ? a : b; }
static int sq_max(int a, int b) { return a > b ? a : b; }
static int sq_abs(int a) { return a < 0 ? -a : a; }
static u32 sq_len(const char *t) { u32 n = 0; while (t[n]) n++; return n; }
static int sq_eq(const char *a, const char *b) { while (*a && *a == *b) { a++; b++; } return *a == *b; }
static u32 put_s(char *d, u32 n, u32 cap, const char *t) { while (*t && n < cap - 1u) d[n++] = *t++; d[n] = 0; return n; }
static u32 put_u(char *d, u32 n, u32 cap, u64 v)
{
    char tmp[24];
    u32 k = 0;
    do { u64 r, q = udiv64(v, 10u, &r); tmp[k++] = (char)('0' + r); v = q; } while (v);
    while (k && n < cap - 1u) d[n++] = tmp[--k];
    d[n] = 0;
    return n;
}
/* a scaled integer v (value x 10^places, as js_fixed_d gives it) as the page's toFixed(places) text */
static u32 put_fix(char *d, u32 n, u32 cap, u64 v, int places)
{
    u64 p10 = places == 0 ? 1u : places == 1 ? 10u : places == 2 ? 100u : 1000u, fr;
    n = put_u(d, n, cap, udiv64(v, p10, &fr));
    if (places && n < cap - 1u) {
        d[n++] = '.';
        for (u64 p = p10; p > 1u && n < cap - 1u; ) { p = udiv64(p, 10u, 0); u64 q = udiv64(fr, p, &fr); d[n++] = (char)('0' + q); }
        d[n] = 0;
    }
    return n;
}
/* JS a16(W * r) / ev(H * r) for the ratio r (the doubles 2/3, 1/3, 1/6 as the page computes them) */
static i64 dfloor(dbl x) { return !x.m ? 0 : x.e >= 0 ? (i64)(x.m << x.e) : -x.e > 63 ? 0 : (i64)(x.m >> -x.e); }
static dbl rat_d(u32 r) { return dratio(RAT_N[r], RAT_D[r]); }
static int a16r(int W_, u32 r) { return (int)(udiv((u32)dfloor(dmul(rat_d(r), (u64)W_)), 16u) * 16u); }
static int evr(int H_, u32 r) { return (int)(dfloor(dmul(rat_d(r), (u64)H_)) & ~(i64)1); }
static int is_int_bin(u32 r) { return r != 1u; }     /* Number.isInteger(1 / r): 1, 2, 3, 6 yes; 1.5 no (node) */
static int bin_h(int H_, u32 r) { return evr(H_, r) - (r == 4u ? VM_ROWS : 0); }   /* binH: ÷6 keeps VM_ROWS spare rows */
/* Math.round(x / 2) * 2 and Math.round(x / 16) * 16 of a positive double (round half up, exact) */
static int round_to(dbl x, int k) { x.e -= k == 2 ? 1 : 4; return (int)js_fixed_d(x, 0) * k; }

static void rec_write(struct st *st);

static int busy(void)
{
    u32 sel = W(MOV_SELECTOR) == 0x21u ? MOVREC_SEL21 : MOVREC_DEFAULT;
    return *(volatile u8 *)(uintptr_t)sel || W(XMP_FOBJ_PTR) || *(volatile u8 *)(uintptr_t)MOV_ACTIVE;
}

/* ---------------------------------------------------------------------------------------------- rates */
static struct rat rate_q(const struct rcp *q) { struct rat r = {CD_CLK, (u32)q->hm * q->lo}; return r; }
static struct rat rate_std(u32 i) { struct rat r = {STD_N[i], STD_D[i]}; return r; }
static i64 rdiff(struct rat a, struct rat b) { return (i64)((u64)a.n * b.d) - (i64)((u64)b.n * a.d); }   /* sign of a - b */
static u64 rden(struct rat a, struct rat b) { return (u64)a.d * b.d; }
static int same(struct rat a, struct rat b)          /* |a - b| < 5e-4 */
{
    i64 x = rdiff(a, b);
    return (u64)(x < 0 ? -x : x) * 2000u < rden(a, b);
}
static int ge_tol(struct rat a, struct rat b) { return rdiff(a, b) * 2000 >= -(i64)rden(a, b); }   /* a >= b - 5e-4 */
static int gt_tol(struct rat a, struct rat b) { return rdiff(a, b) * 2000 > (i64)rden(a, b); }     /* a > b + 5e-4 */
static int lt_tol(struct rat a, struct rat b) { return rdiff(a, b) * 2000 < -(i64)rden(a, b); }    /* a < b - 5e-4 */
static int rgt(struct rat a, struct rat b) { return rdiff(a, b) > 0; }
static int rge(struct rat a, struct rat b) { return rdiff(a, b) >= 0; }
static u32 f3_put(char *d, u32 n, u32 cap, struct rat f) { return put_fix(d, n, cap, (u64)js_fixed_d(dratio(f.n, f.d), 3), 3); }
static int f3_same(struct rat a, struct rat b) { return js_fixed_d(dratio(a.n, a.d), 3) == js_fixed_d(dratio(b.n, b.d), 3); }

/* ---------------------------------------------------------------------------------------------- geometry */
static int dc_preset(u32 w, u32 h)
{
    for (u32 i = 0; i < N_DC; i++) if (DCW[i] == w && DCH[i] == h) return (int)i;
    return -1;
}
static void k_label(char *d, u32 w)                  /* kLabel */
{
    u32 n = 0;
    if (4u * w < 3u * 1024u) {
        u32 t = (10u * w + 512u) >> 10;
        n = put_u(d, n, 6, udiv(t, 10u));
        d[n++] = '.';
        n = put_u(d, n, 6, t - 10u * udiv(t, 10u));
    } else {
        u32 x2 = (w + 256u) >> 9;
        n = put_u(d, n, 6, x2 >> 1);
        if (x2 & 1u) { d[n++] = '.'; d[n++] = '5'; }
    }
    d[n++] = 'K';
    d[n] = 0;
}
static void div_text(char *d, u32 W_, u32 H_, u32 w, u32 h)   /* divText */
{
    u32 n = 0, kw = 0, kh = 0;
    for (u32 i = 0; i < 8u && !kw; i++) if (a16i((int)udiv(W_, DIVK[i])) == (int)w) kw = DIVK[i];
    for (u32 i = 0; i < 8u && !kh; i++)
        if (evi((int)udiv(H_, DIVK[i])) == (int)h || (DIVK[i] == 6u && evi((int)udiv(H_, 6u)) - VM_ROWS == (int)h)) kh = DIVK[i];
    d[0] = 0;
    if (!kw && !kh) return;
    if (kw) n = put_u(d, n, 8, kw);
    d[n++] = 'x'; d[n] = 0;
    if (kh) put_u(d, n, 8, kh);
}
static u32 res_list(struct st *st, u32 W_, u32 H_, struct ritem *out)   /* resList */
{
    u32 n = 0, hd = dc_preset(W_, H_) == 1;
    for (u32 r = 0; r < N_RAT; r++) {
        int w = a16r((int)W_, r), h = is_int_bin(r) ? bin_h((int)H_, r) : evi((int)udiv((u32)w * H_, W_));
        if (w < WMIN || h < HMIN) continue;
        struct ritem *it = &out[n++];
        it->w = (u16)w; it->h = (u16)h; it->ratio = 1; it->kl = (u8)r;
        k_label(it->lab, (u32)w);
    }
    u32 nr = n;
    for (u32 k = 0; k < 7u; k++) {
        u32 w = KL_W[k];
        if (w > W_ || evi((int)udiv(w * H_, W_)) < HMIN) continue;
        u32 dup = 0;
        for (u32 i = 0; i < nr && !dup; i++) dup = sq_eq(out[i].lab, KL_N[k]);
        if (dup) continue;
        struct ritem *it = &out[n++];
        it->w = (u16)w; it->h = (u16)evi((int)udiv(w * H_, W_)); it->ratio = 0; it->kl = (u8)k;
        put_s(it->lab, 0, 6, KL_N[k]);
    }
    if (hd)
        for (u32 k = 7; k < N_KHD; k++) {
            struct ritem *it = &out[n++];
            it->w = KL_W[k]; it->h = KL_H[k]; it->ratio = 0; it->kl = (u8)k;
            put_s(it->lab, 0, 6, KL_N[k]);
        }
    for (u32 k = N_KHD; k < N_KL; k++) {            /* 0.0.6test: 1x2 / 1x3, full width, labelled by the merge */
        int w = a16i((int)W_), h = evi((int)udiv(H_, KL_H[k]));
        if (w < WMIN || h < HMIN) continue;
        struct ritem *it = &out[n++];
        it->w = (u16)w; it->h = (u16)h; it->ratio = 0; it->kl = (u8)k;
        put_s(it->lab, 0, 6, KL_N[k]);
    }
    u32 m = 0;
    for (u32 i = 0; i < n; i++) {                    /* one per W x H (the first), then by width, stable */
        u32 seen = 0;
        for (u32 j = 0; j < m && !seen; j++) seen = out[j].w == out[i].w && out[j].h == out[i].h;
        if (!seen) { if (m != i) out[m] = out[i]; m++; }
    }
    for (u32 i = 1; i < m; i++) {
        struct ritem x = out[i];
        u32 j = i;
        while (j && out[j - 1u].w > x.w) { out[j] = out[j - 1u]; j--; }
        out[j] = x;
    }
    for (u32 i = 0; i < m; i++) div_text(out[i].div, W_, H_, out[i].w, out[i].h);
    (void)st;
    return m;
}
static u32 refresh_list(struct st *st) { return st->n_list = res_list(st, st->s.dcw, st->s.dch, st->list); }

static void res_now(struct st *st, u32 *w, u32 *h)  /* res() */
{
    struct sel *s = &st->s;
    if (s->custom) { *w = s->cw; *h = s->ch; return; }
    if (s->resk) {
        refresh_list(st);
        for (u32 i = 0; i < st->n_list; i++)
            if (sq_eq(st->list[i].lab, KL_N[s->resk - 1u])) { *w = st->list[i].w; *h = st->list[i].h; return; }
    }
    u32 r = s->rat;
    if (a16r((int)s->dcw, r) < WMIN || bin_h((int)s->dch, r) < HMIN) r = 0;   /* x1, the ratio not forgotten */
    int rw = a16r((int)s->dcw, r);
    *w = (u32)rw;
    *h = (u32)(is_int_bin(r) ? bin_h((int)s->dch, r) : evi((int)udiv((u32)rw * s->dch, s->dcw)));
}
static int res_hit(struct st *st, u32 w, u32 h)
{
    refresh_list(st);
    for (u32 i = 0; i < st->n_list; i++) if (st->list[i].w == w && st->list[i].h == h) return (int)i;
    return -1;
}

/* ---------------------------------------------------------------------------------------------- recipes */
static struct cell *cell_now(struct st *st)
{
    u32 rw, rh;
    res_now(st, &rw, &rh);
    struct sel *s = &st->s;
    struct cell *c = 0, *old = &st->cache[0];
    for (u32 i = 0; i < N_CACHE; i++) {
        struct cell *x = &st->cache[i];
        if (x->used && x->dcw == s->dcw && x->dch == s->dch && x->rw == rw && x->rh == rh) c = x;
        if (x->used < old->used) old = x;
    }
    if (c) { st->hits++; c->used = ++st->tick; return st->cur = c; }
    c = old;
    st->computes++;
    int n = core_qualities_tol((int)s->dcw, (int)s->dch, (int)rw, (int)rh, 0, 1, TOL_NUM, TOL_DEN, st->scratch,
                               (int)CORE_MAX_QUAL);
    c->dcw = s->dcw; c->dch = s->dch; c->rw = rw; c->rh = rh; c->used = ++st->tick; c->used_n = st->computes;
    c->n = n < 0 || n > (int)MAXR ? -1 : n;          /* no data: the page's "no FPSDATA" */
    for (int i = 0; i < c->n; i++) {
        const core_quality *q = &st->scratch[i];
        struct rcp *r = &c->r[i];
        r->hm = (u16)q->hm; r->lo = (u16)q->vmin_lo; r->mh = (u16)q->mh; r->mv = (u16)q->mv; r->ad = (u16)q->ad;
        r->hb = (u16)q->hbin; r->vb = (u16)q->vbin; r->scw = (u16)q->cw; r->sch = (u16)q->ch; r->sw = (u16)q->sw;
        r->sh = (u16)q->sh; r->vis_w = (u16)q->vis_w; r->vis_h = (u16)q->vis_h; r->zh = (u16)q->zh;
        r->zv = (u16)q->zv; r->key = (u16)q->key; r->rs_us = (u32)q->rs_us;
        r->win_w = (u16)q->win_w; r->win_h = (u16)q->win_h; r->rec_w = (u16)q->rec_w; r->rec_h = (u16)q->rec_h;
    }
    return st->cur = c;
}
static u32 rq_of(const struct rcp *q) { return (u32)q->ad << 16 | (u32)q->mh << 12 | (u32)q->mv << 8 | (u32)q->hb << 4 | q->vb; }
static int is_preset(const struct rcp *q) { return q->hb == 1 && q->vb == 1; }
static u32 pval(const struct rcp *q, u32 k)
{
    return k == K_AD ? q->ad : k == K_SCW ? q->scw : k == K_SCH ? q->sch : k == K_MH ? q->mh : k == K_MV ? q->mv :
           k == K_HB ? q->hb : q->vb;
}
static int usable(const struct st *st, const struct rcp *q)
{
    struct rat f = {st->s.fps_n, st->s.fps_d};
    return ge_tol(rate_q(q), f);
}
/* The bits a recipe RECORDS (Bei 10-30, notes/RWZM_14BIT_CHECK.md; the page's recBits): RWZM carries 12 bits, so a
 * 14-bit-AD recipe that scales (zoom != 1024 on either axis, every CRCT bin) records a 12-bit DNG; only 1:1 is 14. */
static u32 rec_bits(const struct rcp *q)
{
    return q->ad == 14u && q->zh == 1024u && q->zv == 1024u && q->hb == 1u && q->vb == 1u ? 14u : 12u;
}
/* 0.0.3test (Bei 11-08: 8 / 10-bit CinemaDNG): the stock bit-depth setting (menu BIT row = stock MV_DNGQuality, the
 * source of truth as in RES-Custom) -- 8 / 10 bit makes the picker ask TAB1 / TAB2 and the record canvas carries that
 * depth's plane codes for ANY recipe (apply/ap.c); "RAW bit" (stock 12) records the recipe's own 12 / 14.  Read once per
 * layout (sq_test 11 bits 16..23 replace it offline, 0 = 12); a change drops the defaultPick memo. */
static u32 depth_now(struct st *st)
{
    if (st->bd.ok && st->bd.read_at == st->leaves) return st->bd.bits;
    u32 b = st->md_force ? (st->md_force - 1u) >> 16 & 0xFFu : 0u;   /* 0.0.4test: forced 0 = the firmware's own */
    if (!b) b = (u32)ap_raw_bits();
    b = b == 8u || b == 10u ? b : 12u;
    if (!st->bd.ok || b != st->bd.bits) st->memo_ok = 0;
    st->bd.read_at = st->leaves; st->bd.ok = 1; st->bd.bits = b;
    return b;
}
/* 0.0.4test (Bei 11-08): the QS FORMAT dial picks the depth.  It writes the stock setting by the menu BIT row's own
 * path: the row's MV_DNGQuality (0 / 1 / 2) -> the converter's table C2E401CC (-> eRawBitType 4 / 3 / 0) ->
 * MenuAction_w71c1 v74 @C04AAE08 (the GUI handler's +0x130 slot, FUN_c057a5f0) = FUN_c005bef0(settings, type, 0).
 * The QS GUI subscribes no MV_DNGQuality (only UicGuiMenuMovieRecord, the B2_5 page, does), so the tile calls the
 * setter and then posts the row value, as the row itself leaves it.  sq_test 11's forced depth follows. */
#define BIT_SET   0xC04AAE08u                         /* ARM: (this unused, eRawBitType) */
#define BIT_POST  0xC0593F30u                         /* (0, name, value): a variable message into the GUI queue */
static void depth_set(struct st *st, u32 bits)
{
    ((void (*)(u32, u32))BIT_SET)(0, bits == 8u ? 4u : bits == 10u ? 3u : 0u);
    ((void (*)(u32, uintptr_t, u32))BIT_POST)(0, (uintptr_t)"MV_DNGQuality", bits == 8u ? 0u : bits == 10u ? 1u : 2u);
    if (st->md_force && ((st->md_force - 1u) >> 16 & 0xFFu))
        st->md_force = (((st->md_force - 1u) & 0xFF00FFFFu) | bits << 16) + 1u;
    st->bd.ok = 0;                                    /* read back now (the stock normaliser may keep another) */
}
static u32 depth_idx(u32 b) { return b == 8u ? 0u : b == 10u ? 1u : 2u; }   /* FORMAT's options 8 / 10 / RAW bit */
/* the bits a recipe records under the stock depth (the page's outBits) */
static u32 out_bits(struct st *st, const struct rcp *q)
{
    u32 b = depth_now(st);
    return b == 12u ? rec_bits(q) : b;
}
static const u16 NATIVE_W[4] = {6048, 5040, 4144, 3984};   /* the sensor's native readout widths (spec 原生寬度標點) */
static u32 native_w(u32 w) { for (u32 i = 0; i < 4u; i++) if (NATIVE_W[i] == w) return 1u; return 0; }
/* A coarse DC WIDTH step stops at the first native point it crosses, in either
 * direction. Exclude the current width so the next step can leave that point. */
static int native_w_stop(int w, int next)
{
    for (u32 i = 0; i < 4u; i++) {
        int p = NATIVE_W[i];
        if ((w < p && p <= next) || (next <= p && p < w)) next = p;
    }
    return next;
}
/* defaultPick (Bei 10-29, QS_DC_RES_SPEC 配方預設): no choice yet -> |DC_h/RES_h - mv| ascending, RECORDED bits descending
 * (Bei 10-30: rec_bits),
 * |DC_w/RES_w - mh| ascending, RS descending; a full tie keeps the list order (JS sort is stable).  The page's doubles
 * |H/h - m| order exactly as |H - m h| (one h per cell; a midpoint tie is exact in both) */
static int dpick_before(struct st *st, const struct rcp *a, const struct rcp *b, u32 rw, u32 rh)
{
    i64 va = (i64)st->s.dch - (i64)a->mv * rh, vb = (i64)st->s.dch - (i64)b->mv * rh;
    va = va < 0 ? -va : va; vb = vb < 0 ? -vb : vb;
    if (va != vb) return va < vb;
    if (out_bits(st, a) != out_bits(st, b)) return out_bits(st, a) > out_bits(st, b);   /* 0.0.3test: under 8 / 10 a tie */
    i64 ha = (i64)st->s.dcw - (i64)a->mh * rw, hb = (i64)st->s.dcw - (i64)b->mh * rw;
    ha = ha < 0 ? -ha : ha; hb = hb < 0 ? -hb : hb;
    if (ha != hb) return ha < hb;
    return a->rs_us > b->rs_us;
}
/* nearest(R, d) over the cell's recipes with filter `want` (bit 0 usable, bit 1 preset) */
static const struct rcp *nearest(struct st *st, u32 want)
{
    struct cell *c = st->cur;
    const struct rcp *best = 0;
    u32 bd = 0, rw = c->rw, rh = c->rh;               /* the cell is this DC x RES */
    for (int i = 0; i < c->n; i++) {
        const struct rcp *q = &c->r[i];
        if (((want & 1u) && !usable(st, q)) || ((want & 2u) && !is_preset(q))) continue;
        if (!st->s.rd_ok) { if (!best || dpick_before(st, q, best, rw, rh)) best = q; continue; }   /* !d: defaultPick(R) */
        u32 d = 0;
        for (u32 k = 0; k < N_PARAM; k++) d += pval(q, k) != st->s.rd[k];
        if (!best || d < bd || (d == bd && rgt(rate_q(q), rate_q(best)))) { best = q; bd = d; }
    }
    return best;
}
static const struct rcp *cur_recipe0(struct st *st)
{
    struct cell *c = st->cur;
    if (c->n <= 0) return 0;
    for (int i = 0; i < c->n; i++) if (rq_of(&c->r[i]) == st->s.rq && usable(st, &c->r[i])) return &c->r[i];
    const struct rcp *q = nearest(st, 3u);
    return q ? q : nearest(st, 1u);
}
/* v0.4.1test: memoised (defaultPick scans every recipe; a QS refresh asks dozens of times).  The key is everything
 * curRecipe reads: the cell (pointer + its compute serial), the rate, the choice. */
static const struct rcp *cur_recipe(struct st *st)    /* curRecipe */
{
    struct sel *s = &st->s;
    depth_now(st);                                    /* 0.0.3test: a new stock depth drops the memo */
    u32 k[5 + N_PARAM] = {(u32)(uintptr_t)st->cur, st->cur->used_n, s->fps_n, s->fps_d, s->rd_ok ? s->rq : 0xFFFFFFFFu};
    for (u32 i = 0; i < N_PARAM; i++) k[5 + i] = s->rd_ok ? s->rd[i] : 0u;
    u32 hit = st->memo_ok;
    for (u32 i = 0; hit && i < 5u + N_PARAM; i++) hit = st->memo_key[i] == k[i];
    if (hit) return st->memo;
    st->memo = cur_recipe0(st);
    for (u32 i = 0; i < 5u + N_PARAM; i++) st->memo_key[i] = k[i];
    st->memo_ok = 1;
    return st->memo;
}
static int has_q(const struct st *st) { return st->cur->n > 0; }    /* quals() non-null (and not empty) */
static struct rat fps_max(const struct st *st)       /* fpsMax(quals()) */
{
    struct rat m = {0, 1}, k1000 = {1000, 1};
    const struct cell *c = st->cur;
    for (int i = 0; i < c->n; i++) if (is_preset(&c->r[i]) && rgt(rate_q(&c->r[i]), m)) m = rate_q(&c->r[i]);
    return rgt(m, k1000) ? k1000 : m;
}
static int qmark(const struct st *st, struct rat f)  /* Q.some(q => same(q.max, f)) */
{
    const struct cell *c = st->cur;
    for (int i = 0; i < c->n; i++) if (is_preset(&c->r[i]) && same(rate_q(&c->r[i]), f)) return 1;
    return 0;
}
static u32 fps_list(struct st *st)                    /* fpsList */
{
    struct sel *s = &st->s;
    u32 n = 0;
    if (!has_q(st)) return st->n_fl = 0;
    struct rat M = fps_max(st), k1000 = {1000, 1};
    for (u32 i = 0; i < N_STD; i++) {
        struct fent *e = &st->fl_e[n++];
        e->f = rate_std(i); e->std = (u8)(i + 1u); e->custom = 0; e->na = gt_tol(e->f, M);
    }
    const struct cell *c = st->cur;
    for (int i = 0; i < c->n; i++) {
        if (!is_preset(&c->r[i])) continue;
        struct rat f = rate_q(&c->r[i]);
        if (rgt(f, k1000)) continue;
        u32 dup = 0;
        for (u32 j = 0; j < n && !dup; j++) dup = same(st->fl_e[j].f, f);
        if (dup) continue;
        struct fent *e = &st->fl_e[n++];
        e->f = f; e->std = 0; e->custom = 0; e->na = 0;
    }
    for (u32 j = 0; j < n; j++) st->fl_e[j].mark = (u8)qmark(st, st->fl_e[j].f);
    if (s->fc_d) {
        struct rat fc = {s->fc_n, s->fc_d};
        u32 dup = 0;
        for (u32 j = 0; j < n && !dup; j++) dup = same(st->fl_e[j].f, fc);
        if (!gt_tol(fc, M) && !dup) {
            struct fent *e = &st->fl_e[n++];
            e->f = fc; e->std = 0; e->custom = 1; e->na = 0; e->mark = (u8)qmark(st, fc);
        }
    }
    for (u32 i = 1; i < n; i++) {                    /* by rate (no two within 5e-4: no ties) */
        struct fent x = st->fl_e[i];
        u32 j = i;
        while (j && rgt(st->fl_e[j - 1u].f, x.f)) { st->fl_e[j] = st->fl_e[j - 1u]; j--; }
        st->fl_e[j] = x;
    }
    return st->n_fl = n;
}
static int fps_sel(struct st *st)
{
    struct rat f = {st->s.fps_n, st->s.fps_d};
    fps_list(st);
    for (u32 i = 0; i < st->n_fl; i++) if (same(st->fl_e[i].f, f)) return (int)i;
    return -1;
}
static u32 fmt_rate(char *d, u32 cap, const struct fent *e)   /* fmtF */
{
    return e->std ? put_s(d, 0, cap, STD_S[e->std - 1u]) : f3_put(d, 0, cap, e->f);
}
static void fix_fps(struct st *st)                    /* fixFps: after a DC / RES change */
{
    cell_now(st);
    if (!has_q(st)) return;
    struct rat M = fps_max(st), f = {st->s.fps_n, st->s.fps_d};
    if (!gt_tol(f, M)) return;
    fps_list(st);
    struct rat to = M;
    for (u32 i = 0; i < st->n_fl; i++) if (st->fl_e[i].std && !st->fl_e[i].na) to = st->fl_e[i].f;
    st->s.fps_n = to.n; st->s.fps_d = to.d;
}
static void fine_exit(struct st *st)                  /* fineExit */
{
    struct sel *s = &st->s;
    struct rat f = {s->fps_n, s->fps_d};
    s->fine = 0;
    fps_list(st);
    u32 hit = 0;
    for (u32 i = 0; i < st->n_fl; i++) if (!st->fl_e[i].custom && same(st->fl_e[i].f, f)) hit = 1;
    if (hit) s->fc_d = 0; else { s->fc_n = f.n; s->fc_d = f.d; }
}
static struct rat fine_step(struct st *st, struct rat f, int d, int big)   /* fineStep */
{
    const struct cell *c = st->cur;
    struct rat k1000 = {1000, 1};
    for (int n = 0; n < (big ? 10 : 1); n++) {
        struct rat best = {0, 0};
        for (int i = 0; i < c->n; i++) {
            const struct rcp *q = &c->r[i];
            if (!is_preset(q)) continue;
            u64 num = (u64)CD_CLK * f.d, den = (u64)q->hm * f.n, V;      /* v = clk / (hm x f) */
            V = d > 0 ? udiv64(num - 1u, den, 0) : udiv64(num, den, 0) + 1u;   /* ceil(v) - 1 / floor(v) + 1 */
            if (V < q->lo || V > VMAX_MAX) continue;
            struct rat g = {CD_CLK, (u32)(q->hm * V)};
            if (gt_tol(g, k1000)) continue;
            if (d > 0 ? gt_tol(g, f) && (!best.d || rgt(best, g)) : lt_tol(g, f) && (!best.d || rgt(g, best))) best = g;
        }
        if (!best.d) break;
        if (f3_same(best, f)) { f = best; n--; continue; }   /* the user sees every step move */
        f = best;
    }
    return f;
}

/* ---------------------------------------------------------------------------------------------- setDC / setRes */
static int mem_find(const struct sel *s, u32 w, u32 h)
{
    for (u32 i = 0; i < s->nmem; i++) if (s->mem[i][0] == w && s->mem[i][1] == h) return (int)i;
    return -1;
}
static void mem_drop(struct sel *s, int i)
{
    if (i < 0) return;
    for (u32 j = (u32)i; j + 1u < s->nmem; j++) for (u32 k = 0; k < 4u; k++) s->mem[j][k] = s->mem[j + 1u][k];
    s->nmem--;
}
static void mem_put(struct sel *s, u32 dw, u32 dh, u32 w, u32 h)
{
    int i = mem_find(s, dw, dh);
    if (i < 0) {
        if (s->nmem == N_MEM) mem_drop(s, 0);         /* the oldest goes (the page keeps all) */
        i = (int)s->nmem++;
    }
    s->mem[i][0] = dw; s->mem[i][1] = dh; s->mem[i][2] = w; s->mem[i][3] = h;
}
static void set_dc0(struct st *st, int w, int h)
{
    struct sel *s = &st->s;
    if (s->custom) mem_put(s, s->dcw, s->dch, s->cw, s->ch);
    s->dcw = (u32)sq_max(WMIN, sq_min(WMAX, a16i(w)));
    s->dch = (u32)sq_max(HMIN, sq_min(HMAX, evi(h)));
    int m = mem_find(s, s->dcw, s->dch);
    s->custom = 0;
    if (m >= 0 && s->mem[m][2] <= s->dcw && s->mem[m][3] <= s->dch) { s->custom = 1; s->cw = s->mem[m][2]; s->ch = s->mem[m][3]; }
    u32 rw, rh;
    res_now(st, &rw, &rh);
    s->raw = rw; s->rah = rh;
    st->dirty = 1;
}
static void set_dc(struct st *st, int w, int h) { set_dc0(st, w, h); fix_fps(st); }
static void set_res0(struct st *st, int w, int h)
{
    struct sel *s = &st->s;
    w = sq_max(WMIN, sq_min((int)s->dcw, a16i(w)));
    h = sq_max(HMIN, sq_min((int)s->dch, evi(h)));
    int hit = res_hit(st, (u32)w, (u32)h), q = -1;
    if (hit >= 0 && st->list[hit].ratio)
        for (u32 r = 0; r < N_RAT && q < 0; r++) if (a16r((int)s->dcw, r) == w) q = (int)r;
    if (q >= 0) { s->rat = (u32)q; s->resk = 0; s->custom = 0; mem_drop(s, mem_find(s, s->dcw, s->dch)); }
    else if (hit >= 0) { s->resk = st->list[hit].kl + 1u; s->custom = 0; mem_drop(s, mem_find(s, s->dcw, s->dch)); }
    else { s->resk = 0; s->custom = 1; s->cw = (u32)w; s->ch = (u32)h; }
    st->dirty = 1;
}
static void set_res(struct st *st, int w, int h) { set_res0(st, w, h); fix_fps(st); }

/* visible(): the selected recipe's own visible size (<= 2 % short), else the nominal */
static void visible(struct st *st, u32 *w, u32 *h, u32 *shrt)
{
    u32 rw, rh;
    res_now(st, &rw, &rh);
    cell_now(st);
    const struct rcp *c = cur_recipe(st);
    if (c) { *w = c->vis_w; *h = c->vis_h; *shrt = c->vis_h + 10u < rh || c->vis_w + 16u < rw; return; }
    *w = rw - 16u; *h = rh - 10u; *shrt = 0;
}
/* v0.7.38test (Bei 11-05, "display rules, single source"): the effective recipe -- cur_recipe,
 * the one that overrides RES, not the sub-QS picks -- is the single source of every recipe-dependent text.  eff_now()
 * gives the RES the user gets (v0.7.35test effRes: the recipe's visible + 16 x 10, else the RES), its visible size and
 * shortness, and the merge hint; RES tile and RES WIDTH / HEIGHT both read it (the page's effDisplay).
 * The hint: per axis sensor merge x ISP bin, "HxV"; 0.0.6test (Bei 11-10): always the merge, "+RW" when the RWZM is on
 * (either axis not 1024, the ÷3 bins' forced 1025 included: "9x18+RW" at most, 7 chars); no recipe: the geometric DC / RES
 * division (div_text). */
struct eff { const struct rcp *c; u32 rw, rh, w, h, vw, vh, shr; char hint[8]; };
static int rw_on(const struct rcp *c) { return c->zh > 1024u || c->zv > 1024u; }
static void recipe_hint(const struct rcp *c, char *d)    /* recipeHint */
{
    u32 n = put_u(d, 0, 8, (u32)c->mh * c->hb);
    d[n++] = 'x'; d[n] = 0;
    n = put_u(d, n, 8, (u32)c->mv * c->vb);
    if (rw_on(c)) put_s(d, n, 8, "+RW");
}
static const struct rcp *eff_now(struct st *st, struct eff *e)   /* effDisplay */
{
    res_now(st, &e->rw, &e->rh);
    cell_now(st);
    const struct rcp *c = e->c = cur_recipe(st);
    visible(st, &e->vw, &e->vh, &e->shr);
    if (c) { e->w = c->vis_w + 16u; e->h = c->vis_h + 10u; recipe_hint(c, e->hint); }
    else { e->w = e->rw; e->h = e->rh; div_text(e->hint, st->s.dcw, st->s.dch, e->w, e->h); }
    return c;
}

/* ---------------------------------------------------------------------------------------------- recipe parameters */
static const struct rcp *combo(struct st *st, u32 key, u32 v)   /* combo(key, v): every other choice kept */
{
    const struct rcp *c = cur_recipe(st), *best = 0;
    if (!c) return 0;
    const struct cell *cl = st->cur;
    for (int i = 0; i < cl->n; i++) {
        const struct rcp *q = &cl->r[i];
        if (pval(q, key) != v) continue;
        u32 ok = 1;
        for (u32 k = K_AD; k <= K_VB && ok; k++)
            if (k != key && k != K_SCW && k != K_SCH && pval(q, k) != pval(c, k)) ok = 0;
        if (!ok) continue;
        if (key == K_SCW || key == K_SCH) return q;
        if (!best || rgt(rate_q(q), rate_q(best))) best = q;
    }
    return best;
}
static void use_recipe(struct st *st, const struct rcp *q)   /* useRecipe */
{
    struct sel *s = &st->s;
    if (!usable(st, q)) return;                       /* v0.2.2test: a recipe never lowers the FPS (DC > RES > FPS > RECIPE) */
    s->rq = rq_of(q); s->rd_ok = 1;
    for (u32 k = 0; k < N_PARAM; k++) s->rd[k] = pval(q, k);
    st->dirty = 1;
}
static int ok_v(struct st *st, u32 key, u32 v)      /* ok(v): the combination exists and reaches the FPS */
{
    const struct rcp *n = combo(st, key, v);
    return n && usable(st, n);
}
static u32 vals(struct st *st, u32 key, u32 *out)   /* the distinct values of key, ascending */
{
    u32 n = 0, crop = key == K_SCW || key == K_SCH;  /* crop tiles list only what the other choices reach: no grey (Bei 10-29) */
    const struct cell *c = st->cur;
    for (int i = 0; i < c->n; i++) {
        u32 v = pval(&c->r[i], key), seen = 0;
        if (crop && !combo(st, key, v)) continue;
        for (u32 j = 0; j < n && !seen; j++) seen = out[j] == v;
        if (seen) continue;
        u32 j = n++;
        while (j && out[j - 1u] > v) { out[j] = out[j - 1u]; j--; }
        out[j] = v;
    }
    return n;
}
static u32 short_name(char *d, u32 n, u32 k, u32 v)  /* SHORT */
{
    n = put_s(d, n, FT, k == K_AD ? "" : k == K_MH ? "S.HBIN" : k == K_MV ? "S.VBIN" : k == K_HB ? "I.HBIN" : "I.VBIN");
    n = put_u(d, n, FT, v);
    return k == K_AD ? put_s(d, n, FT, "bit") : n;
}
static void why_not(struct st *st, char *d, u32 key, u32 v)   /* whyNot */
{
    const struct rcp *c = cur_recipe(st), *best = 0;
    u32 n = 0, bd = 0;
    d[0] = 0;
    if (!c) return;
    const struct rcp *cb = combo(st, key, v);
    if (cb && !usable(st, cb)) {                      /* FPS comes first: "\u226422.48p" (SL_LE: "<" if the font lacks it) */
        n = put_s(d, 0, FT, SL_LE);
        n = put_fix(d, n, FT, (u64)js_fixed_d(dratio(CD_CLK, (u32)cb->hm * cb->lo), 2), 2);
        put_s(d, n, FT, "p");
        return;
    }
    if (key == K_MH || key == K_MV) {
        u32 mh = key == K_MH ? v : c->mh, mv = key == K_MV ? v : c->mv, hw = 0;
        for (u32 i = 0; i < 9u; i++) hw |= (u32)(HW_MODES[i][0] - '0') == mh && (u32)(HW_MODES[i][2] - '0') == mv;
        if (!hw) {
            n = put_s(d, 0, FT, "no "); n = put_u(d, n, FT, mh); n = put_s(d, n, FT, "x"); put_u(d, n, FT, mv);
            return;
        }
    }
    const struct cell *cl = st->cur;
    for (int i = 0; i < cl->n; i++) {
        const struct rcp *q = &cl->r[i];
        if (pval(q, key) != v) continue;
        u32 df = 0;
        for (u32 k = K_AD; k <= K_VB; k++) if (k != key && k != K_SCW && k != K_SCH && pval(q, k) != pval(c, k)) df++;
        if (!best || df < bd) { best = q; bd = df; }
    }
    if (!best) { put_s(d, 0, FT, "not at this RES"); return; }
    n = put_s(d, 0, FT, "\xE2\x86\x92");             /* "→12bit S.HBIN1" (U+2192: live run 4 drew it, "read → 3024") */
    static const u8 CHOICE[5] = {K_AD, K_MH, K_MV, K_HB, K_VB};
    u32 first = 1;
    for (u32 j = 0; j < 5u; j++) {
        u32 k = CHOICE[j];
        if (k == key || pval(best, k) == pval(c, k)) continue;
        if (!first) n = put_s(d, n, FT, " ");
        first = 0;
        n = short_name(d, n, k, pval(best, k));
    }
}
static u32 rwzm(char *d, u32 n, u32 z)               /* RWZM 1:1 within 0.5 %, else 1/x.xx */
{
    if (z < 1029u) return put_s(d, n, TXT, "RWZM 1:1");
    n = put_s(d, n, TXT, "RWZM 1/");
    return put_fix(d, n, TXT, (u64)js_fixed_d(dratio(z, 1024), 2), 2);
}

/* ---------------------------------------------------------------------------------------------- MB/s */
/* notes/MBPS_TILE_RESEARCH.md v2 (Bei 10-29: conservative): uncompressed = fps x (W x H x b / 8 + 79 184); lossless =
 * the frames the engine compresses at 5.0 bpp (12-bit merged; +2 for 14-bit, +1.5 for 1x1) + per-tile cost, the rest
 * written raw (engine time t_c from the stock tile grid).  The medium: SD (bus mode) or SSD, as the stock frame-rate
 * menu decides it (ssd ready && MediaSelect == 1). */
#define D(a, b) udiv64((u64)(a), (u64)(b), 0)
typedef u32 (*mfn1)(u32);
typedef u32 (*mfn2)(u32, u32);
typedef u32 (*mfn4)(u32, u32, u32, u32);
static u32 drv_of(u32 slot) { return slot == 5u ? ((mfn1)0xC0366A98u)(5u) : ((mfn1)0xC0366A98u)(1u); }   /* 1 or 5 only */
static void media_read(struct st *st)
{
    if (st->md.ok && st->md.read_at == st->leaves) return;
    st->md.read_at = st->leaves; st->md.ok = 1;
    if (st->md_force) {                               /* offline tests: no firmware */
        st->md.ssd = (st->md_force - 1u) >> 8 & 1u; st->md.sd_mode = (st->md_force - 1u) & 0xFFu;
        return;
    }
    st->md.ssd_ready = ((mfn1)0xC0518410u)(5u) & 0xFFu;
    st->md.ssd_mnt = ((mfn1)0xC0518490u)(5u) & 0xFFu;
    st->md.sd_mnt = ((mfn1)0xC0518490u)(1u) & 0xFFu;
    u32 d = drv_of(1u);
    st->md.sd_mode = d ? ((mfn1)W(W(d + 0x18u) + 0x24u))(d) : 0u;
    u32 fac = W(0xC31CAA80u), item = fac ? ((mfn1)W(W(fac + 4u) + 0x354u))(fac) : 0u;
    st->md.ms_a = st->md.ms_raw = 0xFFu;
    if (item) {
        u32 ivt = W(item + 0xCu), n = ((mfn1)W(ivt + 0x1Cu))(item);
        if (n) st->md.ms_a = ((mfn2)0xC006D530u)(item, ((mfn4)0xC00913F8u)(item, 0xFFFFu, n, 0x80000001u)) & 0xFFu;
        u32 pv = ((mfn2)W(ivt + 0x18u))(item, 0u);
        if (pv) st->md.ms_raw = W(pv);
    }
    u32 sd = st->md.sd_mnt, ssd = st->md.ssd_mnt;     /* method B: the mounts decide, else the saved choice (C00AB768) */
    st->md.ms_b = sd && !ssd ? 0u : ssd && !sd ? 1u : st->md.ms_raw;
    st->md.ssd = st->md.ssd_ready && st->md.ms_b == 1u;
}
static void media_rc(const struct st *st, u32 *r, u32 *c, const char **name)   /* MB/s sustained, cluster bytes */
{
    if (st->md.ssd) { *r = 390u; *c = 524288u; *name = "SSD"; return; }
    *c = 131072u;
    if (st->md.sd_mode == 3u) { *r = 240u; *name = "UHS-II"; } else { *r = 87u; *name = st->md.sd_mode == 2u ? "UHS-I" : "SD"; }   /* v0.4.0test: short (live6 footer overflow) */
}
struct mbps { u32 ok, ll_no; u64 u_m, ll_m; u32 du, dl; };   /* rates in bytes/s x 1000; duty in per mille; ll_no: lossless refuses */
static void mbps_of(struct st *st, struct mbps *o)
{
    const struct rcp *c = cur_recipe(st);
    o->ok = 0;
    if (!c) return;
    media_read(st);
    u32 W_ = c->rec_w, H_ = c->rec_h, b = out_bits(st, c);   /* the page's c.d.rec (v0.4.1test: was vis + 16 x 10) */
    u32 one = c->mh * c->mv == 1u && c->hb * c->vb == 1u && c->zh <= 1028u && c->zv <= 1028u;
    u32 b16 = 80u + 32u * (b == 14u) + 24u * one;     /* bpp x 16 */
    if (b16 > 16u * b) b16 = 16u * b;
    u64 px = (u64)W_ * H_, fu = D(px * b, 8u) + 79184u;
    u32 best = 0, gn = 0, gnx = 0, gpw = 0, gph = 0;
    for (u32 tw = 32; tw <= 512; tw += 32) for (u32 th = 16; th <= 512; th += 16) {   /* the stock tile grid */
        u32 nx = D(W_ + tw - 1u, tw), ny = D(H_ + th - 1u, th), n = nx * ny;
        if (n > 160u) continue;
        u32 cost = nx * tw * ny * th + 32250u * n;
        if (!best || cost < best) { best = cost; gn = n; gnx = nx; gpw = nx * tw; gph = ny * th; }
    }
    if (!best) return;
    u64 fc = D(px * b16, 128u) + 80u * gn + 80896u;
    if (fc > fu) fc = fu;
    o->ll_no = fc > LL_MAX_FRAME || b == 8u;            /* v0.4.0test: a compressed frame over 16 MiB is refused;
                                                           0.0.3test: Lossless takes 10 / 12 bit only (control.c) */
    u64 tc = D((u64)gpw * gph * 47u, 10000u) + D((u64)gnx * gph * 46u, 100u) + 2000u;   /* engine us per frame */
    u64 fpsm = D((u64)st->s.fps_n * 1000u, st->s.fps_d);  /* fps x 1000 */
    u64 lim = D(1000000000u, tc), raw_m = fpsm > lim ? fpsm - lim : 0u;   /* frames/s x 1000 the engine leaves raw */
    o->u_m = fpsm * fu;
    o->ll_m = (fpsm - raw_m) * fc + raw_m * fu;
    u32 r, cl; const char *nm;
    media_rc(st, &r, &cl, &nm);
    u64 fl = fpsm ? D(o->ll_m, fpsm) : fu;              /* the mean lossless frame */
    u64 tu = D(D(fu + cl - 1u, cl) * cl, r) + 510u, tl = D(D(fl + cl - 1u, cl) * cl, r) + 510u;   /* us per frame */
    o->du = (u32)(D(fpsm * tu, 1000000u)); o->dl = (u32)(D(fpsm * tl, 1000000u));
    o->ok = 1;
}
static u32 mb_put(char *d, u32 n, u64 m) { return put_u(d, n, TXT, D(D(m, 1000u) + 500000u, 1000000u)); }   /* round(MB/s) */

/* ---------------------------------------------------------------------------------------------- the apply hook */
/* The later "apply" step installs the effective selection: core_quality_plan(q, CLK, hm x VMAX) -> core_smc_create
 * (the sensor mode) and core_quality_spec -> core_isp_plan / core_isp_row (the ISP), the kernels / mode into BINFILT.
 * Today it only records what that would be (st->applied), at every leave(), outside the QS key path. */
/* the VMAX step at the selected rate: the smallest VMAX >= lo whose rate does not exceed it */
static u32 vmax_of(const struct st *st, const struct rcp *c)
{
    u64 num = (u64)CD_CLK * st->s.fps_d, den = (u64)c->hm * st->s.fps_n, v = udiv64(num + den - 1u, den, 0);
    return (u32)(v < c->lo ? c->lo : v > VMAX_MAX ? VMAX_MAX : v);
}
static void sq_apply(struct st *st);
/* the QS change event / leave(): hand the effective selection to the apply unit (it commits only what changed) */
static void sq_push(struct st *st)
{
    if (st->push_pause) { st->lt[15]++; return; }        /* v0.7.0test: isolate the apply step (sq_test 30) */
    if (st->scan.pending && st->scan.on_page) return;    /* 0.0.2test: inside the QR page's settings session (sl_mqr_v73) */
    sq_apply(st);
    const struct rcp *c = cur_recipe(st);
    struct ap_sel *a = &st->ap_last;
    zero(a, sizeof *a);
    a->bytes = sizeof *a; a->abi = AP_ABI;
    a->valid = st->applied.valid; a->fmt = 0;               /* FORMAT: DNG only (MOV grey) */
    if (c) {
        a->dcw = st->applied.dcw; a->dch = st->applied.dch; a->rw = st->applied.rw; a->rh = st->applied.rh;
        a->key = (s32)c->key; a->hbin = (s32)c->hb; a->vbin = (s32)c->vb; a->hm = c->hm; a->vmax = st->applied.vmax;
        a->fps_n = st->applied.fps_n; a->fps_d = st->applied.fps_d;
        a->kh = st->applied.kh; a->kv = st->applied.kv; a->km = st->applied.km;
    }
    a->standby = 1;                                        /* Bei 10-29: the standby LV runs our readout too */
    st->ap_pushes++;
    st->ap_boot_owed = 0;
    st->ap_rc = ap_request(st->ap_mem, a);
    /* v0.7.38test (live 11-05: runs 0, up to 20 posts for nothing): committed by ANY path -- sup_entry, the boot
     * callback, leave(), a layout reload -- ends the boot apply; the poller only stays for a selection not yet in */
    if (st->ap_rc == AP_OK || st->ap_rc == AP_IDLE) st->boot.done = 1;
    /* no separate ap_flush here: ap_request already commits whatever is owed (a refused or deferred commit) */
}
static void sq_apply(struct st *st)
{
    struct sel *s = &st->s;
    u32 rw, rh;
    res_now(st, &rw, &rh);
    cell_now(st);
    const struct rcp *c = cur_recipe(st);
    st->applies++;
    st->applied.valid = c != 0;
    if (!c) return;
    st->applied.dcw = s->dcw; st->applied.dch = s->dch; st->applied.rw = rw; st->applied.rh = rh;
    st->applied.key = c->key; st->applied.hm = c->hm;
    st->applied.vmax = vmax_of(st, c);
    st->applied.fps_n = s->fps_n; st->applied.fps_d = s->fps_d;
    st->applied.kh = s->kh; st->applied.kv = s->kv; st->applied.km = s->km;
    st->applied.ri = (s32)(c - st->cur->r);
}

/* ---------------------------------------------------------------------------------------------- QR */
/* The payload (notes/QR_QS_RESEARCH.md §3.4, shared with the web page): these fields MSB first, each cut to its width,
 * CRC-8 (poly 0x07, init 0, no reflection, no xor) over the 213 bits, one 0 pad bit, base64url without '=' = 37 chars.
 * ver 1 | DC w h | RES w h | FPS pick (0..28 STD, 29 tuned / other, 30 a recipe maximum) | VMAX | HMAX | AD (0 = 11,
 * 1 = 12, 2 = 14) | sensor mh mv | ISP hbin vbin | readout key | kernels kh kv, mode | recipe CUSTOM | visible w h |
 * RS us | format (0 DNG) | RES CUSTOM | sensor crop scw sch | ISP window win_w win_h */
#define N_QF 27u
#define QF_BITS 213u
static const u8 QF_W[N_QF] = {4, 13, 12, 13, 12, 5, 15, 16, 2, 2, 3, 4, 4, 6, 3, 3, 1, 1, 13, 12, 17, 1, 1, 13, 12, 13, 12};
static const char B64U[65] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

static int qr_fields(struct st *st, u32 *f)        /* 0: no recipe (nothing to show) */
{
    struct sel *s = &st->s;
    u32 rw, rh, vw, vh, shr, i = 0;
    res_now(st, &rw, &rh);
    cell_now(st);
    const struct rcp *c = cur_recipe(st);
    if (!c) return 0;
    int k = fps_sel(st);
    u32 pick = 29u;
    if (k >= 0) { const struct fent *e = &st->fl_e[k]; pick = e->std ? e->std - 1u : e->mark ? 30u : 29u; }
    visible(st, &vw, &vh, &shr);
    f[i++] = 1u; f[i++] = s->dcw; f[i++] = s->dch; f[i++] = rw; f[i++] = rh; f[i++] = pick;
    f[i++] = vmax_of(st, c); f[i++] = c->hm; f[i++] = c->ad == 11u ? 0u : c->ad == 12u ? 1u : 2u;
    f[i++] = c->mh; f[i++] = c->mv; f[i++] = c->hb; f[i++] = c->vb; f[i++] = c->key;
    f[i++] = s->kh; f[i++] = s->kv; f[i++] = s->km; f[i++] = !is_preset(c);
    f[i++] = vw; f[i++] = vh; f[i++] = c->rs_us > 131071u ? 131071u : c->rs_us; f[i++] = 0u;   /* DNG */
    f[i++] = res_hit(st, rw, rh) < 0; f[i++] = c->scw; f[i++] = c->sch; f[i++] = c->win_w; f[i++] = c->win_h;
    return 1;
}
static void qr_pack(const u32 *f, char *out)       /* -> 37 chars + NUL */
{
    u8 b[28];
    u32 n = 0, crc = 0;
    for (u32 i = 0; i < sizeof b; i++) b[i] = 0;
    for (u32 i = 0; i < N_QF; i++)
        for (u32 w = QF_W[i]; w--; n++) if (f[i] >> w & 1u) b[n >> 3] |= (u8)(0x80u >> (n & 7u));
    for (u32 i = 0; i < QF_BITS; i++) {               /* CRC-8, bit by bit, MSB first */
        u32 top = (crc >> 7 & 1u) ^ (b[i >> 3] >> (7u - (i & 7u)) & 1u);
        crc = crc << 1 & 0xFFu;
        if (top) crc ^= 0x07u;
    }
    for (u32 w = 8; w--; n++) if (crc >> w & 1u) b[n >> 3] |= (u8)(0x80u >> (n & 7u));
    for (u32 i = 0; i < QR_CHARS; i++) {             /* the pad bit is already 0 */
        u32 v = 0;
        for (u32 j = 0; j < 6u; j++) { u32 q = 6u * i + j; v = v << 1 | (b[q >> 3] >> (7u - (q & 7u)) & 1u); }
        out[i] = B64U[v];
    }
    out[QR_CHARS] = 0;
}
static int qr_code_now(struct st *st)              /* st->qr.code from the current selection */
{
    u32 f[N_QF];
    st->qr.code[0] = 0;
    if (!qr_fields(st, f)) return 0;
    qr_pack(f, st->qr.code);
    return 1;
}

/* ---- the encoder: QR version 5-L, byte mode, our own (ISO/IEC 18004; the layout follows Nayuki's qrcodegen) */
static u32 gf_mul(u32 a, u32 b)                      /* GF(2^8), x^8 + x^4 + x^3 + x^2 + 1 */
{
    u32 r = 0;
    while (b) { if (b & 1u) r ^= a; a <<= 1; if (a & 0x100u) a ^= 0x11Du; b >>= 1; }
    return r & 0xFFu;
}
static void qm_set(struct qr *q, u32 x, u32 y, u32 dark)   /* a function module (x = column, y = row) */
{
    q->mat[y * QR_N + x] = (u8)dark; q->fn[y * QR_N + x] = 1;
}
static void qr_format(struct qr *q, u32 mask)        /* ECC L (01) + mask, BCH(15,5), xor 0x5412 */
{
    u32 data = 1u << 3 | mask, rem = data;
    for (u32 i = 0; i < 10u; i++) rem = (rem << 1) ^ ((rem >> 9) * 0x537u);
    u32 b = (data << 10 | rem) ^ 0x5412u;
    for (u32 i = 0; i <= 5u; i++) qm_set(q, 8, i, b >> i & 1u);
    qm_set(q, 8, 7, b >> 6 & 1u); qm_set(q, 8, 8, b >> 7 & 1u); qm_set(q, 7, 8, b >> 8 & 1u);
    for (u32 i = 9; i < 15u; i++) qm_set(q, 14u - i, 8, b >> i & 1u);
    for (u32 i = 0; i < 8u; i++) qm_set(q, QR_N - 1u - i, 8, b >> i & 1u);
    for (u32 i = 8; i < 15u; i++) qm_set(q, 8, QR_N - 15u + i, b >> i & 1u);
    qm_set(q, 8, QR_N - 8u, 1);                       /* the dark module */
}
static u32 div3(u32 n) { return n * 0xAAABu >> 17; }   /* exact for n < 2^16 (here <= 36 x 36) */
static u32 mod3(u32 n) { return n - 3u * div3(n); }
static u32 mask_bit(u32 m, u32 x, u32 y)
{
    u32 xy = x * y;
    switch (m) {
    case 0: return (x + y) % 2u == 0u;
    case 1: return y % 2u == 0u;
    case 2: return mod3(x) == 0u;
    case 3: return mod3(x + y) == 0u;
    case 4: return (div3(x) + y / 2u) % 2u == 0u;
    case 5: return xy % 2u + mod3(xy) == 0u;
    case 6: return (xy % 2u + mod3(xy)) % 2u == 0u;
    default: return ((x + y) % 2u + mod3(xy)) % 2u == 0u;
    }
}
static void qr_apply_mask(struct qr *q, u32 m)
{
    for (u32 y = 0; y < QR_N; y++) for (u32 x = 0; x < QR_N; x++)
        if (!q->fn[y * QR_N + x] && mask_bit(m, x, y)) q->mat[y * QR_N + x] ^= 1u;
}
static u32 qr_penalty(const struct qr *q)            /* N1 runs, N2 blocks, N3 finder look-alikes, N4 balance */
{
    u32 p = 0, dark = 0;
    for (u32 pass = 0; pass < 2u; pass++)
        for (u32 a = 0; a < QR_N; a++) {
            u32 run = 0, prev = 2, h = 0;
            for (u32 b = 0; b < QR_N; b++) {
                u32 v = pass ? q->mat[b * QR_N + a] : q->mat[a * QR_N + b];
                if (v == prev) { run++; if (run == 5u) p += 3u; else if (run > 5u) p++; } else { run = 1; prev = v; }
                h = (h << 1 | v) & 0x7FFu;
                if (b >= 10u && (h == 0x5D0u || h == 0x05Du)) p += 40u;   /* 1011101 0000 / 0000 1011101 */
            }
        }
    for (u32 y = 0; y + 1u < QR_N; y++) for (u32 x = 0; x + 1u < QR_N; x++) {
        u32 c = q->mat[y * QR_N + x];
        if (c == q->mat[y * QR_N + x + 1u] && c == q->mat[(y + 1u) * QR_N + x] && c == q->mat[(y + 1u) * QR_N + x + 1u]) p += 3u;
    }
    for (u32 i = 0; i < QR_N * QR_N; i++) dark += q->mat[i];
    u32 tot = QR_N * QR_N, d = dark * 20u > tot * 10u ? dark * 20u - tot * 10u : tot * 10u - dark * 20u;
    return p + 10u * (udiv(d + tot - 1u, tot) - 1u);
}
static int qr_encode(struct qr *q)                   /* q->url -> q->mat (0 = dark, 0xFF = light, the Y8 convention) */
{
    u32 len = sq_len(q->url), nb = 0;
    if (len > QR_DATA_CW - 2u) return 1;              /* 4 + 8 + 8 len bits within 108 codewords */
    u8 *cw = q->cw;
    for (u32 i = 0; i < QR_DATA_CW + QR_EC_CW; i++) cw[i] = 0;
#define PUTB(v, w) for (u32 k_ = (w); k_--; nb++) if ((v) >> k_ & 1u) cw[nb >> 3] |= (u8)(0x80u >> (nb & 7u))
    PUTB(4u, 4u); PUTB(len, 8u);                      /* mode 0100 (byte), count (8 bits below V10) */
    for (u32 i = 0; i < len; i++) PUTB((u32)(u8)q->url[i], 8u);
#undef PUTB
    nb += 4u;                                         /* the terminator (room: len <= 106) */
    for (u32 i = (nb + 7u) >> 3, pad = 0xECu; i < QR_DATA_CW; i++, pad ^= 0xECu ^ 0x11u) cw[i] = (u8)pad;
    u32 root = 1;                                     /* the generator, degree 26, roots a^0..a^25 */
    for (u32 i = 0; i < QR_EC_CW; i++) q->gen[i] = 0;
    q->gen[QR_EC_CW - 1u] = 1;
    for (u32 i = 0; i < QR_EC_CW; i++) {
        for (u32 j = 0; j < QR_EC_CW; j++) {
            q->gen[j] = (u8)gf_mul(q->gen[j], root);
            if (j + 1u < QR_EC_CW) q->gen[j] ^= q->gen[j + 1u];
        }
        root = gf_mul(root, 2);
    }
    u8 *ec = cw + QR_DATA_CW;                         /* the remainder of data(x) x^26 / gen(x) */
    for (u32 i = 0; i < QR_DATA_CW; i++) {
        u32 f = cw[i] ^ ec[0];
        for (u32 j = 0; j + 1u < QR_EC_CW; j++) ec[j] = ec[j + 1u];
        ec[QR_EC_CW - 1u] = 0;
        for (u32 j = 0; j < QR_EC_CW; j++) ec[j] ^= (u8)gf_mul(q->gen[j], f);
    }
    for (u32 i = 0; i < QR_N * QR_N; i++) { q->mat[i] = 0; q->fn[i] = 0; }
    for (u32 i = 0; i < QR_N; i++) { qm_set(q, 6, i, i % 2u == 0u); qm_set(q, i, 6, i % 2u == 0u); }   /* timing */
    static const u8 FC[3][2] = {{3, 3}, {QR_N - 4u, 3}, {3, QR_N - 4u}};
    for (u32 k = 0; k < 3u; k++)                      /* finders + separators */
        for (int dy = -4; dy <= 4; dy++) for (int dx = -4; dx <= 4; dx++) {
            int x = FC[k][0] + dx, y = FC[k][1] + dy, d = sq_max(sq_abs(dx), sq_abs(dy));
            if (x >= 0 && y >= 0 && x < (int)QR_N && y < (int)QR_N) qm_set(q, (u32)x, (u32)y, d != 2 && d != 4);
        }
    for (int dy = -2; dy <= 2; dy++) for (int dx = -2; dx <= 2; dx++)   /* V5: one alignment pattern, at (30, 30) */
        qm_set(q, (u32)(30 + dx), (u32)(30 + dy), sq_max(sq_abs(dx), sq_abs(dy)) != 1);
    qr_format(q, 0);                                  /* reserves the format modules */
    u32 i = 0, total = 8u * (QR_DATA_CW + QR_EC_CW);
    for (int right = (int)QR_N - 1; right >= 1; right -= 2) {   /* the zigzag, two columns at a time, skipping column 6 */
        if (right == 6) right = 5;
        for (u32 v = 0; v < QR_N; v++) for (u32 j = 0; j < 2u; j++) {
            u32 x = (u32)right - j, up = (((u32)right + 1u) & 2u) == 0u, y = up ? QR_N - 1u - v : v;
            if (!q->fn[y * QR_N + x] && i < total) { q->mat[y * QR_N + x] = (u8)(cw[i >> 3] >> (7u - (i & 7u)) & 1u); i++; }
        }
    }
    u32 best = 0, bp = 0;
    for (u32 m = 0; m < 8u; m++) {                    /* the best of the 8 masks */
        qr_apply_mask(q, m); qr_format(q, m);
        u32 p = qr_penalty(q);
        if (m == 0u || p < bp) { bp = p; best = m; for (u32 k = 0; k < QR_N * QR_N; k++) q->best[k] = q->mat[k]; }
        qr_apply_mask(q, m);                          /* undo (xor) */
    }
    q->mask = best;
    for (u32 k = 0; k < QR_N * QR_N; k++) q->mat[k] = q->best[k] ? 0u : 0xFFu;
    q->n = QR_N;
    return 0;
}

/* ---- the scan decoder (v0.7.32test): our V5-L symbol, behind SIGMA's version-20-only decoder (notes/QR_SCAN_DESIGN.md) */
#include "qrdec.c"
_Static_assert(sizeof(struct qrd) <= QRD_BYTES, "struct qrd outgrew QRD_BYTES");

/* ---- the observer: FUN_c0528700 calls vt[0x0C](obs, desc, arg) on the draw thread, slot by slot, for its group */
static u32 qr_nop(void) { return 0; }
static int qr_buf(const struct qr *q, u32 base)
{
    for (u32 i = 0; i < q->nbuf; i++) if (q->buf[i] == base) return (int)i;
    return -1;
}
/* the square at (x0, y0): restore 0 = the code, 1 = the shadow back.  On the way the shadow learns what UIC drew there:
 * every pixel of a buffer that never held the code, and of one that did, every pixel that is not the code's (UIC
 * repainted it since) */
static void qr_square(struct qr *q, u32 base, int dirty, int restore)
{
    const u8 *old = dirty >= 0 ? q->prior[dirty] : q->live;
    u32 s = q->scale, side = q->side, off = QR_QZ * s, cm[QR_SHADOW > 256u ? 256u : 1u];
    for (u32 x = 0, m = 0, t = 0; x < side; x++) {     /* the module column of each x (0xFF = quiet zone) */
        cm[x] = x < off || x >= off + q->n * s ? 0xFFu : m;
        if (x >= off && ++t == s) { t = 0; m++; }
    }
    for (u32 y = 0, my = 0, t = 0; y < side; y++) {
        volatile u16 *p = (volatile u16 *)(uintptr_t)(base + (q->y0 + y) * 2u * OSD_W + 2u * q->x0);
        u16 *sh = &q->sh[y * side];
        u32 qrow = y >= off && y < off + q->n * s;
        for (u32 x = 0; x < side; x++) {
            u32 module = qrow && cm[x] != 0xFFu, at = my * q->n + cm[x];
            u32 dark = module && !q->live[at];
            u16 c = dark ? ARGB_BLACK : ARGB_WHITE, b = p[x];
            u16 was = module && !old[at] ? ARGB_BLACK : ARGB_WHITE;
            if (!q->have_sh || dirty < 0 || b != was) sh[x] = b;
            p[x] = restore ? sh[x] : c;
        }
        if (qrow && ++t == s) { t = 0; my++; }
    }
    q->have_sh = 1;
}
static void qr_req(const struct qr *q)               /* one more draw cycle of our group */
{
    if (!(q->force & 1u)) ((void (*)(u32, u32))F_DRAW_REQ)(DRAW_CTRL, q->group);
}
static int qr_uic_rendered(u32 base)
{
    /* C055F0F0() = C37B7048. C0561198 writes the current buffer's rect and mode
     * after UIC runs. Mode 1 updates state WITHOUT rendering or presenting; mode 0
     * with an empty rect also returns 0. QR must never promote either to a present:
     * the rest of that back buffer can still contain an older QS/menu page.
     * C05628B8 uses this same bounded ten-record lookup (we refuse missing records). */
    for (u32 r = UIC_RECS; r < UIC_RECS_END; r += 0x20u) {
        if (W(r + 4u) != base) continue;
        u32 mode = W(r + 0x18u);
        return (mode == 0u || mode == 2u) && (s32)W(r + 0x10u) > 0 && (s32)W(r + 0x14u) > 0;
    }
    return 0;
}
static u32 qr_draw(struct qobs *ob, u32 desc, u32 arg)
{
    struct st *st = ob->st;
    struct qr *q = &st->qr;
    (void)arg;
    if (!desc) return 0;
    u32 base = W(desc + 4u), dims = W(desc + 8u);
    if (!base || !dims || W(dims) != OSD_W || W(dims + 4u) != OSD_H || !q->side) return 0;   /* the 1024 x 682 main layer */
    if (!qr_uic_rendered(base)) return 0;              /* follow native UIC; no extra buffer flip for QR */
    int i = qr_buf(q, base);
    /* UicContentsIfBase v10/v11 publish/clear this owner via v16 (the UIC draw handler).
     * QS_CINE's main tiles have ids < 70; 70..77 are the container's temporary sub-QS.
     * Preparing text also happens at non-QS layout loads: it alone is NOT proof of visibility. */
    if (q->on && W(UIC_DRAW + 8u) == UIC_OWNER && W(UIC_OWNER) == UIC_OWNER_VT &&
        q->qs && W(q->qs + 0xBCu) < QS_SUB_ID0 && !busy()) {
        if (i < 0 && q->nbuf == 4u) return 0;          /* more buffers than a triple buffer: never lose one's shadow */
        qr_square(q, base, i, 0);
        if (i < 0) { i = (int)q->nbuf++; q->buf[i] = base; }
        for (u32 k = 0; k < QR_N * QR_N; k++) q->prior[i][k] = q->live[k];
        q->draws++;
        return 1;
    }
    if (i < 0) return 0;
    qr_square(q, base, i, 1);                         /* restore against the code this buffer actually held */
    q->buf[i] = q->buf[--q->nbuf];
    for (u32 k = 0; k < QR_N * QR_N; k++) q->prior[i][k] = q->prior[q->nbuf][k];
    q->restores++;
    if (q->nbuf) qr_req(q);                            /* the next buffer comes up next cycle */
    return 1;
}
static int qr_tile(struct st *st)                    /* our registered QR id, independent of the focused tile */
{
    const struct qsc_api *api = st->svc->find(st->svc, QSC_ID);
    if (!api || api->magic != QSC_API_MAGIC) return -1;
    int ui = api->ui_id(api, 0x31344C53u, "QR");
    if (ui < (int)QSC_UI_BASE || ui >= (int)(QSC_UI_BASE + QSC_MAX)) return -1;
    u32 id = (u32)ui + (QSC_INT_BASE - QSC_UI_BASE), set = ((u32 (*)(void))SETTINGS_FN)();
    for (u32 k = 0; k < 8u; k++) if (((u32 (*)(u32, u32))QS_GET_FN)(set, k) == id) return (int)k;
    return -1;
}
static int qr_attach(struct qr *q)                   /* into the group of the GUI's observer, after it */
{
    for (u32 g = 0; g < 4u; g++) {
        u32 layer = W(DRAW_LAYERS + 8u * g), gs = 3u;
        if (!layer || W(layer + 0x1Cu) != 1u) continue;   /* 16 bpp: the main ARGB4444 layer */
        for (u32 k = 0; k < 3u; k++) if (W(DRAW_CTRL + 12u * g + 4u * k) == UIC_DRAW) gs = k;
        if (gs == 3u) continue;
        if (W(DRAW_COUNT + 4u * g) >= 3u) return 5;
        q->group = g; q->gui_slot = gs;
        ((void (*)(u32, u32, u32))F_OBS_ADD)(DRAW_CTRL, g, (u32)(uintptr_t)&q->obs);
        q->slot = 3;
        for (u32 k = 0; k < 3u; k++) if (W(DRAW_CTRL + 12u * g + 4u * k) == (u32)(uintptr_t)&q->obs) q->slot = k;
        if (q->slot == 3u) return 6;
        if (q->slot < gs) { ((void (*)(u32, u32, u32))F_OBS_DEL)(DRAW_CTRL, g, (u32)(uintptr_t)&q->obs); return 6; }   /* would draw first */
        q->reg = 1;
        return 0;
    }
    return 4;                                         /* no GUI observer on a 16-bpp layer */
}
static void qr_detach(struct qr *q)                  /* a layout load: the screen is redrawn anyway */
{
    q->on = 0;
    if (q->reg && !(q->force & 1u)) ((void (*)(u32, u32, u32))F_OBS_DEL)(DRAW_CTRL, q->group, (u32)(uintptr_t)&q->obs);
    q->reg = 0; q->nbuf = 0; q->have_sh = 0;
}
/* noinline: inlined into sq_value, its PC-relative movw/movt of qr_nop / qr_draw spanned 31.8 KiB of .text, and the
 * assembler refuses a locally resolved pair past +-32 KiB ("Relocation Not In Range"; 2026-11-03 menu mutants) */
__attribute__((noinline)) static int qr_show(struct st *st)
{
    struct qr *q = &st->qr;
    q->why = 0;
    if (busy()) { q->on = 0; q->why = 1; return 0; }
    if (!qr_code_now(st)) { q->on = 0; q->why = 2; return 0; }
    int k = qr_tile(st);
    if (k < 0) { q->on = 0; q->why = 7; return 0; }
    u32 same = q->n == QR_N;
    for (u32 j = 0; same && j <= QR_CHARS; j++)
        if (q->url[sizeof QR_URL - 1u + j] != q->code[j]) same = 0;
    if (same && q->on && q->tile == (u32)k) return 1;                              /* moving focus alone does not encode again */
    if (q->nbuf && q->tile != (u32)k) { q->on = 0; q->why = 8; qr_req(q); return 0; }
    if (!same) {
        u32 n = put_s(q->url, 0, sizeof q->url, QR_URL);
        put_s(q->url, n, sizeof q->url, q->code);
        if (qr_encode(q)) { q->on = 0; q->why = 9; return 0; }
    }
    u32 s = udiv(QR_SIDE_MAX, QR_N + 2u * QR_QZ), side = (QR_N + 2u * QR_QZ) * s;
    if (!s || side * side > QR_SHADOW) { q->why = 3; return 0; }
    u32 tx = TILE_W * ((u32)k & 3u), ty = TILE_Y0 + TILE_DY * ((u32)k >> 2);
    u32 x0 = tx + ((TILE_W - side) >> 1), y0 = ty + ((TILE_H - side) >> 1);
    q->obs.vt = q->vt; q->obs.st = st;
    for (u32 i = 0; i < 8u; i++) q->vt[i] = (u32)(uintptr_t)qr_nop;   /* +0x10 attach, +0x14 detach, +0x1C 0 */
    q->vt[3] = (u32)(uintptr_t)qr_draw;
    if (!q->reg && !(q->force & 1u)) {
        int e = qr_attach(q);
        if (e) { q->why = (u32)e; return 0; }
    }
    /* Encode outside DrawController's mutex, then publish only the small matrix under the same mutex
     * FUN_c0528700 holds while invoking observers. Never block drawing on the QR encoder. */
    u32 lock[2];
    if (!(q->force & 1u)) ((void (*)(void *, u32))F_MUTEX_LOCK)(lock, DRAW_CTRL + 0x78u);
    for (u32 j = 0; j < QR_N * QR_N; j++) q->live[j] = q->mat[j];
    q->tile = (u32)k; q->scale = s; q->side = side; q->x0 = x0; q->y0 = y0;
    q->qs = ((u32 (*)(void))QS_STATE_FN)();
    if (!(q->force & 1u)) ((void (*)(void *, u32))F_MUTEX_UNLOCK)(lock, 2);
    q->on = 1;
    qr_req(q);
    q->shows++;
    return 1;
}
static void qr_hide(struct st *st)                   /* the observer stays until every buffer is restored */
{
    struct qr *q = &st->qr;
    if (!q->on) return;
    q->on = 0;
    if (q->reg) qr_req(q);
    q->hides++;
}

/* ---------------------------------------------------------------------------------------------- QR scan (v0.7.32test) */
/* AEL on the QR tile -> the container opens SIGMA's "Load from QR Code" page (Y5_ReadQR, QSC_F_GO, container API 7).
 * That page's own reader thread (QrReadTh) decodes the centre 512 x 512 of the display image; its decoder reads only
 * version 20 (FUN_c05cb960), so while the page is up its decoder object's vtable word points at our copy whose decode
 * slot runs the stock decoder first and qrdec.c second, writing our bytes back in the stock byte - i convention.
 * The page's handler (MenuQrCodeReadHandler) keeps its stock behaviour except: a result that is a SensorLab URL is
 * checked here (qr_unpack, then the restored selection must give back its input fields: qr_diff), shown as the
 * stock "ProcessingComplete" when it restores exactly (OK applies it and leaves through the stock back path) and as
 * the stock "Incompatible QR code." otherwise (the reason stays for the QR tile).  Every other result is stock.
 * RAM words only: the handler's vtable slots (claimed at entry) and the decoder object's vtable word (a run-time
 * object: armed at page entry only over the stock value, put back at page exit and at any leave() off the page). */
#define QRT_OBJ_VT    0xC3588D68u             /* QrReadTh (0xC3588D30) + 0x14 XC_QrCode, + 0x24: its vtable word */
#define QRT_VT_STOCK  0xC2DFE860u             /* XC_QrCode's vtable: {0, RTTI, dtor, decode, 1} */
#define QRT_VT_RTTI   0xC2DFE88Cu
#define QRT_VT_DTOR   0xC05C4640u
#define QRT_DECODE    0xC05C4E50u             /* XC_QrCode::v1 (obj, mode, params): FUN_c05c5d00 / FUN_c05c5dc8 */
#define QRT_DST_MAX   0x35Au                  /* the stock destination buffer (FUN_c05c49f0: 0x35A bytes) */
#define MQR_VT        0xC0CD35C4u             /* MenuQrCodeReadHandler's vtable (its v8/v62/v72/v73 words are unique) */
#define MQR_V12       (MQR_VT + 0x30u)        /* the Down key (0xC0476C70): read mode off, then Down -> R_FileSelect; not used */
#define MQR_V62       (MQR_VT + 0xF8u)        /* messages: 0xC0476DF0 */
#define MQR_V72       (MQR_VT + 0x120u)       /* page entry: 0xC0476B38 */
#define MQR_V73       (MQR_VT + 0x124u)       /* page exit: 0xC0476BB0 */
#define MQR_BASE_V62  0xC046C118u             /* MenuHandlerSubBase::v62 (the stock v62's last call) */
#define LV_EXE        0xC0370CF8u             /* the LV executor (FUN_c0371730's singleton 0xC351FE88) */
#define LV_READ_MODE  0xC03714A8u             /* (exe, on): QR read mode (vt + 0x84, rec-seq msg 0x1A) */
#define KEY_DEV       0xC02DBAF0u             /* XC_DeviceEventNotifierKeyDev singleton */
#define KEY_POST      0xC02DBBE8u             /* (dev, code): a key code into its queue -- the GPIO key path (FUN_c02dcd80) */
#define KEY_QS_ON     0x22u                   /* the device key codes, the shell's key table (.data 0xC2F205C0, seg1): */
#define KEY_QS_OFF    0x23u                   /*   QSON 0x22 / QSOFF 0x23 (OKON 0x1C = the GPIO table's OK: one code space) */
#define MQR_PHASE_END 3u                      /* handler +0x30: 1 reading, 2 stopping (the end message then replays a
                                                 key: Down -> R_FileSelect), 3 done (the end message does nothing) */
#define MQR_S_V62     0xC0476DF0u
#define MQR_S_V72     0xC0476B38u
#define MQR_S_V73     0xC0476BB0u
#define SCAN_SHOW_US  30000000u               /* the QR tile shows the result this long */
#ifndef QSC_F_GO                              /* qsc.h API 7 (QSContainer v0.3.7); the same values */
#define QSC_F_GO(t) ((((uint32_t)(t)) & 0xFu) << 8)
enum { QSC_GO_READQR = 1u };
#endif
_Static_assert(N_QF == 27u, "struct scan .f is N_QF");
static const char QF_NAME[N_QF][6] = {"VER", "DCW", "DCH", "RESW", "RESH", "FPS", "VMAX", "HMAX", "AD", "MH", "MV",
                                      "HBIN", "VBIN", "KEY", "KH", "KV", "KM", "RCP", "VISW", "VISH", "RS", "FMT",
                                      "RESC", "SCW", "SCH", "WINW", "WINH"};

/* 0.0.5test (Bei: old codes keep working): a code is accepted when its INPUT fields come back from the restored
 * selection; the rest is what the current core derives from them (VMAX of a common rate, HMAX, readout key, recipe
 * CUSTOM / RES CUSTOM flags, visible, RS, ISP window) and may differ from the code's.  Inputs: VER, DC, RES, FPS pick,
 * AD, MH, MV, HBIN, VBIN, kernels KH KV KM, FMT, sensor crop SCW SCH; VMAX x HMAX only as the rate of a pick 29 / 30. */
#define QF_INPUT (1u << 0 | 1u << 1 | 1u << 2 | 1u << 3 | 1u << 4 | 1u << 5 | 1u << 8 | 1u << 9 | 1u << 10 | 1u << 11 | \
                  1u << 12 | 1u << 14 | 1u << 15 | 1u << 16 | 1u << 21 | 1u << 23 | 1u << 24)
static u32 qr_diff(const u32 *f, const u32 *g, u32 ok, u32 mapped)
{
    u32 d = 0;
    for (u32 i = 0; i < N_QF; i++) if (!ok || (QF_INPUT >> i & 1u && g[i] != f[i])) d |= 1u << i;
    if (ok && mapped && f[5] >= 29u && g[5] >= 29u && g[5] <= 30u) d &= ~(1u << 5);   /* mapped: tuned <-> a maximum */
    return d;
}
/* a pick 29 / 30 the recipe no longer gives exactly (its VMAX range moved with the vertical margin): the same recipe
 * (inputs AD MH MV HBIN VBIN SCW SCH) at its maximum (30), or (29) at the fastest VMAX step not faster than the
 * code's rate -- ceil(VMAX x HMAX / hm), what any rate restores to (vmax_of) -- clamped to lo..VMAX_MAX; 1 = mapped */
static u32 qr_map_rate(struct st *st, const u32 *f, u32 ad)
{
    struct sel *s = &st->s;
    const struct cell *c = st->cur;
    if (!c || c->n <= 0) return 0;
    for (s32 i = 0; i < c->n; i++) {
        const struct rcp *q = &c->r[i];
        if (q->ad != ad || q->mh != f[9] || q->mv != f[10] || q->hb != f[11] || q->vb != f[12] || q->scw != f[23] ||
            q->sch != f[24] || !q->hm) continue;
        u64 v = f[5] == 30u ? q->lo : udiv64((u64)f[6] * f[7] + q->hm - 1u, q->hm, 0);
        v = v < q->lo ? q->lo : v > VMAX_MAX ? VMAX_MAX : v;
        s->fps_n = CD_CLK; s->fps_d = (u32)(q->hm * v);
        if (f[5] == 29u) { s->fc_n = s->fps_n; s->fc_d = s->fps_d; } else s->fc_d = 0;
        st->memo_ok = 0;
        return 1;
    }
    return 0;
}
/* the payload's fields -> the selection; 1 = its inputs come back (qr_diff), else the differing fields in *diff and
 * the selection is put back.  keep = 0: only the check. */
static int qr_restore(struct st *st, const u32 *f, u32 *diff, u32 keep)
{
    struct sel save = st->s;
    u32 dirty = st->dirty, g[N_QF], ad = f[8] == 0u ? 11u : f[8] == 1u ? 12u : 14u;
    struct sel *s = &st->s;
    *diff = 0;
    set_dc0(st, (int)f[1], (int)f[2]);
    set_res0(st, (int)f[3], (int)f[4]);
    s->rd[K_AD] = ad; s->rd[K_SCW] = f[23]; s->rd[K_SCH] = f[24]; s->rd[K_MH] = f[9]; s->rd[K_MV] = f[10];
    s->rd[K_HB] = f[11]; s->rd[K_VB] = f[12];
    s->rq = ad << 16 | f[9] << 12 | f[10] << 8 | f[11] << 4 | f[12]; s->rd_ok = 1;
    s->kh = f[14]; s->kv = f[15]; s->km = f[16];
    s->fine = 0;
    if (f[5] < N_STD) { struct rat r = rate_std(f[5]); s->fps_n = r.n; s->fps_d = r.d; s->fc_d = 0; }
    else {                                            /* a recipe maximum / a tuned rate: CLK / (HMAX x VMAX), exact */
        s->fps_n = CD_CLK; s->fps_d = f[7] * f[6];
        if (f[5] == 29u) { s->fc_n = s->fps_n; s->fc_d = s->fps_d; } else s->fc_d = 0;
    }
    st->memo_ok = 0;
    u32 ok = !f[21] && f[7] && f[6] && qr_fields(st, g), mapped = 0;
    *diff = qr_diff(f, g, ok, 0);
    if (*diff && !f[21] && f[7] && f[6] && f[5] >= N_STD && qr_map_rate(st, f, ad)) {
        mapped = 1;
        ok = qr_fields(st, g);
        *diff = qr_diff(f, g, ok, mapped);
    }
    if ((*diff && keep != 2u) || !keep) {               /* keep 2: sq_test only (set the inputs, whatever they give) */
        st->s = save; st->dirty = dirty; st->memo_ok = 0;
        cell_now(st);
    }
    return !*diff;
}
static struct st *scan_st(void) { struct st *st = sq_ctx(); return st && st->scan.vt_ok ? st : 0; }
static void scan_disarm(struct st *st)
{
    struct scan *sc = &st->scan;
    if (W(QRT_OBJ_VT) == (u32)(uintptr_t)sc->dvt) { W(QRT_OBJ_VT) = QRT_VT_STOCK; sc->disarms++; }
    sc->armed = 0;
}
static void scan_arm(struct st *st)
{
    struct scan *sc = &st->scan;
    struct qr *q = &st->qr;
    if (busy()) { sc->arm_refused++; return; }
    if (q->n != QR_N && !q->on && !q->nbuf) {          /* the function map comes from any encoded V5 code */
        u32 n = put_s(q->url, 0, sizeof q->url, QR_URL);
        for (u32 i = 0; i < QR_CHARS; i++) q->url[n + i] = 'A';
        q->url[n + QR_CHARS] = 0;
        if (qr_encode(q)) q->n = 0;
    }
    if (q->n != QR_N || W(QRT_OBJ_VT) != QRT_VT_STOCK) { sc->arm_refused++; return; }
    W(QRT_OBJ_VT) = (u32)(uintptr_t)sc->dvt;
    sc->armed = 1; sc->arms++;
}
/* QrReadTh, per frame: the stock decoder, then ours on the same Y8 when it found nothing.  p = the decoder input
 * (FUN_c05c49f0's locals): +0x10 length out, +0x14 destination, +0x18 width, +0x1C lines, +0x20 the Y8 image. */
USED int sl_qr_dec(u32 obj, u32 mode, u32 p)
{
    int r = ((int (*)(u32, u32, u32))QRT_DECODE)(obj, mode, p);
    struct st *st = scan_st();
    if (!st) return r;
    struct scan *sc = &st->scan;
    sc->decodes++;
    if (!r || busy() || st->qr.n != QR_N) return r;
    const u8 *img = (const u8 *)(uintptr_t)W(p + 0x20);
    u8 *dst = (u8 *)(uintptr_t)W(p + 0x14);
    u32 w = W(p + 0x18), h = W(p + 0x1Cu), len = 0;
    if (!img || !dst || w < 64u || h < 64u || w > 2048u || h > 2048u) return r;
    sc->ours++;
    if (qrd_decode((struct qrd *)(void *)sc->qd, img, w, h, w, st->qr.fn, sc->out, &len) != QD_OK || !len ||
        len > QRT_DST_MAX) return r;
    for (u32 i = 0; i < len; i++) dst[i] = sc->out[i];
    qrd_to_stock(dst, len);
    W(p + 0x10) = len;
    *(volatile u8 *)(uintptr_t)(p + 1u) = (u8)QR_VER;
    sc->ours_ok++;
    return 0;
}
/* a decoded result (stock convention) -> 0 not ours, 1 ours and it restores exactly, 2 ours, refused / invalid */
static u32 scan_result(struct st *st, const u8 *data, u32 len)
{
    struct scan *sc = &st->scan;
    sc->results++;
    if (!data || !qrd_sensorlab(data, len, 1, sc->code)) return 0;
    sc->sensorlab++;
    sc->last_at = ap_now_us();
    sc->unpack_rc = (u32)qr_unpack(sc->code, sc->f);
    if (sc->unpack_rc) { sc->invalid++; sc->last = 3; sc->diff = 0; return 2; }
    if (!qr_restore(st, sc->f, &sc->diff, 0)) { sc->refused++; sc->last = 2; return 2; }
    sc->accepted++;
    return 1;
}
/* v0.7.34test: leave the read page to the CINE QS (where AEL came from).  v0.7.33test used the handler's v12, which is
 * the Down key, not back: it stops reading, then the end message replays Down -> the page's KeyEvent 4239
 * "R_FileSelect" (read a QR from a playback image; live SS3154).  Now: read mode off, the handler marked done (+0x30 = 3:
 * the end message then replays nothing), our decoder word put back, then one QS press + release into the key device
 * queue -- the path a real QS key takes -> the page's CommonSystemKeyEvent QS (args 0x14): SYS_SubmenuOpen, app sync,
 * controlAppState "QS" -> the stock transition to QS_CINE. */
static void scan_to_qs(struct st *st, u32 h)
{
    ((void (*)(u32, u32))LV_READ_MODE)(((u32 (*)(void))LV_EXE)(), 0);
    W(h + 0x30u) = MQR_PHASE_END;
    scan_disarm(st);
    u32 dev = ((u32 (*)(void))KEY_DEV)();
    ((void (*)(u32, u32))KEY_POST)(dev, KEY_QS_ON);
    ((void (*)(u32, u32))KEY_POST)(dev, KEY_QS_OFF);
    st->scan.to_qs++;
}
/* v0.7.33test: the live run (v0.7.32test) showed the page's own path, not an OK key: its page data
 * (Y5_ReadQR object 4262 "Processing", 0xC2D19D7E..) answers the state "ProcessingComplete" with a 2 s timer and
 * controlAppState "Y5_ReadQR_SaveSettings", and the stock parser FUN_c052bd38 ACCEPTED our URL (name = URL[i] - i), so
 * a SensorLab code reached "Select Destination Mode".  Now a SensorLab result never reaches the stock result branch:
 *   restores exactly -> applied here (selection, dirty; committed at the page exit, sl_mqr_v73), the base class sees the message, and the page leaves
 *                       to the QS (scan_to_qs, v0.7.34test); no state, no save page;
 *   refused / invalid -> the stock handler with the result code 2 ("Incompatible QR code."): its no-parse branch.
 * Everything else is the stock handler, untouched. */
USED void sl_mqr_v62(u32 h, u32 msg)
{
    struct st *st = scan_st();
    u32 ours = 0, res = 0;
    if (st && !busy() && W(msg) == 2u && W(msg + 4u) == 0u && W(msg + 12u) == 0u) {
        res = W(msg + 20u);
        if (res && W(res) == 0u) ours = scan_result(st, (const u8 *)(uintptr_t)W(res + 0x14u), W(res + 0x18u));
    }
    if (ours == 1u) {
        struct scan *sc = &st->scan;
        if (qr_restore(st, sc->f, &sc->diff, 1)) { sc->applied++; sc->last = 1; st->dirty = 1; sc->pending = 1; }
        else { sc->refused++; sc->last = 2; }
        ((void (*)(u32, u32))MQR_BASE_V62)(h, msg);       /* what the stock v62 ends with */
        scan_to_qs(st, h);
        return;
    }
    if (ours == 2u) {                                   /* the stock "Incompatible" without the stock parse */
        W(res) = 2u;
        ((void (*)(u32, u32))MQR_S_V62)(h, msg);
        W(res) = 0u;
        return;
    }
    ((void (*)(u32, u32))MQR_S_V62)(h, msg);
}
USED void sl_mqr_v72(u32 h)
{
    ((void (*)(u32))MQR_S_V72)(h);
    struct st *st = scan_st();
    if (!st) return;
    st->scan.on_page = 1; st->scan.pending = 0;
    scan_arm(st);
}
/* 0.0.2test (Bei 11-08 live: the QS showed the scan, REC recorded the settings before it): the page's v72 opens a
 * settings session (FUN_c0057d38: MenuSettingStorage v5, every item then reads / writes a work copy) and its v73 ends
 * it with 0 (FUN_c0057da0 -> v6(0): the work copy dropped).  A commit inside the page set the native frame rate (the
 * carrier) into that copy, so it went back at exit and REC's picker key no longer named the live slot; the QS leave()
 * after it found nothing new to commit.  An applied scan now commits here, after the stock exit closed the session. */
USED void sl_mqr_v73(u32 h)
{
    struct st *st = scan_st();
    u32 owed = 0;
    if (st) { scan_disarm(st); st->scan.on_page = 0; owed = st->scan.pending; st->scan.pending = 0; }
    ((void (*)(u32))MQR_S_V73)(h);
    if (owed && !busy()) sq_push(st);
}
/* QR tile AEL (container API 7 GO): non-0 = open the read page */
USED int sq_qr_go(void *arg, int on)
{
    struct st *st = sq_ctx();
    (void)arg;
    if (!on || !st || !st->scan.vt_ok || busy()) return 0;
    const struct qsc_api *api = st->svc->find(st->svc, QSC_ID);
    if (!api || api->magic != QSC_API_MAGIC || api->version < 7u) return 0;
    st->scan.goes++;
    return 1;
}
/* sup_entry: the handler's three slots (v62 / v72 / v73), all or none (claimed: the loader puts them back if this sup goes) */
/* external (USED), like the wrappers above: clang emits external definitions in source order, so the PC-relative
 * addresses taken here stay near them (the +-32 KiB movw/movt cliff; static ones are emitted where first referenced) */
__attribute__((noinline)) USED void scan_install(struct st *st, const struct sl_svc *svc)
{
    static const u32 SITE[3] = {MQR_V62, MQR_V72, MQR_V73};
    static const u32 STOCK[3] = {MQR_S_V62, MQR_S_V72, MQR_S_V73};
    struct scan *sc = &st->scan;
    u32 ours[3] = {(u32)(uintptr_t)sl_mqr_v62, (u32)(uintptr_t)sl_mqr_v72, (u32)(uintptr_t)sl_mqr_v73};
    sc->dvt[0] = 0; sc->dvt[1] = QRT_VT_RTTI; sc->dvt[2] = QRT_VT_DTOR; sc->dvt[3] = (u32)(uintptr_t)sl_qr_dec; sc->dvt[4] = 1;
    st->f[F_QR].flags |= QSC_F_GO(QSC_GO_READQR);    /* AEL on the QR tile -> the read page (container API 7) */
    st->f[F_QR].fine = sq_qr_go;
    for (u32 i = 0; i < 3u; i++) if (W(SITE[i]) != STOCK[i]) { sc->vt_why = 1u + i; return; }
    for (u32 i = 0; i < 3u; i++) if (svc->claim(svc, SITE[i], 4u, &STOCK[i], SL_EXCL) != SL_OK) { sc->vt_why = 5u + i; return; }
    for (u32 i = 0; i < 3u; i++) W(SITE[i]) = ours[i];
    sc->vt_ok = 1;
}
/* the QR tile's small line: the last scan for SCAN_SHOW_US */
static const char *scan_small(struct st *st, char *d)
{
    struct scan *sc = &st->scan;
    if (!sc->last || ap_now_us() - sc->last_at > SCAN_SHOW_US) return 0;
    if (sc->last == 1u) return "QR applied";
    if (sc->last == 3u) return "QR invalid";
    u32 n = put_s(d, 0, TXT, "QR refused ");
    for (u32 i = 0; i < N_QF; i++) if (sc->diff >> i & 1u) { put_s(d, n, TXT, QF_NAME[i]); break; }
    return d;
}

/* ---------------------------------------------------------------------------------------------- the record */
#define REC_WORDS (2u + 30u + 4u * N_MEM + 1u)
static void rec_pack(const struct sel *s, u32 *r)
{
    u32 k = 0;
    r[k++] = REC_MAGIC; r[k++] = REC_VERSION;
    const u32 *w = &s->dcw;
    for (u32 i = 0; i < 13u; i++) r[k++] = w[i];      /* dcw .. ch */
    r[k++] = s->nmem;
    r[k++] = s->fps_n; r[k++] = s->fps_d; r[k++] = s->fc_n; r[k++] = s->fc_d;
    r[k++] = s->rq; r[k++] = s->rd_ok;
    for (u32 i = 0; i < N_PARAM; i++) r[k++] = s->rd[i];
    r[k++] = s->kh; r[k++] = s->kv; r[k++] = s->km;
    for (u32 i = 0; i < N_MEM; i++) for (u32 j = 0; j < 4u; j++) r[k++] = i < s->nmem ? s->mem[i][j] : 0;
    u32 h = 2166136261u;
    for (u32 i = 0; i < k; i++) { u32 v = r[i]; for (u32 b = 0; b < 4u; b++) { h = (h ^ (v & 0xFFu)) * 16777619u; v >>= 8; } }
    r[k] = h;
}
static int size_ok(u32 w, u32 h, u32 mw, u32 mh) { return !(w & 15u) && !(h & 1u) && w >= WMIN && h >= HMIN && w <= mw && h <= mh; }
static int rec_load(struct sel *out, const u32 *r)
{
    struct sel s;
    u32 chk[REC_WORDS];
    if (r[0] != REC_MAGIC || r[1] != REC_VERSION) return 0;
    u32 k = 2, *w = &s.dcw;
    for (u32 i = 0; i < 13u; i++) w[i] = r[k++];
    s.nmem = r[k++];
    s.fps_n = r[k++]; s.fps_d = r[k++]; s.fc_n = r[k++]; s.fc_d = r[k++]; s.fine = 0;
    s.rq = r[k++]; s.rd_ok = r[k++];
    for (u32 i = 0; i < N_PARAM; i++) s.rd[i] = r[k++];
    s.kh = r[k++]; s.kv = r[k++]; s.km = r[k++];
    if (s.nmem > N_MEM) return 0;
    for (u32 i = 0; i < N_MEM; i++) for (u32 j = 0; j < 4u; j++) s.mem[i][j] = r[k++];
    rec_pack(&s, chk);
    for (u32 i = 0; i < REC_WORDS; i++) if (chk[i] != r[i]) return 0;
    if (!size_ok(s.dcw, s.dch, WMAX, HMAX) || s.rat >= N_RAT || s.resk > N_KL || s.dclock > 1u || s.reslock > 1u ||
        s.custom > 1u || (s.custom && !size_ok(s.cw, s.ch, s.dcw, s.dch)) || !s.daw || !s.dah || !s.raw || !s.rah ||
        !s.fps_n || !s.fps_d || s.kh > 5u || s.kv > 5u || s.km > 1u)
        return 0;
    for (u32 i = 0; i < s.nmem; i++)
        if (!size_ok(s.mem[i][0], s.mem[i][1], WMAX, HMAX) || !size_ok(s.mem[i][2], s.mem[i][3], s.mem[i][0], s.mem[i][1]))
            return 0;
    /* v0.7.39test: CPU x2 (ISP HBIN hbin 2, option 13 of v0.7.38test) is gone (live 11-05: 103 MB/s of 457 needed;
     * validation/20261105-cpux2-archive).  A record saved with it selects ISP HBIN 1 -- its RWZM twin, the same AD /
     * sensor merge / record -- instead of whichever of 1 / 3 the nearest-recipe tie would pick. */
    if (s.rd[K_HB] == 2u) s.rd[K_HB] = 1u;
    if ((s.rq >> 4 & 0xFu) == 2u) s.rq = (s.rq & ~0xF0u) | 0x10u;
    *out = s;
    return 1;
}
/* Into this sup's own BIN, in place (open 7 = overwrite, no truncation), read back.  Never creates: the file must
 * still be this sup (its 48-byte header) -- sup-writeback-must-not-create.  Not while recording. */
static void rec_write(struct st *st)
{
    const struct sl_svc *svc = st->svc;
    const char *path = svc->self_path(svc, st->block);
    u32 fo = (u32)(uintptr_t)svc->uncached(svc, st->block + st->dma_off);
    u32 buf = fo + FO_BYTES, back = buf + 0x200u, ok = 0, got = 0, r[REC_WORDS];
    rec_pack(&st->s, r);
    if (!path || svc->file_is(svc, path, st->block, SL4_HEADER_LEN) != SL_OK) { st->write_why = 2; st->write_fails++; return; }
    for (u32 i = 0; i < REC_WORDS; i++) W(buf + 4u * i) = r[i];
    ((u32 (*)(u32, u32))F_CTOR)(fo, 1);
    if (((u32 (*)(u32, u32, u32))F_OPEN)(fo, (u32)(uintptr_t)path, 7)) {
        if (((u32 (*)(u32, u32, u32))F_SEEK)(fo, st->rec_off, 0) &&
            ((u32 (*)(u32, u32, u32))F_WRITE)(fo, buf, 4u * REC_WORDS) &&
            ((u32 (*)(u32, u32, u32))F_SEEK)(fo, st->rec_off, 0)) {
            for (u32 i = 0; i < REC_WORDS; i++) W(back + 4u * i) = 0xFFFFFFFFu;
            ((u32 (*)(u32, u32, u32, u32))F_READ)(fo, back, 4u * REC_WORDS, (u32)(uintptr_t)&got);
            ok = got == 4u * REC_WORDS;
            for (u32 i = 0; ok && i < REC_WORDS; i++) if (W(back + 4u * i) != r[i]) ok = 0;
        }
        ((u32 (*)(u32))F_CLOSE)(fo);
    }
    ((u32 (*)(u32, u32))F_DTOR)(fo, 2);
    if (ok) { st->writes++; st->dirty = 0; } else { st->write_why = 3; st->write_fails++; }
}
static void slm_idle(struct st *st);
static void slm_cancel_go(struct st *st);
static void boot_watch(struct st *st);
static void sq_leave_body(struct st *st, u32 *ph)
{
    u32 t = ap_now_us();
    slm_cancel_go(st);                                /* consumed request must not fire when menu is rebuilt */
    qr_detach(&st->qr);                               /* the blur came first; the new screen is drawn whole */
    if (!st->scan.on_page) scan_disarm(st);           /* v0.7.32test: never leave the reader on our decoder */
    boot_watch(st);                                   /* v0.7.35test: the boot apply's variable (UI thread, once) */
    if (busy()) { slm_idle(st); return; }
    if (!st->lt[7]) st->lt[10] = ap_now_us();
    sq_push(st);                                      /* v0.5.0test: leave() flushes (and the boot restore lands here) */
    ph[0] = ap_now_us() - t; t += ph[0];
    if (!st->lt[7]) st->lt[11] = ap_now_us();
    ap_idle(st->ap_mem);                              /* UI thread: publish HUD tiles queued by the apply step */
    ph[1] = ap_now_us() - t; t += ph[1];
    slm_idle(st);                                     /* private menu models and confirmed-selection bridge */
    ph[2] = ap_now_us() - t; t += ph[2];
    if (st->dirty) rec_write(st);
    ph[3] = ap_now_us() - t;
}
static void sq_leave(void *arg)                       /* the container's leave(): every layout load */
{
    struct st *st = (struct st *)arg;
    u32 t0 = ap_now_us(), ph[4] = {0, 0, 0, 0};
    st->leaves++;
    sq_leave_body(st, ph);
    u32 d = ap_now_us() - t0;
    if (!st->lt[7]) { st->lt[0] = d; for (u32 i = 0; i < 4u; i++) st->lt[1u + i] = ph[i]; st->lt[8] = t0; st->lt[9] = t0 + d; }
    if (d > st->lt[5]) st->lt[5] = d;
    st->lt[6] = d; st->lt[7]++;
}

/* ---------------------------------------------------------------------------------------------- callbacks */
static u32 who(void *arg, u32 *item)
{
    struct st *st = sq_ctx();
    u32 a = (u32)((u8 *)arg - &st->arg[0][0]);
    *item = a & 7u;
    return a >> 3;
}
static char *vbuf(u32 f, u32 j) { return sq_ctx()->v[f][j]; }
static char *sbuf(u32 f, u32 j) { return sq_ctx()->sm[f][j]; }
static u32 mm_put(char *d, u32 n, u32 px)            /* mm(px) = (px * (35.9 / 6048)).toFixed(1) */
{
    dbl k = dratio(359, 10), pxmm = dratio(k.m, 6048);
    pxmm.e += k.e;
    return put_fix(d, n, TXT, (u64)js_fixed_d(dmul(pxmm, px), 1), 1);
}
/* Labels only: preserve exact dimensions, saved lock ratio and crop calculations.
 * A 0.25% relative tolerance covers even/16-pixel sensor alignment (6048x4040 -> 3:2).
 * Other aspects use two decimal places followed by X, e.g. cinema 1.85X / 2.39X. */
static void sq_ratio_text(char *d, u32 w, u32 h)
{
    static const u8 common[][2] = {{1,1},{5,4},{4,3},{3,2},{16,9},{2,1},
                                    {4,5},{3,4},{2,3},{9,16},{1,2}};
    if (!w || !h) { put_s(d, 0, TXT, "-"); return; }
    for (u32 i = 0; i < sizeof common / sizeof common[0]; i++) {
        u64 a = (u64)w * common[i][1], b = (u64)h * common[i][0];
        u64 diff = a > b ? a - b : b - a;
        if (400u * diff <= b) {
            u32 n = put_u(d, 0, TXT, common[i][0]); n = put_s(d, n, TXT, ":");
            put_u(d, n, TXT, common[i][1]); return;
        }
    }
    u32 n = put_fix(d, 0, TXT, (u64)js_fixed_d(dratio(w, h), 2), 2);
    put_s(d, n, TXT, "X");
}
static void dc_size(struct st *st, u32 f, u32 *w, u32 *h) { if (f == F_DC) { *w = st->s.dcw; *h = st->s.dch; } else res_now(st, w, h); }

static const char *sq_value(void *arg)
{
    struct st *st = sq_ctx();
    u32 qs = ((u32 (*)(void))QS_STATE_FN)();
    if (!qs || W(qs + 0xBCu) >= QS_SUB_ID0) qr_hide(st);
    u32 j, f = who(arg, &j), w, h;
    char *d = vbuf(f, j);
    d[0] = 0;
    cell_now(st);
    const struct rcp *c = cur_recipe(st);
    if (f == F_DC || f == F_RES) {
        if (j == 0u && f == F_DC) {
            int p = dc_preset(st->s.dcw, st->s.dch);
            put_s(d, 0, TXT, p >= 0 ? DCN[p] : "CUSTOM");
        } else if (j == 0u) {
            res_now(st, &w, &h);
            int i = res_hit(st, w, h);
            put_s(d, 0, TXT, i >= 0 ? st->list[i].lab : "CUSTOM");
        } else if (j == 1u || j == 2u) {
            /* v0.7.36test (Bei 11-05): RES WIDTH / HEIGHT show the dialed RES (its nominal visible size, - 16 x 10), never
             * the recipe's: a 2 % tolerance recipe made the value look stuck; what it records goes in the small line */
            if (f == F_DC) { w = st->s.dcw; h = st->s.dch; } else { res_now(st, &w, &h); w -= 16u; h -= 10u; }
            put_u(d, 0, TXT, j == 1u ? w : h);
        } else {
            dc_size(st, f, &w, &h);
            sq_ratio_text(d, w, h);
        }
    } else if (f == F_FPS) {
        if (!has_q(st)) return "\xE2\x80\x94";
        struct rat fr = {st->s.fps_n, st->s.fps_d};
        int k = fps_sel(st);
        if (j == 1u || st->s.fine || k < 0) f3_put(d, 0, TXT, fr); else fmt_rate(d, TXT, &st->fl_e[k]);   /* FINE.v / FPS.v */
    } else if (f == F_FORMAT) {
        put_s(d, 0, TXT, "DNG");
    } else if (f == F_MBPS) {
        struct mbps m; mbps_of(st, &m);
        if (!m.ok) return "\xE2\x80\x94";
        mb_put(d, 0, m.u_m);
    } else if (f == F_QR) {
        if (qs && W(qs + 0xBCu) < QS_SUB_ID0) qr_show(st);
        put_s(d, 0, TXT, "QR");
    } else if (j == 0u) {
        if (!c) return "\xE2\x80\x94";
        if (!is_preset(c)) put_s(d, 0, TXT, "CUSTOM");
        else { u32 n = put_u(d, 0, TXT, c->ad); n = put_s(d, n, TXT, "b "); n = put_u(d, n, TXT, c->mh);
               n = put_s(d, n, TXT, "x"); put_u(d, n, TXT, c->mv); }
    } else {
        if (!c) return "\xE2\x80\x94";
        u32 key = j - 1u;
        if (key == K_HB || key == K_VB) {             /* v0.2.2test: "3[1,2,1]" (the container draws "[..]" thin) or "1" */
            u32 b = key == K_HB ? c->hb : c->vb, kk = key == K_HB ? st->s.kh : st->s.kv, n;
            if (b == 3u) { n = put_s(d, 0, TXT, "3["); n = put_s(d, n, TXT, KERN[kk]); put_s(d, n, TXT, "]"); }
            else put_s(d, 0, TXT, "1");
            return d;
        }
        u32 n = put_s(d, 0, TXT, key == K_SCW || key == K_SCH ? "S " : "");   /* v0.2.2test: "S 6064" (bold S, digits) */
        n = put_u(d, n, TXT, pval(c, key));
        if (key == K_AD) put_s(d, n, TXT, "bit");
    }
    return d;
}

static const char *sq_small(void *arg, uint32_t *flags)
{
    struct st *st = sq_ctx();
    u32 j, f = who(arg, &j), n = 0;
    char *d = sbuf(f, j);
    d[0] = 0;
    cell_now(st);
    const struct rcp *c = cur_recipe(st);
    if (f == F_DC && j == 0u) {                       /* "35.9 × 20.2 mm" */
        n = mm_put(d, 0, st->s.dcw); n = put_s(d, n, TXT, " \xC3\x97 "); n = mm_put(d, n, st->s.dch);
        put_s(d, n, TXT, " mm");
    } else if (f == F_RES && j == 0u) {               /* visible size · HxV, yellow when the recipe is short */
        struct eff e;
        eff_now(st, &e);                              /* v0.7.38test: the effective recipe's hint (single source) */
        n = put_u(d, 0, TXT, e.vw); n = put_s(d, n, TXT, "\xC3\x97"); n = put_u(d, n, TXT, e.vh);
        if (e.hint[0]) { n = put_s(d, n, TXT, " \xC2\xB7 "); put_s(d, n, TXT, e.hint); }
        if (e.shr) *flags |= QSC_T_APPROX;
    } else if ((f == F_DC || f == F_RES) && (j == 1u || j == 2u)) {
        if (f == F_DC) { n = mm_put(d, 0, j == 1u ? st->s.dcw : st->s.dch); put_s(d, n, TXT, " mm"); }
        else {                                        /* v0.7.36test: what is recorded, when a tolerance recipe applies */
            struct eff e;
            eff_now(st, &e);                          /* v0.7.38test: the same hint as the RES tile (single source) */
            n = 0;
            if (e.w != e.rw || e.h != e.rh) {
                n = put_s(d, 0, TXT, "\xE2\x86\x92"); n = put_u(d, n, TXT, e.w); n = put_s(d, n, TXT, "\xC3\x97"); n = put_u(d, n, TXT, e.h);
            }
            if (e.hint[0]) { if (n) n = put_s(d, n, TXT, " \xC2\xB7 "); n = put_s(d, n, TXT, e.hint); }
            else if (!n) d[0] = 0;
            if (e.c && rw_on(e.c)) {                  /* 0.0.6test: this axis' RWZM ratio, when it fits the small line */
                char x[16];
                u32 k = put_s(x, 0, sizeof x, " /");
                k = put_fix(x, k, sizeof x, (u64)js_fixed_d(dratio(j == 1u ? e.c->zh : e.c->zv, 1024u), 2), 2);
                if (n + k <= QSC_VALUE - 1u) put_s(d, n, TXT, x);
            }
        }
    } else if (f == F_DC || f == F_RES) {             /* Semantic fallback: older QS ignores SMALL_* icons.
                                                     * A supporting container replaces this with its image. */
        return (f == F_DC ? st->s.dclock : st->s.reslock) ? "LOCK" : "";
    } else if (f == F_FPS) {                          /* "· 32 recipes" (· at a recipe's maximum) */
        if (!has_q(st)) return "no recipe";
        struct rat fr = {st->s.fps_n, st->s.fps_d};
        u32 a = 0;
        const struct cell *cl = st->cur;
        for (int i = 0; i < cl->n; i++) if (is_preset(&cl->r[i]) && ge_tol(rate_q(&cl->r[i]), fr)) a++;
        /* v0.2.1test: U+00B7 (the page's "•" U+2022 is not in the camera's small-line font: it drew "?" in live
         * run 4; "·" is, the RES line's separator) */
        if (qmark(st, fr)) n = put_s(d, 0, TXT, "\xC2\xB7 ");
        n = put_u(d, n, TXT, a);
        put_s(d, n, TXT, " recipes");
    } else if (f == F_FORMAT) {
        if (c) { u32 b = out_bits(st, c); put_s(d, put_u(d, 0, TXT, b), TXT, "bit"); }   /* the recorded bits (11 / scaled
                                                                                         14 AD: 12; stock 8 / 10: that) */
    } else if (f == F_MBPS) {                         /* "LL ~94", yellow past 75 % of the medium (no green / red glyphs yet) */
        struct mbps m; mbps_of(st, &m);
        if (!m.ok) return 0;
        if (m.ll_no) put_s(d, 0, TXT, "LL \xE2\x80\x94");       /* v0.4.0test: "LL —", the lossless sup refuses it */
        else { n = put_s(d, 0, TXT, "LL ~"); mb_put(d, n, m.ll_m); if (m.dl > 750u) *flags |= QSC_T_APPROX; }
    } else if (f == F_QR) {                           /* the code's first 10 chars + ".." (37 do not fit the line) */
        const char *scan = scan_small(st, d);          /* v0.7.32test: the last scan, for a while */
        if (scan) return scan;
        if (!qr_code_now(st)) return "no recipe";
        n = 0;
        for (u32 i = 0; i < 10u; i++) d[n++] = st->qr.code[i];
        put_s(d, n, TXT, "..");
    } else if (j == 0u) {                             /* RECIPE */
        if (!c) return "no recipe";
        struct eff e;
        eff_now(st, &e);
        if (!is_preset(c)) {
            n = put_u(d, 0, TXT, c->ad); n = put_s(d, n, TXT, "b "); n = put_u(d, n, TXT, c->mh); n = put_s(d, n, TXT, "x");
            n = put_u(d, n, TXT, c->mv); n = put_s(d, n, TXT, " ISP "); n = put_u(d, n, TXT, c->hb); n = put_s(d, n, TXT, "x");
            n = put_u(d, n, TXT, c->vb); n = put_s(d, n, TXT, " \xC2\xB7 ");
        }
        n = put_s(d, n, TXT, "RS ");
        /* v0.7.38test (Bei live 11-05): RS one decimal, no visible-size suffix (the RES tile / sub-items show what is
         * recorded); a short recipe still turns the line yellow */
        n = put_fix(d, n, TXT, (u64)js_fixed_d(dratio(c->rs_us, 1000), 1), 1);
        put_s(d, n, TXT, " ms");
        if (e.shr) *flags |= QSC_T_APPROX;
    } else if (c) {
        u32 key = j - 1u;
        if (key == K_SCW || key == K_SCH) {           /* v0.2.2test: the ISP crop in sensor pixels, "I 3396" */
            n = put_s(d, 0, TXT, "I "); u32 iw = (u32)c->win_w * c->mh, ih = (u32)c->win_h * c->mv;      /* never past S: an odd merged row count reads as the next even one (live5) */
              put_u(d, n, TXT, key == K_SCW ? (iw < c->scw ? iw : c->scw) : (ih < c->sch ? ih : c->sch)); }
        else if (key == K_HB || key == K_VB) {
            u32 b = key == K_HB ? c->hb : c->vb, kk = key == K_HB ? st->s.kh : st->s.kv;
            (void)kk;                                 /* v0.2.2test: the kernel is in the big text */
            if (b == 3u) { n = put_s(d, 0, TXT, MODE[st->s.km]); n = put_s(d, n, TXT, " \xC2\xB7 "); }
            rwzm(d, n, key == K_HB ? c->zh : c->zv);
        }
    }
    return d[0] ? d : 0;
}

/* the footer: at most N_LIST options, a window of 15 around the current one (the container shows 7 of them) */
static u32 window(u32 n, int cur, u32 *lo)
{
    *lo = 0;
    if (n <= N_LIST) return n;
    int a = cur - 7;
    if (a < 0) a = 0;
    if (a > (int)n - 15) a = (int)n - 15;
    *lo = (u32)a;
    return 15;
}
static const u8 OPTS_B[13] = {1, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3};   /* ISP bin options: 1, then 3 x kernel x mode */
static int isp_cur(struct st *st, u32 key)
{
    const struct rcp *c = cur_recipe(st);
    if (!c) return -1;
    u32 b = key == K_HB ? c->hb : c->vb;
    return b == 3u ? 1 + (int)st->s.km * 6 + (int)(key == K_HB ? st->s.kh : st->s.kv) : 0;
}

static u32 sq_footer(void *arg, struct qsc_foot *o)
{
    struct st *st = sq_ctx();
    u32 j, f = who(arg, &j), w, h, n = 0, lo = 0;
    int cur = -1;
    cell_now(st);
    const struct rcp *c = cur_recipe(st);
    if (f == F_DC && j == 0u) {
        for (u32 i = 0; i < N_DC; i++) {
            u32 k = put_u(st->fs[i], 0, FT, DCW[i]); k = put_s(st->fs[i], k, FT, "\xC3\x97"); put_u(st->fs[i], k, FT, DCH[i]);
            o->label[i] = DCN[i]; o->small[i] = st->fs[i];
        }
        n = N_DC; cur = dc_preset(st->s.dcw, st->s.dch);
    } else if (f == F_RES && j == 0u) {
        res_now(st, &w, &h);
        cur = res_hit(st, w, h);
        n = window(st->n_list, cur, &lo);
        for (u32 i = 0; i < n; i++) o->label[i] = st->list[lo + i].lab;   /* v0.2.1test: label only, the ratio stays on the tile */
    } else if ((f == F_DC || f == F_RES) && (j == 1u || j == 2u)) {
        o->label[0] = sq_value(arg); o->n = 1; o->spin = 1;
        if (f == F_DC && j == 1u) o->mark = native_w(st->s.dcw);   /* a native readout width: dotted underline */
        return 1;
    } else if (f == F_DC || f == F_RES) {
        o->label[0] = "LOCK"; o->label[1] = "FREE";
        n = 2; cur = (f == F_DC ? st->s.dclock : st->s.reslock) ? 0 : 1;
    } else if (f == F_FPS) {
        if (!has_q(st)) return 0;
        struct rat fr = {st->s.fps_n, st->s.fps_d};
        if (j == 1u || st->s.fine) {                  /* FINE / fine mode: the K-style spinner, marked at a maximum */
            f3_put(st->fl[0], 0, FT, fr);
            o->label[0] = st->fl[0]; o->n = 1; o->spin = 1; o->mark = (u32)qmark(st, fr);
            return 1;
        }
        cur = fps_sel(st);
        n = window(st->n_fl, cur, &lo);
        for (u32 i = 0; i < n; i++) {
            const struct fent *e = &st->fl_e[lo + i];
            fmt_rate(st->fl[i], FT, e);
            o->label[i] = st->fl[i];
            o->mark |= (u32)e->mark << i; o->custom |= (u32)e->custom << i; o->grey |= (u32)e->na << i;
        }
    } else if (f == F_FORMAT) {                      /* 0.0.4test: 8 / 10 / RAW bit (the recipe's own 12 / 14), MOV grey */
        put_s(st->fl[0], put_u(st->fl[0], 0, FT, c ? rec_bits(c) : 12u), FT, "bit");
        o->label[0] = "8bit"; o->label[1] = "10bit"; o->label[2] = st->fl[0]; o->label[3] = "MOV"; o->grey = 8u;
        n = 4; cur = (int)depth_idx(depth_now(st));
    } else if (f == F_MBPS) {                         /* the medium + duties, and the raw reads (Bei verifies the SSD half) */
        struct mbps m; mbps_of(st, &m);
        u32 r, cl, k; const char *nm;
        media_rc(st, &r, &cl, &nm);
        o->label[0] = nm; o->small[0] = 0;
        if (m.ok) { k = put_u(st->fs[0], 0, FT, (u32)D(m.du + 5u, 10u)); k = put_s(st->fs[0], k, FT, "%/");   /* "91%/42%" */
                    if (m.ll_no) put_s(st->fs[0], k, FT, "\xE2\x80\x94");
                    else { k = put_u(st->fs[0], k, FT, (u32)D(m.dl + 5u, 10u)); put_s(st->fs[0], k, FT, "%"); }
                    o->small[0] = st->fs[0]; }
        k = put_s(st->fl[1], 0, FT, "A"); k = put_u(st->fl[1], k, FT, st->md.ms_a); k = put_s(st->fl[1], k, FT, " B");
        put_u(st->fl[1], k, FT, st->md.ms_b);
        k = put_s(st->fs[1], 0, FT, "R"); k = put_u(st->fs[1], k, FT, st->md.ssd_ready); k = put_s(st->fs[1], k, FT, " M");
        k = put_u(st->fs[1], k, FT, st->md.ssd_mnt); k = put_u(st->fs[1], k, FT, st->md.sd_mnt); k = put_s(st->fs[1], k, FT, " S");
        put_u(st->fs[1], k, FT, st->md.sd_mode);
        o->label[1] = st->fl[1]; o->small[1] = st->fs[1];
        n = 2; cur = 0;
    } else if (f == F_QR) {
        return 0;                                     /* no options */
    } else if (j == 0u) {                             /* RECIPE: the presets, RS, H<rows> when short */
        res_now(st, &w, &h);
        u32 k = 0;
        const struct cell *cl = st->cur;
        int csel = -1;
        u32 np = 0;
        for (int i = 0; i < cl->n; i++) if (is_preset(&cl->r[i])) { if (c && rq_of(&cl->r[i]) == rq_of(c)) csel = (int)np; np++; }
        cur = csel;
        n = window(np, cur, &lo);
        for (int i = 0; i < cl->n && k < lo + n; i++) {
            const struct rcp *q = &cl->r[i];
            if (!is_preset(q)) continue;
            if (k >= lo) {
                u32 t = k - lo, m;
                m = put_u(st->fl[t], 0, FT, q->ad); m = put_s(st->fl[t], m, FT, "b "); m = put_u(st->fl[t], m, FT, q->mh);
                m = put_s(st->fl[t], m, FT, "x"); put_u(st->fl[t], m, FT, q->mv);
                m = put_fix(st->fs[t], 0, FT, (u64)js_fixed_d(dratio(q->rs_us, 1000), 1), 1);   /* v0.2.2test: "7.4ms", */
                m = put_s(st->fs[t], m, FT, "ms");                                                 /* the footer font is ~12 px */
                if (q->vis_h + 10u < h) { m = put_s(st->fs[t], m, FT, " H"); put_u(st->fs[t], m, FT, q->vis_h); o->approx |= 1u << t; }
                o->label[t] = st->fl[t]; o->small[t] = st->fs[t];
                if (!usable(st, q)) o->grey |= 1u << t;
            }
            k++;
        }
    } else {                                          /* the recipe parameters */
        u32 key = j - 1u;
        if (!c) return 0;
        if (key == K_HB || key == K_VB) {
            cur = isp_cur(st, key);
            for (u32 i = 0; i < 13u; i++) {
                u32 b = OPTS_B[i], ok = (u32)ok_v(st, key, b), m = 0;
                st->fs[i][0] = 0;
                if (i) { u32 md = i > 6u, ki = i - 1u - 6u * md;       /* v0.2.2test: "3[1,2,1]" / "SOFT" */
                         m = put_s(st->fl[i], 0, FT, "3["); m = put_s(st->fl[i], m, FT, KERN[ki]); put_s(st->fl[i], m, FT, "]");
                         m = put_s(st->fs[i], 0, FT, MODE[md]); }
                else put_s(st->fl[i], 0, FT, "1");
                if (!ok) { char wn[FT]; why_not(st, wn, key, b); if (i) m = put_s(st->fs[i], m, FT, " "); put_s(st->fs[i], m, FT, wn);
                           o->grey |= 1u << i; }
                o->label[i] = st->fl[i]; o->small[i] = st->fs[i][0] ? st->fs[i] : 0;
            }
            n = 13;
        } else {
            u32 V[MAXR];
            u32 nv = vals(st, key, V);
            for (u32 i = 0; i < nv; i++) if (V[i] == pval(c, key)) cur = (int)i;
            n = window(nv, cur, &lo);
            for (u32 i = 0; i < n; i++) {
                u32 v = V[lo + i], m = put_u(st->fl[i], 0, FT, v);
                if (key == K_AD) put_s(st->fl[i], m, FT, "bit");
                o->label[i] = st->fl[i];
                o->small[i] = 0;
                if (!ok_v(st, key, v)) { why_not(st, st->fs[i], key, v); o->small[i] = st->fs[i]; o->grey |= 1u << i; }
            }
        }
    }
    o->n = n;
    o->cur = cur >= 0 ? (u32)cur - lo : n;
    return n;
}

static int sq_lock_icon(void *arg)
{
    struct st *st = sq_ctx();
    u32 j, f = who(arg, &j);
    (void)j;
    return (f == F_DC ? st->s.dclock : st->s.reslock) ? QSC_LOCK_SMALL_SHUT : QSC_LOCK_SMALL_OPEN;
}

/* the page's p.w / p.h vs asp within 0.002, as the doubles compare (subtraction exact, Sterbenz) */
static int asp_near(u32 pw, u32 ph, u32 aw, u32 ah)
{
    dbl a = dratio(pw, ph), b = dratio(aw, ah), c = dratio(2, 1000);
    if (a.e - b.e > 1 || b.e - a.e > 1) return 0;     /* not within a factor of 2: far apart */
    int e1 = a.e < b.e ? a.e : b.e;
    u64 x = a.m << (a.e - e1), y = b.m << (b.e - e1), d = x > y ? x - y : y - x;
    if (!d) return 1;
    int sh = e1 - c.e;                                /* d * 2^e1 < c.m * 2^c.e */
    if (sh >= 0) return sh < 63 && d < ((u64)1 << (63 - sh)) ? (d << sh) < c.m : 0;
    return d < (c.m << -sh);
}

static int sq_adjust_qs(void *arg, int step);
static int sq_adjust(void *arg, int step)             /* v0.5.0test: every dial step is a change event -> apply */
{
    int r = sq_adjust_qs(arg, step);
    struct st *st = sq_ctx();
    if (!busy()) sq_push(st);
    return r;
}
static int sq_adjust_qs(void *arg, int step)
{
    struct st *st = sq_ctx();
    struct sel *s = &st->s;
    u32 j, f = who(arg, &j), w, h;
    int d = step > 0 ? 1 : -1, big = step > 1 || step < -1;
    cell_now(st);
    if ((f == F_DC || f == F_RES) && j == 0u && f == F_DC) {   /* DC.adj: the next preset, stops at the ends */
        int k = dc_preset(s->dcw, s->dch);
        if (k < 0) { k = 0; for (u32 i = 1; i < N_DC; i++) if (sq_abs(DCW[i] - (int)s->dcw) < sq_abs(DCW[k] - (int)s->dcw)) k = (int)i; }
        else k = sq_max(0, sq_min((int)N_DC - 1, k + d));
        set_dc(st, DCW[k], DCH[k]);
        s->daw = DCW[k]; s->dah = DCH[k];
    } else if (f == F_RES && j == 0u) {               /* RES.adj */
        res_now(st, &w, &h);
        int k = res_hit(st, w, h), L = (int)st->n_list;
        if (k < 0) {
            k = -1;
            for (int i = 0; i < L && k < 0; i++) if (st->list[i].w > w) k = i;
            k = k < 0 ? L - 1 : d > 0 ? k : k - 1;
        } else k += d;
        k = sq_max(0, sq_min(L - 1, k));
        u32 nw = st->list[k].w, nh = st->list[k].h;
        set_res(st, (int)nw, (int)nh);
        s->raw = nw; s->rah = nh;
    } else if ((f == F_DC || f == F_RES) && (j == 1u || j == 2u)) {   /* dimTile.adj */
        u32 isdc = f == F_DC, lock = isdc ? s->dclock : s->reslock, aw = isdc ? s->daw : s->raw, ah = isdc ? s->dah : s->rah;
        if (isdc) { w = s->dcw; h = s->dch; } else res_now(st, &w, &h);
        int Wl = isdc ? WMAX : (int)s->dcw, Hl = isdc ? HMAX : (int)s->dch, nw = (int)w, nh = (int)h;
        dbl asp = dratio(aw, ah);
        if (j == 1u) {
            nw += d * 16 * (big ? 10 : 1);
            if (isdc && big) nw = native_w_stop((int)w, nw);
            if (lock) nh = round_to(ddiv_int((u64)(nw > 0 ? nw : 0), asp), 2);
        }
        else { nh += d * 2 * (big ? 10 : 1); if (lock) nw = round_to(dmul(asp, (u64)(nh > 0 ? nh : 0)), 16); }
        if (nw > Wl || nh > Hl) {
            if (lock) return 0;
            nw = sq_min(nw, Wl); nh = sq_min(nh, Hl);
        }
        if (nw < WMIN || nh < HMIN) return 0;
        int pw = -1, ph = -1;
        if (isdc) {
            for (u32 i = 0; i < N_DC && pw < 0; i++)
                if (sq_abs(DCW[i] - nw) <= 16 && sq_abs(DCH[i] - nh) <= 2 && (!lock || asp_near(DCW[i], DCH[i], aw, ah))) { pw = DCW[i]; ph = DCH[i]; }
        } else {
            refresh_list(st);
            for (u32 i = 0; i < st->n_list && pw < 0; i++)
                if (sq_abs(st->list[i].w - nw) <= 16 && sq_abs(st->list[i].h - nh) <= 2 &&
                    (!lock || asp_near(st->list[i].w, st->list[i].h, aw, ah))) { pw = st->list[i].w; ph = st->list[i].h; }
        }
        if (pw >= 0 && lock) { nw = pw; nh = ph; }
        if (isdc) set_dc(st, nw, nh); else set_res(st, nw, nh);
    } else if (f == F_DC || f == F_RES) {             /* lockTile: the dial flips; locking takes the ratio */
        u32 *lk = f == F_DC ? &s->dclock : &s->reslock;
        *lk ^= 1u;
        if (*lk) { dc_size(st, f, &w, &h); if (f == F_DC) { s->daw = w; s->dah = h; } else { s->raw = w; s->rah = h; } }
        st->dirty = 1;
    } else if (f == F_FPS) {
        if (!has_q(st)) return 0;
        struct rat fr = {s->fps_n, s->fps_d};
        if (j == 1u && !s->fine) { s->fine = 1; s->fc_d = 0; }   /* FINE.adj: the first step drops the old tuned rate */
        if (s->fine) { fr = fine_step(st, fr, d, big); s->fps_n = fr.n; s->fps_d = fr.d; st->dirty = 1; return 0; }
        fps_list(st);
        int k = fps_sel(st), L = (int)st->n_fl;
        if (k < 0) {
            int a = -1;
            for (int i = 0; i < L && a < 0; i++) if (d > 0 ? rgt(st->fl_e[i].f, fr) : rge(st->fl_e[i].f, fr)) a = i;
            k = d > 0 ? a - 1 : a;
        }
        int jj = k + d;
        while (jj >= 0 && jj < L && st->fl_e[jj].na) jj += d;
        if (jj >= 0 && jj < L) { s->fps_n = st->fl_e[jj].f.n; s->fps_d = st->fl_e[jj].f.d; st->dirty = 1; }
    } else if (f == F_FORMAT) {                       /* 0.0.4test FORMAT.adj: 8 / 10 / RAW bit, stops at the ends */
        int k = (int)depth_idx(depth_now(st)) + d;
        if (k < 0 || k > 2) return 0;
        depth_set(st, k == 0 ? 8u : k == 1 ? 10u : 12u);
    } else if (f == F_RECIPE && j == 0u) {            /* RECIPE.adj: presets, usable only */
        const struct cell *cl = st->cur;
        const struct rcp *c = cur_recipe(st), *P[MAXR];
        int np = 0, jj = -1;
        for (int i = 0; i < cl->n; i++) if (is_preset(&cl->r[i])) { if (c && rq_of(&cl->r[i]) == rq_of(c)) jj = np; P[np++] = &cl->r[i]; }
        if (jj < 0 && c) {
            jj = 0;
            for (int i = 0; i < np; i++) if (P[i]->ad == c->ad && P[i]->mh == c->mh && P[i]->mv == c->mv) { jj = i; break; }
        } else jj += d;
        while (jj >= 0 && jj < np && !usable(st, P[jj])) jj += d;
        if (jj >= 0 && jj < np) {
            s->rq = rq_of(P[jj]); s->rd_ok = 1;
            for (u32 k = 0; k < N_PARAM; k++) s->rd[k] = pval(P[jj], k);
            st->dirty = 1;
        }
    } else if (f == F_RECIPE) {
        const struct rcp *c = cur_recipe(st);
        u32 key = j - 1u;
        if (!c) return 0;
        if (key == K_HB || key == K_VB) {             /* ispBinTile.adj: 1, then this mode's kernels */
            u32 *kk = key == K_HB ? &s->kh : &s->kv, b = key == K_HB ? c->hb : c->vb;
            /* all 13: 1, SOFT x6, STD x6 (live5: STD was unreachable); from 1 it lands on this axis' kernel */
            int jj = b == 3u ? isp_cur(st, key) + d : (d > 0 ? 1 + 6 * (int)s->km + (int)*kk : -1);
            if (jj < 0 || jj > 12) return 0;
            const struct rcp *q = combo(st, key, jj == 0 ? 1u : 3u);
            if (!q) return 0;
            use_recipe(st, q);
            if (jj) {
                u32 md = jj > 6, ki = (u32)jj - 1u - 6u * md;
                if (*kk != ki || s->km != md) { *kk = ki; s->km = md; st->dirty = 1; }
            }
        } else {
            u32 V[MAXR], nv = vals(st, key, V);
            int jj = -1;
            for (u32 i = 0; i < nv; i++) if (V[i] == pval(c, key)) jj = (int)i;
            jj += d;
            while (jj >= 0 && jj < (int)nv && !ok_v(st, key, V[jj])) jj += d;
            if (jj >= 0 && jj < (int)nv) use_recipe(st, combo(st, key, V[jj]));
        }
    }
    return 0;
}

/* 0.0.2test (Bei 11-07): AEL on the main QS's FPS tile -- the in-place fine mode (container API 4 fine(), API 9 next to
 * the sub-QS): on = entering drops the old tuned rate; off (AEL, MENU, the focus moving, a layout load) = fineExit */
static int sq_fine(void *arg, int on)
{
    struct st *st = sq_ctx();
    (void)arg;
    cell_now(st);
    if (on) {
        if (!has_q(st)) return 0;
        st->s.fine = 1; st->s.fc_d = 0;               /* entering fine drops the old tuned rate */
        st->dirty = 1;
        return 1;
    }
    if (st->s.fine) { fine_exit(st); st->dirty = 1; if (!busy()) sq_push(st); }   /* fine mode left: the value lands */
    return 0;
}

static void sq_fine_blur(void *arg)                  /* the focus left FINE (container API 6 blur): fineExit */
{
    struct st *st = sq_ctx();
    (void)arg;
    cell_now(st);
    if (st->s.fine) { fine_exit(st); st->dirty = 1; if (!busy()) sq_push(st); }   /* the tuned value lands: apply */
}

#include "slm_runtime.h"

/* ---------------------------------------------------------------------------------------------- boot apply (v0.7.35test) */
/* After a reboot the recorded selection used to wait for the first leave() that came after live view was up -- in
 * practice the first MENU / QS (the first layout load runs before the mode descriptor exists: AP_E_NOTREADY, owed, and
 * nothing retried).  Now:
 *   - a poller task (priority 28, below the UI and the shell; it never commits) waits every 100 ms for ap_boot_ready
 *     (a standby LV start seen by the picker hook, no playback hook since, not recording, CinemaDNG, descriptor and
 *     register record built) to hold for 5 polls, then posts the private app variable SLM_Boot (FUN_c0593f30: a message
 *     into the GUI queue, the way the firmware's own notifiers post from their tasks);
 *   - the GUI applies it on the UI thread, whose change callback (FUN_c0560fb0) pushes the selection there -- outside
 *     the picker / LV-start path -- after checking again; ap_idle (HUD tiles) follows, as in leave().
 * Only with a valid record (st->loaded): no record keeps today's behaviour.  At most BOOT_TRIES posts, 1.5 s apart;
 * done after a commit that took (AP_OK / AP_IDLE).  leave() stays the fallback: a later push is idempotent (AP_IDLE).
 * The variable and its callback are registered at the first leave() (the UI thread; the GUI object exists then). */
#define BOOT_POLL_MS   100u
#define BOOT_STABLE    5u
#define BOOT_GAP_US    1500000u
#define BOOT_TRIES     20u
#define BOOT_VAR       "SLM_Boot"
#define BOOT_PRIORITY  28u
#define BOOT_STACK     0x800u
#define BOOT_PARK_MS   0x00FFFFFFu            /* done / given up: one wake every ~4.7 h (tk_dly_tsk; no tk_ext_tsk here) */
#define STBY_V72       0xC0CD7A88u            /* StandbyEventHandler_w71c1's vtable word for v72 (screen enter; unique) */
#define STBY_V72_STOCK 0xC0481D80u
#define TK_CRE_TSK     0xC0016A58u
#define TK_STA_TSK     0xC0016BC0u
#define TK_SLEEP_MS    0xC03705D8u
#define GUI_POST_INT   0xC0593F30u            /* (0, name, value): a variable message into the GUI queue */
#define GUI_WATCH      0xC0560FB0u            /* (GUI object, name, fn): fn(desc) on the UI thread */
#define GUI_OBJECT     0xC37B7048u
static u32 boot_owed(const struct st *st) { return st->loaded && !st->boot.done; }
/* the UI thread: the posted value arrived */
USED u32 sq_boot_changed(uintptr_t d)
{
    struct st *st = sq_ctx();
    (void)d;
    if (!st || !boot_owed(st)) return 0;
    st->boot.runs++;
    if (busy() || st->scan.on_page || !ap_boot_ready(st->ap_mem)) { st->boot.why = 2; return 0; }
    sq_push(st);
    st->boot.last_rc = (u32)st->ap_rc;
    if (st->ap_rc == AP_OK || st->ap_rc == AP_IDLE) { st->boot.why = 0; ap_idle(st->ap_mem); }   /* done: sq_push */
    else st->boot.why = 3;
    return 0;
}
/* one poll (the task's body; sq_test 47): 1 = posted */
static u32 boot_poll(struct st *st)
{
    struct boot *b = &st->boot;
    if (!boot_owed(st) || !b->var_ok || b->tries >= BOOT_TRIES) return 0;
    b->polls++;
    if (!ap_boot_ready(st->ap_mem) || busy()) { b->stable = 0; return 0; }
    b->ready_polls++;
    if (++b->stable < BOOT_STABLE) return 0;
    if (b->posts && ap_now_us() - b->last_post < BOOT_GAP_US) return 0;
    b->tries++; b->posts++; b->last_post = ap_now_us(); b->stable = 0;
    ((void (*)(u32, u32, u32))GUI_POST_INT)(0, (u32)(uintptr_t)BOOT_VAR, b->posts);
    return 1;
}
/* the poller (its own task, entered through boot.tramp in ARM state; never returns -- a task cannot end here) */
USED void sq_boot_task(void)
{
    struct st *st = sq_ctx();
    for (;;) {
        u32 live = st && boot_owed(st) && st->boot.tries < BOOT_TRIES;
        ((void (*)(u32))TK_SLEEP_MS)(live ? BOOT_POLL_MS : BOOT_PARK_MS);   /* parked: blocked in tk_dly_tsk */
        if (live) boot_poll(st);
    }
}
/* the first leave() or the standby screen's enter (UI thread): the variable and its callback, once */
__attribute__((noinline)) USED void boot_watch_body(struct st *st)
{
    uintptr_t app = W(GUI_OBJECT);
    if (!app || (app & 3u) || !slm_variable(app, BOOT_VAR, 0, 0)) { st->boot.why = 5; return; }
    ((void (*)(u32, u32, u32))GUI_WATCH)(GUI_OBJECT, (u32)(uintptr_t)BOOT_VAR, (u32)(uintptr_t)sq_boot_changed);
    st->boot.var_ok = 1;
}
/* v0.7.36test: the first leave() only comes with the first MENU / QS -- the case this exists for.  The standby (live
 * view) screen's handler enter, StandbyEventHandler_w71c1::v72 (it registers the screen's rec-seq observer: the LV
 * screen; GUI thread), runs at boot with no key: wrapped through its vtable word (RAM; the QR page's way). */
USED void sl_stby_v72(u32 h)
{
    ((void (*)(u32))STBY_V72_STOCK)(h);
    struct st *st = sq_ctx();
    if (!st) return;
    st->boot.stby_enters++;
    if (!st->boot.var_ok && st->boot.task > 0 && boot_owed(st)) boot_watch_body(st);
}
/* sup_entry: the poller (external, next to the functions whose addresses it hands on: the movw / movt cliff) */
__attribute__((noinline)) USED void boot_start(struct st *st)
{
    volatile u32 d[8];
    st->boot.task = -1;
    if (!st->loaded) { st->boot.why = 1; return; }    /* no record: stock until the first push, as before */
    static const u32 STBY_STOCK = STBY_V72_STOCK;
    if (W(STBY_V72) == STBY_V72_STOCK && st->svc->claim(st->svc, STBY_V72, 4u, &STBY_STOCK, SL_EXCL) == SL_OK) {
        W(STBY_V72) = (u32)(uintptr_t)sl_stby_v72;
        st->boot.stby_ok = 1;
    }                                                 /* else: the first leave() registers (as v0.7.35test) */
    st->boot.tramp[0] = 0xE51FF004u;                  /* ldr pc, [pc, #-4]: interworks into the Thumb body */
    st->boot.tramp[1] = (u32)(uintptr_t)sq_boot_task;  /* Thumb: bit 0 set */
    ((void (*)(void))AP_DCACHE)();                    /* the new instruction words out of the D-cache (code-runs-from-the-pool) */
    d[0] = 0; d[1] = 0x41u; d[2] = (u32)(uintptr_t)st->boot.tramp; d[3] = BOOT_PRIORITY; d[4] = BOOT_STACK;
    d[5] = 0x4F42534Cu; d[6] = 0x0000544Fu; d[7] = 0;   /* "LSBOOT" */
    s32 id = ((s32 (*)(volatile u32 *))TK_CRE_TSK)(d);
    if (id < 1 || ((s32 (*)(s32, u32))TK_STA_TSK)(id, 0)) { st->boot.why = 4; return; }
    st->boot.task = id;
    /* v0.7.37test (live 11-05): the boot LV screen enters BEFORE the sups load (stby_enters 0 after a cold boot, 1 after
     * MENU and back), so the standby hook alone never fires at boot.  The GUI object and its variable registry already
     * exist at load (ScreenFlip and fpsup-ui register / subscribe from their entries): register here; the standby hook
     * and the first leave() stay as fallbacks (both skip once var_ok). */
    boot_watch_body(st);
    st->boot.lv_load = (u32)ap_lv_at_load(st->ap_mem);   /* the boot LV was before us too: the picker never saw it */
    /* v0.7.37test (Bei 11-05: "RES-Custom 就辦得到"): commit right here, as RES-Custom's ogc_restore does at the end of
     * its sup_entry (a running LV is stopped and started by the commit, its lv_reload).  Not ready (no descriptor yet,
     * recording, not CinemaDNG): the poller and the UI-thread callback stay the fallback.  Committed: done -- live
     * 11-05 the callback never ran at boot (posts 16, runs 0: the watch registered from sup_entry does not take), so
     * ap_idle (HUD tiles) comes with the first leave(), as before v0.7.35test. */
    st->boot.entry_rc = -99;
    if (!busy() && ap_cine_now()) {                   /* STILL at boot stays stock: the poller applies back in CINE */
        sq_push(st);
        st->boot.entry_rc = st->ap_rc;                /* committed: sq_push set boot.done */
    }
}
static void boot_watch(struct st *st) { if (!st->boot.var_ok && st->boot.task > 0 && boot_owed(st)) boot_watch_body(st); }

/* ---------------------------------------------------------------------------------------------- test entry */
/* The pure rules for the exhaustive offline tests (test_slqs.py calls it under unicorn): op 1 a16(W*r),
 * 2 ev(H*r), 3 mm text, 4 ratio text, 5 kLabel (3-5 return the text's address), 6 rh(w / (b/c)), 7 rw(h * (b/c)),
 * 8 |pw/ph - b/c| < 0.002, 9 core_qualities_tol of the cell (timing). */
USED int sq_test(u32 op, u32 a, u32 b, u32 c)
{
    struct st *st = sq_ctx();
    char *d = st->v[0][0];
    d[0] = 0;
    if (op == 1u) return a16r((int)a, b);
    if (op == 2u) return evr((int)a, b);
    if (op == 3u) { mm_put(d, 0, a); return (int)(uintptr_t)d; }
    if (op == 4u) { put_fix(d, 0, TXT, (u64)js_fixed_d(dratio(a, b), 3), 3); return (int)(uintptr_t)d; }
    if (op == 5u) { k_label(d, a); return (int)(uintptr_t)d; }
    if (op == 6u) return round_to(ddiv_int(a, dratio(b, c)), 2);
    if (op == 7u) return round_to(dmul(dratio(b, c), a), 16);
    if (op == 8u) return asp_near(a >> 16, a & 0xFFFFu, b, c);
    if (op == 10u) return (int)(uintptr_t)&st->applied;
    if (op == 11u) { st->md_force = a; st->md.ok = 0; return 0; }   /* 0.0.3test: bits 16..23 = depth, read at the next layout */
    if (op == 12u) { st->qr.force = a; return 0; }   /* QR: bit 0 no firmware display calls (no observer) */
    if (op == 13u) { qr_code_now(st); return (int)(uintptr_t)st->qr.code; }   /* the live payload (37 chars, "" = none) */
    if (op == 14u) {                                  /* the QR state */
        struct qr *q = &st->qr;
        u32 v[22] = {q->on, q->enc_ret, q->n, q->scale, q->x0, q->y0, (u32)(uintptr_t)q->mat, (u32)(uintptr_t)q->url,
                     (u32)(uintptr_t)&q->obs, q->vt[3], q->shows, q->hides, q->draws, q->why, q->side, q->reg, q->group,
                     q->tile, q->nbuf, q->restores, q->mask, q->slot};
        for (u32 i = 0; i < 22u; i++) q->info[i] = v[i];
        return (int)(uintptr_t)q->info;
    }
    if (op == 15u) { qr_pack((const u32 *)(uintptr_t)a, d); return (int)(uintptr_t)d; }   /* pack N_QF fields at a */
    /* v0.5.0test, the apply unit (also for the shell: callfn sq_test(op, ...)): 16 flush -> result; 17 the status
     * (struct ap_status; AP_ABI 3: 43 words, the first-frame and resync counters last) -> its address; 18 the last ap_sel
     * handed over -> its address; 19 push now */
    if (op == 16u) return st->ap_rc = ap_flush(st->ap_mem);
    if (op == 17u) {
        st->ap_st.bytes = sizeof st->ap_st; st->ap_st.abi = AP_ABI;
        ap_status_get(st->ap_mem, &st->ap_st);
        return (int)(uintptr_t)&st->ap_st;
    }
    if (op == 18u) return (int)(uintptr_t)&st->ap_last;
    /* v0.7.27test: the first-frame trace (struct ap_trace, apply/ap.c; layout validation/20261104-first-frame-trace):
     * 33 a=0 -> its address (read-only: read it with mem get / MEM1 after the take), a=1 -> records this take */
    if (op == 33u) {
        const u32 *t = (const u32 *)ap_trace_info(st->ap_mem);
        return a == 1u ? (t ? (int)t[4] : 0) : (int)(uintptr_t)t;
    }
    if (op == 19u) { sq_push(st); return st->ap_rc; }
    if (op == 20u) return (int)st->ap_pushes;                     /* change events handed over */
    if (op == 21u) return st->ap_init_rc;
    if (op == 22u) { st->ap_last.valid = 0; return st->ap_rc = ap_request(st->ap_mem, &st->ap_last); }   /* back to stock */
    if (op == 23u) return (int)(uintptr_t)ap_pb_info(st->ap_mem);       /* playback status, read after playback */
    if (op == 24u) return (int)ap_pb_ctl(st->ap_mem, a, b);             /* bounded playback policy controls */
    if (op == 25u) { slm_build(st); return (int)(uintptr_t)&st->menu; } /* offline menu model */
    if (op == 26u) return slm_pick(st, a, b);                         /* offline only: invokes UI services */
    if (op == 27u) return (int)(uintptr_t)&st->menu;                   /* read-only live diagnostics */
    if (op == 28u) return (int)st->pb_ui_result;
    if (op == 29u) return (int)(uintptr_t)st->lt;                     /* v0.7.0test: leave() timing (16 words) */
    if (op == 30u) {                                                  /* v0.7.0test: pause the apply step (a = 1) */
        if (a > 1u) return -1;
        st->push_pause = a;
        if (a) { st->ap_last.valid = 0; return st->ap_rc = ap_request(st->ap_mem, &st->ap_last); }   /* stock, kept */
        sq_push(st);
        return st->ap_rc;
    }
    if (op == 31u) {                                                  /* the container's first-layout timing (API 6) */
        const struct qsc_api *api = st->svc->find(st->svc, QSC_ID);
        return api && api->magic == QSC_API_MAGIC && api->version >= 6u ? (int)(uintptr_t)api->timing : 0;
    }
    if (op == 32u) { sq_ratio_text(d, a, b); return (int)(uintptr_t)d; } /* display-only ratio labels */
    if (op == 40u) return (int)(uintptr_t)&st->scan;                   /* v0.7.32test: the scan state */
    if (op == 41u) {                                    /* qr_restore(fields at a, keep b: 0 check, 1 exact, 2 force) -> ok | diff << 1 */
        u32 diff = 0, ok = (u32)qr_restore(st, (const u32 *)(uintptr_t)a, &diff, b);
        if (ok && b) { st->dirty = 1; sq_push(st); }
        return (int)(ok | diff << 1);
    }
    if (op == 42u) return (int)scan_result(st, (const u8 *)(uintptr_t)a, b);   /* a decoded result, stock convention */
    if (op == 43u) { qr_fields(st, (u32 *)(uintptr_t)a); return 0; }   /* the current 27 fields */
#ifdef AP_REC_DELAY_TEST
    if (op == 49u) return (int)(uintptr_t)&st->rd;                     /* 0.0.2test TEST build: the REC-start delay */
#endif
    if (op == 44u) return (int)(uintptr_t)st->svc->find(st->svc, QSC_ID);   /* the container's api (or 0) */
    if (op == 45u) return (int)(uintptr_t)&st->f[F_QR];               /* the QR function's struct qsc_func */
    if (op == 46u) return (int)(uintptr_t)&st->boot;                  /* v0.7.35test: the boot apply state */
    if (op == 47u) return (int)boot_poll(st);                         /* one poll of the boot poller */
    if (op == 48u) return (int)sq_boot_changed(0);                    /* the UI-thread callback, as the GUI calls it */
    if (op == 9u) return core_qualities_tol((int)(a >> 16), (int)(a & 0xFFFFu), (int)(b >> 16), (int)(b & 0xFFFFu), 0, 1,
                                            TOL_NUM, TOL_DEN, st->scratch, (int)CORE_MAX_QUAL);
    return -1;
}

/* ---------------------------------------------------------------------------------------------- entry */
struct cfg { u32 magic, version, state_off, dma_off, rec_off; };

USED int sup_entry(void *block, const struct sl_svc *svc, const char *path)
{
    const struct sl4_header *hd = (const struct sl4_header *)block;
    const struct cfg *c = (const struct cfg *)((const u8 *)block + SL4_HEADER_LEN);
    (void)path;
    if (svc->version < 6u || c->magic != CFG_MAGIC || c->version != 2u || c->state_off < hd->file_len ||
        c->state_off + sizeof(struct st) > c->dma_off || c->dma_off + FO_BYTES + 0x400u > hd->block_size ||
        c->rec_off + 4u * REC_WORDS > hd->file_len || (c->rec_off & 3u))
        return SL_RELEASE;
    struct st *st = (struct st *)((u8 *)block + c->state_off);
    zero(st, sizeof *st);
    st->svc = svc; st->block = (const u8 *)block; st->rec_off = c->rec_off; st->dma_off = c->dma_off;
    W(sq_ctx_at()) = (u32)(uintptr_t)st;
    struct sel *s = &st->s;                           /* the page's initial S */
    s->dcw = 6048; s->dch = 3402; s->dclock = 1; s->reslock = 1; s->daw = 6048; s->dah = 3402; s->raw = 6048; s->rah = 3402;
    s->rat = 3; s->fps_n = 5994; s->fps_d = 100; s->kh = 1; s->kv = 1;
    st->loaded = (u32)rec_load(s, (const u32 *)((const u8 *)block + c->rec_off));
    for (u32 fi = 0; fi < N_FN; fi++) {
        struct qsc_func *f = &st->f[fi];
        f->sup_id = hd->sup_id;
        for (u32 k = 0; k < QSC_NAME - 1u && FN_NAME[fi][k]; k++) f->name[k] = FN_NAME[fi][k];
        f->label = FN_LABEL[fi];
        f->icon = FN_ICON[fi][0] ? FN_ICON[fi] : 0;
        f->flags = QSC_F_CINE | QSC_F_LOCK_REC | (fi == F_RECIPE || fi == F_MBPS || fi == F_QR ? QSC_F_TITLE : 0u);
        if (fi == F_DC) f->flags |= QSC_F_REPLACE(12);
        else if (fi == F_RES) f->flags |= QSC_F_REPLACE(23);
        else if (fi == F_FPS) f->flags |= QSC_F_REPLACE(25);
        else if (fi == F_FORMAT) f->flags |= QSC_F_REPLACE(21);
        f->value = sq_value;
        f->adjust = fi == F_MBPS || fi == F_QR ? 0 : sq_adjust;   /* 0.0.4test: FORMAT dials the stock depth */
        if (f->adjust) f->flags |= QSC_F_DIAL_HINT;       /* v0.7.36test: container API 8 shows the dial steps (older: ignored) */
        f->small = sq_small;
        f->footer = sq_footer;
        f->arg = &st->arg[fi][0];
        u32 ns = fi == F_DC || fi == F_RES ? 3u : fi == F_RECIPE ? 7u : fi == F_FPS ? 1u : 0u;   /* FPS: FINE */
        for (u32 j = 0; j < ns; j++) {
            struct qsc_sub *b = &st->sub[fi][j];
            b->label = fi == F_RECIPE ? SUB_LABEL[j] : fi == F_FPS ? "FINE" : j == 0u ? "WIDTH" : j == 1u ? "HEIGHT" : "RATIO";
            b->value = sq_value;
            b->adjust = sq_adjust;
            b->arg = &st->arg[fi][j + 1u];
            b->small = sq_small;
            b->footer = sq_footer;
            b->lock = (fi == F_DC || fi == F_RES) && j == 2u ? sq_lock_icon : 0;
            b->icon = (fi == F_DC || fi == F_RES) && j == 2u ? "menu_lock_qs" : 0;
            b->blur = fi == F_FPS ? sq_fine_blur : 0;
        }
        if (ns) { st->subs[fi].n = ns; st->subs[fi].item = st->sub[fi]; f->sub = &st->subs[fi]; }
    }
    {   /* 0.0.2test: FPS AEL = in-place fine when the container takes fine + sub (API 9; it loads first: alphabetical) */
        const struct qsc_api *api = svc->find(svc, QSC_ID);
        if (api && api->magic == QSC_API_MAGIC && api->version >= 9u) st->f[F_FPS].fine = sq_fine;
    }
    st->t.magic = QSC_TABLE_MAGIC4;
    st->t.n = N_FN;
    st->t.f = st->f;
    st->t.leave = sq_leave;
    st->t.leave_arg = st;
    /* v0.5.0test: the apply unit claims and arms its 26 hooks + the clock gate here (sup_entry only).  The recorded
     * selection is restored at the first leave() (the first layout load), not here: no LV, no descriptor yet. */
    st->ap_init_rc = ap_init(st->ap_mem, sizeof st->ap_mem, svc);
#ifdef AP_REC_DELAY_TEST
    if (st->ap_init_rc == AP_OK) ap_rd_attach(st->ap_mem, &st->rd);   /* the REC-start delay (TEST build) */
#endif
    scan_install(st, svc);                            /* v0.7.32test: the read page's handler slots */
    st->pb_ui_result = UIA_NO_UI;
    /* v0.7.21test: the Playback page's blank Resolution frame is applied at the first-layout menu setup
     * (slm_runtime.h), where the UI reader exists -- here it would be UIA_NO_UI. */
    st->ap_boot_owed = 1;
    boot_start(st);                                   /* v0.7.35test: apply the record once LV is up (no MENU / QS) */
    svc->publish(svc);
    return svc->provide(svc, QSC_TAG(hd->sup_id), &st->t) == SL_OK ? SL_KEEP : SL_RELEASE;
}
