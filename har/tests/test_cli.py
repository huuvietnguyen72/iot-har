from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
import contextlib
import io
import json
import re
import threading
import unittest

from har.cli import main
from har.fake_esp32 import FakeEsp32
from har.tests.fixtures import MINI_GRID, write_own_dataset, write_own_session
from har.tests.test_inference import build_run, write_csv


class CliTests(unittest.TestCase):
    def test_missing_command_is_usage_error(self):
        with self.assertRaises(SystemExit) as ctx:
            main([])
        self.assertEqual(ctx.exception.code, 2)

    def test_help_exits_zero(self):
        with self.assertRaises(SystemExit) as ctx, contextlib.redirect_stdout(io.StringIO()):
            main(["--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_predict_and_benchmark_success(self):
        with TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            run = build_run(tmp)
            csv_path = tmp / "ref.csv"
            write_csv(csv_path)
            replay = tmp / "replay.json"
            bench = tmp / "bench.json"
            self.assertEqual(main(["predict-csv", "--run-dir", str(run), "--csv", str(csv_path),
                                   "--output", str(replay)]), 0)
            self.assertEqual(main(["benchmark", "--run-dir", str(run), "--csv", str(csv_path),
                                   "--output", str(bench)]), 0)
            self.assertTrue(replay.exists() and bench.exists())

    def test_bad_artifact_is_data_error(self):
        with TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            csv_path = tmp / "ref.csv"
            write_csv(csv_path)
            code = main(["predict-csv", "--run-dir", str(tmp / "missing"), "--csv", str(csv_path),
                         "--output", str(tmp / "out.json")])
            self.assertEqual(code, 1)

    def test_missing_arguments_is_usage_error(self):
        with self.assertRaises(SystemExit) as ctx:
            main(["predict-csv", "--run-dir", "x"])
        self.assertEqual(ctx.exception.code, 2)

    def test_train_own_success(self):
        with TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as out, \
                mock.patch("har.train.make_grid", return_value=MINI_GRID):
            tmp = Path(tmp)
            train_dir, test_dir = write_own_dataset(tmp / "data")
            compare = build_run(tmp)
            run = tmp / "own"
            code = main(["train-own", "--train-dir", str(train_dir), "--test-dir", str(test_dir),
                         "--run-dir", str(run), "--compare-run", str(compare)])
            self.assertEqual(code, 0)
            self.assertIn("test_macro_f1=", out.getvalue())
            self.assertTrue((run / "sessions.json").exists())
            report = json.loads((run / "report.json").read_text(encoding="utf-8"))
            self.assertIn("comparison", report)

    def test_train_own_empty_dir_is_data_error(self):
        with TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()) as err:
            tmp = Path(tmp)
            code = main(["train-own", "--train-dir", str(tmp / "none"), "--test-dir",
                         str(tmp / "none"), "--run-dir", str(tmp / "run")])
            self.assertEqual(code, 1)
            self.assertIn("no session JSON", err.getvalue())

    def test_train_own_missing_compare_run_is_data_error(self):
        with TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()),                 contextlib.redirect_stderr(io.StringIO()) as err,                 mock.patch("har.train.make_grid", return_value=MINI_GRID):
            tmp = Path(tmp)
            train_dir, test_dir = write_own_dataset(tmp / "data")
            run = tmp / "own"
            code = main(["train-own", "--train-dir", str(train_dir), "--test-dir", str(test_dir),
                         "--run-dir", str(run), "--compare-run", str(tmp / "missing")])
            self.assertEqual(code, 1)
            self.assertIn("error:", err.getvalue())
            self.assertFalse(run.exists())


class LiveDemoCliTests(unittest.TestCase):
    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_live_prints_predictions_from_fake_esp32(self):
        with TemporaryDirectory() as tmp:
            run = build_run(tmp)
            csv_path = write_own_session(Path(tmp) / "s", "s1", "walk", "2026-10-14T08:00:00Z",
                                         seconds=10).with_suffix(".csv")
            with FakeEsp32(csv_path, speed=20, loop=True) as fake:
                result = {}
                argv = ["live", "--run-dir", str(run), "--esp",
                        f"127.0.0.1:{fake.port}", "--max-predictions", "2"]
                worker = threading.Thread(target=lambda: result.update(r=self.run_main(argv)),
                                          daemon=True)
                worker.start()
                worker.join(timeout=30)
                self.assertFalse(worker.is_alive(), "live command did not finish")
                code, out, _ = result["r"]
        self.assertEqual(code, 0)
        lines = [l for l in out.splitlines() if re.match(r"^\d\d:\d\d:\d\d  ", l)]
        self.assertGreaterEqual(len(lines), 2)
        self.assertIn("Hz", lines[0])

    def test_live_and_demo_configuration_errors_exit_1(self):
        with TemporaryDirectory() as tmp:
            run = build_run(tmp)
            cases = [["live", "--run-dir", str(Path(tmp) / "missing"), "--esp", "127.0.0.1:1"],
                     ["live", "--run-dir", str(run), "--esp", "nohost"],
                     ["demo", "--run-dir", str(run), "--esp", "127.0.0.1:1",
                      "--data-dir", str(Path(tmp) / "missing")],
                     ["demo", "--run-dir", str(run), "--esp", "bad", "--data-dir", tmp],
                     ["demo", "--run-dir", str(Path(tmp) / "missing"), "--esp", "127.0.0.1:1",
                      "--data-dir", tmp]]
            good_csv = write_own_session(Path(tmp) / "s", "s1", "walk", "2026-10-14T08:00:00Z",
                                         seconds=2).with_suffix(".csv")
            cases.append(["fake-esp32", "--csv", str(good_csv), "--speed", "nan", "--port", "0"])
            for argv in cases:
                code, _, err = self.run_main(argv)
                self.assertEqual(code, 1, argv)
                self.assertIn("error:", err)
            usage_errors = [["demo", "--run-dir", str(run), "--esp", "127.0.0.1:1",
                             "--data-dir", tmp, "--port", "70000"],
                            ["fake-esp32", "--csv", str(good_csv), "--port", "-1"],
                            ["live", "--run-dir", str(run), "--esp", "127.0.0.1:1",
                             "--max-predictions", "0"]]
            for argv in usage_errors:
                with self.assertRaises(SystemExit) as ctx:
                    self.run_main(argv)
                self.assertEqual(ctx.exception.code, 2, argv)

    def test_fake_esp32_bad_csv_exits_1(self):
        with TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.csv"
            bad.write_text("x\n", encoding="utf-8")
            code, _, err = self.run_main(["fake-esp32", "--csv", str(bad), "--port", "0"])
        self.assertEqual(code, 1)
        self.assertIn("error:", err)
