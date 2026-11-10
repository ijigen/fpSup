#!/usr/bin/env python3
"""SensorLab "UHD 29.97 12b 1x1" (and the UHD 25p 11-bit sweep recipe) against stock UHD CinemaDNG 12-bit, word by word,
on the real firmware image under unicorn (offline; no camera, no USB).

    cd projects/sensorlab-imx410/validation/20261108-purple-stock-diff
    python3 -B stock_diff.py            # ~1-2 min: writes diff.json, diff.md (tables), mmio-<case>.tsv

What it compares (all through the firmware's own code; ap.c's hooks live for our modes, as on the camera):
  a. the 8 sensor-mode rows (TIM META R28 R38 R14 R68 REG via the firmware's lookups, R10 via FUN_c031ffa0)
  b. the 65-word profile canvas (FUN_c043a158's gather, ap.c's vpro/canvas hooks) for the record and standby pids,
     and FUN_c043a1c8's profile class flags (holder +0x168) that FUN_c03a66b0 reads to decide a REC-start switch
  c. the REC start: SetImgMode_s(standby mode) -> [ImgCtrl message 1: SetImgMode_s(record mode)] -> ContSet_Adr1 with
     the mode current (validation/20261104-first-frame-resync2: the CinemaDNG REC start switches in the ImgCtrl task,
     ContSet_Adr1 never does).  Every MMIO write is logged; the whole 0x3000_0000..0x30FF_FFFF register image is
     snapshot at BUFA1's start (C031CAE0) and diffed, so standby leftovers count too.
Scenarios for SensorLab:  'sw8'  standby stock mode 8, switch to ours at REC start (the 11-03 bus logs: what 12v2 did);
                          'same' standby already in our mode (sby = 1, the MOV/TAB3 answer is our id): no switch;
                          'twin' standby in a twin id (same rows), switch to ours (the TEST build's bit 0).
"""
import collections, json, pathlib, struct, sys
from fractions import Fraction as Fr

HERE = pathlib.Path(__file__).resolve().parent
SL = HERE.parents[1]
sys.path[:0] = [str(SL / 'apply'), str(SL / 'validation/20261103-first-frame-mmio-diff')]
_argv = list(sys.argv)
sys.argv = sys.argv[:1]
import test_apply as T                                      # noqa: E402
import mmio_diff as MD                                      # noqa: E402
sys.argv[:] = _argv

# the product's ap.c has AP_RESYNC 0 (the test unit's default is 1, for ResyncTests): every cam here is product-like
PRODUCT = ('AP_RESYNC=0',)
_mcam_init = MD.MCam.__init__


def _product_init(self, extra=None, **kw):
    kw.setdefault('defines', PRODUCT)
    _mcam_init(self, extra, **kw)


MD.MCam.__init__ = _product_init
from unicorn import UC_HOOK_CODE                            # noqa: E402
from unicorn.arm_const import UC_ARM_REG_R4, UC_ARM_REG_SP  # noqa: E402

UHD30 = (6048, 3402, 3840, 2160, '1x1', 12, Fr(2997, 100))  # Bei's "UHD 29.97 12b 1x1" (defaultPick at 29.97: key "12")
UHD25 = (6048, 3402, 3840, 2160, '1x1', 11, Fr(25))         # the 11-08 sweep recipe: key 3 "12fastW", HMAX 418, VMAX 6890
MD.CASES.update({'sl_uhd30': UHD30, 'sl_uhd25': UHD25, 'stockUHD25': 'UHD25'})
PAIRS = [('stockUHD30', 'sl_uhd30'), ('stockUHD25', 'sl_uhd25')]
TB = ['TIM', 'META', 'R28', 'R38', 'R14', 'R68']
START = 0xC031CAE0
STOCK_STANDBY = (5, 8)                                       # TABS "MOV": {1, pid 5, mode 8}
TWIN = 2                                                     # the TEST build's twin id = id + 2 (232 / 233)


def rows(cam, mode):
    out = {}
    for k, name in enumerate(TB):
        out[name] = list(struct.unpack(f'<{T.TABLES[k][2] // 4}I', cam.row_via_lookup(k, mode)))
    out['REG'] = list(struct.unpack('<162I', cam.reg_via_lookup(mode)))
    out['R10'] = [cam.call(T.LK_R10, T.IMAGER, mode)]
    return out


def canvas(cam, pid):
    holder = MD.HOLDER_AT + 0x800
    cam.mu.mem_write(holder, b'\0' * 0x400)
    cam.put(MD.LVP_AT, 0); cam.put(MD.LVP_AT + 4, 0)
    cam.run(0xC043A158, holder, pid, MD.LVP_AT)
    return list(struct.unpack('<65I', cam.mu.mem_read(holder + 0x5C, 65 * 4))), cam.w(holder + 0x168), cam.w(holder)


def entry(cam, table, key):
    e = cam.call(T.PICKER, 0, table, cam.key(key))
    return list(struct.unpack('<3I', cam.mu.mem_read(e, 12)))


def imgctrl(cam, mode):
    """the image controller task's message 1: SetImgMode_s(FUN_c03133a0(), msg+0x1BC) -- every CINE mode set"""
    msg = T.WORK + 0xF000
    cam.mu.mem_write(msg, b'\0' * 0x1C4)
    cam.put(msg + 0x1BC, mode)
    cam.mu.reg_write(UC_ARM_REG_R4, msg)
    cam.mu.reg_write(UC_ARM_REG_SP, T.STACK - 0x8000)
    cam.mu.emu_start(0xC030D160, 0xC030D16C, **T.emu_cap(200_000_000))
    if cam.error:
        raise cam.error


def setup_cam(cam, sel=None):
    """MD.setup's tail for a prepared MCam (TEST builds: the caller made it with its defines and attached rd)"""
    if sel is not None:
        assert cam.apply(sel) == T.AP_OK, cam.status()
        st = cam.status()
        cam.pid, cam.mode = st['pid'], st['mode_id']
    cam.sel = sel
    cam.put(0xC343B680, 1)
    cam.run(0xC03255B0, T.IMAGER, T.DESC)
    holder = MD.HOLDER_AT
    cam.mu.mem_write(holder, b'\0' * 0x400)
    cam.put(MD.LVP_AT, 0); cam.put(MD.LVP_AT + 4, 0)
    cam.run(0xC043A158, holder, cam.pid, MD.LVP_AT)
    cam.put(T.LV_MGR + 8, holder)
    cam.put(T.LV_MGR + 4, MD.LVP_AT - 0x48)
    return cam


REC_SITE = 0xC0379180                                        # FUN_c0378a50: bl FUN_c030cf98 (the TEST builds hook it)


def bl_target(site, w):
    off = ((w & 0xFFFFFF) ^ 0x800000) - 0x800000
    return site + 8 + 4 * off


def rec_seq(cam, standby, via_site=False):
    """standby SetImgMode_s(standby) and the REC start: the ImgCtrl switch when the mode differs, then ContSet_Adr1
    (via_site: through C0379180's BL -- the TEST hook, then the real FUN_c030cf98).  -> (phases, regs at BUFA1 start,
    sensor writes per phase); cam.switched"""
    snap = {}

    def at_start(uc, a, sz, d):
        snap['regs'] = bytes(uc.mem_read(0x30000000, 0x01000000))
    h = cam.mu.hook_add(UC_HOOK_CODE, at_start, begin=START, end=START)
    for g in MD.GUARDS_DONE:
        cam.put(g, 1)
    cam.put(MD.CUR_MODE, 0)
    cam.run(0xC031A0F8)
    cam.put(0xC343A78C, 2)
    cam.mmio.clear(); cam.sensor = []
    imgctrl(cam, standby)
    assert cam.w(MD.CUR_MODE) == standby
    ph = {'standby': list(cam.mmio)}
    sens = {'standby': list(cam.sensor)}
    cam.mmio.clear(); cam.sensor = []
    switched = cam.w(MD.CUR_MODE) != cam.mode
    if switched:                                             # ImgCtrl message 1 (C030D160..C030D16C), the real code
        imgctrl(cam, cam.mode)
        assert cam.w(MD.CUR_MODE) == cam.mode
    ph['switch'] = list(cam.mmio)
    sens['switch'] = list(cam.sensor)
    cam.mmio.clear(); cam.sensor = []
    if via_site:                                             # FUN_c0378a50's call: the 0x1B0 descriptor (+0x14 mode)
        src = T.WORK + 0xF800
        cam.mu.mem_write(src, b'\0' * 0x1B0)
        cam.put(src + 0x14, cam.mode); cam.put(src + 0x18, 0); cam.put(src + 0x20, 0); cam.put(src + 0x30, MD.DEST)
        cam.put(0xC343A96C, 1)                               # FUN_c031be20's guard: the Cont ctx (CONT_CTX) built
        cam.run(bl_target(REC_SITE, cam.w(REC_SITE)), 0x11, src, 0x33)
    else:
        d = MD.DESCBUF                                       # FUN_c030cf98's ContSet_Adr1 call, the mode current
        cam.mu.mem_write(d, b'\0' * 0x1C0)
        cam.put(d + 0x1C, cam.mode); cam.put(d + 0x20, 0); cam.put(d + 0x28, 0); cam.put(d + 0x38, MD.DEST)
        cam.run(MD.CONTSET, MD.CONT_CTX, d)
    ph['contset'] = list(cam.mmio)
    sens['contset'] = list(cam.sensor)
    cam.mu.hook_del(h)
    assert 'regs' in snap, 'BUFA1 start not reached'
    cam.switched = switched
    return ph, snap['regs'], sens


def rec_start(case, scenario):
    """(cam, mmio of each phase, register image at BUFA1's start, sensor writes in order)"""
    cam = MD.setup(case)
    T.ff_window(cam)
    stock = cam.sel is None
    if stock:
        assert cam.init() == T.AP_OK                         # the hooks armed, no slot: stock answers everywhere
    standby = {'sw8': STOCK_STANDBY[1], 'same': cam.mode, 'twin': cam.mode + TWIN}[scenario] if not stock else 8
    ph, regs, sens = rec_seq(cam, standby)
    return cam, ph, regs, sens


def regimage(b, written):
    return {a: struct.unpack_from('<I', b, a - 0x30000000)[0] for a in written}


def main():
    out = {}
    for stock_case, sl_case in PAIRS:
        res = {}
        cams = {}
        for case in (stock_case, sl_case):
            cams[case] = MD.setup(case)
        s, o = cams[stock_case], cams[sl_case]
        st = o.status()
        res['ids'] = dict(stock=dict(pid=s.pid, mode=s.mode), sl=dict(pid=o.pid, mode=o.mode, spid=st['pid'] + 2,
                          sel=o.sel))
        res['entries'] = dict(stock_tab3=entry(s, T.TAB3, stock_case.replace('stock', '')),
                              stock_mov=entry(s, T.TABS, 'MOV'),
                              sl_tab3=entry(o, T.TAB3, stock_case.replace('stock', '')), sl_mov=entry(o, T.TABS, 'MOV'))
        # a. rows
        rs, ro = rows(s, s.mode), rows(o, o.mode)
        res['rows'] = {k: [(i, rs[k][i], ro[k][i]) for i in range(len(rs[k])) if rs[k][i] != ro[k][i] and
                           not (k != 'R10' and i == 0)] for k in rs}
        res['rows_full'] = dict(stock=rs, sl=ro)
        # b. canvases (record and standby) + class flags
        cs, fs, ps = canvas(s, s.pid)
        co, fo, po = canvas(o, o.pid)
        sb_s, sbf_s, _ = canvas(s, STOCK_STANDBY[0])
        sb_o, sbf_o, _ = canvas(o, st['pid'] + 2)
        res['canvas_rec'] = [(4 * i, cs[i], co[i]) for i in range(65) if cs[i] != co[i]]
        res['canvas_sb'] = [(4 * i, sb_s[i], sb_o[i]) for i in range(65) if sb_s[i] != sb_o[i]]
        res['flags'] = dict(stock_rec=fs, sl_rec=fo, stock_sb=sbf_s, sl_sb=sbf_o)
        res['canvas_full'] = dict(stock_rec=cs, sl_rec=co, stock_sb=sb_s, sl_sb=sb_o)
        # c. the REC start
        runs = {}
        for name, case, sc in ((stock_case, stock_case, None), (sl_case + ':sw8', sl_case, 'sw8'),
                               (sl_case + ':same', sl_case, 'same')):
            cam, ph, regs, sens = rec_start(case, sc or 'sw8')
            runs[name] = (cam, ph, regs, sens)
            with open(HERE / f'mmio-{name.replace(":", "-")}.tsv', 'w') as f:
                f.write('phase\tseq\tpc\tfunc\taddr\tvalue\n')
                for p, ws in ph.items():
                    for seq, pc, a, sz, v, _ in ws:
                        f.write(f'{p}\t{seq}\t{pc:#010x}\t{MD.owner(pc)}\t{a:#010x}\t{v:#010x}\n')
        allw = set()
        for name, (cam, ph, regs, sens) in runs.items():
            for p in ph.values():
                allw |= {a & ~3 for _, _, a, *_r in p}
        imgs = {n: regimage(r[2], allw) for n, r in runs.items()}
        names = list(runs)
        res['rec_regs'] = [(a, *[imgs[n][a] for n in names]) for a in sorted(allw)
                           if len({imgs[n][a] for n in names}) > 1]
        res['rec_names'] = names
        res['switched'] = {n: r[0].switched for n, r in runs.items()}
        res['contset_writes'] = {n: len(r[1]['contset']) for n, r in runs.items()}
        res['contset_funcs'] = {n: collections.Counter(MD.owner(pc) for _, pc, *_r in r[1]['contset']).most_common()
                                for n, r in runs.items()}
        res['phase_writes'] = {n: {p: len(w) for p, w in r[1].items()} for n, r in runs.items()}

        def sensfinal(ws):
            d = {}
            for a, v in ws:
                d[a] = v
            return d
        sf = {n: sensfinal(r[3]['standby'] + r[3]['switch'] + r[3]['contset']) for n, r in runs.items()}
        keys = sorted(set().union(*[set(v) for v in sf.values()]))
        res['sensor_final'] = [(a, *[sf[n].get(a) for n in names]) for a in keys if len({sf[n].get(a) for n in names}) > 1]
        res['sensor_counts'] = {n: {p: len(w) for p, w in r[3].items()} for n, r in runs.items()}
        out[stock_case] = res
    (HERE / 'diff.json').write_text(json.dumps(out, indent=1, default=str) + '\n')
    return out


if __name__ == '__main__':
    o = main()
    for k, r in o.items():
        print(k, r['ids'], r['entries'], r['flags'], 'switched', r['switched'], 'contset writes', r['contset_writes'])
        print(' rows differ:', {t: len(v) for t, v in r['rows'].items()})
        print(' canvas rec differ', len(r['canvas_rec']), 'sb', len(r['canvas_sb']), 'regs differ', len(r['rec_regs']),
              'sensor differ', len(r['sensor_final']))
