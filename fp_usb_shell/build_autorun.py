#!/usr/bin/env python3
"""Build the USB shell AutoRun.

Assembles worker.S, relocates it for its load address, and emits the card script
with a progress readout on the camera's screen.

    ./build_autorun.py                      shell only
    ./build_autorun.py --payload X.S --entry name [--payload-addr 0xC072DE64]

A payload is anything meant to live in the cave alongside the shell -- it is not
this tool's business what.  It is loaded after the worker is running and armed
last, because the worker's bootstrap borrows the same callback and restores it
once its task exists; the several seconds of `mem set` that loading a payload
takes are also the seconds that restore needs.
"""
import argparse, hashlib, pathlib, sys

from armasm import assemble, symbols, words as to_words

HERE = pathlib.Path(__file__).resolve().parent
DEST_DEFAULT = HERE / 'autorun' / 'AutoRun.txt'

ap = argparse.ArgumentParser()
ap.add_argument('--payload', help='source to load into the cave and arm')
ap.add_argument('--entry', help='symbol in the payload the callback should reach')
ap.add_argument('--payload-addr', type=lambda s: int(s, 0), default=0xC072DE64)
ap.add_argument('--out', type=pathlib.Path, default=None,
                help='where to write; defaults to this tool\'s own autorun/')
ap.add_argument('--also', action='append', default=[], metavar='ADDR:SRC',
                help='additional source to place at a fixed address, repeatable')
ap.add_argument('--boot-call', action='append', default=[], metavar='ADDR:SRC',
                help='write this routine at ADDR and run it once, by borrowing the '
                     'echo handler; for work the AutoRun cannot express, like '
                     'reading a file into memory')
ap.add_argument('--no-pad', action='store_true',
                help='do not pad to a fixed length. Only safe when whatever writes '
                     'the card removes the old file first -- putfile cannot, the '
                     'Mac can. Saves the camera parsing five hundred lines of '
                     'filler on every boot.')
ap.add_argument('--no-shell', action='store_true',
                help='leave the USB shell out: no worker, no endpoint patches, no '
                     'state block. The loader sleeps instead of becoming it. Boots '
                     'faster and leaves one less resident task, at the price of no '
                     'way to look inside if something goes wrong.')
ap.add_argument('--loader', action='store_true',
                help='put the code in VSHL.BIN and have the AutoRun read it')
args = ap.parse_args()
DEST = args.out or DEST_DEFAULT
DEST.parent.mkdir(parents=True, exist_ok=True)

CAVE_LOW = 0xC072DE64
LOADER_END = CAVE_LOW + 0x200   # loader.S sits at the bottom; payloads go above

LOAD   = 0xC072F050   # worker code — high, leaving 0xC072DE64..0xC072F000 free
STATE  = 0xC072F000   # worker state, 16 words
CAPLEN = 0xC072F040   # capture length
ECHO_SLOT = 0xC0BAC2F8  # command table entry 17, echo's handler pointer
ECHO_ORIG = 0xC03D99A0
HOOK   = 0xC00D0794   # gyro callback, borrowed once to create the task

from patches import PATCHES, SCREEN, BAR_WIDTH

# The on-screen readout.  `display text` draws into the OSD surface and
# `display osd 1` composites it; with a colour argument it fills the layer
# instead, which is how the surface gets wiped.  The layer runs three buffers,
# so each step is repeated three times or the old frame shows through.


def word_at(seq, i):
    return seq[i]


# A measuring build only: one send per update instead of three.
#
# The bar keeps every step; each step just costs three commands rather than
# nine. If the eight seconds between 0% and 20% -- where the shipping build
# issues nine display commands and nothing else -- collapses, the display is
# what the boot is spending its time on. If it does not, that stretch belongs to
# the camera's own start-up and no amount of trimming here will touch it.
THIN_BAR = __import__('os').environ.get('FPSUP_THIN_BAR') == '1'


def progress(out, pct: int):
    """One update, sent three times over.

    Sending it once looked safe -- a dropped progress update is only a bar that
    does not move -- and it was not: the bar stopped at 67 while the boot ran on
    to the end, and 67 was then read as a hang. A progress bar that lies is
    worse than no bar. The repetition was measured on this camera; the saving
    comes from taking fewer steps, not from trusting each one.
    """
    filled = round(pct * BAR_WIDTH / 100)
    msg = f"fpSup[{'#' * filled}{'.' * (BAR_WIDTH - filled)}]{pct}"
    reps = 1 if THIN_BAR else 3
    for _ in range(reps):
        out.append("display osd 1 0x00000000")
    for _ in range(reps):
        out.append(f"display text {msg}")
        out.append("display osd 1")


WORKER = HERE / 'camera' / 'worker.S'
code = assemble(WORKER)
words = to_words(code)
end = LOAD + len(code)
if end > 0xC072F700:
    raise SystemExit(f'worker overruns the one-shot scratch: 0x{end:08X}')

disp = (LOAD - (HOOK + 8)) >> 2
if not -(1 << 23) <= disp < (1 << 23):
    raise SystemExit('bootstrap branch out of range')
hook_bl = 0xEB000000 | (disp & 0xFFFFFF)

out = []
w = out.append
w("# ============================================================================")
w("# USB shell.")
w("#")
w("# The camera keeps its own PTP gadget exactly as the firmware builds it, so the")
w("# firmware owns the descriptors, creates and enables the endpoints, and")
w("# re-creates them after a record-mode reconfiguration.  A few words are changed")
w("# so nothing competes for those pipes and so PTP's unused interrupt endpoint")
w("# becomes a second bulk IN for streaming; the rest of this file is the worker.")
w("#")
w("#   EP 0x01 OUT  commands      EP 0x82 IN  replies      EP 0x83 IN  streaming")
w("#")
w("# The worker understands one command: `shl <line>`, which runs <line> in the")
w("# firmware's own shell and returns what it printed.  `mem set` and `mem save`")
w("# come along for free, so the worker needs no memory commands of its own.")
w("#")
w("# Boot with the USB cable UNPLUGGED, then attach it.  The gadget is built on")
w("# attach, so the patches have to land first; and the patched words sit in code")
w("# that has not run yet, so no stale instruction-cache line can shadow them.")
w("#")
w("# The screen reads fpSup[........]0 through fpSup[########]100 while this runs")
w("# and fpSup! when it is done.  A bar that stops means the load stopped there.")
w("# ============================================================================")
w("")
w("# --- screen ------------------------------------------------------------------")
w("display monitor 0 1")
for addr, value, why in SCREEN:
    w(f"# {why}")
    w(f"mem set 0x{addr:08X} 0x{value:08X}")
w("")
progress(out, 0)
w("")
if args.no_shell:
    w("# --- no shell ----------------------------------------------------------------")
    w("# The endpoint patches and the worker's state block are the USB shell's, and")
    w("# there is no shell here: forty-two commands that a camera nobody is going to")
    w("# plug a debugger into does not need. The loader sleeps instead of becoming a")
    w("# worker: the loader reads the file from the callback and returns.")
else:
    w("# --- patches -----------------------------------------------------------------")
    for patch in PATCHES:
        addr, value, *why = patch
        for line in why:
            w(f"# {line}")
        w(f"mem set 0x{addr:08X} 0x{value:08X}")
    w("")
    progress(out, 10)
    w("")
    w(f"# --- worker state @0x{STATE:08X}, 16 words, plus the capture length ----------")
    for i in range(16):
        w(f"mem set 0x{STATE + i*4:08X} 0x00000000")
    w(f"mem set 0x{CAPLEN:08X} 0x00000000")
w("")
progress(out, 20)
w("")
CHUNKS = 3      # progress steps through the loader; each one draws
if not args.loader:
    w(f"# --- worker code @0x{LOAD:08X}..0x{end:08X}, {len(code)} bytes ---------------")
    per = (len(words) + CHUNKS - 1) // CHUNKS
    for c in range(CHUNKS):
        for i in range(c * per, min((c + 1) * per, len(words))):
            w(f"mem set 0x{LOAD + i*4:08X} 0x{words[i]:08X}")
        w("")
        progress(out, 20 + round((c + 1) * 40 / CHUNKS))
    w("")
w("# --- DMA pool; its address lands in 0xC3757A7C -------------------------------")
w("# +0x0000 frame buffer 4 KiB   +0x2000 capture buffer 16 KiB")
w("# +0x6000 free for whatever is loaded alongside   +0x10000 template scratch")
w("# Reserve the whole span up front rather than writing past the allocation and")
w("# hoping the tail is free. Everything derives its address from this pointer:")
w("# asking for 64 KiB instead of 4 already moved the base from 0x44F6ADC0 to")
w("# 0x45026680, and every hard-coded address went with it.")
w("# Three arguments, never four. The handler parses the alignment and stores it")
w("# into the size slot -- `str r3, [sp, #4]` at 0xC03FA580, where the size went")
w("# at 0xC03FA558; the alignment slot at [sp, #0xc] is only ever written with 0.")
w("# So `get 0 0x20000 0x40` asked for 64 bytes and was handed the 128-byte")
w("# minimum, while everything past it belonged to a 256 KiB buffer owned by")
w("# 0xC03A4EEC that is reinitialised when recording starts. That is where the")
w("# shell's capture buffer and anything loaded beside it had been living, and why")
w("# the picture tore and the camera froze at unpredictable moments.")
w("# 1 MiB. The USER pool reports 18 MB free in MOVIE_REC_DNG, and 128 KiB was")
w("# not enough to stage a quarter-megabyte file -- which showed up as a verify")
w("# that never converged rather than as an error, because the overflow landed in")
w("# memory somebody else kept rewriting.")
w("memmgr bufmem get 0 1048576")
w("")
if args.loader:
    # Everything the AutoRun used to spell out goes in a file, and what it
    # spells out instead is the thing that reads the file. Four hundred `mem
    # set` commands become a hundred and twenty-eight, and stay there: adding
    # the gyro logger to this file costs eight hundred more today and none once
    # the code is in the binary beside it.
    #
    # There is no `mem load`. The shell can save memory to a file and not the
    # other way, so the AutoRun cannot ask for this directly -- only spell out
    # something small that asks on its behalf.
    lsrc = HERE / 'templates' / 'loader.S'
    # The release build has no worker to become, so the loader does not need a
    # task: it reads the file straight from the gyro callback and returns. That
    # is 31 fewer words to spell out, which is 31 fewer `mem set` commands --
    # about two seconds off the boot, measured.
    ldef = ['NOTASK=1'] if args.no_shell else []
    lcode = assemble(lsrc, ldef)
    lwords = to_words(lcode)
    # Not at LOAD. The loader's whole job is to write to LOAD, and putting it
    # there means its copy loop overwrites the instructions it is executing --
    # which worked, once, and only because the instruction cache still held
    # them. It goes at the bottom of the cave instead, where nothing it places
    # can reach it.
    LOADER = CAVE_LOW
    lend = LOADER + len(lcode)
    if lend > LOAD:
        sys.exit(f'loader at 0x{LOADER:08X}..0x{lend:08X} runs into the worker')
    lboot = LOADER + symbols(lsrc, ldef)['boot']
    ldisp = (lboot - HOOK - 8) >> 2
    hook_bl = 0xEB000000 | (ldisp & 0xFFFFFF)

    w(f"# --- loader @0x{LOADER:08X}..0x{lend:08X}, {len(lcode)} bytes --------------")
    w("# Reads \\VSHL.BIN and places what it says. The worker itself is in there.")
    per = (len(lwords) + CHUNKS - 1) // CHUNKS
    for c in range(CHUNKS):
        for i in range(c * per, min((c + 1) * per, len(lwords))):
            w(f"mem set 0x{LOADER + i*4:08X} 0x{word_at(lwords, i):08X}")
        w("")
        progress(out, 20 + round((c + 1) * 70 / CHUNKS))
        w("")

w("# --- start the worker --------------------------------------------------------")
w("# A one-shot branch from the gyro callback: bootstrap calls the routine it")
w("# displaced, creates the task, and restores this word.")
w(f"mem set 0x{HOOK:08X} 0x{hook_bl:08X}")
w("")
if args.payload and not args.loader:
    if not args.entry:
        sys.exit('--payload needs --entry')
    gsrc = pathlib.Path(args.payload)
    gcode = assemble(gsrc)
    gwords = to_words(gcode)
    gend = args.payload_addr + len(gcode)
    if args.payload_addr < CAVE_LOW or gend > STATE:
        sys.exit(f'{gsrc.name} at 0x{args.payload_addr:08X}..0x{gend:08X} does not fit '
                 f'the cave 0x{CAVE_LOW:08X}..0x{STATE:08X}')
    gentry = args.payload_addr + symbols(gsrc)[args.entry]
    gdisp = (gentry - HOOK - 8) >> 2
    ghook = 0xEB000000 | (gdisp & 0xFFFFFF)

    w("")
    w("# --- payload -------------------------------------------------------------")
    w(f"# {gsrc.name}, {len(gcode)} bytes at 0x{args.payload_addr:08X}.")
    w("# Loaded after the worker is running, so the several seconds this takes are")
    w("# also the seconds the bootstrap needs to fire and put the callback back.")
    # The payload is often more than half the file, so it gets the rest of the
    # bar. Without this the readout sits at 90% through several hundred silent
    # commands and then jumps to done, which looks exactly like a stall.
    GCHUNKS = 3
    per = (len(gwords) + GCHUNKS - 1) // GCHUNKS
    for c in range(GCHUNKS):
        for i in range(c * per, min((c + 1) * per, len(gwords))):
            w(f"mem set 0x{args.payload_addr + i*4:08X} 0x{word_at(gwords, i):08X}")
        w("")
        progress(out, 60 + round((c + 1) * 35 / GCHUNKS))
        w("")
    for spec in args.also:
        addr_s, _, src_s = spec.partition(':')
        addr, extra = int(addr_s, 0), assemble(pathlib.Path(src_s))
        w("")
        w(f"# {pathlib.Path(src_s).name}, {len(extra)} bytes at 0x{addr:08X}")
        for i, word in enumerate(to_words(extra)):
            w(f"mem set 0x{addr + i*4:08X} 0x{word:08X}")
    w("")
    w("# The logger initialises its own state block, guarded by a magic word, so")
    w("# nothing here has to clear it -- and clearing it by hand is what made the")
    w("# hook create a second writer thread every time.")
    w(f"mem set 0x{HOOK:08X} 0x{ghook:08X}")
    w("")

for spec in args.boot_call:
    addr_s, _, src_s = spec.partition(':')
    addr, blob = int(addr_s, 0), assemble(pathlib.Path(src_s))
    name = pathlib.Path(src_s).name
    w("")
    w(f"# --- {name}, run once ---------------------------------------------------")
    w("# Spelled out here rather than placed by the loader: the loader fires from a")
    w("# gyro callback whenever it likes, and this has to be written before it is")
    w("# called. A hundred lines of `mem set` buys an order that is not a race.")
    w(f"# {len(blob)} bytes at 0x{addr:08X}, then the echo handler is borrowed to")
    w("# call it and put back. There is no `mem call`.")
    for i, word in enumerate(to_words(blob)):
        w(f"mem set 0x{addr + i*4:08X} 0x{word:08X}")
    w(f"mem set 0x{ECHO_SLOT:08X} 0x{addr:08X}")
    w("echo")
    for _ in range(3):
        # `mem set` drops commands, and a handler left pointing at our routine
        # turns the next `echo` into a branch into whatever is there. Seen: the
        # slot came out of a boot holding 0xC072F000, one nibble off the address
        # that was written.
        w(f"mem set 0x{ECHO_SLOT:08X} 0x{ECHO_ORIG:08X}")
    w("")

w("# --- done --------------------------------------------------------------------")
for _ in range(3):
    w("display osd 1 0x00000000")
for _ in range(3):
    w("display text fpSup!")
    w("display osd 1")

if args.loader:
    if args.payload and not args.entry:
        sys.exit('--payload needs --entry')
    if args.payload and args.payload_addr < LOADER_END:
        sys.exit(f'--payload-addr 0x{args.payload_addr:08X} is inside the loader '
                 f'(0x{CAVE_LOW:08X}..0x{LOADER_END:08X}), which is executing from '
                 f'there while it places sections: it would overwrite itself')
    import struct
    # No worker in the release build, and with NOTASK no task to park in it
    # either, so nothing goes to LOAD at all -- the sleeper is debug-only now.
    secs = [] if args.no_shell else [(LOAD, code)]
    if args.payload:
        secs.append((args.payload_addr, assemble(pathlib.Path(args.payload))))
    for spec in args.also:
        addr_s, _, src_s = spec.partition(':')
        secs.append((int(addr_s, 0), assemble(pathlib.Path(src_s))))
    if args.payload:
        # Point the gyro callback at the payload -- last, so it is written only
        # after the payload itself is in place. A `mem set` in the AutoRun could
        # not promise that: the loader runs from a callback of its own, on its
        # own schedule, and arming a hook that branches into memory nobody has
        # written yet is a freeze. As a section it cannot be early. The loader
        # puts the callback back before it places anything, so this is not
        # overwritten either.
        gsrc = pathlib.Path(args.payload)
        gentry = args.payload_addr + symbols(gsrc)[args.entry]
        gdisp = (gentry - HOOK - 8) >> 2
        secs.append((HOOK, struct.pack('<I', 0xEB000000 | (gdisp & 0xFFFFFF))))
    table = b''
    body = b''
    for addr, blob in secs:
        table += struct.pack('<II', addr, len(blob))
        body += blob + b'\x00' * (-len(blob) % 4)
    entry = 0 if args.no_shell else LOAD + symbols(WORKER)['serve']
    binblob = struct.pack('<4sIII', b'VBIN', len(secs), entry, len(body)) + table + body
    binpath = DEST.parent / 'VSHL.BIN'
    BIN_PAD = 8192
    if len(binblob) > BIN_PAD:
        sys.exit(f'binary is {len(binblob)} bytes, past the {BIN_PAD} it pads to')
    binblob += b'\x00' * (BIN_PAD - len(binblob))
    binpath.write_bytes(binblob)
    print(f"binary : {binpath.name}  {len(binblob)} bytes, {len(secs)} section(s), "
          f"entry 0x{entry:08X}")

text = '\n'.join(out) + '\n'

# Pad to a fixed length.
#
# `putfile` opens with mode 7, which creates and overwrites but does NOT
# truncate: writing a shorter file leaves the tail of the longer one behind it.
# The loader build is ten kilobytes against the old eighteen, so the card ended
# up holding the new script followed by four hundred `mem set` commands from the
# previous one -- which would have written the old worker straight over the
# loader, after the loader had already been hooked. Every version being the same
# length makes that impossible, whichever way the size goes.
PAD_TO = 32768
if len(text) > PAD_TO:
    sys.exit(f'script is {len(text)} bytes, past the {PAD_TO} everything is padded to')
if not args.no_pad:
    filler = '# pad -- see PAD_TO: mode 7 overwrites but does not truncate\n'
    while len(text) + len(filler) <= PAD_TO:
        text += filler
    text += '#' * (PAD_TO - len(text) - 1) + '\n' 
DEST_DEFAULT.parent.mkdir(exist_ok=True)
DEST.write_text(text)

if args.no_shell:
    print("worker : none -- no task either, the loader runs in the callback")
else:
    print(f"worker : {len(code)} bytes, {len(words)} words, 0x{LOAD:08X}..0x{end:08X}")
print(f"start  : 0x{HOOK:08X} = 0x{hook_bl:08X} -> 0x{LOAD:08X}")
if args.payload:
    # In loader mode the payload is a section of the binary, not a run of `mem
    # set`, so the sizes come from there rather than from the emitting branch.
    psrc = pathlib.Path(args.payload)
    pcode = assemble(psrc)
    pentry = args.payload_addr + symbols(psrc)[args.entry]
    print(f"payload: {psrc.name}, {len(pcode)} bytes, 0x{args.payload_addr:08X}.."
          f"0x{args.payload_addr + len(pcode):08X}, entry 0x{pentry:08X}"
          + (" (armed by the binary's last section)" if args.loader else ""))
print(f"patches: {0 if args.no_shell else len(PATCHES)} endpoint, {len(SCREEN)} screen")
print(f"wrote  : {DEST_DEFAULT.relative_to(HERE)}  {len(out)} lines  "
      f"sha256={hashlib.sha256(text.encode()).hexdigest()[:16]}")
commands = [l for l in out if l and not l.startswith('#')]
for bad in ("mem save", "ctrl sleep", "display colorbar"):
    if any(l.startswith(bad) for l in commands):
        raise SystemExit(f"unwanted command: {bad}")
print(f"clean  : {len(commands)} commands, no dumps and no diagnostics")
