#!/usr/bin/env python3
"""Quiet detached memory maintenance entry point. Exit status reports no result."""
import sys
sys.dont_write_bytecode = True


def main():
    import os
    from pathlib import Path
    args = sys.argv[1:]
    if len(args) not in (4, 6) or len(set(args[::2])) != len(args[::2]):
        return
    options = dict(zip(args[::2], args[1::2]))
    if set(options) not in ({"--reason", "--project"}, {"--reason", "--project", "--expect-device"}):
        return
    library = Path(__file__).resolve().parent.parent / "skills/corthex-memory/scripts"
    sys.path.insert(0, str(library))
    from memory_lib import worker_runtime
    if os.name != "nt":
        os.nice(10)
    worker_runtime.run(options["--project"], options["--reason"], options.get("--expect-device"))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
