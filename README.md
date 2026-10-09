# chainway-serial

[![Check](https://github.com/DaanVervacke/chainway-serial/actions/workflows/check.yml/badge.svg)](https://github.com/DaanVervacke/chainway-serial/actions/workflows/check.yml)
[![PyPI version](https://img.shields.io/pypi/v/chainway-serial.svg)](https://pypi.org/project/chainway-serial/)
[![Python versions](https://img.shields.io/pypi/pyversions/chainway-serial.svg)](https://pypi.org/project/chainway-serial/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Unofficial asynchronous Python library to interact with Chainway UR4 fixed UHF RFID readers over RS-232 and TCP, built on [serialx](https://github.com/puddly/serialx). Requires Python >= 3.14.

> Unofficial and reverse-engineered: not endorsed by Chainway, and it may
> break without notice whenever Chainway changes their firmware.

The library has been tested with a UR4 running UHF module firmware 7.40.1 over RS-232.

## Install

```bash
uv add chainway-serial
```

## Documentation

The documentation is hosted at
[chainway-serial.readthedocs.io](https://chainway-serial.readthedocs.io/).

## Usage

```python
import asyncio

from chainway_serial import ChainwayClient


async def main() -> None:
    async with ChainwayClient("/dev/ttyUSB0") as client:
        print(await client.get_version())

        async for tag in client.inventory():
            print(tag.epc.hex(), tag.rssi)


asyncio.run(main())
```

`ChainwayClient` takes any serialx URL: a serial device path, or `socket://host:8888` for a reader on the network.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, the gate and the live hardware tests.

```bash
uv sync
uv run python -m scripts.check
```

## License

MIT. See [LICENSE](LICENSE).
