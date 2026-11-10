#!/usr/bin/env python3
"""Explicit one-shot H1 tap trial using the existing isolated BUFA0 capture.

Default prints the plan only. --run-live is required for camera operations.
Uses the known H1 tap through a0 rather than replacing the preview's BufA7 job.
No card writes or recording. Unknown completion retains allocations.
"""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[4]
IMXL = ROOT / 'projects/imx410-lab'
SHELL = ROOT / 'fpSup/fp_usb_shell'
SOURCE_H, SOURCE_V = 0xC31DF600, 0xC31DF604
MUX, H1, H2 = 0x300F06B0, 0x300F0840, 0x300F08C0
EXTRA_REGS = [SOURCE_H, SOURCE_V, 0x300F0004, 0x300F0800,
              *range(0x300F0810, 0x300F0824, 4), H1,
              *range(0x300F0850, 0x300F0860, 4), 0x300F0870,
              H2, 0x300F08C4]
STAGES = [('S0_crmf', 1, 0, 0), ('S1_h1_bypass', 3, 0, 0),
          ('S2_h1_div3_kernel0', 3, 1, 0),
          ('S3_h1_div3_kernel1', 3, 1, 1), ('S4_crmf_after', 1, 0, 0)]
SENTINEL = 0xCDCDCDCD


def driver(record, horizontal):
    if record not in (0, 1) or horizontal not in (0, 1):
        raise ValueError('only two native records and H1 bypass/div3')
    rom = (ROOT / 'out/seg0_c0000000.bin').read_bytes()
    off = 0xB5F770 + record * 0x38
    blob = bytearray(rom[off:off + 0x2C])
    assert len(blob) == 0x2C
    blob[0], blob[0x1A], blob[0x28] = 0, horizontal, 0
    return bytes(blob)


def validate_geometry(rows, words, full_bytes, allocation):
    if not (0 < rows <= 4096 and 0 < words <= 4096):
        raise ValueError('invalid capture geometry')
    size = rows * words * 4
    if size > full_bytes or full_bytes + 0x200 > allocation:
        raise ValueError('capture or worst-case full-width footprint exceeds allocation')
    return size


def snapshot(B):
    return {a: B.P().mem_get(a, 1, tries=1)[0] for a in EXTRA_REGS}


def checked_snapshot(B):
    result = snapshot(B)
    if any(v is None for v in result.values()):
        raise RuntimeError('incomplete H1 readback')
    return result


def publish_native(P):
    """Bootstrap via ROM only; never execute fresh RAM to publish itself."""
    if P.mem_get(P.ECHO_SLOT)[0] != P.ECHO_ORIG:
        raise RuntimeError('echo has another owner')
    for address in (0xC000E91C, 0xC000EABC):
        P.set_echo_handler(address)
        try:
            P.sh('echo', retries=0)
        finally:
            P.set_echo_handler(P.ECHO_ORIG)


def install_checked_upload(P):
    # Avoid executing the old bulk/dump helpers during code bootstrap. All
    # temporary code and parameter uploads are small, checked native writes.
    def upload(address, blob, label='', *args, **kwargs):
        blob = bytes(blob)
        if len(blob) % 4:
            blob += bytes(-len(blob) % 4)
        for offset in range(0, len(blob), 256):
            P.put_slow(address + offset, blob[offset:offset + 256], label)
        publish_native(P)
    P.put = upload
    original_sh = P.sh
    def bounded_sh(line, *args, **kwargs):
        # In particular, an uncertain heap allocation must never be repeated.
        kwargs['retries'] = 0
        return original_sh(line, *args, **kwargs)
    P.sh = bounded_sh


def scope_claims(cave, base, size):
    original = cave.claim
    claims = {}
    cursor = 0
    def claim(name, count):
        nonlocal cursor
        if not name.startswith('imxl.') or name == 'imxl.heap.code':
            return original(name, count)
        if name in claims:
            address, capacity = claims[name]
            if count > capacity:
                raise RuntimeError('temporary claim cannot grow')
            return address
        count = (count + 7) & ~7
        if cursor + count > size:
            raise RuntimeError('owned helper allocation exhausted')
        claims[name] = (base + cursor, count)
        cursor += count
        return claims[name][0]
    cave.claim = claim
    return original, claims


def configure(B, F, s, full, item, extra):
    name, mux, horizontal, record = item
    B.startstop(100)
    B.wr(SOURCE_H, horizontal)
    B.wr(SOURCE_V, 0)
    st = extra['claim']('imxl.h1.driver', 48)
    B.P().put(st, driver(record, horizontal), 'H1 native driver')
    B.call(0xC0633B31, 1, st)
    B.call(0xC017FAA1, horizontal, 0)
    B.wr(MUX, mux)
    rows, words = full[0], (882 if horizontal else full[1])
    s.size = validate_geometry(rows, words, full[0] * full[1] * 4, s.alloc)
    s.h, s.words = rows, words
    s.tail = s.buf + s.size - 16
    s.guard = s.buf + full[0] * full[1] * 4 + 0x100
    B.wr(0x30182110, rows)
    B.wr(0x30182114, words)
    B.wr(s.guard, 0x5AFE5AFE)
    B.call(B.F_SETADDR, s.scratch)
    B.startstop(10)
    time.sleep(0.35)
    rb = checked_snapshot(B)
    if rb[SOURCE_H] != horizontal or rb[SOURCE_V] != 0:
        raise RuntimeError('native H1 source overwritten')
    if (rb[H1] & 3) != horizontal or (rb[H2] & 3) != 0:
        raise RuntimeError('H1/H2 control does not match requested stage')
    if B.P().mem_get(MUX)[0] != mux:
        raise RuntimeError('H1 tap overwritten')
    expected_driver = driver(record, horizontal)
    expected_kernel = [int.from_bytes(expected_driver[o:o+3], 'little')
                       for o in range(0x1C, 0x28, 3)]
    if [rb[a] for a in range(0x300F0850, 0x300F0860, 4)] != expected_kernel:
        raise RuntimeError('native H1 kernel overwritten')
    return dict(stage=name, mux=mux, hbin=3 if horizontal else 1,
                kernel_record=record, height=s.h, line_words=s.words,
                bits=14, window=s.base_window,
                readback={hex(a): v for a, v in rb.items()},
                transfer_is_a0_tap=True, native_bufa7_job_not_replaced=True)


def capture(B, s, full, directory, meta):
    directory.mkdir(parents=True, exist_ok=False)
    full_bytes = full[0] * full[1] * 4
    metas = []
    for name in ('frame.raw', 'frame2.raw'):
        P = B.P()
        P.mem_window(B.WIN, s.buf, full_bytes, 3)
        try:
            P.mem_write(s.buf, struct.pack('<I', SENTINEL) * (full_bytes // 4),
                        label='owned capture sentinel')
        finally:
            P.mem_window(B.WIN, s.buf, full_bytes, 0)
        if not s.grab_cb(timeout=1.5):
            raise RuntimeError('no whole H1 frame completion')
        P.mem_window(B.WIN, s.buf, full_bytes, 1)
        try:
            raw = P.mem_read(s.buf, full_bytes, label='H1 capture')
        finally:
            P.mem_window(B.WIN, s.buf, full_bytes, 0)
        if P.mem_get(s.guard)[0] != 0x5AFE5AFE:
            raise RuntimeError('DMA exceeded worst-case full-width capture')
        # Record the actual footprint instead of trusting a programmed pitch.
        import numpy as np
        words = np.frombuffer(raw, dtype='<u4')
        changed = np.flatnonzero(words != SENTINEL)
        span = 0 if not len(changed) else (int(changed[-1]) + 1) * 4
        (directory / (name + '.full')).write_bytes(raw)
        (directory / name).write_bytes(raw[:s.size])
        metas.append(dict(name=name, bytes=s.size, changed_extent_bytes=span,
                          expected_extent_bytes=s.size,
                          full_sha256=hashlib.sha256(raw).hexdigest()))
        if span != s.size:
            raise RuntimeError(f'actual DMA extent {span} differs from expected {s.size}')
    meta['frames'] = metas
    meta['readback_after'] = {hex(a): v for a, v in checked_snapshot(B).items()}
    (directory / 'frame.json').write_text(json.dumps(meta, indent=2) + '\n')


def recover(B, s, full, saved, out):
    # First restore a full-width stream so a previously short/no-frame DMA can
    # complete within the retained full-width allocation, then stop in its ISR.
    B.wr(SOURCE_H, saved[SOURCE_H])
    B.wr(SOURCE_V, saved[SOURCE_V])
    for a, value in saved.items():
        if a not in (SOURCE_H, SOURCE_V):
            B.wr(a, value)
    B.wr(MUX, 1)
    B.wr(0x30182110, full[0])
    B.wr(0x30182114, full[1])
    B.call(B.F_SETADDR, s.scratch)
    time.sleep(0.25)
    stopped = B.startstop(100)
    if stopped is False:
        raise RuntimeError('no boundary completion during recovery; keep buffers')
    if B.P().mem_get(0x30182000)[0] & 0x1F:
        raise RuntimeError('BUFA0 remains active; keep buffers')
    # Source values must be restored before native window/mode restoration.
    for a in (SOURCE_H, SOURCE_V):
        if B.P().mem_get(a)[0] != saved[a]:
            raise RuntimeError('native source restore not confirmed')
    (out / 'recovered-before-close.json').write_text(json.dumps(
        {hex(a): v for a, v in checked_snapshot(B).items()}, indent=2) + '\n')


def run(out):
    sys.path[:0] = [str(IMXL), str(SHELL)]
    import putfile as P
    import cave
    import imxl
    import bufa_probe as B
    import fastsweep as F
    import bins
    import l7
    import callfn
    out.mkdir(parents=True, exist_ok=True)
    s = None
    work = None
    full = saved = None
    safe_to_free = False
    session_started = False
    result = dict(status='STARTED', camera_operated=True,
                  plan=[dict(name=n, mux=m, horizontal=h, record=r) for n,m,h,r in STAGES])
    with open('/tmp/fp-af-fusion.lock', 'a+') as lease:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert 'app_current -> 2' in P.sh('status get app_current', retries=0)
        assert 'is_recording -> 0' in P.sh('status get is_recording', retries=0)
        assert ',0008,' in P.sh('imager mode_now', retries=0)
        assert P.mem_get(P.ECHO_SLOT)[0] == P.ECHO_ORIG
        rom = (ROOT/'out/seg0_c0000000.bin').read_bytes()
        for address in (0xC000E91C,0xC000EABC,0xC0633B30,0xC017FAA0,
                        0xC01D36E0,0xC06314D0,0xC0631640,0xC06316B8):
            expected = list(struct.unpack_from('<2I',rom,address-0xC0000000))
            if P.mem_get(address,2,tries=1) != expected:
                raise RuntimeError(f'firmware entry differs at {address:08X}')
        result['boot'] = cave.boot_id()
        result['before'] = {hex(a): v for a, v in checked_snapshot(B).items()}
        install_checked_upload(P)
        try:
            # First bootstrap the existing cave callfn, then acquire owned RAM.
            imxl.HEAP_CLASS = 0
            work = imxl.heap(0, 65536)
            if not work[0]:
                raise RuntimeError('helper allocation refused')
            original_claim, claims = scope_claims(cave, work[0], 65536)
            result['work'] = [work[0], work[1]]
            result['work_claims'] = claims
            F.cached_assemble()
            session_started = True
            s = F.Session(out, 512, pair=True, mode=10, min_alloc=24 << 20)
            result['capture_allocations'] = s.held
            B.startstop(100)
            regs, hmax, _, _, _ = bins.V['v3_14']
            regs = [(r,v) for r,v in regs if r != 0x005D] + [(0x005D,5)]
            # Existing native batch helper with an exactly-sized table claim.
            import tc_stages as TC
            count = TC.batch(regs)
            assert count == len(regs)
            B.wr(0x30100004, (hmax-1) | (hmax-1) << 16)
            B.wr(0x30100800, 0x00112013)
            B.wr(0x300E10B4, 3)
            l7.rewindow(s, 1)
            full = (s.h, s.words)
            saved = checked_snapshot(B)
            assert saved[SOURCE_H] == saved[SOURCE_V] == 0
            assert full == (512,2653), f'unexpected full-width RAW14 geometry {full}'
            result['full_geometry'] = full
            result['saved'] = {hex(a): v for a,v in saved.items()}
            (out/'state.json').write_text(json.dumps(result,indent=2)+'\n')
            for item in STAGES:
                print('stage', item[0], flush=True)
                meta = configure(B,F,s,full,item,dict(claim=cave.claim))
                capture(B,s,full,out/item[0],meta)
                result.setdefault('completed',[]).append(item[0])
                (out/'state.json').write_text(json.dumps(result,indent=2)+'\n')
            result['status'] = 'CAPTURED_PENDING_ANALYSIS'
        except BaseException as exc:
            result['status'] = 'TRIAL_INCOMPLETE'
            result['error'] = repr(exc)
            print('trial error',repr(exc),flush=True)
        finally:
            try:
                if s is not None and full is not None and saved is not None:
                    recover(B,s,full,saved,out)
                    s.write(0x0018,0)
                    s.write(0x005D,3)
                    s.close()
                    safe_to_free = True
                elif s is None and not session_started:
                    safe_to_free = True
                if safe_to_free and work and work[0]:
                    # Heap helper stays in the cave, not in the freed region.
                    imxl.give_back([work])
                    result['resources_released'] = True
                else:
                    result['resources_released'] = False
            except BaseException as exc:
                result['cleanup_error'] = repr(exc)
                result['resources_released'] = False
            result['after'] = {}
            if result.get('resources_released'):
                for cmd in ('status get app_current','status get is_recording','imager mode_now'):
                    result['after'][cmd] = P.sh(cmd,retries=0)
                time.sleep(0.3)
                second = P.sh('imager mode_now',retries=0)
                result['after']['imager mode_now second'] = second
                first_count = re.search(r'frame_count:(\d+)',result['after']['imager mode_now'])
                second_count = re.search(r'frame_count:(\d+)',second)
                result['liveview_advances'] = bool(first_count and second_count and
                    int(second_count[1]) > int(first_count[1]))
            (out/'state.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2),flush=True)
    return 0 if result['status']=='CAPTURED_PENDING_ANALYSIS' and result.get('resources_released') else 1


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-live', action='store_true')
    p.add_argument('--output',type=Path,default=ROOT/'projects/sensorlab-imx410/validation/h1-live-20261030/run1')
    a=p.parse_args()
    if not a.run_live:
        print(json.dumps(dict(camera_operated=False,stages=STAGES,
            source_registers=[hex(SOURCE_H),hex(SOURCE_V)],
            scope='512-row sensor V3 RAW14; independent a0 H1 tap; no recording/card write'),indent=2))
        return 0
    return run(a.output)


if __name__=='__main__':
    raise SystemExit(main())
