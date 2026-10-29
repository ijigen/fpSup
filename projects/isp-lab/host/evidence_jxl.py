#!/usr/bin/env python3
"""Repack a run's evidence.tar.zst with cdng-image (JPEG XL, lossless) and restore it bit for bit.

    evidence_jxl.py pack validation/RUN [RUN ...]    replaces evidence.tar.zst only after a full restore matches
    evidence_jxl.py unpack validation/RUN DEST [MEMBER ...]

evidence.cdngt   every uncompressed DNG member (cdng-image temporal; restores as 16-bit DNG)
evidence.side.tar.zst   the other members, each DNG's bytes outside its strip, the stream.raw headers
EVIDENCE.json    member order, tar metadata, sha256 and how each member is stored

The DNG strip is re-packed from the 16-bit restore to its own bit depth (MSB first) and spliced into the original
header, so the restored member equals the original byte for byte. stream.raw is the push stream: 256-byte
headers each followed by a payload that is also stored as its own member (10-28: 202 MB of 267 MB was this copy).
"""
import hashlib, io, json, os, pathlib, shutil, struct, subprocess, sys, tarfile, tempfile
import numpy as np

CDNG = pathlib.Path(__file__).resolve().parents[2] / 'cdng-image' / 'rust' / 'target' / 'release' / 'cdng-image'
OLD, FRAMES, SIDE, MANIFEST = 'evidence.tar.zst', 'evidence.cdngt', 'evidence.side.tar.zst', 'EVIDENCE.json'
META = ('mode', 'mtime', 'uid', 'gid', 'uname', 'gname')


def sha(b):
    return hashlib.sha256(b).hexdigest()


def strip(b):
    """(offset, length, width, height, bits) of an uncompressed single-strip little-endian DNG, else None."""
    if b[:4] != b'II*\x00' or len(b) < 16:
        return None
    o = struct.unpack_from('<I', b, 4)[0]
    if o + 2 > len(b):
        return None
    n, t = struct.unpack_from('<H', b, o)[0], {}
    if o + 2 + 12 * n > len(b):
        return None
    for i in range(n):
        tag, typ, cnt, val = struct.unpack_from('<HHII', b, o + 2 + 12 * i)
        t[tag] = (typ, cnt, val & 0xFFFF if typ == 3 else val)
    need = (256, 257, 258, 259, 273, 279)
    if any(k not in t or t[k][1] != 1 for k in need) or t[259][2] != 1 or t.get(277, (3, 1, 1))[2] != 1:
        return None
    off, ln, w, h, bits = t[273][2], t[279][2], t[256][2], t[257][2], t[258][2]
    if not 8 < bits <= 16 or off + ln > len(b) or h == 0 or ln % h or ln // h < -(-w * bits // 8):
        return None
    return off, ln, w, h, bits


def pack_bits(px, w, h, bits, row_bytes):
    """16-bit samples (h, w) -> MSB-first `bits`-bit rows padded to row_bytes."""
    v = px.reshape(h, w).astype('>u2')
    b = np.unpackbits(v.view(np.uint8).reshape(h, w, 2), axis=2)[:, :, 16 - bits:].reshape(h, w * bits)
    out = np.packbits(b, axis=1)
    if out.shape[1] < row_bytes:
        out = np.pad(out, ((0, 0), (0, row_bytes - out.shape[1])))
    return out.tobytes()


def stream_map(raw, by_sha):
    """stream.raw as [(header hex, member name)], or None if any payload is not a stored member."""
    out, p = [], 0
    while p < len(raw):
        if p + 32 > len(raw):
            return None
        hl, total = struct.unpack_from('<I', raw, p + 4)[0], struct.unpack_from('<I', raw, p + 28)[0]
        name = by_sha.get(sha(raw[p + hl:p + hl + total]))
        if hl < 32 or name is None or p + hl + total > len(raw):
            return None
        out.append((raw[p:p + hl].hex(), name))
        p += hl + total
    return out


def read_tar_zst(path):
    with subprocess.Popen(['zstd', '-q', '-dc', str(path)], stdout=subprocess.PIPE) as z:
        with tarfile.open(fileobj=z.stdout, mode='r|') as t:
            ms = [(m, t.extractfile(m).read() if m.isfile() else None) for m in t]
        if z.wait():
            raise ValueError(f'zstd failed on {path}')
    return ms


def write_tar_zst(path, members):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w', format=tarfile.PAX_FORMAT) as t:
        for m, data in members:
            t.addfile(m, io.BytesIO(data) if data is not None else None)
    subprocess.run(['zstd', '-q', '-12', '-T0', '--long=27', '-f', '-o', str(path)], input=buf.getvalue(), check=True)


def restored_dngs(cdngt, work):
    ex = pathlib.Path(work) / 'ex'
    subprocess.run([str(CDNG), 'extract', str(cdngt), str(ex)], check=True, stdout=subprocess.DEVNULL)
    return {p.name: p for p in ex.rglob('*.DNG')}


def splice(rest_bytes, head, tail, s):
    off, ln, w, h, bits = s
    r = strip(rest_bytes)
    if r is None or r[2:4] != (w, h) or r[4] != 16:
        return None
    px = np.frombuffer(rest_bytes, '<u2', w * h, r[0])
    body = px.astype('<u2').tobytes() if bits == 16 else pack_bits(px, w, h, bits, ln // h)
    return head + body + tail


def pack(run):
    run = pathlib.Path(run)
    old = run / OLD
    ms = read_tar_zst(old)
    if (run / 'ARCHIVE.json').exists():                         # the archive's own manifest, when it has one
        want = json.loads((run / 'ARCHIVE.json').read_text())['files']
        got = {m.name: {'bytes': m.size, 'sha256': sha(d)} for m, d in ms if d is not None}
        if got != want:
            raise ValueError('evidence.tar.zst differs from ARCHIVE.json')
    by_sha = {sha(d): m.name for m, d in ms if d is not None and m.name != 'push/stream.raw'}
    manifest, side, dngs = [], [], {}
    for m, d in ms:
        e = {'name': m.name, 'type': 'file' if m.isfile() else 'dir' if m.isdir() else None,
             **{k: getattr(m, k) for k in META}}
        if e['type'] is None:
            raise ValueError(f'unsupported member {m.name}')
        if d is not None:
            e.update(bytes=len(d), sha256=sha(d), how='side')
            s = strip(d)
            if s:
                e.update(how='dng', dng=f'f{len(dngs):05d}.DNG', strip=list(s))
                dngs[e['dng']] = (d, s)
            elif m.name == 'push/stream.raw' and (sm := stream_map(d, by_sha)):
                e.update(how='stream')
                side.append(('_evidence/stream.json', json.dumps(sm).encode()))
            else:
                side.append((m.name, d))
        else:
            e['how'] = 'dir'
        manifest.append(e)
    with tempfile.TemporaryDirectory(prefix='evjxl-', dir=run) as work:
        work = pathlib.Path(work)
        if dngs:
            (work / 'src' / 'CLIP').mkdir(parents=True)
            for n, (d, _) in dngs.items():
                (work / 'src' / 'CLIP' / n).write_bytes(d)
            subprocess.run([str(CDNG), 'pack', str(work / 'src'), str(work / FRAMES), '--codec', 'temporal'],
                           check=True, stdout=subprocess.DEVNULL)
            shutil.rmtree(work / 'src')
            rest = restored_dngs(work / FRAMES, work)
            for e in manifest:
                if e['how'] != 'dng':
                    continue
                d, s = dngs[e['dng']]
                head, tail = d[:s[0]], d[s[0] + s[1]:]
                if rest.get(e['dng']) and splice(rest[e['dng']].read_bytes(), head, tail, s) == d:
                    side += [(f"_evidence/dng/{e['dng']}.head", head), (f"_evidence/dng/{e['dng']}.tail", tail)]
                else:                                           # not reproducible: keep it whole
                    e['how'] = 'side'
                    del e['dng'], e['strip']
                    side.append((e['name'], d))
            shutil.rmtree(work / 'ex')
            if not any(e['how'] == 'dng' for e in manifest):
                (work / FRAMES).unlink()
        tis = []
        for n, d in side:
            ti = tarfile.TarInfo(n)
            ti.size = len(d)
            tis.append((ti, d))
        write_tar_zst(work / SIDE, tis)
        (work / MANIFEST).write_text(json.dumps({'version': 1, 'members': manifest}, ensure_ascii=False))
        # the proof: restore everything from the new files and compare with the old archive's members
        check = work / 'check'
        unpack(work, check)
        for m, d in ms:
            p = check / m.name
            if (m.isfile() and p.read_bytes() != d) or (m.isdir() and not p.is_dir()):
                raise ValueError(f'restore differs: {m.name}')
        shutil.rmtree(check)
        for n in (FRAMES, SIDE, MANIFEST):
            if (work / n).exists():
                os.replace(work / n, run / n)
    before = old.stat().st_size
    old.unlink()
    after = sum((run / n).stat().st_size for n in (FRAMES, SIDE) if (run / n).exists())
    return before, after


def unpack(run, dest, only=None):
    """Recreate the original members (all, or those whose name starts with one of `only`) under dest."""
    run, dest = pathlib.Path(run), pathlib.Path(dest)
    if (run / OLD).exists():
        dest.mkdir(parents=True, exist_ok=True)
        subprocess.run(f'zstd -q -dc "{run / OLD}" | tar -xf - -C "{dest}" {" ".join(only or [])}', shell=True,
                       check=True)
        return
    man = json.loads((run / MANIFEST).read_text())['members']
    pick = [e for e in man if not only or any(e['name'] == o or e['name'].startswith(o.rstrip('/') + '/')
                                               for o in only)]
    side = {m.name: d for m, d in read_tar_zst(run / SIDE) if d is not None}
    with tempfile.TemporaryDirectory(prefix='evjxl-x-') as work:
        rest = restored_dngs(run / FRAMES, work) if any(e['how'] == 'dng' for e in pick) else {}
        data = {}
        for e in man:
            if e['how'] == 'side':
                data[e['name']] = side[e['name']]
            elif e['how'] == 'dng' and e in pick or (e['how'] == 'dng' and any(x['how'] == 'stream' for x in pick)):
                n = e['dng']
                d = splice(rest[n].read_bytes(), side[f'_evidence/dng/{n}.head'], side[f'_evidence/dng/{n}.tail'],
                           tuple(e['strip']))
                data[e['name']] = d
        for e in pick:
            p = dest / e['name']
            if e['how'] == 'dir':
                p.mkdir(parents=True, exist_ok=True)
                continue
            if e['how'] == 'stream':
                d = b''.join(bytes.fromhex(h) + data[n] for h, n in json.loads(side['_evidence/stream.json']))
            else:
                d = data[e['name']]
            if sha(d) != e['sha256']:
                raise ValueError(f'restored {e["name"]} does not match its sha256')
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(d)
            os.chmod(p, e['mode'])
            os.utime(p, (e['mtime'], e['mtime']))


if __name__ == '__main__':
    if sys.argv[1] == 'pack':
        tb = ta = 0
        for r in sys.argv[2:]:
            if not (pathlib.Path(r) / OLD).exists():
                continue
            try:
                b, a = pack(r)
            except Exception as ex:
                print(f'FAIL {pathlib.Path(r).name}: {ex}', flush=True)
                continue
            tb, ta = tb + b, ta + a
            print(f'{pathlib.Path(r).name} {b / 1e6:.0f} -> {a / 1e6:.0f} MB  (total {tb / 1e9:.2f} -> {ta / 1e9:.2f} GB)',
                  flush=True)
    elif sys.argv[1] == 'unpack':
        unpack(sys.argv[2], sys.argv[3], sys.argv[4:] or None)
