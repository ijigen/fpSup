import sys
sys.path.insert(0, '/Users/dido/Developer.localized/SIGMAfp_re/fpSup/fp_usb_shell')
from callfn import call
from putfile import sh, mem_get

def g(a, n=1):
    v = mem_get(a, n)
    if any(x is None for x in v):
        v = mem_get(a, n)
    if any(x is None for x in v):
        raise SystemExit('mem_get None at %x' % a)
    return v

def H(v): return [hex(x) for x in v]

def c(fn, *a):
    ok, r = call(fn, *a)
    if not ok:
        raise SystemExit('call %x failed' % fn)
    print('    = %s' % hex(r), flush=True)
    return r

print('slot:', sh('sdcard slot').strip())
print('sdmode:', sh('sdcard sdmode').strip())
c(0xC0407E20)
d5 = c(0xC0366A98, 5)
print('d5 words', H(g(d5, 8)))
vt5 = g(d5 + 0x18)[0]
print('d5 vt', hex(vt5), 'vt+0x18..+0x2C', H(g(vt5 + 0x18, 6)))
f24, f28 = g(vt5 + 0x24, 2)
print('ready5 C0518410(5)'); r5 = c(0xC0518410, 5)
print('mount5 C0518490(5)'); m5 = c(0xC0518490, 5)
print('SSD vt+0x24', hex(f24)); c(f24, d5)
print('SSD vt+0x28', hex(f28)); c(f28, d5)
# SD side
d1 = c(0xC0366A98, 1)
print('d1 words', H(g(d1, 8)))
vt1 = g(d1 + 0x18)[0]
s24, s28 = g(vt1 + 0x24, 2)
print('ready1 C0518410(1)'); c(0xC0518410, 1)
print('mount1 C0518490(1)'); c(0xC0518490, 1)
print('SD vt+0x24 (sd_mode)', hex(s24)); c(s24, d1)
# item re-derive
fac = g(0xC31CAA80)[0]; fvt = g(fac + 4)[0]; fget = g(fvt + 0x354)[0]
print('fac', hex(fac), 'fvt', hex(fvt), 'vt+0x354', hex(fget))
item = c(fget, fac)
print('item words', H(g(item, 8)))
ivt = g(item + 0xC)[0]
iv = g(ivt + 0x18, 5)
print('ivt', hex(ivt), '+0x18..+0x28', H(iv))
assert iv == [0xC00812A8,0xC0081538,0xC0081958,0xC0081D28,0xC00AB768], 'item vtable changed'
assert fget == 0xC0085370
print('n = vt+0x1C'); n = c(iv[1], item)
idx = 0
if n:
    print('C00913F8(item,0xFFFF,n,0x80000001)'); idx = c(0xC00913F8, item, 0xFFFF, n, 0x80000001)
else:
    print('n==0, skip C00913F8')
print('C006D530(item,idx=%d)' % idx); ms = c(0xC006D530, item, idx)
print('vt+0x18 C00812A8(item,0)'); p = c(iv[0], item, 0)
print('  [p] raw =', H(g(p)))
print('vt+0x28 C00AB768(item,1,0)'); c(iv[4], item, 1, 0)
print('item words after', H(g(item, 8)))
gp = g(item + 0x18)[0]
print('gate ptr', hex(gp), 'word', H(g(gp)))
