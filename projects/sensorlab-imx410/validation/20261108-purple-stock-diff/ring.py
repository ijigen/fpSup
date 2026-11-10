#!/usr/bin/env python3
"""Decode the PURPLE TEST build's struct ap_rd (ver 2) from a raw dump of block + rec_delay.base_off (0x440 bytes).

    python3 -B ring.py out-purple-test/build-<ver>.json dump.bin        # -> one JSON line per REC start, oldest first

Offline helper: it reads files only.  Fields (README "The ring"): bits = toggles live for the take | stock row mode << 8
| refused << 16; sw = SetImgMode_s calls since the previous REC start | from << 8 | to << 16 | into-ours << 24.
"""
import json, struct, sys

NAMES = {1: 'TWIN', 2: 'NOWIN', 4: 'ROWS', 8: 'RWZM', 16: 'SBSTOCK'}


def decode(info, raw):
    rd = info['rec_delay']
    base = rd['base_off']
    hw = (rd['ring_off'] - base) // 4
    h = struct.unpack_from(f'<{hw}I', raw, 0)
    keys = 'magic ms ver n sleeps clamped rec_words nmax bits smode live refused commits sw_total'.split()
    head = dict(zip(keys, h))
    assert head['magic'] == 0x594C4452 and head['ver'] == 2 and head['rec_words'] == len(rd['rec_fields']), head
    n, recs = head['n'], []
    for k in range(max(0, n - rd['nmax']), n):
        i = k % rd['nmax']
        w = struct.unpack_from(f'<{rd["rec_words"]}I', raw, rd['ring_off'] - base + 4 * rd['rec_words'] * i)
        r = dict(zip(rd['rec_fields'], w))
        r['toggles'] = [v for b, v in NAMES.items() if r['bits'] & b]
        r['smode'] = r['bits'] >> 8 & 0xFF
        r['sw_n'], r['sw_from'], r['sw_to'], r['sw_ours'] = (r['sw'] & 0xFF, r['sw'] >> 8 & 0xFF, r['sw'] >> 16 & 0xFF,
                                                             r['sw'] >> 24)
        r['switched_at_rec'] = bool(r['sw_dt']) and r['sw_dt'] < 1_000_000 and r['sw_to'] == r['cur']   # < 1 s before t0
        r['arm_t1'] = (r['arm_us'] - r['t1']) & 0xFFFFFFFF if r['arm_us'] else None
        r['line0_dec'] = r['line0'] >> 16 & 0x3FFF
        recs.append(r)
    return head, recs


if __name__ == '__main__':
    info = json.load(open(sys.argv[1]))
    head, recs = decode(info, open(sys.argv[2], 'rb').read())
    print(json.dumps(head))
    for r in recs:
        print(json.dumps(r))
