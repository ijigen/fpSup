/* LUT 當 COL-Share 的客戶(cols.c)的狀態,在 struct lut4_state 裡。2026-11-07 取代 clist.h:
 * COLOR 清單的點、GUI 表、setter、root 字都歸 COL-Share(fpSup/colshare/)。
 * 2026-11-10(Bei):COL-Share 12 列;LUT 最多交 CL_MAX 列,實際上限 = COL-Share 的 room()(12 − 其他客戶的列)。 */
#ifndef LUT_COLS_H
#define LUT_COLS_H
#include "colshare.h"
#define CL_MAX          12u                 /* LUT 最多交出的列(= COL-Share 的 rows_max 12) */
#define CL_OLD_MAX      4u                  /* 舊 COL-Share(API < 3,沒有 room())的列數 */
#define LC_MAGIC        0x3143434Cu         /* "LCC1": 測試用它找 */
struct lut_cols {
    u32 magic;
    u32 attached;                /* COL-Share 收下了我們(api 有效) */
    u32 n;                       /* rows() 最後交出的列數 */
    u32 map[CL_MAX];             /* 第 j 列 -> library index(= 它的 key) */
    u32 recd[CL_MAX], nrecd;     /* 交過記錄的 key(不再是列時撤回) */
    u32 over;                    /* 開著、可用,但 rows() 的 max 放不下的(library 順序的最後幾個;Manager 標示) */
    const struct cols_api *api;
    struct cols_client client;
    char names[CL_MAX][32];      /* 大標籤:檔名去掉 .cube(COL-Share 在 rows() 之後讀) */
};
#endif
