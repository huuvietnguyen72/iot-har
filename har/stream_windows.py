"""Cut a live or replayed sample stream into model windows (same rules as collector_csv)."""
from collections import deque
import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .collector_csv import GAP_US, HEADER, _float, _int
from .config import STRIDE, WINDOW_SIZE


@dataclass(frozen=True)
class StreamSample:
    stream_id: str
    seq: int
    time_us: int
    values: tuple  # ax, ay, az (g), gx, gy, gz (deg/s)
    session_id: str | None = None
    label: str | None = None


@dataclass(frozen=True)
class StreamWindow:
    window: np.ndarray  # (128, 6); gyro in rad/s
    record: dict


class StreamWindower:
    def __init__(self):
        self.reset()

    def reset(self):
        self._buffer = deque(maxlen=WINDOW_SIZE)
        self._previous = None
        self._count = 0

    def _continues(self, sample):
        # Unlike collector_csv, a non-increasing seq/time starts a new segment instead of
        # raising, so a live stream survives ESP32 reboots and duplicated lines.
        p = self._previous
        return (p is not None
                and (p.session_id, p.stream_id, p.label)
                == (sample.session_id, sample.stream_id, sample.label)
                and sample.seq == p.seq + 1
                and 0 < sample.time_us - p.time_us <= GAP_US)

    def push(self, sample):
        """Add one sample; return (started_new_segment, StreamWindow or None)."""
        new_segment = not self._continues(sample)
        if new_segment:
            self._buffer.clear()
            self._count = 0
        self._buffer.append(sample)
        self._previous = sample
        self._count += 1
        if self._count < WINDOW_SIZE or (self._count - WINDOW_SIZE) % STRIDE:
            return new_segment, None
        samples = list(self._buffer)
        values = np.array([s.values for s in samples], dtype=np.float64)
        values[:, 3:6] = np.deg2rad(values[:, 3:6])
        first, last = samples[0], samples[-1]
        record = {"session_id": first.session_id, "stream_id": first.stream_id,
                  "label": first.label, "start_seq": first.seq, "end_seq": last.seq,
                  "start_time_us": first.time_us, "end_time_us": last.time_us}
        return new_segment, StreamWindow(values, record)


def read_csv_samples(csv_path):
    """Yield StreamSample rows of a collector CSV, with the same field parsing as collector_csv."""
    with Path(csv_path).open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        if next(reader, None) != HEADER:
            raise ValueError("unexpected collector CSV header")
        for number, row in enumerate(reader, start=2):
            if not row:
                continue
            if len(row) != len(HEADER):
                raise ValueError(f"row {number} has {len(row)} fields")
            yield StreamSample(
                stream_id=row[2], seq=_int(row[3], "seq"), time_us=_int(row[4], "device_time_us"),
                values=tuple(_float(row[6 + i], HEADER[6 + i]) for i in range(6)),
                session_id=row[0], label=row[1])
