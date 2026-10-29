#!/usr/bin/env python3
"""The ISPL push engine's state on the camera, read only: armed flag, counters, the TRB chain, ctx 3's tables.

    pxdump.py [OUT.json]

Offsets come from a layout probe of the current build (sup/build.py tree); reads go through the uncached alias
after a cache flush, so they show what the USB controller sees.
"""
import json, pathlib, struct, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'sup'))
import ispl                                                    # noqa: E402

FIELDS = {'px': 'offsetof(wr_t, px)', 'trb': 'offsetof(wr_t, px.trb)', 'armed': 'offsetof(wr_t, px.armed)',
          'owns': 'offsetof(wr_t, px.owns)', 'n_sent': 'offsetof(wr_t, px.n_sent)'}


def offsets():
    import build as IB
    with tempfile.TemporaryDirectory() as tmp:
        tree = pathlib.Path(tmp)
        IB.unity(tree)
        probe = tree / 'p2.c'
        probe.write_text('#include <stddef.h>\n#include "ix_wr.h"\n' +
                         ''.join(f'char p_{k}[{v}+1];\n' for k, v in FIELDS.items()))
        d = IB.compile_c(tree, probe).read_bytes()
    shoff, = struct.unpack_from('<I', d, 0x20)
    _, shnum, _ = struct.unpack_from('<HHH', d, 0x2E)
    secs = [struct.unpack_from('<10I', d, shoff + 40 * i) for i in range(shnum)]
    sym = next(s for s in secs if s[1] == 2)
    strs = secs[sym[6]]
    got = {}
    for i in range(sym[5] // 16):
        n, _v, size, *_ = struct.unpack_from('<IIIBBH', d, sym[4] + 16 * i)
        got[d[strs[4] + n:d.index(b'\0', strs[4] + n)].decode()] = size - 1
    return {k: got['p_' + k] for k in FIELDS}


def dump():
    off = offsets()
    p = ispl.P()
    info, blk = ispl.build(), ispl.block_addr()
    unc = (blk - 0x80000000 if blk >= 0xC0000000 else blk) + info['state_at']
    ispl.flush()
    base, n = unc + off['px'], 2048
    p.mem_window(7, base, n, 1)
    try:
        b = p.mem_read(base, n, sync=False, label='px    ')
    finally:
        p.mem_window(7, base, n, 0)
    o = lambda k: off[k] - off['px']
    armed, last = struct.unpack_from('<II', b, o('armed'))
    rep = {'armed': armed, 'last_trb': last, 'owns': struct.unpack_from('<I', b, o('owns'))[0],
           'n_sent_bad_timeout_starterr_deaf_lastrc_lost': list(struct.unpack_from('<7I', b, o('n_sent'))),
           'trb': [[hex(x) for x in struct.unpack_from('<4I', b, o('trb') + 16 * i)] for i in range(min(last + 2, 8))],
           'hdr_dma_expected': hex(unc + off['px'] - 0x40000000),
           'ctx3_tables': [hex(p.mem_get(0xC31E3244)[0]), hex(p.mem_get(0xC31E3270)[0])],
           'deaf': p.mem_get(0xC31E38FC)[0]}
    return rep


if __name__ == '__main__':
    r = dump()
    print(json.dumps(r, indent=1))
    if len(sys.argv) > 1:
        pathlib.Path(sys.argv[1]).write_text(json.dumps(r, indent=1))
