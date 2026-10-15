"""Parse DATA records of the MPU6050 USB collector protocol v1."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

PROTOCOL_VERSION = 1
STREAM_ID_RE = re.compile(r"^[0-9a-f]{16}$")
FIELD_COUNT = 12


class ParseError(ValueError):
    """A line that starts with DATA but is not a valid v1 record."""


@dataclass(frozen=True)
class Sample:
    stream_id: str
    seq: int
    device_time_us: int
    ax_g: float
    ay_g: float
    az_g: float
    gx_dps: float
    gy_dps: float
    gz_dps: float
    temp_c: float


def _parse_int(field: str, name: str) -> int:
    if not field.isdigit():
        raise ParseError(f"{name} is not a non-negative integer: {field!r}")
    try:
        return int(field)
    except ValueError:
        raise ParseError(f"{name} is not a non-negative integer: {field!r}") from None


def _parse_float(field: str, name: str) -> float:
    try:
        value = float(field)
    except ValueError:
        raise ParseError(f"{name} is not a number: {field!r}") from None
    if not math.isfinite(value):
        raise ParseError(f"{name} is not finite: {field!r}")
    return value


def parse_line(line: str) -> Sample | None:
    line = line.strip("\r\n")
    if not line.startswith("DATA"):
        return None
    fields = line.split(",")
    if len(fields) != FIELD_COUNT:
        raise ParseError(f"DATA record has {len(fields)} fields, expected {FIELD_COUNT}")
    if fields[1] != str(PROTOCOL_VERSION):
        raise ParseError(f"unsupported protocol version: {fields[1]!r}")
    if not STREAM_ID_RE.match(fields[2]):
        raise ParseError(f"invalid stream_id: {fields[2]!r}")
    seq = _parse_int(fields[3], "seq")
    if seq > 0xFFFFFFFF:
        raise ParseError(f"seq out of range: {seq}")
    return Sample(
        stream_id=fields[2],
        seq=seq,
        device_time_us=_parse_int(fields[4], "device_time_us"),
        ax_g=_parse_float(fields[5], "ax_g"),
        ay_g=_parse_float(fields[6], "ay_g"),
        az_g=_parse_float(fields[7], "az_g"),
        gx_dps=_parse_float(fields[8], "gx_dps"),
        gy_dps=_parse_float(fields[9], "gy_dps"),
        gz_dps=_parse_float(fields[10], "gz_dps"),
        temp_c=_parse_float(fields[11], "temp_c"),
    )
