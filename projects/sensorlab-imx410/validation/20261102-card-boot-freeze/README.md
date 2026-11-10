# SD 卡插入凍結：0.7.12 設定對照

使用者回報初次使用可開機，後續無卡可開、開機後插卡凍結；懷疑 BIN 保存設定。

唯讀備份 /Volumes/fpSup 的 AutoRun、fpSup 頂層 22 檔與 UI 資源。記錄與來源雜湊見 card-manifest.json / ui-manifest.json。工作完成時再次核對頂層 23 檔全部不變。沒有操作相機、沒有改寫卡。

## 發現

- SensorLab 0.7.12 與交付版只差設定區內30 bytes；QSContainer 0.3.4亦僅設定區不同。兩份設定的校驗均有效。
- SensorLab 保存 DC 2096×1240，raw RES 336×206（顯示320×196），FPS 72000000/223080（約322.754）。沒有鎖定特定配方；實際程式重播選到 key7，12b 3×3 fast，HMAX330/VMAX676。
- 首次 layout 的 leave 回呼自動 sq_push/ap_request；描述表未就緒時延後，就緒時啟用高速設定。這是確定的程式行為，但尚未證明它造成實機凍結。
- 卡上 LOAD.LOG 有 LOADED 0.7.12 和 DONE；舊版 SensorLab/QSContainer是 DUP 未執行。不能證明這是凍結那次的紀錄。
- LOAD.LOG也顯示ISPL、Lossless、Stop-FX、SUPMGR啟用；UnlockWriter因ISPL的claim衝突被拒絕。沒有因此改動啟用清單。

## 離線重播

`replay_saved_settings.py`使用備份原始AutoRun、LOADER、QSContainer、SensorLab；清空設定／改59.94fps只存在模擬副本，其他active companions不加入此隔離模型。

原設定、清空設定、僅降FPS × 描述表未就緒／已就緒，共6組。所有載入及3次layout均返回；寫回journal逐項核對還原。原設定在描述表就緒時成功啟用322.754fps；沒有模擬實體LV、DMA、媒體掃描或插卡事件，未重現實機凍結。

模擬曾因測試腳本誤將sq_test_off再次加上code_off而讀取未映射記憶體；修正為文件指定的block相對位移後六組完成，這是測試腳本錯誤，不算產品故障證據。初次受限環境Unicorn執行異常後改用核准的本機離線執行。

## 對照檔

`settings-reset/fpSup/SensorLab-IMX410_v0.7.12test.BIN`只清空260bytes設定區，逐位元組等於原交付預設BIN。不改版本、碼、AutoRun、其他sup或拍攝檔。

這是交由使用者實機隔離的對照檔，不是已驗證修正；若恢復相同設定後再次凍結，需再定位套用時機／高速處理，不能把清空記憶當成永久修復。
