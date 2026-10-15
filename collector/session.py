"""Write a recording session to CSV plus JSON metadata."""
from __future__ import annotations

import csv
import json
import os
import random
import re
from datetime import datetime, timezone
from pathlib import Path

from .protocol import PROTOCOL_VERSION

LABEL_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}\Z")

CSV_HEADER = [
    "session_id", "label", "stream_id", "seq", "device_time_us",
    "host_elapsed_s", "ax_g", "ay_g", "az_g", "gx_dps", "gy_dps", "gz_dps", "temp_c",
]

SENSOR_CONFIG = {
    "accel_range_g": 4,
    "gyro_range_dps": 500,
    "dlpf": 3,
    "internal_sample_rate_hz": 100,
    "output_interval_ms": 20,
}

FLUSH_EVERY_ROWS = 50
MAX_ID_ATTEMPTS = 5


def generate_session_id(now=None, rng=None):
    now = now or datetime.now(timezone.utc)
    rng = rng or random.Random()
    return now.strftime("%Y%m%dT%H%M%SZ") + "-" + format(rng.getrandbits(32), "08x")


class SessionWriter:
    def __init__(self, *, output_dir, label, port, baud, requested_duration_s,
                 transport="serial", endpoint=None, id_factory=generate_session_id):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.label = label
        self.port = port
        self.baud = baud
        self.requested_duration_s = requested_duration_s
        self.transport = transport
        self.endpoint = endpoint
        self.started_utc = datetime.now(timezone.utc)
        self._csv_fh = None
        self._csv_writer = None
        self._rows_since_flush = 0
        self._stream_id = None
        for _ in range(MAX_ID_ATTEMPTS):
            candidate = id_factory()
            try:
                handle = open(self._json_path(candidate), "x", encoding="utf-8")
            except FileExistsError:
                continue
            self.session_id = candidate
            with handle:
                json.dump(self._metadata("recording", {}, csv_file=None), handle,
                          indent=2, ensure_ascii=False)
            return
        raise FileExistsError("cannot allocate a unique session id")

    def _json_path(self, session_id=None):
        return self.output_dir / f"{session_id or self.session_id}.json"

    def _csv_path(self):
        return self.output_dir / f"{self.session_id}.csv"

    def _metadata(self, status, stats, csv_file, telemetry=None):
        finished = None
        if status != "recording":
            finished = datetime.now(timezone.utc)
        return {
            "protocol_version": PROTOCOL_VERSION,
            "session_id": self.session_id,
            "label": self.label,
            "status": status,
            "started_utc": self.started_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "finished_utc": finished.strftime("%Y-%m-%dT%H:%M:%SZ") if finished else None,
            "transport": self.transport,
            "endpoint": self.endpoint,
            "port": self.port,
            "baud": self.baud,
            "requested_duration_s": self.requested_duration_s,
            "stream_id": self._stream_id,
            "csv_file": csv_file,
            "sensor_config": SENSOR_CONFIG,
            "firmware_counters_first": telemetry["first"] if telemetry else None,
            "firmware_counters_last": telemetry["last"] if telemetry else None,
            "telemetry_errors": telemetry["telemetry_errors"] if telemetry else None,
            "stats": stats,
        }

    def write(self, sample, host_elapsed_s):
        if self._csv_fh is None:
            self._csv_fh = open(self._csv_path(), "x", encoding="utf-8", newline="")
            self._csv_writer = csv.writer(self._csv_fh)
            self._csv_writer.writerow(CSV_HEADER)
            self._stream_id = sample.stream_id
        self._csv_writer.writerow([
            self.session_id, self.label, sample.stream_id, sample.seq,
            sample.device_time_us, f"{host_elapsed_s:.6f}",
            f"{sample.ax_g:.3f}", f"{sample.ay_g:.3f}", f"{sample.az_g:.3f}",
            f"{sample.gx_dps:.3f}", f"{sample.gy_dps:.3f}", f"{sample.gz_dps:.3f}",
            f"{sample.temp_c:.2f}",
        ])
        self._rows_since_flush += 1
        if self._rows_since_flush >= FLUSH_EVERY_ROWS:
            self._csv_fh.flush()
            self._rows_since_flush = 0

    def finalize(self, status, stats, telemetry=None):
        csv_path = None
        if self._csv_fh is not None:
            self._csv_fh.flush()
            self._csv_fh.close()
            csv_path = self._csv_path()
        tmp_path = self._json_path().with_suffix(".json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(self._metadata(status, stats,
                                     csv_file=csv_path.name if csv_path else None,
                                     telemetry=telemetry),
                      handle, indent=2, ensure_ascii=False)
        os.replace(tmp_path, self._json_path())
        return {"csv": csv_path, "json": self._json_path()}
