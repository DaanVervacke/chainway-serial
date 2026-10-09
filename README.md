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
| Connection | Keepalive, dead-link detection, reconnect on the next command, connection lost callback |
| Module | Voltage verification, module parameters, temperature protection, work time, dual single mode, dwell time, idle sleep time |
| RF | Per-antenna read and write power, region, fixed frequency, Gen2 parameters, RF link, protocol type, FastID, TagFocus, fast inventory mode, carrier wave |
| Inventory | Mode selection, tag filter, single and continuous inventory with phase and frequency reporting, tag callbacks |
| Tag operations | Read, write, block write, block erase, lock, kill, authenticate, protected mode, block permalock, Monza QT set, get, read and write, deactivate, with tag filters |
| Sensor tags | Sensor reads, calibration write, temperature logging, sensor mode check, tag voltage, logged temperatures |
| Collected tags | Batch pull, full record pull, counts, delete, flash pull, for auto and trigger work modes |
| Configuration | Reader and destination addresses, work modes, trigger timing, buzzer, volume, GPO outputs, GPI inputs, antennas, software and factory reset |
| Peripherals | Barcode imager, beep and buzzer stop, LED switch and color blink |
| Firmware | Bootloader jump with four targets and the update block flow |
| Discovery | UDP discovery broadcast listener |

## Protocol status

The wire protocol is reverse engineered from the vendor Android, Java and Windows SDKs, cross-checked against the vendor's official protocol document and the native libraries. Every command the sources assign to the UR4 is implemented, including the module-level subset and the native library catalog, with two gaps: opcode 0x30, which carries two conflicting meanings in the sources, and the 0xF0 imager settings with undocumented payloads. Opcode 0x97 also has two meanings. The library sends it as the Monza QT set from the native library, while the 2025 Java SDK uses it for a margin read.

Verified on a UR4 over RS-232 at 115200, mainboard firmware 7.0.9, UHF module firmware 7.40.1, hardware 2.2.0, without antenna or tags:

- Status, RF and configuration reads, and write round trips for power, region, RF link, FastID, TagFocus, inventory mode, Gen2 parameters, trigger timing and the internal baud rate
- Which settings survive a power cycle, per save flag
- Continuous inventory start, stop and command rejection while a scan runs, framing resync after garbage bytes, dead-link detection and reconnect, software reset and factory reset
- The split between the STM32 mainboard and the UHF module, and which command families belong to other Chainway hardware: battery, barcode, LED, collected tag storage and volume get no useful answer on the UR4

Not verified yet: the TCP transport, tag reads and every tag operation, which need an antenna and tags. The `hardware/` test suite runs these checks against a real reader with `CHAINWAY_URL=/dev/ttyUSB0 uv run pytest hardware`. The complete byte level reference, with every decoded payload layout, the live findings and the open items, lives in [docs/protocol.md](docs/protocol.md). Mainboard firmware dumps of the test unit live in [firmware/UR4](firmware/UR4).

`set_uart_baudrate` only accepts 115200 and 460800. The module also accepts a code for 57600 that the mainboard cannot follow, which cuts the module off from the host until the code is reset over the mainboard debug port.

While a continuous inventory runs, the reader answers no command except stop inventory. The client models this: other commands raise `ChainwayInventoryActiveError` until the scan ends.

## Documentation

The full documentation is on [Read the Docs](https://chainway-serial.readthedocs.io/).
