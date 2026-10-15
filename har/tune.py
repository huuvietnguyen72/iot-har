import json

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import f1_score
from sklearn.model_selection import GroupKFold

from .config import LABELS, SEED

N_SPLITS = 5


def make_grid():
    return [dict(n_estimators=300, max_features=max_features,
                 min_samples_leaf=min_samples_leaf, max_depth=max_depth,
                 class_weight=class_weight)
            for max_features in ("sqrt", 0.3)
            for min_samples_leaf in (1, 2, 4)
            for max_depth in (None, 16)
            for class_weight in (None, "balanced_subsample")]


def _complexity(config):
    return ((config["max_depth"] is not None) + (config["min_samples_leaf"] > 1)
            + (config["class_weight"] is not None) + (config["max_features"] != "sqrt"))


def cv_select(features, labels, subjects, *, n_splits=N_SPLITS, seed=SEED, grid=None):
    features = np.asarray(features, dtype=np.float64)
    labels = np.asarray(labels)
    subjects = np.asarray(subjects)
    if len(np.unique(subjects)) < n_splits:
        raise ValueError("not enough subjects for cross-validation")
    folds = list(GroupKFold(n_splits=n_splits).split(features, labels, subjects))
    results = []
    for config in (grid or make_grid()):
        scores = []
        for train_idx, test_idx in folds:
            if set(labels[train_idx]) != set(LABELS):
                raise ValueError("a training fold is missing a class")
            model = RandomForestClassifier(random_state=seed, n_jobs=-1, **config)
            model.fit(features[train_idx], labels[train_idx])
            scores.append(float(f1_score(labels[test_idx], model.predict(features[test_idx]),
                                         labels=list(LABELS), average="macro", zero_division=0)))
        results.append({"config": config, "fold_macro_f1": scores,
                        "mean_macro_f1": float(np.mean(scores)),
                        "std_macro_f1": float(np.std(scores))})
    return results


def select_best(results, *, tol=1e-6):
    best = max(result["mean_macro_f1"] for result in results)
    tied = [result for result in results if best - result["mean_macro_f1"] <= tol]
    tied.sort(key=lambda result: (_complexity(result["config"]),
                                  json.dumps(result["config"], sort_keys=True)))
    return tied[0]
