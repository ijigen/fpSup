---
name: fp-camera
description: Talking to the SIGMA fp over the USB shell — starting the daemon, deploying code, asking the camera questions, running a recording test, and getting out of a freeze. Use whenever the work touches the live camera rather than the decompilation.
---

# Working with the live fp

Everything here was paid for. Where a rule has a reason, the reason is a thing
that went wrong on this camera.

## Before anything

The shell talks over a Unix socket, so the daemon has to be up:

```sh
cd fpSup-v1/fp_usb_shell
(./fpshd >/tmp/fpshd.log 2>&1 &)          # socket /tmp/fpshd.sock
```

`putfile` resolves its imports from that directory — run python from
`fp_usb_shell/`, or `sys.path.insert(0, '.../fp_usb_shell')`. A bare
`ModuleNotFoundError: putfile` means the cwd moved; the tool resets it between
calls more often than you expect.

**Check for a daemon before starting one.** They do not replace each other --
they compete for interface 0, and the loser gets `LIBUSB_ERROR_ACCESS`. Kill by
PID; `pkill -f './fpshd'` has silently matched nothing and left two running
while a third was started on top:

```sh
pgrep -fl fpshd                      # expect nothing, or exactly one
for p in $(pgrep -f fpshd); do kill -9 $p; done
```

Reading the state of play:

| what you see | what it means |
|---|---|
| `ERR shl open ... failed` | the camera is not on USB (off, cable out, or wedged) |
| `ERR shl frame0 ... TIMEOUT` | enumerated but nothing answers — usually no shell in that build |
| `LIBUSB_ERROR_ACCESS` | someone else holds interface 0. Check `pgrep -fl fpshd` **first** -- a second daemon is the usual cause. If there is only one, it is the host's PTP stack (`ptpcamerad`, `mscamerad-xpc`), which claims the interface whenever it still declares class `06/01/01`. `./lsdesc` says which: `ff/ff/ff` means the interface patch is in and the daemon is the culprit |
| `./lsdesc` shows no device | gone entirely, not just deaf |

## What is known, and how

Each claim says how it is known. **Measured** means it was reproduced or read
off the camera. **Standing** means the user asked for it. **Seen once** means
exactly that — one incident, cause not established. Treat "seen once" as
something to be careful around, not as a law, and correct it when it is
understood.

### Standing (the user's, not mine)

- Every `mem read` needs explicit consent, each time, naming the addresses.
- Never `dir` a clip folder. `dir \CINEMA` (the folder list) is fine.
- Never `delCinemaDng`, `deloneimg`, `delall`.
- Do not commit or push unless asked.

### Measured

- **A command sent while the camera is recording wedges the vendor endpoint.**
  The camera keeps working; USB needs a reboot. Reproduced.
- **`P.mem_set` silently drops writes.** Read back and retry:
  ```python
  for _ in range(8):
      P.mem_set(addr, val)
      if P.mem_get(addr)[0] == val: break
  ```
  Reads are reliable.
- **`P.mem_get` fails silently above some size.** 9216 words returned nothing;
  4096 works. The actual ceiling has never been measured — 4096 is a size known
  to work, not a boundary.
- **Freshly written code is data to the caches** until `0xC000E91C` runs.
- **A soft power cycle does not clear RAM**; a battery pull does.

### Seen once

- **`movrec movc`, sent with nothing recording, and the camera left USB
  entirely.** No clip appeared, so it did not start a take. Blocking in the
  shell thread is a guess — the mechanism was never established. Until it is,
  be wary of command families that change state (`movrec`, `rec`, `still`,
  `play`) and prefer reading them in the decompilation first. Read-only
  families have never done this: `setting`, `imager mode_list`, `help`,
  `menu dump`.

## Deploying over USB (RAM — dies on power off)

For *writing* camera-side code rather than deploying what already exists — which
call site to borrow, the ARM traps that freeze the camera, the host tools, the
cave layout — see the **fp-usb-shell** skill. fpGyroSup is released and in
maintenance; new work starts there.

```sh
cd fpSup-v1/gyro
python3 ring_task_deploy.py --gcsv --place     # the writer, into the pool
python3 imu_stream_deploy.py --restore         # unhook first, or arming refuses
python3 imu_stream_deploy.py                   # place the producers and arm
python3 imu_stream_deploy.py --stage 5         # turn the flow all the way on
```

`--stage` refuses if the sites still hold the firmware word — that guard exists
because a stage without arming looks exactly like a working deploy until the
take produces nothing.

A USB deploy survives unplugging the cable but **not** a power cycle. That is
what makes it the right tool when the SSD needs the only USB socket: deploy,
unplug, attach the SSD, record, detach, reattach, read.

## Cards

```sh
python3 build_base_card.py --edition gcsv --debug --version 'vX debug' --out DIR
python3 release_card.py gcsv vX.Y            # a release, section-checked
cp DIR/AutoRun.txt DIR/VSHL.BIN /Volumes/fpSup/ && sync
diskutil eject /Volumes/fpSup                # Spotlight often dissents; sync is
                                             # what matters, Finder can eject
```

`--debug` is the same code plus the USB shell. It works because the loader hands
`0xC00D0794` to the worker once everything is placed — before that fix a card
could carry a logger or a shell but never both.

**A release card has no shell. You cannot ask it anything.** If a fault only
appears on a release card, put the debug card on instead; it is the same code.

## Asking the camera

The native shell knows more than we usually remember. `help` lists 70 command
families. The ones that keep earning their keep:

- `imager mode_now` / `imager mode_list` — the sensor's own mode table, names
  and all. Better than anything derived from the firmware image.
- `setting` — 178 named parameters; `setting get/set <name>`. Note `setting
  get` reads a **mirror** that is empty until `setting readcam`.
- `menu dump` — the UI's setting store as hex; diff it across a menu change to
  find the byte that moved.
- `dir`, and `getfile.py <remote> <local> --size N` for anything on a card.

Before writing plumbing, check whether the shell already has the command.

## When it goes wrong

- **Freeze: read the card first** — whatever the hooks wrote is already on it —
  then pull the battery. (Measured: the data survives.)
- **Everything injected over USB is RAM.** A cold boot clears it; the card puts
  back only what the card carries.
- **Ask when, not just what.** An "intermittent" SSD fault turned out to be
  strictly "SSD attached before power-on". The question that settled it came
  from the user, after a day of asking a different one that looked close
  enough. When a fault will not reproduce, list the variables out loud before
  guessing at causes.

## What this was written against

The camera side is firmware Ver.5.02. The host side is `fpshd` **3.0.0**, and
that is accurate — the daemon is unchanged since the tag `fp-usb-shell-v3.0.0`.
The camera side and build tooling have moved a long way since without a version
of their own, so `FPSHD_VERSION` tells you about the daemon and nothing else.
The newest shell is local only.

If the shell changes, this can go stale without anything failing loudly. Check
`FPSHD_VERSION` against this line when something here does not match what the
camera does.

## Keeping this file honest

This is a record, not a rulebook. When something here is contradicted by the
camera, change it — and say in the edit what the new evidence was. Several
entries started as one observation written up as a law; that is the failure
mode to watch for. If a claim cannot be traced to a measurement, a reproduction
or the user, it belongs under **Seen once** or not here at all.
