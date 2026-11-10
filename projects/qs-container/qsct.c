/* QS Container (sup_id QSCT), v0.2.2: new functions in the stock custom-QS
 * editor's list and on the Quick Set page, registered by other sups (qsc.h),
 * that behave like a stock function, and never reach the settings flash.
 *
 *   registration  clients provide(QSC_TAG(id), table); collected once, at the
 *                 first layout load after all entries (C05D90F0, SL_CHAIN)
 *   C1 CSV rows   the four Y2_3_CINE*.cvm copies in the shared file-redirect
 *                 table get one row per function (KEY = the literal label)
 *   C4 converter  [0xC37B7728] -> a vtable copy; +0x344 (CINE) = the layer
 *                 below's pairs + {54+i, 49+i} + the QS page's sub-item and
 *                 blank tiles {70+j, 65+j}, {77, 72}
 *   C5 save swap  0xC0088C60 `bl FUN_c0088660`: every id >= 54 in the image
 *                 serialised is replaced by the slot's previous stock function
 *                 (kept in this BIN's record), RAM gets it back right after
 *   C6 QR read    0xC053DBF8 `bl FUN_c0061b08`: >= 54 reads as the placeholder
 *   C7 restore    at collection: a slot the record says is ours and that still
 *                 holds its placeholder gets the function back (client present)
 *   E2-E5 editor  Y2_3C / Y2_3C_ShutterAngle served from one streaming copy
 *                 each (uishare's FSPG convention), with the edit list
 *                 editor_data.py made
 *   Q  QS page    QS_CINE through the C05E6400 record layer (SL_CHAIN, nested:
 *                 only stock records, another layer's copies pass): the records
 *                 qs_page_data.py lists are served from copies built once at
 *                 collection -- ranges/intervals to UI 72, the dial / AEL key
 *                 clips with the headphone's closing key and one keyEvent of
 *                 ours (controlAppVariable QSC_Key <- code), the tile's icon,
 *                 label / value drawText bound to QSC_L/V<k>, grey QSC_G<k>; the
 *                 cached QS layout is let go once so the next QS open reparses
 *                 (res-custom ogc_qslay's rule, after v5c: never the one loading)
 *   K  keys       QSC_Key watched (C0560FB0): dial -> the focused function's or
 *                 sub-item's adjust(); AEL -> sub-QS open / return (MV_QSMENU_QSn
 *                 posted, never the settings); texts posted with C0593FE0
 *   G  focus      0xC0582DB4 `bl FUN_c057f310(id)` in the QS GUI's QS_QSMode
 *                 callback (v0.2.1): the "AEL more options" hint for our ids
 *                 (only with sub-items), the footer option strip, the arrows
 *   0.0.2test     API 9 (Bei 11-07, SensorLab FPS): a function may have both fine() and a sub-QS -- AEL on its tile
 *                 runs the fine mode in place (fine() wins, as before); the sub-QS opens only through open()
 *                 (QSC_OPEN_SUB / QSC_OPEN_SUB_AT).  API <= 8 refused such a function at registration.
 *   v0.3.8        API 8 (README "v0.3.8"): QSC_F_DIAL_HINT -- on a flagged function's tile / sub-item with an
 *                 adjust() and not locked, the footer guide line's left end shows the stock dial glyphs and steps
 *                 (QSC_DH: a text in the BIN, QSC_DHB: its backing box), decided where the arrows are (qc_focus)
 *   v0.3.7        API 7 (README "v0.3.7"): QSC_F_GO -- AEL on the tile asks fine(arg, 1); non-0 posts QSC_Go,
 *                 whose change event (an object of ours on the QS page) sends the stock controlAppState request
 *                 held in the go text (filled only for a go, emptied at the next layout load); a private state
 *                 machine (fpsup-ui FT4S file, installed at entry) has QS_CINE -> Y5_ReadQR
 *   v0.3.2        AEL alive on the first QS open (README "v0.3.2"): QS_AELbtn (the stock AEL object's visibility,
 *                 where our keyEvent lives) posted on every focus of ours -- it was left to the last stock tile
 *                 + a lock tile's small text in the title row, clear of the icon (live4 #15)
 *   v0.3.1        API 6 (README "v0.3.1"): a sub-item's blur() when the focus leaves it; open() can focus a
 *                 sub-item (QSC_OPEN_SUB_AT(k)) -- SensorLab's FPS sub-QS (FPS + FINE), the menu's CUSTOM on FINE
 *   v0.2.4        RECIPE round (README "v0.2.4"): a value's "[...]" part is drawn in the plain font
 *                 (bold "3", thin "[1,2,1]"); footer options too wide for a 128 px slot get a wider
 *                 pitch and fewer options at once (qc_small_w: measured glyph advances)
 *   v0.2.3        main QS layout (README "v0.2.3"): a footer option without a second line
 *                 is drawn centred in its box (three centred label roles), the mark is a thin
 *                 dotted line under it; a QSC_F_TITLE function's tile gets no borrowed icon;
 *                 our tiles drive the hint text QS_FooterGuid1 themselves (1 = AEL more
 *                 options, 0 = none) -- the stock K tile's text no longer stays on them
 *   v0.2.2        API 4 (README "v0.2.2"): fine mode, footer mark / custom / grey, 7 sub-items,
 *                 rear dial +-10, QSC_F_TITLE, lock icon in the value row, table leave();
 *                 live run 3: MENU in the sub-QS is the stock MENU again (config flag),
 *                 AEL returns; small lines in the plain font (grey: glyph images are
 *                 not tinted); values too wide for the tile in the plain font
 *   v0.2.1        values in the stock bold glyphs (inline <!font_menu_LB_..>),
 *                 small line, footer strip / spinner, sub-QS: the function on
 *                 tile 1, MENU returns, hint "MENU Back" (QS_FooterGuid1 14);
 *                 Icon02 re-triggered from the value text (an invisible object's
 *                 events do not fire) -- README "v0.2.1"
 *
 *   Q4 headphone  0xC0582AE8 (QS GUI's CM_HeadphoneVolume callback): not called
 *                 while the focused QS tile is ours (belt and braces now: the
 *                 data closes the headphone keyEvent at t(49))
 *
 * Design: projects/qs-touch/notes/QS_CONTAINER_DESIGN.md; README.md next to
 * this file.  Loader v4, -fropi Thumb, .text only: no .rodata, no division.
 * Firmware Ver.5.02. */
#include <stdint.h>
#include "sloader4.h"
#include "fpui_stock.c"
#include "fpsup_ui.c"             /* v0.3.7: fpui_install of the go machine's FT4S file */
#include "qsc.h"

typedef uint32_t u32;
typedef uint16_t u16;
typedef uint8_t u8;
#define USED __attribute__((used))
#define W(a) (*(volatile u32 *)(uintptr_t)(a))
#define B8(a) (*(volatile u8 *)(uintptr_t)(a))

/* ---- firmware (Ver.5.02) --------------------------------------------------- */
#define CONV_GET     0xC058C4D0u  /* FUN_c058c4d0: builds once, returns the singleton */
#define CONV         0xC37B7724u
#define CONV_VT      0xC37B7728u
#define VT_STOCK     0xC2DEAD7Cu
#define VT_PRE       8u
#define VT_BYTES     0x55Cu
#define VT_CINE      0x344u       /* MenuValueConverterBase v207: CINE {internal, ui} */
#define TAB_MAX      96u
#define SAVE_SITE    0xC0088C60u  /* MenuSettingStorage::v2: bl FUN_c0088660(store, image) */
#define SAVE_STOCK   0xEBFFFE7Eu
#define REC_SITE     0xC053DBF8u  /* FUN_c053db98 (RecommendedSetting): bl FUN_c0061b08 */
#define REC_STOCK    0xEBEC8FC2u
#define HP_SITE      0xC0582AE8u  /* FUN_c0582ab0 (QS: CM_HeadphoneVolume): bl FUN_c0062bb0 */
#define HP_STOCK     0xEBEB8030u
#define LAY_SITE     0xC05D90F0u  /* FUN_c05d90f0: load one layout (Thumb) */
#define LAY_STOCK    0x4CF0E92Du  /* push.w {r4-r7, r10, r11, lr} */
#define QS_STATE     0xC05666A0u  /* FUN_c05666a0: +0xBC = the focused QS tile's internal id */
#define QS_FOCUS     0xBCu
#define FV_SITE      0xC05E5BECu
#define FV_STOCK     0x60681840u
#define STORE        0xC31AE3B0u
#define STORE_IMG_A  0xCu
#define STORE_IMG_B  0x58D4u
#define STORE_SEL    0xB19Cu
#define QS_ARR0      0x23E8u      /* STILL's eight slots */
#define QS_ARR1      0x2700u      /* CINE's (camera 2026-10-28) */
#define SETTINGS_GET 0xC0057AE8u
#define TICK_US      0xC002B6E0u  /* FUN_c002b6e0: the microsecond tick (SensorLab's ap_now_us) */
#define IS_CINE      0xC0058340u
#define QS_GET       0xC0061B08u
#define TO_UI        0xC06C7B28u
#define TO_INT       0xC06C7BC0u
#define POST_INT     0xC0593F30u
#define QS_NAME0     0xC2DEE70Eu  /* "MV_QSMENU_QS1", +0x10 each */
#define F_CTOR  0xC0365E90u
#define F_OPEN  0xC0365FB0u
#define F_READ  0xC0366060u
#define F_WRITE 0xC03660E8u
#define F_SEEK  0xC03661E0u
#define F_CLOSE 0xC0366020u
#define F_DTOR  0xC0365ED0u
#define MOV_SELECTOR   0xC347D1D4u
#define MOVREC_DEFAULT 0xC347E08Fu
#define MOVREC_SEL21   0xC3476609u
#define XMP_FOBJ_PTR   0xC358E140u
#define MOV_ACTIVE     0xC35A952Cu
#define VENEER_ARM     0xE51FF004u  /* ldr pc, [pc, #-4] */
#define VENEER_THUMB   0xF000F8DFu  /* ldr.w pc, [pc, #0] */
#define ZQS_ID         0x314E5351u  /* "QSN1": QS Touch's native sup (ZQS.BIN) */
/* stage 2: the QS page */
#define REC_PARSE      0xC05E6400u  /* FUN_c05e6400(reader): parse one NBU record (Thumb) */
#define REC_PARSE_STOCK 0x4FF0E92Du /* push.w {r4-r11, lr} */
#define R_POS          0x04u        /* reader: record position (from the base) */
#define R_BASE         0x24u        /* reader: base; the record is at base + pos */
#define RCACHE         0xC37B7254u  /* UicResourceCache: +4 the layout it holds */
#define RCACHE_V2      0xC05663E8u
#define RCACHE_V3      0xC0566498u  /* takes the cache in r0 (rcache-v3-takes-the-cache) */
#define GUI_OBJECT     0xC37B7048u
#define VAR_REGISTER   0xC05DB309u  /* Thumb (app, 1, {type, name, first}) -> 0 */
#define VAR_WATCH      0xC0560FB0u  /* ARM (GUI object, name, fn): fn(desc) on the UI thread */
#define POST_STR       0xC0593FE0u  /* ARM (0, name, text): the GUI keeps the pointer */
#define VAR_TEXT       2u
/* v0.2.1: the focus of a QS tile, the "AEL more options" hint */
#define GUID_SITE      0xC0582DB4u  /* FUN_c0582da0 (QS_QSMode -> internal): bl FUN_c057f310(id) */
#define GUID_STOCK     0xEBFFF155u
#define GUID_FN        0xC057F310u  /* sets QS_FooterGuidDisp for a stock id (1 for every id >= 4) */
#define APPVARS        0xC054DD38u  /* -> the app variable object: vt+0x2C (obj, name, value) */
#define GUID_NAME      0xC0D1C900u  /* "QS_FooterGuidDisp" */
#define GUID1_NAME     0xC0D1C8C0u  /* "QS_FooterGuid1": the hint's text (frame of 'Option') */
#define HINT_MORE      1u           /* Footer14_K "AEL Further Options" */
#define HINT_BACK      14u          /* Footer03_K "MENU Back" (qs_page_data.hint_back) */
#define AELBTN_NAME    0xC2DAAD34u  /* "QS_AELbtn": the Button's AEL object (8514) is visible -- its keyEvents
                                     * fire -- only while this is 1; every stock QSMode holder writes it, our ids
                                     * have none (v0.3.2) */
#define QS_GUID_VT     0x44u        /* [QS state + 0x44] + 0x74: its current value (of QS state + 0x3C) */
#define QS_GUID_CACHE  0xC0u

#define CFG_MAGIC 0x30435351u     /* "QSC0" */
#define ST_MAGIC  0x4E555251u     /* "QRUN" */
#define REC_MAGIC 0x31435351u     /* "QSC1" */
#define REC_VERSION 1u
#define NSLOT     16u
#define REC_WORDS (2u + 5u * NSLOT + 1u)   /* magic, version, 16 x {key[4], ph}, FNV */
#define REC_SUM   (REC_WORDS - 1u)
#define FO_BYTES  0x800u
#define DMA_BYTES (FO_BYTES + 0x600u)
#define NCSV      4u
#define NPAGE     2u
#define UI_BASE   49u
#define INT_BASE  54u
#define ICON_NAME 28u
#define UI_SUB0   65u             /* qs_page_data.py: 65 = the open function (tile 1), items 66..71, blank 72 */
#define INT_SUB0  70u             /* ... internal 70, 71..76, 77 */
#define UI_MAIN   UI_SUB0
#define INT_MAIN  INT_SUB0
#define INT_ITEM0 (INT_SUB0 + 1u)
#define N_EXTRA   8u              /* the open function, six sub-items, the blank */
#define UI_BLANK  (UI_SUB0 + 7u)
#define QT_MAX    160u            /* QS table targets */
#define N_SLOT    15u             /* footer slot positions (qs_page_data.N_SLOT) */
#define BOX_NONE  15u
#define N_WIN     7u              /* footer options shown at once */
#define N_NAMES   212u            /* qs_page_data.NAMES */
#define NAME_BYTES 12u
#define S_KEY 0u
#define S_L   1u
#define S_V   9u
#define S_G   17u
#define S_S   25u
#define S_Y   33u
#define S_FL  41u
#define S_FS  (S_FL + N_SLOT)
#define S_FY  (S_FS + N_SLOT)
#define S_FG  (S_FY + N_SLOT)       /* v0.2.2: grey label, yellow (custom) label, grey-reason small, mark */
#define S_FC  (S_FG + N_SLOT)
#define S_FN  (S_FC + N_SLOT)
#define S_FM  (S_FN + N_SLOT)
#define S_FP  (S_FM + N_SLOT)       /* v0.2.3: centred label (no second line): white, grey, yellow */
#define S_FQ  (S_FP + N_SLOT)
#define S_FR  (S_FQ + N_SLOT)
#define S_FB  (S_FR + N_SLOT)
#define S_ARW (S_FB + 1u)
#define S_LW  (S_ARW + 1u)
#define S_SW  (S_LW + 8u)
#define S_GO  (S_SW + 8u)         /* v0.3.7: QSC_Go (int): its change event sends the go request */
#define GO_TEXT 32u               /* qs_page_data.GO_TEXT_BYTES: the request text (private string) */
#define S_DH  (S_GO + 1u)         /* v0.3.8: QSC_DH (text): the dial guide, a text of the BIN or blank */
#define S_DHB (S_GO + 2u)         /* v0.3.8: QSC_DHB (int): its backing box, 1 = shown */
#define DH_BYTES 128u             /* qs_page_data.DIAL_TEXT_BYTES: each guide text's slot (API 4, API 3 steps) */
#define CODE_UP 1u
#define CODE_DOWN 2u
#define CODE_RUP 3u               /* v0.2.2: the rear dial (BL / BR) */
#define CODE_RDOWN 4u
#define CODE_AEL 5u
#define CODE_MENU 6u
#define TXT_BYTES 512u            /* a tile text after the glyph markup */
#define FT_BYTES  64u             /* a footer text (a spinner arrow's markup is 28; v0.2.2: a greyed reason line) */
#define N_FROLE   10u             /* footer roles: label, small, yellow small, grey label, yellow label, grey small, mark,
                                     v0.2.3: the three labels centred (an option without a second line) */
#define VALUE_W   220u            /* v0.2.2: a value wider than this in the bold glyphs is drawn in the plain font */
#define CF_MENU_BACK 1u           /* cfg->flags: MENU in the sub-QS returns (v0.2.1 data M); off = stock MENU */
#define FX_API4   0x80000000u     /* struct fx flags: the function came in an API 4 table */
#define N_GLYPH   129u            /* per font: ASCII 0..127, then U+00D7 */
enum { R_L = 0, R_V, R_S, R_Y, N_ROLE };
enum { FONT_PLAIN = 0, FONT_BIG = 1, FONT_SMALL = 2 };
enum { Q_SET = 1, Q_ADD = 2, Q_INS = 3, Q_APP = 4 };
enum { P_STR = 1, P_LOOK = 2, P_GO = 3 };
struct qt { u32 pos, len, fnv, out_len, op_first, op_n, patch_first, patch_n, n_out; };
struct qop { u32 at; u8 kind, z0; u16 z1; u32 a, b; };
struct qpatch { u32 out; u16 kind, arg; };

/* editor_data.py */
enum { K_ADDF_N = 1, K_SET_END, K_ADJ, K_INS, K_SETV, K_SETFLAG, K_DIGIT,
       K_FRAG, K_FPATCH, K_ADDC };       /* v0.3.6 (editor_title.py): fragment, its patch, add a constant */
enum { S_NONE = 0, S_IMAGE, S_RECT, S_SIZE, S_POS, S_ROW, S_LABEL, S_TITLE, S_BLANK };
struct edit { u32 pos; u8 kind, sel, fi, pad; u32 a, b; };
struct icon { char name[ICON_NAME]; u32 image, rect, size, pos; };

/* The host's config, at block + 48 (build_qsct.py). */
struct cfg {
    u32 magic, version;
    u32 state_off, dma_off, rec_off;
    u32 fpui_off, fpui_len;               /* entry: HOOK_FV only (the redirect handler) */
    u32 fv_entry, fv_table_word;
    u32 csv_stock[NCSV], csv_size[NCSV];
    u32 icons_off, n_icons, icon_default;
    u32 page_name_off[NPAGE], page_name_len[NPAGE], page_entry[NPAGE], page_len[NPAGE];
    u32 edits_off[NPAGE], n_edits[NPAGE], page_csv[NPAGE], page_ins_max[NPAGE];
    u32 t_of[QSC_MAX];                    /* t(49 + i) */
    u32 digit[10];                        /* pool offsets of font_menu_S_0..9 */
    u32 def[NSLOT];                       /* the stock defaults (FUN_c04b4688), the last resort */
    u32 flags;
    /* stage 2: the QS page (qs_page_data.py table(), offsets from the block) */
    u32 qs_off, qs_n, qs_ops_off, qs_patches_off, qs_frags_off, qs_out_total;
    u32 qs_page_entry, qs_page_len, qs_page_name_off, qs_page_name_len;
    u32 names_off;                        /* N_NAMES x 12 bytes: the private variable names */
    u32 blank_off;                        /* " " */
    u32 qsmode_name;                      /* the stock pool's "QS_QSMode" (an address) */
    u32 looks_off;                        /* per icon: the QS Icon01 look {image, rect, size, pos} (raw BE) */
    /* v0.2.1 */
    u32 focuspos_name;                    /* the stock pool's "QS_FocusPos" (an address) */
    u32 pool_base;                        /* the string pool: a look's image is an offset into it */
    u32 glyph_off;                        /* 2 x N_GLYPH u32: block offsets of "<!font_menu_LB_..,CENTER>" (0 = the char) */
    u32 mk_open_off, mk_close_off;        /* "<!", ",CENTER>" */
    u32 lock_off[2];                      /* "<!menu_select_unlock,CENTER>", "<!menu_select_lock,CENTER>" */
    u32 arrow_off[2];                     /* "<!menu_arrow_M_left,CENTER>", "<!menu_arrow_M_right,CENTER>" */
    /* v0.2.2 */
    u32 gwidth_off;                       /* N_GLYPH bytes: the LB glyph widths (px) */
    u32 mark_off;                         /* the footer mark text (a dotted line) */
    /* v0.3.7 (API 7 go) */
    u32 go_file_off, go_file_len;         /* fpsup-ui FT4S file: one never-shown page + machine TransQscGo */
    u32 go_text_off;                      /* GO_TEXT bytes right after the blank: the request, empty but for a go */
    u32 go_page_off;                      /* QSC_GO_READQR's page name ("Y5_ReadQR") */
    /* v0.3.8 (API 8 dial guide) */
    u32 dial_off;                         /* 2 x DH_BYTES right after the go text: the guide with the rear step
                                             +-10 (API 4), with +-1 (API 3 / 2) */
};

struct fn {
    u32 key[4];                           /* sup_id, name[12] */
    char label[QSC_LABEL];
    u32 icon;                             /* index into the icon table */
    u32 csv_icon;                         /* the same: its name is the CSV IMAGE */
};

/* Results (st.result / st.freeze): 0 = fine. */
enum { R_OK = 0, R_CLAIM = 1, R_PREV_VT = 2, R_COLLIDE = 3, R_CHAIN = 4, R_CAVE = 5 };
enum { F_ZQS = 1, F_PAGE = 3, F_CSV = 4, F_NONE = 5, F_QS = 6 };
enum { PH_ENTRY = 0, PH_RUNNING = 1, PH_READY = 2, PH_DOWN = 3 };

struct st {
    u32 magic, result, phase, freeze;                             /* 0 */
    const struct sl_svc *svc;                                     /* 16 */
    const u8 *block;
    const struct cfg *cfg;
    const char *path;
    u32 n, offered, full, bad, tables, lay_calls;                 /* 32 */
    struct fn f[QSC_MAX];                                         /* 56 */
    /* converter */
    u32 prev_vt, prev_cine, src, src_n, tab_n, tab_for, tab_ok, collide;
    u32 vt[(VT_PRE + VT_BYTES) / 4u];
    u32 tab[2u * TAB_MAX];
    /* hooks */
    u32 next_save, next_rec, next_hp, next_lay, veneer;
    /* the record: what the BIN holds (read at boot, then written) */
    u32 rec_key[NSLOT][4], rec_ph[NSLOT], rec_used, rec_valid;
    u32 last[NSLOT];                      /* each slot's last stock value seen */
    u32 saves, sanitized, rec_hits, hp_blocks, restored, stale, orphans;
    u32 writes, write_fails, write_why, busy_skips, emitted;
    u32 fv_result, csv_result, csv_rows[NCSV], page_result[NPAGE], page_at[NPAGE], page_bytes[NPAGE];
    struct qsc_api api;
    /* ---- stage 2 (appended: stage 1's offsets stay) ---- */
    struct fx {                           /* function i's QS side (qsc_func, validated) */
        u32 flags, value, adjust, state, arg, nsub, small, footer;
        u32 sv[QSC_SUB_MAX], sa[QSC_SUB_MAX], sarg[QSC_SUB_MAX], ssmall[QSC_SUB_MAX], sfoot[QSC_SUB_MAX],
            slock[QSC_SUB_MAX];
        char sl[QSC_SUB_MAX][QSC_LABEL];
        char sicon[QSC_SUB_MAX][ICON_NAME];
    } fx[QSC_MAX];
    u32 qs_result, qs_ready, qs_pre, qs_boot, qs_inreload, qs_reloads;
    u32 qs_hits, qs_foreign, qs_entry_bad, qs_vars;
    u32 next_qsrec, tab_extra;
    u32 qs_out[QT_MAX];                   /* each target's output records */
    int32_t sub_open;                     /* the function whose sub-QS is up, or -1 */
    u32 sub_tile[8];                      /* the tiles' UI ids while it is */
    u32 keys, dials, aels, opens, closes, adjusts, locked, posts;
    u32 g_last[8], t_sel[8][N_ROLE];
    /* v0.2.1 */
    u32 menus, focus_calls, guid_sets, qs_fresh, sub_home, focus, fb_last, arw_last, foot_on;
    u32 f_sel[N_SLOT][N_FROLE];
    char txt[8][N_ROLE][2][TXT_BYTES];    /* tile k, role, double buffer (the GUI keeps the pointer) */
    char ftxt[N_SLOT][N_FROLE][2][FT_BYTES];   /* footer slot j, role (N_FROLE) */
    u32 next_guid;
    /* v0.2.2 (appended) */
    u32 xfine[QSC_MAX];                   /* function i's fine(); 0 = none (API 3) */
    u32 leave_fn[QSC_MAX], leave_arg[QSC_MAX], n_leave;
    u32 fine_on, fines, leaves, rears;
    /* v0.2.4 (appended) */
    u32 foot_pitch;                       /* the footer's slot pitch now (2 = 128 px) */
    /* API 5: a request opens only at the proven QS focus callback; all layout
     * changes restore stock app-variable ids before another page can use them. */
    u32 qs_active, pending_fn, pending_how, standalone;
    u32 editor_row[NCSV][QSC_MAX];
    /* API 6 (v0.3.1, appended): each sub-item's blur(); the focused item that has one, called when the focus leaves */
    u32 sblur[QSC_MAX][QSC_SUB_MAX];
    u32 blur_id, blur_fn, blur_arg, blurs;
    u32 tm[12];                           /* API 6: layout timing (qsc_api.timing) */
    u32 lock_width_last[8];                /* v0.3.4: centred native QS LOCK image, 0 / 150 */
    u32 small_lock_width_last[8];          /* v0.3.5: same asset in the small row, 0 / 120 */
    /* v0.3.7 (API 7, appended): the go machine's install result (0 = in), a go text armed, QSC_Go's last value,
     * goes posted, fine(arg, 1) said no, AEL on a GO tile skipped (no machine / recording / unknown target) */
    u32 go_result, go_armed, go_seq, goes, go_refused, go_skips;
    /* v0.3.8 (API 8, appended): the dial guide shown now (0 none, 1 rear +-10, 2 rear +-1), its posts */
    u32 dh_last, dh_posts;
};

/* ---- the state pointer: a word in the code (writable at the cached alias) ---- */
__attribute__((noinline)) static u32 qc_ctx_at(void)
{
    u32 at;
    __asm__ volatile("adr %0, 1f\n\tb 2f\n\t.balign 4\n1:\t.word 0\n2:" : "=r"(at));
    return at;
}
static struct st *qc_ctx(void) { return (struct st *)(uintptr_t)W(qc_ctx_at()); }

typedef u32 (*fn0)(void);
typedef u32 (*fn1)(u32);
typedef u32 (*fn2)(u32, u32);
typedef u32 (*fn3)(u32, u32, u32);
typedef u32 (*fn4)(u32, u32, u32, u32);

static int ours(const struct st *s, u32 v) { return v - INT_BASE < s->n; }
static u32 extra(const struct st *s);
static u32 replacement(u32 flags) { return ((flags & QSC_REPLACE_MASK) >> 16) - 1u; }
static u32 qc_go_target(const struct fx *x) { return (x->flags & QSC_GO_MASK) >> 8; }
static u32 qc_qs_id(const struct st *s, u32 v)
{
    if (s->qs_active && ((fn1)IS_CINE)(((fn0)SETTINGS_GET)()) == 1u)
        for (u32 i = 0; i < s->n; i++) if (replacement(s->fx[i].flags) == v) return INT_BASE + i;
    return v;
}
static int ours_qs(const struct st *s, u32 v) { v = qc_qs_id(s, v); return ours(s, v) || v - INT_SUB0 < extra(s); }
static u32 qc_slot_ui(const struct st *s, u32 k)
{
    u32 v = ((fn2)QS_GET)(((fn0)SETTINGS_GET)(), k);
    return ((fn2)TO_UI)(CONV, qc_qs_id(s, v));
}
static u32 editor_count(const struct st *s, u32 n)
{
    u32 count = 0;
    for (u32 i = 0; i < n; i++) if (!(s->fx[i].flags & QSC_REPLACE_MASK)) count++;
    return count;
}
static int foreign_id(u32 v) { return v >= INT_BASE; }          /* no stock function is >= 54 */
static u32 arr(u32 i) { return (i < 8u ? QS_ARR0 : QS_ARR1) + 4u * (i & 7u); }
static u32 image_now(void) { return STORE + (B8(STORE + STORE_SEL) ? STORE_IMG_B : STORE_IMG_A); }
static u32 bl_to(u32 site, u32 dest) { return 0xEB000000u | (((dest - site - 8u) >> 2) & 0xFFFFFFu); }
static u32 thumb_bw(u32 site, u32 to)
{
    u32 off = to - (site + 4u), sg = off >> 31, i1 = (off >> 23) & 1u, i2 = (off >> 22) & 1u;
    u32 j1 = (1u ^ i1) ^ sg, j2 = (1u ^ i2) ^ sg;
    return (0xF000u | sg << 10 | ((off >> 12) & 0x3FFu)) | (0x9000u | j1 << 13 | j2 << 11 | ((off >> 1) & 0x7FFu)) << 16;
}
static u32 fnv_words(const u32 *w, u32 n)
{
    u32 h = 2166136261u;
    for (u32 i = 0; i < n; i++) {
        u32 v = w[i];
        for (u32 b = 0; b < 4u; b++) { h = (h ^ (v & 0xFFu)) * 16777619u; v >>= 8; }
    }
    return h;
}
static u32 popcount(u32 v) { u32 n = 0; for (; v; v &= v - 1u) n++; return n; }
static u32 rd_be(uintptr_t a) { return (u32)B8(a) << 24 | (u32)B8(a + 1) << 16 | (u32)B8(a + 2) << 8 | B8(a + 3); }
static void wr_be(uintptr_t a, u32 v) { B8(a) = (u8)(v >> 24); B8(a + 1) = (u8)(v >> 16); B8(a + 2) = (u8)(v >> 8); B8(a + 3) = (u8)v; }
static int key_eq(const u32 *a, const u32 *b) { return a[0] == b[0] && a[1] == b[1] && a[2] == b[2] && a[3] == b[3]; }
static u32 label_id(const struct fn *f) { return (u32)(uintptr_t)f->label - SL_ALIAS; }

/* ===== C4: the converter layer ============================================== */
static int collides(u32 a, u32 b) { return a - INT_BASE < QSC_MAX + N_EXTRA || b - UI_BASE < QSC_MAX + N_EXTRA; }
static u32 extra(const struct st *s) { return s->n && s->qs_ready ? N_EXTRA : 0u; }

static u32 qc_build(struct st *s, u32 prev, u32 n)
{
    s->tab_ok = 0;
    if (!prev || (prev & 3u) || n > TAB_MAX - QSC_MAX - N_EXTRA) return 0;
    for (u32 i = 0; i < n; i++) {
        u32 a = W(prev + 8u * i), b = W(prev + 8u * i + 4u);
        if (collides(a, b)) { s->collide++; return 0; }
        s->tab[2u * i] = a;
        s->tab[2u * i + 1u] = b;
    }
    for (u32 j = 0; j < s->n; j++) {
        s->tab[2u * (n + j)] = INT_BASE + j;
        s->tab[2u * (n + j) + 1u] = UI_BASE + j;
    }
    for (u32 j = 0; j < extra(s); j++) {              /* the QS page's sub-item / blank tiles */
        s->tab[2u * (n + s->n + j)] = INT_SUB0 + j;
        s->tab[2u * (n + s->n + j) + 1u] = UI_SUB0 + j;
    }
    s->tab_n = n + s->n + extra(s);
    s->tab_for = s->n;
    s->tab_extra = extra(s);
    s->src = prev;
    s->src_n = n;
    s->tab_ok = 1;
    return 1;
}

/* Every slot's last stock value: the conversion runs before the editor's setter
 * writes a slot, so the value our function replaces is seen here first. */
static void qc_snapshot(struct st *s)
{
    u32 img = image_now();
    for (u32 i = 0; i < NSLOT; i++) {
        u32 v = W(img + arr(i));
        if (!foreign_id(v)) s->last[i] = v;
    }
}

static USED u32 qc_cine(u32 conv, u32 *out)
{
    struct st *s = qc_ctx();
    u32 prev = 0, n = ((u32 (*)(u32, u32 *))s->prev_cine)(conv, &prev);
    if (s->phase == PH_READY) qc_snapshot(s);
    if ((s->tab_ok && prev == s->src && n == s->src_n && s->tab_for == s->n && s->tab_extra == extra(s)) ||
        qc_build(s, prev, n)) {
        *out = (u32)(uintptr_t)s->tab;
        return s->tab_n;
    }
    *out = prev;
    return n;
}

/* ===== C5 / C6: the placeholder ============================================ */
static int busy(void)
{
    u32 sel = W(MOV_SELECTOR) == 0x21u ? MOVREC_SEL21 : MOVREC_DEFAULT;
    return B8(sel) || W(XMP_FOBJ_PTR) || B8(MOV_ACTIVE);
}

/* What flash gets for slot i holding v >= 54: the stock function the slot held
 * before (the record's, else the last seen), else the stock default. */
static u32 qc_placeholder(const struct st *s, u32 i, u32 v)
{
    if (ours(s, v) && (s->rec_used >> i & 1u) && key_eq(s->rec_key[i], s->f[v - INT_BASE].key))
        return s->rec_ph[i];
    if (!ours(s, v) && (s->rec_used >> i & 1u)) return s->rec_ph[i];
    if (ours(s, v) && !foreign_id(s->last[i])) return s->last[i];
    return s->cfg->def[i];
}

/* The record into this sup's own BIN, in place (open 7 = overwrite without
 * truncating), then read back.  Never creates: the file must still be this
 * sup (its 48-byte header) -- sup-writeback-must-not-create. */
static u32 qc_write(struct st *s, const u32 *rec)
{
    const struct sl_svc *svc = s->svc;
    u32 fo = (u32)(uintptr_t)svc->uncached(svc, s->block + s->cfg->dma_off);
    u32 buf = fo + FO_BYTES, back = buf + 0x200u, ok = 0, got = 0;
    if (svc->file_is(svc, s->path, s->block, SL4_HEADER_LEN) != SL_OK) return 2;
    for (u32 i = 0; i < REC_WORDS; i++) W(buf + 4u * i) = rec[i];
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

/* After a save: the record as it should be now (ours, and orphans whose slot
 * still shows the placeholder); written only when it changed. */
static void qc_record(struct st *s, const u32 *was, const u32 *ph)
{
    u32 key[NSLOT][4], used = 0, same;
    for (u32 i = 0; i < NSLOT; i++) {
        key[i][0] = key[i][1] = key[i][2] = key[i][3] = 0;
        if (ours(s, was[i])) {
            for (u32 k = 0; k < 4u; k++) key[i][k] = s->f[was[i] - INT_BASE].key[k];
            used |= 1u << i;
        } else if ((s->rec_used >> i & 1u) && was[i] == s->rec_ph[i]) {
            u32 reg = 0;
            for (u32 j = 0; j < s->n; j++) if (key_eq(s->rec_key[i], s->f[j].key)) reg = 1;
            if (!reg) {                                   /* an orphan: its client is away */
                for (u32 k = 0; k < 4u; k++) key[i][k] = s->rec_key[i][k];
                used |= 1u << i;
            }
        }
    }
    same = used == s->rec_used;
    for (u32 i = 0; same && i < NSLOT; i++)
        if ((used >> i & 1u) && (!key_eq(key[i], s->rec_key[i]) || ph[i] != s->rec_ph[i])) same = 0;
    if (same) return;
    if (busy()) { s->busy_skips++; return; }
    u32 rec[REC_WORDS];
    rec[0] = REC_MAGIC; rec[1] = REC_VERSION;
    for (u32 i = 0; i < NSLOT; i++) {
        u32 *e = rec + 2u + 5u * i;
        for (u32 k = 0; k < 4u; k++) e[k] = key[i][k];
        e[4] = (used >> i & 1u) ? ph[i] : 0xFFFFFFFFu;
    }
    rec[REC_SUM] = fnv_words(rec, REC_SUM);
    u32 why = qc_write(s, rec);
    s->write_why = why;
    if (why) { s->write_fails++; return; }
    s->writes++;
    s->rec_used = used;
    for (u32 i = 0; i < NSLOT; i++) {
        for (u32 k = 0; k < 4u; k++) s->rec_key[i][k] = key[i][k];
        s->rec_ph[i] = (used >> i & 1u) ? ph[i] : 0xFFFFFFFFu;
    }
}

/* Replaces `bl FUN_c0088660(store, image)` (power-off save, shell `menu save`):
 * the image copied into the flash buffer holds no id >= 54. */
static USED u32 qc_save(u32 store, u32 image)
{
    struct st *s = qc_ctx();
    u32 was[NSLOT], ph[NSLOT], mask = 0, mine = image == STORE + STORE_IMG_A;
    s->saves++;
    for (u32 i = 0; i < NSLOT; i++) {
        was[i] = mine ? W(image + arr(i)) : 0;
        ph[i] = 0xFFFFFFFFu;
        if (mine && foreign_id(was[i])) {
            ph[i] = qc_placeholder(s, i, was[i]);
            W(image + arr(i)) = ph[i];
            mask |= 1u << i;
        }
    }
    u32 r = ((fn2)s->next_save)(store, image);
    for (u32 i = 0; i < NSLOT; i++)
        if (mask >> i & 1u) { W(image + arr(i)) = was[i]; s->sanitized++; }
    if (mine && s->phase == PH_READY) {
        for (u32 i = 0; i < NSLOT; i++)
            if (!(mask >> i & 1u) && (s->rec_used >> i & 1u)) ph[i] = s->rec_ph[i];
        qc_record(s, was, ph);
    }
    return r;
}

/* Replaces `bl FUN_c0061b08(settings, k)` in the RecommendedSetting getter:
 * its export table has no entry for >= 54 (FUN_c0548208 asserts and loops). */
static USED u32 qc_rec(u32 settings, u32 k)
{
    struct st *s = qc_ctx();
    u32 v = ((fn2)s->next_rec)(settings, k);
    if (!foreign_id(v)) return v;
    s->rec_hits++;
    u32 i = (k & 7u) + (((fn1)IS_CINE)(((fn0)SETTINGS_GET)()) == 1u ? 8u : 0u);
    return qc_placeholder(s, i, v);
}

/* Q4: replaces `bl FUN_c0062bb0(settings, volume, 1)` in the QS GUI's
 * CM_HeadphoneVolume callback.  The dial's headphone keyEvent stays on past
 * frame 48 (QS_CINE's FR/FL/BR/BL keys clips have no closing key), so on one
 * of our tiles it would change the volume: the setter is skipped then. */
static USED u32 qc_hp(u32 settings, u32 volume, u32 flag)
{
    struct st *s = qc_ctx();
    if (s->phase == PH_READY && ours_qs(s, W(((fn0)QS_STATE)() + QS_FOCUS))) { s->hp_blocks++; return 0; }
    return ((fn3)s->next_hp)(settings, volume, flag);
}

/* ===== C7: the record, read at collection ==================================== */
static void qc_rec_load(struct st *s)
{
    const u32 *r = (const u32 *)(s->block + s->cfg->rec_off);
    u32 tmp[REC_WORDS];
    for (u32 i = 0; i < REC_WORDS; i++) tmp[i] = r[i];
    s->rec_used = 0;
    if (tmp[0] != REC_MAGIC || tmp[1] != REC_VERSION || tmp[REC_SUM] != fnv_words(tmp, REC_SUM)) return;
    for (u32 i = 0; i < NSLOT; i++) {
        const u32 *e = tmp + 2u + 5u * i;
        for (u32 k = 0; k < 4u; k++) s->rec_key[i][k] = e[k];
        s->rec_ph[i] = e[4];
        if (e[0] && !foreign_id(e[4])) s->rec_used |= 1u << i;
    }
    s->rec_valid = 1;
}

static void qc_restore(struct st *s)
{
    u32 img = image_now();
    for (u32 i = 0; i < NSLOT; i++) {
        if (!(s->rec_used >> i & 1u)) continue;
        u32 j = QSC_MAX;
        for (u32 k = 0; k < s->n; k++) if (key_eq(s->rec_key[i], s->f[k].key)) j = k;
        u32 v = W(img + arr(i));
        if (v != s->rec_ph[i]) { s->stale++; s->rec_used &= ~(1u << i); continue; }  /* theirs now */
        if (j == QSC_MAX) { s->orphans++; continue; }                               /* client away */
        s->last[i] = v;
        W(img + arr(i)) = INT_BASE + j;
        s->restored++;
    }
}

static void qc_emit(struct st *s)
{
    u32 t0 = ((fn0)TICK_US)();
    s->emitted++;
    s->tm[11]++;
    u32 set = ((fn0)SETTINGS_GET)();
    if (((fn1)IS_CINE)(set) != 1u) return;
    for (u32 k = 0; k < 8u; k++) {
        ((fn3)POST_INT)(0, QS_NAME0 + 0x10u * k, qc_slot_ui(s, k));
    }
    if (!s->tm[7]) s->tm[6] += ((fn0)TICK_US)() - t0;               /* the first layout's write-backs */
}

/* ===== registration ============================================================ */
static const struct icon *icon_at(const struct st *s, u32 i)
{
    return (const struct icon *)(s->block + s->cfg->icons_off) + i;
}

static u32 icon_find(const struct st *s, const char *name)
{
    if (!name) return s->cfg->icon_default;
    for (u32 i = 0; i < s->cfg->n_icons; i++) {
        const char *a = icon_at(s, i)->name;
        u32 k = 0;
        while (k < ICON_NAME && a[k] && a[k] == name[k]) k++;
        if (k < ICON_NAME && !a[k] && !name[k]) return i;
    }
    return s->cfg->icon_default;
}

/* Labels are CSV text and a drawText string: printable ASCII, no , " { } and
 * not only digits (a numeric KEY is looked up in .nloc). */
static u32 label_ok(const char *l)
{
    u32 n = 0, digits = 1;
    if (!l) return 0;
    for (; n < QSC_LABEL && l[n]; n++) {
        char c = l[n];
        if (c < 0x20 || c > 0x7E || c == ',' || c == '"' || c == '{' || c == '}') return 0;
        if (c < '0' || c > '9') digits = 0;
    }
    return n && n < QSC_LABEL && !digits;
}

static int ptr_ok(const void *p) { u32 a = (u32)(uintptr_t)p; return a >= 0x40000000u && !(a & 3u); }
static int fn_ok(const void *p) { return !p || (u32)(uintptr_t)p >= 0x40000000u; }     /* 0, or code (Thumb: odd) */

/* The API 2 layout (magic QSF1): qsc_func without small / footer, qsc_sub without
 * icon / small / footer / lock.  A table of either is read into struct fx. */
struct qsc_sub2 { const char *label; const char *(*value)(void *); int (*adjust)(void *, int); void *arg; };
struct qsc_func2 {
    uint32_t sup_id; char name[QSC_NAME]; const char *label, *icon; uint32_t flags;
    const char *(*value)(void *); int (*adjust)(void *, int); int (*state)(void *);
    const struct qsc_subs *sub; void *arg;
};

static u32 name_ok(const char *n)                 /* a stock image name: 1..27 of [A-Za-z0-9_] */
{
    u32 k = 0;
    if (!n) return 1;
    if (!ptr_ok(n) && (u32)(uintptr_t)n < 0x40000000u) return 0;
    for (; k < ICON_NAME && n[k]; k++) {
        char c = n[k];
        if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_')) return 0;
    }
    return k && k < ICON_NAME;
}

/* A sub-QS: 1..6 items, each with a title like a function's label (it is drawn
 * as text), callbacks 0 or code, an icon 0 or a plain image name. */
static int subs_ok(const struct qsc_subs *b, u32 v3, u32 v4)
{
    if (!b) return 1;
    if (!ptr_ok(b) || !b->n || b->n > (v4 ? QSC_SUB_MAX : 6u) || !ptr_ok(b->item)) return 0;
    for (u32 j = 0; j < b->n; j++) {
        const struct qsc_sub *q = b->item + j;
        const struct qsc_sub2 *o = (const struct qsc_sub2 *)b->item + j;
        if (v3 ? (!label_ok(q->label) || !fn_ok(q->value) || !fn_ok(q->adjust) || !fn_ok(q->small) ||
                  !fn_ok(q->footer) || !fn_ok(q->lock) || !name_ok(q->icon) ||
                  (v4 ? !fn_ok(q->reserved) : q->reserved != 0))   /* API 6: blur() */
               : (!label_ok(o->label) || !fn_ok(o->value) || !fn_ok(o->adjust)))
            return 0;
    }
    return 1;
}

static void copy_name(char *d, const char *t, u32 cap)
{
    u32 k = 0;
    for (; t && k < cap - 1u && t[k]; k++) d[k] = t[k];
    for (; k < cap; k++) d[k] = 0;
}

static void qc_take(struct st *s, u32 sup_id, const struct qsc_table *t)
{
    u32 v3;
    if (!ptr_ok(t) || (t->magic != QSC_TABLE_MAGIC4 && t->magic != QSC_TABLE_MAGIC && t->magic != QSC_TABLE_MAGIC2) ||
        !t->n || t->n > QSC_MAX || !ptr_ok(t->f)) { s->bad++; return; }
    u32 v4 = t->magic == QSC_TABLE_MAGIC4;
    if (v4 && !fn_ok((const void *)t->leave)) { s->bad++; return; }
    v3 = t->magic == QSC_TABLE_MAGIC || v4;
    s->tables++;
    if (v4 && t->leave && s->n_leave < QSC_MAX) {
        s->leave_fn[s->n_leave] = (u32)(uintptr_t)t->leave;
        s->leave_arg[s->n_leave++] = (u32)(uintptr_t)t->leave_arg;
    }
    for (u32 i = 0; i < t->n; i++) {
        const struct qsc_func *q = t->f + i;
        const struct qsc_func2 *q2 = (const struct qsc_func2 *)t->f + i;
        if (!v3) q = (const struct qsc_func *)q2;          /* the common head is the same */
        u32 key[4] = {q->sup_id, 0, 0, 0}, nl = 0;
        if (q->sup_id != sup_id || !(q->flags & QSC_F_CINE) || !label_ok(q->label) || !fn_ok(q->value) ||
            !fn_ok(q->adjust) || !fn_ok(q->state) || !subs_ok(q->sub, v3, v4) ||
            (v3 && (!fn_ok(q->small) || !fn_ok(q->footer) || (v4 ? !fn_ok(q->reserved) : q->reserved != 0)))) {
            s->bad++; continue;                                  /* API 9: fine + sub on one function is allowed */
        }
        while (nl < QSC_NAME && q->name[nl]) nl++;
        if (!nl || nl == QSC_NAME) { s->bad++; continue; }
        for (u32 k = 0; k < nl; k++) ((u8 *)&key[1])[k] = (u8)q->name[k];
        u32 dup = 0;
        for (u32 j = 0; j < s->offered; j++) if (key_eq(s->f[j].key, key)) dup = 1;
        u32 go = (q->flags & QSC_GO_MASK) >> 8;                 /* API 7: a known target, fine() as the request */
        if (go && (!v4 || go != QSC_GO_READQR || !q->fine || q->sub)) { s->bad++; continue; }
        u32 repl = replacement(q->flags);
        if (repl != 0xFFFFFFFFu) {
            if (!v4 || (repl != 12u && repl != 21u && repl != 23u && repl != 25u)) { s->bad++; continue; }
            for (u32 j = 0; j < s->offered; j++) if (replacement(s->fx[j].flags) == repl) dup = 1;
        }
        if (dup) { s->bad++; continue; }
        if (s->offered == QSC_MAX) { s->full++; continue; }
        struct fn *f = &s->f[s->offered++];
        for (u32 k = 0; k < 4u; k++) f->key[k] = key[k];
        copy_name(f->label, q->label, QSC_LABEL);
        f->icon = icon_find(s, q->icon);
        struct fx *x = &s->fx[s->offered - 1u];
        x->flags = q->flags | (v4 ? FX_API4 : 0u);
        s->xfine[s->offered - 1u] = v4 ? (u32)(uintptr_t)q->fine : 0u;
        x->value = (u32)(uintptr_t)q->value;
        x->adjust = (u32)(uintptr_t)q->adjust;
        x->state = (u32)(uintptr_t)q->state;
        x->arg = (u32)(uintptr_t)q->arg;
        x->small = v3 ? (u32)(uintptr_t)q->small : 0u;
        x->footer = v3 ? (u32)(uintptr_t)q->footer : 0u;
        x->nsub = q->sub ? q->sub->n : 0u;
        for (u32 j = 0; j < x->nsub; j++) {
            const struct qsc_sub *b = q->sub->item + j;
            const struct qsc_sub2 *b2 = (const struct qsc_sub2 *)q->sub->item + j;
            if (!v3) b = (const struct qsc_sub *)b2;           /* label..arg: the same head */
            x->sv[j] = (u32)(uintptr_t)b->value;
            x->sa[j] = (u32)(uintptr_t)b->adjust;
            x->sarg[j] = (u32)(uintptr_t)b->arg;
            x->ssmall[j] = v3 ? (u32)(uintptr_t)b->small : 0u;
            x->sfoot[j] = v3 ? (u32)(uintptr_t)b->footer : 0u;
            x->slock[j] = v3 ? (u32)(uintptr_t)b->lock : 0u;
            copy_name(x->sl[j], b->label, QSC_LABEL);
            copy_name(x->sicon[j], v3 ? b->icon : 0, ICON_NAME);
            s->sblur[s->offered - 1u][j] = v4 ? (u32)(uintptr_t)b->reserved : 0u;   /* API 6 */
        }
    }
}

static void qc_collect(struct st *s)
{
    const struct sl_svc *svc = s->svc;
    struct sl_supinfo info;
    for (u32 i = 0; svc->sups_list(svc, i, &info) == SL_OK; i++) {
        if (info.status != SL_S_LOADED || info.id == QSC_ID) continue;
        const struct qsc_table *t = (const struct qsc_table *)svc->find(svc, QSC_TAG(info.id));
        if (t) qc_take(s, info.id, t);
    }
}

static int qc_zqs(const struct st *s)
{
    struct sl_supinfo info;
    for (u32 i = 0; s->svc->sups_list(s->svc, i, &info) == SL_OK; i++)
        if (info.id == ZQS_ID && info.status == SL_S_LOADED) return 1;
    return 0;
}

/* ===== C1: the editor's CSV rows ============================================== */
static u32 qc_table(const struct cfg *c)
{
    u32 w = W(FV_SITE), hw1 = w & 0xFFFFu, hw2 = w >> 16, sg, j1, j2, i1, i2, off;
    if ((hw1 & 0xF800u) != 0xF000u || (hw2 & 0xD000u) != 0x9000u) return 0;
    sg = (hw1 >> 10) & 1u; j1 = (hw2 >> 13) & 1u; j2 = (hw2 >> 11) & 1u;
    i1 = 1u ^ (j1 ^ sg); i2 = 1u ^ (j2 ^ sg);
    off = sg << 24 | i1 << 23 | i2 << 22 | (hw1 & 0x3FFu) << 12 | (hw2 & 0x7FFu) << 1;
    if (sg) off |= 0xFE000000u;
    u32 veneer = FV_SITE + 4u + off, entry, table;
    if (veneer & 3u || W(veneer) != VENEER_THUMB) return 0;
    entry = W(veneer + 4u);
    if (entry & 3u) return 0;
    table = W(entry - c->fv_entry + c->fv_table_word);
    return !table || (table & 3u) || W(table) != 0x56465346u ? 0 : table;
}

/* Rows of a CSV: line ends outside quotes, less the header line. */
static u32 csv_rows(uintptr_t p, u32 n)
{
    u32 lines = 0, q = 0;
    for (u32 i = 0; i < n; i++) {
        u8 c = B8(p + i);
        if (c == '"') q ^= 1u;
        else if (c == '\n' && !q) lines++;
    }
    return lines ? lines - 1u : 0;
}

/* The first two CSV columns are numeric, even if the memo contains quoted
 * commas/newlines. Return a zero-based stock editor row, never an unseen id. */
static u32 csv_ui_row(uintptr_t p, u32 n, u32 ui)
{
    u32 start = 0, line = 0, quoted = 0;
    for (u32 end = 0; end < n; end++) {
        u8 c = B8(p + end);
        if (c == '"') quoted ^= 1u;
        if (c != '\n' || quoted) continue;
        if (line) {
            u32 at = start, val = 0, digits = 0;
            while (at < end && B8(p + at) != ',') at++;
            for (at++; at < end && B8(p + at) >= '0' && B8(p + at) <= '9'; at++) { val = val * 10u + B8(p + at) - '0'; digits++; }
            if (digits && at < end && B8(p + at) == ',' && val == ui) return line - 1u;
        }
        line++; start = end + 1u;
    }
    return 0u;   /* a hidden legacy id on an unsupported twin list: a valid row */
}

static u32 put_dec(uintptr_t p, u32 v)
{
    u32 n = 0, started = 0;
    for (u32 d = 1000u;; ) {
        u32 digit = 0;
        while (v >= d) { v -= d; digit++; }
        if (digit || started || d == 1u) { B8(p + n++) = (u8)('0' + digit); started = 1; }
        if (d == 1u) break;
        d = d == 1000u ? 100u : d == 100u ? 10u : 1u;
    }
    return n;
}

static u32 put_str(uintptr_t p, const char *t, u32 max)
{
    u32 n = 0;
    while (n < max && t[n]) { B8(p + n) = (u8)t[n]; n++; }
    return n;
}

/* `NO,ID,IMAGE,KEY,memo` for function i: KEY is the label itself (the list's
 * .nloc lookup falls back to the text, camera 2026-10-28). */
static u32 csv_row(const struct st *s, uintptr_t p, u32 no, u32 i)
{
    u32 n = put_dec(p, no);
    B8(p + n++) = ',';
    n += put_dec(p + n, UI_BASE + i);
    B8(p + n++) = ',';
    n += put_str(p + n, icon_at(s, s->f[i].icon)->name, ICON_NAME);
    B8(p + n++) = ',';
    n += put_str(p + n, s->f[i].label, QSC_LABEL);
    B8(p + n++) = ','; B8(p + n++) = 'S'; B8(p + n++) = '\r'; B8(p + n++) = '\n';
    return n;
}

/* Each CSV: a new copy of whatever the table holds now (stock, or another
 * sup's copy) with our rows after its rows.  Built first (the pages need each
 * list's row count), committed last, the way uishare does: a new entry is
 * filled before the count, a known one gets the pointer before the length. */
struct rows { u32 table, cnt, buf[NCSV], len[NCSV], at[NCSV], stock[NCSV]; };

static u32 qc_csv_build(struct st *s, u32 n, struct rows *w)
{
    const struct cfg *c = s->cfg;
    w->table = qc_table(c);
    if (!w->table) return 1;
    w->cnt = W(w->table + 8);
    if (w->cnt > W(w->table + 12)) return 2;
    for (u32 f = 0; f < NCSV; f++) {
        u32 copy = c->csv_stock[f], size = c->csv_size[f];
        w->at[f] = w->cnt;
        w->stock[f] = c->csv_stock[f];
        for (u32 e = 0; e < w->cnt; e++)
            if (W(w->table + 16u + 12u * e) == c->csv_stock[f]) {
                copy = W(w->table + 20u + 12u * e); size = W(w->table + 24u + 12u * e); w->at[f] = e;
            }
        if (!copy || size > 0x10000u) return 3;
        uintptr_t b = fst_alloc(size + 2u + 64u * n);
        if (!b) return 4;
        fst_move(b, copy, size);
        u32 len = size;
        if (len < 2u || B8(b + len - 1u) != '\n') { B8(b + len++) = '\r'; B8(b + len++) = '\n'; }
        u32 rows = csv_rows(b, len);
        if (rows + editor_count(s, n) > 99u) return 5;      /* the total count has two digits */
        s->csv_rows[f] = rows;
        u32 added = 0;
        for (u32 i = 0; i < n; i++) {
            u32 repl = replacement(s->fx[i].flags);
            if (repl != 0xFFFFFFFFu) s->editor_row[f][i] = csv_ui_row(b, len, ((fn2)TO_UI)(CONV, repl));
            else {
                s->editor_row[f][i] = rows + added;
                len += csv_row(s, b + len, rows + 1u + added, i);
                added++;
            }
        }
        w->buf[f] = b; w->len[f] = len;
    }
    u32 fresh = 0;
    for (u32 f = 0; f < NCSV; f++) fresh += w->at[f] == w->cnt;
    return w->cnt + fresh > W(w->table + 12) ? 6 : 0;
}

static void qc_csv_commit(const struct rows *w)
{
    u32 table = w->table;
    fst_publish();
    for (u32 f = 0; f < NCSV; f++) {
        if (w->at[f] == w->cnt) {
            u32 e = W(table + 8);
            W(table + 20u + 12u * e) = w->buf[f];
            W(table + 24u + 12u * e) = w->len[f];
            W(table + 16u + 12u * e) = w->stock[f];
            fst_publish();
            W(table + 8) = e + 1u;
        } else {
            W(table + 20u + 12u * w->at[f]) = w->buf[f];
            fst_publish();
            W(table + 24u + 12u * w->at[f]) = w->len[f];
        }
        fst_publish();
    }
}

/* ===== E2-E5: the editor pages, one streaming copy each ======================== */
static void cp(uintptr_t to, uintptr_t from, u32 n)
{
    if (!((to ^ from) & 3u)) {
        while (n && (to & 3u)) { B8(to++) = B8(from++); n--; }
        for (; n >= 4u; n -= 4u, to += 4u, from += 4u) W(to) = W(from);
    } else if (!((to ^ from) & 1u)) {
        while (n && (to & 1u)) { B8(to++) = B8(from++); n--; }
        for (; n >= 2u; n -= 2u, to += 2u, from += 2u)
            *(volatile u16 *)to = *(volatile const u16 *)from;
    }
    while (n--) B8(to++) = B8(from++);
}

static u32 sel_value(const struct st *s, u32 sel, u32 fi, u32 row0, u32 csv, u32 n)
{
    u32 v = 0, blank = (u32)(uintptr_t)(s->block + s->cfg->blank_off) - SL_ALIAS;
    if (sel == S_BLANK) return blank;
    if (fi >= n) return sel == S_TITLE ? blank : 0;
    u32 title = s->fx[fi].flags & QSC_F_TITLE;
    if (sel == S_TITLE) return title ? label_id(&s->f[fi]) : blank;   /* v0.3.6: the tile's text title */
    const struct icon *ic = icon_at(s, s->f[fi].icon);
    if (title && (sel == S_RECT || sel == S_SIZE)) return 0;           /* no borrowed icon (the QS page's rule) */
    if (sel == S_IMAGE) return ic->image;
    if (sel == S_RECT) return ic->rect;
    if (sel == S_SIZE) return ic->size;
    if (sel == S_POS) return ic->pos;
    if (sel == S_ROW) { (void)row0; fst_int_to_f32((int32_t)s->editor_row[csv][fi], &v); return v; }
    if (sel == S_LABEL) return label_id(&s->f[fi]);
    return 0;
}

struct src { uintptr_t base, deltas; u32 len, n_deltas, next_id, counters[UIA_COUNTERS][2]; };

static u32 src_at(const struct src *r, u32 pos)
{
    u32 c = pos;
    for (u32 i = 0; i < r->n_deltas; i++) if (W(r->deltas + 8u * i) <= pos) c += W(r->deltas + 8u * i + 4u);
    return c;
}

/* One page: stock -> copy with our edits, or another sup's FSPG copy -> a
 * copy of that with ours on top (their deltas kept, ours after them). */
static u32 qc_page(struct st *s, u32 p, u32 n, u32 row0)
{
    const struct cfg *c = s->cfg;
    uintptr_t reader = fst_reader(), e;
    struct src r;
    if (!reader || !(e = fst_find_entry(reader, (uintptr_t)(s->block + c->page_name_off[p]), c->page_name_len[p])))
        return 1;
    u32 off = W(e + ENTRY_OFFSET);
    r.base = NBU_BASE + off;
    for (u32 i = 0; i < UIA_COUNTERS; i++) r.counters[i][0] = r.counters[i][1] = 0;
    if (off == c->page_entry[p]) {
        r.len = c->page_len[p]; r.deltas = 0; r.n_deltas = 0; r.next_id = 1;
    } else {
        uintptr_t h = (r.base & ~3u) - UIA_HEADER;
        if (W(h) != UIA_MAGIC || W(h + 4) != UIA_VERSION || W(h + 16) != c->page_len[p]) return 2;
        r.len = W(h + 12); r.next_id = W(h + 20); r.n_deltas = W(h + 24); r.deltas = W(h + 32);
        for (u32 i = 0; i < UIA_COUNTERS; i++) { r.counters[i][0] = W(h + 36 + 8 * i); r.counters[i][1] = W(h + 40 + 8 * i); }
    }
    const struct edit *ed = (const struct edit *)(s->block + c->edits_off[p]);
    u32 ne = c->n_edits[p], dcap = r.n_deltas + c->page_ins_max[p] / 10u + 1u;
    u32 cap = r.len + c->page_ins_max[p];
    uintptr_t blk = fst_alloc(8u * dcap + UIA_HEADER + 4u + cap);
    if (!blk || (blk & 7u)) return 3;
    uintptr_t deltas = blk, out = blk + 8u * dcap + UIA_HEADER + (r.base & 3u);
    u32 nd = r.n_deltas, in = 0, o = 0, mask = n >= 32u ? 0xFFFFFFFFu : (1u << n) - 1u;
    for (u32 i = 0; i < nd; i++) { W(deltas + 8u * i) = W(r.deltas + 8u * i); W(deltas + 8u * i + 4u) = W(r.deltas + 8u * i + 4u); }
    u32 last_pos = 0xFFFFFFFFu, frag_o = 0xFFFFFFFFu, frag_len = 0;
    for (u32 k = 0; k < ne; k++) {
        const struct edit *x = ed + k;
        if (x->fi != 0xFFu && x->fi >= n) continue;
        u32 at = src_at(&r, x->pos);
        if (x->kind == K_FPATCH) {                                   /* into the fragment just inserted */
            if (frag_o == 0xFFFFFFFFu || x->a + 4u > frag_len) return 9;
            wr_be(out + frag_o + x->a, sel_value(s, x->sel, x->b, row0, c->page_csv[p], n));
            continue;
        }
        if (x->kind == K_INS || x->kind == K_FRAG) {
            u32 len = x->kind == K_INS ? 10u : x->b;
            if (at < in || at > r.len || o + (at - in) + len > cap) return 4;
            cp(out + o, r.base + in, at - in); o += at - in; in = at;
            if (x->kind == K_INS) {
                B8(out + o) = 0; B8(out + o + 1u) = 0;
                wr_be(out + o + 2u, c->t_of[x->fi]);
                wr_be(out + o + 6u, sel_value(s, x->sel, x->fi, row0, c->page_csv[p], n));
            } else {
                cp(out + o, (uintptr_t)(s->block + x->a), len);
                frag_o = o; frag_len = len;
            }
            o += len;
            if (last_pos == x->pos) W(deltas + 8u * (nd - 1u) + 4u) += len;
            else { W(deltas + 8u * nd) = x->pos; W(deltas + 8u * nd + 4u) = len; nd++; last_pos = x->pos; }
            continue;
        }
        u32 w = x->kind == K_SETFLAG ? 2u : 4u;
        if (at + w > r.len) return 4;
        if (at + w > in) { cp(out + o, r.base + in, at + w - in); o += at + w - in; in = at + w; }
        if (in - at > o) return 4;
        uintptr_t q = out + o - (in - at);
        u32 v = w == 2u ? ((u32)B8(q) << 8 | B8(q + 1u)) : rd_be(q);
        if (x->kind != K_ADJ && x->kind != K_ADDC && v != x->a) return 5;   /* not the bytes this was built for */
        if (x->kind == K_ADDF_N) {
            int32_t iv;
            u32 count = x->b ? editor_count(s, n) : n;             /* list rows versus stable dynamic id range */
            if (!fst_f32_to_int(v, &iv) || !fst_int_to_f32(iv + (int32_t)count, &v)) return 6;
            wr_be(q, v);
        } else if (x->kind == K_SET_END) {
            if (n) wr_be(q, c->t_of[n - 1u]);
        } else if (x->kind == K_ADJ) {
            wr_be(q, v + x->b * popcount(x->a & mask));
        } else if (x->kind == K_ADDC) {
            wr_be(q, v + x->b);
        } else if (x->kind == K_SETV) {
            wr_be(q, sel_value(s, x->sel, x->fi, row0, c->page_csv[p], n));
        } else if (x->kind == K_SETFLAG) {
            B8(q) = 0; B8(q + 1u) = 0;
        } else if (x->kind == K_DIGIT) {
            if (n) {
                u32 total = row0 + editor_count(s, n), tens = 0;
                while (total >= 10u) { total -= 10u; tens++; }
                if (tens > 9u) return 6;
                wr_be(q, c->digit[x->sel ? total : tens]);
            }
        } else {
            return 7;
        }
    }
    cp(out + o, r.base + in, r.len - in); o += r.len - in;
    if (o > cap) return 8;
    uintptr_t h = (out & ~3u) - UIA_HEADER;
    W(h + 0) = UIA_MAGIC; W(h + 4) = UIA_VERSION; W(h + 8) = cap; W(h + 12) = o;
    W(h + 16) = c->page_len[p]; W(h + 20) = r.next_id; W(h + 24) = nd; W(h + 28) = dcap; W(h + 32) = deltas;
    for (u32 i = 0; i < UIA_COUNTERS; i++) { W(h + 36 + 8 * i) = r.counters[i][0]; W(h + 40 + 8 * i) = r.counters[i][1]; }
    for (u32 a = 36u + 8u * UIA_COUNTERS; a < UIA_HEADER; a += 4u) W(h + a) = 0;
    s->page_at[p] = out; s->page_bytes[p] = o;
    fst_publish();
    W(e + ENTRY_OFFSET) = out - NBU_BASE;
    fst_publish();
    return 0;
}


/* ===== Q: the QS page (QS_CINE) through the C05E6400 record layer ============= */
static const char *qc_name(const struct st *s, u32 k)
{
    return (const char *)(s->block + s->cfg->names_off + NAME_BYTES * k);
}
/* a private string's id: its address at the uncached alias (the core resolves it) */
static u32 qc_name_id(const struct st *s, u32 k) { return (u32)(uintptr_t)qc_name(s, k) - SL_ALIAS; }
static const char *qc_blank(const struct st *s) { return (const char *)(s->block + s->cfg->blank_off); }
static const struct qt *qt_at(const struct st *s, u32 i)
{
    return (const struct qt *)(s->block + s->cfg->qs_off) + i;
}
static u32 fnv_bytes(uintptr_t p, u32 n)
{
    u32 h = 2166136261u;
    for (u32 i = 0; i < n; i++) h = (h ^ B8(p + i)) * 16777619u;
    return h;
}

static u32 qc_patch_value(const struct st *s, u32 kind, u32 arg, u32 n, u32 *v)
{
    if (kind == P_STR) {
        if (arg >= N_NAMES) return 0;
        *v = qc_name_id(s, arg);
        return 1;
    }
    if (kind == P_GO) {                                   /* v0.3.7: the go request text's private id */
        if (arg) return 0;
        *v = (u32)(uintptr_t)(s->block + s->cfg->go_text_off) - SL_ALIAS;
        return 1;
    }
    if (kind == P_LOOK) {
        u32 fi = arg >> 2, sel = arg & 3u;
        if (fi >= QSC_MAX) return 0;
        u32 icon = fi < n ? s->f[fi].icon : s->cfg->icon_default;
        *v = ((const u32 *)(s->block + s->cfg->looks_off))[4u * icon + sel];
        /* v0.2.3: a function with a text title draws no icon (width / height 0, as the sub-QS tiles) */
        if (fi < n && (s->fx[fi].flags & QSC_F_TITLE) && (sel == 1u || sel == 2u)) *v = 0;   /* LOOK_RECT, LOOK_SIZE */
        return 1;
    }
    return 0;
}

/* One target: the stock record at `src` (length and FNV checked) through its
 * ops (qs_page_data.apply_table is the reference), into `out`.  0 = good. */
static u32 qc_qs_one(const struct st *s, const struct qt *t, uintptr_t src, uintptr_t out, u32 n)
{
    const struct cfg *c = s->cfg;
    const u8 *tab = s->block + c->qs_off;
    const struct qop *op = (const struct qop *)(tab + c->qs_ops_off) + t->op_first;
    uintptr_t frags = (uintptr_t)(tab + c->qs_frags_off);
    u32 p = 0, o = 0, grow = 0, sized = 0;
    if (rd_be(src + 4u) != t->len || fnv_bytes(src, t->len) != t->fnv) return 1;
    for (u32 j = 0; j < t->op_n; j++, op++) {
        u32 at = op->at;
        if (op->kind == Q_INS || op->kind == Q_APP) {
            if (at > t->len || at < p) return 2;
            if (op->kind == Q_APP && !sized) {
                cp(out + o, src + p, t->len - p); o += t->len - p; p = t->len;
                wr_be(out + 4u, t->len + grow);
                sized = 1;
            }
            cp(out + o, src + p, at - p); o += at - p; p = at;
            cp(out + o, frags + op->b, op->a); o += op->a;
            if (op->kind == Q_INS) grow += op->a;
            continue;
        }
        if ((op->kind != Q_SET && op->kind != Q_ADD) || at + 4u > t->len || sized) return 3;
        if (p < at + 4u) {
            if (at + 4u - p > t->len) return 3;
            cp(out + o, src + p, at + 4u - p); o += at + 4u - p; p = at + 4u;
        }
        uintptr_t q = out + o - (p - at);
        wr_be(q, op->kind == Q_SET ? op->a : rd_be(q) + op->a);
    }
    if (!sized) {
        cp(out + o, src + p, t->len - p); o += t->len - p;
        wr_be(out + 4u, t->len + grow);
    }
    if (o != t->out_len) return 4;
    const struct qpatch *pt = (const struct qpatch *)(tab + c->qs_patches_off) + t->patch_first;
    for (u32 j = 0; j < t->patch_n; j++, pt++) {
        u32 v;
        if (pt->out + 4u > t->out_len || !qc_patch_value(s, pt->kind, pt->arg, n, &v)) return 5;
        wr_be(out + pt->out, v);
    }
    u32 cur = 0, k = 0;
    while (cur < t->out_len) {
        u32 sz = rd_be(out + cur + 4u);
        if (sz < 8u || cur + sz > t->out_len) return 6;
        cur += sz; k++;
    }
    return k == t->n_out ? 0 : 6;
}

/* At collection: every target's output, once (they stay: the parser may keep
 * pointers into a record), then the variables.  0 = the layer is good. */
static u32 qc_qs_build(struct st *s, u32 n)
{
    const struct cfg *c = s->cfg;
    if (!c->qs_n || c->qs_n > QT_MAX) return 1;
    uintptr_t reader = fst_reader(), e;
    if (!reader || !(e = fst_find_entry(reader, (uintptr_t)(s->block + c->qs_page_name_off), c->qs_page_name_len)))
        return 2;
    if (W(e + ENTRY_OFFSET) != c->qs_page_entry) { s->qs_entry_bad = W(e + ENTRY_OFFSET); return 3; }
    uintptr_t buf = fst_alloc(c->qs_out_total + 8u);
    if (!buf) return 4;
    u32 at = 0;
    for (u32 i = 0; i < c->qs_n; i++) {
        const struct qt *t = qt_at(s, i);
        if (i && t->pos <= qt_at(s, i - 1u)->pos) return 5;          /* sorted: the hook bisects */
        if (t->pos + t->len > c->qs_page_len || at + t->out_len > c->qs_out_total) return 5;
        u32 r = qc_qs_one(s, t, NBU_BASE + c->qs_page_entry + t->pos, buf + at, n);
        if (r) return 16u + (i << 8) + r;
        s->qs_out[i] = buf + at;
        at += t->out_len;
    }
    uintptr_t app = W(GUI_OBJECT);
    if (!app || (app & 3u)) return 6;
    for (u32 k = 0; k < N_NAMES; k++) {
        u32 text = !(k == S_KEY || k - S_G < 8u || k == S_FB || k == S_ARW || k - S_LW < 8u || k - S_SW < 8u ||
                     k == S_GO || k == S_DHB), def[3];
        def[0] = text ? VAR_TEXT : 0u;
        def[1] = (u32)(uintptr_t)qc_name(s, k);
        def[2] = text ? (u32)(uintptr_t)qc_blank(s) : k == S_FB ? BOX_NONE : 0u;
        if (((fn3)VAR_REGISTER)((u32)app, 1u, (u32)(uintptr_t)def)) return 7;
        s->qs_vars++;
    }
    fst_publish();
    return 0;
}

static u32 qt_find(const struct st *s, u32 rel)
{
    u32 lo = 0, hi = s->cfg->qs_n;
    while (lo < hi) {
        u32 mid = (lo + hi) >> 1, p = qt_at(s, mid)->pos;
        if (p == rel) return mid;
        if (p < rel) lo = mid + 1u; else hi = mid;
    }
    return QT_MAX;
}

/* C05E6400(reader): a target record of the stock QS_CINE is parsed from its
 * output instead -- one or more records, then base and position back the way
 * the firmware expects (past the stock record).  Anything else: the next layer. */
static USED u32 qc_qsrec(u32 reader)
{
    struct st *s = qc_ctx();
    fn1 next = (fn1)s->next_qsrec;
    if (!s->qs_ready) return next(reader);
    u32 base = W(reader + R_BASE), pos = W(reader + R_POS), rel = pos - s->cfg->qs_page_entry;
    if (rel >= s->cfg->qs_page_len) return next(reader);
    u32 i = qt_find(s, rel);
    if (i == QT_MAX) return next(reader);
    if (base != NBU_BASE) { s->qs_foreign++; return next(reader); }  /* another layer's copy */
    const struct qt *t = qt_at(s, i);
    uintptr_t out = s->qs_out[i];
    u32 cur = 0, res = 0;
    W(reader + R_BASE) = out - pos;
    while (cur < t->out_len) {
        W(reader + R_POS) = pos + cur;
        res = next(reader);
        cur += rd_be(out + cur + 4u);
    }
    W(reader + R_BASE) = base;
    W(reader + R_POS) = pos + t->len;
    s->qs_hits++;
    return res;
}

/* The displaced first instruction of FUN_c05e6400, then the rest of it. */
__attribute__((naked)) static void qc_qsrec_stock(void)
{
    __asm__ volatile("push.w {r4, r5, r6, r7, r8, r9, r10, r11, lr}\n\t"
                     "ldr.w pc, 1f\n\t"
                     ".balign 4\n"
                     "1:\t.word 0xC05E6405\n");
}

/* After a layout load, once per boot: the QS layout the resource cache parsed
 * before the layer was up is let go (v3 with the cache, then v2) so the next
 * QS open parses it through us.  res-custom ogc_qslay's rule (after the v5c
 * freeze): never while it is the one loading, only when the cache holds it alone. */
static int qc_releasable(u32 l)
{
    u32 tree = W(l + 0xCu), ctx = W(l + 4u);
    return tree && B8(RCACHE + 0x28u) == 0 && W(tree + 0xCu) == 1u && ctx && W(ctx + 0x84Cu) != l &&
           W(ctx + 0x848u) != l;
}
static void qc_release(struct st *s, u32 layout)
{
    if (!s->qs_ready || s->qs_boot || s->qs_inreload) return;
    u32 held = W(RCACHE + 4u);
    if (!held || held != s->qs_pre) { s->qs_boot = 1; s->qs_fresh++; return; }  /* not cached: parsed through us anyway */
    if (held == layout || !qc_releasable(held)) return;             /* later */
    s->qs_boot = 1;
    s->qs_inreload = 1;
    ((fn1)RCACHE_V3)(RCACHE);
    ((fn1)RCACHE_V2)(RCACHE);
    s->qs_inreload = 0;
    s->qs_reloads++;
}

/* ---- the tiles' texts, the footer, the dials, AEL, MENU --------------------------------- */
static u32 qc_locked(const struct st *s, u32 i)
{
    const struct fx *x = &s->fx[i];
    if ((x->flags & QSC_F_LOCK_REC) && busy()) return 1;
    return x->state && ((int (*)(void *))x->state)((void *)(uintptr_t)x->arg) ? 1u : 0u;
}

/* A text into `d` (cap bytes): printable ASCII and UTF-8 kept, control bytes '?'.
 * FONT_BIG / FONT_SMALL: every character the stock bold glyph set has (digits,
 * A-Z, . : - / + % # x ...: the config's table) becomes its inline image
 * "<!font_menu_LB_..,CENTER>" -- the glyphs the stock values are drawn with;
 * the rest stays text in the same line.  Never empty (" "). */
static u32 qc_put(char *d, u32 n, u32 cap, const char *t)
{
    while (*t && n < cap - 1u) d[n++] = *t++;
    return n;
}
static void qc_expand(const struct st *s, char *d, u32 cap, const char *t, u32 font)
{
    const u32 *glyph = (const u32 *)(s->block + s->cfg->glyph_off);
    u32 n = 0, i = 0;
    while (t && t[i] && n < cap - 1u) {
        u8 c = (u8)t[i];
        u32 g = 0, used = 1;
        if (c == '[') font = FONT_PLAIN;              /* v0.2.4: "3[1,2,1]" -> bold 3, the bracket part thin */
        if (c == 0xC3u && (u8)t[i + 1] == 0x97u) { g = N_GLYPH - 1u; used = 2; }   /* U+00D7 */
        else if (c < 0x80u) g = c;
        else g = 0xFFFFFFFFu;
        u32 off = font != FONT_PLAIN && g != 0xFFFFFFFFu ? glyph[(font - 1u) * N_GLYPH + g] : 0u;
        if (off) {
            const char *m = (const char *)(s->block + off);
            u32 len = 0;
            while (m[len]) len++;
            if (n + len >= cap - 1u) break;
            n = qc_put(d, n, cap, m);
            i += used;
            continue;
        }
        d[n++] = (c >= 0x20u && c != 0x7Fu) ? (char)c : '?';
        i++;
    }
    if (!n) d[n++] = ' ';
    d[n] = 0;
}

/* `t` into the double buffer `buf` (the GUI keeps the pointer it was given),
 * posted to variable `var` only when it changed. */
static void qc_post_buf(struct st *s, u32 var, char *buf, u32 cap, u32 *sel, const char *t)
{
    char *cur = buf + cap * *sel;
    u32 i = 0;
    while (i < cap && t[i] == cur[i] && t[i]) i++;
    if (i < cap && t[i] == cur[i]) return;                       /* unchanged */
    *sel ^= 1u;
    cur = buf + cap * *sel;
    for (i = 0; i < cap; i++) { cur[i] = t[i]; if (!t[i]) break; }
    ((fn3)POST_STR)(0, (u32)(uintptr_t)qc_name(s, var), (u32)(uintptr_t)cur);
    s->posts++;
}

static u32 qc_chars(const char *t)                   /* UTF-8 characters */
{
    u32 n = 0;
    for (u32 i = 0; t[i]; i++) n += ((u8)t[i] & 0xC0u) != 0x80u;
    return n;
}

/* v0.2.4: the footer's small plain font, a character's advance (px, measured on live screenshots: digits 9,
 * capitals 10, lower case 8, "→" 18).  No table: -fropi .text only. */
static u32 qc_small_w(const char *t)
{
    u32 w = 0;
    for (u32 i = 0; t && t[i]; i++) {
        u8 c = (u8)t[i];
        if (c >= '0' && c <= '9') w += 9u;
        else if (c >= 'A' && c <= 'Z') w += c == 'I' ? 4u : (c == 'M' || c == 'W') ? 13u : 10u;
        else if (c >= 'a' && c <= 'z') w += (c == 'i' || c == 'l' || c == 'j') ? 4u :
                                              (c == 'f' || c == 't' || c == 'r') ? 5u : (c == 'm' || c == 'w') ? 12u : 8u;
        else if (c == ' ') w += 6u;
        else if (c == '.' || c == ',' || c == ':' || c == ';') w += 4u;
        else if (c == '[' || c == ']' || c == '(' || c == ')' || c == '/' || c == '|') w += 5u;
        else if (c == 0xE2u && (u8)t[i + 1] == 0x86u && (u8)t[i + 2] == 0x92u) { w += 18u; i += 2u; }   /* U+2192 */
        else if (c == 0xC2u && (u8)t[i + 1] == 0xB7u) { w += 5u; i++; }                                   /* U+00B7 */
        else if (c == 0xC3u && (u8)t[i + 1] == 0x97u) { w += 9u; i++; }                                   /* U+00D7 */
        else if ((c & 0xC0u) == 0x80u) continue;                                                           /* tail */
        else w += c >= 0xC0u ? 14u : 8u;
    }
    return w;
}

/* v0.2.2: the bold glyphs' width of a value (px), the plain characters counted as the widest glyph */
static u32 qc_value_width(const struct st *s, const char *t)
{
    const u8 *gw = s->block + s->cfg->gwidth_off;
    u32 w = 0;
    for (u32 i = 0; t && t[i]; i++) {
        u8 c = (u8)t[i];
        if (c == 0xC3u && (u8)t[i + 1] == 0x97u) { w += gw[N_GLYPH - 1u]; i++; continue; }
        if (c == '[') return w + 22u * qc_chars(t + i);   /* v0.2.4: the bracket part is plain (~22 px a character) */
        w += c < 0x80u && gw[c] ? gw[c] : 40u;
    }
    return w;
}

static void qc_post_text(struct st *s, u32 k, u32 role, const char *t, u32 font)
{
    char tmp[TXT_BYTES];
    u32 var = role == R_L ? S_L : role == R_V ? S_V : role == R_S ? S_S : S_Y;
    if (font == FONT_BIG && qc_value_width(s, t) > VALUE_W) font = FONT_PLAIN;   /* live 3: CUSTOM filled the tile */
    qc_expand(s, tmp, TXT_BYTES, t, font);
    qc_post_buf(s, var + k, &s->txt[k][role][0][0], TXT_BYTES, &s->t_sel[k][role], tmp);
}

static const char *qc_call_text(const struct st *s, u32 fnp, u32 arg)
{
    const char *t = fnp ? ((const char *(*)(void *))fnp)((void *)(uintptr_t)arg) : 0;
    return t ? t : qc_blank(s);
}

static const char *qc_call_small(const struct st *s, u32 fnp, u32 arg, u32 *approx)
{
    u32 fl = 0;
    const char *t = fnp ? ((const char *(*)(void *, u32 *))fnp)((void *)(uintptr_t)arg, &fl) : 0;
    *approx = fl & QSC_T_APPROX;
    return t ? t : qc_blank(s);
}

/* "<!name,CENTER>" for a stock image name (a sub-item's icon, the open function's look). */
static void qc_markup(const struct st *s, char *d, u32 cap, const char *name)
{
    u32 n = qc_put(d, 0, cap, (const char *)(s->block + s->cfg->mk_open_off));
    n = qc_put(d, n, cap, name);
    n = qc_put(d, n, cap, (const char *)(s->block + s->cfg->mk_close_off));
    d[n] = 0;
}

/* The eight tiles' UI ids: the user's layout (the CINE set), or the sub-QS. */
static u32 qc_tile_ids(const struct st *s, u32 *ui)
{
    if (s->sub_open >= 0 || s->standalone) {
        for (u32 k = 0; k < 8u; k++) ui[k] = s->sub_tile[k];
        return 1;
    }
    u32 set = ((fn0)SETTINGS_GET)();
    if (((fn1)IS_CINE)(set) != 1u) return 0;
    for (u32 k = 0; k < 8u; k++) ui[k] = qc_slot_ui(s, k);
    return 1;
}

/* What an internal id on the QS page is: a function (54+i), the open function
 * on tile 1 (70), a sub-item (71+j); -1 = stock / blank. */
static int32_t qc_fn_of(const struct st *s, u32 id, int32_t *item)
{
    *item = -1;
    id = qc_qs_id(s, id);
    if (id - INT_BASE < s->n) return (int32_t)(id - INT_BASE);
    if (s->sub_open < 0) return -1;
    if (id == INT_MAIN) return s->sub_open;
    if (id - INT_ITEM0 < s->fx[s->sub_open].nsub) { *item = (int32_t)(id - INT_ITEM0); return s->sub_open; }
    return -1;
}

static void qc_texts(struct st *s)
{
    u32 ui[8];
    char mk[64];
    if (!qc_tile_ids(s, ui))
        for (u32 k = 0; k < 8u; k++) ui[k] = 0;
    for (u32 k = 0; k < 8u; k++) {
        const char *l = qc_blank(s), *v = qc_blank(s), *sm = qc_blank(s);
        u32 g = 0, approx = 0, lock_width = 0, small_lock_width = 0, lfont = FONT_PLAIN, vfont = FONT_BIG, id = ui[k] + (INT_BASE - UI_BASE);
        int32_t item, i = ui[k] >= UI_BASE ? qc_fn_of(s, id, &item) : -1;
        if (i >= 0) {
            const struct fx *x = &s->fx[i];
            g = qc_locked(s, (u32)i);
            if (item < 0) {
                v = qc_call_text(s, x->value, x->arg);
                sm = qc_call_small(s, x->small, x->arg, &approx);
                if (x->flags & QSC_F_TITLE) l = s->f[i].label;   /* API 4: the label as the title, no icon */
                else if (id == INT_MAIN && (x->flags & FX_API4)) l = s->f[i].label;   /* live 3: the inline look sat off centre */
                else if (id == INT_MAIN) {                    /* tile 1 of the sub-QS: the function's look */
                    const u32 *lk = (const u32 *)(s->block + s->cfg->looks_off) + 4u * s->f[i].icon;
                    qc_markup(s, mk, sizeof mk, (const char *)(uintptr_t)(s->cfg->pool_base + lk[0]));
                    l = mk;
                }
            } else {
                u32 j = (u32)item;
                v = qc_call_text(s, x->sv[j], x->sarg[j]);
                sm = qc_call_small(s, x->ssmall[j], x->sarg[j], &approx);
                l = x->sl[j];
                if (x->slock[j]) {
                    int lk = ((int (*)(void *))x->slock[j])((void *)(uintptr_t)x->sarg[j]);
                    const char *ic = (const char *)(s->block + s->cfg->lock_off[lk == QSC_LOCK_SHUT]);
                    if (lk == QSC_LOCK_TITLE_OPEN || lk == QSC_LOCK_TITLE_SHUT) {
                        /* The native QS padlock fits above the value; no icon when unlocked.
                         * Opt-in leaves existing API 3/4 key-icon clients unchanged. */
                        l = qc_blank(s);
                        if (lk == QSC_LOCK_TITLE_SHUT && x->sicon[j][0]) {
                            /* Only the stock QS LOCK uses the new native image. Other API clients keep
                             * their supplied title icons. Fixed 28-byte registered name buffer. */
                            if (!x->sicon[j][12] && fnv_bytes((uintptr_t)x->sicon[j], 12u) == 0x1AD6EC9Du)
                                lock_width = 150u;    /* fnv1a("menu_lock_qs"); image rect belongs to this tile */
                            else { qc_markup(s, mk, sizeof mk, x->sicon[j]); l = mk; }
                        }
                    }
                    else if (lk == QSC_LOCK_SMALL_OPEN || lk == QSC_LOCK_SMALL_SHUT) {
                        sm = qc_blank(s); approx = 0;
                        if (lk == QSC_LOCK_SMALL_SHUT) small_lock_width = 120u;
                    }
                    else if ((lk == QSC_LOCK_OPEN || lk == QSC_LOCK_SHUT) && (x->flags & FX_API4)) {
                        vfont = FONT_PLAIN, v = ic;
                        /* v0.3.2 (live4 #15): the 96 px icon drawn from the value line's top (tile y ~100, key
                         * y 130..185) covered the small line (150..190).  A small text moves to the title row
                         * (38..86), above the icon; the small row stays empty.  No small text: the title stays. */
                        if (sm[0] && !(sm[0] == ' ' && !sm[1])) { l = sm; sm = qc_blank(s); approx = 0; }
                    }
                    else if (lk == QSC_LOCK_OPEN || lk == QSC_LOCK_SHUT) l = ic;   /* API 3: over the title (live 3: overlaps) */
                } else if (x->sicon[j][0]) {
                    qc_markup(s, mk, sizeof mk, x->sicon[j]);
                    l = mk;
                }
            }
        }
        if (lock_width != s->lock_width_last[k]) {
            s->lock_width_last[k] = lock_width;
            ((fn3)POST_INT)(0, (u32)(uintptr_t)qc_name(s, S_LW + k), lock_width);
        }
        if (small_lock_width != s->small_lock_width_last[k]) {
            s->small_lock_width_last[k] = small_lock_width;
            ((fn3)POST_INT)(0, (u32)(uintptr_t)qc_name(s, S_SW + k), small_lock_width);
        }
        qc_post_text(s, k, R_L, l, lfont);
        qc_post_text(s, k, R_V, v, vfont);
        /* live 3: the small glyph images are not tinted (white); the plain font takes the grey / yellow */
        qc_post_text(s, k, R_S, approx ? qc_blank(s) : sm, FONT_PLAIN);
        qc_post_text(s, k, R_Y, approx ? sm : qc_blank(s), FONT_PLAIN);
        if (g != s->g_last[k]) {
            s->g_last[k] = g;
            ((fn3)POST_INT)(0, (u32)(uintptr_t)qc_name(s, S_G + k), g);
        }
    }
}

/* QS_FooterGuidDisp ("AEL more options") as FUN_c057f310 sets it for a stock id:
 * written only when it differs from the QS state's copy. */
static void qc_guid_set(struct st *s, u32 v)
{
    u32 q = ((fn0)QS_STATE)();
    u32 cur = ((fn1)W(W(q + QS_GUID_VT) + 0x74u))(q + 0x3Cu);
    if (cur == v) return;
    u32 o = ((fn0)APPVARS)();
    ((fn3)W(W(o) + 0x2Cu))(o, GUID_NAME, v);
    B8(q + QS_GUID_CACHE) = (u8)v;
    s->guid_sets++;
}

static void qc_foot_text(struct st *s, u32 j, u32 role, const char *t)
{
    char tmp[FT_BYTES];                   /* S_FL, S_FS, S_FY, S_FG, S_FC, S_FN, S_FM, S_FP, S_FQ, S_FR: N_SLOT each */
    qc_expand(s, tmp, FT_BYTES, t, FONT_PLAIN);
    qc_post_buf(s, S_FL + N_SLOT * role + j, &s->ftxt[j][role][0][0], FT_BYTES, &s->f_sel[j][role], tmp);
}

/* In the sub-QS / fine mode: "MENU Back" only when MENU returns (cfg CF_MENU_BACK); live run 3: MENU also ran
 * the stock MENU, so by default MENU is the stock one, AEL returns, and no stock string says "AEL back": no hint. */
static u32 qc_back_hint(const struct st *s) { return s->cfg->flags & CF_MENU_BACK ? 1u : 0u; }

/* The option strip for the focused id: our function / sub-item -> its footer()
 * (up to N_WIN at once around the current one, centred: option q of m on slot
 * 8 - m + 2q), else nothing.  The arrows: ours -> QSC_Arw = adjust ? 1 : 0
 * (2 first, so the value changes and the page's event runs).  gui: inside the
 * QS GUI (the hint may be written). */
/* API 6: the focused sub-item's blur() once the focus is anywhere else (id), or forced (id = ~0: the sub-QS closes) */
static void qc_blur(struct st *s, u32 id)
{
    if (!s->blur_fn || s->blur_id == id) return;
    u32 fn = s->blur_fn, arg = s->blur_arg;
    s->blur_fn = 0; s->blur_id = 0; s->blurs++;
    ((void (*)(void *))fn)((void *)(uintptr_t)arg);
}

/* v0.3.8 (API 8): the dial guide -- 0 none, 1 "+-1 / +-10" (API 4), 2 "+-1 / +-1" (API 3 / 2: the rear step);
 * posted only when it changes (the GUI keeps the pointer: the texts are in the borrowed range of the BIN). */
static void qc_dial_hint(struct st *s, u32 dh)
{
    if (dh == s->dh_last) return;
    s->dh_last = dh;
    s->dh_posts++;
    const char *t = dh ? (const char *)(s->block + s->cfg->dial_off + DH_BYTES * (dh - 1u)) : qc_blank(s);
    ((fn3)POST_STR)(0, (u32)(uintptr_t)qc_name(s, S_DH), (u32)(uintptr_t)t);
    ((fn3)POST_INT)(0, (u32)(uintptr_t)qc_name(s, S_DHB), dh ? 1u : 0u);
}

static void qc_focus(struct st *s, u32 id, u32 gui)
{
    struct qsc_foot f;
    volatile u32 *z = (volatile u32 *)&f;
    int32_t item, i = qc_fn_of(s, id, &item);
    u32 n = 0, adj = 0, more = 0, lo = 0, m = 0, dh = 0;
    s->focus_calls++;
    s->focus = id;
    qc_blur(s, id);
    for (u32 w = 0; w < sizeof f / 4u; w++) z[w] = 0;
    if (i >= 0) {
        const struct fx *x = &s->fx[i];
        if (item >= 0 && s->sub_open == i && s->sblur[i][item]) {
            s->blur_id = id; s->blur_fn = s->sblur[i][item]; s->blur_arg = x->sarg[item];
        }
        u32 fp = item < 0 ? x->footer : x->sfoot[item], arg = item < 0 ? x->arg : x->sarg[item];
        adj = (item < 0 ? x->adjust : x->sa[item]) && !qc_locked(s, (u32)i);
        if (adj && (x->flags & QSC_F_DIAL_HINT)) dh = (x->flags & FX_API4) ? 1u : 2u;   /* API 8 */
        more = item < 0 && id != INT_MAIN && (x->nsub || s->xfine[i]) && s->sub_open < 0 && !s->fine_on &&
               !qc_locked(s, (u32)i);
        if (fp) n = ((u32 (*)(void *, struct qsc_foot *))fp)((void *)(uintptr_t)arg, &f);
        if (n > QSC_FOOT_MAX) n = QSC_FOOT_MAX;
    }
    /* v0.2.4: options whose lines are wider than a 128 px slot get a wider pitch p (slots 64 p apart) and fewer of
     * them at once: p 2 -> 7, 3 -> 5, 4 -> 4, 5..7 -> 3 (p (m - 1) even and <= 14, so the strip stays centred).
     * A label counts 4/3 of the small font. */
    u32 p = 2;
    for (;;) {
        u32 mx = p == 2u ? 7u : p == 3u ? 5u : p == 4u ? 4u : 3u;
        m = n < mx ? n : mx;
        if ((p & 1u) && !(m & 1u) && p < 7u) { p++; continue; }     /* odd pitch, even count: not centred */
        lo = 0;
        if (n > m && f.cur < n) {
            lo = f.cur > m / 2u ? f.cur - m / 2u : 0u;
            if (lo > n - m) lo = n - m;
        }
        u32 wmax = 0;
        if (!f.spin)
            for (u32 o = lo; o < lo + m; o++) {
                u32 a = f.small[o] ? qc_small_w(f.small[o]) : 0u, b = f.label[o] ? (qc_small_w(f.label[o]) * 4u) / 3u : 0u;
                if (a > wmax) wmax = a;
                if (b > wmax) wmax = b;
            }
        if (wmax + 10u <= 64u * p || p >= 7u) break;
        p++;
    }
    s->foot_pitch = p;
    u32 j0 = 7u - (p * (m ? m - 1u : 0u)) / 2u;                      /* option q on slot j0 + p q */
    u32 box = BOX_NONE, spin = n && f.spin, v4 = i >= 0 && (s->fx[i].flags & FX_API4);
    if (!v4) f.mark = f.custom = f.grey = 0;                         /* API 3: reserved, ignored */
    for (u32 j = 0; j < N_SLOT; j++) {
        const char *t[N_FROLE], *b = qc_blank(s);
        u32 o = 0xFFFFFFFFu;
        u32 q = 0xFFFFFFFFu;                                         /* slot j = j0 + p q (p = 2: 8 - m + 2q) */
        for (u32 k = 0; k < m; k++) if (j0 + p * k == j) q = k;
        for (u32 r = 0; r < N_FROLE; r++) t[r] = b;
        if (spin) {                                                  /* "<  value  >": slots 5, 7, 9 */
            if (j == 7u) o = 0;
            else if (j == 5u || j == 9u) t[7] = (const char *)(s->block + s->cfg->arrow_off[j == 9u]);   /* centred */
        } else if (m && q < m) {
            o = lo + q;
            if (o == f.cur) box = j;
        }
        if (o < n) {
            /* label: white, grey (not selectable) or yellow (custom); small: grey, yellow, or the grey reason */
            u32 grey = f.grey >> o & 1u, cu = f.custom >> o & 1u;
            if (f.label[o] && f.small[o]) t[grey ? 3 : cu ? 4 : 0] = f.label[o];
            else if (f.label[o]) t[grey ? 8 : cu ? 9 : 7] = f.label[o];     /* v0.2.3: no second line -> centred */
            if (f.small[o]) t[grey ? 5 : (f.approx >> o & 1u) ? 2 : 1] = f.small[o];
            if (f.mark >> o & 1u) t[6] = (const char *)(s->block + s->cfg->mark_off);
        }
        for (u32 r = 0; r < N_FROLE; r++) qc_foot_text(s, j, r, t[r]);
    }
    s->foot_on = n ? 1u : 0u;
    qc_dial_hint(s, dh);                                             /* stock / blank ids: none */
    if (box != s->fb_last) {
        s->fb_last = box;
        ((fn3)POST_INT)(0, (u32)(uintptr_t)qc_name(s, S_FB), box);
    }
    if (i >= 0) {
        ((fn3)POST_INT)(0, (u32)(uintptr_t)qc_name(s, S_ARW), 2u);
        ((fn3)POST_INT)(0, (u32)(uintptr_t)qc_name(s, S_ARW), adj);
        s->arw_last = adj;
        if (gui) {                                                    /* sub-QS / fine: "MENU Back" or none */
            u32 inner = s->sub_open >= 0 || s->fine_on, h = inner ? qc_back_hint(s) : more;
            qc_guid_set(s, h);
            /* v0.2.3 (live run 4): the hint's text is QS_FooterGuid1's frame, and only the stock K tile writes it
             * (frame 4/5 "AEL WB adjust"); QS_FooterGuidDisp alone did not hide it on our tiles.  Ours: the
             * frame of our own hint, or 0 (no text, no box). */
            ((fn3)POST_INT)(0, GUID1_NAME, h ? (inner ? HINT_BACK : HINT_MORE) : 0u);
            /* v0.3.2 (live4 #8, SensorLab v1-live2 #7/#9): our AEL keyEvent sits in the stock AEL object, which is
             * shown only while QS_AELbtn == 1.  The stock holders write it per id; on our ids it kept what the last
             * stock tile left, so after boot (or a menu jump straight into our sub-QS) AEL was dead until the focus
             * crossed a stock tile that writes 1 (K).  Ours: 1 where AEL acts (more options, or back from the
             * sub-QS / fine mode), 0 otherwise -- as a stock holder does. */
            ((fn3)POST_INT)(0, AELBTN_NAME, inner || more ? 1u : 0u);
        }
    }
}

static void qc_sub_close(struct st *s, u32 focus);
static void qc_sub_open(struct st *s, u32 i, u32 allow_standalone, u32 at);
static u32 qc_pending(struct st *s);

/* API 4 fine mode keeps its tile. API 5 may supply a temporary single tile. */
static void qc_fine_end(struct st *s, u32 focus)
{
    if (!s->fine_on) return;
    u32 i = s->fine_on - 1u;
    s->fine_on = 0;
    ((int (*)(void *, int))s->xfine[i])((void *)(uintptr_t)s->fx[i].arg, 0);
    ((fn3)POST_INT)(0, GUID1_NAME, HINT_MORE);
    if (s->standalone) qc_sub_close(s, focus);
}

static void qc_fine_begin(struct st *s, u32 i)
{
    if (!((int (*)(void *, int))s->xfine[i])((void *)(uintptr_t)s->fx[i].arg, 1)) return;
    s->fine_on = i + 1u;
    s->fines++;
    if (qc_back_hint(s)) ((fn3)POST_INT)(0, GUID1_NAME, HINT_BACK);
    qc_focus(s, INT_BASE + i, 1);
}

/* Replaces `bl FUN_c057f310(id)` in FUN_c0582da0, the QS GUI's QS_QSMode
 * callback (+0xBC was just written): the hint for our ids (only with
 * sub-items), the stock one otherwise; then the footer and the arrows. */
static USED void qc_guid(u32 id)
{
    struct st *s = qc_ctx();
    if (s->phase == PH_READY && s->qs_ready) {
        u32 was_active = s->qs_active;
        s->qs_active = ((fn1)IS_CINE)(((fn0)SETTINGS_GET)()) == 1u;
        if (qc_pending(s)) return;
        u32 resolved = qc_qs_id(s, id);
        if ((!was_active || resolved != id) && s->qs_active && s->sub_open < 0 && !s->standalone) qc_emit(s);
        if (resolved != id) {
            id = resolved;
            W(((fn0)QS_STATE)() + QS_FOCUS) = id;
            ((fn3)POST_INT)(0, s->cfg->qsmode_name, ((fn2)TO_UI)(CONV, id));
        }
        qc_blur(s, id);                                             /* API 6: before the texts are posted */
        if (s->fine_on && id != INT_BASE + s->fine_on - 1u) {
            u32 standalone = s->standalone;
            qc_fine_end(s, standalone);
            if (standalone) id = W(((fn0)QS_STATE)() + QS_FOCUS);
        }
        qc_texts(s);
    }
    if (s->phase != PH_READY || !s->qs_ready || !ours_qs(s, id)) ((fn1)s->next_guid)(id);
    if (s->phase == PH_READY && s->qs_ready) qc_focus(s, id, 1);
}

/* Back to the user's layout: the eight ids from the settings; with `focus`, the
 * focus goes back to the function's own tile (QS_FocusPos, QS_QSMode, the QS
 * state's +0xBC as the QS GUI's callback writes it) and its footer. */
static void qc_sub_close(struct st *s, u32 focus)
{
    qc_blur(s, 0xFFFFFFFFu);
    u32 set = ((fn0)SETTINGS_GET)(), cine = ((fn1)IS_CINE)(set) == 1u, home = s->sub_home, fui = 0;
    for (u32 k = 0; k < 8u; k++) {
        u32 ui = cine ? qc_slot_ui(s, k) : ((fn2)TO_UI)(CONV, 0u);
        ((fn3)POST_INT)(0, QS_NAME0 + 0x10u * k, ui);
        if (k == home) fui = ui;
    }
    s->sub_open = -1;
    s->standalone = 0;
    s->closes++;
    if (qc_back_hint(s)) ((fn3)POST_INT)(0, GUID1_NAME, HINT_MORE);
    if (focus && home < 8u) {
        ((fn3)POST_INT)(0, s->cfg->focuspos_name, home);
        ((fn3)POST_INT)(0, s->cfg->qsmode_name, fui);              /* the focused tile is the function again */
        u32 internal = ((fn2)TO_INT)(CONV, fui);
        W(((fn0)QS_STATE)() + QS_FOCUS) = internal;
        qc_focus(s, internal, 1);
    }
}

/* The sub-QS of function i: tile 1 = the function (UI 65, focused), tiles 2..
 * its sub-items (66..), the rest blank (72).  Only the eight app variables
 * change, never the settings.  API 6: at = 1 + k focuses sub-item k (tile k + 2). */
static void qc_sub_open(struct st *s, u32 i, u32 allow_standalone, u32 at)
{
    u32 set = ((fn0)SETTINGS_GET)(), k0 = 8;
    if (((fn1)IS_CINE)(set) != 1u) return;
    for (u32 k = 0; k < 8u && k0 == 8u; k++)
        if (qc_slot_ui(s, k) == UI_BASE + i) k0 = k;
    if (k0 == 8u && !allow_standalone) return;
    if (k0 == 8u) { k0 = 0; s->standalone = 1; }
    for (u32 k = 0; k < 8u; k++) {
        u32 id = k == 0 ? UI_MAIN : k - 1u < s->fx[i].nsub ? UI_SUB0 + k : UI_BLANK;
        s->sub_tile[k] = id;
        ((fn3)POST_INT)(0, QS_NAME0 + 0x10u * k, id);
    }
    s->sub_open = (int32_t)i;
    s->sub_home = k0;
    s->opens++;
    if (qc_back_hint(s)) ((fn3)POST_INT)(0, GUID1_NAME, HINT_BACK);
    if (at > s->fx[i].nsub) at = 0;
    ((fn3)POST_INT)(0, s->cfg->focuspos_name, at);
    ((fn3)POST_INT)(0, s->cfg->qsmode_name, UI_MAIN + at);
    W(((fn0)QS_STATE)() + QS_FOCUS) = INT_MAIN + at;
    qc_focus(s, INT_MAIN + at, 1);
}

/* Consume exactly once, on the real QS-only focus path. No unknown layout
 * identity field is used to decide whether editor app variables may change. */
static u32 qc_pending(struct st *s)
{
    if (!s->pending_fn) return 0;
    u32 i = s->pending_fn - 1u, how = s->pending_how;
    s->pending_fn = 0; s->pending_how = 0;
    if (!s->qs_active || i >= s->n || busy() || qc_locked(s, i)) return 0;
    qc_fine_end(s, 0);
    if (s->sub_open >= 0) qc_sub_close(s, 0);
    if ((how & 0xFFu) == QSC_OPEN_SUB && s->fx[i].nsub) qc_sub_open(s, i, 1, how >> 8);
    else if (how == QSC_OPEN_FINE && s->xfine[i] && !qc_go_target(&s->fx[i])) {
        u32 home = 8;
        for (u32 k = 0; k < 8u; k++) if (home == 8u && qc_slot_ui(s, k) == UI_BASE + i) home = k;
        if (home == 8u) {
            home = 0; s->standalone = 1; s->sub_home = 0;
            for (u32 k = 0; k < 8u; k++) {
                s->sub_tile[k] = k ? UI_BLANK : UI_BASE + i;
                ((fn3)POST_INT)(0, QS_NAME0 + 0x10u * k, s->sub_tile[k]);
            }
        } else qc_emit(s);
        ((fn3)POST_INT)(0, s->cfg->focuspos_name, home);
        ((fn3)POST_INT)(0, s->cfg->qsmode_name, UI_BASE + i);
        W(((fn0)QS_STATE)() + QS_FOCUS) = INT_BASE + i;
        qc_fine_begin(s, i);
        if (!s->fine_on && s->standalone) qc_sub_close(s, 1);
    } else return 0;
    qc_texts(s);
    return 1;
}

/* API 7: AEL on a GO tile (not greyed / locked: qc_ael).  fine(arg, 1) is the request; yes = the go text gets
 * the target page and QSC_Go its next value -- the change event of our object on the QS page then sends the
 * stock request (a deferred controlAppState: the private machine's QS_CINE -> page).  Never while recording
 * (the stock menu is not reachable then), never without the machine.  fine(arg, 0) is not called. */
static void qc_go(struct st *s, u32 i)
{
    const struct cfg *c = s->cfg;
    if (s->go_result || qc_go_target(&s->fx[i]) != QSC_GO_READQR || busy()) { s->go_skips++; return; }
    if (!((int (*)(void *, int))s->xfine[i])((void *)(uintptr_t)s->fx[i].arg, 1)) { s->go_refused++; return; }
    qc_fine_end(s, 0);
    if (s->sub_open >= 0) qc_sub_close(s, 0);
    char *t = (char *)(uintptr_t)(s->block + c->go_text_off);
    const char *pg = (const char *)(s->block + c->go_page_off);
    u32 k = 0;
    for (; k < GO_TEXT - 1u && pg[k]; k++) t[k] = pg[k];
    t[k] = 0;
    s->go_armed = 1;
    s->goes++;
    ((fn3)POST_INT)(0, (u32)(uintptr_t)qc_name(s, S_GO), ++s->go_seq);
}

static void qc_dial(struct st *s, u32 foc, int step, u32 rear)
{
    int32_t item, i = qc_fn_of(s, foc, &item);
    s->dials++;
    if (i < 0) return;
    if (qc_locked(s, (u32)i)) { s->locked++; return; }
    u32 fp = item < 0 ? s->fx[i].adjust : s->fx[i].sa[item];
    u32 arg = item < 0 ? s->fx[i].arg : s->fx[i].sarg[item];
    if (fp) {
        if (rear && (s->fx[i].flags & FX_API4)) { step *= QSC_STEP_REAR; s->rears++; }
        ((int (*)(void *, int))fp)((void *)(uintptr_t)arg, step);
        s->adjusts++;
        qc_focus(s, foc, 1);                                        /* the footer follows the dial */
    }
}

static void qc_ael(struct st *s, u32 foc)
{
    s->aels++;
    if (s->fine_on) {
        u32 standalone = s->standalone;
        qc_fine_end(s, 1);
        qc_focus(s, standalone ? W(((fn0)QS_STATE)() + QS_FOCUS) : foc, 1);
        return;
    }
    if (s->sub_open >= 0) { qc_sub_close(s, 1); return; }
    if (foc - INT_BASE >= s->n) return;
    u32 i = foc - INT_BASE;
    if (!s->fx[i].nsub && !s->xfine[i]) return;
    if (qc_locked(s, i)) { s->locked++; return; }
    if (qc_go_target(&s->fx[i])) { qc_go(s, i); return; }     /* API 7: a stock page, not a fine mode */
    if (s->xfine[i]) qc_fine_begin(s, i);
    else qc_sub_open(s, i, 0, 0);
}

/* QSC_Key changed (a keyEvent of ours wrote the code): the GUI calls this
 * with the variable's descriptor (+8 the value), on the UI thread.  The
 * variable goes back to 0 at once (our own post does not call us), so the
 * next press is a change again. */
static USED u32 qc_key(u32 desc)
{
    struct st *s = qc_ctx();
    u32 code = W(desc + 8u);
    if (!code) return 0;
    ((fn3)POST_INT)(0, (u32)(uintptr_t)qc_name(s, S_KEY), 0);
    if (s->phase != PH_READY || !s->qs_ready) return 0;
    if (((fn1)IS_CINE)(((fn0)SETTINGS_GET)()) != 1u) return 0;
    s->keys++;
    u32 native = W(((fn0)QS_STATE)() + QS_FOCUS), foc = qc_qs_id(s, native);
    W(((fn0)QS_STATE)() + QS_FOCUS) = foc;
    if (foc != native && s->qs_active && s->sub_open < 0 && !s->standalone) qc_emit(s);
    if (code >= CODE_UP && code <= CODE_RDOWN)
        qc_dial(s, foc, code == CODE_UP || code == CODE_RUP ? 1 : -1, code >= CODE_RUP);
    else if (code == CODE_AEL) qc_ael(s, foc);
    else if (code == CODE_MENU) {                                   /* only with CF_MENU_BACK (the data's M) */
        s->menus++;
        if (s->cfg->flags & CF_MENU_BACK) { qc_fine_end(s, 1); if (s->sub_open >= 0) qc_sub_close(s, 1); }
    }
    qc_texts(s);
    return 0;
}

/* ===== collection: once, at the first layout load after the entries ========= */
static void qc_freeze(struct st *s)
{
    s->phase = PH_RUNNING;
    qc_rec_load(s);
    {
        u32 img = image_now();
        for (u32 i = 0; i < NSLOT; i++) s->last[i] = W(img + arr(i));
    }
    if (qc_zqs(s)) { s->freeze = F_ZQS; s->phase = PH_DOWN; return; }
    qc_collect(s);
    u32 n = s->offered;
    struct rows rw;
    if (!n) s->freeze = F_NONE;
    else if ((s->csv_result = qc_csv_build(s, n, &rw)) != 0) { s->freeze = F_CSV; n = 0; }
    /* the pages (invisible without the rows), then the rows: a function exists
     * only when everything it needs is in */
    /* the QS page's records next (all of them or none: a QS tile half done is
     * the 2026-10-29 bug), then the editor pages */
    if (n && (s->qs_result = qc_qs_build(s, n)) != 0) { s->freeze = F_QS; n = 0; }
    for (u32 p = 0; n && p < NPAGE; p++) {
        u32 r = qc_page(s, p, n, s->csv_rows[s->cfg->page_csv[p]]);
        s->page_result[p] = r;
        if (r) { s->freeze = F_PAGE; n = 0; }
    }
    if (n) qc_csv_commit(&rw);
    s->n = n;
    s->qs_ready = n ? 1u : 0u;
    if (n) ((fn3)VAR_WATCH)(GUI_OBJECT, (u32)(uintptr_t)qc_name(s, S_KEY), (u32)(uintptr_t)&qc_key);
    fst_publish();
    qc_restore(s);
    if (s->restored) qc_emit(s);
    s->phase = PH_READY;
}

static USED u32 qc_layout(u32 layout)
{
    struct st *s = qc_ctx();
    u32 t0 = ((fn0)TICK_US)(), first = !s->tm[7];
    s->lay_calls++;
    if (first) { s->tm[0] = t0; s->tm[1] = ((fn0)TICK_US)(); }
    if (s->go_armed) {                         /* v0.3.7: the go's request was taken: a QS built again asks nothing */
        *(char *)(uintptr_t)(s->block + s->cfg->go_text_off) = 0;
        s->go_armed = 0;
    }
    if (s->phase == PH_ENTRY && !W(SL_SVC_AT)) qc_freeze(s);
    if (first) { s->tm[2] = ((fn0)TICK_US)(); s->tm[3] = s->tm[2]; s->tm[4] = s->tm[2]; }
    if (s->phase == PH_READY && s->qs_ready) {
        u32 was_qs = s->qs_active;
        s->qs_active = 0;
        qc_fine_end(s, 0);                                          /* QS was left in fine mode */
        if (s->sub_open >= 0) qc_sub_close(s, 0);                  /* QS was left with the sub-QS up */
        if (was_qs) qc_emit(s);                                     /* editor sees only the stock ids */
        if (first) s->tm[3] = ((fn0)TICK_US)();
        for (u32 j = 0; j < s->n_leave; j++) {                      /* API 4 leave(): outside the key path */
            ((void (*)(void *))s->leave_fn[j])((void *)(uintptr_t)s->leave_arg[j]);
            s->leaves++;
        }
        if (first) s->tm[4] = ((fn0)TICK_US)();
        qc_texts(s);
        qc_focus(s, W(((fn0)QS_STATE)() + QS_FOCUS), 0);          /* the strip of the tile QS opens on */
    }
    u32 r = ((fn1)s->next_lay)(layout);
    qc_release(s, layout);
    u32 t1 = ((fn0)TICK_US)(), d = t1 - t0;
    if (first) { s->tm[5] = t1; s->tm[10] = d; }
    if (d > s->tm[8]) s->tm[8] = d;
    s->tm[9] = d; s->tm[7]++;
    return r;
}

/* The displaced first instruction of FUN_c05d90f0, then the rest of it. */
__attribute__((naked)) static void qc_lay_stock(void)
{
    __asm__ volatile("push.w {r4, r5, r6, r7, r10, r11, lr}\n\t"
                     "ldr.w pc, 1f\n\t"
                     ".balign 4\n"
                     "1:\t.word 0xC05D90F5\n");
}

/* ===== the API (svc->find(QSC_ID)) ============================================== */
static int qc_ui_id(const struct qsc_api *api, u32 sup_id, const char *name)
{
    struct st *s = qc_ctx();
    (void)api;
    if (s->phase != PH_READY || !name) return -1;
    u32 key[4] = {sup_id, 0, 0, 0}, nl = 0;
    while (nl < QSC_NAME - 1u && name[nl]) { ((u8 *)&key[1])[nl] = (u8)name[nl]; nl++; }
    if (name[nl]) return -1;
    for (u32 j = 0; j < s->n; j++) if (key_eq(s->f[j].key, key)) return (int)(UI_BASE + j);
    return -1;
}
static int qc_open(const struct qsc_api *api, u32 sup_id, const char *name, u32 how)
{
    struct st *s = qc_ctx();
    int ui = qc_ui_id(api, sup_id, name);
    if (ui < 0 || !s->qs_ready || busy() || ((fn1)IS_CINE)(((fn0)SETTINGS_GET)()) != 1u) return 0;
    u32 i = (u32)ui - UI_BASE, at = how >> 8;                       /* API 6: QSC_OPEN_SUB_AT(k): at = k + 1 */
    if (qc_locked(s, i) || (how & ~0xFFFFu) || (how & 0xFFu) - 1u > 1u ||
        ((how & 0xFFu) == QSC_OPEN_SUB && (!s->fx[i].nsub || at > s->fx[i].nsub)) ||
        ((how & 0xFFu) == QSC_OPEN_FINE && (at || !s->xfine[i] || qc_go_target(&s->fx[i])))) return 0;
    s->pending_fn = i + 1u; s->pending_how = how;
    return 1;
}
static void qc_refresh(const struct qsc_api *api, u32 sup_id, const char *name)
{
    struct st *s = qc_ctx();
    (void)api; (void)sup_id; (void)name;
    if (s->phase == PH_READY && s->qs_ready) {
        qc_texts(s);
        qc_focus(s, s->focus, 0);
    }
}

/* ===== entry ========================================================================= */
static void hex8(char *p, u32 v)
{
    for (u32 i = 0; i < 8u; i++) {
        u32 d = (v >> (28u - 4u * i)) & 0xFu;
        p[i] = (char)(d < 10u ? '0' + d : 'A' + d - 10u);
    }
}
static void qc_log(struct st *s)
{
    char line[32];
    u32 n = 0;
    line[n++] = 'Q'; line[n++] = 'S'; line[n++] = 'C'; line[n++] = ' ';
    hex8(line + n, s->result << 16 | s->fv_result); n += 8; line[n++] = ' ';
    hex8(line + n, s->prev_vt); n += 8;
    line[n] = 0;
    if (s->svc->log) s->svc->log(s->svc, line);
}

static int qc_fail(struct st *s, u32 why)
{
    s->result = why;
    qc_log(s);
    return SL_RELEASE;        /* nothing written yet but claims: the loader undoes them */
}

USED int sup_entry(void *block, const struct sl_svc *svc, const char *path)
{
    const struct sl4_header *h = (const struct sl4_header *)block;
    const struct cfg *c = (const struct cfg *)((const u8 *)block + SL4_HEADER_LEN);
    if (svc->version < 6u || c->magic != CFG_MAGIC || c->version != 4u ||
        c->state_off < h->file_len || c->state_off + sizeof(struct st) > c->dma_off ||
        (c->dma_off & 63u) || c->dma_off + DMA_BYTES > h->block_size ||
        c->rec_off + 4u * REC_WORDS > h->file_len || (c->rec_off & 3u) || !c->n_icons ||
        c->icon_default >= c->n_icons || c->qs_off + c->qs_frags_off > h->file_len ||
        c->blank_off != c->names_off + NAME_BYTES * N_NAMES || c->blank_off + 4u > h->file_len ||
        c->go_text_off != c->blank_off + 4u || c->go_text_off + GO_TEXT > h->file_len ||
        c->go_page_off >= h->file_len || c->go_file_off + c->go_file_len > h->file_len || (c->go_file_off & 63u) ||
        c->dial_off != c->go_text_off + GO_TEXT || c->dial_off + 2u * DH_BYTES > h->file_len)
        return SL_RELEASE;
    struct st *s = (struct st *)((u8 *)block + c->state_off);
    s->magic = ST_MAGIC; s->svc = svc; s->block = (const u8 *)block; s->cfg = c; s->path = path;
    s->phase = PH_ENTRY;
    W(qc_ctx_at()) = (u32)(uintptr_t)s;
    svc->publish(svc);

    /* 1. claims (any refusal: RELEASE, nothing written) */
    ((fn0)CONV_GET)();
    if (svc->claim(svc, CONV_VT, 4, &(u32){VT_STOCK}, SL_CHAIN) != SL_OK ||
        svc->claim(svc, SAVE_SITE, 4, &(u32){SAVE_STOCK}, SL_CHAIN) != SL_OK ||
        svc->claim(svc, REC_SITE, 4, &(u32){REC_STOCK}, SL_CHAIN) != SL_OK ||
        svc->claim(svc, HP_SITE, 4, &(u32){HP_STOCK}, SL_CHAIN) != SL_OK ||
        svc->claim(svc, LAY_SITE, 4, &(u32){LAY_STOCK}, SL_CHAIN) != SL_OK ||
        svc->claim(svc, REC_PARSE, 4, &(u32){REC_PARSE_STOCK}, SL_CHAIN) != SL_OK ||
        svc->claim(svc, GUID_SITE, 4, &(u32){GUID_STOCK}, SL_CHAIN) != SL_OK)
        return qc_fail(s, R_CLAIM);
    /* the redirect site: claimed with whoever else did (SHARED_UI); a foreign
     * hook nobody claimed is left to its owner (then no rows: qc_table fails) */
    if (W(FV_SITE) == FV_STOCK || svc->holder(svc, FV_SITE, 0))
        svc->claim(svc, FV_SITE, 4, &(u32){FV_STOCK}, SL_SHARED_UI);

    /* 2. prepare: the converter copy, on whatever layer is there now */
    u32 prev = W(CONV_VT);
    if (!prev || (prev & 3u) || prev < 0xC0000000u || !W(prev + VT_CINE)) return qc_fail(s, R_PREV_VT);
    for (u32 i = 0; i < (VT_PRE + VT_BYTES) / 4u; i++) s->vt[i] = W(prev - VT_PRE + 4u * i);
    s->prev_vt = prev;
    s->prev_cine = W(prev + VT_CINE);
    {
        u32 t = 0, n = ((u32 (*)(u32, u32 *))s->prev_cine)(CONV, &t);
        if (!qc_build(s, t, n)) return qc_fail(s, s->collide ? R_COLLIDE : R_PREV_VT);
    }
    s->vt[(VT_PRE + VT_CINE) / 4u] = (u32)(uintptr_t)&qc_cine;
    s->next_save = svc->chain_next(svc, SAVE_SITE, 0);
    s->next_rec = svc->chain_next(svc, REC_SITE, 0);
    s->next_hp = svc->chain_next(svc, HP_SITE, 0);
    s->next_guid = svc->chain_next(svc, GUID_SITE, 0);
    s->next_lay = svc->chain_next(svc, LAY_SITE, 1);
    if (!s->next_lay) s->next_lay = (u32)(uintptr_t)&qc_lay_stock;
    s->next_qsrec = svc->chain_next(svc, REC_PARSE, 1);
    if (!s->next_qsrec) s->next_qsrec = (u32)(uintptr_t)&qc_qsrec_stock;
    if (!s->next_save || !s->next_rec || !s->next_hp || !s->next_guid) return qc_fail(s, R_CHAIN);
    u32 v = svc->cave_alloc(svc, 48);
    if (!v || (v & 7u)) return qc_fail(s, R_CAVE);
    W(v) = VENEER_ARM; W(v + 4u) = (u32)(uintptr_t)&qc_save;
    W(v + 8u) = VENEER_ARM; W(v + 12u) = (u32)(uintptr_t)&qc_rec;
    W(v + 16u) = VENEER_ARM; W(v + 20u) = (u32)(uintptr_t)&qc_hp;
    W(v + 24u) = VENEER_THUMB; W(v + 28u) = (u32)(uintptr_t)&qc_layout;
    W(v + 32u) = VENEER_THUMB; W(v + 36u) = (u32)(uintptr_t)&qc_qsrec;
    W(v + 40u) = VENEER_ARM; W(v + 44u) = (u32)(uintptr_t)&qc_guid;
    s->veneer = v;
    /* the labels, texts and variable names are handed to the firmware by id or
     * pointer: it must never free them */
    if (svc->borrow(svc, s, s + 1) != SL_OK ||
        svc->borrow(svc, s->block + c->names_off, s->block + c->dial_off + 2u * DH_BYTES) != SL_OK) return qc_fail(s, R_CAVE);
    s->sub_open = -1;
    s->sub_home = 8;
    s->fb_last = BOX_NONE;
    s->qs_pre = W(RCACHE + 4u);              /* parsed before us: let go once (qc_release) */
    s->api.magic = QSC_API_MAGIC; s->api.version = 9;
    s->api.ui_id = qc_ui_id; s->api.refresh = qc_refresh;
    s->api.open = qc_open;
    s->api.timing = s->tm;
    svc->publish(svc);

    /* 3. the save swap first: before anything can hold an id >= 54 */
    W(SAVE_SITE) = bl_to(SAVE_SITE, v);
    W(REC_SITE) = bl_to(REC_SITE, v + 8u);
    W(HP_SITE) = bl_to(HP_SITE, v + 16u);
    W(GUID_SITE) = bl_to(GUID_SITE, v + 40u);
    svc->publish(svc);
    /* 4. the redirect handler (found, or installed: the rows go in at collection) */
    {
        struct uia_outcome o;
        s->fv_result = fpui_stock_apply(svc, s->block + c->fpui_off, c->fpui_len, &o);
    }
    /* 5. the converter (no new pairs until collection), then the trigger */
    W(CONV_VT) = (u32)(uintptr_t)&s->vt[VT_PRE / 4u];
    svc->publish(svc);
    W(LAY_SITE) = thumb_bw(LAY_SITE, v + 24u);
    W(REC_PARSE) = thumb_bw(REC_PARSE, v + 32u);   /* the layer passes everything until collection */
    svc->publish(svc);
    /* 6. v0.3.7: the go machine (QS_CINE -> Y5_ReadQR), as any fpsup-ui sup installs its pages at entry; a
     * failure only turns the go off (AEL on a GO tile then does nothing, fine() is not asked) */
    {
        u32 r = fpui_install(svc, s->block + c->go_file_off);
        s->go_result = r ? 0x100u | r : 0u;
    }
    svc->provide(svc, QSC_ID, &s->api);
    qc_log(s);
    return SL_KEEP;
}
