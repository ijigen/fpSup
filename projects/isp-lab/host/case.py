#!/usr/bin/env python3
"""One ISP custom case -> case.json + checkpoint pictures, for the page (site/build_page.py).

    case.py validation/RUN          reads RUN/applied.json (isp_custom plan, optional) and RUN/push/ (push_rx)

Checkpoints (notes/IMX410_LAB_SPEC.md §2): standby LV = the last LV before REC, focus LV = an LV pushed with the
half-press flag (none yet: the take presses AF before the sampler starts), recording LV = the middle one with the
REC flag, CDNG = the last DNG pushed after the stop (green channel, black-subtracted, gamma 2.2 for viewing only).
Each gets RUN/shots/<name>.jpg (<= 960 px wide) and RUN/shots/full/<name>.jpg. The verdict compares the formula's
prediction (rec, act) with the DNG's ImageWidth/Length and DefaultCropSize. Originals stay untouched:
archive them with archive_validation.py pack.
"""
import json, pathlib, struct, sys

import numpy as np
import aspect
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'sup'))
import ispl_records as R                            # noqa: E402  (the report pushes)
from PIL import Image

PREVIEW_W = 960


def yuyv_rgb(raw, w, h):
    """The LV ring is Y Cr Y Cb (YVYU): read as Y Cb Y Cr an orange cat came out blue (user, LCD, 10-27)."""
    b = np.frombuffer(raw, np.uint8)[:w * h * 2].reshape(h, w * 2)
    y = b[:, 0::2].astype(float)
    v = np.repeat(b[:, 1::4].astype(float), 2, 1) - 128
    u = np.repeat(b[:, 3::4].astype(float), 2, 1) - 128
    rgb = np.dstack([y + 1.5748 * v, y - 0.1873 * u - 0.4681 * v, y + 1.8556 * u])
    return np.clip(rgb, 0, 255).astype(np.uint8)


LV_CHROMA_TOL = 4.0      # recording LV mean Cb / Cr vs the same take's standby LV (stock mode, same scene): stock < 1
LV_Y_RANGE = (16, 235)   # mean Y of a real picture; the bad-R10 V41 recording LV was 244 (all white)
LV_Y_STD_MIN = 4.0
ASPECT_TOL = 0.03        # LV content aspect vs the DNG's physical aspect (stock FHD60: 1.778 for 1.776)


def lv_stats(raw, w, h):
    """(mean Y, std Y, mean Cb, mean Cr) of a YVYU frame."""
    b = np.frombuffer(raw, np.uint8)[:w * h * 2]
    y = b[0::2].astype(float)
    return float(y.mean()), float(y.std()), float(b[3::4].mean()), float(b[1::4].mean())


def dng_tags(b):
    ifd, = struct.unpack_from('<I', b, 4)
    n, = struct.unpack_from('<H', b, ifd)
    t = {}
    for i in range(n):
        tag, typ, cnt, val = struct.unpack_from('<HHII', b, ifd + 2 + 12 * i)
        t[tag] = (typ, cnt, val)
    return t


def pair(b, t, tag):
    """A 2-value SHORT/LONG/RATIONAL tag as two numbers."""
    if tag not in t:
        return None
    typ, cnt, val = t[tag]
    if typ == 3:
        return (val & 0xFFFF, val >> 16)
    if typ == 4:
        return tuple(struct.unpack_from('<2I', b, val)) if cnt == 2 else (val,)
    if typ in (5, 10):
        r = struct.unpack_from('<4I' if typ == 5 else '<4i', b, val)
        return (r[0] / r[1], r[2] / r[3])
    return None


def unpack_msb(raw, bits, n):
    """CinemaDNG packing: samples back to back, most significant bit first."""
    if bits == 8:
        return np.frombuffer(raw, np.uint8)[:n].astype(np.uint16)
    if bits == 16:
        return np.frombuffer(raw, '>u2')[:n].astype(np.uint16)
    bitsarr = np.unpackbits(np.frombuffer(raw, np.uint8))[:n * bits].reshape(n, bits).astype(np.uint16)
    return (bitsarr << np.arange(bits - 1, -1, -1, dtype=np.uint16)).sum(axis=1).astype(np.uint16)


def cfa_ok(ph):
    """ph = means at (0,0) (0,1) (1,0) (1,1). RGGB: the greens (0,1)/(1,0) are the matching pair. A RAW one row or
    column off (g1 M117 12fastW, M160 f12v3: greens at (0,0)/(1,1)) is grey-identical, only its colour is wrong."""
    rel = lambda a, b: abs(a - b) / max(1.0, (a + b) / 2)
    return rel(ph[1], ph[2]) < rel(ph[0], ph[3])


def dng_green(b):
    """CinemaDNG -> colour view (half size; green channel = the green plane), the green plane's stats, and the DNG geometry."""
    t = dng_tags(b)
    w, h, bps = t[256][2], t[257][2], t[258][2] & 0xFFFF
    off = t[273][2]
    if bps not in (8, 10, 12, 14, 16) or (t[259][2] & 0xFFFF) != 1:
        return None, {'w': w, 'h': h, 'bits': bps, 'compression': t[259][2] & 0xFFFF}
    px = unpack_msb(b[off:off + w * h * bps // 8], bps, w * h)
    full = px.reshape(h, w)
    g = full[0::2, 1::2].astype(float)
    # the four CFA phases' means (the DNG says RGGB): the two greens match each other better than R and B do
    ph = [float(full[y::2, x::2].mean()) for y in (0, 1) for x in (0, 1)]
    if bps != 12:                       # view and stats on the 12-bit scale, so every depth reads alike
        g = g * (1 << 12) / (1 << bps)
    geo = {'w': w, 'h': h, 'bits': bps, 'crop_origin': pair(b, t, 0xC61F), 'crop_size': pair(b, t, 0xC620),
           'g_median': float(np.median(g)), 'g_p999': float(np.percentile(g, 99.9)),
           'cfa_means': [round(v, 1) for v in ph], 'cfa_ok': cfa_ok(ph)}
    # the view in colour (half size, one pixel per RGGB quad, white balanced by AsShotNeutral): a CFA phase error is a
    # colour error only. Its green channel is the old grey view exactly, so the fov checks read the same numbers.
    k = (1 << 12) / (1 << bps)
    r, b2 = full[0::2, 0::2] * k, full[1::2, 1::2] * k
    wb = neutral(b, t)
    span = max(1.0, np.percentile(g, 99.5) - 250)
    view = np.stack([np.clip((c - 250) * gain / span, 0, 1) for c, gain in
                     ((r, wb[1] / wb[0]), (g, 1.0), (b2, wb[1] / wb[2]))], axis=-1) ** (1 / 2.2) * 255
    return view.astype(np.uint8), geo


WB_FALLBACK = (0.5, 1.0, 0.6)     # roughly daylight, only when a DNG has no AsShotNeutral


def neutral(b, t):
    """AsShotNeutral (0xC628, 3 RATIONAL) as (r, g, b)."""
    if 0xC628 not in t or t[0xC628][0] != 5 or t[0xC628][1] != 3:
        return WB_FALLBACK
    v = struct.unpack_from('<6I', b, t[0xC628][2])
    n = tuple(v[i] / v[i + 1] for i in (0, 2, 4) if v[i + 1])
    return n if len(n) == 3 and min(n) > 0 else WB_FALLBACK


FPS_TOL = 0.001                   # measured sensor fps vs the formula's (TEST_PLAN_V2 §4.2)


def frame_clock(push, rows):
    """The last report's sensor frame clock (ISPL layout 9: a TickTimer stamp on every Vd while REC):
    fps, frames, shortest/longest period in us; None before layout 9 or with under two frames."""
    reps = [r for r in rows if r['source'] == 'report']
    if not reps:
        return None
    raw = (push / reps[-1]['file']).read_bytes()
    try:
        c = R.parse_cap(raw)
    except Exception:
        return None
    if c.get('version') != 9 or c.get('fc_frames', 0) < 2 or c['fc_t_last'] == c['fc_t_first']:
        return None
    span = (c['fc_t_last'] - c['fc_t_first']) & 0xFFFFFFFF
    return {'fps': round((c['fc_frames'] - 1) * 1e6 / span, 4), 'frames': c['fc_frames'],
            'gap_min_us': c['fc_gap_min'], 'gap_max_us': c['fc_gap_max']}


STANDBY_SKIP = 1 | 2 | 4 | 8 | 16     # REC, focus, magnify, burst, starting (ix_wr.h IX_LV_F_*)
FOV_MIN = 0.6                     # correlation of the CDNG with the full-field standby LV, both at 64x36


def fov_match(cdng_view, standby_rgb):
    """Does the DNG show the whole field the standby LV shows? Both to 64x36 grey, Pearson r.
    A record path that crops instead of scaling (E1, 10-27) gives the right size and a wrong picture."""
    a = np.asarray(Image.fromarray(cdng_view[..., 1]).resize((64, 36)), float).ravel()
    b = np.asarray(Image.fromarray(standby_rgb).convert('L').resize((64, 36)), float).ravel()
    if a.std() == 0 or b.std() == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


FOV_SCALE_TOL = 0.02              # the DNG's field of view against the LV's, after registration; the LV shows act, not
                                  # the 16 px record margin, as stock does (user 10-28 chose stock): 336 wide is 0.952
REG_R_MIN = 0.85                  # a registration is only a match above this: passes are >= 0.93; the H-only-zoom record
                                  # night1 z2048x1024 (recording LV seamed and repeated) registered at 0.54 and passed (user 10-27)
REC_LV_TOL = 0.02                 # recording LV vs the DNG = act / rec (the LV drops the 16 px margin): stock 1936 wide
                                  # 0.985 for 0.983; 336 wide 0.935 for 0.952 (mx1 S16); E1 cropping it 0.945 for 0.977


def _centre(img, s, W, H):
    w, h = img.size
    cw, ch = w / s, h / s
    return np.asarray(img.crop(((w - cw) / 2, (h - ch) / 2, (w + cw) / 2, (h + ch) / 2)).resize((W, H)), float)


def fov_scale(cdng_view, lv_rgb):
    """Best centred scale between the DNG and the LV, both ways: >1 = the LV shows more than the DNG.
    Correlation alone missed an 8 % wider DNG on the crop routes (10-27 night3 FHD60CROP z2048: r 0.86)."""
    a = Image.fromarray(cdng_view[..., 1])            # the green channel = the grey view these were tuned on
    b = Image.fromarray(lv_rgb).convert('L')
    W, H = 192, 108
    best = (-2.0, 1.0)
    for s in np.arange(0.80, 1.2501, 0.005):
        A, B = (_centre(a, 1, W, H), _centre(b, s, W, H)) if s >= 1 else (_centre(a, 1 / s, W, H), _centre(b, 1, W, H))
        if A.std() == 0 or B.std() == 0:
            continue
        r = float(np.corrcoef(A.ravel(), B.ravel())[0, 1])
        if r > best[0]:
            best = (r, float(s))
    return round(best[1], 3), round(best[0], 3)


def save(img, run, name):
    shots = run / 'shots'
    (shots / 'full').mkdir(parents=True, exist_ok=True)
    im = Image.fromarray(img)
    im.save(shots / 'full' / f'{name}.jpg', quality=90)
    if im.width > PREVIEW_W:
        im = im.resize((PREVIEW_W, round(im.height * PREVIEW_W / im.width)))
    im.save(shots / f'{name}.jpg', quality=85)
    return f'shots/{name}.jpg'


def build(run):
    run = pathlib.Path(run)
    push = run / 'push'
    rows = [json.loads(l) for l in (push / 'index.jsonl').read_text().splitlines() if l.strip()]
    lv = [r for r in rows if r['source'] == 'lv']
    rec = [r for r in lv if r['flags'] & 1]
    focus = [r for r in lv if r['flags'] & 2]
    mag = [r for r in lv if r['flags'] & 4]
    # ISPL v8.1 flags 16 (between our MOVON and recstate +6) and 8 (burst): the REC transition, not the standby LV.
    # Counting them as standby picked the first frame after REC was pressed (10-28: RWZM H 1:1 cases showed the top
    # third x3 there -- every 'stretched standby' fail since p5 -- while the LCD and the real standby were right)
    before = [r for r in lv if not r['flags'] & STANDBY_SKIP and (not rec or r['t_us'] < rec[0]['t_us'])
              and (not focus or r['t_us'] < focus[0]['t_us'])]
    # a profile written while the LV runs shows only after the LV is rebuilt (half-press / magnify): the standby
    # checkpoint is the standby LV after the magnify, else the one before the focus (10-27 sby: M155 showed M122's crop)
    rebuilt = [r for r in lv if not r['flags'] & STANDBY_SKIP and mag and r['t_us'] > mag[-1]['t_us']
               and (not rec or r['t_us'] < rec[0]['t_us'])]
    before = rebuilt or before
    cd = [r for r in rows if r['source'] == 'cdng']
    clock = frame_clock(push, rows)
    case = {'run': run.name, 'counts': {s: sum(r['source'] == s for r in rows) for s in ('lv', 'cdng', 'report')},
            'checkpoints': {}}
    standby_img = focus_img = rec_img = None
    stats, aspects = {}, {}
    for name, pick in (('standby_lv', before[-1] if before else None), ('focus_lv', focus[-1] if focus else None),
                       ('mag_lv', mag[-1] if mag else None), ('rec_lv', rec[len(rec) // 2] if rec else None)):
        if pick:
            raw = (push / pick['file']).read_bytes()
            img = yuyv_rgb(raw, pick['w'], pick['h'])
            stats[name] = [round(x, 1) for x in lv_stats(raw, pick['w'], pick['h'])]
            asp = aspect.lv_aspect(raw, pick['w'], pick['h'])
            aspects[name] = round(asp[0], 3) if asp else None
            if name == 'standby_lv':
                standby_img = img
            if name == 'focus_lv':
                focus_img = img
            if name == 'rec_lv':
                rec_img = img
            case['checkpoints'][name] = {'shot': save(img, run, name), 'w': pick['w'], 'h': pick['h'], 'y_std_cb_cr': stats[name], 'aspect': aspects[name],
                                         'file': f"push/{pick['file']}"}
        else:
            case['checkpoints'][name] = None
    if cd:
        try:
            view, geo = dng_green((push / cd[-1]['file']).read_bytes())
        except (struct.error, KeyError, ValueError) as e:      # a stale DNG half overwritten by this take (10-27 b3x3-z1100)
            view, geo = None, {'w': 0, 'h': 0, 'broken': f'{type(e).__name__}: {e}'[:120]}
        case['checkpoints']['cdng'] = dict(geo, file=f"push/{cd[-1]['file']}",
                                           shot=save(view, run, 'cdng') if view is not None else None)
        # every pushed frame: its CFA phase (fast readouts put single frames one row off: g1 M117 1 of 3, M133 2 of 3)
        # and its picture (colour views 10-27: tiled and pure-noise frames among passes; noise has all four phases
        # equal and passes the CFA test, so each frame must also show the standby LV's field)
        phases, frame_r, bad = [], [], None
        for r in cd:
            try:
                v, gg = dng_green((push / r['file']).read_bytes())
            except (struct.error, KeyError, ValueError):
                v, gg = None, {}
            phases.append(bool(gg.get('cfa_ok')))
            fr = round(fov_match(v, standby_img), 3) if v is not None and standby_img is not None else None
            frame_r.append(fr)
            if bad is None and v is not None and (not phases[-1] or (fr is not None and fr < FOV_MIN)):
                bad = save(v, run, 'cdng_bad')
        g = case['checkpoints']['cdng']
        g['cfa_frames'], g['cfa_ok'] = phases, bool(phases) and all(phases)
        g['frame_r'], g['bad_shot'] = frame_r, bad
        g['frames_ok'] = bool(frame_r) and all(r is None or r >= FOV_MIN for r in frame_r)
        if view is not None and standby_img is not None:
            case['checkpoints']['cdng']['fov_r'] = round(fov_match(view, standby_img), 3)
        ref = focus_img if focus_img is not None else standby_img       # the focused LV: sharper to register
        if view is not None and ref is not None:
            case['checkpoints']['cdng']['fov_scale'], case['checkpoints']['cdng']['fov_scale_r'] = fov_scale(view, ref)
        if view is not None and rec_img is not None:     # the recording LV shows the recorded area (stock 0.985: its margin)
            case['checkpoints']['cdng']['rec_fov_scale'], case['checkpoints']['cdng']['rec_fov_r'] = fov_scale(view, rec_img)
    else:
        case['checkpoints']['cdng'] = None
    applied = run / 'applied.json'
    if applied.exists():
        p = json.loads(applied.read_text())
        case['experiment'] = {k: p[k] for k in ('experiment', 'route', 'row', 'profile_id', 'want')}
        case['experiment']['name'] = p.get('name')       # matrix.py's readable name (10-27 late), None before
        case['experiment']['fps'] = p.get('fps')
        case['experiment']['words_changed'] = len(p['diffs'])
        want, g = p['want'], case['checkpoints']['cdng']
        if g:
            case['predicted'] = {'rec': list(want['rec']), 'act': list(want['act'])}
            case['measured'] = {'rec': [g['w'], g['h']], 'act': list(g['crop_size']) if g.get('crop_size') else None}
            size_ok = (case['predicted']['rec'] == case['measured']['rec'] and case['measured']['act'] is not None and
                       case['predicted']['act'] == [round(x) for x in case['measured']['act']])
            fov_r = g.get('fov_r')
            bits_ok = g.get('bits') == want.get('bits', 12)   # a row the menu does not record with changes nothing
            fs, rs = g.get('fov_scale'), g.get('rec_fov_scale')
            fsr, rsr = g.get('fov_scale_r') or 0, g.get('rec_fov_r') or 0
            case['checks'] = {'size': size_ok, 'bits': bits_ok, 'fov_r': fov_r, 'fov_scale': fs, 'rec_fov_scale': rs,
                              'fov': fov_r is not None and fov_r >= FOV_MIN and fs is not None and abs(fs - want['act'][0] / want['rec'][0]) <= FOV_SCALE_TOL
                                     and fsr >= REG_R_MIN,
                              'rec_lv': rs is not None and abs(rs - want['act'][0] / want['rec'][0]) <= REC_LV_TOL and rsr >= REG_R_MIN}
            st, rc = stats.get('standby_lv'), stats.get('rec_lv')
            case['checks']['lv_colour'] = bool(st and rc and LV_Y_RANGE[0] <= rc[0] <= LV_Y_RANGE[1] and rc[1] >= LV_Y_STD_MIN
                                               and abs(rc[2] - st[2]) <= LV_CHROMA_TOL and abs(rc[3] - st[3]) <= LV_CHROMA_TOL)
            # distortion (user 10-27: some modes look stretched): the LV's content must have the DNG's physical
            # aspect, standby and recording; every non-16:9 record filled the 16:9 LV (square 1.0 shown 1.78)
            want_asp = aspect.dng_aspect(want)
            case['checks']['aspect_dng'] = round(want_asp, 3)
            case['checks']['aspect'] = all(aspects.get(n) and abs(aspects[n] / want_asp - 1) <= ASPECT_TOL
                                           for n in ('standby_lv', 'rec_lv'))
            case['checks']['cfa'] = bool(g.get('cfa_ok'))
            case['checks']['frames'] = bool(g.get('frames_ok'))
            case['measured']['fps'] = clock
            want_fps = case['experiment'].get('fps')
            # the clock's own fps against the formula; a dropped or doubled Vd breaks the period range as well
            case['checks']['fps'] = None if not (clock and want_fps) else bool(
                abs(clock['fps'] / want_fps - 1) <= FPS_TOL and clock['gap_max_us'] < 1.5e6 / want_fps
                and clock['gap_min_us'] > 0.5e6 / want_fps)
            case['verdict'] = 'pass' if (size_ok and bits_ok and case['checks']['fov'] and case['checks']['rec_lv'] and case['checks']['cfa']
                                         and case['checks']['frames'] and case['checks']['fps'] is not False
                                         and case['checks']['lv_colour'] and case['checks']['aspect']) else 'fail'
    results = run / 'RESULTS.md'
    if results.exists():
        case['results_md'] = results.name
    (run / 'case.json').write_text(json.dumps(case, indent=1, ensure_ascii=False))
    return case


if __name__ == '__main__':
    c = build(sys.argv[1])
    print(json.dumps({k: c.get(k) for k in ('run', 'counts', 'verdict', 'checks', 'predicted', 'measured')},
                     ensure_ascii=False))
