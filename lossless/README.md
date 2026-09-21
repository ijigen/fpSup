# fpLossless — standalone lossless RAW compression

Development source, **not an installable recording product**. No AutoRun,
VSHL, firmware patch or camera deployment is emitted by this directory yet.

Requested UI: **SHOOT page 2 (CINE)**, alongside DC crop, recording settings
and audio recording, with a dedicated **Lossless RAW / 無損壓縮: OFF / ON**
row. Existing entries retain their original meanings. The private binding name
is `MV_fpLossless`. An offline fourth-row resource builder now exists in
`menu/`; `native/` contains executable ARM variable-call wrappers and, in
`native_port.c`, the `fpl_binding_ops` adapter that routes a native variable
event into policy. Native row installation, rendered-view publication, choice
permissions and the exclusion/quiescence providers remain pending.

This is an independent product. It does not select a sensor mode, alter crop,
exposure or bit depth, or include OpenGate patches. Future OG2K/OG3K combinations
must be produced exclusively by `tools/card-composer` (fp-Merge). File/range
compatibility alone will not certify recording or playback compatibility.

## Implemented control core

`control.c` is a portable, freestanding C core for a future firmware adapter:

- private OFF/ON state, default OFF after a quiescent boot reset;
- no setting changes while a take is active;
- exact first-target eligibility: FHD RAW12 / SD / 24000/1001;
- separate UI, codec, writer, header, playback, storage and REC-gate proofs;
- a second eligibility check at REC, catching mode changes after ON was chosen;
- no silent compressed-to-RAW fallback within a take;
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
control/lifecycle suite contains 32 unique passing tests, including all 128
readiness combinations. Host execution plus ARM compilation is not execution
on the camera CPU.
It performs no camera or USB operations and fails if the compiler is missing.

Common codec research remains in `research/slimRAW` and `research/imaging-hw`.
Integration evidence and product decisions belong in `projects/lossless-sup`.

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
REC while state is uncertain. Use the mandatory `fpl_binding_begin` entry; do
not bypass it with a separately constructed context. Its 30 tests use mock
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
See `native/README.md`, `menu/README.md` and
`projects/lossless-sup/notes/IMPLEMENTATION.md`.
