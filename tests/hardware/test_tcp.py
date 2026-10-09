"""Live checks of the TCP link. They skip on a serial URL."""

import asyncio
import socket
from dataclasses import replace
from urllib.parse import urlsplit

import pytest

from chainway_serial import (
    ChainwayClient,
    ChainwayConnectionError,
    ChainwayError,
    OutputRoute,
    ReaderAddress,
    WorkMode,
    discover_readers,
)
from chainway_serial.const import Command
from chainway_serial.frames import parse_frame

from .conftest import TCP, URL

pytestmark = pytest.mark.skipif(not TCP, reason="needs a socket:// URL")

UDP_PUSH_PORT = 9999
UDP_PUSH_WAIT_SECONDS = 40
UDP_PUSH_MIN_DATAGRAMS = 10


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


async def test_a_new_client_ends_the_scan_of_the_one_it_replaces() -> None:
    stray: list[object] = []
    async with ChainwayClient(URL) as first:
        await first.start_inventory()
        await asyncio.sleep(1.0)
        async with ChainwayClient(URL, on_tag=stray.append) as second:
            assert await second.get_version() is not None
            await asyncio.sleep(1.0)
            assert stray == []
            assert not second.inventory_active


class _Datagrams(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.frames: list[int] = []

    def datagram_received(self, data: bytes, _addr: tuple[str | None, int]) -> None:
        length = int.from_bytes(data[2:4])
        command, _payload = parse_frame(data[:length])
        self.frames.append(command)


def _host_address(reader_ip: str) -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect((reader_ip, UDP_PUSH_PORT))
        return str(probe.getsockname()[0])


async def _answer_after_boot(client: ChainwayClient) -> None:
    for _ in range(45):
        try:
            await client.get_version()
        except ChainwayError:
            await asyncio.sleep(1.0)
        else:
            return


async def test_auto_mode_pushes_tags_over_udp() -> None:
    target = urlsplit(URL)
    assert target.hostname is not None
    host = ReaderAddress(ip=_host_address(target.hostname), port=UDP_PUSH_PORT)
    loop = asyncio.get_running_loop()
    transport, datagrams = await loop.create_datagram_endpoint(
        _Datagrams,
        local_addr=("0.0.0.0", UDP_PUSH_PORT),  # noqa: S104
    )
    client = ChainwayClient(URL)
    try:
        destination = await client.get_destination_address()
        trigger = await client.get_trigger_config()
        try:
            await client.set_destination_address(host)
            await client.set_trigger_config(replace(trigger, output=OutputRoute.UDP))
            await client.set_work_mode(WorkMode.AUTO)
            await client.software_reset()
            await client.disconnect()
            for _ in range(UDP_PUSH_WAIT_SECONDS):
                if len(datagrams.frames) >= UDP_PUSH_MIN_DATAGRAMS:
                    break
                await asyncio.sleep(1.0)
            assert len(datagrams.frames) >= UDP_PUSH_MIN_DATAGRAMS
            assert set(datagrams.frames) == {Command.TAG_STREAM}
        finally:
            await _answer_after_boot(client)
            await client.set_work_mode(WorkMode.COMMAND)
            await client.set_trigger_config(trigger)
            await client.set_destination_address(destination)
        assert await client.get_work_mode() is WorkMode.COMMAND
        assert await client.get_trigger_config() == trigger
        assert await client.get_destination_address() == destination
    finally:
        await client.disconnect()
        transport.close()


async def test_discovery_finds_the_reader() -> None:
    target = urlsplit(URL)
    readers = await discover_readers(listen_seconds=35.0)
    assert any(reader.ip == target.hostname and reader.port == target.port for reader in readers)
