"""Run unchanged V5.02 CinemaDNG playback ring creation, offline only.

Native: loop, descriptor constructor/copy, queue insertion and count updates.
Models: pool allocation success count, locks/interrupts, empty XMP object,
memcpy/memset. No physical memory availability, decoder, timing or camera I/O.
The boundary is the actual requested allocation, not Unicorn's mapped region.
"""
from pathlib import Path
import hashlib
import json
import struct
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_PC, UC_ARM_REG_SP, UC_ARM_REG_LR

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
IMAGE = (ROOT/'out/MAIN_c0000000.bin').read_bytes()
ENTRY, END = 0xC05C2D10, 0xC05C2E90
RAM, DESCRIPTORS, DONE = 0x45000000, 0x46000000, 0x47000000
CAPACITY_BYTES, STRIDE = 0x6F090, 0x5EC
SERVICES = {
    0xC0010298: 'lock', 0xC00102D0: 'unlock',
    0xC001CCE0: 'interrupt_lock', 0xC001CD18: 'interrupt_unlock',
    0xC001CF78: 'pool', 0xC001D1E8: 'allocate',
    0xC0015058: 'memset', 0xC0014DAC: 'memcpy',
    0xC00560C0: 'empty_xmp_init', 0xC00CB7E0: 'empty_xmp_destroy',
    0xC0011100: 'assert',
}
NATIVE = ((ENTRY, END), (0xC05C3370, 0xC05C33B8),
          (0xC05C3438, 0xC05C35A0), (0xC05C3638, 0xC05C3718))


def replay(file_bytes, successful_allocations):
    u = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    u.mem_map(0xC0000000, 0x03000000)
    u.mem_write(0xC0000000, IMAGE[:0x03000000])
    u.mem_map(RAM, 0x20000)
    u.mem_map(DESCRIPTORS, 0x100000)
    u.mem_map(DONE, 0x1000)
    canary = bytes([0xA5])*0x1000
    u.mem_write(DESCRIPTORS+CAPACITY_BYTES, canary)
    allocations, overflows, seen_services = [], [], set()
    successes = 0
    def r(reg): return u.reg_read(reg)
    def ret(value=0):
        u.reg_write(UC_ARM_REG_R0, value)
        u.reg_write(UC_ARM_REG_PC, r(UC_ARM_REG_LR))
    def code(mu, a, sz, _):
        nonlocal successes
        if a == DONE: mu.emu_stop(); return
        if a not in SERVICES:
            assert any(lo <= a < hi for lo, hi in NATIVE), f'unmodeled native call {a:08x}'
            return
        n = SERVICES[a]; seen_services.add(n)
        r0, r1, r2 = r(UC_ARM_REG_R0), r(UC_ARM_REG_R1), r(UC_ARM_REG_R2)
        if n == 'assert': raise AssertionError(f'native assert line {r1}')
        if n == 'pool': assert r0 in (10, 11); ret(r0); return
        if n == 'allocate':
            if r0 == 11:
                assert r1 == CAPACITY_BYTES
                ptr = DESCRIPTORS
            else:
                assert r0 == 10 and r1 == (file_bytes+0x1FFF)&~0xFFF
                ptr = 0x50000000+successes*r1 if successes < successful_allocations else 0
                successes += bool(ptr)
            allocations.append(dict(pool=r0, bytes=r1, pointer=ptr))
            ret(ptr); return
        if n == 'memset': mu.mem_write(r0, bytes([r1&255])*r2)
        if n == 'memcpy': mu.mem_write(r0, bytes(mu.mem_read(r1, r2)))
        ret(r0 if n in ('memset', 'memcpy') else 0)
    def write(mu, access, a, size, value, _):
        if DESCRIPTORS+CAPACITY_BYTES <= a < DESCRIPTORS+0x100000:
            if not overflows:
                overflows.append(dict(pc=f'{r(UC_ARM_REG_PC):08x}', address=f'{a:08x}',
                                      bytes=size, completed_descriptors=struct.unpack('<I',mu.mem_read(RAM+4,4))[0]))
    u.hook_add(UC_HOOK_CODE, code)
    u.hook_add(UC_HOOK_MEM_WRITE, write)
    u.reg_write(UC_ARM_REG_SP, RAM+0x1F000)
    u.reg_write(UC_ARM_REG_LR, DONE)
    u.reg_write(UC_ARM_REG_R0, RAM)
    u.reg_write(UC_ARM_REG_R1, file_bytes)
    u.emu_start(ENTRY, DONE, count=2_000_000)
    assert r(UC_ARM_REG_PC) == DONE, 'instruction cap reached'
    completed = struct.unpack('<I',u.mem_read(RAM+4,4))[0]
    actual_canary = bytes(u.mem_read(DESCRIPTORS+CAPACITY_BYTES,len(canary)))
    changed = sum(a!=b for a,b in zip(canary,actual_canary))
    assert completed == successful_allocations
    assert bool(overflows) == (successful_allocations > CAPACITY_BYTES//STRIDE)
    assert bool(changed) == bool(overflows)
    return dict(file_bytes=file_bytes, modeled_successful_raw_allocations=successful_allocations,
                descriptor_allocation=allocations[0], descriptor_stride=STRIDE,
                descriptor_capacity=CAPACITY_BYTES//STRIDE, completed_descriptors=completed,
                raw_request_bytes=allocations[1]['bytes'], raw_total_bytes=successes*allocations[1]['bytes'],
                canary_changed_bytes=changed, first_out_of_bounds_write=overflows,
                native_returned=True, services=sorted(seen_services))


if __name__ == '__main__':
    rows = []
    for file_bytes, count in ((183808,299),(183808,300),(183808,301),
                              (182784,301),(1097216,301),(4*1024*1024,77)):
        row = replay(file_bytes,count);rows.append(row)
        print(json.dumps(row),flush=True)
    result = dict(firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
                  native_function_sha256=hashlib.sha256(IMAGE[ENTRY-0xC0000000:END-0xC0000000]).hexdigest(),
                  hardware_tested=False, physical_pool_availability_modeled=True, cases=rows)
    (HERE/'native-ring-result.json').write_text(json.dumps(result,indent=2)+'\n')
