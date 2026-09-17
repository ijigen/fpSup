#!/usr/bin/env python3
"""Generate every published image from the one drawn file in assets/src/.

    ./tools/build_assets.py            rewrite assets/
    ./tools/build_assets.py --check    fail if anything is stale (this is what CI runs)

The source is a 524x568 PNG with an opaque near-white background — a scan of a
drawing, not a vector, and there is no larger original. Nothing here enlarges
it: the hero shows it at 262 CSS px (crisp at 2x), the icons are reductions,
and the social card is a *composition* that places the artwork at 88% on a
1200x630 canvas rather than blowing it up.

Two things the source needs before it can go on the page:

  * **The white has to come out.** `sips` reports hasAlpha: yes, but the alpha
    channel is 255 everywhere — the background is opaque #FEFEFE. On the dark
    palette that is a white slab around the logo. `knockout()` floods the
    border-connected white, dilates into the brush's antialiased edge, and
    rebuilds those pixels as black-with-alpha, which is what a black brush over
    transparency should have been in the first place.
  * **418 KB is too heavy.** The whole front page is 10 KB of HTML, and the
    first thing a phone arriving from YouTube waits for should not be forty
    times that. WebP q88 is 35 KB and holds up against the PNG side by side.

Icons split at the wordmark, because the two jobs want opposite things. The
favicon is a crop of the face: at 16 px a bright yellow tile is picked out of a
tab strip, while the full logo reduces to a dark muddy square and `fpSup.` to
mush. The touch icon keeps the whole frame and the wordmark, which is legible
at the 180 px iOS draws it at, over the paper colour because iOS composites
transparency onto white anyway.
"""
import pathlib, shutil, subprocess, sys, tempfile, urllib.request
from collections import deque

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
except ImportError:
    raise SystemExit('  needs Pillow: python3 -m pip install --user Pillow')

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
ASSETS = ROOT / 'assets'
SOURCE = ASSETS / 'src' / 'fpsup-logo-source.png'

# Sampled off the artwork, not picked by eye — see tools/README or the site's
# --sig. Black 27%, white 24%, yellow 21%, and the red the wordmark's "Sup."
# and the eye are drawn in.
RED = (0xE0, 0x38, 0x58)
PAPER = (0xF2, 0xF1, 0xED)
INK = (0x17, 0x1B, 0x1F)
DIM = (0x5D, 0x65, 0x70)

# The social card's copy. It has three jobs and one glance to do them in: say
# what you get, say it is reversible, say which camera. Version numbers stay
# out — a YouTube video still sends people here in two years and the table on
# the page is generated, so it is the thing allowed to name a version.
OG_HEAD = ['Open gate 3:2', 'on the SIGMA fp']
OG_BODY = ['Full-sensor 3024×2010 recording and Gyroflow',
           'motion data, from one file on the SD card.']
OG_FOOT = 'RAM only  ·  Firmware Ver.5.02  ·  fp, not fp L'

PLEX = {600: 'zYXGKVElMYYaJe8bpLHnCwDKr932-G7dytD-Dmu1swZSAXcomDVmadSDNF5zAA.ttf',
        400: 'zYXGKVElMYYaJe8bpLHnCwDKr932-G7dytD-Dmu1swZSAXcomDVmadSD6llzAA.ttf'}
FALLBACK = ['/System/Library/Fonts/Supplemental/Arial Bold.ttf',
            '/System/Library/Fonts/Supplemental/Arial.ttf']


def font(weight, size, cache):
    """IBM Plex Sans, the face the page itself loads. Cached, then fallback."""
    p = cache / f'plex_{weight}.ttf'
    if not p.exists():
        try:
            url = 'https://fonts.gstatic.com/s/ibmplexsans/v23/' + PLEX[weight]
            with urllib.request.urlopen(url, timeout=20) as r:
                p.write_bytes(r.read())
        except Exception:
            f = FALLBACK[0 if weight >= 600 else 1]
            print(f'  ! no network for IBM Plex {weight}, falling back to {f}')
            return ImageFont.truetype(f, size)
    return ImageFont.truetype(str(p), size)


def knockout(im):
    """Border-connected white becomes transparent; the brush edge survives it.

    A plain "white -> alpha 0" would eat the white inside the drawing (the `fp`
    of the wordmark, the bandage) and leave a hard sawtooth along the frame. So
    the white is found by flooding in from the border, dilated by 3 px to take
    in the antialiased transition, and every pixel in that band is rebuilt as
    black at an alpha read off its luminance.
    """
    im = im.convert('RGBA')
    W, H = im.size
    px = im.load()

    outside = bytearray(W * H)
    q = deque()

    def push(x, y):
        i = y * W + x
        if not outside[i]:
            r, g, b, _ = px[x, y]
            if min(r, g, b) > 228:
                outside[i] = 1
                q.append((x, y))

    for x in range(W):
        push(x, 0)
        push(x, H - 1)
    for y in range(H):
        push(0, y)
        push(W - 1, y)
    while q:
        x, y = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < W and 0 <= ny < H:
                push(nx, ny)

    band = Image.frombytes('L', (W, H), bytes(b * 255 for b in outside))
    band = band.filter(ImageFilter.MaxFilter(7)).load()

    hi, lo = 232, 40           # full white -> clear, near-black -> solid
    out = im.copy()
    op = out.load()
    for y in range(H):
        for x in range(W):
            if band[x, y]:
                r, g, b, _ = px[x, y]
                lum = (r * 299 + g * 587 + b * 114) // 1000
                a = 0 if lum >= hi else 255 if lum <= lo else int(255 * (hi - lum) / (hi - lo))
                op[x, y] = (0, 0, 0, a)
    return out.crop(out.getbbox())


def social(logo, cache):
    """1200x630 for the unfurl on Discord, Reddit and anywhere else it is pasted.

    Paper rather than the dark palette: the artwork's own frame is black, and a
    light card is the one that reads as an engineering page in both a light
    Reddit and a dark Discord.
    """
    W, H = 1200, 630
    card = Image.new('RGB', (W, H), PAPER)
    d = ImageDraw.Draw(card)

    h = 440                                   # 88% of the artwork — never above 100
    w = round(logo.width * h / logo.height)
    art = logo.resize((w, h), Image.LANCZOS)
    card.paste(art, (78, (H - h) // 2), art)

    x = 78 + w + 66
    d.line([(x, 150), (x, 150 + 54)], fill=RED, width=5)

    y = 138
    f = font(600, 55, cache)
    for line in OG_HEAD:
        d.text((x + 26, y), line, font=f, fill=INK)
        y += 66
    y += 26
    f = font(400, 25, cache)
    for line in OG_BODY:
        d.text((x + 26, y), line, font=f, fill=DIM)
        y += 36
    d.text((x + 26, 446), OG_FOOT, font=font(400, 22, cache), fill=RED)
    return card


def build(out):
    src = Image.open(SOURCE)
    logo = knockout(src)
    cache = pathlib.Path(tempfile.gettempdir()) / 'fpsup-fonts'
    cache.mkdir(exist_ok=True)

    logo.save(out / 'fpsup-logo.png')
    logo.save(out / 'fpsup-logo.webp', 'WEBP', quality=88, method=6)

    # Favicon: the face alone. The wordmark is unreadable below ~64 px and only
    # darkens the tile.
    fw = int(logo.width * 0.72)
    face = logo.crop((int(logo.width * 0.10), int(logo.height * 0.02),
                      int(logo.width * 0.10) + fw, int(logo.height * 0.02) + fw))
    for s in (16, 32, 180):
        face.resize((s, s), Image.LANCZOS).save(out / f'favicon-{s}.png')
    face.resize((32, 32), Image.LANCZOS).save(
        out / 'favicon.ico', sizes=[(16, 16), (32, 32)])

    # Touch icon: whole frame, wordmark and all, on paper — iOS flattens alpha.
    side = max(logo.size)
    touch = Image.new('RGB', (side, side), PAPER)
    touch.paste(logo, ((side - logo.width) // 2, (side - logo.height) // 2), logo)
    touch.resize((180, 180), Image.LANCZOS).save(out / 'apple-touch-icon.png')

    social(logo, cache).save(out / 'og.png')
    social(logo, cache).save(out / 'og.jpg', quality=90, optimize=True)


def main():
    check = '--check' in sys.argv
    if not SOURCE.exists():
        raise SystemExit(f'  missing {SOURCE.relative_to(ROOT)}')

    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        build(tmp)
        made = sorted(p.name for p in tmp.iterdir())
        stale = [n for n in made
                 if not (ASSETS / n).exists()
                 or (ASSETS / n).read_bytes() != (tmp / n).read_bytes()]
        if not check:
            for n in made:
                shutil.copy2(tmp / n, ASSETS / n)
        for n in made:
            kb = (tmp / n).stat().st_size / 1024
            print(f'  {n:<22} {kb:7.1f} KB{"   STALE" if n in stale and check else ""}')

    if check and stale:
        print('\n  STALE: ' + ', '.join(stale) +
              ' — run tools/build_assets.py and commit', file=sys.stderr)
        return 1
    print('\n  ' + ('up to date' if check else f'wrote {len(made)} files to assets/'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
