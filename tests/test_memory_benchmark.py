"""Exercise real subprocess samples without mistaking a short smoke run for p95."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from _common import ROOT


class WholeHookBenchmarkTest(unittest.TestCase):
    def test_fixture_home_and_project_use_real_paths_below_an_aliased_temp_parent(self):
        spec = importlib.util.spec_from_file_location("aliased_profile_fixture", ROOT / ".github/hook-check/run.py")
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        with tempfile.TemporaryDirectory() as temporary:
            owned = Path(temporary).resolve()
            target, alias = owned / "target", owned / "alias"
            target.mkdir()
            try:
                alias.symlink_to(target, target_is_directory=True)
            except OSError:
                program = shutil.which("cmd.exe") if os.name == "nt" else None
                if not program or not Path(program).is_absolute():
                    self.skipTest("directory aliases require host support")
                if any(char in str(alias) + str(target) for char in '%&|<>!^"'):
                    self.skipTest("junction fixture paths need shell escaping")
                made = subprocess.run([program, "/d", "/c", "mklink", "/J", str(alias), str(target)],
                                      capture_output=True, timeout=10)
                if made.returncode:
                    self.skipTest("directory aliases unavailable")
            self.assertEqual(alias.resolve(), target)
            try:
                home, project = runner.prepare(alias / "profile")
                self.assertEqual(home, home.resolve())
                self.assertEqual(project, project.resolve())
                from memory_lib import clock, worker_support
                root = home / ".corthex/corthex-memory"
                memory = worker_support.WorkerStore(root)
                deadline = clock.now() + 10
                with memory.lease(root / "projects/demo/curation.lock", "curation", deadline,
                                  acquire_deadline=deadline):
                    self.assertEqual(memory.fence.root, root)
            finally:
                self.assertEqual(alias.resolve(), target)
                if os.name == "nt":
                    alias.rmdir()
                else:
                    alias.unlink()

    def native_fixture(self, root):
        spec = importlib.util.spec_from_file_location("native_benchmark_fixture", ROOT / ".github/hook-check/run.py")
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        for name in ("observations", "measurements"):
            (root / name).mkdir()
        for pid, hook in enumerate(runner.native_benchmark.HOOKS, 101):
            observation = {"hook": hook, "pid": pid, "session": "native-session", "nonce": "fixture-nonce",
                           "before": 1000, "after": 1001, "outcome": "ok", "exit": 0}
            clock = {"hook": hook, "pid": pid, "child_pid": pid + 100, "exit": 0, "milliseconds": 42.5,
                     "started_monotonic_ns": 100000000, "ended_monotonic_ns": 142500000,
                     "interpreter_startup_included": True, "wrapper_startup_included": False,
                     "host_launch_overhead_included": False}
            for name, value in (("observations", observation), ("measurements", clock)):
                (root / name / (hook + ".json")).write_text(json.dumps(value), encoding="utf-8")
        return runner.native_benchmark

    def test_native_session_rejects_invalid_clocks_instead_of_claiming_fast_hooks(self):
        cases = [("milliseconds", -1), ("milliseconds", float("nan")), ("milliseconds", float("inf")),
                 ("started_monotonic_ns", 200000000), ("ended_monotonic_ns", 0)]
        for field, value in cases:
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                benchmark = self.native_fixture(root)
                path = root / "measurements/prompt.json"
                clock = json.loads(path.read_bytes())
                clock[field] = value
                path.write_text(json.dumps(clock), encoding="utf-8")
                with self.assertRaises(AssertionError):
                    benchmark.validate_session(root, "native-session", "fixture-nonce")

    def test_native_session_rejects_misattributed_missing_or_wrong_count_samples(self):
        cases = [("session", "another-session"), ("nonce", "stale-attempt"), ("before", 999),
                 ("after", 1000), ("outcome", "failed"), ("pid", 999), ("hook", "prompt")]
        for field, value in cases:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                benchmark = self.native_fixture(root)
                path = root / "observations/start.json"
                record = json.loads(path.read_bytes())
                record[field] = value
                path.write_text(json.dumps(record), encoding="utf-8")
                with self.assertRaises(AssertionError):
                    benchmark.validate_session(root, "native-session", "fixture-nonce")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            benchmark = self.native_fixture(root)
            observed, clocks = benchmark.validate_session(root, "native-session", "fixture-nonce")
            self.assertEqual((len(observed), len(clocks)), (4, 4))
            with patch.object(benchmark.Path, "glob", return_value=iter(())):
                with self.assertRaises(AssertionError):
                    benchmark.validate_session(root, "native-session", "fixture-nonce")

    def test_short_real_smoke_keeps_1000_entries_but_cannot_claim_the_100_sample_goal(self):
        spec = importlib.util.spec_from_file_location("benchmark_fixture", ROOT / ".github/hook-check/run.py")
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            inputs = output / "inputs"
            inputs.mkdir()
            contract = json.loads((ROOT / ".github/hook-check/host-inputs.json").read_bytes())["hosts"]["claude"]
            values = {"str": "fixture", "dict": {}, "list": [], "bool": False, "NoneType": None}
            for event, fields in contract["events"].items():
                value = {name: values[kind] for name, kind in fields.items()}
                value.update(hook_event_name=event, source="startup", reason="other",
                             prompt=runner.PROMPT, last_assistant_message=runner.REPLY)
                (inputs / (event + ".json")).write_text(json.dumps(value), encoding="utf-8")
            plugin = ROOT / "plugins/corthex-memory"
            result = runner.benchmark_hooks.measure(plugin, "claude", output, runner.prepare, runner.base_env, samples=1)
            self.assertTrue(result["measurement_valid"])
            self.assertFalse(result["verified"])
            self.assertFalse(result["meets_100_ms_target"])
            self.assertTrue(result["interpreter_startup_included"])
            self.assertFalse(result["product_instrumented"])
            self.assertEqual(len(result["rows"]), 4)
            for row in result["rows"]:
                self.assertEqual((row["samples"], row["warmups"], row["raw_entries_before_each_sample"]), (1, 1, [1000]))
                self.assertIsNone(row["p95_ms"])
                samples = [json.loads(line) for line in (output / "benchmark" / row["hook"] / "samples.jsonl").read_bytes().splitlines()]
                self.assertEqual([r["warmup"] for r in samples], [True, False])
                self.assertTrue(all(r["before"] == 1000 and r["after"] == 1001 and r["outcome"] == "ok" for r in samples))
