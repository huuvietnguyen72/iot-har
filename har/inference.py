from pathlib import Path
import platform
import time

import numpy as np
from threadpoolctl import threadpool_limits

from .artifact import load_bundle, uses_pressure, write_json
from .collector_csv import load_collector_windows
from .config import WINDOW_SIZE
from .features import extract_features
from .pressure import baro_path_for

SCOPE = "model_replay_not_activity_validation"


def _validate_windows(windows):
    array = np.asarray(windows, dtype=np.float64)
    if array.ndim != 3 or array.shape[1:] != (WINDOW_SIZE, 6):
        raise ValueError("windows must have shape (N, 128, 6)")
    return array


def _model_pressure(metadata, pressure):
    """The pressure slopes to feed this model: None for motion-only models."""
    if not uses_pressure(metadata):
        return None
    if pressure is None:
        raise ValueError("this model needs barometer data (a .baro.csv next to the CSV)")
    return pressure


def load_csv_for_model(csv_path, metadata):
    """Load a collector CSV (and its .baro.csv when present); for a pressure model keep only
    the windows that have a barometer slope."""
    baro = baro_path_for(csv_path)
    loaded = load_collector_windows(Path(csv_path), baro if baro.is_file() else None)
    if not uses_pressure(metadata):
        return loaded.windows, None, loaded.records, loaded.quality
    if loaded.pressure is None:
        raise ValueError(f"this model needs barometer data: {baro.name} not found")
    keep = np.isfinite(loaded.pressure)
    records = [record for record, ok in zip(loaded.records, keep) if ok]
    return loaded.windows[keep], loaded.pressure[keep], records, loaded.quality


def predict_windows(run_dir, windows, pressure=None):
    array = _validate_windows(windows)
    estimator, metadata = load_bundle(run_dir)
    labels = [str(label) for label in estimator.classes_]
    if not len(array):
        return {"labels": labels, "predictions": [], "probabilities": []}
    features = extract_features(array, _model_pressure(metadata, pressure))
    probabilities = estimator.predict_proba(features)
    predictions = estimator.predict(features)
    return {"labels": labels, "predictions": [str(p) for p in predictions],
            "probabilities": probabilities.tolist()}


def predict_csv(run_dir, csv_path, output_path):
    _, metadata = load_bundle(run_dir)
    windows, pressure, window_records, quality = load_csv_for_model(csv_path, metadata)
    predicted = predict_windows(run_dir, windows, pressure)
    records = []
    for record, prediction, probabilities in zip(window_records, predicted["predictions"],
                                                 predicted["probabilities"]):
        records.append(dict(record, prediction=prediction, probabilities=probabilities))
    result = {"scope": SCOPE, "source_csv": str(csv_path), "quality": quality,
              "labels": predicted["labels"], "windows": records}
    write_json(Path(output_path), result)
    return result


def benchmark(run_dir, windows, *, warmup=10, repeats=200, output_path=None, pressure=None):
    array = _validate_windows(windows)
    if not len(array):
        raise ValueError("benchmark needs at least one window")
    estimator, metadata = load_bundle(run_dir)
    slopes = _model_pressure(metadata, pressure)
    if hasattr(estimator, "n_jobs"):
        estimator.n_jobs = 1
    durations = []
    with threadpool_limits(limits=1):
        for i in range(warmup + repeats):
            index = i % len(array)
            window = array[index][None]
            started = time.perf_counter()
            features = extract_features(window, None if slopes is None else slopes[index:index + 1])
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
