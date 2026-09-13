#!/usr/bin/env python3
"""Regenerate the composer's card catalogue from real build outputs.

    ./build_catalogue.py            -> index.html

The page composes cards from pre-built section blobs, so it needs no assembler
and no firmware image at run time.  Two facts make that legitimate:

  * `VSHL.BIN` is a plain container -- "VBIN", a count, the entry, the payload
    length, then one (dest, len) record per section and the blobs 4-byte
    aligned.  Sections are independent; merging is concatenation plus checks.
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
import base64, json, pathlib, struct, sys, zipfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
OG = ROOT / 'projects' / 'open-gate' / 'build'
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
TEMPLATES = [
    ('plain',     OG / 'og3k_gyro_release' / 'AutoRun.txt'),
    ('shell',     OG / 'og3k_gyro' / 'AutoRun.txt'),
    ('shellpush', ROOT / 'fpSup' / 'fp_usb_shell' / 'autorun' / 'AutoRun.txt'),
]

CARDS = [
    # First on purpose.  picked() walks this list, and the development card puts
    # the worker at record 1 -- listing the shell here is what makes the merge
    # come out byte-identical to it instead of merely equivalent.
    dict(id='shell', name='USB shell', shell=True,
         dir=ROOT / 'fpSup' / 'fp_usb_shell' / 'autorun',
         template='shellpush',
         desc='The worker that answers `shl` over USB. Selecting it switches the '
              'AutoRun to the loader that creates a task, because the worker '
              'blocks on the endpoint and cannot run in a borrowed callback.'),
    dict(id='gyro', name='fpGyroSup v1.11b',
         zip=(GYRO / 'release' / 'fp-gyro-sup-v1.11b.zip', 'fp-gyro-sup-v1.11b/'),
         desc='Writes .gcsv and .json into the clip folder while recording. '
              'The released card, unmodified.'),
    dict(id='og3k', name='OG3K open gate — 3:2', dir=OG / 'og3k_release',
         desc='3024×2010 readout, DNG cropped to 3008×2000. Live view, playback '
              'and DNG geometry all verified. Carries no entry section — it is '
              'all static writes.'),
    # og3k_gyro_release is deliberately NOT a card.  Under the policy that merges
    # happen only in the page, offering a pre-merged card alongside its two
    # halves is a second way to get the same bytes -- and a second way to drift.
    # It stays a verification reference below: ticking OG3K and the gyro must
    # produce it exactly.
]

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


def main():
    out_cards, templates = [], {}
    for card in CARDS:
        vshl, ar = load(card)
        entry, recs = parse(vshl)
        ban = banner_of(ar)
        templates[ban] = ar.split('# pad -- see PAD_TO')[0].replace(ban, '@@BANNER@@')
        out_cards.append(dict(
            id=card['id'], name=card['name'], desc=card['desc'],
            banner=ban, entry=entry, shell=bool(card.get('shell')),
            template=card.get('template', 'plain'),
            records=[dict(a=a, b=base64.b64encode(b).decode(),
                          l=FIXED.get(a, LABELS.get(a, '')),
                          k='fixed' if a in FIXED else 'sec')
                     for a, b in recs]))
        print(f'  {card["id"]:9} {len(recs):3} sections  entry '
              f'0x{entry:08X}  "{ban}"')

    templates_out = {}
    for name, path in TEMPLATES:
        txt = path.read_text('utf-8')
        ban = banner_of(txt)
        templates_out[name] = txt.split('# pad -- see PAD_TO')[0].replace(ban, '@@BANNER@@')
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
               entry_at=0xC072E064, park_at=PARK_AT, worker_at=0xC072F050,
               worker_entry=0xC072F188, templates=templates_out,
               autorun_template=template, filler=FILLER)

    # Refuse to ship a catalogue that does not reproduce what it came from.
    print()
    bad = False
    for card, spec in zip(out_cards, CARDS):
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
                k = (r['a'], r['b'])
                if k in seen:
                    continue
                seen.add(k)
                (tail if r['a'] == cat['entry_at'] else out).append(r)
        recs = out + tail
        entry = (cat['entry_at'] if any(r['a'] == cat['entry_at'] for r in recs)
                 else cat['worker_entry'] if any(r['a'] == cat['worker_at'] for r in recs)
                 else 0)
        return compose([(r['a'], base64.b64decode(r['b'])) for r in recs], entry)
    merges = [
        ('gyro+og3k          == og3k_gyro_release',
         merge(['gyro', 'og3k']), (OG / 'og3k_gyro_release' / 'VSHL.BIN').read_bytes()),
        ('shell+gyro+og3k    == og3k_gyro (dev)',
         merge(['shell', 'gyro', 'og3k']), (OG / 'og3k_gyro' / 'VSHL.BIN').read_bytes()),
    ]
    for what, got, want in merges:
        ok = got == want
        bad |= not ok
        print(f'  {"OK  " if ok else "FAIL"}  {what}')
    autos = [
        ('AutoRun plain      == og3k_gyro_release',
         autorun(templates_out['plain'], banner_of(
             (OG / 'og3k_gyro_release' / 'AutoRun.txt').read_text('utf-8'))),
         (OG / 'og3k_gyro_release' / 'AutoRun.txt').read_text('utf-8')),
        ('AutoRun shell      == og3k_gyro (dev)',
         autorun(templates_out['shell'], banner_of(
             (OG / 'og3k_gyro' / 'AutoRun.txt').read_text('utf-8'))),
         (OG / 'og3k_gyro' / 'AutoRun.txt').read_text('utf-8')),
        ('AutoRun shellpush  == fp_usb_shell',
         autorun(templates_out['shellpush'], banner_of(
             (ROOT / 'fpSup' / 'fp_usb_shell' / 'autorun' / 'AutoRun.txt').read_text('utf-8'))),
         (ROOT / 'fpSup' / 'fp_usb_shell' / 'autorun' / 'AutoRun.txt').read_text('utf-8')),
    ]
    for what, got, want in autos:
        ok = got == want
        bad |= not ok
        print(f'  {"OK  " if ok else "FAIL"}  {what}')
    if bad:
        raise SystemExit('a card does not round-trip; page not written')

    page = (HERE / 'template.html').read_text().replace(
        '@@CATALOGUE@@', json.dumps(cat, separators=(',', ':')))
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


if __name__ == '__main__':
    main()
