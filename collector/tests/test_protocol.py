import unittest

from collector.protocol import ParseError, Sample, parse_line

VALID = "DATA,1,7a31b25c809fd416,12,8340000,-0.921,0.051,0.132,0.120,-0.080,0.050,29.40"

FIELD_INDEX = {"version": 1, "stream_id": 2, "seq": 3, "time": 4, "ax": 5,
               "ay": 6, "az": 7, "gx": 8, "gy": 9, "gz": 10, "temp": 11}


def record(**changes):
    fields = VALID.split(",")
    for name, value in changes.items():
        fields[FIELD_INDEX[name]] = str(value)
    return ",".join(fields)


class ParseLineTests(unittest.TestCase):
    def test_valid_record_parses_all_fields(self):
        sample = parse_line(VALID)
        self.assertEqual(sample, Sample(
            stream_id="7a31b25c809fd416", seq=12, device_time_us=8340000,
            ax_g=-0.921, ay_g=0.051, az_g=0.132,
            gx_dps=0.120, gy_dps=-0.080, gz_dps=0.050, temp_c=29.40))

    def test_trailing_carriage_return_ignored(self):
        self.assertEqual(parse_line(VALID + "\r"), parse_line(VALID))

    def test_log_line_is_ignored(self):
        self.assertIsNone(parse_line("[CAL] DONE bias=(15.6,4.5,0.5) dps"))

    def test_empty_line_is_ignored(self):
        self.assertIsNone(parse_line(""))

    def test_wrong_version_is_error(self):
        with self.assertRaises(ParseError):
            parse_line(record(version=2))

    def test_wrong_field_count_is_error(self):
        with self.assertRaises(ParseError):
            parse_line(",".join(VALID.split(",")[:-1]))

    def test_non_numeric_value_is_error(self):
        with self.assertRaises(ParseError):
            parse_line(record(ax="abc"))

    def test_nan_and_inf_are_errors(self):
        for bad in ("nan", "inf", "-inf"):
            with self.assertRaises(ParseError):
                parse_line(record(temp=bad))

    def test_negative_seq_is_error(self):
        with self.assertRaises(ParseError):
            parse_line(record(seq="-1"))

    def test_short_stream_id_is_error(self):
        with self.assertRaises(ParseError):
            parse_line(record(stream_id="7a31b25c"))

    def test_firmware_golden_record_parses(self):
        record_line = ("DATA,1,7a31b25c809fd416,12,8340000,0.500,-0.250,1.000,"
                       "0.125,-0.125,0.000,29.50")
        self.assertEqual(parse_line(record_line), Sample(
            stream_id="7a31b25c809fd416", seq=12, device_time_us=8340000,
            ax_g=0.5, ay_g=-0.25, az_g=1.0,
            gx_dps=0.125, gy_dps=-0.125, gz_dps=0.0, temp_c=29.5))

    def test_non_ascii_digit_seq_is_error(self):
        with self.assertRaises(ParseError):
            parse_line(record(seq="\u00b2"))


if __name__ == "__main__":
    unittest.main()
