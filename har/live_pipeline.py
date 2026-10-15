"""Join samples, windows, predictions and status into events for the demo and the CLI."""
from collections import deque
import threading
import time

import numpy as np

from .stream_windows import StreamWindower

HISTORY_LIMIT = 2000
PREDICT_TIMES = 200
RATE_WINDOW_S = 5.0
STALE_AFTER_S = 2.0
STATUS_EVERY_S = 1.0
SAMPLE_PERIOD_S = 0.02
TICK_S = 0.2
SAMPLE_BATCH_LIMIT = 1000


class LivePipeline:
    """Thread-safe: sources call sample()/status(), a ticker calls tick() every TICK_S.

    emit(event, data) must not block; it is called while the pipeline lock is held, so a
    blocking emit stalls the source and ticker threads.
    """

    def __init__(self, predictor, emit, *, clock=time.monotonic, wall=time.time):
        self._predictor = predictor
        self._emit = emit
        self._clock = clock
        self._wall = wall
        self._lock = threading.RLock()
        self.labels = list(predictor.labels)
        self.start("live")

    def start(self, mode, sessions=None, speed=None):
        """Forget the previous source and announce the new mode."""
        with self._lock:
            self._windower = StreamWindower()
            self._predictor.reset()
            self._history = deque(maxlen=HISTORY_LIMIT)
            self._latest = None
            self._batch = deque(maxlen=SAMPLE_BATCH_LIMIT)
            self._arrivals = deque()
            self._predict_ms = deque(maxlen=PREDICT_TIMES)
            self._last_sample = None
            self._last_arrival = None
            self._sample_count = 0
            self._index = 0
            self._scored = 0
            self._correct = 0
            self._status = {"mode": mode, "state": "starting", "attempt": 0, "endpoint": None,
                            "message": None, "rate_hz": 0.0, "missing": 0, "parse_errors": 0,
                            "restarts": 0, "predict_p95_ms": None, "session": None,
                            "sessions": list(sessions or []), "speed": speed,
                            "replay_accuracy": None, "collecting": True, "stale": False}
            self._send_status()

    def status(self, **fields):
        with self._lock:
            if "state" in fields and fields["state"] != self._status["state"]:
                self._last_arrival = None
                self._status["stale"] = False
            self._status.update(fields)
            self._send_status()

    def sample(self, s):
        with self._lock:
            now = self._clock()
            last = self._last_sample
            if (last is not None and last.stream_id == s.stream_id and last.session_id == s.session_id
                    and s.seq > last.seq + 1):
                self._status["missing"] += s.seq - last.seq - 1
            if self._status["mode"] == "live" and last is not None and last.stream_id != s.stream_id:
                self._status["restarts"] += 1
            self._last_sample = s
            self._last_arrival = now
            self._arrivals.append(now)
            self._trim_arrivals(now)
            self._sample_count += 1
            self._batch.append([round(self._sample_count * SAMPLE_PERIOD_S, 2), *s.values[:3]])
            new_segment, window = self._windower.push(s)
            if new_segment:
                self._predictor.reset()
                if not self._status["collecting"]:
                    self._status["collecting"] = True
                    self._send_status()
            if window is not None:
                self._predict(window)

    def tick(self):
        with self._lock:
            if self._batch:
                batch = list(self._batch)
                self._batch.clear()
                self._emit("samples", {"samples": batch})
            now = self._clock()
            stale = (self._status["state"] == "streaming" and self._last_arrival is not None
                     and now - self._last_arrival > STALE_AFTER_S)
            if stale != self._status["stale"] or now - self._status_sent >= STATUS_EVERY_S:
                self._status["stale"] = stale
                self._send_status()

    def snapshot(self):
        with self._lock:
            return {"labels": list(self.labels), "status": self._public_status(),
                    "latest": self._latest, "history": list(self._history)}

    def _predict(self, window):
        result = self._predictor.predict(window.window)
        self._predict_ms.append(result["predict_ms"])
        event = dict(result, index=self._index, time=self._wall(),
                     true_label=window.record["label"], session=window.record["session_id"])
        self._index += 1
        if self._status["mode"] == "replay" and event["true_label"] is not None:
            self._scored += 1
            self._correct += int(event["label"] == event["true_label"])
            self._status["replay_accuracy"] = self._correct / self._scored
        self._status["collecting"] = False
        self._status["predict_p95_ms"] = float(np.percentile(self._predict_ms, 95))
        self._history.append(event)
        self._latest = event
        self._emit("prediction", event)

    def _public_status(self):
        now = self._clock()
        self._trim_arrivals(now)
        rate = 0.0
        recent = self._last_arrival is not None and now - self._last_arrival <= STALE_AFTER_S
        if recent and len(self._arrivals) >= 2 and self._arrivals[-1] > self._arrivals[0]:
            rate =(len(self._arrivals) - 1) / (self._arrivals[-1] - self._arrivals[0])
        return dict(self._status, rate_hz=round(rate, 1))

    def _trim_arrivals(self, now):
        while self._arrivals and now - self._arrivals[0] > RATE_WINDOW_S:
            self._arrivals.popleft()

    def _send_status(self):
        self._status_sent = self._clock()
        self._emit("status", self._public_status())
