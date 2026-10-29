#!/usr/bin/env python3
"""Build the SensorLab-IMX410 QS client (loader v4 sup, sup_id SL41): fpSup/SensorLab-IMX410_v<ver>.BIN, a client
of the QS container (API 4, QSContainer v0.2.2).

    python3 -B build_slqs.py --out out          # + out/build-<ver>.json (offsets, sha256); older BINs untouched

slqs.c is one unit with the C core (#include core.c).  The core's tables are read-only data and the v4 loader
copies one flat image, so link_flat() lays out .text then the .rodata sections and resolves the Thumb calls and
the -fropi PC-relative MOVW / MOVT pairs itself; anything needing a load-time relocation is refused.  The settings record lives in the BIN at rec_off (zeros = the defaults).  No device I/O."""
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
ROOT = HERE.parents[2]
CORE = HERE.parent / 'core'
QSC = ROOT / 'projects' / 'qs-container'
LDR = ROOT / 'fpSup' / 'loader-v4'
sys.path[:0] = [str(HERE), str(LDR), str(QSC)]
import build_v4 as B                       # noqa: E402

VERSION = '0.2.0test'
SUP_ID = 'SL41'
NAME = 'SensorLab-IMX410'
SOURCE = HERE / 'slqs.c'
CFG_MAGIC = 0x32344C53                     # "SL42"
CFG_WORDS = 5
STATE_RESERVE = 49152                      # sizeof(struct st) (the entry checks it fits before dma_off)
DMA_BYTES = 0x800 + 0x400
REC_WORDS = 2 + 30 + 4 * 8 + 1


class BuildError(RuntimeError):
    pass


def file_name():
    return f'SensorLab-IMX410_v{VERSION}.BIN'


class TextImage:
    def __init__(self, code, functions, sections):
        self.code, self.functions, self.sections = code, functions, sections


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
    """One ELF32 ARM relocatable (the unit: slqs.c + the core) -> flat position-independent bytes: .text, then
    every read-only data section; the Thumb calls and the -fropi PC-relative MOVW / MOVT pairs resolved here
    (REL addends from the instructions).  Anything else -- a writable section, an absolute relocation, a data
    relocation, an undefined symbol -- is refused: the image must need no relocation at load."""
    E = struct.unpack_from
    if data[:4] != b'\x7fELF' or data[4:6] != b'\x01\x01' or E('<H', data, 18)[0] != 40:
        raise BuildError('not an ARM ELF32')
    shoff, = E('<I', data, 32)
    shnum, shstrndx = E('<HH', data, 48)
    sh = [E('<10I', data, shoff + 40 * i) for i in range(shnum)]
    names = data[sh[shstrndx][4]:sh[shstrndx][4] + sh[shstrndx][5]]
    nm = lambda o: names[o:names.index(b'\0', o)].decode()
    sec = [(nm(x[0]),) + x for x in sh]
    load, out, base = [], bytearray(), {}
    for i, x in enumerate(sec):
        name, kind, flags, size, align = x[0], x[2], x[3], x[6], x[9] or 1
        if not flags & 2:                                  # SHF_ALLOC
            continue
        if flags & 1:
            raise BuildError(f'writable section {name}')
        if name == '.ARM.exidx' or name.startswith('.ARM.exidx'):
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
        load.append(name)
    if not base or sec[min(base)][0] != '.text':
        raise BuildError('no .text')
    symtab = [i for i, x in enumerate(sec) if x[2] == 2]
    if len(symtab) != 1:
        raise BuildError('one symbol table expected')
    st = sec[symtab[0]]
    strs = data[sec[st[7]][5]:sec[st[7]][5] + sec[st[7]][6]]
    syms = []
    for k in range(st[6] // 16):
        n_, val, _sz, info, _o, shndx = E('<IIIBBH', data, st[5] + 16 * k)
        syms.append((strs[n_:strs.index(b'\0', n_)].decode(), val, info, shndx))
    funcs = {}
    for n_, val, info, shndx in syms:
        if info & 0xF == 2 and shndx in base:              # STT_FUNC
            funcs[n_] = base[shndx] + val
    for x in sec:
        if x[2] != 9:                                      # SHT_REL
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
                    hw2 |= 0x1000                         # BL
            elif typ in (R_THM_MOVW_PREL_NC, R_THM_MOVT_PREL):
                A = _thm_imm16(hw1, hw2)
                A = A - 0x10000 if A & 0x8000 else A
                v = (S + A - P) & 0xFFFFFFFF
                hw1, hw2 = _thm_set_imm16(hw1, hw2, v & 0xFFFF if typ == R_THM_MOVW_PREL_NC else v >> 16)
            else:
                raise BuildError(f'relocation type {typ} for {sname!r}')
            struct.pack_into('<HH', out, P, hw1, hw2)
    return TextImage(bytes(out), funcs, load)


def compile_text(src, extra=()):
    """slqs.c (+ the core) -> TextImage: .text and the read-only data, linked flat"""
    clang = shutil.which('clang') or 'clang'
    flags = [*B.CFLAGS, *B.V3.cdefs(), *extra, '-I', str(CORE), '-I', str(QSC), '-I', str(LDR),
             '-I', str(B.FPSUP_UI), '-fno-unwind-tables', '-fno-asynchronous-unwind-tables']
    with tempfile.TemporaryDirectory(prefix='slqs-') as t:
        obj = pathlib.Path(t) / 'slqs.o'
        r = subprocess.run([clang, *flags, '-c', str(src), '-o', str(obj)], capture_output=True, text=True)
        if r.returncode:
            raise BuildError('compile failed:\n' + r.stderr)
        img = link_flat(obj.read_bytes())
    if not img.functions.get('sup_entry', 0) & 1:
        raise BuildError('sup_entry missing or not Thumb')
    return img


def build(src=None):
    src = src or os.environ.get('SLQS_SRC') or SOURCE
    text = compile_text(pathlib.Path(src))
    hdr = B.SL4_HEADER_LEN
    lead = 4 * CFG_WORDS
    lead += -(hdr + lead) % 8                  # the code (and its folded data) 8-aligned in the block
    body = bytearray(lead) + text.code
    entry = hdr + lead + text.functions['sup_entry']

    def place(data, align=4):
        body.extend(bytes(-(hdr + len(body)) % align))
        at = hdr + len(body)
        body.extend(data)
        return at
    rec_off = place(bytes(4 * REC_WORDS))
    probe = B.make_sup(bytes(body), entry, SUP_ID, min_svc=6, flags=B.SL_F_CACHED_OK, name=NAME)
    file_len = len(probe)
    state_off = (file_len + 63) & ~63
    dma_off = (state_off + STATE_RESERVE + 63) & ~63
    block = dma_off + DMA_BYTES
    words = [CFG_MAGIC, 2, state_off, dma_off, rec_off]
    body[0:4 * CFG_WORDS] = struct.pack(f'<{CFG_WORDS}I', *words)
    blob = B.make_sup(bytes(body), entry, SUP_ID, min_svc=6, flags=B.SL_F_CACHED_OK, name=NAME,
                      block_size=block, dma=(dma_off, DMA_BYTES), version=20)
    if len(blob) != file_len:
        raise BuildError('layout moved')
    info = dict(file=file_name(), bytes=len(blob), sha256=hashlib.sha256(blob).hexdigest(), sup_id=SUP_ID,
                entry=entry, code=len(text.code), code_off=hdr + lead, state_off=state_off, dma_off=dma_off,
                block_size=block, rec_off=rec_off, functions=text.functions)
    return blob, info


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    (out / 'fpSup').mkdir(parents=True, exist_ok=True)
    blob, info = build()
    (out / 'fpSup' / file_name()).write_bytes(blob)
    info.pop('functions')
    (out / f'build-{VERSION}.json').write_text(json.dumps(info, indent=1) + '\n')
    print(f'{file_name()}  {len(blob)} B  {info["sha256"][:16]}')


if __name__ == '__main__':
    main()
