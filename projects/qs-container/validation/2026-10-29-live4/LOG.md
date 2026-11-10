# QS Container v0.2.2 + SensorLab-IMX410 v0.2.0test live test 2026-10-29 (run 4)

Shots: `shots/` (copies of /tmp/fp_ui/*). Reader: `qst4.py` (v0.2.2 layout: S = B + 154496, B = 0xC55BC8C0;
field offsets from `test_qs_page.LAYOUT` — v0.2.1's README offsets no longer apply). Dials: `fpsh "key CMDDIAL1 ±1"` (front),
`CMDDIAL2 ±1` (rear). After SS2577 the `dir` reply was full (16 KB), screenshots fetched by number (getfile size loop).
Note: images SS2535..SS2577 were saved but I could not view them in this session (image limit); the notes for that
stretch come from counters and settings reads, not from looking. SS2578 onward were all looked at.

## Start / prep
1. 13:33 shell OK. Camera had been restarted (LOAD.LOG 13:32) and v0.2.1 was in the RES sub-QS (sub_open 1).
   CINE 21 54 55 25 39 50 27 19, STILL 9 10 11 19 20 22 24 30; fmt 0 / size 2 / fps 5 / ISO 3200 / hp 3; WB 5550 K.
   Backups: card_backup/fpSup_dir_before.txt, LOAD.LOG.before.
2. AEL -> sub-QS closed (sub_open -1). QS, MENU, SYSTEM p2, editor: slot 2 -> DC裁剪模式, slot 3 -> 解析度. mem get CINE = 21 12 23 25 39 50 27 19. MENU MENU -> LV.
3. `fl del` QSContainer_v0.2.1.BIN, SensorLab-IMX410_v0.1.0test.BIN -> OK. deploy_v3 with read-back:
   QSContainer_v0.2.2.BIN 154440 B (sha 1c4296ef...), SensorLab-IMX410_v0.2.0test.BIN 72980 B (sha ef2d3bee...). Both OK.
4. `ui_drive.py reboot` up 10.8 s. LOAD.LOG (card_backup/LOAD.LOG.boot1): `QSC 00000000 C2DEAD7C`,
   `0A C55BC8C0 QSContainer_v0.2.2.BIN`, `0A C55F3640 SensorLab-IMX410_v0.2.0test.BIN`. After first MENU: result 0, phase 2,
   freeze 0, N 5, recv 5, qs_result 0, qs_ready 1, qs_vars 148, fresh 1. PASS.

## Editor (slots chosen, stock function displaced)
5. slot 1 FORMAT(21) -> SL FORMAT(58); slot 2 DC裁剪(12) -> DC(54); slot 3 解析度(23) -> RES(55); slot 4 FPS(25) -> SL FPS(56);
   slot 5 id 39 -> RECIPE(57). Slots 6-8 (50 K, 27 COLOR, 19 WB) untouched. CINE = 58 54 55 56 57 50 27 19. List is 37 long.

## QS (key QSON). Settings fmt/size/fps/ISO/hp/WB read unchanged after every block.
6. Open: hits 118 (= n_targets of v0.2.2). Five tiles have values. Titles: FORMAT, DC icon, RES., FPS, and RECIPE (text) —
   **the RECIPE tile also draws the DC icon on top of its title text (`RE[DC]PE`)**, in every QS screenshot.
   Small lines are grey system font (PASS).
7. DC: front dial 9 steps up/down, adjusts counted, values back to HD (not viewed, SS2559-2563).
8. **AEL on DC / RES right after boot did nothing: aels stayed 0** (key not delivered to us). After focus had visited the
   stock K tile and RECIPE/FORMAT, AEL worked every time (aels 1..9). Repro condition not isolated.
9. RES dial: up 7, down 9, up 2 (back to 2K). Timed each dial: adjusts counter changed 43..223 ms after the key command
   returned, same range as the FPS dial (52..219 ms); one mem get = ~45 ms. No lag beyond the USB round trip that the
   counters can show. RES 2K reads `2000×1124 · 3x3` (live 3 showed 2016×1134) — not explained here.
10. FPS: list 48 / 48.713 / 50 / 59.94 / 60 / 60.562 / 61.668..., dotted underline under non-stock rates, `14 recipes`.
    Up to cap 185.529 (`? 1 recipes`): 200 / 239.76 / 240 grey, one more +1 stays at 185.529 (PASS skip).
    **The bullet before `N recipes` renders as `?`** (SS2575, SS2576). Rear dial on list moves one entry (185.529 -> 180).
11. FPS AEL fine mode (SS2597): layout unchanged, footer `◀ 59.940 ▶`, fine_on 3. Front +1 -> 59.947, rear +1 -> 60.006
    (rear = 10 steps, CMDDIAL2 +1 = up). AEL -> fine_on 0, list 50 / 59.94 / 60 / **60.006 yellow** / 60.562 (PASS). Dialed back to 59.94.
    Hint during fine mode still shows the stock `AEL 白平衡調整` (not hidden), see 15.
12. RECIPE tile: `12b 2x3` `RS 7.37 ms`, footer greyed entries with amber small text (`RS 21.35`), dial only on available ones
    (2x3 -> 3x2 -> back). Rear +1 did not move it (adjusts counted).
13. RECIPE sub-QS (SS2602): RECIPE, ADC `12bit`, SENSOR HDC 6048 `read → 3024`, VDC 3402 `read → 1134`, HBIN 2, VBIN 3,
    ISP HBIN 1 `RWZM 1/1.50`, ISP VBIN 1 `RWZM 1:1` (8 tiles, PASS). ADC footer `11bit 12bit 14bit`, 14bit grey with
    `needs SENSOR H1`; dial +1 stays 12bit (PASS). HBIN -> 1, then ADC +1 -> 14bit, recipe `14b 1x3 RS 15.10 ms`;
    back in main QS FORMAT small line `14bit` (PASS linked); FPS stayed 59.94 (14b 1x3 fits, auto-lower not exercised).
    RECIPE dialed back to `12b 2x3`, FORMAT `12bit`. ISP HBIN 3 / core / SOFT not tested.
14. FORMAT (SL FORMAT): footer `DNG | MOV`, MOV grey; front and rear dial: nothing changes, SetMovRecFormat 0 (PASS).
15. DC sub-QS (SS2585): DC/HD, WIDTH 6048, HEIGHT 3402, RATIO title + key icon in value place, `1.778 : 1` under it.
    Footer `OG HD S35 APS-C S16 SQ`. WIDTH -1 -> 6032×3394 CUSTOM 1.777; +1 -> **6048×3402 HD** (PASS, snap-back).
    Rear -1 -> 5888×3312 (10×16), +1 -> HD. AEL -> back to 8 tiles, focus on DC (PASS).
    **Hint in the sub-QS shows `AEL 白平衡調整`** (stock K's hint left on screen, expected hidden).
    Small issue: the key icon overlaps the `1.778 : 1` text.
16. RES sub-QS (SS2592): RES 2K, WIDTH 2000, HEIGHT 1124, RATIO key. WIDTH -1 -> 1984×1116 CUSTOM 1.776, +1 -> 2000×1124 2K (PASS).
    RATIO -> FREE (crossed key) -> LOCK (PASS).
17. Neighbour check: K stays 5550 after dialing RECIPE (left neighbour) front/rear and after FORMAT; stock fmt/size/fps/ISO/hp unchanged (PASS).

## MENU from the sub-QS (once, RECIPE sub-QS, 14:00:20)
18. `key MENUON` -> 3 s -> ping pong, app_current 5. Screen: QS closed, stock menu (SYSTEM p2, 自定QS row). sub_open -1,
    closes +1, menus 0 (no MENU-back by default, as designed), leaves +2. The client wrote its record on leave():
    SensorLab BIN mtime 14:01:14, `SLQ2` record present, rest of the BIN identical (card_backup/SensorLab-IMX410_v0.2.0test.after.BIN).
    MENU -> LV, QS reopened: user's 8 tiles, focus SL FORMAT, values drawn. Shell answered throughout (one ERR ping right
    after QSON, next pings fine; one LIBUSB timeout on a MENU key, recovered). **PASS — no wedge.**

## End state
19. Bei (via coordinator, mid-run): leave our functions in the slots. I had already put slots 1-3 back to stock in the editor
    and then set them back to SL FORMAT / DC / RES. Final CINE 58 54 55 56 57 50 27 19, STILL 9 10 11 19 20 22 24 30.
    fmt 0, size 2, fps 5, ISO 3200, hp 3, WB 5550. Container: phase 2, freeze 0, sub_open -1, fine_on 0.
    Card: QSContainer_v0.2.2.BIN + SensorLab-IMX410_v0.2.0test.BIN. Camera in LV_CINE_MEDIUM standby, not recording.
