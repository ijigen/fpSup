/* SensorLab-IMX410 core: the IMX410 custom readout planner (readout_cfg.plan), the sensor mode creator
 * (smc.create), the ISP custom formula (isp_formula.plan / row) and the quality enumeration that joins them
 * (isp-lab/host/quality.py: which qualities record a crop at a RES, at which fps), freestanding C.
 *
 * No libc, no heap, no writable globals: every result goes into a caller-owned struct; the only data is
 * const rodata from core_data.h (export_core.py output, reached PC-relative under -fropi).
 * Every function returns 0 or a negative CORE_E_* code: the same accept/reject decision as the Python. */
#ifndef SENSORLAB_CORE_H
#define SENSORLAB_CORE_H
#include <stdint.h>

/* ---- error codes (one per Python raise) ---- */
enum {
    CORE_OK = 0,
    CORE_E_KEY = -1,          /* readout key index out of range (BY_KEY KeyError) */
    CORE_E_WIDE = -2,         /* crop wider than the formats */
    CORE_E_H3V1 = -3,         /* 3:1 horizontal without a vertical group */
    CORE_E_UPSCALE = -4,      /* RWZM cannot upscale */
    CORE_E_NOWIN = -5,        /* vertical window not tested */
    CORE_E_HMAX = -6,         /* HMAX below the floor */
    CORE_E_ROWS = -7,         /* output rows > what the readout delivers */
    CORE_E_V016 = -8,         /* 0016 below the tested minimum */
    CORE_E_VMIN = -9,         /* fps needs VMAX < minimum */
    CORE_E_VMAX = -10,        /* fps needs VMAX > 16384 */
    CORE_E_WINROWS = -11,     /* window outside the readable rows */
    CORE_E_MARGIN = -12,      /* window above the readable rows (V3 margin) */
    CORE_E_SKIP = -13,        /* window above the readable rows (V3 skip) */
    CORE_E_SENSOR = -14,      /* too many sensor writes for CORE_MAX_SENSOR */
    CORE_E_FULL = -15,        /* qualities: more qualities than the caller's array holds */
    CORE_E_INPUT = -16,       /* qualities: a negative size, or a cap below 1 fps (the Python does not cover these) */
    CORE_E_ROWCROP = -17,     /* R16 row crop on a window, or not even inside the rows delivered */
    CORE_E_LOOKUP = -20,      /* smc: a dict lookup the Python does (KeyError): cls / bin / bits not in a table */
    CORE_E_CAT = -21,         /* smc: no cat rule for this class */
    CORE_E_LIN = -22,         /* smc: linear rule has no group */
    CORE_E_REG = -23,         /* smc: a write to a register that is not a table register */
    CORE_E_EXACT = -24,       /* smc: an 'exact' field core.c has no formula for (Python changed: port it) */
    CORE_E_ZERO = -25,        /* smc: division by zero (ZeroDivisionError in the Python) */
    CORE_E_RULE = -26,        /* smc: unknown rule kind in the data */
    CORE_E_ISP = -30,         /* isp: NotPossible (cause in core_isp_plan.why) */
};

/* why an isp plan is NotPossible */
enum { ISP_WHY_RWZM = 1, ISP_WHY_BIN, ISP_WHY_UNITYBIN, ISP_WHY_REC, ISP_WHY_CBIN_FIT, ISP_WHY_NO_F,
       ISP_WHY_EMPTY, ISP_WHY_BITS };

/* smc attributes (smc.attrs_from_plan); export_core.py reads this enum to index the rule data */
enum core_attr {
    A_CLS, A_HBIN, A_VBIN, A_VADD, A_BITS, A_WIDTH, A_HEIGHT, A_HMAX, A_TAIL, A_VMAX, A_F5C, A_X0, A_X1,
    A_Y0, A_Y1, A_FPSN, A_WIN, A_WSTART, A_WH, A_ROWS, A_ACQ, A_CROP, A_CONT, A_Y_SKIP, A_DYO,
    A_N
};

/* row tables, smc order; T_R10 last */
enum { T_TIM, T_META, T_R28, T_R38, T_R14, T_R68, T_REG, T_R10, T_N };

#define CORE_MAX_SENSOR 96

typedef struct {
    int32_t key, hdr, donor, bits, mh, mv, is_new;
    int32_t cw, ch, ow, oh;
    int32_t fmt_w, line_w, raster_w, out_h, y_skip, receiver_lines;
    int32_t sw_num, sw_den, sh_num, sh_den;      /* crop on the sensor grid as a rational (Python sw, sh floats) */
    int32_t fast_set, tim_line, r38_words;       /* 0 = None */
    int32_t hmax, vmax, vmin, rx_width, rx_end;  /* fps = CLK / (hmax * vmax), fps_max = CLK / (hmax * vmin) */
    int32_t n_sensor;
    uint32_t sensor[CORE_MAX_SENSOR][2];         /* (register, value) in plan order */
} core_plan;

typedef struct {
    int32_t attrs[A_N];
    uint8_t tim[0x20], meta[100], r28[0x28], r38[0x38], r14[0x14], r68[0x68], reg[0x288], r10[8];
} core_mode;

typedef struct {
    int32_t win_w, win_h, zh, zv, sx, sy, vbin, hbin, bits, hirate;
    int32_t has_rec, rec_w, rec_h;               /* has_rec 0 = Spec.rec None (the most R8 allows) */
} core_spec;

enum { PATH_B = 1, PATH_C, PATH_D, PATH_E1, PATH_E3 };

typedef struct {
    int32_t why;                                 /* ISP_WHY_* when NotPossible */
    int32_t rec[2], act[2], path, preview[4], source[2], visible[2], raster[2], standby[2];
    uint32_t words[65];                          /* only the words in mask are the formula's */
    uint32_t mask[3];                            /* bit i: word i (offset 4*i) is set by the formula */
} core_isp_result;

int core_n_keys(void);
int core_key_index(const char *name);            /* -1 when unknown */
/* fps = fps_num / fps_den (0 / anything = None); v016 < 0 = None; hmax 0 = None; rows < 0 = None (R16: a full-height
 * plan whose TIM keeps `rows` output rows, centred: y_skip moves down by the rows dropped above, out_h = rows) */
int core_readout_plan(int key, int cw, int ch, int ow, int oh, uint32_t fps_num, uint32_t fps_den,
                      int v016, int hmax, int hdr, int rows, core_plan *out);
int core_smc_create(const core_plan *p, core_mode *out);
int core_isp_plan(const core_spec *s, core_isp_result *out);
int core_isp_row(const core_spec *s, const uint32_t base[65], uint32_t out[65]);

/* ---- quality.py: the qualities that record exactly ow x oh from a cw x ch sensor crop ----
 * A quality = sensor merge mh x mv x AD (11 fast / 12 / 14) x CRCT hbin x vbin; each comes on its fastest readout
 * variant (window width w18 / w2C / ... is a speed choice, not a quality).  fps = CLK / (hm * VMAX) for every VMAX
 * vmin_lo..CD_VMAX_MAX; core_quality_plan / core_quality_spec give the full settings at any of them. */
#define CORE_MAX_QUAL (4 * 40)                   /* qualities never exceed readout keys x CRCT bins */

typedef struct {
    int32_t mh, mv, ad, hbin, vbin;              /* the quality */
    int32_t key, bits;                           /* the readout variant chosen; bits = the ISP plane depth */
    int32_t cw, ch, sw, sh, hmax;                /* readout_cfg.plan(key, cw, ch, sw, sh, fps, None, hmax or None): cw is
                                                    the crop + 16 when the R2 retry widened it, hmax the R11 HMAX
                                                    (min_line_clk of the raster width win_w) */
    int32_t rows;                                /* R16 row crop (ch is then 4040), -1 = none */
    int32_t capped;                              /* planned at the cap (fps_max > cap): the args' fps is the cap */
    int32_t hm, vmin_lo, vmin, vmax;             /* the plan's HMAX; vmin = fps_max at the readout's own blanking (what
                                                    the pick compares), vmin_lo = the planner's floor (0016 fallback);
                                                    vmax = this case's (vmin, or the cap's) */
    int32_t fps_milli;                           /* round(CLK / (hm * vmax), 3) * 1000: matrix 'fps', the pick key */
    int32_t win_w, win_h, zh, zv, rec_w, rec_h, path;   /* isp Spec window / zoom / rec, plan path (PATH_*) */
    int32_t seq;                                 /* the candidate's place in quality.candidates() order */
    /* visible tolerance (core_qualities_tol) and what the QS shows per recipe */
    int32_t lines;                               /* the plan's receiver lines (every line the sensor sends) */
    int32_t vis_w, vis_h;                        /* its own visible size: rec - stock 16 x 10 (DNG DefaultCrop) */
    int32_t rs_us;                               /* round(rolling_ms, 3) * 1000 = round(hm * lines / CLK * 1e3, 3), Python floats */
} core_quality;

/* R11 / R15 (isp_formula.min_line_clk): the HMAX readout `key` needs for a w px raster line, 0 when its floor is enough */
int core_line_hmax(int key, int w);
/* cap = cap_num / cap_den (cap_num 0 = None: uncapped, max fps); returns the number of qualities in out (matrix
 * order) or a CORE_E_* code: an error the Python raises through (CORE_E_ZERO for an empty crop / RES) */
int core_qualities(int cw, int ch, int ow, int oh, uint32_t cap_num, uint32_t cap_den, core_quality *out, int max);
/* quality.qualities(..., tol): tol = tol_num / tol_den (tol_den 0 = None: exactly core_qualities).  With a tol
 * every recipe whose raster is at most tol short of ow x oh per axis is listed too (quality.short_ok, r16_rows(tol),
 * isp(nom)); each carries vis_w / vis_h, the RES's nominal is (ow - 16, oh - 10). */
int core_qualities_tol(int cw, int ch, int ow, int oh, uint32_t cap_num, uint32_t cap_den, uint32_t tol_num,
                       uint32_t tol_den, core_quality *out, int max);
/* the readout plan of quality q at fps (fps_num 0 = fps_max; VMAX step v: fps = CD_CLK / (q->hm * v)) */
int core_quality_plan(const core_quality *q, uint32_t fps_num, uint32_t fps_den, core_plan *out);
void core_quality_spec(const core_quality *q, core_spec *out);  /* its isp Spec (core_isp_plan / core_isp_row) */

/* exposed for the exhaustive tests of the integer replacements of Python float expressions */
int core_r28(int32_t width, int32_t height, int32_t out[8]);
uint32_t core_fbits(uint32_t x);                 /* IEEE single bits of an integer (struct.pack('<f')) */
int64_t core_py_vmax(uint32_t hm, uint32_t num, uint32_t den);   /* round(72e6 / (hm * (num / den))), Python floats */
int32_t core_fps_milli(uint32_t clocks);         /* round(72e6 / clocks, 3) * 1000, Python floats */
/* JavaScript (num / den).toFixed(places) * 10^places: the double nearest num / den, rounded half up from its exact
 * value (ECMA-262 Number.prototype.toFixed); num, den < 2^53, places 0..3.  What a page shows for a rational. */
int64_t core_js_fixed(uint64_t num, uint64_t den, int places);
/* the tolerance predicates, exposed for the exhaustive tests: quality.short_ok and quality.r16_rows (-1 = None) */
int core_short_ok(int rec_w, int rec_h, int rw, int rh, uint32_t tol_num, uint32_t tol_den);
int core_r16_rows(int key, int ch, uint32_t tol_num, uint32_t tol_den);

#endif
