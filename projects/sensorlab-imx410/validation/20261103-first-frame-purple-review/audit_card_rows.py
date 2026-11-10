"""Offline check of four archived clips; no camera access."""
import pathlib,json,re,hashlib
import tifffile,numpy as np
root=pathlib.Path(__file__).resolve().parent.parent/'20261103-first-frame-purple'/'card'
result=[]
for clip in ['A001_012','A001_013','A001_014','A001_015']:
 files=sorted(root.glob(clip+'*.DNG'))
 arrays=[]; blobs=[]; offsets=[]; specs=[]
 for f in files:
  data=f.read_bytes(); blobs.append(data)
  with tifffile.TiffFile(f) as tf:
   p=tf.pages[0]; arrays.append(p.asarray().astype(np.int32)); offsets.append(p.dataoffsets[0])
   specs.append(dict(file=str(f),sha256=hashlib.sha256(data).hexdigest(),shape=list(arrays[-1].shape),BitsPerSample=p.bitspersample,Compression=int(p.compression),dataoffsets=list(p.dataoffsets),databytecounts=list(p.databytecounts)))
 a,b,c=arrays
 assert specs[0]['BitsPerSample'] == 12 and specs[0]['Compression'] == 1
 assert a.shape == b.shape == c.shape
 rowbytes=a.shape[1]*specs[0]['BitsPerSample']//8
 row=blobs[0][offsets[0]:offsets[0]+rowbytes]
 x=np.frombuffer(row,dtype=np.uint8).reshape(-1,3).astype(np.uint16)
 manual=np.column_stack(((x[:,0]<<4)|(x[:,1]>>4),((x[:,1]&15)<<8)|x[:,2])).reshape(-1)
 errors=[]
 for aa,bb in [(a,b),(b,c)]:
  A,B=aa[200:-200,200:-200],bb[200:-200,200:-200]
  err={str(d):float(np.abs(A[max(d,0):A.shape[0]+min(d,0)]-B[max(-d,0):B.shape[0]-max(d,0)]).mean()) for d in range(-3,4)}
  errors.append(dict(dy=int(min(err,key=err.get)),errors=err))
 markers={f'FF{m:02X}':[x.start() for x in re.finditer(re.escape(bytes([255,m])),row)] for m in [0xd8,0xc3,0xc4,0xda,0xd9]}
 segments=[]
 for key in ['FFC4','FFDA']:
  for pos in markers[key]:
   length=int.from_bytes(row[pos+2:pos+4],'big')
   segments.append(dict(marker=key,relative_offset=pos,declared_length=length,hex=row[pos:pos+min(length+2,50)].hex()))
 result.append(dict(clip=clip,frames=specs,rowbytes=rowbytes,manual_decode_matches_tifffile=bool(np.array_equal(manual,a[0])),
   shifts_1_vs_2_and_2_vs_3=errors,first_three_row_means=a[:3].mean(axis=1).tolist(),frame2_first_row_mean=float(b[0].mean()),
   first_row_quantiles=np.quantile(a[0],[0,.05,.5,.95,1]).tolist(),first_row_unique=int(len(np.unique(a[0]))),first_row_saturated=int((a[0]==4095).sum()),
   first_row_markers=markers,marker_details=segments,first_row_hex128=row[:128].hex(' '),
   first_row_mae_vs_frame2_first=float(np.abs(a[0]-b[0]).mean()),first_row_mae_vs_frame2_last=float(np.abs(a[0]-b[-1]).mean()),
   second_row_mae_vs_frame2_first=float(np.abs(a[1]-b[0]).mean()),last_row_mae_vs_frame2_penultimate=float(np.abs(a[-1]-b[-2]).mean()),
   trailerbytes=len(blobs[0])-offsets[0]-specs[0]['databytecounts'][0]))
pathlib.Path(__file__).resolve().with_name('card-row0-audit.json').write_text(json.dumps(result,indent=2))
for r in result:
 print(json.dumps({k:r[k] for k in ['clip','rowbytes','manual_decode_matches_tifffile','shifts_1_vs_2_and_2_vs_3','first_three_row_means','frame2_first_row_mean','first_row_quantiles','first_row_unique','first_row_saturated','marker_details','trailerbytes']}))
