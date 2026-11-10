# 0.0.3test: CinemaDNG 8 / 10-bit + MOV feasibility (2026-11-08, offline only)

Designs: `notes/BITDEPTH_8_10.md`, `notes/MOV_FEASIBILITY.md`. No camera, USB or card was used.

- Product: `qs/out/fpSup/SensorLab-IMX410_v0.0.3test.BIN`, sha256 `9dd864ff7f9bbd57ae8dcecdcf5d2c0bbb3caef038a881aa615d99e269a8b173`,
  207148 B. Two builds are identical. A frozen copy is in `qs/test-fixtures/settings-migration/frozen/`.
- REC-delay TEST variant: `qs/out-rec-delay-test/fpSup/SensorLab-IMX410_v0.0.3test.BIN`, sha256 `776fb7a6…69a00`.
- Container unchanged: QS-Share 0.0.2test.
- prelive (`tools/test-logs/prelive-20261108-040634`):
  - apply: 92 tests and 141 mutants. Includes the new tests: the table / mode identity test, and plane codes + BlackLevel
    per table.
  - core: 62 mutants.
  - unit suites PASS. The failures at the time were mutant pattern errors and the missing 0.0.3test frozen fixture.
    All were fixed and rerun: settings-migration 9 OK, site 9 OK, test_slqs 78 OK, menu 42 OK, fast PASS.
  - slqs depth mutants rerun one by one: 12 of 12 caught.
  - Two mutants were dropped as equivalent ('defaultPick ignores the stock depth', 'depth change keeps the memo').
    A page sweep of 270 DC×RES×FPS cells found no cell where the stock depth changes the default recipe.
- `mov_feasibility.json`: output of `tools/mov_feasibility.py`.
