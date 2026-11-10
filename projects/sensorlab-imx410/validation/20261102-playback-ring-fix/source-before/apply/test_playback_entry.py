#!/usr/bin/env python3
"""Native selection/v2/v11/TIFF read and prepare on recorded DNG bytes.
File I/O, allocator, audio/timecode, RTOS, configuration and decoder are declared
fixtures. TIFF parsing/tag lookup, selection copies, rate lookup and prepare
execute ROM. No camera, pixel decode, pool availability or LCD proof.
"""
import argparse,hashlib,unittest
import sys,json,struct
from pathlib import Path
import test_playback_checked as C
T=C.T
SEQ=T.WORK+0x9000
VIEW=T.WORK+0xA000
class Entry(C.NativePrepare):
    IO={0xC0013090:'once',0xC03C0C80:'timer',0xC03C0CD0:'timer_end',
        0xC03D4C00:'view',0xC03B7C58:'copy_path',0xC069B930:'media',
        0xC069B568:'filename',0xC0013CF8:'copy',
        0xC00178D8:'state_init',0xC0017AC8:'camera_state',
        0xC001D860:'alloc_init',0xC001D948:'alloc_data',0xC001D8F8:'free',
        0xC0365E90:'file_init',0xC069B9B8:'filepath',0xC0365FB0:'open',
        0xC0366060:'read',0xC0365ED0:'file_free',0xC00C1508:'tiff_init',
        0xC05BDD68:'file_size',0xC05BFF80:'audio',0xC05C1BD8:'timecode',
        0xC0055F20:'tiff_free',0xC0015AE0:'udiv',
        T.WORK+0xB000:'view0',T.WORK+0xB004:'view1'}
    def __init__(self):
        super().__init__()
        self.trace=[]
        del self.by_addr[0xC05BCB60]
        self.mu.mem_write(0xC05BCB60,struct.pack('<I',T.iw(0xC05BCB60)))
        self.mu.mem_write(T.OBJ+0x34,T.image()[0x2DFDF4C:0x2DFDF4C+100])
        self.put(T.OBJ+4,0xC2DFDE50)
        self.put(SEQ+8,T.OBJ);self.put(SEQ+0x3C,32*1024*1024)
        self.put(VIEW,VIEW+0x100)
        self.put(VIEW+0x110,T.WORK+0xB000);self.put(VIEW+0x114,T.WORK+0xB004)
        self.mu.mem_write(T.WORK+0xB100,b'A001_001_000001.DNG\0'.ljust(64,b'\0'))
        for a,n in self.IO.items():self.stub(a,n)
        self.handle=self.mu.hook_add(C.UC_HOOK_CODE,self.guard)
    def guard(self,mu,a,size,data):
        self.trace.append(a)
        if len(self.trace)>60:self.trace.pop(0)
        if (a in self.by_addr or a==T.DONE or T.BLOB<=a<T.BLOB+len(self.img) or
            T.MEM<=a<T.MEM+40*88 or T.CAVE_ARENA<=a<T.CAVE_ARENA+0x1000 or
            0xC05BCB60<=a<0xC05BCC38 or 0xC05BDE28<=a<0xC05BE3A0 or 0xC05BC408<=a<0xC05BC490 or 0xC05BDAD0<=a<0xC05BDAF8 or
            0xC03BAB68<=a<0xC03BAE30 or 0xC05BCF28<=a<0xC05BCF80 or
            0xC05BDB08<=a<0xC05BDD68 or 0xC05C1A58<=a<0xC05C1BD8 or
            0xC03B86A0<=a<0xC03B86D8 or 0xC06A0770<=a<0xC06A08D0 or 0xC00159D0<=a<0xC0015A00):return
        raise AssertionError(f'unmodeled {a:08x}; tail={[hex(v) for v in self.trace[-14:]]}')
    def _hook(self,mu,a,size,data):
        if a==0xC05BCB60:return  # Execute ROM; SelectedCam otherwise intercepts this by address.
        if a not in self.IO:return super()._hook(mu,a,size,data)
        n=self.IO[a];r=[self.r(x) for x in (T.UC_ARM_REG_R0,T.UC_ARM_REG_R1,T.UC_ARM_REG_R2,T.UC_ARM_REG_R3)]
        self.calls.append((n,*r[:2]))
        if n=='once':return self.ret(0)
        if n=='view':return self.ret(VIEW)
        if n in ('view0','view1'):return self.ret(0)
        if n=='camera_state':return self.ret(T.WORK+0xC000)
        if n=='alloc_init':self.put(r[0]+8,0x500000)
        if n=='alloc_data':return self.ret(T.WORK+0x100000)
        if n in ('filename','filepath'):return self.ret(T.WORK+0xB100)
        if n=='copy':mu.mem_write(r[0],bytes(mu.mem_read(r[1],r[2])))
        if n=='open':return self.ret(1)
        if n=='read':self.put(r[3],200000);return self.ret(1)
        if n=='tiff_init':self.put(r[0],T.TIFF)
        if n=='file_size':
            self.put(r[0]+0xA0,4*1024*1024);self.put(r[0]+0xA4,0)
            self.put(r[2]+0xC,4);self.put(r[2]+0x10,16*1024*1024);self.put(r[2]+0x14,0)
        if n=='udiv':return self.ret(r[0]//r[1])
        return self.ret(0)
    def entry(self,tags):
        self.tags=tags
        result=self.call(0xC03BAB68,SEQ,T.WORK+0xD000,1,0)
        return result

    def prepare(self,stream=False):
        return C.SelectedCam.prepare(self,stream)

class Parser(Entry):
    RUNTIME={0xC03D8BD0:'new',0xC001349C:'delete',0xC03D8E20:'delete',0xC0014DAC:'memcpy',0xC001510C:'memcpy'}
    def __init__(self,path,data=None):
        self.tagcalls=[];self.pending=[]
        self.data=path.read_bytes() if data is None else data;self.heap=0x48500000
        super().__init__()
        self.mu.mem_map(self.heap,0x800000)
        self.mu.mem_map(0x49000000,0x800000)
        self.mu.mem_write(0x49000000,self.data)
        for address in (0xC00C1508,0xC0055F20,*[T.PB[n] for n in ('TAG_E40','TAG_DB8','TAG_ED0','TAG_458','TAG_4D8')]):
            self.by_addr.pop(address,None)
            self.mu.mem_write(address,struct.pack('<I',T.iw(address)))
        for a,n in self.RUNTIME.items():self.stub(a,n)
    def guard(self,mu,a,size,data):
        if a in (0xC05C1DB8,0xC05C1E40,0xC05C1ED0):
            self.pending.append((self.r(T.UC_ARM_REG_LR)&~1,self.r(T.UC_ARM_REG_R2),self.r(T.UC_ARM_REG_R3),a))
        if self.pending and a==self.pending[-1][0]:
            lr,tag,p,callee=self.pending.pop()
            self.tagcalls.append((hex(callee),hex(tag),self.r(T.UC_ARM_REG_R0),bytes(mu.mem_read(p,8)).hex()))
        if (0xC00B8000<=a<0xC00C3000 or 0xC05A4D70<=a<0xC05A4F18 or
            0xC05C1DB8<=a<0xC05C1FE8 or 0xC0055F20<=a<0xC0055F80 or 0xC01F57CC<=a<0xC01F57F4 or 0xC03D8F80<=a<0xC03D8FA8):return
        return super().guard(mu,a,size,data)
    def _hook(self,mu,a,size,data):
        if a in (0xC00C1508,0xC0055F20):return
        r=[self.r(x) for x in (T.UC_ARM_REG_R0,T.UC_ARM_REG_R1,T.UC_ARM_REG_R2,T.UC_ARM_REG_R3)]
        if a==0xC001D948:return self.ret(0x49000000)
        if a==0xC0366060:self.put(r[3],len(self.data));return self.ret(1)
        if a in self.RUNTIME:
            n=self.RUNTIME[a]
            if n=='new':
                p=self.heap;self.heap+=(r[0]+15)&~15
                assert self.heap<0x48D00000
                return self.ret(p)
            if n=='memcpy':mu.mem_write(r[0],bytes(mu.mem_read(r[1],r[2])));return self.ret(r[0])
            return self.ret(0)
        return super()._hook(mu,a,size,data)

EVIDENCE=[]

def entry_offset(data,tag):
    off=struct.unpack_from('<I',data,4)[0]
    for i in range(struct.unpack_from('<H',data,off)[0]):
        p=off+2+12*i
        if struct.unpack_from('<H',data,p)[0]==tag:return p
    raise ValueError(hex(tag))

class NativeEntryTests(unittest.TestCase):
    def test_recorded_files_pass_native_selection_parser_and_prepare(self):
        paths=sorted(T.DNG_DIR.glob('*.DNG'))
        self.assertEqual(len(paths),3)
        for path in paths:
            with self.subTest(file=path.name):
                c=Parser(path)
                self.assertEqual(c.entry({}),1)
                tags=T.dng_tags(path)
                self.assertEqual((c.w(T.OBJ+0x98),c.w(T.OBJ+0x9C)),(tags[0x100][0],tags[0x101][0]))
                # These are written by the second native v2 copy, never seeded by the test.
                self.assertEqual((c.w(T.OBJ+0x54),c.w(T.OBJ+0x58)),tuple(tags[0xC620]))
                prepared=c.prepare()
                EVIDENCE.append(dict(file=path.name,sha256=hashlib.sha256(c.data).hexdigest(),
                    parser='native ROM',prepared=bool(prepared),config=c.configured,tag_reads=c.tagcalls))
                self.assertEqual(prepared,1,'uncompressed actual file must reach native configure')
                self.assertEqual(len(c.configured),1)
                self.assertEqual(c.configured[0]['params'][1:3],tags[0xC620])

    def test_native_parser_omission_does_not_admit_compressed_or_missing_tag(self):
        path=T.DNG_DIR/'A001_261_000001.DNG'
        for kind in ('compressed','missing','wrong_type','wrong_count'):
            with self.subTest(kind=kind):
                data=bytearray(path.read_bytes());off=entry_offset(data,0x103)
                if kind=='compressed':struct.pack_into('<H',data,off+8,7)
                if kind=='missing':struct.pack_into('<H',data,off,0xF123)
                if kind=='wrong_type':struct.pack_into('<H',data,off+2,4)
                if kind=='wrong_count':struct.pack_into('<I',data,off+4,2)
                c=Parser(path,bytes(data));self.assertEqual(c.entry({}),1)
                self.assertEqual(c.prepare(),0);self.assertEqual(c.configured,[])
                EVIDENCE.append(dict(mutated_header=kind,prepared=False))

    def test_header_reader_is_bounded_and_rejects_ambiguous_ifd(self):
        good=C.SelectedCam.header_bytes([1]);bad=[b'',good[:7],good[:-1]]
        for offset,value,fmt in ((0,0x5A5A,'<H'),(2,43,'<H'),(4,0xFFFFFFF0,'<I'),(8,513,'<H')):
            b=bytearray(good);struct.pack_into(fmt,b,offset,value);bad.append(bytes(b))
        bad.append(good[:8]+struct.pack('<H',2)+good[10:22]*2+bytes(4))
        for data in bad:
            with self.subTest(data=data.hex()):
                c=C.SelectedCam();c.select(C.movie())
                c.header(data);c.info(C.movie())
                self.assertEqual(c.prepare(),0)
        # Bounded scanner accepts either standard byte order. TIFF model is
        # intentionally stubbed in this unit test, unlike the recorded cases.
        big=b'MM\0*'+struct.pack('>IH',8,1)+struct.pack('>HHII',0x103,3,1,1<<16)+bytes(4)
        c=C.SelectedCam();c.select(C.movie());c.header(big);c.info(C.movie())
        self.assertEqual(c.prepare(),1)

    def test_header_and_player_must_match(self):
        for offset in (0,4,8):  # header owner, selected-file descriptor, TIFF handle
            with self.subTest(offset=offset):
                c=C.SelectedCam();c.select(C.movie())
                pb=c.fn('ap_pb_info',T.MEM)&0xFFFFFFFF
                # Appended after the existing 13-word selected record at word180.
                header=pb+(180+13)*4
                c.put(header+offset,c.w(header+offset)^4)
                c.info(C.movie())
                self.assertEqual(c.prepare(),0)

    def test_rate_restriction_is_exercised_from_rom_not_a_success_stub(self):
        # Existing unrelated native restriction: less than 23 fps has no rate
        # descriptor. Document it; this compression fix does not fake cadence.
        path=T.DNG_DIR/'A001_261_000001.DNG'
        data=bytearray(path.read_bytes());off=entry_offset(data,0xC764)
        p=struct.unpack_from('<I',data,off+8)[0];struct.pack_into('<ii',data,p,12,1)
        c=Parser(path,bytes(data));self.assertEqual(c.entry({}),1)
        self.assertEqual(c.w(T.OBJ+0x68),0)
        self.assertEqual(c.prepare(),0);self.assertEqual(c.configured,[])
        EVIDENCE.append(dict(known_limit='12 fps maps to unsupported native cadence',prepared=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path);parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args();C.SOURCE=args.source
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(NativeEntryTests))
    args.report.write_text(json.dumps(dict(success=result.wasSuccessful(),tests=result.testsRun,
        failures=len(result.failures),errors=len(result.errors),cases=EVIDENCE,limitations=__doc__),indent=2)+'\n')
    raise SystemExit(0 if result.wasSuccessful() else 1)
