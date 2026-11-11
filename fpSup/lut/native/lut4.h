/* Public LUT-specific service, svc->find(svc, LUT4_SERVICE_ID).
 * Loader v4/services v6 (private Color page). No Live View, buffer lease or calibration is implied.
 * All callback pointers and state remain owned by the sup for this boot.
 */
#ifndef FPSUP_LUT4_H
#define FPSUP_LUT4_H
#include <stdint.h>
#define LUT4_SERVICE_ID 0x3454554Cu
struct lut4_state;
struct lut4_status {
    uint32_t version;
    int32_t asset_status, model_status;
    uint32_t live_view_connected, color, gamma, strength_percent;
    uint32_t rendered_samples, outside_1d_channels, outside_3d_channels;
    int32_t last_error;
};
struct lut4_api {
    uint32_t magic, version;
    struct lut4_state *state;
    int (*select)(struct lut4_state *, uint32_t color, uint32_t gamma);
    int (*strength)(struct lut4_state *, uint32_t percent); /* 0/25/50/75/100 */
    int (*enable)(struct lut4_state *, uint32_t on);       /* on -> -13: no backend */
    /* Calibrated scene-linear XYZ D65, 18% Y=.18; signed Q20 in/out. Output
     * is full normalized Rec.709/Gamma2.4, negative/overrange preserved.
     * Caller owns both aligned detached arrays; same-array in-place is OK,
     * other overlap rejected. Count 1..4096, XYZ +-64, selected linear +-128.
     * This is a reference batch processor, not an established realtime path.
     * Returns 0, -10 missing, -11 invalid, -12 pending model, -14 bad input.
     */
    int (*render)(struct lut4_state *, const int32_t *, int32_t *, uint32_t count);
    int (*status)(struct lut4_state *, struct lut4_status *);
    /* version 2: make library entry `index` the monitored LUT (0xFFFFFFFF = Off);
     * the native COLOR list calls it.  Enabled and set-up entries only; saved. */
    int (*pick)(struct lut4_state *, uint32_t index);
    /* version 2: the COLOR list (2026-11-07: through COL-Share, cols.c): 0 = COL-Share
     * has our rows, 1 no library, 8 no COL-Share on the card (yet), 9 provide refused,
     * 0x10 | add()'s refusal, 0x99 bisect build; read only. */
    uint32_t clist;
};
#endif
