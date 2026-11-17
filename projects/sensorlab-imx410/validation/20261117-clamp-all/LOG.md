# 2026-11-17 — 0.0.9test: video clamp on for every recipe; output acceptance (raw_accept.py)

Change: apply/ap_calc.c ORs R38 +4 bit 3 and +0x18 bits 14-15 into every recipe's row (the formula set them only for
a 1.7..2.0 readout). Offline: apply suites 122 OK, test_blv mutants caught, tools/test.py full 843 jobs OK, blk_replay PASS.
Card build: card/ (sha16 eedbef369fe5ffc9, settings carried from the card's 0.0.8test), LOAD.LOG block 0xC52D4480.

## Live, lens capped, 3 s takes, frames 6.., ISO 100 and 3200 (accept/results.jsonl, accept-nonhd.log)
- smoke (4 recipes x 2 ISO): all pass. 6048x2020 14-bit 1x2 (Bei's flickering clips): max deviation 0.002-0.003 DN12
  over 16-18 frames (before: ~half the frames 0.25 off), mean - tag -0.11 / +0.05.
- nonhd (36 coarse strata without the formula's clamp x 2 ISO = 72 takes): 63 pass.
  Passing takes: |mean - tag| mean 0.103, max 0.274 (0.0.8test worst case 0.66); all steady.
- 9 failing takes, 5 recipes:
  1. SQ 1024x1024 RWZM 12-bit and 14-bit AD (F-B-AQAQAAaXQG9UiIJIPwP2MUyPwPwH4H4BM, F-B-AQAQA8QMgNmkiIBIPwP2YGIPwPwH4H4E8):
     compressed frames decode (rawpy) with 258 all-zero rows (rows 1, 3, 7, 11, 15 ...); frame 1 (uncompressed) clean.
     Known since 11-16 on 0.0.7test. Not yet decided: codec output or the decoder.
  2. 6048x4040 12-bit fast (G9B-Reg_IAcEQGiEiIZJeQ--LmYXoPyL0H5C-): the clip has 2 frames on SD (36.7 MB + 7.7 MB);
     both dark and on the tag. Tool now reads short clips from frame 2 and reports steadiness as not judged.
  3. APS-C 1312x874 3x3 fast (F7hSAUgNqAjjQFKNiI5IUQNgCBMPcKQCmBtjC) ISO 100: 5 of 40 frames carry a bright band
     (top 3/16 at ~1600 DN12, lens capped). ISO 3200: 0 of 40.
  4. APS-C 3952x874 12-bit 1x3 fast (F7hSA9wNqAjjQFKFiMBI9gNgCF6PcKQHuBtkS): 36 / 32 of 40 frames carry bands
     (140..1185 DN12 above the tag; e.g. the lower 9/16 of the frame). The bad frames compress to 3.2 MB vs 1.1 MB.
     NOT new: 11-16 takes/p1-f12v3---11-iso100/f3.DNG (0.0.7test, clamp off) has rows 1680 1028 256 ... = the same.
  Samples: diag/.

## Incident 18:01 — camera stopped answering, battery pull
For an A/B I deleted 0.0.9test from the card (fl del), rebooted into 0.0.8test (LOAD-ab008.LOG) and started
raw_accept --only f12v3,3x3fast with the 0.0.8test build json. First take (3x3fast ISO 100): after rec_take.sh the
status read gave no answer ("STILL RECORDING: stopping"), the restore's mem readback was all None. No clip was made
(newest stayed A001_097 = the nonhd run's last take). Bei: "畫面出現一堆直線", pulled the battery.
Last actions sent: menu SetIso 100; sq_test 41/43/41/19 with the 3x3fast code; 4 s; newest_clip probes; rec_take.sh 3.
Not known: whether the freeze was at the recipe push or at REC; why (the same recipe recorded twice today on
0.0.9test and 3 times on 11-16). Not retried. After the pull ptpcamerad held the interface while stale fpshd clients
were still listed, so daemon_restart_log.ptp_claimant() returned None -- a gap in that check (to fix).
0.0.9test redeployed 18:05 (LOAD-2.LOG), recipe G9B-QvQfkGVFwG9VCJRIvAfKGLKXoPyL0D7yK ISO 3200 restored.

## Not tested
Lit-scene colour / linearity; frames past the first 40; takes over 3 s; heat; MOV; 8 / 10-bit; ISO other than 100 and
3200; the 36 strata that already had the clamp (only 2 smoke recipes of them); the 106 fine strata not in the coarse plan.

## 18:10-18:31 — the remaining failures are the Lossless sup's (0.3.2test), not Sensor Lab's
- Garbage is in the SOURCE the encoder read, not a broken stream: A001_094 frame 7 (3952x874, tiles 512x448): the 8
  tiles of row 1 are ~110 KB each (70 KB in a clean frame) and the 8 of row 2 ~300 KB; the garbage starts at row 397,
  not on the tile boundary 448. A001_076 frame 8 (1312x874): rows 0-162 (~320 KB) look like compressed data.
  In 094 the garbage has 12-byte structure (IFD-like).
- Lossless counters after an f12v3 1:1 take (diag-f12v3b/lossless-status.txt): held 64, compressed 48, no benefit 16,
  zero copy swapped 48, declined 0, undone 0, faults 0, stalls 0, tile grid 512x448.
- **Lossless OFF (fpSup page, UI), same recipes, ISO 100, 40 frames each (lossless-off/results.jsonl): all pass** --
  f12v3 1:1, 3x3fast 1:1, SQ 1024x1024 RWZM 12-bit and 14-bit AD (no zero rows, mean - tag -0.16 / -0.03).
  Lossless set back to ON afterwards (screenshot 183119).
- Which recipes: fast AD (11b) x vertical merge 3 x no RWZM (874 rows): f12v3, 3x3fast. Fine: 12v3 1:1 (12b, 874
  rows), f12v2 1:1 (1312 rows), 2x2fast, 12fast. All at 23.976 fps (vmax 9101). SQ 1024x1024: tiles 512x512, 2x2, no
  padding; zero rows per tile = row 1 and rows 3, 7, 11 ... 511.
- Working guess, NOT proven: after a zero-copy swap Lossless keeps the frame's old allocation as its spare and the
  firmware still uses that allocation in these modes, so the next compressed output lands in a live source frame.
- Not done: a Lossless build without the swap; any Lossless change.
