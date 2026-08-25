# ui sup

[English](#english) | [繁體中文](#繁體中文)

On-screen display, boot animation and everything the camera shows.
**Status: in progress — text on screen works, a persistent marker does not**

螢幕 OSD、開機動畫與機上顯示。**狀態:能在螢幕上寫字了,持久標示未做**

---

## English

### Goal

Put our own information on the camera's screen — boot progress, tool state, and
eventually live data.

### Proven (2026-08-26)

Writing to the top-left corner needs **two commands**, and it is the second one
that makes anything appear:

```
display text <token>      draws into the OSD surface. A single token — the shell
                          splits on spaces and keeps only the first
display osd 1 <ARGB>      with a colour, fills the whole layer — use it to clear
display osd 1             without a colour, only presents; nothing is filled
display osd 0             turns the layer off
```

**The layer runs three buffers in rotation**, so every step has to be repeated
three times or the previous frame — or the one before that — shows through. A full
update is `display osd 1 0x00000000` ×3 to clear, then
(`display text <message>` + `display osd 1`) ×3 to draw and present.

The layout is hard-coded immediates in the handler and can be changed with
`mem set`:

```
0xC0BB1208   text colour (the first of a two-word style table)
0xC03E46A0   mov r5,#imm   x
0xC03E4698   mov r8,#imm   y
0xC03E469C   mov ip,#0x180 width 384 px, which is the ~24 character limit
```

Other limits: a message **cannot contain a space** (`0xA0` works as one), `%` is
eaten as a format specifier, and **changing camera mode wipes the layer**.

In use: the USB shell's AutoRun draws a boot progress bar with it — where the bar
stops is where the load stopped.

### Retracted

The earlier claim that `display osd` and `display text` never appear because the
draw thread clears the layer every cycle is **wrong**. What was missing was the
`display osd 1` present step.

### Open

- **The text colour encoding.** ARGB, ABGR, RGB565 and RGBA4444 all contradict
  what was measured (`0xF8B2` pink, `0xF0AA` light blue, `0xF800` and `0xF15F`
  invisible). Only `0xFFFFF8B2` = pink and `0xFFFFFFFF` = white are confirmed;
  everything else was extrapolation and should not be trusted. Finding another
  colour means scanning systematically, one nibble at a time
- **A persistent marker.** Surviving redraws and mode changes needs our own
  DrawingObserver registered through `FUN_c0528300`, with vtable `+0x1c` returning
  0 so it is never auto-removed. Researched, not implemented
- **Replacing the boot animation.** It is a UIC Logo screen playing LZ4 `.xci`
  bitmaps embedded in MAIN, so it can only be replaced by reflashing

---

## 繁體中文

### 目標

在相機螢幕上顯示我們自己的資訊 —— 開機進度、工具狀態、之後可能是即時資料。

### 已確認(2026-08-26)

在螢幕左上角寫字需要**兩個指令**,而且第二個才是讓它出現的關鍵:

```
display text <token>      畫進 OSD 表面。單一 token —— shell 以空白切且只取第一段
display osd 1 <ARGB>      帶顏色 = 用該色「填滿整層」,拿來清除用
display osd 1             不帶顏色 = 只 present,不填色
display osd 0             關掉
```

**那個圖層有三塊緩衝輪替**,所以每一步都要做三次,否則會看到上一輪甚至上上輪的殘影。
完整更新序列:`display osd 1 0x00000000` ×3(清)→
(`display text <訊息>` + `display osd 1`) ×3(畫並 present)。

版面是 handler 裡寫死的立即值,可以用 `mem set` 改:

```
0xC0BB1208   文字顏色(兩字樣式表的第一個)
0xC03E46A0   mov r5,#imm   x 座標
0xC03E4698   mov r8,#imm   y 座標
0xC03E469C   mov ip,#0x180 寬 384 px → 約 24 字上限
```

其他限制:訊息**不能有空格**(`0xA0` 可以當空格用)、`%` 會被當格式字元吃掉、
**切換相機模式會把圖層刷掉**。

實際用途:USB shell 的 AutoRun 用它做開機進度條,停在哪就是載入停在哪。

### 已推翻的舊結論

先前斷言「`display osd`／`display text` 永遠不會出現,繪圖執行緒每輪都會清掉圖層」——
**是錯的**。當時漏掉的是 `display osd 1` 這個 present 步驟。

### 未解

- **文字顏色的編碼格式** —— ARGB、ABGR、RGB565、RGBA4444 都跟實測對不上
  (`0xF8B2` 桃紅、`0xF0AA` 淺藍、`0xF800` 與 `0xF15F` 完全看不見)。
  目前只確定 `0xFFFFF8B2` = 桃紅、`0xFFFFFFFF` = 白,其餘是外推,不可信。
  要換色得有系統地掃,一次固定一個 nibble
- **持久標示** —— 要撐過重繪與模式切換,需要註冊自己的 DrawingObserver
  (`FUN_c0528300`,vtable `+0x1c` 回 0 才不會被自動移除)。研究過但沒實作
- **開機動畫替換** —— fp 的開機動畫是 UIC Logo screen 播放內嵌在 MAIN 的 LZ4 `.xci` 點陣圖,
  只能靠重刷韌體替換

---

**Notes / 相關筆記:** `DISPLAY_OSD_MAP`, `OSD_PERSISTENT_MARKER`, `BOOT_OPENING_LOGO`
