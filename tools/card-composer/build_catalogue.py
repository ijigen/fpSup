#!/usr/bin/env python3
"""Regenerate the composer's card catalogue from real build outputs.

    ./build_catalogue.py            -> index.html

The page composes cards from pre-built section blobs, so it needs no assembler
and no firmware image at run time.  Two facts make that legitimate:

  * `fpSup.BIN` is a plain container -- "VBIN", a count, the entry, the payload
    length, then one (dest, len) record per section and the blobs 4-byte
    aligned.  Firmware/pool sections are independent; destination zero is the
    loader-owned stage2 helper and is canonicalized when cards are combined.
  * `AutoRun.txt` does not depend on the section list *or the entry*.  Measured:
    the OG3K-only card (entry 0) and the OG3K+gyro card (entry 0xC072E064) have
    the same 135 commands and differ only in three banner lines.  The loader
    reads the entry out of fpSup.BIN's header, not out of AutoRun.

**Cards, not modules.**  An earlier version of this treated the shipped cards as
subsets of one another and it was wrong: the OG3K-only card is built through a
different loader path.  It carries no park stub, no F_WRITE prologue restore and
no entry section, and it has a pool section the merged card does not.  Filtering
one shipped card's records can produce another only by accident.  So each
shipped card is carried whole, and combining them is an explicit merge with the
same checks the build scripts run.

To add a card: drop its directory in CARDS and run this.  Data, not code.
"""
import base64, hashlib, json, pathlib, re, shutil, struct, subprocess, sys, tempfile, zipfile

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


SHELL_DIR = ROOT / 'fpSup' / 'fp_usb_shell'


def build_fast():
    """The fast path, as three carried blobs rather than a rule.

    A card boots fast when its loader is already in the settings block, and that
    takes four things that all come out of ONE `--store-boot` build:

        the AutoRun    twenty-six words of store_boot, which verify the block and
                       branch into it, plus the loader spelled out for the boot
                       that has to put it there
        stage2         the same helper plus the block that writes the loader into
                       flash, once it has been used rather than merely read
        abort          the routine that stops the script the fast path has just
                       made redundant, placed in the cave
        the magic      sha256 of that loader's own bytes, baked into store_boot

    The magic is why these cannot be mixed and matched: it is a hash of the
    loader that this AutoRun spells out, so a store_boot from one build and a
    loader from another verify against each other and disagree.  Taking all four
    from one build is not tidiness, it is the only combination that works.

    And it is why the page needs no assembler to offer a fast card: nothing here
    is computed at merge time.  The page swaps three blobs.
    """
    tmp = pathlib.Path(tempfile.mkdtemp(prefix='fast-'))
    out = {}
    stage2 = abort = None
    for name, flags in TEMPLATE_FLAGS.items():
        f = tmp / f'{name}.txt'
        r = subprocess.run([sys.executable, str(SHELL_DIR / 'build_autorun.py'),
                            '--loader', '--store-boot', *flags,
                            '--banner', '@@BANNER@@',
                            '--vshl-entry', '0xC072E064', '--out', str(f)],
                           capture_output=True, text=True)
        if r.returncode:
            sys.stderr.write(r.stdout + r.stderr)
            raise SystemExit(f'could not build the fast {name} template')
        out[name] = f.read_text('utf-8').split('# pad -- see PAD_TO')[0]
        _, records = parse((tmp / 'fpSup.BIN').read_bytes())
        if not records or records[0][0] != 0:
            raise SystemExit(f'fast {name}: the first section is not the helper')
        aborts = [b for a, b in records if a == ABORT_AT]
        if len(aborts) != 1:
            raise SystemExit(f'fast {name} carries {len(aborts)} abort sections')
        if stage2 is None:
            stage2, abort = records[0][1], aborts[0]
        elif (records[0][1], aborts[0]) != (stage2, abort):
            raise SystemExit(f'fast {name} disagrees with the other fast builds')
    shutil.rmtree(tmp, ignore_errors=True)
    # The one thing that makes these four pieces a set: store_boot's expected
    # magic is sha256 of the loader that its own AutoRun spells out.  Checked
    # here, from the emitted text, because the failure it guards against is
    # silent and unrecoverable -- a store_boot that accepts a store holding a
    # different loader branches into it at boot, with no shell to recover with.
    for name, text in out.items():
        w = {int(a, 16): int(v, 16) for a, v in
             re.findall(r'^mem set (0x[0-9A-F]{8}) (0x[0-9A-F]{8})', text, re.M)}
        loader, a = b'', CAVE_LOW
        while a in w:
            loader += struct.pack('<I', w[a])
            a += 4
        want = int(hashlib.sha256(loader).hexdigest()[:8], 16)
        if want not in [w.get(STORE_BOOT_AT + 4 * i) for i in range(32)]:
            raise SystemExit(f'fast {name}: store_boot does not carry '
                             f'sha256 of the {len(loader)}-byte loader it '
                             f'spells out (0x{want:08X})')
    return out, stage2, abort


ABORT_AT = 0xC072F080           # where the abort routine is placed in the cave
CAVE_LOW = 0xC072DE64           # where the AutoRun spells the loader out
STORE_BOOT_AT = 0xC072F700      # and where it puts the bootstrap that checks it


def trampoline():
    """The stub that calls every payload's entry, with its table's own offset.

    A VBIN header has one entry word.  Combining two cards that each have one
    used to mean picking a winner -- and the loser vanished without a symptom:
    its sections were placed, its state words written, and nothing called it.
    So a combination carries this instead, and the header points at it.

    Assembled here rather than written in JavaScript for the same reason stage2
    is carried rather than rebuilt: the bytes a card runs should come from the
    assembler, once.  The page only appends the entry words and patches one --
    see templates/entries.S for what that word is.
    """
    sys.path.insert(0, str(SHELL_DIR))
    from armasm import assemble, symbols
    src = SHELL_DIR / 'templates' / 'entries.S'
    return assemble(src, []), symbols(src, [])['table']


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
        _, records = parse((tmp / 'fpSup.BIN').read_bytes())
        # stage2 is the FIRST section, and that is structural rather than a
        # convention: loader.S computes where to branch as 16 + count * 8 -- the
        # end of the table, which is where the first section's data begins -- so
        # whatever is first IS the loader's second half by definition.
        #
        # "the one section with destination zero" was the old rule, and it held
        # only while stage2 was the only thing that ran where it landed.  A card
        # can now carry several: the USB shell's worker bootstrap runs in the
        # staging buffer so that nothing of it is left in the cave, and a card
        # with more than one entry carries the trampoline that calls them.  Both
        # are destination zero and neither is stage2.
        if not records or records[0][0] != 0:
            raise SystemExit(f'{name}: the first section is not the loader helper')
        helper = records[0][1]
        if stage2 is None:
            stage2 = helper
        elif helper != stage2:
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
    og_entry, og_records = parse(payload(og3k).read_bytes())
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
        _, records = parse(payload(d).read_bytes())
        missing = NATIVE_UI_SECTIONS - {address for address, _ in records}
        if missing:
            sites = ', '.join(f'0x{address:08X}' for address in sorted(missing))
            raise SystemExit(f'{name} reference lacks native UI sections: {sites}')
        out[name] = d
    out['_tmp'] = tmp
    REFS[product] = out
    return out


# Merge checks that cannot pass until a release is cut, with the reason.
#
# A named exception rather than a flag: a flag gets passed forever and nobody
# remembers what it was covering.  Each of these is removed by cutting the
# release it names, and the check below turns one that starts passing back into
# a failure so that a stale entry here cannot outlive its reason.
#
# Both of these are the same shape: the reference is rebuilt from the source
# tree, the merge uses the frozen release, and the source tree has moved.  That
# is by design -- a release freezes a camera-tested payload -- so a difference
# here is news about the releases, not about the merge.
STALE = {
    'gyro+og3k': 'the gyro pool blob at 0x44000 is 10,552 bytes in '
                 'fpsup-gyro-v1.11b and 10,640 in the source tree: cut a gyro '
                 'release, or point refs() at the released blob',
    'gyro+og2k': 'same as gyro+og3k -- the frozen gyro blob is 88 bytes older',
    'shell+gyro+og3k': 'fpsup-usbshell-v3.1.0 is two generations old: its '
                       'worker lives at 0xC072F050 in the cave (1,608 bytes) '
                       'and its state words and descriptor patch are `mem set` '
                       'lines in its AutoRun.  The current shell puts all three '
                       'in the file -- a destination-zero bootstrap that asks '
                       'the allocator for its own memory, a 96-byte state '
                       'section and a patch section -- so the two cannot '
                       'reproduce each other.  Cut a usbshell release.',
    'shell+gyro+og2k': 'same as shell+gyro+og3k',
}

def payload(d):
    """The payload container inside a card directory.

    A build writes fpSup.BIN.  Every release published before 2026-09-19 carries
    VSHL.BIN, and a release is frozen bytes -- so both names stay readable for as
    long as one of those is the newest of its product.  Writing is one name;
    reading is two, and only reading.
    """
    for name in ('fpSup.BIN', 'VSHL.BIN'):
        if (d / name).exists():
            return d / name
    return None


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
        if d.is_dir() and payload(d) and (d / 'AutoRun.txt').exists():
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
#     address space, so a payload record (a blob plus a destination) has no way to
#     reach it.  Checking the destinations is what proves a card is RAM-only.
#   gyro/logger.S POOL_BYTES -- the pool a pool-offset section is an offset
#     INTO.  The AutoRun used to ask for this with `memmgr bufmem get` and leave
#     the address in a word; it does not any more, and the payload's own entry
#     asks for it and publishes it instead.  Same megabyte, different owner, and
#     still nobody checks writes against it: a section past the end lands in
#     whatever the allocator handed out next and the symptom appears somewhere
#     unrelated.  Read rather than written down, so it cannot drift.
DRAM_IMAGE = (0xC0000000, 0xC2F30800)


def pool_size():
    import re
    src = (ROOT / 'fpSup' / 'gyro' / 'logger.S').read_text()
    eq = dict(re.findall(r'\.equ\s+(\w+)\s*,\s*(0x[0-9A-Fa-f]+|\d+)', src))
    return int(eq['POOL_BYTES'], 0)


POOL_SIZE = pool_size()

PAD_TO = 32768
FILLER = '# pad -- see PAD_TO: mode 7 overwrites but does not truncate\n'


def parse(blob):
    magic, count, entry, _ = struct.unpack_from('<4sIII', blob)
    if magic != b'VBIN':
        raise SystemExit('not a VBIN container')
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
        raise SystemExit(f'{len(out)} bytes, past the {size} the container is padded to')
    return out + b'\x00' * (size - len(out))


def offsets(recs):
    """Where each section's data lands in the file, in order.

    An entry below 0x40000000 is an offset into the file, not an address, so a
    card's entry has to be re-expressed when the file is rebuilt: which section
    it points into, and how far.  That is what these offsets are for.
    """
    off, out = 16 + 8 * len(recs), []
    for _, blob in recs:
        out.append(off)
        off += len(blob) + (-len(blob) % 4)
    return out


def autorun(template, banner):
    t = template.replace('@@BANNER@@', banner)
    # PAD_TO - 1, not PAD_TO: the last byte is the newline.  Filler that landed
    # exactly on PAD_TO left nothing for it, and `'#' * -1` is the empty string
    # rather than an error -- so this produced a file one byte over the pad and
    # said nothing.  The same arithmetic in the page throws instead, which is
    # how it was found.
    while len(t) + len(FILLER) <= PAD_TO - 1:
        t += FILLER
    out = t + '#' * (PAD_TO - len(t) - 1) + '\n'
    assert len(out) == PAD_TO, f'padded to {len(out)}, not {PAD_TO}'
    return out


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


def read_cap():
    """How many bytes of the card the loader will read, from loader.S.

    This used to be a WINDOW -- pool+O_FOBJ to pool+O_BUF+MAXLEN -- and the page
    refused any pool section that landed in it.  That was a real constraint while
    the loader staged the file inside the same 1 MiB pool the payload used: the
    gyro logger's blob at pool+0x44000 cleared pool+0x8000..0x28000 by design.

    The loader asks the allocator for its own 64 KiB now and hands it back on the
    way out, so those offsets are in a buffer nobody else can name, and comparing
    them with a payload's pool offsets was comparing two address spaces.  Every
    destination-zero section has offset zero and was flagged by it -- which is to
    say the page told everyone not to use any card.

    What survives is a size: the loader reads at most MAXLEN bytes.
    """
    import re
    src = (ROOT / 'fpSup' / 'fp_usb_shell' / 'templates' / 'loader.S').read_text()
    eq = dict(re.findall(r'\.equ\s+(\w+)\s*,\s*(0x[0-9A-Fa-f]+|\d+)', src))
    return int(eq['MAXLEN'], 0)


def load(card):
    if 'zip' in card:
        z, pre = card['zip']
        zf = zipfile.ZipFile(z)
        names = set(zf.namelist())
        bin_name = next(n for n in ('fpSup.BIN', 'VSHL.BIN') if pre + n in names)
        vshl, ar = zf.read(pre + bin_name), zf.read(pre + 'AutoRun.txt').decode('utf-8')
    else:
        vshl = payload(card['dir']).read_bytes()
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
    tramp, tramp_tbl = trampoline()
    fast_tpl, fast_stage2, fast_abort = build_fast()
    for name in TEMPLATE_FLAGS:
        n = len([l for l in autorun(templates_out[name], 'X').splitlines()
                 if l.strip() and not l.lstrip().startswith('#')])
        print(f'  template {name:10} {n} commands')

    # The AutoRun template belongs to the *loader*, not to the card: the loader
    # only reads the container, and even the entry comes out of that file's header.
    # Two loaders exist.  Everything built now uses the echo-borrow one; the
    # shipped v1.11b zip predates it and carries the older gyro-callback
    # bootstrap, 13 commands longer.  Their payload files are identical --
    # `build_base_card.py --edition gcsv` reproduces the shipped one byte for
    # byte -- so the difference is purely the loader, and the current one is
    # both shorter and verified on hardware.  Compose with it.
    template = templates_out['plain']
    for c in out_cards:
        c['autorun_current'] = templates.get(c['banner']) in templates_out.values()
        if not c['autorun_current']:
            print(f'  note: {c["id"]} shipped with the older loader; the page '
                  f'composes the current one (same payload, shorter AutoRun)')

    cap = read_cap()
    cat = dict(cards=out_cards, pad_to=PAD_TO, read_cap=cap,
               dram_image=list(DRAM_IMAGE), pool_size=POOL_SIZE,
               entry_at=0xC072E064, park_at=PARK_AT,
               # worker_at/worker_entry used to live here: 0xC072F050 and
               # 0xC072F188, the cave address the shell's worker was placed at
               # and the offset of its `spawn`.  The worker asks the allocator
               # for its own memory now and its bootstrap runs where the file
               # landed, so there is no address to recognise it by -- and
               # 0xC072F050 has since become the word that holds the pool
               # pointer, which is inside the state section, so the test could
               # not even match.  The entry is worked out from each card's own
               # header instead, which is where it was all along.
               trampoline=dict(b=base64.b64encode(tramp).decode(), tbl=tramp_tbl),
               # Everything a fast card needs, from one --store-boot build.  The
               # page swaps these three in; it computes nothing.
               fast=dict(templates=fast_tpl,
                         stage2=dict(a=0, b=base64.b64encode(fast_stage2).decode(),
                                     l='stage2 (fast: writes the loader to flash)',
                                     k='stage2'),
                         abort=dict(a=ABORT_AT,
                                    b=base64.b64encode(fast_abort).decode(),
                                    l='abort (stops the script)', k='sec')),
               templates=templates_out,
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
        print(f'  {"OK  " if ok_v else "FAIL"}  {card["id"]} payload')
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
        out, tail, seen, kept, entries = [], [], {}, {}, []
        for c in out_cards:
            if c['id'] not in ids:
                continue
            recs_in = by[c['id']]['records']
            # The FIRST section is the loader's own second half, whichever card
            # it came from, because that is where loader.S branches: the end of
            # the table.  Dropped, and one canonical helper put back below --
            # the old cards carry older ones.
            #
            # It used to drop every section with destination zero, which was the
            # same thing while stage2 was the only code that ran where it
            # landed.  It no longer is: the shell's worker bootstrap runs in the
            # staging buffer, and so does this trampoline.  Dropping those would
            # have taken the worker off the card silently.
            for i, r in enumerate(recs_in):
                if i == 0:
                    continue
                k = (r['a'], r['b'])
                if k in seen:
                    kept[id(r)] = seen[k]
                    continue
                seen[k] = r
                kept[id(r)] = r
                (tail if r['a'] == cat['entry_at'] else out).append(r)
            # This card's entry, as something that survives being re-laid-out.
            e = by[c['id']]['entry']
            if e == 0:
                continue
            if e >= 0x40000000:
                entries.append(('abs', e, 0))
                continue
            blobs = [(r['a'], base64.b64decode(r['b'])) for r in recs_in]
            for i, off in enumerate(offsets(blobs)):
                if off <= e < off + len(blobs[i][1]):
                    entries.append(('in', recs_in[i], e - off))
                    break
            else:
                raise SystemExit(f'{c["id"]}: entry 0x{e:08X} is in no section')

        recs = [cat['stage2']] + out + tail
        if len(entries) > 1:
            # One header word, several entries: carry the stub that calls them
            # all.  Last, so nothing it might be asked to call moves after it.
            pad = 4 * (len(entries) + 1)
            recs = recs + [dict(a=0, b=base64.b64encode(tramp + b'\x00' * pad).decode(),
                                l='entries (generated)', k='stage2')]
        blobs = [(r['a'], base64.b64decode(r['b'])) for r in recs]
        off = offsets(blobs)
        where = {id(r): off[i] for i, r in enumerate(recs)}

        def resolve(e):
            kind, ref, delta = e
            return ref if kind == 'abs' else where[id(kept[id(ref)])] + delta

        if len(entries) > 1:
            tbl = off[-1] + tramp_tbl
            words = struct.pack(f'<{len(entries) + 2}I', tbl,
                                *[resolve(e) for e in entries], 0)
            body = bytearray(blobs[-1][1])
            body[tramp_tbl:tramp_tbl + len(words)] = words
            blobs[-1] = (0, bytes(body))
            entry = off[-1]
        elif entries:
            entry = resolve(entries[0])
        else:
            entry = 0
        return compose(blobs, entry)
    merges = [
        ('gyro+og3k          == og3k_gyro_release',
         merge(['gyro', 'og3k']), payload(refs()['plain']).read_bytes()),
        ('shell+gyro+og3k    == og3k_gyro (dev)',
         merge(['shell', 'gyro', 'og3k']), payload(refs()['shell']).read_bytes()),
        ('gyro+og2k          == og2k_gyro (rebuilt)',
         merge(['gyro', 'og2k']), payload(refs('og2k')['plain']).read_bytes()),
        ('shell+gyro+og2k    == og2k_gyro (rebuilt, dev)',
         merge(['shell', 'gyro', 'og2k']), payload(refs('og2k')['shell']).read_bytes()),
    ]
    for what, got, want in merges:
        ok = got == want
        stale = next((why for k, why in STALE.items() if what.startswith(k)), None)
        bad |= not ok and stale is None
        print(f'  {"OK  " if ok else ("STALE" if stale else "FAIL")}  {what}')
        if not ok and stale:
            print(f'          {stale}')
        if ok and stale:
            print(f'          passes now -- remove it from STALE')
            bad = True
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
