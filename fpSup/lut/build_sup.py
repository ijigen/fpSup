#!/usr/bin/env python3
"""Build the Loader v4 LUT development sup and a separate prepared LUT asset.

No device I/O. FSB4, services v6 minimum, cached private code/data; only the file
object and chunk scratch are DMA/uncached. Card builds include the shared v4
page renderer by default. Calibrated owned-frame monitoring is still pending.
"""
import argparse
import os
import hashlib
import json
from pathlib import Path
import struct
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
FPSUP=HERE.parent
ROOT=FPSUP.parent
sys.path.insert(0,str(HERE))
sys.path.insert(0,str(FPSUP/'loader-v4'))
import build_v4 as B
import names_v4 as NV                     # the card name, display name and version (Bei 2026-11-12: always versioned)
from cinemadng import COLOR_SPACES, GAMMAS, COMMON_GAMMAS, BLACKMAGIC_GAMMAS, Selection, catalogue
from color import from_xyz_matrix, transfer
from cube import Cube

Q=1<<20
CURVE_N=27*256+1
HEADER=256
# The prepared table's capacity.  A library build borrows it from the firmware allocator for one load and
# returns it (native/borrow.c, 2026-11-07: resident, it made MOV recording freeze); only the reference build
# (no --library) keeps it in its block.  env LUT_ASSET_CAP: diagnostic builds only (the size borrowed, or the
# reference build's resident area; it no longer changes a library build's block).
CAPACITY=int(os.environ.get('LUT_ASSET_CAP',4*1024*1024))
LVB_CAP=0x400                    # native/lvb.c LVB_CAP: what the ISP / DNG hooks read; the shown row's set is borrowed
                                 # (Bei 2026-11-10; was 0x1D000 = four resident sets)
CONFIG=56                        # native/lut4.c struct cfg: 14 words
CONV_CAP=0x400                   # native/conv.c CONV_CAP: struct conv_keep (the conversion's work is borrowed)
SOURCE=HERE/'native/lut4.c'


def sha(data): return hashlib.sha256(data).hexdigest()
def align(n,a=64): return (n+a-1)&~(a-1)


def fnv(data):
    value=2166136261
    for byte in data: value=((value^byte)*16777619)&0xffffffff
    return value


def quantize(values,limit):
    values=np.asarray(values,dtype=np.float64)
    if not np.isfinite(values).all() or np.any(np.abs(values)>limit):
        raise ValueError('value exceeds the explicit native Q20 range')
    return np.rint(values*Q).astype('<i4')


def asset(cube,color='rec709',gamma='gamma24',strength=100,source_identity=None):
    selection=Selection(color,gamma)
    selection.encoding()                        # no unverified fallback
    if strength not in (0,25,50,75,100): raise ValueError('native strength is 0/25/50/75/100 percent')
    matrices=[]
    for choice in COLOR_SPACES.values():
        matrices.append(np.zeros((3,3)) if choice.gamut is None else from_xyz_matrix(choice.gamut))
    payload=bytearray(quantize(matrices,16).tobytes())
    # Exponent/mantissa grid: every Q20 integer below 2^-12 is exact; above
    # it, 256 intervals/octave. Covers linear -128..128, with no hidden clamp.
    values=[0.]
    for exponent in range(27):
        values.extend(((1<<exponent)*(1+np.arange(256)/256)/Q).tolist())
    values.append(128.)
    grid=np.asarray(values[1:])
    assert len(grid)==CURVE_N
    for key in COMMON_GAMMAS:
        curve=GAMMAS[key].curve
        for sign in (1,-1):
            result=np.zeros(CURVE_N) if curve is None else transfer(sign*grid,curve)
            payload.extend(quantize(result,2047).tobytes())
    matrix_off=HEADER
    curve_off=HEADER+8*9*4
    n1=0 if cube.table1d is None else len(cube.table1d)
    n3=0 if cube.table3d is None else len(cube.table3d)
    one_off=HEADER+len(payload) if n1 else 0
    if n1: payload.extend(quantize(cube.table1d,1024).tobytes())
    three_off=HEADER+len(payload) if n3 else 0
    if n3: payload.extend(quantize(cube.table3d,1024).tobytes())
    total=HEADER+len(payload)
    if total>CAPACITY: raise ValueError('prepared LUT exceeds 4 MiB resident limit')
    header=bytearray(HEADER)
    fields=[0x31554c46,1,HEADER,total,0,n1,n3,CURVE_N,matrix_off,curve_off,
            one_off,three_off,list(COLOR_SPACES).index(color),list(COMMON_GAMMAS).index(gamma),strength,1]
    struct.pack_into('<16I',header,0,*fields)
    for offset,domain in ((64,cube.range1d),(100,cube.range3d)):
        quantized=quantize(domain,128).reshape(2,3)
        if np.any(quantized[1]<=quantized[0]): raise ValueError('domain collapses at native Q20 precision')
        struct.pack_into('<9i',header,offset,*quantized.reshape(-1).tolist(),0,0,0)
    header[136:168]=bytes.fromhex(source_identity or cube.sha256)
    title=(cube.title or 'User monitoring LUT').encode('utf-8')[:63]
    title=title.decode('utf-8','ignore').encode('utf-8')
    header[168:168+len(title)]=title
    struct.pack_into('<I',header,16,fnv(header+payload))
    return bytes(header+payload)


VFP=['-mfloat-abi=softfp','-mfpu=vfpv3-d16','-fno-math-errno']   # native/jfit.c (conv.c): the kernel saves d0-d15


CHECKER_FILE=HERE/'checker_q20.bin'      # checker_q20(): the data the sup carries; --write-checker remakes it


def checker_q20():
    """The ColorChecker 24 at -1 / 0 / +1 EV as camera RGB (lut_batch_eval.sample_sets()['色卡'], jft.convert's
    score), Q20 int32, 72 x 3, then the grey axis -- data in the file: the sup has no .rodata.  Read from
    checker_q20.bin (the research tree that computes it, projects/lut-sup/probes, is not public);
    checker_q20_compute() is how it was made."""
    return CHECKER_FILE.read_bytes()


def checker_q20_compute():
    import sys
    sys.path.insert(0,str(ROOT/'projects/lut-sup/probes'))
    import numpy as np
    import lut_batch_eval as E
    chk=E.sample_sets()['色卡']
    assert chk.shape==(72,3)
    import jft                                         # + the grey axis (conv.c CONV_GREY), the same values jft.convert fits
    grey=jft.grey_samples()
    assert grey.shape==(168,3)
    return np.round(chk*(1<<20)).astype('<i4').tobytes()+np.round(grey*(1<<20)).astype('<i4').tobytes()


def strings():
    # \fpSup\LUT\ is the user's cubes alone (2026-11-06): the sup's own files are in \fpSup\LUTDATA\
    return ['\\fpSup\\LUTDATA\\ACTIVE.LUT', 'LUT file / status','LUT color space','LUT gamma value',
            'LUT strength value','LUT monitoring', *[c.label for c in COLOR_SPACES.values()],
            *[GAMMAS[k].label for k in COMMON_GAMMAS], *[GAMMAS[k].label for k in BLACKMAGIC_GAMMAS],
            '0%','25%','50%','75%','100%','ACTIVE.LUT; LV pending','LUT file missing',
            'LUT file invalid','Selected model pending',
            'LUT color family','LUT gamma family','LUT strength range',
            'ACES / Adobe / BMD','P3 D60 / P3 D65 / 2020','Rec.709 / sRGB',
            'Adobe / 2.4 / 2.6','Linear / Rec.709 / sRGB','Blackmagic',
            '0 / 25 / 50%','75 / 100%', 'Color', '\\fpSup\\UI\\COLOR.BIN', 'FT_COLOR',
            'Active LUT','LUT manager','Enabled in list','Enable','Disable','Settings',
            'Enabled','Disabled','Setup required','Model pending','Off','Active','Save failed',
            'No LUT selected','FT_LUTMGR','FT_LUTSET','FT_LUTSEL','','.LUT',   # 62: was DATA\ (no prepared assets since 11-06)
            'LUT loaded','Source file missing','Library invalid','Unable to load LUT',
            '# FPSUP_METADATA_V1\n# FPSUP_SOURCE_ID ', '\n# FPSUP_USER_INPUT_COLOR_SPACE ',
            '\n# FPSUP_USER_INPUT_GAMMA ', '\n# FPSUP_OUTPUT_COLOR_SPACE rec709\n# FPSUP_OUTPUT_GAMMA gamma24\n#',
            'unset','# FPSUP_INPUT_COLOR_SPACE ','# FPSUP_INPUT_GAMMA ','','.cube',   # 75: was SOURCES\ (11-06)
            *COLOR_SPACES, *COMMON_GAMMAS, *BLACKMAGIC_GAMMAS, '# FPSUP_METADATA_END\n',
            'Color space','Gamma',                    # 94, 95: the two settings rows (user 2026-10-24)
            'TITLE','LUT_1D_SIZE','LUT_3D_SIZE','DOMAIN_MIN','DOMAIN_MAX','LUT_1D_INPUT_RANGE','LUT_3D_INPUT_RANGE',
            'User monitoring LUT',                    # 96..103: native/import.c (no .rodata in the sup)
            '\n# FPSUP_USER_COLOR_MATRIX ',              # 104: cube4.c cube_header
            '# FPSUP_USER_INPUT_COLOR_SPACE ','# FPSUP_USER_INPUT_GAMMA ','# FPSUP_USER_COLOR_MATRIX ',   # 105..107: cube_decode
            '# FPSUP_COLOR_MATRIX ','# FPSUP_COLOR_MATRIX1 ','# FPSUP_COLOR_MATRIX2 ',   # 108..110: the author's (import.c)
            'standard','off','custom',               # 111..113: library.MATRICES, MAT_*
            'Color matrix','Standard','OFF','Custom',   # 114..117: the settings row (user 2026-11-03)
            'Converting ','% match','Convert failed','Not converted',   # 118..121: native/conv.c
            'LC_ConvEnd','LC_ConvStart',              # 122, 123: conv.c's app states (manager_page.CONV_EVENT / BUSY_EVENT)
            'Match ']                                 # 124: conv.c conv_match (the ColorChecker chart)


SUP_ID='LUT4'


def version_word(text):
    """'0.1.0test' -> 0x000100 (as build_colshare.version_word)."""
    major,minor,patch=(int(''.join(ch for ch in x if ch.isdigit()) or 0) for x in text.split('.')[:3])
    return major<<16|minor<<8|patch


SUP_FILE=NV.file_name(SUP_ID)             # LUT_v0.1.0test.BIN
SUP_NAME=NV.display(SUP_ID)
SUP_VERSION=version_word(NV.version(SUP_ID))


def build_sup(source=SOURCE,collection=None,name=SUP_NAME,version=SUP_VERSION):
    import tempfile
    with tempfile.TemporaryDirectory(prefix='lut4-build-') as td:
        # -mno-movt: function addresses from literal pools.  Apple clang's assembler refuses a
        # movw/movt pc-relative pair spanning > 32 KiB ("Relocation Not In Range"); lvb.c pushed
        # library4.c's row callbacks past it (2026-11-04).
        text=B.compile_unit(Path(td),Path(source),'sup_entry',['-I',str(HERE/'native'),'-I',str(FPSUP/'colshare'),'-mno-movt',*VFP,*([f"-DLUT_BISECT={int(os.environ['LUT_BISECT'])}"] if os.environ.get('LUT_BISECT') else [])])
    code_off=B.SL4_HEADER_LEN+CONFIG
    body=bytearray(CONFIG+len(text.code))
    body[CONFIG:]=text.code
    body.extend(bytes(-len(body)%4))
    string_off=B.SL4_HEADER_LEN+len(body)
    words=strings()
    offsets=[]
    body.extend(bytes(4*len(words)))
    for word in words:
        offsets.append(B.SL4_HEADER_LEN+len(body))
        body.extend(word.encode()+b'\0')
    struct.pack_into('<'+str(len(words))+'I',body,string_off-B.SL4_HEADER_LEN,*offsets)
    catalogue_off=clist_off=import_off=0
    body.extend(bytes(-len(body)%4));chk_off=B.SL4_HEADER_LEN+len(body)   # conv.c: the ColorChecker, camera RGB Q20
    body.extend(checker_q20())
    if collection is not None:
        import library
        import import_ui
        body.extend(bytes(-len(body)%4));catalogue_off=B.SL4_HEADER_LEN+len(body)
        body.extend(library.binary(collection))
        # the COLOR list's rows are COL-Share's since 2026-11-07 (fpSup/colshare; cols.c): no section here
        # any .cube copied to the card (import_ui / native/import.c)
        body.extend(bytes(-(B.SL4_HEADER_LEN+len(body))%8));import_off=B.SL4_HEADER_LEN+len(body)
        body.extend(import_ui.section(import_off))
    probe=B.make_sup(bytes(body),code_off+text.functions['sup_entry'],'LUT4',name=name,
                     flags=B.SL_F_CACHED_OK,min_svc=6,version=version)
    import import_ui
    state_off=align(len(probe)); io_off=state_off+4096; icons_off=io_off+8192
    # library: lvb's small region, conv's resident state.  Borrowed, not resident (Bei 2026-11-10): the asset
    # area, the shown row's ISP set, the COLOR tile while COL-Share copies it (import.c), a .JFT being read.
    # Reference: the resident asset.
    asset_off=0 if collection is not None else align(icons_off)
    lvb_off=align(icons_off) if collection is not None else 0                # native/lvb.c's region (LVB_CAP)
    conv_off=align(lvb_off+LVB_CAP) if lvb_off else 0                     # native/conv.c's (CONV_CAP)
    end=conv_off+CONV_CAP if conv_off else asset_off+CAPACITY
    struct.pack_into('<14I',body,0,0x3443544c,state_off,io_off,asset_off,CAPACITY,string_off,len(words),catalogue_off,clist_off,
                     icons_off,import_off,lvb_off,conv_off,chk_off if conv_off else 0)
    blob=B.make_sup(bytes(body),code_off+text.functions['sup_entry'],'LUT4',name=name,
                    flags=B.SL_F_CACHED_OK,min_svc=6,version=version,
                    block_size=end,dma=(io_off,8192))
    assert len(blob)==len(probe) and state_off>=len(blob)
    facts=dict(code_offset=code_off,code_bytes=len(text.code),file_bytes=len(blob),
               block_bytes=end,state_offset=state_off,io_offset=io_off,
               lvb_offset=lvb_off,conv_offset=conv_off,checker_offset=chk_off,
               asset_offset=asset_off,asset_capacity=CAPACITY,asset_borrowed=collection is not None,
               library_offset=catalogue_off,clist_offset=clist_off,import_offset=import_off,icons_offset=icons_off,
               entries={k:code_off+v for k,v in text.functions.items() if k.startswith(('sup_','lut4_'))})
    return blob,facts


def identity():
    return Cube.parse(b'TITLE "Diagnostic identity; not camera calibration"\nLUT_3D_SIZE 2\n'
                      b'0 0 0\n1 0 0\n0 1 0\n1 1 0\n0 0 1\n1 0 1\n0 1 1\n1 1 1\n')


def colshare_file():
    """(card name, bytes) of COL-Share: LUT's COLOR rows need it (Bei 2026-11-07 #2: the merge page brings it)."""
    sys.path.insert(0,str(FPSUP/'colshare'))
    import build_colshare as CS
    blob,facts=CS.build()
    return 'fpSup/'+facts['file'],blob


def build(output,cube=None,color='rec709',gamma='gamma24',strength=100,*,card=False,debug=False,
          splash=False,instant=False,fast=False,ui=True,collection=None,info_path=None,colshare=True,product=None):
    """Card files under `output`.  \\fpSup\\LUT\\ holds only .cube files (a --library's, copied as they are);
    the sup's own files are in \\fpSup\\LUTDATA\\.  The build record is not on the card: it is returned,
    and written to `info_path` (a new file outside the card) when one is given."""
    if collection is not None:
        import library
        collection=library.refresh(collection)
    cube=cube or identity()
    prepared=asset(cube,color,gamma,strength)
    # product: (card file, display name, version word) -- build_v4_lut.py, names_v4 (merge page 2026-11-12)
    sup_file,*named=product or (SUP_FILE,)
    sup,facts=build_sup(collection=collection,**dict(zip(('name','version'),named)))
    if (debug or splash or instant or fast) and not card: raise ValueError('boot options require --card')
    files={'fpSup/'+sup_file:sup,'fpSup/LUTDATA/ACTIVE.LUT':prepared}    # the reference mode's one asset
    if collection is not None:
        import library
        files.pop('fpSup/LUTDATA/ACTIVE.LUT')
        files.update(library.assets(collection))      # the cubes themselves, into \fpSup\LUT\
    if ui:
        from color_ui import data_file
        files['fpSup/UI/COLOR.BIN']=data_file()[0]
    if card and colshare and collection is not None:
        name,blob=colshare_file();files[name]=blob                   # LUT's COLOR rows: COL-Share's
    if card:
        autorun,loader,_=B.boot_card(splash=splash,instant=instant,fast=fast,slim=True,ui=ui)
        files.update({'AutoRun.txt':autorun,'fpSup/LOADER.BIN':loader,'fpSup/SUPMGR.BIN':B.supmgr_sup()})
        if ui:
            for name,data in B.ui_files().items(): files[f'fpSup/UI/{name}']=data
        if debug: files['fpSup/SHELL.BIN']=B.shell_sup()
        if splash:
            for i,pixels in enumerate(B.V3.splash_frames()): files[f'fpSup/UI/{i}.BIN']=pixels
    info=dict(schema='fpSup-lut4-development-1',sup=sup_file,format='FSB4',service_version=6,
              loader_service_version=B.SL4_SVC_VERSION,ui_registered_rows=1,private_setting_rows=8,ui_popup_max_items=3,
              cached_private_block=True,dma='8 KiB file object + read scratch only',**facts,
              source_cube=cube.summary(),selection=Selection(color,gamma).summary(),strength_percent=strength,
              output='Rec.709 D65 / Gamma 2.4; normalized full',
              native_sample_format='signed Q20 XYZ D65 -> signed Q20 Rec.709 Gamma2.4',
              native_sample_limit=4096,xyz_input_limit=64,selected_linear_limit=128,
              lookup='original 1D + 3D nodes quantized Q20; tetrahedral, no grid resampling',
              strength_steps=[0,25,50,75,100],asset_checksum='FNV-1a accidental corruption check; not authentication',
              live_view_backend_connected=False,on_camera_verified=False,ui_renderer_present=bool(card and ui),
              ui_architecture='One Color home entry + private fpsup-ui settings page',
              ui_string_model='private address IDs and borrow ranges; no uishare runtime',
              lut_ui_on_camera_verified=False,
              settings_persistence='input comments in cube; enabled/active/strength in guarded BIN' if collection is not None else 'package defaults only; UI changes are volatile until next boot',
              requirements_remaining=([] if card and ui else ['include Loader v4 page renderer'])+
                                     ['on-camera LUT UI acceptance','calibrated, owned monitoring route',
                                      'native ISP + CPU residual integration and performance','settings writeback'],
              card=card,debug=debug,splash=splash,instant=instant,fast=fast,ui=bool(card and ui),
              files={name:dict(bytes=len(data),sha256=sha(data)) for name,data in files.items()},
              source_hashes={str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in
                             [SOURCE,HERE/'native/lut4.h',HERE/'native/color_ui.c',HERE/'native/library4.c',
                              HERE/'native/library4.h',HERE/'native/cube4.c',HERE/'cube_metadata.py',HERE/'color_ui.py',B.FPSUP_UI/'fpsup_ui.c',
                              Path(__file__).resolve(),HERE/'color.py',HERE/'cinemadng.py',HERE/'native/cols.c',
                              FPSUP/'colshare/colshare.h',FPSUP/'colshare/colshare.c',FPSUP/'colshare/colshare_ui.py',
                              B.HERE/'sloader4.h',B.HERE/'build_v4.py']})
    if collection is not None:
        info['library']=library.summary(collection);info['source_cube']=None
        info['selection']=None;info['strength_percent']=None;info['max_library_items']=library.MAX_LUTS
        info['requirements_remaining'].remove('settings writeback')
        info['source_hashes']['fpSup/lut/library.py']=sha((HERE/'library.py').read_bytes())
    if card:
        for path in [B.HERE/'sloader4.c',B.HERE/'sloader4_entry.S',B.HERE/'supmgr.c',
                     B.FPSUP_UI/'fpsup_ui.c',
                     B.V3.HERE/'build_v3.py',B.SHELL_DIR/'build_autorun.py',
                     *[B.SHELL_DIR/'asm'/name for name in
                       ('loader.S','stage2.S','store_boot.S','store_boot_slim.S','lhook_stub.S',
                        'abort.S','entries.S','splash_finish.S')]]:
            info['source_hashes'][str(path.relative_to(ROOT))]=sha(path.read_bytes())
        if ui:
            for path in [B.HERE/'fpsup_home.c']:
                info['source_hashes'][str(path.relative_to(ROOT))]=sha(path.read_bytes())
    if ui:
        for path in [B.FPSUP/'uishare/tab'/name for name in
                     ('build_fp4.py','home4_page.py','manage_page.py','manager_logo.py','ft6_page.py','build_ft6.py')]:
            info['source_hashes'][str(path.relative_to(ROOT))]=sha(path.read_bytes())
    info['menu']=catalogue()                     # was fpSup/LUT/menu.json on the card (until 2026-11-06)
    out=Path(output)
    if info_path is not None:
        info_path=Path(info_path).resolve()
        if info_path.is_relative_to(out.resolve()): raise ValueError('the build record does not go on the card')
        if info_path.exists(): raise FileExistsError(info_path)
    out.mkdir(parents=True,exist_ok=False)
    for name,data in files.items():
        target=out/name; target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as stream: stream.write(data)
    if info_path is not None:
        info_path.parent.mkdir(parents=True,exist_ok=True)
        with info_path.open('x') as stream: stream.write(json.dumps(info,ensure_ascii=False,indent=2)+'\n')
    return info


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,help='new local output directory (required unless --write-checker)')
    ap.add_argument('--info',type=Path,help='also write the build record (JSON) here: a new file, not inside --out')
    sources=ap.add_mutually_exclusive_group()
    sources.add_argument('--cube',type=Path,help='default: labeled diagnostic identity fixture')
    sources.add_argument('--library',type=Path,help='per-cube library manifest from fplut library-import')
    ap.add_argument('--input-space',choices=list(COLOR_SPACES),default='rec709')
    ap.add_argument('--input-gamma',choices=list(GAMMAS),default='gamma24')
    ap.add_argument('--strength',type=int,choices=(0,25,50,75,100),default=100)
    ap.add_argument('--card',action='store_true',help='include the unchanged shared v4 boot envelope')
    ap.add_argument('--debug',action='store_true',help='include v4 SHELL.BIN')
    ap.add_argument('--splash',action='store_true')
    ap.add_argument('--instant',action='store_true')
    ap.add_argument('--fast',action='store_true')
    ap.add_argument('--colshare',action=argparse.BooleanOptionalAction,default=True,
                    help='a --card --library card carries COL-Share (default): without it LUT has no COLOR rows')
    ap.add_argument('--ui',action=argparse.BooleanOptionalAction,default=True,
                    help='include shared Loader v4 UI in a card (default); --no-ui for offline core checks')
    ap.add_argument('--write-checker',action='store_true',help='remake checker_q20.bin from projects/lut-sup/probes and stop')
    a=ap.parse_args()
    if a.write_checker:
        CHECKER_FILE.write_bytes(checker_q20_compute());print(CHECKER_FILE);return
    if a.out is None: ap.error('--out is required')
    collection=None
    if a.library:
        import library
        collection=library.read(a.library)
    info=build(a.out,Cube.read(a.cube) if a.cube else None,a.input_space,a.input_gamma,a.strength,
               card=a.card,debug=a.debug,splash=a.splash,instant=a.instant,fast=a.fast,ui=a.ui,collection=collection,
               info_path=a.info,colshare=a.colshare)
    print(json.dumps(dict(output=str(a.out.resolve()),sup_bytes=info['file_bytes'],
                         resident_bytes=info['block_bytes'],live_view_backend_connected=False),indent=2))


if __name__=='__main__': main()
