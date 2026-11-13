"""Barometer feature: slope maths, .baro.csv loading, windows and stairs training."""
import contextlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np

from har.artifact import load_bundle, uses_pressure
from har.collector_csv import load_collector_windows
from har.config import ALLOWED_LABELS, LABELS
from har.features import extract_features, feature_names
from har.own_dataset import load_own_sessions
from har.pressure import (BARO_HEADER, MIN_READINGS, PRESSURE_FEATURE, baro_path_for,
                          load_baro_csv, pressure_slope, window_slopes)
from har.tests.fixtures import MINI_GRID, write_own_dataset, write_own_session
from har.train_own import train_own


class SlopeTests(unittest.TestCase):
    def test_exact_line(self):
        times = [i * 100_000 for i in range(25)]  # 10 Hz for 2.4 s
        pressures = [100000.0 - 3.0 * t / 1e6 for t in times]
        self.assertAlmostEqual(pressure_slope(times, pressures), -3.0, places=6)

    def test_offset_does_not_matter(self):
        times = [5_000_000 + i * 100_000 for i in range(25)]
        a = pressure_slope(times, [90000.0 + 2.0 * (t - times[0]) / 1e6 for t in times])
        b = pressure_slope(times, [101000.0 + 2.0 * (t - times[0]) / 1e6 for t in times])
        self.assertAlmostEqual(a, b, places=6)

    def test_too_few_readings_or_no_spread(self):
        self.assertIsNone(pressure_slope(list(range(MIN_READINGS - 1)), [1.0] * (MIN_READINGS - 1)))
        self.assertIsNone(pressure_slope([7] * 20, list(range(20))))


class BaroFileTests(unittest.TestCase):
    def test_load_and_header_check(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.baro.csv"
            path.write_text(",".join(BARO_HEADER) + "\ns,aaaa,0,500,100812.44,28.41\n\n",
                            encoding="utf-8")
            self.assertEqual(load_baro_csv(path), [("aaaa", 500, 100812.44)])
            path.write_text("wrong,header\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "header"):
                load_baro_csv(path)
            path.write_text(",".join(BARO_HEADER) + "\ns,aaaa,0,500,nan,28.41\n",
                            encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "finite"):
                load_baro_csv(path)

    def test_baro_path_is_next_to_the_csv(self):
        self.assertEqual(baro_path_for(Path("data/x/20261014T042223Z-e1354d0d.csv")),
                         Path("data/x/20261014T042223Z-e1354d0d.baro.csv"))

    def test_window_slopes_match_stream_and_time(self):
        records = [{"stream_id": "a", "start_time_us": 0, "end_time_us": 2_540_000},
                   {"stream_id": "b", "start_time_us": 0, "end_time_us": 2_540_000}]
        rows = [("a", t, 100000.0 - 3.0 * t / 1e6) for t in range(0, 3_000_000, 100_000)]
        slopes = window_slopes(records, rows)
        self.assertAlmostEqual(slopes[0], -3.0, places=6)
        self.assertTrue(np.isnan(slopes[1]))  # no readings of stream b


class FeatureTests(unittest.TestCase):
    def test_pressure_is_the_71st_feature(self):
        windows = np.random.default_rng(1).normal(0, 0.1, (3, 128, 6))
        motion = extract_features(windows)
        both = extract_features(windows, np.array([-3.0, 0.0, 3.0]))
        self.assertEqual(motion.shape, (3, 70))
        self.assertEqual(both.shape, (3, 71))
        np.testing.assert_array_equal(both[:, :70], motion)
        np.testing.assert_array_equal(both[:, 70], [-3.0, 0.0, 3.0])
        self.assertEqual(feature_names(pressure=True)[-1], PRESSURE_FEATURE)
        self.assertEqual(len(feature_names()), 70)

    def test_missing_or_wrong_length_pressure_is_rejected(self):
        windows = np.zeros((2, 128, 6))
        with self.assertRaisesRegex(ValueError, "pressure"):
            extract_features(windows, np.array([1.0, np.nan]))
        with self.assertRaisesRegex(ValueError, "pressure"):
            extract_features(windows, np.array([1.0]))


class WindowsWithBaroTests(unittest.TestCase):
    def test_collector_windows_carry_slopes(self):
        with TemporaryDirectory() as tmp:
            json_path = write_own_session(tmp, "s1", "stairs_up", "2026-10-14T08:00:00Z",
                                          baro=True)
            csv_path = json_path.with_suffix(".csv")
            plain = load_collector_windows(csv_path)
            loaded = load_collector_windows(csv_path, baro_path_for(csv_path))
            self.assertIsNone(plain.pressure)
            self.assertEqual(len(loaded.pressure), len(loaded.windows))
            self.assertEqual(loaded.quality["windows_without_pressure"], 0)
            self.assertTrue(np.all(np.abs(loaded.pressure + 3.0) < 0.5))

    def test_sessions_with_and_without_baro(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_own_session(folder, "with", "walk", "2026-10-14T08:00:00Z", baro=True)
            windows, sessions = load_own_sessions(folder, "train")
            self.assertEqual(len(windows.pressure), len(windows.labels))
            self.assertTrue(sessions[0]["has_pressure"])
            write_own_session(folder, "without", "sit", "2026-10-14T08:03:00Z")
            windows, sessions = load_own_sessions(folder, "train")
            self.assertIsNone(windows.pressure)  # not every session has a barometer file

    def test_missing_baro_file_rejects_the_session(self):
        with TemporaryDirectory() as tmp:
            write_own_session(tmp, "s1", "walk", "2026-10-14T08:00:00Z", baro=True)
            Path(tmp, "s1.baro.csv").unlink()
            _, sessions = load_own_sessions(tmp, "train")
            self.assertFalse(sessions[0]["accepted"])
            self.assertIn("barometer file", sessions[0]["reason"])


class StairsTrainingTests(unittest.TestCase):
    def test_stairs_labels_use_the_pressure_feature(self):
        with TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as out:
            tmp = Path(tmp)
            train_dir, test_dir = write_own_dataset(tmp / "data", labels=ALLOWED_LABELS,
                                                    baro=True)
            run = tmp / "run"
            result = train_own(train_dir, test_dir, run, grid=MINI_GRID)
            self.assertIn("barometer slope", out.getvalue())
            self.assertEqual(result["labels"], list(ALLOWED_LABELS))
            self.assertTrue(result["pressure_feature"])
            # Stairs move like walk in the fixture: only the pressure feature separates them,
            # so without it walk/up/down would be a three-way coin toss (macro-F1 about 0.78).
            self.assertGreater(result["test"]["selected"]["macro_f1"], 0.9)
            matrix = result["test"]["selected"]["confusion_matrix"]
            up, down = ALLOWED_LABELS.index("stairs_up"), ALLOWED_LABELS.index("stairs_down")
            self.assertEqual((matrix[up][down], matrix[down][up]), (0, 0))
            estimator, metadata = load_bundle(run)
            self.assertTrue(uses_pressure(metadata))
            self.assertEqual(estimator.n_features_in_, 71)
            self.assertEqual(set(estimator.classes_), set(ALLOWED_LABELS))
            report = (run / "report.md").read_text(encoding="utf-8")
            self.assertIn("stairs_up", report)
            self.assertIn("đặc trưng áp suất", report)

    def test_stairs_without_barometer_is_an_error(self):
        with TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            tmp = Path(tmp)
            train_dir, test_dir = write_own_dataset(tmp / "data", labels=ALLOWED_LABELS)
            with self.assertRaisesRegex(ValueError, "barometer"):
                train_own(train_dir, test_dir, tmp / "run", grid=MINI_GRID)
            self.assertFalse((tmp / "run").exists())

    def test_barometer_without_stairs_keeps_the_motion_model(self):
        with TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            tmp = Path(tmp)
            train_dir, test_dir = write_own_dataset(tmp / "data", baro=True)
            result = train_own(train_dir, test_dir, tmp / "run", grid=MINI_GRID)
            self.assertEqual(result["labels"], list(LABELS))
            self.assertFalse(result["pressure_feature"])
            _, metadata = load_bundle(tmp / "run")
            self.assertFalse(uses_pressure(metadata))

    def test_stairs_in_test_but_not_train_is_an_error(self):
        with TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            tmp = Path(tmp)
            train_dir, test_dir = write_own_dataset(tmp / "data", baro=True)
            write_own_session(test_dir, "test-up", "stairs_up", "2026-10-15T08:00:00Z",
                              baro=True)
            with self.assertRaisesRegex(ValueError, "stairs_up"):
                train_own(train_dir, test_dir, tmp / "run", grid=MINI_GRID)


class SampleModelTests(unittest.TestCase):
    def test_the_bundled_four_activity_model_still_loads(self):
        run = Path(__file__).resolve().parents[2] / "har_runs" / "own_rf_01"
        if not (run / "model.joblib").exists():
            self.skipTest("sample model not present")
        estimator, metadata = load_bundle(run)
        self.assertFalse(uses_pressure(metadata))
        self.assertEqual(estimator.n_features_in_, 70)
        self.assertEqual(json.loads((run / "metadata.json").read_text(encoding="utf-8"))["labels"],
                         list(LABELS))


if __name__ == "__main__":
    unittest.main()
