from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from har.runtime_config import load_runtime_config


def write(folder, text):
    path = Path(folder) / "har_demo.toml"
    path.write_text(text, encoding="utf-8")
    return path


VALID = 'esp = "172.20.10.2:8765"\nrun_dir = "har_runs/own_rf_01"\ndata_dir = "data/har_own"\n'


class RuntimeConfigTests(unittest.TestCase):
    def test_valid_file_gets_defaults_for_host_and_port(self):
        with TemporaryDirectory() as tmp:
            config = load_runtime_config(write(tmp, VALID))
        self.assertEqual(config, {"esp": "172.20.10.2:8765", "run_dir": "har_runs/own_rf_01",
                                  "data_dir": "data/har_own", "host": "0.0.0.0", "port": 8080})

    def test_explicit_host_and_port_are_kept(self):
        with TemporaryDirectory() as tmp:
            config = load_runtime_config(write(tmp, VALID + 'host = "127.0.0.1"\nport = 9000\n'))
        self.assertEqual((config["host"], config["port"]), ("127.0.0.1", 9000))

    def test_missing_file_is_a_clear_error(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "config file not found"):
                load_runtime_config(Path(tmp) / "nope.toml")

    def test_invalid_toml_is_a_clear_error(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "invalid config"):
                load_runtime_config(write(tmp, 'esp = "unterminated\n'))

    def test_unknown_key_is_rejected(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "unknown config key"):
                load_runtime_config(write(tmp, VALID + "pasword = 'x'\n"))

    def test_required_keys_are_checked(self):
        with TemporaryDirectory() as tmp:
            for missing in ("esp", "run_dir", "data_dir"):
                lines = [line for line in VALID.splitlines() if not line.startswith(missing + " ")]
                with self.subTest(missing=missing):
                    with self.assertRaisesRegex(ValueError, f"missing {missing}"):
                        load_runtime_config(write(tmp, "\n".join(lines) + "\n"))

    def test_bad_endpoint_and_port_are_rejected(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "host:port"):
                load_runtime_config(write(tmp, VALID.replace("172.20.10.2:8765", "nohost")))
            with self.assertRaisesRegex(ValueError, "port must be"):
                load_runtime_config(write(tmp, VALID + "port = 70000\n"))
            with self.assertRaisesRegex(ValueError, "port must be"):
                load_runtime_config(write(tmp, VALID + 'port = "8080"\n'))

    def test_token_is_optional_and_checked(self):
        with TemporaryDirectory() as tmp:
            self.assertNotIn("token", load_runtime_config(write(tmp, VALID)))
            config = load_runtime_config(write(tmp, VALID + 'token = "abcdefghijklmnopqrstuv"\n'))
            self.assertEqual(config["token"], "abcdefghijklmnopqrstuv")
            with self.assertRaisesRegex(ValueError, "token must be"):
                load_runtime_config(write(tmp, VALID + 'token = "short"\n'))
