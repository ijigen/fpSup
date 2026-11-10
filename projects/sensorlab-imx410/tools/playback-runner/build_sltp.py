#!/usr/bin/env python3
"""Offline build only: a standalone loader-v4 SLTP.BIN. No camera imports."""
import argparse
import hashlib
import json
import pathlib
import struct
import sys
import tempfile

HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parents[3]
sys.path.insert(0,str(ROOT/'fpSup/loader-v4'))
import build_v4 as B

def build(src=None):
    src=pathlib.Path(src or HERE/'sltp.c')
    with tempfile.TemporaryDirectory(prefix='sltp-build-') as tmp:
        unit=B.compile_unit(pathlib.Path(tmp),src,'sup_entry')
    entry=48+unit.functions['sup_entry']
    blob=B.make_sup(unit.code,entry,'SLTP',version=1,min_svc=5,flags=B.SL_F_CACHED_OK,name='SL playback trial')
    state_off=(len(blob)+63)&~63
    block=state_off+256
    blob=blob[:12]+struct.pack('<I',block)+blob[16:]
    # context_word's emitted ADR/B/zero literal; fail closed if compiler shape moves.
    at=48+(unit.functions['context_word']&~1)
    pattern=bytes.fromhex('00a001e000000000')
    window=blob[at:at+64]
    if window.count(pattern)!=1:raise B.BuildError('review changed context literal encoding')
    mutable=at+window.index(pattern)+4
    info=dict(file='SLTP.BIN',bytes=len(blob),sha256=hashlib.sha256(blob).hexdigest(),
              source_sha256=hashlib.sha256(src.read_bytes()).hexdigest(),entry=entry,
              state_off=state_off,block_size=block,code_bytes=len(unit.code),
              mutable_file_offsets=[mutable],state_bytes=176,
              functions={k:48+v for k,v in unit.functions.items()})
    return blob,info

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=pathlib.Path,required=True)
    a=ap.parse_args();blob,info=build()
    (a.out/'fpSup').mkdir(parents=True,exist_ok=True)
    (a.out/'fpSup/SLTP.BIN').write_bytes(blob)
    (a.out/'build.json').write_text(json.dumps(info,indent=2)+'\n')
    print(info['file'],info['bytes'],info['sha256'])
