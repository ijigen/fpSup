# SensorLab 本機模擬器

在 `projects/sensorlab-imx410` 目錄啟動：

```sh
python3 -B preview/server.py
```

開啟 <http://127.0.0.1:8766/dcres.html>。可用 `--port 8767` 換埠；Ctrl-C 關閉。
需要 Python 3.9 以上與 C 編譯器（macOS Command Line Tools）；服務本身沒有額外 Python 套件依賴。

每次啟動都讀取目前 `core/core.c`、`core.h`、`core_data.h`，以及 `qs/slqs.c` 的常數與 QR 編碼器，
一次編譯到獨立暫存目錄。所有自訂 DC／RES 直接呼叫相機使用的 `core_qualities_tol`，使用相同 2% 容差、
配方數上限與順序；沒有另一套 JavaScript 公式。原始碼更新後重新啟動服務即可。
顯示版本讀自 `qs/build_slqs.py`，代表**本機原始碼版本**，不代表相機卡上版本。

本服務只監聽 `127.0.0.1`，只提供預覽資料與頁面，不使用相機、USB、SD、韌體部署或 ARM 模擬器。
編譯不會寫入共用 `core/build` 或 `qs/out`，關閉時清理自己的暫存目錄。
直接開 HTML 檔案時只有原先的預設資料；完整自訂計算與 QR 需從上述本機網址開啟。

## API

- `GET /api/info`：`version`、`fingerprint`、`core_fingerprint`、`qr_url`、`offline`。
- `GET /api/qualities?dcw=5040&dch=3402&rw=1680&rh=1134`：`key`、`case`、`nominal`、`clk`、`vmax_max`。
  `case` 保留 `fps_data.js` 的 `[HMAX, VMAX下限, 配方名稱, 配方欄位]` 格式；自訂裁切 key 包含完整尺寸，
  例如 `C5040x3402:1680x1134`。寬度須是16的倍數、高度須是2的倍數，尺寸範圍與相機相同，RES不能大於DC。
- `GET /api/readout?dcw=…&dch=…&rw=…&rh=…`：同一格每個配方的讀出計畫（`fmt_w`、`line_w`、`raster_w`、`out_h`、`mh`、`mv`、`windowed`、`start`、`y_skip`），
  來自 `host_bridge.c` 的 `preview_readout`（相機核心 `core_quality_plan`）；網頁版走 WebAssembly 的 `wasm_readout`。
- `GET /api/qr?code=…`：37字元的 base64url 配方碼，回傳 `{size:37, modules:[…]}`。
  37列各37格，**1為黑、0為白**，不含外圈空白；內容是相機同一個 `QR_URL + code`。

所有回應停用瀏覽器快取；非本機 Host／Origin 拒絕，沒有寫入 API。

## 離線驗證

```sh
python3 -B -m unittest discover -s preview -p test_server.py -v
node --test preview/test_client.js
```

涵蓋現存45組預設的837個配方、自訂DC／RES與Python公式逐欄比較、相同RES不同DC的key隔離、
不合法輸入、HTTP路由與來源限制，以及獨立QR結構／Reed–Solomon／內容解碼器。
QR測試驗證產生的矩陣，不宣稱已經用手機實拍掃描。

瀏覽器端測試直接執行頁面邏輯，檢查快速切換裁切時的舊回應隔離、目前FPS上限、QR更新順序、
主／子QS顯示，以及固定DC只改RES高度時的比例。背景只示意裁切與輸出變形，不模擬畫質、錄影或回放。

## 網頁（模擬器＝QR 落地頁）

`dcres.html` 同時是相機 QR 的落地頁：`site_page.js` 把 `#<37字元碼>` 解碼載入模擬器狀態（無法完全重現的欄位會列出），
任何變更以 `history.replaceState` 寫回網址（同一個 `qrPack`），並畫出模式詳情與 EN／简／繁。
本機服務也一樣，例如 <http://127.0.0.1:8766/#G9B-QvQfkGKTgOPlCKxIvAfUMpAXoPyL0D7zI>。
`dcres.html` 的規格邏輯（`// ---- render` 之前與輸入處理）沒有改動。發布檔由 `../site/build_site.py` 產生，說明見 `../site/README.md`。
`test_client.js` 另含：全部預設配方的 狀態→碼→載入 往返、隨機碼、網址同步、錯誤碼、語言切換、畫面圖不重疊檢查。
