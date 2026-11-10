import struct, sys
from unicorn import *
from unicorn.arm_const import *
IMG='/Users/dido/Developer.localized/SIGMAfp_re/out/MAIN_c0000000.bin'
img=open(IMG,'rb').read()
mu=Uc(UC_ARCH_ARM,UC_MODE_ARM)
mu.mem_map(0xC0000000,0x03000000); mu.mem_write(0xC0000000,img[:0x03000000])
mu.mem_map(0xC3000000,0x01000000)
H=0x10000000; mu.mem_map(H,0x01000000)
STK=0x20000000; mu.mem_map(STK-0x10000,0x10000)
DONE=0x30000000; mu.mem_map(DONE,0x1000)
# enable VFP
mu.reg_write(UC_ARM_REG_C1_C0_2, mu.reg_read(UC_ARM_REG_C1_C0_2)|(0xf<<20))
mu.reg_write(UC_ARM_REG_FPEXC,0x40000000)
def run(fn,args,limit=200_000_000):
    regs=[UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3]
    for r,v in zip(regs,args): mu.reg_write(r,v)
    mu.reg_write(UC_ARM_REG_SP,STK-0x100); mu.reg_write(UC_ARM_REG_LR,DONE)
    mu.emu_start(fn,DONE,count=limit)
    return mu.reg_read(UC_ARM_REG_R0)
data=sys.argv[1].encode() if len(sys.argv)>1 else b'https://example.com/m#ABC'
pre=bool(int(sys.argv[2])) if len(sys.argv)>2 else True
if pre: data=bytes((b-i)&0xff for i,b in enumerate(data))
W,Hh=1024,682
WORK=H; DATA=H+0x10000; DST=H+0x20000; P=H+0x8000
mu.mem_write(DATA,data)
# white fill YUYV-ish 0x80ff80ff
mu.mem_write(DST, struct.pack('<I',0x80ff80ff)*(W*Hh//2))
X,Y=0x24a-0x24a+100,0x3f  # place
dst=DST+(W*Y+X)*2
p=struct.pack('<B3xIIIII IIII',0x14,2,1,WORK,len(data),DATA,4,2,W,dst)
mu.mem_write(P,p)
r=run(0xC05C5BE8,[P])
print('ret',hex(r))
buf=bytes(mu.mem_read(DST,W*Hh*2))
import numpy as np
a=np.frombuffer(buf,np.uint8).reshape(Hh,W*2)
# try to get luma: candidates even/odd bytes
for name,yy in (('even',a[:,0::2]),('odd',a[:,1::2])):
    import cv2
    y=np.ascontiguousarray(yy)
    cv2.imwrite(f'/private/tmp/claude-501/-Users-dido-Developer-localized-SIGMAfp-re/f58271b0-5db4-4cd7-a9d1-abe4b221a3ba/scratchpad/qrtools/qr_{name}.png',y)
    det=cv2.QRCodeDetector()
    s,pts,_=det.detectAndDecode(y)
    print(name,'uniq',np.unique(y)[:5],'decoded:',repr(s))
