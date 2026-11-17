#!/usr/bin/env python3
"""One BLK-SNAP take: set the recipe from its QR code (sq_test 41 force -> 43 -> 41 check -> 19 push, the way
validation/20261110-vertical-margin/live2/setrecipe.py did it live for 30 clips), set the ISO, record 2 s
(rec_take.sh: nothing on USB while recording, 12 s after the stop), read the snapshot ring (sq_test 50) and one DNG.

    python3 -B take.py TAG CODE ISO          # -> takes/TAG/{ring.bin, ring.txt, f3.DNG, take.json}
"""
import json, pathlib, re, subprocess, sys, time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SHELL = ROOT / 'fpSup/fp_usb_shell'
LIVE = ROOT / 'projects/sensorlab-imx410/tools/live'
sys.path[:0] = [str(SHELL), str(LIVE)]
from callfn import call                                   # noqa: E402
import putfile as pf                                      # noqa: E402
import blk_plan as P                                      # noqa: E402
import blk_snap as D                                      # noqa: E402
import test_blk_plan as TP                                # noqa: E402

BUILD = pathlib.Path(__import__('os').environ.get('BLK_BUILD', HERE / 'out-blk-snap-test/build-0.0.7test.json'))
INFO = json.loads(BUILD.read_text())
BLOCK = 0xC52D4480                                        # LOAD-after.LOG: SensorLab-IMX410_v0.0.7test.BIN
SQ = BLOCK + INFO['sq_test_off']
CONSTS = P.page_consts()
NAMES = [n for n, _w in CONSTS['qr_fields']]


def op(n, a=0, b=0):
    r = call(SQ, r0=n, r1=a, r2=b, verbose=False)
    return r[1] if isinstance(r, tuple) else r


def fsh(line):
    return subprocess.run([str(SHELL / 'host/fpsh'), *line.split()], capture_output=True, text=True,
                          cwd=SHELL).stdout


def put(buf, vals):
    for i, v in enumerate(vals):
        pf.mem_set(buf + 4 * i, v)
    got = pf.mem_get(buf, len(vals))
    assert got == list(vals), ('readback', got)


def live_code():
    a = op(13)
    b = b''.join(w.to_bytes(4, 'little') for w in pf.mem_get(a, 10))
    return b.split(b'\0')[0].decode()


def set_recipe(code):
    f = TP.decode(code, CONSTS['qr_fields'])
    buf = pf.mem_caps()['pool'] + 0x80000                 # the worker's own pool, past anything resident
    put(buf, [f[n] for n in NAMES])
    op(41, buf, 2)                                         # force the inputs
    op(43, buf)                                            # the fields the selection now gives
    got = dict(zip(NAMES, pf.mem_get(buf, len(NAMES))))
    put(buf, [got[n] for n in NAMES])
    chk = op(41, buf, 0)                                   # exact check
    keyf = ('dcw', 'dch', 'rw', 'rh', 'ad', 'mh', 'mv', 'hbin', 'vbin', 'key', 'scw', 'sch', 'ww', 'wh')
    if chk != 1 or any(got[k] != f[k] for k in keyf):
        raise SystemExit(f'not the recipe: check {chk}, {[(k, f[k], got[k]) for k in keyf if got[k] != f[k]]}')
    rc = op(19)
    return got, rc


LAST_CLIP = HERE / 'last_clip.json'


def clip_exists(name, date):
    r = subprocess.run([sys.executable, '-B', 'getfile.py', f'\\CINEMA\\{name}\\{name}_{date}_000001.DNG', '/dev/null',
                        '--size', '4096', '--partial'], cwd=SHELL, capture_output=True, text=True)
    return bool(re.search(r'actual [1-9]', r.stdout + r.stderr))


def newest_clip():
    """`dir \\CINEMA` is cut at its 16 KB reply (11-16: past ~300 folders the list ended at A001_320 while A001_321
    existed), so: the listing while it is whole, then the last known clip + probing the next numbers"""
    out = fsh('dir \\CINEMA')
    rows = re.findall(r'(\d{4})/(\d\d)/(\d\d)\s+\S+\s+<DIR>\s+(A\d{3}_\d{3})', out)
    y, m, d, name = max(rows, key=lambda r: r[3])
    best = (name, f'{y}{m}{d}')
    if LAST_CLIP.exists():
        k = json.loads(LAST_CLIP.read_text())
        if k['name'] > best[0]:
            best = (k['name'], k['date'])
    reel, n = best[0].split('_')
    n = int(n)
    k = n                                                  # a failed REC can use a number and leave no clip (11-16:
    while k < 999 and k - n < 4:                           # A001_520 missing, A001_521 there): look past 3 gaps
        k += 1
        if clip_exists(f'{reel}_{k:03d}', best[1]):
            n = k
    best = (f'{reel}_{n:03d}', best[1])
    LAST_CLIP.write_text(json.dumps(dict(name=best[0], date=best[1])))
    return best


def fetch(remote, local):
    """getfile's length probe only works below its buffer: ask for more than any DNG and keep what is read.
    Right after a stock take the card can still be busy (11-16 stock-iso100: refused, then fine by hand): one retry."""
    for attempt in (0, 1):
        r = subprocess.run([sys.executable, '-B', 'getfile.py', remote, str(local), '--size', str(64 << 20),
                            '--partial'], cwd=SHELL, capture_output=True, text=True)
        if not r.returncode or 'open returned 0' in r.stdout + r.stderr:
            break
        time.sleep(5)
    m = re.search(r'actual (\d+) of', r.stdout + r.stderr)
    if r.returncode or not m or not local.exists() or local.stat().st_size != int(m.group(1)):
        raise SystemExit(f'{remote}: fetch failed ({(r.stdout + r.stderr)[-300:]})')
    return int(m.group(1))


def main(tag, code, iso):
    out = HERE / __import__('os').environ.get('BLK_TAKES', 'takes') / tag
    out.mkdir(parents=True, exist_ok=True)
    log = dict(tag=tag, code=code, iso=iso, t=time.strftime('%Y-%m-%d %H:%M:%S'))
    if 'is_recording -> 0' not in fsh('status get is_recording'):
        raise SystemExit('recording or no answer: nothing sent')
    fsh(f'menu SetIso {iso}')
    log['iso_read'] = fsh('menu SetIso').strip()
    got, rc = set_recipe(code)
    log['push_rc'] = rc
    time.sleep(4)                                          # the commit's LV stop / start
    log['live_code'] = live_code()
    if log['live_code'] != code:
        print(f'note: live code {log["live_code"]} (fps / vmax may map)', file=sys.stderr)
    n0 = op(50, 1)
    clip0 = newest_clip()[0]
    subprocess.run(['zsh', str(SHELL / 'rec_take.sh'), '2'], capture_output=True, timeout=90)
    if 'is_recording -> 0' not in fsh('status get is_recording'):
        raise SystemExit('still recording after rec_take: stop here')
    log['ring_n_before'], log['ring_n_after'] = n0, op(50, 1)
    log['cur_mode'] = pf.mem_get(0xC343B590)[0]
    ring = D.read_camera(BUILD, BLOCK)
    (out / 'ring.bin').write_bytes(ring)
    clip, date = newest_clip()
    log['clip'] = clip
    if clip == clip0:
        raise SystemExit(f'no new clip (newest {clip})')
    for frame in (3, 2):                                   # a full-frame take may stop after 2 frames (the card)
        remote = f'\\CINEMA\\{clip}\\{clip}_{date}_{frame:06d}.DNG'
        try:
            log['dng'], log['dng_bytes'] = remote, fetch(remote, out / 'f3.DNG')
            break
        except SystemExit as e:
            log['fetch_' + str(frame)] = str(e)[:120]
    else:
        raise SystemExit('no frame 3 or 2')
    # frame 1 is always uncompressed: 11-16 the Lossless-compressed frames of SQ 1024x1024 RWZM decoded with 258
    # all-zero rows while frame 1 was a clean dark frame -- keep it as the fallback
    try:
        log['dng1'], log['dng1_bytes'] = f'{clip}_{date}_000001', fetch(
            f'\\CINEMA\\{clip}\\{clip}_{date}_000001.DNG', out / 'f1.DNG')
    except SystemExit as e:
        log['fetch_1'] = str(e)[:120]
    hdr, recs = D.parse(ring)
    rows, text = D.table(recs)
    (out / 'ring.txt').write_text(text + '\n')
    (out / 'take.json').write_text(json.dumps(log, indent=1) + '\n')
    print(json.dumps(log))
    print(text.splitlines()[0]); print('\n'.join(text.splitlines()[-4:]))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]))
