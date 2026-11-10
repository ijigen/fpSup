# fpLossless — standalone lossless RAW compression

## 2026-10-12: independent lossless module with adaptive batch count

The current builders produce an **offline development candidate**, including
the menu, native recording hooks and shared loader. The older status below is
retained as history. This increment has not been tested on a camera.

- Keep the stock **64 MiB** byte target. A second native flush trigger limits
  frames in a batch to half the available descriptor budget, after reserving
  two stop slots, four pipeline slots, and arrivals during a writer return.
  FPS is rounded upward; the initial return allowance is **100 ms**, then only
  increases to the longest observed return in that take. These reserves are
  policy assumptions pending hardware measurement, not a no-stall guarantee.
- Actual mixed RAW/compressed bytes drive the existing byte trigger. A rolling
  32-file sample reports compression fraction, mean file size and the estimated
  frames needed for 64 MiB. The estimate never relaxes the count/free-slot
  guards. Resolution and RAW fallbacks are thus reflected in actual file sizes.
- The count hook applies only to the current admitted lossless writer frame
  with the stock CinemaDNG callback. Low/unknown free descriptor counts force
  an earlier native flush. OFF and unrelated filesystem calls retain their
  original count decision.
- Flush metadata now checks the native frame pointer and generation as well
  as the file buffer address; reused addresses retire mismatched metadata
  without freeing live memory or applying a previous frame's compressed header.

The batch hook is guarded, journaled, exclusively claimed in v3 and restored on
shutdown. LOSS builds, loads and runs its tests independently of other optional
sup modules. The module package contains `10LOSS.BIN` and its build/layout
metadata. Cross-module checks are maintained separately in `integration_tests/`.

Build from `fpSup/` into a new empty directory:

```sh
python3 -B lossless/build_v3_lossless.py --out /absolute/new/directory
# Add --trace for diagnostics, or --card for a complete shared-loader card.
```

Focused offline tests:

```sh
cd lossless/native
python3 -B -m unittest test_bulk_policy test_frame_hold test_record_diag
cd ..
python3 -B -X faulthandler -m unittest test_bulk_native test_v3_lossless test_card_emulation
```

`card_status.py` reads the matching build's `layout.json` and reports batch cap,
FPS reserve, pool pressure, mixed file statistics and retired stale metadata.
Source changes, exact candidate bytes, validation logs and hardware limitations:
[`20261012-lossless-independent`](../../projects/lossless-sup/validation/20261012-lossless-independent/).
The updated mechanism is also recorded in
[`EARLY_STOP_94.md`](../../projects/lossless-sup/notes/EARLY_STOP_94.md).

## Historical status — 2026-09-30

Development source, **not an installable recording product**. No AutoRun,
VSHL, firmware patch or camera deployment is emitted by this directory yet.
The current development entry (2026-09-30, §14), evidence limits and next gates are in
[`PROGRESS_20260930.md`](../../projects/lossless-sup/notes/PROGRESS_20260930.md).
The adjacent `IMPLEMENTATION.md` is a chronological history, not the current
verdict.
Buffer/lifetime notes and historical design alternatives are in
[`BUFFER_DESIGN.md`](../../projects/lossless-sup/notes/BUFFER_DESIGN.md).
The 2026-09-29 synchronous probe wrote decodable compressed DNGs. The historical
async probe copied earlier-frame output into a later frame; its driver now
unconditionally refuses `arm`, including direct API calls. The new
`frame_pipeline.c` implements a single-pending-frame adaptive policy with saved
source/file identity, but has no native hold/defer/handoff adapter. Source
lifetime, source-tail coverage, safe release and all-format capacity remain
integration gates. Busy frames pass as RAW; no source frame is deliberately
dropped. Submit return is not a buffer-release fence.
Follow [`SUP_BUILD_RULES.md`](../SUP_BUILD_RULES.md) for builds; notify the user
before camera testing and obtain authorization for that run. This increment
includes host and ARM-emulated tests, not a card build or camera validation.

Current requested test card: **direct compression + current USB shell + Fast
Start 2**, without menu, OG or gyro. `fpl_begin_direct` is implemented for the
real REC boundary: it omits only UI readiness and preserves every capture
proof. It does not install a recorder hook or make unverified geometry ready.
There is not yet a deployable card; `requested_test_build` in the manifest is
the requested scope, not an artifact receipt. USB shell must remain enabled in
the shared build; a shell-only card is not a Lossless build.

The REC-before-frame workspace is now implemented in `native/rec_workspace.c`,
with geometry-derived layout and native RAW/class 10 allocation wrappers. It
calls original REC preparation before reserving, rechecks producer facts and
source headroom after reserving, and separates stop from quiescent release.
This adapter has compiled-C integration tests and ARM object builds; the RAW
wrapper additionally executes original descriptor instructions in Unicorn.
It is **not installed at the REC call site**, has no native facts provider or
compression worker, and does not prove DMA output limits. Layout arithmetic
includes 14-bit, but the recording control still rejects 14-bit. Reproduce with
`native/build_workspace_offline.py`; see [native details](native/README.md).

Deferred UI: **SHOOT page 2 (CINE)**, alongside DC crop, recording settings
and audio recording, with a dedicated **Lossless RAW / 無損壓縮: OFF / ON**
row. Existing entries retain their original meanings. The private binding name
is `MV_fpLossless`. An offline fourth-row resource builder now exists in
`menu/`; `native/` contains executable ARM variable-call wrappers and, in
`native_port.c`, the `fpl_binding_ops` adapter that routes a native variable
event into policy. The opt-in `native-permission-gated` resource adds separate
private Cursor and Confirm bindings; the port refreshes confirmation permission
without treating a cursor move as a saved preference. `loader/native_reader.c`
now bridges real ARM32 reader fields to the original parser. Native row
installation, rendered-view publication, outer reader lifetime protection and
the exclusion/quiescence providers remain pending. No menu is installed on a
camera by these changes, and this port still refuses to supply `FPL_READY_UI`.

This is an independent product. It does not select a sensor mode, alter crop,
exposure or bit depth, or include OpenGate patches. Future OG2K/OG3K combinations
must be produced exclusively by `tools/card-composer` (fp-Merge). File/range
compatibility alone will not certify recording or playback compatibility.

## Implemented control core

`control.c` is a portable, freestanding C core for a future firmware adapter:

- private OFF/ON state, default OFF after a quiescent boot reset;
- no setting changes while a take is active;
- actual 10/12-bit CinemaDNG geometry candidates, including representative
  1K/2K/4K/6K sizes, positive frame rate and SD; bounded to 160 tiles;
- separate UI, codec, writer, header, playback, storage and REC-gate proofs;
- a second eligibility check at REC, catching mode changes after ON was chosen;
- a separate no-menu `fpl_begin_direct` REC entry; no fabricated UI bit and no
  UI binding instance in that build, with the same capture/format/fault checks;
- no implicit OFF when ON fails readiness; during a ready adaptive ON take,
  busy frames intentionally pass as RAW and keep their original identity;
- sticky error and explicit completion/cleanup before returning to idle.

The core does not itself provide atomic locking, DMA ownership, codec unwind,
menu drawing, parameter persistence, recording interception or playback. Its
caller must serialize access and derive readiness from verified adapters. No
production adapter currently supplies those proofs; ON must therefore remain
unavailable on an actual camera, rather than claim to compress while writing RAW.

The capability check deliberately uses the producer's actual dimensions and
packing rather than `M139`, `M98`, or an OpenGate display label. Additional
validated geometries can be added without building a separate compression
product per resolution. FHD is the first test case, not the product identity.
Candidate eligibility is not per-format support: the adapter must recompute
all readiness proofs for the exact geometry/packing/rate/media tuple. This
increment does not add 14-bit support or change sensor modes.

`frame_pipeline.c` is the small task-context policy behind adaptive compression:
one saved lease, no pending-frame queue or full-frame pool, no 40-frame stop.
OFF is all RAW. ON selects an idle arrival only after same-frame hold/defer
proof; busy arrivals pass untouched. Completion cannot release the lease until
codec quiescence and same-frame native handoff are proven. A valid result that
does not reduce the **complete DNG** size instead hands off the unchanged source
as RAW and continues. Real errors retain ownership and require cleanup.
Stop drains the last selected frame without requiring another incoming frame;
old take/session callbacks and inline handoff reentry are rejected. Counters
saturate without ending recording. The adapter must serialize calls, preserve
source metadata/filename, and never retain the stack-local stock writer at
`C03A5490`. None of those native adapter proofs are fabricated by the policy.

`ui_control.c` provides the corresponding lifecycle policy: CINE/MainB2-only
visibility, explicit confirmed OFF/ON events, stale-owner/generation/session
rejection, duplicate-attach protection, and recording-time lockout. A new boot
session invalidates old callbacks even if an owner address is reused. The native
adapter must supply non-reused tokens and actually unsubscribe/drain events;
this core cannot prove that on its own. It does not create the row.

## Offline checks

`python3 -B -m unittest discover -s tests -v` compiles this exact core for the
host, executes state transitions, and cross-compiles for ARMv7 with clang
(`-mfloat-abi=soft -mfpu=none`; no FP/NEON dependency). The view API uses an
explicit output pointer rather than an aggregate-return ABI. The initial
control/lifecycle suite covers all 128 readiness combinations and a 10,000-frame
control run. Compiled-C pipeline tests include a 1,200-frame run, OFF/ON
integration, error cleanup, stale tokens and mutation controls.
`tests/test_frame_pipeline_arm.py` additionally runs the actual compiled ARM
instructions with strict external-call checks, saved-register/SP checks and
an explicitly synthetic handoff. It uses the existing checked ELF extractor,
not a new linker or loader. A failed JIT is a test failure, not a silent pass.
These are not execution on the camera CPU or native buffer ownership proof.
It performs no camera or USB operations and fails if the compiler is missing.

Common codec research remains in `research/slimRAW` and `research/imaging-hw`.
Integration evidence and product decisions belong in `projects/lossless-sup`;
`notes/ROADMAP.md` is canonical for current gates.

The shared `research/ui/tools/native_ui_audit.py` verifies the pinned stock
MainB2 page and reports its row/allocation structure. It passes 15 additional
tests with the explicit pinned firmware, but does not add the fourth row.
The `menu/` builder now emits a complete expanded MainB2 resource fragment and
private string pool, **not a firmware image or installable card**. Its default
`pure-fixed-gated` profile adds a generic two-choice stock control as the fourth
CINE row, with literal **Lossless RAW / OFF / ON** and five private variable
references. It preserves the original three rows, stock string offsets and
allocation reserves, and remaps only typed object references. The original
Audio-clone profile remains a gated structural comparison, not the product UI.

The shared component-schema tooling covers all 18 ordinary kinds used by the
row, including unaligned strings and drawable common fields. The native
variable probe additionally passes 15 original-instruction tests with explicit
Lua/allocator substitutes. It confirms that registration failures are **not
transactional**; retries require a real recovery design.

The default row uses fixed popup geometry and explicitly disables its stock
sync request; it no longer reads shared popup width. The menu/recipe suites
pass 35 + 8 tests. Width 320 is a design choice, not measured camera rendering.

`binding/` adds a tested coordinator for registration ownership, private value
publication, rejected-choice restoration and subscription retirement. Native
callback return does not veto assignment; failed publication can leave ON
visible. The `FPL_BLOCK_REC` context bit therefore blocks RAW as well as lossless
REC while state is uncertain. In a UI-enabled build use the mandatory
`fpl_binding_begin` entry; do not bypass that binding with a separately
constructed context. The separate no-menu test build must not attach this UI
binding and uses `fpl_begin_direct` with fresh producer facts. Its 30 tests use mock
port operations plus ARM compilation, not the native GUI.

`loader/` adds a normalized reader-view lease with 53 sanitizer-tested groups,
exact candidate pins and retained string-pool lifetime. It is not a native
parser struct, hook or cache adapter. The original-instruction binding probe
adds 18 tests with explicit substitutes; actual widget callbacks are not run.
Rendering, navigation, native port functions, loader ownership and actual
allocation remain unverified. An offline
structural pass must not enable ON or bypass any codec/writer/playback gate.
The native call layer passes 23 compiled-ARM-to-original-instruction tests.
`native/native_port.c` implements the port contract over it: 22 scenarios run
twice each (host -O2 and an ASan/UBSan executable) against the real
coordinator, UI policy and control sources, plus an ARMv7 Thumb soft-float
compile with no libc, FP or compiler-runtime dependency. This port can never
claim `FPL_READY_UI`, so ON stays unselectable; without caller-supplied
exclusion and quiescence providers it reports FPL_BUSY and refuses to retire a
live subscription. Four injected defects each fail the suite.
Further shared probes cover lazy page selection (16 cases) and input/property
boundaries (14 cases). These expose two integration hazards: parser nonzero
returns can publish an incomplete root, and disabling a key does not cancel an
already-active repeat. The current page candidate is intentionally unchanged.
See `native/README.md`, `menu/README.md`, the canonical
`projects/lossless-sup/notes/ROADMAP.md`, and the historical
`projects/lossless-sup/notes/IMPLEMENTATION.md`.
