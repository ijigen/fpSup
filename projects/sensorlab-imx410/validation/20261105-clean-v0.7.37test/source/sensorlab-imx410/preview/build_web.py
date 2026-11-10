#!/usr/bin/env python3
"""Build the unchanged camera core and QR encoder for a static browser site.

Only writes the three web-engine assets to --out; compilation is private/temp.
No camera/card, shared build artifacts, package install or publication actions.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import server

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
EXPORTS = ('preview_quality_size preview_max_qualities preview_clock preview_vmax_max '
           'preview_key_name preview_path_name wasm_rows wasm_url wasm_qr_output '
           'wasm_url_capacity wasm_qualities wasm_qr wasm_readout preview_win_top').split()


def toolchain():
    compiler = os.environ.get('WASM_CC') or shutil.which('clang')
    linker = os.environ.get('WASM_LD') or shutil.which('wasm-ld')
    if not linker:
        candidates = sorted((Path.home() / '.rustup' / 'toolchains').glob('*/lib/rustlib/*/bin/gcc-ld/wasm-ld'))
        linker = str(candidates[0]) if candidates else None
    if not compiler or not linker:
        raise RuntimeError('A wasm32-capable clang and wasm-ld are required; set WASM_CC and WASM_LD')
    return compiler, linker


def linker_environment(linker):
    env = dict(os.environ)
    # Rust ships wasm-ld beside rust-lld, with LLVM in the toolchain's top lib
    # directory. Its installed macOS rpath may not locate that sibling tree.
    # Give only this subprocess that existing library; do not alter the system.
    for parent in Path(linker).resolve().parents:
        library = parent / 'lib' / 'libLLVM.dylib'
        if library.is_file():
            previous = env.get('DYLD_LIBRARY_PATH')
            env['DYLD_LIBRARY_PATH'] = str(library.parent) + (os.pathsep + previous if previous else '')
            break
    return env


def build(destination):
    destination = Path(destination)
    compiler, linker = toolchain()
    core = {name: (PROJECT / 'core' / name).read_bytes() for name in ('core.c', 'core.h', 'core_data.h')}
    qs = (PROJECT / 'qs' / 'slqs.c').read_bytes()
    version_source = (PROJECT / 'qs' / 'build_slqs.py').read_bytes()
    host_bridge = (HERE / 'host_bridge.c').read_bytes()
    wasm_bridge = (HERE / 'wasm_bridge.c').read_bytes()
    backend_js = (HERE / 'wasm_backend.js').read_bytes()
    snapshot = {**{PROJECT / 'core' / name: data for name, data in core.items()},
                PROJECT / 'qs' / 'slqs.c': qs, PROJECT / 'qs' / 'build_slqs.py': version_source,
                HERE / 'host_bridge.c': host_bridge, HERE / 'wasm_bridge.c': wasm_bridge,
                HERE / 'wasm_backend.js': backend_js}
    source = qs.decode()
    versions = [node.value.value for node in ast.parse(version_source).body
                if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'VERSION' for t in node.targets)
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)]
    if len(versions) != 1:
        raise RuntimeError('Cannot read source VERSION')
    constants = {name: server.integer_definition(source, name)
                 for name in ('WMIN', 'HMIN', 'WMAX', 'HMAX', 'MAXR', 'TOL_NUM', 'TOL_DEN', 'QR_N', 'QR_CHARS')}
    start = source.index('static u32 gf_mul(')
    end = source.index('/* ---- the scan decoder', start)   # v0.7.32test: qrdec.c is included between the encoder and the observer
    encoder = source[start:end]
    if 'static int qr_encode(' not in encoder or 'static u32 qr_nop(' in encoder:
        raise RuntimeError('Cannot isolate the camera QR encoder')
    with tempfile.TemporaryDirectory(prefix='sensorlab-wasm-') as temp:
        folder = Path(temp)
        for name, data in {**core, 'host_bridge.c': host_bridge, 'wasm_bridge.c': wasm_bridge}.items():
            (folder / name).write_bytes(data)
        (folder / 'camera_qr.h').write_text(encoder)
        (folder / 'camera_qr_constants.h').write_text('\n'.join('#define ' + name + ' ' + server.definition(source, name)
                                                               for name in ('QR_N', 'QR_DATA_CW', 'QR_EC_CW')) + '\n')
        (folder / 'string.h').write_text('#include <stddef.h>\nvoid *memcpy(void *, const void *, size_t);\n'
                                       'void *memset(void *, int, size_t);\nsize_t strlen(const char *);\n')
        objects = []
        for name in ('core', 'host_bridge', 'wasm_bridge'):
            obj = folder / (name + '.o')
            command = [compiler, '--target=wasm32', '-O2', '-ffreestanding', '-fno-builtin', '-nostdlib',
                       '-std=c11', '-Wall', '-Wextra', '-Werror', '-I', str(folder), '-c', str(folder / (name + '.c')), '-o', str(obj)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=60)
            if result.returncode:
                raise RuntimeError('WebAssembly compilation failed:\n' + result.stderr)
            objects.append(str(obj))
        wasm = folder / 'sensorlab.wasm'
        command = [linker, '--no-entry', '--export-memory', '--stack-first', '-z', 'stack-size=1048576',
                   '--initial-memory=2097152', '--max-memory=2097152', '--strip-all', *['--export=' + n for n in EXPORTS],
                   *objects, '-o', str(wasm)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=60, env=linker_environment(linker))
        if result.returncode:
            raise RuntimeError('WebAssembly link failed:\n' + result.stderr)
        wasm_bytes = wasm.read_bytes()
    inputs = {**core, 'slqs.c': qs, 'build_slqs.py': version_source, 'host_bridge.c': host_bridge, 'wasm_bridge.c': wasm_bridge}
    manifest = {
        'info': {'version': versions[0], 'core_fingerprint': server.fingerprint(core), 'fingerprint': server.fingerprint(inputs),
                 'qr_url': ast.literal_eval(server.definition(source, 'QR_URL')), 'offline': True},
        'constants': constants, 'fields': server.QFIELDS,
        'margin': [server.integer_definition(core['core_data.h'].decode(), n) for n in ('CD_Q_MARGIN_W', 'CD_Q_MARGIN_H')],
        'dc_names': [{'w': w, 'h': h, 'name': name} for w, h, name in zip(server.table(source, 'DCW'), server.table(source, 'DCH'), server.table(source, 'DCN'))],
        'clk': server.integer_definition(core['core_data.h'].decode(), 'CD_CLK'),
        'vmax_max': server.integer_definition(core['core_data.h'].decode(), 'CD_VMAX_MAX'),
        'wasm_sha256': hashlib.sha256(wasm_bytes).hexdigest(),
    }
    changed = [str(path.relative_to(PROJECT)) for path, contents in snapshot.items() if path.read_bytes() != contents]
    if changed:
        raise RuntimeError('Sources changed during compilation; rebuild from the current snapshot: ' + ', '.join(changed))
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'sensorlab.wasm').write_bytes(wasm_bytes)
    (destination / 'wasm_info.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (destination / 'wasm_backend.js').write_bytes(backend_js)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    info = build(args.out)
    print(f'SensorLab {info["info"]["version"]}: {args.out / "sensorlab.wasm"}')


if __name__ == '__main__':
    main()
