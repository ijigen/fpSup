/* ISPL fork of projects/imx410-lab/sup/ix_wr.h (IMXL, sha256 deed1891..., see
 * UPSTREAM.sha256), 2026-10-23.  Changes, all in ix_cap (layout version 2):
 *   - capture keeps only some blocks: the first keep_first, then one per
 *     every_us; the rest are dropped (n_skip).  Bounded by the lent chunks.
 *   - a 16-byte line per block, kept or not, in a host-lent log (ix_logline)
 *   - ctl: a low-priority task starts and stops the take itself (key MOVON /
 *     MOVOFF through the stock shell executor), so the host stays silent
 *     from the arm until well after the stop.  Design: isp-lab RESEARCH_PLAN §6.
 *
 * IMXL fork of rec-core/writer/wr.h (ULWR, sha256 518de2ce...), 2026-10-20.
 * Only change: the sink (ix_cap) -- the writer either writes the block to the
 * card as ULWR does (IX_SD), copies it into DRAM the host lent us (IX_CAPTURE),
 * or drops it (IX_DISCARD).  Design: projects/imx410-lab/DESIGN.md §2.C.
 *
 * wr -- the native adapter between stock's file layer and our writer task.
 * Design: research/storage/notes/WRITER_LOCK_SCOPE.md §5-§7 (the six vol
 * pointers, the C063F140 hook, the late cookie, the stop drain).
 *
 * Every firmware call goes through wr_fw, so the same code runs on the host
 * against fakes (test_wr.py) and on the camera with the real addresses
 * (wr_card.S fills the table).  Every entry takes the wr_t: the card's
 * veneers load it, the firmware never sees it.
 *
 *   wr_installed  C063F220 returned 1 for `vol`: take the vol's arena pointers
 *   wr_send       C063F140 entry.  0 = handled; 1 = not ours, run stock
 *   wr_cb_*       what vol+0x4834..0x4848 point at while installed
 *   wr_task       the writer task's body (never returns)
 *   wr_take_start C063F220 entered (every aggregated take, ours or not)
 *   wr_late_frame C03A5348 after its write C069ADE0 returned: 1 = this frame
 *                 was written after the stop turned aggregation off, so stock
 *                 must complete it itself (the "mgr+0xD == 0" branch)
 */
#ifndef REC_CORE_WR_H
#define REC_CORE_WR_H
#include <stdint.h>
#include "bq.h"

#define WR_MAGIC      0x31525757u        /* "WWR1" */

/* vol fields (fp 5.02, WRITER_LOCK_SCOPE §1, FORMAT_CLUSTER_SIZE) */
#define V_DEV         0x0000u            /* device handle passed to C01EB790   */
#define V_HEAP_LBA    0x1458u            /* cluster heap, sectors (64-bit)     */
#define V_SECTOR      0x1460u            /* bytes per sector                   */
#define V_SPC         0x146Cu            /* sectors per cluster                */
#define V_THRESH      0x4828u
#define V_CB          0x4834u            /* cookie callback                    */
#define V_ACQ         0x4838u
#define V_ADD         0x483Cu
#define V_CKPT        0x4840u
#define V_RB          0x4844u
#define V_REL         0x4848u
#define V_ARENA       0x484Cu
#define V_NCOOKIE     0x4850u
#define V_COOKIES     0x4854u
#define V_CL          0x4A54u
#define V_BYTES       0x4A58u

#define WR_LR_STOP    0xC063F34Du        /* C063F310's bl C063F140 returns here */

/* C03A5348's frame (SRecFile): mgr = fp, node = r4 */
#define M_AGGREGATE   0x000Du            /* byte: completion comes from the vol */
#define N_STATE       0x1104u            /* 0xC handed to the FS, 0xD completed */
#define N_HANDED      0xCu

/* event flag bits */
#define WR_F_WORK     1u                 /* a block was sealed                  */
#define WR_F_FREE     2u                 /* a block became free                 */
#define WR_F_IDLE     4u                 /* nothing queued/writing/completing   */
#define TWF_ORW_BITCLR 0x21u

typedef struct {
    /* stock driver arena (the originals saved from the vol) */
    uint32_t (*drv_acquire)(void);
    int      (*drv_add)(uint32_t addr, uint32_t len);
    void     (*drv_release)(void);
    void     (*stock_cb)(uint32_t frame, uint32_t status);     /* C03A55D0 */
    /* device write C01EB790(dev, lba_lo, lba_hi, sectors, buf): 1 = ok */
    int      (*dev_write)(uint32_t dev, uint32_t lo, uint32_t hi, uint32_t n, uint32_t buf);
    uint32_t (*irq_off)(void);                                  /* C000EC14 */
    void     (*irq_restore)(uint32_t);                          /* C000EC24 */
    int      (*flg_set)(int id, uint32_t ptn);
    int      (*flg_wait)(int id, uint32_t ptn, uint32_t mode, uint32_t *out, int tmo_ms);
    uint32_t (*shell_exec)(uint32_t ctx, char *line);           /* C03D9C20: strtoks it */
    uint32_t shell_ctx;                                         /* C3756904 */
    uint32_t recstate;                                          /* C3757F30 */
    void     (*dly)(uint32_t ms);
    uint32_t (*tick_us)(void);                                  /* C002B6E0 */
    int      (*start_xfer)(uint32_t phys);                      /* C01E6B80: 0 = started, -2 = deaf */
    void     (*end_xfer)(uint32_t ctx);                         /* C01E6D48 */
} wr_fw;

/* ---- the sink.  The host fills mode/nchunk/chunk while the camera is not
 * recording (cursor and counters zeroed first, mode last); the writer reads
 * mode once per block.  Capture memory is a list of chunks from the firmware
 * allocator (uncached alias), filled front to back with records:
 *
 *   ix_rec (32 B), then `bytes` bytes = what ULWR would have written at
 *   cluster `cl` (whole DNG files, cluster padded), then pad to 4.
 *
 * A record that does not fit whole is not stored (n_full++); its frames are
 * still completed with status 0, so the take goes on. */
enum { IX_SD = 0, IX_CAPTURE = 1, IX_DISCARD = 2 };
#define IX_MAX_CHUNK  32u
#define IX_REC_MAGIC  0x31525849u        /* "IXR1" */
#define IX_CAP_MAGIC  0x4C505349u        /* "ISPL": the host finds the sink by it */
#define IX_CAP_VERSION 4u

/* ctl: the host writes start_ms/rec_ms, then ctl = IX_CTL_ARMED (last).  The
 * control task stamps t_arm and, start_ms later, runs the firmware's own
 * record script (FUN_c0405ba0): recstate ena/init, key MOVON, recstate
 * movrecstwai; rec_ms after that key MOVON + recstate movsavewai (up to three
 * times), recstate disa.  Writing 0 before the start cancels. */
enum { IX_CTL_IDLE = 0, IX_CTL_ARMED = 1, IX_CTL_REC = 2, IX_CTL_DONE = 3,
       IX_CTL_FAIL_START = 4,            /* no sign the take started: no second press */
       IX_CTL_FAIL_STOP = 5 };           /* three stop presses, no "saved"            */

/* LV sampler (layout 3): the control task reads the LCD output descriptor
 * (0xC30255B4) and the display DMA channel's slot register, and hands the slot
 * written before the current one to the push engine (FPP1, PUSH_PROTOCOL.md)
 * as source 1, mode 0 (skip if busy).  The engine is another sup: the host
 * writes its entry into lv_push (Thumb: +1); 0 = sampler off.  Design:
 * notes/PUSH_CALLERS.md §1. */
#define IX_LV_DESC     0xC30255B4u       /* LCD descriptor: [3] w [4] h [8] n [9..] handles */
#define IX_LV_CHSEL    0xC31DF8D8u       /* channel = this + 2 (>= 7: 8), FUN_c01d7638 */
#define IX_LV_ENGINE   1u                /* lv_push = 1: the built-in engine (ix_push.c) */
#define IX_LV_MAX_N    8u
#define IX_LV_MAX_BYTES ((16u << 20) - 1024u)   /* one TRB */
enum { IX_PUSH_SENT = 0, IX_PUSH_SKIPPED = 1 };
typedef struct { uint32_t addr, len; } ix_seg;
typedef struct {
    uint32_t mode, source, frame_no, w, h, fmt, stride, flags, aux0, aux1, nseg;
    ix_seg   seg[4];
} ix_push_req;                           /* what the engine is handed (header fields) */

/* CDNG after the stop (notes/PUSH_CALLERS.md §3, validation/20261025-rawpool-01):
 * the RAW class arena keeps the last frames of a take after it is freed. */
#define IX_CD_CLASS_TBL 0xC30739DCu      /* [ + 4*class] = the class object (FUN_c001cf78) */
#define IX_CD_RAW_CLASS 10u
#define IX_CD_BLOCK     0xDEADBEEFu      /* chain block header (FUN_c00104a8) */
#define IX_CD_STEP      0x400u           /* DNG starts seen 10-25: all 0x400-aligned */
#define IX_CD_DNG_MAX   (64u << 20)
enum { IX_CD_IDLE = 0, IX_CD_DONE = 1, IX_CD_NO_ARENA = 2, IX_CD_BUSY = 3 };

/* one per block the writer took, kept or not */
typedef struct { uint32_t seq, t_us, ncookie, bytes; } ix_logline;

typedef struct { uint32_t addr, len; } ix_chunk;

typedef struct {
    uint32_t magic, seq, cl, bytes;      /* bytes: data after this header      */
    uint32_t ncookie, t_us, copy_us, nseg;
} ix_rec;

typedef struct {
    uint32_t magic;                      /* IX_CAP_MAGIC                        */
    uint32_t version;                    /* layout version, IX_CAP_VERSION      */
    /* host-written */
    uint32_t mode;
    uint32_t nchunk;
    ix_chunk chunk[IX_MAX_CHUNK];
    uint32_t keep_first;                 /* capture: always keep this many blocks */
    uint32_t every_us;                   /* then one per this interval (0: none)  */
    uint32_t log_addr, log_max;          /* lent log: log_max ix_logline (0: off) */
    uint32_t ctl, start_ms, rec_ms;      /* see IX_CTL_*                         */
    /* camera-written */
    uint32_t ci, coff;                   /* cursor: chunk index, offset in it   */
    uint32_t used;                       /* bytes stored, records included      */
    uint32_t n_rec, n_full, n_discard, n_sd;
    uint32_t t_first, t_last;            /* tick_us of the first/last record    */
    uint32_t copy_us, copy_max_us;       /* summed and worst per-block copy     */
    uint32_t n_skip;                     /* capture blocks dropped by the policy */
    uint32_t log_n;                      /* log lines written                    */
    uint32_t t_arm, t_rec, t_stop;       /* tick_us: ctl armed seen, REC pressed twice */
    uint32_t n_press;                    /* key presses issued                   */
    uint32_t ctl_line;                   /* last shell line started (IX_SH_*)    */
    uint32_t rs_started, rs_saved;       /* recstate +6 / +7 when checked        */
    uint32_t install_at_arm;             /* n_install when the arm was seen      */
    /* LV sampler: host-written */
    uint32_t lv_push;                    /* 1: built-in engine; else an entry, ix_push_req * -> IX_PUSH_* */
    uint32_t lv_every_us;                /* one push per this interval (0: off)  */
    uint32_t lv_lag;                     /* 1 = the last slot finished, 2 = one older (0: 1) */
    uint32_t lv_max;                     /* stop after this many sent (0: no cap) */
    /* LV sampler: camera-written */
    uint32_t lv_t_last;                  /* tick_us of the last attempt          */
    uint32_t lv_n_sent, lv_n_skip, lv_n_bad, lv_n_err;
    uint32_t lv_last_reg;                /* raw slot index read                  */
    uint32_t lv_last_addr;               /* the slot pushed                      */
    /* CDNG after the stop (layout 4, ix_cdng.c): host-written */
    uint32_t cd_go;                      /* 1: scan now (a manual take); the camera clears it */
    uint32_t cd_after_ms;                /* our own take: scan this long after t_stop (0: never) */
    uint32_t cd_max;                     /* push at most this many (0: all of the newest take) */
    /* camera-written */
    uint32_t cd_state;                   /* IX_CD_*                              */
    uint32_t cd_lo, cd_hi;               /* the RAW arena scanned (uncached)     */
    uint32_t cd_found, cd_newest_n;      /* DNG headers seen / of the newest take */
    uint32_t cd_sent, cd_skip;           /* pushes that went / did not            */
    uint32_t cd_us;                      /* the whole scan + push, microseconds   */
    uint8_t  cd_newest[20];              /* that take's DateTime, "YYYY:MM:DD HH:MM:SS" */
} ix_cap;

/* ---- the push engine (FPP1 over EP 0x83, notes/PUSH_PROTOCOL.md; ix_push.c).
 * The header and the TRB chain live here and are written through the uncached
 * alias, so the controller reads them with no cache maintenance.  TRB buffer
 * addresses are DMA = uncached CPU - 0x40000000 (the firmware's own convention). */
#define PX_CTX        3u                 /* EP 0x83 (memory push-endpoint-is-ep83) */
#define PX_PHYS       7u
#define PX_TRB_DMA    0xC31E3238u        /* [ctx]: TRB DMA address StartTransfer hands the controller */
#define PX_TRB_CPU    0xC31E3264u        /* [ctx]: the same TRB, CPU address (= DMA + 0x40000000) */
#define PX_DEAF       0xC31E38FCu        /* 1 after a PTP Cancel/Reset: StartTransfer -> -2 (handover F2) */
#define PX_MAX_TRB    64u
#define PX_MAX_SEG    4u
#define PX_TRB_MAX_LEN 0xFFFC00u         /* 16 MiB - 1 KiB */
#define PX_HDR        256u
#define PX_MAGIC      0x31505046u        /* "FPP1" */
#define PX_TRB_MID    0x15u              /* HWO | CHN | normal */
#define PX_TRB_LAST   0x813u             /* HWO | LST | normal | IOC (the firmware's) */
enum { PX_SENT = 0, PX_SKIPPED = 1, PX_ERR_BAD = 2, PX_ERR_TIMEOUT = 3, PX_ERR_START = 4 };

typedef struct { uint32_t lo, hi, size, ctrl; } px_trb;
typedef struct {
    uint8_t  hdr[PX_HDR];                /* 16-aligned: first in the struct          */
    px_trb   trb[PX_MAX_TRB];
    uint32_t armed;                      /* a transfer was started and not yet seen done */
    uint32_t last_trb;                   /* index of the armed chain's last TRB      */
    uint32_t saved_dma, saved_cpu;       /* ctx 3's table entries before we took them */
    uint32_t owns;                       /* 1 while the tables point at our chain    */
    uint32_t seq[8], n_skip[8];          /* per source                               */
    uint32_t n_sent, n_bad, n_timeout, n_start_err, n_deaf, last_rc;
    uint64_t bytes;
} ix_px_t;

/* Recognising the volume's driver by its saved acquire pointer. */
#define WR_SD_ACQ     0xC065F021u
#define WR_SSD_ACQ    0xC06702B9u
#define WR_SD_MAXDESC 0xC2F2E750u        /* bytes per ADMA descriptor           */

typedef struct {
    uint32_t magic;
    wr_fw    fw;
    int      flag;                       /* event flag id (> 0)                 */
    int      task_id;                    /* the writer task (wr_card.c)         */
    int      ctl_task_id;                /* the control task                    */
    uint32_t veneer[6];                  /* cb, acq, add, ckpt, rb, rel (ours)  */
    uint32_t block_bytes;                /* batch size; rounded up to a cluster */
    uint32_t maxdesc_at;                 /* where the SD descriptor size lives  */
    /* the take */
    uint32_t vol;                        /* 0 when not installed                */
    uint32_t wvol;                       /* the writer's: kept after a restore  */
    uint32_t saved[6];                   /* stock +0x4834..+0x4848              */
    uint32_t sector_shift;
    uint32_t cur;                        /* block being written (writer only)   */
    /* counters (host tools read them) */
    uint32_t n_install, n_refuse, n_send, n_stock_send, n_chunk, n_acq_retry, n_dev_err,
             n_wait_free, n_drain, n_drain_timeout, n_late, n_late_direct, n_late_full,
             n_mismatch, last_status, n_late_frame;
    uint32_t ended_vol;                  /* the vol our stop restored; 0 at take start */
    ix_cap   cap;                        /* before q: a fixed offset for the host */
    bq_t     q;
    ix_px_t  px;                         /* the push engine (ix_push.c); last, 16-aligned */
} wr_t;

void     wr_init(wr_t *w, const wr_fw *fw, int flag, const uint32_t veneer[6],
                 uint32_t block_bytes, uint32_t maxdesc_at);
void     wr_installed(wr_t *w, uint32_t vol);
int      wr_send(wr_t *w, uint32_t vol, uint32_t lr);
void     wr_cb_cookie(wr_t *w, uint32_t frame, uint32_t status);
uint32_t wr_cb_acquire(wr_t *w);
int      wr_cb_add(wr_t *w, uint32_t addr, uint32_t len);
void     wr_cb_ckpt(wr_t *w);
void     wr_cb_rollback(wr_t *w);
void     wr_cb_release(wr_t *w);
/* One pass of the writer: write every queued block.  wr_task loops on it. */
void     wr_service(wr_t *w);
void     wr_task(wr_t *w);
void     wr_take_start(wr_t *w);
int      wr_late_frame(wr_t *w, uint32_t mgr, uint32_t node);
/* The control task: one step (test_card.py calls it), and the loop. */
void     ix_ctl_step(wr_t *w);
void     ix_ctl_task(wr_t *w);
/* The push engine: build header + TRBs for q, start EP 0x83.  IX_PUSH_* / PX_ERR_*. */
uint32_t ix_push(wr_t *w, const volatile ix_push_req *q, uint32_t timeout_ms);
void     ix_push_release(wr_t *w);
/* CDNG after the stop: scan the RAW arena, push the newest take's DNGs (task only). */
void     ix_cdng_run(wr_t *w);

#endif
