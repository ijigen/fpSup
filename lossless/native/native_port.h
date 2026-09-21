#ifndef FPLOSSLESS_NATIVE_PORT_H
#define FPLOSSLESS_NATIVE_PORT_H
#include "binding.h"
#include "native_variable.h"

#define FPL_PORT_MAGIC 0x4c53504fu

/* `fpl_binding_ops` implemented over the v5.02 native variable call layer.
 *
 * This is the callback-to-policy adapter ONLY. It does not create the menu
 * row, render it, port choice permissions, install a hook, or provide any
 * codec/writer/header/playback proof. It therefore always strips
 * FPL_READY_UI: an integer write plus readback is not a rendered view, so ON
 * can never become selectable through this port alone. Do not add the bit
 * here to make the row look functional.
 *
 * Two contracts are deliberately NOT implemented and are never stubbed:
 *  - notification exclusion (`enter`/`leave`) must exclude ALL native
 *    notifications and subscriber changes before unsubscribe frees the copied
 *    native pair; and
 *  - quiescence must prove no queued source event or callback user remains.
 * Without an integrator-supplied provider both report FPL_BUSY, so close/reap
 * fail closed and keep the ticket, callback code and context alive.
 *
 * Producer facts come from a caller-supplied provider that reads actual
 * backend state, never from UI labels, mode IDs or this port's own value. */
struct fpl_port_facts {
    uint32_t (*read)(void *, struct fpl_context *);
    void *context;
};
/* enter returns FPL_OK only while holding exclusion, otherwise FPL_BUSY and
 * acquires nothing. quiesce returns FPL_OK only with proven drain; a provider
 * that returns FPL_OK unconditionally defeats the whole retirement design. */
struct fpl_port_exclusion {
    uint32_t (*enter)(void *);
    void (*leave)(void *);
    uint32_t (*quiesce)(void *);
    void *context;
};

struct fpl_port {
    uint32_t magic;
    struct fp_nv_state nv;
    struct fpl_binding *binding;
    const struct fpl_ticket *ticket;
    uintptr_t descriptor;
    struct fpl_port_facts facts;
    struct fpl_port_exclusion exclusion;
    uint32_t exclusion_held, callback_depth, publishing;
    uint32_t fault, last_nv, last_notify;
    uint32_t callbacks_seen, callbacks_refused, callbacks_rejected, echoes_suppressed;
    uint32_t presentation_unapplied, ui_claims_stripped, subscribe_uncertain;
    uint32_t retired;
};

/* Fresh zeroed storage. `app` must be a live initialized v5.02 app and `name`
 * stable FPL_PRIVATE_VARIABLE storage retained for the whole registry
 * lifetime. Providers may be null; their operations then fail closed. */
uint32_t fpl_port_init(struct fpl_port *, void *app, const char *name,
                       const struct fpl_port_facts *, const struct fpl_port_exclusion *);
/* Wire the coordinator before fpl_binding_attach. A port with a live
 * subscription never changes coordinator; the callback would outlive it. */
uint32_t fpl_port_bind(struct fpl_port *, struct fpl_binding *);
const struct fpl_binding_ops *fpl_port_ops(void);
/* Drop the retained ticket reference after quiescence was proven AND the
 * coordinator released it. Only then may the caller free ticket storage,
 * callback code or context. A fault stays sticky across release. */
uint32_t fpl_port_release(struct fpl_port *);
/* Explicit FP_NV_* -> FPL_* translation. Never yields FPL_OK for a native
 * error and never yields FPL_BUSY, which would invite a retry after a
 * possibly-published partial mutation. */
uint32_t fpl_port_translate(uint32_t native_result);
#endif
