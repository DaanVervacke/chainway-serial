"""Live checks of the TCP link. They skip on a serial URL."""

import asyncio
from urllib.parse import urlsplit

import pytest

from chainway_serial import ChainwayClient, ChainwayConnectionError, discover_readers

from .conftest import TCP, URL

pytestmark = pytest.mark.skipif(not TCP, reason="needs a socket:// URL")


async def _wait_for(lost: list[Exception]) -> None:
    for _ in range(100):
        if lost:
            return
        await asyncio.sleep(0.03)


async def _version_after_takeover(client: ChainwayClient) -> object:
    try:
        return await client.get_version()
    except ChainwayConnectionError:
        return await client.get_version()


async def test_two_clients_take_the_link_from_each_other() -> None:
    first_lost: list[Exception] = []
    second_lost: list[Exception] = []
    async with ChainwayClient(URL) as first:
        first.on_connection_lost = first_lost.append
        assert await first.get_version() is not None
        async with ChainwayClient(URL) as second:
            second.on_connection_lost = second_lost.append
            assert await second.get_version() is not None
            assert await _version_after_takeover(first) is not None
            await _wait_for(first_lost)
            assert len(first_lost) == 1
            assert await _version_after_takeover(second) is not None
            await _wait_for(second_lost)
            assert len(second_lost) == 1


async def test_discovery_finds_the_reader() -> None:
    target = urlsplit(URL)
    readers = await discover_readers()
    assert any(reader.ip == target.hostname and reader.port == target.port for reader in readers)
