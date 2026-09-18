#include "native_variable.h"
#include <stddef.h>

#if !defined(__arm__) || UINTPTR_MAX != UINT32_MAX
#error "This native ABI implementation is ARM32-only; execute tests in the emulator."
#endif
#define NV_MAGIC 0x4e564c53u
#define INLINE static __attribute__((always_inline)) inline

struct native_pair { fp_nv_callback callback; void *context; };
struct fp_nv_descriptor {
    uint32_t type; const char *name; uint32_t value, index;
    void *component_list0, *component_list1;
    struct native_pair *subscription;
    void *derived;
};
struct definition { uint32_t type; const char *name; uint32_t value; };
_Static_assert(sizeof(struct definition) == 12, "native definition stride");
_Static_assert(sizeof(struct native_pair) == 8, "native callback pair");
_Static_assert(sizeof(struct fp_nv_descriptor) == 32, "native descriptor size");
_Static_assert(offsetof(struct fp_nv_descriptor, subscription) == 24, "subscription offset");
_Static_assert(sizeof(struct fp_nv_state) == 36, "ARM state layout");

INLINE uint32_t name_ok(const char *p) {
    return p && p[0]=='M' && p[1]=='V' && p[2]=='_' && p[3]=='f' &&
        p[4]=='p' && p[5]=='L' && p[6]=='o' && p[7]=='s' && p[8]=='s' &&
        p[9]=='l' && p[10]=='e' && p[11]=='s' && p[12]=='s' && !p[13];
}
INLINE uint32_t firmware_ok(void) {
    return *(volatile const uint32_t *)0xc05db308u == 0x4ff0e92du &&
        *(volatile const uint32_t *)0xc05dca88u == 0xb908b530u &&
        *(volatile const uint32_t *)0xc05dcb18u == 0x2006b908u &&
        *(volatile const uint32_t *)0xc05dcb30u == 0xd1012800u &&
        *(volatile const uint32_t *)0xc05dc778u == 0x0004b5f0u;
}
INLINE uint32_t poison(struct fp_nv_state *s, uint32_t error) {
    s->fault = error; return error;
}
INLINE uint32_t check(struct fp_nv_state *s, uint32_t cleanup) {
    if (!s || s->magic != NV_MAGIC || !s->app || ((uintptr_t)s->app & 3)) return FP_NV_INVALID;
    if (!name_ok(s->name)) return poison(s, FP_NV_INVALID);
    if (!firmware_ok()) return poison(s, FP_NV_FIRMWARE);
    if (s->fault && !cleanup) return FP_NV_FAULT;
    return FP_NV_OK;
}
INLINE uint32_t lookup(struct fp_nv_state *s, struct fp_nv_descriptor **out) {
    typedef uint32_t (*fn)(void *, const char *, struct fp_nv_descriptor **);
    *out = 0;
    s->last_native = ((fn)0xc05dca89u)(s->app, s->name, out);
    return s->last_native ? poison(s, FP_NV_NATIVE) : FP_NV_OK;
}
INLINE uint32_t owned(struct fp_nv_state *s, struct fp_nv_descriptor **out) {
    uint32_t r = lookup(s, out);
    if (r) return r;
    if (!*out || *out != s->owned || (*out)->name != s->name) return poison(s, FP_NV_STALE);
    if ((*out)->type) return poison(s, FP_NV_TYPE);
    return FP_NV_OK;
}
INLINE uint32_t subscription_owned(struct fp_nv_state *s, const struct fp_nv_descriptor *d) {
    const struct native_pair *p = d->subscription;
    if (s->callback) {
        if (!p || p != s->native_pair || p->callback != s->callback || p->context != s->callback_context)
            return poison(s, FP_NV_COLLISION);
    } else if (p) {
        return poison(s, FP_NV_COLLISION);
    }
    return FP_NV_OK;
}

uint32_t fp_nv_init(struct fp_nv_state *s, void *app, const char *name) {
    if (!s || s->magic || !app || ((uintptr_t)app & 3) || !name_ok(name)) return FP_NV_INVALID;
    if (!firmware_ok()) return FP_NV_FIRMWARE;
    s->app = app; s->name = name; s->owned = 0; s->callback = 0;
    s->callback_context = 0; s->native_pair = 0; s->fault = 0; s->last_native = 0;
    s->magic = NV_MAGIC;
    return FP_NV_OK;
}
uint32_t fp_nv_inspect(struct fp_nv_state *s, struct fp_nv_snapshot *out) {
    struct fp_nv_descriptor *d;
    uint32_t r;
    if (!out) return FP_NV_INVALID;
    out->descriptor = out->type = out->value = out->subscription = 0;
    r = check(s, 0); if (r) return r;
    r = lookup(s, &d); if (r || !d) return r;
    out->descriptor = (uintptr_t)d; out->type = d->type;
    out->value = d->value; out->subscription = (uintptr_t)d->subscription;
    return FP_NV_OK;
}
uint32_t fp_nv_register_off(struct fp_nv_state *s) {
    typedef uint32_t (*fn)(void *, uint32_t, const struct definition *);
    struct fp_nv_descriptor *d;
    struct definition def;
    uint32_t r = check(s, 0); if (r) return r;
    if (s->owned) return FP_NV_INVALID;
    r = lookup(s, &d); if (r) return r;
    if (d) return poison(s, FP_NV_COLLISION);
    def.type = 0; def.name = s->name; def.value = 0;
    s->last_native = ((fn)0xc05db309u)(s->app, 1, &def);
    if (s->last_native) return poison(s, FP_NV_NATIVE);
    r = lookup(s, &d); if (r) return r;
    if (!d || d->type || d->name != s->name || d->subscription || d->value)
        return poison(s, FP_NV_STALE);
    s->owned = d;
    return FP_NV_OK;
}
uint32_t fp_nv_read(struct fp_nv_state *s, uint32_t *out) {
    struct fp_nv_descriptor *d;
    uint32_t r;
    if (!out) return FP_NV_INVALID;
    *out = 0;
    r = check(s, 0); if (r) return r;
    r = owned(s, &d); if (r) return r;
    r = subscription_owned(s, d); if (r) return r;
    *out = d->value;
    return FP_NV_OK;
}
uint32_t fp_nv_subscribe(struct fp_nv_state *s, fp_nv_callback callback, void *context) {
    typedef uint32_t (*fn)(void *, const char *, const struct native_pair *);
    struct fp_nv_descriptor *d;
    struct native_pair pair;
    uint32_t r = check(s, 0); if (r) return r;
    if (!callback || !context || s->callback) return FP_NV_INVALID;
    r = owned(s, &d); if (r) return r;
    if (d->subscription) return poison(s, FP_NV_COLLISION);
    s->callback = callback; s->callback_context = context;
    pair.callback = callback; pair.context = context;
    s->last_native = ((fn)0xc05dcb19u)(s->app, s->name, &pair);
    /* Retain possible publication identity even on a non-atomic failure. */
    s->native_pair = d->subscription;
    if (s->last_native) return poison(s, FP_NV_NATIVE);
    if (!d->subscription || d->subscription->callback != callback || d->subscription->context != context)
        return poison(s, FP_NV_STALE);
    return FP_NV_OK;
}
uint32_t fp_nv_set_canonical(struct fp_nv_state *s, uint32_t value) {
    typedef uint32_t (*fn)(void *, uint32_t, uint32_t, const struct definition *);
    struct fp_nv_descriptor *d;
    struct definition item;
    uint32_t r = check(s, 0); if (r) return r;
    if (value > 1) return FP_NV_INVALID;
    r = owned(s, &d); if (r) return r;
    r = subscription_owned(s, d); if (r) return r;
    item.type = 0; item.name = s->name; item.value = value;
    s->last_native = ((fn)0xc05dc779u)(s->app, 0, 1, &item);
    if (s->last_native) return poison(s, FP_NV_NATIVE);
    r = owned(s, &d); if (r) return r;
    r = subscription_owned(s, d); if (r) return r;
    if (d->value != value) return poison(s, FP_NV_DIVERGED);
    return FP_NV_OK;
}
uint32_t fp_nv_unsubscribe_locked(struct fp_nv_state *s) {
    typedef uint32_t (*fn)(void *, const char *);
    struct fp_nv_descriptor *d;
    struct native_pair *p;
    uint32_t r = check(s, 1); if (r) return r;
    if (!s->callback) return FP_NV_INVALID;
    r = owned(s, &d); if (r) return r;
    p = d->subscription;
    if (p) {
        if (p != s->native_pair || p->callback != s->callback || p->context != s->callback_context)
            return poison(s, FP_NV_COLLISION);
        s->last_native = ((fn)0xc05dcb31u)(s->app, s->name);
        if (s->last_native) return poison(s, FP_NV_NATIVE);
        if (d->subscription) return poison(s, FP_NV_STALE);
    } else if (s->native_pair) {
        return poison(s, FP_NV_STALE);
    }
    s->callback = 0; s->callback_context = 0; s->native_pair = 0;
    return FP_NV_OK; /* no quiescence or callback-storage release is implied */
}
