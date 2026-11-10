# live7: crop the code from an OSD buffer dump (fbgrab.py .npy, ARGB4444) or a screenshot JPG and decode it with OpenCV.
# usage: qrdecode.py IN(.npy|.jpg) OUT_CROP.png [x y w h]   (default crop = panel 0,77,1024,454)
import sys, numpy as np, cv2
src, dst = sys.argv[1], sys.argv[2]
x, y, w, h = (int(v) for v in sys.argv[3:7]) if len(sys.argv) >= 7 else (0, 77, 1024, 454)
if src.endswith('.npy'):
    px = np.load(src)
    g = (((px >> 8 & 15) + (px >> 4 & 15) + (px & 15)) * 255 // 45).astype(np.uint8)
    g[(px >> 12) == 0] = 128
else:
    g = cv2.imread(src, cv2.IMREAD_GRAYSCALE)
crop = np.ascontiguousarray(g[y:y + h, x:x + w])
cv2.imwrite(dst, crop)
txt = cv2.QRCodeDetector().detectAndDecode(crop)[0]
print('decoded:', repr(txt))
