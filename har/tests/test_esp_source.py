from pathlib import Path
from tempfile import TemporaryDirectory
import socket
import threading
import time
import unittest

from har.fake_esp32 import FakeEsp32
from har.sources import EspSource
from har.stream_windows import read_csv_samples
from har.tests.fixtures import write_own_session

NET = "[NET],1,,0,0"  # what the firmware sends while calibrating (empty stream id)


class RecordingSink:
    def __init__(self, stop, until):
        self.samples, self.statuses = [], []
        self._stop, self._until = stop, until
        self.sample_after_stop = False
        self.stopped_at = None
        self.alive_at_timeout = None
        self.exit_delay_s = None

    def sample(self, s):
        if self._stop.is_set():
            self.sample_after_stop = True
        self.samples.append(s)
        self._check()

    def status(self, **fields):
        self.statuses.append(fields)
        self._check()

    def states(self):
        return [s["state"] for s in self.statuses if "state" in s]

    def _check(self):
        if not self._stop.is_set() and self._until(self):
            self.stopped_at = time.monotonic()
            self._stop.set()


class RaisingSink(RecordingSink):
    def sample(self, s):
        raise ValueError("sink rejected sample")


class SilentTransport:
    """Opens fine; every read times out with no bytes (like TcpTransport on an idle socket)."""

    def __init__(self, host, port, connect_timeout=None):
        pass

    def open(self):
        pass

    def read(self, size):
        time.sleep(0.01)
        return b""

    def close(self):
        pass


class BurstTransport(SilentTransport):
    """Every read returns three complete DATA lines at once (one poll() batch)."""

    def __init__(self, host, port, connect_timeout=None):
        self._seq = 0

    def read(self, size):
        chunk = b""
        for _ in range(3):
            chunk += (f"DATA,1,{'b' * 16},{self._seq},{self._seq * 20000},"
                      "0.1,0.2,1.0,1.5,2.5,3.5,25.0\n").encode()
            self._seq += 1
        assert len(chunk) <= size
        return chunk


class CalibratedNetThenSilentTransport(SilentTransport):
    """First read: one NET line of an already calibrated ESP32 (real stream id); then silence."""

    def __init__(self, host, port, connect_timeout=None):
        self._sent = False

    def read(self, size):
        if self._sent:
            return super().read(size)
        self._sent = True
        return f"[NET],1,{'c' * 16},0,0\n".encode()


def run_source(source, until, timeout=15.0, sink_cls=RecordingSink):
    stop = threading.Event()
    sink = sink_cls(stop, until)
    thread = threading.Thread(target=source.run, args=(sink, stop), daemon=True)
    thread.start()
    finished = stop.wait(timeout)
    sink.alive_at_timeout = thread.is_alive()
    stop.set()
    thread.join(timeout=10)
    if sink.stopped_at is not None and not thread.is_alive():
        sink.exit_delay_s = time.monotonic() - sink.stopped_at
    return sink, finished


class EspSourceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.csv = write_own_session(Path(self._tmp.name), "s1", "walk", "2026-10-14T08:00:00Z",
                                     seconds=3).with_suffix(".csv")

    def tearDown(self):
        self._tmp.cleanup()

    def test_receives_all_samples(self):
        with FakeEsp32(self.csv, speed=20, loop=False) as fake:
            source = EspSource(fake.host, fake.port, retry_s=0.05)
            sink, finished = run_source(source, lambda s: len(s.samples) >= 150)
        self.assertTrue(finished)
        expected = list(read_csv_samples(self.csv))
        first = sink.samples[0]
        self.assertEqual((first.seq, first.time_us, first.values),
                         (expected[0].seq, expected[0].time_us, expected[0].values))
        self.assertIsNone(first.session_id)
        self.assertIsNone(first.label)
        self.assertEqual([(s.seq, s.time_us) for s in sink.samples[:150]],
                         [(e.seq, e.time_us) for e in expected[:150]])
        states = sink.states()
        # The CSV-mode fake is an already calibrated ESP32 (NET lines carry a real stream id).
        self.assertEqual(states[:2], ["connecting", "streaming"])
        self.assertNotIn("calibrating", states)
        self.assertEqual(sink.statuses[0]["endpoint"], f"{fake.host}:{fake.port}")
        streaming = next(st for st in sink.statuses if st.get("state") == "streaming")
        self.assertEqual(streaming["attempt"], 0)

        # Stop set by the first sample of a 3-line batch: no further sample(), prompt return.
        source = EspSource("esp", 1, retry_s=0.05, transport_factory=BurstTransport)
        sink, finished = run_source(source, lambda s: len(s.samples) >= 4)
        self.assertTrue(finished)
        self.assertFalse(sink.sample_after_stop)
        self.assertEqual([s.seq for s in sink.samples], [0, 1, 2, 3])
        self.assertIsNotNone(sink.exit_delay_s)
        self.assertLess(sink.exit_delay_s, 0.5)

    def test_reconnects_after_connection_closes(self):
        with FakeEsp32(self.csv, speed=50, close_after=60) as fake:
            source = EspSource(fake.host, fake.port, retry_s=0.05)
            sink, finished = run_source(source, lambda s: len(s.samples) >= 130)
            connections = fake.connections
        self.assertTrue(finished)
        self.assertGreaterEqual(connections, 3)
        self.assertIn("lost", sink.states())
        # Stopped mid-stream (more lines in flight): run() returns promptly, nothing after stop.
        self.assertFalse(sink.sample_after_stop)
        self.assertEqual(len(sink.samples), 130)
        self.assertIsNotNone(sink.exit_delay_s)
        self.assertLess(sink.exit_delay_s, 0.5)

    def test_busy_when_closed_before_any_line(self):
        with FakeEsp32(self.csv, reject_all=True) as fake:
            source = EspSource(fake.host, fake.port, retry_s=0.05)
            sink, finished = run_source(source, lambda s: "busy" in s.states())
        self.assertTrue(finished)
        self.assertEqual(sink.samples, [])
        self.assertNotIn("lost", sink.states())
        self.assertNotIn("calibrating", sink.states())
        self.assertEqual(sink.states(), ["connecting", "busy"])

        # An unexpected exception from the sink is reported as "error" and ends run().
        with FakeEsp32(self.csv, speed=20) as fake:
            source = EspSource(fake.host, fake.port, retry_s=0.05)
            sink, finished = run_source(source, lambda s: False, timeout=1.0, sink_cls=RaisingSink)
        self.assertFalse(finished)
        self.assertFalse(sink.alive_at_timeout)
        self.assertEqual(sink.states()[-1], "error")
        self.assertIn("ValueError", sink.statuses[-1]["message"])

    def test_calibrating_while_only_net_lines_arrive(self):
        with FakeEsp32(None, preamble=(NET,), idle_net_period_s=0.05) as fake:
            source = EspSource(fake.host, fake.port, retry_s=0.05, idle_timeout_s=0.3)
            sink, finished = run_source(source, lambda s: False, timeout=0.8)
        self.assertFalse(finished)
        self.assertEqual(sink.samples, [])
        self.assertEqual(sink.states()[-1], "calibrating")
        self.assertNotIn("lost", sink.states())

    def test_idle_connection_counts_as_lost(self):
        with FakeEsp32(None, preamble=(NET,), idle_net_period_s=30) as fake:
            source = EspSource(fake.host, fake.port, retry_s=0.05, idle_timeout_s=0.3)
            sink, finished = run_source(source, lambda s: "lost" in s.states())
        self.assertTrue(finished)
        self.assertEqual(sink.states(), ["connecting", "calibrating", "lost"])

        # No line at all, but the socket stays open: still "lost" (idle), never "busy".
        source = EspSource("esp", 1, retry_s=0.05, idle_timeout_s=0.2,
                           transport_factory=SilentTransport)
        started = time.monotonic()
        sink, finished = run_source(source, lambda s: "lost" in s.states())
        self.assertTrue(finished)
        self.assertGreaterEqual(time.monotonic() - started, 0.2)
        self.assertNotIn("busy", sink.states())
        self.assertEqual(sink.states(), ["connecting", "lost"])

        # A calibrated ESP32's NET line (non-empty stream id), then silence: not "calibrating".
        source = EspSource("esp", 1, retry_s=0.05, idle_timeout_s=0.2,
                           transport_factory=CalibratedNetThenSilentTransport)
        sink, finished = run_source(source, lambda s: "lost" in s.states())
        self.assertTrue(finished)
        self.assertEqual(sink.states(), ["connecting", "lost"])

    def test_parse_errors_are_counted_and_skipped(self):
        with FakeEsp32(self.csv, preamble=("DATA,1,broken",), speed=50, loop=False) as fake:
            source = EspSource(fake.host, fake.port, retry_s=0.05)
            sink, finished = run_source(
                source, lambda s: len(s.samples) >= 10 and any(st.get("parse_errors") for st in s.statuses))
        self.assertTrue(finished)
        self.assertEqual(max(st.get("parse_errors", 0) for st in sink.statuses), 1)

    def test_retries_when_connection_refused(self):
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        source = EspSource("127.0.0.1", port, retry_s=0.05, connect_timeout_s=1.0)
        sink, finished = run_source(source, lambda s: any(st.get("attempt", 0) >= 2 for st in s.statuses))
        self.assertTrue(finished)
        self.assertEqual(sink.samples, [])
        self.assertEqual(set(sink.states()), {"connecting"})
