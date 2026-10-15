"""Train and evaluate the four-activity model on the user's own labelled sessions."""
from collections import Counter
import json
from pathlib import Path

import numpy as np

from .artifact import load_bundle, write_json
from .config import LABELS
from .features import extract_features
from .own_dataset import (N_OWN_SPLITS, TRIM_US, load_own_sessions, require_session_counts,
                          session_fold_groups)
from .train import evaluate, train_baseline

TITLE = "Dữ liệu MPU6050 đeo ở eo — 1 người (phương án A)"
NOTES = ["Nguồn: phiên collector có nhãn do một người đeo; đánh giá theo phiên/buổi, "
         "không theo người.", "",
         "Cross-validation chạy trên một buổi train nên chỉ dùng để chọn cấu hình; "
         "điểm báo cáo là buổi test giữ riêng."]
CV_METHOD = (f"GroupKFold {N_OWN_SPLITS} fold theo thứ tự phiên trong từng hoạt động "
             "(buổi train)")


def _accepted(sessions):
    return [s for s in sessions if s["accepted"]]


def _format_counts(counts):
    return ", ".join(f"{label}={counts[label]}" for label in LABELS)


def compare_on_test(compare_run, test):
    estimator, metadata = load_bundle(compare_run)
    metrics = evaluate(test.labels, estimator.predict(extract_features(test.windows)))
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
    train_counts = require_session_counts(train_sessions, "train")
    test_counts = require_session_counts(test_sessions, "test")
    shared = sorted(set(train.subjects.tolist()) & set(test.subjects.tolist()))
    if shared:
        raise ValueError(f"sessions appear in both train and test: {', '.join(shared)}")
    for split, window_set, counts in (("train", train, train_counts), ("test", test, test_counts)):
        windows = Counter(window_set.labels.tolist())
        print(f"{split}: sessions {_format_counts(counts)}; "
              f"windows {_format_counts({label: windows[label] for label in LABELS})}",
              flush=True)
    folds = session_fold_groups(train_sessions)
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
        extra["comparison"] = compare_on_test(compare_run, test)
    result = train_baseline(train, test, manifest, run_dir, grid=grid, cv_groups=cv_groups,
                            n_splits=N_OWN_SPLITS, title=TITLE, per_group_test=True, extra=extra)
    write_json(Path(run_dir) / "sessions.json", sessions_payload)
    return result
