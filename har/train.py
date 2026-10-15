from datetime import datetime, timezone
from pathlib import Path
import time

import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score

from .artifact import save_bundle, write_json
from .config import LABELS, SEED
from .features import extract_features
from .report import write_report
from .tune import N_SPLITS, cv_select, make_grid, select_best


def evaluate(y_true, y_pred):
    return {"accuracy": float(accuracy_score(y_true, y_pred)),
            "macro_f1": float(f1_score(y_true, y_pred, labels=list(LABELS), average="macro",
                                       zero_division=0)),
            "per_class": classification_report(y_true, y_pred, labels=list(LABELS),
                                               output_dict=True, zero_division=0),
            "confusion_matrix": confusion_matrix(y_true, y_pred, labels=list(LABELS)).tolist()}


def per_group_accuracy(groups, labels, predictions):
    groups, labels, predictions = map(np.asarray, (groups, labels, predictions))
    rows = []
    for group in dict.fromkeys(groups.tolist()):
        mask = groups == group
        rows.append({"group": str(group), "labels": sorted(set(labels[mask].tolist())),
                     "windows": int(mask.sum()),
                     "accuracy": float(np.mean(labels[mask] == predictions[mask]))})
    return rows


def train_baseline(train, test, dataset_manifest, run_dir, *, grid=None, cv_groups=None,
                   n_splits=N_SPLITS, title=None, per_group_test=False, extra=None):
    run = Path(run_dir)
    run.parent.mkdir(parents=True, exist_ok=True)
    run.mkdir(exist_ok=False)
    write_json(run / "status.json", {"status": "training"})
    try:
        if set(train.subjects) & set(test.subjects):
            raise ValueError("official train and test share subjects")
        features = extract_features(train.windows)
        search = grid if grid is not None else make_grid()
        groups = train.subjects if cv_groups is None else np.asarray(cv_groups)
        method = (f"GroupKFold-{n_splits} macro-F1 on official train subjects" if cv_groups is None
                  else f"GroupKFold-{n_splits} macro-F1 on train session folds")
        print(f"Cross-validating {len(search)} Random Forest configs "
              f"(GroupKFold {n_splits}) on train...", flush=True)
        cv_results = cv_select(features, train.labels, groups, n_splits=n_splits, grid=search)
        chosen = select_best(cv_results)
        write_json(run / "selection.json", {
            "method": method, "selected": chosen, "candidates": cv_results})
        print(f"Selected config {chosen['config']} "
              f"(CV macro-F1 {chosen['mean_macro_f1']:.4f})", flush=True)
        estimator = RandomForestClassifier(random_state=SEED, n_jobs=-1, oob_score=True,
                                           **chosen["config"])
        started = time.perf_counter()
        estimator.fit(features, train.labels)
        final_seconds = time.perf_counter() - started
        dummy = DummyClassifier(strategy="most_frequent").fit(features, train.labels)
        test_features = extract_features(test.windows)
        predictions = estimator.predict(test_features)
        test_metrics = {"selected": evaluate(test.labels, predictions),
                        "dummy": evaluate(test.labels, dummy.predict(test_features))}
        oob = getattr(estimator, "oob_score_", None)
        result = {"selected_config": chosen["config"], "cv_selection": cv_results,
                  "selected_cv_mean_macro_f1": chosen["mean_macro_f1"],
                  "selected_cv_std_macro_f1": chosen["std_macro_f1"],
                  "oob_score": float(oob) if oob is not None else None,
                  "test": test_metrics, "dataset_manifest": dataset_manifest, "warnings": [],
                  "final_fit_seconds": final_seconds, "seed": SEED,
                  "train_windows": len(train.labels), "test_windows": len(test.labels),
                  "excluded_stairs": {"train": train.excluded_rows, "test": test.excluded_rows},
                  "quality_goal_met": test_metrics["selected"]["macro_f1"] >= 0.85,
                  "beats_dummy": (test_metrics["selected"]["macro_f1"]
                                  > test_metrics["dummy"]["macro_f1"])}
        clash = set(extra or ()) & (set(result) | {"title", "test_groups"})
        if clash:
            raise ValueError(f"extra overrides result keys: {sorted(clash)}")
        if title is not None:
            result["title"] = title
        if per_group_test:
            result["test_groups"] = per_group_accuracy(test.subjects, test.labels, predictions)
        if extra:
            result.update(extra)
        save_bundle(run, estimator, {
            "selected_config": chosen["config"], "seed": SEED,
            "selection_method": f"GroupKFold-{n_splits}", "dataset_manifest": dataset_manifest,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "model_config": {k: v for k, v in estimator.get_params().items()
                             if isinstance(v, (str, int, float, bool, type(None)))}})
        write_report(run, result)
        write_json(run / "status.json", {"status": "completed"}, replace=True)
        return result
    except BaseException as exc:
        write_json(run / "status.json", {"status": "failed", "error": str(exc)}, replace=True)
        raise
