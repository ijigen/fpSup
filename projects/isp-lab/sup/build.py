#!/usr/bin/env python3
"""ISPL -- the ISP Lab sup: IMXL's DRAM sink (projects/imx410-lab/sup, sha256s in
UPSTREAM.sha256) plus a keep policy, a block log and a control task that starts
and stops the take itself.  Loader v4 file.

    python3 -B build.py [--out DIR] -> build/ISPL.BIN, build/build.json (or DIR/)

IMXL's description follows.

Built like rec-core/writer/build.py (v3 patch_sup + the wr_card.S inner, the C
as one -fropi unit), then re-headed for loader v4 the way build_v4.shell_sup()
does it.  bq.c/bq.h are rec-core's, unchanged; ix_wr.* / ix_card.* are forks.

[v4 header][patch_sup: claim C063F140 + C063F220 + C03A549C][ix_card.S inner][C text][name]
                                                             block: [state wr_t]
"""
import hashlib, json, pathlib, re, shutil, struct, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WRITER = ROOT / 'projects' / 'rec-core' / 'writer'
SHELL = ROOT / 'fpSup' / 'fp_usb_shell'
sys.path[:0] = [str(SHELL.parent / 'loader-v4'), str(SHELL / 'v3'), str(SHELL), str(ROOT / 'research/ui/tools/arm_text')]
import build_v3 as B                         # noqa: E402  (read-only use)
import build_v4 as B4                        # noqa: E402
from armasm import assemble, symbols         # noqa: E402
import elf_text                              # noqa: E402

SUP_ID, VERSION, NAME = 'ISPL', 1, 'ISP Lab'
OUT = HERE / 'build' / 'ISPL.BIN'
# The control-only build (10-23 route, RESEARCH_PLAN §7): the control task alone -- no writer hook,
# no writer task, no claim; stock writes the card.  A separate file and id so both never meet.
CTL_ID, CTL_NAME = 'ISPC', 'ISP Lab ctl'
CTL_OUT = HERE / 'build' / 'ISPC.BIN'
SL_EXCL = 2
SITES = {0xC063F140: '2de9f04584b00446', 0xC063F220: '2de9f04107460d46',
         0xC03A549C: '0d30dbe5000053e3'}
ENTRIES = {'OFF_INIT': 'wr_card_init', 'OFF_SEND': 'wr_send', 'OFF_INSTALLED': 'wr_installed',
           'OFF_COOKIE': 'wr_cb_cookie', 'OFF_ACQ': 'wr_cb_acquire', 'OFF_ADD': 'wr_cb_add',
           'OFF_CKPT': 'wr_cb_ckpt', 'OFF_RB': 'wr_cb_rollback', 'OFF_REL': 'wr_cb_release',
           'OFF_TASK': 'wr_task', 'OFF_START': 'wr_take_start', 'OFF_LATE': 'wr_late_frame',
           'OFF_SERVICE': 'wr_service',   # test_card.py runs the writer through wr_service
           'OFF_CTL': 'ix_ctl_task', 'OFF_STEP': 'ix_ctl_step',
           'OFF_PUSH': 'ix_push', 'OFF_PXREL': 'ix_push_release', 'OFF_CDNG': 'ix_cdng_run'}   # the push engine, called directly by tests   # ... and the control task by step
CFLAGS = ['--target=armv7a-none-eabi', '-mcpu=cortex-a9', '-mthumb', '-mfloat-abi=soft',
          '-mfpu=none', '-mstackrealign', '-ffreestanding', '-fno-builtin', '-nostdlib',
          '-fno-jump-tables', '-fropi', '-fno-addrsig', '-O2', '-std=c11', '-Wall', '-Wextra',
          '-Werror', '-Wno-unused-function']
API = re.compile(r'^((?:int|void|uint32_t|bq_block)\s*\*?\s*((?:bq|wr|ix)_\w+)\s*\()', re.M)
SOURCES = [(WRITER, 'bq.h'), (WRITER, 'bq.c'), (HERE, 'ix_wr.h'), (HERE, 'ix_push.c'), (HERE, 'ix_cdng.c'), (HERE, 'ix_wr.c'), (HERE, 'ix_card.c')]


class BuildError(RuntimeError):
    pass


def unity(tree):
    for d, f in SOURCES:
        text = (d / f).read_text()
        text = API.sub(lambda m: ('static __attribute__((used)) ' if m.group(2) in ENTRIES.values()
                                  else 'static ') + m.group(1), text)
        (tree / f).write_text(text)
    u = tree / 'unity.c'
    u.write_text('#include "bq.c"\n#include "ix_push.c"\n#include "ix_cdng.c"\n#include "ix_wr.c"\n#include "ix_card.c"\n')
    return u


def compile_c(tree, src, defines=()):
    obj = tree / (src.stem + '.o')
    r = subprocess.run(['clang', *CFLAGS, *[f'-D{d}' for d in defines], '-I', str(tree), '-c', str(src), '-o', str(obj)],
                       capture_output=True, text=True)
    if r.returncode:
        raise BuildError('compile failed:\n' + r.stderr)
    return obj


def layout(tree):
    """sizeof(wr_t), offsetof(wr_t, cap) (the host reads the sink there), sizeof(ix_cap)."""
    probe = tree / 'probe.c'
    probe.write_text('#include <stddef.h>\n#include "ix_wr.h"\n'
                     'char ix_probe_size[sizeof(wr_t)];\nchar ix_probe_cap[offsetof(wr_t, cap)];\n'
                     'char ix_probe_capsz[sizeof(ix_cap)];\n')
    d = compile_c(tree, probe).read_bytes()
    shoff, = struct.unpack_from('<I', d, 0x20)
    _, shnum, _ = struct.unpack_from('<HHH', d, 0x2E)
    secs = [struct.unpack_from('<10I', d, shoff + 40 * i) for i in range(shnum)]
    sym = next(s for s in secs if s[1] == 2)
    strs = secs[sym[6]]
    got = {}
    for i in range(sym[5] // 16):
        n, _v, size, *_ = struct.unpack_from('<IIIBBH', d, sym[4] + 16 * i)
        got[d[strs[4] + n:d.index(b'\0', strs[4] + n)]] = size
    try:
        return got[b'ix_probe_size'], got[b'ix_probe_cap'], got[b'ix_probe_capsz']
    except KeyError:
        raise BuildError('layout probe missing')


def check_sites():
    img = B.IMAGE.read_bytes()
    for a, hexs in SITES.items():
        if img[a - 0xC0000000:a - 0xC0000000 + 8].hex() != hexs:
            raise BuildError(f'0x{a:08X} is not the stock prologue in the reference image')


def v4_file(v3, block_size, sup_id=SUP_ID, name=NAME):
    """A v3 patch_sup file as a v4 sup (build_v4.shell_sup's conversion), run cached."""
    hdr = struct.unpack_from('<8I', v3)
    body = v3[B.SL_HEADER_LEN:]
    shift = B4.SL4_HEADER_LEN - B.SL_HEADER_LEN
    return B4.make_sup(body, hdr[4] + shift, sup_id, version=hdr[6], flags=B4.SL_F_CACHED_OK,
                       min_svc=B4.SL4_SVC_VERSION, name=name, block_size=block_size + shift), shift


def build(defines=(), ctl_only=False):
    """defines: test mutants only (test_card.py); a release build passes none."""
    sup_id, name = (CTL_ID, CTL_NAME) if ctl_only else (SUP_ID, NAME)
    if ctl_only:
        defines = tuple(defines) + ('ISPL_CTL_ONLY',)
    check_sites()
    with tempfile.TemporaryDirectory() as tmp:
        tree = pathlib.Path(tmp)
        text = elf_text.load_text(compile_c(tree, unity(tree), defines))
        state_bytes, cap_off, cap_bytes = layout(tree)
    missing = [f for f in ENTRIES.values() if f not in text.functions]
    if missing:
        raise BuildError(f'entries missing: {missing}')
    if any(not text.functions[f] & 1 for f in ENTRIES.values()):
        raise BuildError('an entry is not Thumb')
    src = HERE / 'ix_card.S'
    defs = lambda rel: ([f'STATE_REL=0x{rel:X}'] + [f'{k}=0x{text.functions[v]:X}' for k, v in ENTRIES.items()]
                        + list(defines))
    c_base = symbols(src, defs(0))['c_base']
    inner = lambda rel: (lambda code: code[:c_base] + text.code)(assemble(src, defs(rel)))
    rows = [] if ctl_only else [(a, bytes(8), SL_EXCL, 'claim') for a in SITES]
    probe, shift = v4_file(B.patch_sup(sup_id, rows, inner(0), inner_entry=0, version=VERSION), 0, sup_id, name)
    file_len = len(probe)
    inner_at = probe.index(inner(0)[:64])          # the inner blob ends the body
    state_at = (file_len + 63) & ~63
    block = state_at + state_bytes
    v3 = B.patch_sup(sup_id, rows, inner(state_at - inner_at), inner_entry=0, version=VERSION,
                     block_size=block - shift)
    sup, _ = v4_file(v3, block - shift, sup_id, name)
    if len(sup) != file_len or sup.index(inner(state_at - inner_at)[:64]) != inner_at:
        raise BuildError('layout moved between passes')
    if struct.unpack_from('<I', sup, 12)[0] != block:
        raise BuildError('block size')
    info = {'file_len': file_len, 'block_size': block, 'inner_at': inner_at, 'c_base': c_base,
            'c_text': len(text.code), 'state_at': state_at, 'state_bytes': state_bytes,
            'cap_off': cap_off, 'cap_bytes': cap_bytes, 'entries': {v: text.functions[v] for v in ENTRIES.values()},
            'sha256': hashlib.sha256(sup).hexdigest()}
    return sup, info


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=pathlib.Path)
    ap.add_argument('--ctl-only', action='store_true', help='ISPC.BIN: the control task alone')
    a = ap.parse_args()
    default = CTL_OUT if a.ctl_only else OUT
    out = a.out / default.name if a.out else default
    sup, info = build(ctl_only=a.ctl_only)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(sup)
    (out.parent / ('build-ctl.json' if a.ctl_only else 'build.json')).write_text(json.dumps(info, indent=1))
    print(f'{out.name}: {info["file_len"]} B, block {info["block_size"]} B, C {info["c_text"]} B, '
          f'state {info["state_bytes"]} B (cap at +{info["cap_off"]}), sha256 {info["sha256"][:16]}')


if __name__ == '__main__':
    main()
