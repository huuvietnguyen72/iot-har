"""A stairs model with the pressure feature, end to end: replay, live TCP, predict-csv."""
from collections import Counter
import contextlib
import io
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import threading
import unittest

from har.config import ALLOWED_LABELS
from har.fake_esp32 import FakeEsp32
from har.inference import predict_csv
from har.live_pipeline import NO_PRESSURE_MESSAGE, LivePipeline
from har.live_predict import LivePredictor
from har.sources import EspSource, ReplaySource
from har.tests.fixtures import MINI_GRID, write_own_dataset
from har.tests.test_esp_source import run_source
from har.train_own import train_own


class Events:
    def __init__(self):
        self.events = []

    def __call__(self, event, data):
        self.events.append((event, data))

    def predictions(self):
        return [d for e, d in self.events if e == "prediction"]

    def statuses(self):
        return [d for e, d in self.events if e == "status"]


class FastClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class StairsModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = TemporaryDirectory()
        root = Path(cls._tmp.name)
        with contextlib.redirect_stdout(io.StringIO()):
            cls.train_dir, cls.test_dir = write_own_dataset(root / "data", labels=ALLOWED_LABELS,
                                                            baro=True)
            cls.run_dir = root / "run"
            train_own(cls.train_dir, cls.test_dir, cls.run_dir, grid=MINI_GRID)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def csv(self, label, k=0):
        return self.test_dir / f"test-{label}-{k}.csv"

    def replay(self, csv_paths):
        events = Events()
        pipeline = LivePipeline(LivePredictor(self.run_dir), events)
        pipeline.start("replay", ["x"], 4)
        clock = FastClock()
        source = ReplaySource(csv_paths, 4, clock=clock, sleep=clock.sleep)
        source.run(pipeline, threading.Event())
        return events

    def test_replay_with_barometer_recognises_stairs(self):
        for label in ("stairs_up", "stairs_down"):
            events = self.replay([self.csv(label)])
            labels = Counter(p["raw_label"] for p in events.predictions())
            self.assertGreater(sum(labels.values()), 0, label)
            self.assertEqual(labels.most_common(1)[0][0], label)

    def test_replay_without_barometer_file_says_so(self):
        with TemporaryDirectory() as tmp:
            copy = Path(tmp) / self.csv("stairs_up").name
            shutil.copy(self.csv("stairs_up"), copy)  # CSV only, no .baro.csv
            events = self.replay([copy])
        self.assertEqual(events.predictions(), [])
        self.assertTrue(any(s.get("message") == NO_PRESSURE_MESSAGE for s in events.statuses()))

    def test_live_tcp_forwards_baro_lines(self):
        events = Events()
        pipeline = LivePipeline(LivePredictor(self.run_dir), events)
        with FakeEsp32(self.csv("stairs_down"), speed=20, loop=True) as fake:
            source = EspSource(fake.host, fake.port, retry_s=0.05)

            class Sink:
                def sample(self, s):
                    pipeline.sample(s)

                def status(self, **fields):
                    pipeline.status(**fields)

                def pressure(self, *reading):
                    pipeline.pressure(*reading)

            stop = threading.Event()
            thread = threading.Thread(target=source.run, args=(Sink(), stop), daemon=True)
            thread.start()
            for _ in range(300):
                if len(events.predictions()) >= 3:
                    break
                stop.wait(0.05)
            stop.set()
            thread.join(timeout=10)
        labels = Counter(p["raw_label"] for p in events.predictions())
        self.assertGreaterEqual(sum(labels.values()), 3)
        self.assertEqual(labels.most_common(1)[0][0], "stairs_down")

    def test_motion_only_sinks_ignore_baro_lines(self):
        with FakeEsp32(self.csv("stairs_up"), speed=20, loop=False) as fake:
            source = EspSource(fake.host, fake.port, retry_s=0.05)
            sink, finished = run_source(source, lambda s: len(s.samples) >= 150)
        self.assertTrue(finished)
        self.assertEqual(max((st.get("parse_errors", 0) for st in sink.statuses), default=0), 0)

    def test_predict_csv_uses_the_baro_file(self):
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "replay.json"
            result = predict_csv(self.run_dir, self.csv("stairs_up", 1), output)
            predictions = Counter(w["prediction"] for w in result["windows"])
            self.assertEqual(predictions.most_common(1)[0][0], "stairs_up")
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["labels"],
                             result["labels"])
            copy = Path(tmp) / "alone.csv"
            shutil.copy(self.csv("stairs_up", 1), copy)
            with self.assertRaisesRegex(ValueError, "barometer"):
                predict_csv(self.run_dir, copy, Path(tmp) / "other.json")


if __name__ == "__main__":
    unittest.main()
