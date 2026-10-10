"""End to end client tests against a scripted fake reader over TCP."""

import asyncio
from collections.abc import Callable
from contextlib import aclosing

import pytest

from chainway_serial import (
    BootloaderTarget,
    ChainwayClient,
    ChainwayConnectionError,
    ChainwayInventoryActiveError,
    ChainwayResponseError,
    ChainwayTimeoutError,
    ChainwayUnsupportedCommandError,
    FirmwareVersion,
    InventoryMode,
    LockBank,
    LockMode,
    MemoryBank,
    OutputRoute,
    ProtocolType,
    Region,
    ReturnLoss,
    RfLink,
    TagFilter,
    TriggerConfig,
    TriggerInput,
    UartBaudRate,
    WorkMode,
)
from chainway_serial.const import Command, SensorSubcommand
from chainway_serial.frames import build_frame
from chainway_serial.models import AntennaPower, Gen2Parameters, ReaderAddress

from .conftest import wait_for_server
from .fake_reader import FakeReaderLogic


def received(logic: FakeReaderLogic, command: Command) -> bytes:
    matches = [
        payload for received_command, payload in logic.received if received_command == command
    ]
    assert matches, f"command {command:#04x} was never sent"
    return matches[-1]


def commands_seen(logic: FakeReaderLogic) -> list[int]:
    return [command for command, _ in logic.received]


def stream_tag_record() -> bytes:
    return b"\x30\x00" + bytes(range(1, 13)) + b"\xfe\xd6\x00"


def qt_filter() -> TagFilter:
    return TagFilter(bank=MemoryBank.EPC, bit_address=0x20, bit_length=16, data=b"\xe2\x80")


async def test_get_version(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    assert await client.get_version() == FirmwareVersion(1, 2, 3)
    assert received(logic, Command.GET_VERSION) == b""


async def test_get_stm32_version(client: ChainwayClient) -> None:
    assert await client.get_stm32_version() == FirmwareVersion(1, 0, 1)


async def test_get_hardware_version(client: ChainwayClient) -> None:
    assert await client.get_hardware_version() == FirmwareVersion(0, 1, 2)


async def test_get_device_id(client: ChainwayClient) -> None:
    assert await client.get_device_id() == b"\xf1\xf2\xf3\xf4"


async def test_get_temperature(client: ChainwayClient) -> None:
    assert await client.get_temperature() == 41.1


async def test_get_antenna_connection_state(client: ChainwayClient) -> None:
    state = await client.get_antenna_connection_state()
    assert state.connected == (True, True, False, False, False, False, False, False) + (False,) * 8
    assert state.raw == b"\x00\x03"


async def test_get_battery_level(client: ChainwayClient) -> None:
    assert await client.get_battery_level() == 100


async def test_verify_voltage(client: ChainwayClient) -> None:
    assert await client.verify_voltage() == 3000


async def test_module_parameter_roundtrip(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    await client.set_module_parameter(1, 0x01020304, b"\xaa\xbb\xcc\xdd")
    assert received(logic, Command.SET_PARAM) == bytes.fromhex("0101020304aabbccdd")
    assert await client.get_module_parameter(1, 0x01020304) == b"\xaa\xbb\xcc\xdd"
    assert received(logic, Command.GET_PARAM) == bytes.fromhex("0101020304")


async def test_module_parameter_rejects_a_foreign_echo(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    logic._responders[Command.GET_PARAM] = lambda _payload: bytes.fromhex("010000000055667788")
    with pytest.raises(ChainwayResponseError, match="echoed"):
        await client.get_module_parameter(1, 5)


async def test_set_module_parameter_rejects_a_bad_field(client: ChainwayClient) -> None:
    with pytest.raises(ValueError, match="parameter type"):
        await client.set_module_parameter(256, 0, b"\x00" * 4)
    with pytest.raises(ValueError, match="parameter ID"):
        await client.set_module_parameter(0, 1 << 32, b"\x00" * 4)
    with pytest.raises(ValueError, match="parameter data"):
        await client.set_module_parameter(0, 0, b"\x00")


async def test_temperature_protect_roundtrip(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    await client.set_temperature_protect(1)
    assert received(logic, Command.SET_TEMPERATURE_PROTECT) == b"\x01"
    assert await client.get_temperature_protect() == 1


async def test_set_temperature_protect_rejects_a_bad_value(client: ChainwayClient) -> None:
    with pytest.raises(ValueError, match="temperature protect"):
        await client.set_temperature_protect(256)


async def test_module_work_time_roundtrip(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    await client.set_module_work_time(500)
    assert received(logic, Command.SET_MODULE_WORK_TIME) == bytes.fromhex("00000001F4")
    assert await client.get_module_work_time() == 500


async def test_set_module_work_time_rejects_a_bad_value(client: ChainwayClient) -> None:
    with pytest.raises(ValueError, match="work time"):
        await client.set_module_work_time(1 << 40)


async def test_dual_single_mode_roundtrip(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    await client.set_dual_single_mode(1)
    assert received(logic, Command.SET_DUAL_SINGLE_MODE) == b"\x01\x01"
    await client.set_dual_single_mode(0, save=False)
    assert received(logic, Command.SET_DUAL_SINGLE_MODE) == b"\x00\x00"
    assert await client.get_dual_single_mode() == 0


async def test_set_dual_single_mode_rejects_a_bad_mode(client: ChainwayClient) -> None:
    with pytest.raises(ValueError, match="mode"):
        await client.set_dual_single_mode(256)


async def test_set_rf_power_sends_the_documented_payload(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    await client.set_rf_power(30.0, antenna=1)
    assert received(logic, Command.SET_POWER) == b"\x02\x01\x0b\xb8\x0b\xb8"
    await client.set_rf_power(30.0, antenna=1, save=False)
    assert received(logic, Command.SET_POWER) == b"\x00\x01\x0b\xb8\x0b\xb8"


async def test_set_rf_power_rejects_a_bad_value(client: ChainwayClient) -> None:
    with pytest.raises(ValueError, match="power"):
        await client.set_rf_power(31.0)


async def test_set_antenna_power(client: ChainwayClient) -> None:
    await client.set_antenna_power(2, 20.0, 25.0)


async def test_get_rf_power(client: ChainwayClient) -> None:
    assert await client.get_rf_power() == (AntennaPower(1, 30.0, 30.0),)


async def test_fixed_frequency_sends_the_documented_payload(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    await client.set_fixed_frequency(920125)
    assert received(logic, Command.SET_FIXED_FREQUENCY) == b"\x01\x0e\x0a\x3d"


async def test_get_fixed_frequency(client: ChainwayClient) -> None:
    assert await client.get_fixed_frequency() == (920125,)


async def test_region(client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]) -> None:
    logic, _ = reader_server
    await client.set_region(Region.JAPAN, save=False)
    assert received(logic, Command.SET_REGION) == b"\x00\x32"
    assert await client.get_region() is Region.JAPAN


async def test_carrier_wave_and_return_loss(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    await client.set_carrier_wave(enabled=True)
    assert received(logic, Command.SET_CARRIER_WAVE) == b"\x01"
    losses = await client.get_return_loss()
    assert losses == (
        ReturnLoss(port=1, loss_db=18),
        ReturnLoss(port=2, loss_db=1),
        ReturnLoss(port=3, loss_db=0),
        ReturnLoss(port=4, loss_db=0),
    )


async def test_gen2_roundtrip(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    parameters = Gen2Parameters(target=3, session=2)
    await client.set_gen2_parameters(parameters)
    assert received(logic, Command.SET_GEN2_PARAMETERS) == b"\x61\x40\xfb\x22"
    assert await client.get_gen2_parameters() == parameters


async def test_rf_link(client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]) -> None:
    logic, _ = reader_server
    await client.set_rf_link(RfLink.PR_ASK_MILLER_4_640_KHZ, save=True)
    assert received(logic, Command.SET_RF_LINK) == b"\x00\x01\x03"
    assert await client.get_rf_link() is RfLink.PR_ASK_MILLER_4_640_KHZ


async def test_uart_baudrate(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    await client.set_uart_baudrate(UartBaudRate.BAUD_460800)
    assert received(logic, Command.SET_UART_BAUDRATE) == b"\x03"
    assert await client.get_uart_baudrate() is UartBaudRate.BAUD_460800


async def test_uart_baudrate_refuses_codes_outside_the_enum(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    with pytest.raises(ValueError, match="1"):
        await client.set_uart_baudrate(1)  # type: ignore[arg-type]
    assert Command.SET_UART_BAUDRATE not in commands_seen(logic)


async def test_uart_baudrate_reports_a_pending_code_outside_the_enum(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    logic.uart_baudrate = 0x01
    with pytest.raises(ChainwayResponseError, match="0x01"):
        await client.get_uart_baudrate()


async def test_fast_id(client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]) -> None:
    logic, _ = reader_server
    await client.set_fast_id(enabled=False)
    assert received(logic, Command.SET_FAST_ID) == b"\x00\x00"
    assert await client.get_fast_id() is False


async def test_tag_focus(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    await client.set_tag_focus(enabled=True)
    assert received(logic, Command.SET_TAG_FOCUS) == b"\x01\x00"
    assert await client.get_tag_focus() is True


async def test_protocol_type_roundtrip(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    await client.set_protocol_type(ProtocolType.GB_T_29768)
    assert received(logic, Command.SET_PROTOCOL_TYPE) == b"\x00\x01"
    assert await client.get_protocol_type() is ProtocolType.GB_T_29768


async def test_inventory_mode_roundtrip(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    await client.set_inventory_mode(
        InventoryMode.EPC_TID_USER, user_address=2, user_length=4, save=False
    )
    assert received(logic, Command.SET_INVENTORY_MODE) == b"\x00\x02\x02\x04"
    config = await client.get_inventory_mode()
    assert config.mode is InventoryMode.EPC_TID_USER
    assert config.user_address == 2
    assert config.user_length == 4


async def test_set_filter_sends_the_documented_payload(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    await client.set_filter(
        TagFilter(bank=MemoryBank.EPC, bit_address=0x20, bit_length=16, data=b"\x12\x34"),
        save=False,
    )
    assert received(logic, Command.SET_INVENTORY_FILTER) == b"\x00\x01\x00\x20\x00\x10\x12\x34"


async def test_clear_filter(client: ChainwayClient) -> None:
    await client.set_filter(None, save=False)


async def test_antenna_mask_roundtrip(client: ChainwayClient) -> None:
    await client.set_antenna_mask(0x0102, save=True)
    assert await client.get_antenna_mask() == 0x0102


async def test_antenna_work_time_roundtrip(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    await client.set_antenna_work_time(1, 200, save=False)
    assert received(logic, Command.SET_ANTENNA_WORK_TIME) == b"\x01\x00\xc8"
    assert await client.get_antenna_work_time(1) == 200
    with pytest.raises(ChainwayUnsupportedCommandError, match="0x4a or this form"):
        await client.set_antenna_work_time(2, 300, save=True)
    assert received(logic, Command.SET_ANTENNA_WORK_TIME) == b"\x12\x01\x2c"
    assert await client.get_antenna_work_time(2) != 300


async def test_fast_inventory_mode_sends_the_documented_payload(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    await client.set_fast_inventory_mode(enabled=False)
    assert received(logic, Command.SET_FAST_INVENTORY_MODE) == b"\x01\x00\x00"
    await client.set_fast_inventory_mode(enabled=False, save=False)
    assert received(logic, Command.SET_FAST_INVENTORY_MODE) == b"\x00\x00\x00"
    assert await client.get_fast_inventory_mode() is True


async def test_reset_commands(client: ChainwayClient) -> None:
    await client.software_reset()
    await client.restore_factory_settings()


async def test_single_inventory(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    tag = await client.single_inventory()
    assert received(logic, Command.SINGLE_INVENTORY) == b"\x00\x64"
    assert tag is not None
    assert tag.epc == bytes(range(1, 13))
    assert tag.rssi == -29.8
    assert tag.antenna == 0


async def test_single_inventory_without_a_tag(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    logic.single_inventory_payload = b""
    assert await client.single_inventory() is None


async def test_read_tag_sends_the_documented_payload(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    data = await client.read_tag(MemoryBank.USER, 2, 2)
    assert data == b"\x11\x22\x33\x44"
    assert received(logic, Command.READ_TAG) == (
        b"\x00\x00\x00\x00\x01\x00\x00\x00\x00\x03\x00\x02\x00\x02"
    )


async def test_write_tag(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    await client.write_tag(MemoryBank.USER, 2, b"\xe2\x80")
    assert received(logic, Command.WRITE_TAG) == (
        b"\x00\x00\x00\x00\x01\x00\x00\x00\x00\x03\x00\x02\x00\x01\xe2\x80"
    )


async def test_write_tag_rejects_odd_data(client: ChainwayClient) -> None:
    with pytest.raises(ValueError, match="even number"):
        await client.write_tag(MemoryBank.USER, 2, b"\xe2")


async def test_block_write_and_erase(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    await client.block_write_tag(MemoryBank.USER, 2, b"\xe2\x80")
    assert received(logic, Command.BLOCK_WRITE_TAG) == (
        b"\x00\x00\x00\x00\x01\x00\x00\x00\x00\x03\x00\x02\x00\x01\xe2\x80"
    )
    await client.block_erase_tag(MemoryBank.USER, 2, 1)
    assert received(logic, Command.BLOCK_ERASE_TAG) == (
        b"\x00\x00\x00\x00\x01\x00\x00\x00\x00\x03\x00\x02\x00\x01"
    )


async def test_lock_tag_sends_the_documented_lock_code(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    await client.lock_tag([LockBank.ACCESS_PASSWORD], LockMode.LOCK)
    assert received(logic, Command.LOCK_TAG) == b"\x00\x00\x00\x00\x01\x00\x00\x00\x00\x02\x00\x80"


async def test_kill_tag(client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]) -> None:
    logic, _ = reader_server
    await client.kill_tag(b"\x12\x34\x56\x78")
    assert received(logic, Command.KILL_TAG) == b"\x12\x34\x56\x78\x01\x00\x00\x00\x00"


async def test_authenticate_tag_sends_the_documented_payload(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    challenge = bytes(range(10))
    data = await client.authenticate_tag(challenge)
    assert data == bytes(range(16))
    assert received(logic, Command.AUTHENTICATE_TAG) == (
        b"\x00\x00\x00\x00\x01\x00\x00\x00\x00\x0b\x00" + challenge
    )


async def test_authenticate_tag_with_a_filter(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    tag_filter = TagFilter(bank=MemoryBank.TID, bit_address=0, bit_length=96, data=bytes(12))
    await client.authenticate_tag(bytes(10), key_id=2, tag_filter=tag_filter)
    assert received(logic, Command.AUTHENTICATE_TAG).startswith(
        b"\x00\x00\x00\x00\x02\x00\x00\x00\x60" + bytes(12) + b"\x0b\x02"
    )


async def test_authenticate_tag_rejects_a_bad_challenge(client: ChainwayClient) -> None:
    with pytest.raises(ValueError, match="challenge"):
        await client.authenticate_tag(bytes(9))


async def test_authenticate_tag_rejects_a_bad_key_id(client: ChainwayClient) -> None:
    with pytest.raises(ValueError, match="key ID"):
        await client.authenticate_tag(bytes(10), key_id=256)


async def test_set_protected_mode_sends_the_documented_payload(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    await client.set_protected_mode(protected=True, short_range=False, tag_filter=qt_filter())
    assert received(logic, Command.SET_PROTECTED_MODE) == bytes.fromhex(
        "000000000100200010E2800100"
    )
    await client.set_protected_mode(protected=False, short_range=True)
    assert received(logic, Command.SET_PROTECTED_MODE) == (
        b"\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x01"
    )


async def test_read_block_permalock_sends_the_documented_payload(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    data = await client.read_block_permalock(MemoryBank.USER, 0, 1)
    assert data == b"\xf0\x00"
    assert received(logic, Command.BLOCK_PERMALOCK_TAG) == (
        b"\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x03\x00\x00\x00\x01"
    )


async def test_read_block_permalock_with_a_filter(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    tag_filter = TagFilter(bank=MemoryBank.TID, bit_address=0, bit_length=96, data=bytes(12))
    await client.read_block_permalock(MemoryBank.USER, 0, 1, tag_filter=tag_filter)
    assert received(logic, Command.BLOCK_PERMALOCK_TAG) == (
        b"\x00\x00\x00\x00\x02\x00\x00\x00\x60" + bytes(12) + b"\x00\x03\x00\x00\x00\x01"
    )


async def test_read_block_permalock_rejects_a_short_data_response(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    logic._responders[Command.BLOCK_PERMALOCK_TAG] = lambda _payload: b"\x01\x00"
    with pytest.raises(ChainwayResponseError, match="promised"):
        await client.read_block_permalock(MemoryBank.USER, 0, 1)


async def test_set_block_permalock_sends_the_documented_payload(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    await client.set_block_permalock(MemoryBank.USER, 0, 1, 0xF000)
    assert received(logic, Command.BLOCK_PERMALOCK_TAG) == (
        b"\x00\x00\x00\x00\x01\x00\x00\x00\x00\x01\x03\x00\x00\x00\x01\xf0\x00"
    )


async def test_block_permalock_rejects_a_bad_window(client: ChainwayClient) -> None:
    with pytest.raises(ValueError, match="block pointer"):
        await client.read_block_permalock(MemoryBank.USER, -1, 1)
    with pytest.raises(ValueError, match="block range"):
        await client.read_block_permalock(MemoryBank.USER, 0, 0)


async def test_block_permalock_rejects_a_bad_mask(client: ChainwayClient) -> None:
    with pytest.raises(ValueError, match="mask"):
        await client.set_block_permalock(MemoryBank.USER, 0, 1, 0x10000)


async def test_qt_roundtrip(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    await client.set_qt(0x01, tag_filter=qt_filter())
    assert received(logic, Command.SET_QT) == bytes.fromhex("000000000100200010E28001")
    assert await client.get_qt(tag_filter=qt_filter()) == 0x01
    assert received(logic, Command.GET_QT) == bytes.fromhex("000000000100200010E280")


async def test_qt_read_and_write_send_the_documented_payload(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    data = await client.read_qt(0x01, MemoryBank.USER, 0, 2, tag_filter=qt_filter())
    assert data == b"\x11\x22\x33\x44"
    assert received(logic, Command.READ_QT) == bytes.fromhex("000000000100200010E280010300000002")
    await client.write_qt(0x01, MemoryBank.USER, 0, b"\x12\x34", tag_filter=qt_filter())
    assert received(logic, Command.WRITE_QT) == bytes.fromhex(
        "000000000100200010E2800103000000011234"
    )


async def test_qt_rejects_bad_values(client: ChainwayClient) -> None:
    with pytest.raises(ValueError, match="QT"):
        await client.set_qt(256)
    with pytest.raises(ValueError, match="QT"):
        await client.read_qt(256, MemoryBank.USER, 0, 2)
    with pytest.raises(ValueError, match="QT"):
        await client.write_qt(256, MemoryBank.USER, 0, b"\x12\x34")
    with pytest.raises(ValueError, match="even number"):
        await client.write_qt(0x01, MemoryBank.USER, 0, b"\x12")


async def test_read_qt_failure_raises(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    logic.failing_tag_commands = {Command.READ_QT}
    with pytest.raises(ChainwayResponseError, match="error code 0x01"):
        await client.read_qt(0x01, MemoryBank.USER, 0, 2)


async def test_deactivate_tag_sends_the_documented_payload(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    await client.deactivate_tag(tag_filter=qt_filter())
    assert received(logic, Command.DEACTIVATE_TAG) == bytes.fromhex("0000000000000100200010E280")


async def test_deactivate_tag_rejects_a_bad_command(client: ChainwayClient) -> None:
    with pytest.raises(ValueError, match="command"):
        await client.deactivate_tag(b"\x00")


async def test_set_dwell_time_sends_the_documented_payload(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    await client.set_dwell_time(1000, 3)
    assert received(logic, Command.SET_DWELL_TIME) == bytes.fromhex("000003E800000003")


async def test_set_dwell_time_rejects_a_bad_value(client: ChainwayClient) -> None:
    with pytest.raises(ValueError, match="dwell"):
        await client.set_dwell_time(-1, 3)
    with pytest.raises(ValueError, match="count"):
        await client.set_dwell_time(3, 1 << 32)


async def test_read_tag_sensor_sends_the_documented_payload(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    epc = bytes.fromhex("E2801160600002056B3A5A1E")
    data = await client.read_tag_sensor(SensorSubcommand.ON_CHIP_RSSI, epc, 1, 30.0)
    assert data == b"\x11\x22\x33\x44"
    assert received(logic, Command.SENSOR_CALIBRATION) == (
        b"\x03" + epc + b"\x00\x00\x00\x00" + b"\x01\x0b\xb8"
    )


async def test_read_tag_sensor_rejects_the_write_subcommand(client: ChainwayClient) -> None:
    with pytest.raises(ValueError, match="write calibration"):
        await client.read_tag_sensor(SensorSubcommand.WRITE_CALIBRATION, b"\x01", 1, 30.0)


async def test_write_tag_calibration_sends_the_documented_payload(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    epc = bytes.fromhex("E2801160600002056B3A5A1E")
    await client.write_tag_calibration(epc, 1, 30.0, bytes(8))
    assert received(logic, Command.SENSOR_CALIBRATION) == (
        b"\x06" + epc + b"\x00\x00\x00\x00" + b"\x01\x0b\xb8" + bytes(8)
    )


async def test_tag_sensor_logging(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    await client.start_tag_logging(qt_filter(), 0x50, 0x7A, 0, 0x0A)
    assert received(logic, Command.TAG_SENSOR) == (
        b"\x03\x01\x00\x20\x00\x10\xe2\x80\x00\x50\x00\x7a\x00\x00\x00\x0a"
    )
    await client.stop_tag_logging(qt_filter())
    assert received(logic, Command.TAG_SENSOR) == b"\x04\x01\x00\x20\x00\x10\xe2\x80"


async def test_tag_sensor_reads(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    assert await client.check_tag_sensor_mode(qt_filter()) == 1
    assert received(logic, Command.TAG_SENSOR) == b"\x05\x01\x00\x20\x00\x10\xe2\x80"
    assert await client.read_tag_sensor_voltage(qt_filter()) == 2.5
    assert received(logic, Command.TAG_SENSOR) == b"\x06\x01\x00\x20\x00\x10\xe2\x80"
    assert await client.read_tag_temperatures(qt_filter(), 0, 2) == (20.0, 30.5)
    assert received(logic, Command.TAG_SENSOR) == b"\x07\x01\x00\x20\x00\x10\xe2\x80\x00\x00\x02"


async def test_tag_sensor_rejects_bad_values(client: ChainwayClient) -> None:
    with pytest.raises(ValueError, match="temperature codes"):
        await client.start_tag_logging(qt_filter(), 0x400, 0x7A, 0, 0x0A)
    with pytest.raises(ValueError, match="delay and interval"):
        await client.start_tag_logging(qt_filter(), 0x50, 0x7A, -1, 0x0A)
    with pytest.raises(ValueError, match="start"):
        await client.read_tag_temperatures(qt_filter(), 0x10000, 1)
    with pytest.raises(ValueError, match="count"):
        await client.read_tag_temperatures(qt_filter(), 0, 0)


async def test_tag_sensor_failure_raises(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    logic.failing_tag_commands = {Command.TAG_SENSOR}
    with pytest.raises(ChainwayResponseError, match="error code 0x01"):
        await client.start_tag_logging(qt_filter(), 0x50, 0x7A, 0, 0x0A)


async def test_failing_tag_operation_raises(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    logic.failing_tag_commands = {Command.WRITE_TAG}
    with pytest.raises(ChainwayResponseError, match="error code 0x01"):
        await client.write_tag(MemoryBank.USER, 2, b"\xe2\x80")


async def test_read_tag_rejects_a_short_data_response(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    logic.read_tag_payload = b"\x01\x00\x00\x04\x11\x22"
    with pytest.raises(ChainwayResponseError, match="promised"):
        await client.read_tag(MemoryBank.USER, 2, 2)


async def test_collected_tags(client: ChainwayClient) -> None:
    collected = await client.read_collected_tags()
    assert collected.index == 5
    assert collected.tags == (b"\x11\x22\x33\x44\x55\x66", b"\xaa\xbb\xcc\xdd")


async def test_collected_tags_full(client: ChainwayClient) -> None:
    collected = await client.read_collected_tags_full()
    assert collected.index == 5
    assert len(collected.tags) == 2
    assert collected.tags[0].epc == bytes(range(1, 13))
    assert collected.tags[0].rssi == -29.8
    assert collected.tags[0].antenna is None


async def test_collected_tag_counts_and_delete(client: ChainwayClient) -> None:
    assert await client.get_collected_tag_count() == 2
    assert await client.get_new_collected_tag_count() == 2
    await client.delete_collected_tags()
    collected = await client.read_collected_tags_from_flash()
    assert collected == (b"\x11\x22\x33\x44\x55\x66", b"\xaa\xbb\xcc\xdd")


async def test_reader_address_with_mask_and_gateway(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    await client.set_reader_address(
        ReaderAddress(ip="10.0.0.5", port=5000, subnet_mask="255.255.255.0", gateway="10.0.0.1")
    )
    assert received(logic, Command.CONFIG) == (
        b"\x01\x0a\x00\x00\x05\x13\x88\xff\xff\xff\x00\x0a\x00\x00\x01"
    )
    address = await client.get_reader_address()
    assert address.ip == "10.0.0.5"
    assert address.port == 5000
    assert address.subnet_mask == "255.255.255.0"
    assert address.gateway == "10.0.0.1"


async def test_destination_address(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    await client.set_destination_address(ReaderAddress(ip="192.168.99.50", port=5084))
    assert received(logic, Command.CONFIG) == b"\x03\xc0\xa8\x63\x32\x13\xdc"
    address = await client.get_destination_address()
    assert address.ip == "192.168.99.50"
    assert address.port == 5084


async def test_work_mode_roundtrip(client: ChainwayClient) -> None:
    await client.set_work_mode(WorkMode.TRIGGER)
    assert await client.get_work_mode() is WorkMode.TRIGGER


async def test_buzzer_roundtrip(client: ChainwayClient) -> None:
    await client.set_buzzer(enabled=False)
    assert await client.get_buzzer() is False


async def test_gpo_set_sends_both_outputs_and_the_relay(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    await client.set_gpo(output_0=True, output_1=False, relay_closed=True)
    assert received(logic, Command.CONFIG) == b"\x09\x01\x00\x01"


async def test_gpi_reads_the_inputs_not_the_outputs(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    logic.gpi_state = b"\x00\x01"
    await client.set_gpo(output_0=True, output_1=True, relay_closed=True)
    state = await client.get_gpi()
    assert state.input_1 is False
    assert state.input_2 is True


async def test_trigger_config_roundtrip(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    config = TriggerConfig(
        input=TriggerInput.INPUT_2,
        work_time_ms=1000,
        min_interval_ms=100,
        output=OutputRoute.UDP,
    )
    await client.set_trigger_config(config)
    assert received(logic, Command.CONFIG) == b"\x0b\x01\x00\x64\x00\x0a\x01\x00"
    assert await client.get_trigger_config() == config


async def test_volume_roundtrip(client: ChainwayClient) -> None:
    await client.set_volume(7)
    assert await client.get_volume() == 7


async def test_scan_barcode_without_a_read(client: ChainwayClient) -> None:
    assert await client.scan_barcode() is None


async def test_scan_barcode_with_data(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    logic.barcode_payload = b"\x02" + b"12345678"
    assert await client.scan_barcode() == b"12345678"


async def test_beep(client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]) -> None:
    logic, _ = reader_server
    await client.beep(2)
    assert received(logic, Command.PERIPHERAL) == b"\x03\x01\x02"


async def test_stop_buzzer(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    await client.stop_buzzer()
    assert received(logic, Command.PERIPHERAL) == b"\x03\x00"


async def test_led(client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]) -> None:
    logic, _ = reader_server
    await client.set_led(enabled=True)
    assert received(logic, Command.PERIPHERAL) == b"\x07\x01\x00\x00\x00"
    await client.blink_led(10, 20, 30)
    assert received(logic, Command.PERIPHERAL) == b"\x07\x02\x0a\x14\x1e"


async def test_firmware_update_flow(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    await client.jump_to_bootloader()
    assert received(logic, Command.JUMP_TO_BOOTLOADER) == b"\xcc"
    await client.start_update()
    assert received(logic, Command.START_UPDATE) == b""
    await client.send_update_block(b"\x01\x02\x03")
    assert received(logic, Command.UPDATE_BLOCK) == b"\x01\x02\x03" + b"\x00" * 61
    await client.stop_update()
    assert received(logic, Command.STOP_UPDATE) == b""


async def test_jump_to_bootloader_targets(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    await client.jump_to_bootloader(BootloaderTarget.MAINBOARD)
    assert received(logic, Command.JUMP_TO_BOOTLOADER) == b"\xee"
    await client.jump_to_bootloader(BootloaderTarget.READER_BOOTLOADER)
    assert received(logic, Command.JUMP_TO_BOOTLOADER) == b"\xbb"
    await client.jump_to_bootloader(BootloaderTarget.EX10)
    assert received(logic, Command.JUMP_TO_BOOTLOADER) == b"\xaa"


async def test_inventory_streams_tags_and_stops(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    logic.tags_to_stream = [stream_tag_record(), stream_tag_record()]
    tags = []
    async with aclosing(client.inventory()) as stream:
        async for tag in stream:
            tags.append(tag)
            if len(tags) == 2:
                break
    assert len(tags) == 2
    assert tags[0].epc == bytes(range(1, 13))
    assert client.inventory_active is False
    assert received(logic, Command.STOP_INVENTORY) == b""


async def test_inventory_break_stops_the_scan(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    logic.tags_to_stream = [stream_tag_record()] * 5
    async with aclosing(client.inventory()) as stream:
        async for _tag in stream:
            break
    await asyncio.sleep(0.05)
    assert client.inventory_active is False
    assert Command.STOP_INVENTORY in commands_seen(logic)


async def test_commands_are_rejected_during_inventory(client: ChainwayClient) -> None:
    client._tag_queue = asyncio.Queue()
    client._inventory_active = True
    with pytest.raises(ChainwayInventoryActiveError):
        await client.get_version()
    client._inventory_active = False
    client._tag_queue = None


async def test_stop_inventory_is_a_noop_when_idle(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    await client.stop_inventory()
    assert commands_seen(logic) == [Command.STOP_INVENTORY]


async def test_inventory_phase_mode_reports_the_phase(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    record = b"\x34\x00" + bytes.fromhex("e2c45566a5030060705db2c7") + b"\x00\x3b\xfe\xc8\x01"
    logic.tags_to_stream = [record]
    tags = []
    async with aclosing(client.inventory(phase=True)) as stream:
        async for tag in stream:
            tags.append(tag)
            break
    assert tags[0].phase == 59
    starts = [payload for command, payload in logic.received if command == Command.START_INVENTORY]
    assert starts[-1] == b"\xff\xff"


async def test_inventory_frequency_mode_reports_the_frequency(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    record = b"\x30\x00" + bytes(range(1, 13)) + bytes.fromhex("0DF4C8") + b"\xfd\x6f\x01"
    logic.tags_to_stream = [record]
    tags = []
    async with aclosing(client.inventory(frequency=True)) as stream:
        async for tag in stream:
            tags.append(tag)
            break
    assert tags[0].phase is None
    assert tags[0].frequency_khz == 914632
    starts = [payload for command, payload in logic.received if command == Command.START_INVENTORY]
    assert starts[-1] == b"\xff\xfe"


async def test_inventory_phase_and_frequency_mode_reports_both(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    record = b"\x30\x00" + bytes(range(1, 13)) + bytes.fromhex("2A8C0DF4C8") + b"\xfd\x6f\x01"
    logic.tags_to_stream = [record]
    tags = []
    async with aclosing(client.inventory(phase=True, frequency=True)) as stream:
        async for tag in stream:
            tags.append(tag)
            break
    assert tags[0].phase == 0x2A8C
    assert tags[0].frequency_khz == 914632
    starts = [payload for command, payload in logic.received if command == Command.START_INVENTORY]
    assert starts[-1] == b"\xff\xfd"


async def test_malformed_tag_record_is_dropped_and_the_stream_survives(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    logic.tags_to_stream = [b"\x30\x00", stream_tag_record()]
    tags = []
    async with aclosing(client.inventory()) as stream:
        async for tag in stream:
            tags.append(tag)
            break
    assert len(tags) == 1


async def test_sync_on_tag_callback_fires_outside_an_inventory_run(
    reader_server: tuple[FakeReaderLogic, int],
) -> None:
    logic, port = reader_server
    seen: list[bytes] = []

    def on_tag(tag: object) -> None:
        seen.append(tag.epc)  # type: ignore[attr-defined]

    client = ChainwayClient(
        f"socket://127.0.0.1:{port}",
        keepalive_interval=60.0,
        dead_link_timeout=60.0,
        on_tag=on_tag,
    )
    await client.connect()
    try:
        await wait_for_server(logic)
        assert logic.push is not None
        logic.push(build_frame(0x83, stream_tag_record()))
        await asyncio.sleep(0.05)
        assert seen == [bytes(range(1, 13))]
    finally:
        await client.disconnect()


async def test_async_on_tag_callback_runs_as_a_task(
    reader_server: tuple[FakeReaderLogic, int],
) -> None:
    logic, port = reader_server
    seen: list[bytes] = []

    async def on_tag(tag: object) -> None:
        seen.append(tag.epc)  # type: ignore[attr-defined]

    client = ChainwayClient(
        f"socket://127.0.0.1:{port}",
        keepalive_interval=60.0,
        dead_link_timeout=60.0,
        on_tag=on_tag,
    )
    await client.connect()
    try:
        await wait_for_server(logic)
        assert logic.push is not None
        logic.push(build_frame(0x83, stream_tag_record()))
        await asyncio.sleep(0.05)
        assert seen == [bytes(range(1, 13))]
    finally:
        await client.disconnect()


async def test_manual_scan_sends_tags_to_the_callback(
    reader_server: tuple[FakeReaderLogic, int],
) -> None:
    logic, port = reader_server
    logic.tags_to_stream = [stream_tag_record()] * 3
    seen: list[bytes] = []
    client = ChainwayClient(
        f"socket://127.0.0.1:{port}",
        keepalive_interval=60.0,
        dead_link_timeout=60.0,
        on_tag=lambda tag: seen.append(tag.epc),
    )
    await client.connect()
    try:
        await client.start_inventory()
        for _ in range(50):
            if len(seen) == 3:
                break
            await asyncio.sleep(0.02)
        assert seen == [bytes(range(1, 13))] * 3
        assert client._tag_queue is None
    finally:
        await client.stop_inventory()
        await client.disconnect()


async def test_inventory_takes_over_a_manual_scan(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    logic.tags_to_stream = []
    await client.start_inventory()
    assert client._tag_queue is None
    async with aclosing(client.inventory()) as stream:
        consumer = asyncio.create_task(anext(stream))
        await asyncio.sleep(0.05)
        assert logic.push is not None
        logic.push(build_frame(0x83, stream_tag_record()))
        tag = await consumer
    assert tag.epc == bytes(range(1, 13))
    assert client.inventory_active is False
    starts = [command for command, _ in logic.received if command == Command.START_INVENTORY]
    assert len(starts) == 1


async def test_tag_without_a_callback_or_queue_is_ignored(
    reader_server: tuple[FakeReaderLogic, int],
) -> None:
    logic, port = reader_server
    client = ChainwayClient(
        f"socket://127.0.0.1:{port}",
        keepalive_interval=60.0,
        dead_link_timeout=60.0,
    )
    await client.connect()
    try:
        await wait_for_server(logic)
        assert logic.push is not None
        logic.push(build_frame(0x83, stream_tag_record()))
        await asyncio.sleep(0.05)
        assert await client.get_version() == FirmwareVersion(1, 2, 3)
    finally:
        await client.disconnect()


async def test_lazy_connect_on_first_command(
    make_client: Callable[..., ChainwayClient],
) -> None:
    client = make_client()
    assert client.connected is False
    assert await client.get_version() == FirmwareVersion(1, 2, 3)
    assert client.connected is True
    await client.disconnect()


async def test_response_timeout(
    make_client: Callable[..., ChainwayClient],
    reader_server: tuple[FakeReaderLogic, int],
) -> None:
    logic, _ = reader_server
    logic.silent_commands = {Command.GET_TEMPERATURE}
    client = make_client(response_timeout=0.1)
    await client.connect()
    try:
        with pytest.raises(ChainwayTimeoutError, match="no response"):
            await client.get_temperature()
    finally:
        await client.disconnect()


async def test_connection_lost_callback_and_lazy_reconnect(
    reader_server: tuple[FakeReaderLogic, int],
) -> None:
    logic, port = reader_server
    lost: list[Exception] = []

    async def on_connection_lost(error: Exception) -> None:
        lost.append(error)

    client = ChainwayClient(
        f"socket://127.0.0.1:{port}",
        keepalive_interval=60.0,
        dead_link_timeout=60.0,
        on_connection_lost=on_connection_lost,
    )
    await client.connect()
    await wait_for_server(logic)
    assert logic.close_transport is not None
    logic.close_transport()
    await asyncio.sleep(0.1)
    assert client.connected is False
    assert len(lost) == 1
    assert isinstance(lost[0], ChainwayConnectionError)
    assert await client.get_version() == FirmwareVersion(1, 2, 3)
    assert client.connected is True
    await client.disconnect()


async def test_pending_command_fails_when_the_link_drops(
    reader_server: tuple[FakeReaderLogic, int],
) -> None:
    logic, port = reader_server
    client = ChainwayClient(
        f"socket://127.0.0.1:{port}",
        response_timeout=5.0,
        keepalive_interval=60.0,
        dead_link_timeout=60.0,
    )
    await client.connect()
    logic.drop_connection_commands = {Command.GET_TEMPERATURE}
    try:
        with pytest.raises(ChainwayConnectionError):
            await client.get_temperature()
    finally:
        await client.disconnect()


async def test_inventory_raises_when_the_link_drops_mid_scan(
    reader_server: tuple[FakeReaderLogic, int],
) -> None:
    logic, port = reader_server
    client = ChainwayClient(
        f"socket://127.0.0.1:{port}",
        keepalive_interval=60.0,
        dead_link_timeout=60.0,
    )
    await client.connect()
    logic.tags_to_stream = [stream_tag_record()]
    try:

        async def fail_scan() -> None:
            async for _tag in client.inventory():
                assert logic.close_transport is not None
                logic.close_transport()

        with pytest.raises(ChainwayConnectionError):
            await fail_scan()
    finally:
        await client.disconnect()


async def test_idle_keepalive_polls_the_version(
    reader_server: tuple[FakeReaderLogic, int],
) -> None:
    logic, port = reader_server
    client = ChainwayClient(
        f"socket://127.0.0.1:{port}",
        keepalive_interval=0.05,
        dead_link_timeout=60.0,
    )
    await client.connect()
    try:
        await asyncio.sleep(0.3)
        version_requests = [
            command for command, _ in logic.received if command == Command.GET_VERSION
        ]
        assert len(version_requests) >= 2
    finally:
        await client.disconnect()


async def test_inventory_keepalive_sends_the_bare_byte(
    reader_server: tuple[FakeReaderLogic, int],
) -> None:
    logic, port = reader_server
    client = ChainwayClient(
        f"socket://127.0.0.1:{port}",
        keepalive_interval=0.05,
        dead_link_timeout=60.0,
    )
    await client.connect()
    try:
        await client.start_inventory()
        await asyncio.sleep(0.3)
        assert Command.GET_VERSION not in commands_seen(logic)
        assert b"\x00" in logic.raw
    finally:
        await client.stop_inventory()
        await client.disconnect()


async def test_dead_link_watchdog_drops_a_silent_link(
    reader_server: tuple[FakeReaderLogic, int],
) -> None:
    logic, port = reader_server
    lost: list[Exception] = []

    async def on_connection_lost(error: Exception) -> None:
        lost.append(error)

    client = ChainwayClient(
        f"socket://127.0.0.1:{port}",
        keepalive_interval=5.0,
        dead_link_timeout=0.15,
        on_connection_lost=on_connection_lost,
    )
    await client.connect()
    try:
        await asyncio.sleep(0.5)
        assert client.connected is False
        assert len(lost) == 1
        assert "silent" in str(lost[0])
    finally:
        await client.disconnect()


async def test_disconnect_ends_the_link(client: ChainwayClient) -> None:
    await client.disconnect()
    assert client.connected is False
    await client.disconnect()


async def test_context_manager_connects_and_disconnects(
    make_client: Callable[..., ChainwayClient],
) -> None:
    client = make_client()
    async with client:
        assert client.connected is True
        assert await client.get_version() == FirmwareVersion(1, 2, 3)
    assert client.connected is False


async def test_junk_on_connect_is_resynced(
    reader_server: tuple[FakeReaderLogic, int],
) -> None:
    logic, port = reader_server
    logic.junk_on_connect = b"\x00\x01\x02garbage"
    client = ChainwayClient(
        f"socket://127.0.0.1:{port}",
        keepalive_interval=60.0,
        dead_link_timeout=60.0,
    )
    await client.connect()
    try:
        assert await client.get_version() == FirmwareVersion(1, 2, 3)
    finally:
        await client.disconnect()


async def test_bad_checksum_response_times_out_and_the_retry_works(
    reader_server: tuple[FakeReaderLogic, int],
) -> None:
    logic, port = reader_server
    client = ChainwayClient(
        f"socket://127.0.0.1:{port}",
        response_timeout=0.2,
        keepalive_interval=60.0,
        dead_link_timeout=60.0,
    )
    await client.connect()
    try:
        logic.bad_checksum_commands = {Command.GET_REGION}
        with pytest.raises(ChainwayTimeoutError):
            await client.get_region()
        logic.bad_checksum_commands = set()
        assert await client.get_region() is Region.USA
    finally:
        await client.disconnect()


async def test_connect_failure_raises_a_connection_error() -> None:
    client = ChainwayClient("socket://127.0.0.1:1")
    with pytest.raises(ChainwayConnectionError, match="could not open"):
        await client.connect()


@pytest.mark.parametrize("url", ["socket://127.0.0.1", "socket://127.0.0.1:99999"])
async def test_malformed_url_raises_a_connection_error(url: str) -> None:
    client = ChainwayClient(url)
    with pytest.raises(ChainwayConnectionError, match="could not open"):
        await client.connect()
    assert client.connected is False


async def test_second_connect_is_a_noop(client: ChainwayClient) -> None:
    await client.connect()
    assert client.connected is True


async def test_stray_unsolicited_frame_is_ignored(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    assert logic.push is not None
    logic.push(build_frame(0x35, b"\x01\x10\x0e"))
    await asyncio.sleep(0.02)
    assert await client.get_version() == FirmwareVersion(1, 2, 3)
