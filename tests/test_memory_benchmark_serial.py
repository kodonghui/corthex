"""Concurrent native hook setup must not read a fixture being restored."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from _common import ROOT


class BenchmarkSerialTest(unittest.TestCase):
    def test_an_overlapping_hook_waits_for_fixture_restoration(self):
        spec = importlib.util.spec_from_file_location("serial_benchmark_fixture", ROOT / ".github/hook-check/run.py")
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary).resolve()
            home, demo = runner.prepare(folder / "profile")
            from memory_lib import base, clock, locks, raw_log, worker_support
            plugin = folder / "plugin"
            shutil.copytree(ROOT / "plugins/corthex-memory", plugin, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            for source, target in (("native_benchmark_hook.py", "benchmark_hook.py"),
                                   ("benchmark_hooks.py", "benchmark_support.py"), ("measure_hook.py", "benchmark_inner.py")):
                shutil.copyfile(ROOT / ".github/hook-check" / source, plugin / "scripts" / target)
            root = home / ".corthex/corthex-memory"
            memory = worker_support.WorkerStore(root)
            seed = root / "projects/demo/raw" / (raw_log.log_name("codex", "native-benchmark-seed") + ".jsonl")
            at = base.utc_time()
            entries = b"".join(base.json_bytes({"id": "e_" + str(n).zfill(12), "seq": n, "turn": n,
                "at": at, "host": "codex", "session": "native-benchmark-seed", "kind": "prompt",
                "speaker": "user", "text": "fixture"}, "TBL-007", compact=True) for n in range(1, 1001))
            observations = folder / "observations"
            for name in ("observations", "measurements", "inputs"):
                (folder / name).mkdir()
            ready, reading = folder / "ready", folder / "reading"
            bootstrap = """import importlib.util,sys
from pathlib import Path
from unittest.mock import patch
script,seed,ready,reading=map(Path,sys.argv[1:])
sys.argv=[str(script),'prompt']
sys.path.insert(0,str(script.parent))
spec=importlib.util.spec_from_file_location('serial_hook',script)
hook=importlib.util.module_from_spec(spec);spec.loader.exec_module(hook)
read=Path.read_bytes
def observed(path):
 if path==seed:reading.write_bytes(b'reading')
 return read(path)
ready.write_bytes(b'ready')
with patch.object(Path,'read_bytes',observed):sys.exit(hook.main())
"""
            env = runner.base_env(home)
            env.update(CLAUDECODE="1", CLAUDE_PLUGIN_ROOT=str(plugin), PYTHONUTF8="1",
                       HOOKCHECK_BENCHMARK_SEED=str(seed), HOOKCHECK_BENCHMARK_NONCE="fixture-nonce",
                       HOOKCHECK_BENCHMARK_OBSERVATIONS=str(observations),
                       HOOKCHECK_MEASURE_DIR=str(folder / "measurements"), HOOKCHECK_CAPTURE_INPUT_DIR=str(folder / "inputs"))
            payload = {"session_id": "fixture-session", "cwd": str(demo), "hook_event_name": "UserPromptSubmit",
                       "prompt": runner.PROMPT, "transcript_path": ""}
            with locks.Lock(root.parent / "benchmark-fixture.lock", "curation", memory.device).held(clock.now() + 20):
                seed.write_bytes(b"")
                child = subprocess.Popen([sys.executable, "-B", "-c", bootstrap, str(plugin / "scripts/benchmark_hook.py"),
                                          str(seed), str(ready), str(reading)], cwd=demo, env=env,
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    child.stdin.write(json.dumps(payload).encode("utf-8")); child.stdin.close(); child.stdin = None
                    deadline = time.monotonic() + 10
                    while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
                        time.sleep(.025)
                    self.assertTrue(ready.exists(), "child did not load the actual wrapper")
                    deadline = time.monotonic() + 1
                    while not reading.exists() and child.poll() is None and time.monotonic() < deadline:
                        time.sleep(.025)
                finally:
                    seed.write_bytes(entries)
            stdout, stderr = child.communicate(timeout=20)
            self.assertEqual(child.returncode, 0, stderr.decode("utf-8", "replace"))
            rows = [json.loads(path.read_bytes()) for path in observations.glob("*.json")]
            self.assertEqual([(row["before"], row["after"], row["outcome"]) for row in rows], [(1000, 1001, "ok")])
            attempts = [json.loads(path.read_bytes()) for path in (folder / "attempts").glob("*.json")]
            self.assertEqual([(row["phase"], row["error"]) for row in attempts], [("completed", None)])

    def test_setup_failure_preserves_safe_phase_and_source_without_exception_text(self):
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location("failed_benchmark_fixture", ROOT / ".github/hook-check/run.py")
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary).resolve()
            home, _ = runner.prepare(folder / "profile")
            (folder / "observations").mkdir()

            @runner.benchmark_hooks.serialized_fixture
            def fail():
                raise ValueError("private exception value must not be logged")

            with patch.dict("os.environ", {"HOME": str(home), "HOOKCHECK_BENCHMARK_NONCE": "fixture-nonce",
                    "HOOKCHECK_BENCHMARK_OBSERVATIONS": str(folder / "observations")}), patch.object(sys, "argv", ["hook", "prompt"]):
                with self.assertRaises(ValueError):
                    fail()
            raw = next((folder / "attempts").glob("*.json")).read_text(encoding="utf-8")
            note = json.loads(raw)
            self.assertEqual((note["phase"], note["error"], note["failure_frame"]["function"]), ("failed", "ValueError", "fail"))
            self.assertNotIn("private exception", raw)
