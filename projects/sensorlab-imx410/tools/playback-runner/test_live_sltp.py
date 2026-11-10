#!/usr/bin/env python3
"""Fake transport only; no putfile import, camera, USB or real sleeping."""
import contextlib,io,json,os,pathlib,struct,sys,tempfile,types,unittest
from unittest.mock import patch
import live_sltp as L
BLOCK=0xC50F2380
INFO,LOCAL=L.local_build(L.HERE/'out-v1/build.json')
AT=BLOCK+INFO['state_off']
LOG=f'01 00329FB8 00000000 \n0A {BLOCK:08X} 00000000 SLTP.BIN\n'
class Fake:
    def __init__(self):
        self.calls=[];self.raw=bytearray(176);self.remote=bytearray(LOCAL)
        for k,v in {0:0x31505453,4:1,48:17}.items():struct.pack_into('<I',self.raw,k,v)
        struct.pack_into('<I',self.remote,1612,AT)
        self.recording,self.app=0,2
        self.fail_commit,self.commit_err,self.ignore_mode=False,False,False
        self.window_perm=0
    def mem_caps(self,**kw):
        self.calls.append(('caps',kw));return dict(windows=[(0,0,0)]*8)
    def mem_window(self,slot,base,size,perm):
        self.calls.append(('window',perm));self.window_perm=perm
    def mem_read(self,at,n,**kw):
        self.calls.append(('read',at,n,kw))
        assert self.window_perm==1 and kw['sync'] is True
        if at==BLOCK-0x80000000:return bytes(self.remote)
        assert at==AT-0x80000000 and n==176
        return bytes(self.raw)
    def sh(self,cmd,**kw):
        self.calls.append(('sh',cmd,kw));assert kw['retries']==0
        if cmd=='status get is_recording':return f'is_recording -> {self.recording}\n'
        if cmd=='status get app_current':return f'app_current -> {self.app}\n'
        if cmd.startswith('mem get'):
            return '\n'.join(f'get : A:0x{AT+4*i:08X}, D:0x{v:08X}' for i,v in enumerate(struct.unpack('<44I',self.raw)))
        if cmd.startswith('mem set'):
            _,_,a,v=cmd.split();a,v=int(a,16),int(v,16)
            assert self.window_perm==0 and a in (AT+8,AT+12)
            if a==AT+12:
                assert kw['timeout_ms']==1000
                if self.fail_commit:raise TimeoutError('lost commit ack')
                if self.commit_err:return 'ERR timeout'
            if a!=AT+8 or not self.ignore_mode:struct.pack_into('<I',self.raw,a-AT,v)
            return 'set done'
        raise AssertionError('unexpected '+cmd)
class Host(unittest.TestCase):
    def fake_run(self,api,out,command='arm',mode=2):
        self.sleeps=[]
        def quiet(s):self.sleeps.append((s,list(api.calls)))
        return L.run(api,command,mode,INFO,LOCAL,out,get_log=lambda _:LOG,sleep=quiet)
    def test_mode_first_seq_last_and_no_usb_after_commit(self):
        for mode in (1,2):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                api=Fake();r=self.fake_run(api,pathlib.Path(tmp),mode=mode)
                writes=[x for x in api.calls if x[0]=='sh' and x[1].startswith('mem set')]
                self.assertEqual([x[1] for x in writes],[f'mem set 0x{AT+8:08X} 0x{mode:08X}',f'mem set 0x{AT+12:08X} 0x00000001'])
                self.assertEqual(api.calls[-1],writes[-1]);self.assertEqual(self.sleeps,[(30,api.calls)])
                self.assertEqual(r['seq'],1);self.assertFalse(r['physical_exit_verified']);self.assertEqual(api.window_perm,0)
    def test_ack_exception_or_error_still_only_waits_locally(self):
        for error in (False,True):
            with self.subTest(error=error),tempfile.TemporaryDirectory() as tmp:
                api=Fake();api.commit_err=error;api.fail_commit=not error
                with self.assertRaises(RuntimeError if error else TimeoutError):
                    self.fake_run(api,pathlib.Path(tmp))
                self.assertEqual(self.sleeps,[(30,api.calls)])
                self.assertEqual(api.calls[-1][1],f'mem set 0x{AT+12:08X} 0x00000001')
                self.assertIn('commit_attempted_utc',json.loads((pathlib.Path(tmp)/'arm.json').read_text()))
    def test_wrong_code_or_context_revokes_and_refuses(self):
        for off in (100,1612):
            with self.subTest(off=off),tempfile.TemporaryDirectory() as tmp:
                api=Fake();api.remote[off]^=1
                with self.assertRaises(RuntimeError):self.fake_run(api,pathlib.Path(tmp))
                self.assertEqual(api.calls[-1],('window',0))
                self.assertFalse(any(x[0]=='sh' and x[1].startswith('mem set') for x in api.calls))
    def test_active_pending_invalid_and_failed_task_cannot_write(self):
        for off,val in ((0,0),(28,1),(28,7),(12,1),(48,0),(52,0xffffffff),(28,10)):
            with self.subTest(off=off,val=val),tempfile.TemporaryDirectory() as tmp:
                api=Fake();struct.pack_into('<I',api.raw,off,val)
                with self.assertRaises((RuntimeError,ValueError)):self.fake_run(api,pathlib.Path(tmp))
                self.assertFalse(any(x[0]=='sh' and x[1].startswith('mem set') for x in api.calls))
    def test_idle_gate_and_mode_readback_fail_before_commit(self):
        for kind in ('recording','app','ignore_mode'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as tmp:
                api=Fake();setattr(api,kind,1 if kind!='ignore_mode' else True)
                with self.assertRaises(RuntimeError):self.fake_run(api,pathlib.Path(tmp))
                self.assertFalse(any(x[0]=='sh' and x[1].startswith(f'mem set 0x{AT+12:08X}') for x in api.calls))
    def test_status_is_read_only_and_does_not_prove_physical_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            api=Fake();r=self.fake_run(api,pathlib.Path(tmp),command='status',mode=None)
            self.assertTrue(r['no_request_sent']);self.assertFalse(r['state']['physical_exit_verified'])
            self.assertFalse(any(x[0]=='sh' and x[1].startswith('mem set') for x in api.calls));self.assertEqual(self.sleeps,[])
    def test_human_confirmation_required_before_build_or_transport(self):
        for cmd in ('arm','status'):
            with self.subTest(cmd=cmd),patch.object(sys,'argv',['live_sltp',cmd,'--out','/not-created']),patch.object(L,'local_build',side_effect=AssertionError('too early')),contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as r:L.main()
                self.assertEqual(r.exception.code,2)
    def test_exact_unique_log_entry(self):
        self.assertEqual(L.loaded_block(LOG),BLOCK)
        for txt in ('',LOG+LOG,LOG.replace('SLTP.BIN','SLTP.BIN.old'),LOG.replace(f'{BLOCK:08X}','450F2380')):
            with self.subTest(txt=txt):
                with self.assertRaises(RuntimeError):L.loaded_block(txt)
    def test_relative_output_is_resolved_before_getfile_changes_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=pathlib.Path(tmp)/'relative-evidence';out.mkdir()
            relative=pathlib.Path(os.path.relpath(out,pathlib.Path.cwd()))
            def getfile(cmd,**kwargs):
                self.assertEqual(kwargs['cwd'],L.SHELL)
                self.assertEqual(pathlib.Path(cmd[4]),out.resolve()/'LOAD.LOG')
                pathlib.Path(cmd[4]).write_text(LOG)
                return types.SimpleNamespace(returncode=0,stdout='read complete',stderr='')
            with patch.object(L.subprocess,'run',side_effect=getfile):
                self.assertEqual(L.read_current_log(relative),LOG)
            target=pathlib.Path(tmp)/'main-evidence'
            relmain=os.path.relpath(target,pathlib.Path.cwd())
            with patch.object(sys,'argv',['live_sltp','status','--confirm-returned-liveview','--out',relmain]),patch.dict(sys.modules,{'putfile':object()}),patch.object(L,'host_lease',return_value=contextlib.nullcontext()),patch.object(L,'run',return_value={}) as run,contextlib.redirect_stdout(io.StringIO()):
                L.main()
                self.assertEqual(run.call_args.args[5],target.resolve())
    def test_shared_flock_excludes_second_operator(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=pathlib.Path(tmp)/'lease'
            with L.host_lease(p):
                with self.assertRaises(BlockingIOError):
                    with L.host_lease(p):pass
            with L.host_lease(p):pass
    def test_completed_sequence_increments_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            api=Fake()
            for off,v in ((12,7),(16,7),(20,7),(24,7),(28,8)):struct.pack_into('<I',api.raw,off,v)
            self.assertEqual(self.fake_run(api,pathlib.Path(tmp))['seq'],8)
            self.assertEqual(api.calls[-1][1],f'mem set 0x{AT+12:08X} 0x00000008')
if __name__=='__main__':unittest.main(verbosity=2)
