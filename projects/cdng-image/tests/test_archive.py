import hashlib
import io
from pathlib import Path
import struct
import tempfile
import threading
import unittest

import imagecodecs
import numpy as np
import pycdlib
import rawpy
import tifffile

from cdng_image.dng import compress,LAYOUT
from cdng_image.iso import StreamISO
from cdng_image.packer import pack

ROOT=Path(__file__).resolve().parents[3]
REAL=ROOT/'bmd_gen1/resolve_test/0_fp_original.dng'
COMPRESSED=ROOT/'research/slimRAW/captures/A001_083_FHD_f07_compressed_288x368.DNG'


def synthetic(bits,width=66,height=35,smooth=False):
    rng=np.random.default_rng(bits)
    a=rng.integers(0,min(2**bits,512),(height,width),dtype=np.uint16)
    if smooth:
        y,x=np.indices((height,width));a=((x//2+y//2)%64+rng.integers(0,3,(height,width))).astype(np.uint16)
    raw=(a.astype('<u2').tobytes() if bits==16 else a.astype('u1').tobytes() if bits==8
         else np.packbits(((a[...,None] >> np.arange(bits-1,-1,-1)) & 1).astype('u1').reshape(height,-1),axis=1,bitorder='big').tobytes())
    # All metadata is deliberately stored before a single packed RAW strip.
    tags={256:(4,1,width),257:(4,1,height),258:(3,1,bits),259:(3,1,1),262:(3,1,32803),
          273:(4,1,512),277:(3,1,1),278:(4,1,height),279:(4,1,len(raw)),
          33421:(3,2,0x00020002),33422:(1,4,0x02010100),
          50706:(1,4,0x00000401),50707:(1,4,0x00000401)}
    prefix=bytearray(512);prefix[:8]=b'II*\0'+struct.pack('<I',8)
    struct.pack_into('<H',prefix,8,len(tags))
    for i,(tag,(typ,count,value)) in enumerate(sorted(tags.items())):
        struct.pack_into('<HHII',prefix,10+12*i,tag,typ,count,value)
    return bytes(prefix)+raw,a


class DNGTests(unittest.TestCase):
    def test_depths_and_edge_tiles(self):
        for bits in (8,10,12,14,16):
            data,a=synthetic(bits)
            for effort in ('fast','balanced','max'):
                out,info=compress(data,effort)
                with tifffile.TiffFile(io.BytesIO(out)) as tf:
                    self.assertTrue(np.array_equal(a,tf.pages[0].asarray()),(bits,effort))
                self.assertTrue(info['pixel_verified'])

    def test_real_pixels_metadata_and_recompression(self):
        for src in (REAL,COMPRESSED):
            data=src.read_bytes()
            before=rawpy.imread(io.BytesIO(data)).raw_image.copy()
            out,_=compress(data,'max')
            self.assertLess(len(out),len(data))
            with rawpy.imread(io.BytesIO(out)) as raw:self.assertTrue(np.array_equal(before,raw.raw_image))
            with tifffile.TiffFile(io.BytesIO(data)) as a,tifffile.TiffFile(io.BytesIO(out)) as b:
                for tag in a.pages[0].tags.values():
                    if tag.code not in LAYOUT:
                        # Compare original entry bytes, including all metadata pointers.
                        self.assertEqual(data[tag.offset:tag.offset+12],out[b.pages[0].tags[tag.code].offset:b.pages[0].tags[tag.code].offset+12])
            old_raw=min(tifffile.TiffFile(io.BytesIO(data)).pages[0].dataoffsets)
            self.assertEqual(data[8:old_raw],out[8:old_raw])

    def test_lossy_and_truncated_rejected(self):
        data,_=synthetic(12)
        with self.assertRaises(Exception):compress(data[:-20])
        data=bytearray(data)
        n=struct.unpack_from('<H',data,8)[0]
        for i in range(n):
            at=10+12*i
            if struct.unpack_from('<H',data,at)[0]==259:struct.pack_into('<I',data,at+8,34892)
        with self.assertRaises(ValueError):compress(bytes(data))


class ImageTests(unittest.TestCase):
    def test_joliet_many_names_nested_empty_and_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            iso=Path(directory)/'test.iso';payloads={f'中文資料/filename_{i:04}.DNG':bytes([i%256])*i for i in range(150)}
            with iso.open('wb+') as file:
                w=StreamISO(file,[(name,False,0) for name in payloads]+[('empty',True,0)])
                for name,data in payloads.items():w.add(name,(data,))
                w.finish()
            reader=pycdlib.PyCdlib();reader.open(str(iso))
            try:
                for name,data in payloads.items():
                    buf=io.BytesIO();reader.get_file_from_iso_fp(buf,joliet_path='/'+name);self.assertEqual(buf.getvalue(),data)
            finally:reader.close()

    def test_name_rejections(self):
        for paths in [[('A.dng',False,0),('a.DNG',False,0)],[('😀.dng',False,0)],[('bad:name',False,0)]]:
            with self.assertRaises(ValueError):StreamISO(io.BytesIO(),paths)

    def test_pack_and_guardrails(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);src=root/'source';src.mkdir();(src/'A.dng').write_bytes(REAL.read_bytes())
            (src/'Audio.WAV').write_bytes(b'audio\x00\x01')
            result=pack(src,root/'clip.iso',workers=2)
            self.assertTrue(result['image_checksums_verified']);self.assertEqual(result['files'],2)
            with self.assertRaises(FileExistsError):pack(src,root/'clip.iso')
            with self.assertRaises(ValueError):pack(src,src/'inside.iso')
            cancel=threading.Event();cancel.set()
            with self.assertRaises(InterruptedError):pack(src,root/'cancel.iso',cancel=cancel)
            self.assertFalse((root/'cancel.iso').exists());self.assertFalse(list(root.glob('*.partial')))
            (src/'link').symlink_to(src/'A.dng')
            with self.assertRaises(ValueError):pack(src,root/'links.iso')

if __name__=='__main__':unittest.main()
