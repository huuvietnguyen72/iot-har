"""Settings for `har demo` and `har live`: TOML file first, command-line values override it, then checks."""
from pathlib import Path
import tomllib

from .sources import parse_endpoint

REQUIRED = ("esp", "run_dir", "data_dir")
OPTIONAL = {"host": "0.0.0.0", "port": 8080}
OPTIONAL_NOT_DEFAULTED = ("token",)
KNOWN = set(REQUIRED) | set(OPTIONAL) | set(OPTIONAL_NOT_DEFAULTED)


def _read_file(path):
    try:
        with Path(path).open("rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        raise ValueError(f"config file not found: {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid config {path}: {exc}") from None
    unknown = sorted(set(data) - KNOWN)
    if unknown:
        raise ValueError(f"unknown config key in {path}: {', '.join(unknown)}")
    return data


def load_runtime_config(path=None, *, overrides=None, required=REQUIRED):
    """Merge file, then overrides (None means not given), then check. Returns only the keys in use."""
    config = dict(OPTIONAL)
    if path is not None:
        config.update(_read_file(path))
    config.update({key: value for key, value in (overrides or {}).items() if value is not None})
    for key in required:
        if key not in config:
            raise ValueError(f"missing {key}")
    for key in ("esp", "run_dir", "data_dir"):
        if key in config and not isinstance(config[key], str):
            raise ValueError(f"{key} must be a string")
    if "esp" in config:
        parse_endpoint(config["esp"])
    port = config.get("port", OPTIONAL["port"])
    if isinstance(port, bool) or not isinstance(port, int) or not 0 < port < 65536:
        raise ValueError("port must be an integer from 1 to 65535")
    token = config.get("token")
    if token is not None and (not isinstance(token, str) or len(token) < 16):
        raise ValueError("token must be a string of at least 16 characters (see: python -m har new-token)")
    return {key: config[key] for key in (*REQUIRED, "host", "port", *OPTIONAL_NOT_DEFAULTED) if key in config}
