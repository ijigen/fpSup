# Playback 黑屏後離線 review（2026-10-30，未改部署版本）

使用者在 live-v1（180516 B，SHA 前綴 fdb59ef）切到影片後回報黑屏，已自行重啟。
本次只讀源碼與原廠反編譯，沒有相機操作；尚未重現凍結，也不能把以下缺陷認定為凍結原因。

## 已確定的邏輯缺陷

`apply/ap.c` 的 `ap_pb_canvas()`（約 430 行）先清 `pb.active`；原廠尺寸、位元平面與
DefaultScale 都符合時直接 skip，留下 `active=0`。但 `H_OUT`（618 行）在 `active=0`
時回退到目前 live custom slot，`H_ASP1/2`（643 行）也只用 `pb.active` 排除回放。
因此「原廠片的 canvas 沒改」不等於「整條回放沒改」：若 live slot 是非 16:9，原廠片的
1620×911／320×180 輸出 descriptor 仍可能被 live slot 改形狀，aspect enum 也可能變成 9。
`apply/test_apply.py:1279` 的 stock 測試只比 canvas 與 skip，沒有驗 `out()`／aspect。
這需要補播放模式與自訂 canvas 的分離狀態，並測 stock/custom/live 互相切換；目前未修。

`ap_pb_ctl(mode=0)` 不是完整卸除：只清 active，PB name/tag 觀察與 HUD hooks 仍安裝；
width/height HUD 抑制未受 mode gate 控制。不可把它描述成回復原廠回放。

## 已排除的一項 ABI 疑點

原廠 `FUN_c05c1a58`（`out/decomp/full/blk_c05.c:146663`）為 void，4 個參數是
context、TIFF、crop out、raster out；`H_PBTAG` 先執行 displaced body 再讀 tag 的形狀相符。
它的 `C05C1ED0` BitsPerSample helper 使用 SHORT，現有呼叫先清零再取低 16 位，相符。
這不等於完整原廠播放管線已驗證；現有測試仍 stub 低層 TIFF／GUI／NBR。

## 暫停點與後續

pool、allocation、實際 decoder 寬度由另一離線 review 處理。凍結原因仍未知；也尚未釐清
手動切影片與先前自動 S1 退出的先後。用戶已將優先順序轉回 14-bit 水平縮減研究。
如需回復，應在恢復後使用已知基線的冷啟動／既有 loader restore 流程；不能在黑屏時用
單一 mode=0 宣稱全數 hooks 已卸除。此檔只記錄 review，未改 apply source 或任何 frozen BIN。
