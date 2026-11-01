"""TC-338 direct launch fixtures; no real worker or session-hook evidence."""
import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from test_memory_store import SCRIPTS, StoreCase
from memory_lib import base, diagnostics, locks, worker_launch
from memory_lib import clock as memory_clock

MARKER = "made-up-worker-environment-marker"

CHILD = '''import json, os, sys, time
from pathlib import Path
root = Path.cwd()
deadline = time.monotonic() + 12
stdin_eof = sys.stdin.buffer.read() == b""
print("fixture-child-stdout", flush=True)
print("fixture-child-stderr", file=sys.stderr, flush=True)
while not (root / "fixture-go").exists():
    if time.monotonic() > deadline:
        raise SystemExit(20)
    time.sleep(0.01)
result = {"stdin_eof": stdin_eof, "isolated": sys.flags.isolated == 1,
          "marker_received": os.environ.get("CORTHEX_MEMORY_TEST_TOKEN") == "made-up-worker-environment-marker",
          "pythonpath_ignored": os.environ["PYTHONPATH"] not in sys.path,
          "cwd": str(root), "argv": sys.argv[1:], "pid": os.getpid()}
if os.name != "nt":
    result["own_session"] = os.getsid(0) == os.getpid() == os.getpgrp()
temporary = root / "fixture-child.tmp"
temporary.write_text(json.dumps(result), encoding="utf-8")
temporary.replace(root / "fixture-child.json")
'''

PARENT = '''import ctypes, json, os, subprocess, sys
from ctypes import wintypes
from pathlib import Path
sys.path.insert(0, SCRIPTS)
from memory_lib import diagnostics, store, worker_launch
from memory_lib import clock
job = None
if OWN_JOB:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    job = kernel.CreateJobObjectW(None, None)
    if not job or not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        raise ctypes.WinError(ctypes.get_last_error())
    # This new owned job has no breakaway permission and no kill-on-close limit.
    # No existing host job or its limits are queried or changed.
events = []
original = subprocess.Popen
def recorded(command, **options):
    event = {"flags": options.get("creationflags", 0)}
    events.append(event)
    try:
        child = original(command, **options)
    except OSError as error:
        event["winerror"] = getattr(error, "winerror", None)
        raise
    event["pid"] = child.pid
    return child
worker_launch.subprocess.Popen = recorded
worker_launch.WORKER = Path(CHILD_PATH)
memory = store.MemoryStore()
logger = diagnostics.Diagnostics(memory)
deadline = clock.now() + 5
device = logger.read_gate(deadline)["device"]
in_job = worker_launch._in_job() if OWN_JOB else None
started = worker_launch.launch(memory, "sample", "start", deadline, logger,
                               expected_device=device, hook="start", host="codex")
print(json.dumps({"started": started, "events": events, "in_job": in_job}), flush=True)
if job:
    kernel.CloseHandle(job)
os._exit(0 if started else 21)
'''


def denied(number=5):
    error = PermissionError(MARKER)
    error.winerror = number
    return error


class WorkerLaunchTest(StoreCase):
    def setUp(self):
        super().setUp()
        self.deadline = memory_clock.now() + 5
        self.logger = diagnostics.Diagnostics(self.memory)
        self.logger.read_gate(self.deadline)
        self.device = self.header["device"]

    def launch(self, **changes):
        options = dict(expected_device=self.device, hook="start", host="codex")
        options.update(changes)
        return worker_launch.launch(self.memory, "sample", "start", self.deadline,
                                    self.logger, **options)

    def failures(self):
        return [json.loads(line) for path in (self.root / "logs").glob("failures-*.jsonl")
                for line in path.read_text(encoding="utf-8").splitlines()]

    def test_tc338_posix_options_inherit_environment_without_argv_values(self):
        process = mock.Mock()
        with mock.patch.object(worker_launch, "_WINDOWS", False), \
                mock.patch.object(worker_launch.subprocess, "Popen", return_value=process) as popen, \
                mock.patch.dict(os.environ, {"CORTHEX_MEMORY_ANTHROPIC_API_KEY": MARKER}):
            self.assertTrue(self.launch())
        args, options = popen.call_args
        self.assertEqual(args[0], [sys.executable, "-I", str(worker_launch.WORKER),
                                  "--reason", "start", "--project", "sample",
                                  "--expect-device", self.device])
        self.assertNotIn(MARKER, repr(popen.call_args))
        self.assertEqual(options, dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL, cwd=str(self.root),
                                      close_fds=True, shell=False, start_new_session=True))
        process.wait.assert_not_called()
        process.communicate.assert_not_called()
        process.__enter__ = mock.Mock()
        process.__enter__.assert_not_called()
        self.assertEqual(self.failures(), [])

    def test_tc338_windows_initial_flags_do_not_query_a_successful_launch(self):
        with mock.patch.object(worker_launch, "_WINDOWS", True), \
                mock.patch.object(worker_launch, "_in_job") as query, \
                mock.patch.object(worker_launch.subprocess, "Popen") as popen:
            self.assertTrue(self.launch())
        query.assert_not_called()
        self.assertEqual(popen.call_args.kwargs["creationflags"], 0x01004208)
        self.assertNotIn("start_new_session", popen.call_args.kwargs)
        if os.name == "nt":
            for name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP",
                         "CREATE_BREAKAWAY_FROM_JOB", "BELOW_NORMAL_PRIORITY_CLASS"):
                self.assertEqual(getattr(worker_launch, name), getattr(subprocess, name))

    def test_tc338_conditional_retry_and_final_failure_matrix(self):
        cases = [(denied(), True, False, 2, 0),
                 (denied(), True, True, 2, 1),
                 (denied(), False, False, 1, 1),
                 (denied(13), True, False, 1, 1),
                 (OSError(MARKER), True, False, 1, 1)]
        for error, in_job, second_fails, calls, failures in cases:
            with self.subTest(winerror=getattr(error, "winerror", None), job=in_job,
                              second_fails=second_fails):
                effects = [error, OSError(MARKER) if second_fails else mock.Mock()]
                logger = mock.Mock()
                with mock.patch.object(worker_launch, "_WINDOWS", True), \
                        mock.patch.object(worker_launch, "_in_job", return_value=in_job) as query, \
                        mock.patch.object(worker_launch.subprocess, "Popen", side_effect=effects) as popen:
                    result = worker_launch.launch(self.memory, "sample", "start", self.deadline, logger)
                self.assertEqual(result, not failures)
                self.assertEqual(popen.call_count, calls)
                self.assertEqual(query.call_count, int(getattr(error, "winerror", None) == 5))
                self.assertEqual(logger.failure.call_count, failures)
                if calls == 2:
                    first, second = popen.call_args_list
                    expected = dict(first.kwargs)
                    expected["creationflags"] &= ~worker_launch.CREATE_BREAKAWAY_FROM_JOB
                    self.assertEqual(second.args, first.args)
                    self.assertEqual(second.kwargs, expected)
                if failures:
                    self.assertEqual(logger.failure.call_args.args,
                                     ("worker-start", "trigger", self.deadline))
                    self.assertNotIn(MARKER, repr(logger.failure.call_args))

    def test_tc338_query_requires_success_and_positive_result_with_null_job(self):
        for succeeded, present in ((0, 0), (0, 1), (1, 0), (1, 1)):
            def query(process, job, result):
                self.assertEqual(process, 123)
                self.assertIsNone(job)
                result._obj.value = present
                return succeeded
            kernel = SimpleNamespace(GetCurrentProcess=mock.Mock(return_value=123),
                                     IsProcessInJob=mock.Mock(side_effect=query))
            with mock.patch.object(ctypes, "WinDLL", create=True, return_value=kernel):
                self.assertEqual(worker_launch._in_job(), bool(succeeded and present))
        with mock.patch.object(ctypes, "WinDLL", create=True, side_effect=OSError(MARKER)):
            self.assertFalse(worker_launch._in_job())

    def test_tc338_query_failure_does_not_retry_or_leak_exception_text(self):
        logger = mock.Mock()
        with mock.patch.object(worker_launch, "_WINDOWS", True), \
                mock.patch.object(ctypes, "WinDLL", create=True, side_effect=OSError(MARKER)), \
                mock.patch.object(worker_launch.subprocess, "Popen", side_effect=denied()) as popen:
            self.assertFalse(worker_launch.launch(self.memory, "sample", "start", self.deadline, logger))
        self.assertEqual(popen.call_count, 1)
        self.assertEqual(logger.failure.call_count, 1)
        self.assertNotIn(MARKER, repr(logger.failure.call_args))

    def test_tc338_final_failure_keeps_original_and_expired_diagnostic_deadline(self):
        for expired in (False, True):
            with self.subTest(expired=expired):
                deadline = memory_clock.now() + (-1 if expired else 5)
                before = len(self.failures())
                with mock.patch.object(worker_launch.subprocess, "Popen", side_effect=OSError(MARKER)), \
                        mock.patch.object(self.logger, "failure", wraps=self.logger.failure) as failure:
                    self.assertFalse(worker_launch.launch(self.memory, "sample", "start", deadline,
                                                          self.logger, hook="start", host="codex"))
                self.assertEqual(failure.call_count, 1)
                self.assertEqual(failure.call_args.args, ("worker-start", "trigger", deadline))
                self.assertTrue(failure.call_args.kwargs["opportunistic"])
                rows = self.failures()
                self.assertEqual(len(rows), before + 1)
                self.assertEqual(rows[-1]["error"], "worker-start")
                self.assertEqual(rows[-1]["step"], "trigger")
                self.assertEqual(rows[-1]["project"], "sample")
                self.assertTrue(all(MARKER not in path.read_text(encoding="utf-8")
                                    for path in self.root.rglob("*") if path.is_file()))

    def test_tc338_fresh_curation_lease_skips_quietly_without_taking_or_touching_it(self):
        path = self.root / "projects/sample/curation.lock"
        base.private_directory(path.parent)
        with locks.Lock(path, "curation", self.device).held(self.deadline):
            before = self.snapshot()
            with mock.patch.object(worker_launch.subprocess, "Popen") as popen:
                self.assertFalse(self.launch())
            popen.assert_not_called()
            self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.failures(), [])

    def test_tc338_freshness_boundary_and_stale_lease_remain_unmodified(self):
        path = self.root / "projects/sample/curation.lock"
        base.private_directory(path.parent)
        path.write_bytes(b"incomplete fixture lease")
        now = time.time_ns() // 1000000000 * 1000000000
        for age in (-60, 599, 600, 601):
            stamp = now - age * 1000000000
            os.utime(str(path), ns=(stamp, stamp))
            before = self.snapshot()
            with mock.patch.object(worker_launch.time, "time_ns", return_value=now), \
                    mock.patch.object(worker_launch.subprocess, "Popen") as popen:
                self.assertEqual(self.launch(), age > 600)
            self.assertEqual(popen.call_count, int(age > 600))
            self.assertEqual(self.snapshot(), before)

    def test_tc338_absent_project_is_not_provisioned_and_device_argument_is_optional(self):
        before = self.snapshot()
        with mock.patch.object(worker_launch.subprocess, "Popen") as popen:
            self.assertTrue(self.launch(expected_device=None))
        self.assertNotIn("--expect-device", popen.call_args.args[0])
        self.assertEqual(self.snapshot(), before)

    def test_tc338_data_leases_prevent_launch_and_diagnostic_until_released(self):
        self.memory.held = [object()]
        logger = mock.Mock()
        with mock.patch.object(worker_launch.subprocess, "Popen", side_effect=OSError(MARKER)) as popen:
            self.assertFalse(worker_launch.launch(self.memory, "sample", "start", self.deadline, logger))
            popen.assert_not_called()
            logger.failure.assert_not_called()
            self.memory.held.clear()
            self.assertFalse(worker_launch.launch(self.memory, "sample", "start", self.deadline, logger))
            self.assertEqual(popen.call_count, 1)
            self.assertEqual(logger.failure.call_count, 1)

    def test_tc338_invalid_arguments_never_spawn_or_escape(self):
        for project, reason, device in (("../outside", "start", None),
                                        ("sample", MARKER, None), ("sample", "start", MARKER)):
            with mock.patch.object(worker_launch.subprocess, "Popen") as popen:
                before = self.snapshot()
                self.assertFalse(worker_launch.launch(self.memory, project, reason, self.deadline,
                                                      mock.Mock(), expected_device=device))
                popen.assert_not_called()
                self.assertEqual(self.snapshot(), before)

    def fixture(self, own_job=False):
        child = self.folder / "fixture-child.py"
        child.write_text(CHILD, encoding="utf-8")
        code = ("SCRIPTS = %r\nCHILD_PATH = %r\nOWN_JOB = %r\n" %
                (str(SCRIPTS), str(child), own_job)) + PARENT
        env = dict(os.environ, CORTHEX_MEMORY_TEST_TOKEN=MARKER, PYTHONPATH=str(self.folder / "ignored"))
        parent = subprocess.Popen([sys.executable, "-I", "-c", code], cwd=self.folder,
                                  env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            output, error = parent.communicate(timeout=10)
            self.assertEqual(parent.returncode, 0, error.decode("utf-8", "replace"))
            self.assertEqual(error, b"")
            result = json.loads(output)
            self.assertTrue(result["started"])
            self.assertIsNotNone(parent.returncode)
            # The child cannot finish its evidence until this test sees the parent exit.
            self.assertFalse((self.root / "fixture-child.json").exists())
            (self.root / "fixture-go").touch()
            until = time.monotonic() + 10
            path = self.root / "fixture-child.json"
            while not path.exists() and time.monotonic() < until:
                time.sleep(0.01)
            self.assertTrue(path.exists(), "Fixture child did not survive its parent")
            evidence = json.loads(path.read_text(encoding="utf-8"))
            for key in ("stdin_eof", "isolated", "marker_received", "pythonpath_ignored"):
                self.assertTrue(evidence[key], key)
            self.assertEqual(Path(evidence["cwd"]), self.root)
            self.assertEqual(evidence["argv"], ["--reason", "start", "--project", "sample",
                                                 "--expect-device", self.device])
            if os.name != "nt":
                self.assertTrue(evidence["own_session"])
            self.assertEqual(self.failures(), [])
            self.assertNotIn(MARKER, path.read_text(encoding="utf-8"))
            if own_job:
                self.assertTrue(result["in_job"])
                self.assertEqual(len(result["events"]), 2)
                self.assertEqual(result["events"][0], {"flags": worker_launch.WINDOWS_FLAGS, "winerror": 5})
                self.assertEqual(result["events"][1]["flags"],
                                 worker_launch.WINDOWS_FLAGS & ~worker_launch.CREATE_BREAKAWAY_FROM_JOB)
        finally:
            (self.root / "fixture-go").touch()
            if parent.poll() is None:
                parent.kill()
                parent.communicate(timeout=5)
            parent.stdout.close()
            parent.stderr.close()

    def test_tc338_synthetic_child_outlives_parent_with_null_streams_and_isolation(self):
        self.fixture()

    def test_tc338_windows_no_breakaway_job_uses_actual_conditional_retry(self):
        if os.name != "nt":
            self.skipTest("Windows job fixture")
        self.fixture(own_job=True)
