/* SensorLab-IMX410 apply: make the QS selection take effect on the sensor and the ISP.
 *
 * Design: ../notes/APPLY_DESIGN.md (v2 + "2026-10-29 Bei 更正：套用時機" + §11 the apply unit).
 * Technique: RES-Custom's virtual tables (open-gate/build/res-custom ogc.c / ogc_shims.S), copied, never
 * requiring RES-Custom: the seven mode-table index lookups and the +0x10 value answer two rotating virtual
 * mode ids, a virtual profile id gets a base row and its canvas is declared, the picker hands out our entry.
 * Nothing in a firmware table and nothing in the camera's settings is written.
 *
 * Contract for the caller (slqs.c), on the UI thread (Bei 2026-10-29: no resident task, commit from the change event):
 *   ap_init     in sup_entry only (it claims the hook sites through the loader and arms them; every hook
 *               passes straight down until a commit).  mem: AP_MEM_BYTES, 8-aligned, resident, in the
 *               sup's cached block; it holds the veneers (code), so never free it.
 *   ap_request  from the QS change event itself (adjust / pick): commits right away.  The same selection twice is
 *               not recommitted (no LV flash).  A request that arrives while a commit runs only replaces the
 *               wanted selection; the running commit commits the latest once more when it is done.
 *   ap_flush    leave() / boot restore / after a recording: commit what is owed (a request refused while recording,
 *               or one that failed).  Never while recording.
 * Returns: AP_OK, AP_IDLE (nothing to do), AP_PENDING (owed: recording, or a commit is running), or a negative
 * AP_E_* (refused or failed: the camera is on stock then, see ap_status). */
#ifndef SENSORLAB_AP_H
#define SENSORLAB_AP_H
#include <stdint.h>

#define AP_ABI          3u               /* 2: event commit (no ap_tick), the standby flag; 3 (v0.7.26test):
                                            struct ap_status + the first-frame counters (38 words; v0.7.28test 41; v0.7.29test 43);
                                            v0.7.27test: no drop / repair, the counters are now checks only */

struct sl_svc;

/* The effective selection: what slqs.c's sq_apply() already computes (st->applied), plus the format. */
struct ap_sel {
    uint32_t bytes, abi;                 /* sizeof(struct ap_sel), AP_ABI */
    uint32_t valid;                      /* 0: no SensorLab recipe -> stock */
    uint32_t fmt;                        /* 0 = CinemaDNG (anything else -> stock) */
    uint32_t dcw, dch, rw, rh;           /* DC crop and RES: core_qualities_tol(dcw, dch, rw, rh, none, 2 %) */
    int32_t  key, hbin, vbin;            /* the recipe: readout key index, ISP CRCT bins (identify the quality) */
    uint32_t hm, vmax;                   /* its HMAX (checked) and the VMAX step of the selected rate */
    uint32_t fps_n, fps_d;               /* the rate the user selected (the DNG FrameRate when it is the real one) */
    uint32_t kh, kv, km;                 /* CRCT kernels 0..5 and SOFT 0 / STD 1 */
    uint32_t standby;                    /* 1: the standby LV runs our readout too (Bei 2026-10-29; gated, §12.2);
                                            0: refused (AP_E_STANDBY), v0.7.2test: CinemaDNG standby IS the record
                                            route (TAB3), so a stock standby would switch readout at REC start */
};

enum {
    AP_OK = 0, AP_IDLE = 1, AP_PENDING = 2,
    AP_E_ABI = -1,        /* bytes / abi of a struct */
    AP_E_HOOKS = -2,      /* ap_init: a site was not stock or a claim was refused: nothing armed */
    AP_E_NOTREADY = -3,   /* the mode descriptor is not built yet (before the first LV) */
    AP_E_RECIPE = -4,     /* the recipe is not one of core_qualities_tol(DC, RES) or its HMAX differs */
    AP_E_CORE = -5,       /* core_quality_plan / core_smc_create refused (detail = CORE_E_*) */
    AP_E_ISP = -6,        /* core_isp_plan refused (detail = ISP_WHY_*) */
    AP_E_RATE = -7,       /* the native frame-rate setter did not take the carrier */
    AP_E_FORMAT = -8,     /* not CinemaDNG */
    AP_E_BUSY = -9,       /* recording / XMP / MOV writer active when the commit had to happen */
    AP_E_REENTER = -10,
    AP_E_STANDBY = -11,   /* v0.7.2test: standby cannot run the record's readout (the route gate, or standby 0): stock.
                             The picker never answers by busy(): a standby on the stock route switching to ours at REC
                             start (v0.7.1test, HD 2K 11b 3x2) froze the camera (APPLY_DESIGN §14) */
};

struct ap_status {
    uint32_t bytes, abi;
    uint32_t armed;                      /* hooks installed */
    uint32_t active, cur, mode_id, pid;  /* a SensorLab slot is live: which, its virtual mode / profile ids */
    int32_t  result, detail;             /* the last commit's result, and its CORE_E_* / ISP_WHY_* detail */
    uint32_t commits, refusals, lv_reloads, owed;
    uint32_t picks, lookups, canvases, recrates;
    uint32_t standby_picks, carrier, carrier_sets, fast;   /* standby entries handed out; the carrier enum; setter
                                                              calls; 1 = engine > 99 (clock gate forced open) */
    uint32_t commit_us;                  /* the last commit's duration (tick_us), LV stop to LV start included */
    uint32_t gated, blacks;              /* v0.7.2test: commits refused by the route gate (AP_E_STANDBY; v0.5.1..0.7.1
                                            counted standby picks sent to stock); true-14 BlackLevel fixes */
    uint32_t defc;                       /* v0.7.25test: the live slot has its own converted defect table */
    uint32_t defc_builds, defc_skips, defc_loads;   /* tables converted / not converted (stock DEFC) / handed to DEFC */
    int32_t  defc_last;                  /* the last commit's: 1 built, 0 not needed, -1 buffer not loaded, -2 no
                                            directory, -3 no source table / too big, -4 recording, -5 converter
                                            failed, -6 no end mark */
    /* v0.7.26test (ABI 3): the first recorded frame's +1 row (notes/FIRST_FRAME_REPAIR.md) */
    uint32_t first_arms;                 /* takes whose first frame got the row-0 sentinel (our mode, at ContSet_Adr1) */
    uint32_t first_skips;                /* our mode, but its geometry / raster address was not usable: not armed */
    uint32_t first_checks;               /* armed first frames checked at their writer arrival (C038BDB4) */
    uint32_t first_intact;               /* ... sentinel intact there: BUFA1 never wrote row 0's end (shifted); kept */
    uint32_t first_ok;                   /* ... sentinel overwritten: a normal frame */
    uint32_t first_miss;                 /* the first arrival was not the armed frame (or no slot) */
    uint32_t trace_n, trace_lost;        /* v0.7.27test: records in this take's trace (sq_test 33), refused (full) */
    uint32_t resync_calls;               /* v0.7.28test: REC starts given the native sensor pause / resume + link resync */
    uint32_t resync_skips;               /* ... not given it: frame period <= 15 ms (v27's own guard) or no IMX410 v27 */
    uint32_t resync_us;                  /* the last one's duration (tick_us): two v27 halves and two VD waits */
    uint32_t resync_seen;                /* v0.7.29test: mode switches through either hooked SetImgMode_s site (any mode) */
    uint32_t resync_ours;                /* ... of them into the live slot's mode (= resync_calls + resync_skips) */
    uint32_t rec_bits;                   /* 0.0.3test: the depth of the CDNG table our entry was last handed from (8 / 10 /
                                            12; 0 none): 8 / 10 put that depth's plane codes on the record canvas */
    uint32_t low_picks;                  /* ... entries handed out from TAB1 / TAB2 (8 / 10-bit) */
};

#define AP_MEM_BYTES 0x37000u            /* checked by ap_init against sizeof(struct ap); v0.6.0: + the playback
                                            state and 8 HUD size tiles (NBR packs the firmware keeps: resident);
                                            v0.7.25test: + 0x20000, the two slots' defect tables (DMA-read);
                                            v0.7.27test: + 0x1000, the first-frame trace (12 x 224 B) */

int  ap_init(void *mem, uint32_t bytes, const struct sl_svc *svc);
int  ap_request(void *mem, const struct ap_sel *s);
int  ap_flush(void *mem);
int  ap_boot_ready(void *mem);          /* v0.7.35test: 1 = a commit may run now (boot apply; slqs.c) */
int  ap_raw_bits(void);                /* 0.0.3test: the stock CinemaDNG bit depth (8 / 10 / 12; 12 = also 14) */
int  ap_cine_now(void);                /* v0.7.37test: CinemaMode != STILL (the entry commit's gate) */
int  ap_lv_at_load(void *mem);         /* v0.7.37test: diagnostics: a CINE LV running now */
void ap_status_get(void *mem, struct ap_status *out);
uint32_t ap_now_us(void);                /* the firmware's microsecond tick (0xC002B6E0) */

/* v0.6.0 playback (notes/PLAYBACK_DESIGN.md):
 *   ap_idle     on the UI thread outside any commit (slqs.c: leave(), not recording): registers the HUD size tiles
 *               queued by the commits (one NBR pack per number the firmware has no tile for).  AP_OK / AP_IDLE.
 *   ap_pb_info  the playback state (struct ap_pb in ap.c; the shell reads it after playback, never during it)
 *   ap_pb_ctl   which 0: canvas mode (0 off / v1 fallback, 1 on [default], 2 only while a SensorLab slot is live);
 *               1: HUD tiles on/off [default off]; 2: PB_Resolution for non-stock clips (0xFFFFFFFF = stock);
 *               3: admission guard [default 1]: canvas on requires the selected clip's validated metadata;
 *               canvas off retains v1 stock-only refusal. Guard 0 is the legacy diagnostic path, not a product default.
 *               Returns the old value, or 0xFFFFFFFF for an unknown `which`. */
int  ap_idle(void *mem);
const void *ap_pb_info(void *mem);
const void *ap_trace_info(void *mem);    /* v0.7.27test: the first-frame trace (struct ap_trace in ap.c), read-only */
#ifdef AP_REC_DELAY_TEST
int ap_rd_attach(void *mem, void *rd);    /* 0.0.2test TEST build: the REC-start delay control + ring (struct ap_rd) */
#endif
uint32_t ap_pb_ctl(void *mem, uint32_t which, uint32_t value);

#endif
