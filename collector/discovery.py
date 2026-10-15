"""Find the ESP32 collector advertised over mDNS (_mpu6050._tcp)."""
from __future__ import annotations

import time

SERVICE_TYPE = "_mpu6050._tcp.local."


class DiscoveryError(OSError):
    """Discovery failed: missing dependency, no device, or several devices."""


def discover(timeout=5.0):
    try:
        from zeroconf import ServiceBrowser, Zeroconf
    except ImportError as exc:
        raise DiscoveryError(
            "zeroconf is not installed (pip install zeroconf or use --tcp host:port)") from exc

    found = []

    class Listener:
        def add_service(self, zc, type_, name):
            info = zc.get_service_info(type_, name, timeout=int(timeout * 1000))
            if info is None:
                return
            addresses = info.parsed_addresses()
            if not addresses:
                return
            found.append((info.server.rstrip(".") if info.server else name,
                          addresses[0], info.port))

        def update_service(self, *args):
            pass

        def remove_service(self, *args):
            pass

    zc = Zeroconf()
    try:
        ServiceBrowser(zc, SERVICE_TYPE, Listener())
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not found:
            time.sleep(0.1)
    finally:
        zc.close()
    return found


def _select(results):
    if not results:
        raise DiscoveryError(f"no {SERVICE_TYPE} device found")
    if len(results) > 1:
        names = ", ".join(f"{host}:{port}" for _, host, port in results)
        raise DiscoveryError(
            f"multiple devices found ({names}); use --tcp host:port to choose one")
    _name, host, port = results[0]
    return host, port


def discover_one(timeout=5.0):
    return _select(discover(timeout))
