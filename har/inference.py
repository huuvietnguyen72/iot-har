from pathlib import Path
import platform
import time

import numpy as np
from threadpoolctl import threadpool_limits

from .artifact import load_bundle, write_json
from .collector_csv import load_collector_windows
from .config import LABELS, WINDOW_SIZE
from .features import extract_features

SCOPE = "public_dataset_model_replay_not_activity_validation"


def _validate_windows(windows):
    array = np.asarray(windows, dtype=np.float64)
    if array.ndim != 3 or array.shape[1:] != (WINDOW_SIZE, 6):
        raise ValueError("windows must have shape (N, 128, 6)")
    return array


def predict_windows(run_dir, windows):
    array = _validate_windows(windows)
    estimator, metadata = load_bundle(run_dir)
    labels = [str(label) for label in estimator.classes_]
    if not len(array):
        return {"labels": labels, "predictions": [], "probabilities": []}
    features = extract_features(array)
    probabilities = estimator.predict_proba(features)
    predictions = estimator.predict(features)
    return {"labels": labels, "predictions": [str(p) for p in predictions],
            "probabilities": probabilities.tolist()}


def predict_csv(run_dir, csv_path, output_path):
    loaded = load_collector_windows(Path(csv_path))
    predicted = predict_windows(run_dir, loaded.windows)
    records = []
    for record, prediction, probabilities in zip(loaded.records, predicted["predictions"],
                                                 predicted["probabilities"]):
        records.append(dict(record, prediction=prediction, probabilities=probabilities))
    result = {"scope": SCOPE, "source_csv": str(csv_path), "quality": loaded.quality,
              "labels": predicted["labels"], "windows": records}
    write_json(Path(output_path), result)
    return result


def benchmark(run_dir, windows, *, warmup=10, repeats=200, output_path=None):
    array = _validate_windows(windows)
    if not len(array):
        raise ValueError("benchmark needs at least one window")
    estimator, metadata = load_bundle(run_dir)
    if hasattr(estimator, "n_jobs"):
        estimator.n_jobs = 1
    durations = []
    with threadpool_limits(limits=1):
        for i in range(warmup + repeats):
            window = array[i % len(array)][None]
            started = time.perf_counter()
            features = extract_features(window)
            estimator.predict(features)
            elapsed = time.perf_counter() - started
            if i >= warmup:
                durations.append(elapsed)
    values = np.array(durations)
    p95 = float(np.percentile(values, 95))
    result = {"warmup": warmup, "repeats": repeats, "durations_s": durations,
              "median_s": float(np.median(values)), "p95_s": p95,
              "criterion_p95_under_1_28": p95 < 1.28, "threadpool_limits": 1,
              "model_sha256": metadata["model_sha256"], "platform": platform.platform()}
    if output_path is not None:
        write_json(Path(output_path), result)
    return result
