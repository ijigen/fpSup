# hpzoom sup

[English](#english) | [繁體中文](#繁體中文)

Half-press magnification for manual lenses.
**Status: working on camera (firmware 5.02), v3 sup with tests**

手動鏡頭的半按快門放大對焦。**狀態:已上機驗證(韌體 5.02),v3 sup 附測試**

---

## English

### Goal

With a fully manual lens (no electronic contacts), the stock fp requires a
button press (OK) to enter magnification, and a half-press of the shutter
cancels it — the exact opposite of what focusing a vintage lens needs. HpZoom
reverses this: **half-press S1 to magnify, release to unmagnify**, and the
live view turns **B&W while magnified** so focus peaking stands out. Stills
are captured in colour.

### Behaviour

- Active only in **MF mode** with **Auto Magnification OFF** — with an
  electronic lens and Auto Magnification ON, the stock behaviour is
  untouched.
- S1 half-press while not magnified posts the magnify-toggle event (OK);
  S1 while magnified is left to the stock path, which unmagnifies — so the
  release side needs no code.
- While the zoom machine is in MfZoom (state 4, full-screen and PIP alike)
  the two live monofilter records at `0xC341399C+0x10/+0x1b0` are re-asserted
  to grayscale every frame by the live-view applier hook (~200/s); the pipe
  consumes them continuously, so no commit and no extra reconfig. On S2-down
  (capture) the colour pattern is written once and the assert is inhibited,
  so the still is colour; S2-up or leaving MfZoom re-arms.
- A `--no-bw` build (`20HPZOMNB.BIN`, sup id `HPZN`) ships the half-press
  magnification without the B&W.

### Hook sites (all SL_CHAIN, insertion hooks that replay or jump below)

| address | function | displaced word |
|---|---|---|
| `0xC02DBBF0` | GUI event poster +4 | `mov r4, r0` |
| `0xC04819DC` | zoom machine `change_state` +4 | `mov r4, r0` |
| `0xC02DBC10` | poster +40, after the queue push | `add sp, sp, #4` |
| `0xC02BAD0C` | live-view applier +4 | `sub sp, sp, #0x64` |

### Files

- `hpzoom/hpzoom_sup.S` — the sup (ARM, position-independent)
- `hpzoom/build_v3_hpzoom.py` — builder (`--card` builds a whole v3 test card)
- `hpzoom/test_v3_hpzoom.py` — unicorn tests against the reference image:
  claims/journal/power-off, CHAIN layering, and the feature itself with the
  poster, focus-mode getter and queue push stubbed

### Proven

- 16/16 emulated tests, including power-off write-back and chaining under and
  over another sup; a deliberate one-line mutation (`EVT_OK` 0x1C→0x1D) is
  caught.
- On camera (firmware 5.02): boot, half-press magnify/unmagnify, B&W while
  magnified, colour still while magnified, and clean power-off/reboot verified
  on the standalone test card from `build_v3_hpzoom.py --card`
  (`20HPZOOM.BIN`, 1504 bytes, SHA-256
  `2119f4fa364430238218ae1eb86d244ed121dda841e09bcea60b5121fa02d705`).
  The same logic as the older v2-style HpZoom card has been daily-driven
  longer: MF/AF and AutoMag gating verified live there.

### Not done

- A menu setting (e.g. an added "Vintage" option under Auto Magnification);
  the gates are fixed at MF + AutoMag-OFF for now.
- AF-lens interaction beyond the gate (not tested with an electronic lens
  attached).

---

## 繁體中文

### 目標

使用全手動鏡頭(無電子接點)時,原廠 fp 必須按 OK 鍵才能進入放大,而半按快門
反而會取消放大——與手動對焦的需求正好相反。HpZoom 把它反過來:**半按 S1 放
大、放開即取消**,並在**放大期間把即時取景轉為黑白**,讓峰值對焦更醒目。拍照
成品仍為彩色。

### 行為

- 僅在 **MF 模式**且**自動放大關閉**時生效——電子鏡頭開啟自動放大時維持原廠
  行為。
- 未放大時半按 S1 會送出一個放大切換事件(OK);已在放大時的 S1 交給原廠路徑
  取消放大——所以「放開」這一側不需要任何程式碼。
- 當 zoom 狀態機處於 MfZoom(狀態 4,全螢幕與 PIP 皆是)時,即時取景 applier
  hook(約 200 次/秒)每幀把 `0xC341399C+0x10/+0x1b0` 兩組 live monofilter
  記錄重新寫成灰階——管線每幀都在讀它們,因此不需要 commit、也不需要額外的
  reconfig。S2 按下(拍攝)時寫回彩色樣式一次並暫停該斷言,照片保持彩色;
  S2 放開或離開 MfZoom 時重新啟用。
- `--no-bw` 版本(`20HPZOMNB.BIN`,sup id `HPZN`)只保留半按放大,不含黑白。

### Hook 位置(皆為 SL_CHAIN,插入式 hook,結尾重放原指令或跳往下層)

| 位址 | 函式 | 被覆寫的指令 |
|---|---|---|
| `0xC02DBBF0` | GUI event poster +4 | `mov r4, r0` |
| `0xC04819DC` | zoom 狀態機 `change_state` +4 | `mov r4, r0` |
| `0xC02DBC10` | poster +40,佇列推送之後 | `add sp, sp, #4` |
| `0xC02BAD0C` | live-view applier +4 | `sub sp, sp, #0x64` |

### 檔案

- `hpzoom/hpzoom_sup.S` — sup 本體(ARM,位置無關)
- `hpzoom/build_v3_hpzoom.py` — 建置器(`--card` 可產生完整 v3 測試卡)
- `hpzoom/test_v3_hpzoom.py` — 以 unicorn 對參考映像執行的測試:
  claims/journal/關機還原、CHAIN 疊層,以及以 stub 模擬 poster、對焦模式
  讀取與佇列推送的功能測試

### 已驗證

- 16/16 模擬測試通過,含關機寫回、與其他 sup 的上下疊層;刻意改錯一行
  (`EVT_OK` 0x1C→0x1D)會被測試抓到。
- 上機(韌體 5.02):以 `build_v3_hpzoom.py --card` 產生的獨立測試卡驗證開機、
  半按放大/取消、放大時黑白、放大中拍攝仍為彩色、關機寫回與重新開機
  (`20HPZOOM.BIN`,1504 bytes,SHA-256
  `2119f4fa364430238218ae1eb86d244ed121dda841e09bcea60b5121fa02d705`)。
  相同邏輯的 v2 版本(HpZoom 卡)已更長時間日常使用,MF/AF 與自動放大的
  門檻皆在實機驗證。

### 尚未完成

- 選單設定(例如在自動放大下新增「Vintage」選項);目前門檻固定為 MF + 自動
  放大關閉。
- 電子鏡頭裝上時的互動(未實測)。
