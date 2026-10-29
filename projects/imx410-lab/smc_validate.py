#!/usr/bin/env python3
"""SMC verification round (notes/SMC_VERIFY.md): generated 8-table mode -> virtual mode under host 10 -> the
firmware's own mode switch (magnify) -> checks. No direct sensor/SoC writes: everything comes from the tables.

    smc_validate.py OUT [--set core|sweep] [--dark]
Checks: G2 switch + receiver lines == plan; G5 live view (display transfer count grows); burst timing (8 frames);
--dark (lens capped): G4 black -- image black == OB black (+-3 DN), no row/column structure; otherwise G3 exposure
linearity (SHS held, VMAX +150/+400). Results -> captures/smc_validated.json (id -> checks).
"""
import argparse, json, pathlib, struct, subprocess, sys, time
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import numpy as np
import readout_cfg as C
import smc

R10 = smc.R10_OF_CLS          # one table: smc.create writes R10 itself since 2026-10-27 (isp-lab); kept for callers
DB = HERE / 'captures' / 'smc_validated.json'
VREG = 0x30100020
# image-minus-OB black of stock modes per readout class, dark, AE gain (captures/smc_r1/stock*): 8 -> 5.95, 11 -> 6.81, 58 -> 8.03, 12 -> 2.30;
# normal classes measured ~0 (round 1 PASS). 1x1 fast (no stock mode): the fast-class value.
# camera settings every pass runs under (user 2026-10-24): full_v1 ran at ISO 800 / 1/30 because a peer had changed
# them, and the dark references (measured at ISO auto) no longer matched -- the run now refuses other settings and
# records what it read. Read with `menu SetIso` / `menu SetShutterSpeed` (no argument = read).
CAMERA = {'SetIso': '800', 'SetShutterSpeed': '1/30'}     # = full_v1 (user 2026-10-24: dim light, 1/30)


def camera_settings():
    import bufa_probe as B
    return {k: B.P().sh(f'menu {k}').strip() for k in CAMERA}


FLICKER_HZ = 119.94          # mains 59.97 Hz here (IMX410_RULES §55)
BLACK_REF_FAST = 7.4        # 1x1 fast AD (12fast/12fastW): no stock mode; the fast-class value (round 1 used it)
BLACK_REF = {19: 7.4, 21: 6.0, 23: 2.3, 17: 0.0, 16: 0.0, 18: 0.0, 20: 0.0, 22: 0.0}

# Round 4 (SMC_VERIFY): image-minus-OB black of the donor-class stock mode at FIXED analog gain codes (0x400, 3900),
# measured the same way (captures/smc_r4_stock). AE-gain comparisons were unreliable (AE picks different gains per mode).
# The fast classes grow ~+2 DN at code 3900 from short (540 rows) to full height (dark shading), hence the wider tolerance.
STOCK_BLACK = {'14': (0.7, -1.3), '12': (1.9, 1.8), '12fast': (3.9, 5.2), '12fastW': (3.9, 5.2), '2x2': (6.1, 1.2),
               '2x2fast': (3.5, 7.3), '3x3': (1.9, 0.7), '3x3fast': (3.9, 5.2), '3x6': (1.1, 1.2), '3x6fast': (1.9, 2.2)}
# ISO 800 (CAMERA, 2026-10-24, captures/stockblack_iso800, same 14 stock modes, same method): the offsets above were
# measured at ISO auto and the stock modes themselves moved (98: 6.1 -> 3.9 at 0x400, 11: 7.3 -> 3.3 at 3900) -- the
# forced codes set the analog gain only, the ISO setting still moves the black. Same mode -> key mapping as round 4.
STOCK_BLACK_AUTO = dict(STOCK_BLACK)
STOCK_BLACK.update({'14': (0.5, -0.9), '12': (1.3, 1.5), '12fast': (2.5, 3.5), '12fastW': (2.5, 3.5), '2x2': (3.9, 0.8),
                    '2x2fast': (2.4, 3.3), '3x3': (1.4, -0.2), '3x3fast': (2.5, 3.5), '3x6': (0.6, 1.9), '3x6fast': (1.0, 1.6)})
BLACK_TOL = (2.0, 3.0)
# stock binned classes at full height (sensor window OFF, 0003=0; SMC_VERIFY round 17): the image-vs-OB offset sits ~2-3 DN
# below the windowed stock reference (2x2 4.2 vs 6.1 at 0x400, 2x2fast 4.5 vs 7.3 at 3900) -- own reference
STOCK_BLACK_FULL = {'2x2': (4.2, 1.0), '2x2fast': (2.2, 4.5), '3x3': (1.1, 0.9), '3x3fast': (2.5, 4.5), '3x6': (1.0, 1.4),
                    '3x6fast': (1.8, 2.0)}
# matrix classes (§67): their own reference = mean image-vs-OB offset at 0x400 / 3900 over the 7-8 dark configs of
# smc_m1 (2026-10-23, lens capped; spread within a class <= 1.1 DN). 12h3 / f12h3 / 14v2 / 14v3: none yet (bound)
STOCK_BLACK.update({'12v2': (4.1, 0.5), '12v3': (1.2, 1.0), '12h2': (1.1, 1.4), '12h2v3': (1.1, 1.2), '12h3v2': (3.4, 0.1),
                    'f12v2': (1.8, 5.2), 'f12v3': (2.2, 5.7), 'f12h2': (2.4, 4.9), 'f12h2v3': (2.3, 5.2), 'f12h3v2': (2.8, 3.7),
                    '14v2': (0.3, -1.3), '14v3': (0.4, -1.3)})   # 14-bit: SMC_VERIFY round 19 (= stock 14 class 0.7/-1.3)


MATRIX_BLACK_BOUND = (4.0, 10.0)   # matrix classes (§67) have no stock mode: until their own reference exists, bound the
                                   # offset at the widest stock class values (2x2 6.1 at 0x400, 2x2fast 7.3 at 3900) + tol


def _black_base(key):
    """width presets are judged against the class they were cut from (2026-10-23 [I]: the format word sets the width
    only, so the black offset should match): 12w18 -> 12, f12w18 -> 12fast (fast 1x1), f12v2w2C -> f12v2, 14v3w2B -> 14v3"""
    import re as _re
    b = _re.sub(r'w(18|03|2C|2B)$', '', key)
    return '12fast' if b == 'f12' else b


def black_judge(key, gains, full=False):
    if key not in STOCK_BLACK and _black_base(key) in STOCK_BLACK:
        r = black_judge(_black_base(key), gains, full)
        r['ref_from'] = _black_base(key)
        return r
    if key not in STOCK_BLACK:
        got = (gains.get(1024, gains.get('1024')), gains.get(3900, gains.get('3900')))
        if None in got:
            return dict(PASS=False, why='missing gain frame')
        return dict(g1024=got[0], g3900=got[1], ref='bound', bound=list(MATRIX_BLACK_BOUND),
                    PASS=all(abs(g) <= b for g, b in zip(got, MATRIX_BLACK_BOUND)))
    ref = STOCK_BLACK_FULL[key] if full and key in STOCK_BLACK_FULL else STOCK_BLACK[key]
    got = (gains.get(1024, gains.get('1024')), gains.get(3900, gains.get('3900')))
    if None in got:
        return dict(PASS=False, why='missing gain frame')
    dev = [g - r for g, r in zip(got, ref)]
    return dict(g1024=got[0], g3900=got[1], ref=list(ref), dev=dev, PASS=all(abs(d) <= t for d, t in zip(dev, BLACK_TOL)))


def rows_ok(img, ob):
    """every image row must be a real row: no saturated / far-off rows (round 4: tall 2x2/3x3 windows ran past the
    readable area and the last ~50 rows read 4095, invisible to the receiver line count)"""
    rp = img.mean(1)
    bad = int((np.abs(rp - ob) > 60).sum())
    return dict(bad_rows=bad, PASS=bad == 0)


CORE = [('12', (6060, 3408), (3840, 2160)), ('12', (3840, 2160), (3840, 2160)), ('14', (4152, 2160), (3840, 2160)),
        ('12fast', (4176, 2016), (4160, 2016)), ('12fastW', (6060, 3408), (3840, 2160)), ('2x2', (6060, 3408), (1920, 1080)),
        ('2x2fast', (3840, 2160), (1920, 1080)), ('3x3', (6060, 3408), (1920, 1080)), ('3x3fast', (5760, 3240), (1920, 1080)),
        ('3x6', (6060, 4040), (1008, 662)), ('3x6fast', (6060, 4040), (1008, 662))]


def lin_check(pts, base=None):
    """with a measured zero-exposure baseline (round 3b): (signal - base)/(VMAX-8) must be constant within 6 % or 1 DN;
    without one, the old line fit (kept for re-checking stored data)."""
    if base is not None and len(pts) == 3:
        k = [(p[1] * (p[0] - 8) - base) / (p[0] - 8) for p in pts]
        sig = [p[1] * (p[0] - 8) - base for p in pts]
        dev = max(k) - min(k)
        ok = min(k) > 0 and (dev / max(k) < 0.06 or dev * (pts[0][0] - 8) < 1.0)
        return dict(points=pts, base=base, k=k, signal=sig, PASS=bool(ok))
    return lin_fit(pts)


def lin_fit(pts):
    """signal = a + b*(VMAX-8): a constant image-vs-OB black offset (fast/2x2 classes, amplified by the gain) makes
    signal/(VMAX-8) drift with VMAX although the exposure is linear (round 3). Fit a line through the 3 points
    (signal = ratio*(VMAX-8)) and require the residual < 2 % of the signal span and a positive slope."""
    if len(pts) != 3:
        return dict(points=pts, PASS=False)
    x = np.array([p[0] - 8 for p in pts], float); y = np.array([p[1] * (p[0] - 8) for p in pts], float)
    b, a = np.polyfit(x, y, 1)
    resid = float(np.max(np.abs(a + b * x - y)))
    span = float(y.max() - y.min()) or 1.0
    return dict(points=pts, slope=float(b), offset=float(a), resid_rel=resid / span, resid=resid,
                PASS=bool(b > 0 and (resid / span < 0.02 or resid < 1.0)))   # < 1 DN: low-signal configs (short frames, dim room)


def sweep_set():
    """many geometries per readout: crop heights / widths spread over the sensor"""
    out = []
    for key in ('12', '14', '12fast', '2x2', '2x2fast', '3x3', '3x3fast'):
        r = C.BY_KEY[key]
        m = r['mh']
        for ch in (4000, 3240, 2160, 1600, 1080, 720, 480, 240):
            for cw in (6048, 4800, 3840, 2400, 1920):
                if key == '12fast' and cw > C.max_width(r):
                    continue
                ow = (cw // m) // 16 * 16
                oh = (ch // r['mv']) // 2 * 2
                if ow < 256 or oh < 120:
                    continue
                try:
                    C.plan(key, cw, ch, ow, oh)
                except ValueError:
                    continue
                out.append((key, (cw, ch), (ow, oh)))
    return out


def fps_set():
    """common frame rates (VMAX above the minimum, the sweep ran everything at max fps): every readout x 3 crop heights
    x 23.976/29.97/59.94/119.88 where the plan allows it"""
    out = []
    for key in ('12', '14', '12fast', '12fastW', '2x2', '2x2fast', '3x3', '3x3fast', '3x6', '3x6fast'):
        r = C.BY_KEY[key]
        cw = C.max_width(r) if key == '12fast' else 6048     # 12fast: 4160, the line's real width (§72)
        hs = (4040,) if r['centre'] is None else (3408, 2160, 1080)
        for ch in hs:
            ow = (cw // r['mh']) // 16 * 16
            oh = (ch // r['mv']) // 2 * 2
            for fps in (23.976, 29.97, 59.94, 119.88):
                try:
                    C.plan(key, cw, ch, ow, oh, fps)
                except ValueError:
                    continue
                out.append((key, (cw, ch), (ow, oh), fps))
    return out


def matrix_set():
    """matrix classes (readout_cfg new=True, §67): full height at full width + two receiver crops, two vertical windows
    (3408 / 2160 sensor rows), all at max fps; full frame at 23.976 / 29.97 / 59.94 where the plan allows it"""
    out = []
    for r in C.READOUTS:
        if not (r.get('new') or r.get('exp')):       # + width presets (user 2026-10-23: the whole matrix)
            continue
        w = C.max_width(r)                          # 1x1 short lines: the real width (§72); merged: as before
        cw_full = max(r['fmt']) * r['mh'] if r['mh'] > 1 else w
        for frac in (1.0, 0.75, 0.5):
            # narrower crops stay where they were (they never reached the short line's end, full_v1 passed them)
            cw = int((cw_full if frac == 1.0 else max(r['fmt']) * r['mh']) * frac) // (12 * r['mh']) * (12 * r['mh'])
            ow = (cw // r['mh']) // 16 * 16
            oh = C.full_rows(r['key'])
            out.append((r['key'], (cw, 4040), (ow, oh), None))
        for ch in (3408, 2160):                     # vertical windows (§64 rule; not yet measured for these classes)
            ow = (cw_full // r['mh']) // 16 * 16
            try:
                C.plan(r['key'], cw_full, ch, ow, int(ch / r['mv']) // 2 * 2)
            except ValueError:
                continue
            out.append((r['key'], (cw_full, ch), (ow, int(ch / r['mv']) // 2 * 2), None))
        for fps in (23.976, 29.97, 59.94):
            ow = (cw_full // r['mh']) // 16 * 16
            try:
                C.plan(r['key'], cw_full, 4040, ow, C.full_rows(r['key']), fps)
            except ValueError:
                continue
            out.append((r['key'], (cw_full, 4040), (ow, C.full_rows(r['key'])), fps))
    return out


def full_set():
    """the complete pass (user 2026-10-23: rerun everything, then rebuild the page from it): matrix_set's shapes for
    EVERY class (full height at 3 widths, 3408 / 2160 windows, 23.976 / 29.97 / 59.94), plus CORE and fps_set, one per id"""
    saved = [(r, r.get('exp')) for r in C.READOUTS]
    try:
        for r, _ in saved:
            r['exp'] = True
        cfgs = matrix_set()
    finally:
        for r, e in saved:
            if e is None:
                r.pop('exp', None)
            else:
                r['exp'] = e
    seen, out = set(), []
    for c in cfgs + [x if len(x) == 4 else (*x, None) for x in list(CORE) + fps_set()]:
        try:
            pid = C.plan(c[0], *c[1], *c[2], c[3])['id']
        except ValueError:                           # a class the generator now refuses (e.g. h3, §72)
            continue
        if pid not in seen:
            seen.add(pid); out.append(c)
    return out


def all_set():
    """every validator set at today's plan (user 2026-10-23: the complete pass includes the earlier tests): full_set +
    the 254-point crop sweep + stockfull + fmtexp, one per id. Ids from older plans (e.g. full height 2020 before §64
    made it 2014) are superseded, not rerun."""
    extra = sweep_set() + stockfull_set() + [(r['key'], (max(r['fmt']) * r['mh'] if r['mh'] > 1 else C.max_width(r), 4040), (C.max_width(r), C.full_rows(r['key'])), None)
                                             for r in C.EXPERIMENTAL]
    seen, out = set(), []
    for c in full_set() + [x if len(x) == 4 else (*x, None) for x in extra]:
        pid = C.plan(c[0], *c[1], *c[2], c[3])['id']
        if pid not in seen:
            seen.add(pid); out.append(c)
    return out


def reshoot_set(out):
    """representative frames for the simulator page (user 2026-10-23: the passing configs' frames had been deleted):
    every class at full width x full height, plus the 3408 / 2160 windows where the plan allows; configs that already
    kept a preview.jpg are left out. Run with --force (they passed before)."""
    res = []
    for r in C.READOUTS:
        ow = C.max_width(r); cw = max(r['fmt']) * r['mh'] if r['mh'] > 1 else ow
        cand = [((cw, 4040), (ow, C.full_rows(r['key'])))]
        cand += [((cw, ch), (ow, int(ch / r['mv']) // 2 * 2)) for ch in (3408, 2160)]
        for crop, outsz in cand:
            try:
                pid = C.plan(r['key'], *crop, *outsz)['id']
            except ValueError:
                continue
            if not (out / pid.replace(':', '_').replace('>', '_') / 'preview.jpg').exists():
                res.append((r['key'], crop, outsz, None))
    return res


def stockfull_set():
    """stock binned classes at their measured full height (round 14: 2x2 2014, 3x3 1344, 3x6 672), full width, at max fps
    and 29.97 / 59.94 where the plan allows it"""
    out = []
    for key in ('2x2', '2x2fast', '3x3', '3x3fast', '3x6', '3x6fast'):
        r = C.BY_KEY[key]; w = max(r['fmt'])
        cw = w * r['mh']
        for fps in (None, 29.97, 59.94):
            try:
                C.plan(key, cw, 4040, w // 16 * 16, C.full_rows(key), fps)
            except ValueError:
                continue
            out.append((key, (cw, 4040), (w // 16 * 16, C.full_rows(key)), fps))
    return out


def run_one(key, crop, outsz, base_out, dark, fps=None):
    import bufa_probe as B, resweep as R, vmode, hsburst
    import fastsweep as F
    F.cached_assemble()                     # callfn re-ran clang on every firmware call: 2.7 s a config (10-23 profile)
    p = C.plan(key, *crop, *outsz, fps)
    a, rows, how = smc.create(p)
    rows = {t: bytes(v) for t, v in rows.items()}
    rows['R10'] = struct.pack('<II', R10[a['cls']], 10)
    d = base_out / p['id'].replace(':', '_').replace('>', '_')
    d.mkdir(parents=True, exist_ok=True)
    res = dict(id=p['id'], attrs=a, checks={})
    vmode.KEEP_WINDOW = True
    b = R.Base(d, 'V2' if p['bits'] == 14 else 'V1', rows=rows)
    s = b.s; s.pair = True
    import fastsweep as F

    def trip(timeout=1.0):                  # >400 fps: the DMA rewrites the tail before a verified write reads back
        for i in range(4):
            B.wr(s.tail + 4 * i, F.SENT, verify=False)
        t0 = time.time()
        while time.time() - t0 < timeout:
            if B.P().mem_get(s.tail)[0] != F.SENT:
                return True
        return False
    s._trip = trip
    st = B.bus_state()
    top = a['y0']
    OBE = max(top - 4 - p.get('y_skip', 0), 6)      # OB rows end: V3-window margin rows are image, not OB (§76)
    try:
        ln = min(B.P().mem_get(0x301005D8)[0] for _ in range(3))
        res['checks']['switch_lines'] = dict(measured=ln, planned=p['receiver_lines'], PASS=abs(ln - p['receiver_lines']) <= 8)
        def counts():
            for line in B.P().sh('imager mode_now').splitlines():
                if line.startswith('frame_count'):
                    return [int(x.split(':')[1]) for x in line.split(',')]
        c0 = counts(); time.sleep(0.5); c1 = counts()      # display transfers run at ~30/s: >5 in 0.5 s
        def settle(n=4, floor=0.1, cap=2.0):
            """wait until the sensor has started n more frames (a gain / SHS / VMAX change lands within 2), instead of
            a fixed 0.3-0.4 s: short at high fps, still enough at long VMAX"""
            t0 = time.time(); f0 = counts()[0]
            time.sleep(floor)
            while counts()[0] - f0 < n and time.time() - t0 < cap:
                time.sleep(0.01)
        res['checks']['live_view'] = dict(frames=c1[0] - c0[0], transfers=c1[1] - c0[1], PASS=(c1[1] - c0[1]) > 5)
        settle(8)                                   # full_v1: tried for 14v3's 12-14 dark top rows in f/ -- not the cause
                                                    # (still there after 8 frames, absent in gainprobe/ at SHS 4): suspect AE's SHS
        ok = s.grab(d / 'f')
        res['checks']['frame'] = dict(PASS=bool(ok))   # smc_m1: 10 configs never completed a frame and still "passed"
        if ok and p['bits'] == 14:
            m = json.loads((d / 'f' / 'frame.json').read_text()); m['bits'] = 14; (d / 'f' / 'frame.json').write_text(json.dumps(m))
        if ok:
            fr, m = R.decode(d / 'f')
            img = fr[0][top + 2:top + p['out_h'] - 2, 16:-16]; ob = fr[0][4:OBE, 16:-16]
            try:                                    # small JPEG kept after the raw frames are deleted (simulator page)
                import preview
                preview.make(fr[0], top, p['out_h'], p['crop'][0] / p['crop'][1], d / ('preview_dark.jpg' if dark else 'preview.jpg'), ob=ob)
            except Exception:                       # noqa: BLE001 -- a preview never fails a config
                pass
            if not dark:                            # matrix classes: y0 was measured with 0018 (dark rows) on, which the
                rs_ = fr[0][:, 16:-16].std(1)      # REG table cannot carry. Texture, not level (h3 had a dark scene
                thr = 2 * float(np.median(rs_[1:6])) + 3.0   # top); and the first COMPLETE row pair: in f12v2 row 18 was
                lit = next((r for r in range(2, len(rs_) - 1) if rs_[r] > thr and rs_[r + 1] > thr), -1)  # lit, 19 dark
                lit += lit % 2
                # a dark scene top looks exactly like the dark rows (f12v3 windows: rows 20-33 at black, std 2), so a
                # later first textured pair is only a warning; an image starting BEFORE y0 (rows lost) is a failure
                # 12v3 / 12h2v3 (normal AD): rows 18-19 are a complete pair in some runs and not in others (same
                # config) -- y0 = 20 skips that unstable pair, so first_pair = y0 - 2 is expected, not a failure
                res['checks']['top'] = dict(first_pair=lit, y0=top, warn=bool(lit > top),
                                            PASS=(lit >= top - 2 - p.get('y_skip', 0)) if p.get('new') else True)   # V3 margin rows are image (§76)
                # rows the sensor did not deliver (round 12/14: planned rows past the readout read 1 or 0) or flat
                # rows (no texture at all) -- the dark rows check only, so a light-only round missed them
                rp_ = img.mean(1); rsd = img.std(1)
                blank = int(((rp_ < ob.mean() - 60) | (rsd < 0.5)).sum())
                res['checks']['rows'] = dict(blank_rows=blank, PASS=blank == 0)
                # columns the sensor did not deliver (full_v1: every width preset at its widest format width ends in 24
                # pad / garbage columns -- w03 "4016" is 3992 real) -- right edge only: a flat scene region at the left
                # looks like pad in a lit frame (colscan_edge.py)
                # unexposed top image rows (§72/§76: new V3 windows lost their first 14 rows now and then): rows whose
                # level above black is < 1/4 of the frame body; not judged on a frame too dark to tell (< 15 DN)
                import v3top
                _d = v3top.dead_rows(fr[0], top, p.get('y_skip', 0))
                res['checks']['top_exposed'] = dict(dead_rows=_d, judged=_d >= 0, PASS=_d <= 0)
                # under-exposed rows ANYWHERE in the output (§76: new-V3 full height had 14 inserted unexposed rows after
                # the first 14 -- top_exposed stops at the first lit row and rows' std < 0.5 test missed them)
                _f0 = fr[0].astype(float); _rm = _f0[:, 16:-16].mean(1) - _f0[4:OBE, 16:-16].mean()
                _img = _rm[top + 2:top + p['out_h'] - 2]; _body = float(np.median(_img))
                _low = int((_img < 0.15 * _body).sum()) if _body >= 15 else -2   # unexposed rows sit at ~0-1 DN; a dark
                                                                                  # scene band (narrow crops) at ~0.5 x body
                res['checks']['bands'] = dict(low_rows=_low, judged=_low >= 0, PASS=_low <= 0)
                import colscan_edge
                _l, _r, _t = colscan_edge.edges(fr[0].astype(float)[top + 2:top + p['out_h'] - 2])
                res['checks']['cols'] = dict(right_pad=_r, left_flat=_l, PASS=_r == 0)
            if dark:
                rowp = img.mean(1); colp = img.mean(0)
                # image - OB black depends on the AD class (stock fast modes: +6..8 DN, others ~0..2; SMC_VERIFY round 1):
                # compare with the stock reference of the same class, not with zero
                ref = BLACK_REF_FAST if p['fast_set'] else BLACK_REF.get(a['cls'], 0.0)   # 1x1 fast is class 17 + fast AD (round 4)
                diff = float(img.mean() - ob.mean())
                res['checks']['black'] = dict(image=float(img.mean()), ob=float(ob.mean()), diff=diff, ref=ref, row_std=float(rowp.std()), col_std=float(colp.std()),
                                              even_odd=float(rowp[0::2].mean() - rowp[1::2].mean()),
                                              PASS=abs(diff - ref) < 3 and rowp.std() < 1.5 and abs(rowp[0::2].mean() - rowp[1::2].mean()) < 1.5)
                # round 4: image-vs-OB offset at forced analog gain codes (light rounds saw ~98 / ~138 DN at high gain);
                # recorded only -- judged against stock modes of the same class measured the same way (smc_stockblack.py)
                B.bus_on(st)
                hg = {}
                for code in (0x400, 3900):
                    B.bus_subs(st, [(0x0005, 4), (0x0006, 0), (0x003D, code & 0xFF), (0x003E, code >> 8), (0x003F, code & 0xFF), (0x0040, code >> 8)])
                    settle()
                    if s.grab(d / f'g{code}'):
                        if p['bits'] == 14:
                            m2 = json.loads((d / f'g{code}' / 'frame.json').read_text()); m2['bits'] = 14
                            (d / f'g{code}' / 'frame.json').write_text(json.dumps(m2))
                        f2, _ = R.decode(d / f'g{code}')
                        hg[code] = float(np.mean([f[top + 2:top + p['out_h'] - 2, 16:-16].mean() - f[4:OBE, 16:-16].mean() for f in f2]))
                B.bus_subs(st, [])
                res['gain_offsets'] = hg
                res['checks']['black_gain'] = black_judge(key, hg, full=(0x0003, 1) not in p['sensor'])
                res['checks']['rows'] = rows_ok(img, float(ob.mean()))
                # the AE-gain check stays for structure only (row/column/even-odd); its level is judged by black_gain
                res['checks']['black']['PASS'] = rowp.std() < 1.5 and abs(rowp[0::2].mean() - rowp[1::2].mean()) < 1.5
            else:
                B.bus_on(st)
                B.P().sh('imager fixed_shutter 1 100')
                v0 = B.P().mem_get(VREG)[0]; vp = (v0 >> 16) + 1

                clipmask = {}

                def sig(dd):
                    if p['bits'] == 14:
                        m2 = json.loads((dd / 'frame.json').read_text()); m2['bits'] = 14; (dd / 'frame.json').write_text(json.dumps(m2))
                    f2, _ = R.decode(dd)                 # both frames of the pair (round 3d: one frame was too noisy at ~10 DN)
                    out_ = []
                    for f in f2:
                        img_ = f[top + 2:top + p['out_h'] - 2, 16:-16]
                        if 'mask' not in clipmask:       # smc_m1 h3: highlights clip at the longest exposure even at the
                            clipmask['mask'] = img_ < 1500   # lowest gain code -> one fixed mask from the first (longest) frame;
                            # 1500 not 3600: a merged h3 value can be far below 4095 while one of its 3 pixels clipped
                        mk = clipmask['mask'][:img_.shape[0], :img_.shape[1]]
                        out_.append(img_[mk[:img_.shape[0]]].mean() - f[4:OBE, 16:-16].mean())
                    return float(np.mean(out_))
                # adaptive gain (round 3: a dimmed room left ~7 DN of signal and the 6 % test failed on noise):
                # raise the analog gain code until the full-frame signal is >= ~120 DN, or the code tops out
                code = 0x400
                # h3 turns convex above code ~3700 while 1x1 stays linear (SMC_VERIFY round 16: k 52 -> 77 -> 87 at
                # 3711 / 3900, linear at 1024, passes at ~3300) -- full_v1 (dim room) pushed every h3 config to 3900
                cap = 3300 if key in ('12h3', 'f12h3') else 3900
                for _ in range(4):
                    B.bus_subs(st, [(0x0005, 4), (0x0006, 0), (0x003D, code & 0xFF), (0x003E, code >> 8), (0x003F, code & 0xFF), (0x0040, code >> 8)])
                    settle()
                    if not s.grab(d / 'gainprobe'):
                        break
                    sg = sig(d / 'gainprobe')
                    if sg >= 120 or code >= cap:
                        break
                    g = 4095 / (4095 - code) * min(8.0, 160 / max(sg, 2))
                    code = min(cap, int(4095 - 4095 / g))
                res['gain_code'] = code
                clipmask.clear()                         # the mask comes from the first VMAX point (the longest exposure)
                pts = []
                # VMAX at exposures of n, n+1, n+2 lamp periods (120 Hz): a dimmed (PWM) room flickers and short
                # exposures then wander by ~1 DN (round 3c); whole periods average the flicker out (IMX410_RULES §55)
                hw = B.P().mem_get(0x30100004)[0]; hm = min(hw & 0x3FFF, (hw >> 16) & 0x3FFF) + 1
                per = 72e6 / hm / FLICKER_HZ
                n0 = max(1, int(np.ceil((vp - 8) / per)))
                vms = [int(np.ceil(n * per)) + 8 for n in (n0 + 2, n0 + 1, n0)]
                for vm in vms:
                    B.wr(VREG, ((vm - 1) << 16) | (v0 & 0xFFFF)); settle()
                    if s.grab(d / f'v{vm}'):
                        pts.append((vm, sig(d / f'v{vm}') / (vm - 8)))
                # zero-exposure baseline: SHS just below VMAX/2 (exposure ~4 lines) -> the image-vs-OB offset itself
                vb_ = vms[-1]
                B.wr(VREG, ((vb_ - 1) << 16) | (v0 & 0xFFFF))
                shs0 = vb_ // 2 - 2
                B.bus_subs(st, [(0x0005, shs0 & 0xFF), (0x0006, shs0 >> 8), (0x003D, code & 0xFF), (0x003E, code >> 8), (0x003F, code & 0xFF), (0x0040, code >> 8)])
                settle()
                b1 = sig(d / 'base') if s.grab(d / 'base') else None
                b2 = sig(d / 'base2') if s.grab(d / 'base2') else None
                base = None if b1 is None or b2 is None else (b1 + b2) / 2
                res['checks']['linearity'] = lin_check(pts, base)
                # Bayer phase (round 4: an even window start mixed the colours or swapped the row phase and every other
                # check still passed): every stock mode reads [R/B, G, G, B/R] -- the two greens equal and the brightest
                fb, _ = R.decode(d / f'v{vms[0]}')
                fb = fb[0].astype(float)[top + 10:top + p['out_h'] - 10, 32:-32]
                ph = [float(fb[i::2, j::2].mean()) for i in (0, 1) for j in (0, 1)]
                g = (ph[1] + ph[2]) / 2
                res['checks']['bayer'] = dict(phases=ph, PASS=abs(ph[1] - ph[2]) < 0.02 * g and g > max(ph[0], ph[3]) + 0.05 * g)
                # full_v1: 12h3 / f12h3 had R and B at black (R/G 0.0-0.26 vs 0.59 on 1x1) and passed the check above -- an
                # all-green frame satisfies "greens equal and brightest". A real scene has R and B well above zero.
                _b = float(ob.mean())                    # ph is raw (black included); compare above black
                _g, _r, _bl = g - _b, ph[0] - _b, ph[3] - _b
                res['checks']['colour'] = dict(rg=_r / _g if _g > 0 else None, bg=_bl / _g if _g > 0 else None,
                                               PASS=bool(_g < 5 or min(_r, _bl) > 0.3 * _g))   # < 5 DN: too dark to judge
                # row phase (Julien Acquaviva, sigma-fp-raw: OG3K/M98 G2 rows 0.5 px off): even vertical bins put the
                # second row of each pair 1 sensor row off -- must equal the stock value for the class (§65)
                import rowphase
                res['checks']['rowphase'] = rowphase.judge(fb, C.BY_KEY[key]['mv'])
                B.bus_subs(st, []); B.P().sh('imager fixed_shutter 0'); B.wr(VREG, v0)
        meta, raws = hsburst.burst(s, n=8, enum=1 if p['bits'] == 14 else 0, store=False)   # timing only
        dt = np.diff([e[0] for e in meta['ents']])[1:]
        law = np.median(dt)
        res['checks']['burst'] = dict(median_us=float(law), drops=int((dt > 1.5 * law).sum()), PASS=int((dt > 1.5 * law).sum()) == 0)
    finally:
        try:
            B.bus_subs(st, []); B.P().sh('imager fixed_shutter 0')
        finally:
            b.close()
    res['PASS'] = all(c['PASS'] for c in res['checks'].values())
    (d / 'result.json').write_text(json.dumps(res, indent=1, default=float))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out'); ap.add_argument('--set', default='core'); ap.add_argument('--dark', action='store_true')
    ap.add_argument('--only', default='')
    ap.add_argument('--any-settings', action='store_true', help=f'run even if ISO / shutter differ from {CAMERA}')
    ap.add_argument('--db', default=str(DB))           # a fresh pass keeps its own results (full_v1)
    ap.add_argument('--fresh', action='store_true'); ap.add_argument('--force', action='store_true')   # poff before every config (matrix r2: wedges at configs 3 and 7)
    a = ap.parse_args()
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    cfgs = {'core': CORE, 'sweep': sweep_set, 'fps': fps_set, 'matrix': matrix_set,
            'stockfull': stockfull_set,
            'fmtexp': lambda: [(r['key'], (max(r['fmt']) * r['mh'] if r['mh'] > 1 else C.max_width(r), 4040), (C.max_width(r), C.full_rows(r['key'])), None) for r in C.EXPERIMENTAL],
            'reshoot': lambda: reshoot_set(pathlib.Path(a.out)), 'full': full_set, 'all': all_set,
            'matrixfull': lambda: [c for c in matrix_set() if c[1][1] == 4040 and c[3] is None and c[2][0] >= (max(C.BY_KEY[c[0]]['fmt']) // 16 * 16) - 16]}[a.set]
    cfgs = cfgs() if callable(cfgs) else cfgs
    cfgs = [c if len(c) == 4 else (*c, None) for c in cfgs]
    if a.only:
        cfgs = [c for c in cfgs if c[0] in a.only.split(',')]
    dbp = pathlib.Path(a.db)
    db = json.loads(dbp.read_text()) if dbp.exists() else {}
    tag = 'dark' if a.dark else 'light'
    print(f'{len(cfgs)} configs ({tag})', flush=True)

    got = camera_settings()
    print('  camera', got, flush=True)
    if got != CAMERA and not a.any_settings:
        print(f'camera settings {got} != {CAMERA}: set them on the camera (or --any-settings) -- not running', flush=True)
        return
    with open(out / 'settings.jsonl', 'a') as fh:      # beside thermal.jsonl; the db stays id -> results only
        fh.write(json.dumps(dict(t=time.strftime('%Y-%m-%d %H:%M'), tag=tag, **got)) + '\n')

    def focus():                                    # user rule: AF after every (re)boot and at the start of a run
        if __import__('os').environ.get('SMC_NOFOCUS'):  # 2026-10-25: in the dim room AF threw a hand-set focus off --
            print('  AF skipped (SMC_NOFOCUS)', flush=True)   # keep the user's manual focus
            return
        subprocess.run([sys.executable, 'bufa_probe.py', 'focus', '--hold', '3.0'], cwd=HERE, capture_output=True, timeout=90)
    focus()
    for key, crop, outsz, fps in cfgs:
        if (out / 'STOP').exists():
            print('STOP file: stopping cleanly after the last config', flush=True); break
        pid = C.plan(key, *crop, *outsz, fps)['id']
        if db.get(pid, {}).get(tag, {}).get('PASS') and not a.force:
            continue
        chk = subprocess.run([sys.executable, '-c', 'import vmode, bufa_probe as B; vmode.check_stock(); print("HEAP", B.P().sh("memmgr heapmem").strip())'],
                             cwd=HERE, capture_output=True, text=True, timeout=120)
        hl = next((l for l in chk.stdout.splitlines() if l.startswith('HEAP')), '')
        if hl:
            print('  ' + hl, flush=True)                # round 5: the shell died after 55-90 configs twice -- watch for a leak
        if chk.returncode or a.fresh:
            print('  not stock -> fastreboot' if chk.returncode else '  fresh boot', flush=True)
            rb = subprocess.run([sys.executable, '-c', 'import sweep; sweep.KEEP=None; sweep.fastreboot()'], cwd=HERE,
                                capture_output=True, timeout=300)
            if rb.returncode:                       # round 4: a failed restart used to fall through and fail every later config
                print('camera did not come back -- stopping (needs a manual reboot)', flush=True); break
            focus()
        try:                                           # sensor temperature before every config (user 10-23: runs hot)
            import thermal
            _t = thermal.wait_cool(); thermal.log(out / 'thermal.jsonl', pid)
            print(f"  temp {_t.get('C')}", flush=True)
        except Exception as _e:                        # noqa: BLE001
            print('  temp read failed', _e, flush=True)
        r = subprocess.run([sys.executable, '-u', '-c',
                            f'import json,pathlib,smc_validate as V; print("RES", json.dumps(V.run_one({key!r}, {crop!r}, {outsz!r}, pathlib.Path({str(out)!r}), {a.dark!r}, {fps!r}), default=float))'],
                           cwd=HERE, capture_output=True, text=True, timeout=600)
        line = next((l for l in r.stdout.splitlines() if l.startswith('RES ')), None)
        if line:
            res = json.loads(line[4:])
            db.setdefault(pid, {})[tag] = res
            fails = [k for k, c in res['checks'].items() if not c['PASS']]
            # user 2026-10-23: test data is kept, compressed. A config writes ~260 MB of raw frames (14 grabs); zstd -9
            # keeps ~65 % (0.3 s / 18 MB), so all of it for 647 x 2 configs would be ~220 GB. Kept: the main pair f/ of
            # every config, every frame of a failing config, and all metadata (frame.json, summary.npz, result.json,
            # previews); the gain / VMAX series of passing configs keep their summary.npz only.
            sfx = '_dark' if a.dark else ''
            for f in (out / pid.replace(':', '_').replace('>', '_')).rglob('frame*.raw'):
                if f.parent.name == 'f' or not res['PASS']:
                    z = f.with_name(f.stem + sfx + '.raw.zst')
                    if subprocess.run(['zstd', '-q', '-9', '-T4', '-f', str(f), '-o', str(z)]).returncode == 0:
                        f.unlink()
                else:
                    f.unlink()
            print(f"{'PASS' if res['PASS'] else 'FAIL'} {pid}  " + ' '.join(f"{k}={'ok' if c['PASS'] else json.dumps({x: y for x, y in c.items() if x not in ('PASS', 'points')}, default=float)[:120]}" for k, c in res['checks'].items()), flush=True)
            if res.get('gain_offsets'):
                print('   gain offsets', {k: round(v, 1) for k, v in res['gain_offsets'].items()}, flush=True)
        else:
            (out / f"{pid.replace(':', '_').replace('>', '_')}.stderr").write_text(r.stdout + '\n----\n' + r.stderr)   # full trace for the post-mortem
            db.setdefault(pid, {})[tag] = dict(PASS=False, error=(r.stderr.strip().splitlines() or ['?'])[-1][:200])
            print(f'ERROR {pid}: {db[pid][tag]["error"]}', flush=True)
        dbp.write_text(json.dumps(db, indent=1, default=float))


if __name__ == '__main__':
    main()
