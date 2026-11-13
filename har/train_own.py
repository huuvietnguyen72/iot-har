"""Train and evaluate the activity model on the user's own labelled sessions.

Four activities always; stairs_up / stairs_down are added when the train sessions contain
them, and then the barometer slope is used as an extra feature (every session needs a
barometer file).
"""
from collections import Counter
import json
from pathlib import Path

import numpy as np

from .artifact import load_bundle, uses_pressure, write_json
from .config import STAIRS_LABELS
from .features import extract_features
from .own_dataset import (N_OWN_SPLITS, TRIM_US, load_own_sessions, model_labels,
                          require_session_counts, session_fold_groups)
from .train import evaluate, train_baseline

TITLE = "Dữ liệu MPU6050 đeo ở eo"
NOTES = ["Nguồn: phiên collector có nhãn; đánh giá theo phiên/buổi, không theo người.", "",
         "Cross-validation chạy trên một buổi train nên chỉ dùng để chọn cấu hình; "
         "điểm báo cáo là buổi test giữ riêng."]
CV_METHOD = (f"GroupKFold {N_OWN_SPLITS} fold theo thứ tự phiên trong từng hoạt động "
             "(buổi train)")


def _accepted(sessions):
    return [s for s in sessions if s["accepted"]]


def _format_counts(counts):
    return ", ".join(f"{label}={count}" for label, count in counts.items())


def compare_on_test(compare_run, test, labels):
    estimator, metadata = load_bundle(compare_run)
    pressure = None
    if uses_pressure(metadata):
        if test.pressure is None:
            raise ValueError(f"{compare_run} needs barometer data in every test session")
        pressure = test.pressure
    predictions = estimator.predict(extract_features(test.windows, pressure))
    metrics = evaluate(test.labels, predictions, labels)
    return {"run_dir": str(compare_run), "model_sha256": metadata["model_sha256"],
            "accuracy": metrics["accuracy"], "macro_f1": metrics["macro_f1"],
            "confusion_matrix": metrics["confusion_matrix"]}


def train_own(train_dir, test_dir, run_dir, *, compare_run=None, grid=None):
    train, train_sessions = load_own_sessions(train_dir, "train")
    test, test_sessions = load_own_sessions(test_dir, "test")
    for split, sessions in (("train", train_sessions), ("test", test_sessions)):
        for entry in sessions:
            if not entry["accepted"]:
                print(f"[{split}] rejected {entry['json_file']}: {entry['reason']}", flush=True)
    labels = model_labels(train_sessions)
    unknown = sorted({s["label"] for s in test_sessions if s["accepted"]} - set(labels))
    if unknown:
        raise ValueError(f"test has activities that train does not: {', '.join(unknown)}")
    train_counts = require_session_counts(train_sessions, "train", labels)
    test_counts = require_session_counts(test_sessions, "test", labels)
    pressure = any(label in STAIRS_LABELS for label in labels)
    if pressure:
        for split, window_set, sessions in (("train", train, train_sessions),
                                            ("test", test, test_sessions)):
            if window_set.pressure is None:
                missing = [s["session_id"] for s in sessions
                           if s["accepted"] and not s["has_pressure"]]
                raise ValueError(
                    "stairs sessions need barometer data in every session; "
                    f"{split} sessions without a .baro.csv: {', '.join(missing)}")
        print("using the barometer slope as an extra feature (stairs labels present)",
              flush=True)
    shared = sorted(set(train.subjects.tolist()) & set(test.subjects.tolist()))
    if shared:
        raise ValueError(f"sessions appear in both train and test: {', '.join(shared)}")
    for split, window_set, counts in (("train", train, train_counts), ("test", test, test_counts)):
        windows = Counter(window_set.labels.tolist())
        print(f"{split}: sessions {_format_counts(counts)}; "
              f"windows {_format_counts({label: windows[label] for label in labels})}",
              flush=True)
    folds = session_fold_groups(train_sessions, labels=labels)
    for entry in train_sessions:
        entry["fold"] = folds.get(entry["session_id"]) if entry["accepted"] else None
    cv_groups = np.array([folds[session_id] for session_id in train.subjects])
    sessions_payload = {"train": train_sessions, "test": test_sessions}
    json.dumps(sessions_payload, allow_nan=False)  # fail before the run directory exists
    accepted = _accepted(train_sessions) + _accepted(test_sessions)
    manifest = {"source": "own", "train_dir": str(train_dir), "test_dir": str(test_dir),
                "trim_s": TRIM_US / 1e6,
                "train_sessions": [s["session_id"] for s in _accepted(train_sessions)],
                "test_sessions": [s["session_id"] for s in _accepted(test_sessions)],
                "csv_sha256": {s["session_id"]: s["csv_sha256"] for s in accepted}}
    extra = {"notes": NOTES, "cv_method": CV_METHOD, "test_heading": "Buổi test giữ riêng"}
    if compare_run is not None:
        extra["comparison"] = compare_on_test(compare_run, test, labels)
    result = train_baseline(train, test, manifest, run_dir, grid=grid, cv_groups=cv_groups,
                            n_splits=N_OWN_SPLITS, title=TITLE, per_group_test=True, extra=extra,
                            labels=labels, pressure=pressure)
    write_json(Path(run_dir) / "sessions.json", sessions_payload)
    return result
