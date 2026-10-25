"""Lossless archive checks; no camera or network access."""
import pathlib
import tempfile
import unittest

import archive_validation as A


class Archive(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.run = pathlib.Path(tmp.name) / 'run'
        (self.run / 'nested').mkdir(parents=True)
        (self.run / 'RESULTS.md').write_text('measurement\n')
        (self.run / 'nested' / 'frame.bin').write_bytes(bytes(range(256)) * 4096)

    def test_roundtrip_and_repack_preserve_every_member(self):
        first = A.pack(self.run)
        self.assertEqual(A.verify(self.run), first)
        second = A.pack(self.run)
        self.assertEqual(first['files'], second['files'])
        self.assertEqual(set(second['files']), {'RESULTS.md', 'nested/frame.bin'})

    def test_corrupt_archive_is_rejected(self):
        A.pack(self.run)
        path = self.run / A.ARCHIVE
        data = bytearray(path.read_bytes()); data[-1] ^= 1; path.write_bytes(data)
        with self.assertRaisesRegex(ValueError, 'fingerprint'):
            A.verify(self.run)

    def test_symlink_is_not_archived(self):
        (self.run / 'link').symlink_to(self.run / 'RESULTS.md')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            A.pack(self.run)


if __name__ == '__main__':
    unittest.main()
