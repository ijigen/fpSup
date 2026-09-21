/* Host scenarios for the exact native_port.c logic.
 *
 * fp_nv_* is substituted here because native_variable.c is ARM32-only and is
 * separately executed into the original firmware instructions. The mock keeps
 * that layer's checked semantics (ownership, subscription identity, sticky
 * faults, non-atomic failure) so the port is tested against its real contract,
 * not a permissive stub. Nothing here is a camera, GUI or rendering proof. */
#include "native_port.h"
#define CHECK(x) do { if (!(x)) return __LINE__; } while (0)

struct mock_pair { fp_nv_callback callback; void *context; };
struct fp_nv_descriptor { uint32_t type; const char *name; uint32_t value; struct mock_pair *sub; };

static struct mock {
    struct fp_nv_descriptor descriptor;
    struct mock_pair pair, foreign_pair;
    uint32_t present;
    uint32_t fail_inspect, fail_register, fail_subscribe, fail_set, fail_unsubscribe;
    uint32_t fire_on_set, fire_on_read, fire_value;
    uint32_t registers, subscribes, sets, reads, unsubscribes;
} M;
#define MOCK_MAGIC 0x4e564c53u

static uint32_t name_ok(const char *p) {
    static const char expected[] = FPL_PRIVATE_VARIABLE;
    uint32_t n;
    if (!p) return 0;
    for (n = 0; n < sizeof(expected); ++n) if (p[n] != expected[n]) return 0;
    return 1;
}
static uint32_t nv_poison(struct fp_nv_state *s, uint32_t error) { s->fault = error; return error; }
static uint32_t nv_check(struct fp_nv_state *s, uint32_t cleanup) {
    if (!s || s->magic != MOCK_MAGIC || !s->app) return FP_NV_INVALID;
    if (!name_ok(s->name)) return nv_poison(s, FP_NV_INVALID);
    if (s->fault && !cleanup) return FP_NV_FAULT;
    return FP_NV_OK;
}
static uint32_t nv_owned(struct fp_nv_state *s) {
    if (!M.present || s->owned != &M.descriptor || M.descriptor.name != s->name)
        return nv_poison(s, FP_NV_STALE);
    if (M.descriptor.type) return nv_poison(s, FP_NV_TYPE);
    return FP_NV_OK;
}
static uint32_t nv_subscription_owned(struct fp_nv_state *s) {
    struct mock_pair *p = M.descriptor.sub;
    if (s->callback) {
        if (!p || p != s->native_pair || p->callback != s->callback ||
            p->context != s->callback_context) return nv_poison(s, FP_NV_COLLISION);
    } else if (p) {
        return nv_poison(s, FP_NV_COLLISION);
    }
    return FP_NV_OK;
}
static void nv_fire(void) {
    if (M.descriptor.sub) {
        M.descriptor.value = M.fire_value;
        M.descriptor.sub->callback(&M.descriptor, M.descriptor.sub->context);
    }
}
uint32_t fp_nv_init(struct fp_nv_state *s, void *app, const char *name) {
    if (!s || s->magic || !app || ((uintptr_t)app & 3) || !name_ok(name)) return FP_NV_INVALID;
    s->app = app; s->name = name; s->owned = 0; s->callback = 0;
    s->callback_context = 0; s->native_pair = 0; s->fault = 0; s->last_native = 0;
    s->magic = MOCK_MAGIC;
    return FP_NV_OK;
}
uint32_t fp_nv_inspect(struct fp_nv_state *s, struct fp_nv_snapshot *out) {
    uint32_t r;
    if (!out) return FP_NV_INVALID;
    out->descriptor = out->type = out->value = out->subscription = 0;
    r = nv_check(s, 0); if (r) return r;
    if (M.fail_inspect) return nv_poison(s, FP_NV_NATIVE);
    if (!M.present) return FP_NV_OK;
    out->descriptor = (uint32_t)(uintptr_t)&M.descriptor;
    out->type = M.descriptor.type;
    out->value = M.descriptor.value;
    out->subscription = (uint32_t)(uintptr_t)M.descriptor.sub;
    return FP_NV_OK;
}
uint32_t fp_nv_register_off(struct fp_nv_state *s) {
    uint32_t r = nv_check(s, 0); if (r) return r;
    if (s->owned) return FP_NV_INVALID;
    ++M.registers;
    if (M.present) return nv_poison(s, FP_NV_COLLISION);
    if (M.fail_register) return nv_poison(s, FP_NV_NATIVE);
    M.present = 1;
    M.descriptor.type = 0; M.descriptor.name = s->name;
    M.descriptor.value = 0; M.descriptor.sub = 0;
    s->owned = &M.descriptor;
    return FP_NV_OK;
}
uint32_t fp_nv_read(struct fp_nv_state *s, uint32_t *out) {
    uint32_t r;
    if (!out) return FP_NV_INVALID;
    *out = 0;
    r = nv_check(s, 0); if (r) return r;
    r = nv_owned(s); if (r) return r;
    r = nv_subscription_owned(s); if (r) return r;
    ++M.reads;
    if (M.fire_on_read) { M.fire_on_read = 0; nv_fire(); }
    *out = M.descriptor.value;
    return FP_NV_OK;
}
uint32_t fp_nv_subscribe(struct fp_nv_state *s, fp_nv_callback callback, void *context) {
    uint32_t r = nv_check(s, 0); if (r) return r;
    if (!callback || !context || s->callback) return FP_NV_INVALID;
    r = nv_owned(s); if (r) return r;
    if (M.descriptor.sub) return nv_poison(s, FP_NV_COLLISION);
    ++M.subscribes;
    s->callback = callback; s->callback_context = context;
    if (M.fail_subscribe) { s->native_pair = M.descriptor.sub; return nv_poison(s, FP_NV_NATIVE); }
    M.pair.callback = callback; M.pair.context = context;
    M.descriptor.sub = &M.pair;
    s->native_pair = &M.pair;
    return FP_NV_OK;
}
uint32_t fp_nv_set_canonical(struct fp_nv_state *s, uint32_t value) {
    uint32_t r = nv_check(s, 0); if (r) return r;
    if (value > 1) return FP_NV_INVALID;
    r = nv_owned(s); if (r) return r;
    r = nv_subscription_owned(s); if (r) return r;
    ++M.sets;
    if (M.fail_set) return nv_poison(s, FP_NV_NATIVE);
    M.descriptor.value = value;
    if (M.fire_on_set) { M.fire_on_set = 0; nv_fire(); M.descriptor.value = value; }
    r = nv_owned(s); if (r) return r;
    r = nv_subscription_owned(s); if (r) return r;
    if (M.descriptor.value != value) return nv_poison(s, FP_NV_DIVERGED);
    return FP_NV_OK;
}
uint32_t fp_nv_unsubscribe_locked(struct fp_nv_state *s) {
    struct mock_pair *p;
    uint32_t r = nv_check(s, 1); if (r) return r;
    if (!s->callback) return FP_NV_INVALID;
    r = nv_owned(s); if (r) return r;
    ++M.unsubscribes;
    p = M.descriptor.sub;
    if (p) {
        if (p != s->native_pair || p->callback != s->callback || p->context != s->callback_context)
            return nv_poison(s, FP_NV_COLLISION);
        if (M.fail_unsubscribe) return nv_poison(s, FP_NV_NATIVE);
        M.descriptor.sub = 0;
    } else if (s->native_pair) {
        return nv_poison(s, FP_NV_STALE);
    }
    s->callback = 0; s->callback_context = 0; s->native_pair = 0;
    return FP_NV_OK;
}

/* ---- scenario scaffolding ------------------------------------------------ */
static const char PRIVATE_NAME[] = FPL_PRIVATE_VARIABLE;
static uint32_t APP;

struct scene {
    struct fpl_port port;
    struct fpl_binding binding;
    struct fpl_state state;
    struct fpl_ticket ticket;
    struct fpl_context facts;
    uint32_t facts_result, enter_result, quiesce_result;
    uint32_t enters, leaves, quiesces, exclusive;
};
static uint32_t facts_read(void *p, struct fpl_context *out) {
    struct scene *s = p;
    *out = s->facts;
    return s->facts_result;
}
static uint32_t exclusion_enter(void *p) {
    struct scene *s = p;
    ++s->enters;
    if (s->enter_result != FPL_OK) return s->enter_result;
    if (s->exclusive) return FPL_BUSY;
    s->exclusive = 1;
    return FPL_OK;
}
static void exclusion_leave(void *p) { struct scene *s = p; ++s->leaves; s->exclusive = 0; }
static uint32_t exclusion_quiesce(void *p) {
    struct scene *s = p; ++s->quiesces; return s->quiesce_result;
}

enum providers { NO_PROVIDERS = 0, FACTS = 1, EXCLUDE = 2, DRAIN = 4 };
static uint32_t setup(struct scene *s, uint32_t providers) {
    struct fpl_port_facts facts = {facts_read, s};
    struct fpl_port_exclusion exclusion = {exclusion_enter, exclusion_leave, exclusion_quiesce, s};
    if (!(providers & EXCLUDE)) { exclusion.enter = 0; exclusion.leave = 0; }
    if (!(providers & DRAIN)) exclusion.quiesce = 0;
    s->facts = (struct fpl_context){502, 1, 1, 12, 1936, 1090, 24000, 1001, 1, FPL_READY_ALL};
    fpl_boot(&s->state);
    if (fpl_port_init(&s->port, &APP, PRIVATE_NAME,
                      (providers & FACTS) ? &facts : 0, &exclusion) != FPL_OK) return 0;
    if (fpl_binding_init(&s->binding, 9, &s->state, fpl_port_ops(), &s->port) != FPL_OK) return 0;
    if (fpl_port_bind(&s->port, &s->binding) != FPL_OK) return 0;
    return 1;
}
static uint32_t attach(struct scene *s) {
    return fpl_binding_attach(&s->binding, FPL_PAGE_MAINB2, 0x1234, 1, &s->ticket);
}
/* A native user write: the registry value changes and the copied pair runs. */
static void user_write(uint32_t value) { M.fire_value = value; nv_fire(); }

int port_case(uint32_t number) {
    struct scene s = {0};
    struct fpl_context context;
    uint32_t result, value;
    M = (struct mock){0};
    APP = 0;
    switch (number) {
    case 0: /* default_off_registration */
        CHECK(setup(&s, FACTS | EXCLUDE | DRAIN));
        CHECK(attach(&s) == FPL_OK);
        CHECK(M.registers == 1 && M.subscribes == 1 && M.present == 1);
        CHECK(M.descriptor.value == 0 && M.descriptor.type == 0);
        CHECK(M.descriptor.name == PRIVATE_NAME);
        CHECK(s.port.descriptor == (uint32_t)(uintptr_t)&M.descriptor);
        CHECK(s.ticket.descriptor == s.port.descriptor);
        CHECK(s.port.ticket == &s.ticket && s.port.fault == 0);
        CHECK(M.descriptor.sub == &M.pair && M.pair.context == &s.port);
        break;
    case 1: /* ready_ui_never_claimed */
        CHECK(setup(&s, FACTS | EXCLUDE | DRAIN));
        CHECK(attach(&s) == FPL_OK);
        CHECK(fpl_binding_context(&s.binding, &context) == FPL_OK);
        CHECK((context.ready & FPL_READY_UI) == 0);
        CHECK((context.ready & FPL_BLOCK_REC) == 0);
        CHECK(s.port.ui_claims_stripped > 0);
        CHECK(fpl_can_enable(&context) == FPL_NOT_READY);
        /* RAW recording stays available; only lossless is refused. */
        CHECK(fpl_binding_begin(&s.binding) == FPL_OK);
        CHECK(s.state.clip == FPL_RAW);
        break;
    case 2: /* result_translation_table */
        CHECK(fpl_port_translate(FP_NV_OK) == FPL_OK);
        CHECK(fpl_port_translate(FP_NV_INVALID) == FPL_INVALID);
        CHECK(fpl_port_translate(FP_NV_FIRMWARE) == FPL_UNSUPPORTED);
        CHECK(fpl_port_translate(FP_NV_COLLISION) == FPL_FAULT);
        CHECK(fpl_port_translate(FP_NV_STALE) == FPL_FAULT);
        CHECK(fpl_port_translate(FP_NV_TYPE) == FPL_FAULT);
        CHECK(fpl_port_translate(FP_NV_NATIVE) == FPL_FAULT);
        CHECK(fpl_port_translate(FP_NV_FAULT) == FPL_FAULT);
        CHECK(fpl_port_translate(FP_NV_DIVERGED) == FPL_FAULT);
        CHECK(fpl_port_translate(0x999) == FPL_FAULT);
        for (value = 0x100; value <= 0x110; ++value) {
            result = fpl_port_translate(value);
            CHECK(result != FPL_OK && result != FPL_BUSY && result != FPL_NOT_READY);
        }
        break;
    case 3: /* name_content_checked_without_pointer_identity */
        {
            char copy[sizeof(PRIVATE_NAME)];
            static const char wrong[] = "MV_AudioRecord";
            struct fpl_variable variable = {0, 0, 0};
            const struct fpl_binding_ops *ops = fpl_port_ops();
            CHECK(setup(&s, FACTS | EXCLUDE | DRAIN));
            for (value = 0; value < sizeof(copy); ++value) copy[value] = PRIVATE_NAME[value];
            CHECK(copy != PRIVATE_NAME);
            CHECK(ops->lookup(&s.port, copy, &variable) == FPL_OK);
            CHECK(ops->lookup(&s.port, wrong, &variable) == FPL_INVALID);
            CHECK(ops->lookup(&s.port, 0, &variable) == FPL_INVALID);
            CHECK(ops->register_integer(&s.port, wrong, 0) == FPL_INVALID);
            CHECK(M.registers == 0 && M.present == 0);
        }
        break;
    case 4: /* register_only_creates_off */
        {
            const struct fpl_binding_ops *ops = fpl_port_ops();
            CHECK(setup(&s, FACTS | EXCLUDE | DRAIN));
            CHECK(ops->register_integer(&s.port, PRIVATE_NAME, 1) == FPL_INVALID);
            CHECK(M.registers == 0);
            CHECK(ops->register_integer(&s.port, PRIVATE_NAME, 0) == FPL_OK);
            CHECK(M.descriptor.value == 0);
            /* one claim only: a second registration is refused before native */
            CHECK(ops->register_integer(&s.port, PRIVATE_NAME, 0) == FPL_INVALID);
            CHECK(M.registers == 1);
        }
        break;
    case 5: /* foreign_descriptor_not_adopted */
        CHECK(setup(&s, FACTS | EXCLUDE | DRAIN));
        M.present = 1;
        M.descriptor.name = "MV_fpLossless"; /* another module's entry */
        M.descriptor.value = 1;
        M.descriptor.sub = &M.foreign_pair;
        CHECK(attach(&s) == FPL_FAULT);
        CHECK(M.registers == 0 && M.subscribes == 0);
        CHECK(M.descriptor.sub == &M.foreign_pair && M.descriptor.value == 1);
        CHECK(s.port.descriptor == 0 && s.port.ticket == 0);
        CHECK(fpl_binding_begin(&s.binding) == FPL_FAULT);
        break;
    case 6: /* subscribe_failure_retains_context_and_blocks */
        CHECK(setup(&s, FACTS | EXCLUDE | DRAIN));
        M.fail_subscribe = 1;
        CHECK(attach(&s) == FPL_FAULT);
        CHECK(s.port.subscribe_uncertain == 1 && s.port.fault == 1);
        CHECK(s.port.ticket == &s.ticket); /* callback storage stays addressable */
        CHECK(s.port.nv.callback_context == &s.port);
        CHECK(fpl_binding_context(&s.binding, &context) != FPL_OK);
        CHECK(context.ready == FPL_BLOCK_REC);
        CHECK(fpl_binding_begin(&s.binding) == FPL_FAULT);
        break;
    case 7: /* callback_to_policy_restores_canonical */
        CHECK(setup(&s, FACTS | EXCLUDE | DRAIN));
        CHECK(attach(&s) == FPL_OK);
        user_write(1); /* the user moved the row to ON */
        CHECK(s.port.callbacks_seen == 1 && s.port.callbacks_refused == 0);
        CHECK(s.port.last_notify == FPL_NOT_READY); /* no UI proof exists */
        CHECK(s.state.requested == 0);
        CHECK(M.descriptor.value == 0); /* canonical value restored natively */
        CHECK(s.port.fault == 0 && s.binding.uncertain == 0);
        user_write(0); /* an OFF confirmation is accepted */
        CHECK(s.port.last_notify == FPL_OK);
        CHECK(s.state.requested == 0 && M.descriptor.value == 0);
        break;
    case 8: /* echo_during_publish_suppressed */
        CHECK(setup(&s, FACTS | EXCLUDE | DRAIN));
        CHECK(attach(&s) == FPL_OK);
        M.fire_on_set = 1; M.fire_value = 1;
        user_write(1);
        CHECK(s.port.echoes_suppressed == 1);
        CHECK(s.port.callbacks_refused == 0 && s.port.fault == 0);
        CHECK(M.descriptor.value == 0 && s.state.requested == 0);
        break;
    case 9: /* nested_callback_refused_and_sticky */
        CHECK(setup(&s, FACTS | EXCLUDE | DRAIN));
        CHECK(attach(&s) == FPL_OK);
        M.fire_on_read = 1; M.fire_value = 1;
        user_write(1);
        CHECK(s.port.callbacks_refused == 1 && s.port.fault == 1);
        CHECK(s.binding.uncertain == 1);
        CHECK(fpl_binding_context(&s.binding, &context) != FPL_OK);
        CHECK(context.ready == FPL_BLOCK_REC);
        CHECK(fpl_binding_begin(&s.binding) == FPL_FAULT);
        /* A quarantined coordinator is not refreshable at all. */
        CHECK(fpl_binding_refresh(&s.binding) == FPL_INVALID);
        break;
    case 10: /* close_without_exclusion_is_busy */
        CHECK(setup(&s, FACTS));
        CHECK(attach(&s) == FPL_OK);
        CHECK(fpl_binding_close(&s.binding) == FPL_BUSY);
        CHECK(s.port.exclusion_held == 0 && M.unsubscribes == 0);
        CHECK(M.descriptor.sub == &M.pair); /* the native pair is still live */
        CHECK(s.port.ticket == &s.ticket);
        CHECK(s.binding.unsubscribe_attempted == 0);
        CHECK(fpl_binding_reap(&s.binding) == FPL_INVALID);
        break;
    case 11: /* quiesce_absent_keeps_ticket_after_unsubscribe */
        CHECK(setup(&s, FACTS | EXCLUDE));
        CHECK(attach(&s) == FPL_OK);
        CHECK(fpl_binding_close(&s.binding) == FPL_OK);
        CHECK(M.unsubscribes == 1 && M.descriptor.sub == 0);
        CHECK(s.enters == 1 && s.leaves == 1 && s.exclusive == 0);
        CHECK(fpl_binding_reap(&s.binding) == FPL_BUSY);
        CHECK(fpl_binding_reap(&s.binding) == FPL_BUSY);
        CHECK(s.port.ticket == &s.ticket); /* callback storage must not be freed */
        CHECK(s.binding.phase == FPL_BIND_DRAINING);
        break;
    case 12: /* unsubscribe_requires_held_exclusion */
        {
            const struct fpl_binding_ops *ops = fpl_port_ops();
            CHECK(setup(&s, FACTS | EXCLUDE | DRAIN));
            CHECK(attach(&s) == FPL_OK);
            CHECK(ops->unsubscribe(&s.port, &s.ticket) == FPL_INVALID);
            CHECK(M.unsubscribes == 0 && M.descriptor.sub == &M.pair);
            CHECK(ops->quiesce(&s.port, &s.ticket) == FPL_FAULT); /* still subscribed */
            CHECK(s.port.fault == 1);
        }
        break;
    case 13: /* full_retirement */
        CHECK(setup(&s, FACTS | EXCLUDE | DRAIN));
        CHECK(attach(&s) == FPL_OK);
        CHECK(fpl_binding_close(&s.binding) == FPL_OK);
        CHECK(fpl_binding_reap(&s.binding) == FPL_OK);
        CHECK(s.quiesces == 1 && M.descriptor.sub == 0);
        CHECK(s.port.retired == 1 && s.port.ticket == &s.ticket);
        CHECK(s.port.nv.callback == 0 && s.port.nv.native_pair == 0);
        CHECK(s.port.fault == 0 && s.binding.phase == FPL_BIND_CLEAN);
        CHECK(fpl_port_release(&s.port) == FPL_OK);
        CHECK(s.port.ticket == 0 && s.port.retired == 0);
        CHECK(fpl_port_release(&s.port) == FPL_OK); /* idempotent */
        CHECK(M.present == 1 && M.descriptor.name == PRIVATE_NAME); /* not freed */
        CHECK(s.state.requested == 0);
        break;
    case 14: /* quiesce_provider_is_not_trusted_alone */
        {
            const struct fpl_binding_ops *ops = fpl_port_ops();
            CHECK(setup(&s, FACTS | EXCLUDE | DRAIN));
            CHECK(attach(&s) == FPL_OK);
            CHECK(fpl_binding_close(&s.binding) == FPL_OK);
            M.descriptor.sub = &M.foreign_pair; /* a new subscriber appeared */
            CHECK(fpl_binding_reap(&s.binding) == FPL_FAULT);
            CHECK(s.port.ticket == &s.ticket && s.binding.phase == FPL_BIND_DRAINING);
            M.descriptor.sub = 0;
            /* Drain is provable again, but the port fault is sticky, so the
             * coordinator's own value re-check fails and nothing is released. */
            CHECK(fpl_binding_reap(&s.binding) == FPL_FAULT);
            CHECK(s.port.retired == 1 && s.binding.phase == FPL_BIND_DRAINING);
            CHECK(fpl_port_release(&s.port) == FPL_BUSY);
            CHECK(s.port.ticket == &s.ticket);
            CHECK(ops->read_integer(&s.port, s.port.descriptor, &value) == FPL_FAULT);
        }
        break;
    case 15: /* native_set_failure_is_sticky_but_cleanup_still_runs */
        CHECK(setup(&s, FACTS | EXCLUDE | DRAIN));
        CHECK(attach(&s) == FPL_OK);
        M.fail_set = 1;
        CHECK(fpl_binding_refresh(&s.binding) == FPL_FAULT);
        CHECK(s.port.fault == 1 && s.port.last_nv == FP_NV_NATIVE);
        CHECK(s.binding.uncertain == 1 && s.binding.healthy == 0);
        M.fail_set = 0;
        CHECK(fpl_binding_refresh(&s.binding) == FPL_INVALID); /* quarantined, no retry */
        CHECK(fpl_binding_begin(&s.binding) == FPL_FAULT);
        CHECK(fpl_binding_close(&s.binding) == FPL_OK); /* cleanup path stays open */
        CHECK(M.descriptor.sub == 0);
        CHECK(fpl_binding_reap(&s.binding) == FPL_FAULT); /* value never re-proved */
        CHECK(s.port.ticket == &s.ticket);
        break;
    case 16: /* facts_absent_blocks_rec */
        CHECK(setup(&s, EXCLUDE | DRAIN));
        CHECK(attach(&s) == FPL_NOT_READY);
        CHECK(M.registers == 0 && M.subscribes == 0);
        CHECK(fpl_binding_context(&s.binding, &context) == FPL_NOT_READY);
        CHECK(context.ready == FPL_BLOCK_REC);
        CHECK(fpl_binding_begin(&s.binding) == FPL_FAULT);
        break;
    case 17: /* presentation_unapplied_is_counted_not_claimed */
        CHECK(setup(&s, FACTS | EXCLUDE | DRAIN));
        CHECK(attach(&s) == FPL_OK);
        /* ON is not selectable, so every published view disables a choice
         * that this port cannot actually disable on screen. */
        CHECK(s.port.presentation_unapplied > 0);
        value = s.port.presentation_unapplied;
        s.facts.width = 4096; /* an ineligible producer keeps ON disabled */
        CHECK(fpl_binding_refresh(&s.binding) == FPL_OK);
        CHECK(s.port.presentation_unapplied == value + 1);
        CHECK(M.descriptor.value == 0);
        break;
    case 18: /* read_and_publish_reject_a_foreign_descriptor */
        {
            const struct fpl_binding_ops *ops = fpl_port_ops();
            struct fpl_view view = {1, 0, 1, 0, FPL_OK};
            CHECK(setup(&s, FACTS | EXCLUDE | DRAIN));
            CHECK(attach(&s) == FPL_OK);
            CHECK(ops->read_integer(&s.port, s.port.descriptor + 4, &value) == FPL_INVALID);
            CHECK(ops->read_integer(&s.port, s.port.descriptor, 0) == FPL_INVALID);
            CHECK(ops->publish(&s.port, s.port.descriptor + 4, &view) == FPL_INVALID);
            view.value = 2;
            CHECK(ops->publish(&s.port, s.port.descriptor, &view) == FPL_INVALID);
            CHECK(s.port.fault == 0 && M.descriptor.value == 0);
        }
        break;
    case 19: /* init_and_bind_validation */
        {
            struct fpl_port other = {0};
            struct fpl_binding second = {0};
            struct fpl_port_facts facts = {facts_read, &s};
            struct fpl_port_facts empty = {0, &s};
            struct fpl_port_exclusion half = {exclusion_enter, 0, 0, &s};
            CHECK(fpl_port_init(&other, &APP, "MV_AudioRecord", &facts, 0) == FPL_INVALID);
            CHECK(fpl_port_init(&other, 0, PRIVATE_NAME, &facts, 0) == FPL_INVALID);
            CHECK(fpl_port_init(&other, (char *)&APP + 1, PRIVATE_NAME, &facts, 0) == FPL_INVALID);
            CHECK(fpl_port_init(&other, &APP, PRIVATE_NAME, &empty, 0) == FPL_INVALID);
            CHECK(fpl_port_init(&other, &APP, PRIVATE_NAME, &facts, &half) == FPL_INVALID);
            CHECK(other.magic == 0);
            CHECK(fpl_port_init(&other, &APP, PRIVATE_NAME, &facts, 0) == FPL_OK);
            CHECK(fpl_port_init(&other, &APP, PRIVATE_NAME, &facts, 0) == FPL_INVALID);
            CHECK(fpl_port_bind(&other, 0) == FPL_INVALID);
            CHECK(setup(&s, FACTS | EXCLUDE | DRAIN));
            CHECK(fpl_port_bind(&s.port, &s.binding) == FPL_OK); /* idempotent */
            CHECK(fpl_port_bind(&s.port, &second) == FPL_BUSY);
            CHECK(s.port.binding == &s.binding);
        }
        break;
    case 20: /* initial_publish_failure_never_shows_a_working_row */
        CHECK(setup(&s, FACTS | EXCLUDE | DRAIN));
        M.fail_set = 1;
        CHECK(attach(&s) == FPL_FAULT);
        CHECK(M.subscribes == 1 && M.sets == 1);
        CHECK(s.binding.healthy == 0 && s.binding.uncertain == 1);
        CHECK(fpl_binding_begin(&s.binding) == FPL_FAULT);
        CHECK(s.port.fault == 1);
        break;
    case 21: /* late_event_after_close_is_rejected_not_a_port_fault */
        CHECK(setup(&s, FACTS));
        CHECK(attach(&s) == FPL_OK);
        CHECK(fpl_binding_close(&s.binding) == FPL_BUSY); /* no exclusion available */
        user_write(1); /* the subscription is still live natively */
        CHECK(s.port.callbacks_seen == 1);
        CHECK(s.port.last_notify == FPL_INVALID);
        CHECK(s.port.callbacks_rejected == 1 && s.port.callbacks_refused == 0);
        CHECK(s.port.fault == 0);
        CHECK(s.state.requested == 0);
        CHECK(M.descriptor.value == 1); /* divergence stays visible, not hidden */
        CHECK(fpl_binding_begin(&s.binding) == FPL_FAULT);
        break;
    default:
        return __LINE__;
    }
    return 0;
}
