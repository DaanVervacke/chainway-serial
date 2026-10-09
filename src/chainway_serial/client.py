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
    AUTH_CHALLENGE_SIZE,
    AUTH_KEY_AND_DATA_SIZE,
    BARCODE_NO_READ_PAYLOAD,
    BYTE_MAX,
    COLLECTED_TAGS_FULL_PAYLOAD,
    CONFIG_COMMIT_DELAY,
    CONFIG_COMMITTING_SUBCOMMANDS,
    DEFAULT_BAUDRATE,
    DEFAULT_DEAD_LINK_TIMEOUT,
    DEFAULT_KEEPALIVE_INTERVAL,
    DEFAULT_RESPONSE_TIMEOUT,
    DWORD_MAX,
    FREQUENCY_BYTES,
    INVENTORY_KEEPALIVE_BYTE,
    INVENTORY_START_DELAY,
    MAINTENANCE_TICK,
    MAX_ANTENNA,
    MAX_FIXED_FREQUENCY_KHZ,
    MAX_POWER_DBM,
    MIN_ANTENNA,
    MIN_POWER_DBM,
    MODULE_WORK_TIME_BYTES,
    MODULE_WORK_TIME_MAX,
    RESTORE_COMMIT_DELAY,
    SINGLE_INVENTORY_PAYLOAD,
    START_INVENTORY_FREQUENCY_PAYLOAD,
    START_INVENTORY_PAYLOAD,
    START_INVENTORY_PHASE_AND_FREQUENCY_PAYLOAD,
    START_INVENTORY_PHASE_PAYLOAD,
    STATUS_OK,
    TAG_ERROR_MEANINGS,
    TAG_SENSOR_VOLTAGE_FACTOR,
    TAG_SUCCESS,
    TEMP_CODE_MAX,
    UNSUPPORTED_REPLY,
    UPDATE_BLOCK_SIZE,
    VERIFY_VOLTAGE_PAYLOAD,
    WORD_MAX,
    Command,
    ConfigSubcommand,
    FlashDataSubcommand,
    FlashSubcommand,
    PeripheralSubcommand,
    ProtocolTypeSelector,
    SensorSubcommand,
    TagSensorSubcommand,
)
from .exceptions import (
    ChainwayConnectionError,
    ChainwayError,
    ChainwayInventoryActiveError,
    ChainwayResponseError,
    ChainwayTimeoutError,
    ChainwayUnsupportedCommandError,
)
from .frames import build_frame
from .models import (
    AntennaPower,
    AntennaState,
    BootloaderTarget,
    CollectedTags,
    CollectedTagsFull,
    FirmwareVersion,
    Gen2Parameters,
    GpiState,
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
    UartBaudRate,
    WorkMode,
)
from .parsers import (
    banks_tuple,
    build_deactivate_payload,
    build_filter_payload,
    build_lock_code,
    build_module_parameter_payload,
    build_power_payload,
    build_reader_address_payload,
    build_sensor_payload,
    build_tag_operation_payload,
    build_tag_sensor_payload,
    now_utc,
    pack_gen2_parameters,
    parse_antenna_connection_state,
    parse_collected_tags,
    parse_collected_tags_full,
    parse_device_id,
    parse_fixed_frequency,
    parse_flash_tags,
    parse_module_parameter,
    parse_power_records,
    parse_reader_address,
    parse_return_loss,
    parse_tag_record,
    parse_tag_sensor_value,
    parse_tag_temperatures,
    parse_temperature,
    parse_version,
    parse_voltage,
    parse_word_data,
    require_minimum_length,
    require_status_header,
    unpack_gen2_parameters,
    validate_block_window,
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


def _link_error(exc: Exception | None) -> ChainwayError:
    if exc is None:
        return ChainwayConnectionError("the link was closed by the reader")
    if isinstance(exc, ChainwayError):
        return exc
    error = ChainwayConnectionError(f"the link failed: {exc}")
    error.__cause__ = exc
    return error


def _require_ack(payload: bytes, command: Command) -> None:
    if not payload or payload[0] != STATUS_OK:
        msg = f"command {command:#04x} was not acknowledged, got payload {payload!r}"
        raise ChainwayResponseError(msg)


def _reject_unsupported(payload: bytes, command: Command) -> None:
    if payload == UNSUPPORTED_REPLY:
        msg = f"the reader does not support command {command:#04x}, it answered a bare 00 byte"
        raise ChainwayUnsupportedCommandError(msg)


def _require_tag_success(payload: bytes, command: Command) -> None:
    if payload[:2] == TAG_SUCCESS:
        return
    _reject_unsupported(payload, command)
    if len(payload) < len(TAG_SUCCESS):
        msg = f"command {command:#04x} failed with payload {payload!r}"
        raise ChainwayResponseError(msg)
    code = payload[1]
    msg = f"command {command:#04x} failed with error code {code:#04x}"
    meaning = TAG_ERROR_MEANINGS.get(code)
    if meaning is not None:
        msg = f"{msg}: {meaning}"
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
        self._inventory_frequency = False
        self._tag_queue: asyncio.Queue[Tag | _LinkClosed] | None = None
        self._maintenance_task: asyncio.Task[None] | None = None
        self._callback_tasks: set[asyncio.Task[None]] = set()
        self._last_keepalive = 0.0
        self._link_reported = False
        self._link_lost_error: Exception | None = None
        self._link_answered = False
        self._quiet_until = 0.0
        self._discarding_tags = False

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
        :meth:`disconnect`. The reader keeps scanning when a link
        closes during a continuous inventory, so this method sends stop
        inventory first and drops the tag records that arrive before
        the answer. A reader that does not answer, for example while it
        boots, delays the return by the response timeout. When a link
        fails before it answered anything, the next request opens it
        again and sends once more, because the UR4 resets some fresh TCP
        connections.

        Raises:
            ChainwayConnectionError: The URL could not be opened.
        """
        async with self._lifecycle_lock:
            if self._transport is not None:
                return
            protocol = ChainwayProtocol(
                self._handle_frame, lambda exc: self._schedule_drop_link(exc, protocol)
            )
            loop = asyncio.get_running_loop()
            self._discarding_tags = True
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
                self._discarding_tags = False
                msg = f"could not open {self.url}: {err}"
                raise ChainwayConnectionError(msg) from err
            self._transport = transport
            self._protocol = protocol
            self._link_reported = False
            self._link_lost_error = None
            self._link_answered = False
            await self._stop_leftover_scan()
            self._last_keepalive = time.monotonic()
            self._maintenance_task = asyncio.create_task(self._maintenance_loop())

    async def _stop_leftover_scan(self) -> None:
        try:
            async with self._lock:
                with suppress(ChainwayTimeoutError):
                    await self._exchange(Command.STOP_INVENTORY, b"")
        finally:
            self._discarding_tags = False

    async def disconnect(self) -> None:
        """Close the link and stop the keepalive loop.

        Pending requests fail with
        :class:`chainway_serial.ChainwayConnectionError`. A no-op when
        already closed.
        """
        self._link_reported = True
        self._link_lost_error = None
        transport = await self._shutdown()
        await self._release(transport)

    async def _shutdown(self) -> BaseSerialTransport | None:
        """Tear the link state down under the lifecycle lock.

        Returns the transport for the caller to close outside the
        lock, because ``wait_closed`` can block and must never hold
        the lock.
        """
        async with self._lifecycle_lock:
            return await self._teardown()

    async def _release(self, transport: BaseSerialTransport | None) -> None:
        if transport is None:
            return
        transport.close()
        with suppress(Exception):
            async with asyncio.timeout(1.0):
                await transport.wait_closed()

    async def __aenter__(self) -> Self:
        """Open the link and return the client."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the link when the context exits."""
        await self.disconnect()

    async def get_version(self) -> FirmwareVersion:
        """Return the UHF module firmware version."""
        payload = await self._request(Command.GET_VERSION)
        return parse_version(payload)

    async def get_stm32_version(self) -> FirmwareVersion:
        """Return the STM32 microcontroller version."""
        payload = await self._request(Command.STM32_VERSION)
        return parse_version(payload)

    async def get_hardware_version(self) -> FirmwareVersion:
        """Return the UHF module hardware version.

        On an Ex10 module this is the version of the Ex10 chip.
        """
        payload = await self._request(Command.HARDWARE_VERSION)
        return parse_version(payload)

    async def get_device_id(self) -> bytes:
        """Return the four-byte device ID.

        The UR4 mainboard answers with bytes 3 to 6 of the reader MAC
        address.
        """
        payload = await self._request(Command.GET_DEVICE_ID)
        return parse_device_id(payload)

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

    async def verify_voltage(self) -> int:
        """Return the module supply voltage reading as a raw signed value.

        The native library names the command voltage verification. No
        SDK documents the unit of the value.
        """
        payload = await self._request(Command.VERIFY_VOLTAGE, VERIFY_VOLTAGE_PAYLOAD)
        return parse_voltage(payload)

    async def set_module_parameter(self, param_type: int, param_id: int, data: bytes) -> None:
        """Write one module parameter.

        Args:
            param_type: The one byte parameter type.
            param_id: The four byte parameter ID.
            data: Exactly four bytes of parameter data.

        Raises:
            ValueError: A field does not fit its wire size.
            ChainwayResponseError: The reader did not acknowledge the
                write.
        """
        payload = build_module_parameter_payload(param_type, param_id, data)
        response = await self._request(Command.SET_PARAM, payload)
        _require_ack(response, Command.SET_PARAM)

    async def get_module_parameter(self, param_type: int, param_id: int) -> bytes:
        """Read one module parameter and return its four data bytes.

        Only the Linux native library builds the command and no SDK
        decodes the reply, so the reply shape follows the disassembly.

        Raises:
            ValueError: A field does not fit its wire size.
            ChainwayResponseError: The reply is truncated or echoes a
                different parameter ID.
        """
        payload = build_module_parameter_payload(param_type, param_id, None)
        response = await self._request(Command.GET_PARAM, payload)
        return parse_module_parameter(response, param_id)

    async def set_temperature_protect(self, value: int) -> None:
        """Set the module temperature protection value.

        The payload is one byte, the sources disagree whether it
        carries a flag or a temperature value.

        Raises:
            ValueError: The value does not fit one byte.
        """
        if not 0 <= value <= BYTE_MAX:
            msg = f"temperature protect value must be between 0 and 255, got {value}"
            raise ValueError(msg)
        response = await self._request(Command.SET_TEMPERATURE_PROTECT, bytes((value,)))
        _require_ack(response, Command.SET_TEMPERATURE_PROTECT)

    async def get_temperature_protect(self) -> int:
        """Return the module temperature protection value."""
        payload = await self._request(Command.GET_TEMPERATURE_PROTECT)
        require_status_header(payload, 2, STATUS_OK, "temperature protect")
        return payload[1]

    async def set_module_work_time(self, value: int) -> None:
        """Set the module work time.

        The request carries the value in five bytes, the response of
        the get form returns four, and no source documents the unit.

        Raises:
            ValueError: The value does not fit five bytes.
        """
        if not 0 <= value <= MODULE_WORK_TIME_MAX:
            msg = f"work time must be within 0 to {MODULE_WORK_TIME_MAX}, got {value}"
            raise ValueError(msg)
        response = await self._request(
            Command.SET_MODULE_WORK_TIME, value.to_bytes(MODULE_WORK_TIME_BYTES)
        )
        _require_ack(response, Command.SET_MODULE_WORK_TIME)

    async def get_module_work_time(self) -> int:
        """Return the module work time."""
        payload = await self._request(Command.GET_MODULE_WORK_TIME)
        require_status_header(payload, 5, STATUS_OK, "work time")
        return int.from_bytes(payload[1:5])

    async def set_dual_single_mode(self, mode: int, *, save: bool = True) -> None:
        """Set the dual single mode of the module.

        No source documents the mode values, so the raw byte passes
        through.

        Raises:
            ValueError: The mode does not fit one byte.
        """
        if not 0 <= mode <= BYTE_MAX:
            msg = f"mode must be between 0 and 255, got {mode}"
            raise ValueError(msg)
        response = await self._request(Command.SET_DUAL_SINGLE_MODE, bytes((int(save), mode)))
        _require_ack(response, Command.SET_DUAL_SINGLE_MODE)

    async def get_dual_single_mode(self) -> int:
        """Return the dual single mode of the module."""
        payload = await self._request(Command.GET_DUAL_SINGLE_MODE)
        require_status_header(payload, 2, STATUS_OK, "dual single mode")
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

    async def set_rf_power(self, power_dbm: float, *, antenna: int = 1, save: bool = True) -> None:
        """Set the transmit and receive power of one antenna.

        Args:
            power_dbm: Power in dBm applied to both directions.
            antenna: One-based antenna number.
            save: Store the setting across a power cycle.

        Raises:
            ValueError: The antenna number or the power value is out
                of range.
        """
        if not MIN_POWER_DBM <= power_dbm <= MAX_POWER_DBM:
            msg = f"power must be between {MIN_POWER_DBM} and {MAX_POWER_DBM} dBm, got {power_dbm}"
            raise ValueError(msg)
        payload = build_power_payload(antenna, power_dbm, power_dbm, save=save)
        response = await self._request(Command.SET_POWER, payload)
        _require_ack(response, Command.SET_POWER)

    async def set_antenna_power(
        self,
        antenna: int,
        read_power_dbm: float,
        write_power_dbm: float,
        *,
        save: bool = True,
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
        payload = build_power_payload(antenna, read_power_dbm, write_power_dbm, save=save)
        response = await self._request(Command.SET_POWER, payload)
        _require_ack(response, Command.SET_POWER)

    async def get_rf_power(self) -> tuple[AntennaPower, ...]:
        """Return the read and write power of every antenna."""
        payload = await self._request(Command.GET_POWER)
        return parse_power_records(payload)

    async def set_fixed_frequency(self, frequency_khz: int) -> None:
        """Pin the reader to one frequency.

        The setting lasts until power off.

        Raises:
            ValueError: The frequency does not fit the 3-byte field.
        """
        if not 1 <= frequency_khz <= MAX_FIXED_FREQUENCY_KHZ:
            msg = f"frequency must be at most {MAX_FIXED_FREQUENCY_KHZ} kHz, got {frequency_khz}"
            raise ValueError(msg)
        payload = b"\x01" + frequency_khz.to_bytes(FREQUENCY_BYTES)
        response = await self._request(Command.SET_FIXED_FREQUENCY, payload)
        _require_ack(response, Command.SET_FIXED_FREQUENCY)

    async def get_fixed_frequency(self) -> tuple[int, ...]:
        """Return the fixed frequency table in kHz.

        The module currently supports one frequency, the table
        shape allows more.
        """
        payload = await self._request(Command.GET_FIXED_FREQUENCY)
        return parse_fixed_frequency(payload)

    async def set_region(self, region: Region, *, save: bool = True) -> None:
        """Set the regulatory frequency region."""
        payload = bytes((int(save), region))
        response = await self._request(Command.SET_REGION, payload)
        _require_ack(response, Command.SET_REGION)

    async def get_region(self) -> Region:
        """Return the regulatory frequency region."""
        payload = await self._request(Command.GET_REGION)
        require_status_header(payload, 2, STATUS_OK, "region")
        return Region(payload[1])

    async def set_carrier_wave(self, *, enabled: bool) -> None:
        """Turn the continuous carrier wave on or off."""
        response = await self._request(Command.SET_CARRIER_WAVE, bytes((int(enabled),)))
        _require_ack(response, Command.SET_CARRIER_WAVE)

    async def get_return_loss(self) -> tuple[ReturnLoss, ...]:
        """Return the return loss of every antenna port in dB.

        A port reported as 0 is not enabled, or has no antenna
        connected on a single-port module. On a UR4 the first port
        reads 1 to 2 dB with the antenna jack open and 10 to 16 dB
        with an antenna attached, and ports 2 to 4 read 0.
        """
        payload = await self._request(Command.GET_RETURN_LOSS)
        return parse_return_loss(payload)

    async def set_gen2_parameters(self, parameters: Gen2Parameters) -> None:
        """Set the Gen2 inventory parameters.

        The setting lasts until power off.
        """
        response = await self._request(
            Command.SET_GEN2_PARAMETERS, pack_gen2_parameters(parameters)
        )
        _require_ack(response, Command.SET_GEN2_PARAMETERS)

    async def get_gen2_parameters(self) -> Gen2Parameters:
        """Return the Gen2 inventory parameters."""
        payload = await self._request(Command.GET_GEN2_PARAMETERS)
        return unpack_gen2_parameters(payload)

    async def set_uart_baudrate(self, baudrate: UartBaudRate) -> None:
        """Set the internal UART baud rate, applied at the next power cycle.

        The code sets the link between the mainboard and the UHF module,
        and the mainboard moves the host port with it. The reader keeps
        talking at the current rate until it reboots, and the setting
        persists across power loss.

        Raises:
            ValueError: The code is not a :class:`UartBaudRate` member.
                Other codes the module accepts leave it unreachable.
        """
        code = UartBaudRate(baudrate)
        response = await self._request(Command.SET_UART_BAUDRATE, bytes((code,)))
        _require_ack(response, Command.SET_UART_BAUDRATE)

    async def get_uart_baudrate(self) -> UartBaudRate:
        """Return the pending UART baud rate code.

        Raises:
            ChainwayResponseError: The module reports a code outside
                :class:`UartBaudRate`, such as 0x01 for 57600. The
                mainboard does not follow that rate, so the module
                becomes unreachable at the next power cycle unless
                :meth:`set_uart_baudrate` stores a supported code first.
        """
        payload = await self._request(Command.GET_UART_BAUDRATE)
        require_status_header(payload, 2, STATUS_OK, "UART baud rate")
        try:
            return UartBaudRate(payload[1])
        except ValueError as err:
            msg = (
                f"the module reports internal baud code {payload[1]:#04x}, which the mainboard"
                " does not follow. Store UartBaudRate.BAUD_115200 before the next power cycle"
            )
            raise ChainwayResponseError(msg) from err

    async def set_rf_link(self, mode: RfLink, *, save: bool = True) -> None:
        """Set the recommended RF link combination."""
        payload = bytes((0x00, int(save), mode))
        response = await self._request(Command.SET_RF_LINK, payload)
        _require_ack(response, Command.SET_RF_LINK)

    async def get_rf_link(self) -> RfLink:
        """Return the recommended RF link combination."""
        payload = await self._request(Command.GET_RF_LINK, b"\x00\x00")
        require_status_header(payload, 3, STATUS_OK, "RF")
        return RfLink(payload[2])

    async def set_fast_id(self, *, enabled: bool) -> None:
        """Turn FastID on or off.

        The setting lasts until power off.
        """
        response = await self._request(Command.SET_FAST_ID, bytes((int(enabled), 0x00)))
        _require_ack(response, Command.SET_FAST_ID)

    async def get_fast_id(self) -> bool:
        """Return whether FastID is on."""
        payload = await self._request(Command.GET_FAST_ID, b"\x00\x00")
        require_status_header(payload, 2, STATUS_OK, "FastID")
        return payload[1] == 0x01

    async def set_tag_focus(self, *, enabled: bool) -> None:
        """Turn TagFocus on or off.

        The setting lasts until power off.
        """
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
        require_status_header(payload, 4, STATUS_OK, "inventory")
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
        require_status_header(payload, 4, STATUS_OK, "antenna")
        return payload[2] << 8 | payload[3]

    async def set_fast_inventory_mode(self, *, enabled: bool, save: bool = True) -> None:
        """Turn the fast inventory mode on or off."""
        response = await self._request(
            Command.SET_FAST_INVENTORY_MODE, bytes((int(save), int(enabled), 0x00))
        )
        _require_ack(response, Command.SET_FAST_INVENTORY_MODE)

    async def get_fast_inventory_mode(self) -> bool:
        """Return whether the fast inventory mode is on."""
        payload = await self._request(Command.GET_FAST_INVENTORY_MODE, b"\x00\x00")
        require_status_header(payload, 2, STATUS_OK, "fast inventory mode")
        return payload[1] == 0x01

    async def software_reset(self) -> None:
        """Reboot the reader.

        The UR4 mainboard acknowledges and then reboots the whole
        reader, which prints its boot console on the serial port.
        Over serial, commands sent during the reboot, about two
        seconds, time out. Over TCP the socket stays silent and a new
        connection works again after 11 to 31 seconds.
        """
        response = await self._request(Command.SOFTWARE_RESET)
        _require_ack(response, Command.SOFTWARE_RESET)

    async def restore_factory_settings(self) -> None:
        """Restore the factory settings of the UHF module and the mainboard.

        On a UR4 the mainboard also resets its own settings: the buzzer
        turns back on, the trigger parameters return to their defaults
        and the work mode returns to command mode. The reader address
        returns to 192.168.99.202, port 8888, at once, so a TCP link
        to any other address drops. The SDKs call the same opcode the
        soft reset.
        The module drops every request for about 1.5 seconds after the
        acknowledgement, so the next command waits that long.
        """
        response = await self._request(Command.RESTORE_FACTORY_SETTINGS)
        _require_ack(response, Command.RESTORE_FACTORY_SETTINGS)
        self._quiet_until = time.monotonic() + RESTORE_COMMIT_DELAY

    async def single_inventory(self) -> Tag | None:
        """Inventory once and return the tag, or None without a tag."""
        payload = await self._request(Command.SINGLE_INVENTORY, SINGLE_INVENTORY_PAYLOAD)
        if not payload:
            return None
        return parse_tag_record(payload, with_antenna=True, received_at=now_utc())

    async def start_inventory(self, *, phase: bool = False, frequency: bool = False) -> None:
        """Start a continuous inventory.

        The reader sends no acknowledgement, this method waits the
        documented start delay and returns. A no-op when an inventory
        is already running. The two payload bytes select the
        reporting mode: the SDKs send ``00 00`` for a normal scan,
        and the 2025 Java SDK defines ``FF FF`` for phase reporting,
        ``FF FE`` for frequency point reporting and ``FF FD`` for
        both.

        Args:
            phase: Report the tag phase in degrees, 0 to 359, in every
                sighting. With phase reporting alone the reader leaves
                the TID and USER blocks out of the sightings.
            frequency: Report the channel frequency in kHz in every
                sighting.
        """
        await self._ensure_connected()
        async with self._lock:
            if self._inventory_active:
                return
            await self._wait_for_commit()
            transport = self._transport
            if transport is None:
                msg = "the link is closed"
                raise ChainwayConnectionError(msg)
            self._tag_queue = asyncio.Queue()
            if phase and frequency:
                payload = START_INVENTORY_PHASE_AND_FREQUENCY_PAYLOAD
            elif phase:
                payload = START_INVENTORY_PHASE_PAYLOAD
            elif frequency:
                payload = START_INVENTORY_FREQUENCY_PAYLOAD
            else:
                payload = START_INVENTORY_PAYLOAD
            self._write(transport, build_frame(Command.START_INVENTORY, payload))
            self._inventory_phase = phase
            self._inventory_frequency = frequency
            self._inventory_active = True
            await asyncio.sleep(INVENTORY_START_DELAY)

    async def stop_inventory(self) -> None:
        """Stop a running continuous inventory. A no-op when idle.

        The scan state clears and the iterator is released even when
        the stop command fails. The command error still propagates
        to the caller.

        Raises:
            ChainwayTimeoutError: The reader did not acknowledge the
                stop in time.
            ChainwayResponseError: The reader did not acknowledge the
                stop.
            ChainwayConnectionError: The link dropped while stopping.
        """
        if not self._inventory_active:
            return
        try:
            payload = await self._request(Command.STOP_INVENTORY, allow_during_inventory=True)
            _require_ack(payload, Command.STOP_INVENTORY)
        finally:
            self._finish_inventory()
            queue = self._tag_queue
            self._tag_queue = None
            if queue is not None:
                queue.put_nowait(_LinkClosed(None))

    async def inventory(
        self, *, phase: bool = False, frequency: bool = False
    ) -> AsyncGenerator[Tag]:
        """Yield tag sightings from a continuous inventory run.

        Starts the scan on first iteration and stops it on exit. Close
        the iterator with :class:`contextlib.aclosing` when breaking out
        early, otherwise the stop frame is only sent once the generator
        is collected.

        Args:
            phase: Report the tag phase in degrees in every sighting.
            frequency: Report the channel frequency in kHz in every
                sighting.

        Raises:
            ChainwayConnectionError: The link dropped mid-scan.
        """
        await self.start_inventory(phase=phase, frequency=frequency)
        queue = self._tag_queue
        if queue is None:
            msg = "the link was lost"
            raise ChainwayConnectionError(msg)
        try:
            while True:
                item = await queue.get()
                if isinstance(item, _LinkClosed):
                    if item.error is not None:
                        raise item.error
                    return
                yield item
        finally:
            if self._inventory_active and self._tag_queue is queue:
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
        return parse_word_data(response, "read")

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

    async def authenticate_tag(
        self,
        challenge: bytes,
        *,
        key_id: int = 0x00,
        access_password: bytes = b"\x00\x00\x00\x00",
        tag_filter: TagFilter | None = None,
    ) -> bytes:
        """Authenticate one tag with the Gen2 v2.0 Authenticate command.

        Args:
            challenge: The ten-byte IChallenge_TAM1 data.
            key_id: The key ID, the default is 0.
            access_password: Four-byte tag access password.
            tag_filter: Selection filter, or None to let the reader
                pick the tag.

        Returns:
            The returned data, eight words on success.

        Raises:
            ValueError: The challenge is not ten bytes or the key
                ID does not fit one byte.
            ChainwayResponseError: The reader reported a failure.
        """
        if len(challenge) != AUTH_CHALLENGE_SIZE:
            msg = f"challenge must be {AUTH_CHALLENGE_SIZE} bytes, got {len(challenge)}"
            raise ValueError(msg)
        if not 0 <= key_id <= BYTE_MAX:
            msg = f"key ID must be between 0 and 255, got {key_id}"
            raise ValueError(msg)
        tail = bytes((AUTH_KEY_AND_DATA_SIZE, key_id)) + challenge
        payload = build_tag_operation_payload(access_password, tag_filter, tail)
        response = await self._request(Command.AUTHENTICATE_TAG, payload)
        _require_tag_success(response, Command.AUTHENTICATE_TAG)
        return parse_word_data(response, "authenticate")

    async def set_protected_mode(
        self,
        *,
        protected: bool,
        short_range: bool,
        access_password: bytes = b"\x00\x00\x00\x00",
        tag_filter: TagFilter | None = None,
    ) -> None:
        """Set the protected mode and the short range mode of one tag.

        The 2025 Java SDK is the only source and documents no mode
        semantics.

        Args:
            protected: Turn the protected mode on or off.
            short_range: Turn the short range mode on or off.
            access_password: Four-byte tag access password.
            tag_filter: Selection filter, or None to let the reader
                pick the tag.

        Raises:
            ChainwayResponseError: The reader did not acknowledge the
                command.
        """
        tail = bytes((int(protected), int(short_range)))
        payload = build_tag_operation_payload(access_password, tag_filter, tail)
        response = await self._request(Command.SET_PROTECTED_MODE, payload)
        _require_ack(response, Command.SET_PROTECTED_MODE)

    async def read_block_permalock(
        self,
        bank: MemoryBank,
        block_ptr: int,
        block_range: int,
        *,
        access_password: bytes = b"\x00\x00\x00\x00",
        tag_filter: TagFilter | None = None,
    ) -> bytes:
        """Read the permalock status of one tag memory bank.

        Args:
            bank: The bank to read the permalock status from.
            block_ptr: Block start address, in windows of 16
                blocks of 8 bytes.
            block_range: Number of 16-block windows to read.
            access_password: Four-byte tag access password.
            tag_filter: Selection filter, or None to let the reader
                pick the tag.

        Returns:
            The per-block permalock bits, ``block_range`` words.

        Raises:
            ValueError: The window is invalid.
            ChainwayResponseError: The reader reported a failure.
        """
        validate_block_window(block_ptr, block_range)
        tail = bytes(
            (
                0x00,
                bank,
                block_ptr >> 8 & 0xFF,
                block_ptr & 0xFF,
                block_range >> 8 & 0xFF,
                block_range & 0xFF,
            )
        )
        payload = build_tag_operation_payload(access_password, tag_filter, tail)
        response = await self._request(Command.BLOCK_PERMALOCK_TAG, payload)
        _require_tag_success(response, Command.BLOCK_PERMALOCK_TAG)
        data = response[2:]
        if len(data) < block_range * 2:
            msg = f"block permalock response promised {block_range * 2} data bytes, got {len(data)}"
            raise ChainwayResponseError(msg)
        return data[: block_range * 2]

    async def set_block_permalock(
        self,
        bank: MemoryBank,
        block_ptr: int,
        block_range: int,
        mask: int,
        *,
        access_password: bytes = b"\x00\x00\x00\x00",
        tag_filter: TagFilter | None = None,
    ) -> None:
        """Permalock blocks of one tag memory bank.

        Args:
            bank: The bank to permalock blocks of.
            block_ptr: Block start address, in windows of 16
                blocks of 8 bytes.
            block_range: Number of 16-block windows to permalock.
            mask: The 16-bit block mask, the high bit selects the
                first block of the window.
            access_password: Four-byte tag access password.
            tag_filter: Selection filter, or None to let the reader
                pick the tag.

        Raises:
            ValueError: The window or the mask is invalid.
            ChainwayResponseError: The reader reported a failure.
        """
        validate_block_window(block_ptr, block_range)
        if not 0 <= mask <= WORD_MAX:
            msg = f"mask must be between 0 and 65535, got {mask}"
            raise ValueError(msg)
        tail = bytes(
            (
                0x01,
                bank,
                block_ptr >> 8 & 0xFF,
                block_ptr & 0xFF,
                block_range >> 8 & 0xFF,
                block_range & 0xFF,
                mask >> 8 & 0xFF,
                mask & 0xFF,
            )
        )
        payload = build_tag_operation_payload(access_password, tag_filter, tail)
        response = await self._request(Command.BLOCK_PERMALOCK_TAG, payload)
        _require_tag_success(response, Command.BLOCK_PERMALOCK_TAG)

    async def set_qt(
        self,
        qt_data: int,
        *,
        access_password: bytes = b"\x00\x00\x00\x00",
        tag_filter: TagFilter | None = None,
    ) -> None:
        """Set the Impinj Monza QT configuration of one tag.

        The opcode comes from the 2024 native library. The 2025 Java
        SDK uses the same opcode for a margin read with a different
        payload, so which command the current firmware runs is
        unverified.

        Args:
            qt_data: The one byte QT control value.
            access_password: Four-byte tag access password.
            tag_filter: Selection filter, or None to let the reader
                pick the tag.

        Raises:
            ValueError: The QT value does not fit one byte.
            ChainwayResponseError: The reader did not acknowledge the
                write.
        """
        if not 0 <= qt_data <= BYTE_MAX:
            msg = f"QT value must be between 0 and 255, got {qt_data}"
            raise ValueError(msg)
        payload = build_tag_operation_payload(access_password, tag_filter, bytes((qt_data,)))
        response = await self._request(Command.SET_QT, payload)
        _require_ack(response, Command.SET_QT)

    async def get_qt(
        self,
        *,
        access_password: bytes = b"\x00\x00\x00\x00",
        tag_filter: TagFilter | None = None,
    ) -> int:
        """Return the Impinj Monza QT configuration of one tag.

        Raises:
            ChainwayUnsupportedCommandError: The reader does not support
                the command. UR4 firmware 7.40.1 answers this way for
                tags without QT support.
            ChainwayResponseError: The response is truncated.
        """
        payload = build_tag_operation_payload(access_password, tag_filter, b"")
        response = await self._request(Command.GET_QT, payload)
        _reject_unsupported(response, Command.GET_QT)
        require_status_header(response, 2, STATUS_OK, "QT")
        return response[1]

    async def read_qt(
        self,
        qt_data: int,
        bank: MemoryBank,
        word_address: int,
        word_count: int,
        *,
        access_password: bytes = b"\x00\x00\x00\x00",
        tag_filter: TagFilter | None = None,
    ) -> bytes:
        """Read from the QT memory of one tag.

        The native wrappers run a single inventory before the read,
        call :meth:`single_inventory` to reproduce that sequence.

        Args:
            qt_data: The one byte QT control value.
            bank: The QT memory bank to read from.
            word_address: Start address in 16-bit words.
            word_count: Number of 16-bit words to read. The native
                library truncates the count above 255 bytes.
            access_password: Four-byte tag access password.
            tag_filter: Selection filter, or None to let the reader
                pick the tag.

        Returns:
            The read data, ``word_count`` times two bytes.

        Raises:
            ValueError: The QT value or the window is invalid.
            ChainwayResponseError: The reader reported a failure.
        """
        if not 0 <= qt_data <= BYTE_MAX:
            msg = f"QT value must be between 0 and 255, got {qt_data}"
            raise ValueError(msg)
        validate_word_window(word_address, word_count)
        tail = bytes(
            (
                qt_data,
                bank,
                word_address >> 8 & 0xFF,
                word_address & 0xFF,
                word_count >> 8 & 0xFF,
                word_count & 0xFF,
            )
        )
        payload = build_tag_operation_payload(access_password, tag_filter, tail)
        response = await self._request(Command.READ_QT, payload)
        _require_tag_success(response, Command.READ_QT)
        return parse_word_data(response, "QT read")

    async def write_qt(
        self,
        qt_data: int,
        bank: MemoryBank,
        word_address: int,
        data: bytes,
        *,
        access_password: bytes = b"\x00\x00\x00\x00",
        tag_filter: TagFilter | None = None,
    ) -> None:
        """Write to the QT memory of one tag.

        Raises:
            ValueError: The QT value is invalid, the data length is
                odd or the window is invalid.
            ChainwayResponseError: The reader reported a failure.
        """
        if not 0 <= qt_data <= BYTE_MAX:
            msg = f"QT value must be between 0 and 255, got {qt_data}"
            raise ValueError(msg)
        if not data or len(data) % 2 != 0:
            msg = f"data must be a non-empty even number of bytes, got {len(data)}"
            raise ValueError(msg)
        validate_word_window(word_address, len(data) // 2)
        word_count = len(data) // 2
        tail = (
            bytes(
                (
                    qt_data,
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
        response = await self._request(Command.WRITE_QT, payload)
        _require_tag_success(response, Command.WRITE_QT)

    async def deactivate_tag(
        self,
        command: bytes = b"\x00\x00",
        *,
        access_password: bytes = b"\x00\x00\x00\x00",
        tag_filter: TagFilter | None = None,
    ) -> None:
        """Send the native deactivate command to one tag.

        The two command bytes lead the payload and no source documents
        their meaning. The vendor frame sends two zero bytes. UR4
        firmware 7.40.1 does not support the command.

        Raises:
            ValueError: The command is not two bytes.
            ChainwayUnsupportedCommandError: The reader does not support
                the command.
            ChainwayResponseError: The reader did not acknowledge the
                command.
        """
        payload = build_deactivate_payload(command, access_password, tag_filter)
        response = await self._request(Command.DEACTIVATE_TAG, payload)
        _reject_unsupported(response, Command.DEACTIVATE_TAG)
        _require_ack(response, Command.DEACTIVATE_TAG)

    async def set_dwell_time(self, dwell: int, count: int) -> None:
        """Set the dwell time of the module.

        No source documents the units. The reference frame carries
        the values 1000 and 3.

        Raises:
            ValueError: A value does not fit four bytes.
        """
        if not 0 <= dwell <= DWORD_MAX:
            msg = f"dwell must be within 0 to {DWORD_MAX}, got {dwell}"
            raise ValueError(msg)
        if not 0 <= count <= DWORD_MAX:
            msg = f"count must be within 0 to {DWORD_MAX}, got {count}"
            raise ValueError(msg)
        payload = dwell.to_bytes(4) + count.to_bytes(4)
        response = await self._request(Command.SET_DWELL_TIME, payload)
        _require_ack(response, Command.SET_DWELL_TIME)

    async def read_tag_sensor(
        self,
        sub: SensorSubcommand,
        epc: bytes,
        antenna: int,
        power_dbm: float,
    ) -> bytes:
        """Read one value from a sensor tag with the 0x7C command.

        Args:
            sub: The value to read, every subcommand except write
                calibration.
            epc: The tag EPC, zero padded to 16 bytes on the wire.
            antenna: One-based antenna number.
            power_dbm: Power in dBm applied to the read.

        Returns:
            The read data. The length depends on the subcommand, the
            response carries a word count.

        Raises:
            ValueError: The subcommand is write calibration, or a
                field is out of range.
            ChainwayResponseError: The reader reported a failure.
        """
        if sub is SensorSubcommand.WRITE_CALIBRATION:
            msg = "the write calibration subcommand belongs to write_tag_calibration"
            raise ValueError(msg)
        payload = build_sensor_payload(sub, epc, antenna, power_dbm)
        response = await self._request(Command.SENSOR_CALIBRATION, payload)
        _require_tag_success(response, Command.SENSOR_CALIBRATION)
        return parse_word_data(response, "tag sensor")

    async def write_tag_calibration(
        self,
        epc: bytes,
        antenna: int,
        power_dbm: float,
        data: bytes,
    ) -> None:
        """Write the calibration block of a sensor tag.

        Args:
            epc: The tag EPC, zero padded to 16 bytes on the wire.
            antenna: One-based antenna number.
            power_dbm: Power in dBm applied to the write.
            data: Exactly eight calibration bytes.

        Raises:
            ValueError: A field is out of range.
            ChainwayResponseError: The reader reported a failure.
        """
        payload = build_sensor_payload(
            SensorSubcommand.WRITE_CALIBRATION, epc, antenna, power_dbm, data
        )
        response = await self._request(Command.SENSOR_CALIBRATION, payload)
        _require_tag_success(response, Command.SENSOR_CALIBRATION)

    async def start_tag_logging(
        self,
        tag_filter: TagFilter,
        min_code: int,
        max_code: int,
        delay: int,
        interval: int,
    ) -> None:
        """Start temperature logging on one sensor tag.

        The layout comes from the disassembly only. The boundary
        values are 10-bit temperature codes, the same format
        :meth:`read_tag_temperatures` decodes.

        Args:
            tag_filter: The mask filter that selects the sensor tag.
            min_code: The lower temperature boundary, 0 to 1023.
            max_code: The upper temperature boundary, 0 to 1023.
            delay: The logging start delay, unit undocumented.
            interval: The logging interval, unit undocumented.

        Raises:
            ValueError: A value is out of range.
            ChainwayResponseError: The reader reported a failure.
        """
        if not 0 <= min_code <= TEMP_CODE_MAX or not 0 <= max_code <= TEMP_CODE_MAX:
            msg = (
                f"temperature codes must be within 0 to {TEMP_CODE_MAX},"
                f" got {min_code} and {max_code}"
            )
            raise ValueError(msg)
        if not 0 <= delay <= WORD_MAX or not 0 <= interval <= WORD_MAX:
            msg = f"delay and interval must be within 0 to {WORD_MAX}, got {delay} and {interval}"
            raise ValueError(msg)
        extra = (
            min_code.to_bytes(2) + max_code.to_bytes(2) + delay.to_bytes(2) + interval.to_bytes(2)
        )
        payload = build_tag_sensor_payload(TagSensorSubcommand.START_LOGGING, tag_filter, extra)
        response = await self._request(Command.TAG_SENSOR, payload)
        _require_tag_success(response, Command.TAG_SENSOR)

    async def stop_tag_logging(self, tag_filter: TagFilter) -> None:
        """Stop temperature logging on one sensor tag.

        Raises:
            ChainwayResponseError: The reader reported a failure.
        """
        payload = build_tag_sensor_payload(TagSensorSubcommand.STOP_LOGGING, tag_filter, b"")
        response = await self._request(Command.TAG_SENSOR, payload)
        _require_tag_success(response, Command.TAG_SENSOR)

    async def check_tag_sensor_mode(self, tag_filter: TagFilter) -> int:
        """Return the operating mode value of one sensor tag.

        No source documents the value.

        Raises:
            ChainwayUnsupportedCommandError: The reader does not support
                the command.
            ChainwayResponseError: The response is truncated or echoes
                a different subcommand.
        """
        payload = build_tag_sensor_payload(TagSensorSubcommand.CHECK_OP_MODE, tag_filter, b"")
        response = await self._request(Command.TAG_SENSOR, payload)
        _reject_unsupported(response, Command.TAG_SENSOR)
        return parse_tag_sensor_value(
            response, TagSensorSubcommand.CHECK_OP_MODE, "tag sensor mode"
        )

    async def read_tag_sensor_voltage(self, tag_filter: TagFilter) -> float:
        """Return the voltage of one sensor tag in volts.

        The value is the raw reading times 2.5 divided by 8192.

        Raises:
            ChainwayUnsupportedCommandError: The reader does not support
                the command.
            ChainwayResponseError: The response is truncated or echoes
                a different subcommand.
        """
        payload = build_tag_sensor_payload(TagSensorSubcommand.READ_VOLTAGE, tag_filter, b"")
        response = await self._request(Command.TAG_SENSOR, payload)
        _reject_unsupported(response, Command.TAG_SENSOR)
        raw = parse_tag_sensor_value(
            response, TagSensorSubcommand.READ_VOLTAGE, "tag sensor voltage"
        )
        return raw * TAG_SENSOR_VOLTAGE_FACTOR

    async def read_tag_temperatures(
        self,
        tag_filter: TagFilter,
        start: int,
        count: int,
    ) -> tuple[float, ...]:
        """Read the logged temperatures of one sensor tag.

        Args:
            tag_filter: The mask filter that selects the sensor tag.
            start: The first temperature entry to read, 0 to 65535.
            count: How many entries to read, 1 to 255.

        Returns:
            One temperature in degrees C per returned entry.

        Raises:
            ValueError: The window is out of range.
            ChainwayUnsupportedCommandError: The reader does not support
                the command.
            ChainwayResponseError: The response is truncated.
        """
        if not 0 <= start <= WORD_MAX:
            msg = f"start must be within 0 to {WORD_MAX}, got {start}"
            raise ValueError(msg)
        if not 1 <= count <= BYTE_MAX:
            msg = f"count must be between 1 and 255, got {count}"
            raise ValueError(msg)
        extra = start.to_bytes(2) + bytes((count,))
        payload = build_tag_sensor_payload(TagSensorSubcommand.READ_MULTI_TEMP, tag_filter, extra)
        response = await self._request(Command.TAG_SENSOR, payload)
        _reject_unsupported(response, Command.TAG_SENSOR)
        return parse_tag_temperatures(response)

    async def read_collected_tags(self) -> CollectedTags:
        """Pull the tags collected in auto or trigger work mode.

        UR4 firmware 7.40.1 never answers this command over serial,
        in command and in auto work mode alike.
        """
        payload = await self._request(Command.READ_COLLECTED_TAGS)
        return parse_collected_tags(payload)

    async def read_collected_tags_full(self) -> CollectedTagsFull:
        """Pull full tag records collected in auto or trigger work mode.

        The records carry the PC word and the RSSI pair, without the
        antenna byte of a live sighting. The request form is documented
        as one byte with an unverified tail, this method sends the
        single documented byte.

        Raises:
            ChainwayUnsupportedCommandError: The reader does not support
                the command. UR4 firmware 7.40.1 answers this way.
        """
        payload = await self._request(Command.READ_COLLECTED_TAGS_FULL, COLLECTED_TAGS_FULL_PAYLOAD)
        _reject_unsupported(payload, Command.READ_COLLECTED_TAGS_FULL)
        return parse_collected_tags_full(payload)

    async def get_collected_tag_count(self) -> int:
        """Return how many collected tags the reader stores.

        Raises:
            ChainwayUnsupportedCommandError: The reader does not support
                the command. UR4 firmware 7.40.1 answers this way.
        """
        payload = await self._request(Command.FLASH_STORAGE, bytes((FlashSubcommand.ALL_COUNT,)))
        _reject_unsupported(payload, Command.FLASH_STORAGE)
        require_minimum_length(payload, 2, "collected count")
        return payload[0] << 8 | payload[1]

    async def get_new_collected_tag_count(self) -> int:
        """Return how many collected tags arrived since the last pull.

        Raises:
            ChainwayUnsupportedCommandError: The reader does not support
                the command. UR4 firmware 7.40.1 answers this way.
        """
        payload = await self._request(Command.FLASH_STORAGE, bytes((FlashSubcommand.NEW_COUNT,)))
        _reject_unsupported(payload, Command.FLASH_STORAGE)
        require_minimum_length(payload, 2, "collected count")
        return payload[0] << 8 | payload[1]

    async def delete_collected_tags(self) -> None:
        """Delete every collected tag from the reader storage.

        Raises:
            ChainwayUnsupportedCommandError: The reader does not support
                the command. UR4 firmware 7.40.1 answers this way.
        """
        payload = await self._request(Command.FLASH_STORAGE, bytes((FlashSubcommand.DELETE_ALL,)))
        _reject_unsupported(payload, Command.FLASH_STORAGE)
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
        """Set who drives the inventory.

        In auto mode the UR4 starts scanning when it boots and pushes
        the tag frames to the destination address over UDP when the
        trigger output route is UDP. Call :meth:`software_reset` and
        :meth:`disconnect` afterwards. Connecting a client sends stop
        inventory, which ends the auto scan until the next boot.
        """
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
        """Turn the buzzer on or off.

        The mainboard keeps the setting across a power cycle.
        """
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

    async def get_gpi(self) -> GpiState:
        """Return the trigger input levels GPI1 and GPI2.

        The reader has no command that reads back the outputs set with
        :meth:`set_gpo`.
        """
        payload = await self._request(Command.CONFIG, bytes((ConfigSubcommand.GET_GPI,)))
        require_status_header(payload, 3, ConfigSubcommand.GET_GPI, "GPI")
        return GpiState(input_1=payload[1] == 0x01, input_2=payload[2] == 0x01)

    async def set_trigger_config(self, config: TriggerConfig) -> None:
        """Set the trigger work mode timing.

        The mainboard keeps the setting across a power cycle.
        """
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

    async def stop_buzzer(self) -> None:
        """Turn the buzzer off.

        The vendor demos ship this form as a hardcoded frame, the
        buzzer off variant of the buzzer duration command.
        """
        response = await self._request(
            Command.PERIPHERAL,
            bytes((PeripheralSubcommand.BUZZER_DURATION, 0x00)),
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

    async def jump_to_bootloader(
        self, target: BootloaderTarget = BootloaderTarget.UHF_MODULE
    ) -> None:
        """Reboot one firmware target into its bootloader.

        Args:
            target: The firmware target to reboot. Every SDK jumps to
                the UHF module, the other targets come from the native
                libraries and the C# demo.
        """
        response = await self._request(Command.JUMP_TO_BOOTLOADER, bytes((target,)))
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

        A link that fails before it answered anything is opened again
        and the request is sent once more. The UR4 resets some fresh
        TCP connections without answering.

        Raises:
            ChainwayInventoryActiveError: A continuous inventory is
                running and the command is not stop inventory.
            ChainwayTimeoutError: No response arrived in time.
            ChainwayConnectionError: The link dropped while waiting.
        """
        await self._ensure_connected()
        protocol = self._protocol
        try:
            return await self._request_once(
                command, payload, allow_during_inventory=allow_during_inventory
            )
        except ChainwayConnectionError as err:
            if self._link_answered:
                raise
            _LOGGER.debug("the link failed before its first answer, reconnecting once: %s", err)
            await self._drop_link(err, protocol)
        await self._ensure_connected()
        return await self._request_once(
            command, payload, allow_during_inventory=allow_during_inventory
        )

    async def _request_once(
        self,
        command: Command,
        payload: bytes,
        *,
        allow_during_inventory: bool,
    ) -> bytes:
        if self._inventory_active and not allow_during_inventory:
            msg = "the reader only answers stop inventory while a continuous inventory runs"
            raise ChainwayInventoryActiveError(msg)
        async with self._lock:
            return await self._exchange(command, payload)

    async def _wait_for_commit(self) -> None:
        delay = self._quiet_until - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)

    async def _exchange(self, command: Command, payload: bytes) -> bytes:
        await self._wait_for_commit()
        transport = self._transport
        if transport is None:
            msg = "the link is closed"
            raise ChainwayConnectionError(msg)
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bytes] = loop.create_future()
        self._pending = (command + 1, future)
        try:
            self._write(transport, build_frame(command, payload))
        except ChainwayError:
            self._pending = None
            raise
        try:
            async with asyncio.timeout(self.response_timeout):
                response = await future
        except TimeoutError as err:
            msg = f"no response for command {command:#04x} within {self.response_timeout} seconds"
            raise ChainwayTimeoutError(msg) from err
        finally:
            self._pending = None
        if (
            command == Command.CONFIG
            and payload[:1]
            and payload[0] in CONFIG_COMMITTING_SUBCOMMANDS
            and response[:1] == bytes((STATUS_OK,))
        ):
            self._quiet_until = time.monotonic() + CONFIG_COMMIT_DELAY
        return response

    def _handle_frame(self, command: int, payload: bytes) -> None:
        pending = self._pending
        if pending is not None and pending[0] == command:
            self._link_answered = True
            if not pending[1].done():
                pending[1].set_result(payload)
            return
        if command == Command.TAG_STREAM:
            self._deliver_tag(payload)
            return
        _LOGGER.debug("dropping unexpected frame with command %#04x", command)

    def _deliver_tag(self, payload: bytes) -> None:
        if self._discarding_tags:
            _LOGGER.debug("dropping a tag record from a scan started before this connection")
            return
        try:
            tag = parse_tag_record(
                payload,
                with_antenna=True,
                received_at=now_utc(),
                with_phase=self._inventory_phase,
                with_frequency=self._inventory_frequency,
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
        try:
            result = callback(argument)
        except Exception:
            _LOGGER.exception("callback failed")
            return
        if isinstance(result, Coroutine):
            task = asyncio.create_task(result)
            self._callback_tasks.add(task)
            task.add_done_callback(self._callback_tasks.discard)
            task.add_done_callback(_consume_task_exception)

    def _write(self, transport: BaseSerialTransport, frame: bytes) -> None:
        try:
            transport.write(frame)
        except OSError as err:
            self._schedule_drop_link(err, self._protocol)
            raise _link_error(err) from err

    def _schedule_drop_link(
        self, exc: Exception | None, protocol: ChainwayProtocol | None = None
    ) -> None:
        task = asyncio.create_task(self._drop_link(exc, protocol))
        self._callback_tasks.add(task)
        task.add_done_callback(self._callback_tasks.discard)
        task.add_done_callback(_consume_task_exception)

    async def _drop_link(
        self, exc: Exception | None, protocol: ChainwayProtocol | None = None
    ) -> None:
        async with self._lifecycle_lock:
            if protocol is not None and protocol is not self._protocol:
                return
            if self._link_lost_error is None:
                self._link_lost_error = _link_error(exc)
            transport = await self._teardown()
        await self._release(transport)
        if not self._link_reported:
            self._link_reported = True
            error = self._link_lost_error
            self._link_lost_error = None
            callback = self.on_connection_lost
            if callback is not None and error is not None:
                self._run_callback(callback, error)

    def _finish_inventory(self) -> None:
        self._inventory_active = False
        self._inventory_phase = False
        self._inventory_frequency = False

    async def _teardown(self) -> BaseSerialTransport | None:
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
        return transport

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
                await self._drop_link(ChainwayConnectionError("the link went silent"), protocol)
                return
            if now - self._last_keepalive >= self.keepalive_interval:
                self._last_keepalive = now
                if self._inventory_active:
                    transport = self._transport
                    if transport is not None:
                        with suppress(ChainwayError):
                            self._write(transport, INVENTORY_KEEPALIVE_BYTE)
                else:
                    with suppress(ChainwayError):
                        await self._request_once(
                            Command.GET_VERSION, b"", allow_during_inventory=False
                        )
