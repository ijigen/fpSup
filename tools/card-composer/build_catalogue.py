#!/usr/bin/env python3
"""Regenerate the composer's card catalogue from real build outputs.

    ./build_catalogue.py            -> index.html

The page composes cards from pre-built section blobs, so it needs no assembler
and no firmware image at run time.  Two facts make that legitimate:

  * `VSHL.BIN` is a plain container -- "VBIN", a count, the entry, the payload
    length, then one (dest, len) record per section and the blobs 4-byte
    aligned.  Firmware/pool sections are independent; destination zero is the
    loader-owned stage2 helper and is canonicalized when cards are combined.
  * `AutoRun.txt` does not depend on the section list *or the entry*.  Measured:
    the OG3K-only card (entry 0) and the OG3K+gyro card (entry 0xC072E064) have
    the same 135 commands and differ only in three banner lines.  The loader
    reads the entry out of VSHL.BIN's header, not out of AutoRun.

**Cards, not modules.**  An earlier version of this treated the shipped cards as
subsets of one another and it was wrong: the OG3K-only card is built through a
different loader path.  It carries no park stub, no F_WRITE prologue restore and
no entry section, and it has a pool section the merged card does not.  Filtering
one shipped card's records can produce another only by accident.  So each
shipped card is carried whole, and combining them is an explicit merge with the
same checks the build scripts run.

To add a card: drop its directory in CARDS and run this.  Data, not code.
"""
import base64, json, pathlib, re, shutil, struct, subprocess, sys, tempfile, zipfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
GYRO = ROOT / 'fpSup' / 'gyro'

PARK_AT, F_WRITE_AT = 0xC072EFB4, 0xC03660E8
# build_base_card.py passes these two as `--also`, not `--also-bin`, so its own
# check() never sees them -- and the cave-bounds rule must not be applied to
# them either.  The park stub lives *at* PARK_AT, so "must not run past PARK_AT"
# is a guaranteed false failure on it.  That is exactly what went wrong first time.
FIXED = {PARK_AT: 'park stub', F_WRITE_AT: 'fwrite prologue restore'}
LABELS = {
    0xC072E064: 'gsup_entry',  0xC072E200: 'accel', 0xC072E300: 'drain',
    0xC072E4E0: 'start',       0xC072E620: 'stop',  0xC072E6A0: 'mode',
    0xC072EC38: '→stream_claim',  0xC072EC3C: '→stream_commit',
    0xC072EC40: '→gyro_drain',    0xC072EC44: '→stream_flush',
    0xC072EC60: 'space',       0x00044000: 'gcsv_task (pool)',
}

# The AutoRun belongs to the loader, not to the card, and there is more than one
# loader.  Which one a card needs is decided by whether it carries the shell:
#
#   plain      loader.S with NOTASK=1.  The file read happens in the borrowed
#              dispatcher task, once, at boot.  236 bytes.
#   shell      loader.S without it: 356 bytes, because the worker blocks in
#              FN_WAIT on the endpoint and cannot run in a borrowed callback --
#              it needs a task of its own.  Plus 68 bytes zeroing the worker's
#              state (a warm restart does not clear RAM) and the interface-class
#              patch, without which the host's PTP stack claims interface 0.
#   shellpush  the same, plus the six EP 0x83 patches.
#
# These are carried whole.  Splitting an AutoRun into optional blocks would be
# rebuilding build_autorun.py's option matrix in JavaScript, and that matrix
# grows; a whole template per configuration does not rot.
# The three AutoRun templates come straight from build_autorun.py.  They are a
# property of the *loader*, and the loader has exactly three configurations:
#
#   --no-shell        NOTASK=1.  236-byte loader, the read happens in the
#                     borrowed dispatcher task.  135 commands.
#   --no-ep-patches   the task-creating loader plus the interface-class patch,
#                     without the six EP 0x83 writes.  189 commands.
#   (neither)         the same plus the push patches.  195 commands.
#
# An earlier version of this file lifted two of them out of merged cards that
# had been built and left in the tree, which is why a merge tool appeared to
# depend on merged cards.  It never did: the cards happened to be the first
# place each loader configuration could be found.  Verified identical.
TEMPLATE_FLAGS = {'plain': ['--no-shell'], 'shell': ['--no-ep-patches'], 'shellpush': []}


def build_templates():
    """Build each AutoRun template and the current canonical stage2 helper."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix='tpl-'))
    out, stage2 = {}, None
    for name, flags in TEMPLATE_FLAGS.items():
        f = tmp / f'{name}.txt'
        r = subprocess.run([sys.executable,
                            str(ROOT / 'fpSup' / 'fp_usb_shell' / 'build_autorun.py'),
                            '--loader', *flags, '--banner', '@@BANNER@@',
                            '--vshl-entry', '0xC072E064', '--out', str(f)],
                           capture_output=True, text=True)
        if r.returncode:
            sys.stderr.write(r.stdout + r.stderr)
            raise SystemExit(f'could not build the {name} template')
        out[name] = f.read_text('utf-8').split('# pad -- see PAD_TO')[0]
        _, records = parse((tmp / 'VSHL.BIN').read_bytes())
        helpers = [blob for address, blob in records if address == 0]
        if len(helpers) != 1:
            raise SystemExit(f'{name} loader emitted {len(helpers)} stage2 helpers')
        if stage2 is None:
            stage2 = helpers[0]
        elif helpers[0] != stage2:
            raise SystemExit(f'{name} loader emitted a different stage2 helper')
    shutil.rmtree(tmp, ignore_errors=True)
    return out, stage2


# The merge checks build from the newest released OG3K artifact, not from the
# mutable research worktree.  A release can deliberately freeze a
# camera-tested payload while the source tree moves on to the next experiment.
# build_base_card.py is an independent combiner and safety checker: feeding it
# the released sections proves that the browser merge reproduces the same
# gyro+OG3K and shell+gyro+OG3K cards without rebuilding OG3K.
REFS = {}
NATIVE_UI_SECTIONS = {
    0xC0732700,  # runtime state
    0xC0732C84,  # UI code + selected-record table
    0xC0793060,  # private NBR pack
    0xC05E5B58,  # string resolver hook
    0xC05E84D8,  # NBR loader hook
    0xC05E6400,  # NBU record hook
}
NATIVE_UI_RECORDS = 360


def refs(product='og3k'):
    """Independently rebuild <product>+gyro so the browser merge has something to
    be equal to.  Parametrised because OG2K is a second open-gate card built the
    same way: shipping it without the check OG3K gets would be the one difference
    that matters."""
    if product in REFS:
        return REFS[product]
    tmp = pathlib.Path(tempfile.mkdtemp(prefix=f'{product}ref-'))
    og3k = latest(product)
    og_entry, og_records = parse((og3k / 'VSHL.BIN').read_bytes())
    if og_entry != 0:
        raise SystemExit(f'{og3k.name} unexpectedly carries an entry point')
    helpers = [(address, blob) for address, blob in og_records
               if address < 0x40000000]
    if len(helpers) != 1 or helpers[0][0] != 0:
        raise SystemExit(f'{og3k.name} has an unexpected loader-helper shape')
    firmware_records = [(address, blob) for address, blob in og_records
                        if address >= 0x40000000]
    missing = NATIVE_UI_SECTIONS - {address for address, _ in firmware_records}
    if missing:
        sites = ', '.join(f'0x{address:08X}' for address in sorted(missing))
        raise SystemExit(f'{og3k.name} lacks native UI sections: {sites}')
    manifest = (og3k / 'MANIFEST.txt').read_text('utf-8')
    if f'{NATIVE_UI_RECORDS} selected NBU records' not in manifest:
        raise SystemExit(f'{og3k.name} does not attest {NATIVE_UI_RECORDS} UI records')

    section_args = []
    for index, (address, blob) in enumerate(firmware_records):
        path = tmp / f'og3k_{index:02d}_{address:08X}.bin'
        path.write_bytes(blob)
        section_args += ['--also-bin', f'0x{address:08X}:{path}']

    out = {}
    for name, debug in (('plain', False), ('shell', True)):
        d = tmp / name
        cmd = [sys.executable, str(GYRO / 'build_base_card.py'),
               '--edition', 'gcsv', '--version', 'catalogue-reference',
               '--banner', f'fpSup-{product.upper()}-Gyro!', '--out', str(d),
               *section_args]
        if debug:
            cmd.append('--debug')
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            sys.stderr.write(r.stdout + r.stderr)
            raise SystemExit(f'could not build the {name} reference card')
        _, records = parse((d / 'VSHL.BIN').read_bytes())
        missing = NATIVE_UI_SECTIONS - {address for address, _ in records}
        if missing:
            sites = ', '.join(f'0x{address:08X}' for address in sorted(missing))
            raise SystemExit(f'{name} reference lacks native UI sections: {sites}')
        out[name] = d
    out['_tmp'] = tmp
    REFS[product] = out
    return out


RELEASES = ROOT / 'fpSup' / 'releases'

PRODUCTS = {
    'usbshell': dict(id='shell', name='USB shell', shell=True, template='shellpush',
                     desc='The worker that answers `shl` over USB. Selecting it '
                          'switches the AutoRun to the loader that creates a task, '
                          'because the worker blocks on the endpoint and cannot run '
                          'in a borrowed callback.'),
    'gyro':     dict(id='gyro', name='fpGyroSup',
                     desc='Writes .gcsv and .json into the clip folder while '
                          'recording. The released card, unmodified.'),
    'og3k':     dict(id='og3k', name='OpenGate 3K', excl=['og2k'],
                     desc='3024×2010, DNG cropped to 3008×2000, eight frame rates, '
                          '8/10/12-bit CinemaDNG. Sensor modes 98/117 — the sensor\'s '
                          'own 2×2-binned 3:2 modes, so the ISP scales nothing. Native '
                          'OG3K entry in Recording Settings and Quick Set. 219 MB/s at '
                          '24p 12-bit. Super35/crop must be off. Alpha — the release '
                          'README lists what is and is not verified. Carries no entry '
                          'section: it is all static writes.'),
    'og2k':     dict(id='og2k', name='OpenGate 2K', excl=['og3k'],
                     desc='2016×1344, DNG cropped to 2000×1334 — the same 3:2 field of '
                          'view at a third of the data. Sensor mode 139, the 3×3 '
                          'readout, so all eight frame rates including 100p stay on the '
                          'quiet one; rolling shutter 8.3 ms. 98 MB/s at 24p 12-bit, '
                          'which an ordinary fast card can sustain. Test build. '
                          'Not with OpenGate 3K: the resolution menu holds three '
                          'entries and each of them takes the third.'),
}
# usbshell first: picked() walks this order, and the development card puts the
# worker at record 1, which is what makes the merge come out byte-identical to it.
# og2k last: the merge checks below reproduce cards that predate it, and
# picked() walks this order, so appending cannot change their bytes.
ORDER = ['usbshell', 'gyro', 'og3k', 'og2k']


def version_key(q):
    """Sort key for a release's version string.

    Numbers compare as numbers, so 1.11 beats 1.2.  Among equal numbers a plain
    release is newest, then letter revisions, then anything word-shaped:
    v1.11b > v1.11a > v1.11test is wrong only if someone ships a `test` *after*
    a final, which is not a thing.
    """
    nums = tuple(int(n) for n in re.findall(r'\d+', q))
    tail = re.sub(r'^[\d.]*', '', q)
    rank = 2 if not tail else (1 if len(tail) == 1 else 0)
    return (nums, rank, tail)


def latest(product):
    """Newest fpsup-<product>-v<version>/ directory, or None."""
    found = []
    for d in RELEASES.glob(f'fpsup-{product}-v*'):
        if d.is_dir() and (d / 'VSHL.BIN').exists() and (d / 'AutoRun.txt').exists():
            found.append((version_key(d.name.split('-v', 1)[1]), d))
    return max(found)[1] if found else None


def discover():
    """Resolve every product to its newest release.  Adding a version is adding
    a directory -- nothing here names one."""
    out = []
    for key in ORDER:
        d = latest(key)
        if d is None:
            raise SystemExit(f'no release for {key} in {RELEASES}')
        spec = dict(PRODUCTS[key])
        spec['dir'] = d
        spec['version'] = d.name.split('-v', 1)[1]
        out.append(spec)
    return out


# Both derived, never invented:
#   research/firmware/notes/FORMAT.md -- the DFI carries the firmware LZSS-
#     compressed and the loader decompresses two segments into DRAM, landing
#     contiguously at 0xC0000000..0xC2F30800.  The NAND itself is not in the
#     address space, so a VSHL record (a blob plus a destination) has no way to
#     reach it.  Checking the destinations is what proves a card is RAM-only.
#   fp_usb_shell/putfile.py POOL_SIZE -- the AutoRun asks `memmgr bufmem get`
#     for 1 MiB, and docs/AUDIT.md notes nobody checks writes against it, so a
#     section past the end lands in whatever the allocator handed out next and
#     the symptom appears somewhere unrelated.
DRAM_IMAGE = (0xC0000000, 0xC2F30800)
POOL_SIZE = 1048576

PAD_TO = 32768
FILLER = '# pad -- see PAD_TO: mode 7 overwrites but does not truncate\n'


def parse(blob):
    magic, count, entry, _ = struct.unpack_from('<4sIII', blob)
    if magic != b'VBIN':
        raise SystemExit('not a VSHL.BIN')
    recs, off = [], 16 + count * 8
    for i in range(count):
        dst, ln = struct.unpack_from('<II', blob, 16 + i * 8)
        recs.append((dst, blob[off:off + ln]))
        off += ln + (-ln % 4)
    return entry, recs


def compose(recs, entry, size=PAD_TO):
    tbl = body = b''
    for dst, b in recs:
        tbl += struct.pack('<II', dst, len(b))
        body += b + b'\x00' * (-len(b) % 4)
    out = struct.pack('<4sIII', b'VBIN', len(recs), entry, len(body)) + tbl + body
    if len(out) > size:
        raise SystemExit(f'{len(out)} bytes, past the {size} a VSHL.BIN is padded to')
    return out + b'\x00' * (size - len(out))


def autorun(template, banner):
    t = template.replace('@@BANNER@@', banner)
    while len(t) + len(FILLER) <= PAD_TO:
        t += FILLER
    return t + '#' * (PAD_TO - len(t) - 1) + '\n'


def banner_of(text):
    """The banner is the last `display text` that is not a progress bar.

    Progress lines look like `fpSup[###.....]060`; the banner is whatever the
    build was told to call itself, and it is not always `fpSup-` prefixed --
    the shell's own card says `fpShell-dbg1!`.
    """
    last = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith('display text ') and 'fpSup[' not in s:
            last = s[len('display text '):]
    if last is None:
        raise SystemExit('no banner line in AutoRun.txt')
    return last


def loader_window():
    """Derived from loader.S so the address is never written down twice."""
    import re
    src = (ROOT / 'fpSup' / 'fp_usb_shell' / 'templates' / 'loader.S').read_text()
    eq = dict(re.findall(r'\.equ\s+(\w+)\s*,\s*(0x[0-9A-Fa-f]+|\d+)', src))
    return int(eq['O_FOBJ'], 0), int(eq['O_BUF'], 0) + int(eq['MAXLEN'], 0)


def load(card):
    if 'zip' in card:
        z, pre = card['zip']
        zf = zipfile.ZipFile(z)
        vshl, ar = zf.read(pre + 'VSHL.BIN'), zf.read(pre + 'AutoRun.txt').decode('utf-8')
    else:
        vshl = (card['dir'] / 'VSHL.BIN').read_bytes()
        ar = (card['dir'] / 'AutoRun.txt').read_text('utf-8')
    return vshl, ar


def check_js(page):
    """Refuse to write a page whose script does not parse.

    A syntax error anywhere in the module takes the whole page down: nothing
    renders, no card appears, and the only symptom is a user saying the tools
    are gone.  That has now happened twice -- once from a stale published check
    and once from a shell one-liner whose replacement text ate a regex
    terminator -- so the build proves the page parses before it ships it.
    """
    blocks = [js for attrs, js in
              re.findall(r'<script([^>]*)>(.*?)</script>', page, re.S)
              if 'json' not in attrs.lower()]
    if not blocks:
        raise SystemExit('  no script found in the template')
    if not shutil.which('node'):
        print('  note: node not found -- the page was NOT syntax-checked')
        return
    for i, js in enumerate(blocks):
        r = subprocess.run(['node', '--check', '-'], input=js,
                           capture_output=True, text=True)
        if r.returncode:
            sys.stderr.write(r.stderr)
            raise SystemExit(f'  script block {i} does not parse; page not written')
    print(f'  js     {len(blocks)} script blocks parse')


def main():
    out_cards, templates = [], {}
    for card in discover():
        vshl, ar = load(card)
        entry, recs = parse(vshl)
        ban = banner_of(ar)
        templates[ban] = ar.split('# pad -- see PAD_TO')[0].replace(ban, '@@BANNER@@')
        out_cards.append(dict(
            id=card['id'], name=card['name'] + '  ' + card['version'],
            desc=card['desc'], excl=card.get('excl', []),
            banner=ban, entry=entry, shell=bool(card.get('shell')),
            template=card.get('template', 'plain'),
            records=[dict(a=a, b=base64.b64encode(b).decode(),
                          l=FIXED.get(a, LABELS.get(a, '')),
                          k='fixed' if a in FIXED else 'sec')
                     for a, b in recs]))
        print(f'  {card["id"]:9} {len(recs):3} sections  entry '
              f'0x{entry:08X}  "{ban}"')

    templates_out, stage2 = build_templates()
    for name in TEMPLATE_FLAGS:
        n = len([l for l in autorun(templates_out[name], 'X').splitlines()
                 if l.strip() and not l.lstrip().startswith('#')])
        print(f'  template {name:10} {n} commands')

    # The AutoRun template belongs to the *loader*, not to the card: the loader
    # only reads VSHL.BIN, and even the entry comes out of that file's header.
    # Two loaders exist.  Everything built now uses the echo-borrow one; the
    # shipped v1.11b zip predates it and carries the older gyro-callback
    # bootstrap, 13 commands longer.  Their VSHL.BIN files are identical --
    # `build_base_card.py --edition gcsv` reproduces the shipped one byte for
    # byte -- so the difference is purely the loader, and the current one is
    # both shorter and verified on hardware.  Compose with it.
    template = templates_out['plain']
    for c in out_cards:
        c['autorun_current'] = templates.get(c['banner']) in templates_out.values()
        if not c['autorun_current']:
            print(f'  note: {c["id"]} shipped with the older loader; the page '
                  f'composes the current one (same VSHL.BIN, shorter AutoRun)')

    lo, hi = loader_window()
    cat = dict(cards=out_cards, pad_to=PAD_TO, loader_window=[lo, hi],
               dram_image=list(DRAM_IMAGE), pool_size=POOL_SIZE,
               entry_at=0xC072E064, park_at=PARK_AT, worker_at=0xC072F050,
               worker_entry=0xC072F188, templates=templates_out,
               autorun_template=template, filler=FILLER,
               stage2=dict(a=0, b=base64.b64encode(stage2).decode(),
                           l='stage2 (current loader)', k='stage2'))

    # Refuse to ship a catalogue that does not reproduce what it came from.
    print()
    bad = False
    for card, spec in zip(out_cards, discover()):
        vshl, ar = load(spec)
        got = compose([(r['a'], base64.b64decode(r['b'])) for r in card['records']],
                      card['entry'])
        ok_v = got == vshl
        bad |= not ok_v
        print(f'  {"OK  " if ok_v else "FAIL"}  {card["id"]} VSHL.BIN')
        if card['autorun_current']:
            ok_a = autorun(templates_out[card['template']],
                           card['banner']).encode('utf-8') == ar.encode('utf-8')
            bad |= not ok_a
            print(f'  {"OK  " if ok_a else "FAIL"}  {card["id"]} AutoRun.txt')
        else:
            print(f'  --    {card["id"]} AutoRun.txt (shipped with the older loader)')
    # The page must also reproduce the cards it can only make by merging.
    by = {c['id']: c for c in out_cards}
    def merge(ids):
        # Mirror the page's picked() exactly: it walks the *catalogue* order,
        # not the order the ids were given.  These were allowed to differ once
        # and the check passed while the page produced different bytes.
        out, tail, seen = [], [], set()
        for c in out_cards:
            if c['id'] not in ids:
                continue
            i = c['id']
            for r in by[i]['records']:
                # Destination zero is loader-owned, not a product record.  Old
                # standalone cards can carry an older helper; a combined card
                # uses the one just built with the current AutoRun templates.
                if r['a'] == 0:
                    continue
                k = (r['a'], r['b'])
                if k in seen:
                    continue
                seen.add(k)
                (tail if r['a'] == cat['entry_at'] else out).append(r)
        recs = [cat['stage2']] + out + tail
        entry = (cat['entry_at'] if any(r['a'] == cat['entry_at'] for r in recs)
                 else cat['worker_entry'] if any(r['a'] == cat['worker_at'] for r in recs)
                 else 0)
        return compose([(r['a'], base64.b64decode(r['b'])) for r in recs], entry)
    merges = [
        ('gyro+og3k          == og3k_gyro_release',
         merge(['gyro', 'og3k']), (refs()['plain'] / 'VSHL.BIN').read_bytes()),
        ('shell+gyro+og3k    == og3k_gyro (dev)',
         merge(['shell', 'gyro', 'og3k']), (refs()['shell'] / 'VSHL.BIN').read_bytes()),
        ('gyro+og2k          == og2k_gyro (rebuilt)',
         merge(['gyro', 'og2k']), (refs('og2k')['plain'] / 'VSHL.BIN').read_bytes()),
        ('shell+gyro+og2k    == og2k_gyro (rebuilt, dev)',
         merge(['shell', 'gyro', 'og2k']), (refs('og2k')['shell'] / 'VSHL.BIN').read_bytes()),
    ]
    for what, got, want in merges:
        ok = got == want
        bad |= not ok
        print(f'  {"OK  " if ok else "FAIL"}  {what}')
    autos = [
        ('AutoRun plain      == og3k_gyro_release',
         autorun(templates_out['plain'], banner_of(
             (refs()['plain'] / 'AutoRun.txt').read_text('utf-8'))),
         (refs()['plain'] / 'AutoRun.txt').read_text('utf-8')),
        ('AutoRun shell      == og3k_gyro (dev)',
         autorun(templates_out['shell'], banner_of(
             (refs()['shell'] / 'AutoRun.txt').read_text('utf-8'))),
         (refs()['shell'] / 'AutoRun.txt').read_text('utf-8')),
    ]
    # There is deliberately no "AutoRun shellpush == fp_usb_shell/autorun" check.
    # That template IS build_autorun.py's output for those flags, so comparing it
    # to itself proves nothing -- and the stored card is older than the current
    # loader anyway: its task tail still spins on `b .` where the loader now
    # sleeps through dly_tsk, which is the fix for the priority inversion that
    # starved the worker.  A stored artefact predating a loader change is
    # information, not a failure.
    for what, got, want in autos:
        ok = got == want
        bad |= not ok
        print(f'  {"OK  " if ok else "FAIL"}  {what}')
    if bad:
        raise SystemExit('a card does not round-trip; page not written')

    page = (HERE / 'template.html').read_text().replace(
        '@@CATALOGUE@@', json.dumps(cat, separators=(',', ':')))
    check_js(page)
    # Two outputs from one template.  The Artifact host supplies the doctype and
    # <head>, so it gets the page as written; a file opened from disk gets
    # neither, and without a charset the section labels come out as mojibake.
    # They were allowed to drift apart once -- the published page kept a check
    # that had already been fixed locally, which disabled both download buttons
    # and hid a card, and the only symptom was a user saying "the button does
    # not work".  Emitting both from here means they cannot.
    (HERE / 'artifact.html').write_text(page)
    # template.html is shaped for the Artifact host, which supplies the doctype
    # (local copy below)
    css, rest = page.split('</style>', 1)
    (HERE / 'index.html').write_text(
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        + css + '</style>\n</head>\n<body>\n' + rest + '\n</body>\n</html>\n')
    print(f'\n  wrote  {HERE / "index.html"}  '
          f'{(HERE / "index.html").stat().st_size:,} bytes')
    for product in list(REFS):
        shutil.rmtree(REFS[product]['_tmp'], ignore_errors=True)
    if REFS:
        print('  refs   built and discarded (merged cards never land in the tree)')


if __name__ == '__main__':
    main()
