"""Manual 50 ms loss measurement, with zero or one competing CPU process.

Run --samples 100 in an isolated checker checkout under the Windows flock.
Both processes use one available core; no machine affinity setting changes.
Each profile resets its raw baseline outside timing. No real stores are used.
Ctrl-C stops the run; the load process and fixture are cleaned up on exit.
"""

import argparse
import ctypes
import json
import multiprocessing
import os
import platform
import statistics
import time
from collections import Counter

from test_memory_raw_log import RawLogTest, raw_log
from memory_lib import clock


def pin(core=None):
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        kernel.GetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
        kernel.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        handle, mask, system = kernel.GetCurrentProcess(), ctypes.c_size_t(), ctypes.c_size_t()
        if not kernel.GetProcessAffinityMask(handle, ctypes.byref(mask), ctypes.byref(system)):
            raise ctypes.WinError(ctypes.get_last_error())
        core = mask.value.bit_length()-1 if core is None else core
        if not mask.value & (1 << core) or not kernel.SetProcessAffinityMask(handle, 1 << core):
            raise RuntimeError("CPU affinity unavailable")
    else:
        core = max(os.sched_getaffinity(0)) if core is None else core
        os.sched_setaffinity(0, {core})
    return core


def load(stop, ready, core):
    pin(core)
    ready.send(True)
    value = 1
    while not stop.is_set():
        for _ in range(20000):
            value = (value*1664525+1013904223) & 0xffffffff


def measure(samples):
    assert raw_log.RECORD_SECONDS > 0 and raw_log.clock is clock
    core, rows = pin(), []
    context = multiprocessing.get_context("spawn")
    for competing in (False, True):
        stop, process = context.Event(), None
        if competing:
            incoming, outgoing = context.Pipe(duplex=False)
            process = context.Process(target=load, args=(stop, outgoing, core))
            process.start()
            if not incoming.poll(10) or incoming.recv() is not True:
                stop.set()
                process.terminate()
                process.join(5)
                raise RuntimeError("CPU load did not start")
        try:
            for name, prior_text, text in (("append-1KiB", "a"*1024, "a"*1024),
                    ("append-512KiB", "a"*(512*1024), "a"*(512*1024)),
                    ("after-control-512KiB", "\x01"*(512*1024), "a"*1024)):
                case = RawLogTest()
                case.setUp()
                try:
                    value = dict(case.record().entry, text=prior_text)
                    baseline = raw_log.base.json_bytes(value, "TBL-007", compact=True)
                    outcomes, times, entries, expired = Counter(), [], 0, 0
                    for _ in range(samples):
                        case.log.path.write_bytes(baseline)
                        for marker in case.markers():
                            if marker.name.endswith("."+case.log.log+".2"):
                                marker.unlink()
                        prepared = raw_log.prepare(text, {})
                        started = clock.now()
                        result = case.log.append("prompt", prepared, diagnostic_deadline=started+3)
                        ended = clock.now()
                        valid = (result.outcome == "ok" and result.entry is not None or
                            result.outcome == "deadline" and result.entry is not None and ended >= prepared.deadline or
                            result.outcome == "lock-busy" and result.entry is None and ended >= prepared.deadline)
                        if not valid:
                            raise RuntimeError("unexpected recording result")
                        outcomes[result.outcome] += 1
                        entries += result.entry is not None
                        expired += result.entry is None and ended >= prepared.deadline
                        times.append((ended-started)*1000)
                    rows.append(dict(name=name, cpu_load_processes=int(competing), samples=samples,
                        deadline_ms=raw_log.RECORD_SECONDS*1000, bytes=len(text.encode("utf-8")), tail_bytes=len(baseline),
                        entries=entries, expired_without_entry=expired, loss_percent=100*expired/samples,
                        outcomes=dict(outcomes), median_ms=round(statistics.median(times),3), max_ms=round(max(times),3)))
                finally:
                    case.doCleanups()
        finally:
            stop.set()
            if process is not None:
                process.join(5)
                if process.is_alive():
                    process.terminate()
                    process.join(5)
                incoming.close()
                outgoing.close()
    return dict(schema=1, os=platform.system(), python=platform.python_version(), clock="perf_counter",
                core=core, setup_included=False, warmups=0, rows=rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples",type=int,default=100,choices=range(1,101))
    try:
        data = measure(parser.parse_args().samples)
    except Exception as error:
        print("CORTHEX_RECORDING_LOSS_FAILURE="+json.dumps({"error":type(error).__name__}))
        raise SystemExit(1)
    print("CORTHEX_RECORDING_LOSS="+json.dumps(data))
