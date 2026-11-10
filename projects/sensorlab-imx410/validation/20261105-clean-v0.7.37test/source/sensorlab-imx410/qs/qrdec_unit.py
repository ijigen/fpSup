"""Build the QR scan decoder (qrdec.c) with the REAL slqs.c encoder pieces, for the host (ctypes) and for the camera's
Thumb target (link_flat, the same as build_slqs.py) -- notes/QR_SCAN_DESIGN.md, phase 1.

The unit = typedefs + core.c's udiv64 + slqs.c's helpers, QR defines, payload tables, qr_pack and the whole encoder
section ("---- the encoder" .. "---- the scan decoder"), copied out of the files at build time (never retyped), then
#include "qrdec.c", then thin exports taking caller memory (the camera image allows no writable section)."""
import ctypes
import hashlib
import pathlib
import re
import shutil
import subprocess
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SLQS = HERE / 'slqs.c'
CORE_C = HERE.parent / 'core' / 'core.c'
QRDEC = HERE / 'qrdec.c'


def _cut(text, start, end, what):
    a = text.index(start)
    b = text.index(end, a)
    if b <= a:
        raise ValueError(what)
    return text[a:b]


def _func(text, head):
    """a top-level function from its head line to the first column-0 '}'"""
    a = text.index(head)
    b = text.index('\n}\n', a) + 3
    return text[a:b]


def unit_source(qrdec_text=None):
    s = SLQS.read_text()
    core = CORE_C.read_text()
    parts = ['#include <stdint.h>',
             'typedef uint32_t u32; typedef uint16_t u16; typedef uint8_t u8; typedef int32_t s32;',
             'typedef uint64_t u64; typedef int64_t i64;',
             _func(core, '__attribute__((noinline)) static u64 udiv64')]
    for name in ('static u32 udiv(', 'static int sq_max(', 'static int sq_abs(', 'static u32 sq_len('):
        line = next(l for l in s.splitlines() if l.startswith(name))
        parts.append(line)
    for d in ('QR_URL', 'QR_CHARS', 'QR_VER', 'QR_N', 'QR_DATA_CW', 'QR_EC_CW'):
        parts.append(next(l for l in s.splitlines() if re.match(r'#define %s\s' % d, l)))
    parts.append('struct qr { u32 n, mask; char url[96]; u8 cw[QR_DATA_CW + QR_EC_CW], gen[QR_EC_CW];\n'
                 '            u8 mat[QR_N * QR_N + 3u], fn[QR_N * QR_N + 3u], best[QR_N * QR_N + 3u]; };')
    for d in ('#define N_QF ', '#define QF_BITS ', 'static const u8 QF_W[', 'static const char B64U['):
        parts.append(next(l for l in s.splitlines() if l.startswith(d)))
    parts.append(_func(s, 'static void qr_pack('))
    enc = _cut(s, '/* ---- the encoder', '/* ---- the scan decoder', 'encoder section')   # v0.7.32test: slqs.c includes qrdec.c there
    parts.append(enc)
    parts.append(qrdec_text if qrdec_text is not None else '#include "qrdec.c"')
    parts.append(EXPORTS)
    return '\n'.join(parts) + '\n'


EXPORTS = r'''
#define QH __attribute__((used))
QH u32 qh_sizes(u32 k) { return k == 0u ? (u32)sizeof(struct qrd) : (u32)sizeof(struct qr); }
QH int qh_encode(struct qr *q, const char *url, u8 *mat, u8 *fn, u32 *mask)   /* mat: 1 = dark */
{
    u32 i = 0;
    for (; url[i] && i < 95u; i++) q->url[i] = url[i];
    q->url[i] = 0;
    int r = qr_encode(q);
    for (u32 k = 0; k < QR_N * QR_N; k++) { mat[k] = q->mat[k] == 0u; fn[k] = q->fn[k]; }
    *mask = q->mask;
    return r;
}
QH int qh_decode(struct qrd *d, const u8 *img, u32 w, u32 h, u32 stride, const u8 *fn, u8 *out, u32 *len, u32 *diag)
{
    int r = qrd_decode(d, img, w, h, stride, fn, out, len);
    diag[0] = d->why; diag[1] = d->tries; diag[2] = d->fmt_d; diag[3] = d->mask; diag[4] = d->rs_n;
    diag[5] = d->align; diag[6] = d->mirror; diag[7] = d->pat_bad; diag[8] = d->nc;
    return r;
}
QH int qh_rs(struct qrd *d, u8 *cw)                   /* RS alone on 134 codewords (corrected in place) */
{
    qd_gf(d);
    for (u32 i = 0; i < QD_NCW; i++) d->cw[i] = cw[i];
    int r = qd_rs(d);
    for (u32 i = 0; i < QD_NCW; i++) cw[i] = d->cw[i];
    return r;
}
QH int qh_sensorlab(const u8 *b, u32 len, u32 stock, char *code) { return qrd_sensorlab(b, len, stock, code); }
QH void qh_to_stock(u8 *b, u32 len) { qrd_to_stock(b, len); }
QH int qh_unpack(const char *code, u32 *f) { return qr_unpack(code, f); }
QH void qh_pack(const u32 *f, char *out) { qr_pack(f, out); }
QH u32 qh_dbg_scan(struct qrd *d, const u8 *img, u32 w, u32 h, u8 *bin)   /* binarise + scan only -> row hits */
{
    d->img = img; d->w = (s32)w; d->h = (s32)h; d->stride = w;
    qd_blocks(d); qd_scan(d);
    for (u32 y = 0; y < h; y++) for (u32 x = 0; x < w; x++) bin[y * w + x] = (u8)qd_px(d, (s32)x, (s32)y);
    return d->hits;
}
QH u32 qh_dbg_ratio(const u32 *r) { return qd_ratio(r); }
QH int qh_dbg_map(struct qrd *d, s32 u, s32 v, s32 *xy) { return qd_map(d, u, v, &xy[0], &xy[1]); }
QH u32 qh_dbg_cand(struct qrd *d, u32 i, s32 *c) { if (i >= d->nc) return 0; c[0] = d->c[i].x; c[1] = d->c[i].y; c[2] = d->c[i].m; c[3] = (s32)d->c[i].n; return 1; }
'''


class Lib:
    """the host build (ctypes) of one unit text"""

    def __init__(self, qrdec_text=None, outdir=None):
        src = unit_source(qrdec_text)
        body = qrdec_text if qrdec_text is not None else QRDEC.read_text()
        tag = hashlib.sha256((src + body).encode()).hexdigest()[:16]   # the included file too (a stale .so lied once)
        base = pathlib.Path(outdir or tempfile.gettempdir()) / f'qrdec-{tag}'
        base.mkdir(parents=True, exist_ok=True)
        so = base / 'qrdec.so'
        if not so.exists():
            (base / 'unit.c').write_text(src)
            if qrdec_text is not None:
                (base / 'qrdec.c').write_text(qrdec_text)
            else:
                shutil.copy(QRDEC, base / 'qrdec.c')
            cc = shutil.which('clang') or 'cc'
            flags = ['-O2', '-shared', '-fPIC', '-std=c11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                     '-ffreestanding', '-fno-builtin', '-I', str(base)]
            r = subprocess.run([cc, *flags, str(base / 'unit.c'), '-o', str(so)], capture_output=True, text=True)
            if r.returncode:
                raise RuntimeError('host build failed:\n' + r.stderr)
        self.so = so
        L = self.L = ctypes.CDLL(str(so))
        L.qh_sizes.restype = ctypes.c_uint32
        self.dbuf = ctypes.create_string_buffer(L.qh_sizes(0))
        self.qbuf = ctypes.create_string_buffer(L.qh_sizes(1))

    def encode(self, url):
        import numpy as np
        mat = (ctypes.c_uint8 * 1369)(); fn = (ctypes.c_uint8 * 1369)(); mask = ctypes.c_uint32()
        r = self.L.qh_encode(self.qbuf, url.encode(), mat, fn, ctypes.byref(mask))
        if r:
            raise ValueError('encode failed')
        return np.frombuffer(bytes(mat), np.uint8).reshape(37, 37).copy(), bytes(fn), mask.value

    def decode(self, img, fn):
        import numpy as np
        img = np.ascontiguousarray(img, dtype=np.uint8)
        h, w = img.shape
        out = (ctypes.c_uint8 * 128)(); n = ctypes.c_uint32(); diag = (ctypes.c_uint32 * 9)()
        r = self.L.qh_decode(self.dbuf, img.ctypes.data_as(ctypes.c_void_p), w, h, w, fn, out, ctypes.byref(n), diag)
        return r, bytes(out[:n.value]), list(diag)

    def rs(self, cw):
        b = (ctypes.c_uint8 * 134)(*cw)
        r = self.L.qh_rs(self.dbuf, b)
        return r, bytes(b)

    def sensorlab(self, data, stock):
        code = ctypes.create_string_buffer(40)
        ok = self.L.qh_sensorlab(data, len(data), stock, code)
        return code.value.decode() if ok else None

    def to_stock(self, data):
        b = ctypes.create_string_buffer(bytes(data), len(data))
        self.L.qh_to_stock(b, len(data))
        return b.raw

    def unpack(self, code):
        f = (ctypes.c_uint32 * 27)()
        r = self.L.qh_unpack(code.encode() + b'\0', f)
        return r, list(f)

    def pack(self, fields):
        out = ctypes.create_string_buffer(40)
        self.L.qh_pack((ctypes.c_uint32 * 27)(*fields), out)
        return out.value.decode()


def thumb_image(qrdec_text=None):
    """the same unit for the camera target: build_v4 CFLAGS, then build_slqs.link_flat (no load-time relocation)"""
    import sys
    sys.path.insert(0, str(HERE))
    import build_slqs as BS
    src = unit_source(qrdec_text)
    with tempfile.TemporaryDirectory(prefix='qrdec-arm-') as t:
        t = pathlib.Path(t)
        (t / 'unit.c').write_text(src)
        (t / 'qrdec.c').write_text(qrdec_text if qrdec_text is not None else QRDEC.read_text())
        flags = [*BS.B.CFLAGS, '-fno-unwind-tables', '-fno-asynchronous-unwind-tables', '-I', str(t)]
        r = subprocess.run([shutil.which('clang') or 'clang', *flags, '-c', str(t / 'unit.c'), '-o', str(t / 'u.o')],
                           capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError('thumb build failed:\n' + r.stderr)
        return BS.link_flat((t / 'u.o').read_bytes())
