"""Whole hook timings after interpreter startup; generated fixtures only.

Each call uses a fresh interpreter. The clock starts at hook.py's STARTED
assignment, before its product imports, and ends after output and cleanup.
Reports contain only counts, outcomes and timings; no paths or conversation.
"""

import argparse
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plugins/corthex-memory/scripts/hook.py"
sys.path.insert(0, str(ROOT / "plugins/corthex-memory/skills/corthex-memory/scripts"))
sys.dont_write_bytecode = True
from memory_lib import base, files, store
from memory_lib import clock as memory_clock

MARKER = "CORTHEX_HOOK_BENCH="
CALL = "CORTHEX_HOOK_CALL="
EVENTS = {"start": "SessionStart", "prompt": "UserPromptSubmit", "end-of-turn": "Stop", "end": "SessionEnd"}
BUDGETS = {"start": 1000, "prompt": 900, "end-of-turn": 300, "end": 500}
WRAPPER = r'''
import sys, time, builtins
script, hook, mode = sys.argv[1:4]
sys.argv = [script, hook]
real_clock, started = time.perf_counter, []
def clock():
    value = real_clock()
    if sys._getframe(1).f_code.co_filename == script:
        started.append(value)
        time.perf_counter = real_clock
    return value
time.perf_counter = clock
if mode != "normal":
    original_import = builtins.__import__
    def importing(name, *args, **kwargs):
        module = original_import(name, *args, **kwargs)
        if name == "memory_lib.hooks":
            builtins.__import__ = original_import
            if mode == "slow-answer":
                raw = original_import("memory_lib.raw_log", fromlist=["redaction"])
                redacting = raw.redaction.redact
                def slow(text, environment=None):
                    time.sleep(0.32)
                    return redacting(text, environment)
                raw.redaction.redact = slow
            else:
                process = module.process
                def controlled(frame):
                    if mode == "slow-end":
                        time.sleep(0.52)
                    else:
                        raise RuntimeError("benchmark-fixture")
                    return process(frame)
                module.process = controlled
        return module
    builtins.__import__ = importing
status = 0
try:
    with open(script, "rb") as source:
        code = compile(source.read(), script, "exec")
    exec(code, {"__name__": "__main__", "__file__": script})
except SystemExit as error:
    status = error.code if isinstance(error.code, int) else 1
except Exception:
    status = 1
stopped = real_clock()
import json
print("CORTHEX_HOOK_CALL=" + json.dumps({"started": len(started) == 1, "exit": status,
      "ms": round((stopped-started[0])*1000, 3) if started else 0}))
'''


def fixture(folder, count, script):
    home, project = folder / "home", folder / "registered" / "sample"
    base.private_directory(home / ".corthex")
    project.mkdir(parents=True)
    roots = [{"name": "sample", "path": str(project)}]
    for index in range(1, count):
        path = folder / "registered" / ("project-%04d" % index)
        path.mkdir()
        roots.append({"name": "project-%04d" % index, "path": str(path)})
    (home / ".corthex/projects.json").write_text(json.dumps({"projects": roots}), encoding="utf-8")
    memory = store.MemoryStore(folder / "memory")
    base.private_directory(memory.folder / "logs")
    files.write_json(memory.folder / "store.json", store.new_record("0.2.0"), "TBL-001")
    at = base.utc_time()
    memory.write_configuration({"consent": {"at": at, "version": 1},
        "projects": {"sample": {"enabled": True, "since": at}}}, memory_clock.now() + 2)
    for name in ("raw", "unprocessed"):
        base.private_directory(memory.folder / "projects" / base.project_folder_name("sample") / name)
    environment = {k: v for k, v in os.environ.items() if k.upper() in
                   {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP"}}
    environment.update(HOME=str(home), USERPROFILE=str(home), CORTHEX_HOME=str(home / ".corthex"),
                       CORTHEX_MEMORY_HOME=str(memory.folder), CLAUDECODE="1", PLUGIN_ROOT="")
    wrapper = folder / "caller.py"
    wrapper.write_text(WRAPPER, encoding="utf-8")
    return project, memory.folder, environment, wrapper, script


def records(memory, pattern):
    return [json.loads(line) for path in sorted(memory.glob(pattern))
            for line in path.read_text(encoding="utf-8").splitlines()]


def attempt(state, hook, mode, number):
    project, memory, environment, wrapper, script = state
    before = len(records(memory, "projects/*/raw/*.jsonl"))
    timings = len(records(memory, "logs/hooks-*.jsonl"))
    event = {"hook_event_name": EVENTS[hook], "session_id": "%s-%s-%d" % (hook, mode, number),
             "cwd": str(project), "source": "startup", "prompt": "hello",
             "last_assistant_message": "한국어 답변", "reason": "other"}
    run = subprocess.run([sys.executable, "-B", str(wrapper), str(script), hook, mode],
                         input=json.dumps(event).encode("utf-8"), capture_output=True,
                         env=environment, cwd=str(project), timeout=15)
    lines = run.stdout.splitlines()
    marked = [line for line in lines if line.startswith(CALL.encode())]
    assert len(marked) == 1 and run.returncode == 0 and run.stderr == b"", "hook timing worker contract"
    measured = json.loads(marked[0].split(b"=", 1)[1])
    assert measured["started"] and measured["exit"] == 0
    output = [line for line in lines if not line.startswith(CALL.encode())]
    assert len(output) == int(hook == "start") and all(byte < 128 for line in output for byte in line)
    if output:
        assert set(json.loads(output[0])) == {"hookSpecificOutput"}
    new = len(records(memory, "projects/*/raw/*.jsonl")) - before
    log = records(memory, "logs/hooks-*.jsonl")[timings:]
    outcome = log[-1]["outcome"] if log else "base-only" if hook == "start" else "not-recorded"
    assert new in (0, 1)
    if mode == "error-end":
        assert outcome == "error" and new == 0
    elif mode == "slow-end":
        assert outcome in ("deadline","not-recorded") and new == 0
        assert measured["ms"] >= BUDGETS[hook]
    elif mode == "slow-answer":
        # A late hook still attempts recording within its raw budget. A busy
        # raw lease or expired write can skip the entry; late diagnostic locks
        # can also skip their lines. Retain these samples in the counts.
        assert outcome in ("deadline","not-recorded")
        assert measured["ms"] >= BUDGETS[hook]
    elif hook != "start":
        assert outcome in ("ok", "deadline", "lock-busy", "not-recorded")
        assert outcome != "ok" or new == 1
        assert outcome != "lock-busy" or new == 0
        assert outcome != "not-recorded" or measured["ms"] >= BUDGETS[hook]
    return measured["ms"], outcome, new


def measure(samples=5):
    rows = []
    with tempfile.TemporaryDirectory(prefix="c1-hook-bench-") as temporary:
        plugin = Path(temporary) / "plugin"
        shutil.copytree(SCRIPT.parent.parent, plugin, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for count in (1, 200, 1000):
            state = fixture(Path(temporary) / str(count), count, plugin / "scripts/hook.py")
            cases = [(hook, "normal") for hook in EVENTS]
            if count == 1:
                cases += [("end", "slow-end"), ("end", "error-end"), ("end-of-turn", "slow-answer")]
            for hook, mode in cases:
                warmup = attempt(state, hook, mode, -1)
                measured = [attempt(state, hook, mode, number) for number in range(samples)]
                times = [value[0] for value in measured]
                outcomes = dict(Counter(value[1] for value in measured))
                entries = sum(value[2] for value in measured)
                valid = not (count == 1 and hook == "end" and mode == "normal" and max(times) >= 500)
                rows.append({"hook": hook, "mode": mode, "registry": count, "samples": samples,
                             "warmups": 1, "warmup_outcome": warmup[1], "budget_ms": BUDGETS[hook],
                             "median_ms": round(statistics.median(times), 3), "max_ms": round(max(times), 3),
                             "outcomes": outcomes, "entries": entries,
                             "skipped_entries": 0 if hook == "start" else samples - entries,
                             "over_budget": sum(value >= BUDGETS[hook] for value in times), "valid": valid})
    return {"schema": 1, "os": platform.system(), "python": platform.python_version(),
            "clock": "hook.py STARTED through return", "clock_source": "perf_counter", "interpreter_start_included": False,
            "product_imports_included": True, "plugin_bytecode_excluded": True,
            "fixture_setup_included": False, "rows": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=5, choices=range(1, 21))
    args = parser.parse_args()
    result = measure(args.samples)
    print(MARKER + json.dumps(result, ensure_ascii=True))
    sys.exit(0 if all(row["valid"] for row in result["rows"]) else 1)
