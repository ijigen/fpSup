# live7: read the 1024x682 ARGB4444 main OSD layer buffers (layer 0xC3824FA8 -> buffer descs C38D6DB0/CC/E8, base at desc+4)
# with putfile.read_bulk (read_direct's MEM1 window is refused for these addresses) and save .npy + a grey PNG
# (ARGB4444 alpha-blended over mid grey) for each. usage: fbgrab.py OUTDIR [i ...]
import sys, numpy as np
sys.path.insert(0, '/Users/dido/Developer.localized/SIGMAfp_re/fpSup/fp_usb_shell')
import putfile
BASES = (0xC6200180, 0xC6355180, 0xC64AA180)
out = sys.argv[1]
idx = [int(x) for x in sys.argv[2:]] or [0, 1, 2]
for i in idx:
    raw = putfile.read_bulk(BASES[i], 1024 * 682 * 2)
    px = np.frombuffer(raw, '<u2').reshape(682, 1024)
    np.save(f'{out}/fb{i}.npy', px)
    a = (px >> 12 & 15) / 15.0; g = ((px >> 8 & 15) + (px >> 4 & 15) + (px & 15)) / 45.0
    img = (255 * (a * g + (1 - a) * 0.5)).astype(np.uint8)
    try:
        from PIL import Image; Image.fromarray(img).save(f'{out}/fb{i}.png')
    except ImportError:
        pass
    print(hex(BASES[i]), 'white', int((px == 0xFFFF).sum()), 'black', int((px == 0xF000).sum()), 'zero', int((px == 0).sum()))
