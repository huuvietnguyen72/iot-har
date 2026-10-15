"""Track sample continuity and gap statistics for one recording session."""
from __future__ import annotations

GAP_WARNING_US = 40_000


class QualityTracker:
    def __init__(self):
        self.samples_written = 0
        self.data_errors = 0
        self.oversize_lines = 0
        self.missing_by_seq = 0
        self.duplicates = 0
        self.out_of_order = 0
        self.timestamp_errors = 0
        self.max_gap_us = 0
        self.gaps_over_40ms = 0
        self._last_seq = None
        self._last_time_us = None
        self._first_time_us = None

    def record_error(self):
        self.data_errors += 1

    def record_oversize(self, count):
        self.oversize_lines += count

    def record(self, sample):
        if self._last_seq is not None:
            if sample.seq == self._last_seq:
                self.duplicates += 1
                return False
            if sample.seq < self._last_seq:
                self.out_of_order += 1
                return False
            if sample.device_time_us <= self._last_time_us:
                self.timestamp_errors += 1
                return False
            self.missing_by_seq += sample.seq - self._last_seq - 1
            gap = sample.device_time_us - self._last_time_us
            if gap > self.max_gap_us:
                self.max_gap_us = gap
            if gap > GAP_WARNING_US:
                self.gaps_over_40ms += 1
        if self._first_time_us is None:
            self._first_time_us = sample.device_time_us
        self._last_seq = sample.seq
        self._last_time_us = sample.device_time_us
        self.samples_written += 1
        return True

    def snapshot(self):
        span_s = 0.0
        rate_hz = 0.0
        if self._first_time_us is not None and self.samples_written >= 2:
            span_s = (self._last_time_us - self._first_time_us) / 1e6
            if span_s > 0:
                rate_hz = (self.samples_written - 1) / span_s
        return {
            "samples_written": self.samples_written,
            "data_errors": self.data_errors,
            "oversize_lines": self.oversize_lines,
            "missing_by_seq": self.missing_by_seq,
            "duplicates": self.duplicates,
            "out_of_order": self.out_of_order,
            "timestamp_errors": self.timestamp_errors,
            "max_gap_us": self.max_gap_us,
            "gaps_over_40ms": self.gaps_over_40ms,
            "device_span_s": round(span_s, 6),
            "sample_rate_hz": round(rate_hz, 3),
        }
