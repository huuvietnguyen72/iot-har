"""Barometer feature: the pressure trend (Pa/s) during a model window.

Air pressure falls about 12 Pa per metre, so climbing stairs gives a steady negative slope
of a few Pa/s and going down a positive one; walking on the flat gives about zero. The
slope is a least-squares fit over the BMP280 readings whose device time falls inside the
window, so it does not depend on absolute pressure (weather, floor of the building).
"""
import csv
import math
from pathlib import Path

import numpy as np

PRESSURE_FEATURE = "pressure_slope_pa_s"
BARO_HEADER = ["session_id", "stream_id", "seq", "device_time_us", "pressure_pa", "temp_c"]
# A 2.56 s window holds about 25 readings at 10 Hz; fewer than this means readings were lost.
MIN_READINGS = 10


def baro_path_for(csv_path):
    """<session>.csv -> <session>.baro.csv next to it (the file may not exist)."""
    path = Path(csv_path)
    return path.with_name(f"{path.stem}.baro.csv")


def load_baro_csv(path):
    """Read a collector .baro.csv; return a list of (stream_id, device_time_us, pressure_pa)."""
    rows = []
    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        if next(reader, None) != BARO_HEADER:
            raise ValueError("unexpected barometer CSV header")
        for number, row in enumerate(reader, start=2):
            if not row:
                continue
            if len(row) != len(BARO_HEADER):
                raise ValueError(f"barometer row {number} has {len(row)} fields")
            try:
                time_us = int(row[3])
                pressure = float(row[4])
            except ValueError as exc:
                raise ValueError(f"barometer row {number}: {exc}") from None
            if not math.isfinite(pressure):
                raise ValueError(f"barometer row {number}: pressure is not finite")
            rows.append((row[1], time_us, pressure))
    return rows


def pressure_slope(times_us, pressures):
    """Least-squares slope in Pa/s, or None with fewer than MIN_READINGS or no time spread."""
    if len(times_us) < MIN_READINGS:
        return None
    t = (np.asarray(times_us, dtype=np.float64) - times_us[0]) / 1e6
    p = np.asarray(pressures, dtype=np.float64)
    t_centered = t - t.mean()
    denominator = float(np.sum(t_centered * t_centered))
    if denominator <= 0:
        return None
    return float(np.sum(t_centered * (p - p.mean())) / denominator)


def window_slopes(records, baro_rows):
    """One slope per window record (NaN where too few readings fall inside the window)."""
    by_stream = {}
    for stream_id, time_us, pressure in baro_rows:
        by_stream.setdefault(stream_id, []).append((time_us, pressure))
    for readings in by_stream.values():
        readings.sort()
    slopes = np.full(len(records), np.nan)
    for i, record in enumerate(records):
        readings = by_stream.get(record["stream_id"], [])
        inside = [(t, p) for t, p in readings
                  if record["start_time_us"] <= t <= record["end_time_us"]]
        slope = pressure_slope([t for t, _ in inside], [p for _, p in inside])
        if slope is not None:
            slopes[i] = slope
    return slopes
