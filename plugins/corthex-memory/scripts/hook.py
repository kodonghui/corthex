#!/usr/bin/env python3
"""Quiet entry point for the four CORTHEX memory hooks, and from release 0.3.0 the two compaction hooks."""

import time

# Sample before product imports; subsequent calls use memory_lib.clock.
STARTED = time.perf_counter()

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
    except Exception as error:
        sys.stderr.write("corthex-memory: " + type(error).__name__ + "\n")
    sys.exit(0)
