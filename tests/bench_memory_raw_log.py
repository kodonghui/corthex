"""Manual post-redaction recording timings; generated data, metadata only."""

import argparse
import json
import platform
import statistics
import time
from collections import Counter

from test_memory_locks import holder
from test_memory_raw_log import RawLogTest, raw_log
from memory_lib import clock as memory_clock


class MeasurementFailure(RuntimeError):
    def __init__(self, **metadata):
        self.metadata = metadata
        super().__init__("recording measurement did not complete")


def measure(samples):
    case = RawLogTest()
    case.setUp()
    rows, phase = [], "setup"
    try:
        for name, size in (("append-1KiB",1024),("append-512KiB",512*1024)):
            phase = name
            times, outcomes, entries = [], Counter(), 0
            for sample in range(samples+1):
                before = case.log.path.read_bytes() if case.log.path.exists() else b""
                prepared = raw_log.prepare("a"*size,{})
                started = time.perf_counter()
                result = case.log.append("prompt",prepared,diagnostic_deadline=memory_clock.now()+3)
                elapsed = (time.perf_counter()-started)*1000
                ended = memory_clock.now()
                valid = (result.outcome == "ok" and result.entry is not None or
                         result.outcome in ("deadline","lock-busy") and ended >= prepared.deadline
                         and (result.outcome != "lock-busy" or result.entry is None))
                if not valid:
                    raise MeasurementFailure(case=name, sample=sample, outcome=result.outcome,
                                             entry=result.entry is not None, elapsed_ms=round(elapsed,3))
                if result.entry is None:
                    assert (case.log.path.read_bytes() if case.log.path.exists() else b"") == before
                else:
                    assert case.entries()[-1] == result.entry
                    marker = any(p.name.endswith("."+case.log.log+"."+str(result.entry["turn"])) for p in case.markers())
                    assert marker == (result.outcome == "ok")
                if sample:
                    times.append(elapsed)
                    outcomes[result.outcome] += 1
                    entries += result.entry is not None
                else:
                    warmup = dict(warmup_outcome=result.outcome,warmup_entry=result.entry is not None)
            rows.append(dict(name=name,samples=samples,deadline_ms=50,bytes=size,
                             outcome="ok" if outcomes=={"ok":samples} else "mixed",outcomes=dict(outcomes),
                             entries=entries,skipped=samples-entries,
                             median_ms=round(statistics.median(times),3),max_ms=round(max(times),3),**warmup))
        phase = "foreign-lease"
        connection, process = case.start(holder,str(case.log.path.with_suffix(".lock")),case.header["device"])
        assert case.receive(connection)
        before = case.log.path.read_bytes()
        times = []
        try:
            for sample in range(samples):
                prepared = raw_log.prepare("made-up busy sample",{})
                started = time.perf_counter()
                result = case.log.append("prompt",prepared,diagnostic_deadline=memory_clock.now()+3)
                elapsed = (time.perf_counter()-started)*1000
                times.append(elapsed)
                if result.outcome != "lock-busy" or result.entry is not None:
                    raise MeasurementFailure(case=phase, sample=sample, outcome=result.outcome,
                                             entry=result.entry is not None, elapsed_ms=round(elapsed,3))
                assert case.log.path.read_bytes() == before
            rows.append(dict(name="foreign-lease",samples=samples,deadline_ms=50,bytes=0,
                             outcome="lock-busy",outcomes={"lock-busy":samples},entries=0,skipped=samples,
                             median_ms=round(statistics.median(times),3),max_ms=round(max(times),3)))
        finally:
            connection.send("check")
            assert case.receive(connection) == "changed"
            process.join(10)
            assert process.exitcode == 0
    except MeasurementFailure:
        raise
    except Exception as error:
        raise MeasurementFailure(case=phase, error=raw_log.diagnostics.error_kind(error) or "RuntimeError") from None
    finally:
        case.doCleanups()
    return dict(schema=2,os=platform.system(),python=platform.python_version(),clock="perf_counter",cases=rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples",type=int,default=10,choices=range(1,101))
    try:
        data = measure(parser.parse_args().samples)
    except MeasurementFailure as error:
        print("CORTHEX_RAW_BENCH_FAILURE="+json.dumps(error.metadata))
        raise SystemExit(1)
    print("CORTHEX_RAW_BENCH="+json.dumps(data))
