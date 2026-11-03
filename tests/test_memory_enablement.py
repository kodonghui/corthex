"""TASK-019/020: actual local on/off entry points and consent, never real stores."""
import copy
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from _common import ROOT, load_json
from test_memory_api import fits

SCRIPTS = ROOT / "plugins/corthex-memory/skills/corthex-memory/scripts"
ENTRY = SCRIPTS / "memory.py"
HOOK = ROOT / "plugins/corthex-memory/scripts/hook.py"
MARKERS = ("MEMORY_TEST_KEY_VALUE_ANTHROPIC_7890", "MEMORY_TEST_KEY_VALUE_OPENAI_7890")


class EnablementTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name).resolve()
        self.home, self.memory, self.project = (self.folder / name for name in ("home", "memory", "project"))
        self.project.mkdir()
        self.registry = self.home / ".corthex/projects.json"
        self.registry.parent.mkdir(parents=True)
        self.registry.write_text(json.dumps({"projects": [{"name": "demo", "path": str(self.project)}]}), encoding="utf-8")
        self.environment = {k: v for k, v in os.environ.items() if not k.upper().startswith(
            ("CLOUDFLARE", "CF_", "CLAUDE", "ANTHROPIC", "OPENAI", "CORTHEX_MEMORY_", "GH_", "GITHUB_"))}
        self.environment.update(HOME=str(self.home), USERPROFILE=str(self.home), CORTHEX_MEMORY_HOME=str(self.memory),
                                PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        self.schema = load_json(ROOT / "docs/06-api/memory-result.schema.json")
        api = (ROOT / "docs/06-api/memory.md").read_text(encoding="utf-8")
        self.consent = api.split("```text\nCORTHEX memory, consent version 1.\n", 1)[1].split("\n```", 1)[0]
        self.consent = "CORTHEX memory, consent version 1.\n" + self.consent

    def cli(self, *arguments, folder=None, environment=None, instant=None, patch=""):
        args = ["--folder", str(folder or self.project)] + list(arguments)
        command = [sys.executable, "-B", str(ENTRY)] + args
        if instant is not None or patch:
            program = ("import sys,runpy;from pathlib import Path;s=Path(sys.argv[1]);"
                       "stamp=float(sys.argv[2]);sys.path.insert(0,str(s));"
                       "from memory_lib import commands,enablement;\n")
            if instant is not None:
                program += "commands.time.time=lambda:stamp\n"
            program += patch + "\n"
            program += ("sys.argv=[str(s/'memory.py')]+sys.argv[3:];"
                       "runpy.run_path(sys.argv[0],run_name='__main__')")
            command = [sys.executable, "-B", "-c", program, str(SCRIPTS), str(instant or 0)] + args
        env = dict(self.environment)
        env.update(environment or {})
        result = subprocess.run(command, cwd=str(self.project), env=env, stdin=subprocess.DEVNULL,
                                capture_output=True, timeout=30)
        self.assertEqual(result.stderr, b"")
        self.assertTrue(result.stdout.isascii())
        self.assertEqual(result.stdout.count(b"\n"), 1)
        value = json.loads(result.stdout)
        self.assertEqual(fits(self.schema, value), [], value)
        for marker in MARKERS:
            self.assertNotIn(marker, result.stdout.decode("ascii"))
        self.assertEqual(result.returncode, 2 if value["code"] == "usage" else int(value["outcome"] in ("failed", "refused")))
        return value, result.returncode

    def snapshot(self):
        return {p.relative_to(self.memory).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.memory.rglob("*") if p.is_file()} if self.memory.exists() else {}

    def enable(self, folder=None, environment=None):
        preview, status = self.cli("on", folder=folder, environment=environment)
        self.assertEqual((preview["outcome"], status), ("confirm", 0))
        value, status = self.cli("on", "--confirm", preview["confirm"], folder=folder, environment=environment)
        self.assertEqual((value["code"], value["outcome"], status), ("ok", "done", 0))
        return value

    def hook(self, name, prompt="on prompt", answer="on answer", environment=None):
        event = {"hook_event_name": {"prompt": "UserPromptSubmit", "end-of-turn": "Stop"}[name],
                 "session_id": "enablement-fixture", "cwd": str(self.project),
                 "prompt": prompt, "last_assistant_message": answer}
        env = dict(self.environment, CLAUDECODE="1", PLUGIN_ROOT="")
        env.update(environment or {})
        run = subprocess.run([sys.executable, "-B", str(HOOK), name], cwd=str(self.project),
                             env=env, input=json.dumps(event).encode("utf-8"), capture_output=True, timeout=15)
        self.assertEqual((run.returncode, run.stdout, run.stderr), (0, b"", b""))

    def test_tc079_without_yes_has_exact_consent_and_creates_no_store(self):
        before = self.registry.read_bytes()
        preview, status = self.cli("on")
        self.assertEqual((preview["command"], preview["code"], preview["outcome"], status), ("on", "ok", "confirm", 0))
        self.assertEqual(preview["data"], {"project": "demo", "consent": {"version": 1, "text": self.consent}})
        self.assertRegex(preview["confirm"], r"^[0-9a-hjkmnp-tv-z]{8}$")
        self.assertFalse(self.memory.exists())
        self.assertEqual(self.registry.read_bytes(), before)

    def test_tc080_yes_creates_header_configuration_and_empty_curation_without_keys(self):
        env = {"CORTHEX_MEMORY_ANTHROPIC_API_KEY": MARKERS[0], "CORTHEX_MEMORY_OPENAI_API_KEY": MARKERS[1]}
        value = self.enable(environment=env)
        record = load_json(self.memory / "store.json")
        self.assertRegex(record["device"], r"^d_[0-9a-hjkmnp-tv-z]{12}$")
        self.assertEqual(record["format"], 1)
        manifest = load_json(ROOT / "plugins/corthex-memory/.codex-plugin/plugin.json")
        self.assertEqual(record["release"], manifest["version"])
        config = load_json(self.memory / "configuration.json")
        self.assertEqual(config["consent"]["version"], 1)
        self.assertRegex(config["consent"]["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
        self.assertTrue(config["projects"]["demo"]["enabled"])
        self.assertNotIn("sync", config)
        project = self.memory / "projects/demo"
        for name in ("raw", "unprocessed", "notices", "injections", "layer", "layer/items", "layer/tombstones"):
            self.assertTrue((project / name).is_dir(), name)
        self.assertEqual(load_json(project / "curation.json"),
                         {"logs": {}, "applies": 0, "recent": [], "consolidation": {"failures": 0}})
        self.assertEqual(value["data"]["keys"], {"anthropic": "present", "openai": "present"})
        self.assertEqual((value["data"]["retention_days"], value["data"]["left_out"]), (100, {"folders": [], "kinds": []}))
        for data, _ in self.snapshot().values():
            for marker in MARKERS:
                self.assertNotIn(marker.encode(), data)

    def test_tc081_generic_provider_keys_do_not_count_as_memory_keys(self):
        env = {"ANTHROPIC_API_KEY": MARKERS[0], "OPENAI_API_KEY": MARKERS[1]}
        value = self.enable(environment=env)
        self.assertEqual(value["data"]["keys"], {"anthropic": "missing", "openai": "missing"})
        for name in ("CORTHEX_MEMORY_ANTHROPIC_API_KEY", "CORTHEX_MEMORY_OPENAI_API_KEY"):
            self.assertIn(name, value["say"])
        self.hook("prompt", environment=env)
        self.hook("end-of-turn", environment=env)
        raw = b"".join(path.read_bytes() for path in (self.memory / "projects/demo/raw").glob("*.jsonl"))
        self.assertIn(b"on prompt", raw)
        self.assertIn(b"on answer", raw)

    def test_tc082_old_consent_code_returns_fresh_consent_without_creating_store(self):
        old, _ = self.cli("on", instant=1200)
        stale, status = self.cli("on", "--confirm", old["confirm"], instant=2400)
        self.assertEqual((stale["code"], stale["outcome"], status), ("confirm-stale", "confirm", 0))
        self.assertEqual(stale["data"], old["data"])
        self.assertNotEqual(stale["confirm"], old["confirm"])
        self.assertFalse(self.memory.exists())

    def test_tc083_idempotent_on_and_second_project_preserve_device_and_consent(self):
        self.enable()
        before = self.snapshot()
        nothing, _ = self.cli("on")
        self.assertEqual(nothing["outcome"], "nothing")
        self.assertEqual(self.snapshot(), before)
        second = self.folder / "second"
        second.mkdir()
        self.registry.write_text(json.dumps({"projects": [{"name": "demo", "path": str(self.project)},
                                                         {"name": "second", "path": str(second)}]}), encoding="utf-8")
        header = load_json(self.memory / "store.json")
        consent = load_json(self.memory / "configuration.json")["consent"]
        value, _ = self.cli("on", folder=second)
        self.assertEqual((value["outcome"], value["data"]["project"]), ("done", "second"))
        self.assertEqual(load_json(self.memory / "store.json"), header)
        self.assertEqual(load_json(self.memory / "configuration.json")["consent"], consent)
        self.assertTrue((self.memory / "projects/second/curation.json").is_file())

    def test_tc085_off_twice_then_on_preserves_existing_memory_and_same_consent(self):
        self.enable()
        saved = self.memory / "projects/demo/raw/existing.jsonl"
        saved.write_bytes(b"existing raw bytes\n")
        curation = self.memory / "projects/demo/curation.json"
        before = (saved.read_bytes(), curation.read_bytes(), load_json(self.memory / "configuration.json")["consent"])
        value, _ = self.cli("off")
        self.assertEqual((value["outcome"], value["data"]), ("done", {"project": "demo"}))
        config = load_json(self.memory / "configuration.json")
        self.assertFalse(config["projects"]["demo"]["enabled"])
        snap = self.snapshot()
        value, _ = self.cli("off")
        self.assertEqual(value["outcome"], "nothing")
        self.assertEqual(self.snapshot(), snap)
        value, _ = self.cli("on")
        self.assertEqual(value["outcome"], "done")
        self.assertNotIn("confirm", value)
        self.assertEqual((saved.read_bytes(), curation.read_bytes(), load_json(self.memory / "configuration.json")["consent"]), before)

    def test_tc084_real_hooks_record_on_then_write_nothing_after_off(self):
        self.enable(environment={"ANTHROPIC_API_KEY": MARKERS[0], "OPENAI_API_KEY": MARKERS[1]})
        self.hook("prompt")
        self.hook("end-of-turn")
        logs = list((self.memory / "projects/demo/raw").glob("*.jsonl"))
        self.assertEqual(len(logs), 1)
        raw = logs[0].read_bytes()
        self.assertIn(b"on prompt", raw)
        self.assertIn(b"on answer", raw)
        value, _ = self.cli("off")
        self.assertEqual(value["outcome"], "done")
        before = self.snapshot()
        self.hook("prompt", "disabled prompt")
        self.hook("end-of-turn", answer="disabled answer")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(logs[0].read_bytes(), raw)

    def test_tc078_consent_codes_accept_current_and_previous_period(self):
        for stamp in (1250, 1800):
            with self.subTest(stamp=stamp):
                folder = self.folder / ("memory-" + str(stamp))
                env = {"CORTHEX_MEMORY_HOME": str(folder)}
                preview, _ = self.cli("on", environment=env, instant=1200)
                done, status = self.cli("on", "--confirm", preview["confirm"], environment=env, instant=stamp)
                self.assertEqual((done["outcome"], status), ("done", 0))
                self.assertTrue(load_json(folder / "configuration.json")["projects"]["demo"]["enabled"])

    def test_tc078_changed_project_is_rechecked_under_lock_and_gets_fresh_consent(self):
        preview, _ = self.cli("on")
        patch = ("from contextlib import contextmanager\n"
                 "original=commands.Context.lock\n"
                 "@contextmanager\n"
                 "def changed(context,*args,**kwargs):\n"
                 "    with original(context,*args,**kwargs) as lease:\n"
                 "        registry=Path.home()/'.corthex/projects.json'\n"
                 "        registry.write_text(" + repr(json.dumps({"projects": [{"name": "renamed", "path": str(self.project)}]})) + ",encoding='utf-8')\n"
                 "        yield lease\n"
                 "commands.Context.lock=changed\n")
        stale, status = self.cli("on", "--confirm", preview["confirm"], patch=patch)
        self.assertEqual((stale["code"], stale["outcome"], status), ("confirm-stale", "confirm", 0))
        self.assertEqual(stale["data"]["project"], "renamed")
        self.assertNotEqual(stale["confirm"], preview["confirm"])
        self.assertFalse(self.memory.exists())

    def test_on_off_preserve_existing_configuration_and_progress(self):
        self.enable()
        path = self.memory / "configuration.json"
        config = load_json(path)
        config.update(models={"curator": "fixture-curator", "dims": 256}, retention={"days": 365},
                      sync={"address": "https://sync.invalid/memory", "branch": "kept"})
        config["projects"]["demo"].update(left_out={"folders": ["private"], "kinds": ["boundary"]})
        path.write_text(json.dumps(config), encoding="utf-8")
        curation = self.memory / "projects/demo/curation.json"
        progress = {"logs": {"claude-code-0000000000000001": 7}, "applies": 9, "recent": [], "consolidation": {"failures": 2}}
        curation.write_text(json.dumps(progress), encoding="utf-8")
        before = (curation.read_bytes(), curation.stat().st_mtime_ns)
        original = copy.deepcopy(config)
        off, _ = self.cli("off")
        self.assertEqual(off["outcome"], "done")
        done, _ = self.cli("on")
        self.assertEqual(done["outcome"], "done")
        after = load_json(path)
        original["projects"]["demo"]["since"] = after["projects"]["demo"]["since"]
        self.assertEqual(after, original)
        self.assertEqual((curation.read_bytes(), curation.stat().st_mtime_ns), before)
        self.assertEqual((done["data"]["retention_days"], done["data"]["left_out"]), (365, config["projects"]["demo"]["left_out"]))

    def test_missing_or_damaged_existing_progress_is_never_reset_or_enabled(self):
        self.enable()
        self.cli("off")
        path = self.memory / "projects/demo/curation.json"
        for data in (None, b"damaged progress"):
            with self.subTest(data=data):
                if path.exists():
                    path.unlink()
                if data is not None:
                    path.write_bytes(data)
                before = (self.memory / "configuration.json").read_bytes()
                value, status = self.cli("on")
                self.assertEqual((value["code"], value["outcome"], status), ("internal", "failed", 1))
                self.assertEqual((self.memory / "configuration.json").read_bytes(), before)
                self.assertFalse(load_json(self.memory / "configuration.json")["projects"]["demo"]["enabled"])
                self.assertEqual(path.read_bytes() if path.exists() else None, data)

    def test_bootstrap_configuration_failure_leaves_recording_disabled_then_recovers(self):
        preview, _ = self.cli("on")
        patch = ("original=enablement.files.write_json\n"
                 "def fail(path,*args,**kwargs):\n"
                 "    if path.name=='configuration.json': raise OSError('test-only')\n"
                 "    return original(path,*args,**kwargs)\n"
                 "enablement.files.write_json=fail\n")
        value, status = self.cli("on", "--confirm", preview["confirm"], patch=patch)
        self.assertEqual((value["code"], status), ("internal", 1))
        self.assertTrue((self.memory / "store.json").is_file())
        self.assertFalse((self.memory / "configuration.json").exists())
        before = self.snapshot()
        self.hook("prompt")
        self.hook("end-of-turn")
        self.assertEqual(self.snapshot(), before)
        header = (self.memory / "store.json").read_bytes()
        self.enable()
        self.assertEqual((self.memory / "store.json").read_bytes(), header)

    def test_changed_store_device_under_lock_is_not_overwritten(self):
        self.enable()
        patch = ("from contextlib import contextmanager\n"
                 "import json\n"
                 "original=commands.Context.lock\n"
                 "@contextmanager\n"
                 "def changed(context,*args,**kwargs):\n"
                 "    with original(context,*args,**kwargs) as lease:\n"
                 "        path=context.memory.folder/'store.json'\n"
                 "        value=json.loads(path.read_text(encoding='utf-8'));value['device']='d_000000000000'\n"
                 "        path.write_text(json.dumps(value),encoding='utf-8')\n"
                 "        yield lease\n"
                 "commands.Context.lock=changed\n")
        before = (self.memory / "configuration.json").read_bytes()
        value, status = self.cli("off", patch=patch)
        self.assertEqual((value["code"], status), ("internal", 1))
        self.assertEqual((self.memory / "configuration.json").read_bytes(), before)
        self.assertEqual(load_json(self.memory / "store.json")["device"], "d_000000000000")

    def test_curation_symlink_cannot_enable_or_read_outside_the_store(self):
        self.enable()
        self.cli("off")
        path = self.memory / "projects/demo/curation.json"
        outside = self.folder / "outside-curation.json"
        outside.write_text(json.dumps({"logs": {}, "applies": 42, "recent": [], "consolidation": {"failures": 0}}), encoding="utf-8")
        path.unlink()
        try:
            path.symlink_to(outside)
        except OSError:
            self.skipTest("file symlinks require host permission")
        before = (self.memory / "configuration.json").read_bytes()
        target = outside.read_bytes()
        value, status = self.cli("on")
        self.assertEqual((value["code"], value["outcome"], status), ("internal", "failed", 1))
        self.assertEqual((self.memory / "configuration.json").read_bytes(), before)
        self.assertEqual(outside.read_bytes(), target)
        self.assertTrue(path.is_symlink())

    def test_lost_identity_never_restores_foreign_backup_while_logging_failure(self):
        self.enable()
        before = self.snapshot()
        patch = ("from contextlib import contextmanager\nimport json\n"
                 "original=commands.Context.lock\n@contextmanager\n"
                 "def changed(context,*args,**kwargs):\n"
                 "    with original(context,*args,**kwargs) as lease:\n"
                 "        path=context.memory.folder/'store.json'\n"
                 "        value=json.loads(path.read_text(encoding='utf-8'));value['device']='d_000000000000'\n"
                 "        path.with_name('store.json.bak').write_text(json.dumps(value),encoding='utf-8')\n"
                 "        path.write_bytes(b'{')\n"
                 "        yield lease\ncommands.Context.lock=changed\n")
        value, status = self.cli("off", patch=patch)
        self.assertEqual((value["code"], status), ("internal", 1))
        self.assertEqual((self.memory / "store.json").read_bytes(), b"{")
        self.assertEqual(load_json(self.memory / "store.json.bak")["device"], "d_000000000000")
        others = lambda entries: {name: item for name, item in entries.items() if name not in ("store.json", "store.json.bak")}
        self.assertEqual(others(self.snapshot()), others(before))

    def test_failure_diagnostics_never_write_through_an_external_log_directory(self):
        self.enable()
        outside = self.folder / "outside-logs"
        outside.mkdir()
        logs = self.memory / "logs"
        logs.rmdir()
        try:
            logs.symlink_to(outside, target_is_directory=True)
        except OSError:
            program = shutil.which("cmd.exe") if os.name == "nt" else None
            if program is None or not Path(program).is_absolute():
                self.skipTest("directory aliases require host support")
            if any(char in str(logs) + str(outside) for char in "%&|<>!^\""):
                self.skipTest("directory junction fixture path needs shell escaping")
            made = subprocess.run([program, "/d", "/c", "mklink", "/J", str(logs), str(outside)],
                                  capture_output=True, timeout=10)
            if made.returncode != 0:
                self.skipTest("directory junctions unavailable (exit %d)" % made.returncode)
        before = (self.memory / "configuration.json").read_bytes()
        patch = ("original=enablement.files.write_json\n"
                 "def fail(path,*args,**kwargs):\n"
                 "    if path.name=='configuration.json': raise OSError('test-only')\n"
                 "    return original(path,*args,**kwargs)\n"
                 "enablement.files.write_json=fail\n")
        value, status = self.cli("off", patch=patch)
        self.assertEqual((value["code"], value["data"], status), ("internal", {"error": "OSError"}, 1))
        self.assertEqual((self.memory / "configuration.json").read_bytes(), before)
        self.assertEqual(list(outside.iterdir()), [])

    def test_lost_configuration_and_curation_never_reset_existing_progress(self):
        self.enable()
        self.cli("off")
        raw = self.memory / "projects/demo/raw/old.jsonl"
        raw.write_bytes(b"old raw must remain\n")
        for name in ("configuration.json", "configuration.json.bak", "projects/demo/curation.json"):
            path = self.memory / name
            if path.exists():
                path.unlink()
        preview, _ = self.cli("on")
        value, status = self.cli("on", "--confirm", preview["confirm"])
        self.assertEqual((value["code"], value["outcome"], status), ("internal", "failed", 1))
        self.assertFalse((self.memory / "configuration.json").exists())
        self.assertFalse((self.memory / "projects/demo/curation.json").exists())
        self.assertEqual(raw.read_bytes(), b"old raw must remain\n")

    def test_two_confirmations_do_not_overwrite_the_first_device_or_consent(self):
        preview, _ = self.cli("on")
        args = [sys.executable, "-B", str(ENTRY), "--folder", str(self.project), "on", "--confirm", preview["confirm"]]
        processes = [subprocess.Popen(args, cwd=str(self.project), env=self.environment,
                                      stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
        self.addCleanup(lambda: [p.kill() for p in processes if p.poll() is None])
        values = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            self.assertEqual(stderr, b"")
            value = json.loads(stdout)
            self.assertEqual(fits(self.schema, value), [])
            self.assertEqual(process.returncode, int(value["outcome"] in ("failed", "refused")))
            values.append(value)
        self.assertEqual(sum(value["outcome"] == "done" for value in values), 1)
        other = next(value for value in values if value["outcome"] != "done")
        # A contender may observe the explicitly allowed incomplete bootstrap
        # before the winner publishes store.json; it must refuse without writes.
        self.assertIn((other["code"], other["outcome"]),
                      (("confirm-stale", "confirm"), ("store-damaged", "refused")))
        before = self.snapshot()
        nothing, _ = self.cli("on")
        self.assertEqual(nothing["outcome"], "nothing")
        self.assertEqual(self.snapshot(), before)


    def test_tc077_validated_header_bytes_cannot_be_replaced_before_pinning(self):
        for mode in ("device", "newer", "damaged"):
            with self.subTest(header=mode):
                if self.memory.exists():
                    shutil.rmtree(self.memory)
                self.enable()
                before = self.snapshot()
                patch = ("import json\noriginal=enablement._read\n"
                         "def swap(memory,name,parse,check,*args,**kwargs):\n"
                         " value=original(memory,name,parse,check,*args,**kwargs)\n"
                         " if name=='store.json':\n"
                         "  path=memory.folder/name\n"
                         "  record=json.loads(path.read_bytes())\n")
                if mode == "device":
                    patch += "  record.update(device='d_000000000000')\n"
                elif mode == "newer":
                    patch += "  record.update(format=2)\n"
                patch += ("  path.write_bytes(b'{')\n" if mode == "damaged" else
                          "  path.write_bytes(json.dumps(record).encode())\n")
                patch += " return value\nenablement._read=swap\n"
                value, status = self.cli("off", patch=patch)
                self.assertEqual((value["code"], status), ("internal", 1))
                others = lambda entries: {n: v for n, v in entries.items() if n != "store.json"}
                self.assertEqual(others(self.snapshot()), others(before))
                shutil.rmtree(self.memory)

    def test_tc077_actual_on_off_keep_the_gate_fence_after_root_replacement(self):
        for command in ("on", "off"):
            with self.subTest(command=command):
                if self.memory.exists():
                    shutil.rmtree(self.memory)
                self.enable()
                if command == "on":
                    self.cli("off")
                before = self.snapshot()
                patch = ("import shutil\noriginal=enablement._apply\n"
                         "def swap(context,*args,**kwargs):\n"
                         " root=context.memory.folder\n"
                         " moved=root.with_name('moved-" + command + "')\n"
                         " root.rename(moved)\n shutil.copytree(moved,root)\n"
                         " return original(context,*args,**kwargs)\n"
                         "enablement._apply=swap\n")
                value, status = self.cli(command, patch=patch)
                self.assertEqual((value["code"], status), ("internal", 1))
                self.assertEqual(self.snapshot(), before)
                shutil.rmtree(self.memory)

    def test_tc077_actual_enablement_logs_locked_backup_restores_once(self):
        for name in ("store.json", "configuration.json", "projects/demo/curation.json"):
            for mode in ("missing", "damaged"):
                with self.subTest(record=name, primary=mode):
                    if self.memory.exists():
                        shutil.rmtree(self.memory)
                    self.enable()
                    self.cli("off")
                    path = self.memory / "projects/demo/curation.json"
                    progress = {"logs": {"claude-code-0000000000000001": 7}, "applies": 9,
                                "recent": [], "consolidation": {"failures": 2}}
                    path.write_bytes(json.dumps(progress).encode())
                    saved = path.read_bytes()
                    patch = ("original=enablement._apply\n"
                             "def restore(context,*args,**kwargs):\n"
                             " path=context.memory.folder/" + repr(name) + "\n"
                             " path.rename(path.with_name(path.name+'.bak'))\n")
                    if mode == "damaged":
                        patch += " path.write_bytes(b'{')\n"
                    patch += " return original(context,*args,**kwargs)\nenablement._apply=restore\n"
                    value, status = self.cli("on", patch=patch)
                    self.assertEqual((value["code"], value["outcome"], status), ("ok", "done", 0))
                    self.assertEqual(path.read_bytes(), saved)
                    rows = [json.loads(line) for log in (self.memory / "logs").glob("failures-*.jsonl")
                            for line in log.read_text(encoding="utf-8").splitlines()]
                    self.assertEqual([(r["step"], r["error"]) for r in rows], [("restore", "restored")])
                    self.assertEqual(list(self.memory.rglob("*.lock")), [])
                    shutil.rmtree(self.memory)

    def test_tc077_release_failures_are_reported_after_data_leases_without_changing_success(self):
        for command, kind in (("on", "store"), ("on", "curation"), ("on", "layer"), ("off", "store")):
            for changed in (False, True):
                with self.subTest(command=command, lease=kind, changed_device=changed):
                    if self.memory.exists():
                        shutil.rmtree(self.memory)
                    self.enable()
                    if command == "on":
                        self.cli("off")
                    expected = {"store", "curation", "layer"} if command == "on" else {"store"}
                    patch = ("import json\noriginal=enablement.locks.Lock._release\nreleased=set()\n"
                             "def fail(lease,deadline):\n"
                             " released.add(lease.path.stem)\n"
                             " if lease.path.stem==" + repr(kind) + ":\n")
                    if changed:
                        patch += ("  path=lease.path.parents[0]" + (".parents[1]" if kind != "store" else "") + "/'store.json'\n"
                                  "  record=json.loads(path.read_bytes());record['device']='d_000000000000'\n"
                                  "  path.write_bytes(json.dumps(record).encode())\n")
                    patch += ("  raise PermissionError('MEMORY_TEST_RELEASE_SECRET_7890')\n"
                              " return original(lease,deadline)\nenablement.locks.Lock._release=fail\n"
                              "logging=enablement.BoundDiagnostics.failure\n"
                              "def bounded(logger,*args,**kwargs):\n"
                              " assert " + repr(expected) + " <= released\n"
                              " return logging(logger,*args,**kwargs)\n"
                              "enablement.BoundDiagnostics.failure=bounded\n")
                    value, status = self.cli(command, patch=patch)
                    failed = changed and kind != "store"
                    self.assertEqual((value["code"], value["outcome"], status),
                                     ("internal", "failed", 1) if failed else ("ok", "done", 0))
                    self.assertEqual(load_json(self.memory / "configuration.json")["projects"]["demo"]["enabled"], command == "on" and not failed)
                    rows = [json.loads(line) for log in (self.memory / "logs").glob("failures-*.jsonl")
                            for line in log.read_text(encoding="utf-8").splitlines()]
                    self.assertEqual([(row["step"], row["error"]) for row in rows],
                                     [] if changed else [("restore", "PermissionError")])
                    self.assertNotIn("MEMORY_TEST_RELEASE_SECRET_7890", json.dumps(value) + json.dumps(rows))


if __name__ == "__main__":
    unittest.main()
