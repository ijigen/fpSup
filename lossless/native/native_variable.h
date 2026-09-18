#ifndef FPLOSSLESS_NATIVE_VARIABLE_H
#define FPLOSSLESS_NATIVE_VARIABLE_H
#include <stdint.h>

/* ARM32 v5.02 native call layer. No hook, lock, renderer or readiness proof. */
struct fp_nv_descriptor;
typedef int32_t (*fp_nv_callback)(struct fp_nv_descriptor *, void *);
enum fp_nv_result {
    FP_NV_OK = 0, FP_NV_INVALID = 0x100, FP_NV_COLLISION, FP_NV_STALE,
    FP_NV_TYPE, FP_NV_NATIVE, FP_NV_FAULT, FP_NV_FIRMWARE, FP_NV_DIVERGED
};
struct fp_nv_state {
    uint32_t magic;
    void *app;
    const char *name;
    struct fp_nv_descriptor *owned;
    fp_nv_callback callback;
    void *callback_context;
    void *native_pair;
    uint32_t fault, last_native;
};
struct fp_nv_snapshot { uint32_t descriptor, type, value, subscription; };

/* Fresh zeroed storage; app must be a live initialized v5.02 app. name must be
 * stable "MV_fpLossless" storage retained for the whole registry lifetime.
 * Exact function prologue checks catch conflicts, not a whole-image identity.
 * Every operation requires serialized registry/GUI ownership. They do not lock.
 * Outputs and state must be separate, valid caller-owned allocations. */
uint32_t fp_nv_init(struct fp_nv_state *, void *app, const char *name);
uint32_t fp_nv_inspect(struct fp_nv_state *, struct fp_nv_snapshot *);
uint32_t fp_nv_register_off(struct fp_nv_state *);
uint32_t fp_nv_read(struct fp_nv_state *, uint32_t *out);
uint32_t fp_nv_subscribe(struct fp_nv_state *, fp_nv_callback, void *context);
/* This writes only canonical 0/1 and suppresses app callbacks, NOT native
 * component dispatch. Success proves integer readback, not rendered UI.
 * Nonzero may follow a write. Fault is sticky; do not retry/reset live state. */
uint32_t fp_nv_set_canonical(struct fp_nv_state *, uint32_t value);
/* Caller MUST hold exclusion against all native notifications and subscriber
 * changes before calling; this function cannot establish that exclusion.
 * It verifies exact pair pointer/callback/context. After success, callback
 * code/context still cannot be freed until source events/users are drained. */
uint32_t fp_nv_unsubscribe_locked(struct fp_nv_state *);
#endif
