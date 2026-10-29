#!/usr/bin/env python3
"""IMX410 Lab host tool, stage C-a: a take into camera DRAM instead of the card.

    imxl.py status                       where the sink is, what it holds
    imxl.py arm [--mb 192] [--mode capture|discard]
                                          lend memory, then record (button or key MOVON)
    imxl.py pull OUT_DIR                  after the stop (wait 10 s): records -> DNG files
    imxl.py disarm                        back to writing the card, memory returned

Rules this follows (memory: no-usb-during-rec-or-playback, record-freeze-was-host-poll):
nothing is sent while recording or within 10 s of the stop; arm/pull/disarm
refuse to run when the camera's record flag is set.  The sink itself never
touches USB.  The card still gets the clip's directory entries (stock's file
system runs as usual) but no frame data: delete those clips afterwards.

Where the sink is: LOAD.LOG's LOADED line for IMXL.BIN gives the block; the
state is at build.json's state_at, the sink at +cap_off (cached alias).
Override with IMXL_BLOCK=0x... when LOAD.LOG cannot be read.
"""
import argparse, json, os, pathlib, re, struct, subprocess, sys, time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SHELL = ROOT / 'fpSup' / 'fp_usb_shell'
sys.path[:0] = [str(HERE / 'sup'), str(SHELL)]
import imxl_records as R                                     # noqa: E402

BUILD = json.loads((HERE / 'sup' / 'build' / 'build.json').read_text())
ALLOC_KEEP = HERE / '.imxl_alloc.json'      # what we borrowed, to give it back
CHUNK = 16 << 20                            # heapalloc.S verified to 32 MiB; 16 is the shell's habit
HEAP_CLASS = 0                              # memory bufmem-get-wedges-shell: 0, not 10
REC_FLAG = 0xC347E08F                       # MovieRecording +0x157 (memory movie-recording-flag-selector)
WIN_SLOT = 7


def P():
    import putfile
    return putfile


def block_addr():
    if os.environ.get('IMXL_BLOCK'):
        return int(os.environ['IMXL_BLOCK'], 0)
    out = HERE / '.LOAD.LOG'
    subprocess.run([sys.executable, '-B', str(SHELL / 'getfile.py'), r'\fpSup\LOAD.LOG', str(out),
                    '--size', '0x2000', '--partial'], check=True, cwd=SHELL)
    for line in out.read_text('ascii', 'replace').splitlines():
        m = re.match(r'^0A ([0-9A-F]{8}) [0-9A-F]{8} ?IMXL\.BIN', line.strip(), re.I)
        if m:
            return int(m.group(1), 16)
    raise SystemExit('IMXL.BIN is not LOADED in this boot\'s LOAD.LOG')


def cap_addr():
    b = block_addr()
    cached = b + 0x80000000 if 0x40000000 <= b < 0x80000000 else b
    return cached + BUILD['state_at'] + BUILD['cap_off']


def read_cap(at):
    raw = P().mem_read(at, R.CAP_BYTES, label='sink  ')
    cap = R.parse_cap(raw)
    if cap['magic'] != R.CAP_MAGIC or cap['version'] != 1:
        raise SystemExit(f'no IMXL sink at 0x{at:08X} (magic {cap["magic"]:#x}): wrong block or build')
    return cap


def not_recording():
    v = P().mem_get(REC_FLAG & ~3)[0]
    if v is None:
        raise SystemExit('could not read the record flag')
    if (v >> (8 * (REC_FLAG & 3))) & 0xFF:
        raise SystemExit('the camera is recording: not sending anything')


def window(base, length, perm):
    P().mem_window(WIN_SLOT, base, length, perm)


def heap(op, size=0, desc=None):
    """asm/heapalloc.S through the echo slot (fpSup/gyro/heap_survives.py's way).
    Allocate: -> (address, descriptor words).  Free: put that allocation's
    16-byte descriptor back at +0xE0 first -- heapalloc frees whatever it names."""
    from armasm import assemble
    import cave, struct as _st
    p = P()
    # Its own code block (2026-10-24), not the shared p.CODE: callfn and this took turns writing their code there and
    # running it through echo with no I-cache maintenance in between, so the CPU could run the OTHER one's stale
    # instructions with this one's parameters (callfn jumping to "address" 0 = op alloc; heapalloc freeing callfn's
    # words). Written once per boot here, re-checked each time, never overwritten by anything else.
    code = assemble(SHELL / 'asm' / 'heapalloc.S', [f'P=0x{p.P:08X}'])
    at = cave.claim('imxl.heap.code', 256)
    if len(code) > 256:
        raise SystemExit(f'heapalloc is {len(code)} B, claim is 256')
    n = (len(code) + 3) // 4
    cur = p.mem_get(at, n)
    if None in cur or _st.pack(f'<{n}I', *cur) != code + bytes(-len(code) % 4):
        p.put(at, code, 'heap  ')
        from callfn import call as _call
        _call(0xC000E91C, verbose=False)        # D-clean / I-invalidate before the first run of the new bytes
    orig = p.mem_get(p.ECHO_SLOT)
    if not orig or orig[0] not in (p.ECHO_ORIG, p.CODE, at):
        raise SystemExit(f'echo handler is {orig}, not free to borrow')
    want = [op, HEAP_CLASS, size, 0] + list(desc or [])
    try:
        p.mem_set(p.ECHO_SLOT, at)
        for _ in range(5):                      # mem set drops writes now and then (memory: shell-mem-set-drops-writes)
            for off, val in ((0x00, op), (0x04, HEAP_CLASS), (0x08, size), (0x0C, 0)):
                p.mem_set(p.P + off, val)
            for i, val in enumerate(desc or []):
                p.mem_set(p.P + 0xE0 + 4 * i, val)
            got = p.mem_get(p.P, 4) + (p.mem_get(p.P + 0xE0, 4) if desc else [])
            if got == want:
                break
        else:
            raise SystemExit(f'heap parameters did not land: {got}')
        p.sh('echo', retries=1)
        if op:
            return None
        return p.mem_get(p.P + 0x0C)[0], p.mem_get(p.P + 0xE0, 4)
    finally:
        for _ in range(10):
            p.mem_set(p.ECHO_SLOT, p.ECHO_ORIG)
            if (p.mem_get(p.ECHO_SLOT) or [0])[0] == p.ECHO_ORIG:
                break


def write_cap(at, mode, chunks):
    """Counters zeroed and chunks first, the mode word last (the writer reads it per block)."""
    body = bytearray(R.CAP_BYTES - 8)
    struct.pack_into('<II', body, 0, R.MODES['sd'], len(chunks))
    for i, (a, n) in enumerate(chunks):
        struct.pack_into('<II', body, 8 + 8 * i, a, n)
    window(at, R.CAP_BYTES, 3)
    try:
        P().mem_write(at + 8, bytes(body), label='sink  ')
        P().mem_write(at + 8, struct.pack('<I', R.MODES[mode]), label='mode  ')
    finally:
        window(at, R.CAP_BYTES, 0)


def cmd_status(a):
    at = cap_addr()
    cap = read_cap(at)
    mode = {v: k for k, v in R.MODES.items()}.get(cap['mode'], cap['mode'])
    lent = sum(n for _, n in cap['chunks'][:cap['nchunk']])
    print(f'sink 0x{at:08X}  mode {mode}  lent {lent >> 20} MiB in {cap["nchunk"]} chunks  '
          f'used {cap["used"] / 2**20:.1f} MiB')
    print(f'records {cap["n_rec"]}  full {cap["n_full"]}  discard {cap["n_discard"]}  sd {cap["n_sd"]}')
    if cap['n_rec']:
        span = (cap['t_last'] - cap['t_first']) / 1e6
        print(f'span {span:.2f} s  copy {cap["copy_us"] / 1e3:.0f} ms total, worst {cap["copy_max_us"] / 1e3:.1f} ms '
              f'({cap["used"] / max(cap["copy_us"], 1):.1f} MB/s)')


def cmd_arm(a):
    not_recording()
    at = cap_addr()
    cap = read_cap(at)
    if cap['mode'] != R.MODES['sd'] or ALLOC_KEEP.exists():
        raise SystemExit('already armed: pull and/or disarm first')
    chunks, held = [], []                   # held: (address, descriptor) to give back
    if a.mode == 'capture':
        want = a.mb << 20
        try:
            while sum(n for _, n in chunks) < want:
                n = min(CHUNK, want - sum(n for _, n in chunks))
                addr, desc = heap(0, n)
                if not addr:
                    print(f'allocator refused after {sum(n for _, n in chunks) >> 20} MiB', file=sys.stderr)
                    break
                held.append((addr, desc))
                ALLOC_KEEP.write_text(json.dumps(held))
                # the sink takes the uncached alias only
                chunks.append((addr - 0x80000000 if addr >= 0xC0000000 else addr, n))
        except BaseException:
            give_back(held)
            ALLOC_KEEP.unlink(missing_ok=True)
            raise
        if not chunks:
            raise SystemExit('nothing lent')
    write_cap(at, a.mode, chunks)
    ALLOC_KEEP.write_text(json.dumps(held))
    cap = read_cap(at)
    print(f'armed: {a.mode}, {sum(n for _, n in chunks) >> 20} MiB in {len(chunks)} chunks. '
          f'Record now; wait 10 s after the stop before `pull`.')


def give_back(held):
    for _addr, desc in held:
        heap(1, 0, desc)


def cmd_pull(a):
    not_recording()
    at = cap_addr()
    cap = read_cap(at)
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    chunks = cap['chunks'][:cap['nchunk']]
    stream, left = bytearray(), cap['used']
    for addr, n in chunks:
        take = min(n, left)
        if take <= 0:
            break
        window(addr, take, 1)
        try:
            stream += P().mem_read(addr, take, label='pull  ')
        finally:
            window(addr, take, 0)
        left -= take
    (out / 'stream.bin').write_bytes(stream)
    recs = list(R.records(stream, cap['used']))
    meta = {k: v for k, v in cap.items() if k != 'chunks'}
    meta['chunks'] = chunks
    meta['records'] = [{k: v for k, v in r.items() if k != 'data'} for r in recs]
    (out / 'cap.json').write_text(json.dumps(meta, indent=1))
    n = split_dngs(recs, out / 'frames')
    print(f'{len(recs)} records, {len(stream) / 2**20:.1f} MiB -> {n} DNG files in {out}/frames')


def split_dngs(recs, d, spc_bytes=None):
    """Files start on a cluster boundary with a TIFF header; a file may span records."""
    d.mkdir(exist_ok=True)
    recs = sorted(recs, key=lambda r: r['cl'])
    image, runs = bytearray(), []           # contiguous runs of clusters
    cluster = spc_bytes or guess_cluster(recs)
    for r in recs:
        if runs and r['cl'] == runs[-1][1]:
            runs[-1][1] = r['cl'] + len(r['data']) // cluster
            runs[-1][2] += r['data']
        else:
            runs.append([r['cl'], r['cl'] + len(r['data']) // cluster, bytearray(r['data'])])
    n = 0
    for _, _, data in runs:
        starts = [o for o in range(0, len(data), cluster) if data[o:o + 4] in (b'II*\0', b'MM\0*')]
        for i, s in enumerate(starts):
            e = starts[i + 1] if i + 1 < len(starts) else len(data)
            (d / f'F{n:05d}.dng').write_bytes(data[s:e])
            n += 1
    return n


def guess_cluster(recs):
    """Every record's data is whole clusters: their gcd is the cluster size."""
    from math import gcd
    g = 0
    for r in recs:
        g = gcd(g, len(r['data']))
    return g or 512


def cmd_disarm(a):
    not_recording()
    at = cap_addr()
    write_cap(at, 'sd', [])
    if ALLOC_KEEP.exists():
        give_back(json.loads(ALLOC_KEEP.read_text()))
        ALLOC_KEEP.unlink()
    print('disarmed: the next take writes the card (ULWR behaviour)')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('status').set_defaults(f=cmd_status)
    s = sub.add_parser('arm'); s.set_defaults(f=cmd_arm)
    s.add_argument('--mb', type=int, default=192)
    s.add_argument('--mode', choices=('capture', 'discard'), default='capture')
    s = sub.add_parser('pull'); s.set_defaults(f=cmd_pull); s.add_argument('out')
    sub.add_parser('disarm').set_defaults(f=cmd_disarm)
    a = ap.parse_args()
    a.f(a)


if __name__ == '__main__':
    main()
