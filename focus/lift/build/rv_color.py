#!/usr/bin/env python3
"""rv_color.py — RC1/RC2 的色彩矩陣(fp 感光元件 → Rec.709),唯一定義。

來源:非 OFF 模式 still DNG 的 ColorMatrix2(D65,XYZ→camera)。
  research/imaging-hw/color-characterisation/captures/_SDI5625.DNG(sha256 0e2d43289d2fbcf4…,PowderBlue)
  OFF 的 DNG／ISP 都是單位矩陣(README「RAW 模式色彩矩陣」),所以校色矩陣只能取自非 OFF 的 metadata。
換算(dcraw 做法):cam_rgb = CM2 · M709(linear Rec.709 → XYZ),每列正規化成和 1(白平衡後的白 → 白),rgb_cam = inv(cam_rgb)。
參考 BMCC:Film to Video 在中低飽和 ＝ 3×3 + 每通道 tone(飽和增益 ≈ 1),直接用此矩陣(子代理分析,README)。

韌體矩陣表(root+0x08 → 0xC0B39CC8,35 筆 × 0x18 {mode, 9 × s16, pad},512 = 1.0),每列對角在前:
  R 列 (R, G, B)、G 列 (G, R, B)、B 列 (B, R, G)(以 Standard 模式與 DNG 私有 tag 0x124 核對)。
硬體:係數 11-bit;任一列第 1 項 ≥ 1024 或第 2/3 項 < −511 會觸發縮半(FUN_c02cf938)→ 這裡 assert 不觸發。
2026-09-25 上機:換 root+0x08 指到副本後 RGBLMAT 組 2 即為此矩陣,灰維持中性。
"""
import struct

CM2 = [[0.8252, -0.2044, -0.1744], [-0.4961, 1.1648, 0.0631], [-0.1137, 0.1581, 0.3549]]
M709 = [[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]]

MAT_TAB = 0xC0B39CC8
MAT_N, MAT_REC, OFF_IDX = 35, 0x18, 34
OFF_REC = MAT_TAB + OFF_IDX * MAT_REC      # 0xC0B39FF8
ROOT_P08 = 0xC2F1A06C


def _mm(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _inv(m):
    (a, b, c), (d, e, f), (g, h, i) = m
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    return [[(e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det],
            [(f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det],
            [(d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det]]


def cam_to_709():
    c = _mm(CM2, M709)
    c = [[v / sum(r) for v in r] for r in c]
    return _inv(c)


def q9():
    """3×3,×512 取整,每列和修成 512(灰不偏)。"""
    out = []
    for r in cam_to_709():
        q = [round(v * 512) for v in r]
        q[0] += 512 - sum(q)                 # 餘差放對角
        out.append(q)
    return out


def table_order():
    """韌體表內順序的 9 個 s16。"""
    (rr, rg, rb), (gr, gg, gb), (br, bg, bb) = q9()
    t = (rr, rg, rb, gg, gr, gb, bb, br, bg)
    for k in range(0, 9, 3):
        assert t[k] < 1024 and t[k + 1] >= -511 and t[k + 2] >= -511, t   # 不觸發縮半
    return t


def off_words(new):
    """OFF 那筆的前 6 個 word(mode + 9 × s16 + pad):原廠(單位)或新矩陣。"""
    s = table_order() if new else (512, 0, 0) * 3
    return struct.unpack('<6I', struct.pack('<I9hH', 0x24, *s, 0))


# ---- 矩陣程度(AEL 飽和度;2026-09-25 使用者:飽和度控制套用矩陣的程度,限制 0..5)----
# UI 0..5 → k = 0 %..100 %(每格 20 %):0 = 不套(OFF 原生,預設)、5 = 完整 fp 校色。負值由 stub_sa 拉回 0。
# M_k = I + k·(M − I):列和維持 512(灰不偏)。
SAT_LEVELS = range(0, 6)


def sat_k(ui):
    return ui / 5


def sat_table(ui):
    m = cam_to_709()
    k = sat_k(ui)
    out = []
    for i in range(3):
        q = [round(512 * ((i == j) + k * (m[i][j] - (i == j)))) for j in range(3)]
        q[i] += 512 - sum(q)
        out.append(q)
    (rr, rg, rb), (gr, gg, gb), (br, bg, bb) = out
    t = (rr, rg, rb, gg, gr, gb, bb, br, bg)
    for c in range(0, 9, 3):
        assert t[c] < 1024 and t[c + 1] >= -511 and t[c + 2] >= -511, (ui, t)
    return t


def sat_words():
    """6 筆 × 6 word(OFF 筆 {0x24, 9 × s16, pad}),UI 0..5 依序。"""
    return [w for ui in SAT_LEVELS for w in struct.unpack('<6I', struct.pack('<I9hH', 0x24, *sat_table(ui), 0))]


if __name__ == '__main__':
    for r in cam_to_709():
        print('  '.join(f'{v:7.4f}' for v in r))
    print('Q9', q9(), 'table', table_order())
    for ui in SAT_LEVELS:
        print(f'飽和度 {ui:+d}  {sat_k(ui):4.0%}  {sat_table(ui)}')
