# v0.7.3test standby acceptance — 2026-10-30

Result: **NOT ACCEPTED**. Installation, hook initialization, standby commits and restoration passed. The returned screenshots have composition anomalies; they cannot establish that the physical LCD is correct. No recording or playback occurred. No camera freeze was observed.

Bei explicitly authorized writing the offline-verified candidate, preserving settings, rebooting, and checking standby LCD/QS proportions. Root exclusively owned USB; peer agents used local evidence only.

## Installation and preservation

- Fresh original SensorLab backup: v0.7.2test, 182944 B, SHA256 `61a2c57713263c4f688b2b4edfacce538633b0e3f88090276e0c93b6603d19e4`.
- Candidate built with this exact saved record: v0.7.3test, 183120 B, SHA256 `811b4473830ff316c7205f455f0e44edc35f814d53d96c7a29d6503818fe50f0`. Only the record differs from the offline default build. The 260-byte record is unchanged, SHA256 `e6901b0af056df0eff9c75fbe499d9e6fcc5cf8f129a448765e3dd0ebd62f658`.
- `deploy_v3.py` wrote and read back the whole candidate. Only then was the old SensorLab version removed. No AutoRun, loader or QSContainer deployment.
- Separate standard `ui_drive.py reboot`. Fresh `LOAD-current.LOG`: one SensorLab v0.7.3test, claims `00000027`; `sq_test21=0`.
- Standard reboot's host daemon child ended with its execution group. Confirmed no fpshd existed, started one detached instance, then native ping / idle / LOAD_DONE_US succeeded. This was a host-service failure, not evidence of camera freeze. No extra camera reboot was used for it.

## Actual standby cases

All used original 11-bit 3x2 recipe, key21, HMAX330, VMAX11468, FPS `72000000/3784294`; DC FREE, RES locked. Every case returned active1 / armed1 / result0 / gated0 / refusals0. Each pair includes QS, then stable LV after closing QS and waiting8s.

| Tag | DC | Actual raster | QS / LV screenshots | Captured-buffer observation |
|---|---|---|---|---|
| h4040 | 6048×4040 | 2016×1346 | SS2888 / SS2889 | Full-frame baseline |
| h3800 | 6048×3800 | 2016×1266 | SS2890 / SS2891 | Vertical repetition at row643; not clean centered letterbox |
| h3500 | 6048×3500 | 2016×1166 | SS2892 / SS2893 | Vertical repetition at row592 in LV and QS |
| w5088 | 5088×4040 | 1696×1346 | SS2894 / SS2895 | LV image x0..859, right remainder black; QS differs |
| w5008 | 5008×4040 | 1664×1346 | SS2896 / SS2897 | LV image x0..851, right remainder black |
| w4800 | 4800×4040 | 1600×1346 | SS2898 / SS2899 | LV image x0..811, right remainder black |

Effective image dimensions track the predicted custom aspect, but the returned JPEG origin/composition does not match a centered LCD viewport. For h3800/h3500, repeated rows reproduce the AF mark. These are measurements of the returned screenshots, **not independent physical LCD observations**. Bei subsequently replied「現在看不到相機」; no physical LCD observation is available. Offline investigation continues without another camera run. See `screenshot-review.json` for hashes, measurements and limitations.

## Restoration and final checks

Restored DC6048×4040 / raster2016×1346, original rate, recipe and locks. All63 resident selection words matched the pretest snapshot, not just visible dimensions; no resolution-memory entry was added. Closed QS and called the established stock-state operation, returning active0 as before testing.

`after-test/manifest.json`: full candidate file matched the fresh preserved-record build exactly; QSContainer, loader and AutoRun each matched their complete pretest backup byte-for-byte.

Because visual acceptance remained incomplete, restored the original v0.7.2test BIN from the fresh backup with full readback, removed v0.7.3test, and used a separate standard reboot. Final verification **passed**: fresh `LOAD-restored.LOG` locates v0.7.2test at `C55F9DC0`,37 claims, init0, CINE standby/recording0/active0; all63 selection words and all four complete files match pretest. See `final-verification.json`. The first final ping encountered a closed old USB handle; host inventory still found the camera, and the next bounded ping returned pong on the re-enumerated device. No reset/reboot loop or further camera mutation was used. Candidate and evidence remain local for diagnosis; this run does not promote v0.7.3test as a validated product.

## Next investigation

Trace capture source dimensions/stride and the actual LCD composition consumer beyond the fitter's returned rectangle. Existing native arithmetic/dispatch tests stop before final scanout and capture. Preserve the passing native ratio arithmetic tests, but do not use them as proof of complete LCD composition. No further live change is justified until this discrepancy is explained offline and actual LCD output can be distinguished from capture behavior.
