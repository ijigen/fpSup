# bridge

[English](#english) | [繁體中文](#繁體中文)

USB control of the camera over PTP — [`sigma-fp-bridge`](https://github.com/ijigen/sigma-fp-bridge).
**Status: stopped**

透過 PTP 對相機做 USB 控制 —— [`sigma-fp-bridge`](https://github.com/ijigen/sigma-fp-bridge)。
**狀態:已停止**

---

## English

### What it is

A separate repository: PTP over libusb, exposed to clients as HTTP and WebSocket.

- Live view, MJPEG at about 24 fps
- Focus control — AF/MF, tap to focus, absolute positioning, a continuous slider
- Exposure: aperture, shutter, ISO, white balance, metering, compensation
- Movie recording and format control
- Tethered capture at roughly 56 MB/s, DNG or JPEG
- A `focus-ai/` experiment that drove focus from face width and defocus blur

Tested mainly on macOS with a 45mm F2.8 DG DN. CINE is the exercised path; stills
much less so; Linux is untested.

### Why it is here

It is stopped, but it is the most complete thing anyone has built on the fp's PTP
surface, and two of its results are load-bearing for the rest of this repository:

- **UHD 12-bit CinemaDNG cannot be reached over USB.** That limit belongs to
  [raw sup](raw-sup.md) and is why the HDMI RAW path matters
- **focus-ai measured why host-side autofocus is hard**, and those measurements —
  no optical direction cue, a weak face-width signal, a two-part latency — are
  summarised in [focus sup](focus-sup.md) alongside what the firmware offers that
  a host-side loop cannot reach

### What this project's firmware research adds

- **Focus is refused during recording by the handler, not by PTP.** The gate is
  `captureState[0x220] == 0 && [0x7c] == 0`. That is exactly why focus commands
  sent through tethering vanish once recording starts
- **The vendor opcode map** — `0x9016`–`0x9038` are the SetCamDataGrp family and
  `0x9032` is SetCamDataGroupFocus — with the TLV payload format
  (`FUN_c0501350` / `FUN_c0501508`): a count at `+0x04`, then 12-byte entries of
  `{u16 tag, ..., value}`
- **Position and distance convert exactly**, through the lens's own support points
  interpolated in reciprocal distance

---

## 繁體中文

### 這是什麼

一個獨立的 repo:PTP over libusb,對外以 HTTP 與 WebSocket 提供服務。

- Live view,MJPEG 約 24 fps
- 對焦控制 —— AF/MF、點擊對焦、絕對定位、連續滑桿
- 曝光:光圈、快門、ISO、白平衡、測光、補償
- 錄影與格式控制
- Tethered 擷取約 56 MB/s,DNG 或 JPEG
- 一個 `focus-ai/` 實驗,用臉寬與離焦模糊驅動對焦

主要在 macOS 上以 45mm F2.8 DG DN 測試。CINE 是走過的路徑,靜態拍攝用得少,Linux 未測。

### 為什麼放在這裡

它已經停止,但那是目前在 fp 的 PTP 介面上做得最完整的東西,
而且它的兩個結果撐著這個 repo 的其他部分:

- **UHD 12-bit CinemaDNG 無法透過 USB 取得。** 那個限制屬於 [raw sup](raw-sup.md),
  也是 HDMI RAW 路徑之所以重要的原因
- **focus-ai 量出了「主機端自動對焦為什麼難」** —— 沒有光學方向線索、臉寬是弱訊號、
  延遲其實是兩件事 —— 那些量測整理在 [focus sup](focus-sup.md),
  連同「韌體能提供而主機端迴圈拿不到」的對照

### 這個專案的韌體研究補上什麼

- **錄影中拒絕對焦是 handler 擋的,不是 PTP 的限制。** 閘門是
  `captureState[0x220] == 0 && [0x7c] == 0`。這正是 tethered 對焦指令在開始錄影後
  消失的原因
- **vendor opcode 對照** —— `0x9016`–`0x9038` 是 SetCamDataGrp 系列、
  `0x9032` 是 SetCamDataGroupFocus —— 以及 TLV 酬載格式
  (`FUN_c0501350` / `FUN_c0501508`):`+0x04` count,之後每筆 12 bytes
  `{u16 tag, ..., value}`
- **位置與距離可以精確換算**,用鏡頭自己的支撐點在倒數距離空間內插

---

**Notes / 相關筆記:** `PTP_OPCODES`, `PTP_CINEMADNG`, `PTP_FOCUS_RECORDING`,
`PTP_READ_USER_EXPOSURE`, `FOCUS_DISTANCE_PRINCIPLE`
