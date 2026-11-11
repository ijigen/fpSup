"""The prepared camera copy's managed comment block -- the user layer only.

A prepared copy starts with a 512-byte block we own, so a camera writeback
never shifts the LUT table.  It holds the user's choices (FPSUP_USER_*, or
`unset` = follow the author).  The author's own FPSUP_* lines stay in the body
exactly as written: neither the host nor the camera ever rewrites them
(user 2026-11-03: the designer's record is kept, the user's choice overrides
it from behind).  Identity excludes the managed block and the author's
FPSUP_* lines, so an author edit refreshes the same entry.
"""
import hashlib

SIZE=512
MAX_SOURCE=64*1024*1024
BOM=b'\xef\xbb\xbf'
MARKER=b'# FPSUP_METADATA_V1\n'
END=b'# FPSUP_METADATA_END\n'
AUTHOR_KEYS=(b'FPSUP_INPUT_COLOR_SPACE',b'FPSUP_INPUT_GAMMA',
             b'FPSUP_OUTPUT_COLOR_SPACE',b'FPSUP_OUTPUT_GAMMA',
             b'FPSUP_COLOR_MATRIX',b'FPSUP_COLOR_MATRIX1',b'FPSUP_COLOR_MATRIX2')
USER_KEYS=(b'FPSUP_USER_INPUT_COLOR_SPACE',b'FPSUP_USER_INPUT_GAMMA',b'FPSUP_USER_COLOR_MATRIX')
FIXED_OUTPUT=b'# FPSUP_OUTPUT_COLOR_SPACE rec709\n# FPSUP_OUTPUT_GAMMA gamma24\n'


def split(source):
    """(BOM prefix, the source without our managed block)."""
    prefix=BOM if source.startswith(BOM) else b''
    raw=source[len(prefix):]
    if raw.startswith(MARKER):
        end=raw.find(END,len(MARKER),4096)
        if end<0 or raw[end-1:end]!=b'\n':raise ValueError('truncated fpSup comment block')
        raw=raw[end+len(END):]
    return prefix,raw


def body(source):
    """(prefix, text) with the managed block and the author's FPSUP_* lines removed: the identity's input."""
    prefix,raw=split(source)
    lines=[]
    for line in raw.splitlines(keepends=True):
        stripped=line.lstrip()
        if stripped.startswith(b'#'):
            token=stripped[1:].lstrip().split(None,1)
            if token and token[0] in AUTHOR_KEYS+USER_KEYS:continue
        lines.append(line)
    return prefix,b''.join(lines)


def identity(source):
    prefix,table=body(source)
    return hashlib.sha256(prefix+table).hexdigest()


def header(identity,color=None,gamma=None,matrix=None,*,bom=False):
    """The managed block: the user's overrides, `unset` where the author's value stands."""
    if len(identity)!=64 or any(c not in '0123456789abcdef' for c in identity):raise ValueError('invalid cube identity')
    data=(BOM if bom else b'')+MARKER+f'# FPSUP_SOURCE_ID {identity}\n'.encode()
    for name,value in zip(USER_KEYS,(color,gamma,matrix)):
        data+=b'# '+name+b' '+(value or 'unset').encode()+b'\n'
    data+=FIXED_OUTPUT
    if len(data)+2+len(END)>SIZE:raise ValueError('user settings do not fit the managed comment block')
    return data+b'#'+b' '*(SIZE-len(data)-2-len(END))+b'\n'+END


def user_values(source):
    """The managed block's user layer: {key: value or None}; {} when there is no block."""
    prefix=BOM if source.startswith(BOM) else b''
    raw=source[len(prefix):]
    if not raw.startswith(MARKER):return {}
    block=raw[:raw.find(END)]
    out={}
    for line in block.splitlines():
        parts=line[1:].split() if line.startswith(b'#') else []
        if len(parts)==2 and parts[0] in USER_KEYS:
            out[parts[0].decode()]=None if parts[1]==b'unset' else parts[1].decode()
    return out


def prepare(source,color=None,gamma=None,matrix=None):
    """The camera copy: our block of user choices, then the source as the author wrote it."""
    prefix,rest=split(source)
    result=header(identity(source),color,gamma,matrix,bom=bool(prefix))+rest
    if len(result)>MAX_SOURCE:raise ValueError('camera cube source exceeds the 64 MiB development limit')
    return result
