# v0.7.4test：自訂裁切不再改 RGB 介面比例

2026-11-01 使用者測試 v0.7.3test 後回報「連QS和menu等 都變形了」，確認是套用自訂裁切後才發生。v0.7.3test 已否決；已請使用者回復自己的原 BIN，回復尚未獨立確認。本次沒有上機操作。

## 找到的原因

先前將 W v4 當作另一條 liveview 路徑，H_ASP3 全域回傳本 slot 的比例。但原生 RGB bitmap 建構器 C03078E0→C0307EA8→C02F3DC8 會把種類設成3或4，原生分派 C02F3E30 因而進 W v4；YUV 描述由 C0307810→C0307E08→C02F3D10 建成0／1，走W v2。QS／選單的原生圖形提交 C02E8730 使用前者。原生YUV提交C02E8030使用後者。

舊測試直接指定 kind=3 並要求它跟著 sensor 比例，這個測試契約錯了。僅有 H_FIT 的精確指標守衛仍不夠：H_ASP3 先讓RGB請求取得同一個slot指標，守衛會合法命中錯誤對象。

新增原生建構器→metadata→分派→完整fit的隔離測試。v0.7.3在4種bitmap尺寸×2種format全部失敗（8個子案例，0 error），例如1024×682的UI被壓成1620×1012、y34；原生對照為1620×1080全畫布。只取消H_ASP3覆寫的隔離副本全部通過，YUV8:5仍為1620×1012。原始失敗記錄與副本保留，不改成PASS。

## 產品改動

移除H_ASP3及C0306DB0的claim／veneer；W v4 classifier完整保持原生。保留H_ASP1／2（YUV）與H_FIT本slot指標、inactive／播放守衛。37 hooks＋clock＝38 claims（0x26），AP ABI2／QS API6不變。沒有修改sensor／ISP公式、loader、AutoRun、QSContainer或設定格式。

新版預設BIN 183088 bytes，SHA-256 `7f1de25f256cb727c57238d73c6a7082d03cbf1b387299d74231a101a77445fb`。相較0.7.3短32 bytes；不同檔名，手動測試必須把舊SensorLab BIN移出fpSup，只留一份，不保留舊尾巴或同時載兩版。

## 離線驗證與界線

- apply／比例／分派／外層／新UI隔離：74 tests PASS。
- QS建置、保存、套用：12 tests PASS。
- 真v4 loader／client／container設定遷移：8 tests PASS，新版本新增獨立預設fixture，舊fixture未覆寫。
- 回報區間321個裁切×2組格率，共642選擇；每組執行原生YUV建構器／fit與兩種RGB建構器／fit，共1926個fit案例。YUV依真slot比例置中，RGB與原生對照一致。
- 2K 11b3x2／30.018與19.026是明示配方fixture，不是使用者完整設定的實測。分派和算術跑真ROM，allocator、display metadata、UI predicate為明示fixture。
- 沒有執行選單事件／GUI實際繪圖、queue、DMA、LCD。沒有對相機寫入或測錄。**使用者已實體LCD回報：v0.7.4的QS／MENU正常，原本liveview拉寬仍在；整體驗收未通過。**

本次交付為預設設定版；目前卡片不可讀，沒有冒稱保留當前設定。使用者自行換檔測試，應保留完整原BIN以還原。

## 後續確認

使用者確認v0.7.4只修復QS／MENU，liveview仍與v0.7.2相同。補跑原生W v2分支判斷後，明示狀態fixture可重現原生3:2分支略過自訂比例而輸出滿版；這未證實為目前相機的實際分支。連線嘗試未建立shell，沒有讀到現場狀態，也沒有部署新版本。詳見[後續證據](../20261101-v074-followup/REPORT.json)。原evidence.tar.gz保留不覆寫，其當時「待驗收」狀態由這份後續紀錄取代。
