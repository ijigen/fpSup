#!/usr/bin/env python3
"""MOV feasibility facts for Sensor Lab (0.0.3test, notes/MOV_FEASIBILITY.md).  Offline only: the real image
(out/MAIN_c0000000.bin) under unicorn through apply/test_apply.Cam (the SensorLab apply unit armed), nothing built
for the camera.

  1. the MOV route table (general 0xC0BE4D50, the cfg[0x45] one 0xC0BE5050) vs the CinemaDNG ones: same key -> same
     sensor mode? (the readout is a mode; MOV and CDNG differ in the profile only)
  2. with a SensorLab slot live, the native MOV searcher FUN_c043cdb8 still returns the stock entry and the apply
     unit's picker hook (C043CCF8) never runs: MOV today records stock, by construction
  3. the native gather of stock MOV profiles vs their CinemaDNG twins: which canvas words differ (what a virtual MOV
     profile would have to own)

  python3 -B tools/mov_feasibility.py [--json OUT]
"""
import argparse
import json
import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
PROJ = HERE.parent
sys.path.insert(0, str(PROJ / 'apply'))
import test_apply as T                                       # noqa: E402

B = 0xC0000000
GEN, G45 = 0xC0BE4D50, 0xC0BE5050
CDNG = {8: 0xC0BE5810, 10: 0xC0BE59B0, 12: 0xC0BE5B50}
MOV_SEARCH = 0xC043CDB8                                      # FUN_c043b988's general-table scan (span 0x300)
G45_SEARCH = 0xC043CE78                                      # its cfg[0x45] scan (span 0x100)


def table(img, at, n):
    out = []
    for i in range(n):
        c, pid, mode, k = struct.unpack_from('<4I', img, at - B + 16 * i)
        o = k - B
        out.append(dict(key=img[o:img.index(b'\0', o)].decode(), const=c, pid=pid, mode=mode))
    return out


def facts():
    img = (T.ROOT / 'out' / 'MAIN_c0000000.bin').read_bytes()
    gen, g45 = table(img, GEN, 48), table(img, G45, 16)
    cd = {b: table(img, t, 26) for b, t in CDNG.items()}
    by12 = {r['key']: r for r in cd[12]}
    same, differ, mov_only = [], [], []
    for r in gen:
        c = by12.get(r['key'])
        if not c:
            mov_only.append(r['key'])
        elif c['mode'] == r['mode']:
            same.append(r['key'])
        else:
            differ.append((r['key'], r['mode'], c['mode']))
    out = dict(tables=dict(mov_general=len(gen), mov_cfg45=len(g45), cdng=len(cd[12]),
                           same_mode=same, different_mode=differ, mov_only=mov_only,
                           cfg45_keys=[(r['key'], r['pid'], r['mode']) for r in g45]))

    # 2. SensorLab live (the apply tests' V1 recipe on the 29.97 carrier): MOV searcher vs the CDNG picker
    cam = T.Cam()
    assert cam.init() == T.AP_OK
    assert cam.apply(T.recipe(*T.V1_ARGS)[0]) == T.AP_OK
    picks0 = cam.status()['picks']
    route = {}
    for k in ('UHD30', 'UHD30CROP', 'FHD30'):
        e = cam.call(MOV_SEARCH, 0, GEN, cam.key(k))
        route[k] = dict(entry=hex(e), stock=GEN <= e < GEN + 0x300,
                        pid=cam.w(e + 4) if e else None, mode=cam.w(e + 8) if e else None)
    during = cam.status()['picks'] - picks0
    ours = cam.call(T.PICKER, 0, CDNG[12], cam.key('UHD30'))
    out['live_slot'] = dict(mov_route=route, picks_during_mov=during,
                            cdng_answer_is_ours=T.MEM <= ours < T.MEM + 0x8000, slot_pid=cam.status()['pid'],
                            slot_mode=cam.status()['mode_id'])

    # 3. canvas words of the MOV profiles vs their CDNG twins (same key, same sensor mode)
    ref = T.Cam()
    pairs = []
    for r in gen:
        c = by12.get(r['key'])
        if not c or c['mode'] != r['mode'] or r['key'].endswith('CROP'):
            continue
        a, b = ref.canvas(r['pid']), ref.canvas(c['pid'])
        pairs.append(dict(key=r['key'], mov_pid=r['pid'], cdng_pid=c['pid'],
                          differ={hex(4 * i): [a[i], b[i]] for i in range(65) if a[i] != b[i]}))
    out['canvas'] = pairs
    words = {}
    for p in pairs:
        for w in p['differ']:
            words[w] = words.get(w, 0) + 1
    out['canvas_words_that_differ'] = dict(sorted(words.items(), key=lambda kv: int(kv[0], 16)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json')
    a = ap.parse_args()
    f = facts()
    s = json.dumps(f, indent=1)
    if a.json:
        pathlib.Path(a.json).write_text(s + '\n')
    t = f['tables']
    print('MOV general', t['mov_general'], 'entries; same sensor mode as CDNG 12-bit:', len(t['same_mode']),
          'different:', t['different_mode'], 'MOV only:', len(t['mov_only']))
    print('live slot: MOV route', {k: (v['stock'], v['pid'], v['mode']) for k, v in f['live_slot']['mov_route'].items()},
          'picker hook runs during MOV lookups:', f['live_slot']['picks_during_mov'],
          'CDNG answer ours:', f['live_slot']['cdng_answer_is_ours'])
    print('canvas words that differ MOV vs CDNG (count of', len(f['canvas']), 'pairs):', f['canvas_words_that_differ'])


if __name__ == '__main__':
    main()
