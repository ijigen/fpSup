# 2026-11-18 — Lossless playback: one engine job a frame, no bulk copy, the next file read meanwhile

Bei: the playback decode has to be as efficient as the compression, the decode chip never idle.

## Before (0.3.7test, `play_decode.c` of 2026-10-01)

Per frame, per tile row: stream DMA'd to a scratch, engine init/open/submit/start/wait/close, rows DMA'd back.
3024x2010: 58.6 ms a frame where the engine alone needs 22.7 ms (tools/hwdecode, one band, padded height).
Measured today on a 1024x678-class clip (1.04 MB raw, A001_396, dark-ish): 60 frames, 8.5 ms each, none refused
(the first time a small raster's playback ran at all: they were never compressed before 0.3.7test).

## What changed (0.3.8test .. 0.3.11test; only 0.3.11test is kept)

1. `C05C2D10` returns through our `pool_made` (the entry shim swaps lr): every player buffer is moved up to the
   next 1 KiB (the allocator's address kept in the word below, capacity cut), and put back in `fpl_play_end`
   before the player frees by address (`C001D2B8`). Two more buffers of the same size are taken before the
   player empties the pool: the spare and the one read ahead into.
2. A frame: the engine reads the stream where the player's read put it (the strip offset is 1 KiB aligned in
   the file), one job with the tile-padded height into the spare at the same strip offset; the header is copied
   in front while the engine runs; the slot takes the spare (the player reloads slot+0x14 at C05C0F00), the old
   buffer becomes the spare. Clip open asks for buffers with room for whole default tiles below the last row.
3. While the engine runs, the next frame FILE is read into the second spare (the path at reader+0x80 with its
   six digits at +0x23 one higher). New site `C05C0EA0` (the player's `bl C0366060`): if the player asks for
   exactly that path, the slot takes that buffer and the read is skipped. Any other path: read as stock.
4. A frame the fast way cannot take (no spare, strip not 1 KiB aligned, another grid's padded height not
   fitting) goes the old row way. Counters: fast / rows / why not.

## Measured on the camera (SD, ISO 3200, dim scene; `card_status.py`, the player's read-ahead burst)

| clip | version | frames | hook ms/frame | between hooks ms | engine job open |
|---|---|---|---|---|---|
| 1.04 MB raw (A001_396) | 0.3.7test rows | 60 | 8.5 (last) | not measured | - |
| same | 0.3.8test one job | 58 | 4.1 (engine 3.56, header 0.43) | - | - |
| same | 0.3.9test one job | 57 | 3.96 | 5.3 | 36 % |
| 3.9 MB raw 2016 wide (A001_398) | 0.3.9test one job | 61 | 9.4 | 8.0 | 50 % |
| same | 0.3.10test + read ahead | 61 | 9.65 | 1.2 (0.3 typical, one 48.9) | 83 % |
| same | 0.3.11test header during the job | 61 | 9.0 | 1.1 (0.3 typical, one 41.7) | 88 % |
| 1.04 MB raw (new take) | 0.3.11test | 57 | 3.95 | 1.2 (0.3 typical, one 47.0) | 75 % |

"engine job open" = time between the engine's START and its completion being taken, over hook + gap time; the
job is started before the header copy and the read-ahead, so it overstates the engine's own run time by the
wait for the read when the read is the longer one (2016 wide: read 8.07 ms, engine still busy 0.46 ms after it;
1.04 MB: read 3.76 ms, 0.02 ms after it -- there the card read is as long as the decode). Every frame of these
clips went the fast way, read ahead was handed over for every frame but each clip's first, 0 refused, every
buffer put back (848 / 288 / 1061 slots over the sessions), no spare lost.

Other clips, 0.3.11test: s-f12v3 1:1 (uncompressed by design, 5.26 MB frames) 63 stock frames played, untouched.
s-14 1:1 (18.2 MB frames) and s-12 1:1 (15.6 MB frames): the clip opens, NO frame is read -- the same with
0.3.7test put back on the card (control: 1 clip opened, 0 frames read). Not this change; what the camera
shows for those clips was not looked at.

## Things that went wrong on the way

- The camera's shell died twice (07:20, 08:12; power cycle by Bei). Cause: `raw_accept.py` CALLS Sensor Lab's
  sq_test at `--block + sq_test_off`, and the Lossless build that grew by 4 KiB moved Sensor Lab's block from
  0xC52D5480 to 0xC52D6480. `raw_accept.py` now reads LOAD.LOG and refuses a `--block` that is not where the
  build's file is loaded this boot (checked: the old address is refused, nothing called).
- After a reboot macOS `ptpcamerad` can take the interface (07:19): `ui_drive.py reboot` clears it.
- Around playback the replies of delivered keys time out; `play_last.sh` does not resend and gives each call 5 s.
- One fetch run was very slow (a frame in tens of seconds, 06:30-06:57) and fine afterwards; not explained.

## Offline

test_play_decode 60 (one-job tests + 20 mutants, read-ahead tests + 10 mutants, the old row tests and mutants),
test_card_emulation 35 (the pool shim returns through pool_made to the caller, twice; the read shim with nothing
read ahead is the player's own read), test_v4_lossless 10, codec_job / frame_hold / tile_grid / rec_workspace /
rec_hook OK.

## Not tested

- The picture, by eye (only counters were read): play, pause, fast forward, reverse, clip change.
- Bit-exact pixels in the player's buffer on the camera (the whole-frame job itself: 0 of 6,078,240 pixels
  differ, tools/hwdecode 2026-10-01; header copy and buffer exchange: host fixture only).
- The read shim's "served" branch in the ARM emulation (on the camera it ran for 56-60 frames a clip).
- A lit scene (larger files: the card read becomes the longer side), SSD, long clips, 24 Mpixel clips (they do
  not play at all, see above), clips recorded with a forced grid, REC right after playback (one take after
  each playback here was fine), in-camera playback while HDMI is connected.
