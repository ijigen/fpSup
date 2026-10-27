"""Streaming ISO9660 + Joliet writer.

Directory space is reserved before payloads. File extents and sizes are filled in
after compression, without staging a second copy of the clip. No Rock Ridge,
symlinks, >4GiB files, or non-BMP Joliet names are silently approximated.
"""
import datetime
import hashlib
import math
import struct
from dataclasses import dataclass, field
from pathlib import PurePosixPath

BLOCK = 2048


def both16(n): return struct.pack('<H',n)+struct.pack('>H',n)
def both32(n): return struct.pack('<I',n)+struct.pack('>I',n)
def blocks(n): return (n+BLOCK-1)//BLOCK


@dataclass
class Node:
    path: str
    directory: bool
    index: int
    parent: object = None
    children: list = field(default_factory=list)
    extent: int = 0
    size: int = 0
    mtime: float = 0
    locations: dict = field(default_factory=dict)
    lengths: dict = field(default_factory=dict)

    def name(self, joliet):
        if not self.path: return b'\0'
        if joliet: return PurePosixPath(self.path).name.encode('utf-16-be')
        return (f'D{self.index:07}' if self.directory else f'F{self.index:07}.DAT;1').encode('ascii')


def record(node, identifier, joliet, directory=None):
    isdir = node.directory if directory is None else directory
    extent = node.locations[joliet] if isdir else node.extent
    size = node.lengths[joliet] if isdir else node.size
    stamp = datetime.datetime.fromtimestamp(node.mtime or 0, datetime.timezone.utc)
    stamp = max(stamp, datetime.datetime(1900,1,1,tzinfo=datetime.timezone.utc))
    date = bytes((min(255,stamp.year-1900),stamp.month,stamp.day,stamp.hour,stamp.minute,stamp.second,0))
    length = 33+len(identifier)+(len(identifier)%2 == 0)
    return (bytes((length,0))+both32(extent)+both32(size)+date+
            bytes((2 if isdir else 0,0,0))+both16(1)+bytes((len(identifier),))+
            identifier+b'\0'*(len(identifier)%2 == 0))


class StreamISO:
    def __init__(self, file, paths, volume='CDNG_IMAGE'):
        self.file = file
        self.volume = volume
        self.nodes = {'':Node('',True,1)}
        for path, isdir, mtime in paths:
            parts = PurePosixPath(path).parts
            if not parts or any(p in ('','..','.') for p in parts):
                raise ValueError(f'Invalid archive path: {path}')
            for part in parts:
                if len(part.encode('utf-16-be')) > 128 or any(ord(c)>65535 or ord(c)<32 or c in '\\/:*?"<>|' for c in part):
                    raise ValueError(f'Name is not portable to Windows/Joliet: {part}')
            for i in range(1,len(parts)+1):
                key = '/'.join(parts[:i])
                want_dir = i < len(parts) or isdir
                if key not in self.nodes:
                    parent = self.nodes['/'.join(parts[:i-1])]
                    if not parent.directory:
                        raise ValueError('File/directory name conflict')
                    if any(PurePosixPath(n.path).name.casefold() == parts[i-1].casefold() for n in parent.children):
                        raise ValueError(f'Case-insensitive name collision: {key}')
                    node = Node(key,want_dir,len(self.nodes)+1,parent,mtime=mtime)
                    self.nodes[key] = node; parent.children.append(node)
                elif self.nodes[key].directory != want_dir:
                    raise ValueError('File/directory name conflict')
        self.dirs = sorted((n for n in self.nodes.values() if n.directory), key=lambda n:(n.path.count('/')+(bool(n.path)),n.path))
        if len(self.dirs)>65535: raise ValueError('Too many directories for ISO')
        self.dir_index = {n.path:i+1 for i,n in enumerate(self.dirs)}
        cursor = 19
        self.tables = {}
        for joliet in (False,True):
            size = sum(8+len(n.name(joliet))+(len(n.name(joliet))%2) for n in self.dirs)
            self.tables[joliet] = (cursor,cursor+blocks(size),size)
            cursor += 2*blocks(size)
            for node in self.dirs:
                used = 68  # dot, dot-dot
                for child in sorted(node.children,key=lambda n:n.name(joliet)):
                    length = 33+len(child.name(joliet))+(len(child.name(joliet))%2 == 0)
                    if used%BLOCK+length > BLOCK: used += BLOCK-used%BLOCK
                    used += length
                node.locations[joliet] = cursor
                node.lengths[joliet] = blocks(used)*BLOCK
                cursor += blocks(used)
        self.payload_start = cursor*BLOCK
        file.seek(self.payload_start)
        self.written = set()

    def add(self, path, chunks, cancel=None):
        node = self.nodes[path]
        if node.directory or path in self.written:
            raise ValueError(f'Invalid or duplicate payload: {path}')
        node.extent = self.file.tell()//BLOCK
        digest = hashlib.sha256()
        size = 0
        for chunk in chunks:
            if cancel and cancel.is_set(): raise InterruptedError('Cancelled')
            size += len(chunk)
            if size > 0xffffffff: raise ValueError('A single file exceeds the ISO 4 GiB limit')
            if self.file.tell()+len(chunk) >= (2**32-1)*BLOCK: raise ValueError('ISO exceeds 8 TiB limit')
            self.file.write(chunk); digest.update(chunk)
        node.size = size
        self.file.write(b'\0'*(-size%BLOCK))
        self.written.add(path)
        return dict(size=size,sha256=digest.hexdigest(),extent=node.extent)

    def _descriptor(self, joliet, volume_blocks):
        b = bytearray(BLOCK)
        b[:7] = bytes((2 if joliet else 1,))+b'CD001\1'
        enc = 'utf-16-be' if joliet else 'ascii'
        def text(at,width,value):
            pad = ' '.encode(enc); raw = value.encode(enc)
            b[at:at+width] = (raw+pad*width)[:width]
        text(8,32,'CDNG IMAGE');text(40,32,self.volume[:16] if joliet else self.volume[:32])
        b[80:88] = both32(volume_blocks)
        if joliet:b[88:91]=b'%/E'
        b[120:124]=both16(1);b[124:128]=both16(1);b[128:132]=both16(BLOCK)
        le,be,size=self.tables[joliet]
        b[132:140]=both32(size)
        struct.pack_into('<I',b,140,le);struct.pack_into('>I',b,148,be)
        b[156:190]=record(self.nodes[''],b'\0',joliet)
        text(190,128,'CDNG IMAGE');text(318,128,'CDNG IMAGE');text(446,128,'CDNG IMAGE 0.1.0')
        for at in (813,830,847,864):b[at:at+17]=b'0'*16+b'\0'
        b[881]=1
        return b

    def finish(self):
        missing = {p for p,n in self.nodes.items() if not n.directory}-self.written
        if missing: raise ValueError(f'Missing payloads: {sorted(missing)[:3]}')
        end = self.file.tell()
        for joliet in (False,True):
            for node in self.dirs:
                parent=node.parent or node
                data=bytearray(record(node,b'\0',joliet)+record(parent,b'\1',joliet))
                for child in sorted(node.children,key=lambda n:n.name(joliet)):
                    rec=record(child,child.name(joliet),joliet)
                    if len(data)%BLOCK+len(rec)>BLOCK:data.extend(b'\0'*(-len(data)%BLOCK))
                    data.extend(rec)
                data.extend(b'\0'*(node.lengths[joliet]-len(data)))
                self.file.seek(node.locations[joliet]*BLOCK);self.file.write(data)
            le,be,_=self.tables[joliet]
            for endian,location in (('<',le),('>',be)):
                table=bytearray()
                for node in self.dirs:
                    name=node.name(joliet)
                    table.extend(bytes((len(name),0))+struct.pack(endian+'IH',node.locations[joliet],self.dir_index[(node.parent or node).path])+name+b'\0'*(len(name)%2))
                self.file.seek(location*BLOCK);self.file.write(table)
        self.file.seek(16*BLOCK);self.file.write(self._descriptor(False,end//BLOCK))
        self.file.write(self._descriptor(True,end//BLOCK));self.file.write(b'\xffCD001\1'+b'\0'*(BLOCK-7))
        self.file.truncate(end);self.file.flush()
        return end
