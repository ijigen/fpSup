#!/usr/bin/env python3
"""Run the Python formulas once and emit everything data-driven core.c needs as core_data.h (const rodata only).

    python3 -B export_core.py [--out core_data.h]

Sources (read-only imports, never edited here):
  projects/imx410-lab/readout_cfg.py   READOUTS / BY_KEY (per-key table) + constants
  projects/imx410-lab/smc.py           fit(): the per-field rule set (exact / const / cat / lin / byte / nearest),
                                       BASE_X0 / BASE_Y0 / VADD / R10_OF_CLS, the stock attrs 'nearest' needs
  projects/imx410-lab/offline/mode_rules.py  DEFECT_DIR / DEFECT_FALLBACK / K_* (the 'exact' formulas are ported
                                       by hand in core.c; a new EXACT field makes core.c return CORE_E_EXACT)
  projects/imx410-lab/readout_export.py      REG_ORDER, row strides
  projects/imx410-lab/bins.py          diff('8', '139'): the fast Family A set
  projects/isp-lab/host/quality.py     QUAL order / AD / CRCT bin order / NEAR_UNITY / WIDEN for core_qualities(),
                                       isp_formula.LINE_PX_PER_CLK (R11) for core_line_hmax(), SRC_MAX_H (R12)
The C evaluates the exported rules; it never fits anything.
"""
import argparse, hashlib, pathlib, re, sys
from fractions import Fraction

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
IMXL = ROOT / 'projects' / 'imx410-lab'
ISPH = ROOT / 'projects' / 'isp-lab' / 'host'
sys.path[:0] = [str(IMXL), str(IMXL / 'offline'), str(ISPH)]
import readout_cfg as C          # noqa: E402
import isp_formula as F          # noqa: E402
import quality as Q              # noqa: E402
import smc                       # noqa: E402
import mode_rules as MR          # noqa: E402
import readout_export as X       # noqa: E402

KINDS = {'exact': 0, 'const': 1, 'cat': 2, 'lin': 3, 'byte': 4, 'nearest': 5}
TABS = ['TIM', 'META', 'R28', 'R38', 'R14', 'R68', 'REG']
NONE8 = 0xFF


def attr_enum():
    """attribute order = core.h's enum core_attr (single source)"""
    txt = (HERE / 'core.h').read_text()
    body = re.search(r'enum core_attr \{(.*?)\};', txt, re.S).group(1)
    names = [n.strip() for n in body.replace('\n', ' ').split(',') if n.strip()]
    assert names[-1] == 'A_N'
    return [n[2:].lower() for n in names[:-1]]


class ExportError(RuntimeError):
    pass


def collect():
    """everything the C needs, as plain Python data (test_core uses it too)"""
    attrs_order = attr_enum()
    AI = {n: i for i, n in enumerate(attrs_order)}
    modes, attrs, fields, rules = smc.fit()
    d = {}
    # ---------------- readout_cfg
    keys = [r['key'] for r in C.READOUTS]
    if len(set(keys)) != len(keys):
        raise ExportError('duplicate readout keys')
    pairs = []
    ro = []
    for r in C.READOUTS:
        ex = list(r.get('extra', []))
        st = len(pairs); pairs += ex
        fm = sorted(r['fmt'].items())
        if len(fm) > 4:
            raise ExportError(f'{r["key"]}: more than 4 formats')
        cls = r.get('cls') or {'14': 16, '12': 17, '12fast': 17, '12fastW': 17}.get(r['key'], X.CLS.get(r['key']))
        ro.append(dict(key=r['key'], mh=r['mh'], mv=r['mv'], bits=r['bits'], donor=r['donor'], hmin=r['hmin'],
                       over=r['over'], centre=-1 if r['centre'] is None else r['centre'], v016=r['v016'],
                       v016_min=-1 if r['v016_min'] is None else r['v016_min'], fast_set=int(bool(r.get('fast_set'))),
                       new=int(bool(r.get('new'))), y0=r.get('y0') or 0, rows_full=r.get('rows_full') or 0,
                       cls=cls or 0, fmt=fm, extra=(st, len(ex))))
        for nm in ('mh', 'mv'):
            if r[nm] <= 0:
                raise ExportError('bad merge')
    d['ro'] = ro
    d['pairs'] = pairs
    if C.V3_SKIP_ON and len(C.V3_WIN) > 4:
        raise ExportError('V3_WIN too long')
    d['const'] = dict(SENSOR_H=C.SENSOR_H, WIN_TOP=C.WIN_TOP, WIN_BOTTOM=C.WIN_BOTTOM, VMAX_MAX=C.VMAX_MAX,
                      V3_MARGIN=C.V3_MARGIN, V3_SKIP=C.V3_SKIP, V3_SKIP_ON=int(bool(C.V3_SKIP_ON)),
                      V3_FULL_SKIP=C.V3_FULL_SKIP, LINE_SHORT=C.LINE_SHORT)
    if Fraction(C.CLK) != int(C.CLK):
        raise ExportError('CLK not an integer')
    d['const']['CLK'] = int(C.CLK)
    d['v3win'] = list(C.V3_WIN)
    # ---------------- quality.py (the enumeration) + R11
    num, den = F.LINE_PX_PER_CLK
    if F.min_line_clk(num) != den or F.min_line_clk(num + 1) != den + 1:
        raise ExportError('isp_formula.min_line_clk is no longer ceil(w * den / num): port core_line_hmax')
    if F.min_line_clk(F.WIDE14_W + 1, 14) != max(F.WIDE14_HMAX, F.min_line_clk(F.WIDE14_W + 1)) \
            or F.min_line_clk(F.WIDE14_W, 14) != F.min_line_clk(F.WIDE14_W):
        raise ExportError('isp_formula R15 is no longer "14 bit wider than WIDE14_W: at least WIDE14_HMAX": port it')
    d['const'].update(WIDE14_W=F.WIDE14_W, WIDE14_HMAX=F.WIDE14_HMAX)                          # R15
    d['const'].update(LINE_PX_NUM=num, LINE_PX_DEN=den, Q_NEAR_UNITY=Q.NEAR_UNITY, Q_WIDEN=Q.WIDEN,
                      Q_SENSOR_W=Q.SENSOR_W, SRC_MAX_H=F.SRC_MAX_H,      # R12: preview source rows
                      Q_MARGIN_W=F.MARGIN[0], Q_MARGIN_H=F.MARGIN[1])     # quality.visible_of: the stock margin
    d['qual'] = [(keys.index(k), b, int(Q.ad_of(k, b))) for k, b in Q.QUAL]
    d['qbins'] = list(Q.BINS)
    if sorted(d['qbins']) != [(1, 1), (1, 3), (3, 1), (3, 3)]:
        raise ExportError(f'quality.BINS changed: {Q.BINS}')
    # ---------------- smc
    d['base_x0'] = dict(smc.BASE_X0); d['base_y0'] = dict(smc.BASE_Y0); d['vadd'] = dict(smc.VADD)
    d['r10'] = dict(smc.R10_OF_CLS)
    d['reg_order'] = list(X.REG_ORDER)
    stride = dict(smc.STRIDE)
    want = {'TIM': 0x20, 'META': 100, 'R28': 0x28, 'R38': 0x38, 'R14': 0x14, 'R68': 0x68, 'REG': 0x288}
    if stride != want or len(X.REG_ORDER) != 161:
        raise ExportError(f'row strides changed: {stride}, {len(X.REG_ORDER)} REG registers (update core.h)')
    if smc.TABLES != TABS:
        raise ExportError(f'smc.TABLES changed: {smc.TABLES}')
    import bins
    d['fast'] = list(bins.diff('8', '139'))
    # stock attrs for 'nearest'
    d['modes'] = list(modes)
    d['stock'] = [(attrs[m]['cls'], attrs[m]['width'], attrs[m]['height']) for m in modes]
    rl, cat, cat_ent, lin, lin_ent, near = [], [], [], [], [], []
    for f, (kind, r) in smc.fit()[3].items():
        t, o = f
        ti = TABS.index(t)
        off = 4 * (1 + X.REG_ORDER.index(o)) if t == 'REG' else o
        k = KINDS[kind]
        if kind == 'exact':
            arg = 0
        elif kind == 'const':
            arg = r & 0xFFFFFFFF
        elif kind == 'cat':
            ks, look = r
            if not 1 <= len(ks) <= 2:
                raise ExportError(f'{f}: cat on {len(ks)} keys')
            arg = len(cat)
            cat.append((AI[ks[0]], AI[ks[1]] if len(ks) > 1 else NONE8, len(cat_ent), len(look)))
            for kt, v in look.items():
                cat_ent.append((kt[0], kt[1] if len(kt) > 1 else 0, v & 0xFFFFFFFF))
        elif kind == 'lin':
            xn, grp, rule = r
            arg = len(lin)
            lin.append((AI[xn], AI[grp] if grp else NONE8, len(lin_ent), len(rule)))
            for g, (sl, b) in rule.items():
                sl, b = Fraction(sl), Fraction(b)
                e = (g, sl.numerator, sl.denominator, b.numerator, b.denominator)
                if any(abs(x) >= 1 << 31 for x in e):
                    raise ExportError(f'{f}: linear rule does not fit int32')
                lin_ent.append(e)
        elif kind == 'byte':
            xn, sh = r
            arg = AI[xn] | sh << 8
        elif kind == 'nearest':
            if list(r) != list(modes):
                raise ExportError(f'{f}: nearest values not in stock mode order')
            arg = len(near)
            near.append([r[m] & 0xFFFFFFFF for m in modes])
        rl.append((ti, k, off, arg, f))
    d.update(rules=rl, cat=cat, cat_ent=cat_ent, lin=lin, lin_ent=lin_ent, near=near)
    # ---------------- mode_rules data the exact formulas use (mode = -1 for a new mode: no HAND, no v33/zoom/rep)
    if -1 in MR.V33_IDS or -1 in MR.ZOOM_IDS or -1 in MR.DEFECT_DIR.values() or any(-1 in h for h in MR.HAND.values()):
        raise ExportError('mode -1 appears in mode_rules data: core.c assumes a new mode is no stock mode')
    d['defect_dir'] = [k + (v,) for k, v in MR.DEFECT_DIR.items()]
    d['defect_fb'] = [k + (v,) for k, v in MR.DEFECT_FALLBACK.items()]
    d['k'] = {n: Fraction(repr(getattr(MR, n))) for n in ('K_EVAL_W', 'K_EVAL_H', 'K_AF_W', 'K_AF_H')}
    return d


def emit(d):
    o = []
    w = o.append
    w('/* GENERATED by export_core.py from the current Python formulas -- do not edit. */')
    w('#ifndef SENSORLAB_CORE_DATA_H\n#define SENSORLAB_CORE_DATA_H')
    for k, v in d['const'].items():
        w(f'#define CD_{k} {v}')
    w(f'#define CD_N_KEYS {len(d["ro"])}')
    w('typedef struct { int16_t mh, mv, bits, donor, hmin, over, centre, v016, v016_min, fast_set, is_new, y0,'
      ' rows_full, cls; uint16_t nfmt, fmt_w[4], fmt_code[4], extra_start, extra_n; } cd_ro_t;')
    w('static const cd_ro_t cd_ro[CD_N_KEYS] = {')
    for r in d['ro']:
        fw = [x for x, _ in r['fmt']] + [0] * (4 - len(r['fmt']))
        fc = [y for _, y in r['fmt']] + [0] * (4 - len(r['fmt']))
        w(f'  {{{r["mh"]}, {r["mv"]}, {r["bits"]}, {r["donor"]}, {r["hmin"]}, {r["over"]}, {r["centre"]}, {r["v016"]}, '
          f'{r["v016_min"]}, {r["fast_set"]}, {r["new"]}, {r["y0"]}, {r["rows_full"]}, {r["cls"]}, {len(r["fmt"])}, '
          f'{{{", ".join(map(str, fw))}}}, {{{", ".join(map(str, fc))}}}, {r["extra"][0]}, {r["extra"][1]}}},  /* {r["key"]} */')
    w('};')
    w('static const char cd_key_name[CD_N_KEYS][16] = {' + ', '.join(f'"{r["key"]}"' for r in d['ro']) + '};')
    def arr(name, typ, rows, per=8):
        w(f'static const {typ} {name}[{max(1, len(rows))}] = {{')
        if not rows:
            w('  {0}' if '{' in typ or typ.startswith('cd_') else '  0')
        for i in range(0, len(rows), per):
            w('  ' + ' '.join(f'{x},' for x in rows[i:i + per]))
        w('};')
    w('typedef struct { uint16_t reg, val; } cd_pair_t;')
    w(f'#define CD_N_PAIRS {len(d["pairs"])}')
    arr('cd_pairs', 'cd_pair_t', [f'{{0x{a:04X}, 0x{v:02X}}}' for a, v in d['pairs']])
    w(f'#define CD_N_V3WIN {len(d["v3win"])}')
    arr('cd_v3win', 'cd_pair_t', [f'{{0x{a:04X}, 0x{v:02X}}}' for a, v in d['v3win']])
    w('typedef struct { uint8_t key, bits, ad; } cd_qual_t;   /* quality.QUAL order: readout, ISP bits, AD */')
    w(f'#define CD_N_QUAL {len(d["qual"])}')
    arr('cd_qual', 'cd_qual_t', ['{%d, %d, %d}' % q for q in d['qual']], 8)
    w(f'#define CD_N_QBINS {len(d["qbins"])}')
    w('static const uint8_t cd_qbins[CD_N_QBINS][2] = {' + ', '.join('{%d, %d}' % b for b in d['qbins']) + '};   /* (hbin, vbin) */')
    # smc constants
    def lut(name, dct, lo, hi):
        vals = [dct.get(i, -1) for i in range(lo, hi + 1)]
        w(f'#define {name.upper()}_LO {lo}\n#define {name.upper()}_HI {hi}')
        arr(name, 'int16_t', [str(v) for v in vals], 16)
    lut('cd_base_x0', d['base_x0'], 0, max(d['base_x0']))
    lut('cd_base_y0', d['base_y0'], min(d['base_y0']), max(d['base_y0']))
    lut('cd_vadd', d['vadd'], 0, max(d['vadd']))
    lut('cd_r10', d['r10'], min(d['r10']), max(d['r10']))
    w(f'#define CD_N_REG {len(d["reg_order"])}')
    arr('cd_reg_order', 'uint16_t', [f'0x{r:04X}' for r in d['reg_order']], 12)
    w(f'#define CD_N_FAST {len(d["fast"])}')
    arr('cd_fast', 'cd_pair_t', [f'{{0x{a:04X}, 0x{v:02X}}}' for a, v in d['fast']])
    # rules
    w('enum { RK_EXACT, RK_CONST, RK_CAT, RK_LIN, RK_BYTE, RK_NEAREST };')
    w('typedef struct { uint8_t tab, kind; uint16_t off; uint32_t arg; } cd_rule_t;')
    w(f'#define CD_N_RULES {len(d["rules"])}')
    w(f'static const cd_rule_t cd_rules[CD_N_RULES] = {{')
    for ti, k, off, arg, f in d['rules']:
        w(f'  {{{ti}, {k}, 0x{off:03X}, 0x{arg:X}u}},  /* {f[0]} {f[1]:#x} */')
    w('};')
    w('typedef struct { uint8_t k0, k1; uint16_t start, n; } cd_cat_t;')
    w('typedef struct { int32_t k0, k1; uint32_t v; } cd_cat_ent_t;')
    w('typedef struct { uint8_t x, g; uint16_t start, n; } cd_lin_t;')
    w('typedef struct { int32_t g, p, q, r, s; } cd_lin_ent_t;')
    w(f'#define CD_N_CAT {len(d["cat"])}')
    arr('cd_cat', 'cd_cat_t', ['{%d, %d, %d, %d}' % c for c in d['cat']], 6)
    arr('cd_cat_ent', 'cd_cat_ent_t', ['{%d, %d, 0x%Xu}' % c for c in d['cat_ent']], 4)
    w(f'#define CD_N_LIN {len(d["lin"])}')
    arr('cd_lin', 'cd_lin_t', ['{%d, %d, %d, %d}' % c for c in d['lin']], 6)
    arr('cd_lin_ent', 'cd_lin_ent_t', ['{%d, %d, %d, %d, %d}' % c for c in d['lin_ent']], 4)
    w(f'#define CD_N_STOCK {len(d["stock"])}')
    w('typedef struct { int16_t cls, w, h; } cd_stock_t;')
    arr('cd_stock', 'cd_stock_t', ['{%d, %d, %d}' % s for s in d['stock']], 6)
    w(f'#define CD_N_NEAR {len(d["near"])}')
    w(f'static const uint32_t cd_near[{max(1, len(d["near"]))}][CD_N_STOCK] = {{')
    for v in d['near'] or [[0] * len(d['stock'])]:
        w('  {' + ', '.join(f'0x{x:X}u' for x in v) + '},')
    w('};')
    # mode_rules data
    w('typedef struct { int16_t hb, vb, w, h, id; } cd_defect_t;')
    w(f'#define CD_N_DEFECT {len(d["defect_dir"])}')
    arr('cd_defect', 'cd_defect_t', ['{%d, %d, %d, %d, %d}' % x for x in d['defect_dir']], 4)
    w(f'#define CD_N_DEFECT_FB {len(d["defect_fb"])}')
    arr('cd_defect_fb', 'cd_defect_t', ['{%d, %d, 0, 0, %d}' % x for x in d['defect_fb']], 4)
    for n, fr in d['k'].items():
        w(f'#define CD_{n}_NUM {fr.numerator}\n#define CD_{n}_DEN {fr.denominator}')
    w('#endif')
    return '\n'.join(o) + '\n'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=str(HERE / 'core_data.h'))
    a = ap.parse_args()
    d = collect()
    txt = emit(d)
    pathlib.Path(a.out).write_text(txt)
    from collections import Counter
    kinds = Counter(k for _, k, *_ in d['rules'])
    inv = {v: k for k, v in KINDS.items()}
    print(f'{a.out}: {len(d["ro"])} readout keys, {len(d["rules"])} rules '
          f'({", ".join(f"{inv[k]} {n}" for k, n in sorted(kinds.items()))}), sha256 {hashlib.sha256(txt.encode()).hexdigest()[:12]}')


if __name__ == '__main__':
    main()
