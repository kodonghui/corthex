"""Isolated installed-host evidence; never operate on the caller's real home."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import secrets
import shutil
import time
clock_ns = (lambda: time.clock_gettime_ns(time.CLOCK_MONOTONIC)) if hasattr(time, "clock_gettime_ns") else time.monotonic_ns


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value) + "\n", encoding="utf-8")
    temporary.replace(path)


def package_copy(repository, output):
    target = output / "source"
    target.mkdir()
    for name in (".claude-plugin", ".agents/plugins", "plugins"):
        shutil.copytree(repository / name, target / name)
    memory = target / "plugins/corthex-memory"
    helpers = Path(__file__).parent
    original_hooks = memory / "hooks/hooks.json"
    original_worker = memory / "scripts/worker.py"
    pins = {"hooks": digest(original_hooks), "worker": digest(original_worker),
            "retention": digest(memory / "skills/corthex-memory/scripts/memory_lib/retention.py")}
    shutil.copyfile(original_worker, original_worker.with_name("worker_actual.py"))
    shutil.copyfile(helpers / "lifetime_worker.py", original_worker)
    shutil.copyfile(helpers / "measure_hook.py", memory / "scripts/measure_hook.py")
    source = original_hooks.read_text(encoding="utf-8")
    assert source.count("/scripts/hook.py") == 20
    original_hooks.write_text(source.replace("/scripts/hook.py", "/scripts/measure_hook.py"), encoding="utf-8")
    pins.update(instrumented_hooks=digest(original_hooks), instrumented_worker=digest(original_worker),
                original_entry_preserved=digest(original_worker.with_name("worker_actual.py")) == pins["worker"])
    write(output / "instrumentation.json", pins)
    return target, pins


def configure_lifetime(base, home, pins):
    from memory_lib import base as memory_base, raw_log
    folder = base / "lifetime"
    folder.mkdir()
    nonce = secrets.token_hex(16)
    root = home / ".corthex/corthex-memory/projects/demo/raw"
    old = root / (raw_log.log_name("codex", "lifetime-fixture") + ".jsonl")
    at = memory_base.utc_time(datetime.now(timezone.utc) - timedelta(days=101))
    entry = {"id": "e_000000000001", "seq": 1, "turn": 1, "at": at, "host": "codex",
             "session": "lifetime-fixture", "kind": "prompt", "speaker": "user", "text": "expired synthetic lifetime record"}
    old.write_bytes(memory_base.json_bytes(entry, "TBL-007", compact=True))
    return {"HOOKCHECK_LIFETIME_DIR": str(folder), "HOOKCHECK_LIFETIME_NONCE": nonce,
            "HOOKCHECK_RETENTION_SHA256": pins["retention"], "HOOKCHECK_ORIGINAL_WORKER_SHA256": pins["worker"]}, old


def release_lifetime(base, environment, host_run, old):
    folder = base / "lifetime"
    nonce = environment["HOOKCHECK_LIFETIME_NONCE"]
    ended = host_run["ended_monotonic_ns"]
    started = host_run["started_monotonic_ns"]
    hook_ended = host_run["hooks_ended_monotonic_ns"]
    boundary = max(ended, hook_ended)
    entered, heartbeat = {}, {}

    def read(name):
        try:
            value = json.loads((folder / (name + ".json")).read_bytes())
            return value if value.get("nonce") == nonce else {}
        except (OSError, ValueError):
            return {}

    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        entered, heartbeat = read("entered"), read("heartbeat")
        if entered and heartbeat.get("monotonic_ns", 0) > boundary:
            break
        time.sleep(.025)
    write(folder / "release.json", {"nonce": nonce, "host_exit_monotonic_ns": ended})
    deadline = time.monotonic() + 12
    while not read("returned") and time.monotonic() < deadline:
        time.sleep(.025)
    entry, resumed, returned = read("worker-entry"), read("resumed"), read("returned")
    rows = [json.loads(line) for line in old.read_bytes().splitlines()] if old.exists() else []
    removed = not any(row.get("id") == "e_000000000001" for row in rows)
    values = (entry, entered, heartbeat, resumed, returned)
    verified = (host_run["exit"] == 0 and all(values) and len({v.get("pid") for v in values}) == 1 and
                started <= entered["monotonic_ns"] <= ended <= boundary < heartbeat["monotonic_ns"] <= resumed["monotonic_ns"] <= returned["monotonic_ns"] and
                returned.get("entered_retention") is True and not read("barrier-timeout") and removed)
    return {"verified": bool(verified), "instrumented_call_barrier": True, "host_exit_monotonic_ns": ended,
            "hooks_exit_monotonic_ns": hook_ended, "worker_entry": entry,
            "entered": entered, "after_host_exit": heartbeat, "resumed": resumed, "returned": returned,
            "expired_record_removed": removed, "barrier_timed_out": bool(read("barrier-timeout"))}


def persistent_files(home):
    root = home / ".corthex/corthex-memory"
    paths = [root / name for name in ("store.json", "configuration.json")]
    paths += sorted(root.glob("projects/*/raw/*.jsonl"))
    return {path.relative_to(root).as_posix(): digest(path) for path in paths if path.exists()}


def reinstall(executable, host, environment, demo, home, execute):
    before = persistent_files(home)
    remove = ["plugin", "uninstall" if host == "claude" else "remove", "corthex-memory@corthex"]
    add = ["plugin", "install" if host == "claude" else "add", "corthex-memory@corthex"]
    removed = execute([executable] + remove, environment, demo)
    after_remove = persistent_files(home)
    installed = execute([executable] + add, environment, demo)
    after_install = persistent_files(home)
    return {"verified": removed["exit"] == installed["exit"] == 0 and bool(before) and before == after_remove == after_install,
            "uninstall_exit": removed["exit"], "reinstall_exit": installed["exit"],
            "before": before, "after_remove": after_remove, "after_install": after_install}


def external_clocks(base):
    hooks = ("start", "prompt", "end-of-turn", "end")
    deadline = time.monotonic() + 3
    while True:
        rows = [json.loads(path.read_bytes()) for path in sorted((base / "measurements").glob("*.json"))]
        if all(any(row["hook"] == hook for row in rows) for hook in hooks) or time.monotonic() >= deadline:
            break
        time.sleep(.025)
    return {"verified": all(any(row["hook"] == hook and row["exit"] == 0 for row in rows) for hook in hooks),
            "rows": rows, "p95_claimed": False, "minimum_samples_for_percentiles": 100}


def input_identity(base, session):
    inputs = [json.loads(path.read_bytes()) for path in (base / "inputs").glob("*.json")]
    events = {value.get("hook_event_name") for value in inputs}
    changed = {value.get("hook_event_name"): ["session_id:value"] for value in inputs if value.get("session_id") != session}
    verified = session is not None and len(inputs) == 4 and events == {"SessionStart", "UserPromptSubmit", "Stop", "SessionEnd"} and not changed
    return {"verified": verified, "changed_fields": changed,
            "scope": "native CLI/input session identity; TC-106 field/version/prefix drift remains follow-up"}
