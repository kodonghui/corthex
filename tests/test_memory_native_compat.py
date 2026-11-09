"""Native QA must detect diagnostic-only writes and await delayed end records."""
import errno
import hashlib
import importlib
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from _common import ROOT


class NativeCompatibilityGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        previous = list(sys.path)
        try:
            sys.path.insert(0, str(ROOT / ".github/hook-check"))
            cls.trust = importlib.import_module("trust_update")
            cls.lifecycle = importlib.import_module("lifecycle")
        finally:
            sys.path[:] = previous

    def diagnostic_change(self, name):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve()
            self.assertEqual(home.parent, Path(tempfile.gettempdir()).resolve())
            root = home / ".corthex/corthex-memory"; root.mkdir(parents=True)
            (root / "store.json").write_bytes(b"{}\n")
            (root / "configuration.json").write_bytes(b"{}\n")
            before = self.trust.before_retrust_files(home)
            raw_before = self.trust.runner.native_evidence.persistent_files(home)
            (root / "logs").mkdir()
            (root / "logs" / (name + "-2026-11-04.jsonl")).write_bytes(b"{}\n")
            self.assertEqual(raw_before, self.trust.runner.native_evidence.persistent_files(home))
            self.assertNotEqual(before, self.trust.before_retrust_files(home),
                                "An untrusted hook's diagnostic write must fail even without raw recording")

    def test_pre_retrust_detects_hook_timing_without_raw_change(self):
        self.diagnostic_change("hooks")

    def test_pre_retrust_detects_failure_without_raw_change(self):
        self.diagnostic_change("failures")

    def test_native_review_panel_requires_its_advertised_trust_action(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.toml"
            for count in (1, 4):
                path.write_text("", encoding="utf-8")
                class ReviewPanel:
                    data = bytearray(("Hooks need review\n%d hooks are new or changed\nTrust all and continue\n" % count).encode())
                    panel = False
                    def wait(self, predicate):
                        if not predicate():
                            raise AssertionError("Native terminal did not reach its expected state")
                    def key(self, key, **options):
                        if key == b"\r":
                            self.panel = True
                            self.data.extend(b"Hooks\nLifecycle hooks from config \x1b[0mand enabled plugins.\nt \x1b[0mtrust all\n")
                        elif key == b"t" and self.panel:
                            path.write_text("\n".join('trusted_hash = "fixture%d"' % i for i in range(count)), encoding="utf-8")
                with self.subTest(hooks=count):
                    self.trust.trust_hooks(ReviewPanel(), path, count)
                    self.assertEqual(path.read_text(encoding="utf-8").count("trusted_hash"), count)

    def test_lifecycle_quiet_precondition_waits_for_a_maintenance_lease(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve()
            lock = home / ".corthex/corthex-memory/projects/demo/curation.lock"
            lock.parent.mkdir(parents=True)
            lock.write_bytes(b"fixture lease\n")
            def release():
                time.sleep(.15)
                lock.unlink()
            child = threading.Thread(target=release); child.start()
            started = time.monotonic()
            try:
                result = self.lifecycle.wait_quiet_store(home, quiet=.05)
            finally:
                child.join(timeout=2)
            self.assertGreaterEqual(time.monotonic() - started, .2)
            self.assertEqual(result["observed_leases"], [["projects/demo/curation.lock"]])
            self.assertFalse(result["worker_completion_claimed"])

    def test_busy_lifecycle_precondition_fails_without_changing_the_store(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve()
            lock = home / ".corthex/corthex-memory/projects/demo/raw/native.lock"
            lock.parent.mkdir(parents=True)
            lock.write_bytes(b"fixture lease\n")
            with self.assertRaises(AssertionError):
                self.lifecycle.wait_quiet_store(home, timeout=.05, quiet=.02)
            self.assertEqual(lock.read_bytes(), b"fixture lease\n")

    def test_failed_native_runs_retain_raw_and_diagnostics_without_account_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            home, output = base / "home", base / "output"
            for name in (".corthex/corthex-memory/projects/demo/raw/native.jsonl",
                         ".corthex/corthex-memory/logs/failures-fixture.jsonl", ".codex/auth.json"):
                path = home / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"synthetic fixture\n")
            self.lifecycle.retain_store_evidence(home, output)
            self.assertEqual(sorted(p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()),
                             ["store-evidence/logs/failures-fixture.jsonl", "store-evidence/projects/demo/raw/native.jsonl"])

    def test_lifecycle_copy_preserves_original_children_and_declares_its_two_observers(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary).resolve()
            copy = self.lifecycle.paced_package(ROOT, output) / "plugins/corthex-memory"
            report = json.loads((output / "lifecycle-instrumentation.json").read_bytes())
            self.assertTrue(report["original_children_unchanged"])
            self.assertEqual(len(report["candidate_sha256s"]), 123)
            for name in ("format2", "fence_plan", "c2_store", "revision_io", "item_types", "item_plan", "item_io", "state_types", "history_io", "history_recovery", "state_plan", "state_io", "history_retention", "migration_plan", "migration_inventory", "maintenance_owner", "model_access", "model_usage", "model_stream", "model_wire", "model_transport", "maintenance_identity", "migration_intent", "model_prompts", "model_request", "model_client", "maintenance_journal", "migration_headers", "migration_header_resume", "migration_initialize", "migration_initialize_resume", "migration_finalize",
                         "migration_final_headers", "migration_finalize_resume", "migration_driver", "migration_command",
                         "index_io", "model_count", "model_embed", "curation_triggers", "curation_rebuild", "request_budget", "run_log",
                         "curation_worker", "consolidation_worker", "state_rewrite", "run_listing",
                         "forget_plan", "forget_command", "raw_fill", "forget_effects", "undo_plan",
                         "undo_command", "undo_effects", "index_worker", "injection_log", "start_summary", "recall",
                         "prompt_recall", "conflicts_command", "item_commands", "search_command",
                         "pin_command", "resume_command", "c2_status"):
                module = "skills/corthex-memory/scripts/memory_lib/" + name + ".py"
                self.assertEqual(report["candidate_sha256s"][module],
                                 hashlib.sha256((ROOT/"plugins/corthex-memory"/module).read_bytes()).hexdigest())
            for name in ("scripts/hook.py", "scripts/worker.py"):
                self.assertEqual((copy/name).read_bytes(), (ROOT/"plugins/corthex-memory"/name).read_bytes())
            hooks = json.loads((copy/"hooks/hooks.json").read_bytes())["hooks"]
            for event in ("SessionStart", "UserPromptSubmit"):
                self.assertIn("lifecycle_prompt.py", hooks[event][0]["hooks"][0]["command"])
            for event in ("Stop", "SessionEnd"):
                self.assertNotIn("lifecycle_prompt.py", hooks[event][0]["hooks"][0]["command"])

    def test_native_prompt_waits_for_observed_start_and_forwards_child_bytes_environment_and_exit(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve()
            (home/".corthex/corthex-memory").mkdir(parents=True)
            script = home/"lifecycle_prompt.py"
            shutil.copyfile(ROOT/".github/hook-check/lifecycle_prompt.py", script)
            (home/"hook.py").write_text("import os,sys,time\nassert os.environ['PACE_SENTINEL']=='preserved'\n"
                "data=sys.stdin.buffer.read()\nif sys.argv[1]=='start': time.sleep(.15)\n"
                "sys.stdout.buffer.write(data)\nsys.stderr.buffer.write(b'original-child-stderr')\n"
                "raise SystemExit(0 if sys.argv[1]=='start' else 7)\n", encoding="utf-8")
            output = home/"prompt-gates"
            env = dict(self.lifecycle.runner.base_env(home), HOOKCHECK_LIFECYCLE_GATES=str(output), PACE_SENTINEL="preserved")
            self.lifecycle.arm_start(env, "startup")
            incoming = json.dumps({"session_id":"native-fixture","source":"startup","prompt":"한국어"}, ensure_ascii=False).encode("utf-8")
            start = subprocess.Popen([sys.executable,"-B","-X","utf8",str(script),"start"], env=env,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            start.stdin.write(incoming); start.stdin.close(); start.stdin=None
            try:
                prompt = subprocess.run([sys.executable,"-B","-X","utf8",str(script),"prompt"],
                                        env=env, input=incoming, capture_output=True, timeout=10)
                stdout, stderr = start.communicate(timeout=10)
                self.assertEqual((stdout,stderr,start.returncode),(incoming,b"original-child-stderr",0))
                self.assertEqual((prompt.stdout,prompt.stderr,prompt.returncode),(incoming,b"original-child-stderr",7))
                receipts = [json.loads(p.read_bytes()) for p in output.glob("*.json") if p.name!="generation.json"]
                passed = next(v for v in receipts if v["hook"]=="prompt")
                self.assertGreaterEqual(passed["child_started_ns"], passed["start_completion"]["child_ended_ns"])
                self.assertTrue(passed["start_completion"]["completed"])
                with self.assertRaises(AssertionError):
                    self.lifecycle.pacing_evidence(home)  # The original prompt child exited 7.
                receipt_path = next(p for p in output.glob("*.json")
                                    if json.loads(p.read_bytes()).get("hook")=="prompt")
                passed["exit"] = 0
                passed["child_started_ns"] = passed["start_completion"]["child_ended_ns"] - 1
                receipt_path.write_text(json.dumps(passed),encoding="utf-8")
                with self.assertRaises(AssertionError):
                    self.lifecycle.pacing_evidence(home)
            finally:
                if start.poll() is None: start.kill(); start.communicate()

    def test_the_start_file_is_replaced_again_while_windows_refuses_the_replace(self):
        # A prompt child that reads the start file makes Windows refuse its replace for a moment (Access is denied).
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            replace, refused = Path.replace, []

            def busy(source, target):
                if len(refused) < 3:
                    refused.append(Path(target).name)
                    raise PermissionError(13, "Access is denied")
                return replace(source, target)
            with patch.object(Path, "replace", busy):
                self.lifecycle.write_start(folder / "start.json", {"session": "native-fixture"})
            self.assertEqual(refused, ["start.json"] * 3)
            self.assertEqual(json.loads((folder / "start.json").read_text(encoding="utf-8")), {"session": "native-fixture"})
            self.assertEqual([path.name for path in folder.iterdir()], ["start.json"])
            # A refusal that outlasts the wait still fails the check, and leaves no temporary file behind.
            with patch.object(Path, "replace", side_effect=PermissionError(13, "Access is denied")):
                with self.assertRaises(PermissionError):
                    self.lifecycle.write_start(folder / "start.json", {"session": "other"}, seconds=.1)
            self.assertEqual(json.loads((folder / "start.json").read_text(encoding="utf-8")), {"session": "native-fixture"})
            self.assertEqual([path.name for path in folder.iterdir()], ["start.json"])
            # A removal that fails too leaves the replace's error to be raised.
            with patch.object(Path, "replace", side_effect=PermissionError(13, "Access is denied")), \
                    patch.object(Path, "unlink", side_effect=PermissionError(32, "The file is in use")):
                with self.assertRaises(PermissionError) as raised:
                    self.lifecycle.write_start(folder / "start.json", {"session": "other"}, seconds=.1)
            self.assertEqual(raised.exception.errno, 13)
            left = list(folder.glob("start.*.tmp"))
            self.assertEqual(len(left), 1)
            left[0].unlink()
            # A write that fails part of the way leaves no temporary file either.
            write = Path.write_text

            def full(target, text, **options):
                write(target, text[:5], **options)
                raise OSError(28, "No space left on device")
            with patch.object(Path, "write_text", full):
                with self.assertRaises(OSError):
                    self.lifecycle.write_start(folder / "start.json", {"session": "other"})
            self.assertEqual([path.name for path in folder.iterdir()], ["start.json"])

    def test_resume_rejects_a_previous_completed_start_for_the_same_native_session(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary).resolve()/"prompt-gates"
            output.mkdir()
            event = {"session_id":"same-native-session"}
            old = {"id":"previous","source":"startup","armed_ns":1}
            new = {"id":"current","source":"resume","armed_ns":2}
            helper = sys.modules["lifecycle_prompt"]
            helper.write_start(helper.start_path(output,event),
                               {"completed":True,"exit":0,"generation":old,"event_source":"startup"})
            with self.assertRaises(AssertionError):
                helper.wait_start_completed(output,event,new,timeout=.05)
            helper.write_start(helper.start_path(output,event),
                               {"completed":True,"exit":0,"generation":new,"event_source":"resume"})
            self.assertEqual(helper.wait_start_completed(output,event,new)["generation"],new)

    def complete_capture_file(self, home):
        path = home / ".corthex/corthex-memory/projects/demo/raw/native.jsonl"
        path.parent.mkdir(parents=True)
        rows = [{"session":"native-fixture", "kind":"start", "event":"start"},
                {"session":"native-fixture", "kind":"prompt", "turn":1, "text":self.lifecycle.runner.PROMPT},
                {"session":"native-fixture", "kind":"answer", "turn":1, "text":self.lifecycle.runner.REPLY},
                {"session":"native-fixture", "kind":"end"}]
        path.write_bytes(b"".join((json.dumps(v) + "\n").encode("utf-8") for v in rows))
        return path, rows

    def test_capture_recovers_from_transient_read_and_partial_json_failures(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve()
            path, rows = self.complete_capture_file(home)
            original = Path.read_bytes
            pending = [PermissionError(13, "fixture sharing"), FileNotFoundError("fixture replacement"),
                       b'{"session":', b'{"text":"\xea']
            def read(candidate):
                if candidate == path and pending:
                    value = pending.pop(0)
                    if isinstance(value, bytes):
                        return value
                    raise value
                return original(candidate)
            with patch.object(Path, "read_bytes", read):
                result = self.lifecycle.wait_capture(home, {}, "startup", timeout=1)
            self.assertTrue(result["verified"])
            self.assertEqual(result["entries"], rows)

    def test_unreadable_capture_keeps_its_original_deadline_and_never_verifies(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve()
            self.complete_capture_file(home)
            with patch.object(Path, "read_bytes", side_effect=PermissionError(13, "fixture sharing")), \
                 patch.object(self.lifecycle.time, "monotonic", side_effect=[0, .02, .04, .06]), \
                 patch.object(self.lifecycle.time, "sleep"):
                with self.assertRaises(PermissionError):
                    self.lifecycle.wait_capture(home, {}, "startup", timeout=.05)

    @unittest.skipUnless(os.name == "nt", "Windows read-sharing fixture")
    def test_capture_waits_for_an_actual_windows_read_sharing_handle(self):
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve()
            path, rows = self.complete_capture_file(home)
            handle = kernel.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)
            if handle in (None, ctypes.c_void_p(-1).value):
                raise ctypes.WinError(ctypes.get_last_error())
            owned = {"handle":handle, "timer":None, "closed":False}
            def release():
                current, owned["handle"] = owned["handle"], None
                if current is not None:
                    owned["closed"] = bool(kernel.CloseHandle(current))
            original = Path.read_bytes
            def read(candidate):
                try:
                    return original(candidate)
                except PermissionError:
                    if candidate == path and owned["timer"] is None:
                        owned["timer"] = threading.Timer(.05, release)
                        owned["timer"].start()
                    raise
            try:
                with patch.object(Path, "read_bytes", read):
                    result = self.lifecycle.wait_capture(home, {}, "startup", timeout=2)
                self.assertTrue(result["verified"])
                self.assertEqual(result["entries"], rows)
            finally:
                if owned["timer"] is not None:
                    owned["timer"].join(timeout=2)
                    self.assertFalse(owned["timer"].is_alive())
                release()
                self.assertTrue(owned["closed"])

    def test_waits_for_actual_delayed_end_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve()
            self.assertEqual(home.parent, Path(tempfile.gettempdir()).resolve())
            path = home / ".corthex/corthex-memory/projects/demo/raw/native.jsonl"
            path.parent.mkdir(parents=True)
            rows = [{"session":"native-fixture", "kind":"start", "event":"start"},
                    {"session":"native-fixture", "kind":"prompt", "turn":1, "text":self.lifecycle.runner.PROMPT},
                    {"session":"native-fixture", "kind":"answer", "turn":1, "text":self.lifecycle.runner.REPLY}]
            def encode(values):
                return b"".join((json.dumps(v, ensure_ascii=False) + "\n").encode("utf-8") for v in values)
            path.write_bytes(encode(rows))
            def end():
                time.sleep(.15)
                pending = path.with_suffix(".pending")
                pending.write_bytes(encode(rows + [{"session":"native-fixture", "kind":"end"}]))
                deadline = time.monotonic() + 2
                while True:
                    try:
                        pending.replace(path)
                        break
                    except PermissionError as error:
                        if os.name != "nt" or getattr(error, "winerror", None) not in (5, 32, 33) or time.monotonic() >= deadline:
                            raise
                        time.sleep(.01)
            child = threading.Thread(target=end); child.start()
            try:
                result = self.lifecycle.wait_capture(home, {}, "startup")
                self.assertTrue(result["verified"])
                self.assertEqual(result["entries"][-1]["kind"], "end")
            finally:
                child.join(timeout=2)
                self.assertFalse(child.is_alive())

    def test_missing_end_or_a_boundary_with_text_never_qualifies(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve()
            self.assertEqual(home.parent, Path(tempfile.gettempdir()).resolve())
            path = home / ".corthex/corthex-memory/projects/demo/raw/native.jsonl"
            path.parent.mkdir(parents=True)
            rows = [{"session":"native-fixture","kind":"start","event":"start"},
                    {"session":"native-fixture","kind":"prompt","turn":1,"text":self.lifecycle.runner.PROMPT},
                    {"session":"native-fixture","kind":"answer","turn":1,"text":self.lifecycle.runner.REPLY}]
            for suffix in ([], [{"session":"native-fixture","kind":"end","text":"invalid boundary body"}]):
                with self.subTest(end=suffix):
                    path.write_bytes(b"".join((json.dumps(v, ensure_ascii=False) + "\n").encode("utf-8") for v in rows + suffix))
                    with self.assertRaises(AssertionError):
                        self.lifecycle.wait_capture(home, {}, "startup", timeout=.05)

    @unittest.skipIf(os.name == "nt", "Unix PTY cleanup; Windows native terminal cases are operator-run")
    def test_terminal_initialization_failure_reaps_its_actual_child_and_closes_fd(self):
        import fcntl
        import pty
        owned, fork = [], pty.fork
        def observed_fork():
            value = fork()
            if value[0]: owned.append(value)
            return value
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve()
            self.assertEqual(home.parent, Path(tempfile.gettempdir()).resolve())
            try:
                with patch.object(pty, "fork", observed_fork), patch.object(fcntl, "ioctl", side_effect=OSError("fixture ioctl failure")):
                    with self.assertRaises(OSError):
                        self.lifecycle.Terminal([sys.executable,"-c","import time;time.sleep(30)"],
                                                self.lifecycle.runner.base_env(home), home, home / "terminal.bin")
                self.assertEqual(len(owned), 1)
                pid, fd = owned[0]
                with self.assertRaises(ChildProcessError): os.waitpid(pid, os.WNOHANG)
                with self.assertRaises(OSError): os.fstat(fd)
            finally:
                for pid, fd in owned:
                    try:
                        if os.waitpid(pid, os.WNOHANG)[0] == 0:
                            os.killpg(pid, signal.SIGKILL); os.waitpid(pid, 0)
                    except ChildProcessError: pass
                    try: os.close(fd)
                    except OSError: pass

    @unittest.skipIf(os.name == "nt", "Unix PTY cleanup; Windows native terminal cases are operator-run")
    def test_terminal_close_reaps_its_child_when_macos_refuses_the_group_signal(self):
        # macOS answers EPERM to killpg once every member of the group has exited
        # but is not yet reaped. The refusal must not skip reaping the CLI.
        # Ctrl-C is held back: until exec, the forked child still runs this test's
        # code, and a SIGINT there would unwind it through these cleanups.
        refusal = PermissionError(errno.EPERM, "fixture group signal refusal")
        for script in ("pass", "import time;time.sleep(30)"):
            with self.subTest(script=script), tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary).resolve()
                terminal = self.lifecycle.Terminal([sys.executable, "-c", script],
                                                   self.lifecycle.runner.base_env(home), home, home / "terminal.bin")
                try:
                    with patch.object(terminal, "pump"), \
                            patch.object(terminal, "wait", side_effect=AssertionError("fixture graceful timeout")), \
                            patch.object(os, "write") as keys, \
                            patch.object(os, "killpg", side_effect=refusal) as group, \
                            patch.object(os, "kill", wraps=os.kill) as single:
                        terminal.close()
                    keys.assert_any_call(terminal.fd, b"\x03")
                    group.assert_called_once_with(terminal.pid, signal.SIGKILL)
                    single.assert_called_once_with(terminal.pid, signal.SIGKILL)
                    self.assertIsNotNone(terminal.status)
                    with self.assertRaises(ChildProcessError): os.waitpid(terminal.pid, os.WNOHANG)
                    with self.assertRaises(OSError): os.fstat(terminal.fd)
                finally:
                    try:
                        if os.waitpid(terminal.pid, os.WNOHANG)[0] == 0:
                            os.kill(terminal.pid, signal.SIGKILL); os.waitpid(terminal.pid, 0)
                    except ChildProcessError: pass
