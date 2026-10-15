"""Predict one window at a time with a saved model and smooth the probabilities."""
from collections import deque
import time

import numpy as np
from threadpoolctl import ThreadpoolController

from .artifact import load_bundle
from .config import WINDOW_SIZE
from .features import extract_features

SMOOTHING_WINDOWS = 3
UNCERTAIN_BELOW = 0.60


class LivePredictor:
    def __init__(self, run_dir, *, clock=time.perf_counter):
        estimator, metadata = load_bundle(run_dir)
        if hasattr(estimator, "n_jobs"):
            estimator.n_jobs = 1
        self._estimator = estimator
        self._threadpools = ThreadpoolController()
        self._clock = clock
        self.metadata = metadata
        self.labels = [str(label) for label in estimator.classes_]
        self._recent = deque(maxlen=SMOOTHING_WINDOWS)

    def reset(self):
        self._recent.clear()

    def predict(self, window):
        array = np.asarray(window, dtype=np.float64)
        if array.shape != (WINDOW_SIZE, 6):
            raise ValueError("window must have shape (128, 6)")
        started = self._clock()
        with self._threadpools.limit(limits=1):
            raw = np.asarray(self._estimator.predict_proba(extract_features(array[None]))[0],
                             dtype=np.float64)
        predict_ms = (self._clock() - started) * 1000.0
        self._recent.append(raw)
        smoothed = np.mean(np.stack(self._recent), axis=0)
        best = int(np.argmax(smoothed))
        return {"raw_label": self.labels[int(np.argmax(raw))],
                "raw_probabilities": [float(p) for p in raw],
                "label": self.labels[best],
                "probabilities": [float(p) for p in smoothed],
                "uncertain": bool(smoothed[best] < UNCERTAIN_BELOW),
                "predict_ms": predict_ms}

