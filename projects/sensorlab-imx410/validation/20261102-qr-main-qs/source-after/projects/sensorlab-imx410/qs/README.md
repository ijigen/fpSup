# SensorLab-IMX410 QS：DC、RES、FPS、RECIPE、FORMAT、MB/s、QR

## v0.7.16test：LOCK 舊容器相容顯示（2026-11-02，離線候選）

只更新 SensorLab。DC／RES 的比例欄小字回呼提供鎖定狀態的 `LOCK` 文字、解鎖時空字串。QSContainer v0.3.2–0.3.4 使用這份文字；已有 v0.3.5 時，由容器換成小字列原生鎖頭圖示。`RATIO` 標題及大字比例沿用。先前 v0.7.14／15 留空小字並假設容器支援新圖示值，造成舊 QS 靜默漏掉 LOCK；現在有基本文字後備，無須為此更新 QS。

QS API 6、設定格式及 v0.7.15 的錄影／回放程式不變；不新增 QS 版本、載入器相依或 observer。需要的仍是 SensorLab、既有 API 6 QSContainer 及原有共用載入／UI 資源。完整 SUP 關係、保存卡片快照與新舊版本離線對照見 [本輪核對](../validation/20261102-sensorlab-sup-audit/README.md)。實體 LCD 尚待使用者確認。

## v0.7.15test：14-bit 回放的 RAW 讀取格式（2026-11-02，離線候選）

原廠 `C01CDBE0` 把影像平面轉成 RAW 讀取設定時，只明列 8／10／12-bit；SensorLab 的 14-bit 平面會落入 12-bit 預設值。新掛鉤只對已核對、已準備且尺寸一致的選中 14-bit 片段，保留原廠讀取器支援的 14-bit 格式值。位於 `C01CE450` 的 Thumb ADD 以同一份既有 veneer／journal 機制掛接，所有路徑重做原 ADD；42 apply hooks 加 clock 共 43 claims。

四種尺寸 × 四種位深的原廠格式轉換、舊碼對照與負向守衛通過。實際 BIN 的預設／保存設定各自驗證 descriptor 就緒與未就緒載入，55 筆還原記錄全部核對；沒有新增 observer、SD 寫入或影格複製。QSContainer v0.3.5 與 v0.7.14 的比例介面沿用。

這證明離線格式轉換缺口已修正，**尚未證實實機 14-bit 花屏消失**。輸入 frame descriptor 是明列的測試資料，LCD／DMA／位元組順序仍需使用者上機確認。見 [驗證與交付紀錄](../validation/20261102-playback-raw14-fix/README.md)。

## v0.7.14test：比例欄標題與小字 LOCK（2026-11-02，離線候選）

DC／RES 的比例欄恢復 `RATIO` 標題，大字維持常見比例或電影倍率；掛鎖與 `LOCK` 改用小字列的原生 QS 圖示，解鎖時隱藏。配對 QSContainer v0.3.5，其他欄位不顯示掛鎖。API／設定格式、裁切與預覽公式、錄影及回放程式沿用 v0.7.13test。

14-bit 花屏（使用者回報 S16 2K、29.97、14b 1x1）尚未證實修復，本版不作該項宣稱。離線測試與交付雜湊見 [本輪紀錄](../validation/20261102-ratio-small-lock/README.md)。

## v0.7.13test：高速片段回放緩衝上限（2026-11-02，離線候選）

原廠回放描述表只有 300 格，RAW 緩衝卻持續配置到記憶體不足；小尺寸片段可在第 301 格寫出表外。新增一個原字核對的配置呼叫掛鉤，依描述表大小／步長限制為 300，沿用原廠結束與釋放流程。已驗證的選中片段若落入原廠無播放表的高速類別 11–13，播放時使用最高有效類別 10；DNG 的拍攝幀率與錄影設定保留，高速片可能以較慢節奏播放。41 apply hooks＋clock 共 42 claims，ABI 2／QS API 6 沿用。

24 份卡上實拍 DNG 標頭的單格／連續播放準備共 48 案例通過；含第 301 格越界對照、清理／重建、三個可執行錯誤反例。實際交付 BIN 與保存的 AutoRun／LOADER／QSContainer v0.3.4 離線載入，全部 54 筆還原記錄逐位元核對。只換 SensorLab BIN；交付包保留使用者 v0.7.12 卡片快照中的設定。相機回放、LCD／DMA／聲音及插卡凍結改善尚未實測，不能視為已修復。見 [本輪證據](../validation/20261102-playback-ring-fix/README.md)。

## v0.7.12test：高速預覽取自錄影影像（2026-11-02，離線候選）

使用者確認 v0.7.11 仍在錄影幾秒後卡住，停止錄影後恢復；12b 3×6、11b 3×6 都會，RES 顯示 320×196。QS 顯示的是有效尺寸，未修改的 S16／0.3K 實際錄影矩陣為 336×206。這兩種配方在離線重建中都走獨立預覽分支；使用者另提的 2×6 尚未在同組目錄重建，不算已驗。

共用幾何公式新增預設關閉的「優先錄影取樣點」選項，SensorLab 僅在既有高速引擎條件成立時開啟。當來源寬高及完整視野都符合原有上限時，預覽與錄影共用取樣；其他情況仍用原有選路。沒有按尺寸／配方硬編例外，也不改感光元件時序、錄影尺寸、DNG 比例或既有顯示比例公式。原廠選路執行、低速還原、邊界與負向反例通過；**尚未證實能修好實機卡住**。

只換 SensorLab BIN，QSContainer v0.3.4／AutoRun／LOADER 沿用。預設設定包需重選配置。詳見 [本輪證據](../validation/20261102-hirate-followup/README.md)。

## v0.7.11test：高速畫布欄位補齊（2026-11-02，實測仍卡住）

使用者後續回報「沒什麼變化，還是會卡住」，並確認停止錄影後 liveview 會恢復。欄位補齊未解決症狀；持續錄影檔是否完整仍未知。見 [後續回報](../validation/20261102-hirate-followup/USER_FEEDBACK.json)。

使用者回報約 200 fps／38 MB/s／S16／0.3K，開始錄影幾秒後 liveview 停住；是否仍持續錄影、確切 RECIPE 與數字尺寸尚未核對。補齊錄影畫布 +B0：依原廠 100／120 格率載體選擇高速值。原廠這兩個載體的 engine 是 50／60，因此不能用 engine >99 判斷此欄位。純幾何公式、感光元件時序、實際錄影格率與既有預覽比例不變，沒有新增 hook。

離線執行原廠畫布→設定→影像狀態→處理描述子的傳遞流程；舊版與錯用 engine 門檻的反例均被測試拒絕。這只能證實遺漏欄位已補齊，尚未證實能解除數秒後停住。回放延用 v0.7.10，實機回放也尚未驗收。只換 SensorLab BIN，QSContainer v0.3.4／AutoRun／LOADER 沿用；預設設定版需重選 SensorLab 設定。見 [本輪證據](../validation/20261102-hirate-preview/README.md)。


## v0.7.10test：選片誤拒修正（2026-11-02，離線候選）

使用者確認 v0.7.9 仍在「選到片段」時顯示「檔案內容不能檢視」。已以三份保存的實拍 DNG 重現：原廠 v11 使用的 TIFF parser 不保留 Compression(0x103)，v0.7.9 卻要求從該 parser 取得它，因此正常未壓縮片也被拒絕。舊測試的人工 tag helper 掩蓋了此差異。

v0.7.10 在 v11 已讀入的檔案緩衝中有限度檢查 IFD0，將 Compression 與本次 player／檔案描述物件／TIFF handle 綁定，再保留既有尺寸與位深檢查。壓縮、缺標記、截斷、重複或錯誤型別仍拒播。新增一個有原字核對的 BL hook；不複製影格、不改預覽公式。40 apply hooks＋clock 共 41 claims，AP ABI 2／QS API 6 沿用。

103 項離線測試通過；原廠選片資料複製、v11、TIFF parser、tag lookup、格率表與 prepare 均執行 ROM。相機解碼／DMA／LCD／聲音及先前黑屏仍未驗證；低於 23 fps 等原廠無格率項目的片段仍不能播放，本次不假造播放節奏。只換 SensorLab BIN，QSContainer v0.3.4、AutoRun／LOADER 沿用。詳見 [本輪證據](../validation/20261102-playback-entry/README.md)。

## v0.7.9test：自訂 CinemaDNG 回放候選（2026-11-02，僅離線驗證）

預設啟用自訂片段的回放畫布，尺寸／位元深度／DefaultScale 取自目前選中片段的讀取結果。保留解碼前檢查：要求選取物件、檔案識別與資料尺寸一致，僅接受未壓縮 8／10／12／14-bit CinemaDNG 與既有錄影幾何範圍。索引瀏覽快取不再能以相同裁切尺寸蓋掉選中片段；14-bit 沿用既有原廠 RAW14 平面碼。沒有新增 hook、全幅複製或個別尺寸補丁，v0.7.8 的預覽公式沿用。

原廠標頭／profile／canvas、準備入口、配置包裝與尺寸計算均已離線執行；相機的解碼、DMA、可用記憶體、播放流暢度及先前黑屏原因仍未驗證，**不能視為已修復所有格式回放**。壓縮 CinemaDNG 仍拒播，HUD／Playback 頁面的實驗改動保持關閉。只換 SensorLab BIN，QSContainer v0.3.4、AutoRun／LOADER 沿用；本包為預設設定版。詳見 [本輪驗證](../validation/20261102-playback-checked/README.md)。

## v0.7.8test：RES 單軸調整預覽（2026-11-02，離線候選）

所有 DC／RES 共用 `apc_display(record_width, record_height)`：預覽依 ISP 實際輸出比例，RES 解鎖後單獨降低 Height 會垂直壓縮；降低 Width 會水平壓縮。沿用現有共用畫框公式與即時更新路徑，沒有個別尺寸條件或新 hook。物理感光區比例仍供 DNG DefaultScale 使用，錄影資料與播放行為沿用。

63 項離線測試通過；216 組配方逐位元組比對，僅六個預覽欄位可不同。舊版反例重現問題；LCD 尚未驗收。只換 SensorLab BIN，QSContainer v0.3.4、AutoRun／LOADER 沿用。預設設定版需重選 SensorLab 設定。見 [本輪紀錄](../validation/20261102-res-output-aspect/REPORT.json)。

## 2026-11-02：LOCK 偏右修正候選只更新 QSContainer v0.3.4

使用者截圖 SS__2900.JPG 確認 v0.3.3 圖示偏到格子右側並裁切。改用獨立原生圖片元件，明定水平座標；SensorLab v0.7.7test 與已確認的 liveview 修正均沿用。只換 QSContainer v0.3.4 BIN。這是離線修正候選，LCD尚未驗收，見 [本輪紀錄](../validation/20261102-lock-position/REPORT.json)。下方 v0.3.3 套件保留為歷史證據，不作為最新候選。


## v0.7.7test ＋ QSContainer v0.3.3：比例大字／QS LOCK（2026-11-01，離線候選）

DC／RES 的 RATIO 格改為大字比例，上方沿用原生 `menu_lock_qs`；解鎖時圖示消失。常用比例採 `3:2`、`4:3`、`16:9` 等；其餘兩位小數加 `X`。顯示比對容許 0.25% 尺寸對齊差，尺寸／鎖定計算不變。套件需同時換兩個 BIN，AutoRun／LOADER 沿用；預設設定包需重選設定與 QS 配置。

57 項 QS／ARM 回歸與 8 項設定遷移通過，原生圖示幾何與字型寬度通過；未操作相機，LCD 待使用者確認。驗證與檔案見 [本輪紀錄](../validation/20261101-ratio-ui/REPORT.json)。


## v0.7.6test：QS 內調整預覽比例（2026-11-01，使用者已確認修正成功）

依「退出 QS 後似乎正常」的回報，補上 YUV fallback，讓每幀使用最新裁切 slot 的比例；不新增 QS 關閉／重開或裁切切換。RGB／QS／MENU 分支、原有近16:9規則和設定格式維持原規則。

103 項離線測試通過，含 QS 調整回呼連續提交、播放保護和設定遷移；321 個裁切×2格率×5明示狀態，共9630次原生fit通過。交付時僅有離線證據；後續使用者回報「很好成功修正問題」，已確認該預覽問題修正。這不代表錄影或全格式驗收。見 [使用者後續回報](../validation/20261101-ratio-ui/USER_FEEDBACK.json)。39 hooks＋clock＝40 claims。預設 BIN 183304 bytes，SHA256 `1de06ee3728df24b53dd3aba01f1ddad2e9680175a87385175a4f851fff9812f`；只更換 SensorLab BIN，AutoRun／LOADER／QSContainer 沿用。見[修正與驗證](../validation/20261101-qs-live-update/README.md)。

## v0.7.5test：退出 QS 後正常，QS 內即時更新待修（2026-11-01）

新增H_YUV32 @ C0306E70，修正另一條YUV路徑仍固定使用3:2的漏網情況；非16:9取本slot比例，16:9取原廠enum3，inactive與播放維持原生。RGB／W v4維持v0.7.4的隔離。38 hooks＋clock＝39 claims；只換SensorLab BIN。

98項離線測試與321裁切×2格率×兩條分支的3852個fit案例通過。原版失敗對照及播放保護反例有效；**使用者先回報與v0.7.2無顯著差異，後續確認退出QS後似乎正常；目前要求在QS調整時也即時更新，尚未完整驗收**。詳見[後續紀錄](../validation/20261101-v075-followup/USER_FEEDBACK.json)。預設設定BIN 183192 bytes，SHA256 `150791537485c2e6fa79e044ecf3420907d9c59870c1535fce6554decb03dc4a`。見[修正與驗證](../validation/20261101-yuv-32-branch/README.md)。

## v0.7.4test：QS／MENU正常，liveview拉寬未解（2026-11-01使用者LCD回報）

v0.7.3已被使用者實機回報否決：自訂裁切後連QS／menu都變形。已重現原因並移除誤套到RGB bitmap／W v4的H_ASP3；保留YUV的比例與精確指標fit。37 hooks＋clock＝38 claims，API／設定格式不變。

74項apply／顯示、12項QS保存／套用、8項設定遷移通過；321裁切×2格率的642選擇，每組YUV與兩種RGB原生fit均通過。這是離線結果。使用者已實體LCD確認：QS／MENU恢復正常，liveview仍和v0.7.2一樣拉寬，整體驗收未通過。新預設BIN183088 bytes、SHA256 `7f1de25f256cb727c57238d73c6a7082d03cbf1b387299d74231a101a77445fb`，不帶目前卡上設定，只換SensorLab BIN。
補測原生W v2分支後，找到舊fixture漏掉的3:2路徑：該路徑仍輸出滿版。這是離線反例，尚未證明使用者現場正走此路徑；當時尚未有新測試版；後續候選為上方的v0.7.5test。見[後續狀態](../validation/20261101-v074-followup/REPORT.json)。

詳見[原因、反例、修正與驗證界線](../validation/20261101-ui-layer-scope/README.md)。原v0.7.3失敗證據保留，勿繼續使用；已請使用者回復原BIN，但回復尚未確認。

## v0.7.3test 歷史紀錄（2026-11-01實體LCD回歸否決，停用）

原始碼已改為 v0.7.3test；本輪經授權部署與待機取證後，因畫面驗收未完成而回復 v0.7.2test。候選處理自訂 live view 的比例吸附：
W71C1 v4 改用本 slot 的比例；原生 fit 分類後只還原本 slot 自有指標的比例，再繼續原廠整數畫框。
原廠／inactive／播放保持原路徑。兩個新增 hook 已宣告 claim，合計 38 hooks＋clock＝39（LOAD.LOG `00000027`）；AP ABI 2／QS API 6 不變。

| 候選 BIN | bytes | SHA-256 |
|---|---|---|
| [預設設定](../validation/20261030-lv-aspect-fix/default-build/fpSup/SensorLab-IMX410_v0.7.3test.BIN) | 183120 | `766dd87c3c2c97bdd0276ff027fad21593d5bf7ec9833f7e29dc5d4049a5155a` |
| [保留 live3 15:44 讀回設定](../validation/20261030-lv-aspect-fix/settings-build/fpSup/SensorLab-IMX410_v0.7.3test.BIN) | 183120 | `b22078395d32a7cb5adffd8d7441d4682249002e677d1cb827a98647b3c8e954` |
| [本輪新鮮讀回設定，實際上機候選](../validation/20261030-lv-aspect-fix/live/build/fpSup/SensorLab-IMX410_v0.7.3test.BIN) | 183120 | `811b4473830ff316c7205f455f0e44edc35f814d53d96c7a29d6503818fe50f0` |

三者只差260-byte記錄；15:44版本未用於本輪部署，實際上機版保留剛讀回卡檔的原始設定。`sq_test_off=31621`（0x7B85）；工具必須讀對應 build JSON。
不用改 loader／AutoRun／QSContainer。測試與限制見 [APPLY_DESIGN §15](../notes/APPLY_DESIGN.md)。
離線驗證已完成：快速回歸72項＋core PASS；prelive 的非設定測試、core及285組突變工作全部通過（其中lv-fit一組含5個變體）。
原prelive有6項設定測試因缺少新版固定樣本而error；按既有規則新增v0.7.3樣本後，[設定遷移8項重跑PASS](../validation/20261030-lv-aspect-fix/settings-migration/report.json)，沒有改測試斷言或產品程式。
另補跑啟動prelive後才加入的外層顯示4項PASS、上機清單主機測試9項PASS。原prelive保留1項既有skip（`PageStrip.test_menu_key_switches_at_the_sub_ids`）。
完整原始報告未改寫，彙整見 [verification.json](../validation/20261030-lv-aspect-fix/verification.json)。

**本輪待機結果：未驗收。** 初始化與高度3800／3500、寬5088／5008／4800全部套用成功，無凍結、拒絕或錄影／回放；但截圖高度出現643／592列回捲，寬度畫面從x0開始、右側全黑。有效尺寸接近預期，不能因此斷言實體LCD已正確置中，也不能只憑截圖判LCD本身必然損壞。下一步追最終顯示與capture來源尺寸／stride。已回復測試前v0.7.2與原設定；四個完整卡檔及63個設定字全部相同，CINE待機active0。詳見[上機紀錄](../validation/20261030-lv-aspect-fix/live/LOG.md)及[回復驗證](../validation/20261030-lv-aspect-fix/live/final-verification.json)。

**後續離線已找到原生SS尺寸不一致。** 真按鍵／事件路徑8項、fit→直接packet producer3項、writeback1項（11組宣告尺寸）均通過獨立重跑：SS配置／JPEG固定1024×682，寫回卻另取當前display W/H與stride。這不是本輪getter實測或像素DMA重現；使用者目前無法看相機，LCD仍未確認。產品與相機未再改動，詳見[離線追查彙整](../validation/20261030-lv-aspect-fix/offline-capture/README.md)。

**2026-11-01 範圍回歸補充**：使用者確認問題發生於「SensorLab 選單自訂裁切後直接套用」。現有候選通過寬5088–6048／高3520–4040共321個裁切、兩組格率（642個apply選擇）的真ARM離線比例回歸，另20項顯示回歸通過；移除fit hook的反例會重新拉滿。固定2K 11b 3x2配方與3:2顯示fixture，未執行選單事件或LCD。重建預設BIN與上述`766dd87c…`相同，沒有新增產品程式修正或部署。本次主機USB清單沒有相機，實體LCD仍未驗收。詳見[範圍、限制與完整證據](../validation/20261101-crop-bands/README.md)。

## 目前基線：v0.7.2test ＋ QSContainer v0.3.2（2026-10-30，live3 已部署）

已接受的功能實測見 [live3 紀錄](../validation/2026-10-30-v1-live3/LOG.md)：AEL、`1000.0`、RATIO 與 HD 2K 11b 3x2 錄影通過；
回放第15項未做，第16項只做shell reboot，實體電源開關尚未驗。本輪候選回退後，已重新讀取確認v0.7.2／v0.3.2、CINE待機、apply active0。
卡上 BIN 含使用者設定，和下表的空白設定建置不同；部署時整檔讀回相符的證據在 live3 的 `build/`、`readback/`。

| BIN | bytes | sha256 |
|---|---|---|
| `out/fpSup/SensorLab-IMX410_v0.7.2test.BIN`（`out/build-0.7.2test.json`，sq_test_off 31483 = 0x7AFB） | 182 944 | `af2a7271eb48a6c5d5db0ea413a122d732bc1e455242581f5ee7a31c63e03fe7` |
| `../../qs-container/out/fpSup/QSContainer_v0.3.2.BIN`（`build-0.3.2.json`，API 6 不變） | 176 736 | `a73c9fcd6d7ca8c122a085cd77251e59209778442427e0930a2ebacbdcaff512` |

都是空白設定記錄的預設建置；部署時照舊用卡上當下的 BIN 做 `--settings-from` 重建。hook 數不變（LOAD.LOG 仍寫 `00000025`）。
修 live2（`../validation/2026-10-30-v1-live2/LOG.md`）的問題：
1. **錄 gated 配方就凍結（第 14 項，HD 2K 11b 3x2）**：v0.7.1test 的 TAB3 picker 依 `busy()` 回答——待機給原廠路線、錄影給我們的，
   所以開錄那一刻讀出在沒有 LV 停／啟的情況下被換掉（RES-Custom 的 picker 從不看 busy()）。現在：
   - picker 的 TAB3 答案**不看 busy()**，待機、錄影、停錄後都是同一個 entry；
   - 路線閘門 `rok` 拿掉可見高 1334 的上限（那是原廠待機 profile 的 2016×1344 視窗，不是凍結規則）；只留 R12 來源 ≤ 1710 列、
     光柵 ≤ 來源、可見寬 ≤ 2000。證據：isp-lab 10-28 p5 跑過整族 HD 3x2（可見 1671–1686、來源 1702），待機＋錄影 6/6 通過
     （`20261028-p5-FHD60_Cdae66428` 就是 HD 2K 11b 3x2）；
   - 真的不過閘門（或 `standby=0`）→ 提交拒絕 `AP_E_STANDBY`（−11），整台留在原廠，`gated` 改計拒絕次數；
   - 掃過全部預設 DC×RES 的每個配方：都過閘門（`RouteSweepTests`），所以 QS 不必反灰。詳見 `../notes/APPLY_DESIGN.md` §14。
2. **FPS 清單倒數第二列顯示「關閉」**：列文字 `1000` 被原生清單當成 .nloc 字串 id（id 1000 = Off／關閉）。四位純數字的列文字改送 `1000.0`。
3. **FINE 每轉一格就套用**：沒改。預覽 `dcres.html` 的 FINE 每格就改 `S.fps`（跟其他轉盤一樣），APPLY_DESIGN §12.1（Bei：修改事件套用）
   也是每格提交；v0.7.0test 段落與舊清單寫的「離開時 +1」才是不一致的那邊。清單預期已改，**待 Bei 確認**。
4. **記錄設定的 FPS 摘要是 `30.001`**：沒改。MENU_DESIGN §2「摘要 = QS FPS 格的大字（細調中或不在清單上寫三位小數）」就是 `30.001`；
   `CUSTOM 30.001` 是清單那一列的字。舊清單第 7 項寫錯，已改。
5. **開機後 AEL 要等焦點經過 K 格才有效**（容器 v0.3.2）：AEL 物件的可見性由 `QS_AELbtn` 控制，只有原廠格的 holder 會寫它；
   我們的格子現在依「AEL 有沒有作用」寫 1／0。字串位址 `0xC2DAAD34` 未上機驗（備用同名字串 `0xC18DEDE8`）。
   **RATIO 格的鎖圖蓋住比例字**（容器 v0.3.2，live4 #15）：96 px 的鎖圖從值行頂畫到約 y185，蓋住小字列（150–190）。有鎖圖又有小字時，小字改放標題行，
   小字列留空：RATIO 格變成上面 `1.778 : 1`、中間鎖圖（`RATIO` 標題字不再出現）；只用原廠圖。`test_slqs` 的預覽比對照這條規則對應。
6. 工具：`rec_take.sh` 停錄後等 12 s；`sl.py`／`tools/live/dc_probe.py` 從 `build-<版本>.json` 讀 sq_test 位移；
   13:59 的 fpshd 換 PID 其實是 13:31 `ui_drive.py reboot` 的 `pkill` 重啟，現在重啟都會寫 `~/Library/Logs/fpshd-restarts.log`。
7. `tools/live/dc_probe.py`：讀 sq_test 17／18、`0xC343B590`、lk_reg 的 REG 列（0x0003、vstart、vsize），一行 JSON。

**清單的變動（v0.7.2test 上機時用）**：第 0 項部署 v0.7.2test ＋ 容器 v0.3.2（刪 v0.7.1test、v0.3.1）；第 1 項兩行都 `0A`，SensorLab 仍 `00000025`；
第 4 項 `~1000` 那列顯示 `1000.0`（反灰），不再是「關閉」；第 7、9 項見下表的新預期；第 14 項見下表；DC／RES 子 QS 的 RATIO 格：上面比例字、中間鎖圖，不重疊。

### 已知上機問題總表（qs-container live1–7、apply1、SensorLab v1-live 至 live3、menu-diag；2026-10-30 整理）

已修、實機確認過的（不再列細節）：轉盤改到上一格、子 QS 回來原廠格沒值、空反白框、子 QS 按 MENU 凍結、RECIPE 標題蓋 DC 圖示、`•`→`?`、
原廠「AEL 白平衡」提示、換 BIN 丟格子記錄、MB/s 選項超框、QR 畫在 back buffer／殘影、選單選解析度凍結、首個 MENU 2.3 s 空窗。

| # | 來源 | 問題 | 狀態 |
|---|---|---|---|
| 1 | v1-live2 #14 | 錄 gated 配方（HD 2K 11b 3x2）凍結 | **已修，live3 #14 PASS**（v0.7.2test，30.018p；錄後 mode 231、DNG 2016×1134／12-bit；錄影中未讀 USB） |
| 2 | v1-live2 #4 | FPS 清單 `1000` 顯示「關閉」 | **已修，live3 (b) PASS**（v0.7.2test） |
| 3 | QC live4 #8／live5 #7、v1-live2 #7 #9 | 開機後 AEL 要等焦點經過 K 格 | **已修，live3 (a) PASS**（容器 v0.3.2） |
| 4 | QC live4 #15 | RATIO 格的鑰匙／鎖頭圖蓋住比例字 | **已修，live3 (c) PASS**（容器 v0.3.2） |
| 5 | v1-live2 工具 | `rec_take.sh` 停錄 5 s 就 ping；fpshd 重啟無紀錄 | **已修**（12 s；重啟寫 log） |
| 6 | v1-live2 #7 #9 | FINE 每轉一格就套用 | **暫緩**：預覽與 §12.1（修改事件套用）都是每格；要 Bei 定 |
| 7 | v1-live2 #4 #7 | FPS 摘要 `30.001` 而非 `CUSTOM 30.001` | **暫緩**：MENU_DESIGN §2 規定摘要 = QS 大字；要 Bei 定 |
| 8 | v1-live2 #13 | RES 6K 實際 6032×4030，清單寫 6048×4040 | **暫緩**：DC 高度調查（`tools/live/dc_probe.py` 已備），要上機量 |
| 9 | v1-live2 #14 | HD 2K 配方清單沒有 `12b 3x2` | **暫緩**：可能是 2 % 寬容或格率篩掉，需對 core 查；不影響安全 |
| 10 | v1-live2 #7 | RES 清單最後一列 CUSTOM 被切在畫面底 | **暫緩**：要改原生 popup 視窗高度／捲動（MENU_DESIGN 一頁幾格），外觀問題 |
| 11 | v1-live2 #6 | DC 清單列文字底線稍擠 | **暫緩**：外觀，69 px 間距是為了七列不捲動 |
| 12 | QC live6 #7、v1-live2 #11 | 6K 的 LL 小字顯示 `LL ?`（`—` 字型沒有） | **暫緩**：換成字表內的字元即可，下一版 |
| 13 | QC live5 #4、live6 #4、live7 §2 | 編輯器裡 RECIPE／MB/s／QR 借 DC 圖示 | **暫緩**：只用原廠資源，沒有更合適的圖 |
| 14 | QC live5 #10 | 只有一個選項時仍畫 ◀▶ | **暫緩**：未再驗，低風險外觀 |
| 15 | QC live5 #15 | ISP bin 的 STD 核心轉不到 | **暫緩**：等 Bei 決定（「離線證明不了的」#4） |
| 16 | QC live5 #17 | 非原廠格率小字多一個前導點 `· 16 recipes` | **暫緩**：未再驗 |
| 17 | QC live3 #10、live4 #9 | RES +1 得 2016×1132／RES 顯示可見尺寸 vs raster | **暫緩**：疑似可見 vs raster 兩種數字，未寫明，下輪截圖對照 |
| 18 | QC apply1 | 回原廠沒還原使用者原本的 24 fps | **暫緩**：載體格率覆寫原廠設定的設計後果，要 Bei 定要不要記原值 |
| 19 | menu-diag #5 | `sq_test(22)` 撐不過下一次 MENU | **暫緩**：已知操作注意事項（改用 `sq_test 30`） |
| 20 | QC live §Q4 | 耳機音量 hook 從沒被走到 | **暫緩**：無影響、未再測 |
| 21 | v1-live2 工具 | QS 裡第一次 CAPTURE 逾時 | **暫緩**：疑似傳輸，非 sup |
| 22 | v1-live2 #13 | 6K 14-bit 左右邊緣 8 個孤立像素 | **暫緩**：像壞點，要原廠 6K 對照 |
| 23 | v1-live3 DC 高度／寬度 | 感測器有裁切，部分比例的 LV 仍拉伸；QS 開／關的切框斷點不同 | **未解；v0.7.3待機未驗收，已回退**：有效尺寸隨crop，但截圖回捲／偏移；實際LCD未獨立確認。需追capture與最終composition，不能以fit測試宣告已修 |
| 24 | v1-live3 異常 | 關 QS 約 1.5 s 的 LV 截圖出現假色與資訊列，等 8 s 後正常 | **未釐清**：`pic_false_color_on=0`，僅保留觀察，未證明來源 |
| 25 | v1-live3 異常 | DC 子 QS 用 QS 鍵關掉再開，主 QS 焦點不固定 | **未修**：需比對容器焦點與原生 QS 路徑 |

第 23 項的 DC 調查使用 2K，不能當成第 8 項 6K 尺寸差已解決。回放安全與實體暖開機仍是未完成驗收。

第 23 項離線追查：原生 `C0306DF8 → C02F43A8 → C02F4410` 的 fit 會先依 `round(9×比例)==16` 吸附至 16:9，
否則依 `round(2×比例)==3` 吸附至 3:2（`out/decomp/full/blk_c02.c` 的 `FUN_c02f4410`）。
v0.7.3 的真 ARM 回歸已覆蓋這層。注意應用公式產生的 slot 比例不等於 DC 寬高比：同 live3 的11-bit 3x2／30.018p，
寬5040是840:671、5008是1117:893（兩者略大於1.25，仍吸附成3:2），4800是800:671（脫離吸附區）。
8:5 修復契約先在舊產品失敗（滿框1620×1080），候選輸出1620×1012。直接 fit、v4 classifier與兩條串流分派都跑原生程式；
metadata／UI條件為明示fixture，仍須實機驗收LCD，不能把模擬當成已看到新畫面。

### v0.7.1test（前一版）


| BIN | bytes | sha256 |
|---|---|---|
| `out/fpSup/SensorLab-IMX410_v0.7.1test.BIN`（`out/build-0.7.1test.json`） | 182 892 | `c9a4e8bd2b5e858df4ac9533543502c2da56f66b3d8d2e38a59997f85408dd35` |

容器不變（v0.3.1）。v0.7.1test 修兩個 v1 上機問題（`../validation/2026-10-30-v1-live/LOG.md`）：
- **選單選解析度就凍結**：清單 popup 的變數事件（`slm_changed`）裡原本同步 commit（LV 停／啟、carrier setter）、`ap_idle`、
  再重寫 SLM_RES／SLM_FPS 兩個 modelCSV。modelCSV 的 notify（`C05D83A8` type 1）會同步重建所有綁定的清單（`C05CE8A0` 刪掉再重建 item），
  也就是正在執行 commit 動作序列的那個 popup。現在事件裡**只記錄選擇**（`menu.owed`，附加在 `struct slm_state` 尾端）、
  排隊送三個摘要字串（`C0593FE0` 只是入佇列）；push／commit／`ap_idle`／重建模型都留到下一次 leave()。
  同一次選單裡第二個選擇若在舊清單、現在已不提供（例如換 DC 後的 RES 列），拒絕（`rejected` +1）。
  `SLM_Refresh`（格式變更）事件也不再重寫模型，只送鎖定與值。
- **自訂 DC 寬度在待機被擠壓而不是裁切**：公式的預覽可見高常是 1335（比原廠待機上限 1334 多一列，OG 寬度每隔一個 16 px 步），
  閘門因此把待機送回原廠路線，而 LV 框與比例 hook 仍套我們的形狀 → 原廠畫面被擠進新比例。現在：
  1. 待機用的可見／光柵若只超過上限 ≤ 8，切到上限（`sv`／`sr`，錄影仍用公式原值）→ 閘門通過，待機跑我們的讀出；
  2. 閘門真的擋下時（`lv_stock`），LV 框、比例 hook 維持原廠，不再擠壓。

### 前一版：v0.7.0test

| BIN | bytes | sha256 |
|---|---|---|
| `out/fpSup/SensorLab-IMX410_v0.7.0test.BIN`（`out/build-0.7.0test.json`） | 181 916 | `ce1f9704cfc9db00f7c7cce6a6eba2dbfcb243da385867851011990ba6cdce8a` |
| `../../qs-container/out/fpSup/QSContainer_v0.3.1.BIN`（`build-0.3.1.json`） | 176 608 | `59bdd1361d973707d313cd77f8eea98264a9cc1ba3ae62cc3c9aafa03436752d` |

兩個都是**空白設定記錄**的預設建置（可重現：重建 sha 相同）。部署時要用卡上**當下**的舊 BIN 做 `--settings-from`（兩個 builder 都有，README-settings-migration.txt），重新產生後再上卡。
SensorLab v0.7.0test **需要容器 v0.3.1（API 6）**：舊容器不收 FPS（sub-item 的 blur 欄位非 0 就拒絕該功能），選單的 FPS CUSTOM 也會被拒。
發布組合：`QSContainer_v0.3.1.BIN`、`SensorLab-IMX410_v0.7.0test.BIN`。**不含 `SLTP.BIN`**（回放自動測試實驗，已退出發布組合；卡上若有要刪）。

改了什麼：
- **FPS 子 QS（Bei 10-30 A，QS_DC_RES_SPEC「FPS 改用子 QS」）**：
  - FPS 按 AEL 開子 QS（FPS、FINE）。FINE 就是舊的細調轉輪：前轉盤 VMAX ±1，後轉盤 ±10，配方上限點有標記。
  - 第一次轉 FINE 就丟掉舊的細調值。焦點離開 FINE（移焦點、AEL 返回、關 QS）時，新的細調值插進清單（黃色），並且套用。
  - 選單的 FPS CUSTOM 開 FPS 子 QS，焦點停在 FINE。FPS 在 8 格裡、或不在（獨立子 QS）都一樣。
  - 容器 API 6 的兩個新介面：`qsc_sub.blur()`（焦點離開時呼叫）和 `QSC_OPEN_SUB_AT(k)`。
- **回放 v1 = 只做原廠回放**（`../notes/PLAYBACK_DESIGN.md` §15）：
  - 原廠 profile 讀不了的片子（所有自訂尺寸、14-bit），在 `FUN_c05be080` 之前就被拒絕。
  - 原廠片配上 live 的非 16:9 配方時，回放的 LCD 形狀維持原廠（修掉 10-30 review 的缺陷）。
  - 不改畫布、不註冊 HUD 數字、不套 Playback 頁。v2 的機制還在，用 `sq_test 24` 打開。
- **首個 MENU**（live 診斷 2026-10-30-menu-diag 已判定「卡住」未證實；這裡只做量測工具）：
  - 私有選單初始化不再把兩個原生 modelCSV 各寫兩次。
  - `sq_test 29` → 16 字（µs，韌體 tick）：
    - 0–4：首次 leave 的總計、push（含 commit）、ap_idle、選單、寫記錄；
    - 5–7：最大、最近、次數；
    - 8–11：首次 leave 的起點／終點、push 的起點／終點，都是絕對 tick；
    - 12–14：選單初始化的 `fpui_stock_apply`、兩個 `slm_model`、整個初始化；
    - 15：暫停期間略過的 push 次數。
  - `sq_test 31` → 容器的 12 字（API 6 `qsc_api.timing`）：
    - 首次 layout 的進入點、收集開始／結束、leave 開始／結束、原廠 loader 結束（絕對 tick）；
    - 寫回耗時（µs）；
    - 次數、最大、最近、首次總計、寫回次數。
    - 兩邊用同一個 tick，可以直接對齊。
  - **`sq_test 30`**：1 = 立刻回原廠，而且之後不再 push（leave、轉盤、選單都不 push），直到送 0 才恢復，0 會立刻重新套用。可以撐過 leave()，但重開機就沒了。用來把 apply 跟選單／容器拆開來看。`sq_test 22` 會被下一次 leave 推翻，做不到這件事。
  - 離線指令數：`../tools/first_menu_icount.py`。tick 換成「已執行指令數」，所以上面的 timing 字直接變成各階段的指令數；原生服務是 stub，沒算進去：

    | 階段 | 指令 | 約（0.3–0.6 G 指令/s，估計） |
    |---|---|---|
    | 首次 layout（容器 hook 全部） | 20.2 M | 34–67 ms |
    | 容器收集 `qc_freeze` | 3.0 M | 5–10 ms |
    | SensorLab leave() | 17.2 M | 29–57 ms |
    | 開機還原 push | 3.2 M | 5–11 ms |
    | 選單初始化（`slm_idle`） | 14.0 M | 23–47 ms |
    | 其中 `fpui_stock_apply` | 13.1 M | 22–44 ms |
    | 其中兩個 `slm_model` | 0.09 M | < 1 ms |
    | 之後每次 layout | 0.94 M | 2–3 ms |

    我們的程式碼解釋不了秒級的延遲，跟 live 診斷量到的一致：按鍵 0.20 s、commit 15.7 ms、離開選單時約 2 s 的 GUI／LV 重建。
  - 分析見 `../notes/MENU_DESIGN.md`「首個 MENU 回覆逾時」。
- 位移：`sq_test` 在 `block + sq_test_off`（Thumb）。**`sq_test_off` 每版都會變，一律從 `out/build-<版本>.json` 讀，不要寫死**（v0.7.0test 是 0x79DF、v0.7.1test 是 0x7B61；`tools/live/dc_probe.py` 與 live2 的 `sl.py` 都照 LOAD.LOG 的版本自動讀）；state_off 181 952；rec_off 181 636。claim 數：36 個 hook + 時脈閘 = 37，LOAD.LOG 會寫 `00000025`（v0.6 是 0x23）。

離線測試結果記在本次的報告：測試數、突變與指令。實機上什麼都還沒驗。

### v1 上機清單（v0.7.0test ＋ 容器 v0.3.1）

上機前：通知 Bei 並等他回覆，再廣播所有 peer；錄影中、回放中都不碰 USB，停錄後等 10 秒；用完廣播 released。
每一項都要截圖或讀值，對照「預期」；不符合就停在那一步，先讀卡、做紀錄。

| # | 項目 | 做法 | 預期 |
|---|---|---|---|
| 0 | 部署 | 備份 `\fpSup\`、LOAD.LOG，以及卡上的 SensorLab／容器 BIN。用這兩個 BIN 做 `--settings-from` 重建，部署後讀回比 sha。刪掉 SLTP.BIN、舊版 SensorLab（v0.5.x／v0.6.0）與舊容器（v0.2.4／v0.3.0）；卡上不能有 RES-Custom | 卡上只有 v0.3.1 和 v0.7.0test 各一份，sha 等於重建結果 |
| 1 | 開機 | `ui_drive.py reboot`，接著讀 LOAD.LOG | `QSContainer_v0.3.1` 與 `SensorLab-IMX410_v0.7.0test` 都是 `0A`（loaded），SensorLab 那行是 `00000025`，沒有 SLTP；`ping` 正常；`sq_test 21` = 0 |
| 2 | 首個 MENU | `../tools/live/pingloop.py --key MENU --out …`：每 100 ms 一次 ping，按鍵只送一次；**單獨一次按鍵逾時不算卡住**。接著讀 `sq_test 29`（16 字）、`sq_test 31`（12 字）、`sq_test 27`、`sq_test 17`。截圖用 `../tools/live/ui_shot.sh N`，N 是下一個編號，**不要靠 `dir` 找** | 選單正常出現（MainB1），ping 中斷後會恢復。29：`lt[7]=1`，記下 0–4 與 12–14。31：首次 layout 的總計。27：ready 1、result 0。17：result 0、active 1。若要把 apply 拆開：重開機後先 `sq_test(30,1)` 再按 MENU，比較兩次的總計 |
| 3 | 選單：解析度 | 記錄設定 → 解析度；選一個（OK）後先 `sq_test 27`、`sq_test 17`，再按 MENU 離開選單後再讀一次 | 這個 DC 的 K 清單（1K…6K，由小到大）＋ CUSTOM；**v0.7.1test：OK 後 shell 照常回應**，列的摘要立刻變；27 的 picks +1、`owed`（+7484）= 1，17 的 commits **不變**；離開選單（leave）後 commits +1、owed 0、QS 的 RES 跟著變 |
| 4 | 選單：每秒幀數 | 每秒幀數 | 常用格率到 1000，達不到的反灰；細調過時多一列 `CUSTOM xx.xxx`；選一個 → QS FPS 相同 |
| 5 | 選單：位元深度 | 位元深度 | 8 bit、10 bit 反灰；RAW 可選 |
| 6 | 選單：DC | DC 裁剪 | OG、HD、S35、APS-C、S16、SQ ＋ CUSTOM；選了 → RES 照規則重算 |
| 7 | CUSTOM 跳轉 | DC CUSTOM、RES CUSTOM、FPS CUSTOM 各一次，每次返回後再從選單進 | 選單關閉、QS 打開對應的子 QS：DC／RES 焦點在第 1 格；**FPS 焦點在 FINE（第 2 格），下方是 `◀ 59.940 ▶`**；轉一格會變，**每轉一格就套用**（commits 每格 +1，v0.7.2test 預期，待 Bei 確認）；**第一下 AEL 就回到 FPS 格**（容器 v0.3.2），清單裡多一個黃色的細調值；再進選單，FPS 列**摘要**是 `59.9xx`（三位小數，MENU_DESIGN §2），清單那一列是 `CUSTOM 59.9xx`；不會重複跳 |
| 8 | QS 取代模式 | 編輯器把 CINE 8 格設回原廠（21 12 23 25 …），先 `mem get 0xC31B0ABC,,32`，再開 QS | FORMAT、DC、RES、FPS 四格顯示 SensorLab 的值；離開 QS 後 `mem get` 跟開 QS 前相同；編輯器清單裡沒有這四個重複列，RECIPE、MB/s、QR 還在 |
| 9 | QS 的 FPS 子 QS | **開機後第一次開 QS、焦點直接在 FPS** 按 AEL（v0.3.2：第一下就要開）；FINE 前轉盤一格、後轉盤一格；分別用移焦點、AEL、關 QS 離開 | 子 QS 是 FPS、FINE；前轉盤 ±1 VMAX，後轉盤 ±10；到配方上限有細虛線；三種離開方式都會把細調值插進清單（只留一個、黃色）；套用在轉的當下（每格 commits +1），離開時不再 +1（AP_IDLE） |
| 10 | QR | 把 QR 放進一格，AEL | QR 畫在格子裡（37×37，白底）；手機掃出 `https://ijigen.github.io/fpSup/sensor_lab_imx410/#` 後面 37 個字元，跟 `sq_test 13` 相同；網頁還沒發布，所以會 404（這是預期）；再按 AEL 或移焦點就隱藏 |
| 11 | MB/s | 看 MB/s 格，切幾種配方 | 大字是未壓縮 MB/s，小字是 `LL ~N`；顏色依媒體；數字符合 MBPS_TILE_RESEARCH 的公式（每個錄影配方都記下來） |
| 12 | 錄影 A：12-bit 容器 | DC OG，RECIPE 選 14b 1x3（例如 OG 2K），錄 3 秒 | FORMAT 顯示 12bit、ADC 顯示 14bit；`0xC343B590` = 230／231；DNG BitsPerSample 12，BlackLevel 是 12-bit 尺度（約 256），WhiteLevel 4095；DefaultCrop = RES 格的看到尺寸；彩色預覽正常（先扣黑階再乘白平衡） |
| 13 | 錄影 B：真 14 | OG 6K，RECIPE 14b 1x1，錄 3 秒 | FORMAT 14bit；DNG BitsPerSample 14，BlackLevel 約 1024，WhiteLevel 16383；raster 6064×4050，DefaultCrop 6048×4040；格率不超過約 19 |
| 14 | 錄影 C：HD 2K 3x2 | HD 2K，RECIPE 11b 3x2（live2 清單裡沒有 12b 3x2）。**v0.7.2test：先只看待機 30 s**（截圖、`dc_probe.py`），沒問題才錄 3 秒；`rec_take.sh` 停錄後等 12 s | **gated = 0**、standby_picks 增加（待機跑我們的讀出，可見 2000×1686；isp-lab p5 實證）；待機畫面無花屏、不凍結；錄影中與錄影後 `0xC343B590` 都是同一個 230／231；DNG 12-bit，尺寸 = 看到尺寸 +16／+10。若待機異常：`sq_test(22)` 回原廠、停，交 Bei |
| 15 | 回放安全 | 先 `sq_test(22)` 回原廠，錄一段原廠 UHD；再把配方恢復成非 16:9。全程不接 USB：進回放 → 原廠片（看、播、暫停）→ A／B／C 三段各瀏覽並按播放 → PLAY 退出。退出後才接 USB，讀 `sq_test 23` 那個位址 `+176×4` 起的 4 字 | 原廠片顯示、播放與 v0.5 相同，LCD 16:9 不變形。A／B／C：**只會黑畫面或出現錯誤圖示，不凍結，按鍵有反應，PLAY／S1 能退出**；block 1、refused > 0。按播放後如果卡住，就是 §15 的串流路徑未驗項目：停下來，交 Bei 決定 |
| 16 | 暖開機 | 拔掉 USB，撥電源開關關機再開機；之後再接 USB | LOAD.LOG 兩個都載入；QS 的選擇（DC／RES／FPS／RECIPE 與細調值）都還在；第一次 MENU 的情況同第 2 項（再讀一次 `sq_test 29`） |
| 17 | 收尾 | `sq_test(22)`，讀 apply 狀態；編輯器格子照 Bei 的意思保留或還原 | active 0；原廠 Format／Size／Framerate 與第 0 項記下的相同 |

## Testing（測試入口，2026-10-30）

全部離線，不碰相機。一個入口跑所有套件（SensorLab qs／apply／menu／site／core ＋ qs-container），每個工作一個行程平行跑：

此 Mac 的沙箱會讓 Unicorn 在初始化 `mem_map` 時收到 SIGILL；須用已核准的本機離線執行方式，不能將初始化崩潰記成產品測試失敗或通過。
接手基線 `fast-20261030-162631`：56 項單元測試與 core 比對全部通過（0 skip）；這次未重跑 prelive／full，也未操作相機。
同一 checkout 一次只跑一份 runner，避免 core／apply 的固定 host dylib 輸出互相覆寫。

```
cd projects/sensorlab-imx410
python3 -B tools/test.py fast              # 約 7 s：純主機測試＋幾步 unicorn 冒煙
python3 -B tools/test.py full              # 全部測試＋全部突變，約 16 min（10 核），PASS
python3 -B tools/test.py prelive           # 上機前：全部測試＋只跑「目標檔變過」的突變套件（目標 3–5 min）
python3 -B tools/test.py full --no-mutants # 全部測試，約 85 s
python3 -B tools/test.py mutants --only slqs,core   # 只跑某些套件的突變
python3 -B tools/test.py list full         # 看會跑哪些工作
python3 -B tools/test.py clean             # 清掉測試快取
```

兩層的分工（Bei 10-30 定）：**`full` 是發布閘門**（全部測試＋全部突變，約 19 min）；**`prelive` 是上機前用的**：全部單元測試平行跑，
加上只有「突變目標檔變過」的突變套件。每個突變套件對應它改的檔（`tools/test.py` 的 `MUT_TARGETS`：slqs → `slqs.c`／`build_slqs.py`／
`preview_runner.js`；apply → `ap.c`／`ap_calc.c`／`ap.h`；core → `core.c`／`core.h`；qsc、qsc-page → `qsct.c`；menu → `menu_lists.py`／`slm_page.py`；
再加各自的測試檔，突變清單改了也算）。`full` 全部通過（沒有 `--no-mutants`／`--only`／`--strict`）時把這些檔的 sha256 記在
`tools/.testcache/last_full.json`；沒有記錄就退回 `full`。`slm_runtime.h` 的突變在單元測試 `menu-runtime-mutations` 裡，每次都跑。

選項：`-j N` 行程數（預設 CPU 數）；`--strict` 用 unicorn 的指令計數上限、不用快取（等同舊行為）；`--kills` 突變不 failfast（要看每個突變被哪些測試抓到時用）。
終端機每個套件一行；完整日誌與 `report.json` 在 `tools/test-logs/<tier>-<時間>/`。各套件原本的指令（`python3 -B -m unittest test_slqs`、`--mutate` …）照舊能單獨跑。

| | 之前（逐一、序列） | 之後 |
|---|---|---|
| fast | — | **6.7 s** |
| 全部測試 | 742 s（slqs 328、core 120、runtime_mutations 64、qs_page 60、runtime 54、qsct 40、apply 34、api5 23、page 15） | 序列 211 s；`full --no-mutants` **83 s** |
| 全部突變（339 個） | 沒完整跑過；估計約 10.6 h | `full` 合計 **958 s**，全部 PASS（含 settings-migration 8 項） |

數字與每個類別、慢測試的時間在 `tools/test_timing_baseline.json`。測試數不變（slqs 53、qs_page 58（1 skip）、qsct 32、apply 47、api5 11、menu 15、page 13、runtime 11＋1、pb_page 4、site 6；core 報表的每一列比較數逐字相同）。

變快的原因：
- **unicorn 的 `count=` 上限**會逐指令插樁，QS 測試慢 4–5 倍。改成牆鐘上限（count ÷ 1000 萬指令/s；實測 1–3 億），能返回的程式結果不變；`SL_EMU_LOG=檔名` 會列出沒跑到終點的呼叫（全套 0 筆）。`SL_EMU_COUNT=1` 恢復計數器。
- **快取**（`qs-container/testcache.py`，放在 `tools/.testcache/`）：SensorLab BIN、容器 BIN、v4 核心、網頁版的逐步狀態。鍵 = 建置時實際讀到的所有東西：repo 內所有載入的 Python 原始檔、開過的檔（含韌體映像）、clang 用 `-M` 列出的標頭、突變用的環境變數（是檔案就取內容 sha）。大小＋mtime_ns 不同就比內容。`full` 先用 `SL_TESTCACHE=refresh` 重建一次再分派；突變一律唯讀（`ro`）；`SL_TESTCACHE=0` 關掉。每次開機都要讀的映像與 `build_autorun.py` 改成每個行程一次。
- **容器建置**：`editor_data.pool_offset` 逐位元組 `startswith` 改成 `find`，9.8 s → 1.3 s；BIN 逐位元組相同（sha 59bdd136…）。
- **core**：`test_core.py --jobs N` 每個比較步驟一個 fork 行程（各自固定種子），報表相同；`core_data.h` 內容沒變就不重寫。
- **突變**：每個突變一個行程，空的 bytecode 快取（`PYTHONPYCACHEPREFIX` 設成該突變的暫存目錄，避開同長度改寫的舊 .pyc），預設 failfast（`SL_MUT_FAILFAST=1`）。`test_qsct.py`／`test_qs_page.py`／`test_core.py` 加了 `--part=k/n`。`test_apply` 的 host dylib 改到每個行程自己的暫存目錄（平行時不會覆寫別人載入中的 dylib）。

還慢的：
- `core` 全量 ≈ 52 s，被 `grid` 一個步驟卡住（160 萬筆 Python 參考計算）；切開會改變 smc 去重的比較數，所以沒切。
- 突變占 `full` 的大部分：slqs 一個突變 = 重建＋整套 slqs（failfast 下抓到的很快，存活的要跑完整套）。
- `menu/test_page.Native.test_native_firmware_parses_both_pages` ≈ 9 s、`test_runtime_mutations`（10 個編譯突變串在一個測試裡）≈ 20 s：主要是 Python 端與重建，不是模擬。
- unicorn 開機後快照沒做：一次開機已降到約 1 s，平行後不是瓶頸。

突變清單整理（2026-10-30，Bei 同意的測試修正；BIN 不變）：
- 過時樣式更新成現行原始碼、原意不變：slqs「RECIPE without a text title」（標題條件多了 MB/s、QR）、「"max" with one decimal」（前面多了 `n =`）、「crop small line still the readout」（I 值改成 min(視窗×合併, S 裁切)）；只是補 `(void)x` 讓突變編得過（-Werror 未使用變數）：「space after the arrow」「ISP value without the kernel」「ISP footer label without the kernel」「defaultPick: R[0] again」。qs_page「sub-QS focus not on tile 1」（現在 post `at`）、「fine mode never starts」（`qc_sub_open` 多一個參數）。
- 存活的補測試：`Preview.test_19`（新腳本 'ISP bin just short of the FPS; I.HBIN reason'：HD 2K 11b 1x3 停在它自己的上限 131.991，ISP HBIN 3 版本只到 131.676 → 反灰 `<131.68p`、轉盤拒絕；降一格後 ISP 3 可選，S.HBIN 2／3 反灰 `→I.HBIN1`）抓到 slqs「a recipe lowers the FPS again」「ISP reason name」「ISP option ok ignores the FPS」；`test_sequences_reach_what_they_name` 加了這三個狀態的檢查。qs_page `Recipe024.test_the_window_centres_the_current_option`（測試用戶端改成 10 個選項、pitch 3）抓到「window not re-centred」。
- 刪掉兩個等價突變（理由寫在 MUTANTS 註解）：「dial lands on a value that cannot reach the FPS」——所有預設格、1014 個自訂 DC×RES、每個切換點格率、每個可用 recipe，沒有任何轉盤出現「下一格存在但太慢、再下一格可以」；「defaultPick: horizontal before AD」——只有真 14（1x1、RES=DC）記 14 bit，同垂直合併時對手水平距離相同、RS 較短，RS 那一步選出同一個。
- `test_settings_migration.py` 改讀自己的固定輸入 `qs/test-fixtures/settings-migration/`（卡上備份 v0.5.0test／v0.2.4 原樣複製，加上 v0.7.0test／v0.3.1 預設建置；README.txt 有 sha），已放進兩層的 full。

## v0.6.0test（2026-10-30，離線整合；live-v1 上過卡，回放凍結後已退回 v0.5.0test）

最新狀態以 `../notes/STATUS_20261030.md`、建置器當次輸出的 `build-<ver>.json` 與測試日誌為準。
**下方 v0.2–v0.5 各節是歷史版本紀錄**；其中的位移、hook 數、容器版本、離線狀態與上機步驟不能直接套用到新 BIN。
卡上已有的 v0.5.0test 生效 V1 試驗，記錄在 `projects/qs-container/validation/2026-10-30-apply1`；本次新組合未部署。

- 原始碼使用 QS 容器 **API 5**：原廠槽位替換、編輯器清單與由選單開啟子 QS／細調。容器目前建置版本是 v0.3.0；卡上的 v0.2.4 不具有這份新介面。
- `sq_push` 已接套用單元；不再只是計算顯示。回放尺寸、DefaultScale、RAW14 分類與 HUD 修正已接到離線建置；NBR 註冊只在 UI callback 做。
- `../menu/slm_page.py` 產生 `SLM_PAGE`／`SLM_PACK`；`slm_runtime.h` 的私有清單、確認訊號與摘要在 UI callback 初始化成功後才切換原廠頁面。
  DC／RES／FPS 的 CUSTOM 常駐；FPS 達不到的列保留原廠反灰判斷。Pick 先 -1 再列號，讓同值 CUSTOM 可以重開；程式同步 VALUE 不會觸發選取。
  `SLM_*N` 是最後一列索引（count−1），List／MenuItem_Select／IconChange 一起綁定；MOV 格式反灰且私有設定在 MOV 下鎖住，格式列可切回 CinemaDNG。
- CUSTOM 換頁保留同頁原廠 QS 的全部五筆 action（含 MENU_ReturnScreen）。兩頁共用 `SLM_PAGE + SLM_REQUEST_OFFSET` 的常駐請求字串：成功安裝後清空，確認開啟時寫 QS，下一次 layout leave 清空，避免重建選單時再跳一次。
- 選單清單／頁面 **27/27 離線通過**（真 ARM FPUI、原廠 NBU parser、Lossless 真區塊雙順序合併），6 個頁面與 11 個清單突變被抓到；詳 `../menu/out/menu-build.json`。
  回放的 47 項離線測試與突變詳 `../notes/PLAYBACK_DESIGN.md`。完整 QS／容器／runtime 的最終結果由各自本次測試日誌記錄，不把舊版測試數當新版結果。

14-bit 判斷仍依**實際處理路徑**：已測的 RWZM／CRCT 縮放配置丟低兩位，所以目前產品配方用 12-bit 容器；1:1 的真 14-bit 已有證據。
這不能推出「所有機內硬體都不可能 14-bit H2」。HSEP 新路徑的小圖、bypass／格式、錄影串流與 CPU 吞吐是各自獨立的待驗事項，見 `../notes/TRUE14_2X_RESEARCH.md` §10–11。
新版本的回放大幅面池、真實反灰／50 列捲動、事件通知時序、CUSTOM 返回選單與相機穩定性都仍 pending。

## v0.2 原型基線（歷史）

`fpSup/SensorLab-IMX410_v0.2.0test.BIN`（sup_id `SL41`，72 980 B）。用戶端，搭配 **QS 容器 v0.2.2（API 4）**
（`projects/qs-container/out/fpSup/QSContainer_v0.2.2.BIN`）。規格：**`../preview/dcres.html`**（Bei 認可的網頁版，以它為準）
與 `../QS_DC_RES_SPEC.md`。
**這一階段只選擇與顯示**：不裝任何感光元件／ISP 設定。之後的「套用」接在 `slqs.c` 的 `sq_apply()`（見下）。
全部離線：沒碰相機、沒碰 USB、沒寫卡；共用 loader 位元組與其他產品沒動；v0.1.0test 的 BIN 與 `out/build.json` 留著沒蓋掉
（新的是 `out/build-0.2.0test.json`）。

| 檔 | 內容 |
|---|---|
| `slqs.c` | 用戶端本體，跟 C 核心同一個編譯單元（`#include core.c`） |
| `build_slqs.py` | `python3 -B build_slqs.py --out out`；`link_flat()` 把 `.text` 與唯讀資料排成一塊、自己解 Thumb 呼叫與 `-fropi` 的 MOVW/MOVT，需要載入時重定位的一律拒絕 |
| `preview_runner.js` | 在 node 裡跑網頁版自己的程式（`// ---- render` 之前的邏輯＋`act`/`moveFocus`/`closeSub`），輸出每一步的畫面狀態 |
| `test_slqs.py` | unicorn 測試（真 v4 核心＋真容器 v0.2.2＋本 BIN＋真映像）、與網頁版逐步比對、`--mutate`、`--timing` |
| `slqs_ref.py` | v0.1.0test 的 Python 參考（DC/RES 舊版），已由網頁版取代，留作紀錄 |

## v0.2.1test：主 QS 畫面排版（搭配容器 v0.2.3；live run 4）

`out/fpSup/SensorLab-IMX410_v0.2.1test.BIN`（72 964 B）；v0.2.0test 的 BIN 留著。
- RES 選項列只顯示標籤（1K、2K…），倍率只在 RES 格子的小字（網頁版同）。
- FPS 切換點的「•」（U+2022）字型裡沒有，上機畫成「?」；改用「·」（U+00B7，RES 小字分隔符已上機證明畫得出來）。
  網頁版仍是「•」，`test_slqs.SMALL_MAP` 對照。點狀底線與置中由容器 v0.2.3 處理；RECIPE 照舊 `QSC_F_TITLE`，容器不再給它借用圖示。
- 網頁版 `RES.opts` 那行的註解吞掉了 `sel:`（網頁本身也壞），已換行修好。
- **已知差異（不在這一輪）**：網頁版後來的 RECIPE 子 QS 規則（達不到 FPS 的值反灰寫 `max N`、recipe 不降 FPS）還沒移植；
  `Preview.test_10` 標成 expectedFailure，移植後拿掉。
- 測試：`Tiles.test_main_qs_layout_v021`；突變 `v0.2.1test: …` 4 個。

## 功能

| 功能（清單標籤） | 格子 | 轉盤 | AEL |
|---|---|---|---|
| DC（`DC`） | DC 圖示、`HD`/`CUSTOM`、`35.9 × 20.2 mm` | 常見裁切，到頭停住 | 子 QS：DC、WIDTH、HEIGHT、RATIO |
| RES（`RES`） | RES. 圖示、K 標籤/`CUSTOM`、**看到的尺寸**`·`倍率（recipe 少幾列時黃色） | 清單由小到大 | 子 QS：RES、WIDTH、HEIGHT、RATIO |
| FPS（`SL FPS`） | 原廠 FPS 外觀、`59.94`、`• 32 recipes` | 常用格率到 1000，達不到的反灰並跳過；recipe 最高點有點狀底線 | **細調**：K 那種 `◀ 59.954 ▶`，前轉盤 VMAX ±1、後轉盤 10 步 |
| RECIPE（`RECIPE`） | 標題文字 RECIPE、`11b 3x6`/`CUSTOM`、`RS 3.13 ms` | 只在可用的預設 recipe（ISP 1x1）之間 | 子 QS：RECIPE、ADC、SENSOR HDC/VDC/HBIN/VBIN、ISP HBIN/VBIN（7 格） |
| FORMAT（`SL FORMAT`） | 原廠 FORMAT 外觀、`DNG`、`12bit`/`14bit`（跟 recipe 的 AD） | 無 | 無；選項列 `DNG | MOV`，MOV 反灰 |

行為跟網頁版逐條相同（網頁版 10-29 修正全部在內：比例鎖記住上鎖當下的比例並吸附預設、固定 K 以標籤記住、
小 DC 暫用 ×1 不忘倍率、細調每步數字必變、細調值只留一個並插回清單、選的 recipe 不被覆蓋、ISP bin 核心 × SOFT/STD
共用模式、反灰寫原因 `no 3x1`／`needs 12bit`／`not at this RES`、RWZM 0.5% 內寫 1:1、RS 兩位小數）。
介面字只用英文與原廠字串；`CUSTOM` 用大寫（原廠粗體字形只有大寫）。

**recipe 在相機上算**：任何 DC×RES（含自訂）都由 C 核心 `core_qualities_tol(DC, RES, 不設上限, 2%)` 現算
（= `isp-lab/host/quality.py` 逐位元），4 格快取。網頁版的 FPSDATA 只是替身。

**原廠 FORMAT 格不能借**：原廠格的值是 `Icon02` 自己的影格、選項列是它 holder 的 keyEvent（直接寫 `MV_RecordingFormat` 原廠設定），
容器只畫自己 id（≥49）的格子。所以 FORMAT 是我們自己的功能（放進編輯器取代原廠 FORMAT 格），只顯示、不寫原廠設定。

## 計算成本（unicorn，`python3 -B test_slqs.py --timing`）

| DC×RES | recipes | 指令數 | 堆疊 |
|---|---|---|---|
| OG 1K | 58 | 4.03 M | 2 472 B |
| HD 2K | 36 | 4.35 M | 2 472 B |
| S35 0.7K | 58 | 5.29 M | 2 472 B |
| OG 6K | 3 | 3.32 M | 2 472 B |

一次 3–5 M 指令；A9 在快取別名上大約 1 指令/週期，約 10 ms 級（**沒量過**；非快取別名慢約 50 倍會到 0.3 s，
BIN 有 `SL_F_CACHED_OK`）。只在換 DC/RES 而快取沒有時算一次（4 格 LRU），FPS／RECIPE 的轉盤不重算。

## 記錄（本 BIN 自己的）

`rec_off`（`out/build-0.2.0test.json`）65 字：`{'SLQ2', 2, DC 寬高, 兩個鎖, DC/RES 鎖定比例, 倍率, K 標籤, 自訂 RES, 記憶數,
fps 分子分母, 細調值, 選的 recipe + 它的 7 個參數, 兩軸核心, 模式, 8 × {裁切, RES}, FNV}`。
**只在容器的 `leave()`（每次換版面：關 QS、進選單）寫**，有改才寫；轉盤不寫卡。模式 7 原地覆寫＋讀回比對；
寫前 `file_is` 比對前 48 bytes，不是自己就不寫、絕不建檔；錄影中不寫（五個功能錄影中也鎖住）。

## 「套用」的接點

`sq_apply()`（`slqs.c`）：每次 `leave()` 時算出有效選擇——DC、RES、有效 recipe 的 readout key／HMAX、所選格率的 VMAX 步
（`fps_at(VMAX) ≤ 所選` 的最小 VMAX）、兩軸核心與模式——存在 `st->applied`，目前**不寫任何硬體**。
下一步在這裡接：`core_quality_plan(q, CLK, hm×VMAX)` → `core_smc_create`（感光元件模式），`core_quality_spec` →
`core_isp_plan`/`core_isp_row`（ISP），核心與 SOFT/STD → BINFILT。

## 離線測試

```
cd projects/sensorlab-imx410/qs
python3 -B -m unittest test_slqs          # 30 項，約 150 s（要 node）
python3 -B test_slqs.py --mutate --part=0/4   # 四份可以平行跑；34 個突變全部被抓到，每一項測試至少被一個突變打掉（slqs.c、build_slqs.py、preview_runner.js；2 個等價突變不列，見 MUTANTS 註解）
python3 -B test_slqs.py --timing
```

| 類 | 內容 |
|---|---|
| Preview（14 個腳本） | 網頁版在 node 裡跑同一串按鍵，每一步比對：前 5 格（自訂 QS 版面）或子 QS 每一格的大字、小字、黃色；子 QS 標題；焦點格的選項列（標籤、小字、黃、點狀底線、黃色細調值、反灰、目前那個；超過 16 個時比對同一個 15 項視窗）或數字轉輪。FPSDATA 由 `preview/gen_fps.py fpsdata()` 現產生，腳本走到的自訂 DC×RES 也產生（同一份 Python）。另一項檢查腳本真的走到了：SQ、細調與細調值、反灰、黃色 RES、14bit、反灰原因、ISP bin、CUSTOM recipe、自訂 DC、切換點標記 |
| Exact | JavaScript 的 double：`a16(W×r)`／`ev(H×r)` 每個偶數寬高 × 5 個倍率、mm 每個偶數 px、kLabel、`(w/h).toFixed(3)`、鎖定時的 `Math.round(w/asp)`／`(h×asp)` 與 `|p.w/p.h − asp| < 0.002`，全部對 node |
| Tiles | 開 QS 的五格、RECIPE 子 QS 7 項（第 7 項用 UI 72）、FORMAT 沒有轉盤且 MOV 反灰 |
| Record | 只在 leave() 寫、下次開機還原（含 FPS／recipe／核心）、壞記錄 → 預設、不是自己的檔／不見了 → 不寫不建、錄影中鎖住不寫、原廠設定不動 |
| Apply | `sq_apply` 只在 leave() 跑；有效 recipe 的 HMAX 與 VMAX 步對 `quality.py` |
| Build | 平面影像不需重定位；指標表會被 `link_flat` 拒絕 |

## 上機步驟（照慣例：先告訴 Bei 並等回覆、廣播相機使用權；錄影中與回放中不碰 USB；不按「建立 QR code」）

需要：v4 LOADER.BIN（fpSup 頁版）、**QSContainer_v0.2.2.BIN**、**SensorLab-IMX410_v0.2.0test.BIN**。
卡上不要同時留 QSContainer v0.2.1／SensorLab v0.1.0test（同 sup_id，新版會贏，但別留）；不放 ZQS。
v0.2.1 的格子記錄不會被 v0.2.2 讀 → 編輯器要重新放。

1. 讀 `\fpSup\` 清單、備份 LOAD.LOG；記下 CINE 兩組 8 格（`mem get 0xC31B0ABC,,32`）與 SetMovRecFormat／Size／Framerate。
2. `fl del` 舊的 v0.2.1／v0.1.0test，部署（讀回比對）：
   `python3 -B fpSup/fp_usb_shell/v3/deploy_v3.py projects/qs-container/out --only fpSup/QSContainer_v0.2.2.BIN`
   `python3 -B fpSup/fp_usb_shell/v3/deploy_v3.py projects/sensorlab-imx410/qs/out --only fpSup/SensorLab-IMX410_v0.2.0test.BIN`
3. `ui_drive.py reboot`。LOAD.LOG：兩個都 LOADED。進一次選單後狀態：N 5、qs_ready 1、qs_vars 148。
4. 編輯器（CINE）：放成 `SL FORMAT, DC, RES, SL FPS, RECIPE` 在第 1–5 格（清單最後五列）。離開到 LV。
5. `key QSON`，每一步截圖（`ui_drive.py shot`）：
   - 五格都有值；RECIPE 標題是文字；小字是**灰色系統字**（v0.2.2 改的：字形圖不吃顏色）；`CUSTOM` 這種太寬的值用系統字。
   - FPS 格：轉盤走常用格率，高過上限的跳過；下方反灰的是灰字，recipe 最高點下面有點線，`• N recipes` 在切換點出現。
   - FPS 按 **AEL**：版面不變、下方變 `◀ 59.940 ▶`、提示列**不顯示**（v0.2.2 預設）；前轉盤一步、**後轉盤十步**（容器 v0.2.2 分前後轉盤，上機確認 BR/BL 的方向）；
     再按 AEL：細調值黃色插進清單。細調中左右移焦點 → 也離開細調。
   - RECIPE：轉盤只走可用的；FPS 調高讓選的 recipe 不可用 → 顯示別的，FPS 調回來 → 回到原本選的。
   - RECIPE 按 AEL：8 格（RECIPE＋7 項，第 8 格是 ISP VBIN）；ADC 換成 14bit 時 FPS 自動降、FORMAT 變 14bit；
     SENSOR HBIN 的反灰項小字寫原因（`no 3x1`、`needs ...`）；ISP HBIN 轉到 3 有核心與 SOFT。
   - DC/RES 子 QS：RATIO 格標題是 `RATIO`、鎖頭圖在**值的位置**；WIDTH −1 再 +1 回到原值且比例不飄（live 3 的 1.778→1.781）。
   - 子 QS 第 1 格標題是文字（live 3 的 `RES.` 偏右）。
6. **MENU 的新規則（live 3）**：子 QS 或細調裡按 **AEL** 回上層；按 MENU 是原廠 MENU（關 QS、開選單），容器在換版面時把子 QS 收掉。
   看：AEL 回上層焦點回原格；MENU 之後再開 QS 是使用者的 8 格、`sub_open` −1。之後 `status` 確認 shell 還在
   （live 3 的 shell 卡住跟 MENU 的關係未證實——**MENU 這步做完先查 shell**，卡住就停）。
7. 關 QS、進選單（觸發 `leave()`）→ 讀卡上 BIN 的記錄（`rec_off`）有寫；重開機選擇都在（含 FPS、recipe、核心）。
   `mem get` 兩組 8 格與原廠 Format／Size／Framerate = 第 1 步（原廠設定沒變）。
8. 錄影鎖（**Bei 手動**）：錄影中 QS 五格反灰、轉盤與 AEL 不動作。停錄 10 秒後才接 USB。

收尾：編輯器把五格換回原廠功能，讀回兩組 8 格。

## 離線證明不了的

1. 畫面本身：灰色系統字小字、點狀底線（`. . . . . .` 一個 drawText）、灰／黃標籤、鎖頭在值的位置、長小字縮到 208 px 寬 30 號字是否放得下
   （RECIPE CUSTOM 的小字很長，例 `11b 1x1 ISP 3x3 · RS 15.84 ms`）。
2. `core_qualities` 在相機上的時間（只有指令數）與 UI 執行緒的堆疊夠不夠（量到 2.5 KB）。
3. 後轉盤碼 3/4 的方向（資料照原廠 BR = −1、BL = +1）。
4. **ISP bin 的 STD 模式在相機上選不到**：網頁版要直接點另一個模式的選項才換模式，相機沒有點選、轉盤只在目前模式內走。要 Bei 決定（例如轉盤走完 SOFT 接著走 STD）。
5. MENU 回上層：live 3 看到 MENU 同時跑了原廠 MENU；v0.2.2 預設不再接 MENU（見容器 README），子 QS／細調裡沒有提示（沒有原廠的「AEL 退回」字串）。要不要另找方法讓 MENU 回上層，待 Bei 決定。

## v0.3.0test (2026-10-29): MB/s
A sixth function, MB/s (internal 59; text title, no icon).
- Big text: uncompressed MB/s.
- Small text: `LL ~N`, the conservative lossless prediction from notes/MBPS_TILE_RESEARCH.md v2. It turns yellow past 75 % of the medium's sustained rate.
- Footer: the medium (`SD UHS-II` / `SD UHS-I` / `SSD`) with RAW / LL duty, plus the raw media reads `A<ms_a> B<ms_b>` / `R<ssd ready> M<ssd mnt><sd mnt> S<sd mode>` so Bei can verify the SSD half on camera.
- Media reads (validation/2026-10-29-media): once per QS visit; drv() only with slot 1 or 5.
- Tests force the medium with sq_test 11.

## v0.4.0test (2026-10-29): QR, MB/s footer
`out/fpSup/SensorLab-IMX410_v0.4.0test.BIN`（78 716 B，sha256 `9c4c19d0…`，`out/build-0.4.0test.json`）。offline only, not on the camera yet.
Block 180 096 B (was ~131 KB): `struct st` is 96 952 B of the 98 304 reserved, 47 KB of it the encoder's work area + matrix.

**QR** (7th function, internal 60; text title `QR`, big `QR`, small = the code's first 10 chars + `..`, no footer, no dial,
locked while recording). AEL shows the code over the QS panel; AEL again, the focus moving off, or any layout load
(QS closed, OK, MENU; also `leave()`) hide it.
- Payload: notes/QR_QS_RESEARCH.md §3.4 — 27 fields (213 bit) + CRC-8 (0x07) + 1 pad = 37 base64url chars;
  URL `https://ijigen.github.io/fpSup/sensor_lab_imx410/#` + 37 = 87 B. Values from the selection and the effective recipe
  (`qr_fields`: the real visible size, RS, VMAX step = `sq_apply`'s, readout key index, scw/sch, win_w/win_h).
  Polarities: recipe 1 = CUSTOM, format 0 = DNG, RES 1 = CUSTOM. `sq_test 13` returns the live code, `15` packs given fields.
- Encoder: the stock `FUN_c05c5be8` (ARM; V20, byte mode, ECC L, 1 px/module, Y8, stride 97), data = URL − i per byte
  (cancels `FUN_c05c5b98`'s +i); the matrix is checked (0/255 only, dark corner). The blit takes any n×n (`q->n`), so a V4
  encoder of our own only has to fill `mat` with n = 33.
- Display: a DrawingObserver on the main OSD layer. Group = the first of 4 whose layer has fmt 1 (16 bpp ARGB4444,
  `[0xC3783078 + 8g] + 0x1C`); refused when that group already has 3 observers (`FUN_c0528300` asserts at 3).
  Register `FUN_c0528300(0xC3783020, g, obs)` + redraw request `FUN_c05284E8(ctrl, g)`; hide = `FUN_c05283D8` +
  `FUN_c05284A0(ctrl, g, 1)` (next cycle fills the layer with 0, as `DebugStandbyStateProc` does) + redraw request.
  vtable: +0x0C draw(obs, desc, arg) → 1 when drawn, others no-op/0. Draw only when `desc` dims = 1024×682 and not recording.
- Panel rectangle (live6 2693-mainqs.jpg, 1024×682): **x 0, y 77, 1024 × 454** (two tile rows 77..300, 308..531).
  Scale = ⌊454 / (97 + 8)⌋ = **4 px/module**: code 388 × 388 at (318, 110), quiet zone 33 px (8 modules) top/bottom,
  rest of the panel white. LCD 3.15" 1024×682 ≈ 0.065 mm/px → **module 0.26 mm, code 25.2 mm** (small; if phones struggle,
  the V4 path: 33 modules × 11 px ≈ 0.72 mm in the same panel).
- Per draw cycle: 1024 × 454 px written (≈ 0.9 MB), only while shown.

**MB/s**: footer item 1 shortened to `UHS-II` / `UHS-I` / `SD` / `SSD` with small `91%/42%` (RAW/LL duty); a predicted
lossless frame over 16 MiB (refused by the lossless sup, MBPS research §6.5) shows small `LL —` and footer `624%/—`.
Same in preview/dcres.html.

**Preview** (`preview/dcres.html`): QR in slot 6 (ISO's place); the same payload (`qrFields`/`qrPack`), AEL shows a white
overlay over the panel with the URL; same hide rules.

**S16 → HD (live6 §8, 6K / 48)**: spec behaviour, not a C bug. On S16 the RES dial went 1K (÷2) → 1.5K → 2K, the last
being ×1 (S16's full width); the page remembers the ratio, so back on HD ×1 = 6K, whose fastest recipe is under 59.94,
and fixFps drops to 48. The page does exactly this (`Preview.test_16` + `test_s16_back_to_hd_is_the_spec`).

**Tests** (`python3 -B -m unittest test_slqs`; set `SLQS_CV_PYTHON` to an interpreter with opencv-python when this one has
no cv2, else the decode is skipped = unverified):
- `QRPayload`: the reference itself (CRC-8 check value 0xF4, 213 bit, 37 chars, 87 B URL), the page's `qrPack` in node =
  the reference over 200 random vectors.
- `QR`: C `qr_pack` = reference over 302 vectors + width cutting; the live payload = selection/`sq_apply`/tiles; the real
  stock encoder under unicorn → matrix decoded by OpenCV to the exact URL, then the observer on a fake 1024×682 buffer:
  nothing outside the panel, black/white only, module for module, decoded again, nothing on another layer or when hidden;
  the real `FUN_c0528300`/`FUN_c05283D8` on a fake controller (slot, count, the wipe flag, full group refused); locked
  while recording; the short MB/s footer.
- `Preview` 15/16: QR show/hide rules and the payload compared with the page at every step (not on custom DCs: the page
  keys FPSDATA by DC name, so two custom DCs with one RES share recipes there — a harness limit, found by this check).
- Mutants: 13 new (`--mutate QR MB/s "preview: QR"`).

**Needs the camera**: the group choice (the first 16-bpp layer) and z-order (we draw after the GUI's observer only if
we get a later slot); whether the hide wipe (fill 0 + redraw) brings the QS panel back cleanly or leaves it blank until
the GUI redraws (if the GUI draws incrementally); whether the QR drawn every cycle flickers against the GUI's own panel
redraw; the encoder's time on the UI thread (~8.4 M instructions, est. 10 ms); phone scanning of 0.26 mm modules on the
LCD; HDMI connected (the 1024×682 check skips other layers).

## v0.4.1test (2026-10-29): our own V5-L code, drawn in the QR tile (live7 fixes)
`out/fpSup/SensorLab-IMX410_v0.4.1test.BIN` (83 940 B, sha256 `36c232e6…`, block 230 400 B). Offline only; not on the camera.
`struct st` fits the 143 360 B reserve (_Static_assert) (the 88 KB shadow below; the V20 work area is gone).

**Encoder** (Bei 10-29): our own, `qr_encode` in slqs.c — version 5-L (37×37; V4-L holds 78 B, the URL is 87 B), byte
mode, RS(134,108) over GF(256)/0x11D, the best of the 8 masks (penalty N1–N4; N3 by the 11-module pattern).
URL and payload unchanged (87 B, 37 chars).

**Where**: inside the QR tile itself, only while shown (AEL; AEL again / focus away / layout load hide). Proposal: keep it
AEL-only — always-on would hide the tile's own text, cost a square per frame, and need the restore on every redraw.
- Tile k of the CINE layout (the slot whose `QS_GET` = the focused id at AEL): 256 × 223 at (256·(k mod 4), 77 + 231·⌊k/4⌋);
  the focus box is the tile's own rectangle, 4 px at the sides, 5 px top/bottom (live6 2693, live7 2726).
- Inside the box, 1 px clear: 246 × 211 → module = ⌊211 / (37 + 2·2)⌋ = **5 px**, white square 205 px (2-module quiet zone),
  code 185 px, at tile + (25, 9). LCD ≈ 0.065 mm/px → **0.325 mm/module, code 12.0 mm**.
- Shorter URLs (2-module quiet zone, same 211 px): V4 (33) is still 5 px — no gain (and needs ≤ 78 B: only by dropping
  vis/rs *and* the crop fields, 22 chars → 72 B); V3 (29) → 6 px = 0.39 mm, needs ≤ 53 B: impossible with this 50 B prefix
  (possible with `fpsup.ijigen.xyz/m#` 27 B + 22 chars = 49 B); V2 → 7 px needs ≤ 32 B (no https URL fits).

**Drawing path** (live7: group 0 drew into a buffer that was never presented; hide left the code in the GUI's buffers):
- `FUN_c0528178(g)` = 1 only for g = 2, 3: only those groups commit + present in `FUN_c0528700` (after their observers).
- The GUI's observer is the UIC draw handler `0xC38D3D0C` (`UicContentsIfBase::v16` returns this singleton; live7 found it
  in group 2 slot 0). We register in **the group whose slots hold it** (16-bpp layer), check our slot is after its slot
  (observers run in slot order) — else unregister, `why 6`; full group → `why 5`, never the assert.
- `UicDrawHandler::v5` (+0x1C) returns 0, so no front→back copy (`FUN_c0528ba0` not called): each of the 3 rotating buffers
  keeps what was drawn in it; UIC repaints only what changed. Hence: one shadow of what UIC drew under our square
  (205×205×2 B). Each draw learns it — every pixel of a buffer that never held the code, and of one that did, every pixel
  that is not the code's (UIC repainted it). We remember which buffers (desc base) hold the code.
- Hide: `on = 0` + a redraw request; the observer stays. Each later cycle, a buffer that holds the code gets the shadow
  back (after UIC's own repaint of that cycle, merged) and leaves the list; while buffers remain we request one more
  cycle (`FUN_c05284E8` from the draw thread = an event-flag set, picked up next cycle). Layout load (`leave()`):
  unregister and forget (the new screen is drawn whole; live7 2735 QS close was clean). No layer wipe any more (the
  v0.4.0test `FUN_c05284A0` on group 0 emptied the shared layer: live7 2730).
- Limit: a GUI pixel repainted under the code with exactly the code's colour (opaque 0xFFFF / 0xF000) is not learnt
  (the shadow keeps the previous value there).
- Stock alternative found but not used: `ReqForceDraw` = `FUN_c0527e68(CYC_DRAW(), {0x101, -1, 0})` (UicContentsIfBase::v1,
  DebugViewDispStateObserver after its group-2 register) makes UIC redraw fully (`UicDrawHandler::v1` mode 2), but the
  force byte is cleared after one drawn cycle (`DrawThread::v1`), i.e. one buffer of three; the shadow covers all three.

**Tests**: `QR.test_triple_buffer_and_present` models `FUN_c0528700`: the real `FUN_c0528300`/`FUN_c05283D8` on a controller
with groups 0 and 2 sharing a 16-bpp layer and the GUI handler in group 2 slot 0; 3 rotating buffers; per cycle group 0's
observers draw into a buffer never presented, the GUI repaints into the back buffer only what changed since that buffer
had it, then group 2's observers in slot order, then present. Required: the code decodes on the LCD while shown, nothing
outside the square changes; after hide by AEL (GUI changes only the hint) and by focus move (GUI repaints both tiles)
every presented frame equals the GUI picture exactly; layout load unregisters. `test_encoder_matrix`: V5, OpenCV decodes
the URL; module and square inside the focus box. Mutants include `group 0 again (live7)`, `no restore at hide`,
`only the presented buffer restored`, `the shadow never learns`, RS / format / quiet-zone errors.

**Needs the camera**: that the GUI handler is in group 2 there too and we get slot 1; no flicker between the GUI and our
square; restore clean after AEL-hide and focus-hide; scanning 0.325 mm modules.

### v0.4.1test also: defaultPick, MB/s raster, cost
- **Default recipe** (Bei 10-29, QS_DC_RES_SPEC 配方預設; page `defaultPick`): with no choice yet, `nearest()` picks by
  |DC_h/RES_h − mv| ↑, AD ↓, |DC_w/RES_w − mh| ↑, RS ↓, a full tie in list order. C compares |H − m·h| (one RES per cell),
  which orders exactly as the page's doubles. HD 2K 59.94 → 14b 1x3, HD 2K 90 → 12b 3x3 (`Preview.test_17`,
  `test_default_pick_examples`). Tests whose fixtures assumed the old first-preset default were updated
  (`Tiles.test_qs_open` 14bit, `test_recipe_layout_v022` dials to 12b 2x3 first, `Apply` matches the shown recipe).
- **MB/s** uses the recipe's raster `rec_w × rec_h` (the page's `c.d.rec`) instead of visible + 16 × 10.
- **Cost**: `cur_recipe()` is memoised (key: cell + its compute serial, rate, choice) — defaultPick scans every recipe and
  a refresh asks dozens of times; without it a RES step that computes a new cell went past the harness's 20 M
  instruction cap (the MB/s tile was left stale, Preview 01/04/05/06). Now: RES step with a new cell ≈ 15–16 M, cached
  ≈ 9 M, QR AEL (encode + refresh) ≈ 6 M instructions (unicorn count, all code). The mask math uses a multiply for ÷3.

## v0.5.0test (2026-10-30): the apply step integrated (V1)

`out/fpSup/SensorLab-IMX410_v0.5.0test.BIN`：98 824 B，sha256 `82f84a219321db2f…`，block 278 592 B，`out/build-0.5.0test.json`。
這一節記錄當時的離線建置；後續 V1 生效實機結果見 `../notes/APPLY_DESIGN.md` §13 與上述進度總覽。套用單元在 `../apply/`（當時 ap.h ABI 2，設計見 `../notes/APPLY_DESIGN.md` §11–§12.9）。

**接法：**
- `slqs.c` 在 core.c 之後 `#include "ap.c"`（build_slqs.py 加了 `-I ../apply`）。
- `struct st` 多了 `ap_mem`（32 KiB），STATE_RESERVE 加 0x8200。
- `sup_entry` 呼叫 `ap_init`：claim 26 個 hook 加時脈閘，共 27 個，包含 frmax／frclass 兩個格率閘門。
- `sq_push` = `sq_apply` 算出有效選擇 → 填 `ap_sel`（`standby = 1`）→ `ap_request`。三個地方會呼叫它：
  - 每個轉盤步（`sq_adjust`）；
  - FPS 細調結束（`fine(0)`）；
  - `leave()`。
- `ap_request` 本身就會提交欠帳（被拒絕或延後的那一次），所以「下一個 QS 事件」和 leave() 都會補套用。
- **開機還原**：entry 只 arm、不提交。第一次 leave()（第一次版面載入）把記錄裡的選擇交出去；描述子還沒建好時回 `AP_E_NOTREADY` 並記欠帳，下一個事件再試。

**sq_test 新增的 op：**

| op | 作用 |
|---|---|
| 16 | `ap_flush` |
| 17 | 回傳 `struct ap_status`（22 字）的位址 |
| 18 | 回傳最後交出去的 `ap_sel`（19 字）的位址 |
| 19 | 立刻 push |
| 20 | push 次數 |
| 21 | `ap_init` 的結果 |
| 22 | 送出 `valid = 0` → 回原廠 |

**測試：**
- `test_slqs`：49 項（47 + `ApplyUnit` 2），1 項略過（原本就有）。`ApplyUnit` 也驗 `sq_test 22` 回原廠。新增兩項：
  - entry 已 arm；轉盤一步就到 `ap_request`，帶著有效選擇；沒有描述子時是 NOTREADY 並記欠帳；leave() 會再 push。
  - 有了描述子之後，leave() 把開機欠帳補上：生效、mode 230／231、載體 59.94 經原生 setter 寫入、時脈閘維持原廠；同一選擇不重提交；之後轉盤一步就提交。
  - 測試裡的韌體函式（格式、格率 get／set、LV、清單重算）用小段 ARM stub 取代（`AP_STUBS`）。
- 新增 4 個 slqs 突變，全部被抓：轉盤不 push、leave 不 push、entry 不 arm、sel 的 VMAX 錯。另一個「push 後不呼叫 flush」是等價突變，已刪掉那段多餘的 flush，突變也移除。
- `../apply/test_apply`：31 項，46 個突變全部被抓（`../apply/build/mutate.log`）。

### V1 上機清單（給上機的 agent；照慣例先告訴 Bei、廣播相機使用權；錄影中、回放中不碰 USB）

**卡上要有：**
- v4 LOADER.BIN（fpSup 頁版）；
- `fpSup/QSContainer_v0.2.4.BIN`；
- `fpSup/SensorLab-IMX410_v0.5.0test.BIN`（同一個 sup_id 的舊版刪掉）。

**卡上不能有：** RES-Custom（RESCUS／32RESCUS），因為它 claim 同一批站點。

**怎麼讀狀態（全是唯讀的 `mem get`，不用呼叫任何函式）：**
- `ap_mem` 的位址：
  - 讀 `mem get 0xC0320BA0`，得到一個 B 指令；
  - 目的地 `cave = 0xC0320BA0 + 8 + 4 × sign-extended(imm24)`；
  - `mem get cave,,2`，應該是 `E51FF004 <ap_mem>`。
- 區塊：`block = ap_mem − 0x24050`（state_off 0x18240 + offsetof(st, ap_mem) 0xBE10，emulation 實測）。
- `ap_mem + 0x8F0`，用 `mem get <addr>,,16` 讀出 16 字，依序是：

| 欄位 | 位移 | 應該是 |
|---|---|---|
| magic | +0x8F0 | `31504C53` |
| abi | +0x8F4 | 2 |
| armed | +0x8F8 | |
| svc | +0x8FC | |
| active | +0x900 | |
| cur | +0x904 | |
| picked | +0x908 | |
| in_commit | +0x90C | |
| owed | +0x910 | |
| seq | +0x914 | |

- 接著還有：
  - result `+0x9FC`（有號數；-3 = NOTREADY、-7 = RATE、-9 = BUSY），detail `+0xA00`；
  - commits `+0xA04`、refusals `+0xA08`、lv_reloads `+0xA0C`；
  - picks `+0xA10`、lookups `+0xA14`、canvases `+0xA18`、recrates `+0xA1C`；
  - commit_us `+0xA20`、standby_picks `+0xA24`、carrier_sets `+0xA28`；
  - clk_ok `+0xA2C`、clk_open `+0xA30`。
- 要主動提交：callfn（skill fp-firmware-call）呼叫 `block + 0x7111`（sq_test，Thumb）並傳 `r0 = 16`。
  - `sq_test_off = 0x7111` 寫在 build-0.5.0test.json。
  - 回傳值就是結果碼。

**步驟：**
1. 備份 `\fpSup\` 清單與 LOAD.LOG。記下原廠 Format／Size／Framerate 與 CINE 兩組 8 格（`mem get 0xC31B0ABC,,32`）。
2. 部署並讀回比對，`ui_drive.py reboot`。
   - LOAD.LOG：SensorLab 是 LOADED，**claim 數 = 基準 + 27**（基準 = v0.4.1test 那次的數字）。
   - 讀 26 個站點，都是 `EA…`／`EB…`；cave 是 `E51FF004 + 區塊內位址`。
   - `0xC0189440` 仍是 `2C49F241`。
3. 先用原廠選單把格率設成 **59.94 以外**的值，例如 24。相機設 CinemaDNG、12-bit；媒體用 SSD；HDMI／shell 照 res-lab 規則。
4. QS 選 **OG 2K（DC OG、RES 2K）、29.97、RECIPE 12b 2x3**。轉盤當下就套用。
   - 讀狀態：magic、abi 2、armed 1、active 1、result 0、`cur` 對應 mode 230／231（`cur` 0 → 230）、carrier_sets ≥ 1、clk_open 0。
   - 原廠選單的格率**自動變成 29.97**。
5. **第一個實驗：待機。**
   - standby_picks 要 > 0。
   - 截圖：取景（2000×1320 的 FOV）、比例、無花屏。
   - 觀察 30 s，畫面要穩定；再截一張比對。
   - 異常就停止，先讀卡、記錄（[[freeze-postmortem-discipline]]）。下一次改成 `standby = 0` 做對照（要另外出一版）。
6. 錄 **3 秒**，停錄等 10 秒，再讀狀態：picks、lookups、canvases、recrates 都要 > 0。
7. 讀 `0xC343B590`，應為 **230 或 231**。
8. 拿 DNG 驗：
   - **2016×1330**、DefaultCrop **2000×1320**、**12-bit**；
   - FrameRate：所選 29.97 在實際格率 50 ppm 內就是 30000/1001，否則是實際值的最簡分數；
   - 彩色預覽：先扣黑階再乘白平衡，肉眼看一張；
   - 與 isp-lab 殼路徑同配方的 DNG 比內容統計（可選）。
9. **回原廠**：callfn `sq_test(22)`，送出 `valid = 0` 的選擇，回傳 0。
   - 驗：active 0；再錄一段，必須是原廠 mode（`0xC343B590` 不是 230／231）；clk 字是原廠。

**已知未驗（都是推論）：**
- 待機讀出這條路沒有原廠前例。
- 原生 setter 會不會多觸發一次 LV 重建。
- 提交一次的耗時：commit_us 估約 60–150 ms。
- 錄影計時顯示仍用載體（非原廠格率時會錯；V1 是 29.97，不受影響）。

## v0.5.1test (2026-10-30)：live 1 之後的修正（離線，未上機）
`out/fpSup/SensorLab-IMX410_v0.5.1test.BIN`：99 592 B，sha256 `0cc487dc2316683a…`（全文在 build-0.5.1test.json）。改了什麼見 `../notes/APPLY_DESIGN.md` §13。
- **待機閘門**改掛在 TAB3（待機實際走的路徑）。
- **14-bit AD 經 RWZM** 一律用 12-bit 容器錄（FORMAT 顯示 12bit，ADC 仍顯示 14bit）。
- **真 14-bit 的 BlackLevel** 改成 14-bit 尺度（約 1024），靠新增的 2 個 hook。
- 預設配方的位數那一步改看錄的位數。DC WIDTH 在 6048／5040／4144／3984 上加點線標記。
- 給上機的人（以本版為準，v0.5.0test 那份清單裡的位移已經不對）：
  - claim 數 = 基準 + 29（28 個 hook + 時脈閘）；
  - `block = ap_mem − 0x24350`（state_off 0x18540；用 emulation 實測過）；
  - `sq_test` 在 `block + 0x7293`（`sq_test_off` = 0x7293）；
  - 狀態欄位：
    - magic 在 `ap_mem + 0x9A0`，以前的 +0x8F0 全部加 0xB0，因為多了 2 個 veneer；
    - result `+0xAAC`、commits `+0xAB4`、refusals `+0xAB8`、clk_ok `+0xADC`、clk_open `+0xAE0`、gated `+0xAE4`、blacks `+0xAE8`；
    - `sq_test 17` 的狀態結構現在是 24 字，最後兩字是 gated、blacks。

## v0.7.17test (2026-11-02): QR directly on main QS

The QR tile displays its code automatically on main QS, regardless of focus. AEL is no longer required and has no QR toggle. The registered QR function id determines its slot; the user's eight-slot layout is retained. Existing QSContainer API 6 is sufficient; no container or AutoRun update.

Preparation is called from the existing QR value callback. Because that callback also runs at non-QS layout loads, drawing additionally requires UIC's active owner to be the stock QS object (0xC37859E0, vtable 0xC0D1D6C4), main-QS focus ids below 70, and no recording. Native provenance: UicContentsIfBase v10/v11 at C06D15A8/C06D1660 set/clear v16's handler +8; v16 C06D12D0 returns C38D3D0C. Container temporary sub-QS uses 70..77. Layout leave still detaches and clears buffer history; preparation may register again, but the observer paints only QS. Removing QR from the layout leaves it detached.

The encoder is cached by payload and runs on the UI thread outside the draw mutex. Only the 37×37 matrix and geometry are published under DrawController's existing mutex at +0x78 (the same native guard as C0528700). Each of up to four rotating buffers remembers the small matrix it last held; changed settings can therefore update immediately without mistaking older QR pixels for GUI pixels during restoration. The existing 205×205 bounded tile shadow is retained; no full-frame copy or new firmware hook. The existing limitation remains: a native repaint using exactly the previous code pixel's color cannot be distinguished from that pixel by the shadow learner.

Evidence: `../validation/20261102-qr-main-qs/`. Includes all eight positions, focus/AEL independence, consecutive payload changes and decoding, native-owner and layer rejection, recording/submenu restoration, old-container compatibility, exact BIN boot/journal replay, and three negative controls. These are offline ARM/display-buffer models; physical LCD visibility, scan reliability and real scheduling remain untested. The website preview retains its historical AEL interaction; its payload comparison is retained with the main-QS visibility expectation updated for this client.
