"""TASK-023: actual local retention command with disposable records only."""
import copy
from datetime import datetime, timedelta, timezone
import json
import subprocess
import sys
import unittest

from _common import load_json
import test_memory_enablement as fixture


class RetentionCommandTest(unittest.TestCase):
    def setUp(self):
        fixture.EnablementTest.setUp(self)
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
    cli = fixture.EnablementTest.cli
    enable = fixture.EnablementTest.enable
    snapshot = fixture.EnablementTest.snapshot
    hook = fixture.EnablementTest.hook

    def seeded(self, ages):
        self.hook("prompt")
        path = next((self.memory / "projects/demo/raw").glob("*.jsonl"))
        original = json.loads(path.read_bytes().splitlines()[0])
        now = self.now
        rows = []
        for seq, age in enumerate(ages, 1):
            row = copy.deepcopy(original)
            row.update(id="e_" + str(seq).zfill(12), seq=seq, turn=seq,
                       at=(now - timedelta(days=age)).strftime("%Y-%m-%dT%H:%M:%S.000Z"))
            rows.append(row)
        path.write_bytes(b"".join((json.dumps(row) + "\n").encode() for row in rows))
        return path, rows

    def retained(self, *args, **kwargs):
        patch = ("from memory_lib import retention_settings\n"
                 "from datetime import datetime,timezone\n"
                 "retention_settings._now=lambda:datetime.fromisoformat(%r)\n" % self.now.isoformat())
        patch += kwargs.pop("patch", "")
        return self.cli("retention", *args, patch=patch, **kwargs)

    def test_tc093_shorten_stale_confirm_extend_and_idempotent(self):
        self.enable()
        before = self.snapshot()
        preview, status = self.cli("retention", "7", instant=1200)
        self.assertEqual((preview["code"], preview["outcome"], status), ("ok", "confirm", 0))
        self.assertEqual(preview["data"], {"days": 7, "was": 100, "entries": 0})
        self.assertEqual(self.snapshot(), before)
        stale, _ = self.cli("retention", "7", "--confirm", preview["confirm"], instant=2400)
        self.assertEqual((stale["code"], stale["outcome"]), ("confirm-stale", "confirm"))
        self.assertNotEqual(stale["confirm"], preview["confirm"])
        self.assertEqual(self.snapshot(), before)
        applied, _ = self.cli("retention", "7", "--confirm", stale["confirm"], instant=2400)
        self.assertEqual((applied["code"], applied["outcome"]), ("ok", "done"))
        self.assertEqual(load_json(self.memory / "configuration.json")["retention"], {"days": 7})
        extended, _ = self.cli("retention", "200", instant=2400)
        self.assertEqual((extended["outcome"], extended["data"]), ("done", {"days": 200, "was": 7}))
        self.assertNotIn("confirm", extended)
        after = self.snapshot()
        repeated, _ = self.cli("retention", "200", instant=2400)
        self.assertEqual(repeated["outcome"], "nothing")
        self.assertEqual(self.snapshot(), after)

    def test_preview_counts_entries_not_turns_and_keeps_cutoff_future_and_invalid_ages(self):
        self.enable()
        path, rows = self.seeded([101, 8, 7, 1, -1])
        answer = dict(rows[0], id="e_000000000006", seq=6, turn=1, kind="answer", speaker="agent")
        invalid = dict(rows[0], id="e_000000000007", seq=7, turn=7, at="2026-02-30T00:00:00.000Z")
        with path.open("ab") as raw:
            raw.write((json.dumps(answer) + "\n").encode())
            raw.write((json.dumps(invalid) + "\n").encode())
            raw.write(b"damaged row\n" + json.dumps(rows[0]).encode())
        before = self.snapshot()
        value, _ = self.retained("7")
        self.assertEqual(value["data"], {"days": 7, "was": 100, "entries": 3})
        self.assertEqual(value["outcome"], "confirm")
        self.assertEqual(self.snapshot(), before)

    def test_preview_includes_disabled_and_no_longer_registered_projects(self):
        self.enable()
        path, _ = self.seeded([8, 1])
        for name in ("disabled", "unregistered"):
            folder = self.folder / name
            folder.mkdir()
            registry = load_json(self.registry)
            registry["projects"].append({"name": name, "path": str(folder)})
            self.registry.write_text(json.dumps(registry), encoding="utf-8")
            value, _ = self.cli("on", folder=folder)
            self.assertEqual(value["outcome"], "done")
            destination = self.memory / "projects" / name / "raw" / path.name
            destination.write_bytes(path.read_bytes())
            if name == "disabled":
                self.cli("off", folder=folder)
        config_path = self.memory / "configuration.json"
        config = load_json(config_path)
        config["projects"].pop("unregistered")
        config_path.write_text(json.dumps(config), encoding="utf-8")
        self.registry.write_text(json.dumps({"projects": [{"name": "demo", "path": str(self.project)}]}), encoding="utf-8")
        before = self.snapshot()
        value, _ = self.retained("7", folder=self.folder)
        self.assertEqual(value["data"]["entries"], 3)
        self.assertEqual(self.snapshot(), before)

    def test_fresh_preview_invalidates_confirmation_after_the_entry_count_changes(self):
        self.enable()
        path, rows = self.seeded([8, 1])
        preview, _ = self.retained("7", instant=1200)
        self.assertEqual(preview["data"]["entries"], 1)
        rows[1]["at"] = rows[0]["at"]
        path.write_bytes(b"".join((json.dumps(row) + "\n").encode() for row in rows))
        before = self.snapshot()
        stale, _ = self.retained("7", "--confirm", preview["confirm"], instant=1200)
        self.assertEqual((stale["code"], stale["data"]["entries"]), ("confirm-stale", 2))
        self.assertNotEqual(stale["confirm"], preview["confirm"])
        self.assertEqual(self.snapshot(), before)

    def test_missing_primary_preview_reads_backup_without_restoring_it(self):
        self.enable()
        path, _ = self.seeded([8, 1])
        path.rename(path.with_name(path.name + ".bak"))
        before = self.snapshot()
        value, _ = self.retained("7")
        self.assertEqual(value["data"]["entries"], 1)
        self.assertFalse(path.exists())
        self.assertEqual(self.snapshot(), before)

    def test_unreadable_raw_refuses_incomplete_count_without_changing_configuration(self):
        self.enable()
        path, _ = self.seeded([8, 1])
        before, raw = (self.memory / "configuration.json").read_bytes(), path.read_bytes()
        patch = ("from pathlib import Path\noriginal=Path.open\n"
                 "def blocked(path,*args,**kwargs):\n"
                 " if path.parent.name=='raw' and path.suffix=='.jsonl':raise PermissionError('RETENTION_PRIVATE_READ_MARKER')\n"
                 " return original(path,*args,**kwargs)\nPath.open=blocked\n")
        value, code = self.retained("7", patch=patch)
        self.assertEqual((value["code"], code), ("internal", 1))
        self.assertNotIn("entries", value["data"])
        self.assertEqual((self.memory / "configuration.json").read_bytes(), before)
        self.assertEqual(path.read_bytes(), raw)
        self.assertNotIn("RETENTION_PRIVATE_READ_MARKER", json.dumps(value) + str(self.snapshot()))

    def test_confirm_changes_only_configuration_and_start_reason_worker_uses_the_setting(self):
        self.enable()
        path, rows = self.seeded([8, 1, -1])
        raw = path.read_bytes()
        config_path = self.memory / "configuration.json"
        before = load_json(config_path)
        preview, _ = self.retained("7")
        self.assertEqual(preview["data"]["entries"], 1)
        value, _ = self.retained("7", "--confirm", preview["confirm"])
        self.assertEqual(value["outcome"], "done")
        self.assertEqual(path.read_bytes(), raw)
        expected = copy.deepcopy(before)
        expected["retention"] = {"days": 7}
        self.assertEqual(load_json(config_path), expected)
        worker = fixture.ROOT / "plugins/corthex-memory/scripts/worker.py"
        result = subprocess.run([sys.executable, "-B", str(worker), "--project", "demo", "--reason", "start"],
                                cwd=str(self.project), env=self.environment, stdin=subprocess.DEVNULL,
                                capture_output=True, timeout=20)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))
        remaining = [json.loads(line) for line in path.read_bytes().splitlines()]
        self.assertEqual([row["id"] for row in remaining], [row["id"] for row in rows[1:]])


    def test_boundary_original_root_survives_same_device_replacement(self):
        self.enable()
        config = (self.memory / "configuration.json").read_bytes()
        patch = ("import shutil\noriginal=commands._gates\n"
                 "def replaced(context):\n"
                 " answer=original(context)\n"
                 " if context.command=='retention' and answer is None:\n"
                 "  folder=context.memory.folder;old=folder.with_name(folder.name+'-original')\n"
                 "  folder.rename(old);shutil.copytree(old,folder)\n"
                 " return answer\ncommands._gates=replaced\n")
        value, code = self.cli("retention", "200", patch=patch)
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
        value, code = self.cli("retention", "200", patch=patch)
        self.assertEqual((value["code"], code), ("internal", 1))
        self.assertEqual(load_json(self.memory / "store.json")["format"], 999)
        self.assertEqual((self.memory / "configuration.json").read_bytes(), config)
        self.assertEqual(list((self.memory / "logs").glob("failures-*.jsonl")), [])

    def test_boundary_release_notice_preserves_success_and_hides_error_text(self):
        self.enable()
        patch = ("original=enablement.locks.Lock._release\nreleased=set()\n"
                 "def failed(lease,deadline):\n"
                 " released.add(lease.path.stem)\n"
                 " if lease.path.stem=='store':raise PermissionError('RETENTION_PRIVATE_RELEASE_MARKER')\n"
                 " return original(lease,deadline)\nenablement.locks.Lock._release=failed\n"
                 "logging=enablement.BoundDiagnostics.failure\n"
                 "def bounded(logger,*args,**kwargs):\n"
                 " assert 'store' in released\n"
                 " return logging(logger,*args,**kwargs)\n"
                 "enablement.BoundDiagnostics.failure=bounded\n")
        value, code = self.cli("retention", "200", patch=patch)
        self.assertEqual((value["code"], value["outcome"], code), ("ok", "done", 0))
        self.assertEqual(load_json(self.memory / "configuration.json")["retention"]["days"], 200)
        rows = [json.loads(line) for path in (self.memory / "logs").glob("failures-*.jsonl")
                for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([(row["step"], row["error"]) for row in rows], [("restore", "PermissionError")])
        self.assertNotIn("RETENTION_PRIVATE_RELEASE_MARKER", json.dumps(value) + json.dumps(rows))


    def test_header_replacement_at_last_config_check_preserves_old_configuration(self):
        for command in ("retention",):
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
                arguments = [command, "200"]
                value, code = self.cli(*arguments, patch=patch)
                self.assertEqual(load_json(self.memory / "store.json")["format"], 999)
                self.assertEqual((value["code"], code), ("internal", 1))
                self.assertEqual((self.memory / "configuration.json").read_bytes(), before)
                self.assertEqual(list((self.memory / "logs").glob("failures-*.jsonl")), [])


if __name__ == "__main__":
    unittest.main()
