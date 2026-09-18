# fpLossless private-variable coordinator

Offline C implementation, **not a native ABI adapter or installed hook**.
`binding.c` joins the existing control and UI policies through explicit port
operations. No camera, USB, firmware patch, AutoRun or merged product is emitted.

Run `python3 -B test_binding.py`: 29 exact-C host scenarios plus ARMv7
soft-float compilation, 30 tests total. Mock ports deliberately model writes
that succeed before a later error. Native instruction evidence is separate:
`research/ui/tools/native_variable_probe/README_BINDING.md`.

## Ownership and publication

- Fresh zeroed binding, already-booted core and non-reused session required.
  Never reset live storage to bypass failure or warm-reset cleanup.
- Register absent `MV_fpLossless` once, default 0; relookup and type-check.
  An existing matching name is not ownership. Unknown/replaced descriptors,
  duplicate subscribers and partial registration are quarantined.
- The ticket is immutable and generation/session/owner/descriptor checked.
  Subscription copies a native pair, but callback code/context remain borrowed.
- Native assignment is not vetoed by callback return. Every choice, including
  rejection, explicitly republishes canonical value and view. Synchronous
  self-echo does not process another choice; other reentrancy is blocked.
- A non-atomic publication failure may leave ON visible while core rolled back.
  `uncertain` therefore blocks **all** recording, not just compression.

## Native port contracts still unimplemented

All calls require one proven serialized owner for GUI/recorder state.
`notification_enter` must exclude all native notifications before unsubscribe
can free its copied pair; BUSY acquires nothing. `notification_leave` releases
that exclusion even after a mutation error. The native unsubscribe has no
expected-owner parameter; the port must verify ownership under exclusion.

`quiesce` must prove no active/queued callback, source row event or pending
native value write remains, with sources kept retired until reattachment.
After draining, the coordinator rereads the integer before retiring the ticket.
Mismatch keeps the REC interlock; read failure retains ticket/draining state.
Successful drain alone is not UI repair.

Recovery reattachment republishes canonical state, then redraws from fresh port
facts before clearing uncertainty. Public context stays blocked throughout;
a port-provided recording block is never removed. Normal, consistent page
closure retains an already-proven UI readiness bit so ON -> exit menu -> REC
can work. The module never creates a readiness proof itself.

Use **`fpl_binding_begin`** for every recorder start in an eventual port.
It checks fresh producer facts, serialization and uncertainty before the core.
Do not bypass it with raw `fpl_begin` plus a separately constructed context.
`FPL_BLOCK_REC` is bit31 of context.ready: an unconditional denial, not one of
the seven readiness proofs. The structure layout remains unchanged.

No code here frees descriptors, names, modules or page resources. Retain all
borrowed state through exclusion, cancellation, proven quiescence and failures.
Stock attach/detach calls and arguments must be preserved separately by a future
hook. Native registration/rendering/locking/queue-drain/recorder operations,
persistent storage and actual camera behavior remain integration gates.
