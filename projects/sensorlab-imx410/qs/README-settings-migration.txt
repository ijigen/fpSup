Offline settings migration for the v0.6.0test / QSContainer v0.3.0 upgrade

Both builders accept an optional complete previously saved BIN:
  python3 -B projects/sensorlab-imx410/qs/build_slqs.py --out /tmp/sl-upgrade --settings-from /path/to/SensorLab-IMX410_v0.5.0test.BIN
  python3 -B projects/qs-container/build_qsct.py --out /tmp/qsc-upgrade --settings-from /path/to/QSContainer_v0.2.4.BIN
The Python API is build(settings_from=path). Omitting it preserves the existing
all-zero default record and identical default BIN bytes. Each product owns
its own validation helper; neither imports the other's migration logic.

The source must be a complete loader-v4 BIN with the expected sup_id, config
magic/version and a bounded, aligned record. Header lengths, entry/block,
state/DMA ranges, record magic/version and FNV-1a checksum are validated before
compilation. A blank record, bare record file, other product, or unsupported
record/config version is rejected. This is integrity checking, not signature
authentication. Field semantics remain the compiled client's responsibility.
SensorLab: config SL42 v2, record SLQ2 v2, 65 words.
QSContainer: config QSC0 v4, record QSC1 v1, 83 words.

The validated record is placed during normal image layout at the new rec_off,
not patched into a canonical BIN afterwards. The output build JSON includes
settings_from: absolute source path, source length/SHA, source file/config
version, old record offset, record version/length/FNV/SHA. The normal output
SHA describes the new complete file. The source file is never written; the CLI rejects an output path that would
overwrite it. Choose a separate output directory to preserve the default build.

Reproducible offline verification from repo root:
  python3 -B projects/sensorlab-imx410/qs/test_settings_migration.py
Optional --fixture selects a directory containing both saved old BINs and a
manifest.json; --frozen selects independently frozen default BINs; --out
selects a separate result directory. The default fixture is the fresh
validation/20261030-takeover/preupgrade_backup, checked against its SHA manifest.
The default frozen directory is settings-migration/frozen, copied from the
independently tested final format-notify/client and container builds with a
source-manifest.json. Results include separate default/migrated BINs, build
metadata and report.json. Earlier equality against the pre-watcher freeze is
retained in settings-migration-before-format-notify/report.json.

Checks: default bytes versus frozen builds, only-record differences, exact
record preservation, 38 damaged-source refusals, 10 assertion-caught parser
mutations, real loader-v4 ARM boot/record load, all 63 SensorLab selection
words and actual ARM rec_pack round-trip, seven old named QS assignments,
corrupt-record runtime rejection and a user-changed stock placeholder retained.
The old explicit QS assignments remain supported even when the corresponding
new replacement function is hidden from the editor.

The emulator uses the established test_qsct/test_slqs file/UI/settings models
and explicit SD media/QR display test switches. Both sup entries, record
validation/restoration/serialization and the loader execute real compiled ARM.
No physical UI, firmware setting persistence, camera, USB or card access is
claimed. Successful boot migration does not authorize deployment. A later
live upgrade should rebuild from the freshly read source records.
