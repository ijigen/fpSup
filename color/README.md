# color

Render a SIGMA fp DNG through the camera's own colour modes, from the camera's
own numbers. This is the reference implementation of what
[`docs/COLOR_MODES.md`](../docs/COLOR_MODES.md) decodes — short enough to read
beside the document, not a converter.

用相機自己的數值,把 SIGMA fp 的 DNG 依照機內色彩模式算出來。這是
[`docs/COLOR_MODES.md`](../docs/COLOR_MODES.md) 所解出管線的參考實作 ——
刻意寫得短,方便對照文件閱讀,不是一套轉檔工具。

| file | what it is |
|---|---|
| `render_dng.py` | The whole pipeline in one file: MakerNote reader, raw decode, the five colour stages, and a CLI<br>整條管線都在這一個檔案裡:MakerNote 讀取、RAW 解碼、五個色彩階段,以及命令列介面 |

## Use it

```
pip install rawpy numpy Pillow

./render_dng.py shot.DNG                     # Standard -> shot_Standard.png
./render_dng.py shot.DNG --mode Vivid
./render_dng.py shot.DNG --mode all          # every mode the file carries
./render_dng.py shot.DNG --mode all --half   # half-size decode, about 4x faster
./render_dng.py shot.DNG --list              # what this file carries, then exit
```

Modes: `Standard`, `Vivid`, `Neutral`, `Portrait`, `Landscape`, `Cinematic`,
`TealAndOrange`, `SunsetRed`, `ForestGreen`, `FOVClassicBlue`,
`FOVClassicYellow`, `Monochrome`, `PowderBlue`, `WarmGold`, `OFF`.

## Why it needs almost nothing

**Every fp DNG carries the colour pipeline its ISP ran on**, as floats in the
Sigma MakerNote. Tag 292 holds the sixteen runtime 3x3 mode matrices, 297 the
sixteen YCbCr matrices, 299 the 24-bin hue tables and 301 sixteen 128-point tone
curves. So the script reads the look out of the file you give it, and needs no
firmware image for fourteen of the fifteen modes.

每一張 fp 的 DNG 都帶著 ISP 當時實際使用的色彩管線,以浮點數存在 Sigma
MakerNote 裡:tag 292 是十六組 3x3 模式矩陣,297 是十六組 YCbCr 矩陣,
299 是 24 格色相表,301 是十六條 128 點色調曲線。所以本腳本直接從你給的檔案
讀出 look,十五個模式裡有十四個完全不需要韌體映像。

The chain, in the camera's order:

```
raw -> linear ProPhoto        the DNG's own ColorMatrix2 and AsShotNeutral
    -> FRONT                  one measured 3x3
    -> mode matrix            tag 292
    -> tone curve, per channel tag 301, then an sRGB encode
    -> YC matrix              tag 297, into the mode's own chroma plane
    -> rotate and scale       tag 299, 24 bins from 285 degrees
    -> back through Rec.601   which is how a JPEG's Y, Cb, Cr are read
```

## The three things to know before trusting it

**One measured constant.** `FRONT` is the transform from this script's linear
decode to the camera's linear front end. It is measured rather than tuned: OFF's
exported matrix is the exact identity, so a render of OFF is the front end alone,
and one least squares of the OFF JPEG against the decode of the same frame fixes
it on 709,631 pixels at a 2.31 percent residual. That fit never sees any mode's
matrix, so every other mode is a prediction. Everything else in the chain is read
out of the camera.

**`FRONT` is tied to this exact decode.** It is a bridge between two pipelines,
not a property of the camera. The `rawpy` arguments in `decode_prophoto` are
pinned for that reason — change the demosaic, the output space or the
white-balance handling and `FRONT` is wrong. It was measured on one body;
`ColorMatrix1` and `ColorMatrix2` are identical in the two DNGs this project has,
which suggests they are per-model, so it should carry across fp bodies. Untested.

**Warm Gold is knowingly wrong**, at about 8 dE against the camera where every
other mode is under 2.9. The camera exports sixteen records and Warm Gold is not
among them — the preloader passes sixteen hardcoded mode ids with OFF twice and
Warm Gold never — so it falls back to deriving its matrix from the firmware
table, by a composition that is exact only for modes which keep white neutral.
Warm Gold shifts it by 0.188, and the derivation drops the red lift its name
promises. Pass `--firmware MAIN_dec.bin` to render it at all. It is left visibly
wrong rather than fitted, because the thing that would fix it is an open question
in [`docs/COLOR_MODES.md`](../docs/COLOR_MODES.md).

**Warm Gold 是已知錯誤的**,約 8 dE,其他模式都在 2.9 以下。相機只匯出十六筆
紀錄,其中沒有 Warm Gold,所以它只能從韌體表推導矩陣,而那個推導會丟掉紅色
增益。需要加 `--firmware` 才能算。這裡刻意留著錯,不做擬合。

## How close it is

| against | difference |
|---|---|
| the chain measured in `docs/COLOR_MODES.md` | mean 0.0002, 99th percentile 0.0018, worst 0.0087 |
| the camera's own JPEG, held out | 1.85 dE mean over fourteen modes, 1.38 over the thirteen exported |

The first row is this script against the reference implementation, over thirteen
modes and 2000 colours. In 8-bit terms that is a mean of 0.05 of a level, 0.5 at
the 99th percentile, and 2.2 at the very worst — Powder Blue, which has the
steepest tone curve of the fifteen.

**All of that residual is the tone curve, and none of it is the chain.** Tag 301
gives 128 points where the firmware's gamma bank has 2048, so this script
interpolates where the reference reads directly. Swap the bank curve in and the
two agree to 0.000004, which is float noise. The trade is deliberate: 128 points
out of the DNG means the script needs no firmware image.

The second row is the pipeline itself against the camera, from the document —
measured on one half of a frame and scored on the other, against a median 8.2 dE
between one camera mode and the next.

**No exposure fudge.** Those scores allowed brightness to vary by about a quarter
stop per mode when matching the camera's JPEG, to absorb decode differences. This
script applies `FRONT` as measured and nothing else, so a render may sit slightly
darker or lighter than the camera's JPEG of the same frame.

It does no sharpening, no noise reduction and no lens correction. The camera's
JPEG is barrel-corrected and its DNG is not, so the two do not lie on the same
pixels — comparing them needs the radial warp fitted and undone, which this
script does not do.

## Related

- [`docs/COLOR_MODES.md`](../docs/COLOR_MODES.md) — where every number comes from
- [`docs/PIPELINE_COVERAGE.md`](../docs/PIPELINE_COVERAGE.md) — which ISP stages are read and which are not
- [`firmware/colormode_extract.py`](../firmware/colormode_extract.py) — dumps the look tables from a firmware image
