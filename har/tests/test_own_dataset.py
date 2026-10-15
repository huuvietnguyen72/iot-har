import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

from har.config import LABELS
from har.own_dataset import load_own_sessions, require_session_counts, session_fold_groups
from har.tests.fixtures import write_own_session

T0 = "2026-10-14T08:00:00Z"


class LoadOwnSessionsTests(unittest.TestCase):
    def test_valid_session_is_trimmed(self):
        with TemporaryDirectory() as tmp:
            write_own_session(tmp, "s-walk", "walk", T0)
            windows, sessions = load_own_sessions(tmp, "train")
            self.assertEqual(windows.windows.shape, (6, 128, 6))
            self.assertEqual(set(windows.labels), {"walk"})
            self.assertEqual(set(windows.subjects), {"s-walk"})
            self.assertEqual(windows.split, "train")
            entry = sessions[0]
            self.assertTrue(entry["accepted"])
            self.assertIsNone(entry["reason"])
            self.assertEqual((entry["windows"], entry["trimmed_windows"]), (6, 8))
            self.assertEqual(len(entry["csv_sha256"]), 64)

    def test_rejection_reasons(self):
        cases = {
            "protocol": ({"meta": {"protocol_version": 2}}, "protocol_version"),
            "status": ({"meta": {"status": "interrupted"}}, "status"),
            "started": ({"meta": {"started_utc": "yesterday"}}, "started_utc"),
            "range": ({"meta": {"sensor_config": {"accel_range_g": 2}}}, "accel_range_g"),
            "stats": ({"meta": {"stats": {"data_errors": 1}}}, "data_errors"),
            "nocsv": ({"write_csv": False}, "not found"),
            "csvlabel": ({"csv_label": "sit"}, "does not match"),
            "short": ({"seconds": 12}, "no windows left"),
            "gyro": ({"meta": {"sensor_config": {"gyro_range_dps": 250}}}, "gyro_range_dps"),
            "notz": ({"meta": {"started_utc": "2026-10-14T08:00:00"}}, "no timezone"),
            "csvpath": ({"meta": {"csv_file": "sub/x.csv"}}, "plain file name"),
        }
        for name, (kwargs, reason) in cases.items():
            with self.subTest(name=name), TemporaryDirectory() as tmp:
                write_own_session(tmp, f"s-{name}", "walk", T0, **kwargs)
                windows, sessions = load_own_sessions(tmp, "train")
                self.assertFalse(sessions[0]["accepted"])
                self.assertIn(reason, sessions[0]["reason"])
                self.assertEqual(len(windows.labels), 0)

    def test_unknown_label_rejected(self):
        with TemporaryDirectory() as tmp:
            write_own_session(tmp, "s-jump", "jump", T0)
            _, sessions = load_own_sessions(tmp, "train")
            self.assertFalse(sessions[0]["accepted"])
            self.assertIn("label 'jump'", sessions[0]["reason"])

    def test_mixed_directory_keeps_only_accepted(self):
        with TemporaryDirectory() as tmp:
            for label in LABELS:
                write_own_session(tmp, f"ok-{label}", label, T0)
            write_own_session(tmp, "bad", "walk", T0, meta={"status": "no_data"})
            windows, sessions = load_own_sessions(tmp, "train")
            self.assertEqual(len(sessions), 5)
            self.assertEqual(len(windows.labels), 24)
            self.assertNotIn("bad", set(windows.subjects))

    def test_duplicate_session_id_is_rejected(self):
        with TemporaryDirectory() as tmp:
            json_path = write_own_session(tmp, "s-walk", "walk", T0)
            shutil.copy(json_path, Path(tmp) / "s-walk - Copy.json")
            windows, sessions = load_own_sessions(tmp, "train")
            self.assertEqual(len(sessions), 2)
            self.assertEqual([s["accepted"] for s in sessions].count(True), 1)
            rejected = next(s for s in sessions if not s["accepted"])
            self.assertEqual(rejected["windows"], 0)
            self.assertIn("duplicate session_id", rejected["reason"])
            self.assertEqual(len(windows.labels), 6)

    def test_json_with_bom_is_accepted(self):
        with TemporaryDirectory() as tmp:
            json_path = write_own_session(tmp, "s-walk", "walk", T0)
            json_path.write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8-sig")
            _, sessions = load_own_sessions(tmp, "train")
            self.assertTrue(sessions[0]["accepted"], sessions[0]["reason"])

    def test_non_string_metadata_values_are_not_copied_to_entry(self):
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "nan.json").write_text(
                '{"protocol_version": 1, "status": "completed", "session_id": NaN}',
                encoding="utf-8")
            _, sessions = load_own_sessions(tmp, "train")
            self.assertFalse(sessions[0]["accepted"])
            self.assertIsNone(sessions[0]["session_id"])
            json.dumps(sessions[0], allow_nan=False)

    def test_empty_directory_is_error(self):
        with TemporaryDirectory() as tmp, self.assertRaisesRegex(ValueError, "no session JSON"):
            load_own_sessions(tmp, "train")


def fake_sessions(per_label, accepted=True):
    return [{"label": label, "accepted": accepted, "session_id": f"{label}-{k}",
             "started_utc": T0} for label in LABELS for k in range(per_label)]


class SessionCountTests(unittest.TestCase):
    def test_train_needs_four_per_activity(self):
        sessions = fake_sessions(4)
        self.assertEqual(require_session_counts(sessions, "train"), {l: 4 for l in LABELS})
        with self.assertRaisesRegex(ValueError, "walk=3"):
            require_session_counts(sessions[1:], "train")

    def test_rejected_sessions_do_not_count(self):
        sessions = fake_sessions(4)
        sessions[0]["accepted"] = False
        with self.assertRaisesRegex(ValueError, "at least 4"):
            require_session_counts(sessions, "train")

    def test_test_needs_every_activity(self):
        self.assertEqual(require_session_counts(fake_sessions(1), "test"), {l: 1 for l in LABELS})
        missing_lie = [s for s in fake_sessions(1) if s["label"] != "lie"]
        with self.assertRaisesRegex(ValueError, "lie=0"):
            require_session_counts(missing_lie, "test")


class FoldGroupTests(unittest.TestCase):
    def test_order_by_start_time_and_wrap(self):
        sessions = []
        for label in LABELS:
            for k in range(5):
                # k=0 is the latest session: names are in reverse time order
                sessions.append({"label": label, "accepted": True, "session_id": f"{label}-{k}",
                                 "started_utc": f"2026-10-14T08:{50 - k * 10:02d}:00Z"})
        groups = session_fold_groups(sessions)
        self.assertEqual(groups["walk-4"], 0)
        self.assertEqual(groups["walk-1"], 3)
        self.assertEqual(groups["walk-0"], 0)
        for fold in range(4):
            labels = {s["label"] for s in sessions if groups[s["session_id"]] == fold}
            self.assertEqual(labels, set(LABELS))

    def test_rejected_sessions_have_no_fold(self):
        self.assertEqual(session_fold_groups(fake_sessions(1, accepted=False)), {})
