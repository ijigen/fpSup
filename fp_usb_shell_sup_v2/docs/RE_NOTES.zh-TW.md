# USB shell — 挾持 PTP gadget 的端點 (2026-08-25 實機驗證通過)

程式在 `codex/usbshell/`,不相依舊樹。舊的傳輸層在 `codex/_retired_2026-08-25/`。

## 結果

```
USB shell        ✅ 只有 shl,主機端 fpshd + fpsh
錄影共存         ✅ 錄影前後 DALEPENA 都是 0x0A7,錄影檔正常
記憶體讀寫       ✅ 韌體 shell 的 mem get / mem set
三條 bulk 管線   ✅ 主機端 lsdesc 確認
執行注入的程式碼 ✅ oneshot.S + inject.py,不碰 AutoRun 也不碰 daemon
EP 0x83 搬資料   ❓ 尚未實測(描述元與 DALEPENA 都對,但沒推過 byte)
```

## 設計

相機跑的是韌體**原本的 PTP gadget**,由韌體建立描述元、建立與啟用端點、
並在錄影模式重設後重建。AutoRun 只改 ROM 範本的值,不 hook、不注入描述元:

| 位址 | 改法 | 理由 |
|---|---|---|
| `0xC0CF3740` | `03 06 01 01` → `03 ff ff ff` | 介面 class 改成 vendor,主機的 PTP stack 才不會先 claim interface 0 |
| `0xC0CF3780/84` | Int → Bulk,mps 64→1024 | PTP 沒人用的 EP 0x83 改成第二條 bulk IN(SS) |
| `0xC0CF3758/5C` | companion burst 0→3 | 同上的 SS companion |
| `0xC0CF3798/9C` | Int → Bulk | 同上(FS) |

**EP 0x83 已確認是 Bulk / mps 1024 / burst 3**(主機端 `lsdesc`,乾淨開機後)。

有一個反直覺的地方值得記:相機 RAM 裡那個端點的 `wMaxPacketSize` 欄位
(`0xC3774874`)讀出來仍是舊值 `0x000B0040`,但主機收到的是 1024 ——
**韌體在送出描述元時會依速度與型別正規化 mps,不直接用陣列裡的值**。
所以只要把型別改成 bulk 就夠,mps 不用管。`bInterval=11` 也還在,但 bulk 忽略它。

(中途一度看到 mps=64,那是狀態被一連串實驗汙染後的列舉結果,不是真的。
判斷這類事情要以**乾淨開機**後的第一次讀數為準。)

## 畫面提示

AutoRun 會在載入過程顯示進度條,最後變成 `fpSup!`。**進度條停在哪就是載入停在哪**。

正確的繪製序列(繞了很多圈才確定):

```
display text <token>        畫進 OSD 表面;單一 token,shell 以空白切且只取第一段
display osd 1 <ARGB>        ★ 帶顏色 = 用該色「填滿整層」,可用來清除
display osd 1               ★ 不帶顏色 = 只 present,不填色
```

**那個圖層有三塊緩衝輪替**,所以每一步都要做三次,否則會看到上一輪甚至上上輪的殘影。
每次更新的完整序列是:`display osd 1 0x00000000` ×3(清)→
`display text <訊息>` + `display osd 1` ×3(畫並 present)。

版面旋鈕(都是 handler 裡寫死的立即值 / 一張兩字的樣式表):

```
mem set 0xC0BB1208 0xFFFFF8B2   文字顏色 —— 格式未解,見下
mem set 0xC03E46A0 0xE3A05078   mov r5,#120  x 座標(避開電量顯示)
mem set 0xC03E4698 0xE3A08010   mov r8,#16   y 座標
mem set 0xC03E469C 0xE3A0CD06   mov ip,#0x180 寬 384px → 約 24 字上限
```

其他限制:訊息**不能有空格**(`0xA0` 可以當空格用)、`%` 會被當格式字元吃掉、
**切換相機模式會把圖層刷掉**。

**文字顏色的格式沒解出來。** 試過 ARGB / ABGR / RGB565 / RGBA4444 都跟實測對不上
(`0xF8B2` 桃紅、`0xF0AA` 淺藍、`0xF800` 與 `0xF15F` 完全看不見)。目前只知道
`0xFFFFF8B2` = 桃紅、`0xFFFFFFFF` = 白,其餘是外推,不可信。要換色得有系統地掃
(一次固定一個 nibble、每個停久一點),不要像我那樣亂射。

## 尚待處理

* EP 0x83 實際搬資料未測 —— 會在第一個用到它的 hook 寫出來時自然驗到
* 舊的 hook-push 程式碼(`fpshell_tool/camera/telemetry_push.S`、`telemetry_push_v1.S`、
  `raw_probe_worker.S`、`lens_block_sweep_push.S`、`push_addr.S`)寫死舊端點
  `0xC31E3274` / `StartTransfer(9)`,要改成 `0xC31E3270` / `StartTransfer(7)`。
  它們原本靠舊 worker 的 `call` 進入,現在要改用 oneshot 範本
* worker 的 `faults` 計數把閒置逾時也算進去,名字取壞了
* `display text` 的顏色格式未解
