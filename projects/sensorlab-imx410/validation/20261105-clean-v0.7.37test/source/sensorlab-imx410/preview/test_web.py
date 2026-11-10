"""Cross-architecture parity of the public site's real C engine, without HTTP.

Both native and wasm compile in separate private temporary directories. The
browser adapter executes under Node's actual WebAssembly runtime; no formula
implementation is mocked. No camera, SD, shared dylib or package dependency.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_web
import server

sys.path.insert(0, str(HERE.parent / 'tools' / 'qr'))
from qr_v5_reference import decode_modules

NODE = r'''
const fs = require('fs'), vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
vm.runInThisContext(fs.readFileSync(input.folder + '/wasm_backend.js', 'utf8'));
(async () => {
  const bytes = fs.readFileSync(input.folder + '/sensorlab.wasm');
  const manifest = JSON.parse(fs.readFileSync(input.folder + '/wasm_info.json', 'utf8'));
  const backend = await SensorLabWasm.create(bytes, manifest);
  const results = [];
  for (const request of input.requests) {
    try { results.push(await backend[request.method](...request.args)); }
    catch (error) { results.push({error: error.message}); }
  }
  const module = await WebAssembly.compile(bytes);
  console.log(JSON.stringify({results, imports: WebAssembly.Module.imports(module), info: await backend.info()}));
})().catch(error => {console.error(error); process.exit(1)});
'''


class WebEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='sensorlab-test-web-')
        cls.manifest = build_web.build(cls.temp.name)
        cls.native = server.Backend()
        if cls.manifest['info']['core_fingerprint'] != cls.native.info['core_fingerprint']:
            raise RuntimeError('Core sources changed while preparing cross-architecture parity tests')

    @classmethod
    def tearDownClass(cls):
        cls.native.close()
        cls.temp.cleanup()

    def wasm(self, requests):
        result = subprocess.run(['node', '-e', NODE], input=json.dumps({'folder': self.temp.name, 'requests': requests}),
                                capture_output=True, text=True, timeout=60, check=True)
        return json.loads(result.stdout)

    def test_all_presets_match_native_and_saved_data(self):
        saved = json.loads((HERE / 'fps_data.js').read_text().split('const FPSDATA = ', 1)[1].rstrip(';\n'))
        dc = {name: dimensions for dimensions, name in self.native.dc_names.items()}
        cells = [(*dc[key.split(':')[0]], *map(int, key.split(':')[1].split('x'))) for key in saved['cases']]
        got = self.wasm([{'method': 'qualities', 'args': cell} for cell in cells])
        self.assertEqual(got['imports'], [], 'No external API, filesystem or host runtime imports')
        self.assertEqual(got['info']['core_fingerprint'], self.native.info['core_fingerprint'])
        self.assertEqual(got['info']['version'], self.native.version)
        for cell, result in zip(cells, got['results']):
            with self.subTest(cell=cell):
                self.assertEqual(result, self.native.qualities(*cell))
                self.assertEqual(result['case'], saved['cases'][result['key']])
        self.assertEqual(len(cells), 45)
        self.assertEqual(sum(len(r['case']) for r in got['results']), 837)

    def test_custom_and_boundary_dimensions(self):
        cells = [(5040, 3402, 1680, 1134), (2096, 1240, 320, 196),
                 (6000, 3374, 2000, 1124), (5904, 3320, 2000, 1124),
                 (6032, 3402, 2000, 1134), (6016, 3402, 2000, 1134),
                 (256, 144, 256, 144), (6048, 4040, 6048, 4040), (6048, 4040, 256, 144)]
        got = self.wasm([{'method': 'qualities', 'args': cell} for cell in cells])['results']
        for cell, result in zip(cells, got):
            with self.subTest(cell=cell):
                self.assertEqual(result, self.native.qualities(*cell))
        self.assertNotEqual(got[4]['key'], got[5]['key'])

    def test_qr_matches_native_and_independent_decoder(self):
        codes = ['A' * 37, '0123456789abcdefghijklmnopqrstuvwxyz_', '_-Az09' * 6 + 'A']
        got = self.wasm([{'method': 'qr', 'args': [code]} for code in codes])['results']
        for code, result in zip(codes, got):
            with self.subTest(code=code):
                self.assertEqual(result, self.native.qr(code))
                decoded, mask = decode_modules(result['modules'])
                self.assertEqual(decoded.decode(), self.native.qr_url + code)
                self.assertIn(mask, range(8))

    def test_bad_inputs_are_rejected(self):
        bad_cells = [(6049, 3402, 2016, 1134), (6048, 3403, 2016, 1134),
                     (256, 144, 512, 144), (6048, 4040, 2016.5, 144), (6048, 4040, 256, 143)]
        bad_codes = ['', 'A' * 36, 'A' * 38, 'A' * 36 + '+']
        requests = [{'method': 'qualities', 'args': cell} for cell in bad_cells]
        requests += [{'method': 'qr', 'args': [code]} for code in bad_codes]
        for result in self.wasm(requests)['results']:
            self.assertIn('error', result)

    def test_readout_plan_matches_native_and_drives_the_diagram(self):
        """What the sensor sends (fmt_w x rows, windowed or full) comes from the C core; the diagram's readout box is
        that plan and the DC crop box is scw x sch inside it, for every preset and some custom DCs."""
        saved = json.loads((HERE / 'fps_data.js').read_text().split('const FPSDATA = ', 1)[1].rstrip(';\n'))
        dc = {name: dimensions for dimensions, name in self.native.dc_names.items()}
        cells = [(*dc[key.split(':')[0]], *map(int, key.split(':')[1].split('x'))) for key in saved['cases']]
        cells += [(5040, 3402, 1680, 1134), (2096, 1240, 320, 196), (6000, 3374, 2000, 1124), (6048, 2000, 2016, 1000),
                  (4192, 2358, 1920, 1080), (3968, 2232, 1984, 1116)]
        got = self.wasm([{'method': 'readout', 'args': cell} for cell in cells] +
                        [{'method': 'qualities', 'args': cell} for cell in cells])['results']
        readouts, qualities = got[:len(cells)], got[len(cells):]
        native_widths = {6064, 5073, 4176, 4016, 3032, 2016}
        pairs = []
        for cell, ro, q in zip(cells, readouts, qualities):
            with self.subTest(cell=cell):
                self.assertEqual(ro, self.native.readout(*cell))
                self.assertEqual(len(ro['readout']), len(q['case']))
                for (_hm, _lo, _name, d), r in zip(q['case'], ro['readout']):
                    self.assertIsNotNone(r, d['key'])
                    self.assertEqual((r['mh'], r['mv']), (d['mh'], d['mv']))
                    self.assertIn(r['fmt_w'], native_widths)
                    self.assertGreaterEqual(1000 * r['fmt_w'] * r['mh'], 995 * min(d['scw'], 6048), d['key'])
                    self.assertEqual(bool(r['windowed']), d['sch'] < 4040 - 2 * d['mv'], d['key'])
                    pairs.append([d, r, cell])
        # DC 5040 on a 1x1 readout whose only native line is 6064: the sensor sends 6064, the receiver cuts 5040.
        dc5040 = [(d, r) for d, r, cell in pairs if cell[:2] == (5040, 3402) and d['key'] in ('12', '14')]
        self.assertTrue(dc5040)
        for d, r in dc5040:
            self.assertEqual(r['fmt_w'], 6064)
            self.assertIn(d['scw'], (5040, 5056))           # the core's R2 retry may widen the crop by 16
        # The page's diagram from these plans (site_page.js frameLayout, run in Node).
        page = (HERE / 'dcres.html').read_text()
        logic = page.split('<script>\n', 1)[1].split('// ---- render', 1)[0]
        source = (HERE / 'fps_data.js').read_text() + (HERE / 'site_page.js').read_text() + logic + r"""
const input = JSON.parse(require('fs').readFileSync(0, 'utf8')), bad = [];
for (const [d, r] of input) for (const narrow of [true, false]) {
  const f = {ver: 1, dcw: d.scw, dch: d.sch, rw: d.rec[0], rh: d.rec[1], fps: 30, vmax: 2000, hmax: 900, ad: 1, mh: d.mh,
    mv: d.mv, hbin: d.hbin, vbin: d.vbin, key: 1, kh: 1, kv: 1, km: 0, rcustom: 0, visw: d.vis[0], vish: d.vis[1], rs: 1000,
    fmt: 0, rescustom: 0, scw: d.scw, sch: d.sch, ww: d.win[0], wh: d.win[1]};
  const L = SiteRecipe.frameLayout(SiteRecipe.describe(f), narrow, {...r, win_top: 56}), s = L.scale, R = L.rects;
  const want = (v, parent) => v > parent - 6 ? Math.max(2, parent - 6) : Math.max(2, v);
  const ro = [want(r.fmt_w * r.mh * s, R[0].w), want(r.out_h * r.mv * s, R[0].h)];
  const crop = [want(d.scw * s, R[1].w), want(d.sch * s, R[1].h)];
  if (Math.abs(R[1].w - ro[0]) > 1 || Math.abs(R[1].h - ro[1]) > 1) bad.push(['readout box', d.key, R[1].w, ro[0], R[1].h, ro[1]]);
  if (Math.abs(R[2].w - crop[0]) > 1 || Math.abs(R[2].h - crop[1]) > 1) bad.push(['crop box', d.key, R[2].w, crop[0], R[2].h, crop[1]]);
  if (!L.labels[1].text.includes(`${r.fmt_w * r.mh}×${r.out_h * r.mv}`) || !L.labels[2].text.includes(`${d.scw}×${d.sch}`)) bad.push(['labels', d.key]);
  if (L.dashed.some(x => x.from < 2)) bad.push(['dashed on a crop step', d.key]);
}
console.log(JSON.stringify(bad.slice(0, 5)));"""
        result = subprocess.run(['node', '-e', source], input=json.dumps([[d, r] for d, r, _c in pairs]),
                                capture_output=True, text=True, timeout=120, check=True)
        self.assertEqual(json.loads(result.stdout), [])
        self.assertGreater(len(pairs), 850)

    def test_manifest_hash_matches_binary(self):
        binary = (Path(self.temp.name) / 'sensorlab.wasm').read_bytes()
        self.assertEqual(hashlib.sha256(binary).hexdigest(), self.manifest['wasm_sha256'])
        self.assertLess(len(binary), 100_000)


if __name__ == '__main__':
    unittest.main()
