#!/usr/bin/env python3
"""Offline first-row/row-phase audit. Reads archived DNGs only; never imports camera tools."""
import argparse, pathlib, json, hashlib, re
import numpy as np
import tifffile
ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument('--source', type=pathlib.Path, default=pathlib.Path(__file__).resolve().parent.parent / '20261103-first-frame-purple')
ap.add_argument('--output', type=pathlib.Path, default=pathlib.Path(__file__).resolve().with_name('row0-audit.json'))
args = ap.parse_args()
ROOT = args.source.resolve()
OUT = args.output.resolve()
assert not OUT.is_relative_to(ROOT), 'Keep the archived evidence unchanged'
records=[]
queries=[]

def structured_segment(marker, segment):
    """Check marker payload structure, not just an FF byte pair."""
    payload = segment[4:]
    if marker == 'FFDA':
        return bool(payload) and 1 <= payload[0] <= 4 and len(payload) == 4 + 2*payload[0]
    pos = 0
    while pos < len(payload):
        if pos + 17 > len(payload) or payload[pos] >> 4 > 1 or payload[pos] & 15 > 3:
            return False
        count = sum(payload[pos+1:pos+17])
        if not 0 < count <= 256:
            return False
        pos += 17 + count
    return pos == len(payload) and pos > 0

for d in sorted((ROOT/'bus').glob('t*')):
    files=sorted(d.glob('*.DNG'))
    assert len(files) == 2, (d, len(files))
    first, second=files
    fb=first.read_bytes(); sb=second.read_bytes()
    with tifffile.TiffFile(first) as tf:
        p=tf.pages[0]; a=p.asarray().astype(np.int32)
        off=p.dataoffsets[0]; count=p.databytecounts[0]; bps=p.bitspersample; h=p.imagelength; w=p.imagewidth
        compression=int(p.compression)
        assert bps == 12 and compression == 1 and len(p.dataoffsets) == 1
        rowbytes=w*bps//8; row=fb[off:off+rowbytes]
        assert count >= rowbytes*h and off+count <= len(fb)
    with tifffile.TiffFile(second) as tf:
        p=tf.pages[0]; b=p.asarray().astype(np.int32)
        so=p.dataoffsets[0]; sc=p.databytecounts[0]
        assert a.shape == b.shape
        header=sb[so:so+128]
    # Independent packed12 decode, separate from TIFF codec.
    packed=np.frombuffer(row,dtype=np.uint8).reshape(-1,3).astype(np.uint16)
    manual=np.column_stack(((packed[:,0]<<4)|(packed[:,1]>>4), ((packed[:,1]&15)<<8)|packed[:,2])).reshape(-1)
    A=a[200:-200,200:-200]; B=b[200:-200,200:-200]
    errors={str(dy):float(np.abs(A[max(dy,0):A.shape[0]+min(dy,0)]-B[max(-dy,0):B.shape[0]-max(dy,0)]).mean()) for dy in range(-3,4)}
    dy=int(min(errors,key=errors.get))
    markers={f'FF{m:02X}':[x.start() for x in re.finditer(re.escape(bytes([255,m])),row)] for m in [0xd8,0xc3,0xc4,0xda,0xd9]}
    segments=[]
    for key in ['FFC4','FFDA']:
        for q in markers[key]:
            length=int.from_bytes(row[q+2:q+4],'big')
            if 2<=length<=256:
                seg=row[q:q+length+2]
                if len(seg) != length+2 or not structured_segment(key, seg):
                    continue
                segments.append(dict(marker=key,relative_offset=q,absolute_offset=off+q,segment_length=len(seg),hex=seg.hex(),equals_frame2_at_same_offset=seg==header[q:q+len(seg)]))
    for pos in [128,512,2048]:
        queries.append(dict(take=d.name,position=pos,bytes=row[pos:pos+64],matches=[]))
    rec=dict(take=d.name,first=str(first),second=str(second),sha256_first=hashlib.sha256(fb).hexdigest(),sha256_second=hashlib.sha256(sb).hexdigest(),
      ImageWidth=w,ImageLength=h,BitsPerSample=bps,Compression=compression,StripOffsets=[off],StripByteCounts=[count],rowbytes=rowbytes,filesize=len(fb),trailerbytes=len(fb)-off-count,
      strip_padding_bytes=count-rowbytes*h,pixel_end_to_eof_bytes=len(fb)-off-rowbytes*h,
      raw12_manual_equals_tifffile=bool(np.array_equal(manual,a[0])),dy=dy,shift_errors=errors,
      first_two_row_means=a[:2].mean(axis=1).tolist(),second_first_row_mean=float(b[0].mean()),first_row_range=[int(a[0].min()),int(a[0].max())],
      first_row_jpeg_markers=markers,valid_header_segments=segments,
      lastrow_mae_vs_frame2_last=float(np.abs(a[-1]-b[-1]).mean()),lastrow_mae_vs_frame2_penultimate=float(np.abs(a[-1]-b[-2]).mean()),
      first_row_hex_128=row[:128].hex(' '))
    records.append(rec)
# Search raw-row entropy samples across ALL archived DNG bytes, including same-file headers/previews,
# same-file other rows, same-take frame2, other takes and card originals. Exclude only source row itself.
for f in sorted(ROOT.rglob('*.DNG')):
    data=f.read_bytes()
    for q in queries:
        needle=q['bytes']; pos=0
        while (pos:=data.find(needle,pos))!=-1:
            own=next(r for r in records if r['take']==q['take'])
            if not (str(f)==own['first'] and own['StripOffsets'][0] <= pos < own['StripOffsets'][0]+own['rowbytes']):
                q['matches'].append(dict(file=str(f),offset=pos))
            pos+=1
for q in queries: q['hex']=q.pop('bytes').hex()
report=dict(records=records,entropy64byte_queries=queries,
 summary=dict(takes=len(records),purple=sum(r['dy']%2 for r in records),good=sum(r['dy']%2==0 for r in records),
   purple_with_any_structured_jpeg_header=[r['take'] for r in records if r['dy']%2 and r['valid_header_segments']],
   purple_with_structured_jpeg_headers=[r['take'] for r in records if r['dy']%2 and any(s['equals_frame2_at_same_offset'] for s in r['valid_header_segments'])],
   entropy_queries_with_any_nonself_match=[dict(take=q['take'],position=q['position'],matches=q['matches']) for q in queries if q['matches']]))
report['source'] = str(ROOT)
report['analysis_script_sha256'] = hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()
OUT.write_text(json.dumps(report,indent=2) + '\n')
print(json.dumps(report['summary'],indent=2))
print('Report:',OUT)
for r in records:
 print(r['take'], 'dy',r['dy'],'row0',round(r['first_two_row_means'][0],2),'row1',round(r['first_two_row_means'][1],2),'trailer',r['trailerbytes'],
       'tail MAE same/-1',round(r['lastrow_mae_vs_frame2_last'],3),round(r['lastrow_mae_vs_frame2_penultimate'],3),
       'jpeg',[(s['marker'],s['relative_offset'],s['equals_frame2_at_same_offset']) for s in r['valid_header_segments']])
