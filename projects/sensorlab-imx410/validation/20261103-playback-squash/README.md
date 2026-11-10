# 回放播放時畫面被壓扁（2026-11-03，v0.7.20test，上機通過）

Bei 回報：`G9B-QvQfkGKTgOPlCKxIvAfUMpAXoPyL0D7zI`（OG → 3024×2014、14v2，3:2）回放時預覽圖正常，播放時被壓扁。

## 原因（推論，修正後上機現象消失）

回放時 `H_OUT` 已依片子換輸出框，但 LCD 比例吸附的 hook（`H_ASP1/2`、`H_YUV32`、`H_YUV_FALLBACK`、`H_FIT`、`H_RATIO`）在回放時一律交回原廠（舊註解「playback keeps the stock fit」）。原廠電影回放只見過 16:9 片，YUV 路徑會吸附成 16:9，3:2 片因此被壓扁；暫停預覽走另一條依實際尺寸的路，所以正常。

## 修正（`apply/ap.c`）

- `ap_pb_pair()`：我們的回放畫布生效（`pb.active`）、片子不是 16:9、比例兩項都非零 → 片子的比例 `pb.asp`，否則 0（原廠）。
- 上述五個 hook 在 `pb.active` 時改用它；live 的判斷完全不變；原廠畫布（`pbc`）照舊原廠。
- 0:0 防護是整套回歸抓到的：測試的 active 狀態沒有比例，交給原生 fitter 會走進斷言（C0015608）。

## 驗證

- `test_lv_branches`：新增「回放畫布下兩條 YUV 分支都用片子的 8:5」與「16:9 片保持原廠」；原「回放保持原廠」改為只涵蓋原廠畫布與非生效。
- `test_lv_update`：新增 fallback 分支的 8:5 回放案例。
- 反例：修改前的原始碼（`--source` 舊 ap.c）在新增案例上失敗（branches 2、update 2），其餘照過。
- `full-no-mutants.log`：0:0 防護前的一輪，只有 `test_fallback_inactive_and_playback_stay_native` 失敗（即上述斷言）；修後 `test_lv_update`＋`test_lv_branches` 13 項通過。`prelive.log`（部署後跑完）：606 個 job，單元測試全過；突變失敗 7 個，其中 apply 60 與 lv-fit 0 是本次改寫讓舊比對字串失效（`mutant text not found`／`target count 0`），已改為對準新程式碼並重跑：lv-fit 5/5、apply 60 都抓到；其餘 apply 48/56/61、slqs 39/81 是 11-03 已記錄的既有測試債。
- **上機**：`card-settings-build/fpSup/SensorLab-IMX410_v0.7.20test.BIN`（設定取自卡上 v0.7.19，`card-before/`）寫入、整檔讀回一致；LOAD.LOG 載入 v0.7.20test、v0.7.19 為重複。**Bei 播放 G9B-…zI：不再壓扁。** 其他片（16:9 原廠片等）未另外回報。

v0.7.20test 同時包含 11-03 的程式碼品質整理（`../20261103-quality-v0720/`）。
