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
ap.add_argument('--no-ep-patches', action='store_true',
                help='leave EP 0x83 alone.  Those six patches exist for '
                     'hook-push, which a card never does.  The interface-class '
                     'patch is NOT one of them and is applied whenever the '
                     'shell is in: it is what stops the host PTP stack taking '
                     'interface 0, and without it the shell cannot be reached')
ap.add_argument('--abort-always', action='store_true',
                help='diagnostic: abort the script whether or not the store '
                     'started us.  On a card with no store that keeps the '
                     'timing and adds only the abort, which is the other half '
                     'of the pair the store path changes at once')
ap.add_argument('--abort-now', action='store_true',
                help='diagnostic: the loader takes the stop itself instead of '
                     'arming it, so the banner never draws.  One boot to say '
                     'whether the arming is what breaks a store card')
ap.add_argument('--store-boot', action='store_true',
                help='keep the loader in the settings block and carry only a '
                     'bootstrap here.  XC_CommonSaveData survives a power cycle '
                     'where nothing in RAM does (measured: 206 of 207 words), so '
                     'after one boot has filled it every later boot writes 40 '
                     '`mem set` instead of 80.  The first boot costs more, once: '
                     'it carries the bootstrap AND the loader, and the loader '
                     'publishes itself on its way out')
ap.add_argument('--retain-ram', action='store_true',
                help='raise the DRAM self-refresh window from 15 minutes to '
                     '11.95 hours, so the cave survives a soft power-off long '
                     'enough for a warm boot to reuse it.  One word, and it is '
                     'code, so it survives the warm boot itself.  Costs battery: '
                     'self-refresh draws current the whole time the camera is off')
ap.add_argument('--banner', default='fpSup!',
                help='what the screen reads when the load is done.  The bar is '
                     '19 characters wide and the surface is wiped before this '
                     'is drawn, so anything up to that length is safe')
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
ap.add_argument('--also-bin', action='append', default=[], metavar='ADDR:FILE',
                help='place raw bytes at ADDR, repeatable. For a blob that has '
                     'to be patched after assembly, and for sections that are '
                     'just words. An ADDR below 0x40000000 is an OFFSET into '
                     'the camera\'s DMA pool: stage2 adds the base it reads at '
                     'boot, which is the only way to place code in the pool '
                     'from a build that cannot know where the pool is.')
ap.add_argument('--vshl-entry', type=lambda s: int(s, 0), default=None,
                help='absolute address for the file to name as its entry: '
                     'stage2 branches there once every section is placed, with '
                     'lr still pointing back into the loader, so a routine that '
                     'returns lets the boot carry on')
ap.add_argument('--loader', action='store_true',
                help='put the code in VSHL.BIN and have the AutoRun read it')
args = ap.parse_args()
DEST = args.out or DEST_DEFAULT
DEST.parent.mkdir(parents=True, exist_ok=True)

CAVE_LOW = 0xC072DE64
STORE = 0xC3075264           # XC_CommonSaveData + 0x28: past the u16 the
                             # firmware clears at +0x024.  Measured safe to
                             # +0x200 -- see PERSISTENT_STORE_COMMONSAVE.md
STORE_MAX = (0xC307523C + 0x200) - (STORE + 4)     # what the body may occupy;
                             # the header is one word (the magic) -- see
                             # templates/store_boot.S for where the other three
                             # fields went
CAVE_END = 0xC0730000        # the cave's top; sections above this are the
                             # payload's own business, not the loader's
POOL_DESC     = 0xC072F6D8   # sixteen bytes of scratch for the allocator's
                             # descriptor, above the worker and below
                             # STORE_FROM.  The worker ceiling below guards it.
STORE_VER_AT  = 0xC072F6FC   # the version this card was built with.  One
                             # `mem set`, written before the bootstrap runs, so
                             # a loader that came out of the settings block can
                             # tell whether it is the one this card expects --
                             # see the note in loader.S.  The cave is zeroed at
                             # boot, so a stale store can never match by luck.
STORE_BOOT_AT = 0xC072F700   # cave scratch: above the payload and above
                             # the shell's worker (which ends 0xC072F698).
                             # NOT CAVE_LOW -- the bootstrap copies the
                             # loader there and would overwrite itself.
LOADER_END = CAVE_LOW + 0x200   # loader.S sits at the bottom; payloads go above

LOAD   = 0xC072F050   # worker code — high, leaving 0xC072DE64..0xC072F000 free
STATE  = 0xC072F000   # worker state, 16 words
CAPLEN = 0xC072F040   # capture length
ECHO_SLOT = 0xC0BAC2F8  # command table entry 17, echo's handler pointer
ECHO_ORIG = 0xC03D99A0
HOOK   = 0xC00D0794   # gyro callback, borrowed once to create the task

from patches import IFACE, PUSH, RETAIN, SCREEN, BAR_WIDTH

# The on-screen readout.  `display text` draws into the OSD surface and
# `display osd 1` composites it; with a colour argument it fills the layer
# instead, which is how the surface gets wiped.  The layer runs three buffers,
# so each step is repeated three times or the old frame shows through.


def word_at(seq, i):
    return seq[i]


def verify_stage2_cache_publish(code):
    """Require stage2 to publish placed code to both cache domains.

    AutoRun reaches stage2 only after live view has already executed hot firmware
    callsites.  A RAM readback can therefore show a new branch while the CPU is
    still executing its cached stock instruction.  Decode the two immediate
    loads before each ``blx ip`` from the emitted machine code so a source-only
    comment or a renamed constant cannot make a build appear safe.
    """
    insns = to_words(code)

    def mov_imm(word, opcode):
        if word & 0x0FF00000 != opcode or (word >> 12) & 0xF != 12:
            return None
        return ((word >> 4) & 0xF000) | (word & 0x0FFF)

    calls = []
    for index, word in enumerate(insns):
        if word != 0xE12FFF3C or index < 2:  # ARM ``blx ip``
            continue
        low = mov_imm(insns[index - 2], 0x03000000)   # movw ip, #imm16
        high = mov_imm(insns[index - 1], 0x03400000)  # movt ip, #imm16
        if low is not None and high is not None:
            calls.append((index, low | high << 16))

    required = [0xC000E91C, 0xC000EABC]
    if [address for _, address in calls] != required:
        sys.exit('stage2 must call D-cache maintenance 0xC000E91C followed by '
                 'whole I-cache invalidate 0xC000EABC after placing sections; '
                 f'emitted calls were {[hex(address) for _, address in calls]}')
    entry_load = next((index for index, word in enumerate(insns)
                       if word == 0xE5960008), None)  # ldr r0, [r6, #8]
    if entry_load is None or calls[-1][0] >= entry_load:
        sys.exit('stage2 cache publication must finish before loading its entry')


# A measuring build only: one send per update instead of three.
#
# The bar keeps every step; each step just costs two commands rather than six.
# If the eight seconds between 0% and 20% -- where the shipping build issues six
# display commands and nothing else -- collapses, the display is what the boot
# is spending its time on. If it does not, that stretch belongs to the camera's
# own start-up and no amount of trimming here will touch it.
THIN_BAR = __import__('os').environ.get('FPSUP_THIN_BAR') == '1'
# FPSUP_MIN_BAR=1 draws the opening frame and nothing after it: one bar update
# and the banner.  For measuring what the readout costs -- the same card twice,
# differing only in display commands, is the only way to price them.
MIN_BAR = __import__('os').environ.get('FPSUP_MIN_BAR') == '1'
# FPSUP_NO_BAR=1 draws nothing until the banner.  Measured 2026-09-18: twelve
# display commands were worth 3.4 seconds of boot, about 283 ms each, while the
# `mem set` commands a night was spent shaving are a fraction of that.  The
# readout is the expensive thing on this card, not the code it announces.
NO_BAR = __import__('os').environ.get('FPSUP_NO_BAR') == '1'

BAR_WIPED = []      # the surface is cleared once, before the first bar frame


def progress(out, pct: int):
    """One update, drawn into all three OSD buffers.

    The layer runs three buffers and composites whichever is current, so a step
    sent fewer than three times leaves one buffer holding the previous frame and
    the bar flickers between them. Two sends shipped for a while and read as the
    bar vanishing and coming back.

    Three sends used to mean nine commands, because each frame was a wipe as
    well: `display text` does not clear what it draws over, and a blank in the
    new string leaves the old glyph standing. Zero-padding the percentage --
    007 rather than "  7" -- puts a glyph in every cell, so each frame paints
    over the last one completely and the wipes go away. Six commands a step,
    what two sends used to cost, without the flicker.

    Set FPSUP_THIN_BAR=1 to send once and take the risk.
    """
    if NO_BAR:
        return
    if MIN_BAR and BAR_WIPED:
        return
    if not BAR_WIPED:
        for _ in range(3):
            out.append("display osd 1 0x00000000")
        BAR_WIPED.append(True)
    filled = round(pct * BAR_WIDTH / 100)
    msg = f"fpSup[{'#' * filled}{'.' * (BAR_WIDTH - filled)}]{pct:03d}"
    reps = 1 if THIN_BAR else 3
    for _ in range(reps):
        out.append(f"display text {msg}")
        out.append("display osd 1")


WORKER = HERE / 'camera' / 'worker.S'
code = assemble(WORKER)
words = to_words(code)
end = LOAD + len(code)
if end > POOL_DESC:
    raise SystemExit(f'worker reaches the allocator descriptor at '
                     f'0x{POOL_DESC:08X}: it ends at 0x{end:08X}')

disp = (LOAD - (HOOK + 8)) >> 2
if not -(1 << 23) <= disp < (1 << 23):
    raise SystemExit('bootstrap branch out of range')
hook_bl = 0xEB000000 | (disp & 0xFFFFFF)
WORKER_BL = hook_bl             # kept: --loader overwrites hook_bl with its own

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
w(f"# and {args.banner} when it is done.  A bar that stops means the load "
  "stopped there.")
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
fw_patches = []
if args.no_shell:
    w("# --- no shell ----------------------------------------------------------------")
    w("# The endpoint patches and the worker's state block are the USB shell's, and")
    w("# there is no shell here: forty-two commands that a camera nobody is going to")
    w("# plug a debugger into does not need. The loader sleeps instead of becoming a")
    w("# worker: the loader reads the file from the callback and returns.")
else:
    # The interface patch travels with the shell, not with hook-push: without it
    # the interface still says PTP, the host's own PTP stack claims interface 0
    # first, and every command comes back LIBUSB_ERROR_ACCESS.  A card that
    # carries a shell you cannot talk to is not a debug card.
    fw_patches = ([] if args.no_shell else IFACE) + \
                 ([] if args.no_ep_patches else PUSH)
    w("# --- patches and worker state: in the file, not here -------------------------")
    w("# Seven descriptor words and seventeen zeroes used to be twenty-four `mem set`")
    w("# commands.  Every one of them is a fixed value at a fixed address, which is")
    w("# the definition of a VBIN section -- so they ride in the file and the loader")
    w("# writes them, and this script is the same length whether the card carries a")
    w("# shell or not.")
w("")
if args.retain_ram:
    w("# --- DRAM retention ----------------------------------------------------------")
    w("# 15 minutes -> 11.95 hours, so a soft power-off leaves the cave loaded.")
    for addr, value, *why in RETAIN:
        for line in why:
            w(f"# {line}")
        w(f"mem set 0x{addr:08X} 0x{value:08X}")
    w("")
progress(out, 20)
w("")
# Progress steps through the loader.  Each step is six commands -- text and
# present, three times, because the layer composites one of three buffers and
# fewer than three leaves one holding the last frame.  So a step is not free:
# six was chosen when the loader was four hundred commands and the bar was the
# only sign the camera had not died.  It is fifty-two now, and two steps still
# move the bar while it runs.
CHUNKS = 2      # progress steps through the loader; each one draws
if not args.loader:
    w(f"# --- worker code @0x{LOAD:08X}..0x{end:08X}, {len(code)} bytes ---------------")
    per = (len(words) + CHUNKS - 1) // CHUNKS
    for c in range(CHUNKS):
        for i in range(c * per, min((c + 1) * per, len(words))):
            w(f"mem set 0x{LOAD + i*4:08X} 0x{words[i]:08X}")
        w("")
        progress(out, 30 + round((c + 1) * 30 / CHUNKS))
    w("")
w("# --- the pool is the loader's business now -----------------------------------")
w("# `memmgr bufmem get` lived here, and it was the script asking for something\n# only the loader uses.  The loader asks the allocator itself -- class 0, the\n# same channel -- and still leaves the address at 0xC3757A7C for everything\n# downstream that reads it from there.")
w("")
progress(out, 30)   # the allocation is seconds; say so rather than look stalled
w("")
if args.store_boot:
    # After the pool, because a store that verifies branches straight into the
    # loader and the loader stages the file at pool+0x8000.  Before the loader,
    # because the whole point is not to write it.
    # The bootstrap carries the loader's length as a constant rather than
    # reading it out of the store, so the loader has to be measured first.
    # Assembling it twice is free next to a wrong length, which the copy loop
    # would run: it writes past the cave, through the payload and the worker,
    # for as far as the number says.
    sprobe = ([f'LOADER_BASE={CAVE_LOW}', f'POOL_DESC=0x{POOL_DESC:08X}']
              + (['ABORT_NOW=1'] if args.abort_now else [])
              + ['ABORT_AUTORUN=1', 'STORE_PROVISION=1', 'STORE_LEN=0',
                 'STORE_MAGIC=0',
                 f'ECHO_SLOT=0x{ECHO_SLOT:08X}', f'ECHO_ORIG=0x{ECHO_ORIG:08X}'])
    sbytes = assemble(HERE / 'templates' / 'loader.S', sprobe)
    slen = len(sbytes)
    # The magic is a hash of the loader's own bytes, taken from the probe build
    # whose own STORE_MAGIC is zero -- so the value cannot depend on itself.
    # It is a literal in a pool either way, so it never changes the size.
    #
    # This is what makes "the store holds a DIFFERENT build of the loader"
    # unreachable rather than merely unlikely: a constant string has to be
    # bumped by hand, and in one night the loader changed four times while the
    # string sat still.
    smagic = int(hashlib.sha256(sbytes).hexdigest()[:8], 16)
    if slen > STORE_MAX:
        sys.exit(f'loader is {slen} bytes; the store holds {STORE_MAX}.')
    ssrc = HERE / 'templates' / 'store_boot.S'
    scode = assemble(ssrc, [f'STORE_LEN=0x{slen:X}',
                            f'STORE_MAGIC=0x{smagic:08X}'])
    swords = to_words(scode)
    send = STORE_BOOT_AT + len(scode)
    if send > CAVE_END:
        sys.exit(f'store bootstrap 0x{STORE_BOOT_AT:08X}..0x{send:08X} leaves the cave')
    w(f"# --- store bootstrap @0x{STORE_BOOT_AT:08X}..0x{send:08X}, {len(scode)} bytes -----")
    w("# The loader lives in XC_CommonSaveData, which survives a power cycle.  If")
    w("# the header and sum check out this copies it into the cave and branches,")
    w("# and the loader ends by stopping the script -- everything below is then")
    w("# a slower way to do what has already been done.  If they do not, this")
    w("# returns having touched nothing and the file carries on.")
    for i in range(len(swords)):
        w(f"mem set 0x{STORE_BOOT_AT + i*4:08X} 0x{word_at(swords, i):08X}")
    w("")
    w(f"mem set 0x{ECHO_SLOT:08X} 0x{STORE_BOOT_AT:08X}")
    w("echo")
    w("")
    # The banner goes AFTER that line, not before it.  It used to be before,
    # because a store that verified stopped the script right here and the
    # banner two hundred commands further down would never be reached -- so it
    # was moved up, and started announcing a load that had not happened yet.
    # For a night "thirty per cent, then the banner" was read as the fast path
    # finishing when it was the slow path carrying on to sixty and ninety
    # underneath, and three conclusions were overturned by it.
    #
    # The loader no longer stops the script; it arms the stop and returns.  So
    # by the time these lines run the load really is done, on the fast path.
    w("# The load is finished by now -- the loader returned rather than stopping")
    w("# the script, which is what lets this line exist at all.")
    for _ in range(3):
        w("display osd 1 0x00000000")
    for _ in range(3):
        w(f"display text {args.banner}")
        w("display osd 1")
    w("")
    # One line, two meanings.  Fast path: the slot points at the loader's
    # abort_entry, which puts the handler back and stops the reader, so nothing
    # below runs.  Slow path: it still points at the bootstrap, which fails its
    # magic check for the second time and returns having touched nothing.
    w("echo")
    for _ in range(3):
        w(f"mem set 0x{ECHO_SLOT:08X} 0x{ECHO_ORIG:08X}")
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
    # CALL in the loader needs to know where the loader will be copied to,
    # because the assembler lays it out at zero.
    # One loader, whatever the card carries: see the note at `boot:` in
    # loader.S for the task that turned out to be unnecessary.
    ldef = [f'LOADER_BASE={CAVE_LOW}', f'POOL_DESC=0x{POOL_DESC:08X}']
    if args.abort_always:
        # ABORT_NOW too: a card with no store has only ONE `echo`, and the three
        # commands after it put the handler back -- so an ARMED abort is
        # disarmed before anything can trigger it.  The first build of this test
        # did exactly that and passed by doing nothing.
        ldef += ['ABORT_AUTORUN=1', 'ABORT_ALWAYS=1', 'ABORT_NOW=1',
                 f'ECHO_SLOT=0x{ECHO_SLOT:08X}', f'ECHO_ORIG=0x{ECHO_ORIG:08X}']
    if args.store_boot:
        # The stored copy is the one that aborts the script: reaching it means
        # the settings block was good, and everything after that point in the
        # file is a slower way to do what has just been done.  The copy the
        # AutoRun spells out carries the same code -- it has to, because it is
        # what gets published -- and simply never gets that far on a first boot.
        #
        # STORE_LEN has to be the assembled length, which is not known until it
        # is assembled.  Both constants are movw/movt pairs, so their VALUE
        # cannot change the size: assemble once to measure, then again for real.
        probe = ldef + ['ABORT_AUTORUN=1', 'STORE_PROVISION=1', 'STORE_LEN=0',
                        'STORE_MAGIC=0'] + \
                       (['ABORT_NOW=1'] if args.abort_now else []) + [
                        f'ECHO_SLOT=0x{ECHO_SLOT:08X}', f'ECHO_ORIG=0x{ECHO_ORIG:08X}']
        n = len(assemble(HERE / 'templates' / 'loader.S', probe))
        # The store's body is the loader itself, so its ceiling is the space
        # measured safe in XC_CommonSaveData: +0x024..+0x200 of the block, less
        # the one-word header.  Checked here rather than assumed, because a
        # loader that outgrows it fails silently -- store_boot copies the wrong
        # number of bytes and every boot takes the slow path with nothing to
        # show why.
        if n > STORE_MAX:
            sys.exit(f'loader is {n} bytes; the store holds {STORE_MAX}. '
                     f'Shrink the loader or use a second run of the block.')
        if n != slen:
            sys.exit(f'the bootstrap was built for {slen} bytes of loader and '
                     f'the loader is {n}: the two measurements disagree.')
        ldef += ['ABORT_AUTORUN=1', 'STORE_PROVISION=1'] + \
                (['ABORT_NOW=1'] if args.abort_now else []) + [
                 f'STORE_LEN=0x{n:X}', f'STORE_MAGIC=0x{smagic:08X}',
                 # The abort skips the three commands that put the echo handler
                 # back, so the loader has to do it itself, and needs to be told
                 # what to put there.
                 f'ECHO_SLOT=0x{ECHO_SLOT:08X}', f'ECHO_ORIG=0x{ECHO_ORIG:08X}']
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
        progress(out, 30 + round((c + 1) * 60 / CHUNKS))
        w("")

w("# --- start ------------------------------------------------------------------")
if args.loader:
    # Borrow the echo handler, the way --boot-call does. The loader used to be
    # reached from the gyro callback, which cost it three mechanisms that did no
    # work: a call to the routine that site displaces, a word proving it had not
    # already run at 50-90 Hz, and putting the firmware's word back before the
    # file read rather than after. None of them survive the move.
    #
    # It also removes a race this file used to warn about in --boot-call's own
    # comment: the loader fired "whenever it likes", so anything it needed had
    # to be spelled out before it, not merely before the command that runs it.
    # Called from `echo`, it runs where the AutoRun says and nowhere else.
    w("# The loader runs here, once, in the shell dispatcher's task -- where a file")
    w("# read is an ordinary thing to do. The gyro callback is the logger's alone.")
    w(f"mem set 0x{ECHO_SLOT:08X} 0x{lboot:08X}")
    w("echo")
    for _ in range(3):
        # `mem set` drops commands, and a handler left pointing at the loader
        # turns the next `echo` into a branch into it.
        w(f"mem set 0x{ECHO_SLOT:08X} 0x{ECHO_ORIG:08X}")
else:
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
# The three wipes above clear the surface, so this does not have to be the
# same length as the bar it replaces -- `display text` leaves standing whatever
# it does not draw over, and that is what the wipe is for.
if len(args.banner) > 24:
    sys.exit(f'--banner is {len(args.banner)} characters; the readout is not '
             f'that wide')
for _ in range(3):
    w(f"display text {args.banner}")
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
    # The loader's second half rides in the file as the first section, marked
    # with destination zero so it is run where it lands instead of copied. Every
    # word it saves the AutoRun is a `mem set` and about sixty milliseconds.
    stage2 = assemble(HERE / 'templates' / 'stage2.S')
    verify_stage2_cache_publish(stage2)
    secs = [(0, stage2)]
    if not args.no_shell:
        secs.append((LOAD, code))
    if args.payload:
        secs.append((args.payload_addr, assemble(pathlib.Path(args.payload))))
    for spec in args.also:
        addr_s, _, src_s = spec.partition(':')
        secs.append((int(addr_s, 0), assemble(pathlib.Path(src_s))))
    for spec in args.also_bin:
        addr_s, _, src_s = spec.partition(':')
        secs.append((int(addr_s, 0), pathlib.Path(src_s).read_bytes()))
    if not args.no_shell:
        # The worker's sixteen state words and the capture length, contiguous at
        # 0xC072F000, and the descriptor patches.  Zeroes, because the cave is
        # zeroed at boot -- but written rather than assumed: if the image ever
        # stops being reloaded from NAND, stale state is a worker that answers
        # with somebody else's buffer length.
        secs.append((STATE, b'\x00' * 68))
        for addr, value, *_ in fw_patches:
            secs.append((addr, struct.pack('<I', value)))
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
        if len(blob) % 4:
            sys.exit(f'section for 0x{addr:08X} is {len(blob)} bytes; the loader '
                     f'copies whole words, so every section must be a multiple of four')
        table += struct.pack('<II', addr, len(blob))
        body += blob + b'\x00' * (-len(blob) % 4)
    entry = (args.vshl_entry if args.vshl_entry is not None else
             0 if args.no_shell else LOAD + symbols(WORKER)['spawn'])
    binblob = struct.pack('<4sIII', b'VBIN', len(secs), entry, len(body)) + table + body
    binpath = DEST.parent / 'VSHL.BIN'
    # Padded to a fixed size for the same reason AutoRun.txt is: putfile writes
    # over USB and cannot shorten a file, so a smaller binary would leave the
    # tail of the last one behind.  Thirty-two kilobytes because an edition that
    # carries its own writer needs more than eight.
    #
    # The ceiling is the pool, not this number: the loader reads up to MAXLEN
    # (0x20000) into pool+0x8000, so pool+0x7000..0x28000 is spoken for while
    # stage2 runs -- it executes from that buffer and reads the other sections
    # out of it.  The first pool user above it is the writer blob at 0x44000.
    # build_base_card.check() derives the window from loader.S and refuses a
    # pool-relative section that lands in it; an earlier comment here put the
    # edge at 0x42000, which was neither the buffer's end nor the blob's start.
    BIN_PAD = 32768
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
print(f"start  : echo handler 0x{ECHO_SLOT:08X} -> 0x{lboot:08X} (loader)"
      if args.loader else
      f"start  : 0x{HOOK:08X} = 0x{hook_bl:08X} -> 0x{LOAD:08X}")
if args.payload:
    # In loader mode the payload is a section of the binary, not a run of `mem
    # set`, so the sizes come from there rather than from the emitting branch.
    psrc = pathlib.Path(args.payload)
    pcode = assemble(psrc)
    pentry = args.payload_addr + symbols(psrc)[args.entry]
    print(f"payload: {psrc.name}, {len(pcode)} bytes, 0x{args.payload_addr:08X}.."
          f"0x{args.payload_addr + len(pcode):08X}, entry 0x{pentry:08X}"
          + (" (armed by the binary's last section)" if args.loader else ""))
# Counted from the list that was actually emitted, not recomputed from the
# flags -- the old line recomputed, and said "0 endpoint" for builds that wrote
# seven of them.  A summary that can disagree with the file is worse than none.
# --retain-ram is emitted outside the shell branch, so it has to be counted
# outside it too; leaving it out is how this line starts disagreeing with the
# file again.
_retain = len(RETAIN) if args.retain_ram else 0
print(f"patches: {(len(fw_patches) if not args.no_shell else 0) + _retain} firmware "
      f"({'iface' if not args.no_shell else '-'}"
      f"{'+push' if not args.no_shell and not args.no_ep_patches else ''}"
      f"{'+retain' if _retain else ''}), "
      f"{len(SCREEN)} screen")
print(f"wrote  : {DEST}  {len(out)} lines  "
      f"sha256={hashlib.sha256(text.encode()).hexdigest()[:16]}")
commands = [l for l in out if l and not l.startswith('#')]
for bad in ("mem save", "ctrl sleep", "display colorbar"):
    if any(l.startswith(bad) for l in commands):
        raise SystemExit(f"unwanted command: {bad}")
print(f"clean  : {len(commands)} commands, no dumps and no diagnostics")
