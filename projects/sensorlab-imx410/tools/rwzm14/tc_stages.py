#!/usr/bin/env python3
"""T-C (notes/TRUE14_2X_RESEARCH.md §7): CRCT bin precision per stage, standby, BUFA0 a0 mux 1/2/3/4.

    tc_stages.py OUT [STAGE ...]      default S0 S1 S2 S3 S4 S5; ends with poff 1 (sweep.fastreboot)

Imports the imx410-lab tools (bins / fastsweep / bufa_probe / l7 / sweep); does not modify them.
Readout = bins.V['v3_14'] (14v3, 14-bit ADC). Each stage: safe_stop -> bin regs + mux + smaller DMA geometry ->
start -> grab_cb x2 -> safe_stop -> bins / mux / geometry back -> start.
"""
import json, pathlib, sys, time

IMXL = pathlib.Path('/Users/dido/Developer.localized/SIGMAfp_re/projects/imx410-lab')
sys.path.insert(0, str(IMXL))
import bins                                                            # noqa: E402
import fastsweep as F                                                  # noqa: E402
import bufa_probe as B                                                 # noqa: E402
import l7                                                              # noqa: E402

MUX = 0x300F06B0
V, H1, H2, H2K, BYP = 0x300F0800, 0x300F0840, 0x300F08C0, 0x300F08C4, 0x300F0870
BIN_STOCK = {V: 0, H1: 0, H2: 0, H2K: 0x00102010, BYP: 0}        # mode 10 standby (captures/crct_m8_m10.json)
# stage: (bin writes, mux, rows (None = rewindow's), words (None = rewindow's))
STAGES = {
    'S0': ({}, 1, None, None),
    'S1': ({V: 1}, 2, 320, None),
    'S2': ({H1: 1}, 3, None, 882),
    'S3': ({H2: 1, H2K: 0x00102010}, 4, None, 882),
    'S4': ({V: 1, H2: 1, H2K: 0x00102010}, 4, 320, 882),
    'S5': ({}, 4, None, None),
    'S2b': ({H1: 1, BYP: 1}, 3, None, 882),
    # run4 (10-30): the bin registers read 0 again 0.3 s after the write (firmware rewrites them per frame), and
    # S2's 882-word geometry overran the frame (the DMA writes the real line). Full geometry from here on.
    'S2f': ({H1: 1}, 3, None, None),
    'S3f': ({H2: 1, H2K: 0x00102010}, 4, None, None),
    # run4: 0x300F08C0 does stick (0800 does not), and with the full geometry no frame completed. Narrow line
    # words; the guard and the read-back cover the full-frame extent (the buffer is 24 MB) so a DMA that
    # writes the real line still lands inside our buffer and is kept.
    'S3n': ({H2: 1, H2K: 0x00102010}, 4, None, 882),
}
LOG = []
FULL = [0]          # bytes of the full-geometry frame (set after rewindow)


def log(msg):
    line = f'{time.strftime("%H:%M:%S")} {msg}'
    print(line, flush=True)
    LOG.append(line)


def batch(regs):
    """l7.batch with the table claimed at its real size (l7 claims 1024 B; the cave had 956 left on 10-30)."""
    import struct, cave
    from armasm import assemble
    code = assemble(IMXL / 'sensor_read' / 'batch.S')
    at = cave.claim('imxl.batch', 256)
    tab = cave.claim(f'tc.batch.tab{len(regs)}', 8 * len(regs))
    B.P().put(at, code + bytes(-len(code) % 4), 'batch ')
    B.P().put(tab, b''.join(struct.pack('<II', 0x81 | (r >> 8) << 8 | (r & 0xFF) << 16, v) for r, v in regs), 'table ')
    B.call(B.F_DCACHE)
    return B.call(at, tab, len(regs))


def set_geom(s, rows, words):
    B.wr(0x30182110, rows)
    B.wr(0x30182114, words)
    s.h, s.words, s.size = rows, words, rows * words * 4
    s.tail = s.buf + s.size - 16
    s.guard = s.buf + max(s.size, FULL[0]) + 0x100
    s.readn = max(s.size, FULL[0])
    B.wr(s.guard, 0x5AFE5AFE)


def grab_pair(s, d, meta):
    d.mkdir(parents=True, exist_ok=True)
    for name in ('frame.raw', 'frame2.raw'):
        if not s.grab_cb():
            return False
        n = getattr(s, 'readn', s.size)
        B.P().mem_window(B.WIN, s.buf, n, 1)
        try:
            raw = B.P().mem_read(s.buf, n, label='frame ')
        finally:
            B.P().mem_window(B.WIN, s.buf, n, 0)
        if B.P().mem_get(s.guard)[0] != 0x5AFE5AFE:
            raise SystemExit('DMA overrun past the frame end')
        (d / name).write_bytes(raw)
    (d / 'frame.json').write_text(json.dumps(dict(meta, height=s.h, line_words=s.words, bits=14,
                                                  window=s.base_window, t=time.time()), indent=1))
    return True


def stage(s, out, name, full):
    writes, mux, rows, words = STAGES[name]
    B.startstop(100)
    for a, v in writes.items():
        B.wr(a, v)
    B.wr(MUX, mux)
    set_geom(s, rows or full[0], words or full[1])
    B.call(B.F_SETADDR, s.scratch)
    B.startstop(10)
    time.sleep(0.3)
    rb = {f'0x{a:08X}': f'0x{B.P().mem_get(a)[0]:08X}' for a in (V, H1, H2, H2K, BYP, MUX, 0x30182110, 0x30182114)}
    ok = grab_pair(s, out / name, dict(stage=name, mux=mux, writes={f'0x{a:08X}': v for a, v in writes.items()}, readback=rb))
    log(f'{name}: mux {mux} writes {[(hex(a), hex(v)) for a, v in writes.items()]} rows {s.h} words {s.words} -> '
        f'{"ok" if ok else "NO FRAME"}  readback {rb}')
    # back: if no completion came, put full geometry + no bin first so the DMA can finish a frame, then stop
    if not ok:
        for a, v in BIN_STOCK.items():
            B.wr(a, v)
        B.wr(MUX, 1)
    B.startstop(100)
    for a, v in BIN_STOCK.items():
        B.wr(a, v)
    B.wr(MUX, 1)
    set_geom(s, *full)
    B.call(B.F_SETADDR, s.scratch)
    B.startstop(10)
    time.sleep(0.2)
    return ok


def main():
    out = pathlib.Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
    names = sys.argv[2:] or ['S0', 'S1', 'S2', 'S3', 'S4', 'S5']
    regs, hmax, rx, yend, rx14 = bins.V['v3_14']
    regs = [(r, v) for r, v in regs if r != 0x005D] + [(0x005D, 0x05)]
    F.cached_assemble()
    B.not_recording()
    s = F.Session(out, yend, True, 10, min_alloc=24 << 20)
    clean = False
    try:
        B.startstop(100)
        n = batch(regs)
        B.wr(0x30100004, (hmax - 1) | (hmax - 1) << 16)
        B.wr(0x30100800, 0x00112013); B.wr(0x300E10B4, 3)
        log(f'readout v3_14: {n} regs, HMAX {hmax}, yend {yend}, rx14')
        time.sleep(0.3)
        l7.rewindow(s, 1)
        full = (s.h, s.words)
        FULL[0] = s.h * s.words * 4
        log(f'full geometry {full}')
        time.sleep(0.5)
        for name in names:
            if (out / 'STOP').exists():
                log('STOP file: ending'); break
            if not stage(s, out, name, full):
                log(f'{name} failed: ending the run'); break
        s.write(0x0018, 0x00); s.write(0x005D, 0x03)
        clean = True
    finally:
        try:
            s.close()
        finally:
            (out / 'run.log').write_text('\n'.join(LOG) + '\n')
            import sweep
            sweep.KEEP = None
            log(f'closing (clean={clean}); poff 1')
            sweep.fastreboot()
            (out / 'run.log').write_text('\n'.join(LOG) + '\n')


if __name__ == '__main__':
    main()
