import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from har.collector_csv import HEADER, load_collector_windows


def write_csv(path, rows):
    path.write_text("\n".join([",".join(HEADER)] + [",".join(map(str, r)) for r in rows]) + "\n",
                    encoding="utf-8")


def sample(seq, time_us, *, stream="a" * 16, label="walk", gx=180.0, session="s1"):
    return [session, label, stream, seq, time_us, "0.0", "0.0", "0.0", "1.0",
            gx, "0.0", "0.0", "25.0"]


class CollectorCsvTests(unittest.TestCase):
    def test_clean_stream(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "clean.csv"
            write_csv(path, [sample(i, i * 20000) for i in range(192)])
            loaded = load_collector_windows(path)
            self.assertEqual(loaded.windows.shape, (2, 128, 6))
            np.testing.assert_allclose(loaded.windows[:, :, 3], np.pi)
            self.assertEqual(loaded.records[0]["start_seq"], 0)
            self.assertEqual(loaded.records[1]["start_seq"], 64)
            self.assertEqual(loaded.quality["segments"], 1)

    def test_short_streams(self):
        for count, expected in ((127, 0), (128, 1)):
            with self.subTest(count=count), TemporaryDirectory() as tmp:
                path = Path(tmp) / "short.csv"
                write_csv(path, [sample(i, i * 20000) for i in range(count)])
                loaded = load_collector_windows(path)
                self.assertEqual(len(loaded.records), expected)
                self.assertEqual(loaded.quality["rows"], count)
                if expected == 0:
                    self.assertEqual(loaded.quality["incomplete_tail_samples"], count)

    def test_gap_is_not_bridged(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "gap.csv"
            rows = [sample(i, i * 20000) for i in range(64)]
            rows += [sample(64 + i, 64 * 20000 + 40001 + i * 20000) for i in range(64)]
            write_csv(path, rows)
            loaded = load_collector_windows(path)
            self.assertEqual(len(loaded.records), 0)
            self.assertEqual(loaded.quality["segments"], 2)
            self.assertGreaterEqual(loaded.quality["rejected_candidate_windows"], 1)

    def test_stream_change_splits(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "two.csv"
            rows = [sample(i, i * 20000, stream="a" * 16) for i in range(128)]
            rows += [sample(i, (128 + i) * 20000, stream="b" * 16) for i in range(128)]
            write_csv(path, rows)
            loaded = load_collector_windows(path)
            self.assertEqual(len(loaded.records), 2)
            self.assertEqual(loaded.quality["segments"], 2)
            self.assertEqual({r["stream_id"] for r in loaded.records}, {"a" * 16, "b" * 16})

    def test_test_label_retained(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.csv"
            write_csv(path, [sample(i, i * 20000, label="test") for i in range(128)])
            self.assertEqual(load_collector_windows(path).records[0]["label"], "test")

    def test_invalid_files_rejected(self):
        cases = {
            "header": [",".join(HEADER[:-1])],
            "nonfinite": [sample(0, 0)],
            "duplicate_seq": [sample(0, 0), sample(0, 20000)],
            "reverse_time": [sample(0, 20000), sample(1, 10000)],
        }
        with TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            bad_header = tmp / "bad_header.csv"
            bad_header.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_collector_windows(bad_header)
            nonfinite = tmp / "nonfinite.csv"
            write_csv(nonfinite, [sample(0, 0, gx=float("nan"))])
            with self.assertRaises(ValueError):
                load_collector_windows(nonfinite)
            duplicate = tmp / "dup.csv"
            write_csv(duplicate, cases["duplicate_seq"])
            with self.assertRaises(ValueError):
                load_collector_windows(duplicate)
            reverse = tmp / "rev.csv"
            write_csv(reverse, cases["reverse_time"])
            with self.assertRaises(ValueError):
                load_collector_windows(reverse)

    def test_round_trip_uses_same_features(self):
        from har.features import extract_features
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "clean.csv"
            write_csv(path, [sample(i, i * 20000) for i in range(192)])
            windows = load_collector_windows(path).windows
            self.assertEqual(extract_features(windows).shape, (2, 70))

    def test_quality_reports_first_and_last_time(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "times.csv"
            write_csv(path, [sample(i, 1000 + i * 20000) for i in range(130)])
            loaded = load_collector_windows(path)
            self.assertEqual(loaded.quality["first_time_us"], 1000)
            self.assertEqual(loaded.quality["last_time_us"], 1000 + 129 * 20000)
