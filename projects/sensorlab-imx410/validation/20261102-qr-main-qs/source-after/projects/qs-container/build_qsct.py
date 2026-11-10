#!/usr/bin/env python3
"""Build the QS container sup (loader v4): fpSup/QSContainer_v<ver>.BIN.

    python3 -B build_qsct.py --out out          # + out/build.json (offsets, sha256)
    # Optional: --settings-from old.BIN preserves its validated settings record in the new build.

Everything the container needs to know about the firmware's editor is worked
out here from the image (editor_data.py) and carried in the BIN's config; the
camera code only applies it.  No device I/O.

Environment (mutation checks only): QSCT_SRC = another qsct.c;
QSCT_MUTATE = 'nodigits' / 'noend' / 'norange' (drop that edit kind from the
list) or 'stepflag' (keep the twin keys' interpolation flag); QSCT_QS_MUTATE =
one of qs_page_data.MUTATIONS (the QS page table built without that edit).
"""
import argparse
import hashlib
import json
import os
import pathlib
import struct
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FPSUP = ROOT / 'fpSup'
sys.path[:0] = [str(HERE), str(FPSUP / 'loader-v4'), str(FPSUP / 'uishare')]
import build_v4 as B                       # noqa: E402
from ui import fpui, options as O          # noqa: E402
import editor_data as E                    # noqa: E402
import qs_page_data as QP                  # noqa: E402

VERSION = '0.3.5'
SUP_ID = 'QSCT'
NAME = 'QS Container'
SOURCE = HERE / 'qsct.c'
CFG_MAGIC = 0x30435351                     # "QSC0"
CFG_WORDS = 104
STATE_RESERVE = 69632                      # sizeof(struct st) is checked by the entry
DMA_BYTES = 0x800 + 0x600                  # qsct.c FO_BYTES + buffers
REC_WORDS = 2 + 5 * 16 + 1
SETTINGS_CFG_VERSION = 4
SETTINGS_REC_MAGIC = 0x31435351             # "QSC1"
SETTINGS_REC_VERSION = 1
ICON_NAME = 28
QP_NAME = 12                               # qsct.c NAME_BYTES
# FUN_c04b4688's defaults (internal ids): STILL's eight, then CINE's
DEFAULTS = [9, 10, 11, 19, 20, 22, 24, 30, 21, 25, 40, 2, 3, 9, 27, 19]


# The stock bold glyph images (research/ui/tools/nbr_stock.py list font_menu_LB; rendered and read
# 2026-10-29): index = ASCII code, 128 = U+00D7.  LB = the stock QS values' size, SB = the small lines.
def _glyphs(prefix, letters, kigou, extra=()):
    g = {ord(str(d)): f'{prefix}_{d}' for d in range(10)}
    if letters:
        g.update({ord(c): f'{prefix}_id_{c}' for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'})
    g.update({ord(c) if c != 'x' else 128: f'{prefix}_kigou_{n}' for c, n in kigou})
    g.update({ord(c): f'{prefix}_{n}' for c, n in extra})
    return g


GLYPHS = [_glyphs('font_menu_LB', True, [('.', '01'), (':', '02'), (';', '03'), ('-', '04'), ('/', '05'),
                                          ('+', '07'), ('x', '09'), ('#', '16'), ('%', '17')]),
          _glyphs('font_menu_SB', False, [('.', '01'), (':', '02'), ('-', '04'), ('/', '05'), ('+', '07'),
                                           ('x', '09')],
                  [('K', 'tex_kelvin'), ('F', 'tex_iris_F'), ('T', 'tex_iris_T'), ('s', 'tex_time_3')])]
LOCK_ICONS = ['menu_select_unlock', 'menu_select_lock']    # qsc.h QSC_LOCK_OPEN, QSC_LOCK_SHUT
ARROWS = ['menu_arrow_M_left', 'menu_arrow_M_right']       # the stock footer spinner's (colour temperature)


class BuildError(RuntimeError):
    pass


def glyph_widths():
    """N_GLYPH bytes: the width (px, the XCI header) of each LB glyph image, 0 = none (qsct.c qc_value_width)"""
    sys.path.insert(0, str(ROOT / 'research' / 'ui' / 'tools'))
    import nbr_stock as N
    nbr = N.StockNbr((ROOT / 'out' / 'seg0_c0000000.bin').read_bytes())
    by = {e.path.rsplit('/', 1)[-1]: e for e in nbr.entries}
    out = bytearray(129)
    for c, name in GLYPHS[0].items():
        e = by.get(name + '.xci')
        if e is None:
            raise BuildError('no glyph image ' + name)
        out[c] = struct.unpack_from('<H', nbr._bytes(e.data_address, 12), 8)[0]
    return bytes(out)


def file_name():
    return f'QSContainer_v{VERSION}.BIN'


def compile_code(src):
    with tempfile.TemporaryDirectory(prefix='qsct-') as t:
        return B.compile_unit(pathlib.Path(t), pathlib.Path(src), 'sup_entry', ['-I', str(HERE)])


def edits_for(page, mutate):
    edits = E.page_edits(page)
    drop = {'nodigits': E.K_DIGIT, 'noend': E.K_SET_END, 'norange': E.K_ADDF_N}.get(mutate)
    if drop:
        edits = [e for e in edits if e[1] != drop]
    if mutate == 'stepflag':
        edits = [e for e in edits if e[1] != E.K_SETFLAG]
    return edits


def settings_record(source):
    """Validate a complete saved BIN and return its unchanged settings record.

    This only checks the file/record envelope and FNV integrity. The compiled
    client's record loader remains responsible for field semantics. A blank
    default record is deliberately refused when migration is requested.
    """
    path = pathlib.Path(source).resolve()
    data = path.read_bytes()
    hdr = B.SL4_HEADER_LEN
    if len(data) < hdr + 4 * CFG_WORDS:
        raise BuildError('settings source is too short for header/config')
    h = struct.unpack_from('<12I', data)
    magic, hlen, flen, block, entry, sid = h[:6]
    if magic != 0x34425346 or hlen != hdr or flen != len(data):
        raise BuildError('settings source has an invalid v4 file header/length')
    if sid != int.from_bytes(SUP_ID.encode('ascii'), 'little'):
        raise BuildError('settings source sup_id does not match ' + SUP_ID)
    if block < flen or not hdr <= (entry & ~1) < flen:
        raise BuildError('settings source has an invalid block/entry range')
    cfg_magic, cfg_version, state, dma, off = struct.unpack_from('<5I', data, hdr)
    if cfg_magic != CFG_MAGIC or cfg_version != SETTINGS_CFG_VERSION:
        raise BuildError('settings source config magic/version is unsupported')
    if state < flen or dma < state or h[9] != dma or dma + h[10] > block:
        raise BuildError('settings source has an invalid state/DMA range')
    size = 4 * REC_WORDS
    if off & 3 or off < hdr + 4 * CFG_WORDS or off + size > flen:
        raise BuildError('settings source record range is invalid')
    record = data[off:off + size]
    words = struct.unpack(f'<{REC_WORDS}I', record)
    if words[:2] != (SETTINGS_REC_MAGIC, SETTINGS_REC_VERSION):
        raise BuildError('settings source record magic/version is unsupported or blank')
    checksum = 2166136261
    for byte in record[:-4]:
        checksum = ((checksum ^ byte) * 16777619) & 0xFFFFFFFF
    if checksum != words[-1]:
        raise BuildError('settings source record FNV checksum mismatch')
    manifest = dict(source_file=str(path), source_bytes=len(data),
                    source_sha256=hashlib.sha256(data).hexdigest(), source_sup_id=SUP_ID,
                    source_file_version=h[6], source_cfg_version=cfg_version,
                    source_rec_off=off, record_bytes=size, record_words=REC_WORDS,
                    record_magic=f'{words[0]:08x}', record_version=words[1],
                    record_fnv1a32=f'{checksum:08x}',
                    record_sha256=hashlib.sha256(record).hexdigest())
    return record, manifest


def build(*, src=None, mutate=None, name=None, sup_id=SUP_ID, settings_from=None):
    record, settings = settings_record(settings_from) if settings_from is not None else (bytes(4 * REC_WORDS), None)
    if settings is not None and sup_id != SUP_ID:
        raise BuildError("settings migration requires the canonical sup_id")
    src = src or os.environ.get('QSCT_SRC') or SOURCE
    mutate = os.environ.get('QSCT_MUTATE', '') if mutate is None else mutate
    text = compile_code(src)
    hdr = B.SL4_HEADER_LEN
    body = bytearray(4 * CFG_WORDS) + text.code
    entry = hdr + 4 * CFG_WORDS + text.functions['sup_entry']

    def place(data, align=4):
        body.extend(bytes(-(hdr + len(body)) % align))
        at = hdr + len(body)
        body.extend(data)
        return at

    icons = E.icon_table()
    names = sorted(icons)
    if E.DEFAULT_ICON not in icons:
        raise BuildError('the default icon has no look')
    for n in names:
        if len(n) >= ICON_NAME:
            raise BuildError('icon name too long: ' + n)
    icons_off = place(b''.join(n.encode().ljust(ICON_NAME, b'\0') + struct.pack('<4I', *icons[n]) for n in names))
    page_name, page_name_len, page_entry, page_len, edits_off, n_edits, page_csv, ins_max = ([] for _ in range(8))
    for p in E.PAGES:
        a, off, n = O.resource_set(p)
        ed = edits_for(p, mutate)
        page_name.append(place(p.encode() + b'\0'))
        page_name_len.append(len(p))
        page_entry.append(off)
        page_len.append(n)
        edits_off.append(place(E.pack_edits(ed)))
        n_edits.append(len(ed))
        page_csv.append(E.PAGE_CSV[p])
        ins_max.append(10 * sum(1 for e in ed if e[1] == E.K_INS))
    blk = fpui.Block()
    O.hook_fv(blk)
    fpui_block = blk.encode()
    fpui_off = place(fpui_block, 8)
    # stage 2: the QS page table, the QS looks, the variable names
    design = QP.Design(mutate=os.environ.get('QSCT_QS_MUTATE') or None)
    qs_blob, qs = QP.table(design)
    qs_off = place(qs_blob)
    looks = QP.qs_icon_looks(names)
    if any(x is None for x in looks):
        raise BuildError('an icon without one QS look')
    looks_off = place(b''.join(struct.pack('<4I', *x) for x in looks))
    names_off = place(b''.join(n.encode().ljust(QP_NAME, b'\0') for n in QP.NAMES))
    blank_off = place(b' \0\0\0')
    if blank_off != names_off + QP_NAME * len(QP.NAMES):
        raise BuildError('the blank text must follow the names')
    qs_name_off = place(QP.PAGE.encode() + b'\0')
    # v0.2.1: the bold glyphs (LB: the stock values, SB: the small lines), the markup, the lock icons
    gstr, gtab = {}, []
    for font in GLYPHS:
        for c in range(129):
            name = font.get(c)
            if name and name not in gstr:
                gstr[name] = place(f'<!{name},CENTER>'.encode() + b'\0', 1)
            gtab.append(gstr[name] if name else 0)
    glyph_off = place(struct.pack(f'<{len(gtab)}I', *gtab))
    mk_open = place(b'<!\0', 1)
    mk_close = place(b',CENTER>\0', 1)
    lock_off = [place(f'<!{n},CENTER>'.encode() + b'\0', 1) for n in LOCK_ICONS]
    arrow_off = [place(f'<!{n},CENTER>'.encode() + b'\0', 1) for n in ARROWS]
    gwidth_off = place(glyph_widths(), 1)
    mark_off = place(QP.MARK_TEXT.encode() + b'\0', 1)
    _a, qs_entry, qs_len = O.resource_set(QP.PAGE)
    rec_off = place(record)
    _code, fv_entry, fv_table_word = O.handler()
    display = name or NAME
    probe = B.make_sup(bytes(body), entry, sup_id, min_svc=B.SL4_SVC_VERSION, flags=B.SL_F_CACHED_OK,
                       name=display)
    file_len = len(probe)
    state_off = (file_len + 63) & ~63
    dma_off = (state_off + STATE_RESERVE + 63) & ~63
    block = dma_off + DMA_BYTES
    t_of = [E.t_of(E.UI_BASE + i) for i in range(E.MAX_FUNCS)]
    words = [CFG_MAGIC, 4, state_off, dma_off, rec_off, fpui_off, len(fpui_block), fv_entry, fv_table_word,
             *[a for _n, a, _s in E.CSVS], *[s for _n, _a, s in E.CSVS],
             icons_off, len(names), names.index(E.DEFAULT_ICON),
             *page_name, *page_name_len, *page_entry, *page_len, *edits_off, *n_edits, *page_csv, *ins_max,
             *t_of, *E.digit_offsets(), *DEFAULTS, 1 if QP.MENU_BACK else 0,
             qs_off, qs['n_targets'], qs['ops_off'], qs['patches_off'], qs['frags_off'], qs['out_total'],
             qs_entry, qs_len, qs_name_off, len(QP.PAGE), names_off, blank_off,
             E.POOL + QP.pstr('QS_QSMode'), looks_off,
             E.POOL + QP.pstr('QS_FocusPos'), E.POOL, glyph_off, mk_open, mk_close, *lock_off, *arrow_off,
             gwidth_off, mark_off]
    if len(words) != CFG_WORDS:
        raise BuildError(f'config has {len(words)} words, qsct.c expects {CFG_WORDS}')
    body[0:4 * CFG_WORDS] = struct.pack(f'<{CFG_WORDS}I', *words)
    blob = B.make_sup(bytes(body), entry, sup_id, min_svc=B.SL4_SVC_VERSION, flags=B.SL_F_CACHED_OK,
                      name=display, block_size=block, dma=(dma_off, DMA_BYTES),
                      version=int(VERSION.replace('.', '')))
    if len(blob) != file_len:
        raise BuildError('layout moved')
    info = dict(file=file_name(), bytes=len(blob), sha256=hashlib.sha256(blob).hexdigest(), entry=entry,
                code=len(text.code), state_off=state_off, dma_off=dma_off, block_size=block, rec_off=rec_off,
                icons_off=icons_off, icons=names, edits_off=edits_off, n_edits=n_edits, page_entry=page_entry,
                page_len=page_len, fpui_off=fpui_off, qs_off=qs_off, qs=qs, names_off=names_off,
                looks_off=looks_off, qs_notes=design.notes, functions=text.functions)
    if settings is not None:
        info['settings_from'] = settings
    return blob, info


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--out', required=True)
    ap.add_argument('--settings-from', type=pathlib.Path, help='validated complete saved BIN; copy its settings record')
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    if a.settings_from is not None and (out / 'fpSup' / file_name()).resolve() == a.settings_from.resolve():
        raise BuildError('output would overwrite the settings source')
    (out / 'fpSup').mkdir(parents=True, exist_ok=True)
    blob, info = build(settings_from=a.settings_from)
    (out / 'fpSup' / file_name()).write_bytes(blob)
    info.pop('functions')
    (out / f'build-{VERSION}.json').write_text(json.dumps(info, indent=1) + '\n')   # v0.2.1's build.json stays
    print(f'{file_name()}  {len(blob)} B  {info["sha256"][:16]}')


if __name__ == '__main__':
    main()
