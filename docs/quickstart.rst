Quickstart
==========

Install with uv:

.. code-block:: bash

   uv add chainway-serial

Connect and read the firmware version:

.. code-block:: python

   import asyncio
   from chainway_serial import ChainwayClient


   async def main() -> None:
       async with ChainwayClient("/dev/ttyUSB0") as client:
           print(await client.get_version())
           print(await client.get_temperature())


   asyncio.run(main())

Every command waits up to two seconds for a response by default. Pass
``response_timeout`` to the constructor to change that.

While a continuous inventory runs, the reader answers no command
except stop inventory. Other commands raise
:class:`chainway_serial.ChainwayInventoryActiveError` until the scan
ends.

Errors
------

Every exception derives from :class:`chainway_serial.ChainwayError`.

.. list-table::
   :header-rows: 1

   * - Exception
     - Meaning
   * - ``ChainwayConnectionError``
     - The link could not be opened or was lost
   * - ``ChainwayTimeoutError``
     - The reader did not answer in time
   * - ``ChainwayResponseError``
     - The reader rejected the request or answered with an unexpected payload
   * - ``ChainwayUnsupportedCommandError``
     - The reader does not support the command, a subclass of ``ChainwayResponseError``
   * - ``ChainwayInventoryActiveError``
     - A continuous inventory is running
   * - ``ChainwayProtocolError``
     - A frame broke the wire format
