from pathlib import Path
from tempfile import TemporaryDirectory
import socket
import time
import unittest

from collector.protocol import parse_line
from har.fake_esp32 import FakeEsp32
from har.tests.fixtures import write_own_session


def read_lines(sock, limit=10_000, timeout=10):
    sock.settimeout(timeout)
    buffer, lines = b"", []
    while len(lines) < limit:
        try:
            chunk = sock.recv(4096)
        except (ConnectionResetError, ConnectionAbortedError):
            break
        if not chunk:
            break
        buffer += chunk
        *done, buffer = buffer.split(b"\n")
        lines += [line.decode("utf-8") for line in done]
    return lines


class FakeEsp32Tests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.csv = write_own_session(Path(self._tmp.name), "s1", "walk", "2026-10-14T08:00:00Z",
                                     seconds=1).with_suffix(".csv")

    def tearDown(self):
        self._tmp.cleanup()

    def test_streams_every_row_as_data_lines(self):
        with FakeEsp32(self.csv, speed=50, loop=False) as fake:
            with socket.create_connection((fake.host, fake.port)) as sock:
                lines = read_lines(sock)
        data = [line for line in lines if line.startswith("DATA")]
        self.assertEqual(len(data), 50)
        self.assertTrue(any(line.startswith("[NET],1,") for line in lines))
        samples = [parse_line(line) for line in data]
        self.assertEqual([s.seq for s in samples], list(range(50)))
        self.assertEqual(len({s.stream_id for s in samples}), 1)

    def test_loop_uses_new_stream_id_each_round(self):
        with FakeEsp32(self.csv, speed=100, loop=True) as fake:
            with socket.create_connection((fake.host, fake.port)) as sock:
                lines = read_lines(sock, limit=130)
        ids = {parse_line(line).stream_id for line in lines if line.startswith("DATA")}
        self.assertGreaterEqual(len(ids), 2)

    def test_second_client_is_rejected(self):
        with FakeEsp32(self.csv, speed=1, loop=True) as fake:
            with socket.create_connection((fake.host, fake.port)) as first:
                self.assertTrue(read_lines(first, limit=1))
                with socket.create_connection((fake.host, fake.port)) as second:
                    self.assertEqual(read_lines(second, timeout=5), [])
            self.assertEqual(fake.connections, 2)

        # stop() must close a client that never reads, promptly
        fake = FakeEsp32(self.csv, speed=1000, loop=True).start()
        try:
            with socket.create_connection((fake.host, fake.port)) as client:
                time.sleep(0.8)  # buffers fill; the serve thread blocks in sendall
                began = time.monotonic()
                fake.stop()
                self.assertLess(time.monotonic() - began, 2.5)
                read_lines(client, timeout=2)  # reaches EOF/reset; a timeout would raise
        finally:
            fake.stop()

    def test_reject_all_and_preamble_only(self):
        with FakeEsp32(self.csv, reject_all=True) as fake:
            with socket.create_connection((fake.host, fake.port)) as sock:
                self.assertEqual(read_lines(sock, timeout=5), [])
        with FakeEsp32(None, idle_net_period_s=1.0) as fake:
            with socket.create_connection((fake.host, fake.port)) as sock:
                began = time.monotonic()
                lines = read_lines(sock, limit=1)
                self.assertLess(time.monotonic() - began, 0.5)
        self.assertTrue(lines[0].startswith("[NET],1,"))
        with FakeEsp32(None, idle_net_period_s=30) as fake:
            with socket.create_connection((fake.host, fake.port)) as sock:
                self.assertTrue(read_lines(sock, limit=1))
            again, deadline = [], time.monotonic() + 2
            while not again and time.monotonic() < deadline:
                time.sleep(0.05)
                with socket.create_connection((fake.host, fake.port)) as sock:
                    again = read_lines(sock, limit=1, timeout=0.5)
        self.assertTrue(again and again[0].startswith("[NET],1,"))
        with FakeEsp32(None, preamble=("hello",), idle_net_period_s=0.05) as fake:
            with socket.create_connection((fake.host, fake.port)) as sock:
                lines = read_lines(sock, limit=3)
        self.assertEqual(lines[0], "hello")
        self.assertTrue(lines[1].startswith("[NET],1,"))

    def test_close_after_limits_data_lines_per_connection(self):
        with FakeEsp32(self.csv, speed=100, close_after=7) as fake:
            with socket.create_connection((fake.host, fake.port)) as sock:
                lines = read_lines(sock)
            self.assertEqual(len([line for line in lines if line.startswith("DATA")]), 7)
            # the slot is released: an immediate reconnect is served, not rejected
            with socket.create_connection((fake.host, fake.port)) as sock:
                lines = read_lines(sock)
            self.assertEqual(len([line for line in lines if line.startswith("DATA")]), 7)

    def test_bad_csv_and_speed_rejected(self):
        bad = Path(self._tmp.name) / "bad.csv"
        bad.write_text("x\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            FakeEsp32(bad)
        with self.assertRaises(ValueError):
            FakeEsp32(self.csv, speed=0)
