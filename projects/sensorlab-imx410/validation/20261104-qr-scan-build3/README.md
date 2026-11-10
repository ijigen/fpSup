# SensorLab-IMX410 v0.7.34test: after a QR code is applied, return to the QS (2026-11-04, offline candidate)

Follows the v0.7.33test live run (`../20261104-qr-scan-build2/live/`, SS3154). QSContainer stays **v0.3.7** (unchanged).

## Live finding → cause → fix

**Live (v0.7.33test):**
- Scanning and applying worked: `accepted 3`, `applied 3`, the mode changed, and `0xC3588D68` was put back.
- But the page then went into playback "read QR from a playback image" (`R_FileSelect`).

**Cause [C]:**
- **v12 is the Down key.** The handler's v12, which v0.7.33 used as "back", is the Down key (`MenuHandlerSubBase::v12` → key 0x0D).
- **The end message replays Down.** In phase 1 the stock v12 turns read mode off and sets phase 2. The reader's end message (`[3] = 3`) in phase 2 then calls `MenuHandlerSubBase::v12` again (Down).
- **Down leads to playback.** On the page, Down (args 0x28) on KeyEvent 4239 does `CM_FileSelectType = 8` and `controlAppState "R_FileSelect"`.

**Fix** (`scan_to_qs`, used after a successful apply):
1. Read mode off: `FUN_c03714a8(FUN_c0370cf8(), 0)`.
2. Handler `+0x30 = 3` (done), so the end message replays nothing.
3. Our decoder vtable word is put back (`0xC3588D68 = 0xC2DFE860`).
4. One **QS press and release** go into the key device queue: `FUN_c02dbbe8(FUN_c02dbaf0(), 0x22)` then `0x23`. This is the queue the GPIO key interrupt feeds (`FUN_c02dcd80`).
   - The read page then runs its own CommonSystemKeyEvent QS (args 0x14): `SYS_SubmenuOpen`, app sync, `controlAppState "QS"`. That is the stock transition to QS_CINE, where the QR tile shows `QR applied` for 30 s.

**Refused codes:** unchanged. They stay on the read page with "Incompatible QR code." and SIGMA's own Menu → retry.

**Evidence:**
- The key codes come from the firmware's initialised data (`out/seg1_c2ef6e00.bin`, loaded at 0xC2EF6E00). The shell key table at 0xC2F205C0 has `QSON = 0x22`, `QSOFF = 0x23`. Its `OKON/OKOFF = 0x1C/0x1D` also appear in the GPIO key table at 0xC2F1CE68, so it is one code space.
- The page data gives QS (0x14) → "QS" and Down (0x28) → "R_FileSelect". Both are tested by reading the image.

**Inference [I], the live check:** that device code 0x22 arrives at the page as the QS key (0x14), exactly as the physical QS key does.

**Bounce back to the read page:** none expected. The container empties its go request at the next QS layout load (`qsct.c qc_layout`) before the page asks again.

## Builds

| File | Bytes | sha256 |
|---|---|---|
| `card-settings-build/fpSup/SensorLab-IMX410_v0.7.34test.BIN` (**card**; settings from `../20261104-qr-scan-build2/live/readback.BIN`) | 203492 | `424b074d95ad985e8739cdfc6a071019b6a078eb9d26b954dafb29b5f83b4ff2` |
| `default-build/fpSup/SensorLab-IMX410_v0.7.34test.BIN` (blank record; frozen migration fixture) | 203492 | `56c663237c03ceb8aacc0f7799b187805783bb6f0faf8059488fb19d6afe8df7` |

Replace the card's v0.7.33test with this file.

## Tests

| Suite | Result |
|---|---|
| `qs/test_qrscan.py` (22) | OK; **mutants 27/27** (`qrscan-mutants.log`) |
| `qs/test_slqs.py` (68) | OK |
| `qs/test_settings_migration.py` (8, new fixture) | OK |
| `site/test_site.py` (9; local copy regenerated, version string only) | OK |
| `tools/test.py fast` | PASS |

**New tests**, on the real handler and page data:
- applied → read mode off, phase 3, one QS press and release (0x22, 0x23), never the Down key; the following end message replays nothing;
- the v0.7.33 path reproduced: phase 2 plus the end message calls the base Down key;
- the decoder word is put back after an apply that follows page entry;
- the image data: QSON 0x22 / QSOFF 0x23, the shared GPIO code space, page QS → "QS" and Down → "R_FileSelect".

**New mutants:**
- no leave;
- reader left on;
- phase left at stopping;
- word not put back;
- another key;
- no release.

## Live check

1. AEL on the QR tile → read page → show the site's V5 code of another mode.
   - Expect: back in the **CINE QS** within a moment, the QR tile showing `QR applied`, and the tiles showing the code's mode.
   - `sq_test 40`: `applied 1`, `to_qs 1`.
   - `0xC3588D68 = 0xC2DFE860`.
2. **No bounce:** the QS stays (does not jump back to the read page). Close the QS and open it again.
3. **Not in playback:** never `R_FileSelect` or playback.
4. A refused code stays on the read page with "Incompatible". Menu retries; QS / half-press leave.
5. SIGMA's own settings code still goes through Select Destination and saves as before.

## 上機（2026-11-04，Bei 操作）

部署 v0.7.34test（卡上設定版，203,492 B，讀回比對相同），QSContainer v0.3.7，LUT v5 也有載入。Bei 實測後回報「可以了」：掃描、套用、回到 QS 都正常。

讀到的計數（`sq_test 40`）：arms 1、disarms 1、decodes 47（全部由我們的解碼器處理）、ours_ok 1、sensorlab 1、accepted 1、refused 0、**applied 1、to_qs 1**、goes 1；`0xC3588D68` 讀回原廠值 `0xC2DFE860`。套用後的配方：DC 6048×4040 → RES 5120×3420、key 1、29.97。

只記錄到一次成功掃描；拒絕碼、SIGMA 自己的設定碼、關閉再開 QS 是否被彈回，這次的計數看不出來（Bei 回報整體可以）。
