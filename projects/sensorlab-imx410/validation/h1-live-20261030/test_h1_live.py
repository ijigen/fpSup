#!/usr/bin/env python3
"""Offline trial-controller guards. No camera imports or operations."""
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('h1_live', Path(__file__).with_name('h1_live.py'))
H = importlib.util.module_from_spec(spec)
spec.loader.exec_module(H)


class FakeP:
    ECHO_SLOT, ECHO_ORIG = 10, 20
    def __init__(self):
        self.memory = {a:0 for a in H.EXTRA_REGS}
        self.memory.update({10:20,H.MUX:1,0x30182000:0})
        self.blobs = {}
        self.events = []
        self.fail_echo = False
    def mem_get(self,a,n=1,**kw):
        return [self.memory.get(a+4*i,0) for i in range(n)]
    def set_echo_handler(self,v):
        self.memory[10]=v
        self.events.append(('handler',v))
    def sh(self,line,**kw):
        self.events.append(('echo',self.memory[10]))
        if self.fail_echo: raise RuntimeError('uncertain')
    def put(self,a,blob,*args): self.blobs[a]=blob


class FakeB:
    F_SETADDR=30
    def __init__(self):
        self.p=FakeP()
        self.ignore_source=False
        self.completion=True
    def P(self):return self.p
    def startstop(self,n):return self.completion
    def wr(self,a,v):
        if not (self.ignore_source and a==H.SOURCE_H):self.p.memory[a]=v
    def call(self,fn,*args):
        if fn==0xC0633B31:
            d=self.p.blobs[args[1]]
            self.p.memory[H.H1]=d[0x1a]
            self.p.memory[H.H2]=d[0x28]
            for a,o in zip(range(0x300F0850,0x300F0860,4),range(0x1c,0x28,3)):
                self.p.memory[a]=int.from_bytes(d[o:o+3],'little')
        elif fn==0xC017FAA1:self.p.memory[H.H1]=args[0]


class Guards(unittest.TestCase):
    def test_driver_selects_only_horizontal_and_known_records(self):
        for r in (0,1):
            for h in (0,1):
                d=H.driver(r,h)
                self.assertEqual((len(d),d[0],d[0x1a],d[0x28]),(44,0,h,0))
        with self.assertRaises(ValueError):H.driver(2,1)

    def test_geometry_accounts_for_full_width_overrun(self):
        self.assertEqual(H.validate_geometry(512,882,512*2653*4,24<<20),512*882*4)
        for args in ((0,882,10000,20000),(512,882,512*2653*4,512*882*4+4096),
                     (512,4097,512*2653*4,24<<20)):
            with self.assertRaises(ValueError):H.validate_geometry(*args)

    def test_configure_protects_source_and_second_stage(self):
        b=FakeB();s=SimpleNamespace(buf=0x45000000,scratch=0x47000000,alloc=24<<20,base_window=0)
        with patch.object(H.time,'sleep',lambda _:None):
            meta=H.configure(b,None,s,(512,2653),H.STAGES[2],{'claim':lambda *_:1000})
        self.assertEqual((meta['hbin'],s.words),(3,882))
        self.assertEqual(b.p.memory[H.SOURCE_H],1)
        self.assertEqual(b.p.memory[H.H2],0)

    def test_missing_source_write_mutant_is_rejected(self):
        b=FakeB();b.ignore_source=True
        s=SimpleNamespace(buf=0x45000000,scratch=0x47000000,alloc=24<<20,base_window=0)
        with patch.object(H.time,'sleep',lambda _:None):
            with self.assertRaisesRegex(RuntimeError,'source overwritten'):
                H.configure(b,None,s,(512,2653),H.STAGES[2],{'claim':lambda *_:1000})

    def test_publication_is_native_d_then_i_with_hook_restoration(self):
        p=FakeP();H.publish_native(p)
        self.assertEqual([v for e,v in p.events if e=='echo'],[0xC000E91C,0xC000EABC])
        self.assertEqual(p.memory[10],20)

    def test_uncertain_native_cache_call_restores_hook(self):
        p=FakeP();p.fail_echo=True
        with self.assertRaises(RuntimeError):H.publish_native(p)
        self.assertEqual(p.memory[10],20)
        self.assertEqual([v for e,v in p.events if e=='echo'],[0xC000E91C])

    def test_unknown_echo_owner_is_not_overwritten(self):
        p=FakeP();p.memory[10]=99
        with self.assertRaises(RuntimeError):H.publish_native(p)
        self.assertEqual(p.events,[])

    def test_no_recovery_completion_cannot_release_buffers(self):
        b=FakeB();b.completion=False;s=SimpleNamespace(scratch=0x47000000)
        saved={a:0 for a in H.EXTRA_REGS}
        with tempfile.TemporaryDirectory() as d,patch.object(H.time,'sleep',lambda _:None):
            with self.assertRaisesRegex(RuntimeError,'keep buffers'):
                H.recover(b,s,(512,2653),saved,Path(d))
            self.assertFalse((Path(d)/'recovered-before-close.json').exists())

    def test_recovery_requires_stopped_channel_and_restored_sources(self):
        b=FakeB();s=SimpleNamespace(scratch=0x47000000)
        saved={a:0 for a in H.EXTRA_REGS}
        with tempfile.TemporaryDirectory() as d,patch.object(H.time,'sleep',lambda _:None):
            H.recover(b,s,(512,2653),saved,Path(d))
            self.assertTrue((Path(d)/'recovered-before-close.json').exists())


if __name__=='__main__':unittest.main()
