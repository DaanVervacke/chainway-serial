API reference
=============

Client
------

.. autoclass:: chainway_serial.client.ChainwayClient
   :members:

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
.. autoclass:: chainway_serial.CollectedTags
   :members:
.. autoclass:: chainway_serial.GpoState
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
.. autoclass:: chainway_serial.LockMode
   :members:
.. autoclass:: chainway_serial.LockBank
   :members:
.. autoclass:: chainway_serial.TriggerInput
   :members:
.. autoclass:: chainway_serial.OutputRoute
   :members:

Exceptions
----------

.. autoclass:: chainway_serial.ChainwayError
.. autoclass:: chainway_serial.ChainwayConnectionError
.. autoclass:: chainway_serial.ChainwayTimeoutError
.. autoclass:: chainway_serial.ChainwayProtocolError
.. autoclass:: chainway_serial.ChainwayResponseError
.. autoclass:: chainway_serial.ChainwayInventoryActiveError
