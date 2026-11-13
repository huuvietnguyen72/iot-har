from tempfile import TemporaryDirectory
import contextlib
import http.client
import io
import json
import threading
import unittest

from har.demo_server import DemoApp, make_server, run_demo
from har.live_predict import LivePredictor
from har.sources import ReplaySource
from har.tests.fixtures import write_own_dataset
from har.tests.test_inference import build_run

TOKEN = "t0k3n-for-tests-only-123"


class IdleSource:
    def run(self, sink, stop):
        sink.status(state="connecting", attempt=1, endpoint="test:1")
        stop.wait()


class SecureServerTests(unittest.TestCase):
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
                                                                            sleep=lambda s: None),
                           token=TOKEN)
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

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def test_page_needs_token(self):
        self.assertEqual(self.request("GET", "/")[0], 401)
        self.assertEqual(self.request("GET", "/api/sessions")[0], 401)
        self.assertEqual(self.request("GET", "/", headers={"Authorization": "Bearer wrong"})[0], 401)

    def test_bearer_header_and_cookie_are_accepted(self):
        status, _, _ = self.request("GET", "/", headers={"Authorization": f"Bearer {TOKEN}"})
        self.assertEqual(status, 200)
        status, _, _ = self.request("GET", "/api/sessions", headers={"Cookie": f"har_token={TOKEN}"})
        self.assertEqual(status, 200)

    def test_query_token_sets_cookie_for_later_requests(self):
        status, headers, _ = self.request("GET", f"/?token={TOKEN}")
        self.assertEqual(status, 200)
        cookie = headers["Set-Cookie"]
        self.assertIn(f"har_token={TOKEN}", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)

    def test_mode_change_needs_token_and_leaves_mode_alone(self):
        body = b'{"mode":"replay","sessions":["test-walk-0"],"speed":4}'
        self.assertEqual(self.request("POST", "/api/mode", body)[0], 401)
        self.assertEqual(self.app.pipeline.snapshot()["status"]["mode"], "live")

    def test_health_reports_connecting_as_not_ok(self):
        status, _, body = self.request("GET", "/health", headers={"Authorization": f"Bearer {TOKEN}"})
        data = json.loads(body)
        self.assertEqual(status, 503)
        self.assertFalse(data["ok"])
        self.assertEqual((data["mode"], data["state"], data["endpoint"]), ("live", "connecting", "test:1"))
        for key in ("rate_hz", "missing", "restarts", "parse_errors", "stale", "predict_p95_ms"):
            self.assertIn(key, data)

    def test_health_needs_token_too(self):
        self.assertEqual(self.request("GET", "/health")[0], 401)


class RunDemoSafetyTests(unittest.TestCase):
    def test_listening_beyond_localhost_without_token_is_refused(self):
        with TemporaryDirectory() as tmp:
            run = build_run(tmp)
            write_own_dataset(tmp, train_sessions=1, test_sessions=1)
            with self.assertRaisesRegex(ValueError, "token"):
                with contextlib.redirect_stdout(io.StringIO()):
                    run_demo(run, "127.0.0.1:1", tmp, "0.0.0.0", 0)

    def test_localhost_without_token_is_allowed_to_start(self):
        with TemporaryDirectory() as tmp:
            run = build_run(tmp)
            write_own_dataset(tmp, train_sessions=1, test_sessions=1)
            out = io.StringIO()
            done = threading.Event()

            def interrupt():
                done.wait(0.5)
                import _thread
                _thread.interrupt_main()

            threading.Thread(target=interrupt, daemon=True).start()
            code = run_demo(run, "127.0.0.1:1", tmp, "127.0.0.1", 0, out=out)
            done.set()
        self.assertEqual(code, 0)
        self.assertIn("http://127.0.0.1:", out.getvalue())
