#!/usr/bin/env python3
"""Offline only: original fp 5.02 ARM front/back getters and ring commit."""
import hashlib,json,pathlib,struct
from capstone import Cs,CS_ARCH_ARM,CS_MODE_ARM
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC
HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parents[3]
ROM=ROOT/'out/MAIN_c0000000.bin'
BASE=0xC0000000;LAYER=0xC3824FA8;VT=0xC2EF6280
DESCS=[0xC38D6DB0,0xC38D6DCC,0xC38D6DE8]
RANGES=[('front getter',0xC07212E0,0x44),('back getter',0xC0721328,0x44),
        ('commit wrapper',0xC0721370,0x58),('ring getters and commit',0xC0721CB8,0x9C),
        ('ready leaf',0xC0721F98,0x10),('draw commits then presents',0xC05289F8,0x44),
        ('present selects front',0xC0528650,0x7C),('present copies front to output request',0xC02E8ABC,0x24),
        ('present submits request',0xC02E8C54,0x10),('front to back copy',0xC0528BA0,0x84)]
def main():
    blob=ROM.read_bytes();md=Cs(CS_ARCH_ARM,CS_MODE_ARM)
    text=[f'Original image: {ROM}\nSHA256: {hashlib.sha256(blob).hexdigest()}\nARM little-endian, raw bytes included.\n']
    for name,at,n in RANGES:
        text.append(f'\n{name} @ {at:08X}\n')
        for i in md.disasm(blob[at-BASE:at-BASE+n],at):text.append(f'{i.address:08X}  {i.bytes.hex()}  {i.mnemonic:8} {i.op_str}\n')
    (HERE/'native-disassembly.txt').write_text(''.join(text))
    mu=Uc(UC_ARCH_ARM,UC_MODE_ARM);mu.mem_map(BASE,0x4000000);mu.mem_write(BASE,blob)
    stack,done=0xC3FF0000,0xC3FFF000
    w=lambda a:struct.unpack('<I',mu.mem_read(a,4))[0]
    def put(a,v):mu.mem_write(a,struct.pack('<I',v))
    put(LAYER,VT)
    for i,d in enumerate(DESCS):put(LAYER+0x3C+4*i,d)
    writes=[]
    mu.hook_add(UC_HOOK_MEM_WRITE,lambda m,acc,a,n,v,user:writes.append((a,n)))
    def call(fn,arg):
        mu.reg_write(UC_ARM_REG_R0,arg);mu.reg_write(UC_ARM_REG_SP,stack);mu.reg_write(UC_ARM_REG_LR,done)
        mu.emu_start(fn,done,count=1000)
        assert mu.reg_read(UC_ARM_REG_PC)==done
        assert mu.reg_read(UC_ARM_REG_SP)==stack
        return mu.reg_read(UC_ARM_REG_R0)
    calls=0;cases=[]
    for start in range(3):
        put(LAYER+0x50,start);put(LAYER+0x48,DESCS[start]);put(LAYER+0x4C,DESCS[(start+1)%3])
        for cycle in range(9):
            front=call(0xC07212E0,LAYER);back=call(0xC0721328,LAYER);calls+=2
            idx=(start+cycle)%3
            assert front==DESCS[idx] and back==DESCS[(idx+1)%3] and front!=back
            before=len(writes);call(0xC0721CD8,LAYER+0x24);calls+=1
            assert set(writes[before:])=={(LAYER+0x48,4),(LAYER+0x4C,4),(LAYER+0x50,4)}
            assert w(LAYER+0x48)==back
            cases.append(dict(start=start,cycle=cycle,front=hex(front),back=hex(back),committed=hex(w(LAYER+0x48))))
    assert all((a,n) in {(LAYER+0x48,4),(LAYER+0x4C,4),(LAYER+0x50,4)} or stack-8<=a<stack for a,n in writes)
    result=dict(status='PASS_OFFLINE',native_calls=calls,cycles=len(cases),image_sha256=hashlib.sha256(blob).hexdigest(),
                physical_display_verified=False,models='layer pointer table and stack only; getters/ready/rotation execute original ARM without function stubs',
                front_pointer_address=hex(LAYER+0x48),back_pointer_address=hex(LAYER+0x4C),index_address=hex(LAYER+0x50),cases=cases)
    (HERE/'proof.json').write_text(json.dumps(result,indent=2)+'\n');print(result['status'],calls,'native calls;',len(cases),'commits')
if __name__=='__main__':main()
