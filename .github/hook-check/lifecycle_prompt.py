"""Observe native starts and pace prompts before unchanged product hook children."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid


def wait_quiet_store(home, timeout=6, quiet=.25):
    """Observe a quiet interval, not worker completion or lossless recording."""
    root = home / ".corthex/corthex-memory"
    started, quiet_since, observed = time.monotonic(), None, []
    while time.monotonic() - started < timeout:
        busy = sorted(p.relative_to(root).as_posix() for p in root.rglob("*.lock"))
        if busy:
            quiet_since = None
            if not observed or observed[-1] != busy:
                observed.append(busy)
        else:
            quiet_since = time.monotonic() if quiet_since is None else quiet_since
            if time.monotonic() - quiet_since >= quiet:
                return {"quiet_ms":round(quiet * 1000), "wait_ms":round((time.monotonic()-started)*1000, 3),
                        "observed_leases":observed, "worker_completion_claimed":False}
        time.sleep(.025)
    raise AssertionError("Synthetic store did not reach the lifecycle test's quiet precondition")


def start_path(output, event):
    return output / ("start-" + hashlib.sha256(event["session_id"].encode("utf-8")).hexdigest() + ".json")


def write_start(path, value, seconds=2):
    pending = path.with_suffix("." + uuid.uuid4().hex + ".tmp")
    try:
        pending.write_text(json.dumps(value) + "\n", encoding="utf-8")
        # On Windows the prompt hook's read of the file refuses the replace for a moment (Access is denied).
        deadline = time.monotonic() + seconds
        while True:
            try:
                pending.replace(path)
                return
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.025)
    finally:
        # A write or replace that failed leaves no temporary file in the folder that later steps read, and a
        # removal that fails too leaves the first error to be raised.
        try:
            pending.unlink(missing_ok=True)
        except OSError:
            pass


def wait_start_completed(output, event, generation, timeout=6):
    path = start_path(output, event)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = json.loads(path.read_bytes())
            if (value.get("completed") is True and value.get("exit") == 0
                    and value.get("generation") == generation
                    and value.get("event_source") == generation["source"]):
                return value
        except (OSError, ValueError):
            pass
        time.sleep(.025)
    raise AssertionError("The native start hook child did not complete for this session")


def main():
    assert sys.argv[1:] in (["start"], ["prompt"])
    hook = sys.argv[1]
    incoming = sys.stdin.buffer.read()
    event = json.loads(incoming)
    output = Path(os.environ["HOOKCHECK_LIFECYCLE_GATES"])
    assert output.is_absolute()
    output.mkdir(parents=True, exist_ok=True)
    generation = json.loads((output / "generation.json").read_bytes())
    receipt = {"input_sha256":hashlib.sha256(incoming).hexdigest(), "started_ns":time.monotonic_ns(),
               "hook":hook, "generation":generation, "original_child_started":False}
    if hook == "start":
        assert event.get("source") == generation["source"], "The armed native start source must match"
        receipt["event_source"] = event["source"]
        write_start(start_path(output, event), dict(receipt, completed=False))
    try:
        if hook == "prompt":
            receipt["start_completion"] = wait_start_completed(output, event, generation)
            receipt["precondition"] = wait_quiet_store(Path.home())
        receipt["original_child_started"] = True
        receipt["child_started_ns"] = time.monotonic_ns()
        child = subprocess.run([sys.executable, "-I", str(Path(__file__).with_name("hook.py")), hook],
                               input=incoming, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        receipt["exit"] = child.returncode
        receipt["child_ended_ns"] = time.monotonic_ns()
        if hook == "start":
            write_start(start_path(output, event), dict(receipt, completed=True))
        sys.stdout.buffer.write(child.stdout); sys.stdout.buffer.flush()
        sys.stderr.buffer.write(child.stderr); sys.stderr.buffer.flush()
    finally:
        receipt["ended_ns"] = time.monotonic_ns()
        (output / (uuid.uuid4().hex + ".json")).write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    raise SystemExit(child.returncode)


if __name__ == "__main__":
    main()
