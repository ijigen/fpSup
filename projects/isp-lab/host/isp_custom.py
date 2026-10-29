#!/usr/bin/env python3
"""ISP custom: one recording experiment = a Want -> imx410_profile.declare() -> one profile row, installed in RAM
over a stock route's row while the camera is in standby (notes/IMX410_LAB_SPEC.md §0).

The formula is the experiment: nothing here patches a field by hand. A target is turned into a Want with the
recording size rules (imx410-lab notes/ISP_SIZE_RULES.md §1: rec = (window // bin) * 1024 // Z, width & ~15,
height & ~1; act = rec - (16, 10)); declare() writes the whole 65-word row; only the words that differ from the
stock row are written, each into its column table (all 65 table addresses checked against the 5.02 image).

    isp_custom.py show EXP            the Want, the row and the words that would change
    isp_custom.py apply EXP           standby only: write them (readback-checked) and remember them
    isp_custom.py restore             put the stock words back (readback-checked)

Experiments (stock route FHD30 = profile 175, row 122, sensor mode 106, raster 3032x1708):
    E0  the stock route through the formula: must change nothing
    E1  record CRCT bin 3x3, RWZM 1:1
    E2  RWZM 1536 (a ratio stock never records with), bin 1
A instant restart keeps RAM: always `restore`, or cold-reboot with the shell's `reboot`.
"""
import argparse, dataclasses, json, pathlib, struct, sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OG = ROOT / 'projects' / 'open-gate' / 'build'
SHELL = ROOT / 'fpSup' / 'fp_usb_shell'
PROFILES = ROOT / 'research/other/external/FP3K-technical-handoff-2026-09-10/analysis/firmware/raw-profiles.json'
IMAGE = ROOT / 'out' / 'MAIN_c0000000.bin'
STATE = HERE / '.isp_custom_applied.json'
sys.path[:0] = [str(OG), str(SHELL)]
import imx410_profile as P                                   # noqa: E402

import os                                                    # noqa: E402
import isp_formula as F                                      # noqa: E402
import aspect                                                # noqa: E402
FORMULA = os.environ.get('ISP_FORMULA', 'v2')                # v1 = open-gate imx410_profile.declare (shared)


def spec_of(w):
    """A v1 Want -> a v2 Spec: same geometry, the record bin (1|3, 1|3)."""
    return F.Spec(window=tuple(w.window), zoom=tuple(1024 if z == P.RWZM_UNITY_STOCK else z for z in w.zoom),
                  scale=tuple(int(x) for x in w.scale), vbin=w.bin[1], hbin=w.bin[0], bits=w.bits, hirate=w.hirate, rec=tuple(w.rec))


ROUTE = 'FHD30'
BASE_ID = 171                     # the base row declare() is proven with (test_imx410_profile)


def tables():
    """{profile word offset: column table address}, every one checked against the image."""
    j = json.loads(PROFILES.read_text())
    img = IMAGE.read_bytes()
    out = {}
    for c in j['columns']:
        col = list(struct.unpack_from('<306I', img, c['table'] - 0xC0000000))
        if col != [r['words'][c['offset'] // 4] for r in j['rows']]:
            raise SystemExit(f'profile column +{c["offset"]:#x}: table {c["table"]:#x} does not match the image')
        out[c['offset']] = c['table']
    if sorted(out) != list(range(0, 0x104, 4)):
        raise SystemExit('profile columns: not exactly 65 words')
    return out, j


def stock(j, row):
    return list(j['rows'][row]['words'])


FORMAT_12 = 7                     # movie_routes format_enum: the same name exists once per depth (7/9/10)
FORMAT_OF_BITS = {12: 7, 10: 9, 8: 10}    # the route tables 0xC0BE5B50 / 59B0 / 5810 (their rows' +0x84 = 7 / 9 / 10)


def route(j, name=ROUTE, fmt=FORMAT_12):
    return next(m for m in j['movie_routes'] if m['name'] == name and m['format_enum'] == fmt)


def base_want(j, r):
    """The stock route's own Want (as test_imx410_profile.want_of builds it)."""
    import test_imx410_profile as T
    return T.want_of(r)


def sized(w, bin_=(1, 1), zoom=(1024, 1024)):
    """ISP_SIZE_RULES §1.1/1.3: rec from the raster, bin and RWZM; act = rec less the 16/10 margin."""
    rec = (((w.window[0] // bin_[0]) * 1024 // zoom[0]) & ~15, ((w.window[1] // bin_[1]) * 1024 // zoom[1]) & ~1)
    act = (rec[0] - 16, rec[1] - 10)
    z = tuple(P.RWZM_UNITY_STOCK if v == 1024 else v for v in zoom)
    return dataclasses.replace(w, rec=rec, act=act, zoom=z, bin=bin_)


# Named experiments; any other name is parsed as `z<H>[x<V>]` and/or `b<H>x<V>` joined by '-', e.g. z2048,
# z3072x1536, b3x3-z1024: the stock route with that record RWZM / bin (the resolution presets of the spec
# §1 are crop width x {1, 2/3, 1/2, 1/3, 1/6} -> Z = 1024, 1536, 2048, 3072, 6144).
NAMED = {'E0': {}, 'E1': {'bin_': (3, 3)}, 'E2': {'zoom': (1536, 1536)}}


# Hypothesis H-shared-bin (10-27, night1 z4096/z6144 before the fix): the CRCT /3 written in the PREVIEW fields
# (+0x58/+0xC4) also divides the record when the preview RWZM (+0x60/+0xD0) is not unity; the record bin enum
# (+0x5C/+0xC8) alone does nothing (E1).  `s<P>` declares a binned record (b3x3) through that path: preview /3 with
# RWZM P.  Proven, it moves into imx410_profile.declare(); until then it lives here, applied after declare().
def parse_exp(name):
    if name in NAMED:
        return NAMED[name]
    kw = {}
    for part in name.split('-'):
        if part[:1] == 's' and part[1:].isdigit():
            kw['shared'] = int(part[1:])
        elif part[:1] == 'd' and part[1:] in ('8', '10', '12', '14'):
            kw['bits'] = int(part[1:])
        elif part[:1] == 'V' and part[1:].isdigit():   # a verified IMX410 custom readout (modes_verified.json index)
            kw['vmode'] = int(part[1:])
        elif part[:1] == 'M' and part[1:].isdigit():   # a matrix case (matrix.py): readout + RES + quality
            kw['matrix'] = int(part[1:])
        elif part[:1] == 'C' and len(part) == 9 and all(ch in '0123456789abcdef' for ch in part[1:]):
            kw['matrix'] = part[1:]                    # the same by its content hash (matrix.case_id)
        elif part[:1] == 'k' and len(part) >= 3 and part[1] in 'hvm' and part[2:].isdigit():
            kw.setdefault('kernel', {})[part[1]] = int(part[2:])   # binfilt: kh0..5 / kv0..5 / km0|1 (soft/std)
        elif part == 'h9':                       # hypothesis: branch C bins H twice (Hbin + Hbin2) -> x9
            kw['h9'] = True
        elif part[:1] in 'zb' and part[1:]:
            v = tuple(int(x) for x in part[1:].split('x'))
            v = v if len(v) == 2 else (v[0], v[0])
            kw['zoom' if part[0] == 'z' else 'bin_'] = v
        else:
            raise SystemExit(f'no experiment {name}')
    return kw


def experiment(j, name):
    rname, _, name = name.rpartition(':')      # "UHD25@8:z2048": the route the camera's menu is on (default FHD30@12)
    rname, _, rbits = rname.partition('@')
    r = route(j, rname or ROUTE, FORMAT_OF_BITS[int(rbits or 12)])
    w = base_want(j, r)
    kw = dict(parse_exp(name))
    shared = kw.pop('shared', None)
    bits = kw.pop('bits', None)
    if shared:
        kw.setdefault('bin_', (3, 3))
    h9 = kw.pop('h9', False)
    kernel = kw.pop('kernel', None)
    mx = kw.pop('matrix', None)
    if mx is not None:                       # everything comes from the case: readout plan + v2 Spec inputs
        c = matrix_case(mx)
        rec = tuple(c['rec'])
        w = dataclasses.replace(w, window=tuple(c['window']), scale=tuple(float(x) for x in c['merge'].split('x')),
                                bin=(1, c['vbin']), zoom=tuple(c['zoom']), bits=bits or c['bits'], rec=rec,
                                act=(rec[0] - 16, rec[1] - 10))
        return r, dataclasses.replace(w, bin=(c.get('hbin', 1), c['vbin'])), (None, kernel)
    vm = kw.pop('vmode', None)
    if vm is not None:                       # the readout is ours: window and sensor merge come from its plan
        vp = vmode_plan(vm)
        w = dataclasses.replace(w, window=(vp['raster_w'], vp['out_h']), scale=tuple(float(x) for x in vp['merge']),
                                bin=(1, 1), zoom=(P.RWZM_UNITY_STOCK, P.RWZM_UNITY_STOCK))
        kw.setdefault('zoom', (1024, 1024))
    w = sized(w, **kw) if kw else w
    if h9:                                        # size as if H were binned 9, declare the bin enum 3 as before
        h = sized(w, bin_=(3 * w.bin[0], w.bin[1]), zoom=tuple(1024 if z == P.RWZM_UNITY_STOCK else z for z in w.zoom))
        w = dataclasses.replace(w, rec=h.rec, act=h.act)
    if bits:
        w = dataclasses.replace(w, bits=bits)       # the plane codes (+0x80/+0x84) follow; the route stays 12-bit
    return r, w, (shared, kernel)


IMXL = ROOT / 'projects' / 'imx410-lab'
VERIFIED = IMXL / 'export' / 'modes_verified.json'


def vmode_entry(n):
    return json.loads(VERIFIED.read_text())['modes'][n]


def vmode_plan(n):
    """readout_cfg.plan for verified mode n, exactly as export_modes built it (id key:CWxCH>OWxOH@FPS, 0 = max)."""
    sys.path[:0] = [str(IMXL), str(IMXL / 'offline')]
    import readout_cfg as RCF
    e = vmode_entry(n)
    key, rest = e['id'].split(':', 1)
    crop, rest = rest.split('>')
    out, fps = rest.split('@')
    cw, ch = map(int, crop.split('x')); ow, oh = map(int, out.split('x'))
    p = RCF.plan(key, cw, ch, ow, oh, float(fps) or None)
    if p['id'] != e['id']:
        raise SystemExit(f'verified mode {n}: plan id {p["id"]} != {e["id"]}')
    p['merge'] = e['merge']
    return p


MATRIX = HERE / 'matrix.json'


def matrix_case(n):
    cs = json.loads(MATRIX.read_text())
    if isinstance(n, int):
        return cs[n]
    hit = [c for c in cs if c.get('id') == n]
    if not hit:
        raise SystemExit(f'no matrix case C{n}')
    return hit[0]


def readout_plan(args):
    """readout_cfg.plan(key, cw, ch, ow, oh, fps) with the merge string vmode installs want."""
    sys.path[:0] = [str(IMXL), str(IMXL / 'offline')]
    import readout_cfg as RCF
    return RCF.plan(*args)


def vmode_install(n, host):
    """smc.create rows of verified mode n (int) or readout_cfg.plan args (list) under the recording mode id `host`
    (vmode.apply: descriptor -> RAM copies)."""
    sys.path[:0] = [str(IMXL), str(IMXL / 'offline')]
    import smc, vmode
    vp = readout_plan(n) if isinstance(n, list) else vmode_plan(n)
    _, rows, _ = smc.create(vp)
    # experiment knob: VMODE_SET='META+0x60=18,...' overrides whole words of the generated rows (one variable at a
    # time against a failing readout); the formula, not this, is what a passing result changes
    for item in filter(None, os.environ.get('VMODE_SET', '').split(',')):
        where, v = item.split('=')
        t, off = where.split('+')
        b = bytearray(rows[t])
        struct.pack_into('<I', b, int(off, 0), int(v, 0))
        rows[t] = type(rows[t])(b) if not isinstance(rows[t], list) else list(b)
    vmode.apply(rows, host, f'{vp["id"]} {os.environ.get("VMODE_SET", "")}'.strip())


def vmode_restore():
    sys.path[:0] = [str(IMXL), str(IMXL / 'offline')]
    import vmode
    if vmode.STATE.exists():
        vmode.restore()


ASPECT_SITES = (0xC0306EA0, 0xC0306EEC)    # XC_DisplayZoomParameter: the only two `mov r0, #3` (16:9) fits
MOV_R0 = 0xE3A00000
ASPECT_TABLE = 0xC0B4CAB8                  # {w, h} pairs: 1 4:3, 2 3:2, 3 16:9, 4 1:1, 5 21:9, 6 7:6, 7 141:100
ASPECT_SLOT = 7                            # A-paper ratio, not used by movie LV: ours, restored after
LCD_W, LCD_H = 1620, 1080                  # STILL's 3:2 template: the whole LCD


def lv_box(a):
    """The LV buffer for record aspect a inside the 1620x1080 LCD, touching one side (user 10-27)."""
    return (LCD_W, round(LCD_W / a) // 2 * 2) if a >= LCD_W / LCD_H else (round(LCD_H * a) // 16 * 16, LCD_H)


def display_diffs(a):
    """The LV fits the record's physical aspect a (one side touches, bars on the other: user 10-27) instead of
    stretching it to 16:9 (open-gate imx410_aspect does it on the product card; the test install lacked it).
    Only the fit enum is a RAM word; the LV buffer itself is lvout's (lvout_rules)."""
    from fractions import Fraction
    if abs(a / (16 / 9) - 1) < 0.005:
        return []
    r = Fraction(a).limit_denominator(1000)
    slot = ASPECT_TABLE + 8 * ASPECT_SLOT
    out = [(slot, 141, r.numerator, 0x2000), (slot + 4, 100, r.denominator, 0x2004)]
    out += [(site, MOV_R0 | 3, MOV_R0 | ASPECT_SLOT, 0x2010 + i) for i, site in enumerate(ASPECT_SITES)]
    return out


# ---- the LV buffer: res-custom's C0437E98 hook (ogc.c ogc_out / og3kout), asm/lvout.S ------------------------------
# XC_LiveViewDispParam::v5 (C0437E98) answers a disp param's descriptor idx; every LV channel is built from it
# (FUN_c0436d98, through v1).  The configurator (0xC375E8DC on 5.02: CINE = +0x28C, its idx 0 = +0x58 = 0xC375E934)
# picks the disp param in XC_LiveViewConfiguratorW71c1::v5 (C043C090) from the LV's route entry:
#   standby  MOV* (C0BE4990)            -> +0x28C  idx0 +0x58 1620x911,  idx2 0xC2F21620 320x180
#   REC      route tables 5810/59B0/5B50 -> +0x460  idx0 0xC2F21494 1920x1080 (static), idx2 0xC2F21620
#   no table (res-custom's own entries)  -> +0x268  idx0 +0x2C 1620x1080, idx2 0xC2F215C8 320x213 (log 0x511)
# res-custom's REC is 3:2 by the last line: its picker answers entries from its own table.  isp_custom keeps the
# stock route entry, so REC gets the 1920x1080 and the LCD shows it 16:9 -- the 10-27 RAM write to 0xC375EA68
# (= +0x18C, disp param +0x3AC's descriptor, not the route's) could not reach it.  The hook covers both states.
LVOUT_SRC = HERE / 'asm' / 'lvout.S'
LVOUT_SITE = (0xC0437E98, 0xE92D4030, 0xE1A05000)      # push {r4, r5, lr}; mov r5, r0
LVOUT_REC = 0xC2F21494                                   # .data (seg1): FUN_c0438338 sets W/H, the rest is the image's
LVOUT_REC_STOCK = [1920, 1080, 0, 0, 1920, 1080, 0, 4, 0x3FC000, 1, 1]
LVOUT_NRULE, LVOUT_RULE, LVOUT_HITS = 3, 80, 72         # lvout.S NRULE / RULE / R_HITS
DET_W, DET_HMAX = 320, 240                               # idx 2 (kind 0x20): cap 76800 = 320 x 240 bytes


def lvout_rules(a):
    """(idx, addr or 0, stock W, H, new W, H) for record aspect a; [] at 16:9.  idx 0: the standby 1620x911 (CINE and
    MAG, by size as ogc_out) and the REC 1920x1080 (by address) both become lv_box(a) -- res-custom's REC buffer is the
    still 1620x1080.  idx 2: 320x180 -> 320 x 320/a as ogc_out's 320x213, only while that fits its 320x240 cap (1:1
    keeps the stock one: no res-custom precedent)."""
    if abs(a / (16 / 9) - 1) < 0.005:
        return []
    tw, th = lv_box(a)
    out = [(0, 0, 1620, 911, tw, th), (0, LVOUT_REC, 1920, 1080, tw, th)]
    if round(DET_W / a) <= DET_HMAX:
        out.append((2, 0, DET_W, 180, DET_W, round(DET_W / a)))
    return out


def lvout_check(p, rules):
    """Refuse unless the site and the REC descriptor read stock (nothing written yet)."""
    site, w0, w1 = LVOUT_SITE
    if p.mem_get(site, 2) != [w0, w1]:
        raise SystemExit(f'lvout: site {site:#x} is not stock: refusing')
    if any(r[1] == LVOUT_REC for r in rules) and p.mem_get(LVOUT_REC, 11) != LVOUT_REC_STOCK:
        raise SystemExit(f'lvout: {LVOUT_REC:#x} is not the stock 1920x1080 descriptor: refusing')


def lvout_code(rules):
    import armasm
    code = bytearray(armasm.assemble(LVOUT_SRC))
    sym = armasm.symbols(LVOUT_SRC)
    if len(rules) > LVOUT_NRULE:
        raise SystemExit(f'lvout: {len(rules)} rules, the hook has {LVOUT_NRULE}')
    for i, r in enumerate(rules):
        struct.pack_into('<6I', code, sym['rules'] + LVOUT_RULE * i, *r)
    return code, sym


def lvout_install(rules):
    """lvout.S (rules patched in) in a cave block, the site pointed at it; the address word goes in before the ldr."""
    import cave
    from putfile import put
    p = _shell()
    lvout_check(p, rules)
    code, sym = lvout_code(rules)
    at = cave.claim('ispc.lvout', len(code))
    put(at, bytes(code), 'lvout')
    site, w0, w1 = LVOUT_SITE
    _set(p, site + 4, at + sym['out'])
    _set(p, site, LDR_PC_M4)
    return {'at': at, 'rules': rules, 'hits': [at + sym['rules'] + LVOUT_RULE * i + LVOUT_HITS for i in range(len(rules))]}


def lvout_restore():
    p = _shell()
    site, w0, w1 = LVOUT_SITE
    _set(p, site, w0)
    _set(p, site + 4, w1)


def lvout_hits(h):
    from putfile import mem_get
    return [mem_get(a)[0] for a in h['hits']]


def standby_diffs(sb):
    """(addr, stock, new, tag) for the six standby profiles' visible width (+0x20) / height (+0x28), as the
    product's GTAB groups write them (open-gate imx410_plan.PREV_PROFILES / prev_width_addrs)."""
    import imx410_plan as PL
    img = IMAGE.read_bytes()
    out = []
    for a_h, a_w in zip(PL.PREV_PROFILES, PL.prev_width_addrs(img)):
        for a, v, stock in ((a_w, sb[0], PL.PREV_STOCK_W), (a_h, sb[1], PL.PREV_STOCK_H)):
            if v != stock:
                out.append((a, stock, v, 0x1000 + (0x20 if a == a_w else 0x28)))   # tag > 0x104: not a row word
    return out


def declare_shared(w, base, p):
    """H-shared-bin: declare() with the preview forced to factor 3P (CRCT /3 + RWZM P on both axes), so every
    preview field -- source, visible, margins, +0x38 -- follows that preview, not branch C's."""
    saved = P.preview_factors, P.record_preview
    P.preview_factors, P.record_preview = (lambda _w: (3 * p, 3 * p)), (lambda _w: False)
    try:
        return P.declare(w, base)
    finally:
        P.preview_factors, P.record_preview = saved


def plan(name):
    cols, j = tables()
    r, w, (shared, kernel) = experiment(j, name)
    row = r['profile_row']
    old = stock(j, row)
    by_id = {pid: rr['words'] for rr in j['rows'] for pid in rr['profile_ids']}
    if shared or FORMULA == 'v1':                 # the shared-bin hypothesis is a v1 experiment (refuted 10-27)
        new = declare_shared(w, by_id[BASE_ID], shared) if shared else P.declare(w, by_id[BASE_ID])
    else:
        new = F.row(spec_of(w), by_id[BASE_ID])       # notes/ISP_FORMULA_V2.md
    diffs = [(cols[4 * i] + 4 * row, old[i], new[i], 4 * i) for i in range(65)
             if new[i] != old[i] and 4 * i != P.ENGINE_FPS]
    # the 6 standby profiles show the recorded area (v2 §3.4), crops included: the readout is centred, so a smaller
    # standby visible is the crop (Jose's S16 716x424 frame does the same); 10-27 mx1 had 111 crops fail without it
    if not shared and FORMULA == 'v2' and os.environ.get('ISPC_STANDBY_FULL_ONLY') != '1':
        diffs += standby_diffs(F.plan(spec_of(w)).standby)
        asp = aspect.dng_aspect(dataclasses.asdict(w))
        diffs += display_diffs(asp)
        lvout = lvout_rules(asp)
    else:
        asp, lvout = None, []
    mx = parse_exp(name.rpartition(':')[2]).get('matrix') if name.rpartition(':')[2] not in NAMED else None
    return {'experiment': name, 'name': matrix_case(mx).get('name') if mx is not None else None,
            'fps': matrix_case(mx).get('fps') if mx is not None else None,
            'formula': FORMULA if not shared else 'v1', 'route': r['name'], 'row': row, 'profile_id': r['profile_id'], 'shared_bin': shared,
            'sensor_mode': r['sensor_mode'], 'vmode': vmode_of(name),
            'want': {k: v for k, v in dataclasses.asdict(w).items()}, 'diffs': diffs,
            'binfilt': binfilt_cfg(w.bin, kernel), 'aspect': asp, 'lvout': lvout}


def binfilt_cfg(bins, kernel):
    """res-custom's SEC_BINFILT packing (ogc_binfilt.c) or 0 = no hook: a horizontal bin needs it (R3, branch C's
    second /3); a vertical-only bin runs stock unless a kernel is asked for (mx1 vbin cases passed without it).
    Kernels default to index 1 = [1 2 1]/4 on both axes."""
    kernel = kernel or {}
    if bins[0] != 3 and not kernel:
        return 0
    kh, kv, km = kernel.get('h', 1), kernel.get('v', 1), kernel.get('m', 0)
    if not (0 <= kh < 6 and 0 <= kv < 6 and km in (0, 1)) or (bins[0] != 3 and bins[1] != 3):
        raise SystemExit(f'binfilt: kernel {kernel} on bins {bins}')
    return 0x800 | (0x200 if bins[0] == 3 else 0) | (0x400 if bins[1] == 3 else 0) | km << 8 | kh | kv << 4


def vmode_of(name):
    kw = parse_exp(name.rpartition(':')[2])
    if 'matrix' in kw:
        return matrix_case(kw['matrix'])['readout']
    return kw.get('vmode')


def show(name):
    p = plan(name)
    print(json.dumps({k: p[k] for k in ('experiment', 'route', 'row', 'profile_id', 'want')}))
    for a, o, n, off in p['diffs']:
        print(f'  +{off:#05x}  {a:#010x}  {o:#010x} -> {n:#010x}')
    print(f'{len(p["diffs"])} words change')
    for i, a, w, h, nw, nh in p['lvout']:
        print(f'  lvout idx {i} {a and hex(a) or "any"} {w}x{h} -> {nw}x{nh}')
    return p


def _shell():
    import putfile
    return putfile


def _set(p, a, v):
    for _ in range(8):
        p.mem_set(a, v)
        if p.mem_get(a)[0] == v:
            return
    raise SystemExit(f'{a:#x} did not take {v:#x}')


def _flush():
    import callfn
    for fn in (0xC000E91C, 0xC000EABC):     # D-cache clean, then I-cache invalidate (display_diffs patch code)
        ok, _ = callfn.call(fn, verbose=False)
        if not ok:
            raise SystemExit(f'cache maintenance {fn:#x} did not return')


CAMSCH1, CS_GET, CS_SET = 0xC0207188, 0xC0207440, 0xC02073B8      # open-gate og3krestore.S lvreload, the same calls
LV_HOLDER, LV_STOP, LV_START = 0xC0423C48, 0xC0423D28, 0xC0423C88


def lv_reload():
    """The LV re-reads the profile tables: CamSch1 state 6 -> MovSigProcess stop -> start -> state back
    (setChangeSensorMode's order without the mode change; og3krestore 09-24 live: 1125 -> 1334, no flicker).
    Without it the standby profiles only took effect at the next magnify. Returns False when the LV isn't running."""
    import callfn
    from putfile import mem_get

    def call(fn, *a):
        ok, v = callfn.call(fn, *a, verbose=False)
        if not ok:
            raise SystemExit(f'lv_reload: {fn:#x} did not return')
        return v
    holder = call(LV_HOLDER)
    obj = mem_get(holder)[0]
    if not obj or not mem_get(obj + 4)[0]:
        return False
    cs = call(CAMSCH1)
    st = call(CS_GET, cs)
    if st != 6:
        call(CS_SET, cs, 6)
    call(LV_STOP, holder)
    call(LV_START, holder)
    if st != 6:
        call(CS_SET, cs, st)
    return True


BINFILT_SRC = HERE / 'asm' / 'binfilt.S'
LDR_PC_M4 = 0xE51FF004                     # ldr pc, [pc, #-4] + address (sup/ix_card.S form)
BINFILT_SITES = {'path': (0xC0325228, 0xE92D00F0, 0xE1A05000),     # CRCT path selector: push {r4-r7}; mov r5, r0
                 'k1': (0xC032DDE8, 0xE5DD0002, 0xE28D1008),       # before blx 0xC0635DB0: ldrb r0,[sp,#2]; add r1,sp,#8
                 'k2': (0xC032DE68, 0xE5DD0003, 0xE28D1008)}       # before blx 0xC0635DC8: ldrb r0,[sp,#3]; add r1,sp,#8


def binfilt_install(cfg):
    """Put binfilt.S (cfg patched in) in a cave block and point the three sites at it; the stock words are checked
    first. The address word goes in before the ldr, so the site never jumps through a stale word."""
    import armasm, cave
    from putfile import put, mem_get
    code = bytearray(armasm.assemble(BINFILT_SRC))
    sym = armasm.symbols(BINFILT_SRC)
    struct.pack_into('<I', code, sym['cfg'], cfg)
    for name, (site, w0, w1) in BINFILT_SITES.items():
        if mem_get(site, 2) != [w0, w1]:
            raise SystemExit(f'binfilt: {name} site {site:#x} is not stock: refusing')
    at = cave.claim('ispc.binfilt', len(code))
    put(at, bytes(code), 'binfilt')
    p = _shell()
    for name, (site, w0, w1) in BINFILT_SITES.items():
        _set(p, site + 4, at + sym[name])
        _set(p, site, LDR_PC_M4)
    return {'at': at, 'cfg': cfg, 'hits': [at + sym['hits_path'], at + sym['hits_k']]}


def binfilt_restore():
    p = _shell()
    for name, (site, w0, w1) in BINFILT_SITES.items():
        _set(p, site, w0)
        _set(p, site + 4, w1)


def binfilt_hits(b):
    from putfile import mem_get
    return [mem_get(a)[0] for a in b['hits']]


def apply(name):
    if STATE.exists():
        raise SystemExit(f'{STATE.name} exists: restore first')
    plan_ = show(name)
    p = _shell()
    if not p.sh('status get is_recording').strip().endswith('0'):
        raise SystemExit('recording: no USB during recording')
    for a, o, n, off in plan_['diffs']:
        cur = p.mem_get(a)[0]
        if cur != o:
            raise SystemExit(f'+{off:#x} at {a:#x} is {cur:#x}, not the stock {o:#x}: refusing')
    if os.environ.get('ISPC_LVOUT', '1') != '1':  # 0: the control, the fit enum only
        plan_['lvout'] = []
    if plan_.get('lvout'):
        lvout_check(p, plan_['lvout'])
    STATE.write_text(json.dumps(plan_))           # first, so a failure half way can still be restored
    if plan_.get('vmode') is not None:
        vmode_install(plan_['vmode'], plan_['sensor_mode'])
    for a, o, n, off in plan_['diffs']:
        _set(p, a, n)
    if plan_.get('binfilt') and os.environ.get('ISPC_BINFILT', '1') == '1':   # 0: the control, no hook
        plan_['binfilt_hook'] = binfilt_install(plan_['binfilt'])
        STATE.write_text(json.dumps(plan_))
    if plan_.get('lvout'):                        # before the LV reload: the rebuilt channels come through it
        plan_['lvout_hook'] = lvout_install(plan_['lvout'])
        STATE.write_text(json.dumps(plan_))
    _flush()
    if os.environ.get('ISPC_LV_RELOAD', '1') == '1':
        print(f'lv reload: {lv_reload()}')
    print(f'applied {name}: {len(plan_["diffs"])} words')


def restore():
    if not STATE.exists():
        print('nothing applied')
        return
    plan_ = json.loads(STATE.read_text())
    p = _shell()
    if not p.sh('status get is_recording').strip().endswith('0'):
        raise SystemExit('recording: no USB during recording')
    hits = binfilt_hits(plan_['binfilt_hook']) if plan_.get('binfilt_hook') else None
    if plan_.get('binfilt'):                      # unconditional: a failed install may have left a site armed
        binfilt_restore()
    lvhits = lvout_hits(plan_['lvout_hook']) if plan_.get('lvout_hook') else None
    if plan_.get('lvout'):                        # the same
        lvout_restore()
    for a, o, n, off in plan_['diffs']:
        _set(p, a, o)
    _flush()
    bad = [hex(a) for a, o, n, off in plan_['diffs'] if p.mem_get(a)[0] != o]
    if bad:
        raise SystemExit(f'not restored: {bad}')
    if plan_.get('vmode') is not None:
        vmode_restore()
    if os.environ.get('ISPC_LV_RELOAD', '1') == '1':
        lv_reload()
    STATE.unlink()
    print(f'restored {plan_["experiment"]}: {len(plan_["diffs"])} words' +
          (f', binfilt hits (path, kernel) {hits}' if hits is not None else '') +
          (f', lvout hits (standby, rec, idx2) {lvhits}' if lvhits is not None else ''))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    for c in ('show', 'apply'):
        s = sub.add_parser(c)
        s.add_argument('exp')
    sub.add_parser('restore')
    a = ap.parse_args()
    {'show': lambda: show(a.exp), 'apply': lambda: apply(a.exp), 'restore': restore}[a.cmd]()


if __name__ == '__main__':
    main()
