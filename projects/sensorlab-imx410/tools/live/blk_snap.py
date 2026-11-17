#!/usr/bin/env python3
"""BLK-SNAP TEST build: decode the BlackLevel loop snapshot ring (apply/ap.c struct ap_bs, sq_test 50) and put the
numbers through the firmware's own arithmetic.

    python3 -B blk_snap.py decode RING.bin [--build build-<ver>.json] [--dng-black 255.99 ...] [--bits 12|14]
    python3 -B blk_snap.py read OUT.bin --build build-<ver>.json --block 0x...   # camera: sq_test 50 -> the address,
                                             # word reads (after the take's stop + 12 s; refuses while recording)

The ring: 8 header words {"BSNP", ver 1, rec_words 48, nmax 32, n, 0, 0, 0}, then 32 records of 48 words (the field
names are build json blk_snap.rec_fields = FIELDS below).  One record per BlackLevel hook call (one per DNG header).

The arithmetic (read from the image, out/decomp/full/blk_c03.c; [C] = code, [I] = inference):
  v35  = ob_a0 - ob_b0, - 0x80 when 0x500 < sensor_gain <= 0x800                      XC_ImageSensorIMX410::v35 [C]
  black = 0x40000 - (avg_at_lock - ob_b0) + trunc((ped_target - ped_prev) / 4) * 0x400 + v35     FUN_c031a2a0 [C]
          (DN12 x 1024; trunc = C's signed division, toward zero; stored in the clamp object's 10-entry ring)
  the DNG tag = the sensor state's +0x208 >> (12 - bits), << 2 for 14 bits, / 1024             FUN_c02ca190 [C]
          which ring entry (or mean) reaches +0x208 is NOT read yet [I]: the table prints the newest and the mean.
  init pedestal = 0x400 + adj[branch][ob_int & 3], ob_int = (ob_b0 & 0xFFF00) >> 8             FUN_c0313ec0 [C]
          branch A when (flag byte0 == 0 or flag1 != 1) and (flag byte1 == 0 or flag2 != 1), else B;
          A: {1: -3, 2: -2, 3: -1, 0: 0}   B: {1: -1, 2: 0, 3: -3, 0: -2};  0x400 = the mode descriptor's +0x2E [I: not
          in the record]
A record is read by the hook a little after the firmware computed its own value from the same registers, so
`pred` (from the record's registers) and `fw` (the firmware's newest ring entry) may differ by the frame-to-frame
change of the averages; a constant difference means the formula above is wrong.
"""
import argparse
import json
import pathlib
import struct
import sys

MAGIC = 0x504E5342
HEADER_WORDS, REC_WORDS, NMAX = 8, 48, 32
FIELDS = (['seq', 'hook', 'site_r0', 'bits_fw', 'bits_out', 'pick_bits', 'rec14', 'cur_mode']
          + [f'ob_a{i}' for i in range(4)] + [f'ob_b{i}' for i in range(4)] + ['ped_reg0', 'ped_reg1']
          + ['ped_target', 'ped_cur', 'avg_locked', 'avg_at_lock', 'ped_prev', 'init_count']
          + [f'flag{i}' for i in range(4)] + [f'black{i}' for i in range(10)] + ['black_idx', 'sensor_gain']
          + ['crct_gain', 'tg_frame', 'tg_line'] + [f'pad{i}' for i in range(5)])
assert len(FIELDS) == REC_WORDS
ADJ = {'A': {1: -3, 2: -2, 3: -1, 0: 0}, 'B': {1: -1, 2: 0, 3: -3, 0: -2}}
RING_BYTES = 4 * (HEADER_WORDS + NMAX * REC_WORDS)


class BadRing(ValueError):
    pass


def s32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


def trunc_div4(v):
    """C's signed (v / 4): toward zero (the firmware's asr / add / asr sequence at C031A308)"""
    v = s32(v)
    return -((-v) >> 2) if v < 0 else v >> 2


def parse(buf, fields=None):
    """-> (header dict, [record dict] oldest first).  Refuses a ring that is not a whole, self-consistent one."""
    fields = list(fields or FIELDS)
    if len(buf) < RING_BYTES:
        raise BadRing(f'{len(buf)} bytes, a ring is {RING_BYTES}')
    h = struct.unpack_from(f'<{HEADER_WORDS}I', buf, 0)
    hdr = dict(magic=h[0], ver=h[1], rec_words=h[2], nmax=h[3], n=h[4])
    if h[0] != MAGIC:
        raise BadRing(f'magic {h[0]:#x}, not "BSNP": the ring is not attached (not the BLK-SNAP build?)')
    if (h[1], h[2], h[3]) != (1, REC_WORDS, NMAX) or len(fields) != REC_WORDS:
        raise BadRing(f'layout {h[1:4]} is not ver 1 / {REC_WORDS} words / {NMAX} records')
    n = h[4]
    out = []
    for k in range(max(0, n - NMAX), n):                    # record number k (0-based) is in slot k & (NMAX - 1)
        w = struct.unpack_from(f'<{REC_WORDS}I', buf, 4 * (HEADER_WORDS + (k & (NMAX - 1)) * REC_WORDS))
        r = dict(zip(fields, w))
        if r['seq'] != k + 1:
            raise BadRing(f'slot {k & (NMAX - 1)} holds seq {r["seq"]}, expected {k + 1} (torn or overwritten read)')
        out.append(r)
    return hdr, out


def v35(r):
    v = s32(r['ob_a0'] - r['ob_b0'])
    if 0x500 < r['sensor_gain'] <= 0x800:
        v -= 0x80
    return v


def black_x1024(r):
    """FUN_c031a2a0's stored value from the record's own inputs (DN12 x 1024)"""
    return (0x40000 - s32(r['avg_at_lock'] - r['ob_b0']) + trunc_div4(r['ped_target'] - r['ped_prev']) * 0x400
            + v35(r))


def branch(r):
    b0, b1 = r['flag0'] & 0xFF, (r['flag0'] >> 8) & 0xFF
    return 'A' if (b0 == 0 or r['flag1'] != 1) and (b1 == 0 or r['flag2'] != 1) else 'B'


def init_pedestal(r, target=0x400):
    ob_int = (r['ob_b0'] & 0xFFF00) >> 8
    return target + ADJ[branch(r)][ob_int & 3]


def fw_newest(r):
    """the clamp object's newest stored black: FUN_c031a2a0 writes slot (idx - 1), or 9 when idx is 0"""
    i = r['black_idx']
    if i > 10:
        return None
    return s32(r[f'black{9 if i == 0 else i - 1}'])


def row(r):
    blacks = [s32(r[f'black{i}']) for i in range(10)]
    pred, fw = black_x1024(r), fw_newest(r)
    return dict(seq=r['seq'], hook=('BLK6', 'BLK')[r['hook'] & 1], mode=r['cur_mode'], bits=r['bits_out'],
                bits_fw=r['bits_fw'], rec14=None if r['rec14'] == 0xFFFFFFFF else r['rec14'],
                ob_a=r['ob_a0'] / 1024, ob_b=r['ob_b0'] / 1024, lock=r['avg_at_lock'] / 1024,
                ped=(r['ped_reg0'] & 0x3FFF), ped_target=r['ped_target'], ped_cur=r['ped_cur'], ped_prev=r['ped_prev'],
                branch=branch(r), ped_init=init_pedestal(r), v35=v35(r) / 1024, pred=pred / 1024,
                fw=None if fw is None else fw / 1024, fw_mean=sum(blacks) / 10240, gain=r['sensor_gain'])


def tag_of(black_dn12, bits):
    """the DNG BlackLevel a 12-bit-scale black gives at this depth (FUN_c02ca190: << 2 at 14, >> (12 - bits) below)"""
    return black_dn12 * 4 if bits == 14 else black_dn12 / (1 << (12 - bits)) if bits < 12 else black_dn12


def table(records, dng_black=None, bits=None):
    rows = [row(r) for r in records]
    lines = ['seq hook mode bits rec14  ob_a     ob_b     lock     ped  tgt  prev br init  v35     pred     fw       fw_mean']
    for x in rows:
        lines.append('%3d %-4s %4d %4d %5s %8.3f %8.3f %8.3f %4d %4d %4d  %s %4d %7.3f %8.3f %8s %8.3f' % (
            x['seq'], x['hook'], x['mode'], x['bits'], x['rec14'], x['ob_a'], x['ob_b'], x['lock'], x['ped'],
            x['ped_target'], x['ped_prev'], x['branch'], x['ped_init'], x['v35'], x['pred'],
            '-' if x['fw'] is None else '%.3f' % x['fw'], x['fw_mean']))
    if rows:
        mp = sum(x['pred'] for x in rows) / len(rows)
        fws = [x['fw'] for x in rows if x['fw'] is not None]
        lines.append(f'mean pred {mp:.3f}' + (f'   mean fw {sum(fws) / len(fws):.3f}' if fws else ''))
        if dng_black:
            b = bits or rows[-1]['bits']
            md = sum(dng_black) / len(dng_black)
            lines.append(f'DNG BlackLevel mean {md:.3f} ({len(dng_black)} frames, {b}-bit)   '
                         f'pred as a tag {tag_of(mp, b):.3f}   tag - pred {md - tag_of(mp, b):+.3f}'
                         + (f'   tag - fw {md - tag_of(sum(fws) / len(fws), b):+.3f}' if fws else ''))
    return rows, '\n'.join(lines)


def read_camera(build, block=None, addr=None, cam=None):
    """sq_test 50 -> the ring's address (or --addr), then word reads.  Refuses while recording; run it >= 12 s after
    the take's stop (rec_take.sh already waits)."""
    info = json.loads(pathlib.Path(build).read_text())
    if 'blk_snap' not in info:
        raise SystemExit(f'{build}: not a --blk-snap-test build')
    if cam is None:                                           # pragma: no cover  (camera)
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        import run_checklist as RC
        cam = RC.Camera()
    if cam.recording():
        raise SystemExit('recording: nothing is sent')
    if addr is None:
        if block is None:
            raise SystemExit('read: give --block (the SensorLab block from LOAD.LOG) or --addr')
        addr = cam.call(block + info['sq_test_off'], 50, 0, 0)
    if not addr or addr & 3:
        raise SystemExit(f'sq_test 50 answered {addr:#x}: not the BLK-SNAP build on the camera?')
    words = []
    for off in range(0, RING_BYTES // 4, 128):
        words += cam.mem(addr + 4 * off, min(128, RING_BYTES // 4 - off))
    return struct.pack(f'<{len(words)}I', *words)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    d = sub.add_parser('decode')
    d.add_argument('ring')
    d.add_argument('--build', help='build json: its blk_snap.rec_fields must be this decoder\'s')
    d.add_argument('--dng-black', type=float, nargs='*', help='the take\'s DNG BlackLevel values (any order)')
    d.add_argument('--bits', type=int, choices=(8, 10, 12, 14))
    d.add_argument('--json', help='also write the rows here')
    r = sub.add_parser('read')
    r.add_argument('out')
    r.add_argument('--build', required=True)
    r.add_argument('--block', type=lambda x: int(x, 0), help='the SensorLab block address (LOAD.LOG)')
    r.add_argument('--addr', type=lambda x: int(x, 0), help='the ring address, when already known')
    a = ap.parse_args(argv)
    if a.cmd == 'read':                                       # pragma: no cover  (camera)
        pathlib.Path(a.out).write_bytes(read_camera(a.build, a.block, a.addr))
        print(f'{a.out}: {RING_BYTES} bytes')
        return 0
    fields = FIELDS
    if a.build:
        info = json.loads(pathlib.Path(a.build).read_text())
        if 'blk_snap' not in info:
            raise SystemExit(f'{a.build}: not a --blk-snap-test build')
        fields = info['blk_snap']['rec_fields']
        if fields != FIELDS:
            raise SystemExit('the build\'s record layout is not this decoder\'s')
    hdr, recs = parse(pathlib.Path(a.ring).read_bytes(), fields)
    rows, text = table(recs, a.dng_black, a.bits)
    print(f'{hdr["n"]} records written, {len(recs)} kept')
    print(text)
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(dict(header=hdr, rows=rows, records=recs), indent=1) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
