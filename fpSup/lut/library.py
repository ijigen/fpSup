"""Per-cube monitoring library and optional author comments; no camera I/O.

Filenames are labels. SHA-256 excluding managed comments binds settings here.
FPSUP_* comments are our optional convention, not a standard .cube header.

On the card (2026-11-06, Bei: the list is the folder) every LUT is a .cube in
\\fpSup\\LUT\\ and the camera keys it by file name (native/import.c imp_identity:
name, size and dates); its settings live in LUT.BIN only.  A library given to
build_sup is therefore written as those files plus pre-filled records for them
(binary(), assets()): the camera finds each by name and keeps the settings.
"""
import hashlib
from fractions import Fraction
import json
import os
from pathlib import Path
import shlex
import struct
import tempfile

from cube import Cube
from cinemadng import COLOR_SPACES, COMMON_GAMMAS, BLACKMAGIC_GAMMAS, Selection
import cube_metadata as CM

SCHEMA='fpsup-lut-library-1'
STRENGTHS=(0,20,25,40,50,60,75,80,100)   # 25 % steps; the COLOR box's 20 % (native/clist.c)
MAX_LUTS=32                         # development library; never silently truncate
MAGIC=0x31424c43                    # CLB1, embedded user record in LUT.BIN
VERSION=3
HEADER=64
RECORD=256                          # v3: author + user layers (native/library4.h)
NONE=0xffffffff
ENABLED=1
SPACE_SET=2
GAMMA_SET=4
MATRIX_SET=8
READY=SPACE_SET|GAMMA_SET|MATRIX_SET
AUTH_CUSTOM=16                      # author_flags: the author's custom matrices parsed
MATRICES=('standard','off','custom')   # the DNG profile the LUT was made on (user 2026-11-03)
GAMMAS_ALL=(*COMMON_GAMMAS,*BLACKMAGIC_GAMMAS)
Q20=1<<20
MATRIX_LIMIT=16                     # |coefficient| <= 16, as the asset's matrices
ORIGIN_CAMERA=1                     # native/library4.h: a .cube in \\fpSup\\LUT\\ (every record, since 2026-11-06)
ORIGIN_GONE=2                       # ... whose file is not there (the record is kept, hidden)
TAGS={
    'FPSUP_INPUT_COLOR_SPACE':'input_space',
    'FPSUP_INPUT_GAMMA':'input_gamma',
    'FPSUP_OUTPUT_COLOR_SPACE':'output_space',
    'FPSUP_OUTPUT_GAMMA':'output_gamma',
    'FPSUP_COLOR_MATRIX':'color_matrix',
}
MATRIX_TAGS={'FPSUP_COLOR_MATRIX1':'matrix1','FPSUP_COLOR_MATRIX2':'matrix2'}


def q20(token):
    """round(decimal * 2^20), ties to even, exactly as native/import.c imp_q20."""
    import re
    if not re.fullmatch(r'[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?',token):raise ValueError(f'matrix coefficient {token!r} is not a decimal')
    value=Fraction(token)*Q20
    if abs(value)>MATRIX_LIMIT*Q20:raise ValueError('matrix coefficient outside +-16')
    return round(value)


def author_settings(cube):
    """The author's FPSUP_* lines, after our managed block (which is the user's)."""
    result={}
    _prefix,text=CM.split(cube.source)
    for line_no,line in enumerate(text.decode('utf-8-sig').splitlines(),1):
        line=line.strip()
        if not line.startswith('#'):continue
        first=line[1:].lstrip().split(None,1)
        if not first or (first[0] not in TAGS and first[0] not in MATRIX_TAGS):continue
        parts=shlex.split(line[1:],comments=False)
        if parts[0] in MATRIX_TAGS:
            key=MATRIX_TAGS[parts[0]]
            if len(parts)!=10 or key in result:raise ValueError(f'line {line_no}: {parts[0]} needs nine numbers, once')
            try:[q20(v) for v in parts[1:]]
            except (ValueError,ZeroDivisionError) as error:raise ValueError(f'line {line_no}: {error}') from None
            result[key]=parts[1:];continue
        key=TAGS[parts[0]]
        if len(parts)!=2 or key in result:
            raise ValueError(f'line {line_no}: duplicate or invalid {parts[0]}')
        result[key]=None if parts[1]=='unset' and key in ('input_space','input_gamma','color_matrix') else parts[1]
    if result.get('input_space') is not None and result['input_space'] not in COLOR_SPACES:
        raise ValueError('author input color space is not supported')
    if result.get('input_gamma') is not None and result['input_gamma'] not in GAMMAS_ALL:
        raise ValueError('author input gamma is not supported')
    if result.get('input_space') and result.get('input_gamma'):
        Selection(result['input_space'],result['input_gamma'])
    if result.get('output_space','rec709')!='rec709' or result.get('output_gamma','gamma24')!='gamma24':
        raise ValueError('monitoring library requires Rec.709 / Gamma 2.4 output')
    has=('matrix1' in result) or ('matrix2' in result)
    if result.get('color_matrix') is not None and result['color_matrix'] not in MATRICES:
        raise ValueError('author color matrix must be standard, off or custom')
    if has and result.get('color_matrix') in ('standard','off'):
        raise ValueError('custom matrices given with a stock color matrix')
    if result.get('color_matrix')=='custom' and not has:
        raise ValueError('custom color matrix needs FPSUP_COLOR_MATRIX1 or 2')
    if has and result.get('color_matrix') is None:result['color_matrix']='custom'
    return result


def custom_matrices(author):
    """[A, D65] as Q20 rows of nine; one given = both (single illuminant)."""
    one=author.get('matrix1') or author.get('matrix2');two=author.get('matrix2') or author.get('matrix1')
    return [[q20(v) for v in m] for m in (one,two)]


def blank():return dict(schema=SCHEMA,active=None,luts=[])


def compatible(space_index,gamma):
    return (space_index==2)==(gamma in BLACKMAGIC_GAMMAS)


def resolved(entry):
    """Effective values: the user's override, else the author's, else unset -- native lib_resolve."""
    author=entry.get('author',{})
    override=entry.get('overrides',{})
    us,ug,um=override.get('input_space'),override.get('input_gamma'),override.get('color_matrix')
    au,ag,am=author.get('input_space'),author.get('input_gamma'),author.get('color_matrix')
    for v,ok in ((us,COLOR_SPACES),(au,COLOR_SPACES)):
        if v is not None and v not in ok:raise ValueError('unknown LUT input color space')
    for v in (ug,ag):
        if v is not None and v not in GAMMAS_ALL:raise ValueError('unknown LUT input gamma')
    for v in (um,am):
        if v is not None and v not in MATRICES:raise ValueError('unknown LUT color matrix')
    amount=override.get('strength_percent',100)
    if type(amount) is not int or amount not in STRENGTHS:raise ValueError('strength must be one of %s'%(STRENGTHS,))
    color=us if us is not None else au
    first=ug if ug is not None else ag
    index=list(COLOR_SPACES).index(color) if color is not None else (2 if first in BLACKMAGIC_GAMMAS else 6)
    gamma=next((g for g in (ug,ag) if g is not None and compatible(index,g)),None)
    custom='matrix1' in author or 'matrix2' in author
    matrix=next((m for m in (um,am) if m is not None and (m!='custom' or custom)),None) or 'off'   # no author's: Off (user 11-05)
    selection=Selection(color,gamma) if color is not None and gamma is not None else None
    return dict(input_space=color,input_gamma=gamma,color_matrix=matrix,strength_percent=amount,
                configured=selection is not None,
                model_available=bool(selection and selection.numerical_reference_available),
                author=dict(input_space=au,input_gamma=ag,color_matrix=am))


def validate(document):
    if not isinstance(document,dict) or document.get('schema')!=SCHEMA or not isinstance(document.get('luts'),list):
        raise ValueError('not an fpSup LUT library')
    entries=document['luts']
    if len(entries)>MAX_LUTS:raise ValueError(f'development library supports at most {MAX_LUTS} LUTs')
    ids=set();names={}
    for entry in entries:
        identity=entry.get('id','')
        if len(identity)!=64 or any(c not in '0123456789abcdef' for c in identity) or identity in ids:
            raise ValueError('invalid or duplicate cube content identity')
        ids.add(identity)
        filename=entry.get('filename','')
        if not filename or len(filename.encode())>63 or any(ord(c)<32 for c in filename):
            raise ValueError('cube display filename must fit 63 UTF-8 bytes without control characters')
        if type(entry.get('enabled')) is not bool:raise ValueError('enabled must be a boolean')
        if not isinstance(entry.get('source'),str):raise ValueError('missing original cube source')
        if not isinstance(entry.get('author'),dict) or not isinstance(entry.get('overrides'),dict):
            raise ValueError('invalid per-cube settings')
        if entry['overrides'].get('color_matrix')=='custom' and not ('matrix1' in entry['author'] or 'matrix2' in entry['author']):
            raise ValueError('custom color matrix: the author gave none')
        resolved(entry)
        names.setdefault(filename.casefold(),[]).append(identity)
        if entry['author'].get('output_space','rec709')!='rec709' or entry['author'].get('output_gamma','gamma24')!='gamma24':
            raise ValueError('author output is outside the fixed monitoring contract')
    active=document.get('active')
    if active is not None:
        selected=next((e for e in entries if e['id']==active),None)
        if selected is None or not selected['enabled'] or not resolved(selected)['configured']:
            raise ValueError('active LUT must be enabled and have an explicit input space and gamma')
    return document


def read(path):return validate(json.loads(Path(path).read_text()))


def save(path,document):
    validate(document)
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    payload=json.dumps(document,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    name=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,prefix=path.name+'.',delete=False) as stream:
            name=stream.name;stream.write(payload)
        os.replace(name,path)
    finally:
        if name and Path(name).exists():Path(name).unlink()


def set_override(entry,key,value):
    """The user's choice; the author's own value is no override (it clears one)."""
    if value is None or entry['author'].get(key)==value:entry['overrides'].pop(key,None)
    else:entry['overrides'][key]=value


def import_cubes(document,paths,*,input_space=None,input_gamma=None,color_matrix=None):
    """Read each cube's author lines; never write the source.  input_* given = the user's choice."""
    validate(document)
    if (input_space is None)!=(input_gamma is None):raise ValueError('supply input space and gamma together')
    if input_space is not None:Selection(input_space,input_gamma)
    result=json.loads(json.dumps(document))
    for path in paths:
        path=Path(path).resolve();cube=Cube.read(path)
        author=author_settings(cube)
        identity=CM.identity(cube.source)
        previous=next((e for e in result['luts'] if e['id'] in (identity,cube.sha256)),None)
        if previous:
            if result.get('active')==previous['id']:result['active']=identity
            previous.update(id=identity,source=str(path),filename=path.name,author=author)
            for k in ('input_space','input_gamma','color_matrix'):          # an override equal to the new author value goes
                if k in previous['overrides']:set_override(previous,k,previous['overrides'][k])
        else:
            previous=dict(id=identity,filename=path.name,source=str(path),enabled=False,author=author,overrides={})
            result['luts'].append(previous)
            carried=CM.user_values(cube.source)          # a prepared copy brings its user layer along
            for key,tag in (('input_space','FPSUP_USER_INPUT_COLOR_SPACE'),('input_gamma','FPSUP_USER_INPUT_GAMMA'),
                            ('color_matrix','FPSUP_USER_COLOR_MATRIX')):
                if carried.get(tag) is not None:set_override(previous,key,carried[tag])
        if input_space is not None:
            set_override(previous,'input_space',input_space);set_override(previous,'input_gamma',input_gamma)
        if color_matrix is not None:set_override(previous,'color_matrix',color_matrix)
        if result.get('active')==identity and not resolved(previous)['configured']:result['active']=None
    return validate(result)


def find(document,key):
    exact=[e for e in document['luts'] if e['id']==key]
    matches=exact or [e for e in document['luts'] if e['id'].startswith(key) or e['filename']==key]
    if len(matches)!=1:raise ValueError('LUT identifier is missing or ambiguous; use its content ID')
    return matches[0]


def configure(document,key,*,input_space=None,input_gamma=None,color_matrix=None,strength_percent=None,enabled=None,active=False):
    """The user's layer only: the cube file and the author's lines are never touched."""
    result=json.loads(json.dumps(document));entry=find(result,key)
    if (input_space is None)!=(input_gamma is None):raise ValueError('supply input space and gamma together')
    if input_space is not None:
        Selection(input_space,input_gamma)
        if CM.identity(Path(entry['source']).read_bytes())!=entry['id']:raise ValueError('cube contents changed; import the file again')
        set_override(entry,'input_space',input_space);set_override(entry,'input_gamma',input_gamma)
    if color_matrix is not None:
        if color_matrix not in MATRICES:raise ValueError('color matrix must be standard, off or custom')
        set_override(entry,'color_matrix',color_matrix)
    if strength_percent is not None:entry['overrides']['strength_percent']=strength_percent
    if enabled is not None:entry['enabled']=enabled
    if not entry['enabled'] and result.get('active')==entry['id']:result['active']=None
    if active:result['active']=entry['id']
    return validate(result)


def summary(document):
    validate(document)
    return dict(active=document.get('active'),luts=[dict(id=e['id'],filename=e['filename'],enabled=e['enabled'],
                     active=document.get('active')==e['id'],**resolved(e)) for e in document['luts']])


def refresh(document):
    """Re-read every author layer (an external edit included); the user's layer stays."""
    validate(document);result=json.loads(json.dumps(document))
    for entry in result['luts']:
        cube=Cube.read(entry['source'])
        if CM.identity(cube.source)!=entry['id']:raise ValueError('cube contents changed; import the file again')
        entry['author']=author_settings(cube)
        for k in ('input_space','input_gamma','color_matrix'):
            if k in entry['overrides']:set_override(entry,k,entry['overrides'][k])
        if entry['overrides'].get('color_matrix')=='custom' and not ('matrix1' in entry['author'] or 'matrix2' in entry['author']):
            entry['overrides'].pop('color_matrix')
        if result.get('active')==entry['id'] and not resolved(entry)['configured']:result['active']=None
    return validate(result)


def checksum(data):
    value=2166136261
    for i,byte in enumerate(data):value=((value^(0 if 24<=i<28 else byte))*16777619)&0xffffffff
    return value


def layer_fields(entry):
    """native lib_entry +128..+256: author and user layers, gammas as the global index (6, 7 = Blackmagic)."""
    author,override=entry['author'],entry['overrides']
    spaces=list(COLOR_SPACES)
    af=(SPACE_SET if author.get('input_space') else 0)|(GAMMA_SET if author.get('input_gamma') else 0)| \
       (MATRIX_SET if author.get('color_matrix') else 0)|(AUTH_CUSTOM if ('matrix1' in author or 'matrix2' in author) else 0)
    uf=(SPACE_SET if 'input_space' in override else 0)|(GAMMA_SET if 'input_gamma' in override else 0)| \
       (MATRIX_SET if 'color_matrix' in override else 0)
    ix=lambda seq,v:seq.index(v) if v is not None else 0
    cm=custom_matrices(author) if af&AUTH_CUSTOM else [[0]*9,[0]*9]
    return (af,ix(spaces,author.get('input_space')),ix(GAMMAS_ALL,author.get('input_gamma')),
            ix(MATRICES,author.get('color_matrix')),uf,ix(spaces,override.get('input_space')),
            ix(GAMMAS_ALL,override.get('input_gamma')),ix(MATRICES,override.get('color_matrix'))),cm


def camera_name(filename):
    """The entry name the camera gives a file (native/import.c imp_is_cube): UTF-16 units, non-ASCII as '?'."""
    units=filename.encode('utf-16-le')
    name=''.join(chr(c) if c<0x80 else '?' for c in struct.unpack(f'<{len(units)//2}H',units))
    if len(name)>63 or len(name)<6 or not name.lower().endswith('.cube'):raise ValueError(f'{filename!r}: not a name the camera lists')
    return name


def camera_identity(name,size,dates=bytes(12)):
    """native/import.c imp_identity: 'CAM1', size, the directory entry's 12 date bytes, FNV-1a of the name."""
    sha=bytearray(32);sha[0:4]=b'CAM1';struct.pack_into('<I',sha,4,size);sha[8:20]=dates
    struct.pack_into('<I',sha,20,fnv(name.encode()));return bytes(sha)


def _listable(filename):
    try:camera_name(filename);return True
    except ValueError:return False


def record_identity(entry):
    """The identity binary() writes for this entry (the camera's for its file, at zero dates)."""
    return camera_identity(camera_name(entry['filename']),len(Path(entry['source']).read_bytes()))


def card_names(document):
    """{entry id: the camera's name}; two cubes of one name cannot both be in the folder."""
    names={e['id']:camera_name(e['filename']) for e in document['luts']}
    if len({n.casefold() for n in names.values()})!=len(names):raise ValueError('two cubes of the same name: \\fpSup\\LUT\\ holds one')
    return names


def binary(document):
    """LUT.BIN's catalog: one record per cube as the camera keeps it (origin camera, keyed by name).  The
    identity assumes zero dates; the camera's own differs and it re-keys by name on its first scan."""
    document=refresh(document);entries=document['luts'];names=card_names(document)
    identities=b''.join(bytes.fromhex(e['id']) for e in entries)
    out=bytearray(HEADER+RECORD*MAX_LUTS)          # room for what native/import.c adds on the camera
    active=next((i for i,e in enumerate(entries) if e['id']==document.get('active')),NONE)
    struct.pack_into('<8I',out,0,MAGIC,VERSION,HEADER,RECORD,len(entries),active,0,0)
    out[32:64]=hashlib.sha256(identities).digest()
    for i,entry in enumerate(entries):
        p=HEADER+RECORD*i;value=resolved(entry)
        source=Path(entry['source']).read_bytes();name=names[entry['id']]
        out[p:p+32]=camera_identity(name,len(source));out[p+32:p+32+len(name)]=name.encode()   # = record_identity
        flags=int(entry['enabled']) | (SPACE_SET if value['input_space'] is not None else 0) | \
              (GAMMA_SET if value['input_gamma'] is not None else 0) | MATRIX_SET
        color=list(COLOR_SPACES).index(value['input_space']) if value['input_space'] is not None else \
              (2 if (entry['overrides'].get('input_gamma') or entry['author'].get('input_gamma')) in BLACKMAGIC_GAMMAS else 6)
        gammas=BLACKMAGIC_GAMMAS if color==2 else COMMON_GAMMAS
        gamma=gammas.index(value['input_gamma']) if value['input_gamma'] in gammas else 0
        struct.pack_into('<4I',out,p+96,flags,color,gamma,value['strength_percent'])
        struct.pack_into('<4I',out,p+112,len(source),0,0,ORIGIN_CAMERA)
        layers,cm=layer_fields(entry)
        struct.pack_into('<9I',out,p+128,MATRICES.index(value['color_matrix']),*layers)
        struct.pack_into('<18i',out,p+176,*cm[0],*cm[1])
    struct.pack_into('<I',out,24,checksum(out[:HEADER+RECORD*len(entries)]))   # native library_hash: the entries there are
    return bytes(out)


def recover(document,bin_data,sources=None):
    """Merge a saved on-camera BIN, before rebuilding the library: a record of a .cube in the folder
    (origin camera) by the file's name, an older prepared one by content ID.
    v1/v2 records carry effective values only: they become user overrides where
    they differ from the author.  v3 carries the user layer itself."""
    validate(document)
    if len(bin_data)<80 or struct.unpack_from('<I',bin_data)[0]!=0x34425346 or struct.unpack_from('<I',bin_data,48)[0]!=0x3443544c:
        raise ValueError('not a LUT4 BIN')
    file_len=struct.unpack_from('<I',bin_data,8)[0]
    off=struct.unpack_from('<I',bin_data,76)[0]
    if file_len!=len(bin_data) or off<80 or off+HEADER>file_len:raise ValueError('BIN has no valid library record')
    magic,version,header,record,count,active,total,reserved=struct.unpack_from('<8I',bin_data,off)
    rec=RECORD if version==3 else 128
    size=HEADER+rec*count
    if magic!=MAGIC or version not in (1,2,3) or (header,record,reserved)!=(HEADER,rec,0) or count>MAX_LUTS or off+size>file_len:
        raise ValueError('invalid saved library')
    data=bin_data[off:off+size]
    if checksum(data)!=total or (active!=NONE and active>=count):raise ValueError('corrupt saved library')
    result=json.loads(json.dumps(document));saved=[]
    by_name={camera_name(e['filename']):e['id'] for e in result['luts'] if _listable(e['filename'])}
    for i in range(count):
        p=HEADER+rec*i;identity=data[p:p+32].hex()
        flags,color,gamma,amount=struct.unpack_from('<4I',data,p+96)
        if not data[p+32] or data[p+95]:raise ValueError('invalid saved cube record')
        if version==1 and any(data[p+112:p+128]):raise ValueError('invalid saved cube record')
        origin=0
        if version>=2:
            length,body_hash,options,origin=struct.unpack_from('<4I',data,p+112)
            if origin>(ORIGIN_CAMERA|ORIGIN_GONE) or options>1 or length>CM.MAX_SOURCE or \
               (not origin&ORIGIN_CAMERA and (length<CM.SIZE or origin)):raise ValueError('invalid saved source record')
            if origin&ORIGIN_CAMERA:identity=by_name.get(data[p+32:p+96].split(b'\0')[0].decode('ascii','replace'),'camera:'+identity)
        if flags>(15 if version==3 else 7) or color>=len(COLOR_SPACES) or amount not in STRENGTHS:raise ValueError('invalid saved cube settings')
        gammas=BLACKMAGIC_GAMMAS if color==2 else COMMON_GAMMAS
        if gamma>=len(gammas) or identity in saved:raise ValueError('invalid saved gamma or duplicate identity')
        if version==3:
            _m,_af,_ac,_ag,_am,uf,uc,ug,um=struct.unpack_from('<9I',data,p+128)
            if uf&~(SPACE_SET|GAMMA_SET|MATRIX_SET) or uc>=len(COLOR_SPACES) or ug>=len(GAMMAS_ALL) or um>=len(MATRICES):
                raise ValueError('invalid saved user layer')
        saved.append(identity)
        entry=next((e for e in result['luts'] if e['id']==identity),None)
        if entry:
            entry['enabled']=bool(flags&ENABLED)
            entry['overrides']['strength_percent']=amount
            if version==3:
                for bit,key,value in ((SPACE_SET,'input_space',list(COLOR_SPACES)[uc]),(GAMMA_SET,'input_gamma',GAMMAS_ALL[ug]),
                                      (MATRIX_SET,'color_matrix',MATRICES[um])):
                    set_override(entry,key,value if uf&bit else None)
            else:
                if version==2 and sources is not None:
                    source=Path(sources)/(identity+'.cube');cube=Cube.read(source)
                    if CM.identity(cube.source)!=entry['id']:raise ValueError('saved cube identity differs from the library')
                    entry['source']=str(source.resolve())
                set_override(entry,'input_space',list(COLOR_SPACES)[color] if flags&SPACE_SET else None)
                set_override(entry,'input_gamma',gammas[gamma] if flags&GAMMA_SET else None)
            if entry['overrides'].get('color_matrix')=='custom' and not ('matrix1' in entry['author'] or 'matrix2' in entry['author']):
                entry['overrides'].pop('color_matrix')
    desired=saved[active] if active!=NONE else None
    result['active']=desired if any(e['id']==desired and e['enabled'] and resolved(e)['configured'] for e in result['luts']) else None
    return validate(result)


def fnv(data):
    value=2166136261
    for byte in data:value=((value^byte)*16777619)&0xffffffff
    return value


def prepared_source(entry):
    source=Path(entry['source']).read_bytes()
    if CM.identity(source)!=entry['id']:raise ValueError('cube contents changed; import the file again')
    o=entry['overrides']
    return CM.prepare(source,o.get('input_space'),o.get('input_gamma'),o.get('color_matrix'))


def assets(document):
    """The card's \\fpSup\\LUT\\: each cube as it is (the user's file; the camera parses it, native/import.c).
    Nothing else of ours goes in that folder (2026-11-06)."""
    document=refresh(document);names=card_names(document);files={}
    for entry in document['luts']:
        source=Path(entry['source']).read_bytes()
        if CM.identity(source)!=entry['id']:raise ValueError('cube contents changed; import the file again')
        files[f'fpSup/LUT/{entry["filename"]}']=source
    if len({k.casefold() for k in files})!=len(files):raise ValueError('two cubes of the same file name')
    return files
