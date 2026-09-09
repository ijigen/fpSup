---
name: fp-usb-shell
description: Building and running code on the SIGMA fp with the USB shell — borrowing a call site, the ARM traps that freeze the camera, the host tools, and the AutoRun/VSHL card pipeline. Use when writing or deploying camera-side code. For camera etiquette and reading state, see fp-camera.
---

# The USB shell as a tool

fpGyroSup is released and in maintenance. Most new work now starts here: the
shell is how anything gets onto the camera and how you find out what it did.

`fp-camera` covers the live camera — daemon, consent, freezes, what to ask.
This file covers building the thing you are about to run.

## The one rule everything follows from

**The shell can write memory. Nothing in it can call.** Code runs by pointing
an address the firmware already calls at your routine and letting it fire.

Every template in `templates/` starts there. They differ only in *which* site
they borrow, and that choice decides what your code is allowed to do:

| borrow | template | your code may |
|---|---|---|
| a shell command handler | `shellcmd.S` | block, take mutexes, do file I/O — it runs in the dispatcher's task |
| the gyro callback | `oneshot.S` | not block, not take a mutex, not call anything that might — 50-90 Hz, interrupt-ish |

**Default to the command handler.** The table is 77 entries of
`{char name[0x14]; void *handler}` at `0xC0BAC14C`, stride `0x18`; entry *n*'s
pointer is at `0xC0BAC14C + n*0x18 + 0x14`. `echo` is entry 17 → `0xC0BAC2F8`.
`[r0]` there is a printf, so the routine can answer the host directly.

Take the callback only when you need a moment no command can reach — during
recording, between frames.

**A resident thread is a third option, and a real one.** An earlier version of
this file said "do not create a task" -- that took one true fact (`tk_ext_tsk`,
a task ending *itself*, is not in the syscall table) and inflated it into a
rule. The shipped gyro writer is our own thread and has been for weeks.

Use the firmware's own thread pool rather than raw `tk_cre_tsk`:

| | |
|---|---|
| `XT_CREATE` `0xC036E108` | `f(&holder, pri, stksz, name8)` |
| `XT_ATTACH` `0xC036E1B8` | `f(&holder, bodyobj)` -- attach and wake |
| `XT_JOIN` `0xC036E1F8` | `f(&holder)` -- `tk_wai_flg`, `TMO_FEVR` |
| `XT_DESTROY` `0xC036E168` | `f(&holder, 2)` -- join, wup, ter, del |

The body you hand it is one word holding a vtable pointer; the pool's worker
calls slot `+0xC`. Pass the **address** of that word, not its contents -- every
build that passed the contents called a garbage pointer the instant it was
woken. The writer runs at priority **6**, which is `AudF_W`'s and `SRecFile`'s;
the old priority-28 thread waking every 5 ms is what dropped samples.

So the three shapes are: **borrow a command** for one-shot work that has to
finish and return, **borrow the callback** for a moment no command can reach,
and **a pool thread** for anything resident. `tk_ext_tsk`'s absence only bites
the first shape, and borrowing a command is exactly how that shape avoids it.
`park.S` is for replacing a resident thread's code underneath it.

## The five ways to freeze the camera

All five were paid for. Each one looks like a bug in your payload.

1. **Push an odd number of registers.** AAPCS wants 8-byte alignment at a call;
   nothing complains until the callee reaches `LDRD`/`STRD`, then it is a data
   abort with the shell task holding the dispatcher — battery out. `callfn.S`
   pushed nine and died calling the firmware's own clock.
2. **Not saving `lr` in anything that calls out.** `blx` overwrites it. The gyro
   logger's `writer_open` called out five times without saving it.
3. **Arming with `B` instead of `BL`.** The borrowed sites hold a `BLX`; your
   routine must return through `lr`. Word:
   `0xEB000000 | ((target - site - 8) >> 2 & 0xFFFFFF)`.
4. **Trusting `mem set`.** It drops writes silently — measured 18 of 200 lost,
   then 0, then 48. Not pacing; no delay makes it safe. Two lost words turned
   `movt ip, #0xC044` into the `blx ip` after it. **Write, read back, rewrite
   the holes, repeat.** Reads are sound.
5. **Sharing `0xC072F700`.** Templates all use it. `bulkload.S` kept its
   destination pointer at `+0x14`, which is `getfile.S`'s buffer; loading
   getfile walked that pointer and the read landed elsewhere.

Move bytes in the command line, not one `mem set` per word: `bulkload.S` does
~240 at a time against 4, which took a 14 KB AutoRun from 448 s to under one.
Verification matters *more* there — a lost chunk is a 240-byte hole.

Freshly written code is data to the caches until `0xC000E91C` runs.

## Two bases, and they are not the same

This one cost two weeks of a red test suite reading like a real overrun:

| constant | value | whose |
|---|---|---|
| `CAVE_BASE` (`load.py:93`) | `0xC072DE64` | images injected over USB (`load.sh`) |
| `ENTRY_AT` (`build_base_card.py:58`) | `0xC072E064` | the card's VSHL image — the loader owns the 512 below |
| `PARK_AT` | `0xC072EFB4` | the park stub; nothing of ours may reach it |
| — | `0xC072F000` | the shell's own state starts here |

Template scratch is separate: `0xC072F700` parameters/results (256 B),
`0xC072F800` the routine, up to `0xC0730000`.

`build_base_card.py` refuses to write a card whose sections reach `PARK_AT`.
Trust that guard over any arithmetic written down somewhere else.

## Host tools

```sh
cd fpSup-v1/fp_usb_shell
(./fpshd >/tmp/fpshd.log 2>&1 &)              # daemon; socket /tmp/fpshd.sock
```

| | |
|---|---|
| `inject.py <src.S>` | assemble and run once |
| `callfn.py <fn> --r0 .. --r5` | call one firmware function, see what it returned |
| `load.py <src.S> --entry S --hook ADDR` | place a resident image and arm it |
| `putfile.py <local> <remote>` | write a file to the card (mode 7 truncates; `0x402` fails if it exists) |
| `getfile.py <remote> [local] --size N` | read one back |
| `memprobe.py <base> <size> [--check]` | mark a region, then see what survived |
| `swapworker.py` | replace the resident worker without a battery pull, ~1 s |
| `build_autorun.py` | build `AutoRun.txt` (+ `VSHL.BIN` with `--loader`) |

Run python from `fp_usb_shell/` — imports resolve from there.

⚠️ `swapworker.py` and the deploy scripts **talk to the camera when run with no
arguments**. Do not run one to read its usage.

## Hot-updating what is already running

Editing camera-side code used to cost a reboot per edit — the task asking for
the change is running inside the code being replaced. Eight reboots in one
evening for eight one-line edits is what produced both mechanisms below. Use
them; a battery pull per iteration is not the cost of this work any more.

**They are two different mechanisms.** Which one you need depends on whether
the thing you are replacing can reach the loader by itself.

### The shell worker: hand the task over (`swapworker.py`)

The worker checks two words every round, so the swap is just the boot path
asked for a second time:

```
putfile VSHL.BIN                     the new code, onto the card
mem_set 0xC072F048 <loader `load`>   SWAP_ADDR — address first
mem_set 0xC072F044 0x50415753        SWAP_MAGIC "SWAP" — magic second
```

The worker clears the magic, `bx`es into the loader's `load`, and the loader
re-reads the file and branches to the new worker's entry. About a second, no
reboot. Address before magic, because the worker checks the magic and only then
reads the address — a half-written pair can never send it somewhere arbitrary.

The endpoints are unattended while the file is read, so **the first command
after a swap is expected to be slow**; `swapworker.py` retries for ten seconds.

Note what this does *not* touch: the gyro-callback bootstrap at the top of
`loader.S` is the power-on path only. A swap enters at `load`, from the
worker's own task — which is also the evidence that `load` is perfectly happy
in ordinary task context.

### A resident thread that cannot: park it (`park.S`, via `load.py`)

The gyro logger's writer thread runs from the cave and has no way to reach the
loader, so it steps aside instead:

```
state+0x00  PARK     host sets it; cleared when the new body is ready
state+0x04  PARKED   the thread sets it — now it is safe to write
state+0x08  RESUME   where to carry on
```

Your loop tests PARK at the top and `bx`es to the stub. `load.py` does the rest
(`--park-state`, `--park-stub`, `--park-resume`); `gyro/load.sh` is the worked
example. The stub is placed **unconditionally**, even with nothing resident —
the payload's PARK_STUB is a compiled-in address, and on a cold boot that
address held zeros, which ARM executes as no-ops all the way out of the cave.

**This swaps implementations, not protocols.** It replaces the body of a loop
that keeps talking to the same state block in the same way. Change where the
state lives, or what registers the resume point expects, and the parked thread
has no way to know — reboot for those. On resume only `r10` is promised (the
three words); point RESUME at a label that sets up its own registers.

> **Open:** `park.S`'s header says a resident task cannot be stopped. That was
> true when it was written. `tk_ter_tsk` (`0xC01F8E44`) and `tk_del_tsk`
> (`0xC01F897C`) were read out of `XC_Thread.cpp` on 2026-09-07 and the firmware
> uses them itself (ThreadPool teardown: wup → ter → del). Only `tk_ext_tsk` —
> a task ending *itself* — is genuinely absent. So parking may no longer be the
> only option for a cave thread; the hand-over above is the other, and it is
> already proven daily. Neither has been tried on the logger.

## Endpoints — check this before believing any note

```
EP 0x01 OUT  bulk 1024 burst 3   commands
EP 0x82 IN   bulk 1024 burst 3   replies
EP 0x83 IN   bulk 1024 burst 3   streaming, for a hook to arm directly
```

All three are firmware-owned. Seven words change (`patches.py`): six reshape
PTP's unused interrupt endpoint into the second bulk IN, one stops the host's
PTP stack claiming interface 0 before the daemon can. The firmware then builds
and re-creates the endpoints itself, which is why **recording while connected
works now** — v1 bolted on endpoints the firmware did not know about, and
recording tore the channel down.

A card that only answers questions does not need them: `--no-ep-patches` keeps
the shell and leaves the descriptors alone. They exist for hook-push on EP 0x83,
which a card never does.

**21 notes in `notes/` still describe `EP 0x05 OUT / EP 0x84 IN`.** That
configuration is gone; EP84 is not enabled under the current descriptors and
`StartTransfer` on it was refused 100/100. Read
`notes/USB_SHELL_INDEX.md` before any other shell note — it says which are
current and which were overturned.

## Cards

The AutoRun spells out a small loader; the loader reads `\VSHL.BIN` off the
card and becomes it. That is why command count stopped growing with payload
size. `--debug` builds the same code plus the shell, which works because the
loader hands `0xC00D0794` back to the worker once everything is placed.

The loader tries `F_VOL`'s volume, then falls back to the card — an SSD
attached before power-on *is* what `F_VOL` names, and without the fallback
nothing loads and the whole session silently has no logger.

**A release card has no shell; you cannot ask it anything.** If a fault only
shows on a release card, put the debug card on — it is the same code.

## Adding a template

Two things earn a file a place in `templates/`, and neither is "it worked once":

- **Every return value is checked.** The media API reports failure by returning
  zero; a write that never happened looks exactly like one that worked.
- **What is verified is written down, and what is not is written down too.** A
  constant taken from watching working code is a guess about what the firmware
  does, not a fact about it. Say which is which in the header.

## What this was written against

Firmware Ver.5.02. `FPSHD_VERSION` is **3.0.0** and that is accurate: the daemon
has not changed one byte since it was set (`git diff fp-usb-shell-v3.0.0 HEAD --
host/fpshd.c` is empty). There is no 3.x.

What the number does not cover is the rest of the shell — the camera side and
the build tooling are ~540 lines and 8 files further on (`build_autorun.py`,
`loader.S`, and the `stage2.S` / `lensblock.S` / `sleeper.S` templates, all
added since), with no version of their own. `README.md`'s "v3" means the whole
package; `FPSHD_VERSION` means only the daemon. Do not read one as the other.

The newest shell is local only.

## Keeping this file honest

A record, not a rulebook. When the camera contradicts something here, change it
and say in the edit what the new evidence was. The failure mode to watch for is
one observation written up as a law — this project has produced several,
including a freeze root cause that was declared anchored and overturned two days
later. If a claim cannot be traced to a measurement, a reproduction, or the
user, it does not belong here.
