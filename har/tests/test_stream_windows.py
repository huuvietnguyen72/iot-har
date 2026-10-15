from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np

from har.collector_csv import HEADER, load_collector_windows
from har.stream_windows import StreamSample, StreamWindower, read_csv_samples


def write_rows(path, rows):
    """rows: (session_id, label, stream_id, seq, device_time_us)."""
    rng = np.random.default_rng(7)
    lines = [",".join(HEADER)]
    for i, (session, label, stream, seq, time_us) in enumerate(rows):
        values = rng.normal(0, 1, 6)
        lines.append(",".join([session, label, stream, str(seq), str(time_us), f"{i * 0.02:.3f}",
                               *(f"{v:.6f}" for v in values), "25.0"]))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def scenario_rows():
    a, b = "a" * 16, "b" * 16
    rows = [("s1", "walk", a, seq, seq * 20000) for seq in range(300)]            # 3 windows
    rows += [("s1", "walk", a, seq, seq * 20000) for seq in range(303, 500)]      # seq jump: 2 windows
    base = 499 * 20000 + 120000                                                   # 120 ms gap
    rows += [("s1", "walk", a, 500 + k, base + k * 20000) for k in range(200)]    # 2 windows
    rows += [("s2", "sit", b, k, k * 20000) for k in range(130)]                  # new session: 1 window
    return rows


def sample(seq, time_us, stream="a" * 16):
    return StreamSample(stream, seq, time_us, (0.0, 0.0, 1.0, 0.0, 0.0, 0.0))


class StreamWindowerTests(unittest.TestCase):
    def test_matches_collector_csv_windows_and_records(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "scenario.csv"
            write_rows(path, scenario_rows())
            expected = load_collector_windows(path)
            windower = StreamWindower()
            windows, records, segments = [], [], 0
            for s in read_csv_samples(path):
                new_segment, window = windower.push(s)
                segments += int(new_segment)
                if window is not None:
                    windows.append(window.window)
                    records.append(window.record)
            self.assertEqual(segments, 4)
            self.assertEqual(len(windows), 8)
            self.assertTrue(np.array_equal(np.stack(windows), expected.windows))
            self.assertEqual(records, expected.records)

    def test_gyro_is_converted_to_radians(self):
        windower = StreamWindower()
        window = None
        for i in range(128):
            _, window = windower.push(StreamSample("a" * 16, i, i * 20000,
                                                   (0.1, 0.2, 0.3, 180.0, 90.0, -45.0)))
        np.testing.assert_allclose(window.window[0], [0.1, 0.2, 0.3, np.pi, np.pi / 2, -np.pi / 4])

    def test_windows_every_stride_after_first(self):
        windower = StreamWindower()
        emitted = [i for i in range(320) if windower.push(sample(i, i * 20000))[1] is not None]
        self.assertEqual(emitted, [127, 191, 255, 319])

    def test_non_increasing_sample_starts_new_segment_instead_of_failing(self):
        windower = StreamWindower()
        self.assertTrue(windower.push(sample(0, 0))[0])
        self.assertFalse(windower.push(sample(1, 20000))[0])
        self.assertTrue(windower.push(sample(1, 20000))[0])
        self.assertTrue(windower.push(sample(2, 10000))[0])

    def test_reset_forgets_previous_samples(self):
        windower = StreamWindower()
        for i in range(100):
            windower.push(sample(i, i * 20000))
        windower.reset()
        new_segment, window = windower.push(sample(100, 100 * 20000))
        self.assertTrue(new_segment)
        self.assertIsNone(window)

    def test_read_csv_samples_rejects_bad_header_and_rows(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            path.write_text("a,b\n1,2\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                list(read_csv_samples(path))
            path.write_text(",".join(HEADER) + "\n1,2,3\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                list(read_csv_samples(path))
