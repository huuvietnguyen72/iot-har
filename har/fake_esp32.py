"""A stand-in for the ESP32 TCP server: streams a collector CSV as DATA,1 lines."""
import csv
import math
from pathlib import Path
import secrets
import select
import socket
import sys
import threading
import time

from .collector_csv import HEADER

SAMPLE_PERIOD_S = 0.02
NET_PERIOD_S = 1.0
SEND_STALL_S = 3.0  # firmware kSendStallMs
IDLE_STREAM_ID = ""  # firmware sends an empty stream id until boot calibration succeeds


def read_csv_fields(csv_path):
    """[(seq, device_time_us, ax, ay, az, gx, gy, gz, temp)] as the original strings."""
    with Path(csv_path).open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        if next(reader, None) != HEADER:
            raise ValueError("unexpected collector CSV header")
        rows = []
        for number, row in enumerate(reader, start=2):
            if not row:
                continue
            if len(row) != len(HEADER):
                raise ValueError(f"row {number} has {len(row)} fields")
            rows.append((row[3], row[4], *row[6:13]))
    if not rows:
        raise ValueError("no data rows")
    return rows


def _net_line(stream_id):
    return f"[NET],1,{stream_id},0,0\n".encode()


class FakeEsp32:
    """One client at a time, like the firmware; a second concurrent client is closed at once."""

    def __init__(self, csv_path=None, *, host="127.0.0.1", port=0, speed=1.0, loop=True,
                 preamble=(), close_after=None, reject_all=False, idle_net_period_s=1.0):
        if not (math.isfinite(speed) and speed > 0):
            raise ValueError("speed must be a positive number")
        self._rows = read_csv_fields(csv_path) if csv_path is not None else None
        self._speed = float(speed)
        self._loop = loop
        self._preamble = tuple(preamble)
        self._close_after = close_after
        self._reject_all = reject_all
        self._idle_net_period_s = idle_net_period_s
        self._stop = threading.Event()
        self._busy = threading.Lock()
        self._lock = threading.Lock()
        self._active = None
        self._serve_thread = None
        self.connections = 0
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(0.1)
        if sys.platform == "win32":
            # SO_REUSEADDR on Windows allows port hijacking; use exclusive bind instead.
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self._sock.bind((host, port))
            self._sock.listen(4)
        except BaseException:
            self._sock.close()
            raise
        self.host, self.port = self._sock.getsockname()[:2]
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass
        with self._lock:
            active = self._active
        if active is not None:
            try:
                active.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                active.close()
            except OSError:
                pass
        deadline = time.monotonic() + 2
        for thread in (self._thread, self._serve_thread):
            if thread is not None and thread.is_alive():
                thread.join(timeout=max(0.0, deadline - time.monotonic()))

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            self.connections += 1
            if self._reject_all or not self._busy.acquire(blocking=False):
                conn.close()
                continue
            self._serve_thread = threading.Thread(target=self._serve, args=(conn,), daemon=True)
            self._serve_thread.start()

    def _serve(self, conn):
        with self._lock:
            self._active = conn
        try:
            conn.settimeout(SEND_STALL_S)
            for line in self._preamble:
                conn.sendall((line + "\n").encode())
            if self._rows is None:
                self._serve_idle(conn)
            else:
                self._serve_rows(conn)
        except (OSError, ValueError):
            pass
        finally:
            with self._lock:
                self._active = None
            self._busy.release()  # before close, so an instant reconnect is accepted
            try:
                conn.close()
            except OSError:
                pass

    def _serve_idle(self, conn):
        next_net = time.monotonic()
        while not self._stop.is_set():
            now = time.monotonic()
            if now >= next_net:
                conn.sendall(_net_line(IDLE_STREAM_ID))
                next_net = now + self._idle_net_period_s
            readable, _, _ = select.select([conn], [], [], max(0.0, min(next_net - now, 0.1)))
            if readable and conn.recv(1024) == b"":
                return  # client closed

    def _serve_rows(self, conn):
        sent = 0
        started = time.monotonic()
        while not self._stop.is_set():
            stream_id = secrets.token_hex(8)
            last_net = None
            for i, fields in enumerate(self._rows):
                if self._close_after is not None and sent >= self._close_after:
                    return
                delay = started + i * SAMPLE_PERIOD_S / self._speed - time.monotonic()
                if delay > 0 and self._stop.wait(delay):
                    return
                if self._stop.is_set():
                    return
                now = time.monotonic()
                if last_net is None or now - last_net >= NET_PERIOD_S:
                    conn.sendall(_net_line(stream_id))
                    last_net = now
                conn.sendall((",".join(("DATA", "1", stream_id, *fields)) + "\n").encode())
                sent += 1
            if not self._loop:
                return
            started += len(self._rows) * SAMPLE_PERIOD_S / self._speed
