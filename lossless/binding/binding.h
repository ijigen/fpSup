#ifndef FPLOSSLESS_BINDING_H
#define FPLOSSLESS_BINDING_H
#include "ui_control.h"

#define FPL_BIND_MAGIC 0x4c534249u
#define FPL_TICKET_MAGIC 0x4c535449u
#define FPL_PRIVATE_VARIABLE "MV_fpLossless"
enum fpl_bind_phase { FPL_BIND_CLEAN, FPL_BIND_ACTIVE, FPL_BIND_QUARANTINED,
                      FPL_BIND_DRAINING };

struct fpl_binding;
/* Immutable after subscription. Storage and callback code must survive through
 * successful unsubscribe AND quiescence, including failures and warm resets. */
struct fpl_ticket {
    uint32_t magic, session, generation, owner;
    uintptr_t descriptor;
};
struct fpl_variable {
    uintptr_t descriptor;
    uint32_t type, subscription_present;
};
/* Port contract, NOT guessed firmware function signatures. Implementations
 * return FPL_OK on success. Calls are serialized with GUI and recorder access.
 * publish updates only this feature's variable/row and may synchronously echo
 * the subscription callback. A nonzero mutation result is never assumed atomic.
 * notification_enter must hold exclusion against ALL native notifications
 * before unsubscribe frees its native callback pair. It returns BUSY without
 * acquiring anything, or OK holding exclusion until notification_leave.
 * A check-then-unsubscribe without a held lock/owner-executor exclusion is not
 * sufficient. unsubscribe must verify ownership; quiesce must prove no active
 * or queued user of the ticket remains, including source row events and pending
 * native variable writes. Those sources must stay retired until reattachment.
 * Neither can be an unconditional stub
 * in a real port. context reads current producer/backend facts, not UI labels.
 * These operations do NOT call stock attach/detach: an eventual hook must
 * preserve those calls and arguments independently, even when this feature fails.
 */
struct fpl_binding_ops {
    uint32_t (*lookup)(void *, const char *, struct fpl_variable *);
    uint32_t (*register_integer)(void *, const char *, uint32_t);
    uint32_t (*subscribe)(void *, const struct fpl_ticket *);
    uint32_t (*unsubscribe)(void *, const struct fpl_ticket *);
    uint32_t (*quiesce)(void *, const struct fpl_ticket *);
    uint32_t (*context)(void *, struct fpl_context *);
    uint32_t (*read_integer)(void *, uintptr_t, uint32_t *);
    uint32_t (*publish)(void *, uintptr_t, const struct fpl_view *);
    uint32_t (*notification_enter)(void *);
    void (*notification_leave)(void *);
};
struct fpl_binding {
    uint32_t magic, session, generation, phase, publishing, in_call;
    uint32_t unsubscribe_attempted, last_port_error, healthy, uncertain;
    uintptr_t descriptor;
    struct fpl_ticket *ticket;
    struct fpl_ui ui;
    struct fpl_state *state;
    const struct fpl_binding_ops *ops;
    void *port;
};

/* init only accepts fresh zeroed storage, a non-reused resource session, and a
 * valid already-booted control state. Never zero/reset a live binding to retry. */
uint32_t fpl_binding_init(struct fpl_binding *, uint32_t session,
                         struct fpl_state *, const struct fpl_binding_ops *, void *);
uint32_t fpl_binding_attach(struct fpl_binding *, uint32_t page, uint32_t owner,
                           uint32_t private_row_present, struct fpl_ticket *);
uint32_t fpl_binding_notify(struct fpl_binding *, const struct fpl_ticket *, uintptr_t descriptor);
uint32_t fpl_binding_refresh(struct fpl_binding *);
/* close invalidates policy before native unsubscribe; reap waits for actual
 * quiescence. Only successful reap releases the borrowed ticket. On error,
 * keep module code, bridge, state and ticket alive; no automatic retry/reset. */
uint32_t fpl_binding_close(struct fpl_binding *);
uint32_t fpl_binding_reap(struct fpl_binding *);
/* Never invent a UI readiness proof. Successful normal page closure retains
 * existing readiness; an unhealthy/uninitialized/draining binding strips it. */
uint32_t fpl_binding_context(struct fpl_binding *, struct fpl_context *);
/* Mandatory recorder entry for a port using this coordinator. It reads fresh
 * facts and refuses all REC while publication/cancellation is uncertain. */
uint32_t fpl_binding_begin(struct fpl_binding *);
#endif
