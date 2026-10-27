"""Manual post-redaction recording timings; generated data, metadata only."""

import argparse
import json
import platform
import statistics
import time

from test_memory_locks import holder
from test_memory_raw_log import RawLogTest, raw_log


def measure(samples):
    case = RawLogTest()
    case.setUp()
    rows = []
    try:
        for name, size in (("append-1KiB",1024),("append-512KiB",512*1024)):
            times = []
            for sample in range(samples+1):
                prepared = raw_log.prepare("a"*size,{})
                started = time.perf_counter()
                result = case.log.append("prompt",prepared,diagnostic_deadline=time.monotonic()+3)
                elapsed = (time.perf_counter()-started)*1000
                if result.outcome != "ok" or result.entry is None:
                    raise AssertionError("recording sample did not complete")
                if sample:
                    times.append(elapsed)
            rows.append(dict(name=name,samples=samples,deadline_ms=50,bytes=size,
                             outcome="ok",median_ms=round(statistics.median(times),3),max_ms=round(max(times),3)))
        connection, process = case.start(holder,str(case.log.path.with_suffix(".lock")),case.header["device"])
        assert case.receive(connection)
        before = case.log.path.read_bytes()
        times = []
        try:
            for _ in range(samples):
                prepared = raw_log.prepare("made-up busy sample",{})
                started = time.perf_counter()
                result = case.log.append("prompt",prepared,diagnostic_deadline=time.monotonic()+3)
                times.append((time.perf_counter()-started)*1000)
                assert result.outcome == "lock-busy" and result.entry is None
                assert case.log.path.read_bytes() == before
            rows.append(dict(name="foreign-lease",samples=samples,deadline_ms=50,bytes=0,
                             outcome="lock-busy",median_ms=round(statistics.median(times),3),max_ms=round(max(times),3)))
        finally:
            connection.send("check")
            assert case.receive(connection) == "changed"
            process.join(10)
            assert process.exitcode == 0
    finally:
        case.doCleanups()
    return dict(schema=1,os=platform.system(),python=platform.python_version(),clock="perf_counter",cases=rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples",type=int,default=10,choices=range(1,101))
    print("CORTHEX_RAW_BENCH="+json.dumps(measure(parser.parse_args().samples)))
