#!/usr/bin/env python3
"""Original fp 5.02 H1 setter/routing instructions, passive MMIO, no camera."""
import json,struct,hashlib
from pathlib import Path
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_MEM_WRITE
from unicorn.arm_const import *
ROOT=Path('/Users/dido/Developer.localized/SIGMAfp_re'); P=0xc3e00000; DONE=0xc3ef0000
SEG0=(ROOT/'out/seg0_c0000000.bin').read_bytes(); SEG1=(ROOT/'out/seg1_c2ef6e00.bin').read_bytes()
REAL=[(0xc017e138,0xc017e5e0),(0xc0180418,0xc01805e8),(0xc017faa0,0xc017fb00),(0xc0633b30,0xc0633d30)]
class Rig:
 def __init__(self):
  self.m=Uc(UC_ARCH_ARM,UC_MODE_ARM);self.m.mem_map(0xc0000000,0x4000000);self.m.mem_write(0xc0000000,SEG0);self.m.mem_write(0xc2ef6e00,SEG1);self.m.mem_map(0x30000000,0x400000);self.trace=[];self.writes=[];self.returned=False
  self.m.hook_add(UC_HOOK_CODE,self.code);self.m.hook_add(UC_HOOK_MEM_WRITE,self.write,begin=0x30000000,end=0x303fffff)
 def w(self,a):return struct.unpack('<I',self.m.mem_read(a,4))[0]
 def put(self,a,v):self.m.mem_write(a,struct.pack('<I',v))
 def ret(self,v=0):self.m.reg_write(UC_ARM_REG_R0,v);self.m.reg_write(UC_ARM_REG_PC,self.m.reg_read(UC_ARM_REG_LR))
 def write(self,m,access,a,s,v,d):self.writes.append([hex(a),s,hex(v)])
 def code(self,m,a,s,d):
  regs=[m.reg_read(r) for r in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3)]
  if a==DONE:self.returned=True;m.emu_stop();return
  if any(lo<=a<hi for lo,hi in REAL):return
  if a==0xc0015058:m.mem_write(regs[0],bytes([regs[1]&255])*regs[2]);return self.ret(regs[0])
  if a==0xc000ec14:self.trace.append(['irq_mask_stub',regs]);return self.ret(0)
  if a==0xc000ec24:self.trace.append(['irq_restore_stub',regs]);return self.ret(0)
  if a==0xc0134058:self.trace.append(['bufa_prepare_stub',regs]);return self.ret(0)
  if a==0xc019b0b8:
   self.trace.append(['route_builder_stub',regs,[list(struct.unpack('<2I',m.mem_read(regs[1]+8*i,8))) for i in range(regs[0])]])
   m.mem_write(regs[2],bytes(20));return self.ret(0)
  if a==0xc019b3e8:self.trace.append(['route_submit_stub',regs]);return self.ret(0)
  raise RuntimeError('unexpected original instruction '+hex(a))
 def call(self,a,*args):
  self.returned=False;self.m.reg_write(UC_ARM_REG_SP,0xc3ff0000);self.m.reg_write(UC_ARM_REG_LR,DONE)
  for r,v in zip((UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3),args):self.m.reg_write(r,v)
  self.m.emu_start(a|1,0,count=100000);assert self.returned
 def case(self,record,route,ch):
  source=SEG0[0xc0b5f770-0xc0000000+record*0x38:0xc0b5f770-0xc0000000+record*0x38+0x2c]
  driver=bytearray(source);driver[0]=0;driver[0x1a]=1;driver[0x28]=0
  self.m.mem_write(P+0x800,bytes(driver));self.call(0xc0633b30,1,P+0x800)
  before_h=self.w(0x300f0840);self.call(0xc017faa0,1,0);assert self.w(0x300f0840)==before_h
  desc=bytearray(0x520);struct.pack_into('<I',desc,0x50c,1);struct.pack_into('<I',desc,0x38+0xc,ch);struct.pack_into('<I',desc,0x38+0x14,route)
  self.m.mem_write(P,bytes(desc));self.put(0x30182050,0);self.call(0xc017e138,P)
  mux=self.w({0:0x300f06b0,7:0x300f06d0}[ch]);gate=self.w(0x30182050)
  assert mux==(3 if route==0x10 else 4 if route==0x40 else 1)
  assert gate==(0x100 if ch==7 else 1)
  assert bytes(self.m.mem_read(P,len(desc)))==bytes(desc)
  assert self.w(0x300f0840)==before_h and self.w(0x300f08c0)==0
  routes=[x[2] for x in self.trace if x[0]=='route_builder_stub']
  assert routes==[[[3 if ch==7 else 1,0x4c000 if ch==7 else 0x1c000]]]
  active=dict(record=record,route=hex(route),channel=ch,h1_control=hex(before_h),h1_kernel=[hex(self.w(x)) for x in range(0x300f0850,0x300f0860,4)],mux=mux,bufa_gate=hex(gate),route_pairs=routes[0],helper_trace=self.trace)
  self.call(0xc017faa0,0,0);active['h1_after_native_source_zero']=hex(self.w(0x300f0840));assert self.w(0x300f0840)==before_h&~3
  return active
cases=[]
for r in (0,1):
 for route,ch in ((0x10,7),(0x40,0),(4,0)):
  c=Rig();cases.append(c.case(r,route,ch))
proof=dict(status='PASS_OFFLINE',camera_operated=False,pixel_emulation=False,cases=cases,firmware_sha256={'seg0':hashlib.sha256(SEG0).hexdigest(),'seg1':hashlib.sha256(SEG1).hexdigest()},real_original_functions=[hex(a) for a,b in REAL],limits=['Synthetic frame descriptors follow static C01CB388 channel-selection rules; C01CB388 itself is not executed.','Only H1/H2 setter and C017E138/C0180418 routing/gate instructions execute.','memset, IRQ mask/restore, BUFA preparation, route builder and submit are explicit stubs.','MMIO is passive memory; no pixel, DMA, timing, scheduling, completion, restoration or RAW14 precision result.','The 0x40 and 4 cases deliberately retain H1 as route controls, not complete native product configurations.'])
Path('/private/tmp/h1-route-native-20261030.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps({'status':proof['status'],'cases':len(cases),'result':'/private/tmp/h1-route-native-20261030.json','h1_route_cases':[dict(record=x['record'],h1_control=x['h1_control'],mux=x['mux'],bufa_gate=x['bufa_gate'],route_pairs=x['route_pairs']) for x in cases if x['route']=='0x10']},indent=2))
