"""Replay copied real headers through native selection/parser/prepare.

SensorLab apply is rebuilt from sources verified equal to the archived 0.7.12
sources; it is not an exact-card full-loader test. Physical I/O, allocation,
ring creation, RTOS, configuration and decode remain declared harness models.
Ring creation is independently executed by replay_native_ring.py.
"""
from pathlib import Path
import hashlib
import json
import struct
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PROJECT = ROOT/'projects/sensorlab-imx410'
sys.path.insert(0,str(PROJECT/'apply'))
import test_playback_entry as E
T = E.T


class ActualSizeParser(E.Parser):
    def __init__(self, row):
        self.actual = row
        self.ring_requests = []
        super().__init__(ROOT/row['copy'])

    def _hook(self, mu, a, size, data):
        if a == 0xC05BDD68:
            obj, result = self.r(T.UC_ARM_REG_R0), self.r(T.UC_ARM_REG_R2)
            self.put(obj+0xA0, self.actual['file_bytes']); self.put(obj+0xA4,0)
            self.put(result+0xC,self.actual['clip_frames'])
            # Only a total-byte fixture; stream playback/decode is not executed.
            self.put(result+0x10,self.actual['file_bytes']*self.actual['clip_frames'])
            self.put(result+0x14,0)
            return self.ret(0)
        if a == 0xC05C2D10:
            self.ring_requests.append(self.r(T.UC_ARM_REG_R1))
        return super()._hook(mu,a,size,data)


if __name__ == '__main__':
    sources = {}
    for name in ('apply/ap.c','apply/ap_calc.c','apply/ap.h','core/core.c','core/core.h'):
        p = PROJECT/name
        frozen = PROJECT/'validation/20261102-hirate-followup/source-final'/name
        if not frozen.exists():
            # Header files not captured by the original bundle are fingerprinted,
            # not incorrectly claimed to have been compared.
            sources[name] = dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest(),compared=False)
        else:
            assert p.read_bytes() == frozen.read_bytes(), f'source changed: {name}'
            sources[name] = dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest(),compared=True)
    rows = json.loads((HERE/'media.json').read_text())['files']
    results = []
    for row in rows:
        assert row['full_file']
        c = ActualSizeParser(row)
        assert hashlib.sha256(c.data).hexdigest() == row['sha256']
        admitted = c.entry({})
        prepared = c.prepare()
        if c.ring_requests:
            assert c.ring_requests == [row['file_bytes']]
        if c.configured:
            assert c.configured[0]['params'][1:3] == row['tags']['crop_size']
        result = dict(file=Path(row['path']).name,sha256=row['sha256'],
                      rate=row['tags']['frame_rate'],selected=admitted,prepared=prepared,
                      native_rate_enum=c.w(T.OBJ+0x68),ring_file_bytes=c.ring_requests,
                      configuration=c.configured, playback_state=c.v1(),
                      native_shape=[c.w(T.OBJ+x) for x in (0x54,0x58,0x98,0x9C,0xA8,0xAC)],
                      tag_reads=c.tagcalls)
        results.append(result)
        print(json.dumps(result),flush=True)
    (HERE/'native-header-result.json').write_text(json.dumps(dict(
        sources=sources,cases=results,hardware_tested=False,
        limitations=__doc__),indent=2)+'\n')
