#ifndef FPLOSSLESS_CONTROL_H
#define FPLOSSLESS_CONTROL_H

#include <stdint.h>

#define FPL_MAGIC 0x46504c53u
#define FPL_ABI 1u
/* Only the firmware adapter may supply these proofs; not menu preferences. */
#define FPL_READY_UI       (1u << 0)
#define FPL_READY_CODEC    (1u << 1)
#define FPL_READY_WRITER   (1u << 2)
#define FPL_READY_HEADER   (1u << 3)
#define FPL_READY_PLAYBACK (1u << 4)
#define FPL_READY_STORAGE  (1u << 5)
#define FPL_READY_REC_GATE (1u << 6)
#define FPL_READY_ALL 0x7fu
/* A binding/port with uncertain visible state or in-flight teardown denies
 * ALL recording, including RAW with requested=0. This is not a readiness proof. */
#define FPL_BLOCK_REC (1u << 31)

enum fpl_result {
    FPL_OK = 0, FPL_INVALID = 1, FPL_BUSY = 2,
    FPL_UNSUPPORTED = 3, FPL_NOT_READY = 4, FPL_FAULT = 5
};
enum fpl_clip { FPL_IDLE = 0, FPL_RAW = 1, FPL_LOSSLESS = 2, FPL_STOP = 3 };

struct fpl_state {
    uint32_t magic, abi, requested, clip, frames, fault, reserved0, reserved1;
};
/* Values describe the actual producer, not a mode name or menu label. */
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
uint32_t fpl_frame_done(struct fpl_state *state);
uint32_t fpl_fail(struct fpl_state *state, uint32_t error);
/* Call only after writer/codec completion and cleanup, not merely REC key-up. */
uint32_t fpl_end(struct fpl_state *state, uint32_t cleanup_complete);

#endif
