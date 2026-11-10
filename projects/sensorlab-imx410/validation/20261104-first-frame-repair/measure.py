#!/usr/bin/env python3
"""Instruction counts of the first-frame arm / check / repair (apply/ap.c v0.7.26test) under unicorn, against the real
image, through test_apply.FFCam (the real hooked sites C031C948 / C038BDB4).  Offline only.

    cd projects/sensorlab-imx410/validation/20261104-first-frame-repair
    python3 -B measure.py            # prints a table, writes measure.json

Counted: every instruction executed between the site and its return (the veneer, ap_hook, ap_ff_*, the firmware's
FUN_c0631b98 / FUN_c03753c0 below them), and how many of them are memory loads / stores in the raster.  The D-cache
routine C000E91C and the tick are stubs here (0 instructions): their cost is added from the notes in the README.
"""
import json, pathlib, struct, sys
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'apply'))
sys.argv = sys.argv[:1]
import test_apply as T                                       # noqa: E402
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE  # noqa: E402


def count(cam, fn):
    n = [0, 0, 0]
    h1 = cam.mu.hook_add(UC_HOOK_CODE, lambda uc, a, s, d: n.__setitem__(0, n[0] + 1))
    hs = [h1]
    for base in (T.FF_U, T.FF_U + 0x80000000):              # the raster window, both aliases
        hs.append(cam.mu.hook_add(UC_HOOK_MEM_READ, lambda uc, acc, a, s, v, d: n.__setitem__(1, n[1] + s),
                                  begin=base, end=base + T.FF_SIZE - 1))
        hs.append(cam.mu.hook_add(UC_HOOK_MEM_WRITE, lambda uc, acc, a, s, v, d: n.__setitem__(2, n[2] + s),
                                  begin=base, end=base + T.FF_SIZE - 1))
    fn()
    for h in hs:
        cam.mu.hook_del(h)
    return n


rows = []
for name, args, fmt, w, h in (('12v2 3024x2010 RAW12', T.FF_12V2, 0, 3024, 2010),
                              ('1x1 14-bit 3024x2020 RAW14', T.R14_1X1, 1, 3024, 2020)):
    for shifted in (True, False):
        cam = T.FFCam()
        assert cam.init() == T.AP_OK
        assert cam.apply(T.recipe(*args)[0]) == T.AP_OK
        row = w * (14 if fmt else 12) // 8
        ref = bytes(row * h)
        cam.mu.mem_write(T.FF_DEST, b'\x55' * (row * h))
        mode = cam.status()['mode_id']
        arm = count(cam, lambda: cam.arm(mode, fmt))
        if shifted:
            cam.mu.mem_write(T.FF_DEST + row, ref[:row * (h - 1)])
        else:
            cam.mu.mem_write(T.FF_DEST, ref)
        chk = count(cam, lambda: cam.arrive(T.FF_DEST))
        st = cam.status()
        nxt = count(cam, lambda: cam.arrive(T.FF_DEST, ident=9))
        rows.append(dict(case=name, shifted=shifted, row_bytes=row, rows=h, moved_bytes=row * (h - 1) + row if shifted else 0,
                         arm_insns=arm[0], arm_raster_bytes_written=arm[2],
                         arrival_insns=chk[0], arrival_raster_bytes_read=chk[1], arrival_raster_bytes_written=chk[2],
                         later_frame_insns=nxt[0], repairs=st['first_repairs'], ok=st['first_ok']))
for r in rows:
    print(f"{r['case']:28s} {'shifted' if r['shifted'] else 'normal ':8s} arm {r['arm_insns']:5d} insns "
          f"({r['arm_raster_bytes_written']} B)  arrival {r['arrival_insns']:9d} insns, raster read {r['arrival_raster_bytes_read']:9d} B "
          f"written {r['arrival_raster_bytes_written']:9d} B  later frames {r['later_frame_insns']} insns")
(HERE / 'measure.json').write_text(json.dumps(rows, indent=1) + '\n')
