"""Library identity, explicit inputs, author defaults and user overrides."""
from pathlib import Path
import json
import struct
import tempfile
import unittest

from cube import Cube
import library as L
import cube_metadata as CM
from test_lut import make_cube


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def cube(self,name='A.cube',comments=b'',title='A'):
        path=self.root/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(comments+f'TITLE "{title}"\n'.encode()+make_cube(2))
        return path

    def test_filename_is_label_not_inferred_input(self):
        path=self.cube('Portrait_Rec709_G24.cube')
        doc=L.import_cubes(L.blank(),[path])
        self.assertEqual(doc['luts'][0]['filename'],path.name)
        self.assertFalse(L.resolved(doc['luts'][0])['configured'])
        self.assertFalse(doc['luts'][0]['enabled'])
        with self.assertRaises(ValueError):L.configure(doc,path.name,enabled=True,active=True)

    def test_author_comments_survive_normal_cube_parser_and_prefill(self):
        tags=b'# FPSUP_INPUT_COLOR_SPACE p3-d65\n# FPSUP_INPUT_GAMMA gamma26\n# FPSUP_OUTPUT_COLOR_SPACE rec709\n# FPSUP_OUTPUT_GAMMA gamma24\n'
        path=self.cube(comments=tags)
        before=path.read_bytes();doc=L.import_cubes(L.blank(),[path])
        self.assertEqual(L.resolved(doc['luts'][0])['input_space'],'p3-d65')
        self.assertEqual(L.resolved(doc['luts'][0])['input_gamma'],'gamma26')
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(Cube.read(path).table3d.shape,(2,2,2,3))

    def test_unrelated_comment_quotes_are_not_metadata(self):
        path=self.cube(comments=b'# This author\'s "unfinished sentence is just a comment\n')
        self.assertEqual(L.author_settings(Cube.read(path)),{})

    def test_author_invalid_conflicting_or_non709_output_is_rejected(self):
        for tags in (b'# FPSUP_INPUT_GAMMA nonsense\n',
                     b'# FPSUP_INPUT_GAMMA gamma24\n# FPSUP_INPUT_GAMMA gamma26\n',
                     b'# FPSUP_INPUT_COLOR_SPACE blackmagic-design\n# FPSUP_INPUT_GAMMA gamma24\n',
                     b'# FPSUP_OUTPUT_COLOR_SPACE p3-d65\n',b'# FPSUP_OUTPUT_GAMMA srgb\n'):
            with self.subTest(tags=tags),self.assertRaises(ValueError):
                L.import_cubes(L.blank(),[self.cube(comments=tags)])

    def test_user_overrides_are_per_cube_and_preserved_on_rename(self):
        a=self.cube('A.cube',b'# FPSUP_INPUT_COLOR_SPACE p3-d65\n# FPSUP_INPUT_GAMMA gamma26\n')
        b=self.cube('B.cube',title='B')
        doc=L.import_cubes(L.blank(),[a,b])
        doc=L.configure(doc,'A.cube',input_space='aces',input_gamma='linear',strength_percent=25,enabled=True,active=True)
        moved=a.with_name('Renamed.cube');a.rename(moved)
        doc=L.import_cubes(doc,[moved])
        self.assertEqual(len(doc['luts']),2)
        item=L.find(doc,'Renamed.cube')
        self.assertEqual(L.resolved(item)['input_space'],'aces')
        self.assertEqual(L.resolved(item)['strength_percent'],25)
        self.assertEqual(doc['active'],item['id'])
        self.assertFalse(L.resolved(L.find(doc,'B.cube'))['configured'])

    def test_same_filename_different_contents_is_not_a_shared_setting(self):
        a=self.cube('one/Look.cube',title='A');b=self.cube('two/Look.cube',title='B')
        doc=L.import_cubes(L.blank(),[a,b],input_space='rec709',input_gamma='gamma24')
        with self.assertRaises(ValueError):L.find(doc,'Look.cube')
        doc=L.configure(doc,doc['luts'][0]['id'],strength_percent=25)
        self.assertEqual(L.resolved(doc['luts'][1])['strength_percent'],100)
        for build in (L.binary,L.assets):          # one \\fpSup\\LUT\\ holds one Look.cube (2026-11-06)
            with self.subTest(build=build.__name__),self.assertRaises(ValueError):build(doc)

    def saved_bin(self,document):
        data=L.binary(document);blob=bytearray(80)+data
        struct.pack_into('<I',blob,0,0x34425346)
        struct.pack_into('<I',blob,8,len(blob))
        struct.pack_into('<I',blob,48,0x3443544c)
        struct.pack_into('<I',blob,76,80)
        return bytes(blob)

    def test_recover_saved_settings_by_file_name_as_the_camera_keys_them(self):
        """The camera's records are its folder's files, by name (2026-11-06): a renamed file is a new cube there."""
        a=self.cube();b=self.cube('B.cube',title='B')
        original=L.import_cubes(L.blank(),[a,b],input_space='rec709',input_gamma='gamma24')
        edited=L.configure(original,'B.cube',input_space='p3-d65',input_gamma='linear',strength_percent=25,enabled=True,active=True)
        saved=self.saved_bin(edited)
        result=L.recover(original,saved)
        entry=L.find(result,'B.cube')
        self.assertEqual(result['active'],entry['id'])
        self.assertEqual((entry['enabled'],L.resolved(entry)['input_space'],L.resolved(entry)['strength_percent']),(True,'p3-d65',25))
        self.assertEqual(L.resolved(result['luts'][0])['strength_percent'],100)
        moved=b.with_name('Renamed.cube');b.rename(moved)
        manifest=L.import_cubes(original,[moved])
        result=L.recover(manifest,saved)
        self.assertIsNone(result['active'])
        self.assertFalse(L.find(result,'Renamed.cube')['enabled'])

    def test_recover_rejects_corrupt_record_and_preserves_manifest(self):
        original=L.import_cubes(L.blank(),[self.cube()],input_space='rec709',input_gamma='gamma24')
        before=json.dumps(original,sort_keys=True)
        saved=self.saved_bin(original)
        for pos in (0,8,48,76,80+24,80+64+100):
            blob=bytearray(saved);blob[pos]^=1
            with self.subTest(pos=pos),self.assertRaises(ValueError):L.recover(original,blob)
        blob=bytearray(saved);blob[-1]=1
        struct.pack_into('<I',blob,80+24,L.checksum(blob[80:]))
        with self.assertRaises(ValueError):L.recover(original,blob)
        self.assertEqual(json.dumps(original,sort_keys=True),before)

    def test_disable_active_becomes_off_without_selecting_another(self):
        doc=L.import_cubes(L.blank(),[self.cube()],input_space='rec709',input_gamma='gamma24')
        doc=L.configure(doc,'A.cube',enabled=True,active=True)
        doc=L.configure(doc,'A.cube',enabled=False)
        self.assertIsNone(doc['active'])
        self.assertEqual(L.validate(dict(schema=L.SCHEMA,active=None,luts=[]))['luts'],[])

    def test_pending_model_is_recorded_without_substitution(self):
        doc=L.import_cubes(L.blank(),[self.cube()],input_space='blackmagic-design',input_gamma='blackmagic-film')
        value=L.resolved(doc['luts'][0]);self.assertTrue(value['configured']);self.assertFalse(value['model_available'])
        data=L.binary(doc);flags,color,gamma,amount=struct.unpack_from('<4I',data,L.HEADER+96)
        self.assertEqual((color,gamma),(2,0));self.assertEqual(flags,L.READY)

    def test_binary_identity_flags_checksum_and_original_source(self):
        doc=L.import_cubes(L.blank(),[self.cube()],input_space='p3-d65',input_gamma='gamma26')
        doc=L.configure(doc,'A.cube',enabled=True,active=True)
        data=L.binary(doc)
        self.assertEqual(struct.unpack_from('<6I',data),(L.MAGIC,3,64,L.RECORD,1,0))
        count=struct.unpack_from('<I',data,16)[0]
        self.assertEqual(struct.unpack_from('<I',data,24)[0],L.checksum(data[:L.HEADER+L.RECORD*count]))   # the entries there are
        self.assertEqual(len(data),L.HEADER+L.RECORD*L.MAX_LUTS)                                   # room for the camera's
        source=self.root.joinpath('A.cube').read_bytes()
        self.assertEqual(data[64:96],L.camera_identity('A.cube',len(source)))      # as native imp_identity keys the file
        self.assertEqual(data[96:101],b'A.cube'[:5]);self.assertEqual(data[96:160].split(b'\0')[0],b'A.cube')
        self.assertEqual(struct.unpack_from('<4I',data,160),(15,4,2,100))
        self.assertEqual(struct.unpack_from('<4I',data,176),(len(source),0,0,L.ORIGIN_CAMERA))
        self.assertEqual(L.assets(doc),{'fpSup/LUT/A.cube':source})          # the user's file as it is, nothing else

    def test_user_choice_never_rewrites_the_author_and_overrides_from_behind(self):
        """user 2026-11-03: the designer's record stays; the user's choice is stored after it."""
        path=self.cube(comments=b'\xef\xbb\xbf# author\'s original comment\r\n# FPSUP_INPUT_COLOR_SPACE p3-d65\r\n# FPSUP_INPUT_GAMMA gamma26\r\n')
        before=path.read_bytes();doc=L.import_cubes(L.blank(),[path]);identity=doc['luts'][0]['id']
        doc=L.configure(doc,'A.cube',input_space='adobe-rgb',input_gamma='linear',color_matrix='off')
        self.assertEqual(path.read_bytes(),before)                       # the source file is not touched
        value=L.resolved(doc['luts'][0])
        self.assertEqual((value['input_space'],value['input_gamma'],value['color_matrix']),('adobe-rgb','linear','off'))
        self.assertEqual(value['author'],dict(input_space='p3-d65',input_gamma='gamma26',color_matrix=None))
        prepared=L.prepared_source(doc['luts'][0])
        self.assertEqual(L.author_settings(Cube.parse(prepared))['input_space'],'p3-d65')    # the author's line, kept
        self.assertEqual(CM.user_values(prepared),{'FPSUP_USER_INPUT_COLOR_SPACE':'adobe-rgb',
                         'FPSUP_USER_INPUT_GAMMA':'linear','FPSUP_USER_COLOR_MATRIX':'off'})
        self.assertEqual(CM.identity(prepared),identity)
        self.assertIn(before[3:],prepared)                               # the author's text, byte for byte
        # an author edit refreshes the author layer, the user's override still wins
        path.write_bytes(before.replace(b'p3-d65',b'p3-d60'))
        doc=L.refresh(doc);value=L.resolved(doc['luts'][0])
        self.assertEqual(doc['luts'][0]['id'],identity)
        self.assertEqual((value['author']['input_space'],value['input_space']),('p3-d60','adobe-rgb'))
        # choosing the author's own value clears the override
        doc=L.configure(doc,'A.cube',input_space='p3-d60',input_gamma='gamma26')
        self.assertNotIn('input_space',doc['luts'][0]['overrides']);self.assertNotIn('input_gamma',doc['luts'][0]['overrides'])
        self.assertEqual(CM.user_values(L.prepared_source(doc['luts'][0]))['FPSUP_USER_INPUT_COLOR_SPACE'],None)

    def test_author_color_matrix_and_custom_matrices(self):
        m1=b'# FPSUP_COLOR_MATRIX1 0.6 -0.1 -0.05 -0.4 1.2 0.2 -0.1 0.2 0.55\n'
        m2=b'# FPSUP_COLOR_MATRIX2 0.5 -0.0625 -.05 -0.4 1.25e0 0.2 -0.1 0.2 0.5\n'
        path=self.cube(comments=b'# FPSUP_COLOR_MATRIX custom\n'+m1+m2)
        doc=L.import_cubes(L.blank(),[path]);e=doc['luts'][0]
        self.assertEqual(L.resolved(e)['color_matrix'],'custom')
        a,d=L.custom_matrices(e['author'])
        self.assertEqual(a[0],round(0.6*2**20));self.assertEqual(d[1],-65536);self.assertEqual(d[4],int(1.25*2**20))
        data=L.binary(doc)
        self.assertEqual(struct.unpack_from('<9I',data,L.HEADER+128)[:5],(2,L.MATRIX_SET|L.AUTH_CUSTOM,0,0,2))
        self.assertEqual(list(struct.unpack_from('<18i',data,L.HEADER+176)),a+d)
        # matrices alone mean custom; one illuminant fills both
        doc=L.import_cubes(L.blank(),[self.cube('B.cube',m2,title='B')])
        e=doc['luts'][0];self.assertEqual(L.resolved(e)['color_matrix'],'custom')
        self.assertEqual(*L.custom_matrices(e['author']))
        # no author line: off (user 11-05), and custom cannot be chosen
        doc=L.import_cubes(L.blank(),[self.cube('C.cube',title='C')])
        self.assertEqual(L.resolved(doc['luts'][0])['color_matrix'],'off')
        with self.assertRaises(ValueError):L.configure(doc,'C.cube',color_matrix='custom')
        doc=L.configure(doc,'C.cube',color_matrix='off')
        self.assertEqual(struct.unpack_from('<9I',L.binary(doc),L.HEADER+128),(1,0,0,0,0,L.MATRIX_SET,0,0,1))
        for bad in (b'# FPSUP_COLOR_MATRIX custom\n',b'# FPSUP_COLOR_MATRIX standard\n'+m1,b'# FPSUP_COLOR_MATRIX grey\n',
                    b'# FPSUP_COLOR_MATRIX1 1 0 0 0 1 0 0 0\n',b'# FPSUP_COLOR_MATRIX1 1 0 0 0 1 0 0 0 1/2\n',
                    b'# FPSUP_COLOR_MATRIX1 17 0 0 0 1 0 0 0 1\n',m1+m1):
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                L.import_cubes(L.blank(),[self.cube('D.cube',bad,title='D')])

    def test_recover_v3_brings_back_the_user_layer_only(self):
        path=self.cube(comments=b'# FPSUP_INPUT_COLOR_SPACE p3-d65\n# FPSUP_INPUT_GAMMA gamma26\n# FPSUP_COLOR_MATRIX off\n')
        original=L.import_cubes(L.blank(),[path])
        edited=L.configure(original,'A.cube',input_space='p3-d65',input_gamma='linear',color_matrix='standard',enabled=True,active=True)
        result=L.recover(original,self.saved_bin(edited));e=result['luts'][0]
        self.assertEqual(e['overrides'],dict(input_gamma='linear',color_matrix='standard',strength_percent=100))
        self.assertEqual(result['active'],e['id'])

    def test_invalid_selection_does_not_change_source_comments(self):
        path=self.cube();doc=L.import_cubes(L.blank(),[path]);before=path.read_bytes()
        with self.assertRaises(ValueError):L.configure(doc,'A.cube',input_space='rec709',input_gamma='gamma24',active=True)
        self.assertEqual(path.read_bytes(),before)

    def test_changed_source_is_not_silently_bound_to_old_settings(self):
        path=self.cube();doc=L.import_cubes(L.blank(),[path])
        path.write_bytes(path.read_bytes()+b'# changed\n')
        with self.assertRaises(ValueError):L.assets(doc)

    def test_manifest_roundtrip_and_bound_are_explicit(self):
        doc=L.import_cubes(L.blank(),[self.cube()]);path=self.root/'library.json'
        L.save(path,doc);self.assertEqual(L.read(path),doc)
        too_many=json.loads(json.dumps(doc))
        too_many['luts']*=L.MAX_LUTS+1
        with self.assertRaises(ValueError):L.validate(too_many)


if __name__=='__main__':unittest.main()
