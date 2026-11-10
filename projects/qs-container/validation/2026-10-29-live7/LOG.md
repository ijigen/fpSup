# QS Container v0.2.4 + SensorLab-IMX410 v0.4.0test live test 2026-10-29 (run 7, QR)

Shots: `shots/NNNN-tag.jpg` = SS__NNNN.JPG fetched by number (`shot.sh N tag`), every one viewed. This run: 2715..2737.
Scripts: `shot.sh`, `qst7.py` (= live6 qst6.py, container v0.2.4 @C55BC8C0 unchanged), `qrstate.py` (st->qr via `mem get`:
st = C55F8200 + state_off 78720, qr = st + 47304 = 0xC5616E48), `fbgrab.py` (the 3 OSD buffers via `putfile.read_bulk`;
`read_direct` is refused for these and for the st region: `ERR win window refused code=2`), `qrdecode.py` (OpenCV, scratchpad qrenv).
Keys via `ui_drive.py`; dial `fpsh "key CMDDIAL1 1"`. No S1/S2/MOV, no recording, no MENU in a sub-QS.

## 1. Deploy — PASS
- `card_backup/fpSup_dir_before.txt`, `LOAD.LOG.before` (v0.2.4 @C55BC8C0, v0.3.0test @C55F8200).
- `fl del \fpSup\SensorLab-IMX410_v0.3.0test.BIN` OK; `v3/deploy_v3.py card/` -> `OK SensorLab-IMX410_v0.4.0test.BIN 78716 B`
  (full read-back; local sha256 9c4c19d0...). QSContainer_v0.2.4.BIN 173888 untouched.
- `ui_drive.py reboot` separately: up 11.4 s. `LOAD.LOG.boot1`: `0A C55F8200 SensorLab-IMX410_v0.4.0test.BIN`, rest unchanged
  (Stop-FX/SUPMGR moved up by the bigger block).
- Before MENU all 0; after first MENU (2716): result 0, phase 2, freeze 0, **N 7, recv 7**, qs_ready 1, qs_vars 193, fresh 1.

## 2. Editor — PASS
SYSTEM p2 (MainY2) -> 自定QS (2719). Slot 8 WB (2720) -> OK: list **39** items (2721), RIGHT:25 -> 39/39 name `QR` (2722),
OK -> slot 8 name `QR` (2723). **CINE = 58 54 55 56 57 50 59 60** (QR = 60).
Cosmetic: QR's list icon and editor tile are the borrowed DC icon (same as RECIPE/MB/s).

## 3. MB/s footer — PASS
2725: footer item 1 `UHS-II` / `91%/42%`, inside its box. Item 2 `A0 B0` / `R0 M01 S3`. Tile 210 / LL ~91.

## 4. QR tile and show — tile PASS, display FAIL
- Tile (2724, 2726): title `QR`, big `QR`, small `G9BqUfgRuQ..` (first 10 chars + `..`). Focus shows hint `AEL 更多選項`.
- AEL (2727): **nothing visible**; the screenshot is the unchanged QS panel. Client state: on 1, enc_ret 0, why 0, n 97, scale 4,
  x0 318, y0 110, shows 1, draws climbing (~hundreds/s while shown).
- Why (framebuffer dump, `fbgrab.py`): the main OSD layer 0xC3824FA8 is triple-buffered (descs C38D6DB0/CC/E8, bases
  C6200180 / C6355180 / C64AA180). DrawController: group 0 slot = our obs (count[0] = 1), group 2 slot = the GUI's observer
  C38D3D0C (count[2] = 1); groups 0 and 2 share this layer. `qr_group()` picks group 0. Our draw lands in a back buffer
  (`shots/fb-after-show1-buf0.png`: white panel + code, exactly 318..705 x 110..497, only 0xFFFF/0xF000 in the panel)
  but group 0's cycle never presents it; the displayed buffer is the GUI's (`fb-after-show1-buf2.png` = the plain panel).
- Decode of the drawn code (from the buffer, not a screenshot): `shots/fb0-qr-code-crop.png` (452x452 full-res crop) ->
  **`https://ijigen.github.io/fpSup/sensor_lab_imx410/#G9BqUfgRuQKjAG9ZiJxIfQRkDmaXoNSl6CN0i`** (OpenCV). Same as st->qr.url.
- Payload vs selection: `qr_unpack` (test_slqs.py) -> CRC ok; ver 1, DC 6048x3402, RES 2016x1134, fps idx 8, VMAX 2700, HMAX 445,
  AD 12-bit, 2x3, ISP 1x1, key 14, kern 1/1 SOFT, preset recipe, visible 2000x1124, RS 7373 us, DNG, K-label RES,
  scw/sch 6048x3402, win 3024x1134 = the QS tiles (HD / 2K 2000x1124 / 59.94 / 12b 2x3 / RS 7.37 ms / DNG).
  72e6/(445x2700) = 59.925 fps <= 59.94. Readback = st->qr.code read with `mem get` (the buffer `sq_test 13` fills/returns);
  sq_test itself was not called on the camera.

## 5. Hide — FAIL (stale code leaks, panel left blank)
- AEL again (2728, still there 4 s later 2729): on 0, hides 1, our obs gone from group 0. The GUI redrew only the lower tile row
  + hint into the buffer that held our code and presented it: **upper half of the QR is now on screen** over the panel's top row.
  The wipe (`F_DRAW_CLR`) did not clear it before that flip.
- AEL to show again (2730, 2731): the displayed layer is now **empty** (whole QS panel gone, live view only); the code went to the
  other back buffer (`fb-after-show2-buf012.png`: buf0 = half code + lower row, buf1 = all zero = displayed, buf2 = full code).
  A rear-dial step on QR (2732, dials 1, adjusts 0) caused no redraw.
- Focus LEFT (2733): hidden (hides 2); again the GUI's partial redraw shows the **upper half of the code** above the tile row.
- RIGHT + AEL (2734): upper half of the panel blank, lower tile row present, no code.
- QS key (2735): QS closed, LV_CINE_MEDIUM, clean, no white; identical to start (2715). PASS for that part.
- Flicker: not observable (the code never displays as designed).

## 6. Final state (as asked)
QS reopened (2736, clean panel, focus QR), AEL (2737): on 1, shows 4, draws climbing, focus 0x3C. **The screenshot shows no code**
(plain panel). Left like this for Bei; expect no scannable code on the LCD. CINE 58 54 55 56 57 50 59 60, STILL and stock
Format 0 / Size 2 / Framerate 5 / ISO 3200 / headphone 3 unchanged. Counters: keys 6, dials 1, aels 5, fines 4, menus 0.

## Bugs (no source edited)
1. `projects/sensorlab-imx410/qs/slqs.c:922` `qr_group()` + `:969-970`: registering in the first 16-bpp group (0) draws into a
   back buffer that is never presented; the GUI's observer is in group 2 on the same layer (ctrl+0x18 = C38D3D0C). Needs to draw
   in the presenting group/cycle (e.g. group 2, after the GUI's observer) or trigger the flip.
2. `slqs.c:982-983` (`qr_hide`): `F_DRAW_CLR` + request on group 0 does not clean the GUI's buffers; the GUI's next partial redraw
   presents a buffer still holding the code (2728/2733), and after a re-show the displayed layer is all zero (2730). Hide needs a
   full GUI repaint of the panel in every buffer it rotates through.
