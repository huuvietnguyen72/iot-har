import unittest

from collector.protocol import Sample
from collector.quality import QualityTracker


def sample(seq, time_us, stream_id="7a31b25c809fd416"):
    return Sample(stream_id=stream_id, seq=seq, device_time_us=time_us,
                  ax_g=0.0, ay_g=0.0, az_g=1.0, gx_dps=0.0, gy_dps=0.0,
                  gz_dps=0.0, temp_c=25.0)


class QualityTrackerTests(unittest.TestCase):
    def test_first_sample_is_accepted(self):
        tracker = QualityTracker()
        self.assertTrue(tracker.record(sample(0, 1000)))
        self.assertEqual(tracker.samples_written, 1)

    def test_duplicate_seq_is_rejected(self):
        tracker = QualityTracker()
        tracker.record(sample(5, 1000))
        self.assertFalse(tracker.record(sample(5, 2000)))
        self.assertEqual(tracker.duplicates, 1)
        self.assertEqual(tracker.samples_written, 1)

    def test_out_of_order_seq_is_rejected(self):
        tracker = QualityTracker()
        tracker.record(sample(5, 1000))
        self.assertFalse(tracker.record(sample(3, 2000)))
        self.assertEqual(tracker.out_of_order, 1)

    def test_non_increasing_timestamp_is_rejected(self):
        tracker = QualityTracker()
        tracker.record(sample(1, 20000))
        self.assertFalse(tracker.record(sample(2, 20000)))
        self.assertEqual(tracker.timestamp_errors, 1)
        self.assertEqual(tracker.samples_written, 1)

    def test_missing_samples_counted_from_seq(self):
        tracker = QualityTracker()
        tracker.record(sample(5, 0))
        tracker.record(sample(8, 60000))
        self.assertEqual(tracker.missing_by_seq, 2)

    def test_gap_metrics(self):
        tracker = QualityTracker()
        tracker.record(sample(0, 0))
        tracker.record(sample(1, 30000))
        tracker.record(sample(2, 90000))
        self.assertEqual(tracker.max_gap_us, 60000)
        self.assertEqual(tracker.gaps_over_40ms, 1)

    def test_snapshot_rate_from_device_time(self):
        tracker = QualityTracker()
        for i in range(3):
            tracker.record(sample(i, i * 20000))
        snap = tracker.snapshot()
        self.assertEqual(snap["samples_written"], 3)
        self.assertAlmostEqual(snap["device_span_s"], 0.04, places=6)
        self.assertAlmostEqual(snap["sample_rate_hz"], 50.0, places=3)

    def test_error_and_oversize_counters(self):
        tracker = QualityTracker()
        tracker.record_error()
        tracker.record_oversize(2)
        snap = tracker.snapshot()
        self.assertEqual(snap["data_errors"], 1)
        self.assertEqual(snap["oversize_lines"], 2)


if __name__ == "__main__":
    unittest.main()
