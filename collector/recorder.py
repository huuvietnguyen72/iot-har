"""Run the acquisition loop: parse lines, track quality, sink samples."""
from __future__ import annotations

import time

from .protocol import ParseError, parse_line
from .tcp_transport import ConnectionLost

WAIT_TIMEOUT_S = 60.0
GAP_TIMEOUT_S = 3.0


class Recorder:
    def __init__(self, reader, tracker, sink, *, clock=time.monotonic,
                 progress=None, progress_interval_s=1.0, status_sink=None,
                 net_tracker=None):
        self._reader = reader
        self._tracker = tracker
        self._sink = sink
        self._clock = clock
        self._progress = progress
        self._progress_interval_s = progress_interval_s
        self._status_sink = status_sink
        self._net_tracker = net_tracker

    def run(self, duration_s):
        started_at = self._clock()
        first_sample_at = None
        last_accepted_at = None
        current_stream = None
        oversize_seen = 0
        last_progress_at = started_at
        while True:
            now = self._clock()
            if first_sample_at is None:
                if now - started_at >= WAIT_TIMEOUT_S:
                    return "wait_timeout"
            else:
                if now - last_accepted_at >= GAP_TIMEOUT_S:
                    return "no_data"
                if now - first_sample_at >= duration_s:
                    return "completed"
            if self._progress is not None and now - last_progress_at >= self._progress_interval_s:
                self._progress(now - started_at, self._tracker.snapshot())
                last_progress_at = now
            try:
                lines = self._reader.poll()
            except ConnectionLost:
                return "connection_lost"
            except OSError:
                return "serial_error"
            new_oversize = self._reader.oversize_lines - oversize_seen
            if new_oversize > 0:
                self._tracker.record_oversize(new_oversize)
                oversize_seen = self._reader.oversize_lines
            for line in lines:
                try:
                    sample = parse_line(line)
                except ParseError:
                    self._tracker.record_error()
                    continue
                if sample is None:
                    if self._net_tracker is not None and self._net_tracker.observe(line):
                        continue
                    if first_sample_at is None and self._status_sink is not None:
                        self._status_sink(line)
                    continue
                if current_stream is None:
                    current_stream = sample.stream_id
                    if self._net_tracker is not None:
                        self._net_tracker.bind_stream(current_stream)
                elif sample.stream_id != current_stream:
                    return "stream_changed"
                if not self._tracker.record(sample):
                    continue
                accepted_at = self._clock()
                if first_sample_at is None:
                    first_sample_at = accepted_at
                    host_elapsed = 0.0
                else:
                    host_elapsed = accepted_at - first_sample_at
                last_accepted_at = accepted_at
                self._sink(sample, host_elapsed)
