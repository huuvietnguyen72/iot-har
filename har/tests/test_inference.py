import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

import numpy as np

from har.collector_csv import HEADER, load_collector_windows
from har.config import LABELS
from har.inference import benchmark, predict_csv, predict_windows
from har.tests.fixtures import MINI_GRID, grouped_fixture
from har.train import train_baseline


def build_run(root):
    run = Path(root) / "run"
    train_baseline(grouped_fixture(range(1, 11)), grouped_fixture([21, 22], "test"),
                   {"synthetic_fixture": True}, run, grid=MINI_GRID)
    return run


def write_csv(path, count=192):
    rows = [",".join(HEADER)]
    for i in range(count):
        rows.append(",".join(["s1", "test", "a" * 16, str(i), str(i * 20000), "0.0",
                              "0.0", "0.1", "1.0", "12.0", "0.0", "0.0", "25.0"]))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


class InferenceTests(unittest.TestCase):
    def test_predict_windows_labels_and_probabilities(self):
        with TemporaryDirectory() as tmp:
            run = build_run(tmp)
            windows = np.random.default_rng(0).normal(size=(3, 128, 6))
            result = predict_windows(run, windows)
            self.assertEqual(set(result["labels"]), set(LABELS))
            self.assertEqual(len(result["predictions"]), 3)
            probabilities = np.array(result["probabilities"])
            self.assertEqual(probabilities.shape, (3, 4))
            np.testing.assert_allclose(probabilities.sum(axis=1), 1.0, atol=1e-6)
            self.assertTrue(all(p in LABELS for p in result["predictions"]))

    def test_predict_empty_windows(self):
        with TemporaryDirectory() as tmp:
            result = predict_windows(build_run(tmp), np.empty((0, 128, 6)))
            self.assertEqual(result["predictions"], [])
            self.assertEqual(result["probabilities"], [])

    def test_predict_csv_scope(self):
        with TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            run = build_run(tmp)
            csv_path = tmp / "ref.csv"
            write_csv(csv_path)
            output = tmp / "replay.json"
            result = predict_csv(run, csv_path, output)
            self.assertEqual(result["scope"], "model_replay_not_activity_validation")
            self.assertEqual(len(result["windows"]), 2)
            self.assertIn("prediction", result["windows"][0])
            self.assertTrue(output.exists())

    def test_benchmark_timing_math_with_controlled_clock(self):
        with TemporaryDirectory() as tmp:
            run = build_run(tmp)
            windows = np.random.default_rng(1).normal(size=(5, 128, 6))
            for step, expected in ((1.0, True), (2.0, False)):
                ticks = iter(i * step for i in range(1000))
                with mock.patch("har.inference.time.perf_counter",
                                side_effect=lambda: float(next(ticks))):
                    result = benchmark(run, windows, warmup=1, repeats=3)
                self.assertEqual(len(result["durations_s"]), 3)
                self.assertAlmostEqual(result["median_s"], step)
                self.assertAlmostEqual(result["p95_s"], step)
                self.assertEqual(result["criterion_p95_under_1_28"], expected)

    def test_benchmark_writes_exclusive_output_and_rejects_empty(self):
        with TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            run = build_run(tmp)
            windows = np.random.default_rng(2).normal(size=(3, 128, 6))
            output = tmp / "bench.json"
            benchmark(run, windows, warmup=1, repeats=2, output_path=output)
            self.assertTrue(output.exists())
            with self.assertRaises(FileExistsError):
                benchmark(run, windows, warmup=1, repeats=2, output_path=output)
            with self.assertRaises(ValueError):
                benchmark(run, np.empty((0, 128, 6)))
