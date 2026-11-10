#!/usr/bin/env python3
"""Jose Hurtado's Desqueeze and Tap to Zoom, moved to loader v4 by us (the user
2026-10-22: 「我們幫他調整吧」; his source is not here).

    python3 -B ports_jose.py --out DIR      -> DIR/fpSup/{Desqueeze,TapToZoom}_v*.BIN + DIR/ports_jose.json

His released v3 files (byte-for-byte, sha checked) get, and get only:
  1. the 48-byte FSB4 header in place of FSB1's 32: the body moves by 16 and
     is position-independent (adr / pc-relative only, his entry checks its
     own 8-alignment, which +16 keeps); SL_F_CACHED_OK; the display name is
     his row title inside his FPUI block;
  2. his claim table without its last three rows -- the uishare string sites
     (C05E5B58 / C05E61C8 / C05E61E0), which the v4 core owns -- by lowering
     the count (DSQZ: the table's count word, 13 -> 10; TAPZ: `mov r8, #6`
     -> #3);
  3. his one call of the embedded uishare uia_apply (a Thumb BL from his menu
     glue) now calling fpsup-ui's fpui_stock_apply, appended after his BSS:
     the same FPUI block and the same composition rules, his private strings
     handed out as address ids and borrowed (svc from SL_SVC_AT: the call is
     made while his entry runs).  Nothing else of his embedded uishare runs
     any more except uis_pool_known (reads the stock pool, unchanged).
Everything else is his bytes.  Tests: test_ports_jose_v4.py.
"""
import argparse, hashlib, json, pathlib, shutil, struct, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
FPSUP = HERE.parent
ROOT = FPSUP.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / 'research' / 'ui' / 'tools' / 'arm_text'))
sys.path.insert(0, str(FPSUP / 'uishare'))
import build_v4 as B                                     # noqa: E402
import names_v4 as N                                     # noqa: E402

V3_HDR, V4_HDR = 32, 48
SHIFT = V4_HDR - V3_HDR

# sup_id -> facts about his v3 file (v3 file offsets); the card file name and
# the display name: names_v4 (the user 2026-10-25)
JOSE = {
    'DSQZ': dict(src=FPSUP / 'releases/fpsup-desqueeze-v0.1.4test/fpSup/41DSQZ.BIN',
                     sha='cddf6da4b3da', count_at=0x5A0, count=(13, 10, 'word'),
                     bl_at=0x2700, bl_old=0x360A, bss_end=0x15020,
                     name_at=0x6B7C, name=b'Desqueeze\0', fpui_at=0x6A40),
    'TAPZ': dict(src=FPSUP / 'releases/fpsup-tap-to-zoom-v0.1.0test/fpSup/42TAPZ.BIN',
                     sha='7eb0be22dbc5', count_at=0x38, count=(0xE3A08006, 0xE3A08003, 'insn'),
                     bl_at=0x76C, bl_old=0x15FA, bss_end=0xD020,
                     name_at=0x44B4, name=b'Tap to Zoom\0', fpui_at=0x4410),
}

SHIM = r'''
#include "fpui_stock.c"
/* His menu glue's call, uia_apply(block, bytes, &outcome), made while his
 * entry runs: the core's table is at SL_SVC_AT then. */
uint32_t jose_apply(uintptr_t b, uint32_t bytes, struct uia_outcome *out)
{
    const struct sl_svc *svc = *(const struct sl_svc *const volatile *)SL_SVC_AT;
    if (svc && ((uintptr_t)svc & 3u)) svc = 0;
    return fpui_stock_apply(svc, (const void *)b, bytes, out);
}
'''


class PortError(RuntimeError):
    pass


def shim_code():
    import build_section as US
    import elf_text
    with tempfile.TemporaryDirectory(prefix='jose4-') as t:
        t = pathlib.Path(t)
        (t / 'shim.c').write_text(SHIM)
        clang = shutil.which('clang') or 'clang'
        r = subprocess.run([clang] + US.CFLAGS + ['-c', '-I', str(FPSUP / 'fpsup-ui'), '-I', str(HERE),
                            str(t / 'shim.c'), '-o', str(t / 'shim.o')], capture_output=True, text=True)
        if r.returncode:
            raise PortError('shim: ' + r.stderr)
        text = elf_text.load_text(t / 'shim.o')
    fn = text.functions.get('jose_apply', 0)
    if not fn & 1:
        raise PortError('jose_apply missing or not Thumb')
    return text.code, fn


def thumb_bl(at, target):
    """Thumb-2 BL at file offset `at` to Thumb `target` (both in the block)."""
    off = target - (at + 4)
    if off & 1 or not -(1 << 24) <= off < (1 << 24):
        raise PortError('BL out of reach')
    s = (off >> 24) & 1
    i1, i2 = (off >> 23) & 1, (off >> 22) & 1
    j1, j2 = (1 - i1) ^ s, (1 - i2) ^ s
    hw1 = 0xF000 | s << 10 | ((off >> 12) & 0x3FF)
    hw2 = 0xD000 | j1 << 13 | j2 << 11 | ((off >> 1) & 0x7FF)
    return struct.pack('<HH', hw1, hw2)


def bl_target(word, at):
    hw1, hw2 = struct.unpack('<HH', word)
    if (hw1 & 0xF800) != 0xF000 or (hw2 & 0xD000) != 0xD000:
        raise PortError('not a Thumb BL')
    s = (hw1 >> 10) & 1
    j1, j2 = (hw2 >> 13) & 1, (hw2 >> 11) & 1
    i1, i2 = 1 - (j1 ^ s), 1 - (j2 ^ s)
    off = s << 24 | i1 << 23 | i2 << 22 | (hw1 & 0x3FF) << 12 | (hw2 & 0x7FF) << 1
    if s:
        off -= 1 << 25
    return at + 4 + off


def port(name, code=None, fn=None):
    j = JOSE[name]
    v3 = j['src'].read_bytes()
    if hashlib.sha256(v3).hexdigest()[:12] != j['sha']:
        raise PortError(f'{name}: not his released file')
    h = struct.unpack_from('<8I', v3)
    if h[0] != 0x31425346 or h[1] != V3_HDR or h[2] != len(v3) or h[4] != V3_HDR or h[3] != j['bss_end']:
        raise PortError(f'{name}: header not as reviewed')
    body = bytearray(v3[V3_HDR:])
    o = j['count_at'] - V3_HDR                           # 2. the claims without the string sites
    old, new, kind = j['count']
    if struct.unpack_from('<I', body, o)[0] != old:
        raise PortError(f'{name}: claim count not as reviewed')
    struct.pack_into('<I', body, o, new)
    if code is None:
        code, fn = shim_code()
    o = j['bl_at'] - V3_HDR                              # 3. his uia_apply call
    if bl_target(bytes(body[o:o + 4]), j['bl_at']) != j['bl_old']:
        raise PortError(f'{name}: the call is not to his uia_apply')
    shim_at = (j['bss_end'] + SHIFT + 63) & ~63          # v4 file offset, past his BSS
    body = body.ljust(shim_at - V4_HDR, b'\0') + code
    body[o:o + 4] = thumb_bl(j['bl_at'] + SHIFT, shim_at + (fn & ~1))
    name_at = j['name_at']                               # the row title in his FPUI block
    if v3[name_at:name_at + len(j['name'])] != j['name']:
        raise PortError(f'{name}: display name not where reviewed')
    # the display name (names_v4) over his row title, in its own room only:
    # "Tap to Zoom" -> "Tap To Zoom" (the user 2026-10-25), same length
    display = N.display(name).encode() + b'\0'
    if len(display) != len(j['name']):
        raise PortError(f'{name}: display name must keep his title\'s length ({len(j["name"]) - 1})')
    if display != j['name']:
        o = name_at - V3_HDR
        body[o:o + len(display)] = display
        # his FPUI block's FNV-1a (fpui_stock.c fst_fnv: +12, over +0x20 .. total)
        f = j['fpui_at'] - V3_HDR
        magic, _ver, total = struct.unpack_from('<3I', body, f)
        if magic != 0x49555046 or not f < o < f + total:
            raise PortError(f'{name}: the title is not in his FPUI block')
        fnv = 2166136261
        for c in body[f + 0x20:f + total]:
            fnv = ((fnv ^ c) * 16777619) & 0xFFFFFFFF
        struct.pack_into('<I', body, f + 12, fnv)
    data = bytearray(B.make_sup(bytes(body), h[4] + SHIFT, struct.pack('<I', h[5]).decode(),
                                version=h[6], min_svc=6, flags=B.SL_F_CACHED_OK))
    struct.pack_into('<I', data, 44, name_at + SHIFT)  # his row title as the display name
    return bytes(data), {'v3_sha256': hashlib.sha256(v3).hexdigest(), 'shim_at': shim_at,
                         'shim_bytes': len(code), 'jose_apply': shim_at + fn,
                         'display': N.display(name), 'file': N.file_name(name)}


def build():
    code, fn = shim_code()
    return {N.file_name(n): port(n, code, fn) for n in JOSE}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=pathlib.Path, required=True)
    a = ap.parse_args()
    d = a.out / 'fpSup'
    d.mkdir(parents=True, exist_ok=True)
    info = {}
    for n, (data, facts) in build().items():
        (d / n).write_bytes(data)
        info[n] = dict(facts, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        print(f'{n}: {len(data)} B  {info[n]["sha256"][:16]}  (shim {facts["shim_bytes"]} B @ {facts["shim_at"]:#x})')
    (a.out / 'ports_jose.json').write_text(json.dumps(info, indent=1) + '\n')


if __name__ == '__main__':
    main()
