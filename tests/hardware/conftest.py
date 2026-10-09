"""Fixtures for the live-hardware suite.

Run with ``CHAINWAY_URL=/dev/ttyUSB0 uv run pytest tests/hardware``.
Without CHAINWAY_URL pytest does not collect these tests. The suite
talks to a real reader: it changes settings and restores them, and one
test drops the link on purpose by shortening the dead-link timeout. The
final test runs a factory restore and then writes the buzzer setting
and the reader address back, so a full run leaves the reader at
factory defaults with the buzzer and address as they were, and wipes
any other settings stored on it before the run. Over TCP the factory
restore is skipped.
"""

import os
from collections.abc import AsyncIterator

import pytest

from chainway_serial import ChainwayClient

URL = os.environ.get("CHAINWAY_URL", "")
TCP = URL.startswith("socket://")

collect_ignore_glob = [] if URL else ["test_*.py"]


@pytest.fixture(autouse=True)
def fast_client_timings() -> None:
    """Keep the real reader timings that the unit tests set to zero."""


@pytest.fixture
def url() -> str:
    return URL


@pytest.fixture
async def client(url: str) -> AsyncIterator[ChainwayClient]:
    async with ChainwayClient(url) as live:
        yield live
