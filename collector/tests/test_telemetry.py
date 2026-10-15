import unittest

from collector.telemetry import NetError, NetSnapshot, NetTracker, parse_net_line


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class ParseNetLineTests(unittest.TestCase):
    def test_valid_net_line_parses(self):
        snapshot = parse_net_line("[NET],1,7a31b25c809fd416,7,12")
        self.assertEqual(snapshot, NetSnapshot("7a31b25c809fd416", 7, 12, 0.0))

    def test_data_line_is_ignored(self):
        self.assertIsNone(parse_net_line(
            "DATA,1,7a31b25c809fd416,12,8340000,0.500,-0.250,1.000,"
            "0.125,-0.125,0.000,29.50"))

    def test_log_line_is_ignored(self):
        self.assertIsNone(parse_net_line("[CAL] DONE bias=(15.6,4.5,0.5) dps"))

    def test_wrong_version_is_error(self):
        with self.assertRaises(NetError):
            parse_net_line("[NET],2,7a31b25c809fd416,0,0")

    def test_short_stream_id_is_error(self):
        with self.assertRaises(NetError):
            parse_net_line("[NET],1,7a31b25c,0,0")

    def test_negative_counter_is_error(self):
        with self.assertRaises(NetError):
            parse_net_line("[NET],1,7a31b25c809fd416,-1,0")

    def test_wrong_field_count_is_error(self):
        with self.assertRaises(NetError):
            parse_net_line("[NET],1,7a31b25c809fd416,0")


class NetTrackerTests(unittest.TestCase):
    def test_first_and_last_snapshot_for_bound_stream(self):
        clock = Clock()
        tracker = NetTracker(clock=clock)
        clock.t = 1.0
        self.assertTrue(tracker.observe("[NET],1,aaaa000000000000,0,0"))
        tracker.bind_stream("aaaa000000000000")
        clock.t = 2.0
        tracker.observe("[NET],1,aaaa000000000000,3,4")
        data = tracker.as_dict()
        self.assertEqual(data["first"]["stream_id"], "aaaa000000000000")
        self.assertEqual(data["first"]["queue_dropped_total"], 0)
        self.assertEqual(data["last"]["queue_dropped_total"], 3)
        self.assertEqual(data["last"]["unobserved_total"], 4)
        self.assertEqual(data["telemetry_errors"], 0)

    def test_snapshot_from_other_stream_is_not_adopted(self):
        gate = Clock()
        tracker = NetTracker(clock=gate)
        tracker.observe("[NET],1,aaaa000000000000,0,0")
        tracker.bind_stream("bbbb000000000000")
        self.assertIsNone(tracker.as_dict()["first"])

    def test_malformed_net_increments_telemetry_errors(self):
        tracker = NetTracker()
        self.assertFalse(tracker.observe("[NET],9,bad,0,0"))
        self.assertEqual(tracker.as_dict()["telemetry_errors"], 1)

    def test_net_after_bind_with_other_stream_is_ignored(self):
        clock = Clock()
        tracker = NetTracker(clock=clock)
        tracker.observe("[NET],1,aaaa000000000000,0,0")
        tracker.bind_stream("aaaa000000000000")
        tracker.observe("[NET],1,aaaa000000000000,1,1")
        self.assertFalse(tracker.observe("[NET],1,bbbb000000000000,5,5"))
        self.assertEqual(tracker.as_dict()["last"]["queue_dropped_total"], 1)


if __name__ == "__main__":
    unittest.main()
