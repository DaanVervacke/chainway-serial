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

   from chainway_serial import ProtocolType

   await client.set_protocol_type(ProtocolType.ISO_18000_6C)
   print(await client.get_protocol_type())

Power and every setting that carries a ``save`` flag store the value
across a power cycle by default. Pass ``save=False`` to keep it until
power off.

Resets
------

Two reset commands exist, both from the official protocol document:

.. code-block:: python

   await client.software_reset()
   await client.restore_factory_settings()

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
   await client.set_antenna_work_time(antenna=1, work_time=200)
   state = await client.get_antenna_connection_state()

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

   print(await client.get_battery_level())
   print(await client.scan_barcode())
   await client.beep(duration=1)
   await client.set_buzzer(enabled=True)
   await client.set_volume(5)
   await client.set_led(enabled=True)
   await client.blink_led(10, 20, 30)
   await client.stop_buzzer()
   await client.set_gpo(output_0=True, output_1=False, relay_closed=True)
   print(await client.get_gpi())

Module settings
---------------

These commands come from the module-level protocol and the native
libraries. Most take raw integers because no source documents their
units:

.. code-block:: python

   print(await client.verify_voltage())
   await client.set_temperature_protect(1)
   await client.set_module_work_time(100)
   await client.set_dual_single_mode(0)
   await client.set_reader_idle_sleep_time(10)
   await client.set_dwell_time(1000, 3)
   data = await client.get_module_parameter(param_type=0, param_id=1)

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

The update flow is reconstructed from the SDKs and has not run against
a UR4.
