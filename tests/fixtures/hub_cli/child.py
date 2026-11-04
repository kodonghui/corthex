"""Execute the actual hub __main__ with an explicit loopback-only socket guard.

No production function or result is patched. The process exit is hub's actual
SystemExit. Credentials are absent from the freshly constructed environment.
"""
import argparse
import json
import runpy
import socket
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hub", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--guard-receipt", required=True)
    parser.add_argument("words", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    receipt = {"allowedLoopbackConnections": 0, "blockedConnectionAttempts": 0,
               "blockedResolutionAttempts": 0, "rawAddressesPersisted": False}
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_resolve = socket.getaddrinfo

    def permitted(address):
        return isinstance(address, tuple) and len(address) >= 2 and address[0] == "127.0.0.1" and address[1] == args.port

    def connect(sock, address):
        if not permitted(address):
            receipt["blockedConnectionAttempts"] += 1
            raise OSError("external network forbidden by fixture guard")
        receipt["allowedLoopbackConnections"] += 1
        return original_connect(sock, address)

    def connect_ex(sock, address):
        if not permitted(address):
            receipt["blockedConnectionAttempts"] += 1
            raise OSError("external network forbidden by fixture guard")
        receipt["allowedLoopbackConnections"] += 1
        return original_connect_ex(sock, address)

    def resolve(host, port, *positional, **keywords):
        if host != "127.0.0.1" or int(port) != args.port:
            receipt["blockedResolutionAttempts"] += 1
            raise OSError("external resolution forbidden by fixture guard")
        return original_resolve(host, port, *positional, **keywords)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.getaddrinfo = resolve
    hub = Path(args.hub).resolve()
    words = args.words[1:] if args.words[:1] == ["--"] else args.words
    sys.path.insert(0, str(hub.parent))
    sys.argv = [str(hub)] + words
    try:
        runpy.run_path(str(hub), run_name="__main__")
    finally:
        Path(args.guard_receipt).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf8")


if __name__ == "__main__":
    main()
