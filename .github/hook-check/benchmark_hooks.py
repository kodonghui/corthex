"""External subprocess clocks with exactly 1,000 raw entries before each sample.

Replay the pinned native host's observed input shape against unchanged product
scripts. Fixture setup and coordinated restoration are outside the clock.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
import uuid

EVENTS = {"start": "SessionStart", "prompt": "UserPromptSubmit", "end-of-turn": "Stop", "end": "SessionEnd"}


def serialized_fixture(function):
    """Serialize fixture setup and observation, outside the product clock."""
    def guarded():
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/corthex-memory/scripts"))
        from memory_lib import clock, locks, worker_support
        hook = sys.argv[1]
        assert hook in EVENTS
        root = Path(os.environ["HOME"]) / ".corthex/corthex-memory"
        folder = Path(os.environ["HOOKCHECK_BENCHMARK_OBSERVATIONS"]).parent / "attempts"
        folder.mkdir(exist_ok=True)
        path = folder / (hook + "-" + str(os.getpid()) + ".json")
        note = {"hook": hook, "pid": os.getpid(), "nonce": os.environ["HOOKCHECK_BENCHMARK_NONCE"]}

        def checkpoint(phase, error=None):
            note.update(phase=phase, error=error)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(note) + "\n", encoding="utf-8")
            temporary.replace(path)

        checkpoint("waiting-fixture")
        try:
            memory = worker_support.WorkerStore(root)
            # This separate fixture path sorts before the nested product leases.
            with locks.Lock(root.parent / "benchmark-fixture.lock", "curation", memory.device).held(clock.now() + 10):
                checkpoint("running-fixture")
                result = function()
                checkpoint("completed")
                return result
        except Exception as error:
            frame = error.__traceback__
            while frame.tb_next:
                frame = frame.tb_next
            note["failure_frame"] = {"file": Path(frame.tb_frame.f_code.co_filename).name,
                                     "function": frame.tb_frame.f_code.co_name, "line": frame.tb_lineno}
            try:
                checkpoint("failed", type(error).__name__)
            except OSError:
                pass
            raise
    return guarded


def records(root, pattern):
    return [json.loads(line) for path in root.glob(pattern) for line in path.read_bytes().splitlines()]


def resize_seed(memory, seed, entries, previous):
    from memory_lib import clock, curation
    root, deadline = seed.parent.parent, clock.now() + 10
    with memory.lease(root / "curation.lock", "curation", deadline, acquire_deadline=deadline):
        with memory.lease(root / "layer.lock", "layer", deadline, acquire_deadline=deadline):
            if previous is not None:
                assert previous.parent == seed.parent and previous != seed
                with memory.lease(previous.with_suffix(".lock"), "raw", deadline, acquire_deadline=deadline):
                    memory.fence.check(previous)
                    previous.unlink()
                    for path in (root / "unprocessed").glob("*." + previous.stem + ".*"):
                        assert memory.fence.check(path).st_size == 0
                        path.unlink()
                    progress = curation.read(memory, root, deadline)
                    if progress["logs"].pop(previous.stem, None) is not None:
                        curation.write(memory, root, progress, deadline)
            with memory.lease(seed.with_suffix(".lock"), "raw", deadline, acquire_deadline=deadline):
                assert list(seed.parent.glob("*.jsonl")) == [seed]
                seed.write_bytes(b"".join(entries))
                assert sum(len(path.read_bytes().splitlines()) for path in seed.parent.glob("*.jsonl")) == 1000


def measure(plugin, host, output, prepare, base_env, samples=100):
    assert 1 <= samples <= 100
    sys.path.insert(0, str(plugin / "skills/corthex-memory/scripts"))
    from memory_lib import base, raw_log, worker_support
    templates = [json.loads(path.read_bytes()) for path in (output / "inputs").glob("*.json")]
    script = plugin / "scripts/hook.py"
    rows = []
    for hook, event_name in EVENTS.items():
        inputs = [value for value in templates if value.get("hook_event_name") == event_name]
        assert len(inputs) == 1, (host, hook, "native input missing or duplicated")
        home, project = prepare(output / "benchmark" / hook)
        root = home / ".corthex/corthex-memory"
        memory = worker_support.WorkerStore(root)
        seed = root / "projects/demo/raw" / (raw_log.log_name("codex", "external-benchmark-seed") + ".jsonl")
        at = base.utc_time()
        entries = [base.json_bytes({"id": "e_" + str(n).zfill(12), "seq": n, "turn": n, "at": at,
            "host": "codex", "session": "external-benchmark-seed", "kind": "prompt", "speaker": "user",
            "text": "synthetic benchmark seed"}, "TBL-007", compact=True) for n in range(1, 1001)]
        seed.write_bytes(b"".join(entries))
        environment = base_env(home)
        environment.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
        environment.update({"CLAUDECODE": "1"} if host == "claude" else {"PLUGIN_ROOT": str(plugin)})
        times, entry_counts, previous = [], [], None
        for number in range(samples + 1):
            resize_seed(memory, seed, entries, previous)
            event = dict(inputs[0], session_id=str(uuid.uuid4()), cwd=str(project))
            if "turn_id" in event:
                event["turn_id"] = str(uuid.uuid4())
            data = json.dumps(event, ensure_ascii=True).encode("ascii")
            before = len(records(root, "logs/hooks-*.jsonl"))
            started = time.perf_counter()
            result = subprocess.run([sys.executable, "-B", str(script), hook], input=data,
                env=environment, cwd=project, capture_output=True, timeout=15)
            elapsed = (time.perf_counter() - started) * 1000
            assert result.returncode == 0 and result.stderr == b"", (host, hook, number, result.stderr)
            if hook == "start":
                assert len(result.stdout.splitlines()) == 1 and result.stdout.isascii()
                assert set(json.loads(result.stdout)) == {"hookSpecificOutput"}
            else:
                assert result.stdout == b""
            new = records(root, "logs/hooks-*.jsonl")[before:]
            assert len(new) == 1 and new[0]["hook"] == hook and new[0]["outcome"] == "ok", (host, hook, number, new)
            count = len(records(root, "projects/*/raw/*.jsonl"))
            assert count == 1001, (host, hook, number, count)
            previous = seed.parent / (raw_log.log_name("claude-code" if host == "claude" else "codex", event["session_id"]) + ".jsonl")
            with (output / "benchmark" / hook / "samples.jsonl").open("a", encoding="utf-8") as log:
                log.write(json.dumps({"sample": number, "warmup": number == 0, "milliseconds": elapsed, "before": 1000, "after": count, "outcome": "ok"}) + "\n")
            if number:
                times.append(elapsed)
                entry_counts.append(1000)
        percentile = sorted(times)[math.ceil(.95 * len(times)) - 1] if samples == 100 else None
        rows.append({"hook": hook, "samples": samples, "warmups": 1, "raw_entries_before_each_sample": entry_counts,
            "milliseconds": times, "median_ms": statistics.median(times), "p95_ms": percentile,
            "under_100_ms": percentile < 100 if percentile is not None else None, "outcomes": {"ok": samples}})
        (output / "benchmark/progress.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    value = {"verified": samples == 100, "measurement_valid": True, "host": host, "os": platform.system(),
        "python": platform.python_version(), "interpreter_startup_included": True, "fixture_setup_included": False,
        "product_instrumented": False, "input_source": "pinned native host input with synthetic session/cwd/turn identifiers",
        "entry_sha256": hashlib.sha256(script.read_bytes()).hexdigest(), "percentile": "nearest rank, ceil(0.95*n)",
        "meets_100_ms_target": all(row["under_100_ms"] is True for row in rows), "rows": rows}
    (output / "benchmark/result.json").write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return value
