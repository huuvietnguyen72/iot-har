import unittest

from collector.discovery import DiscoveryError, _select


class SelectTests(unittest.TestCase):
    def test_single_result_returns_host_and_port(self):
        self.assertEqual(_select([("esp.local.", "10.0.0.5", 8765)]),
                         ("10.0.0.5", 8765))

    def test_empty_results_raise(self):
        with self.assertRaises(DiscoveryError):
            _select([])

    def test_multiple_results_raise(self):
        with self.assertRaises(DiscoveryError):
            _select([("a.local.", "1.1.1.1", 1), ("b.local.", "2.2.2.2", 2)])


if __name__ == "__main__":
    unittest.main()
