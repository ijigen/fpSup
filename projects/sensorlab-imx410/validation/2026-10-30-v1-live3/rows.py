"""Dump the SensorLab private menu lists (struct slm_state rows) -- read only."""
import sys, json
from sl import op, words, MENU, HERE
a = op(27); h = words(a, 23); out = {}
for L in range(3):
    n = h[8 + L]; rows = []
    for i in range(min(n, 50)):
        base = a + 92 + (L * 50 + i) * 48
        w = words(base, 12)
        t = b''.join(x.to_bytes(4, 'little') for x in w[4:]).split(b'\0')[0].decode('latin1')
        rows.append(f"{'' if w[2] else '~'}{'*' if w[3] else ''}{t}")
    out[L] = dict(count=n, cur=h[11 + L], rows=rows)
print(json.dumps(out, ensure_ascii=False))
open(HERE / 'results.jsonl', 'a').write(json.dumps(dict(tag=sys.argv[-1], rows=out), ensure_ascii=False) + '\n')
