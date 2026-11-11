"""Actual ARM library UI and own-BIN persistence; ROM file calls are stubs.

The added F_SEEK stub has the same bounded effect as res-custom's harness.
This does not establish SD atomicity, native UI rendering or live monitoring.
Every LUT is a .cube in \\fpSup\\LUT\\ (2026-11-06): a library's records reach the
camera as build_sup writes them -- the files and their pre-filled records.
"""
from pathlib import Path
import copy
import struct
import tempfile
import unittest
from unittest.mock import patch

import build_sup as P
import jft
import library as L
import cube_metadata as CM
import test_sup_ui as U
from test_lut import make_cube
from cube import Cube
from monitor import Monitor
import numpy as np

BIN='\\fpSup\\'+P.SUP_FILE
SEEK=0xC03661E0
MUTANT_SOURCE=None


JFIT='\\fpSup\\LUTDATA\\'                       # the sup's .JFT files (2026-11-06: not in the user's LUT folder)
FOLDER='\\fpSup\\LUT\\'


def folder_entries(files,folder=FOLDER):
    """The dir API's listing of `folder` (test_v3's model: name, attribute, size): its files, and a
    sub-folder entry (attribute 0x10) for each sub-folder that holds any (an older card's SOURCES, JFIT, DATA)."""
    out,subs=[],[]
    for p,d in files.items():
        if not p.startswith(folder):continue
        rest=p[len(folder):]
        if '\\' in rest:
            sub=rest.split('\\')[0]
            if sub not in subs:subs.append(sub);out.append((sub,0x10,0))
        else:out.append((rest,0x20,len(d)))
    return out


def with_library(files,doc):
    """`files` with the folder holding just `doc`'s cubes and LUT.BIN carrying its records."""
    out={p:d for p,d in files.items() if not p.startswith(FOLDER)}
    out[BIN],_facts=P.build_sup(MUTANT_SOURCE or P.SOURCE,collection=doc)   # (a mutant's too: mutation runs)
    for name,data in L.assets(doc).items():out['\\'+name.replace('/','\\')]=data
    return out


class Camera(U.Camera):
    def __init__(self,files,autorun):
        self.seek_ok=True;self.write_ok=True;self.corrupt_write=False;self.bin_writes=0;self.bin_open_writes=0
        self.cube_write_ok=True;self.cube_corrupt_write=False;self.cube_writes=0;self.go_requests=[]
        super().__init__(dict(files),autorun)

    def page_entries(self):
        """The card's \\fpSup\\LUT\\ as the dir API lists it now (again after a test changes the files)."""
        super().page_entries()
        self.dirs[FOLDER[:-1]]=folder_entries(self.files)

    # The stock list models (modelCSV) the core rewrites for the author's star
    # (color_ui.c model_texts), as Python: a resource per pack model, its rows the
    # pack's CSV, the interface table with modelCSV's wrappers, cell writes kept.
    RES_FIND,RES_COUNT,RES_LOAD,RES_GET,MODEL_IFACE,NOTIFY=0xC05E0320,0xC05D8BD8,0xC05D8B78,0xC05D8BF8,0xC05D8358,0xC05D83A8
    W_ROWS,W_CURRENT,W_STRING,W_INSERT,W_DELETE=0xC05F4860,0xC05F4878,0xC05F4928,0xC05F4940,0xC05F4958
    MODELS=U.U.F6.FAKE+0xE000          # per model k: resource +0x10k, instance +0x400+0x10k; interface +0x800

    def model(self,name):
        """The model's rows (cells), as the pack has them until the core writes a cell."""
        if not hasattr(self,'csv_rows'):
            self.csv_rows={n:[line.split(',') for line in csv.decode('utf-8-sig').split('\r\n')[1:-1]]
                         for n,csv in self.csv_models.items()}
            self.csv_row_names=sorted(self.csv_rows);self.csv_row_cur={};self.model_notified=[]
            iface=self.MODELS+0x800
            for slot,w in ((0x14,self.W_ROWS),(0x18,self.W_CURRENT),(0x30,self.W_STRING),(0x34,self.W_INSERT),(0x38,self.W_DELETE)):
                self.put(iface+slot,w|1)
        return self.csv_rows[name]

    def texts(self,name):return [row[1] for row in self.model(name)]

    def _model_hook(self,addr,r0,r1,r2):
        if addr==self.RES_FIND:
            name=self.cstr(r1);self.model(next(iter(self.csv_models)))
            if name not in self.csv_rows:return self._ret(1)
            self.put(r2,self.MODELS+0x10*self.csv_row_names.index(name));return self._ret(0)
        if addr==self.RES_COUNT:self.put(r1,1);return self._ret(0)
        if addr==self.RES_LOAD:return self._ret(0)
        if addr==self.RES_GET:self.put(r1,r0+0x400);return self._ret(0)
        if addr==self.MODEL_IFACE:self.put(r1,self.MODELS+0x800);return self._ret(0)
        name=lambda inst:self.csv_row_names[(inst-self.MODELS-0x400)//0x10]
        if addr==self.W_ROWS:self.put(r1,len(self.csv_rows[name(r0)]));return self._ret(0)
        if addr==self.W_CURRENT:self.csv_row_cur[r0]=r1;return self._ret(0)
        if addr==self.W_STRING:
            self.csv_rows[name(r0)][self.csv_row_cur[r0]][r1]=self.cstr(r2,128);return self._ret(0)
        if addr==self.NOTIFY:self.model_notified.append(name(r0));return self._ret(0)
        if addr in (self.W_INSERT,self.W_DELETE):raise AssertionError('the star never adds or removes rows')
        return None

    def _hook(self,mu,addr,size,data):
        r0,r1,r2,r3=(self.r(r) for r in (U.N.T3.UC_ARM_REG_R0,U.N.T3.UC_ARM_REG_R1,U.N.T3.UC_ARM_REG_R2,U.N.T4.UC_ARM_REG_R3))
        # conv.c's GUI calls (test_conv_native records them): the GUI function object, its v1 (an app
        # state onto the GUI queue), the ms clock -- the firmware's own would read RAM this image lacks
        if addr==0xC054DD38:return self._ret(0xC3786188)
        if addr==0xC055D470:self.app_states=getattr(self,'app_states',[])+[self.cstr(r1)];return self._ret(1)
        if addr==0xC002B920:self.ms=getattr(self,'ms',0)+50;return self._ret(self.ms)
        if addr==0xC01F8ED4:return self._ret(0)   # tk_wup_tsk: the worker woken (test_conv_native runs it)
        if addr in (self.RES_FIND,self.RES_COUNT,self.RES_LOAD,self.RES_GET,self.MODEL_IFACE,self.NOTIFY,
                    self.W_ROWS,self.W_CURRENT,self.W_STRING,self.W_INSERT,self.W_DELETE):
            return self._model_hook(addr,r0,r1,r2)
        if addr==SEEK:
            assert r2==0
            if not self.seek_ok:return self._ret(0)
            self.fobj[r0][1]=r1;return self._ret(1)
        if addr==U.N.T3.F['F_OPEN'] and r2==7 and (self.cstr(r1)==BIN or self.cstr(r1).endswith('.cube')):
            path=self.cstr(r1)
            if path not in self.files and path not in self.written:return self._ret(0)
            if path==BIN:self.bin_open_writes+=1
            self.written.setdefault(path,self.files.get(path,b''));self.fobj[r0]=[path,0]
            return self._ret(1)
        if addr==U.N.T3.F['F_WRITE'] and self.fobj.get(r0) and (self.fobj[r0][0]==BIN or self.fobj[r0][0].endswith('.cube')):
            source=self.fobj[r0][0]!=BIN
            if source:self.cube_writes+=1
            else:self.bin_writes+=1
            if not (self.cube_write_ok if source else self.write_ok):return self._ret(0)
            assert r2<=4096
            path,pos=self.fobj[r0];blob=bytearray(mu.mem_read(r1,r2))
            if source:assert r2==CM.SIZE and pos==0
            if self.cube_corrupt_write if source else self.corrupt_write:blob[-1]^=1
            old=self.written[path];self.written[path]=old[:pos]+bytes(blob)+old[pos+r2:]
            self.fobj[r0][1]+=r2;return self._ret(1)
        # made again at each open from the record as it is then (the AEL title reads it before the settings)
        if addr==U.N.T3.F['F_OPEN'] and self.auto_jft and self.cstr(r1).startswith(JFIT) and self.cstr(r1).endswith('.JFT') and \
                (self.cstr(r1) not in self.files or self.cstr(r1) in getattr(self,'synth',set())):
            self.synth=getattr(self,'synth',set())|{self.cstr(r1)};self.files.pop(self.cstr(r1),None)
            self.synth_jft(self.cstr(r1))
        if addr==U.N.T3.F['F_READ'] and self.fobj.get(r0) and self.fobj[r0][0] in self.written:
            path,pos=self.fobj[r0];blob=self.written[path][pos:pos+r2]
            mu.mem_write(r1,blob);self.fobj[r0][1]+=len(blob)
            if r3:self.put(r3,len(blob))
            return self._ret(len(blob))
        return super()._hook(mu,addr,size,data)

    # conv.c (Stage B) lists a cube in COLOR only once converted.  Tests about other things see every cube as
    # converted: opening \\fpSup\\LUTDATA\\<sha>.JFT yields a valid 64-byte header for the record now in
    # memory (64 bytes only: lvb_jft still falls back to the camera fit, as before Stage A).  auto_jft = False
    # for the tests of the files themselves.
    auto_jft=True
    no_jft=frozenset()                   # cube names left without one (without_jft)
    JFT_SCORE=63                         # dE x 100 -> 94 %

    def synth_jft(self,path):
        blob=self.files[BIN]
        if getattr(self,'_lut_block',None) is None:
            heap=bytes(self.mu.mem_read(U.N.T4.HEAP,U.N.T4.HEAP_SIZE));at=heap.find(blob[:48+56])   # header + cfg: the code holds state words (color_ctx_at)
            self._lut_block=U.N.T4.HEAP+at if at>=0 else 0
        if not self._lut_block:return
        lib=self._lut_block+struct.unpack_from('<I',blob,48+28)[0]
        count=struct.unpack_from('<I',bytes(self.mu.mem_read(lib,64)),16)[0]
        for i in range(min(count,32)):
            r=bytes(self.mu.mem_read(lib+64+256*i,256))
            if '\\'+jft.path_for(r[:32].hex()).replace('/','\\')==path:   # lvb_jpath's name (11-10: size + name for CAM1)
                if r[32:96].split(b'\0')[0].decode() in self.no_jft:return
                flags,color,gamma,amount=struct.unpack_from('<4I',r,96);matrix=struct.unpack_from('<I',r,128)[0]
                self.files[path]=struct.pack('<4I8s5I3I2I',0x3154464A,1,64,64+jft.PAYLOAD,r[:8],color,gamma,amount,matrix,jft.JFIT_VERSION,
                                             self.JFT_SCORE,self.JFT_SCORE,self.JFT_SCORE,0,0)
                return

    # The settings page has no slots: two stock lists on their own variables
    # (color_ui.SETTINGS_VARS).  These read them the way the slot helpers do.
    SETTINGS={'Color space':('LC_SpaceV','LC_SpaceT',None),'Gamma':('LC_GammaV','LC_GammaT','LC_GammaM'),
              'Color matrix':('LC_MatrixV','LC_MatrixT','LC_MatrixM')}

    def in_settings(self):return bool(self.shown) and self.shown[-1][1]=='FT_LUTSET'

    def press(self,key):
        # MENU leaves by the page's native Return (TransColor), not fpui_show
        if key==70 and self.in_settings():self.shown.append((0,'FT_LUTMGR'))
        go=self.vars['LC_Go'][1]
        result=super().press(key)
        # AEL: the core posts LC_Go after the settings page's variables; the
        # manager's change event requests the name in LC_GO___ (the stock
        # transition), and the settings page writes LC_Go = 0 as it enters
        if self.vars['LC_Go'][1]!=go and self.vars['LC_Go'][1]:
            self.go_requests.append(self.cstr(self.go_text()))
            self.shown.append((0,self.go_requests[-1]));self.notify('LC_Go',0)
        return result

    def text_at(self,prefix):
        """Where the core writes a request: COLOR.BIN's fixed text starting `prefix`, in its heap copy."""
        data=self.files['\\fpSup\\UI\\COLOR.BIN']
        heap=bytes(self.mu.mem_read(U.N.T4.HEAP,U.N.T4.HEAP_SIZE))
        at=heap.find(data[:68]);assert at>=0
        texts_off,n=struct.unpack_from('<2I',data,44)
        offs=[struct.unpack_from('<I',data,texts_off+4*k)[0] for k in range(n)]
        return U.N.T4.HEAP+at+next(o for o in offs if data[o:].startswith(prefix))

    def back_text(self):
        """T_BACK: what the settings page's LC_Back change event asks for."""
        return self.cstr(self.text_at(b'LC_BACK_'))

    def go_text(self):
        """Where the core writes the request: COLOR.BIN's fixed text C_GO_TEXT in its heap copy."""
        if not getattr(self,'_go_at',None):
            data=self.files['\\fpSup\\UI\\COLOR.BIN']
            heap=bytes(self.mu.mem_read(U.N.T4.HEAP,U.N.T4.HEAP_SIZE))
            at=heap.find(data[:68]);assert at>=0
            texts_off,n=struct.unpack_from('<2I',data,44)
            offs=[struct.unpack_from('<I',data,texts_off+4*k)[0] for k in range(n)]
            off=next(o for o in offs if data[o:].startswith(b'LC_GO___'))
            self._go_at=U.N.T4.HEAP+at+off
        return self._go_at

    def current_rows(self,private=True):
        if private and self.in_settings():
            return {t:(k,self.setting(t)) for k,t in enumerate(self.SETTINGS)}
        if private:
            return {r['name']:(k,r) for k in range(6) for r in [self.manager_row(k)] if r['Visible']}
        return super().current_rows(private)

    def manager_row(self,k):
        """Slot k of the manager (SupManager's page: LC_N / LC_G white / grey name,
        LC_R the red note, LC_TOn / LC_TOff the stock On / Off)."""
        v=lambda n:self.vars[f'LC_{n}{k}'][1]
        return {'name':v('N').strip() or v('G').strip(),'A':v('R'),'TOn':v('TOn'),'TOff':v('TOff'),
                'Tog':int(bool(v('TOn') or v('TOff'))),'Max':1,'Lock':v('Lock'),'Visible':v('Visible'),
                'Grey':v('GShow')}

    def setting(self,title):
        value,text,cap=self.SETTINGS[title]
        return {'A':self.vars[text][1],'V':self.vars[value][1],'Max':self.vars[cap][1] if cap else 7}

    def find_row(self,title):
        if title in self.SETTINGS and self.in_settings():return 0,self.setting(title)
        if title in self.current_rows():return self.current_rows()[title]
        page=self.vars['LC_PageText'][1].strip()
        current,total=map(int,page.split('/')) if '/' in page else (1,1)
        for _ in range(current-1):self.press(10)
        for _ in range(total):
            if title in self.current_rows():return self.current_rows()[title]
            self.press(11)
        raise AssertionError('manager row unreachable: '+title)

    def choose(self,title,choice):
        if title in self.SETTINGS and self.in_settings():
            return self.notify(self.SETTINGS[title][0],choice)
        k,_row=self.find_row(title)
        return self.notify(f'LC_Choice{k}',0 if choice else 1)     # the stock popup: 0 Enable, 1 Disable

    def jump(self,title):
        k,row=self.find_row(title);assert row['Jump']
        self.press(41+k)

    def manager(self):self.open_color()            # the fpSup row opens the manager itself

    def edit(self,name):                             # AEL on the cube's row: its settings
        self.manager();k,_row=self.find_row(name);self.ael(k)

    def ael(self,k):                                 # the row has focus, AEL on the page's Menu
        self.notify('LC_Focus',self.vars[f'LC_RowId{k}'][1]);self.press(80)

    def saved_files(self):              # the harness's own .JFT stay behind: the next camera makes its own
        return {p:b for p,b in dict(self.files,**self.written).items() if p not in getattr(self,'synth',())}

    def record(self,index):
        """Saved record `index` (LUT.BIN as written, else as it was): its fields by library.layer_fields' names."""
        data=self.written.get(BIN,self.files[BIN]);p=struct.unpack_from('<I',data,76)[0]+64+index*L.RECORD
        flags,color,gamma,amount=struct.unpack_from('<4I',data,p+96)
        m,af,ac,ag,am,uf,uc,ug,um=struct.unpack_from('<9I',data,p+128)
        return dict(sha=data[p:p+32],name=data[p+32:p+96].split(b'\0')[0].decode(),flags=flags,color=color,gamma=gamma,
                    amount=amount,origin=struct.unpack_from('<I',data,p+124)[0],matrix=m,author=(af,ac,ag,am),user=(uf,uc,ug,um))

    def user_value(self,index,bit):
        """The user's layer for one field as saved (None = the author's stands): the index, gammas global."""
        uf,uc,ug,um=self.record(index)['user']
        return None if not uf&bit else {L.SPACE_SET:uc,L.GAMMA_SET:ug,L.MATRIX_SET:um}[bit]


def without_jft(make,*names):
    """A camera with no .JFT for the cubes `names` (none given: for any cube), from its boot on.  2026-11-10 (Bei:
    switching COLOR then MENU was slow): a pick with no area of its own (library_load_index) only selects an entry
    whose .JFT is there -- the tables come from it -- and checks the cube (parse + identity) only without one.
    Why a damaged / changed cube still meets the check on the camera:
      - its .JFT is named and headed by the identity "CAM1" + byte size + the name's fnv (import.c imp_identity,
        lvb.c lvb_jpath, conv.c conv_score: +16 = sha[0..7]); the boot's (and the manager's) imp_scan writes a
        cube's new identity into its entry, so a cube whose size changed has no .JFT and is checked;
      - a malformed or pending cube cannot be converted: conv_inputs loads it through library_load_index with the
        asset area held (the parse path, never the shortcut), and conv_write runs only after that succeeded.
    The harness's .JFT (Camera.auto_jft) are made for whatever the record holds, so these tests take them away."""
    old=Camera.auto_jft,Camera.no_jft
    Camera.auto_jft,Camera.no_jft=bool(names),frozenset(names)
    try:c=make()
    finally:Camera.auto_jft,Camera.no_jft=old
    c.auto_jft,c.no_jft=bool(names),frozenset(names)      # the instance keeps them past the boot
    return c


@unittest.skipIf(U.N.T4.Uc is None or not U.N.T3.IMAGE.exists(),'requires Unicorn and firmware; skipped is unverified')
class LibraryNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        tags=lambda space,gamma:f'# FPSUP_INPUT_COLOR_SPACE {space}\n# FPSUP_INPUT_GAMMA {gamma}\n'.encode()
        paths=[]                          # B.cube: a BOM, its author lines, then > 8 KiB of comments
        for name,space,gamma,scale in [('A.cube','rec709','gamma24',1),('B.cube','p3-d65','gamma26',.7),('Unknown_709.cube',None,None,.8)]:
            path=cls.root/name;path.write_bytes((CM.BOM if name=='B.cube' else b'')+(tags(space,gamma) if space else b'')+
                 (b'# '+b'x'*40+b'\r\n'+b'# notes\r\n'*1100 if name=='B.cube' else b'')+
                 f'TITLE "{name}"\n'.encode()+make_cube(2,fn=lambda r,g,b:(scale*r,scale*g,scale*b)))
            paths.append(path)
        cls.doc=L.import_cubes(L.blank(),paths)
        cls.doc=L.configure(cls.doc,'A.cube',enabled=True,active=True)
        cls.doc=L.configure(cls.doc,'B.cube',enabled=True)
        cls.info=P.build(cls.root/'card',card=True,debug=True,collection=cls.doc)
        cls.files=U.runtime_files(cls.root/'card');cls.ar=cls.files['\\AutoRun.txt']
        if MUTANT_SOURCE:
            cls.files[BIN],facts=P.build_sup(MUTANT_SOURCE,collection=cls.doc)
            cls.info.update(facts)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def cam(self,files=None):
        c=Camera(files or self.files,self.ar);c.open_color();return c

    # The fpSup row opens the manager (user 2026-10-24): every cube with its
    # stock Off / On, AEL for its settings (color space, Gamma).  Which LUT is
    # monitored comes from the native COLOR list, through api.pick (index 8).
    PICK,OFF=8,0xFFFFFFFF

    def pick(self,c,index):return c.invoke(self.PICK,index)

    def test_library_records_carry_the_user_matrix_and_the_author_custom_one(self):
        """The user's layer and the author's matrices ride in the BIN; the cube file is not written."""
        root=self.root/'matrix';root.mkdir(exist_ok=True)
        a=root/'A.cube';a.write_bytes(b'# FPSUP_INPUT_COLOR_SPACE rec709\n# FPSUP_INPUT_GAMMA gamma24\n'+make_cube(2))
        c=root/'C.cube';c.write_bytes(b'# FPSUP_INPUT_COLOR_SPACE p3-d65\n# FPSUP_INPUT_GAMMA gamma26\n'
                                      b'# FPSUP_COLOR_MATRIX2 0.5 -0.1 0 -0.4 1.25 0.2 -0.1 0.2 0.5\n'+make_cube(2,fn=lambda r,g,b:(b,g,r)))
        doc=L.import_cubes(L.blank(),[a,c])
        doc=L.configure(doc,'A.cube',input_space='p3-d65',input_gamma='linear',color_matrix='off',enabled=True)
        doc=L.configure(doc,'C.cube',enabled=True)
        cam=self.cam(with_library(self.files,doc))
        self.assertEqual(self.pick(cam,0),0);self.assertEqual(self.pick(cam,1),0)
        data=cam.written[BIN];off=struct.unpack_from('<I',data,76)[0]
        rec=lambda i:off+64+L.RECORD*i
        self.assertEqual(struct.unpack_from('<3I',data,rec(0)+100),(4,3,100))
        self.assertEqual(struct.unpack_from('<9I',data,rec(0)+128),(1,L.SPACE_SET|L.GAMMA_SET,6,1,0,
                         L.SPACE_SET|L.GAMMA_SET|L.MATRIX_SET,4,3,1))
        layers,cm=L.layer_fields(L.find(doc,'C.cube'))
        self.assertEqual(struct.unpack_from('<9I',data,rec(1)+128),(2,*layers))
        self.assertEqual(list(struct.unpack_from('<18i',data,rec(1)+176)),cm[0]+cm[1])
        self.assertEqual(cam.cube_writes,0)

    STAR=' *'                         # the menu font has no U+2605 (camera 2026-11-03)

    def starred(self,c,name):
        """The rows of model `name` the core marked as the author's."""
        return [i for i,t in enumerate(c.texts(name)) if t.endswith(self.STAR)]

    def test_the_authors_choice_is_starred_in_each_list(self):
        """user 2026-11-03: the author's original choice is marked with a star."""
        from cinemadng import COLOR_SPACES,COMMON_GAMMAS
        c=self.cam();c.edit('B.cube')                            # author: p3-d65 / gamma26, no matrix
        space=list(COLOR_SPACES).index('p3-d65');gamma=list(COMMON_GAMMAS).index('gamma26')
        self.assertEqual(self.starred(c,'LC_SPACE'),[space])
        self.assertEqual(c.texts('LC_SPACE')[space],COLOR_SPACES['p3-d65'].label+self.STAR)
        self.assertEqual(self.starred(c,'LC_GAMMA'),[gamma])
        for name in ('LC_GAMMA_BMD','LC_MATRIX','LC_MATRIX_C'):self.assertEqual(self.starred(c,name),[],name)
        self.assertEqual(set(c.model_notified),{'LC_SPACE','LC_GAMMA','LC_GAMMA_BMD','LC_MATRIX','LC_MATRIX_C'})
        # the user's own choice moves nothing: the star stays the author's
        c.choose('Color space',0);c.press(70);c.edit('B.cube')
        self.assertEqual(self.starred(c,'LC_SPACE'),[space])
        # each cube its own: no author, no star; another author, its rows
        c.press(70);c.edit('Unknown_709.cube')
        for name in ('LC_SPACE','LC_GAMMA'):self.assertEqual(self.starred(c,name),[],name)
        c.press(70);c.edit('A.cube')
        self.assertEqual((self.starred(c,'LC_SPACE'),self.starred(c,'LC_GAMMA')),
                         ([list(COLOR_SPACES).index('rec709')],[list(COMMON_GAMMAS).index('gamma24')]))
        self.assertEqual(c.vars['LC_Back'][1]>0,True)

    def matrix_cam(self):
        root=self.root/'matrix_row';root.mkdir(exist_ok=True)
        m=root/'M.cube';m.write_bytes(b'# FPSUP_INPUT_COLOR_SPACE rec709\n# FPSUP_INPUT_GAMMA gamma24\n# FPSUP_COLOR_MATRIX custom\n'
                                      b'# FPSUP_COLOR_MATRIX2 0.5 -0.1 0 -0.4 1.25 0.2 -0.1 0.2 0.5\n'+make_cube(2,fn=lambda r,g,b:(g,b,r)))
        o=root/'O.cube';o.write_bytes(b'# FPSUP_INPUT_COLOR_SPACE rec709\n# FPSUP_INPUT_GAMMA gamma24\n# FPSUP_COLOR_MATRIX off\n'+make_cube(2))
        doc=L.import_cubes(L.blank(),[m,o])
        return self.cam(with_library(self.files,doc))

    def user_matrix(self,c,index):
        """The user's layer for the matrix, as the camera saved it in LUT.BIN (None = the author's)."""
        m=c.user_value(index,L.MATRIX_SET);return None if m is None else L.MATRICES[m]

    def test_the_matrix_row_lists_custom_only_with_the_authors_matrices(self):
        c=self.matrix_cam();c.edit('O.cube')                     # author: off, no matrices
        self.assertEqual((c.vars['LC_MatrixX'][1],c.vars['LC_MatrixM'][1]),(0,1))
        self.assertEqual((c.vars['LC_MatrixV'][1],c.vars['LC_MatrixT'][1]),(1,'OFF'))
        self.assertEqual(self.starred(c,'LC_MATRIX'),[1])
        c.press(70);c.edit('M.cube')                              # author: custom with ColorMatrix2
        self.assertEqual((c.vars['LC_MatrixX'][1],c.vars['LC_MatrixM'][1]),(1,2))
        self.assertEqual((c.vars['LC_MatrixV'][1],c.vars['LC_MatrixT'][1]),(2,'Custom'))
        self.assertEqual(self.starred(c,'LC_MATRIX_C'),[2])

    def test_the_matrix_row_writes_the_users_layer_and_refuses_custom_without_matrices(self):
        c=self.matrix_cam();c.edit('O.cube');o=c.vars['LC_PageTitle'][1].split('  ')[0]=='O.cube' and 1
        self.assertIsNone(self.user_matrix(c,o))
        c.choose('Color matrix',0)                                # Standard: the user's override
        self.assertEqual((self.user_matrix(c,o),c.vars['LC_MatrixT'][1]),('standard','Standard'))
        c.choose('Color matrix',2)                                # Custom: this author has no matrices
        self.assertEqual(self.user_matrix(c,o),'standard')
        self.assertEqual((c.vars['LC_MatrixV'][1],c.vars['LC_MatrixT'][1]),(0,'Standard'))   # repainted
        c.choose('Color matrix',1)                                # the author's own: no override left
        self.assertEqual((self.user_matrix(c,o),c.vars['LC_MatrixT'][1]),(None,'OFF'))
        self.assertEqual(self.starred(c,'LC_MATRIX'),[1])

    def test_manager_lists_every_cube_with_stock_on_off(self):
        c=self.cam()
        self.assertEqual(set(c.current_rows(False)),{'LUT manager','SupManager'})
        self.assertEqual(set(c.current_rows()),{'A.cube','B.cube','Unknown_709.cube'})
        for name,on in (('A.cube',1),('B.cube',1)):
            row=c.find_row(name)[1]
            self.assertEqual((row['A'],row['Tog'],row['TOn'],row['TOff'],row['Max'],row['Lock']),(' ',1,on,1-on,1,0))
        row=c.find_row('Unknown_709.cube')[1]       # Off, and SupManager's red note
        self.assertEqual((row['A'],row['TOff'],row['Lock']),('Setup required',1,0))
        self.assertEqual(c.vars['LC_Header'][1],'LUT (2/12)')     # COL-Share's room (Bei 11-10: 12 rows)
        self.assertEqual(c.vars['LC_OK'][1],U.C.F.SUPMGR_TEXTS[5])       # SupManager's fixed footer
        self.assertEqual(c.vars['LC_RightFooter'][1],U.C.AEL_HINT)
        self.assertEqual(c.status()['asset'],0)
        self.assertEqual(c.misaligned,[])

    def test_a_record_saved_under_the_old_matrix_rule_still_loads(self):
        """camera 11-05: v12 made "no author matrix" Off (was Standard); a LUT.BIN the camera saved before still says
        Standard there.  The load resolves the layers again instead of refusing the library (an empty manager)."""
        blob=bytearray(self.files[BIN]);off=struct.unpack_from('<I',blob,48+28)[0]
        count=struct.unpack_from('<I',blob,off+16)[0];stale=0
        for i in range(count):
            p=off+L.HEADER+L.RECORD*i
            af,uf=struct.unpack_from('<I',blob,p+132)[0],struct.unpack_from('<I',blob,p+148)[0]
            if not (af|uf)&L.MATRIX_SET and struct.unpack_from('<I',blob,p+128)[0]==1:
                struct.pack_into('<I',blob,p+128,0);stale+=1         # the old rule's effective value: standard
        self.assertGreater(stale,0)
        struct.pack_into('<I',blob,off+24,L.checksum(blob[off:off+L.HEADER+L.RECORD*count]))
        files=dict(self.files);files[BIN]=bytes(blob)
        c=self.cam(files)
        self.assertEqual(set(c.current_rows()),{'A.cube','B.cube','Unknown_709.cube'})
        c.edit('B.cube')
        self.assertEqual((c.vars['LC_MatrixV'][1],c.vars['LC_MatrixT'][1]),(1,'OFF'))

    def test_ael_is_on_the_system_key_object_and_needs_a_focused_row(self):
        page,_r,_f,slots=U.C.MP.build()
        recs=[bytearray(r.to_bytes()) for r in U.C.P.N.split(page)]
        pg=U.C.M.Management(*U.C.P.stock_pool())
        ael=[r for r in recs if U.C.P.u32(r,0)==0x10006 and len(r)>=40 and pg.pool.text(U.C.P.u32(r,20))=='AEL']
        self.assertEqual([(U.C.P.u32(r,24),len(r),U.C.P.u32(r,40)) for r in ael],[(U.C.MP.SYSKEY_OBJECT,44,0x13)])
        self.assertEqual(len(set(slots)),6)
        first=self.cam();first.press(80)    # AEL right after entering: the core's own first focus
        self.assertRegex(first.vars['LC_PageTitle'][1],r'^A\.cube(  \d+% match)?$')   # + the match when its .JFT is there
        c=self.cam();c.notify('LC_Focus',12345);c.press(80)        # no row focused: nothing opens
        self.assertEqual(set(c.current_rows()),{'A.cube','B.cube','Unknown_709.cube'})

    def test_ael_opens_by_the_stock_transition_and_menu_returns_to_that_cube(self):
        c=self.cam();shown=len(c.shown);c.edit('B.cube')
        self.assertEqual(c.go_requests,['FT_LUTSET'])             # LC_Go's change event, not fpui_show
        self.assertEqual([p for _a,p in c.shown[shown:]],['FT_LUTSET'])
        self.assertEqual(c.cstr(c.go_text()),'')                  # LC_Go = 0 on entering: nothing left to ask
        self.assertEqual(c.vars['LC_Focus'][1],c.vars['LC_SRow0'][1])
        c.press(70)
        self.assertEqual(c.vars['LC_Focus'][1],c.vars['LC_RowId1'][1])   # B.cube's row, not the title

    def test_moving_focus_reposts_nothing_of_the_rows(self):
        # the lag: the earlier page posted every slot's words on each focus move
        c=self.cam();before=len(c.posts)
        for v in (c.vars['LC_RowId1'][1],c.vars['LC_RowId2'][1],c.vars['LC_RowId0'][1]):c.notify('LC_Focus',v)
        self.assertEqual([n for n,_v in c.posts[before:] if n not in ('LC_Focus',)],[])

    def test_cap_is_col_shares_room_and_setup_first(self):
        """Bei 2026-11-10: as many on as COL-Share has rows for us (12, nothing else on the card)."""
        doc=L.blank();paths=[]
        for i in range(14):
            path=self.root/f'Cap{i}.cube';path.write_bytes(f'TITLE "Cap{i}"\n'.encode()+make_cube(2));paths.append(path)
        doc=L.import_cubes(doc,paths,input_space='rec709',input_gamma='gamma24')
        for i in range(11):doc=L.configure(doc,f'Cap{i}.cube',enabled=True)
        c=self.cam(with_library(self.files,doc))
        c.choose('Cap11.cube',1)
        self.assertEqual(c.vars['LC_Header'][1],'LUT (12/12)')
        c.choose('Cap12.cube',1)                       # the thirteenth: refused, as RES-Custom's list full
        self.assertEqual(c.find_row('Cap12.cube')[1]['TOn'],0)
        self.assertEqual(c.vars['LC_OK'][1],'List full: disable one')
        c.choose('Cap0.cube',0);c.choose('Cap12.cube',1)
        self.assertEqual((c.find_row('Cap12.cube')[1]['TOn'],c.vars['LC_Header'][1]),(1,'LUT (12/12)'))
        u=self.cam();u.choose('Unknown_709.cube',1)  # not set up: refused, the footer says how
        self.assertEqual((u.find_row('Unknown_709.cube')[1]['TOn'],u.vars['LC_OK'][1]),(0,'Set up first: AEL'))

    def test_ael_opens_two_settings_rows_and_menu_returns_to_the_manager(self):
        c=self.cam();c.edit('B.cube')
        self.assertRegex(c.vars['LC_PageTitle'][1],r'^B\.cube(  \d+% match)?$')   # + the match when its .JFT is there
        self.assertEqual(set(c.current_rows()),{'Color space','Gamma','Color matrix'})
        self.assertEqual(c.vars['LC_RightFooter'][1],' ')
        space=c.find_row('Color space')[1];gamma=c.find_row('Gamma')[1]
        self.assertEqual((space['A'],space['Max'],gamma['A'],gamma['Max']),('P3 D65',7,'Gamma 2.6',5))
        back=c.vars['LC_Back'][1]
        self.assertEqual(c.back_text(),'')        # the event's first run, as the page is built: no request
        c.press(70)
        self.assertEqual(c.back_text(),'Return')
        c.edit('A.cube')                           # a second visit: its first run must not leave again
        self.assertEqual(c.back_text(),'')
        c.press(70)
        self.assertEqual(set(c.current_rows()),{'A.cube','B.cube','Unknown_709.cube'})
        # the page's Return waits for LC_Back, posted after the manager's focus (diagK3)
        self.assertNotEqual(c.vars['LC_Back'][1],back)

    def test_lists_are_own_csv_models_and_gamma_follows_blackmagic(self):
        c=self.cam()
        self.assertEqual(set(c.csv_models),{'LC_SPACE','LC_GAMMA','LC_GAMMA_BMD','LC_MATRIX','LC_MATRIX_C'})
        rows=lambda n:c.csv_models[n].decode('utf-8-sig').split('\r\n')[1:-1]
        self.assertEqual([r.split(',')[1] for r in rows('LC_SPACE')],[v.label for v in P.COLOR_SPACES.values()])
        self.assertEqual(len(rows('LC_GAMMA')),6);self.assertEqual(len(rows('LC_GAMMA_BMD')),2)
        self.assertTrue(all(c.csv_models[n].endswith(b'\r\n') for n in c.csv_models))
        c.edit('B.cube')
        self.assertEqual((c.vars['LC_GammaX'][1],c.vars['LC_GammaM'][1]),(0,5))
        c.choose('Color space',2)
        self.assertEqual((c.vars['LC_GammaX'][1],c.vars['LC_GammaM'][1]),(1,1))
        self.assertEqual(c.vars['LC_Focus'][1],c.vars['LC_SRow0'][1])

    def test_every_color_space_and_its_gammas_by_index(self):
        c=self.cam();c.edit('B.cube')
        for ci,space in enumerate(P.COLOR_SPACES):
            c.choose('Color space',ci)
            self.assertEqual(c.find_row('Color space')[1]['A'],P.COLOR_SPACES[space].label)
            names=P.BLACKMAGIC_GAMMAS if ci==2 else P.COMMON_GAMMAS
            self.assertEqual(c.find_row('Gamma')[1]['Max'],len(names)-1)
            for gi,gamma in enumerate(names):
                c.choose('Gamma',gi)
                self.assertEqual(c.find_row('Gamma')[1]['A'],P.GAMMAS[gamma].label)
        r=c.record(1);spaces=list(P.COLOR_SPACES)
        self.assertEqual(r['user'][:3],(L.SPACE_SET|L.GAMMA_SET,spaces.index('srgb'),L.GAMMAS_ALL.index('srgb')))
        self.assertEqual(r['author'][:3],(L.SPACE_SET|L.GAMMA_SET,spaces.index('p3-d65'),L.GAMMAS_ALL.index('gamma26')))
        self.assertEqual((c.cube_writes,c.written.get(FOLDER+'B.cube',c.files[FOLDER+'B.cube'])),
                         (0,self.files[FOLDER+'B.cube']))       # the designer's file is never rewritten

    def test_editing_one_cube_does_not_change_other_or_current_active(self):
        c=self.cam();c.edit('B.cube');c.choose('Color space',1);c.choose('Gamma',3)
        self.assertEqual((c.status()['color'],c.status()['gamma']),(6,1))      # A stays monitored
        c.press(70);c.edit('A.cube')
        self.assertEqual((c.find_row('Color space')[1]['A'],c.find_row('Gamma')[1]['A']),('Rec.709','Gamma 2.4'))
        c.press(70);c.edit('B.cube')
        self.assertEqual((c.find_row('Color space')[1]['A'],c.find_row('Gamma')[1]['A']),('Adobe RGB','Linear'))

    def test_pick_restores_cube_settings_and_uses_its_original_nodes(self):
        c=self.cam();self.assertEqual(self.pick(c,1),0)
        self.assertEqual((c.status()['color'],c.status()['gamma']),(4,2))
        xyz=np.array([[.1,.2,.3],[.18,.18,.18]])
        rc,actual=c.render(xyz)
        expected,_=Monitor(Cube.read(self.root/'B.cube'),'p3-d65',input_gamma='gamma26').evaluate_xyz(xyz)
        self.assertEqual(rc,0);np.testing.assert_allclose(actual,expected,atol=4e-5,rtol=0)
        self.assertEqual(self.pick(c,0),0)
        self.assertEqual((c.status()['color'],c.status()['gamma']),(6,1))

    def test_unmarked_cube_needs_both_settings_before_it_can_be_on_or_picked(self):
        c=self.cam()
        self.assertEqual(self.pick(c,2),-12)          # even a forged pick is refused
        c.edit('Unknown_709.cube')
        self.assertEqual((c.find_row('Color space')[1]['A'],c.find_row('Gamma')[1]['A']),('Setup required','Setup required'))
        c.choose('Color space',6)
        self.assertEqual(c.find_row('Gamma')[1]['A'],'Setup required')
        c.choose('Gamma',1);c.press(70)
        row=c.find_row('Unknown_709.cube')[1]
        self.assertEqual((row['A'],row['Tog'],row['TOff']),(' ',1,1))
        c.choose('Unknown_709.cube',1)
        self.assertEqual(c.find_row('Unknown_709.cube')[1]['TOn'],1)
        self.assertEqual(self.pick(c,2),0)

    def test_turning_the_active_cube_off_saves_off_and_stays_off_after_reload(self):
        c=self.cam();c.choose('A.cube',0);c.choose('B.cube',0)
        self.assertEqual(c.render([[.1,.2,.3]])[0],-15)
        self.assertEqual(self.pick(c,1),-12)
        again=self.cam(c.saved_files())
        self.assertEqual(again.render([[.1,.2,.3]])[0],-15)
        self.assertEqual({again.find_row(n)[1]['TOff'] for n in ('A.cube','B.cube')},{1})

    def test_active_input_becoming_incomplete_saves_off_and_reloads_validly(self):
        c=self.cam();c.edit('A.cube');c.choose('Color space',2)
        self.assertEqual(c.find_row('Gamma')[1]['A'],'Setup required')
        self.assertEqual(c.status()['asset'],-15)
        self.assertEqual((c.user_value(0,L.SPACE_SET),c.user_value(0,L.GAMMA_SET)),(2,None))   # blackmagic-design, unset
        self.assertEqual(c.record(0)['author'][2],L.GAMMAS_ALL.index('gamma24'))   # kept; it does not fit Blackmagic
        again=without_jft(lambda:self.cam(c.saved_files()),'A.cube')   # Blackmagic: never converted
        self.assertEqual(again.status()['asset'],-15)
        again.edit('A.cube');self.assertEqual(again.find_row('Color space')[1]['A'],'Blackmagic Design')
        again.choose('Gamma',0)
        # a pending model (Blackmagic) is refused as the cube is parsed (import.c: the asset's own check), no
        # longer loaded and refused at render as a computer-prepared asset was (-12 then)
        self.assertEqual(self.pick(again,0),-11)
        self.assertEqual(again.render([[.1,.2,.3]])[0],-15)

    def test_pick_saves_across_boot_with_no_source_cube_write(self):
        c=self.cam();self.assertEqual(self.pick(c,1),0)
        again=self.cam(c.saved_files())
        self.assertEqual((again.status()['color'],again.status()['gamma']),(4,2))
        self.assertEqual({p for p in c.written if p!= '\\fpSup\\LOAD.LOG'},{BIN})
        self.assertEqual(len(c.written[BIN]),len(self.files[BIN]))
        recovered=L.recover(self.doc,c.written[BIN])
        self.assertEqual(recovered['active'],self.doc['luts'][1]['id'])

    def test_missing_or_replaced_bin_is_not_created_or_overwritten(self):
        for missing in (True,False):
            with self.subTest(missing=missing):
                c=self.cam()
                if missing:c.files.pop(BIN)
                else:
                    blob=bytearray(c.files[BIN]);blob[self.info['library_offset']+32]^=1;c.files[BIN]=bytes(blob)
                c.choose('B.cube',0)
                self.assertEqual(c.status()['last'],-16)
                self.assertEqual(c.bin_open_writes,0)
                self.assertEqual(c.find_row('B.cube')[1]['TOn'],1)

    def test_readback_failure_rolls_back_ram_and_does_not_replay(self):
        c=self.cam();c.corrupt_write=True;c.choose('B.cube',0)
        self.assertEqual(c.status()['last'],-16);self.assertEqual(c.find_row('B.cube')[1]['TOn'],1)
        writes=c.bin_writes
        c.choose('B.cube',0)
        self.assertEqual(c.bin_writes,writes)
        again=self.cam(c.saved_files())
        self.assertEqual(again.status()['asset'],-11)

    def test_recording_blocks_file_loads_and_settings_writes(self):
        c=self.cam();c.mu.mem_write(0xC347E08F,b'\1')
        opened=len(c.opened);c.choose('B.cube',0)
        self.assertEqual(c.status()['last'],-17);self.assertEqual(c.bin_writes,0)
        c.edit('B.cube');c.choose('Color space',0)
        self.assertEqual(c.status()['last'],-17);self.assertEqual(c.cube_writes,0)
        self.assertEqual(self.pick(c,1),-17);self.assertEqual(len(c.opened),opened)

    def test_a_damaged_cube_does_not_replace_selected_lut(self):
        files=dict(self.files);files[FOLDER+'B.cube']=files[FOLDER+'B.cube'][:-12]   # its last row short
        c=without_jft(lambda:self.cam(files),'B.cube')                           # (its size changed: no .JFT)
        self.assertEqual(self.pick(c,1),-11)
        self.assertEqual((c.status()['color'],c.status()['gamma'],c.status()['asset']),(6,1,0))

    def test_full_library_last_page_and_chunked_write_are_reachable(self):
        doc=L.blank()
        paths=[]
        for i in range(L.MAX_LUTS):
            path=self.root/f'Look{i:02}.cube';path.write_bytes(f'TITLE "Look{i}"\n'.encode()+make_cube(2));paths.append(path)
        doc=L.import_cubes(doc,paths,input_space='p3-d65',input_gamma='gamma26')
        for e in doc['luts']:e['enabled']=True
        c=self.cam(with_library(self.files,doc))
        k,row=c.find_row('Look31.cube')
        self.assertEqual(c.vars['LC_PageText'][1],'7 / 7')
        c.choose('Look31.cube',0)
        self.assertEqual(c.bin_writes,3)  # 8256-byte record (v3) crosses two 4096-byte DMA chunks
        recovered=L.recover(doc,c.written[BIN])
        self.assertTrue(recovered['luts'][30]['enabled'])
        self.assertFalse(recovered['luts'][31]['enabled'])
        c.ael(k);self.assertRegex(c.vars['LC_PageTitle'][1],r'^Look31\.cube(  \d+% match)?$')   # + the match when its .JFT is there
        c.press(70);self.assertEqual(c.vars['LC_PageText'][1],'7 / 7')
        self.assertEqual(self.pick(c,30),0)     # the last page's cube, from its file
        self.assertEqual(c.status()['asset'],0)

    def test_input_choice_is_saved_in_the_bin_and_the_cube_is_untouched(self):
        """2026-11-06: the cube is the user's file; every setting lives in LUT.BIN."""
        c=self.cam();before=c.files[FOLDER+'B.cube']
        c.edit('B.cube');c.choose('Color space',1);c.choose('Gamma',3)
        self.assertEqual((c.cube_writes,FOLDER+'B.cube' in c.written,c.files[FOLDER+'B.cube']),(0,False,before))
        self.assertGreater(c.bin_writes,0)
        self.assertEqual((c.user_value(1,L.SPACE_SET),c.user_value(1,L.GAMMA_SET)),(1,3))   # adobe-rgb, linear
        again=self.cam(c.saved_files());again.edit('B.cube')
        self.assertEqual(again.find_row('Color space')[1]['A'],'Adobe RGB')
        self.assertEqual(again.find_row('Gamma')[1]['A'],'Linear')


if __name__=='__main__':unittest.main()
