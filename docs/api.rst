API reference
=============

Client
------

.. autoclass:: chainway_serial.client.ChainwayClient
   :members:

.. py:data:: chainway_serial.TagCallback

   The ``on_tag`` callback type. It takes a :class:`chainway_serial.Tag`
   and may be a plain function or a coroutine function.

.. py:data:: chainway_serial.ConnectionLostCallback

   The ``on_connection_lost`` callback type. It takes the exception that
   ended the link and may be a plain function or a coroutine function.

Discovery
---------

.. autofunction:: chainway_serial.discovery.discover_readers

Lock codes
----------

.. autofunction:: chainway_serial.parsers.build_lock_code

Models
------

.. autoclass:: chainway_serial.Tag
   :members:
.. autoclass:: chainway_serial.TagFilter
   :members:
.. autoclass:: chainway_serial.FirmwareVersion
   :members:
.. autoclass:: chainway_serial.AntennaState
   :members:
.. autoclass:: chainway_serial.AntennaPower
   :members:
.. autoclass:: chainway_serial.ReturnLoss
   :members:
.. autoclass:: chainway_serial.CollectedTags
   :members:
.. autoclass:: chainway_serial.CollectedTagsFull
   :members:
.. autoclass:: chainway_serial.GpiState
   :members:
.. autoclass:: chainway_serial.ReaderAddress
   :members:
.. autoclass:: chainway_serial.TriggerConfig
   :members:
.. autoclass:: chainway_serial.Gen2Parameters
   :members:
.. autoclass:: chainway_serial.InventoryModeConfig
   :members:
.. autoclass:: chainway_serial.DiscoveredReader
   :members:

Enums
-----

.. autoclass:: chainway_serial.InventoryMode
   :members:
.. autoclass:: chainway_serial.WorkMode
   :members:
.. autoclass:: chainway_serial.MemoryBank
   :members:
.. autoclass:: chainway_serial.Region
   :members:
.. autoclass:: chainway_serial.ProtocolType
   :members:
.. autoclass:: chainway_serial.RfLink
   :members:
.. autoclass:: chainway_serial.LinkFrequency
   :members:
.. autoclass:: chainway_serial.LockMode
   :members:
.. autoclass:: chainway_serial.LockBank
   :members:
.. autoclass:: chainway_serial.TriggerInput
   :members:
.. autoclass:: chainway_serial.OutputRoute
   :members:
.. autoclass:: chainway_serial.BootloaderTarget
   :members:
.. autoclass:: chainway_serial.SensorSubcommand
   :members:
.. autoclass:: chainway_serial.UartBaudRate
   :members:

Exceptions
----------

.. autoclass:: chainway_serial.ChainwayError
.. autoclass:: chainway_serial.ChainwayConnectionError
.. autoclass:: chainway_serial.ChainwayTimeoutError
.. autoclass:: chainway_serial.ChainwayProtocolError
.. autoclass:: chainway_serial.ChainwayResponseError
.. autoclass:: chainway_serial.ChainwayUnsupportedCommandError
.. autoclass:: chainway_serial.ChainwayInventoryActiveError
