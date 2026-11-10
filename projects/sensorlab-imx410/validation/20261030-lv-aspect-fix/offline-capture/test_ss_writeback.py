#!/usr/bin/env python3
"""Offline SS destination versus native display-writeback layout fixture.

No USB, product build, host dylib or hardware execution. All geometry, getters,
clear length and writeback register packing execute original ROM instructions.
The display suspend/resume call C00E23A8 is a declared success-only fixture;
its driver/interrupt side effects are outside this destination-layout test.
The fixture stops at C00E22C8, before requesting a hardware writeback trigger.
Display dimensions are declared state, not measurements of the camera/LCD.
"""
import hashlib
import json
from pathlib import Path
import struct
import sys
import unittest

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn import arm_const as R

ROOT = Path(__file__).resolve().parents[5]
ROM, RAM, WORK, STACK, STOP, PIXELS = 0xC0000000, 0xC3000000, 0x10000000, 0x10010000, 0x10030000, 0x45000000
ENTRY, CONFIGURE, TRIGGER = 0xC00EAD71, 0xC00EB290, 0xC00E22C8
NATIVE = (
    (0xC0388668,0xC0388680), (0xC0046030,0xC0046080),
    (0xC02E5C10,0xC02E5C70), (0xC02DA6E0,0xC02DA750),
    (0xC0015058,0xC0015108), (0xC00DB278,0xC00DB2F8),
    (0xC00DEA80,0xC00DEC20), (0xC00DEC20,0xC00DECB8),
    (0xC00DE5C8,0xC00DE6F8), (0xC00E4648,0xC00E4708),
    (0xC00E4750,0xC00E4768), (0xC00E5C10,0xC00E5C38),
    (0xC00F5640,0xC00F56F0), (0xC00FAF68,0xC00FAFA0),
    (0xC00FB090,0xC00FB0C0), (0xC00EAD70,0xC00EAE90),
    (0xC00E22A0,0xC00E22C8), (0xC00E2348,0xC00E23A8),
    (0xC00E23D0,0xC00E2400), (0xC00EB290,0xC00EB3F0),
    (0xC00EAEF8,0xC00EB098),
    (0xC042EAD0,0xC042EB68), (0xC042EC90,0xC042EE28),
)


def mapped_image():
    image=bytearray(0x3000000)
    main=(ROOT/'out/MAIN_c0000000.bin').read_bytes()[:0x3000000]
    image[:len(main)]=main
    seg=(ROOT/'out/seg1_c2ef6e00.bin').read_bytes()
    image[0x2EF6E00:0x2EF6E00+len(seg)]=seg
    assert len(image)==0x3000000
    return bytes(image)


def w(mu, address, *values):
    mu.mem_write(address, struct.pack('<'+'I'*len(values), *values))


def words(mu, address, count):
    return struct.unpack('<'+'I'*count, mu.mem_read(address, count*4))


class Writeback:
    def __init__(self, width, height):
        self.mu=mu=Uc(UC_ARCH_ARM,UC_MODE_ARM)
        mu.mem_map(ROM,0x3000000); mu.mem_write(ROM,mapped_image())
        mu.mem_map(RAM,0x1000000)
        mu.mem_map(WORK,0x1000); mu.mem_map(STACK,0x10000); mu.mem_map(STOP,0x1000)
        mu.mem_map(0x30000000,0x200000); mu.mem_map(PIXELS,0x400000)
        self.executed=set(); self.sync_calls=[]; self.clear=None; self.packet=None
        self.pixel_extent=None; self.run_mode='return'; self.reached=False
        self.jpeg_inputs=None
        # Native callback C00FB090 resolves the declared output object through
        # its real registry. C00F56D0 follows +14; width/height getters follow
        # output +48 -> descriptor +4 -> {width,height}.
        registry,output,info,geometry=WORK+0x100,WORK+0x200,WORK+0x300,WORK+0x400
        w(mu,0xC31D718C,registry); w(mu,registry,0); w(mu,registry+0x14,output)
        w(mu,output+0x48,info); w(mu,info+4,geometry); w(mu,geometry,width,height)
        w(mu,0xC31D60A0,0xC00FB091); w(mu,0xC31D2534,0)
        w(mu,0xC31D2858,1); w(mu,0x30190000,0x11)
        # Disable the unrelated pre-enabled output changes.
        w(mu,0xC31D5DEC,0,0)
        mu.hook_add(UC_HOOK_CODE,self.code)
        mu.hook_add(UC_HOOK_MEM_WRITE,self.write)

    def ret(self,value):
        self.mu.reg_write(R.UC_ARM_REG_R0,value)
        self.mu.reg_write(R.UC_ARM_REG_PC,self.mu.reg_read(R.UC_ARM_REG_LR))

    def code(self,mu,address,size,_):
        if address==STOP:
            self.reached=True; mu.emu_stop(); return
        if address==0xC00E23A8:
            assert self.run_mode=='writeback'
            self.sync_calls.append((mu.reg_read(R.UC_ARM_REG_R0),mu.reg_read(R.UC_ARM_REG_R1)))
            return self.ret(0)
        if address==0xC00E23D0:
            self.clear=words(mu,mu.reg_read(R.UC_ARM_REG_R0),5)
        if address==0xC00EAEF8:
            self.packet=words(mu,mu.reg_read(R.UC_ARM_REG_R0),0x1D)
        if address==TRIGGER:
            assert self.run_mode=='writeback' and self.packet is not None
            self.reached=True; mu.emu_stop(); return
        if address==0xC01AA888:
            assert self.run_mode=='jpeg'
            self.jpeg_inputs=dict(
                source_info=list(words(mu,mu.reg_read(R.UC_ARM_REG_R1),5)),
                geometry=list(words(mu,mu.reg_read(R.UC_ARM_REG_R2),13)))
            self.reached=True; mu.emu_stop(); return
        if not any(lo<=address and address+size<=hi for lo,hi in NATIVE):
            raise AssertionError(f'unapproved native execution {address:#x}')
        self.executed.add(address)

    def write(self,mu,access,address,size,value,_):
        if PIXELS<=address and address+size<=PIXELS+0x400000:
            end=address+size
            self.pixel_extent=(address,end) if self.pixel_extent is None else (min(address,self.pixel_extent[0]),max(end,self.pixel_extent[1]))
            return
        if (STACK<=address and address+size<=STACK+0x10000 or
            WORK<=address and address+size<=WORK+0x1000 or
            0xC31D0000<=address and address+size<=0xC31E0000 or
            0x30000000<=address and address+size<=0x30200000):
            return
        raise AssertionError(f'unapproved native write {address:#x} size {size}')

    def call(self,address,*args,mode='return'):
        self.run_mode=mode; self.reached=False
        mu=self.mu
        mu.reg_write(R.UC_ARM_REG_SP,STACK+0xFFF0); mu.reg_write(R.UC_ARM_REG_LR,STOP)
        w(mu,STACK+0xFFF0,0,0)
        for i,value in enumerate(args): mu.reg_write(getattr(R,f'UC_ARM_REG_R{i}'),value)
        mu.emu_start(address,STOP+4,count=2000000)
        assert self.reached,'native instruction budget exhausted'
        return mu.reg_read(R.UC_ARM_REG_R0)

    def run(self):
        mu=self.mu
        pair=self.call(0xC0388668)
        self.call(0xC0046030,WORK+0x500,pair)
        self.call(0xC02E5C10,WORK+0x540,WORK+0x500,0,0)
        # Fifth C02E5C10 argument is zero from untouched emulated stack.
        capacity=self.call(0xC02DA6E0,WORK+0x540)
        desc=words(mu,WORK+0x540,12)
        w(mu,WORK+0x600,1,PIXELS)
        self.call(ENTRY,WORK+0x600,mode='writeback')
        assert self.clear is not None and self.packet is not None
        width,height=self.clear[1:3]
        result=dict(descriptor=list(desc),capacity_bytes=capacity,
            declared_writeback_size=[width,height],clear_bytes=width*height*2,
            actual_native_clear_extent=list(self.pixel_extent),
            packet=list(self.packet),
            hardware_height=words(mu,0x30193010,1)[0],
            hardware_stride_words=words(mu,0x30193014,1)[0],
            hardware_destination_words=words(mu,0x30193080,1)[0],
            suspend_fixture_calls=self.sync_calls,
            executed_native_instruction_addresses=len(self.executed))
        assert desc[:6]==(1024,682,0,0,1024,682)
        assert capacity==1024*682*2
        assert self.pixel_extent==(PIXELS,PIXELS+width*height*2)
        assert result['hardware_height']==height
        assert result['hardware_stride_words']==width//2
        assert result['hardware_destination_words']==(PIXELS-0x40000000)//4
        assert self.sync_calls==[(3,1)]
        # The same destination address is attached to the fixed descriptor by
        # native C0699250 in C0383AA0. Here the descriptor object plumbing is a
        # declared fixture; the encoder geometry handoff itself runs ROM.
        w(mu,WORK+0x540+0x1C,PIXELS)
        obj,params=WORK+0x700,WORK+0x740
        w(mu,obj,WORK+0x540); w(mu,obj+0x24,0)
        self.call(0xC042EAD0,obj,params)
        result['jpeg_descriptor_to_params']=list(words(mu,params,13))
        w(mu,params,90); w(mu,params+0x24,capacity); w(mu,params+0x30,PIXELS+0x200000)
        self.call(0xC042EC90,obj,params,WORK+0x7C0,mode='jpeg')
        assert self.jpeg_inputs['source_info'][1]==PIXELS
        assert self.jpeg_inputs['geometry'][:3]==[1024,682,0]
        result['jpeg_encoder_handoff']=self.jpeg_inputs
        return result


class NativeWritebackTests(unittest.TestCase):
    def test_fixed_descriptor_dynamic_native_layout(self):
        results=[]
        cases=[('declared sensitivity example',size) for size in
               ((1024,682),(1024,642),(1024,591),(862,682),(852,682),(814,682))]
        cases += [('observed RGB period hypothesis; getter not measured',size) for size in
                  ((1024,643),(1024,592),(860,682),(852,682),(812,682))]
        for kind,size in cases:
            with self.subTest(kind=kind,size=size):
                r=Writeback(*size).run()
                self.assertEqual(r['declared_writeback_size'],list(size))
                r['case_kind']=kind
                results.append(r)
        if len(sys.argv)>1 and sys.argv[1]=='--json':
            out=Path(__file__).with_name('ss-writeback-native.json')
            out.write_text(json.dumps(dict(note='Declared dimensions; not live measurements. No pixel DMA or LCD scanout emulated.',
                rom_provenance=dict(mapped_range='C0000000..C3000000',
                    mapping='zero-filled 0x3000000 bytes, copy MAIN prefix, then seg1 at C2EF6E00; no seg0 overlay in native fixture',
                    mapped_bytes_sha256=hashlib.sha256(mapped_image()).hexdigest(),
                    main_prefix_sha256=hashlib.sha256((ROOT/'out/MAIN_c0000000.bin').read_bytes()[:0x3000000]).hexdigest(),
                    seg1_sha256=hashlib.sha256((ROOT/'out/seg1_c2ef6e00.bin').read_bytes()).hexdigest()),
                cases=results),indent=2)+'\n')


if __name__=='__main__':
    unittest.main(argv=[sys.argv[0]],verbosity=2)
