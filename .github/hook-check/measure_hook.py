"""Test-only outer clock for the unchanged hook in an isolated plugin copy.

The installed fixture replaces only hook command paths with this wrapper.
The measured subprocess includes the product interpreter's startup and exit;
the extra wrapper's startup and the host's own launch overhead are excluded.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("start", "prompt", "end-of-turn", "end"):
        return 2
    event = sys.argv[1]
    raw = sys.stdin.buffer.read()
    environment = dict(os.environ)
    memory_proxy = environment.get("HOOKCHECK_MEMORY_PROXY")
    if memory_proxy:
        environment.update(HTTP_PROXY=memory_proxy, HTTPS_PROXY=memory_proxy, ALL_PROXY=memory_proxy,
                           NO_PROXY="127.0.0.1,localhost")
    started = time.perf_counter()
    started_ns = time.monotonic_ns()
    process = subprocess.Popen([sys.executable, str(Path(__file__).with_name("hook.py")), event],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
    stdout, stderr = process.communicate(raw)
    ended_ns = time.monotonic_ns()
    elapsed = (time.perf_counter() - started) * 1000
    folder = Path(os.environ["HOOKCHECK_MEASURE_DIR"])
    if not folder.is_absolute():
        raise ValueError("the fixture measurement directory must be absolute")
    folder.mkdir(parents=True, exist_ok=True)
    value = {"hook": event, "milliseconds": elapsed, "exit": process.returncode,
             "interpreter_startup_included": True, "wrapper_startup_included": False,
             "host_launch_overhead_included": False, "pid": os.getpid(), "child_pid": process.pid,
             "dedicated_memory_proxy": bool(memory_proxy),
             "started_monotonic_ns": started_ns, "ended_monotonic_ns": ended_ns}
    name = event + "-" + str(os.getpid())
    temporary = folder / (name + ".tmp")
    temporary.write_text(json.dumps(value) + "\n", encoding="utf-8")
    temporary.replace(folder / (name + ".json"))
    if os.environ.get("HOOKCHECK_CAPTURE_INPUT_DIR"):
        inputs = Path(os.environ["HOOKCHECK_CAPTURE_INPUT_DIR"])
        if not inputs.is_absolute():
            raise ValueError("the fixture input directory must be absolute")
        inputs.mkdir(parents=True, exist_ok=True)
        temporary = inputs / (name + ".tmp")
        temporary.write_bytes(raw)
        temporary.replace(inputs / (name + ".json"))
    sys.stdout.buffer.write(stdout)
    sys.stderr.buffer.write(stderr)
    return process.returncode


if __name__ == "__main__":
    sys.exit(main())
