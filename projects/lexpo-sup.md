# lexpo sup

[English](#english) | [繁體中文](#繁體中文)

Timed shutter speeds past 30 s on the dial.
**Status: working on camera (firmware 5.02), v3 sup with tests**

撥盤上超過 30 秒的定時快門。**狀態:已上機驗證(韌體 5.02),v3 sup 附測試**

---

## English

### What it does

The stock fp stops the manual shutter-speed selector at 30 s and pushes you to
BULB beyond it. LExpo removes that wall: in **M and S modes** the dial offers
**40" to 500"** — the 1/3-stop ladder 40/50/60/80/100/125/160/200/250/320/400/500 s
(≈ 1, 2, 4, 8 minutes) — with the camera's own labels, metering display,
EXIF and playback. Nothing is added: the ladder, the strings in all 17
language blobs and the playback formatter already ship in the firmware; the
mod only widens the bound that hides them.

### Mechanism

Shutter speed is a {numerator, denominator} value everywhere, not a list
index. The 30 s wall is not in the write path (the property store never
clamps); it is the **read-back refresh** vmethod (`0xC009FEF0`), which
re-validates the cell on every read against a computed slow bound. In stills
modes that bound is the fallback default loaded by one instruction at
`0xC007F324` — `movw ip, #0x96f4`, addressing the {30,1} entry of the ROM
defaults table. The entry at `0xC07396FC` is {500,1}, the firmware's own
ladder top. Patching the immediate to `#0x96fc` widens the bound for every
consumer at once: the shell setter sticks, the picker list (bounded by the
same getter) grows the 40"…500" rungs, and a stored >30 s value survives
mode recall.

One patch row, kind EXCL, plus a one-shot live-view hook. The picker list is
pull-based (the ShutterSpeedListBuilder subscribes to nothing), its boot-time
build predates the sup, and the dial widget caches the list count at creation
— a load-time rebuild alone leaves the dial capped one rung past the old top.
So the sup claims the live-view applier site (`0xC02BAD0C`, SL_CHAIN — HpZoom
layers the same site) and arms a one-shot hook: on the first live-view frame
(the GUI is up by then) it calls the camera's own refresh path —
`0xC049D448()` for the controller, then the wrapper `0xC049D6D0(ctrl, 1)`,
the exact call `StandbyStateProc` makes on standby (re)entry: rebuild
(change-gated, so the boot-time 30 s context vs the widened one registers),
the `B1_1_2_Speed` list-changed event with the new items and count, and a
dial re-sync. No load-time rebuild on purpose: it would cache the widened
context and the wrapper's change gate would suppress the event. The loader
journals the stock words and writes them back at power-off; a stale patch
left by a missed power-off is repaired on the next boot.

| address | stock word | patched word |
|---|---|---|
| `0xC007F324` | `0xE309C6F4` (movw ip, #0x96f4 → {30,1}) | `0xE309C6FC` (movw ip, #0x96fc → {500,1}) |

### Files

- `lexpo/build_v3_lexpo.py` — builder (`--card` builds a whole v3 test card);
  the stock word is checked against the reference image at build time
- `lexpo/lexpo_inner.S` — inner entry + one-shot live-view hook: arms a
  CHAIN hook on the LV applier site and, on the first LV frame, calls the
  camera's own picker-refresh wrapper (rebuild + list-changed event)
- `lexpo/test_v3_lexpo.py` — unicorn tests against the reference image with
  the real loader: patch applied, journal + power-off write-back, stale-patch
  repair, EXCL conflict release, rebuild call (force=1, mode=1, after the
  write)

### Proven

- 8/8 emulated tests, including power-off write-back, repair of a word a
  missed power-off left behind, and the forced picker-list rebuild; a deliberate one-word mutation (patched word
  XOR 1) is caught by the tests.
- On camera (firmware 5.02), the same one-word change as a v2-style card:
  `SetShutterSpeed 60 1` sticks after the patch (was clamped back to 30/1),
  the dial lists 40"–500" natively, a real 60 s exposure times at 60 s and
  saves normally. The v3 sup on camera (2026-10-10, standalone --card
  build): cold boot into M mode, the dial offers 40"–500" immediately, no
  mode reselect needed; range persists across power-off/on
  (`30LEXPO.BIN`, 692 bytes, SHA-256
  `3e81afe00996567f7956b58d26ea8ed057c1d63e4d51515d43daf91b8c8a4b90`).

### Not done / notes

- The ladder is 1/3-stop based: 60/125/250/500 s ≈ 1, 2, 4, 8 min — there are
  no exact 2/3/5-minute rungs (adding them would need list and string
  surgery, deliberately not done).
- 500 s is the useful ceiling. The ROM window also holds {1000,1}/{2000,1}
  pairs reachable by the same one-word patch, but the picker ladder and all
  display strings top out at 500 s, and longer timed exposures are unverified
  in the sensor path. BULB remains the path beyond 500 s.
- A full-length 500 s exposure has not been shot end-to-end (60 s has).
  Long-exposure NR, when enabled, doubles the total time — stock behaviour.

---

## 繁體中文

### 功能

原廠 fp 的手動快門選擇到 30 秒為止,再慢就只能用 B 快門。LExpo 解除這道牆:
在 **M 與 S 模式**下,撥盤可選 **40" 到 500"** ——1/3 級距的
40/50/60/80/100/125/160/200/250/320/400/500 秒(約 1、2、4、8 分鐘)——標籤、
測光顯示、EXIF 與回放全部使用相機內建資源。沒有新增任何東西:級距表、17
國語言字串與回放格式本來就在韌體裡;此修改只是放寬把它們藏起來的那個界限。

### 原理

快門速度在各處都是 {分子, 分母} 的數值,不是列表索引。30 秒的限制不在寫入
路徑(屬性儲存並不截斷),而在**讀回刷新** vmethod(`0xC009FEF0`):每次讀取
時都會對計算出的慢速界限重新驗證。在拍照模式下,該界限是由 `0xC007F324`
一條指令載入的備用預設值 —— `movw ip, #0x96f4`,指向 ROM 預設表中的 {30,1}
項目。`0xC07396FC` 處的項目是 {500,1},即韌體內建級距的頂端。把立即數改成
`#0x96fc`,所有消費者一次到位:shell setter 能存住、選擇器列表(由同一 getter
定界)長出 40"…500" 的級距、已存的大於 30 秒數值在模式召回後仍然保留。

一條 patch 記錄(EXCL)加一個一次性的即時取景 hook。選擇器列表是被動拉取式
(ShutterSpeedListBuilder 不訂閱任何通知),開機時的列表建立早於 sup 載入,而且
撥盤 widget 在建立時快取了列表數量——只在載入時重建會讓撥盤停在舊上限再過一級
的地方。因此本 sup 佔用即時取景 applier 位置(`0xC02BAD0C`,SL_CHAIN ——
HpZoom 也疊在同一位置)並裝上一個一次性 hook:在第一幀即時取景(此時 GUI 已
就緒)呼叫相機自己的刷新路徑 —— `0xC049D448()` 取得 controller,再呼叫
`0xC049D6D0(ctrl, 1)`,即 `StandbyStateProc` 在待命(重新)進入時的同一呼叫:
重建(以 context 比較作為變更閘門,開機時的 30 秒 context 與放寬後的 context
不同,因此會觸發)、送出帶新列表與數量的 `B1_1_2_Speed` 列表變更事件,並重新
同步撥盤。刻意不在載入時重建:那會先把放寬後的 context 寫入快取,讓 wrapper 的
變更閘門判定「無變更」而不發事件。載入器會記錄原廠字組並在關機時寫回;若上次
未能正常關機留下殘留 patch,下次開機會先修復。

| 位址 | 原廠字組 | 修改後 |
|---|---|---|
| `0xC007F324` | `0xE309C6F4`(movw ip, #0x96f4 → {30,1}) | `0xE309C6FC`(movw ip, #0x96fc → {500,1}) |

### 檔案

- `lexpo/build_v3_lexpo.py` — 建置器(`--card` 產生完整 v3 測試卡);建置時會
  對照參考映像檢查原廠字組
- `lexpo/lexpo_inner.S` — inner entry + 一次性即時取景 hook:在 LV applier 位置
  裝上 CHAIN hook,於第一幀即時取景呼叫相機內建的選擇器刷新 wrapper(重建 +
  列表變更事件)
- `lexpo/test_v3_lexpo.py` — 以 unicorn 搭配真實載入器對參考映像執行的測試:
  patch 生效、兩處的 journal 與關機寫回、殘留 patch 修復、EXCL 衝突釋放、寫入後
  的一次性 wrapper 呼叫、原指令重放、與其他 sup 的 CHAIN 疊層

### 已驗證

- 8/8 模擬測試通過,含關機寫回、「上次未正常關機殘留字組」的修復,以及強制
  重建選擇器列表;刻意改錯一個字組(patched word XOR 1)會被測試抓到。
- 上機(韌體 5.02),相同的一字組修改以 v2 卡形式驗證:patch 後
  `SetShutterSpeed 60 1` 能存住(原先會被夾回 30/1),撥盤原生列出 40"–500",
  實際 60 秒曝光計時正確、照片正常儲存。v3 sup 上機(2026-10-10,--card
  獨立測試卡):冷開機進 M 模式,撥盤立即可選 40"–500",不需重選模式;
  關機再開範圍仍在(`30LEXPO.BIN`,692 bytes,SHA-256
  `3e81afe00996567f7956b58d26ea8ed057c1d63e4d51515d43daf91b8c8a4b90`)。

### 尚未完成 / 備註

- 級距為 1/3 級:60/125/250/500 秒約等於 1、2、4、8 分鐘——沒有剛好 2/3/5
  分鐘的級距(要新增需要列表與字串手術,刻意不做)。
- 500 秒是實用上限。同一 ROM 窗口內雖有 {1000,1}/{2000,1} 可用同一招指向,
  但選擇器級距與所有顯示字串都到 500 秒為止,更長的定時曝光在感光元件路徑上
  未經驗證。超過 500 秒請用 B 快門。
- 尚未完整拍過一整段 500 秒曝光(60 秒已驗證)。開啟長曝光降噪時總時間加倍
  ——原廠行為。
