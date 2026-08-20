#!/usr/bin/env python3
"""Assemble camera/imu_snapshot.S, extract the position-independent blob, and
(optionally) inject + call + read it live over the shell daemon socket.

  python3 build_imu_snapshot.py            # just assemble, print words
  python3 build_imu_snapshot.py --live     # inject to 0xC072F200 + call + decode result
"""
import sys, pathlib, subprocess, tempfile, struct, time, argparse
sys.path.insert(0, '/Users/dido/Developer.localized/SIGMAfp_re/codex')
from build_stage5_autorun import extract_and_relocate, words

HERE = pathlib.Path('/Users/dido/Developer.localized/SIGMAfp_re/codex/fpshell_tool')
CODE = 0xC072F200
RESULT = 0xC072F300

def build():
    with tempfile.TemporaryDirectory() as d:
        obj = pathlib.Path(d)/'i.o'
        r = subprocess.run(['clang','-target','armv7-none-eabi','-c',
                            str(HERE/'camera/imu_snapshot.S'),'-o',str(obj)],
                           capture_output=True, text=True)
        if r.returncode: sys.stderr.write(r.stderr); sys.exit(1)
        code = extract_and_relocate(obj)
    w = words(code)
    end = CODE + len(code)
    assert end <= RESULT, f"blob overruns RESULT: end 0x{end:08X} > 0x{RESULT:08X}"
    return w, end

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--live', action='store_true')
    ap.add_argument('--socket', default='/tmp/fpshell.sock')
    a = ap.parse_args()
    w, end = build()
    print(f"blob: {len(w)} words @0x{CODE:08X}..0x{end:08X}  result@0x{RESULT:08X}")
    for i, x in enumerate(w):
        print(f"mem set 0x{CODE+i*4:08X} 0x{x:08X}")
    if not a.live:
        return
    sys.path.insert(0, str(HERE/'monitor'))
    import fpstate as F
    sh = F.Shell(a.socket, mock=False)
    print("\n-- injecting blob --")
    for i, x in enumerate(w):
        sh._set_mem(CODE + i*4, x)
    print("-- call + read result --")
    t0 = time.time()
    sh._call(CODE)
    raw = sh.read_mem(RESULT, 0x18)
    dt = (time.time()-t0)*1000
    magic = struct.unpack_from('<I', raw, 0x14)[0]
    ax, ay, az = struct.unpack_from('<hhh', raw, 0)
    head = struct.unpack_from('<I', raw, 8)[0]
    gx, gy, gz = struct.unpack_from('<hhh', raw, 0x0C)
    print(f"magic  0x{magic:08X} {'OK' if magic==0x494D5530 else 'BAD'}")
    print(f"accel  raw ({ax},{ay},{az})  g ({ax/1024:.3f},{ay/1024:.3f},{az/1024:.3f})  |g|={ (ax*ax+ay*ay+az*az)**0.5/1024:.3f}")
    print(f"gyro   head=0x{head:04X}  raw ({gx},{gy},{gz})  dps ({gx/131:.1f},{gy/131:.1f},{gz/131:.1f})")
    print(f"call+read = 2 transactions, {dt:.0f}ms")

if __name__ == '__main__':
    main()
