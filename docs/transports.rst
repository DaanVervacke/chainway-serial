Transports
==========

The client takes one serialx URL and opens it with
``serialx.create_serial_connection``:

.. code-block:: python

   ChainwayClient("/dev/ttyUSB0")
   ChainwayClient("/dev/serial/by-id/usb-Chainway_UR4-if00-port0")
   ChainwayClient("socket://192.168.99.200:8888")
   ChainwayClient("rfc2217://gateway:4001")

The frame format and the command set are identical on RS-232 and TCP,
so the same client works everywhere. The line settings ``baudrate``,
``parity``, ``stopbits``, ``xonxoff`` and ``rtscts`` only apply to
serial device paths:

.. code-block:: python

   import serialx

   ChainwayClient(
       "/dev/ttyUSB0",
       baudrate=115200,
       stopbits=serialx.StopBits.ONE,
   )

The UR4 defaults are 115200 baud, 8 data bits, 1 stop bit, no parity
and no flow control.

Lifecycle
---------

Connect explicitly, or let the first command open the link:

.. code-block:: python

   client = ChainwayClient("socket://192.168.99.200:8888")
   await client.connect()
   await client.get_version()
   await client.disconnect()

When the link drops, the client marks it closed, fails any pending
command with :class:`chainway_serial.ChainwayConnectionError`, fires the
``on_connection_lost`` callback, and the next command reconnects on
its own.

The reader keeps scanning when a link closes during a continuous
inventory. ``connect`` therefore stops any running scan first and drops
the tag sightings that arrive before the stop is acknowledged.

Keepalive
---------

The client sends a get-version frame every 5 seconds, or a bare ``00``
byte during an inventory. It drops the link after 20 seconds of inbound
silence on an idle link, and suspends that check while a scan runs.
Tune it with ``keepalive_interval`` and ``dead_link_timeout``, both in
seconds.
