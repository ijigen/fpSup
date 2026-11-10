# 截圖尺寸與顯示提交：離線追查結果

2026-10-30。Bei回覆「現在看不到相機」，因此實體LCD維持**未確認**。本次只執行本機韌體模擬與既有圖片分析，沒有USB、部署或新相機試驗；相機最後已核對狀態仍以`../live/final-verification.json`為準（原v0.7.2與原設定）。v0.7.3不提升為已驗收。

## 本次縮小到的問題

已找到真正的原生SS路徑，並確認一項可造成截圖布局錯誤的尺寸不一致：

1. SS配置及JPEG輸入描述固定為**1024×682**，配置1,396,736 bytes。
2. 寫回畫面的驅動不接收這個SS尺寸，而從目前display物件另取W/H；清除長度、列間距與寫回高度皆使用這組動態值。
3. 原生JPEG提交仍帶固定1024×682及同一個buffer地址，沒有讀取寫回列間距。

這個差異已由真ROM指令離線重現。**尚未證實實機當時選了這個分支、getter實際值，以及像素DMA／JPEG如何產生那幾張RGB回捲**；不能由此排除實體LCD另有問題。

## 證據與測試

| 範圍 | 結果 | 證據與界線 |
|---|---|---|
| CAPTUREON至RecMgr screenshot事件 | 8 tests PASS，root獨立重跑PASS | [按鍵橋接](capture-key-dispatch.md)：真shell lookup、GUI packet、原始standby/QS vtable及event constructor；佇列排程／eligibility是明示fixture |
| SS配置、動態writeback及JPEG提交參數 | 1 test／11宣告尺寸案例PASS，root獨立重跑PASS | [SS producer鏈](ss-producer-chain.md)、[原生資料](ss-writeback-native.json)；getter、clear與寄存器打包真執行；停在DMA觸發與JPEG engine前 |
| streaming fit後直接交packet producer | 3 tests PASS；6組幾何×2個packet layer ID | [資料](native-submission.json)、[測試](test_native_submission.py)：來源／完整尺寸與置中偏移仍保留；包括丟失origin的負向控制、每例strict observer命中及ABI檢查；未經queue／observer或實際consumer選擇 |
| 13張既有圖片的mapping假說 | 單一全域offset或compact-stride模型不足 | [模型與反例](capture_mapping_models.json)：同DC的QS與LV需要不同origin；不是用一個全域偏移就能修正全部圖片 |

提交資料測試的1620×1080 metadata、來源zoom物件與packet layer ID為明示fixture，並非本輪相機讀回。11個writeback尺寸包含6個敏感度案例和5個對應已觀察RGB週期的假設，均**不是getter實測值**。沒有執行完整從按鍵到檔案的worker排程或像素引擎。

各測試程式與JSON保留ROM／overlay雜湊；root重跑輸出在`root-independent-verification.json`及`root-*-tests.txt`。既有產品程式、版本、離線prelive原始報告與卡檔都未更動。

## 下一個精確接點

連接「實際選中的顯示物件／尺寸」與`C0383910`的direct或intermediate分支，追registered output幾何的更新來源；以此判斷本輪RGB異常屬於哪個consumer／狀態。現有fit→packet測試沒有執行這個選擇。不能為了使截圖看似正常，先加全域offset或直接改固定JPEG尺寸。

未解析的SS檔名前綴generator已列出精確virtual callsite，但不影響本次尺寸不一致的證據，不以它擴大搜尋。實體LCD仍需獨立觀察，或取得能代表最終顯示的證據後才可驗收。
