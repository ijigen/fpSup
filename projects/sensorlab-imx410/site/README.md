# SensorLab page (simulator + camera QR landing)

One page. `build_site.py` generates `fpSup/sensor_lab_imx410/` from the simulator sources in `../preview/`:
`index.html` is `preview/dcres.html` (plus the WebAssembly adapter script), with `site_page.js`,
`simulator.js`, `fps_data.js`, the engine (`wasm_backend.js`, `sensorlab.wasm`, `wasm_info.json`) and
`assets/` beside it. `simulator/index.html` only redirects to `../`, keeping the hash, so old links work.
This script does not publish.

The camera's QR URL is unchanged: `https://ijigen.github.io/fpSup/sensor_lab_imx410/#<37 chars>`.

- **`#<code>`**: decoded (213 data bits, CRC-8 0x07, one zero pad bit, base64url without `=`; fields =
  `qs/slqs.c` "QR" / `N_QF`). DC, RES and kernels are set at once; FPS and the recipe are matched by identity
  (HMAX, readout key, ADC, sensor/ISP bins, sensor crop, ISP window) once that DC × RES cell's recipes exist.
  The page then re-encodes the simulator state; any field that differs from the code is listed in a visible
  note, and the details keep the camera's values. A bad length, characters, CRC, padding, version or an
  out-of-range field shows a clear error and the default simulator.
- **Changes** rewrite the hash with `history.replaceState` (no history entries) using the page's `qrPack`
  (bit-identical to the camera's `qr_pack`, tested against `qs/test_slqs.py`'s reference); the QS QR tile
  shows the same code. Loading a code never rewrites the address; no hash = the plain default view.
- **Details** (from the code): frame diagram, sensor binning, ISP kernel, ADC vs recorded DNG depth, sizes,
  rolling shutter, data rates. The frame diagram uses ONE scale for every stage: each solid box is that stage's
  pixel grid (sensor px, sensor crop, binned px, ISP window in binned px, recorded px), centred in the previous
  stage where the camera puts it, so a later stage is never bigger and a crop shows as a smaller box inside.
  Stages: sensor (6064×4040, the widest native line) → ① readout, what the sensor actually sends: its native
  line width fmt_w (× bin) and the rows it reads, windowed at the real start row or full height, from the C core's
  readout plan (`host_bridge.c preview_readout`, via WebAssembly `wasm_readout` or the local server's
  `/api/readout`; never recomputed in JS, marked pending until it arrives) → ② DC crop scw×sch by the SoC receiver
  → ③ sensor bin → ④ ISP DC → ⑤ recording. The legend says which part the sensor, the receiver or the ISP does.
  A stage the same size as its parent is drawn 3 px inset and keyed "same size". Crops (sensor → DC, binned
  frame → ISP DC) are just the smaller box inside; deformations (sensor binning, ISP scale) get dashed
  connectors in that step's key colour: none if nothing changes, one line at the middle of each changed side if
  one axis changes, corner to corner if both change; each line ends in an arrowhead of its colour 2.5 px short of
  the result box. Labels
  are a colour key under the drawing, so no line crosses them. Recorded depth follows the current QS
  `rec_bits` policy; zoom is reconstructed as in `core.c` `q_isp`. For the current selection the data rates
  are the MB/s tile's own estimate; for a code the simulator cannot reproduce, the code-only estimate.
- **Layout**: desktop two columns, details left and the simulator right (sticky when the viewport is tall
  enough); below 900 px one column: summary, diagram, simulator, binning/kernel, speed and data. Changing a
  setting never moves a section or the scroll position: fixed drawing box, fixed-width chips, reserved
  heights for text that varies, the notice/details keep their space when they clear.
- **Rolling shutter in the live view**: the background scene leans as a horizontal pan would make it (static, no
  animation): the bottom row is shifted v × RS frame widths against the top, RS = the current recipe's readout time,
  v = pan speed (off / slow 1 / fast 4 frame widths per second, saved as `sl410-pan`). "Compare with stock FHD" adds
  the stock 10.556 ms lean as dashed lines. Formula and numbers are shown under the screen (EN/简/繁).
- **Screen (website only)**: on the main QS the QR tile is drawn bottom-right and WB takes its cell (the camera's
  order and the spec logic are unchanged; tiles keep their logical index). The QS panel is lighter (alpha .6 vs the
  camera's .86) with a soft text shadow; white value text stays ≥ 5:1 over the brightest scene pixel.
- **Controls**: click/tap and wheel only, no keypad. A tile click selects it, a second click (or the AEL
  chip) opens more options, the chip goes back; ◀ ▶ on the selected tile or the wheel step it, « » on numeric
  footers or Shift+wheel step ten; an option click applies; the QS chip opens/closes the Quick Set. Keyboard
  shortcuts remain as unlisted extras.
- **Languages**: English by default regardless of browser language; EN / 简 / 繁 is saved as `sl410-lang`.
  Everything outside the simulated camera screen is translated, including the side panel and the engine
  status. The QS tiles keep the camera's own English labels; the AEL/MENU hint is localised.

The spec logic in `dcres.html` (before `// ---- render`, and the input handlers) is unchanged:
`qs/preview_runner.js`, `menu/page_lists.js` and `preview/gen_fps.py` still read it. `site_page.js` only
reads its globals at call time.

From the repository root:

```sh
python3 -B projects/sensorlab-imx410/site/build_site.py           # write fpSup/sensor_lab_imx410/
python3 -B projects/sensorlab-imx410/site/build_site.py --check   # fail if the local copy differs
python3 -B -m unittest discover -s projects/sensorlab-imx410/site -p test_site.py -v
node --test projects/sensorlab-imx410/preview/test_client.js
node --test projects/sensorlab-imx410/preview/test_layout.js   # real headless Chrome; skips without Chrome
```

`--simulator` is still accepted (the simulator is always built). `--out` can target an isolated
publication checkout; the build removes the former `simulator/*` engine files and `--check` fails while
any remain. Building needs a wasm32-capable clang and `wasm-ld` (see `preview/build_web.py`).

Tests: `test_site.py` checks the schema against `slqs.c`, decode/encode against the camera reference for
random payloads, every error class, zoom / recorded depth / raster for all 837 preset recipes, data
rates, complete translations, the redirect, and that the publication copy equals the generated output.
`preview/test_client.js` runs the real page scripts: every preset recipe state → code → page loaded from
that code is the identical selection; random payloads; replaceState-only address updates; invalid codes in
three languages; language switching; every former keypad action reproduced by click/tap/wheel; and the frame
diagram (shared scale, real centred positions, no identical outlines, the 0 / 2-midpoint / 4-corner connector
rule, one arrowhead per connector at the result end along the line, no connector on a box edge, key never crossed or clipped, one fixed drawing box, back-to-front order) over all presets and extreme custom sizes in three languages, with a
mutation check; the rolling-shutter lean for every preset at off/slow/fast (bottom-row shift within 1 px of v × RS ×
width, stock compare at 10.556 ms, with a mutation check); the screen's tile order. `test_site.py` also checks the
panel contrast and that no translation key is defined twice. `preview/test_layout.js` opens the generated copy in headless Chrome at 360 and 1280 px and
makes 50 setting changes per width and start page (no hash / a camera code), requiring every section box to stay
within 1 px and the scroll position to stay put (with a mutation check). Browser
screenshots: `validation/20261104-site-merge/`. The former standalone mode viewer is archived there as
`before/mode.html`.
