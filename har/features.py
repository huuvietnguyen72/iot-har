import numpy as np

from .config import CHANNELS, CORRELATIONS, STATISTICS, WINDOW_SIZE


def feature_names():
    return ([f"{channel}_{stat}" for channel in CHANNELS for stat in STATISTICS]
            + [f"corr_{CHANNELS[a]}_{CHANNELS[b]}" for a, b in CORRELATIONS])


def extract_features(windows):
    w = np.asarray(windows, dtype=np.float64)
    if w.ndim != 3 or w.shape[1:] != (WINDOW_SIZE, 6):
        raise ValueError("windows must have shape (N, 128, 6)")
    if not np.isfinite(w).all():
        raise ValueError("nonfinite sensor data")
    if not len(w):
        return np.empty((0, 70), dtype=np.float64)
    x = np.concatenate((w, np.linalg.norm(w[:, :, :3], axis=2, keepdims=True),
                        np.linalg.norm(w[:, :, 3:], axis=2, keepdims=True)), axis=2)
    q25, q75 = np.percentile(x, [25, 75], axis=1, method="linear")
    stats = np.stack((x.mean(axis=1), x.std(axis=1), x.min(axis=1), x.max(axis=1),
                      np.median(x, axis=1), np.sqrt(np.mean(x * x, axis=1)),
                      np.mean(np.abs(x), axis=1), q75 - q25), axis=2)
    centered = w - w.mean(axis=1, keepdims=True)
    correlations = []
    for a, b in CORRELATIONS:
        numerator = np.sum(centered[:, :, a] * centered[:, :, b], axis=1)
        denominator = np.sqrt(np.sum(centered[:, :, a] ** 2, axis=1)
                              * np.sum(centered[:, :, b] ** 2, axis=1))
        value = np.divide(numerator, denominator, out=np.zeros(len(w)),
                          where=denominator > 0)
        correlations.append(np.clip(value, -1, 1))
    features = np.column_stack((stats.reshape(len(w), 64), *correlations))
    if not np.isfinite(features).all():
        raise ValueError("feature overflow")
    return features
