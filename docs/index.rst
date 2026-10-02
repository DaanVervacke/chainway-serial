chainway-serial
===============

Asynchronous Python library for the Chainway UR4 fixed UHF RFID reader,
over RS-232 and TCP, built on `serialx <https://github.com/puddly/serialx>`_.
Requires Python >= 3.14.

.. toctree::
   :maxdepth: 2
   :caption: Contents

   quickstart
   transports
   inventory
   tag-operations
   configuration
   discovery
   api

The wire protocol is reverse engineered from the vendor SDKs. The full
byte level reference lives in `docs/protocol.md
<https://github.com/DaanVervacke/chainway-serial/blob/main/docs/protocol.md>`_
in the repository.

Indices and tables
===================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
