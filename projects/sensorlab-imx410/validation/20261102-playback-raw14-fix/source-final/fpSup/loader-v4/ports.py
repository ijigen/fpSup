#!/usr/bin/env python3
"""The released v3 sups that need only the v4 header (2026-10-22 assessment).

    python3 -B ports.py --out DIR        -> DIR/fpSup/<names_v4 file names> + DIR/ports.json

File and display names: names_v4.py (the user 2026-10-25), e.g.
EarlyFlush_v0.1.0.BIN "Early Flush" (was FCAP), USB-Shell_v3.4.0.BIN.

Each is built from its own source by its own builder, exactly as for v3, then
moved under the v4 header by build_v4.from_v3 (body unchanged, +16 bytes).

  FCAP    projects/rec-core/fcap        patch_sup, one EXCL word
  ULWR    projects/rec-core/writer      patch_sup + wr_card.S inner; adr only, state at
                                        STATE_REL from `inner`; already moves itself to the
                                        cached alias (a no-op when the block is cached)
  STOPFX  fpSup/stopfix (Ruari)         patch_sup, one EXCL word; the fixture asserts the
                                        v3 bytes are Ruari's original 316 B
  GYR2    projects/gyro2-sup (build 6)  no longer a header swap (2026-10-24): its own v4 build,
                                        build.build_v4 = gyr2.S -DGYR2_V4 + src/gyr2_row4.c,
                                        the fpSup page's Gyro2 ON/OFF row saved in GYR2.BIN
                                        (test_gyr2_v4.py); everything else is the v3 code
  SHELL   fp_usb_shell                  as released: BURST15 + NOPTP; not cached (worker DMA)

Load order is the file name's (v4): FCAP, GYR2, SHELL, STOPFX, ULWR -- none of
them depends on order (their sites are their own; GYR2's C050D4C8 is CHAIN).
"""
import argparse, hashlib, importlib.util, json, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import build_v4 as B                                    # noqa: E402
import names_v4 as N                                    # noqa: E402


def _module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def fcap():
    return _module(ROOT / 'projects/rec-core/fcap/build.py', 'fcap_build').build()


def ulwr():
    return _module(ROOT / 'projects/rec-core/writer/build.py', 'ulwr_build').build()[0]


def stopfx():
    return _module(ROOT / 'fpSup/stopfix/stopfix_fixture.py', 'stopfx_fixture').stopfix_sup()


def gyr2():
    """(v4 with the row, the v3 build it grew from)."""
    g = _module(ROOT / 'projects/gyro2-sup/build.py', 'gyr2_build')
    return g.build_v4()[0], g.build()[0]


# sup_id -> (v3 builder, v4 flags, reviewed non-patch_sup body); names: names_v4
PORTS = {
    'FCAP': (fcap, B.SL_F_CACHED_OK, False),
    'STFX': (stopfx, B.SL_F_CACHED_OK, False),
    'ULWR': (ulwr, B.SL_F_CACHED_OK, False),
}


def build():
    """{file name: (v4 bytes, v3 bytes)}."""
    out = {}
    for sid, (fn, flags, reviewed) in PORTS.items():
        v3 = fn()
        out[N.file_name(sid)] = (B.from_v3(v3, name=N.display(sid), flags=flags, reviewed=reviewed), v3)
    out[N.file_name('GYR2')] = gyr2()
    out[N.file_name('SHEL')] = (B.shell_sup(burst15=True), B.V3.shell_sup(burst15=True))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=pathlib.Path, required=True)
    a = ap.parse_args()
    d = a.out / 'fpSup'
    d.mkdir(parents=True, exist_ok=True)
    info = {}
    for name, (v4, v3) in build().items():
        (d / name).write_bytes(v4)
        info[name] = {'bytes': len(v4), 'sha256': hashlib.sha256(v4).hexdigest(),
                      'v3_sha256': hashlib.sha256(v3).hexdigest()}
        print(f'{name:24} {len(v4):6} B  {info[name]["sha256"][:16]}  (v3 {info[name]["v3_sha256"][:8]})')
    (a.out / 'ports.json').write_text(json.dumps(info, indent=1) + '\n')


if __name__ == '__main__':
    main()
