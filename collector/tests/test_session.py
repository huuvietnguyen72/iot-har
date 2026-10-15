import json
import random
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from collector.protocol import Sample
from collector.session import SessionWriter, generate_session_id

HEADER = ("session_id,label,stream_id,seq,device_time_us,host_elapsed_s,"
          "ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps,temp_c")


def sample(seq=0, stream_id="7a31b25c809fd416"):
    return Sample(stream_id=stream_id, seq=seq, device_time_us=seq * 20000,
                  ax_g=-0.921, ay_g=0.051, az_g=0.132,
                  gx_dps=0.12, gy_dps=-0.08, gz_dps=0.05, temp_c=29.4)


def make_writer(tmp, **kwargs):
    return SessionWriter(output_dir=Path(tmp), label="test", port="/dev/ttyUSB0",
                         baud=115200, requested_duration_s=60.0, **kwargs)


class SessionIdTests(unittest.TestCase):
    def test_format(self):
        session_id = generate_session_id(
            now=datetime(2026, 10, 9, 12, 34, 56, tzinfo=timezone.utc),
            rng=random.Random(42))
        self.assertRegex(session_id, r"^20261009T123456Z-[0-9a-f]{8}$")


class SessionWriterTests(unittest.TestCase):
    def test_csv_written_on_first_sample(self):
        with TemporaryDirectory() as tmp:
            writer = make_writer(tmp)
            writer.write(sample(seq=3), host_elapsed_s=0.0)
            paths = writer.finalize(status="completed", stats={"samples_written": 1})
            rows = Path(paths["csv"]).read_text(encoding="utf-8").splitlines()
            self.assertEqual(rows[0], HEADER)
            fields = rows[1].split(",")
            self.assertEqual(fields[1], "test")
            self.assertEqual(fields[2], "7a31b25c809fd416")
            self.assertEqual(fields[3], "3")
            self.assertEqual(fields[4], "60000")
            self.assertEqual(fields[5], "0.000000")
            self.assertEqual(fields[6], "-0.921")
            self.assertEqual(fields[12], "29.40")
            self.assertEqual(len(rows), 2)

    def test_no_csv_without_samples(self):
        with TemporaryDirectory() as tmp:
            writer = make_writer(tmp)
            paths = writer.finalize(status="no_data", stats={})
            self.assertIsNone(paths["csv"])
            self.assertEqual(list(Path(tmp).glob("*.csv")), [])
            self.assertEqual(json.loads(Path(paths["json"]).read_text(encoding="utf-8"))["status"],
                             "no_data")

    def test_metadata_recording_then_completed(self):
        with TemporaryDirectory() as tmp:
            writer = make_writer(tmp)
            initial = json.loads(
                Path(tmp, f"{writer.session_id}.json").read_text(encoding="utf-8"))
            self.assertEqual(initial["status"], "recording")
            paths = writer.finalize(status="completed", stats={"samples_written": 7})
            meta = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
            self.assertEqual(meta["status"], "completed")
            self.assertEqual(meta["stats"], {"samples_written": 7})
            self.assertEqual(meta["protocol_version"], 1)
            self.assertEqual(meta["requested_duration_s"], 60.0)
            self.assertEqual(meta["sensor_config"]["gyro_range_dps"], 500)
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])

    def test_duplicate_session_id_is_not_overwritten(self):
        with TemporaryDirectory() as tmp:
            first = "20261009T000000Z-00000001"
            second = "20261009T000000Z-00000002"
            kept = Path(tmp, f"{first}.json")
            kept.write_text("keep", encoding="utf-8")
            ids = iter([first, second])
            writer = make_writer(tmp, id_factory=lambda: next(ids))
            self.assertEqual(writer.session_id, second)
            self.assertEqual(kept.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
