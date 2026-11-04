"""Reject mismatched native delivery evidence; these fixtures are not host runs."""
import copy
import importlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from _common import ROOT


class NativeMessageProvenanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        previous = list(sys.path)
        try:
            sys.path.insert(0, str(ROOT / ".github/hook-check"))
            cls.prefix = importlib.import_module("native_prefix")
            cls.cross = importlib.import_module("cross_session")
        finally:
            sys.path[:] = previous

    def requests(self, call, target, success=True, is_error=False):
        return [{"messages":[{"role":"assistant","content":[
            {"type":"tool_use","id":call,"name":"SendMessage","input":{"to":target,"message":"marker only"}},
            {"type":"tool_result","tool_use_id":call,"is_error":is_error,
             "content":[{"type":"text","text":json.dumps({"success":success})}]}]}]}]

    def test_actual_agent_source_and_positive_send_are_both_required(self):
        inputs = [{"session_id":"parent", "prompt":'<agent-message from="child">marker only</agent-message>'}]
        requests = self.requests("toolu_child_2", "main")
        good = self.prefix.qualify_own_parent(inputs, requests, "parent", "child", "marker")
        self.assertTrue(good["verified"])
        for session, child in (("other-parent", "child"), ("parent", "other-child")):
            with self.subTest(session=session, child=child), self.assertRaises(AssertionError):
                self.prefix.qualify_own_parent(inputs, requests, session, child, "marker")
        for failed in ([], self.requests("toolu_child_2", "another-session"),
                       self.requests("toolu_child_2", "main", False), self.requests("toolu_child_2", "main", True, True)):
            with self.subTest(requests=failed), self.assertRaises(AssertionError):
                self.prefix.qualify_own_parent(inputs, failed, "parent", "child", "marker")

    def test_cross_delivery_must_match_both_owned_sessions_and_success(self):
        names = {"receiver":"fixture_receiver", "sender":"fixture_sender"}
        inputs = [{"session_id":"receiver-session", "prompt":'<cross-session-message from-name="fixture_sender">marker only</cross-session-message>'}]
        requests = self.requests("toolu_cross_2", names["receiver"])
        good = self.cross.qualify_delivery(inputs, requests, "receiver-session", names, "marker")
        self.assertTrue(good["native_send_succeeded"])
        wrong_sender = copy.deepcopy(inputs)
        wrong_sender[0]["prompt"] = wrong_sender[0]["prompt"].replace("fixture_sender", "unrelated_sender")
        for prompts, sent, session in (
            (inputs, requests, "unrelated-session"), (wrong_sender, requests, "receiver-session"),
            (inputs + inputs, requests, "receiver-session"),
            (inputs, self.requests("toolu_cross_2", "unrelated_receiver"), "receiver-session"),
            (inputs, self.requests("toolu_cross_2", names["receiver"], False), "receiver-session"),
        ):
            with self.subTest(prompts=prompts, sent=sent, session=session), self.assertRaises(AssertionError):
                self.cross.qualify_delivery(prompts, sent, session, names, "marker")

    def test_measured_package_keeps_product_children_and_declares_observers(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary).resolve()
            _, package, originals = self.prefix.measured_copy(output)
            info = json.loads((output / "native-instrumentation.json").read_text(encoding="utf-8"))
            self.assertEqual(info["candidate_sha256s"], originals)
            for name in ("scripts/hook.py", "scripts/worker.py"):
                self.assertEqual((package / name).read_bytes(), (ROOT / "plugins/corthex-memory" / name).read_bytes())
            self.assertNotEqual(info["modified_hook_config_sha256"], originals["hooks/hooks.json"])
            self.assertTrue(info["measurement_helper_sha256"])

    def test_installed_package_mismatch_cannot_qualify(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary).resolve()
            _, package, originals = self.prefix.measured_copy(output)
            config = output / "config"
            version = json.loads((package / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))["version"]
            cache = config / "plugins/cache/corthex/corthex-memory" / version
            shutil.copytree(package, cache)
            self.assertTrue(self.prefix.installed_copy(config, package, originals)["verified"])
            (cache / "scripts/worker.py").write_bytes(b"changed child\n")
            with self.assertRaisesRegex(AssertionError, "installed package"):
                self.prefix.installed_copy(config, package, originals)

    def end_fixture(self, output):
        home = output / "home"
        raw = home / ".corthex/corthex-memory/projects/demo/raw/session.jsonl"
        timing = home / ".corthex/corthex-memory/logs/hooks-fixture.jsonl"
        raw.parent.mkdir(parents=True); timing.parent.mkdir(parents=True)
        host = "claude-code"
        rows = [{"host":host,"session":"fixture","kind":"start","event":"start"},
                {"host":host,"session":"fixture","kind":"prompt","turn":1,"text":self.cross.runner.PROMPT},
                {"host":host,"session":"fixture","kind":"answer","turn":1,"text":self.cross.runner.REPLY}]
        logs = [{"host":host,"hook":hook,"outcome":"ok"} for hook in ("start","prompt","end-of-turn")]
        self.write_rows(raw, rows); self.write_rows(timing, logs)
        return home, raw, timing, rows, logs

    def write_rows(self, path, rows):
        pending = path.with_suffix(".pending")
        pending.write_bytes(b"".join((json.dumps(row,ensure_ascii=False)+"\n").encode("utf-8") for row in rows))
        deadline = time.monotonic() + 2
        while True:
            try:
                pending.replace(path); return
            except PermissionError as error:
                if os.name != "nt" or getattr(error,"winerror",None) not in (5,32,33) or time.monotonic() >= deadline:
                    raise
                time.sleep(.01)

    def test_delayed_end_and_its_timing_finish_before_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary).resolve()
            home, raw, timing, rows, logs = self.end_fixture(output)
            errors = []
            def finish():
                try:
                    time.sleep(.15)
                    self.write_rows(raw, rows + [{"host":"claude-code","session":"fixture","kind":"end"}])
                    time.sleep(.1)
                    self.write_rows(timing, logs + [{"host":"claude-code","hook":"end","outcome":"ok"}])
                except Exception as error:
                    errors.append(error)
            child = threading.Thread(target=finish); child.start()
            try:
                capture = self.cross.finish_store(home, output / "export", "fixture", timeout=3)
                self.assertTrue(capture["end_ok"])
                self.assertTrue(capture["timings_ok"])
                self.assertGreaterEqual(capture["capture_wait_ms"], 150)
                root = output / "export/store-evidence"
                self.assertEqual(len((root / "projects/demo/raw/session.jsonl").read_bytes().splitlines()),4)
                self.assertEqual(len((root / "logs/hooks-fixture.jsonl").read_bytes().splitlines()),4)
            finally:
                child.join(timeout=3)
                self.assertFalse(child.is_alive())
                self.assertEqual(errors,[])

    def test_missing_end_times_out_and_exports_unchanged_partial_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary).resolve()
            home, raw, timing, _, _ = self.end_fixture(output)
            original = (raw.read_bytes(),timing.read_bytes())
            capture = self.cross.finish_store(home, output / "export", "fixture", timeout=.05)
            self.assertFalse(capture["end_ok"])
            self.assertFalse(capture["timings_ok"])
            self.assertGreaterEqual(capture["capture_wait_ms"],40)
            self.assertLess(capture["capture_wait_ms"],1000)
            self.assertEqual((raw.read_bytes(),timing.read_bytes()),original)
            self.assertEqual((output / "export/store-evidence/projects/demo/raw/session.jsonl").read_bytes(),original[0])

    def test_capture_read_denial_waits_without_rerunning_a_hook(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary).resolve()
            home, _, _, _, _ = self.end_fixture(output)
            snapshot = self.cross.runner.capture(home, host="claude-code", session="fixture")
            snapshot["hook_outcomes"]["end"] = ["ok"]
            with patch.object(self.cross.runner, "capture", side_effect=[PermissionError("fixture"), snapshot]) as read, \
                    patch.object(self.cross.runner, "run", side_effect=AssertionError("a hook must not run again")):
                result = self.cross.runner.wait_for_capture(home, timeout=.2, host="claude-code", session="fixture")
            self.assertEqual(read.call_count, 2)
            self.assertGreaterEqual(result["capture_wait_ms"], 40)

    def test_permanent_capture_read_denial_expires_and_invalid_json_is_not_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            with patch.object(self.cross.runner, "capture", side_effect=PermissionError("fixture")):
                started = time.monotonic()
                with self.assertRaises(PermissionError):
                    self.cross.runner.wait_for_capture(home, timeout=.05)
                self.assertGreaterEqual(time.monotonic() - started, .04)
                self.assertLess(time.monotonic() - started, 1)
            with patch.object(self.cross.runner, "capture", side_effect=json.JSONDecodeError("fixture", "", 0)) as read:
                with self.assertRaises(json.JSONDecodeError):
                    self.cross.runner.wait_for_capture(home, timeout=.2)
                self.assertEqual(read.call_count, 1)


if __name__ == "__main__":
    unittest.main()
