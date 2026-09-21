#include "native_port.h"

/* Callback-to-policy adapter over the verified native variable calls.
 * No hook installation, row construction, rendering or recording path. */

/* Freestanding zeroing: an aggregate initializer would call a compiler
 * runtime helper (__aeabi_memclr4) that an installed adapter cannot assume. */
static void zero_words(volatile uint32_t *words, uint32_t count) {
    while (count--) *words++ = 0;
}
_Static_assert(sizeof(struct fpl_port) % sizeof(uint32_t) == 0, "port word size");
_Static_assert(sizeof(struct fpl_context) % sizeof(uint32_t) == 0, "context word size");

/* Content equality only: the coordinator and the integrator may hold distinct
 * copies of the literal. Native calls always use the retained storage given to
 * fpl_port_init, never the caller's pointer. */
static uint32_t private_name(const char *p) {
    static const char expected[] = FPL_PRIVATE_VARIABLE;
    uint32_t n;
    if (!p) return 0;
    for (n = 0; n < sizeof(expected); ++n)
        if (p[n] != expected[n]) return 0;
    return 1;
}
uint32_t fpl_port_translate(uint32_t native_result) {
    switch (native_result) {
    case FP_NV_OK: return FPL_OK;
    case FP_NV_INVALID: return FPL_INVALID;
    case FP_NV_FIRMWARE: return FPL_UNSUPPORTED;
    default: return FPL_FAULT; /* collision/stale/type/native/fault/diverged */
    }
}
/* A native error may already have published state; the port never retries and
 * never downgrades it to BUSY or NOT_READY. Faults are sticky. */
static uint32_t record(struct fpl_port *p, uint32_t native_result) {
    uint32_t result = fpl_port_translate(native_result);
    if (native_result != FP_NV_OK) p->last_nv = native_result;
    if (result == FPL_FAULT) p->fault = 1;
    return result;
}
static uint32_t usable(const struct fpl_port *p, uint32_t cleanup) {
    if (!p || p->magic != FPL_PORT_MAGIC || !p->nv.magic) return FPL_INVALID;
    if (p->fault && !cleanup) return FPL_FAULT;
    return FPL_OK;
}
/* The ticket, not a bare descriptor, proves which subscription is addressed. */
static uint32_t ours(const struct fpl_port *p, const struct fpl_ticket *t) {
    return t && p->ticket == t && t->magic == FPL_TICKET_MAGIC &&
           p->descriptor && t->descriptor == p->descriptor;
}

/* Runs in the native notification context. It may not allocate, block, free
 * the callback pair or assume the coordinator still accepts events. */
static int32_t port_callback(struct fp_nv_descriptor *descriptor, void *context) {
    struct fpl_port *p = context;
    uint32_t result;
    if (!p || p->magic != FPL_PORT_MAGIC || !p->binding || !p->ticket) return -1;
    ++p->callbacks_seen;
    /* Only an event for the descriptor this port claimed is forwarded, and it
     * is forwarded as the claimed handle, never as an unchecked pointer. */
    if (!p->descriptor || !p->nv.owned || descriptor != p->nv.owned) {
        ++p->callbacks_rejected;
        return -1;
    }
    if (p->publishing) { ++p->echoes_suppressed; return 0; } /* our own write */
    if (p->callback_depth) {
        /* Serialization is the caller's contract; a nested notification means
         * it does not hold. Refuse and stay faulted rather than interleave a
         * second policy transition over a half-applied one. */
        ++p->callbacks_refused;
        p->fault = 1;
        return -1;
    }
    p->callback_depth = 1;
    result = fpl_binding_notify(p->binding, p->ticket, p->descriptor);
    p->callback_depth = 0;
    p->last_notify = result;
    /* A rejected stale/retired event is correct policy, not a port fault. The
     * coordinator poisons itself when a port operation inside it failed. */
    if (result != FPL_OK) ++p->callbacks_rejected;
    return result == FPL_OK ? 0 : -1;
}

static uint32_t port_lookup(void *port, const char *name, struct fpl_variable *out) {
    struct fpl_port *p = port;
    struct fp_nv_snapshot snapshot;
    uint32_t result = usable(p, 0);
    if (result != FPL_OK) return result;
    if (!out || !private_name(name)) return FPL_INVALID;
    out->descriptor = 0; out->type = 0; out->subscription_present = 0;
    result = record(p, fp_nv_inspect(&p->nv, &snapshot));
    if (result != FPL_OK) return result;
    /* Report the registry as found. A matching name is not ownership, so the
     * descriptor is never adopted here; only registration claims one. */
    out->descriptor = snapshot.descriptor;
    out->type = snapshot.type;
    out->subscription_present = snapshot.subscription ? 1 : 0;
    return FPL_OK;
}
static uint32_t port_register(void *port, const char *name, uint32_t value) {
    struct fpl_port *p = port;
    struct fp_nv_snapshot snapshot;
    uint32_t result = usable(p, 0);
    if (result != FPL_OK) return result;
    if (!private_name(name)) return FPL_INVALID;
    if (value) return FPL_INVALID; /* the private variable is created OFF only */
    if (p->descriptor) return FPL_INVALID; /* one claim per registry lifetime */
    result = record(p, fp_nv_register_off(&p->nv));
    if (result != FPL_OK) return result;
    /* Adopt the handle the registry reports, cross-checked against the claimed
     * descriptor. fp_nv_snapshot is the 32-bit native handle type; the two are
     * the same value on the ARM32 target. */
    result = record(p, fp_nv_inspect(&p->nv, &snapshot));
    if (result != FPL_OK) return result;
    if (!snapshot.descriptor || snapshot.type || snapshot.value || snapshot.subscription ||
        snapshot.descriptor != (uint32_t)(uintptr_t)p->nv.owned) {
        p->fault = 1;
        return FPL_FAULT;
    }
    p->descriptor = snapshot.descriptor;
    return FPL_OK;
}
static uint32_t port_subscribe(void *port, const struct fpl_ticket *ticket) {
    struct fpl_port *p = port;
    uint32_t result = usable(p, 0);
    if (result != FPL_OK) return result;
    if (!p->binding || !ticket || ticket->magic != FPL_TICKET_MAGIC ||
        !p->descriptor || ticket->descriptor != p->descriptor) return FPL_INVALID;
    if (p->ticket || p->nv.callback) return FPL_INVALID; /* never two subscriptions */
    /* Retained before the call: a non-atomic native failure can still have
     * published the pair, so the callback context must stay addressable. */
    p->ticket = ticket;
    result = record(p, fp_nv_subscribe(&p->nv, port_callback, p));
    if (result != FPL_OK) {
        p->subscribe_uncertain = 1; /* keep ticket; cancellation is explicit */
        p->fault = 1;
    }
    return result;
}
static uint32_t port_unsubscribe(void *port, const struct fpl_ticket *ticket) {
    struct fpl_port *p = port;
    uint32_t result = usable(p, 1); /* reachable while faulted: this is cleanup */
    if (result != FPL_OK) return result;
    if (!ours(p, ticket)) return FPL_INVALID;
    /* The coordinator must already hold exclusion; this port cannot establish
     * it and must not pretend the native mutation lock is equivalent. */
    if (!p->exclusion_held) return FPL_INVALID;
    return record(p, fp_nv_unsubscribe_locked(&p->nv));
}
static uint32_t port_quiesce(void *port, const struct fpl_ticket *ticket) {
    struct fpl_port *p = port;
    struct fp_nv_snapshot snapshot;
    uint32_t result = usable(p, 1);
    if (result != FPL_OK) return result;
    if (!ours(p, ticket)) return FPL_INVALID;
    if (!p->exclusion.quiesce) return FPL_BUSY; /* no drain proof exists yet */
    result = p->exclusion.quiesce(p->exclusion.context);
    if (result != FPL_OK) return result;
    /* A provider's word is not enough: the registry must also show the pair
     * gone and the call layer must have released its copy. */
    if (p->nv.callback || p->nv.native_pair) { p->fault = 1; return FPL_FAULT; }
    result = record(p, fp_nv_inspect(&p->nv, &snapshot));
    if (result != FPL_OK) return result;
    if (snapshot.subscription || (uintptr_t)snapshot.descriptor != p->descriptor) {
        p->fault = 1;
        return FPL_FAULT;
    }
    /* Quiescence is proven, but the coordinator may still fail its own final
     * checks, so the ticket reference stays until fpl_port_release. */
    p->retired = 1;
    return FPL_OK;
}
static uint32_t port_context(void *port, struct fpl_context *out) {
    struct fpl_port *p = port;
    uint32_t result = usable(p, 0);
    if (!out) return FPL_INVALID;
    zero_words((volatile uint32_t *)out, sizeof(*out) / sizeof(uint32_t));
    if (result != FPL_OK) { out->ready = FPL_BLOCK_REC; return result; }
    if (!p->facts.read) { out->ready = FPL_BLOCK_REC; return FPL_NOT_READY; }
    result = p->facts.read(p->facts.context, out);
    if (result != FPL_OK) {
        zero_words((volatile uint32_t *)out, sizeof(*out) / sizeof(uint32_t));
        out->ready = FPL_BLOCK_REC;
        return result;
    }
    /* This port writes and reads an integer. It does not render the row, port
     * choice permissions or prove a visible view, so it can never carry a UI
     * readiness proof, whatever the facts provider claims. */
    if (out->ready & FPL_READY_UI) {
        out->ready &= ~FPL_READY_UI;
        ++p->ui_claims_stripped;
    }
    if (p->subscribe_uncertain) out->ready |= FPL_BLOCK_REC;
    return FPL_OK;
}
static uint32_t port_read(void *port, uintptr_t descriptor, uint32_t *out) {
    struct fpl_port *p = port;
    uint32_t result = usable(p, 0);
    if (result != FPL_OK) return result;
    if (!out || !p->descriptor || descriptor != p->descriptor) return FPL_INVALID;
    return record(p, fp_nv_read(&p->nv, out));
}
static uint32_t port_publish(void *port, uintptr_t descriptor, const struct fpl_view *view) {
    struct fpl_port *p = port;
    uint32_t result = usable(p, 0);
    if (result != FPL_OK) return result;
    if (!view || !p->descriptor || descriptor != p->descriptor) return FPL_INVALID;
    if (view->value > 1) return FPL_INVALID;
    /* Only the canonical value is expressible. Hiding the row and disabling a
     * choice need the page/permission ports, so they are counted as unapplied
     * rather than silently treated as displayed. Stripping FPL_READY_UI keeps
     * a wrongly selectable ON from ever being accepted by policy. */
    if (view->visible != 1 || view->on_enabled != view->off_enabled)
        ++p->presentation_unapplied;
    p->publishing = 1;
    result = record(p, fp_nv_set_canonical(&p->nv, view->value));
    p->publishing = 0;
    return result;
}
static uint32_t port_enter(void *port) {
    struct fpl_port *p = port;
    uint32_t result = usable(p, 1);
    if (result != FPL_OK) return result;
    if (p->exclusion_held) return FPL_BUSY; /* never nested by the coordinator */
    if (!p->exclusion.enter) return FPL_BUSY; /* acquires nothing; not a stub OK */
    result = p->exclusion.enter(p->exclusion.context);
    if (result == FPL_OK) p->exclusion_held = 1;
    else if (result == FPL_INVALID || result == FPL_UNSUPPORTED) result = FPL_BUSY;
    return result;
}
static void port_leave(void *port) {
    struct fpl_port *p = port;
    if (!p || p->magic != FPL_PORT_MAGIC || !p->exclusion_held) return;
    p->exclusion_held = 0;
    if (p->exclusion.leave) p->exclusion.leave(p->exclusion.context);
}

static const struct fpl_binding_ops port_ops = {
    port_lookup, port_register, port_subscribe, port_unsubscribe, port_quiesce,
    port_context, port_read, port_publish, port_enter, port_leave
};
const struct fpl_binding_ops *fpl_port_ops(void) { return &port_ops; }

uint32_t fpl_port_init(struct fpl_port *p, void *app, const char *name,
                       const struct fpl_port_facts *facts,
                       const struct fpl_port_exclusion *exclusion) {
    uint32_t result;
    if (!p || p->magic || !private_name(name)) return FPL_INVALID;
    if (facts && !facts->read) return FPL_INVALID;
    if (exclusion && ((exclusion->enter && !exclusion->leave) ||
                      (!exclusion->enter && exclusion->leave))) return FPL_INVALID;
    zero_words((volatile uint32_t *)p, sizeof(*p) / sizeof(uint32_t));
    result = fpl_port_translate(fp_nv_init(&p->nv, app, name));
    if (result != FPL_OK) {
        zero_words((volatile uint32_t *)p, sizeof(*p) / sizeof(uint32_t));
        return result;
    }
    if (facts) p->facts = *facts;
    if (exclusion) p->exclusion = *exclusion;
    p->magic = FPL_PORT_MAGIC;
    return FPL_OK;
}
uint32_t fpl_port_release(struct fpl_port *p) {
    if (!p || p->magic != FPL_PORT_MAGIC) return FPL_INVALID;
    if (!p->ticket) return FPL_OK;
    if (!p->retired || p->nv.callback || p->nv.native_pair) return FPL_BUSY;
    /* The coordinator must have finished its own retirement first; otherwise
     * it can still address this ticket. */
    if (!p->binding || p->binding->ticket || p->binding->phase != FPL_BIND_CLEAN)
        return FPL_BUSY;
    p->ticket = 0;
    p->retired = 0;
    p->subscribe_uncertain = 0;
    return FPL_OK;
}
uint32_t fpl_port_bind(struct fpl_port *p, struct fpl_binding *binding) {
    if (!p || p->magic != FPL_PORT_MAGIC || !binding) return FPL_INVALID;
    if (p->binding) return p->binding == binding ? FPL_OK : FPL_BUSY;
    if (p->ticket || p->nv.callback) return FPL_BUSY; /* callback would outlive it */
    p->binding = binding;
    return FPL_OK;
}
