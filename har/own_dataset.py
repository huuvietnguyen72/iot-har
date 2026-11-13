"""Load labelled MPU6050 collector sessions (CSV + JSON) as training windows."""
from collections import Counter
import csv
from datetime import datetime
import json
from pathlib import Path

import numpy as np

from .collector_csv import load_collector_windows
from .config import ALLOWED_LABELS, LABELS, WINDOW_SIZE
from .dataset import WindowSet, sha256_file

TRIM_US = 5_000_000
MIN_TRAIN_SESSIONS = 4
N_OWN_SPLITS = 4
EXPECTED_SENSOR = {"accel_range_g": 4, "gyro_range_dps": 500, "output_interval_ms": 20}
ZERO_STATS = ("data_errors", "missing_by_seq", "duplicates", "out_of_order", "gaps_over_40ms")


def parse_utc(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _metadata_problem(meta, folder):
    if not isinstance(meta, dict):
        return "metadata is not a JSON object"
    if meta.get("protocol_version") != 1:
        return f"protocol_version is {meta.get('protocol_version')!r}, expected 1"
    if meta.get("status") != "completed":
        return f"status is {meta.get('status')!r}, expected 'completed'"
    if not isinstance(meta.get("session_id"), str) or not meta["session_id"]:
        return "session_id is missing"
    try:
        started = parse_utc(meta.get("started_utc"))
    except (AttributeError, TypeError, ValueError):
        return "started_utc is not an ISO-8601 timestamp"
    if started.tzinfo is None:
        return "started_utc has no timezone"
    sensor = meta.get("sensor_config") if isinstance(meta.get("sensor_config"), dict) else {}
    for key, expected in EXPECTED_SENSOR.items():
        if sensor.get(key) != expected:
            return f"sensor_config.{key} is {sensor.get(key)!r}, expected {expected}"
    if meta.get("label") not in ALLOWED_LABELS:
        return f"label {meta.get('label')!r} is not one of {', '.join(ALLOWED_LABELS)}"
    stats = meta.get("stats") if isinstance(meta.get("stats"), dict) else {}
    for key in ZERO_STATS:
        if stats.get(key) != 0:
            return f"stats.{key} is {stats.get(key)!r}, expected 0"
    csv_name = meta.get("csv_file")
    if not isinstance(csv_name, str) or not csv_name or Path(csv_name).name != csv_name:
        return "csv_file is missing or not a plain file name"
    if not (folder / csv_name).is_file():
        return f"CSV file {csv_name} not found"
    baro_name = meta.get("baro_file")
    if baro_name is not None:
        if not isinstance(baro_name, str) or not baro_name or Path(baro_name).name != baro_name:
            return "baro_file is not a plain file name"
        if not (folder / baro_name).is_file():
            return f"barometer file {baro_name} not found"
    return None


def _load_session(json_path):
    entry = {"json_file": json_path.name, "session_id": None, "label": None,
             "started_utc": None, "accepted": False, "reason": None,
             "windows": 0, "trimmed_windows": 0, "csv_sha256": None,
             "has_pressure": False, "windows_without_pressure": 0}
    try:
        meta = json.loads(json_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        entry["reason"] = f"cannot read metadata: {exc}"
        return entry, None
    if isinstance(meta, dict):
        entry.update({key: meta.get(key) if isinstance(meta.get(key), str) else None
                      for key in ("session_id", "label", "started_utc")})
    problem = _metadata_problem(meta, json_path.parent)
    if problem:
        entry["reason"] = problem
        return entry, None, None
    csv_path = json_path.parent / meta["csv_file"]
    baro_path = json_path.parent / meta["baro_file"] if meta.get("baro_file") else None
    try:
        loaded = load_collector_windows(csv_path, baro_path)
    except (OSError, ValueError, csv.Error) as exc:
        entry["reason"] = f"cannot read CSV: {exc}"
        return entry, None, None
    for record in loaded.records:
        if record["label"] != meta["label"] or record["session_id"] != meta["session_id"]:
            entry["reason"] = "CSV label or session_id does not match metadata"
            return entry, None, None
    first = loaded.quality["first_time_us"] + TRIM_US
    last = loaded.quality["last_time_us"] - TRIM_US
    keep = [i for i, record in enumerate(loaded.records)
            if record["start_time_us"] >= first and record["end_time_us"] <= last]
    entry["trimmed_windows"] = len(loaded.records) - len(keep)
    entry["csv_sha256"] = sha256_file(csv_path)
    pressure = None
    if loaded.pressure is not None:
        # Windows whose barometer readings were lost cannot carry the pressure feature.
        with_pressure = [i for i in keep if np.isfinite(loaded.pressure[i])]
        entry["windows_without_pressure"] = len(keep) - len(with_pressure)
        entry["has_pressure"] = True
        keep = with_pressure
        pressure = loaded.pressure[keep]
    if not keep:
        entry["reason"] = "no windows left after trimming 5 s at each end"
        return entry, None, None
    entry.update(accepted=True, windows=len(keep))
    return entry, loaded.windows[keep], pressure


def load_own_sessions(directory, split):
    """Return (WindowSet, sessions); rejected sessions are listed with a reason.

    WindowSet.pressure holds the barometer slope of every window when every accepted
    session has a barometer file, otherwise None.
    """
    folder = Path(directory)
    json_files = sorted(folder.glob("*.json"))
    if not json_files:
        raise ValueError(f"no session JSON files in {folder}")
    sessions, windows, labels, subjects, pressures = [], [], [], [], []
    loaded_from = {}
    for path in json_files:
        entry, session_windows, session_pressure = _load_session(path)
        if entry["accepted"]:
            sid = entry["session_id"]
            if sid in loaded_from:
                entry.update(accepted=False, windows=0, trimmed_windows=0,
                             reason=f"duplicate session_id {sid} "
                                    f"(already loaded from {loaded_from[sid]})")
                session_windows = None
            else:
                loaded_from[sid] = entry["json_file"]
        sessions.append(entry)
        if session_windows is not None:
            windows.append(session_windows)
            pressures.append(session_pressure)
            labels += [entry["label"]] * len(session_windows)
            subjects += [entry["session_id"]] * len(session_windows)
    stacked = np.concatenate(windows) if windows else np.empty((0, WINDOW_SIZE, 6))
    pressure = None
    if pressures and all(p is not None for p in pressures):
        pressure = np.concatenate(pressures)
    window_set = WindowSet(stacked, np.array(labels, dtype=str),
                           np.array(subjects, dtype=str), np.arange(len(labels)), split,
                           pressure=pressure)
    return window_set, sessions


def model_labels(sessions):
    """Labels the model will learn: the four base activities plus any stairs label present."""
    present = {s["label"] for s in sessions if s["accepted"]}
    return [label for label in ALLOWED_LABELS if label in LABELS or label in present]


def require_session_counts(sessions, split, labels=LABELS):
    """Raise ValueError unless every activity in labels has enough accepted sessions."""
    counts = Counter(s["label"] for s in sessions if s["accepted"])
    minimum = MIN_TRAIN_SESSIONS if split == "train" else 1
    if any(counts[label] < minimum for label in labels):
        found = ", ".join(f"{label}={counts[label]}" for label in labels)
        raise ValueError(f"{split} needs at least {minimum} accepted session(s) per activity; "
                         f"found {found}")
    return {label: counts[label] for label in labels}


def session_fold_groups(sessions, n_splits=N_OWN_SPLITS, labels=LABELS):
    """Map session_id -> fold: the k-th session (by start time) of each activity -> (k-1) mod n."""
    groups = {}
    for label in labels:
        ordered = sorted((s for s in sessions if s["accepted"] and s["label"] == label),
                         key=lambda s: (parse_utc(s["started_utc"]), s["session_id"]))
        for ordinal, session in enumerate(ordered):
            groups[session["session_id"]] = ordinal % n_splits
    return groups
