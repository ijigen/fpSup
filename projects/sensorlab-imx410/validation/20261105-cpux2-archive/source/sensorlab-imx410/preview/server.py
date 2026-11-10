#!/usr/bin/env python3
"""Offline SensorLab preview: current camera C formulas, served on loopback only.

No camera, USB, SD, ARM emulator, shared build directory, or package dependency.
The compiler writes only to one private temporary directory for this process.
"""
import argparse
import ast
import ctypes
from functools import lru_cache, partial
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import parse_qs, unquote, urlsplit

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
QFIELDS = ("mh mv ad hbin vbin key bits cw ch sw sh hmax rows capped hm vmin_lo vmin vmax fps_milli "
           "win_w win_h zh zv rec_w rec_h path seq lines vis_w vis_h rs_us").split()


class Quality(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int32) for name in QFIELDS]


def definition(source, name):
    """Read a simple constant from current camera source; fail if its shape changes."""
    match = re.search(r'^#define\s+' + re.escape(name) + r'\s+([^\n]+)', source, re.M)
    if not match:
        raise RuntimeError(f'Camera constant {name} was not found')
    return match.group(1).split('/*', 1)[0].strip()


def integer_definition(source, name):
    return int(definition(source, name).rstrip('uUlL'), 0)


def table(source, name):
    match = re.search(r'\b' + re.escape(name) + r'\[[^=]+?=\s*\{([^}]+)\}', source)
    if not match:
        raise RuntimeError(f'Camera table {name} was not found')
    return json.loads('[' + match.group(1) + ']')


def fingerprint(files):
    h = hashlib.sha256()
    for name, contents in sorted(files.items()):
        h.update(name.encode() + b'\0' + contents + b'\0')
    return h.hexdigest()


class Backend:
    def __init__(self):
        self._temp = tempfile.TemporaryDirectory(prefix='sensorlab-preview-')
        try:
            self._build()
        except BaseException:
            self.close()
            raise

    def _build(self):
        core = {name: (PROJECT / 'core' / name).read_bytes() for name in ('core.c', 'core.h', 'core_data.h')}
        qs = (PROJECT / 'qs' / 'slqs.c').read_bytes()
        build = (PROJECT / 'qs' / 'build_slqs.py').read_bytes()
        bridge = (HERE / 'host_bridge.c').read_bytes()
        source = qs.decode()
        versions = [node.value.value for node in ast.parse(build).body
                    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'VERSION' for t in node.targets)
                    and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)]
        if len(versions) != 1:
            raise RuntimeError('Cannot read source VERSION from build_slqs.py')
        self.version = versions[0]
        self.constants = {name: integer_definition(source, name)
                          for name in ('WMIN', 'HMIN', 'WMAX', 'HMAX', 'MAXR', 'TOL_NUM', 'TOL_DEN', 'QR_N', 'QR_CHARS')}
        self.dc_names = {(w, h): name for w, h, name in zip(table(source, 'DCW'), table(source, 'DCH'), table(source, 'DCN'))}
        self.qr_url = ast.literal_eval(definition(source, 'QR_URL'))
        self.margin = [integer_definition(core['core_data.h'].decode(), name) for name in ('CD_Q_MARGIN_W', 'CD_Q_MARGIN_H')]
        # The pure encoder is maintained inside slqs.c. Extract it on each launch,
        # failing closed if its explicit section markers ever change.
        start = source.index('static u32 gf_mul(')
        end = source.index('/* ---- the observer:', start)
        if '/* ---- the scan decoder' in source[start:end]:     # v0.7.32test: the camera's QR decoder; the page only encodes
            end = source.index('/* ---- the scan decoder', start)
        encoder = source[start:end]
        if 'static int qr_encode(' not in encoder or 'static u32 qr_nop(' in encoder:
            raise RuntimeError('Cannot isolate the camera QR encoder')
        qr_defines = '\n'.join('#define ' + name + ' ' + definition(source, name)
                               for name in ('QR_N', 'QR_DATA_CW', 'QR_EC_CW')) + '\n'
        folder = Path(self._temp.name)
        for name, data in core.items():
            (folder / name).write_bytes(data)
        (folder / 'host_bridge.c').write_bytes(bridge)
        (folder / 'camera_qr.h').write_text(encoder)
        (folder / 'camera_qr_constants.h').write_text(qr_defines)
        compiler = shutil.which('clang') or shutil.which('cc')
        if not compiler:
            raise RuntimeError('A C compiler is required (install the Command Line Tools on macOS)')
        library = folder / ('preview.dylib' if sys.platform == 'darwin' else 'preview.so')
        command = [compiler, '-O2', '-std=c11', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                   '-I', str(folder), str(folder / 'core.c'), str(folder / 'host_bridge.c'), '-o', str(library)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise RuntimeError('Preview C adapter did not compile:\n' + result.stderr)
        self.lib = ctypes.CDLL(str(library))
        self.lib.preview_quality_size.restype = ctypes.c_int
        if self.lib.preview_quality_size() != ctypes.sizeof(Quality):
            raise RuntimeError('Camera core_quality layout changed; update the preview binding')
        self.lib.core_qualities_tol.argtypes = ([ctypes.c_int] * 4 + [ctypes.c_uint32] * 4
                                              + [ctypes.POINTER(Quality), ctypes.c_int])
        self.lib.core_qualities_tol.restype = ctypes.c_int
        for name in ('preview_key_name', 'preview_path_name'):
            fn = getattr(self.lib, name)
            fn.argtypes, fn.restype = [ctypes.c_int], ctypes.c_char_p
        self.lib.preview_qr.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint8)]
        self.lib.preview_qr.restype = ctypes.c_int
        self.lib.preview_readout.argtypes = [ctypes.POINTER(Quality), ctypes.POINTER(ctypes.c_int32)]
        self.lib.preview_readout.restype = ctypes.c_int
        self.lib.preview_win_top.restype = ctypes.c_int
        self.clk, self.vmax_max = self.lib.preview_clock(), self.lib.preview_vmax_max()
        self.max_qualities = self.lib.preview_max_qualities()
        self.info = {'version': self.version, 'core_fingerprint': fingerprint(core),
                     'fingerprint': fingerprint({**core, 'slqs.c': qs, 'build_slqs.py': build,
                                                 'host_bridge.c': bridge, 'server.py': Path(__file__).read_bytes()}),
                     'qr_url': self.qr_url, 'offline': True}

    def close(self):
        self._temp.cleanup()

    def validate_cell(self, dcw, dch, rw, rh):
        c = self.constants
        if any(type(v) is not int for v in (dcw, dch, rw, rh)):
            raise ValueError('Dimensions must be integers')
        for name, value, low, high, step in (('dcw', dcw, c['WMIN'], c['WMAX'], 16),
                                            ('dch', dch, c['HMIN'], c['HMAX'], 2),
                                            ('rw', rw, c['WMIN'], dcw, 16), ('rh', rh, c['HMIN'], dch, 2)):
            if not low <= value <= high or value % step:
                raise ValueError(f'{name} must be {low}..{high}, aligned to {step}')

    @lru_cache(maxsize=256)
    def qualities(self, dcw, dch, rw, rh):
        self.validate_cell(dcw, dch, rw, rh)
        rows = (Quality * self.max_qualities)()
        n = self.lib.core_qualities_tol(dcw, dch, rw, rh, 0, 1, self.constants['TOL_NUM'],
                                         self.constants['TOL_DEN'], rows, self.max_qualities)
        case = []
        if n < 0 or n > self.constants['MAXR']:
            # slqs.c cell_now rejects both formula errors and its 80-row cache overflow.
            case = {'err': f'core result {n}'}
        else:
            for q in rows[:n]:
                recipe = {'key': self.lib.preview_key_name(q.key).decode(), 'mh': q.mh, 'mv': q.mv, 'ad': q.ad,
                          'hbin': q.hbin, 'vbin': q.vbin, 'scw': q.cw, 'sch': q.ch, 'sw': q.sw, 'sh': q.sh,
                          'win': [q.win_w, q.win_h], 'zoom': [q.zh, q.zv],
                          'path': self.lib.preview_path_name(q.path).decode(), 'rs_ms': q.rs_us / 1000,
                          'rec': [q.rec_w, q.rec_h], 'vis': [q.vis_w, q.vis_h]}
                label = f'{q.ad}b {q.mh}x{q.mv}'
                if (q.hbin, q.vbin) != (1, 1):
                    label += f' h{q.hbin}v{q.vbin}'
                case.append([q.hm, q.vmin_lo, label, recipe])
        dc_key = self.dc_names.get((dcw, dch), f'C{dcw}x{dch}')
        return {'key': f'{dc_key}:{rw}x{rh}', 'case': case, 'nominal': [rw - self.margin[0], rh - self.margin[1]],
                'clk': self.clk, 'vmax_max': self.vmax_max}

    @lru_cache(maxsize=256)
    def readout(self, dcw, dch, rw, rh):
        """Each recipe's readout plan (host_bridge.c preview_readout), in qualities() order."""
        cell = self.qualities(dcw, dch, rw, rh)
        if not isinstance(cell['case'], list):
            return {'key': cell['key'], 'readout': None, 'win_top': self.lib.preview_win_top()}
        rows = (Quality * self.max_qualities)()
        n = self.lib.core_qualities_tol(dcw, dch, rw, rh, 0, 1, self.constants['TOL_NUM'],
                                         self.constants['TOL_DEN'], rows, self.max_qualities)
        out = []
        for q in rows[:n]:
            v = (ctypes.c_int32 * 10)()
            self.lib.preview_readout(ctypes.byref(q), v)
            out.append(None if v[0] else dict(zip(('fmt_w', 'line_w', 'raster_w', 'out_h', 'mh', 'mv', 'windowed',
                                                    'start', 'y_skip'), v[1:])))
        return {'key': cell['key'], 'readout': out, 'win_top': self.lib.preview_win_top()}

    @lru_cache(maxsize=64)
    def qr(self, code):
        if not isinstance(code, str) or not re.fullmatch(r'[A-Za-z0-9_-]{' + str(self.constants['QR_CHARS']) + '}', code):
            raise ValueError('code must contain exactly 37 base64url characters')
        size = self.constants['QR_N']
        pixels = (ctypes.c_uint8 * (size * size))()
        if self.lib.preview_qr((self.qr_url + code).encode('ascii'), pixels) != size:
            raise RuntimeError('Camera QR encoder rejected this payload')
        return {'size': size, 'modules': [list(pixels[y * size:(y + 1) * size]) for y in range(size)]}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, backend, **kwargs):
        self.backend = backend
        super().__init__(*args, directory=str(HERE), **kwargs)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        super().end_headers()

    def json_response(self, status, data):
        body = json.dumps(data, separators=(',', ':')).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def local_request(self):
        port = self.server.server_port
        hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
        if self.headers.get('Host') not in hosts:
            return False
        origin = self.headers.get('Origin')
        return origin is None or origin in {f'http://{host}' for host in hosts}

    def do_GET(self):
        if not self.local_request():
            return self.json_response(403, {'error': 'Only same-origin loopback requests are accepted'})
        if len(self.path) > 4096:
            return self.json_response(414, {'error': 'Request is too long'})
        path = urlsplit(self.path)
        if path.path.startswith('/api/'):
            try:
                query = parse_qs(path.query, keep_blank_values=True, max_num_fields=8)
                if path.path == '/api/info' and not query:
                    result = self.backend.info
                elif path.path in ('/api/qualities', '/api/readout'):
                    keys = ('dcw', 'dch', 'rw', 'rh')
                    if set(query) != set(keys) or any(len(query[k]) != 1 or not re.fullmatch(r'[0-9]{1,5}', query[k][0]) for k in keys):
                        raise ValueError('Expected one integer each: dcw, dch, rw, rh')
                    method = self.backend.qualities if path.path == '/api/qualities' else self.backend.readout
                    result = method(*(int(query[k][0]) for k in keys))
                elif path.path == '/api/qr':
                    if set(query) != {'code'} or len(query['code']) != 1:
                        raise ValueError('Expected one code parameter')
                    result = self.backend.qr(query['code'][0])
                else:
                    return self.json_response(404, {'error': 'Unknown endpoint'})
                return self.json_response(200, result)
            except ValueError as error:
                return self.json_response(400, {'error': str(error)})
            except RuntimeError as error:
                return self.json_response(500, {'error': str(error)})
        # Serve only files inside preview, including through encoded paths/symlinks.
        relative = unquote(path.path).lstrip('/') or 'dcres.html'
        target = (HERE / relative).resolve()
        if not target.is_relative_to(HERE) or not target.is_file():
            return self.json_response(404, {'error': 'Not found'})
        if path.path == '/':
            self.path = '/dcres.html'
        return super().do_GET()

    def do_HEAD(self):
        self.send_error(405, 'GET only')

    def do_POST(self):
        self.send_error(405, 'GET only')


def make_server(backend, port=8766):
    server = ThreadingHTTPServer(('127.0.0.1', port), partial(Handler, backend=backend))
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error('--port must be 0..65535')
    backend = Backend()
    try:
        with make_server(backend, args.port) as server:
            print(f'SensorLab {backend.version} offline preview: http://127.0.0.1:{server.server_port}/dcres.html', flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
    finally:
        backend.close()


if __name__ == '__main__':
    main()
