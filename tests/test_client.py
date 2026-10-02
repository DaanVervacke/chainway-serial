"""End to end client tests against a scripted fake reader over TCP."""

import asyncio
from collections.abc import Callable
from contextlib import aclosing

import pytest

from chainway_serial import (
    ChainwayClient,
    ChainwayConnectionError,
    ChainwayInventoryActiveError,
    ChainwayResponseError,
    ChainwayTimeoutError,
    FirmwareVersion,
    InventoryMode,
    LockBank,
    LockMode,
    MemoryBank,
    OutputRoute,
    ProtocolType,
    Region,
    RfLink,
    TagFilter,
    TriggerConfig,
    TriggerInput,
    WorkMode,
)
from chainway_serial.const import Command
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


async def test_get_version(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    assert await client.get_version() == FirmwareVersion(1, 2, 3)
    assert received(logic, Command.GET_VERSION) == b""


async def test_get_stm32_version(client: ChainwayClient) -> None:
    assert await client.get_stm32_version() == FirmwareVersion(1, 0, 1)


async def test_get_module_version(client: ChainwayClient) -> None:
    assert await client.get_module_version() == FirmwareVersion(0, 1, 2)


async def test_get_temperature(client: ChainwayClient) -> None:
    assert await client.get_temperature() == 41.1


async def test_get_antenna_connection_state(client: ChainwayClient) -> None:
    state = await client.get_antenna_connection_state()
    assert state.connected == (True, True, False, False, False, False, False, False)
    assert state.raw == b"\x00\x03"


async def test_get_battery_level(client: ChainwayClient) -> None:
    assert await client.get_battery_level() == 100


async def test_set_rf_power_sends_the_documented_payload(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    await client.set_rf_power(30.0, antenna=1)
    assert received(logic, Command.SET_POWER) == b"\x02\x01\x0b\xb8\x0b\xb8"


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


async def test_region(client: ChainwayClient) -> None:
    await client.set_region(Region.USA, save=False)
    assert await client.get_region() is Region.USA


async def test_carrier_wave(client: ChainwayClient) -> None:
    await client.set_carrier_wave(enabled=True)
    assert await client.get_carrier_wave() is True


async def test_gen2_roundtrip(client: ChainwayClient) -> None:
    await client.set_gen2_parameters(Gen2Parameters(target=3, session=2))
    assert (await client.get_gen2_parameters()).target == 4


async def test_rf_link(client: ChainwayClient) -> None:
    await client.set_rf_link(RfLink.DSB_ASK_FM0_400_KHZ, save=True)
    assert await client.get_rf_link() is RfLink.PR_ASK_MILLER_4_300_KHZ


async def test_fast_id(client: ChainwayClient) -> None:
    await client.set_fast_id(enabled=False)
    assert await client.get_fast_id() is True


async def test_tag_focus(client: ChainwayClient) -> None:
    await client.set_tag_focus(enabled=True)
    assert await client.get_tag_focus() is True


async def test_protocol_type_roundtrip(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    await client.set_protocol_type(ProtocolType.GB_T_29768)
    assert received(logic, Command.SET_PROTOCOL_TYPE) == b"\x00\x01"
    assert await client.get_protocol_type() is ProtocolType.GB_T_29768


async def test_inventory_mode_roundtrip(client: ChainwayClient) -> None:
    await client.set_inventory_mode(
        InventoryMode.EPC_TID_USER, user_address=2, user_length=4, save=False
    )
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


async def test_antenna_work_time_roundtrip(client: ChainwayClient) -> None:
    await client.set_antenna_work_time(1, 200, save=False)
    assert await client.get_antenna_work_time(1) == 200


async def test_fast_inventory_mode(client: ChainwayClient) -> None:
    await client.set_fast_inventory_mode(enabled=False)
    assert await client.get_fast_inventory_mode() is True


async def test_soft_reset(client: ChainwayClient) -> None:
    await client.soft_reset()


async def test_single_inventory(client: ChainwayClient) -> None:
    tag = await client.single_inventory()
    assert tag is not None
    assert tag.epc == bytes(range(1, 13))
    assert tag.rssi == -29.7
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


async def test_block_write_and_erase(client: ChainwayClient) -> None:
    await client.block_write_tag(MemoryBank.USER, 2, b"\xe2\x80")
    await client.block_erase_tag(MemoryBank.USER, 2, 1)


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


async def test_failing_tag_operation_raises(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    logic.failing_tag_commands = {Command.WRITE_TAG}
    with pytest.raises(ChainwayResponseError, match="error code 1"):
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


async def test_collected_tag_counts_and_delete(client: ChainwayClient) -> None:
    assert await client.get_collected_tag_count() == 2
    assert await client.get_new_collected_tag_count() == 2
    await client.delete_collected_tags()
    collected = await client.read_collected_tags_from_flash()
    assert collected == (b"\x11\x22\x33\x44\x55\x66", b"\xaa\xbb\xcc\xdd")


async def test_reader_address_with_mask_and_gateway(client: ChainwayClient) -> None:
    await client.set_reader_address(
        ReaderAddress(ip="10.0.0.5", port=5000, subnet_mask="255.255.255.0", gateway="10.0.0.1")
    )


async def test_destination_address(client: ChainwayClient) -> None:
    await client.set_destination_address(ReaderAddress(ip="192.168.99.50", port=5084))
    address = await client.get_destination_address()
    assert address.ip == "192.168.99.201"
    assert address.port == 5000


async def test_work_mode_roundtrip(client: ChainwayClient) -> None:
    await client.set_work_mode(WorkMode.TRIGGER)
    assert await client.get_work_mode() is WorkMode.TRIGGER


async def test_buzzer_roundtrip(client: ChainwayClient) -> None:
    await client.set_buzzer(enabled=False)
    assert await client.get_buzzer() is False


async def test_gpo_roundtrip(client: ChainwayClient) -> None:
    await client.set_gpo(output_0=True, output_1=False, relay_closed=True)
    state = await client.get_gpo()
    assert state.output_0 is True
    assert state.output_1 is False


async def test_trigger_config_roundtrip(client: ChainwayClient) -> None:
    config = TriggerConfig(
        input=TriggerInput.INPUT_2,
        work_time_ms=1000,
        min_interval_ms=100,
        output=OutputRoute.UDP,
    )
    await client.set_trigger_config(config)
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


async def test_beep(client: ChainwayClient) -> None:
    await client.beep(2)


async def test_led(client: ChainwayClient) -> None:
    await client.set_led(enabled=True)
    await client.blink_led(10, 20, 30)


async def test_firmware_update_flow(client: ChainwayClient) -> None:
    await client.jump_to_bootloader()
    await client.start_update()
    await client.send_update_block(b"\x01\x02\x03")
    await client.stop_update()


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
    assert Command.STOP_INVENTORY not in commands_seen(logic)


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
        assert b"\x00" in b"".join(logic.raw)
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
