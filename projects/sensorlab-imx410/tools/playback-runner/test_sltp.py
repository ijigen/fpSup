"""Real loader-v4 + compiled ARM; RTOS/clock/key executor are declared models.
No camera or transport imports. The model proves order/guards, not playback."""
import json
import os
import pathlib
import struct
import subprocess
import sys
import tempfile
import unittest

import build_sltp as B
import test_v4 as V
from unicorn import UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_SP

HERE=pathlib.Path(__file__).resolve().parent
FIELDS='magic version req_mode req_seq seen_seq active_seq done_seq phase mode error reject_seq reject_error task_id task_rc accepted_us phase_us done_us n_events cine_at_arm busy_at_arm'.split()
OFF={n:4*i for i,n in enumerate(FIELDS)}
SRC=os.environ.get('SLTP_SRC')
BLOB,INFO=B.build(SRC)
LOADER=V.B.loader_bin()[0]

class Cam(V.Camera):
    def __init__(self,create=7,start=0):
        self.clock=1_400_000; self.cine=True; self.keys=[]; self.desc=None
        self.create_rc=create; self.start_rc=start; self.started=[]; self.shell_rc=0
        self.stop_when_done=False; self.min_sp=V.T3.STACK; self.key_ms=1
        super().__init__(*V.card(('SLTP.BIN',BLOB),loader=LOADER))
        for addr,name in ((0xC0057AE8,'SETTINGS_GET'),(0xC0058340,'IS_CINE'),(0xC03D9C20,'SHELL_EXEC')):
            self.by_addr[addr]=name
            self.mu.mem_write(addr,struct.pack('<I',0xE12FFF1E))
        for a in (0xC347D1D4,0xC347E08C,0xC3476608,0xC358E140,0xC35A952C):self.put(a,0)
        self.boot()
        self.block=V.blocks(self)['SLTP.BIN'];self.at=self.block+INFO['state_off']

    def _hook(self,mu,addr,size,data):
        n=self.by_addr.get(addr)
        if n in ('TK_CRE','TK_STA','SETTINGS_GET','IS_CINE','SHELL_EXEC','D_SLEEP','TICK'):
            assert self.r(UC_ARM_REG_SP)%8==0,(n,hex(self.r(UC_ARM_REG_SP)))
            self.min_sp=min(self.min_sp,self.r(UC_ARM_REG_SP))
        if n=='TK_CRE':
            self.desc=list(struct.unpack('<8I',mu.mem_read(self.r(UC_ARM_REG_R0),32)))
            return self._ret(self.create_rc)
        if n=='TK_STA':
            self.started.append((self.r(UC_ARM_REG_R0),self.r(UC_ARM_REG_R1)))
            return self._ret(self.start_rc)
        if n=='SETTINGS_GET':return self._ret(0xC3001000)
        if n=='IS_CINE':return self._ret(int(self.cine))
        if n=='TICK':return self._ret(self.clock&0xffffffff)
        if n=='D_SLEEP':
            ms=self.r(UC_ARM_REG_R0);assert ms==20
            self.clock+=ms*1000
            if self.stop_when_done and self.state()['phase']==8:
                mu.emu_stop();return
            return self._ret(0)
        if n=='SHELL_EXEC':
            assert self.r(UC_ARM_REG_R0)==0xC3756904
            line=self.cstr(self.r(UC_ARM_REG_R1),16)
            assert line in ('key PLAYON','key PLAYOFF','key OKON','key OKOFF','key S1ON','key S1OFF'),line
            self.keys.append((line,self.clock&0xffffffff))
            self.clock+=self.key_ms*1000
            return self._ret(self.shell_rc)
        return super()._hook(mu,addr,size,data)

    def state(self):return dict(zip(FIELDS,struct.unpack('<20I',self.mu.mem_read(self.at,80))))
    def events(self):return [struct.unpack('<4I',self.mu.mem_read(self.at+80+16*i,16)) for i in range(self.state()['n_events'])]
    def request(self,mode=2,seq=1):
        self.put(self.at+OFF['req_mode'],mode);self.put(self.at+OFF['req_seq'],seq)
    def step(self,us=0):
        self.clock+=us
        return self.call(self.block+(INFO['functions']['sltp_step']&~1),thumb=True,sp=V.T3.STACK-0x1008)
    def finish(self):
        for _ in range(1100):
            self.step(20_000)
            if self.state()['phase']==8:return
        raise AssertionError('fixed sequence did not finish')


@unittest.skipIf(V.Uc is None or not V.T3.IMAGE.exists(),'requires Unicorn and local firmware')
class Trial(unittest.TestCase):
    def test_loader_owns_block_and_task_descriptor(self):
        c=Cam();s=c.state()
        self.assertEqual((s['magic'],s['version'],s['phase'],s['n_events']),(0x31505453,1,0,0))
        self.assertEqual(c.callsvc('find',0x50544c53),c.at)
        self.assertEqual(c.desc[1],0x41)
        self.assertEqual(c.desc[3:5],[25,0x2000])
        self.assertTrue(c.block<=c.desc[2]<c.block+len(BLOB))
        self.assertEqual(c.started,[(7,0)])
        self.assertEqual(c.keys,[]);self.assertEqual(c.journal(),[])
        self.assertNotIn(c.block-0x80000000,c.freed)
        self.assertEqual(c.state()['req_seq'],0)
        self.assertEqual(struct.unpack_from('<2I',BLOB,36),(0,0)) # no DMA or borrowed memory
        c.step();self.assertEqual(c.keys,[])

    def test_movie_sequence_and_timestamp_delays(self):
        c=Cam();c.request();c.step();accepted=c.clock
        c.step(1_999_999);self.assertEqual(c.keys,[])
        c.step(1);c.finish()
        self.assertEqual([x[0] for x in c.keys],['key PLAYON','key PLAYOFF','key OKON','key OKOFF','key S1ON','key S1OFF'])
        ev=c.events();self.assertEqual([x[0] for x in ev],[1,2,3,4,5,6])
        self.assertGreaterEqual(ev[0][1]-accepted,2_000_000)
        for i,delay in enumerate((800_000,2_000_000,800_000,3_000_000,800_000),1):
            self.assertGreaterEqual(ev[i][1]-ev[i-1][2],delay)
        self.assertGreaterEqual(c.state()['done_us']-ev[-1][2],10_000_000)
        self.assertEqual(c.state()['done_seq'],1)
        for _ in range(10):c.step(1_000_000)
        self.assertEqual(len(c.keys),6)

    def test_thumbnail_omits_ok_and_releases_both_keys(self):
        c=Cam();c.request(1);c.finish()
        self.assertEqual([x[0] for x in c.keys],['key PLAYON','key PLAYOFF','key S1ON','key S1OFF'])
        ev=c.events();self.assertGreaterEqual(ev[2][1]-ev[1][2],5_000_000)
        self.assertEqual(c.state()['done_seq'],1)

    def test_invalid_mode_non_cine_and_all_record_guards_reject(self):
        c=Cam();q=0
        for mode in (0,3,0xffffffff):
            q+=1;c.request(mode,q);c.step();self.assertEqual(c.state()['error'],1)
        c.cine=False;q+=1;c.request(2,q);c.step();self.assertEqual(c.state()['error'],2);c.cine=True
        for addr,selector,byte in ((0xC347E08F,0,True),(0xC3476609,0x21,True),(0xC358E140,0,False),(0xC35A952C,0,True)):
            c.put(0xC347D1D4,selector)
            if byte:c.mu.mem_write(addr,b'\1')
            else:c.put(addr,0xC5001000)
            q+=1;c.request(2,q);c.step();self.assertEqual(c.state()['error'],3)
            if byte:c.mu.mem_write(addr,b'\0')
            else:c.put(addr,0)
        self.assertEqual(c.keys,[])

    def test_gate_rechecked_after_quiet_window(self):
        for which in ('record','cine'):
            c=Cam();c.request();c.step()
            if which=='record':c.put(0xC35A952C,1)
            else:c.cine=False
            c.step(2_000_000)
            self.assertEqual(c.state()['phase'],9);self.assertEqual(c.keys,[])
            c.put(0xC35A952C,0);c.cine=True;c.step(10_000_000)
            self.assertEqual(c.keys,[],'rejected sequence must not retry')

    def test_active_request_rejected_not_queued_and_mode_latched(self):
        c=Cam();c.request(1,1);c.step();c.request(2,2);c.step()
        self.assertEqual((c.state()['reject_seq'],c.state()['reject_error']),(2,4))
        c.finish();self.assertEqual(c.state()['done_seq'],1)
        self.assertEqual([x[0] for x in c.keys],['key PLAYON','key PLAYOFF','key S1ON','key S1OFF'])
        c.step(10_000_000);self.assertEqual(c.state()['phase'],8)
        c.request(2,1);c.step();self.assertEqual(c.state()['phase'],8)
        c.request(2,3);c.step();self.assertEqual(c.state()['phase'],1)

    def test_native_return_codes_recorded_without_retrying_on(self):
        c=Cam();c.shell_rc=0xffffffff;c.request();c.finish()
        self.assertEqual(len(c.keys),6)
        self.assertEqual([e[3] for e in c.events()],[0xffffffff]*6)
        self.assertEqual(c.keys[-1][0],'key S1OFF')

    def test_clock_wrap_and_real_task_loop(self):
        c=Cam();c.clock=0xfffff000;c.request();c.stop_when_done=True
        c.call(c.desc[2]&~1,thumb=bool(c.desc[2]&1),sp=V.T3.STACK-0x1008)
        self.assertEqual(c.state()['done_seq'],1)
        self.assertEqual(len(c.keys),6)
        self.assertLess((c.state()['done_us']-c.state()['accepted_us'])&0xffffffff,21_000_000)
        self.assertLess(V.T3.STACK-0x1008-c.min_sp,0x1000) # modeled callees, not native worst-case bound

    def test_task_creation_or_start_failure_retains_provided_block(self):
        for create,start,why in ((-33,0,5),(7,-5,6)):
            c=Cam(create,start);s=c.state()
            self.assertEqual((s['phase'],s['error']),(10,why))
            self.assertEqual(c.keys,[])
            self.assertNotIn(c.block-0x80000000,c.freed)
            self.assertEqual(c.started,[] if create<1 else [(7,0)])

    def test_sequence_writes_only_private_memory(self):
        c=Cam();writes=[]
        c.mu.hook_add(UC_HOOK_MEM_WRITE,lambda mu,access,addr,size,value,data:writes.append((addr,size)))
        c.request();c.finish()
        for a,n in writes:
            self.assertTrue(c.block<=a and a+n<=c.block+INFO['block_size'] or
                            V.T3.STACK-0x3008<=a and a+n<=V.T3.STACK-0x1008,(hex(a),n))

MUTANTS=[
 ('missing PLAY release','key(s,K_PLAY_OFF); phase(s,PLAY_SETTLE);','phase(s,PLAY_SETTLE);','test_movie_sequence_and_timestamp_delays'),
 ('missing S1 release','key(s,K_S1_OFF); phase(s,EXIT_WAIT);','phase(s,EXIT_WAIT);','test_movie_sequence_and_timestamp_delays'),
 ('short key hold','#define GAP_US 800000u','#define GAP_US 100000u','test_movie_sequence_and_timestamp_delays'),
 ('short post exit wait','#define EXIT_US 10000000u','#define EXIT_US 100000u','test_movie_sequence_and_timestamp_delays'),
 ('thumbnail sends OK','if (s->mode==2u)','if (s->mode>=1u)','test_thumbnail_omits_ok_and_releases_both_keys'),
 ('record flags ignored','s->busy_at_arm = busy();','s->busy_at_arm = busy() & 0u;','test_invalid_mode_non_cine_and_all_record_guards_reject'),
 ('quiet window recheck removed','s->error=gate(s);','s->error=0;','test_gate_rechecked_after_quiet_window'),
 ('mode not latched','if (s->mode==2u)','if (s->req_mode==2u)','test_active_request_rejected_not_queued_and_mode_latched'),
]

def mutate():
    source=(HERE/'sltp.c').read_text();results=[]
    for label,old,new,test in MUTANTS:
        assert source.count(old)==1,label
        with tempfile.TemporaryDirectory(prefix='sltp-mut-') as tmp:
            p=pathlib.Path(tmp)/'sltp.c';p.write_text(source.replace(old,new));B.build(p)
            run=subprocess.run([sys.executable,'-B','-m','unittest','-q','test_sltp.Trial.'+test],cwd=HERE,
                               env=dict(os.environ,SLTP_SRC=str(p)),capture_output=True,text=True)
        caught=run.returncode!=0 and ('FAIL: '+test) in run.stderr
        results.append(dict(label=label,compiled=True,caught=caught,stderr=run.stderr))
        print(('CAUGHT' if caught else 'UNVERIFIED')+': '+label,flush=True)
    out=HERE/'validation';out.mkdir(exist_ok=True)
    (out/'mutants.json').write_text(json.dumps(results,indent=2)+'\n')
    return 0 if all(r['caught'] for r in results) else 1

if __name__=='__main__':
    if '--mutate' in sys.argv:raise SystemExit(mutate())
    unittest.main()
