# fpRemote

[English](#english) | [繁體中文](#繁體中文)

A wireless bridge and low-resolution streaming, running through AutoRun on the
camera rather than through PTP. **Status: not started**

外部無線橋接與低解析度串流,走相機端的 AutoRun 而不是 PTP。**狀態:未開始**

---

## English

### Goal

Let an external device monitor and control the camera without a cable, with the
camera side running our own code loaded by AutoRun — not the PTP surface that
[bridge](bridge.md) and [gimbal](gimbal.md) use.

That choice is the point of the project. PTP means the host asks and the camera
answers, on the camera's schedule. Code loaded by AutoRun runs inside the camera,
can hook whatever it needs, and pushes on its own terms.

### What already exists to build on

- **[usb shell sup](usb-shell-sup.md)** is the same shape of thing, working: an
  AutoRun writes a worker into RAM, the worker serves a transport, and the
  firmware owns the endpoints. A wireless bridge is that with a different link
- **A third bulk pipe is already reserved** — EP 0x83 exists on the current gadget
  specifically so a hook can push a stream without blocking the command channel
- **A cheap picture source is proven.** The detection image channel at
  `0xC375D8C0` is a clean 320×240 linear 8-bit greyscale frame, already carried
  over hook-push at 0.125 ms per frame. For a remote monitor that is the obvious
  source — no Bayer extraction, no compression, no display decoding
- **Code can be run on the camera once, from the host**, without changing the
  AutoRun, which makes experiments cheap

### Not done

Everything. No hardware chosen, no link protocol, no client.

---

## 繁體中文

### 目標

讓外部裝置不用接線就能監看與控制相機,而**相機端跑的是我們自己的程式,由 AutoRun 載入** ——
不是 [bridge](bridge.md) 與 [gimbal](gimbal.md) 用的 PTP 介面。

這個選擇正是這個專案的重點。PTP 是主機問、相機答,節奏在相機手上;
而由 AutoRun 載入的程式**跑在相機裡面**,想 hook 什麼就 hook 什麼,推送的時機自己決定。

### 已經有的基礎

- **[usb shell sup](usb-shell-sup.md) 就是同一個形狀的東西,而且已經在動**:
  AutoRun 把 worker 寫進 RAM、worker 服務一條傳輸通道、端點由韌體擁有。
  無線橋接就是把那條連結換掉
- **第三條 bulk 管線已經留好了** —— 目前的 gadget 上 EP 0x83 的存在目的就是
  讓 hook 推串流而不擋住指令通道
- **便宜的畫面來源已驗證。** 偵測影像通道 `0xC375D8C0` 是乾淨的 320×240 線性 8-bit 灰階,
  已經以 0.125 ms/frame 透過 hook-push 搬過。做遠端監看,那是最明顯的來源 ——
  不必取 Bayer、不必壓縮、不必解顯示格式
- **可以從主機讓程式碼在相機上跑一次**,而且不必動 AutoRun,所以實驗成本很低

### 未做

全部。硬體沒選、連結協定沒定、客戶端沒有。

---

**Notes / 相關筆記:** `IMAGE_CHANNELS`, `EGRESS_MAP`, `HOOKPUSH_PACING`
