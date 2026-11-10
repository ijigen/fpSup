#!/usr/bin/env python3
"""Bounded, reproducible static SS event/producer/encoder evidence. No USB."""
import hashlib
import json
from pathlib import Path
import struct
from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB

ROOT=Path(__file__).resolve().parents[5]
files={name:(ROOT/'out'/name).read_bytes() for name in
       ('MAIN_c0000000.bin','seg0_c0000000.bin','seg1_c2ef6e00.bin')}
b=bytearray(files['MAIN_c0000000.bin'])
b[:len(files['seg0_c0000000.bin'])]=files['seg0_c0000000.bin']
s=files['seg1_c2ef6e00.bin']; b[0x2EF6E00:0x2EF6E00+len(s)]=s

def words(a,n): return list(struct.unpack_from('<'+'I'*n,b,a-0xC0000000))
def cstring(a):
    i=a-0xC0000000
    return bytes(b[i:b.index(0,i)]).decode('ascii')
def disasm(a,n,thumb=False):
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB if thumb else CS_MODE_ARM)
    return [f'{i.address:08X} {i.bytes.hex():8s} {i.mnemonic} {i.op_str}'
            for i in md.disasm(bytes(b[a-0xC0000000:a-0xC0000000+n]),a)]

events=[]
for event in (0x18,0x19):
    name_ptr=words(0xC2F1FA78+event*4,1)[0]
    row=words(0xC0B9E034+event*16,4)
    handler=words(0xC2F1F5A4+event*16,3)
    events.append(dict(event=event,name=cstring(name_ptr),camera_dispatch=row,
        movie_state_dispatch=handler))
ranges=((0xC03A1F78,0xD0,False),(0xC038ACA8,0xB0,False),
    (0xC03AB638,0x70,False),(0xC03ABDD8,0x60,False),
    (0xC03833B8,0x318,False),(0xC0383910,0x190,False),
    (0xC0306B60,0xB8,False),(0xC00EAD70,0x120,True),
    (0xC00EB290,0x160,True),(0xC00EAEF8,0x1A0,True),
    (0xC042EAD0,0x98,False),(0xC042EC90,0x198,False))
result=dict(image_sha256={k:hashlib.sha256(v).hexdigest() for k,v in files.items()},
    runtime_overlay='seg0 code + seg1 at C2EF6E00; MAIN alone has compressed/uninitialized data at some C2F1 tables',
    events=events,
    screenshot_size_words=words(0xC0B9BA00,2),
    writeback_vtable=words(0xC0B54CD0,4),
    disassembly={f'{a:08X}':disasm(a,n,t) for a,n,t in ranges})
Path(__file__).with_name('ss-producer-evidence.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(dict(events=events,screenshot_size=result['screenshot_size_words']),indent=2))
