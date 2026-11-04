"""Bounded fixture barrier after original entry/runtime setup; byte-identical libraries run with profiling removed before waiting."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys
import time
import traceback
clock_ns = (lambda: time.clock_gettime_ns(time.CLOCK_MONOTONIC)) if hasattr(time, "clock_gettime_ns") else time.monotonic_ns


def main():
    folder = Path(os.environ["HOOKCHECK_LIFETIME_DIR"])
    if not folder.is_absolute():
        raise ValueError("the fixture barrier directory must be absolute")
    folder.mkdir(parents=True, exist_ok=True)
    nonce = os.environ["HOOKCHECK_LIFETIME_NONCE"]
    expected = os.environ["HOOKCHECK_RETENTION_SHA256"]
    original = Path(__file__).with_name("worker_actual.py")
    original_hash = hashlib.sha256(original.read_bytes()).hexdigest()
    if original_hash != os.environ["HOOKCHECK_ORIGINAL_WORKER_SHA256"]:
        raise ValueError("unexpected original worker entry")
    entered = []

    def write(name, **values):
        value = dict(nonce=nonce, pid=os.getpid(), monotonic_ns=clock_ns(), **values)
        temporary = folder / (name + ".tmp")
        temporary.write_text(json.dumps(value) + "\n", encoding="utf-8")
        deadline = time.monotonic() + .5
        while True:
            try:
                temporary.replace(folder / (name + ".json"))
                break
            except PermissionError:
                # A Windows observer may briefly have the old name open.
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.002)

    def observe(frame, event, unused):
        if event != "call" or frame.f_code.co_name != "retain_project":
            return
        source = Path(frame.f_code.co_filename)
        if source.name != "retention.py" or source.parent.name != "memory_lib":
            return
        if frame.f_locals.get("project") != "demo" or hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError("unexpected retention source or project")
        sys.setprofile(None)
        entered.append(True)
        write("entered", source_sha256=expected, function="retain_project", project="demo")
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            write("heartbeat")
            release = folder / "release.json"
            if release.exists():
                try:
                    value = json.loads(release.read_bytes())
                except PermissionError:
                    # A Windows file observer can briefly deny this read.
                    # Keep the original barrier deadline and nonce check.
                    value = {}
                if value.get("nonce") == nonce:
                    write("resumed", host_exit_monotonic_ns=value["host_exit_monotonic_ns"])
                    return
            time.sleep(.025)
        write("barrier-timeout")
        raise TimeoutError("host did not release the bounded fixture barrier")

    def profile(frame, event, unused):
        try:
            return observe(frame, event, unused)
        except BaseException:
            write("observer-error", traceback=traceback.format_exc())
            raise

    write("worker-entry", parent_pid=os.getppid(), arguments=sys.argv[1:], original_entry_sha256=original_hash)
    sys.setprofile(profile)
    try:
        runpy.run_path(str(original), run_name="__main__")
    finally:
        sys.setprofile(None)
        write("returned", entered_retention=bool(entered))


if __name__ == "__main__":
    main()
