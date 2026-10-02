"""Probe a live Chainway UR4 reader and dump every response to captures/."""

import asyncio
import json
import sys
from pathlib import Path

from chainway_serial import ChainwayClient, InventoryMode, discover_readers
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


async def probe_reader(client: ChainwayClient) -> dict[str, object]:
    """Run every read command against the reader and collect the results."""
    results: dict[str, object] = {}
    results["url"] = client.url
    results["version"] = str(await client.get_version())
    results["stm32_version"] = str(await client.get_stm32_version())
    results["module_version"] = str(await client.get_module_version())
    results["temperature"] = await client.get_temperature()
    results["antenna_state"] = (await client.get_antenna_connection_state()).connected
    results["battery"] = await client.get_battery_level()
    results["power"] = [
        {
            "antenna": power.antenna,
            "read": power.read_power_dbm,
            "write": power.write_power_dbm,
        }
        for power in await client.get_rf_power()
    ]
    results["region"] = (await client.get_region()).name
    results["gen2"] = (await client.get_gen2_parameters()).__dict__
    results["rf_link"] = (await client.get_rf_link()).name
    results["fast_id"] = await client.get_fast_id()
    results["tag_focus"] = await client.get_tag_focus()
    results["inventory_mode"] = (await client.get_inventory_mode()).__dict__
    results["antenna_mask"] = await client.get_antenna_mask()
    results["work_mode"] = (await client.get_work_mode()).name
    results["buzzer"] = await client.get_buzzer()
    results["gpo"] = (await client.get_gpo()).__dict__
    results["trigger_config"] = (await client.get_trigger_config()).__dict__
    results["volume"] = await client.get_volume()
    results["reader_address"] = (await client.get_reader_address()).__dict__
    results["destination_address"] = (await client.get_destination_address()).__dict__
    results["collected_count"] = await client.get_collected_tag_count()
    barcode = await client.scan_barcode()
    results["barcode"] = barcode.hex() if barcode else None
    return results


async def probe_inventory(client: ChainwayClient, seconds: float) -> list[dict[str, object]]:
    """Run a timed inventory and collect the tag sightings."""
    tags: list[dict[str, object]] = []

    def on_tag(tag: Tag) -> None:
        tags.append(serialize_tag(tag))

    scanning = ChainwayClient(
        client.url,
        keepalive_interval=client.keepalive_interval,
        dead_link_timeout=client.dead_link_timeout,
        on_tag=on_tag,
    )
    await scanning.connect()
    try:
        await scanning.set_inventory_mode(InventoryMode.EPC_TID_USER, save=False)
        await scanning.start_inventory()
        await asyncio.sleep(seconds)
        await scanning.stop_inventory()
    finally:
        await scanning.disconnect()
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
