# 20261027-discard-take-03 — LV pushed DURING a real (discard) take, host listening the whole time

fpshd 3.3.0 now installed as ./fpshd. Same test card / ISPL 81b5a551. AF half-press, then
`take --discard --start-ms 3000 --rec-ms 2000 --lv-every-ms 250 --lv-max 30 --listen push/` (host sends nothing after the arm).

- Take: ctl done, started 1 / saved 1, 2 presses, **25 blocks discarded / 0 written**, REC +3643 ms, stopped 2528 ms later.
- Push: **30 images, 98.1 MB, 0 skipped, 0 torn / resync / leftover, all CRC good**; camera lv_n_sent 30, skip 0, bad 0, err 0.
- **8 images during recording** (header flag bit0), 13 before, 9 after. Interval 250 ms except two gaps: ~775 ms at the
  start and ~737 ms at the stop — the control task is inside the firmware record script (movrecstwai / movsavewai) there.
- **The LCD ring changes geometry while recording: 1620×911 in standby → 1920×1080 during REC** (back to 1620×911 after);
  the sampler re-reads the descriptor every sample, so it followed. Picture correct (`rec_lv_example.png`).
- lv_push set back to 0.

So the push engine works during a recording with the writer pipeline running, and costs the take nothing measurable.
