# PreCap release status (2026-10-27)

For whoever runs the loader v4 release path. Not yet committed or pushed.

**Product row for `fpSup/tools/merge-v4/build_catalogue_v4.py`.** This session
did not edit fpSup:

```python
'precap': dict(name='PreCap', sup_id='PCAP', file='PreCap_v0.1.0.BIN',
               summary=dict(en='Hold the half press in high-speed continuous and the last four frames are kept; the full press writes them ahead of the burst.',
                            zh='高速連拍時按住半按留下最近四幀，全按時這四幀寫在連拍之前。'),
               category='monitor', excl=[], author=AUTHOR, credits=[]),
```

`excl=[]` is checked, not assumed: `C038F0E8`, `C038F174`, `C02DC108` and
`C03817D4` appear in no `12 <addr>` declaration of the official card's
`LOAD.LOG` (thirteen sups), so all four claims are `SL_EXCL` and nothing
collides today.

| | |
|---|---|
| builder | `projects/precapture/build/build_precap_sup.py --out DIR` writes `DIR/PreCap_v0.1.0.BIN` |
| sup | `PreCap_v0.1.0.BIN`: 2,664 B, sup_id `PCAP`, header version 1, min_svc 5, block 2,800 B |
| sha256 | `794a2b0eb65a3f8e41e17547fca4b71658c9e9082e3299f838b7012c35849ce0` |
| on the camera | yes. These exact bytes are on the card, confirmed by LOAD.LOG; test shots taken |
| offline | 16 emulator tests pass (`build/test_precap_sup.py`) |
| claims | `C038F0E8` EXCL, `C038F174` EXCL, `C02DC108` EXCL, `C03817D4` EXCL |
| suggested version | `fpsup-precap-v0.1.0` |
| README draft | `release/README.txt` (plain, no firmware addresses) |
| ABOUT draft | `release/ABOUT.txt` |

## Two things a packager needs to know

1. **The sup returns `SL_KEEP`, not `SL_RELEASE`.** The fpSup-page row points
   into the sup's own block, so releasing it would leave a row pointing at
   freed memory. Anything that audits the release (`cave_audit.py`) should not
   flag it.
2. **The four stub addresses are baked into the loader's cave**, not into the
   block: block-to-firmware distance is about 2 GB and a `bl` only reaches
   ±32 MB, so `svc->cave_alloc` is the only workable landing pad. This is why
   the sup asks for 32 bytes of cave.

## Blockers

None. The open question is design, not code: ON at every boot is this author's
choice (the feature should be used, not discovered). A packager who disagrees
can flip one line — `str r0, [r4, #P_ON]` in `precap.S` — to ship it OFF.
