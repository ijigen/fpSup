#!/usr/bin/env python3
"""The v4 USB shell with EP 0x83 shaped for the push engine (dev cards only).

Same build as the released shell (loader-v4 build_v4.shell_sup(burst15=True),
ports.py), plus fp_usb_shell/patches.py PUSH: EP 0x83 interrupt/64 -> bulk/1024,
burst 3.  The v4 owner confirmed 10-25 the release leaves PUSH out on purpose;
this file changes nothing shared.  The patches take effect only if the camera
enumerates AFTER the sup loaded: boot, then plug the cable.

    build_devshell.py      -> cards/<shell file name> + devshell.json (diff vs the release build)
"""
import hashlib, json, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
V4 = ROOT / 'fpSup' / 'loader-v4'
sys.path[:0] = [str(V4), str(ROOT / 'fpSup' / 'fp_usb_shell' / 'v3'), str(ROOT / 'fpSup' / 'fp_usb_shell')]
import build_v4 as B, names_v4                                   # noqa: E402
import patches                                                   # noqa: E402

# 2026-10-27 (validation/20261027-report-take-01): patches.PUSH alone is not enough. FUN_c00327b8 runs at USB
# init and on every (re)connect and forces each interface's THIRD endpoint (EP 0x83) to an interrupt shape --
# MPS 64, bInterval 11 (FS: 100) -- in the RAM copy of the descriptors (0xC3774820.., built by FUN_c04e9148 from
# 0xC0CF37xx), whatever the template says; it never touches bmAttributes, so the host saw "bulk, 64, 11".
# These five ARM immediates make that branch write a bulk shape instead (control flow unchanged). A RAM copy
# built before this sup loaded is not patchable here (patch_sup takes image addresses only, to restore them):
# the next (re)connect re-runs FUN_c00327b8 and writes it right.
USBFIX = [
    (0xC0032808, 0xE3A03B01, "FUN_c00327b8 SS: 3rd endpoint MPS mov r3,#0x40 -> #0x400"),
    (0xC0032814, 0xE3A03000, "FUN_c00327b8 SS: 3rd endpoint bInterval mov r3,#0xb -> #0"),
    (0xC0032850, 0xE3A03C02, "FUN_c00327b8 HS: 3rd endpoint MPS mov r3,#0x40 -> #0x200"),
    (0xC003285C, 0xE3A03000, "FUN_c00327b8 HS: 3rd endpoint bInterval mov r3,#0xb -> #0"),
    (0xC003289C, 0xE3A03000, "FUN_c00327b8 FS: 3rd endpoint bInterval mov r3,#100 -> #0"),
]
USBFIX_OLD = {0xC0032808: 0xE3A03040, 0xC0032814: 0xE3A0300B, 0xC0032850: 0xE3A03040,
              0xC003285C: 0xE3A0300B, 0xC003289C: 0xE3A03064}   # the 5.02 image, checked before building


def main():
    import struct
    usbfix = '--no-usbfix' not in sys.argv      # bisect (2026-10-27): the shell take-03 worked with
    img = (ROOT / 'out' / 'MAIN_c0000000.bin').read_bytes()
    for a, old in USBFIX_OLD.items():
        got, = struct.unpack_from('<I', img, a - 0xC0000000)
        if got != old:
            raise SystemExit(f'{a:#x} is {got:#x} in the image, expected {old:#x}: not fp 5.02?')
    rel = B.shell_sup(burst15=True)
    saved = patches.PUSH
    patches.PUSH = saved + (USBFIX if usbfix else [])
    try:
        dev = B.from_v3(B.V3.shell_sup(ep_patches=True, burst15=True), name=names_v4.display('SHEL'), flags=0)
    finally:
        patches.PUSH = saved
    name = names_v4.file_name('SHEL')
    if not usbfix:
        (HERE / 'nousbfix').mkdir(exist_ok=True)
        (HERE / 'nousbfix' / name).write_bytes(dev)
        print(json.dumps({'nousbfix': len(dev), 'sha256': hashlib.sha256(dev).hexdigest()}))
        return
    (HERE / name).write_bytes(dev)
    diff = [i for i in range(min(len(rel), len(dev))) if rel[i] != dev[i]]
    rep = {'file': name, 'bytes': len(dev), 'release_bytes': len(rel),
           'sha256': hashlib.sha256(dev).hexdigest(), 'release_sha256': hashlib.sha256(rel).hexdigest(),
           'differing_bytes': len(diff) + abs(len(rel) - len(dev)),
           'first_diff': diff[0] if diff else None}
    (HERE / 'devshell.json').write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep))


if __name__ == '__main__':
    main()
