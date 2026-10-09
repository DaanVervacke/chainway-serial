"""Live verification of the ChainwayClient against real hardware.

The tests run in file order and finish with a factory restore, so a
full run leaves the reader in its baseline state. The buzzer setting
from before the run is written back after the restore. Expected wire
behavior is documented in docs/protocol.md under live verification.
"""

import asyncio
from contextlib import aclosing, suppress

import pytest

from chainway_serial import (
    ChainwayClient,
    ChainwayInventoryActiveError,
    ChainwayResponseError,
    ChainwayTimeoutError,
    InventoryMode,
    ProtocolType,
    Region,
    RfLink,
    TriggerConfig,
    UartBaudRate,
    WorkMode,
)
from chainway_serial.models import OutputRoute, TriggerInput

PARTIAL_FRAME = b"\xa5\x5a\x00\xff\x02\xff\x0d\x0a"


async def test_identity_reads(client: ChainwayClient) -> None:
    version = await client.get_version()
    assert version.major == 7
    assert await client.get_stm32_version() is not None
    assert await client.get_hardware_version() is not None
    assert len(await client.get_device_id()) == 4


async def test_status_reads(client: ChainwayClient) -> None:
    assert isinstance(await client.get_temperature(), float)
    assert await client.get_antenna_connection_state() is not None
    assert await client.get_gen2_parameters() is not None


async def test_config_reads(client: ChainwayClient) -> None:
    assert await client.get_region() is not None
    assert len(await client.get_rf_power()) == 4
    assert await client.get_rf_link() is not None
    assert isinstance(await client.get_fast_id(), bool)
    assert isinstance(await client.get_tag_focus(), bool)
    assert await client.get_inventory_mode() is not None
    assert await client.get_antenna_mask() is not None
    assert await client.get_work_mode() is WorkMode.COMMAND


async def test_rf_power_write_leaves_lower_antennas_alone(
    client: ChainwayClient,
) -> None:
    before = await client.get_rf_power()
    original = before[1].write_power_dbm
    await client.set_rf_power(25.0, antenna=2, save=False)
    after = await client.get_rf_power()
    assert after[0].write_power_dbm == before[0].write_power_dbm
    assert after[1].write_power_dbm == 25.0
    await client.set_rf_power(original, antenna=2, save=False)
    assert (await client.get_rf_power())[1].write_power_dbm == original


async def test_region_roundtrip(client: ChainwayClient) -> None:
    original = await client.get_region()
    other = Region.CHINA_1 if original is not Region.CHINA_1 else Region.USA
    await client.set_region(other, save=False)
    assert await client.get_region() is other
    await client.set_region(original, save=False)
    assert await client.get_region() is original


async def test_rf_link_roundtrip(client: ChainwayClient) -> None:
    original = await client.get_rf_link()
    other = RfLink.PR_ASK_MILLER_8_160_KHZ
    if original is other:
        other = RfLink.PR_ASK_MILLER_4_250_KHZ
    await client.set_rf_link(other, save=False)
    assert await client.get_rf_link() is other
    await client.set_rf_link(original, save=False)
    assert await client.get_rf_link() is original


async def test_fast_id_and_tag_focus_roundtrip(client: ChainwayClient) -> None:
    original = await client.get_fast_id()
    await client.set_fast_id(enabled=not original)
    assert await client.get_fast_id() is (not original)
    await client.set_fast_id(enabled=original)

    original_focus = await client.get_tag_focus()
    await client.set_tag_focus(enabled=not original_focus)
    assert await client.get_tag_focus() is (not original_focus)
    await client.set_tag_focus(enabled=original_focus)


async def test_inventory_mode_roundtrip(client: ChainwayClient) -> None:
    original = await client.get_inventory_mode()
    await client.set_inventory_mode(InventoryMode.EPC_TID, save=False)
    updated = await client.get_inventory_mode()
    assert updated.mode is InventoryMode.EPC_TID
    await client.set_inventory_mode(original.mode, save=False)
    assert (await client.get_inventory_mode()).mode is original.mode


async def test_protocol_type_read_only(client: ChainwayClient) -> None:
    assert await client.get_protocol_type() is ProtocolType.ISO_18000_6C
    with pytest.raises(ChainwayResponseError):
        await client.set_protocol_type(ProtocolType.GB_T_29768)


async def test_gen2_parameters_survive_a_same_value_write(
    client: ChainwayClient,
) -> None:
    original = await client.get_gen2_parameters()
    await client.set_gen2_parameters(original)
    assert await client.get_gen2_parameters() == original


async def test_trigger_config_roundtrip(client: ChainwayClient) -> None:
    original = await client.get_trigger_config()
    variant = TriggerConfig(
        original.input, original.work_time_ms + 1000, original.min_interval_ms, original.output
    )
    await client.set_trigger_config(variant)
    assert await client.get_trigger_config() == variant
    await client.set_trigger_config(original)
    assert await client.get_trigger_config() == original


async def test_reader_address_set_same_value(client: ChainwayClient) -> None:
    original = await client.get_reader_address()
    await client.set_reader_address(original)
    assert await client.get_reader_address() == original


async def test_uart_baudrate_same_code_roundtrip(client: ChainwayClient) -> None:
    current = await client.get_uart_baudrate()
    assert current in (UartBaudRate.BAUD_115200, UartBaudRate.BAUD_460800)
    await client.set_uart_baudrate(current)
    assert await client.get_uart_baudrate() is current


async def test_unsupported_commands_raise(client: ChainwayClient) -> None:
    with pytest.raises(ChainwayTimeoutError):
        await client.get_dual_single_mode()
    with pytest.raises(ChainwayTimeoutError):
        await client.set_volume(5)
    with pytest.raises(ChainwayResponseError):
        await client.set_dwell_time(1000, 3)
    with pytest.raises(ChainwayResponseError):
        await client.scan_barcode()


async def test_inventory_rejects_commands_while_a_scan_runs(
    client: ChainwayClient,
) -> None:
    await client.start_inventory()
    assert client.inventory_active
    with pytest.raises(ChainwayInventoryActiveError):
        await client.get_version()
    with pytest.raises(ChainwayInventoryActiveError):
        await client.single_inventory()
    await client.stop_inventory()
    assert not client.inventory_active
    assert await client.get_version() is not None


async def test_iterator_cancellation_stops_the_scan(client: ChainwayClient) -> None:
    tags: list[object] = []

    async def drain() -> None:
        async with aclosing(client.inventory()) as stream:
            async for tag in stream:
                tags.append(tag)
                if len(tags) >= 3:
                    break

    with suppress(TimeoutError):
        await asyncio.wait_for(drain(), timeout=8.0)
    assert not client.inventory_active
    assert await client.get_version() is not None


async def test_garbage_bytes_resync_the_framing(client: ChainwayClient) -> None:
    transport = client._transport
    assert transport is not None
    for chunk in (
        b"\xa5\x5a",
        b"\xa5\x5a\x00\xff\x01\x02\xde\xad\xbe\xef\x0d\x0a",
        b"\xc8\x8c\xff\xff\x00\x00\x00\x00\x0d\x0a",
        bytes(range(64)),
        PARTIAL_FRAME,
    ):
        transport.write(chunk)
    assert await client.get_version() is not None


async def test_dead_link_drop_and_reconnect(url: str) -> None:
    lost: list[Exception] = []
    async with ChainwayClient(url, dead_link_timeout=2.0) as live:
        live.on_connection_lost = lost.append
        assert await live.get_version() is not None
        for _ in range(20):
            await asyncio.sleep(1.0)
            if not live.connected:
                break
        assert not live.connected
        for _ in range(300):
            if lost:
                break
            await asyncio.sleep(0.01)
        assert lost
        assert await live.get_version() is not None
        assert live.connected


async def test_software_reset_then_factory_restore(client: ChainwayClient) -> None:
    await client.software_reset()
    for _ in range(20):
        await asyncio.sleep(0.5)
        try:
            if await client.get_version() is not None:
                break
        except ChainwayTimeoutError:
            continue

    buzzer = await client.get_buzzer()
    await client.restore_factory_settings()
    assert await client.get_version() is not None
    assert await client.get_buzzer() is True
    await client.set_buzzer(enabled=buzzer)
    assert await client.get_buzzer() is buzzer
    assert (await client.get_inventory_mode()).mode is InventoryMode.EPC
    assert await client.get_antenna_mask() == 1
    assert (await client.get_rf_power())[0].read_power_dbm == 30.0
    assert await client.get_trigger_config() == TriggerConfig(
        TriggerInput.INPUT_1, 1000, 1000, OutputRoute.LINK
    )
