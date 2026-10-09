Tag operations
==============

Read and write
--------------

Addresses and lengths are in 16-bit words:

.. code-block:: python

   from chainway_serial import MemoryBank, TagFilter

   data = await client.read_tag(MemoryBank.USER, word_address=0, word_count=2)
   await client.write_tag(MemoryBank.USER, 0, b"\xbe\xef\xca\xfe")

``MemoryBank.RESERVED`` holds the kill password in words 0 and 1 and the
access password in words 2 and 3.

A filter selects one tag by matching bits in a memory bank. Its address
and length are in bits. Without a filter the reader picks a tag on its
own:

.. code-block:: python

   tag_filter = TagFilter(
       bank=MemoryBank.TID,
       bit_address=0,
       bit_length=96,
       data=tag.tid,
   )
   await client.write_tag(MemoryBank.USER, 0, b"\xbe\xef", tag_filter=tag_filter)

Block write and block erase take the same bank and word address:

.. code-block:: python

   await client.block_write_tag(MemoryBank.USER, 0, b"\x11\x22\x33\x44")
   await client.block_erase_tag(MemoryBank.USER, 0, word_count=2)

Errors
------

A failed tag operation raises :class:`chainway_serial.ChainwayResponseError`
with the error code in the message:

.. list-table::
   :header-rows: 1

   * - Code
     - Meaning
   * - ``0x01``
     - The tag rejected the operation: the memory is locked, the password is wrong, or the chip does not support the command
   * - ``0x22``
     - No tag answered, or the word window runs past the end of the bank

Lock
----

Write an access password, then lock banks with it:

.. code-block:: python

   from chainway_serial import LockBank, LockMode

   password = bytes.fromhex("aabbccdd")
   await client.write_tag(MemoryBank.RESERVED, 2, password, tag_filter=tag_filter)
   await client.lock_tag(
       [LockBank.USER],
       LockMode.LOCK,
       access_password=password,
       tag_filter=tag_filter,
   )

``LockMode.OPEN`` unlocks again. ``PERMANENTLY_LOCK`` and
``PERMANENTLY_OPEN`` cannot be undone. :func:`chainway_serial.build_lock_code`
returns the three-byte lock code without sending it.

Kill
----

Kill needs the kill password, not the access password. A killed tag
never answers again:

.. code-block:: python

   await client.kill_tag(b"\x12\x34\x56\x78")

Chip specific commands
----------------------

These commands need a tag that supports them. Other tags answer error
code ``0x01``.

.. code-block:: python

   data = await client.authenticate_tag(challenge, key_id=0)
   status = await client.read_block_permalock(MemoryBank.USER, 0, 1)
   await client.set_block_permalock(MemoryBank.USER, 0, 1, mask=0x8000)
   await client.set_protected_mode(protected=False, short_range=False)

``authenticate_tag`` sends the Gen2 v2.0 Authenticate command with a
ten-byte challenge. ``set_block_permalock`` locks blocks for good. Impinj
Monza QT tags have ``set_qt``, ``get_qt``, ``read_qt`` and ``write_qt``.

Not supported on the UR4
------------------------

The client also implements commands that other Chainway readers answer.
A UR4 with UHF module firmware 7.40.1 does not support them. They raise
:class:`chainway_serial.ChainwayUnsupportedCommandError`, time out, or
return no data:

* ``deactivate_tag``
* the sensor tag commands: ``read_tag_sensor``, ``write_tag_calibration``,
  ``start_tag_logging``, ``stop_tag_logging``, ``check_tag_sensor_mode``,
  ``read_tag_sensor_voltage`` and ``read_tag_temperatures``
* the collected tag storage: ``read_collected_tags``,
  ``read_collected_tags_full``, ``get_collected_tag_count``,
  ``get_new_collected_tag_count``, ``delete_collected_tags`` and
  ``read_collected_tags_from_flash``
