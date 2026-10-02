"""Asyncio protocol that frames the Chainway UR4 byte stream."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import cast

from serialx import BaseSerialTransport

from .const import FRAME_HEADER, FRAME_PREFIX_SIZE, MAX_FRAME_LENGTH, MIN_FRAME_LENGTH
from .exceptions import ChainwayProtocolError
from .frames import parse_frame

_LOGGER = logging.getLogger(__name__)

FrameHandler = Callable[[int, bytes], None]
ConnectionLostHandler = Callable[[Exception | None], None]


class ChainwayProtocol(asyncio.Protocol):
    """Buffer inbound bytes and hand complete frames to a callback.

    The state machine hunts the A5 5A header, validates the 8 to 2048
    length window, verifies the XOR checksum and the 0D 0A tail, and
    resynchronizes on the next header after any violation. Stray bytes
    such as the bare inventory keepalive byte are discarded without
    error.
    """

    def __init__(
        self,
        on_frame: FrameHandler,
        on_connection_lost: ConnectionLostHandler,
    ) -> None:
        """Initialize the protocol.

        Args:
            on_frame: Called with the command and payload of every valid
                inbound frame.
            on_connection_lost: Called with the exception that ended the
                link, or None for a clean close.
        """
        self._on_frame = on_frame
        self._on_connection_lost = on_connection_lost
        self._buffer = bytearray()
        self._transport: BaseSerialTransport | None = None
        self.last_activity = time.monotonic()

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        """Store the serial transport that owns this protocol."""
        self._transport = cast("BaseSerialTransport", transport)

    def data_received(self, data: bytes) -> None:
        """Buffer inbound bytes and extract every complete frame."""
        self.last_activity = time.monotonic()
        self._buffer.extend(data)
        while self._extract_one_frame():
            continue

    def connection_lost(self, exc: Exception | None) -> None:
        """Forward the loss of the link to the callback."""
        self._on_connection_lost(exc)

    def _extract_one_frame(self) -> bool:
        """Try to extract one frame, resynchronizing on any violation.

        Returns whether progress was made, a frame extracted or garbage
        dropped, so the caller can loop until the buffer needs more data.
        """
        header_index = self._buffer.find(FRAME_HEADER)
        if header_index < 0:
            if self._buffer and self._buffer[-1] == FRAME_HEADER[0]:
                del self._buffer[:-1]
            else:
                self._buffer.clear()
            return False
        if header_index > 0:
            del self._buffer[:header_index]
            return True
        if len(self._buffer) < FRAME_PREFIX_SIZE:
            return False
        length = self._buffer[2] << 8 | self._buffer[3]
        if not MIN_FRAME_LENGTH <= length <= MAX_FRAME_LENGTH:
            del self._buffer[:1]
            _LOGGER.debug("dropping frame with invalid length %d", length)
            return True
        if len(self._buffer) < length:
            return False
        return self._extract_complete_frame(length)

    def _extract_complete_frame(self, length: int) -> bool:
        """Validate one buffered frame of ``length`` bytes and emit it."""
        frame = bytes(self._buffer[:length])
        try:
            command, payload = parse_frame(frame)
        except ChainwayProtocolError as err:
            del self._buffer[:1]
            _LOGGER.debug("resynchronizing after %s", err)
            return True
        del self._buffer[:length]
        self._on_frame(command, payload)
        return True
