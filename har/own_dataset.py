"""Load labelled MPU6050 collector sessions (CSV + JSON) as training windows."""
from collections import Counter
import csv
from datetime import datetime
import json
from pathlib import Path

import numpy as np

from .collector_csv import load_collector_windows
from .config import LABELS, WINDOW_SIZE
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
    if meta.get("label") not in LABELS:
        return f"label {meta.get('label')!r} is not one of {', '.join(LABELS)}"
    stats = meta.get("stats") if isinstance(meta.get("stats"), dict) else {}
    for key in ZERO_STATS:
        if stats.get(key) != 0:
            return f"stats.{key} is {stats.get(key)!r}, expected 0"
    csv_name = meta.get("csv_file")
    if not isinstance(csv_name, str) or not csv_name or Path(csv_name).name != csv_name:
        return "csv_file is missing or not a plain file name"
    if not (folder / csv_name).is_file():
        return f"CSV file {csv_name} not found"
    return None


def _load_session(json_path):
    entry = {"json_file": json_path.name, "session_id": None, "label": None,
             "started_utc": None, "accepted": False, "reason": None,
             "windows": 0, "trimmed_windows": 0, "csv_sha256": None}
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
        return entry, None
    csv_path = json_path.parent / meta["csv_file"]
    try:
        loaded = load_collector_windows(csv_path)
    except (OSError, ValueError, csv.Error) as exc:
        entry["reason"] = f"cannot read CSV: {exc}"
        return entry, None
    for record in loaded.records:
        if record["label"] != meta["label"] or record["session_id"] != meta["session_id"]:
            entry["reason"] = "CSV label or session_id does not match metadata"
            return entry, None
    first = loaded.quality["first_time_us"] + TRIM_US
    last = loaded.quality["last_time_us"] - TRIM_US
    keep = [i for i, record in enumerate(loaded.records)
            if record["start_time_us"] >= first and record["end_time_us"] <= last]
    entry["trimmed_windows"] = len(loaded.records) - len(keep)
    entry["csv_sha256"] = sha256_file(csv_path)
    if not keep:
        entry["reason"] = "no windows left after trimming 5 s at each end"
        return entry, None
    entry.update(accepted=True, windows=len(keep))
    return entry, loaded.windows[keep]


def load_own_sessions(directory, split):
    """Return (WindowSet, sessions); rejected sessions are listed with a reason."""
    folder = Path(directory)
    json_files = sorted(folder.glob("*.json"))
    if not json_files:
        raise ValueError(f"no session JSON files in {folder}")
    sessions, windows, labels, subjects = [], [], [], []
    loaded_from = {}
    for path in json_files:
        entry, session_windows = _load_session(path)
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
            labels += [entry["label"]] * len(session_windows)
            subjects += [entry["session_id"]] * len(session_windows)
    stacked = np.concatenate(windows) if windows else np.empty((0, WINDOW_SIZE, 6))
    window_set = WindowSet(stacked, np.array(labels, dtype=str),
                           np.array(subjects, dtype=str), np.arange(len(labels)), split)
    return window_set, sessions


def require_session_counts(sessions, split):
    """Raise ValueError unless every activity has enough accepted sessions."""
    counts = Counter(s["label"] for s in sessions if s["accepted"])
    minimum = MIN_TRAIN_SESSIONS if split == "train" else 1
    if any(counts[label] < minimum for label in LABELS):
        found = ", ".join(f"{label}={counts[label]}" for label in LABELS)
        raise ValueError(f"{split} needs at least {minimum} accepted session(s) per activity; "
                         f"found {found}")
    return {label: counts[label] for label in LABELS}


def session_fold_groups(sessions, n_splits=N_OWN_SPLITS):
    """Map session_id -> fold: the k-th session (by start time) of each activity -> (k-1) mod n."""
    groups = {}
    for label in LABELS:
        ordered = sorted((s for s in sessions if s["accepted"] and s["label"] == label),
                         key=lambda s: (parse_utc(s["started_utc"]), s["session_id"]))
        for ordinal, session in enumerate(ordered):
            groups[session["session_id"]] = ordinal % n_splits
    return groups
