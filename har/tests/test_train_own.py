import contextlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
import unittest

from har.own_dataset import load_own_sessions
from har.tests.fixtures import MINI_GRID, write_own_dataset, write_own_session
from har.tests.test_inference import build_run
from har.train_own import train_own


class TrainOwnTests(unittest.TestCase):
    def test_end_to_end_with_comparison(self):
        with TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as out:
            tmp = Path(tmp)
            train_dir, test_dir = write_own_dataset(tmp / "data")
            write_own_session(train_dir, "bad-walk", "walk", "2026-10-14T12:00:00Z",
                              meta={"status": "interrupted"})
            compare = build_run(tmp)
            run = tmp / "own"
            result = train_own(train_dir, test_dir, run, compare_run=compare, grid=MINI_GRID)
            self.assertIn("rejected bad-walk.json", out.getvalue())
            self.assertIn("windows walk=", out.getvalue())
            self.assertGreater(result["test"]["selected"]["macro_f1"],
                               result["test"]["dummy"]["macro_f1"])
            self.assertEqual(len(result["test_groups"]), 8)
            self.assertEqual(result["comparison"]["run_dir"], str(compare))
            sessions = json.loads((run / "sessions.json").read_text(encoding="utf-8"))
            self.assertEqual(len(sessions["train"]), 17)
            self.assertEqual(len(sessions["test"]), 8)
            rejected = [s["session_id"] for s in sessions["train"] if not s["accepted"]]
            self.assertEqual(rejected, ["bad-walk"])
            folds = {s["fold"] for s in sessions["train"] if s["accepted"]}
            self.assertEqual(folds, {0, 1, 2, 3})
            metadata = json.loads((run / "metadata.json").read_text(encoding="utf-8"))
            manifest = metadata["dataset_manifest"]
            self.assertEqual(manifest["source"], "own")
            self.assertEqual(len(manifest["train_sessions"]), 16)
            self.assertEqual(len(manifest["csv_sha256"]), 24)
            report = (run / "report.md").read_text(encoding="utf-8")
            self.assertIn("phương án A", report)

    def test_session_in_both_splits_is_error(self):
        with TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            tmp = Path(tmp)
            train_dir, test_dir = write_own_dataset(tmp / "data")
            write_own_session(test_dir, "train-walk-0", "walk", "2026-10-15T08:00:00Z")
            with self.assertRaisesRegex(ValueError, "train-walk-0"):
                train_own(train_dir, test_dir, tmp / "run", grid=MINI_GRID)
            self.assertFalse((tmp / "run").exists())

    def test_unserialisable_session_value_fails_before_run_dir(self):
        with TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            tmp = Path(tmp)
            train_dir, test_dir = write_own_dataset(tmp / "data")
            with mock.patch("har.train_own.load_own_sessions", wraps=load_own_sessions) as load:
                def poisoned(directory, split):
                    windows, sessions = load_own_sessions(directory, split)
                    sessions[0]["reason"] = float("nan")
                    return windows, sessions
                load.side_effect = poisoned
                with self.assertRaises(ValueError):
                    train_own(train_dir, test_dir, tmp / "run", grid=MINI_GRID)
            self.assertFalse((tmp / "run").exists())

    def test_too_few_train_sessions_is_error(self):
        with TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            tmp = Path(tmp)
            train_dir, test_dir = write_own_dataset(tmp / "data", train_sessions=3)
            with self.assertRaisesRegex(ValueError, "at least 4"):
                train_own(train_dir, test_dir, tmp / "run", grid=MINI_GRID)
            self.assertFalse((tmp / "run").exists())
