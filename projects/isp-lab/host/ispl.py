#!/usr/bin/env python3
"""ISP Lab host tool: a take into camera DRAM, started and stopped by the sup.

    ispl.py status
    ispl.py take [--mb 192] [--keep-first 4] [--every-ms 500] [--start-ms 1500] [--rec-ms 3000]
                                  lend memory, arm, then stay SILENT: the sup presses
                                  REC start-ms later and again rec-ms after that
    ispl.py pull OUT_DIR          records -> DNG files, block log -> log.json
    ispl.py disarm                back to writing the card, memory returned

Fork of projects/imx410-lab/imxl.py (sha256 in ../sup/UPSTREAM.sha256 is the sup's;
this tool borrows imxl.heap() for the allocator call).  Differences:
  - ix_cap v2: keep policy, block log, ctl (RESEARCH_PLAN §6)
  - "recording?" asks the native getter (status get is_recording), not one
    flag byte: memory movie-recording-flag-selector, the flag has two homes
  - `take` sends nothing between the arm and start+rec+10 s

Rules (memory no-usb-during-rec-or-playback): nothing is sent while
recording or within 10 s of the stop.  The card still gets the clip's
directory entries but no frame data: those clips are empty.
"""
import argparse, json, os, pathlib, re, struct, subprocess, sys, time

HERE = pathlib.Path(__file__).resolve().parent
LAB = HERE.parent
ROOT = LAB.parents[1]
SHELL = ROOT / 'fpSup' / 'fp_usb_shell'
IMXL = ROOT / 'projects' / 'imx410-lab'
sys.path[:0] = [str(LAB / 'sup'), str(SHELL)]
import ispl_records as R                                     # noqa: E402

BUILD_JSON = LAB / 'sup' / 'build' / 'build.json'
SUP_FILE = 'ISPL.BIN'
ALLOC_KEEP = HERE / '.ispl_alloc.json'      # what we borrowed, to give it back
MIN_CHUNK = 256 << 10
CHUNK = 4 << 20                             # 10-23: class 0 refused 16 MiB, gave 4 (records span chunks)
LOG_BYTES = 256 << 10                       # 16384 block lines
WIN_SLOT = 7
WIN_W = 2048                                # covers +8 .. +8+1 KiB-rounded cap
F_DCACHE = 0xC000E91C                       # whole L1+L2 clean+invalidate (CPU_GLOBAL_CONFIG.md)
QUIET_AFTER_S = 15                          # after the planned stop: movsavewai + the 10 s rule


def P():
    import putfile
    return putfile


def build():
    return json.loads(BUILD_JSON.read_text())


def block_addr():
    if os.environ.get('ISPL_BLOCK'):
        return int(os.environ['ISPL_BLOCK'], 0)
    out = HERE / '.LOAD.LOG'
    subprocess.run([sys.executable, '-B', str(SHELL / 'getfile.py'), r'\fpSup\LOAD.LOG', str(out),
                    '--size', '0x2000', '--partial'], check=True, cwd=SHELL)
    return parse_load_log(out.read_text('ascii', 'replace'))


def parse_load_log(text, name=None):
    name = name or SUP_FILE
    for line in text.splitlines():
        m = re.match(r'^0A ([0-9A-F]{8}) [0-9A-F]{8} ?' + re.escape(name), line.strip(), re.I)
        if m:
            return int(m.group(1), 16)
    raise SystemExit(f"{name} is not LOADED in this boot's LOAD.LOG")


def use_ctl_only():
    """ISPC.BIN (RESEARCH_PLAN §7 step 1): the control task alone; stock writes the card."""
    global BUILD_JSON, SUP_FILE
    BUILD_JSON = LAB / 'sup' / 'build' / 'build-ctl.json'
    SUP_FILE = 'ISPC.BIN'


def cap_addr(block, info):
    """The sink at its UNCACHED alias: MEM1 windows only cover 0x40000000..0x80000000.
    The sup itself works through the cached alias, so every host read is
    preceded, and every host write surrounded, by flush() (10-23 first run)."""
    uncached = block - 0x80000000 if block >= 0xC0000000 else block
    return uncached + info['state_at'] + info['cap_off']


def flush():
    """Clean+invalidate the camera's caches: the sup's counters reach memory
    before we read them; our writes are not hidden behind its stale lines."""
    sys.path.insert(0, str(SHELL))
    import callfn
    # The maintained callfn owns 'callfn.code' (IMX410_RULES §71).  Reuse it:
    # a second ISP-specific claim wastes cave space and rewrites a fresh stub.
    ok, _ = callfn.call(F_DCACHE)
    if not ok:
        raise SystemExit('cache flush did not return')


def read_cap(api, at):
    flush()
    window(api, at, R.CAP_BYTES, 1)                         # MEM1 reads need a window too
    try:
        cap = R.parse_cap(api.mem_read(at, R.CAP_BYTES, label='sink  '))
    finally:
        window(api, at, R.CAP_BYTES, 0)
    if cap['magic'] != R.CAP_MAGIC or cap['version'] != R.CAP_VERSION:
        raise SystemExit(f'no ISPL v{R.CAP_VERSION} sink at 0x{at:08X} '
                         f'(magic {cap["magic"]:#x} v{cap["version"]}): wrong block or build')
    return cap


def not_recording(api):
    reply = api.sh('status get is_recording')
    m = re.search(r'(\d+)\s*$', reply.strip())
    if not m:
        raise SystemExit(f'could not read the record state: {reply!r}')
    if int(m.group(1)):
        raise SystemExit('the camera is recording: not sending anything')


def window(api, base, length, perm):
    api.mem_window(WIN_SLOT, base, length, perm)


def cap_image(mode, chunks, keep_first=0, every_us=0, log=(0, 0), start_ms=0, rec_ms=0):
    """ix_cap from +8 (mode) to the end: host fields set, counters zero, ctl idle."""
    body = bytearray(R.CAP_BYTES - 8)
    struct.pack_into('<II', body, 0, R.MODES[mode], len(chunks))
    for i, (a, n) in enumerate(chunks):
        struct.pack_into('<II', body, R.O_CHUNK - 8 + 8 * i, a, n)
    for k, v in (('keep_first', keep_first), ('every_us', every_us), ('log_addr', log[0]),
                 ('log_max', log[1]), ('ctl', R.CTL['idle']), ('start_ms', start_ms), ('rec_ms', rec_ms)):
        struct.pack_into('<I', body, R.OFF[k] - 8, v)
    return bytes(body)


def write_cap(api, at, mode, chunks, ctl=False, **kw):
    """Everything with mode = sd and ctl idle first; then the mode word; then
    (take only) ctl = armed, the very last thing this tool sends before the take."""
    body = bytearray(cap_image(mode, chunks, **kw))
    struct.pack_into('<I', body, 0, R.MODES['sd'])
    flush()                                     # nothing of the sup's dirty may land on top later
    window(api, at, WIN_W, 3)                   # MEMW checks a write at its 1 KiB-rounded length
    try:
        api.mem_write(at + 8, bytes(body), label='sink  ')
        flush()
        api.mem_write(at + 8, struct.pack('<I', R.MODES[mode]), label='mode  ')
        flush()
        if ctl:
            api.mem_write(at + R.OFF['ctl'], struct.pack('<I', R.CTL['armed']), label='ctl   ')
            flush()                             # the control task must see it: invalidate
    finally:
        window(api, at, WIN_W, 0)


def uncached(addr):
    return addr - 0x80000000 if addr >= 0xC0000000 else addr


def lend(want, heap, held, limit):
    """Append (address, descriptor, bytes) pieces to `held` until `want` more
    bytes or `limit` pieces; halve the piece on a refusal.  `held` is saved
    after every piece, so a crash still leaves a list to give back."""
    got, size = 0, CHUNK
    while got < want and len(held) < limit:
        n = min(size, want - got)
        addr, desc = heap(0, n)
        if not addr:
            if size > MIN_CHUNK:                      # try smaller pieces before giving up
                size //= 2
                continue
            print(f'allocator refused after {got / 2**20:.2f} MiB', file=sys.stderr)
            break
        held.append((addr, desc, n))
        ALLOC_KEEP.write_text(json.dumps(held))
        got += n
    return held


def give_back(held, heap):
    for _addr, desc, _n in held:
        heap(1, 0, desc)
    ALLOC_KEEP.unlink(missing_ok=True)


def imxl_heap():
    sys.path.insert(0, str(IMXL))
    import imxl                               # its heapalloc.S-through-echo call, class 0
    imxl.HEAP_CLASS = 0                       # memory bufmem-get-wedges-shell / allocator-not-across-recording
    return imxl.heap


def cmd_status(a, api=None):
    api = api or P()
    info = build()
    at = cap_addr(block_addr(), info)
    cap = read_cap(api, at)
    print(summary(cap))


def summary(cap):
    mode = {v: k for k, v in R.MODES.items()}.get(cap['mode'], cap['mode'])
    ctl = {v: k for k, v in R.CTL.items()}.get(cap['ctl'], cap['ctl'])
    lent = sum(n for _, n in cap['chunks'][:cap['nchunk']])
    lines = [f'mode {mode}  ctl {ctl}  lent {lent >> 20} MiB in {cap["nchunk"]} chunks  used {cap["used"] / 2**20:.1f} MiB',
             f'kept {cap["n_rec"]}  skipped {cap["n_skip"]}  full {cap["n_full"]}  discard {cap["n_discard"]}  '
             f'sd {cap["n_sd"]}  log {cap["log_n"]}  presses {cap["n_press"]}',
             f'last shell line: {R.SH_LINES.get(cap["ctl_line"], cap["ctl_line"])}  '
             f'recstate started {cap["rs_started"]} saved {cap["rs_saved"]}']
    if cap['t_rec'] and cap['t_stop']:
        lines.append(f'REC pressed at +{(cap["t_rec"] - cap["t_arm"]) / 1e3:.0f} ms, '
                     f'stopped {(cap["t_stop"] - cap["t_rec"]) / 1e3:.0f} ms later')
    if cap['n_rec']:
        lines.append(f'copy {cap["copy_us"] / 1e3:.0f} ms total, worst {cap["copy_max_us"] / 1e3:.1f} ms '
                     f'({cap["used"] / max(cap["copy_us"], 1):.1f} MB/s)')
    return '\n'.join(lines)


def cmd_take(a, api=None, heap=None, sleep=time.sleep):
    api = api or P()
    heap = heap or (None if SUP_FILE == 'ISPC.BIN' else imxl_heap())
    not_recording(api)
    info = build()
    at = cap_addr(block_addr(), info)
    cap = read_cap(api, at)
    if cap['mode'] != R.MODES['sd'] or (SUP_FILE != 'ISPC.BIN' and ALLOC_KEEP.exists()):
        raise SystemExit('already armed: pull and/or disarm first')
    if a.focus:                                             # half press: AF (S2 would toggle REC in CINE)
        api.sh('key S1ON'); sleep(a.focus_ms / 1000); api.sh('key S1OFF')
    if SUP_FILE == 'ISPC.BIN':                              # control only: nothing lent, nothing captured
        write_cap(api, at, 'sd', [], ctl=True, start_ms=a.start_ms, rec_ms=a.rec_ms)
        quiet = (a.start_ms + a.rec_ms) / 1000 + QUIET_AFTER_S
        print(f'armed (control only): REC in {a.start_ms} ms for {a.rec_ms} ms, stock writes the card. '
              f'Silent for {quiet:.0f} s.', flush=True)
        sleep(quiet)
        try:
            not_recording(api)
        except SystemExit:
            raise SystemExit('still recording after the planned stop: stop it on the camera (REC), wait 10 s, then `status`')
        print(summary(read_cap(api, at)))
        return
    held = []
    try:
        lend(LOG_BYTES, heap, held, 1)                      # the log first: small, always fits
        lend(a.mb << 20, heap, held, 1 + R.MAX_CHUNK)
        if len(held) < 2 or held[0][2] != LOG_BYTES:
            raise SystemExit('not enough memory lent for records and the log')
        log = held[0]
        chunks = [(uncached(addr), n) for addr, _, n in held[1:]]
        log_at = uncached(log[0])
        write_cap(api, at, 'capture', chunks, ctl=True, keep_first=a.keep_first,
                  every_us=a.every_ms * 1000, log=(log_at, log[2] // R.LOG.size),
                  start_ms=a.start_ms, rec_ms=a.rec_ms)
    except BaseException:
        give_back(held, heap)
        raise
    ALLOC_KEEP.write_text(json.dumps(held))
    quiet = (a.start_ms + a.rec_ms) / 1000 + QUIET_AFTER_S
    print(f'armed: {sum(n for _, n in chunks) >> 20} MiB, keep first {a.keep_first} then one per {a.every_ms} ms; '
          f'REC in {a.start_ms} ms for {a.rec_ms} ms. Silent for {quiet:.0f} s.', flush=True)
    sleep(quiet)                                            # nothing is sent in here
    try:
        not_recording(api)
    except SystemExit:
        raise SystemExit('still recording after the planned stop: stop it on the camera (REC), '
                         'wait 10 s, then `status` shows where the control task got to')
    print(summary(read_cap(api, at)))


def cmd_pull(a, api=None):
    api = api or P()
    not_recording(api)
    at = cap_addr(block_addr(), build())
    cap = read_cap(api, at)
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    chunks = cap['chunks'][:cap['nchunk']]
    stream = read_lent(api, chunks, cap['used'])
    (out / 'stream.bin').write_bytes(stream)
    recs = list(R.records(stream, cap['used']))
    log = R.log_lines(read_lent(api, [(cap['log_addr'], cap['log_max'] * R.LOG.size)],
                                cap['log_n'] * R.LOG.size), cap['log_n']) if cap['log_n'] else []
    meta = {k: v for k, v in cap.items() if k != 'chunks'}
    meta['chunks'] = chunks
    meta['records'] = [{k: v for k, v in r.items() if k != 'data'} for r in recs]
    meta['log_check'] = check_log(log, cap)
    (out / 'cap.json').write_text(json.dumps(meta, indent=1))
    (out / 'log.json').write_text(json.dumps(log, indent=0))
    n = split_dngs(recs, out / 'frames')
    print(summary(cap))
    print(f'{len(recs)} records -> {n} DNG files in {out}/frames; log {len(log)} blocks, {meta["log_check"]}')


def read_lent(api, chunks, used):
    data, left = bytearray(), used
    for addr, n in chunks:
        take = min(n, left)
        if take <= 0:
            break
        window(api, addr, take, 1)
        try:
            data += api.mem_read(addr, take, label='pull  ')
        finally:
            window(api, addr, take, 0)
        left -= take
    return bytes(data)


def check_log(log, cap):
    """Blocks the writer took, in order, none missing (seq consecutive); frames per block."""
    seqs = [l['seq'] for l in log]
    gaps = [b - a for a, b in zip(seqs, seqs[1:]) if b - a != 1]
    return {'blocks': len(log), 'frames': sum(l['ncookie'] for l in log), 'seq_gaps': gaps,
            'accounted': len(log) == cap['n_rec'] + cap['n_skip'] + cap['n_full'] + cap['n_discard'] + cap['n_sd'],
            'log_full': cap['log_n'] >= cap['log_max']}


def split_dngs(recs, d, cluster=None):
    """imxl.py's: files start on a cluster boundary with a TIFF header; one may span records."""
    d.mkdir(exist_ok=True)
    recs = sorted(recs, key=lambda r: r['cl'])
    runs = []
    cluster = cluster or guess_cluster(recs)
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
    from math import gcd
    g = 0
    for r in recs:
        g = gcd(g, len(r['data']))
    return g or 512


def cmd_disarm(a, api=None, heap=None):
    api = api or P()
    not_recording(api)
    at = cap_addr(block_addr(), build())
    write_cap(api, at, 'sd', [])
    if ALLOC_KEEP.exists():
        give_back([tuple(h) for h in json.loads(ALLOC_KEEP.read_text())], heap or imxl_heap())
    print('disarmed: the next take writes the card')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--ctl-only', action='store_true', help='drive ISPC.BIN (control task alone, no capture)')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('status').set_defaults(f=cmd_status)
    s = sub.add_parser('take'); s.set_defaults(f=cmd_take)
    s.add_argument('--mb', type=int, default=192)
    s.add_argument('--keep-first', type=int, default=4)
    s.add_argument('--every-ms', type=int, default=500)
    s.add_argument('--start-ms', type=int, default=3000)
    s.add_argument('--rec-ms', type=int, default=3000)
    s.add_argument('--no-focus', dest='focus', action='store_false', help='skip the half-press AF before arming')
    s.add_argument('--focus-ms', type=int, default=1500)
    s = sub.add_parser('pull'); s.set_defaults(f=cmd_pull); s.add_argument('out')
    sub.add_parser('disarm').set_defaults(f=cmd_disarm)
    a = ap.parse_args()
    if a.ctl_only:
        use_ctl_only()
    a.f(a)


if __name__ == '__main__':
    main()
