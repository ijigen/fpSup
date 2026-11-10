
2026-11-02 v0.7.10test: bounded IFD0 Compression check before native v11 metadata parsing.
SHA256 affe0369743080db013d51fc5f0fd05069f5028c08fbe969764bdcb104d2c739; 184888 bytes.
Source/evidence: validation/20261102-playback-entry (offline candidate).

2026-11-02 v0.7.11test: native high-rate carrier canvas +B0 field.
SHA256 5b7a2e48a90183875f6d49a46d8ad5fd8427a62ba7106d7d6abf60c3d4b5e152; 184920 bytes.
Source/evidence: validation/20261102-hirate-preview (offline candidate; sustained liveview not verified).

2026-11-02 v0.7.12test: high-engine-rate record-tap preview preference, with source and visible bounds.
SHA256 003129402061d0531d97fe4d97f8987c1ac5971f0f8380ac75360adb4b9ed4a2; 185024 bytes.
Source/evidence: validation/20261102-hirate-followup (offline candidate; camera outcome unverified).

2026-11-02 RATIO / small LOCK baseline: SensorLab-IMX410_v0.7.14test.BIN 0ec8ebedeb78ad26131fcff1dfd75b31c107e08e6445b2024844e5e2e74b0841

2026-11-02 RATIO / small LOCK baseline: QSContainer_v0.3.5.BIN 9dc84b78207a28c081977a3ba9b751acd4886c8ee64e35ff3ed293528d68115c

2026-11-02: SensorLab v0.7.16test default build, client-only LOCK text fallback.
SensorLab-IMX410_v0.7.16test.BIN 3ad6568f3cd3326849017e68cf5fe1360d566ef46aaf3a826b4dafcb7b52e2bd

2026-11-02: SensorLab v0.7.17test default, automatic QR on main QS; sha256 6ae0a730038752747fc0cf8756c396fdabc7b35a8d7b9d6d4342fe64e14fc9bf

2026-11-02: SensorLab v0.7.18test default, QR follows native rendered passes only; sha256 f037e8d7624ebdddbbb083555926630aba18efb77b3d2d280a5e614010c25797

2026-11-02 v0.7.19test default build: DC WIDTH coarse-step native stops.
SHA256 f553428514deba35aee446325acd3b9e6a27c84c5fb5b9edc646e7c728014586; 186268 bytes.
Source/evidence: validation/20261102-dc-native-stops/default-build (fixture added 2026-11-03; it was missing from this directory).

2026-11-03 v0.7.20test default build: code-quality pass (qr_show noinline for the movw/movt range, named constants, ap_pb_tag guard order, ring hook pointer check). No intended behaviour change.
SHA256 ec55ba7092b05a80cb0aff3ea080577fdae4527a39b50228df65b438d9ed3a88; rebuilt 2026-11-03 with the playback-fit fix (validation/20261103-playback-squash).
Source/evidence: validation/20261103-quality-v0720 (offline candidate).

2026-11-03 QSContainer v0.3.6 default build: text titles for QSC_F_TITLE functions in the custom-QS editor tiles.
SHA256 eb900933c36491070d1c113198f79544ac1d1f6845f06d0bdc034dae8d3fe061; 199400 bytes (rebuilt after live fix: title object under Icon01_CINE).
Source/evidence: projects/qs-container/validation/20261103-editor-title/default-build.

2026-11-03 v0.7.21test default build: Playback page blank Resolution frame applied (SL_PB_V2 gate removed; applied at the first-menu setup): a custom clip hides the FHD label.
SHA256 6d8852fe0d48c7b31f7d2ea5ad59343b9f3e8d84b1d123757e735daecc847612; 185388 bytes (applied at the first-menu setup).
Source/evidence: validation/20261103-pb-hide-fhd.

2026-11-03 v0.7.22test default build: playback pixel-size row as text (PB_OwnModel 1 for non-stock sizes, hook at v153 C05A2440).
SHA256 8467fe0dbf9abad2a39830ee8f80d53c7b01598d103a6b2292e7dfc5084a4c85; 185628 bytes.
Source/evidence: validation/20261103-pb-size-text.

2026-11-03 v0.7.23test default build: v5/v6 keep the real pixel size unless the HUD tile experiment is on (the text row read 0x0).
SHA256 6d5bab3092396262911444d9d82f1ef6f30041d91fbaa13d1f84e547becafad3; 185636 bytes.
Source/evidence: validation/20261103-pb-size-text.

2026-11-03 v0.7.24test default build: playback refuses rasters past stock DCI4K 4112x2170 (6K froze the camera).
SHA256 e09df4d129d7a62c917bd9915cbd35467ae7b855d99e8002ccccee0693cdfe95; 185692 bytes.
Source/evidence: validation/20261103-6k-freeze.

2026-11-03 v0.7.25test default build: defect (hot pixel) tables for the virtual modes -- the commit converts flash table 0x61 with the firmware's FUN_c0310740 and the slot's R68 row; hook at C030F624 (c030e2a0 -> FUN_c0635d80) hands DEFC the slot's table. AP_MEM_BYTES 0x16000 -> 0x36000 (block 566784 B).
SHA256 6872f0683e2ba2d02b6689f8f617a3e02d48eae5c73f9b49241cf9212a504193; 186364 bytes.
Source/evidence: validation/20261103-defect-virtual (offline candidate, not deployed).

2026-11-04 v0.7.26test default build: the first recorded frame's +1 row -- a per-take sentinel in raster row 0's last 64 B at ContSet_Adr1 (hook C031C948), checked at FUN_c038bd98's frame lookup (hook C038BDB4); intact -> the frame is DROPPED (native release pair, the lookup answers NULL: FUN_c038bd98's own no-frame branch before the first frame), or moved up one row when a stop / flag 2 is pending. AP_ABI 3 (struct ap_status +8 words), STATE_RESERVE +0x40. (Supersedes the same-day repair-only build e966ae54...)
SHA256 26e81702f5def44619753316d84d2360b0212b0761ce74aaa623a438603454cb; 187900 bytes.
Source/evidence: validation/20261104-first-frame-repair (offline candidate, not deployed).

2026-11-04 v0.7.27test default build: first-frame trace (read-only; FIRST_FRAME_SENSOR_RESET.md §5 step 1) -- v0.7.26test's drop / repair removed; the per-take row-0 sentinel stays (C031C948); records at the arm, BUFA1's completion callback FUN_c031bca0 (IRQ, plain loads / stores) and FUN_c038bd98's lookup (C038BDB4) for the first 4 frames into a 12-record ring in struct ap (sq_test 33). AP_MEM_BYTES 0x36000 -> 0x37000.
SHA256 0639af10d61dc1ecc33c4d8a5d06e5b3d7cf6157e54fe7cd6dab0bd508d2e566; 188732 bytes.
Source/evidence: validation/20261104-first-frame-trace (offline candidate, not deployed).

2026-11-04 v0.7.28test default build: on top of v0.7.27test (trace + sentinel unchanged), the firmware's own sensor pause / resume + link resync once at REC start -- after ContSet_Adr1's SetImgMode_s into the live slot's mode (hook C031BF88): XC_ImageSensorIMX410 v27(1), VD, v27(0), VD through the imager vtable; skipped when the frame period <= 15 ms (v27's guard). ap_status +3 words (resync_calls / skips / us).
SHA256 ff734e5fc2387578a028c4578ae074ce2c0aaa2e3b2e371eae4c064cc330130e; 188988 bytes.
Source/evidence: validation/20261104-first-frame-resync (offline candidate, not deployed).

2026-11-04 v0.7.29test default build: v0.7.28test's resync also at the switch a CinemaDNG REC start really makes -- the image controller task's SetImgMode_s (hook C030D168, message 1 of FUN_c030d0c0); ContSet_Adr1's own switch (C031BF88) kept; ap_status +2 words (resync_seen / resync_ours).
SHA256 b88f616dd4ed1a1395e9913f5b389cb259c0cef3abccaf28fe4a40f4a1d21b61; 189036 bytes.
Source/evidence: validation/20261104-first-frame-resync2 (offline candidate, not deployed).

2026-11-05 v0.7.38test default build (refresh 3): CPU x2 = its RWZM twin (D11: core_quality_twin, record RWZM +0x64 at unity, 12-bit container), the pass bins after BUFA0 completion (deadline 2 frame periods), BUFA0 line check, cached worker entry, throughput probe ap_h2_bench (sq_test 49 / 50).
SHA256 8bb95fa3d0b54a0e5d16954a0649cda4acaf9819fc16ae61c9956fefdd72270d; 213996 bytes.
Source/evidence: notes/CPU_X2_DESIGN.md "D11: the twin" (offline candidate, not deployed).

2026-11-05 v0.7.38test default build (refresh 4): D11 difference (4), Bei choice B -- a 14-bit AD CPU x2 records true 14 bit (plane code +0x84 = 8, rec14, h2_p14, 14-bit line / BlackLevel / tag bits byte); UI rec_bits counts hbin 2 as 1:1.
SHA256 059b99802be7f68d5faf48a15d0fe4f7404a498eb887cc6ca2bbc60e39c0648a; 214044 bytes.
Source/evidence: notes/CPU_X2_DESIGN.md "D11: the twin" (4); validation/20261105-cpux2-14bit-build (offline candidate, not deployed).

2026-11-05 v0.7.39test default build: CPU x2 removed (live 103 MB/s against 457 needed; code archived in validation/20261105-cpux2-archive). The core, apply and preview equal v0.7.37test; the kept fixes are the merge hint from the effective recipe, RECIPE line RS to one decimal with no size suffix, and boot.done in sq_push. rec_load maps a saved hbin 2 (v0.7.38test option 13) to ISP HBIN 1.
SHA256 f949e51643c303f52497919a9e7e4540c20b3f1ed4272ee8c81984eb5d5e484b; 205936 bytes.
Source/evidence: validation/20261105-cpux2-removed (offline candidate, not deployed). v0.7.38test is kept here as the hbin-2 migration source.

2026-11-07 renamed default builds (names_v4.py): SensorLab-IMX410_v0.0.1test.BIN 244fb64a82542d0cb8948b2ac5426f324b8f1e69dee7c6fb3a623c44fd15f55e (205936 bytes, = v0.7.39test except the header name) and QS-Share_v0.0.1test.BIN dcc773534fc9778d9116796790f71879a4aa3fca650685b3da849a7763cc4028 (202876 bytes, = QSContainer v0.3.8 except the header name and the state/DMA offsets).

2026-11-08 0.0.3test default build: CinemaDNG 8 / 10-bit (notes/BITDEPTH_8_10.md) -- the picker also answers TAB1 / TAB2, the record canvas takes 10/10 / 10/9 after such a pick, the true-14 BlackLevel shift only after TAB3; FORMAT / MB/s / defaultPick use the stock depth (C005BF28, once per layout); ap_status +2 words (rec_bits, low_picks); menu BIT row 8 / 10 selectable.
SHA256 9dd864ff7f9bbd57ae8dcecdcf5d2c0bbb3caef038a881aa615d99e269a8b173; 207148 bytes.
Source/evidence: validation/20261108-bitdepth-mov (offline candidate, not deployed).

2026-11-10 0.0.5test default build: first-frame purple fix = vertical margin, no extra rows (Bei 11-10): every recipe keeps >= 4.875 spare RWZM input rows below the record on its own readout (both RWZM ratios smaller by one factor / a shorter record in tol / both / the same at 3 % / not offered; RS and fps unchanged); old QR codes restore by their input fields (qr_diff / qr_map_rate). (No 0.0.4test fixture was frozen.)
SHA256 dd00aea48cded59e570aeb04f22a8cdefe999c737cd8b620858d99a86255dd45; 210000 bytes.
Source/evidence: validation/20261110-vertical-margin (offline candidate; the live 0/30 was the superseded extra-rows PURPLE build).
