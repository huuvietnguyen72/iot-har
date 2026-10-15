import socket
import threading
import unittest

from collector.tcp_transport import ConnectionLost, TcpTransport


class ServerThread:
    def __init__(self, handler):
        self._handler = handler
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(1)
        self.port = self._sock.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        try:
            conn, _ = self._sock.accept()
        except OSError:
            return
        try:
            self._handler(conn)
        finally:
            try:
                conn.close()
            except OSError:
                pass
            self._sock.close()

    def join(self):
        self._thread.join(timeout=5)


class TcpTransportTests(unittest.TestCase):
    def test_endpoint_reports_host_and_port(self):
        t = TcpTransport("127.0.0.1", 8765)
        self.assertEqual(t.endpoint, "127.0.0.1:8765")

    def test_reads_multiple_lines_from_one_chunk(self):
        payload = b"DATA,one\nDATA,two\nDATA,three\n"
        server = ServerThread(lambda conn: conn.sendall(payload))
        transport = TcpTransport("127.0.0.1", server.port, read_timeout=0.2)
        transport.open()
        received = b""
        while len(received) < len(payload):
            received += transport.read(256)
        self.assertEqual(received, payload)
        transport.close()
        server.join()

    def test_read_timeout_returns_empty_not_eof(self):
        def handler(conn):
            conn.recv(1)
        server = ServerThread(handler)
        transport = TcpTransport("127.0.0.1", server.port, read_timeout=0.1)
        transport.open()
        self.assertEqual(transport.read(256), b"")
        self.assertEqual(transport.read(256), b"")
        transport.close()
        server.join()

    def test_fragmented_payload_is_reassembled_across_reads(self):
        import time

        def handler(conn):
            conn.sendall(b"DATA,part")
            time.sleep(0.05)
            conn.sendall(b"ial\n")

        server = ServerThread(handler)
        transport = TcpTransport("127.0.0.1", server.port, read_timeout=0.2)
        transport.open()
        received = b""
        while len(received) < len(b"DATA,partial\n"):
            received += transport.read(256)
        self.assertEqual(received, b"DATA,partial\n")
        transport.close()
        server.join()

    def test_peer_close_raises_connection_lost(self):
        server = ServerThread(lambda conn: None)
        transport = TcpTransport("127.0.0.1", server.port, read_timeout=0.2)
        transport.open()
        with self.assertRaises(ConnectionLost):
            for _ in range(50):
                transport.read(256)
        transport.close()
        server.join()

    def test_read_before_open_raises_connection_lost(self):
        transport = TcpTransport("127.0.0.1", 1)
        with self.assertRaises(ConnectionLost):
            transport.read(16)


if __name__ == "__main__":
    unittest.main()
