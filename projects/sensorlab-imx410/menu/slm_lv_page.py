#!/usr/bin/env python3
"""The live view's frame rate, drawn from SensorLab's own rate (0.0.7test, Bei 11-15).

python3 -B slm_lv_page.py       # deterministic slm_lv_page.h, included by slqs.c

Stock draws the frame rate at the foot of the live view as one of ten bitmaps
(object "FrameRate": a drawImage keyed by LV_FrameRate).  Under SensorLab that
variable follows the carrier, the stock rate under the real one, so the number
on screen is the nearest stock rate, not the rate being recorded -- and a rate
like 57.123 has no bitmap at all.

Each CINE live-view page gets, as one FPUI block (a page copy; nothing is
patched in place):

  * the stock FrameRate object moved off the screen (its base rect's y);
  * beside it, under the same parent and at its place, a copy of the page's own
    "RemainingTimeString" object -- a drawText whose text is an app string
    variable, the stock digits as images (<!font_S_5,BOTTOM>...) -- bound to
    SLM_LvFpsS (the MEDIUM page, font_S) / SLM_LvFpsM (LARGE, font_M) instead
    of LV_RemainingRecTimeString*.

The copy is the stock records byte for byte except: the object id, the parent,
the object name, the base rect, the drawText's rect / first text,
and the variable name.  slm_runtime.h registers the two variables and writes
them (slm_lv_post).

Only the two CINE pages: the STILL-like pages animate the object's position.
"""
import functools
import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT / 'projects/open-gate/build'),
               str(ROOT / 'fpSup/uishare'), str(ROOT / 'research/ui/tools')]
import b25_plan as B
import imx410_rate_lv as R
import sl_b25_page as S
import slm_page as SP
from ui import fpui

u32, put = B.u32, S.put
# page -> (the variable, the digit images' prefix)
PAGES = {'LV_CINE_MEDIUM': ('SLM_LvFpsS', 'font_S_'), 'LV_CINE_LARGE': ('SLM_LvFpsM', 'font_M_')}
DONOR = 'RemainingTimeString'
OFF_SCREEN = 4000.0
EXTRA_W = 20.0                      # the text ends (align 3, as every stock digit text) where the stock "FPS" ended
TEXT_LEN = 192                      # slm_state.h SLM_LVTEXT: seven images and the unit


def _set(name):
    s = next(x for x in R.SETS if x['name'] == name)
    B.SETS[name] = (s['start'], s['end'])
    return s


def edit(im, pool, name):
    s = _set(name)
    p = SP.Page(im, name, pool)
    var, _prefix = PAGES[name]
    fr = s['owner']
    assert p.objs[fr][1] == 'FrameRate'
    parent = p.objs[fr][0]
    fr_base = next(r for r in p.records(fr, 0x10004))
    x, y, w, h = struct.unpack_from('>4f', fr_base, 32)
    # the stock object: no position curve in its clip (the STILL-like pages have one), so the base rect is where it is
    clip = next(r for r in p.records(fr, 0x1000A))
    import native_ui_audit as A
    props = A.parse_clip(A.Record(0, bytes(clip)), im.text)['properties']
    assert all(q['name'] in ('image', 'rect') and q['component_ref'] == 3 for q in props), props
    struct.pack_into('>f', fr_base, 36, OFF_SCREEN)

    donor = next(o for o, (_par, nm) in sorted(p.objs.items()) if nm == DONOR)
    src = p.records(donor)
    assert [u32(r, 0) for r in src] == [0x10003, 0x10004, 0x10005, 0x10006], [hex(u32(r, 0)) for r in src]
    obj, base, text, event = (bytearray(r) for r in src)
    assert (u32(obj, 8), u32(obj, 12), u32(obj, 16)) == (3, 0, 0)
    oid = p.next
    p.next += 1
    put(obj, 20, oid); put(obj, 24, parent)
    p.text(obj, 28, var)
    put(base, 20, oid)
    # the donor's own height (= its font size), the bottom edge where the stock bitmap's was.  A box lower than
    # the font draws only the first image (live 11-17: "2" of 29.97 at the stock 35; whole at 38, SS3532).
    dh = struct.unpack_from('>f', base, 44)[0]
    struct.pack_into('>4f', base, 32, x, y - (dh - h), w + EXTRA_W, dh)
    h = dh
    fields = {q: at for at, q, _k, _c in B.fields(im, bytes(text))}
    assert list(fields) == ['text', 'font-size', 'horz-align', 'rect'] and len(text) == 61, fields
    put(text, 20, oid)
    p.text(text, fields['text'], ' ', True)
    # horz-align stays the donor's (3: from the right, live 11-17), so the number ends where the stock "FPS" did
    struct.pack_into('>4f', text, fields['rect'], 0.0, 0.0, w + EXTRA_W, h)
    ev = {q: at for at, q, _k, _c in B.fields(im, bytes(event))}
    assert list(ev) == ['variable-name', 'property-name', 'decimal-places'] and len(event) == 50, ev
    assert pool.text(u32(event, ev['variable-name'])).startswith('LV_RemainingRecTimeString')
    assert pool.text(u32(event, ev['property-name'])) == 'text'
    put(event, 24, oid)
    p.text(event, ev['variable-name'], var)
    p.after(p.records(fr)[-1], [obj, base, text, event])
    par = p.obj(parent)
    put(par, 16, u32(par, 16) + 1)
    p.budgets()
    return p


@functools.lru_cache(None)
def pages():
    im = B.Image()
    pool = S.Pool(im.pool)
    return [edit(im, pool, name) for name in PAGES]


def build():
    return SP.build(pages())


def applied(blob=None):
    pp = pages()
    pool = fpui.Strings(pp[0].im.pool)
    target = {p.name: fpui.PageCopy(p.stock, len(p.stock), p.first) for p in pp}
    fpui.apply(build() if blob is None else blob, target, pool)
    return target, pool


def header():
    data = build()
    lines = ['/* generated by menu/slm_lv_page.py -- do not edit */', '#ifndef SLM_LV_PAGE_H', '#define SLM_LV_PAGE_H',
             '#include <stdint.h>', 'static const uint8_t SLM_LV_PAGE[%d] = {' % len(data)]
    lines += ['    ' + ', '.join(str(v) for v in data[i:i + 20]) + ',' for i in range(0, len(data), 20)]
    return '\n'.join(lines + ['};', '#endif', ''])


if __name__ == '__main__':
    (HERE / 'slm_lv_page.h').write_text(header())
    targets, _pool = applied()
    print('SLM_LV_PAGE %d bytes' % len(build()))
    for p in pages():
        print(p.name, len(p.stock), '->', len(targets[p.name].data), 'objects +', p.next - p.first)
