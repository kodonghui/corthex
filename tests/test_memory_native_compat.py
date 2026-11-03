"""Native QA must detect diagnostic-only writes and await delayed end records."""
import importlib
import json
import os
from pathlib import Path
import signal
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
