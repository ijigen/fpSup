#!/usr/bin/env python3
"""唯讀診斷:相機上 COL-Share + LUT 的狀態(只用 mem get,不寫任何東西)。

    cd fpSup/fp_usb_shell && python3 -B ../colshare/diag_camera.py 0xC504F7C0 0xC5102680
    (兩個位址 = LOAD.LOG 的 LOADED 行第二欄:COL-Share、LUT.BIN)
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'fp_usb_shell'))
from putfile import mem_get   # noqa: E402


def words(addr, n):
    out = []
    while len(out) < n:
        k = min(64, n - len(out))
        got = mem_get(addr + 4 * len(out), k)
        out += [0xDEADDEAD if w is None else w for w in got]
    return out


def s32(w): return w - (1 << 32) if w >> 31 else w


def find(ws, magic):
    return next((i for i, w in enumerate(ws) if w == magic), None)


def main():
    cs, lut = (int(a, 16) for a in sys.argv[1:3])
    # ---------------- COL-Share
    cfg = words(cs + 48, 3)
    print(f'COL-Share cfg {[hex(x) for x in cfg]} (magic CFG1=0x31474643)')
    L = cs + cfg[1]
    w = words(L, 224)                                      # 896 bytes of struct cols
    print(f'  magic {w[0]:#x} (LRUN 0x4e55524c=installed)  n(rows) {w[1]}  active {w[2]}  menu {w[5]}')
    print(f'  eff {[s32(x) for x in w[7:12]]}  rec[0..4] {[hex(x) for x in w[54:59]]}  shown {w[59]}  shown_rec {w[60]:#x}  down {w[61]}')
    print(f'  api magic {w[108]:#x} (CLA1 0x31414c43)  ncl {w[192]}')
    for k in range(min(w[192], 4)):
        base = 120 + 18 * k
        c, nrec = w[base], w[base + 1]
        recs = [(w[base + 2 + 2 * i], hex(w[base + 3 + 2 * i])) for i in range(min(nrec, 8))]
        print(f'  client {k}: ptr {c:#x} nrec {nrec} (key, rec) {recs}')
    print(f'  row_sup {[hex(x) for x in w[193:198]]}  row_key {[s32(x) for x in w[198:203]]}')
    print(f'  page {w[203]:#x} table {w[204]:#x} installed {w[205]} result {w[207]} pend_pick {w[208]} pend_eff {w[209]}'
          f' sync_pending {w[210]} told {w[211]:#x}/{s32(w[212])} poffs {w[217]} syncs {w[218]} deferred {w[219]} rejected {w[220]}')
    # ---------------- LUT
    cfg = words(lut + 48, 14)
    print(f'LUT cfg magic {cfg[0]:#x} state {cfg[1]:#x} library {cfg[7]:#x} lvb {cfg[11]:#x} conv {cfg[12]:#x}')
    S = lut + cfg[1]
    st = words(S, 1024)
    api_clist = st[9]
    print(f'  api.version {st[1]}  api.clist {api_clist} (0 attached, 8 no COL-Share, 0x1x add refused)')
    lc = find(st, 0x3143434C)                               # LCC1
    if lc is None:
        print('  lut_cols magic NOT FOUND')
    else:
        c = st[lc:lc + 15]
        print(f'  lut_cols attached {c[1]} n {c[2]} map {c[3:7]} recd {c[7:11]} nrecd {c[11]} api {c[12]:#x}')
        after = lc + 57                                     # sizeof(struct lut_cols) = 228 B
        print(f'  clist_result {st[after]}  dng_result {st[after + 13]}  dng_calls {st[after + 14]}')
    lv = find(st, 0x3142564C)                               # LVB1
    if lv is not None:
        v = st[lv:lv + 64]
        print(f'  lvb ready {v[1]} installed {v[2]} keyed {v[3]} result {v[4]:#x} fits {v[5]} jfts {v[45]}'
              f' ygam_posts {v[46]} jft_why {[hex(x) for x in v[47:51]]}  lvb_result {st[lv + 51]}')
    cv = find(st, 0x31564E43)                               # CNV1
    if cv is not None:
        v = st[cv:cv + 12]
        print(f'  conv state {v[1]} index {v[2]} err {v[5]} runs {v[8]} done {v[9]} last {v[10]}')
    lib = words(lut + cfg[7], 16)
    count, active = lib[4], lib[5]
    print(f'  library count {count} active {s32(active)}  (header words {[hex(x) for x in lib[:8]]})')
    for i in range(min(count, 8)):
        e = words(lut + cfg[7] + 64 + 256 * i, 36)
        sha = struct.pack('<2I', e[0], e[1]).hex()
        print(f'   [{i}] sha8 {sha} flags {e[24]:#x} color {e[25]} gamma {e[26]} amount {e[27]} matrix {e[32]}')
    if cfg[12]:
        k = words(lut + cfg[12], 160)
        ck, csha, score = k[48:80], k[80:112], k[112:144]
        print(f'  conv cache ck {[hex(x) for x in ck[:8]]}')
        print(f'             csha {[hex(x) for x in csha[:8]]}')
        print(f'             score {score[:8]}  (match%+1; 0 = no valid .JFT for this key)')


if __name__ == '__main__':
    main()
