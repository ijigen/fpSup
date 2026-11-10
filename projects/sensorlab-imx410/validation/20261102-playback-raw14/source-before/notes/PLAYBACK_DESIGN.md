# SensorLab-IMX410 機內回放設計(2026-10-30,離線)

範圍:讓 SensorLab 錄的 CinemaDNG(虛擬 mode 230/231,任意尺寸／格率,8/10/12-bit,1:1 時真 14-bit)能在機內回放。
本輪只做離線建置與模擬，沒碰相機。[驗] = 源碼或明列的驗證紀錄；[推] = 推論，要上機確認。
實作屬於 `apply/`。下方 §0–6 保留最初設計，當中的「沒有 hook／尚未做」描述的是 v0.5 基線。

## v0.7.13：回放描述表越界與高速播放節奏（2026-11-02，僅離線）

原廠 `C05C2D10` 向 pool 11 配置 `0x6F090` bytes 描述表，每項 `0x5EC` bytes，容量恰為 300；其 pool 10 RAW 配置迴圈沒有數量上限。未修改 ROM 在第 301 個成功配置後於 `C05C3648` 寫出表外。這發生在 prepare 的格率檢查之前，亦可影響稍後會拒播的高速片。物理配置結果是明列模型；未證實相機那次凍結或插卡掃描必定經過此路徑。

`H_PBRING` 位於 `C05C2DE8`（原字 `EBE968FE`，BL `C001D1E8`），在 count 已達容量時回傳 NULL，直接走原廠結束路徑；尚未達容量時照常呼叫原廠配置器。沒有額外計數狀態，清理與重建沿用原廠。零 RAW 配置時原廠描述表釋放缺陷不屬此修正，測試不將該路徑宣稱為清理通過。

原廠 `C06A0770` 將約 239 fps 以上分到 11–13，但 `C05BCB60` 對這些類別只有零表。兩個既有 prepare 入口在檔案／owner／壓縮／模式 guard 通過後，只把目前選中 player 的 runtime 格率類別 11–13 轉為 10（原廠表 `5994,2,1`）。檔案幀率標記保留；不是精確原速回放，低於 23 fps 的類別 0 仍未支援。

已執行原廠選片／TIFF／prepare／ring／queue／descriptor／cleanup 與實際交付 BIN；配置器、XMP 空初始化、鎖、檔案 I/O、非同步工作、解碼仍為明列模型。24 個實拍首末 DNG 標頭 × 2 prepare 路徑通過，三個有效變異均被拒絕；硬體解碼／LCD／DMA／聲音／插卡凍結仍未驗證。詳見 [修正與證據](../validation/20261102-playback-ring-fix/README.md)。

## v0.7.10：原廠 parser 不保留 Compression（2026-11-02）

v0.7.9 的實機回報仍是選片立即不能檢視。新測試實際執行 `setPlayInfo C03BAB68` → `v2 C05BCF28` → `v11 C05BDB08` → `C00C1508` / `C00B8D58` → `C05C1A58`，由檔案 bytes 自行建立 TIFF 物件，不再人工供應每個 tag。三份保存的 DNG 均能讀出尺寸和位深，但 `C05C1ED0(tiff,0,0x103,...)` 回傳 0；v0.7.9 因此拒播。前一輪的成功模型過度提供了該標記，不能作為實機成功證據。

修正只在 v11 的 parse 呼叫 `C05BDC9C`（原字 `EBEC0E19`）增加觀察：既有 r1 read buffer、r2 byte count，r4 為 player。先核對 TIFF endian/magic、IFD 範圍、最多 512 entries、Compression 必須是單一 SHORT；綁定 owner/file descriptor/parse handle。仍呼叫原廠 parser，既有 tag hook 只在這份壓縮資訊一致且值為 1 時放行。沒有新增檔案 I/O、buffer allocation 或全影格 CPU copy。

新測試與隔離反例證明：實拍標頭可進 prepare；壓縮或另一 owner 仍拒播。原廠低格率限制另列未解決：小於 23 fps 被 `C06A0770` 分成 enum 0，`C05BCB60` 回傳空格率，prepare 失敗。本版不改格率或宣稱所有格式可播。詳細前後對照、未驗項目與成品見 [本輪證據](../validation/20261102-playback-entry/README.md)。

## v0.7.9 候選（2026-11-02，僅離線）

使用者回報「檔案內容不能檢視」。v0.7.0–0.7.8 的預設會在原廠 prepare 前拒絕非原廠 raster；v0.7.9 改為開啟自訂 canvas，但保留 admission guard。`v11` 的 `context=obj+0x1AC`、`raster=obj+0x98` 識別目前選中片段；保存其檔案識別與已核對標頭，兩個 prepare 入口必須與這份快照相同。canvas 使用此快照，瀏覽索引的同 crop 快取不能替換它。Compression=1、合法位元深度及原有錄影幾何才會放行。模式 0 的原廠限定 fallback 保留。

原廠 prepare `C05BE080`／配置包裝 `C05BC408`、key／canvas 與 FieldAngle 計算已在模擬器執行；配置器、記憶體服務與非同步工作仍為明列的 fixture。已保存的 2K／原廠 DNG 僅重播標頭，沒有解碼像素。先前實機黑屏的原因尚未證實，不能把快取缺陷的修正當作黑屏已解決。完整測試、反例、來源及硬體限制見 [本輪紀錄](../validation/20261102-playback-checked/README.md)。以下 v0.6 資料為歷史設計。

## v0.6 實作與離線驗證（2026-10-30 接手更新）

回放核心已實作，不能再把它列成「尚未開始」。完整 SensorLab BIN 的版本、entry 整合與成品雜湊由 QS builder 管理；本節不把單元測試當成上機通過。

| 功能 | 現況 |
|---|---|
| 片子自己的畫布 | `ap_pb_tag` 讀實際 raster、crop、bits、DefaultScale；八筆 tag cache；`H_PBNAME` 只鎖存原廠 key builder 的裁切；`ap_pb_canvas` 改回放畫布，離開回放清 active |
| 8／10／12-bit | 保留原廠類別；原廠 FHD/UHD 的畫布逐位元不改；自訂尺寸修正列寬 |
| 14-bit | 原廠 reader 的 14→RAW8 改走 12-bit profile lookup，再把回放畫布 low-byte 平面碼設成 8。已模擬 profile 與畫布結果，未驗真正 RAW 顯像／解包／DMA |
| DefaultScale | 非方形配方在 IFD0 寫 C61E、RATIONAL×2；回放讀它計算 LCD 比例。尺寸恰等於原廠格式時也照比例處理 |
| 尺寸數字圖磚 | `pb_glyph.*` 產生字形模板；commit 排隊、UI 執行緒 `ap_idle()` 註冊 NBR。每次開機最多八個新數字；沒有圖磚的舊片尺寸行會隱藏，避免雜訊 |
| 誤導的 FHD 標籤 | `pb_page.py` → `pb_page.h` 的 616-byte FPUI block，替 Playback 三個 Resolution clip 加 enum 3 空白影格。原廠 0／1／2 的 image、size、rect 不改。只有 `fpui_stock_apply` 成功後才 `ap_pb_ctl(mem,2,AP_PB_PAGE_FRAME)` |
| 非原廠格率 | 沿用原廠量化節奏，符合 Bei 定案；精確播放時間不是 v1 工作 |

接手時原有回放測試有重複記憶體映射、資源模組 import 次序、NBR reader 欄位名三個錯誤，導致回放案例沒有真正跑完；現已修正。另以先失敗再修正的測試重現兩個產品問題：

- mode 2 沒有 live slot 時，RAW14 仍被改成 RAW12 查表類別，卻不改畫布；現與畫布使用相同的啟用條件。
- raster/crop 剛好匹配原廠時，DefaultScale 原本被跳過；現只在像素比例也是 1:1 時直接保留原廠畫布。

驗證指令（`apply/`，無相機 I/O）：

```sh
python3 -B -m unittest -v test_apply test_pb_page
python3 -B test_apply.py --mutate --only=52 --only=53 --only=54 --only=55 --only=56 --only=57 --only=58 --only=59
```

- 完整回歸 **47 項通過**，紀錄 `apply/build/playback-test.log`。實際 ARM/Thumb apply、原廠 tag reader／profile key／canvas gather、FPUI C applier 在 Unicorn 執行；檔案 tag 底層、NBR loader、配置器與 GUI 通知是明示 stub。
- FPUI 驗證：實際 C 產生的 page bytes = Python reference；原廠頁不寫；重裝或 guard 不符不更換 runtime entry；原廠三影格內容不改；allocation 的 properties／keys 餘量不變。
- 八個回放反例涵蓋模式閘門、DefaultScale、列寬、RAW14 平面碼、退出狀態、DNG tag 型別、缺字隱藏、原廠 HD/DCI 標籤。結果見 `playback-mutate.log`、`playback-mutate-58.log`；58 首次因未使用變數無法編譯，已修成可編譯的有效反例後單獨重跑，不能把編譯失敗算 caught。
- sandbox 內的 Unicorn 在第一個 ARM 案例收到 SIGILL；同一指令經本機執行核准後可執行。沒有將 sandbox 中斷當作通過。

`ap_idle` 只能從 UI callback 呼叫；目前 queue 在成功 commit 結尾產生，因此 QS `leave()` 的順序要是 `sq_push/ap_flush → ap_idle`。不能透過 USB task 直接呼叫 NBR loader。未選過的舊片尺寸沒有新圖磚時，先採上述隱藏尺寸行的 fallback。

仍須上機的項目：T1 自訂片進入／暫停／播放／退出，T2 原廠回歸，RAW14 實際解包與顏色，DefaultScale 在 LCD 與後製的效果，圖磚與空白標籤實際顯示，暖開機。

大幅面仍是未驗證風險：原廠 FieldAngle 計算器算得 p51 為 14,752,488 B，A001_261 為 6,419,320 B，OG3K 為 11,153,160 B；6048×3402 為 36,120,128 B，6048×4040（12 或 14-bit）為 42,815,976 B。這只是尺寸計算，不證明相機當時有足夠回放池。現行程式沒有最初 §3.5 提議的 22 MB 閘門；大幅面必須單獨分級驗證，不能由單元測試宣稱已可播。§7 已釐清 FieldAngle 使用 48 MiB LVIEW 池，另有固定 80 MiB 的輸出緩衝，兩者不可混算。

## 0. 結論

- **今天很可能不能播，而且可能凍結。** A001_261(2016×1330,裁切 2000×1320,12-bit)在原廠回放會拿到 FHD 回放 profile p73,
  它的柵格是 1936×1090,跟片子的列寬 2016 不一致。OG2K 的片子也是 2016 寬，在同樣情況下**黑屏凍結、要拔電池**
  [驗 `open-gate/notes/OG2K_PLAN.md` 第十輪]。SensorLab 目前沒有任何回放 hook [驗 `apply/ap.c` 26 個站點]。
- **推薦做法：照搬 OG3K/OG2K/RES-Custom 已上機成功的「回放畫布」機制，但改由 DNG 本身驅動，不查表。**
  做法是一個新觀察 hook,外加擴充兩個現有 hook。12-bit 以下、任意尺寸都能播，原廠片子逐位元不受影響。
- 14-bit、非原廠格率的播放速度、變形(非方形像素)的顯示比例，以及缺字型圖磚，各是獨立的後續項目(§5)。

## 1. 今天的回放怎麼運作 [驗]

| 階段 | 函式／站點 | 讀什麼 | 來源 |
|---|---|---|---|
| 讀片子資訊 | `FUN_c05c1a58` | 只讀 6 個 tag:DefaultCropSize、ImageWidth/Length、BitsPerSample、FillOrder、FrameRate | OG3K_PLAYBACK_PROFILE_CLASSES §12;反編譯 blk_c05.c:146663 |
| 位深分類 | 同上 | `12→0`、`10→3`、**其他(含 14)→4 = RAW8** | 同上;OG14_FEASIBILITY §2 |
| 格率 | `FUN_c06a0770` | `分子/分母` **取整數**後落到 enum:<23→0、23–24→2(分母 1001 時→1)、25–28→3、29–47→4、48–49→6、50–58→7、59–98→8、99–118→9、119–238→10、239–398→11、399–1198→12、更高→13 | blk_c06.c:130663 |
| 選回放 profile | `FUN_c043bc68`(配置器 mode 5)以解析度名當鍵 | 名稱發射器 `C0437B48` 比對**裁切尺寸**:4096×2160→DCI4、3840×2160→UHD、1280×720→HD,**其餘一律 FHD** | §8;OG2K 第十輪 |
| 回放 profile 表 | `0xC0BE4508` | 3 個位深 × 4 個解析度，共 12 個影片回放 profile,全是 16:9,**沒有空位** | §4、§8 |
| 畫布 | `C043A198 bl c0439d18` 填好 → `C043A19C`(SensorLab 已有 H_CANVAS) | 回放類的判別：畫布 `+0x80` 有 bit16(0x1000A/0x10009/0x10007);506 個 profile 只有這 12 個有 | §3 |
| 顯像 | `FUN_c05bb4a0` 把每格交給 RAW 顯像引擎 | 像素位址、strip、寬高、bits 都直接從檔案來，是對的 | §13 |
| 檔案緩衝 | `C05C2D10` | 每格 `(檔案位元組+0x1FFF)&~0xFFF`,一直配置到池子滿為止 | OG4K_SIZING |
| LCD 輸出描述子 | `C0437E98` | 回放沿用待機的 1620×911 / 320×180 | §13、§14b |
| picker | — | **回放不走 picker** | OG3K_WHAT_WAS_WRONG |

**失敗的根因只有一個：回放 profile 的柵格必須等於檔案的列寬** [驗 §14]。
原廠片子的列寬一定等於「裁切 +16 寬 / +10 高」,剛好就是它那個 profile 的柵格。

### A001_261 的實際 tag [驗,本輪解檔]

ImageWidth/Length = 2016×1330、DefaultCropSize = 2000×1320、BitsPerSample = 12、未壓縮、只有 IFD0、沒有 DefaultScale(C61E)。
FrameRate = 14400000/480511,取整後是 29,落在 enum 4。

推下去:鍵是 "FHD",12-bit 那組 → p73(柵格 1936×1090)→ 列距差 80 像素 → **花屏或黑屏凍結** [推;同寬度的 OG2K 是凍結]。
回放 HUD 的尺寸字會畫成彩色雜訊：韌體有 `font_S_imageSize_2000`,**沒有 `_1320`** [驗 本輪掃 MAIN 的 71 個資源;OG2K §AR 同一機制]。

### 既有 sup 的回放紀錄

| sup | 結果 | 證據 |
|---|---|---|
| OG3K 12-bit | 暫停與播放都正常(A001_037);8/10-bit 沒驗 | §14、fpSup/opengate/README |
| OG2K(2016 寬) | 修正前黑屏凍結;v0.1.3test 可進、可播、不凍結;左上角有字型雜訊 | OG2K_PLAN 第十、十一輪 |
| OG2K p221 版 | DefaultCropSize 0×0 → 進回放當機、失去 USB | OG2K_PLAN 第七輪 |
| RES-Custom(通用化之後) | 機制在 `ogc_name`/`ogc_canvas`/`ogc_out`;**沒找到任何上機回放紀錄** | res-custom-v4/ogc.c:1203–1260;res-lab 各輪都寫「回放未驗」 |
| Julien R181 | 宣稱 mod 片子「以自己的形狀」播放，可暫停、逐格;壓縮幀略過(SD 只看到第一格、SSD 約半速)。作者自己也還沒上機 | upstream R181/NOTES.md |
| raw-view | 與回放無關(LV 工具) | — |
| PlaybackAction | 不是回放的必要閘門;action 7 = 播放中再按 Play | memory playback-action-gate-real |

R181 比 R168 多出來的站點 [驗 本輪比對 FRM1]:
- `C043A198`(畫布填寫)、`C043C000`(`bl c043bc68`,回放 profile 選擇)、`C05C1964`(每格讀 0x111 StripOffsets,用來略過壓縮幀);
- `C0422950`(`bl c02dafa0` 比例 getter);
- `C04288CC` / `C04288E8`(兩個 blx,推測是播放中隱藏疊圖);
- `C0306F28` / `C03077A8`(比例)。

這些站點的含義是 [推],之後可以拿來對照，但不照抄。

## 2. RES-Custom 怎麼做，SensorLab 能沿用什麼

RES-Custom 的流程 [驗 ogc.c]:
- `ogc_name`(C0437B48)拿發射器收到的**裁切尺寸**去比 RCD 列的 `act`,命中就記 `S_PBROW`;
- `ogc_canvas` 在畫布有 `+0x80 & 0x10000`、且 PBROW 有值時，套用那一列的 13 筆回放 pair;
- `ogc_out` 在 PBROW 列是 3:2 時，把 LCD 描述子改成 1620×1080 / 320×213;
- 呼叫者是鍵組建者(lr = C043BCBC)時，發射器一律交回原廠，查表鍵不能動(§8 的教訓)。

13 筆 pair [驗 rl_v3.c:242–247]:

| 畫布位移 | 值 |
|---|---|
| 0x1C | 2 |
| 0x0C / 0x10、0xD8 / 0xE0、0xF4 / 0xF8 | 記錄尺寸(= 檔案柵格) |
| 0x20 / 0x28 | 裁切 |
| 0x60 / 0xD0 / 0x64 / 0xD4 | 1024 |

`+0x44`、`+0x80` 不動，類別要留著。

**可以沿用**:13 筆的公式、bit16 守衛、KEYBLD 放行、輸出描述子的做法。
**不能照搬**:RES-Custom 是「列表驅動」,只認得卡上已註冊的格式。SensorLab 的配方在 QS 上隨時會換，卡上的舊片子是之前配方錄的。
所以 SensorLab 必須**從片子本身推出幾何**。這剛好可行，因為 SensorLab 的記錄尺寸一律是 `act + 16 / + 10`
[驗 core.c:713 `act0 = rec0 − MARGIN_W`],A001_261 也符合。

## 3. 推薦設計(v1)

### 3.1 hook 與狀態

| hook | 站點 | 類型 | 做什麼 |
|---|---|---|---|
| **H_PBNAME(新)** | `C0437B48` 名稱發射器入口(`push {r4-r8,sb,fp,lr}`) | K_ENTRY,只觀察，一律往下走原廠 | 拿 `[r2+8]` / `[r2+0xC]`(裁切 w/h,非 0 才記)當 `pb_crop` 存起來，序號 +1。不改輸出，也不改查表鍵 |
| H_PBTAG(新，選用) | `C05C1A58` 入口 | 先往下呼叫，回來再讀 | 讀 `param_4[0..1]`(實際柵格)、自己再讀一次 0x102 拿原始 bits。存進 8 筆小環 `{crop, raster, bits}`,讓 H_CANVAS 交叉核對。縮圖列表會連讀很多片，所以不能只信最後一筆 |
| H_CANVAS(擴充) | `C043A19C`(已有) | — | 新增回放分支，見下 |
| H_OUT(擴充) | `C0437E98`(已有) | — | `pb_active` 時用片子自己的比例 |
| H_ASP / H_RATIO | 已有 | — | `pb_active` 時不回答 live 配方的比例(避免拿現在的配方去畫舊片子) |

H_CANVAS 回放分支的條件與動作:
- 條件：畫布 `+0x80 & 0x10000`,而且 `pb_crop` 有值;
- 計算 `ras = crop + (16, 10)`;有 H_PBTAG 的話，要求環裡有一筆同 crop、raster 相同，否則不動;
- **只在 `ras ≠ 畫布現值 +0x0C / +0x10` 時**寫入 13 筆,`+0x1C` 照 RES-Custom 寫 2。
  所以原廠 FHD/UHD/DCI4 片子永遠不會被改(1936×1090、3856×2170 剛好等於原廠柵格);
- 寫入後設 `pb_active = 1`,計數 `pb_patch++`;
- 任何**不帶** bit16 的畫布載入時清 `pb_active`。退出回放會重開 LV,LV 會載入非回放畫布 [推]。

H_OUT 在 `pb_active` 時，用 `apc_display` 同一套公式，以片子的裁切寬高算 `box_w/box_h`(idx 0)與 `det_h`(idx 2)。
接近 16:9 就不動。

### 3.2 DNG／片子 → 配方的對應

v1 **不需要把片子對回配方**:幾何、位深、格率都在 DNG 裡，自我描述。
唯一缺的是**像素比例**:
- SensorLab 的配方可能不是方形像素(zoom × scale × bin 兩軸不同，見 `ap_calc.c` 的 dng_aspect);
- DNG 沒有寫 DefaultScale。

v1 先用 DNG 像素幾何顯示(方形像素)。要正確顯示變形畫面，選項如下(問 Bei):
- (a) 錄影時在 DNG 標頭寫 **DefaultScale**(C61E)。標準欄位，Resolve 也會用;但標頭佈局是固定的，要找可以換掉的欄位;
- (b) 小 sidecar。違反「停止路徑要薄」,也增加 SD 爭用;
- (c) 在 SensorLab 自己的 BIN 裡存 `take 名稱 → 比例` 表。只對本機錄的片子有效。

### 3.3 格率

播放節奏只吃 `FUN_c06a0770` 的 enum,有效精度就是那 13 格 [驗 函式本體;消費端還沒追到，所以「播放速度 = 該格的標稱值」是 [推]]。

| 片子格率 | enum | 結果 |
|---|---|---|
| 29.968(A001_261) | 4 | 與 29.97 同格，沒有差別 |
| 37.14 | 4 | 約 0.8× 慢放 [推] |
| 72 | 8 | 約 0.83× [推] |
| 23.976 但分母不是 1001 | 2(24) | 差 0.1% |

v1 接受這個量化(只影響機內預覽速度，不影響檔案)。
v2 若要準確：先離線追 `param_2+0x18` 的消費端(enum → 週期),再用 H_PBTAG 拿到的分數改週期。

### 3.4 位深

- **8/10/12-bit**:原廠就依 BitsPerSample 選對類別;我們只改幾何。
  OG3K 的 8/10-bit 回放沒驗過，要列入測試 [驗 fpSup/opengate/README]。
- **14-bit(只有 1:1 配方)**:會被歸成 RAW8 類 → 位元組列距算錯。改幾何救不了。
  v1 的規則是：H_PBTAG 看到 bits = 14 就**不寫畫布**,並記 `pb_skip14++`。
  但這樣仍是原廠行為，也就是可能凍結。所以 14-bit 必須等 §5 的研究，或請 Bei 決定 v1 是否接受。
  縮放過的 14-bit-AD 配方是 12-bit 容器，走 12-bit 路線，沒問題 [驗 ap_calc.c:224–229]。

### 3.5 凍結風險清單

| 風險 | 依據 | 對策 |
|---|---|---|
| 柵格 ≠ 列寬 | OG2K 黑屏凍結 [驗] | §3.1 本身 |
| DefaultCropSize 0×0 | OG2K p221 當機 [驗] | SensorLab 有寫裁切 [驗 A001_261];crop 是 0 一律不動 |
| 大幅面超過回放池 | 已知池子服務過 p51 22 MB [驗]。6048×4040 級的片子一格約 37 MB,畫布需求約為 p51 的 3 倍 [推] | 離線用 unicorn 跑原廠 `C0435428/C0435588`(OG4K_SIZING 的做法)算各級需求;v1 只對 ≤ 22 MB 的寫畫布，更大的等上機分級測 |
| 狀態殘留(`pb_active` 沒清)→ LV 用到片子比例 | 推 | bit16 守衛 + 非回放畫布清旗標;上機核對退出後 LV |
| 改到查表鍵 | §8 [驗] | H_PBNAME 只讀不寫 |
| 回放中 USB | memory [驗] | 回放中零 USB;證據用計數器，退出等 10 秒再讀 |
| 壓縮幀(Lossless sup 同卡) | 原廠回放不解 Compression=7 [驗 OG_2K_3K_4K_QUALITY_OPTIONS] | 不在 v1;R181 的 `C05C1964` 是可參考的略過做法 |
| 沒載入 SensorLab 卻播 SensorLab 片子 | 等同今天 | 發布說明要寫明 |
| 與 OG sup 同卡 | 兩個都改同一張畫布 | 我們只在 ras ≠ 現值時寫，寫的值與 OG 一致，結果冪等 [推] |

### 3.6 工作量

v1:
- `ap.c` 新增 1–2 個站點，擴充 3 個 handler,約 120–150 行 C;
- `test_apply`:新站點的原廠字比對;用 A001_261 的標頭在 unicorn 跑真 `FUN_c05c1a58` / `C0437B48`;
  真 `C0435588` 的尺寸上限;原廠 FHD/UHD 片子「零寫入」的反證;mutation 測試;
- 估計離線 1 天、上機 2–3 輪。

v2 各項各約 0.5–1 天，另加研究:字型圖磚、DefaultScale、精確格率、14-bit。

## 4. 上機分級

每一輪：先告訴 Bei 並等回覆、廣播相機使用權;回放期間不接 USB 指令。

- **T0(原樣，就是 Bei 要的第一個測試)**
  - 不改卡。卡上 A001_262 是最新的原廠 FHD 片子，所以按 PLAY 會先停在它(安全)。
  - 接著:
    1. Bei 按左鍵一次到 A001_261,看暫停畫面;
    2. 看縮圖／索引畫面;
    3. 按播放;
    4. 退出。
  - 用手機拍 LCD,或退出後再截圖。
  - **預期 [推]**:花屏或黑屏凍結。凍結就拔電池(回放只讀卡，片子應該沒事)。
  - 這一輪的價值：確認基線，並看縮圖路徑會不會在暫停之前就出事。
- **T1(v1)**:A001_261 暫停 → 播放 → 退出。退出 10 秒後讀計數:`pb_crop = 2000×1320`、`pb_patch > 0`、`pb_active = 0`。
- **T2 回歸**:原廠 FHD、UHD 片子各播一次，必須 `pb_patch = 0`。退出後 LV 正常。
- **T3 幾何**:3:2、接近 16:9、2:1、比 3:2 高的、小幅面(~1000 寬)、大幅面(依離線尺寸表由小到大),另加 8/10-bit 各一段。
- **T4 格率**:23.976、37.14、72、119.88、240 各 5 秒，用碼錶量播放時長。
- **T5**:SensorLab 已退回原廠(active 0)時播 SensorLab 片子(應該照樣正常);RES-Custom／OG3K 片子(順便確認通用性)。
- **T6 14-bit**:等 §5 定案後才做，單獨一輪，準備好拔電池。

## 5. 後續項目

1. **字型圖磚**:回放 HUD 對寬高各查一次 `font_S_imageSize_<N>`。韌體只有 71 個 N,1320 不在裡面。
   rl_v3.c 已經會在相機上產生 XCI;做法是「缺哪個補哪個」,註冊進私有 NBR。
2. **DefaultScale**:見 §3.2。
3. **精確格率**:見 §3.3。
4. **14-bit**:要先查 RAW 顯像引擎(與照片共用)能不能吃 bits = 14 的未壓縮封裝;
   再看能不能把 enum 改成 0、配一個 14-bit 的畫布平面碼(0x80/0x84 = 7/8,core 已有)。查不通就只能讓 14-bit 片子乾淨地拒播(機制未知)。
5. **R181**:反組譯它在 §1 那些站點的 payload,對照它的「自己的形狀」是怎麼算的。

## 6. 要問 Bei

1. T0 原樣測，預期可能凍結、要拔電池，可以嗎?
2. 變形配方在回放中要顯示真實比例嗎?要的話，選 DNG 寫 DefaultScale(後製也受益)還是本機表?
3. 14-bit(1:1)回放 v1 需要嗎?不需要的話，可以接受暫時「不保證、可能凍結」嗎?
4. 非原廠格率在機內以最接近的標準格速度播放(例如 37 fps 用 30 播),可以接受嗎?
5. 回放 HUD 寫 "FHD"、尺寸字是雜訊：要在 v1 一起修嗎?
6. 通用機制也會修好 OG／RES-Custom 片子的回放(只要 SensorLab 有載入),要保留這個行為嗎?

## Bei 定案（2026-10-30）
1. T0（原樣播 A001_261，可能凍結要拔電池）：可以做。
2. 非原廠格率用最接近的標準格速度播：可以。
3. 變形配方：在 DNG 寫比例（DefaultScale），後製也受益；回放照它顯示。
4. 14-bit（1:1）回放、HUD 的 "FHD" 字樣與尺寸字雜訊：v1 一起修。

## 7. 6K 回放記憶體池核對（2026-10-30，靜態確證）

**已證明目前輸出描述子的全部緩衝合計不超過原廠固定 80 MiB；尚未證明 6K 回放當時可成功取得所有記憶體。** `42,815,976 B` 是另一個 LVIEW 池的 FieldAngle 需求，不能拿它單獨和 80 MiB 比較，也不能把它當作整個回放流程的總需求。本次只讀韌體及現行實作，未更動 `ap.c`、未新增拒播 hook，未做相機操作。

### 7.1 三種配置分開計算

| 用途 | 原廠配置路徑 | 池與大小 |
|---|---|---|
| CinemaDNG 檔案環形緩衝 | `C05C2D10` | pool 10 `RAW`；每個檔案緩衝 `(file_bytes + 0x1FFF) & ~0xFFF`，反覆配置直到回傳 NULL。描述子另在 pool 11 `JPEG` 配 `0x6F090` B |
| LCD／顯像輸出緩衝 | `C05BE080 → C05BC408(&object[+0x4FC], 9, 0x5000000, 0)` | pool 9 `YUV`，固定 **80 MiB = 83,886,080 B**，原廠同一路徑已如此配置 |
| RAW 顯像 FieldAngle 工作區 | `C0428AB8 → C04371F0 → C0436EC8 → C0437AF8 → C0435588` | 回放 class 5 走 pool 3 `LVIEW`；全幅 6064×4050 raster、6048×4040 crop 的已測計算值 **42,815,976 B** |

來源：`out/decomp/full/blk_c05.c:147562`（檔案環）、`:144018`（80 MiB）；`blk_c04.c:26987`、`:37423`、`:37250`、`:37844`（FieldAngle 呼叫鏈）。`C04371F0` 明確把 class 3／4 與其他 class 分開；回放 class 5 的配置呼叫是 `C001CF78(3)`、`C001D038(...)`，base 存 object `+0xE8`、size 存 `+0xEC`，不是 80 MiB 輸出物件的 `+0x4FC`。

pool 名稱來自 ROM `C2EF727C` 的指標表；memory-mode 名稱表 `C2EF7248` 的 index 8／9 分別是 `PLAY_CINEMA_DNG`／`PLAY_CINEMA_DNG_ONE`。這些指標表在 `out/seg1_c2ef6e00.bin`，字串本體在 `out/seg0_c0000000.bin`。

### 7.2 `C0436D98` 全部輸出 slot 的合計

`C0436D98` 逐一處理四個 slot，`C0436538` 把每個來源的 11-word 描述子複製到目的記錄的 `+4`；非獨立 base 的 slot，以來源 `word[7] × word[8]`（buffer count × bytes per buffer）推進 base。flag `0x20` 的 slot 使用另一個 base。見 `blk_c04.c:37215`、`:36779`。

電影回放 profile 選 configurator `+0x4CC`／`+0x4F0`／`+0x514`（`blk_c04.c:40639` 起）。三者初始化如下（`:39875`）：

| configurator | slot 0 | slot 1 | slot 2、3 | 合計 |
|---|---|---|---|---:|
| `+0x4CC` | constructor descriptor `+0x1B8`（`param+0x6E`），count 4、每個 `0xFD2000` B | `C2F213B8`，count 4、每個 `0x3FC000` B | 皆 NULL | **83,066,880 B** |
| `+0x4F0` | constructor descriptor `+0x1E4`（`param+0x79`），count 4、每個 `0xFD2000` B | 同上 | 皆 NULL | **83,066,880 B** |
| `+0x514` | constructor descriptor `+0x210`（`param+0x84`），count 4、每個 `0xFD2000` B | NULL | 皆 NULL | **66,355,200 B** |

最大值是 `4 × 0xFD2000 + 4 × 0x3FC000 = 83,066,880 B`，比固定 `0x5000000` 少 **819,200 B**。slot 0 三個描述子的 count／size 在 `blk_c04.c:39834` 附近逐字初始化；slot 1 的 `C2F213B8` ROM words 7／8 是 `4`／`0x3FC000`，`C0438338` 只透過 `C02E5B38` 初始化其幾何。

SensorLab `ap_out_tpl`（`apply/ap.c:465`）先複製全部 11 words，再只改幾何 words 0、1、4、5；它保留 words 7、8。因此目前比例修正沒有增加上述 count／size 合計，也沒有把 6K 原始 raster 當成 LCD 輸出尺寸。本輪沒有發現需要新增 80 MiB 越界拒絕的條件；這個結論限於目前三組描述子與現行 handler。

### 7.3 48 MiB LVIEW 容量與仍未證明的部分

`C001EE58` 的 memory-mode 8／9 靜態表均把 pool 3 配成 `0x03000000 = 50,331,648 B`（48 MiB）。證據為 `blk_c00.c:28394` 起的 `C3073F28` 表，以及 `:28443` 起的 `C3073E74` 表。兩張表的 pool 10 RAW 容量分別是 530 MiB、310 MiB；pool 9 YUV 分別採剩餘容量、固定 260 MiB，不能因此把 LVIEW 池當成可跨池借用。

已執行原廠 FieldAngle 算式的測試位於 `apply/test_apply.py` 的 `PoolTests.test_sizes`（約 `:1461`），全幅值 42,815,976 B 比 48 MiB 少 **7,515,672 B**。這只能證明該筆配置小於名義池容量。

**同時存在的其他配置與碎片化仍未驗證。** 例如 `C03C5C88` 在 `TakeOneFrameImage` 前透過 `C001D740(...,3,...)` 配暫存影像，成功後還會再配另一個 pool 3 緩衝（`blk_c03.c:139055`、`:139078`）；不能假設 FieldAngle 是 LVIEW 池內唯一的消費者。尚未取得實際回放 memory-mode、當時可用最大連續區塊、所有同時配置的壽命交集與完整 6K 顯像結果。此處不宣稱 6K 已可播。

### 7.4 配置失敗不是乾淨拒播

- `C05BC408` 的 80 MiB 配置回傳 NULL 時直接呼叫 `C0011130` assert（`blk_c05.c:142572`）；這是原廠同一路徑的既有行為，本次幾何修正沒有增加該筆配置大小。
- `C04371F0` 的 LVIEW 配置失敗也走 assert；已配置物件的容量小於新需求時同樣 assert（`blk_c04.c:37447` 起）。
- `C05C2D10` 的檔案環配置到零個 buffer 時仍把 initialized 設為 1，沒有回傳錯誤；不能把 NULL 視為已有安全退出。其 cleanup `C05C2E90` 只在 count 非零時釋放描述子（`blk_c05.c:147610` 起）。

因此不採舊 §3.5 的「超過 22 MB 就只略過畫布改寫」提案：保留錯誤 stride 仍可能讓原廠繼續顯像。若後續證明需要拒播，必須在完整處理啟動前返回失敗，並驗證呼叫者確實處理這個失敗；目前沒有為此增加 hook。靜態候選是 `C05BE080` 的早期失敗出口，仍需獨立驗證完整 UI／退出流程，不能只讓 `C05C1A58` 或 `setPlayInfo` 回傳 0 就宣稱已拒播。
