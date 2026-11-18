#ifndef FPLOSSLESS_PLAY_DECODE_H
#define FPLOSSLESS_PLAY_DECODE_H
#include <stdint.h>
#include "../control.h"

/* In-camera playback of a compressed clip, by the engine's decode mode.
 *
 * The CinemaDNG player (CinemaDngPlay), as read 2026-10-01:
 *   clip   C05BDD68 takes the FIRST frame file's size into player+0xA0
 *          (C03665F8) -- the size of every frame buffer it will make;
 *   pool   C05C2D10 makes buffers of (size + 0x1FFF) & ~0xFFF from the RAW
 *          pool (class 10) until the pool is empty;
 *   frame  C05C0C38 reads each frame file whole into one (f_read C05C0EA0:
 *          slot+0x14 buffer, +0x18 capacity, +0x1C bytes read), and never
 *          looks at Compression or the strip offsets;
 *   close  C05C2E90 frees the pool.
 * Measured: the buffers are not 1 KiB aligned and lie above 0x80000000.
 *
 * So, three places:
 *   fpl_play_clip   (C05BDDAC, the store of that size) reads the first
 *                   frame's header; for a clip of ours it makes the size the
 *                   stock frame's and notes the scratch the decoder needs;
 *   fpl_play_pool   (C05C2D10, the pool made) takes that scratch from the RAW
 *                   pool BEFORE the player empties it. Not at clip open: the
 *                   player frees its old pool between the two when the size
 *                   changed (2026-10-02, a 48p clip: the scratch taken at
 *                   clip open was freed with that pool, every frame refused);
 *   fpl_play_frame  (C05C0EA4, after the read) decodes a frame of ours back
 *                   into the stock layout and puts the root back on IFD0,
 *                   which still describes the uncompressed strip;
 *   fpl_play_end    (C05C2E90, the pool freed; also any REC start) gives the
 *                   scratch back.
 *
 * The engine needs 1 KiB aligned buffers and writes whole tiles, and the
 * player's buffer is neither aligned nor sized for the padding. Each tile row
 * is therefore decoded into the scratch and its rows copied in by the
 * firmware's DMA C00FBB90 -- BOTTOM UP: the stream lies at the start of the
 * strip, and as long as every tile row up to r compresses into no more than
 * r raw tile rows (checked first, for every row), the rows written never
 * reach a stream not yet read. One tile row's stream and output fit the
 * scratch. The engine's outer routine C062FAD0 cannot do a frame whose height
 * is not a whole number of tiles (tools/hwdecode); its steps are done here
 * for one tile row at a time.
 *
 * 2026-11-18, the whole frame in ONE engine job with no bulk copy (the row
 * path above took 58.6 ms for a 3024x2010 frame the engine alone decodes in
 * 22.7 ms -- tools/hwdecode -- and 8.5 ms for a 1 MiB frame):
 *   aligned  when the player has made its pool (C05C2D10's return), every
 *            buffer's address is moved up to the next 1 KiB (4..0x400 B; the
 *            address the allocator gave is kept in the word below) and its
 *            capacity cut by as much; fpl_play_end puts both back before the
 *            player frees them (C001D2B8 frees by address);
 *   spare    one more buffer of the same size from the same allocator, taken
 *            before the player empties the pool, aligned the same way;
 *   a frame  its stream is read by the engine where the player's read put it
 *            (the strip offset is 1 KiB aligned in the file), decoded with the
 *            tile-padded height into the spare at the same strip offset; the
 *            header is copied in front of it, and the slot takes the spare
 *            while the frame's old buffer becomes the spare (the player
 *            reloads slot+0x14 after the site, C05C0F00).
 *   ahead    while the engine decodes frame N, the next frame FILE is read
 *            into a second spare (the player's path with its six digits at
 *            +0x23 one higher, C06A0B08); when the player then comes to read
 *            exactly that path (C05C0EA0, its f_read call), the slot takes
 *            that buffer and the read is skipped. So a frame costs the longer
 *            of its read and its decode, not their sum, and the engine is
 *            never idle while a file is read. Any other path: read as stock.
 * A frame the fast way cannot take (no spare, a strip not 1 KiB aligned, a
 * buffer too small for the padded height) goes the row way. */

enum fpl_play_refusal {
    FPL_PLAY_R_SLOT = 0,      /* no buffer */
    FPL_PLAY_R_TIFF = 1,      /* not a little-endian TIFF, or too short */
    FPL_PLAY_R_ROOT = 2,      /* the root IFD is not readable in the bytes read */
    FPL_PLAY_R_FORMAT = 3,    /* not Compression 7 / tiled / a depth we know */
    FPL_PLAY_R_TILES = 4,     /* tile table not contiguous or past the data */
    FPL_PLAY_R_IFD0 = 5,      /* IFD0 at 8 is not this frame's stock strip */
    FPL_PLAY_R_ROOM = 6,      /* the buffer cannot hold the pixels */
    FPL_PLAY_R_ORDER = 7,     /* a tile row compressed worse than raw: bottom up unsafe */
    FPL_PLAY_R_SCRATCH = 8,   /* no scratch, or too small for a tile row */
    FPL_PLAY_R_ENGINE = 9,    /* the engine refused, failed or timed out */
    FPL_PLAY_R_COPY = 10,     /* a DMA copy failed */
    FPL_PLAY_R_BUSY = 11      /* a take is live: the engine is the recorder's */
};
#define FPL_PLAY_REASONS 12u
#define FPL_PLAY_STOCK   0xfeu        /* returned: root at 8, left alone */
#define FPL_PLAY_DECODED 0xffu        /* returned: decoded, root back at 8 */
#define FPL_PLAY_HEADER  1024u        /* first-frame bytes read at clip open */
#define FPL_PLAY_PATH    96u          /* a frame file's path, with its NUL */
#define FPL_PLAY_DIGITS  0x23u        /* where C06A0B08 puts the six-digit frame number */

struct fpl_play {
    uint32_t seen, stock, decoded;           /* frames: all, root at 8, done */
    uint32_t refused_by[FPL_PLAY_REASONS];
    uint32_t last_us, max_us;                /* a decode, start to the root put back */
    uint32_t last_buf, last_cap, last_got;   /* the last slot seen */
    /* clip open */
    uint32_t clips, clips_ours, clip_size_was, clip_size_set, clip_failed;
    uint32_t scratch_bytes, scratch_failed, scratch_freed;
    uint32_t scratch_want;                   /* the clip's need; 0: not one we decode */
    uint32_t clips_first_stock;              /* decodable clips opening on a stock frame */
    uintptr_t scratch;
    uint32_t obj[4];                         /* the scratch allocation record */
    /* the whole frame in one job */
    uintptr_t pool;                          /* the player's pool object; 0: none of ours */
    uintptr_t pool_return;                   /* C05C2D10's caller, while it runs */
    uintptr_t spare;                         /* aligned; 0: the row way only */
    uint32_t spare_cap, spare_failed, spare_lost;
    uint32_t slots, slots_base;              /* buffers aligned at pool make */
    uint32_t restored, not_ours;             /* at the end: put back, left alone */
    uint32_t fast, rows;                     /* frames decoded: one job, row by row */
    uint32_t fast_no_spare, fast_no_align, fast_no_room;
    uint32_t last_engine_us, last_head_us;   /* a fast frame: the job, the header copy */
    /* this clip, frames decoded the fast way: the engine's time, our hook's,
     * and the time between our hooks (the player's read and the rest) */
    uint32_t sum_engine_us, sum_hook_us, sum_gap_us, timed, hook_end_us;
    uint32_t sums_stale, gaps, last_gap_us, min_gap_us, max_gap_us;
    /* the next file, read while the engine runs */
    uintptr_t ahead;                         /* aligned; 0: no reading ahead */
    uint32_t ahead_cap, ahead_got;           /* got: bytes of ahead_path in it; 0: none */
    uint32_t ahead_read, ahead_used, ahead_missed, ahead_none, ahead_failed;
    uint32_t last_read_us, last_wait_us;     /* a fast frame: the read ahead, the engine after it */
    uint32_t sum_read_us, sum_wait_us;
    char ahead_path[FPL_PLAY_PATH];
    uint32_t file[0x400 / 4];                /* the native file object */
    uint32_t header[FPL_PLAY_HEADER / 4];
};

#if defined(FPL_PLAY_DECODE_HOST_TEST)
struct fpl_play_natives {
    uint32_t (*read)(uintptr_t);
    void (*write)(uintptr_t, uint32_t);
    uintptr_t (*alloc)(uint32_t *obj, uint32_t bytes);     /* 1 KiB aligned */
    void (*release)(uint32_t *obj);
    uintptr_t (*buffer_get)(uint32_t bytes);                /* as the player's: any address */
    void (*buffer_put)(uintptr_t address);
    uint32_t (*dma)(uintptr_t to, uintptr_t from, uint32_t bytes);   /* 0 = done */
    uint32_t (*init)(volatile uint32_t *);                  /* 1 = latched */
    uint32_t (*flag)(void);
    uint32_t (*clr)(uint32_t, uint32_t);
    uint32_t (*open)(void);
    uint32_t (*submit)(volatile uint32_t *);
    uint32_t (*start)(void);
    uint32_t (*wait)(uint32_t flag, uint32_t *pattern);    /* 0 = set */
    uint32_t (*close)(void);
    uint32_t (*now)(void);
    void (*sync)(void);                                     /* D-cache clean */
    /* the first frame of a clip: 1 = read; *got bytes into buf */
    uint32_t (*first_frame)(uintptr_t desc, uint32_t *file, uint8_t *buf,
                            uint32_t bytes, uint32_t *got);
    /* a file read whole: 1 = read; *got bytes (at most `bytes`) into buf */
    uint32_t (*file_read)(uint32_t volume, const char *path, uint32_t *file, uintptr_t buf,
                          uint32_t bytes, uint32_t *got);
};
extern const struct fpl_play_natives fpl_play_test_natives;
#endif

/* C05BDDAC: player+0xA0 is about to become `size`, the first frame file's
 * size, of the clip `desc` names. Returns the size to store. */
uint32_t fpl_play_clip(struct fpl_play *, uintptr_t desc, uint32_t size, uint32_t busy);
/* C05C0EA4. `busy` nonzero: a take owns the engine, leave the frame.
 * Returns FPL_PLAY_STOCK, FPL_PLAY_DECODED, or the refusal (frame untouched,
 * except after FPL_PLAY_R_ENGINE / a late FPL_PLAY_R_COPY, when some tile rows
 * are already written and the root still says compressed). */
uint32_t fpl_play_frame(struct fpl_play *, uintptr_t slot, uint32_t busy);
/* The same, with the player's reader object (r4 at the site: the path being
 * read at +0x80, its volume at +0xB4), so the next file can be read ahead. */
uint32_t fpl_play_frame_at(struct fpl_play *, uintptr_t slot, uintptr_t reader, uint32_t busy);
/* C05C0EA0, the player about to f_read the file `reader` names into `slot`.
 * 1: the slot already holds that file (read ahead) -- the read is skipped. */
uint32_t fpl_play_read(struct fpl_play *, uintptr_t slot, uintptr_t reader, uint32_t busy);
/* C05C2D10's entry, the player about to make its buffer pool `pool` of
 * buffers for `size` B files: the scratch and the spare the open clip needs,
 * taken first. */
void fpl_play_pool(struct fpl_play *, uintptr_t pool, uint32_t size);
/* C05C2D10's return: the pool is made; its buffers aligned. */
void fpl_play_made(struct fpl_play *);
/* C05C2E90, and every REC start: the buffers' own addresses back in their
 * slots, the spare and the scratch back to the pool. */
void fpl_play_end(struct fpl_play *);
#endif
