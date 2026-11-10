#!/usr/bin/env python3
"""Native playback ring bounds and real high-rate DNG selection/prepare.

Runs ROM C05C2D10, descriptor copies/queues, C05C2E90 cleanup, and the installed
SensorLab hook. Allocation success/failure, locks, empty XMP init/destruction
and memcpy/memset are explicit models. Parser cases additionally run native
selection/TIFF/prepare, with physical I/O, worker, configuration and decode
modeled by test_playback_entry. No physical pool availability or LCD proof.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import unittest
from unicorn import UC_HOOK_CODE
import test_playback_entry as E

T = E.T
ENTRY, CLEANUP, SITE = 0xC05C2D10, 0xC05C2E90, 0xC05C2DE8
RING, TABLE = 0x4B000000, 0x4B010000
TABLE_BYTES, STRIDE = 0x6F090, 0x5EC
CASES = T.ROOT/'projects/sensorlab-imx410/validation/20261102-hirate-playback-diagnosis/media.json'
SERVICES = {
    0xC0010298:'ring_lock', 0xC00102D0:'ring_unlock',
    0xC001CCE0:'intr_lock', 0xC001CD18:'intr_unlock',
    0xC001CF78:'ring_pool', 0xC001D1E8:'ring_allocate', 0xC001D2B8:'ring_free',
    0xC0015058:'ring_memset', 0xC0014DAC:'ring_memcpy',
    0xC00560C0:'empty_xmp_init', 0xC00CB7E0:'empty_xmp_destroy',
    0xC0011100:'ring_assert',
}
NATIVE = ((ENTRY,0xC05C2F58),(0xC05C3370,0xC05C33B8),
          (0xC05C3438,0xC05C35A0),(0xC05C3638,0xC05C3718))
EVIDENCE = []


class RingModel:
    def ring_init(self, available=1000):
        self.mu.mem_map(RING,0x100000)
        self.mu.mem_write(TABLE+TABLE_BYTES,bytes([0xA5])*0x1000)
        self.available=available;self.allocated=[];self.freed=[];self.requests=[]
        self.entry_sizes=[];self.expected_size=None
        for a,n in SERVICES.items():self.stub(a,n)
        self.mu.hook_add(UC_HOOK_CODE,self.ring_trace,begin=ENTRY,end=ENTRY)
        self.mu.hook_add(UC_HOOK_CODE,self.ring_trace,begin=SITE,end=SITE)

    def ring_trace(self,mu,a,size,data):
        if a==ENTRY:
            self.entry_sizes.append(self.r(T.UC_ARM_REG_R1))
        else:
            assert self.r(T.UC_ARM_REG_R4)==RING, 'wrong native owner at allocation hook'
            assert self.r(T.UC_ARM_REG_R1)==(self.entry_sizes[-1]+0x1FFF)&~0xFFF

    def ring_service(self,mu,a):
        if a not in SERVICES:return False
        n=SERVICES[a]
        r0,r1,r2=[self.r(x) for x in (T.UC_ARM_REG_R0,T.UC_ARM_REG_R1,T.UC_ARM_REG_R2)]
        if n=='ring_assert':raise AssertionError(f'native assertion {r1}')
        if n=='ring_pool':assert r0 in (9,10,11);self.ret(r0);return True
        if n=='ring_allocate':
            if r0==11:
                assert r1==TABLE_BYTES
                p=TABLE
            else:
                assert r0==10 and r1==(self.entry_sizes[-1]+0x1FFF)&~0xFFF
                p=0x60000000+len(self.allocated)*r1 if len(self.allocated)<self.available else 0
                if p:self.allocated.append(p)
            self.requests.append((r0,r1,p));self.ret(p);return True
        if n=='ring_free':self.freed.append((r0,r1))
        if n=='ring_memset':mu.mem_write(r0,bytes([r1&255])*r2)
        if n=='ring_memcpy':mu.mem_write(r0,bytes(mu.mem_read(r1,r2)))
        self.ret(r0 if n in ('ring_memset','ring_memcpy') else 0)
        return True

    def canary_ok(self):return bytes(self.mu.mem_read(TABLE+TABLE_BYTES,0x1000))==bytes([0xA5])*0x1000


class NativeRing(RingModel,T.Cam):
    def __init__(self,available=1000,patched=True):
        super().__init__(src=E.C.SOURCE)
        assert self.init()==T.AP_OK
        if not patched:self.put(SITE,T.iw(SITE))
        self.ring_init(available)
        self.mu.hook_add(UC_HOOK_CODE,self.guard)

    def _hook(self,mu,a,size,data):
        if self.ring_service(mu,a):return
        return super()._hook(mu,a,size,data)

    def guard(self,mu,a,size,data):
        if (any(lo<=a<hi for lo,hi in NATIVE) or a in self.by_addr or a==T.DONE or
            T.BLOB<=a<T.BLOB+len(self.img) or T.MEM<=a<T.MEM+(len(self.claims)-1)*88 or
            T.CAVE_ARENA<=a<T.CAVE_ARENA+0x1000):return
        raise AssertionError(f'unapproved ring instruction {a:08x}')

    def create(self,file_bytes):self.call(ENTRY,RING,file_bytes,sp=T.STACK-0x1000)
    def cleanup(self):self.call(CLEANUP,RING,sp=T.STACK-0x1000)


class NativeClip(RingModel,E.Parser):
    def __init__(self,row,data=None,available=1000):
        self.actual=row
        super().__init__(T.ROOT/row['copy'],data)
        self.by_addr.pop(ENTRY,None);self.put(ENTRY,T.iw(ENTRY))
        self.ring_init(available)
        self.put(T.OBJ+0xB4,RING)

    def _hook(self,mu,a,size,data):
        if a==ENTRY:return  # Parent models this whole function; execute it instead.
        if self.ring_service(mu,a):return
        if a==0xC05BDD68:
            obj,result=self.r(T.UC_ARM_REG_R0),self.r(T.UC_ARM_REG_R2)
            self.put(obj+0xA0,self.actual['file_bytes']);self.put(obj+0xA4,0)
            self.put(result+0xC,self.actual['clip_frames'])
            self.put(result+0x10,self.actual['file_bytes']*self.actual['clip_frames']);self.put(result+0x14,0)
            return self.ret(0)
        return super()._hook(mu,a,size,data)

    def guard(self,mu,a,size,data):
        if any(lo<=a<hi for lo,hi in NATIVE):return
        return super().guard(mu,a,size,data)


class PlaybackRing(unittest.TestCase):
    def test_original_native_loop_reproduces_301st_descriptor_overwrite(self):
        c=NativeRing(301,patched=False);c.create(183808)
        self.assertEqual(c.w(RING+4),301)
        self.assertFalse(c.canary_ok())
        EVIDENCE.append(dict(original_native_overflow=True,completed=c.w(RING+4)))

    def test_cap_and_allocator_failure_preserve_queue_cleanup_and_reuse(self):
        for size in (182784,183808,1097216,4*1024*1024):
            for available in (0,1,77,299,300,301,1000):
                with self.subTest(file_bytes=size,available=available):
                    c=NativeRing(available);c.create(size)
                    n=min(available,300)
                    self.assertEqual(c.w(RING+4),n)
                    self.assertEqual(c.w(RING+0x18),n)  # native free-queue count
                    self.assertEqual(len(c.allocated),n)
                    self.assertEqual(sum(pool==10 for pool,_,_ in c.requests),n+(available<300))
                    self.assertTrue(c.canary_ok())
                    before=len(c.requests);c.create(size)
                    self.assertEqual(len(c.requests),before,'already-prepared native path must not reallocate')
                    if n:
                        pointers=c.allocated[:];c.cleanup()
                        self.assertEqual(c.freed,[(10,p) for p in pointers]+[(11,TABLE)])
                        self.assertEqual((c.w(RING+4),c.w(RING+8),c.w(RING+0x3C)),(0,0,0))
                        c.allocated=[];c.freed=[];c.requests=[]
                        c.create(size)
                        self.assertEqual(c.w(RING+4),n);self.assertTrue(c.canary_ok())
                    EVIDENCE.append(dict(file_bytes=size,available=available,completed=n,canary=True,
                                         cleanup_and_reuse=bool(n)))

    def test_actual_card_headers_single_frame_and_stream_prepare(self):
        rows=json.loads(CASES.read_text())['files']
        self.assertEqual(len(rows),24)
        for row in rows:
            for stream in (False,True):
                with self.subTest(file=row['path'],stream=stream):
                    c=NativeClip(row)
                    self.assertEqual(hashlib.sha256(c.data).hexdigest(),row['sha256'])
                    self.assertEqual(c.entry({}),1)
                    original_enum=c.w(T.OBJ+0x68)
                    self.assertEqual(c.prepare(stream),1)
                    self.assertEqual(c.w(T.OBJ+0x68),10 if original_enum in (11,12,13) else original_enum)
                    self.assertEqual(c.w(RING+4),300);self.assertTrue(c.canary_ok())
                    self.assertEqual(c.entry_sizes,[row['file_bytes']])
                    self.assertEqual(c.configured[0]['params'][1:3],row['tags']['crop_size'])
                    self.assertEqual(bytes(c.mu.mem_read(0x49000000,len(c.data))),c.data,'DNG bytes must not change')
                    EVIDENCE.append(dict(file=Path(row['path']).name,stream=stream,source_enum=original_enum,
                                         playback_enum=c.w(T.OBJ+0x68),prepared=True,buffers=c.w(RING+4)))

    def test_cadence_only_changes_valid_enabled_selected_high_rate_clip(self):
        row=json.loads(CASES.read_text())['files'][-2]
        original=(T.ROOT/row['copy']).read_bytes()
        for rate in ((24000,1001),(25,1),(30000,1001),(60000,1001),(120000,1001),
                     (209,1),(238,1),(239,1),(600000,1859),(100000,209),(1200,1),(12,1)):
            with self.subTest(rate=rate):
                data=bytearray(original);off=E.entry_offset(data,0xC764)
                ptr=struct.unpack_from('<I',data,off+8)[0];struct.pack_into('<2i',data,ptr,*rate)
                c=NativeClip(row,bytes(data),available=1);self.assertEqual(c.entry({}),1)
                before=c.w(T.OBJ+0x68);result=c.prepare()
                self.assertEqual(result,int(rate!=(12,1)))
                self.assertEqual(c.w(T.OBJ+0x68),10 if before in (11,12,13) else before)
                self.assertEqual(bytes(c.mu.mem_read(0x49000000,len(data))),data)
        for why in ('other_owner','other_file','compressed','disabled','conditional_without_live','legacy_unselected'):
            with self.subTest(rejection=why):
                data=bytearray(original)
                if why=='compressed':struct.pack_into('<H',data,E.entry_offset(data,0x103)+8,7)
                c=NativeClip(row,bytes(data),available=1);self.assertEqual(c.entry({}),1)
                before=c.w(T.OBJ+0x68)
                if why in ('other_owner','legacy_unselected'):
                    # Selected snapshot belongs to another player; reuse must fail.
                    info=c.fn('ap_pb_info',T.MEM)&0xFFFFFFFF
                    c.put(info+E.C.T.PB_V1_AT+16,0)
                if why=='legacy_unselected':c.fn('ap_pb_ctl',T.MEM,3,0)
                if why=='other_file':c.put(T.OBJ+0x88,99)
                if why in ('disabled','conditional_without_live'):
                    c.fn('ap_pb_ctl',T.MEM,0,0 if why=='disabled' else 2)
                self.assertEqual(c.prepare(),0)
                self.assertEqual(c.w(T.OBJ+0x68),before)
                if why!='legacy_unselected':self.assertEqual(c.requests,[])


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path);p.add_argument('--report',type=Path,required=True)
    a=p.parse_args();E.C.SOURCE=a.source
    run=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(PlaybackRing))
    a.report.write_text(json.dumps(dict(success=run.wasSuccessful(),tests=run.testsRun,failures=len(run.failures),
                                       errors=len(run.errors),cases=EVIDENCE,limitations=__doc__),indent=2)+'\n')
    raise SystemExit(0 if run.wasSuccessful() else 1)
