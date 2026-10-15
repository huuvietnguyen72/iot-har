"""HTTP + Server-Sent Events server for the live/replay demo (standard library only)."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time
import traceback

from .live_pipeline import TICK_S, LivePipeline
from .live_predict import LivePredictor
from .sources import REPLAY_SPEEDS, EspSource, ReplaySource, list_replay_sessions, parse_endpoint

STATIC_DIR = Path(__file__).with_name("demo_static")
QUEUE_SIZE = 1000
KEEPALIVE_S = 15
MAX_BODY_BYTES = 10_000
SSE_SOCKET_TIMEOUT_S = 30
TICK_ERROR_LOG_EVERY_S = 10
PUBLIC_SESSION_KEYS = ("session_id", "split", "label", "started_utc")


def sse_message(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, allow_nan=False)}\n\n"


class Broadcaster:
    """Fan events out to SSE clients; a client whose queue is full is dropped."""

    def __init__(self, queue_size=QUEUE_SIZE):
        self._lock = threading.Lock()
        self._queues = set()
        self._queue_size = queue_size

    def subscribe(self):
        q = queue.Queue(maxsize=self._queue_size)
        with self._lock:
            self._queues.add(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            self._queues.discard(q)

    def is_subscribed(self, q):
        with self._lock:
            return q in self._queues

    def publish(self, event, data):
        # Never blocks (put_nowait): the pipeline calls this while holding its lock.
        message = sse_message(event, data)
        with self._lock:
            for q in list(self._queues):
                try:
                    q.put_nowait(message)
                except queue.Full:
                    self._queues.discard(q)

    def close(self):
        with self._lock:
            for q in self._queues:
                try:
                    q.put_nowait(None)
                except queue.Full:
                    pass
            self._queues.clear()


class _Gate:
    """Forward a source's calls to the pipeline only until its stop event is set.

    This is what guarantees a source that outlives the join timeout in _stop_worker
    (e.g. stuck in a blocking socket call) can never feed the pipeline together with its
    replacement: once stop is set, its calls are dropped.
    """

    def __init__(self, pipeline, stop):
        self._pipeline = pipeline
        self._stop = stop

    def sample(self, s):
        if not self._stop.is_set():
            self._pipeline.sample(s)

    def status(self, **fields):
        if not self._stop.is_set():
            self._pipeline.status(**fields)


class DemoApp:
    def __init__(self, predictor, data_dir, esp_host, esp_port, *, live_factory=None,
                 replay_factory=None):
        self.broadcaster = Broadcaster()
        self.pipeline = LivePipeline(predictor, self.broadcaster.publish)
        self._data_dir = Path(data_dir)
        self._live_factory = live_factory or (lambda: EspSource(esp_host, esp_port))
        self._replay_factory = replay_factory or (lambda paths, speed: ReplaySource(paths, speed))
        self._mode_lock = threading.Lock()
        self._worker = None
        self._worker_stop = None
        self._closed = threading.Event()
        self._ticker = threading.Thread(target=self._tick_loop, daemon=True)

    @property
    def closed(self):
        return self._closed.is_set()

    def start(self):
        self._ticker.start()
        self.set_mode({"mode": "live"})
        return self

    def sessions(self):
        return list_replay_sessions(self._data_dir)

    def _parse_mode(self, payload):
        """Validate a /api/mode body -> (mode, ids, speed, make_source); ValueError if bad."""
        if not isinstance(payload, dict):
            raise ValueError("body must be a JSON object")
        mode = payload.get("mode")
        if mode == "live":
            return mode, [], None, self._live_factory
        if mode != "replay":
            raise ValueError("mode must be 'live' or 'replay'")
        ids = payload.get("sessions")
        speed = payload.get("speed", 1)
        if isinstance(speed, bool) or speed not in REPLAY_SPEEDS:
            raise ValueError("speed must be 1, 2 or 4")
        if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
            raise ValueError("sessions must be a non-empty list of session ids")
        known = {s["session_id"]: s for s in self.sessions()}
        unknown = [i for i in ids if i not in known]
        if unknown:
            raise ValueError(f"unknown session id: {unknown[0]}")
        paths = [known[i]["csv"] for i in ids]
        return mode, ids, speed, lambda: self._replay_factory(paths, speed)

    def set_mode(self, payload):
        """Validate a /api/mode body and switch sources; ValueError for bad input."""
        mode, ids, speed, make_source = self._parse_mode(payload)
        with self._mode_lock:
            if self._closed.is_set():
                raise RuntimeError("demo is shutting down")
            # Build the new source first: if the factory fails, the old one keeps running.
            source = make_source()
            # If the old worker ignores stop past the join timeout, its _Gate still drops
            # everything it sends, so only the new source feeds the pipeline.
            self._stop_worker()
            self.pipeline.start(mode, ids, speed)
            stop = threading.Event()
            self._worker_stop = stop
            self._worker = threading.Thread(target=self._run_source, args=(source, stop), daemon=True)
            self._worker.start()
        return {"mode": mode, "sessions": ids}

    def close(self):
        self._closed.set()
        with self._mode_lock:
            self._stop_worker()
        self.broadcaster.close()

    def _run_source(self, source, stop):
        gate = _Gate(self.pipeline, stop)
        try:
            source.run(gate, stop)
        except Exception as exc:  # keep the server alive and show the failure on the page
            gate.status(state="error", message=f"{type(exc).__name__}: {exc}")

    def _stop_worker(self):
        if self._worker is not None:
            self._worker_stop.set()
            self._worker.join(timeout=5)
            self._worker = None

    def _tick_loop(self):
        last_logged = None
        while not self._closed.wait(TICK_S):
            try:
                self.pipeline.tick()
            except Exception as exc:  # the ticker must never die: the page relies on it
                now = time.monotonic()
                if last_logged is None or now - last_logged >= TICK_ERROR_LOG_EVERY_S:
                    last_logged = now
                    where = traceback.extract_tb(exc.__traceback__)[-1]
                    print(f"demo: ticker error {type(exc).__name__}: {exc} "
                          f"({Path(where.filename).name}:{where.lineno})", file=sys.stderr, flush=True)


def make_handler(app):
    page = (STATIC_DIR / "index.html").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        server_version = "HARDemo/1"
        timeout = 10  # bounds body reads; _events replaces it with its own write timeout

        def log_message(self, format, *args):  # keep the console for status lines
            pass

        def _send(self, status, body, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status, data):
            try:
                self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                           "application/json; charset=utf-8")
            except OSError:  # the client has already gone
                pass

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/":
                self._send(200, page, "text/html; charset=utf-8")
            elif path == "/api/sessions":
                sessions = [{k: s[k] for k in PUBLIC_SESSION_KEYS} for s in app.sessions()]
                self._json(200, {"sessions": sessions})
            elif path == "/events":
                self._events()
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):
            if self.path.split("?", 1)[0] != "/api/mode":
                self._json(404, {"error": "not found"})
                return
            try:
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    raise ValueError("invalid Content-Length") from None
                if length < 0:
                    raise ValueError("invalid Content-Length")
                if length > MAX_BODY_BYTES:
                    raise ValueError("request body too large")
                result = app.set_mode(json.loads(self.rfile.read(length) or b"null"))
            except (ValueError, UnicodeDecodeError, RecursionError) as exc:
                self._json(400, {"error": str(exc) or type(exc).__name__})
                return
            except OSError:  # client went away or body read timed out
                return
            except Exception as exc:
                if app.closed:
                    self._json(503, {"error": "demo is shutting down"})
                else:
                    self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
                return
            self._json(200, result)

        def _events(self):
            # A client that stops reading must not pin this thread forever: writes time out
            # (socket.timeout is an OSError) and are treated as a disconnect.
            self.connection.settimeout(SSE_SOCKET_TIMEOUT_S)
            # Subscribe BEFORE taking the snapshot so no event can fall in the gap. Events
            # published between the two are also in the snapshot; the page drops such
            # duplicates by prediction index.
            q = app.broadcaster.subscribe()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                try:
                    first = sse_message("snapshot", app.pipeline.snapshot())
                except ValueError as exc:  # e.g. NaN in the snapshot: do not loop on it
                    print(f"demo: cannot encode snapshot: {exc}", file=sys.stderr, flush=True)
                    return
                self.wfile.write(first.encode("utf-8", errors="replace"))
                self.wfile.flush()
                idle = 0
                while not app.closed:
                    try:
                        message = q.get(timeout=1.0)
                    except queue.Empty:
                        if not app.broadcaster.is_subscribed(q):
                            break
                        idle += 1
                        if idle >= KEEPALIVE_S:
                            idle = 0
                            self.wfile.write(b": keepalive\n\n")
                            self.wfile.flush()
                        continue
                    if message is None:
                        break
                    idle = 0
                    self.wfile.write(message.encode("utf-8", errors="replace"))
                    self.wfile.flush()
            except OSError:  # disconnects and write timeouts
                pass
            finally:
                app.broadcaster.unsubscribe(q)

    return Handler


class _Server(ThreadingHTTPServer):  # daemon_threads is already True here
    # On Windows SO_REUSEADDR lets a second process bind a port that is in use; turn it
    # off so a taken port raises OSError like on Linux.
    allow_reuse_address = os.name != "nt"


def make_server(app, host, port):
    return _Server((host, port), make_handler(app))


def run_demo(run_dir, esp, data_dir, host, port, *, out=None):
    """Validate everything, then serve until Ctrl+C. Errors raise before the port opens."""
    out = out or sys.stdout
    esp_host, esp_port = parse_endpoint(esp)
    if not Path(data_dir).is_dir():
        raise ValueError(f"data directory not found: {data_dir}")
    predictor = LivePredictor(run_dir)
    app = DemoApp(predictor, data_dir, esp_host, esp_port)
    try:
        # Bind first: a port-in-use OSError propagates before any thread is started.
        server = make_server(app, host, port)
    except BaseException:
        app.close()
        raise
    try:
        app.start()
        shown = "<địa-chỉ-máy>" if host in ("0.0.0.0", "") else host
        print(f"demo: http://{shown}:{server.server_address[1]}/  ESP32 {esp_host}:{esp_port}"
              f"  (Ctrl+C để dừng)", file=out, flush=True)
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        app.close()
        server.server_close()
    return 0
