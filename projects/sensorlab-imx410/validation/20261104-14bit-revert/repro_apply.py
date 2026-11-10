#!/usr/bin/env python3
"""14-bit -> 12-bit after a few takes: what the apply unit does across REC cycles (offline, unicorn, test_apply.Cam).

    SL_ROOT=<repo> python3 -B repro_apply.py [<apply dir>]

Read-only: imports apply/test_apply.py (from the given apply dir, default ../../apply) and drives the real ap.c hooks.
Per scenario it prints, after every take: active / cur / pid, the TAB3 answer (ours or stock), the record canvas plane
codes (+0x80/+0x84: 7/8 = 14-bit record plane, 7/7 = 12-bit), the BlackLevel bits hook (14 / 12), and what a
"leave() after the take" (same selection) and a "nudge" (different selection, then back) return.
"""
import os, pathlib, sys
from fractions import Fraction

APPLY = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else pathlib.Path(__file__).resolve().parents[2] / 'apply')
sys.path.insert(0, str(APPLY))
os.chdir(APPLY)
import test_apply as T                                      # noqa: E402
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_SP  # noqa: E402

REC = T.MOVREC_DEFAULT & ~3, 1 << (8 * (T.MOVREC_DEFAULT & 3))


def blk(c, site, field):
    obj = 0xC3E09000
    c.put(obj + field, 0)
    c.mu.reg_write(UC_ARM_REG_R0, obj)
    c.mu.reg_write(UC_ARM_REG_SP, T.STACK - 0x2004)
    c.mu.emu_start(site, site + 8, count=10000)
    return c.r(UC_ARM_REG_R0)


def state(c, key):
    st = c.status()
    ans = c.call(T.PICKER, 0, T.TAB3, c.key(key))
    ours = T.MEM <= ans < T.MEM + T.AP_MEM
    g = c.canvas(st['pid']) if st['active'] else None
    planes = (g[0x80 // 4], g[0x84 // 4]) if g else None
    return dict(active=st['active'], cur=st['cur'], mode=st['mode_id'], ours=ours, planes=planes,
                blk=(blk(c, 0xC02CA1BC, 0x24), blk(c, 0xC02CA218, 0x08)), result=st['result'], owed=st['owed'],
                commits=st['commits'], carrier=st['carrier'])


def take(c, key, between=None):
    """one take as test_apply.rec_start models it: standby TAB3, REC flag up, TAB3 again, (between), the DNG header's
    BlackLevel bits, REC flag down, the LV's standby TAB3"""
    c.call(T.PICKER, 0, T.TAB3, c.key(key))
    c.put(*REC)
    c.call(T.PICKER, 0, T.TAB3, c.key(key))
    if between:
        between(c)
    b = (blk(c, 0xC02CA1BC, 0x24), blk(c, 0xC02CA218, 0x08))
    c.put(REC[0], 0)
    return b


def run(name, sel, key, n=4, between=None, after=None):
    print(f'\n== {name}')
    c = T.Cam()
    c.init()
    rc = c.apply(sel)
    print('commit', rc, state(c, key))
    for i in range(1, n + 1):
        b = take(c, key, between)
        if after:
            after(c, i)
        same = c.apply(sel)                                    # leave() after the take: the same selection
        print(f'take {i}: rec-time BlackLevel bits {b}; leave(same) -> {same}; {state(c, key)}')
    nudge = dict(sel, vmax=sel['vmax'] + 1)
    print('nudge ->', c.apply(nudge), 'back ->', c.apply(sel), state(c, key))


def main():
    for args in ((6048, 2540, 6048, 2540), (6048, 2240, 6048, 2240)):
        sel, case, *_ = T.recipe(*args, '1x1', 14, fps=Fraction(25))
        print('\n#### recipe', args, '1x1 14b 25p', {k: sel[k] for k in ('key', 'hm', 'vmax')})
        run('A: plain takes', sel, 'UHD25')
        # B: a non-matching picker call inside the take (another table / key / the MOV standby when sby = 0)
        run('B: a MOV standby query during the take', sel, 'UHD25',
            between=lambda c: c.call(T.PICKER, 0, T.TABS, c.key('MOV_UHD25')))
        run('B2: a TAB3 query with another key during the take', sel, 'UHD25',
            between=lambda c: c.call(T.PICKER, 0, T.TAB3, c.key('UHD30')))
        # C: the stock frame-rate enum moves after take 2 (2 = 25 -> 3 = 29.97), the firmware key follows it
        def drift(c, i):
            if i == 2:
                c.fr = 3
        c_key = {'k': 'UHD25'}
        print('\n== C: stock rate enum drifts after take 2 (key UHD30 from then on)')
        c = T.Cam(); c.init(); print('commit', c.apply(sel), state(c, 'UHD25'))
        for i in range(1, 5):
            take(c, c_key['k'])
            drift(c, i)
            if c.fr == 3:
                c_key['k'] = 'UHD30'
            print(f'take {i}: leave(same) -> {c.apply(sel)}; {state(c, c_key["k"])}')
        print('nudge ->', c.apply(dict(sel, vmax=sel['vmax'] + 1)), 'back ->', c.apply(sel), state(c, 'UHD25'),
              'fr', c.fr)


if __name__ == '__main__':
    main()
