from pathlib import Path
import re
import unittest

PAGE = Path(__file__).resolve().parents[1] / "demo_static" / "index.html"
REQUIRED_IDS = ("btn-live", "btn-replay", "status-line", "notice", "replay-panel", "replay-session",
                "replay-speed", "replay-start", "replay-error", "state-icon", "state-name",
                "state-conf", "state-uncertain", "probs", "chart", "history-pred", "true-block",
                "history-true", "accuracy", "accuracy-note")


class DemoPageTests(unittest.TestCase):
    def setUp(self):
        self.html = PAGE.read_text(encoding="utf-8")

    def test_has_required_elements(self):
        for element_id in REQUIRED_IDS:
            self.assertIn(f'id="{element_id}"', self.html, element_id)
        script = re.search(r"<script>(.*)</script>", self.html, re.S).group(1)
        literal_ids = set(re.findall(r'\$\("([^"]+)"\)', script))
        self.assertTrue(literal_ids)
        for element_id in literal_ids:
            self.assertIn(f'id="{element_id}"', self.html, element_id)

    def test_uses_only_local_resources(self):
        self.assertIsNone(re.search(r"https?://", self.html))
        self.assertNotIn("<link", self.html)
        self.assertNotRegex(self.html, r"<script[^>]+src=")

    def test_talks_to_demo_endpoints(self):
        for needle in ('new EventSource("/events")', '"/api/mode"', '"/api/sessions"',
                       '"snapshot"', '"prediction"', '"samples"', '"status"'):
            self.assertIn(needle, self.html)

    def test_vietnamese_labels_and_messages(self):
        for text in ("Đi bộ", "Ngồi", "Đứng", "Nằm", "không chắc", "Đang thu tín hiệu…",
                     "ESP32 đang hiệu chỉnh — để yên trên bàn", "Mất kết nối — đang thử lại",
                     "ESP32 vừa khởi động lại", "Mất tín hiệu",
                     "ESP32 đang bận — tắt collector hoặc chương trình khác đang đọc",
                     "phát lại không bỏ 5 s đầu/cuối như lúc đánh giá nên có thể thấp hơn 0.975"):
            self.assertIn(text, self.html)
