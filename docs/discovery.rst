Discovery
=========

The reader broadcasts a 12-byte UDP packet with its MAC address, IPv4
address and TCP port every 10 seconds. Listen for it:

.. code-block:: python

   from chainway_serial import discover_readers

   readers = await discover_readers()
   for reader in readers:
       print(reader.mac, reader.ip, reader.port)

The listener runs for ``listen_seconds``, 12 seconds by default, so it
hears at least one broadcast from every reader. A window shorter than
10 seconds can miss a reader. Wi-Fi drops some broadcasts. On a
wireless host about 1 in 6 was lost, so pass ``listen_seconds=35`` there
to hear about three of them. It returns one entry per
unique MAC address, IP address and port, sorted by IP address and port.
It listens on UDP port 1111 by default. Pass ``port`` to change that.
