import struct,sys
exec(open('emu_qr.py').read().split("data=sys.argv")[0])
url=sys.argv[1].encode(); bpp=int(sys.argv[2])
data=bytes((b-i)&0xff for i,b in enumerate(url))
WORK=H; DATA=H+0x10000; DST=H+0x20000; P=H+0x8000
mu.mem_write(DATA,data); mu.mem_write(DST,b'\xff'*20000)
p=struct.pack('<B3xIIIII IIII',0x14,2,1,WORK,len(data),DATA,1,bpp,97,DST)
mu.mem_write(P,p)
import time;t=time.time();cnt=[0]
mu.hook_add(UC_HOOK_CODE,lambda *a: cnt.__setitem__(0,cnt[0]+1))
r=run(0xC05C5BE8,[P]); print('ret',hex(r),'insns',cnt[0])
b=bytes(mu.mem_read(DST,97*97*bpp+16))
import numpy as np, cv2
print('vals',sorted(set(b[:97*97*bpp])), 'tail',b[97*97*bpp:97*97*bpp+4])
if bpp==1:
  m=np.frombuffer(b[:97*97],np.uint8).reshape(97,97)
  img=cv2.resize(m,(97*6,97*6),interpolation=cv2.INTER_NEAREST); img=cv2.copyMakeBorder(img,40,40,40,40,cv2.BORDER_CONSTANT,value=255)
  print(repr(cv2.QRCodeDetector().detectAndDecode(img)[0]))
