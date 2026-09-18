#ifndef FPLOSSLESS_READER_LEASE_H
#define FPLOSSLESS_READER_LEASE_H

#include <stddef.h>
#include <stdint.h>

/* OFFLINE CONTRACT ONLY: not the native parser layout or a callable hook ABI. */
#define FP_MAINB2_PAGE_ID 10u
#define FP_STOCK_NBU_BASE UINT32_C(0xc18c0460)
#define FP_STOCK_PAGE_START UINT32_C(0x76ff04)
#define FP_STOCK_PAGE_END UINT32_C(0x795950)
#define FP_STOCK_POOL_LENGTH 176152u
#define FP_PRIVATE_PAGE_LENGTH 179725u
#define FP_PRIVATE_POOL_LENGTH 176240u
#define FP_PRIVATE_RECORD_COUNT 1538u
#define FP_NATIVE_BINDING_READY 0

enum fp_result {
    FP_OK = 0, FP_NOT_TARGET, FP_REFUSED, FP_REENTRY, FP_FAIL_STOP,
    FP_END, FP_NOT_LIVE
};
enum fp_cache { FP_CACHE_UNKNOWN = 0, FP_CACHE_FIRST_PARSE,
                FP_CACHE_STOCK, FP_CACHE_PRIVATE };
enum fp_phase { FP_EMPTY = 0, FP_ACTIVE, FP_PARSED_PINNED,
                FP_POISONED, FP_RELEASED };

/* bytes/capacity describe accessible host memory. arm_base models a separately
 * validated target allocation; test values are not reserved camera addresses. */
struct fp_blob {
    const uint8_t *bytes;
    size_t capacity;
    uint32_t arm_base;
    uint32_t length;
};
struct fp_reader_view {
    struct fp_blob source;
    struct fp_blob pool;
    uint32_t position;
    uint32_t resource_id;
    uint32_t generation;
    uint32_t stream_handle; /* only memory mode (zero) is accepted */
    uint32_t owns_input;    /* borrowed memory only */
    uint32_t page_id;       /* verified by a future page selector, not in header */
};
struct fp_package {
    struct fp_blob page;
    struct fp_blob pool;
    uint32_t page_id;
    uint32_t record_count;
};
struct fp_hook_words {
    uint32_t string_entry; /* C05E5B58 */
    uint32_t nbr_entry;    /* C05E84D8 */
    uint32_t record_entry; /* C05E6400 */
};
struct fp_record_token {
    uint32_t generation;
    uint32_t ordinal;
    uint32_t offset;
    uint32_t length;
    uint32_t tag;
};
struct fp_span { const uint8_t *bytes; uint32_t length; };
struct fp_lease {
    enum fp_phase phase;
    struct fp_reader_view saved;
    struct fp_reader_view *reader;
    struct fp_package package;
    uint32_t cursor;
    uint32_t records;
    uint32_t terminal_seen;
};

/* Zero-initialize a fresh lease. Never zero/reset a live or poisoned lease. */
enum fp_result fp_lease_begin(struct fp_lease *, struct fp_reader_view *,
                             const struct fp_package *, enum fp_cache,
                             const struct fp_hook_words *);
enum fp_result fp_lease_peek(struct fp_lease *, struct fp_record_token *);
/* Body spans are transient: valid only until accept/finish/failure. Copied raw
 * C pointers cannot be revoked; callers must not retain them. */
enum fp_result fp_lease_body(struct fp_lease *, const struct fp_record_token *,
                           struct fp_span *);
/* Caller models successful consumption by updating view.position to record end.
 * accepted is normalized success, NOT an assumed native return-code ABI. */
enum fp_result fp_lease_accept(struct fp_lease *,
                             const struct fp_record_token *, int accepted);
enum fp_result fp_lease_finish(struct fp_lease *);
enum fp_result fp_lease_abort(struct fp_lease *);
/* Uses the lease's retained private pool even after reader restoration. Native
 * lazy resolver/callback lifetime is NOT proven by this host helper. */
enum fp_result fp_lease_string(struct fp_lease *, uint32_t offset,
                             struct fp_span *);
/* Explicit external proof: all objects, reader, and callbacks of this exact
 * resource generation have been destroyed. This function does not destroy them
 * and never restores/retries a partially parsed native resource. */
enum fp_result fp_lease_owner_destroyed(struct fp_lease *, uint32_t resource_id,
                                     uint32_t generation, int all_destroyed);
uint32_t fp_fnv1a32(const uint8_t *, uint32_t);

#endif
