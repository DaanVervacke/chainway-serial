Configuration
=============

RF power
--------

Power is set per antenna in dBm. ``set_rf_power`` sets one value,
``set_antenna_power`` sets separate read and write power:

.. code-block:: python

   await client.set_rf_power(30.0)
   await client.set_antenna_power(antenna=2, read_power_dbm=20.0, write_power_dbm=25.0)
   powers = await client.get_rf_power()

RF behaviour
------------

.. code-block:: python

   from chainway_serial import Region, RfLink

   await client.set_region(Region.EUROPE, save=True)
   await client.set_fixed_frequency(920_125)
   print(await client.get_fixed_frequency())
   await client.set_rf_link(RfLink.PR_ASK_MILLER_4_250_KHZ)
   await client.set_fast_id(enabled=True)
   await client.set_tag_focus(enabled=False)
   await client.set_carrier_wave(enabled=False)
   await client.set_fast_inventory_mode(enabled=True)
   print(await client.get_return_loss())

Protocol type
-------------

.. code-block:: python

   print(await client.get_protocol_type())

A UR4 reports ``ProtocolType.ISO_18000_6C`` and rejects
``set_protocol_type`` with :class:`chainway_serial.ChainwayResponseError`.

Power and every setting that carries a ``save`` flag store the value
across a power cycle by default. Pass ``save=False`` to keep it until
power off.

Resets
------

.. code-block:: python

   await client.software_reset()
   await client.restore_factory_settings()

``software_reset`` reboots the reader. Over serial that takes about two
seconds. Over TCP the socket stays silent and a new connection works
again after 11 to 31 seconds. ``restore_factory_settings`` resets the RF settings, and also turns the
buzzer back on and returns the trigger parameters and the work mode to
their defaults. It also sets the reader address back to
192.168.99.202, port 8888, right away. Over TCP on any other address
the link drops and the reader is only reachable on the factory address.

Gen2 parameters
---------------

.. code-block:: python

   from chainway_serial import Gen2Parameters

   await client.set_gen2_parameters(
       Gen2Parameters(target=4, session=1, start_q=4, max_q=15)
   )
   print(await client.get_gen2_parameters())

Antennas
--------

The enable mask is 16 bits, bit 0 is antenna 1:

.. code-block:: python

   await client.set_antenna_mask(0b101, save=True)
   mask = await client.get_antenna_mask()
   await client.set_antenna_work_time(antenna=1, work_time=200, save=False)
   state = await client.get_antenna_connection_state()

A UR4 with UHF module firmware 7.40.1 rejects the antenna work time
with ``save=True`` and raises
:class:`chainway_serial.ChainwayResponseError`. The volatile form works.

Work modes
----------

.. code-block:: python

   from chainway_serial import (
       OutputRoute,
       ReaderAddress,
       TriggerConfig,
       TriggerInput,
       WorkMode,
   )

   await client.set_work_mode(WorkMode.TRIGGER)
   await client.set_trigger_config(
       TriggerConfig(
           input=TriggerInput.INPUT_1,
           work_time_ms=1000,
           min_interval_ms=100,
           output=OutputRoute.LINK,
       )
   )
   await client.set_destination_address(
       ReaderAddress(ip="192.168.99.50", port=5084)
   )

In command mode the host starts and stops the inventory. In auto mode
the reader inventories on its own. In trigger mode a GPI signal starts
a run. Tag output goes to the link or to the UDP destination.

Reader network
--------------

.. code-block:: python

   address = ReaderAddress(
       ip="192.168.99.201",
       port=8888,
       subnet_mask="255.255.255.0",
       gateway="192.168.99.1",
   )
   await client.set_reader_address(address)
   print(await client.get_reader_address())

Peripherals
-----------

.. code-block:: python

   await client.set_buzzer(enabled=False)
   await client.set_gpo(output_0=True, output_1=False, relay_closed=True)
   print(await client.get_gpi())

``set_buzzer`` turns the beep on tag reads on or off and survives a
power cycle. The battery, barcode, beep, volume and LED commands
belong to other Chainway readers. A UR4 does not support them.

Firmware update
---------------

Reboot a firmware target into its bootloader, then send the image in
64-byte blocks:

.. code-block:: python

   from chainway_serial import BootloaderTarget

   await client.jump_to_bootloader(BootloaderTarget.UHF_MODULE)
   await client.start_update()
   for offset in range(0, len(image), 64):
       await client.send_update_block(image[offset : offset + 64])
   await client.stop_update()

The update flow is untested on a UR4. A failed update can leave the
reader unusable.
