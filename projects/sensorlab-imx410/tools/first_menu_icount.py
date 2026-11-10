"""Scratch: the v0.7 timing words with the firmware tick replaced by an executed-instruction counter (block sizes),
so each word is an instruction count of that phase in the offline rig (native services are Python stubs: 0)."""
import sys, struct
sys.path[:0] = ['/Users/dido/Developer.localized/SIGMAfp_re/projects/sensorlab-imx410/menu',
                '/Users/dido/Developer.localized/SIGMAfp_re/projects/sensorlab-imx410/qs']
from unittest.mock import patch
import test_slqs as S, runtime_camera as RC
from unicorn import UC_HOOK_BLOCK, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_PC, UC_ARM_REG_LR
Q = S.Q1
n = [0]
def prep(cam):
    S.ap_firmware(cam, False)
    cam.mu.hook_add(UC_HOOK_BLOCK, lambda uc, a, size, d: n.__setitem__(0, n[0] + max(1, size // (2 if a & 1 else 4))))
    def tick(uc, a, size, d):
        uc.reg_write(UC_ARM_REG_R0, n[0] & 0xFFFFFFFF); uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
    cam.mu.hook_add(UC_HOOK_CODE, tick, begin=0xC002B6E0, end=0xC002B6E0)
with patch.object(Q, 'Cam', RC.Cam):
    c = Q.boot([(Q.CNAME, Q.cblob()[0]), (S.BS.file_name(), S.blob()[0])], prepare=prep)
c.layout()
lt = struct.unpack('<16I', bytes(c.mu.mem_read(S.sqt(c, 29), 64)))
tm = struct.unpack('<12I', bytes(c.mu.mem_read(S.sqt(c, 31), 48)))
M = lambda x: f'{x/1e6:6.2f} M  ~{x/1e6/0.6:5.1f}-{x/1e6/0.3:5.1f} ms'
rows = [('first layout, whole container hook', tm[10]), ('  container collection (qc_freeze)', tm[2] - tm[1]),
        ('  container slot write-back', tm[6]), ('  leave() of all clients', tm[4] - tm[3]),
        ('    SensorLab leave() total', lt[0]), ('      apply push (boot restore)', lt[1]), ('      ap_idle', lt[2]),
        ('      menu bridge (slm_idle)', lt[3]), ('        setup total', lt[14]), ('        fpui_stock_apply', lt[12]),
        ('        both slm_model', lt[13]), ('      record write', lt[4]), ('  stock layout loader (stubbed)', tm[5] - tm[4]),
        ('second layout (whole)', None)]
c.layout()
tm2 = struct.unpack('<12I', bytes(c.mu.mem_read(S.sqt(c, 31), 48)))
for name, v in rows:
    print(f'{name:40s} {M(v if v is not None else tm2[9])}')
print('ms = instructions / (300..600 per us): Cortex-A9 cached, IPC ~0.5-1 at ~600 MHz -- an estimate, not a measurement')
