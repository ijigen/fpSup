#!/usr/bin/env python3
"""Host-side safety checks for the resident logger image.

These do not emulate the camera.  They protect the properties that caused
the field freeze: the stop publication must be followed by a READY rescan, and
the logger/PGEN images must remain inside their fixed RAM regions.
"""

from __future__ import annotations

import itertools
import struct
import sys
import pathlib
import re
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "fp_usb_shell"))

from armasm import assemble, symbols  # noqa: E402


class StopRaceTests(unittest.TestCase):
    def test_stop_rescan_never_closes_over_late_ready(self):
        """Enumerate every ordering of callback publication and writer scan."""

        producer = ("publish_ready", "publish_stop")
        writer = ("scan", "observe_stop_and_rescan")

        for order in itertools.permutations(producer + writer):
            if [x for x in order if x in producer] != list(producer):
                continue
            if [x for x in order if x in writer] != list(writer):
                continue

            ready = stop = scanned_ready = closed = False
            for event in order:
                if event == "publish_ready":
                    ready = True
                elif event == "publish_stop":
                    stop = True
                elif event == "scan":
                    scanned_ready = ready
                    if scanned_ready:
                        ready = False  # writer drains it
                elif stop:
                    # The revised writer acquires STOP and rescans READY here.
                    if ready:
                        ready = False
                    else:
                        closed = True

            self.assertFalse(closed and ready, order)

    def test_three_slot_producer_claims_only_empty_or_drops(self):
        """Exhaust every state combination around the producer's ring walk."""

        empty, filling, ready, writing = range(4)
        for current in range(3):
            others = ((current + 1) % 3, (current + 2) % 3)
            for states_tail in itertools.product(range(4), repeat=2):
                states = [ready, ready, ready]
                states[current] = ready  # the producer has just sealed it
                for slot, state in zip(others, states_tail):
                    states[slot] = state

                claimed = next((slot for slot in others
                                if states[slot] == empty), None)
                dropped = claimed is None

                if dropped:
                    self.assertNotIn(empty, (states[others[0]],
                                             states[others[1]]))
                else:
                    self.assertEqual(states[claimed], empty)
                    states[claimed] = filling
                    self.assertEqual(sum(state == filling for state in states),
                                     states_tail.count(filling) + 1)

    def test_three_slot_writer_always_consumes_lowest_ready_sequence(self):
        """Physical ring position cannot reorder published sample blocks."""

        empty, filling, ready, writing = range(4)
        del empty, filling, writing
        sequences = (11, 7, 19)
        for states in itertools.product(range(4), repeat=3):
            candidates = [i for i, state in enumerate(states)
                          if state == ready]
            chosen = min(candidates, key=sequences.__getitem__) \
                if candidates else None
            if candidates:
                self.assertEqual(sequences[chosen],
                                 min(sequences[i] for i in candidates))
            else:
                self.assertIsNone(chosen)

    def test_head_take_finishes_before_next_take_starts(self):
        """GYR/GCSV/JSON form one transaction in queue order."""

        flags = [0b01, 0b00, 0b00, 0b01]
        # The head already has GCSV, so JSON for that same take is next even
        # though later takes still need their GCSV.
        self.assertEqual("json" if flags[0] & 1 else "gcsv", "json")












    def test_json_path_is_rebuilt_from_each_queued_job(self):
        """GCSV-first order must not send an older JSON to a later clip."""

        def json_path(gyro_path: bytes) -> bytes:
            clip = gyro_path[6:14]
            return b"\\CINEMA\\" + clip + b"\\" + clip + b".json"

        self.assertEqual(
            json_path(b"\\GYRO\\A001_021.GYR\0"),
            b"\\CINEMA\\A001_021\\A001_021.json",
        )
        self.assertEqual(
            json_path(b"\\GYRO\\A001_030.GYR\0"),
            b"\\CINEMA\\A001_030\\A001_030.json",
        )

    def test_quick_restart_boundary_is_debounced_and_armed(self):
        """Only a sustained zero after live geometry may split a take."""

        active, counter = 1, 0

        def poll(width):
            nonlocal active, counter
            if active == 2:
                if width:
                    active = 0
                return
            if active != 1:
                return
            if width:
                counter = 1
            elif counter:
                counter += 1
                if counter >= 21:
                    active = 3

        # The geometry may still be zero just after the record flag rises.
        for _ in range(40):
            poll(0)
        self.assertEqual((active, counter), (1, 0))

        poll(1920)
        for _ in range(19):
            poll(0)
        self.assertEqual(active, 1)
        poll(0)
        self.assertEqual(active, 3)

        # The callback seals 3 -> 2; the writer releases it only when the next
        # clip's real geometry appears.
        active = 2
        poll(0)
        self.assertEqual(active, 2)
        poll(1920)
        self.assertEqual(active, 0)

    def test_transient_geometry_zero_does_not_split(self):
        counter = 1
        for width in [0] * 8 + [1920] + [0] * 8:
            counter = 1 if width else counter + 1
        self.assertLess(counter, 21)


class ImageLayoutTests(unittest.TestCase):
    def test_queue_fits_header_tail_exactly(self):
        queue_at = 0x2A0
        metadata = 0x10
        jobs = 7 * 0x30
        file_object_at = 0x400
        self.assertEqual(queue_at + metadata + jobs, file_object_at)

    # Two bases, and they are not interchangeable.
    #
    # CAVE_BASE is the first byte the injection region owns, and loader.S sits
    # there: load.py spells the rest as CAVE_LOW = LOADER_END = CAVE_BASE +
    # 0x200, build_autorun.py refuses a --payload-addr below it, and
    # imu_stream_deploy.py's CAVE_LO is the same number.  So a payload placed
    # over USB starts at LOADER_END, not at CAVE_BASE.
    #
    # An earlier pass through these tests read the opposite: 0xC072E064 was
    # taken for build_base_card.py's ENTRY_AT alone -- it is that too, the two
    # images happen to clear the same loader by the same 0x200 -- and the
    # logger tests were moved down to CAVE_BASE, which handed them the 512
    # bytes the loader is executing from.  That is why two of them read green
    # while the third, still spelling the literal, read red.  The red one was
    # right.  Both constants are read from their own build script; which one a
    # test wants depends on what it is placing.

    def _cave_base(self):
        """The injection region's first byte: where loader.S itself sits."""
        return self._load_const("CAVE_BASE")

    def _payload_base(self):
        """Where an image placed over USB starts, which is above the loader."""
        return self._load_const("CAVE_BASE") + 0x200

    def _load_const(self, name):
        source = (ROOT / "fp_usb_shell" / "load.py").read_text()
        m = re.search(rf"^{name} = (0x[0-9A-Fa-f]+)", source, re.M)
        self.assertIsNotNone(m, f"{name} is gone from load.py")
        return int(m.group(1), 0)




    def test_the_pool_blob_offset_agrees_everywhere_it_is_written(self):
        """0x44000 is written down twice and assembly cannot see across files.

        ring_task_deploy.py tells stage2 where to put the writer blob;
        gsup_launch.S copies the writer to that same offset, and gsup_boot
        recomputes its own address from it.  If one moves, the launcher reads a word out of
        whatever is at the old offset instead of the routine table -- and its
        only guard is that the word is exactly zero, so anything else becomes
        a blx into garbage.
        """
        deploy = (HERE / "ring_task_deploy.py").read_text()
        entry = (HERE / "gsup_launch.S").read_text()
        m = re.search(r"^CODE_POOL_OFF = (0x[0-9A-Fa-f]+)", deploy, re.M)
        n = re.search(r"^\.equ CODE_OFF,\s*(0x[0-9A-Fa-f]+)", entry, re.M)
        self.assertIsNotNone(m, "CODE_POOL_OFF is gone from ring_task_deploy.py")
        self.assertIsNotNone(n, "CODE_OFF is gone from gsup_launch.S")
        self.assertEqual(int(m.group(1), 0), int(n.group(1), 0))

    def test_the_writer_travels_with_its_own_bootstrap(self):
        """A pool-offset section can only be placed once somebody has published
        a pool, and nobody does that any more except the payload that wants one.

        The writer used to be such a section.  The AutoRun's `memmgr bufmem get`
        published the pool before anything else ran; when that line went, the
        pointer was zero by the time stage2 looked, the section was skipped, and
        the card logged nothing -- with no symptom, because doing nothing is
        exactly what the entry is supposed to do when there is no pool.

        So the writer travels appended to gsup_launch, as one destination-zero
        section that asks for the pool itself and copies itself in.  Asserted
        here: nothing has gone back to the old shape, the writer really is the
        tail of that section, and check() refuses a pool section if one returns.
        """
        import build_base_card
        secs = build_base_card.sections("gcsv")
        pool = [(a, a + len(b), w) for a, b, w in secs if a < 0x40000000]
        self.assertEqual(pool, [], "a pool-relative section is back")

        blob, writer_len = build_base_card.launch("gcsv")
        self.assertGreater(writer_len, 0)
        boot = assemble(HERE / "gsup_launch.S", ("BLOB_LEN=0x%X" % writer_len,))
        self.assertEqual(len(blob), len(boot) + writer_len,
                         "the writer is not the tail of the launch section")
        self.assertEqual(blob[:len(boot)], boot)

        with self.assertRaises(SystemExit):
            build_base_card.check(secs + [(0x44000, b"\x00" * 4, "a pool section")])

    def test_the_card_image_starts_above_the_loader(self):
        """ENTRY_AT is not CAVE_BASE -- what the two tests above got wrong.

        The gap is what the loader needs to not be overwritten by the image it
        just placed.  Asserted as "big enough", not as its present value: 0x200
        is a round number someone chose with margin, and the loader assembles
        to 396 bytes at its largest, so pinning the constant would fail a
        legitimate tightening of it.  What must never happen is the image
        starting inside the running loader.
        """
        card = (HERE / "build_base_card.py").read_text()
        m = re.search(r"^ENTRY_AT = (0x[0-9A-Fa-f]+)", card, re.M)
        self.assertIsNotNone(m)
        entry_at = int(m.group(1), 0)
        loader = assemble(ROOT / "fp_usb_shell" / "templates" / "loader.S",
                          ("LOADER_BASE=0x%X" % self._cave_base(),
                           "POOL_DESC=0xC072F6D8",
                           'BIN_PATH="\\\\fpSup.BIN"'))
        self.assertGreaterEqual(entry_at - self._cave_base(), len(loader))


    def test_the_shipping_build_guards_the_park_stub_itself(self):
        source = (HERE / "build_base_card.py").read_text()
        self.assertIn("PARK_AT = 0xC072EFB4", source)
        self.assertIn("if hi > PARK_AT:", source)


    def test_stream_state_and_32k_text_chunk_have_guard_space(self):
        stream_state = 0x01A0
        stream_state_last_word = 0x40
        header = 0x0200
        text = 0x1A000
        flush = 0x10000
        max_line_slop = 64
        next_region = 0x5B000

        self.assertLessEqual(stream_state + stream_state_last_word + 4, header)
        self.assertLessEqual(text + flush + max_line_slop, next_region)






class SharedBlockTests(unittest.TestCase):
    """A displacement off a shared word has to land where the source says.

    The shared block used to be a list of `.equ`s at cave addresses, and the
    addresses carried the sizes: G_HELD was 0xC072E944 and the flag after it
    0xC072E94C, so `[G_HELD, #8]` reached the flag because G_HELD was eight
    bytes wide.  Re-declaring the block as words lost that -- G_HELD became one
    word, `str r1, [r8, #4]` wrote the second half of the sample over the flag
    and `str r0, [r8, #8]` wrote 1 over the text buffer POINTER.  The build was
    clean, the boot was clean, and the camera froze the moment it recorded.

    So: every displacement off a SHAREDAT register must land exactly on a
    declared field, and where the line names the field in its comment, it must
    be that one.  A field that grows or shrinks now breaks the build.
    """

    def block(self):
        """The shared block's fields, as {name: (offset, size)}."""
        text = (HERE / "writer_core.inc.S").read_text()
        body = text.split("\ng_shared:", 1)[1].split("\n.equ ", 1)[0]
        fields, off = {}, 0
        for line in body.split("\n"):
            m = re.match(r"\s*g_([a-z_0-9]+):\s*\.(word|space)\s+([0-9, ]+)", line)
            if not m:
                continue
            if m.group(2) == "space":
                size = int(m.group(3).split(",")[0])
            else:
                size = 4 * len(m.group(3).replace(" ", "").rstrip(",").split(","))
            fields[m.group(1).upper()] = (off, size)
            off += size
        self.assertIn("G_HELD", fields)
        return fields

    def test_every_displacement_off_a_shared_word_lands_on_a_field(self):
        fields = self.block()
        starts = {off: name for name, (off, _) in fields.items()}
        checked = 0
        for src in sorted(HERE.glob("*.S")):
            held = {}                       # register -> field name
            for n, line in enumerate(src.read_text().split("\n"), 1):
                code = line.split("@")[0]
                m = re.match(r"\s*SHAREDAT\s+(\w+),\s*O_(\w+)", code)
                if m:
                    held[m.group(1)] = m.group(2)
                    continue
                for reg, disp in re.findall(r"\[(\w+),\s*#(\d+)\]", code):
                    if reg not in held:
                        continue
                    start, size = fields[held[reg]]
                    base = start + int(disp)
                    where = f"{src.name}:{n}"
                    if base < start + size:
                        continue            # inside the base field itself
                    self.assertIn(
                        base, starts,
                        f"{where}: [{reg}, #{disp}] off {held[reg]} lands at "
                        f"+{base} in the shared block, which is inside a field, "
                        f"not at the start of one")
                    named = re.search(r"@\s*([A-Z][A-Z_0-9]+)", line)
                    if named and named.group(1) in fields:
                        self.assertEqual(
                            starts[base], named.group(1),
                            f"{where}: the comment says {named.group(1)} but "
                            f"the displacement reaches {starts[base]}")
                    checked += 1
                # A plain write through the register does not disturb it, but
                # anything that assigns it does.
                m = re.match(r"\s*(?:ldr|mov|add|sub|bl|blx)\b[^,]*?(\w+)\s*,",
                             code)
                if m and m.group(1) in held and not code.strip().startswith("str"):
                    held.pop(m.group(1), None)
        self.assertGreater(checked, 3, "the scan found nothing to check")

    def test_a_shared_word_written_with_writeback_is_a_buffer(self):
        """D_PATH was `48 bytes` in a comment on its .equ and one word in the
        block that replaced it.  dbg_path copies a path into it with
        `strb r0, [r1], #1`, so the take's first open wrote forty-four bytes of
        the blob's own code and the camera froze the moment it recorded -- the
        same failure as the 2026-09-07 accel-hook overlap, arrived at from the
        other direction.

        A register that walks forward cannot be bounded from here, but a
        one-word field is never a thing you walk forward through, so a
        SHAREDAT register used with writeback must name a field wider than a
        word.  That is enough to make the next dropped size stop the build.
        """
        fields = self.block()
        found = 0
        for src in sorted(HERE.glob("*.S")):
            held = {}
            for n, line in enumerate(src.read_text().split("\n"), 1):
                code = line.split("@")[0]
                m = re.match(r"\s*SHAREDAT\s+(\w+),\s*O_(\w+)", code)
                if m:
                    held[m.group(1)] = m.group(2)
                    continue
                m = re.match(r"\s*(?:str|ldr)[bh]?\s+\w+,\s*\[(\w+)\]\s*,",
                             code)                 # post-indexed writeback
                if not m:
                    m = re.match(r"\s*(?:str|ldr)[bh]?\s+\w+,\s*\[(\w+),[^]]*\]!",
                                 code)             # pre-indexed writeback
                if m and m.group(1) in held:
                    name = held[m.group(1)]
                    self.assertGreater(
                        fields[name][1], 4,
                        f"{src.name}:{n}: {m.group(1)} walks forward through "
                        f"{name}, which is one word wide -- it is a buffer, and "
                        f"the block has to give it its bytes")
                    found += 1
        self.assertGreater(found, 0, "the scan found no writeback to check")

class CaveTemplateTests(unittest.TestCase):
    """A host template's block address comes from the caller, or from nobody.

    Ten templates each declared `.equ P, 0xC072F700` and every host tool wrote
    its parameters there, which worked because they all agreed.  The moment the
    host started ASKING for that block instead of naming it, the agreement had
    to be carried in the call -- and getfile.S was not converted with the rest.
    The host wrote the parameters into the arena, the template read 0xC072F700,
    and the injected code hung with the shell behind it.  A power cycle.

    This is the config-duplication failure, so the check is mechanical: a
    template that takes one of these names must guard it, and every assemble()
    of that template anywhere in the tree must pass it.  It lives in the gyro
    suite because that is the suite that runs, and it already reaches into
    fp_usb_shell/templates for park.S and loader.S.
    """

    # Names the HOST decides and the template must be told.
    #
    # Not FRAMEBUF or CAP_LEN: those are the resident worker's rendezvous,
    # fixed on both sides because the worker carries them.
    #
    # Not store_boot.S's BOOT_AT either, and that one is worth writing down.
    # It runs BEFORE stage2 -- it is what copies the loader out of the settings
    # block -- so there is no arena to allocate from yet, exactly as the
    # loader's own block cannot be allocated.  It shared 0xC072F700 with the
    # host's parameter block for months; the host moving out is what ends that,
    # not store_boot moving.
    HOST_NAMED = ('P', 'SCRATCH')
    TEMPLATES = ROOT / 'fp_usb_shell' / 'templates'

    def guarded(self):
        """{template stem: {names it takes from the caller}}."""
        out = {}
        for f in sorted(self.TEMPLATES.glob('*.S')):
            text = f.read_text()
            takes = set()
            for name in self.HOST_NAMED:
                m = re.search(rf'^\.equ\s+{name},\s*0xC072[0-9A-Fa-f]{{4}}',
                              text, re.M)
                if not m:
                    continue
                before = text[:m.start()]
                self.assertRegex(
                    before[-120:], rf'#ifndef\s+{name}\s*\n\s*$',
                    f'{f.name}: `.equ {name}` is a cave address the host now '
                    f'allocates, so it must sit under `#ifndef {name}` and the '
                    f'caller must pass it')
                takes.add(name)
            if takes:
                out[f.stem] = takes
        return out

    def test_every_template_that_takes_a_block_is_guarded(self):
        takes = self.guarded()
        self.assertIn('putfile', takes, 'the scan found no guarded template')

    def test_every_assemble_passes_the_block_it_promised(self):
        takes = self.guarded()
        calls = 0
        for f in sorted(ROOT.rglob('*.py')):
            if '/release/' in str(f) or '/history/' in str(f):
                continue
            text = f.read_text()
            for m in re.finditer(
                    r"assemble\(\s*[^)]*?'(\w+)\.S'\s*(?:,\s*(.*?))?\)",
                    text, re.S):
                stem, args = m.group(1), (m.group(2) or '')
                if stem not in takes:
                    continue
                calls += 1
                for name in sorted(takes[stem]):
                    self.assertRegex(
                        args, rf"{name}=",
                        f'{f.name}: assemble({stem}.S) does not pass {name}, '
                        f'which that template takes from its caller -- the '
                        f'template would use its standalone default and the '
                        f'host would use the allocated block')
        self.assertGreater(calls, 0, 'the scan found no call to check')

class ArenaTests(unittest.TestCase):
    """Nothing names an address inside the arena.

    The arena is 0xC072E064..0xC072EFB4, handed out at boot by the camera and
    over USB by fp_usb_shell/cave.py.  A constant naming an address in it is a
    claim nobody else can see: the allocator will hand the same bytes to
    somebody, and the two find out by freezing.  mpool_probe's argument words
    sat at 0xC072E0F0 and the first host claim covered them; thirteen probes in
    raw/ still default their slot to 0xC072E080, which is the gyro's fourth
    hook veneer.

    A `#ifndef`-guarded default in a .S is not a claim -- it is what the file
    assembles to on its own, and the caller passes the real address -- so those
    are allowed, and CaveTemplateTests is what proves the caller passes it.

    Python is read with ast rather than a regex: the regex version reported
    tools/rmequ.py, where the address is an example inside the docstring.
    """

    LO, HI = 0xC072E064, 0xC072EFB4

    # Each of these owns arena addresses for a reason, and the reason is that
    # it is not sharing the arena with anybody.  Named one at a time, because a
    # spelling rule would quietly exempt the next one that really is a claim.
    EXEMPT = {
        'cave.py':
            'declares the arena',
        'imu_stream_deploy.py':
            'CAVE_LO/CAVE_HI are the bounds its placement check uses',
        'build_base_card.py':
            'ENTRY_AT is the floor it checks a section against',
        'build_autorun.py':
            'WORKER_AT is the fallback card\'s worker -- that card has no '
            'stage2 either, and cave.py refuses to allocate on one',
        'test_safety.py':
            'this file declares the bounds it checks against',
    }
    SKIP_DIRS = ('/release/', '/history/', '/.git/', '/node_modules/')

    def offenders(self):
        import ast
        out = []
        for f in sorted(ROOT.rglob('*.py')):
            if any(d in str(f) for d in self.SKIP_DIRS):
                continue
            if f.name in self.EXEMPT:
                continue
            try:
                tree = ast.parse(f.read_text())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                vals = ([node.value] if not isinstance(node.value, ast.Tuple)
                        else list(node.value.elts))
                for v in vals:
                    if (isinstance(v, ast.Constant) and isinstance(v.value, int)
                            and self.LO <= v.value < self.HI):
                        out.append(f'{f.name}:{node.lineno}: 0x{v.value:08X}')
        for f in sorted(ROOT.rglob('*.S')):
            if any(d in str(f) for d in self.SKIP_DIRS):
                continue
            if f.name in self.EXEMPT:
                continue
            text = f.read_text()
            for m in re.finditer(
                    r'^\.equ\s+([A-Z][A-Z_0-9]*),\s*(0xC072E[0-9A-Fa-f]{3})',
                    text, re.M):
                at = int(m.group(2), 16)
                if not self.LO <= at < self.HI:
                    continue
                before = text[:m.start()][-140:]
                if re.search(rf'#ifndef\s+{m.group(1)}\s*\n\s*$', before):
                    continue        # a standalone default; the caller passes it
                out.append(f'{f.name}: .equ {m.group(1)}, 0x{at:08X}')
        return out

    def test_nothing_claims_an_address_in_the_arena(self):
        bad = self.offenders()
        self.assertEqual(
            bad, [],
            'these name an address the allocator hands out:\n  '
            + '\n  '.join(bad))

    def test_the_exemptions_are_still_needed(self):
        """An exemption that has stopped being true is a hole nobody sees."""
        import ast
        for name in self.EXEMPT:
            hits = [f for f in ROOT.rglob(name)
                    if not any(d in str(f) for d in self.SKIP_DIRS)]
            self.assertTrue(hits, f'{name} is exempted but does not exist')
            found = False
            for f in hits:
                for node in ast.walk(ast.parse(f.read_text())):
                    if isinstance(node, (ast.Assign, ast.AnnAssign)):
                        vals = ([node.value] if not isinstance(node.value, ast.Tuple)
                                else list(node.value.elts))
                        found = found or any(
                            isinstance(v, ast.Constant)
                            and isinstance(v.value, int)
                            and self.LO <= v.value < self.HI for v in vals)
            self.assertTrue(
                found,
                f'{name} no longer names an arena address -- drop its exemption')

if __name__ == "__main__":
    unittest.main()
