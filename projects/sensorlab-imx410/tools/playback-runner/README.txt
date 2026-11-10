SLTP v1: fixed autonomous playback trial, fp Ver.5.02

This directory builds SLTP.BIN for the existing loader v4. It neither installs
nor contacts a camera. It changes no loader, ISPL ABI, firmware hook or card
setting. Resident code/state live in the sup's own block; the RTOS allocates
the task's private 0x2000-byte stack, priority 25, attrs 0x41. Entry returns.
Task creation/start failure keeps the published block resident and reports
INIT_FAILED. The task remains dormant between explicitly armed sequences.

There are exactly two scenes:
  1: thumbnail view: PLAYON, 0.8 s, PLAYOFF, 2 s + 3 s, S1ON, 0.8 s, S1OFF.
  2: movie playback: PLAYON, 0.8 s, PLAYOFF, 2 s, OKON, 0.8 s, OKOFF,
     3 s, S1ON, 0.8 s, S1OFF.
Both wait 2 s after accepting the request before PLAYON, leaving time for the
host to become silent; both wait 10 s after S1OFF returns before reporting DONE.
Delay starts after the preceding native executor returns, not before it.
Typical complete duration after acceptance: 18.6 s / 19.4 s plus native calls
and 20 ms polling quantization. No MOV, S2, general script or arbitrary pointer
input is supported. All six key strings are compiled into the worker.

Arming contract (for the separately authorized camera operator)
-------------------------------------------------------------
Start only from externally confirmed CINE live-view idle, not an open menu,
recording, playback, a pending operation, or an uncertain prior command. The
internal gate checks CINE and the same movie-busy flags as QS/HSEP at acceptance
and immediately before PLAY. These flags do NOT establish GUI live-view idle
or prove playback has exited. Do not mistake them for a playback-state getter.

Read state and identify the exact running build while idle. The state address
is the loaded cached block base + build.json state_off; svc->find('SLTP') also
publishes this address. Only two input words exist:
  state + 8: req_mode (1 or 2)
  state +12: req_seq (start at 1, strictly increase; commit this word last)
Write mode first and sequence last. Do not retry an uncertain arm. After the
commit, leave USB entirely silent during playback and for the exit settling
period. Existing daemon attachment need not be changed. Confirm live view
has returned before reading state; waiting for a host timeout does not prove
exit. Nothing in this runner performs a USB transaction or framebuffer read.

A newer request received during a sequence is rejected and consumed, never
queued. The active scene is latched. Duplicate/older sequence values do not
replay. Invalid scene, non-CINE or recording requests are rejected once.
The native shell executor can block; the runner cannot preempt/cancel it or
guarantee physical exit if it hangs. Each attempted key is issued once. Native
return values are recorded, and the matching releases are still attempted;
DONE means the fixed sequence returned, not successful playback/physical exit.

State ABI (all little-endian u32, total 176 bytes)
------------------------------------------------
  0 magic STP1; 4 version 1; 8 mode request; 12 seq request
 16 seen_seq; 20 active_seq; 24 done_seq; 28 phase
 32 active mode; 36 error; 40 rejected seq; 44 rejection reason
 48 task id; 52 task create/start result; 56 accepted timestamp
 60 phase timestamp; 64 completed timestamp; 68 event count
 72 CINE at last gate; 76 busy at last gate
 80..175: six 16-byte event records {key, entered_us, returned_us, native_rc}
Key ids: 1 PLAYON, 2 PLAYOFF, 3 OKON, 4 OKOFF, 5 S1ON, 6 S1OFF.
Phases: 0 idle, 1 arm wait, 2 PLAY held, 3 PLAY settle, 4 OK held,
5 observe, 6 S1 held, 7 exit wait, 8 done, 9 rejected, 10 init failed.
Errors: 0 none, 1 bad mode, 2 non-CINE, 3 recording busy, 4 active,
5 task create failed, 6 task start failed. Timestamps wrap at 2^32 microseconds.
Use done_seq == the requested sequence and phase == 8 for sequence completion.
decode_sltp.py reads a previously saved binary state without camera access.

Build, offline checks and provenance
-----------------------------------
  python3 -B build_sltp.py --out out-v1
  python3 -B -m unittest -v test_sltp
  python3 -B test_sltp.py --mutate
  python3 -B decode_sltp.py saved-state.bin

Artifact: out-v1/fpSup/SLTP.BIN; exact hash/offsets: out-v1/build.json.
mutable_file_offsets lists the one context-pointer literal changed at entry;
mask exactly those 4 bytes when comparing running code to the file. This is
provenance information for the operator, not a runtime loader pairing check.
validation/ contains the baseline transcript, eight assertion-caught mutants,
source identity, and modeled event timing. Tests execute the actual compiled
Thumb code through the actual loader-v4 ARM path. RTOS task creation, clock,
settings getter and shell executor/key effects are explicit stubs; neither
the native key handler nor physical camera playback is claimed as tested.
The memory-write test covers private code/state and stack after loader boot.

Primary task/stack/VFP evidence: projects/isp-lab/hsep/task-context.txt.
Shell executor/context and key-string construction: projects/isp-lab/sup/
ix_card.c and ix_wr.c. Attrs 0x41 are HLNG|DSNAME, not a VFP-enable switch.
SLTP is compiled soft-float with no FPU instructions. No AutoRun update is
needed for adding this compatible standalone sup to an existing v4 card.

Minimal live host helper (prepared offline; not automatically executed)
---------------------------------------------------------------------
live_sltp.py supports only arm and status. It pins the exact v1 SHA above,
fetches the current 8192-byte LOAD.LOG through the existing getfile helper,
requires exactly one loaded SLTP.BIN, validates the resident bytes and exact
context pointer, then validates state magic/version/task/phase/sequence.
It holds the shared /tmp/fp-af-fusion.lock throughout. Native app_current=2
and is_recording=0 are additional checks; they do not replace visual CINE
live-view confirmation. Importing this helper does not import the transport.

From this directory, for the authorized operator only:
  python3 -B live_sltp.py arm --scene thumbnail --confirm-cine-idle --out /tmp/sltp-scene1-new
  python3 -B live_sltp.py arm --scene play --confirm-cine-idle --out /tmp/sltp-scene2-new
After visually confirming return to idle live view and completed settling:
  python3 -B live_sltp.py status --confirm-returned-liveview --out /tmp/sltp-status-new
Every evidence directory must be new; the helper refuses to overwrite a prior
request. --build defaults to this directory's out-v1/build.json. There is no
block-address override, arbitrary pointer, command, MOV, S2, polling or cancel.

The resident MEM1 window is read-only, sync-enabled, and revoked before arm.
MEMW's minimum 1 KiB grant would extend beyond the 256-byte state reserve, so
it is deliberately not used. Existing native cached-address mem set writes
req_mode once, then a native cached read verifies mode and inactive sequence.
After a final idle check, req_seq is written once with retries=0 and 1 s ack
timeout. That commit is the last USB command on every outcome. The helper
persists local intent before committing, and after success/error/exception it
only saves local evidence and waits 30 s while holding the lock. No window
cleanup or readback follows commit. An error/timeout never authorizes replay.

The local 30 s wait and lock release are NOT proof that playback exited;
native calls can block. All other tools must remain quiet until the operator
visually confirms idle live view and exit settling. The independent status
command requires the explicit confirmation flag before any camera access.
Its sequence_completed field proves only the worker finished its sequence.

Offline fake-transport checks:
  python3 -B -m unittest -v test_live_sltp
These cover strict build/context identity, current log identity, idle/pending
state gates, mode-before-sequence, zero USB after commit (including lost ack),
status confirmation and shared flock. They do not exercise the native shell
or physical playback. validation/live-host.json records the tested sources.
