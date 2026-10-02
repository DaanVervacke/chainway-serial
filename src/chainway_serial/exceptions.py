"""Typed exception hierarchy for chainway-serial."""

from __future__ import annotations


class ChainwayError(Exception):
    """Base class for every error raised by the library."""


class ChainwayConnectionError(ChainwayError, ConnectionError):
    """The serial or TCP link could not be opened or was lost."""


class ChainwayTimeoutError(ChainwayError, TimeoutError):
    """The reader did not answer within the response timeout."""


class ChainwayProtocolError(ChainwayError):
    """A frame violated the wire format: bad header, length, checksum or tail."""


class ChainwayResponseError(ChainwayError):
    """The reader answered with an unexpected or malformed payload."""


class ChainwayInventoryActiveError(ChainwayError):
    """The reader only answers stop inventory while a continuous inventory runs."""
