================================================================
 PreCap  fpSup-PreCap v0.1.0
 SIGMA fp Ver.5.02 only -- Loader v4 card
================================================================

WHAT IT IS

  Pre-capture for the high-speed continuous drive mode. Hold the half
  press and the camera runs the burst as usual, but the frames do not
  reach the card: the newest four are kept in a ring, about half a
  second of them. Press the shutter all the way and those four are
  written ahead of the frames taken after the press, so the picture
  that made you press is in the file. Let go of the half press and the
  ring is thrown away.

  - Drive mode: HIGH SPEED CONTINUOUS only. Single shot, medium
    continuous and the cine modes are untouched -- there the camera
    behaves exactly as without this sup.
  - The shutter sound is muted while the ring fills. From the full
    press onwards it sounds normally.
  - Where: the fpSup page, row "PreCap", ON / OFF. ON at every boot.
  - ON is the default because the feature is meant to be used, not
    discovered. Turn it OFF if you would rather not have four extra
    frames in a burst.

WHAT TO EXPECT

  The burst really runs underneath: the screen flickers, the frame
  counter advances and the file numbering moves on while you are only
  half pressing. This is the cost of driving the camera's own burst
  pipeline instead of a private one, and it is why the four committed
  frames are exact rather than approximate.

  If you half press and then let go, nothing is written. The frame
  numbers still move.

INSTALL

  Copy PreCap_v0.1.0.BIN into \fpSup\ next to the other sups. To make
  a whole card, use fpSup-Merge and tick PreCap.

  Take the card out and the camera is back to normal.

TESTED

  2026-10-27, SIGMA fp Ver.5.02, on a Loader v4 card alongside the
  other twelve sups. Half press alone: no file, ring discarded.
  Half press then full press: four frames committed ahead of the
  burst. Single shot: the factory shutter, no pre-capture engaged.
  Five power cycles with the hooks still installed and the cave never
  walked past its end.

  Offline: 16 emulator tests (entry contract, the page switch, the
  ring, commit, drop, mute) plus the 24 tests of the development
  build this one was made from.

NOT TESTED

  - Medium continuous and the cine modes were only checked to the
    extent that they do not engage; their own recording was not
    measured with this sup on the card.
  - Bursts longer than ten seconds: the ring stops pre-capturing at
    ten seconds and returns to the plain burst, on purpose.

REPORTING

  SIGMA fp Discord, https://discord.gg/XeFK5zNZpT -- say PreCap.
  This is unofficial firmware modification. Use at your own risk.
