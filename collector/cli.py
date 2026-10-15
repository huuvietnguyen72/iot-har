"""Command line entry for the MPU6050 collector (USB serial or Wi-Fi TCP)."""
from __future__ import annotations

import argparse
import math
import os
import sys
import time
from pathlib import Path

from .collect import collect
from .session import LABEL_RE
from .tcp_transport import TcpTransport

EXIT_CODES = {
    "completed": 0,
    "interrupted": 130,
    "wait_timeout": 3,
    "no_data": 3,
    "stream_changed": 4,
    "serial_error": 5,
    "connection_lost": 5,
}

QUALITY_KEYS = ("data_errors", "missing_by_seq", "duplicates", "out_of_order",
                "timestamp_errors", "gaps_over_40ms")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="collector",
        description="Record MPU6050 DATA records over USB serial or Wi-Fi TCP to CSV.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--port", help="serial port, e.g. /dev/ttyUSB0")
    group.add_argument("--tcp", help="ESP32 TCP endpoint host:port")
    group.add_argument("--discover", action="store_true",
                       help="find the ESP32 via mDNS on the local network")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--duration", type=float, default=60.0,
                        help="recording seconds after the first valid sample")
    parser.add_argument("--label", default="test", help="session label, e.g. test/walk/sit")
    parser.add_argument("--output", default="data", help="output directory")
    args = parser.parse_args(argv)
    if args.tcp is not None:
        try:
            parse_endpoint(args.tcp)
        except ValueError:
            parser.error("--tcp must be host:port")
    if not math.isfinite(args.duration) or args.duration <= 0:
        parser.error("--duration must be a finite positive number")
    if not LABEL_RE.match(args.label):
        parser.error("--label must match [A-Za-z0-9_-]{1,32}")
    return args


def parse_endpoint(value):
    host, sep, port = value.rpartition(":")
    if not sep or not host or not port.isdigit():
        raise ValueError(value)
    return host, int(port)


def open_serial(port, baud):
    try:
        import serial
    except ImportError as exc:
        raise OSError("pyserial is not installed (sudo apt install python3-serial)") from exc
    if os.name == "posix":
        stream = serial.Serial(port, baud, timeout=0.05, exclusive=True)
    else:
        stream = serial.Serial(port, baud, timeout=0.05)
    stream.dtr = False
    stream.rts = False
    return stream


def open_tcp(host, port):
    transport = TcpTransport(host, port)
    transport.open()
    return transport


def format_progress(elapsed_s, stats):
    phase = "waiting" if stats["samples_written"] == 0 else "recording"
    sys.stdout.write("\r%-9s %6.1fs samples=%d errors=%d rate=%.1f Hz"
                     % (phase, elapsed_s, stats["samples_written"], stats["data_errors"],
                        stats["sample_rate_hz"]))
    sys.stdout.flush()


def show_status(line):
    sys.stdout.write("\r" + line + "\n")
    sys.stdout.flush()


def _open_transport(args, *, open_serial_fn, open_tcp_fn, discover_fn):
    if args.tcp:
        host, port = parse_endpoint(args.tcp)
        return open_tcp_fn(host, port), "tcp", f"{host}:{port}", None, None
    if args.discover:
        if discover_fn is None:
            from .discovery import discover_one
            discover_fn = discover_one
        host, port = discover_fn()
        return open_tcp_fn(host, port), "tcp", f"{host}:{port}", None, None
    return open_serial_fn(args.port, args.baud), "serial", None, args.port, args.baud


def main(argv=None, *, open_serial_fn=open_serial, open_tcp_fn=open_tcp,
         discover_fn=None, clock=time.monotonic):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    args = parse_args(argv)
    try:
        stream, transport_kind, endpoint, port, baud = _open_transport(
            args, open_serial_fn=open_serial_fn, open_tcp_fn=open_tcp_fn,
            discover_fn=discover_fn)
    except ValueError:
        print("error: --tcp must be host:port", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: cannot open transport: {exc}", file=sys.stderr)
        return 5
    print("waiting for valid DATA records; keep the sensor still until calibration completes")
    try:
        result = collect(stream, output_dir=Path(args.output), label=args.label,
                         port=port, baud=baud, duration_s=args.duration,
                         clock=clock, progress=format_progress, status_sink=show_status,
                         transport_kind=transport_kind, endpoint=endpoint)
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 6
    finally:
        try:
            stream.close()
        except OSError:
            pass
    print()
    print(f"status={result.status} samples={result.stats['samples_written']} "
          f"rate={result.stats['sample_rate_hz']} Hz "
          f"errors={result.stats['data_errors']} missing={result.stats['missing_by_seq']}")
    print(f"json: {result.json_path}")
    if result.csv_path is not None:
        print(f"csv:  {result.csv_path}")
    if result.status == "completed":
        if any(result.stats.get(key, 0) for key in QUALITY_KEYS):
            print("warning: quality issues detected; review JSON stats", file=sys.stderr)
        return 0
    print(f"error: recording ended with status {result.status}", file=sys.stderr)
    return EXIT_CODES.get(result.status, 1)
