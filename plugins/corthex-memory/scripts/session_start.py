#!/usr/bin/env python3
"""Compatibility entry point for the 0.1.0 session-start command."""

import json
import os
import sys
sys.dont_write_bytecode = True
from pathlib import Path

LIBRARY = Path(__file__).resolve().parent.parent / "skills/corthex-memory/scripts"
sys.path.insert(0, str(LIBRARY))

def read_event(stream):
    """The hook input object, or {} when there is none."""
    try:
        if stream.isatty():
            return {}
        raw = stream.buffer.read().decode("utf-8", "replace") if hasattr(stream, "buffer") else stream.read()
        data = json.loads(raw or "{}")
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def main():
    event = read_event(sys.stdin)
    cwd = event.get("cwd")
    folder = Path(cwd if isinstance(cwd, str) and cwd else os.getcwd()).expanduser().resolve()
    context = build_context(folder, Path.home())
    output = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}
    # ASCII-only JSON, so the console code page on Windows cannot break the output.
    sys.stdout.buffer.write(json.dumps(output, ensure_ascii=True).encode("ascii") + b"\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    try:
        from memory_lib.context import *
        sys.exit(main())
    except Exception as error:  # A missing context must never stop the session.
        sys.stderr.write("corthex-memory: no session context (%s)\n" % type(error).__name__)
        sys.exit(0)
