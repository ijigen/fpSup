# BLK-SNAP live, 2026-11-16 (Bei chose: test on 0.0.7test)

| time | step | result |
|---|---|---|
| 10:36 | backup `\fpSup\LOAD.LOG`, `SensorLab-IMX410_v0.0.6test.BIN` (211 820 B, sha256 9dcdaf3e…, settings record inside) | `backup/` |
| 10:36 | build `--blk-snap-test --settings-from backup/…0.0.6test.BIN` | 214 640 B, `0ca881db14f80c0c…` (out-blk-snap-test/) |
| 10:37 | `deploy_v3.py --only fpSup/SensorLab-IMX410_v0.0.7test.BIN` | OK, full read-back. The 0.0.6test file left on the card |
| 10:37 | `ui_drive.py reboot` | **no pong in 120 s** |
| 10:39 | host side only (no command sent): `SIGMA fp` 1003:c432 enumerated, interface class **06/01/01 (stock PTP)**, not ff/ff/ff | the USB shell sup did not load this boot |

LOAD-before.LOG order: … SensorLab-IMX410_v0.0.6test (0x36 claims) → Stop-FX → StorageTest → SUPMGR → TapToZoom →
UnlockWriter → USB-Shell_v3.4.0 last. Inference [I]: SensorLab 0.0.7test (BLK-SNAP) stopped the load or froze at init,
so USB-Shell never loaded. Not yet known: whether the UI runs, what LOAD.LOG says.

Stopped here (AGENT_BRIEF: on a freeze, no recovery loops). Next: Bei reports the screen; read the card's LOAD.LOG in a
card reader (the loader's record of how far it got); restore = delete `\fpSup\SensorLab-IMX410_v0.0.7test.BIN`
(the 0.0.6test file is still there and loads again).

## Update 10:47 — the "lost after reboot" was the Mac, not the camera
ioreg: `ptpcamerad` held interface 0 (stock-PTP descriptor right after a reboot). Killed it once, started fpshd:
pong. LOAD-after.LOG: SensorLab-IMX410_v0.0.7test loaded at 0xC52D4480 (0x36 claims), 0.0.6test skipped as the
older duplicate, USB-Shell loaded. Known since BOOT_TIMING.md §1 but never wired into the reboot tools: now
`daemon_restart_log.release_ptp()` (kills only a ptpcamerad that holds the SIGMA fp interface while no fpshd does),
called by `ui_drive.py reboot` and `fastreboot.py` before each daemon spawn.

## Phase 0 + one stock take (10:55–11:30), lens capped, recipe set over USB (take.py: sq_test 41/43/41/19)
`results.json`; data = rawpy mean of the centre 3/4, DN12 (14-bit / 4). Ring = blk_snap.py decode of `takes/*/ring.bin`.

| take | bits | data | tag | err | ped | ped-fixed tag err |
|---|---|---|---|---|---|---|
| 12v2 6048x1700 ISO 100 (clamp) | 12 | 254.776 | 255.997 | -1.221 | 1021 | -0.471 |
| 14v2 same | 14 | 255.890 | 256.002 | -0.112 | 1024 | -0.112 |
| 12 6048x4040 1:1 ISO 100 (no clamp) | 12 | 255.765 | 256.000 | -0.235 | 1024 | -0.235 |
| 14 same | 14 | 256.126 | 256.000 | +0.126 | 1024 | +0.126 |
| 12v2 ISO 3200 | 12 | 254.864 | 255.897 | -1.033 | 1021 | -0.283 |
| 14v2 ISO 3200 | 14 | 255.689 | 255.860 | -0.171 | 1023 | +0.079 |
| 12 full ISO 3200 | 12 | 255.854 | 255.875 | -0.021 | 1024 | -0.021 |
| 14 full ISO 3200 | 14 | 255.929 | 255.875 | +0.054 | 1024 | +0.054 |
| **stock** (sq_test 30 1; mode 109, FHD 1936x1090) ISO 100 | 12 | 255.378 | 255.988 | -0.610 | 1022 | -0.110 |

Mechanism (ring + FUN_c0313ec0 / FUN_c031a2a0):
- clamp off: pedestal stays 1024, the tag is a constant 256 (255.875 at 3200): errors within +-0.25.
- clamp on: at init the loop moves the pedestal by a table entry picked by the OB average's two low DN14 bits
  (branch A {1:-3,2:-2,3:-1,0:0}, B {1:-1,2:0,3:-3,0:-2}). 12-bit OB averages come off truncated data (12v2:
  254.79 -> 1019 DN14 -> &3 = 3 -> B: -3 -> 1021). The tag formula assumes the black at lock is 256 and only
  tracks changes since: it never sees the pedestal move. 12-bit SensorLab recipes lose 3 DN14 (-0.75 DN12, ~-1 DN
  measured), stock FHD 2 (-0.6 measured) -> **stock 12-bit CinemaDNG has the same error, smaller**.
- candidate fix (offline, not built): tag += (pedestal - 1024) / 4 in the BlackLevel hook: worst 1.22 -> 0.47,
  stock 0.61 -> 0.11. The 12v2 residual (-0.47 / -0.28) is not explained yet (n = 2).
State after: recipe back to OG 3K 12b 1x2 (code G9B-QvQfkGVFwG9VCJRIvAfKGLKXoPyL0D7yK), ISO 3200.
The BLK-SNAP 0.0.7test build is still on the card (0.0.6test file kept; delete the 0.0.7test file to go back).

## Phase 1, coarse (11:35–12:55): 72 strata x ISO 100/800/3200 = 216 takes, all recorded, no freeze, no error
`run_plan.py` -> `results-phase1.jsonl`, `analyze.py` -> `summary-phase1.json`. err = data black - DNG tag, DN12.

| recorded bits, clamp, path | n | err mean (lo..hi) | after the pedestal term |
|---|---|---|---|
| 12, off, 1:1 | 33 | -0.413 (-0.792..-0.015) | same (pedestal 1024) |
| 12, off, RWZM | 66 | +0.047 (-0.406..+0.596) | same |
| 12, on, 1:1 | 33 | -0.802 (-1.231..-0.130) | -0.401 |
| 12, on, RWZM | 66 | -0.460 (-0.972..+0.144) | -0.009 |
| 14, off, 1:1 | 9 | +0.082 | same |
| 14, on, 1:1 | 9 | -0.028 (-0.766..+0.214) | +0.056 |

Model: err = (pedestal - 1024) / 4 + (12-bit and RWZM off ? -0.42 : 0).  -0.42 ~ the floor bias of 14 -> 12 bit
truncation (-0.375); RWZM rounds (+0.03).  |err| mean / p90 / max: now 0.415 / 0.874 / 1.231; pedestal term only
0.237 / 0.508 / 0.875; both terms 0.162 / 0.347 / 0.565 (the rest: fast AD at ISO 3200, up to +0.57).

Side findings:
- SQ 1024x1024 RWZM: Lossless-compressed frames decode (rawpy) with 258 all-zero rows; frame 1 (uncompressed) is
  clean. Not yet known whether the encoder or the decoder is wrong.
- APS-C 1312-row V2 / 2x2 recipes (12v2, 14v2, f12v2, 2x2, 2x2fast): the last 2 DNG rows are 1..4 (blank),
  outside the 5-row DefaultCrop margin.
Card state: unchanged since the phase-0 note (BLK-SNAP 0.0.7test on the card, recipe OG 3K 12b 1x2, ISO 3200).

## H_BLV live acceptance (14:00–16:55), build blv/out-blk-snap-blv (0.0.7test + H_BLV + BLK-SNAP, claims 0x37)
- `ui_drive.py reboot` with `release_ptp`: ptpcamerad grabbed the interface twice, both handled, shell up in 12.6 s.
- `blv/accept.jsonl`: stock FHD (sq_test 30 1, mode 109) 2 takes per ISO; phase 0 again; the 14 worst of phase 1.
- `blv/results-iso.jsonl` + `blv/summary-iso.json`: the 72 strata at ISO 1600 / 6400 / 12800 with H_BLV.
  (stopped once at take 64: `dir \CINEMA` is cut at 16 KB past ~320 folders; take.py now probes the next clip.)

| ISO | stock FHD abs err | ours (72 strata) mean / max | ours worse than stock |
|---|---|---|---|
| 100 | 0.58 0.60 | 0.145 / 0.500 | 0 |
| 800 | 0.63 0.64 | 0.150 / 0.406 | 0 |
| 1600 | 0.79 0.82 | 0.177 / 0.597 | 0 |
| 3200 | 0.30 0.31 | 0.197 / 0.596 | 12 |
| 6400 | 0.97 0.98 | 0.160 / 0.655 | 0 |
| 12800 | 0.07 0.10 | 0.165 / 0.615 | 42 |
(ISO 100/800/3200: phase-1 takes + the table; 1600/6400/12800: measured with the hook.)
Overall: ours max 0.655 vs stock max 0.98, ours mean ~0.17 vs stock ~0.58.  Per ISO, stock happens to be close at
3200 / 12800 and 54 of 431 strata-takes are worse there.  The remainder is RWZM rounding, recipe- and gain-dependent
(crop alone moves it up to 0.67): only a measured per-recipe x ISO table (black balance) beats stock at every ISO.
Sensor gain word (imager +0x24) by ISO: 100/800 0x3D9, 1600 0x9EC, 3200 0x60A, 6400 0x807, 12800 0xC03.
State: recipe G9B-QvQfkGVFwG9VCJRIvAfKGLKXoPyL0D7yK, ISO 3200; camera released.

## Release candidate 0.0.8test (18:30–19:15)
- Rule kept = v1 (pedestal term for all our 12/14-bit recipes, -0.375 for every 12-bit 1:1). Tried and REVERTED the
  same evening: exceptions for fast AD and the v35 gain band -- built from a few consecutive takes; the replay of all
  431 takes (tools/live/blk_replay.py) showed them worse (27 vs 11 takes worse than stock). The replay is now the gate
  for any rule change (mean <= 0.17, worse-than-stock <= 11).
- full tier: all mutants caught (apply 141, core 97, slqs 126, qsc 43, qsc-page 84, blv/blk-snap/blk-plan/menu/lv-fit);
  failures: test_site (the site copy still says 0.0.6test: pre-existing, regenerate at publish) and
  test_settings_migration frozen-bytes (0.0.7test's frozen copy is the other session's build) -> version bumped to
  0.0.8test (names_v4.py, build_slqs.py VERSION), frozen fixture added (sha 6abc1e9b...), 0.0.7test kept.
- Card: release-008/card (settings from the card's BIN), LOAD.LOG: 0.0.8test at 0xC52D4680 (0x37 claims), 0.0.7test
  and 0.0.6test skipped as older.  Reboot reconnected by itself in 12.9 s.
- Bei's recipe 12v2 6048x1700, lens capped: ISO 100 err -0.110 (was -1.221), ISO 3200 +0.137 (was -1.033).
- A failed REC can take a clip number and leave nothing (A001_520): take.py now probes past 3 gaps.
- State: recipe G9B-QvQfkGVFwG9VCJRIvAfKGLKXoPyL0D7yK, ISO 3200; camera released. Not published (merge page / site).
