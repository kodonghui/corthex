"""Check isolation and evidence guards without treating fixtures as host runs."""
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from _common import ROOT


class NativeEvidenceTest(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("native_evidence_test", ROOT / ".github/hook-check/native_evidence.py")
        self.evidence = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.evidence)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_every_http_method_invalidates_the_no_egress_verdict(self):
        spec = importlib.util.spec_from_file_location("proxy_test", ROOT / ".github/hook-check/network_proxy.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for method in ("HEAD", "PUT", "PATCH", "DELETE", "OPTIONS", "CUSTOM"):
            with self.subTest(method=method):
                proxy = module.NetworkProxy()
                self.addCleanup(proxy.finish)
                connection = http.client.HTTPConnection(*proxy.server.server_address, timeout=2)
                connection.request(method, "http://hookcheck.invalid/blocked")
                connection.getresponse().read()
                connection.close()
                result = proxy.finish()
                self.assertTrue(result["positive_control"])
                self.assertFalse(result["verified"], method + " was received but silently ignored")
                self.assertEqual(result["observed_requests"], [{"method": method, "target": "http://hookcheck.invalid/blocked"}])

    def test_native_input_session_drift_names_the_wrong_event(self):
        folder = self.root / "inputs"
        folder.mkdir()
        for event in ("SessionStart", "UserPromptSubmit", "Stop", "SessionEnd"):
            (folder / (event+".json")).write_text(json.dumps({"hook_event_name":event,"session_id":"native-session"}),encoding="utf-8")
        self.assertTrue(self.evidence.input_identity(self.root,"native-session")["verified"])
        (folder / "SessionEnd.json").write_text(json.dumps({"hook_event_name":"SessionEnd","session_id":"other-session"}),encoding="utf-8")
        result = self.evidence.input_identity(self.root,"native-session")
        self.assertFalse(result["verified"])
        self.assertEqual(result["changed_fields"],{"SessionEnd":["session_id:value"]})

    def test_instrumentation_preserves_the_original_entry_and_library_bytes(self):
        original = ROOT / "plugins/corthex-memory"
        old = (original / "hooks/hooks.json").read_bytes()
        target, pins = self.evidence.package_copy(ROOT, self.root)
        copied = target / "plugins/corthex-memory"
        self.assertEqual((original / "hooks/hooks.json").read_bytes(), old)
        self.assertEqual((copied / "scripts/worker_actual.py").read_bytes(), (original / "scripts/worker.py").read_bytes())
        self.assertTrue(pins["original_entry_preserved"])
        for path in (original / "skills/corthex-memory/scripts/memory_lib").glob("*.py"):
            self.assertEqual(path.read_bytes(), (copied / path.relative_to(original)).read_bytes())

    def test_successful_uninstall_status_cannot_hide_a_deleted_store(self):
        home = self.root / "home"
        store = home / ".corthex/corthex-memory"
        store.mkdir(parents=True)
        sentinel = store / "configuration.json"
        sentinel.write_text("{}", encoding="utf-8")
        def execute(arguments, environment, demo):
            if sentinel.exists():
                sentinel.unlink()
            return {"exit": 0}
        result = self.evidence.reinstall("fixture", "codex", {}, self.root, home, execute)
        self.assertFalse(result["verified"])
        self.assertTrue(result["before"])

    def test_barrier_observes_the_same_active_retention_frame_after_parent_exit(self):
        library = self.root / "memory_lib"
        library.mkdir()
        (library / "__init__.py").write_bytes(b"")
        source = library / "retention.py"
        source.write_text("import os\nfrom pathlib import Path\ndef retain_project(memory, project, owner, deadline):\n Path(os.environ['FIXTURE_OLD']).unlink()\n", encoding="utf-8")
        (self.root / "worker_actual.py").write_text("import time\ntime.monotonic_ns=lambda:1\nimport sys\nfrom pathlib import Path\nsys.path.insert(0,str(Path(__file__).parent))\nfrom memory_lib.retention import retain_project\nretain_project(None,'demo',None,None)\n", encoding="utf-8")
        shutil.copyfile(ROOT / ".github/hook-check/lifetime_worker.py", self.root / "worker.py")
        old = self.root / "old.jsonl"
        old.write_text('{"id":"e_000000000001"}\n', encoding="utf-8")
        environment = dict(os.environ, HOOKCHECK_LIFETIME_DIR=str(self.root / "lifetime"),
                           HOOKCHECK_LIFETIME_NONCE="synthetic-fixture", FIXTURE_OLD=str(old),
                           HOOKCHECK_ORIGINAL_WORKER_SHA256=hashlib.sha256((self.root / "worker_actual.py").read_bytes()).hexdigest(),
                           HOOKCHECK_RETENTION_SHA256=hashlib.sha256(source.read_bytes()).hexdigest())
        started = self.evidence.clock_ns()
        child = subprocess.Popen([sys.executable, "-I", str(self.root / "worker.py")], env=environment,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(lambda: child.kill() if child.poll() is None else None)
        deadline = time.monotonic() + 5
        while not (self.root / "lifetime/entered.json").exists() and time.monotonic() < deadline:
            time.sleep(.025)
        self.assertIsNone(child.poll())
        self.assertTrue((self.root / "lifetime/entered.json").exists())
        host_run = {"exit":0,"started_monotonic_ns":started,"ended_monotonic_ns":self.evidence.clock_ns(),"hooks_ended_monotonic_ns":self.evidence.clock_ns()}
        read_bytes, seen = Path.read_bytes, []
        def collision(path):
            data = read_bytes(path)
            if path.name == "heartbeat.json" and json.loads(data)["monotonic_ns"] > max(host_run["ended_monotonic_ns"],host_run["hooks_ended_monotonic_ns"]):
                if seen:
                    raise PermissionError("injected observer collision after a valid heartbeat")
                seen.append(True)
            return data
        with mock.patch.object(Path,"read_bytes",collision):
            result = self.evidence.release_lifetime(self.root,environment,host_run,old)
        self.assertEqual(seen,[True])
        stdout, stderr = child.communicate(timeout=5)
        self.assertEqual((child.returncode, stdout, stderr), (0, b"", b""), stderr.decode("utf-8", "replace"))
        self.assertTrue(result["verified"],json.dumps(result))
        self.assertEqual((result["expired_record_removed"],result["barrier_timed_out"]),(True,False))

    def test_used_input_type_drift_names_the_changed_field(self):
        sys.path.insert(0, str(ROOT / "plugins/corthex-memory/skills/corthex-memory/scripts"))
        expected = json.loads((ROOT / ".github/hook-check/host-inputs.json").read_bytes())["hosts"]["claude"]
        folder = self.root / "inputs"
        folder.mkdir()
        values = {"str": "synthetic 한글", "dict": {}, "list": [], "bool": False, "NoneType": None}
        for event, fields in expected["events"].items():
            value = {name: values[kind] for name, kind in fields.items()}
            value["hook_event_name"] = event
            (folder / (event + ".json")).write_text(json.dumps(value), encoding="utf-8")
        self.assertTrue(self.evidence.input_contract(self.root, "claude", expected["version"])["verified"])
        path = folder / "UserPromptSubmit.json"
        value = json.loads(path.read_bytes())
        value["prompt"] = []
        path.write_text(json.dumps(value), encoding="utf-8")
        changed = self.evidence.input_contract(self.root, "claude", expected["version"])
        self.assertFalse(changed["verified"])
        self.assertEqual(changed["changed_fields"], {"UserPromptSubmit": ["prompt"]})

    def test_drift_values_name_versions_and_stop_reentry_changes(self):
        sys.path.insert(0,str(ROOT / "plugins/corthex-memory/skills/corthex-memory/scripts"))
        from memory_lib import hooks
        expected=json.loads((ROOT / ".github/hook-check/host-inputs.json").read_bytes())["hosts"]["claude"]
        folder=self.root / "inputs"
        folder.mkdir()
        values={"str":"fixture","dict":{},"list":[],"bool":False,"NoneType":None}
        for event,fields in expected["events"].items():
            row={name:values[kind] for name,kind in fields.items()}
            row["hook_event_name"]=event
            (folder/(event+".json")).write_text(json.dumps(row),encoding="utf-8")
        for change in ("version","Stop.stop_hook_active","prefix.version"):
            with self.subTest(change=change):
                stop=folder / "Stop.json"
                row=json.loads(stop.read_bytes())
                row["stop_hook_active"]=change=="Stop.stop_hook_active"
                stop.write_text(json.dumps(row),encoding="utf-8")
                with mock.patch.object(hooks,"HOST_PROMPTS_VERSION","changed" if change=="prefix.version" else "host-prompts-2"):
                    result=self.evidence.input_contract(self.root,"claude","0.0.0" if change=="version" else expected["version"])
                self.assertFalse(result["verified"])
                self.assertIn(change,result.get("changed_values",{}))
