"""Offline-only checks for the preview's real C backend and HTTP contract.

Compiles once in a private temporary directory. No hardware, ARM emulator,
shared host libraries, camera builds, or network beyond loopback are used.
"""
import http.client
import json
from pathlib import Path
import sys
import threading
import unittest
from urllib.parse import urlencode

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import server
import gen_fps

sys.path.insert(0, str(HERE.parent / 'tools' / 'qr'))
from qr_v5_reference import decode_modules


class PreviewBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend = server.Backend()
        cls.http = server.make_server(cls.backend, 0)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join(timeout=5)
        cls.backend.close()

    def request(self, path, headers=None, method='GET'):
        connection = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=5)
        try:
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            return response.status, {k.lower(): v for k, v in response.getheaders()}, response.read()
        finally:
            connection.close()

    def get_json(self, path, headers=None):
        status, response_headers, body = self.request(path, headers)
        self.assertIn('application/json', response_headers['content-type'])
        self.assertEqual(response_headers['cache-control'], 'no-store')
        return status, json.loads(body)

    def test_all_saved_presets_match_current_c(self):
        old = json.loads((HERE / 'fps_data.js').read_text().split('const FPSDATA = ', 1)[1].rstrip(';\n'))
        crops = {name: dimensions for dimensions, name in self.backend.dc_names.items()}
        for key, expected in old['cases'].items():
            with self.subTest(key=key):
                name, dimensions = key.split(':')
                rw, rh = map(int, dimensions.split('x'))
                result = self.backend.qualities(*crops[name], rw, rh)
                self.assertEqual(result['key'], key)
                self.assertEqual(result['case'], expected)
                self.assertEqual(result['nominal'], old['nominal'][key])
                self.assertEqual(result['clk'], old['clk'])
                self.assertEqual(result['vmax_max'], old['vmax_max'])

    def test_custom_cells_match_python_without_key_collisions(self):
        cells = ((5040, 3402, 1680, 1134), (2096, 1240, 320, 196),
                 (6000, 3374, 2000, 1124), (5904, 3320, 2000, 1124))
        results = []
        for cell in cells:
            with self.subTest(cell=cell):
                status, result = self.get_json('/api/qualities?' + urlencode(dict(zip(('dcw', 'dch', 'rw', 'rh'), cell))))
                self.assertEqual(status, 200)
                self.assertEqual(result['case'], gen_fps.case(*cell, .02))
                results.append(result)
        self.assertEqual([len(r['case']) for r in results], [36, 58, 36, 20])
        self.assertEqual(results[-2]['key'], 'C6000x3374:2000x1124')
        self.assertEqual(results[-1]['key'], 'C5904x3320:2000x1124')
        self.assertNotEqual(results[-2]['key'], results[-1]['key'])

    def test_bad_dimensions_and_queries_are_rejected(self):
        valid = {'dcw': 6048, 'dch': 3402, 'rw': 2016, 'rh': 1134}
        for changes in ({'dcw': 6049}, {'dch': 3403}, {'rw': 2017}, {'rh': 143}, {'dcw': 256, 'rw': 512},
                        {'dcw': -16}, {'dch': 4042}, {'rw': '1e3'}, {'rh': ''}):
            with self.subTest(changes=changes):
                status, body = self.get_json('/api/qualities?' + urlencode({**valid, **changes}))
                self.assertEqual(status, 400)
                self.assertIn('error', body)
        query = urlencode(valid)
        for suffix in ('&rw=2016', '&extra=1'):
            self.assertEqual(self.get_json('/api/qualities?' + query + suffix)[0], 400)
        self.assertEqual(self.get_json('/api/qualities?dcw=6048')[0], 400)

    def test_qr_matches_independent_pristine_decoder(self):
        for code in ('A' * 37, '0123456789abcdefghijklmnopqrstuvwxyz_', '_-Az09' * 6 + 'A'):
            with self.subTest(code=code):
                status, result = self.get_json('/api/qr?' + urlencode({'code': code}))
                self.assertEqual(status, 200)
                self.assertEqual(result['size'], 37)
                decoded, mask = decode_modules(result['modules'])
                self.assertEqual(decoded.decode(), self.backend.qr_url + code)
                self.assertIn(mask, range(8))
        damaged = [row[:] for row in result['modules']]
        damaged[36][36] ^= 1
        with self.assertRaises(ValueError):
            decode_modules(damaged)

    def test_readout_route(self):
        status, data = self.get_json('/api/readout?' + urlencode({'dcw': 5040, 'dch': 3402, 'rw': 1680, 'rh': 1134}))
        self.assertEqual(status, 200)
        self.assertEqual(data, self.backend.readout(5040, 3402, 1680, 1134))
        self.assertTrue(data['readout'] and all(r['fmt_w'] for r in data['readout']))
        self.assertEqual(self.get_json('/api/readout?dcw=1')[0], 400)

    def test_invalid_qr_payloads_are_rejected(self):
        for code in ('', 'A' * 36, 'A' * 38, 'A' * 36 + '+', 'A' * 36 + '中'):
            with self.subTest(code=code):
                self.assertEqual(self.get_json('/api/qr?' + urlencode({'code': code}))[0], 400)
        self.assertEqual(self.get_json('/api/qr')[0], 400)

    def test_source_info_and_static_root(self):
        status, info = self.get_json('/api/info')
        self.assertEqual(status, 200)
        self.assertEqual(info['version'], self.backend.version)
        self.assertRegex(info['fingerprint'], '^[0-9a-f]{64}$')
        self.assertRegex(info['core_fingerprint'], '^[0-9a-f]{64}$')
        self.assertTrue(info['offline'])
        status, headers, html = self.request('/')
        self.assertEqual(status, 200)
        self.assertIn('text/html', headers['content-type'])
        self.assertEqual(html, (HERE / 'dcres.html').read_bytes())
        for path in ('/../qs/slqs.c', '/%2e%2e/qs/slqs.c', '/api/unknown'):
            self.assertEqual(self.get_json(path)[0], 404)

    def test_loopback_origin_and_get_only(self):
        for headers in ({'Origin': 'https://example.com'}, {'Origin': 'null'}, {'Host': 'example.com'},
                        {'Origin': 'http://127.0.0.1:1'}):
            with self.subTest(headers=headers):
                self.assertEqual(self.get_json('/api/info', headers)[0], 403)
        self.assertEqual(self.get_json('/api/info', {'Origin': f'http://localhost:{self.http.server_port}'})[0], 200)
        self.assertEqual(self.request('/api/info', method='POST')[0], 405)


if __name__ == '__main__':
    unittest.main()
