#ifndef FPLOSSLESS_WORKSPACE_LAYOUT_H
#define FPLOSSLESS_WORKSPACE_LAYOUT_H

#include "../control.h"

#define FPL_WORKSPACE_ALIGNMENT 1024u
#define FPL_WORKSPACE_MAX_WIDTH 6064u
#define FPL_WORKSPACE_MAX_HEIGHT 4042u

struct fpl_workspace_span { uint32_t offset, capacity; };
struct fpl_workspace_layout {
    uint32_t width, height, bits, tile_cols, tile_rows, tile_count;
    uint32_t raster_bytes, total_bytes;
    struct fpl_workspace_span source, output, codec_sizes, codec_scratch;
    struct fpl_workspace_span metadata, tile_offsets, tile_counts;
};

/* Reservation arithmetic ONLY, for a tightly packed Bayer raster. It neither
 * allocates memory nor proves native source ownership, codec/DMA limits,
 * source headroom, writer deferral, or readiness. Recording eligibility
 * (10/12/14 bit, 2026-11-10) is control.c's, not this planner's.
 *
 * The output span is align1024(raster_bytes): a benefit-only output BUDGET,
 * NOT a worst-case lossless-JPEG bound. A noisy image can exceed it. Do not
 * submit an encoder until its actual output-capacity enforcement is proven;
 * checking a returned size or a canary after DMA is not that proof. A result
 * fitting this span still requires validation and a full-file size comparison.
 * No readiness bits are returned by this planner.
 *
 * With copy_source=1, reserve a separate packed-source copy plus the tail up
 * to the next 1024-byte boundary. The caller must copy this frame and initialize
 * that tail before submission; this is NOT full tile-edge pixel padding.
 * copy_source=0 gives an empty source span. It does not authorize reading past
 * a native source: its ownership and rounded-length coverage remain external.
 *
 * Codec table and scratch each hold tile_count uint32_t words in separate
 * aligned spans. Scratch immediately follows the rounded codec table, matching
 * the native table+align1024(table_bytes) convention. TIFF offsets and counts
 * get two additional spans and are not aliases of the codec tables.
 * metadata_bytes is the caller's required metadata/header/IFD storage, excluding
 * these two TIFF tables (normally native header size 0x15400, not a fixed ABI).
 * A zero metadata request reserves an empty span, not metadata ownership.
 *
 * Every nonempty span and total_bytes is 1024-aligned; allocator base must also
 * be aligned. Offsets are relative to that one owned allocation. The caller
 * must separately check base+total_bytes against address-space wrap.
 * Width must be a multiple of 8 and height even, within the maxima above.
 * copy_source must be exactly 0 or 1. No allocations, globals, or native calls.
 * FPL_OK publishes the complete layout; on failure *out is unchanged.
 */
uint32_t fpl_workspace_plan(struct fpl_workspace_layout *out,
                            uint32_t width, uint32_t height, uint32_t bits,
                            uint32_t copy_source, uint32_t metadata_bytes);

#endif
