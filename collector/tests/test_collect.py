import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from collector.collect import collect
from collector.session import SessionWriter
from collector.tests.fakes import FakeClock, FakeSerial

A = "7a31b25c809fd416"


def data(seq, time_us):
    return (f"DATA,1,{A},{seq},{time_us},0.000,0.000,1.000,"
            f"0.000,0.000,0.000,25.00\n").encode()


def run_collect(serial, clock, tmp, duration_s=1.0):
    return collect(serial, output_dir=Path(tmp), label="test", port="/dev/ttyUSB0",
                   baud=115200, duration_s=duration_s, clock=clock)


class CollectTests(unittest.TestCase):
    def test_completed_writes_csv_and_json(self):
        clock = FakeClock()
        serial = FakeSerial([data(0, 0), data(1, 20000)], clock=clock, read_delay=0.01)
        with TemporaryDirectory() as tmp:
            result = run_collect(serial, clock, tmp)
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.stats["samples_written"], 2)
            self.assertTrue(result.csv_path.exists())
            self.assertTrue(result.json_path.exists())

    def test_interrupt_saves_partial_data(self):
        clock = FakeClock()
        serial = FakeSerial([data(0, 0), data(1, 20000)], clock=clock, read_delay=0.01)
        serial.error_on_read = KeyboardInterrupt()
        serial.error_after_reads = 1
        with TemporaryDirectory() as tmp:
            result = run_collect(serial, clock, tmp)
            self.assertEqual(result.status, "interrupted")
            rows = result.csv_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(rows), 2)

    def test_write_error_propagates(self):
        clock = FakeClock()
        serial = FakeSerial([data(0, 0)], clock=clock, read_delay=0.01)
        with TemporaryDirectory() as tmp, mock.patch.object(
                SessionWriter, "write", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                run_collect(serial, clock, tmp)

    def test_empty_stream_ends_as_wait_timeout(self):
        clock = FakeClock()
        serial = FakeSerial([], clock=clock, read_delay=10.0)
        with TemporaryDirectory() as tmp:
            result = run_collect(serial, clock, tmp)
            self.assertEqual(result.status, "wait_timeout")
            self.assertIsNone(result.csv_path)
            self.assertTrue(result.json_path.exists())

    def test_tcp_transport_metadata_and_telemetry(self):
        clock = FakeClock()
        stream = FakeSerial(
            [b"[NET],1," + A.encode() + b",5,9\n" + data(0, 0) + data(1, 20000)],
            clock=clock, read_delay=0.01)
        with TemporaryDirectory() as tmp:
            result = collect(stream, output_dir=Path(tmp), label="test", port=None,
                             baud=None, duration_s=1.0, clock=clock,
                             transport_kind="tcp", endpoint="1.2.3.4:8765")
            self.assertEqual(result.status, "completed")
            meta = json.loads(result.json_path.read_text(encoding="utf-8"))
            self.assertEqual(meta["transport"], "tcp")
            self.assertEqual(meta["endpoint"], "1.2.3.4:8765")
            self.assertIsNone(meta["port"])
            self.assertIsNone(meta["baud"])
            self.assertEqual(meta["telemetry_errors"], 0)
            self.assertEqual(meta["firmware_counters_first"]["stream_id"], A)
            self.assertEqual(meta["firmware_counters_first"]["queue_dropped_total"], 5)
            self.assertEqual(meta["firmware_counters_last"]["unobserved_total"], 9)

    def test_serial_metadata_has_null_telemetry(self):
        clock = FakeClock()
        serial = FakeSerial([data(0, 0), data(1, 20000)], clock=clock, read_delay=0.01)
        with TemporaryDirectory() as tmp:
            result = run_collect(serial, clock, tmp)
            meta = json.loads(result.json_path.read_text(encoding="utf-8"))
            self.assertEqual(meta["transport"], "serial")
            self.assertEqual(meta["port"], "/dev/ttyUSB0")
            self.assertIsNone(meta["firmware_counters_first"])


if __name__ == "__main__":
    unittest.main()
