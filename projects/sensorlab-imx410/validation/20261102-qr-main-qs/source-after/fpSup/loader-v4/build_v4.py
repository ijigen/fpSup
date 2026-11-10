#!/usr/bin/env python3
"""Build Loader v4: the core (\\fpSup\\LOADER.BIN), SUPMGR.BIN and the USB shell (names_v4: USB-Shell_v3.4.0.BIN).
Design: projects/loader-v4/DESIGN.md.  v3/ is not touched; its helpers
(the AutoRun builder, the boot envelope, patch_sup.S, the shell worker) are
reused as they are.

    python3 -B fpSup/loader-v4/build_v4.py --out DIR            # DIR/fpSup/{LOADER,SUPMGR}.BIN + the shell
                                                    # + DIR/AutoRun.txt
"""
import argparse, pathlib, re, shutil, struct, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
FPSUP = HERE.parent                          # fpSup/loader-v4 (moved from fp_usb_shell/v4, 2026-10-21)
SHELL_DIR = FPSUP / 'fp_usb_shell'          # v3's build and the host tools v4 reuses
ROOT = FPSUP.parent
sys.path.insert(0, str(SHELL_DIR / 'v3'))
sys.path.insert(0, str(SHELL_DIR))
sys.path.insert(0, str(ROOT / 'research' / 'ui' / 'tools' / 'arm_text'))

import cave
import build_v3 as V3
from armasm import assemble, symbols

SL_DIR, SL_SELF = 'fpSup', 'LOADER.BIN'
SL4_MAGIC = 0x34425346                      # "FSB4"
SL4_HEADER_LEN = 48
SL4_SVC_VERSION = 6                         # the min_svc a sup asks for: 6 adds file_read, borrow
SL4_LOADER_SVC = 7                          # sloader4.h SL4_SVC_VERSION: what the core gives (7: ui_go)
SL_F_CACHED_OK = 1
SMGR_ID = 'SMGR'
DS_MAGIC, DS_MAX = 0x53445346, 30
CFLAGS = V3.CFLAGS


class BuildError(RuntimeError):
    pass


def _id(sup_id):
    if isinstance(sup_id, str):
        return struct.unpack('<I', sup_id.encode().ljust(4, b'\0')[:4])[0]
    return sup_id


UI_DIR, UI_FILE = 'UI', 'FPSUP.BIN'          # the home page's data (uishare/tab/build_fp4.py)
FPSUP_UI = FPSUP / 'fpsup-ui'                # the page library every v4 sup may #include
UI_SITES = (('STOCK_GUI', 0xC056461C), ('STOCK_RES', 0xC05E5B58),   # fpsup_home.c's four sites
            ('STOCK_OWN', 0xC05E61C8), ('STOCK_REM', 0xC05E61E0))


def ui_stock_defines():
    """The four sites' stock words, from the firmware image (fpsup_home.c STOCK_*)."""
    img = (ROOT / 'out/MAIN_c0000000.bin').read_bytes()
    out = []
    for name, a in UI_SITES:
        w = struct.unpack_from('<I', img, a - 0xC0000000)[0]
        out.append(f'-D{name}=0x{w:08X}u')
    if out[0] != '-DSTOCK_GUI=0xEB000005u':
        raise BuildError('0xC056461C is not the stock bl FUN_c0564638')
    return out


def compile_unit(tmp, src, entry, extra=(), ui=False):
    """One -fropi C file -> (code bytes, {function: offset})."""
    import elf_text
    if ui:                                   # fpsup_home.c: the fpSup page and the two fixed-rule hooks
        extra = [*extra, '-DFPSUP_UI=1', *ui_stock_defines()]
    obj = tmp / (src.stem + '.o')
    clang = shutil.which('clang') or 'clang'
    r = subprocess.run([clang, *CFLAGS, *V3.cdefs(), *extra, '-c', '-I', str(HERE), '-I', str(FPSUP_UI),
                        str(src), '-o', str(obj)], capture_output=True, text=True)
    if r.returncode:
        raise BuildError(f'{src.name}: compile failed:\n' + r.stderr)
    text = elf_text.load_text(obj)
    if not text.functions.get(entry, 0) & 1:
        raise BuildError(f'{src.name}: {entry} missing or not Thumb')
    return text


MARK_DEFINES = ['-DBOOT_MARKERS=1', '-DMARK_AT=0xC072E064u', '-DMARK_DATA=0xC072E0B4u', '-DMARK_BYTES=0x98u',
                '-DMARK_LIVE=0x314B524Du', '-DMARK_SEEN=0x444B524Du', '-DMARK_NONE=0x454E4F4Eu']
# = build_autorun.py MARK_AT (CAVE_ARENA), MARK_BYTES, MARK_MAGIC; 'MRKD' seen, 'NONE' stale


def loader_bin(file_offset=None, splash=False, src=None, markers=False, pwroff_log=False, entry_src=None,
               pwroff_file=False, ui=False):
    """The v4 core as a VBIN with no sections, then its disabled list.
    `src`: another sloader4.c (the mutation check).  `markers`: BOOT_MARKERS.
    `pwroff_log`: PWROFF_LOG, the debug power-off decision log (README "關機紀錄器").
    `pwroff_file`: PWROFF_FILE, a debug power-off record in \\fpSup\\PWROFF.LOG (README "關機紀錄寫卡").
    `ui`: FPSUP_UI, the fpSup page and the page-id / string hooks (fpsup_home.c; data \\fpSup\\UI\\FPSUP.BIN)."""
    with tempfile.TemporaryDirectory(prefix='slv4-') as t:
        text = compile_unit(pathlib.Path(t), src or HERE / 'sloader4.c', 'sl_boot',
                            [*(MARK_DEFINES if markers else ()), *(['-DPWROFF_LOG=1'] if pwroff_log else ()),
                             *(['-DPWROFF_FILE=1'] if pwroff_file else ())], ui=ui)
    src = entry_src or HERE / 'sloader4_entry.S'
    strs = [f'SL_DIR="\\\\{SL_DIR}"', f'SL_SELF="{SL_SELF}"', *(V3.splash_defines() if splash else []),
            *([f'SL_FILE_OFFSET={file_offset}'] if file_offset is not None else []),
            *(['PWROFF_LOG=1'] if pwroff_log else []),
            *(['POFF_HOOK=1'] if pwroff_log or pwroff_file else []),
            *([f'UI_PATH="\\\\{SL_DIR}\\\\{UI_DIR}\\\\{UI_FILE}"'] if ui else [])]
    c_base = symbols(src, ['C_BOOT=1', *strs])['c_base']
    defines = [f'C_BOOT={c_base + text.functions["sl_boot"]}', *strs]
    stub = assemble(src, defines)
    if len(stub) != c_base or symbols(src, defines)['c_base'] != c_base:
        raise BuildError('the stub moved when the offset went in')
    code = stub + text.code
    code += b'\0' * (-len(code) % 4)
    vbin = struct.pack('<4sIII', b'VBIN', 0, 0, len(code)) + code
    vbin += struct.pack('<II', DS_MAGIC, 0) + bytes(4 * DS_MAX)
    return vbin, {'stub': len(stub), 'c_text': len(text.code), 'bytes': len(vbin)}


def with_disabled(vbin, ids):
    """LOADER.BIN with `ids` on its disabled list (tests, and a merge page)."""
    tail = 8 + 4 * DS_MAX
    body = vbin[:-tail]
    ids = [_id(i) for i in ids]
    if len(ids) > DS_MAX:
        raise BuildError('disabled list full')
    return body + struct.pack('<II', DS_MAGIC, len(ids)) + b''.join(struct.pack('<I', i) for i in ids) \
        + bytes(4 * (DS_MAX - len(ids)))


def make_sup(body, entry_off, sup_id, *, version=1, block_size=None, min_svc=1,
             flags=0, dma=(0, 0), name=None):
    """A v4 sup file: the 48-byte header, then `body`, then the display name.
    `entry_off` is from the first byte of the FILE, bit 0 = Thumb."""
    tail = b''
    name_off = 0
    if name:
        name_off = SL4_HEADER_LEN + len(body) + (-len(body) % 4)
        tail = b'\0' * (-len(body) % 4) + name.encode() + b'\0'
    file_len = SL4_HEADER_LEN + len(body) + len(tail)
    file_len += -file_len % 4
    block = max(block_size or 0, file_len)
    hdr = struct.pack('<12I', SL4_MAGIC, SL4_HEADER_LEN, file_len, block, entry_off,
                      _id(sup_id), version, min_svc, flags, dma[0], dma[1], name_off)
    return (hdr + body + tail).ljust(file_len, b'\0')


def c_sup(src, sup_id, *, name, flags=SL_F_CACHED_OK, version=1, bss=0, extra=(),
          min_svc=SL4_SVC_VERSION):
    """A sup written in C (-fropi, one .text, entry `sup_entry`)."""
    with tempfile.TemporaryDirectory(prefix='slv4sup-') as t:
        text = compile_unit(pathlib.Path(t), src, 'sup_entry', extra)
    body = text.code + b'\0' * (-len(text.code) % 4)
    entry = SL4_HEADER_LEN + text.functions['sup_entry']        # Thumb bit kept
    blob = make_sup(body, entry, sup_id, version=version, flags=flags, name=name,
                    min_svc=min_svc, block_size=None)
    blk = len(blob) + bss
    return blob[:12] + struct.pack('<I', blk + (-blk % 4)) + blob[16:]


CFG_SIZE = 640                                # test_sup4.c: struct cfg, then code


def test_sup(cfg_bytes, sup_id, *, flags=SL_F_CACHED_OK, name=None, dma=(0, 0), bss=0x100):
    """test_sup4.c with its config in front of the code."""
    if len(cfg_bytes) > CFG_SIZE:
        raise BuildError('cfg too large')
    with tempfile.TemporaryDirectory(prefix='slv4t-') as t:
        text = compile_unit(pathlib.Path(t), HERE / 'test_sup4.c', 'sup_entry')
    body = cfg_bytes.ljust(CFG_SIZE, b'\0') + text.code
    entry = SL4_HEADER_LEN + CFG_SIZE + text.functions['sup_entry']
    blob = make_sup(body, entry, sup_id, flags=flags, name=name, dma=dma, min_svc=SL4_SVC_VERSION)
    blk = len(blob) + bss
    return blob[:12] + struct.pack('<I', blk) + blob[16:]


def supmgr_sup():
    return c_sup(HERE / 'supmgr.c', SMGR_ID, name='SupManager', bss=0x1000)   # 32 rows x 64 (labels)


# patch_sup.S's entry, the first words of every v3 patch sup (from_v3 checks it)
PATCH_SUP_ENTRY = bytes.fromhex('f0472de90040a0e10150a0e1')   # push {r4-r10,lr}; mov r4,r0; mov r5,r1


def from_v3(v3, *, name, flags=SL_F_CACHED_OK, sup_id=None, reviewed=False):
    """A v3 patch sup (fp_usb_shell/v3/patch_sup.S, with or without an inner
    entry) under the v4 header.  The body moves by SL4_HEADER_LEN -
    SL_HEADER_LEN and nothing in it changes: patch_sup and its inner entries
    are position-independent (adr only) and never read their header, and the
    block -- BSS included -- grows by the same 16 bytes, so every offset from
    the code to its state is unchanged.  Only patch_sup bodies are accepted:
    another v3 sup may read its own header (CFG at +32) and needs a real port.
    `reviewed`: a non-patch_sup body read and found position-independent and
    header-blind (ports.py names which, and why)."""
    hdr = struct.unpack_from('<8I', v3)
    if hdr[0] != V3.SL_MAGIC or hdr[1] != V3.SL_HEADER_LEN or hdr[2] != len(v3):
        raise BuildError('not a v3 sup file')
    if hdr[4] & ~1 < V3.SL_HEADER_LEN:
        raise BuildError('entry inside the header')
    if not reviewed and (hdr[4] != V3.SL_HEADER_LEN or
                         v3[hdr[4]:hdr[4] + len(PATCH_SUP_ENTRY)] != PATCH_SUP_ENTRY):
        raise BuildError('not a patch_sup body: port it from its source')
    shift = SL4_HEADER_LEN - V3.SL_HEADER_LEN
    sid = sup_id or struct.pack('<I', hdr[5]).decode()
    return make_sup(v3[V3.SL_HEADER_LEN:], hdr[4] + shift, sid, version=hdr[6], flags=flags,
                    name=name, block_size=hdr[3] + shift)


def shell_sup(burst15=False):
    """The USB shell as a v4 sup: v3's patch_sup.S + worker.S, unchanged code,
    v4 header.  Not SL_F_CACHED_OK: the block only holds `spawn`, which moves
    the worker into its own allocation (worker.S WCODE_PTR) and runs it there;
    its TRB/EP82/EP83/MEM1 buffers are in the worker's pool (DMA, uncached).
    Cached execution for the worker itself is a worker change (README).
    `burst15`: the released shell's bMaxBurst 15 rows (tools/release_v3.py)."""
    import names_v4
    return from_v3(V3.shell_sup(burst15=burst15), name=names_v4.display('SHEL'), flags=0)


def boot_card(splash=False, instant=False, fast=False, markers=False, slim=False, pwroff_log=False,
              pwroff_file=False, ui=False):
    """(AutoRun, LOADER.BIN, info): v3's shared boot envelope around the v4 core.
    `ui`: the fpSup page (FPSUP_UI; data from ui_files()).
    Same switches as v3 boot_card: `splash` = the four-box image splash (UI\\0..4.BIN),
    `instant` = Fast Start 2 (power-switch restart reuses the RAM loader hook),
    `fast` = Fast Start 3 (bootstrap stored in camera settings, short cold AutoRun)."""
    anim = (['--four-box-bar', '--splash-dir', V3.UI_DIR, '--splash-hold-ms', '0']    # v4: no hold
            if splash else ['--no-four-box-bar'])
    flags = (['--loader-hook'] if instant else ['--loader-hook-off']) + (['--store-boot'] if fast else [])
    flags += ['--boot-markers', '--profile'] if markers else []
    # --slim: the smaller bootstrap (README "縮小引導程式"): the loader opens the
    # card directly, the Fast Start 2 entry travels in the BIN instead of being
    # spelled out, and the Fast Start 3 bootstrap is the compact one.
    flags += (['--slim-open'] + (['--store-slim'] if fast else []) +
              (['--lhook-in-file'] if instant else [])) if slim else []
    with tempfile.TemporaryDirectory(prefix='slv4boot-') as t:
        tmp = pathlib.Path(t)
        payload = tmp / 'core.bin'
        offset = 0
        tail_len = 8 + 4 * DS_MAX
        for attempt in range(2):
            core, info = loader_bin(file_offset=offset, markers=markers, pwroff_log=pwroff_log,
                                    pwroff_file=pwroff_file, ui=ui)
            tail = core[-tail_len:]
            payload.write_bytes(core[:-tail_len])
            cmd = [sys.executable, '-B', str(SHELL_DIR / 'build_autorun.py'), '--loader',
                   '--no-shell', *anim, *flags, '--bin-name', f'{SL_DIR}\\\\{SL_SELF}',
                   '--boot-bin', f'{payload}:16', '--out', str(tmp / 'AutoRun.txt')]
            p = subprocess.run(cmd, capture_output=True, text=True)
            if p.returncode:
                raise BuildError('boot envelope failed:\n' + p.stderr + p.stdout)
            blob = (tmp / f'{SL_DIR}\\\\{SL_SELF}').read_bytes()
            magic, count, entry, size = struct.unpack_from('<4sIII', blob)
            if magic != b'VBIN' or len(blob) != 16 + count * 8 + size:
                raise BuildError('invalid shared boot envelope')
            if attempt and entry != offset:
                raise BuildError('boot envelope moved')
            offset = entry
        blob += tail
        if len(blob) > 0xF000:
            raise BuildError('boot envelope exceeds the common loader read cap')
        return (tmp / 'AutoRun.txt').read_bytes(), blob, dict(info, bytes=len(blob), core_entry=offset,
                                                                 splash=splash, instant=instant, fast=fast, markers=markers,
                                                                 slim=slim, pwroff_log=pwroff_log,
                                                                 pwroff_file=pwroff_file, ui=ui)


def ui_files():
    """{name in \\fpSup\\UI: bytes}: the fpSup page and SupManager's page (uishare/tab/build_fp4.py)."""
    sys.path.insert(0, str(FPSUP / 'uishare' / 'tab'))
    import build_fp4
    return {UI_FILE: build_fp4.home_file()[0], 'SUPMGR.BIN': build_fp4.supmgr_file()[0]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=pathlib.Path, required=True)
    ap.add_argument('--splash', action='store_true', help='four-box image splash (writes UI\\0..4.BIN)')
    ap.add_argument('--instant', action='store_true', help='Fast Start 2: power-switch restart via the loader hook')
    ap.add_argument('--fast', action='store_true', help='Fast Start 3: bootstrap stored in camera settings')
    ap.add_argument('--card', action='store_true', help='= --splash --instant --fast (what the merge page ships)')
    ap.add_argument('--boot-markers', action='store_true', help='boot timing stamps (+ --profile); default off')
    ap.add_argument('--slim', action=argparse.BooleanOptionalAction, default=True,
                    help='smaller bootstrap: --slim-open, --lhook-in-file (with instant), --store-slim (with fast); '
                         'default on since 2026-10-20 (on-camera: cold boot 3.65 -> 3.51 s); --no-slim = the old bootstrap')
    ap.add_argument('--pwroff-log', action='store_true',
                    help='DEBUG: record what each power-off decided (README "關機紀錄器"); default off')
    ap.add_argument('--pwroff-file', action='store_true',
                    help='DEBUG: write each power-off\'s decision inputs to \\fpSup\\PWROFF.LOG (README "關機紀錄寫卡"); default off')
    ap.add_argument('--ui', action=argparse.BooleanOptionalAction, default=True,
                    help='the fpSup page and SupManager\'s page (DESIGN.md §14; writes UI\\FPSUP.BIN, UI\\SUPMGR.BIN); '
                         'default on since 2026-10-21; --no-ui = the core without pages')
    a = ap.parse_args()
    if a.card:
        a.splash = a.instant = a.fast = True
    ar, vbin, info = boot_card(splash=a.splash, instant=a.instant, fast=a.fast, markers=a.boot_markers,
                               slim=a.slim, pwroff_log=a.pwroff_log,
                               pwroff_file=a.pwroff_file, ui=a.ui)
    d = a.out / SL_DIR
    d.mkdir(parents=True, exist_ok=True)
    (d / SL_SELF).write_bytes(vbin)
    if a.splash:
        ui = d / 'UI'
        ui.mkdir(exist_ok=True)
        for i, pixels in enumerate(V3.splash_frames()):
            (ui / f'{i}.BIN').write_bytes(pixels)
    if a.ui:
        (d / UI_DIR).mkdir(exist_ok=True)
        for name, data in ui_files().items():
            (d / UI_DIR / name).write_bytes(data)
    (a.out / 'AutoRun.txt').write_bytes(ar)
    (d / 'SUPMGR.BIN').write_bytes(supmgr_sup())
    import names_v4
    (d / names_v4.file_name('SHEL')).write_bytes(shell_sup())
    import hashlib
    for f in sorted(p for p in d.rglob('*') if p.is_file()):
        print(f'{str(f.relative_to(d)):24s} {f.stat().st_size:7d}  {hashlib.sha256(f.read_bytes()).hexdigest()[:16]}')
    print(info)


if __name__ == '__main__':
    main()
