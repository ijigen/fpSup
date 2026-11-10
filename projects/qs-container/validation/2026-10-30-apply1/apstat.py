# apstat.py: read-only SensorLab apply status (mem get only). -s = also the 26 hook sites + clock gate.
import sys, re, subprocess
FPSH='/Users/dido/Developer.localized/SIGMAfp_re/fpSup/fp_usb_shell/host/fpsh'
def rd(addr, n):
    for _ in range(3):
        out=subprocess.run([FPSH, f'mem get 0x{addr:08X},,{n*4}'],capture_output=True,text=True,timeout=30).stdout
        v=[int(x,16) for x in re.findall(r'D:0x([0-9A-Fa-f]+)',out)]
        if len(v)==n: return v
    raise SystemExit(f'short read at {addr:08X}: {out!r}')
def s32(x): return x-(1<<32) if x&0x80000000 else x
def btarget(site, w):
    imm=w&0xFFFFFF
    if imm&0x800000: imm-=1<<24
    return (site+8+4*imm)&0xFFFFFFFF
w=rd(0xC0320BA0,1)[0]; cave=btarget(0xC0320BA0,w)
cv=rd(cave,2); apm=cv[1]; blk=apm-0x24050
print(f'site0 {w:08X} cave {cave:08X} -> {cv[0]:08X} {cv[1]:08X}  ap_mem {apm:08X} block {blk:08X}')
v=rd(apm+0x8F0,10)
names=['magic','abi','armed','svc','active','cur','picked','in_commit','owed','seq']
print(' '.join(f'{n}={x:X}' if n in('magic','svc') else f'{n}={s32(x)}' for n,x in zip(names,v)))
v=rd(apm+0x9FC,14)
names=['result','detail','commits','refusals','lv_reloads','picks','lookups','canvases','recrates','commit_us','standby_picks','carrier_sets','clk_ok','clk_open']
print(' '.join(f'{n}={s32(x)}' for n,x in zip(names,v)))
if '-s' in sys.argv:
    sites=[0xC0320BA0,0xC0320B38,0xC0320E90,0xC0320F60,0xC0320EF8,0xC0320C00,0xC0326DB8,0xC031FFA0,0xC031AC38,0xC031ACD8,
           0xC031B660,0xC03249A0,0xC043CCF8,0xC043A18C,0xC043A19C,0xC03A6DD8,0xC00C9BD0,0xC0325228,0xC032DDF0,0xC032DE70,
           0xC0437E98,0xC0306EA0,0xC0306EEC,0xC02DAFA0,0xC00A87E4,0xC04A121C]
    bad=0
    for s in sites:
        x=rd(s,1)[0]; t=btarget(s,x); c=rd(t,2)
        ok=(x>>24) in (0xEA,0xEB) and c[0]==0xE51FF004 and blk<=c[1]<blk+278592
        bad+=not ok
        print(f'  {s:08X} {x:08X} -> {t:08X}: {c[0]:08X} {c[1]:08X} {"ok" if ok else "BAD"}')
    print('sites bad =',bad,' clk 0xC0189440 =',f'{rd(0xC0189440,1)[0]:08X}')
