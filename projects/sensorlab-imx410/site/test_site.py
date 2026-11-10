"""Offline checks of the merged SensorLab page: the decoder/details JavaScript against the camera reference,
and the publication copy (index.html = simulator + QR landing page, simulator/ = redirect) against build_site.py.
Browser behaviour (hash <-> state, languages, frame diagram) is in preview/test_client.js."""
import ast
import json
import pathlib
import random
import re
import subprocess
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'qs'))
import test_slqs as Q
import build_site as B

HTML = B.SOURCE.read_text()
LOGIC = HTML.split('<script>\n', 1)[1].split('// ---- render', 1)[0]
SITE = (B.PREVIEW / 'site_page.js').read_text()
DATA = (B.PREVIEW / 'fps_data.js').read_text()
DEMO = dict(ver=1, dcw=6048, dch=3402, rw=2016, rh=1134, fps=8, vmax=1201,
            hmax=1000, ad=1, mh=2, mv=3, hbin=1, vbin=1, key=5, kh=1, kv=1,
            km=0, rcustom=0, visw=2000, vish=1124, rs=7370, fmt=0,
            rescustom=0, scw=6048, sch=3402, ww=3024, wh=1134)


def pack(f):
    return Q.qr_pack([f[name] for name, _width in Q.QR_FIELDS])


def js(expression, value=None):
    # The page's own scripts (spec logic + site_page.js) in Node, without a DOM.
    source = DATA + '\n' + SITE + '\n' + LOGIC
    source += '\nconst input=JSON.parse(require("fs").readFileSync(0,"utf8"));\nconst R=SiteRecipe;\n'
    source += 'console.log(JSON.stringify(' + expression + '));'
    result = subprocess.run(['node', '-e', source], input=json.dumps(value),
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


class Site(unittest.TestCase):
    def test_schema_and_random_decode_match_camera_reference(self):
        fields = js('QR_FIELDS')
        self.assertEqual(fields, [list(f) for f in Q.QR_FIELDS])
        widths = re.search(r'QF_W\[N_QF\] = \{([^}]+)', (Q.HERE / 'slqs.c').read_text())[1]
        self.assertEqual([w for _n, w in fields], [int(w.strip()) for w in widths.split(',')])
        self.assertEqual(sum(w for _n, w in fields), 213)
        rng = random.Random(410)
        vectors = []
        for _ in range(300):
            f = {n: rng.randrange(1, 1 << w) for n, w in Q.QR_FIELDS}
            f.update(ver=1, ad=rng.randrange(3), fps=rng.randrange(31), kh=rng.randrange(6), kv=rng.randrange(6))
            vectors.append(f)
        codes = [pack(f) for f in vectors]
        self.assertTrue(all(len(c) == 37 for c in codes))
        self.assertEqual(js('input.map(c=>R.decodeRecipe(c))', codes), [{'fields': f} for f in vectors])
        # The page's encoder (the one that writes the address) equals the camera reference too.
        self.assertEqual(js('input.map(f=>qrPack(f))', vectors), codes)
        self.assertEqual(js("R.crc8([...Buffer.from('123456789')].flatMap(n=>Array.from({length:8},(_,i)=>n>>(7-i)&1)))"), 0xF4)

    def test_crc_canonical_pad_version_and_invalid_input(self):
        code = pack(DEMO)
        self.assertEqual(js('R.decodeRecipe(input)', code), {'fields': DEMO})
        damaged = []
        for bit in range(221):
            i, shift = divmod(bit, 6)
            damaged.append(code[:i] + Q.B64U[Q.B64U.index(code[i]) ^ (1 << (5 - shift))] + code[i+1:])
        errors = js('input.map(c=>R.decodeRecipe(c).error)', damaged)
        self.assertTrue(all(e in ('crc', 'version', 'field') for e in errors), set(errors))
        pad = code[:-1] + Q.B64U[Q.B64U.index(code[-1]) ^ 1]
        self.assertEqual(js('R.decodeRecipe(input).error', pad), 'pad')
        cases = [(code[:-1], 'length'), (code + 'A', 'length'), ('', 'length'), (code[:-1] + '=', 'chars'),
                 (code[:-1] + '/', 'chars')]
        for k, value in [('ver', 2), ('ver', 0)]:
            cases.append((pack(dict(DEMO, **{k: value})), 'version'))
        for k, value in [('ad', 3), ('fps', 31), ('kh', 6), ('kv', 7), ('hmax', 0), ('vmax', 0), ('ww', 0),
                         ('hbin', 0), ('mv', 0), ('visw', 0)]:
            cases.append((pack(dict(DEMO, **{k: value})), 'field'))
        self.assertEqual(js('input.map(c=>R.decodeRecipe(c).error)', [c for c, _e in cases]), [e for _c, e in cases])

    def test_all_reference_recipes_preserve_zoom_recorded_bits_and_raster(self):
        data = json.loads(DATA.split('const FPSDATA = ', 1)[1].rstrip(';\n'))
        dcs = {n: (w, h) for n, w, h in ast.literal_eval(re.search(r'const DCS = (\[.*?\]);', LOGIC)[1])}
        cases = []
        for cell, recipes in data['cases'].items():
            dc, wh = cell.split(':'); rw, rh = map(int, wh.split('x')); dcw, dch = dcs[dc]
            for hm, lo, _name, r in recipes:
                f = dict(DEMO, dcw=dcw, dch=dch, rw=rw, rh=rh, hmax=hm, vmax=lo,
                         ad={11: 0, 12: 1, 14: 2}[r['ad']], mh=r['mh'], mv=r['mv'],
                         hbin=r['hbin'], vbin=r['vbin'], scw=r['scw'], sch=r['sch'],
                         ww=r['win'][0], wh=r['win'][1], visw=r['vis'][0], vish=r['vis'][1])
                bits = 14 if r['ad'] == 14 and r['zoom'] == [1024, 1024] and r['hbin'] in (1, 2) and r['vbin'] == 1 else 12   # D11 (4)
                cases.append((pack(f), [r['zoom'], bits, r['rec']], cell, r['key']))
        results = js('input.map(c=>{const m=R.describe(R.decodeRecipe(c).fields);return [m.zoom,m.recordBits,[m.recW,m.recH]]})',
                     [c[0] for c in cases])
        self.assertEqual(len(cases), 930)   # 0.0.6test: 57 preset cells (÷6 - 10 rows, 1x2 / 1x3); 0.0.5test 823
        for actual, (_code, expected, cell, key) in zip(results, cases):
            self.assertEqual(actual, expected, (cell, key))

    def test_data_rate_uses_recorded_depth_and_actual_raster(self):
        f = dict(DEMO, ad=2, mh=1, mv=3, ww=6048, wh=1134, visw=2000, vish=1114)
        m, rate = js('(()=>{const m=R.describe(R.decodeRecipe(input).fields);return [m,R.dataRates(m)]})()', pack(f))
        self.assertEqual(m['adBits'], 14)
        self.assertEqual(m['recordBits'], 12)
        pixels = 2016 * 1124
        self.assertAlmostEqual(rate['u'], m['fpsExact'] * (pixels * 12 / 8 + 79184) / 1e6)
        self.assertAlmostEqual(rate['ll'], m['fpsExact'] * (pixels * 5 / 8 + 81000) / 1e6)

    def test_english_default_and_complete_translations(self):
        self.assertIn('<html lang="en">', HTML)
        self.assertEqual(js("R.lang()"), 'en')
        source = SITE.split('const I18N = {', 1)[1].split('\nlet LANG', 1)[0]
        for block in re.split(r'\n  (?:en|hans|hant): \{', source)[1:]:
            names = re.findall(r'(?:^|[{,\n])\s*([A-Za-z]\w*): ', block.split('fields: {', 1)[0])
            self.assertEqual(len(names), len(set(names)), sorted(n for n in set(names) if names.count(n) > 1))
        keys = js('Object.fromEntries(Object.entries(R.I18N).map(([l,t])=>[l,Object.keys(t).sort()]))')
        self.assertEqual(keys['hans'], keys['en'])
        self.assertEqual(keys['hant'], keys['en'])
        used = set(re.findall(r'data-th?="([^"]+)"', HTML))
        self.assertTrue(used <= set(keys['en']), used - set(keys['en']))
        fields = js('Object.fromEntries(Object.entries(R.I18N).map(([l,t])=>[l,Object.keys(t.fields)]))')
        for lang in ('en', 'hans', 'hant'):
            self.assertEqual(fields[lang], [n for n, _w in Q.QR_FIELDS])

    def test_local_publication_copy_is_the_generated_output(self):
        files = B.publication_files()
        out = B.DESTINATION.parent
        self.assertEqual(B.DESTINATION.relative_to(Q.ROOT).as_posix(), 'fpSup/sensor_lab_imx410/index.html')
        for name, contents in files.items():
            with self.subTest(name=name):
                self.assertEqual((out / name).read_bytes(), contents)
        for name in B.OBSOLETE:
            self.assertFalse((out / name).exists(), name)
        index = files['index.html'].decode()
        for src in re.findall(r'<script src="([^"]+)"', index):
            self.assertIn(src, files)
        self.assertIn('assets/menu_lock_qs.png', files)
        self.assertEqual(json.loads(files['wasm_info.json'])['info']['qr_url'], Q.QR_URL)
        self.assertEqual(Q.QR_URL, 'https://ijigen.github.io/fpSup/sensor_lab_imx410/#')

    def test_layout_simulator_right_on_desktop_after_the_diagram_on_phones(self):
        self.assertIn('grid-template-areas:"head sim" "details sim" "foot foot"', HTML)
        narrow = HTML.split('@media (max-width:899px)', 1)[1].split('</style>', 1)[0]
        order = {sel: int(n) for sel, n in re.findall(r'(main > header|#details > \.frame-card|main > \.sim|'
                                                     r'#details > \.grid2|#details > section:last-child|main > \.page-foot) \{ order:(\d)', narrow)}
        self.assertEqual(sorted(order, key=order.get), ['main > header', '#details > .frame-card', 'main > .sim',
                                                        '#details > .grid2', '#details > section:last-child', 'main > .page-foot'])
        self.assertIn('class="card frame-card"', HTML)

    def test_qs_panel_value_text_contrast(self):
        """White value text over the lighter QS panel, on the brightest scene pixel (white line art at .75 over the
        gradient's light end), keeps WCAG contrast >= 4.5 (the screen's colours are the same in light and dark mode)."""
        alpha = float(re.search(r'#cam \{ --tile:rgba\(28,30,33,([.0-9]+)\)', HTML)[1])
        self.assertLessEqual(alpha, 0.65, 'lighter than the camera panel (.86)')
        def lum(rgb):
            c = [v / 255 for v in rgb]
            c = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
            return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
        light_end = (0xc0, 0x9a, 0x70)
        scene = [0.75 * 255 + 0.25 * v for v in light_end]          # the white line art over it
        under = [alpha * t + (1 - alpha) * v for t, v in zip((28, 30, 33), scene)]
        ratio = (lum((255, 255, 255)) + 0.05) / (lum(under) + 0.05)
        self.assertGreaterEqual(ratio, 4.5, ratio)
        self.assertIn('text-shadow', HTML.split('.tile .t, .tile .v, .tile .s', 1)[1].split('}', 1)[0])

    def test_simulator_alias_redirects_with_the_hash(self):
        page = B.REDIRECT
        self.assertIn("location.replace('../' + location.hash)", page)
        self.assertIn('<meta http-equiv="refresh" content="0; url=../">', page)
        self.assertIn('<a href="../">', page)
        # Run the redirect script as a browser would.
        script = page.split('<script>', 1)[1].split('</script>', 1)[0]
        got = subprocess.run(['node', '-e', 'let to;const location={hash:"#abc",replace:u=>to=u};' + script +
                              ';console.log(to)'], capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(got, '../#abc')


if __name__ == '__main__':
    unittest.main()
