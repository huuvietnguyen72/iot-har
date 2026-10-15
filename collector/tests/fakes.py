class FakeClock:
    def __init__(self, now=0.0):
        self.now = float(now)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeSerial:
    def __init__(self, chunks=None, *, clock=None, read_delay=0.0):
        self.chunks = list(chunks or [])
        self.clock = clock
        self.read_delay = read_delay
        self.reads = 0
        self.error_on_read = None
        self.error_after_reads = 0
        self.closed = False

    def read(self, size):
        if self.error_on_read is not None and self.reads >= self.error_after_reads:
            raise self.error_on_read
        self.reads += 1
        if self.clock is not None and self.read_delay:
            self.clock.advance(self.read_delay)
        if self.chunks:
            return self.chunks.pop(0)
        return b""

    def close(self):
        self.closed = True
