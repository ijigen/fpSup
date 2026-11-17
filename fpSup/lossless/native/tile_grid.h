#ifndef FPLOSSLESS_TILE_GRID_H
#define FPLOSSLESS_TILE_GRID_H
#include <stdint.h>
#include "../control.h"

/* The tile size one frame is compressed with. Every consumer -- the codec
 * job, the workspace tables, the trailing IFD -- asks this, so they agree.
 *
 * Legal tiles: the engine's (FUN_c062fff8) width 32..512 in steps of 32 and
 * height 2..512 even, narrowed to TIFF's rule that TileWidth and TileLength
 * are multiples of 16. At most FPL_TILE_MAX tiles (the commit's table).
 *
 * `force` = width << 16 | height, for measuring on the camera; 0, or a
 * force that is not a legal tile for this frame, gives the default below.
 * No division: the camera build has no __aeabi_uidiv. */

static inline uint32_t fpl_tile_steps(uint32_t n, uint32_t t) {
    uint32_t q = 0;
    while (n > 0) { ++q; n = n > t ? n - t : 0; }
    return q;
}

static inline uint32_t fpl_tile_legal(uint32_t width, uint32_t height,
                                      uint32_t tw, uint32_t th) {
    if (tw < 32u || tw > 512u || (tw & 31u)) return 0;
    if (th < 16u || th > 512u || (th & 15u)) return 0;
    if (!width || !height || width > 0x4000u || height > 0x4000u) return 0;
    return fpl_tile_steps(width, tw) * fpl_tile_steps(height, th) <= FPL_TILE_MAX;
}

/* The default: the legal grid the engine finishes soonest. Measured on the
 * camera (2026-10-07, OG3K 3024x2010, seven grids, every one within 0.5 ms):
 *     job ms = 4.26 x padded Mpixel + 0.137 x tiles + 5.3
 * so a tile costs as much as FPL_TILE_PIXELS padded pixels. An equal cost keeps
 * the first found (the narrower tile): with areas in units of 32 x 16 and
 * 32250 not a multiple of 512, equal costs always have equal tile counts.
 * 16 widths x 32 heights, once per frame: a few thousand steps. */
#define FPL_TILE_PIXELS 32250u

static inline void fpl_tile_grid(uint32_t width, uint32_t height, uint32_t force,
                                 uint32_t *tw, uint32_t *th) {
    uint32_t fw = force >> 16, fh = force & 0xffffu, best = UINT32_MAX;
    if (force && fpl_tile_legal(width, height, fw, fh)) {
        *tw = fw;
        *th = fh;
        return;
    }
    *tw = FPL_TILE_WIDTH;
    *th = FPL_TILE_HEIGHT;
    if (!width || !height || width > 0x4000u || height > 0x4000u) return;
    for (uint32_t w = 32u; w <= 512u; w += 32u) {
        /* 2026-11-17: never two tiles exactly across. LibRaw (lossless_dng_load_raw) treats a 2-component
         * tile with 2 x tile width == image width as one row holding both halves, and puts our rows in the
         * wrong place -- SQ 1024x1024 at 512x512 read back with rows 1, 3, 7, 11 ... empty, while the stream
         * itself decodes right (an independent decoder; validation/20261117-lossless-stale). */
        if (width == 2u * w) continue;
        uint32_t across = fpl_tile_steps(width, w);
        for (uint32_t h = 16u; h <= 512u; h += 16u) {
            uint32_t down = fpl_tile_steps(height, h), tiles = across * down, cost;
            if (tiles > FPL_TILE_MAX) continue;
            cost = across * w * down * h + tiles * FPL_TILE_PIXELS;
            if (cost < best) {
                best = cost;
                *tw = w;
                *th = h;
            }
        }
    }
}
#endif
