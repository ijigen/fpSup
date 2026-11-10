import math
# (label, kind, iso, bits, unmerged1x1, measured_bpp)
D=[("FHD testcard-h","cam",100,12,0,4.35),("FHD testcard-k","cam",100,12,0,4.13),("FHD testcard-l","cam",100,12,0,4.21),
("FHD testcard-o","cam",100,12,0,4.20),("FHD testcard-g","cam",100,12,0,3.11),("OG3K testcard-s","cam",100,12,0,3.32),
("OG3K A001_267","cam",100,12,0,4.27),("FHD A001_020","cam",500,12,0,2.57),("OG3K A001_022","cam",500,12,0,2.63),
("FHD stopfx","cam",3200,12,0,2.62),("FHD A001_044","cam",3200,12,0,3.50),("FHD A001_059","cam",3200,12,0,4.04),
("FHD A001_227","cam",3200,12,0,3.67),("OG3K A001_228","cam",3200,12,0,4.23),("OG3K reslab3k","cam",3200,12,0,3.16),
("FHD A001_002","cam",4000,12,0,3.88),("FHD A001_009","cam",4000,12,0,3.53),("M12 1008x672","cam",4000,12,0,3.34),
("FHD early-dng","cam",6400,12,0,2.98),("M12 1008x672","cam",6400,12,0,2.75),
("6K still 14b","still",100,14,1,6.75),("6K still 14b","still",800,14,1,8.40),("6K still 14b","still",1250,14,1,7.53),("6K still 14b","still",2000,14,1,7.72),
("FHD A001_083 host","host",800,12,0,4.48),("FHD A001_002 host","host",800,12,0,5.00),("UHD A001_043 host","host",800,12,0,2.60),
("lab FHD iso100-800","sim",100,12,0,4.48),("lab FHD iso2500","sim",2500,12,0,6.80),("lab FHD iso3200","sim",3200,12,0,7.16),
("dark FHD iso2500","sim",2500,12,0,2.98),("dark FHD iso6400","sim",6400,12,0,4.73),("OG2K 3x3 iso100","sim",100,12,0,4.44),
("UHD 3872 iso100","sim",100,12,0,2.72),("FHD native12 iso500","sim",500,12,0,2.76),("FHD native10 iso500","sim",500,10,0,2.60)]
A=4.7;M1=1.5
def pred(iso,b,u): return min(b, A+0.5*math.log2(max(iso,100)/100)+(b-12)+M1*u)
rows=[]
for l,k,iso,b,u,m in D:
    p=pred(iso,b,u); rows.append((l,k,iso,b,u,m,p,(p-m)/m))
    print(f"| {l} | {k} | {iso} | {b} | {'1x1' if u else 'merged/scaled'} | {m:.2f} | {p:.2f} | {100*(p-m)/m:+.0f}% |")
e=[r[7] for r in rows]; print('min',min(e),'max',max(e))
import statistics
for k in ("cam","still","host","sim"):
    ek=[r[7] for r in rows if r[1]==k]; print(k,len(ek),'median %+.0f%%'%(100*statistics.median(ek)),'min %+.1f%%'%(100*min(ek)))
