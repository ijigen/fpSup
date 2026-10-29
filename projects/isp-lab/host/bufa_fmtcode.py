#!/usr/bin/env python3
"""What do the BUFA0 format codes the firmware never writes do? (2026-10-27)

FUN_c06306e0 writes 0x3018210C = 0 (12 bit), 1 (14), 2 (10), 3 (8), 4 (16)
and 0x806 (compressed); 5, 6, 7 alone are never used.  This takes one standby
frame per code with imx410-lab's `bufa_probe.py frame`, unchanged except that
right after its window call the format register is set to CODE.  The line
length stays the 12-bit one (w*3/8 words) and each buffer is allocated 1.5x
the frame, so a format that writes more than the line length hits the guard
words, not someone else's memory.  Every touched register is restored by
bufa_probe itself.

    bufa_fmtcode.py OUT_DIR CODE [CODE ...]      (0 = the 12-bit reference)
"""
import argparse, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
IMXL = HERE.parents[1] / 'imx410-lab'
sys.path.insert(0, str(IMXL))
import bufa_probe as B                                       # noqa: E402

FMT = 0x3018210C
ROWS = 320


def take(out, code):
    orig = B.call

    def call(fn, *args):
        v = orig(fn, *args)
        if fn == B.F_WINDOW:
            B.wr(FMT, code)
            print(f'  format register {B.P().mem_get(FMT)[0]:#x} (asked {code})')
        return v
    B.call = call
    orig_release, orig_wr = B.release, B.wr
    peek_n = int(4.5 * (1 << 20))

    def release(path, held):
        # read the whole buffer back BEFORE it is given back, frame seen or not: did anything write it?
        if held:
            buf = held[0][0] - 0x80000000 if held[0][0] >= 0xC0000000 else held[0][0]
            P = B.P()
            P.mem_window(B.WIN, buf, peek_n, 1)
            try:
                (pathlib.Path(out) / 'buffer.bin').write_bytes(P.mem_read(buf, peek_n, label='bufpk '))
            finally:
                P.mem_window(B.WIN, buf, peek_n, 0)
        return orig_release(path, held)
    B.release = release
    try:
        # class 0 (memory bufmem-get-wedges-shell: class 10 raced liveview and wedged the shell). Class 0 has
        # < 10 MB free, so the receiver window is cut to ROWS rows (restored by bufa_probe) and each buffer is
        # 4.5 MB = > 1.5x a 12-bit frame of that height (ROWS x 2274 words x 4 = 2.9 MB): an overrun hits the guards.
        y0 = B.P().mem_get(0x30100024)[0] >> 16
        a = argparse.Namespace(out=str(out), pre=[], post=[], settle=1.0, bus=False, heap_class=0,
                               keep=None, keep_size=int(4.5 * (1 << 20)), sub=[], mux=1, ystart=None,
                               yend=y0 + ROWS, vmax=None)
        B.cmd_frame(a)
    finally:
        B.call, B.release = orig, orig_release


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out', type=pathlib.Path)
    ap.add_argument('codes', type=int, nargs='+')
    a = ap.parse_args()
    for c in a.codes:
        if c not in range(0, 8):
            raise SystemExit('codes 0..7 only')
        take(a.out / f'code{c}', c)


if __name__ == '__main__':
    main()
