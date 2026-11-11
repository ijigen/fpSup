"""LUT4 + exact shared v4 UI through the actual ARM callbacks, offline.

Only the native GUI app/variable-post queue is the maintained v4 fake. LUT4,
core, string/page hooks, registry, UI data and popup callbacks are real bytes.
No claim about camera display rendering, DMA coherency or live monitoring.
"""
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE),str(HERE.parent/'loader-v4')]
import build_sup as P
import test_sup_native as N
import test_ui_v4 as U
import color_ui as C
from cinemadng import COLOR_SPACES,COMMON_GAMMAS


def runtime_files(directory):
    root=Path(directory)
    return {'\\'+str(p.relative_to(root)).replace('/','\\'):p.read_bytes()
            for p in root.rglob('*') if p.is_file()}


class Camera(U.Cam):
    call=N.Camera.call
    svc=N.Camera.svc
    lut=N.Camera.lut
    invoke=N.Camera.invoke
    status=N.Camera.status
    render=N.Camera.render
    power_off_all=N.TB.Camera.power_off_all
    loaded=N.TB.Camera.loaded

    def __init__(self,files,autorun):
        entries=[]
        for path,data in files.items():
            name=path.removeprefix('\\fpSup\\')
            if path.startswith('\\fpSup\\') and '\\' not in name and name.upper().endswith('.BIN'):
                entries.append((name,0x20,len(data)))
        entries += [('UI',0x10,0),('LUT',0x10,0)]
        with patch.object(N.T4.Uc,'hook_add',N.rom_hook):
            super().__init__(files,{'\\fpSup':entries})
        self.mu.mem_write(N.T3.CAVE_LOW,bytes(0x200))
        for address,value in P.B.V3.loader_words(autorun).items(): self.put(address,value)
        self.by_addr[N.TB.POP]='AR_POP'
        self.put(N.TB.POP,0xe12fff1e)
        self.put(N.TB.TABLE+0x21c,2)
        self.put(N.TB.TABLE+36+4,0xC03DA158)
        self.put(N.TB.TABLE+72+4,N.TB.LINE)
        self.put(N.TB.TABLE+72+12,N.TB.CTX)
        self.put(N.TB.CTX+0x90,1); self.put(N.TB.CTX+0x94,N.TB.FOBJ)
        self.put(N.T3.DRAW,N.T3.DRAW_PAUSED)
        self.fallback=None
        self.page_entries()
        N.TB.run_autorun(self,autorun)

    PAGE_ENTRIES=U.F6.FAKE+0xC000                # free in the fake app's area
    def page_entries(self):
        """The reader's runtime page entries (fpui_stock.c READER_ENTRIES / READER_TABLE:
        44 bytes each, +04 name, +08 offset from the NBU base), here only the set the
        COLOR list's FPUI block copies -- the camera has all of them."""
        sys.path.insert(0,str(HERE.parent/'colshare'))
        import colshare_ui
        a,off,_n=colshare_ui.O.resource_set('ColorButtonMenu')
        at=self.PAGE_ENTRIES;name=at+44
        self.mu.mem_write(at,bytes(44));self.mu.mem_write(name,b'ColorButtonMenu\0')
        self.put(at+4,name);self.put(at+8,off)
        self.put(U.F6.READER+0xA8,1);self.put(U.F6.READER+0xAC,at)

    def _hook(self,mu,addr,size,data):
        if N.borrow_hook(self,mu,addr): return True
        if addr==U.F6.NBR_LOAD:
            pack=bytes(mu.mem_read(self.r(N.T3.UC_ARM_REG_R1),self.r(N.T3.UC_ARM_REG_R2)))
            if C.MACHINE.encode() in pack:
                n=len(self.machine_names);self.machine_names.append(C.MACHINE)
                machine=U.F6.FAKE+0x9000+0x40*n
                name=U.F6.FAKE+0x9800+0x20*n
                mu.mem_write(name,C.MACHINE.encode()+b'\0');self.put(machine+8,name)
                self.new_machine=machine
                return U.F6.Cam._hook(self,mu,addr,size,data)
        if addr==U.F6.NBR_LOAD and self.nbr_result==0:
            pack=bytes(mu.mem_read(self.r(N.T3.UC_ARM_REG_R1),self.r(N.T3.UC_ARM_REG_R2)))
            if b'modelCSV' in pack[:256]:          # Color's own lists (settings_page.csv_pack)
                self.csv_models=C.S.inspect_csv_pack(pack)
                self.nbr_calls.append(([self.r(N.T3.UC_ARM_REG_R0),0,len(pack),0],0,pack))
                return self._ret(0)
        if addr==N.TB.POP:
            self.calls.append('AR_POP')
            self.put(N.TB.TABLE+0x21c,self.w(N.TB.TABLE+0x21c)-1)
            return self._ret(0)
        return super()._hook(mu,addr,size,data)

    def slot(self,k,private=True):
        prefix=C.PREFIX if private else 'FT_'
        return {g:self.vars[prefix+U.FP4.slot_var(g,k)[3:]][1] for g in U.FP4.GROUPS}

    def current_rows(self,private=True):
        return {self.slot(k,private)['N']:(k,self.slot(k,private)) for k in range(6)
                if self.slot(k,private)['Visible']}

    def press(self,key): self.notify(C.PREFIX+'Key',key)

    def open_color(self):
        k,row=self.current_rows(False)['LUT manager']
        self.notify('FT_Key',41+k)
        return row

    def find_row(self,title):
        if title in self.current_rows(): return self.current_rows()[title]
        page=self.vars[C.PREFIX+'PageText'][1].strip()
        current,total=map(int,page.split('/')) if '/' in page else (1,1)
        for _ in range(current-1): self.press(10)
        for _ in range(total):
            if title in self.current_rows(): return self.current_rows()[title]
            self.press(11)
        raise AssertionError('private row unreachable: '+title)

    def choose(self,title,choice):
        k,row=self.find_row(title)
        assert choice<=row['Max'],(title,choice,row)
        self.notify(C.PREFIX+f'Choice{k}',choice)


@unittest.skipIf(N.T4.Uc is None or not N.T3.IMAGE.exists(),'needs Unicorn and firmware image; skip is unverified')
class LutUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sup,_=P.build_sup(N.MUTANT_SOURCE or P.SOURCE)
        cls.ar,cls.loader,_=P.B.boot_card(slim=True,ui=True)
        cls.data=P.B.ui_files()
        cls.data['COLOR.BIN']=C.data_file()[0]
        cls.smgr=P.B.supmgr_sup()
        cls.prepared=P.asset(P.identity())

    def files(self,asset=True,manager=True):
        files={'\\fpSup\\LOADER.BIN':self.loader,'\\fpSup\\LUT.BIN':self.sup,
               **{'\\fpSup\\UI\\'+name:data for name,data in self.data.items()}}
        if asset: files[N.ASSET]=self.prepared
        if manager: files['\\fpSup\\SUPMGR.BIN']=self.smgr
        return files

    def cam(self,open_color=True,**kw):
        c=Camera(self.files(**kw),self.ar)
        if open_color:c.open_color()
        return c

    def test_home_has_one_lut_manager_row_and_it_opens_the_manager(self):
        c=self.cam(open_color=False)
        self.assertEqual(U.ui_lines(c),[(0,0,'LOADER.BIN'),(0x100,2,'LOADER.BIN')])
        self.assertEqual(c.callsvc('page_count'),2)
        self.assertEqual(set(c.current_rows(False)),{'LUT manager','SupManager'})
        self.assertEqual(c.current_rows(False)['LUT manager'][1]['Jump'],1)
        c.open_color()
        self.assertIn(C.MACHINE,c.machines())
        # no library (a single prepared cube): the manager says so, as RES-Custom's "No RCD files"
        self.assertEqual((c.vars['LC_G0'][1],c.vars['LC_Visible0'][1],c.vars['LC_Lock0'][1]),('No LUT files',1,1))
        self.assertEqual(c.vars['LC_Header'][1],'LUT (0/12)')
        self.assertEqual(c.vars['LC_RightFooter'][1],' ')
        self.assertEqual(c.status()['asset'],0)
        self.assertEqual(c.misaligned,[])

    def test_without_supmanager_the_lut_manager_still_opens(self):
        c=self.cam(manager=False)
        self.assertEqual(c.callsvc('page_count'),1)
        self.assertEqual(set(c.current_rows(False)),{'LUT manager'})
        self.assertEqual(c.vars['LC_Header'][1],'LUT (0/12)')

    def test_pages_and_their_routes_through_the_stock_matcher(self):
        mpage,mrefs,_row0,slots=C.MP.build()
        spage,srefs,_srow0=C.make_settings('LUT settings')
        C.P.check_page(mpage,*C.P.stock_pool());C.Y.check_settings_page(spage)
        for page in (mpage,spage):self.assertFalse(C.P.Lab.duplicate_local_ids(page))
        self.assertEqual(len(set(slots)),6)
        pages=[(C.MP.PAGE,mpage),(C.SETTINGS_PAGE,spage)]
        pack=C.F.FT.build_pack(pages,machine=C.MACHINE,trans=C.TRANSITIONS)
        matcher=C.F.FT.SL;old=matcher.MACHINE
        try:
            matcher.MACHINE=C.MACHINE
            import nbu_probe
            with patch.object(nbu_probe.NbuProbe,'BLOB_MAX',0x90000):
                got=matcher.native_switch(pack,[(a,e) for a,_b,e in C.TRANSITIONS])
        finally:matcher.MACHINE=old
        for a,b,e in C.TRANSITIONS:self.assertEqual(got[(a,e)][0],b)
        declared={n for _t,n,_v in C.variables()}
        named={t for _o,t in mrefs+srefs if t.startswith('LC_')}-{C.MP.GO_TEXT,C.MP.CONV_EVENT,C.MP.BUSY_EVENT,C.Y.BACK_TEXT}-{n for n,_d in C.Y.models()}
        self.assertEqual(named-declared,set())

    def test_manager_overlay_while_converting(self):
        """busy_overlay: Y1_1's BG box, focusable, opacity LC_Busy; three cmn_clock frames, opacity
        LC_Clock0..2 (no text of its own: SS__3197's striped band was its 1024-wide centred copy of LC_OK);
        Root's first child the ColorChecker chart (checker_chart) over it; ReturnCheck's LC_ConvStart
        focuses the box, LC_ConvEnd gives focus to LC_Focus, then LC_Key = 90."""
        import struct
        page,refs,_row0,_slots=C.MP.build()
        img,pool=C.P.stock_pool()
        recs=[bytes(r.to_bytes()) for r in C.P.N.split(page)]
        offs=[];o=0
        for r in recs:offs.append(o);o+=len(r)
        at={o2:t for o2,t in refs}
        u=lambda r,k:struct.unpack_from('>I',r,k)[0]
        text=lambda i,k:at.get(offs[i]+k) or pool.text(u(recs[i],k))
        kind=lambda i:pool.text(u(recs[i],8)) if u(recs[i],0)!=0x10003 else 'object'
        heads=[i for i,r in enumerate(recs) if u(r,0)==0x10003]
        parent={u(recs[i],20):u(recs[i],24) for i in heads}
        root_kids=[u(recs[i],20) for i in heads if u(recs[i],24)==1]
        chart_id,o_id=root_kids[:2]
        by=C.P.by_object([bytearray(r) for r in recs])
        owned=lambda oid:by[oid][1:]
        mine=owned(o_id)
        self.assertEqual(sorted(kind(i) for i in mine if u(recs[i],0)!=0x10006 or kind(i)!='appVariableEvent'),
                         ['controlValue','drawRect','objectBase'])
        base=next(recs[i] for i in mine if kind(i)=='objectBase')
        self.assertEqual(struct.unpack_from('>4f',base,32),(0.0,99.0,1024.0,486.0))
        kids=[k for k,p2 in parent.items() if p2==o_id]
        self.assertEqual(len(kids),3)
        self.assertEqual(u(recs[next(i for i in heads if u(recs[i],20)==o_id)],16),3)
        allvars=lambda oid:{t for i in owned(oid) for k2 in range(20,len(recs[i])-3) for t in [at.get(offs[i]+k2)] if t and t.startswith('LC_')}
        self.assertEqual(allvars(o_id),{'LC_Busy'})
        imgs=[]
        for k in kids:
            v=allvars(k)
            self.assertFalse([i for i in owned(k) if kind(i)=='drawText'],'no text in the box')
            d=[i for i in owned(k) if kind(i)=='drawImage']
            imgs.append(pool.text(u(recs[d[0]],32)))
            self.assertEqual(struct.unpack_from('>2f',recs[d[0]],44),(44.0,80.0))
            self.assertEqual(len(v),1);self.assertTrue(next(iter(v)).startswith('LC_Clock'))
        self.assertEqual(sorted(imgs),['cmn_clock_1','cmn_clock_2','cmn_clock_3'])
        self.check_chart(recs,offs,at,pool,heads,parent,by,chart_id)
        def event(name):
            i=next(i for i in owned(C.MP.RETURN_CHECK) if kind(i)=='appStateEvent' and text(i,36)==name)
            return [recs[i+1+a] for a in range(u(recs[i],16))],i
        acts,i=event('LC_ConvStart')
        self.assertEqual([(pool.text(u(a,8)),u(a,40)) for a in acts],[('controlFocus',o_id)])
        acts,i=event('LC_ConvEnd')
        self.assertEqual([pool.text(u(a,8)) for a in acts],['controlFocus','controlAppVariable'])
        self.assertEqual(at.get(offs[i+1]+40),'LC_Focus')
        self.assertEqual(len(acts[0]),45)
        self.assertEqual((at.get(offs[i+2]+36),at.get(offs[i+2]+41) or pool.text(u(acts[1],41))),('LC_Key','90'))
        self.assertEqual([u(a,28) for a in acts],[1,2])

    def check_chart(self,recs,offs,at,pool,heads,parent,by,chart_id):
        """checker_chart: 48 halves in a 6 x 4 grid, each a drawRect whose colour is LC_Pnn (conv.c
        conv_chart's order: patch p top 2p, bottom 2p + 1), the bar's fill width LC_Bar, the match LC_Match,
        all of it (and the panel) opacity LC_Chart."""
        import struct
        u=lambda r,k:struct.unpack_from('>I',r,k)[0]
        kind=lambda i:pool.text(u(recs[i],8)) if u(recs[i],0)!=0x10003 else 'object'
        owned=lambda oid:by[oid][1:]
        def binds(oid):
            out=[]
            for i in owned(oid):
                if kind(i)=='appVariableEvent':
                    out.append((at.get(offs[i]+40),u(recs[i],45),pool.text(u(recs[i],49)),u(recs[i],54) if len(recs[i])==62 else None))
            return out
        comp_id=lambda oid,name:u(recs[next(i for i in owned(oid) if kind(i)==name)],24)
        self.assertEqual(binds(chart_id),[('LC_Chart',comp_id(chart_id,'objectBase'),'opacity',None)])
        kids=[k for k,p2 in parent.items() if p2==chart_id]
        self.assertEqual(len(kids),2*24+3)
        self.assertEqual(u(recs[by[chart_id][0]],16),len(kids))
        halves={}
        for k in kids:
            b=binds(k)
            self.assertIn(('LC_Chart',comp_id(k,'objectBase'),'opacity',None),b,k)
            colour=[x for x in b if x[2]=='color']
            if colour:
                self.assertEqual(len(colour),1)
                self.assertEqual(colour[0][1],comp_id(k,'drawRect'))
                base=recs[next(i for i in owned(k) if kind(i)=='objectBase')]
                halves[colour[0][0]]=struct.unpack_from('>4f',base,32)
        self.assertEqual(sorted(halves),C.MP.patch_vars())
        for p in range(24):
            r,cc=divmod(p,6)
            top,bot=halves[f'LC_P{2*p:02d}'],halves[f'LC_P{2*p+1:02d}']
            self.assertEqual((top[0],top[1]),(20.0+108*cc,10.0+64*r))
            self.assertEqual((bot[0],bot[1],bot[2],bot[3]),(top[0],top[1]+28,100.0,28.0))
        bar=[k for k in kids if any(x[0]=='LC_Bar' for x in binds(k))]
        self.assertEqual(len(bar),1)
        self.assertIn(('LC_Bar',comp_id(bar[0],'drawRect'),'rect',2),binds(bar[0]))
        match=[k for k in kids if any(x[0]=='LC_Match' for x in binds(k))]
        self.assertEqual(len(match),1)
        self.assertIn(('LC_Match',comp_id(match[0],'drawText'),'text',None),binds(match[0]))
        # every chart rect within the panel; the match text in the footer FT_OK's own form (camera-proven with
        # posted strings), not label_text's centred one that drew SS__3197's band
        for k in kids:
            base=recs[next(i for i in owned(k) if kind(i)=='objectBase')]
            x,y,w,h=struct.unpack_from('>4f',base,32)
            self.assertTrue(0<=x and x+w<=680 and 0<=y and y+h<=380,(k,x,y,w,h))
        t=recs[next(i for i in owned(match[0]) if kind(i)=='drawText')]
        footer=recs[next(i for i in owned(C.MP.FOOTER_TEXT) if kind(i)=='drawText')]
        self.assertEqual((len(t),u(t,28)),(len(footer),u(footer,28)))
        self.assertEqual(struct.unpack_from('>f',t,len(t)-8)[0],640.0)

    def test_manager_page_ids_are_unique(self):
        """Duplicate local ids froze the camera (B5_4_2, fp-native-ui 8b-3): per object, event (+28) and clip
        (+24) ids share one space; component ids (+24) are unique too; object ids unique page-wide."""
        import struct
        for page in (C.MP.build()[0],):
            recs=[bytes(r.to_bytes()) for r in C.P.N.split(page)]
            u=lambda r,k:struct.unpack_from('>I',r,k)[0]
            objs=[u(r,20) for r in recs if u(r,0)==0x10003]
            self.assertEqual(len(objs),len(set(objs)))
            owner=None;seen={}
            for r in recs:
                tag=u(r,0)
                if tag==0x10003:owner=u(r,20);seen[owner]=({},{})
                elif tag in (0x10004,0x10005):
                    self.assertEqual(u(r,20),owner);ids=seen[owner][1]
                    self.assertNotIn(u(r,24),ids,f'object {owner} component id {u(r,24)}');ids[u(r,24)]=1
                elif tag in (0x10006,0x1000A):                       # events {+24 owner, +28 id}, clips {+20, +24}
                    o2,k=(u(r,24),u(r,28)) if tag==0x10006 else (u(r,20),u(r,24))
                    ids=seen[o2][0]
                    self.assertNotIn(k,ids,f'object {o2} local id {k}');ids[k]=1

    def test_supmanager_opens_and_lists_the_lut_without_exposing_core(self):
        c=self.cam(open_color=False)
        k,_row=c.current_rows(False)['SupManager']
        c.notify('FT_Key',41+k)
        self.assertEqual((c.shown,U.go_text(c)),([],'FT_LIST'))
        names=[c.vars[f'SM_N{k}'][1] or c.vars[f'SM_G{k}'][1] for k in range(6)]
        self.assertIn(P.SUP_NAME,names)
        self.assertNotIn('LOADER.BIN',names)
        self.assertEqual(c.vars['SM_Title'][1],0)
        self.assertEqual(c.vars['SM_Focus'][1],c.vars['SM_Row0'][1])

    def test_absent_ui_file_leaves_lut_service_available(self):
        files=self.files(); files.pop(U.UI_PATH)
        c=Camera(files,self.ar)
        self.assertEqual(U.ui_lines(c),[(0,0,'LOADER.BIN'),(1,0,'LOADER.BIN')])
        self.assertNotIn('FT_Key',c.vars)
        self.assertEqual(c.status()['asset'],0)
        self.assertEqual(c.invoke(5,1),-13)

    def test_missing_private_page_keeps_one_entry_and_native_api(self):
        files=self.files();files.pop('\\fpSup\\UI\\COLOR.BIN')
        c=Camera(files,self.ar)
        self.assertEqual(set(c.current_rows(False)),{'LUT manager','SupManager'})
        c.open_color()
        self.assertEqual(c.shown,[])
        self.assertNotIn('LC_Key',c.vars)
        self.assertEqual(c.status()['asset'],0)
        self.assertEqual(c.invoke(5,1),-13)

    def test_power_off_restores_shared_ui_hook_words(self):
        c=self.cam()
        sites=(0xC056461C,0xC05E5B58,0xC05E61C8,0xC05E61E0)
        expected=[struct.unpack_from('<I',c.img,a-0xc0000000)[0] for a in sites]
        self.assertNotEqual([c.w(a) for a in sites],expected)
        c.power_off_all()
        self.assertEqual([c.w(a) for a in sites],expected)

    def test_exported_ui_and_no_ui_cards_share_autorun_and_lut_payload(self):
        with tempfile.TemporaryDirectory() as td:
            first=P.build(Path(td)/'ui',card=True,debug=True)
            bare=P.build(Path(td)/'bare',card=True,debug=True,ui=False)
            for name in ('AutoRun.txt','fpSup/'+P.SUP_FILE,'fpSup/LUTDATA/ACTIVE.LUT'):
                self.assertEqual((Path(td)/'ui'/name).read_bytes(),(Path(td)/'bare'/name).read_bytes())
            self.assertNotEqual(first['files']['fpSup/LOADER.BIN'],bare['files']['fpSup/LOADER.BIN'])
            self.assertTrue(first['ui_renderer_present'])
            self.assertFalse(bare['ui_renderer_present'])
            self.assertFalse((Path(td)/'bare/fpSup/UI/FPSUP.BIN').exists())
            files=runtime_files(Path(td)/'ui')
            c=Camera(files,files['\\AutoRun.txt'])
            self.assertEqual(c.status()['asset'],0)
            self.assertEqual(c.callsvc('page_count'),2)
            self.assertEqual(U.ui_lines(c),[(0,0,'LOADER.BIN'),(0x100,2,'LOADER.BIN')])

    def test_private_home_and_manager_strings_resolve_and_stay_borrowed_with_lut(self):
        c=self.cam()
        def string_call(site,value):
            return c.call(site,r0=reader,r1=value,thumb=True)[0]
        reader=U.F6.FAKE+0x7400
        pool=U.F6.FAKE+0x7480
        c.mu.mem_write(pool,b'stock-0\0stock-8\0')
        c.put(reader+0x10,16);c.put(reader+0x14,pool)
        heap=bytes(c.mu.mem_read(N.T4.HEAP,N.T4.HEAP_SIZE))
        for name in (P.B.UI_FILE,'SUPMGR.BIN','COLOR.BIN'):
            data=self.data[name]
            header=struct.unpack_from('<17I',data)
            self.assertEqual(header[0],0x53345446)   # actual FT4S data, no shared string layer
            at=heap.find(data[:68]);self.assertGreaterEqual(at,0)
            base=N.T4.HEAP+N.T4.ALIAS+at
            pack_off,strs_off,n_refs,refs_off=header[1],header[3],header[5],header[6]
            for index in (0,n_refs//2,n_refs-1):
                offset,key=struct.unpack_from('<II',data,refs_off+8*index)
                sid=struct.unpack('>I',bytes(c.mu.mem_read(base+pack_off+offset,4)))[0]
                text=base+struct.unpack_from('<I',data,strs_off+4*key)[0]
                self.assertEqual(sid+N.T4.ALIAS,text)
                self.assertTrue(0x40000000<=sid<0x80000000)
                resolved=string_call(0xC05E5B58,sid)
                self.assertEqual(resolved,text)
                self.assertEqual(string_call(0xC05E61C8,text),1)
                self.assertGreater(string_call(0xC05E61E0,text),len(c.cstr(text)))
        self.assertEqual(c.status()['asset'],0)
        self.assertEqual(c.status()['backend'],0)


if __name__=='__main__': unittest.main()
