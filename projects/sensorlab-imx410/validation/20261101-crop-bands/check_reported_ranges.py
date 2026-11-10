#!/usr/bin/env python3
"""Offline SensorLab crop-band regression; never opens a camera or writes a card.

Execute real apply-generated aspect pairs through W v4's two call sites and
the native rectangle fitter, with a strict code/write boundary for the latter.
The 2K 11-bit 3x2 selection is a declared fixture, not the user's current recipe.
The menu itself, the display consumer and physical LCD do not execute.
"""
import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import struct
import sys
import time

ROOT = Path('/Users/dido/Developer.localized/SIGMAfp_re')
sys.path.insert(0, str(ROOT / 'projects/sensorlab-imx410/apply'))
import test_apply as T
import test_lv_fit as L
import test_lv_routes as W
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn import arm_const as R


def fingerprints():
    paths = set()
    for name in ('apply', 'core', 'qs', 'menu'):
        base = ROOT / 'projects/sensorlab-imx410' / name
        paths.update(p for p in base.glob('*') if p.suffix in ('.c', '.h', '.py'))
    paths.add(ROOT / 'fpSup/loader-v4/build_v4.py')
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths)}


def checked_fit(cam, source):
    """Only approved ROM, product code/veneers, private stack and output may run/write."""
    work = T.WORK + 0x3F0000
    ranges = [(lo, hi) for lo, hi, _ in L.NATIVE_RANGES] + [
        (T.BLOB, T.BLOB + len(cam.img)),
        (T.MEM, T.MEM + (len(cam.claims) - 1) * 88),
        (T.CAVE_ARENA, cam.w(T.CAVE_BUMP)),
    ]
    seen = set()
    def code(mu, addr, size, data):
        if addr == T.DONE:
            return
        if not any(lo <= addr and addr + size <= hi for lo, hi in ranges):
            raise AssertionError(f'unapproved native/product execution: {addr:#x}')
        seen.add(addr)
    def write(mu, access, addr, size, value, data):
        if T.STACK - 0x10000 <= addr and addr + size <= T.STACK:
            return
        if work <= addr and addr + size <= work + 16:
            return
        raise AssertionError(f'unapproved fitter write: {addr:#x} size={size}')
    handles = [cam.mu.hook_add(UC_HOOK_CODE, code),
               cam.mu.hook_add(UC_HOOK_MEM_WRITE, write)]
    try:
        for lo, hi in ranges:
            cam.mu.ctl_remove_cache(lo, hi)
        saved = {getattr(R, f'UC_ARM_REG_R{n}'): 0x55550000 + n for n in range(4, 12)}
        for number, value in saved.items():
            cam.mu.reg_write(number, value)
        def call(addr, *args):
            return cam.call(addr, *args, sp=T.STACK - 0x1000)
        result = L.fit_native(cam.mu, call, source, work=work)
        assert cam.r(R.UC_ARM_REG_SP) == T.STACK - 0x1000
        assert all(cam.r(k) == v for k, v in saved.items()), 'callee-saved register damage'
        assert L.FIT in seen and L.SNAP_END in seen
        return result, len(seen)
    finally:
        for handle in handles:
            cam.mu.hook_del(handle)


def run(out):
    started = time.time()
    before = fingerprints()
    cam, _ = W.prepared(active=True)
    crops = sorted({(w, 4040) for w in range(5088, 6049, 16)} |
                   {(6048, h) for h in range(3520, 4041, 2)})
    rates = [('live3_30.018_fixture', Fraction(30018, 1000)),
             ('prior_trial_19.026_fixture', Fraction(72000000, 3784294))]
    results = []
    for label, fps in rates:
        for dw, dh in crops:
            # Explicit 2K-like RES fixture. SensorLab DC steps are 16 x 2;
            # its recording raster is independently aligned to 16 x 2.
            rw, rh = (dw // 3) & ~15, (dh // 3) & ~1
            sel = T.recipe(dw, dh, rw, rh, '3x2', 11, fps=fps)[0]
            rc = cam.apply(sel)
            assert rc in (T.AP_OK, T.AP_IDLE), (sel, rc, cam.status())
            ptr = cam.call(T.RATIO, 9)
            assert T.MEM <= ptr < T.MEM + T.AP_MEM
            pair = L.words(cam.mu, ptr, 2)
            cam.mu.mem_write(W.INPUT, struct.pack('<2I', *pair))
            routed, classifier_entries = W.w_pair(cam)
            assert routed == ptr and not classifier_entries, (sel, pair, routed, ptr)
            got, instructions = checked_fit(cam, routed)
            expected = L.continuous_rectangle(pair)
            assert got == expected, (sel, pair, got, expected)
            stock = L.continuous_rectangle(L.stock_ratio(pair))
            results.append(dict(rate_fixture=label, dc=[dw, dh], raster=[rw, rh],
                                key=sel['key'], hmax=sel['hm'], vmax=sel['vmax'],
                                aspect=pair, rectangle=got, stock_rectangle=stock,
                                differs_from_stock=got != stock,
                                checked_instruction_addresses=instructions))
        print(f'{label}: {len(crops)} crop selections passed', flush=True)

    # Counterexample in emulator memory only: removing just the ratio restore
    # must reintroduce the reported full-width distortion. Restore before end.
    sel = T.recipe(5088, 4040, 1696, 1346, '3x2', 11, fps=rates[0][1])[0]
    assert cam.apply(sel) in (T.AP_OK, T.AP_IDLE)
    ptr = cam.call(T.RATIO, 9)
    pair = L.words(cam.mu, ptr, 2)
    original = cam.w(L.SNAP_END)
    try:
        cam.put(L.SNAP_END, T.iw(L.SNAP_END))
        damaged, _ = checked_fit(cam, ptr)
        assert damaged != L.continuous_rectangle(pair)
        assert damaged == L.continuous_rectangle(L.stock_ratio(pair))
    finally:
        cam.put(L.SNAP_END, original)
    restored, _ = checked_fit(cam, ptr)
    assert restored == L.continuous_rectangle(pair)
    after = fingerprints()
    assert before == after, 'shared source changed during this run'
    data = dict(result='PASS', elapsed_seconds=round(time.time() - started, 3),
                unique_crops=len(crops), selections=len(results),
                actual_menu_flow_executed=False, camera_operations=0,
                source_fingerprints=before,
                firmware_sha256=hashlib.sha256(L.image()).hexdigest(),
                product_apply_unit_sha256=hashlib.sha256(cam.img).hexdigest(),
                negative_control=dict(dc=[5088,4040], aspect=pair,
                                      hook_removed=damaged, hook_restored=restored),
                limitations=[
                    'Declared 2K 11-bit 3x2 RES/rate fixtures; current user recipe unknown.',
                    'Menu-to-apply events are not exercised: test starts at the real apply API.',
                    'Settings, LV stop/start and sensor I/O use the existing explicit Cam fixtures.',
                    '3:2 1620x1080 display fixture; no actual display selection/queue, DMA or LCD.',
                    'Passing offline calculations do not establish a fixed physical liveview.',
                    'Candidate source predates this run; no new product-source correction was made.'
                ], cases=results)
    out.write_text(json.dumps(data, indent=2) + '\n')
    print(json.dumps({k:data[k] for k in ('result','elapsed_seconds','unique_crops','selections')}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    run(args.report)
