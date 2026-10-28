"""Observe asynchronous host hooks without rerunning or hiding failures."""

import importlib.util
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
        self.append(self.raw,dict(kind="prompt",text="hello",host="claude-code",session="fixture",turn=1))
        self.append(self.raw,dict(kind="answer",text=self.fixture.REPLY,host="claude-code",session="fixture",turn=1))
        for hook in ("prompt","end-of-turn"):
            self.append(self.timings,dict(hook=hook,outcome="ok"))

    def append(self,path,value):
        with path.open("a",encoding="utf-8") as output:
            output.write(json.dumps(value,ensure_ascii=False)+"\n")

    def test_waits_for_the_existing_end_hooks_final_timing(self):
        self.append(self.raw,dict(kind="end"))
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
