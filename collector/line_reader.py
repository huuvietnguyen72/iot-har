"""Reassemble newline-terminated lines from a byte stream."""
from __future__ import annotations

NEWLINE = 0x0A


class SerialLineReader:
    def __init__(self, stream, max_line_bytes=512, read_size=256):
        self._stream = stream
        self._max = max_line_bytes
        self._read_size = read_size
        self._buffer = bytearray()
        self._skipping = False
        self.oversize_lines = 0

    def poll(self):
        chunk = self._stream.read(self._read_size)
        lines = []
        if not chunk:
            return lines
        for byte in chunk:
            if byte == NEWLINE:
                if self._skipping:
                    self._skipping = False
                else:
                    lines.append(self._buffer.decode("utf-8", errors="replace").rstrip("\r"))
                self._buffer.clear()
                continue
            if self._skipping:
                continue
            self._buffer.append(byte)
            if len(self._buffer) > self._max:
                self._skipping = True
                self._buffer.clear()
                self.oversize_lines += 1
        return lines
