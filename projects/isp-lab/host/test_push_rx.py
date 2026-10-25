#!/usr/bin/env python3
"""Offline tests for push_rx.py.  python3 -B -m unittest test_push_rx"""
import json, os, pathlib, random, socket, struct, tempfile, threading, time, unittest
from unittest import mock

import push_rx as P


def image(source, seq, segs, **kw):
    rnd = random.Random(seq * 31 + source)
    payload = b''.join(rnd.randbytes(n) for n in segs)
    return P.make_header(source, seq, segs, **kw) + payload, payload


class Split(unittest.TestCase):
    def run_split(self, stream, pieces):
        got = []
        sp = P.Splitter(lambda h, p: got.append((h, p)))
        rnd = random.Random(pieces)
        i = 0
        while i < len(stream):
            n = rnd.randint(1, pieces)
            sp.feed(stream[i:i + n]); i += n
        return got, sp

    def test_any_chunking(self):
        imgs = [image(1, s, [3_000, 17, 70_001]) for s in range(5)] + [image(4, 9, [1])]
        stream = b''.join(i for i, _ in imgs)
        for pieces in (1, 7, 1024, 1 << 20):
            got, sp = self.run_split(stream, pieces)
            self.assertEqual([p for _, p in got], [p for _, p in imgs])
            self.assertEqual(sp.stats()['skipped_bytes'], 0)
            self.assertEqual(got[0][0]['segs'], [3_000, 17, 70_001])

    def test_resync_after_a_torn_image(self):
        a, pa = image(1, 1, [5000])
        b, pb = image(1, 2, [5000])
        torn = a[:HALF] if (HALF := 3000) else a        # an image whose tail never came
        for gap in (0, 77):
            got, sp = self.run_split(torn + b'\x00' * gap + b + image(1, 3, [5000])[0], 64)
            self.assertEqual([h['seq'] for h, _ in got], [2, 3])
            self.assertEqual(got[0][1], pb)
            self.assertEqual(sp.stats()['torn'], 1)

    def test_bad_crc_is_not_an_image(self):
        a, _ = image(2, 1, [100])
        bad = bytearray(a); bad[0x14] ^= 1            # frame_no changed, CRC not
        got, _ = self.run_split(bytes(bad), 1 << 20)
        self.assertEqual(got, [])

    def test_crc_zero_means_unchecked(self):
        a, pa = image(3, 1, [100], crc=False)
        got, _ = self.run_split(a, 1 << 20)
        self.assertEqual([p for _, p in got], [pa])

    def test_seq_gap_is_a_camera_skip(self):
        stream = b''.join(image(1, s, [10])[0] for s in (1, 2, 5, 6)) + b''.join(image(2, s, [10])[0] for s in (1, 2))
        _, sp = self.run_split(stream, 1 << 20)
        self.assertEqual(sp.stats()['seq_gaps'], {'lv': 2})

    def test_header_rejects_inconsistent_lengths(self):
        h = bytearray(P.make_header(1, 1, [10, 20]))
        struct.pack_into('<I', h, 0x1C, 31)               # total != sum(segs)
        struct.pack_into('<I', h, 0x3C, P.header_crc(h))
        self.assertIsNone(P.parse_header(bytes(h)))


class FakeFpshd(threading.Thread):
    """LISTEN83's socket side, as host/fpshd.c 3.3.0 writes it."""
    def __init__(self, path, stream, trigger_reply=None, chunk=50_000):
        super().__init__(daemon=True)
        self.path, self.stream, self.reply, self.chunk = path, stream, trigger_reply, chunk
        self.srv = socket.socket(socket.AF_UNIX); self.srv.bind(path); self.srv.listen(1)
        self.request = None

    def run(self):
        c, _ = self.srv.accept()
        self.request = c.recv(4096).decode()
        c.sendall(b'OK83L 7\n')
        for i in range(0, len(self.stream), self.chunk):
            d = self.stream[i:i + self.chunk]
            c.sendall(struct.pack('<I', len(d)) + d)
        c.sendall(struct.pack('<I', 0))
        c.sendall(f'END83 {len(self.stream)} idle -7 0 {len(self.reply or "")}\n'.encode())
        if self.reply is not None:
            c.sendall(f'REPLY {self.reply}\n'.encode())
        c.close(); self.srv.close()


class Listen(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.sock = str(self.tmp / 'fake.sock')
        self.saved = P.SOCK
        P.SOCK = self.sock

    def tearDown(self):
        P.SOCK = self.saved

    def test_end_to_end_with_a_trigger(self):
        imgs = [image(2, s, [2016 * 1344]) for s in range(3)]
        srv = FakeFpshd(self.sock, b''.join(i for i, _ in imgs), trigger_reply='done')
        srv.start()
        end, reply, stats = P.listen(self.tmp / 'out', 1 << 30, 3000, 60000, quiet_ms=0, trigger='echo')
        srv.join(5)
        self.assertEqual(srv.request, 'LISTEN83 1073741824 3000 60000 q=0 echo\n')
        self.assertEqual(end['reason'], 'idle')
        self.assertEqual(reply, 'REPLY done')
        self.assertEqual(stats['images'], 3)
        lines = [json.loads(l) for l in (self.tmp / 'out' / 'index.jsonl').read_text().splitlines()]
        self.assertEqual([l['source'] for l in lines], ['bufa1'] * 3)
        self.assertEqual((self.tmp / 'out' / lines[1]['file']).read_bytes(), imgs[1][1])
        self.assertEqual((self.tmp / 'out' / 'stream.raw').read_bytes(), srv.stream)

    def test_listen_only(self):
        srv = FakeFpshd(self.sock, image(1, 1, [10])[0])
        srv.start()
        end, reply, stats = P.listen(self.tmp / 'o2', 100, 10, 1000)
        srv.join(5)
        self.assertEqual(srv.request, 'LISTEN83 100 10 1000 q=1000\n')
        self.assertIsNone(reply)
        self.assertEqual(stats['images'], 1)

    def test_return_waits_until_camera_commands_are_allowed(self):
        srv = FakeFpshd(self.sock, image(1, 1, [10])[0])
        srv.start()
        started = time.monotonic()
        P.listen(self.tmp / 'quiet', 1000, 10, 1000, quiet_ms=200)
        srv.join(5)
        # A caller can issue its first camera cleanup write after return.
        # The old receiver returned immediately into fpshd's ERR quiet gate.
        self.assertGreaterEqual(time.monotonic() - started, .2)

    def test_broken_stream_waits_for_host_barrier_and_quiet(self):
        requests = []
        srv = socket.socket(socket.AF_UNIX)
        srv.bind(self.sock); srv.listen(2)
        def serve():
            with srv:
                conn, _ = srv.accept()
                with conn:
                    requests.append(conn.recv(4096))
                    conn.sendall(b'OK83L 0\n' + struct.pack('<I', 100) + b'partial')
                conn, _ = srv.accept()
                with conn:
                    requests.append(conn.recv(4096))
                    conn.sendall(b'OK name=fpshd version=3.3.0\n')
        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        started = time.monotonic()
        with self.assertRaises(ConnectionError):
            P.listen(self.tmp / 'broken', 1000, 10, 1000, quiet_ms=100)
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(requests[1], b'STATUS\n')
        self.assertGreaterEqual(time.monotonic() - started, .1)

    def test_missing_barrier_is_explicitly_unsettled(self):
        with mock.patch.object(P.socket, 'socket') as sock, \
             mock.patch.object(P, 'read_line', return_value='ERR unavailable'):
            with self.assertRaises(P.ListenerUnsettled):
                P.listener_barrier(1000)
        sock.return_value.__enter__.return_value.sendall.assert_called_once_with(b'STATUS\n')


if __name__ == '__main__':
    unittest.main()
