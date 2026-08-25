# fpRemote

[English](#english) | [繁體中文](#繁體中文)

A wireless bridge and low-resolution streaming, on top of PTP external control.
**Status: the wired half already works — [`sigma-fp-bridge`](https://github.com/ijigen/sigma-fp-bridge);
the wireless bridge has not started**

外部無線橋接與低解析度串流,建立在 PTP 外控之上。
**狀態:有線那一半已經可用 —— [`sigma-fp-bridge`](https://github.com/ijigen/sigma-fp-bridge);
無線橋接尚未開始**

---

## English

### Goal

Let an external device control and monitor the camera without a cable: commands
over PTP, picture over a low-resolution stream, with a wireless bridge in between.

### Already working — [sigma-fp-bridge](https://github.com/ijigen/sigma-fp-bridge)

A separate repository, and the wired half of this project. PTP over libusb,
exposed to clients as HTTP and WebSocket:

- Live view, MJPEG at about 24 fps
- Focus control — AF/MF, tap to focus
- Exposure: aperture, shutter, ISO, white balance and the rest
- Movie recording and format control
- Tethered capture at roughly 56 MB/s, DNG or JPEG

Tested mainly on macOS with a 45mm F2.8 DG DN; CINE is the exercised path, stills
much less so; Linux is untested. **UHD 12-bit CinemaDNG is not reachable over
USB** — that limit belongs to [raw sup](raw-sup.md), not to the bridge.

### What this project's firmware research adds

- **The vendor opcode table**: `0x9016`–`0x9038` are the SetCamDataGrp family,
  `0x9032` is SetCamDataGroupFocus, and the GIMBAL group lives at `0x94xx`
- **The payload is TLV** (parsers `FUN_c0501350` and `FUN_c0501508`): a count at
  `+0x04`, then entries of 12 bytes each, `{u16 tag, ..., value}`
- **The GIMBAL command-name table** (`0xC0CF4D30`–`0xC0CF5050`): OpenApplication,
  CloseApplication, GetParameter, ShiftParameter, SetGpsParam and the rest
- **PTP still accepts commands while recording** — the property the bridge relies on
- **Focus is refused while recording** by the handler itself, not by PTP: it only
  drives when `captureState[0x220] == 0 && [0x7c] == 0`. See [focus sup](focus-sup.md)
- PTP arms one TRB per transfer and waits synchronously; there is no standing ring.
  EP 0x83 is its event endpoint, an interrupt endpoint whose SuperSpeed
  `bInterval=11` gives one service opportunity every 128 ms — fine for
  notifications, useless as a stream

### Not done

- The wireless bridge itself, hardware and protocol
- A lower-latency stream than MJPEG live view. The detection image channel at
  `0xC375D8C0` is a clean 320×240 greyscale frame, already proven over hook-push,
  and is the obvious source for a cheap remote monitor

---

## 繁體中文

### 目標

讓外部裝置不用接線就能控制與監看相機:指令走 PTP,畫面走低解析度串流,
中間放一個無線橋接器。

### 已經能用的部分 —— [sigma-fp-bridge](https://github.com/ijigen/sigma-fp-bridge)

獨立的 repo,也就是這個項目有線的那一半。PTP over libusb,對外以 HTTP 與 WebSocket 提供:

- Live view,MJPEG 約 24 fps
- 對焦控制 —— AF/MF、點擊對焦
- 曝光參數:光圈、快門、ISO、白平衡等
- 錄影與格式控制
- Tethered 擷取約 56 MB/s,DNG 或 JPEG

主要在 macOS 上以 45mm F2.8 DG DN 測試;CINE 是走過的路徑,靜態拍攝用得少很多;
Linux 未測。**UHD 12-bit CinemaDNG 無法透過 USB 取得** —— 那個限制屬於
[raw sup](raw-sup.md),不是橋接器的問題。

### 這個專案的韌體研究補上了什麼

- **vendor opcode 表**:`0x9016`–`0x9038` 是 SetCamDataGrp 系列,
  `0x9032` = SetCamDataGroupFocus,`0x94xx` 是 GIMBAL 群
- **酬載格式是 TLV**(parser `FUN_c0501350` / `FUN_c0501508`):
  `+0x04` count,之後每筆 12 bytes `{u16 tag, ..., value}`
- **GIMBAL 指令名稱表**(`0xC0CF4D30`–`0xC0CF5050`):
  OpenApplication / CloseApplication / GetParameter / ShiftParameter / SetGpsParam …
- **PTP 在錄影期間仍可下指令** —— 橋接器倚賴的就是這個性質
- **錄影中對焦被拒絕是 handler 自己擋的,不是 PTP 的限制** ——
  它只在 `captureState[0x220]==0 && [0x7c]==0` 才驅動。見 [focus sup](focus-sup.md)
- PTP 每次傳輸現場武裝一個 TRB 再同步等待,沒有常駐 ring;
  EP 0x83 是事件用的 interrupt 端點(SS 下 `bInterval=11` → 128 ms 一次),
  當通知可以,當串流不行

### 未做

- 無線橋接本身,硬體與協定
- 比 MJPEG live view 更低延遲的串流。偵測影像通道 `0xC375D8C0` 是乾淨的
  320×240 灰階影格,已驗證可 hook-push,是做遠端監看最明顯的來源

---

**Notes / 相關筆記:** `PTP_OPCODES`, `PTP_CINEMADNG`, `PTP_FOCUS_RECORDING`,
`PTP_READ_USER_EXPOSURE`, `GIMBAL_MANUAL`, `GHIDRA_GIMBAL_CHECKLIST`, `IMAGE_CHANNELS`
