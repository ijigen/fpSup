# COL-Share(v0.0.1test,sup_id `COLS`)

原生 COLOR 清單「多出來的列」的共用容器(Bei 2026-11-07)。設計與 Bei 的決定:[DESIGN.md](DESIGN.md) §9.1。
本目錄是 P1(抽出)+ P2(通用)的實作;P3(RAW-View 0.4.0test 改成客戶)在 `projects/rawview/build`(`build_v4_rawview.py --cols`、`test_v4_cols_rawview.py`)。**全部離線,未上機。**

## 檔案

| 檔案 | 內容 |
|---|---|
| `colshare.h` | 客戶 API 版本 1(`cols_client` / `cols_api` / `cols_rec`) |
| `colshare.c` | sup 本體:16 個清單點、`C05E5BEC`、root 共用字、setter／±框／選單 stub、同步、錄影延後、關機回呼 |
| `colshare_ui.py` | 主機端資料(由 `lut/clist_ui.py` 搬來):FPUI 區塊、CSV 複本、佔位圖示、標籤佔位字串、`cs_section` |
| `build_colshare.py` | 建 `fpSup/COL-Share_v0.0.1test.BIN`(一個 sup 一個檔:UI 資料都在 BIN 裡);常駐 > 64 KB 就失敗 |
| `test_colshare.py` | §11 的離線測試(unicorn,真韌體映像) |
| `mutate_colshare.py` | 突變檢查:每個突變都必須讓某個測試失敗 |
| `rows-test/` | P4 列數測試(2026-11-10):各項上限、`build_colshare.py --rows N` 測試版(內建 TEST 1..N 假客戶)、離線測試、上機步驟 |

LUT 這邊:`lut/native/cols.c`、`cols.h`(客戶)取代 `clist.c`/`clist.h`/`clist_ui.py`(已刪,舊版備份在
scratchpad `lut-before-colshare/`)。`lut/test_clist_native.py` 已移植成「COL-Share + LUT」。

## 誰擁有什麼(關機寫回、暖開機殘留)

COL-Share claim(loader 的 journal 在關機時寫回,暖開機殘留由 claim 修成原廠值):

- 16 個 `SL_EXCL` 清單點(與 `clist.c` 相同的位址與原廠字)
- `C05E5BEC`(`SL_SHARED_UI`,與 Res-Custom／QS-Share 共用;fpui_stock 的 HOOK_FV 不替呼叫者 claim)
- root 六組 8 bytes:`+0x08 +0x10 +0x28 +0x48 +0x50 +0x70`(各含後面的筆數字,共 12 字)

`fpui_stock_apply` 對這個區塊寫的其他東西:複本與 FSFV 表(自己 `fst_alloc` 的記憶體)、cave 跳板
(`CAVE_BUMP` 配的 cave 字)、runtime 頁面表的 offset(韌體堆積,每次開機重建)—— 都不是映像字,不需 claim。

PQ 快取鍵 `C3414D14 / C2F19D44 / C2F19D48` 不是 claim 的字:entry 與 COL-Share 的關機回呼清成 ~0
(11-04 暖重開凍結的教訓,原本在 LUT 的 `lvb_poweroff`)。

LUT 保留自己專屬的點:DNG 六點與兩張 OFF 表(`dng.c`)、MakerNote 0x124/0x12D/0x34/0x129 與 YGAM(`lvb.c`)。
它不再 claim root 字。

## 客戶要點

- 晚到:`svc->find(COLS_ID)` → `add()`;早到:`provide(COLS_TAG(id))`,COL-Share 的 entry 撈。
  兩條路都在列排好之後叫 `attached(arg, api)`;客戶在那裡交記錄、裝自己的點。
  早到的客戶在 COL-Share 的 entry 裡 claim,LOAD.LOG 會記在 COL-Share 名下。
- 列序:`order` 小的在前(RAW-View 0、LUT 100),同值照註冊序。上限 4 列(與今天相同;P4 驗 5–8 列)。
- 記錄 `cols_rec`:依序寫;切回原廠時,舊記錄的字反序寫回 `stock_root`(新記錄也會寫的字跳過)。
  只收 claim 範圍內的偏移;`set_record(…, 0)` = 沒有記錄(選到時 root 不動;正在顯示的被撤回就回原廠)。
- 錄影中(`0xC347D1C0+0x14 == 0x21` → `0xC34765CC+0x3D`,否則 `+0x157`)不叫 `on_pick` / `strength_set`,
  停錄後下一次選單關閉或 `changed()` 補送。
- 舊 RAW-View(檔頭 sup_id `RAWV`、version < `0x000400`、SupManager 沒停用)在卡上 → COL-Share 自己 RELEASE。
  **P3 的 RAW-View 檔頭 version 必須 ≥ `0x000400`**(0.4.0)。

## 建置與測試

```
python3 -B fpSup/colshare/build_colshare.py                  # fpSup/COL-Share_v0.0.1test.BIN
python3 -B fpSup/lut/build_sup.py --card --library … --out …  # LUT 卡,預設帶 COL-Share(--no-colshare 不帶)
cd fpSup/colshare && python3 -B -m unittest test_colshare && python3 -B mutate_colshare.py
cd fpSup/lut && python3 -B -m unittest discover -p 'test_*.py'
```

上機步驟見 DESIGN.md §12。

## 與 DESIGN.md 不同的地方(P1/P2 實作,2026-11-07)

1. **圖示仍複製**(§7 說「不複製,指向客戶」):LUT 只有一格常駐圖磚(`imp_icon_slot`),四列要四份就得長 LUT 的常駐。
   改成客戶的 `icon(arg, key, &len)` 回呼,COL-Share 在同步時抄進 donor 複本(與今天相同,複本在 fpui 配的堆積,
   不算 COL-Share 常駐)。`cols_row` 因此沒有 icon 欄位。
2. **API 多兩個欄位**:`cols_client.order`(Bei #3 的列序:RAW-View 0、LUT 100)與 `attached(arg, api)`
   (早到的客戶在那裡才拿到 api、交記錄、裝自己的點)。`COLS_R_LOCK_REC` 沒做(Bei #6:照原廠),`flags` 必須 0。
3. **root +0x40/+0x44 沒 claim**:原廠值不知道(RAM,映像裡是雜訊),而 RAW-View 實際只用 +0x70 與 +0x08。
   claim 的是 6 組 8 bytes(指標 + 筆數),記錄可寫其中 12 個字。
4. **列上限仍是 4**:16 點的位元組(AEL 頁上限 BE 19.0、`mov r2, #20`)與今天相同;5–8 列是 P4。
5. 舊 RAW-View 判斷看檔頭 version < `0x000400`;今天的 v0.3.1 檔頭 version = 1。P3 要把 RAW-View 檔頭改成 ≥ 0x000400。
6. LUT 在一個列的表重擬合(強度改了)而那列正顯示時呼叫 `reapply()`(重寫 root + 清 PQ 快取鍵);
   clist.c 時代只在 root 指標變了才清鍵。
7. 早到客戶(在 COL-Share 前載入)自己的點在 COL-Share 的 entry 裡 claim,LOAD.LOG 記在 COL-Share 名下。
   LUT 實際上永遠晚到(檔名序),這條路只有測試(把 COL-Share 改名排到後面)走。

## P3(2026-11-08,離線)

- RAW-View 0.4.0test:列序 0(最前)、±框 SA/GA(API 2,見下)、記錄 `{+0x70 → mode 副本, +0x08 → 矩陣副本}`(指標固定;
  生效與否只改副本 OFF 筆的內容,root 字從不由 RAW-View 寫)。claim 只剩自己的 20 個點(RAW_CORR `C032F728` 先 EXCL)。
- `colshare_ui.rawview_files()`:探測名單加入 0.3.x 與 0.4.x(含 `test` 後綴)——0.3.1 舊檔與 0.4 客戶同卡時,
  loader 只載入新的那個,COL-Share 要看得到客戶才不會誤退出;names_v4 的版本有後綴時也不會解析失敗。
- LUT `dng.c`:自訂 DNG 矩陣的暫換改寫 FUN_c02c4a50 實際讀的表(解 `C02C4BE4/C02C4C98` 的 movw/movt),
  因為 RAW-View 把 OFF 常數指到自己的 cm_buf;否則兩者同卡時 LUT 的自訂矩陣進不了 DNG。

## API 2(Bei 2026-11-08:SA/GA 留在原生 ±框)

- `COLS_API_VERSION` 2;客戶 `api` 可為 1 或 2(LUT 留 1)。版本 2 多 `client->box()` 與 `COLS_R_SNAP`(DESIGN §9.1 #7)。
- 新 claim:`C05E2200`(Thumb BL,SL_CHAIN,接下層)→ Thumb veneer → `cs_stub_ai`(字形表)。COL-Share claim 數 23 → 24。
- `struct cols` 尾端加 snap/live/glyph/ai_next(asm 用 888/908/928/948);前面的偏移不變。

## 12 列 + 「沒用掉的東西不要佔用記憶體」(Bei 2026-11-10,離線,未上機)

rows-test 19 列上機通過之後,產品改成 12 列(`CS_MAX 12`;`--rows N` 測試版保留)。同一輪 Bei 定的原則:
**沒用掉的東西不要佔用記憶體**——兩個 sup 都照這個改。

**COL-Share**
- CSV 與圖示複本**只給存在的列、大小剛好**:FPUI 區塊裡不再有 `OP_FILE`(也不再有額外區塊)。`sync()`(選單關閉、不在錄影)
  在機上組三份 CSV(原廠檔 + 每列一行,與 `colshare_ui.rows_csv` 逐位元組相同),跟韌體配置器(class 0)要剛好的大小,
  掛進共用重導表;列不見了就把表項的 stock 字清 0(handler 比不到)再 `free`。表項不刪(別的 sup 可能記著位址),自己的留著重用。
- BIN 不再存 3×(N+1) 份 CSV 與每列佔位圖:只剩一張共用佔位圖(客戶 `icon()` 回 0 時)。
- 錄影中不同步(延到停錄後下一次關選單 / `changed()`):配置器不在錄影時碰。
- 共用重導表容量 32 → 64(資料;rows-test 上機用的就是 64)。每客戶記錄表 8 → 12(LUT 可佔滿)。
- **API v3**(v1/v2 客戶照舊):`api->rows_max`(12)、`api->room(api, sup)` = 12 − 其他客戶上一次同步排進的列;
  v3 客戶在每次同步抄完圖示後收到 `icon(arg, COLS_NONE, 0)`(可以還畫圖示的暫存)。

**LUT**(`lut/native/cols.c`、`lvb.c`、`color_ui.c`、`conv.c`、`import.c`)
- 最多 12 列(`CL_MAX`);Manager 的上限 = `room()`(RAW-View 在 → 11)。標題 `LUT (開著/room)`;超過時 On 被拒、
  顯示 `List full: disable one`;轉檔完成時若已滿,轉好的那個保持 Off(同樣訊息)。
- 晚到的客戶(先開 12 個 LUT,之後才啟用 RAW-View):`rows()` 拿到的 max 變小,**照 library 順序**前面的成為列,
  後面的不出現,Manager 那一列紅字 `No COLOR row: list full`(標題變成 `LUT (12/11)`);關掉任一個,它就回來。
- **ISP set 最多兩份**(每份約 26 KB,借來的,不常駐):已選列的一份,加上選單開著時游標所在列的一份。
  **游標一到 LUT 列就預覽**(Bei 11-10 第二輪,與以前相同):COL-Share v3 在 setter 寫完 root 後叫客戶的 `preview(key)`
  (`cs_cursor`);LUT 讀那列的 .JFT、建表、`set_record` → 畫面立刻是那個 LUT;游標離開時上一份預覽還回去;
  在預覽列按 OK 關選單 → 那份直接變成「已選」(不再建一次)。一步的成本:讀一個 .JFT(12.8 KB,一次開檔)+ 約 26 KB 表複製,
  模擬器實測 175 k 指令(不含韌體讀檔;估計每步數 ms,要上機量)。沒有有效 .JFT 的列(轉檔後改過強度)游標上不擬合(要幾秒),
  顯示原廠直到選它;鄰列預取沒做(每列多 26 KB + 一次讀檔,不划算)。
- **錄影中**:不預覽、不讀檔、不借記憶體。游標到「已有表」的列(已選的那列、錄影前最後預覽的那列)照樣顯示那個 LUT,
  其他 LUT 列顯示原廠;在錄影中選的列,停錄後下一次關選單才載入。
- 也改成借用(用完即還)的:COLOR 圖示的畫圖格(12.8 KB)、讀 .JFT 的緩衝(12.8 KB,lvb / 轉檔讀回 / 色卡列)。

| 常駐(block) | 之前 | 之後 |
|---|---|---|
| COL-Share | 33 024 B(4 列)+ 堆積複本約 57 KB(4 圖 × 13 312 + 3 CSV,不管有沒有列) | 24 576 B(12 列)+ 只有存在的列:12 列約 10 KB、0 列 0 |
| LUT(3 個 cube 的 library) | 723 584 B(4 個 ISP set 118 784 B + 圖示格 + .JFT 緩衝常駐) | 593 408 B;LUT 列顯示時另借 1 份 set 25 984 B(換列瞬間 2 份) |

- **另修一個舊 bug(會影響多列)**:機上匯入的 cube 身分是 `CAM1` + 檔案大小 + …,而 .JFT 檔名只取前 8 bytes ——
  **同大小的兩個 cube(Resolve 匯出的 33³ 常常一樣大)共用同一個 .JFT**,選 A 可能顯示 B 的表。檔名改成「大小 + 檔名雜湊」
  (`lvb_jpath`、`jft.py path_for` 同規則;主機 sha256 身分不變)。**代價:機上已轉好的檔名變了,要在 Manager 重新轉檔一次**。
- 稽核(常駐但很少用、這次沒動的):LUT.BIN 裡的 `import_ui` 區段 476 KB(載入 cube 用的常數 332 KB + 畫圖示的字型 144 KB)
  一直常駐,只在選 LUT / 轉檔 / 同步圖示時用。細目與方案(Bei 11-10:先報告、不實作):

  | 內容 | 大小 | 何時用 | zlib-9(參考) |
  |---|---|---|---|
  | 傳遞曲線表:6 種 gamma × 正負 × 6913 點 Q20 int32 | 331 824 B | 載入 cube(開機、選 LUT、轉檔、擬合、render API) | 約 153 KB |
  | 色域矩陣 8 × 3×3 | 288 B | 同上 | — |
  | 圖示字型 atlas:23 / 19 / 15 px 三種 | 55 288 + 48 056 + 41 048 B | COL-Share 同步時畫 COLOR 圖示 | 約 23 KB |
  | 程式碼(合計 90 KB) | 轉檔/擬合約 43 KB、其餘約 47 KB | 轉檔 / 一直 | — |
  | 字串 1.7 KB、ColorChecker 2.9 KB、library 表 8.3 KB | 13 KB | Manager / 轉檔 / 一直 | — |

  BIN 整個被 loader 讀進 block,所以「放在 BIN 裡」= 常駐;不動共用 loader/merge 的作法只有壓縮或在機上重算:
  (a) 曲線 + 字型 LZ4 壓在 BIN,要用時解到借來的記憶體(曲線直接解進已借的 4 MB asset 區,不多佔;字型借 144 KB 只在同步期間)
      —— 常駐約剩 LZ4 後大小,估省 240–360 KB(曲線先做差分再壓可再小);風險:多一段解壓碼(要越界測試)、每次載入多幾 ms;
  (b) 曲線在機上用公式重算(0 常駐、省 332 KB)—— 風險:與主機量化結果差 1 LSB,現有「相機與主機 asset 逐位元相同」測試要改;
  (c) 只留一種字號(省 89 KB)—— 長檔名的圖示字變小/被截,屬 UI 改變;
  (d) 移到獨立資料檔 —— 要 merge 頁一起打包,不符這次條件。
  必須常駐的:8 KB DMA 檔案暫存(檔案 I/O 走它)、狀態 4 KB、library 表、lvb 的 0x400(DNG/YGAM hook 隨時會讀)、
  COL-Share 的頁面複本與標籤字串(韌體按位址讀)。

測試:`test_capacity.py`(容量、Manager 上限、晚到客戶、11 列各自的 ISP 記錄、只借一份 set、錄影不讀檔、複本隨列配/還、常駐);
突變在 `mutate_colshare.py`(新增 COL-Share 7 個、LUT 6 個)。

### 上機步驟(12 列;先廣播相機使用權,用完廣播 released)

卡:`projects/lut-sup/private/cards/20261110-rows12/card/`(COL-Share 12 列、LUT 兩個 cube、RAW-View 0.4.0test;sha256 在 `files.json`)。

1. 部署、冷開機,LOAD.LOG:COL-Share / LUT / RAW-View 三行都是 `0A`。
2. Manager:標題 `LUT (1/11)`(RAW-View 在 → room 11);p2d60 若顯示未轉,轉一次(檔名規則改了)。
3. COLOR 鍵:原廠 16 格後是 RAW、p2d60(、Kodak 設定並轉檔後);游標移到 LUT 列 → **畫面立刻是那個 LUT**(預覽),
   記下每步有沒有可感覺的延遲(估計數 ms);來回移動多次不卡、不凍結;OK 選定。
4. 錄影中開 COLOR:游標到已選的 LUT 列 → LUT;到別的(未預覽過的)LUT 列 → 原廠、不卡;停錄後開關一次選單 → 選定的 LUT 出現。
5. 錄一段 MOV、拍 JPG:LUT 有燒進去(與之前相同)。
6. 多列:換 rows-test `--rows 12` 版(`rows-test/out/rows12/`)看 12 格都畫得出、選得到(19 列已過)。
