"""Which qualities can record a sensor crop at a RES, and at which frame rates (notes/IMX410_LAB_SPEC.md §2).

    qualities(cw, ch, ow, oh, cap=None) -> [case]      one case per quality: its fastest readout variant
    vmax_range(case) -> (lo, vmin, VMAX_MAX)            every VMAX step lo..VMAX_MAX is fps = fps_at(case, VMAX)
    settings(case, fps) -> (readout plan, isp Spec)     what a case installs at that fps

A quality = sensor merge mh x mv x AD (11 fast / 12 / 14) x CRCT hbin x vbin.  RWZM is derived; the readout's window
width (w18, w2C, w03, w2B, W) is a speed choice the formula makes, not a quality.  A quality that cannot record
exactly ow x oh is not offered (user 10-27: a quality never changes the RES).  matrix.py is candidates() over the
preset DC x RES at the host cap; projects/sensorlab-imx410/core is this in C, bit for bit (test_core.py).

R16 (Bei 10-29: the sensor crops the height first, the ISP crops what the sensor cannot): a readout that cannot window
the DC (3x6 / 3x6fast are full height only; a V3 window whose margin leaves the readable rows) reads the full-height
frame and the TIM keeps the DC's rows, centred (readout_cfg.plan rows=): the ISP raster, the record and the DNG are
the DC's, and RWZM / CRCT take it to the RES as for any case -- a crop, never a scale of the extra rows.  Full height
is the smallest larger crop any such readout accepts: every window refusal grows with the window's height, and a
wider crop never helps (the readout's width is a format choice + the TIM's centred x window).

Visible tolerance (opt-in, tol=; Bei 10-29, notes/VISIBLE_TOLERANCE.md): the UI shows the DNG DefaultCrop, not the
record.  A readout that delivers a little less than the DC (full-height V2 2014 rows for 2020, new V3 1330 for 1346)
records a raster a little SHORTER than the clean RES at the clean RES's pixel pitch -- the RWZM is the one the DC would
need, so a downscaled RES loses field of view as rows, never as a stretch -- and qualifies when every axis is at most
`tol` short of the clean raster.  Each case then carries its own `visible` = its raster minus the stock 16 x 10
margin (the RES the UI shows while that recipe is selected) and the case's `nominal` = the clean raster minus the
margin (what the UI remembers and restores; Bei 10-29: no shared minimum).  tol=None: exactly as before.
"""
import pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
IMXL = HERE.parents[1] / 'imx410-lab'
sys.path[:0] = [str(IMXL), str(IMXL / 'offline')]
import readout_cfg as RCF                                            # noqa: E402
import isp_formula as F                                             # noqa: E402

NEAR_UNITY = 1025
WIDEN, SENSOR_W = 16, 6064
QUAL = [(k, 14 if k.startswith('14') else 12) for k in sorted(RCF.BY_KEY)]   # every readout class (40)
BINS = ((1, 1), (1, 3), (3, 1), (3, 3))                             # CRCT bins (R3: with binfilt)


def line_hmax(key, w):
    """R11 / R15: the HMAX readout `key` needs for a w px raster line; None when the readout's floor does."""
    hm = F.min_line_clk(w, RCF.BY_KEY[key]['bits'])                 # R15 for the 14-bit classes
    return hm if hm > RCF.BY_KEY[key]['hmin'] else None


def readout(key, cw, ch, cap=None, rows=None):
    """The plan at the fastest rate: max fps, capped at `cap` (the record route's limit) when one is given.
    p['args'] replay exactly this plan: the cap only when the plan was made with it.  rows: R16's centred row crop
    of a full-height plan (ch = SENSOR_H)."""
    r = RCF.BY_KEY[key]
    sw, sh = cw // r['mh'], ch // r['mv']
    if ch >= RCF.SENSOR_H:                                          # full height: the rows the readout delivers
        sh = min(sh, RCF.full_rows(key))
    if rows is not None:
        sh = rows
    more = [] if rows is None else [0, rows]                        # plan(..., hdr, rows)
    p = RCF.plan(key, cw, ch, sw, sh, None, None, None, *more)
    # R11: no faster line than the ISP keeps up with, on the raster it processes (the isp window, not sw); the
    # raster does not depend on HMAX, so the plan above refuses exactly what the one below would
    hm = line_hmax(key, p['raster_w'])
    if hm:
        p = RCF.plan(key, cw, ch, sw, sh, None, None, hm, *more)
    fps = cap if cap is not None and p['fps_max'] > cap else None
    if fps is not None:
        p = RCF.plan(key, cw, ch, sw, sh, fps, None, hm, *more)
    p['args'] = [key, cw, ch, sw, sh, fps]
    if hm or more:
        p['args'] += [None, hm] + more
    return p


def r16_rows(key, ch, tol=None):
    """R16: the DC's rows on the readout's output grid, even (never more than the DC); None when the full frame
    holds fewer (new V3 at 4032: 1330 rows = 3990 sensor rows) -- the field of view would be less than the DC.
    tol: the whole frame when it is at most tol short of the DC's rows (the record is then short, see candidates)"""
    rows = ch // RCF.BY_KEY[key]['mv'] & ~1
    if tol is not None and rows > RCF.full_rows(key) >= rows * (1 - tol):
        return RCF.full_rows(key)
    return rows if rows <= RCF.full_rows(key) else None


def rows_of(c):
    """the case's R16 row crop, None for a plain plan"""
    a = c['readout']
    return a[9] if len(a) > 9 else None


def _z(src, dst):
    z = src * 1024 // dst
    return 1024 if z < 1024 + 2 else z                              # within 0.2 %: 1:1, the record crops


def isp(p, bits, rw, rh, vbin, hbin=1, nom=None):
    """Each axis on its own (user 10-27: 3x3 is also sensor 1x3 + RWZM 3x1, ...): the sensor merge, the CRCT bin
    and RWZM share the axis' total reduction DC/RES; RWZM takes what the other two leave.
    nom (visible tolerance): the DC on the readout grid; an axis that delivers less keeps the DC's RWZM, and the
    record is as short as the delivery (the most R8 allows, never more than rw x rh).  Only rows come short: the
    readout already refuses a crop wider than its format beyond plan()'s 0.5 % trim, so nom[0] <= W always."""
    W, H = p['raster_w'], p['out_h']
    bw, bh = (W, H) if nom is None else (max(W, nom[0]), max(H, nom[1]))
    zh = _z(bw // hbin, rw) if hbin == 3 or bw > rw else 1024
    zv = _z(bh // vbin, rh) if vbin == 3 or bh > rh else 1024
    if (hbin == 3 or vbin == 3) and zh == zv == 1024:                # R2: a 1:1 record does not bin; 1025 takes
        zh = zv = NEAR_UNITY                                        # branch C (bin4 b3x3-z1025 10-27)
    most_h = (H // vbin) * 1024 // zv if zv > 1024 else H // vbin
    s = F.Spec(window=(W, H), zoom=(zh, zv), scale=tuple(int(x) for x in p['merge'].split('x')), vbin=vbin, hbin=hbin,
               bits=bits, rec=(rw, min(rh, most_h) & ~1))
    return s, F.plan(s)


def short_ok(rec, rw, rh, tol):
    """the visible tolerance: rec no larger than rw x rh and at most tol short of it on each axis"""
    return rec[0] <= rw and rec[1] <= rh and rw - rec[0] <= tol * rw and rh - rec[1] <= tol * rh


def candidates(cw, ch, rw, rh, cap=None, tol=None):
    """Every readout x CRCT bin that records exactly rw x rh from the crop, window variants included, in matrix order.
    tol: also every one whose record is at most tol short of rw x rh per axis (module doc: visible tolerance)."""
    out = []
    for key, bits in QUAL:
        rch, rows = ch, None
        try:
            p = readout(key, cw, ch, cap)
        except ValueError:
            if ch >= RCF.SENSOR_H:
                continue
            # R16: the readout cannot window the DC -> read the full height, the TIM keeps the DC's rows (centred)
            rch, rows = RCF.SENSOR_H, r16_rows(key, ch, tol)
            if rows is None:
                continue
            try:
                p = readout(key, cw, rch, cap, rows)
            except ValueError:
                continue
        r = RCF.BY_KEY[key]
        nom = None if tol is None else (cw // r['mh'], ch // r['mv'] & ~1)          # the DC on the readout grid
        for hbin, vbin in BINS:
            pb = p
            try:
                s, pl = isp(pb, bits, rw, rh, vbin, hbin, nom)
            except F.NotPossible:
                # RWZM 1025 (R2) loses up to 16 px of a 1:1 record: one more 16 px of sensor crop
                # (+0.3 % field) buys them back, inside the 6064 the readouts deliver
                if hbin == vbin == 1 or cw + WIDEN > SENSOR_W:
                    continue
                try:
                    pb = readout(key, cw + WIDEN, rch, cap, rows)
                    s, pl = isp(pb, bits, rw, rh, vbin, hbin, nom)
                except (ValueError, F.NotPossible):
                    continue
            if tuple(pl.rec) != (rw, rh) and (tol is None or not short_ok(pl.rec, rw, rh, tol)):
                continue                                            # user 10-27: a quality never changes the RES
            out.append(dict(res=[rw, rh], quality=f'{key}' + ('-h3' if hbin == 3 else '') + ('-v3' if vbin == 3 else ''),
                            readout=pb['args'], merge=pb['merge'],
                            readout_id=pb['id'], fps=round(pb['fps'], 3), bits=bits, hbin=hbin, vbin=vbin,
                            window=list(s.window), zoom=list(s.zoom), rec=list(pl.rec), path=pl.path))
    return out


def ad_of(key, bits):
    """The quality's AD: 11 (fast), 12 or 14."""
    return {'fast': '11'}.get(RCF.BY_KEY[key]['ad'], '14' if bits == 14 else '12')


def quality_of(c):
    """The user's quality: sensor merge x AD x CRCT bins.  The readout's window width (w18, w2C, W...) is not one."""
    r = RCF.BY_KEY[c['readout'][0]]
    return f"{r['mh']}x{r['mv']}", ad_of(c['readout'][0], c['bits']), c['hbin'], c['vbin']


def pick(cs, group=lambda c: ()):
    """One case per group x quality: of its window variants the fastest (user 10-27: the window is a speed choice
    the formula makes), the first listed on a tie; in the order of the cases kept."""
    best = {}
    for c in cs:
        k = group(c) + quality_of(c)
        if k not in best or c['fps'] > best[k]['fps']:
            best[k] = c
    return [c for c in cs if best[group(c) + quality_of(c)] is c]


def visible_of(rec):
    """the DNG DefaultCrop a raster shows: the raster minus the stock margin"""
    return [rec[0] - F.MARGIN[0], rec[1] - F.MARGIN[1]]


def qualities(cw, ch, ow, oh, cap=None, tol=None):
    """The qualities that record exactly ow x oh from a cw x ch sensor crop, each on its fastest readout variant
    (max fps, or the most that reaches `cap`).  Raises what the formulas raise on input they do not cover
    (ZeroDivisionError for an empty sensor-grid crop or RES).
    tol: also the ones at most tol short per axis; every case then carries its own `visible` and the RES's `nominal`."""
    cs = pick(candidates(cw, ch, ow, oh, cap, tol))
    if tol is not None:
        for c in cs:
            c['visible'], c['nominal'] = visible_of(c['rec']), visible_of((ow, oh))
    return cs


def _replay(c, fps=None, v016=None):
    key, cw, ch, sw, sh = c['readout'][:5]
    hm = c['readout'][7] if len(c['readout']) > 7 else None
    more = [] if rows_of(c) is None else [0, rows_of(c)]
    return RCF.plan(key, cw, ch, sw, sh, fps, v016, hm, *more)


def vmax_range(c):
    """(lo, vmin, VMAX_MAX): the case runs at every VMAX lo..VMAX_MAX, fps = fps_at(c, VMAX).  vmin is the case's
    fps_max (the readout's own 0016 blanking: the rate candidates() compares); below it, down to lo, readout_cfg.plan
    falls back to the smallest tested blanking (0016 = v016_min) when it is asked for an fps."""
    vmin = _replay(c)['soc']['vmax']
    r = RCF.BY_KEY[c['readout'][0]]
    lo = _replay(c, v016=r['v016_min'])['soc']['vmax'] if r['v016_min'] is not None else vmin
    return min(lo, vmin), vmin, RCF.VMAX_MAX


def hmax_of(c):
    return _replay(c)['soc']['hmax']


def fps_at(c, vmax):
    return RCF.CLK / (hmax_of(c) * vmax)


def settings(c, fps=None):
    """The readout plan (fps None = fps_max) and the isp Spec of case c."""
    m = c['merge'].split('x')
    s = F.Spec(window=tuple(c['window']), zoom=tuple(c['zoom']), scale=(int(m[0]), int(m[1])), vbin=c['vbin'],
               hbin=c['hbin'], bits=c['bits'], rec=tuple(c['rec']))
    return _replay(c, fps), s
