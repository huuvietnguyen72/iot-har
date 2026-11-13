import numpy as np

from .config import CHANNELS, CORRELATIONS, STATISTICS, WINDOW_SIZE
from .pressure import PRESSURE_FEATURE

N_MOTION_FEATURES = 70


def feature_names(pressure=False):
    """70 motion features; with pressure=True, the barometer slope is appended as the 71st."""
    names = ([f"{channel}_{stat}" for channel in CHANNELS for stat in STATISTICS]
             + [f"corr_{CHANNELS[a]}_{CHANNELS[b]}" for a, b in CORRELATIONS])
    return names + [PRESSURE_FEATURE] if pressure else names


def extract_features(windows, pressure=None):
    """(N, 128, 6) windows -> (N, 70) features; pressure: optional (N,) slopes in Pa/s."""
    features = _motion_features(windows)
    if pressure is None:
        return features
    slopes = np.asarray(pressure, dtype=np.float64).reshape(-1)
    if len(slopes) != len(features):
        raise ValueError("need one pressure slope per window")
    if not np.isfinite(slopes).all():
        raise ValueError("missing or nonfinite pressure slope")
    return np.column_stack((features, slopes))


def _motion_features(windows):
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
