"""Fixtures for the live-hardware suite.

Run with ``CHAINWAY_URL=/dev/tty.PL2303G-USBtoUART110 uv run pytest hardware``.
Without CHAINWAY_URL every test skips. The suite talks to a real
reader: it changes settings and restores them, and one test drops the
link on purpose by shortening the dead-link timeout. The final test
runs a factory restore and then writes the buzzer setting back, so a
full run leaves the reader at factory defaults with the buzzer as it
was, and wipes any other settings stored on it before the run.
"""

import os
from collections.abc import AsyncIterator

import pytest

from chainway_serial import ChainwayClient


@pytest.fixture
def url() -> str:
    value = os.environ.get("CHAINWAY_URL")
    if not value:
        pytest.skip("CHAINWAY_URL is not set")
    return value


@pytest.fixture
async def client(url: str) -> AsyncIterator[ChainwayClient]:
    async with ChainwayClient(url) as live:
        yield live
