"""Try the stock QR encoder FUN_c05c5be8 at other versions (gate bypassed in the emulator only).
usage: emu_ver.py <version> <ecc 0=M 1=L> <url>"""
import struct,sys
exec(open('emu_qr.py').read().split("data=sys.argv")[0])
ver=int(sys.argv[1]); ecc=int(sys.argv[2]); url=sys.argv[3].encode()
n=4*ver+17
mu.mem_write(0xC05C5C00,bytes.fromhex('00f020e3'))          # bne -> nop (struct version == 0x14 check)
def gate(mu,addr,size,_):                                     # FUN_c05cbe08: capacity -> 0xffff
    mu.reg_write(UC_ARM_REG_R0,0xffff); mu.reg_write(UC_ARM_REG_PC,mu.reg_read(UC_ARM_REG_LR))
mu.hook_add(UC_HOOK_CODE,gate,begin=0xC05CBE08,end=0xC05CBE08)
data=bytes((b-i)&0xff for i,b in enumerate(url))
WORK=H; DATA=H+0x10000; DST=H+0x20000; P=H+0x8000
mu.mem_write(DATA,data); mu.mem_write(DST,b'\xff'*20000)
mu.mem_write(P,struct.pack('<B3xIIIIIIIII',ver,2,ecc,WORK,len(data),DATA,1,1,n,DST))
try: r=run(0xC05C5BE8,[P],limit=50_000_000); print('ret',hex(r))
except Exception as e: print('emu error',e, hex(mu.reg_read(UC_ARM_REG_PC)))
import numpy as np, cv2
m=np.frombuffer(bytes(mu.mem_read(DST,n*n)),np.uint8).reshape(n,n)
print('n',n,'dark',int((m==0).sum()),'of',n*n)
img=cv2.copyMakeBorder(cv2.resize(m,(n*8,n*8),interpolation=cv2.INTER_NEAREST),40,40,40,40,cv2.BORDER_CONSTANT,value=255)
cv2.imwrite(f'v{ver}.png',img)
print('decoded:',repr(cv2.QRCodeDetector().detectAndDecode(img)[0]))
