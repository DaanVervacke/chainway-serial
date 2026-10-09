"""Probe a live Chainway UR4 reader and dump every response to captures/."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from pathlib import Path

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


async def probe_reader(client: ChainwayClient) -> dict[str, object]:
    """Run every read command against the reader and collect the results."""
    results: dict[str, object] = {}
    results["url"] = client.url
    results["version"] = str(await client.get_version())
    results["stm32_version"] = str(await client.get_stm32_version())
    results["hardware_version"] = str(await client.get_hardware_version())
    results["device_id"] = (await client.get_device_id()).hex()
    results["temperature"] = await client.get_temperature()
    results["antenna_state"] = (await client.get_antenna_connection_state()).connected
    results["battery"] = await client.get_battery_level()
    await capture(results, "voltage", client.verify_voltage)
    await capture(results, "temperature_protect", client.get_temperature_protect)
    await capture(results, "module_work_time", client.get_module_work_time)
    await capture(results, "dual_single_mode", client.get_dual_single_mode)
    await capture(results, "module_parameter", lambda: client.get_module_parameter(1, 1))
    results["power"] = [
        {
            "antenna": power.antenna,
            "read": power.read_power_dbm,
            "write": power.write_power_dbm,
        }
        for power in await client.get_rf_power()
    ]
    results["region"] = (await client.get_region()).name
    results["fixed_frequency"] = await client.get_fixed_frequency()
    results["return_loss"] = [
        {"port": loss.port, "loss_db": loss.loss_db} for loss in await client.get_return_loss()
    ]
    results["gen2"] = asdict(await client.get_gen2_parameters())
    results["rf_link"] = (await client.get_rf_link()).name
    results["fast_id"] = await client.get_fast_id()
    results["tag_focus"] = await client.get_tag_focus()
    results["inventory_mode"] = asdict(await client.get_inventory_mode())
    results["antenna_mask"] = await client.get_antenna_mask()
    results["work_mode"] = (await client.get_work_mode()).name
    results["buzzer"] = await client.get_buzzer()
    results["gpi"] = asdict(await client.get_gpi())
    results["trigger_config"] = asdict(await client.get_trigger_config())
    results["volume"] = await client.get_volume()
    results["reader_address"] = asdict(await client.get_reader_address())
    results["destination_address"] = asdict(await client.get_destination_address())
    results["collected_count"] = await client.get_collected_tag_count()
    barcode = await client.scan_barcode()
    results["barcode"] = barcode.hex() if barcode else None

    async def read_collected_full() -> dict[str, object]:
        collected = await client.read_collected_tags_full()
        return {"index": collected.index, "tags": [serialize_tag(tag) for tag in collected.tags]}

    await capture(results, "collected_full", read_collected_full)
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
        readers = await discover_readers(listen_seconds=5.0)
        for reader in readers:
            print(f"discovered {reader.mac} at {reader.ip}:{reader.port}")
        print("pass a serialx URL, for example socket://192.168.99.200:8888")
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
