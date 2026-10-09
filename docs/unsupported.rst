Not supported on the UR4
========================

The client also implements commands that other Chainway readers answer.
A UR4 with UHF module firmware 7.40.1 does not support the commands
below. They raise :class:`chainway_serial.ChainwayUnsupportedCommandError`
or :class:`chainway_serial.ChainwayResponseError`, time out, or return
no data.

Tag commands:

* ``block_erase_tag``
* ``deactivate_tag``
* the Impinj Monza QT reads and writes: ``get_qt``, ``read_qt`` and
  ``write_qt``
* the sensor tag commands: ``read_tag_sensor``, ``write_tag_calibration``,
  ``start_tag_logging``, ``stop_tag_logging``, ``check_tag_sensor_mode``,
  ``read_tag_sensor_voltage`` and ``read_tag_temperatures``
* the collected tag storage: ``read_collected_tags``,
  ``read_collected_tags_full``, ``get_collected_tag_count``,
  ``get_new_collected_tag_count``, ``delete_collected_tags`` and
  ``read_collected_tags_from_flash``

Reader and module settings:

* ``set_protocol_type``
* ``set_antenna_work_time`` with ``save=True``, the volatile form works
* ``get_temperature_protect``
* ``set_module_work_time`` and ``get_module_work_time``
* ``set_dual_single_mode`` and ``get_dual_single_mode``
* ``set_dwell_time``
* ``get_module_parameter``

Peripherals:

* ``get_battery_level``
* ``scan_barcode``
* ``beep`` and ``stop_buzzer``
* ``set_volume`` and ``get_volume``
* ``set_led`` and ``blink_led``
* ``set_reader_idle_sleep_time`` and ``get_reader_idle_sleep_time``

``set_buzzer`` and ``get_buzzer`` work. They switch the beep on tag
reads.
