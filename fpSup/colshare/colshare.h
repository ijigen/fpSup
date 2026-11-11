/* COL-Share 客戶 API(版本 3;版本 1、2 的客戶照舊可用)。設計:fpSup/colshare/DESIGN.md(Bei 2026-11-07 §9.1)。
 *
 * COL-Share(sup_id 'COLS')擁有原生 COLOR 清單的「多出來的列」:16 個清單點、共用檔案重導
 * C05E5BEC、CSV／圖示／ColorButtonMenu 複本、GUI 對照表、setter 點、±框,以及 ISP root 的共用指標字
 * (root+0x08/0x0C/0x10/0x14/0x28/0x2C/0x48/0x4C/0x50/0x54/0x70/0x74)。客戶(LUT、RAW-View ...)
 * 報上自己的列,事先交出「選到時 root 要寫什麼」的記錄;COL-Share 在 setter 裡照記錄寫、
 * 切回原廠時以原廠值反序寫回。客戶自己專屬的點(LUT 的 YGAM、DNG、MakerNote)各自 claim。
 *
 * 註冊(順序無關):
 *   晚到(COL-Share 已載入):api = svc->find(svc, COLS_ID); api->add(api, &client)  -- 只在自己的 entry 裡
 *   早到(還沒有 COL-Share):svc->provide(svc, COLS_TAG(my_sup_id), &client)
 *                            COL-Share 的 entry 會用 sups_list + find 撈進來。
 * 兩條路都在列排好(rows() 叫過)之後呼叫 client->attached(arg, api):客戶在那裡交記錄、裝自己的點;
 * 早到的客戶在那裡才知道 api(那時是 COL-Share 的 entry,它的 claim 記在 COL-Share 名下)。
 * add() 要放在 entry 裡最後一個可能失敗的步驟之後:之後不能再回 SL_RELEASE(指標會懸空)。
 *
 * 規則:所有回呼在 UI 執行緒(或某個 sup 的 entry 裡)、要快、程式在客戶自己的塊。
 * cols_rec 一旦交出就不能改內容;要換就準備另一份再 set_record(單字指標交換,setter 可能同時讀)。
 * 舊的那份留到下一次 set_record 返回之後。記錄裡的表(指標指向的東西)交出前要已發布(svc->publish)。
 *
 * 版本 3(Bei 2026-11-10:12 列、「沒用掉的東西不要佔用記憶體」):
 *   api->rows_max = 清單多出來的列數上限(12);api->room(api, my_id) = 我現在最多能有幾列
 *   (rows_max − 其他客戶上一次同步排進去的列數)。客戶在自己的設定頁用它擋「啟用」(LUT Manager)。
 *   客戶的 rows() 拿到的 max 仍是實際能放的列數(排在前面的客戶先放);多出來的由客戶自己決定怎麼標示。
 *   v3 客戶(client->api == 3)在每次同步抄完全部圖示後會收到 icon(arg, COLS_NONE, 0):
 *   「圖示抄完了」,客戶可以把畫圖示用的暫存記憶體還回去(len 是 0,不可寫)。 */
#ifndef FPSUP_COLSHARE_H
#define FPSUP_COLSHARE_H
#include <stdint.h>

#define COLS_ID          0x534C4F43u                 /* "COLS": svc->find(svc, COLS_ID) -> struct cols_api */
#define COLS_TAG(id)     ((uint32_t)(id) ^ 0xC0C0C0C0u)   /* 早到客戶的 provide 鍵(QSC_TAG 不同) */
#define COLS_API_MAGIC   0x31414C43u                 /* "CLA1" */
#define COLS_CLIENT_MAGIC 0x31434C43u                /* "CLC1" */
#define COLS_API_VERSION 3u                         /* the api's version; a client says 1, 2 or 3 */
#define COLS_API_V1      1u                          /* a version-1 client: no box() (plain clamped box) */
#define COLS_API_V3      3u                          /* rows_max / room(); a v3 client gets icon(COLS_NONE) after a sync */
#define COLS_NONE        0xFFFFFFFFu                 /* on_pick:離開這個客戶的列 */
#define COLS_REC_MAX     12u
#define COLS_ROOT        0xC2F1A064u                 /* ISP root;stock_root[] = 它的前 36 字 */
#define COLS_ROOT_WORDS  36u

/* COL-Share 會寫、也 claim 了的 root 偏移(cols_rec.w[].off 只能是這些):
 * 0x08/0x0C 矩陣組 2、0x10/0x14 矩陣組 1、0x28/0x2C YCMAT、0x48/0x4C 三通道清單、0x50/0x54 CEQ、0x70/0x74 tone 基底 */
#define COLS_OFF_OK(o)   ((o) == 0x08u || (o) == 0x0Cu || (o) == 0x10u || (o) == 0x14u || (o) == 0x28u || (o) == 0x2Cu || \
                          (o) == 0x48u || (o) == 0x4Cu || (o) == 0x50u || (o) == 0x54u || (o) == 0x70u || (o) == 0x74u)

struct cols_row {                /* rows() 填;只列「現在可選」的列 */
    uint32_t key;                /* 客戶內穩定、跨開機不變(COLS_NONE 不可用) */
    const char *name;            /* 大標籤:1..31 可列印 ASCII(其他字元變 '?',過長截斷);rows() 返回前有效 */
    int8_t eff_min, eff_max;     /* ±框範圍,-5..+5 之內、min <= max;0,0 = 沒有強度(框固定 0) */
    uint16_t flags;              /* 版本 1:必須是 0;版本 2:COLS_R_SNAP */
};
/* 版本 2(Bei 2026-11-08:RAW-View 的 SA/GA 留在原生 ±框):±框仍由 COL-Share 的 hook 管(原廠只有一個框),
 * 但每一列由客戶決定框的樣子:範圍(eff_min..eff_max)、要不要「只停兩端」、每一格顯示的字形、
 * 每一步做什麼(live:每一步立刻寫的字;strength_set:選單關閉、不在錄影時交出,和 LUT 的強度一樣)。 */
#define COLS_R_SNAP      1u      /* 框只停在 eff_min / eff_max:往上一步 = max、往下 = min(RAW-View SA/GA) */
#define COLS_GLYPH_MAX   4u
struct cols_box {                /* client->box(arg, key);0 = 一般的框 */
    int32_t *live;               /* 0 或一個字:框的每一步(選單開著時,stub 裡)立刻寫入新值;只寫資料 */
    /* 0 或 {n <= COLS_GLYPH_MAX, (原圖名, 新圖名) × n}:圖名 = 字型名稱在韌體字串池裡的位移;
     * 游標在這一列且它是 active 時,效果框(符號 0x177 / 數字 0x178)的關鍵影格圖名照表換 */
    const uint32_t *glyphs;
};

struct cols_rec {                /* 選到這列時 root 要寫的字,依序寫;回原廠時用原廠值反序寫 */
    uint32_t n;                  /* 1..COLS_REC_MAX */
    struct { uint16_t off; uint16_t _r; uint32_t val; } w[COLS_REC_MAX];   /* off:COLS_OFF_OK */
};

struct cols_api;
struct cols_client {
    uint32_t magic, api;         /* COLS_CLIENT_MAGIC, COLS_API_VERSION */
    uint32_t sup_id;
    uint32_t order;              /* 列序:小的在前(Bei 11-07 #3:RAW-View 0、LUT 100);同值照註冊序 */
    uint32_t (*rows)(void *arg, struct cols_row *out, uint32_t max);
    /* 列 key 的 86x74 XCI(<= 13312 B);指標有效到下一次 icon() 呼叫。0 = 保留目前圖示 */
    const uint8_t *(*icon)(void *arg, uint32_t key, uint32_t *len);
    uint32_t (*picked)(void *arg);                         /* 客戶記得的選擇:key + 1,0 = 無 */
    void     (*on_pick)(void *arg, uint32_t key_or_none);  /* 選單關閉、不在錄影;COLS_NONE = 離開這個客戶的列 */
    int      (*strength_get)(void *arg, uint32_t key);
    void     (*strength_set)(void *arg, uint32_t key, int v);   /* 選單關閉、不在錄影 */
    void     (*attached)(void *arg, const struct cols_api *api);   /* 加入完成(推/拉兩條路都叫一次) */
    void *arg;
    /* ---- 版本 2(api == 2 才讀) ---- */
    const struct cols_box *(*box)(void *arg, uint32_t key);   /* 0 = 每列都是一般的框;回傳的指標常駐 */
    /* ---- 版本 3(api == 3 才讀) ---- */
    /* 選單開著、游標移到某列之後(root 已照那列的記錄寫好):key = 自己的列,COLS_NONE = 游標不在自己的列上。
     * 客戶可以當場做那列的表再 set_record(Bei 11-10:游標到就預覽,但不常駐每一列的表);錄影中不叫。0 = 不要 */
    void (*preview)(void *arg, uint32_t key);
};

struct cols_api {
    uint32_t magic, version;     /* COLS_API_MAGIC, COLS_API_VERSION */
    int  (*add)(const struct cols_api *, const struct cols_client *);       /* 客戶自己的 entry 裡;0 = 加入 */
    void (*changed)(const struct cols_api *, uint32_t sup_id);   /* 列/名/圖/ready 變了:重排(選單開著就延到關閉) */
    /* 0 = 收下;rec 0 = 這個 key 沒有記錄(選到時 root 不動)。被選中且 root 不是這份時立刻寫 */
    int  (*set_record)(const struct cols_api *, uint32_t sup_id, uint32_t key, const struct cols_rec *);
    int  (*shown)(const struct cols_api *, uint32_t *sup_id, uint32_t *key);   /* root 現在顯示誰;0 = 原廠 */
    void (*reapply)(const struct cols_api *);    /* 表的內容變了(重擬合):重寫目前那列、重設 PQ 快取鍵 */
    const uint32_t *stock_root;  /* entry 時(claim 修復殘留之後)root 的 36 字快照:LUT 的 DNG shadow 用 */
    /* ---- 版本 3(version >= 3 才有) ---- */
    uint32_t rows_max;           /* 多出來的列最多幾列(12) */
    uint32_t (*room)(const struct cols_api *, uint32_t sup_id);   /* 這個客戶現在最多能有幾列 */
};

#endif
