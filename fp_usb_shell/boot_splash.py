"""Four-box boot artwork and AutoRun commands (offline only).

The two small alpha masks are rendered logo artwork, not a bundled font.
The builder needs only Python's standard library. The actual camera format is
little-endian ARGB4444; all five frames have a transparent background.
See research/display/notes/{BOOT_BANNER,SPLASH_BAND}.md for measured formats.
"""
import base64
import struct
import zlib

SCREEN_WIDTH = 1024
# osdfile starts at (0,0). Progress updates need only the narrow logo rectangle;
# the first frame clears the full top row without touching the lower native UI.
WIDTH, HEIGHT = 176, 56
FRAME_BYTES = WIDTH * HEIGHT * 2
ASSET_NAME = 'FPSUPUI'
DRAW = 0xC0528700
DRAW_ORIGINAL = 0xE92D4BF0
DRAW_PAUSED = 0xE12FFF1E
ECHO_SLOT, ECHO_ORIGINAL = 0xC0BAC2F8, 0xC03D99A0
DCACHE, ICACHE = 0xC000E91C, 0xC000EABC
HOLD_MS = 2000
# User reference: white fp and Sup pink sampled near #E03959.
# Native 4-bit channels quantize the pink to #DD3355.
WHITE, PINK, OUTLINE, FILL = 0xFFFFFF, 0xDD3355, 0x888888, 0xFFFFFF
# SF system UI, regular upright weight, with the font's natural baseline/spacing.
# Only these rendered alpha masks are carried; no font is needed by the builder.
MASK_HEIGHT = 28
FP_WIDTH = 27
FP_MASK = (
    'c-n2!PbdUY90&04oA-937D+CO92DgsNpV;XQd}G;4%VJr+>}s~l(i(eX*tNrh0`tvIf#ReY<r>5Y7ffaC=Q#=?9R'
    '`dncZz>cYn9()BC=8zuylGrIVp>xETuaiZRz2$?5^mCxIzSJ^7~V!19UXB%N$Sv2utA#hoRk3`_`l9T!6IY``TwS'
    'Z>Z{$?|yO^giYpEkm`}D}&t&+iN2(!zfdY=ptHig^Z8*fNs%ff|Ai_q!yj3>JQS-`RR+qA>-UN#f<b0(!OY~9;ot'
    'Z+IJ087$Wq@!F2kgBS4YAxh}IItdveR$rgYs6(8E216HC7vymM8lx(n5fC-~{Y>}wjPJWn#Nuqu`ZDdYimZ;ZGL9'
    ';^w0ZO;p>7!i#b;j8Zy_UoNu6a2L;lv<m2jEspkvgmgw!fvwt<#lypA9_zrh|#`orFf4@>YfzeP(H<@7J8eu0BqN'
    'xveE7L#t>B+&;$+hhW_lgO>FTs4U4%TW&*+;M5<c@Vw13NXP@MVCgbcSVia`oIcg2'
)
SUP_WIDTH = 51
SUP_MASK = (
    'c-oDWT}V_x6vxlZ+`EPutE6FR^r2~Qg5gUK5@q?MJ!ILJOCSnXlo0!nec;E7J{5sv4_cUyQ7PJ&N=Tumwu>4{YAI'
    '%=v1=_^ZQZ^1G&A?^BDv(Ahs&Ka=Qn5O{Lc&kfz+D51^?32y+Z&LRyRVS!i$!5r$@q2xP_>7);g<Omk<{sVveCPn'
    'kE0zdkpMlt0SaW_oad&4AxC)xEmN%6k^RXg~_kN14W2jFYXII0Y%Q+;4)&lHTc(<bq>DRhDCe~s+o`^=I5snvcuu'
    'n0%o3rjy(Ri&rui+iN!Z=Ix~3`*xni6Qp5&=dr{yl;t7$90Qrd1eEl9YqK?mtk_K+aaCZah<9p0tMj0at6l+?6g^'
    'X%0j<ji$rxC|GT?XRwHIyU^{N>gCo2(rxP=a{aLdI~I`yQe1m#4r6G<#gfN-jgj8!6-0{%bju55pq5md!<{u+^h`'
    '6M4|ua#z4qe<&YlSOo8Yjfk37A(qOvA{nKPt{(z&a(6f+mx|gmvP(CbMR83fwwJh3NVyW}z@OV>BN2%A;tMG?p;B'
    'dA3mPq95l?~?ia_)nx|cPm4dT2w%)%kQBnz?6<G^0$g^k3Lk-z}HjS@(qiKr97ie(Wd+a=YHtu=_}AxbiosWZka0'
    ';dctqpBDuFX4!J{0iAr3KSt$X6nCZH}h%PrDqVY1LPn+l)Ww5bkxi;8w;wU5*ReJOn89$`y(+TOTtCJ;ZGwF>j?y'
    'kgyX0lME+n$oY+S_VjIx-*IbV2_Qs}XqH|6HV{i#I<7sVOH%?AyZh8E<E}W=xR16~e()h{k_1}Yc-<`|L&nw<!4o'
    '7xQ;fzE+C$*cdPuU^@Am!ZMo}vD>x&ut!B)&{ubKl_ovb9j%a77}Eb|~qZ{xDRVWJ=0b+&vO{OQcUq2@qq4(5uC@'
    'Cq#4r3874kiM;y~Sx;0k8G01{ZzdvoA+q@8NaVHx`3q@8g4X'
)


def asset():
    """Return empty→four-filled frames with no host font/library dependency."""
    base = [0] * (WIDTH * HEIGHT)
    logo_width = FP_WIDTH + SUP_WIDTH
    box_size, gap, logo_gap = 12, 4, 8
    total = logo_width + logo_gap + 4 * box_size + 3 * gap
    left = 16
    assert left + total <= WIDTH

    def logo(encoded, width, x, color):
        alpha = zlib.decompress(base64.b85decode(encoded))
        assert len(alpha) == width * MASK_HEIGHT
        rgb = [(color >> shift) & 255 for shift in (16, 8, 0)]
        for y in range(min(MASK_HEIGHT, HEIGHT - 10)):
            for dx in range(width):
                a = alpha[y * width + dx]
                alpha4 = (a + 8) // 17
                r, g, b = [(c + 8) // 17 for c in rgb]
                base[(y + 10) * WIDTH + x + dx] = ((alpha4 << 12) | (r << 8) |
                                                              (g << 4) | b) if alpha4 else 0

    logo(FP_MASK, FP_WIDTH, left, WHITE)
    logo(SUP_MASK, SUP_WIDTH, left + FP_WIDTH, PINK)
    # Align the square outlines with the visible logo, not its padded mask.
    # Derive the center from the quantized ink so padding cannot shift the boxes.
    ink_rows = [i // WIDTH for i, pixel in enumerate(base) if pixel >> 12]
    boxes_y = (min(ink_rows) + max(ink_rows) + 1 - box_size) // 2
    boxes_x = left + logo_width + logo_gap
    frames = []
    for filled in range(5):
        pixels = base.copy()
        for box in range(4):
            x0, y0 = boxes_x + box * (box_size + gap), boxes_y
            # Empty: thin gray outline. Complete: solid white, covering the outline.
            for y in range(box_size):
                for x in range(box_size):
                    border = x == 0 or x == box_size-1 or y == 0 or y == box_size-1
                    if box < filled:
                        pixels[(y0+y)*WIDTH+x0+x] = 0xFFFF
                    elif border:
                        pixels[(y0+y)*WIDTH+x0+x] = 0xF888
        frames.append(struct.pack('<' + 'H' * len(pixels), *pixels))
    result = b''.join(frames)
    assert len(result) == 5 * FRAME_BYTES
    return result


def frame_width(index):
    return SCREEN_WIDTH if index == 0 else WIDTH


def frames():
    """One full-width initial frame, then four small progress images."""
    artwork = asset()
    result = [artwork[n * FRAME_BYTES:(n + 1) * FRAME_BYTES] for n in range(5)]
    row_bytes = WIDTH * 2
    transparent_tail = bytes((SCREEN_WIDTH - WIDTH) * 2)
    result[0] = b''.join(result[0][y * row_bytes:(y + 1) * row_bytes] +
                         transparent_tail for y in range(HEIGHT))
    return result


def publish(out):
    # No freshly injected helper may bootstrap its own instruction cache.
    for address in (DCACHE, ICACHE):
        out.extend((f'mem set 0x{ECHO_SLOT:08X} 0x{address:08X}', 'echo'))


def restore_echo(out):
    out.extend([f'mem set 0x{ECHO_SLOT:08X} 0x{ECHO_ORIGINAL:08X}'] * 3)


class FourBoxBar:
    def __init__(self):
        self.frame = -1

    def start(self, out):
        out.append('# --- four-box UI: pause native redraw, publish the code patch ---')
        out.append(f'mem set 0x{DRAW:08X} 0x{DRAW_PAUSED:08X}')
        publish(out)
        # The first frame replaces the full upper row in all three buffers.
        # Keep every lower row and the sublayer; do not clear whole OSD layers.
        self.progress(out, 0)

    def progress(self, out, filled):
        # Fast miss falls through to the slow loader. Keep the visible state
        # monotonic; never announce completion before stage2 has returned.
        filled = min(3, filled)
        if filled <= self.frame:
            return
        for value in range(self.frame + 1, filled + 1):
            out.append(f'# four-box frame {value}/4')
            out.extend([f'display osdfile \\{ASSET_NAME}\\{value}.BIN 0 0 {frame_width(value)} {HEIGHT} 0'] * 3)
        self.frame = filled

    def fallback(self, out):
        # Reached on plain success and on any BIN-read failure. Fast success
        # restores natively in splash_finish.S before its existing abort.
        out.append('# --- four-box UI fallback: restore even if BIN did not load ---')
        out.extend([f'mem set 0x{DRAW:08X} 0x{DRAW_ORIGINAL:08X}'] * 3)
        publish(out)
        restore_echo(out)
