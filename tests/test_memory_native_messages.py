"""Reject mismatched native delivery evidence; these fixtures are not host runs."""
import copy
import importlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
