import contextlib
import io
import re
import tempfile
import threading
import unittest
from unittest import mock

from har.live_terminal import TerminalPrinter, run_live
from har.stream_windows import StreamSample
from har.tests.test_inference import build_run

BASE = {"mode": "live", "attempt": 0, "endpoint": "1.2.3.4:8765", "stale": False, "restarts": 0,
        "rate_hz": 0.0, "missing": 0, "message": None}


def status(**fields):
    return dict(BASE, **fields)


class FailingSource:
    def run(self, sink, stop):
        sink.status(state="error", message="boom")


class FloodSource:
    def run(self, sink, stop):
        for seq in range(200):
            sink.sample(StreamSample("a" * 16, seq, seq * 20000, (0.1, 0.2, 1.0, 0.0, 0.0, 0.0)))
        stop.wait()


class BlockingSource:
    def __init__(self):
        self.stopped = False

    def run(self, sink, stop):
        stop.wait()
        self.stopped = stop.is_set()


class TerminalPrinterTests(unittest.TestCase):
    def setUp(self):
        self.out = io.StringIO()
        self.printer = TerminalPrinter(self.out)

    def lines(self):
        return self.out.getvalue().splitlines()

    def test_state_changes_print_once(self):
        self.printer("status", status(state="starting"))
        self.printer("status", status(state="connecting", attempt=1))
        self.printer("status", status(state="connecting", attempt=1))
        self.printer("status", status(state="connecting", attempt=2))
        self.printer("status", status(state="calibrating"))
        self.printer("status", status(state="busy"))
        self.printer("status", status(state="lost", message="mất kết nối"))
        self.printer("status", status(state="lost", message="mất kết nối"))
        self.printer("status", status(state="error", message="hỏng"))
        self.assertEqual(self.lines(), [
            "Đang tìm ESP32 (1.2.3.4:8765)… lần thử 1",
            "Đang tìm ESP32 (1.2.3.4:8765)… lần thử 2",
            "ESP32 đang hiệu chỉnh — để yên trên bàn",
            "ESP32 đang bận — tắt collector hoặc chương trình khác đang đọc",
            "Mất kết nối — đang thử lại",
            "  (lý do: mất kết nối)",
            "Lỗi: hỏng"])
        self.printer("status", status(state="streaming"))
        self.printer("status", status(state="lost", message="mất kết nối"))
        self.assertEqual(self.lines()[-1], "  (lý do: mất kết nối)")

    def test_stale_and_restart_messages(self):
        self.printer("status", status(state="streaming"))
        self.printer("status", status(state="streaming", stale=True))
        self.printer("status", status(state="streaming", restarts=1))
        self.assertEqual(self.lines(), ["Đã nhận dữ liệu từ ESP32", "Mất tín hiệu",
                                        "Có tín hiệu lại", "ESP32 vừa khởi động lại"])
        self.out.truncate(0)
        self.out.seek(0)
        self.printer("status", status(state="streaming", restarts=1))
        self.printer("status", status(state="streaming", restarts=1, stale=True))
        self.printer("status", status(state="lost", restarts=1, stale=False, message="no data for 5 s"))
        self.assertEqual(self.lines(), ["Mất tín hiệu", "Mất kết nối — đang thử lại",
                                        "  (lý do: no data for 5 s)"])

    def test_prediction_line(self):
        self.printer("status", status(state="streaming", rate_hz=50.0, missing=2))
        self.printer("prediction", {"time": 0.0, "label": "walk", "uncertain": False,
                                    "labels_order": None,
                                    "probabilities": [0.96, 0.01, 0.03, 0.0],
                                    "raw_label": "walk", "raw_probabilities": [0.94, 0.02, 0.04, 0.0]})
        line = self.lines()[-1]
        self.assertRegex(line, r"^\d\d:\d\d:\d\d  ĐI BỘ ")
        for part in ("96%", "(thô: walk 0.94)", "50.0 Hz", "mất 2 mẫu"):
            self.assertIn(part, line)
        self.assertEqual(self.printer.predictions, 1)

    def test_uncertain_flag(self):
        self.printer("prediction", {"time": 0.0, "label": "sit", "uncertain": True,
                                    "probabilities": [0.4, 0.3, 0.2, 0.1],
                                    "raw_label": "stand", "raw_probabilities": [0.1, 0.2, 0.5, 0.2]})
        self.assertTrue(self.lines()[-1].endswith("(không chắc)"))
        self.assertRegex(self.lines()[-1], r"NGỒI\s+40%")

    def test_ignores_samples(self):
        self.printer("samples", {"samples": [[0.02, 0, 0, 1]]})
        self.assertEqual(self.out.getvalue(), "")


class RunLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        with contextlib.redirect_stdout(io.StringIO()):
            cls.run_dir = build_run(cls._tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_run_live_returns_1_when_source_fails(self):
        out = io.StringIO()
        code = run_live(self.run_dir, "1.2.3.4", 8765, out=out, source=FailingSource())
        self.assertEqual(code, 1)
        self.assertIn("Lỗi: boom", out.getvalue())

    def test_run_live_returns_0_at_max_predictions(self):
        out = io.StringIO()
        code = run_live(self.run_dir, "h", 1, out=out, max_predictions=1, source=FloodSource())
        self.assertEqual(code, 0)
        self.assertRegex(out.getvalue(), r"\d\d:\d\d:\d\d  \S.* \d+%")

    def test_run_live_ctrl_c_returns_0(self):
        source = BlockingSource()
        with mock.patch("har.live_terminal.time.sleep", side_effect=KeyboardInterrupt):
            code = run_live(self.run_dir, "h", 1, out=io.StringIO(), source=source)
        self.assertEqual(code, 0)
        self.assertTrue(source.stopped)


if __name__ == "__main__":
    unittest.main()
