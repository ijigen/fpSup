#!/usr/bin/env python3
"""Build the fpLossless TEST card: direct compression + USB shell + Fast Start 3.

    python3 -B lossless/build_card.py --out /absolute/new/directory

Another sup can ride along: --add-sup lcdflip (fpSup/lcdflip/sup.py: its
launcher section after lossless's entry, its menu block after the FPLM), and
--no-lossless leaves lossless out. Without them the output is unchanged.

Writes AutoRun.txt and fpSup.BIN into a NEW directory (refuses a non-empty
one), plus BUILD_NOTES.md and SHA256SUMS. It never writes a card.

WHAT IS IN IT (manifest.json requested_test_build): the current USB shell from
fp_usb_shell, Fast Start 3 (--store-boot --loader-hook --four-box-bar, one
packaging, SUP_BUILD_RULES §5), and the lossless launcher as a run-in-place
section after the shell's worker. No menu, no OpenGate, no gyro.

HOW THE C GETS ON THE CAMERA WITHOUT A LINKER. Every module is compiled as ONE
translation unit with every public function made internal, so the compiler
resolves every call itself and the object carries no relocation at all; the
repository's strict extractor (research/ui/tools/arm_text/elf_text.py) then
takes .text and refuses anything it would have had to patch. -fropi makes
the few function addresses the code stores PC-relative, -fno-jump-tables keeps
switch tables out of .rodata. The source files are not edited: the build
rewrites copies.

WHAT THE LAUNCHER DOES is card.S: allocate its own USER block, copy,
publish, init, then arm its declared hook sites all-or-nothing, with veneers taken
from the cave's bump allocator. Each site is also declared here as a 4-byte
section holding the firmware's own word, so stage2 journals it and the
loader's power-off callback writes it back (SUP_BUILD_RULES §4).
"""
import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
FPSUP = HERE.parent
ROOT = FPSUP.parent
SHELL = FPSUP / 'fp_usb_shell'
NATIVE = HERE / "native"
UISHARE = FPSUP / "uishare"                 # the shared UI convention (ui_pool)
IMAGE = ROOT / 'out/seg0_c0000000.bin'
IMAGE_SHA256 = 'aaa5208a028d9c4aebb9cc8614add723d456e96b2a95914f433079954320e622'
sys.path.insert(0, str(SHELL))
sys.path.insert(0, str(ROOT / 'research/ui/tools/arm_text'))

BANNER = 'fpLossless TEST'          # the bar holds 19 characters
MENU_AT = 0xF000                    # native/menu_page.h FPL_MENU_AT_MIN = loader MAXLEN
MENU_STEP, MENU_MAX = 0x1000, 0x1F000   # FPL_MENU_AT_STEP / _MAX (build_autorun --read-cap)


def menu_at_for(binary):
    """Where the row's data goes: native/menu_page.c menu_at() from the VBIN
    header -- MENU_AT if the VBIN fits, else its end rounded up to 4 KiB, the
    read cap fpSup-Merge gives such a card too (template.html capFor)."""
    _, count, _, body = struct.unpack_from('<4sIII', binary)
    used = 16 + 8 * count + body
    at = MENU_AT if used <= MENU_AT else -(-used // MENU_STEP) * MENU_STEP
    if at > MENU_MAX:
        raise BuildError(f'the VBIN is {used} bytes: past the loader read ceiling 0x{MENU_MAX:X}')
    return at
RELEASES = FPSUP / 'releases'
BLOCK_BYTES = 0x80000               # the launcher's own USER block: code and
                                    # state (most of it the 128 flush promises),
                                    # then the menu row's page and string pool,
                                    # which the UI borrows for the whole boot
SITES = {                           # site: (stock word, what it is)
    0xC03A33C8: (0xEBFFFC1A, 'REC preparation: bl C03A2438'),
    0xC038BFF0: (0xE12FFF33, 'creator enqueue: blx r3'),
    0xC0398D88: (0xE92D49F0, 'stop check entry: push {r4-r8, fp, lr}'),
    0xC03A5490: (0xEB0BD652, 'final flush: bl C069ADE0'),
    0xC05C0EA4: (0xE595201C, 'player frame read: ldr r2, [r5, #0x1c]'),
    0xC05BDDAC: (0xE58430A0, 'player clip size: str r3, [r4, #0xa0]'),
    0xC05C2E90: (0xE92D4070, 'player pool free: push {r4, r5, r6, lr}'),
    0xC05C2D10: (0xE92D44F0, 'player pool make: push {r4, r5, r6, r7, sl, lr}'),
    0xC038BD08: (0xE594300C, 'CinemaDNG event observation: ldr r3, [r4, #0xc]'),
    0xC037DEF8: (0xEB000042, 'native FIFO discard observation: bl C037E008'),
    # the row's private strings hang on these (uishare/NESTED_HOOKS.md);
    # other sups declare the same stock words, and identical sections fold
    0xC05E5B58: (0x3FFFF1B1, 'string resolve (nested string layers)'),
    0xC05E61C8: (0x428A6942, 'string owns (nested string layers)'),
    0xC05E61E0: (0x69406902, 'string remain (nested string layers)'),
}
SHARED_SITES = {0xC05E5B58, 0xC05E61C8, 0xC05E61E0}   # declared by others too
# The fields a host reads after a test take, by their path in struct fpl_card.
# Their offsets are taken from the ARM compile itself, never computed on the
# host, whose pointers are a different size.
FIELDS = ['magic', 'hold_live', 'rec_events', 'rec_admitted', 'rec_raw',
          'rec_firmware_refused', 'rec_hold_refused', 'hold_init_failed', 'ring_busy',
          'stops', 'finishes', 'finish_busy', 'last_finish', 'stale_promises',
          'rec.workspace.last_result', 'rec.workspace.native_result',
          'rec.facts.seen.width', 'rec.facts.seen.height', 'rec.facts.seen.bits',
          'rec.facts.seen.raster', 'rec_menu_off', 'menu.result', 'menu.registered',
          'spare_bytes', 'spare_failed', 'spares_freed',
          'task_id', 'lane_b_failed', 'lane_stop_result',
          'hold.magic', 'hold.lane', 'hold.arrivals', 'hold.held', 'hold.passed',
          'hold.compressed', 'hold.refused', 'hold.no_benefit', 'hold.not_eligible',
          'hold.faults', 'hold.swapped', 'hold.swap_declined', 'hold.swap_undone',
          'hold.dma_failed', 'hold.lanes_full', 'hold.refused_by',
          'hold_b.magic', 'hold_b.lane', 'hold_b.held', 'hold_b.compressed',
          'hold_b.refused', 'hold_b.no_benefit', 'hold_b.faults', 'hold_b.swapped',
          'hold_b.dma_failed',
          'flush.applied', 'flush.tag_failed', 'flush.length_mismatch',
          'hold.stalls', 'hold_b.stalls', 'hold.job_last_us', 'hold.job_max_us',
          'hold.stall_limit_us', 'hold_b.job_last_us', 'hold_b.job_max_us', 'hold.job_sum_us', 'hold.job_count', 'hold_b.job_sum_us', 'hold_b.job_count', 'hold.submit_sum_us', 'hold.finish_sum_us', 'hold.poll_sum', 'hold.gap_sum_us', 'hold.cycle_sum_us', 'hold.cycle_count', 'hold_b.submit_sum_us', 'hold_b.finish_sum_us', 'hold_b.poll_sum', 'hold_b.gap_sum_us', 'hold_b.cycle_sum_us', 'hold_b.cycle_count', 'tile_force', 'hold.job.tile_width', 'hold.job.tile_height', 'hold.job.tiles', 'hold.job.stall_regs', 'hold_b.job.stall_regs',
          'play.seen', 'play.stock', 'play.decoded', 'play.refused_by', 'play.last_us',
          'play.max_us', 'play.last_buf', 'play.last_cap', 'play.last_got',
          'play.clips', 'play.clips_ours', 'play.clip_size_was', 'play.clip_size_set',
          'play.clip_failed', 'play.scratch_bytes', 'play.scratch_failed',
          'play.scratch_freed', 'play.scratch_want', 'play.clips_first_stock', 'take_frames']
FIELDS += ['settings_on', 'settings_ok', 'saves', 'save_failed', 'save_last', 'trace_n', 'trace', 'elog_n', 'elog']          # card.c FPL_TRACE: per-arrival records
FIELDS += ['engine_release', 'hold.job.reused', 'hold_b.job.reused', 'tag_tiles', 'tag_bytes', 'hold.require_head', 'observer_slot', 'observer_full', 'observer_calls', 'tag_mode0',
           'tag_added', 'tag_add_result', 'tag_add_failed', 'tag_prepared', 'tag_prepare_failed',
           'tag_prepare_result', 'tag_head',
           'tag_want', 'tag_pending', 'tag_live', 'tag_index']   # header_tag.h
FIELDS += ['record_diag.' + name for name in (
    'event_calls', 'raw_errors', 'capture_limits', 'completion_errors', 'lookup_missing',
    'last_event', 'last_result', 'last_slot', 'last_generation', 'last_state',
    'last_handle', 'last_missing', 'discard_calls', 'discard_count', 'discard_missing',
    'discard_raw', 'discard_completion', 'discard_teardown', 'discard_other',
    'drop_next', 'drop_used', 'drop_overwritten', 'drops',
    'writer_calls', 'writer_zero', 'writer_nonzero', 'writer_low', 'writer_high')]
UNITS = ['control.c', 'frame_pipeline.c', 'native/workspace_layout.c', 'uishare/ui_pool.c',
         'uishare/ui_apply.c',
         'native/menu_page.c',
         'native/raw_workspace.c', 'native/rec_workspace.c', 'native/producer_facts.c',
         'native/rec_hook.c', 'native/codec_job.c', 'native/header_tag.c',
         'native/frame_hold.c', 'native/flush_site.c', 'native/play_decode.c',
         'native/record_diag.c',
         'native/card.c']
ENTRIES = {'OFF_INIT': 'fpl_card_init', 'OFF_REC': 'fpl_card_rec',
           'OFF_ARRIVE': 'fpl_card_arrive', 'OFF_STOP': 'fpl_card_stop',
           'OFF_FLUSH': 'fpl_card_flush', 'OFF_TASK': 'fpl_card_task',
           'OFF_PLAY': 'fpl_card_play', 'OFF_CLIP': 'fpl_card_clip',
           'OFF_END': 'fpl_card_play_end', 'OFF_POOL': 'fpl_card_play_pool',
           'OFF_WRITTEN': 'fpl_card_written', 'OFF_EVENT': 'fpl_card_event',
           'OFF_DISCARD': 'fpl_card_discard',
           'OFF_OBSERVE': 'fpl_card_observe', 'OFF_OBSERVER': 'fpl_card_observer'}
CFLAGS = ['--target=armv7a-none-eabi', '-mcpu=cortex-a9', '-mthumb', '-mfloat-abi=soft',
          '-mfpu=none', '-mstackrealign', '-ffreestanding', '-fno-builtin', '-nostdlib', '-fno-jump-tables',
          '-fropi', '-fno-addrsig', '-O2', '-std=c11', '-Wall', '-Wextra', '-Werror',
          '-Wno-unused-function']
PUBLIC = re.compile(r'^(?!typedef\b|static\b|extern\b|#|enum\b|union\b|struct\s+\w+\s*\{)'
                    r'((?:USED\s+)?(?:const\s+)?(?:struct\s+\w+|u?int\w*_t|void|uintptr_t)'
                    r'\s*\**\s*(?:fpl|uis|uia)_\w+\s*\()', re.M)


class BuildError(RuntimeError):
    pass


def unity(tree: pathlib.Path) -> pathlib.Path:
    """Copies with every public fpl_ function made internal, and one unit
    that includes them all, each module's private names prefixed."""
    for src in list(HERE.glob('*.[ch]')) + list(NATIVE.glob('*.[ch]')) + list(UISHARE.glob('*.[ch]')):
        rel = src.relative_to(HERE.parent) if src.parent == UISHARE else src.relative_to(HERE)
        (tree / rel).parent.mkdir(parents=True, exist_ok=True)
        (tree / rel).write_text(PUBLIC.sub(r'static \1', src.read_text()))
    lines = ['/* generated by build_card.py */']
    for unit in UNITS:
        path = tree / unit
        text = path.read_text()
        private = sorted({s for s in re.findall(
            r'^(?:static|INLINE)\s[^(=;]*?\b(\w+)\s*\(', text, re.M)
            if not s.startswith(('fpl_', 'uis_', 'uia_'))})
        macros = sorted(set(re.findall(r'^\s*#\s*define\s+(\w+)', text, re.M)))
        lines += [f'#define {s} {path.stem}__{s}' for s in private]
        lines.append(f'#include "{path}"')
        lines += [f'#undef {s}' for s in private] + [f'#undef {m}' for m in macros]
    out = tree / 'unity.c'
    out.write_text('\n'.join(lines) + '\n')
    return out


def compile_c(tree, unit, extra=''):
    source = unit
    if extra:
        source = tree / 'probe.c'
        source.write_text(unit.read_text() + extra)
    obj = tree / (source.stem + '.o')
    clang = shutil.which('clang') or 'clang'
    r = subprocess.run([clang] + CFLAGS + ['-c', '-I', str(tree), '-I', str(tree / 'native'),
                                           '-I', str(tree / 'uishare'),
                        str(source), '-o', str(obj)], capture_output=True, text=True)
    if r.returncode:
        raise BuildError('compile failed:\n' + r.stderr)
    return obj


def symbol_size(obj: pathlib.Path, name: str) -> int:
    d = obj.read_bytes()
    shoff, = struct.unpack_from('<I', d, 0x20)
    shentsize, shnum, _ = struct.unpack_from('<HHH', d, 0x2E)
    secs = [struct.unpack_from('<IIIIIIIIII', d, shoff + i * shentsize) for i in range(shnum)]
    symtab = next(s for s in secs if s[1] == 2)
    strtab = secs[symtab[6]]
    for i in range(symtab[5] // 16):
        n, _v, size, _info, _o, _s = struct.unpack_from('<IIIBBH', d, symtab[4] + 16 * i)
        if d[strtab[4] + n:d.index(b'\0', strtab[4] + n)].decode() == name:
            return size
    raise BuildError(f'{name} not in {obj.name}')


def check_sites():
    image = IMAGE.read_bytes()
    if hashlib.sha256(image).hexdigest() != IMAGE_SHA256:
        raise BuildError('firmware image hash differs; hook sites unverified')
    for site, (stock, what) in SITES.items():
        word, = struct.unpack_from('<I', image, site - 0xC0000000)
        if word != stock:
            raise BuildError(f'0x{site:08X} ({what}) reads 0x{word:08X} in the image, '
                             f'not 0x{stock:08X}')


def build_blob(tmp: pathlib.Path):
    from armasm import assemble, symbols
    import elf_text
    tree = tmp / 'tree'
    tree.mkdir()
    unit = unity(tree)
    text = elf_text.load_text(compile_c(tree, unit))
    missing = [f for f in ENTRIES.values() if f not in text.functions]
    if missing:
        raise BuildError(f'entries missing from the text: {missing}')
    for name in ENTRIES.values():
        if not text.functions[name] & 1:
            raise BuildError(f'{name} is not Thumb')
    probe = '\nchar fpl_card_size_probe[sizeof(struct fpl_card)];\n' + ''.join(
        f'char fpl_off_{i}[__builtin_offsetof(struct fpl_card, {f}) + 1];\n'
        for i, f in enumerate(FIELDS))
    probed = compile_c(tree, unit, probe)
    state = symbol_size(probed, 'fpl_card_size_probe')
    layout = {f: symbol_size(probed, f'fpl_off_{i}') - 1 for i, f in enumerate(FIELDS)}
    card = NATIVE / 'card.S'
    probe = [f'BLOB_LEN=0x4', f'BLOCK_BYTES=0x{BLOCK_BYTES:X}', 'STATE_OFF=0x4'] + \
            [f'{k}=0x1' for k in ENTRIES]
    c_base = symbols(card, probe)['c_base']
    blob_len = c_base + len(text.code)
    blob_len += -blob_len % 8
    state_off = (blob_len + 63) & ~63
    if state_off + state > BLOCK_BYTES:
        raise BuildError(f'blob {blob_len} + state {state} exceed the {BLOCK_BYTES}-byte block')
    defines = [f'BLOB_LEN=0x{blob_len:X}', f'BLOCK_BYTES=0x{BLOCK_BYTES:X}',
               f'STATE_OFF=0x{state_off:X}'] + \
              [f'{k}=0x{text.functions[v]:X}' for k, v in ENTRIES.items()]
    launcher = assemble(card, defines)
    if symbols(card, defines)['c_base'] != c_base or len(launcher) < c_base:
        raise BuildError('card.S moved between passes')
    blob = launcher[:c_base] + text.code
    blob += b'\0' * (blob_len - len(blob))
    return blob, {'c_base': c_base, 'c_text': len(text.code), 'blob_len': blob_len,
                  'state_off': state_off, 'state_bytes': state, 'block_bytes': BLOCK_BYTES,
                  'entries': {v: text.functions[v] for v in ENTRIES.values()},
                  'defines': defines, 'layout': layout}


def og_sections(tmp, target='og3k'):
    """OpenGate (og3k or og2k) as its own release builder makes it: every
    section with a destination (stage2, destination 0, is the shared one this
    build already has) and its entry. Nothing here knows what the sections do.
    The builder reads OG_TARGET when it is imported, so it is set first."""
    os.environ['OG_TARGET'] = target
    og = ROOT / 'projects/open-gate/build'
    sys.path.insert(0, str(og))
    import build_og3k_ui_candidate as og3k
    if og3k.PLAN_TARGET['label'].lower() != target:
        raise BuildError(f'OpenGate builder made {og3k.PLAN_TARGET["label"]}, not {target}')
    og3k.build(out=tmp / target, release=True)
    blob = (tmp / target / 'fpSup.BIN').read_bytes()
    magic, count, entry, _ = struct.unpack_from('<4sIII', blob)
    if magic != b'VBIN' or entry < 0x40000000:
        raise BuildError('OpenGate BIN is not a VBIN with an absolute entry')
    args, off = [], 16 + 8 * count
    for i in range(count):
        dst, ln = struct.unpack_from('<II', blob, 16 + 8 * i)
        if dst in SHARED_SITES and blob[off:off + ln] == struct.pack('<I', SITES[dst][0]):
            pass                                        # this card declares it already
        elif dst:
            if dst < 0x40000000:
                raise BuildError('OpenGate carries a pool-offset section; not supported here')
            f = tmp / f'{target}_{i:03d}_{dst:08x}.bin'
            f.write_bytes(blob[off:off + ln])
            args += ['--also-bin', f'0x{dst:08X}:{f}']
        off += ln + (-ln % 4)
    return args + ['--vshl-entry', f'0x{entry:08X}']


def raw_view_sections(tmp, release):
    """fpSup-RAW-View as released: its no-shell card's fixed sections and its
    launcher, byte for byte (the tested bytes, not a rebuild). The first
    section is that card's stage2 -- this build has its own. The launcher's
    entry is called after OpenGate's, the order the card composer uses: its
    stock-word guards then see whatever the others installed."""
    blob = (release / 'fpSup.BIN').read_bytes()
    manifest = (release / 'MANIFEST.txt').read_text()
    digest = hashlib.sha256(blob).hexdigest()
    if f'fpSup.BIN' not in manifest or digest not in manifest:
        raise BuildError(f'{release.name}/fpSup.BIN is not the one its MANIFEST names')
    magic, count, entry, _ = struct.unpack_from('<4sIII', blob)
    if magic != b'VBIN':
        raise BuildError('RAW-View BIN is not a VBIN')
    args, off, launcher, sites = [], 16 + 8 * count, None, []
    for i in range(count):
        dst, ln = struct.unpack_from('<II', blob, 16 + 8 * i)
        part = blob[off:off + ln]
        if dst == 0 and i == 0:
            pass                                        # its stage2
        elif dst == 0:
            if launcher is not None or off != entry:
                raise BuildError('RAW-View: expected one launcher, at the entry')
            launcher = tmp / 'rawview.bin'
            launcher.write_bytes(part)
        else:
            if dst < 0x40000000:
                raise BuildError('RAW-View carries a pool-offset section; not supported here')
            f = tmp / f'rawview_{i:03d}_{dst:08x}.bin'
            f.write_bytes(part)
            args += ['--also-bin', f'0x{dst:08X}:{f}']
            sites.append((dst, ln))
        off += ln + (-ln % 4)
    if launcher is None:
        raise BuildError('RAW-View: no launcher section')
    for site in SITES:
        if any(d <= site < d + n for d, n in sites):
            raise BuildError(f'RAW-View writes 0x{site:08X}, a lossless hook site')
    return args + ['--late-boot-bin', f'{launcher}:0'], {
        'release': release.name, 'fpSup.BIN': digest, 'sections': len(sites),
        'launcher_bytes': launcher.stat().st_size,
        'launcher_sha256': hashlib.sha256(launcher.read_bytes()).hexdigest()}


def added_sup(name):
    """Another sup on the same card: fpSup/<name>/sup.py, which provides
    build_blob(tmp) -> (blob, facts) for a --boot-bin section, menu_block()
    -> bytes appended to fpSup.BIN after lossless's FPLM, BANNER and
    sources(). Its entry follows lossless's in the loader's trampoline."""
    import importlib.util
    path = FPSUP / name / 'sup.py'
    spec = importlib.util.spec_from_file_location(f'fpsup_{name}_sup', path)
    if spec is None or not path.is_file():
        raise BuildError(f'no sup named {name} ({path})')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--out', type=pathlib.Path, required=True)
    ap.add_argument('--with-og3k', action='store_true', help='same as --og og3k')
    ap.add_argument('--og', choices=('og3k', 'og2k'),
                    help='also carry OpenGate (its release build from '
                         'projects/open-gate/build, current og3k_ui.S): every fixed '
                         'section and its entry, after the lossless launcher')
    ap.add_argument('--plain', action='store_true',
                    help='no Fast Start 3 (a single-product card: plain --loader)')
    ap.add_argument('--no-shell', action='store_true', help='leave the USB shell out')
    ap.add_argument('--banner', default=None)
    ap.add_argument('--add-sup', action='append', default=[], choices=('lcdflip',),
                    help='also carry another sup (fpSup/<name>/sup.py): its launcher '
                         'section and its menu block')
    ap.add_argument('--raw-view', nargs='?', const='fpsup-raw-view-v0.2.2test', default=None,
                    metavar='RELEASE',
                    help='also carry fpSup-RAW-View from fpSup/releases/RELEASE (default '
                         'v0.2.2test), called after OpenGate. A VBIN past 0xF000 raises the '
                         'loader read to its next 4 KiB and the menu block moves there')
    ap.add_argument('--no-lossless', action='store_true',
                    help='leave lossless out (a card of the added sups, OG, shell)')
    a = ap.parse_args()
    if a.no_lossless and not a.add_sup:
        raise SystemExit('--no-lossless needs at least one --add-sup')
    sups = [added_sup(n) for n in a.add_sup]
    if a.raw_view and sups:
        raise SystemExit('--raw-view with --add-sup: the added sups read at 0xF000')
    if a.banner is None:
        a.banner = sups[0].BANNER if a.no_lossless else BANNER
    if a.with_og3k:
        a.og = a.og or 'og3k'
    out = a.out.resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f'{out} is not empty: this never overwrites a build or a card')
    out.mkdir(parents=True, exist_ok=True)
    if not a.no_lossless:
        check_sites()
    added = {}
    with tempfile.TemporaryDirectory(prefix='fpl-card-') as t:
        tmp = pathlib.Path(t)
        cmd = [sys.executable, '-B', str(SHELL / 'build_autorun.py'), '--loader',
               '--no-ep-patches', '--banner', a.banner, '--out', str(out / 'AutoRun.txt')]
        facts = None
        if not a.no_lossless:
            blob, facts = build_blob(tmp)
            (tmp / 'lossless.bin').write_bytes(blob)
            cmd += ['--boot-bin', f'{tmp / "lossless.bin"}:0']
        for sup in sups:                    # their entries follow lossless's
            sblob, sfacts = sup.build_blob(tmp)
            (tmp / f'{sup.NAME}.bin').write_bytes(sblob)
            cmd += ['--boot-bin', f'{tmp / (sup.NAME + ".bin")}:0']
            added[sup.NAME] = (sblob, sfacts)
        if not a.plain:
            cmd += ['--store-boot', '--loader-hook', '--four-box-bar']     # Fast Start 3
        if a.no_shell:
            cmd += ['--no-shell']
        for site, (stock, _) in (sorted(SITES.items()) if not a.no_lossless else []):
            f = tmp / f'site_{site:08x}.bin'
            f.write_bytes(struct.pack('<I', stock))
            cmd += ['--also-bin', f'0x{site:08X}:{f}']
        if a.og:
            cmd += og_sections(tmp, a.og)
        raw_view = None
        if a.raw_view:
            rv_args, raw_view = raw_view_sections(tmp, RELEASES / a.raw_view)
            cmd += rv_args
        # The read cap follows the VBIN (menu_at_for): build at the ceiling to
        # learn the size, then again at the cap that size needs -- the BIN's
        # sections do not depend on it, only the loader's two words (and a
        # fast card's magic) do.
        menu_at = MENU_AT
        for cap in (MENU_MAX, None):
            if cap is None:
                if menu_at == MENU_AT:
                    run = cmd
                else:
                    run = cmd + ['--read-cap', f'0x{menu_at:X}']
            else:
                run = cmd + ['--read-cap', f'0x{cap:X}']
            r = subprocess.run(run, capture_output=True, text=True, cwd=SHELL)
            (out / 'build_autorun.log').write_text(r.stdout + r.stderr)
            if r.returncode:
                raise SystemExit('build_autorun failed; see build_autorun.log')
            if cap is not None:
                menu_at = menu_at_for((out / 'fpSup.BIN').read_bytes())
                if sups and menu_at != MENU_AT:
                    raise SystemExit('the added sups read their blocks at 0xF000; '
                                     'this VBIN does not fit it')
        if not a.no_lossless:
            (out / 'lossless.bin').write_bytes(blob)
        for name, (sblob, _) in added.items():
            (out / f'{name}.bin').write_bytes(sblob)
    # One file: the loader reads fpSup.BIN only up to its read cap, so the menu
    # row's page rides after that, where native/menu_page.c finds it from the
    # VBIN header (menu_at_for: 0xF000 unless the VBIN needs more). The
    # loader's part is padded to exactly that.
    # Blocks follow each other: lossless's FPLM first (its reader expects it
    # at 0xF000), then each added sup's, which skips the ones before it.
    menu = b''
    if not a.no_lossless:
        sys.path.insert(0, str(HERE / 'menu'))
        import build_fpui
        menu, menu_info, _ = build_fpui.build()          # FPUI: what the row adds to MainB2
        menu += b'\0' * (-len(menu) % 0x1000)        # putfile cannot shorten a file
    for sup in sups:
        menu += sup.menu_block()
    binary = (out / 'fpSup.BIN').read_bytes()
    if menu_at_for(binary) != menu_at:
        raise BuildError('the VBIN changed size between the two builds')
    binary = binary[:menu_at] if len(binary) > menu_at and not any(binary[menu_at:]) else binary
    if len(binary) > menu_at:
        raise BuildError(f'fpSup.BIN is {len(binary)} bytes: past the loader MAXLEN {menu_at}')
    (out / 'fpSup.BIN').write_bytes(binary + b'\0' * (menu_at - len(binary)) + menu)
    if facts:
        (out / 'layout.json').write_text(json.dumps({
            'record': 'cave block from the bump: +32 "FLPC", +36 card state, +40 resident '
                      'base, +44 blob length', 'state_bytes': facts['state_bytes'],
            'fields': facts['layout']}, indent=1) + '\n')
    produced = sorted(p for p in out.iterdir() if p.is_file() and p.name != 'SHA256SUMS')
    sources = [pathlib.Path(__file__)]
    if not a.no_lossless:
        sources += [(HERE.parent if u.startswith('uishare/') else HERE) / u for u in UNITS] + \
                   [NATIVE / 'card.S']
    for sup in sups:
        sources += list(sup.sources())
    sources = sorted(set(sources))
    sums = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in produced}
    (out / 'SHA256SUMS').write_text(''.join(f'{h}  {n}\n' for n, h in sums.items()))
    (out / 'build.json').write_text(json.dumps({
        'product': 'fpLossless card' if not a.no_lossless else 'card of ' + ', '.join(a.add_sup),
        'lossless': not a.no_lossless, 'added_sups': {n: f for n, (_, f) in added.items()},
        'banner': a.banner,
        'fast_start_2': not a.plain, 'usb_shell': not a.no_shell, 'opengate': a.og,
        'raw_view': raw_view, 'loader_read': f'0x{menu_at:X}',
        'command': ' '.join(sys.argv), 'blob': facts,
        'sites': {f'0x{s:08X}': {'stock': f'0x{w:08X}', 'what': d}
                  for s, (w, d) in SITES.items()} if not a.no_lossless else {},
        'outputs': sums,
        'sources': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sources},
        'firmware_image_sha256': IMAGE_SHA256,
        'written_to_card': False, 'camera_tested': False}, indent=1) + '\n')
    print(f'built into {out}')
    if facts:
        print(json.dumps({k: v for k, v in facts.items() if k not in ('defines', 'layout')},
                         indent=1))
    for name, (_, f) in added.items():
        print(name, json.dumps(f))


if __name__ == '__main__':
    main()
