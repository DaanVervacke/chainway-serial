# chainway-serial

[![Check](https://github.com/DaanVervacke/chainway-serial/actions/workflows/check.yml/badge.svg)](https://github.com/DaanVervacke/chainway-serial/actions/workflows/check.yml)
[![PyPI](https://img.shields.io/pypi/v/chainway-serial.svg)](https://pypi.org/project/chainway-serial)
[![Python](https://img.shields.io/pypi/pyversions/chainway-serial.svg)](https://pypi.org/project/chainway-serial)
[![License](https://img.shields.io/pypi/l/chainway-serial.svg)](https://github.com/DaanVervacke/chainway-serial/blob/main/LICENSE)

Asynchronous Python library for the [Chainway UR4](https://www.chainway.net/) fixed UHF RFID reader, over RS-232 and TCP, built on [serialx](https://github.com/puddly/serialx). Requires Python >= 3.14.

```bash
uv add chainway-serial
```

or:

```bash
pip install chainway-serial
```

```python
import asyncio

from chainway_serial import ChainwayClient


async def main() -> None:
    async with ChainwayClient("socket://192.168.99.200:8888") as client:
        print(await client.get_version())

        async for tag in client.inventory():
            print(tag.epc.hex(), tag.rssi, tag.antenna)


asyncio.run(main())
```

## Scope

| Area | Coverage |
|---|---|
| Transports | Any serialx URL: device paths, `socket://`, `rfc2217://`, ESPHome proxies |
| Status | Firmware, STM32 and hardware versions, device ID, temperature, return loss, antenna connection state, battery |
| Module | Voltage verification, module parameters, temperature protection, work time, dual single mode, dwell time |
| RF | Per-antenna read and write power, region, fixed frequency, Gen2 parameters, RF link, FastID, TagFocus, fast inventory mode, carrier wave |
| Inventory | Mode selection, tag filter, single and continuous inventory with phase and frequency reporting, tag callbacks |
| Tag operations | Read, write, block write, block erase, lock, kill, authenticate, block permalock, Monza QT set, get, read and write, deactivate, with tag filters |
| Sensor tags | Sensor and calibration reads and writes, temperature logging, tag voltage, logged temperatures |
| Collected tags | Batch pull, full record pull, counts, delete, flash pull, for auto and trigger work modes |
| Configuration | Reader and destination addresses, work modes, trigger timing, buzzer, volume, GPO, antennas, software and factory reset |
| Peripherals | Barcode imager, buzzer with the off form, LED |
| Firmware | Bootloader jump with four targets and the update block flow |
| Discovery | UDP discovery broadcast listener |

## Protocol status

The wire protocol is reverse engineered from the vendor Android, Java and Windows SDKs, cross-checked against the vendor's official protocol document and the native libraries. Every command the sources assign to the UR4 is implemented, including the module-level subset and the native library catalog, with three gaps: opcodes 0x30 and 0x97, which each carry two conflicting meanings in the sources, and the 0xF0 imager settings with undocumented payloads. No command has been verified against live hardware yet. The complete byte level reference, with every decoded payload layout and the unverified items, lives in [docs/protocol.md](docs/protocol.md). When a reader is available, `uv run python scripts/probe_chainway.py socket://192.168.99.200:8888` exercises the read commands that need no tag in range and writes the responses to `captures/`.

While a continuous inventory runs, the reader answers no command except stop inventory. The client models this: other commands raise `ChainwayInventoryActiveError` until the scan ends.

## Documentation

The full documentation is on [Read the Docs](https://chainway-serial.readthedocs.io/).
