#ifndef FPLOSSLESS_CONTROL_H
#define FPLOSSLESS_CONTROL_H

#include <stdint.h>

#define FPL_MAGIC 0x46504c53u
#define FPL_ABI 1u
#define FPL_TILE_WIDTH 512u
#define FPL_TILE_HEIGHT 368u
#define FPL_TILE_MAX 160u
/* Only the firmware adapter may supply these proofs; not menu preferences. */
#define FPL_READY_UI       (1u << 0)
#define FPL_READY_CODEC    (1u << 1)
#define FPL_READY_WRITER   (1u << 2)
#define FPL_READY_HEADER   (1u << 3)
#define FPL_READY_PLAYBACK (1u << 4)
#define FPL_READY_STORAGE  (1u << 5)
#define FPL_READY_REC_GATE (1u << 6)
#define FPL_READY_ALL 0x7fu
/* Explicit no-menu test entry omits UI only, never recorder safety proofs. */
#define FPL_READY_CAPTURE (FPL_READY_ALL & ~FPL_READY_UI)
/* A binding/port with uncertain visible state or in-flight teardown denies
 * ALL recording, including RAW with requested=0. This is not a readiness proof. */
#define FPL_BLOCK_REC (1u << 31)
/* NOT a readiness proof: the host-set row-pitch test switch (card.c
 * pitch_test, 2026-11-10). With it, a 10/14-bit width whose packed row is
 * not a multiple of 4 bytes is admitted anyway, to see on the camera what
 * the engine makes of it. Every other format check still applies. */
#define FPL_TEST_PITCH (1u << 30)

enum fpl_result {
    FPL_OK = 0, FPL_INVALID = 1, FPL_BUSY = 2,
    FPL_UNSUPPORTED = 3, FPL_NOT_READY = 4, FPL_FAULT = 5
};
enum fpl_clip { FPL_IDLE = 0, FPL_RAW = 1, FPL_LOSSLESS = 2, FPL_STOP = 3 };

struct fpl_state {
    uint32_t magic, abi, requested, clip, frames, fault, reserved0, reserved1;
};
/* Values describe the actual producer, not a mode name or menu label.
 * ready is evidence for THIS exact dimensions/bits/packing/rate/media tuple;
 * the adapter must invalidate/recompute it when any of those changes.
 * Format eligibility alone never supplies readiness or a DMA size bound. */
struct fpl_context {
    uint32_t firmware, cine, compression, bits, width, height;
    uint32_t fps_num, fps_den, media, ready;
};

/* Caller must serialize GUI/recorder access. This core does not own DMA,
 * locks, buffers, hooks or persisted settings. Boot reset requires capture
 * quiescence; it must never be used to abandon a live allocation. */
void fpl_boot(struct fpl_state *state);
uint32_t fpl_can_enable(const struct fpl_context *context);
uint32_t fpl_menu_value(const struct fpl_state *state);
uint32_t fpl_set(struct fpl_state *state, uint32_t enabled,
                 const struct fpl_context *context);
uint32_t fpl_begin(struct fpl_state *state, const struct fpl_context *context);
/* Always-on/no-menu build: invoke at the real REC boundary with fresh producer
 * facts, not at boot with invented readiness. Checks the same format, fault,
 * storage/codec/writer/header/playback/REC proofs as the menu path, omitting
 * only UI. Success selects lossless for this take; failure changes nothing.
 * No UI readiness bit is forged and this does not install a native adapter.
 * Caller must not share this entry with a live menu/binding instance. */
uint32_t fpl_begin_direct(struct fpl_state *state, const struct fpl_context *context);
/* Diagnostic completed-frame count saturates; it never limits take length.
 * In adaptive operation this counts compressed handoffs, not RAW pass-through. */
uint32_t fpl_frame_done(struct fpl_state *state);
uint32_t fpl_fail(struct fpl_state *state, uint32_t error);
/* Call only after writer/codec completion and cleanup, not merely REC key-up. */
uint32_t fpl_end(struct fpl_state *state, uint32_t cleanup_complete);

#endif
