"""Numeric-only TASK-013/014 measurements on each checked OS/Python.

Format a 7,000-byte base, 10,000 bytes of state text, 50 maximum-size item
texts and seven notices. One warm-up precedes ten timed complete formats.
Time module import separately in ten fresh interpreters, excluding process
startup and path setup. No files, stores or host settings are created/read.
"""

import argparse
import json
import platform
import statistics
import subprocess
import sys
import time
from datetime import timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "plugins/corthex-memory/skills/corthex-memory/scripts"
sys.path.insert(0, str(SCRIPTS))
from memory_lib import start_memory

MARKER = "CORTHEX_START_MEMORY_BENCH="


def inputs():
    pins = [{"id": "i_%012d" % n, "kind": "decision", "text": "가" * 1333 + "x",
             "quotes": [{"speaker": "user", "said": "2026-10-24T12:00:00.000Z"}]} for n in range(50)]
    state = [{"id": "s_%012d" % n, "part": start_memory.PARTS[n % 5], "pos": n,
              "text": "가" * 66 + "ab", "cites": ["i_000000000000"]} for n in range(50)]
    kinds = ("stopped", "consent", "key", "key", "retention", "sync-stopped", "sync-unreachable")
    notices = [start_memory.Notice(kind, "Made-up notice %d. " % n + "a" * 70) for n, kind in enumerate(kinds)]
    return "b" * 7000, notices, pins, state


def stats(values):
    return {"median_ms": round(statistics.median(values), 3), "max_ms": round(max(values), 3)}


def measure(samples=10):
    args = inputs()
    assert sum(len(row["text"].encode("utf-8")) for row in args[3]) == 10000
    start_memory.build_summary(*args, zone=timezone.utc)
    elapsed = []
    for _ in range(samples):
        began = time.perf_counter()
        result = start_memory.build_summary(*args, zone=timezone.utc)
        elapsed.append((time.perf_counter() - began) * 1000)
        assert len(result.text.encode("utf-8")) <= 7999
        assert result.text.startswith(args[0] + "\n\n")
    imports = []
    code = ("import sys,time; sys.dont_write_bytecode=True; sys.path.insert(0,sys.argv[1]); "
            "began=time.perf_counter(); import memory_lib.start_memory; "
            "print((time.perf_counter()-began)*1000)")
    for _ in range(samples):
        run = subprocess.run([sys.executable, "-I", "-c", code, str(SCRIPTS)],
                             capture_output=True, text=True, check=True, timeout=30)
        imports.append(float(run.stdout))
    return {"schema": 1, "os": platform.system(), "python": platform.python_version(),
            "samples": samples, "format_warmups": 1, "import_fresh_interpreters": True,
            "interpreter_startup_included": False, "base_bytes": 7000, "state_text_bytes": 10000,
            "pins": 50, "pin_text_bytes_each": 4000, "notices": 7,
            "summary_bytes": len(result.text.encode("utf-8")), "shown_pins": len(result.pins),
            "format": stats(elapsed), "import": stats(imports)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=10)
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("samples must be positive")
    print(MARKER + json.dumps(measure(args.samples)))
