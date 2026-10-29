#!/usr/bin/env python3
"""Publish the ISP custom page to the fpSup repo (site + git), from site/out built by build_page.py.

    build_page.py && publish_fpsup.py REPO        REPO = a checkout of ijigen/fpSup (worktrees/fpsup-merged)

The site (GitHub Pages, 1 GB) gets the page and small display thumbnails:
    REPO/fpSup/explainers/isp-custom.html + isp-custom-shots/<run>/<shot>.jpg (480 px wide)
git gets the full-size pictures and the text evidence, and the page links the full pictures to their GitHub page:
    REPO/projects/isp-lab/validation/<run>/{*.json,*.log,*.md,...} + shots/full/*.jpg
The raw evidence (evidence.tar.zst, evidence.cdngt, *.bin/raw/dng; ~52 GB, already zstd/JXL) stays local.
"""
import pathlib, re, shutil, sys

from PIL import Image

HERE = pathlib.Path(__file__).resolve().parent
VALIDATION = HERE.parent / 'validation'
PAGE = HERE / 'out' / 'isp-custom.html'
GIT_PAGE = 'https://github.com/ijigen/fpSup/blob/main/projects/isp-lab/validation'
THUMB_W, THUMB_Q = 480, 72
TEXT = ('.json', '.jsonl', '.log', '.LOG', '.md', '.txt')


def thumb(src, dst):
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        im = im.convert('RGB')
        if im.width > THUMB_W:
            im = im.resize((THUMB_W, round(im.height * THUMB_W / im.width)), Image.LANCZOS)
        im.save(dst, 'JPEG', quality=THUMB_Q, optimize=True, progressive=True)


def copy(src, dst):
    if dst.exists() and dst.stat().st_size == src.stat().st_size and dst.stat().st_mtime >= src.stat().st_mtime:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def publish(repo):
    site = repo / 'fpSup' / 'explainers'
    page = PAGE.read_text()
    used = set()

    def src(m):
        run, name = m[1], m[2]
        used.add(run)
        thumb(VALIDATION / run / 'shots' / name, site / 'isp-custom-shots' / run / name)
        return m[0]
    page = re.sub(r'src="isp-custom-shots/([^/"]+)/([^/"]+\.jpg)"', src, page)
    page = re.sub(r'href="isp-custom-shots/([^/"]+)/full/([^/"]+)"',
                  lambda m: f'href="{GIT_PAGE}/{m[1]}/shots/full/{m[2]}"', page)
    page = re.sub(r'href="isp-custom-shots/([^/"]+)/RESULTS\.md"',
                  lambda m: f'href="{GIT_PAGE}/{m[1]}/RESULTS.md"', page)
    # raw evidence is not uploaded: say so instead of a dead link
    page = re.sub(r'<a href="isp-custom-shots/[^"]+/evidence\.tar\.zst">[^<]*</a>', '原檔留在本機（未上傳）', page)
    page = re.sub(r'<a href="isp-custom-shots/[^"]+/evidence\.cdngt">[^<]*</a> · <a href="[^"]+">[^<]*</a>（[^）]*）',
                  '原檔 CDNG 留在本機（未上傳）', page)
    left = re.findall(r'(?:src|href)="(isp-custom-shots/[^"]*)"', page)
    if any(not (site / p).exists() for p in left):
        sys.exit(f'unresolved links: {[p for p in left if not (site / p).exists()][:5]}')
    page = page.replace('<header><h1>', '<header><p class="note"><a href="../research.html">← fpSup 研究</a></p><h1>', 1)
    (site / 'isp-custom.html').write_text(page)

    git = repo / 'projects' / 'isp-lab' / 'validation'
    n = 0
    for run in sorted(set(re.findall(r'<section class="case" id="([^"]+)"', page))):
        d = VALIDATION / run
        for f in d.rglob('*'):
            rel = f.relative_to(d)
            if f.is_file() and (f.suffix in TEXT and rel.parts[0] != 'push' or rel.parts[:2] == ('shots', 'full')):
                copy(f, git / run / rel)
                n += 1
    print(f'{site / "isp-custom.html"}: {len(used)} runs; {n} files under {git}')


if __name__ == '__main__':
    publish(pathlib.Path(sys.argv[1]).resolve())
