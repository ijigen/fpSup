#include "reader_lease.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint8_t *seg, *page, *pool;
static size_t seglen, pagelen, poollen;
static unsigned tests;
static const struct fp_hook_words original_hooks = {
    UINT32_C(0x3ffff1b1), UINT32_C(0xb086b500), UINT32_C(0x4ff0e92d)
};
struct fixture {
    struct fp_reader_view r;
    struct fp_package p;
    struct fp_lease l;
};

/* Deliberate host misalignment exercises byte reads and BE32 record lengths. */
static uint8_t *load(const char *path, size_t *length)
{
    FILE *f = fopen(path, "rb");
    long n;
    uint8_t *p;
    assert(f && fseek(f, 0, SEEK_END) == 0);
    n = ftell(f); assert(n > 0 && fseek(f, 0, SEEK_SET) == 0);
    p = malloc((size_t)n + 1); assert(p);
    assert(fread(p + 1, 1, (size_t)n, f) == (size_t)n && fclose(f) == 0);
    *length = (size_t)n;
    return p + 1;
}

static struct fixture fresh(void)
{
    struct fixture f = {0};
    f.r.source = (struct fp_blob){seg + 0x18c0460, seglen - 0x18c0460,
                                 FP_STOCK_NBU_BASE, (uint32_t)(seglen - 0x18c0460)};
    f.r.pool = (struct fp_blob){seg + 0x18c0474, FP_STOCK_POOL_LENGTH,
                               FP_STOCK_NBU_BASE + 20, FP_STOCK_POOL_LENGTH};
    f.r.position = FP_STOCK_PAGE_START;
    f.r.resource_id = 0x50000001; f.r.generation = 7;
    f.r.page_id = FP_MAINB2_PAGE_ID;
    f.p.page = (struct fp_blob){page, pagelen, 0xd0000000, (uint32_t)pagelen};
    f.p.pool = (struct fp_blob){pool, poollen, 0xd0040000, (uint32_t)poollen};
    f.p.page_id = FP_MAINB2_PAGE_ID; f.p.record_count = FP_PRIVATE_RECORD_COUNT;
    return f;
}

static enum fp_result begin(struct fixture *f)
{
    return fp_lease_begin(&f->l, &f->r, &f->p, FP_CACHE_FIRST_PARSE, &original_hooks);
}

static void denied(struct fixture *f, enum fp_result expected)
{
    struct fp_reader_view before = f->r;
    assert(begin(f) == expected);
    assert(memcmp(&before, &f->r, sizeof(before)) == 0 && f->l.phase == FP_EMPTY);
    ++tests;
}

static void consume(struct fixture *f)
{
    struct fp_record_token t;
    struct fp_span body;
    unsigned unaligned = 0;
    while (fp_lease_peek(&f->l, &t) == FP_OK) {
        if (t.offset & 3) ++unaligned;
        assert(fp_lease_body(&f->l, &t, &body) == FP_OK);
        assert(body.length == t.length - 8);
        f->r.position += t.length;
        assert(fp_lease_accept(&f->l, &t, 1) == FP_OK);
    }
    assert(unaligned > 0 && f->l.phase == FP_ACTIVE);
    assert(f->l.records == FP_PRIVATE_RECORD_COUNT);
    assert(fp_lease_peek(&f->l, &t) == FP_END);
}

static void refused_inputs(void)
{
    struct fixture f;
    struct fp_hook_words hooks;
    struct fp_reader_view before;
    unsigned i;
    f = fresh(); f.r.page_id = 11; denied(&f, FP_NOT_TARGET);
    for (i = 0; i < 4; ++i) if (i != FP_CACHE_FIRST_PARSE) {
        f = fresh(); before = f.r;
        assert(fp_lease_begin(&f.l, &f.r, &f.p, (enum fp_cache)i, &original_hooks) == FP_REFUSED);
        assert(memcmp(&before, &f.r, sizeof(before)) == 0); ++tests;
    }
    f = fresh(); f.r.source.length = FP_STOCK_PAGE_END - 1; denied(&f, FP_REFUSED);
    f = fresh(); --f.r.source.capacity; denied(&f, FP_REFUSED);
    f = fresh(); ++f.r.source.length; ++f.r.source.capacity; denied(&f, FP_REFUSED);
    f = fresh(); f.r.position++; denied(&f, FP_REFUSED);
    f = fresh(); f.r.source.arm_base++; denied(&f, FP_REFUSED);
    f = fresh(); f.r.stream_handle = 1; denied(&f, FP_REFUSED);
    f = fresh(); f.r.owns_input = 1; denied(&f, FP_REFUSED);
    f = fresh(); f.r.resource_id = 0; denied(&f, FP_REFUSED);
    f = fresh(); f.r.generation = 0; denied(&f, FP_REFUSED);
    f = fresh(); f.p.page_id = 31; denied(&f, FP_REFUSED);
    f = fresh(); --f.p.record_count; denied(&f, FP_REFUSED);
    f = fresh(); --f.p.page.length; denied(&f, FP_REFUSED);
    f = fresh(); --f.p.pool.length; denied(&f, FP_REFUSED);
    f = fresh(); --f.p.page.capacity; denied(&f, FP_REFUSED);
    f = fresh(); f.p.page.arm_base = UINT32_MAX - 2; denied(&f, FP_REFUSED);
    f = fresh(); f.p.pool.arm_base = f.p.page.arm_base + 100; denied(&f, FP_REFUSED);
    f = fresh(); f.p.page.arm_base = FP_STOCK_NBU_BASE; denied(&f, FP_REFUSED);
    f = fresh(); f.p.pool.bytes = f.p.page.bytes + 1; denied(&f, FP_REFUSED);
    f = fresh(); f.p.pool.bytes = f.r.pool.bytes; denied(&f, FP_REFUSED);
    f = fresh(); f.r.pool.bytes++; denied(&f, FP_REFUSED);
    f = fresh(); f.r.pool.arm_base++; denied(&f, FP_REFUSED);
    f = fresh(); --f.r.pool.length; denied(&f, FP_REFUSED);
    for (i = 0; i < 3; ++i) {
        f = fresh(); hooks = original_hooks; before = f.r;
        if (i == 0) hooks.string_entry ^= 1;
        if (i == 1) hooks.nbr_entry ^= 1;
        if (i == 2) hooks.record_entry ^= 1;
        assert(fp_lease_begin(&f.l, &f.r, &f.p, FP_CACHE_FIRST_PARSE, &hooks) == FP_REFUSED);
        assert(memcmp(&before, &f.r, sizeof(before)) == 0); ++tests;
    }
}

static void mutation_preflight(void)
{
    const uint32_t offsets[] = {0, 4, 7, 3288 + 4, FP_PRIVATE_PAGE_LENGTH - 1,
                               FP_PRIVATE_PAGE_LENGTH - 8};
    size_t i;
    struct fixture f;
    for (i = 0; i < sizeof(offsets) / sizeof(offsets[0]); ++i) {
        f = fresh(); page[offsets[i]] ^= 0x80;
        denied(&f, FP_REFUSED); page[offsets[i]] ^= 0x80;
    }
    f = fresh(); pool[FP_STOCK_POOL_LENGTH] ^= 1;
    denied(&f, FP_REFUSED); pool[FP_STOCK_POOL_LENGTH] ^= 1;
    f = fresh(); seg[0x18c0474] ^= 1;
    denied(&f, FP_REFUSED); seg[0x18c0474] ^= 1;
    f = fresh(); seg[0x2030364 + 20] ^= 1;
    denied(&f, FP_REFUSED); seg[0x2030364 + 20] ^= 1;
}

static void happy_and_lifetime(void)
{
    struct fixture f = fresh();
    struct fp_reader_view original = f.r;
    struct fp_record_token token;
    struct fp_span body, string;
    assert(begin(&f) == FP_OK && f.l.phase == FP_ACTIVE);
    assert(fp_lease_peek(&f.l, &token) == FP_OK);
    assert(fp_lease_body(&f.l, &token, &body) == FP_OK);
    assert(begin(&f) == FP_REENTRY && f.r.position == 0);
    assert(fp_lease_owner_destroyed(&f.l, original.resource_id, original.generation, 1) == FP_REFUSED);
    assert(fp_lease_string(&f.l, 176224, &string) == FP_OK);
    assert(string.length == 12 && !memcmp(string.bytes, "Lossless RAW", 12));
    assert(fp_lease_string(&f.l, UINT32_MAX, &string) == FP_OK && !string.bytes);
    assert(fp_lease_string(&f.l, FP_PRIVATE_POOL_LENGTH, &string) == FP_REFUSED && !string.bytes);
    consume(&f);
    assert(fp_lease_finish(&f.l) == FP_OK && f.l.phase == FP_PARSED_PINNED);
    original.position = FP_STOCK_PAGE_END;
    assert(!memcmp(&f.r, &original, sizeof(original)));
    assert(fp_lease_body(&f.l, &token, &body) == FP_NOT_LIVE && !body.bytes);
    assert(fp_lease_string(&f.l, 176224, &string) == FP_OK);
    assert(string.bytes >= pool && string.bytes < pool + poollen);
    assert(string.bytes != f.r.pool.bytes + 176224); /* not restored stock pool */
    assert(begin(&f) == FP_REFUSED); /* completed generation is still borrowed */
    assert(fp_lease_owner_destroyed(&f.l, original.resource_id, original.generation, 0) == FP_REFUSED);
    assert(fp_lease_owner_destroyed(&f.l, original.resource_id, original.generation + 1, 1) == FP_REFUSED);
    assert(fp_lease_owner_destroyed(&f.l, original.resource_id + 1, original.generation, 1) == FP_REFUSED);
    assert(fp_lease_owner_destroyed(&f.l, original.resource_id, original.generation, 1) == FP_OK);
    assert(fp_lease_string(&f.l, 176224, &string) == FP_NOT_LIVE && !string.bytes);
    assert(f.l.phase == FP_RELEASED && !f.l.package.page.bytes && !f.l.package.pool.bytes);
    assert(begin(&f) == FP_REFUSED);
    ++tests;
}

static void fail_stops(void)
{
    struct fixture f;
    struct fp_record_token t;
    struct fp_span s;
    unsigned i;
    for (i = 0; i < 9; ++i) {
        f = fresh(); assert(begin(&f) == FP_OK);
        assert(fp_lease_peek(&f.l, &t) == FP_OK);
        if (i == 0) assert(fp_lease_finish(&f.l) == FP_FAIL_STOP);
        if (i == 1) { f.r.pool = f.l.saved.pool; assert(fp_lease_finish(&f.l) == FP_FAIL_STOP); }
        if (i == 2) { f.r.generation++; assert(fp_lease_peek(&f.l, &t) == FP_FAIL_STOP); }
        if (i == 3) { f.r.source.length--; assert(fp_lease_body(&f.l, &t, &s) == FP_FAIL_STOP); }
        if (i == 4) assert(fp_lease_accept(&f.l, &t, 0) == FP_FAIL_STOP);
        if (i == 5) assert(fp_lease_accept(&f.l, &t, 1) == FP_FAIL_STOP); /* cursor not consumed */
        if (i == 6) { ++t.ordinal; assert(fp_lease_body(&f.l, &t, &s) == FP_FAIL_STOP); }
        if (i == 7) { f.r.position++; assert(fp_lease_peek(&f.l, &t) == FP_FAIL_STOP); }
        if (i == 8) assert(fp_lease_abort(&f.l) == FP_FAIL_STOP);
        assert(f.l.phase == FP_POISONED && f.r.source.bytes != f.l.saved.source.bytes);
        assert(fp_lease_finish(&f.l) == FP_FAIL_STOP);
        assert(fp_lease_body(&f.l, &t, &s) == FP_FAIL_STOP && !s.bytes);
        assert(fp_lease_string(&f.l, 176224, &s) == FP_FAIL_STOP && !s.bytes);
        assert(begin(&f) == FP_FAIL_STOP);
        assert(fp_lease_owner_destroyed(&f.l, f.l.saved.resource_id,
                                       f.l.saved.generation, 1) == FP_OK);
        ++tests;
    }
    f = fresh(); assert(begin(&f) == FP_OK); consume(&f);
    f.r.resource_id++; assert(fp_lease_finish(&f.l) == FP_FAIL_STOP); ++tests;
    f = fresh(); assert(begin(&f) == FP_OK); consume(&f);
    page[100] ^= 1; assert(fp_lease_finish(&f.l) == FP_FAIL_STOP); page[100] ^= 1; ++tests;
    f = fresh(); assert(begin(&f) == FP_OK); consume(&f);
    pool[176224] ^= 1; assert(fp_lease_finish(&f.l) == FP_FAIL_STOP); pool[176224] ^= 1; ++tests;
    f = fresh(); assert(begin(&f) == FP_OK); assert(fp_lease_peek(&f.l, &t) == FP_OK);
    page[4] = 0xff; assert(fp_lease_peek(&f.l, &t) == FP_FAIL_STOP); page[4] = 0; ++tests;
    f = fresh(); assert(begin(&f) == FP_OK); assert(fp_lease_peek(&f.l, &t) == FP_OK);
    f.r.position = t.length; assert(fp_lease_accept(&f.l, &t, 1) == FP_OK);
    assert(fp_lease_body(&f.l, &t, &s) == FP_FAIL_STOP && !s.bytes); ++tests;
}

int main(int argc, char **argv)
{
    assert(argc == 4);
    seg = load(argv[1], &seglen); page = load(argv[2], &pagelen); pool = load(argv[3], &poollen);
    assert(seglen == 49245696 && pagelen == FP_PRIVATE_PAGE_LENGTH && poollen == FP_PRIVATE_POOL_LENGTH);
    refused_inputs(); mutation_preflight(); happy_and_lifetime(); fail_stops();
    printf("{\"test_groups\":%u,\"records_walked_per_complete_parse\":%u,"
           "\"native_binding_ready\":false,\"camera_accessed\":false}\n", tests,
           FP_PRIVATE_RECORD_COUNT);
    free(seg - 1); free(page - 1); free(pool - 1);
    return 0;
}
