#include "reader_lease.h"

static uint32_t be32(const uint8_t *p)
{
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
           ((uint32_t)p[2] << 8) | (uint32_t)p[3];
}

uint32_t fp_fnv1a32(const uint8_t *p, uint32_t n)
{
    uint32_t h = UINT32_C(0x811c9dc5), i;
    for (i = 0; i < n; ++i) h = (h ^ p[i]) * UINT32_C(0x01000193);
    return h;
}

static int blob_valid(const struct fp_blob *b)
{
    return b->bytes && b->length && b->capacity >= b->length && b->arm_base &&
           b->length <= UINT32_MAX - b->arm_base &&
           b->length <= UINTPTR_MAX - (uintptr_t)b->bytes;
}

static int overlaps(const struct fp_blob *a, const struct fp_blob *b)
{
    uintptr_t ah = (uintptr_t)a->bytes, bh = (uintptr_t)b->bytes;
    return (a->arm_base < b->arm_base + b->length &&
            b->arm_base < a->arm_base + a->length) ||
           (ah < bh + b->length && bh < ah + a->length);
}

static int same_blob(const struct fp_blob *a, const struct fp_blob *b)
{
    return a->bytes == b->bytes && a->capacity == b->capacity &&
           a->arm_base == b->arm_base && a->length == b->length;
}

static int same_identity(const struct fp_lease *l)
{
    const struct fp_reader_view *r = l->reader;
    return r && r->resource_id == l->saved.resource_id &&
           r->generation == l->saved.generation &&
           r->page_id == FP_MAINB2_PAGE_ID && !r->stream_handle && !r->owns_input;
}

static int private_view(const struct fp_lease *l)
{
    return same_identity(l) && same_blob(&l->reader->source, &l->package.page) &&
           same_blob(&l->reader->pool, &l->package.pool);
}

static enum fp_result poison(struct fp_lease *l)
{
    if (l && (l->phase == FP_ACTIVE || l->phase == FP_PARSED_PINNED ||
              l->phase == FP_POISONED)) {
        l->phase = FP_POISONED;
        return FP_FAIL_STOP;
    }
    return FP_NOT_LIVE;
}

/* Structural preflight precedes all mutation, independent of fingerprint guard.
 * Every length is BE32 and may itself be unaligned in the byte stream. */
static int page_valid(const struct fp_package *p)
{
    uint32_t pos = 0, count = 0, terminal = 0;
    while (pos < p->page.length) {
        const uint8_t *r;
        uint32_t len, tag;
        if (p->page.length - pos < 8) return 0;
        r = p->page.bytes + pos;
        tag = be32(r); len = be32(r + 4);
        if (len < 8 || len > p->page.length - pos) return 0;
        if (!count && (tag != UINT32_C(0x10002) || len != 3288u)) return 0;
        if (count && tag == UINT32_C(0x10002)) return 0;
        if (tag == UINT32_MAX) {
            if (len != 8 || pos != p->page.length - 8) return 0;
            terminal = 1;
        }
        ++count;
        if (count > p->record_count) return 0;
        pos += len;
    }
    return terminal && count == p->record_count && pos == p->page.length;
}

enum fp_result fp_lease_begin(struct fp_lease *l, struct fp_reader_view *r,
                             const struct fp_package *p, enum fp_cache cache,
                             const struct fp_hook_words *hooks)
{
    uint32_t i;
    if (!l || !r || !p || !hooks) return FP_REFUSED;
    if (l->phase == FP_ACTIVE) return FP_REENTRY;
    if (l->phase == FP_POISONED) return FP_FAIL_STOP;
    if (l->phase != FP_EMPTY) return FP_REFUSED;
    if (r->page_id != FP_MAINB2_PAGE_ID) return FP_NOT_TARGET;
    if (cache != FP_CACHE_FIRST_PARSE || !r->resource_id || !r->generation ||
        r->stream_handle || r->owns_input ||
        r->source.arm_base != FP_STOCK_NBU_BASE ||
        r->position != FP_STOCK_PAGE_START ||
        hooks->string_entry != UINT32_C(0x3ffff1b1) ||
        hooks->nbr_entry != UINT32_C(0xb086b500) ||
        hooks->record_entry != UINT32_C(0x4ff0e92d)) return FP_REFUSED;
    if (!blob_valid(&r->source) || !blob_valid(&r->pool) ||
        r->source.length < FP_STOCK_PAGE_END ||
        /* Bound NBU view to the pinned seg0 address range, not arbitrary RAM. */
        r->source.length > UINT32_C(0x2ef6e00) - UINT32_C(0x18c0460) ||
        r->pool.arm_base != FP_STOCK_NBU_BASE + 20u ||
        r->pool.length != FP_STOCK_POOL_LENGTH ||
        r->pool.bytes != r->source.bytes + 20u ||
        p->page_id != FP_MAINB2_PAGE_ID ||
        p->record_count != FP_PRIVATE_RECORD_COUNT ||
        !blob_valid(&p->page) || !blob_valid(&p->pool) ||
        p->page.length != FP_PRIVATE_PAGE_LENGTH ||
        p->pool.length != FP_PRIVATE_POOL_LENGTH ||
        overlaps(&p->page, &p->pool) || overlaps(&p->page, &r->source) ||
        overlaps(&p->pool, &r->source)) return FP_REFUSED;
    if (!page_valid(p) ||
        fp_fnv1a32(p->page.bytes, p->page.length) != UINT32_C(0x1ac9054d) ||
        fp_fnv1a32(p->pool.bytes, p->pool.length) != UINT32_C(0x6bab62d9))
        return FP_REFUSED;
    /* Strong SHA-256 source/package pinning is a separate host validation gate.
     * This exact prefix comparison guards the existing string offset meaning. */
    for (i = 0; i < FP_STOCK_POOL_LENGTH; ++i)
        if (p->pool.bytes[i] != r->pool.bytes[i]) return FP_REFUSED;
    if (fp_fnv1a32(r->source.bytes + FP_STOCK_PAGE_START,
                  FP_STOCK_PAGE_END - FP_STOCK_PAGE_START) !=
        UINT32_C(0x617110b3)) return FP_REFUSED;
    l->saved = *r; l->reader = r; l->package = *p;
    l->cursor = 0; l->records = 0; l->terminal_seen = 0;
    r->source = p->page; r->pool = p->pool; r->position = 0;
    l->phase = FP_ACTIVE;
    return FP_OK;
}

enum fp_result fp_lease_peek(struct fp_lease *l, struct fp_record_token *t)
{
    const uint8_t *r;
    uint32_t len, tag;
    if (!l || !t || l->phase != FP_ACTIVE)
        return l && l->phase == FP_POISONED ? FP_FAIL_STOP : FP_NOT_LIVE;
    if (!private_view(l) || l->reader->position != l->cursor) return poison(l);
    if (l->cursor == l->package.page.length) return FP_END;
    if (l->cursor > l->package.page.length ||
        l->package.page.length - l->cursor < 8 ||
        l->records >= l->package.record_count || l->terminal_seen) return poison(l);
    r = l->package.page.bytes + l->cursor;
    tag = be32(r); len = be32(r + 4);
    if (len < 8 || len > l->package.page.length - l->cursor ||
        (!l->records && (tag != UINT32_C(0x10002) || len != 3288u)) ||
        (l->records && tag == UINT32_C(0x10002)) ||
        (tag == UINT32_MAX && (len != 8 ||
         l->cursor != l->package.page.length - 8))) return poison(l);
    t->generation = l->saved.generation; t->ordinal = l->records;
    t->offset = l->cursor; t->length = len; t->tag = tag;
    return FP_OK;
}

static int token_matches(const struct fp_lease *l, const struct fp_record_token *t)
{
    const uint8_t *r;
    if (!t || t->generation != l->saved.generation || t->ordinal != l->records ||
        t->offset != l->cursor || l->cursor > l->package.page.length ||
        l->package.page.length - l->cursor < 8) return 0;
    r = l->package.page.bytes + l->cursor;
    return t->length >= 8 && t->length <= l->package.page.length - l->cursor &&
           t->length == be32(r + 4) && t->tag == be32(r);
}

enum fp_result fp_lease_body(struct fp_lease *l, const struct fp_record_token *t,
                           struct fp_span *s)
{
    if (s) { s->bytes = NULL; s->length = 0; }
    if (!l || !s || l->phase != FP_ACTIVE)
        return l && l->phase == FP_POISONED ? FP_FAIL_STOP : FP_NOT_LIVE;
    if (!private_view(l) || l->reader->position != l->cursor ||
        !token_matches(l, t)) return poison(l);
    s->bytes = l->package.page.bytes + t->offset + 8;
    s->length = t->length - 8;
    return FP_OK;
}

enum fp_result fp_lease_accept(struct fp_lease *l, const struct fp_record_token *t,
                             int accepted)
{
    if (!l || l->phase != FP_ACTIVE)
        return l && l->phase == FP_POISONED ? FP_FAIL_STOP : FP_NOT_LIVE;
    if (accepted != 1 || !private_view(l) || !token_matches(l, t) ||
        l->reader->position != l->cursor + t->length) return poison(l);
    l->cursor += t->length; ++l->records;
    if (t->tag == UINT32_MAX) l->terminal_seen = 1;
    return FP_OK;
}

enum fp_result fp_lease_finish(struct fp_lease *l)
{
    if (!l || l->phase != FP_ACTIVE)
        return l && l->phase == FP_POISONED ? FP_FAIL_STOP : FP_NOT_LIVE;
    if (!private_view(l) || l->reader->position != l->package.page.length ||
        l->cursor != l->package.page.length || !l->terminal_seen ||
        l->records != l->package.record_count ||
        fp_fnv1a32(l->package.page.bytes, l->package.page.length) != UINT32_C(0x1ac9054d) ||
        fp_fnv1a32(l->package.pool.bytes, l->package.pool.length) != UINT32_C(0x6bab62d9))
        return poison(l);
    *l->reader = l->saved;
    l->reader->position = FP_STOCK_PAGE_END;
    l->phase = FP_PARSED_PINNED;
    return FP_OK;
}

enum fp_result fp_lease_abort(struct fp_lease *l) { return poison(l); }

enum fp_result fp_lease_string(struct fp_lease *l, uint32_t offset,
                             struct fp_span *s)
{
    uint32_t end;
    if (s) { s->bytes = NULL; s->length = 0; }
    if (!l || !s || (l->phase != FP_ACTIVE && l->phase != FP_PARSED_PINNED))
        return l && l->phase == FP_POISONED ? FP_FAIL_STOP : FP_NOT_LIVE;
    if (l->phase == FP_ACTIVE && !private_view(l)) return poison(l);
    if (offset == UINT32_MAX) return FP_OK; /* stock null-string sentinel */
    if (offset >= l->package.pool.length) return FP_REFUSED;
    end = offset;
    while (end < l->package.pool.length && l->package.pool.bytes[end]) ++end;
    if (end == l->package.pool.length) return FP_REFUSED;
    s->bytes = l->package.pool.bytes + offset; s->length = end - offset;
    return FP_OK;
}

enum fp_result fp_lease_owner_destroyed(struct fp_lease *l, uint32_t id,
                                     uint32_t generation, int destroyed)
{
    if (!l || (l->phase != FP_PARSED_PINNED && l->phase != FP_POISONED) ||
        destroyed != 1 || id != l->saved.resource_id || generation != l->saved.generation)
        return FP_REFUSED;
    l->reader = NULL;
    l->package.page.bytes = NULL; l->package.pool.bytes = NULL;
    l->saved.source.bytes = NULL; l->saved.pool.bytes = NULL;
    l->phase = FP_RELEASED;
    return FP_OK;
}
