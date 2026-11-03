"""Observe asynchronous host hooks without rerunning or hiding failures."""

import importlib.util
import contextlib
import io
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from _common import ROOT


class HostCaptureTest(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("memory_host_fixture",ROOT/".github/hook-check/run.py")
        self.fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.fixture)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        folder = self.home/".corthex/corthex-memory"
        self.raw = folder/"projects/sample/raw/session.jsonl"
        self.timings = folder/"logs/hooks-2026-10-27.jsonl"
        self.raw.parent.mkdir(parents=True)
        self.timings.parent.mkdir(parents=True)
        self.append(self.raw,dict(kind="prompt",text=self.fixture.PROMPT,host="claude-code",session="fixture",turn=1))
        self.append(self.raw,dict(kind="answer",text=self.fixture.REPLY,host="claude-code",session="fixture",turn=1))
        for hook in ("start","prompt","end-of-turn"):
            self.append(self.timings,dict(hook=hook,outcome="ok"))

    def append(self,path,value):
        with path.open("a",encoding="utf-8") as output:
            output.write(json.dumps(value,ensure_ascii=False)+"\n")

    def test_waits_for_the_existing_end_hooks_final_timing(self):
        self.append(self.raw,dict(kind="end",host="claude-code",session="fixture"))
        self.assertTrue(self.fixture.capture(self.home)["end_ok"])
        def finish():
            time.sleep(0.1)
            self.append(self.timings,dict(hook="end",outcome="ok"))
        worker = threading.Thread(target=finish)
        worker.start()
        self.addCleanup(worker.join,2)
        value = self.fixture.wait_for_capture(self.home,timeout=2)
        self.assertTrue(value["timings_ok"])
        self.assertEqual(value["entries"],3)
        self.assertGreater(value["capture_wait_ms"],0)
        self.assertTrue(self.fixture.REPLY not in json.dumps(value))

    def test_terminal_end_failure_is_retained_without_waiting_or_rerunning(self):
        self.append(self.timings,dict(hook="end",outcome="lock-busy"))
        with mock.patch.object(self.fixture.time,"sleep",side_effect=AssertionError("terminal result")):
            value = self.fixture.wait_for_capture(self.home,timeout=2)
        self.assertFalse(value["end_ok"])
        self.assertFalse(value["timings_ok"])
        self.assertEqual(value["hook_outcomes"]["end"],["lock-busy"])

    def test_timeout_preserves_missing_end_and_changes_no_fixture_file(self):
        before = (self.raw.read_bytes(),self.timings.read_bytes())
        value = self.fixture.wait_for_capture(self.home,timeout=0)
        self.assertFalse(value["end_ok"])
        self.assertFalse(value["timings_ok"])
        self.assertTrue((self.raw.read_bytes(),self.timings.read_bytes())==before)

    def test_three_recording_hooks_do_not_prove_the_session_start_hook(self):
        self.append(self.raw,dict(kind="end",host="claude-code",session="fixture"))
        self.append(self.timings,dict(hook="end",outcome="ok"))
        rows = [json.loads(line) for line in self.timings.read_text(encoding="utf-8").splitlines()]
        self.timings.write_text("".join(json.dumps(row)+"\n" for row in rows if row["hook"] != "start"),encoding="utf-8")
        before = (self.raw.read_bytes(),self.timings.read_bytes())
        value = self.fixture.capture(self.home)
        self.assertFalse(value["timings_ok"])
        self.assertFalse(value["start_ok"])
        self.assertEqual(before,(self.raw.read_bytes(),self.timings.read_bytes()))
        self.append(self.timings,dict(hook="start",outcome="ok"))
        value = self.fixture.capture(self.home)
        self.assertFalse(value["start_ok"], "an ok timing cannot replace a missing raw start")
        self.assertTrue(value["timings_ok"])
        self.append(self.raw,dict(kind="start",host="claude-code",session="other-session"))
        self.assertFalse(self.fixture.capture(self.home)["start_ok"])
        self.append(self.raw,dict(kind="start",host="claude-code",session="fixture"))
        self.assertTrue(self.fixture.capture(self.home)["start_ok"])
        wrong = [dict(row, session="other-session") if row.get("kind")=="end" else row
                 for row in map(json.loads,self.raw.read_text(encoding="utf-8").splitlines())]
        self.raw.write_text("".join(json.dumps(row)+"\n" for row in wrong),encoding="utf-8")
        self.assertFalse(self.fixture.capture(self.home)["end_ok"])

    def run_fake_host(self, label="fixture", failed=None, inventory=None):
        good = {k: True for k in ("start_ok", "prompt_ok", "answer_ok", "end_ok", "same_turn",
                                 "korean_intact", "timings_ok", "failures_ok", "boundary_ok")}
        with tempfile.TemporaryDirectory() as output:
            value = {"requests": [{"path": "/v1/messages", "context": 1}], "capture": good,
                     "install": {"memory": {"exit": 7 if failed == "install" else 0}},
                     "run": {"exit": 7 if failed == "run" else 0}}
            with mock.patch.object(self.fixture.sys, "argv", ["run.py", label, output, "claude"]), \
                 mock.patch.object(self.fixture, "Mock"), mock.patch.object(self.fixture, "market", return_value=[]), \
                 mock.patch.object(self.fixture, "facts", return_value=inventory or {}), \
                 mock.patch.object(self.fixture, "shells", return_value={}), \
                 mock.patch.object(self.fixture, "claude", return_value=value), \
                 mock.patch.object(self.fixture, "codex", return_value={}), \
                 mock.patch.object(self.fixture, "summary", return_value="fixture"), \
                 mock.patch.dict(self.fixture.os.environ, {"GITHUB_STEP_SUMMARY": ""}), \
                 contextlib.redirect_stdout(io.StringIO()):
                return self.fixture.main()

    def test_actual_runner_rejects_a_failed_host_even_with_all_hook_markers(self):
        for failed in ("install", "run"):
            with self.subTest(failed=failed):
                self.assertEqual(self.run_fake_host(failed=failed), 1)

    def test_windows_variants_cannot_pass_with_the_original_shell_still_present(self):
        cases = [("no-git-bash", {"git_bash": "Git/bin/bash.exe"}),
                 ("no-git-bash", {"found": {"bash": "alternate/bash.exe"}}),
                 ("powershell-5.1-only", {"found": {"pwsh": "alternate/pwsh.exe"}}),
                 ("powershell-5.1-only", {"found": {"powershell": "PS.exe"}, "powershell_version": "7.6.0"})]
        for label, inventory in cases:
            with self.subTest(label=label, inventory=inventory):
                self.assertEqual(self.run_fake_host(label=label, inventory=inventory), 1)
        for label in ("no-git-bash", "powershell-5.1-only"):
            self.assertEqual(self.run_fake_host(label=label, inventory={"found": {"powershell": "PS.exe"},
                                                                     "powershell_version": "5.1.1"}), 0)

    def test_native_capture_rejects_the_wrong_host_session_or_timing_host(self):
        for wrong in ("host", "session", "timing", None):
            with self.subTest(wrong=wrong):
                host = "codex" if wrong == "host" else "claude-code"
                session = "different-session" if wrong == "session" else "native-session"
                rows = [dict(kind=kind, host=host, session=session, turn=1, **({"text": text} if text else {}))
                        for kind, text in (("start",None),("prompt",self.fixture.PROMPT),("answer",self.fixture.REPLY),("end",None))]
                self.raw.write_text("".join(json.dumps(row)+"\n" for row in rows),encoding="utf-8")
                self.timings.write_text("".join(json.dumps(dict(hook=hook,outcome="ok",host="codex" if wrong=="timing" else "claude-code"))+"\n"
                                               for hook in ("start","prompt","end-of-turn","end")),encoding="utf-8")
                done = {"exit":0,"stdout":'{"session_id":"native-session"}',"stderr":"","seconds":0}
                with mock.patch.object(self.fixture,"prepare",return_value=(self.home,self.home)), \
                     mock.patch.object(self.fixture.shutil,"which",return_value="fixture.exe"), \
                     mock.patch.object(self.fixture,"run",return_value=done), \
                     mock.patch.object(self.fixture,"install_steps",return_value={"memory":{"exit":0}}), \
                     mock.patch.object(self.fixture,"wait_for_capture",side_effect=lambda home,**kw:self.fixture.capture(home,**kw)):
                    value = self.fixture.claude("fixture",self.home,mock.Mock(port=1),self.home,[])["capture"]
                self.assertEqual(all(value[k] for k in ("start_ok","end_ok","prompt_ok","answer_ok","timings_ok")),wrong is None)

    def test_fresh_fixture_uses_the_real_on_contract_and_initializes_progress(self):
        home, demo = self.fixture.prepare(self.home / "fresh")
        bootstrap = json.loads((home.parent / "bootstrap.json").read_bytes())
        self.assertEqual(bootstrap["preview"]["outcome"], "confirm")
        self.assertEqual(bootstrap["result"]["outcome"], "done")
        self.assertFalse(bootstrap["real_user_consent"])
        root = home / ".corthex/corthex-memory"
        progress = json.loads((root / "projects/demo/curation.json").read_bytes())
        self.assertEqual(progress["logs"], {})
        self.assertEqual(progress["applies"], 0)
        self.assertTrue((root / "configuration.json").exists())
