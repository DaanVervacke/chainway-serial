"""Frame codec for the Chainway UR4 wire format."""

from __future__ import annotations

from .const import (
    FRAME_HEADER,
    FRAME_HEADERS,
    FRAME_OVERHEAD,
    FRAME_TAIL,
    MAX_FRAME_LENGTH,
    MIN_FRAME_LENGTH,
)
from .exceptions import ChainwayProtocolError


def compute_checksum(data: bytes) -> int:
    """Return the XOR of every byte in ``data``."""
    checksum = 0
    for byte in data:
        checksum ^= byte
    return checksum


def build_frame(command: int, payload: bytes = b"") -> bytes:
    """Build one request frame.

    Args:
        command: The request command byte.
        payload: The command payload.

    Raises:
        ChainwayProtocolError: The payload pushes the frame outside the
            8 to 2048 byte length window.
    """
    length = len(payload) + FRAME_OVERHEAD
    if not MIN_FRAME_LENGTH <= length <= MAX_FRAME_LENGTH:
        msg = f"frame length {length} falls outside 8 to 2048"
        raise ChainwayProtocolError(msg)
    body = bytes((length >> 8 & 0xFF, length & 0xFF, command)) + payload
    return FRAME_HEADER + body + bytes((compute_checksum(body),)) + FRAME_TAIL


def parse_frame(frame: bytes) -> tuple[int, bytes]:
    """Parse one complete frame and return its command and payload.

    Args:
        frame: The complete frame including header, checksum and tail.

    Returns:
        The command byte and the payload.

    Raises:
        ChainwayProtocolError: The frame is not a valid Chainway frame.
    """
    if not MIN_FRAME_LENGTH <= len(frame) <= MAX_FRAME_LENGTH:
        msg = f"frame length {len(frame)} falls outside 8 to 2048"
        raise ChainwayProtocolError(msg)
    if frame[:2] not in FRAME_HEADERS:
        msg = "frame does not start with a valid A5 5A or C8 8C header"
        raise ChainwayProtocolError(msg)
    if frame[-2:] != FRAME_TAIL:
        msg = "frame does not end with the 0D 0A tail"
        raise ChainwayProtocolError(msg)
    if compute_checksum(frame[2:-3]) != frame[-3]:
        msg = "frame checksum mismatch"
        raise ChainwayProtocolError(msg)
    return frame[4], frame[5:-3]
