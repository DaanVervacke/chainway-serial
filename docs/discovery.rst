Discovery
=========

The reader broadcasts a 12-byte UDP packet with its MAC address, IPv4
address and TCP port. Listen for it:

.. code-block:: python

   from chainway_serial import discover_readers

   readers = await discover_readers(listen_seconds=5.0)
   for reader in readers:
       print(reader.mac, reader.ip, reader.port)

Each unique reader appears once. The packet carries no identification
beyond the MAC address, so every broadcast within the listen window is
collected.
