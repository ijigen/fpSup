#!/usr/bin/env python3
"""Read what the fpLossless card recorded, after a take.

    python3 -B lossless/card_status.py --layout <build>/layout.json --dry-run
    python3 -B lossless/card_status.py --layout <build>/layout.json

THIS READS CAMERA MEMORY (reads only; nothing is ever written). --dry-run
prints exactly what would be read and reads nothing.

What it reads: the cave arena 0xC072E064..0xC072EFB4 (to find the card's
48-byte record, whose word +32 is "FLPC"), then scalar fields and bounded
arrays at offsets the ARM build itself reported in layout.json.
"""
import argparse
import json
import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'fp_usb_shell'))

ARENA, ARENA_END = 0xC072E064, 0xC072EFB4
MAGIC = 0x43504C46                      # "FLPC"
ARRAY_WORDS = {'hold.refused_by': 8, 'play.refused_by': 12, 'hold.job.stall_regs': 8,
               'hold_b.job.stall_regs': 8, 'record_diag.drops': 16 * 15}


def find_record(mem_get):
    words = mem_get(ARENA, (ARENA_END - ARENA) // 4)
    for i in range(0, len(words) - 12):
        if words[i + 8] == MAGIC:
            block = ARENA + 4 * i
            state, base = words[i + 9], words[i + 10]
            # 0x4xxxxxxx: the loader's NonCacheBuffer block; 0xCxxxxxxx: the
            # same memory's cached alias, where the card runs since 2026-10-13
            cached = 0xC4000000 <= base < 0x100000000
            if (0x40000000 <= base < 0x80000000 or cached) and base < state and not base & 7:
                return block, state, base
    return None



def read_words(at, nbytes):
    """read_direct's DMA reaches only CPU-0x40000000 addresses. A cached-alias
    state (0xC4.. and up) is read word by word through the shell's CPU reads:
    slower, but coherent with the cache, and nothing outside its reach."""
    import struct
    if at < 0x80000000:
        from putfile import read_direct
        return read_direct(at, nbytes)
    from putfile import mem_get
    words = []
    for off in range(0, nbytes, 1024):
        words += mem_get(at + off, min(256, (nbytes - off + 3) // 4))
    return struct.pack(f'<{len(words)}I', *words)


LANE = {0: 'idle', 1: 'held', 2: 'running', 3: 'finished', 4: 'collecting', 5: 'fault'}


def print_trace(at, n, out):
    """Per arrival: time, arrivals, writer flushes, descriptors free, lanes,
    then the registry: lock byte, occupied slots, and the oldest occupied
    frame's state / live children / duplicates / parent. arrivals - flushed =
    frames the writer has not written yet; REC stops at descriptors free <= 1."""
    import struct
    raw = read_words(at, 32 * n)
    rows = [struct.unpack_from('<8I', raw, 32 * i) for i in range(n)]
    t0 = rows[0][0]
    lines = ['ms,arrivals,flushed,unwritten,desc_free,lane_a,lane_b,reg_lock,occupied,'
             'oldest_state,oldest_children,oldest_dups,oldest_parent']
    for t, arr, fl, w, r0, st, ch, par in rows:
        lines.append(f'{(t - t0) / 1000:.1f},{arr},{fl},{arr - fl},{w & 0xffff},'
                     f'{LANE.get((w >> 16) & 0xff, (w >> 16) & 0xff)},'
                     f'{LANE.get(w >> 24, w >> 24)},{r0 & 0xff},{r0 >> 8},'
                     f'0x{st:X},{ch & 0xffff},{ch >> 16},{par - (1 << 32) if par >> 31 else par}')
    if out:
        out.write_text('\n'.join(lines) + '\n')
    print(f'\ntrace: {n} arrivals' + (f' -> {out}' if out else ''))
    step = max(1, n // 16)
    for line in [lines[0]] + lines[1::step] + ([lines[-1]] if (n - 1) % step else []):
        print('  ' + line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--layout', type=pathlib.Path, required=True)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--elog', type=pathlib.Path,
                    help='also write the native event log (card.c FPL_ELOG) here as CSV')
    ap.add_argument('--trace', type=pathlib.Path,
                    help='also write the per-arrival trace (card.c FPL_TRACE) here as CSV')
    ap.add_argument('--state', type=lambda s: int(s, 0),
                    help='the card state address, if already known (skips the scan)')
    a = ap.parse_args()
    layout = json.loads(a.layout.read_text())
    fields = layout['fields']
    if a.dry_run:
        print('would read (nothing written):')
        if a.state is None:
            print(f'  0x{ARENA:08X}..0x{ARENA_END:08X}  the cave arena, '
                  f'{(ARENA_END - ARENA) // 4} words, to find the "FLPC" record')
            print('  then the stated number of words at <state> + each offset below')
        else:
            print(f'  the stated number of words at 0x{a.state:08X} + each offset below')
        for name, off in fields.items():
            print(f'    +0x{off:04X}  {name}  ({ARRAY_WORDS.get(name, 1)} words)')
        return 0

    from putfile import mem_get
    if a.state is None:
        found = find_record(mem_get)
        if not found:
            print('no FLPC record in the cave: the card did not arm (or is not loaded)')
            return 1
        block, state, base = found
        print(f'record at 0x{block:08X}: state 0x{state:08X}, resident base 0x{base:08X}')
    else:
        state = a.state
    arrays = ARRAY_WORDS
    v = {name: mem_get(state + off, 1)[0] for name, off in fields.items()
         if name not in arrays and name not in ('trace', 'elog')}
    arr = {name: mem_get(state + fields[name], n) for name, n in arrays.items() if name in fields}
    for name, value in v.items():
        print(f'  {name:42s} {value:>12}  0x{value:08X}')
    why = ['descriptor', 'reserve', 'handle', 'raster', 'short', 'output', 'no promise slot', '-']
    turned = {why[i]: n for i, n in enumerate(arr.get('hold.refused_by', [])) if n}

    if 'trace' in fields and v.get('trace_n'):
        print_trace(state + fields['trace'], min(v['trace_n'], 512), a.trace)
    if 'elog' in fields and v.get('elog_n') and a.elog:
        import struct
        n = min(v['elog_n'], 2048)
        raw = read_words(state + fields['elog'], 8 * n)
        rows = [struct.unpack_from('<2I', raw, 8 * i) for i in range(n)]
        t0 = rows[0][0]
        a.elog.write_text('ms,kind,slot,result,state\n' + ''.join(
            f'{(t - t0) / 1000:.1f},{"W" if (w & 0xff) == 0x57 else w & 0xff},'
            f'{(w >> 8) & 0xff},{(w >> 16) & 0xff},0x{w >> 24:X}\n' for t, w in rows))
        print(f'\nevent log: {n} records -> {a.elog}')
    print('\nreading:')
    if v['magic'] != 0x44524143:
        print('  the state is not initialised: the launcher never reached init')
        return 1
    menu = {0: 'never tried', 1: 'INSTALLED', 2: 'no GUI', 3: 'no MainB2 screen',
            4: 'reader not stock', 5: 'no MainB2 entry', 6: 'no room', 7: 'no menu data',
            8: 'menu data damaged', 9: 'registration failed', 10: 'variable not usable',
            11: 'shared string pool refused'}
    print(f'  menu row: {menu.get(v["menu.result"], v["menu.result"])}; takes left stock '
          f'because OFF {v["rec_menu_off"]}')
    w, h, bits = (v['rec.facts.seen.width'], v['rec.facts.seen.height'],
                  v['rec.facts.seen.bits'])
    if w and h and bits:
        print(f'  producer {w}x{h} {bits}-bit, raster {v["rec.facts.seen.raster"]:,} B')
    tid = v['task_id'] - (1 << 32) if v['task_id'] & 0x80000000 else v['task_id']
    lanes = ['hold'] + (['hold_b'] if v['hold_b.magic'] else [])
    print(f'  takes admitted {v["rec_admitted"]}, recorded RAW {v["rec_raw"]}; codec task '
          + (f'id {tid}' if tid > 0 else 'none (compression unavailable)') + '; second lane '
          + ('ON' if v['hold_b.magic'] else f'off (failed {v["lane_b_failed"]})'))
    held = sum(v[f'{x}.held'] for x in lanes)
    print(f'  frames reaching the lossless hook {v["take_frames"]}: held {held}, compressed '
          f'{sum(v[f"{x}.compressed"] for x in lanes)}, passed because both lanes busy '
          f'{v["hold.lanes_full"]}, not eligible {v["hold.not_eligible"]}'
          + (f' {turned}' if turned else ''))
    print(f'  engine refused {sum(v[f"{x}.refused"] for x in lanes)}, no saving '
          f'{sum(v[f"{x}.no_benefit"] for x in lanes)}, faults '
          f'{sum(v[f"{x}.faults"] for x in lanes)}; header DMA refused '
          f'{sum(v[f"{x}.dma_failed"] for x in lanes)}')
    stalls = sum(v[f'{x}.stalls'] for x in lanes)
    print(f'  engine jobs given up on (never finished): {stalls}'
          + ''.join(f'; {x} registers 0000/04/08/0C/64/74/F8/3FC '
                    + ' '.join(f'{r:08X}' for r in arr.get(f'{x}.job.stall_regs', []))
                    for x in lanes if v[f'{x}.stalls']))
    print(f'  zero copy: swapped {sum(v[f"{x}.swapped"] for x in lanes)}, declined '
          f'{v["hold.swap_declined"]}, undone {v["hold.swap_undone"]}; spare '
          f'{v["spare_bytes"]:,} B, failed {v["spare_failed"]}, freed {v["spares_freed"]}')
    print(f'  stop: stops {v["stops"]}, finished {v["finishes"]}, busy {v["finish_busy"]}, '
          f'lanes now {v["hold.lane"]}/{v["hold_b.lane"]}, result {v["lane_stop_result"]}')
    pwhy = ['slot', 'not tiff', 'root', 'format', 'tiles', 'ifd0', 'room', 'order', 'scratch',
            'engine', 'copy', 'take live']
    if 'hold.job_max_us' in v:
        print(f'  codec job time: last {v["hold.job_last_us"] / 1000:.1f} ms, longest '
              f'{v["hold.job_max_us"] / 1000:.1f} ms (lane B {v["hold_b.job_last_us"] / 1000:.1f} / '
              f'{v["hold_b.job_max_us"] / 1000:.1f}); given up after '
              f'{v["hold.stall_limit_us"] / 1000:.0f} ms')
    if 'hold.job_count' in v:
        n = v['hold.job_count'] + v['hold_b.job_count']
        mean = (v['hold.job_sum_us'] + v['hold_b.job_sum_us']) / n / 1000 if n else 0
        print(f'  tile grid {v["hold.job.tile_width"]}x{v["hold.job.tile_height"]} '
              f'({v["hold.job.tiles"]} tiles; force 0x{v["tile_force"]:08X}); '
              f'mean codec job {mean:.2f} ms over {n} jobs')
    if 'bulk' in v:
        b = v['bulk']
        print(f'  file-layer bulk this take: {b:,} B ({b / 2**20:.1f} MiB'
              f'{", stock" if b == 0x4000000 else ""}); writer already open at REC: '
              f'{v["bulk_writer_open"]} (must be 0, or the value came too late)')
    print(f'  this take {v["take_frames"]} frames (the first left uncompressed); clips opening '
          f'on a stock frame {v["play.clips_first_stock"]}')
    print(f'  clips opened {v["play.clips"]}, ours {v["play.clips_ours"]} (frame size '
          f'{v["play.clip_size_was"]:,} -> {v["play.clip_size_set"]:,}), header unread '
          f'{v["play.clip_failed"]}; scratch {v["play.scratch_bytes"]:,} B, failed '
          f'{v["play.scratch_failed"]}, freed {v["play.scratch_freed"]}')
    prefused = {pwhy[i]: n for i, n in enumerate(arr.get('play.refused_by', [])) if n}
    print(f'  playback: frames read {v["play.seen"]}, stock {v["play.stock"]}, decoded '
          f'{v["play.decoded"]} (last {v["play.last_us"] / 1000:.1f} ms, max '
          f'{v["play.max_us"] / 1000:.1f} ms)' + (f', left alone {prefused}' if prefused else '')
          + f'; last slot buffer 0x{v["play.last_buf"]:08X} capacity {v["play.last_cap"]:,} '
          f'read {v["play.last_got"]:,}')
    print(f'  before file write (not a write-success count): IFDs completed {v["flush.applied"]}, header not the take\'s '
          f'{v["flush.tag_failed"]}, other length {v["flush.length_mismatch"]}; '
          f'promises a previous take left {v["stale_promises"]}')
    if 'record_diag.writer_calls' in v:
        d = {k.removeprefix('record_diag.'): val for k, val in v.items()
             if k.startswith('record_diag.')}
        print(f'  native events: RAW errors {d["raw_errors"]}, capture limits '
              f'{d["capture_limits"]}, completion errors {d["completion_errors"]}, '
              f'missing registry slots {d["lookup_missing"]}')
        print(f'  last nonzero/missing event: event {d["last_event"]}, result '
              f'{d["last_result"]}, slot {d["last_slot"]}, generation '
              f'{d["last_generation"]}, state {d["last_state"]}, handle '
              f'0x{d["last_handle"]:08X}, missing {d["last_missing"]}')
        print(f'  native FIFO discarded {d["discard_count"]}: RAW error '
              f'{d["discard_raw"]}, completion error {d["discard_completion"]}, '
              f'teardown {d["discard_teardown"]}, other {d["discard_other"]}')
        result = d['writer_low'] | (d['writer_high'] << 32)
        print(f'  native writer returns: calls {d["writer_calls"]}, zero '
              f'{d["writer_zero"]}, nonzero {d["writer_nonzero"]}, last {result} bytes '
              '(API result, not proof of durable files)')
        drops = arr.get('record_diag.drops', [])
        used = min(d['drop_used'], 16)
        first = d['drop_next'] % 16 if used == 16 else 0
        print(f'  recent discarded files: {used} retained, {d["drop_overwritten"]} older '
              'records overwritten; slots are not file numbers')
        for n in range(used):
            at = ((first + n) % 16) * 15
            row = drops[at:at + 15]
            if len(row) != 15:
                break
            name = struct.pack('<12I', *row[3:]).split(b'\0', 1)[0].decode('utf-8', 'replace')
            print(f'    slot {row[0]}, generation {row[1]}, clear caller '
                  f'0x{row[2]:08X}, path {name!r}')
    return 0

if __name__ == '__main__':
    sys.exit(main())
