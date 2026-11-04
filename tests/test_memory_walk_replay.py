"""TASK-057 qualification guards; these are not simulated native E2E proof."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from _common import ROOT

FOLDER = ROOT / ".github/hook-check"
sys.path.insert(0, str(FOLDER))
spec = importlib.util.spec_from_file_location("walk_replay_guard", FOLDER / "walk_replay.py")
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)


class WalkReplayGuardTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.walk = replay.Replay.__new__(replay.Replay)
        self.walk.host, self.walk.lang = "codex", "en"
        self.walk.base, self.walk.home = root / "output", root / "home"
        self.walk.project = root / "project"
        self.walk.project.mkdir()
        self.walk.exe = "unused-native-cli"
        self.walk.env = {"HOOKCHECK_LIFECYCLE_GATES": str(root / "gates"),
                         "MOCK_KEY": "synthetic-replay-guard"}
        self.walk.report = {"turns": []}
        memory = self.walk.home / ".corthex/corthex-memory"
        self.raw = memory / "projects/demo/raw/old.jsonl"
        self.raw.parent.mkdir(parents=True)
        self.raw.write_bytes(b'{"session":"earlier","kind":"prompt","text":"synthetic earlier entry"}\n')
        self.log = memory / "logs/hooks.jsonl"
        self.log.parent.mkdir()
        self.log.write_bytes(b'{"hook":"prompt","outcome":"ok","ms":1}\n')

    def invoke(self, events, export_error=False):
        def native(*args, **kwargs):
            output = self.walk.base / "observations"
            output.mkdir(parents=True)
            for index, (hook, session) in enumerate(events):
                value = {"hook": hook, "input": {"session_id": session},
                         "exit": 0, "stderr": "", "started_ns": index,
                         "stdout": json.dumps({"hookSpecificOutput": {"additionalContext": "CORTHEX session context"}})}
                (output / (str(index) + ".json")).write_text(json.dumps(value), encoding="utf-8")
            return {"exit": 0, "stdout": '{"type":"thread.started","thread_id":"current"}\n',
                    "stderr": self.walk.env["MOCK_KEY"]}
        with mock.patch.object(replay.runner, "run", side_effect=native) as call:
            if export_error:
                with mock.patch.object(replay, "retain_store_evidence", side_effect=PermissionError()):
                    self.walk.turn("off", [])
            else:
                self.walk.turn("off", [])
            self.assertEqual(call.call_count, 1)

    def assert_retained_failure(self):
        result = json.loads((self.walk.base / "off.json").read_bytes())
        self.assertFalse(result["verified"])
        self.assertEqual(result["native_run"]["stderr"], "[mock-key]")
        self.assertIn("prompt", result)
        copied = self.walk.base / "turns/off/store-evidence"
        self.assertEqual((copied / "projects/demo/raw/old.jsonl").read_bytes(), self.raw.read_bytes())
        self.assertEqual((copied / "logs/hooks.jsonl").read_bytes(), self.log.read_bytes())
        self.assertEqual(len(self.walk.report["turns"]), 1)
        return result

    def test_tc110_other_session_cannot_supply_missing_hooks_to_an_empty_raw_branch(self):
        with self.assertRaisesRegex(AssertionError, "Unrelated native session"):
            self.invoke([("start", "other"), ("prompt", "other"),
                         ("end-of-turn", "other"), ("end", "current")])
        self.assert_retained_failure()

    def test_tc110_duplicate_hook_cannot_pass_by_set_membership(self):
        with self.assertRaises(AssertionError):
            self.invoke([(hook, "current") for hook in ("start", "prompt", "end-of-turn", "end-of-turn", "end")])
        self.assert_retained_failure()

    def test_tc110_exact_current_session_hooks_can_qualify_an_empty_raw_branch(self):
        self.invoke([(hook, "current") for hook in ("start", "prompt", "end-of-turn", "end")])
        result = json.loads((self.walk.base / "off.json").read_bytes())
        self.assertTrue(result["verified"])
        self.assertEqual(result["raw"], [])

    def test_tc110_export_failure_preserves_the_original_qualification_error(self):
        with self.assertRaisesRegex(AssertionError, "Unrelated native session"):
            self.invoke([("start", "other"), ("prompt", "other"),
                         ("end-of-turn", "other"), ("end", "current")], export_error=True)
        result = json.loads((self.walk.base / "off.json").read_bytes())
        self.assertEqual(result["export_error"], "PermissionError")
        self.assertFalse(result["verified"])

    def test_tc110_missing_safe_export_cannot_be_marked_verified(self):
        with self.assertRaisesRegex(AssertionError, "Could not retain safe memory evidence"):
            self.invoke([(hook, "current") for hook in ("start", "prompt", "end-of-turn", "end")], export_error=True)
        result = json.loads((self.walk.base / "off.json").read_bytes())
        self.assertFalse(result["verified"])


if __name__ == "__main__":
    unittest.main()
