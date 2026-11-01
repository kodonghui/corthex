"""Real C1 worker phases, store binding and lifetime; session hooks stay TASK-017."""
from datetime import datetime, timedelta, timezone
import contextlib
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest import mock

from test_memory_store import AT, SCRIPTS, StoreCase
from test_memory_cleanup import hold
from test_memory_worker_launch import PARENT, fixture_child_exit
from memory_lib import base, cleanup, clock, curation, locks, raw_log, retention
from memory_lib import worker_launch, worker_runtime, worker_support

ENTRY = SCRIPTS.parents[2] / "scripts/worker.py"
NOW = datetime.now(timezone.utc)
MARKER = "made-up-worker-runtime-private-marker"

CHILD = '''import json, os, runpy, sys, time
from pathlib import Path
root = Path.cwd()
before = os.nice(0) if os.name != "nt" else None
evidence = {"stdin_eof": sys.stdin.buffer.read() == b"", "isolated": sys.flags.isolated == 1,
            "marker_received": os.environ.get("CORTHEX_MEMORY_TEST_TOKEN") == MARKER,
            "pythonpath_ignored": os.environ["PYTHONPATH"] not in sys.path,
            "argv": sys.argv[1:], "cwd_matches": root == Path(os.environ["CORTHEX_MEMORY_HOME"])}
print("fixture null stdout", flush=True)
print("fixture null stderr", file=sys.stderr, flush=True)
until = time.monotonic() + 15
while not (root / "fixture-go").exists():
    if time.monotonic() >= until:
        raise SystemExit(20)
    time.sleep(.01)
try:
    runpy.run_path(REAL_ENTRY, run_name="__main__")
except SystemExit as result:
    evidence["quiet_exit"] = result.code == 0
evidence["own_library"] = Path(sys.modules["memory_lib.worker_runtime"].__file__).resolve() == REAL_LIBRARY
if os.name != "nt":
    evidence["own_session"] = os.getsid(0) == os.getpid() == os.getpgrp()
    evidence["nice_before"], evidence["nice_after"] = before, os.nice(0)
temporary = root / "fixture-finished.tmp"
temporary.write_text(json.dumps(evidence), encoding="utf-8")
temporary.replace(root / "fixture-finished.json")
if os.name == "nt":
    time.sleep(.25)  # Completion evidence precedes process exit; exercise the cleanup barrier.
'''


class WorkerRuntimeTest(StoreCase):
    def setUp(self):
        super().setUp()
        self.device = self.header["device"]
        (self.root / "configuration.json").write_bytes(base.json_bytes({}, "TBL-002"))
        self.log = raw_log.log_name("codex", "worker-runtime-fixture")
        self.project("sample")

    def project(self, name):
        root = self.root / "projects" / base.project_folder_name(name)
        base.private_directory(root / "raw")
        base.private_directory(root / "unprocessed")
        entries = [{"id": "e_" + str(seq).zfill(12), "seq": seq, "turn": seq,
                    "at": base.utc_time(NOW - timedelta(days=days)), "host": "codex",
                    "session": "worker-runtime-fixture", "kind": "prompt", "speaker": "user",
                    "text": "fixture-%d" % seq} for seq, days in ((1, 101), (2, 99))]
        (root / "raw" / (self.log + ".jsonl")).write_bytes(
            b"".join(base.json_bytes(e, "TBL-007", compact=True) for e in entries))
        record = {"logs": {self.log: 2}, "applies": 4, "recent": [], "consolidation": {"failures": 0}}
        (root / "curation.json").write_bytes(base.json_bytes(record, "TBL-009"))
        return root

    def rows(self, name="sample"):
        root = self.root / "projects" / base.project_folder_name(name)
        return [json.loads(l) for l in (root / "raw" / (self.log + ".jsonl")).read_bytes().splitlines()]

    def run_worker(self, project="sample", reason="start", expected=True):
        return worker_runtime.run(project, reason, self.device if expected else None, self.root)

    def failures(self):
        return [json.loads(l) for p in (self.root / "logs").glob("failures-*.jsonl")
                for l in p.read_bytes().splitlines()]

    def aged(self, path, seconds):
        path.write_bytes(b"owned fixture")
        value = time.time_ns() - seconds * 1000000000
        os.utime(path, ns=(value, value))
        return path

    def test_tc331_missing_initial_folder_maintains_disabled_unconsented_keyless_projects(self):
        self.project("disabled")
        config = {"projects": {"disabled": {"enabled": False, "since": AT}}}
        (self.root / "configuration.json").write_bytes(base.json_bytes(config, "TBL-002"))
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("ANTHROPIC", "OPENAI", "CORTHEX_MEMORY_"))}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertIsNone(self.run_worker("registered-without-folder"))
        self.assertFalse((self.root / "projects/registered-without-folder").exists())
        for name in ("sample", "disabled"):
            self.assertEqual([x["seq"] for x in self.rows(name)], [2])
            path = self.root / "projects" / name / "curation.json"
            self.assertEqual(curation.parse(path.read_bytes())["logs"][self.log], 2)
        self.assertEqual(self.failures(), [])

    def test_tc331_retention_lowers_progress_before_reusing_deleted_tail_sequence(self):
        root = self.root / "projects/sample"
        entries = self.rows()
        entries[0]["at"], entries[1]["at"] = entries[1]["at"], entries[0]["at"]
        (root / "raw" / (self.log + ".jsonl")).write_bytes(
            b"".join(base.json_bytes(e, "TBL-007", compact=True) for e in entries))
        self.run_worker()
        self.assertEqual([x["seq"] for x in self.rows()], [1])
        progress = lambda: curation.parse((root / "curation.json").read_bytes())["logs"][self.log]
        self.assertEqual(progress(), 1)
        result = raw_log.RawLog(self.memory, "sample", "codex", "worker-runtime-fixture").append(
            "prompt", raw_log.prepare("new sequence after worker"), diagnostic_deadline=clock.now() + 5)
        self.assertEqual(result.outcome, "ok")
        self.assertEqual(result.entry["seq"], 2)
        self.assertLess(progress(), result.entry["seq"])

    def test_tc331_retention_precedes_cleanup_in_sorted_nonoverlapping_phases(self):
        for name in ("zzz", "con", "aaa", "a", "a-b"):
            self.project(name)
        events = []
        def observe(label, original, project_phase):
            def call(memory, *args):
                curation_leases = [x for x in memory.held if x.policy == locks.POLICIES["curation"]]
                self.assertEqual(len(curation_leases), 1 if project_phase else 0)
                if not project_phase:
                    self.assertEqual(memory.held, [])
                events.append((label, args[0] if project_phase else None))
                return original(memory, *args)
            return call
        functions = [(retention, "retain_project", True), (retention, "retain_logs", False),
                     (cleanup, "clean_store", False), (cleanup, "clean_project", True), (cleanup, "clean_logs", False)]
        with contextlib.ExitStack() as stack:
            for module, name, project_phase in functions:
                stack.enter_context(mock.patch.object(module, name, observe(name, getattr(module, name), project_phase)))
            self.run_worker("zzz")
        ordered = ["a-b", "a", "aaa", "con", "sample", "zzz"]
        self.assertEqual(events, [("retain_project", x) for x in ordered] + [("retain_logs", None),
                         ("clean_store", None)] + [("clean_project", x) for x in ordered] + [("clean_logs", None)])
        for name in ordered:
            self.assertFalse((self.root / "projects" / base.project_folder_name(name) / "curation.lock").exists())

    def test_tc058_real_worker_cleans_only_old_owned_artifacts_after_retention(self):
        raw = self.root / "projects/sample/raw"
        old = self.aged(raw / (self.log + ".jsonl.abcdefgh.tmp"), 660)
        young = self.aged(raw / (self.log + ".jsonl.ijklmnop.tmp"), 540)
        unknown = self.aged(raw / "unknown.json.abcdefgh.tmp", 660)
        (raw / "items.json.bak").write_bytes(b"unknown C2")
        (self.root / "logs/failures-2000-01-01.jsonl").write_bytes(b"{}\n")
        (self.root / "logs/hooks-2000-01-01.jsonl").write_bytes(b"{}\n")
        self.run_worker()
        self.assertFalse(old.exists())
        self.assertTrue(young.exists() and unknown.exists() and (raw / "items.json.bak").exists())
        self.assertFalse((self.root / "logs/failures-2000-01-01.jsonl").exists())
        self.assertFalse((self.root / "logs/hooks-2000-01-01.jsonl").exists())
        self.assertEqual([x["seq"] for x in self.rows()], [2])

    def test_tc331_nonstart_reasons_do_only_the_existing_project_gate(self):
        before = self.snapshot()
        for reason in ("skill", "end-of-turn", "end"):
            self.run_worker(reason=reason)
            self.run_worker("missing", reason)
            self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.root / "projects/missing").exists())

    def test_tc057_real_fresh_initial_lease_ends_worker_without_changes(self):
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        path = self.root / "projects/sample/curation.lock"
        process = context.Process(target=hold, args=(child, str(path), "curation", self.device))
        process.start()
        child.close()
        try:
            self.assertTrue(parent.poll(15))
            self.assertTrue(parent.recv())
            before = self.snapshot()
            self.run_worker()
            self.assertEqual(self.snapshot(), before)
        finally:
            parent.send("stop")
            process.join(15)
            if process.is_alive():
                process.kill()
                process.join(5)
            parent.close()
        self.assertEqual(process.exitcode, 0)

    def test_tc331_busy_other_project_is_untouched_and_later_project_runs(self):
        busy = self.project("aaa")
        path = busy / "curation.lock"
        path.write_text(json.dumps({"token": "a" * 32}), encoding="utf-8")
        before = {p.name: p.read_bytes() for p in busy.rglob("*") if p.is_file()}
        self.run_worker()
        self.assertEqual({p.name: p.read_bytes() for p in busy.rglob("*") if p.is_file()}, before)
        self.assertEqual([x["seq"] for x in self.rows()], [2])
        self.assertEqual(self.failures(), [])

    def test_tc331_invalid_configuration_stops_maintenance_without_provisioning(self):
        for document in (b'{"retention":{"days":0}}', b'{"unknown":"' + MARKER.encode() + b'"}'):
            (self.root / "configuration.json").write_bytes(document)
            before = self.snapshot()
            self.run_worker("missing")
            self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.root / "projects/missing").exists())

    def test_tc331_blocked_store_gates_never_write_data_or_diagnostics(self):
        path = self.root / "store.json"
        for value in ({**self.header, "format": 2}, {**self.header, "migrating": {}}, None):
            path.write_bytes(b"damaged" if value is None else json.dumps(value).encode())
            before = self.snapshot()
            self.run_worker()
            self.assertEqual(self.snapshot(), before)
        path.unlink()
        before = self.snapshot()
        self.run_worker()
        self.assertEqual(self.snapshot(), before)

    def test_tc331_expected_device_blocks_primary_and_backup_before_recovery(self):
        other = {**self.header, "device": base.new_id("d")}
        path = self.root / "store.json"
        for primary in (base.json_bytes(other, "TBL-001"), b"damaged"):
            path.write_bytes(primary)
            path.with_name("store.json.bak").write_bytes(base.json_bytes(other, "TBL-001"))
            before = self.snapshot()
            self.run_worker()
            self.assertEqual(self.snapshot(), before)

    def test_tc331_direct_launch_without_expected_device_binds_first_read(self):
        self.assertIsNone(self.run_worker(expected=False))
        self.assertEqual([x["seq"] for x in self.rows()], [2])
        self.assertEqual(self.failures(), [])

    def test_tc331_store_replacement_stops_subsequent_phases_and_stale_diagnostics(self):
        original = retention.retain_project
        calls = []
        def replace(memory, *args):
            calls.append(args[0])
            candidate = self.root / "fixture-replacement"
            candidate.write_bytes(base.json_bytes(self.header, "TBL-001"))
            candidate.replace(self.root / "store.json")
            return original(memory, *args)
        with mock.patch.object(retention, "retain_project", replace), mock.patch.object(cleanup, "clean_store") as clean:
            self.run_worker()
            clean.assert_not_called()
        self.assertEqual(calls, ["sample"])
        self.assertEqual([x["seq"] for x in self.rows()], [1, 2])
        self.assertEqual(self.failures(), [])

    def test_tc331_lost_curation_token_stops_after_release_and_preserves_new_holder(self):
        original = retention.retain_project
        def replace(memory, project, owner, deadline):
            document = json.loads(owner.path.read_text(encoding="utf-8"))
            document["token"] = "0" * 32
            owner.path.write_text(json.dumps(document), encoding="utf-8")
            return original(memory, project, owner, deadline)
        with mock.patch.object(retention, "retain_project", replace), mock.patch.object(cleanup, "clean_store") as clean:
            self.run_worker()
            clean.assert_not_called()
        self.assertEqual([x["seq"] for x in self.rows()], [1, 2])
        self.assertEqual(json.loads((self.root / "projects/sample/curation.lock").read_text())["token"], "0" * 32)
        self.assertTrue(self.failures())
        self.assertTrue(all(x["error"] == "lost-lock" for x in self.failures()))

    def test_tc331_unsafe_active_lease_ends_before_next_project_or_global_cleanup(self):
        self.project("zzz")
        original, seen = retention.retain_project, []
        def guarded(memory, project, owner, deadline):
            seen.append(project)
            if project != "sample":
                return original(memory, project, owner, deadline)
            check = memory.fence.check
            def unsafe(path):
                if path == owner.path:
                    raise worker_support.UnsafePath()
                return check(path)
            with mock.patch.object(memory.fence, "check", unsafe):
                return original(memory, project, owner, deadline)
        with mock.patch.object(retention, "retain_project", guarded), mock.patch.object(cleanup, "clean_store", wraps=cleanup.clean_store) as clean:
            self.run_worker()
            self.assertEqual(seen, ["sample"])
            clean.assert_not_called()
        self.assertEqual([x["seq"] for x in self.rows("zzz")], [1, 2])
        self.assertTrue(self.failures())
        self.assertTrue(all(x["error"] == "lost-lock" for x in self.failures()))

    def test_tc332_phase_expiry_keeps_original_deadline_and_leaves_work_for_next_start(self):
        original, now, offset = retention.retain_project, clock.now, [0]
        deadlines = []
        def expire(memory, project, owner, deadline):
            deadlines.append(deadline)
            offset[0] = worker_support.PHASE_SECONDS + 1
            return original(memory, project, owner, deadline)
        with mock.patch.object(clock, "now", lambda: now() + offset[0]), mock.patch.object(retention, "retain_project", expire), mock.patch.object(cleanup, "clean_store") as clean:
            self.run_worker()
            clean.assert_not_called()
        self.assertEqual(len(deadlines), 1)
        self.assertEqual([x["seq"] for x in self.rows()], [1, 2])
        self.assertFalse((self.root / "projects/sample/curation.lock").exists())
        self.assertEqual(self.failures(), [])
        self.run_worker()
        self.assertEqual([x["seq"] for x in self.rows()], [2])

    def test_tc332_zero_gate_budget_stops_before_data_changes(self):
        before = self.snapshot()
        with mock.patch.object(worker_support, "OPERATION_SECONDS", 0):
            self.run_worker()
        self.assertEqual(self.snapshot(), before)

    def test_tc332_retention_errors_log_safe_metadata_after_leases_then_continue(self):
        self.project("aaa")
        original, failure = retention.retain_project, worker_support.WorkerStore.failure
        held = []
        def fail_first(memory, project, owner, deadline):
            if project == "aaa":
                raise OSError(MARKER)
            return original(memory, project, owner, deadline)
        def observe(memory, *args, **kwargs):
            held.append(list(memory.held))
            return failure(memory, *args, **kwargs)
        with mock.patch.object(retention, "retain_project", fail_first), mock.patch.object(worker_support.WorkerStore, "failure", observe):
            self.run_worker()
        self.assertEqual([x["seq"] for x in self.rows("aaa")], [1, 2])
        self.assertEqual([x["seq"] for x in self.rows()], [2])
        self.assertEqual(held, [[]])
        self.assertEqual([(x["error"], x["step"]) for x in self.failures()], [("OSError", "retention")])
        self.assertNotIn(MARKER, str(self.snapshot()))

    def test_tc332_cleanup_error_uses_restore_without_exception_text(self):
        with mock.patch.object(cleanup, "clean_store", side_effect=PermissionError(MARKER)):
            self.run_worker()
        self.assertEqual([(x["error"], x["step"]) for x in self.failures()], [("PermissionError", "restore")])
        self.assertNotIn(MARKER, str(self.snapshot()))

    def test_tc332_diagnostics_expire_with_their_own_operation_budget(self):
        def error(*args):
            worker_support.OPERATION_SECONDS = 0
            raise OSError(MARKER)
        with mock.patch.object(worker_support, "OPERATION_SECONDS", worker_support.OPERATION_SECONDS), mock.patch.object(retention, "retain_project", error):
            self.run_worker()
        self.assertEqual(self.failures(), [])
        self.assertEqual([x["seq"] for x in self.rows()], [1, 2])

    def test_tc331_inventory_preserves_noncanonical_names_files_and_outside_aliases(self):
        projects = self.root / "projects"
        (projects / "not-a-directory").write_bytes(b"preserve")
        bad = projects / "not_canonical"
        bad.mkdir()
        (bad / "fixture").write_bytes(b"preserve")
        if os.name != "nt":
            outside = self.folder / "outside"
            outside.mkdir()
            (outside / "fixture").write_bytes(b"preserve")
            (projects / "linked").symlink_to(outside, target_is_directory=True)
        self.run_worker()
        self.assertEqual((projects / "not-a-directory").read_bytes(), b"preserve")
        self.assertEqual((bad / "fixture").read_bytes(), b"preserve")
        if os.name != "nt":
            self.assertEqual((outside / "fixture").read_bytes(), b"preserve")
        self.assertEqual([x["seq"] for x in self.rows()], [2])

    def test_tc331_no_store_or_logs_directory_is_created(self):
        missing = self.folder / "absent-store"
        worker_runtime.run("sample", "start", folder=missing)
        self.assertFalse(missing.exists())
        (self.root / "logs").rmdir()
        self.run_worker()
        self.assertFalse((self.root / "logs").exists())

    def test_tc332_entry_is_quiet_for_invalid_arguments_and_invalid_home(self):
        vectors = [[], ["--help"], ["--reason", "start", "--project", "../outside"],
                   ["--reason", "start", "--reason", "start"],
                   ["--reason", MARKER, "--project", "sample"],
                   ["--reason", "start", "--project", "sample", "--expect-device", MARKER]]
        before = self.snapshot()
        for args in vectors:
            result = subprocess.run([sys.executable, "-I", str(ENTRY)] + args, cwd=self.folder,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))
            self.assertEqual(self.snapshot(), before)
        env = dict(os.environ, CORTHEX_MEMORY_HOME="relative-invalid-home")
        result = subprocess.run([sys.executable, "-I", str(ENTRY), "--reason", "start", "--project", "sample"],
                                env=env, cwd=self.folder, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))
        self.assertFalse((self.folder / "relative-invalid-home").exists())

    def fixture(self, own_job=False):
        raw = self.root / "projects/sample/raw"
        old = self.aged(raw / (self.log + ".jsonl.abcdefgh.tmp"), 660)
        shim = self.folder / "worker-barrier.py"
        library = SCRIPTS / "memory_lib/worker_runtime.py"
        shim.write_text("REAL_ENTRY = %r\nREAL_LIBRARY = __import__('pathlib').Path(%r)\nMARKER = %r\n" %
                        (str(ENTRY), str(library.resolve()), MARKER) + CHILD, encoding="utf-8")
        code = ("SCRIPTS = %r\nCHILD_PATH = %r\nOWN_JOB = %r\n" % (str(SCRIPTS), str(shim), own_job)) + PARENT
        code = code.replace("sys.path.insert(0, SCRIPTS)", "sys.dont_write_bytecode = True\nsys.path.insert(0, SCRIPTS)")
        env = dict(os.environ, CORTHEX_MEMORY_TEST_TOKEN=MARKER, PYTHONPATH=str(self.folder / "ignored"))
        parent = subprocess.Popen([sys.executable, "-I", "-c", code], cwd=self.folder, env=env,
                                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        finished = self.root / "fixture-finished.json"
        child_exit = contextlib.ExitStack()
        try:
            output, error = parent.communicate(timeout=15)
            self.assertEqual((parent.returncode, error), (0, b""))
            result = json.loads(output)
            self.assertTrue(result["started"])
            child_exit.enter_context(fixture_child_exit(self, result))
            self.assertFalse(finished.exists())
            self.assertTrue(old.exists())
            self.assertEqual([x["seq"] for x in self.rows()], [1, 2])
            # Actual parent exit is observed before real entry-point maintenance can start.
            (self.root / "fixture-go").touch()
            until = time.monotonic() + 15
            while not finished.exists() and time.monotonic() < until:
                time.sleep(.01)
            self.assertTrue(finished.exists(), "Real worker did not finish after parent exit")
            evidence = json.loads(finished.read_text(encoding="utf-8"))
            for key in ("stdin_eof", "isolated", "marker_received", "pythonpath_ignored", "quiet_exit", "own_library", "cwd_matches"):
                self.assertTrue(evidence[key], key)
            self.assertEqual(evidence["argv"], ["--reason", "start", "--project", "sample", "--expect-device", self.device])
            self.assertEqual([x["seq"] for x in self.rows()], [2])
            self.assertFalse(old.exists())
            self.assertEqual(self.failures(), [])
            if os.name != "nt":
                self.assertTrue(evidence["own_session"])
                if evidence["nice_before"] <= 9:
                    self.assertEqual(evidence["nice_after"], evidence["nice_before"] + 10)
                else:
                    self.assertGreaterEqual(evidence["nice_after"], evidence["nice_before"])
            if own_job:
                self.assertTrue(result["in_job"])
                self.assertEqual(result["events"][0], {"flags": worker_launch.WINDOWS_FLAGS, "winerror": 5})
                self.assertEqual(result["events"][1]["flags"], worker_launch.WINDOWS_FLAGS & ~worker_launch.CREATE_BREAKAWAY_FROM_JOB)
                self.assertEqual(len(result["events"]), 2)
            self.assertNotIn(MARKER, finished.read_text(encoding="utf-8"))
        finally:
            try:
                (self.root / "fixture-go").touch()
                if parent.poll() is None:
                    parent.kill()
                    parent.communicate(timeout=5)
            finally:
                try:
                    child_exit.close()
                finally:
                    parent.stdout.close()
                    parent.stderr.close()

    def test_tc056_real_worker_finishes_after_actual_fixture_parent_exits(self):
        self.fixture()

    def test_tc056_real_worker_survives_owned_windows_no_breakaway_job_parent(self):
        if os.name != "nt":
            self.skipTest("Windows job fixture")
        self.fixture(own_job=True)
