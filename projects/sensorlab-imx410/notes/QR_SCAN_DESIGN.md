# QR scan in QS: restore a SensorLab mode from a QR code (design, offline)

2026-11-04. Offline study only: no camera, no USB, no product-code edits. Firmware Ver.5.02.
Evidence: **[C]** = read in the decompile / image bytes (`out/decomp/full/*.c`, `out/MAIN_c0000000.bin`);
**[I]** = inference, needs a live check. Addresses are firmware addresses.

## 0. Summary

1. **The firmware already has the whole pipeline** [C]: SIGMA's own "Save / Load settings (QR)" feature
   (`Y5_CreateQR*`, `Y5_ReadQR`, `Y5_ReadQR_SaveSettings`). It has a live-view reader thread `QrReadTh`, the
   display image cropped to the centre 512×512 and turned into Y8, a decoder, result messages to observers, and a
   menu page with a detection frame, status messages and ×1/×4/×8 magnification. The shell command `qr lv_read`
   drives the same reader from outside the menu, which is the pattern a sup can copy.
2. **Blocker [C]: the stock decoder only accepts QR version 20.** `FUN_c05cb960` returns −0x1E for any
   version ≠ 20 (`if (*ver != 0x14) return -0x1e`). Codes below version 7 carry no version-info block, so they are
   treated as version 20 (the `-2` branch) and the 97×97 grid is sampled. The per-version tables
   (`FUN_c05cbdc8`/`be08`/`be30`/`be78`/`bec0`) exist only for V20 and V26. Byte capacity (`FUN_c05cbe08`) exists
   only for V20, so V26 also fails. **SensorLab's V5-L code (tile and website) cannot be read by the stock
   decoder.**
3. **Recommended design**: use the stock reader and the stock UX, and change two things:
   - **Decoder fallback (RAM-only hook)**: the reader's decoder object sits at a fixed address. Its vtable pointer
     `[0xC3588D68]` = `0xC2DFE860` [C] is RAM. Point it at our 5-word copy whose decode slot runs the stock decoder
     first, then our small **V5-L-only** decoder on the same Y8 input. Stock codes keep working unchanged. No code
     bytes are patched.
   - **Result handler**: a SensorLab URL is recognised before the stock settings parser sees it. It then gets our
     confirm and apply step, styled like the stock flow. A stock SIGMA settings code (binary, model `"C43"`) goes on
     to the stock parser and the stock "save to C1–C6" flow as before.
4. **Phase 0 needs no code**: the website also renders a **V20-L** copy of the same 87-byte URL ("for the camera").
   The stock decoder reads it today. That proves the image path, focus and magnify with zero camera code, and it is
   the cheapest live check (§7).

---

## 1. The stock QR-settings feature, end to end

### 1.1 Pages and strings [C]

| Item | Evidence |
|---|---|
| Menu sets | `Y5_CreateQR`, `Y5_CreateQR_SaveSettingsSelect`, `Y5_CreateQR_IconSetting`, `Y5_CreateQR_Preview`, `Y5_ReadQR`, `Y5_ReadQR_SaveSettings` (`research/ui/nbu_sets.json` 22/25/77/159/135/212) |
| Menu title | "Save / Load settings ⟨QR icon⟩"; rows "Save to QR Code", "Load from QR Code" |
| Read page texts | "Detecting QR code..." (footer `ReadQRFooter`), "No compatible QR code found.", "Incompatible QR code." |
| Apply / save texts | "Overwrite the ⟨QRcodeIcon⟩ settings", "⟨QRcodeIcon⟩ settings saved.", "Saved settings as ⟨C1-6⟩.", "Overwrite the system settings?" |
| UI states | `QRDetectStart`, `ProcessingErrorNoQRCode`, `ProcessingErrorNotSupported`, `ProcessingComplete` (0xC0CD31EC..), `QRCodeDetectionFrame(State)`, `ReadQR`, `ReadQRON`, `ReadQRComplete`, `ReadQRError` |
| Handlers | `MenuQrCodeReadHandler` (v72 enter 0xC0476B38, v73 exit, v8, v12 back, v29/v30 dial, v62 messages 0xC0476DF0, v70 key, v86 UI events), `MenuQrCodeSelectApplyTargetHandler` (0xC0477368..), Create / Preview / IconSetting / SelectSave |

### 1.2 Read flow (`Y5_ReadQR`, `MenuQrCodeReadHandler`) [C unless marked]

1. **Enter (v72)**: clears state (+0x2C done, +0x2D LV ready, +0x2E UI ready, +0x30 phase). Calls
   `FUN_c00173e8(1)`. Opens a settings session `FUN_c0057d38(s)`. Sets two settings items to 1 without persisting
   them (`FUN_c0059fb0(s,1,0)` = item at settings vt+0xDC, `FUN_c005a078(s,1,0)` = vt+0xE0), then commits
   (`FUN_c0058128`). Which items these are is **[I]**: probably the LV/AF state the reader wants. Read them before
   and after on the camera.
2. **Start**: reading starts once both of these have arrived: the rec-sequence message `{[0]=0,[1]=0,[3]=0xB}`
   (LV up) and the page's UI event `"QRDetectStart"` (end of its open animation). Then
   `LV = FUN_c0370cf8()` (singleton 0xC351FE88) does `SetReadMode(1)` (vt+0x84 → rec-seq msg 0x1A) and
   `ReqRead` (vt+0x88 → msg 0x1B), and the phase becomes 1.
3. **Each request** decodes one frame in thread **`QrReadTh`** (object 0xC3588D30, priority 0x1A = 26, stack
   0x2000; `FUN_c0387c68`). In detail, `QrCodeReadThread::v1` 0xC0381460:
   - requires display state `FUN_c0423e48()==3`, otherwise it replies with code 0x15;
   - gets the display YUV through `FUN_c0429560` (descriptor 0xC375C094, display channels 0..2);
   - crops from base 1024×682 the window offset (256,0), size 512×512 (`0xC0B9B200..214`);
   - `FUN_c05c4878` → `FUN_c05c48a0`: YUV→Y8 (`XC_StillYuvToY8`), work buffer 0x5C6A0 B from allocator class 0,
     decode params `{binTh 0, eMode 5, eEcc 5, work, dstLen, dst, w, h, src}` → decoder vtable +0xC
     (`XC_QrCode::v1` 0xC05C4E50 → `FUN_c05c5d00`);
   - result codes: 0 = OK, 2 = decoder −0x1E ("not supported"), 1 = anything else;
   - posts a 0x174-byte message (template 0xC0B9B224) through `FUN_c03a0c40` to all rec-sequence observers:
     `[3]` = 0 or 0x15, `[4]` = running id, `[5]` → result `{+0 result, +4..+0x10 found rect, +0x14 data, +0x18 len}`.
4. **Result (v62)**:
   - result 0: copies the data, capped at the page buffer's capacity, and runs the stock settings parser
     `FUN_c052bd38` (`XC_Recommend…`). Success → state `ProcessingComplete`, +0x2C = 1. Failure →
     `ProcessingErrorNotSupported` ("Incompatible QR code.").
   - result 1 → `ProcessingErrorNoQRCode` and **immediately `ReqRead` again**: the page scans continuously.
   - result 2 → `ProcessingErrorNotSupported`.
   - Every result also hands the found rect to the page (vt+0x644), which draws `QRCodeDetectionFrame` on the code.
5. **Magnify (v29/v30, dial)**: cycles 100 → 400 → 800 (`FUN_c0477290`). That is LV magnification ×1/×4/×8
   **[I]**, set by `FUN_c03713f0(lv, z)` (vt+0x78), with ×1 = `FUN_c0371098(lv,0)`. The value is shown via vt+0x640.
   This is how the stock feature reads a small code, for example on another fp's LCD.
6. **Confirm → save**: when done (+0x2C), OK moves to `Y5_ReadQR_SaveSettings` (`FUN_c046c320`).
   `MenuQrCodeSelectApplyTargetHandler::v86` takes target 0..6 (current mode / C1..C6, `FUN_c052bd98`) and an
   overwrite flag. `FUN_c052be40(mgr, data, target, flag)` writes the settings. The texts are "Overwrite the ⟨⟩
   settings" (confirm) and "⟨⟩ settings saved." On exit, a mode change triggers `FUN_c04bbb08`/`FUN_c04bc580`.
7. **Exit / back (v12, v73)**: in phase 1, back sends `SetReadMode(0)` and the phase becomes 2. The sequence then
   replies with the end message (`[3]=3`, `FUN_c0383860`), the phase becomes 3 and the page closes. v73 also calls
   `FUN_c00173e8(0)`, ends the settings session (`FUN_c0057da0`) and resets the magnification to 100.
   Key 0x1B (v70) re-issues `ReqRead`. **There is no timeout**: it scans until the user leaves.
8. **Record gate**: the reader runs only in display state 3. The menu is not reachable while recording.

### 1.3 Stock payload (how stock recognises its own codes) [C]

- Encoder: V20 only, byte mode, ECC L (858 B) or M (`FUN_c05c5be8`; QR_QS_RESEARCH §1.2/§6). The payload buffer
  is 0x35A B (`FUN_c052bd28`).
- **Obfuscation**: the encoder writes `data[i] + i` and the decoder always returns `data[i] − i`
  (`FUN_c05c5bc0`, called at the end of `FUN_c05c5d00`). So **any plain QR (ours) comes out of the stock decoder
  as `URL[i] − i`.** We add i back.
- Binary header, read by `FUN_c052d068`:

  | Offset | Size | Content |
  |---|---|---|
  | 0 | 16 B | name ("My Settings") |
  | 0x11 | 2 B | icon (`#M`/`#S`/`#A`/`#P` or C-slot icon) |
  | 0x14 | 3 B | model `"C43"` (0xC0B4D958) |
  | 0x18, 0x19 | 2 × u8 | version, must be ≥ 0x0107 |
  | 0x1A | 4 B | (not identified) |
  | 0x20, 0x22 | 2 × u16 | lengths, both ≤ total |

  The data follows, with ≥ 0x20 bytes required (`FUN_c052d100`). Recognition = this parse succeeding. Our URL
  fails it: the u16 at 0x20 comes out ≈ 0x454D, larger than 87, so the stock flow would say "Incompatible QR
  code." [I, by arithmetic].

---

## 2. Image source and optics

| Source | Size | Verdict |
|---|---|---|
| Detection image 0xC375D8C0 | 320×180 content (240 rows allocated), Y8 | **Too coarse.** A phone QR 40 mm wide at 30 cm with a 45 mm lens fills about 53 px, which is 1.3 px/module for V5 (41 modules with the quiet zone). The target is ≥ 3. |
| Display YUV via `FUN_c0429560` (what stock uses) | 1024×682 normalised; decode window 512×512 centre; converted to Y8 by the firmware | **Use this.** The same code is 171 px wide, about 4.2 px/module. With ×4 magnify an fp LCD tile works too: 13.3 mm at 24 cm is 71 px (1.7 px/module) at ×1 and 6.9 px/module at ×4. |
| Display ring 0x49801000 (YUYV at descriptor width) | about 1620 wide | Not needed. Reading it ourselves would bring in buffer ownership and tearing problems that the stock path already handles. |

Field width assumed: 36 mm × d / f, LV ≈ full width [I]. ×4 / ×8 come from the stock dial.

- **Ownership, cache and tearing**: the stock thread fetches and converts the frame itself, under its own mutex,
  inside `QrReadTh`. Our fallback decoder runs inside that same call, on that thread, reading the Y8 buffer the
  stock code just wrote with the CPU (cacheable) [I]. No UI-thread work, no display-ring access, no extra
  allocation: the Y8 buffer and the work buffer belong to the stock call.
- **Rate**: one decode per `ReqRead`, re-issued after each failure, so it runs as fast as decoding allows. Each
  request takes one fresh display frame.
- **Focus / exposure / flicker [I]**: contrast AF on a phone screen works with a half-press. Moiré from the screen's
  subpixels is reduced by the YUV→Y8 resample and by binarisation. Phone PWM and LCD refresh can band at short
  shutter speeds; ≥ 1/50–1/60 s is safe. The stock entry (v72) changes two settings items temporarily, possibly for
  exactly this. The live check should identify them, and our entry should copy them if we bypass the page.

## 3. Decoder

- **Reuse**: stock decoder for V20 (stock codes and the website's V20 copy). Its binarisation, finders and
  sampling are good for any version. Only the version tables and the version gate stop V5.
- **Patching the stock decoder for V5 is not recommended**: that means 6+ code patches plus V5 tables and the
  EC-26 generator, which the stock encoder also uses (QR_QS_RESEARCH §6.3).
- **Own fallback, fixed to our symbol**: V5 (37×37), ECC L, byte mode, 1 RS block (134 = 108 data + 26 EC),
  payload exactly 87 bytes with the prefix `https://ijigen.github.io/fpSup/sensor_lab_imx410/#`.
  - **Input**: the stock decode params (Y8 pointer, w, h).
  - **Binarise**: local mean over 16×16 tiles, integer, about 4 cycles/px.
  - **Finders**: 1:1:3:1:1 run scan on rows, confirmed by a column check; take the 3 best, ordered by geometry.
  - **Geometry**: affine from the 3 finder centres, refined at the single alignment pattern (30,30), then a
    homography fixed to 16.16 with the existing `udiv64` (no float, no hardware divide).
  - **Sampling**: 3×3 majority per module.
  - **Format**: read both copies; nearest of 32 BCH codewords, accepting ECC L only.
  - **Data**: unmask and read the zigzag with the encoder's own `fn[]` function-module map. `qr_encode` already
    builds it for V5, so we share it.
  - **RS**: syndromes, Berlekamp–Massey, Chien, Forney over the existing `gf_mul` (up to 13 symbol errors).
  - **Output**: in stock convention (`dst[i] = byte − i`, `len`) so every consumer sees the same thing.
  - Try a mirrored read too, and both 90° orders, which are free from the finder layout.
- **Size estimate [I]**: about 600–700 lines of C → **4–6 KB Thumb**. Table data: format list 64 B,
  alignment 1 entry.
- **CPU estimate [I]**: 512×512 = 262k px; binarise plus finder scan about 1.5–3 M cycles; RS under 0.1 M.
  That is **about 3–5 ms per frame** on the A9 when run from the cached alias (sup code run uncached is ~50×
  slower, see the memory note). It runs only after the stock decoder has failed, in `QrReadTh` (priority 26), only
  while scanning.
- **Already shipped elsewhere**: payload unpacking = inverse of `qr_pack` (base64url → 222 bits → CRC-8 0x07 →
  pad 0 → version 1 → 27 fields). The site's JS decoder (`site/mode.html`) has the same rules: reject bad CRC,
  noncanonical pad, unknown version, invalid fields.

## 4. UI flow (mirror the stock pattern)

**Recommended A: reuse the stock `Y5_ReadQR` page.**

1. **Entry**: AEL on the QR tile. Today the QR tile has no sub-QS, no fine mode and `adjust = 0`
   (`slqs.c` ~l.1981–1991), so AEL does nothing there. It would set `sl_scan = 1` and leave the QS straight into
   `Y5_ReadQR`. That is a page-data transition (`controlAppState
   "Y5_ReadQR"` on a private app variable, the same mechanism as SensorLab menu's `SLM_Go`). This **needs a
   QSContainer addition**:
   - a per-function "AEL → go to page" action (`qsc_func.go` or a `QSC_F_AEL_GO` flag with a page name);
   - the container closes the QS (leave() runs, so the record is written as usual) and posts the transition.
2. **Scan screen**: entirely stock. Live view, the detection frame on the found code, "Detecting QR code...",
   dial = magnify ×1/×4/×8, back exits.
3. **Result interception**: hook `MenuQrCodeReadHandler` vtable slot v62 (RAM vtable word, the Dial Fix way; no
   code overwrite), active only while `sl_scan` is set or always (cheap prefix test). On result 0, add i back and
   compare the 50-byte prefix:
   - **SensorLab URL with valid payload**: stop reading (`SetReadMode(0)`). Show the summary
     "SensorLab: DC 6048×3402 · RES 4K · 23.976 · 12b 2×2 · RS 10.6 ms" using the page's message line (a private
     FSPL string via uishare, or the `ProcessingComplete` state with our text). Footer: "OK: apply · MENU: cancel".
   - **SensorLab URL but bad CRC / version / fields**: say "SensorLab code not valid for this version" and keep
     scanning.
   - **Anything else**: call the stock v62, so stock SIGMA codes work exactly as before and other codes say
     "Incompatible QR code.".
4. **Confirm**: OK applies (§5), shows "SensorLab settings applied.", then returns to LV/QS. This mirrors
   "Overwrite…?" → "…saved.", without the C1–C6 target page, because SensorLab has one selection.
5. **Exit**: MENU / back / half-press → stock exit path; `sl_scan = 0`.

**Fallback B (no stock page)**: scan inside the QS. The client drives the reader like `qr lv_read` does:
`FUN_c0371598(lv, obs)` (observer `{vt: v0 dtor, v1 notify}`; v1 accepts `[0]==2 && [3]<3`), `SetReadMode(1)`,
`ReqRead` per result, `SetReadMode(0)` + `FUN_c03715c8` on exit. It needs container additions:
- "panel hidden" mode, because the QS tiles cover y 77..539 of the LV;
- a status line;
- a guide box, drawn by our DrawingObserver as the QR tile already does.

More UI work and less stock-like. Keep it as plan B if the page transition proves fragile.

**Blocked states**:
- recording: the tile is already `QSC_F_LOCK_REC`, and the stock reader needs display state 3;
- playback: the QS is not reachable;
- also refuse when `busy()` or `state() != 0`.

## 5. Apply path

- **Decoded fields → `struct sel`**:
  - DC: `dcw`, `dch`.
  - RES: `res_hit(rw,rh)` → K label or ratio; otherwise `custom` with `cw`, `ch` (the RES CUSTOM bit).
  - FPS:
    - STD pick 0..28 → that rate;
    - 30 (recipe max) → that recipe's maximum;
    - 29 → tuned: `fps = CD_CLK / (HMAX × VMAX)` as an exact rational, `fine = 1`.
  - Recipe: `rd[] = {AD, SCW, SCH, MH, MV, HB, VB}`, `rd_ok = 1`, CUSTOM bit → `rq`.
  - Kernels: `kh`, `kv`, `km`.
- **Verify**: recompute with the camera's own core (`cell_now`, `cur_recipe`). Compare the payload's derived
  fields with the recomputed recipe: HMAX, VMAX, readout key, visible w×h, RS µs, sensor crop, ISP window.
  - **Exact**: apply silently.
  - **Different** (another SensorLab / core_data version, or a recipe the current planner does not produce):
    show the differences ("FPS 23.976 → 23.981", "visible 6000×3376 → 6016×3384"). OK applies the nearest; the
    summary marks it yellow, like `QSC_T_APPROX`.
  - Key index out of range, or no recipe at all → "Not available in this version", nothing applied.
- **Commit**: `st->dirty = 1; sq_push(st)` (outside recording). The record is written by the normal `leave()`
  `rec_write` on the next layout load, which the return to QS causes. No new write path.
- **Format**: always DNG today. The MOV bit is ignored, with a note.

## 6. Risks

| Risk | Handling |
|---|---|
| **Version gate** (V5 not decodable by stock) | Phase 0: V20 copy on the site; Phase 3: own V5 fallback |
| RAM vtable redirect `[0xC3588D68]` | Write it only while scanning and restore it on exit. Verify the old value is `0xC2DFE860` before writing. The object is a static singleton [C] |
| v62 hook vs other sups | Chain: call the saved stock pointer for anything that is not ours |
| CPU on LV | Stock already decodes every frame while on the page. Our fallback adds 3–5 ms only after a stock miss, only on that page |
| Memory | All of it is the stock per-call allocations (Y8 + 0x5C6A0 work, class 0). The fallback needs about 3 KB of stack, and `QrReadTh` has 8 KB [I: measure headroom]. Or a small static scratch inside the BIN |
| Recording / playback | Not reachable (QS lock, reader state 3). Never call `SetReadMode` while recording ([[no-usb-during-rec-or-playback]] spirit) |
| The two stock settings items forced on entry | Identify before relying on them (Phase 1) |
| Pool allocator globals shared with the encoder (0xC37CE9B8..) | Our encoder is our own (V5), so there is no conflict |

## 7. Phased plan

**Phase 0: live checks with zero code** (USB shell, LV standby, not recording):
1. `qr decode_log` (log on) and `qr dump_y8` (optional: saves the decoder's Y8 input) [I: where it is written].
2. A phone shows a **V20-L** QR of a real SensorLab URL. Run `qr lv_read`. Expect: `id`, `result = 0`, a rect,
   and a hex dump equal to `URL[i] − i`.
3. Same with today's **V5** code (phone and an fp tile). Expect: result 1 or 2, which confirms the gate live.
4. In the stock menu, run "Load from QR Code" on the V20 copy. Expect "Incompatible QR code." (stock untouched).
   Try ×4/×8 on an fp tile.
5. Keep the dumped Y8 frames as the host decoder's test set (real optics, real moiré).

**Phase 1: offline**:
- Host C build of the V5 fallback decoder (same source as the sup, no libc).
- Test set:
  - frames rendered from our encoder at 2–6 px/module with blur, noise, perspective and gamma;
  - Phase 0 dumps;
  - mutation tests: drop RS, wrong mask, mirrored.
- Unicorn: run the hook dispatcher against the real image with the stock decoder.
- Payload unpack ↔ `qr_pack` round trip over the 837 presets and random payloads (shared with `test_site.py`).
- Also identify the v72 settings items.

**Phase 2: site**: add a "for the camera" V20-L rendering of the same URL. Any JS QR library with a forced
version, or a WASM build of an encoder.

**Phase 3: camera**:
- QR-tile AEL → `Y5_ReadQR` (container addition);
- v62 hook + SensorLab confirm/apply;
- decoder vtable redirect with the V5 fallback.
- Live: phone V20, phone V5, fp-to-fp V5 at ×4, stock SIGMA code still saved to C1, exit paths, and no change
  while recording.

## 8. Open questions for Bei

1. Is it acceptable to enter the stock "Load from QR Code" page (stock look, stock texts) from the QR tile, or must
   scanning stay inside the QS panel (plan B)?
2. Phase 2 (website V20 copy) as a first product step before the own V5 decoder? It covers website → camera,
   but not fp → fp.
3. When a restored mode differs from the code (another version), apply the nearest with a yellow note, or refuse?

---

## 9. Bei's decisions (2026-11-04)

1. **Route A**: AEL on the QR tile opens SIGMA's `Y5_ReadQR` page.
2. **Own V5 decoder**. No website V20 copy.
3. **Refuse** when the recomputed recipe differs from the code's derived fields. Show why; never apply the
   nearest.

## 10. Phase 1 result: the V5-L decoder (offline, host + Thumb under unicorn)

### 10.1 Files

| File | Role |
|---|---|
| `qs/qrdec.c` | The decoder, sup C. No libc, no float, no `/`/`%` on variables (a CLZ shift-subtract `qd_div`). It reuses slqs.c's `gf_mul`, `mask_bit`, the QR defines, payload tables and the encoder's function map `fn[]`. Not yet `#include`d by slqs.c, so the BIN is unchanged. |
| `qs/qrdec_unit.py` | Builds one unit out of the real files: core.c `udiv64`, slqs.c helpers / defines / `qr_pack` / the whole encoder section (cut from the source, never retyped), and `qrdec.c`. Host build via ctypes; Thumb build with the sup CFLAGS + `build_slqs.link_flat` (no load-time relocation). |
| `qs/test_qrdec.py` | The suite, `--rates`, `--count`, `--mutate`. |
| `validation/20261104-qr-scan-design/` | `rates.json`, `floors.json`, `instructions.json`, `mutants.log`. |

### 10.2 How it works (`qrdec.c` header)

- **Threshold**: 16-px block min/max/mean, then the local **mean** over 5×5 blocks. Low contrast falls back to the
  global threshold. The first version used the midpoint and lost glare and low-contrast frames to a bright or dark
  surround: at 40 codes, glare160@4 went 0.28 → 1.00 and lowc40@5 0.00 → 0.65.
- **Finders**: 1:1:3:1:1 run scan on every 2nd row, confirmed down the column and again along the row. Sightings
  merge only when they have the same module size: a scene blob once swallowed the BL finder.
- **Triple**: right angle ±15°, sides within 1:2, and 20–40 modules long.
- **Alignment**: the pattern is searched around its affine prediction, scored on 25 modules.
- **Homography**: 4 points (3 finders + alignment), integer homogeneous, square→quad twice + adjugate.
  M is kept to 2⁴⁰. Normalising it to 2²⁴ rounded the perspective row away, and every alignment-refined read
  failed until fixed.
- **Sampling**: 37×37 module centres, then a finder/timing misfit check. A 5-point majority measured no gain
  in any cell and was removed.
- **One pixel test** (`qd_bit`) is shared by the row scan and every other read.
- **Format**: nearest of the 32 BCH words over both copies, ECC L only, distance ≤ 3.
- **Data**: unmask + the encoder's zigzag.
- **RS**: Berlekamp–Massey, Chien, Forney (first root α⁰), t = 13, re-syndrome after correction.
- **Segment**: byte mode only. A mirrored symbol is retried transposed.
- **Payload**: `qrd_sensorlab(bytes, len, stock, code)` accepts exactly `QR_URL` + 37 base64url characters, with
  `stock=1` adding i back (the stock decoder's `byte − i`). `qrd_to_stock()` converts our output to that
  convention. `qr_unpack()` is the inverse of `qr_pack`: CRC, pad bit, version 1.

### 10.3 Measured

- **Codes**: the 837 preset recipes (built from the site data as `site/test_site.py` does) + 300 random payloads,
  encoded by the extracted slqs.c encoder. One test checks the extracted encoder against the built sup in unicorn.
- **Image**: 512×512 Y8 like the stock reader's input, over a textured scene with hard-edged confusers, 2-module
  quiet zone (the tile's).
- **Clean, 4 px/module**: all 1 137 codes decode.

Decode rate, 100 codes per cell (`rates.json`). **0 wrong payloads in all cells.**

| condition | 3 px | 4 px | 5 px | 6 px | 8 px |
|---|---|---|---|---|---|
| clean | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| rotation +10° | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| rotation −10° | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| perspective ±6 % corners | 0.99 | 1.00 | 1.00 | 1.00 | 1.00 |
| blur σ0.8 px | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| blur σ1.4 px | 0.27 | 0.88 | 1.00 | 1.00 | 1.00 |
| noise σ10 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| noise σ20 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| contrast 90..160 | 0.94 | 0.99 | 1.00 | 0.98 | 0.99 |
| glare +110 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| combined (rot 7°, persp 4 %, blur 0.9, noise 8, 60..200, glare 60) | 0.73 | 1.00 | 1.00 | 1.00 | 1.00 |
| stress: blur σ2.0 | 0.00 | 0.00 | 0.96 | 0.99 | 1.00 |
| stress: noise σ30 | 0.95 | 0.96 | 0.98 | 0.95 | 0.94 |
| stress: perspective ±10 % | 0.85 | 0.93 | 0.96 | 0.96 | 0.94 |
| stress: glare +160 | 0.98 | 1.00 | 1.00 | 1.00 | 1.00 |
| stress: contrast 110..150 | 0.36 | 0.57 | 0.68 | 0.82 | 0.86 |
| stress: all at once (rot 10, persp 6 %, blur 1.4, noise 15, 80..180, glare 100) | 0.00 | 0.00 | 0.13 | 0.33 | 0.54 |

**Reading the table**:
- Every condition in the brief is ≥ 0.9 from 4 px/module up, except blur σ1.4 at 3–4 px.
- 3 px/module (the brief's minimum) loses under blur and the combined case. The camera has ×4/×8 magnify for that.
- Stress cells (blur σ2 at ≤ 4 px, 40-level contrast, `hard`) mark the limits; they are not targets.
- None of this is optical: phone screens, moiré and the stock Y8 resample are unverified until §7's live check.

**Cost**, Thumb, `-O2` sup flags, unicorn instruction count per 512×512 frame (`instructions.json`):
- 7.7–8.6 M instructions per decode;
- about 6.8 M of that is spent even with no code in view: 3.7 M block statistics + 3.2 M row scan.
- At ~1 instruction/cycle that is about 10 ms per frame at 800 MHz [I: the fp's A9 clock is not measured here].
- Scanning every 2nd row (instead of every row) cut 12.0 M → 8.5 M with no measured loss at ≥ 4 px/module.
- It runs only after the stock decoder misses, in `QrReadTh`, while the scan page is open.
- The host build and the Thumb build give identical results on every counted frame.

**Size**: about 11 KB Thumb, including about 0.4 KB of test exports. That is above the 4–6 KB estimate; the
64-bit homography arithmetic is inlined. Mind the slqs.c movw/movt ±32 KiB cliff when it is included: keep
`qrd_decode` `noinline` and next to its callers.

### 10.4 Tests and mutants

**Suite** (`python3 -B test_qrdec.py`):
- pack/unpack round trip = test_slqs's Python reference;
- every single-bit flip of a code is rejected;
- pad, version and character errors rejected;
- SensorLab check, plain and stock convention (prefix, length, charset; a `C43` stock header is not ours);
- RS corrects every 0..13-error pattern (20 each) against an independent Python encoder. With 14..29 errors it
  either fails or yields a valid codeword, and the CRC then catches it;
- all 1 137 codes clean;
- mirrored symbol;
- rate floors (`floors.json` = the seed-3 measurement −0.10);
- no decode on scene-only frames or on V3/V4/V20/V26 renders (`tools/qr/*.png`);
- extracted encoder = the built sup's matrix;
- format: either copy alone reads at distance 0 (8 masks), and ECC M/Q/H words are refused;
- byte mode only: the same symbol re-placed with a numeric or alphanumeric header is refused (control: byte mode
  re-placed = the encoder's matrix);
- finder ratio unit cases;
- white box: the C binarisation equals an independent NumPy recomputation (5×5 block mean, contrast fallback),
  and the row-scan pattern count equals an independent run-length count on that binarisation.

**Mutants** (`--mutate`): **18 of 18 caught** (`mutants.log`). They cover RS, Forney, format order and ECC, threshold, block mean, alignment, mirror, zigzag, byte mode, the stock `−i` quirk, prefix, pad, the pixel test, the row-scan bypass, the merge size rule, the mirror result and the finder ratio. The suite is 13 tests, all passing (`suite.log`).

Mutants dropped as equivalent or redundant:
- "RS accepts without re-check": with Chien limited to the 134 real positions and `found == L ≤ 13`, the corrected
  word is a codeword. The re-syndrome stays as a guard.
- "no majority samples": the feature was removed instead.

## 11. Phase 3 plan: from design to code (implemented offline 2026-11-04: SensorLab v0.7.32test + QSContainer v0.3.7, validation/20261104-qr-scan-build; not tested live)

### 11.1 Hook points (all RAM words, no code bytes changed)

1. **Decoder fallback.**
   - The `QrReadTh` object is 0xC3588D30 (`FUN_c0381420`). Its `XC_QrCode` sits at +0x14 = 0xC3588D44, and its
     vtable word is **0xC3588D68 = 0xC2DFE860** [C: `FUN_c0387c68` copies 0xC0B9B19C.., the last word
     0xC2DFE860].
   - The stock vtable is `{0, 0xC2DFE88C, 0xC05C4640 dtor, 0xC05C4E50 decode, 1}`.
   - Our copy in the sup state is the same, with slot 3 = `sl_qr_dec | 1`.
   - **Arm**: in v72 (page entry) only if the word reads 0xC2DFE860, and before `SetReadMode(1)`.
   - **Disarm**: in v73 (exit) and in every `leave()`. Restore only if it still holds our copy.
   - `sl_qr_dec(obj, mode, p)` calls the stock decoder first. On a nonzero return it runs
     `qrd_decode(src=[p+0x20], w=[p+0x18], h=[p+0x1C], stride=w, st->qr.fn)`. On success it writes
     `qrd_to_stock(bytes)` into `[p+0x14]` (capacity 0x35A), the length into `[p+0x10]`, version 5 into `p+1`,
     and returns 0.
   - The param offsets come from `FUN_c05c49f0`'s locals [C]. Prove them in unicorn on the real `FUN_c05c48a0`
     with a Y8 frame before relying on them.
   - The work struct `struct qrd` (~8 KB) lives in the sup state, not on the 8 KiB `QrReadTh` stack.
   - The `fn` map comes from `st->qr.fn`. It is valid once `q->n == QR_N`; otherwise run `qr_encode` once on the UI
     thread when arming.
2. **Result handler.** `MenuQrCodeReadHandler` vtable base **0xC0CD35C4** (unique hits [C]):
   - v8 = +0x20 → 0xC0CD35E4;
   - v62 = +0xF8 → **0xC0CD36BC** (= 0xC0476DF0);
   - v72 = 0xC0CD36E4;
   - v73 = 0xC0CD36E8.

   Wrap v62. For a message `[0]==2, [3]==0` whose result `+0 == 0` and where
   `qrd_sensorlab([res+0x14], [res+0x18], 1)` matches:
   - `qr_unpack` → §11.3;
   - `SetReadMode(0)` (stop scanning);
   - post our message (summary, or the refusal reason);
   - remember `pending`.

   Anything else goes to the stock v62 unchanged, so SIGMA codes work as before. Wrap v8 (OK): with `pending`,
   apply and leave the page by the stock back path instead of `Y5_ReadQR_SaveSettings`. Install the wrappers at
   boot (vtable words, the Dial Fix way) or only around AEL; restore the old words on unload.
3. **Message text.** The page shows states such as `ProcessingComplete` and `ProcessingErrorNotSupported`. Ours is
   a private FSPL string through uishare, shown while `pending` (summary + "OK: apply", or the reason). Check
   [I] that the page's message object takes a text variable; otherwise draw with the OSD text path
   (osd-persistent-marker).
4. **QSContainer: AEL → open a page** (another sup; coordinate before coding):
   - a new API version adds `qsc_func.page` (a stock page name) or `QSC_F_AEL_PAGE`;
   - AEL on that tile makes the container close the QS (`leave()` runs, so the record is saved) and post a private
     app variable;
   - a page-data `appVariableEvent` → `controlAppState "Y5_ReadQR"` does the transition, like the existing `Menu`
     keyEvent / `SLM_Go`;
   - older containers ignore the field (the tile then has no AEL).
   - SensorLab sets it on F_QR. The QR tile still has `adjust = 0` and no sub-QS.

### 11.2 Gates

Scanning is not entered when any of these holds:
- `busy()` (recording), or the QS lock;
- the stock reader not in display state 3 (it replies 0x15);
- the decoder vtable word holds an unknown value: then run stock only, and log it;
- playback.

### 11.3 Apply or refuse (decision 3)

1. `qr_unpack`: CRC, pad, version 1, MOV bit (`fmt` = 1 → refuse "MOV not supported").
2. Build a candidate `struct sel` on a copy:
   - DC;
   - RES: K / ratio entry via `res_hit`, or CUSTOM `cw`, `ch`;
   - FPS: STD index / recipe maximum / tuned (`fine`, CD_CLK ÷ (HMAX × VMAX) as a rational);
   - recipe: `rd[] = {AD, SCW, SCH, MH, MV, HB, VB}`, `rd_ok`, `rq` of the matching recipe;
   - kernels `kh kv km`.
3. **Exact check = `qr_fields(candidate) == the 27 decoded fields`.** This reuses the same function that made the
   code, so HMAX, VMAX, key, visible w×h, RS µs, crop and ISP window are all compared.
4. Any differing field → **refuse**, naming the first differing fields ("VMAX 1201 ≠ 1203", "readout key 5 ≠ 7",
   "visible 2000×1124 ≠ 2016×1134"). The selection is untouched.
5. Equal → `st->s = candidate; st->dirty = 1; sq_push(st)`. The record is written by the normal `leave()` when the
   page returns to the QS.

### 11.4 Tests to write (phase 3)

**Unicorn, the built SensorLab sup:**
- New `sq_test` op "restore from code".
- For all 837 presets + tuned FPS + RES CUSTOM: boot A → set → code; boot B → restore → `qr_fields` equal and
  `ap_last` equal to A's.
- Refusals with a reason for:
  - each single-field edit that the planner cannot reproduce;
  - version 2;
  - MOV;
  - while `busy()`.
- Mutants: skip the compare, wrong field order, apply on mismatch, write the record per scan.

**Hook wrappers against the real image:**
- `sl_qr_dec` with the real `FUN_c05c48a0` and stock decoder on a Y8 frame:
  - a V5 SensorLab frame → stock misses, ours fills the stock buffer in the `byte − i` convention;
  - a V20 frame → stock decodes, ours never runs.
- v62 wrapper: a SensorLab result → ours; a stock SIGMA header (`C43`) → stock path, unchanged; random → stock
  "Incompatible".
- Arm/disarm restores both words, refuses an unknown old value, and `leave()` disarms.
- Mutants: no disarm, skipped stock-first, missing `+i`.

**Container (its own repo tests):** AEL → page variable only on tiles with `page`; old API ignores it.

**Live, phase 4**, after the §7 zero-code checks:
- phone V5 at 15/30/40 cm, ×1/×4;
- fp → fp tile at ×4;
- a SIGMA code still saves to C1;
- MENU / half-press exits;
- nothing while recording.
