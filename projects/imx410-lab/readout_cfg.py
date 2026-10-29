"""Single source of truth for the readout planner / generator / validator (DEV_PLAN D1).

Every readout the IMX410 can do on the fp, with the rules measured in IMX410_RULES §42-§58:
  mh, mv     sensor merge (horizontal, vertical); output rows = 2 * window H for every class
  fmt        sensor output width -> 0001 format code (the receiver then crops to the request, 12 px units)
  hmin       line-time floor (72 MHz cycles); hdef = the donor's own HMAX
  over       receiver lines on top of the image rows; centre = sensor row the window is centred on (2080 for every
             class; None: no window tested for this class -> full height only). start = centre - H*mv snapped to 1 mod 4
  v016       the donor's vertical blanking (0016); v016_min = smallest value tested good (None = not tested)
  fast_set   1x1 fast AD built on mode-10 rows: Family A fast values + TIM line length = width + 4 + DCLP width
  ev         where it was measured; 'est' = not measured with the standard method yet
"""
import json, math, pathlib

CLK = 72e6
HERE = pathlib.Path(__file__).resolve().parent
RESULTS = HERE / 'captures' / 'readout_validated.json'

READOUTS = [
    dict(key='14',       name='14-bit 1x1',       mh=1, mv=1, bits=14, ad='14',     donor=6,   fmt={6064: 0x29},
         hmin=870, hdef=911, over=52, centre=2080, v016=25, v016_min=None, ev='§42 §54'),
    dict(key='12',       name='12-bit 1x1',       mh=1, mv=1, bits=12, ad='normal', donor=10,  fmt={6064: 0x2A},
         hmin=445, hdef=445, over=52, centre=2080, v016=35, v016_min=2, ev='§45 §46'),
    dict(key='12fast',   name='12-bit fast 1x1',  mh=1, mv=1, bits=12, ad='fast',   donor=10,  fmt={4176: 0x2C},
         hmin=330, hdef=330, over=52, centre=2080, v016=35, v016_min=None, fast_set=True, ev='§49 (320 = broken frames, batch 10-22)'),
    dict(key='12fastW',  name='12-bit fast 1x1 wide', mh=1, mv=1, bits=12, ad='fast', donor=10, fmt={6064: 0x2A},
         hmin=400, hdef=400, over=52, centre=2080, v016=35, v016_min=None, fast_set=True, ev='§31 L2b (est)'),
    dict(key='2x2',      name='12-bit 2x2',       mh=2, mv=2, bits=12, ad='normal', donor=98,  fmt={3032: 0x39},
         hmin=445, hdef=445, over=30, centre=2080, v016=20, v016_min=None, ev='§21 (est)'),
    dict(key='2x2fast',  name='12-bit fast 2x2',  mh=2, mv=2, bits=12, ad='fast',   donor=11,  fmt={3032: 0x39},
         hmin=330, hdef=330, over=30, centre=2080, v016=7,  v016_min=7, ev='§47 §50 §52'),
    dict(key='3x3',      name='12-bit 3x3',       mh=3, mv=3, bits=12, ad='normal', donor=139, fmt={2016: 0x2F},
         hmin=445, hdef=445, over=26, centre=2080,  v016=50, v016_min=None, ev='mode 134 window (est)'),
    dict(key='3x3fast',  name='12-bit fast 3x3',  mh=3, mv=3, bits=12, ad='fast',   donor=8,   fmt={2016: 0x2F},
         hmin=330, hdef=330, over=26, centre=2080,  v016=50, v016_min=2, ev='§48 §58 (320 = broken frames, batch 10-22)'),
    dict(key='3x6',      name='12-bit 3x6',       mh=3, mv=6, bits=12, ad='normal', donor=140, fmt={2016: 0x30},
         hmin=445, hdef=445, over=19, centre=None, v016=35, v016_min=None, ev='M140 batch 10-22'),
    dict(key='3x6fast',  name='12-bit fast 3x6',  mh=3, mv=6, bits=12, ad='fast',   donor=12,  fmt={2016: 0x30},
         hmin=330, hdef=330, over=19, centre=None, v016=25, v016_min=None, ev='M12 batch 10-22: 287 fps linear, no drops'),
] 

# --- readout matrix (2026-10-22, IMX410_RULES §67): cells measured feasible or untested, built from register groups
# split off the stock tables. new=True: no stock class -> smc refuses them; layer-1 validation (direct writes) only.
# Vertical-only / horizontal-only and 14-bit vertical merges: §35 §37 §66, L7 T1. v6 without h3 and h2v3/h3v2: probes.
V2 = [(0x0005, 0x03), (0x001C, 0x03), (0x0717, 0x04), (0x071E, 0x05), (0x0720, 0x05), (0x0722, 0x02), (0x0723, 0x02),
      (0x0724, 0x02), (0x0725, 0x02), (0x0726, 0x01), (0x0728, 0x3D), (0x072A, 0xF0), (0x072B, 0x03), (0x072C, 0x04),
      (0x0734, 0x05), (0x0735, 0x05), (0x0737, 0x02), (0x0738, 0x02), (0x0739, 0x02), (0x073A, 0x02), (0x0792, 0x22),
      (0x0793, 0x02), (0x0794, 0x05), (0x079C, 0x3D)]                      # Z CAM MODE21 vertical 2:1 (L3)
V3 = [(0x0016, 0x32), (0x001C, 0x02), (0x0058, 0x70), (0x0717, 0x06), (0x071E, 0x03), (0x0722, 0x02), (0x0723, 0x02),
      (0x0724, 0x04), (0x0725, 0x04), (0x0728, 0x3F), (0x072A, 0xA0), (0x072B, 0x02), (0x072C, 0x06), (0x0734, 0x03),
      (0x0737, 0x02), (0x0738, 0x02), (0x0739, 0x04), (0x073A, 0x04), (0x0792, 0x30), (0x0793, 0x03), (0x079C, 0x3D)]   # mode 139 Family B (L4)
V3_WIN = [(0x08B6, 0x01), (0x08B7, 0x68)]   # full_v1 (IMX410_RULES §72): a V3 WINDOW's first 14 output rows go unexposed
                                           # whenever the frame is stretched (AE in a dim room). These two make the sensor
                                           # skip the window's first 16 output rows (content moves up 16, measured), so the
                                           # window is read 16 rows taller and starts 16 * mv sensor rows higher: same rows
                                           # out, same first image row. Full height must not have them (1390 -> 1374 lines).
V3_SKIP = 16
V3_MARGIN = int(__import__("os").environ.get("V3_MARGIN", 16))        # >= the 14 unexposed rows, and 16 * 3 = 48 sensor rows keeps the window start = 1 mod 4
V3_SKIP_ON = False   # withdrawn: with it the unexposed band moves INTO the frame (linearity VMAX points: rows 605-739,
                     # 20-206, 359-479 under-exposed) -- the band is not a top-row defect but a V3-window timing fault
V6 = [(0x0005, 0x01), (0x001C, 0x02), (0x0058, 0x70), (0x0716, 0x00), (0x0717, 0x00), (0x071E, 0x00), (0x0720, 0x00),
      (0x0727, 0x00), (0x0728, 0x00), (0x072A, 0x00), (0x072B, 0x00), (0x072C, 0x00), (0x0734, 0x00), (0x0735, 0x00),
      (0x0790, 0x00), (0x0792, 0x00), (0x0793, 0x00), (0x0794, 0x00), (0x0795, 0x00), (0x0796, 0x00), (0x0797, 0x00),
      (0x0798, 0x00), (0x079A, 0x00), (0x079C, 0x00), (0x079E, 0x00), (0x079F, 0x00)]                       # mode 140 vertical set
PAIR = [(0x0242, 0x2C), (0x0278, 0x04), (0x0279, 0x01), (0x027B, 0x04), (0x08B6, 0x01), (0x08B7, 0x68)]   # same-colour pairing: h1 v2 only (§37)
BINNED = [(0x0058, 0x70)]
FULL = [(0x0003, 0x00)]          # no sensor window. (0018 = extra dark rows was on in matrix r1/r2 but is not among the
                                  # 161 REG-table registers, so a generated mode cannot carry it; stock binned modes do without)

_OVER = {(2, 1): 54, (3, 1): 34, (1, 2): 26, (3, 2): 26, (1, 3): 43, (2, 3): 43, (1, 6): 19, (2, 6): 19}
# receiver lines over the image rows, firmware switch WITHOUT 0018 (smc_m1 2026-10-23): every class sent exactly 36
# lines fewer than with 0018=0x12 on (matrix r1/r2: 90/70/62/60/79/79) -- 0x12 = 18 extra dark row pairs
_V016 = {1: 35, 2: 35, 3: 50, 6: 35}


_ROWS_FULL = {2: 2014}   # full-height image rows from y0 when fewer than 4040/mv: every V2 class (12v2, f12v2, 12h3v2) sent
                         # only 2014 image rows from y0 = 20, the last 6 receiver rows read 1 (smc_m1 dark, 2026-10-23)
_Y0 = {(1, 2): 20, (1, 3): 20, (2, 1): 40, (3, 1): 20, (2, 3): 20, (3, 2): 20}   # first COMPLETE row pair (full frames)   # first image row, even; h2 / h2v3 re-measured
# measured by the firmware switch without 0018 (smc_m1, 2026-10-23): first lit row 17/18 for every vertical or mixed
# merge, 40 for h2 (3B); h3 (2F, v1): rows 16-19 read below black (199), texture from row 20 (the 640 was a dark scene top)


def _cell(key, mh, mv, ad, fmt, extra, ev):
    bits = 14 if ad == '14' else 12
    h = {'14': 870, 'normal': 445, 'fast': 400 if min(fmt) > 4200 else 330}[ad]
    return dict(key=key, name=f'{bits}-bit{" fast" if ad == "fast" else ""} {mh}x{mv}', mh=mh, mv=mv, bits=bits, ad=ad,
                donor=6 if ad == '14' else 10, fmt=fmt, hmin=h, hdef=h, over=_OVER[(mh, mv)], centre=2080, v016=_V016[mv],
                v016_min=None, fast_set=ad == 'fast', extra=FULL + extra, new=True,
                y0=_Y0[(mh, mv)], rows_full=_ROWS_FULL.get(mv),
                cls=16 if ad == '14' else 17, ev=ev)


for _ad, _p in (('normal', ''), ('fast', 'f')):
    READOUTS += [
        _cell(f'{_p}12v2', 1, 2, _ad, {6064: 0x2A}, V2 + PAIR, '§35 §37 (12-bit normal)'),
        _cell(f'{_p}12v3', 1, 3, _ad, {6064: 0x2A}, V3, '§37'),
        _cell(f'{_p}12h2', 2, 1, _ad, {3032: 0x3B}, BINNED, '§35 (3B)'),
        _cell(f'{_p}12h3', 3, 1, _ad, {2016: 0x2F}, BINNED, 'probe'),
        _cell(f'{_p}12h2v3', 2, 3, _ad, {3032: 0x3B}, V3, 'matrix r2: 3B + V3 (39 + V3 put the colours 2 rows apart)'),
        _cell(f'{_p}12h3v2', 3, 2, _ad, {2016: 0x2F}, V2 + PAIR + BINNED, 'matrix r2: 2F + V2 + pairing set (without it 1.45 rows apart)'),
    ]
READOUTS += [
    _cell('14v2', 1, 2, '14', {6064: 0x29}, V2 + PAIR, 'L7 T1'),
    _cell('14v3', 1, 3, '14', {6064: 0x29}, V3, '§66'),
]
# matrix round 2 (§67): the format word decides whether the sensor pairs rows itself -- 39 (stock 2x2) does, so it
# cannot carry V3; 2F (h3) and 2A/3B (no h merge in v) do not, so v2 with them needs the pairing set
# measured NOT feasible (matrix round 1, §67): v/6 without the h3 format word 30 (12v6 sent 2272 lines, 12h2v6 2080 --
# the 07xx v6 set alone does not divide by 6); 14-bit with any non-stock 0001 word (only 29/2B carry a 14-bit image)
READOUTS += [
]
# sensor-side horizontal crop presets (format words with a narrower output, §43/§45; user 2026-10-23: they are width
# crops): EXPERIMENTAL, not in any validation set until measured (fmtw.py). Same Family A as 12 / 12fast, 1x1, cls 17.
EXPERIMENTAL = []
for _w, _code, _nm in ((5073, 0x18, 'w18'), (4016, 0x03, 'w03'), (4176, 0x2C, 'w2C')):
    for _fast in (False, True):
        _b = dict(next(r for r in READOUTS if r['key'] == ('12fast' if _fast else '12')))
        _b.update(key=('f12' if _fast else '12') + _nm, fmt={_w: _code}, cls=17, exp=True,
                  hmin=max(330, -(-_w * 665 // 100000) * 10) if _fast else 445, hdef=max(330, -(-_w * 665 // 100000) * 10) if _fast else 445,   # fmtw: fast floor ~0.0665*W up to the measured 10s, AD floor 330
                  name=f'12-bit{" fast" if _fast else ""} 1x1 width {_w} ({_code:02X}) [exp]')
        if not (_fast and _code == 0x2C):              # f12w2C == the stock-derived 12fast class
            EXPERIMENTAL.append(_b)
# width presets with vertical merges, fast AD (user 2026-10-23: do they stack?): the format word only sets the width,
# the V2 (+pairing) / V3 group sets the vertical merge -- same extra regs as f12v2 / f12v3
for _vk in ('f12v2', 'f12v3'):
    _v = next(r for r in READOUTS if r['key'] == _vk)
    for _w, _code, _nm in ((5073, 0x18, 'w18'), (4016, 0x03, 'w03'), (4176, 0x2C, 'w2C')):
        _b = dict(_v)
        _h = max(330, -(-_w * 665 // 100000) * 10)
        _b.update(key=_vk + _nm, fmt={_w: _code}, exp=True, new=True, hmin=_h, hdef=_h,
                  name=f'{_v["name"]} width {_w} ({_code:02X}) [exp]')
        EXPERIMENTAL.append(_b)
# full matrix (user 2026-10-23: every bit depth x crop x merge x format x AD). 11-bit == the fast AD (§21/Z CAM), so
# bit depth and AD are one axis: 14 / 12 normal / 11 fast. Missing cells: normal-AD width presets with V2/V3 (the fast
# ones stack, round 22) and 14-bit 2B (the only other 14-bit word, §67 scan) at 1x1 / V2 / V3. 03 + merge stays out.
for _vk in ('12v2', '12v3'):
    _v = next(r for r in READOUTS if r['key'] == _vk)
    for _w, _code, _nm in ((5073, 0x18, 'w18'), (4176, 0x2C, 'w2C')):
        _b = dict(_v)
        _b.update(key=_vk + _nm, fmt={_w: _code}, exp=True, new=True, name=f'{_v["name"]} width {_w} ({_code:02X}) [exp]')
        EXPERIMENTAL.append(_b)
for _vk in ('14', '14v2', '14v3'):
    _b = dict(next(r for r in READOUTS if r['key'] == _vk))
    _b.update(key=_vk + 'w2B', fmt={4176: 0x2B}, exp=True, cls=16, name=f'{_b["name"]} width 4176 (2B) [exp]')
    if _vk == '14':
        _b.update(new=False)
    EXPERIMENTAL.append(_b)
# measured geometry (fmtexp, 2026-10-23): 18 / 03 at 1x1 move the image up 6 rows (textured 34..4075, y0 34); 18 with
# V3 ends 6 rows early (17..1371 -> 1352 from 20); 03 with V2/V3 loses the OB rows (texture from row 1) -> dropped;
# 2C needs nothing (1x1 / V2 / V3 pass as planned)
_GEOM = {'12w18': dict(y0=34), 'f12w18': dict(y0=34), 'f12v3w18': dict(rows_full=1352), '12v3w18': dict(rows_full=1352),  # [I] same as fast
         '12w03': dict(y0=34), 'f12w03': dict(y0=34)}
for _r in EXPERIMENTAL:
    _r.update(_GEOM.get(_r['key'], {}))
EXPERIMENTAL = [r for r in EXPERIMENTAL if r['key'] not in ('f12v2w03', 'f12v3w03')]
READOUTS += EXPERIMENTAL
BY_KEY = {r['key']: r for r in READOUTS}
# full-height image rows from y0, measured (rowrange search, lens open, window kept, 2026-10-23): every stock binned
# readout delivers exactly 4032 sensor rows of image (2x2 / V2 rows 18..2033, 3x3 14..1357, 3x6 8..679 = 4032/vbin);
# 1x1 delivers 4042 (40..4081). Planning more rows than this gave rows that read 1 (2x2: 2020 -> 6, 3x3: 1347 -> 3,
# 3x6: 673 -> 1). 12v3 (Family B V3 on 2A) textures 17..1377 -- 1358 from y0, kept at the validated 1347 for now.
for _r in READOUTS:
    if _r['mv'] in (2, 3, 6) and not _r.get('rows_full'):
        # new V3 classes (Family B on 2A / 3B): textured 17..1377 -> 1358 from y0 = 20 (14v3 assumed the same [I])
        _r['rows_full'] = 1358 if (_r.get('new') and _r['mv'] == 3) else {2: 2014, 3: 1344, 6: 672}[_r['mv']]
VMAX_MAX = 16384                                    # SoC 0x30100020 field is 14 bits: 16384 OK, 16385 wrapped and
                                                    # wedged the shell (longexp 2026-10-23) -- never write above
SENSOR_H = 4040                                     # active rows
WIN_TOP, WIN_BOTTOM = 56, 4104                      # readable sensor rows for a window (2x2 lit-row edges, SMC round 4)


def validated():
    try:
        return json.loads(RESULTS.read_text())
    except (OSError, ValueError):
        return {}


V3_FULL_SKIP = 28    # §76: a new-V3 full-height frame has 14 good rows, then 14 unexposed rows the sensor inserts (every
                     # frame, any exposure; content continues across them), then the rest -- start the ISP below both


def full_rows(key):
    """output rows of a full-height plan on readout `key` (even)"""
    r = BY_KEY[key]
    n = r.get('rows_full') or int(SENSOR_H / r['mv']) // 2 * 2
    return n - V3_FULL_SKIP if r['mv'] == 3 and r.get('new') else n


LINE_SHORT = 16    # full_v1 (IMX410_RULES §72, xoff.py): a 1x1 format word narrower than the full 6064 sends a line
                   # 16 columns shorter than its width (4176 -> 4160, 4016 -> 4000, 5073 -> 5057); captured from x0 = 8,
                   # the last 24 raster columns were pad (normal AD) or garbage (fast AD). x0 = 0, 4160: no pad, same phase


def line_width(r, fmt):
    """columns of real image a format word's line carries"""
    return fmt - LINE_SHORT if r['mh'] == 1 and fmt < 6000 else fmt


def max_width(r):
    """widest raster (multiple of 16) readout r can record"""
    lw = line_width(r, max(r['fmt']))
    return lw // 16 * 16


def config_id(key, cw, ch, ow, oh, fps):
    return f'{key}:{cw}x{ch}>{ow}x{oh}@{fps:g}'


def plan(key, cw, ch, ow, oh, fps=None, v016=None, hmax=None, hdr=0, rows=None):
    """crop cw x ch (sensor px) -> output ow x oh at fps on readout `key`: everything needed to set it up, or
    raise ValueError if the rules say it cannot be done.

    rows (R16, isp-lab quality.py): a full-height plan whose TIM keeps only `rows` output rows, centred in the frame
    the readout delivers (y0 moves down by the rows above them, even: Bayer phase). The sensor still reads and sends
    the whole frame (same lines, same fps); the ISP raster, the record and the DNG get only these rows."""
    r = BY_KEY[key]
    sw, sh = cw / r['mh'], ch / r['mv']                 # crop on the sensor output grid
    fmt = min((w for w in r['fmt'] if line_width(r, w) >= sw - 1e-6), default=None)
    if fmt is None and line_width(r, max(r['fmt'])) >= sw * 0.995:   # within 0.5 %: trim the crop to the format (OG on 3x3)
        fmt = max(r['fmt']); sw = line_width(r, fmt)
    if fmt is None:
        raise ValueError(f'crop {cw} wider than {key} formats')
    full_h = SENSOR_H / r['mv']
    windowed = sh < full_h - 2
    if r['mh'] == 3 and r['mv'] == 1:
        # full_v1 (IMX410_RULES §72): 12h3 / f12h3 deliver no red or blue -- R and B at black (R/G 0.0-0.26 vs 0.59 on
        # 1x1, full height too); with the sensor window half the frame also sits up to ~120 DN below black. Format 2F
        # (native 3x3) is fine with the V3 (3x3) and V2 (h3v2) groups; with no vertical group it is not. Not usable yet.
        raise ValueError(f'{key}: 3:1 horizontal with no vertical merge gives no red / blue (format 2F needs a vertical group)')
    # full height: the readout delivers rows_full rows, which can be more than 4040/v (1x1 4042, new V3 1358 = 4074
    # sensor rows) -- checked against rows_out below; a window is bounded by its crop
    if ow > sw + 1e-6 or (windowed and oh > sh + 1e-6):
        raise ValueError('RWZM cannot upscale')
    if windowed and r['centre'] is None:
        raise ValueError(f'{key}: vertical window not tested -- full height only')
    H = math.ceil(sh / 2)
    hm = hmax or r['hmin']
    if hm < r['hmin']:
        raise ValueError(f'HMAX {hm} below the floor {r["hmin"]}')
    rows_out = 2 * H if windowed else full_rows(key)
    y_crop = 0
    if rows is not None:                                # R16: a centred row crop of the full-height frame
        if windowed:
            raise ValueError(f'{key}: a row crop is cut from a full-height frame, not from a window')
        if rows <= 0 or rows % 2 or rows > rows_out:
            raise ValueError(f'{key}: row crop {rows} not even inside the {rows_out} rows delivered')
        y_crop = (rows_out - rows) // 4 * 2
        rows_out = rows
    if oh > rows_out:
        raise ValueError(f'{key}: {oh} output rows > {rows_out} the readout delivers')
    lines = (rows_out if windowed else int(round(full_h))) + r['over']   # the sensor still sends the empty rows below rows_full
    # new V3 windows: the window's first 14 output rows go unexposed now and then (a sensor-internal cycle not locked to
    # the frame, §72/§76). Read V3_MARGIN more rows above the window and let the ISP start below them: the bad rows land
    # in the margin, the output keeps its planned rows and first row. Costs V3_MARGIN lines (~1 % rolling).
    y_skip = (V3_MARGIN if windowed else V3_FULL_SKIP) if r['mv'] == 3 and r.get('new') else 0
    lines += y_skip if windowed else 0
    y_skip += y_crop                                    # R16: the TIM starts below the dropped rows (smc y0)
    b = r['v016'] if v016 is None else v016
    if b < r['v016'] and (r['v016_min'] is None or b < r['v016_min']):
        raise ValueError(f'0016={b} below the tested minimum for {key}')
    vmin = lines + 2 * b + 12
    if fps:
        vmax = round(CLK / (hm * fps))
        if vmax < vmin and r['v016_min'] is not None and v016 is None:   # try the smaller tested blanking
            b = r['v016_min']; vmin = lines + 2 * b + 12
        if vmax < vmin:
            raise ValueError(f'{fps} fps needs VMAX {vmax} < minimum {vmin}')
        if vmax > VMAX_MAX:
            raise ValueError(f'{fps} fps needs VMAX {vmax} > {VMAX_MAX} (14-bit SoC field) -- multi-frame exposure (0007)')
    else:
        vmax = vmin
    rx_w = math.ceil(sw / 12) * 12
    lw = line_width(r, fmt)
    raster_w = min(fmt if lw == fmt else lw // 16 * 16, math.ceil(sw / 16) * 16)   # recorded raster (BUFA/ISP: x16)
    sensor = list(r.get('extra', [])) + [(0x0001, r['fmt'][fmt])]   # matrix classes: their register groups first
    if windowed:
        # window start is in SENSOR rows for every merge class and the window spans 2H output rows = 2H*mv sensor rows,
        # centred on row 2080 (stock 10/100/58/134/132 all fit); it must be = 1 mod 4 like every stock window -- an even
        # start mixes the colours (1x1, 3x3) or swaps the Bayer row phase (2x2) (SMC round 4, captures/winbound)
        raw = r['centre'] - H * r['mv']
        st = min((raw + k for k in range(-2, 3) if (raw + k) % 4 == 1), key=lambda x: (abs(x - raw), x))
        if st < WIN_TOP or st + 2 * H * r['mv'] > WIN_BOTTOM:
            raise ValueError(f'{key}: window rows {st}..{st + 2 * H * r["mv"]} outside the readable {WIN_TOP}..{WIN_BOTTOM}')
        Hr = H + y_skip // 2; st -= y_skip * r['mv']                       # 16 rows = 48 sensor rows: still = 1 mod 4
        if st < WIN_TOP:
            raise ValueError(f'{key}: window rows {st}.. above the readable {WIN_TOP} (V3 margin)')
        if r['mv'] == 3 and r.get('new') and V3_SKIP_ON:
            Hr = H + V3_SKIP // 2; st -= V3_SKIP * r['mv']                 # 48 sensor rows: still = 1 mod 4
            if st < WIN_TOP:
                raise ValueError(f'{key}: window rows {st}.. above the readable {WIN_TOP} (V3 skip)')
            sensor += V3_WIN
        sensor += [(0x0003, 1), (0x0022, st & 0xFF), (0x0023, st >> 8), (0x0024, Hr & 0xFF), (0x0025, Hr >> 8)]
    elif not any(a == 0x0003 for a, _ in sensor):
        sensor.append((0x0003, 0))                      # full height: switch the donor's window off (HDR r1: 12 / 14
                                                        # full-height plans read only the donor's 2076 rows)
    if b != r['v016']:
        sensor.append((0x0016, b))
    if hdr:
        # single-frame checkerboard HDR (§30): 0242 bit 0 + 0738 = attenuated row group; 1x1 and vertical merges only
        # [I, to be measured for every class]. The cells are 4 raw columns wide: crops stay 4-aligned because the
        # receiver works in 12-px units; an ISP-side x0 must be = 0 mod 4 as well.
        regs = dict(sensor)
        sensor = [(a, v) for a, v in sensor if a not in (0x0242, 0x0738)]
        sensor += [(0x0242, regs.get(0x0242, 0) | 1), (0x0738, hdr)]
    return dict(id=config_id(key, cw, ch, ow, oh, fps or 0) + (f'+hdr{hdr:02X}' if hdr else '') + (f'+rows{rows}' if rows is not None else ''), key=key, hdr=hdr, name=r['name'], ev=r['ev'], donor=r['donor'], bits=r['bits'],
                merge=f"{r['mh']}x{r['mv']}", mv=r['mv'], new=bool(r.get('new')), crop=[cw, ch], out=[ow, oh], fmt_w=fmt, line_w=lw, raster_w=raster_w, out_h=rows_out, y_skip=y_skip, receiver_lines=lines,
                rwzm=[sw / ow, sh / oh], sensor=sensor, fast_set=bool(r.get('fast_set')),
                rows=dict(TIM_line=(fmt + 4) if r.get('fast_set') and fmt < 6000 else None,
                          R38_words=(fmt // 12 + 1) if r.get('fast_set') and fmt < 6000 else None),
                soc=dict(hmax=hm, vmax=vmax, rx_width=rx_w, rx_end=lines - 2),
                fps=CLK / (hm * vmax), fps_max=CLK / (hm * vmin), rolling_ms=hm * lines / CLK * 1e3)
