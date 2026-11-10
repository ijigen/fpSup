Frozen inputs for test_settings_migration.py (copied 2026-10-30; test-only, never deployed).

preupgrade_backup/  the read-only card backup the migration reads (SensorLab v0.5.0test, QSContainer v0.2.4, their
                    manifest), copied unchanged from validation/20261030-takeover/preupgrade_backup/.
frozen/             the default builds the builders must reproduce byte for byte:
                    SensorLab-IMX410_v0.7.3test.BIN  sha256 766dd87c3c2c97bdd0276ff027fad21593d5bf7ec9833f7e29dc5d4049a5155a
                    (copied from validation/20261030-lv-aspect-fix/default-build after native fit/route/outer tests)
                    (SensorLab-IMX410_v0.7.2test.BIN af2a7271... kept: the last live-tested version)
                    (SensorLab-IMX410_v0.7.1test.BIN c9a4e8bd... kept: the previous version, no longer read)
                    (SensorLab-IMX410_v0.7.0test.BIN ce1f9704... kept: the previous version, no longer read)
                    QSContainer_v0.3.2.BIN           sha256 a73c9fcd6d7ca8c122a085cd77251e59209778442427e0930a2ebacbdcaff512
                    (QSContainer_v0.3.1.BIN 59bdd136... kept: the previous version)
                    (copies of qs/out/fpSup and qs-container/out/fpSup).  A new version: copy its default builds here.

2026-11-01: added SensorLab-IMX410_v0.7.4test.BIN 7f1de25f256cb727c57238d73c6a7082d03cbf1b387299d74231a101a77445fb (default build from validation/20261101-ui-layer-scope/fixed-default-build; offline fixture only, not accepted hardware). v0.7.3test retained as a rejected regression reference, never overwritten.

2026-11-01: added SensorLab-IMX410_v0.7.5test.BIN 150791537485c2e6fa79e044ecf3420907d9c59870c1535fce6554decb03dc4a (default build from validation/20261101-yuv-32-branch/default-build; offline fixture only; awaiting user LCD test). Older version fixtures retained.

2026-11-01: added SensorLab-IMX410_v0.7.6test.BIN 1de06ee3728df24b53dd3aba01f1ddad2e9680175a87385175a4f851fff9812f (default build from validation/20261101-qs-live-update/default-build; offline fixture only; QS live adjustment awaits user LCD confirmation). Older fixtures retained.

2026-11-01 ratio UI defaults (offline-only fixtures; previous versions retained):
  SensorLab-IMX410_v0.7.7test.BIN 171c0aa6c300af694c3bdce37f0f68278988e32db88f5c118ae02d932f7673cf
  QSContainer_v0.3.3.BIN 5ec80aa118db12ec593c38e7534ec3db0ef6d4b79379c7ab780e4af0dc734e8d

2026-11-02: added QSContainer_v0.3.4.BIN 2eac6a799f7fc175d2a8fa0a23cbb151b1878c5f31f1e070d1ea8c924addacec (default build; native lock position candidate; LCD unverified).

2026-11-02: added SensorLab-IMX410_v0.7.8test.BIN d4eb7e2e110d50ba89342414930ca45aa00a8d1f2d1d0e8b16173fb8e71297ca (default build; unified RES output liveview aspect; offline fixture only, LCD unverified).
2026-11-02: added SensorLab-IMX410_v0.7.9test.BIN 389e93c2ff7ac0cd6ae9a75e26974d5d62a5ba0ec3d7a8342ebb512036f1b58b (default build; selected-file playback admission/canvas; offline fixture only, hardware playback unverified).

2026-11-02: added SensorLab-IMX410_v0.7.13test.BIN 7553f5c5cf559d1a48e48edecf88dd351c301dc3cc47d374eac12f7d19e429fa (default build from validation/20261102-playback-ring-fix; playback ring capacity/cadence fix; offline fixture only, hardware not yet verified). Older fixtures retained.

2026-11-02: added SensorLab-IMX410_v0.7.15test.BIN 8abbf6c669b5ea91ec2b568c61cdeb3fbf6f489e1162cf5c3cd75d3188cf319b (default from validation/20261102-playback-raw14-fix; selected primary RAW14 read format candidate; hardware unverified). Older fixtures retained.

2026-11-04: added SensorLab-IMX410_v0.7.32test.BIN f07a91180bba0baf4e0d9efb28e47564dd8dce92496110b205d143cdea14734d and QSContainer_v0.3.7.BIN 646ef5202ac5e250f96fba593a4ee937f76b40aa1c7a52b56679be280881abbc (default builds from validation/20261104-qr-scan-build; QR scan via the stock read page + container API 7; REC-start resync switched off; settings record unchanged; offline fixtures only, hardware unverified). Older fixtures retained.

2026-11-04: added SensorLab-IMX410_v0.7.33test.BIN 686f8ef4357f227cc8cfbaa01669b9a2c808d96e871f27ef3127e05feb5856c5 (default build from validation/20261104-qr-scan-build2; a SensorLab QR result never reaches the stock parser / save page; offline fixture only). Older fixtures retained.

2026-11-04: added SensorLab-IMX410_v0.7.34test.BIN 56c663237c03ceb8aacc0f7799b187805783bb6f0faf8059488fb19d6afe8df7 (default build from validation/20261104-qr-scan-build3; an applied QR code leaves the read page to the QS; offline fixture only). Older fixtures retained.

2026-11-05: added SensorLab-IMX410_v0.7.35test.BIN a3fd557c9dabb73a1267a58aa027e07ed7529a2eb05c002af689d75f6d0eb830 (default build from validation/20261104-boot-apply; boot apply without MENU/QS + RES one-step window and effective-RES hint; offline fixture only). Older fixtures retained.

2026-11-05: added SensorLab-IMX410_v0.7.36test.BIN 0170ba75700496abdc9e0fcd60d82b7314748ff19f2dc98b569203f23d86fad8 and QSContainer_v0.3.8.BIN cf297822fbd206a805e23cbcf79a64a3edfff0a12933ff7751ba7d519c690aa0 (default builds from validation/20261105-boot-apply2; boot apply at the standby screen's enter, RES shows the dialled value + the recorded size, the dial guide (container API 8); offline fixtures only). Older fixtures retained.

2026-11-05: added SensorLab-IMX410_v0.7.37test.BIN 23c76320f62977d4447303af9a0e643f7950bd5cdb59f6fd4d3aee33df81448a (default build from validation/20261105-boot-apply3; the boot apply variable registered at sup load and the commit at sup_entry (RES-Custom's way), a CINE live view running counts as ready: the boot LV starts before the sups load; offline fixture only). Older fixtures retained.

2026-11-05: added SensorLab-IMX410_v0.7.38test.BIN 8fddef8cbcf08456679978ce909c7db0ad216083cab8f3c506fc19e87fa07009 (default build from validation/20261105-cpux2-build; the CPU x2 option (ISP HBIN hbin 2) in the QS UI on top of the CPU x2 recipe core / apply unit; refreshed 11-05: hint from the effective recipe, RECIPE line RS one decimal, core never offers a CPU x2 recipe apply refuses, any committed push ends the boot apply; offline fixture only). Older fixtures retained.

2026-11-05: added SensorLab-IMX410_v0.7.39test.BIN f949e51643c303f52497919a9e7e4540c20b3f1ed4272ee8c81984eb5d5e484b (default build from validation/20261105-cpux2-removed; CPU x2 (ISP HBIN hbin 2) removed from the product: the recipe core, apply and preview are back to v0.7.37test, and the kept display fixes are the single-source merge hint, the shorter RECIPE line and boot.done in sq_push; a saved hbin 2 loads as ISP HBIN 1, see test_settings_migration CpuX2Removed, which builds its hbin-2 source from frozen/SensorLab-IMX410_v0.7.38test.BIN; offline fixture only). Older fixtures retained.

2026-11-07: added SensorLab-IMX410_v0.0.1test.BIN 244fb64a82542d0cb8948b2ac5426f324b8f1e69dee7c6fb3a623c44fd15f55e and QS-Share_v0.0.1test.BIN dcc773534fc9778d9116796790f71879a4aa3fca650685b3da849a7763cc4028 (default builds; Bei renamed the products for the first merge-page release: Sensor Lab-IMX410 0.0.1test = v0.7.39test with the header display name "Sensor Lab-IMX410" (body byte-identical); QS-Share 0.0.1test = QS Container v0.3.8 with the header display name "QS-Share" (was "font_menu_SB_kigou_09", a builder bug), file 12 bytes shorter so state_off/dma_off/block moved down 64 B; sup_ids SL41/QSCT and the records unchanged; offline fixtures only). Older fixtures retained.

2026-11-07: added SensorLab-IMX410_v0.0.2test.BIN c5c1ddad39e37b4d323516b9ba2e728fdf09f3c43c6b81de2dbfdc8ccb621220 and
QS-Share_v0.0.2test.BIN 4939f399abb21076576dcb337d2ba8b6e66ad8375868f37e97aa976485e372b2 (default builds; FPS AEL in-place
fine, QS-Share API 9; offline fixtures only, not live-tested). Older fixtures retained.

2026-11-08: refreshed SensorLab-IMX410_v0.0.2test.BIN c5c1ddad... -> 542bc89ec69f0afbaf47361668a3d5ed13ac05d84cf8ea067c573826bb46d4fa
(default build with the QR-scan commit moved to the read page exit, validation/20261108-qr-rec-revert; record format
unchanged; offline fixture only, not live-tested).

2026-11-10: added SensorLab-IMX410_v0.0.6test.BIN 36f24a1267596cafaa99ed24830f3d4d9df20e58282e2da57661483edc470b83 (default build; exact merges + 1x2 / 1x3 presets + RES menu page 12 rows, validation/20261110-binning-exact; offline fixture only). Older fixtures retained.
