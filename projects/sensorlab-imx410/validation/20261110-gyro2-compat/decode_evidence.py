#!/usr/bin/env python3
"""Decode Gyro2 FSG2 blocks in Sensor Lab DNGs (offline) and compare with the DNG's own tags.
python3 -B decode_evidence.py DNG...        (default: the 2026-11-02 hirate media)
python3 -B decode_evidence.py --take DIR    every DNG of one take, in order: tiling / mark / Vd checks"""
import pathlib, struct, sys
ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'projects/gyro2-sup'))
import fsg2

def tags(buf):
    root_at = struct.unpack_from('<I', buf, 4)[0]
    e = fsg2.ifd_entries(buf, root_at)
    def val(t):
        ty, c, v = e[t]
        if ty == 3 and c <= 2: return [v & 0xFFFF, v >> 16][:c]
        if ty == 4 and c == 1: return [v]
        if ty in (3, 4): return list(struct.unpack_from('<%d%s' % (c, 'H' if ty == 3 else 'I'), buf, v))
        if ty in (5, 10): return list(struct.unpack_from('<%dI' % (2 * c), buf, v))
        return None
    out = {}
    for name, t in (('w', 256), ('h', 257), ('crop_origin', 0xC61F), ('crop_size', 0xC620), ('frame_rate', 0xC764)):
        if t in e: out[name] = val(t)
    return out

def main(paths):
    for p in paths:
        buf = pathlib.Path(p).read_bytes()
        t = tags(buf)
        try:
            r = fsg2.read_frame(buf)
        except Exception as ex:
            print(f'{pathlib.Path(p).name}: no FSG2 ({ex}); {t}')
            continue
        fr = t.get('frame_rate')
        fps = fr[0] / fr[1] if fr else None
        print(f"{pathlib.Path(p).name}: writer {r['writer']} mode {r['mode_id']} hmax {r['hmax']} read_w {r['read_w']} "
              f"lines {r['lines']} bin {r['bin_h']}x{r['bin_v']} -> readout {r['readout_ns']/1000:.1f} us, "
              f"crop {r['crop_x']},{r['crop_y']},{r['crop_w']}x{r['crop_h']}; focal {r['calib_focal']}; "
              f"seq {r['frame_seq']} n {r['n_samples']} ev {r['n_events']} flags {r['flags']:#x}; "
              f"DNG {t.get('w')}x{t.get('h')} dcrop {t.get('crop_size')} fps {fps}")

def take(d):
    fs = sorted(pathlib.Path(d).glob('*.DNG'))
    prev, bad, vds = None, 0, []
    fps = None
    for f in fs:
        buf = f.read_bytes()
        try:
            r = fsg2.read_frame(buf)
        except Exception as ex:
            print(f'{f.name}: NO BLOCK ({ex})'); bad += 1; continue
        if fps is None:
            fr = tags(buf).get('frame_rate'); fps = fr[0] / fr[1] if fr else None
        mark = r['frame_mark'] - 65536 if r['frame_mark'] >= 32768 else r['frame_mark']
        msg = []
        if mark < 0: msg.append(f'mark {mark} < 0 (stream ahead of the frame)')
        if prev and r['base_idx'] != prev['base_idx'] + prev['n_samples']: msg.append('blocks do not tile')
        if prev and (r['mode_id'], r['hmax'], r['read_w'], r['lines']) != (prev['mode_id'], prev['hmax'], prev['read_w'], prev['lines']):
            msg.append('mode changed')
        if r['flags'] & fsg2.F_LOST: msg.append('LOST')
        vds += [r['base_idx'] + e[0] for e in r['events'] if e[1] == 3]
        if msg: bad += 1; print(f'{f.name}: seq {r["frame_seq"]} base {r["base_idx"]} n {r["n_samples"]}: ' + '; '.join(msg))
        prev = r
    if len(vds) > 2 and fps:
        vds = sorted(set(vds)); d = (vds[-1] - vds[0]) / (len(vds) - 1)
        print(f'Vd: {len(vds)} events, mean spacing {d:.3f} samples; DNG fps {fps:.4f} -> {2499.466 / fps:.3f} expected')
    print(f'{len(fs)} frames, {bad} flagged')

if __name__ == '__main__':
    if sys.argv[1:2] == ['--take']:
        take(sys.argv[2]); sys.exit(0)
    d = ROOT / 'projects/sensorlab-imx410/validation/20261102-hirate-playback-diagnosis/media'
    main(sys.argv[1:] or sorted(map(str, d.glob('*.DNG'))))
