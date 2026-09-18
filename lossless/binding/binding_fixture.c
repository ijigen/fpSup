#include "binding.h"
#define CHECK(x) do { if (!(x)) return __LINE__; } while (0)
struct fake {
    struct fpl_binding binding;
    struct fpl_state state;
    struct fpl_context context;
    struct fpl_ticket first, second, unknown;
    struct fpl_view shown;
    uintptr_t descriptor;
    uint32_t type, subscribed, value;
    uint32_t lookups, registrations, subscriptions, unsubscriptions, quiescences, publishes, reads;
    uint32_t fail_lookup_at, fail_register, fail_subscribe, fail_publish, fail_unsubscribe, fail_publish_at;
    uint32_t busy_quiesce, fail_context, fail_read, echo, echo_result, close_result;
    uint32_t exclusive, exclusion_busy, enters, leaves;
};
static uint32_t lookup(void *p, const char *name, struct fpl_variable *v) {
    struct fake *f = p; (void)name;
    if (++f->lookups == f->fail_lookup_at) return FPL_FAULT;
    *v = (struct fpl_variable){f->descriptor, f->type, f->subscribed}; return FPL_OK;
}
static uint32_t reg(void *p, const char *name, uint32_t value) {
    struct fake *f = p; (void)name; ++f->registrations;
    f->descriptor = 0x123400; f->value = value;
    return f->fail_register ? FPL_FAULT : FPL_OK; /* failure may already publish */
}
static uint32_t subscribe(void *p, const struct fpl_ticket *t) {
    struct fake *f = p; (void)t; ++f->subscriptions; f->subscribed = 1;
    return f->fail_subscribe ? FPL_FAULT : FPL_OK;
}
static uint32_t unsubscribe(void *p, const struct fpl_ticket *t) {
    struct fake *f = p; ++f->unsubscriptions;
    if (!f->exclusive) return FPL_INVALID;
    f->echo_result = fpl_binding_notify(&f->binding, t, f->descriptor);
    if (f->fail_unsubscribe) return FPL_FAULT;
    f->subscribed = 0; return FPL_OK;
}
static uint32_t quiesce(void *p, const struct fpl_ticket *t) {
    struct fake *f = p; (void)t; ++f->quiescences;
    return f->busy_quiesce ? FPL_BUSY : FPL_OK;
}
static uint32_t context(void *p, struct fpl_context *out) {
    struct fake *f = p; *out = f->context; return f->fail_context ? FPL_FAULT : FPL_OK;
}
static uint32_t read_integer(void *p, uintptr_t d, uint32_t *out) {
    struct fake *f = p; (void)d; ++f->reads; *out = f->value;
    return f->fail_read ? FPL_FAULT : FPL_OK;
}
static uint32_t publish(void *p, uintptr_t d, const struct fpl_view *view) {
    struct fake *f = p; ++f->publishes; f->shown = *view; f->value = view->value;
    if (f->echo) {
        f->echo_result = fpl_binding_notify(&f->binding, f->binding.ticket, d);
        f->close_result = fpl_binding_close(&f->binding);
    }
    return (f->fail_publish || f->publishes == f->fail_publish_at) ? FPL_FAULT : FPL_OK;
}
static uint32_t enter(void *p) {
    struct fake *f = p; ++f->enters;
    if (f->exclusion_busy || f->exclusive) return FPL_BUSY;
    f->exclusive = 1; return FPL_OK;
}
static void leave(void *p) {
    struct fake *f = p; ++f->leaves; f->exclusive = 0;
}
static const struct fpl_binding_ops ops = {lookup, reg, subscribe, unsubscribe, quiesce,
                                         context, read_integer, publish, enter, leave};
static uint32_t attach(struct fake *f) {
    return fpl_binding_attach(&f->binding, FPL_PAGE_MAINB2, 456, 1, &f->first);
}
static uint32_t change(struct fake *f, uint32_t value) {
    f->value = value;
    return fpl_binding_notify(&f->binding, f->binding.ticket, f->descriptor);
}
/* One fresh fixture per scenario; returns the failed C line, or zero. */
int binding_case(uint32_t number) {
    struct fake f = {0};
    struct fpl_context c;
    uint32_t count;
    f.context = (struct fpl_context){502,1,1,12,1936,1090,24000,1001,1,FPL_READY_ALL};
    fpl_boot(&f.state);
    CHECK(fpl_binding_init(&f.binding, 7, &f.state, &ops, &f) == FPL_OK);
    switch (number) {
    case 0: /* default OFF, own var registered once, no recorder */
        CHECK(attach(&f) == FPL_OK);
        CHECK(f.registrations == 1 && f.subscriptions == 1 && f.shown.value == 0 && f.shown.visible == 1);
        CHECK(f.state.clip == FPL_IDLE && f.state.frames == 0); break;
    case 1: /* backend proofs absent -> rejected ON is explicitly restored */
        f.context.ready = 0; CHECK(attach(&f) == FPL_OK);
        CHECK(f.shown.on_enabled == 0 && change(&f,1) == FPL_NOT_READY);
        CHECK(f.value == 0 && f.state.requested == 0); break;
    case 2: /* successful toggle affects only feature state */
        CHECK(attach(&f) == FPL_OK && change(&f,1) == FPL_OK);
        CHECK(f.value == 1 && f.state.requested == 1 && f.state.clip == FPL_IDLE);
        CHECK(change(&f,0) == FPL_OK && f.state.requested == 0); break;
    case 3: /* recorder lock even if a native write arrives anyway */
        CHECK(attach(&f) == FPL_OK && fpl_begin(&f.state,&f.context) == FPL_OK);
        CHECK(change(&f,1) == FPL_BUSY && f.value == 0 && f.state.clip == FPL_RAW);
        CHECK(f.shown.off_enabled == 0 && f.shown.on_enabled == 0); break;
    case 4: /* malformed integer not coerced to boolean */
        CHECK(attach(&f) == FPL_OK && change(&f,2) == FPL_INVALID);
        CHECK(f.value == 0 && f.state.requested == 0); break;
    case 5: /* unrelated page never invokes variable operations */
        CHECK(fpl_binding_attach(&f.binding,31,456,1,&f.first) == FPL_UNSUPPORTED);
        CHECK(fpl_binding_attach(&f.binding,10,456,0,&f.first) == FPL_UNSUPPORTED);
        CHECK(f.lookups == 0 && f.registrations == 0 && f.publishes == 0); break;
    case 6: /* unknown pre-existing private name isn't ownership */
        f.descriptor = 0x999900; CHECK(attach(&f) == FPL_FAULT);
        CHECK(f.registrations == 0 && f.subscriptions == 0 && f.publishes == 0); break;
    case 7: /* non-atomic registration failure is never blindly retried */
        f.fail_register = 1; CHECK(attach(&f) == FPL_FAULT && f.descriptor);
        CHECK(attach(&f) == FPL_FAULT && f.registrations == 1);
        CHECK(fpl_binding_close(&f.binding) == FPL_FAULT); break;
    case 8: /* lookup missing after publication is quarantined */
        f.fail_lookup_at = 2; CHECK(attach(&f) == FPL_FAULT);
        CHECK(attach(&f) == FPL_FAULT && f.registrations == 1 && f.subscriptions == 0); break;
    case 9: /* subscribe failure may still leave a borrowed ticket */
        f.fail_subscribe = 1; CHECK(attach(&f) == FPL_FAULT && f.binding.ticket == &f.first);
        CHECK(change(&f,1) == FPL_INVALID && f.state.requested == 0);
        CHECK(fpl_binding_close(&f.binding) == FPL_OK && f.binding.ticket);
        CHECK(fpl_binding_reap(&f.binding) == FPL_OK && !f.binding.ticket); break;
    case 10: /* cancel invalidates first; cannot reclaim at unsubscribe alone */
        CHECK(attach(&f) == FPL_OK); f.busy_quiesce = 1;
        CHECK(fpl_binding_close(&f.binding) == FPL_OK && f.echo_result == FPL_INVALID);
        CHECK(fpl_binding_reap(&f.binding) == FPL_BUSY && f.binding.ticket == &f.first);
        CHECK(fpl_binding_attach(&f.binding,10,456,1,&f.second) == FPL_FAULT);
        f.busy_quiesce = 0; CHECK(fpl_binding_reap(&f.binding) == FPL_OK);
        CHECK(fpl_binding_attach(&f.binding,10,456,1,&f.second) == FPL_OK);
        CHECK(f.registrations == 1 && f.second.generation == 2);
        CHECK(fpl_binding_notify(&f.binding,&f.first,f.descriptor) == FPL_INVALID); break;
    case 11: /* uncertain cancellation retained, not retried implicitly */
        CHECK(attach(&f) == FPL_OK); f.fail_unsubscribe = 1;
        CHECK(fpl_binding_close(&f.binding) == FPL_FAULT && f.binding.ticket);
        CHECK(fpl_binding_close(&f.binding) == FPL_FAULT && f.unsubscriptions == 1);
        CHECK(fpl_binding_reap(&f.binding) == FPL_INVALID); break;
    case 12: /* synchronous publication echo cannot recurse or close the lease */
        f.echo = 1; CHECK(attach(&f) == FPL_OK && f.echo_result == FPL_OK);
        CHECK(change(&f,1) == FPL_OK && f.echo_result == FPL_OK && f.close_result == FPL_BUSY);
        CHECK(f.reads == 1 && f.publishes == 2 && f.state.requested == 1); break;
    case 13: /* display/write failure rolls back acceptance and strips UI proof */
        CHECK(attach(&f) == FPL_OK); f.fail_publish = 1;
        CHECK(change(&f,1) == FPL_FAULT && f.state.requested == 0);
        CHECK(fpl_binding_context(&f.binding,&c) == FPL_OK && !(c.ready & FPL_READY_UI));
        CHECK(c.ready & FPL_BLOCK_REC);
        CHECK(fpl_begin(&f.state,&c) == FPL_FAULT && fpl_binding_begin(&f.binding) == FPL_FAULT);
        CHECK(f.state.clip == FPL_IDLE && f.value == 1); /* native/UI may still show ON */
        CHECK(fpl_binding_close(&f.binding) == FPL_OK && fpl_binding_reap(&f.binding) == FPL_OK);
        CHECK(fpl_binding_begin(&f.binding) == FPL_FAULT); /* drain != UI repair */
        f.fail_publish = 0;
        CHECK(fpl_binding_attach(&f.binding,10,456,1,&f.second) == FPL_OK && f.value == 0);
        CHECK(f.shown.on_enabled == 1 && f.shown.reason == FPL_OK);
        CHECK(fpl_binding_begin(&f.binding) == FPL_OK && f.state.clip == FPL_RAW); break;
    case 14: /* failed initial publish retains borrowed callback storage */
        f.fail_publish = 1; CHECK(attach(&f) == FPL_FAULT);
        CHECK(f.binding.ticket == &f.first && fpl_binding_close(&f.binding) == FPL_OK); break;
    case 15: /* no implicit fresh-session reset while callbacks exist */
        CHECK(attach(&f) == FPL_OK);
        CHECK(fpl_binding_init(&f.binding,8,&f.state,&ops,&f) == FPL_INVALID);
        f.unknown = f.first; f.unknown.session = 8;
        CHECK(fpl_binding_notify(&f.binding,&f.unknown,f.descriptor) == FPL_INVALID);
        CHECK(fpl_binding_notify(&f.binding,&f.first,0x9999) == FPL_INVALID); break;
    case 16: /* live context, not the snapshot from attach */
        CHECK(attach(&f) == FPL_OK); f.context.bits = 14;
        CHECK(change(&f,1) == FPL_UNSUPPORTED && f.value == 0);
        CHECK(f.shown.on_enabled == 0); break;
    case 17: /* STILL visibility never clears the retained preference */
        CHECK(attach(&f) == FPL_OK && change(&f,1) == FPL_OK); f.context.cine = 0;
        CHECK(fpl_binding_refresh(&f.binding) == FPL_OK);
        CHECK(f.shown.visible == 0 && f.value == 1 && f.state.requested == 1);
        CHECK(change(&f,0) == FPL_UNSUPPORTED && f.value == 1); break;
    case 18: /* stale reads cannot accept a choice */
        CHECK(attach(&f) == FPL_OK); f.fail_read = 1;
        CHECK(change(&f,1) == FPL_FAULT && f.state.requested == 0);
        CHECK(fpl_binding_begin(&f.binding) == FPL_FAULT && f.state.clip == FPL_IDLE); break;
    case 19: /* context acquisition failure invalidates all returned facts */
        f.fail_context = 1; CHECK(fpl_binding_context(&f.binding,&c) == FPL_FAULT);
        CHECK(c.ready == FPL_BLOCK_REC && c.width == 0 && attach(&f) == FPL_FAULT && f.lookups == 0);
        CHECK(fpl_binding_begin(&f.binding) == FPL_FAULT && f.state.clip == FPL_IDLE); break;
    case 20: /* no wrapping generation or reusing an old ticket */
        f.binding.generation = UINT32_MAX; CHECK(attach(&f) == FPL_NOT_READY && f.lookups == 0);
        f.binding.generation = 0; CHECK(attach(&f) == FPL_OK);
        CHECK(fpl_binding_close(&f.binding) == FPL_OK && fpl_binding_reap(&f.binding) == FPL_OK);
        CHECK(attach(&f) == FPL_INVALID); break;
    case 21: /* page reattach detects registry replacement instead of stale descriptor */
        CHECK(attach(&f) == FPL_OK);
        CHECK(fpl_binding_close(&f.binding) == FPL_OK && fpl_binding_reap(&f.binding) == FPL_OK);
        f.descriptor += 0x100;
        CHECK(fpl_binding_attach(&f.binding,10,456,1,&f.second) == FPL_FAULT);
        CHECK(f.subscriptions == 1 && f.registrations == 1); break;
    case 22: /* callback can't overwrite an external subscriber after page close */
        CHECK(attach(&f) == FPL_OK);
        CHECK(fpl_binding_close(&f.binding) == FPL_OK && fpl_binding_reap(&f.binding) == FPL_OK);
        f.subscribed = 1;
        CHECK(fpl_binding_attach(&f.binding,10,456,1,&f.second) == FPL_FAULT && f.subscriptions == 1); break;
    case 23: /* no readiness bit can be invented by this coordinator */
        for (count=0;count<128;++count) {
            f.context.ready = count;
            CHECK(fpl_binding_context(&f.binding,&c) == FPL_OK && c.ready == (count & ~FPL_READY_UI));
        }
        CHECK(attach(&f) == FPL_OK);
        for (count=0;count<128;++count) {
            f.context.ready = count;
            CHECK(fpl_binding_context(&f.binding,&c) == FPL_OK && c.ready == count);
        } break;
    case 24: /* exclude native notifications BEFORE unsubscribe may free pair */
        CHECK(attach(&f) == FPL_OK); f.exclusion_busy = 1;
        CHECK(fpl_binding_close(&f.binding) == FPL_BUSY);
        CHECK(f.unsubscriptions == 0 && f.subscribed == 1 && f.binding.ticket);
        CHECK(change(&f,1) == FPL_INVALID && f.state.requested == 0);
        CHECK(fpl_binding_begin(&f.binding) == FPL_FAULT && f.state.clip == FPL_IDLE);
        f.exclusion_busy = 0; CHECK(fpl_binding_close(&f.binding) == FPL_OK);
        CHECK(f.unsubscriptions == 1 && f.enters == 2 && f.leaves == 1 && !f.exclusive);
        CHECK(fpl_binding_reap(&f.binding) == FPL_OK && f.value == 1);
        CHECK(fpl_binding_begin(&f.binding) == FPL_FAULT && f.state.clip == FPL_IDLE);
        CHECK(fpl_binding_context(&f.binding,&c) == FPL_OK && (c.ready & FPL_BLOCK_REC)); break;
    case 25: /* failed native mutation still releases held exclusion */
        CHECK(attach(&f) == FPL_OK); f.fail_unsubscribe = 1;
        CHECK(fpl_binding_close(&f.binding) == FPL_FAULT);
        CHECK(f.enters == 1 && f.leaves == 1 && !f.exclusive && f.binding.ticket); break;
    case 26: /* normal menu closure must not disable subsequent lossless REC */
        CHECK(attach(&f) == FPL_OK && change(&f,1) == FPL_OK);
        CHECK(fpl_binding_close(&f.binding) == FPL_OK);
        CHECK(fpl_binding_context(&f.binding,&c) == FPL_OK && !(c.ready & FPL_READY_UI));
        CHECK(fpl_binding_begin(&f.binding) == FPL_BUSY);
        CHECK(fpl_binding_reap(&f.binding) == FPL_OK);
        CHECK(fpl_binding_context(&f.binding,&c) == FPL_OK && c.ready == FPL_READY_ALL);
        CHECK(fpl_binding_begin(&f.binding) == FPL_OK && f.state.clip == FPL_LOSSLESS); break;
    case 27: /* final recovery redraw failure cannot release the REC interlock */
        CHECK(attach(&f) == FPL_OK); f.fail_publish = 1;
        CHECK(change(&f,1) == FPL_FAULT);
        CHECK(fpl_binding_close(&f.binding) == FPL_OK && fpl_binding_reap(&f.binding) == FPL_OK);
        f.fail_publish = 0; f.fail_publish_at = f.publishes + 2;
        CHECK(fpl_binding_attach(&f.binding,10,456,1,&f.second) == FPL_FAULT);
        CHECK(f.binding.uncertain && fpl_binding_begin(&f.binding) == FPL_FAULT);
        CHECK(f.state.clip == FPL_IDLE); break;
    case 28: /* no retirement on an unreadable final native value */
        CHECK(attach(&f) == FPL_OK && fpl_binding_close(&f.binding) == FPL_OK);
        f.fail_read = 1; CHECK(fpl_binding_reap(&f.binding) == FPL_FAULT && f.binding.ticket);
        CHECK(f.binding.uncertain && fpl_binding_begin(&f.binding) == FPL_BUSY);
        f.fail_read = 0; CHECK(fpl_binding_reap(&f.binding) == FPL_OK && !f.binding.ticket);
        CHECK(fpl_binding_begin(&f.binding) == FPL_FAULT); break;
    default: return -1;
    }
    return 0;
}
