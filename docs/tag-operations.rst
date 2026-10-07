Tag operations
==============

Every tag operation except the sensor tag commands shares one request
layout: a four-byte password, an optional filter that selects one tag,
and the operation tail. Addresses and lengths are in 16-bit words.

.. code-block:: python

   from chainway_serial import MemoryBank, TagFilter

   data = await client.read_tag(MemoryBank.USER, word_address=2, word_count=2)
   await client.write_tag(MemoryBank.USER, 2, b"\xe2\x80")

Filters select the tag by matching bits in a memory bank. The address
and length are in bits:

.. code-block:: python

   tag_filter = TagFilter(
       bank=MemoryBank.EPC,
       bit_address=0x20,
       bit_length=16,
       data=b"\x12\x34",
   )
   await client.write_tag(MemoryBank.USER, 2, b"\xe2\x80", tag_filter=tag_filter)

Without a filter the reader picks the tag on its own. Pass the access
password with ``access_password`` when the tag is protected.

Block write and block erase take the same bank and word address:

.. code-block:: python

   await client.block_write_tag(MemoryBank.USER, 0, b"\x11\x22\x33\x44")
   await client.block_erase_tag(MemoryBank.USER, 0, word_count=2)

Lock
----

Lock tag memories with one of the four modes over a set of banks:

.. code-block:: python

   from chainway_serial import LockBank, LockMode

   await client.lock_tag(
       [LockBank.ACCESS_PASSWORD, LockBank.EPC],
       LockMode.PERMANENTLY_LOCK,
   )

The library builds the three-byte lock code the SDKs generate: mask
bits 19 down to 10 and action bits 9 down to 0, two bits per memory.
The standalone builder is :func:`chainway_serial.build_lock_code`.

Kill
----

Kill needs the kill password, not the access password:

.. code-block:: python

   await client.kill_tag(b"\x12\x34\x56\x78")

Authenticate
------------

The Gen2 v2.0 Authenticate command needs the ten-byte IChallenge_TAM1
data and returns sixteen bytes on success:

.. code-block:: python

   data = await client.authenticate_tag(challenge, key_id=0)
   print(data.hex())

Block permalock
---------------

Blocks are windows of 16 blocks of 8 bytes. Read the per-block
permalock status, or permalock blocks with a 16-bit mask:

.. code-block:: python

   status = await client.read_block_permalock(MemoryBank.USER, 0, 1)
   await client.set_block_permalock(MemoryBank.USER, 0, 1, mask=0xF000)

Monza QT
--------

Impinj Monza QT tags have a public and a private memory profile. Set or
get the QT control value, and read or write memory under a given
control value:

.. code-block:: python

   await client.set_qt(0x00)
   qt = await client.get_qt()
   data = await client.read_qt(0x00, MemoryBank.USER, 0, 2)
   await client.write_qt(0x00, MemoryBank.USER, 0, b"\x12\x34")

``set_qt`` sends opcode 0x97, which the 2025 Java SDK uses for a margin
read instead. Which command the firmware runs is unverified.

Protected mode and deactivate
-----------------------------

Both come from vendor sources that document no semantics:

.. code-block:: python

   await client.set_protected_mode(protected=True, short_range=False)
   await client.deactivate_tag()

Sensor tags
-----------

The 0x7C family reads sensor values and writes the calibration block.
It selects the tag by EPC and applies its own antenna and power:

.. code-block:: python

   from chainway_serial import SensorSubcommand

   code = await client.read_tag_sensor(
       SensorSubcommand.TEMPERATURE_CODE, epc, antenna=1, power_dbm=30.0
   )
   await client.write_tag_calibration(epc, 1, 30.0, calibration)

The 0xA3 family drives temperature logging tags, selected by a filter:

.. code-block:: python

   await client.start_tag_logging(tag_filter, min_code=0, max_code=1023, delay=1, interval=60)
   mode = await client.check_tag_sensor_mode(tag_filter)
   voltage = await client.read_tag_sensor_voltage(tag_filter)
   temperatures = await client.read_tag_temperatures(tag_filter, start=0, count=10)
   await client.stop_tag_logging(tag_filter)

Collected tags
--------------

In auto and trigger work mode the reader stores sightings. Pull them
with:

.. code-block:: python

   collected = await client.read_collected_tags()
   full = await client.read_collected_tags_full()
   count = await client.get_collected_tag_count()
   new = await client.get_new_collected_tag_count()
   await client.delete_collected_tags()

``read_collected_tags_from_flash`` pulls EPCs from the flash storage.
Its presence on the UR4 is unverified.
