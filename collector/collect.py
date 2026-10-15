"""Orchestrate one recording: reader, tracker, writer, recorder, finalize."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from .line_reader import SerialLineReader
from .quality import QualityTracker
from .recorder import Recorder
from .session import SessionWriter
from .telemetry import NetTracker


@dataclass(frozen=True)
class CollectResult:
    status: str
    session_id: str
    csv_path: Path | None
    json_path: Path
    stats: dict


def collect(stream, *, output_dir, label, port, baud, duration_s,
            clock=time.monotonic, progress=None, status_sink=None,
            transport_kind="serial", endpoint=None):
    reader = SerialLineReader(stream)
    tracker = QualityTracker()
    net_tracker = NetTracker(clock=clock) if transport_kind == "tcp" else None
    writer = SessionWriter(output_dir=Path(output_dir), label=label, port=port,
                           baud=baud, requested_duration_s=duration_s,
                           transport=transport_kind, endpoint=endpoint)
    recorder = Recorder(reader, tracker, writer.write, clock=clock,
                        progress=progress, status_sink=status_sink,
                        net_tracker=net_tracker)
    try:
        status = recorder.run(duration_s)
    except KeyboardInterrupt:
        status = "interrupted"
    stats = tracker.snapshot()
    telemetry = net_tracker.as_dict() if net_tracker is not None else None
    paths = writer.finalize(status, stats, telemetry=telemetry)
    return CollectResult(status=status, session_id=writer.session_id,
                         csv_path=paths["csv"], json_path=paths["json"], stats=stats)
