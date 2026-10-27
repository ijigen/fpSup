import argparse
import json
from .packer import pack

def main():
    ap=argparse.ArgumentParser(description='Compress CinemaDNG directly into a mountable ISO; originals remain untouched.')
    ap.add_argument('source');ap.add_argument('output')
    ap.add_argument('--effort',choices=('fast','balanced','max'),default='balanced')
    ap.add_argument('--method',choices=('lossless','store'),default='lossless')
    ap.add_argument('--workers',type=int,default=2)
    ap.add_argument('--backend',choices=('cpu','metal','cuda'),default='cpu')
    ap.add_argument('--skip-image-checksums',action='store_true')
    a=ap.parse_args()
    try:
        result=pack(a.source,a.output,a.effort,a.workers,a.method,not a.skip_image_checksums,
                    progress=lambda e: print(json.dumps(e,ensure_ascii=False),flush=True),backend=a.backend)
    except Exception as e:ap.exit(1,str(e)+'\n')
