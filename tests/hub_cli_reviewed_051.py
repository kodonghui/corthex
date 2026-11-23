"""Normalize only the reviewed 0.5.1 version fields, before the 0.5.0 and older layers.

0.5.1 releases the QA default source that core 0.16.0 gave the hub (REVIEWED in
hub_cli_fixture.py) and changes nothing else: the hub's VERSION and the transport's
default version move from 0.5.0 to 0.5.1. These pairs run first, so the later layers
meet the 0.5.0 bytes that they were made for.
"""

REVIEWED_051 = {
    "hub.py": ((b'VERSION = "0.5.1"\n', b'VERSION = "0.5.0"\n'),),
    "transport.py": ((b'version="0.5.1", timeout=30, publisher=None):', b'version="0.5.0", timeout=30, publisher=None):'),),
}
