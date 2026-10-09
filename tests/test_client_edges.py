"""Edge case tests that close the defensive branches of the client."""

import asyncio
from collections.abc import Callable

import pytest

from chainway_serial import (
    ChainwayClient,
    ChainwayConnectionError,
    ChainwayResponseError,
    ChainwayTimeoutError,
    FirmwareVersion,
    InventoryMode,
    MemoryBank,
    ProtocolType,
)
from chainway_serial.const import Command
from chainway_serial.frames import build_frame

from .conftest import wait_for_server
from .fake_reader import FakeReaderLogic


async def _anext(stream: object) -> object:
    return await stream.__anext__()  # type: ignore[attr-defined]


async def test_config_set_waits_out_the_commit_mute(
    client: ChainwayClient,
    reader_server: tuple[FakeReaderLogic, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logic, _ = reader_server
    logic.commit_mute = 0.2
    monkeypatch.setattr("chainway_serial.client.CONFIG_COMMIT_DELAY", 0.3)
    await client.set_buzzer(enabled=False)
    assert await client.get_buzzer() is False
    assert logic.dropped == []


async def test_without_the_settle_delay_the_reader_drops_the_next_request(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    logic.commit_mute = 0.3
    client.response_timeout = 0.1
    await client.set_buzzer(enabled=False)
    with pytest.raises(ChainwayTimeoutError):
        await client.get_version()
    assert logic.dropped == [(Command.GET_VERSION, b"")]


async def test_rejected_config_set_does_not_start_a_settle_window(
    client: ChainwayClient,
    reader_server: tuple[FakeReaderLogic, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logic, _ = reader_server
    monkeypatch.setattr("chainway_serial.client.CONFIG_COMMIT_DELAY", 5.0)
    logic._config_responders[0x07] = lambda _payload: b"\x00"
    with pytest.raises(ChainwayResponseError):
        await client.set_buzzer(enabled=False)
    assert client._quiet_until == 0.0


async def test_gpo_set_does_not_start_a_settle_window(
    client: ChainwayClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("chainway_serial.client.CONFIG_COMMIT_DELAY", 5.0)
    await client.set_gpo(output_0=True, output_1=False, relay_closed=False)
    assert client._quiet_until == 0.0


async def test_dead_link_fires_the_callback_exactly_once(
    make_client: Callable[..., ChainwayClient],
) -> None:
    lost: list[Exception] = []
    client = make_client(dead_link_timeout=0.2)
    client.on_connection_lost = lost.append
    await client.connect()
    for _ in range(100):
        await asyncio.sleep(0.02)
        if lost:
            break
    assert lost
    client._schedule_drop_link(ChainwayConnectionError("race"))
    await asyncio.sleep(0.1)
    assert len(lost) == 1
    await client.disconnect()
    assert len(lost) == 1


async def test_os_level_link_failure_reaches_the_callback_as_a_chainway_error(
    client: ChainwayClient,
) -> None:
    lost: list[Exception] = []
    client.on_connection_lost = lost.append
    cause = OSError(6, "Device not configured")
    client._schedule_drop_link(cause)
    for _ in range(100):
        await asyncio.sleep(0.02)
        if lost:
            break
    assert len(lost) == 1
    assert isinstance(lost[0], ChainwayConnectionError)
    assert lost[0].__cause__ is cause
    assert "Device not configured" in str(lost[0])


async def test_explicit_disconnect_swallows_late_drop_callbacks(
    make_client: Callable[..., ChainwayClient],
) -> None:
    lost: list[Exception] = []
    client = make_client(dead_link_timeout=60.0)
    client.on_connection_lost = lost.append
    await client.connect()
    await client.disconnect()
    client._schedule_drop_link(ChainwayConnectionError("late"))
    await asyncio.sleep(0.05)
    assert lost == []


async def test_reader_side_close_fires_the_callback_once(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    lost: list[Exception] = []
    client.on_connection_lost = lost.append
    assert logic.close_transport is not None
    logic.close_transport()
    for _ in range(100):
        await asyncio.sleep(0.02)
        if lost:
            break
    assert len(lost) == 1
    assert not client.connected


async def test_failing_volume_ack_raises(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    logic._config_responders[0x11] = lambda _payload: b"\x11\x02"
    with pytest.raises(ChainwayResponseError, match="not acknowledged"):
        await client.set_volume(5)


async def test_return_loss_rejects_a_malformed_response(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    logic._responders[Command.GET_RETURN_LOSS] = lambda _payload: b"\x01"
    with pytest.raises(ChainwayResponseError, match="return loss"):
        await client.get_return_loss()
    logic._responders[Command.GET_RETURN_LOSS] = lambda _payload: b""
    assert await client.get_return_loss() == ()


async def test_volume_accepts_the_echoed_subcommand_ack(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    logic._config_responders[0x11] = lambda _payload: b"\x11\x01"
    await client.set_volume(5)


async def test_reader_idle_sleep_time_roundtrip(client: ChainwayClient) -> None:
    await client.set_reader_idle_sleep_time(12)
    assert await client.get_reader_idle_sleep_time() == 12


async def test_set_reader_idle_sleep_time_rejects_a_bad_value(client: ChainwayClient) -> None:
    with pytest.raises(ValueError, match="idle sleep time"):
        await client.set_reader_idle_sleep_time(256)


async def test_dead_link_watchdog_stays_suspended_during_a_scan(
    reader_server: tuple[FakeReaderLogic, int],
) -> None:
    logic, port = reader_server
    client = ChainwayClient(
        f"socket://127.0.0.1:{port}",
        keepalive_interval=60.0,
        dead_link_timeout=0.1,
    )
    await client.connect()
    await wait_for_server(logic)
    logic.tags_to_stream = []
    try:
        await client.start_inventory()
        await asyncio.sleep(0.3)
        assert client.connected is True
        assert client.inventory_active is True
    finally:
        await client.stop_inventory()
        await client.disconnect()


async def test_failing_ack_raises(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    logic._responders[Command.RESTORE_FACTORY_SETTINGS] = lambda _payload: b"\x00"
    with pytest.raises(ChainwayResponseError, match="not acknowledged"):
        await client.restore_factory_settings()


async def test_failing_protocol_type_ack_raises(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    logic._responders[Command.SET_PROTOCOL_TYPE] = lambda _payload: b"\x00\x02"
    with pytest.raises(ChainwayResponseError, match="not acknowledged"):
        await client.set_protocol_type(ProtocolType.ISO_18000_6C)


async def test_failing_delete_ack_raises(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    logic._responders[Command.FLASH_STORAGE] = lambda _payload: b"\x00\x01"
    with pytest.raises(ChainwayResponseError, match="not acknowledged"):
        await client.delete_collected_tags()


async def test_set_antenna_power_rejects_a_bad_value(client: ChainwayClient) -> None:
    with pytest.raises(ValueError, match="power"):
        await client.set_antenna_power(2, 31.0, 20.0)


async def test_set_fixed_frequency_rejects_a_bad_value(client: ChainwayClient) -> None:
    with pytest.raises(ValueError, match="frequency"):
        await client.set_fixed_frequency(0x1000000)


async def test_set_inventory_mode_rejects_a_bad_window(client: ChainwayClient) -> None:
    with pytest.raises(ValueError, match="USER window"):
        await client.set_inventory_mode(InventoryMode.EPC_TID_USER, user_address=256)


async def test_set_antenna_mask_rejects_a_bad_mask(client: ChainwayClient) -> None:
    with pytest.raises(ValueError, match="mask"):
        await client.set_antenna_mask(0x10000)


async def test_set_antenna_work_time_rejects_a_bad_antenna(client: ChainwayClient) -> None:
    with pytest.raises(ValueError, match="antenna"):
        await client.set_antenna_work_time(17, 100)


async def test_set_antenna_work_time_rejects_a_bad_time(client: ChainwayClient) -> None:
    with pytest.raises(ValueError, match="work time"):
        await client.set_antenna_work_time(1, 0x10000)


async def test_get_antenna_work_time_rejects_a_bad_antenna(client: ChainwayClient) -> None:
    with pytest.raises(ValueError, match="antenna"):
        await client.get_antenna_work_time(0)


async def test_set_volume_rejects_a_bad_value(client: ChainwayClient) -> None:
    with pytest.raises(ValueError, match="volume"):
        await client.set_volume(256)


async def test_beep_rejects_a_bad_duration(client: ChainwayClient) -> None:
    with pytest.raises(ValueError, match="duration"):
        await client.beep(-1)


async def test_blink_led_rejects_a_bad_color(client: ChainwayClient) -> None:
    with pytest.raises(ValueError, match="red"):
        await client.blink_led(256, 0, 0)


async def test_send_update_block_rejects_a_long_block(client: ChainwayClient) -> None:
    with pytest.raises(ValueError, match="block"):
        await client.send_update_block(b"\x00" * 65)


async def test_block_write_rejects_odd_data(client: ChainwayClient) -> None:
    with pytest.raises(ValueError, match="even number"):
        await client.block_write_tag(MemoryBank.USER, 2, b"\xe2")


async def test_get_reader_address_returns_the_configured_default(client: ChainwayClient) -> None:
    address = await client.get_reader_address()
    assert address.ip == "192.168.99.200"
    assert address.port == 8888


async def test_start_inventory_twice_is_a_noop(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    logic.tags_to_stream = []
    await client.start_inventory()
    await asyncio.sleep(0.02)
    await client.start_inventory()
    await asyncio.sleep(0.02)
    starts = [command for command, _ in logic.received if command == Command.START_INVENTORY]
    assert len(starts) == 1
    await client.stop_inventory()


async def test_start_inventory_with_a_closed_link(
    client: ChainwayClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def no_connect() -> None:
        return

    monkeypatch.setattr(client, "_ensure_connected", no_connect)
    real_transport = client._transport
    client._transport = None
    with pytest.raises(ChainwayConnectionError, match="the link is closed"):
        await client.start_inventory()
    client._transport = real_transport


async def test_request_with_a_closed_link(
    client: ChainwayClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def no_connect() -> None:
        return

    monkeypatch.setattr(client, "_ensure_connected", no_connect)
    real_transport = client._transport
    client._transport = None
    with pytest.raises(ChainwayConnectionError, match="the link is closed"):
        await client.get_version()
    client._transport = real_transport


async def test_stop_inventory_without_a_queue(client: ChainwayClient) -> None:
    client._inventory_active = True
    client._tag_queue = None
    await client.stop_inventory()
    assert client.inventory_active is False


async def test_external_stop_after_a_yield_ends_the_iterator(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    logic.tags_to_stream = [b"\x30\x00" + bytes(range(1, 13)) + b"\xfe\xd6\x00"]
    stream = client.inventory()
    await _anext(stream)
    await client.stop_inventory()
    with pytest.raises(StopAsyncIteration):
        await _anext(stream)
    await stream.aclose()


async def test_external_stop_ends_a_waiting_iterator(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    logic.tags_to_stream = []
    stream = client.inventory()
    consumer = asyncio.create_task(_anext(stream))
    await asyncio.sleep(0.05)
    await client.stop_inventory()
    with pytest.raises(StopAsyncIteration):
        await consumer
    await stream.aclose()


async def test_inventory_raises_when_the_start_lost_the_link(
    client: ChainwayClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def lost_start(*, phase: bool = False, frequency: bool = False) -> None:  # noqa: ARG001
        return

    monkeypatch.setattr(client, "start_inventory", lost_start)
    stream = client.inventory()
    with pytest.raises(ChainwayConnectionError, match="the link was lost"):
        await _anext(stream)


async def test_a_failed_stop_still_clears_the_scan_and_releases_the_iterator(
    reader_server: tuple[FakeReaderLogic, int],
) -> None:
    logic, port = reader_server
    logic.tags_to_stream = []
    client = ChainwayClient(
        f"socket://127.0.0.1:{port}",
        response_timeout=0.2,
        keepalive_interval=60.0,
        dead_link_timeout=60.0,
    )
    await client.connect()
    stream = client.inventory()
    consumer = asyncio.create_task(_anext(stream))
    await asyncio.sleep(0.05)
    logic.silent_commands = {Command.STOP_INVENTORY}
    try:
        with pytest.raises(ChainwayTimeoutError, match="no response"):
            await client.stop_inventory()
        with pytest.raises(StopAsyncIteration):
            await consumer
        assert client.inventory_active is False
        assert await client.get_version() == FirmwareVersion(1, 2, 3)
    finally:
        await stream.aclose()
        await client.disconnect()


async def test_response_for_a_done_future_is_ignored(client: ChainwayClient) -> None:
    future: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
    future.set_result(b"done")
    client._pending = (0x03, future)
    client._handle_frame(0x03, b"\x01\x02\x03")
    assert future.result() == b"done"
    client._pending = None


async def test_maintenance_stops_without_a_protocol(client: ChainwayClient) -> None:
    client._protocol = None
    await asyncio.sleep(0.1)
    assert client.connected is True
    await client.disconnect()


async def test_maintenance_skips_the_keepalive_write_without_a_transport(
    reader_server: tuple[FakeReaderLogic, int],
) -> None:
    logic, port = reader_server
    client = ChainwayClient(
        f"socket://127.0.0.1:{port}",
        keepalive_interval=0.05,
        dead_link_timeout=60.0,
    )
    await client.connect()
    await wait_for_server(logic)
    real_transport = client._transport
    maintenance = client._maintenance_task
    assert maintenance is not None
    try:
        client._inventory_active = True
        client._transport = None
        await asyncio.sleep(0.15)
        assert not maintenance.done()
    finally:
        client._inventory_active = False
        client._transport = real_transport
        await client.disconnect()


async def test_failing_callback_task_logs_and_continues(
    reader_server: tuple[FakeReaderLogic, int],
) -> None:
    logic, port = reader_server

    async def on_tag(_tag: object) -> None:
        msg = "callback boom"
        raise RuntimeError(msg)

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
        logic.push(build_frame(0x83, b"\x30\x00" + bytes(range(1, 13)) + b"\xfe\xd6\x00"))
        await asyncio.sleep(0.1)
        assert client.connected is True
    finally:
        await client.disconnect()


async def test_failing_sync_on_tag_callback_is_contained(
    reader_server: tuple[FakeReaderLogic, int],
) -> None:
    logic, port = reader_server
    seen: list[bytes] = []

    def on_tag(tag: object) -> None:
        seen.append(tag.epc)  # type: ignore[attr-defined]
        msg = "callback boom"
        raise RuntimeError(msg)

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
        record = b"\x30\x00" + bytes(range(1, 13)) + b"\xfe\xd6\x00"
        logic.push(build_frame(0x83, record) + build_frame(0x83, record))
        await asyncio.sleep(0.05)
        assert seen == [bytes(range(1, 13)), bytes(range(1, 13))]
        assert await client.get_version() == FirmwareVersion(1, 2, 3)
    finally:
        await client.disconnect()
