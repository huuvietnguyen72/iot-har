import io
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from tempfile import TemporaryDirectory
from unittest import mock

from collector.cli import EXIT_CODES, main, parse_args
from collector.tests.fakes import FakeClock, FakeSerial

A = "7a31b25c809fd416"


def data(seq, time_us):
    return (f"DATA,1,{A},{seq},{time_us},0.000,0.000,1.000,"
            f"0.000,0.000,0.000,25.00\n").encode()


class ParseArgsTests(unittest.TestCase):
    def test_defaults(self):
        args = parse_args(["--port", "/dev/ttyUSB0"])
        self.assertEqual(args.baud, 115200)
        self.assertEqual(args.duration, 60.0)
        self.assertEqual(args.label, "test")
        self.assertEqual(args.output, "data")

    def test_bad_duration_rejected(self):
        for bad in ("0", "-5", "nan", "inf"):
            with self.assertRaises(SystemExit) as ctx:
                parse_args(["--port", "p", "--duration", bad])
            self.assertEqual(ctx.exception.code, 2)

    def test_bad_label_rejected(self):
        with self.assertRaises(SystemExit) as ctx:
            parse_args(["--port", "p", "--label", "walk up"])
        self.assertEqual(ctx.exception.code, 2)

    def test_label_with_trailing_newline_rejected(self):
        with self.assertRaises(SystemExit) as ctx:
            parse_args(["--port", "p", "--label", "test\n"])
        self.assertEqual(ctx.exception.code, 2)

    def test_exit_codes(self):
        self.assertEqual(EXIT_CODES["completed"], 0)
        self.assertEqual(EXIT_CODES["interrupted"], 130)
        self.assertEqual(EXIT_CODES["no_data"], 3)
        self.assertEqual(EXIT_CODES["wait_timeout"], 3)
        self.assertEqual(EXIT_CODES["stream_changed"], 4)
        self.assertEqual(EXIT_CODES["serial_error"], 5)
        self.assertEqual(EXIT_CODES["connection_lost"], 5)

    def test_transport_selection_requires_exactly_one(self):
        for argv in ([], ["--port", "p", "--tcp", "h:1"], ["--discover", "--port", "p"]):
            with self.assertRaises(SystemExit) as ctx:
                parse_args(argv)
            self.assertEqual(ctx.exception.code, 2)

    def test_tcp_endpoint_must_be_host_port(self):
        with self.assertRaises(SystemExit) as ctx:
            parse_args(["--tcp", "nohost"])
        self.assertEqual(ctx.exception.code, 2)


class MainTests(unittest.TestCase):
    def setUp(self):
        self._stack = ExitStack()
        self.addCleanup(self._stack.close)
        self._stack.enter_context(redirect_stdout(io.StringIO()))
        self._stack.enter_context(redirect_stderr(io.StringIO()))

    def test_open_failure_returns_5(self):
        rc = main(["--port", "/dev/none", "--output", "unused"],
                  open_serial_fn=mock.Mock(side_effect=OSError("no such port")))
        self.assertEqual(rc, 5)

    def test_completed_returns_0_and_closes_port(self):
        clock = FakeClock()
        serial = FakeSerial([data(0, 0), data(1, 20000)], clock=clock, read_delay=0.01)
        with TemporaryDirectory() as tmp:
            rc = main(["--port", "fake", "--output", tmp, "--duration", "1"],
                      open_serial_fn=lambda port, baud: serial, clock=clock)
        self.assertEqual(rc, 0)
        self.assertTrue(serial.closed)

    def test_interrupted_returns_130(self):
        clock = FakeClock()
        serial = FakeSerial([data(0, 0)], clock=clock, read_delay=0.01)
        serial.error_on_read = KeyboardInterrupt()
        serial.error_after_reads = 1
        with TemporaryDirectory() as tmp:
            rc = main(["--port", "fake", "--output", tmp, "--duration", "1"],
                      open_serial_fn=lambda port, baud: serial, clock=clock)
        self.assertEqual(rc, 130)

    def test_no_data_returns_3(self):
        clock = FakeClock()
        serial = FakeSerial([], clock=clock, read_delay=10.0)
        with TemporaryDirectory() as tmp:
            rc = main(["--port", "fake", "--output", tmp],
                      open_serial_fn=lambda port, baud: serial, clock=clock)
        self.assertEqual(rc, 3)

    def test_tcp_run_completes_and_writes_tcp_metadata(self):
        clock = FakeClock()
        stream = FakeSerial(
            [b"[NET],1," + A.encode() + b",0,0\n" + data(0, 0) + data(1, 20000)],
            clock=clock, read_delay=0.01)
        with TemporaryDirectory() as tmp:
            rc = main(["--tcp", "127.0.0.1:8765", "--output", tmp, "--duration", "1"],
                      open_tcp_fn=lambda host, port: stream, clock=clock)
            self.assertEqual(rc, 0)
            self.assertTrue(stream.closed)
            import json
            from pathlib import Path
            meta = json.loads(next(Path(tmp).glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(meta["transport"], "tcp")
            self.assertEqual(meta["endpoint"], "127.0.0.1:8765")

    def test_connection_lost_returns_5(self):
        from collector.tcp_transport import ConnectionLost
        clock = FakeClock()
        stream = FakeSerial([data(0, 0)], clock=clock, read_delay=0.01)
        stream.error_on_read = ConnectionLost("peer closed")
        stream.error_after_reads = 1
        with TemporaryDirectory() as tmp:
            rc = main(["--tcp", "127.0.0.1:8765", "--output", tmp, "--duration", "30"],
                      open_tcp_fn=lambda host, port: stream, clock=clock)
        self.assertEqual(rc, 5)

    def test_discover_resolves_endpoint(self):
        clock = FakeClock()
        stream = FakeSerial([data(0, 0), data(1, 20000)], clock=clock, read_delay=0.01)
        with TemporaryDirectory() as tmp:
            rc = main(["--discover", "--output", tmp, "--duration", "1"],
                      open_tcp_fn=lambda host, port: stream,
                      discover_fn=lambda: ("10.0.0.5", 8765), clock=clock)
        self.assertEqual(rc, 0)

    def test_tcp_open_failure_returns_5(self):
        rc = main(["--tcp", "127.0.0.1:9", "--output", "unused"],
                  open_tcp_fn=mock.Mock(side_effect=OSError("refused")))
        self.assertEqual(rc, 5)


if __name__ == "__main__":
    unittest.main()
