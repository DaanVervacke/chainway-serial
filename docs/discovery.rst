Discovery
=========

The reader broadcasts a 12-byte UDP packet with its MAC address, IPv4
address and TCP port. Listen for it:

.. code-block:: python

   from chainway_serial import discover_readers

   readers = await discover_readers(listen_seconds=5.0)
   for reader in readers:
       print(reader.mac, reader.ip, reader.port)

The listener runs for ``listen_seconds`` and returns one entry per
unique MAC address, IP address and port, sorted by IP address and port.
It listens on UDP port 1111 by default. Pass ``port`` to change that.
