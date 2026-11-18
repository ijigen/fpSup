"""hot_update: the catalogue goes from the card's BIN into a new build, or the tool refuses."""
import struct
import unittest

import hot_update as H


def make(count=0, pad=0x100, tail=b'TAIL' * 8, names=None, active=H.LIB_NONE):
    """A stand-in BIN: config at +0x30, the catalogue pad bytes later, something after it."""
    off = 0x30 + 56 + pad
    blob = bytearray(off + H.BLOCK) + tail
    blob[:4] = b'SL4\0'
    cfg = [H.CFG_MAGIC] + [0] * 13
    cfg[H.CFG_LIBRARY_WORD] = off
    struct.pack_into('<14I', blob, 0x30, *cfg)
    struct.pack_into('<6I', blob, off, H.LIB_MAGIC, H.LIB_VERSION, H.HEADER, H.RECORD, count, active)
    for i in range(count):
        e = off + H.HEADER + H.RECORD * i
        name = (names[i] if names else f'CUBE{i}.cube').encode()
        blob[e + 32:e + 32 + len(name)] = name
        struct.pack_into('<I', blob, e + 96, i & 1)
    struct.pack_into('<I', blob, off + 24, H.checksum(blob[off:off + H.BLOCK]))
    return bytes(blob)


class Splice(unittest.TestCase):
    def test_carries_entries_to_the_new_offset(self):
        old, new = make(5, active=3), make(0, pad=0x240, tail=b'NEWBUILD' * 9)
        out = H.splice(old, new)
        o, r = H.read(old), H.read(out)
        self.assertEqual((r['entries'], r['active'], r['stored']), (o['entries'], 3, r['computed']))
        self.assertEqual(r['off'], H.read(new)['off'])
        self.assertNotEqual(r['off'], o['off'])
        self.assertEqual(out[:r['off']], new[:r['off']])
        self.assertEqual(out[r['off'] + H.BLOCK:], new[r['off'] + H.BLOCK:])

    def test_refuses_damaged_old(self):
        old = bytearray(make(4))
        old[H.read(bytes(old))['off'] + H.HEADER + 40] ^= 1
        with self.assertRaisesRegex(H.Refused, 'checksum'):
            H.splice(bytes(old), make(0))

    def test_refuses_new_with_entries(self):
        with self.assertRaisesRegex(H.Refused, 'already holds'):
            H.splice(make(2), make(1))

    def test_refuses_other_format(self):
        old = bytearray(make(2))
        struct.pack_into('<I', old, H.read(bytes(old))['off'] + 4, 2)
        with self.assertRaisesRegex(H.Refused, 'format'):
            H.splice(bytes(old), make(0))

    def test_refuses_not_a_lut_bin(self):
        with self.assertRaises(H.Refused):
            H.read(bytes(0x4000))

    def test_empty_old_gives_new_unchanged_outside_the_block(self):
        new = make(0, pad=0x80)
        self.assertEqual(H.read(H.splice(make(0), new))['count'], 0)


class Card(unittest.TestCase):
    """card_update against a fake card: no USB."""
    def run_update(self, card, new_name='LUT_v0.1.2test.BIN', new=None, fail_readback=False):
        import pathlib
        import tempfile
        tmp = pathlib.Path(tempfile.mkdtemp())
        new_path = tmp / new_name
        new_path.write_bytes(new or make(0, pad=0x240))
        log = []

        def fetch(name, size, local):
            data = card[name]
            if fail_readback and name == new_name:
                data = data[:-1] + b'\0'
            pathlib.Path(local).write_bytes(data)
            return data

        def tool(script, local, remote):
            log.append(('put', remote))
            card[remote.rsplit('\\', 1)[1]] = pathlib.Path(local).read_bytes()

        class Put:
            @staticmethod
            def delete_file(remote):
                log.append(('del', remote))
                return card.pop(remote.rsplit('\\', 1)[1], None) is not None

        saved = H.card_luts, H.fetch, H.tool
        import sys
        sys.modules['putfile'], had = Put, sys.modules.get('putfile')
        H.card_luts, H.fetch, H.tool = (lambda: {k: len(v) for k, v in card.items()}), fetch, tool
        try:
            H.card_update(new_path, tmp / 'backup')
        finally:
            H.card_luts, H.fetch, H.tool = saved
            if had is None:
                del sys.modules['putfile']
            else:
                sys.modules['putfile'] = had
        return log, tmp

    def test_upgrade_carries_and_deletes_last(self):
        old = make(6, active=2)
        card = {'LUT_v0.1.1test.BIN': old}
        log, tmp = self.run_update(card)
        self.assertEqual(list(card), ['LUT_v0.1.2test.BIN'])
        self.assertEqual(H.read(card['LUT_v0.1.2test.BIN'])['entries'], H.read(old)['entries'])
        self.assertEqual([step for step, _ in log], ['put', 'del'])
        self.assertEqual((tmp / 'backup' / 'LUT_v0.1.1test.oncard.BIN').read_bytes(), old)

    def test_bad_readback_keeps_the_old_file(self):
        card = {'LUT_v0.1.1test.BIN': make(6)}
        with self.assertRaisesRegex(H.Refused, 'read back'):
            self.run_update(card, fail_readback=True)
        self.assertIn('LUT_v0.1.1test.BIN', card)

    def test_two_on_card_refused_before_any_write(self):
        card = {'LUT_v0.1.0test.BIN': make(1), 'LUT_v0.1.1test.BIN': make(2)}
        with self.assertRaisesRegex(H.Refused, 'which catalogue'):
            self.run_update(card)
        self.assertEqual(len(card), 2)

    def test_empty_card_takes_the_new_file_as_is(self):
        card = {}
        new = make(0, pad=0x240)
        self.run_update(card, new=new)
        self.assertEqual(card, {'LUT_v0.1.2test.BIN': new})

    def test_same_name_keeps_the_catalogue(self):
        old = make(3)
        card = {'LUT_v0.1.2test.BIN': old}
        log, _ = self.run_update(card, new=make(0, pad=0x100, tail=b'REBUILT!' * 4))
        self.assertEqual(H.read(card['LUT_v0.1.2test.BIN'])['entries'], H.read(old)['entries'])
        self.assertEqual([step for step, _ in log], ['put'])


if __name__ == '__main__':
    unittest.main()
