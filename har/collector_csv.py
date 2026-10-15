from dataclasses import dataclass
from pathlib import Path
import csv
import math

import numpy as np

from .config import STRIDE, WINDOW_SIZE

HEADER = ["session_id", "label", "stream_id", "seq", "device_time_us",
          "host_elapsed_s", "ax_g", "ay_g", "az_g", "gx_dps", "gy_dps", "gz_dps", "temp_c"]
GAP_US = 40000


@dataclass(frozen=True)
class CollectorWindows:
    windows: np.ndarray
    records: list
    quality: dict


def _int(text, name):
    value = text.strip()
    if not value or not value.lstrip("+-").isdigit():
        raise ValueError(f"{name} is not an integer: {text!r}")
    return int(value)


def _float(text, name):
    try:
        value = float(text)
    except ValueError as exc:
        raise ValueError(f"{name} is not a number: {text!r}") from exc
    if not math.isfinite(value):
        raise ValueError(f"{name} is not finite: {text!r}")
    return value


def load_collector_windows(csv_path):
    path = Path(csv_path)
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError("empty CSV file") from exc
        if header != HEADER:
            raise ValueError("unexpected collector CSV header")
        rows = []
        for number, row in enumerate(reader, start=2):
            if not row:
                continue
            if len(row) != len(HEADER):
                raise ValueError(f"row {number} has {len(row)} fields")
            seq = _int(row[3], "seq")
            if seq < 0:
                raise ValueError("seq must be non-negative")
            rows.append({
                "session_id": row[0], "label": row[1], "stream_id": row[2], "seq": seq,
                "time_us": _int(row[4], "device_time_us"),
                "values": [_float(row[6 + i], HEADER[6 + i]) for i in range(6)],
            })
    if not rows:
        raise ValueError("no data rows")
    segments = _segment(rows)
    windows, records = [], []
    tail = 0
    for segment in segments:
        values = np.array([r["values"] for r in segment], dtype=np.float64)
        values[:, 3:6] = np.deg2rad(values[:, 3:6])
        count = 0
        start = 0
        while start + WINDOW_SIZE <= len(values):
            windows.append(values[start:start + WINDOW_SIZE])
            records.append({
                "session_id": segment[start]["session_id"], "stream_id": segment[start]["stream_id"],
                "label": segment[start]["label"], "start_seq": segment[start]["seq"],
                "end_seq": segment[start + WINDOW_SIZE - 1]["seq"],
                "start_time_us": segment[start]["time_us"],
                "end_time_us": segment[start + WINDOW_SIZE - 1]["time_us"]})
            count += 1
            start += STRIDE
        tail += len(values) - (count * STRIDE + WINDOW_SIZE if count else 0)
    index = _segment_index(rows, segments)
    grid_starts = range(0, len(rows) - WINDOW_SIZE + 1, STRIDE)
    crossing = sum(1 for s in grid_starts if index[s] != index[s + WINDOW_SIZE - 1])
    quality = {"rows": len(rows), "segments": len(segments), "windows": len(windows),
               "incomplete_tail_samples": int(tail), "rejected_candidate_windows": int(crossing),
               "first_time_us": rows[0]["time_us"], "last_time_us": rows[-1]["time_us"]}
    stacked = np.stack(windows) if windows else np.empty((0, WINDOW_SIZE, 6))
    return CollectorWindows(stacked, records, quality)


def _segment(rows):
    segments = [[rows[0]]]
    for previous, current in zip(rows, rows[1:]):
        changed = any(previous[key] != current[key]
                      for key in ("session_id", "stream_id", "label"))
        if changed:
            segments.append([current])
            continue
        if current["time_us"] <= previous["time_us"]:
            raise ValueError("device_time_us must strictly increase within a stream")
        if current["seq"] <= previous["seq"]:
            raise ValueError("seq must strictly increase within a stream")
        if current["seq"] > previous["seq"] + 1 or current["time_us"] - previous["time_us"] > GAP_US:
            segments.append([current])
        else:
            segments[-1].append(current)
    return segments


def _segment_index(rows, segments):
    index = np.zeros(len(rows), dtype=int)
    position = 0
    for number, segment in enumerate(segments):
        index[position:position + len(segment)] = number
        position += len(segment)
    return index
