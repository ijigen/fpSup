# color sup

[English](#english) | [繁體中文](#繁體中文)

Colour science and the DaVinci workflow.
**Status: paused — the research now covers every mode, the deliverable does not**

色彩科學與 DaVinci 工作流。**狀態:暫停 —— 研究已涵蓋所有模式,但交付物不成立**

---

## English

### Goal

Reproduce the fp's in-camera colour in post, so CinemaDNG footage matches what the
camera's own JPEG looks like.

### Proven

- **fp's colour science is fully decompiled** — the whole pipeline from sensor
  output to final colour
- **A DCTL exists that reproduces the Standard colour mode** in-pipeline inside a
  DWG/sRGB grade. The anchor constant is `k = 2.124`
- **The decode colour space turns out not to matter**, which is unintuitive but
  measured, and it removes a whole category of things not to try

### Why it is paused

The DCTL works but is **awkward to actually use**, and there is nothing packaged
that could be released — no file here is in a state where handing it to someone
would help them. Reproducing a colour and shipping a colour tool are not the same
job, and only the first one is done.

Whatever specifically makes it awkward in a real grade has not been written down.
That is the first thing to record when this is picked up again, because it is the
part that decides what the deliverable should even be.

### Not done

- Anything that could be released
- How colour mode interacts with ISO and gain

Modes other than Standard are no longer blocked on research. Every look is
extracted — matrix, 24-bin hue table and the base tone curve, see
[COLOR_MODES.md](../docs/COLOR_MODES.md). Turning them into a DCTL is the work
that remains.

### Picked back up 2026-09-09: how the modes are stored

Static work against the unpacked firmwares, see
[FIRMWARE_UNPACKING.md](../docs/FIRMWARE_UNPACKING.md). `fw_unpack.py` is now
version-generic — MAIN ends at the first trailing section header, which differs
per version, so V502's `0x175E500` was never general.

**There is no LUT support and nothing loads a colour profile from the card.**
Every `lut` match in the image is `resolution`, `absolute` or `evalution`; there
is no `.cube`, `.3dl`, `.icc` or equivalent. The complete list of paths the
firmware names on the card:

```
\AutoRun.txt   \SPP_metadata.xmp  \cine_log.txt  \mov_log.txt
\firmname.bin  \DUMP.YUV  \dump.pal  \dump.xci  \TEST.TIF
\battery.csv   \DBG_TASK.txt  \test.wav  \test.jpg  \t_rw_*.txt  \TEST*.TXT
```

All debug or firmware-update paths. **Colour modes are compiled in**, so a
custom look cannot be dropped on a card — it would have to be a firmware change.

**The mode roster** is two identical 11-entry name-pointer tables, at
`0xC0970934` and `0xC0970A1C` in V502:

```
[0] Neutral  [1] Portrait  [2] Landscape  [3] Cinematic  [4] WarmGold
[5] TealAndOrange  [6] SunsetRed  [7] ForestGreen  [8] PowderBlue
[9] FCBlue  [10] FCYellow
```

Standard, Vivid, Monochrome and DuoTone are not in these tables, so this is one
grouping rather than the whole `ColorMode` enum.

**Version archaeology confirms modes ship before they are announced.**
Unpacking the whole corpus:

| version | TealAndOrange | PowderBlue / DuoTone | WarmGold |
|---|---|---|---|
| 1.02 | **present** | absent | absent |
| 2.00 (T&O announced) | present | absent | absent |
| 2.03 | present | absent | absent |
| 3.00 | present | **present** | absent |
| 4.00 | present | present | absent |
| 5.02 | present | present | **present** |

Teal & Orange is in **Ver. 1.02**, months before Ver. 2.00 exposed it. So the
menu gates modes that already exist in the binary — the same policy-layer
pattern as `EXCL_CinemaDNGQuality` in [raw sup](raw-sup.md).

**V400 -> V502 is a clean single-mode diff**: `WarmGold` inserted at index 4,
name tables 10 -> 11 entries. That is the cheapest place to learn what a mode
consists of.

### Ruled out: the XC blocks are menu artwork, not colour data

An earlier note here said the looks are stored as `XC` container blocks, one per
colour mode. **That was wrong.** The format is now decoded and the blocks are
bitmaps. See [XC_CONTAINER.md](../docs/XC_CONTAINER.md) for the format and
[`firmware/xc_decode.py`](../firmware/xc_decode.py) for the decoder.

The two header fields that looked like an entry id and a group id are the
**bitmap width and height**. The container is the on-screen artwork of the
camera — digits, `23.98 FPS`, `1000`, `ALL-I`, icons, sliders, menu labels. The
card path `\dump.xci` that the firmware already knows is the same subsystem.

What looked like one block per colour mode is the run of 43-pixel-tall menu
labels. Decoded, they read:

| block | address (V2.03) | size | label |
|---|---|---|---|
| 10 | `0xC0DD4744` | 100 x 43 | `STD.` |
| 11 | `0xC0DD59C4` | 116 x 43 | `VIVID` |
| 12 | `0xC0DD7728` | 104 x 43 | `NTR.` |
| 13 | `0xC0DD8BB8` | 131 x 43 | `PORT.` |
| 14 | `0xC0DDA538` | 133 x 43 | `LAND.` |
| 15 | `0xC0DDC088` | 115 x 43 | `CINE.` |
| 16 | `0xC0DDD804` | 133 x 43 | `SUN R.` |
| 17 | `0xC0DDF228` | 129 x 43 | `FOR G.` |
| 18 | `0xC0DE08CC` | 127 x 43 | `FOV B.` |
| 19 | `0xC0DE1E80` | 123 x 43 | `FOV Y.` |
| 20 | `0xC0DE3388` | 144 x 43 | `MONO.` |
| 21 | `0xC0DE5670` | 97 x 43 | `T&O` |

The labels also correct the block order. It is **menu order, not enum order**.
Teal & Orange is the last block, not block 16. Block 16 is Sunset Red. The
group `B=35` that looked like a second pipeline path is the same twelve labels
at a second row height.

Two facts from the earlier note still hold, and they are now explained. The
block count tracks the mode roster across versions, because a new mode needs a
new label. V4.00 to V5.02 differs by exactly four inserted blocks and zero
modified ones, two of them the WarmGold label at both row heights. Neither fact
says anything about colour maths.

Ver 3.00 and later pack every block. The packing is still not decoded. The
sub-header carries LZ4's magic (`04 22 4D 18`) but the codec is not LZ4.

### Found: the looks, in full

Every colour mode is three static tables, one entry per mode. Format, addresses
for all six firmwares, and the extracted numbers are in
[COLOR_MODES.md](../docs/COLOR_MODES.md). The extractor is
[`firmware/colormode_extract.py`](../firmware/colormode_extract.py).

```
hue table      580 bytes  0xC0B400AC (V502)  24 hue bins x 2 x (hue, sat, val)
colour matrix   24 bytes  0xC0B3A340 (V502)  3x3, Q9 fixed point
tone curve    1028 bytes  0xC0B434E8 (V502)  128 (x, y) control points
```

Three things make the reading certain. Monochrome is saturation 0.000 in all 24
bins. OFF is the exact identity in the hue table and, point for point, in the
tone curve. The ten DuoTone matrices all decode to the same luma weights.

**Standard's tone curve is now readable** — 128 control points, and OFF gives
the identity to compare against. That is the base curve the DCTL needs:

```
0.0123 -> 0.0047   0.0989 -> 0.1403   0.2921 -> 0.5044
0.4553 -> 0.7238   0.6398 -> 0.8872   0.8732 -> 0.9902
```

**The mode ids are not the settings enum.** The internal enum grew over time and
ids above each insertion point moved up by one. Matching record contents between
consecutive firmwares gives the renaming exactly, which fixes Standard,
Monochrome, Vivid, OFF, Powder Blue (new in V3.00) and Warm Gold (new in V5.02).
Four more are confirmed from their own data: Cinematic, Teal & Orange, Sunset
Red and Forest Green. See COLOR_MODES.md for the evidence and for the five that
rest on the enum ordering alone.

Two looks are unlike the rest. **Cinematic and Teal & Orange leave saturation at
1.00 in every bin** and work only through hue rotation and the matrix. The other
nine raise saturation by about 1.4 to 1.8 on average. **Teal & Orange has no
saturation boost at all** — it is pure hue rotation, warm colours one way and
cool the other.

Three modes shift the white balance through the matrix: Warm Gold (red gain
1.188, blue 0.846), Sunset Red (red 1.127) and Cinematic (blue 0.748).

### Also found

- **The `PictureQuality` parameter list** at `0xC0B40074`, 7 entries of
  `{void *table, u32 count}`, read through the getter `0xC02D73E8` from the
  module constructor `0xC02C40B8`. Entry 0 is the hue table, entry 4 the tone
  curve. A second list at `0xC0B38ACC` holds 49 entries and is the ISP database
  the SIGSEQ path uses.
- **The tables at `0xC0B43CF0` and `0xC0B43E50` are not per colour mode.** Their
  first field runs 0 to 0x0A but the initialiser `0xC02D73F8` fills the buffers
  with the ISO ladder — 200, 250, 320, 400, 500, 640, 800 and so on. They are
  keyed on a drive or sensor mode, not on the look.
- **Tag-name table** at `0xC0B38A6C`, 8 pointers: `Jpg`, `Dng`, `HdmiRaw`,
  `Mov`, `UpdateMov`, `Cdng`, `UpdateCdng`, `JpgScreen`. These are the output
  paths, and probably what the parallel matrix tables are keyed on.
- **Mode map** at `0xC096FC50`: 11 bytes `05 06 07 0C 11 0D 09 0A 0F 08 0B`.
  It is *not* the roster-to-internal-id map — its value set has 17 and lacks 14,
  which no version's look table matches. Unidentified.

### A wrong turn worth recording

The `0xC010xxxx`/`0xC011xxxx` functions that stage ISP parameters into SIGSEQ
read source structs at `0xC2F0BB74..0xC2F0C930` — for example the RGBLMAT
applier `0xC0119230` memcpy's `0x58` bytes from `0xC2F0C080`. It looked like
those structs were static data in the file.

**They are not in the file at all.** `0xC2F0C080` is `0x15280` bytes past the
end of the image; the region is BSS. The bytes that appeared to be there were
decompression overrun — see [FIRMWARE_UNPACKING.md](../docs/FIRMWARE_UNPACKING.md).
An exhaustive search (ARM and Thumb `movw`/`movt`, literal pools, pointer
tables) found **nothing in MAIN writes `0xC2F0B000..0xC2F0D000`** either, so
those buffers are filled from somewhere outside the update container, or stay
zero.

### The colour-mode value, proven end to end

Setting **id `0x77`**, value range **0..15** (three independent `cmp #0xF`
switches confirm the range). The chain:

```
shell handler 0xC03FE100 -> 0xC0057AE8 (singleton 0xC31AC530)
  settings root 0xC31AC59C, accessor table 0xC07397D8, slot = id*4 = 0x1DC
  accessor 0xC0084850 -> property object at root + 0x828 = 0xC31ACDC4
  vtable 0xC073D954, class name "MenuItemColorMode"
  storage: id table 0xC07461DC[0x77] -> 0xC00B5FB8
```

**The live value is a `u32` at `0xC31B33E8`** (primary bank) or `0xC31B8CB0`
(alternate; selected by a flag byte at `0xC31B954C`). Both are directly
readable with `mem get` from the shell or an `AutoRun` card.

**Per-colour-mode settings** live in a 16-element array of stride 8, split
`record_base + 0x130 + n*8` (modes 0-11) and `record_base + 0x844 + n*8`
(modes 12-15) — `0xC31B33EC` and `0xC31B3B60`. Each element holds
**Effect, Contrast, Sharpness, Saturation, Toning** (ids `0x78..0x7C`), so those
five are remembered per mode.

**There are two different colour-mode enums.** The settings enum is 0..15. The
PictureQuality/metadata side uses a wider one: `0` Standard, `{1,2} + [16,23]`
Monochrome, `3` Vivid, `5..15` the eleven looks, `[24,33]` DuoTone, `36` OFF.
The conversion between them was searched for exhaustively and **not found** —
no translation table exists in any byte, halfword or word encoding, so if it
exists it is inline code.

### The mode does not reach the SIGSEQ colour registers

This is the significant negative. The ISP colour path is fully mapped —

```
StillCreate/StillRec/MovSigProcess/3A/DNG/PTP
  -> C02B8E38(cmd, pass) -> C02B97A8 -> C02BDCB8
  -> PictureQualityCommonPrePst_xz01 vtable 0xC2E38BE8
  -> Thumb packers: C0107490 (+0x0CB0 RGBLMAT), C01082C8 (+0x0E64 YCMAT),
     C010C404 (+0x1068 CUVCONT), C010C8A8 (+0x1088 CSUP), C010DF60 (+0x127C C_SAT_C)
```

— but **the colour mode is not on it.** `paramblk+0x120` is a *processing-pass*
selector (which blocks to re-stage), not a look selector. The parameter values
come from a fixed ROM database at `0xC0B38ACC`, copied into per-engine RAM DBs
by `0xC02D6C08`/`0xC02D7000`; selection inside `0xC0695178` is keyed on
`paramblk+0xFC`, a **gain/ISO key, not colour mode**. Read directly: RGBLMAT
`0xC0B390E8` is identity x0x200, YCMAT `0xC0B39118` is Rec.601.

An earlier inference here said the looks are applied by an XC processor that
consumes the `XC` blocks. **That inference is dead** — those blocks are menu
artwork. A new mode adds an XC block because it needs a menu label, not because
it carries a look.

The negative itself still stands, and it is now explained. The look is applied
before SIGSEQ, from its own per-mode tables — see the section that follows.

### A tooling caveat that matters

`callers.json` in the working directory indexes **ARM `BL` only**. It misses
every Thumb `BL`/`BLX` and every ARM `BLX`, which is why several functions
looked callerless earlier in this work. Rebuild it with all four encodings
before trusting a "no callers" result.

### Open

- **Where the look actually lives.** Not SIGSEQ, not the XC container. The next
  place to look is the descriptor tables `0xC0B43CF0` and `0xC0B43E50`: 11 modes
  x 2 variants, pointing at BSS buffers of 7 to 23 entries. Find what
  `0xC02D73F8` copies into them and where it reads from.
- The custom packing used from V3.00 onward, for the XC container. It is only
  needed for artwork, so it is low value for this project.
- `SetColorMode`'s menu handler is `0xC03FE100`, which calls `0xC005C958` to set
  and `0xC005C990` to read. That is the settings layer. **The code that reads
  the look tables is still untraced** — nothing in the image forms the address
  of the matrix table as a 32-bit constant, so it is base-plus-offset code.
- **Three hidden modes.** Ids 34, 35 and 37 have look or matrix data and no menu
  entry. Id 35 has existed since Ver 1.02 and carries Standard's matrix. Id 37
  arrived in Ver 2.00 beside OFF. Id 34 is an equal-weight greyscale matrix.
  The 1.02 Teal & Orange precedent says to check what they are.
- Which of the two variants in each hue-table bin is used, and when.

---

## 繁體中文

### 目標

在後製軟體裡重現 fp 機內的色彩表現,讓 CinemaDNG 素材能對得上機內 JPEG 的觀感。

### 已確認

- **fp 的色彩科學已完整反編譯** —— 從感光元件輸出到最終色彩的整條管線
- **有一支 DCTL 能重現 Standard 色彩模式**,在 DWG／sRGB 調色流程中以 in-pipeline 方式運作。
  關鍵參數:錨點 `k = 2.124`
- **解碼色彩空間不影響結果** —— 這點反直覺但實測如此,省掉一整類的嘗試

### 為什麼暫停

那支 DCTL 能動,但**實際用起來很難用**,而且沒有任何打包好、能釋出的東西 ——
現在的狀態就算交給別人也幫不上忙。**「重現一個顏色」和「做出一個色彩工具」是兩件事**,
完成的只有第一件。

至於在真實調色流程裡「難用」具體卡在哪,還沒有寫下來。
那是重新撿起這一項時第一件該記錄的事,因為那決定了交付物到底該長什麼樣。

### 2026-09-09 新增:所有色彩模式的資料都已取出

每個色彩模式在韌體裡是三張靜態表:3x3 色彩矩陣(Q9 定點)、24 段色相表
(每段 15 度,含色相旋轉、飽和度倍率、明度倍率),以及 128 點的基礎色調曲線。
格式、各版本位址與取出的數值見 [COLOR_MODES.md](../docs/COLOR_MODES.md),
工具是 [`firmware/colormode_extract.py`](../firmware/colormode_extract.py)。

三個證據讓判讀確定:Monochrome 的 24 段飽和度全是 0.000;OFF 的色相表與色調曲線
都是逐點的單位變換;十個 DuoTone 矩陣都還原成同一組亮度權重。

**Cinematic 與 Teal & Orange 的飽和度倍率全部是 1.00**,只靠色相旋轉與矩陣工作;
其餘九個模式平均把飽和度拉到 1.4 至 1.8。

### 未做

- 任何可以釋出的東西
- 色彩模式與 ISO／增益的交互作用

Standard 以外的模式已經不缺研究資料,缺的是把它們做成 DCTL。

---

**Notes / 相關筆記:** `COLOR_SCIENCE`, `ISO_DR_UNDERSTANDING`
