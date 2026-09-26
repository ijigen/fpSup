"""Focus Lift: three preview tone tables, without changing acquisition gain.

The stock OFF table closely fits sRGB(i/1918) * 8190. This prototype
adds exposure in that linear input domain, with a smooth shoulder above
0.75. It is not Ole Berek's V-Log-input 3D LUT or a RAW clipping display.
"""
import math
import struct

N, WHITE, MAXIMUM = 2048, 1918, 8190


def display(x, stops):
    if stops not in (1, 2, 3) or not math.isfinite(x) or x < 0:
        raise ValueError('Expected nonnegative finite input and +1, +2 or +3 stops')
    y = x * 2 ** stops
    if y > 0.75:
        d = y - 0.75
        y = 0.75 + 0.25 * d / (d + 0.25)
    return 12.92 * y if y <= 0.0031308 else 1.055 * y ** (1 / 2.4) - 0.055


def table(stops):
    return [round(MAXIMUM * display(i / WHITE, stops)) for i in range(N)]


def blob():
    return b''.join(struct.pack('<2048H', *table(s)) for s in (1, 2, 3))
