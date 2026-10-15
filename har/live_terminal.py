"""`har live`: print one line per prediction from the ESP32 stream."""
import sys
import threading
import time

from .live_pipeline import TICK_S, LivePipeline
from .live_predict import LivePredictor
from .sources import EspSource

NAMES = {"walk": "ĐI BỘ", "sit": "NGỒI", "stand": "ĐỨNG", "lie": "NẰM"}
STATE_MESSAGES = {
    "connecting": "Đang tìm ESP32 ({endpoint})… lần thử {attempt}",
    "calibrating": "ESP32 đang hiệu chỉnh — để yên trên bàn",
    "streaming": "Đã nhận dữ liệu từ ESP32",
    "lost": "Mất kết nối — đang thử lại",
    "busy": "ESP32 đang bận — tắt collector hoặc chương trình khác đang đọc",
    "error": "Lỗi: {message}",
}


class TerminalPrinter:
    def __init__(self, out):
        self._out = out
        self._shown = None
        self._stale = False
        self._restarts = None
        self._reason = None
        self._status = {}
        self.predictions = 0
        self.last_state = None

    def __call__(self, event, data):
        if event == "status":
            self._on_status(data)
        elif event == "prediction":
            self._on_prediction(data)

    def _print(self, text):
        print(text, file=self._out, flush=True)

    def _on_status(self, s):
        self._status = s
        state = s.get("state")
        self.last_state = state
        key = (state, s.get("attempt"))
        if state in STATE_MESSAGES and key != self._shown:
            self._shown = key
            self._print(STATE_MESSAGES[state].format(
                endpoint=s.get("endpoint") or "?", attempt=s.get("attempt"),
                message=s.get("message") or ""))
        message = s.get("message")
        if state == "streaming":
            self._reason = None
        elif state in ("connecting", "lost", "busy") and message and message != self._reason:
            self._reason = message
            self._print(f"  (lý do: {message})")
        stale = bool(s.get("stale"))
        if stale and not self._stale:
            self._print("Mất tín hiệu")
        elif self._stale and not stale and state == "streaming":
            self._print("Có tín hiệu lại")
        self._stale = stale
        restarts = s.get("restarts", 0)
        if self._restarts is not None and restarts > self._restarts:
            self._print("ESP32 vừa khởi động lại")
        self._restarts = restarts

    def _on_prediction(self, p):
        self.predictions += 1
        stamp = time.strftime("%H:%M:%S", time.localtime(p["time"]))
        name = NAMES.get(p["label"], p["label"])
        line = (f"{stamp}  {name:<6} {max(p['probabilities']) * 100:3.0f}%"
                f"   (thô: {p['raw_label']} {max(p['raw_probabilities']):.2f})"
                f"   {self._status.get('rate_hz', 0.0):.1f} Hz  mất {self._status.get('missing', 0)} mẫu")
        if p["uncertain"]:
            line += "  (không chắc)"
        self._print(line)


def run_live(run_dir, host, port, *, out=None, max_predictions=None, source=None):
    """Run until Ctrl+C (or max_predictions, used by tests). Model errors raise first.

    Returns 0 on a normal stop, 1 if the source ended on its own or reported "error".
    """
    out = out or sys.stdout
    printer = TerminalPrinter(out)
    pipeline = LivePipeline(LivePredictor(run_dir), printer)
    source = source or EspSource(host, port)
    stop = threading.Event()
    thread = threading.Thread(target=source.run, args=(pipeline, stop), daemon=True)
    thread.start()
    requested_stop = False
    try:
        while thread.is_alive():
            time.sleep(TICK_S)
            pipeline.tick()
            if max_predictions is not None and printer.predictions >= max_predictions:
                requested_stop = True
                break
    except KeyboardInterrupt:
        requested_stop = True
    finally:
        stop.set()
        try:
            thread.join(timeout=5)
        except KeyboardInterrupt:
            pass
    if printer.last_state == "error" or not requested_stop:
        return 1
    return 0
