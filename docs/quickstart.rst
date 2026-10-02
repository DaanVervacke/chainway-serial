Quickstart
==========

Install with uv:

.. code-block:: bash

   uv add chainway-serial

Connect over TCP and read the firmware version:

.. code-block:: python

   import asyncio
   from chainway_serial import ChainwayClient


   async def main() -> None:
       async with ChainwayClient("socket://192.168.99.200:8888") as client:
           print(await client.get_version())
           print(await client.get_temperature())


   asyncio.run(main())

Every command waits up to two seconds for a response by default. Pass
``response_timeout`` to the constructor to change that.

While a continuous inventory runs, the reader answers no command
except stop inventory. The client enforces this: other commands raise
:class:`chainway_serial.ChainwayInventoryActiveError` until the scan
ends.
