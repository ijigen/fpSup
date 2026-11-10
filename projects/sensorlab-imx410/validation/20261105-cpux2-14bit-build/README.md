# CPU ×2 live throughput probe (2026-11-05)

Card: SensorLab v0.7.38test, card-settings-build sha256 4952a391… (settings from live/readback-v0.7.38test.BIN, bc625c71…).
Default build (no settings) sha256 059b9980…. Boot apply OK (sq_test 46 done=1 entry_rc=0). Current recipe not CPU ×2 (ap_h2 armed 0).

## sq_test 50 (ap_h2_bench), 8 MiB class-0 buffer (16 MiB refused), 6048 px line, standby, no recording

| kernel | cached | no cache maint | uncached (0x4…) |
|---|---|---|---|
| 12-bit h2_p12 | 103.4 MB/s | 114.4 MB/s | 19.7 MB/s |
| 14-bit h2_p14 | 71.1 MB/s | 73.7 MB/s | 15.0 MB/s |

Needed (OG 3K 25p): 12-bit ≈ 457 MB/s read, 14-bit ≈ 533 MB/s. Short by 4.4× / 7.5×. CPACR 0xF00000.

## Ceiling: firmware memcpy FUN_c001510c, cached, 4 MiB → 4 MiB, host-timed minus an empty call

≈ 21–27 ms → ≈ 155–200 MB/s copy (≈ 310–400 MB/s total bus traffic). A perfect bin pass moves read R + write R/2,
so its ceiling is R ≈ 210–270 MB/s, still ~2× under 457 in standby, before recording's own DMA load.

Verdict: CPU ×2 cannot run OG 3K at 25p (12 or 14 bit). Stopped per the note's rule (cached < ~460 MB/s); no take recorded.
