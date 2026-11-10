#include "frame_hold.h"

/* Layout of a kind-1 frame, Ver.5.02 [C/L]:
 *   frame+0x04   kind (1 = CinemaDNG RAW)
 *   frame+0x10   the 18-word descriptor the creator copied (C02E5B78)
 *   frame+0x4C   descriptor word 15: the raster, handle + frame[0x128]
 *                (C037A990); C038C5F8 hands it on before the enqueue, and
 *                dispatch subtracts frame[0x14C] from it to make the file
 *                buffer and writes that (XC_StillCreateFile, C037E0F8)
 *   frame+0x68   RAW allocation descriptor {handle, capacity, class}
 *                (C037A990 -> C001CFD8(class 10, &frame[0x68], ...)); freed
 *                through C0374180 after the file is written (C03777B8)
 *   frame+0x128  header reserve, 0x15400 for kind 1 (C0374268)
 *   frame+0x14C  header bytes, set from C038A0F8()+0xC before the enqueue;
 *                C00FBB90 has already copied the header there by DMA
 *   frame+0x1104 native state; 0xB is "pending" (C037DDE0)
 *   frame+0x1114 how many clones share this allocation (Dup2 path)
 *   frame+0x1118 -1 = owns its allocation; else the id of the frame that
 *                does (C03777B8 frees the owner's records on the last clone)
 *   file buffer  = raster - frame[0x14C]: handle + 0x2000 with the stock
 *                0x13400 header (seg[0], measured live 2026-09-26); a take
 *                whose template carries the card's tag (header_tag.h) has a
 *                longer header and its file starts earlier
 *   raster       = handle + header reserve = file + frame[0x14C]
 */
#define FRAME_KIND        0x04u
#define FRAME_DESCRIPTOR  0x10u
#define FRAME_RASTER      0x4cu
#define FRAME_HANDLE      0x68u
#define FRAME_CAPACITY    0x6cu
#define FRAME_CLASS       0x70u
#define FRAME_RESERVE     0x128u
#define FRAME_HEADER      0x14cu
#define FRAME_STATE       0x1104u
#define FRAME_CLONES      0x1114u
#define FRAME_OWNER       0x1118u
#define OWNS_ALLOCATION   0xffffffffu
#define RAW_CLASS         10u
#define KIND_CINEMADNG    1u
#define STATE_PENDING     0xbu
#define HEADER_RESERVE    0x15400u
#define HEAD_MIN          0x400u     /* a header this short is not a DNG's */
/* A job not done after STALL_TIMES its expected time is given up on (the
 * engine, ~170 Mpix/s measured: STALL_PIX_PER_US), but never before
 * STALL_MIN_US. 2026-10-06: a stuck job was waited on for 250 checks
 * (~0.5-1 s); every frame meanwhile went out RAW, an OG3K take's data rate
 * passed the card's and the camera stopped itself (A001_042). Expected: FHD
 * ~14 ms, OG3K ~40 ms, UHD ~55 ms, 6K ~145 ms. */
#define STALL_PIX_PER_US   150u
#define STALL_TIMES          3u
#define STALL_MIN_US     50000u
#define STOP_POLLS        1000u      /* one tick each; the firmware's own
                                        wait for an FHD frame is 100 ticks */

#if defined(FPL_FRAME_HOLD_HOST_TEST)
#define H (&fpl_hold_test_natives)
#define native_frame(id) H->frame(id)
#define native_enqueue(c, id, a) H->enqueue(c, id, a)
#define peek(a) H->read(a)
#define poke(a, v) H->write(a, v)
#define uncached(a) H->uncached(a)
#define barrier() H->barrier()
#define irq_off() H->irq_off()
#define irq_restore(m) H->irq_restore(m)
#define sleep_ms(n) H->sleep_ms(n)
#define header_dma(to, from, n) H->dma(to, from, n)
#define tick_us() H->tick_us()
#elif defined(__arm__) && UINTPTR_MAX == UINT32_MAX
static uintptr_t native_frame(uint32_t id) {
    typedef uintptr_t (*registry)(void);
    typedef uintptr_t (*lookup)(uintptr_t, uint32_t);
    return ((lookup)0xc03753c0u)(((registry)0xc0374220u)(), id);      /* ARM */
}
static uint32_t native_enqueue_raw(uintptr_t creator, uint32_t id, uint32_t argument) {
    typedef uint32_t (*fn)(uintptr_t, uint32_t, uint32_t);
    return ((fn)0xc037dd50u)(creator, id, argument) & 0xffu;          /* uxtb */
}
#define peek(a) (*(volatile const uint32_t *)(a))
#define poke(a, v) (*(volatile uint32_t *)(a) = (v))
#define uncached(a) ((uintptr_t)(a) + 0x40000000u)
#define barrier() __asm__ volatile("dsb sy" ::: "memory")
static uint32_t irq_off(void) {                   /* C000EC14: old CPSR, I+F set */
    typedef uint32_t (*fn)(void);
    return ((fn)0xc000ec14u)();
}
static void irq_restore(uint32_t m) {             /* C000EC24: I+F back as they were */
    typedef void (*fn)(uint32_t);
    ((fn)0xc000ec24u)(m);
}
/* C00FBB90, the DMA copy C038C5F8 puts the header into the frame with:
 * {source, destination, bytes, flags 0}. Synchronous (waits on its own
 * completion flag), does its own cache maintenance, serialised by its own
 * semaphore: task context only. 0 = copied. */
static uint32_t header_dma(uintptr_t to, uintptr_t from, uint32_t bytes) {
    typedef uint32_t (*fn)(volatile uint32_t *);
    volatile uint32_t r[4];
    r[0] = (uint32_t)from;
    r[1] = (uint32_t)to;
    r[2] = bytes;
    r[3] = 0;
    return ((fn)0xc00fbb91u)(r);                  /* Thumb */
}
static void sleep_ms(uint32_t n) {                /* C03705D8 -> tk_dly_tsk */
    typedef void (*fn)(uint32_t);
    ((fn)0xc03705d8u)(n);
}
static uint32_t tick_us(void) {                   /* C002B6E0: the 1 MHz counter */
    typedef uint32_t (*fn)(void);
    return ((fn)0xc002b6e0u)();
}
#ifdef FPL_DIAG_HOOK_TIME
/* diagnostic only: the stock enqueue's own time, to take out of the hooks' */
static uint32_t diag_enqueue(struct fpl_frame_hold *h, uintptr_t creator, uint32_t id,
                             uint32_t argument) {
    uint32_t began = tick_us(), r = native_enqueue_raw(creator, id, argument);
    uint32_t took = tick_us() - began;
    if (!h) return r;
    ++h->diag_enq_n;
    h->diag_enq_us += took;
    if (took > h->diag_enq_max_us) h->diag_enq_max_us = took;
    return r;
}
#define native_enqueue(c, i, a) diag_enqueue(h, c, i, a)
#else
#define native_enqueue native_enqueue_raw
#endif
#else
#error "ARM32 native frame ABI required; host tests must explicitly substitute it"
#endif

static void saturate(uint32_t *v) { if (*v != UINT32_MAX) ++*v; }
static uint32_t bswap(uint32_t v) {
    return (v >> 24) | ((v >> 8) & 0xff00u) | ((v & 0xff00u) << 8) | (v << 24);
}
static uint32_t align512(uint32_t v) { return (v + 0x1ffu) & ~0x1ffu; }

uint32_t fpl_hold_init(struct fpl_frame_hold *h, struct fpl_pipeline *p,
                       const struct fpl_producer_facts *facts,
                       const struct fpl_hold_workspace *w) {
    uint32_t result;
    /* The output span is optional: without one, only frames the buffer swap
     * can take are compressed; any other frame goes out as it is. */
    if (!h || !p || !facts || !w || !w->table || ((w->output | w->table) & 0x3ffu) ||
        !w->output != !w->output_capacity || !w->table_capacity ||
        (!w->output && !w->spare.handle))
        return FPL_INVALID;
    const unsigned char *bytes = (const unsigned char *)h;
    for (uint32_t n = 0; n < sizeof(*h); ++n)
        if (bytes[n]) return FPL_INVALID;
    if ((result = fpl_codec_job_init(&h->job)) != FPL_OK) return result;
    h->pipeline = p;
    h->facts = facts;
    h->workspace = *w;
    h->magic = FPL_HOLD_MAGIC;
    return FPL_OK;
}

static uint32_t hold_valid(const struct fpl_frame_hold *h) {
    return h && h->magic == FPL_HOLD_MAGIC && h->pipeline && h->facts;
}
static int32_t free_slot(const struct fpl_frame_hold *h) {
    for (uint32_t n = 0; n < FPL_HOLD_COMMITS; ++n)
        if (!h->ring[n].file) return (int32_t)n;
    return -1;
}
/* The source length the engine will be told, for THIS producer. */
static uint32_t told_source(const struct fpl_frame_hold *h) {
    return fpl_codec_source_bytes_test(h->facts->seen.width, h->facts->seen.height,
                                       h->facts->seen.format, h->pitch_test);
}

/* Copy-back. Word-by-word volatile accesses through the uncached alias made
 * the copy-back a large share of a frame period on the camera (2026-09-30);
 * eight words a pass through plain pointers lets the compiler burst with
 * ldm/stm. `bytes` is the padded payload: a multiple of 1 KiB. */
#if defined(FPL_FRAME_HOLD_HOST_TEST)
static void bulk_copy(uintptr_t to, uintptr_t from, uint32_t bytes) {
    for (uint32_t n = 0; n < bytes; n += 4) poke(to + n, peek(from + n));
}
#else
static void bulk_copy(uintptr_t to, uintptr_t from, uint32_t bytes) {
    uint32_t *d = (uint32_t *)to;
    const uint32_t *s = (const uint32_t *)from;
    for (uint32_t n = bytes >> 5; n; --n, d += 8, s += 8) {
        uint32_t a = s[0], b = s[1], c = s[2], e = s[3];
        uint32_t f = s[4], g = s[5], i = s[6], j = s[7];
        d[0] = a; d[1] = b; d[2] = c; d[3] = e;
        d[4] = f; d[5] = g; d[6] = i; d[7] = j;
    }
    for (uint32_t n = (bytes & 31u) >> 2; n; --n) *d++ = *s++;
}
#endif

/* The frame's header length (frame+0x14C), or 0 when it cannot be the
 * file's: the file is the `head` bytes before the raster, inside the reserve. */
static uint32_t frame_head(uintptr_t frame) {
    uint32_t head = peek(frame + FRAME_HEADER);
    return head >= HEAD_MIN && head <= HEADER_RESERVE && !(head & 3u) ? head : 0;
}

/* May this frame's allocation be exchanged for the spare? Only a frame that
 * owns its allocation outright, with no clone reading it, whose record is the
 * allocator's own class-10 kind, whose raster pointer is still the one derived
 * from that record, and whose header is where the file will be cut from; and
 * a spare at least as large. Checked when the frame is held and again at the
 * release, because the swap is what makes the firmware free S instead of A. */
static uint32_t swap_allowed(const struct fpl_frame_hold *h, uintptr_t frame) {
    uintptr_t spare = h->workspace.spare.handle, handle;
    if (!spare || (spare & 0x3ffu) || h->workspace.spare.allocator_class != RAW_CLASS)
        return 0;
    handle = peek(frame + FRAME_HANDLE);
    return handle && handle != spare &&
           peek(frame + FRAME_CLASS) == RAW_CLASS &&
           peek(frame + FRAME_OWNER) == OWNS_ALLOCATION &&
           peek(frame + FRAME_CLONES) == 0 &&
           peek(frame + FRAME_RESERVE) == HEADER_RESERVE &&
           frame_head(frame) &&
           (frame != h->frame || frame_head(frame) == h->head) &&
           peek(frame + FRAME_RASTER) == handle + HEADER_RESERVE &&
           h->workspace.spare.capacity >= peek(frame + FRAME_CAPACITY);
}

/* ---- the handoff: this frame's result into this frame, then queue it ---- */
static uint32_t handoff(void *context, const struct fpl_frame_lease *lease,
                        const struct fpl_frame_output *output, uint32_t *proofs) {
    struct fpl_frame_hold *h = (struct fpl_frame_hold *)context;
    if (output) {
        int32_t slot = free_slot(h);
        struct fpl_hold_commit *c;
        uint32_t tiles = h->job.tiles;
        /* Reserved at admission; still free because only this task publishes. */
        if (slot < 0 || tiles > FPL_CODEC_TILE_MAX) return FPL_FAULT;
        c = &h->ring[slot];
        uintptr_t file = lease->buffer;
        uint32_t capacity = lease->capacity;
        if (h->swapping && swap_allowed(h, h->frame)) {
            /* ZERO COPY: the payload is already at the spare's raster. The
             * prefix (the header DMA'd into this frame) goes along, then the
             * frame is given the spare's allocation and the spare this
             * frame's. Uncached both sides: DMA wrote A's header and will
             * read S. The file buffer is S's from here on. */
            uintptr_t frame = h->frame, spare = h->workspace.spare.handle;
            uint32_t a_capacity = peek(frame + FRAME_CAPACITY);
            uint32_t a_class = peek(frame + FRAME_CLASS);
            uintptr_t a = peek(frame + FRAME_HANDLE);
            /* the firmware's own header DMA; the CPU copy only if it fails */
#if defined(FPL_DIAG_HOOK_TIME) && !defined(FPL_FRAME_HOLD_HOST_TEST)
            uint32_t dma_t = tick_us();
#endif
            uint32_t dma_r = header_dma(spare, a, HEADER_RESERVE);
#if defined(FPL_DIAG_HOOK_TIME) && !defined(FPL_FRAME_HOLD_HOST_TEST)
            h->diag_dma_us += tick_us() - dma_t;
            h->diag_dma_n++;
#endif
            if (dma_r != 0) {
                bulk_copy(uncached(spare), uncached(a), HEADER_RESERVE);
                saturate(&h->dma_failed);
            }
            barrier();
            poke(frame + FRAME_HANDLE, spare);
            poke(frame + FRAME_CAPACITY, h->workspace.spare.capacity);
            poke(frame + FRAME_CLASS, h->workspace.spare.allocator_class);
            poke(frame + FRAME_RASTER, spare + HEADER_RESERVE);
            file = spare + HEADER_RESERVE - h->head;
            capacity = h->workspace.spare.capacity - (HEADER_RESERVE - h->head);
            h->workspace.spare.handle = a;
            h->workspace.spare.capacity = a_capacity;
            h->workspace.spare.allocator_class = a_class;
            saturate(&h->swapped);
        } else {
            /* The payload, into THIS frame's raster, through the uncached
             * alias on both sides: the engine wrote the output by DMA and
             * the SD engine will read the frame by DMA. */
            if (h->swapping) saturate(&h->swap_undone);
#if defined(FPL_DIAG_HOOK_TIME) && !defined(FPL_FRAME_HOLD_HOST_TEST)
            uint32_t copy_t = tick_us();
#endif
            bulk_copy(uncached(lease->buffer + h->head), uncached(output->bytes),
                      output->length);
#if defined(FPL_DIAG_HOOK_TIME) && !defined(FPL_FRAME_HOLD_HOST_TEST)
            h->diag_copy_us += tick_us() - copy_t;
            h->diag_copy_n++;
#endif
        }
        for (uint32_t n = 0; n < tiles; ++n)
            c->tile_bytes[n] = bswap(peek(uncached(h->job.table + 4u * n)));
        c->payload = output->length;
        c->tiles = tiles;
        c->tile_width = h->job.tile_width;
        c->tile_height = h->job.tile_height;
        c->capacity = capacity;
        c->stock_bytes = lease->stock_file_bytes;
        c->head = h->head;
        barrier();
        c->file = file;                      /* published */
        barrier();
        saturate(&h->compressed);
        if (h->job.misaligned) saturate(&h->pitch_forced);
    } else {
        saturate(&h->no_benefit);
    }
    /* The whole original call: re-marks 0xB and queues the frame. */
    native_enqueue(h->creator, h->native_id, 1);
    h->frame = 0;
    h->swapping = 0;
    *proofs = FPL_HANDOFF_ALL;
    return FPL_OK;
}

/* Collect the running job if it is done. `wait` spins on the one-tick poll,
 * which is only done at stop. Returns FPL_BUSY if still running. */
static uint32_t service_done(struct fpl_frame_hold *, struct fpl_pipeline *, uint32_t);
static uint32_t service(struct fpl_frame_hold *h, uint32_t wait) {
    struct fpl_pipeline *p = h->pipeline;
    uint32_t result, polls = 0;
    if (p->phase != FPL_SLOT_ENCODING) return FPL_OK;
    do {
        result = fpl_codec_job_poll(&h->job);
    } while (result == FPL_BUSY && wait && ++polls < STOP_POLLS);
    if (result == FPL_BUSY) return FPL_BUSY;
    return service_done(h, p, result);
}

static uint32_t service_done(struct fpl_frame_hold *h, struct fpl_pipeline *p,
                             uint32_t result) {
    struct fpl_frame_output out = {0, 0, 0, 0};

    if (result == FPL_OK) {
        out.bytes = h->swapping ? h->workspace.spare.handle + HEADER_RESERVE
                                : h->workspace.output;
        out.length = h->job.padded;
        out.file_bytes = h->head + h->job.padded;   /* the IFD and its tables
                                                       are in the header */
        out.validated = 1;       /* codec success, every tile, source length
                                    covered by the frame's own allocation,
                                    output bounded by F_INIT's checked length,
                                    same producer descriptor, source only read */
        result = fpl_pipeline_complete(p, &h->token, FPL_OK, 1, &out);
    } else if (result == FPL_UNSUPPORTED) {
        /* The engine refused: the output would not fit one frame, so the
         * complete DNG cannot be smaller. The frame goes out as it was. */
        saturate(&h->refused);
        /* Where the engine was told to write -- the spare when there is no
         * output span (2026-10-01: workspace.output 0 made this INVALID, the
         * frame was never given back, and native stop hung). Nothing is
         * copied from it: the result is READY_RAW. */
        out.bytes = h->job.destination;
        out.length = h->job.destination_bytes;
        out.file_bytes = p->lease.stock_file_bytes;
        out.validated = 1;
        result = fpl_pipeline_complete(p, &h->token, FPL_OK, 1, &out);
    } else {
        /* Engine state unknown. Its SOURCE was only ever read, so the held
         * frame goes to the card as it was -- otherwise native stop would
         * wait on its 0xB forever. The OUTPUT is not quiescent: the pipeline
         * stays ENCODING, no later frame is admitted, and the take cannot
         * finish, so that memory is never released while the engine might
         * still write it. */
        if (h->frame) {
            native_enqueue(h->creator, h->native_id, 1);
            h->frame = 0;
            saturate(&h->faults);
        }
        return FPL_FAULT;                /* the spare stays ours, and busy */
    }
    if (result != FPL_OK) {
        /* The engine is done (polled finished or refused) and only ever read
         * the frame: it goes to the card as it was, or native stop waits on
         * its 0xB forever. */
        if (h->frame) {
            native_enqueue(h->creator, h->native_id, 1);
            h->frame = 0;
        }
        saturate(&h->faults);
        return result;
    }
    return fpl_pipeline_handoff(p, &h->token, handoff, h);
}

/* How far the engine may read from a frame's raster, in place.
 *
 * DIRECT READ, operator decision 2026-09-30. The engine is told
 * align_kib(packed raster) and may read all of it. Measured on the camera:
 * the allocation is exactly the native request (0x15400 + align512(raster),
 * 0x31A200 at FHD 12-bit) and the told end lies 512 B past it. But every
 * kind-1 allocation is 1 KiB aligned (C037A990 -> C001CFD8(..., 0x400, 0))
 * and so is the raster's offset in it, so the told end can never pass the
 * next 1 KiB boundary after the allocation's end: those bytes are alignment
 * padding no 1 KiB-aligned block starts in, and the engine only reads them.
 * The pixels themselves are all inside the allocation. The earlier copy
 * fallback therefore never applied and is gone. */
static uint32_t readable(uint32_t capacity) {
    return ((capacity + 0x3ffu) & ~0x3ffu) - HEADER_RESERVE;
}

/* Build the lease and decide whether this frame can be held at all. */
static uint32_t eligible(struct fpl_frame_hold *h, uintptr_t frame,
                         struct fpl_frame_lease *lease) {
    uint32_t descriptor[FPL_FACTS_DESCRIPTOR_WORDS], handle, capacity, told, head;
    for (uint32_t n = 0; n < FPL_FACTS_DESCRIPTOR_WORDS; ++n)
        descriptor[n] = peek(frame + FRAME_DESCRIPTOR + 4u * n);
    handle = peek(frame + FRAME_HANDLE);
    capacity = peek(frame + FRAME_CAPACITY);
    told = told_source(h);
    if (!fpl_producer_facts_match(h->facts, descriptor)) {   /* planned for
                                                               another format */
        saturate(&h->refused_by[FPL_HOLD_R_DESCRIPTOR]);
        return 0;
    }
    head = frame_head(frame);
    if (peek(frame + FRAME_RESERVE) != HEADER_RESERVE || !head) {
        saturate(&h->refused_by[FPL_HOLD_R_RESERVE]);
        return 0;
    }
    if (h->require_head && head != h->require_head) {
        /* not the template that holds this take's IFD: it stays RAW */
        saturate(&h->refused_by[FPL_HOLD_R_HEADER]);
        return 0;
    }
    if (!handle || (handle & 0x3ffu) || !told) {
        saturate(&h->refused_by[FPL_HOLD_R_HANDLE]);
        return 0;
    }
    /* Every pixel inside the frame's own allocation, and the rounded length
     * inside its 1 KiB-aligned span: see readable(). */
    if (capacity < HEADER_RESERVE || capacity - HEADER_RESERVE < h->facts->seen.raster) {
        saturate(&h->refused_by[FPL_HOLD_R_RASTER]);  /* not a frame we know */
        return 0;
    }
    if (readable(capacity) < told) {
        saturate(&h->refused_by[FPL_HOLD_R_SHORT]);
        return 0;
    }
    if (told > h->workspace.output_capacity && !swap_allowed(h, frame)) {
        saturate(&h->refused_by[FPL_HOLD_R_OUTPUT]);
        return 0;
    }
    if (free_slot(h) < 0) {                  /* no slot, no promise, no hold */
        saturate(&h->refused_by[FPL_HOLD_R_SLOT]);
        return 0;
    }
    lease->buffer = handle + HEADER_RESERVE - head;
    lease->metadata = frame;
    lease->writer = frame;                  /* the file is made from the frame
                                               at dispatch, after release */
    lease->capacity = capacity - (HEADER_RESERVE - head);
    lease->stock_file_bytes = head + align512(h->facts->seen.raster);
    return 1;
}

/* Hold this frame if it may be held: on 1 the frame is marked pending, ours,
 * and `in` is its engine job; on 0 nothing is held and the CALLER gives the
 * frame to the original. */
static uint32_t admit(struct fpl_frame_hold *h, uintptr_t creator, uint32_t native_id,
                      uint32_t argument, struct fpl_codec_input *in) {
    struct fpl_frame_lease lease;
    uint32_t action = FPL_FRAME_NONE, result, ok;
    uintptr_t frame = native_frame(native_id);

    if (!frame || argument != 1 || peek(frame + FRAME_KIND) != KIND_CINEMADNG ||
        h->next_frame == UINT32_MAX) {
        saturate(&h->passed);
        return 0;
    }
    for (uint32_t n = 0; n < sizeof(lease); ++n) ((volatile unsigned char *)&lease)[n] = 0;
    ok = eligible(h, frame, &lease);
    lease.token.session = h->pipeline->session;
    lease.token.take = h->pipeline->take;
    lease.token.frame = ++h->next_frame;
    result = fpl_pipeline_arrive(h->pipeline, &lease, ok ? 1u : 0u, 1, &action);
    h->last_result = result;
    if (result != FPL_OK || action != FPL_FRAME_SELECTED) {
        if (result == FPL_NOT_READY) saturate(&h->not_eligible);
        saturate(&h->passed);
        return 0;
    }

    /* ---- held: exactly C037DD50's prefix, then the engine ---------------- */
    poke(frame + FRAME_STATE, STATE_PENDING);
    h->head = frame_head(frame);         /* eligible() proved it non-zero */
    h->creator = creator;
    h->frame = frame;
    h->native_id = native_id;
    h->token = lease.token;
    in->width = h->facts->seen.width;
    in->height = h->facts->seen.height;
    in->format = h->facts->seen.format;
    in->source = lease.buffer + h->head;
    in->source_capacity = readable(peek(frame + FRAME_CAPACITY));
    h->swapping = swap_allowed(h, frame);
    if (!h->swapping && h->workspace.spare.handle) saturate(&h->swap_declined);
    in->destination = h->swapping ? h->workspace.spare.handle + HEADER_RESERVE
                                  : h->workspace.output;
    in->destination_capacity = h->swapping ? readable(h->workspace.spare.capacity)
                                           : h->workspace.output_capacity;
    in->table = h->workspace.table;
    in->table_capacity = h->workspace.table_capacity;
    in->tile_force = h->tile_force;
    in->pitch_any = h->pitch_test;
    return 1;
}

static void add_us(uint32_t *sum, uint32_t us) {
    if (*sum + us > *sum) *sum += us;                    /* stops at the top */
}

static uint32_t submit(struct fpl_frame_hold *h, const struct fpl_codec_input *in) {
    uint32_t begun = tick_us();
    uint32_t result = fpl_codec_job_submit(&h->job, in);
    fpl_pipeline_submitted(h->pipeline, &h->token, result);
    if (result == FPL_OK) {
        uint32_t limit = in->width * in->height / STALL_PIX_PER_US * STALL_TIMES;
        h->stall_limit_us = limit < STALL_MIN_US ? STALL_MIN_US : limit;
        h->job_start_us = tick_us();
        h->last_poll_us = h->job_start_us;
        add_us(&h->submit_sum_us, h->job_start_us - begun);
        if (h->last_start_us) {
            add_us(&h->cycle_sum_us, begun - h->last_start_us);
            saturate(&h->cycle_count);
        }
        h->last_start_us = begun;
    }
    return result;
}

/* codec_job refuses only BEFORE the engine starts, or closes what it opened,
 * so nothing reads the frame: give it back whole, then record that ownership
 * is resolved. */
static void unstarted(struct fpl_frame_hold *h) {
    native_enqueue(h->creator, h->native_id, 1);
    h->frame = 0;
    h->swapping = 0;
    fpl_pipeline_reap(h->pipeline, &h->token, h->job.phase == FPL_CODEC_IDLE ? 1u : 0u, 1);
    saturate(&h->passed);
}

uint32_t fpl_hold_arrive(struct fpl_frame_hold *h, uintptr_t creator,
                         uint32_t native_id, uint32_t argument) {
    struct fpl_codec_input in;

    if (!hold_valid(h)) return native_enqueue(creator, native_id, argument);
    saturate(&h->arrivals);
    /* First, the frame we already hold: finish it into ITS OWN buffer and
     * queue it, so this arrival can have the engine. */
    service(h, 0);
    if (!admit(h, creator, native_id, argument, &in))
        return native_enqueue(creator, native_id, argument);
    if (submit(h, &in) != FPL_OK) {
        unstarted(h);
        return 1;
    }
    saturate(&h->held);
    saturate(&h->direct);
    return 1;
}

/* ---- lanes ---------------------------------------------------------------
 * Who moves a lane, and only that side:
 *   arrival   IDLE -> HELD          (fpl_hold_take)
 *   arrival   FINISHED -> COLLECTING -> IDLE   (fpl_hold_collect, claimed
 *   or stop                         with IRQs off; FAULT if unknown)
 *   task      HELD -> RUNNING       (fpl_hold_kick, claimed with IRQs off)
 *             RUNNING -> FINISHED   (fpl_hold_check)
 *   arrival   HELD -> COLLECTING -> IDLE/FAULT  (fpl_hold_abandon, claimed
 *   or stop                                     with IRQs off)
 * The frame, the pipeline and the commit ring are touched by the arrival
 * side only, except the pipeline's `submitted` mark, made by the task while
 * the lane is its own. */
uint32_t fpl_hold_take(struct fpl_frame_hold *h, uintptr_t creator,
                       uint32_t native_id, uint32_t argument) {
    if (!hold_valid(h) || h->lane != FPL_LANE_IDLE) return 0;
    saturate(&h->arrivals);
    if (!admit(h, creator, native_id, argument, &h->lane_in)) return 0;
    h->lane_failed = 0;
    barrier();
    h->lane = FPL_LANE_HELD;
    barrier();
    return 1;
}

uint32_t fpl_hold_kick(struct fpl_frame_hold *h) {
    uint32_t mask, result;
    if (!hold_valid(h)) return 0;
    mask = irq_off();
    if (h->lane != FPL_LANE_HELD) { irq_restore(mask); return 0; }
    h->lane = FPL_LANE_RUNNING;
    irq_restore(mask);
    barrier();
    result = submit(h, &h->lane_in);
    if (result != FPL_OK) {
        h->lane_failed = 1;
        h->lane_result = result;
        barrier();
        h->lane = FPL_LANE_FINISHED;
        barrier();
        return 0;
    }
    saturate(&h->held);
    saturate(&h->direct);
    return 1;
}

static uint32_t check(struct fpl_frame_hold *h, uint32_t ticks) {
    uint32_t result;
    if (!hold_valid(h) || h->lane != FPL_LANE_RUNNING) return 0;
    uint32_t took, polled = tick_us(), waited = ticks ? 4u : 0u;
    result = fpl_codec_job_wait(&h->job, ticks);
    took = tick_us() - h->job_start_us;
    if (result == FPL_BUSY) {
        h->last_poll_us = polled;
        /* 2026-10-02: one job in a long take never signalled; the lane waited
         * for it forever and every later frame went out uncompressed. Given
         * up on, the engine is closed (stopped) and the frame goes out as the
         * engine refusing it would: unchanged, and the lane is free again. */
        if (took < h->stall_limit_us) return waited;
        result = fpl_codec_job_abort(&h->job) == FPL_OK ? FPL_UNSUPPORTED : FPL_FAULT;
        saturate(&h->stalls);
    } else {
        h->job_last_us = took;
        if (took > h->job_max_us) h->job_max_us = took;
        saturate(&h->job_count);
        add_us(&h->job_sum_us, took);
        add_us(&h->finish_sum_us, tick_us() - polled);
        add_us(&h->gap_sum_us, polled - h->last_poll_us);
        add_us(&h->poll_sum, h->job.polls);
    }
    h->lane_result = result;
    barrier();
    h->lane = FPL_LANE_FINISHED;
    barrier();
    return 1u | waited;
}

uint32_t fpl_hold_check(struct fpl_frame_hold *h) { return check(h, 0); }

uint32_t fpl_hold_collect(struct fpl_frame_hold *h) {
    uint32_t result, mask;
    if (!hold_valid(h)) return FPL_BUSY;
    /* stop's wait and an arrival may both come for it: one claims it */
    mask = irq_off();
    if (h->lane != FPL_LANE_FINISHED) { irq_restore(mask); return FPL_BUSY; }
    h->lane = FPL_LANE_COLLECTING;
    irq_restore(mask);
    barrier();
    if (h->lane_failed) {
        unstarted(h);
        h->lane = FPL_LANE_IDLE;
        return FPL_OK;
    }
    if (h->abandoned) {
        /* stop already gave the frame back; the take stays unfinished */
        h->lane = FPL_LANE_FAULT;
        return FPL_FAULT;
    }
    result = service_done(h, h->pipeline, h->lane_result);
    barrier();
    h->lane = result == FPL_OK ? FPL_LANE_IDLE : FPL_LANE_FAULT;
    return result;
}

uint32_t fpl_hold_abandon(struct fpl_frame_hold *h) {
    uint32_t mask, result;
    if (!hold_valid(h)) return FPL_INVALID;
    mask = irq_off();
    if (h->lane == FPL_LANE_HELD) {
        h->lane = FPL_LANE_COLLECTING;
        irq_restore(mask);
        /* Never started: the same registered, pending kind-1 frame goes back
         * whole. C037DD50 can return 1 WITHOUT inserting a frame whose first
         * byte is zero; require that native queueable flag before the call.
         * With it, return 1 means FIFO insertion or successful message send,
         * NOT completed media I/O. Refusal/unknown ownership is not retried. */
        if (!h->frame || native_frame(h->native_id) != h->frame ||
            !(peek(h->frame) & 0xffu) ||
            peek(h->frame + FRAME_KIND) != KIND_CINEMADNG ||
            peek(h->frame + FRAME_STATE) != STATE_PENDING ||
            native_enqueue(h->creator, h->native_id, 1) != 1) {
            fpl_pipeline_stop(h->pipeline);
            h->lane = FPL_LANE_FAULT;
            saturate(&h->faults);
            return FPL_FAULT;
        }
        h->frame = 0;
        h->swapping = 0;
        result = fpl_pipeline_cancel_held(h->pipeline, &h->token, 1);
        barrier();
        h->lane = result == FPL_OK ? FPL_LANE_IDLE : FPL_LANE_FAULT;
        if (result != FPL_OK) { saturate(&h->faults); return result; }
        saturate(&h->passed);
        return FPL_OK;
    }
    irq_restore(mask);
    if (h->lane == FPL_LANE_RUNNING && h->frame && !h->abandoned) {
        /* The engine never finished. Its SOURCE was only ever read, so the
         * frame goes to the card as it was and native stop can complete;
         * the output stays the job's and the take never finishes. */
        native_enqueue(h->creator, h->native_id, 1);
        h->abandoned = 1;
        saturate(&h->faults);
        return FPL_FAULT;
    }
    return h->lane == FPL_LANE_IDLE ? FPL_OK : FPL_FAULT;
}

uint32_t fpl_hold_stop(struct fpl_frame_hold *h) {
    uint32_t result;
    if (!hold_valid(h)) return FPL_INVALID;
    fpl_pipeline_stop(h->pipeline);
    if (h->pipeline->phase != FPL_SLOT_ENCODING) return FPL_OK;
    result = service(h, 1);
    if (result == FPL_BUSY && h->frame) {
        /* The engine never finished. Its SOURCE was only ever read, so the
         * frame goes to the card as it was and native stop can complete. The
         * OUTPUT workspace stays with the job: the pipeline remains ENCODING
         * and the take cannot finish, so that memory is never released while
         * the engine might still write it. */
        native_enqueue(h->creator, h->native_id, 1);
        h->frame = 0;
        saturate(&h->faults);
        return FPL_FAULT;
    }
    if (result == FPL_OK) saturate(&h->drained);
    return result;
}

/* ---- two lanes, one engine ------------------------------------------- */
static uint32_t lane_busy(const struct fpl_frame_hold *h) {
    return hold_valid(h) && (h->lane == FPL_LANE_HELD || h->lane == FPL_LANE_RUNNING ||
                             h->lane == FPL_LANE_FINISHED ||
                             h->lane == FPL_LANE_COLLECTING);
}
/* FAILED may still own the shared hardware, even after its lane becomes
 * FINISHED/FAULT. A software completion is not evidence the engine is idle. */
static uint32_t engine_failed(struct fpl_frame_hold *const lane[2]) {
    for (uint32_t n = 0; n < 2; ++n)
        if (hold_valid(lane[n]) && lane[n]->job.phase == FPL_CODEC_FAILED) return 1;
    return 0;
}
/* The lanes in the order their frames arrived. */
static void by_age(struct fpl_frame_hold *const lane[2], struct fpl_frame_hold **first,
                   struct fpl_frame_hold **second) {
    uint32_t swap = hold_valid(lane[1]) && lane[1]->order < lane[0]->order;
    *first = lane[swap];
    *second = hold_valid(lane[!swap]) ? lane[!swap] : 0;
}

uint32_t fpl_lanes_arrive(struct fpl_frame_hold *const lane[2], uintptr_t creator,
                          uint32_t native_id, uint32_t argument) {
    struct fpl_frame_hold *first, *second;
    uint32_t order;
#ifdef FPL_DIAG_HOOK_TIME
    struct fpl_frame_hold *h = lane ? lane[0] : 0;       /* diag_enqueue's account */
#endif
    if (!lane || !hold_valid(lane[0])) return native_enqueue(creator, native_id, argument);
    by_age(lane, &first, &second);
    /* finished frames go back first, oldest first */
#if defined(FPL_DIAG_HOOK_TIME) && !defined(FPL_FRAME_HOLD_HOST_TEST)
    uint32_t diag_t = tick_us(), diag_c = (first->lane == FPL_LANE_FINISHED) +
                      (second && second->lane == FPL_LANE_FINISHED);
#endif
    fpl_hold_collect(first);
    if (second) fpl_hold_collect(second);
#if defined(FPL_DIAG_HOOK_TIME) && !defined(FPL_FRAME_HOLD_HOST_TEST)
    lane[0]->diag_collect_us += tick_us() - diag_t;
    lane[0]->diag_collect_n += diag_c;
#endif
    if (engine_failed(lane)) {
        /* Native transfers stay on the arrival/stop side, not the worker.
         * Waiting frames have not touched the failed engine and go RAW. */
        if (first->lane == FPL_LANE_HELD) fpl_hold_abandon(first);
        if (second && second->lane == FPL_LANE_HELD) fpl_hold_abandon(second);
        return native_enqueue(creator, native_id, argument);
    }
    order = (second && second->order > first->order ? second->order : first->order) + 1u;
    for (uint32_t n = 0; n < 2; ++n) {
        struct fpl_frame_hold *l = lane[n];
        if (!hold_valid(l) || l->lane != FPL_LANE_IDLE) continue;
        l->order = order;
#if defined(FPL_DIAG_HOOK_TIME) && !defined(FPL_FRAME_HOLD_HOST_TEST)
        uint32_t take_t = tick_us(), took_it = fpl_hold_take(l, creator, native_id, argument);
        lane[0]->diag_take_us += tick_us() - take_t;
        lane[0]->diag_take_n++;
        if (took_it) return 1;
#else
        if (fpl_hold_take(l, creator, native_id, argument)) return 1;
#endif
        break;                       /* not a frame to hold: the other lane
                                        would say the same */
    }
    for (uint32_t n = 0; n < 2; ++n)
        if (hold_valid(lane[n]) && lane[n]->lane != FPL_LANE_IDLE) {
            saturate(&lane[0]->lanes_full);
            break;
        }
    return native_enqueue(creator, native_id, argument);
}

uint32_t fpl_lanes_task(struct fpl_frame_hold *const lane[2]) {
    return fpl_lanes_task_wait(lane, 0);
}

uint32_t fpl_lanes_task_wait(struct fpl_frame_hold *const lane[2], uint32_t ticks) {
    struct fpl_frame_hold *first, *second, *next = 0;
    uint32_t moved = 0;
    if (!lane || !hold_valid(lane[0])) return 0;
    by_age(lane, &first, &second);
    /* one engine: at most one lane runs, and only it is waited on (bit 2) */
    moved |= check(first, ticks);
    if (second) moved |= check(second, ticks);
    if (engine_failed(lane)) return moved;  /* unknown hardware is not idle */
    if (first->lane == FPL_LANE_RUNNING || (second && second->lane == FPL_LANE_RUNNING))
        return moved;                /* one engine */
    if (first->lane == FPL_LANE_HELD) next = first;
    else if (second && second->lane == FPL_LANE_HELD) next = second;
    if (!next) return moved;
    if (!fpl_hold_kick(next)) return moved;
    return moved | 2u;
}

uint32_t fpl_lanes_stop(struct fpl_frame_hold *const lane[2]) {
    struct fpl_frame_hold *first, *second;
    uint32_t result = FPL_OK;
    if (!lane || !hold_valid(lane[0])) return FPL_INVALID;
    for (uint32_t n = 0; n < 2; ++n)
        if (hold_valid(lane[n])) fpl_pipeline_stop(lane[n]->pipeline);
    by_age(lane, &first, &second);
    /* The task starts what is held and finishes what runs; this side gives
     * the frames back. Bounded like the firmware's own wait. */
    for (uint32_t n = 0; n < STOP_POLLS; ++n) {
        if (fpl_hold_collect(first) == FPL_OK) saturate(&first->drained);
        if (second && fpl_hold_collect(second) == FPL_OK) saturate(&second->drained);
        if (engine_failed(lane)) {
            if (first->lane == FPL_LANE_HELD) fpl_hold_abandon(first);
            if (second && second->lane == FPL_LANE_HELD) fpl_hold_abandon(second);
        }
        if (!lane_busy(first) && !lane_busy(second)) break;
        sleep_ms(1);
    }
    if (fpl_hold_abandon(first) != FPL_OK) result = FPL_FAULT;
    if (second && fpl_hold_abandon(second) != FPL_OK) result = FPL_FAULT;
    return result;
}

const struct fpl_hold_commit *fpl_hold_peek(struct fpl_frame_hold *h, uintptr_t file) {
    if (!hold_valid(h) || !file) return 0;
    for (uint32_t n = 0; n < FPL_HOLD_COMMITS; ++n)
        if (h->ring[n].file == file) { barrier(); return &h->ring[n]; }
    return 0;
}
void fpl_hold_consumed(struct fpl_frame_hold *h, const struct fpl_hold_commit *c) {
    if (!hold_valid(h) || c < h->ring || c >= h->ring + FPL_HOLD_COMMITS) return;
    barrier();
    ((struct fpl_hold_commit *)c)->file = 0;     /* free */
    barrier();
}
