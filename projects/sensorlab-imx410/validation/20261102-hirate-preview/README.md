# v0.7.11test：高速畫布欄位補齊，尚待實機驗收

使用者回報約 200 fps、38 MB/s、S16、0.3K，錄影開始幾秒後 liveview 停住。持續寫入是否正常尚未證實；沒有確切 RECIPE 或數字尺寸。S16／0.3K 的未修改選單預設推得 DC 2096×1240／RES 336×206，僅作離線案例，不能當成讀回的相機設定。本輪未操作相機、USB、daemon、卡或批次 runner。

## 已確認的遺漏與有限修正

純幾何 `core_quality_spec()` 設定 `hirate=0`。SensorLab 原本直接交給 ISP 規劃，導致高速載體的畫布 +B0 也一直是 0。原廠 FHD100／FHD120 的值為 1，FHD30／FHD60 為 0；既有 RES-Custom 高速設定也有此欄位。

只在 `apc_build()` 的幾何規劃後補一個共用判斷：`w->spec.hirate = cr->rank >= 10000u`。判斷原廠載體，不能看 engine >99：原廠 100／120 載體的 engine 為 50／60。本次沒有改引擎格率、感光元件時序、DNG 實際格率、比例公式、緩衝區或新增 hook。AP ABI 2／QS API 6、40 apply hooks＋clock 共 41 claims 沿用。

## 離線證據

`apply/test_hirate_preview.py` 透過真實畫布 gather、hook 與 ARM 套用程式，執行下列 ROM 路徑：

1. C0434EF8：canvas +B0 → config +14。
2. C01D1630 前綴至 C01D1958：config +14 → C31DF578。
3. C01D7CE8 的分類、C01D3CB0／C01D7D58 getter、C01D0640 selector。
4. C01CABA0 前綴至 C01CABF0：selector → descriptor +0C。

每段有指令範圍與步數界線；未宣稱執行整個引擎初始化。明示替身為相機狀態服務 C00178D8／C0017AC8／C032C900、與此欄位無關的感光器 MMIO flag C01259C0、佇列 flag C01D7948。沒有用替身供應被核對的高速欄位。

五項新測試涵蓋原廠 30／60／100／120 參照、自訂載體、200 fps 的七種 S16 小尺寸配方、返回低速、原廠其他 profile／standby／停用還原。整列比對確認 200 fps 案例只差 +B0。報告分列 requested_fps 與 actual_fps；要求 239.76 的 3x6 配方因下限實際為約 209.04，**不是 239.76 fps 錄影驗證**。

- `regression.log`：91 項（包括新測試）通過；錄影參數、預覽、選單、回放與原廠選片解析皆回歸。
- `qs-regression.log`：9 項通過。
- `settings-migration/report.json`：8 項通過，含真實 v4 loader／sup 入口與凍結 BIN 比對。
- `candidate-final.json`：最終原廠欄位傳遞及現有公式檢查通過。
- `old-source.json`：保存的舊來源可編譯，測試失敗且無測試錯誤；`mutant.json`：將判斷錯換成 `o->fast` 的獨立副本在 60／72／100／119.88 載體被抓到。
- default 與 repro 兩次獨立產出的 BIN 逐位元組一致，詳見 `REPORT.json`。

共 108 項離線測試通過。這些測試不模擬實際 DMA、RTOS 時序、記憶體壓力或持續錄影，**不能證實 +B0 就是幾秒後停住的根因，也不能證實相機已修好**。回放保留 v0.7.10 的修正，但實機回放仍待驗收。

## 交付與使用者驗證

只交付 `fpSup/SensorLab-IMX410_v0.7.11test.BIN`，QSContainer v0.3.4、AutoRun／LOADER 沿用。本包為預設設定版，換檔後需重選原本的 SensorLab 設定。

請使用原本約 200 fps／38 MB/s／S16／0.3K 的設定試錄約 30 秒，觀察 liveview 是否持續更新，以及停止錄影後預覽是否恢復；若仍卡住，再記錄 RECIPE 和實際 RES 寬高。是否持續錄影要以檔案結果核對，不能只憑錄影指示判定。
