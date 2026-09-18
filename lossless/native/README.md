# fpLossless v5.02 native variable call layer

Actual ARM32 C wrappers around the verified native Thumb entrypoints. This is
**not an installed hook, complete binding port, renderer or recording product**.
No camera or USB operation is provided. Test compilation emits only a temporary
object; no VSHL, AutoRun, installer, code-cave reservation or merged card.

## Reproduce

With clang and an existing Unicorn 2.1.4 environment:

```sh
python3 -B /absolute/path/fpSup/lossless/native/test_native_variable.py \
  --seg0 /absolute/path/out/seg0_c0000000.bin \
  --shared-probe /absolute/path/research/ui/tools/native_variable_probe/binding_probe.py \
  --elf-helper /absolute/path/research/ui/tools/arm_text/elf_text.py
```

The test compiles this exact C as freestanding ARMv7 Thumb soft-float, rejects
unresolved symbols or text relocations, maps its code RX and executes it into
the pinned original firmware instructions. The 23 cases pass with zero skips;
r4-r11 and SP are checked after calls, with 20000-instruction / 250 ms bounds.
Original firmware is RX; writes stay in synthetic RAM. The resulting code is
2690 bytes, SHA-256
`9439187375921cd6ba44f0b765308c237701ea36df50cab72c06cdde9c820b38`.

Original Lua registration, heap, locks, strcmp and callback services remain
substituted, and native widget vectors are empty. Thus register/set/subscribe
call shapes execute, but complete UI rendering and real scheduling do not.
Evidence: `projects/lossless-sup/build/native-variable-port-20260916.json`.

## Implemented

- `fp_nv_init`: accepts only fresh storage and exact private name
  `MV_fpLossless`; rejects five changed native function prologues.
- `fp_nv_inspect`: treats successful lookup plus NULL as absent, not found.
- `fp_nv_register_off`: default OFF, one-time ownership claim, no adoption of
  another descriptor and no blind retry after partial native failure.
- `fp_nv_read`: checks descriptor/name/type and subscription identity.
- `fp_nv_subscribe`: verifies the copied pair and retains callback context on
  uncertain failure; duplicate/foreign owners are not overwritten.
- `fp_nv_set_canonical`: accepts 0/1 only, checks ownership before/after calling
  the original named-array setter, then checks readback. The quiet variant
  suppresses app callbacks, **not** native component dispatch.
- `fp_nv_unsubscribe_locked`: verifies exact pair/callback/context before
  calling native removal. It can clean up a failed subscription with no pair
  but never frees descriptor, name or callback context.

Results use `FP_NV_*`, not `FPL_*`; `last_native` retains an encountered native
error. A future binding port must explicitly translate these results.
A failed native mutation may already have published state. Faults are sticky;
do not clear state to retry. Cleanup does not clear the fault.

## Mandatory external contracts / remaining work

Every call requires a live initialized v5.02 app, valid separate caller-owned
buffers and serialized registry/GUI ownership. Name storage is borrowed for the
whole registry lifetime. Prologue guards are conflict checks, not a replacement
for full firmware identity verification.

Before `unsubscribe_locked`, the caller must already exclude ALL native
notifications and subscriber changes. The native internal mutation lock does
not provide that guarantee. Afterward it must drain queued source events and
callback users before releasing code/context. This module supplies neither
lock acquisition nor quiescence; its tests use serial emulation only.

The functions are not yet wired into `fpl_binding_ops`. Callback-to-policy glue,
multi-variable UI permissions, actual rendered view publication and ownership/
queue integration remain pending. Value readback alone must never set
`FPL_READY_UI`. The safe recorder entry remains `fpl_binding_begin`, with all
codec/writer/header/playback/storage proofs still required.
