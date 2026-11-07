# fp-autotest

A standalone hardware-in-the-loop test harness for SIGMA fp SUP cards.

`fp-autotest` drives the fpSup USB shell, runs a suite of read-only
expectations, and prints one PASS/FAIL line per step. It is the scripted,
repeatable replacement for typing the same `version`, `status get` and
`mem get` probes after every card build.

It is deliberately independent of any companion application. The only
camera-facing dependency is the upstream [`fp_usb_shell`](../../fp_usb_shell)
directory in this repository, and only the daemon backend uses it. Suites are
plain YAML or JSON, reports are plain files, and exit codes are suitable for CI
or a shell script.

## Why it exists

A card build is only proven when the camera still answers and the patch words
are where they should be. Doing that by hand is slow and easy to skip. A suite
turns the checks into a checklist that runs in order, stops at the first
surprise, and leaves a report behind. The physical parts -- shutter, mode dial,
card mount -- stay with the operator through explicit `prompt` steps.

The first suite is LExpo (long-exposure patch, fp 5.02). The harness is
transport-agnostic, so other cards and other probes can add a suite without
touching the runtime.

## Requirements

- Python 3.9 or newer.
- JSON suites always work. YAML suites need PyYAML
  (`python -m pip install pyyaml`); without it the loader says so and suggests
  JSON.
- `--backend daemon` needs a running `fpshd` daemon and Unix sockets
  (macOS/Linux).
- `--backend direct` needs pyusb and a libusb-1.0 the platform loader can find
  (Windows, or any host without the daemon). pyusb is imported only when this
  backend is used.

## The two backends

| Backend | Path | Default on | Notes |
|---|---|---|---|
| `daemon` | `fp_usb_shell/putfile.py` → `fpshd` AF_UNIX socket | macOS, Linux | Reuses the upstream client; no socket protocol is reimplemented here. |
| `direct` | pyusb, FPSH v1, interface 0, bulk `0x01`/`0x82` | Windows, other hosts | 64-byte frames, CRC32 over the first frame, replies matched by sequence. |

Both expose the same small surface (`sh`, `mem_get`, `version`, `status`), so a
suite does not know which one is in use. Select explicitly with
`--backend daemon` or `--backend direct`; without the flag the platform default
above is used. A daemon failure is reported, not silently retried over USB.

For the daemon path, start `fpshd` the same way the other `fp_usb_shell` tools
do. The socket defaults to `/tmp/fpshd.sock` and can be moved with
`FPSHD_SOCKET`. `DaemonSession` honours that environment variable and also
accepts an explicit socket path in Python.

## Quick start

Run from this directory (`fpSup/tools/fp-autotest`):

```sh
python -m fpautotest list
python -m fpautotest doctor
python -m fpautotest run lexpo-fp502
python -m fpautotest run lexpo.yaml --report out/lexpo
python -m fpautotest run lexpo.yaml --backend direct --non-interactive
```

`<suite>` is a path to a `.yaml`/`.yml`/`.json` file, a built-in filename such
as `lexpo.yaml`, or the built-in `name:` value such as `lexpo-fp502`.

## CLI

```
python -m fpautotest run <suite> [--backend daemon|direct]
                                [--report DIR] [--non-interactive]
                                [--timeout-ms N]
python -m fpautotest doctor [--backend daemon|direct] [--timeout-ms N]
python -m fpautotest list
```

| Command | Purpose |
|---|---|
| `run` | Execute a suite. Prints the backend, `[PASS]`/`[FAIL]` per step, then `name: PASS (n/m steps)`. `--report DIR` writes `<suite>-result.json` and `<suite>-report.md`. `--non-interactive` makes prompt steps fail instead of waiting for the operator. |
| `doctor` | Read-only connectivity check. Opens a session, prints the backend, the `version` reply and general status, and says whether the shell responds. It assumes no card is mounted. |
| `list` | List the built-in suites in `suites/`. JSON suites list without PyYAML; a YAML suite without PyYAML is reported as unreadable with the reason. |

Exit codes:

| Code | Meaning |
|---|---|
| `0` | Suite passed (or the command was informational) |
| `1` | A suite step failed |
| `2` | Usage error, unknown/malformed suite, or transport/session failure |

## Suite schema

```yaml
name: lexpo-fp502
description: LExpo 40-500 s shutter patch, hook self-disarm, fp 5.02 only
steps:
  - kind: shell
    command: version
    expect_contains: "5.02.0"
  - kind: mem_expect
    addr: "0xC007F324"
    value: "0xE309C6FC"
  - kind: mem_expect_any
    addr: "0xC02BAD0C"
    values: ["0xE24DD064", "0xEB11CCD5"]
```

`name` and `steps` are required; `description` is optional. Step parameters may
be written inline (as above) or nested under `params:`. Explicit `params:` win
over inline keys.

| Kind | Parameters | Behaviour |
|---|---|---|
| `shell` | `command` (required), `expect_contains`, `expect_regex` | Sends one shell line; optionally checks the reply. |
| `mem_expect` | `addr`, `value`, optional `size` (default 4) | Reads a word with `mem get` and compares it exactly. |
| `mem_expect_any` | `addr`, `values` (non-empty list), optional `size` | Passes when the word matches any listed value. |
| `status_expect` | `name`, `value` | Compares `status get <name>` to the expected string. |
| `prompt` | `message` | Prints an operator instruction and waits for Enter. Fails under `--non-interactive`. |
| `wait` | `seconds` (0-600) | Sleeps before the next step. |

Addresses and values accept integers or hex strings with or without `0x`.
Step order is significant: the runner stops at the first failure unless that
step sets `continue_on_fail: true`.

## LExpo first suite

`suites/lexpo.yaml` is the worked example. It checks three things before a
capture:

1. **Firmware.** `version` must contain `5.02.0`; the LExpo patch is built for
   fp 5.02 only.
2. **Patch word.** `mem_expect 0xC007F324 == 0xE309C6FC` proves the patch is
   resident.
3. **Hook site.** `mem_expect_any 0xC02BAD0C in {0xE24DD064, 0xEB11CCD5}`
   accepts either the armed `BL` word or the stock word the one-shot hook writes
   back after it self-disarms.

The suite then hands the capture to a person:

```yaml
  - kind: prompt
    message: "Set M mode and 40 s, press the shutter, wait for the capture, then press Enter"
  - kind: wait
    seconds: 90
```

`wait: 90` covers the 40 s exposure plus its dark frame. A 500 s pass follows
the same shape with a longer wait. Card verification is still manual; mount the
card on the PC and inspect the files as usual.

## Safety

- **Read-only by design, not by sandbox.** The harness itself only calls
  `version`, `status get`, `mem get`, and the lines a suite author writes. It
  does not flash, format, mount, eject, or write memory. It cannot stop a suite
  from containing a write; review suite lines before running them, and keep
  suites to read-only probes.
- **No camera writes.** Do not add `mem set`, `mem save`, `prom write`, card
  formatting, recording, or settings changes to a suite in this repository.
- **Physical preconditions stay human.** Firmware version, the STILL/mode
  dial, stable power, a spare card, and the physical shutter are the operator's
  responsibility. The suite prompts for them rather than pretending to control
  them.
- **A green suite is necessary, not sufficient.** It says the shell answered
  and the words matched. It does not prove the exposure or the card contents;
  those are checked separately.
- **No card assumptions.** `doctor` must work with no card inserted, and no
  step should assume a mounted card.
- **One backend at a time.** Do not run the daemon and a direct client against
  the camera concurrently.

## Tests

The tests use a scripted fake session and never open a camera:

```sh
cd fpSup/tools/fp-autotest
python -m pytest -q tests
```

They cover suite loading (JSON always, YAML when available, and the missing
PyYAML message), every step kind, runner stop/continue behaviour, report
generation, frame encoding/decoding, memory-reply parsing, backend selection,
and the CLI exit codes.

## License

GPL-3.0-or-later, matching fpSup. Each Python file carries an SPDX identifier.
