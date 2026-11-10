/* SensorLab-IMX410 apply: the camera half -- hooks, the virtual tables, the commit transaction, the debounce.
 *
 * One unit with ap_calc.c (included) and, in the sup, after core.c: slqs.c ends with
 *     #include "../apply/ap.c"
 * (or ap.c is compiled with core.c into its own object: it needs only core.h's functions).  Built Thumb, -fropi,
 * no writable globals: every byte of state lives in the caller's `mem` (struct ap), the veneers included.
 *
 * Technique (copied from RES-Custom, projects/open-gate/build/res-custom ogc.c + ogc_shims.S, never calling it):
 *   - two virtual sensor mode ids (AP_VMID0, +1) used in turn: a commit writes the slot that is NOT live, stops the
 *     live view, flips, restarts it; the old slot stays intact until the commit after next (rotation, so no row
 *     the firmware may still hold is ever rewritten under it).
 *   - the seven index lookups answer an index that lands on our row (fake_index), the +0x10 lookup the value (R10).
 *   - the magnifier table: our row is the donor's with our id; acd8 / zg see the donor; v32 writes nothing for our
 *     ids (the REG row already carries the window: imx410-lab KEEP_WINDOW).
 *   - the picker (route tables, 12-bit) hands out our entry {5, virtual pid, virtual mode, key} while a slot is live
 *     and the key's rate suffix is the carrier's; the virtual pid's gather gets the base row of profile 171 (isp-lab's
 *     BASE_ID) and the canvas hook writes the formula's words over it, +0x30 = the carrier's engine fps.
 *   - recrate (DNG FrameRate), binfilt (CRCT selector + both kernel writers), LV out descriptor / aspect / ratio,
 *     the gain dispatch (gs) and the six standby profiles' visible size follow the live slot.
 * Every hook is one generic ARM veneer (ap_veneer below) calling ap_hook(A, frame, id) with an 8-aligned stack. */
#include <stdint.h>
#include "ap.h"
#include "sloader4.h"
#include "ap_calc.c"
#include "pb_glyph.h"

/* ---- firmware (Ver.5.02; every address is res-custom's, live-proven there) ---- */
#define AP_IMAGER     0xC343B588u     /* XC_ImageSensorIMX410: +0 the mode descriptor, +4 the current mode */
#define AP_HOLDER     0xC343B67Cu     /* the register-record holder: +0 -> {base, count} */
#define AP_MAPPING    0xC0BD05D4u     /* profile id -> profile row */
#define AP_BASE_PID   171u            /* isp-lab isp_custom BASE_ID: the row the formula is proven over */
#define AP_LV_MGR     0xC375D840u     /* +8 = the current LV canvas, its +0 the profile id */
#define AP_TAB3       0xC0BE5B50u     /* picker route table, eRawBitType 12-bit */
#define AP_TAB1       0xC0BE5810u     /* 0.0.3test: eRawBitType 4 = 8-bit (FUN_c043b828: params +0x20 == 4) */
#define AP_TAB2       0xC0BE59B0u     /*            eRawBitType 3 = 10-bit (== 3); anything else asks TAB3 */
#define AP_BIT_GET    0xC005BF28u     /* (settings) -> eRawBitType, the stock bit-depth setting (res-custom BIT_GET) */
#define AP_TABS       0xC0BE4990u     /* picker standby table: MOV* {1, pid 5.., mode 8 ..}, MAG* (magnifier) */
#define AP_SBASE_PID  5u              /* the standby profile (MOV / MOVAF60): the standby base row */
#define AP_FR_SET     0xC005C0B8u     /* (settings, enum, 0): the native frame-rate setter (vtable +0x1A4, as the
                                         resolution setter C005C020 is +0x1A0; the menus call it (obj, v, 0)) */
#define AP_EXCL_MGR   0xC049EC58u     /* res-custom: recompute the frame-rate / bit-depth list classes */
#define AP_EXCL_RECOMPUTE 0xC049EE78u
#define AP_ICACHE     0xC000EABCu     /* invalidate the I-cache (isp_custom _flush) */
#define AP_CLK_SITE   0xC0189440u     /* FUN_c0189298: Thumb movw ip, #0x1249 = channel 0's clock 5/16 above 99 fps */
#define AP_CLK_STOCK  0x2C49F241u
#define AP_CLK_OPEN   0x7CFFF64Fu     /* movw ip, #0xffff (res-custom build_v3_rescustom CLK0) */
#define AP_GET_OBJ    0xC0057AE8u
#define AP_GET_FMT    0xC005BE90u     /* (settings) -> 0 = CinemaDNG */
#define AP_CINE       0xC0058340u     /* (settings) -> CinemaMode, 0 = STILL (screenflip flip.c) */
#define AP_FR_GET     0xC005C0F0u     /* (settings) -> the frame-rate internal enum (the carrier) */
#define AP_CAMSCH1    0xC0207188u
#define AP_CS_GET     0xC0207440u
#define AP_CS_SET     0xC02073B8u
#define AP_LV_HOLDER  0xC0423C48u
#define AP_LV_STOP    0xC0423D28u
#define AP_LV_START   0xC0423C88u
#define AP_DCACHE     0xC000E91Cu     /* clean the D-cache (firmware-file-read-idiom) */
#define AP_TICK_US    0xC002B6E0u
#define AP_MOV_SELECTOR 0xC347D1D4u   /* movie-recording-flag-selector: 0x21 -> the flag at SEL21 */
#define AP_MOVREC_SEL21 0xC3476609u
#define AP_MOVREC_DEFAULT 0xC347E08Fu
#define AP_XMP_FOBJ   0xC358E140u
#define AP_MOV_ACTIVE 0xC35A952Cu

/* ---- v0.7.25test: defect (hot pixel) correction for our ids (notes/DEFECT_VIRTUAL_MODES.md) ----
 * FUN_c030e2a0 (ImagerDefect, every mode set) hands DEFC the flash table R68 +04 untranslated unless the mode is v33 /
 * in the magnifier table (imx410-lab DEFECT_CORRECTION.md), so our ids got table 97 in mode 97's raster.  The commit
 * converts the source table R68 +0C with the firmware's own FUN_c0310740 and our R68 row into the slot's buffer;
 * H_DEFC hands that buffer to the loader FUN_c0635d80 (Thumb, only called from c030e2a0) in place of the flash one. */
#define AP_DEFC_CTX   0xC343A66Cu     /* c030e2a0's / c0310740's first argument */
#define AP_DEFC_BUFP  0xC343A71Cu     /* -> the flash defect buffer (partition 0xF, 0x40000 B); 0 = not loaded */
#define AP_DEFC_DIR   0x16000u        /* the directory: +0 valid, +4 n, +8 u16 ids[64], +0x88 u16 sizes (words) */
#define AP_DEFC_BYTES 0x40000u        /* the buffer; table i's point list sits at its end - 0x100 (i + 1) */
#define AP_DEFC_CONV  0xC0310740u     /* (ctx, mode, size words, out table, out list 0x200 B, source table) -> 1 */
#define AP_DEFC_WORDS 0x4000u         /* per slot (u32); Bei's camera's 1x1 table 0x61 is 14454 words */

/* ---- playback (v0.6.0, notes/PLAYBACK_DESIGN.md) ---- */
#define AP_KEYBLD     0xC043BCBCu     /* FUN_c043bc68 (configurator mode 5 = playback) returning from the name emitter */
#define AP_PB_BITS16  0xC05C1ED0u     /* (tiff, 0, tag, &u16, 0) -> != 0 found (FUN_c05c1a58's BitsPerSample read) */
#define AP_PB_LONG    0xC05C1DB8u     /* same ABI, one LONG */
#define AP_PB_PAIR    0xC05C1E40u     /* same ABI, DefaultCropSize pair */
#define AP_TAG_READ   0xC00BA4D8u     /* (tiff, ifd, tag, out, n rationals) -> 0 found (its FrameRate read) */
#define AP_TAG_SET    0xC00BA310u     /* (tiff, ifd, 0, tag, type, count, data): the IFD writer's own setter */
#define AP_NBR_LOAD   0xC05E84D9u     /* Thumb (app, pack, bytes, &reader) -> 0 (fpsup-ui, res-lab rl_prepare) */
#define AP_GUI_OBJECT 0xC37B7048u     /* the GUI app (fpsup-ui FPUI_GUI_OBJECT) */
#define AP_PB_VAR_SET 0xC059F5C8u     /* (notifier, name, value): XC_GuiPlayOnePicNotifier's variable setter */
#define AP_PB_RES_NAME 0xC2DF65B0u    /* "PB_Resolution" (v92 sets it to (w, h) != 3840 x 2160) */
#define AP_PB_OWN_NAME 0xC2DF7C30u    /* "PB_OwnModel" (v153 sets it to param ^ 1: 0 = this camera's clip) */
#define AP_PB14_EN    0u              /* a 14-bit clip's bit enum handed on: the 12-bit route table (FUN_c043bc68
                                         takes 4 = 8-bit, 3 = 10-bit, else 12-bit), then canvas code 8 (14-bit) */
#define AP_PB_RES_STOCK 0xFFFFFFFFu
#define AP_PB_TAGS    8u
#define AP_PB_RING_CAP (0x6F090u / 0x5ECu) /* C05C2D10: descriptor allocation / descriptor stride = 300 */
/* v0.7.24test: the largest raster the player is known to allocate for -- stock DCI4K 4112 x 2170.  Its FieldAngle work
 * area in the 48 MiB LVIEW pool grows with the raster (15 MB here, 40.5 MB at 6048 x 4040) and a failed allocation
 * asserts (C04371F0): a 6K clip froze the camera (Bei 11-02/11-03).  Larger clips are refused before any buffer. */
#define AP_PB_MAX_AREA (4112u * 2170u)
#define AP_PB_RAW_SETUP 0xC31DECCCu   /* C01CDBE0's RAW-read setup base (r5 at C01CE450) */
#define AP_TADD_STOCK 0x0282EB05u     /* Thumb add.w r2, r5, r2, lsl #2: the one K_TADD site's displaced word */
#define AP_GLYPHS     8u
#define AP_GLYPH_BYTES ((AP_GLYPH_PACK_LEN + 7u) & ~7u)

#define AP_VMID0      230u            /* res-custom's ids: < 250 (name slots), not stock, not 0x99..0xB7 */
#define AP_VPID0      74u             /* empty class-0 mapping slots (res-custom VPID_POOL[0..1]) */
#define AP_MAGIC      0x31504C53u     /* "SLP1" */
#define AP_ASPECT_ENUM 9u             /* the aspect sites answer 9; the ratio getter (asserts at >= 9) gives our pair */
#define Z_STRIDE      0x5Cu
#define Z_FIELD       0x128u

typedef u32 (*ap_fw0)(void);
typedef u32 (*ap_fw1)(u32);
typedef u32 (*ap_fw2)(u32, u32);
typedef u32 (*ap_fw3)(u32, u32, u32);
typedef u32 (*ap_fw4)(u32, u32, u32, u32);
typedef u32 (*ap_fw5)(u32, u32, u32, u32, u32);
typedef u32 (*ap_fw6)(u32, u32, u32, u32, u32, u32);
typedef u32 (*ap_fw7)(u32, u32, u32, u32, u32, u32, u32);

#define AP_W(a)  (*(volatile u32 *)(uintptr_t)(a))
#define AP_B8(a) (*(volatile uint8_t *)(uintptr_t)(a))

static inline u32 ap_irq_off(void)
{
    u32 s;
    __asm volatile("mrs %0, cpsr\n\tcpsid if" : "=r"(s) :: "memory");
    return s;
}
static inline void ap_irq_restore(u32 s) { __asm volatile("msr cpsr_c, %0" :: "r"(s) : "memory"); }
static inline void ap_dmb(void) { __asm volatile("dmb ish" ::: "memory"); }

/* ---- the seven tables (ogc_layout.TABLES): descriptor field, stride -------------------------------------- */
enum { TB_TIM, TB_META, TB_R28, TB_R38, TB_R14, TB_R68, TB_REG, TB_N };
static const u32 TB_FIELD[TB_N] = {0x00, 0x08, 0x24, 0x40, 0x48, 0xF4, 0x00};   /* REG: of the register desc */
static const u32 TB_STRIDE[TB_N] = {0x20, 100, 0x28, 0x38, 0x14, 0x68, 0x288};
#define BUF_BYTES(st) ((((st) + 32u) + 7u) & ~7u)
#define BUF_TOTAL (BUF_BYTES(0x20) + BUF_BYTES(100) + BUF_BYTES(0x28) + BUF_BYTES(0x38) + BUF_BYTES(0x14) + \
                   BUF_BYTES(0x68) + BUF_BYTES(0x288))

/* ---- the hooks --------------------------------------------------------------------------------------------- */
enum { K_ENTRY = 0, K_MID = 1, K_BL = 2, K_TADD = 3 }; /* K_TADD: Thumb BLX; handler replays its non-flag-setting ADD */
enum { H_LK0 = 0, H_LK_R10 = 7, H_AC38, H_ACD8, H_ZG, H_V32, H_PICK, H_VPRO, H_CANVAS, H_GS, H_RECRATE,
       H_BINPATH, H_BINK1, H_BINK2, H_OUT, H_ASP1, H_ASP2, H_RATIO, H_FRMAX, H_FRCLASS, H_BLK6, H_BLK,
       H_PBTAG, H_PBNAME, H_DSCALE, H_PBW, H_PBH, H_PBRES, H_PBPREP1, H_PBPREP2, H_FIT, H_YUV32, H_YUV_FALLBACK, H_PBHEADER,
       H_PBRING, H_PBRAW14, H_PBOWN, H_DEFC, H_FFARM, H_FFFIX, H_FFDONE, H_RESYNC, H_RESYNC2,
#ifdef AP_REC_DELAY_TEST
       H_RECDLY,
#endif
       AP_NHOOK };
struct ap_site { u32 site, stock, kind; };
/* order = H_*; stock = the image's word at the site (test_apply checks every one) */
static const struct ap_site AP_SITES[AP_NHOOK] = {
    {0xC0320BA0u, 0xE92D00F0u, K_ENTRY},   /* lk_tim   push {r4-r7}        */
    {0xC0320B38u, 0xE92D00F0u, K_ENTRY},   /* lk_meta                      */
    {0xC0320E90u, 0xE92D04F0u, K_ENTRY},   /* lk_r28   push {r4-r7, sl}    */
    {0xC0320F60u, 0xE92D04F0u, K_ENTRY},   /* lk_r38                       */
    {0xC0320EF8u, 0xE92D04F0u, K_ENTRY},   /* lk_r14                       */
    {0xC0320C00u, 0xE92D00F0u, K_ENTRY},   /* lk_r68                       */
    {0xC0326DB8u, 0xE92D04F0u, K_ENTRY},   /* lk_reg                       */
    {0xC031FFA0u, 0xE92D00F0u, K_ENTRY},   /* lk_r10 (a value)             */
    {0xC031AC38u, 0xE92D4CF0u, K_ENTRY},   /* ac38(dst, _, mode)           */
    {0xC031ACD8u, 0xE92D4BF0u, K_ENTRY},   /* acd8(_, _, _, mode)          */
    {0xC031B660u, 0xEB001724u, K_BL},      /* zg: bl 0xC03212F8 (current mode) */
    {0xC03249A0u, 0xE92D4DF0u, K_ENTRY},   /* v32(imager, i)               */
    {0xC043CCF8u, 0xE92D4CF0u, K_ENTRY},   /* picker(obj, table, key)      */
    {0xC043A18Cu, 0xE79C1105u, K_BL},      /* vpro: ldr r1, [ip, r5, lsl #2] */
    {0xC043A19Cu, 0xE1A00004u, K_BL},      /* canvas: mov r0, r4 (r4 holder, r5 pid) */
    {0xC03A6DD8u, 0xE92D4010u, K_ENTRY},   /* gs()                         */
    {0xC00C9BD0u, 0xE92D41F0u, K_ENTRY},   /* recrate(out)                 */
    {0xC0325228u, 0xE92D00F0u, K_ENTRY},   /* binpath(_, in, out)          */
    {0xC032DDF0u, 0xFA0C1FEEu, K_BL},      /* binkernel1: blx 0xC0635DB0 (r1 driver) */
    {0xC032DE70u, 0xFA0C1FD4u, K_BL},      /* binkernel2: blx 0xC0635DC8   */
    {0xC0437E98u, 0xE92D4030u, K_ENTRY},   /* out(obj, idx)                */
    {0xC0306EA0u, 0xE3A00003u, K_MID},     /* aspect: mov r0, #3           */
    {0xC0306EECu, 0xE3A00003u, K_MID},     /* aspect2: mov r0, #3          */
    {0xC02DAFA0u, 0xE92D4010u, K_ENTRY},   /* ratio(enum) -> {w, h}        */
    {0xC00A87E4u, 0xE1A01004u, K_MID},     /* frmax: mov r1, r4 (r4 = the fastest rate the normaliser allows) */
    {0xC04A121Cu, 0xE1A00001u, K_MID},     /* frclass: mov r0, r1 (r1 = the frame-rate list's state class) */
    /* the DNG BlackLevel (0xC61A, FUN_c02ca190): sensor black (+0x208, 12-bit scale) shifted by the bits FUN_c02da870
     * gives for the RAW descriptor's +0x24 (mode 6) / +0x08 field -- 12 for our true 14-bit DNG, so it wrote 256 under a
     * 16383 white (RWZM_14BIT_CHECK §1).  For a true-14 slot both calls answer 14 (black << 2 = ~1024). */
    {0xC02CA1C0u, 0xEB0041AAu, K_BL},      /* bl FUN_c02da870(desc[+0x24]) */
    {0xC02CA21Cu, 0xEB004193u, K_BL},      /* bl FUN_c02da870(desc[+0x08]) */
    /* v0.6.0 playback: the clip's tags (FUN_c05c1a58: the six tags playback reads), the playback key build (its name
     * emitter's caller is AP_KEYBLD: the clip's DefaultCropSize and bit enum), the DNG DefaultCropSize writer
     * (DefaultScale next to it), and the HUD's three notifier setters (size tiles, PB_Resolution). */
    {0xC05C1A58u, 0xE92D40F0u, K_ENTRY},   /* pbtag(_, tiff, crop out, raster out) */
    {0xC0437B48u, 0xE92D4BF0u, K_ENTRY},   /* pbname: the resolution-name emitter (obj, out, sizes) */
    {0xC02C43C0u, 0xE52DE004u, K_ENTRY},   /* dscale(_, tiff, ifd, info): str lr, [sp, #-4]! */
    {0xC059F8B8u, 0xE92D4030u, K_ENTRY},   /* pbw: XC_GuiPlayOnePicNotifier v5 (n, w): PB_PixelSizeDisp / Width */
    {0xC059F8F8u, 0xE92D4030u, K_ENTRY},   /* pbh: v6 (n, h): PB_PixelSizeDisp / Height */
    {0xC05A1500u, 0xE92D40F0u, K_ENTRY},   /* pbres: v92 (n, w, h): PB_Resolution */
    /* v0.7.0test (v1 playback safety): FUN_c05be080(obj, info), the one place every CinemaDNG decode is prepared --
     * its only two callers, FUN_c05bde28 (multi-frame / stream) and FUN_c05bdfa0 (one frame, XC_CinemaDngPlay v12),
     * return 0 when it does (its own "no frame entry" failure), before any buffer or the RAW engine is touched */
    {0xC05BDE80u, 0xEB00007Eu, K_BL},      /* pbprep1: bl FUN_c05be080 in FUN_c05bde28 */
    {0xC05BDFE8u, 0xEB000024u, K_BL},      /* pbprep2: bl FUN_c05be080 in FUN_c05bdfa0 */
    /* The YUV live fitter snaps arbitrary ratios to 3:2 / 16:9; restore only our own live pair.
     * W71C1 v4 is also used by RGB/UI bitmaps: its classifier must stay native (v0.7.4test). */
    {0xC02F455Cu, 0xE300EE04u, K_MID},    /* fit: movw lr, #0xe04, after r6/r7's native aspect snap */
    {0xC0306E70u, 0xE3A00002u, K_MID},    /* W v2 LCD 3:2 branch: mov r0, #2 */
    {0xC0306F28u, 0xE28D102Cu, K_MID},    /* W v2 fallback: add r1, sp, #0x2c (source size) */
    {0xC05BDC9Cu, 0xEBEC0E19u, K_BL},     /* v11: parse the existing bounded file buffer, before its tags */
    {0xC05C2DE8u, 0xEBE968FEu, K_BL},     /* ring: bl C001D1E8, before each RAW buffer allocation (r4 = ring) */
    {0xC01CE450u, 0x0282EB05u, K_TADD},   /* AP_TADD_STOCK; RAW-read format fallback before store +0x50 */
    /* v0.7.21test: a clip whose size has no font_S_imageSize_<N> image shows the "other model" pixel-size row,
     * PB_PixelSizeString (per-digit font_S_<d> glyphs, computed for every clip), instead of missing images */
    {0xC05A2440u, 0xE92D4030u, K_ENTRY},   /* pbown: v153 (n, own): PB_OwnModel = own ^ 1 */
    /* v0.7.25test: FUN_c0635d80 is Thumb (an ARM entry branch cannot go there); its six callers are all in the ARM
     * FUN_c030e2a0, which keeps its mode argument in r5 throughout.  This is the single-table load of the small
     * directory format (C051F4D8 = SensorAdjustSeparate +0x14 = 0 -> C030ECE0..; IMX410 desc+0x94 = 0); the other
     * five are the double-table and large-format (C030E31C..) copies and the two "off" calls (r0 = 0). */
    {0xC030F624u, 0xFA0C99D5u, K_BL},      /* defc: blx FUN_c0635d80(2, {table, list[128]}), r5 = the mode */
    /* v0.7.26test: the first recorded frame's +1 row (notes/FIRST_FRAME_REPAIR.md).  ContSet_Adr1's BUFA1 branch hands
     * the first frame's raster (desc +0x38, r0; r6 = desc - 8: +0x1C mode, +0x20 format) to the DMA before its start
     * FUN_c0631c08(1) at C031CAE0; FUN_c038bd98 (SRecRaw, every CinemaDNG frame) looks the frame up first thing, before
     * cineCapture, the header DMA (C038C5F8) and the creator enqueue (C038BFF0, Lossless's arrival). */
    {0xC031C948u, 0xFA0C5492u, K_BL},      /* ffarm: blx FUN_c0631b98(raster), the BUFA1 destination of frame 1 */
    {0xC038BDB4u, 0xEBFFA581u, K_BL},      /* fffix: bl FUN_c03753c0(table, id) -> the arriving frame */
    /* v0.7.27test: BUFA1's completion callback (FUN_c0630d60 calls it from the IRQ with the completed raster, r0) */
    {0xC031BCA0u, 0xE92D4070u, K_ENTRY},   /* ffdone: FUN_c031bca0 push {r4, r5, r6, lr} */
    /* v0.7.28test: ContSet_Adr1's mode switch (r1 = desc +0x1C, the record mode), before its shutter / arm-timing
     * waits and the whole BUFA1 block (C031C834..C031CAE4): the sensor pause / resume + link resync runs after it */
    {0xC031BF88u, 0xEBFFDD1Cu, K_BL},      /* resync: bl SetImgMode_s(imgmode, mode) */
    /* v0.7.29test: the switch a CinemaDNG REC start really makes (v0.7.28test live: C031BF88 never reached): the image
     * controller task's message 1 (FUN_c030d0c0: FUN_c030ce00 posts it and waits for its event) runs SetImgMode_s with
     * the message's +0x1BC; ContSet_Adr1 then finds the mode already current and skips its own switch */
    {0xC030D168u, 0xEB0018A4u, K_BL},      /* resync2: bl SetImgMode_s(FUN_c03133a0(), [r4, #0x1bc]) (ImgCtrl task) */
#ifdef AP_REC_DELAY_TEST
    /* 0.0.2test TEST build only (validation/20261107-rec-delay): FUN_c0378a50 (CinemaDNG REC start) calls FUN_c030cf98
     * (desc copy -> ContSet_Adr1: mode switch, VD waits, BUFA1 arm / start) here; sleep N ms first */
    {0xC0379180u, 0xEBFE4F84u, K_BL},      /* recdly: bl FUN_c030cf98(r0, r1, r2) */
#endif
};

/* The veneer (ARM, 88 bytes, 8-aligned; offsets in words):
 *   0  push {r0-r12, lr}       frame: f[0..12] = r0..r12, f[13] = lr
 *   1  mov r1, sp               (frame)
 *   2  mov r5, sp               (r5: callee-saved in C, restored from the frame)
 *   3  bic sp, sp, #7           8-aligned for the C (memory arm-stack-alignment)
 *   4  ldr r0, [pc, #0x20]      A
 *   5  ldr r2, [pc, #0x20]      hook id
 *   6  ldr ip, [pc, #0x20]      ap_hook | 1
 *   7  blx ip
 *   8  mov sp, r5
 *   9  cmp r0, #0
 *  10  pop {r0-r12, lr}         (the frame, as the C left it)
 *  11  ldreq pc, [pc, #0x10]    0: down (the layer below / the replay)
 *  12  ldr pc, [pc, #0x10]      1: "ret": entry / BL = word 13 (bx lr), mid = site + 4
 *  13  bx lr
 *  14..18  A, id, fn, down, ret
 *  19  the displaced instruction (replay)      20  ldr pc, [pc, #-4]      21  site + 4 */
#define VW 22u
static const u32 AP_VENEER[14] = {
    0xE92D5FFFu, 0xE1A0100Du, 0xE1A0500Du, 0xE3CDD007u, 0xE59F0020u, 0xE59F2020u, 0xE59FC020u, 0xE12FFF3Cu,
    0xE1A0D005u, 0xE3500000u, 0xE8BD5FFFu, 0x059FF010u, 0xE59FF010u, 0xE12FFF1Eu,
};
enum { V_A = 14, V_ID, V_FN, V_DOWN, V_RET, V_INSN, V_JMP, V_BACK };

struct ap_tpl { u32 w, h, from, used, words[11]; };
struct ap_slot {
    u32 valid, id, pid, donor, carrier, rank, engine, sfx_len;
    char sfx[8];
    u32 row[TB_N];                    /* the placed rows (absolute), 0 = none */
    u32 r10, zok;
    u32 zrow[Z_STRIDE / 4];           /* the magnifier row: the donor's, our id */
    u32 base_row;                     /* mapping[171] */
    u32 isp[65], mask[3];
    u32 sb_w, sb_h, asp[2], is169, box_w, box_h, det_h;
    u32 dng_n, dng_d, binfilt, fast, rec14, sok;
    u32 ds_on, ds[4];                 /* the DNG DefaultScale (apc_dscale) */
    u32 entry[4];                     /* {5, pid, mode, key}: what the firmware reads */
    char key[16];
    u32 spid, sby, sbase_row, smask[3];   /* the standby readout (§12.2): its virtual pid, on, base row, its words */
    u32 sentry[4];                    /* {1, spid, mode, skey} */
    char skey[16];
    struct ap_tpl tpl[4];             /* the LV descriptors this slot answers (filled from the stock ones) */
    u32 buf[BUF_TOTAL / 4];
    u32 sv[2], sr[2], sclamp;         /* v0.7.1test: the standby visible / raster (apc_out sv_w..) */
    u32 defc;                         /* v0.7.25test: 1 = A->defc[this slot] holds this slot's converted table */
    u32 rec_w, rec_h;                 /* v0.7.26test: the record raster (the DNG's, = BUFA1's line pixels / lines) */
#ifdef AP_PURPLE_TEST
    u32 pt, smode, meta[2];           /* the toggles latched for this slot; PT_ROWS's stock mode and its META w / h */
#endif
};

/* v0.7.26test: one take's first frame, armed at ContSet_Adr1, checked once at its arrival */
struct ap_ff {
    u32 state;                        /* 1 = armed: the sentinel is in the first frame's row 0, its arrival not seen */
    u32 ras;                          /* the first frame's raster, uncached 0x4... alias (BUFA1's destination) */
    u32 row, rows;                    /* bytes per raster row (the DMA's line words x 4), rows (its line count) */
    u32 seed, id;                     /* the take's sentinel seed; the slot's mode id it was armed for */
};

/* v0.7.27test: one trace record (56 words; word offsets in validation/20261104-first-frame-trace/README.md) */
struct ap_trec {
    u32 kind, seq, epoch, raw, us;    /*  0: AP_TR_*, index; timer epoch / timer5 count; tick_us (0 at the IRQ site) */
    u32 tg_frame, tg_line, tg_flags;  /*  5: 0x30100588 / 0x30100590 / 0x3010058C */
    u32 ras;                          /*  8: the raster as the site has it */
    u32 x[4];                         /*  9: arm {mode, 0x30182210, 2214, 2218}; done {0x301821E8, 0x30182280, n, 0x30182048};
                                             write {frame id, frame, n, 0} */
    u32 ok;                           /* 13: 1 = the digest below was read (the raster is DRAM) */
    u32 head0[8], tail0[16], head1[8], tailn[8];   /* 14 / 22 / 38 / 46: uncached reads */
    u32 pad[2];
};
struct ap_trace {
    u32 magic, ver, rec_words, nmax;  /* "SFTR", 1, 56, AP_TR_N */
    u32 n, lost, take, live;          /* records written this take, refused (full), takes armed, tracing now */
    u32 seed, row, rows, id;          /* the take's sentinel seed, raster row bytes / rows, its mode id */
    u32 done, writes;                 /* completions / writer arrivals recorded */
    u32 pad[2];
    struct ap_trec r[12];
};
_Static_assert(sizeof(struct ap_trec) == 56u * 4u, "trace record");

#ifdef AP_REC_DELAY_TEST
/* 0.0.2test TEST build only: the REC-start delay (validation/20261107-rec-delay/README.md).  The host writes ms (word 1)
 * per take with `mem set`; the hook keeps one record per REC start in a 16-entry ring.  It lives at the start of the
 * client's state (slqs.c struct st, build json rec_delay), attached by ap_rd_attach after ap_init. */
#define AP_RD_MAGIC   0x594C4452u     /* "RDLY" */
#define AP_RD_N       16u             /* a power of two: the ring index is n & (AP_RD_N - 1) */
#define AP_RD_MAX_MS  200u            /* the sleep is clamped here (a frame is 20.8 ms at 48p) */
#define AP_RD_FN      0xC030CF98u     /* FUN_c030cf98(r0, r1, r2): the REC-start descriptor copy -> ContSet_Adr1 */
#define AP_RD_SLEEP   0xC03705D8u     /* FUN_c03705d8(ms): tk_dly_tsk(ms) (0xC01F89C4), asserts on an error -- the
                                         sleep ContSet_Adr1 itself uses for max(3 ms, readout start), same thread */
struct ap_rdrec {
    u32 seq, ms, t0, t1, t2, rc;      /* REC start number (1..), the delay used; tick us at entry / after the sleep /
                                         after FUN_c030cf98 returned; its return value */
    u32 line0, line2;                 /* 0x30100590 (TG line counter) at t0 / t2 */
    u32 arm_us, arm_line;             /* the first-frame arm (ContSet_Adr1, BUFA1 branch, our modes only): tick us, 0x30100590 */
    u32 ff, pad;                      /* the first frame at its writer arrival: 1 shifted (sentinel intact), 2 written; 0 none */
#ifdef AP_PURPLE_TEST
    u32 bits;                         /* the live slot's toggles (PT_*) | its stock row mode << 8 | toggles refused << 16 */
    u32 sw;                           /* SetImgMode_s calls since the previous REC start (either site, any mode) | the last
                                         one's from-mode << 8 | to-mode << 16 | calls into the live slot's mode << 24 */
    u32 sw_dt;                        /* t0 - the end of the last SetImgMode_s, us (0: none seen since boot) */
    u32 cur;                          /* the current sensor mode at t0 (*0xC343A6D8) */
#endif
};
struct ap_rd {
    u32 magic, ms, ver, n;            /* "RDLY"; the delay for the next REC start (host-written); 1 (2: purple); REC starts seen */
    u32 sleeps, clamped, rec_words, nmax;
#ifdef AP_PURPLE_TEST
    u32 bits, smode;                  /* host-written: PT_* toggles and the stock mode PT_ROWS borrows; taken at the next commit */
    u32 live, refused;                /* the last commit's latched toggles (after the rules) and the ones it refused */
    u32 commits, sw_total, pad[2];    /* commits that latched; SetImgMode_s calls seen since boot */
#endif
    struct ap_rdrec r[AP_RD_N];
};
#ifdef AP_PURPLE_TEST
_Static_assert(sizeof(struct ap_rdrec) == 16u * 4u, "rd record");
#else
_Static_assert(sizeof(struct ap_rdrec) == 12u * 4u, "rd record");
#endif
#endif

#ifdef AP_PURPLE_TEST
/* 0.0.3test PURPLE TEST build (validation/20261108-purple-stock-diff): each bit makes the slot committed next match
 * stock UHD CinemaDNG in one respect.  Latched per slot at ap_commit (LV stopped), never while recording, never from
 * busy(): the host writes R->bits, then re-commits (sq_test 30 1, sq_test 30 0). */
#ifndef AP_REC_DELAY_TEST
#error "AP_PURPLE_TEST extends the REC-delay TEST build"
#endif
#define AP_CUR_MODE   0xC343A6D8u     /* FUN_c03133a0(): the image-mode object, +0 = the current sensor mode */
#define PT_TWIN       0x01u           /* standby (the MOV answer) runs a twin id (id + 2, the same rows): REC start switches */
#define PT_NOWIN      0x02u           /* our rows, the sensor's vertical window off (REG 0003 / 0022..0025 = 0, as stock) */
#define PT_ROWS       0x04u           /* the eight mode rows are the stock mode R->smode's (sensor, RX, TG, defect); META */
#define PT_RWZM       0x08u           /* the record canvas's raster / crop / RWZM are the base row's (stock UHD: 3856 x 2170,
                                         1600 / 1600) */
#define PT_SBSTOCK    0x10u           /* standby (the MOV answer) is stock: profile 5, mode 8 */
#define PT_ALL        0x1Fu
#define AP_PT_TWIN    2u              /* twin = id + 2: 232 / 233 (not stock, inside RES-Custom's 230..245, which never
                                         shares a card with SensorLab) */
#define AP_PT_COL00   0xC0BE3ADCu     /* FUN_c0439d18's column tables (profile word = column[row]): +00 raster w */
#define AP_PT_COL04   0xC0BE3FA4u     /*   +04 raster h */
#define AP_PT_COL64   0xC0BE149Cu     /*   +64 rec RWZM h */
#define AP_PT_COLD4   0xC0BE1964u     /*   +D4 rec RWZM v */
static const uint8_t AP_PT_SMODES[4] = {7u, 101u, 123u, 151u};   /* stock UHD 29.97 / 23.98 / 25 / 24: 6064 x 3412 */
static const uint8_t AP_PT_WIN[5] = {2u, 6u, 7u, 8u, 9u};       /* REG words: 0003, 0022, 0023, 0024, 0025 (v32's) */
#endif

/* what FUN_c0635d80(2, .) reads: the table's address (the hardware takes (it - 0x40000000) >> 2, so the uncached
 * alias) and the 128 point-register words (copied by the CPU) */
struct ap_defc { u32 tbl; u32 list[128]; };

/* the playback state (word offsets are what the shell reads: keep them; append only) */
struct ap_pbtag { u32 cw, ch, rw, rh, bits, ds[4]; };
struct ap_pb {
    u32 magic;                        /* "SLPB" */
    u32 mode;                         /* 0 off; 1 every clip the stock playback profile does not fit; 2 only while a
                                         SensorLab slot is live (ap_pb_ctl 0) */
    u32 glyph_on, res_val;            /* HUD tiles registered (ap_pb_ctl 1); PB_Resolution for non-stock clips (2) */
    u32 cw, ch, en, seq;              /* the playback key build's latch: the clip's DefaultCropSize, its bit enum */
    u32 active, ras_w, ras_h, bits;   /* our playback canvas is the current one: its raster and BitsPerSample */
    u32 is169, asp[2], box_w, box_h, det_h;   /* the clip's display (DefaultCropSize x DefaultScale) */
    u32 latches, patches, skips, tags, fix14, dscale_w, hud_hidden, res_sets, glyphs, gfail, outs;
    u32 gq[4], gqn;                   /* numbers queued for a tile by the commits, registered by ap_idle */
    u32 gval[AP_GLYPHS], gn;          /* the numbers whose tile we registered (gn packs used, never reused) */
    struct ap_pbtag tag[AP_PB_TAGS];  /* the last clips' tags (the index view reads many: matched by crop) */
    u32 tag_next;
    struct ap_tpl tpl[4];             /* the LV descriptors playback answers */
    /* v0.7.0test (appended): the v1 policy -- a clip the stock playback profile cannot read is refused before its
     * decode (block, ap_pb_ctl 3); pbc: the current canvas is a movie-playback one (patched or not), so the LV
     * descriptor / aspect hooks never apply the live recipe's shape to a playback screen */
    u32 block, refused, pbc, preps;
    /* The selected player's v11 supplies context=obj+0x1ac, raster=obj+0x98.
     * Keep that exact clip separately from index-view reads with the same crop. */
    u32 owner, file, valid, prepared;
    struct ap_pbtag selected;
    u32 header_owner, header_file, header_tiff, compression;
    /* v0.7.21test: the current clip's size is not a stock movie size (v92) -> PB_OwnModel 1 (the text row);
     * own_last: v153's last parameter, put back when a stock clip follows one we changed */
    u32 own_text, own_forced, own_last, own_sets;
    u32 too_big;                      /* v0.7.24test: clips refused for their raster area (AP_PB_MAX_AREA) */
};

struct ap {
    u32 ven[AP_NHOOK][VW];            /* first: 8-aligned with mem */
    u32 magic, abi, armed, svc;
    u32 active, cur, picked, in_commit, owed, seq;    /* picked: slot + 1 (record), | 0x100 (standby entry) */
    struct ap_sel have, want, run;
    s32 result, detail;
    u32 commits, refusals, lv_reloads, picks, lookups, canvases, recrates, commit_us;
    u32 standby_picks, carrier_sets, clk_ok, clk_open, gated, blacks;
    struct ap_slot slot[2];
    struct apc_out out;
    struct apc_work work;
    struct ap_pb pb;
    uint8_t glyph[AP_GLYPHS][AP_GLYPH_BYTES] __attribute__((aligned(8)));   /* the NBR packs: never freed */
    /* v0.7.25test: the defect tables, one per slot (rotation: the converter writes only the slot nobody runs) */
    u32 defc_builds, defc_skips, defc_loads;
    s32 defc_last;                    /* the last ap_defc_build result: 1 built, 0 not needed, < 0 why not */
    struct ap_defc defc[2];
    u32 dtab[2][AP_DEFC_WORDS] __attribute__((aligned(8)));
    /* v0.7.26test: the first frame's row check (appended) */
    struct ap_ff ff;
    u32 ff_arms, ff_skips, ff_checks, ff_ok, ff_intact, ff_miss;
    u32 rs_calls, rs_skips, rs_us, rs_last, rs_seen, rs_ours;   /* v0.7.28test: REC-start resyncs; last skip reason (1 fast, 2 no v27) */
    struct ap_trace tr;               /* v0.7.27test: the take's first-frame trace (sq_test 33) */
    u32 lv_seen, pb_since;            /* v0.7.35test: standby LV picks ("MOV", any slot), a playback hook since the last */
    /* 0.0.3test (appended): the CinemaDNG bit depth of the route table our entry was last handed out from -- 8 / 10 / 12
     * (TAB1 / TAB2 / TAB3; 0 = none yet).  Stock runs the SAME sensor mode in all three tables (only the profile differs:
     * the canvas plane codes), so the slot is one; the canvas takes the table's plane codes (notes/BITDEPTH_8_10.md). */
    u32 pick_bits, low_picks;
#ifdef AP_REC_DELAY_TEST
    struct ap_rd *rd;                 /* 0.0.2test TEST build: ap_rd_attach (0 = the hook passes straight down) */
#endif
#ifdef AP_PURPLE_TEST
    u32 pt_sw, pt_ours, pt_from, pt_to, pt_sw_us;   /* SetImgMode_s since the last REC start: calls, into ours, the last */
#endif
};
_Static_assert(sizeof(struct ap) <= AP_MEM_BYTES, "AP_MEM_BYTES");
_Static_assert((VW * 4u) % 8u == 0, "veneer size");

static void ap_zero(void *p, u32 n) { for (u32 i = 0; i < n; i++) ((volatile uint8_t *)p)[i] = 0; }
static void ap_copy(void *d, const void *s, u32 n)
{
    for (u32 i = 0; i < n; i++) ((volatile uint8_t *)d)[i] = ((const volatile uint8_t *)s)[i];
}

/* ---- what the firmware can tell us ----------------------------------------------------------------------- */
static int ap_busy(void)                              /* res-custom ogc.c ap_busy(): recording, XMP file, MOV writer */
{
    u32 sel = AP_W(AP_MOV_SELECTOR) == 0x21u ? AP_MOVREC_SEL21 : AP_MOVREC_DEFAULT;
    if (AP_B8(sel)) return 1;
    if (AP_W(AP_XMP_FOBJ)) return 2;
    if (AP_B8(AP_MOV_ACTIVE)) return 3;
    return 0;
}
uint32_t ap_now_us(void) { return ((ap_fw0)AP_TICK_US)(); }

static struct ap_slot *ap_slot_id(struct ap *A, u32 id)
{
    for (u32 i = 0; i < 2u; i++) if (A->slot[i].valid && A->slot[i].id == id) return &A->slot[i];
#ifdef AP_PURPLE_TEST
    for (u32 i = 0; i < 2u; i++)                       /* PT_TWIN: the standby twin answers the slot's rows */
        if (A->slot[i].valid && (A->slot[i].pt & PT_TWIN) && A->slot[i].id + AP_PT_TWIN == id) return &A->slot[i];
#endif
    return 0;
}
static struct ap_slot *ap_slot_pid(struct ap *A, u32 pid, u32 *standby)
{
    for (u32 i = 0; i < 2u; i++) {
        struct ap_slot *s = &A->slot[i];
        if (!s->valid) continue;
        if (s->pid == pid) { *standby = 0; return s; }
        if (s->sby && s->spid == pid) { *standby = 1; return s; }
    }
    return 0;
}
static int ap_rec_picked(struct ap *A) { return A->picked == (A->cur & 1u) + 1u; }
static int ap_any_picked(struct ap *A) { return (A->picked & 0xFFu) == (A->cur & 1u) + 1u; }
static struct ap_slot *ap_live(struct ap *A) { return A->active ? &A->slot[A->cur & 1u] : 0; }

/* idx with base + idx * stride == row (mod 2^32), or *ok = 0 (res-custom fake_index) */
static u32 ap_fake_index(u32 row, u32 base, u32 stride, u32 *ok)
{
    u32 d = row - base, k = (u32)__builtin_ctz(stride), m = stride >> k;
    *ok = 0;
    if (d & ((1u << k) - 1u)) return 0;
    u32 x = m;
    for (int i = 0; i < 5; i++) x *= 2u - m * x;
    u32 idx = (d >> k) * x;
    if (k) idx &= 0xFFFFFFFFu >> k;
    if (idx * stride != d) return 0;
    *ok = 1;
    return idx;
}

static int ap_key_rate(const char *key, const struct ap_slot *s)
{
    u32 n = 0;
    while (n < 16u && key[n]) n++;
    if (n >= 4u && key[n - 4] == 'C' && key[n - 3] == 'R' && key[n - 2] == 'O' && key[n - 1] == 'P') n -= 4;
    if (n < s->sfx_len) return 0;
    for (u32 i = 0; i < s->sfx_len; i++) if (key[n - s->sfx_len + i] != s->sfx[i]) return 0;
    /* "...23_98" ends with "98"? only the carrier's whole suffix: the char before must not be a digit or '_' */
    if (n > s->sfx_len) { char c = key[n - s->sfx_len - 1u]; if ((c >= '0' && c <= '9') || c == '_') return 0; }
    return 1;
}

/* the frame-rate gates (res-custom ogc_gate G_FRMAX / G_FRCLASS, Bei 2026-10-29): while a slot is live, widen the
 * native limit just enough for its carrier, so the setter is never refused or normalised below it.
 * Ranks: fps x 100 of the internal enums (ogc_layout.RATE_RANKS; 0 = the hidden 15 fps). */
static u32 ap_rank(u32 en)
{
    if (en == 0) return 1500u;
    for (u32 i = 0; i < 9u; i++) if (APC_RATES[i].en == en) return APC_RATES[i].rank;
    return 0xFFFFFFFFu;
}
/* FUN_c04a1120's classes and the fastest enum each allows (res-custom class_max) */
static const uint8_t AP_CLASS_MAX[6] = {7, 3, 1, 5, 2, 6};
static u32 ap_gate(struct ap *A, u32 kind, u32 v)
{
    struct ap_slot *s = ap_live(A);
    if (!s) return v;
    u32 want = ap_rank(s->carrier);
    if (kind == H_FRMAX) return ap_rank(v) < want ? s->carrier : v;
    if (v < 6u && ap_rank(AP_CLASS_MAX[v]) >= want) return v;
    u32 best = v, br = 0xFFFFFFFFu;                        /* the class allowing the carrier with the least widening */
    for (u32 c = 0; c < 6u; c++) {
        u32 r = ap_rank(AP_CLASS_MAX[c]);
        if (r >= want && r < br) { best = c; br = r; }
    }
    return best;
}

static const uint16_t AP_STANDBY_PIDS[6] = {5, 210, 227, 257, 258, 259};   /* isp_custom / imx410_plan PREV_PROFILES */

/* ---- playback (v0.6.0) ------------------------------------------------------------------------------------- */
/* a HUD size tile exists for v: the firmware's 71, or one we registered */
static int ap_tile_ok(const struct ap *A, u32 v)
{
    for (u32 i = 0; i < AP_TILE_NSTOCK; i++) if (AP_TILE_STOCK[i] == v) return 1;
    for (u32 i = 0; i < A->pb.gn; i++) if (A->pb.gval[i] == v) return 1;
    return 0;
}

/* the NBR pack for v (pb_glyph.py's template): the names' digits, the file table key, the digits drawn centred */
static void ap_glyph_build(uint8_t *p, u32 v)
{
    const u32 px = AP_GLYPH_TW * AP_GLYPH_TH * 2u;
    for (u32 i = 0; i < AP_GLYPH_HEAD; i++) p[i] = AP_GLYPH_TPL[i];
    for (u32 i = 0; i < px; i++) p[AP_GLYPH_HEAD + i] = 0;
    for (u32 i = 0; i < AP_GLYPH_TAIL; i++) p[AP_GLYPH_HEAD + px + i] = AP_GLYPH_TPL[AP_GLYPH_HEAD + i];
    uint8_t d[4];
    u32 n = v >= 1000u ? 4u : v >= 100u ? 3u : v >= 10u ? 2u : 1u, x = v;
    for (u32 i = 0; i < 4u; i++) { d[3u - i] = (uint8_t)(x % 10u); x /= 10u; }   /* d = 4 digits, zero-padded */
    const uint8_t *dig = d + 4u - n;
    for (u32 i = 0; i < 4u; i++) p[AP_GLYPH_NAME + 17u + i] = i < n ? (uint8_t)('0' + dig[i]) : 0u;
    for (u32 i = 0; i < 4u; i++) p[AP_GLYPH_FNAME + 4u + i] = (uint8_t)('0' + d[i]);
    u32 h = 0x811C9DC5u;
    for (u32 i = 0; i < 12u; i++) h = (h ^ p[AP_GLYPH_FNAME + i]) * 0x01000193u;
    p[AP_GLYPH_KEY] = (uint8_t)(h >> 24); p[AP_GLYPH_KEY + 1u] = (uint8_t)(h >> 16);
    p[AP_GLYPH_KEY + 2u] = (uint8_t)(h >> 8); p[AP_GLYPH_KEY + 3u] = (uint8_t)h;
    s32 gap = (s32)AP_GLYPH_GAP, tot;
    for (;;) {
        tot = gap * (s32)(n - 1u);
        for (u32 i = 0; i < n; i++) tot += AP_GLYPH_W[dig[i]];
        if (tot <= (s32)AP_GLYPH_TW) break;
        gap--;
    }
    s32 x0 = ((s32)AP_GLYPH_TW - tot) / 2;
    for (u32 i = 0; i < n; i++) {
        u32 w = AP_GLYPH_W[dig[i]];
        const uint8_t *g = AP_GLYPH_ATLAS + AP_GLYPH_OFF[dig[i]];
        for (u32 y = 0; y < AP_GLYPH_TH; y++)
            for (u32 c = 0; c < w; c++) {
                s32 X = x0 + (s32)c;
                if (X < 0 || X >= (s32)AP_GLYPH_TW) continue;
                uint8_t a = g[y * w + c], *q = p + AP_GLYPH_PIX + 2u * (y * AP_GLYPH_TW + (u32)X);
                if (a > q[1]) { q[0] = a; q[1] = a; }                 /* white, L == A (the stock tiles) */
            }
        x0 += (s32)w + gap;
    }
}

/* register v's tile: UI thread, not in a commit (ap_idle).  A pack handed to the firmware is never reused. */
static int ap_glyph_add(struct ap *A, u32 v)
{
    struct ap_pb *P = &A->pb;
    if (ap_tile_ok(A, v)) return 1;
    u32 app = AP_W(AP_GUI_OBJECT);
    if (!P->glyph_on || P->gn >= AP_GLYPHS || !app) { P->gfail++; return -1; }
    uint8_t *pk = A->glyph[P->gn];
    ap_glyph_build(pk, v);
    P->gval[P->gn++] = v;
    u32 reader = 0;
    if (((ap_fw4)AP_NBR_LOAD)(app, (u32)(uintptr_t)pk, AP_GLYPH_PACK_LEN, (u32)(uintptr_t)&reader)) {
        P->gval[P->gn - 1u] = 0; P->gfail++;
        return -1;
    }
    P->glyphs++;
    return 0;
}
static void ap_glyph_want(struct ap *A, u32 v)
{
    struct ap_pb *P = &A->pb;
    if (!v || v > 9999u || ap_tile_ok(A, v)) return;
    for (u32 i = 0; i < P->gqn; i++) if (P->gq[i] == v) return;
    if (P->gqn < 4u) P->gq[P->gqn++] = v;
}

/* The native playback TIFF parser does not retain Compression (0x103).
 * Inspect only IFD0 in v11's existing read buffer. No allocation or image copy. */
static u32 ap_tiff16(const uint8_t *p, u32 be)
{
    return be ? ((u32)p[0] << 8) | p[1] : p[0] | ((u32)p[1] << 8);
}
static u32 ap_tiff32(const uint8_t *p, u32 be)
{
    return be ? (ap_tiff16(p, be) << 16) | ap_tiff16(p + 2, be) :
                ap_tiff16(p, be) | (ap_tiff16(p + 2, be) << 16);
}
static u32 ap_pb_compression(u32 data, u32 bytes)
{
    if (!data || bytes < 8u || bytes > 0x500000u || data > 0xFFFFFFFFu - bytes) return 0;
    const uint8_t *p = (const uint8_t *)(uintptr_t)data;
    u32 be = p[0] == 'M' && p[1] == 'M';
    if ((!be && !(p[0] == 'I' && p[1] == 'I')) || ap_tiff16(p + 2, be) != 42u) return 0;
    u32 off = ap_tiff32(p + 4, be);
    if (off < 8u || off > bytes - 2u) return 0;
    u32 n = ap_tiff16(p + off, be), value = 0, found = 0;
    if (n > 512u || bytes - off - 2u < n * 12u + 4u) return 0;
    for (u32 i = 0; i < n; i++) {
        const uint8_t *e = p + off + 2u + i * 12u;
        if (ap_tiff16(e, be) != 0x103u) continue;
        if (found || ap_tiff16(e + 2, be) != 3u || ap_tiff32(e + 4, be) != 1u) return 0;
        found = 1; value = ap_tiff16(e + 8, be);
    }
    return value;
}

/* after FUN_c05c1a58: the clip's DefaultCropSize (crop), raster (ras), BitsPerSample (read again: the firmware keeps
 * only its enum, 14 -> 4 = RAW8), DefaultScale; a 14-bit clip is handed on as 12-bit (canvas code 8 later) */
static void ap_pb_tag(struct ap *A, u32 context, u32 tiff, u32 crop, u32 ras)
{
    struct ap_pb *P = &A->pb;
    u32 b = 0, r[4] = {0, 0, 0, 0};
    if (!((ap_fw5)AP_PB_BITS16)(tiff, 0u, 0x102u, (u32)(uintptr_t)&b, 0u)) b = 0;
    b &= 0xFFFFu;
    struct ap_pbtag *t = &P->tag[P->tag_next % AP_PB_TAGS];
    P->tag_next++;
    t->cw = AP_W(crop); t->ch = AP_W(crop + 4u); t->rw = AP_W(ras); t->rh = AP_W(ras + 4u); t->bits = b;
    t->ds[0] = t->ds[1] = t->ds[2] = t->ds[3] = 1u;
    if (((ap_fw5)AP_TAG_READ)(tiff, 0u, 0xC61Eu, (u32)(uintptr_t)r, 2u) == 0u && r[0] && r[1] && r[2] && r[3] &&
        r[0] <= 0xFFFFu && r[1] <= 0xFFFFu && r[2] <= 0xFFFFu && r[3] <= 0xFFFFu)
        for (u32 i = 0; i < 4u; i++) t->ds[i] = r[i];
    if (ras >= 0x98u && !(ras & 3u) && context == ras + 0x114u) {
        u32 rw = 0, rh = 0, cr[2] = {0, 0};
        P->owner = ras - 0x98u; P->file = AP_W(P->owner + 0x88u);
        P->valid = 0; P->prepared = 0;
        P->selected = *t;
        /* Re-read with success checks: the native void reader leaves stale
         * output words when a required tag is absent. Never infer row pitch. */
        /* the header binding first: a clip that cannot qualify makes no firmware tag calls */
        if (P->header_owner == P->owner && P->header_file == P->file && P->header_tiff == tiff &&
            P->compression == 1u && (b == 8u || b == 10u || b == 12u || b == 14u) &&
            ((ap_fw5)AP_PB_LONG)(tiff, 0u, 0x100u, (u32)(uintptr_t)&rw, 0u) &&
            ((ap_fw5)AP_PB_LONG)(tiff, 0u, 0x101u, (u32)(uintptr_t)&rh, 0u) &&
            ((ap_fw5)AP_PB_PAIR)(tiff, 0u, 0xC620u, (u32)(uintptr_t)cr, 0u) &&
            rw == t->rw && rh == t->rh && cr[0] == t->cw && cr[1] == t->ch &&
            rw >= 32u && rw <= 6064u && !(rw & 15u) && rh >= 12u && rh <= 4050u && !(rh & 1u) &&
            cr[0] == rw - 16u && cr[1] == rh - 10u) {
            u32 box[6];
            apc_box((u64)t->cw * t->ds[0] * t->ds[3], (u64)t->ch * t->ds[2] * t->ds[1], box);
            P->valid = box[1] && box[2] && box[3] && box[4];
        }
    }
    if (b == 14u && P->mode && (P->mode != 2u || ap_live(A)) &&
        (!P->block || (P->valid && P->owner + 0x98u == ras))) {
        AP_W(ras + 0x10u) = AP_PB14_EN; P->fix14++;
    }
    P->tags++;
}

/* Prepare only the clip v11 actually read, before either one-frame or stream
 * decoding allocates buffers. Index browsing cannot replace this snapshot. */
static int ap_pb_selected(const struct ap *A, u32 obj)
{
    const struct ap_pb *P = &A->pb;
    const struct ap_pbtag *t = &P->selected;
    if (!P->valid || !obj || (obj & 3u) || obj != P->owner || AP_W(obj + 0x88u) != P->file) return 0;
    u32 en = t->bits == 8u ? 4u : t->bits == 10u ? 3u : 0u;
    return AP_W(obj + 0x98u) == t->rw && AP_W(obj + 0x9Cu) == t->rh &&
           AP_W(obj + 0x54u) == t->cw && AP_W(obj + 0x58u) == t->ch && AP_W(obj + 0xA8u) == en;
}

/* v1: a clip the stock playback reads -- the raster of one of its twelve movie profiles (DCI4K / UHD / FHD / HD crop
 * + 16 / + 10) and an 8 / 10 / 12-bit BitsPerSample (14 reads as RAW8).  Anything else is refused. */
static const uint16_t AP_PB_STOCK_RAS[4][2] = {{4112u, 2170u}, {3856u, 2170u}, {1936u, 1090u}, {1296u, 730u}};
static int ap_pb_blocked(const struct ap *A, u32 rw, u32 rh)
{
    const struct ap_pb *P = &A->pb;
    u32 stock = 0;
    for (u32 i = 0; i < 4u; i++) if (rw == AP_PB_STOCK_RAS[i][0] && rh == AP_PB_STOCK_RAS[i][1]) stock = 1;
    if (!stock) return 1;
    for (u32 k = 0; k < AP_PB_TAGS && k < P->tags; k++) {            /* newest first: this raster's bits */
        const struct ap_pbtag *t = &P->tag[(P->tag_next - 1u - k) % AP_PB_TAGS];
        if (t->rw == rw && t->rh == rh) return !(t->bits == 0u || t->bits == 8u || t->bits == 10u || t->bits == 12u);
    }
    return 0;
}

/* a movie-playback canvas (+0x80 bit 16): the clip's geometry when the stock profile is not it (RES-Custom's 13
 * playback pairs, OG3K_PLAYBACK_PROFILE_CLASSES §14: the raster must be the file's row pitch) */
static void ap_pb_canvas(struct ap *A, u32 c)
{
    struct ap_pb *P = &A->pb;
    P->active = 0;
    if (!P->mode || !P->seq || (P->mode == 2u && !ap_live(A))) return;
    u32 cw = P->cw, ch = P->ch, rw = cw + 16u, rh = ch + 10u, bits = 0, ds[4] = {1u, 1u, 1u, 1u};
    if (P->block) {
        const struct ap_pbtag *t = &P->selected;
        if (!P->prepared || !ap_pb_selected(A, P->prepared) || t->cw != cw || t->ch != ch) return;
        rw = t->rw; rh = t->rh; bits = t->bits;
        for (u32 i = 0; i < 4u; i++) ds[i] = t->ds[i];
    } else for (u32 k = 0; k < AP_PB_TAGS && k < P->tags; k++) {     /* legacy diagnostic mode: newest first */
        const struct ap_pbtag *t = &P->tag[(P->tag_next - 1u - k) % AP_PB_TAGS];
        if (t->cw == cw && t->ch == ch) {
            rw = t->rw; rh = t->rh; bits = t->bits;
            for (u32 i = 0; i < 4u; i++) ds[i] = t->ds[i];
            break;
        }
    }
    if (rw < cw || rh < ch || rw > 8192u || rh > 8192u || !cw || !ch) return;
    u32 c80 = AP_W(c + 0x80u), code = bits == 14u ? 8u : (c80 & 0xFFu);
    if (AP_W(c + 0x0Cu) == rw && AP_W(c + 0x10u) == rh && AP_W(c + 0x20u) == cw && AP_W(c + 0x28u) == ch &&
        (c80 & 0xFFu) == code && (u64)ds[0] * ds[3] == (u64)ds[2] * ds[1]) {
        P->skips++; return;                                  /* square pixels and the stock profile fits */
    }
    u32 b[6];
    apc_box((u64)cw * ds[0] * ds[3], (u64)ch * ds[2] * ds[1], b);
    if (!b[0]) AP_W(c + 0x1Cu) = 2u;
    AP_W(c + 0x0Cu) = rw; AP_W(c + 0x10u) = rh; AP_W(c + 0xD8u) = rw; AP_W(c + 0xE0u) = rh;
    AP_W(c + 0xF4u) = rw; AP_W(c + 0xF8u) = rh;
    AP_W(c + 0x20u) = cw; AP_W(c + 0x28u) = ch;
    AP_W(c + 0x60u) = 1024u; AP_W(c + 0xD0u) = 1024u; AP_W(c + 0x64u) = 1024u; AP_W(c + 0xD4u) = 1024u;
    if (code != (c80 & 0xFFu)) AP_W(c + 0x80u) = (c80 & ~0xFFu) | code;
    P->is169 = b[0]; P->asp[0] = b[1]; P->asp[1] = b[2]; P->box_w = b[3]; P->box_h = b[4]; P->det_h = b[5];
    P->ras_w = rw; P->ras_h = rh; P->bits = bits;
    ap_dmb();
    P->active = 1;
    P->patches++;
}

/* the LV descriptor template for (stock d: w x h) -> nw x nh, cached in tp[0..3] */
static u32 ap_out_tpl(struct ap_tpl *tp, u32 d, u32 w, u32 h, u32 nw, u32 nh)
{
    struct ap_tpl *t = 0;
    for (u32 i = 0; i < 4u && !t; i++) if (tp[i].used && tp[i].from == d) t = &tp[i];
    for (u32 i = 0; i < 4u && !t; i++) if (!tp[i].used) t = &tp[i];
    if (!t) return 0;
    if (!t->used || t->w != w || t->h != h || t->words[0] != nw || t->words[1] != nh) {
        t->used = 0; ap_dmb();
        for (u32 i = 0; i < 11u; i++) t->words[i] = AP_W(d + 4u * i);
        t->words[0] = nw; t->words[4] = nw; t->words[1] = nh; t->words[5] = nh;
        t->w = w; t->h = h; t->from = d; ap_dmb(); t->used = 1;
    }
    return (u32)(uintptr_t)t->words;
}

/* ---- v0.7.27test: the first recorded frames, traced (notes/FIRST_FRAME_SENSOR_RESET.md §5 step 1) ---------- *
 * Read-only diagnosis of the 1x2 first-frame +1 row: is frame 1 already shifted at BUFA1's completion, or does it go
 * wrong between the completion and the writer?  Nothing is dropped or moved (v0.7.26test's drop / repair are gone).
 *   arm   ContSet_Adr1, BUFA1 branch, before FUN_c0631b98(dest) / the start (task): the per-take sentinel (16 xorshift32
 *         words) into raster row 0's LAST 64 B through the uncached alias after a full D-clean -- a frame BUFA1 shifts
 *         therefore carries the sentinel there instead of stale DRAM -- then record 0 of the take's trace.
 *   done  FUN_c031bca0 entry (BUFA1's completion callback, called from the IRQ handler FUN_c0630d60 with the
 *         completed raster, uncached): plain loads and stores only -- no firmware call, no cache operation.
 *   write FUN_c038bd98's frame lookup C038BDB4 (SRecRaw), before cineCapture / the header DMA / the enqueue / Lossless.
 * Records: the raw timer (timer5 count + the tick's software epoch: what C002B4E0 reads, without its IRQ masking),
 * TG frame / line / status, the raster and a digest read through the UNCACHED alias (row 0 head 32 B and tail 64 B, row
 * 1 head 32 B, the last row's tail 32 B).  AP_TR_FRAMES completions and AP_TR_FRAMES writer arrivals per take, in a
 * fixed ring in struct ap; only for a take armed in the live slot's mode (stock never). */
#define AP_FF_WORDS   16u             /* 64 bytes */
#define AP_FF_RAS     0x4Cu           /* frame +0x4C: its raster (FUN_c0378a50: = desc +0x30 -> ContSet_Adr1 +0x38) */
#define AP_FF_AT(ras, row) ((ras) + (row) - 4u * AP_FF_WORDS)   /* the sentinel: row 0's last 64 bytes */
#define AP_TR_FRAMES  4u
#define AP_TR_N       (1u + 2u * AP_TR_FRAMES + 3u)   /* arm + 4 completions + 4 writer arrivals + room */
#define AP_TR_MAGIC   0x52544653u     /* "SFTR" */
#define AP_TR_VER     1u
#define AP_TMR_BASEP  0xC30337F0u     /* -> the timer block (2D810000); timer 5's count at +0x54 (C00165E8) */
#define AP_TMR_EPOCH  0xC30781A4u     /* the tick's software epoch (+1 per timer callback, C002B820) */
enum { AP_TR_ARM = 1, AP_TR_DONE = 2, AP_TR_WRITE = 3 };
_Static_assert(AP_TR_N == sizeof(((struct ap_trace *)0)->r) / sizeof(struct ap_trec), "trace ring");

static u32 ap_ff_next(u32 x) { x ^= x << 13; x ^= x >> 17; x ^= x << 5; return x; }   /* never 0 from x != 0 */

/* the uncached 0x4... alias of [p, p + bytes) in DRAM (0x4... or the cached 0xC...), 4-aligned; 0 = not one */
static u32 ap_ff_unc(u32 p, u32 bytes)
{
    u32 u = p >= 0xC0000000u ? p - SL_ALIAS : p;
    if (u < 0x40000000u || u >= 0x80000000u || (u & 3u) || bytes > 0x80000000u - u) return 0;
    return u;
}

static void ap_tr_words(u32 *d, u32 a, u32 n)            /* n words from the uncached a: loads only */
{
    const volatile u32 *s = (const volatile u32 *)(uintptr_t)a;
    for (u32 i = 0; i < n; i++) d[i] = s[i];
}

/* the next record of the take, or 0 (full / not tracing).  The IRQ site needs no masking (nothing preempts it here);
 * the task sites take the slot with IRQs off (an inline cpsid, no call) */
static struct ap_trec *ap_tr_slot(struct ap *A, u32 kind, u32 ras)
{
    struct ap_trace *T = &A->tr;
    if (T->n >= AP_TR_N) { T->lost++; return 0; }
    struct ap_trec *r = &T->r[T->n];
    r->kind = kind; r->seq = T->n;
    T->n++;
    r->ras = ras;
    u32 base = AP_W(AP_TMR_BASEP);
    r->epoch = AP_W(AP_TMR_EPOCH); r->raw = base ? AP_W(base + 0x54u) : 0u;
    r->tg_frame = AP_W(0x30100588u); r->tg_line = AP_W(0x30100590u); r->tg_flags = AP_W(0x3010058Cu);
    u32 row = T->row, rows = T->rows, u = ap_ff_unc(ras, row * rows);
    r->ok = u ? 1u : 0u;
    if (u) {
        ap_tr_words(r->head0, u, 8u);
        ap_tr_words(r->tail0, AP_FF_AT(u, row), 16u);
        ap_tr_words(r->head1, u + row, 8u);
        ap_tr_words(r->tailn, u + row * rows - 32u, 8u);
    }
    return r;
}

/* ContSet_Adr1, BUFA1 branch, before FUN_c0631b98(dest) and the start FUN_c0631c08(1): d = desc - 8 (task) */
__attribute__((noinline)) static void ap_ff_arm(struct ap *A, u32 dest, u32 d)
{
    A->ff.state = 0;                                         /* a take start always ends the previous one's */
    A->tr.live = 0;
    ap_dmb();
    struct ap_slot *s = ap_live(A);
    if (!s || !d || (d & 3u) || AP_W(d + 0x1Cu) != s->id) return;          /* stock modes: untouched */
    u32 fmt = AP_W(d + 0x20u), bits = fmt == 0u ? 12u : fmt == 1u ? 14u : 0u;   /* FUN_c0630e90: w*3/8, w*7/16 words */
    u32 w = s->rec_w, rows = s->rec_h, row = (w * bits) >> 3, ras = 0;
    if (bits && w && w <= 8192u && !((w * bits) & 31u) && row >= 4u * AP_FF_WORDS && rows >= 4u && rows <= 8192u)
        ras = ap_ff_unc(dest, row * rows);
    if (!ras) { A->ff_skips++; return; }
    u32 seed = (ap_now_us() ^ 0x5346F11Eu ^ (A->ff_arms * 0x9E3779B9u)) | 1u;
    ((ap_fw0)AP_DCACHE)();                                   /* no dirty line left to land on the sentinel / the DMA */
    volatile u32 *p = (volatile u32 *)(uintptr_t)AP_FF_AT(ras, row);
    u32 x = seed;
    for (u32 i = 0; i < AP_FF_WORDS; i++) { x = ap_ff_next(x); p[i] = x; }
    __asm volatile("dsb sy" ::: "memory");                   /* in DRAM before the DMA is started */
    A->ff.ras = ras; A->ff.row = row; A->ff.rows = rows; A->ff.seed = seed; A->ff.id = s->id;
    struct ap_trace *T = &A->tr;                             /* a new take's trace (nothing traces it yet: live 0) */
    T->magic = AP_TR_MAGIC; T->ver = AP_TR_VER; T->rec_words = sizeof(struct ap_trec) / 4u; T->nmax = AP_TR_N;
    T->n = 0; T->lost = 0; T->done = 0; T->writes = 0; T->take++;
    T->seed = seed; T->row = row; T->rows = rows; T->id = s->id;
    struct ap_trec *r = ap_tr_slot(A, AP_TR_ARM, dest);
    if (r) {
        r->us = ap_now_us();
        r->x[0] = s->id; r->x[1] = AP_W(0x30182210u); r->x[2] = AP_W(0x30182214u); r->x[3] = AP_W(0x30182218u);
#ifdef AP_REC_DELAY_TEST
        struct ap_rd *R = A->rd;                             /* the REC start's record: its first arm */
        if (R && R->n) { struct ap_rdrec *q = &R->r[(R->n - 1u) & (AP_RD_N - 1u)];
                         if (!q->arm_us) { q->arm_us = r->us ? r->us : 1u; q->arm_line = r->tg_line; } }
#endif
    }
    ap_dmb();
    T->live = 1u;
    A->ff.state = 1u;
    A->ff_arms++;
}

/* FUN_c031bca0 entry: BUFA1's completion callback, IRQ (FUN_c0630d60).  Plain loads / stores only. */
__attribute__((noinline)) static void ap_tr_done(struct ap *A, u32 ras)
{
    struct ap_trace *T = &A->tr;
    struct ap_slot *s = ap_live(A);
    if (!T->live || T->done >= AP_TR_FRAMES || !s || s->id != T->id) return;
    struct ap_trec *r = ap_tr_slot(A, AP_TR_DONE, ras);
    T->done++;
    if (!r) return;
    r->us = 0;                                               /* no tick call here: epoch / raw only */
    r->x[0] = AP_W(0x301821E8u); r->x[1] = AP_W(0x30182280u); r->x[2] = T->done; r->x[3] = AP_W(0x30182048u);
}

/* FUN_c038bd98 (SRecRaw): fr = the arriving frame.  The first arrival of an armed take is checked (counted only). */
__attribute__((noinline)) static void ap_tr_write(struct ap *A, u32 fr)
{
    struct ap_trace *T = &A->tr;
    struct ap_slot *s = ap_live(A);
    u32 ras = fr && !(fr & 3u) ? AP_W(fr + AP_FF_RAS) : 0u;
    if (A->ff.state == 1u) {
        A->ff.state = 0;
        if (!s || s->id != A->ff.id || !ras || ap_ff_unc(ras, A->ff.row * A->ff.rows) != A->ff.ras) {
            A->ff_miss++;                                    /* not the armed frame (or no slot) */
        } else {
            A->ff_checks++;
            const volatile u32 *p = (const volatile u32 *)(uintptr_t)AP_FF_AT(A->ff.ras, A->ff.row);
            u32 x = A->ff.seed, intact = 1u;
            for (u32 i = 0; i < AP_FF_WORDS; i++) { x = ap_ff_next(x); if (p[i] != x) intact = 0; }
            if (intact) A->ff_intact++; else A->ff_ok++;     /* intact: BUFA1 never wrote row 0's end (shifted) */
#ifdef AP_REC_DELAY_TEST
            if (A->rd && A->rd->n) A->rd->r[(A->rd->n - 1u) & (AP_RD_N - 1u)].ff = intact ? 1u : 2u;
#endif
        }
    }
    if (!T->live || T->writes >= AP_TR_FRAMES || !s || s->id != T->id) return;
    u32 irq = ap_irq_off();
    struct ap_trec *r = ap_tr_slot(A, AP_TR_WRITE, ras);
    T->writes++;
    if (T->done >= AP_TR_FRAMES && T->writes >= AP_TR_FRAMES) T->live = 0;
    ap_irq_restore(irq);
    if (!r) return;
    r->us = ap_now_us();
    r->x[0] = fr ? AP_W(fr + 0x10FCu) : 0u; r->x[1] = fr; r->x[2] = T->writes; r->x[3] = 0;
}

/* ---- v0.7.28test: the firmware's own sensor pause / resume + link resync once at REC start ------------------ *
 * (notes/FIRST_FRAME_SENSOR_RESET.md §2, option B; validation/20261104-first-frame-resync).  Right after ContSet_Adr1's
 * SetImgMode_s (the mode table + 0011 0->1) into the live slot's mode, exactly what the native long-exposure loops do
 * (FUN_c0318490 / C031D0E0 / C0316xxx): XC_ImageSensorIMX410 v27(1) (00CA=0, 1 ms, 0000=shadow|2, 00C6=1, 00C5=0x11,
 * GPIO 0x544 = 1), a VD, v27(0) (0000=shadow&~2, GPIO 0x544 = 0, 12 ms, 00C6=0, 00C5=0, 00CA=1, 1 ms, v21 link resync),
 * a VD.  All through the imager's vtable (+0xD0 table +0x74 = v27 C0325110, which keeps the 0000 shadow itself).
 * v27 does nothing when the frame period C0125CA8() <= 15000 us (> ~66.7 fps): counted as a skip, nothing called. */
#define AP_RS_IMGR    0xC0322E48u     /* (0) -> the imager (XC_ImageSensorIMX410) */
#define AP_RS_V27     0xC0325110u     /* XC_ImageSensorIMX410 v27(obj, suspend) */
#define AP_RS_PERIOD  0xC0125CA9u     /* Thumb: the frame period, us (v27's own guard) */
#define AP_RS_VD      0xC01269A9u     /* Thumb: wait for the next VD (ContSet_Adr1's and the long-exposure loops') */
#define AP_RS_MIN_US  15000u

#ifndef AP_RESYNC
#define AP_RESYNC 0   /* v0.7.32test: off in the product; validation/20261104-resync-review (no fix seen, +50-80 ms REC start) */
#endif
__attribute__((noinline)) static void ap_resync(struct ap *A)
{
    if (!AP_RESYNC) { A->rs_skips++; A->rs_last = 3u; return; }   /* 3: switched off (the hooks still count) */
    u32 obj = ((ap_fw1)AP_RS_IMGR)(0), vt = obj ? AP_W(obj + 0xD0u) : 0u;
    if (!vt || AP_W(vt + 0x74u) != AP_RS_V27) { A->rs_skips++; A->rs_last = 2u; return; }   /* not the IMX410 v27 */
    if (((ap_fw0)AP_RS_PERIOD)() <= AP_RS_MIN_US) { A->rs_skips++; A->rs_last = 1u; return; } /* v27 would no-op */
    u32 t0 = ap_now_us();
    ((ap_fw2)AP_RS_V27)(obj, 1u);
    ((ap_fw0)AP_RS_VD)();
    ((ap_fw2)AP_RS_V27)(obj, 0u);
    ((ap_fw0)AP_RS_VD)();
    A->rs_calls++; A->rs_last = 0u;
    A->rs_us = ap_now_us() - t0;
}

/* ---- the one handler ------------------------------------------------------------------------------------- *
 * f = the frame (r0..r12, lr).  0: go down with f; 1: return ("ret") with f. */
/* v0.7.20: the playing clip's display pair while our playback canvas is up (not 16:9, both terms set), else 0 */
static const u32 *ap_pb_pair(const struct ap *A)
{
    const struct ap_pb *P = &A->pb;
    return P->active && !P->is169 && P->asp[0] && P->asp[1] ? P->asp : 0;
}

static u32 ap_hook(struct ap *A, u32 *f, u32 id)
{
    if (id < H_LK_R10 || id == H_LK_R10) {                          /* the eight lookups: (obj, mode id) */
        struct ap_slot *s = ap_slot_id(A, f[1]);
        if (!s) return 0;
#ifdef AP_PURPLE_TEST
        if (s->pt & PT_ROWS) { f[1] = s->smode; A->lookups++; return 0; }   /* the firmware's own scan: the stock row */
#endif
        if (id == H_LK_R10) { f[0] = s->r10; A->lookups++; return 1; }
        u32 desc = AP_W(f[0]), ok = 0;
        if (!desc || !s->row[id]) return 0;
        u32 idx = ap_fake_index(s->row[id], AP_W(desc + TB_FIELD[id]), TB_STRIDE[id], &ok);
        if (!ok) return 0;
        f[0] = idx; A->lookups++;
        return 1;
    }
    switch (id) {
    case H_AC38: {                                                   /* copies mode r2's 0x5C row into r0 */
        struct ap_slot *s = ap_slot_id(A, f[2]);
        if (!s || !s->zok) return 0;
        ap_copy((void *)(uintptr_t)f[0], s->zrow, Z_STRIDE);
#ifdef AP_PURPLE_TEST
        AP_W(f[0]) = f[2];                                           /* the asked id (the twin's too) */
#endif
        return 1;
    }
    case H_ACD8: {                                                   /* its inline scan sees the donor */
        struct ap_slot *s = ap_slot_id(A, f[3]);
        if (s) f[3] = s->donor;
        return 0;
    }
    case H_ZG: {                                                     /* bl c03212f8 -> the current mode: the donor */
        u32 r = ((ap_fw4)A->ven[id][V_DOWN])(f[0], f[1], f[2], f[3]);
        struct ap_slot *s = ap_slot_id(A, r);
        f[0] = s ? s->donor : r;
        return 1;
    }
    case H_V32:                                                      /* our ids: the REG row has the window */
        return ap_slot_id(A, AP_W(f[0] + 4)) ? 1u : 0u;
    case H_PICK: {
        struct ap_slot *s = ap_live(A);
        {   /* v0.7.35test (boot apply): a standby LV start, ours or stock -- only counted here; ap_boot_ready reads it */
            const char *m = (const char *)(uintptr_t)f[2];
            if (f[1] == AP_TABS && m && m[0] == 'M' && m[1] == 'O' && m[2] == 'V') { A->lv_seen++; A->pb_since = 0; }
        }
        u32 tb = f[1] == AP_TAB3 ? 12u : f[1] == AP_TAB2 ? 10u : f[1] == AP_TAB1 ? 8u : 0u;
        if (s && tb && f[2] && ap_key_rate((const char *)(uintptr_t)f[2], s)) {
            /* the live test (10-30): standby asks THIS table too (the CinemaDNG route, FUN_c043b828).  v0.7.2test: the
             * answer never depends on busy(): v0.7.1test gave a gated standby the stock route and recording ours, so
             * REC start switched the readout outside a commit's LV stop / start and froze the camera (live2 item 14).
             * A selection standby cannot run is refused at the commit (AP_E_STANDBY) instead. */
            if (!ap_busy()) A->standby_picks++;
            A->picked = (A->cur & 1u) + 1u; A->picks++;
            A->pick_bits = tb;                                       /* 0.0.3test: the canvas takes its plane codes */
            if (tb != 12u) A->low_picks++;
            f[0] = (u32)(uintptr_t)s->entry;
            return 1;
        }
        /* the standby LV ("MOV..."; the magnifier "MAG..." keeps the stock mode 10) */
        const char *k = (const char *)(uintptr_t)f[2];
        if (s && s->sby && f[1] == AP_TABS && k && k[0] == 'M' && k[1] == 'O' && k[2] == 'V'
#ifdef AP_PURPLE_TEST
            && !(s->pt & PT_SBSTOCK)                                 /* the stock standby: profile 5, mode 8 */
#endif
            ) {
            A->picked = 0x100u | ((A->cur & 1u) + 1u); A->standby_picks++;
            f[0] = (u32)(uintptr_t)s->sentry;
            return 1;
        }
        A->picked = 0;
        return 0;
    }
    case H_VPRO: {                                                   /* r5 = pid, r1 = mapping[pid] */
        u32 sb;
        struct ap_slot *s = ap_slot_pid(A, f[5], &sb);
        if (!s) return 0;
        f[1] = sb ? s->sbase_row : s->base_row;
        return 1;
    }
    case H_CANVAS: {                                                 /* r4 = holder (canvas +0x5C), r5 = pid */
        u32 c = f[4] + 0x5Cu, pid = f[5];
        u32 sb;
        if (AP_W(c + 0x80u) & 0x10000u) { A->pb.pbc = 1u; ap_pb_canvas(A, c); return 0; }   /* movie playback class */
        A->pb.active = 0; A->pb.pbc = 0;                             /* any other canvas: playback is over */
        struct ap_slot *s = ap_slot_pid(A, pid, &sb);
        if (s) {
            const u32 *m = sb ? s->smask : s->mask;
#ifdef AP_PURPLE_TEST
            /* PT_RWZM: the record canvas keeps the base row's (stock UHD) raster +00/04/DC/E4, crop +24/2C, RWZM +64/D4 */
            u32 keep = !sb && (s->pt & PT_RWZM) ? (1u << 0) | (1u << 1) | (1u << 9) | (1u << 11) | (1u << 25) : 0u;
            u32 keep2 = !sb && (s->pt & PT_RWZM) ? (1u << (0x35 - 32)) | (1u << (0x37 - 32)) | (1u << (0x39 - 32)) : 0u;
            for (u32 i = 0; i < 65u; i++)
                if ((m[i >> 5] >> (i & 31u) & 1u) && !((i < 32u ? keep : i < 64u ? keep2 : 0u) >> (i & 31u) & 1u))
                    AP_W(c + 4u * i) = s->isp[i];
            if (s->pt & PT_ROWS) { AP_W(c + 0xF4u) = s->meta[0]; AP_W(c + 0xF8u) = s->meta[1]; }   /* the stock META */
#else
            for (u32 i = 0; i < 65u; i++) if (m[i >> 5] >> (i & 31u) & 1u) AP_W(c + 4u * i) = s->isp[i];
#endif
            /* 0.0.3test: an 8 / 10-bit table's record carries that depth's plane codes, as the stock profiles of
             * TAB1 / TAB2 do (core R7 / res-custom ogc_canvas: 8 = 10/10, 10 = 10/9); the readout is the slot's. */
            if (!sb && (A->pick_bits == 8u || A->pick_bits == 10u)) {
                AP_W(c + 0x80u) = 10u; AP_W(c + 0x84u) = A->pick_bits == 8u ? 10u : 9u;
            }
            if (s->sclamp && (sb || !ap_busy())) {             /* v0.7.1test: standby, the visible at the cap */
                AP_W(c + 0x20u) = s->sv[0]; AP_W(c + 0x28u) = s->sv[1];
                AP_W(c + 0x0Cu) = s->sr[0]; AP_W(c + 0x10u) = s->sr[1];
            }
            AP_W(c + 0x30u) = s->engine;
            A->canvases++;
            return 0;
        }
        s = ap_live(A);
        if (s && s->sb_w)
            for (u32 i = 0; i < 6u; i++)
                if (pid == AP_STANDBY_PIDS[i]) { AP_W(c + 0x20u) = s->sb_w; AP_W(c + 0x28u) = s->sb_h; break; }
        return 0;
    }
    case H_GS: {                                                     /* our canvases are "raw movie" */
        u32 c = AP_W(AP_LV_MGR + 8u);
        u32 sb;
        if (!c || !ap_slot_pid(A, AP_W(c), &sb) || sb) return 0;
        f[0] = 1;
        return 1;
    }
    case H_RECRATE: {                                                /* the native rational first, then ours */
        u32 out = f[0];
        u32 r = ((ap_fw4)A->ven[id][V_DOWN])(f[0], f[1], f[2], f[3]);
        struct ap_slot *s = ap_live(A);
        if (s && ap_rec_picked(A) && out && !(out & 3u) && AP_W(out + 4u) && AP_W(out) <= 0x01000000u) {
            u32 got = (u32)apc_div((u64)AP_W(out) * 100u, AP_W(out + 4u));
            if (got + 1u >= s->rank && got <= s->rank + 1u) { AP_W(out) = s->dng_n; AP_W(out + 4u) = s->dng_d; A->recrates++; }
        }
        f[0] = r;
        return 1;
    }
    case H_BINPATH: {                                                /* the selector, then branch C's second /3 */
        u32 in = f[1], o = f[2];
        u32 r = ((ap_fw4)A->ven[id][V_DOWN])(f[0], f[1], f[2], f[3]);
        struct ap_slot *s = ap_live(A);
        u32 cfg = s && ap_rec_picked(A) ? s->binfilt : 0;
        if (cfg && AP_W(in + 0x10u) == ((cfg & 0x200u) ? 3u : 1u) && AP_W(in + 0x14u) == ((cfg & 0x400u) ? 3u : 1u)) {
            if (AP_W(o + 8u) == 4u && AP_W(in + 0x10u) == 3u && AP_W(o + 0x24u) == 3u) AP_W(o + 0x24u) = 1u;
            AP_W(o + 0x48u) = (cfg >> 8) & 1u;
        }
        f[0] = r;
        return 1;
    }
    case H_BINK1: case H_BINK2: {                                    /* res-custom ogc_binkernel, r1 = the driver */
        struct ap_slot *s = ap_live(A);
        u32 cfg = s && ap_rec_picked(A) ? s->binfilt : 0, drv = f[1], k, side, mid;
        if (!cfg) return 0;
        if (cfg & 0x200u) {
            k = cfg & 7u;
            side = k == 0 ? 21u : k == 1 ? 16u : k == 2 ? 11u : k == 3 ? 8u : k == 4 ? 4u : 0u;
            mid = 64u - 2u * side;
            AP_B8(drv + 0x29u) = (uint8_t)side; AP_B8(drv + 0x2Au) = (uint8_t)mid; AP_B8(drv + 0x2Bu) = (uint8_t)side;
            for (u32 i = 0; i < 4u; i++) {
                AP_B8(drv + 0x1Cu + 3u * i) = (uint8_t)side; AP_B8(drv + 0x1Du + 3u * i) = (uint8_t)mid;
                AP_B8(drv + 0x1Eu + 3u * i) = (uint8_t)side;
            }
        }
        if (cfg & 0x400u) {
            k = (cfg >> 4) & 7u;
            side = k == 0 ? 1365u : k == 1 ? 1024u : k == 2 ? 683u : k == 3 ? 512u : k == 4 ? 256u : 0u;
            mid = 4096u - 2u * side;
            for (u32 i = 0; i < 3u; i++) {
                volatile uint16_t *v = (volatile uint16_t *)(uintptr_t)(drv + 8u + 6u * i);
                v[0] = (uint16_t)side; v[1] = (uint16_t)mid; v[2] = (uint16_t)side;
            }
        }
        return 0;
    }
    case H_OUT: {                                                    /* (pairs, idx) -> the LV descriptor */
        struct ap_slot *s = ap_live(A);
        struct ap_pb *P = &A->pb;
        u32 idx = f[1], bw, bh, dh, picked;
        struct ap_tpl *tp;
        if (idx != 0 && idx != 2u) return 0;
        if (P->active) {                                             /* playback: the clip's shape, not the slot's */
            if (P->is169) return 0;
            bw = P->box_w; bh = P->box_h; dh = P->det_h; picked = 1; tp = P->tpl;
        } else {
            if (!s || s->is169 || P->pbc) return 0;                  /* v0.7.0test: a stock playback canvas stays stock */
            picked = ap_any_picked(A);
            bw = s->box_w; bh = s->box_h; dh = s->det_h; tp = s->tpl;
        }
        u32 d = AP_W(f[0] + 8u * idx);
        if (d < 0xC0000000u || d >= 0xC4000000u) return 0;
        u32 w = AP_W(d), h = AP_W(d + 4u), nw, nh;
        if (idx == 0 && w == 1620u && (h == 911u || (picked && h == 1080u))) { nw = bw; nh = bh; }
        else if (idx == 2u && w == 320u && dh && (h == 180u || (picked && h == 213u))) { nw = 320u; nh = dh; }
        else return 0;
        u32 t = ap_out_tpl(tp, d, w, h, nw, nh);
        if (!t) return 0;
        if (P->active) P->outs++;
        f[0] = t;
        return 1;
    }
    case H_ASP1: case H_ASP2: {                                      /* W71C1 v2: the YUV aspect only */
        struct ap_slot *s = ap_live(A);
        if (A->pb.active) {                                          /* v0.7.20: our playback canvas -> the clip's */
            if (!ap_pb_pair(A)) return 0;                            /* 16:9: stock movie playback fits it already */
            f[0] = AP_ASPECT_ENUM;
            return 1;
        }
        if (!s || s->is169 || A->pb.pbc) return 0;                  /* a stock playback canvas keeps the stock fit */
        f[0] = AP_ASPECT_ENUM;
        return 1;
    }
    case H_YUV32: {                                                /* W v2's other LCD branch, never W v4/RGB */
        struct ap_slot *s = ap_live(A);
        if (A->pb.active) {
            if (!ap_pb_pair(A)) return 0;
            f[0] = AP_ASPECT_ENUM;
            return 1;
        }
        if (!s || A->pb.pbc) return 0;
        /* This site normally requests 3:2, unlike H_ASP1/2's 16:9.
         * An exact 16:9 slot still needs enum 3 here; enum 9 is ours only for non-16:9. */
        f[0] = s->is169 ? 3u : AP_ASPECT_ENUM;
        return 1;
    }
    case H_YUV_FALLBACK: {                                         /* native W v2 fallback; never W v4/RGB */
        struct ap_slot *s = ap_live(A);
        if (A->pb.active) {
            const u32 *pp = ap_pb_pair(A);
            if (!pp) return 0;
            f[1] = (u32)(uintptr_t)pp;
            return 1;
        }
        if (!s || A->pb.pbc) return 0;
        /* The fallback passed a stack copy of source dimensions to the stock aspect classifier.
         * Use this commit's owned pair, as in the other YUV branches: H_FIT can then preserve it.
         * Do not cache a slot pointer across adjustments, nor change the RGB/UI classifier. */
        f[1] = (u32)(uintptr_t)s->asp;
        return 1;
    }
    case H_FIT: {                                                  /* native integer fit, without snapping our pair */
        struct ap_slot *s = ap_live(A);
        const u32 *pair = A->pb.active ? ap_pb_pair(A) :
                          (!s || s->is169 || A->pb.pbc) ? 0 : s->asp;
        if (!pair || f[11] != (u32)(uintptr_t)pair) return 0;
        f[6] = pair[0]; f[7] = pair[1];
        return 0;                                                  /* replay movw lr: the following movt needs it */
    }
    case H_FRMAX:                                                    /* r4 -> r1 (the displaced mov follows) */
        f[4] = ap_gate(A, H_FRMAX, f[4]);
        return 0;
    case H_FRCLASS:                                                  /* r1 -> r0 */
        f[1] = ap_gate(A, H_FRCLASS, f[1]);
        return 0;
    case H_BLK6: case H_BLK: {                                       /* the bits of the BlackLevel shift */
        u32 r = ((ap_fw4)A->ven[id][V_DOWN])(f[0], f[1], f[2], f[3]);
        struct ap_slot *s = ap_live(A);
        if (s && s->rec14 && ap_rec_picked(A) && A->pick_bits == 12u) { r = 14u; A->blacks++; }   /* 0.0.3test: TAB3 only */
        f[0] = r;
        return 1;
    }
    case H_PBHEADER: {
        struct ap_pb *P = &A->pb;
        u32 obj = f[4], out = f[0];
        P->valid = 0; P->prepared = 0; P->header_tiff = 0; P->compression = 0;
        P->header_owner = obj; P->header_file = obj && !(obj & 3u) ? AP_W(obj + 0x88u) : 0;
        if (obj && !(obj & 3u) && f[3] == 2u && f[14] == 0u)
            P->compression = ap_pb_compression(f[1], f[2]);
        ((ap_fw5)A->ven[id][V_DOWN])(f[0], f[1], f[2], f[3], f[14]);
        if (out && !(out & 3u)) P->header_tiff = AP_W(out);
        return 1;
    }
    case H_PBTAG: {                                                  /* (_, tiff, crop out, raster out): after it */
        u32 tiff = f[1], crop = f[2], ras = f[3];
        A->pb_since = 1;                                             /* v0.7.35test: playback since the last LV */
        ((ap_fw4)A->ven[id][V_DOWN])(f[0], f[1], f[2], f[3]);
        if (tiff && crop && ras) ap_pb_tag(A, f[0], tiff, crop, ras);
        return 1;
    }
    case H_PBRING:
        /* The native loop stops only when allocation returns NULL; small files
         * exhaust its 300 descriptors before the RAW pool. Stop before the next
         * allocation, so its normal completion/cleanup owns every buffer. */
        if (f[4] && !(f[4] & 3u) && AP_W(f[4] + 4u) >= AP_PB_RING_CAP) { f[0] = 0; return 1; }
        return 0;
    case H_PBRAW14: {
        /* C01CDBE0 maps planes 7/9/10 to RAW12/10/8, but drops plane 8
         * into RAW12. C0173F20 consumes this +0x50 as its actual read format.
         * Only the validated selected RAW14 movie's primary frame qualifies. */
        const struct ap_pb *P = &A->pb;
        if (P->active && P->pbc && P->bits == 14u && P->prepared &&
            ap_pb_selected(A, P->prepared) && f[4] == 0u && f[5] == AP_PB_RAW_SETUP &&
            f[6] && !(f[6] & 3u) && f[7] == f[6] + 0x38u &&
            AP_B8(f[7]) == 8u && AP_W(f[7] + 0x20u) == P->ras_w &&
            AP_W(f[7] + 0x28u) == P->ras_h)
            f[3] = 1u;
        f[2] = f[5] + (f[2] << 2); /* displaced Thumb ADD; native store follows */
        return 1;
    }
    case H_PBPREP1: case H_PBPREP2: {                                /* before buffers / RAW decoding */
        struct ap_pb *P = &A->pb;
        A->pb_since = 1;
        u32 obj = f[0];
        P->preps++;
        P->prepared = 0;
        int enabled = P->mode && (P->mode != 2u || ap_live(A));
        int reject = !obj || (obj & 3u);
        if (!reject && (u64)AP_W(obj + 0x98u) * AP_W(obj + 0x9Cu) > AP_PB_MAX_AREA) {   /* any mode: it would freeze */
            P->too_big++;
            reject = 1;
        }
        if (!reject && P->block) reject = enabled ? !ap_pb_selected(A, obj) :
            ap_pb_blocked(A, AP_W(obj + 0x98u), AP_W(obj + 0x9Cu));
        if (reject) {
            P->refused++;                                            /* the raster v11's tag read left in obj + 0x98 */
            f[0] = 0;
            return 1;
        }
        /* C06A0770 classifies >=239 fps as 11..13, but the player's
         * C05BCB60 cadence table ends at 10 (119.88 source / 59.94 display).
         * Clamp only the validated player's runtime enum, not its DNG tags. */
        if (enabled && ap_pb_selected(A, obj)) {
            u32 rate = AP_W(obj + 0x68u);
            if (rate >= 11u && rate <= 13u) AP_W(obj + 0x68u) = 10u;
        }
        if (enabled && P->block) P->prepared = obj;
        return 0;
    }
    case H_PBNAME: {                                                 /* (obj, out, sizes): observe the key build only */
        struct ap_pb *P = &A->pb;
        if (f[13] == AP_KEYBLD && f[2]) {
            u32 w = AP_W(f[2] + 8u), h = AP_W(f[2] + 0xCu);
            if (w && h) { P->cw = w; P->ch = h; P->en = AP_W(f[2] + 0x20u); P->seq++; P->latches++; }
        }
        return 0;
    }
    case H_DSCALE: {                                                 /* (_, tiff, ifd, info): IFD 0, our take only */
        struct ap_slot *s = ap_live(A);
        if (s && s->ds_on && ap_rec_picked(A) && f[1] && f[2] == 0u) {
            u32 r[4] = {s->ds[0], s->ds[1], s->ds[2], s->ds[3]};
            ((ap_fw7)AP_TAG_SET)(f[1], 0u, 0u, 0xC61Eu, 5u, 2u, (u32)(uintptr_t)r);   /* RATIONAL x 2 */
            A->pb.dscale_w++;
        }
        return 0;
    }
    case H_PBW: case H_PBH: {                                        /* (notifier, v): no tile -> no size line */
        struct ap_pb *P = &A->pb;
        u32 v = f[1], o = id == H_PBW ? (v == P->cw ? P->ch : 0u) : (v == P->ch ? P->cw : 0u);
        /* v0.7.22test: only with the HUD tile experiment on (ap_pb_ctl 1).  Off (the product), a size without
         * tiles is shown by the text row (H_PBOWN), which needs the real numbers -- zeroing them drew "0x0" */
        if (P->glyph_on && v && (!ap_tile_ok(A, v) || (o && !ap_tile_ok(A, o)))) { f[1] = 0; P->hud_hidden++; }
        return 0;
    }
    case H_PBRES: {                                                  /* (notifier, w, h): the label of a non-stock clip */
        struct ap_pb *P = &A->pb;
        u32 w = f[1], h = f[2];
        u32 stock = (w == 3840u && h == 2160u) || (w == 1920u && h == 1080u) ||
                    (w == 4096u && h == 2160u) || (w == 1280u && h == 720u);
        /* v0.7.21test: v92 and v153 come in either order -- set or undo PB_OwnModel here too */
        P->own_text = !stock;
        if (!stock) { ((ap_fw3)AP_PB_VAR_SET)(f[0], AP_PB_OWN_NAME, 1u); P->own_forced = 1; P->own_sets++; }
        else if (P->own_forced) { ((ap_fw3)AP_PB_VAR_SET)(f[0], AP_PB_OWN_NAME, P->own_last ^ 1u); P->own_forced = 0; }
        if (P->res_val == AP_PB_RES_STOCK || stock) return 0;
        ((ap_fw3)AP_PB_VAR_SET)(f[0], AP_PB_RES_NAME, P->res_val);
        P->res_sets++;
        return 1;
    }
    case H_PBOWN: {                                                  /* (notifier, own): v153 */
        struct ap_pb *P = &A->pb;
        P->own_last = f[1];
        if (!P->own_text) { P->own_forced = 0; return 0; }           /* stock size: the stock value */
        ((ap_fw3)AP_PB_VAR_SET)(f[0], AP_PB_OWN_NAME, 1u);
        P->own_forced = 1; P->own_sets++;
        return 1;
    }
    case H_DEFC: {                                                   /* (2, {table, list}): r5 = c030e2a0's mode */
        struct ap_slot *s = ap_slot_id(A, f[5]);
        if (f[0] != 2u || !s || !s->defc) return 0;                  /* stock ids, "off", no table: untouched */
#ifdef AP_PURPLE_TEST
        if (s->pt & PT_ROWS) return 0;                               /* the stock R68 row: the stock table, as stock */
#endif
        f[1] = (u32)(uintptr_t)&A->defc[s - A->slot];
        A->defc_loads++;
        return 0;
    }
    case H_FFARM:                                                    /* blx FUN_c0631b98(r0 = dest), r6 = desc - 8 */
        ap_ff_arm(A, f[0], f[6]);
        return 0;
    case H_FFFIX: {                                                  /* bl FUN_c03753c0 -> the frame, then record */
        u32 fr = ((ap_fw4)A->ven[id][V_DOWN])(f[0], f[1], f[2], f[3]);
        ap_tr_write(A, fr);
        f[0] = fr;
        return 1;
    }
    case H_RESYNC: case H_RESYNC2: {                                 /* SetImgMode_s(imgmode, mode), then resync */
#ifdef AP_PURPLE_TEST
        u32 from = AP_W(AP_CUR_MODE);                                /* the PURPLE marker: which switch, when */
#endif
        u32 r = ((ap_fw4)A->ven[id][V_DOWN])(f[0], f[1], f[2], f[3]);
        struct ap_slot *s = ap_live(A);
        A->rs_seen++;                                                /* every mode switch through either site */
#ifdef AP_PURPLE_TEST
        A->pt_sw++; A->pt_from = from; A->pt_to = f[1]; A->pt_sw_us = ap_now_us();
        if (s && f[1] == s->id) A->pt_ours++;
        if (A->rd) A->rd->sw_total++;
#endif
        if (s && f[1] == s->id) { A->rs_ours++; ap_resync(A); }     /* our mode only: stock never */
        f[0] = r;
        return 1;
    }
#ifdef AP_REC_DELAY_TEST
    case H_RECDLY: {                                                 /* bl FUN_c030cf98(r0, r1, r2): sleep, then it */
        struct ap_rd *R = A->rd;
        if (!R || R->magic != AP_RD_MAGIC) return 0;                 /* not attached: straight down */
        u32 ms = R->ms;
        if (ms > AP_RD_MAX_MS) { ms = AP_RD_MAX_MS; R->clamped++; }
        struct ap_rdrec *q = &R->r[R->n & (AP_RD_N - 1u)];
        ap_zero(q, sizeof *q);
        R->n++;
        q->seq = R->n; q->ms = ms;
        q->line0 = AP_W(0x30100590u);
        q->t0 = ap_now_us();
#ifdef AP_PURPLE_TEST
        {
            struct ap_slot *s = ap_live(A);
            u32 pt = s ? s->pt : 0u, sm = s && (pt & PT_ROWS) ? s->smode : 0u;
            q->bits = pt | (sm & 0xFFu) << 8 | (R->refused & 0xFFu) << 16;
            q->sw = (A->pt_sw > 255u ? 255u : A->pt_sw) | (A->pt_from & 0xFFu) << 8 | (A->pt_to & 0xFFu) << 16 |
                    (A->pt_ours > 255u ? 255u : A->pt_ours) << 24;
            q->sw_dt = A->pt_sw_us ? q->t0 - A->pt_sw_us : 0u;
            q->cur = AP_W(AP_CUR_MODE);
            A->pt_sw = 0; A->pt_ours = 0;
        }
#endif
        if (ms) { ((ap_fw1)AP_RD_SLEEP)(ms); R->sleeps++; }
        q->t1 = ap_now_us();
        u32 r = ((ap_fw3)A->ven[id][V_DOWN])(f[0], f[1], f[2]);
        q->t2 = ap_now_us();
        q->line2 = AP_W(0x30100590u);
        q->rc = r;
        f[0] = r;
        return 1;
    }
#endif
    case H_FFDONE:                                                   /* FUN_c031bca0(raster) entry, IRQ */
        ap_tr_done(A, f[0]);
        return 0;
    case H_RATIO: {                                                  /* enum -> {w, h}: ours for 9 */
        struct ap_slot *s = ap_live(A);
        if (f[0] != AP_ASPECT_ENUM) return 0;
        if (A->pb.active) {                                          /* v0.7.20: the playing clip's pair */
            const u32 *pp = ap_pb_pair(A);
            if (!pp) return 0;
            f[0] = (u32)(uintptr_t)pp;
            return 1;
        }
        if (!s || s->is169) return 0;
        f[0] = (u32)(uintptr_t)s->asp;
        return 1;
    }
    }
    return 0;
}

/* ---- install (sup_entry only: the loader attributes claims to the sup whose entry runs) -------------------- */
static u32 ap_branch(u32 site, u32 to, u32 link)
{
    return (link ? 0xEB000000u : 0xEA000000u) | (((to - site - 8u) >> 2) & 0x00FFFFFFu);
}
static int ap_reach(u32 site, u32 to)
{
    int32_t off = (int32_t)(to - site - 8u);
    return off >= -(int32_t)0x02000000 && off < (int32_t)0x02000000;
}
static u32 ap_target(u32 site, u32 w)              /* ARM B / BL / BLX imm, 0 = not a branch */
{
    if ((w & 0x0E000000u) != 0x0A000000u) return 0;
    int32_t off = (int32_t)(w << 8) >> 6;
    u32 t = site + 8u + (u32)off;
    if ((w >> 28) == 0xFu) t |= ((w >> 23) & 2u) | 1u;       /* BLX: Thumb, H bit */
    return t;
}

static u32 ap_thumb_blx(u32 site, u32 target)
{
    u32 d = target - ((site + 4u) & ~3u), s = (d >> 24) & 1u;
    u32 j1 = (~((d >> 23) ^ s)) & 1u, j2 = (~((d >> 22) ^ s)) & 1u;
    return (0xF000u | (s << 10) | ((d >> 12) & 0x3FFu)) |
           ((0xC000u | (j1 << 13) | (j2 << 11) | ((d >> 1) & 0x7FEu)) << 16);
}

int ap_init(void *mem, uint32_t bytes, const struct sl_svc *svc)
{
    struct ap *A = (struct ap *)mem;
    if (!A || ((u32)(uintptr_t)A & 7u) || bytes < sizeof(struct ap) || !svc) return AP_E_ABI;
    ap_zero(A, sizeof *A);
    A->magic = AP_MAGIC; A->abi = AP_ABI; A->svc = (u32)(uintptr_t)svc;
    /* Playback uses a validated selected-clip snapshot; no HUD resource registration. */
    A->pb.magic = 0x42504C53u; A->pb.mode = 1u; A->pb.glyph_on = 0u; A->pb.res_val = AP_PB_RES_STOCK; A->pb.block = 1u;
    for (u32 i = 0; i < 2u; i++) {
        A->slot[i].id = AP_VMID0 + i; A->slot[i].pid = AP_VPID0 + i; A->slot[i].spid = AP_VPID0 + 2u + i;
    }
    /* every site must read stock (a warm restart's leftovers: the claim repairs them first) and every replayed
     * instruction must not read the pc; refuse all if one does not */
    u32 cave[AP_NHOOK];
    for (u32 i = 0; i < AP_NHOOK; i++) {
        const struct ap_site *h = &AP_SITES[i];
        u32 w = h->stock;
        if (h->kind == K_TADD) {
            if (w != AP_TADD_STOCK || (h->site & 3u)) return AP_E_HOOKS;  /* H_PBRAW14 replays exactly this ADD */
        } else if (h->kind != K_BL || !ap_target(h->site, w))
            if (((w >> 16) & 0xFu) == 15u || ((w >> 12) & 0xFu) == 15u || (w & 0xFu) == 15u) return AP_E_HOOKS;
        if (svc->claim(svc, h->site, 4u, &h->stock, SL_EXCL) != SL_OK) return AP_E_HOOKS;
        cave[i] = svc->cave_alloc(svc, 8u);
        if (!cave[i] || !ap_reach(h->site, cave[i])) return AP_E_HOOKS;
        if (h->kind == K_TADD && (u32)(cave[i] - (h->site + 4u) + 0x01000000u) >= 0x02000000u)
            return AP_E_HOOKS; /* Thumb BLX has a smaller signed reach than ARM B */
    }
    /* the >99 fps clock gate (res-custom CLK0): claimed now, opened only while a fast slot is live */
    static const u32 clk_stock = AP_CLK_STOCK;
    if (svc->claim(svc, AP_CLK_SITE, 4u, &clk_stock, SL_EXCL) != SL_OK) return AP_E_HOOKS;
    A->clk_ok = 1;
    u32 fn = (u32)(uintptr_t)&ap_hook;
    for (u32 i = 0; i < AP_NHOOK; i++) {
        const struct ap_site *h = &AP_SITES[i];
        u32 *v = A->ven[i], tgt = h->kind == K_BL ? ap_target(h->site, h->stock) : 0;
        for (u32 k = 0; k < 14u; k++) v[k] = AP_VENEER[k];
        v[V_A] = (u32)(uintptr_t)A; v[V_ID] = i; v[V_FN] = fn;
        v[V_INSN] = h->stock; v[V_JMP] = 0xE51FF004u; v[V_BACK] = h->site + 4u;
        v[V_DOWN] = tgt ? tgt : (u32)(uintptr_t)&v[V_INSN];
        v[V_RET] = h->kind == K_MID ? h->site + 4u : (u32)(uintptr_t)&v[13];
        AP_W(cave[i]) = 0xE51FF004u;                          /* ldr pc, [pc, #-4] */
        AP_W(cave[i] + 4u) = (u32)(uintptr_t)v;
    }
    svc->publish(svc);                                     /* veneers and cave words are code before any site */
    for (u32 i = 0; i < AP_NHOOK; i++)
        AP_W(AP_SITES[i].site) = AP_SITES[i].kind == K_TADD ? ap_thumb_blx(AP_SITES[i].site, cave[i]) :
            ap_branch(AP_SITES[i].site, cave[i], AP_SITES[i].kind == K_BL);
    svc->publish(svc);
    A->armed = 1;
    return AP_OK;
}

/* ---- the commit ------------------------------------------------------------------------------------------ */
/* place one table row in its buffer so that an index exists that lands on it (res-custom clone_row) */
static u32 ap_place(u32 buf, u32 base, u32 stride, const uint8_t *src, u32 id)
{
    u32 g = stride & (0u - stride);
    u32 row = buf + ((base - buf) & (g - 1u));
    ap_copy((void *)(uintptr_t)row, src, stride);
    AP_W(row) = id;
    return row;
}

/* ---- v0.7.25test: the slot's defect table (UI thread, not recording; the slot is valid, not live) ---------- *
 * 1 built; 0 not needed (R68 +08 = 0: +04's table fits the raster as it is, the stock rule); < 0 not built (stock
 * behaviour: DEFC gets what c030e2a0 picks). */
static u32 ap_h16(u32 a) { return *(volatile uint16_t *)(uintptr_t)a; }
static u32 ap_uncached(u32 p) { return p >= SL_ALIAS ? p - SL_ALIAS : p; }   /* sloader4.h: 0xC... = 0x4... + this */
static s32 ap_defc_build(struct ap *A, u32 n, const struct ap_slot *s)
{
    struct ap_defc *d = &A->defc[n];
    u32 *t = A->dtab[n];
    d->tbl = 0;
    u32 r68 = s->row[TB_R68];
    if (!r68 || !AP_B8(r68 + 8u)) return 0;
    u32 want = ap_h16(r68 + 0x0Cu), buf = AP_W(AP_DEFC_BUFP);
    if (!buf || (buf & 3u) || buf > 0xFFFFFFFFu - AP_DEFC_BYTES) return -1;         /* not loaded (yet) */
    u32 dir = buf + AP_DEFC_DIR, nt = AP_W(dir + 4u), src = dir + 0x400u, words = 0;
    if (AP_W(dir) != 1u || !nt || nt > 64u) return -2;                              /* no valid directory */
    for (u32 i = 0; i < nt; i++) {
        u32 sz = ap_h16(dir + 0x88u + 2u * i);
        if (ap_h16(dir + 8u + 2u * i) == want) { words = sz; break; }
        src += 4u * sz;
    }
    if (!words || words > AP_DEFC_WORDS || src + 4u * words > buf + AP_DEFC_BYTES - 0x100u * nt) return -3;
    for (u32 i = 0; i < AP_DEFC_WORDS; i++) t[i] = 0;
    for (u32 i = 0; i < 128u; i++) d->list[i] = 0xFFFFFFFFu;
    if (ap_busy()) return -4;                         /* c0310740's scratch is class 10: never while recording */
    if (!((ap_fw6)AP_DEFC_CONV)(AP_DEFC_CTX, s->id, words, (u32)(uintptr_t)t, (u32)(uintptr_t)d->list, src))
        return -5;                                    /* its scratch allocation failed */
    const volatile uint16_t *h = (const volatile uint16_t *)t;
    u32 ff = 0;
    for (u32 i = 0; i < 2u * words && ff < 4u; i++) ff = h[i] == 0xFFFFu ? ff + 1u : 0u;
    if (ff < 4u) return -6;                           /* no end mark inside the buffer: never hand it out */
    d->tbl = ap_uncached((u32)(uintptr_t)t);
    return 1;
}

static int ap_lv_running(u32 *holder)
{
    *holder = ((ap_fw0)AP_LV_HOLDER)();
    return *holder && AP_W(*holder) && AP_W(AP_W(*holder) + 4u);
}
static void ap_lv_stop(u32 holder, u32 *cs, u32 *was)
{
    *cs = ((ap_fw0)AP_CAMSCH1)();
    *was = ((ap_fw1)AP_CS_GET)(*cs);
    if (*was != 6u) ((ap_fw2)AP_CS_SET)(*cs, 6u);
    ((ap_fw1)AP_LV_STOP)(holder);
}
static void ap_lv_start(struct ap *A, u32 holder, u32 cs, u32 was)
{
    ((ap_fw1)AP_LV_START)(holder);
    if (was != 6u) ((ap_fw2)AP_CS_SET)(cs, was);
    A->lv_reloads++;
}

/* the clock gate word follows the live slot (patched code: D-clean + I-invalidate) */
static void ap_clock(struct ap *A, u32 open)
{
    if (!A->clk_ok || A->clk_open == open) return;
    AP_W(AP_CLK_SITE) = open ? AP_CLK_OPEN : AP_CLK_STOCK;
    ((ap_fw0)AP_DCACHE)();
    ((ap_fw0)AP_ICACHE)();
    A->clk_open = open;
}

/* back to stock: no slot live; the LV reloaded so nothing of ours is shown (Bei: a failure restores stock in full) */
static void ap_to_stock(struct ap *A)
{
    u32 holder, cs = 0, was = 6u, run = ap_lv_running(&holder);
    if (!A->active && !A->clk_open) return;
    if (run) ap_lv_stop(holder, &cs, &was);
    u32 s = ap_irq_off();
    A->active = 0; A->picked = 0;
    ap_dmb(); ap_irq_restore(s);
    ap_clock(A, 0);
    if (run) ap_lv_start(A, holder, cs, was);
}

static int ap_finish(struct ap *A, int rc, s32 detail)
{
    A->result = rc; A->detail = detail;
    if (rc < 0) A->refusals++;
    return rc;
}

#ifdef AP_PURPLE_TEST
static u32 ap_pt_find(u32 base, u32 n, u32 stride, u32 id)   /* the stock row of id in a firmware table, or 0 */
{
    for (u32 i = 0; base && i < n && i < 512u; i++) if (AP_W(base + stride * i) == id) return base + stride * i;
    return 0;
}
static u32 ap_le32(const uint8_t *p) { return (u32)p[0] | (u32)p[1] << 8 | (u32)p[2] << 16 | (u32)p[3] << 24; }
/* input (META) w x h covers an output raster rw x rh at RWZM rz (firmware clamp: >= 0x400), with the centring margin */
static int ap_pt_covers(u32 mw, u32 mh, u32 rw, u32 rh, u32 rzh, u32 rzv)
{
    rzh = rzh < 0x400u ? 0x400u : rzh; rzv = rzv < 0x400u ? 0x400u : rzv;
    return (u64)mw * 0x400u >= (u64)(rw + 8u) * rzh && (u64)mh * 0x400u >= (u64)(rh + 4u) * rzv;
}
/* the toggles the host asked for (R->bits), kept only when they are consistent for this slot; s is the slot being
 * committed (not live: nobody reads its rows yet), its rows placed, rec_w / rec_h / base_row / isp set */
static void ap_pt_latch(struct ap *A, struct ap_slot *s, const struct apc_out *o, u32 desc, u32 regdesc)
{
    struct ap_rd *R = A->rd;
    u32 want = R && R->magic == AP_RD_MAGIC ? R->bits : 0u, pt = want & PT_ALL;
    u32 mw = ap_le32(o->mode.meta + 4), mh = ap_le32(o->mode.meta + 8);
    u32 hm = ap_le32(o->mode.tim + 4) & 0xFFFFu, vm = ap_le32(o->mode.tim + 8) & 0xFFFFu;
    if ((pt & PT_TWIN) && (pt & PT_SBSTOCK)) pt &= ~PT_TWIN;          /* one standby */
    if ((pt & PT_NOWIN) && (pt & PT_ROWS)) pt &= ~PT_NOWIN;           /* stock rows have no window anyway */
    if ((pt & (PT_ROWS | PT_RWZM | PT_NOWIN)) && (o->rec_w != 3840u || o->rec_h != 2160u)) pt &= ~(PT_ROWS | PT_RWZM | PT_NOWIN);
    if (pt & PT_ROWS) {                                               /* a stock UHD mode with our frame time (1 %) */
        u32 sm = R->smode, ok = 0;
        for (u32 i = 0; i < sizeof AP_PT_SMODES; i++) if (sm == AP_PT_SMODES[i]) ok = 1;
        u32 tim = ok ? ap_pt_find(AP_W(desc + 0x00u), AP_W(desc + 0x04u), 0x20u, sm) : 0u;
        u32 meta = ok ? ap_pt_find(AP_W(desc + 0x08u), AP_W(desc + 0x0Cu), 100u, sm) : 0u;
        u32 reg = ok ? ap_pt_find(AP_W(regdesc), AP_W(regdesc + 4u), 0x288u, sm) : 0u;
        u64 a = tim ? (u64)(AP_W(tim + 4u) & 0xFFFFu) * (AP_W(tim + 8u) & 0xFFFFu) : 0u, b = (u64)hm * vm;
        u64 d = a > b ? a - b : b - a;
        if (!tim || !meta || !reg || !b || d * 100u > b) pt &= ~PT_ROWS;
        else { s->smode = sm; s->meta[0] = AP_W(meta + 4u); s->meta[1] = AP_W(meta + 8u); mw = s->meta[0]; mh = s->meta[1]; }
    }
    if ((pt & PT_ROWS) && !ap_pt_covers(mw, mh, o->rec_w, o->rec_h, s->isp[25], s->isp[53])) pt &= ~PT_ROWS;   /* +64 / +D4 */
    if (pt & PT_RWZM) {                                               /* the base row's raster at its RWZM */
        u32 b = s->base_row < 0x200u ? 4u * s->base_row : 0u;      /* a row index into the gather's columns */
        u32 bw = b ? AP_W(AP_PT_COL00 + b) : 0u, bh = b ? AP_W(AP_PT_COL04 + b) : 0u;
        if (!bw || !bh || bw > 4112u || bh > 2176u || bw < o->rec_w || bh < o->rec_h ||
            !ap_pt_covers(mw, mh, bw, bh, AP_W(AP_PT_COL64 + b), AP_W(AP_PT_COLD4 + b))) pt &= ~PT_RWZM;
        else { s->rec_w = bw; s->rec_h = bh; }                        /* the sentinel's row: BUFA1's stock raster */
    }
    if (pt & PT_NOWIN) {                                              /* the windowed REG row (v32's five registers) */
        u32 row = s->row[TB_REG];
        if (!row || AP_W(row + 4u * AP_PT_WIN[0]) != 1u || (u64)hm * vm < 445u * 5398u) pt &= ~PT_NOWIN;
        else for (u32 i = 0; i < sizeof AP_PT_WIN; i++) AP_W(row + 4u * AP_PT_WIN[i]) = 0;
    }
    s->pt = pt;
    if (R) { R->live = pt; R->refused = want & ~pt; R->commits++; }
}
#endif

/* one commit of A->run (the caller holds in_commit) */
static int ap_commit(struct ap *A)
{
    const struct ap_sel *sel = &A->run;
    if (ap_busy()) { A->owed = 1; return ap_finish(A, AP_PENDING, 0); }   /* never while recording */
    u32 t0 = ap_now_us();
    A->ff.state = 0; A->tr.live = 0;                         /* not recording: no first frame is owed */
    ap_copy(&A->have, sel, sizeof *sel);
    if (!sel->valid) { ap_to_stock(A); return ap_finish(A, AP_OK, 0); }
    u32 obj = ((ap_fw0)AP_GET_OBJ)();
    if (sel->fmt || ((ap_fw1)AP_GET_FMT)(obj)) { ap_to_stock(A); return ap_finish(A, AP_E_FORMAT, 0); }
    u32 desc = AP_W(AP_IMAGER), regdesc = AP_W(AP_HOLDER);
    if (!desc || !regdesc || !AP_W(regdesc)) { ap_to_stock(A); A->owed = 1; return ap_finish(A, AP_E_NOTREADY, 0); }   /* retried */
    struct apc_out *o = &A->out;
    int rc = apc_build(sel->dcw, sel->dch, sel->rw, sel->rh, sel->key, sel->hbin, sel->vbin, sel->hm, sel->vmax,
                       sel->fps_n, sel->fps_d, sel->kh, sel->kv, sel->km, &A->work, o);
    if (rc) { ap_to_stock(A); return ap_finish(A, rc, o->detail); }
    /* v0.7.2test: CinemaDNG standby runs the record route (TAB3), so the record's readout must be one standby can run;
     * a standby on the stock route would switch readout at REC start (the v0.7.1test freeze) */
    if (!sel->standby || !o->rok) { ap_to_stock(A); A->gated++; return ap_finish(A, AP_E_STANDBY, 0); }
    /* the slot nobody holds: never the live one; the previous live one stays until the commit after next */
    u32 n = (A->cur & 1u) ^ 1u;
    struct ap_slot *s = &A->slot[n];
    s->valid = 0; ap_dmb();
    u32 id = s->id, pid = s->pid, spid = s->spid;
    ap_zero(s, sizeof *s);
    s->id = id; s->pid = pid; s->spid = spid;
    const uint8_t *rows[TB_N] = {o->mode.tim, o->mode.meta, o->mode.r28, o->mode.r38, o->mode.r14, o->mode.r68,
                                 o->mode.reg};
    u32 buf = (u32)(uintptr_t)s->buf;
    for (u32 k = 0; k < TB_N; k++) {
        u32 base = k == TB_REG ? AP_W(regdesc) : AP_W(desc + TB_FIELD[k]);
        s->row[k] = ap_place(buf, base, TB_STRIDE[k], rows[k], id);
        buf += BUF_BYTES(TB_STRIDE[k]);
    }
    s->r10 = (u32)o->mode.r10[0] | (u32)o->mode.r10[1] << 8 | (u32)o->mode.r10[2] << 16 | (u32)o->mode.r10[3] << 24;
    u32 zb = AP_W(desc + Z_FIELD), zn = AP_W(desc + Z_FIELD + 4u);
    for (u32 i = 0; zb && i < zn && i < 256u; i++)
        if (AP_W(zb + Z_STRIDE * i) == o->donor) {
            ap_copy(s->zrow, (const void *)(uintptr_t)(zb + Z_STRIDE * i), Z_STRIDE);
            s->zrow[0] = id; s->zok = 1;
            break;
        }
    s->donor = o->donor; s->carrier = o->carrier; s->rank = o->rank; s->engine = o->engine; s->fast = o->fast;
    s->rec14 = o->rec14; s->sok = o->sok;
    s->sfx_len = o->sfx_len;
    for (u32 i = 0; i < 6u; i++) s->sfx[i] = o->sfx[i];
    s->base_row = AP_W(AP_MAPPING + 4u * AP_BASE_PID);
    for (u32 i = 0; i < 65u; i++) s->isp[i] = o->isp[i];
    for (u32 i = 0; i < 3u; i++) { s->mask[i] = o->mask[i]; s->smask[i] = o->smask[i]; }
    s->sb_w = o->sb_w; s->sb_h = o->sb_h; s->asp[0] = o->asp_n; s->asp[1] = o->asp_d; s->is169 = o->is169;
    s->box_w = o->box_w; s->box_h = o->box_h; s->det_h = o->det_h;
    s->dng_n = o->dng_n; s->dng_d = o->dng_d; s->binfilt = o->binfilt;
    s->sv[0] = o->sv_w; s->sv[1] = o->sv_h; s->sr[0] = o->sr_w; s->sr[1] = o->sr_h; s->sclamp = o->sclamp;
    s->ds_on = o->ds_on;
    for (u32 i = 0; i < 4u; i++) s->ds[i] = o->ds[i];
    s->rec_w = o->rec_w; s->rec_h = o->rec_h;
#ifdef AP_PURPLE_TEST
    ap_pt_latch(A, s, o, desc, regdesc);
#endif
    /* the keys:"SL" + the carrier suffix, "SLMOV" (the firmware only reads the pointers' strings for logs) */
    s->key[0] = 'S'; s->key[1] = 'L';
    for (u32 i = 0; i < s->sfx_len; i++) s->key[2u + i] = s->sfx[i];
    s->entry[0] = 5u; s->entry[1] = pid; s->entry[2] = id; s->entry[3] = (u32)(uintptr_t)s->key;
    s->sby = o->sok;                                         /* the MOV-table standby (sel->standby: refused above) */
    s->sbase_row = AP_W(AP_MAPPING + 4u * AP_SBASE_PID);
    s->skey[0] = 'S'; s->skey[1] = 'L'; s->skey[2] = 'M'; s->skey[3] = 'O'; s->skey[4] = 'V';
    s->sentry[0] = 1u; s->sentry[1] = spid; s->sentry[2] = id; s->sentry[3] = (u32)(uintptr_t)s->skey;
#ifdef AP_PURPLE_TEST
    if (s->pt & PT_TWIN) s->sentry[2] = id + AP_PT_TWIN;     /* standby on the twin: REC start switches to id */
#endif
    ap_dmb();
    s->valid = 1;
    /* v0.7.25test: its defect table, through the lookups that now answer this id (before the D-clean: DEFC reads
     * the table by DMA) */
    A->defc_last = ap_defc_build(A, n, s);
    s->defc = A->defc_last > 0;
    if (A->defc_last > 0) A->defc_builds++; else if (A->defc_last < 0) A->defc_skips++;
    ((ap_fw0)AP_DCACHE)();                                   /* rows are read by the CPU; clean for any DMA reader */
    /* the transaction: LV down, busy again under IRQ off, flip, the carrier through the native setter, LV up */
    u32 holder, cs = 0, was = 6u, run = ap_lv_running(&holder);
    if (run) ap_lv_stop(holder, &cs, &was);
    u32 irq = ap_irq_off();
    if (ap_busy()) {                                         /* recording began meanwhile: stock, owed */
        A->active = 0; A->picked = 0;
        ap_dmb(); ap_irq_restore(irq);
        ap_clock(A, 0);
        if (run) ap_lv_start(A, holder, cs, was);
        A->owed = 1;
        return ap_finish(A, AP_E_BUSY, 0);
    }
    A->cur = n; A->active = 1; A->picked = 0;
    ap_dmb(); ap_irq_restore(irq);
    /* the carrier (Bei 2026-10-29: set automatically): the setter the menus call, then the list classes, as
     * res-custom's vrc_apply does around its resolution setter */
    if (((ap_fw1)AP_FR_GET)(obj) != s->carrier) {
        ((ap_fw3)AP_FR_SET)(obj, s->carrier, 0);
        u32 list[3] = {0x19u, 0x1Eu, 0xFFFFFFFFu};           /* EXCL_FRAMERATE, EXCL_BITDEPTH */
        ((ap_fw2)AP_EXCL_RECOMPUTE)(((ap_fw0)AP_EXCL_MGR)(), (u32)(uintptr_t)list);
        A->carrier_sets++;
        if (((ap_fw1)AP_FR_GET)(obj) != s->carrier) {        /* the setter refused or normalised it: stock */
            irq = ap_irq_off();
            A->active = 0; A->picked = 0;
            ap_dmb(); ap_irq_restore(irq);
            ap_clock(A, 0);
            if (run) ap_lv_start(A, holder, cs, was);
            return ap_finish(A, AP_E_RATE, (s32)s->carrier);
        }
    }
    ap_clock(A, s->fast);
    if (run) ap_lv_start(A, holder, cs, was);
    ap_glyph_want(A, o->rec_w - 16u);                        /* the take's DefaultCropSize: its HUD tiles, at ap_idle */
    ap_glyph_want(A, o->rec_h - 10u);
    A->commits++;
    A->commit_us = ap_now_us() - t0;
    return ap_finish(A, AP_OK, 0);
}

/* ---- the change event ------------------------------------------------------------------------------------ */
static int ap_same(const struct ap_sel *a, const struct ap_sel *b)
{
    const uint8_t *x = (const uint8_t *)a, *y = (const uint8_t *)b;
    for (u32 i = 0; i < sizeof *a; i++) if (x[i] != y[i]) return 0;
    return 1;
}

/* commit the latest wanted selection until no newer one arrived meanwhile (bounded); the caller set in_commit */
static int ap_run(struct ap *A)
{
    int rc = AP_IDLE;
    for (u32 round = 0; round < 8u; round++) {
        u32 irq = ap_irq_off(), seq = A->seq;
        ap_copy(&A->run, &A->want, sizeof A->run);
        A->owed = 0;
        ap_dmb(); ap_irq_restore(irq);
        rc = ap_commit(A);
        irq = ap_irq_off();
        u32 again = A->seq != seq && !ap_same(&A->want, &A->have) && rc != AP_PENDING;
        if (again) A->owed = 1;
        if (!again) A->in_commit = 0;
        ap_dmb(); ap_irq_restore(irq);
        if (!again) return rc;
    }
    A->in_commit = 0;
    return rc;
}

int ap_request(void *mem, const struct ap_sel *s)
{
    struct ap *A = (struct ap *)mem;
    if (!A || A->magic != AP_MAGIC || !s || s->bytes != sizeof *s || s->abi != AP_ABI) return AP_E_ABI;
    if (!A->armed) return AP_E_HOOKS;
    u32 irq = ap_irq_off();
    ap_copy(&A->want, s, sizeof *s);
    A->seq++;
    A->owed = !ap_same(&A->want, &A->have) || A->result < 0 || A->result == AP_PENDING;
    u32 mine = A->owed && !A->in_commit;
    if (mine) A->in_commit = 1;
    u32 owed = A->owed;
    ap_dmb(); ap_irq_restore(irq);
    if (!owed) return AP_IDLE;
    if (!mine) return AP_PENDING;                        /* a commit is running: it takes this one when done */
    return ap_run(A);
}

/* v0.7.35test: may a commit run now (boot apply, slqs.c)?  1 = a standby LV has started since boot and no playback hook
 * ran after it, nothing records, no commit runs, CinemaDNG is the format, and the mode descriptor and register record
 * exist -- the same tests ap_commit makes before it touches the LV (which then reports AP_E_NOTREADY instead). */
static int ap_cine_lv_now(void)                       /* CINE (not STILL) and the live view running now */
{
    u32 holder;
    return ((ap_fw1)AP_CINE)(((ap_fw0)AP_GET_OBJ)()) && ap_lv_running(&holder);   /* CinemaMode 0 = STILL */
}
int ap_boot_ready(void *mem)
{
    struct ap *A = (struct ap *)mem;
    /* v0.7.37test (live 11-05, second build): the boot LV start never reaches the picker (picks 0 even with the LV
     * screen entered after the load), so lv_seen alone never comes at boot: a CINE live view running now counts too.
     * Playback is still excluded by its own hooks (pb_since / pb.active). */
    if (!A || A->magic != AP_MAGIC || !A->armed || A->in_commit || A->pb_since || A->pb.active || ap_busy()) return 0;
    if (!A->lv_seen && !ap_cine_lv_now()) return 0;
    if (((ap_fw1)AP_GET_FMT)(((ap_fw0)AP_GET_OBJ)())) return 0;
    u32 desc = AP_W(AP_IMAGER), regdesc = AP_W(AP_HOLDER);
    return desc && regdesc && AP_W(regdesc) ? 1 : 0;
}

/* v0.7.37test, diagnostics only (sq_test 46 lv_load): a CINE live view already running at sup_entry (the live 11-05
 * boots: the boot LV starts before the sups load, the picker never sees it -- ap_boot_ready asks ap_cine_lv_now). */
/* 0.0.3test: the stock CinemaDNG bit depth the picker will ask for: FUN_c043b828's rule over eRawBitType (4 -> 8, 3 -> 10,
 * else 12).  UI thread (slqs.c reads it once per layout, like the medium). */
int ap_raw_bits(void)
{
    u32 t = ((ap_fw1)AP_BIT_GET)(((ap_fw0)AP_GET_OBJ)());
    return t == 4u ? 8 : t == 3u ? 10 : 12;
}
int ap_cine_now(void) { return ((ap_fw1)AP_CINE)(((ap_fw0)AP_GET_OBJ)()) != 0; }   /* v0.7.37test: 0 = STILL */
int ap_lv_at_load(void *mem)
{
    struct ap *A = (struct ap *)mem;
    if (!A || A->magic != AP_MAGIC) return 0;
    return ap_cine_lv_now();
}

int ap_flush(void *mem)
{
    struct ap *A = (struct ap *)mem;
    if (!A || A->magic != AP_MAGIC) return AP_E_ABI;
    u32 irq = ap_irq_off();
    u32 mine = A->owed && !A->in_commit;
    if (mine) A->in_commit = 1;
    ap_dmb(); ap_irq_restore(irq);
    if (!mine) return A->owed ? AP_PENDING : AP_IDLE;
    return ap_run(A);
}

void ap_status_get(void *mem, struct ap_status *out)
{
    struct ap *A = (struct ap *)mem;
    if (!out || out->bytes != sizeof *out || out->abi != AP_ABI) return;
    ap_zero((uint8_t *)out + 8, sizeof *out - 8u);
    if (!A || A->magic != AP_MAGIC) return;
    struct ap_slot *s = ap_live(A);
    out->armed = A->armed; out->active = A->active; out->cur = A->cur;
    out->mode_id = s ? s->id : 0; out->pid = s ? s->pid : 0;
    out->result = A->result; out->detail = A->detail;
    out->commits = A->commits; out->refusals = A->refusals; out->lv_reloads = A->lv_reloads; out->owed = A->owed;
    out->picks = A->picks; out->lookups = A->lookups; out->canvases = A->canvases; out->recrates = A->recrates;
    out->commit_us = A->commit_us;
    out->standby_picks = A->standby_picks; out->carrier = s ? s->carrier : 0; out->carrier_sets = A->carrier_sets;
    out->fast = A->clk_open;
    out->gated = A->gated; out->blacks = A->blacks;
    out->defc = s ? s->defc : 0; out->defc_builds = A->defc_builds; out->defc_skips = A->defc_skips;
    out->defc_loads = A->defc_loads; out->defc_last = A->defc_last;
    out->first_arms = A->ff_arms; out->first_skips = A->ff_skips; out->first_checks = A->ff_checks;
    out->first_intact = A->ff_intact; out->first_ok = A->ff_ok; out->first_miss = A->ff_miss;
    out->trace_n = A->tr.n; out->trace_lost = A->tr.lost;
    out->resync_calls = A->rs_calls; out->resync_skips = A->rs_skips; out->resync_us = A->rs_us;
    out->resync_seen = A->rs_seen; out->resync_ours = A->rs_ours;
    out->rec_bits = A->pick_bits; out->low_picks = A->low_picks;
}

/* ---- playback API (v0.6.0) -------------------------------------------------------------------------------- */
int ap_idle(void *mem)
{
    struct ap *A = (struct ap *)mem;
    if (!A || A->magic != AP_MAGIC) return AP_E_ABI;
    if (ap_busy() || A->in_commit) return AP_PENDING;
    u32 n = 0;
    while (A->pb.gqn) {
        u32 v = A->pb.gq[--A->pb.gqn];
        if (ap_glyph_add(A, v) == 0) n++;
    }
    return n ? AP_OK : AP_IDLE;
}

#ifdef AP_REC_DELAY_TEST
/* 0.0.2test TEST build: the delay control and its ring (rd: 8-aligned, resident, zeroed by the caller) */
int ap_rd_attach(void *mem, void *rd)
{
    struct ap *A = (struct ap *)mem;
    struct ap_rd *R = (struct ap_rd *)rd;
    if (!A || A->magic != AP_MAGIC || !R) return AP_E_ABI;
#ifdef AP_PURPLE_TEST
    R->ver = 2u;
#else
    R->ver = 1u;
#endif
    R->rec_words = sizeof(struct ap_rdrec) / 4u; R->nmax = AP_RD_N;
    R->magic = AP_RD_MAGIC;
    A->rd = R;
    return AP_OK;
}
#endif

const void *ap_trace_info(void *mem)
{
    struct ap *A = (struct ap *)mem;
    return A && A->magic == AP_MAGIC ? (const void *)&A->tr : 0;
}

const void *ap_pb_info(void *mem)
{
    struct ap *A = (struct ap *)mem;
    return A && A->magic == AP_MAGIC ? (const void *)&A->pb : 0;
}

uint32_t ap_pb_ctl(void *mem, uint32_t which, uint32_t value)
{
    struct ap *A = (struct ap *)mem;
    if (!A || A->magic != AP_MAGIC) return 0xFFFFFFFFu;
    u32 *w = which == 0u ? &A->pb.mode : which == 1u ? &A->pb.glyph_on : which == 2u ? &A->pb.res_val :
             which == 3u ? &A->pb.block : 0;
    if (!w || (which == 0u && value > 2u) || (which == 3u && value > 1u)) return 0xFFFFFFFFu;
    u32 old = *w;
    *w = value;
    if (which == 0u && !value) A->pb.active = 0;
    return old;
}
