"""Read LV Boost v0.2 diagnostics over the existing fp USB shell.

No camera settings, hooks, or files are changed. The GUI getter provides the
owned allocation address; never scan arbitrary camera RAM for a magic word.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'fp_usb_shell'))


def resident(getter):
    low, high = getter
    if low & 0xFFF0F000 != 0xE3002000 or high & 0xFFF0F000 != 0xE3402000:
        raise ValueError('Unexpected GUI getter; no diagnostic memory was read')
    imm = lambda w: ((w >> 4) & 0xF000) | (w & 0xFFF)
    return (imm(high) << 16 | imm(low)) - 0x98


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    from putfile import mem_get, sh
    addr = resident(mem_get(0xC06C07CC, 2))
    if mem_get(addr, 1) != [int.from_bytes(b'FLF1', 'little')]:
        raise SystemExit('LV Boost is not installed at the GUI allocation')
    words = mem_get(addr + 0x1C, 13)
    names = ('gain_calls', 'last_gain_app', 'tone_calls', 'last_context',
             'last_pq_color', 'last_channels', 'last_stock_pointer',
             'last_tone_app', 'last_flag', 'last_variant', 'lift_applications',
             'last_lift_pointer', 'last_lv_attribute')
    result = dict(zip(names, words))
    result.update(resident=hex(addr), app_status=sh('status get app_current'),
                  lv_attribute=sh('status get app_lv_attribute'),
                  selected=mem_get(addr + 4, 1)[0],
                  level=mem_get(addr + 0x1A4, 1)[0] + 1)
    startup = mem_get(addr + 0x50, 3)
    result.update(startup_state=startup[0], startup_task=startup[1],
                  startup_task_result=startup[2])
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
