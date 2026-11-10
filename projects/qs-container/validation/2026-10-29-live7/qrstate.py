# live7: SensorLab v0.4.0test st->qr readback via `mem get` (read_direct's window is refused here).
# st = block C55F8200 + state_off 78720 (build-0.4.0test.json); qr is st's last member: sizeof(st) 96952 - sizeof(qr) 49648 = +47304
# struct qr (slqs.c:183): on force group shows hides draws enc_ret why n scale x0 y0 | info[16] | obs{vt,st} | vt[8] | param[10] | code[40] | url[96]
import re, struct, subprocess, sys
FPSH = '/Users/dido/Developer.localized/SIGMAfp_re/fpSup/fp_usb_shell/host/fpsh'
Q = 0xC55F8200 + 78720 + 47304
def rd(a, n):
    out = subprocess.run([FPSH, f'mem get 0x{a:08X},,{n*4}'], capture_output=True, text=True, timeout=30).stdout
    return [int(x, 16) for x in re.findall(r'D:0x([0-9A-Fa-f]+)', out)]
w = rd(Q, 48) + rd(Q + 192, 34)
names = 'on force group shows hides draws enc_ret why n scale x0 y0'.split()
print(' '.join(f'{k}={v}' for k, v in zip(names, w)), 'qr@0x%X' % Q)
print('obs.vt=0x%X obs.st=0x%X vt3=0x%X' % (w[28], w[29], w[33]))
b = b''.join(struct.pack('<I', x) for x in w[48:])
print('code', b[:40].split(b'\0')[0].decode(errors='replace'))
print('url ', b[40:136].split(b'\0')[0].decode(errors='replace'))
