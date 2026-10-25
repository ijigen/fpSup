# rec-limit sup

[English](#english) | [繁體中文](#繁體中文)

單次錄影的時長上限。
**狀態: v0.1.0test —— 實機驗證済み（60秒/900秒ジャスト停止、8時間設定で2時間超え・MOV 4時間・CinemaDNG 6時間・メディア満杯まで）**

---

## English

### Goal

The fp stops a movie after two hours: the manual says so, and it is the one
limit that gets in the way of leaving the camera running. This sup raises it
to eight hours without touching code, and leaves everything else — heat,
free space, write errors — exactly as stock.

### How it works

The cap is two 32-bit data words in the Ver.5.02 image, not code:

| address | role |
|---|---|
| `0xC0B9BEDC` | third word of `{0, 0, 7200}` at `0xC0B9BED4`; `0xC0389DE0` fills the first two words from the capacity side, keeps the minimum and stores it as the recording duration (rec parameter `+0x3C`) |
| `0xC0BA0354` | table `0xC0BA0348` + `0xC`; `0xC03A4AB4` computes `floor(value × fps) + 1` as the frame budget of one recording |

The sup is two patch rows through Loader v3 (`fp_usb_shell/v3/patch_sup.S`):
both words are claimed with `SL_EXCL`, the stock words (7200 s, read from the
reference image at build time) go into the loader's journal, the new value is
copied after the claims, and the entry returns. Nothing else:

- no instruction is replaced, no hook, no task, no file write
- RAM only; the flash is never touched, and removing the card returns the
  camera to stock after the next power-on
- at power-off the loader writes the stock words back from the journal
- if another sup already holds either word, this one returns `SL_RELEASE`
  having written nothing

28800 s (8 h) is the value: large enough never to bind, and exact under both
16- and 32-bit arithmetic on the two consumers.

### Proven on the camera

| build | result |
|---|---|
| 60 s | stopped at exactly 60 s |
| 900 s | stopped at exactly 900 s |
| 28800 s | REC counter still running at **2:01:09**, then a **4:02:54.6** MOV (349,440 frames, 109.4 GB) and a **6:06:25.9** CinemaDNG sequence (527,133 frames, 1.712 TB) — both ended because the medium was full |

At the full medium the camera did not freeze: the display went to sleep and the
camera stayed usable. The 60 s and 900 s builds are the proof that these two
words are the cap; the 8 h build is the proof that raising them works on both
recording paths (H.264 and CinemaDNG).

### Limits

- Ver.5.02 only. A card built for one firmware version writes into whatever is
  at those addresses on another.
- Only the time cap moves. Heat, capacity, card write errors and battery stop
  recording exactly as they do on stock.
- UHD and frame rates other than 1920×1080 / 23.976 were not recorded on the
  camera with this sup.
- One earlier boot stopped recording at 108 min with the hand-written version
  of this sup (2026-10-25). It has not been reproduced, and the value was in
  place before recording started both times it was checked afterwards; the
  likely explanation is a boot-relative counter that read the stock value on
  that one boot. Recorded here so nobody assumes the cap is gone under every
  sequence of events.

### Open

- UHD and 50p/60p, and a CinemaDNG run at a frame rate high enough to reach the
  patched frame budget (`floor(28800 × fps) + 1`) before the card fills.
- Whether a recovery boot (card removed, stock again) always puts the cap back
  — the journal path says yes and the offline test checks it; not re-run on the
  camera since the 8 h build went in.

---

## 繁體中文

### 目標

fp 錄影到兩小時就停 —— 手冊這樣寫,也是唯一會妨礙「把相機開著錄」的限制。
這支 sup 把它改成八小時,不改程式碼,溫度、容量、寫入錯誤等其他限制全部照原廠。

### 作法

上限是 Ver.5.02 映像裡的兩個 32 位元資料字,不是程式碼:

| 位址 | 角色 |
|---|---|
| `0xC0B9BEDC` | `0xC0B9BED4` 的 `{0, 0, 7200}` 第三個字;`0xC0389DE0` 用容量那邊的值填前兩個字、取最小值,存成錄影時長(rec 參數 `+0x3C`) |
| `0xC0BA0354` | 表 `0xC0BA0348` + `0xC`;`0xC03A4AB4` 算 `floor(值 × fps) + 1` 當單次錄影的影格上限 |

sup 本體是 Loader v3 的兩列韌體補丁(`fp_usb_shell/v3/patch_sup.S`):
兩個字都以 `SL_EXCL` claim,原廠字組(7200 秒,建置時從參考映像讀)進載入器的
journal,claim 之後才複製新值,entry 返回。其他什麼都沒有:

- 不換任何指令、沒有 hook、沒有 task、不寫檔案
- 只在 RAM;不碰 flash,拔掉卡、下次開機就回到原廠
- 關機時載入器從 journal 把原廠字組寫回
- 若別的 sup 已經佔了任一個字,本支回 `SL_RELEASE`,什麼都不寫

值是 28800 秒(8 小時):大到實際上不會觸發,且兩個消費者在 16/32 位元算術下都精確。

### 實機驗證

| 建置 | 結果 |
|---|---|
| 60 秒 | 剛好 60 秒停止 |
| 900 秒 | 剛好 900 秒停止 |
| 28800 秒 | REC 計數器 **2:01:09** 仍在錄,之後一段 **4:02:54.6** 的 MOV(349,440 格、109.4 GB)與一段 **6:06:25.9** 的 CinemaDNG(527,133 格、1.712 TB),兩者都因**媒體寫滿**而結束 |

寫滿時相機沒有當機:螢幕進睡眠,相機仍可操作。60 秒與 900 秒證明這兩個字就是上限;
8 小時版證明提高它對兩條錄影路徑(H.264 與 CinemaDNG)都有效。

### 限制

- 只支援 Ver.5.02。為某個韌體版本建的卡換到別的版本,會寫進別的位址。
- 只動時間上限。溫度、容量、卡片寫入錯誤、電池都照原廠停止錄影。
- UHD 與 1920×1080 / 23.976 以外的幀率,沒有在相機上實際錄過。
- 2026-10-25 有一次開機用手寫版本時在 108 分停住。之後沒有重現;重測的兩次錄影前
  值都已就位。較可能的解釋是那次開機的計數器從開機起算、讀到的是原廠值。
  記在這裡,免得有人以為任何情況下上限都不存在。

### 待辦

- UHD 與 50p/60p;以及用高到會在卡片寫滿前觸及補丁影格預算
  (`floor(28800 × fps) + 1`)的幀率跑一段 CinemaDNG。
- 「拔卡恢復原廠」是否每次都把上限還原 —— journal 機制與離線測試都說會,
  8 小時版上車後還沒在相機上重跑。
