"""Offline geometry/rate audit; no camera I/O and no claim to reproduce a freeze.

SelectedCam uses explicit TIFF-tag and prepare-service fixtures. It executes
the existing apply hooks and native key/canvas instructions. NativeSizing
executes pinned ROM sizing/rate arithmetic with bounded instructions/writes.
Actual file I/O, allocator availability, tasks, imager, DMA and LCD are absent.
"""
from pathlib import Path
import hashlib
import json
import struct
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path[:0] = [str(ROOT / 'projects/sensorlab-imx410/apply'),
               str(ROOT / 'projects/open-gate/build/og4k_offline')]
import test_playback_checked as C
import og4k_sizes as O


def main():
    fw = O.load_firmware()
    native = O.NativeSizing(fw)
    model = O.load_model()
    rows = []
    for raster in ((3856, 2170), (4016, 2676), (6064, 3412), (6064, 4050)):
        for bits in (12, 14):
            camera = C.SelectedCam()
            camera.select(C.movie(raster, bits))
            assert camera.prepare() == 1  # BE080 is a declared stub here.
            profile, canvas = camera.profile()
            assert (canvas[3], canvas[4]) == raster
            assert canvas[0x80 // 4] & 0xFF == (7 if bits == 12 else 8)
            sizes = []
            for out in ((1620, 1080), (1920, 1080), (3240, 1822), (3840, 2160)):
                result = native.fieldangle(canvas, out)
                assert result['total_bytes'] == model.total(canvas, *out)
                sizes.append(dict(output_fixture=out, **result))
            rows.append(dict(raster_fixture=raster, bits=bits, profile=profile,
                             raw_payload_bytes=raster[0] * raster[1] * bits // 8,
                             sizes=sizes))
    rates = []
    for numerator, denominator, expected in ((12, 1, 0), (22, 1, 0),
                                            (24000, 1001, 1), (24, 1, 2),
                                            (30000, 1001, 4), (120, 1, 10)):
        native.uc.mem_write(native.DESC, struct.pack('<II', numerator, denominator))
        result = native._run(0xC06A0770, (native.DESC,))
        assert result == expected, (numerator, denominator, result)
        rates.append(dict(rational=[numerator, denominator], native_enum=result))
    sources = [ROOT/'projects/sensorlab-imx410/apply/ap.c',
               ROOT/'projects/sensorlab-imx410/apply/test_playback_checked.py',
               Path(__file__)]
    report = dict(passed=True, hardware_tested=False, freeze_reproduced=False,
                  limitations=__doc__, firmware_sha256=hashlib.sha256(fw).hexdigest(),
                  sources={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in sources}, geometry=rows, native_rates=rates)
    (HERE/'native-audit.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(dict(passed=True, geometry_cases=len(rows), size_cases=4*len(rows),
                          rate_cases=len(rates), freeze_reproduced=False)))


if __name__ == '__main__':
    main()
