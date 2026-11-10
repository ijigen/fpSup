#!/usr/bin/env python3
"""Build the SensorLab-IMX410 apply unit for the tests (no BIN, no card, no device I/O).

    python3 -B build_apply.py            # ARM flat image + host library into apply/build/, sizes printed

arm():  ap_unit.c (= core.c + ap.c, exactly what slqs.c gets with `#include "../apply/ap.c"` after its core.c)
        compiled with the sup's flags (loader-v4 build_v4.CFLAGS: Thumb, -fropi, no data section) and linked flat
        by link_flat() -- a copy of qs/build_slqs.py's (not imported: that file is being edited by another agent;
        source sha256 recorded in COPIED below).  Anything that needs a load-time relocation is refused.
host(): ap_calc.c + core.c as a host dylib (apc_build_host) for the field-by-field comparison with the Python.
"""
import hashlib, os, pathlib, shutil, struct, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path(os.environ.get('SL_ROOT', HERE.parents[2]))
CORE = ROOT / 'projects' / 'sensorlab-imx410' / 'core'
LDR = ROOT / 'fpSup' / 'loader-v4'
BUILD = HERE / 'build'
CFLAGS = ['--target=armv7a-none-eabi', '-mcpu=cortex-a9', '-mthumb', '-mfloat-abi=soft', '-mfpu=none',
          '-mstackrealign', '-ffreestanding', '-fno-builtin', '-nostdlib', '-fno-jump-tables', '-fropi',
          '-fno-addrsig', '-O2', '-std=c11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
          '-fno-unwind-tables', '-fno-asynchronous-unwind-tables']
COPIED = {'qs/build_slqs.py link_flat': '2026-10-29, see test_apply.SourceTests (sha256 of the function text)'}


class BuildError(RuntimeError):
    pass


R_THM_CALL, R_THM_JUMP24, R_THM_MOVW_PREL_NC, R_THM_MOVT_PREL = 10, 30, 49, 50


def _thm_imm16(hw1, hw2):
    return ((hw1 & 0xF) << 12) | (((hw1 >> 10) & 1) << 11) | (((hw2 >> 12) & 7) << 8) | (hw2 & 0xFF)


def _thm_set_imm16(hw1, hw2, v):
    hw1 = (hw1 & ~0x040F) | ((v >> 12) & 0xF) | (((v >> 11) & 1) << 10)
    hw2 = (hw2 & ~0x70FF) | (((v >> 8) & 7) << 12) | (v & 0xFF)
    return hw1, hw2


def _thm_branch_get(hw1, hw2):
    s = (hw1 >> 10) & 1
    j1, j2 = (hw2 >> 13) & 1, (hw2 >> 11) & 1
    i1, i2 = 1 ^ (j1 ^ s), 1 ^ (j2 ^ s)
    off = (s << 24) | (i1 << 23) | (i2 << 22) | ((hw1 & 0x3FF) << 12) | ((hw2 & 0x7FF) << 1)
    return off - (1 << 25) if s else off


def _thm_branch_set(hw1, hw2, off):
    if not -(1 << 24) <= off < (1 << 24) or off & 1:
        raise BuildError(f'branch out of range {off}')
    s = (off >> 24) & 1
    i1, i2 = (off >> 23) & 1, (off >> 22) & 1
    j1, j2 = 1 ^ i1 ^ s, 1 ^ i2 ^ s
    hw1 = (hw1 & 0xF800) | (s << 10) | ((off >> 12) & 0x3FF)
    hw2 = (hw2 & 0xD000) | (j1 << 13) | (j2 << 11) | ((off >> 1) & 0x7FF)
    return hw1, hw2


def link_flat(data):
    """ELF32 ARM relocatable -> (flat bytes, {function: offset}): .text then the read-only data, Thumb calls and
    -fropi MOVW / MOVT resolved; a writable section, a data relocation or an undefined symbol is refused."""
    E = struct.unpack_from
    if data[:4] != b'\x7fELF' or data[4:6] != b'\x01\x01' or E('<H', data, 18)[0] != 40:
        raise BuildError('not an ARM ELF32')
    shoff, = E('<I', data, 32)
    shnum, shstrndx = E('<HH', data, 48)
    sh = [E('<10I', data, shoff + 40 * i) for i in range(shnum)]
    names = data[sh[shstrndx][4]:sh[shstrndx][4] + sh[shstrndx][5]]
    nm = lambda o: names[o:names.index(b'\0', o)].decode()       # noqa: E731
    sec = [(nm(x[0]),) + x for x in sh]
    out, base = bytearray(), {}
    for i, x in enumerate(sec):
        name, kind, flags, size, align = x[0], x[2], x[3], x[6], x[9] or 1
        if not flags & 2:
            continue
        if flags & 1:
            raise BuildError(f'writable section {name}')
        if name.startswith('.ARM.exidx'):
            continue
        if kind == 8:
            raise BuildError(f'NOBITS section {name}')
        if not (name == '.text' or name.startswith('.rodata')):
            raise BuildError(f'unexpected section {name}')
        if name == '.text' and base:
            raise BuildError('.text must come first')
        out.extend(bytes(-len(out) % max(align, 4)))
        base[i] = len(out)
        out.extend(data[x[5]:x[5] + size])
    if not base or sec[min(base)][0] != '.text':
        raise BuildError('no .text')
    symtab = [i for i, x in enumerate(sec) if x[2] == 2]
    st = sec[symtab[0]]
    strs = data[sec[st[7]][5]:sec[st[7]][5] + sec[st[7]][6]]
    syms = []
    for k in range(st[6] // 16):
        n_, val, _sz, info, _o, shndx = E('<IIIBBH', data, st[5] + 16 * k)
        syms.append((strs[n_:strs.index(b'\0', n_)].decode(), val, info, shndx))
    funcs = {}
    for n_, val, info, shndx in syms:
        if info & 0xF == 2 and shndx in base:
            funcs[n_] = base[shndx] + val
    for x in sec:
        if x[2] != 9:
            continue
        target = x[8]
        tname = sec[target][0]
        if tname.startswith('.ARM.exidx'):
            continue
        if target not in base:
            raise BuildError(f'relocations for {tname}')
        if tname != '.text':
            raise BuildError(f'a data relocation in {tname} (a pointer in read-only data)')
        for k in range(x[6] // 8):
            off, info = E('<II', data, x[5] + 8 * k)
            typ, si = info & 0xFF, info >> 8
            sname, sval, sinfo, shndx = syms[si]
            if shndx not in base:
                raise BuildError(f'undefined or unloaded symbol {sname!r}')
            S = base[shndx] + sval
            P = base[target] + off
            hw1, hw2 = E('<HH', out, P)
            if typ in (R_THM_CALL, R_THM_JUMP24):
                A = _thm_branch_get(hw1, hw2)
                T = S & ~1 if sinfo & 0xF == 2 else S
                if typ == R_THM_CALL and not (S & 1) and sinfo & 0xF == 2:
                    raise BuildError(f'call to an ARM function {sname}')
                hw1, hw2 = _thm_branch_set(hw1, hw2, (T & ~1) + A - P)
                if typ == R_THM_CALL:
                    hw2 |= 0x1000
            elif typ in (R_THM_MOVW_PREL_NC, R_THM_MOVT_PREL):
                A = _thm_imm16(hw1, hw2)
                A = A - 0x10000 if A & 0x8000 else A
                v = (S + A - P) & 0xFFFFFFFF
                hw1, hw2 = _thm_set_imm16(hw1, hw2, v & 0xFFFF if typ == R_THM_MOVW_PREL_NC else v >> 16)
            else:
                raise BuildError(f'relocation type {typ} for {sname!r}')
            struct.pack_into('<HH', out, P, hw1, hw2)
    return bytes(out), funcs


UNIT = '''/* the test unit: what slqs.c will be (core.c, then ap.c) */
#include "core.c"
#include "ap.c"
/* host-visible entries of the pure half, kept out of line for the tests */
__attribute__((noinline, used)) int apc_build_t(const uint32_t *a, struct apc_work *w, struct apc_out *o)
{
    return apc_build(a[0], a[1], a[2], a[3], (int32_t)a[4], (int32_t)a[5], (int32_t)a[6], a[7], a[8], a[9], a[10],
                     a[11], a[12], a[13], w, o);
}
__attribute__((noinline, used)) uint32_t ap_sizes_t(uint32_t i)
{
    return i == 0 ? sizeof(struct ap) : i == 1 ? sizeof(struct apc_out) : i == 2 ? sizeof(struct apc_work) :
           i == 3 ? sizeof(struct ap_slot) : i == 4 ? sizeof(struct ap_sel) : i == 5 ? sizeof(struct ap_status) :
           i == 6 ? (uint32_t)__builtin_offsetof(struct ap, slot) : i == 7 ? (uint32_t)__builtin_offsetof(struct ap, ven) :
           i == 8 ? (uint32_t)__builtin_offsetof(struct ap_slot, row) : i == 9 ? (uint32_t)__builtin_offsetof(struct ap, active) :
           i == 10 ? (uint32_t)__builtin_offsetof(struct ap, cur) : i == 11 ? (uint32_t)__builtin_offsetof(struct ap, picked) :
           i == 12 ? (uint32_t)__builtin_offsetof(struct ap, want) : i == 13 ? (uint32_t)__builtin_offsetof(struct ap, seq) :
           i == 14 ? (uint32_t)__builtin_offsetof(struct ap, in_commit) : 0;
}
'''

HOST_UNIT = '''#include "core.c"
#include "ap_calc.c"
int apc_build_host(const uint32_t *a, struct apc_work *w, struct apc_out *o)
{
    return apc_build(a[0], a[1], a[2], a[3], (int32_t)a[4], (int32_t)a[5], (int32_t)a[6], a[7], a[8], a[9], a[10],
                     a[11], a[12], a[13], w, o);
}
unsigned apc_f32_host(uint64_t n, uint64_t d) { return apc_f32(n, d); }
unsigned apc_carrier_host(unsigned n, unsigned d) { return apc_carrier(n, d)->en; }
unsigned apc_gate_host(unsigned a, unsigned b, unsigned c, unsigned d, unsigned e, unsigned f) { return apc_standby_ok(a, b, c, d, e, f); }
unsigned apc_route_host(unsigned a, unsigned b, unsigned c, unsigned d, unsigned e, unsigned f) { return apc_route_ok(a, b, c, d, e, f); }
unsigned apc_sizes(int i) { return i == 0 ? sizeof(struct apc_work) : sizeof(struct apc_out); }
void apc_limit_host(uint64_t n, uint64_t d, uint64_t lim, uint32_t *pn, uint32_t *pd) { apc_limit(n, d, lim, pn, pd); }
void apc_display_host(uint64_t an, uint64_t ad, struct apc_out *o) { apc_display(o, an, ad); }
void apc_dng_host(uint32_t hm, uint32_t v, uint32_t sn, uint32_t sd, uint32_t *on, uint32_t *od) { apc_dng_rate(hm, v, sn, sd, on, od); }
'''


def arm(src_dir=HERE, out_dir=None):
    """(flat image bytes, {function: offset}) of the test unit built from src_dir's ap.c / ap_calc.c / ap.h."""
    clang = shutil.which('clang') or 'clang'
    with tempfile.TemporaryDirectory(prefix='slap-') as t:
        unit = pathlib.Path(t) / 'ap_unit.c'
        unit.write_text(UNIT)
        obj = pathlib.Path(t) / 'ap_unit.o'
        r = subprocess.run([clang, *CFLAGS, '-I', str(src_dir), '-I', str(CORE), '-I', str(LDR), '-c', str(unit),
                            '-o', str(obj)], capture_output=True, text=True)
        if r.returncode:
            raise BuildError('ARM compile failed:\n' + r.stderr[-6000:])
        img, funcs = link_flat(obj.read_bytes())
        # the unit alone (ap.c without core.c's bodies) must compile too: it is its own compilation unit
        alone = pathlib.Path(t) / 'ap_alone.o'
        r = subprocess.run([clang, *CFLAGS, '-I', str(src_dir), '-I', str(CORE), '-I', str(LDR), '-c',
                            str(pathlib.Path(src_dir) / 'ap.c'), '-o', str(alone)], capture_output=True, text=True)
        if r.returncode:
            raise BuildError('ap.c alone failed:\n' + r.stderr[-4000:])
    if out_dir:
        pathlib.Path(out_dir).mkdir(parents=True, exist_ok=True)
        (pathlib.Path(out_dir) / 'ap_unit.bin').write_bytes(img)
    return img, funcs


def host(src_dir=HERE, out_dir=BUILD, name='apc_host'):
    import ctypes
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    unit = out_dir / f'{name}.c'
    unit.write_text(HOST_UNIT)
    lib = out_dir / f'{name}.dylib'
    r = subprocess.run(['clang', '-O2', '-std=c11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-shared',
                        '-fPIC', '-I', str(src_dir), '-I', str(CORE), '-o', str(lib), str(unit)],
                       capture_output=True, text=True)
    if r.returncode:
        raise BuildError('host compile failed:\n' + r.stderr[-4000:])
    return ctypes.CDLL(str(lib))


def main():
    img, funcs = arm(out_dir=BUILD)
    host()
    print(f'ap_unit.bin {len(img)} B; ap_init +{funcs["ap_init"]:#x}; sha256 {hashlib.sha256(img).hexdigest()[:16]}')


if __name__ == '__main__':
    main()
