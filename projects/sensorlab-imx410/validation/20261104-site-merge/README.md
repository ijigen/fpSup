# 2026-11-04 — simulator and QR page merged into one page

Local copy `fpSup/sensor_lab_imx410/` served with `python3 -m http.server` on 127.0.0.1; screenshots by
headless Chrome over CDP (`shoot.js`, CSS width 360 = phone at 2x, 1280 = desktop). Every shot also
measured `document.documentElement.scrollWidth`: equal to the viewport (no horizontal scroll) at 360 and
1280 in all cases. No script errors. Dark mode unless the name says `light`. Nothing was published.

`before/` — the pages as they were:
- `mode.html` — the former mode viewer source (`site/mode.html`, now retired; its decoder, details and
  translations moved to `preview/site_page.js`).
- `viewer-valid-{360,1280}.png` — old viewer, code `G9B-QvQfkGKTgOPlCKxIvAfUMpAXoPyL0D7zI` (FIRST_FRAME_PURPLE).
- `viewer-tinyres-{360,1280}.png` — old viewer, synthetic code OG → 256×144, 3×3 (dashed corner lines cross).
- `simulator-{360,1280}.png` — old standalone simulator (Chrome CLI capture; the 360 one may be cropped by
  the CLI's minimum window width).

`after/` (final: shared-scale overlay diagram with 0/2/4 deformation connectors, no keypad, simulator right on desktop,
phone order summary → diagram → simulator → details, no layout shift):
- `b-valid-slowpan-*` — the valid code with the default slow pan: the scene leans by RS 25.89 ms × 1 width/s = 2.59 %
  of width; QR bottom-right, lighter QS panel.
- `g-compare-stock-*` — plus "Compare with stock FHD" (dashed, 10.556 ms → 1.06 %); `g-compare-stock-fast-1280` at
  4 widths/s (10.36 % vs 4.22 %).
- `h-dc5040-readout6064-*` — DC 5040×3402 → 1680×1134 (custom): the 3×3 readout sends whole 2016-px lines (6048
  sensor px) windowed to 3402 rows; the receiver cuts the 5040 crop. `i-s35-windowed-*` — S35: windowed readout.
- `a-nohash-*` — no hash: simulator default, no address change.
- `b-valid-hant-360`, `b-valid-light-360` — the camera code above loaded into the simulator (OG, 3024×2020, 14b 1×2, 29.97), details
  Diagram: DC = sensor (inset, "same size"), the 1×2 binned frame half height inside it (yellow dashed top/bottom
  middles: height only), ISP window, the 2:1 recording (blue dashed left/right middles: width only). `b-valid-hant-360` Traditional Chinese, `b-valid-light-360` light.
- `c-invalid-*` — the same code with the last character changed: "checksum mismatch" error, default simulator.
- `d-simulator-alias-360` — `simulator/#code` redirected to `../#code` (same page and code).
- `e-edited-1280` — after clicking the RES tile and tapping its ◀ twice (real DOM clicks): the address became
  `#G9B-QPwKgGKTgOPlCKxIPgKUMpAXoPyL0D7zK`.
- `f-tinyres-*` — the synthetic OG → 256×144 code: the simulator cannot reproduce that recipe, so the page lists
  each differing field and the details keep the camera's values; the diagram shows the tiny recording as a small
  box centred in the sensor at true scale.

Tests at the time: `site/test-results.log` (9 python + 14 node incl. the headless-Chrome layout test, all pass), `preview` python suites
(test_server, test_web: 12 pass), `menu/test_menu.py` 15 pass, `qs/test_slqs.py -k page` 1 pass, and
`qs/preview_runner.js` output byte-identical for the old and new `dcres.html` on a 19-key sequence.
