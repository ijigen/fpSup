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
#define IX_CAP_VERSION 10u

/* ctl: the host writes start_ms/rec_ms, then ctl = IX_CTL_ARMED (last).  The
 * control task stamps t_arm and, start_ms later, runs the firmware's own
 * record script (FUN_c0405ba0): recstate ena/init, key MOVON, then (layout 10)
 * polls recstate +6 itself every step instead of the blocking movrecstwai, so
 * LV goes on across the start; rec_ms after that ONE key MOVON + recstate
 * movsavewai, recstate disa. Uncertain start/stop is never retried. Writing 0
 * before the MOVON cancels; after it nothing does. After our disa, reset its
 * stale registration byte. */
enum { IX_CTL_IDLE = 0, IX_CTL_ARMED = 1, IX_CTL_REC = 2, IX_CTL_DONE = 3,
       IX_CTL_FAIL_START = 4,            /* no sign the take started: no second press */
       IX_CTL_FAIL_STOP = 5,             /* stop attempted once, no "saved"            */
       IX_CTL_STARTING = 6 };            /* MOVON pressed, recstate +6 not yet seen    */
/* movrecstwai's own bound (FUN_c0407ab8(.., 3)): 600 polls of +6, 100 ms apart */
#define IX_START_WAIT_MS 60000u

/* LV sampler (layout 3): the control task reads the LCD output descriptor
 * (0xC30255B4) and the display DMA channel's slot register, and hands the slot
 * written before the current one to the push engine (FPP1, PUSH_PROTOCOL.md)
 * as source 1, mode 0 (skip if busy).  The engine is another sup: the host
 * writes its entry into lv_push (Thumb: +1); 0 = sampler off.  Design:
 * notes/PUSH_CALLERS.md §1. */
#define IX_LV_DESC     0xC30255B4u       /* LCD descriptor: [3] w [4] h [8] n [9..] handles */
#define IX_LV_CHSEL    0xC31DF8D8u       /* channel = this + 2 (>= 7: 8), FUN_c01d7638 */
#define IX_LV_ENGINE   1u
/* the display watch: three LCD output descriptors' w/h, the engine's output size, the exported preview config of
 * the first two channels (visible w/h, source w/h; open-gate LIVE_VIEW_DISPLAY_CHAIN §1) */
#define IX_FC_REG      0x30100588u       /* receiver frame counter, & 0x7FF (FUN_c0125870 reads it twice) */
#define IX_WT_N        16u
#define IX_WT_ADDRS    { 0xC30255C0u, 0xC30255C4u, 0xC3025640u, 0xC3025644u, 0xC30256C0u, 0xC30256C4u, \
                         0xC31E10F8u, 0xC31E10FCu, 0xC31DF594u, 0xC31DF598u, 0xC31DF59Cu, 0xC31DF5A0u, \
                         0xC31DF744u, 0xC31DF748u, 0xC31DF74Cu, 0xC31DF750u }                /* lv_push = 1: the built-in engine (ix_push.c) */
#define IX_LV_MAX_N    8u
#define IX_LV_MAX_BYTES ((16u << 20) - 1024u)   /* one TRB */
enum { IX_PUSH_SENT = 0, IX_PUSH_SKIPPED = 1 };
/* LV push flags (FPP1 header +0x2C): bit0 recording, bit1 half-press, bit2 magnify, and (layout 10) */
#define IX_LV_F_BURST    8u              /* a burst push: frame_no = slot, aux0 = the step's tick_us, aux1 = bu index */
#define IX_LV_F_STARTING 16u             /* sampled between our MOVON and recstate +6 */
/* the burst (layout 10): every newly finished ring slot from our MOVON until lv_burst_ms after the start was
 * seen, one bu entry per burst push sent (the first IX_BU_N), with the display watch at that moment */
#define IX_BU_N        48u
typedef struct { uint32_t tick_us, slot, flags, reg, wt[IX_WT_N]; } ix_burst;
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
enum { IX_CP_STANDBY = 0, IX_CP_FOCUS = 1, IX_CP_MAG = 2, IX_CP_SETTLE = 3, IX_CP_DONE = 4 };
#define IX_CP_SETTLE_MS 600u
enum { IX_UR_WAIT = 0, IX_UR_OFF = 1, IX_UR_DONE = 2, IX_UR_NOFIX = 3 };
#define IX_USBFIX_AT    0xC0032808u      /* the dev shell's first USBFIX word (cards/build_devshell.py) */
#define IX_USBFIX_WORD  0xE3A03B01u      /* mov r3, #0x400: EP83 MPS 1024 */
#define IX_UR_AFTER_MS  3000u            /* after the control task's first step: every sup has loaded */
#define IX_UR_OFF_MS    700u             /* "usb off" .. "usb on" */
#define IX_UR_GIVEUP_MS 30000u           /* no USBFIX by then: a release shell, never reconnect */             /* after leaving magnify: the readout mode switches back */
/* report events (FPP1 source 5, header frame_no and aux0; payload = the ix_cap snapshot, w = IX_CAP_VERSION) */
enum { IX_EV_ARMED = 1, IX_EV_REC = 2, IX_EV_STOPPED = 3, IX_EV_FAIL_START = 4, IX_EV_FAIL_STOP = 5,
       IX_EV_CDNG = 6, IX_EV_HEARTBEAT = 7 };
#define IX_RP_SOURCE  5u
#define IX_RP_FMT     6u
#define IX_RP_BUF     4608u              /* >= sizeof(ix_cap); checked at compile time in ix_wr.c */

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
    /* reports (layout 5): a snapshot of this whole struct pushed as FPP1 source 5 -- host-written */
    uint32_t rp_on;                      /* 1: push one at every control event (mode 1, short wait) */
    uint32_t rp_every_us;                /* heartbeat: one per this interval, mode 0 (0: none) */
    /* camera-written */
    uint32_t rp_t_last, rp_n_sent, rp_n_skip, rp_last_ev;
    /* checkpoints before the take (layout 6): standby -> half-press AF -> magnify -> settle -> REC, all by the
     * control task, so the LV pushed in each phase carries its flag (bit1 half-press, bit2 magnify) -- host-written */
    uint32_t cp_standby_ms, cp_focus_ms, cp_mag_ms;   /* 0: skip that phase */
    /* camera-written */
    uint32_t cp_phase, cp_t;             /* IX_CP_*, tick_us the phase began */
    /* LV burst across the start (layout 10) -- host-written, inside the arm image */
    uint32_t lv_burst_ms;                /* 0: off (the lv_every_us cadence only) */
    /* USB reconnect once after boot (layout 7): the host enumerated PTP before the dev shell's USBFIX
     * patched FUN_c00327b8, so EP83 is still interrupt/64 until the next connect -- camera-written */
    uint32_t ur_state, ur_t0, ur_t;      /* IX_UR_*, first step / "usb off" tick_us */
    /* display watch (layout 8): the words of IX_WT_ADDRS, sampled with every LV step -- the last value seen in
     * standby and the last while recording (the recording LV ring is 1920x1080 on every route: which layer the LCD
     * shows from, and how it is fitted, is read here, never over USB during the take) -- camera-written */
    uint32_t wt_n_sby, wt_n_rec;
    uint32_t wt_sby[IX_WT_N], wt_rec[IX_WT_N];
    /* sensor frame clock while recording (layout 8): the receiver's frame counter IX_FC_REG & 0x7FF, sampled every
     * control step; fps = fc_frames / (fc_t_last - fc_t_first) us -- camera-written */
    uint32_t fc_prev, fc_frames, fc_t_first, fc_t_last, fc_steps, fc_gap_max;
    /* LV burst (layout 10), past the arm image: zeroed by the control task when it sees the arm -- camera-written */
    uint32_t t_movon;                    /* tick_us | 1 right after our start MOVON returned */
    uint32_t bu_last;                    /* the slot the last burst push sent (0xFFFFFFFF: none yet) */
    uint32_t bu_sent, bu_skip, bu_err;   /* burst pushes: sent / engine busy / refused or bad */
    uint32_t bu_n;                       /* entries in bu (= min(bu_sent, IX_BU_N)) */
    ix_burst bu[IX_BU_N];
} ix_cap;

/* ---- the push engine (FPP1 over EP 0x83, notes/PUSH_PROTOCOL.md; ix_push.c).
 * The header and the TRB chain live here and are written through the uncached
 * alias, so the controller reads them with no cache maintenance.  TRB buffer
 * addresses are DMA = uncached CPU - 0x40000000 (the firmware's own convention). */
#define PX_CTX        3u                 /* EP 0x83 (memory push-endpoint-is-ep83) */
#define PX_PHYS       7u
#define PX_TRB_DMA    0xC31E3238u        /* [ctx]: TRB DMA address StartTransfer hands the controller */
#define PX_TRB_CPU    0xC31E3264u        /* [ctx]: the same TRB, CPU address (= DMA + 0x40000000) */
#define PX_DEAF       0xC31E38FCu
#define PX_DEPCMD     (0x2100C80Cu + 0x10u * PX_PHYS)   /* DWC3 DEPCMD of phys 7: reads back the last endpoint command */
#define PX_CMD_START  6u
#define PX_CMD_UPDATE 7u        /* 1 after a PTP Cancel/Reset: StartTransfer -> -2 (handover F2) */
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
    uint32_t n_lost;                     /* chains dropped by an endpoint reconfigure (host reopen, reconnect) */
    uint64_t bytes;
} __attribute__((aligned(64))) ix_px_t;  /* DWC3 TRBs must be 16-aligned: a misaligned chain is read 8 bytes
                                          * early, its write-back lands in lo/hi and HWO never clears (10-27) */

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
    uint8_t  rp_buf[IX_RP_BUF];          /* report snapshot, written through the uncached alias */
    uint32_t starting;                   /* our start MOVON is unconfirmed: outside the cap, so no host
                                          * write can cancel a pressed start (layout 10) */
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
