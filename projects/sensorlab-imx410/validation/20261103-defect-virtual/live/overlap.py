import sys, glob, json, numpy as np, tifffile
sys.path.insert(0, '.')
from hot import hot
def stable(d):
    f = sorted(glob.glob(d + '/*.DNG')); return hot(f[1])[0] & hot(f[2])[0]
c, b, a = stable('c_v0724'), stable('b_off'), stable('a2_new')
print(json.dumps(dict(c=len(c), b=len(b), c_and_b=len(c & b), a=len(a), a_in_c=len(a & c), c_removed_by_a=len(c - a))))
