# fpLossless — offline reader-view lease adapter

This is a bounded C model for selecting the complete private MainB2 page and
private string pool during a first parse. **It is not a real hook, native page
loader, native cache controller, firmware patch, or deployable product.** It
makes no camera calls and emits no VSHL, AutoRun, installer, or merged artifact.

The pinned `pure-fixed-gated` candidate adds the CINE-only `Lossless RAW` / `OFF`
/ `ON` row, with the shared popup-width/sync dependency removed by its builder.
It has 179725 page bytes / 1538 records and 176240 string-pool bytes; the earlier
`pure-select-gated` candidate is deliberately rejected, not accepted as fallback.
Existing STILL records within MainB2 are preserved by its separately audited
builder. Selection here is MainB2-only (GUI page ID 10, not handler ID 0x1F);
QS and other pages pass through without modifying the reader. CINE/STILL runtime
visibility is not implemented by this adapter; it remains encoded in the page.

## Run the reproducible offline checks

```sh
python3 -B /absolute/path/run_tests.py \
  --seg0 /absolute/path/seg0_c0000000.bin \
  --candidate /absolute/path/mainb2-pure-fixed-20260916
```

The candidate directory must contain `MainB2.fpLossless.gated.page` and
`MainB2.fpLossless.strings`. These plus seg0 must match the hard-coded SHA-256
and length pins, irrespective of any candidate manifest. The runner
compiles and runs the C tests with AddressSanitizer/UndefinedBehaviorSanitizer,
then compiles a freestanding ARMv7 Thumb object and requires zero unresolved
external symbols. It prints JSON evidence including input/tool hashes; temporary
executables and the non-deployable ARM object are removed from system temporary
storage. It uses no working-directory-sensitive imports or network operations.
No runtime ARM call or native allocator is exercised by a successful compile.

Canonical evidence: `projects/lossless-sup/build/reader-lease-tests-20260916.json`
records 53 passing test groups against the fixed candidate. The earlier
pure-select candidate is explicitly rejected before compilation. Input paths
and tool hashes identify the actual tested files.

## Contract and lifetime

`fp_reader_view` is a normalized host contract, **not** the native parser memory
layout. `fp_blob.capacity` and its accessible allocation are caller-owned facts;
C cannot discover whether an arbitrary pointer describes real allocated memory.
Target addresses are separately modeled 32-bit spans. Test private addresses
`D0000000` / `D0040000` are fictitious and do not reserve any camera RAM.

1. Start with a zero-initialized fresh lease. The future caller must prove first
   parse for this exact resource generation, MainB2 identity and memory-backed
   borrowed input. Unknown, already-stock and already-private cache states are
   rejected. There is no cache-clearing, replay, or detach API.
2. Begin requires NBU base `C18C0460`, offset `76FF04`, a source bound containing
   the original page through offset `795950`, and no range beyond pinned seg0.
   It validates the original MainB2 FNV fingerprint and byte-identical stock pool
   prefix. Original pool address is `C18C0474`, length 176152. Private page/pool
   require exact sizes and fingerprints; source/page/pool overlaps and integer
   overflow are rejected before any memory access through their derived offsets.
3. Full preflight checks every BE32 record length, including unaligned fields,
   before replacing the normalized source and pool views. It requires exactly
   1538 records, one initial `10002` / 3288-byte header, and a final exact
   `FFFFFFFF` / 8-byte terminator. GUI page ID is external selector evidence,
   not claimed to be serialized inside that allocation header.
4. `peek`/`body` produce a generation-and-ordinal-checked transient record token.
   A future native binding must normalize a proven consumption result, then set
   the cursor to the exact record end before `accept`. The C layer never calls
   an interpreter and does not assume its return-code convention or recursion.
5. Only a complete, unchanged view and expected terminal/count permit `finish`.
   Source and pool are restored, with source position advanced to the original
   page end rather than private page length. Record body tokens are immediately
   unusable through this API. C cannot revoke copied raw pointers: callers must
   not retain body spans beyond accept/finish/failure.
6. The complete page and pool allocations remain immutable and pinned while any
   objects or callbacks from the resource generation could retain them. A
   `PARSED_PINNED` lease can resolve strings only against its own private pool,
   never the reader's restored stock pool. This helper scans within bounds for
   a terminating NUL; it is not a native resolver hook. Native lazy resolution
   after reader restoration remains a hard integration gate.
7. An incomplete parse, failed consumption, stale token or mismatched restoration
   enters `POISONED` fail-stop. No saved reader is restored and stock parsing
   must not be retried on that partially constructed resource. The caller must
   stop native parsing and quarantine the resource. A poison result is not an
   error convention proven safe to return through an actual hook.
8. `owner_destroyed` only acknowledges external destruction of **all** objects,
   callbacks and reader of the original resource ID/generation. It performs no
   teardown itself, and never repairs a poisoned native parser. Only after that
   acknowledgment may the owner release the page/pool buffers. Never clear or
   zero a live lease to circumvent these lifetime constraints.

The core's FNV checks detect accidental corruption, not adversarial forgery.
Strong SHA pinning happens in the runner; a future native loader would need its
own verified package/source provenance. The core is single-threaded and requires
exclusive access to the reader/package; it implements no interrupt or mutex ABI.

## Newly proven outer loader boundary

The shared `research/ui/tools/native_page_probe/` now verifies the actual
Thumb lazy selector `C05E82F1(app,screen)` in 16 bounded tests. The first parse
call is `C05E834A -> C05E6401(reader)`; a cached screen root bypasses parsing.
Inner return 0 means continue; nonzero only stops the loop and can publish a
root even for an injected error value. A missing screen name can return outer
0 with no root. Return status alone therefore cannot implement this lease.

**Do not pass lease errors directly through the inner parser hook.** Explicit
outer quarantine/unwind and complete cursor/root validation remain required.
The screen declaration at C18EC77C is not an NBR lookup index. None of these
findings installs a native reader adapter or proves resource lifetime.

## Native evidence and unresolved binding

Pinned seg0: 49,245,696 bytes, SHA-256
`aaa5208a028d9c4aebb9cc8614add723d456e96b2a95914f433079954320e622`.
This is not interchangeable with the differently sized `MAIN_c0000000.bin`.

Static evidence in the pinned decompilation:

- `FUN_c05e5f20`: memory reader `+04` position, `+10/+14` string pool length/base,
  `+20/+24` source length/base, `+28` stream handle, `+18` ownership. Memory-mode
  byte/u32/copy/seek callbacks are `C05E5D79`, `C05E5DB9`, `C05E5E39`, `C05E5EA9`.
  These offsets motivate the normalized model; no packed struct cast is used.
- `FUN_c05e5b58`: `FFFFFFFF` or offset >= pool length returns null; otherwise
  resolves against `reader+14`. The private pool retains all original offsets,
  so parse-time private literal resolution does not itself require private NBR
  registration or synthetic high string offsets. Retained/lazy use is unproven.
- `FUN_c05e5fb0` / cleanup paths can release owned input; borrowed-buffer lifetime
  cannot be inferred from reader restoration. This model refuses owned input.
- `FUN_c05e6310` initializes a whole NBU and loops over `FUN_c05e6400`; it does
  not establish the actual MainB2 lazy-page callsite, cache selector, accepted
  record-return semantics, partial-parse unwind, or safe resource re-creation.

The existing OpenGate implementation patches three entry points. This standalone
model requires their original little-endian first words, refusing any changed
slot (including OG's existing hooks); it does not remove or compose those hooks:

| Entry | Original word | Existing OG use |
| --- | --- | --- |
| `C05E5B58` | `3FFFF1B1` | synthetic string offsets |
| `C05E84D8` | `B086B500` | private NBR registration |
| `C05E6400` | `4FF0E92D` | per-record replacement |

These are supplied evidence fields, not a live memory probe. Future fp-Merge
integration requires an explicit shared dispatcher and resource ownership design.
The UI candidate's private variable, navigation,
font/layout, native allocation and event/callback lifetime gates remain open.
No native binding may claim readiness solely because this lease model passes.
