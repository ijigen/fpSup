# gimbal

[English](#english) | [繁體中文](#繁體中文)

SIGMA's GIMBAL vendor protocol — external control of focus and camera state.
**Status: stopped**

SIGMA 的 GIMBAL vendor 協定 —— 對焦與相機狀態的外部控制。**狀態:已停止**

---

## English

### What it is

A separate vendor command group at `0x94xx`, distinct from the SetCamDataGrp
family the rest of PTP control uses. It was the successor path after host-side
autofocus stopped at recording.

### Proven

- **The command name table** is extracted, at `0xC0CF4D30`–`0xC0CF5050`:
  `GIMBAL_OpenApplication`, `GIMBAL_CloseApplication`, `GIMBAL_GetParameter`,
  `GIMBAL_ShiftParameter`, `GIMBAL_SetGpsParam` and the rest
- **GIMBAL commands still work while recording** — which is what made it the
  successor path, since focus through tethering is refused once recording starts
- **Focus driving is relative only** — `0x9411 ExecRelativeFocusDriving`. There is
  no absolute set
- **But the absolute position is readable** — `0x9405 GIMBAL_GetFocusPosition`
  returns `(1, current_abs)` from `FUN_c035fd48()`, in the **same absolute domain**
  as the min and max that PTP reports. So closed-loop absolute positioning is
  possible: read, compute, drive relative, read again
- The relative driver's own units are scaled by a per-lens coefficient

### The open question that matters

**Is that position readback the actual lens position or the commanded one?**

focus-ai measured that the camera reports the commanded position during motion,
and that the lead grows with speed — at 8500 units/s it needed 345 ms of
compensation rather than the 135 ms of image latency alone. If `0x9405` reports
the actual position, most of that compensation disappears and the closed loop is
straightforward. If it reports the commanded one, this path inherits the same
problem.

It is one test, and it decides whether the approach is viable.

---

## 繁體中文

### 這是什麼

位在 `0x94xx` 的另一組 vendor 指令群,跟其他 PTP 控制用的 SetCamDataGrp 系列是分開的。
它是主機端自動對焦卡在錄影之後的後繼路線。

### 已確認

- **指令名稱表**已抽出,在 `0xC0CF4D30`–`0xC0CF5050`:
  `GIMBAL_OpenApplication`、`GIMBAL_CloseApplication`、`GIMBAL_GetParameter`、
  `GIMBAL_ShiftParameter`、`GIMBAL_SetGpsParam` 等
- **GIMBAL 指令在錄影期間仍然有效** —— 這正是它成為後繼路線的原因,
  因為透過 tethering 的對焦在開始錄影後就被拒絕
- **對焦驅動只有相對** —— `0x9411 ExecRelativeFocusDriving`,沒有絕對設定
- **但絕對位置讀得到** —— `0x9405 GIMBAL_GetFocusPosition` 回 `(1, current_abs)`,
  來自 `FUN_c035fd48()`,而且與 PTP 回報的 min/max **同一個絕對域**。
  所以閉迴路絕對定位是可行的:讀 → 算 → 相對驅動 → 再讀
- 相對驅動器的「單位」會被每顆鏡頭的係數縮放

### 真正該問的那一題

**那個位置回讀,是實際鏡頭位置還是指令位置?**

focus-ai 量到相機在運動中回報的是**指令位置**,而且領先量隨速度增加 ——
在 8500 單位/秒時需要 345 ms 的補償,而不只是 135 ms 的影像延遲。
如果 `0x9405` 回報的是實際位置,那大部分補償就不需要,閉迴路很單純;
如果回報的是指令位置,這條路會繼承同一個問題。

**一個測試就能定,而且它決定這個做法可不可行。**

---

**Notes / 相關筆記:** `GIMBAL_MANUAL`, `GHIDRA_GIMBAL_CHECKLIST`, `PTP_OPCODES`,
`FOCUS_POSITION_DOMAIN`
