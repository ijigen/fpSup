/* COL-Share -- 原生 COLOR 清單多出來的列,給所有色彩 sup 共用(Loader v4,Ver.5.02)。
 *
 * 設計:fpSup/colshare/DESIGN.md(Bei 2026-11-07 §9.1)。程式由 lut/native/clist.c(2026-11-07 版)搬來:
 * 列 = 原廠 OFF(0xC)+ active(第幾列);GUI <-> enum 表把 active 那列排第一,所以每條 enum -> GUI 路徑
 * 都落在它上面(raw-view row 17 的機制,上機驗過 1 與 4 列)。不同的是列、名字、圖示、強度範圍、
 * 選到時 root 要寫什麼都來自客戶(colshare.h),root 的共用指標字改由這裡 claim、照客戶的記錄寫。
 *
 * 每幀成本 0:只在按鍵、選單、setter 被呼叫時跑。自己從不寫檔;客戶的 on_pick / strength_set
 * 在錄影中不叫,停錄後下一次選單關閉或 changed() 補送。
 *
 * 寫進原廠的字全都 claim(關機由 loader 的 journal 寫回、暖開機殘留由 claim 修復):
 *   16 個 SL_EXCL 清單點、C05E5BEC(SL_SHARED_UI,fpui_stock 的 HOOK_FV 不替呼叫者 claim)、
 *   root 六組 8 bytes(+0x08 +0x10 +0x28 +0x48 +0x50 +0x70,各含後面的筆數字)SL_EXCL。
 * PQ 快取鍵(C3414D14 / C2F19D44 / C2F19D48)不是 claim 的字:entry 與關機回呼都把它們清成 ~0
 * (11-04 暖重開凍結的教訓,原本在 lut/native/lvb.c lvb_poweroff)。
 *
 * 12 列(Bei 2026-11-10,rows-test 19 列上機通過)與「沒用掉的東西不要佔用記憶體」:
 * 三份 CSV 與每列的圖示複本只在列存在時才有,大小 = 實際內容。同步時(選單關閉、不在錄影)
 * 在機上組 CSV(原廠檔 + 每列一行)、跟韌體配置器(class 0,與 loader / borrow.c 同一個)要剛好的大小,
 * 掛進共用重導表;列不見了就把表項的 stock 字清 0(handler 不再比對到它)再還記憶體。
 * BIN 裡不再存 3 × (N + 1) 份 CSV,也沒有每列的佔位圖示(只有一張共用的)。 */
#include "sloader4.h"
#include "colshare.h"
#include "fpui_stock.c"
typedef uint32_t u32;
typedef int32_t i32;
typedef uint16_t u16;
typedef uint8_t u8;
#define USED __attribute__((used))
#define FW(a, t) ((t)(uintptr_t)(a))

/* 額外列(colshare_ui.MAX_ROWS)。產品 = 12(Bei 2026-11-10);列數測試版(rows-test/、build_colshare.py --rows N)用
 * -DCS_MAX=N。沒有 u 後綴:它也進下面 asm 字串裡的位移運算式。 */
#ifndef CS_MAX
#define CS_MAX          12
#endif
#ifndef CS_TILES
#define CS_TILES        1                   /* 佔位圖示(客戶 icon() 回 0 時):產品一張;測試版每列一張 TEST j */
#endif
#ifndef CS_TEST_ROWS
#define CS_TEST_ROWS    0                   /* 列數測試版:內建假客戶的列數(TEST 1..N,不寫 ISP);產品 = 0 */
#endif
#ifndef CS_STATE
#define CS_STATE        2048                /* build_colshare.STATE */
#endif
#define CS_STOCK        16u
#define CS_GUI_N        (CS_STOCK + CS_MAX)
#define CS_CLIENTS      4u
#define CS_RECS         CS_MAX              /* 每個客戶的記錄表:一個客戶可以佔滿全部的列(LUT 11、12) */
#define CS_FILES        (3u + CS_MAX)       /* 重導的檔案:0..2 三份 CSV,3 + j 第 j + 1 列的圖示 */
#define CS_LABEL        31u
#define CFG_MAGIC       0x31474643u         /* "CFG1": build_colshare.py */
#define SEC_MAGIC       0x31535343u         /* "CSS1": colshare_ui.section() */
#define RUN_MAGIC       0x4E55524Cu         /* "LRUN": 與 clist.c 相同(測試用它找狀態) */
#define RAWV_ID         0x56574152u         /* "RAWV" */

/* sites and the words Ver.5.02 holds there (clist.c, raw-view's rv_launch.S) */
#define S_MA1   0xC0568950u     /* COLOR key: bl GUI->enum      EB055F70 */
#define S_MA2   0xC056D028u     /* menu                          EB054DBA */
#define S_MA3   0xC05818B8u     /* QS                            EB04FB96 */
#define S_MJ    0xC05689A8u     /* COLOR key preview: bl C06C07E8 EB055F8E */
#define S_MB    0xC0595734u     /* CM_COLFIX: bl enum->GUI       EB04AC0B */
#define S_ML    0xC059DA1Cu     /* LV_ColorMode: bl enum->GUI    EB048B51 */
#define S_MC    0xC0075CF4u     /* setter: cmp sl, r6            E15A0006 */
#define S_EF    0xC0568A3Cu     /* Effect box: bl UI->stored     EB0560B7 */
#define S_EN    0xC0595908u     /* v87 CM_COLAJ_Effect           EB04AD18 */
#define S_ENF   0xC05957B0u     /* v82 CM_COLFIX_Effect          EB04AD6E */
#define S_GMOVW 0xC06C07CCu     /* getter: movw r2, #lo          E30122BC */
#define S_GMOVT 0xC06C07D0u     /*         movt r2, #hi          E34C22E4 */
#define S_GCNT  0xC06C07D8u     /*         mov r2, #16           E3A02010 */
#define S_V25   0xC0D119FCu     /* ColorButtonMenu vtable v25    C05687E0 */
#define S_V26   0xC0D11A00u     /*                         v26   C0568888 */
#define S_ADV   0xC1D6ED48u     /* AEL page MenuMode Normal range: BE 12.0 (word 00004041) */
#ifndef ADV_NEW
#define ADV_NEW 0x00009841u     /* BE 19.0 = 15 + CS_MAX(其他列數由 build_colshare.py 傳入) */
#endif
#define FV_SITE  0xC05E5BECu    /* shared file redirect (HOOK_FV) 60681840 */
#define FV_STOCK 0x60681840u
#define AI_SITE  0xC05E2200u    /* Thumb: bl FUN_c05d6bb8 (keyframe image name) F7F4FCDA, CHAIN (v2 glyphs) */
#define AI_STOCK 0xFCDAF7F4u
#define T_VENEER_IP 0xC004F8DFu /* Thumb: ldr.w ip, [pc, #4]; ldr.w pc, [pc, #4]; .word context; .word stub (ARM) */
#define T_VENEER_PC 0xF004F8DFu
#define GUITAB_STOCK 0xC2E412BCu
#define SET_SEL      0xC31B954Cu
#define SET_BANK_A   0xC31B32BCu
#define SET_BANK_B   0xC31B8B84u
#define OFF_COLOR    0x12Cu
#define ROOT         COLS_ROOT
#define KEY_MODE     0xC3414D14u        /* FUN_c02cf490's last mode */
#define KEY_CTX0     0xC2F19D44u        /* FUN_c02d29e0 ctx0 cache key */
#define KEY_CTX1     0xC2F19D48u        /* ctx1 (stills): 11-05 JPEGs kept the previous LUT's tone */
#define POFF_MGR     0xC0023A98u
#define POFF_ADD     0xC0024118u
#define VENEER_IP    0xE59FC000u        /* ldr ip, [pc]; ldr pc, [pc]; .word context; .word stub */
#define MEM_HEAP     0xC001CF78u        /* the firmware allocator (sloader4.c mem_*, lut borrow.c): class 0 */
#define MEM_GET      0xC001D038u
#define MEM_FREE     0xC001D2B8u
#define CS_LINE      64u
#define VENEER_PC    0xE59FF000u

/* colshare_ui.section(): what the host made */
struct cs_section {
    u32 magic, block_off, block_len, icon_cap;
    u32 csv_stock[3], csv_size[3];   /* the stock ListColorButtonMenu CSVs in the image (the camera adds the rows) */
    u32 csv_tail[3];             /* _EXCL / _EXCL2: what follows "NO" on an added row (a string of the block); 0 main */
    u32 csv_field[4];            /* the main CSV's two edited cells: {offset, length} x 2 (in the stock file) */
    u32 donor_stock[CS_MAX], donor_name[CS_MAX];   /* row j's icon file; its name without .xci (a string) */
    u32 tile_off[CS_TILES], tile_len[CS_TILES];    /* placeholder tiles (a client without an icon) */
    u32 page_float[7], text_off, text_base, fv_entry, fv_table_word;
    u32 cap_words[CS_MAX + 1];   /* BE float 15 + n, as the bytes go in memory */
    u32 probe_off, n_probe;      /* raw-view files: \fpSup\NAME\0 ... */
    u32 rawview_id, rawview_client;   /* header version >= rawview_client: a COL-Share client (P3) */
    u32 label_at[CS_MAX];        /* row j's big label: a placeholder string of the block, CS_LABEL bytes */
    u32 ins_pos, ins_len;        /* the label keys' insert (stock position, bytes): our copy's one delta */
    u32 log_old_rawview, log_failed;  /* LOAD.LOG lines (no .rodata) */
};
/* One redirected file: our entry in the shared table (kept for reuse once made; stock word 0 = unused),
 * the allocator's pointer, the copy (cached alias), its capacity and length.  0 = none. */
struct cs_file { u32 entry, raw, buf, cap, len; };
struct cfg { u32 magic, state_off, section_off; };

struct cs_client {
    const struct cols_client *c;
    u32 nrec;
    struct { u32 key; const struct cols_rec *rec; } rec[CS_RECS];
};

/* The state the stubs read (offsets: the asm below; 0..56 as clist.c's). */
struct cols {
    u32 magic;          /* 0   */
    u32 n;              /* 4   rows present */
    u32 active;         /* 8   0 none, 1..n */
    u32 pend;           /* 12  1 = OFF picked, 2..n+1 = row 1..n, 0 = none */
    u32 cur;            /* 16  the COLOR key cursor's GUI row */
    u32 menu;           /* 20  ColorButtonMenu open */
    u32 changed;        /* 24  active moved since the menu opened */
    i32 eff[CS_MAX + 1];/* 28  each row's box value (index 1..n) */
    u32 eff_dirty;      /* 48  */
    u32 on_close;       /* 52  cs_closed (Thumb), r0 = this */
    u32 guitab[2u * CS_GUI_N];   /* 56 {enum, gui} */
    u32 rec[CS_MAX + 1];         /* 216 row j's cols_rec, 0 = none */
    u32 shown;                   /* 236 the row the root shows (0 = stock) */
    u32 shown_rec;               /* 240 the record written (0 = stock) */
    u32 down;                    /* 244 power-off ran: the root stays stock */
    i32 effmin[CS_MAX + 1];      /* 248 */
    i32 effmax[CS_MAX + 1];      /* 268 */
    u32 root_stock[COLS_ROOT_WORDS];   /* 288 the root at the entry, after the claims' repair */
    /* C only */
    struct cols_api api;
    const struct sl_svc *svc; const struct cfg *cfg; void *block; const struct cs_section *sec;
    struct cs_client cl[CS_CLIENTS];
    u32 ncl;
    u32 row_sup[CS_MAX + 1], row_key[CS_MAX + 1];
    u32 page, table, installed, pushed, result;
    u32 pend_pick, pend_eff, sync_pending, told_sup, told_key;
    u32 poff[4], poffs, syncs, deferred, rejected, poff_missing;
    /* API v2 (Bei 11-08): each row's box, read by the asm (offsets below) */
    u32 snap[CS_MAX + 1];        /* 888 COLS_R_SNAP */
    u32 live[CS_MAX + 1];        /* 908 int32_t * or 0 */
    u32 glyph[CS_MAX + 1];       /* 928 {n, (from, to) x n} or 0 */
    u32 ai_next;                 /* 948 the glyph site's next layer (Thumb) */
    /* v3 / 12 rows (Bei 11-10): the redirected copies, only for rows that exist */
    struct cs_file file[CS_FILES];
    u32 n_csv;                   /* the rows the CSV copies hold (0 = none: stock) */
    u32 heap, allocs, frees, alloc_failed, sync_late;   /* bytes held now; counts */
    u32 on_cursor;               /* cs_cursor (Thumb), called by cs_stub_mc after the root write: the preview */
    u32 previews;                /* cursor steps handed to a client's preview() */
#if CS_TEST_ROWS
    struct cols_client tc;       /* rows-test: the built-in dummy client (no record: the root never moves) */
    u32 tpick;
    char tname[CS_TEST_ROWS][12];
#endif
};
/* The asm's offsets into struct cols: the product's numbers at CS_MAX 4 (asserted below); 32 B a row more. */
#define O_EFF       28
#define O_EFF_DIRTY (O_EFF + 4 * (CS_MAX + 1))
#define O_ON_CLOSE  (O_EFF_DIRTY + 4)
#define O_GUITAB    (O_ON_CLOSE + 4)
#define O_REC       (O_GUITAB + 8 * (16 + CS_MAX))
#define O_SHOWN     (O_REC + 4 * (CS_MAX + 1))
#define O_SHOWN_REC (O_SHOWN + 4)
#define O_DOWN      (O_SHOWN_REC + 4)
#define O_EFFMIN    (O_DOWN + 4)
#define O_EFFMAX    (O_EFFMIN + 4 * (CS_MAX + 1))
#define O_ROOT_STK  (O_EFFMAX + 4 * (CS_MAX + 1))
#define O_API       (O_ROOT_STK + 4 * COLS_ROOT_WORDS)
#define O_PEND_PICK (O_API + 40 + 16 + CS_CLIENTS * (8 + 8 * CS_RECS) + 4 + 8 * (CS_MAX + 1) + 20)   /* build_colshare.layout */
#define O_SNAP      (O_PEND_PICK + 56)
#define O_LIVE      (O_SNAP + 4 * (CS_MAX + 1))
#define O_GLYPH     (O_LIVE + 4 * (CS_MAX + 1))
#define O_AI_NEXT   (O_GLYPH + 4 * (CS_MAX + 1))
#define S_(x) #x
#define S(x) S_(x)
#if CS_MAX == 4
_Static_assert(O_EFF_DIRTY == 48 && O_GUITAB == 56 && O_REC == 216 && O_SHOWN == 236 && O_SHOWN_REC == 240 &&
               O_DOWN == 244 && O_EFFMIN == 248 && O_EFFMAX == 268 && O_ROOT_STK == 288 && O_SNAP == 888 &&
               O_LIVE == 908 && O_GLYPH == 928 && O_AI_NEXT == 948, "the product's offsets");
#endif
_Static_assert(__builtin_offsetof(struct cols, eff) == O_EFF, "cols.eff");
_Static_assert(__builtin_offsetof(struct cols, eff_dirty) == O_EFF_DIRTY, "cols.eff_dirty");
_Static_assert(__builtin_offsetof(struct cols, on_close) == O_ON_CLOSE, "cols.on_close");
_Static_assert(__builtin_offsetof(struct cols, guitab) == O_GUITAB, "cols.guitab");
_Static_assert(__builtin_offsetof(struct cols, rec) == O_REC, "cols.rec");
_Static_assert(__builtin_offsetof(struct cols, shown) == O_SHOWN, "cols.shown");
_Static_assert(__builtin_offsetof(struct cols, shown_rec) == O_SHOWN_REC, "cols.shown_rec");
_Static_assert(__builtin_offsetof(struct cols, down) == O_DOWN, "cols.down");
_Static_assert(__builtin_offsetof(struct cols, effmin) == O_EFFMIN, "cols.effmin");
_Static_assert(__builtin_offsetof(struct cols, effmax) == O_EFFMAX, "cols.effmax");
_Static_assert(__builtin_offsetof(struct cols, root_stock) == O_ROOT_STK, "cols.root_stock");
_Static_assert(__builtin_offsetof(struct cols, api) == O_API, "cols.api");
_Static_assert(sizeof(struct cols_api) == 40, "cols_api v3");
_Static_assert(__builtin_offsetof(struct cols, pend_pick) == O_PEND_PICK, "cols.pend_pick");
_Static_assert(__builtin_offsetof(struct cols, snap) == O_SNAP, "cols.snap");
_Static_assert(__builtin_offsetof(struct cols, file) == O_SNAP + 12 * (CS_MAX + 1) + 4, "cols.file (build_colshare.layout)");
#define O_ON_CURSOR (O_SNAP + 12 * (CS_MAX + 1) + 4 + 20 * CS_FILES + 24)
_Static_assert(__builtin_offsetof(struct cols, on_cursor) == O_ON_CURSOR, "cols.on_cursor (build_colshare.layout)");
_Static_assert(__builtin_offsetof(struct cols, live) == O_LIVE, "cols.live");
_Static_assert(__builtin_offsetof(struct cols, glyph) == O_GLYPH, "cols.glyph");
_Static_assert(__builtin_offsetof(struct cols, ai_next) == O_AI_NEXT, "cols.ai_next");
_Static_assert(O_ROOT_STK <= 1020, "add rX, r3, #imm: an ARM immediate (a multiple of 4 up to 1020)");
_Static_assert(16 + CS_MAX <= 255, "the getter's mov r2, #n");
_Static_assert(sizeof(struct cols) <= CS_STATE, "state reservation (build_colshare.STATE)");
_Static_assert(sizeof(struct cols_rec) == 4u + 8u * COLS_REC_MAX, "cols_rec");

__asm__(
"   .text\n"
"   .balign 4\n"
"   .arm\n"
/* GUI -> enum (menu, COLOR key, QS; the preview's): note the pick, tail to the stock one */
"cs_stub_mj:\n"
"   mov     r3, ip\n"
"   ldr     ip, =0xC06C07E8\n"
"   b       1f\n"
"cs_stub_ma:\n"
"   mov     r3, ip\n"
"   ldr     ip, =0xC06C0718\n"
"1: push    {ip}\n"
"   ldr     r2, [r3, #4]\n"
"   add     r2, r2, #16\n"
"   cmp     r1, #15\n"
"   blo     2f\n"
"   cmp     r1, r2\n"
"   bhs     2f\n"
"   sub     r2, r1, #14\n"
"   b       3f\n"
"2: mov     r2, #0\n"
"3: ldr     ip, =0xC05818BC\n"             /* QS: its list has no rows of ours; its 15 is a resync */
"   cmp     lr, ip\n"
"   moveq   r2, #0\n"
"   strne   r1, [r3, #16]\n"
"   str     r2, [r3, #12]\n"
"   pop     {pc}\n"
/* enum -> GUI (CM_COLFIX): OFF while a row is active is that row */
"cs_stub_mb:\n"
"   push    {r4, lr}\n"
"   mov     r4, ip\n"
"   ldr     ip, =0xC06C0768\n"
"   blx     ip\n"
"   cmp     r0, #15\n"
"   bne     1f\n"
"   ldr     r1, [r4, #8]\n"
"   cmp     r1, #0\n"
"   addne   r0, r1, #15\n"
"1: pop     {r4, pc}\n"
/* enum -> GUI for LV_ColorMode: 16.. are its monochrome tint icons */
"cs_stub_ml:\n"
"   push    {r4, lr}\n"
"   ldr     ip, =0xC06C0768\n"
"   blx     ip\n"
"   cmp     r0, #16\n"
"   movhs   r0, #15\n"
"   pop     {r4, pc}\n"
/* the setter's cmp sl, r6 (r4 item, sl old, r6 new); r0-r3 / ip, r4-r7 saved around the root write */
"cs_stub_mc:\n"
"   mov     r3, ip\n"
"   ldr     ip, =0xC31ACDC4\n"
"   cmp     r4, ip\n"
"   bne     9f\n"
"   ldr     r1, [r3, #12]\n"
"   mov     r2, #0\n"
"   str     r2, [r3, #12]\n"
"   ldr     r0, [r3, #8]\n"                /* r0 = old active */
"   mov     r2, r0\n"
"   cmp     r1, #1\n"
"   moveq   r2, #0\n"
"   cmp     r1, #2\n"
"   subhs   r2, r1, #1\n"
"   cmp     r6, #0xC\n"
"   movne   r2, #0\n"                      /* not OFF: no row */
"   cmp     r2, r0\n"
"   beq     9f\n"
"   str     r2, [r3, #8]\n"
"   mov     ip, #1\n"
"   str     ip, [r3, #24]\n"
"   add     r1, r3, #(" S(O_GUITAB) " + 15 * 8 + 4)\n"   /* enum 0xC's GUIs: the active one first */
"   add     r2, r2, #15\n"
"   str     r2, [r1], #8\n"
"   mov     ip, #15\n"
"5: cmp     ip, r2\n"
"   strne   ip, [r1], #8\n"
"   add     ip, ip, #1\n"
"   cmp     ip, #" S(16 + CS_MAX) "\n"
"   blo     5b\n"
"   sub     r2, r2, #15\n"
/* the root at once, from the client's record: the cursor shows the row */
"   ldr     ip, [r3, #" S(O_DOWN) "]\n"
"   cmp     ip, #0\n"
"   bne     17f\n"                         /* after power-off: stock stays */
"   mov     r1, #0\n"
"   cmp     r2, #0\n"
"   beq     10f\n"
"   add     r1, r3, #" S(O_REC) "\n"
"   ldr     r1, [r1, r2, lsl #2]\n"       /* rec[row] */
"   cmp     r1, #0\n"
"   beq     17f\n"                         /* none yet: the root stays */
"   b       11f\n"
"10:ldr     r0, [r3, #" S(O_SHOWN_REC) "]\n"
"   cmp     r0, #0\n"
"   beq     17f\n"                         /* to stock, stock shown: nothing */
"11:push    {r4-r7}\n"
"   ldr     r0, [r3, #" S(O_SHOWN_REC) "]\n"              /* r0 old record, r1 new (0 = stock) */
"   ldr     r4, =0xC2F1A064\n"
"   cmp     r0, #0\n"
"   beq     14f\n"
"   ldr     r5, [r0]\n"
"12:subs    r5, r5, #1\n"                  /* the old one's words in reverse: stock, unless the new one writes it */
"   bmi     14f\n"
"   add     r6, r0, r5, lsl #3\n"
"   ldrh    r6, [r6, #4]\n"
"   cmp     r1, #0\n"
"   beq     13f\n"
"   ldr     r7, [r1]\n"
"18:subs    r7, r7, #1\n"
"   bmi     13f\n"
"   add     ip, r1, r7, lsl #3\n"
"   ldrh    ip, [ip, #4]\n"
"   cmp     ip, r6\n"
"   beq     12b\n"
"   b       18b\n"
"13:add     ip, r3, #" S(O_ROOT_STK) "\n"
"   ldr     ip, [ip, r6]\n"
"   str     ip, [r4, r6]\n"
"   b       12b\n"
"14:cmp     r1, #0\n"
"   beq     16f\n"
"   ldr     r5, [r1]\n"                    /* the new one's words, in its order */
"   add     r6, r1, #4\n"
"15:ldrh    r7, [r6]\n"
"   ldr     ip, [r6, #4]\n"
"   str     ip, [r4, r7]\n"
"   add     r6, r6, #8\n"
"   subs    r5, r5, #1\n"
"   bne     15b\n"
"16:str     r1, [r3, #" S(O_SHOWN_REC) "]\n"
"   cmp     r1, #0\n"
"   moveq   r2, #0\n"
"   str     r2, [r3, #" S(O_SHOWN) "]\n"
"   mvn     ip, #0\n"                       /* the PQ caches re-read the roots (ctx1 too: 11-05) */
"   ldr     r1, =0xC3414D14\n"
"   str     ip, [r1]\n"
"   ldr     r1, =0xC2F19D44\n"
"   str     ip, [r1]\n"
"   ldr     r1, =0xC2F19D48\n"
"   str     ip, [r1]\n"
"   pop     {r4-r7}\n"
"17:push    {r4, lr}\n"                   /* v3 (Bei 11-10): the cursor's row to its client (preview), root already written */
"   mov     r4, sp\n"
"   bic     sp, sp, #7\n"                  /* the firmware may come with sp = 4 (mod 8) */
"   mov     r0, r3\n"
"   ldr     ip, =" S(O_ON_CURSOR) "\n"
"   ldr     ip, [r3, ip]\n"
"   blx     ip\n"
"   mov     sp, r4\n"
"   pop     {r4, lr}\n"
"   movs    r0, #1\n"                      /* Z = 0: the stock 'changed' path notifies */
"   bx      lr\n"
"9: cmp     sl, r6\n"
"   bx      lr\n"
/* Effect box UI -> stored: an active row keeps its own value, in its range */
"cs_stub_ef:\n"
"   mov     r3, ip\n"
"   ldr     r2, [r3, #8]\n"
"   cmp     r2, #0\n"
"   beq     9f\n"
"   mov     r0, r1\n"
"   ldr     ip, =" S(O_SNAP) "\n"                     /* v2 COLS_R_SNAP: a step up is max, down min */
"   add     ip, ip, r3\n"
"   ldr     ip, [ip, r2, lsl #2]\n"
"   cmp     ip, #0\n"
"   beq     4f\n"
"   add     ip, r3, #" S(O_EFF) "\n"
"   ldr     ip, [ip, r2, lsl #2]\n"
"   cmp     r0, ip\n"
"   beq     4f\n"
"   addgt   ip, r3, #" S(O_EFFMAX) "\n"
"   addlt   ip, r3, #" S(O_EFFMIN) "\n"
"   ldr     r0, [ip, r2, lsl #2]\n"
"4: add     ip, r3, #" S(O_EFFMAX) "\n"
"   ldr     ip, [ip, r2, lsl #2]\n"
"   cmp     r0, ip\n"
"   movgt   r0, ip\n"
"   add     ip, r3, #" S(O_EFFMIN) "\n"
"   ldr     ip, [ip, r2, lsl #2]\n"
"   cmp     r0, ip\n"
"   movlt   r0, ip\n"
"   add     ip, r3, #" S(O_EFF) "\n"
"   str     r0, [ip, r2, lsl #2]\n"
"   mov     ip, #1\n"
"   str     ip, [r3, #" S(O_EFF_DIRTY) "]\n"
"   ldr     ip, =" S(O_LIVE) "\n"                     /* v2: the client's live word, at once */
"   add     ip, ip, r3\n"
"   ldr     ip, [ip, r2, lsl #2]\n"
"   cmp     ip, #0\n"
"   strne   r0, [ip]\n"
"   cmp     r0, r1\n"
"   beq     5f\n"
"   push    {r4, lr}\n"                    /* clamped: the box back to the value */
"   mov     r4, r0\n"
"   mov     r0, #0\n"
"   ldr     r1, =0xC2DF0210\n"
"   mov     r2, r4\n"
"   ldr     ip, =0xC0593F30\n"
"   blx     ip\n"
"   mov     r0, #0\n"
"   ldr     r1, =0xC2DF01A8\n"
"   mov     r2, r4\n"
"   ldr     ip, =0xC0593F30\n"
"   blx     ip\n"
"   pop     {r4, lr}\n"
"5: mov     r0, #0\n"
"   bx      lr\n"
"9: ldr     pc, =0xC06C0D20\n"
/* Effect stored -> UI (v87 / v82; r7 = mode): the active row's value */
"cs_stub_en:\n"
"   mov     r3, ip\n"
"   ldr     r2, [r3, #8]\n"
"   cmp     r2, #0\n"
"   beq     9f\n"
"   cmp     r7, #0xC\n"
"   bne     9f\n"
"   add     ip, r3, #" S(O_EFF) "\n"
"   ldr     r0, [ip, r2, lsl #2]\n"
"   bx      lr\n"
"9: ldr     pc, =0xC06C0D70\n"
/* ColorButtonMenu open / close (vtable v25 / v26) */
"cs_stub_mo:\n"
"   mov     r3, ip\n"
"   mov     ip, #1\n"
"   str     ip, [r3, #20]\n"
"   mov     ip, #0\n"
"   str     ip, [r3, #24]\n"
"   str     ip, [r3, #" S(O_EFF_DIRTY) "]\n"
"   ldr     pc, =0xC05687E0\n"
"cs_stub_mx:\n"
"   push    {r0-r4, lr}\n"
"   mov     r4, ip\n"
"   mov     ip, #0\n"
"   str     ip, [r4, #20]\n"
"   ldr     ip, [r4, #" S(O_ON_CLOSE) "]\n"               /* always: a deferred sync / delivery may wait */
"   mov     r0, r4\n"
"   blx     ip\n"
"   pop     {r0-r4, lr}\n"
"   ldr     pc, =0xC0568888\n"
/* v2: the effect box's keyframe glyph names (Thumb C05E2200 `bl FUN_c05d6bb8`, CHAIN; raw-view 0.3.1's stub_ai):
 * r0 node, r1 attribute, r2 image name (a pointer into the current string pool), fp the container (+0x18 its id).
 * While the cursor's row is the active one and its client gave a glyph table: the box's sign (0x177) / number
 * (0x178) names are swapped by pool offset.  Reached by BL -> Thumb veneer (ldr.w ip / ldr.w pc), lr untouched;
 * r0-r3 / ip usable, r4-r7 saved; no call, so any sp. */
"cs_stub_ai:\n"
"   push    {r4-r7}\n"
"   mov     r3, ip\n"
"   ldr     r4, [r3, #16]\n"                /* cur: GUI row; ours are 16.. */
"   sub     r4, r4, #15\n"
"   cmp     r4, #1\n"
"   blt     8f\n"
"   ldr     r5, [r3, #4]\n"
"   cmp     r4, r5\n"
"   bhi     8f\n"
"   ldr     r5, [r3, #8]\n"
"   cmp     r4, r5\n"
"   bne     8f\n"                           /* not the active row */
"   ldr     r5, =" S(O_GLYPH) "\n"
"   add     r5, r5, r3\n"
"   ldr     r5, [r5, r4, lsl #2]\n"
"   cmp     r5, #0\n"
"   beq     8f\n"
"   ldr     r4, [fp, #0x18]\n"
"   sub     r4, r4, #0x170\n"
"   sub     r4, r4, #7\n"
"   cmp     r4, #1\n"                       /* 0x177 sign, 0x178 number */
"   bhi     8f\n"
"   ldr     r6, =0xC37B7048\n"              /* the current string pool: app -> screen 0 -> reader +0x14 */
"   ldr     r6, [r6]\n"
"   cmp     r6, #0\n"
"   beq     7f\n"
"   ldr     r6, [r6, #0x8C]\n"
"   cmp     r6, #0\n"
"   beq     7f\n"
"   ldr     r6, [r6]\n"
"   cmp     r6, #0\n"
"   beq     7f\n"
"   ldr     r6, [r6, #0x24]\n"
"   cmp     r6, #0\n"
"   beq     7f\n"
"   ldr     r6, [r6, #0x14]\n"
"   cmp     r6, #0\n"
"   bne     6f\n"
"7: ldr     r6, =0xC18C0474\n"              /* not up yet: the stock pool */
"6: sub     ip, r2, r6\n"
"   ldr     r7, [r5], #4\n"
"   cmp     r7, #4\n"
"   movhi   r7, #0\n"
"   cmp     r7, #0\n"
"   beq     8f\n"
"1: ldr     r4, [r5], #8\n"
"   cmp     ip, r4\n"
"   ldreq   r4, [r5, #-4]\n"
"   addeq   r2, r6, r4\n"
"   beq     8f\n"
"   subs    r7, r7, #1\n"
"   bne     1b\n"
"8: pop     {r4-r7}\n"
"   ldr     pc, [r3, #" S(O_AI_NEXT) "]\n"
/* power-off: vtbl[+0xC](obj, reason), obj = {obj - 8, this stub, state, cs_poweroff}; sp may be = 4 (mod 8) */
"cs_poff_stub:\n"
"   push    {r4, lr}\n"
"   mov     r4, sp\n"
"   bic     sp, sp, #7\n"
"   ldr     ip, [r0, #12]\n"
"   ldr     r0, [r0, #8]\n"
"   blx     ip\n"
"   mov     sp, r4\n"
"   pop     {r4, pc}\n"
"   .ltorg\n"
"   .thumb\n");
extern const u8 cs_stub_ma[], cs_stub_mj[], cs_stub_mb[], cs_stub_ml[], cs_stub_mc[],
    cs_stub_ef[], cs_stub_en[], cs_stub_mo[], cs_stub_mx[], cs_poff_stub[], cs_stub_ai[];

static u32 rd(u32 a) { return *(volatile const u32 *)(uintptr_t)a; }
static void wr(u32 a, u32 v) { *(volatile u32 *)(uintptr_t)a = v; }
static u32 bl_to(u32 site, u32 dest) { return 0xEB000000u | (((dest - site - 8u) >> 2) & 0xFFFFFFu); }
static u32 thumb_bl(u32 site, u32 dest) {               /* BL (T1) site -> dest (Thumb) */
    u32 off = dest - (site + 4u), sg = off >> 31, j1 = (~(off >> 23) ^ sg) & 1u, j2 = (~(off >> 22) ^ sg) & 1u;
    return (0xF000u | sg << 10 | ((off >> 12) & 0x3FFu)) | (0xD000u | j1 << 13 | j2 << 11 | ((off >> 1) & 0x7FFu)) << 16;
}
static u32 movw_of(u32 w, u32 v) { return (w & 0xFFF0F000u) | ((v & 0xF000u) << 4) | (v & 0xFFFu); }
static void copy(void *d, const void *s, u32 n) { u8 *a = d; const u8 *b = s; for (u32 i = 0; i < n; i++) a[i] = b[i]; }
static void put_bytes(u32 at, u32 w) { for (u32 k = 0; k < 4u; k++) *(volatile u8 *)(uintptr_t)(at + k) = (u8)(w >> (24u - 8u * k)); }
static struct cols *of_api(const struct cols_api *a) {
    return (struct cols *)(uintptr_t)((uintptr_t)a - __builtin_offsetof(struct cols, api));
}
static u32 color_setting(void) {
    u32 bank = *(volatile const u8 *)(uintptr_t)SET_SEL ? SET_BANK_B : SET_BANK_A;
    return rd(bank + OFF_COLOR);
}
/* Movie recording (movie-recording-flag-selector): 0xC347D1C0+0x14 == 0x21 -> 0xC34765CC+0x3D, else +0x157's. */
static int recording(void) {
    u32 sel = rd(0xC347D1D4u);
    return *(volatile const u8 *)(uintptr_t)(sel == 0x21u ? 0xC3476609u : 0xC347E08Fu) != 0;
}
static void keys(void) { wr(KEY_MODE, 0xFFFFFFFFu); wr(KEY_CTX0, 0xFFFFFFFFu); wr(KEY_CTX1, 0xFFFFFFFFu); }

/* ---- the root, from C: the same transition as cs_stub_mc ---- */
static int rec_has(const struct cols_rec *r, u32 off) {
    for (u32 k = 0; r && k < r->n; k++) if (r->w[k].off == off) return 1;
    return 0;
}
static int rec_holds(const struct cols_rec *r) {          /* the root holds every word of r already */
    for (u32 k = 0; k < r->n; k++) if (rd(ROOT + r->w[k].off) != r->w[k].val) return 0;
    return 1;
}
static void root_write(struct cols *L, const struct cols_rec *to, u32 row) {
    const struct cols_rec *from = (const struct cols_rec *)(uintptr_t)L->shown_rec;
    L->svc->publish(L->svc);                              /* the tables reach memory before the ISP is told */
    for (u32 k = from ? from->n : 0; k-- > 0;) {
        u32 off = from->w[k].off;
        if (!rec_has(to, off)) wr(ROOT + off, L->root_stock[off >> 2]);
    }
    for (u32 k = 0; to && k < to->n; k++) wr(ROOT + to->w[k].off, to->w[k].val);
    L->shown_rec = (u32)(uintptr_t)to;
    L->shown = to ? row : 0;
    keys();
}
/* The root to row `row` (0 = stock); only a move re-reads the PQ caches (lvb_show's rule). */
static void show(struct cols *L, u32 row) {
    if (L->down) return;
    const struct cols_rec *to = row && row <= L->n ? (const struct cols_rec *)(uintptr_t)L->rec[row] : 0;
    if (row && !to) return;                               /* no record yet: the root stays */
    if (!to) { if (L->shown_rec) root_write(L, 0, 0); L->shown = 0; return; }
    if (L->shown_rec != (u32)(uintptr_t)to || !rec_holds(to)) root_write(L, to, row);
    L->shown = row;
}

/* ---- the shared redirect table (fpui_stock.c fst_hook_fv's): FSFV {stock, copy, size} ---- */
static u32 cs_table(const struct cs_section *c) {
    u32 w = rd(FV_SITE), hw1 = w & 0xFFFFu, hw2 = w >> 16, s, j1, j2, i1, i2, off;
    if ((hw1 & 0xF800u) != 0xF000u || (hw2 & 0xD000u) != 0x9000u) return 0;
    s = (hw1 >> 10) & 1u; j1 = (hw2 >> 13) & 1u; j2 = (hw2 >> 11) & 1u; i1 = 1u ^ (j1 ^ s); i2 = 1u ^ (j2 ^ s);
    off = s << 24 | i1 << 23 | i2 << 22 | (hw1 & 0x3FFu) << 12 | (hw2 & 0x7FFu) << 1; if (s) off |= 0xFE000000u;
    u32 veneer = FV_SITE + 4u + off, entry, table;
    if (veneer & 3u) return 0;
    entry = rd(veneer + 4u);
    if (entry & 3u) return 0;
    table = rd(entry - c->fv_entry + c->fv_table_word);
    return !table || (table & 3u) || rd(table) != 0x56465346u ? 0 : table;
}

/* ---- the copies (Bei 11-10: nothing for rows that do not exist; each sized to its content) ----
 * Only from sync(): the COLOR menu is closed (its views of the old copies are gone) and no movie is being
 * recorded (the movie's allocations come first, allocator-not-across-recording).  An entry is never removed
 * (another sup may hold its address): unused, its stock word is 0, which no file address equals. */
static void cs_unlink(struct cols *L, u32 k) {
    struct cs_file *f = &L->file[k];
    if (f->entry && rd(f->entry)) { wr(f->entry, 0); L->svc->publish(L->svc); }
}
static void cs_drop(struct cols *L, u32 k) {
    struct cs_file *f = &L->file[k];
    cs_unlink(L, k);
    if (f->raw) {
        FW(MEM_FREE, void (*)(void *, void *))(FW(MEM_HEAP, void *(*)(u32))(0), (void *)(uintptr_t)f->raw);
        L->heap -= f->cap + CS_LINE; L->frees++;
    }
    f->raw = f->buf = f->cap = f->len = 0;
}
/* A copy of n bytes for file k (unlinked: the stock file is served while it is written); 0 = no memory. */
static u8 *cs_fbuf(struct cols *L, u32 k, u32 n) {
    struct cs_file *f = &L->file[k];
    u32 cap = (n + CS_LINE - 1u) & ~(CS_LINE - 1u);
    cs_unlink(L, k);
    if (f->raw && f->cap == cap) return (u8 *)(uintptr_t)f->buf;
    cs_drop(L, k);
    void *h = FW(MEM_HEAP, void *(*)(u32))(0);
    u32 raw = h ? (u32)(uintptr_t)FW(MEM_GET, void *(*)(void *, u32, u32, u32, u32))(h, cap + CS_LINE, 0, 0, 0) : 0;
    if (!raw) { L->alloc_failed++; return 0; }
    u32 ub = (raw + CS_LINE - 1u) & ~(CS_LINE - 1u);
    if (ub >= 0x40000000u && ub < 0x80000000u) ub += SL_ALIAS;    /* used at the cached alias (fpui_stock fst_alloc) */
    L->svc->publish(L->svc);
    f->raw = raw; f->buf = ub; f->cap = cap; L->heap += cap + CS_LINE; L->allocs++;
    return (u8 *)(uintptr_t)ub;
}
/* File k's copy (cs_fbuf'd, n bytes written) served for `stock`: our entry, else a new one at the table's end. */
static int cs_link(struct cols *L, u32 k, u32 stock, u32 n) {
    struct cs_file *f = &L->file[k];
    u32 t = L->table, e = f->entry;
    if (!e) {
        u32 cnt = rd(t + 8u);
        for (u32 i = 0; i < cnt && i < 256u; i++) if (rd(t + 16u + 12u * i) == stock) return 0;   /* someone else's */
        if (cnt >= rd(t + 12u)) return 0;                                       /* the table is full */
        e = t + 16u + 12u * cnt;
        wr(e, 0); L->svc->publish(L->svc);
        wr(t + 8u, cnt + 1u);
        f->entry = e;
    }
    f->len = n;
    wr(e + 4u, f->buf); wr(e + 8u, n);
    L->svc->publish(L->svc);                              /* the copy and its size before the handler can match */
    wr(e, stock);
    L->svc->publish(L->svc);
    return 1;
}
static u32 cs_ch(u8 *out, u32 at, u32 ch) { if (out) out[at] = (u8)ch; return at + 1u; }
static u32 cs_mem(u8 *out, u32 at, const u8 *s, u32 n) { for (u32 i = 0; i < n; i++) at = cs_ch(out, at, s[i]); return at; }
static u32 cs_str(u8 *out, u32 at, const char *s) { while (*s) at = cs_ch(out, at, (u8)*s++); return at; }
static u32 cs_num(u8 *out, u32 at, u32 v) {     /* v < 1000 (row numbers); no divide instruction */
    u32 h = 0, d = 0;
    while (v >= 100u) { v -= 100u; h++; }
    while (v >= 10u) { v -= 10u; d++; }
    if (h) at = cs_ch(out, at, '0' + h);
    if (h || d) at = cs_ch(out, at, '0' + d);
    return cs_ch(out, at, '0' + v);
}
/* CSV f with n rows after the stock sixteen (colshare_ui.rows_csv: the same bytes); out 0 = the length only.
 * Main list: a ring -- the first row's Left is the last added row, OFF's Right the first. */
static u32 cs_csv(const struct cols *L, u32 f, u32 n, u8 *out) {
    const struct cs_section *c = L->sec;
    const u8 *src = (const u8 *)(uintptr_t)c->csv_stock[f], *blk = (const u8 *)L->block;
    u32 size = c->csv_size[f], at = 0;
    if (f == 0u) {
        u32 o1 = c->csv_field[0], e1 = o1 + c->csv_field[1], o2 = c->csv_field[2], e2 = o2 + c->csv_field[3];
        at = cs_mem(out, at, src, o1); at = cs_num(out, at, 15u + n);
        at = cs_mem(out, at, src + e1, o2 - e1); at = cs_num(out, at, 16u);
        at = cs_mem(out, at, src + e2, size - e2);
    } else at = cs_mem(out, at, src, size);
    for (u32 j = 0; j < n; j++) {
        u32 k = 16u + j;
        at = cs_num(out, at, k + 1u);
        if (f == 0u) {
            at = cs_ch(out, at, ','); at = cs_str(out, at, (const char *)blk + c->donor_name[j]);
            at = cs_ch(out, at, ','); at = cs_ch(out, at, '0'); at = cs_ch(out, at, ',');
            at = cs_num(out, at, k - 1u); at = cs_ch(out, at, ',');
            at = cs_num(out, at, j + 1u < n ? k + 1u : 0u); at = cs_ch(out, at, ',');
            at = cs_num(out, at, k); at = cs_ch(out, at, '\r'); at = cs_ch(out, at, '\n');
        } else at = cs_str(out, at, (const char *)blk + c->csv_tail[f]);
    }
    return at;
}
/* The three CSVs for n rows (n 0: none -- the stock files).  0 = a copy could not be made. */
static int cs_csvs(struct cols *L, u32 n) {
    const struct cs_section *c = L->sec;
    if (n == L->n_csv) return 1;
    for (u32 f = 0; f < 3u; f++) {
        if (!n) { cs_drop(L, f); continue; }
        u32 len = cs_csv(L, f, n, 0);
        u8 *b = cs_fbuf(L, f, len);
        if (!b) { L->n_csv = ~0u; return 0; }             /* unknown now: a following cs_csvs(0) drops them all */
        cs_csv(L, f, n, b);
        if (!cs_link(L, f, c->csv_stock[f], len)) { L->n_csv = ~0u; return 0; }
    }
    L->n_csv = n;
    return 1;
}
/* Row j's icon (1-based): the client's tile, else a placeholder; 0 = row j has none (the donor stays stock). */
static void cs_icon(struct cols *L, u32 j, const u8 *icon, u32 len) {
    const struct cs_section *c = L->sec;
    if (!icon || !len || len > c->icon_cap) {
        u32 t = j - 1u < CS_TILES ? j - 1u : CS_TILES - 1u;
        icon = (const u8 *)L->block + c->tile_off[t]; len = c->tile_len[t];
    }
    u8 *b = cs_fbuf(L, 2u + j, len);
    if (!b) return;
    copy(b, icon, len);
    if (!cs_link(L, 2u + j, c->donor_stock[j - 1u], len)) cs_drop(L, 2u + j);
}

/* the COLOR menu's cursor variables (clist.c clist_post, 11-05): 15 = OFF, 15 + j = row j */
static void post(struct cols *L) {
    u32 g = 15u + L->active;
    FW(0xC0593F30u, void (*)(u32, u32, u32))(0, 0xC2DF0168u, g);
    FW(0xC0593F30u, void (*)(u32, u32, u32))(0, 0xC2DF017Cu, g);
    L->pushed = g + 1u;
}
static void label(const char *name, char *out) {
    u32 n = 0;
    for (u32 i = 0; name && name[i] && n < CS_LABEL; i++) { u8 ch = (u8)name[i]; out[n++] = (char)(ch >= 0x20u && ch <= 0x7Eu ? ch : '?'); }
    if (!n) out[n++] = '?';
    out[n] = 0;
}

static struct cs_client *client_of(struct cols *L, u32 sup) {
    for (u32 k = 0; k < L->ncl; k++) if (L->cl[k].c->sup_id == sup) return &L->cl[k];
    return 0;
}
static const struct cols_rec *rec_of(struct cs_client *k, u32 key) {
    for (u32 i = 0; i < k->nrec; i++) if (k->rec[i].key == key) return k->rec[i].rec;
    return 0;
}
static u32 row_of(struct cols *L, u32 sup, u32 key) {
    for (u32 j = 1; j <= L->n; j++) if (L->row_sup[j] == sup && L->row_key[j] == key) return j;
    return 0;
}

static int dup_row(struct cols *L, u32 n, u32 sup, u32 key) {
    for (u32 j = 1; j <= n; j++) if (L->row_sup[j] == sup && L->row_key[j] == key) return 1;
    return 0;
}
static int still_picked(struct cols *L, u32 sup, u32 key) {
    struct cs_client *k = client_of(L, sup);
    return k && k->c->picked && k->c->picked(k->c->arg) == key + 1u;
}

/* Undelivered picks / box values go to the clients: never while recording. */
static void deliver(struct cols *L) {
    if (!L->pend_pick && !L->pend_eff) return;
    if (recording()) { L->deferred++; return; }
    if (L->pend_pick) {
        L->pend_pick = 0;
        u32 a = L->active && L->active <= L->n ? L->active : 0;
        u32 ns = a ? L->row_sup[a] : 0, nk = a ? L->row_key[a] : COLS_NONE;
        struct cs_client *old = L->told_sup && L->told_sup != ns ? client_of(L, L->told_sup) : 0;
        if (old) old->c->on_pick(old->c->arg, COLS_NONE);
        struct cs_client *now = ns ? client_of(L, ns) : 0;
        if (now) now->c->on_pick(now->c->arg, nk);
        L->told_sup = ns; L->told_key = nk;
        post(L);
    }
    if (L->pend_eff) {
        L->pend_eff = 0;
        u32 a = L->active;
        if (a && a <= L->n && (L->effmin[a] || L->effmax[a])) {
            struct cs_client *k = client_of(L, L->row_sup[a]);
            if (k && k->c->strength_set) k->c->strength_set(k->c->arg, L->row_key[a], L->eff[a]);
        }
    }
}

/* The rows to what the clients offer now: CSVs, row limits, icons, labels, GUI table, active, the root. */
static void sync(struct cols *L) {
    const struct cs_section *c = L->sec;
    if (!L->installed) return;
    if (L->menu) { L->sync_pending = 1; return; }       /* never while the COLOR menu is open */
    if (recording()) { L->sync_pending = 1; L->sync_late++; return; }   /* the copies' allocations: not during a take */
    L->sync_pending = 0; L->syncs++;
    u32 act_sup = L->active && L->active <= L->n ? L->row_sup[L->active] : 0, act_key = L->row_key[L->active];
    u32 sh_sup = L->shown && L->shown <= L->n ? L->row_sup[L->shown] : 0, sh_key = L->row_key[L->shown];
    u32 n = 0;
    struct cols_row r[CS_MAX];
    for (u32 k = 0; k < L->ncl && n < CS_MAX; k++) {
        const struct cols_client *cc = L->cl[k].c;
        u32 got = cc->rows(cc->arg, r, CS_MAX - n);
        if (got > CS_MAX - n) got = CS_MAX - n;
        for (u32 i = 0; i < got; i++) {
            if ((r[i].flags & ~(cc->api >= 2u ? COLS_R_SNAP : 0u)) || r[i].key == COLS_NONE || r[i].eff_min < -5 || r[i].eff_max > 5 || r[i].eff_min > r[i].eff_max ||
                dup_row(L, n, cc->sup_id, r[i].key)) { L->rejected++; continue; }
            u32 j = ++n;
            L->row_sup[j] = cc->sup_id; L->row_key[j] = r[i].key;
            L->effmin[j] = r[i].eff_min; L->effmax[j] = r[i].eff_max;
            L->snap[j] = r[i].flags & COLS_R_SNAP;
            const struct cols_box *b = cc->api >= 2u && cc->box ? cc->box(cc->arg, r[i].key) : 0;
            L->live[j] = b ? (u32)(uintptr_t)b->live : 0;
            L->glyph[j] = b && b->glyphs && b->glyphs[0] <= COLS_GLYPH_MAX ? (u32)(uintptr_t)b->glyphs : 0;
            label(r[i].name, (char *)L->block + c->label_at[j - 1u]);
        }
    }
    if (n && !cs_csvs(L, n)) n = 0;                       /* no copies, no rows: the stock sixteen */
    if (!n) cs_csvs(L, 0);
    for (u32 j = n + 1u; j <= CS_MAX; j++) { L->row_sup[j] = 0; L->row_key[j] = COLS_NONE; L->rec[j] = 0; L->effmin[j] = L->effmax[j] = 0;
                                             L->snap[j] = L->live[j] = L->glyph[j] = 0; cs_drop(L, 2u + j); }
    for (u32 j = 1; j <= n; j++) {
        struct cs_client *k = client_of(L, L->row_sup[j]);
        u32 len = 0;
        const u8 *icon = k && k->c->icon ? k->c->icon(k->c->arg, L->row_key[j], &len) : 0;
        cs_icon(L, j, icon, len);
    }
    for (u32 k = 0; k < L->ncl; k++) {                    /* v3: the tiles are copied, a client may let its scratch go */
        const struct cols_client *cc = L->cl[k].c;
        if (cc->api >= COLS_API_V3 && cc->icon) cc->icon(cc->arg, COLS_NONE, 0);
    }
    u32 hdr = (L->page & ~3u) - 128u;
    if (L->page && rd(hdr + 24u) == 1u && rd(rd(hdr + 32u)) == c->ins_pos && rd(rd(hdr + 32u) + 4u) == c->ins_len) {
        /* our label keys are the copy's only insert: no other sup's, so the offsets hold */
        for (u32 k = 0; k < 7u; k++) put_bytes(L->page + c->page_float[k], c->cap_words[n]);
        put_bytes(L->page + c->text_off, c->text_base + 33u * n);
    }
    L->n = n;
    L->rec[0] = 0;
    for (u32 j = 1; j <= n; j++) { struct cs_client *k = client_of(L, L->row_sup[j]); L->rec[j] = (u32)(uintptr_t)(k ? rec_of(k, L->row_key[j]) : 0); }
    L->shown = sh_sup ? row_of(L, sh_sup, sh_key) : 0;
    /* the active row: kept while a pick waits for its delivery or its client still names it; else the first
     * client (in list order) whose remembered choice is a row.  None unless COLOR is OFF. */
    u32 active = 0, win = 0;
    if (color_setting() == 0xCu) {
        if (act_sup && (L->pend_pick || still_picked(L, act_sup, act_key))) active = row_of(L, act_sup, act_key);
        for (u32 k = 0; !active && !L->pend_pick && k < L->ncl; k++) {
            const struct cols_client *cc = L->cl[k].c;
            u32 p = cc->picked ? cc->picked(cc->arg) : 0;
            if (p) active = row_of(L, cc->sup_id, p - 1u);
        }
    }
    L->active = active;
    if (active) win = L->row_sup[active];
    if (!L->pend_pick) {
        L->told_sup = win; L->told_key = win ? L->row_key[active] : COLS_NONE;
        for (u32 k = 0; win && k < L->ncl && !recording(); k++) {   /* one active in the whole system */
            const struct cols_client *cc = L->cl[k].c;
            if (cc->sup_id != win && cc->picked && cc->picked(cc->arg)) cc->on_pick(cc->arg, COLS_NONE);
        }
    }
    for (u32 j = 1; j <= n; j++) {
        i32 v = 0;
        struct cs_client *k = client_of(L, L->row_sup[j]);
        if ((L->effmin[j] || L->effmax[j]) && k && k->c->strength_get) v = k->c->strength_get(k->c->arg, L->row_key[j]);
        L->eff[j] = v < L->effmin[j] ? L->effmin[j] : v > L->effmax[j] ? L->effmax[j] : v;
    }
    /* enum 0xC's GUIs (indices 15..19): the active row's first, as cs_stub_mc does */
    u32 first = 15u + active, at = 16u;
    L->guitab[2u * 15u + 1u] = first;
    for (u32 g = 15u; g < CS_GUI_N; g++) if (g != first) { L->guitab[2u * at + 1u] = g; at++; }
    L->svc->publish(L->svc);
    post(L);
    show(L, active);
}

/* ---- the API ---- */
static void cs_take(struct cols *L, const struct cols_client *c);
static int api_add(const struct cols_api *a, const struct cols_client *c) {
    struct cols *L = of_api(a);
    if (!L->installed || !L->svc->self(L->svc)) return SL_BADARG;      /* from a client's entry only */
    if (!c || c->magic != COLS_CLIENT_MAGIC || c->api < COLS_API_V1 || c->api > COLS_API_VERSION || !c->sup_id || !c->rows || !c->on_pick)
        return SL_BADARG;
    if (client_of(L, c->sup_id)) return SL_CONFLICT;
    if (L->ncl >= CS_CLIENTS) return SL_FULL;
    cs_take(L, c);
    return SL_OK;
}
static void cs_take(struct cols *L, const struct cols_client *c) {
    u32 at = L->ncl;
    while (at && L->cl[at - 1u].c->order > c->order) { copy(&L->cl[at], &L->cl[at - 1u], sizeof L->cl[0]); at--; }   /* stable: list order */
    L->cl[at].c = c; L->cl[at].nrec = 0;
    L->ncl++;
    sync(L);                                              /* its rows first: attached() hands in their records */
    if (c->attached) c->attached(c->arg, &L->api);
}
static void api_changed(const struct cols_api *a, u32 sup) {
    struct cols *L = of_api(a);
    (void)sup;
    deliver(L);
    sync(L);
}
static int api_set_record(const struct cols_api *a, u32 sup, u32 key, const struct cols_rec *r) {
    struct cols *L = of_api(a);
    struct cs_client *k = client_of(L, sup);
    if (!k || key == COLS_NONE) return SL_BADARG;
    if (r) {
        if (((uintptr_t)r & 3u) || !r->n || r->n > COLS_REC_MAX) return SL_BADARG;
        for (u32 i = 0; i < r->n; i++) if (!COLS_OFF_OK(r->w[i].off)) return SL_BADARG;   /* only what we claimed */
    }
    u32 i = 0;
    while (i < k->nrec && k->rec[i].key != key) i++;
    if (i == k->nrec) {
        if (!r) return SL_OK;
        if (k->nrec >= CS_RECS) return SL_FULL;
        k->nrec++;
    }
    if (r) { k->rec[i].key = key; k->rec[i].rec = r; }
    else { k->rec[i].key = k->rec[k->nrec - 1u].key; k->rec[i].rec = k->rec[k->nrec - 1u].rec; k->nrec--; }
    L->svc->publish(L->svc);
    u32 j = row_of(L, sup, key);
    if (!j) return SL_OK;
    L->rec[j] = (u32)(uintptr_t)r;
    if (j == L->active) {
        if (r) show(L, j);
        else if (L->shown == j && !L->down) root_write(L, 0, 0);   /* withdrawn while shown: no pointer into it stays */
    }
    return SL_OK;
}
static int api_shown(const struct cols_api *a, u32 *sup, u32 *key) {
    struct cols *L = of_api(a);
    u32 j = L->shown_rec && L->shown && L->shown <= L->n ? L->shown : 0;
    if (sup) *sup = j ? L->row_sup[j] : 0;
    if (key) *key = j ? L->row_key[j] : COLS_NONE;
    return j ? 1 : 0;
}
static u32 api_room(const struct cols_api *a, u32 sup) {
    struct cols *L = of_api(a);
    u32 others = 0;
    for (u32 j = 1; j <= L->n; j++) if (L->row_sup[j] != sup) others++;
    return others >= CS_MAX ? 0 : CS_MAX - others;
}
static void api_reapply(const struct cols_api *a) {
    struct cols *L = of_api(a);
    if (L->shown_rec && !L->down) root_write(L, (const struct cols_rec *)(uintptr_t)L->shown_rec, L->shown);
}

/* The COLOR cursor moved (cs_stub_mc, the setter, UI thread; the root already shows the row's record).  Bei 11-10:
 * a LUT row previews its LUT at once, but no client keeps a set for every row -- a v3 client's preview(key) builds
 * the row's set now (or COLS_NONE: the cursor is off its rows, it may let a preview set go).  Menu open only;
 * never while recording (the client would read a file): then the row shows what its record is (a set already
 * made, or stock). */
static USED void cs_cursor(struct cols *L) {
    u32 row = L->active;
    if (!L->menu || L->down || recording()) return;
    u32 sup = row && row <= L->n ? L->row_sup[row] : 0;
    for (u32 k = 0; k < L->ncl; k++) {
        const struct cols_client *cc = L->cl[k].c;
        if (cc->api < COLS_API_V3 || !cc->preview) continue;
        cc->preview(cc->arg, cc->sup_id == sup ? L->row_key[row] : COLS_NONE);
        L->previews++;
    }
}

/* The menu closed (the UI thread; cs_stub_mx, every close). */
static USED u32 cs_closed(struct cols *L) {
    if (L->changed) { L->changed = 0; L->pend_pick = 1; }
    if (L->eff_dirty) { L->eff_dirty = 0; L->pend_eff = 1; }
    deliver(L);
    if (!L->pend_pick) post(L);                           /* a post before the GUI is up may be lost */
    if (L->sync_pending) sync(L);
    return 0;
}

/* Power-off (XC_PowerOffMgr, both lists; may run twice): the root stock, the PQ caches cleared
 * (camera 2026-11-04, lut/native/lvb.c lvb_poweroff), the setter stub inert after. */
static USED void cs_poweroff(struct cols *L, u32 reason) {
    (void)reason;
    if (L->shown_rec) root_write(L, 0, 0);
    L->down = 1;
    for (u32 j = 0; j <= CS_MAX; j++) L->rec[j] = 0;
    keys();
    L->poffs++;
}

/* Old RAW-View (<= 0.3.x: its own COLOR points) on the card and not disabled: it keeps them, we leave. */
static int old_rawview(struct cols *L) {
    const struct cs_section *c = L->sec;
    const struct sl_svc *svc = L->svc;
    const char *p = (const char *)L->block + c->probe_off;
    u32 old = 0, client = 0, h[12];
    if (svc->disabled_get && svc->disabled_get(svc, c->rawview_id) == 1) return 0;   /* off in SupManager */
    for (u32 k = 0; k < c->n_probe; k++) {
        for (u32 i = 0; i < 12u; i++) h[i] = 0;
        if (svc->file_read(svc, p, h, 48u) == 48 && h[0] == SL4_MAGIC && h[5] == c->rawview_id) {
            if (h[6] >= c->rawview_client) client = 1; else old = 1;
        }
        while (*p) p++;
        p++;
    }
    return old && !client;
}

/* Site i and the word Ver.5.02 holds there (code: no .rodata). */
#define CS_NSITES 16u
static u32 site(u32 i, u32 *stock) {
    u32 a = 0, w = 0;
    switch (i) {
    case 0: a = S_MA1; w = 0xEB055F70u; break;   case 1: a = S_MA2; w = 0xEB054DBAu; break;
    case 2: a = S_MA3; w = 0xEB04FB96u; break;   case 3: a = S_MJ; w = 0xEB055F8Eu; break;
    case 4: a = S_MB; w = 0xEB04AC0Bu; break;    case 5: a = S_ML; w = 0xEB048B51u; break;
    case 6: a = S_MC; w = 0xE15A0006u; break;    case 7: a = S_EF; w = 0xEB0560B7u; break;
    case 8: a = S_EN; w = 0xEB04AD18u; break;    case 9: a = S_ENF; w = 0xEB04AD6Eu; break;
    case 10: a = S_GMOVW; w = 0xE30122BCu; break; case 11: a = S_GMOVT; w = 0xE34C22E4u; break;
    case 12: a = S_GCNT; w = 0xE3A02010u; break; case 13: a = S_V25; w = 0xC05687E0u; break;
    case 14: a = S_V26; w = 0xC0568888u; break;  case 15: a = S_ADV; w = 0x00004041u; break;
    }
    *stock = w; return a;
}
/* The root's shared words: {offset, stock table, stock count} (lut/native/lvb.c LVB_T* / LVB_N*). */
#define CS_NROOT 6u
static u32 root_pair(u32 i, u32 *table, u32 *count) {
    u32 o = 0;
    switch (i) {
    case 0: o = 0x08u; *table = 0xC0B39CC8u; *count = 35u; break;
    case 1: o = 0x10u; *table = 0xC0B3A010u; *count = 34u; break;
    case 2: o = 0x28u; *table = 0xC2F1AAE8u; *count = 35u; break;
    case 3: o = 0x48u; *table = 0xC0B3AAECu; *count = 12u; break;
    case 4: o = 0x50u; *table = 0xC0B3AB1Cu; *count = 36u; break;
    default: o = 0x70u; *table = 0xC0B3D670u; *count = 36u; break;
    }
    return o;
}

static int fail(struct cols *L, u32 why) {
    L->result = why;
    if (L->sec && L->sec->log_failed) L->svc->log(L->svc, (const char *)L->block + L->sec->log_failed);
    return SL_RELEASE;
}

#if CS_TEST_ROWS
/* rows-test (fpSup/colshare/rows-test): a client inside COL-Share, CS_TEST_ROWS rows "TEST 1".. with the
 * block's own placeholder tiles (icon() 0), no box, no record -- picking a row never moves the ISP root.
 * The pick lives in RAM only (a cold boot starts at OFF).  Never in the product (CS_TEST_ROWS 0). */
#define TC_ID 0x54535443u                         /* "CTST" */
static u32 tc_rows(void *arg, struct cols_row *out, u32 max) {
    struct cols *L = arg;
    u32 n = CS_TEST_ROWS < max ? CS_TEST_ROWS : max;
    for (u32 i = 0; i < n; i++) {
        char *t = L->tname[i];
        u32 k = i + 1u, at = 5u;
        t[0] = 'T'; t[1] = 'E'; t[2] = 'S'; t[3] = 'T'; t[4] = ' ';
        if (k >= 10u) t[at++] = (char)('0' + k / 10u);
        t[at++] = (char)('0' + k % 10u); t[at] = 0;
        out[i].key = i; out[i].name = t; out[i].eff_min = 0; out[i].eff_max = 0; out[i].flags = 0;
    }
    return n;
}
static u32 tc_picked(void *arg) { return ((struct cols *)arg)->tpick; }
static void tc_on_pick(void *arg, u32 key) { ((struct cols *)arg)->tpick = key == COLS_NONE ? 0 : key + 1u; }
static void tc_add(struct cols *L) {
    struct cols_client *t = &L->tc;
    t->magic = COLS_CLIENT_MAGIC; t->api = COLS_API_V1; t->sup_id = TC_ID; t->order = 1000u;
    t->rows = tc_rows; t->icon = 0; t->picked = tc_picked; t->on_pick = tc_on_pick;
    t->strength_get = 0; t->strength_set = 0; t->attached = 0; t->arg = L; t->box = 0; t->preview = 0;
    L->tpick = 0;
    L->svc->publish(L->svc);
    if (L->ncl < CS_CLIENTS) cs_take(L, t);
}
#endif

USED int sup_entry(void *block, const struct sl_svc *svc, const char *path) {
    (void)path;
    const struct sl4_header *h = block;
    const struct cfg *cfg = (const struct cfg *)((u8 *)block + SL4_HEADER_LEN);
    if (svc->version < 6u || cfg->magic != CFG_MAGIC || cfg->state_off < h->file_len ||
        cfg->state_off + sizeof(struct cols) > h->block_size || (cfg->state_off & 7u) ||
        cfg->section_off + sizeof(struct cs_section) > h->file_len) return SL_RELEASE;
    struct cols *L = (struct cols *)((u8 *)block + cfg->state_off);
    const struct cs_section *c = (const struct cs_section *)((const u8 *)block + cfg->section_off);
    if (c->magic != SEC_MAGIC) return SL_RELEASE;
    L->svc = svc; L->cfg = cfg; L->block = block; L->sec = c;
    if (old_rawview(L)) { svc->log(svc, (const char *)block + c->log_old_rawview); return SL_RELEASE; }   /* nothing claimed */
    /* claims: one refusal -> RELEASE, the core undoes the rest (and nothing was written) */
    for (u32 i = 0; i < CS_NSITES; i++) {
        u32 stock, a = site(i, &stock);
        if (svc->claim(svc, a, 4u, &stock, SL_EXCL) != SL_OK) return fail(L, 1);
    }
    {   /* the block's HOOK_FV (Res-Custom's kind: SL_SHARED_UI, NESTED_HOOKS.md rule 7; unclaimed it froze, 11-04) */
        u32 fv = FV_STOCK;
        if (svc->claim(svc, FV_SITE, 4u, &fv, SL_SHARED_UI) != SL_OK) return fail(L, 2);
    }
    for (u32 i = 0; i < CS_NROOT; i++) {
        u32 st[2], o = root_pair(i, &st[0], &st[1]);
        if (svc->claim(svc, ROOT + o, 8u, st, SL_EXCL) != SL_OK) return fail(L, 3);
    }
    {   /* v2: the box glyphs' call site (raw-view 0.3.1's stub_ai: CHAIN, a layer below is kept) */
        u32 ai = AI_STOCK;
        if (svc->claim(svc, AI_SITE, 4u, &ai, SL_CHAIN) != SL_OK) return fail(L, 9);
        L->ai_next = svc->chain_next(svc, AI_SITE, 1u);
        if (!(L->ai_next & 1u)) return fail(L, 10);       /* not a BL to Thumb: leave it */
    }
    L->api.magic = COLS_API_MAGIC; L->api.version = COLS_API_VERSION;
    L->api.add = api_add; L->api.changed = api_changed; L->api.set_record = api_set_record;
    L->api.shown = api_shown; L->api.reapply = api_reapply; L->api.stock_root = L->root_stock;
    L->api.rows_max = CS_MAX; L->api.room = api_room;
    if (svc->provide(svc, COLS_ID, &L->api) != SL_OK) return fail(L, 4);
    keys();                                               /* a warm restart's PQ caches may name a past boot's tables */
    for (u32 k = 0; k < COLS_ROOT_WORDS; k++) L->root_stock[k] = rd(ROOT + 4u * k);   /* after the claims' repair */
    /* the labels are private strings handed to the firmware by address: borrowed */
    if (svc->borrow(svc, block, (const u8 *)block + h->file_len) != SL_OK) return fail(L, 5);
    struct uia_outcome o;
    u32 r = fpui_stock_apply(svc, (const u8 *)block + c->block_off, c->block_len, &o);
    if (r != UIA_OK) return fail(L, 6u | r << 8 | o.op << 16);
    L->page = (u32)o.page;
    L->table = cs_table(c);
    if (!L->table) return fail(L, 7);
    u32 v = svc->cave_alloc(svc, 16u * 10u);
    if (!v || (v & 7u)) return fail(L, 8);
    u32 stub[9];
    stub[0] = (u32)(uintptr_t)cs_stub_ma; stub[1] = (u32)(uintptr_t)cs_stub_mj; stub[2] = (u32)(uintptr_t)cs_stub_mb;
    stub[3] = (u32)(uintptr_t)cs_stub_ml; stub[4] = (u32)(uintptr_t)cs_stub_mc; stub[5] = (u32)(uintptr_t)cs_stub_ef;
    stub[6] = (u32)(uintptr_t)cs_stub_en; stub[7] = (u32)(uintptr_t)cs_stub_mo; stub[8] = (u32)(uintptr_t)cs_stub_mx;
    for (u32 k = 0; k < 9u; k++) { wr(v + 16u * k, VENEER_IP); wr(v + 16u * k + 4u, VENEER_PC);
                                   wr(v + 16u * k + 8u, (u32)(uintptr_t)L); wr(v + 16u * k + 12u, stub[k] & ~1u); }
    wr(v + 144u, T_VENEER_IP); wr(v + 148u, T_VENEER_PC);   /* slot 9: Thumb, for the glyph site */
    wr(v + 152u, (u32)(uintptr_t)L); wr(v + 156u, (u32)(uintptr_t)cs_stub_ai & ~1u);
    for (u32 i = 0; i < 2u * CS_STOCK; i++) L->guitab[i] = rd(GUITAB_STOCK + 4u * i);   /* stock 16, then ours as OFF's enum */
    for (u32 g = CS_STOCK; g < CS_GUI_N; g++) { L->guitab[2u * g] = 0xCu; L->guitab[2u * g + 1u] = g; }
    for (u32 j = 0; j <= CS_MAX; j++) L->row_key[j] = COLS_NONE;
    L->magic = RUN_MAGIC; L->on_close = (u32)(uintptr_t)&cs_closed; L->on_cursor = (u32)(uintptr_t)&cs_cursor;
    u32 *po = L->poff;
    po[0] = (u32)(uintptr_t)po - 8u; po[1] = (u32)(uintptr_t)cs_poff_stub & ~1u;
    po[2] = (u32)(uintptr_t)L; po[3] = (u32)(uintptr_t)&cs_poweroff;
    svc->publish(svc);
    /* Every word we patch goes back by the loader's journal; this routine only adds the PQ caches' reset and
     * the setter's silence.  XC_PowerOffMgr has ten slots a list and they can be full (camera 2026-11-08, LUT's
     * own registration failed): not fatal -- the entry clears the caches at the next boot anyway. */
    for (u32 list = 0; list < 2u; list++) {
        void *mgr = FW(POFF_MGR, void *(*)(void))();
        if (!mgr || !FW(POFF_ADD, u32 (*)(void *, void *, u32))(mgr, po, list)) L->poff_missing |= 1u << list;
    }
    u32 tab = (u32)(uintptr_t)L->guitab;
    wr(S_GMOVW, movw_of(0xE30122BCu, tab & 0xFFFFu));
    wr(S_GMOVT, movw_of(0xE34C22E4u, tab >> 16));
    wr(S_GCNT, 0xE3A02000u | CS_GUI_N);
    wr(S_MA1, bl_to(S_MA1, v)); wr(S_MA2, bl_to(S_MA2, v)); wr(S_MA3, bl_to(S_MA3, v));
    wr(S_MJ, bl_to(S_MJ, v + 16u)); wr(S_MB, bl_to(S_MB, v + 32u)); wr(S_ML, bl_to(S_ML, v + 48u));
    wr(S_MC, bl_to(S_MC, v + 64u)); wr(S_EF, bl_to(S_EF, v + 80u));
    wr(S_EN, bl_to(S_EN, v + 96u)); wr(S_ENF, bl_to(S_ENF, v + 96u));
    wr(S_V25, v + 112u); wr(S_V26, v + 128u);            /* the vtable through veneers too: ip = context */
    wr(S_ADV, ADV_NEW);
    wr(AI_SITE, thumb_bl(AI_SITE, v + 144u));
    svc->publish(svc);
    L->installed = 1;
    sync(L);                                              /* no client yet: the stock sixteen */
    /* clients that loaded before us (provide(COLS_TAG(id))) */
    struct sl_supinfo info;
    for (u32 i = 0; svc->sups_list(svc, i, &info) == SL_OK && L->ncl < CS_CLIENTS; i++) {
        if (info.status != SL_S_LOADED || info.id == COLS_ID) continue;
        const struct cols_client *cc = (const struct cols_client *)svc->find(svc, COLS_TAG(info.id));
        if (cc && cc->magic == COLS_CLIENT_MAGIC && cc->api >= COLS_API_V1 && cc->api <= COLS_API_VERSION && cc->sup_id == info.id &&
            cc->rows && cc->on_pick && !client_of(L, cc->sup_id)) cs_take(L, cc);
    }
#if CS_TEST_ROWS
    tc_add(L);
#endif
    L->result = 0;
    return SL_KEEP;
}
