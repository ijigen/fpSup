SensorLab QR offline verification (2026-10-30)

Run from the repository root:
  python3 -B projects/sensorlab-imx410/tools/qr/verify_qr.py --jobs 2

The default report directory is:
  projects/sensorlab-imx410/validation/qr-offline-20261030/
Override it with --out PATH. --baseline-only omits mutation checks.
Unicorn requires local JIT execution; this environment's filesystem sandbox
traps inside Unicorn initialization, so the exact command is run through the
approved local execution path. No USB, camera, card or deployment is involved.

Dependencies: the existing Python environment with Unicorn and numpy; clang
for the project's normal offline build; node for the preview comparison; the
local out/MAIN_c0000000.bin firmware image. Nothing is downloaded or installed.

OpenCV is OPTIONAL. If installed in this interpreter, or in the interpreter
selected by SLQS_CV_PYTHON, it independently decodes the generated image as an
additional check. SLQS_REQUIRE_OPENCV=1 makes its absence an error. The report
states which path ran. No temporary/scratchpad virtual environment is assumed.

qr_v5_reference.py provides the fallback and runs even when OpenCV is present.
It is a deliberately bounded pristine-matrix verifier: 37x37 V5-L, one byte
segment, upright integer scaling, exact black/white pixels. It verifies fixed
patterns, both BCH format copies, all eight masks, the seven remainder bits,
all 26 Reed-Solomon syndromes, length, terminator and canonical byte padding.
It does not correct corruption, detect a code in a photo, rotate/threshold or
rectify perspective. A successful parse is NOT evidence of optical/phone/LCD
scannability. Physical scanning remains a separate on-camera validation item.

test_qr_v5_reference.py checks the verifier on a captured offline ARM fixture,
all eight remaskings, scaled renderings and deliberately corrupted symbols.
The fixture comes from slqs.c and is labelled as such; the verifier is a
separate structural/parser implementation, not an independent optical result.
The RS syndrome evaluation differs from the C encoder's generator/remainder
calculation. Layout was cross-checked with Project Nayuki's primary source:
  https://www.nayuki.io/page/qr-code-generator-library
  https://github.com/nayuki/QR-Code-generator/blob/master/python/qrcodegen.py

verify_qr.py first requires a passing, zero-skip baseline: verifier unit tests,
QR payload/C/observer tests and Preview 15/16. Then each QR mutation must compile
and fail its explicit focused test. A compile error, missing pattern, missing
dependency, skipped test, timeout or absent machine-readable result cannot
count as a caught mutation. Mutants are temporary copies; slqs.c is unchanged.
The report records source/firmware hashes and per-case transcripts.

Gaps closed in the 2026-10-30 pass:
- The old ISP-window swap mutant survived the focused payload test, because
  scw/sch/ww/wh were not asserted; now all four match the Python quality planner.
- Other-layer drawing is explicitly rejected using wrong width/height cases.
- The shadow-never-learns mutation formerly failed to compile (unused dirty);
  it now compiles, so the triple-buffer assertion can actually exercise it.

emu_qr.py, emu_qr2.py, emu_y8.py and emu_ver.py are historical stock-V20
explorations, not this verification entry point. Some still contain legacy
absolute/scratchpad output paths; no current verification imports or runs them.
