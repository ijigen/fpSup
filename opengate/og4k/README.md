# OG4K-4000 experimental core

Target: SIGMA fp V5.02, **4016×2676 RAW12, 4000×2666 crop, 24.000 fps**,
M151 with the native M3 full-height front end, RAW RWZM 1536/1024.

This directory contains executable ARM routines and offline tests. It does
not contain a camera installer, registered firmware hooks, UI entries,
AutoRun/VSHL package, or a released recording mode. Camera and USB were not
used for this implementation.

## Implemented

| Routine | Behavior |
|---|---|
| `transition(state, action)` | Guard and switch the ten reviewed M151 geometry/receiver/input-window words; retain exact-24 timing; verify every write; restore the prior snapshot after failure |
| `record_canvas(canvas, request)` | Change eight RAW fields on a private p429 canvas only for the exact CINE/24p/RAW12/crop-off request |
| `playback_canvas(canvas, frame)` | Adapt a p71 UHD12 movie canvas to the exact OG4K file raster and crop, independent of current recording selection |

`core.S` is position independent with respect to its code and state. Its ten
firmware data addresses are specific to the pinned V5.02 image. `core_build.py`
assembles and inspects it without opening any transport. No code-cave address
has been reserved and no hook is published by this builder.

### State and failure behavior

`transition` accepts a four-word caller-owned state:
`{magic=0x4B34474F, enabled, error, busy}`.

- Action 2 is boot recovery. It ignores stale state, accepts only stock/our
  known values in all ten words, restores stock, then initializes fresh state.
  Unknown words or changed exact-24 timing cause refusal before data writes.
- Actions 0/1 disable/enable. They require initialized, idle state and a
  complete matching stock/full-height data set. Repeating an action is valid.
- Preflight refusal leaves state and firmware data untouched.
- A dropped write triggers rollback of all ten pre-call values. Successful
  rollback restores the previous enabled state. If rollback fails, magic is
  invalidated and normal actions refuse until boot recovery succeeds.
- The new enabled state is published after readback. IRQ/FIQ masks and
  callee-saved registers are restored. No allocator pointer survives in state.

Return codes: 0 success; 1 invalid/unowned/busy request; 2 unexpected data;
3 foreign timing; 4 write failure with successful rollback; 5 rollback failure.
Boot recovery returning 4 also invalidates state because its starting data may
have been a known partial mixture.

The future firmware adapter **must quiesce capture/reconfiguration before this
routine and perform the required cache publication**. Local IRQ masking does
not stop DMA, another CPU, or a task which already owns an in-flight frame.
These routines alone do not establish whole-camera warm-restart safety.

### Private canvases

Only a private RAM copy may be passed to either canvas routine. Successful
record preparation changes +00/+04 (RAW raster), +24/+2C (active crop),
+DC/+E4 (RAW override), and +64/+D4 (RAW RWZM). The shared profile table is
never edited. +D8/+E0 belong to preview and are preserved.

The record request is a validated nine-word adapter input:
`{magic, selected=1, profile=429, mode=151, fps_num=24, fps_den=1, bits=12,
crop=0, cine=1}`. Each predicate is tested; no live firmware adapter supplies
it yet. Other fps/bit depths must be disabled or rejected by the eventual UI
and picker adapter before recording; falling back silently is unacceptable.

The playback input is a validated ten-word DNG metadata record:
`{magic, compression=1, bits=12, W=4016, H=2676, cropX=8, cropY=5,
cropW=4000, cropH=2666, stripBytes=16120232}`. There is no parser shim yet.
The current routine accepts the p71 UHD12 donor geometry/class and 1× reduction
factors only. It refuses the FHD p73 donor, which retains different reduction
factors. The future picker must select the correct donor from file metadata.

Both routines return 1 when applied, 0 for unrelated metadata/settings, or
2 for a donor mismatch. All guards run before the first canvas write. A return
of 0/2 is not permission for an adapter to start a take with mismatched state.

## Offline verification

Run with Python, clang, and Unicorn available:

```sh
python3 -B core_build.py
python3 -B -m unittest -v test_core.py test_core_review.py
```

The emitted ARM code is executed against synthetic RAM and the pinned firmware
image. Tests cover all 1,024 combinations of known partially retained front-end
words, repeated on/off, all four IRQ/FIQ masks, each dropped write, rollback
failure, invalid/busy/unowned state, publication order, unchanged shared profile
data, and recording/playback metadata rejection.

Project integration evidence and original-firmware emulation live under
`projects/open-gate/build/og4k_offline`; notes are in
`projects/open-gate/notes/OG4K_SIZING.md` and `OG4K_IMPLEMENTATION.md`.
Run `projects/open-gate/build/og4k_offline/run_offline.py` for the combined suite
(paths relative to the workspace root, not this repository). This includes
native profile construction -> this ARM core -> native RAW descriptor ->
recording descriptor copy -> original allocation request. Runtime profile
selection and physical pool availability remain outside that proof. The
combined runner rejects missing Unicorn and skipped checks.

## Outstanding integration

The UI/picker and canvas call-site adapters, capture quiescence, cache and hook
lifecycle, record ring/pool availability, actual DNG metadata propagation,
and live playback routing remain to be integrated or demonstrated. Sensor
electrical behavior, RWZM filtering/Bayer phase, optical coverage, exposure,
and sustained storage throughput require later camera tests. No claim of
image-quality improvement or camera readiness follows from offline tests.
