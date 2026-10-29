# 20261027-report-take-01 — reports (source 5) on; EP83 came up half-patched, so the pushes mostly stalled

ISPL 5132f1ba (reports: ix_cap snapshot per control event + heartbeat). Reboot (fastreboot) → EP83 came up interrupt/64;
user re-plugged → host saw **EP83 attr 02 (bulk), MPS 64, interval 11**.
`take --discard --start-ms 3000 --rec-ms 2000 --lv-every-ms 500 --lv-max 20 --cd-after-ms 2000 --report --heartbeat-ms 1000`.

- Take itself fine: ctl done, started 1 / saved 1, 2 presses, 25 discarded / 0 written.
- Pushes: host got 4 LV (13 MB); camera: lv sent 5 / skip 12, **cdng sent 0 / skip 5 (timeouts), reports sent 0 / skip 13**.
  daemon stalls=0, quarantine=0. (The summary fell back to the shell read; heartbeat and LV turned off afterwards.)
- Cause: the host's EP83 descriptor is the SuperSpeed one **half patched** — word 0xC0CF3780 (bmAttributes → bulk) applied,
  word 0xC0CF3784 (MPS 1024 / interval 0) not — although RAM now holds both patched words. So the host reads a **copy built
  while the shell sup was applying its patch rows** (a race at USB init); a re-plug re-sends that stale copy.
  The poff restart of take-02/03 initialised USB after the patches and got the full 1024 (88–98 MB pushed cleanly).
- RAM now: SS table 0xC0CF3770.. EP01/82/83 = bulk 1024 int 0; FS/HS table 0xC0CF3788.. = bulk 64 int 0; config headers
  0xC0CF37B8 (57 B, SS) / 0xC0CF37D0 (39 B); the 0xC072B0xx copies are other gadgets' (interrupt, untouched).

Next: find where the firmware builds the outgoing config descriptor and rebuild it after the patch (+ a soft reconnect), so
EP83 is reliably bulk 1024 without anyone touching the cable.
