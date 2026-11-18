#!/usr/bin/env python3
"""Replace the card's LUT_v*.BIN without losing the cube catalogue.

The LUT sup keeps its catalogue (which cubes are in the COLOR list, each one's
color / gamma / matrix, the active one) inside its own BIN, and the version is
in the file name -- so a new build put on the card starts empty.  That lost
Bei's settings on 2026-11-14 and again on 2026-11-19.  This is the only way a
LUT BIN should go onto a card that already has one:

    hot_update.py NEW.BIN --backup DIR     card: back up, carry the catalogue, write, read back, delete the old
    hot_update.py --offline OLD NEW OUT    files only: OUT = NEW with OLD's catalogue
    hot_update.py --show BIN               what a BIN's catalogue holds

The card run refuses to start unless exactly one LUT_v*.BIN is on the card (or
none: then NEW goes on as it is), and never deletes the old file before the new
one has read back whole.  It does not reboot.

Layout (native/library4.h, build_sup.py): the config block "LTC4" is at +0x30
of the file and its word 7 is the catalogue's file offset; the catalogue is a
64 B header + 32 records of 256 B; the header's checksum is FNV-1a over the
header (checksum bytes as zero) and the count records in use.
"""
import argparse
import pathlib
import re
import struct
import subprocess
import sys

CFG_OFF, CFG_MAGIC, CFG_LIBRARY_WORD = 0x30, 0x3443544C, 7
LIB_MAGIC, LIB_VERSION, HEADER, RECORD, LIB_MAX = 0x31424C43, 3, 64, 256, 32
BLOCK = HEADER + RECORD * LIB_MAX
LIB_ENABLED, LIB_NONE = 1, 0xFFFFFFFF
SHELL = pathlib.Path(__file__).resolve().parents[1] / 'fp_usb_shell'
NAME = re.compile(r'^LUT_v[0-9A-Za-z.]+\.BIN$', re.I)


class Refused(Exception):
    pass


def catalogue_offset(blob):
    """File offset of the catalogue, from the BIN's own config; checked against the header there."""
    if len(blob) < CFG_OFF + 56 or struct.unpack_from('<I', blob, CFG_OFF)[0] != CFG_MAGIC:
        raise Refused('not a LUT sup BIN (no LTC4 config at +0x30)')
    off = struct.unpack_from('<14I', blob, CFG_OFF)[CFG_LIBRARY_WORD]
    if off == 0 or off + BLOCK > len(blob):
        raise Refused(f'catalogue offset {off:#x} does not fit the file')
    magic, version, header_len, record_len, count = struct.unpack_from('<5I', blob, off)
    if (magic, header_len, record_len) != (LIB_MAGIC, HEADER, RECORD) or count > LIB_MAX:
        raise Refused(f'no catalogue header at {off:#x}')
    return off


def checksum(block):
    count = struct.unpack_from('<I', block, 16)[0]
    h = 2166136261
    for i in range(HEADER + RECORD * count):
        h = ((h ^ (0 if 24 <= i < 28 else block[i])) * 16777619) & 0xFFFFFFFF
    return h


def read(blob):
    """-> dict(off, version, count, active, stored, computed, entries=[(name, enabled)])."""
    off = catalogue_offset(blob)
    block = blob[off:off + BLOCK]
    _, version, _, _, count, active, stored = struct.unpack_from('<7I', block, 0)
    entries = []
    for i in range(count):
        e = block[HEADER + RECORD * i:HEADER + RECORD * (i + 1)]
        entries.append((e[32:96].split(b'\0')[0].decode('latin1'), bool(struct.unpack_from('<I', e, 96)[0] & LIB_ENABLED)))
    return dict(off=off, version=version, count=count, active=active, stored=stored,
                computed=checksum(block), entries=entries, block=block)


def splice(old, new):
    """new with old's catalogue.  Refuses a damaged or other-format old catalogue,
    and a new build whose catalogue is not the empty one it was built with."""
    o, n = read(old), read(new)
    if o['version'] != LIB_VERSION or n['version'] != LIB_VERSION:
        raise Refused(f"catalogue format {o['version']} -> {n['version']}: this tool carries format {LIB_VERSION} only")
    if o['count'] and o['stored'] != o['computed']:
        raise Refused(f"the old catalogue's checksum is wrong ({o['stored']:#x} != {o['computed']:#x}); not carrying it")
    if n['count']:
        raise Refused(f"the new BIN already holds {n['count']} entries; refusing to overwrite them")
    out = bytearray(new)
    out[n['off']:n['off'] + BLOCK] = o['block']
    back = read(bytes(out))
    assert back['entries'] == o['entries'] and back['active'] == o['active'] and back['stored'] == back['computed'] or not o['count']
    assert bytes(out[:n['off']]) == new[:n['off']] and bytes(out[n['off'] + BLOCK:]) == new[n['off'] + BLOCK:]
    return bytes(out)


def describe(blob):
    c = read(blob)
    on = [name for name, enabled in c['entries'] if enabled]
    active = 'none' if c['active'] == LIB_NONE else (c['entries'][c['active']][0] if c['active'] < c['count'] else f"#{c['active']}?")
    ok = 'ok' if not c['count'] or c['stored'] == c['computed'] else 'CHECKSUM WRONG'
    return f"catalogue at {c['off']:#x}: {c['count']} cubes, {len(on)} in the COLOR list {on}, active {active}, {ok}"


# ---- the card ---------------------------------------------------------------
def card_luts():
    """{name: size} of the LUT_v*.BIN files in \\fpSup (not a clip folder: a short listing)."""
    sys.path.insert(0, str(SHELL))
    import putfile
    listing = putfile.sh('dir \\fpSup', retries=0)
    if not listing.strip() or 'AUTORUN' not in listing.upper() and '.BIN' not in listing.upper():
        raise Refused(f'cannot read \\fpSup: {listing[:120]!r}')
    found = {}
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) >= 2 and NAME.match(parts[-1]) and parts[-2].isdigit():
            found[parts[-1]] = int(parts[-2])
    return found


def tool(*args):
    r = subprocess.run([sys.executable, '-B', *args], cwd=SHELL, capture_output=True, text=True)
    if r.returncode:
        raise Refused(f'{args[0]} failed: {r.stdout[-300:]}{r.stderr[-300:]}')


def fetch(name, size, local):
    tool('getfile.py', f'\\fpSup\\{name}', str(local), '--size', str(size))
    data = pathlib.Path(local).read_bytes()
    if len(data) != size:
        raise Refused(f'{name}: read {len(data)} of {size} B')
    return data


def card_update(new_path, backup_dir):
    new = new_path.read_bytes()
    read(new)                                             # a LUT BIN at all, before touching the card
    if not NAME.match(new_path.name):
        raise Refused(f'{new_path.name}: the file name must be LUT_v<version>.BIN')
    on_card = card_luts()
    if len(on_card) > 1:
        raise Refused(f'{len(on_card)} LUT BINs on the card ({sorted(on_card)}): which catalogue is the one in use? remove one by hand')
    backup_dir.mkdir(parents=True, exist_ok=True)
    out = new
    for old_name, old_size in on_card.items():
        backup = backup_dir / (old_name[:-4] + '.oncard.BIN')
        if backup.exists():
            raise Refused(f'{backup} exists; choose another --backup directory')
        old = fetch(old_name, old_size, backup)
        print(f'card   {old_name} {old_size} B -> {backup}\n       {describe(old)}')
        out = splice(old, new)
    staged = backup_dir / new_path.name
    staged.write_bytes(out)
    print(f'new    {new_path.name} {len(out)} B\n       {describe(out)}')
    same_name = new_path.name in on_card
    if same_name and on_card[new_path.name] > len(out):   # Mode 7 does not truncate
        raise Refused('same name and the card file is longer: delete it by hand after checking the backup')
    tool('putfile.py', str(staged), f'\\fpSup\\{new_path.name}')
    check = backup_dir / (new_path.name[:-4] + '.readback.BIN')
    if fetch(new_path.name, len(out), check) != out:
        raise Refused(f'{new_path.name} read back different; the old file is still on the card')
    check.unlink()
    print('wrote  read back equal')
    if on_card and not same_name:
        import putfile
        (old_name,) = on_card
        if not putfile.delete_file(f'\\fpSup\\{old_name}'):
            raise Refused(f'{old_name} would not delete: two LUT BINs are on the card now')
        print(f'delete {old_name}')
    print('not rebooted; the UI section (UI\\COLOR.BIN) is not this tool\'s')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('new', nargs='?', type=pathlib.Path)
    ap.add_argument('--backup', type=pathlib.Path, help='where the card\'s BIN is kept (projects/lut-sup/private/card-backup-YYYYMMDD)')
    ap.add_argument('--offline', nargs=3, type=pathlib.Path, metavar=('OLD', 'NEW', 'OUT'))
    ap.add_argument('--show', type=pathlib.Path)
    a = ap.parse_args(argv)
    try:
        if a.show:
            print(describe(a.show.read_bytes()))
        elif a.offline:
            old, new, out = a.offline
            data = splice(old.read_bytes(), new.read_bytes())
            out.write_bytes(data)
            print(describe(data))
        elif a.new and a.backup:
            card_update(a.new, a.backup)
        else:
            ap.error('NEW.BIN --backup DIR, or --offline OLD NEW OUT, or --show BIN')
    except Refused as e:
        raise SystemExit(f'refused: {e}')


if __name__ == '__main__':
    main()
