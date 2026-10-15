"""Sample sources for the demo: recorded collector CSVs and the ESP32 over TCP."""
import csv
import json
from pathlib import Path
import time

from collector.line_reader import SerialLineReader
from collector.protocol import ParseError, parse_line
from collector.tcp_transport import ConnectionLost, TcpTransport

from .own_dataset import _metadata_problem, parse_utc
from .stream_windows import StreamSample, read_csv_samples

REPLAY_SPEEDS = (1, 2, 4)
SAMPLE_PERIOD_S = 0.02
MAX_REPLAY_STEP_S = 1.0


def parse_endpoint(text):
    """'host:port' -> (host, port); ValueError otherwise."""
    host, sep, port = str(text).rpartition(":")
    if (not sep or not host or any(c.isspace() for c in host)
            or not port.isdigit() or not 0 < int(port) < 65536):
        raise ValueError(f"--esp must look like host:port, got {text!r}")
    try:
        host.encode("idna")
    except UnicodeError:
        raise ValueError(f"--esp must look like host:port (invalid host), got {text!r}") from None
    return host, int(port)


def list_replay_sessions(data_dir):
    """Sessions in data_dir/test and data_dir/train that pass the train-own metadata checks."""
    root = Path(data_dir)
    sessions, seen = [], set()
    for split in ("test", "train"):
        folder = root / split
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.json")):
            try:
                meta = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
            if _metadata_problem(meta, folder) or meta["session_id"] in seen:
                continue
            seen.add(meta["session_id"])
            sessions.append({"session_id": meta["session_id"], "split": split,
                             "label": meta["label"], "started_utc": meta["started_utc"],
                             "csv": folder / meta["csv_file"]})
    sessions.sort(key=lambda s: (s["split"] != "test", parse_utc(s["started_utc"]), s["session_id"]))
    return sessions


class ReplaySource:
    """Play collector CSVs back to back, paced by device_time_us / speed.

    sleep=None means stop.wait, so stopping is immediate.
    """

    def __init__(self, csv_paths, speed=1, *, clock=time.monotonic, sleep=None):
        if isinstance(speed, bool) or speed not in REPLAY_SPEEDS:
            raise ValueError("speed must be 1, 2 or 4")
        if not csv_paths:
            raise ValueError("replay needs at least one session")
        self._paths = [Path(p) for p in csv_paths]
        self._speed = speed
        self._clock = clock
        self._sleep = sleep

    def run(self, sink, stop):
        sleep = self._sleep or stop.wait
        started = self._clock()
        schedule_s = 0.0
        previous = None
        path = None
        try:
            for path in self._paths:
                first = True
                for sample in read_csv_samples(path):
                    if stop.is_set():
                        return
                    if first:
                        sink.status(state="replaying", session=sample.session_id)
                        first = False
                    if previous is not None:
                        step = (sample.time_us - previous) / 1e6
                        schedule_s += step if 0 < step <= MAX_REPLAY_STEP_S else SAMPLE_PERIOD_S
                    previous = sample.time_us
                    delay = started + schedule_s / self._speed - self._clock()
                    if delay > 0:
                        sleep(delay)
                    if stop.is_set():
                        return
                    sink.sample(sample)
        except (OSError, ValueError, csv.Error) as exc:
            name = path.name if path is not None else "replay"
            sink.status(state="error", session=None, message=f"{name}: {exc}")
            return
        sink.status(state="finished", session=None)


class _IdleTimeout(ConnectionLost):
    """No line arrived for idle_timeout_s; always reported as "lost", never "busy"."""


def _is_calibrating_net(line):
    """True for the firmware's boot-calibration NET line, '[NET],1,,<dropped>,<unobserved>'.

    The firmware's stream id stays empty until gyro calibration succeeds; afterwards every
    NET line carries the 16-hex stream id.
    """
    fields = line.strip().split(",")
    return len(fields) >= 3 and fields[0] == "[NET]" and fields[2] == ""


class EspSource:
    """Read DATA records from the ESP32 TCP server; reconnect forever until stopped.

    Status fields sent to sink.status():
      state        "connecting" (connecting or connected, no DATA yet, and the ESP32 has not
                   said it is calibrating), "calibrating" (the ESP32 reports it is calibrating:
                   a NET line with an empty stream id arrived, no DATA yet; sent once per
                   connection), "streaming" (DATA arriving), "lost" (connection dropped after a
                   line arrived, or no line for idle_timeout_s, even if none ever arrived),
                   "busy" (peer closed/reset before any line: another client holds the ESP32),
                   "error" (unexpected failure; run() returns).
                   Typical sequences: connecting -> streaming (already calibrated ESP32);
                   connecting -> calibrating -> streaming (ESP32 just booted);
                   connecting -> busy; connecting -> lost (silent connection).
      attempt      connection attempt number since the last streaming connection (0 once
                   streaming).
      endpoint     "host:port" (sent with each "connecting" status at the start of an attempt).
      message      reason for the last connect failure / lost / busy / error; kept while
                   retrying (also while connected without DATA) and cleared (None) on
                   "calibrating" and "streaming".
      parse_errors running count of malformed DATA lines (sent alone, without state).
    """

    def __init__(self, host, port, *, retry_s=3.0, idle_timeout_s=5.0, connect_timeout_s=3.0,
                 transport_factory=TcpTransport, clock=time.monotonic):
        self._host = host
        self._port = int(port)
        self._retry_s = retry_s
        self._idle_timeout_s = idle_timeout_s
        self._connect_timeout_s = connect_timeout_s
        self._factory = transport_factory
        self._clock = clock

    @property
    def endpoint(self):
        return f"{self._host}:{self._port}"

    def run(self, sink, stop):
        try:
            self._run(sink, stop)
        except Exception as exc:  # keep the worker thread from dying silently
            if not stop.is_set():
                sink.status(state="error", message=f"{type(exc).__name__}: {exc}")

    def _run(self, sink, stop):
        attempt = 0
        parse_errors = 0
        while not stop.is_set():
            attempt += 1
            sink.status(state="connecting", attempt=attempt, endpoint=self.endpoint)
            transport = self._factory(self._host, self._port, connect_timeout=self._connect_timeout_s)
            try:
                try:
                    transport.open()
                except OSError as exc:
                    if not stop.is_set():
                        sink.status(state="connecting", attempt=attempt, message=str(exc))
                        stop.wait(self._retry_s)
                    continue
                if stop.is_set():
                    return
                attempt, parse_errors = self._read(transport, sink, stop, attempt, parse_errors)
            finally:
                transport.close()
            if not stop.is_set():
                stop.wait(self._retry_s)

    def _read(self, transport, sink, stop, attempt, parse_errors):
        """Read one connection until it drops or stop is set; return (attempt, parse_errors)."""
        reader = SerialLineReader(transport)
        got_line = got_data = calibrating = False
        last_line = self._clock()
        try:
            while not stop.is_set():
                lines = reader.poll()  # blocks up to the transport read timeout (50 ms)
                now = self._clock()
                if lines:
                    last_line = now
                elif now - last_line > self._idle_timeout_s:
                    raise _IdleTimeout(f"no data for {self._idle_timeout_s:g} s")
                for line in lines:
                    if stop.is_set():
                        break
                    got_line = True
                    if not (got_data or calibrating) and _is_calibrating_net(line):
                        calibrating = True
                        sink.status(state="calibrating", attempt=attempt, message=None)
                        if stop.is_set():
                            break
                    try:
                        sample = parse_line(line)
                    except ParseError:
                        parse_errors += 1
                        sink.status(parse_errors=parse_errors)
                        continue
                    if sample is None:
                        continue
                    if not got_data:
                        got_data = True
                        attempt = 0
                        sink.status(state="streaming", attempt=0, message=None)
                        if stop.is_set():
                            break
                    sink.sample(StreamSample(
                        sample.stream_id, sample.seq, sample.device_time_us,
                        (sample.ax_g, sample.ay_g, sample.az_g,
                         sample.gx_dps, sample.gy_dps, sample.gz_dps)))
        except OSError as exc:  # ConnectionLost, _IdleTimeout, or any other socket error
            if not stop.is_set():
                lost = got_line or isinstance(exc, _IdleTimeout)
                sink.status(state="lost" if lost else "busy", attempt=attempt, message=str(exc))
        return attempt, parse_errors
