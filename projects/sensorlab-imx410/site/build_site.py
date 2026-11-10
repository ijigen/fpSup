#!/usr/bin/env python3
"""Build the reviewed SensorLab Pages files locally; never commit or publish.

One page: the simulator (preview/dcres.html + WebAssembly engine) is also the camera's QR landing page at
fpSup/sensor_lab_imx410/ (#<code>). simulator/ only redirects there, keeping the hash, for old links.
"""
import argparse
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
PREVIEW = HERE.parent / 'preview'
SOURCE = PREVIEW / 'dcres.html'
DESTINATION = HERE.parents[2] / 'fpSup' / 'sensor_lab_imx410' / 'index.html'
STATIC = ('fps_data.js', 'site_page.js', 'simulator.js', 'assets/menu_lock_qs.png')
ENGINE = ('wasm_backend.js', 'sensorlab.wasm', 'wasm_info.json')
# Files of the former standalone simulator/ directory: removed on build, and --check fails while any remain.
OBSOLETE = tuple('simulator/' + name for name in ENGINE + STATIC if name != 'site_page.js')

REDIRECT = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SensorLab-IMX410</title>
<link rel="canonical" href="../">
<script>location.replace('../' + location.hash);</script>
<meta http-equiv="refresh" content="0; url=../">
<style>body{margin:24px 16px;font:15px/1.5 system-ui,sans-serif;background:#f6f6f6;color:#151515}
@media (prefers-color-scheme:dark){body{background:#0d0d0d;color:#ececec}}a{color:inherit}</style>
</head><body><p>The simulator is now part of the <a href="../">SensorLab-IMX410 page</a>.</p></body></html>
'''


def page(source=None):
    """The published index.html: the simulator page with the browser engine adapter before simulator.js."""
    html = (source or SOURCE).read_text()
    script = '<script src="simulator.js" defer></script>'
    if html.count(script) != 1:
        raise RuntimeError('Cannot locate the simulator adapter script')
    return html.replace(script, '<script src="wasm_backend.js" defer></script>\n' + script)


def publication_files():
    sys.path.insert(0, str(PREVIEW))
    import build_web
    files = {'index.html': page().encode()}
    with tempfile.TemporaryDirectory(prefix='sensorlab-site-') as temp:
        info = build_web.build(temp)['info']
        for name in ENGINE:
            files[name] = (pathlib.Path(temp) / name).read_bytes()
    for name in STATIC:
        files[name] = (PREVIEW / name).read_bytes()
    files['simulator/index.html'] = REDIRECT.encode()
    files['README.md'] = f'''# SensorLab-IMX410 web page

One static page: the Quick Set simulator, which is also where the camera's QR code lands
(`https://ijigen.github.io/fpSup/sensor_lab_imx410/#<code>`). A code in the address is decoded and
loaded into the simulator, with the full mode details (sensor crop, binning, ISP scale, recorded
bit depth, sizes, rolling shutter, data rates). Anything the simulator cannot show exactly is listed
on the page. Every change in the simulator rewrites the address to the camera's own payload format.
English by default, with Simplified and Traditional Chinese. `simulator/` redirects here.

The simulator uses the SensorLab **{info['version']}** C calculation core and QR encoder compiled
to WebAssembly. Everything runs in the browser; no camera, local server, account or remote
calculation service is needed. Image quality, recording, playback and physical camera stability are
not simulated.

These static files are generated from the maintained workspace sources with
`python3 -B projects/sensorlab-imx410/site/build_site.py`. `wasm_info.json` records the version,
source fingerprints and binary checksum. The camera QR payload and its URL are unchanged.
'''.encode()
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='fail if the local publication copy differs')
    parser.add_argument('--simulator', action='store_true', help='accepted for old scripts; the simulator is always built')
    parser.add_argument('--out', type=pathlib.Path, default=DESTINATION.parent, help='publication directory')
    args = parser.parse_args()
    files = publication_files()
    for name, contents in files.items():
        destination = args.out / name
        if args.check:
            if not destination.exists() or destination.read_bytes() != contents:
                parser.exit(1, f'Page copy is stale: {name}; run build_site.py.\n')
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(contents)
    for name in OBSOLETE:
        stale = args.out / name
        if stale.exists():
            if args.check:
                parser.exit(1, f'Obsolete file remains: {name}; run build_site.py.\n')
            stale.unlink()
    if not args.check:
        assets = args.out / 'simulator' / 'assets'
        if assets.is_dir() and not any(assets.iterdir()):
            assets.rmdir()
    print(f'{len(files)} files, {sum(map(len, files.values()))} bytes; local page copies match')


if __name__ == '__main__':
    main()
