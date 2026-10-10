"""UDP discovery of Chainway readers on the local network."""

from __future__ import annotations

import asyncio
import ipaddress
import logging

from .const import DISCOVERY_LISTEN_SECONDS, DISCOVERY_PACKET_SIZE, UDP_DISCOVERY_PORT
from .exceptions import ChainwayConnectionError
from .models import DiscoveredReader

_LOGGER = logging.getLogger(__name__)


class _DiscoveryProtocol(asyncio.DatagramProtocol):
    """Collect discovery broadcasts into a dict keyed by reader identity."""

    def __init__(self, readers: dict[tuple[str, str, int], DiscoveredReader]) -> None:
        self._readers = readers

    def datagram_received(self, data: bytes, _addr: tuple[str | None, int]) -> None:
        if len(data) < DISCOVERY_PACKET_SIZE:
            _LOGGER.debug("ignoring %d byte discovery packet", len(data))
            return
        mac = ":".join(f"{byte:02x}" for byte in data[0:6])
        ip = ".".join(str(byte) for byte in data[6:10])
        port = data[10] << 8 | data[11]
        reader = DiscoveredReader(mac=mac, ip=ip, port=port)
        self._readers[(mac, ip, port)] = reader

    def error_received(self, exc: Exception) -> None:
        _LOGGER.debug("discovery endpoint error: %s", exc)


async def discover_readers(
    *,
    listen_seconds: float = DISCOVERY_LISTEN_SECONDS,
    port: int = UDP_DISCOVERY_PORT,
) -> list[DiscoveredReader]:
    """Listen for reader discovery broadcasts and return the readers heard.

    The reader sends a 12-byte packet with its MAC address, IPv4
    address and TCP port to the discovery port every 10 seconds. Both
    SDKs accept longer packets and read the first 12 bytes, so the
    listener does the same. It runs for ``listen_seconds`` seconds,
    collects one entry per unique reader, and returns them sorted by
    address.

    Args:
        listen_seconds: Seconds to listen before returning. The
            default of 12 seconds covers one full broadcast interval.
            A window shorter than 10 seconds can miss a reader. Wi-Fi
            drops some broadcasts, so on a wireless host 25 to 35
            seconds finds a reader more reliably.
        port: UDP port to listen on.

    Returns:
        Every reader that announced itself, sorted by IP and port.

    Raises:
        ChainwayConnectionError: The discovery port could not be
            opened, for example because another process holds it.
    """
    loop = asyncio.get_running_loop()
    readers: dict[tuple[str, str, int], DiscoveredReader] = {}
    try:
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _DiscoveryProtocol(readers),
            local_addr=("0.0.0.0", port),  # noqa: S104
        )
    except OSError as err:
        msg = f"could not listen on UDP port {port}: {err}"
        raise ChainwayConnectionError(msg) from err
    try:
        await asyncio.sleep(listen_seconds)
    finally:
        transport.close()
    return sorted(
        readers.values(), key=lambda reader: (ipaddress.IPv4Address(reader.ip), reader.port)
    )
