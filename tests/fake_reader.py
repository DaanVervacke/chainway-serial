"""Scriptable Chainway UR4 responder, transport agnostic."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from chainway_serial.const import (
    CONFIG_COMMITTING_SUBCOMMANDS,
    FRAME_HEADERS,
    MAX_FRAME_LENGTH,
    MIN_FRAME_LENGTH,
    Command,
    ConfigSubcommand,
    FlashSubcommand,
    PeripheralSubcommand,
    ProtocolTypeSelector,
    SensorSubcommand,
    TagSensorSubcommand,
)
from chainway_serial.exceptions import ChainwayProtocolError
from chainway_serial.frames import build_frame, parse_frame

Responder = Callable[[bytes], bytes]


class FakeReaderLogic:
    """Answer Chainway UR4 requests with scripted or stored state."""

    def __init__(self) -> None:
        self.received: list[tuple[int, bytes]] = []
        self.raw: list[bytes] = []
        self.silent_commands: set[int] = set()
        self.drop_connection_commands: set[int] = set()
        self.bad_checksum_commands: set[int] = set()
        self.failing_tag_commands: set[int] = set()
        self.junk_on_connect = b""
        self.commit_mute = 0.0
        self.dropped: list[tuple[int, bytes]] = []
        self._muted_until = 0.0
        self.push: Callable[[bytes], None] | None = None
        self.close_transport: Callable[[], None] | None = None
        self._buffer = bytearray()
        self._inventory_task: asyncio.Task[None] | None = None
        self._init_state()
        self._responders = self._build_responders()
        self._config_responders = self._build_config_responders()

    def _init_state(self) -> None:
        self.version_payload = b"\x01\x02\x03"
        self.temperature_payload = b"\x01\x10\x0e"
        self.power_payload = b"\x00\x01\x0b\xb8\x0b\xb8"
        self.antenna_state_payload = b"\x00\x03"
        self.gen2_payload = b"\x84\x4f\xf2\x1a"
        self.collected_payload = b"\x00\x05\x02\x06\x11\x22\x33\x44\x55\x66\x04\xaa\xbb\xcc\xdd"
        self.flash_payload = b"\x02\x06\x11\x22\x33\x44\x55\x66\x04\xaa\xbb\xcc\xdd"
        self.device_id_payload = b"\xf1\xf2\xf3\xf4"
        self.fixed_frequency_payload = b"\x01\x0e\x0a\x3d"
        self.return_loss_payload = b"\x01\x12\x02\x01\x03\x00\x04\x00"
        self.authenticate_payload = b"\x01\x00\x00\x08" + bytes(range(16))
        self.idle_sleep_time = 0x0A
        self.single_inventory_payload = b"\x30\x00" + bytes(range(1, 13)) + b"\xfe\xd6\x00"
        self.read_tag_payload = b"\x01\x00\x00\x02\x11\x22\x33\x44"
        self.read_qt_payload = b"\x01\x00\x00\x02\x11\x22\x33\x44"
        self.sensor_payload = b"\x01\x00\x00\x02\x11\x22\x33\x44"
        self.module_parameter_data = b"\x11\x22\x33\x44"
        self.temperature_protect = 0x01
        self.module_work_time = 500
        self.dual_single_mode = 0x01
        self.qt_data = 0x01
        self.tag_sensor_mode_payload = b"\x05\x00\x01"
        self.tag_sensor_voltage_payload = b"\x06\x20\x00"
        self.tag_temperatures_payload = b"\x07\x00\x02\x02\x50\x00\x00\x00\x7a\x00\x00\x00"
        full_record = b"\x30\x00" + bytes(range(1, 13)) + b"\xfe\xd6"
        self.collected_full_payload = b"\x00\x00\x05\x02\x10" + full_record + b"\x10" + full_record
        self.barcode_payload = b"\x02\x02\x00"
        self.tags_to_stream: list[bytes] = []
        self.stream_delay = 0.01
        self.protocol_type = 0x00
        self.region = 0x08
        self.rf_link = 0x02
        self.fast_id = 0x01
        self.tag_focus = 0x01
        self.reader_address = b"\xc0\xa8\x63\xc8\x22\xb8"
        self.destination_address = b"\xc0\xa8\x63\xc9\x13\x88"
        self.inventory_mode = b"\x02\x00\x04"
        self.antenna_mask = b"\x00\x01"
        self.work_mode = 0x00
        self.buzzer_state = 0x01
        self.gpo_state = b"\x01\x00"
        self.trigger_config = b"\x00\x00\x64\x00\x0a\x00"
        self.volume = 0x05
        self.antenna_work_time: dict[int, int] = {1: 100}
        self.uart_baudrate = 0x02

    def _build_responders(self) -> dict[int, Responder]:
        return {
            Command.GET_VERSION: lambda _payload: self.version_payload,
            Command.STM32_VERSION: lambda _payload: b"\x01\x00\x01",
            Command.HARDWARE_VERSION: lambda _payload: b"\x00\x01\x02",
            Command.GET_DEVICE_ID: lambda _payload: self.device_id_payload,
            Command.GET_TEMPERATURE: lambda _payload: self.temperature_payload,
            Command.ANTENNA_CONNECTION_STATE: lambda _payload: self.antenna_state_payload,
            Command.SET_POWER: lambda _payload: b"\x01",
            Command.GET_POWER: lambda _payload: self.power_payload,
            Command.SET_FIXED_FREQUENCY: lambda _payload: b"\x01",
            Command.GET_FIXED_FREQUENCY: lambda _payload: self.fixed_frequency_payload,
            Command.SET_REGION: self._store_region,
            Command.GET_REGION: lambda _payload: b"\x01" + bytes((self.region,)),
            Command.SET_CARRIER_WAVE: lambda _payload: b"\x01",
            Command.GET_RETURN_LOSS: lambda _payload: self.return_loss_payload,
            Command.SET_GEN2_PARAMETERS: self._store_gen2_parameters,
            Command.GET_GEN2_PARAMETERS: lambda _payload: self.gen2_payload,
            Command.SET_UART_BAUDRATE: self._store_uart_baudrate,
            Command.GET_UART_BAUDRATE: lambda _payload: b"\x01" + bytes((self.uart_baudrate,)),
            Command.SET_RF_LINK: self._store_rf_link,
            Command.GET_RF_LINK: lambda _payload: b"\x01\x00" + bytes((self.rf_link,)),
            Command.SET_FAST_ID: self._store_fast_id,
            Command.GET_FAST_ID: lambda _payload: b"\x01" + bytes((self.fast_id,)),
            Command.SET_TAG_FOCUS: self._store_tag_focus,
            Command.GET_TAG_FOCUS: lambda _payload: b"\x00" + bytes((self.tag_focus,)),
            Command.SET_PROTOCOL_TYPE: self._respond_protocol_type,
            Command.SET_INVENTORY_FILTER: lambda _payload: b"\x01",
            Command.SET_INVENTORY_MODE: self._store_inventory_mode,
            Command.GET_INVENTORY_MODE: lambda _payload: b"\x01" + self.inventory_mode,
            Command.SET_ANTENNA_MASK: self._store_antenna_mask,
            Command.GET_ANTENNA_MASK: lambda _payload: self.antenna_mask,
            Command.SET_ANTENNA_WORK_TIME: self._store_antenna_work_time,
            Command.GET_ANTENNA_WORK_TIME: self._respond_antenna_work_time,
            Command.SET_FAST_INVENTORY_MODE: lambda _payload: b"\x01",
            Command.GET_FAST_INVENTORY_MODE: lambda _payload: b"\x01\x01",
            Command.SOFTWARE_RESET: lambda _payload: b"\x01",
            Command.RESTORE_FACTORY_SETTINGS: lambda _payload: b"\x01",
            Command.VERIFY_VOLTAGE: lambda _payload: b"\x01\x01\x0b\xb8",
            Command.SET_PARAM: self._store_module_parameter,
            Command.GET_PARAM: self._respond_module_parameter,
            Command.SET_TEMPERATURE_PROTECT: self._store_temperature_protect,
            Command.GET_TEMPERATURE_PROTECT: lambda _payload: (
                b"\x01" + bytes((self.temperature_protect,))
            ),
            Command.SET_MODULE_WORK_TIME: self._store_module_work_time,
            Command.GET_MODULE_WORK_TIME: lambda _payload: (
                b"\x01" + self.module_work_time.to_bytes(4)
            ),
            Command.SET_DUAL_SINGLE_MODE: self._store_dual_single_mode,
            Command.GET_DUAL_SINGLE_MODE: lambda _payload: (
                b"\x01" + bytes((self.dual_single_mode,))
            ),
            Command.SENSOR_CALIBRATION: self._respond_sensor,
            Command.TAG_SENSOR: self._respond_tag_sensor,
            Command.SET_DWELL_TIME: lambda _payload: b"\x01",
            Command.SINGLE_INVENTORY: lambda _payload: self.single_inventory_payload,
            Command.READ_TAG: self._respond_read_tag,
            Command.AUTHENTICATE_TAG: self._respond_authenticate,
            Command.WRITE_TAG: lambda _payload: self._tag_result(Command.WRITE_TAG),
            Command.BLOCK_WRITE_TAG: lambda _payload: self._tag_result(Command.BLOCK_WRITE_TAG),
            Command.BLOCK_ERASE_TAG: lambda _payload: self._tag_result(Command.BLOCK_ERASE_TAG),
            Command.BLOCK_PERMALOCK_TAG: self._respond_block_permalock,
            Command.LOCK_TAG: lambda _payload: self._tag_result(Command.LOCK_TAG),
            Command.KILL_TAG: lambda _payload: self._tag_result(Command.KILL_TAG),
            Command.SET_PROTECTED_MODE: lambda _payload: b"\x01",
            Command.SET_QT: self._store_qt,
            Command.GET_QT: lambda _payload: b"\x01" + bytes((self.qt_data,)),
            Command.READ_QT: self._respond_read_qt,
            Command.WRITE_QT: lambda _payload: self._tag_result(Command.WRITE_QT),
            Command.DEACTIVATE_TAG: lambda _payload: b"\x01",
            Command.READ_COLLECTED_TAGS: lambda _payload: self.collected_payload,
            Command.READ_COLLECTED_TAGS_FULL: lambda _payload: self.collected_full_payload,
            Command.FLASH_STORAGE: self._respond_flash,
            Command.READ_FLASH_TAGS: lambda _payload: self.flash_payload,
            Command.JUMP_TO_BOOTLOADER: lambda _payload: b"\x01",
            Command.START_UPDATE: lambda _payload: b"\x01",
            Command.UPDATE_BLOCK: lambda _payload: b"\x01",
            Command.STOP_UPDATE: lambda _payload: b"\x01",
        }

    def _build_config_responders(self) -> dict[int, Responder]:
        return {
            ConfigSubcommand.SET_READER_ADDRESS: self._store_reader_address,
            ConfigSubcommand.GET_READER_ADDRESS: lambda _payload: b"\x02" + self.reader_address,
            ConfigSubcommand.SET_DESTINATION_ADDRESS: self._store_destination_address,
            ConfigSubcommand.GET_DESTINATION_ADDRESS: lambda _payload: (
                b"\x04" + self.destination_address
            ),
            ConfigSubcommand.SET_WORK_MODE: self._store_work_mode,
            ConfigSubcommand.GET_WORK_MODE: lambda _payload: b"\x06" + bytes((self.work_mode,)),
            ConfigSubcommand.SET_BUZZER: self._store_buzzer,
            ConfigSubcommand.GET_BUZZER: lambda _payload: b"\x08" + bytes((self.buzzer_state,)),
            ConfigSubcommand.SET_GPO: self._store_gpo,
            ConfigSubcommand.GET_GPO: lambda _payload: b"\x0a" + self.gpo_state,
            ConfigSubcommand.SET_TRIGGER_CONFIG: self._store_trigger_config,
            ConfigSubcommand.GET_TRIGGER_CONFIG: lambda _payload: b"\x0c" + self.trigger_config,
            ConfigSubcommand.SET_VOLUME: self._store_volume,
            ConfigSubcommand.GET_VOLUME: lambda _payload: b"\x12" + bytes((self.volume,)),
        }

    def handle_bytes(self, data: bytes) -> list[bytes]:
        """Feed inbound bytes and return the response frames."""
        self.raw.append(bytes(data))
        self._buffer.extend(data)
        responses: list[bytes] = []
        while True:
            extracted = self._extract_frame()
            if extracted is None:
                break
            command, payload = extracted
            self.received.append((command, payload))
            if command in self.drop_connection_commands:
                if self.close_transport is not None:
                    self.close_transport()
                break
            if command in self.silent_commands:
                continue
            now = time.monotonic()
            if now < self._muted_until:
                self.dropped.append((command, payload))
                continue
            if (
                command == Command.CONFIG
                and payload[:1]
                and payload[0] in CONFIG_COMMITTING_SUBCOMMANDS
            ):
                self._muted_until = now + self.commit_mute
            response = self._respond(command, payload)
            if response is None:
                continue
            frame = build_frame(command + 1, response)
            if command in self.bad_checksum_commands:
                frame = frame[:-3] + bytes((frame[-3] ^ 0xFF,)) + frame[-2:]
            responses.append(frame)
        return responses

    def _extract_frame(self) -> tuple[int, bytes] | None:
        while True:
            positions = [
                position
                for position in (self._buffer.find(header) for header in FRAME_HEADERS)
                if position >= 0
            ]
            if not positions:
                self._buffer.clear()
                return None
            index = min(positions)
            if index > 0:
                del self._buffer[:index]
                continue
            if len(self._buffer) < 4:
                return None
            length = self._buffer[2] << 8 | self._buffer[3]
            if not MIN_FRAME_LENGTH <= length <= MAX_FRAME_LENGTH:
                del self._buffer[:1]
                continue
            if len(self._buffer) < length:
                return None
            frame = bytes(self._buffer[:length])
            del self._buffer[:length]
            try:
                return parse_frame(frame)
            except ChainwayProtocolError:
                continue

    def _respond(self, command: int, payload: bytes) -> bytes | None:
        if command == Command.START_INVENTORY:
            self._inventory_task = asyncio.create_task(self._stream_tags())
            return None
        if command == Command.STOP_INVENTORY:
            self._cancel_inventory()
            return b"\x01"
        if command == Command.CONFIG:
            return self._config_responders[payload[0]](payload)
        if command == Command.PERIPHERAL:
            return self._respond_peripheral(payload)
        responder = self._responders.get(command)
        if responder is None:
            return b"\x01"
        return responder(payload)

    def _respond_peripheral(self, payload: bytes) -> bytes:
        if payload[0] == PeripheralSubcommand.BATTERY:
            return b"\x01\x64"
        if payload[0] == PeripheralSubcommand.BARCODE:
            return self.barcode_payload
        if payload[0] == PeripheralSubcommand.IDLE_SLEEP_SET:
            self.idle_sleep_time = payload[1]
            return b"\x01"
        if payload[0] == PeripheralSubcommand.IDLE_SLEEP_GET:
            return b"\x06" + bytes((self.idle_sleep_time,))
        return b"\x01"

    def _respond_protocol_type(self, payload: bytes) -> bytes:
        if payload[0] == ProtocolTypeSelector.SET:
            self.protocol_type = payload[1]
            return b"\x00\x01"
        return b"\x01" + bytes((self.protocol_type,))

    def _respond_read_tag(self, _payload: bytes) -> bytes:
        if Command.READ_TAG in self.failing_tag_commands:
            return b"\x01\x01"
        return self.read_tag_payload

    def _respond_read_qt(self, _payload: bytes) -> bytes:
        if Command.READ_QT in self.failing_tag_commands:
            return b"\x01\x01"
        return self.read_qt_payload

    def _respond_module_parameter(self, payload: bytes) -> bytes:
        return b"\x01" + payload[1:5] + self.module_parameter_data

    def _store_module_parameter(self, payload: bytes) -> bytes:
        self.module_parameter_data = payload[5:9]
        return b"\x01"

    def _respond_sensor(self, payload: bytes) -> bytes:
        if Command.SENSOR_CALIBRATION in self.failing_tag_commands:
            return b"\x01\x01"
        if payload[0] == SensorSubcommand.WRITE_CALIBRATION:
            return b"\x01\x00"
        return self.sensor_payload

    def _respond_tag_sensor(self, payload: bytes) -> bytes:
        if Command.TAG_SENSOR in self.failing_tag_commands:
            return b"\x01\x01"
        if payload[0] == TagSensorSubcommand.CHECK_OP_MODE:
            return self.tag_sensor_mode_payload
        if payload[0] == TagSensorSubcommand.READ_VOLTAGE:
            return self.tag_sensor_voltage_payload
        if payload[0] == TagSensorSubcommand.READ_MULTI_TEMP:
            return self.tag_temperatures_payload
        return b"\x01\x00"

    def _respond_authenticate(self, _payload: bytes) -> bytes:
        if Command.AUTHENTICATE_TAG in self.failing_tag_commands:
            return b"\x01\x01"
        return self.authenticate_payload

    def _respond_block_permalock(self, payload: bytes) -> bytes:
        if Command.BLOCK_PERMALOCK_TAG in self.failing_tag_commands:
            return b"\x01\x01"
        mask_bytes = ((payload[7] << 8 | payload[8]) + 7) // 8
        offset = 9 + mask_bytes
        if payload[offset]:
            return b"\x01\x00"
        block_range = payload[offset + 4] << 8 | payload[offset + 5]
        return b"\x01\x00" + b"\xf0\x00" * block_range

    def _tag_result(self, command: Command) -> bytes:
        if command in self.failing_tag_commands:
            return b"\x01\x01"
        return b"\x01\x00"

    def _respond_flash(self, payload: bytes) -> bytes:
        if payload[0] == FlashSubcommand.DELETE_ALL:
            return b"\x00\x00"
        return b"\x00\x02"

    def _store_inventory_mode(self, payload: bytes) -> bytes:
        self.inventory_mode = payload[1:]
        return b"\x01"

    def _store_antenna_mask(self, payload: bytes) -> bytes:
        self.antenna_mask = payload[1:]
        return b"\x01"

    def _store_antenna_work_time(self, payload: bytes) -> bytes:
        self.antenna_work_time[payload[0] & 0x0F] = payload[1] << 8 | payload[2]
        return b"\x01"

    def _store_temperature_protect(self, payload: bytes) -> bytes:
        self.temperature_protect = payload[0]
        return b"\x01"

    def _store_module_work_time(self, payload: bytes) -> bytes:
        self.module_work_time = int.from_bytes(payload)
        return b"\x01"

    def _store_dual_single_mode(self, payload: bytes) -> bytes:
        self.dual_single_mode = payload[1]
        return b"\x01"

    def _store_qt(self, payload: bytes) -> bytes:
        if Command.SET_QT in self.failing_tag_commands:
            return b"\x00"
        self.qt_data = payload[-1]
        return b"\x01"

    def _respond_antenna_work_time(self, payload: bytes) -> bytes:
        antenna = payload[0]
        work_time = self.antenna_work_time.get(antenna, 0)
        return b"\x01" + bytes((antenna, work_time >> 8 & 0xFF, work_time & 0xFF))

    def _store_work_mode(self, payload: bytes) -> bytes:
        self.work_mode = payload[1]
        return b"\x01"

    def _store_buzzer(self, payload: bytes) -> bytes:
        self.buzzer_state = payload[1]
        return b"\x01"

    def _store_gpo(self, payload: bytes) -> bytes:
        self.gpo_state = payload[1:3]
        return b"\x01"

    def _store_trigger_config(self, payload: bytes) -> bytes:
        self.trigger_config = payload[1:]
        return b"\x01"

    def _store_volume(self, payload: bytes) -> bytes:
        self.volume = payload[1]
        return b"\x01"

    def _store_region(self, payload: bytes) -> bytes:
        self.region = payload[1]
        return b"\x01"

    def _store_gen2_parameters(self, payload: bytes) -> bytes:
        self.gen2_payload = payload
        return b"\x01"

    def _store_rf_link(self, payload: bytes) -> bytes:
        self.rf_link = payload[2]
        return b"\x01"

    def _store_fast_id(self, payload: bytes) -> bytes:
        self.fast_id = payload[0]
        return b"\x01"

    def _store_uart_baudrate(self, payload: bytes) -> bytes:
        self.uart_baudrate = payload[0]
        return b"\x01"

    def _store_tag_focus(self, payload: bytes) -> bytes:
        self.tag_focus = payload[0]
        return b"\x01"

    def _store_reader_address(self, payload: bytes) -> bytes:
        self.reader_address = payload[1:]
        return b"\x01"

    def _store_destination_address(self, payload: bytes) -> bytes:
        self.destination_address = payload[1:]
        return b"\x01"

    def _cancel_inventory(self) -> None:
        if self._inventory_task is not None:
            self._inventory_task.cancel()
            self._inventory_task = None

    async def _stream_tags(self) -> None:
        for record in self.tags_to_stream:
            await asyncio.sleep(self.stream_delay)
            if self.push is not None:
                self.push(build_frame(Command.TAG_STREAM, record))
