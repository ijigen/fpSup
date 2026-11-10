# live7 copy of live6 qst6.py (container still v0.2.4 @C55BC8C0, unchanged offsets)
import sys, re, subprocess
FPSH='/Users/dido/Developer.localized/SIGMAfp_re/fpSup/fp_usb_shell/host/fpsh'
B=0xC55BC8C0; S=B+173888
def rd(addr, n):
    out=subprocess.run([FPSH, f'mem get 0x{addr:08X},,{n*4}'],capture_output=True,text=True,timeout=30).stdout
    return [int(x,16) for x in re.findall(r'D:0x([0-9A-Fa-f]+)',out)]
def s32(x): return x-(1<<32) if x&0x80000000 else x
blocks=[(0,12),(3224,8),(11016,12),(11704,17),(11932,9),(64732,6)]
data={}
for off,n in blocks:
    v=rd(S+off,n)
    for i,x in enumerate(v): data[off+4*i]=s32(x)
F={'result':4,'phase':8,'freeze':12,'N':32,'recv':36,'full':40,'bad':44,'saves':3224,
 'qs_result':11016,'qs_ready':11020,'hits':11040,'foreign':11044,'qs_vars':11052,
 'sub_open':11704,'keys':11740,'dials':11744,'aels':11748,'opens':11752,'closes':11756,'adjusts':11760,'locked':11764,'posts':11768,
 'menus':11932,'focus_cb':11936,'hints':11940,'fresh':11944,'sub_home':11948,'focus_id':11952,'foot_on':11964,
 'n_leave':64732,'fine_on':64736,'fines':64740,'leaves':64744,'rears':64748,'foot_pitch':64752}
print(' '.join(f'{k}={data.get(o)}' for k,o in F.items()))
print('sub8=',[data.get(11708+4*i) for i in range(8)], 'focus=0x%X'%rd(0xC37B72A8+0xBC,1)[0])
if '-s' in sys.argv:
    print('STILL',rd(0xC31B07A4,8)); print('CINE',rd(0xC31B0ABC,8))
    for c in ['SetMovRecFormat','SetMovRecSize','SetMovFramerate','SetIso','SetHeadphoneVolume']:
        o=subprocess.run([FPSH,'menu '+c],capture_output=True,text=True,timeout=30).stdout.split()
        print(c,o[:1],end='  ')
    print()
