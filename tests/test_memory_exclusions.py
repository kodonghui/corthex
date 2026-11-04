"""TASK-022: disposable actual-entry project recording exclusions."""
import copy
import json
import subprocess
import sys
import unittest

from _common import load_json
import test_memory_enablement as fixture


class ExclusionsTest(unittest.TestCase):
    setUp = fixture.EnablementTest.setUp
    cli = fixture.EnablementTest.cli
    enable = fixture.EnablementTest.enable
    snapshot = fixture.EnablementTest.snapshot

    def hook(self, name, folder=None, session="settings-fixture"):
        folder = folder or self.project
        event = {"hook_event_name": {"prompt": "UserPromptSubmit", "end-of-turn": "Stop", "end": "SessionEnd"}[name],
                 "cwd": str(folder), "session_id": session, "prompt": "recorded prompt",
                 "last_assistant_message": "recorded answer", "reason": "exit"}
        run = subprocess.run([sys.executable, "-B", str(fixture.HOOK), name], cwd=str(folder),
                             env=dict(self.environment, CLAUDECODE="1", PLUGIN_ROOT=""),
                             input=json.dumps(event).encode("utf-8"), capture_output=True, timeout=15)
        self.assertEqual((run.returncode, run.stdout, run.stderr), (0, b"", b""))

    def raw(self):
        return [json.loads(line) for path in (self.memory / "projects/demo/raw").glob("*.jsonl")
                for line in path.read_bytes().splitlines()]

    def other_files(self):
        return {name: value for name, value in self.snapshot().items() if name not in ("store.json", "store.json.bak")}

    def test_boundary_original_root_survives_same_device_replacement(self):
        self.enable()
        config = (self.memory / "configuration.json").read_bytes()
        patch = ("import shutil\noriginal=commands._gates\n"
                 "def replaced(context):\n"
                 " answer=original(context)\n"
                 " if context.command=='leave-out' and answer is None:\n"
                 "  folder=context.memory.folder;old=folder.with_name(folder.name+'-original')\n"
                 "  folder.rename(old);shutil.copytree(old,folder)\n"
                 " return answer\ncommands._gates=replaced\n")
        value, code = self.cli("leave-out", "private", patch=patch)
        self.assertEqual((value["code"], code), ("internal", 1))
        self.assertEqual((self.memory / "configuration.json").read_bytes(), config)
        self.assertEqual(list((self.memory / "logs").glob("failures-*.jsonl")), [])

    def test_boundary_header_pin_uses_only_the_accepted_bytes(self):
        self.enable()
        config = (self.memory / "configuration.json").read_bytes()
        patch = ("import json\noriginal=enablement._read\n"
                 "def changed(memory,name,parse,check,*args,**kwargs):\n"
                 " if name=='store.json':\n"
                 "  def accepted(data):\n"
                 "   value=parse(data);new=json.loads(data);new['format']=999\n"
                 "   (memory.folder/'store.json').write_text(json.dumps(new),encoding='utf-8')\n"
                 "   return value\n"
                 "  return original(memory,name,accepted,check,*args,**kwargs)\n"
                 " return original(memory,name,parse,check,*args,**kwargs)\n"
                 "enablement._read=changed\n")
        value, code = self.cli("leave-out", "private", patch=patch)
        self.assertEqual((value["code"], code), ("internal", 1))
        self.assertEqual(load_json(self.memory / "store.json")["format"], 999)
        self.assertEqual((self.memory / "configuration.json").read_bytes(), config)
        self.assertEqual(list((self.memory / "logs").glob("failures-*.jsonl")), [])

    def test_boundary_release_notice_preserves_success_and_hides_error_text(self):
        self.enable()
        patch = ("original=enablement.locks.Lock._release\nreleased=set()\n"
                 "def failed(lease,deadline):\n"
                 " released.add(lease.path.stem)\n"
                 " if lease.path.stem=='store':raise PermissionError('EXCLUSION_PRIVATE_RELEASE_MARKER')\n"
                 " return original(lease,deadline)\nenablement.locks.Lock._release=failed\n"
                 "logging=enablement.BoundDiagnostics.failure\n"
                 "def bounded(logger,*args,**kwargs):\n"
                 " assert 'store' in released\n"
                 " return logging(logger,*args,**kwargs)\n"
                 "enablement.BoundDiagnostics.failure=bounded\n")
        value, code = self.cli("leave-out", "private", patch=patch)
        self.assertEqual((value["code"], value["outcome"], code), ("ok", "done", 0))
        self.assertEqual(load_json(self.memory / "configuration.json")["projects"]["demo"]["left_out"]["folders"], ["private"])
        rows = [json.loads(line) for path in (self.memory / "logs").glob("failures-*.jsonl")
                for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([(row["step"], row["error"]) for row in rows], [("restore", "PermissionError")])
        self.assertNotIn("EXCLUSION_PRIVATE_RELEASE_MARKER", json.dumps(value) + json.dumps(rows))

    def test_tc090_excluded_subfolder_records_nothing_but_project_root_records(self):
        self.enable()
        nested = self.project / "secret-data/x"
        nested.mkdir(parents=True)
        value, status = self.cli("leave-out", "secret-data")
        self.assertEqual((value["outcome"], status, value["data"]),
                         ("done", 0, {"project": "demo", "folders": ["secret-data"], "kinds": []}))
        self.assertIn("session folder", value["say"])
        for hook in ("prompt", "end-of-turn", "end"):
            self.hook(hook, nested)
        self.assertEqual(self.raw(), [])
        for hook in ("prompt", "end-of-turn", "end"):
            self.hook(hook)
        self.assertEqual({entry["kind"] for entry in self.raw()}, {"prompt", "answer", "end"})

    def test_tc091_answer_exclusion_keeps_prompts_and_boundaries(self):
        self.enable()
        value, _ = self.cli("leave-out", "--kind", "answer")
        self.assertEqual(value["data"]["kinds"], ["answer"])
        for hook in ("prompt", "end-of-turn", "end"):
            self.hook(hook)
        self.assertEqual({entry["kind"] for entry in self.raw()}, {"prompt", "end"})
        self.assertNotIn("recorded answer", json.dumps(self.raw()))

    def test_tc092_outside_future_both_kinds_and_remove(self):
        self.enable()
        outside = self.folder / "outside"
        outside.mkdir()
        before = self.snapshot()
        value, status = self.cli("leave-out", str(outside))
        self.assertEqual((value["code"], value["outcome"], status), ("folder-outside", "refused", 1))
        self.assertEqual(value["data"]["outside"], [str(outside)])
        self.assertEqual(self.snapshot(), before)
        value, _ = self.cli("leave-out", "future/child", "--kind", "prompt", "--kind", "answer", "--kind", "prompt")
        self.assertEqual(value["data"], {"project": "demo", "folders": ["future/child"], "kinds": ["prompt", "answer"]})
        self.assertIn("curation has nothing to read", value["say"])
        self.assertFalse((self.project / "future").exists())
        for hook in ("prompt", "end-of-turn", "end"):
            self.hook(hook)
        self.assertEqual({entry["kind"] for entry in self.raw()}, {"end"})
        value, _ = self.cli("leave-out", "future/child", "--kind", "prompt", "--kind", "answer", "--remove")
        self.assertEqual(value["data"], {"project": "demo", "folders": [], "kinds": []})
        for hook in ("prompt", "end-of-turn"):
            self.hook(hook, session="after-removal")
        self.assertTrue({"prompt", "answer"} <= {entry["kind"] for entry in self.raw()})

    def test_removal_basis_matches_addition_in_the_selected_subfolder(self):
        self.enable()
        root_child, selected = self.project / "a", self.project / "sub"
        root_child.mkdir()
        selected.mkdir()
        selected_child = selected / "a"
        selected_child.mkdir()
        self.cli("leave-out", "a")
        added, _ = self.cli("leave-out", "a", folder=selected)
        self.assertEqual(added["data"]["folders"], ["a", "sub/a"])
        removed, code = self.cli("leave-out", "a", "--remove", folder=selected)
        self.assertEqual((removed["code"], code), ("ok", 0))
        self.assertEqual(removed["data"]["folders"], ["a"])
        self.hook("prompt", root_child)
        self.assertEqual(self.raw(), [])
        self.hook("prompt", selected_child)
        self.assertEqual(len(self.raw()), 1)

    def test_exclusions_preserve_other_settings_and_are_idempotent(self):
        self.enable()
        path = self.memory / "configuration.json"
        before = load_json(path)
        before.update(retention={"days": 123}, models={"curator": "kept-model"})
        path.write_text(json.dumps(before), encoding="utf-8")
        value, _ = self.cli("leave-out", "future", "./future", "--kind", "boundary")
        expected = copy.deepcopy(before)
        expected["projects"]["demo"]["left_out"] = {"folders": ["future"], "kinds": ["boundary"]}
        self.assertEqual(load_json(path), expected)
        before = self.snapshot()
        again, _ = self.cli("leave-out", "future", "--kind", "boundary")
        self.assertEqual(again["outcome"], "nothing")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(value["data"], again["data"])

    def test_future_exclusion_takes_effect_when_the_folder_is_created(self):
        self.enable()
        self.cli("leave-out", "future/child")
        future = self.project / "future/child/nested"
        future.mkdir(parents=True)
        self.hook("prompt", future)
        self.hook("end-of-turn", future)
        self.assertEqual(self.raw(), [])

    def test_exclusions_recheck_disabled_configuration_under_store_lock(self):
        self.enable()
        patch = ("from contextlib import contextmanager\nimport json\n"
                 "original=commands.Context.lock\n@contextmanager\n"
                 "def changed(context,*args,**kwargs):\n"
                 "    with original(context,*args,**kwargs) as lease:\n"
                 "        path=context.memory.folder/'configuration.json'\n"
                 "        value=json.loads(path.read_text(encoding='utf-8'));value['projects']['demo']['enabled']=False\n"
                 "        path.write_text(json.dumps(value),encoding='utf-8')\n"
                 "        yield lease\ncommands.Context.lock=changed\n")
        value, status = self.cli("leave-out", "private", patch=patch)
        self.assertEqual((value["code"], status), ("not-enabled", 1))
        self.assertNotIn("left_out", load_json(self.memory / "configuration.json")["projects"]["demo"])

    def test_exclusions_do_not_restore_a_foreign_device_backup_after_the_gate(self):
        self.enable()
        patch = ("from contextlib import contextmanager\nimport json\n"
                 "original=commands.Context.lock\n@contextmanager\n"
                 "def changed(context,*args,**kwargs):\n"
                 "    with original(context,*args,**kwargs) as lease:\n"
                 "        path=context.memory.folder/'store.json'\n"
                 "        value=json.loads(path.read_text(encoding='utf-8'));value['device']='d_000000000000'\n"
                 "        path.with_name('store.json.bak').write_text(json.dumps(value),encoding='utf-8')\n"
                 "        path.write_bytes(b'{')\n"
                 "        yield lease\ncommands.Context.lock=changed\n")
        config = (self.memory / "configuration.json").read_bytes()
        value, status = self.cli("leave-out", "private", patch=patch)
        self.assertEqual((value["code"], status), ("internal", 1))
        self.assertEqual((self.memory / "store.json").read_bytes(), b"{")
        self.assertEqual(load_json(self.memory / "store.json.bak")["device"], "d_000000000000")
        self.assertEqual((self.memory / "configuration.json").read_bytes(), config)

    def test_invalid_exclusion_arguments_never_poison_configuration(self):
        self.enable()
        for argument in (".", "x" * 401, "bad:name"):
            with self.subTest(argument=argument):
                before = self.snapshot()
                value, status = self.cli("leave-out", argument)
                self.assertEqual((value["code"], status), ("usage", 2))
                self.assertEqual(self.snapshot(), before)

    def test_enabled_project_can_change_exclusions_without_matching_consent(self):
        self.enable()
        path = self.memory / "configuration.json"
        original = load_json(path)
        for consent in (None, dict(original["consent"], version=2)):
            with self.subTest(consent_version=None if consent is None else consent["version"]):
                config = copy.deepcopy(original)
                if consent is None:
                    config.pop("consent")
                else:
                    config["consent"] = consent
                path.write_text(json.dumps(config), encoding="utf-8")
                value, status = self.cli("leave-out", "private", "--kind", "answer")
                self.assertEqual((value["code"], value["outcome"], status), ("ok", "done", 0))
                changed = load_json(path)
                self.assertEqual(changed.get("consent"), consent)
                self.assertTrue(changed["projects"]["demo"]["enabled"])
                self.assertEqual(changed["projects"]["demo"]["left_out"], {"folders": ["private"], "kinds": ["answer"]})

    def test_header_replacement_at_last_config_check_preserves_old_configuration(self):
        for command in ("on", "off", "leave-out"):
            with self.subTest(command=command):
                self.setUp()
                self.enable()
                if command == "on":
                    self.cli("off")
                before = (self.memory / "configuration.json").read_bytes()
                patch = "\n".join([
                    "import json,os",
                    "from pathlib import Path",
                    "from memory_lib import files",
                    "checked=files._checked;opened=Path.open;active={'yes':False,'reads':0}",
                    "def checking(check,operation):",
                    " code=getattr(operation,'__code__',None)",
                    " cells=getattr(operation,'__closure__',None)",
                    " values=dict(zip(code.co_freevars,(cell.cell_contents for cell in cells))) if code and cells else {}",
                    " if code and 'replace' in code.co_names and getattr(values.get('path'),'name',None)=='configuration.json':",
                    "  active.update(yes=True,reads=0)",
                    "  try:return checked(check,operation)",
                    "  finally:active['yes']=False",
                    " return checked(check,operation)",
                    "files._checked=checking",
                    "class Incoming:",
                    " def __init__(self,source,path):self.source,self.path=source,path",
                    " def __enter__(self):self.source.__enter__();return self",
                    " def fileno(self):return self.source.fileno()",
                    " def read(self,size=-1):return self.source.read(size)",
                    " def __exit__(self,*args):",
                    "  answer=self.source.__exit__(*args)",
                    "  value=json.loads(self.path.read_bytes());value['format']=999",
                    "  temporary=self.path.with_name('next-header');temporary.write_text(json.dumps(value),encoding='utf-8')",
                    "  os.replace(str(temporary),str(self.path))",
                    "  return answer",
                    "def opening(path,*args,**kwargs):",
                    " source=opened(path,*args,**kwargs)",
                    " mode=args[0] if args else kwargs.get('mode','r')",
                    " if path.name=='store.json' and mode=='rb' and active['yes']:",
                    "  active['reads']+=1",
                    "  if active['reads']==4:return Incoming(source,path)",
                    " return source",
                    "Path.open=opening",
                ])
                arguments = [command] + (["private"] if command == "leave-out" else [])
                value, code = self.cli(*arguments, patch=patch)
                self.assertEqual(load_json(self.memory / "store.json")["format"], 999)
                self.assertEqual((value["code"], code), ("internal", 1))
                self.assertEqual((self.memory / "configuration.json").read_bytes(), before)
                self.assertEqual(list((self.memory / "logs").glob("failures-*.jsonl")), [])
