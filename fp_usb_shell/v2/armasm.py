"""Assemble an ARM source file and resolve its internal calls.

The camera has no loader: code is copied to a fixed address as raw words, so the
R_ARM_CALL relocations clang leaves for `bl` between local labels have to be
applied here.  Nothing else is supported, which is deliberate — if a source file
needs more than that, it is doing something the camera cannot load anyway.
"""
import pathlib, struct, subprocess, sys, tempfile


def assemble(src) -> bytes:
    src = pathlib.Path(src)
    with tempfile.TemporaryDirectory() as tmp:
        obj = pathlib.Path(tmp) / 'a.o'
        r = subprocess.run(
            ['clang', '-target', 'armv7-none-eabi', '-c', str(src), '-o', str(obj)],
            capture_output=True, text=True)
        if r.returncode:
            sys.stderr.write(r.stderr)
            raise SystemExit(1)
        elf = obj.read_bytes()

    (shoff, _flags, _ehsize, _phentsize, _phnum,
     shentsize, shnum, shstrndx) = struct.unpack_from('<IIHHHHHH', elf, 0x20)
    sections = [struct.unpack_from('<IIIIIIIIII', elf, shoff + i * shentsize)
                for i in range(shnum)]
    names = sections[shstrndx][4]

    def name_of(sec):
        end = elf.index(b'\0', names + sec[0])
        return elf[names + sec[0]:end].decode()

    by_name = {name_of(s): (i, s) for i, s in enumerate(sections)}
    text_i, text = by_name['.text']
    body = bytearray(elf[text[4]:text[4] + text[5]])

    _, symtab = by_name['.symtab']
    syms = [struct.unpack_from('<IIIBBH', elf, off)
            for off in range(symtab[4], symtab[4] + symtab[5], symtab[9])]

    if '.rel.text' in by_name:
        _, rel = by_name['.rel.text']
        for off in range(rel[4], rel[4] + rel[5], rel[9]):
            place, info = struct.unpack_from('<II', elf, off)
            rtype, symidx = info & 0xFF, info >> 8
            if rtype != 28:
                raise SystemExit(f'unsupported relocation {rtype} at {place:#x}')
            _, value, _, _, _, shndx = syms[symidx]
            if shndx != text_i:
                raise SystemExit('call target outside .text')
            disp = value - place - 8
            if disp % 4:
                raise SystemExit('misaligned call target')
            insn = struct.unpack_from('<I', body, place)[0]
            struct.pack_into('<I', body, place,
                             (insn & 0xFF000000) | ((disp >> 2) & 0xFFFFFF))

    if len(body) % 4:
        body += b'\0' * (-len(body) % 4)
    return bytes(body)


def words(code: bytes):
    return struct.unpack(f'<{len(code)//4}I', code)
