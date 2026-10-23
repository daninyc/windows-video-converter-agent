"""Use the Python driver without loading an unused native OpenSSL dependency."""

import importlib
import sys

# Connector imports the optional C extension even with use_pure=True. In this application's
# process we deliberately disable that optional module before importing the connector.
# This also prevents incompatible preloaded OpenSSL DLLs from triggering a Windows loader fault.
sys.modules.setdefault("mysql.connector.connection_cext", None)
connector = importlib.import_module("mysql.connector")
