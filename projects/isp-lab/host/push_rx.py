#!/usr/bin/env python3
"""FPP1 receiver: fpshd's LISTEN83 stream -> one file per pushed image.

Protocol: projects/isp-lab/notes/PUSH_PROTOCOL.md.  Shared by isp-lab and
imx410-lab.  fpshd owns the USB interface; this only talks to its socket.

    push_rx.py listen OUT_DIR [--max 1G] [--idle 3000] [--deadline 60000] [--quiet 1000] [--trigger 'shell line']
    push_rx.py parse STREAM.bin OUT_DIR       offline, from a saved raw stream

Each image: OUT_DIR/<source>_<seq>.bin (the segments, concatenated) plus one
line in OUT_DIR/index.jsonl with every header field.  A bad magic or CRC is
resynchronised by scanning for the next b'FPP1'; the bytes skipped are counted.
"""
import argparse, json, os, pathlib, socket, struct, sys, time, zlib

MAGIC = 0x31505046                          # b'FPP1'
HDR = 256
SOURCES = {1: 'lv', 2: 'bufa1', 3: 'bufa0', 4: 'cdng', 5: 'report'}
FMTS = {1: 'yuyv8', 2: 'bayer8', 3: 'bayer12', 4: 'bayer14', 5: 'dng', 6: 'report'}
SOCK = os.environ.get('FPSHD_SOCKET', '/tmp/fpshd.sock')
MAX_TOTAL = 1 << 30                          # one image never claims more than this


def header_crc(h):
    b = bytearray(h[:HDR])
    b[0x3C:0x40] = b'\0\0\0\0'
    return zlib.crc32(bytes(b)) & 0xFFFFFFFF


def parse_header(h):
    """dict, or None when this is not a valid FPP1 header."""
    if len(h) < HDR:
        return None
    magic, hlen, source, seq, t_us, frame_no, nseg, total = struct.unpack_from('<8I', h, 0)
    if magic != MAGIC or hlen != HDR or not 1 <= nseg <= 48 or total > MAX_TOTAL:
        return None
    w, hh = struct.unpack_from('<HH', h, 0x20)
    fmt, stride, flags, n_skip, aux0, aux1, crc = struct.unpack_from('<7I', h, 0x24)
    segs = list(struct.unpack_from('<48I', h, 0x40))
    if sum(segs[:nseg]) != total or any(segs[nseg:]):
        return None
    if crc and crc != header_crc(h):         # 0 = the engine does not compute one
        return None
    return {'source': SOURCES.get(source, source), 'seq': seq, 't_us': t_us, 'frame_no': frame_no,
            'nseg': nseg, 'total': total, 'w': w, 'h': hh, 'fmt': FMTS.get(fmt, fmt), 'stride': stride,
            'flags': flags, 'n_skip': n_skip, 'aux': [aux0, aux1], 'segs': segs[:nseg], 'crc': bool(crc)}


def make_header(source, seq, segs, t_us=0, frame_no=0, w=0, h=0, fmt=1, stride=0, flags=0,
                n_skip=0, aux=(0, 0), crc=True):
    """The camera's header, for tests and for a host-side reference encoder."""
    b = bytearray(HDR)
    struct.pack_into('<8I', b, 0, MAGIC, HDR, source, seq, t_us, frame_no, len(segs), sum(segs))
    struct.pack_into('<HH', b, 0x20, w, h)
    struct.pack_into('<6I', b, 0x24, fmt, stride, flags, n_skip, aux[0], aux[1])
    struct.pack_into(f'<{len(segs)}I', b, 0x40, *segs)
    if crc:
        struct.pack_into('<I', b, 0x3C, header_crc(b))
    return bytes(b)


class Splitter:
    """Feed bytes in any pieces; get whole images out."""

    def __init__(self, sink):
        self.buf = bytearray()
        self.sink = sink                     # sink(header_dict, payload_bytes)
        self.skipped = 0                     # bytes dropped while resynchronising
        self.resyncs = 0
        self.torn = 0                        # images cut short: the next header was inside them
        self.images = 0
        self.last_seq = {}
        self.gaps = {}                       # source -> images the camera skipped (seq jumps)

    def feed(self, data):
        self.buf += data
        while True:
            if len(self.buf) < HDR:
                return
            h = parse_header(self.buf)
            if h is None:
                i = self.buf.find(b'FPP1', 1)
                drop = i if i > 0 else max(len(self.buf) - 3, 0)   # keep a possible split magic
                self.skipped += drop
                self.resyncs += 1
                del self.buf[:drop]
                continue
            if len(self.buf) < HDR + h['total']:
                return
            cut = self.next_header(HDR, HDR + h['total'])
            if cut is not None:                   # this image never finished: drop it, resume there
                self.torn += 1
                self.skipped += cut
                del self.buf[:cut]
                continue
            payload = bytes(self.buf[HDR:HDR + h['total']])
            del self.buf[:HDR + h['total']]
            prev = self.last_seq.get(h['source'])
            if prev is not None and h['seq'] != prev + 1:
                self.gaps[h['source']] = self.gaps.get(h['source'], 0) + (h['seq'] - prev - 1)
            self.last_seq[h['source']] = h['seq']
            self.images += 1
            self.sink(h, payload)

    def next_header(self, start, end):
        """Offset of a valid CRC-checked header inside buf[start:end], or None.
        Image data could contain b'FPP1'; with the CRC a false match is ~2^-32."""
        i = self.buf.find(b'FPP1', start, end)
        while i >= 0:
            h = parse_header(self.buf[i:i + HDR])
            if h is not None and h['crc']:
                return i
            i = self.buf.find(b'FPP1', i + 1, end)
        return None

    def stats(self):
        return {'images': self.images, 'skipped_bytes': self.skipped, 'resyncs': self.resyncs,
                'torn': self.torn,
                'seq_gaps': self.gaps, 'leftover': len(self.buf)}


def file_sink(out):
    out.mkdir(parents=True, exist_ok=True)
    index = open(out / 'index.jsonl', 'a')

    def sink(h, payload):
        name = f'{h["source"]}_{h["seq"]:06d}.bin'
        (out / name).write_bytes(payload)
        index.write(json.dumps(dict(h, file=name, rx_time=time.time())) + '\n')
        index.flush()
    sink.close = index.close
    return sink


def read_line(conn):
    b = bytearray()
    while not b.endswith(b'\n'):
        c = conn.recv(1)
        if not c:
            raise ConnectionError('fpshd closed the socket')
        b += c
    return b.decode('latin1').rstrip('\n')


def read_exact(conn, n):
    b = bytearray()
    while len(b) < n:
        c = conn.recv(n - len(b))
        if not c:
            raise ConnectionError('fpshd closed mid-block')
        b += c
    return bytes(b)


class ListenerUnsettled(RuntimeError):
    """Cannot prove the daemon has left LISTEN83; camera cleanup must wait."""


def listener_barrier(timeout_ms):
    """Host-only STATUS is handled after the single-threaded listener exits.

    On a broken stream, closing our socket alone does not prove that happened.
    Never follow an uncertain listener with camera writes until this returns.
    """
    try:
        with socket.socket(socket.AF_UNIX) as conn:
            conn.settimeout(timeout_ms / 1000 + 30)
            conn.connect(SOCK)
            conn.sendall(b'STATUS\n')
            if not read_line(conn).startswith('OK name=fpshd '):
                raise ConnectionError('STATUS did not identify fpshd')
    except Exception as exc:
        raise ListenerUnsettled('LISTEN83 did not settle: no camera cleanup is safe yet') from exc


def listen(out, max_bytes, idle_ms, deadline_ms, quiet_ms=1000, trigger=None, raw_copy=True):
    """Run LISTEN83 and honor its quiet period before returning or raising.

    Returns (END83 fields, REPLY or None, splitter stats).  ListenerUnsettled
    means its host-only completion barrier failed; do not send camera cleanup.
    """
    if quiet_ms < 0:
        raise ValueError('quiet_ms must be nonnegative')
    out.mkdir(parents=True, exist_ok=True)
    sink = file_sink(out)
    sp = Splitter(sink)
    raw = open(out / 'stream.raw', 'ab') if raw_copy else None
    cmd = f'LISTEN83 {max_bytes} {idle_ms} {deadline_ms} q={quiet_ms}' + (f' {trigger}' if trigger else '')
    submitted = completed = False
    try:
        with socket.socket(socket.AF_UNIX) as conn:
            conn.settimeout(deadline_ms / 1000 + 30)
            conn.connect(SOCK)
            submitted = True
            conn.sendall(cmd.encode() + b'\n')
            first = read_line(conn)
            if not first.startswith('OK83L'):
                raise RuntimeError(first)
            while True:
                n, = struct.unpack('<I', read_exact(conn, 4))
                if not n:
                    break
                data = read_exact(conn, n)
                if raw:
                    raw.write(data)
                sp.feed(data)
            end = read_line(conn).split()
            if len(end) != 6 or end[0] != 'END83':
                raise RuntimeError(f'malformed END83: {end!r}')
            reply = read_line(conn) if trigger else None
            completed = True
    finally:
        if raw:
            raw.close()
        sink.close()
        if submitted:
            if not completed:
                listener_barrier(deadline_ms)
            # fpshd starts the quiet interval BEFORE writing END83.  Waiting
            # from its receipt (or STATUS after an error) is conservative.
            time.sleep(quiet_ms / 1000)
    fields = dict(zip(('tag', 'bytes', 'reason', 'rc', 'trigger', 'reply_len'), end))
    stats = sp.stats()
    (out / 'listen.json').write_text(json.dumps({'cmd': cmd, 'end': fields, 'reply': reply, 'stats': stats}, indent=1))
    return fields, reply, stats


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    l = sub.add_parser('listen'); l.add_argument('out', type=pathlib.Path)
    l.add_argument('--max', type=lambda s: int(float(s[:-1]) * (1 << {'K': 10, 'M': 20, 'G': 30}[s[-1]])) if s[-1] in 'KMG' else int(s), default=1 << 30)
    l.add_argument('--idle', type=int, default=3000)
    l.add_argument('--deadline', type=int, default=60000)
    l.add_argument('--quiet', type=int, default=1000)
    l.add_argument('--trigger')
    p = sub.add_parser('parse'); p.add_argument('stream', type=pathlib.Path); p.add_argument('out', type=pathlib.Path)
    a = ap.parse_args()
    if a.cmd == 'parse':
        sink = file_sink(a.out)
        sp = Splitter(sink)
        try:
            sp.feed(a.stream.read_bytes())
        finally:
            sink.close()
        print(json.dumps(sp.stats()))
        return
    end, reply, stats = listen(a.out, a.max, a.idle, a.deadline, a.quiet, a.trigger)
    print(json.dumps({'end': end, 'reply': reply, 'stats': stats}))


if __name__ == '__main__':
    main()
