#!/usr/bin/env python3
"""rv_uidata.py — Color 選單第 17 列「RAW」的 UI 資料(卡片與 shell 測試共用的唯一定義)。

ColorButtonMenu(COLOR 鍵;MENU 路徑也是它,2026-09-24 實測)的 model 是 ListColorButtonMenu{,_EXCL,_EXCL2}.cvm。
新版 CSV 無 BOM、LF;主檔第 1 列 Left→19、第 16 列 Right→16、加第 17–20 列(R1 R2 RC1 RC2);
_EXCL/_EXCL2 各加四列停用的列。
卡片上由 H1(C05E5BEC,取檔位置)把原廠位址換成這些資料;shell 測試改 heap 檔案表。
"""
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[3]
HERE_BUILD = pathlib.Path(__file__).resolve().parent
ROM = REPO / 'out' / 'MAIN_c0000000.bin'

RAW_ICON = 'set_flash_1'   # 借用的圖示名稱(原廠閃電、Color 選單未用);H1 讀取時換成 ICONS 的 RAW 圖(2026-09-25 上機)
NROW = 1          # 第 17 列 = RAW(GUI 16);曲線 SA/GA 用右側上下框、矩陣程度用 AEL 飽和度(2026-09-25 使用者決定)
LAST = 16 + NROW  # 最後一列的 NO(20)

CSVS = [  # (名稱, 原廠位址, 原廠大小, hash, 改列, 新增列)
    ('ListColorButtonMenu', 0xC0D566EC, 453, 0x08C7EA7B,
     {1: f'1,set_color_01,0,{LAST - 1},1,0'.encode(), 16: b'16,set_common_1,0,14,16,15'},
     [f'{n},{RAW_ICON},0,{n - 2},{n if n < LAST else 0},{n - 1}'.encode() for n in range(17, LAST + 1)]),
    ('_EXCL', 0xC0D568B4, 483, 0x75550E26, {}, [f'{n},set_common_1,1,15,15,15'.encode() for n in range(17, LAST + 1)]),
    ('_EXCL2', 0xC0D56A98, 452, 0xB0264BF0, {}, [f'{n},set_common_1,1,14,0,15'.encode() for n in range(17, LAST + 1)]),
]

CAP = {1: 0x80, 4: 0x98}[NROW]   # 列表上限 15.0 → 15 + NROW(大端 float 0x41xx0000 的 xx)
TEXT_END = 500 + 33 * NROW       # 文字群組終點:每列 33(原廠 500;一列時 533 已上機)

PAGE = [  # ColorButtonMenu 頁(大端值跨 word;頁面解析時讀)
    (0xC1D63010, 0x00000070, CAP),                   # 列表上限 15.0 → 19.0
    (0xC1D631AC, 0x70410000, 0x00410000 | CAP << 24),  # 動畫 t=0 上限
    (0xC1D66CBC, 0xF4010000, int.from_bytes(TEXT_END.to_bytes(4, 'big'), 'little')),   # 文字群組終點 500 → 632
    # 同結構的其餘控制值上限(+0x20 大端 15.0)。2026-09-25 上機:少了它們,按 OK 後 16 被夾回 15、再以 15 回呼 → 選回 OFF
    (0xC1D5F200, 0x00000070, CAP),                   # @0xC1D5F1FF
    (0xC1D62A7C, 0x00007041, 0x00000041 | CAP << 8),   # @0xC1D62A7C
    (0xC1D63F8C, 0x00000070, CAP),                   # @0xC1D63F8B
    (0xC1D65B24, 0x70410200, 0x00410200 | CAP << 24),  # @0xC1D65B26
    # 右側框種類 `Effect or Scheme`(C1D63F1F):14–15 → Effect;上限 15.0 → 16.0 讓 RAW 列固定是 Effect 框(否則沿用前一列)
    (0xC1D640A8, 0x00007041, 0x00008041),
]
PAGE += [  # ColorModeAdvancedSettings(AEL 細部頁):`MenuMode` 依 CM_COLFIX_ColorMode,Normal(≤12)→ Contrast/Sharpness/Saturation。
    # RAW(16)不符任何事件 → 無選單組、上下與 MENU 失效(2026-09-25 上機)。12.0 → 16.0;DUO(13)/MONO(14)的 == 事件在後。
    (0xC1D6ED48, 0x00004041, 0x00008041),
]

# UI 條件式(資源字串,原地):`CM_COLFIX/CM_COLAJ/CM_DNGDEV_ColorMode :v() == 15` 的 '==' 改 '>='(長度不變)。
# 原廠值最大 15 → 對原廠模式無影響;RAW(16)跟 OFF 一樣隱藏「±」強度調整框(2026-09-25 截圖 SS__1000)。
EXPR = [0xC2D9FC64, 0xC2D9FD47, 0xC2DA1256, 0xC2DA1290, 0xC2DAF034, 0xC2DAF097, 0xC2DAF0DA, 0xC2DAF15E, 0xC2DAF19C]


def expr_words():
    """[(word 位址, 原廠字, 新字)],每個 '==' 的第一個 '=' 改 '>'。"""
    rom = ROM.read_bytes()
    out = {}
    for a in EXPR:
        assert rom[a - 0xC0000000:a - 0xC0000000 + 2] == b'==', hex(a)
        wa = a & ~3
        cur = out.get(wa) or bytearray(rom[wa - 0xC0000000:wa - 0xC0000000 + 4])
        cur[a - wa] = ord('>')
        out[wa] = cur
    return [(wa, int.from_bytes(rom[wa - 0xC0000000:wa - 0xC0000000 + 4], 'little'), int.from_bytes(b, 'little'))
            for wa, b in sorted(out.items())]


# H1 換檔:圖示(原廠位址、原廠大小、新檔)。位址由相機上 NBR reader 的 heap 檔案表讀出(rv_uidiag nbr 同法),build 時核對 XC 標頭。
ICONS = [('set_flash_1.xci', 0xC14EBAAC, 533, HERE_BUILD / 'rv_raw_icon.xci')]

H1_SITE, H1_ORIG, H1_RET = 0xC05E5BEC, 0x60681840, 0xC05E5BF1   # adds r0,r0,r1; str r0,[r5,#4](Thumb)


def csv(at, size, edits, extra):
    rom = ROM.read_bytes()
    orig = rom[at - 0xC0000000:at - 0xC0000000 + size]
    assert orig[:3] == b'\xef\xbb\xbf'
    lines = [l for l in orig[3:].split(b'\r\n') if l]
    for i, l in edits.items():
        assert lines[i].split(b',')[0] == str(i).encode(), (i, lines[i])
        lines[i] = l
    return b'\n'.join(lines + list(extra)) + b'\n'


def blobs():
    return [(name, at, csv(at, size, ed, ex)) for name, at, size, h, ed, ex in CSVS]


# 右側框字形(條件式替換,stub_fv 的 gltab):位址由相機 heap 檔案表讀出(2026-09-25),圖由 tools/rv_icon.py 產生。
GLYPHS_H1 = [('font_menu_LB_kigou_08.xci(±)→ S', 0xC1427874, 240, HERE_BUILD / 'rv_glyph_S.xci'),
             ('font_menu_LB_0.xci → A', 0xC141E30C, 679, HERE_BUILD / 'rv_glyph_A0.xci'),
             ('font_menu_LB_kigou_07.xci(+)→ G', 0xC1427788, 234, HERE_BUILD / 'rv_glyph_G.xci'),
             ('font_menu_LB_1.xci → A', 0xC141E5B4, 479, HERE_BUILD / 'rv_glyph_A1.xci')]
# fs2-11 上機:圖片依名稱快取(引用計數,FUN_c05dfe88/FUN_c05d8910),同名字形不重讀 → 出現「G1」「±0」,
# 換過的字母也可能留在別處。停用(GLYPHS = []);改以 drawImage(0xC061F0A0)換字表、用原廠 font_menu_LB_id_S/A/G(研究中)。
GLYPHS = []


def glyph_blobs():
    rom = ROM.read_bytes()
    out = []
    for name, at, size, path in GLYPHS:
        assert rom[at - 0xC0000000:at - 0xC0000000 + 4] == b'XC\0\0', name
        out.append((name, at, path.read_bytes()))
    return out


def icon_blobs():
    rom = ROM.read_bytes()
    out = []
    for name, at, size, path in ICONS:
        assert rom[at - 0xC0000000:at - 0xC0000000 + 4] == b'XC\0\0', name
        assert int.from_bytes(rom[at - 0xC0000000 + 8:at - 0xC0000000 + 12], 'little') == 86 | 74 << 16, name
        out.append((name, at, path.read_bytes()))
    return out


# 條件式修改(EXPR)不上卡:NBV 規則在 FS2 載入前就已編譯,執行期與開機時改字串都無效(2026-09-25 上機:
# 游標在 OFF 時 CBM_BKTMonochrome 仍為 1;fs2-6 開機改 '>=' 後游標在 GUI 16 時仍為 0)。而且單列 RAW 正需要框可操作。
