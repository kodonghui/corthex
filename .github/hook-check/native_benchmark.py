"""100 real native sessions, restoring exactly 1,000 entries before every hook."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import platform
import secrets
import shutil
import statistics
import tempfile
import time

from network_proxy import NetworkProxy

HOOKS = ("start", "prompt", "end-of-turn", "end")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_session(folder, session, nonce):
    observed = [json.loads(p.read_bytes()) for p in (folder / "observations").glob("*.json")]
    clocks = [json.loads(p.read_bytes()) for p in (folder / "measurements").glob("*.json")]
    assert len(observed) == len(clocks) == 4 and {r["hook"] for r in observed} == set(HOOKS)
    assert all(r["nonce"] == nonce and r["session"] == session and r["before"] == 1000 and r["after"] == 1001 and r["outcome"] == "ok" and r["exit"] == 0 for r in observed)
    assert {(r["hook"], r["pid"]) for r in clocks} == {(r["hook"], r["pid"]) for r in observed}
    assert all(r["exit"] == 0 and r["interpreter_startup_included"] and not r["wrapper_startup_included"] and not r["host_launch_overhead_included"] for r in clocks)
    assert all(isinstance(r["milliseconds"], (int, float)) and not isinstance(r["milliseconds"], bool) and
               math.isfinite(r["milliseconds"]) and r["milliseconds"] > 0 and
               type(r["started_monotonic_ns"]) is int and type(r["ended_monotonic_ns"]) is int and
               0 < r["started_monotonic_ns"] < r["ended_monotonic_ns"] for r in clocks)
    return observed, clocks


def measure(repository, host, output, model, samples=100):
    assert host in ("claude", "codex") and 1 <= samples <= 100
    output.mkdir(parents=True)
    # A short private profile avoids Windows path/socket limits. Retain it on failure.
    temporary = Path(tempfile.mkdtemp(prefix="c1bench-"))
    (output / "start.json").write_text(json.dumps({"temporary_profile_retained": str(temporary),
        "host": host, "samples": samples, "warmups": 1, "real_model": False,
        "source_worker_sha256": digest(repository / "plugins/corthex-memory/scripts/worker.py")}) + "\n", encoding="utf-8")
    source = temporary / "source"
    source.mkdir()
    for name in (".claude-plugin", ".agents/plugins", "plugins"):
        shutil.copytree(repository / name, source / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    plugin = source / "plugins/corthex-memory"
    original = repository / "plugins/corthex-memory"
    helper = Path(__file__).parent
    pins = {p.relative_to(original).as_posix(): digest(p) for p in original.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    hooks = plugin / "hooks/hooks.json"
    text = hooks.read_text(encoding="utf-8")
    assert text.count("/scripts/hook.py") == 20
    hooks.write_text(text.replace("/scripts/hook.py", "/scripts/benchmark_hook.py"), encoding="utf-8")
    for src, dst in (("native_benchmark_hook.py", "benchmark_hook.py"),
                     ("benchmark_hooks.py", "benchmark_support.py"), ("measure_hook.py", "benchmark_inner.py")):
        shutil.copyfile(helper / src, plugin / "scripts" / dst)
    assert all(digest(plugin / n) == h for n, h in pins.items() if n != "hooks/hooks.json")
    spec = importlib.util.spec_from_file_location("native_benchmark_runner", helper / "run.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    runner.REPO, runner.MEMORY = source, plugin
    prepare, execute, base_env = runner.prepare, runner.run, runner.base_env
    nonce, sessions, state = secrets.token_hex(16), [], {}
    network, memory_network = NetworkProxy(), NetworkProxy()
    old_log = model.log
    network_result = None

    def environment(home):
        value = base_env(home)
        value.update(network.environment(), HOOKCHECK_MEMORY_PROXY=memory_network.url)
        return value

    def provision(base):
        home, demo = prepare(base)
        from memory_lib import base as memory_base, raw_log
        seed = home / ".corthex/corthex-memory/projects/demo/raw" / (raw_log.log_name("codex", "native-benchmark-seed") + ".jsonl")
        at = memory_base.utc_time()
        entries = [memory_base.json_bytes({"id": "e_" + str(n).zfill(12), "seq": n, "turn": n, "at": at,
            "host": "codex", "session": "native-benchmark-seed", "kind": "prompt", "speaker": "user",
            "text": "synthetic benchmark seed"}, "TBL-007", compact=True) for n in range(1, 1001)]
        seed.write_bytes(b"".join(entries))
        state["seed"] = seed
        return home, demo

    def invoke(args, env, cwd=None, **kwargs):
        if "--version" in args:
            result = execute(args, env, cwd, **kwargs)
            state["version"] = result["stdout"].strip()
            return result
        native = "-p" in args if host == "claude" else len(args) > 1 and args[1] == "exec"
        if not native:
            return execute(args, env, cwd, **kwargs)
        args = list(args)
        if "--debug-file" in args:
            offset = args.index("--debug-file")
            del args[offset:offset+2]
        for index in range(samples + 1):
            folder = output / ("%03d" % index)
            for name in ("measurements", "inputs", "observations"):
                (folder / name).mkdir(parents=True)
            current = dict(env, HOOKCHECK_BENCHMARK_SEED=str(state["seed"]), HOOKCHECK_BENCHMARK_NONCE=nonce,
                HOOKCHECK_MEASURE_DIR=str(folder / "measurements"), HOOKCHECK_CAPTURE_INPUT_DIR=str(folder / "inputs"),
                HOOKCHECK_BENCHMARK_OBSERVATIONS=str(folder / "observations"))
            result = execute(args, current, cwd, **kwargs)
            key = "ANTHROPIC_API_KEY" if host == "claude" else "MOCK_KEY"
            (folder / "native-run.json").write_text(json.dumps(runner.scrub_mock_key(result, current[key])) + "\n", encoding="utf-8")
            assert result["exit"] == 0, "native benchmark session failed; retain the attempt"
            session = runner.native_session(host, result)
            deadline = time.monotonic() + 6
            while len(list((folder / "observations").glob("*.json"))) != 4 and time.monotonic() < deadline:
                time.sleep(.025)
            observed, clocks = validate_session(folder, session, nonce)
            contract = runner.native_evidence.input_contract(folder, host, state["version"], session)
            assert contract["verified"], contract
            sessions.append({"index": index, "warmup": index == 0, "session": session, "clocks": clocks,
                             "input_contract": contract, "observations": observed})
            (output / "progress.json").write_text(json.dumps(sessions) + "\n", encoding="utf-8")
        return result

    runner.prepare, runner.run, runner.base_env = provision, invoke, environment
    try:
        diagnostic = temporary / "hk"
        runner.market(diagnostic)
        result = getattr(runner, host)("benchmark", temporary, model, diagnostic, [])
        assert result["install"] and all(r["exit"] == 0 for r in result["install"].values())
        assert len(sessions) == samples + 1 and len({r["session"] for r in sessions}) == samples + 1
        network_result = {"host": network.finish(), "memory": memory_network.finish()}
        assert network_result["memory"]["verified"], "the MEMORY proxy observed egress during native measurement"
        rows = []
        for hook in HOOKS:
            values = [next(c["milliseconds"] for c in r["clocks"] if c["hook"] == hook) for r in sessions[1:]]
            p95 = sorted(values)[math.ceil(.95 * len(values)) - 1] if samples == 100 else None
            rows.append({"hook": hook, "samples": samples, "warmups": 1, "milliseconds": values,
                "raw_entries_before_each_sample": [1000] * samples, "median_ms": statistics.median(values),
                "p95_ms": p95, "under_100_ms": p95 < 100 if p95 is not None else None, "outcomes": {"ok": samples}})
        value = {"verified": samples == 100, "measurement_valid": True, "mode": "actual-native-sessions",
            "native_sessions": len(sessions), "host": host, "version": result["version"],
            "os": platform.system(), "python": platform.python_version(), "interpreter_startup_included": True,
            "fixture_setup_included": False, "product_instrumented": False,
            "entry_sha256": pins["scripts/hook.py"], "worker_sha256": pins["scripts/worker.py"],
            "original_runtime_files_preserved": True, "test_wrapper_configured": True,
            "modified_package_file": "hooks/hooks.json", "installation": result["install"],
            "network": network_result,
            "runtime_hashes": {n: h for n, h in pins.items() if n != "hooks/hooks.json"}, "rows": rows,
            "meets_100_ms_target": all(r["under_100_ms"] is True for r in rows),
            "temporary_profile_retained": str(temporary), "finished_utc": datetime.now(timezone.utc).isoformat()}
        (output / "result.json").write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        return value
    finally:
        model.log = old_log
        if network_result is None:
            network_result = {"host": network.finish(), "memory": memory_network.finish()}
        (output / "network.json").write_text(json.dumps(network_result) + "\n", encoding="utf-8")
