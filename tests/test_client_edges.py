"""Edge case tests that close the defensive branches of the client."""

import asyncio

import pytest

from chainway_serial import (
    ChainwayClient,
    ChainwayConnectionError,
    ChainwayResponseError,
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


async def test_failing_ack_raises(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    logic._responders[Command.SOFT_RESET] = lambda _payload: b"\x00"
    with pytest.raises(ChainwayResponseError, match="not acknowledged"):
        await client.soft_reset()


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


async def test_get_reader_address_roundtrip(client: ChainwayClient) -> None:
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


async def test_iterator_raises_when_the_queue_was_cleared(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    logic.tags_to_stream = [b"\x30\x00" + bytes(range(1, 13)) + b"\xfe\xd6\x00"]
    stream = client.inventory()
    await _anext(stream)
    await client.stop_inventory()
    with pytest.raises(ChainwayConnectionError, match="the link was lost"):
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
