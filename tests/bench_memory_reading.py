"""TC-318 manual measurement: metadata only, under a real foreign lease."""

import argparse
import json
import platform
import statistics
import time

from test_memory_locks import holder
from test_memory_reading import MemoryReadingTest, locks, reading
from memory_lib import clock as memory_clock


def measure(samples):
    case = MemoryReadingTest()
    case.setUp()
    times = []
    try:
        path, backup, lease = case.prepare()
        connection, process = case.start(holder, str(lease.path), case.device)
        assert case.receive(connection)
        for _ in range(samples):
            deadline = memory_clock.now() + 0.05
            started = time.perf_counter()
            try:
                reading.read_json(path, lease, deadline)
            except locks.LockBusy:
                times.append((time.perf_counter() - started) * 1000)
            else:
                raise AssertionError("foreign lease was acquired")
            assert not path.exists() and backup.read_bytes() == b'{"seq":1}\n'
        connection.send("check")
        assert case.receive(connection) == "changed"
        process.join(10)
        assert process.exitcode == 0
    finally:
        case.doCleanups()
    return {"schema": 1, "os": platform.system(), "python": platform.python_version(),
            "samples": len(times), "deadline_ms": 50, "clock": "perf_counter",
            "median_ms": round(statistics.median(times), 3), "max_ms": round(max(times), 3)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=10, choices=range(1, 101))
    print("CORTHEX_READING_BENCH=" + json.dumps(measure(parser.parse_args().samples)))
