import importlib.metadata
import json
import os
from pathlib import Path
import platform

import joblib

from .config import LABELS, SAMPLE_RATE_HZ, SCHEMA_VERSION, STRIDE, WINDOW_SIZE
from .dataset import sha256_file
from .features import feature_names


def versions():
    return {name: importlib.metadata.version(name) for name in
            ("numpy", "scipy", "scikit-learn", "joblib", "threadpoolctl")}


def schema():
    return {"schema_version": SCHEMA_VERSION, "labels": list(LABELS),
            "feature_names": feature_names(), "window_size": WINDOW_SIZE,
            "stride": STRIDE, "sample_rate_hz": SAMPLE_RATE_HZ,
            "units": {"acceleration": "g", "gyroscope": "rad/s"}}


def write_json(path, data, replace=False):
    path = Path(path)
    if not replace and path.exists():
        raise FileExistsError(path)
    payload = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False)
    temp = path.with_name(path.name + ".tmp")
    try:
        with temp.open("x", encoding="utf-8") as fh:
            fh.write(payload + "\n")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def save_bundle(run_dir, estimator, metadata):
    run = Path(run_dir)
    model_path = run / "model.joblib"
    meta_path = run / "metadata.json"
    if model_path.exists() or meta_path.exists():
        raise FileExistsError("model artifact already exists")
    temp = run / "model.joblib.tmp"
    try:
        with temp.open("xb") as fh:
            joblib.dump(estimator, fh, compress=3)
        temp.rename(model_path)
    finally:
        temp.unlink(missing_ok=True)
    meta = dict(metadata)
    meta.update(schema())
    meta.update({"versions": versions(), "python": platform.python_version(),
                 "model_sha256": sha256_file(model_path)})
    write_json(meta_path, meta)


def load_bundle(run_dir):
    run = Path(run_dir)
    metadata = json.loads((run / "metadata.json").read_text(encoding="utf-8"))
    for key, expected in schema().items():
        if metadata.get(key) != expected:
            raise ValueError(f"incompatible artifact schema: {key}")
    if metadata.get("versions") != versions():
        raise ValueError("artifact library versions differ from installed requirements")
    if metadata.get("model_sha256") != sha256_file(run / "model.joblib"):
        raise ValueError("model checksum mismatch")
    estimator = joblib.load(run / "model.joblib")
    if set(estimator.classes_) != set(LABELS) or estimator.n_features_in_ != 70:
        raise ValueError("incompatible estimator features or labels")
    return estimator, metadata
