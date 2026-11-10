# Clean snapshot: SensorLab-IMX410 v0.7.37test (2026-11-05)

This is the known-good state before any CPU ×2 (ISP HBIN hbin = 2) work. Restore from it if the CPU route is dropped. Bei: "到時候 cpu 這條路走不通要從 sensor lab 中移除".

## What it contains

- **`source/sensorlab-imx410/{core,apply,qs,preview}`** and **`source/isp-lab/host/{quality.py,matrix.py}`**: copied right before the CPU ×2 recipe-core edits began. Build outputs, caches and pickles are left out.
- **What this version does:**
  - v0.7.37test boot apply: the commit at sup_entry, RES-Custom's way.
  - All earlier v0.7.3x features (QR scan, RES display, dial hint).
- **`default-build/` and `card-settings-build/`:** the exact BINs built and deployed today.
- **`QSContainer_v0.3.8.BIN`:** the container that goes with it.

## Proof that it is the deployed source

The source was rebuilt in a temporary tree made of this snapshot plus the untouched siblings. Its default build is byte-identical to the frozen fixture and the deployed default build:

`SensorLab-IMX410_v0.7.37test.BIN 206048 B sha256 23c76320f62977d4447303af9a0e643f7950bd5cdb59f6fd4d3aee33df81448a`

Live tests (see `../20261105-boot-apply3/README.md`):
- cold boot and warm poff both applied with no key: `entry_rc=0`, `active=1`;
- RES and dial-guide checks still pending.

## Files the CPU ×2 work changed after this snapshot

- `core/{core.c,core.h,core_data.h,export_core.py,test_core.py}`
- `apply/{ap.c,ap_calc.c,test_apply.py}`
- `qs/test_resmagnet.py`
- `preview/{fps_data.js,test_web.py}`
- `isp-lab/host/{quality.py,matrix.py}`

New files:
- `notes/CPU_X2_DESIGN.md`
- `tools/cpu_h2/`, which is independent and can be deleted with the feature.

## To restore

```sh
cd projects/sensorlab-imx410
for d in core apply qs preview; do rsync -a validation/20261105-clean-v0.7.37test/source/sensorlab-imx410/$d/ $d/; done
cp validation/20261105-clean-v0.7.37test/source/isp-lab/host/*.py ../isp-lab/host/
```
