import concurrent.futures
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import threading
import time
import uuid

import numpy as np
import pycdlib
import rawpy

from .dng import compress
from .iso import StreamISO

MANIFEST = '_CDNG_IMAGE_MANIFEST.json'


def signature(s): return (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)


def inventory(source):
    paths=[]
    def visit(directory):
        for p in sorted(directory.iterdir()):
            s=p.lstat()
            if stat.S_ISLNK(s.st_mode) or not (stat.S_ISREG(s.st_mode) or stat.S_ISDIR(s.st_mode)):
                raise ValueError(f'Links and special files are unsupported: {p}')
            rel=p.relative_to(source).as_posix()
            if rel.casefold()==MANIFEST.casefold(): raise ValueError('Reserved manifest name in source')
            paths.append((rel,p,s))
            if p.is_dir(): visit(p)
    visit(source)
    return paths


def read_frame(path, expected, effort, cancel, backend):
    if cancel.is_set():raise InterruptedError('Cancelled')
    with path.open('rb') as f:
        if signature(os.fstat(f.fileno()))!=signature(expected): raise ValueError(f'Source changed: {path}')
        data=f.read()
        if signature(os.fstat(f.fileno()))!=signature(expected): raise ValueError(f'Source changed: {path}')
    t=time.perf_counter()
    out,info=compress(data,effort,cancel=cancel,backend=backend)
    # Independent LibRaw verification also catches errors in TIFF interpretation.
    with rawpy.imread(io.BytesIO(data)) as before, rawpy.imread(io.BytesIO(out)) as after:
        if not np.array_equal(before.raw_image,after.raw_image):
            raise ValueError(f'Independent RAW verification failed: {path}')
    info.update(source_sha256=hashlib.sha256(data).hexdigest(),source_size=len(data),
                seconds=time.perf_counter()-t,libraw_verified=True)
    return out,info


class HashSink:
    def __init__(self):self.hash=hashlib.sha256();self.size=0
    def write(self,b):self.hash.update(b);self.size+=len(b);return len(b)


def verify_image(path, entries, cancel, progress):
    iso=pycdlib.PyCdlib();iso.open(str(path))
    try:
        for i,entry in enumerate(entries):
            if cancel.is_set():raise InterruptedError('Cancelled')
            sink=HashSink()
            iso.get_file_from_iso_fp(sink,joliet_path='/'+entry['path'])
            if sink.size!=entry['size'] or sink.hash.hexdigest()!=entry['sha256']:
                raise ValueError('Image checksum mismatch: '+entry['path'])
            progress(dict(stage='verify',done=i+1,total=len(entries),name=entry['path']))
    finally:iso.close()


def _publish(partial,output):
    """Exclusive publication; work on filesystems without hard-link support too."""
    try:
        os.link(partial,output)
    except FileExistsError:
        raise
    except OSError:
        fd=os.open(output,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o644)
        os.close(fd)
        try:os.replace(partial,output)
        except BaseException:
            output.unlink();raise
    else:partial.unlink()


def pack(source, output, effort='balanced', workers=2, method='lossless', verify=True,
         cancel=None, progress=lambda event:None, backend='cpu'):
    source=Path(source).resolve();output=Path(output).absolute()
    if not source.is_dir():raise ValueError('Select a source folder')
    if output.suffix.lower()!='.iso':raise ValueError('Output must end in .iso')
    if output.exists():raise FileExistsError(f'Output already exists: {output}')
    if not output.parent.is_dir():raise ValueError('Output parent folder does not exist')
    resolved_output=output.resolve()
    if resolved_output.is_relative_to(source):raise ValueError('Save the image outside the source folder')
    if effort not in ('fast','balanced','max') or method not in ('lossless','store'):
        raise ValueError('Unknown compression option')
    if backend not in ('cpu','metal','cuda'):raise ValueError('Unknown compute backend')
    if backend!='cpu' and method=='lossless':
        from .gpu import get_gpu
        get_gpu(backend)  # fail before writing an image if unavailable; never silently fake GPU use
    if not 1<=workers<=8:raise ValueError('Workers must be between 1 and 8')
    cancel=cancel or threading.Event()
    paths=inventory(source)
    files=[(rel,p,s) for rel,p,s in paths if stat.S_ISREG(s.st_mode)]
    if not files:raise ValueError('Source folder is empty')
    for rel,p,s in files:
        if s.st_size>0xffffffff:raise ValueError(f'Individual file exceeds 4 GiB ISO limit: {rel}')
    partial=output.with_name(output.name+'.'+uuid.uuid4().hex[:10]+'.partial')
    entries=[];pending={};start=time.perf_counter()
    source_bytes=sum(s.st_size for _,_,s in files)
    compressed_count=0
    try:
        with partial.open('xb+') as f, concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            iso=StreamISO(f,[(r,stat.S_ISDIR(s.st_mode),s.st_mtime) for r,_,s in paths]+[(MANIFEST,False,time.time())],
                          re.sub('[^A-Z0-9_]','_',source.name.upper())[:16] or 'CDNG_IMAGE')
            dng_indices=[i for i,(r,p,s) in enumerate(files) if p.suffix.lower()=='.dng' and method=='lossless']
            next_job=iter(dng_indices)
            def submit():
                idx=next(next_job,None)
                if idx is not None:
                    _,p,s=files[idx];pending[idx]=pool.submit(read_frame,p,s,effort,cancel,backend)
            for _ in range(workers):submit()
            for i,(rel,p,s) in enumerate(files):
                if cancel.is_set():raise InterruptedError('Cancelled')
                if i in pending:
                    out,info=pending.pop(i).result();submit()
                    info.update(iso.add(rel,(out,),cancel));del out
                    if info['size']<s.st_size:compressed_count+=1
                else:
                    info=dict(codec='stored',source_size=s.st_size)
                    with p.open('rb') as inp:
                        if signature(os.fstat(inp.fileno()))!=signature(s):raise ValueError(f'Source changed: {rel}')
                        info.update(iso.add(rel,iter(lambda:inp.read(1024*1024),b''),cancel))
                        if signature(os.fstat(inp.fileno()))!=signature(s):raise ValueError(f'Source changed: {rel}')
                    info['source_sha256']=info['sha256']
                if signature(p.stat())!=signature(s):raise ValueError(f'Source changed: {rel}')
                info['path']=rel;entries.append(info)
                progress(dict(stage='compress',done=i+1,total=len(files),name=rel,
                              source_bytes=source_bytes,stored_bytes=sum(e['size'] for e in entries),
                              elapsed=time.perf_counter()-start))
            if cancel.is_set():raise InterruptedError('Cancelled')
            # Detect files added/removed/replaced while the archive was being made.
            current=inventory(source)
            if [(r,signature(s)) for r,_,s in paths] != [(r,signature(s)) for r,_,s in current]:
                raise ValueError('Source folder changed during compression; retry with stable footage')
            manifest=dict(format='CDNG Image',version=1,method=method,effort=effort,backend=backend,
                lossless_definition='Original stored RAW sample values, not byte-identical DNG files',
                metadata='Original header bytes and metadata offsets retained; only image storage layout changes',
                source_bytes=source_bytes,files=entries)
            blob=json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf-8')
            manifest_entry=dict(path=MANIFEST,**iso.add(MANIFEST,(blob,),cancel))
            image_bytes=iso.finish();os.fsync(f.fileno())
        if verify:verify_image(partial,entries+[manifest_entry],cancel,progress)
        if cancel.is_set():raise InterruptedError('Cancelled')
        _publish(partial,output)
        result=dict(output=str(output),source_bytes=source_bytes,image_bytes=image_bytes,
                    saved_fraction=1-image_bytes/source_bytes,files=len(files),
                    compressed_files=compressed_count,seconds=time.perf_counter()-start,
                    image_checksums_verified=verify,backend=backend,workers=workers)
        progress(dict(stage='done',**result));return result
    except BaseException:
        cancel.set()
        for future in pending.values():future.cancel()
        partial.unlink(missing_ok=True)
        raise
