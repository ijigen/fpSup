/* Host-only adapter. The generated camera_qr.h contains the current slqs.c
 * encoder verbatim; neither camera hardware nor ARM hooks are linked here. */
#include <stdint.h>
#include <string.h>
#include "core.h"
#include "core_data.h"

typedef uint32_t u32;
typedef uint8_t u8;

/* Only the fields used by the pure encoder, not its camera drawing state. */
#include "camera_qr_constants.h"
struct qr {
    u32 n, mask;
    char url[QR_DATA_CW + 1u];
    u8 cw[QR_DATA_CW + QR_EC_CW], gen[QR_EC_CW];
    u8 mat[QR_N * QR_N + 3u], fn[QR_N * QR_N + 3u], best[QR_N * QR_N + 3u];
};
static u32 udiv(u32 n, u32 d) { return n / d; }
static int sq_max(int a, int b) { return a > b ? a : b; }
static int sq_abs(int a) { return a < 0 ? -a : a; }
static u32 sq_len(const char *s) { return (u32)strlen(s); }
#include "camera_qr.h"

int preview_quality_size(void) { return (int)sizeof(core_quality); }
int preview_max_qualities(void) { return CORE_MAX_QUAL; }
int preview_clock(void) { return CD_CLK; }
int preview_vmax_max(void) { return CD_VMAX_MAX; }
const char *preview_key_name(int key)
{
    return key >= 0 && key < CD_N_KEYS ? cd_key_name[key] : 0;
}
const char *preview_path_name(int path)
{
    switch (path) {
    case PATH_B: return "B";
    case PATH_C: return "C";
    case PATH_D: return "D";
    case PATH_E1: return "E1";
    case PATH_E3: return "E3";
    default: return 0;
    }
}
int preview_qr(const char *url, u8 *out)
{
    struct qr q = {0};
    if (strlen(url) >= sizeof q.url) return -1;
    memcpy(q.url, url, strlen(url) + 1u);
    if (qr_encode(&q)) return -1;
    for (u32 i = 0; i < QR_N * QR_N; i++) out[i] = q.mat[i] == 0;
    return (int)q.n;
}

/* What the sensor sends for quality q (its readout plan at fps_max; the geometry does not depend on fps):
 * out = {result, fmt_w, line_w, raster_w, out_h, mh, mv, windowed (0003), window start row (0022/0023), y_skip}.
 * fmt_w / line_w / raster_w / out_h are in the sensor's binned output pixels; the page draws fmt_w * mh x out_h * mv. */
int preview_readout(const core_quality *q, int32_t out[10])
{
    core_plan p;
    int r = core_quality_plan(q, 0, 1, &p);
    for (int i = 0; i < 10; i++) out[i] = 0;
    out[0] = r;
    if (r) return r;
    int32_t windowed = 0, lo = 0, hi = 0;
    for (int i = 0; i < p.n_sensor; i++) {               /* dict(sensor): the last write wins */
        if (p.sensor[i][0] == 0x0003) windowed = (int32_t)p.sensor[i][1];
        if (p.sensor[i][0] == 0x0022) lo = (int32_t)p.sensor[i][1];
        if (p.sensor[i][0] == 0x0023) hi = (int32_t)p.sensor[i][1];
    }
    out[1] = p.fmt_w; out[2] = p.line_w; out[3] = p.raster_w; out[4] = p.out_h; out[5] = p.mh; out[6] = p.mv;
    out[7] = windowed; out[8] = windowed ? (hi << 8 | lo) : 0; out[9] = p.y_skip;
    return 0;
}
int preview_win_top(void) { return CD_WIN_TOP; }
