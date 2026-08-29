"""Assemble an ARM source file and resolve its internal calls.

The camera has no loader: code is copied to a fixed address as raw words, so the
R_ARM_CALL relocations clang leaves for `bl` between local labels have to be
applied here.  Nothing else is supported, which is deliberate — if a source file
needs more than that, it is doing something the camera cannot load anyway.
"""
import pathlib, struct, subprocess, sys, tempfile


def _compile(src, defines=()):
    """Assemble to an object file and return (elf_bytes,)."""
    src = pathlib.Path(src)
    with tempfile.TemporaryDirectory() as tmp:
        obj = pathlib.Path(tmp) / 'a.o'
        r = subprocess.run(
            ['clang', '-target', 'armv7-none-eabi', '-c', str(src), '-o', str(obj)]
            + [f'-D{d}' for d in defines],
            capture_output=True, text=True)
        if r.returncode:
            sys.stderr.write(r.stderr)
            raise SystemExit(1)
        elf = obj.read_bytes()
    return elf


def _parse(elf):
    (shoff, _flags, _ehsize, _phentsize, _phnum,
     shentsize, shnum, shstrndx) = struct.unpack_from('<IIHHHHHH', elf, 0x20)
    sections = [struct.unpack_from('<IIIIIIIIII', elf, shoff + i * shentsize)
                for i in range(shnum)]
    names = sections[shstrndx][4]

    def name_of(sec):
        end = elf.index(b'\0', names + sec[0])
        return elf[names + sec[0]:end].decode()

    return elf, sections, {name_of(s): (i, s) for i, s in enumerate(sections)}


def assemble(src, defines=()) -> bytes:
    elf, sections, by_name = _parse(_compile(src, defines))
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
            _, value, _, _, _, shndx = syms[symidx]
            if shndx != text_i:
                raise SystemExit('relocation target outside .text')
            insn = struct.unpack_from('<I', body, place)[0]
            disp = value - place - 8
            if rtype == 28:                     # R_ARM_CALL
                if disp % 4:
                    raise SystemExit('misaligned call target')
                struct.pack_into('<I', body, place,
                                 (insn & 0xFF000000) | ((disp >> 2) & 0xFFFFFF))
            elif rtype == 4:                    # R_ARM_LDR_PC_G0
                # A pc-relative literal load, which is how a template reaches a
                # word the loader fills in.  The U bit carries the sign and the
                # low twelve bits the magnitude.
                mag = abs(disp)
                if mag > 0xFFF:
                    raise SystemExit(f'literal at {place:#x} is {mag} bytes away')
                insn &= ~0x00800FFF
                if disp >= 0:
                    insn |= 0x00800000
                struct.pack_into('<I', body, place, insn | mag)
            else:
                raise SystemExit(f'unsupported relocation {rtype} at {place:#x}')

    if len(body) % 4:
        body += b'\0' * (-len(body) % 4)
    return bytes(body)


def words(code: bytes):
    return struct.unpack(f'<{len(code)//4}I', code)


def symbols(src, defines=()):
    """Map every defined .text symbol to its byte offset within the image.

    The loader needs this to aim a hook at an entry point by name rather than by
    assuming it sits at offset zero -- which it does not, once a source file
    grows a second entry.
    """
    elf, sections, by_name = _parse(_compile(src, defines))
    text_i, _ = by_name['.text']
    _, symtab = by_name['.symtab']
    _, strtab = by_name['.strtab']
    out = {}
    for off in range(symtab[4], symtab[4] + symtab[5], symtab[9]):
        nameoff, value, _, _, _, shndx = struct.unpack_from('<IIIBBH', elf, off)
        if shndx != text_i or not nameoff:
            continue
        end = elf.index(b'\0', strtab[4] + nameoff)
        out[elf[strtab[4] + nameoff:end].decode()] = value
    return out
