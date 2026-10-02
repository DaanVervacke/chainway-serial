"""UDP discovery tests over the loopback interface."""

import asyncio
import socket

from chainway_serial import DiscoveredReader, discover_readers
from chainway_serial.discovery import _DiscoveryProtocol


def free_udp_port() -> int:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    address = probe.getsockname()
    probe.close()
    return int(address[1])


async def test_discover_readers_collects_broadcasts() -> None:
    port = free_udp_port()
    task = asyncio.create_task(discover_readers(listen_seconds=0.3, port=port))
    await asyncio.sleep(0.05)
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    packet = bytes.fromhex("aabbccddeeff") + bytes((192, 168, 99, 200)) + b"\x22\xb8"
    sender.sendto(packet, ("127.0.0.1", port))
    sender.sendto(packet, ("127.0.0.1", port))
    sender.sendto(b"\x00\x01", ("127.0.0.1", port))
    sender.close()
    readers = await task
    assert readers == [DiscoveredReader(mac="aa:bb:cc:dd:ee:ff", ip="192.168.99.200", port=8888)]


async def test_discover_readers_returns_empty_without_broadcasts() -> None:
    port = free_udp_port()
    assert await discover_readers(listen_seconds=0.05, port=port) == []


async def test_discovery_endpoint_reports_delivery_errors() -> None:
    readers: dict[tuple[str, str, int], DiscoveredReader] = {}
    protocol = _DiscoveryProtocol(readers)
    protocol.error_received(OSError("port unreachable"))
    assert not readers
