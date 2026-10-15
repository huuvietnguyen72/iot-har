import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np

from har.config import LABELS
from har.tests.fixtures import MINI_GRID, grouped_fixture
from har.train import evaluate, train_baseline


class TrainTests(unittest.TestCase):
    def test_known_metrics(self):
        metrics = evaluate(np.array(LABELS), np.array(LABELS))
        self.assertEqual(metrics["macro_f1"], 1)
        self.assertEqual(metrics["confusion_matrix"], np.eye(4, dtype=int).tolist())

    def test_full_run_selects_config_and_beats_dummy(self):
        with TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            result = train_baseline(grouped_fixture(range(1, 11)),
                                    grouped_fixture([21, 22], "test"),
                                    {"synthetic_fixture": True}, run, grid=MINI_GRID)
            self.assertEqual(result["selected_config"]["n_estimators"], 300)
            self.assertGreater(result["test"]["selected"]["macro_f1"],
                               result["test"]["dummy"]["macro_f1"])
            self.assertEqual(set(result["test"]), {"selected", "dummy"})
            self.assertEqual(json.loads((run / "status.json").read_text())["status"], "completed")
            self.assertTrue((run / "report.md").exists())
            self.assertIn("UCI HAR", (run / "report.md").read_text(encoding="utf-8"))
            self.assertNotIn("test_groups", result)
            with self.assertRaises(FileExistsError):
                train_baseline(grouped_fixture(range(1, 11)), grouped_fixture([21], "test"), {},
                               run, grid=MINI_GRID)

    def test_custom_groups_title_and_per_group_report(self):
        with TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            train = grouped_fixture(range(1, 9))
            comparison = {"run_dir": "x", "accuracy": 0.5, "macro_f1": 0.4,
                          "confusion_matrix": []}
            result = train_baseline(train, grouped_fixture([21, 22], "test"),
                                    {"synthetic_fixture": True}, run, grid=MINI_GRID,
                                    cv_groups=train.subjects % 4, n_splits=4,
                                    title="Own data", per_group_test=True,
                                    extra={"notes": ["Ghi chú riêng."], "comparison": comparison})
            selection = json.loads((run / "selection.json").read_text(encoding="utf-8"))
            self.assertTrue(selection["method"].startswith("GroupKFold-4"))
            self.assertTrue(selection["method"].endswith("session folds"))
            self.assertEqual(len(result["cv_selection"][0]["fold_macro_f1"]), 4)
            self.assertEqual([row["group"] for row in result["test_groups"]], ["21", "22"])
            self.assertEqual(result["test_groups"][0]["windows"], 8)
            self.assertEqual(result["comparison"], comparison)
            report = (run / "report.md").read_text(encoding="utf-8")
            self.assertIn("# Own data", report)
            self.assertIn("Ghi chú riêng.", report)
            self.assertIn("compare (x)", report)
            self.assertIn("Độ chính xác theo từng phiên test", report)
            self.assertNotIn("UCI HAR", report)

    def test_cv_groups_are_used(self):
        with TemporaryDirectory() as tmp:
            train = grouped_fixture(range(1, 9))
            with self.assertRaisesRegex(ValueError, "not enough subjects"):
                train_baseline(train, grouped_fixture([21, 22], "test"), {}, Path(tmp) / "run",
                               grid=MINI_GRID, cv_groups=train.subjects % 2, n_splits=4)

    def test_extra_cannot_override_result_keys(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "extra overrides"):
                train_baseline(grouped_fixture(range(1, 11)), grouped_fixture([21, 22], "test"),
                               {}, Path(tmp) / "run", grid=MINI_GRID, extra={"test": {}})
