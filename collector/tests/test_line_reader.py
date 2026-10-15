import unittest

from collector.line_reader import SerialLineReader
from collector.tests.fakes import FakeSerial


class LineReaderTests(unittest.TestCase):
    def test_fragmented_line_is_reassembled(self):
        reader = SerialLineReader(FakeSerial([b"DA", b"TA OK\n"]))
        self.assertEqual(reader.poll(), [])
        self.assertEqual(reader.poll(), ["DATA OK"])

    def test_multiple_lines_in_one_chunk(self):
        reader = SerialLineReader(FakeSerial([b"A\nB\nC\n"]))
        self.assertEqual(reader.poll(), ["A", "B", "C"])

    def test_empty_read_returns_no_lines(self):
        reader = SerialLineReader(FakeSerial([]))
        self.assertEqual(reader.poll(), [])

    def test_carriage_return_is_stripped(self):
        reader = SerialLineReader(FakeSerial([b"AB\r\n"]))
        self.assertEqual(reader.poll(), ["AB"])

    def test_line_at_exact_limit_is_kept(self):
        reader = SerialLineReader(FakeSerial([b"X" * 512 + b"\n"]), max_line_bytes=512)
        self.assertEqual(reader.poll(), ["X" * 512])
        self.assertEqual(reader.oversize_lines, 0)

    def test_oversized_line_is_skipped_to_newline(self):
        reader = SerialLineReader(FakeSerial([b"X" * 513 + b"\nDATA,1,ok\n"]),
                                  max_line_bytes=512)
        self.assertEqual(reader.poll(), ["DATA,1,ok"])
        self.assertEqual(reader.oversize_lines, 1)

    def test_split_oversized_line_counts_once(self):
        reader = SerialLineReader(FakeSerial([b"Y" * 300, b"Y" * 300 + b"\nA\n"]),
                                  max_line_bytes=512)
        self.assertEqual(reader.poll(), [])
        self.assertEqual(reader.poll(), ["A"])
        self.assertEqual(reader.oversize_lines, 1)

    def test_invalid_utf8_does_not_raise(self):
        reader = SerialLineReader(FakeSerial([b"\xff\xfe\n"]))
        self.assertEqual(len(reader.poll()), 1)


if __name__ == "__main__":
    unittest.main()
