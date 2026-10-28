#!/usr/bin/env python3
"""Quiet entry point for the four CORTHEX memory hooks."""

import time

STARTED = time.monotonic()

import sys
sys.dont_write_bytecode = True
from pathlib import Path

LIBRARY = Path(__file__).resolve().parent.parent / "skills/corthex-memory/scripts"
sys.path.insert(0, str(LIBRARY))

if __name__ == "__main__":
    try:
        from memory_lib.hooks import run
        if len(sys.argv) == 2:
            run(sys.argv[1], STARTED, sys.stdin.buffer, sys.stdout.buffer)
    except Exception:
        sys.stderr.write("corthex-memory: hook could not finish\n")
    sys.exit(0)
