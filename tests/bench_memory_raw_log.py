"""Manual post-redaction recording timings; generated data, metadata only."""

import argparse
import json
import platform
import statistics
import time
from collections import Counter
from datetime import timedelta

from test_memory_locks import holder
from test_memory_raw_log import RawLogTest, WHEN, raw_log
from memory_lib import clock as memory_clock


class MeasurementFailure(RuntimeError):
    def __init__(self, **metadata):
        self.metadata = metadata
        super().__init__("recording measurement did not complete")


def measure(samples, pending_counts=(0,1000,20000)):
    case = RawLogTest()
    case.setUp()
    rows, phase = [], "setup"
    try:
        profiles = [("append-1KiB",1024,{}),("append-512KiB",512*1024,{})]
        profiles += [("markers-%d" % count,1024,{"requested_markers":count}) for count in pending_counts]
        profiles += [("continued-markers-%d" % count,1024,{"requested_markers":count,"continued_answer":True})
                     for count in pending_counts]
        profiles.append(("after-control-512KiB",1024,{"control_text_bytes":512*1024}))
        for name, size, metadata in profiles:
            phase = name
            baseline = None
            if "requested_markers" in metadata:
                for marker in case.markers():
                    marker.unlink()
                setup = time.perf_counter()
                requested = metadata["requested_markers"]
                count = 0
                for number in range(requested):
                    (case.log.markers / ("20261027T091203Z.codex-"+"0"*16+"."+str(number+1))).write_bytes(b"")
                    count += 1
                    if platform.system()=="Windows" and requested==20000 and count==5000 and time.perf_counter()-setup>10:
                        break
                metadata.update(markers=count,marker_setup_ms=round((time.perf_counter()-setup)*1000,3))
            if metadata.get("continued_answer"):
                # N unrelated markers plus this turn's one marker. The prior
                # entry is an answer, so the second answer must use the scan.
                case.log.path.write_bytes(b"")
                assert case.record().outcome=="ok"
                assert case.record("answer",when=WHEN+timedelta(seconds=1)).outcome=="ok"
                baseline = case.log.path.read_bytes()
                metadata["own_markers"] = 1
            if "control_text_bytes" in metadata:
                # Resetting seq for this fixture must not reuse an earlier
                # profile's marker, especially when this append expires.
                for marker in case.markers():
                    marker.unlink()
                value = dict(case.entries()[-1],seq=1,turn=1,text="\x01"*(512*1024))
                baseline = raw_log.base.json_bytes(value,"TBL-007",compact=True)
                metadata["tail_bytes"] = len(baseline)
            times, outcomes, entries = [], Counter(), 0
            for sample in range(samples+1):
                if baseline is not None:
                    case.log.path.write_bytes(baseline)
                before = case.log.path.read_bytes() if case.log.path.exists() else b""
                prepared = raw_log.prepare("a"*size,{})
                started = time.perf_counter()
                continued = metadata.get("continued_answer",False)
                result = case.log.append("answer" if continued else "prompt",prepared,
                                         stop_hook_active=continued,diagnostic_deadline=memory_clock.now()+3)
                elapsed = (time.perf_counter()-started)*1000
                ended = memory_clock.now()
                valid = (result.outcome == "ok" and result.entry is not None or
                         result.outcome == "deadline" and result.entry is not None and ended >= prepared.deadline or
                         result.outcome == "lock-busy" and result.entry is None and ended >= prepared.deadline)
                if not valid:
                    raise MeasurementFailure(case=name, sample=sample, outcome=result.outcome,
                                             entry=result.entry is not None, elapsed_ms=round(elapsed,3))
                if result.entry is None:
                    assert (case.log.path.read_bytes() if case.log.path.exists() else b"") == before
                else:
                    assert case.entries()[-1] == result.entry
                    at = WHEN.strftime("%Y%m%dT%H%M%SZ") if continued else result.entry["at"][:19].replace("-","").replace(":","")+"Z"
                    marker = case.log.markers / (at+"."+case.log.log+"."+str(result.entry["turn"]))
                    assert marker.exists() if continued else marker.exists() == (result.outcome == "ok")
                    # Keep the requested pending count exact before each call.
                    if not continued and ("markers" in metadata or baseline is not None) and marker.exists():
                        marker.unlink()
                if sample:
                    times.append(elapsed)
                    outcomes[result.outcome] += 1
                    entries += result.entry is not None
                else:
                    warmup = dict(warmup_outcome=result.outcome,warmup_entry=result.entry is not None)
            rows.append(dict(name=name,samples=samples,deadline_ms=50,bytes=size,
                             outcome="ok" if outcomes=={"ok":samples} else "mixed",outcomes=dict(outcomes),
                             entries=entries,skipped=samples-entries,
                             median_ms=round(statistics.median(times),3),max_ms=round(max(times),3),**warmup,**metadata))
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
    return dict(schema=4,os=platform.system(),python=platform.python_version(),clock="perf_counter",cases=rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples",type=int,default=10,choices=range(1,101))
    try:
        data = measure(parser.parse_args().samples)
    except MeasurementFailure as error:
        print("CORTHEX_RAW_BENCH_FAILURE="+json.dumps(error.metadata))
        raise SystemExit(1)
    print("CORTHEX_RAW_BENCH="+json.dumps(data))
