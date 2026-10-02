"""Typed Chainway UR4 client."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Collection, Coroutine
from contextlib import suppress
from types import TracebackType
from typing import Self, TypeVar

import serialx
from serialx import BaseSerialTransport, Parity, StopBits

from .const import (
    BARCODE_NO_READ_PAYLOAD,
    BOOTLOADER_JUMP_PAYLOAD,
    BYTE_MAX,
    DEFAULT_BAUDRATE,
    DEFAULT_DEAD_LINK_TIMEOUT,
    DEFAULT_KEEPALIVE_INTERVAL,
    DEFAULT_RESPONSE_TIMEOUT,
    INVENTORY_KEEPALIVE_BYTE,
    INVENTORY_START_DELAY,
    MAINTENANCE_TICK,
    MAX_ANTENNA,
    MAX_FIXED_FREQUENCY_KHZ,
    MAX_POWER_DBM,
    MIN_ANTENNA,
    MIN_POWER_DBM,
    SINGLE_INVENTORY_PAYLOAD,
    START_INVENTORY_PAYLOAD,
    START_INVENTORY_PHASE_PAYLOAD,
    UPDATE_BLOCK_SIZE,
    WORD_MAX,
    Command,
    ConfigSubcommand,
    FlashDataSubcommand,
    FlashSubcommand,
    PeripheralSubcommand,
    ProtocolTypeSelector,
)
from .exceptions import (
    ChainwayConnectionError,
    ChainwayError,
    ChainwayInventoryActiveError,
    ChainwayResponseError,
    ChainwayTimeoutError,
)
from .frames import build_frame
from .models import (
    AntennaPower,
    AntennaState,
    CollectedTags,
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
    RfLink,
    Tag,
    TagFilter,
    TriggerConfig,
    TriggerInput,
    WorkMode,
)
from .parsers import (
    banks_tuple,
    build_filter_payload,
    build_lock_code,
    build_power_payload,
    build_reader_address_payload,
    build_tag_operation_payload,
    now_utc,
    pack_gen2_parameters,
    parse_antenna_connection_state,
    parse_collected_tags,
    parse_flash_tags,
    parse_power_records,
    parse_reader_address,
    parse_tag_record,
    parse_temperature,
    parse_version,
    require_minimum_length,
    require_status_header,
    unpack_gen2_parameters,
    validate_word_window,
)
from .protocol import ChainwayProtocol

TagCallback = Callable[[Tag], Awaitable[None] | None]
ConnectionLostCallback = Callable[[Exception], Awaitable[None] | None]
CallbackArgument = TypeVar("CallbackArgument")
_LOGGER = logging.getLogger(__name__)


class _LinkClosed:
    """Sentinel pushed into the tag queue when the inventory stream ends."""

    __slots__ = ("error",)

    def __init__(self, error: Exception | None) -> None:
        self.error = error


def _consume_task_exception(task: asyncio.Task[None]) -> None:
    if not task.cancelled() and task.exception() is not None:
        _LOGGER.debug("callback task failed: %s", task.exception())


def _require_ack(payload: bytes, command: Command) -> None:
    if not payload or payload[0] != 0x01:
        msg = f"command {command:#04x} was not acknowledged, got payload {payload!r}"
        raise ChainwayResponseError(msg)


TAG_SUCCESS = b"\x01\x00"


def _require_tag_success(payload: bytes, command: Command) -> None:
    if payload[:2] != TAG_SUCCESS:
        code = payload[1] if len(payload) > 1 else None
        msg = f"command {command:#04x} failed with error code {code}"
        raise ChainwayResponseError(msg)


class ChainwayClient:
    """Communicate with one Chainway UR4 reader.

    The client speaks the reader wire protocol over any serialx URL: a
    device path for RS-232, ``socket://host:8888`` for TCP, and the
    rfc2217 or ESPHome proxies. One request runs at a time, tag
    sightings stream through :meth:`inventory`, and after a link drop
    the next command reconnects on its own.
    """

    def __init__(
        self,
        url: str,
        *,
        baudrate: int = DEFAULT_BAUDRATE,
        parity: Parity = Parity.NONE,
        stopbits: StopBits = StopBits.ONE,
        xonxoff: bool = False,
        rtscts: bool = False,
        response_timeout: float = DEFAULT_RESPONSE_TIMEOUT,
        keepalive_interval: float = DEFAULT_KEEPALIVE_INTERVAL,
        dead_link_timeout: float = DEFAULT_DEAD_LINK_TIMEOUT,
        on_tag: TagCallback | None = None,
        on_connection_lost: ConnectionLostCallback | None = None,
    ) -> None:
        """Initialize the client.

        Args:
            url: The serialx URL of the reader, a device path or
                ``socket://host:port``.
            baudrate: Line baudrate for serial device paths.
            parity: Line parity for serial device paths.
            stopbits: Line stop bits for serial device paths.
            xonxoff: Software flow control for serial device paths.
            rtscts: Hardware flow control for serial device paths.
            response_timeout: Seconds to wait for each reader response.
            keepalive_interval: Seconds between keepalive sends.
            dead_link_timeout: Seconds of inbound silence after which
                an idle link is dropped. The check stays suspended
                while an inventory runs.
            on_tag: Called with every tag sighting that arrives outside
                an active :meth:`inventory` iteration.
            on_connection_lost: Called with the error that ended the
                link.
        """
        self.url = url
        self.response_timeout = response_timeout
        self.keepalive_interval = keepalive_interval
        self.dead_link_timeout = dead_link_timeout
        self.on_tag = on_tag
        self.on_connection_lost = on_connection_lost
        self._baudrate = baudrate
        self._parity = parity
        self._stopbits = stopbits
        self._xonxoff = xonxoff
        self._rtscts = rtscts
        self._transport: BaseSerialTransport | None = None
        self._protocol: ChainwayProtocol | None = None
        self._lock = asyncio.Lock()
        self._lifecycle_lock = asyncio.Lock()
        self._pending: tuple[int, asyncio.Future[bytes]] | None = None
        self._inventory_active = False
        self._inventory_phase = False
        self._tag_queue: asyncio.Queue[Tag | _LinkClosed] | None = None
        self._maintenance_task: asyncio.Task[None] | None = None
        self._callback_tasks: set[asyncio.Task[None]] = set()
        self._last_keepalive = 0.0

    @property
    def connected(self) -> bool:
        """Whether the link is open."""
        return self._transport is not None

    @property
    def inventory_active(self) -> bool:
        """Whether a continuous inventory is running."""
        return self._inventory_active

    async def connect(self) -> None:
        """Open the link and start the keepalive loop.

        A no-op when already open, reusable after
        :meth:`disconnect`.

        Raises:
            ChainwayConnectionError: The URL could not be opened.
        """
        async with self._lifecycle_lock:
            if self._transport is not None:
                return
            protocol = ChainwayProtocol(self._handle_frame, self._schedule_drop_link)
            loop = asyncio.get_running_loop()
            try:
                transport, _ = await serialx.create_serial_connection(
                    loop,
                    lambda: protocol,
                    url=self.url,
                    baudrate=self._baudrate,
                    parity=self._parity,
                    stopbits=self._stopbits,
                    xonxoff=self._xonxoff,
                    rtscts=self._rtscts,
                )
            except (serialx.SerialException, OSError) as err:
                msg = f"could not open {self.url}: {err}"
                raise ChainwayConnectionError(msg) from err
            self._transport = transport
            self._protocol = protocol
            self._last_keepalive = time.monotonic()
            self._maintenance_task = asyncio.create_task(self._maintenance_loop())

    async def disconnect(self) -> None:
        """Close the link and stop the keepalive loop.

        Pending requests fail with
        :class:`chainway_serial.ChainwayConnectionError`. A no-op when
        already closed.
        """
        async with self._lifecycle_lock:
            await self._teardown()

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.disconnect()

    async def get_version(self) -> FirmwareVersion:
        """Return the UHF module firmware version."""
        payload = await self._request(Command.GET_VERSION)
        return parse_version(payload)

    async def get_stm32_version(self) -> FirmwareVersion:
        """Return the STM32 microcontroller version."""
        payload = await self._request(Command.STM32_VERSION)
        return parse_version(payload)

    async def get_module_version(self) -> FirmwareVersion:
        """Return the SDK firmware version of the module."""
        payload = await self._request(Command.MODULE_VERSION)
        return parse_version(payload)

    async def get_temperature(self) -> float:
        """Return the reader temperature in degrees C."""
        payload = await self._request(Command.GET_TEMPERATURE)
        return parse_temperature(payload)

    async def get_antenna_connection_state(self) -> AntennaState:
        """Return which antennas are connected."""
        payload = await self._request(Command.ANTENNA_CONNECTION_STATE)
        return AntennaState(connected=parse_antenna_connection_state(payload), raw=payload)

    async def get_battery_level(self) -> int:
        """Return the battery charge percentage."""
        payload = await self._request(Command.PERIPHERAL, bytes((PeripheralSubcommand.BATTERY,)))
        require_status_header(payload, 2, PeripheralSubcommand.BATTERY, "battery")
        return payload[1]

    async def set_reader_idle_sleep_time(self, value: int) -> None:
        """Set the reader idle sleep time.

        Both SDKs carry the command, neither documents the unit, so
        the meaning of the value is unverified.

        Raises:
            ValueError: The value is out of range.
        """
        if not 0 <= value <= BYTE_MAX:
            msg = f"idle sleep time must be between 0 and 255, got {value}"
            raise ValueError(msg)
        response = await self._request(
            Command.PERIPHERAL, bytes((PeripheralSubcommand.IDLE_SLEEP_SET, value))
        )
        _require_ack(response, Command.PERIPHERAL)

    async def get_reader_idle_sleep_time(self) -> int:
        """Return the reader idle sleep time."""
        payload = await self._request(
            Command.PERIPHERAL, bytes((PeripheralSubcommand.IDLE_SLEEP_GET,))
        )
        require_status_header(payload, 2, PeripheralSubcommand.IDLE_SLEEP_GET, "idle sleep time")
        return payload[1]

    async def set_rf_power(self, power_dbm: float, *, antenna: int = 1) -> None:
        """Set the transmit and receive power of one antenna.

        Args:
            power_dbm: Power in dBm applied to both directions.
            antenna: One-based antenna number.

        Raises:
            ValueError: The antenna number or the power value is out
                of range.
        """
        if not MIN_POWER_DBM <= power_dbm <= MAX_POWER_DBM:
            msg = f"power must be between {MIN_POWER_DBM} and {MAX_POWER_DBM} dBm, got {power_dbm}"
            raise ValueError(msg)
        payload = build_power_payload(antenna, power_dbm, power_dbm)
        response = await self._request(Command.SET_POWER, payload)
        _require_ack(response, Command.SET_POWER)

    async def set_antenna_power(
        self, antenna: int, read_power_dbm: float, write_power_dbm: float
    ) -> None:
        """Set separate receive and transmit power for one antenna.

        Raises:
            ValueError: The antenna number or a power value is out of
                range.
        """
        for power in (read_power_dbm, write_power_dbm):
            if not MIN_POWER_DBM <= power <= MAX_POWER_DBM:
                msg = f"power must be between {MIN_POWER_DBM} and {MAX_POWER_DBM} dBm, got {power}"
                raise ValueError(msg)
        payload = build_power_payload(antenna, read_power_dbm, write_power_dbm)
        response = await self._request(Command.SET_POWER, payload)
        _require_ack(response, Command.SET_POWER)

    async def get_rf_power(self) -> tuple[AntennaPower, ...]:
        """Return the read and write power of every antenna."""
        payload = await self._request(Command.GET_POWER)
        return parse_power_records(payload)

    async def set_fixed_frequency(self, frequency_khz: int) -> None:
        """Pin the reader to one frequency.

        Raises:
            ValueError: The frequency does not fit the 3-byte field.
        """
        if not 1 <= frequency_khz <= MAX_FIXED_FREQUENCY_KHZ:
            msg = f"frequency must be at most {MAX_FIXED_FREQUENCY_KHZ} kHz, got {frequency_khz}"
            raise ValueError(msg)
        payload = b"\x01" + frequency_khz.to_bytes(3)
        response = await self._request(Command.SET_FIXED_FREQUENCY, payload)
        _require_ack(response, Command.SET_FIXED_FREQUENCY)

    async def set_region(self, region: Region, *, save: bool = True) -> None:
        """Set the regulatory frequency region."""
        payload = bytes((int(save), region))
        response = await self._request(Command.SET_REGION, payload)
        _require_ack(response, Command.SET_REGION)

    async def get_region(self) -> Region:
        """Return the regulatory frequency region."""
        payload = await self._request(Command.GET_REGION)
        require_status_header(payload, 2, 0x01, "region")
        return Region(payload[1])

    async def set_carrier_wave(self, *, enabled: bool) -> None:
        """Turn the continuous carrier wave on or off."""
        response = await self._request(Command.SET_CARRIER_WAVE, bytes((int(enabled),)))
        _require_ack(response, Command.SET_CARRIER_WAVE)

    async def get_carrier_wave(self) -> bool:
        """Return whether the continuous carrier wave is on.

        Both SDKs read the first payload byte as the state and do not
        check the response length, so any length is accepted.
        """
        payload = await self._request(Command.GET_CARRIER_WAVE)
        require_minimum_length(payload, 1, "carrier wave")
        return payload[0] == 0x01

    async def set_gen2_parameters(self, parameters: Gen2Parameters) -> None:
        """Set the Gen2 inventory parameters."""
        response = await self._request(
            Command.SET_GEN2_PARAMETERS, pack_gen2_parameters(parameters)
        )
        _require_ack(response, Command.SET_GEN2_PARAMETERS)

    async def get_gen2_parameters(self) -> Gen2Parameters:
        """Return the Gen2 inventory parameters."""
        payload = await self._request(Command.GET_GEN2_PARAMETERS)
        return unpack_gen2_parameters(payload)

    async def set_rf_link(self, mode: RfLink, *, save: bool = True) -> None:
        """Set the recommended RF link combination."""
        payload = bytes((0x00, int(save), mode))
        response = await self._request(Command.SET_RF_LINK, payload)
        _require_ack(response, Command.SET_RF_LINK)

    async def get_rf_link(self) -> RfLink:
        """Return the recommended RF link combination."""
        payload = await self._request(Command.GET_RF_LINK, b"\x00\x00")
        require_status_header(payload, 3, 0x01, "RF")
        return RfLink(payload[2])

    async def set_fast_id(self, *, enabled: bool) -> None:
        """Turn FastID on or off."""
        response = await self._request(Command.SET_FAST_ID, bytes((int(enabled), 0x00)))
        _require_ack(response, Command.SET_FAST_ID)

    async def get_fast_id(self) -> bool:
        """Return whether FastID is on."""
        payload = await self._request(Command.GET_FAST_ID, b"\x00\x00")
        require_status_header(payload, 2, 0x01, "FastID")
        return payload[1] == 0x01

    async def set_tag_focus(self, *, enabled: bool) -> None:
        """Turn TagFocus on or off."""
        response = await self._request(Command.SET_TAG_FOCUS, bytes((int(enabled), 0x00)))
        _require_ack(response, Command.SET_TAG_FOCUS)

    async def get_tag_focus(self) -> bool:
        """Return whether TagFocus is on."""
        payload = await self._request(Command.GET_TAG_FOCUS, b"\x00\x00")
        require_minimum_length(payload, 2, "TagFocus")
        return payload[1] == 0x01

    async def set_protocol_type(self, protocol_type: ProtocolType) -> None:
        """Set the air interface protocol type."""
        payload = bytes((ProtocolTypeSelector.SET, protocol_type))
        response = await self._request(Command.SET_PROTOCOL_TYPE, payload)
        if response != b"\x00\x01":
            msg = f"protocol type set was not acknowledged, got payload {response!r}"
            raise ChainwayResponseError(msg)

    async def get_protocol_type(self) -> ProtocolType:
        """Return the air interface protocol type."""
        payload = await self._request(
            Command.SET_PROTOCOL_TYPE, bytes((ProtocolTypeSelector.GET, 0x00))
        )
        require_status_header(payload, 2, ProtocolTypeSelector.GET, "protocol")
        return ProtocolType(payload[1])

    async def set_inventory_mode(
        self,
        mode: InventoryMode,
        *,
        user_address: int = 0,
        user_length: int = 0,
        save: bool = True,
    ) -> None:
        """Select which data blocks a tag sighting carries.

        Raises:
            ValueError: The USER window is out of range.
        """
        if not 0 <= user_address <= BYTE_MAX or not 0 <= user_length <= BYTE_MAX:
            msg = f"USER window values must fit one byte, got {user_address} and {user_length}"
            raise ValueError(msg)
        payload = bytes((int(save), mode, user_address, user_length))
        response = await self._request(Command.SET_INVENTORY_MODE, payload)
        _require_ack(response, Command.SET_INVENTORY_MODE)

    async def get_inventory_mode(self) -> InventoryModeConfig:
        """Return the inventory mode and the USER read window."""
        payload = await self._request(Command.GET_INVENTORY_MODE, b"\x00\x00")
        require_status_header(payload, 4, 0x01, "inventory")
        return InventoryModeConfig(
            mode=InventoryMode(payload[1]),
            user_address=payload[2],
            user_length=payload[3],
        )

    async def set_filter(self, tag_filter: TagFilter | None, *, save: bool = True) -> None:
        """Set the tag filter, or clear it with ``None``."""
        payload = build_filter_payload(tag_filter, save=save)
        response = await self._request(Command.SET_INVENTORY_FILTER, payload)
        _require_ack(response, Command.SET_INVENTORY_FILTER)

    async def set_antenna_mask(self, mask: int, *, save: bool = True) -> None:
        """Set the 16-bit antenna enable mask, bit 0 is antenna 1.

        Raises:
            ValueError: The mask does not fit 16 bits.
        """
        if not 0 <= mask <= WORD_MAX:
            msg = f"mask must be between 0 and 65535, got {mask}"
            raise ValueError(msg)
        payload = bytes((int(save), mask >> 8 & 0xFF, mask & 0xFF))
        response = await self._request(Command.SET_ANTENNA_MASK, payload)
        _require_ack(response, Command.SET_ANTENNA_MASK)

    async def get_antenna_mask(self) -> int:
        """Return the 16-bit antenna enable mask."""
        payload = await self._request(Command.GET_ANTENNA_MASK)
        require_minimum_length(payload, 2, "antenna")
        return payload[0] << 8 | payload[1]

    async def set_antenna_work_time(
        self, antenna: int, work_time: int, *, save: bool = True
    ) -> None:
        """Set the work time of one antenna.

        Raises:
            ValueError: The antenna number or the work time is out of
                range.
        """
        if not MIN_ANTENNA <= antenna <= MAX_ANTENNA:
            msg = f"antenna must be between {MIN_ANTENNA} and {MAX_ANTENNA}, got {antenna}"
            raise ValueError(msg)
        if not 0 <= work_time <= WORD_MAX:
            msg = f"work time must be between 0 and 65535, got {work_time}"
            raise ValueError(msg)
        payload = bytes((int(save) << 4 | antenna, work_time >> 8 & 0xFF, work_time & 0xFF))
        response = await self._request(Command.SET_ANTENNA_WORK_TIME, payload)
        _require_ack(response, Command.SET_ANTENNA_WORK_TIME)

    async def get_antenna_work_time(self, antenna: int) -> int:
        """Return the work time of one antenna.

        Raises:
            ValueError: The antenna number is out of range.
        """
        if not MIN_ANTENNA <= antenna <= MAX_ANTENNA:
            msg = f"antenna must be between {MIN_ANTENNA} and {MAX_ANTENNA}, got {antenna}"
            raise ValueError(msg)
        payload = await self._request(Command.GET_ANTENNA_WORK_TIME, bytes((antenna, 0x00)))
        require_status_header(payload, 4, 0x01, "antenna")
        return payload[2] << 8 | payload[3]

    async def set_fast_inventory_mode(self, *, enabled: bool) -> None:
        """Turn the fast inventory mode on or off."""
        response = await self._request(
            Command.SET_FAST_INVENTORY_MODE, bytes((0x01, int(enabled), 0x00))
        )
        _require_ack(response, Command.SET_FAST_INVENTORY_MODE)

    async def get_fast_inventory_mode(self) -> bool:
        """Return whether the fast inventory mode is on."""
        payload = await self._request(Command.GET_FAST_INVENTORY_MODE, b"\x00\x00")
        require_status_header(payload, 2, 0x01, "fast inventory mode")
        return payload[1] == 0x01

    async def soft_reset(self) -> None:
        """Reset the UHF module. The link may drop and reconnect."""
        response = await self._request(Command.SOFT_RESET)
        _require_ack(response, Command.SOFT_RESET)

    async def single_inventory(self) -> Tag | None:
        """Inventory once and return the tag, or None without a tag."""
        payload = await self._request(Command.SINGLE_INVENTORY, SINGLE_INVENTORY_PAYLOAD)
        if not payload:
            return None
        return parse_tag_record(payload, with_antenna=True, received_at=now_utc())

    async def start_inventory(self, *, phase: bool = False) -> None:
        """Start a continuous inventory.

        The reader sends no acknowledgement, this method waits the
        documented start delay and returns. A no-op when an inventory
        is already running.

        Args:
            phase: Report the tag phase in degrees in every sighting,
                the official document's phase reporting mode. The
                layout with TID or USER blocks enabled is inferred
                from the documented shape, verify against live
                traffic.
        """
        await self._ensure_connected()
        if self._inventory_active:
            return
        async with self._lock:
            transport = self._transport
            if transport is None:
                msg = "the link is closed"
                raise ChainwayConnectionError(msg)
            self._tag_queue = asyncio.Queue()
            payload = START_INVENTORY_PHASE_PAYLOAD if phase else START_INVENTORY_PAYLOAD
            transport.write(build_frame(Command.START_INVENTORY, payload))
            self._inventory_phase = phase
            self._inventory_active = True
            await asyncio.sleep(INVENTORY_START_DELAY)

    async def stop_inventory(self) -> None:
        """Stop a running continuous inventory. A no-op when idle."""
        if not self._inventory_active:
            return
        payload = await self._request(Command.STOP_INVENTORY, allow_during_inventory=True)
        _require_ack(payload, Command.STOP_INVENTORY)
        self._finish_inventory()
        queue = self._tag_queue
        self._tag_queue = None
        if queue is not None:
            queue.put_nowait(_LinkClosed(None))

    async def inventory(self, *, phase: bool = False) -> AsyncGenerator[Tag]:
        """Yield tag sightings from a continuous inventory run.

        Starts the scan on first iteration and stops it on exit. Close
        the iterator with :class:`contextlib.aclosing` when breaking out
        early, otherwise the stop frame is only sent once the generator
        is collected.

        Args:
            phase: Report the tag phase in degrees in every sighting.

        Raises:
            ChainwayConnectionError: The link dropped mid-scan.
        """
        await self.start_inventory(phase=phase)
        try:
            while True:
                queue = self._tag_queue
                if queue is None:
                    msg = "the link was lost"
                    raise ChainwayConnectionError(msg)
                item = await queue.get()
                if isinstance(item, _LinkClosed):
                    if item.error is not None:
                        raise item.error
                    return
                yield item
        finally:
            if self._inventory_active:
                with suppress(ChainwayError):
                    await self.stop_inventory()

    async def read_tag(
        self,
        bank: MemoryBank,
        word_address: int,
        word_count: int,
        *,
        access_password: bytes = b"\x00\x00\x00\x00",
        tag_filter: TagFilter | None = None,
    ) -> bytes:
        """Read from one tag memory bank.

        Args:
            bank: The bank to read from.
            word_address: Start address in 16-bit words.
            word_count: Number of 16-bit words to read.
            access_password: Four-byte tag access password.
            tag_filter: Selection filter, or None to let the reader
                pick the tag.

        Returns:
            The read data, ``word_count`` times two bytes.

        Raises:
            ValueError: The window or password is invalid.
            ChainwayResponseError: The reader reported a failure.
        """
        validate_word_window(word_address, word_count)
        tail = bytes(
            (
                bank,
                word_address >> 8 & 0xFF,
                word_address & 0xFF,
                word_count >> 8 & 0xFF,
                word_count & 0xFF,
            )
        )
        payload = build_tag_operation_payload(access_password, tag_filter, tail)
        response = await self._request(Command.READ_TAG, payload)
        _require_tag_success(response, Command.READ_TAG)
        require_minimum_length(response, 4, "read")
        words = response[2] << 8 | response[3]
        data = response[4:]
        if len(data) < words * 2:
            msg = f"read response promised {words * 2} data bytes, got {len(data)}"
            raise ChainwayResponseError(msg)
        return data[: words * 2]

    async def write_tag(
        self,
        bank: MemoryBank,
        word_address: int,
        data: bytes,
        *,
        access_password: bytes = b"\x00\x00\x00\x00",
        tag_filter: TagFilter | None = None,
    ) -> None:
        """Write to one tag memory bank.

        Raises:
            ValueError: The data length is odd or the window is
                invalid.
            ChainwayResponseError: The reader reported a failure.
        """
        if not data or len(data) % 2 != 0:
            msg = f"data must be a non-empty even number of bytes, got {len(data)}"
            raise ValueError(msg)
        validate_word_window(word_address, len(data) // 2)
        word_count = len(data) // 2
        tail = (
            bytes(
                (
                    bank,
                    word_address >> 8 & 0xFF,
                    word_address & 0xFF,
                    word_count >> 8 & 0xFF,
                    word_count & 0xFF,
                )
            )
            + data
        )
        payload = build_tag_operation_payload(access_password, tag_filter, tail)
        response = await self._request(Command.WRITE_TAG, payload)
        _require_tag_success(response, Command.WRITE_TAG)

    async def block_write_tag(
        self,
        bank: MemoryBank,
        word_address: int,
        data: bytes,
        *,
        access_password: bytes = b"\x00\x00\x00\x00",
        tag_filter: TagFilter | None = None,
    ) -> None:
        """Write to one tag memory bank with the block write command.

        Raises:
            ValueError: The data length is odd or the window is
                invalid.
            ChainwayResponseError: The reader reported a failure.
        """
        if not data or len(data) % 2 != 0:
            msg = f"data must be a non-empty even number of bytes, got {len(data)}"
            raise ValueError(msg)
        validate_word_window(word_address, len(data) // 2)
        word_count = len(data) // 2
        tail = (
            bytes(
                (
                    bank,
                    word_address >> 8 & 0xFF,
                    word_address & 0xFF,
                    word_count >> 8 & 0xFF,
                    word_count & 0xFF,
                )
            )
            + data
        )
        payload = build_tag_operation_payload(access_password, tag_filter, tail)
        response = await self._request(Command.BLOCK_WRITE_TAG, payload)
        _require_tag_success(response, Command.BLOCK_WRITE_TAG)

    async def block_erase_tag(
        self,
        bank: MemoryBank,
        word_address: int,
        word_count: int,
        *,
        access_password: bytes = b"\x00\x00\x00\x00",
        tag_filter: TagFilter | None = None,
    ) -> None:
        """Erase a window of one tag memory bank.

        Raises:
            ValueError: The window is invalid.
            ChainwayResponseError: The reader reported a failure.
        """
        validate_word_window(word_address, word_count)
        tail = bytes(
            (
                bank,
                word_address >> 8 & 0xFF,
                word_address & 0xFF,
                word_count >> 8 & 0xFF,
                word_count & 0xFF,
            )
        )
        payload = build_tag_operation_payload(access_password, tag_filter, tail)
        response = await self._request(Command.BLOCK_ERASE_TAG, payload)
        _require_tag_success(response, Command.BLOCK_ERASE_TAG)

    async def lock_tag(
        self,
        banks: Collection[LockBank],
        mode: LockMode,
        *,
        access_password: bytes = b"\x00\x00\x00\x00",
        tag_filter: TagFilter | None = None,
    ) -> None:
        """Lock tag memory banks with one lock mode.

        Raises:
            ChainwayResponseError: The reader reported a failure.
        """
        payload = build_tag_operation_payload(
            access_password, tag_filter, build_lock_code(banks_tuple(banks), mode)
        )
        response = await self._request(Command.LOCK_TAG, payload)
        _require_tag_success(response, Command.LOCK_TAG)

    async def kill_tag(
        self,
        kill_password: bytes,
        *,
        tag_filter: TagFilter | None = None,
    ) -> None:
        """Kill a tag with its four-byte kill password.

        Raises:
            ChainwayResponseError: The reader reported a failure.
        """
        payload = build_tag_operation_payload(kill_password, tag_filter, b"")
        response = await self._request(Command.KILL_TAG, payload)
        _require_tag_success(response, Command.KILL_TAG)

    async def read_collected_tags(self) -> CollectedTags:
        """Pull the tags collected in auto or trigger work mode."""
        payload = await self._request(Command.READ_COLLECTED_TAGS)
        return parse_collected_tags(payload)

    async def get_collected_tag_count(self) -> int:
        """Return how many collected tags the reader stores."""
        payload = await self._request(Command.FLASH_STORAGE, bytes((FlashSubcommand.ALL_COUNT,)))
        require_minimum_length(payload, 2, "collected count")
        return payload[0] << 8 | payload[1]

    async def get_new_collected_tag_count(self) -> int:
        """Return how many collected tags arrived since the last pull."""
        payload = await self._request(Command.FLASH_STORAGE, bytes((FlashSubcommand.NEW_COUNT,)))
        require_minimum_length(payload, 2, "collected count")
        return payload[0] << 8 | payload[1]

    async def delete_collected_tags(self) -> None:
        """Delete every collected tag from the reader storage."""
        payload = await self._request(Command.FLASH_STORAGE, bytes((FlashSubcommand.DELETE_ALL,)))
        require_minimum_length(payload, 2, "delete")
        if payload[0] != 0x00 or payload[1] != 0x00:
            msg = f"delete was not acknowledged, got payload {payload!r}"
            raise ChainwayResponseError(msg)

    async def read_collected_tags_from_flash(self) -> tuple[bytes, ...]:
        """Pull collected EPCs from the flash storage.

        The response layout follows the Android demo decode: a one
        byte record count, then per record one length byte and the raw
        EPC bytes. No SDK for the UR4 decodes it, so the shape stays
        unverified until live traffic confirms it.
        """
        payload = await self._request(
            Command.READ_FLASH_TAGS, bytes((FlashDataSubcommand.READ_ALL,))
        )
        return parse_flash_tags(payload)

    async def set_reader_address(self, address: ReaderAddress) -> None:
        """Set the reader IP and port, with optional mask and gateway."""
        payload = build_reader_address_payload(ConfigSubcommand.SET_READER_ADDRESS, address)
        response = await self._request(Command.CONFIG, payload)
        _require_ack(response, Command.CONFIG)

    async def get_reader_address(self) -> ReaderAddress:
        """Return the reader IP, port, mask and gateway."""
        payload = await self._request(Command.CONFIG, bytes((ConfigSubcommand.GET_READER_ADDRESS,)))
        return parse_reader_address(payload, ConfigSubcommand.GET_READER_ADDRESS)

    async def set_destination_address(self, address: ReaderAddress) -> None:
        """Set the UDP push destination for auto and trigger work modes."""
        payload = build_reader_address_payload(ConfigSubcommand.SET_DESTINATION_ADDRESS, address)
        response = await self._request(Command.CONFIG, payload)
        _require_ack(response, Command.CONFIG)

    async def get_destination_address(self) -> ReaderAddress:
        """Return the UDP push destination."""
        payload = await self._request(
            Command.CONFIG, bytes((ConfigSubcommand.GET_DESTINATION_ADDRESS,))
        )
        return parse_reader_address(payload, ConfigSubcommand.GET_DESTINATION_ADDRESS)

    async def set_work_mode(self, mode: WorkMode) -> None:
        """Set who drives the inventory."""
        response = await self._request(
            Command.CONFIG, bytes((ConfigSubcommand.SET_WORK_MODE, mode))
        )
        _require_ack(response, Command.CONFIG)

    async def get_work_mode(self) -> WorkMode:
        """Return who drives the inventory."""
        payload = await self._request(Command.CONFIG, bytes((ConfigSubcommand.GET_WORK_MODE,)))
        require_status_header(payload, 2, ConfigSubcommand.GET_WORK_MODE, "work")
        return WorkMode(payload[1])

    async def set_buzzer(self, *, enabled: bool) -> None:
        """Turn the buzzer on or off."""
        response = await self._request(
            Command.CONFIG, bytes((ConfigSubcommand.SET_BUZZER, int(enabled)))
        )
        _require_ack(response, Command.CONFIG)

    async def get_buzzer(self) -> bool:
        """Return whether the buzzer is on."""
        payload = await self._request(Command.CONFIG, bytes((ConfigSubcommand.GET_BUZZER,)))
        require_status_header(payload, 2, ConfigSubcommand.GET_BUZZER, "buzzer")
        return payload[1] == 0x01

    async def set_gpo(self, *, output_0: bool, output_1: bool, relay_closed: bool) -> None:
        """Set the GPO levels and the relay contact."""
        response = await self._request(
            Command.CONFIG,
            bytes((ConfigSubcommand.SET_GPO, int(output_0), int(output_1), int(relay_closed))),
        )
        _require_ack(response, Command.CONFIG)

    async def get_gpo(self) -> GpoState:
        """Return the GPO levels."""
        payload = await self._request(Command.CONFIG, bytes((ConfigSubcommand.GET_GPO,)))
        require_status_header(payload, 3, ConfigSubcommand.GET_GPO, "GPO")
        return GpoState(output_0=payload[1] == 0x01, output_1=payload[2] == 0x01)

    async def set_trigger_config(self, config: TriggerConfig) -> None:
        """Set the trigger work mode timing."""
        work_units = config.work_time_ms // 10
        interval_units = config.min_interval_ms // 10
        payload = bytes(
            (
                ConfigSubcommand.SET_TRIGGER_CONFIG,
                config.input,
                work_units >> 8 & 0xFF,
                work_units & 0xFF,
                interval_units >> 8 & 0xFF,
                interval_units & 0xFF,
                config.output,
                0x00,
            )
        )
        response = await self._request(Command.CONFIG, payload)
        _require_ack(response, Command.CONFIG)

    async def get_trigger_config(self) -> TriggerConfig:
        """Return the trigger work mode timing."""
        payload = await self._request(Command.CONFIG, bytes((ConfigSubcommand.GET_TRIGGER_CONFIG,)))
        require_status_header(payload, 7, ConfigSubcommand.GET_TRIGGER_CONFIG, "trigger")
        return TriggerConfig(
            input=TriggerInput(payload[1]),
            work_time_ms=(payload[2] << 8 | payload[3]) * 10,
            min_interval_ms=(payload[4] << 8 | payload[5]) * 10,
            output=OutputRoute(payload[6]),
        )

    async def set_volume(self, volume: int) -> None:
        """Set the buzzer volume.

        The Android SDK is the only source for the response and
        expects the subcommand echoed back, every other set command of
        the family answers with a bare acknowledgement, so both shapes
        are accepted.

        Raises:
            ValueError: The volume is out of range.
        """
        if not 0 <= volume <= BYTE_MAX:
            msg = f"volume must be between 0 and 255, got {volume}"
            raise ValueError(msg)
        response = await self._request(Command.CONFIG, bytes((ConfigSubcommand.SET_VOLUME, volume)))
        if response[:1] != b"\x01" and response != b"\x11\x01":
            msg = f"volume set was not acknowledged, got payload {response!r}"
            raise ChainwayResponseError(msg)

    async def get_volume(self) -> int:
        """Return the buzzer volume."""
        payload = await self._request(Command.CONFIG, bytes((ConfigSubcommand.GET_VOLUME,)))
        require_status_header(payload, 2, ConfigSubcommand.GET_VOLUME, "volume")
        return payload[1]

    async def scan_barcode(self) -> bytes | None:
        """Scan one barcode with the imager and return its bytes.

        A response without a barcode, the three byte form ``02 02 00``
        or a bare subcommand echo, returns None.
        """
        payload = await self._request(Command.PERIPHERAL, bytes((PeripheralSubcommand.BARCODE,)))
        require_status_header(payload, 1, PeripheralSubcommand.BARCODE, "barcode")
        if len(payload) < len(BARCODE_NO_READ_PAYLOAD) or payload == BARCODE_NO_READ_PAYLOAD:
            return None
        return payload[1:]

    async def beep(self, duration: int = 1) -> None:
        """Beep the buzzer once for ``duration`` time units.

        Raises:
            ValueError: The duration is out of range.
        """
        if not 0 <= duration <= BYTE_MAX:
            msg = f"duration must be between 0 and 255, got {duration}"
            raise ValueError(msg)
        response = await self._request(
            Command.PERIPHERAL,
            bytes((PeripheralSubcommand.BUZZER_DURATION, 0x01, duration)),
        )
        _require_ack(response, Command.PERIPHERAL)

    async def set_led(self, *, enabled: bool) -> None:
        """Turn the LED on or off."""
        state = 0x01 if enabled else 0x00
        response = await self._request(
            Command.PERIPHERAL,
            bytes((PeripheralSubcommand.LED, state, 0x00, 0x00, 0x00)),
        )
        _require_ack(response, Command.PERIPHERAL)

    async def blink_led(self, red: int, green: int, blue: int) -> None:
        """Blink the LED with color components.

        Raises:
            ValueError: A color component is out of range.
        """
        for name, component in (("red", red), ("green", green), ("blue", blue)):
            if not 0 <= component <= BYTE_MAX:
                msg = f"{name} must be between 0 and 255, got {component}"
                raise ValueError(msg)
        response = await self._request(
            Command.PERIPHERAL,
            bytes((PeripheralSubcommand.LED, 0x02, red, green, blue)),
        )
        _require_ack(response, Command.PERIPHERAL)

    async def jump_to_bootloader(self) -> None:
        """Reboot the module into the bootloader for a firmware update."""
        response = await self._request(Command.JUMP_TO_BOOTLOADER, BOOTLOADER_JUMP_PAYLOAD)
        _require_ack(response, Command.JUMP_TO_BOOTLOADER)

    async def start_update(self) -> None:
        """Start the firmware update after the bootloader jump."""
        response = await self._request(Command.START_UPDATE)
        _require_ack(response, Command.START_UPDATE)

    async def send_update_block(self, block: bytes) -> None:
        """Send one firmware block, padded to 64 bytes.

        Raises:
            ValueError: The block is longer than 64 bytes.
        """
        if len(block) > UPDATE_BLOCK_SIZE:
            msg = f"block must be at most {UPDATE_BLOCK_SIZE} bytes, got {len(block)}"
            raise ValueError(msg)
        response = await self._request(
            Command.UPDATE_BLOCK, block.ljust(UPDATE_BLOCK_SIZE, b"\x00")
        )
        _require_ack(response, Command.UPDATE_BLOCK)

    async def stop_update(self) -> None:
        """Stop the firmware update."""
        response = await self._request(Command.STOP_UPDATE)
        _require_ack(response, Command.STOP_UPDATE)

    async def _ensure_connected(self) -> None:
        if self._transport is None:
            await self.connect()

    async def _request(
        self,
        command: Command,
        payload: bytes = b"",
        *,
        allow_during_inventory: bool = False,
    ) -> bytes:
        """Send one request and return its response payload.

        Raises:
            ChainwayInventoryActiveError: A continuous inventory is
                running and the command is not stop inventory.
            ChainwayTimeoutError: No response arrived in time.
            ChainwayConnectionError: The link dropped while waiting.
        """
        await self._ensure_connected()
        if self._inventory_active and not allow_during_inventory:
            msg = "the reader only answers stop inventory while a continuous inventory runs"
            raise ChainwayInventoryActiveError(msg)
        async with self._lock:
            return await self._exchange(command, payload)

    async def _exchange(self, command: Command, payload: bytes) -> bytes:
        transport = self._transport
        if transport is None:
            msg = "the link is closed"
            raise ChainwayConnectionError(msg)
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bytes] = loop.create_future()
        self._pending = (command + 1, future)
        transport.write(build_frame(command, payload))
        try:
            async with asyncio.timeout(self.response_timeout):
                return await future
        except TimeoutError as err:
            msg = f"no response for command {command:#04x} within {self.response_timeout} seconds"
            raise ChainwayTimeoutError(msg) from err
        finally:
            self._pending = None

    def _handle_frame(self, command: int, payload: bytes) -> None:
        pending = self._pending
        if pending is not None and pending[0] == command:
            if not pending[1].done():
                pending[1].set_result(payload)
            return
        if command == Command.TAG_STREAM:
            self._deliver_tag(payload)
            return
        _LOGGER.debug("dropping unexpected frame with command %#04x", command)

    def _deliver_tag(self, payload: bytes) -> None:
        try:
            tag = parse_tag_record(
                payload,
                with_antenna=True,
                received_at=now_utc(),
                with_phase=self._inventory_phase,
            )
        except ChainwayResponseError as err:
            _LOGGER.debug("dropping malformed tag record: %s", err)
            return
        queue = self._tag_queue
        if queue is not None:
            queue.put_nowait(tag)
            return
        callback = self.on_tag
        if callback is not None:
            self._run_callback(callback, tag)
            return
        _LOGGER.debug("tag arrived outside an inventory run without an on_tag callback")

    def _run_callback(
        self,
        callback: Callable[[CallbackArgument], Awaitable[None] | None],
        argument: CallbackArgument,
    ) -> None:
        result = callback(argument)
        if isinstance(result, Coroutine):
            task = asyncio.create_task(result)
            self._callback_tasks.add(task)
            task.add_done_callback(self._callback_tasks.discard)
            task.add_done_callback(_consume_task_exception)

    def _schedule_drop_link(self, exc: Exception | None) -> None:
        task = asyncio.create_task(self._drop_link(exc))
        self._callback_tasks.add(task)
        task.add_done_callback(self._callback_tasks.discard)
        task.add_done_callback(_consume_task_exception)

    async def _drop_link(self, exc: Exception | None) -> None:
        async with self._lifecycle_lock:
            if self._transport is None:
                return
            await self._teardown()
        error = (
            exc if exc is not None else ChainwayConnectionError("the link was closed by the reader")
        )
        callback = self.on_connection_lost
        if callback is not None:
            self._run_callback(callback, error)

    def _finish_inventory(self) -> None:
        self._inventory_active = False
        self._inventory_phase = False

    async def _teardown(self) -> None:
        current = asyncio.current_task()
        if self._maintenance_task is not None and self._maintenance_task is not current:
            self._maintenance_task.cancel()
            await asyncio.gather(self._maintenance_task, return_exceptions=True)
        self._maintenance_task = None
        transport = self._transport
        self._transport = None
        self._protocol = None
        self._finish_inventory()
        queue = self._tag_queue
        self._tag_queue = None
        pending = self._pending
        self._pending = None
        error = ChainwayConnectionError("the link was lost")
        if pending is not None and not pending[1].done():
            pending[1].set_exception(error)
        if queue is not None:
            queue.put_nowait(_LinkClosed(error))
        if transport is not None:
            transport.close()
            with suppress(Exception):
                await transport.wait_closed()

    async def _maintenance_loop(self) -> None:
        while True:
            await asyncio.sleep(MAINTENANCE_TICK)
            protocol = self._protocol
            if protocol is None:
                return
            now = time.monotonic()
            if (
                not self._inventory_active
                and now - protocol.last_activity >= self.dead_link_timeout
            ):
                await self._drop_link(ChainwayConnectionError("the link went silent"))
                return
            if now - self._last_keepalive >= self.keepalive_interval:
                self._last_keepalive = now
                if self._inventory_active:
                    transport = self._transport
                    if transport is not None:
                        transport.write(INVENTORY_KEEPALIVE_BYTE)
                else:
                    with suppress(ChainwayError):
                        await self._request(Command.GET_VERSION)
