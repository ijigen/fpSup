#!/usr/bin/env python3
"""Switch 0 == the first 0.3.2test build (Bei 2026-11-10).

Compiles control.c and codec_job.c's source_bytes as they were before the
row-pitch test switch (source-mid/) and as they are now (fpSup/), and compares
every decision over a grid: fpl_can_enable / fpl_begin_direct for contexts
WITHOUT the switch bit, and fpl_codec_source_bytes (the strict public one) plus
the new fpl_codec_source_bytes_test(..., 0). Offline; no camera.

    python3 -B default_equivalence.py
"""
import ctypes as ct, itertools, pathlib, shutil, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[3]
OLD, NEW = HERE / 'source-mid/fpSup/lossless', ROOT / 'fpSup/lossless'


class Ctx(ct.Structure):
    _fields_ = [(n, ct.c_uint32) for n in ('firmware', 'cine', 'compression', 'bits', 'width',
                                           'height', 'fps_num', 'fps_den', 'media', 'ready')]


class St(ct.Structure):
    _fields_ = [(n, ct.c_uint32) for n in ('magic', 'abi', 'requested', 'clip', 'frames', 'fault',
                                           'r0', 'r1')]


def lib(tmp, tree, tag):
    out = pathlib.Path(tmp) / f'{tag}.dylib'
    # codec_job.c host-test mode needs its natives table: give it a dummy one
    stub = pathlib.Path(tmp) / f'{tag}_stub.c'
    stub.write_text('#include "codec_job.h"\nconst struct fpl_codec_natives fpl_codec_test_natives;\n')
    subprocess.run([shutil.which('clang') or 'clang', '-shared', '-fPIC', '-O1', '-std=c11',
                    '-DFPL_CODEC_JOB_HOST_TEST', '-I', str(NEW / 'native'), '-I', str(NEW),
                    str(tree / 'control.c'), str(tree / 'native/codec_job.c'), str(stub),
                    '-o', str(out)], check=True, capture_output=True, text=True)
    return ct.CDLL(str(out))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        old, new = lib(tmp, OLD, 'old'), lib(tmp, NEW, 'new')
        n = 0
        widths = list(range(8, 6200, 8)) + [0, 7, 1937, 0x4000, 0x4008]
        for bits in (0, 8, 10, 11, 12, 13, 14, 16):
            for w in widths:
                for h in (2, 1090, 1091, 4040, 0x4002):
                    for ready in (0, 126, 127, 127 | (1 << 31)):
                        c = Ctx(502, 1, 1, bits, w, h, 24000, 1001, 1, ready)
                        a, b = old.fpl_can_enable(ct.byref(c)), new.fpl_can_enable(ct.byref(c))
                        s1, s2 = St(), St()
                        old.fpl_boot(ct.byref(s1)); new.fpl_boot(ct.byref(s2))
                        d1 = old.fpl_begin_direct(ct.byref(s1), ct.byref(c))
                        d2 = new.fpl_begin_direct(ct.byref(s2), ct.byref(c))
                        if (a, d1, bytes(s1)) != (b, d2, bytes(s2)):
                            sys.exit(f'DIFF bits={bits} w={w} h={h} ready={ready:#x}: {a},{d1} vs {b},{d2}')
                        n += 1
        for f in range(6):
            for w in widths:
                for h in (2, 1090, 1091, 4040, 0x4002):
                    a = old.fpl_codec_source_bytes(w, h, f)
                    b = new.fpl_codec_source_bytes(w, h, f)
                    c = new.fpl_codec_source_bytes_test(w, h, f, 0)
                    if not a == b == c:
                        sys.exit(f'DIFF source_bytes w={w} h={h} f={f}: {a} {b} {c}')
                    n += 1
        print(f'switch 0 == first 0.3.2test: {n:,} decisions identical')


if __name__ == '__main__':
    main()
