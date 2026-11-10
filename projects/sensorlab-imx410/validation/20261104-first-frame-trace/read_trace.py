#!/usr/bin/env python3
"""Read and decode SensorLab v0.7.27test's first-frame trace (sq_test 33; struct ap_trace in apply/ap.c).

    python3 -B read_trace.py --load-log RUN/LOAD-current.LOG [--version 0.7.27test --build default-build/build-0.7.27test.json]
                             [--out RUN/trace.jsonl]        # camera: callfn sq_test(33) + mem get, only when idle
    python3 -B read_trace.py --words dump.json              # offline: a list of the 688 words already read

Camera use: after a SensorLab take has STOPPED and the camera is idle (never during recording or playback; the shell
refuses otherwise).  Reads only: sq_test(33, a=0) -> the trace address, then mem get of 16 + 12 x 56 words.
"""
import argparse, json, pathlib, sys, time

HERE = pathlib.Path(__file__).resolve().parent
HDR, RW, N = 16, 56, 12
KINDS = {1: 'arm', 2: 'done', 3: 'write'}
HKEYS = 'magic ver rec_words nmax n lost take live seed row rows id done writes'.split()
RKEYS = 'kind seq epoch raw us tg_frame tg_line tg_flags ras x0 x1 x2 x3 ok'.split()
X = {1: ('mode', 'r2210_lines', 'r2214_words_prev', 'r2218_chunk'), 2: ('r21E8', 'r2280_dest', 'n', 'r2048_irq'),
     3: ('frame_id', 'frame', 'n', '-')}


def sentinel(seed):
    x, out = seed, []
    for _ in range(16):
        x ^= (x << 13) & 0xFFFFFFFF; x ^= x >> 17; x ^= (x << 5) & 0xFFFFFFFF
        out.append(x)
    return out


def tick_us(epoch, raw):
    """C002B6E0's conversion with period 12,000,000 (fp-af-assist NATIVE_HOOK_PLAN §8): epoch*1e6 + raw//12, mod 2^32;
    the pending-bit correction of C002B4E0 is not applied (the IRQ site cannot call it): +-1 s at a wrap"""
    return (epoch * 1000000 + raw // 12) & 0xFFFFFFFF


def decode(words):
    if len(words) < HDR + N * RW:
        raise SystemExit(f'want {HDR + N * RW} words, got {len(words)}')
    h = dict(zip(HKEYS, words[:14]))
    if h['magic'] != 0x52544653 or h['ver'] != 1 or h['rec_words'] != RW:
        raise SystemExit(f'not a v1 trace: {h}')
    sent = sentinel(h['seed'])
    recs = []
    for i in range(min(h['n'], N)):
        w = words[HDR + i * RW:HDR + (i + 1) * RW]
        r = dict(zip(RKEYS, w[:14]))
        r['kind'] = KINDS.get(r['kind'], r['kind'])
        r.update(zip(X.get(w[0], ('x0', 'x1', 'x2', 'x3')), w[9:13]))
        for k in ('x0', 'x1', 'x2', 'x3'):
            r.pop(k)
        r.pop('tg_frame'); r.pop('tg_line')    # words 5-6: 0x30100588 / 590 read 0 / non-counter values live (11-04)
        r['t_us'] = tick_us(r['epoch'], r['raw'])
        r['head0'], r['tail0'], r['head1'], r['tailn'] = w[14:22], w[22:38], w[38:46], w[46:54]
        r['sentinel'] = r['ok'] == 1 and r['tail0'] == sent           # row 0's tail never written by BUFA1
        recs.append(r)
    return h, recs


def verdict(h, recs):
    """frame 1 = the first completion / writer record"""
    done = [r for r in recs if r['kind'] == 'done']
    wr = [r for r in recs if r['kind'] == 'write']
    out = dict(take=h['take'], records=h['n'], lost=h['lost'], completions=len(done), writer=len(wr))
    if not done or not wr:
        out['verdict'] = 'incomplete: no completion or writer record for frame 1'
        return out
    d, w = done[0], wr[0]
    out['frame1_raster_same'] = (d['ras'] & 0x3FFFFFFF) == (w['ras'] & 0x3FFFFFFF)
    out['frame1_shifted_at_completion'] = d['sentinel']
    out['frame1_shifted_at_writer'] = w['sentinel']
    same = all(d[k] == w[k] for k in ('head0', 'tail0', 'head1', 'tailn'))
    out['frame1_digest_unchanged_completion_to_writer'] = same
    out['completion_to_writer_us'] = (w['t_us'] - d['t_us']) & 0xFFFFFFFF
    out['frames_digest_unchanged'] = [all(a[k] == b[k] for k in ('head0', 'tail0', 'head1', 'tailn'))
                                      for a, b in zip(done, wr)]
    if d['sentinel']:
        out['verdict'] = 'capture side: frame 1 is already shifted when BUFA1 reports it complete (row 0 tail never written)'
    elif w['sentinel'] or not same:
        out['verdict'] = 'hand-off / cache side: frame 1 was complete at BUFA1 completion, changed before the writer'
    else:
        out['verdict'] = 'normal take: frame 1 complete at both points'
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--words', help='offline: JSON list of the trace words')
    p.add_argument('--load-log')
    p.add_argument('--version')
    p.add_argument('--build')
    p.add_argument('--tag', default='')
    p.add_argument('--out')
    a = p.parse_args(argv)
    if a.words:
        words = json.loads(pathlib.Path(a.words).read_text())
    else:
        if not a.load_log:
            raise SystemExit('--load-log (camera) or --words (offline)')
        sys.path.insert(0, str(HERE.parents[1] / 'tools/live'))
        import dc_probe as D
        block, ver = D.parse_load_log(pathlib.Path(a.load_log).read_bytes().decode('latin1'), a.version)
        b = D.load_build(ver, a.build)
        D.idle()
        cam = D.Cam(block, b['sq_test_off'])
        addr = cam.op(33)
        if not addr:
            raise SystemExit('sq_test(33) returned 0')
        # 11-04 live: one 688-word `mem get` came back incomplete 3 times; 64-word chunks, each retried
        import putfile as P
        n, words = HDR + N * RW, []
        for o in range(0, n, 64):
            part = P.mem_get(addr + 4 * o, min(64, n - o), tries=6)
            if None in part:
                raise SystemExit(f'mem get 0x{addr + 4 * o:08X}: incomplete')
            words += part
    h, recs = decode(words)
    line = dict(tag=a.tag, t=time.strftime('%H:%M:%S'), header=h, summary=verdict(h, recs),
                records=[{k: (hex(v) if k in ('ras', 'r2280_dest', 'frame', 'r21E8', 'r2048_irq') else v)
                          for k, v in r.items() if k not in ('head0', 'tail0', 'head1', 'tailn')} for r in recs],
                digests=[{k: [hex(x) for x in r[k]] for k in ('head0', 'tail0', 'head1', 'tailn')} for r in recs],
                words=list(words))
    print(json.dumps(line['summary'], indent=1))
    if a.out:
        with open(a.out, 'a') as f:
            f.write(json.dumps(line) + '\n')


if __name__ == '__main__':
    main()
