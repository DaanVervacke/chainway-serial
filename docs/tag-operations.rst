Tag operations
==============

Read, write, block write, block erase, lock and kill share one request
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

Collected tags
--------------

In auto and trigger work mode the reader stores sightings. Pull them
with:

.. code-block:: python

   collected = await client.read_collected_tags()
   count = await client.get_collected_tag_count()
   await client.delete_collected_tags()
