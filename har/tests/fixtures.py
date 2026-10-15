from pathlib import Path

import numpy as np

MINI_GRID = [{"n_estimators": 300, "max_features": "sqrt", "min_samples_leaf": 1,
              "max_depth": None, "class_weight": None}]


def grouped_fixture(subject_ids, split="train"):
    from har.config import LABELS
    from har.dataset import WindowSet

    rng = np.random.default_rng(42)
    windows, labels, subjects = [], [], []
    for subject in subject_ids:
        for activity, label in enumerate(LABELS):
            for repeat in range(2):
                w = rng.normal(0, 0.01, (128, 6))
                w[:, activity % 3] += activity + 0.25
                w[:, 3] += activity * 0.1
                windows.append(w)
                labels.append(label)
                subjects.append(subject)
    return WindowSet(np.array(windows), np.array(labels), np.array(subjects),
                     np.arange(len(labels)), split)


def uci_fixture(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "activity_labels.txt").write_text(
        "1 WALKING\n2 WALKING_UPSTAIRS\n3 WALKING_DOWNSTAIRS\n4 SITTING\n5 STANDING\n6 LAYING\n")
    for split in ("train", "test"):
        folder = root / split
        signals = folder / "Inertial Signals"
        signals.mkdir(parents=True)
        for index, name in enumerate(("total_acc_x", "total_acc_y", "total_acc_z",
                                       "body_gyro_x", "body_gyro_y", "body_gyro_z")):
            np.savetxt(signals / f"{name}_{split}.txt", np.full((6, 128), index + 1.))
        np.savetxt(folder / f"y_{split}.txt", np.arange(1, 7), fmt="%d")
        np.savetxt(folder / f"subject_{split}.txt", np.ones(6) * (1 if split == "train" else 2), fmt="%d")
    return root


def write_own_session(folder, session_id, label, started_utc, *, seconds=20, csv_label=None,
                      write_csv=True, meta=None):
    """Write one collector-format session (CSV + JSON) with a label-dependent signal."""
    import json
    import zlib

    from har.collector_csv import HEADER
    from har.config import LABELS

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    activity = LABELS.index(label) if label in LABELS else 0
    rng = np.random.default_rng(zlib.crc32(session_id.encode()))
    count = seconds * 50
    rows = [",".join(HEADER)]
    for i in range(count):
        n = rng.normal(0, 0.01, 6)
        values = [activity + 0.25 + n[0], n[1], 1.0 + n[2], activity * 10.0 + n[3], n[4], n[5]]
        rows.append(",".join([session_id, csv_label or label, "a" * 16, str(i), str(i * 20000),
                              f"{i * 0.02:.3f}", *(f"{v:.5f}" for v in values), "25.0"]))
    csv_name = f"{session_id}.csv"
    if write_csv:
        (folder / csv_name).write_text("\n".join(rows) + "\n", encoding="utf-8")
    data = {"protocol_version": 1, "session_id": session_id, "label": label,
            "status": "completed", "started_utc": started_utc, "csv_file": csv_name,
            "sensor_config": {"accel_range_g": 4, "gyro_range_dps": 500, "dlpf": 3,
                              "internal_sample_rate_hz": 100, "output_interval_ms": 20},
            "stats": {"samples_written": count, "data_errors": 0, "missing_by_seq": 0,
                      "duplicates": 0, "out_of_order": 0, "timestamp_errors": 0,
                      "gaps_over_40ms": 0}}
    for key, value in (meta or {}).items():
        if isinstance(value, dict) and isinstance(data.get(key), dict):
            data[key] = {**data[key], **value}
        else:
            data[key] = value
    path = folder / f"{session_id}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def write_own_dataset(root, *, train_sessions=4, test_sessions=2):
    """Interleaved train/test sessions: <split>-<label>-<k>, 3 minutes apart."""
    from har.config import LABELS

    root = Path(root)
    dirs = {"train": root / "train", "test": root / "test"}
    minute = 0
    for split, per_label in (("train", train_sessions), ("test", test_sessions)):
        for k in range(per_label):
            for label in LABELS:
                write_own_session(dirs[split], f"{split}-{label}-{k}", label,
                                  f"2026-10-14T{8 + minute // 60:02d}:{minute % 60:02d}:00Z")
                minute += 3
    return dirs["train"], dirs["test"]
