"""Asynchronous Python library for Chainway UR4 UHF RFID readers.

The client speaks the reader wire protocol over any serialx URL: a
device path for RS-232, ``socket://host:8888`` for TCP, and the
rfc2217 or ESPHome proxies.
"""

from importlib.metadata import PackageNotFoundError as _PackageNotFoundError
from importlib.metadata import version as _version

from .client import ChainwayClient, ConnectionLostCallback, TagCallback
from .discovery import discover_readers
from .exceptions import (
    ChainwayConnectionError,
    ChainwayError,
    ChainwayInventoryActiveError,
    ChainwayProtocolError,
    ChainwayResponseError,
    ChainwayTimeoutError,
)
from .models import (
    AntennaPower,
    AntennaState,
    CollectedTags,
    DiscoveredReader,
    FirmwareVersion,
    Gen2Parameters,
    GpoState,
    InventoryMode,
    InventoryModeConfig,
    LockBank,
    LockMode,
    MemoryBank,
    OutputRoute,
    ProtocolType,
    ReaderAddress,
    Region,
    ReturnLoss,
    RfLink,
    Tag,
    TagFilter,
    TriggerConfig,
    TriggerInput,
    WorkMode,
)
from .parsers import build_lock_code

try:
    __version__ = _version("chainway-serial")
except _PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = [
    "AntennaPower",
    "AntennaState",
    "ChainwayClient",
    "ChainwayConnectionError",
    "ChainwayError",
    "ChainwayInventoryActiveError",
    "ChainwayProtocolError",
    "ChainwayResponseError",
    "ChainwayTimeoutError",
    "CollectedTags",
    "ConnectionLostCallback",
    "DiscoveredReader",
    "FirmwareVersion",
    "Gen2Parameters",
    "GpoState",
    "InventoryMode",
    "InventoryModeConfig",
    "LockBank",
    "LockMode",
    "MemoryBank",
    "OutputRoute",
    "ProtocolType",
    "ReaderAddress",
    "Region",
    "ReturnLoss",
    "RfLink",
    "Tag",
    "TagCallback",
    "TagFilter",
    "TriggerConfig",
    "TriggerInput",
    "WorkMode",
    "__version__",
    "build_lock_code",
    "discover_readers",
]
