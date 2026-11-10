"""ISP custom formula v2 (notes/ISP_FORMULA_V2.md): one profile row from measured hardware rules, no mode names.

    plan(Spec(window=(W, H), scale=(sx, sy), zoom=(Zh, Zv), vbin=1|3, bits=8|10|12|14, hirate=False))
        -> Plan(rec, act, path, preview, visible, raster, standby, words)    or raises NotPossible(reason)

The stock rows are a regression check only (test_isp_formula): v2 fed a stock route's inputs must give that row.
Rules (ISP_CAPABILITY_MAP §0.5, live 2026-10-27):
  R1 RWZM per axis 1024..8191 (8192 wraps); 1023 = unity pass-through
  R2 a record 1:1 on both axes does not bin (B/D: top-left crop); one axis off unity is enough (1025 works)
  R3 horizontal CRCT bin: branch C's Hbin2 already
     divides H by 3, the main-pipe /3 must be cleared (res-custom ogc_binpath; isp_custom installs binfilt.S)
  R4 CRCT bin x3 averages, only in branch C                        R5 never branch F
  R10 a 1:1 record previews at the integer ratio that shows all of it (visible <= 2000)
  R9 C at any RWZM: E1 crops the recording LV once act x Z passes 2000 (mx1 M74 0.945); C there shows it all
  R6 preview source <= 2100, visible <= 2000 (16s), raster = visible + 16/10 inside the source
  R7 plane codes per depth                                          R8 rec = window / bin * 1024 / Z, &~15 / &~1
  R11 the ISP takes at most ~15 raster px per 72 MHz line clock: a faster readout puts single frames one row off and
      the CRCT-binned preview / record off by a row (10-27 12fastW / f12v3 at 6048: HMAX 400 bad, 405 good) -- the
      readout's HMAX >= min_line_clk(raster width), 14.5 px/clk with margin
  R15 14 bit wider than 4192 needs HMAX 911 (stock): 10-28 hsA/hsB at 6048 broke frames at every HMAX 875-900
      (CFA one row off, noise) and at 905 on h3v3 (2 of 12); 4192 was clean at 860 / 865 and in p5 at 870 (33 frames).
      The single-frame floor (IMX410_RULES §42, ~860) does not hold for a continuous take at full width
  R12 the preview source is at most SRC_MAX_H rows: E1 (1:1 preview) on a 4040-row window froze the take twice
      (10-28 SQ 2016x2016 2x1); taller windows take E3's /3 bin preview -- the LV gains nothing from more rows
  R14 an E1 / E3 preview that cannot hold the record's act inside its source margin shows less than the record
      (10-28 p5: E3 1x3 S16 688 0.948 predicted, 0.948 measured; 47 of the 50 E-path field-of-view fails); C at
      the record's zoom per axis holds it whenever it fits, so it takes those -- unequal axes as with a CRCT bin.
      Only where C shows all of it (10-28 p6r14: S35 2096 at C met the 2000 visible cap, 0.958 against E3's 0.988).
      (RWZM H 1:1 under C is fine: the 'standby stretched x3' of p5..p7 was case.py taking the REC-start frame.)
"""
import struct
from dataclasses import dataclass, field

UNITY = 1024
UNITY_STOCK = 1023                   # stock writes unity as 1023
RWZM_MAX = 8191                      # R1
SRC_MAX = 2100                       # R6
SRC_MAX_H = 1710                     # R12: preview source rows (stock <= 1174; E1 1702 ran, 4040 froze the camera 10-28)
VIS_MAX_W = 2000
MARGIN = (16, 10)
KNOWN_H = (1125, 1334)               # visible heights the camera shows at width 2000 (16:9 stock, 3:2)
E3_W_MAX = 3 * SRC_MAX               # /3 preview still inside the source
PLANE = {8: (10, 10), 10: (10, 9), 12: (7, 7), 14: (7, 8)}    # R7
HBIN = {1: 0, 3: 1}                  # CRCT enum (FUN_c022ee10); 5 has no kernel
LINE_PX_PER_CLK = (29, 2)            # R11: 14.5 raster px per line clock (measured 15.1 bad, 14.9 good)
WIDE14_W, WIDE14_HMAX = 4192, 911   # R15: a 14-bit raster wider than this needs the stock line (10-28 hs sweep)
STANDBY_WINDOW_DIV = 3               # the 6 standby profiles read the full sensor /3 (2016 x 1344)
STANDBY_VIS_MAX = (2000, 1334)


class NotPossible(ValueError):
    """This combination does not exist: the UI must not offer it."""


@dataclass(frozen=True)
class Spec:
    window: tuple                    # raster the sensor sends (IMX410 custom)
    zoom: tuple                      # record RWZM per axis, x1024 (1024 = 1:1)
    scale: tuple = (1, 1)            # sensor pixels per raster pixel (sensor binning)
    vbin: int = 1                    # CRCT vertical bin: 1 or 3
    hbin: int = 1                    # CRCT horizontal bin: 1 or 3 (R3: only with binfilt's branch C fix)
    bits: int = 12
    hirate: bool = False
    rec: tuple = None                # the record size wanted (DNG); None = the most R8 allows. Stock UHD
                                     # declares 3856 x 2170 out of a possible 3872 x 2184: rec is a choice <= max


@dataclass
class Plan:
    rec: tuple
    act: tuple
    path: str                        # B / C / D / E1 / E3
    preview: tuple                   # (hbin enum, vbin enum, RWZM H, RWZM V) as written
    source: tuple                    # preview source size
    visible: tuple
    raster: tuple
    standby: tuple
    words: dict = field(default_factory=dict)    # profile word offset -> value


def _z(v):
    return UNITY_STOCK if v <= UNITY else v


def ceil16(x):
    return (x + 15) // 16 * 16


def record(s: Spec):
    zh, zv = s.zoom
    for z in (zh, zv):
        if not (z == UNITY or UNITY < z <= RWZM_MAX):
            raise NotPossible(f'RWZM {z} outside 1024..{RWZM_MAX} (R1)')
    if s.vbin not in (1, 3) or s.hbin not in (1, 3):
        raise NotPossible('a CRCT bin is 1 or 3')
    if (s.vbin == 3 or s.hbin == 3) and zh == UNITY and zv == UNITY:
        raise NotPossible('a unity record does not bin (R2)')
    most = (((s.window[0] // s.hbin) * UNITY // zh) & ~15, ((s.window[1] // s.vbin) * UNITY // zv) & ~1)
    rec = s.rec or most
    if rec[0] % 16 or rec[1] % 2 or rec[0] > most[0] or rec[1] > most[1] or rec[0] <= MARGIN[0] or rec[1] <= MARGIN[1]:
        raise NotPossible(f'record {rec} not a multiple of 16 x 2 inside {most} (R8)')
    return rec, (rec[0] - MARGIN[0], rec[1] - MARGIN[1])


def path(s: Spec, act=None):
    """-> (path, preview factor H, V) in window pixels per preview pixel x1024, never branch F (R5)."""
    W, H = s.window
    aw = act[0] if act else W
    fh, fv = s.zoom[0] * s.hbin, s.zoom[1] * s.vbin
    if s.vbin == 3 or s.hbin == 3:                           # R4: only C bins, preview = record per axis
        if W * UNITY // fh > SRC_MAX or H * UNITY // fv > SRC_MAX_H:
            raise NotPossible('a CRCT bin needs the preview to equal the record, which does not fit (R6, R12)')
        return 'C', fh, fv
    if fh == UNITY and fv == UNITY:                          # record 1:1
        if W <= SRC_MAX and aw <= VIS_MAX_W and H <= SRC_MAX_H:
            return 'B', UNITY, UNITY
        # D: the smallest integer ratio (one phase) whose source fits AND whose visible holds the whole record (R10:
        # S35 2096 / 4192 at 1 / 2 showed 0.95 of it in the recording LV, mx1 sby M60 / M55)
        k = max(-(-W // SRC_MAX), -(-aw // VIS_MAX_W), -(-H // SRC_MAX_H))
        return 'D', k * UNITY, k * UNITY
    c_fits = W * UNITY // fh <= SRC_MAX and H * UNITY // fv <= SRC_MAX_H
    if fh == fv and c_fits:                          # C live 1536..3218 unbinned, 6436 with vbin (mx1/cmax 10-27)
        return 'C', fh, fv
    if W <= SRC_MAX and H <= SRC_MAX_H:              # R12: a tall 1:1 preview froze the take (SQ 2032x4040 E1)
        e = 'E1', UNITY, UNITY
    elif W <= E3_W_MAX:
        e = 'E3', 3 * UNITY, 3 * UNITY
    else:
        raise NotPossible('no preview avoids branch F (R5)')
    if act and c_fits and not _shows_all(s, act, e[1], e[2]) and _shows_all(s, act, fh, fv):   # R14
        return 'C', fh, fv
    return e


def _shows_all(s: Spec, act, ph, pv):
    """R14: does a preview at ph x pv hold the record's act inside its source's 16/10 margin?"""
    fh, fv = max(s.zoom[0], UNITY) * s.hbin, max(s.zoom[1], UNITY) * s.vbin
    src = (s.window[0] * UNITY // ph, s.window[1] * UNITY // pv)
    vis = visible(s, act, ph, pv, src)
    return vis[0] >= act[0] * fh // ph and vis[1] >= act[1] * fv // pv


def preview_fields(s: Spec, p, ph, pv):
    """(hbin enum, vbin enum, RWZM H, RWZM V) the profile's preview group carries."""
    if p == 'C':
        return HBIN[s.hbin], HBIN[s.vbin], _z(s.zoom[0]), _z(s.zoom[1])
    if p == 'E3':
        return HBIN[3], HBIN[3], UNITY_STOCK, UNITY_STOCK
    return 0, 0, _z(ph), _z(pv)


def visible(s: Spec, act, ph, pv, src):
    """The record's visible area in preview pixels, fitted inside the source (R6)."""
    fh, fv = max(s.zoom[0], UNITY) * s.hbin, max(s.zoom[1], UNITY) * s.vbin
    aw, ah = act[0] * fh // ph, act[1] * fv // pv
    sw, sh = src[0] - MARGIN[0], src[1] - MARGIN[1]
    if aw <= 0 or ah <= 0 or sw <= 0 or sh <= 0:
        raise NotPossible('empty preview')
    vw, vh = aw, ah
    cap = min(sw, VIS_MAX_W)
    if vw > cap:
        vw, vh = cap, cap * ah // aw
    if vh > sh:
        vh, vw = sh, sh * aw // ah
    vw = min(ceil16(vw), sw // 16 * 16)
    if vw == VIS_MAX_W:
        for k in KNOWN_H:
            if abs(vh - k) <= 4 and k <= sh:
                vh = k
    return vw, vh


def standby(s: Spec, vis, ph, pv):
    """The recording LV's sensor area in the standby window (full sensor / 3). Full-frame readouts only:
    crop readouts use another standby mechanism (ISP_FORMULA_V2 §5-1)."""
    sx, sy = s.scale
    return (min(STANDBY_VIS_MAX[0], vis[0] * ph * sx // (STANDBY_WINDOW_DIV * UNITY)),
            min(STANDBY_VIS_MAX[1], vis[1] * pv * sy // (STANDBY_WINDOW_DIV * UNITY)))


def min_line_clk(w, bits=12):
    """R11: the shortest line (HMAX, 72 MHz clocks) the ISP keeps up with for a raster w wide; R15 for 14 bit."""
    hm = -(-w * LINE_PX_PER_CLK[1] // LINE_PX_PER_CLK[0])
    if bits == 14 and w > WIDE14_W:
        hm = max(hm, WIDE14_HMAX)
    return hm


def fbits(x):
    return struct.unpack('<I', struct.pack('<f', float(x)))[0]


def plan(s: Spec) -> Plan:
    rec, act = record(s)
    p, ph, pv = path(s, act)
    pre = preview_fields(s, p, ph, pv)
    src = (s.window[0] * UNITY // ph, s.window[1] * UNITY // pv)
    # every branch of path() keeps the source inside SRC_MAX (test_preview_inside_its_source)
    vis = visible(s, act, ph, pv, src)
    ras = (vis[0] + MARGIN[0], vis[1] + MARGIN[1])
    w = {0x00: rec[0], 0x04: rec[1], 0xDC: rec[0], 0xE4: rec[1], 0x24: act[0], 0x2C: act[1],
         0xF4: s.window[0], 0xF8: s.window[1],
         0x0C: ras[0], 0x10: ras[1], 0xD8: ras[0], 0xE0: ras[1], 0x20: vis[0], 0x28: vis[1],
         0x58: pre[0], 0xC4: pre[1], 0x60: pre[2], 0xD0: pre[3],
         0x64: _z(s.zoom[0]), 0xD4: _z(s.zoom[1]), 0x5C: HBIN[s.hbin], 0xC8: HBIN[s.vbin],
         0xFC: fbits(s.scale[0]), 0x100: fbits(s.scale[1]),
         0x80: PLANE[s.bits][0], 0x84: PLANE[s.bits][1], 0xB0: 1 if s.hirate else 0,
         0x38: 16 if p == 'E3' else 1, 0x1C: 1, 0x88: 0, 0x90: 1, 0xC0: 0}
    return Plan(rec, act, p, pre, src, vis, ras, standby(s, vis, ph, pv), w)


def row(s: Spec, base_row):
    """The whole 65-word row: the formula's words over a video-class base (34 words identical in every video row)."""
    out = list(base_row)
    for off, v in plan(s).words.items():
        out[off // 4] = v
    return out
