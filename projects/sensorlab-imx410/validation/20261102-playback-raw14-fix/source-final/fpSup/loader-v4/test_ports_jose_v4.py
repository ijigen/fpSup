#!/usr/bin/env python3
"""Jose Hurtado's Desqueeze and Tap to Zoom as ports_jose.py makes them, under
the real v4 core with its fpSup-page hooks (unicorn).

    python3 -B -m unittest test_ports_jose_v4

His code runs as he shipped it -- launcher, menu glue, tasks, INI reader --
against the reference image and a fake UI with SHOOT 2 / SHOOT 4 (MainB2,
MainB4) as the camera lays them out.  Checked: both load, claim no string
site, install the picture CHAIN in file-name order (DSQZ under TAPZ) and
their other sites; each row's page equals uishare's reference applier except
the string fields, and each of those is an id the core resolves to the
reference text; his variables and tasks exist; power-off puts every site back.
Not checked: his image processing, touch, the INI write, the real UI.
"""
import pathlib, struct, sys, unittest

HERE = pathlib.Path(__file__).resolve().parent
FPSUP = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(FPSUP / 'uishare'))
import ports_jose as J                                   # noqa: E402
import names_v4 as N                                     # noqa: E402
import test_ui_v4 as U                                   # noqa: E402
import test_v4 as T                                      # noqa: E402
from ui import fpui                                      # noqa: E402

F6 = U.F6
NBU_BASE = 0xC18C0460
LOOKUP = 0xC05DB418                                      # C05DB419 (Thumb): (registry, name, &desc)
PICTURE = 0xC02E828C
STRINGS = (0xC05E5B58, 0xC05E61C8, 0xC05E61E0)
PAGES = {'MainB2': 0x76FF04, 'MainB4': 0x7A6B6B}         # their OP_PAGE stock offsets
GUI = F6.FAKE + 0xA000                                   # our screens, entries, descriptors
_built = {}
DSQZ, TAPZ = N.file_name('DSQZ'), N.file_name('TAPZ')
SID = {DSQZ: 'DSQZ', TAPZ: 'TAPZ'}


def built():
    if not _built:
        _built.update(J.build())
    return _built


class JoseCamera(U.Cam):
    """test_ui_v4's camera (the v4 core's fake UI) plus SHOOT 2 / SHOOT 4: two
    screens by name, the reader's runtime page entries, the variable lookup."""
    def __init__(self, files, dirs):
        files.setdefault('\\fpSup\\LOAD.LOG', b'')
        super().__init__(files, dirs)
        screens, entries, names = GUI, GUI + 0x400, GUI + 0x800
        self.descs, self.desc_next = {}, GUI + 0x1000
        for i, name in enumerate(PAGES):
            s = screens + 0x40 * i
            self.mu.mem_write(names + 0x20 * i, name.encode() + b'\0')
            self.put(s + 0x04, F6.APP)
            self.put(s + 0x08, names + 0x20 * i)
            self.put(s + 0x24, F6.READER)
            self.put(F6.SCREENS + 4 * (1 + i), s)
            self.put(entries + 44 * i + 4, names + 0x20 * i)
            self.put(entries + 44 * i + 8, PAGES[name])
        self.put(F6.READER + 0xA8, len(PAGES))
        self.put(F6.READER + 0xAC, entries)
        self.put(F6.APP + 0x888, GUI + 0x3000)           # the registry (lookup is ours)
        self.entries = entries
        self.mu.mem_write(LOOKUP, struct.pack('<H', 0x4770))
        self.by_addr[LOOKUP] = 'LOOKUP'

    def _hook(self, mu, addr, size, data):
        if addr == F6.VAR_REGISTER:                      # descriptors he can read
            r1, r2 = self.r(T.T3.UC_ARM_REG_R1), self.r(T.T3.UC_ARM_REG_R2)
            for i in range(r1):
                ty, name, first = struct.unpack('<3I', bytes(mu.mem_read(r2 + 12 * i, 12)))
                d = self.desc_next
                self.desc_next += 16
                mu.mem_write(d, struct.pack('<3I', ty, name, first))
                self.descs[self.cstr(name)] = d
        if addr == LOOKUP:
            name = self.cstr(self.r(T.T3.UC_ARM_REG_R1))
            self.put(self.r(T.T3.UC_ARM_REG_R2), self.descs.get(name, 0))
            return self._ret(0)
        return super()._hook(mu, addr, size, data)

    def page(self, name):
        i = list(PAGES).index(name)
        return (NBU_BASE + self.w(self.entries + 44 * i + 8)) & 0xFFFFFFFF


def ref_text(pool, off):
    if off < len(pool.stock):
        return pool.stock[off:pool.stock.index(b'\0', off)].decode()
    for base, texts in pool.layers:
        if base <= off < base + len(texts):
            return texts[off - base]
    raise KeyError(hex(off))


class JosePortTests(unittest.TestCase):
    def boot(self, *names):
        sups = [(n, built()[n][0]) for n in names]
        cam = JoseCamera(*T.card(*sups, loader=U.built()['vbin']))
        cam.boot()
        self.assertIsNone(cam.error)
        return cam

    def stock(self, cam, a):
        return struct.unpack_from('<I', cam.img, a - 0xC0000000)[0]

    def test_headers(self):
        for n, (data, facts) in built().items():
            h = struct.unpack_from('<12I', data)
            self.assertEqual((h[0], h[1], h[4], h[8]), (T.B.SL4_MAGIC, 48, 0x30, T.B.SL_F_CACHED_OK), n)
            self.assertEqual(data[h[11]:data.index(b'\0', h[11])].decode(), N.display(SID[n]))   # names_v4
            self.assertEqual(facts['display'], N.display(SID[n]))
            v3 = J.JOSE[SID[n]]['src'].read_bytes()
            body, old = data[48:48 + len(v3) - 32], v3[32:]
            diff = [o for o in range(len(old)) if body[o] != old[o]]
            j = J.JOSE[SID[n]]
            touched = {j['count_at'] - 32 + k for k in range(4)} | {j['bl_at'] - 32 + k for k in range(4)} | \
                      {j['name_at'] - 32 + k for k in range(len(j['name']))} | \
                      {j['fpui_at'] - 32 + 12 + k for k in range(4)}      # + "Tap To Zoom" (names_v4), its FNV
            self.assertTrue(set(diff) <= touched, (n, [hex(o) for o in diff]))   # only the two words, the title

    def test_both_load_and_chain_without_the_string_sites(self):
        cam = self.boot(DSQZ, TAPZ)
        loaded = T.blocks(cam)
        self.assertEqual(sorted(loaded), [DSQZ, TAPZ])
        for n, at in loaded.items():
            self.assertTrue(at >= 0xC0000000 and at % 64 == 0, (n, hex(at)))
        claims = {t: k for c, _, k, t in cam.loadlog() if c == T.CODES['LOADED'] and t != 'LOADER.BIN'}
        self.assertEqual(claims, {DSQZ: 10 + 14, TAPZ: 3})      # DSQZ: + its 14 ranges
        journaled = [a for a, _, _ in cam.journal()]
        self.assertNotEqual(cam.w(PICTURE), self.stock(cam, PICTURE))
        for n in (DSQZ, TAPZ):
            self.assertIn(n, [t for c, _, _, t in cam.loadlog() if c == T.CODES['LOADED']])
        self.assertEqual(sum(1 for a in journaled if a in STRINGS), 3)        # the core's, once each
        cam.power_off()
        for a in [PICTURE, 0xC0CFCCDC, 0xC0CFD55C, 0xC2EF6294, 0xC0303FBC, *STRINGS]:
            self.assertEqual(cam.w(a), self.stock(cam, a), hex(a))

    def check_row(self, name, page):
        cam = self.boot(name)
        self.assertIn(name, T.blocks(cam))
        p = cam.page(page)
        self.assertTrue(p >= 0xC0000000, f'{page} not switched to a cached copy: {p:#x}')
        length = cam.w((p & ~3) - 128 + 12)
        off, ln = {DSQZ: (0x6A40, 0xC720), TAPZ: (0x4410, 0x78CC)}[name]
        block = built()[name][0][48 + off - 32:48 + off - 32 + ln]      # his block, our title (names_v4)
        stock_off = PAGES[page]
        a = fpui.decode(block)[1][0][1]
        pages = {page: fpui.PageCopy(cam.img[NBU_BASE - 0xC0000000 + stock_off:][:a[2]], a[2], 1)}
        pool = fpui.Strings(cam.img[0x18C0474:0x18C0474 + 176152])
        fpui.apply(block, pages, pool)
        ref, ours = bytes(pages[page].data), bytes(cam.mu.mem_read(p, length))
        self.assertEqual(len(ours), len(ref))
        ui = T.blocks(cam)[name] + 48 + off - 32
        o, fields = 0, 0
        while o < len(ref):
            if ours[o] == ref[o]:
                o += 1
                continue
            end = o
            while end < len(ref) and ours[end] != ref[end]:
                end += 1
            for at in range(max(0, end - 4), o + 1):
                sid = struct.unpack_from('>I', ours, at)[0]
                try:
                    want = ref_text(pool, struct.unpack_from('>I', ref, at)[0])
                except (KeyError, ValueError):
                    continue
                if 0x40000000 <= sid < 0x80000000:
                    break
            else:
                self.fail(f'{page} +{o:#x}: {ref[o:end].hex()} -> {ours[o:end].hex()}')
            self.assertTrue(ui <= sid + 0x80000000 < ui + ln, f'+{at:#x}')
            got = cam.call(0xC05E5B58, r0=0, r1=sid, thumb=True)[0]       # the core resolves it
            self.assertEqual(cam.cstr(got), want, f'+{at:#x}')
            fields += 1
            o = at + 4
        self.assertGreater(fields, 0)
        return cam

    def test_desqueeze_row_on_shoot_2(self):
        cam = self.check_row(DSQZ, 'MainB2')
        self.assertIn('MV_fpDesqueeze', cam.descs)
        self.assertEqual(len(cam.tasks), 1)

    def test_tap_to_zoom_row_on_shoot_4(self):
        cam = self.check_row(TAPZ, 'MainB4')
        self.assertIn('MV_fpZoom', cam.descs)
        self.assertEqual(len(cam.tasks), 1)


if __name__ == '__main__':
    unittest.main()
