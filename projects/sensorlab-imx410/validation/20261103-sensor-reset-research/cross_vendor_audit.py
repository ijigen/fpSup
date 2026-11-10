#!/usr/bin/env python3
"""Read-only ELF/table audit. No vendor code is executed and no USB is imported."""
import hashlib
import json
import pathlib
import struct

import capstone

ROOT = pathlib.Path(__file__).resolve().parents[4]
DJI = ROOT / 'projects/fp-lidar-direct/evidence/20261022-ronin4d/derived/system/lib64/libsensor_imx410.so'
ZCAM = ROOT / 'projects/imx410-lab/offline/zcam/zcam_imx410_tables.json'
data = DJI.read_bytes()
assert hashlib.sha256(data).hexdigest() == '390e4e03043778dd91a618f3b5eebce281cdb455545da15f939db894ab841786'
shoff = struct.unpack_from('<Q', data, 40)[0]
shsize, shnum, stridx = struct.unpack_from('<HHH', data, 58)
sections = [struct.unpack_from('<IIQQQQIIQQ', data, shoff + i * shsize) for i in range(shnum)]
strings = sections[stridx]
names = data[strings[4]:strings[4] + strings[5]]
by_name = {names[s[0]:].split(b'\0')[0].decode(): s for s in sections}

def read(va, size):
    for section in sections:
        if section[1] != 8 and section[3] <= va and va + size <= section[3] + section[5]:
            offset = section[4] + va - section[3]
            return data[offset:offset + size]
    raise ValueError(hex(va))

def cstring(va):
    return read(va, 160).split(b'\0')[0].decode()

symbols = []
symbol_names = {}
symtab = by_name['.dynsym']
strtab = sections[symtab[6]]
strdata = data[strtab[4]:strtab[4] + strtab[5]]
for offset in range(symtab[4], symtab[4] + symtab[5], symtab[9]):
    name, info, other, index, value, size = struct.unpack_from('<IBBHQQ', data, offset)
    name = strdata[name:].split(b'\0')[0].decode()
    symbols.append((value, size, name))
    if value:
        symbol_names[value] = name
rela, plt = by_name['.rela.plt'], by_name['.plt']
for i, offset in enumerate(range(rela[4], rela[4] + rela[5], rela[9])):
    target, info, addend = struct.unpack_from('<QQq', data, offset)
    symbol_names[plt[3] + 32 + 16 * i] = symbols[info >> 32][2] + '@plt'

print('Source:', DJI.relative_to(ROOT))
print('SHA256:', hashlib.sha256(data).hexdigest())
print('Capstone:', capstone.__version__)
cs = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_LITTLE_ENDIAN)
for label, begin, end in [
    ('probe XCLR', 0x5efc, 0x5f28),
    ('global init and park', 0x65e4, 0x6744),
    ('start reconfigure path', 0x70f8, 0x7114),
    ('stop stream', 0x7220, 0x72f4),
    ('start full path', 0x73ec, 0x7408),
    ('external sync and receiver wait', 0x74f0, 0x750c),
    ('standby/wakeup helper first half', 0xcd70, 0xce40),
    ('standby/wakeup helper last half', 0xcfdc, 0xd02c),
    ('table writer address/value decoding', 0xd100, 0xd158),
    ('table writer call', 0xd2bc, 0xd2e8),
    ('receiver wait wrapper', 0x125e8, 0x12600),
]:
    print('\n' + label)
    for ins in cs.disasm(read(begin, end - begin), begin):
        extra = ''
        if ins.mnemonic in ('b', 'bl') and ins.op_str.startswith('#'):
            extra = symbol_names.get(int(ins.op_str[1:], 16), '')
        print(f'{ins.address:08x} {ins.mnemonic:8} {ins.op_str} {extra}')

print('\nAssociated strings')
for va in (0x1759b, 0x1777b, 0x17ea0, 0x1748b, 0x15e31):
    print(hex(va), cstring(va))

rows = []
for i in range(179):
    row = read(0x3d2c8 + i * 48, 48)
    reg = struct.unpack_from('<H', row, 8)[0]
    if reg == 0xffff:
        assert i == 178
        break
    rows.append((reg, row[10:48]))
print('\nDJI table (178 register rows, 38 readout columns):')
for reg, vals in rows:
    if reg in (0, 1, 0x11, 0x16, 0x1c, 0xc5, 0xc6, 0xca, 0xce, 0x242, 0x278, 0x279, 0x27b, 0x8b6, 0x8b7):
        print(f'{reg:04X}', ' '.join(f'{v:02X}' for v in vals))
print('Table includes 0011:', any(reg == 0x11 for reg, _ in rows))
print('Table includes 0000:', any(reg == 0 for reg, _ in rows))
print('Table includes 00CE:', any(reg == 0xce for reg, _ in rows))
zcam = json.loads(ZCAM.read_text())
print('\nZ CAM exposed modes using readout 21/22:', [m for m in zcam['modes'] if m['readout'] in (21, 22)])
print('Z CAM init rows writing 0011:', [r for r in zcam['regs'] if r['addr'] == 0x11 and any(v != 0xffff for v in r['val'])])
