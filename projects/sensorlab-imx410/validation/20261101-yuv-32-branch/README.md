# v0.7.5test：補上 YUV 預覽的原生 3:2 分支

使用者回報 v0.7.4 的 QS／MENU 正常，但自訂裁切 liveview 仍拉寬。這一版全程離線，交由使用者測試。

## 原因與範圍

原廠 W v2（YUV）的 C0307280 判斷有兩條 LCD 比例分支。既有 H_ASP1／2 只覆蓋 movie 分支的 enum 3；另一條經 C0307680 後，在 C0306E70 使用 enum 2，直接得到 3:2。先前測試固定回傳 movie 分支，漏掉後者。

新測試執行真正的 C0307280／C0307408／C0307520／C0307680 與顯示種類 getter；使用明示的私有狀態輸入：+1F8=2、camera+44=1、LCD kind=1、實體比例=3:2，切換 +23C=0/1。v0.7.4 在第二條路徑的 8:5 與 16:9 兩案例均輸出 1620×1080 全幅；前者應是 1620×1012、y34，後者應是 1620×911、y84。這是原廠程式離線反例，尚未證實使用者現場走這條分支。

只新增 H_YUV32 @ C0306E70（原字 E3A00002，K_MID），讓該 YUV 分支取本 slot 比例；16:9 slot 使用原廠 enum 3，其他自訂比例使用自有 enum 9，再經既有 H_FIT。無 active slot 或播放時仍走原生。RGB／W v4 分類器維持 v0.7.4 的原生行為。

38 hooks＋clock＝39 claims（0x27）。AP ABI2／QS API6、原有設定格式、AutoRun、loader、QSContainer、sensor／ISP公式不變。只更換 SensorLab BIN。

## 驗證

- apply／原廠fit／分派／UI隔離／新分支：78 tests PASS。
- QS建置、記錄保存、套用：12 tests PASS。
- 真v4 loader／client／container設定遷移：8 tests PASS，預設BIN與獨立fixture逐位元組相同。
- width5088–6048（16步進）、height3520–4040（2步進）：321裁切×2格率，642選擇；每個跑兩條YUV分支及兩種RGB格式，共3852個native fit案例，全部PASS。
- v0.7.4原始碼：相同新測試有2個失敗子案例、0 errors。故意取消新hook的播放保護：2個播放子案例失敗、0 errors。反例不改成PASS。
- 最初來源副本缺少標頭與16:9測試誤用自訂enum的測試設定錯誤，分別保留在baseline-setup-error／baseline-fixture-error；修正測試後的正式舊版結果為rejected-v074.json。

範圍掃描的配方是2K 11-bit 3x2／30.018與19.026格率fixture，並非使用者完整設定的實測。allocator、顯示尺寸及狀態是測試輸入；ROM建構器、種類getter、分支判斷及fit真正執行。GUI繪圖、queue、DMA、LCD尚未驗證。

## 交付

預設設定版；未讀取使用者目前卡上的設定。先備份完整舊SensorLab BIN，再移出卡上fpSup，只放一個新版。重新選回原測試的RES／FPS／RECIPE，測5088×4040、5600×4040、6048×3520、6048×3800，並看QS／MENU是否仍正常。詳細檔案大小與SHA256見REPORT.json。

重建命令（由專案根目錄執行，使用新的空目錄）：

```sh
python3 -B projects/sensorlab-imx410/qs/build_slqs.py --out /tmp/sensorlab-v075-clean-build
```

本次建置輸出：`default-build/fpSup/SensorLab-IMX410_v0.7.5test.BIN`。交付ZIP及校驗碼見REPORT.json，使用者已指定由他上機，agent只做離線工作。不需要更新AutoRun。未做實機畫面、錄影、待機關機再開約10次、舊版切新版暖啟動，亦未重跑無關產品完整發行測試；本次依改動範圍跑對應回歸。

`fixed-v075.json`是修正後的初次分支測試，後續將播放反例改用1:1以防原廠比例吸附掩蓋錯誤；最終78項結果見`regression.log`，反例見`mutant-playback.json`。
