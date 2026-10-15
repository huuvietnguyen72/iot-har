from pathlib import Path
from tempfile import TemporaryDirectory
import json
import threading
import time
import unittest

from har.sources import REPLAY_SPEEDS, ReplaySource, list_replay_sessions, parse_endpoint
from har.tests.fixtures import write_own_dataset, write_own_session


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Sink:
    def __init__(self, stop=None, stop_after=None):
        self.samples, self.statuses = [], []
        self._stop, self._stop_after = stop, stop_after

    def sample(self, s):
        self.samples.append(s)
        if self._stop_after and len(self.samples) >= self._stop_after:
            self._stop.set()

    def status(self, **fields):
        self.statuses.append(fields)


class ParseEndpointTests(unittest.TestCase):
    def test_valid_and_invalid(self):
        self.assertEqual(parse_endpoint("192.168.1.2:8765"), ("192.168.1.2", 8765))
        self.assertEqual(parse_endpoint("mpu6050-esp32.local:1"), ("mpu6050-esp32.local", 1))
        for bad in ("nohost", ":8765", "host:", "host:abc", "host:0", "host:70000",
                    "foo..bar:8765", " host:8765"):
            with self.assertRaises(ValueError):
                parse_endpoint(bad)


class ListReplaySessionsTests(unittest.TestCase):
    def test_lists_valid_sessions_test_first(self):
        with TemporaryDirectory() as tmp:
            write_own_dataset(tmp, train_sessions=1, test_sessions=1)
            sessions = list_replay_sessions(tmp)
            self.assertEqual(len(sessions), 8)
            self.assertEqual([s["split"] for s in sessions], ["test"] * 4 + ["train"] * 4)
            self.assertEqual([s["label"] for s in sessions[:4]], ["walk", "sit", "stand", "lie"])
            self.assertEqual(set(sessions[0]), {"session_id", "split", "label", "started_utc", "csv"})
            self.assertTrue(sessions[0]["csv"].is_file())

    def test_skips_rejected_and_duplicate_sessions(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_own_session(root / "test", "good", "walk", "2026-10-14T08:00:00Z", seconds=1)
            write_own_session(root / "test", "bad", "walk", "2026-10-14T08:03:00Z", seconds=1,
                              meta={"status": "interrupted"})
            dup = write_own_session(root / "train", "x", "sit", "2026-10-14T09:00:00Z", seconds=1)
            meta = json.loads(dup.read_text(encoding="utf-8"))
            meta["session_id"] = "good"
            dup.write_text(json.dumps(meta), encoding="utf-8")
            (root / "test" / "broken.json").write_text("{", encoding="utf-8")
            kept = list_replay_sessions(root)
            self.assertEqual([s["session_id"] for s in kept], ["good"])
            self.assertEqual(kept[0]["split"], "test")

    def test_missing_dirs_give_empty_list(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(list_replay_sessions(tmp), [])


class ReplaySourceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        root = Path(self._tmp.name)
        self.walk = write_own_session(root, "w", "walk", "2026-10-14T08:00:00Z", seconds=2).with_suffix(".csv")
        self.sit = write_own_session(root, "s", "sit", "2026-10-14T08:03:00Z", seconds=2).with_suffix(".csv")

    def tearDown(self):
        self._tmp.cleanup()

    def run_replay(self, paths, speed):
        clock = FakeClock()
        sink = Sink()
        ReplaySource(paths, speed, clock=clock, sleep=clock.sleep).run(sink, threading.Event())
        return sink, clock

    def test_paces_at_real_time_and_faster(self):
        for speed in (1, 4):
            clock = FakeClock()
            arrivals = []
            sink = Sink()
            sink.sample = lambda s, a=arrivals, c=clock: a.append(c.now)
            ReplaySource([self.walk], speed, clock=clock, sleep=clock.sleep).run(sink, threading.Event())
            self.assertEqual(len(arrivals), 100)
            for k, t in enumerate(arrivals):
                self.assertAlmostEqual(t, k * 0.02 / speed, places=6)
        # a huge forward jump is paced as one normal period
        lines = self.walk.read_text(encoding="utf-8").splitlines()
        cols = lines[3].split(",")
        cols[4] = str(10**15)
        lines[3] = ",".join(cols)
        jump = Path(self._tmp.name) / "jump.csv"
        jump.write_text("\n".join(lines) + "\n", encoding="utf-8")
        clock = FakeClock()
        arrivals = []
        sink = Sink()
        sink.sample = lambda s: arrivals.append(clock.now)
        ReplaySource([jump], 1, clock=clock, sleep=clock.sleep).run(sink, threading.Event())
        self.assertEqual(len(arrivals), 100)
        for k, t in enumerate(arrivals):
            self.assertAlmostEqual(t, k * 0.02, places=6)

    def test_plays_sessions_back_to_back_with_labels(self):
        sink, clock = self.run_replay([self.walk, self.sit], 2)
        self.assertEqual(len(sink.samples), 200)
        self.assertEqual({s.label for s in sink.samples[:100]}, {"walk"})
        self.assertEqual({s.session_id for s in sink.samples[100:]}, {"s"})
        self.assertAlmostEqual(clock.now, (99 * 0.02 + 0.02 + 99 * 0.02) / 2, places=6)
        states = [(st.get("state"), st.get("session")) for st in sink.statuses]
        self.assertEqual(states, [("replaying", "w"), ("replaying", "s"), ("finished", None)])

    def test_stop_ends_replay(self):
        stop = threading.Event()
        sink = Sink(stop, stop_after=10)
        clock = FakeClock()
        ReplaySource([self.walk, self.sit], 1, clock=clock, sleep=clock.sleep).run(sink, stop)
        self.assertEqual(len(sink.samples), 10)
        self.assertNotIn("finished", [st.get("state") for st in sink.statuses])
        # default sleep (stop.wait) returns promptly when stopped
        real_stop = threading.Event()
        real_sink = Sink()
        timer = threading.Timer(0.1, real_stop.set)
        timer.start()
        t0 = time.monotonic()
        ReplaySource([self.walk], 1).run(real_sink, real_stop)
        timer.cancel()
        self.assertLess(time.monotonic() - t0, 1.0)
        self.assertNotIn("finished", [st.get("state") for st in real_sink.statuses])

    def test_bad_csv_reports_error(self):
        bad = Path(self._tmp.name) / "bad.csv"
        bad.write_text("x\n", encoding="utf-8")
        sink, _ = self.run_replay([bad], 1)
        self.assertEqual(sink.statuses[-1]["state"], "error")
        self.assertIn("header", sink.statuses[-1]["message"])
        self.assertIn("bad.csv", sink.statuses[-1]["message"])
        lines = self.walk.read_text(encoding="utf-8").splitlines()[:51] + ["a,b,c"]
        short = Path(self._tmp.name) / "short.csv"
        short.write_text("\n".join(lines) + "\n", encoding="utf-8")
        sink, _ = self.run_replay([short], 1)
        self.assertGreater(len(sink.samples), 0)
        self.assertEqual(sink.statuses[-1]["state"], "error")
        self.assertIn("short.csv", sink.statuses[-1]["message"])
        self.assertIn("row", sink.statuses[-1]["message"])
        self.assertNotIn("finished", [st.get("state") for st in sink.statuses])

    def test_rejects_bad_arguments(self):
        self.assertEqual(REPLAY_SPEEDS, (1, 2, 4))
        with self.assertRaises(ValueError):
            ReplaySource([self.walk], 3)
        with self.assertRaises(ValueError):
            ReplaySource([], 1)
