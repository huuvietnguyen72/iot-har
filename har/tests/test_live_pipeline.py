from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

import numpy as np

from har.collector_csv import load_collector_windows
from har.inference import predict_windows
from har.live_pipeline import HISTORY_LIMIT, SAMPLE_BATCH_LIMIT, LivePipeline
from har.live_predict import LivePredictor
from har.stream_windows import StreamSample, read_csv_samples
from har.tests.fixtures import write_own_session
from har.tests.test_inference import build_run


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class StubPredictor:
    labels = ["walk", "sit", "stand", "lie"]

    def __init__(self, label="walk"):
        self.label = label
        self.resets = 0
        self.calls = 0

    def reset(self):
        self.resets += 1

    def predict(self, window):
        self.calls += 1
        return {"raw_label": self.label, "raw_probabilities": [1.0, 0.0, 0.0, 0.0],
                "label": self.label, "probabilities": [1.0, 0.0, 0.0, 0.0],
                "uncertain": False, "predict_ms": float(self.calls)}


def samples(count, *, start_seq=0, stream="a" * 16, session=None, label=None, step_us=20000):
    return [StreamSample(stream, seq, seq * step_us, (0.1, 0.2, 1.0, 0.0, 0.0, 0.0), session, label)
            for seq in range(start_seq, start_seq + count)]


class Recorder:
    def __init__(self):
        self.events = []

    def __call__(self, event, data):
        json.dumps(data, allow_nan=False)  # every event must be JSON-serialisable
        self.events.append((event, data))

    def of(self, name):
        return [d for e, d in self.events if e == name]


def make(label="walk", mode="live"):
    clock, recorder, predictor = FakeClock(), Recorder(), StubPredictor(label)
    pipeline = LivePipeline(predictor, recorder, clock=clock, wall=lambda: 1000.0)
    if mode != "live":
        pipeline.start(mode, ["s1"], 4)
    return pipeline, recorder, predictor, clock


class LivePipelineTests(unittest.TestCase):
    def test_start_announces_mode(self):
        pipeline, recorder, _, _ = make()
        status = recorder.of("status")[-1]
        self.assertEqual((status["mode"], status["state"], status["collecting"]), ("live", "starting", True))
        pipeline.start("replay", ["x", "y"], 2)
        status = recorder.of("status")[-1]
        self.assertEqual((status["mode"], status["sessions"], status["speed"]), ("replay", ["x", "y"], 2))

    def test_predictions_every_stride(self):
        pipeline, recorder, _, _ = make()
        for s in samples(192):
            pipeline.sample(s)
        predictions = recorder.of("prediction")
        self.assertEqual([p["index"] for p in predictions], [0, 1])
        self.assertEqual(predictions[0]["time"], 1000.0)
        self.assertIsNone(predictions[0]["true_label"])
        self.assertFalse(pipeline.snapshot()["status"]["collecting"])

    def test_seq_jump_counts_missing_and_resets_smoothing(self):
        pipeline, recorder, predictor, _ = make()
        resets = predictor.resets
        for s in samples(10) + samples(10, start_seq=13):
            pipeline.sample(s)
        self.assertEqual(pipeline.snapshot()["status"]["missing"], 3)
        self.assertEqual(predictor.resets, resets + 2)  # first sample and the jump

    def test_new_segment_after_prediction_emits_collecting_status(self):
        pipeline, recorder, _, _ = make()
        for s in samples(128) + samples(5, start_seq=200):
            pipeline.sample(s)
        self.assertTrue(recorder.of("status")[-1]["collecting"])

    def test_stream_change_counts_restart_only_in_live_mode(self):
        pipeline, _, _, _ = make()
        for s in samples(5) + samples(5, start_seq=100, stream="b" * 16):
            pipeline.sample(s)
        self.assertEqual(pipeline.snapshot()["status"]["restarts"], 1)
        self.assertEqual(pipeline.snapshot()["status"]["missing"], 0)
        pipeline.start("replay", ["s1"], 1)
        for s in samples(5) + samples(5, stream="b" * 16):
            pipeline.sample(s)
        self.assertEqual(pipeline.snapshot()["status"]["restarts"], 0)

    def test_replay_accuracy_and_true_label(self):
        pipeline, recorder, _, _ = make("walk", mode="replay")
        for s in samples(192, session="s1", label="walk"):
            pipeline.sample(s)
        self.assertEqual(recorder.of("prediction")[-1]["true_label"], "walk")
        self.assertEqual(pipeline.snapshot()["status"]["replay_accuracy"], 1.0)
        pipeline, _, _, _ = make("sit", mode="replay")
        for s in samples(128, session="s1", label="walk"):
            pipeline.sample(s)
        self.assertEqual(pipeline.snapshot()["status"]["replay_accuracy"], 0.0)
        pipeline, _, _, _ = make("walk", mode="replay")
        for s in samples(10, session="s1", label="walk") + samples(10, start_seq=50, session="s2", label="walk"):
            pipeline.sample(s)
        self.assertEqual(pipeline.snapshot()["status"]["missing"], 0)

    def test_tick_flushes_sample_batches(self):
        pipeline, recorder, _, _ = make()
        for s in samples(3):
            pipeline.sample(s)
        pipeline.tick()
        pipeline.tick()
        batches = recorder.of("samples")
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0]["samples"], [[0.02, 0.1, 0.2, 1.0], [0.04, 0.1, 0.2, 1.0],
                                                 [0.06, 0.1, 0.2, 1.0]])

    def test_rate_and_stale_signal(self):
        pipeline, recorder, _, clock = make()
        pipeline.status(state="streaming")
        for s in samples(251):
            pipeline.sample(s)
            clock.now += 0.02
        self.assertAlmostEqual(pipeline.snapshot()["status"]["rate_hz"], 50.0, places=1)
        self.assertFalse(pipeline.snapshot()["status"]["stale"])
        clock.now += 2.5
        pipeline.tick()
        self.assertTrue(recorder.of("status")[-1]["stale"])
        self.assertEqual(pipeline.snapshot()["status"]["rate_hz"], 0.0)
        pipeline.status(state="lost")
        self.assertFalse(recorder.of("status")[-1]["stale"])

    def test_status_updates_and_periodic_status(self):
        pipeline, recorder, _, clock = make()
        pipeline.status(state="connecting", attempt=2, endpoint="1.2.3.4:8765")
        last = recorder.of("status")[-1]
        self.assertEqual((last["state"], last["attempt"], last["endpoint"]),
                         ("connecting", 2, "1.2.3.4:8765"))
        count = len(recorder.of("status"))
        clock.now += 1.1
        pipeline.tick()
        self.assertEqual(len(recorder.of("status")), count + 1)

    def test_predict_p95_and_history_snapshot(self):
        pipeline, _, _, _ = make()
        for s in samples(128 + 64 * 9):
            pipeline.sample(s)
        snap = pipeline.snapshot()
        self.assertEqual(len(snap["history"]), 10)
        self.assertEqual(snap["latest"]["index"], 9)
        self.assertAlmostEqual(snap["status"]["predict_p95_ms"], float(np.percentile(range(1, 11), 95)))
        self.assertEqual(snap["labels"], StubPredictor.labels)
        self.assertEqual(HISTORY_LIMIT, 2000)
        pipeline, _, _, clock = make()
        for s in samples(5000):
            pipeline.sample(s)
            clock.now += 0.02
        self.assertLessEqual(len(pipeline._batch), SAMPLE_BATCH_LIMIT)
        self.assertLessEqual(len(pipeline._arrivals), 300)

    def test_raw_labels_match_predict_windows_on_session_csv(self):
        with TemporaryDirectory() as tmp:
            run = build_run(tmp)
            csv_path = write_own_session(Path(tmp) / "s", "s1", "walk", "2026-10-14T08:00:00Z",
                                         seconds=10).with_suffix(".csv")
            recorder = Recorder()
            pipeline = LivePipeline(LivePredictor(run), recorder)
            pipeline.start("replay", ["s1"], 4)
            for s in read_csv_samples(csv_path):
                pipeline.sample(s)
            predictions = recorder.of("prediction")
            batch = predict_windows(run, load_collector_windows(csv_path).windows)
            self.assertEqual(len(predictions), len(batch["predictions"]))
            np.testing.assert_allclose([p["raw_probabilities"] for p in predictions],
                                       batch["probabilities"], rtol=0, atol=1e-12)
