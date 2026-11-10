# H1 RAW14 小範圍實機試驗

使用者已要求「測看看」。只測第一順位 H1，沒有包含 sensor 3B/2F、RWZM旗標、錄影或卡片更新。

## 接法與範圍

沿用已驗的 `fastsweep.Session`／BUFA0獨立擷取：sensor V3 RAW14 → CRCT H1 tap → a0 → 自有緩衝。
這是對H1本身與a0抽頭的試驗，不是把整條原生route0x10／BufA7／SIG錄影路徑換成RAW14。
既有 native route 的6組離線 setter 結果仍僅是設定證據。

- CINE未錄影、mode8開始，暫進mode10，sensor沿用先前T-C的v3_14、HMAX911與RX14設定。
- 只抓512列，完整RAW14幾何必須是512×2653 words，否則停止。
- H1操作來自原廠 `C0633B30` 兩筆driver record，垂直設0、H2設0；`C017FAA0`更新H1並清原生bypass bits。
- 暫存 `C31DF600/604` 後，水平源設enum1（÷3）、垂直源設0，避免下一幀清除H1。
- 先後抓Crmf對照，另有H1 bypass與兩筆原廠核。每個階段兩張完整幀。
- DMA目標與scratch各有獨立24MiB allocation。即使硬體仍寫全寬，也保持在自有緩衝內。
- 每次先填滿整個可能寫入範圍，再從完整回讀檢查實際改寫尾端；要求實際bytes等於設定幾何。
- 確認H1源、H1/H2控制、核與mux保住；不把容器格式或非零low2本身當成真14證明。

## 程式與記憶體

新runner：`../../tools/rwzm14/h1_live.py`，預設只列計畫，必須加`--run-live`。
沿用FP USB shell、IMX410擷取與native batch helper，沒有改共享工具原始碼。
所有新helper放在原生heap class0獨立取得的64KiB allocation；只有heap bootstrap使用既有cave claim。
不使用舊boot的地址；各claim只在本次process、此owned allocation內有效。
上傳採用小段原生寫入與完整核對，接著直接借ROM的D-cache/I-cache函式發布，才執行新RAM指令。
任何heap echo不做盲目重試。開始前核對8個native入口的前兩字與本機ROM一致。

## 收尾與失敗

先把來源與控制恢復成全寬路徑，保留全寬buffer讓先前短行能完成，再在completion ISR停止BUFA0。
不能確認completion或idle時保留allocation與程式，不自動釋放、不重啟或重試另一組。
確認停止後還原既有BUFA視窗／回呼，歸還capture buffers，離開放大，再歸還helper RAM。
來源與register前後值、allocation descriptor及每幀hash保存於run目錄。
收尾另讀兩次mode，確認未錄影且frame count繼續增加。

## 離線檢查

`test_h1_live.py` 的9項controller測試通過，包括：最壞全寬界線、H1來源不保住時拒絕、
cache發布順序、未知echo owner拒絕、異常後hook復原、沒有completion時禁止宣告可釋放。
故意忽略H1來源寫入的反例會被抓到。
這些是host流程與guard測試，不模擬sensor、DMA像素、IRQ時序或相機復原。

本次preflight：現有fpshd v3.3.0、worker MEM1可用、app2、record0、MONIT1_60，
boot stamp3576748；echo原handler、H1/H2/source皆為0。這只描述preflight當時。
