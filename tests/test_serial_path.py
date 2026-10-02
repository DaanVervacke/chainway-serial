"""Serial device path tests over a POSIX pseudo terminal."""

from __future__ import annotations

import asyncio
import os
import pty
import sys

import pytest

from chainway_serial import ChainwayClient, ChainwayConnectionError, FirmwareVersion

from .fake_reader import FakeReaderLogic

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX pty only")


async def test_device_path_roundtrip() -> None:
    logic = FakeReaderLogic()
    master, slave = pty.openpty()
    slave_path = os.ttyname(slave)
    loop = asyncio.get_running_loop()

    def on_readable() -> None:
        try:
            data = os.read(master, 4096)
        except OSError:
            return
        for frame in logic.handle_bytes(data):
            os.write(master, frame)

    loop.add_reader(master, on_readable)
    client = ChainwayClient(slave_path, keepalive_interval=60.0, dead_link_timeout=60.0)
    try:
        await client.connect()
        assert await client.get_version() == FirmwareVersion(1, 2, 3)
    finally:
        loop.remove_reader(master)
        await client.disconnect()
        os.close(master)
        os.close(slave)


async def test_device_path_reports_open_failures() -> None:
    client = ChainwayClient(
        "/nonexistent/ttyUR4",
        keepalive_interval=60.0,
        dead_link_timeout=60.0,
    )
    with pytest.raises(ChainwayConnectionError, match="could not open"):
        await client.connect()
