# 20261027-discard-take-02 — discard take with the LV sampler on; the push engine live (first time)

Same test card and ISPL (81b5a551) as take-01; user adjusted light and ISO. `ispl.py disarm`, then
`take --discard --start-ms 3000 --rec-ms 2000 --lv-every-ms 250 --lv-max 30 --listen ...` (AF half-press first).

What happened:
- **The listener never ran**: `fastreboot.py` (take-01's reboot) restarts `./fpshd` = 3.2.0, which answers `LISTEN83` with
  `ERR unknown`. The script stopped right after the arm; the host then stayed silent 30 s (take + stop + 10 s rule).
- **The take was normal anyway**: ctl done, started 1 / saved 1, 2 presses, **25 blocks discarded / 0 written**,
  REC at +3636 ms, stopped 2513 ms later.
- **The engine with nobody reading**: the first LV push (standby, before REC) armed EP83 and stayed pending; all 363 later
  samples were skipped (mode 0) — nothing waited, the recording started and stopped normally with a transfer pending on EP83.
- Then daemon 3.3.0 back, LISTEN83 (15 s): **30 images, 88.5 MB, every header CRC good, 0 torn / resync / leftover;
  seq gap 424 = the camera's lv_n_skip 424.** 1620×911 YUYV, picture correct (`push_drain/lv_000431.png`). lv_push set 0.

Still to do: a take with the listener actually running (LV *during* recording); make the daemon survive fastreboot
(it restarts ./fpshd = 3.2.0).
