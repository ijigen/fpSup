from pathlib import Path
import struct,json
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_CPSR
ROOT=Path(__file__).resolve().parents[4]
base=0xc0000000; mm=0x300f0000; arg=0xc3e00000; done=0xc3ef0000
m=Uc(UC_ARCH_ARM,UC_MODE_ARM);m.mem_map(base,0x4000000);m.mem_write(base,(ROOT/'out/MAIN_c0000000.bin').read_bytes());m.mem_write(0xc2ef6e00,(ROOT/'out/seg1_c2ef6e00.bin').read_bytes());m.mem_map(mm,0x4000)
w=lambda a:struct.unpack('<I',m.mem_read(a,4))[0]
def put(a,v):m.mem_write(a,struct.pack('<I',v))
def stop(mu,a,s,u):mu.emu_stop()
m.hook_add(UC_HOOK_CODE,stop,begin=done,end=done)
trace=[]
def mem(mu,access,a,s,v,u):trace.append((a,v))
m.hook_add(UC_HOOK_MEM_WRITE,mem,begin=mm,end=mm+0x3fff)
def call(a,x,y=0):
 m.reg_write(UC_ARM_REG_SP,0xc3ff0000);m.reg_write(UC_ARM_REG_LR,done);m.reg_write(UC_ARM_REG_R0,x);m.reg_write(UC_ARM_REG_R1,y);m.emu_start(a|1,0,count=100000)
record=bytes(m.mem_read(0xc2f1226c,200));m.mem_write(arg,record)
put(mm+0x900,0x20000001)
call(0xc0101c30,arg)
a={f'{x:08x}':v for x,v in trace};assert w(mm+0x900)==0x21010001
assert w(mm+0x910)==16 and w(mm+0x914)==0x08100810 and w(mm+0x918)==0
# The main driver's compact params: window flag byte0, H ratio ushort2, V ushort4.
m.mem_write(arg+0x100,struct.pack('<BBHHH',1,0,2048,1024,0));trace.clear();call(0xc0633e60,1,arg+0x100)
b={f'{x:08x}':v for x,v in trace};assert w(mm+0x900)==1 and w(mm+0x908)==2048 and w(mm+0x90c)==1024
# Reapply default full settings, then exact native partial setter preserves flags.
call(0xc0101c30,arg);q=[0]*50;q[0]=1;q[4]=2048;q[5]=512;q[6]=1024;q[7]=0
m.mem_write(arg+0x200,struct.pack('<50I',*q));trace.clear();call(0xc0634038,arg+0x200,1)
c={f'{x:08x}':v for x,v in trace};assert w(mm+0x900)==0x01010001 and w(mm+0x908)==0x02000800 and w(mm+0x90c)==1024
proof={'scope':'real Thumb setter execution only; MMIO is passive RAM; no image simulation or camera access','defaults':list(struct.unpack('<50I',record)),'full_setter':a,'compact_driver':b,'partial_driver':c}


# Exact integer identity of the default spatial coefficient table.
wds=list(struct.unpack('<50I',record))
curve=[(4096-48*i*i+2*i*i*i+2)//4 for i in range(17)]
assert wds[16:33]==curve and wds[33:50]==curve
proof['coefficient_identity']='floor(1024*(1-3*(i/16)^2+2*(i/16)^3)+0.5), i=0..16'
# Eight bounded candidates; vary only native 00/11 flags and independent H phase.
# V remains unity/phase0; no guessed 0910/0914/0918 values.
pre=bytes(m.mem_read(mm,0x4000)); old=dict((o,w(mm+o)) for o in [0x4,0x900,0x908,0x90c])
matrix=[]
for ratio in (2048,3072):
 for flags in (0,1):
  for phase in (0,512):
   d=list(wds);d[1]=flags;d[2]=flags;m.mem_write(arg,struct.pack('<50I',*d));call(0xc0101c30,arg)
   q=[0]*50;q[0]=1;q[4]=ratio;q[5]=phase;q[6]=1024;q[7]=0;m.mem_write(arg+0x200,struct.pack('<50I',*q));call(0xc0634038,arg+0x200,(old[4]>>8)&1)
   assert w(mm+0x900)==(old[0x900]&0xfefefffe)|1|(flags<<16)|(flags<<24)
   assert w(mm+0x908)==ratio|(phase<<16) and w(mm+0x90c)==1024
   matrix.append(dict(h_ratio=ratio,v_ratio=1024,flags16=flags,flags24=flags,h_phase=phase,v_phase=0,control=w(mm+0x900),word0908=w(mm+0x908),word090c=w(mm+0x90c)))
# Replay captured typed state through native setters; this proves register mapping,
# not live quiescence, pixel precision, an input injection path, or reset safety.
d=list(wds);d[1]=(old[0x900]>>16)&1;d[2]=(old[0x900]>>24)&1;m.mem_write(arg,struct.pack('<50I',*d));call(0xc0101c30,arg)
q=[0]*50;q[0]=old[0x900]&1;q[4]=old[0x908]&65535;q[5]=old[0x908]>>16;q[6]=old[0x90c]&65535;q[7]=old[0x90c]>>16
m.mem_write(arg+0x200,struct.pack('<50I',*q));call(0xc0634038,arg+0x200,(old[4]>>8)&1)
assert bytes(m.mem_read(mm,0x4000))==pre
proof['matrix']=matrix;proof['emulated_register_restore_equal']=True
import hashlib
proof['firmware_sha256']=hashlib.sha256((ROOT/'out/MAIN_c0000000.bin').read_bytes()).hexdigest()
proof['seg1_sha256']=hashlib.sha256((ROOT/'out/seg1_c2ef6e00.bin').read_bytes()).hexdigest()
proof['hardware_precision']='unknown; no pixel or sensor execution'
print(json.dumps(proof,indent=2))
