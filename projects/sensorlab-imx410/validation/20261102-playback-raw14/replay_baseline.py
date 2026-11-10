from pathlib import Path
import sys,json,struct
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]
sys.path.insert(0,str(ROOT/'projects/sensorlab-imx410/apply'))
import test_playback_entry as E
T=E.T
rows=[]
for path in sorted((HERE/'media').glob('*.DNG')):
 original=path.read_bytes()
 for bits in [12,14]:
  for num,den in [(1,1),(12,1),(19026,1000),(22478,1000),(24,1),(33478,1000),(60,1)]:
   data=bytearray(original);bp=E.entry_offset(data,0x102);struct.pack_into('<H',data,bp+8,bits)
   rp=E.entry_offset(data,0xC764);ptr=struct.unpack_from('<I',data,rp+8)[0];struct.pack_into('<ii',data,ptr,num,den)
   c=E.Parser(path,bytes(data));entry=c.entry({});en=c.w(T.OBJ+0xA8);rate=c.w(T.OBJ+0x68);prepare=c.prepare()
   rows.append(dict(source=path.name,synthetic_bits_rate=(bits,num,den),entry=entry,bit_enum=en,rate_enum=rate,prepare=prepare,config=c.configured))
(HERE/'baseline.json').write_text(json.dumps(rows,indent=2)+'\n')
print(json.dumps(rows,indent=2))
