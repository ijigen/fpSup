#!/usr/bin/env python3
"""Build the development LV Boost card through fpSup's shared loader.

Derived from the research devkit's RAW View builder; the LV_BOOST assembly
variant leaves capture gain, global tone/matrix roots and DNG metadata alone.
"""
import argparse, pathlib, struct, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
SHELL = REPO / 'fp_usb_shell'
sys.path.insert(0, str(SHELL))
from armasm import assemble, symbols  # noqa: E402
import rv_uidata                       # noqa: E402
import rv_color                        # noqa: E402
import rv_dngcm                        # noqa: E402
import fl_tables                       # noqa: E402


def write_csv_inc(focus_lift=False):
    """rv_resident.S 的 #include:fvtab 與三個 CSV(rv_uidata 是唯一定義)。"""
    files = rv_uidata.blobs() + rv_uidata.icon_blobs()          # 三個 CSV + RAW 圖示
    prefix = 'fl' if focus_lift else 'rv'
    if focus_lift:
        # The second exclusion list disables native OFF and Duotone. Keep
        # those restrictions, but make our additional row reachable.
        name, at, size, _, _, _ = rv_uidata.CSVS[2]
        files[2] = (name, at, rv_uidata.csv(at, size, {
            1: b'1,set_color_01,0,16,1,0',
            15: b'15,set_color_11,0,12,16,14',
        }, [b'17,set_flash_1,0,14,0,16']))
        name, at, _ = files[-1]
        files[-1] = (name, at, (HERE / 'fl_icon.xci').read_bytes())
    glyphs = rv_uidata.glyph_blobs()                             # 條件式:SA/GA 字形
    (HERE / f'{prefix}_fv.inc').write_text(f'/* 由 build_lv_boost.py 產生,勿手改 */\n.equ NFV, {len(files)}\n.equ NGL, {len(glyphs)}\n')
    out = ['/* 由 build_lv_boost.py 產生,勿手改 */', '.align 2', 'fvtab:']
    for i, (name, at, data) in enumerate(files):
        out.append(f'    .word 0x{at:08X}, csv{i} - params, {len(data)}   /* {name} */')
    out.append('gltab:')
    for j, (name, at, data) in enumerate(glyphs):
        out.append(f'    .word 0x{at:08X}, csv{len(files) + j} - params, {len(data)}   /* {name} */')
    files = files + glyphs
    for i, (name, at, data) in enumerate(files):
        out.append('.align 2')
        out.append(f'csv{i}:')
        for j in range(0, len(data), 16):
            out.append('    .byte ' + ', '.join(f'0x{b:02X}' for b in data[j:j + 16]))
    out.append('.align 2')
    (HERE / f'{prefix}_csv.inc').write_text('\n'.join(out) + '\n')

MAXLEN = 0xF000                        # loader.S:整個合併 BIN 的上限
ROM = REPO / 'out' / 'MAIN_c0000000.bin'
# launcher／stub 在執行期會改的位址(與 rv_launch.S 的 GUARD、rv_resident.S 一致;測試逐一核對)
RUNTIME_SITES = [
    (0xC0313244, 'hook A gain_state'), (0xC032F728, 'hook B RAW_CORR'),
    (0xC0568950, 'GUI→enum COLOR 鍵'), (0xC056D028, 'GUI→enum 選單'), (0xC05818B8, 'GUI→enum QS'),
    (0xC0595734, 'enum→GUI CM_COLFIX'), (0xC0075CF4, 'setter cmp'),
    (0xC06C07CC, 'getter movw'), (0xC06C07D0, 'getter movt'), (0xC06C07D8, 'getter count'),
    (0xC05E5BEC, 'H1 取檔位置'),
    (0xC2F1A0D4, 'root+0x70 mode→tone(stub_gs 改)'),
    (0xC059DA1C, 'enum→GUI LV_ColorMode'),
    (rv_color.ROOT_P08, 'root+0x08 色彩矩陣表(stub_gs 改,RAW 生效時)'),
    (0xC0568A3C, '上下框回呼 bl(SA/GA)'), (0xC0595908, 'v87 Effect 發布 bl'),
    (0xC056D5F8, '飽和度 AJ bl'), (0xC056D498, '飽和度 FIX bl'),
    (0xC059588C, 'v85 COLFIX 飽和度 bl'), (0xC05959E4, 'v90 COLAJ 飽和度 bl'),
    (0xC05689A8, 'GUI→enum COLOR 鍵預覽(AJ)'), (0xC05957B0, 'v82 COLFIX Effect 發布 bl'),
] + [(a, f'DNG writer {why}') for a, _, why in rv_dngcm.SITES] + [
    (0xC0D119FC, 'ColorButtonMenu vtable v25(開啟)'), (0xC0D11A00, 'ColorButtonMenu vtable v26(關閉)')] + [
    (a, f'對比/清晰鎖 0 bl {a:08X}') for a in (0xC056D548, 0xC056D3E8, 0xC056D5A0, 0xC056D440,
                                              0xC059581C, 0xC0595974, 0xC0595854, 0xC05959AC)] + [(a, f'ColorButtonMenu 頁面 0x{a:08X}') for a, _, _ in rv_uidata.PAGE]


SEG1, SEG1_BASE = REPO / 'out' / 'seg1_c2ef6e00.bin', 0xC2EF6E00


def stock_word(a):
    """原廠字。0xC2EF6E00 以上是 .data(seg1,開機時由另一段載入初值),MAIN 映像在那裡不是執行期的值。"""
    if a >= SEG1_BASE:
        return SEG1.read_bytes()[a - SEG1_BASE:a - SEG1_BASE + 4]
    return ROM.read_bytes()[a - 0xC0000000:a - 0xC0000000 + 4]


def hook_sites(focus_lift=False):
    """每個執行期位址一個 4-byte 區段,內容 = 原廠字。"""
    sites = RUNTIME_SITES
    if focus_lift:
        excluded = {0xC032F728, 0xC2F1A0D4, rv_color.ROOT_P08,
                    *(a for a, _, _ in rv_dngcm.SITES)}
        sites = [(a, why) for a, why in sites if a not in excluded]
        sites += [(0xC02D2E50, 'LV Boost preview tone pointer')]
    out = [(a, stock_word(a), why) for a, why in sites]
    import struct
    assert struct.unpack('<I', stock_word(0xC2F1A0D4))[0] == 0xC0B3D670, 'root+0x70 原廠值不是 C0B3D670'
    assert struct.unpack('<I', stock_word(rv_color.ROOT_P08))[0] == rv_color.MAT_TAB, 'root+0x08 原廠值不符'
    return out
ALLOWED_CALLS = {0xC001D740, 0xC001D7F0, 0xC000E91C, 0xC000EABC}   # launcher 只呼叫這四個(常駐的 stub_ef 另呼叫 0xC0593F30)


def write_page_inc():
    """rv_launch.S 的 #include:頁面表(rv_uidata.PAGE 是唯一定義)。"""
    out = ['/* 由 build_lv_boost.py 產生,勿手改 */', '.align 2', 'page_tab:']
    for a, old, new in rv_uidata.PAGE:
        out.append(f'    .word 0x{a:08X}, 0x{old:08X}, 0x{new:08X}')
    out.append('    .word 0')
    (HERE / 'rv_page.inc').write_text('\n'.join(out) + '\n')


def write_mat_inc():
    """rv_launch.S 的 #include:OFF 那筆的原廠字(guard)與新矩陣(rv_color 是唯一定義)。"""
    rom = ROM.read_bytes()[rv_color.OFF_REC - 0xC0000000:rv_color.OFF_REC - 0xC0000000 + 24]
    stock = rv_color.off_words(False)
    assert struct.unpack('<6I', rom) == stock, 'OFF 矩陣原廠值不符'
    out = ['/* 由 build_lv_boost.py 產生,勿手改 */', '.align 2',
           'mat_stock: .word ' + ', '.join(f'0x{w:08X}' for w in stock),
           'mat_new:   .word ' + ', '.join(f'0x{w:08X}' for w in rv_color.off_words(True))]
    (HERE / 'rv_mat.inc').write_text('\n'.join(out) + '\n')


def write_sat_inc():
    """rv_resident.S 的 #include:矩陣程度表(rv_color.sat_words,6 筆 × 24 B),放在參數區 +0x1C0。"""
    w = rv_color.sat_words()
    out = ['/* 由 build_lv_boost.py 產生,勿手改 */', 'sat_tab:']
    for i in range(0, len(w), 6):
        out.append('    .word ' + ', '.join(f'0x{x:08X}' for x in w[i:i + 6]) + f'   /* 飽和度 {rv_color.SAT_LEVELS[i // 6]} */')
    (HERE / 'rv_sat.inc').write_text('\n'.join(out) + '\n')


def write_dngcm_inc():
    """rv_resident.S 的 #include:DNG ColorMatrix 6 級 × (CM1, CM2) × 9 double(rv_dngcm 是唯一定義)。"""
    b = rv_dngcm.blob()
    out = ['/* 由 build_lv_boost.py 產生,勿手改 */', 'cm_buf:        /* 初值 = 第 0 級(原廠 OFF),stub_gs 改寫 */']
    words = lambda d: ['    .word ' + ', '.join(f'0x{w:08X}' for w in struct.unpack('<6I', d[i:i + 24]))
                       for i in range(0, len(d), 24)]
    out += words(b[:144]) + ['cm_tab:'] + words(b)
    (HERE / 'rv_dngcm.inc').write_text('\n'.join(out) + '\n')


def build_blob(focus_lift=True, focus_lift_default=None):
    if not focus_lift:
        raise ValueError("This builder packages only the LV Boost variant")
    if focus_lift_default is not None and (not focus_lift or focus_lift_default not in (1, 2, 3)):
        raise ValueError('Startup level requires LV Boost and a level from 1 to 3')
    write_csv_inc(focus_lift)
    write_page_inc()
    write_mat_inc()
    write_sat_inc()
    write_dngcm_inc()
    res_src = HERE / 'rv_resident.S'
    variant = ['LV_BOOST=1'] if focus_lift else []
    if focus_lift_default is not None:
        variant += [f'FL_DEFAULT={focus_lift_default}']
    res = assemble(res_src, variant)
    rs = symbols(res_src, variant)
    assert rs['sat_tab'] - rs['params'] == 0x1C0, f'sat_tab 在 +0x{rs["sat_tab"] - rs["params"]:X}'
    assert rs['cm_buf'] % 8 == 0 and rs['cm_tab'] - rs['cm_buf'] == 144, 'cm_buf 對齊/大小'
    assert rs['stub_gs'] - rs['cm_tab'] == 6 * 144, 'cm_tab 之後應接 stub_gs'
    res += b'\0' * (-len(res) % 4)
    assert 0x3E200 + len(res) <= 0x40800 and 0x40800 + 0x348 + 0xFFF <= 0x42000, f'常駐 {len(res)} B 蓋到矩陣副本(T0 + 0x40800)'
    if focus_lift:
        assert 0x3200 + len(res) <= 0x5800, 'LV Boost resident overlaps matrix storage'
    tdata = fl_tables.blob()
    defs = [f'RES_LEN=0x{len(res):X}', f'TDATA_OFF=0x{len(res):X}',
            f'STUB_GS=0x{rs["stub_gs"]:X}', f'STUB_DG=0x{rs["stub_dg"]:X}',
            f'STUB_MA=0x{rs["stub_ma"]:X}', f'STUB_MB=0x{rs["stub_mb"]:X}', f'STUB_MC=0x{rs["stub_mc"]:X}',
            f'STUB_FV=0x{rs["stub_fv"]:X}', f'STUB_ML=0x{rs["stub_ml"]:X}',
            f'STUB_EF=0x{rs["stub_ef"]:X}', f'STUB_EN=0x{rs["stub_en"]:X}',
            f'STUB_SA=0x{rs["stub_sa"]:X}', f'STUB_SN=0x{rs["stub_sn"]:X}', f'STUB_MJ=0x{rs["stub_mj"]:X}',
            f'CMBUF=0x{rs["cm_buf"] - rs["params"]:X}', f'CMTAB=0x{rs["cm_tab"] - rs["params"]:X}',
            f'STUB_MO=0x{rs["stub_mo"]:X}', f'STUB_MX=0x{rs["stub_mx"]:X}',
            f'STUB_ZC=0x{rs["stub_zc"]:X}', f'STUB_ZS=0x{rs["stub_zs"]:X}',
            f'STUB_ZNC=0x{rs["stub_znc"]:X}', f'STUB_ZNS=0x{rs["stub_zns"]:X}']
    launch_src = HERE / 'rv_launch.S'
    defs += variant
    if focus_lift_default is not None:
        defs += [f'FL_START=0x{rs["fl_start"]:X}']
    launch = assemble(launch_src, defs)
    ls = symbols(launch_src, defs)
    if ls['blob'] != len(launch):
        raise SystemExit(f'launcher blob label at {ls["blob"]:#x} but code is {len(launch):#x} bytes')
    check_calls(launch, focus_lift_default is not None)
    blob = launch + res + tdata
    return blob, {'launch': len(launch), 'resident': len(res), 'tables': len(tdata),
                  'stub_gs': rs['stub_gs'], 'stub_dg': rs['stub_dg'],
                  'stub_ma': rs['stub_ma'], 'stub_mb': rs['stub_mb'], 'stub_mc': rs['stub_mc'],
                  'stub_fv': rs['stub_fv'], 'stub_ml': rs['stub_ml'], 'stub_ef': rs['stub_ef'],
                  'stub_en': rs['stub_en'], 'stub_sa': rs['stub_sa'], 'stub_sn': rs['stub_sn'], 'stub_mj': rs['stub_mj'],
                  'cm_buf': rs['cm_buf'] - rs['params'], 'cm_tab': rs['cm_tab'] - rs['params'],
                  'stub_mo': rs['stub_mo'], 'stub_mx': rs['stub_mx'], 'gltab': rs['gltab'] - rs['params'],
                  'stub_zc': rs['stub_zc'], 'stub_zs': rs['stub_zs'], 'stub_znc': rs['stub_znc'], 'stub_zns': rs['stub_zns']}


def check_calls(code, startup=False):
    """launcher 只能 blx 到四個允許的函式(movw/movt ip 之後的 blx ip)。"""
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
    lo = hi = None
    for i in md.disasm(code, 0):
        if i.mnemonic == 'movw' and i.op_str.startswith('ip,'):
            lo = int(i.op_str.split('#')[1], 0)
        elif i.mnemonic == 'movt' and i.op_str.startswith('ip,'):
            hi = int(i.op_str.split('#')[1], 0)
        elif i.mnemonic == 'blx':
            target = (hi << 16) | lo
            allowed = ALLOWED_CALLS | ({0xC0016A58, 0xC0016BC0} if startup else set())
            if target not in allowed:
                raise SystemExit(f'launcher calls 0x{target:08X}, not an allowed routine')
        elif i.mnemonic == 'bl':
            raise SystemExit(f'launcher has a direct bl at {i.address:#x}')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--default-level', type=int, choices=(1, 2, 3), default=2,
                    help='Startup LV Boost level (default: +2)')
    ap.add_argument('--fs2', action='store_true', help='Enable Fast Start 2')
    ap.add_argument('--no-shell', action='store_true', help='Omit the diagnostic USB shell')
    ap.add_argument('--out', type=pathlib.Path, required=True)
    a = ap.parse_args()
    blob, info = build_blob(True, a.default_level)
    if len(blob) > MAXLEN:
        raise SystemExit(f'blob {len(blob)} bytes exceeds MAXLEN {MAXLEN}')
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        bf = tmp / 'lv-boost.bin'
        bf.write_bytes(blob)
        cmd = [sys.executable, str(SHELL / 'build_autorun.py'), '--loader',
               '--banner', 'fpSup-DEV-LV-BOOST!', '--boot-bin', f'{bf}:0',
               '--out', str(a.out / 'AutoRun.txt'),
               '--no-shell' if a.no_shell else '--no-ep-patches']
        if a.fs2:
            cmd += ['--store-boot', '--loader-hook', '--four-box-bar',
                    '--loader-hook-mark', '0xC072E040']
        for site, word, _ in hook_sites(True):
            f = tmp / f'site_{site:08x}.bin'
            f.write_bytes(word)
            cmd += ['--also-bin', f'0x{site:08X}:{f}']
        a.out.mkdir(parents=True, exist_ok=True)
        subprocess.run(cmd, check=True)
    (a.out / 'lv-boost.bin').write_bytes(blob)
    print(f'LV Boost: {len(blob)} bytes; default +{a.default_level}; {info}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
