# fp USB Shell v2

A command channel to the SIGMA fp over USB, built on the camera's **own PTP gadget**.

The firmware builds the descriptors, creates and enables the endpoints, and
re-creates them after a record-mode reconfiguration. That last point is the whole
reason for the rewrite: v1 bolted on endpoints the firmware did not know about,
so recording tore the channel down. **Recording while connected now works** —
verified with the daemon attached and commands already exchanged, which is the
exact condition that broke v1.

Seven words of firmware are changed. Everything else is our code.

## What you get

```
EP 0x01 OUT  bulk 1024, burst 3    commands
EP 0x82 IN   bulk 1024, burst 3    replies
EP 0x83 IN   bulk 1024, burst 3    streaming, for a hook to arm directly
```

All three are firmware-owned. The third one is PTP's unused interrupt endpoint,
turned into a second bulk IN so a stream and the command channel do not block
each other.

One command: **`shl <line>`** runs `<line>` in the firmware's own shell and
returns what it printed. `mem set` and `mem save` come along for free, so the
worker needs no memory commands of its own.

## The patches

| address | from → to | why |
|---|---|---|
| `0xC0CF3740` | `03 06 01 01` → `03 ff ff ff` | interface class → vendor, so the host's PTP stack does not claim interface 0 first |
| `0xC0CF3780/84` | interrupt → bulk | PTP's unused EP 0x83 becomes a second bulk IN (SuperSpeed) |
| `0xC0CF3758/5C` | companion burst 0 → 3 | its SuperSpeed companion |
| `0xC0CF3798/9C` | interrupt → bulk | the same at full speed |

Every descriptor keeps its length, so the configuration totals still hold and
nothing else moves. Delete the lines and reboot to get stock PTP back.

The firmware normalises `wMaxPacketSize` per speed and type when it emits the
descriptor, so only the type has to be patched — the host receives 1024 even
though the staging array still reads 64.

## Two things that are easy to get wrong

**Do not touch an endpoint before the firmware configures it.** `DALEPENA`
(`0x2100C720`) is the controller's own record of which physical endpoints exist,
and it stays `0x003` — EP0 only — until the host completes SET_CONFIGURATION.
Issuing DEPCMDs before that competes with the driver while it is enumerating,
and enumeration is what loses: three boots in a row failed this way. `USB_STATE`
is no substitute; it reads 2 long before the endpoints exist. The worker gates on
`(DALEPENA & 0x24) == 0x24`.

**Judge from a clean boot.** Several wrong conclusions in this work came from
reading a state that earlier experiments had already disturbed.

## Layout

```
camera/worker.S      camera side, loaded at 0xC072E000
camera/oneshot.S     template for running a routine once, from the host
armasm.py            assembles ARM source and resolves its internal calls
build_autorun.py     assembles worker.S and emits the card script
inject.py            writes a one-shot routine, arms it, waits for it
host/fpshd.c         daemon, listens on /tmp/fpshd.sock
host/fpsh            client
host/lsdesc.c        prints the descriptor the host actually received
autorun/AutoRun.txt  what goes on the card
docs/                reverse-engineering notes (Traditional Chinese)
```

## Use

```sh
make                                  # builds fpshd, lsdesc and the AutoRun
make card CARD=/Volumes/<card name>

# Boot the camera with USB UNPLUGGED. The screen shows a progress bar and ends
# at fpSup! — a bar that stops is a load that stopped there. Then attach USB.
./fpshd &
./host/fpsh ping
./host/fpsh mem get 0xC072F000,,0x34    # worker state
./lsdesc                                # what the host enumerated
```

## Running code on the camera

The shell can write memory but nothing can call it, so there is no `call`
command and no need for one. To run something, point an address the firmware
already calls at your routine, let it fire once, and put the original word back.
`camera/oneshot.S` is that plumbing with a payload slot; `inject.py` writes it,
arms the call site and waits for it to report back. Neither the AutoRun nor the
daemon is involved.

```sh
./inject.py camera/oneshot.S
./host/fpsh mem get 0xC072F500,,0x20
```

The borrowed site is the gyro callback at `0xC00D0794` (50-90 Hz), so the payload
runs in that callback's context: do not block and do not take a mutex.

## Protocol

FPSH v1, 64-byte frames, little-endian.

```
+00 magic "FPSH"   +04 version   +05 command   +06 flags
+08 sequence       +0C payload_length          +0E status
+10 crc32 (whole frame with this field zeroed)
+14 payload, 44 bytes
```

A reply may span several frames — **flags bit 0 means another frame follows** —
and a command may be longer than 44 bytes, because the camera reads the payload
as a NUL-terminated string and the OUT TRB is 1 KiB. The CRC still covers only
the first 64 bytes.

## Not done yet

* EP 0x83 has not moved a byte yet. It is enabled and correctly described, but
  nothing has armed it — the first hook that needs it will be the test.
* v1's hook-push sources still target the old endpoint (`0xC31E3274`,
  `StartTransfer(9)`); on this gadget those become `0xC31E3270` and
  `StartTransfer(7)`.
