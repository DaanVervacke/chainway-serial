"""Typed models for every decoded reader response."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum

from .const import BYTE_MAX, IPV4_OCTETS


def _require_range(name: str, value: int, low: int, high: int) -> None:
    if not low <= value <= high:
        msg = f"{name} must be between {low} and {high}, got {value}"
        raise ValueError(msg)


class InventoryMode(IntEnum):
    """Data blocks a tag sighting carries, set with command 0x70."""

    EPC = 0x00
    EPC_TID = 0x01
    EPC_TID_USER = 0x02


class WorkMode(IntEnum):
    """Who drives the inventory, set with 0xA1 sub 05."""

    COMMAND = 0x00
    AUTO = 0x01
    TRIGGER = 0x02


class MemoryBank(IntEnum):
    """Gen2 memory bank numbers used by tag operations and filters."""

    EPC = 0x01
    TID = 0x02
    USER = 0x03


class Region(IntEnum):
    """Regulatory frequency region, set with command 0x2C."""

    CHINA_1 = 0x01
    CHINA_2 = 0x02
    EUROPE = 0x04
    USA = 0x08
    KOREA = 0x16
    JAPAN = 0x32


class ProtocolType(IntEnum):
    """Air interface protocol, set with command 0x06."""

    ISO_18000_6C = 0x00
    GB_T_29768 = 0x01
    GJB_7377_1 = 0x02


class RfLink(IntEnum):
    """Recommended RF link combination, set with command 0x52."""

    DSB_ASK_FM0_40_KHZ = 0x00
    PR_ASK_MILLER_4_250_KHZ = 0x01
    PR_ASK_MILLER_4_300_KHZ = 0x02
    DSB_ASK_FM0_400_KHZ = 0x03


class LinkFrequency(IntEnum):
    """Gen2 link frequency index used inside the Gen2 parameter block."""

    FREQ_40_KHZ = 0x00
    FREQ_160_KHZ = 0x01
    FREQ_200_KHZ = 0x02
    FREQ_250_KHZ = 0x03
    FREQ_300_KHZ = 0x04
    FREQ_320_KHZ = 0x05
    FREQ_400_KHZ = 0x06
    FREQ_640_KHZ = 0x07


class LockMode(IntEnum):
    """Lock action applied to every selected memory bank."""

    LOCK = 0x10
    OPEN = 0x20
    PERMANENTLY_LOCK = 0x30
    PERMANENTLY_OPEN = 0x40


class LockBank(IntEnum):
    """Tag memory bank a lock action applies to."""

    KILL_PASSWORD = 0x10
    ACCESS_PASSWORD = 0x20
    EPC = 0x30
    TID = 0x40
    USER = 0x50


class TriggerInput(IntEnum):
    """GPI input that starts an inventory run in trigger work mode."""

    INPUT_1 = 0x00
    INPUT_2 = 0x01


class OutputRoute(IntEnum):
    """Where collected tag sightings are delivered."""

    LINK = 0x00
    UDP = 0x01


@dataclass(frozen=True, slots=True)
class FirmwareVersion:
    """Version triple reported by the reader."""

    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"V{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True, slots=True)
class InventoryModeConfig:
    """Inventory mode together with the USER read window."""

    mode: InventoryMode
    user_address: int = 0
    user_length: int = 0

    def __post_init__(self) -> None:
        _require_range("user_address", self.user_address, 0, BYTE_MAX)
        _require_range("user_length", self.user_length, 0, BYTE_MAX)


@dataclass(frozen=True, slots=True)
class AntennaState:
    """Antenna connection state from command 0x4E."""

    connected: tuple[bool, ...]
    raw: bytes

    def __post_init__(self) -> None:
        if not self.connected:
            msg = "connected must list at least one antenna"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class AntennaPower:
    """Read and write power of one antenna."""

    antenna: int
    read_power_dbm: float
    write_power_dbm: float


@dataclass(frozen=True, slots=True)
class Tag:
    """One tag sighting from an inventory stream or a single inventory."""

    pc: bytes
    epc: bytes
    tid: bytes | None
    user_data: bytes | None
    rssi: float | None
    antenna: int | None
    received_at: datetime
    phase: int | None = None


@dataclass(frozen=True, slots=True)
class TagFilter:
    """Tag selection filter used by the read, write, lock and kill requests."""

    bank: MemoryBank
    bit_address: int
    bit_length: int
    data: bytes

    def __post_init__(self) -> None:
        _require_range("bit_address", self.bit_address, 0, 0xFFFF)
        _require_range("bit_length", self.bit_length, 0, 0xFFFF)
        needed = math.ceil(self.bit_length / 8)
        if len(self.data) < needed:
            msg = f"data carries {len(self.data)} bytes but {needed} are needed"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class TriggerConfig:
    """Trigger work mode timing, set with 0xA1 sub 0B."""

    input: TriggerInput
    work_time_ms: int
    min_interval_ms: int
    output: OutputRoute

    def __post_init__(self) -> None:
        _require_range("work_time_ms", self.work_time_ms, 0, 655350)
        _require_range("min_interval_ms", self.min_interval_ms, 0, 655350)


@dataclass(frozen=True, slots=True)
class GpoState:
    """GPO output levels from 0xA1 sub 0A."""

    output_0: bool
    output_1: bool


@dataclass(frozen=True, slots=True)
class ReaderAddress:
    """IPv4 address and port of the reader or of its push destination."""

    ip: str
    port: int
    subnet_mask: str | None = None
    gateway: str | None = None

    def __post_init__(self) -> None:
        parts = self.ip.split(".")
        if len(parts) != IPV4_OCTETS or any(
            not part.isdigit() or not 0 <= int(part) <= BYTE_MAX for part in parts
        ):
            msg = f"ip must be a dotted quad, got {self.ip}"
            raise ValueError(msg)
        _require_range("port", self.port, 1, 65535)


@dataclass(frozen=True, slots=True)
class CollectedTags:
    """Tags pulled from the reader storage with command 0xE0."""

    index: int
    tags: tuple[bytes, ...]


@dataclass(frozen=True, slots=True)
class DiscoveredReader:
    """One reader that answered the UDP discovery broadcast."""

    mac: str
    ip: str
    port: int


@dataclass(frozen=True, slots=True)
class Gen2Parameters:
    """Gen2 inventory parameters, packed into four bytes on the wire.

    The ranges follow the Windows DLL document: ``target`` 0 to 4 for S0
    through S3 and SL, ``action`` 0 to 7, ``start_q``, ``min_q`` and
    ``max_q`` 0 to 15, ``coding`` 0 for FM0 and 1 to 3 for Miller 2, 4 and
    8, ``sel`` 0 to 3, and ``session`` 0 to 3 for S0 through S3.
    """

    target: int = 0x04
    action: int = 0x00
    truncate: bool = False
    dynamic_q: bool = True
    start_q: int = 0x04
    min_q: int = 0x00
    max_q: int = 0x0F
    divider_ratio: int = 0x01
    coding: int = 0x01
    tr_ext: bool = True
    sel: int = 0x00
    session: int = 0x01
    gen2_target: bool = False
    link_frequency: int = 0x02

    def __post_init__(self) -> None:
        _require_range("target", self.target, 0, 4)
        _require_range("action", self.action, 0, 7)
        _require_range("start_q", self.start_q, 0, 15)
        _require_range("min_q", self.min_q, 0, 15)
        _require_range("max_q", self.max_q, 0, 15)
        _require_range("divider_ratio", self.divider_ratio, 0, 1)
        _require_range("coding", self.coding, 0, 3)
        _require_range("sel", self.sel, 0, 3)
        _require_range("session", self.session, 0, 3)
        _require_range("link_frequency", self.link_frequency, 0, 7)
