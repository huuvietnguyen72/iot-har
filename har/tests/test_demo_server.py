from tempfile import TemporaryDirectory
import http.client
import json
import threading
import time
import unittest

from har.config import LABELS
from har.demo_server import Broadcaster, DemoApp, make_server
from har.live_predict import LivePredictor
from har.sources import ReplaySource
from har.tests.fixtures import write_own_dataset
from har.tests.test_inference import build_run


class IdleSource:
    def run(self, sink, stop):
        sink.status(state="connecting", attempt=1, endpoint="test:1")
        stop.wait()


def next_event(response, wanted):
    event = None
    while True:
        line = response.readline().decode("utf-8")
        if not line:
            raise AssertionError(f"stream closed before {wanted}")
        line = line.rstrip("\n")
        if line.startswith("event: "):
            event = line[len("event: "):]
        elif line.startswith("data: ") and event == wanted:
            return json.loads(line[len("data: "):])


class DemoServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = TemporaryDirectory()
        cls.run_dir = build_run(cls._tmp.name)
        write_own_dataset(cls._tmp.name, train_sessions=1, test_sessions=1)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self.app = DemoApp(LivePredictor(self.run_dir), self._tmp.name, "127.0.0.1", 1,
                           live_factory=IdleSource,
                           replay_factory=lambda paths, speed: ReplaySource(paths, speed,
                                                                            sleep=lambda s: None))
        self.app.start()
        self.server = make_server(self.app, "127.0.0.1", 0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.app.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            headers = {"Content-Type": "application/json"} if body is not None else {}
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            return response.status, response.getheader("Content-Type"), response.read()
        finally:
            conn.close()

    def test_index_page(self):
        status, content_type, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertTrue(content_type.startswith("text/html"))
        self.assertIn("<title>".encode(), body)
        with self.assertRaises(OSError):
            make_server(self.app, "127.0.0.1", self.port).server_close()

    def test_sessions_endpoint(self):
        status, _, body = self.request("GET", "/api/sessions")
        sessions = json.loads(body)["sessions"]
        self.assertEqual(status, 200)
        self.assertEqual(len(sessions), 8)
        self.assertEqual(set(sessions[0]), {"session_id", "split", "label", "started_utc"})
        self.assertEqual(sessions[0]["split"], "test")

    def test_bad_requests(self):
        cases = [("POST", "/api/mode", b"{"), ("POST", "/api/mode", b"[]"),
                 ("POST", "/api/mode", b'{"mode":"x"}'),
                 ("POST", "/api/mode", b'{"mode":"replay","sessions":["nope"],"speed":1}'),
                 ("POST", "/api/mode", b'{"mode":"replay","sessions":["test-walk-0"],"speed":3}'),
                 ("POST", "/api/mode", b'{"mode":"replay","sessions":["test-walk-0"],"speed":true}'),
                 ("POST", "/api/mode", b'{"mode":"replay","sessions":[],"speed":1}'),
                 ("POST", "/api/mode", b"[" * 5000)]
        for method, path, body in cases:
            status, _, payload = self.request(method, path, body)
            self.assertEqual(status, 400, body)
            self.assertIn("error", json.loads(payload))
        self.assertEqual(self.request("GET", "/nope")[0], 404)
        self.assertEqual(self.request("POST", "/nope", b"{}")[0], 404)
        self.assertEqual(self.app.pipeline.snapshot()["status"]["mode"], "live")

    def test_events_snapshot_then_replay_predictions(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("GET", "/events")
            response = conn.getresponse()
            self.assertEqual(response.getheader("Content-Type"), "text/event-stream")
            snapshot = next_event(response, "snapshot")
            self.assertEqual(snapshot["status"]["mode"], "live")
            self.assertEqual(snapshot["labels"], sorted(LABELS))
            status, _, body = self.request(
                "POST", "/api/mode", b'{"mode":"replay","sessions":["test-walk-0"],"speed":4}')
            self.assertEqual((status, json.loads(body)["mode"]), (200, "replay"))
            prediction = next_event(response, "prediction")
            self.assertEqual(prediction["true_label"], "walk")
            self.assertIn(prediction["raw_label"], LABELS)
            self.assertEqual(prediction["index"], 0)
        finally:
            conn.close()

    def test_switching_back_to_live(self):
        self.request("POST", "/api/mode", b'{"mode":"replay","sessions":["test-sit-0"],"speed":1}')
        status, _, body = self.request("POST", "/api/mode", b'{"mode":"live"}')
        self.assertEqual((status, json.loads(body)), (200, {"mode": "live", "sessions": []}))
        self.assertEqual(self.app.pipeline.snapshot()["status"]["mode"], "live")
        # the ticker must survive an exception raised by tick()
        original = self.app.pipeline.tick
        calls = []

        def flaky():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("boom")
            original()

        self.app.pipeline.tick = flaky
        time.sleep(0.8)
        self.assertTrue(self.app._ticker.is_alive())
        self.assertGreaterEqual(len(calls), 2)
        self.app.close()
        worker = self.app._worker
        with self.assertRaises(RuntimeError):
            self.app.set_mode({"mode": "live"})
        self.assertIs(self.app._worker, worker)


class BroadcasterTests(unittest.TestCase):
    def test_full_queue_drops_slow_client(self):
        broadcaster = Broadcaster(queue_size=2)
        q = broadcaster.subscribe()
        for i in range(3):
            broadcaster.publish("status", {"i": i})
        self.assertFalse(broadcaster.is_subscribed(q))
        self.assertTrue(q.get_nowait().startswith("event: status\ndata: "))
        live = broadcaster.subscribe()
        broadcaster.close()
        self.assertIsNone(live.get_nowait())
