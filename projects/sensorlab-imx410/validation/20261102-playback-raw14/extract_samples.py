from pathlib import Path
import hashlib,json,subprocess,tarfile
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]
(HERE/'media').mkdir(exist_ok=True);rows=[]
for case in ['20261028-p6r14-FHD60_Caf537419','20261027-rep14-FHD60_M22']:
 d=ROOT/'projects/isp-lab/validation'/case
 manifest=json.loads((d/'ARCHIVE.json').read_text())
 archive=next(p for p in (d/'evidence.tar.zst',d/'evidence.side.tar.zst') if p.exists())
 target=sorted(n for n in manifest['files'] if n.startswith('push/cdng_') and n.endswith('.bin'))[0]
 if archive.name=='evidence.side.tar.zst':
  # Repacked evidence has a separate manifest; original ARCHIVE.json hashes
  # belong to the retired complete archive, not the side archive.
  restored=HERE/'restored'/target
  if not restored.exists():
   subprocess.run(['python3','-B',str(ROOT/'projects/isp-lab/host/evidence_jxl.py'),'unpack',str(d),str(HERE/'restored'),target],check=True)
  data=restored.read_bytes();want=manifest['files'][target]
  assert len(data)==want['bytes'] and hashlib.sha256(data).hexdigest()==want['sha256']
  prefix=data[:131072];dst=HERE/'media'/(case+'.DNG');dst.write_bytes(prefix)
  rows.append(dict(case=case,archive=str(archive),archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),repack_manifest=str(d/'EVIDENCE.json'),member=target,original_bytes=len(data),original_sha256=want['sha256'],file=str(dst),prefix_bytes=len(prefix),prefix_sha256=hashlib.sha256(prefix).hexdigest()))
  continue
 assert hashlib.sha256(archive.read_bytes()).hexdigest()==manifest['archive']['sha256']
 proc=subprocess.Popen(['zstd','-dc',str(archive)],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
 try:
  with tarfile.open(fileobj=proc.stdout,mode='r|') as t:
   for member in t:
    if member.name.lstrip('./')!=target:continue
    fp=t.extractfile(member);h=hashlib.sha256();prefix=b'';count=0
    while True:
     b=fp.read(1024*1024)
     if not b:break
     h.update(b);count+=len(b)
     if len(prefix)<131072:prefix+=b[:131072-len(prefix)]
    want=manifest['files'][target];assert count==want['bytes'] and h.hexdigest()==want['sha256']
    dst=HERE/'media'/(case+'.DNG');dst.write_bytes(prefix)
    rows.append(dict(case=case,archive=str(archive),archive_sha256=manifest['archive']['sha256'],member=target,original_bytes=count,original_sha256=h.hexdigest(),file=str(dst),prefix_bytes=len(prefix),prefix_sha256=hashlib.sha256(prefix).hexdigest()))
    break
 finally:
  proc.stdout.close();proc.terminate();proc.wait()
assert len(rows)==2
(HERE/'media.json').write_text(json.dumps(rows,indent=2)+'\n');print(json.dumps(rows,indent=2))
