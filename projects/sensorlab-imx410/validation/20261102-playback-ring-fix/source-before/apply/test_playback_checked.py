#!/usr/bin/env python3
"""Selected-clip playback: real tag/profile/canvas/prepare-callers in ROM.

TIFF helpers supply declared tags. SelectedCam stubs BE080; NativePrepare runs
BE080 and its allocation wrapper, with allocator/file-ring/RTOS/configurator
services stubbed. NativeSizing executes FieldAngle arithmetic. These verify
admission, row pitch, identity and clean refusal, not real DMA, available pool
memory, playback timing, or LCD pixels. No camera I/O.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import unittest
import test_apply as T
from unicorn import UC_HOOK_CODE

SOURCE = None
EVIDENCE = []


def movie(raster=(2016,1330), bits=12, **kw):
    tags = T.clip(raster, (raster[0]-16,raster[1]-10), bits=bits, **kw)
    tags[0x103] = [1]
    return tags


class SelectedCam(T.V1Cam):
    STREAM = {0xC05C0998:'frame_position',0xC05C09E0:'reader_start',
              0xC05BCC38:'worker_start',0xC05BCB60:'rate_info',0xC05BCFF0:'stream_start'}
    def __init__(self):
        super().__init__(src=SOURCE)
        for address,name in self.STREAM.items(): self.stub(address,name)
        self.stub(0xC00C1508,'fixture_tiff_init')
        self.put(T.WORK+0x7108,30000)
        assert self.init() == T.AP_OK

    def _hook(self,mu,addr,size,data):
        if addr==0xC00C1508:
            self.put(self.r(T.UC_ARM_REG_R0),T.TIFF)
            return self.ret(0)
        if addr in self.STREAM:
            self.calls.append((self.STREAM[addr],self.r(T.UC_ARM_REG_R0),self.r(T.UC_ARM_REG_R1)))
            return self.ret(T.WORK+0x7100 if self.STREAM[addr]=='rate_info' else 0)
        return super()._hook(mu,addr,size,data)

    def select(self, tags, file_id=17):
        # Isolated geometry fixture. test_playback_entry runs the actual v2/v11
        # order and native TIFF parser on recorded file bytes instead.
        self.put(T.OBJ+0x88,file_id)
        self.put(T.OBJ+0x54,tags.get(0xC620,[0,0])[0])
        self.put(T.OBJ+0x58,tags.get(0xC620,[0,0])[1])
        self.header(self.header_bytes(tags.get(0x103)))
        self.info(tags)

    @staticmethod
    def header_bytes(compression):
        entry=struct.pack('<HHII',0x103,3,1,compression[0]) if compression else b''
        return b'II*\0'+struct.pack('<IH',8,int(bool(compression)))+entry+bytes(4)

    def header(self,data):
        """Execute the real v11 parse callsite and hook; TIFF init alone is a stub."""
        sp=T.STACK-0x2000
        self.mu.mem_write(T.WORK+0xE000,data or bytes(1))
        for reg,val in ((T.UC_ARM_REG_SP,sp),(T.UC_ARM_REG_R0,T.WORK+0xD000),
                        (T.UC_ARM_REG_R1,T.WORK+0xE000),(T.UC_ARM_REG_R2,len(data)),
                        (T.UC_ARM_REG_R3,2),(T.UC_ARM_REG_R4,T.OBJ)):
            self.mu.reg_write(reg,val)
        self.put(sp,0)
        self.mu.emu_start(0xC05BDC9C,0xC05BDCA0,**T.emu_cap(1_000_000))
        if self.error:raise self.error
        assert self.r(T.UC_ARM_REG_PC)==0xC05BDCA0

    def prepare(self, stream=False):
        # state 0 takes the same pre-decode calls without starting any task.
        return self.call(T.PREP_DE28,T.OBJ,1) if stream else self.call(T.PREP_DFA0,T.OBJ,0x1D,1)

    def profile(self, config=None):
        self.mu.mem_write(T.KPAR,bytes(0x40))
        w,h,en = ((config[1],config[2],config[4]) if config else
                  (self.w(T.OBJ+0x54),self.w(T.OBJ+0x58),self.w(T.OBJ+0xA8)))
        self.put(T.KPAR+8,w)
        self.put(T.KPAR+12,h)
        self.put(T.KPAR+0x20,en)
        entry=self.call(T.KEYBLD_FN,T.KOBJ,T.KPAR)
        pid=self.w(entry+4)
        return pid,self.canvas(pid)


class NativePrepare(SelectedCam):
    """Run BE080 and its 80 MiB allocation wrapper from ROM. File-ring,
    allocator, RTOS/worker and configurator services are declared fixtures;
    the captured configurator arguments then feed the real key/canvas code.
    """
    SERVICES = {
        0xC001A048:'log',0xC05BE610:'cleanup',0xC05BC7E8:'engine_init',
        0xC05C2D10:'file_ring',0xC05C1818:'reader_init',0xC05C08E8:'reader_reset',
        0xC05C08A8:'reader_bind',0xC05BCD70:'worker_init',0xC05C1710:'reader_seek',
        0xC05C0958:'reader_range',0xC0015058:'memset',0xC0021C00:'state',0xC0021C40:'state',
        0xC0436590:'configurator',0xC04368F8:'configure',0xC001CF78:'pool',
        0xC001D038:'allocate',0xC0011130:'assert'}

    def __init__(self):
        super().__init__()
        self.configured=[];self.allocations=[];self.native_seen=set()
        self.rate_valid=True
        del self.by_addr[T.V1FW['BE080']]
        self.mu.mem_write(T.V1FW['BE080'],struct.pack('<I',T.iw(T.V1FW['BE080'])))
        for address,name in self.SERVICES.items():self.stub(address,name)
        self.put(T.OBJ+0x30,0x19)
        self.put(T.OBJ+0xA0,4*1024*1024)  # declared file-size fixture
        self.put(T.WORK+0x7100,1)

    def _hook(self,mu,addr,size,data):
        if addr in self.SERVICES:
            name=self.SERVICES[addr]
            r=[self.r(x) for x in (T.UC_ARM_REG_R0,T.UC_ARM_REG_R1,T.UC_ARM_REG_R2,T.UC_ARM_REG_R3)]
            self.calls.append((name,*r[:2]))
            if name=='assert':raise AssertionError('native allocation assert reached')
            if name=='memset':mu.mem_write(r[0],bytes([r[1]&255])*r[2]);return self.ret(r[0])
            if name=='pool':return self.ret(r[0])
            if name=='allocate':self.allocations.append(r[:3]);return self.ret(0x4D000000)
            if name=='state':return self.ret(T.WORK+0x7400)
            if name=='configurator':return self.ret(T.WORK+0x7500)
            if name=='configure':
                ptr=self.w(self.r(T.UC_ARM_REG_SP))
                self.configured.append(dict(mode=r[1],output=r[2],params=list(struct.unpack('<6I',mu.mem_read(ptr,24)))))
            return self.ret(0)
        return super()._hook(mu,addr,size,data)

    def prepare(self,stream=False):
        self.put(T.WORK+0x7100,int(self.rate_valid))
        def guard(mu,address,size,data):
            self.native_seen.add(address)
            if (0xC05BDE28<=address<0xC05BE3A0 or 0xC05BC408<=address<0xC05BC490 or
                T.BLOB<=address<T.BLOB+len(self.img) or T.MEM<=address<T.MEM+40*88 or
                T.CAVE_ARENA<=address<T.CAVE_ARENA+0x1000 or
                address in self.by_addr or address==T.DONE):return
            raise AssertionError(f'unapproved prepare instruction {address:#x}')
        handle=self.mu.hook_add(UC_HOOK_CODE,guard)
        try:return super().prepare(stream)
        finally:self.mu.hook_del(handle)


class CheckedPlayback(unittest.TestCase):
    def test_recorded_dng_headers_use_their_real_raster(self):
        paths=sorted(T.DNG_DIR.glob('*.DNG'))
        self.assertGreaterEqual(len(paths),3,'recorded fixtures must be present')
        for path in paths:
            with self.subTest(file=path.name):
                tags=T.dng_tags(path)
                c=NativePrepare();c.select(tags)
                self.assertEqual(c.prepare(),1)
                _,canvas=c.profile(c.configured[0]['params'])
                self.assertEqual((canvas[3],canvas[4]),(tags[0x100][0],tags[0x101][0]))
                EVIDENCE.append(dict(recorded_header=str(path.relative_to(T.ROOT)),
                                     sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                     raster=canvas[3:5],bits=tags[0x102][0],pixel_decode_tested=False))

    def test_selected_canvas_native_fieldangle_fits_nominal_lview_pool(self):
        sys.path.insert(0,str(T.ROOT/'projects/open-gate/build/og4k_offline'))
        import og4k_sizes as O
        em=O.NativeSizing(O.load_firmware());model=O.load_model()
        for raster,bits in (((2016,996),12),((2016,1330),8),((3024,2010),10),
                            ((6064,4050),12),((6064,4050),14)):
            with self.subTest(raster=raster,bits=bits):
                c=SelectedCam();c.select(movie(raster,bits));self.assertEqual(c.prepare(),1)
                _,canvas=c.profile()
                self.assertEqual((canvas[3],canvas[4]),raster)
                sizes=em.fieldangle(canvas,(1620,1080))
                self.assertEqual(sizes['total_bytes'],model.total(canvas,1620,1080))
                self.assertLess(sizes['total_bytes'],48*1024*1024)
                if raster==(6064,4050):self.assertEqual(sizes['total_bytes'],42815976)
                EVIDENCE.append(dict(native_fieldangle=True,raster=raster,bits=bits,**sizes))

    def test_native_prepare_allocates_stock_output_and_passes_selected_shape(self):
        for raster,bits in (((2016,996),12),((2016,1330),8),((3024,2010),10),((6064,4050),14)):
            for stream in (False,True):
                with self.subTest(raster=raster,bits=bits,stream=stream):
                    c=NativePrepare();c.select(movie(raster,bits))
                    self.assertEqual(c.prepare(stream),1)
                    self.assertIn(0xC05BE080,c.native_seen)
                    self.assertIn(0xC05BC408,c.native_seen)
                    self.assertEqual(c.allocations,[[9,0x5000000,0]])
                    self.assertEqual(len(c.configured),1)
                    cfg=c.configured[0]
                    self.assertEqual((cfg['mode'],cfg['output']),(5,0x4D000000))
                    self.assertEqual(cfg['params'][:3],[5,raster[0]-16,raster[1]-10])
                    self.assertEqual(cfg['params'][4],{8:4,10:3,12:0,14:0}[bits])
                    _,canvas=c.profile(cfg['params'])
                    self.assertEqual((canvas[3],canvas[4]),raster)
                    EVIDENCE.append(dict(native_prepare=True,stream=stream,raster=raster,bits=bits,
                                         allocations=c.allocations,configure=cfg))

    def test_native_prepare_returns_failure_when_the_reader_has_no_frame(self):
        c=NativePrepare();c.select(movie());c.rate_valid=False
        self.assertEqual(c.prepare(),0)
        self.assertEqual(c.configured,[])

    def test_selected_custom_clips_reach_prepare_with_their_own_raster(self):
        for raster in ((2016,1330),(2016,996),(3024,2010),(6064,4050)):
            for bits in (8,10,12,14):
                with self.subTest(raster=raster,bits=bits):
                    c=SelectedCam();c.select(movie(raster,bits))
                    self.assertEqual(c.prepare(),1)
                    self.assertEqual(len(c.decoded()),1)
                    pid,canvas=c.profile()
                    self.assertEqual((canvas[3],canvas[4]),raster)
                    self.assertEqual((canvas[8],canvas[10]),(raster[0]-16,raster[1]-10))
                    self.assertEqual((canvas[0xD8//4],canvas[0xE0//4]),raster)
                    self.assertEqual((canvas[0xF4//4],canvas[0xF8//4]),raster)
                    self.assertEqual(canvas[0x80//4]&255,{8:10,10:9,12:7,14:8}[bits])
                    self.assertEqual(c.prepare(stream=True),1)
                    self.assertEqual(len(c.decoded()),2)
                    EVIDENCE.append(dict(raster=raster,bits=bits,pid=pid,canvas=canvas))

    def test_selected_clip_survives_index_cache_churn_and_equal_crop(self):
        c=SelectedCam();c.select(movie())
        for i in range(10):
            # Same crop, different row pitch, bit depth and DefaultScale; index
            # reads do not have the player's context/raster address relation.
            c.tags=T.clip((2048,1340),(2000,1320),bits=14,dscale=[(3,1),(1,1)])
            c.call(T.PBTAG,0,T.TIFF,T.P_CROP,T.P_RAS)
        self.assertEqual(c.prepare(),1)
        _,canvas=c.profile()
        self.assertEqual((canvas[3],canvas[4]),(2016,1330))
        self.assertEqual(canvas[0x80//4]&255,7)
        self.assertEqual((c.pb()['asp_n'],c.pb()['asp_d']),(50,33))

    def test_mismatched_identity_geometry_or_absent_selected_read_is_refused(self):
        for offset,value in ((0x88,18),(0x54,1984),(0x58,1318),(0x98,2048),(0x9C,1340),(0xA8,4)):
            with self.subTest(offset=offset):
                c=SelectedCam();c.select(movie());c.put(T.OBJ+offset,value)
                self.assertEqual(c.prepare(),0);self.assertEqual(c.decoded(),[])
        c=SelectedCam()
        c.tags=movie();c.call(T.PBTAG,0,T.TIFF,T.P_CROP,T.P_RAS)
        self.assertEqual(c.prepare(),0);self.assertEqual(c.decoded(),[])

    def test_missing_compressed_or_invalid_tags_refuse_before_wait(self):
        bad=[]
        for tag in (0x100,0x101,0x102,0x103,0xC620):
            t=movie();del t[tag];bad.append(t)
        for tag,value in ((0x103,[7]),(0x102,[16]),(0x100,[2024]),(0x101,[1331]),
                          (0x100,[8192]),(0xC620,[0,0])):
            t=movie();t[tag]=value;bad.append(t)
        bad += [movie((8192,4050)),movie((6064,4052)),movie((16,12)),movie((32,10))]
        for tags in bad:
            with self.subTest(tags=tags):
                c=SelectedCam();c.select(movie())  # prior valid words deliberately left in the object
                c.select(tags)
                self.assertEqual(c.prepare(),0)
                self.assertEqual(c.prepare(stream=True),0)
                self.assertEqual(c.call(T.V12,T.OBJ,0,0,0),0)
                self.assertNotIn('D818',c.names());self.assertEqual(c.decoded(),[])

    def test_stock_custom_stock_and_live_are_isolated(self):
        c=SelectedCam();self.assertEqual(c.apply(T.recipe(*T.V1_ARGS)[0]),T.AP_OK)
        for tags in (movie((3856,2170)),movie(),movie((1936,1090),10)):
            c.select(tags);self.assertEqual(c.prepare(),1)
            pid,canvas=c.profile()
            self.assertEqual((canvas[3],canvas[4]),(tags[0x100][0],tags[0x101][0]))
            if tags[0x100][0] != 2016:
                self.assertEqual(canvas,T.PbCam().canvas(pid))
                self.assertIsNone(c.out(0))
        c.canvas(175)
        self.assertEqual(c.v1()['pbc'],0)
        self.assertIsNotNone(c.out(0))

    def test_default_scale_is_from_selected_file_not_current_live_recipe(self):
        c=SelectedCam();c.select(movie((2016,996),dscale=[(1,1),(4,3)]))
        self.assertEqual(c.prepare(),1);c.profile()
        from fractions import Fraction
        self.assertEqual(Fraction(c.pb()['asp_n'],c.pb()['asp_d']),
                         Fraction(2000*3,986*4).limit_denominator(1000))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path);p.add_argument('--report',type=Path,required=True)
    args=p.parse_args();SOURCE=args.source
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CheckedPlayback))
    args.report.write_text(json.dumps(dict(success=result.wasSuccessful(),tests=result.testsRun,
        failures=len(result.failures),errors=len(result.errors),cases=EVIDENCE,limitations=__doc__),indent=2)+'\n')
    raise SystemExit(0 if result.wasSuccessful() else 1)
