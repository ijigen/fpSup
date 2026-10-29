# 20261027-push-bisect — why the push engine stalled after the report build, and the fix

Symptom (report-take-01/02/03): after the first push every later one was "busy" — the host had the image, but the
engine's last TRB still showed HWO=1. TRBs read back (pxdump.py): `[lo 0, hi 0x14, size 0x100, ctrl 0x15]`,
`[lo 0, hi 0x812, size 0x2D09D8, ctrl 0x813]` — lo zeroed, hi = ctrl without HWO.

| round | shell | ISPL | pushes | result |
|---|---|---|---|---|
| r1 | dev + USBFIX (9c760717) | 47b517be (reports) | LV only | **1 image**, same corrupt TRBs |
| r2 | dev, no USBFIX (a0095dd5 = take-03's) | 47b517be | LV only | **1 image**, same → not the USB fix |
| r3 | dev + USBFIX | **2212b38a (px aligned 64)** | LV only | **30 images, 98 MB**; TRBs `[lo hdr-DMA, hi 0, size 0, ctrl 0x14/0x812]` = proper write-back |
| r4 | dev + USBFIX | 2212b38a | LV + CDNG + reports + heartbeat | **39 images, 0 torn/resync**; reports rec / stopped / cdng (5) |

**Cause: the TRB array was not 16-byte aligned.** Adding the report fields grew ix_cap by 24 B and moved the engine
(px) inside wr_t to state +54296 (trb +54552, ≡ 8 mod 16). DWC3 reads/writes TRBs at 16-byte boundaries, so it took the
chain 8 bytes early: its write-back of "remaining size 0" and "ctrl without HWO" landed in our lo and hi, and our own
ctrl (HWO=1) was never cleared → busy forever. Earlier builds had px aligned by luck.

Fix: `ix_px_t __attribute__((aligned(64)))`; build.py refuses a build whose px.trb / px.hdr offset is not 16-aligned
(mutation: dropping the attribute → `BuildError: trb at state +54552`); the unicorn controller asserts a 16-aligned TRB
DMA address. 64/64 sup tests.

Also kept from this series: the USB descriptor fix (dev shell: FUN_c00327b8 3rd-endpoint MPS/interval immediates;
EP83 stays bulk 1024 / interval 0 across re-plug), and no EndTransfer on a timeout / at release.
Notes: the "armed" report and heartbeats are mode 0, so they are skipped while an LV push is in flight (seq gaps);
the heartbeat keeps going after the take until `disarm`.
