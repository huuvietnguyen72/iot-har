"""BARO records: parsing, filtering in the recorder, and the .baro.csv file."""
import csv
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from collector.collect import collect
from collector.line_reader import SerialLineReader
from collector.protocol import BaroSample, ParseError, parse_baro_line, parse_line
from collector.quality import QualityTracker
from collector.recorder import Recorder
from collector.session import BARO_HEADER
from collector.tests.fakes import FakeClock, FakeSerial

A = "7a31b25c809fd416"
B = "1122334455667788"


def data(seq, time_us, stream=A):
    return (f"DATA,1,{stream},{seq},{time_us},0.000,0.000,1.000,"
            f"0.000,0.000,0.000,25.00\n").encode()


def baro(seq, time_us, pressure="100812.44", stream=A):
    return f"BARO,1,{stream},{seq},{time_us},{pressure},28.41\n".encode()


class ParseBaroTests(unittest.TestCase):
    def test_valid_record(self):
        self.assertEqual(parse_baro_line(f"BARO,1,{A},5,100000,100812.44,28.41\r\n"),
                         BaroSample(A, 5, 100000, 100812.44, 28.41))

    def test_other_lines_are_not_baro(self):
        for line in (f"DATA,1,{A},0,0,0,0,1,0,0,0,25", "[NET],1,,0,0", "[BARO] no BMP280", ""):
            self.assertIsNone(parse_baro_line(line), line)

    def test_malformed_records_raise(self):
        for line in (f"BARO,1,{A},5,100000,100812.44",            # too few fields
                     f"BARO,2,{A},5,100000,100812.44,28.41",      # other version
                     "BARO,1,xyz,5,100000,100812.44,28.41",       # bad stream id
                     f"BARO,1,{A},-1,100000,100812.44,28.41",     # negative seq
                     f"BARO,1,{A},5,100000,nan,28.41",            # not finite
                     f"BARO,1,{A},5,100000,5000.00,28.41"):       # implausible pressure
            with self.assertRaises(ParseError, msg=line):
                parse_baro_line(line)

    def test_data_parser_still_ignores_baro(self):
        self.assertIsNone(parse_line(f"BARO,1,{A},5,100000,100812.44,28.41"))


class RecorderBaroTests(unittest.TestCase):
    def run_recorder(self, chunks, duration_s=0.05):
        clock = FakeClock()
        serial = FakeSerial(chunks, clock=clock, read_delay=0.005)
        tracker = QualityTracker()
        samples, readings = [], []
        recorder = Recorder(SerialLineReader(serial), tracker,
                            lambda s, elapsed: samples.append(s), clock=clock,
                            baro_sink=readings.append)
        status = recorder.run(duration_s)
        return status, recorder, tracker, samples, readings

    def test_baro_of_the_recorded_stream_is_kept(self):
        status, recorder, tracker, samples, readings = self.run_recorder(
            [data(0, 0) + baro(0, 100) + data(1, 20000)])
        self.assertEqual(status, "completed")
        self.assertEqual([r.seq for r in readings], [0])
        self.assertEqual(tracker.data_errors, 0)
        self.assertEqual(len(samples), 2)

    def test_baro_before_first_data_or_from_other_stream_is_dropped(self):
        _, recorder, _, _, readings = self.run_recorder(
            [baro(0, 100) + data(0, 0) + baro(1, 100, stream=B) + baro(5, 100100)])
        self.assertEqual([r.seq for r in readings], [5])
        self.assertEqual(recorder.baro_other_stream, 2)

    def test_malformed_baro_is_counted_but_not_a_data_error(self):
        _, recorder, tracker, samples, readings = self.run_recorder(
            [data(0, 0) + b"BARO,1,broken\n" + data(1, 20000)])
        self.assertEqual(recorder.baro_errors, 1)
        self.assertEqual(tracker.data_errors, 0)
        self.assertEqual(readings, [])
        self.assertEqual(len(samples), 2)

    def test_baro_does_not_keep_a_silent_session_alive(self):
        clock = FakeClock()
        serial = FakeSerial([data(0, 0)] + [baro(i, i) for i in range(10)], clock=clock,
                            read_delay=0.5)
        recorder = Recorder(SerialLineReader(serial), QualityTracker(), lambda s, e: None,
                            clock=clock, baro_sink=lambda b: None)
        self.assertEqual(recorder.run(100.0), "no_data")

    def test_without_baro_sink_baro_lines_are_ignored(self):
        clock = FakeClock()
        serial = FakeSerial([data(0, 0) + baro(0, 100)], clock=clock, read_delay=0.005)
        statuses = []
        recorder = Recorder(SerialLineReader(serial), QualityTracker(), lambda s, e: None,
                            clock=clock, status_sink=statuses.append)
        self.assertEqual(recorder.run(0.02), "completed")
        self.assertEqual(recorder.baro_errors, 0)


class CollectBaroTests(unittest.TestCase):
    def collect(self, chunks, tmp):
        clock = FakeClock()
        serial = FakeSerial(chunks, clock=clock, read_delay=0.01)
        return collect(serial, output_dir=Path(tmp), label="stairs_up", port=None, baud=None,
                       duration_s=1.0, clock=clock, transport_kind="tcp", endpoint="esp:8765")

    def test_baro_file_and_metadata(self):
        with TemporaryDirectory() as tmp:
            result = self.collect([data(0, 0) + baro(0, 500, "100812.44"),
                                   data(1, 20000), data(2, 40000),
                                   data(3, 60000), data(4, 80000),
                                   data(5, 100000) + baro(5, 100500, "100809.10")], tmp)
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.baro_path.name, f"{result.session_id}.baro.csv")
            with result.baro_path.open(newline="", encoding="utf-8") as fh:
                rows = list(csv.reader(fh))
            self.assertEqual(rows[0], BARO_HEADER)
            self.assertEqual(rows[1], [result.session_id, A, "0", "500", "100812.44", "28.41"])
            self.assertEqual(rows[2][2:5], ["5", "100500", "100809.10"])
            meta = json.loads(result.json_path.read_text(encoding="utf-8"))
            self.assertEqual(meta["baro_file"], result.baro_path.name)
            self.assertEqual(meta["baro_samples"], 2)

    def test_no_baro_lines_means_no_baro_file(self):
        with TemporaryDirectory() as tmp:
            result = self.collect([data(0, 0), data(1, 20000)], tmp)
            self.assertIsNone(result.baro_path)
            self.assertEqual(list(Path(tmp).glob("*.baro.csv")), [])
            meta = json.loads(result.json_path.read_text(encoding="utf-8"))
            self.assertIsNone(meta["baro_file"])
            self.assertEqual(meta["baro_samples"], 0)


if __name__ == "__main__":
    unittest.main()
