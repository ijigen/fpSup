# QS Container v0.2.4 + SensorLab-IMX410 v0.2.2test live test 2026-10-29 (run 5, RECIPE sub-QS round 2)

Shots: `shots/NNNN-tag.jpg` (NNNN = SS__NNNN.JPG, fetched by number with `shot.sh N tag`; every one viewed).
Reader: `qst5.py` (S = B + 173888 = state_off of build-0.2.4.json, B = 0xC55BC8C0 from LOAD.LOG; offsets =
`test_qs_page.LAYOUT` as of 19:10). Dials `fpsh "key CMDDIAL1/2 ±1"`.

## Deploy
1. 19:09 shell OK. `card_backup/fpSup_dir_before.txt`, `LOAD.LOG.before` (v0.2.3 + v0.2.1test loaded at C55BC8C0 / C55F7DC0).
2. `fl del` QSContainer_v0.2.3.BIN, SensorLab-IMX410_v0.2.1test.BIN -> OK. `v3/deploy_v3.py card/` (full read-back):
   QSContainer_v0.2.4.BIN 173888 B (sha 1c2b1bf2...), SensorLab-IMX410_v0.2.2test.BIN 73408 B (sha 6097a3af...). OK.
3. `ui_drive.py reboot` up 11.5 s. LOAD.LOG (`card_backup/LOAD.LOG.boot1`): `QSC 00000000 C2DEAD7C`,
   `0A C55BC8C0 QSContainer_v0.2.4.BIN`, `0A C55F8200 SensorLab-IMX410_v0.2.2test.BIN`. After first MENU: result 0, phase 2,
   freeze 0, N 5, recv 5, qs_result 0, qs_ready 1, qs_vars 193, fresh 1. PASS.

## Slots
4. **CINE read 21 12 23 25 39 50 27 19 (stock placeholders), not 58 54 55 56 57.** Cause: the slot record lives in the
   container BIN at rec_off (173532), the fresh v0.2.4 BIN ships it zeroed, and the old BIN (with the record) was deleted
   -> qc_rec_load finds no record, nothing restored (restored 0, orphans 0). Every container update loses the user's slots
   unless the record is carried over. Re-did the editor (SYSTEM p2 -> 自定QS, list 37 long: 33 DC, 34 RES, 35 SL FPS,
   36 RECIPE, 37 SL FORMAT; 2636..2648). CINE = 58 54 55 56 57 50 27 19.
   Editor: the RECIPE item/tile shows only the DC icon (list 2647, editor tile 2648) — no RECIPE text.

## QS
5. QSON (one LIBUSB timeout on the key, QS opened; hits 118). Main QS 2649 = round 1 look (ref-v023_2631.jpg); RECIPE title
   no longer has the DC icon on top. FPS `14 recipes` without the old `?`.
6. RECIPE tile (2650): footer `12b 1x1 / 21.3ms` (amber, grey), `12b 2x3 / 7.4ms`... short and readable, 7 items. PASS.
7. AEL on RECIPE right after boot: aels 0 twice (dead). RIGHT (K) + LEFT, AEL -> sub-QS opens. Known issue still there.
8. Sub-QS (2651): RECIPE, ADC, DC WIDTH, DC HEIGHT, SENSOR HBIN, SENSOR VBIN, ISP HBIN, ISP VBIN. PASS.
9. ADC (2652): `11bit 12bit 14bit`, 14bit grey `→S.HBIN1`; front +1 x2 stays 12bit (2653). PASS.
10. DC WIDTH `S 6048`/`I 6048` (2654), DC HEIGHT `S 3402`/`I 3402` (2655); footer one item only (6048 / 3402), no greys. PASS.
    Arrows ◀▶ drawn although there is nowhere to go.
11. ISP VBIN/HBIN at 1 (2656/2657): footer `1`, then `3[1,1,1] 3[1,2,1] 3[1,4,1] 3[1,6,1]` grey with `SOFT →S.VBIN1` /
    `SOFT →S.HBIN1` (5 items when greyed with second line).
12. SENSOR VBIN (2658): `1` grey with **`?45.73p`** — the `≤` (slqs.c:98 SL_LE U+2264) renders as `?` (zoom 2658-sv-zoom.png).
    Same for ADC 14bit `?43.67p` (2669) and `?22.48p` (2677).
13. FPS never lowered (SetMovFramerate 5 and FPS 59.94 throughout): VBIN 3 -> -1 -> 2 (12b 2x2, 2660), further front -1 and
    rear -1 stay 2 (2661); ADC 12 -> +1 front, +1 rear onto `14bit ≤43.67p` stays 12bit (2670). PASS.
    2660: DC HEIGHT small turned `I 3404` (ISP crop > sensor crop 3402) after VBIN 2 — looks wrong.
14. SENSOR HBIN 2 -> 1 (2662, 12b 1x2). ISP HBIN footer then white `1 3[1,1,1]..3[0,1,0] SOFT` (2663, 7 items).
    Front +1 from `1` jumped to `3[1,2,1]` (remembered kernel kh, slqs.c:1147), -1 -> `3[1,1,1]` (2664/2665).
    Big `3[1,1,1]`: bold 3, thin bracket; small `SOFT · RWZM 1:1`; footer labels thin. PASS.
    RECIPE tile then `CUSTOM` with a tiny crammed small line `12b 1x2 ISP 3x1 · RS 10.68 ms` (2664).
15. **BUG: STD kernels unreachable.** Footer scrolls to `3[1,1,1] STD ...` drawn white (2666), but +1 from `3[0,1,0] SOFT`
    stays (adjust counted, 2667). slqs.c:1147-1148 limits jj to 0..6 (this mode's 6 kernels); nothing ever sets s.km
    (only the record load, slqs.c:730), while the footer (slqs.c:1005-1016) lists all 13 as selectable. Stopped there.
    HBIN/VBIN sharing the mode therefore not observable; ISP VBIN stayed 1 (grey, S.VBIN 2). ISP HBIN dialed back to 1.
16. FORMAT link: ADC 11bit -> main FORMAT `12bit` (2671/2672). FPS tile lowered to 43.665 (2674), ADC -> 14bit (2676),
    SENSOR HBIN 2/3 grey `→12bit` (2678), +1 stays; main FORMAT `14bit` (2680). PASS.
    Then RECIPE back to 12b 2x3 (2681), FPS back to 59.94 (2682). FORMAT `DNG | MOV`, MOV grey, front/rear +1 no change,
    SetMovRecFormat 0 (2683). PASS. `no 3x1` reason not seen (needs S.VBIN 1, ≤45.73p).
17. FPS small line at non-stock rates reads `· 16 recipes` / `· 18 recipes` with a leading dot (2674, 2680).
18. Neighbours: K/WB 5550K, COLOR OFF; fmt 0 / size 2 / fps 5 / ISO 3200 / hp 3 unchanged. STILL unchanged.

## End
19. QSON -> QS closed, LV_CINE_MEDIUM (2684), ping OK. Counters: keys 52, dials 48, aels 4, opens 2, closes 2, adjusts 46,
    menus 0. CINE 58 54 55 56 57 50 27 19. Card: QSContainer_v0.2.4.BIN + SensorLab-IMX410_v0.2.2test.BIN. No MENU in sub-QS.
