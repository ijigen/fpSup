# RES output aspect, v0.7.8test — offline candidate

User report: with DC OG, changing only RES Height keeps filling the screen. Desired behavior: compress the image vertically as the output height decreases. The implementation must retain one simple formula for all dimensions.

`apc_build` previously passed the physical sensor aspect (record × zoom × scale × bin per axis) to both liveview and DNG DefaultScale. Liveview now passes the actual record raster width/height to the existing `apc_display`; DefaultScale still uses the physical calculation. No new hook, special size, state field, or ABI change. Recorded pixels, ISP words, sensor tables, frame-rate metadata, standby limits and DNG correction are unchanged. Playback continues to interpret its metadata, so its corrected aspect can differ from the output-shaped liveview.

Validation:

- Native ARM/ROM display update suite: 6 passed, including repeated OG Height and Width changes, returning to the original size, fallback/movie branches, original RGB fitting, playback/inactive guards and ABI preservation.
- Apply/crop/native-fit/playback regression: 42 passed. Its 7 calculation tests were rerun successfully after expanding to ten DC/RES combinations.
- Exact default build reproduction and saved-settings migration: 8 passed.
- QS apply-event and ratio-tile integration: 7 passed.
- 216 recipe outputs compared before/after byte-for-byte, excluding only `asp_n`, `asp_d`, `is169`, `box_w`, `box_h`, `det_h`; all remaining bytes identical.
- New independent RES test against pre-change source: expected failure (5 assertions, including unchanged height). This is the negative control, not a passing run.
- One initial invocation of `test_lv_update.py` omitted its required `--report` and exited before tests. The corrected run and report are preserved separately.
- Existing `reconstruct.py` ResourceWarning in the apply regression is unrelated; no skipped or failed tests in the final successful runs.

Example emulated 1620×1080 display, fixed DC 6048×4040, requested RES width 2016, 3x2/11-bit recipe: requested heights 1346 → 1200 → 1000 → 800 produce actual record heights 1342 → 1196 → 996 → 796, and fitted preview heights 1078 → 961 → 800 → 639. Firmware alignment is preserved.

Build from repository root:

```sh
python3 -B projects/sensorlab-imx410/qs/build_slqs.py --out projects/sensorlab-imx410/validation/20261102-res-output-aspect/default-build
```

Focused test commands from `projects/sensorlab-imx410/apply`:

```sh
python3 -B test_lv_update.py --report ../validation/20261102-res-output-aspect/res-native-report.json
python3 -B -m unittest test_apply.CalcTests test_apply.CommitTests test_apply.DcSweepTests test_apply.PlaybackTests test_lv_branches test_lv_fit.ProductFitTests
```

From `projects/sensorlab-imx410/qs`:

```sh
python3 -B test_settings_migration.py --out ../validation/20261102-res-output-aspect/settings-migration
python3 -B -m unittest test_slqs.ApplyUnit test_slqs.RatioTile
```

Delivery is the default-settings SensorLab BIN only. Compatible replacement; AutoRun/LOADER and QSContainer v0.3.4 stay as installed. Re-select SensorLab settings after replacing the BIN. No camera/USB connection, card write, recording or physical LCD validation was performed. The separate QSContainer lock-position candidate remains awaiting user validation.
