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
args = ap.parse_args()
DEST = args.out or DEST_DEFAULT
DEST.parent.mkdir(parents=True, exist_ok=True)

CAVE_LOW = 0xC072DE64

LOAD   = 0xC072F050   # worker code — high, leaving 0xC072DE64..0xC072F000 free
STATE  = 0xC072F000   # worker state, 16 words
CAPLEN = 0xC072F040   # capture length
HOOK   = 0xC00D0794   # gyro callback, borrowed once to create the task

PATCHES = [
    (0xC0CF3740, 0xFFFFFF03,
     "PTP interface template: {bNumEndpoints, class, subclass, protocol}",
     "03/06/01/01 -> 03/ff/ff/ff.  Lengths and the endpoint set are untouched;",
     "this only stops the host's PTP stack from claiming interface 0 before the",
     "shell daemon can."),
    (0xC0CF3780, 0x02830507, "EP 0x83, SuperSpeed: interrupt -> bulk"),
    (0xC0CF3784, 0x00000400, "EP 0x83, SuperSpeed: wMaxPacketSize 64 -> 1024, bInterval 11 -> 0"),
    (0xC0CF3758, 0x00033006, "its SuperSpeed companion: bMaxBurst 0 -> 3"),
    (0xC0CF375C, 0x00000000, "its SuperSpeed companion: wBytesPerInterval 64 -> 0"),
    (0xC0CF3798, 0x02830507, "EP 0x83, full speed: interrupt -> bulk"),
    (0xC0CF379C, 0x00000040, "EP 0x83, full speed: bInterval 100 -> 0"),
]

# The on-screen readout.  `display text` draws into the OSD surface and
# `display osd 1` composites it; with a colour argument it fills the layer
# instead, which is how the surface gets wiped.  The layer runs three buffers,
# so each step is repeated three times or the old frame shows through.
SCREEN = [
    (0xC0BB1208, 0xFFFFF8B2, "text colour"),
    (0xC03E46A0, 0xE3A05078, "mov r5,#120 — x, clear of the battery indicator"),
    (0xC03E4698, 0xE3A08010, "mov r8,#16  — y"),
]
BAR_WIDTH = 8


def word_at(seq, i):
    return seq[i]


def progress(out, pct: int):
    filled = round(pct * BAR_WIDTH / 100)
    msg = f"fpSup[{'#' * filled}{'.' * (BAR_WIDTH - filled)}]{pct}"
    for _ in range(3):
        out.append("display osd 1 0x00000000")
    for _ in range(3):
        out.append(f"display text {msg}")
        out.append("display osd 1")


code = assemble(HERE / 'camera' / 'worker.S')
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
w(f"# --- worker code @0x{LOAD:08X}..0x{end:08X}, {len(code)} bytes ---------------")
CHUNKS = 6
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
w("# --- start the worker --------------------------------------------------------")
w("# A one-shot branch from the gyro callback: bootstrap calls the routine it")
w("# displaced, creates the task, and restores this word.")
w(f"mem set 0x{HOOK:08X} 0x{hook_bl:08X}")
w("")
if args.payload:
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
    GCHUNKS = 7
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

w("# --- done --------------------------------------------------------------------")
for _ in range(3):
    w("display osd 1 0x00000000")
for _ in range(3):
    w("display text fpSup!")
    w("display osd 1")

text = '\n'.join(out) + '\n'
DEST_DEFAULT.parent.mkdir(exist_ok=True)
DEST.write_text(text)

print(f"worker : {len(code)} bytes, {len(words)} words, 0x{LOAD:08X}..0x{end:08X}")
print(f"start  : 0x{HOOK:08X} = 0x{hook_bl:08X} -> 0x{LOAD:08X}")
if args.payload:
    print(f"payload: {gsrc.name}, {len(gcode)} bytes, "
          f"0x{args.payload_addr:08X}..0x{gend:08X}, entry 0x{gentry:08X}")
print(f"patches: {len(PATCHES)} endpoint, {len(SCREEN)} screen")
print(f"wrote  : {DEST_DEFAULT.relative_to(HERE)}  {len(out)} lines  "
      f"sha256={hashlib.sha256(text.encode()).hexdigest()[:16]}")
commands = [l for l in out if l and not l.startswith('#')]
for bad in ("mem save", "ctrl sleep", "display colorbar"):
    if any(l.startswith(bad) for l in commands):
        raise SystemExit(f"unwanted command: {bad}")
print(f"clean  : {len(commands)} commands, no dumps and no diagnostics")
