# Rear wheel decoder v6 — release

SIGMA fp, **firmware 5.02 only**. RAM only: nothing is written to NAND, EEPROM
or settings. Verified on the camera by the user on 2026-11-07 ("works perfect").

| file | what |
|---|---|
| `AutoRun.txt` | the card: decoder v6 + fast boot (153 commands, no comments) |
| `dial2_fast.S` | the decoder source, Thumb-2, 107 of 120 words at `0xC02E1CE8` |
| `SHA256SUMS` | checksums of both |

Frozen copy of commit 45b7796 (`cards/smooth/AutoRun.txt`, `dial2_fast.S`).
`build.py` does not write here; a later version gets its own folder.

## What it does

The rear wheel (Shinmei TSW-26) bounces badly. v6 lets the 12.5 ms poll decide
when a click starts and ends (a poll almost never lands inside a bounce), and
the wheel interrupts decide its direction and count fast spins. One click per
detent, **clockwise = +1**. Details: `../../HOW_IT_WORKS.md`, `../../NOTES.md`
sections 19–22.

## Install

1. Copy `AutoRun.txt` to the **root** of the SD card.
2. Switch the camera on and leave the rear wheel still for a moment.
   `ready` on screen means the decoder is installed.

It stays active until the battery is removed (a power-switch restart keeps
it). With `AutoRun.txt` left on the card it is installed again at every start.

## Undo

Remove card **and** battery, or run `../../cards/restore/AutoRun.txt`
(stock handler back without a battery pull).

## Rebuild / check

```bash
cd ../.. && python3 build.py && python3 test_fast.py
```
`build.py` assembles `dial2_fast.S` with clang and checks the replaced words
against the stock 5.02 image; `test_fast.py` runs the bytes under unicorn on
the camera recordings and synthetic cases.
