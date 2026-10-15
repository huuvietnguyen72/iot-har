import unittest

from har.config import LABELS
from har.features import extract_features
from har.tests.fixtures import grouped_fixture
from har.tune import cv_select, make_grid, select_best


class TuneTests(unittest.TestCase):
    def test_grid_shape_and_keys(self):
        grid = make_grid()
        self.assertEqual(len(grid), 24)
        self.assertEqual({c["n_estimators"] for c in grid}, {300})
        for config in grid:
            self.assertEqual(set(config), {"n_estimators", "max_features",
                                           "min_samples_leaf", "max_depth", "class_weight"})

    def test_select_best_prefers_higher_mean_then_simpler(self):
        results = [
            {"config": {"max_depth": 16, "min_samples_leaf": 1, "class_weight": None,
                        "max_features": "sqrt", "n_estimators": 300}, "mean_macro_f1": 0.80},
            {"config": {"max_depth": None, "min_samples_leaf": 1, "class_weight": None,
                        "max_features": "sqrt", "n_estimators": 300}, "mean_macro_f1": 0.90},
            {"config": {"max_depth": None, "min_samples_leaf": 2, "class_weight": None,
                        "max_features": "sqrt", "n_estimators": 300}, "mean_macro_f1": 0.90},
        ]
        best = select_best(results)
        self.assertEqual(best["mean_macro_f1"], 0.90)
        self.assertEqual(best["config"]["min_samples_leaf"], 1)

    def test_cv_select_returns_all_configs_and_disjoint_folds(self):
        train = grouped_fixture(range(1, 11))
        features = extract_features(train.windows)
        results = cv_select(features, train.labels, train.subjects, n_splits=5,
                            grid=[{"n_estimators": 20, "max_features": "sqrt",
                                   "min_samples_leaf": 1, "max_depth": None, "class_weight": None}])
        self.assertEqual(len(results), 1)
        self.assertEqual(len(results[0]["fold_macro_f1"]), 5)
        self.assertTrue(0.0 <= results[0]["mean_macro_f1"] <= 1.0)
        self.assertEqual(set(train.labels), set(LABELS))

    def test_cv_select_requires_enough_subjects(self):
        train = grouped_fixture([1, 2])
        features = extract_features(train.windows)
        with self.assertRaises(ValueError):
            cv_select(features, train.labels, train.subjects, n_splits=5)
