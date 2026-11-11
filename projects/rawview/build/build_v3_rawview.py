#!/usr/bin/env python3
"""raw-view as a Loader v3 sup: \\fpSup\\45RAWV.BIN.

    python3 -B build_v3_rawview.py --out /absolute/new/directory [--card]

projects/usb-shell-sup/notes/LOADER_V3.md §8 step 5. The same launcher,
resident code and tables as build_rawview.py (the AutoRun card), assembled with
V3=1; the uishare UI section (the COLOR list's RAW row) rides inside the file.

    [FSB1 header 32][settings 32][rv_launch][rv_resident][tables][UI section][claims]
    [zeroed tail: T0 area, 4 KiB aligned, ALLOC bytes]

  - entry(block, svc, path) claims every site first (CHAIN: the three call
    sites whose stub only passes through -- power-off save, picture-quality
    command, key-frame name; EXCL: the rest; SHARED_UI: uishare's file-redirect
    site), then the old GUARDs, then builds the tables inside its own block,
    takes the veneers from svc->cave_alloc, applies the UI block, and only then
    writes the firmware. Any refusal before that is SL_RELEASE, nothing written.
  - no H_GET, no CAVE_BUMP, no copy of the launcher: the block is the file.
  - the user's settings (RAW on, SA/GA, contrast, saturation) live in the
    file's own 32-byte settings record (+32). stub_sv, at the firmware's
    power-off save, rewrites that record in place when it changed (open 7,
    seek, write 32 B, read back -- lossless's idiom); the firmware's own settings are no longer touched (the old
    card stored RAW as colour 0x10-0x17). A camera that still holds 0x10-0x17
    from an old card is read once and put back to 0xC.

--out DIR writes DIR/45RAWV.BIN and build.json. --card makes DIR a whole v3
card: AutoRun, frames, shell and lossless from --from-card, the current
LOADER.BIN (min_svc 2: an older 加載器 refuses this header), and this.
Never writes a camera card.
"""
import argparse
import hashlib
import json
import pathlib
import shutil
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FPSUP = ROOT / 'fpSup'
V3DIR = FPSUP / 'fp_usb_shell' / 'v3'
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(V3DIR))
sys.path.insert(0, str(FPSUP / 'uishare'))

import build_rawview as R                                 # noqa: E402
import build_v3 as B                                      # noqa: E402
import rv_color                                           # noqa: E402
import rv_uidata                                          # noqa: E402
from armasm import assemble, symbols                      # noqa: E402

NAME = '45RAWV.BIN'
SUP_ID = 'RAWV'
VERSION = 1
CHAIN, EXCL, SHARED_UI = 1, 2, 3
CFG_MAGIC = 0x31535652                                    # "RVS1"
CFG_LEN = 32
ALLOC = 0x82000                                           # rv_launch.S ALLOC
KEEP = ('LOADER.BIN', '00SHELL.BIN', '10LOSS.BIN')
STEP2_CARD = ROOT / 'projects/usb-shell-sup/cards/20261006-v3-step4-og3k'   # LOADER.BIN with service v2

# RAW-View 0.4 (cols=True): a COL-Share client (fpSup/colshare/DESIGN.md P3).  The header version is
# what COL-Share's old-RAW-View check reads (colshare_ui.RAWVIEW_CLIENT = 0x000400: maj<<16|min<<8|patch).
COLS_VERSION = 0x000400
COLS_VERSION_TEXT = '0.4.0test'
COLS_FILE = f'RAW-View_v{COLS_VERSION_TEXT}.BIN'      # names_v4 still says 0.3.1: the coordinator bumps it
# its own sites only: gain A/B (RAW_CORR 0xC032F728 too -- EXCL for now, LUT may want it later), saturation x4,
# contrast / sharpness x8, the DNG writer's OFF constants x4, CHAIN power-off save and picture-quality command
COLS_KEEP = {0xC0313244, 0xC032F728, 0xC056D5F8, 0xC056D498, 0xC059588C, 0xC05959E4,
             0xC056D548, 0xC056D3E8, 0xC056D5A0, 0xC056D440, 0xC059581C, 0xC0595974, 0xC0595854, 0xC05959AC,
             0xC02C4BE4, 0xC02C4BE8, 0xC02C4C98, 0xC02C4C9C, 0xC0088C60, 0xC02B8E64}
COLS_STUBS = ('stub_gs', 'stub_dg', 'stub_sa', 'stub_sn', 'stub_zc', 'stub_zs', 'stub_znc', 'stub_zns',
              'stub_sv', 'stub_pq')

H1_SITE = 0xC05E5BEC
ADV_SITE = 0xC1D6ED48
# the call sites whose stubs only pass through to what was there (resident *_next)
CHAIN_SITES = {0xC0088C60: 'sv_next', 0xC02B8E64: 'pq_next', 0xC05E2200: 'ai_next'}
# V3 launcher calls: firmware routines by movw/movt ip, the service table by
# `ldr ip, [r0, #off]`, uia_apply by `add ip, r6, ip`.
V3_ALLOWED = {0xC000E91C, 0xC000EABC, 0xC0057AE8, 0xC005C958}
SVC_OFFS = {8, 16, 20}                                    # claim, chain_next, cave_alloc


class BuildError(RuntimeError):
    pass


def ui_section(v4=False):
    """v4: the same block in fpsup-ui's section (fpui_stock.c, no string layer)."""
    from ui import options as ui_options
    block = ui_options.color_raw(rv_uidata.ICONS[0][3].read_bytes()).encode()
    if v4:
        sys.path.insert(0, str(FPSUP / 'fpsup-ui'))
        import build_stock_section
        return build_stock_section.section(block)
    import build_section
    return build_section.section(block)


def claim_rows(ui_sites):
    """(address, stock bytes, kind): what the V3 launcher and its stubs write.
    The AutoRun card's declared sites, without what only --legacy-ui wrote
    (H1 and the page words other than ADV_SITE: uishare does those now)."""
    legacy = {H1_SITE} | {a for a, _, _ in rv_uidata.PAGE if a != ADV_SITE}
    rows = []
    for a, word, why in R.hook_sites():
        if a in legacy:
            continue
        rows.append((a, word, CHAIN if a in CHAIN_SITES else EXCL))
    have = {a for a, *_ in rows}
    for a, stock in ui_sites:
        if a in have:
            raise BuildError(f'0x{a:08X}: both a raw-view site and a UI site')
        rows.append((a, struct.pack('<I', stock), SHARED_UI))
    if set(CHAIN_SITES) - have or ADV_SITE not in have:
        raise BuildError('a CHAIN site or ADV_SITE is not declared in build_rawview')
    for a, s, _ in rows:
        if a < R.SEG1_BASE and B.stock(a, 4) != s:
            raise BuildError(f'0x{a:08X}: stock is not the reference image')
    return sorted(rows)


def claim_rows_cols():
    """RAW-View 0.4: only what no other sup uses (COL-Share has the COLOR list and the root words)."""
    rows = [(a, w, CHAIN if a in CHAIN_SITES else EXCL) for a, w, _ in R.hook_sites() if a in COLS_KEEP]
    if {a for a, *_ in rows} != COLS_KEEP:
        raise BuildError('a COL-Share client site is not declared in build_rawview')
    for a, s, _ in rows:
        if B.stock(a, 4) != s:
            raise BuildError(f'0x{a:08X}: stock is not the reference image')
    return sorted(rows)


def write_icon_inc():
    """rv_launch.S (COLS): the RAW row's icon, handed to COL-Share by cb_icon (rv_uidata is the one source)."""
    data = rv_uidata.ICONS[0][3].read_bytes()
    out = ['/* 由 build_v3_rawview.py 產生,勿手改 */', 'cb_icon_data:']
    for j in range(0, len(data), 16):
        out.append('    .byte ' + ', '.join(f'0x{b:02X}' for b in data[j:j + 16]))
    (HERE / 'rv_icon.inc').write_text('\n'.join(out) + '\n')
    return len(data)


def claims_table(rows):
    """count, {addr, len, kind, stock_off from the table}, then the stock bytes."""
    base = 4 + 16 * len(rows)
    head, data = struct.pack('<I', len(rows)), b''
    for a, s, k in rows:
        head += struct.pack('<4I', a, len(s), k, base + len(data))
        data += s
    return head + data


def check_calls(code, cols=False):
    """The V3 launcher's calls: allowed firmware routines, the service table, uia_apply.
    No direct bl.  cols: COL-Share's api / the service table through any register
    (`ldr ip, [rN, #off]`), and `bl` only inside the launcher (rv_install)."""
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
    lo = hi = None
    last = None                                           # what last wrote ip
    for i in md.disasm(code, 0):
        ops = i.op_str
        if i.mnemonic == 'movw' and ops.startswith('ip,'):
            lo, last = int(ops.split('#')[1], 0), 'movw'
        elif i.mnemonic == 'movt' and ops.startswith('ip,'):
            hi, last = int(ops.split('#')[1], 0), ('fw' if last == 'movw' else 'odd')
        elif i.mnemonic == 'ldr' and ops.startswith('ip, [r0, #'):
            off = int(ops.split('#')[1].rstrip(']'), 0)
            last = 'svc' if off in SVC_OFFS or cols else 'odd'
        elif cols and i.mnemonic == 'ldr' and ops.startswith('ip, [r') and ', #' in ops:
            last = 'svc'
        elif i.mnemonic == 'add' and ops == 'ip, r6, ip':
            last = 'ui' if last == 'fw' else 'odd'
        elif i.mnemonic == 'blx':
            if ops != 'ip':
                raise BuildError(f'blx {ops} at {i.address:#x}')
            if last == 'fw' and ((hi << 16) | lo) not in V3_ALLOWED:
                raise BuildError(f'launcher calls 0x{(hi << 16) | lo:08X} at {i.address:#x}')
            if last not in ('fw', 'svc', 'ui'):
                raise BuildError(f'blx ip at {i.address:#x}: ip from {last}')
        elif i.mnemonic == 'bl' and cols and 0 <= int(ops.lstrip('#'), 0) < len(code):
            pass
        elif i.mnemonic == 'bl':
            raise BuildError(f'launcher has a direct bl at {i.address:#x}')
        elif ops.startswith('ip,') and i.mnemonic not in ('movw', 'movt'):
            last = 'other'


def build(v4=False, name=b'', cols=False):
    """v4 (build_v4_rawview.py): the FSB4 header (48 B, the record after it),
    rv_*.S V4=1 (file_is before a save, the record reaching memory first),
    fpsup-ui's section for the row; `name` (the display name) ends the file.
    cols (v4 only, RAW-View 0.4): a COL-Share client -- no UI section, no COLOR points."""
    if cols and not v4:
        raise BuildError('cols needs v4')
    HL = 48 if v4 else B.SL_HEADER_LEN
    for w in (R.write_csv_inc, R.write_page_inc, R.write_mat_inc, R.write_sat_inc,
              R.write_dngcm_inc):
        w()
    res_src = HERE / 'rv_resident.S'
    rdefs = ['V3=1'] + (['V4=1'] if v4 else []) + (['COLS=1'] if cols else [])
    icon_len = write_icon_inc() if cols else 0
    res = assemble(res_src, rdefs)
    rs = symbols(res_src, rdefs)
    if rs['params'] != 0 or rs['sat_tab'] != 0x1D0:
        raise BuildError('params moved')
    res += b'\0' * (-len(res) % 4)
    if 0x3E200 + len(res) > 0x40800:
        raise BuildError(f'resident {len(res)} B runs into the matrix copy')
    tdata = R.rv_tables.blob()
    if cols:
        sec, ui = b'', {}
        rows = claim_rows_cols()
    else:
        sec, ui = ui_section(v4)
        rows = claim_rows(ui['sites'])
    ctab = claims_table(rows)

    sec_off = (len(res) + len(tdata) + 3) & ~3
    claims_off = (sec_off + len(sec) + 3) & ~3
    tail = res + tdata
    tail += b'\0' * (sec_off - len(tail)) + sec
    tail += b'\0' * (claims_off - len(tail)) + ctab
    name_at = len(tail)
    tail += name

    stub = {k: rs[k] for k in (COLS_STUBS if cols else
                               ('stub_gs', 'stub_dg', 'stub_ma', 'stub_mb', 'stub_mc', 'stub_fv',
                               'stub_ml', 'stub_ef', 'stub_en', 'stub_sa', 'stub_sn', 'stub_mj',
                               'stub_mo', 'stub_mx', 'stub_zc', 'stub_zs', 'stub_znc', 'stub_zns',
                               'stub_ai', 'stub_sv', 'stub_pq'))}

    def defines(scr_off):
        if cols:
            d = [f'RES_LEN=0x{len(res):X}', f'TDATA_OFF=0x{len(res):X}',
                 f'CMBUF=0x{rs["cm_buf"]:X}', f'CMTAB=0x{rs["cm_tab"]:X}',
                 'UISHARE=1', 'V3=1', 'V4=1', 'COLS=1', f'SCR_OFF=0x{scr_off:X}',
                 f'CLAIMS_OFF=0x{claims_off:X}', f'SAT_MAX={rv_color.SAT_MAX}', f'ICON_LEN={icon_len}',
                 f'NEXT_SV=0x{rs["sv_next"]:X}', f'NEXT_PQ=0x{rs["pq_next"]:X}', f'NEXT_SVC=0x{rs["sv_svc"]:X}']
            return d + [f'{k.upper()}=0x{v:X}' for k, v in stub.items()]
        d = [f'RES_LEN=0x{len(res):X}', f'TDATA_OFF=0x{len(res):X}',
             f'CMBUF=0x{rs["cm_buf"]:X}', f'CMTAB=0x{rs["cm_tab"]:X}',
             'UISHARE=1', 'V3=1', f'SCR_OFF=0x{scr_off:X}', f'CLAIMS_OFF=0x{claims_off:X}',
             f'UI_APPLY=0x{sec_off + ui["uia_apply"]:X}', f'UI_BLOCK=0x{sec_off + ui["block_off"]:X}',
             f'UI_LEN=0x{ui["block_len"]:X}', f'SAT_MAX={rv_color.SAT_MAX}',
             f'NEXT_SV=0x{rs["sv_next"]:X}', f'NEXT_PQ=0x{rs["pq_next"]:X}',
             f'NEXT_AI=0x{rs["ai_next"]:X}'] + (['V4=1', f'NEXT_SVC=0x{rs["sv_svc"]:X}'] if v4 else [])
        return d + [f'{k.upper()}=0x{v:X}' for k, v in stub.items()]

    src = HERE / 'rv_launch.S'
    probe = assemble(src, defines(0))
    file_len = HL + CFG_LEN + len(probe) + len(tail)
    file_len += -file_len % 4
    launch = assemble(src, defines(file_len))
    ls = symbols(src, defines(file_len))
    if len(launch) != len(probe) or ls['blob'] != len(launch) or ls['entry'] != 0:
        raise BuildError('the launcher moved when the offsets went in')
    check_calls(launch[:ls['cb_data']] if cols else launch, cols)
    cfg = struct.pack('<8I', CFG_MAGIC, 0, 0, 0, 0, 0, 0, 0)
    body = cfg + launch + tail
    block = file_len + 0xFFF + ALLOC
    block += -block % 0x1000
    if v4:
        sys.path.insert(0, str(FPSUP / 'loader-v4'))
        import build_v4 as B4
        data = bytearray(B4.make_sup(body, HL + CFG_LEN, SUP_ID, version=COLS_VERSION if cols else VERSION,
                                     block_size=block,
                                     min_svc=5, flags=B4.SL_F_CACHED_OK))
        if name:
            struct.pack_into('<I', data, 44, HL + CFG_LEN + len(launch) + name_at)
        data = bytes(data)
    else:
        data = B.make_sup(body, B.SL_HEADER_LEN + CFG_LEN, SUP_ID, VERSION, block_size=block,
                          min_svc=2)
    if len(data) != file_len:
        raise BuildError('file length')
    facts = {'file_len': file_len, 'block': block, 'launch': len(launch), 'resident': len(res),
             'tables': len(tdata), 'ui_section': len(sec), 'claims': len(rows),
             'entry': HL + CFG_LEN, 'cfg_off': HL,
             'blob_off': HL + CFG_LEN + len(launch),
             'res_syms': {k: rs[k] for k in ('sv_next', 'pq_next', 'stub_sv', 'stub_gs') +
                          (('stub_pq', 'stub_sa', 'stub_zc', 'stub_dg') if cols else ('ai_next',))},
             'launch_syms': {k: ls[k] for k in ('cb_state', 'rv_install')} if cols else {},
             'defines': defines(file_len),
             'claims_list': [{'address': f'0x{a:08X}', 'bytes': len(s),
                              'kind': {CHAIN: 'CHAIN', EXCL: 'EXCL', SHARED_UI: 'SHARED_UI'}[k]}
                             for a, s, k in rows]}
    return data, facts, rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--out', type=pathlib.Path, required=True)
    ap.add_argument('--card', action='store_true',
                    help='a whole v3 card: AutoRun, frames, 00SHELL and 10LOSS from --from-card, '
                         'the current LOADER.BIN, and this sup')
    ap.add_argument('--from-card', type=pathlib.Path, default=STEP2_CARD,
                    help='where --card takes AutoRun, LOADER.BIN, UI frames and the other sups')
    a = ap.parse_args()
    out = a.out.resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f'{out} is not empty: this never overwrites a build or a card')
    data, facts, _ = build()
    out.mkdir(parents=True, exist_ok=True)
    if a.card:
        src = a.from_card.resolve()
        shutil.copy2(src / 'AutoRun.txt', out / 'AutoRun.txt')
        shutil.copytree(src / 'fpSup', out / 'fpSup')
        for p in (out / 'fpSup').glob('*.BIN'):     # keep the shell and lossless only
            if p.name not in KEEP:
                p.unlink()
        # this sup needs service v2 (its own path in r2): the current 加載器
        (out / 'fpSup' / B.SL_SELF).write_bytes(B.loader_bin()[0])
        (out / 'fpSup' / NAME).write_bytes(data)
        lines = [f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(out)}'
                 for p in sorted(out.rglob('*')) if p.is_file()]
        (out / 'MANIFEST.sha256').write_text('\n'.join(lines) + '\n')
    else:
        (out / NAME).write_bytes(data)
    sources = [pathlib.Path(__file__), HERE / 'build_rawview.py', HERE / 'rv_launch.S',
               HERE / 'rv_resident.S']
    (out / 'build.json').write_text(json.dumps({
        'product': 'raw-view, Loader v3 sup', 'file': NAME, 'sup_id': SUP_ID,
        'version': VERSION, 'card': a.card, 'from_card': str(a.from_card) if a.card else None,
        'sha256': hashlib.sha256(data).hexdigest(), 'facts': facts,
        'sources': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sources}}, indent=1, ensure_ascii=False) + '\n')
    print(f'{NAME}  {len(data)} B  block {facts["block"]:#x}  claims {facts["claims"]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
