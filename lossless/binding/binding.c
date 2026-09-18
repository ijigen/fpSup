#include "binding.h"

static uint32_t valid_state(const struct fpl_state *s) {
    return s && s->magic == FPL_MAGIC && s->abi == FPL_ABI &&
           s->requested <= 1 && s->clip <= FPL_STOP && !s->reserved0 && !s->reserved1;
}
static uint32_t valid(const struct fpl_binding *b) {
    return b && b->magic == FPL_BIND_MAGIC && b->session && b->ops && valid_state(b->state);
}
static uint32_t poison(struct fpl_binding *b, uint32_t error) {
    b->phase = FPL_BIND_QUARANTINED;
    b->last_port_error = error;
    b->healthy = 0;
    b->uncertain = 1;
    b->ui.attached = 0;
    return FPL_FAULT;
}
uint32_t fpl_binding_init(struct fpl_binding *b, uint32_t session,
                         struct fpl_state *s, const struct fpl_binding_ops *o, void *port) {
    if (!b || b->magic || !session || !valid_state(s) || !o || !o->lookup ||
        !o->register_integer || !o->subscribe || !o->unsubscribe || !o->quiesce ||
        !o->context || !o->read_integer || !o->publish ||
        !o->notification_enter || !o->notification_leave) return FPL_INVALID;
    *b = (struct fpl_binding){0};
    b->session = session;
    b->state = s;
    b->ops = o;
    b->port = port;
    fpl_ui_boot(&b->ui, session);
    b->magic = FPL_BIND_MAGIC;
    return FPL_OK;
}
uint32_t fpl_binding_context(struct fpl_binding *b, struct fpl_context *out) {
    uint32_t result;
    if (!out) return FPL_INVALID;
    *out = (struct fpl_context){0};
    if (!valid(b)) return FPL_INVALID;
    result = b->ops->context(b->port, out);
    if (result != FPL_OK) {
        *out = (struct fpl_context){0}; out->ready = FPL_BLOCK_REC; return result;
    }
    if (!b->healthy || (b->phase != FPL_BIND_ACTIVE && b->phase != FPL_BIND_CLEAN))
        out->ready &= ~FPL_READY_UI;
    if (b->uncertain || b->phase == FPL_BIND_QUARANTINED || b->phase == FPL_BIND_DRAINING)
        out->ready |= FPL_BLOCK_REC;
    return FPL_OK;
}
static uint32_t publish(struct fpl_binding *b, const struct fpl_context *c) {
    struct fpl_view view;
    uint32_t result;
    fpl_ui_view(&b->ui, b->state, c, &view);
    /* Hidden/non-CINE view fields default to zero in ui_control; do not turn
     * that presentation default into a change of the private preference. */
    view.value = fpl_menu_value(b->state);
    b->publishing = 1;
    result = b->ops->publish(b->port, b->descriptor, &view);
    b->publishing = 0;
    if (result == FPL_OK) b->healthy = 1;
    return result == FPL_OK ? FPL_OK : poison(b, result);
}
static uint32_t ensure_variable(struct fpl_binding *b) {
    struct fpl_variable variable = {0};
    uint32_t result = b->ops->lookup(b->port, FPL_PRIVATE_VARIABLE, &variable);
    if (result != FPL_OK) return poison(b, result);
    if (!variable.descriptor) {
        if (b->descriptor) return poison(b, FPL_INVALID); /* registry changed */
        result = b->ops->register_integer(b->port, FPL_PRIVATE_VARIABLE, 0);
        if (result != FPL_OK) return poison(b, result); /* possibly partial: no retry */
        result = b->ops->lookup(b->port, FPL_PRIVATE_VARIABLE, &variable);
        if (result != FPL_OK || !variable.descriptor || variable.type || variable.subscription_present)
            return poison(b, result ? result : FPL_INVALID);
        b->descriptor = variable.descriptor;
    }
    /* A matching name is not ownership. Never overwrite another subscriber or
     * adopt an unknown descriptor left by an earlier/failed module instance. */
    if (variable.descriptor != b->descriptor || variable.type || variable.subscription_present)
        return poison(b, FPL_INVALID);
    return FPL_OK;
}
uint32_t fpl_binding_attach(struct fpl_binding *b, uint32_t page, uint32_t owner,
                           uint32_t present, struct fpl_ticket *ticket) {
    struct fpl_context context;
    uint32_t result;
    if (!valid(b) || !owner || !ticket || ticket->magic) return FPL_INVALID;
    if (b->in_call) return FPL_BUSY;
    if (b->phase != FPL_BIND_CLEAN) return b->phase == FPL_BIND_ACTIVE ? FPL_BUSY : FPL_FAULT;
    if (page != FPL_PAGE_MAINB2 || present != 1) return FPL_UNSUPPORTED;
    if (b->generation == UINT32_MAX) return FPL_NOT_READY;
    b->in_call = 1;
    result = fpl_binding_context(b, &context);
    if (result != FPL_OK || context.cine != 1) {
        b->in_call = 0;
        return result != FPL_OK ? result : FPL_UNSUPPORTED;
    }
    result = ensure_variable(b);
    if (result != FPL_OK) { b->in_call = 0; return result; }
    ++b->generation;
    *ticket = (struct fpl_ticket){FPL_TICKET_MAGIC, b->session, b->generation, owner, b->descriptor};
    b->ticket = ticket;
    b->unsubscribe_attempted = 0;
    result = fpl_ui_attach(&b->ui, b->session, page, owner, b->generation, context.cine, present);
    if (result != FPL_OK) { b->in_call = 0; return poison(b, result); }
    /* No callback may process values until subscribe has succeeded. */
    b->phase = FPL_BIND_QUARANTINED;
    result = b->ops->subscribe(b->port, ticket);
    if (result != FPL_OK) { b->in_call = 0; return poison(b, result); }
    b->phase = FPL_BIND_ACTIVE;
    /* Allow the first display to reflect the port's existing UI proof. This
     * never supplies a missing proof, and poison clears it if publish fails. */
    b->healthy = 1;
    /* Refresh live facts after subscription; attach never assumes codec-ready. */
    result = fpl_binding_context(b, &context);
    if (result == FPL_OK) result = publish(b, &context);
    else result = poison(b, result);
    if (result == FPL_OK && b->uncertain) {
        /* The canonical value is repaired, but keep the public REC interlock
         * until the final view is published. Read port facts directly so only
         * our old interlock is omitted; a port-supplied block is preserved. */
        result = b->ops->context(b->port, &context);
        if (result == FPL_OK) result = publish(b, &context);
        else result = poison(b, result);
    }
    if (result == FPL_OK) b->uncertain = 0;
    b->in_call = 0;
    return result;
}
static uint32_t current(const struct fpl_binding *b, const struct fpl_ticket *t, uintptr_t descriptor) {
    return valid(b) && b->phase == FPL_BIND_ACTIVE && b->ui.attached == 1 && t && b->ticket == t &&
           t->magic == FPL_TICKET_MAGIC && t->session == b->session &&
           t->generation == b->generation && t->owner == b->ui.owner &&
           t->descriptor == b->descriptor && descriptor == b->descriptor;
}
uint32_t fpl_binding_notify(struct fpl_binding *b, const struct fpl_ticket *ticket, uintptr_t descriptor) {
    struct fpl_context context;
    uint32_t value, previous, result, shown;
    if (!current(b, ticket, descriptor)) return FPL_INVALID;
    if (b->publishing) return FPL_OK; /* synchronous echo, not a second user choice */
    if (b->in_call) return FPL_BUSY;
    b->in_call = 1;
    result = b->ops->read_integer(b->port, b->descriptor, &value);
    if (result == FPL_OK) result = fpl_binding_context(b, &context);
    if (result != FPL_OK) { b->in_call = 0; return poison(b, result); }
    previous = b->state->requested;
    result = fpl_ui_select(&b->ui, ticket->session, ticket->owner, ticket->generation,
                           b->state, &context, value);
    shown = publish(b, &context); /* restore canonical value even after rejection */
    if (shown != FPL_OK) b->state->requested = previous;
    b->in_call = 0;
    return shown == FPL_OK ? result : shown;
}
uint32_t fpl_binding_refresh(struct fpl_binding *b) {
    struct fpl_context context;
    uint32_t result;
    if (!valid(b) || b->phase != FPL_BIND_ACTIVE) return FPL_INVALID;
    if (b->in_call) return FPL_BUSY;
    b->in_call = 1;
    result = fpl_binding_context(b, &context);
    if (result == FPL_OK) result = publish(b, &context);
    else result = poison(b, result);
    b->in_call = 0;
    return result;
}
uint32_t fpl_binding_begin(struct fpl_binding *b) {
    struct fpl_context context;
    uint32_t result;
    if (!valid(b)) return FPL_INVALID;
    if (b->in_call || b->phase == FPL_BIND_DRAINING) return FPL_BUSY;
    if (b->uncertain || b->phase == FPL_BIND_QUARANTINED) return FPL_FAULT;
    b->in_call = 1;
    result = fpl_binding_context(b, &context);
    if (result == FPL_OK) result = fpl_begin(b->state, &context);
    else result = poison(b, result);
    b->in_call = 0;
    return result;
}
uint32_t fpl_binding_close(struct fpl_binding *b) {
    uint32_t result;
    if (!valid(b)) return FPL_INVALID;
    if (b->in_call) return FPL_BUSY;
    if (b->phase == FPL_BIND_CLEAN) return FPL_OK;
    if (!b->ticket || b->unsubscribe_attempted) return FPL_FAULT;
    b->in_call = 1;
    b->ui.attached = 0; /* reject callbacks before touching the native subscription */
    b->phase = FPL_BIND_QUARANTINED;
    /* Native unsubscribe immediately frees its copied pair. Ticket retention
     * alone cannot protect a notifier that already loaded that pair pointer. */
    result = b->ops->notification_enter(b->port);
    if (result != FPL_OK) { b->in_call = 0; return result; }
    b->unsubscribe_attempted = 1;
    result = b->ops->unsubscribe(b->port, b->ticket);
    b->ops->notification_leave(b->port);
    if (result == FPL_OK) b->phase = FPL_BIND_DRAINING;
    else poison(b, result);
    b->in_call = 0;
    return result == FPL_OK ? FPL_OK : FPL_FAULT;
}
uint32_t fpl_binding_reap(struct fpl_binding *b) {
    uint32_t result, value;
    if (!valid(b)) return FPL_INVALID;
    if (b->in_call) return FPL_BUSY;
    if (b->phase != FPL_BIND_DRAINING || !b->ticket) return FPL_INVALID;
    b->in_call = 1;
    result = b->ops->quiesce(b->port, b->ticket);
    if (result == FPL_OK) {
        /* Invalidated callbacks may have ignored a native value write while
         * close was BUSY. Drain alone does not repair that divergence. */
        result = b->ops->read_integer(b->port, b->descriptor, &value);
        if (result != FPL_OK || value != fpl_menu_value(b->state)) {
            b->healthy = 0; b->uncertain = 1;
        }
        if (result != FPL_OK) {
            b->last_port_error = result;
            b->in_call = 0;
            return FPL_FAULT; /* retain ticket and draining state */
        }
        b->ticket = 0;
        b->phase = FPL_BIND_CLEAN;
        b->ui.owner = b->ui.generation = 0;
        b->unsubscribe_attempted = 0;
    }
    b->in_call = 0;
    return result;
}
