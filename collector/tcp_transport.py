"""TCP transport that behaves like the serial stream used by the collector."""
from __future__ import annotations

import socket


class ConnectionLost(OSError):
    """The peer closed, reset, or dropped the TCP connection."""


class TcpTransport:
    def __init__(self, host, port, connect_timeout=5.0, read_timeout=0.05):
        self.host = host
        self.port = int(port)
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._sock = None

    @property
    def endpoint(self):
        return f"{self.host}:{self.port}"

    def open(self):
        self._sock = socket.create_connection((self.host, self.port),
                                              timeout=self._connect_timeout)
        self._sock.settimeout(self._read_timeout)

    def read(self, size):
        if self._sock is None:
            raise ConnectionLost("transport is not open")
        try:
            data = self._sock.recv(size)
        except socket.timeout:
            return b""
        except OSError as exc:
            raise ConnectionLost(str(exc)) from exc
        if data == b"":
            raise ConnectionLost("peer closed the connection")
        return data

    def close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
