"""Probe a live Chainway UR4 reader and dump every response to captures/."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from enum import Enum
from functools import partial
from pathlib import Path
from typing import Any

from chainway_serial import ChainwayClient, ChainwayError, InventoryMode, discover_readers
from chainway_serial.models import Tag

CAPTURES = Path("captures")


def serialize_tag(tag: Tag) -> dict[str, object]:
    """Render one tag sighting as a capture entry."""
    return {
        "epc": tag.epc.hex(),
        "tid": tag.tid.hex() if tag.tid else None,
        "rssi": tag.rssi,
        "antenna": tag.antenna,
    }


async def capture(
    results: dict[str, object], name: str, call: Callable[[], Awaitable[object]]
) -> None:
    """Run one read and record the value, or the error when the reader rejects it."""
    try:
        results[name] = await call()
    except ChainwayError as err:
        results[name] = f"error: {err}"


async def _power(client: ChainwayClient) -> list[dict[str, object]]:
    """Render the per-antenna power records."""
    return [
        {"antenna": record.antenna, "read": record.read_power_dbm, "write": record.write_power_dbm}
        for record in await client.get_rf_power()
    ]


async def _return_loss(client: ChainwayClient) -> list[dict[str, object]]:
    """Render the per-port return loss."""
    return [{"port": loss.port, "loss_db": loss.loss_db} for loss in await client.get_return_loss()]


async def _barcode(client: ChainwayClient) -> str | None:
    """Render one barcode scan."""
    scanned = await client.scan_barcode()
    return scanned.hex() if scanned else None


async def _collected(client: ChainwayClient) -> dict[str, object]:
    """Render the collected EPCs."""
    collected = await client.read_collected_tags()
    return {"index": collected.index, "tags": [epc.hex() for epc in collected.tags]}


async def _flash_tags(client: ChainwayClient) -> list[str]:
    """Render the EPCs pulled from the flash storage."""
    return [epc.hex() for epc in await client.read_collected_tags_from_flash()]


async def _collected_full(client: ChainwayClient) -> dict[str, object]:
    """Render the collected tags with full records."""
    collected = await client.read_collected_tags_full()
    return {"index": collected.index, "tags": [serialize_tag(tag) for tag in collected.tags]}


async def _text(read: Awaitable[object]) -> str:
    """Render a version or similar value as text."""
    return str(await read)


async def _name(read: Awaitable[Enum]) -> str:
    """Render an enum value by member name."""
    return (await read).name


async def _fields(read: Awaitable[Any]) -> dict[str, object]:
    """Render a dataclass value as a dictionary."""
    return asdict(await read)


async def _hex(read: Awaitable[bytes]) -> str:
    """Render a byte value as hex."""
    return (await read).hex()


async def _connected(client: ChainwayClient) -> object:
    """Render the antenna connection flags."""
    return (await client.get_antenna_connection_state()).connected


READS: tuple[tuple[str, Callable[[ChainwayClient], Awaitable[object]]], ...] = (
    ("version", lambda c: _text(c.get_version())),
    ("stm32_version", lambda c: _text(c.get_stm32_version())),
    ("hardware_version", lambda c: _text(c.get_hardware_version())),
    ("device_id", lambda c: _hex(c.get_device_id())),
    ("temperature", lambda c: c.get_temperature()),
    ("antenna_state", _connected),
    ("battery", lambda c: c.get_battery_level()),
    ("voltage", lambda c: c.verify_voltage()),
    ("temperature_protect", lambda c: c.get_temperature_protect()),
    ("module_work_time", lambda c: c.get_module_work_time()),
    ("dual_single_mode", lambda c: c.get_dual_single_mode()),
    ("module_parameter", lambda c: _hex(c.get_module_parameter(1, 1))),
    ("power", _power),
    ("region", lambda c: _name(c.get_region())),
    ("fixed_frequency", lambda c: c.get_fixed_frequency()),
    ("return_loss", _return_loss),
    ("gen2", lambda c: _fields(c.get_gen2_parameters())),
    ("rf_link", lambda c: _name(c.get_rf_link())),
    ("uart_baudrate", lambda c: _name(c.get_uart_baudrate())),
    ("fast_id", lambda c: c.get_fast_id()),
    ("tag_focus", lambda c: c.get_tag_focus()),
    ("inventory_mode", lambda c: _fields(c.get_inventory_mode())),
    ("antenna_mask", lambda c: c.get_antenna_mask()),
    ("work_mode", lambda c: _name(c.get_work_mode())),
    ("buzzer", lambda c: c.get_buzzer()),
    ("gpi", lambda c: _fields(c.get_gpi())),
    ("trigger_config", lambda c: _fields(c.get_trigger_config())),
    ("volume", lambda c: c.get_volume()),
    ("reader_address", lambda c: _fields(c.get_reader_address())),
    ("destination_address", lambda c: _fields(c.get_destination_address())),
    ("protocol_type", lambda c: _name(c.get_protocol_type())),
    ("fast_inventory_mode", lambda c: c.get_fast_inventory_mode()),
    ("antenna_1_work_time", lambda c: c.get_antenna_work_time(1)),
    ("idle_sleep_time", lambda c: c.get_reader_idle_sleep_time()),
    ("collected_count", lambda c: c.get_collected_tag_count()),
    ("new_collected_count", lambda c: c.get_new_collected_tag_count()),
    ("barcode", _barcode),
    ("collected", _collected),
    ("collected_full", _collected_full),
    ("flash_tags", _flash_tags),
)


async def probe_reader(client: ChainwayClient) -> dict[str, object]:
    """Run every reader read command and collect the results.

    Each read is recorded on its own, so a command the reader rejects or
    never answers is recorded as an error and the probe continues.
    """
    results: dict[str, object] = {"url": client.url}
    for name, read in READS:
        await capture(results, name, partial(read, client))
    return results


async def probe_inventory(client: ChainwayClient, seconds: float) -> list[dict[str, object]]:
    """Run a timed inventory and collect the tag sightings."""
    tags: list[dict[str, object]] = []

    async def collect() -> None:
        tags.extend([serialize_tag(tag) async for tag in client.inventory()])

    await client.set_inventory_mode(InventoryMode.EPC_TID_USER, save=False)
    collector = asyncio.create_task(collect())
    await asyncio.sleep(seconds)
    await client.stop_inventory()
    await collector
    return tags


async def main() -> None:
    """Connect, probe every command, and write the captures."""
    if len(sys.argv) < 2:
        readers = await discover_readers()
        for reader in readers:
            print(f"discovered {reader.mac} at {reader.ip}:{reader.port}")
        print("pass a serialx URL, for example socket://192.168.99.202:8888")
        return
    url = sys.argv[1]
    client = ChainwayClient(url)
    await client.connect()
    try:
        results = await probe_reader(client)
    finally:
        await client.disconnect()
    results["inventory_tags"] = await probe_inventory(ChainwayClient(url), seconds=3.0)
    await asyncio.to_thread(CAPTURES.mkdir, exist_ok=True)
    output = CAPTURES / "probe.json"
    await asyncio.to_thread(output.write_text, json.dumps(results, indent=2, default=str))
    print(f"wrote {output}")


if __name__ == "__main__":
    asyncio.run(main())
