# CPU ×2 archive: SensorLab-IMX410 v0.7.38test with ISP HBIN "CPU ×2" (hbin 2), 2026-11-05

This archive holds the full CPU ×2 source state before the feature was removed from the product. Bei asked to keep the code ("保留代碼").
It was removed because the live probe measured 103 MB/s (12-bit, cached) against the 457 MB/s that OG 3K 25p needs, and the firmware memcpy tops out at about 200 MB/s.
See `../20261105-cpux2-14bit-build/README.md` and `notes/CPU_X2_DESIGN.md` (D9).

## Contents

- `source/sensorlab-imx410/{core,apply,qs,preview}`: sources only, with `build/` and `__pycache__` left out.
- `source/sensorlab-imx410/tools/cpu_h2/`: a copy of the kernel tool. It also stays in place in the tree.
- `source/sensorlab-imx410/CPU_X2_DESIGN.md`: a copy of the design note as it was.
- `source/isp-lab/host/{quality.py,matrix.py}`: the CPU ×2 recipe core on the Python side.

## Proof

These sources were rebuilt in a temporary root: this archive, with symlinks to the untouched repo siblings (fpSup, qs-container, the rest of isp-lab and sensorlab-imx410).
The default build is byte-identical to `../20261105-cpux2-14bit-build/default-build`:

`SensorLab-IMX410_v0.7.38test.BIN 214044 B sha256 059b99802be7f68d5faf48a15d0fe4f7404a498eb887cc6ca2bbc60e39c0648a`

## To restore

The product went on to v0.7.39test after this archive, with non-CPU fixes kept. Restoring the archive over the tree puts those changes back to their v0.7.38test state.
Diff against the current tree first, then merge by hand. For a blunt restore:

```sh
cd projects/sensorlab-imx410
for d in core apply qs preview; do rsync -a validation/20261105-cpux2-archive/source/sensorlab-imx410/$d/ $d/; done
cp validation/20261105-cpux2-archive/source/isp-lab/host/*.py ../isp-lab/host/
```
