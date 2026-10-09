Not supported on the UR4
========================

The client also implements commands that other Chainway readers answer.
A UR4 with UHF module firmware 7.40.1 does not support the commands
below. They fail in one of three ways.

Bare 00 reply
-------------

The reader answers a bare ``00`` byte and the client raises
:class:`chainway_serial.ChainwayUnsupportedCommandError`.

Tag commands:

* ``block_erase_tag``
* ``deactivate_tag``
* the Impinj Monza QT reads and writes: ``get_qt``, ``read_qt`` and
  ``write_qt``
* the sensor tag commands: ``read_tag_sensor``, ``write_tag_calibration``,
  ``start_tag_logging``, ``stop_tag_logging``, ``check_tag_sensor_mode``,
  ``read_tag_sensor_voltage`` and ``read_tag_temperatures``
* the collected tag storage: ``read_collected_tags_full``,
  ``get_collected_tag_count``, ``get_new_collected_tag_count`` and
  ``delete_collected_tags``

Reader and module settings:

* ``set_protocol_type``
* ``set_antenna_work_time`` with the default ``save=True``, the volatile
  form works
* ``get_temperature_protect``
* ``set_module_work_time`` and ``get_module_work_time``
* ``set_dwell_time``
* ``get_module_parameter``

Peripherals:

* ``get_battery_level``
* ``scan_barcode``
* ``beep`` and ``stop_buzzer``
* ``set_led`` and ``blink_led``
* ``set_reader_idle_sleep_time`` and ``get_reader_idle_sleep_time``

No answer
---------

The reader never answers and the client raises
:class:`chainway_serial.ChainwayTimeoutError`:

* ``read_collected_tags``
* ``set_dual_single_mode`` and ``get_dual_single_mode``
* ``set_volume`` and ``get_volume``

No data
-------

``read_collected_tags_from_flash`` gets a bare ``00`` and returns an
empty tuple.

Untested
--------

``set_module_parameter`` has not been sent to a UR4. Its parameter
types and IDs are undocumented.

``set_buzzer`` and ``get_buzzer`` work. They switch the beep on tag
reads.
