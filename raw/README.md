# RAW and live-view tools

[English](#english) | [繁體中文](#繁體中文)

## English

This area covers RAW/live-view monitoring and camera-side probes for the fp
RAW path. Live evidence, offline verification, and unfinished work are stated
separately for each tool.

### Live-view monitoring

| Tool | Purpose | Status |
|---|---|---|
| [RAW View](../releases/fpsup-raw-view-v0.2.0test/) | CinemaDNG 12-bit monitoring aligned with recorded RAW | Existing test release; ordinary and Fast Start 2 cards |
| [LV Boost](lv-boost/) | +1/+2/+3 STILL preview brightness, saved level/on-off state (first-use +2), optional Fast Start 2 | Development module; source, tests, and card package |

These are alternative COLOR-menu mods; do not combine their card files.

### Firmware probes

| Area | Status | Contents |
|---|---|---|
| [FHD lossless codec](lossless_codec/) | Writer and power/clock passed on hardware; scratch offline-only; encode dry-run-only | Exact CinemaDNG writer probe, staged codec preflights, assembly sources, and unit tests |

These probes inject code into RAM through `fp_usb_shell`; they are not firmware
updates and do not produce an unsigned `.bin` for flashing.

## 繁體中文

這裡收錄 RAW／即時預覽監看工具，以及 fp RAW 路徑的相機端探針與主機端安全檢查。
[RAW View](../releases/fpsup-raw-view-v0.2.0test/) 用於 CinemaDNG 12-bit 監看；
[LV Boost](lv-boost/) 提供 STILL 預覽 +1／+2／+3 提亮、記憶上次級別與開關狀態（首次預設 +2）及可選 Fast Start 2。
兩者是不同的 COLOR 選單模組，卡片檔案不可混用。每一組工具都必須把
「實機證據」、「離線驗證」與「尚未完成」分開寫清楚。

| 項目 | 狀態 | 內容 |
|---|---|---|
| [FHD 無損 codec](lossless_codec/) | writer 與 power/clock 已實機通過；scratch 僅離線；encode 僅 dry-run | CinemaDNG exact-writer 探針、分階段 codec 預檢、組合語言原始碼與單元測試 |

這些工具透過 `fp_usb_shell` 把程式注入 RAM；它們不是韌體更新，也不會產生可刷入的
未簽章 `.bin`。
