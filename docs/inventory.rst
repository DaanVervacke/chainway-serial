Inventory
=========

Continuous inventory
--------------------

Iterate over tag sightings. The scan starts on first iteration and
stops when the loop ends:

.. code-block:: python

   async with ChainwayClient("socket://192.168.99.200:8888") as client:
       async for tag in client.inventory():
           print(tag.epc.hex(), tag.rssi, tag.antenna)

Break out early with :class:`contextlib.aclosing` so the stop frame is
sent immediately:

.. code-block:: python

   from contextlib import aclosing

   async with aclosing(client.inventory()) as stream:
       async for tag in stream:
           if tag.epc.startswith(b"\xe2"):
               break

Or drive the scan manually:

.. code-block:: python

   await client.start_inventory()
   await client.stop_inventory()

Phase and frequency reporting
-----------------------------

Pass ``phase=True`` and every sighting carries the tag phase in
``tag.phase``. Pass ``frequency=True`` and every sighting carries the
channel frequency in kHz in ``tag.frequency_khz``. Both can run
together:

.. code-block:: python

   async for tag in client.inventory(phase=True, frequency=True):
       print(tag.epc.hex(), tag.phase, tag.frequency_khz, tag.rssi)

``start_inventory`` takes the same two flags. The client reads both
values from the end of the record, before the RSSI pair, like the 2025
Java SDK. The phase is the raw 16-bit value. The official protocol
document calls it degrees, which is unverified on live hardware.

Single inventory
----------------

Scan once and return one tag or None:

.. code-block:: python

   tag = await client.single_inventory()

Inventory mode
--------------

Choose which blocks a sighting carries. TID is a fixed 12 bytes, the
USER window is set in 16-bit words:

.. code-block:: python

   from chainway_serial import InventoryMode

   await client.set_inventory_mode(
       InventoryMode.EPC_TID_USER, user_address=0, user_length=4, save=True
   )
   config = await client.get_inventory_mode()

Tag callbacks
-------------

Tags that arrive outside an active iteration, for example in auto or
trigger work mode, go to the ``on_tag`` callback:

.. code-block:: python

   def on_tag(tag) -> None:
       print(tag.epc.hex())

   client = ChainwayClient("socket://192.168.99.200:8888", on_tag=on_tag)

The callback may be a plain function or a coroutine function. While an
``inventory`` iteration is active, its tags go to the iterator and the
callback stays quiet.
