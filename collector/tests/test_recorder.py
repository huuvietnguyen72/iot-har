import unittest

from collector.line_reader import SerialLineReader
from collector.quality import QualityTracker
from collector.recorder import Recorder
from collector.tcp_transport import ConnectionLost
from collector.telemetry import NetTracker
from collector.tests.fakes import FakeClock, FakeSerial

A = "7a31b25c809fd416"
B = "1122334455667788"


def data(seq, time_us, stream=A):
    return (f"DATA,1,{stream},{seq},{time_us},0.000,0.000,1.000,"
            f"0.000,0.000,0.000,25.00\n").encode()


class RecorderTests(unittest.TestCase):
    def make(self, chunks, clock, **serial_kwargs):
        serial = FakeSerial(chunks, clock=clock, **serial_kwargs)
        reader = SerialLineReader(serial)
        tracker = QualityTracker()
        samples = []
        recorder = Recorder(reader, tracker,
                            lambda s, elapsed: samples.append((s, elapsed)),
                            clock=clock)
        return recorder, tracker, samples, serial

    def test_completes_after_duration_from_first_sample(self):
        clock = FakeClock()
        recorder, tracker, samples, _ = self.make(
            [data(0, 0), data(1, 20000), data(2, 40000)], clock, read_delay=0.005)
        self.assertEqual(recorder.run(1.0), "completed")
        self.assertEqual(tracker.samples_written, 3)
        self.assertEqual(samples[0][1], 0.0)
        self.assertGreater(samples[-1][1], 0.0)

    def test_wait_timeout_when_no_data(self):
        clock = FakeClock()
        recorder, tracker, samples, _ = self.make([], clock, read_delay=10.0)
        self.assertEqual(recorder.run(5.0), "wait_timeout")
        self.assertEqual(tracker.samples_written, 0)

    def test_gap_after_first_sample_ends_as_no_data(self):
        clock = FakeClock()
        recorder, tracker, samples, _ = self.make([data(0, 0)], clock, read_delay=1.0)
        self.assertEqual(recorder.run(100.0), "no_data")
        self.assertEqual(tracker.samples_written, 1)

    def test_stream_change_ends_session(self):
        clock = FakeClock()
        recorder, tracker, samples, _ = self.make(
            [data(0, 0), data(0, 0, stream=B)], clock, read_delay=0.001)
        self.assertEqual(recorder.run(10.0), "stream_changed")
        self.assertEqual(tracker.samples_written, 1)

    def test_parse_error_counted_and_recording_continues(self):
        clock = FakeClock()
        recorder, tracker, samples, _ = self.make(
            [b"DATA,1,broken\n" + data(0, 0)], clock, read_delay=0.005)
        self.assertEqual(recorder.run(0.2), "completed")
        self.assertEqual(tracker.data_errors, 1)
        self.assertEqual(tracker.samples_written, 1)

    def test_wait_phase_status_lines_are_forwarded(self):
        clock = FakeClock()
        serial = FakeSerial([b"[CAL] warming up\n" + data(0, 0)],
                            clock=clock, read_delay=0.005)
        reader = SerialLineReader(serial)
        tracker = QualityTracker()
        statuses = []
        recorder = Recorder(reader, tracker, lambda s, elapsed: None, clock=clock,
                            status_sink=statuses.append)
        self.assertEqual(recorder.run(0.05), "completed")
        self.assertEqual(statuses, ["[CAL] warming up"])

    def test_read_error_ends_as_serial_error(self):
        clock = FakeClock()
        recorder, tracker, samples, serial = self.make([], clock, read_delay=0.001)
        serial.error_on_read = OSError("port gone")
        self.assertEqual(recorder.run(10.0), "serial_error")

    def test_connection_lost_ends_session(self):
        clock = FakeClock()
        recorder, tracker, samples, serial = self.make([], clock, read_delay=0.001)
        serial.error_on_read = ConnectionLost("peer closed")
        self.assertEqual(recorder.run(10.0), "connection_lost")

    def test_net_line_is_consumed_and_bound_to_stream(self):
        clock = FakeClock()
        net = NetTracker(clock=clock)
        serial = FakeSerial([b"[NET],1," + A.encode() + b",0,0\n" + data(0, 0)],
                            clock=clock, read_delay=0.005)
        reader = SerialLineReader(serial)
        tracker = QualityTracker()
        statuses = []
        recorder = Recorder(reader, tracker, lambda s, elapsed: None, clock=clock,
                            status_sink=statuses.append, net_tracker=net)
        self.assertEqual(recorder.run(0.05), "completed")
        self.assertEqual(statuses, [])
        self.assertEqual(tracker.data_errors, 0)
        self.assertEqual(net.first.stream_id, A)

    def test_net_line_does_not_extend_no_data(self):
        clock = FakeClock()
        net = NetTracker(clock=clock)
        serial = FakeSerial([data(0, 0), b"[NET],1," + A.encode() + b",0,0\n"],
                            clock=clock, read_delay=0.5)
        reader = SerialLineReader(serial)
        tracker = QualityTracker()
        recorder = Recorder(reader, tracker, lambda s, elapsed: None, clock=clock,
                            net_tracker=net)
        self.assertEqual(recorder.run(100.0), "no_data")


if __name__ == "__main__":
    unittest.main()
