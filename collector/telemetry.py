"""Parse [NET] telemetry lines and keep a per-session snapshot."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, replace

from .protocol import STREAM_ID_RE

NET_PREFIX = "[NET]"
NET_VERSION = 1
NET_FIELD_COUNT = 5


class NetError(ValueError):
    """A line that starts with [NET] but is not a valid v1 telemetry line."""


@dataclass(frozen=True)
class NetSnapshot:
    stream_id: str
    queue_dropped_total: int
    unobserved_total: int
    host_since_open_s: float = 0.0


def _nonneg_int(field, name):
    if not field.isdigit():
        raise NetError(f"{name} is not a non-negative integer: {field!r}")
    return int(field)


def parse_net_line(line):
    line = line.strip("\r\n")
    if not line.startswith(NET_PREFIX):
        return None
    fields = line.split(",")
    if len(fields) != NET_FIELD_COUNT or fields[0] != NET_PREFIX:
        raise NetError(f"malformed NET line: {line!r}")
    if fields[1] != str(NET_VERSION):
        raise NetError(f"unsupported NET version: {fields[1]!r}")
    if not STREAM_ID_RE.match(fields[2]):
        raise NetError(f"invalid stream_id: {fields[2]!r}")
    return NetSnapshot(fields[2], _nonneg_int(fields[3], "queue_dropped_total"),
                       _nonneg_int(fields[4], "unobserved_total"))


class NetTracker:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._open_at = clock()
        self._stream = None
        self._pending_first = None
        self.first = None
        self.last = None
        self.telemetry_errors = 0

    def observe(self, line):
        try:
            snapshot = parse_net_line(line)
        except NetError:
            self.telemetry_errors += 1
            return False
        if snapshot is None:
            return False
        stamped = replace(snapshot,
                          host_since_open_s=round(self._clock() - self._open_at, 6))
        if self._stream is None:
            self._pending_first = stamped
            return True
        if stamped.stream_id != self._stream:
            return False
        if self.first is None:
            self.first = stamped
        self.last = stamped
        return True

    def bind_stream(self, stream_id):
        self._stream = stream_id
        if self._pending_first is not None:
            if self._pending_first.stream_id == stream_id:
                self.first = self._pending_first
                self.last = self._pending_first
            self._pending_first = None
        if self.first is not None and self.first.stream_id != stream_id:
            self.first = None
            self.last = None

    def as_dict(self):
        return {
            "first": asdict(self.first) if self.first is not None else None,
            "last": asdict(self.last) if self.last is not None else None,
            "telemetry_errors": self.telemetry_errors,
        }
