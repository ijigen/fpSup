# 回放 HUD：隱藏 FHD、尺寸改文字（2026-11-03，v0.7.21–0.7.23test，上機通過）

Bei 回報：回放左上角解析度缺圖、上方中間一律顯示 FHD。Bei 選擇：FHD 位置不顯示（c）；左上角改用文字。

## 機制（Playback 頁，`Movie/...`）

- 上方 `Resolution`（923）：`PB_Resolution` 0/1/2 → `M_resolution_1/2/dci4K`。自訂尺寸借 FHD profile 所以顯示 FHD。
- 左上 `PixelSize`（5020）的 `Model` 群組依 `PB_OwnModel`：0（本機）→ `OwnModel`：`Width`／`Kigou`／`Height` 三張圖，圖名來自規則算的 `PB_PixelSizeImageW/H` = `font_S_imageSize_<N>`（韌體只有 71 個 N）；1（別機）→ `OtherModel`：drawText 綁 `PB_PixelSizeString`，規則用逐位數 `font_S_0..9` 拼出 `<!font_S_3,CENTER>…`，任何數字都有圖。上機讀到：本機片時規則照樣算出這個字串。
- 韌體 C++：notifier v5/v6 寫 `PB_PixelSizeWidth/Height`，v92（C05A1500）寫 `PB_Resolution`，v153（C05A2440）寫 `PB_OwnModel = param ^ 1`。

## 改動

| 版本 | 內容 | 上機 |
|---|---|---|
| v0.7.21 | 拿掉 `SL_PB_V2`：`pb_page`（Resolution 加 enum 3 透明影格）在**第一次 MENU 的選單設定**套用（`sup_entry` 時 UI 讀取器還沒好，`UIA_NO_UI`）；自訂片 `PB_Resolution = 3` | ✓ FHD 不見（相機上 `pb_ui_result = 0`、`PB_Resolution = 3`） |
| v0.7.22 | 新 hook `H_PBOWN` @ C05A2440（v153，K_ENTRY）：v92 判定非原廠尺寸（不是 3840×2160／1920×1080／4096×2160／1280×720）→ `PB_OwnModel = 1`；兩種呼叫順序都處理，原廠片接在後面時寫回原值 | ✗ 顯示 0×0 |
| v0.7.23 | `H_PBW/H_PBH` 的「無圖磚就歸零」只在圖磚實驗（`glyph_on`，產品為 0）打開時生效 | **✓ 尺寸正確（Bei 確認）** |

43 個 apply hooks＋clock；journal 56 筆。限制：開機後沒按過 MENU 就進回放，FHD 會照舊（SensorLab 本來就要按一次 MENU 才生效）。

## 驗證

- `menu/test_runtime.FirstMenu.test_playback_page_frame_applied_at_the_first_menu`：開機時 2（UIA_NO_UI）、第一次 MENU 後 0。
- `test_apply.PlaybackTests`：`test_own_model_text_row_for_sizes_without_tiles`（兩種順序、原廠片還原、四種原廠尺寸）、`test_sizes_without_tiles_keep_their_numbers_for_the_text_row`（`glyph_on` 0 時 3008／2004 原樣）；兩項都以舊程式碼確認會失敗。突變 3 個（`P->own_text`、還原、v153 不改寫）全抓到。
- `full-no-mutants.log` PASS；`check_artifacts.py`（真 AutoRun／LOADER／QSContainer，預設與卡上設定 × descriptor 兩態）4 組、56 筆 journal 全還原。
- 上機時曾在回放畫面中呼叫一次 `sq_test(28)`（USB，未出事）——違反「回放中不碰 USB」，之後改成每次按鍵後先看畫面。
