"""Real ROM helper execution only. No decoder, DMA, LCD or camera proof."""
from pathlib import Path
import sys,struct,json,hashlib
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_HOOK_CODE
from unicorn.arm_const import *
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]
rom=(ROOT/'out/MAIN_c0000000.bin').read_bytes()
m=Uc(UC_ARCH_ARM,UC_MODE_ARM);m.mem_map(0xc0000000,0x3000000);m.mem_write(0xc0000000,rom[:0x3000000]);m.mem_map(0x44000000,0x10000)
DONE=0x4400f000;HOLDER=0x44000000;CANVAS=HOLDER+0x100
ranges=((0xc0436360,0xc04363f4),(0xc02da870,0xc02da8e8),(0xc04356b0,0xc04357e0),(0xc04358d0,0xc0435918))
def guard(mu,a,size,data):
 if a!=DONE and not any(lo<=a<hi for lo,hi in ranges):raise AssertionError(hex(a))
m.hook_add(UC_HOOK_CODE,guard)
def put(a,v):m.mem_write(a,struct.pack('<I',v))
def call(a,*args):
 m.reg_write(UC_ARM_REG_SP,0x4400e000);m.reg_write(UC_ARM_REG_LR,DONE)
 for r,v in zip((UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3),args):m.reg_write(r,v)
 m.emu_start(a,DONE,count=10000);assert m.reg_read(UC_ARM_REG_PC)==DONE
 return m.reg_read(UC_ARM_REG_R0)
put(HOLDER+4,CANVAS);put(CANVAS+0xc,2096);put(CANVAS+0x10,1240)
rows=[]
for code in (7,8,9,10,0x10007,0x10008,0x10009,0x1000a):
 put(CANVAS+0x80,code);en=call(0xc0436360,code);bits=call(0xc02da870,en);size=call(0xc04356b0,HOLDER,0)
 rows.append(dict(canvas_code=hex(code),metadata_enum=en,metadata_bits=bits,native_buffer_bytes=size))
assert next(r for r in rows if r['canvas_code']=='0x10008')['metadata_bits']==12
assert next(r for r in rows if r['canvas_code']=='0x8')['metadata_bits']==14
out=dict(scope=__doc__,rom_sha256=hashlib.sha256(rom).hexdigest(),synthetic_geometry=[2096,1240],cases=rows,conclusion='Packed 14 code falls through metadata conversion to 12 bits; native sizing uses 16 bits. Neither helper proves physical input stride or pixel decode. No production patch yet.')
(HERE/'native-format-probe.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
