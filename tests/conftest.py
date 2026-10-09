"""Shared fixtures: a scripted fake reader over a real TCP server."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any, cast

import pytest

from chainway_serial import ChainwayClient

from .fake_reader import FakeReaderLogic


class FakeReaderServerProtocol(asyncio.Protocol):
    """Serve one FakeReaderLogic over a TCP connection."""

    def __init__(self, logic: FakeReaderLogic) -> None:
        self._logic = logic
        self._transport: asyncio.Transport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self._transport = cast("asyncio.Transport", transport)
        self._logic.push = self._push
        self._logic.close_transport = self._close
        if self._logic.junk_on_connect:
            self._transport.write(self._logic.junk_on_connect)

    def data_received(self, data: bytes) -> None:
        if self._transport is None:
            return
        for frame in self._logic.handle_bytes(data):
            self._transport.write(frame)

    def _push(self, data: bytes) -> None:
        if self._transport is not None:
            self._transport.write(data)

    def _close(self) -> None:
        if self._transport is not None:
            self._transport.close()


@pytest.fixture(autouse=True)
def fast_client_timings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("chainway_serial.client.INVENTORY_START_DELAY", 0.0)
    monkeypatch.setattr("chainway_serial.client.MAINTENANCE_TICK", 0.05)
    monkeypatch.setattr("chainway_serial.client.CONFIG_COMMIT_DELAY", 0.0)


@pytest.fixture
async def reader_server() -> AsyncIterator[tuple[FakeReaderLogic, int]]:
    logic = FakeReaderLogic()
    loop = asyncio.get_running_loop()
    server = await loop.create_server(
        protocol_factory=lambda: FakeReaderServerProtocol(logic), host="127.0.0.1", port=0
    )
    port = server.sockets[0].getsockname()[1]
    async with server:
        yield logic, port


@pytest.fixture
async def client(
    reader_server: tuple[FakeReaderLogic, int],
) -> AsyncIterator[ChainwayClient]:
    _, port = reader_server
    client = ChainwayClient(
        f"socket://127.0.0.1:{port}",
        keepalive_interval=60.0,
        dead_link_timeout=60.0,
    )
    await client.connect()
    yield client
    await client.disconnect()


@pytest.fixture
def make_client(reader_server: tuple[FakeReaderLogic, int]) -> Callable[..., ChainwayClient]:
    _, port = reader_server

    def factory(**kwargs: Any) -> ChainwayClient:
        return ChainwayClient(f"socket://127.0.0.1:{port}", **kwargs)

    return factory


async def wait_for_server(logic: FakeReaderLogic) -> None:
    """Wait until the fake reader saw the client connection."""
    for _ in range(400):
        if logic.push is not None:
            return
        await asyncio.sleep(0.005)
    pytest.fail("the fake reader never saw the connection")
