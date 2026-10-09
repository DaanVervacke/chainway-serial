"""Live tag operations against real hardware with tags on the antenna.

Run with ``CHAINWAY_URL=/dev/cu.PL2303G-USBtoUART1110 uv run pytest
hardware/test_tags.py``. Place at least one Gen2 tag with a 32-bit USER
bank, such as an Impinj Monza R6-P, on the antenna. Every test restores
what it changes: reader settings are written without the save flag, and
tag memory, locks and passwords return to their values from before the
test. No test kills, permalocks or deactivates a tag.
"""

import asyncio
from contextlib import aclosing

import pytest

from chainway_serial import (
    ChainwayClient,
    ChainwayResponseError,
    ChainwayUnsupportedCommandError,
    InventoryMode,
    LockBank,
    LockMode,
    MemoryBank,
    Tag,
    TagFilter,
)

SCAN_SECONDS = 2.0
TEST_PASSWORD = bytes.fromhex("aabbccdd")
ZERO_PASSWORD = bytes(4)


async def scan(
    client: ChainwayClient, *, phase: bool = False, frequency: bool = False
) -> list[Tag]:
    sightings: list[Tag] = []

    async def collect() -> None:
        async with aclosing(client.inventory(phase=phase, frequency=frequency)) as stream:
            sightings.extend([tag async for tag in stream])

    task = asyncio.create_task(collect())
    await asyncio.sleep(SCAN_SECONDS)
    await client.stop_inventory()
    await task
    return sightings


def by_tid(tag: Tag) -> TagFilter:
    assert tag.tid is not None
    return TagFilter(bank=MemoryBank.TID, bit_address=0, bit_length=96, data=tag.tid[:12])


async def strongest_tag(client: ChainwayClient) -> Tag:
    original = await client.get_inventory_mode()
    await client.set_inventory_mode(InventoryMode.EPC_TID, save=False)
    try:
        sightings = [tag for tag in await scan(client) if tag.tid and tag.rssi is not None]
    finally:
        await client.set_inventory_mode(original.mode, save=False)
    best: dict[bytes, Tag] = {}
    for tag in sorted(sightings, key=lambda sighting: sighting.rssi or -1000.0, reverse=True):
        best.setdefault(tag.epc, tag)
    for tag in best.values():
        try:
            await client.read_tag(MemoryBank.RESERVED, 0, 4, tag_filter=by_tid(tag))
        except ChainwayResponseError:
            continue
        return tag
    pytest.skip("no tag on the antenna with a readable RESERVED bank")


async def test_antenna_port_one_is_connected(client: ChainwayClient) -> None:
    state = await client.get_antenna_connection_state()
    assert state.connected[0]
    loss = await client.get_return_loss()
    assert loss[0].port == 1
    assert loss[0].loss_db >= 5


async def test_inventory_reports_tags_with_a_tid(client: ChainwayClient) -> None:
    tag = await strongest_tag(client)
    assert tag.tid is not None
    assert len(tag.tid) == 12
    assert tag.antenna == 1


async def test_phase_is_reported_in_degrees(client: ChainwayClient) -> None:
    sightings = await scan(client, phase=True)
    phases = [tag.phase for tag in sightings if tag.phase is not None]
    if not phases:
        pytest.skip("no tag on the antenna")
    outside = [
        (tag.pc.hex(), tag.epc.hex(), tag.phase)
        for tag in sightings
        if not 0 <= (tag.phase or 0) < 360
    ]
    assert not outside


async def test_frequency_is_reported_in_khz(client: ChainwayClient) -> None:
    sightings = await scan(client, frequency=True)
    frequencies = {tag.frequency_khz for tag in sightings if tag.frequency_khz is not None}
    if not frequencies:
        pytest.skip("no tag on the antenna")
    assert all(840_000 <= frequency <= 960_000 for frequency in frequencies)


async def test_reads_of_every_bank(client: ChainwayClient) -> None:
    tag = await strongest_tag(client)
    selector = by_tid(tag)
    assert tag.tid is not None
    assert len(await client.read_tag(MemoryBank.RESERVED, 0, 4, tag_filter=selector)) == 8
    epc_bank = await client.read_tag(MemoryBank.EPC, 0, 8, tag_filter=selector)
    assert epc_bank[2:4] == tag.pc
    assert epc_bank[4:] == tag.epc[:12]
    assert await client.read_tag(MemoryBank.TID, 0, 6, tag_filter=selector) == tag.tid[:12]


async def test_read_past_the_bank_end_reports_error_0x22(client: ChainwayClient) -> None:
    tag = await strongest_tag(client)
    with pytest.raises(ChainwayResponseError, match="0x22"):
        await client.read_tag(MemoryBank.TID, 0, 64, tag_filter=by_tid(tag))


async def test_user_bank_write_roundtrip(client: ChainwayClient) -> None:
    tag = await strongest_tag(client)
    selector = by_tid(tag)
    original = await client.read_tag(MemoryBank.USER, 0, 2, tag_filter=selector)
    try:
        await client.write_tag(MemoryBank.USER, 0, b"\xbe\xef\xca\xfe", tag_filter=selector)
        assert (
            await client.read_tag(MemoryBank.USER, 0, 2, tag_filter=selector) == b"\xbe\xef\xca\xfe"
        )
    finally:
        await client.write_tag(MemoryBank.USER, 0, original, tag_filter=selector)
    assert await client.read_tag(MemoryBank.USER, 0, 2, tag_filter=selector) == original


async def test_access_password_guards_a_locked_user_bank(client: ChainwayClient) -> None:
    tag = await strongest_tag(client)
    selector = by_tid(tag)
    reserved = await client.read_tag(MemoryBank.RESERVED, 0, 4, tag_filter=selector)
    if reserved != bytes(8):
        pytest.skip("the tag carries a nonzero password")
    original = await client.read_tag(MemoryBank.USER, 0, 2, tag_filter=selector)
    await client.write_tag(MemoryBank.RESERVED, 2, TEST_PASSWORD, tag_filter=selector)
    try:
        await client.lock_tag(
            [LockBank.USER], LockMode.LOCK, access_password=TEST_PASSWORD, tag_filter=selector
        )
        with pytest.raises(ChainwayResponseError, match="0x01"):
            await client.write_tag(MemoryBank.USER, 0, b"\x11\x11", tag_filter=selector)
        await client.write_tag(
            MemoryBank.USER, 0, b"\x22\x22", access_password=TEST_PASSWORD, tag_filter=selector
        )
        with pytest.raises(ChainwayResponseError, match="0x01"):
            await client.lock_tag(
                [LockBank.EPC],
                LockMode.LOCK,
                access_password=bytes(range(1, 5)),
                tag_filter=selector,
            )
    finally:
        await client.lock_tag(
            [LockBank.USER, LockBank.ACCESS_PASSWORD],
            LockMode.OPEN,
            access_password=TEST_PASSWORD,
            tag_filter=selector,
        )
        await client.write_tag(
            MemoryBank.USER, 0, original, access_password=TEST_PASSWORD, tag_filter=selector
        )
        await client.write_tag(
            MemoryBank.RESERVED,
            2,
            ZERO_PASSWORD,
            access_password=TEST_PASSWORD,
            tag_filter=selector,
        )
    assert await client.read_tag(MemoryBank.RESERVED, 0, 4, tag_filter=selector) == bytes(8)
    assert await client.read_tag(MemoryBank.USER, 0, 2, tag_filter=selector) == original


async def test_epc_filter_limits_the_scan(client: ChainwayClient) -> None:
    tag = await strongest_tag(client)
    epc_filter = TagFilter(
        bank=MemoryBank.EPC, bit_address=32, bit_length=len(tag.epc) * 8, data=tag.epc
    )
    await client.set_filter(epc_filter, save=False)
    try:
        sightings = await scan(client)
    finally:
        await client.set_filter(None, save=False)
    assert sightings
    assert {sighting.epc for sighting in sightings} == {tag.epc}


async def test_qt_read_is_unsupported_without_a_qt_tag(client: ChainwayClient) -> None:
    tag = await strongest_tag(client)
    with pytest.raises(ChainwayUnsupportedCommandError):
        await client.get_qt(tag_filter=by_tid(tag))
