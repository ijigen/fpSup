"""Actual LUT4 ARM code loaded by the actual Loader v4, offline only.

Firmware file/allocator routines are the existing v4 stubs. No substitute LUT
implementation is used. Assertions compare to the independent float64 desktop
reference. The emulator proves addresses/flow, not cache coherency or FPS.
"""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE),str(HERE.parent/'loader-v4')]
import build_sup as P
import test_boot_card_v4 as TB
import test_v4 as T4
import test_v3 as T3
from cinemadng import COLOR_SPACES, COMMON_GAMMAS, Selection
from color import source_to_xyz
from cube import Cube
from monitor import Monitor
from test_lut import make_cube

API_ID=0x3454554c
ASSET='\\fpSup\\LUTDATA\\ACTIVE.LUT'       # the sup's own folder (2026-11-06)
MUTANT_SOURCE=None

if T4.Uc is not None:
    from unicorn.arm_const import UC_ARM_REG_C1_C0_2, UC_ARM_REG_FPEXC

    def vfp_on(mu):
        """The camera's cores run with cp10/cp11 on (native/jfit.c, conv.c use the VFP; the kernel saves d0-d15)."""
        if not getattr(mu,'_lut_vfp',False):
            mu.reg_write(UC_ARM_REG_C1_C0_2,mu.reg_read(UC_ARM_REG_C1_C0_2)|(0xF<<20))
            mu.reg_write(UC_ARM_REG_FPEXC,0x40000000); mu._lut_vfp=True
    if not getattr(T4.Uc.hook_add,'_lut_vfp',False):
        _plain_hook_add=T4.Uc.hook_add
        def _hook_add_vfp(mu,*a,**k):
            vfp_on(mu); return _plain_hook_add(mu,*a,**k)
        _hook_add_vfp._lut_vfp=True
        T4.Uc.hook_add=_hook_add_vfp
    ORIGINAL_HOOK=T4.Uc.hook_add
    def rom_hook(mu,kind,callback,*args,**kwargs):
        # Keep strict firmware-call stubs, without a Python callback on every
        # private LUT/loader instruction (the real ARM still runs).
        if kind==T4.UC_HOOK_CODE and not args and not kwargs:
            kwargs=dict(begin=0xC0000000,end=0xC3ffffff)
        return ORIGINAL_HOOK(mu,kind,callback,*args,**kwargs)


def signed(word): return word if word<0x80000000 else word-(1<<32)


# native/borrow.c: the areas the LUT sup borrows from the firmware allocator (class 0) and returns.
# T3/T4's stub is a bump allocator that never reuses; calls whose return address is in the LUT block
# go to this model instead: first fit over what the sup returned, every area poisoned on its way in
# (0xA5) and out (0xDD, after a snapshot), a strict get/free pairing, and an optional refusal.
BORROW_IN, BORROW_OUT = 0xA5, 0xDD
ARENA, ARENA_SIZE = 0x47000000, 0x02000000        # the model's own class-0 memory, mapped at both aliases like T4's heap


def arena(cam):
    if not getattr(cam,'_arena',None):
        import ctypes
        from unicorn import UC_PROT_ALL
        regions=list(cam.mu.mem_regions())
        free=lambda a:all(e<a or b>=a+ARENA_SIZE for b,e,_p in regions)
        base=next(a for a in range(ARENA,0x7E000000,ARENA_SIZE) if free(a) and free(a+T4.ALIAS))
        cam._arena=ctypes.create_string_buffer(ARENA_SIZE); cam.arena_base=base
        ptr=ctypes.addressof(cam._arena)
        cam.mu.mem_map_ptr(base,ARENA_SIZE,UC_PROT_ALL,ptr)
        cam.mu.mem_map_ptr(base+T4.ALIAS,ARENA_SIZE,UC_PROT_ALL,ptr)
        cam.borrow_log,cam.borrow_out,cam.borrow_freed=[],{},[]
        cam.borrow_free=[(base+8,ARENA_SIZE-8)]           # 8 past a line, as T4's allocator: the sup aligns for itself
    return cam._arena


def lut_range(cam):
    """The LUT block's allocation (FSB4, sup_id LUT4), found once it is there."""
    if getattr(cam,'_lut_range',None): return cam._lut_range
    for p,n in cam.allocs.items():
        u=(p+63)&~63
        try: head=bytes(cam.mu.mem_read(u,24))
        except Exception: continue
        if struct.unpack_from('<I',head,0)[0]==P.B.SL4_MAGIC and head[20:24]==b'LUT4':
            cam._lut_range=(p,p+n); return cam._lut_range
    return None


def borrow_hook(cam,mu,addr):
    """True: a LUT borrow / return, answered here."""
    if addr not in (T3.F['MEM_GET'],T3.F['MEM_FREE']): return False
    lr=cam.r(T3.UC_ARM_REG_LR)&~1
    if lr>=T4.HEAP+T4.ALIAS: lr-=T4.ALIAS
    rng=lut_range(cam)
    if not rng or not rng[0]<=lr<rng[1]: return False
    arena(cam)
    if addr==T3.F['MEM_GET']:
        n=cam.r(T3.UC_ARM_REG_R1)
        assert cam.r(T3.UC_ARM_REG_R0)==0x1234,'class 0 heap (mem_heap(0))'
        if library_busy_now(cam): raise AssertionError('a borrow while recording')   # borrow.c must not ask then
        fail=getattr(cam,'borrow_fail',None)
        if fail and fail(n):
            cam.borrow_log.append(('fail',0,n)); cam._ret(0); return True
        n8=(n+63)&~63                                       # whole lines: every area starts 8 past one
        at=next((i for i,(q,m) in enumerate(cam.borrow_free) if m>=n8),None)
        if at is None:
            cam.borrow_log.append(('fail',0,n)); cam._ret(0); return True
        q,m=cam.borrow_free.pop(at)                         # first fit, the rest stays free
        if m>n8: cam.borrow_free.insert(at,(q+n8,m-n8))
        m=n8
        cam.borrow_out[q]=m
        mu.mem_write(q,bytes([BORROW_IN])*m)
        cam.borrow_log.append(('get',q,n))
        cam._ret(q); return True
    q=cam.r(T3.UC_ARM_REG_R1)
    if q>=0xC0000000: q-=T4.ALIAS
    if q not in cam.borrow_out: raise AssertionError(f'return of an area not borrowed: {q:#x}')
    m=cam.borrow_out.pop(q)
    cam.borrow_freed.append((q,m,bytes(mu.mem_read(q,m))))
    del cam.borrow_freed[:-6]
    mu.mem_write(q,bytes([BORROW_OUT])*m)
    free=sorted(cam.borrow_free+[(q,m)])                    # coalesced with its free neighbours
    cam.borrow_free=[]
    for a,k in free:
        if cam.borrow_free and cam.borrow_free[-1][0]+cam.borrow_free[-1][1]==a:
            cam.borrow_free[-1]=(cam.borrow_free[-1][0],cam.borrow_free[-1][1]+k)
        else: cam.borrow_free.append((a,k))
    cam.borrow_log.append(('free',q,m))
    cam._ret(0); return True


def borrows(cam):
    """(gets, frees, outstanding) so far."""
    log=getattr(cam,'borrow_log',[])
    return (sum(1 for k,_q,_n in log if k=='get'),sum(1 for k,_q,_n in log if k=='free'),
            dict(getattr(cam,'borrow_out',{})))


def recording(cam,on=True):
    """library_busy()'s movie flag (library4.c), as test_library_native's recording test sets it."""
    cam.mu.mem_write(0xC347E08F,b'\1' if on else b'\0')


def library_busy_now(cam):
    sel=cam.w(0xC347D1D4)
    rec=0xC3476609 if sel==0x21 else 0xC347E08F
    return bool(cam.mu.mem_read(rec,1)[0] or cam.w(0xC358E140) or cam.mu.mem_read(0xC35A952C,1)[0])


def dangling(cam,extra=()):
    """Words in the sup's state (and `extra` (addr, bytes) ranges) that point into a returned area."""
    out_now=getattr(cam,'borrow_out',{})
    freed=sorted({(q,q+m) for k,q,m in getattr(cam,'borrow_log',[]) if k=='free'})
    freed=[(a,b) for a,b in freed if not any(a<o+n and o<b for o,n in out_now.items())]   # returned, not borrowed again
    if not freed: return []
    _api,state=cam.lut()
    out=[]
    for base,n in [(state,4096),*extra]:
        blob=bytes(cam.mu.mem_read(base,n))
        for i in range(0,n-3,4):
            v=struct.unpack_from('<I',blob,i)[0]
            v0=v-T4.ALIAS if v>=0xC0000000 else v
            if any(a<=v0<b for a,b in freed): out.append((base+i,v))
    return out


class Camera(TB.Camera):
    def __init__(self,sup,asset,*,boot=None,extra=()):
        ar,loader,_=boot or P.B.boot_card(slim=True)
        with patch.object(T4.Uc,'hook_add',rom_hook):
            super().__init__(ar,loader,[('LUT.BIN',sup),*extra],active=True)
        if asset is not None: self.files[ASSET]=asset
        self.asset_objects=[]; self.asset_reads=[]
        TB.run_autorun(self,ar)

    def call(self,pc,r0=0,r1=0,r2=0,lr=T3.DONE,sp=T3.STACK-0x1004,thumb=False):
        mu=self.mu
        for reg,value in [(T3.UC_ARM_REG_SP,sp),(T3.UC_ARM_REG_R0,r0),
                          (T3.UC_ARM_REG_R1,r1),(T3.UC_ARM_REG_R2,r2),(T3.UC_ARM_REG_LR,lr)]:
            mu.reg_write(reg,value&0xffffffff)
        mu.emu_start(pc|(1 if thumb else 0),T3.DONE,count=200_000_000)
        if self.error: raise self.error
        assert self.r(T3.UC_ARM_REG_PC)==T3.DONE,'instruction limit / unexpected stop'
        return self.r(T3.UC_ARM_REG_R0),self.r(T3.UC_ARM_REG_SP)

    def _hook(self,mu,addr,size,data):
        if borrow_hook(self,mu,addr): return True
        # Do not accidentally run unmodelled ROM and count plausible returns.
        if 0xC0000000<=addr<0xC4000000 and not (
            addr in self.by_addr or T3.CAVE_LOW<=addr<0xC0730000):
            raise AssertionError('unmodelled firmware execution: '+hex(addr))
        if addr==T3.F['F_OPEN'] and self.cstr(self.r(T3.UC_ARM_REG_R1))==ASSET:
            self.asset_objects.append(self.r(T3.UC_ARM_REG_R0))
        if addr==T3.F['F_READ'] and self.r(T3.UC_ARM_REG_R0) in self.asset_objects:
            self.asset_reads.append((self.r(T3.UC_ARM_REG_R1),self.r(T3.UC_ARM_REG_R2)))
        return super()._hook(mu,addr,size,data)

    def lut(self):
        api=self.callsvc('find',r1=API_ID)
        assert self.w(api)==API_ID
        return api,self.w(api+8)

    def svc(self):
        # The shared outer stage2 and the v4 core each register a journal.
        # Select the service-v5 object, not the envelope's separate journal.
        objects={o-T4.SVC_BYTES for o,_ in self.registered if 5<=self.w(o-T4.SVC_BYTES)<=7}
        assert len(objects)==1,[(hex(o),self.w(o-T4.SVC_BYTES)) for o,_ in self.registered]
        return objects.pop()

    def invoke(self,index,r1=0,r2=0,r3=0):
        api,state=self.lut()
        ptr=self.w(api+index*4)
        self.mu.reg_write(T4.UC_ARM_REG_R3,r3&0xffffffff)
        result,sp=self.call(ptr&~1,r0=state,r1=r1,r2=r2,thumb=bool(ptr&1))
        assert sp==T3.STACK-0x1004,hex(sp)
        return signed(result)

    def status(self):
        p=self._alloc(44)
        assert self.invoke(7,p)==0
        values=struct.unpack('<Iii7Ii',self.mu.mem_read(p,44))
        return dict(zip(['version','asset','model','backend','color','gamma','strength','samples','outside1','outside3','last'],values))

    def render(self,xyz,inplace=False):
        xyz=np.asarray(xyz,dtype=np.float64).reshape(-1,3)
        encoded=P.quantize(xyz,2047).tobytes()
        source=self._alloc(len(encoded)); dest=source if inplace else self._alloc(len(encoded))
        self.mu.mem_write(source,encoded)
        result=self.invoke(6,source,dest,len(xyz))
        actual=np.frombuffer(self.mu.mem_read(dest,len(encoded)),dtype='<i4').reshape(-1,3)/P.Q
        return result,actual

    def set_row(self,title,value):
        for i in range(self.callsvc('page_count')):
            row=self.callsvc('page_row',r1=i)
            if self.cstr(self.w(row+4))==title:
                callback=self.w(row+16); context=self.w(row+28)
                result,sp=self.call(callback&~1,r0=context,r1=value,thumb=bool(callback&1))
                assert sp==T3.STACK-0x1004
                return signed(result)
        raise AssertionError('missing setting row: '+title)


@unittest.skipIf(T4.Uc is None or not T3.IMAGE.exists(),'requires Unicorn and firmware image; skipped is unverified')
class NativeLutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sup,cls.facts=P.build_sup(MUTANT_SOURCE or P.SOURCE)
        cls.boot=P.B.boot_card(slim=True)

    def cam(self,cube=None,asset=None,extra=()):
        cube=cube or P.identity()
        return Camera(self.sup,P.asset(cube) if asset is None else asset,boot=self.boot,extra=extra)

    def test_loads_cached_with_resident_rows_and_dma_only_file_scratch(self):
        c=self.cam()
        api,state=c.lut()
        self.assertGreaterEqual(api,0xC5000000)
        self.assertGreaterEqual(state,0xC5000000)
        self.assertEqual(c.status()['asset'],0)
        self.assertEqual(c.status()['backend'],0)
        self.assertEqual(c.misaligned,[])
        self.assertEqual([x[2] for x in c.loadlog() if x[0]==10 and x[3]=='LUT.BIN'],[0])
        self.assertEqual(c.callsvc('page_count'),1)
        titles=[]
        for i in range(1):
            row=c.callsvc('page_row',r1=i)
            titles.append(c.cstr(c.w(row+4)))
            self.assertLessEqual(c.w(row)>>16,3)
            self.assertEqual(c.w(row)&0xffff,1)  # only the Color JUMP
            self.assertGreaterEqual(c.w(row+24),0xC5000000)
        self.assertEqual(titles,['LUT manager'])
        self.assertTrue(c.asset_reads)
        base=state-self.facts['state_offset']
        uncached=base-0x80000000+self.facts['io_offset']
        self.assertEqual(c.asset_objects,[uncached])
        self.assertTrue(all(p==uncached+4096 and n<=4096 for p,n in c.asset_reads))
        # The loader has freed/poisoned staging; registered callbacks still work.
        self.assertTrue(c.freed)
        self.assertEqual(c.invoke(3,6,1),0)
        self.assertEqual(c.invoke(5,1),-13)
        self.assertEqual(c.invoke(5,0),0)
        self.assertEqual(c.status()['backend'],0)
        c.power_off_all()

    def test_all_35_models_against_float_reference_and_strengths(self):
        cube=Cube.parse(make_cube(n=5,fn=lambda r,g,b:(r*g+.03*b,.2*r+.6*g+.2*b,b*b-.04*r)))
        c=self.cam(cube)
        rgb=np.array([[.001]*3,[.18]*3,[1.]*3,[-.01,.2,4.],[.3,.15,.05],[.05,.25,.4]])
        xyz=source_to_xyz(rgb,'linear-709')
        for color_index,color in enumerate(COLOR_SPACES):
            if color=='blackmagic-design': continue
            for gamma_index,gamma in enumerate(COMMON_GAMMAS):
                if gamma=='rec709': continue
                with self.subTest(color=color,gamma=gamma):
                    self.assertEqual(c.invoke(3,color_index,gamma_index),0)
                    expected,_=Monitor(cube,color,input_gamma=gamma).evaluate_xyz(xyz)
                    rc,actual=c.render(xyz)
                    self.assertEqual(rc,0)
                    # Q20 input quantization is included, as are matrix/curve/node approximations.
                    np.testing.assert_allclose(actual,expected,atol=4e-5,rtol=0)
        c.invoke(3,6,1)
        for amount in (0,25,50,75,100):
            self.assertEqual(c.invoke(4,amount),0)
            rc,actual=c.render(xyz,inplace=True)
            expected,_=Monitor(cube,'rec709',strength=amount/100,input_gamma='gamma24').evaluate_xyz(xyz)
            self.assertEqual(rc,0)
            np.testing.assert_allclose(actual,expected,atol=4e-5,rtol=0)

    def test_native_controls_reach_all_models_and_strengths_without_ui(self):
        c=self.cam()
        for ci,color in enumerate(COLOR_SPACES):
            for gi in range(2 if color=='blackmagic-design' else 6):
                expected=-12 if ci==2 or gi==4 else 0
                self.assertEqual(c.invoke(3,ci,gi),expected)
                self.assertEqual((c.status()['color'],c.status()['gamma']),(ci,gi))
                self.assertEqual(c.status()['model'],expected)
        for amount in (0,25,50,75,100):
            self.assertEqual(c.invoke(4,amount),0)
            self.assertEqual(c.status()['strength'],amount)
        self.assertEqual(c.invoke(5,1),-13)
        self.assertEqual(c.status()['backend'],0)

    def test_combined_shaper_domains_output_hdr_and_lookup_diagnostics(self):
        source=b'LUT_1D_INPUT_RANGE -1 2\nLUT_3D_INPUT_RANGE -0.5 1.5\nLUT_1D_SIZE 3\n'
        source+=b'LUT_3D_SIZE 3\n-1 -1 -1\n0.5 0.5 0.5\n2 2 2\n'
        source+=make_cube(3,fn=lambda r,g,b:(r*1.5-.2,g*g,b*1.4)).split(b'\n',1)[1]
        cube=Cube.parse(source)
        c=self.cam(cube); c.invoke(3,6,3)
        rgb=np.array([[-2.]*3,[-.2,.3,.8],[.7,.9,1.2],[3.]*3])
        xyz=source_to_xyz(rgb,'linear-709')
        expected,report=Monitor(cube,'rec709',input_gamma='linear').evaluate_xyz(xyz)
        rc,actual=c.render(xyz)
        self.assertEqual(rc,0)
        np.testing.assert_allclose(actual,expected,atol=5e-6,rtol=0)
        self.assertGreater(actual.max(),1)
        self.assertLess(actual.min(),0)
        self.assertEqual(c.status()['outside1'],report['lut_lookups']['shaper_lookup']['below_channels']+
                         report['lut_lookups']['shaper_lookup']['above_channels'])
        self.assertEqual(c.status()['outside3'],report['lut_lookups']['cube_lookup']['below_channels']+
                         report['lut_lookups']['cube_lookup']['above_channels'])

    def test_pure_1d_4096_entries_and_tetrahedra_all_orders(self):
        axis=np.linspace(0,1,4096)
        source=b'LUT_1D_SIZE 4096\n'+b''.join(f'{r*r:.12g} {r:.12g} {1-r:.12g}\n'.encode() for r in axis)
        cube=Cube.parse(source)
        c=self.cam(cube); c.invoke(3,6,3)
        xyz=source_to_xyz([[.99,.1,.55],[1,1,1],[0,0,0]],'linear-709')
        rc,actual=c.render(xyz)
        expected,_=Monitor(cube,'rec709',input_gamma='linear').evaluate_xyz(xyz)
        self.assertEqual(rc,0)
        np.testing.assert_allclose(actual,expected,atol=5e-6,rtol=0)

    def test_full_65_grid_all_tetrahedral_orders_and_original_nodes(self):
        from itertools import permutations
        cube=Cube.parse(make_cube(65,fn=lambda r,g,b:(r*g+.02*b,g*b+.1*r,r*b-.03*g)))
        prepared=P.asset(cube)
        self.assertLess(len(prepared),P.CAPACITY)
        c=self.cam(cube,asset=prepared); c.invoke(3,6,3)
        samples=np.array([*permutations((.13,.43,.83)),[-.1,.5,1.2],[0,0,0],[1,1,1]])
        xyz=source_to_xyz(samples,'linear-709')
        rc,actual=c.render(xyz)
        expected,_=Monitor(cube,'rec709',input_gamma='linear').evaluate_xyz(xyz)
        self.assertEqual(rc,0)
        np.testing.assert_allclose(actual,expected,atol=7e-6,rtol=0)
        self.assertEqual(struct.unpack_from('<I',prepared,24)[0],65)

    def test_bad_input_never_changes_destination_and_pending_models_refuse(self):
        c=self.cam()
        source=c._alloc(24); dest=c._alloc(24)
        c.mu.mem_write(source,P.quantize([[.1]*3,[65.]*3],100).tobytes())
        before=bytes(c.mu.mem_read(dest,24))
        self.assertEqual(c.invoke(6,source,dest,2),-14)
        self.assertEqual(c.status()['last'],-14)
        self.assertEqual(bytes(c.mu.mem_read(dest,24)),before)
        for args in [(source,source+4,1),(source,dest,4097),(source+1,dest,1)]:
            self.assertEqual(c.invoke(6,*args),-14)
        for color,gamma in [(2,0),(2,1),(6,4)]:
            self.assertEqual(c.invoke(3,color,gamma),-12)
            self.assertEqual(c.status()['model'],-12)
            self.assertEqual(c.invoke(6,source,dest,1),-12)
            self.assertEqual(bytes(c.mu.mem_read(dest,24)),before)
        self.assertEqual(c.invoke(3,2,2),-3)
        self.assertEqual(c.invoke(4,55),-3)
        self.assertEqual(c.invoke(5,2),-3)

    def test_missing_short_corrupt_trailing_and_corrupt_header_remain_unapplied(self):
        good=P.asset(P.identity())
        wrong_default=bytearray(good); struct.pack_into('<I',wrong_default,48,0)
        cases=[None,good[:200],good[:-1],good+b'old tail',good[:400]+bytes([good[400]^1])+good[401:],bytes(wrong_default)]
        for i,data in enumerate(cases):
            with self.subTest(case=i):
                c=Camera(self.sup,data,boot=self.boot)
                self.assertEqual(c.status()['asset'],-10 if data is None else -11)
                self.assertEqual(c.status()['backend'],0)
                self.assertEqual(c.invoke(5,1),-13)
                self.assertEqual(c.render([[.1]*3])[0],-10 if data is None else -11)

    def test_released_sup_leaves_no_rows_or_service_on_conflict(self):
        competitor=P.B.test_sup(T4.cfg(provide=(API_ID,0x12345678)),'AAAA',name='Other LUT owner')
        c=self.cam(extra=[('ALPHA.BIN',competitor)])
        self.assertEqual(c.callsvc('find',r1=API_ID),0x12345678)
        self.assertEqual(c.callsvc('page_count'),0)
        self.assertIn('LUT.BIN',[row[3] for row in c.loadlog() if row[0]==11])

    def test_full_home_registry_releases_color_entry_and_api(self):
        extra=[]
        for i in range(11):
            rows=[(2,f'Other {i}-{j}') for j in range(6 if i<10 else 4)]
            other=P.B.test_sup(T4.cfg(rows=rows),f'X{i:03}',name='Other')
            extra.append((f'A{i:02}.BIN',other))
        c=self.cam(extra=extra)
        self.assertEqual(c.callsvc('page_count'),64)
        self.assertEqual(c.callsvc('find',r1=API_ID),0)
        self.assertIn('LUT.BIN',[row[3] for row in c.loadlog() if row[0]==11])

    def test_fast_debug_card_and_retained_image_reinitialize_defaults(self):
        boot=P.B.boot_card(splash=True,instant=True,fast=True,slim=True)
        c=Camera(self.sup,P.asset(P.identity()),boot=boot,extra=[('SHELL.BIN',P.B.shell_sup())])
        self.assertIn('SHELL.BIN',c.loaded())
        self.assertEqual(c.status()['asset'],0)
        c.invoke(3,0,3); c.invoke(4,25)
        self.assertEqual(c.status()['color'],0)
        c.power_off_all()
        c.registered.clear(); c.heap_next=T4.HEAP
        c.written.pop('\\fpSup\\LOAD.LOG',None)
        c.put(TB.TABLE+0x21c,2); c.put(TB.CTX+0x90,1); c.put(TB.CTX+0x94,TB.FOBJ)
        TB.run_autorun(c,boot[0])
        self.assertEqual(c.status()['color'],6)
        self.assertEqual(c.status()['gamma'],1)
        self.assertEqual(c.status()['strength'],100)
        self.assertEqual(c.status()['backend'],0)
        self.assertEqual(c.callsvc('page_count'),1)
        self.assertEqual(c.misaligned,[])


class NativePackageTests(unittest.TestCase):
    def test_header_format_asset_source_and_boot_stay_independent(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            first=P.build(root/'a',card=True,debug=True)
            second=P.build(root/'b',Cube.parse(make_cube(fn=lambda r,g,b:(r*r,g,b))),color='p3-d65',gamma='gamma26',card=True,debug=True)
            for name in ('AutoRun.txt','fpSup/LOADER.BIN','fpSup/'+P.SUP_FILE):
                self.assertEqual((root/'a'/name).read_bytes(),(root/'b'/name).read_bytes())
            hdr=struct.unpack_from('<12I',(root/'a/fpSup'/P.SUP_FILE).read_bytes())
            self.assertEqual(hdr[:2],(P.B.SL4_MAGIC,48))
            self.assertEqual(hdr[7:9],(6,1))
            self.assertEqual(hdr[9:11],(first['io_offset'],8192))
            self.assertFalse((root/'a/fpSup/LUT').exists())             # \\fpSup\\LUT\\ is the user's cubes alone
            self.assertEqual(sorted(p.name for p in (root/'a/fpSup/LUTDATA').iterdir()),['ACTIVE.LUT'])
            self.assertEqual([p for p in root.rglob('*.json')],[])         # no build record on the card
            self.assertFalse(first['live_view_backend_connected'])
            self.assertTrue(first['ui_renderer_present'])
            for source in ('fpSup/fpsup-ui/fpsup_ui.c', 'fpSup/loader-v4/fpsup_home.c'):
                self.assertEqual(first['source_hashes'][source],P.sha((P.ROOT/source).read_bytes()))
            self.assertNotIn('fpSup/uishare/ui_pool.c',first['source_hashes'])
            self.assertNotIn('fpSup/uishare/ui_apply.c',first['source_hashes'])
            for name,data in P.B.ui_files().items():
                self.assertEqual((root/'a/fpSup/UI'/name).read_bytes(),data)
            self.assertNotEqual(first['files']['fpSup/LUTDATA/ACTIVE.LUT']['sha256'],second['files']['fpSup/LUTDATA/ACTIVE.LUT']['sha256'])
            with self.assertRaises(FileExistsError): P.build(root/'a')

    def test_reject_unsupported_model_and_quantization_failures_before_output(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'out'
            with self.assertRaises(ValueError): P.build(out,color='blackmagic-design',gamma='blackmagic-film')
            self.assertFalse(out.exists())
        with self.assertRaises(ValueError): P.asset(Cube.parse(make_cube(fn=lambda r,g,b:(1025,g,b))))
        with self.assertRaises(ValueError): P.asset(Cube.parse(make_cube(headers='DOMAIN_MAX 0.0000001 1 1\n')))


if __name__=='__main__': unittest.main()
