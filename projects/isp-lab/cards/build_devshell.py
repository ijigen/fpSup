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


def main():
    rel = B.shell_sup(burst15=True)
    dev = B.from_v3(B.V3.shell_sup(ep_patches=True, burst15=True), name=names_v4.display('SHEL'), flags=0)
    name = names_v4.file_name('SHEL')
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
