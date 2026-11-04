"""TASK-024: actual purge entry against disposable memory folders only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

import test_memory_enablement as fixture


class PurgeTest(unittest.TestCase):
    setUp = fixture.EnablementTest.setUp
    cli = fixture.EnablementTest.cli
    enable = fixture.EnablementTest.enable
    hook = fixture.EnablementTest.hook
    snapshot = fixture.EnablementTest.snapshot

    def yes(self, preview, **options):
        return self.cli("purge", "--confirm", preview["confirm"], instant=options.pop("instant", 1200), **options)

    def test_tc094_preview_and_yes_delete_only_the_store(self):
        self.enable()
        self.hook("prompt", prompt="purge fixture text")
        profile = self.home / ".corthex/profile.json"
        profile.write_text(json.dumps({"sentinel": "profile stays outside memory"}), encoding="utf-8")
        source = self.project / "sentinel.txt"
        source.write_text("project stays outside memory", encoding="utf-8")
        registry_bytes, profile_bytes = self.registry.read_bytes(), profile.read_bytes()
        before = self.snapshot()
        preview, status = self.cli("purge", instant=1200)
        self.assertEqual((preview["outcome"], preview["code"], status), ("confirm", "ok", 0))
        self.assertEqual(preview["data"]["projects"], ["demo"])
        self.assertEqual(preview["data"]["deleted"], {"items": 0, "entries": 1, "usage": 0})
        self.assertEqual(preview["data"]["sync"], "off")
        self.assertEqual(self.snapshot(), before)
        value, status = self.cli("purge", "--confirm", preview["confirm"], instant=1200)
        self.assertEqual((value["outcome"], value["code"], status), ("done", "ok", 0))
        self.assertEqual(value["data"], preview["data"])
        self.assertFalse(self.memory.exists())
        self.assertEqual(self.registry.read_bytes(), registry_bytes)
        self.assertEqual(profile.read_bytes(), profile_bytes)
        self.assertEqual(source.read_text(encoding="utf-8"), "project stays outside memory")
        self.hook("prompt")
        self.assertFalse(self.memory.exists())

    def test_tc094_missing_store_is_nothing_without_provisioning(self):
        value, status = self.cli("purge")
        self.assertEqual((value["outcome"], status), ("nothing", 0))
        self.assertEqual(value["data"]["deleted"], dict(items=0, entries=0, usage=0))
        self.assertFalse(self.memory.exists())

    def test_tc095_changed_count_sync_and_expired_codes_never_force(self):
        self.enable()
        no_force = "from memory_lib import locks\nold=locks.Lock.acquire\ndef acquire(self,*a,**kw):\n if kw.get('force'):raise AssertionError()\n return old(self,*a,**kw)\nlocks.Lock.acquire=acquire"
        first, _ = self.cli("purge", instant=1200)
        self.hook("prompt")
        changed, _ = self.yes(first, patch=no_force)
        self.assertEqual(changed["code"], "confirm-stale")
        self.assertEqual(changed["data"]["deleted"]["entries"], 1)
        config = self.memory / "configuration.json"
        document = json.loads(config.read_bytes())
        document["sync"] = dict(address="https://memory.example.test/gateway", branch="main")
        config.write_text(json.dumps(document), encoding="utf-8")
        synced, _ = self.yes(changed, patch=no_force)
        self.assertEqual((synced["code"], synced["data"]["sync"]), ("confirm-stale", "on"))
        before = self.snapshot()
        expired, _ = self.yes(synced, instant=2400, patch=no_force)
        self.assertEqual(expired["code"], "confirm-stale")
        self.assertEqual(self.snapshot(), before)

    def test_unknown_opaque_header_never_opens_payload_and_yes_deletes_folder(self):
        self.enable()
        self.hook("prompt")
        header = self.memory / "store.json"
        original = header.read_bytes()
        for content in (b'{"format":999}', b'{"format":1,"migrating":{}}', b'broken'):
            with self.subTest(content=content):
                header.write_bytes(content)
                before = self.snapshot()
                patch = "from memory_lib import store_deletion\nold=store_deletion.Deletion.read\ndef read(self,path):\n if path.name!='store.json':raise AssertionError()\n return old(self,path)\nstore_deletion.Deletion.read=read"
                value, _ = self.cli("purge", instant=1200, patch=patch)
                self.assertEqual(value["outcome"], "confirm")
                self.assertIsNone(value["data"]["projects"])
                self.assertEqual(value["data"]["deleted"], dict(items=None, entries=None, usage=None))
                self.assertEqual(value["data"]["sync"], "unknown")
                self.assertIn("unknown", value["say"])
                self.assertEqual(self.snapshot(), before)
        header.write_bytes(original)
        known, _ = self.cli("purge", instant=1200)
        header.write_bytes(b'{"format":999}')
        fresh, _ = self.yes(known)
        self.assertEqual(fresh["code"], "confirm-stale")
        deleted, status = self.yes(fresh, patch=patch)
        self.assertEqual((deleted["outcome"], status), ("done", 0))
        self.assertFalse(self.memory.exists())

    def test_unknown_fields_are_independent_and_not_zero(self):
        self.enable()
        self.hook("prompt")
        raw = next((self.memory / "projects/demo/raw").glob("*.jsonl"))
        raw.write_bytes(b'broken\n')
        (self.memory / "configuration.json").write_bytes(b'broken')
        value, _ = self.cli("purge", instant=1200)
        self.assertEqual(value["data"], dict(folder=str(self.memory), projects=["demo"],
                         deleted=dict(items=0, entries=None, usage=0), sync="unknown"))
        (self.memory / "logs/usage-2020-01.jsonl").write_bytes(b'{"fixture":true}\n')
        (self.memory / "logs/usage-2021-03.jsonl").write_bytes(b'{"fixture":true}\n{"fixture":true}\n')
        value, _ = self.cli("purge", instant=1200)
        self.assertEqual(value["data"]["deleted"]["usage"], 3)
        (self.memory / "logs/usage-2020-01.jsonl").write_bytes(b'broken\n')
        value, _ = self.cli("purge", instant=1200)
        self.assertIsNone(value["data"]["deleted"]["usage"])

    def test_unknown_blocked_project_never_reports_empty_counts(self):
        self.enable()
        self.hook("prompt")
        patch = ("from pathlib import Path\nold=Path.iterdir\n"
                 "def iterdir(self):\n if self.name=='demo' and self.parent.name=='projects':raise PermissionError()\n return old(self)\nPath.iterdir=iterdir")
        before = self.snapshot()
        value, status = self.cli("purge", instant=1200, patch=patch)
        self.assertEqual((value["outcome"], status), ("confirm", 0))
        self.assertIsNone(value["data"]["deleted"]["items"])
        self.assertIsNone(value["data"]["deleted"]["entries"])
        self.assertEqual(value["data"]["deleted"]["usage"], 0)
        self.assertEqual(self.snapshot(), before)

    def test_readable_usage_is_counted_when_project_listing_is_unknown(self):
        self.enable()
        (self.memory / "logs/usage-2020-01.jsonl").write_bytes(b'{"fixture":true}\n')
        (self.memory / "logs/usage-2021-03.jsonl").write_bytes(b'{"fixture":true}\n{"fixture":true}\n')
        patch = ("from pathlib import Path\nold=Path.iterdir\n"
                 "def iterdir(self):\n if self.name=='projects':raise PermissionError()\n return old(self)\nPath.iterdir=iterdir")
        value, status = self.cli("purge", instant=1200, patch=patch)
        self.assertEqual((value["outcome"], status), ("confirm", 0))
        self.assertIsNone(value["data"]["projects"])
        self.assertEqual(value["data"]["deleted"], dict(items=None, entries=None, usage=3))

    def test_project_alias_and_root_alias_preserve_outside_files(self):
        self.enable()
        outside = self.folder / "outside"
        outside.mkdir()
        sentinel = outside / "sentinel"
        sentinel.write_bytes(b"outside alias destination")
        before = (sentinel.read_bytes(), sentinel.stat().st_mtime_ns)
        link = self.memory / "projects/alias"
        try:
            if os.name == "nt":
                run = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                                     env=self.environment, capture_output=True, timeout=5)
                if run.returncode:
                    self.skipTest("directory junctions unavailable")
            else:
                link.symlink_to(outside, target_is_directory=True)
            value, _ = self.cli("purge", environment={"CORTHEX_MEMORY_HOME": str(link)})
            self.assertEqual(value["outcome"], "failed")
            preview, _ = self.cli("purge", instant=1200)
            self.assertIsNone(preview["data"]["projects"])
            value, status = self.yes(preview)
            self.assertEqual((value["code"], status), ("files-left", 1))
            self.assertIn("projects/alias", value["data"]["left"])
            self.assertEqual((sentinel.read_bytes(), sentinel.stat().st_mtime_ns), before)
        finally:
            if link.is_symlink():
                link.unlink()
            elif link.exists():
                link.rmdir()

    def test_unknown_operational_header_and_config_errors_allow_confirmation(self):
        self.enable()
        for name in ("record", "configuration"):
            with self.subTest(name=name):
                patch = ("from memory_lib import commands,store_deletion\n"
                         "def denied(*a,**kw):raise PermissionError('private fixture text')\n"
                         "commands._DiagnosticStore." + name + "=denied\n"
                         "old=store_deletion.Deletion.read\n"
                         "def read(self,path):\n if path.name=='" + ("store.json" if name == "record" else "configuration.json") + "':raise PermissionError()\n return old(self,path)\n"
                         "store_deletion.Deletion.read=read")
                value, status = self.cli("purge", instant=1200, patch=patch)
                self.assertEqual((value["outcome"], status), ("confirm", 0))
                self.assertEqual(value["data"]["sync"], "unknown")
                self.assertNotIn("private fixture", json.dumps(value))

    def test_tc077_purge_supported_backup_recovery_and_busy_result_remain(self):
        self.enable()
        header = self.memory / "store.json"
        backup = header.with_suffix(".json.bak")
        original = header.read_bytes()
        header.rename(backup)
        patch = "from memory_lib import locks\ndef busy(*a,**kw):raise locks.LockBusy()\nlocks.Lock.acquire=busy"
        value, status = self.cli("purge", instant=1200, patch=patch)
        self.assertEqual((value["code"], status), ("lock-busy", 1))
        self.assertFalse(header.exists())
        self.assertEqual(backup.read_bytes(), original)
        value, _ = self.cli("purge", instant=1200)
        self.assertEqual(value["outcome"], "confirm")
        self.assertEqual(header.read_bytes(), original)
        self.assertFalse(backup.exists())
        failures = list((self.memory / "logs").glob("failures-*.jsonl"))
        self.assertEqual(sum(json.loads(line)["error"] == "restored" for p in failures for line in p.read_text().splitlines()), 1)

    def test_tc096_sync_remote_device_and_plugin_sentinels_survive(self):
        self.enable()
        config = self.memory / "configuration.json"
        document = json.loads(config.read_bytes())
        document["sync"] = dict(address="https://memory.example.test/gateway", branch="main")
        config.write_text(json.dumps(document), encoding="utf-8")
        sentinels = [self.folder / name for name in ("remote", "device", "plugin")]
        for p in sentinels:
            p.write_bytes(b"outside memory; preserve")
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in sentinels}
        value, _ = self.cli("purge", instant=1200)
        self.assertEqual(value["data"]["sync"], "on")
        patch = "import subprocess\ndef blocked(*a,**kw):raise AssertionError()\nsubprocess.Popen=blocked"
        value, status = self.yes(value, patch=patch)
        self.assertEqual((value["outcome"], status), ("done", 0))
        self.assertIn("keep their copies", value["say"])
        self.assertEqual({p: (p.read_bytes(), p.stat().st_mtime_ns) for p in sentinels}, before)

    def test_protected_home_corthex_registry_and_plugin_are_refused_before_gates(self):
        protected = [self.home, self.home / ".corthex", self.folder, fixture.ENTRY.parents[3], fixture.ENTRY.parent]
        for target in protected:
            with self.subTest(target=target):
                patch = "from memory_lib import store\ndef touched(*a,**kw):raise AssertionError()\nstore.MemoryStore.record=touched"
                before = self.registry.read_bytes()
                value, status = self.cli("purge", environment={"CORTHEX_MEMORY_HOME": str(target)}, patch=patch)
                self.assertEqual((value["outcome"], status), ("failed", 1))
                self.assertEqual(self.registry.read_bytes(), before)
                self.assertTrue(target.exists())

    def test_original_override_traversal_is_refused_before_gate_access(self):
        self.enable()
        target = str(self.memory) + os.sep + ".." + os.sep + "memory"
        patch = "from memory_lib import store\ndef touched(*a,**kw):raise AssertionError()\nstore.MemoryStore.record=touched"
        # A separate marker observes whether a normal gate was entered; never
        # create a protected-root deletion token to demonstrate this boundary.
        patch = ("from memory_lib import store\nold=store.MemoryStore.record\n"
                 "def record(self,*a,**kw):\n (self.folder.parent/'gate-touched').touch()\n return old(self,*a,**kw)\nstore.MemoryStore.record=record")
        value, status = self.cli("purge", environment={"CORTHEX_MEMORY_HOME": target}, patch=patch)
        self.assertEqual((value["outcome"], status), ("failed", 1))
        self.assertFalse((self.folder / "gate-touched").exists())

    def test_same_bytes_header_replacement_and_root_replacement_stop_deletion(self):
        self.enable()
        self.hook("prompt")
        preview, _ = self.cli("purge", instant=1200)
        patch = ("from memory_lib import store_deletion\nold=store_deletion.Deletion.apply\n"
                 "def apply(self,data):\n p=self.root/'store.json';q=p.with_name('replacement');q.write_bytes(p.read_bytes());q.replace(p)\n return old(self,data)\n"
                 "store_deletion.Deletion.apply=apply")
        before = self.snapshot()
        value, status = self.yes(preview, patch=patch)
        self.assertEqual((value["outcome"], status), ("failed", 1))
        self.assertEqual({n:b for n,(b,_) in self.snapshot().items()}, {n:b for n,(b,_) in before.items()})
        preview, _ = self.cli("purge", instant=1200)
        patch = ("from memory_lib import store_deletion\nold=store_deletion.Deletion.apply\n"
                 "def apply(self,data):\n self.root.rename(self.root.with_name('old-memory'));self.root.mkdir();(self.root/'sentinel').write_bytes(b'new root')\n return old(self,data)\n"
                 "store_deletion.Deletion.apply=apply")
        value, status = self.yes(preview, patch=patch)
        self.assertEqual((value["outcome"], status), ("failed", 1))
        self.assertEqual((self.memory / "sentinel").read_bytes(), b"new root")
        self.assertTrue((self.folder / "old-memory/store.json").exists())

    def test_lost_prior_lease_blocks_next_force_acquisition_mutation(self):
        self.enable()
        preview, _ = self.cli("purge", instant=1200)
        patch = ("from memory_lib import locks\nold=locks.Lock._create\n"
                 "def create(self):\n"
                 " if self.policy.rank==3:\n"
                 "  p=self.path.parents[2]/'store.lock';p.unlink();p.write_text('{\"token\":\"'+'f'*32+'\"}')\n"
                 " value=old(self)\n"
                 " if self.policy.rank==3 and value:(self.path.parents[3]/'late-mutation').touch()\n"
                 " return value\nlocks.Lock._create=create")
        value, status = self.yes(preview, patch=patch)
        self.assertEqual((value["outcome"], status), ("failed", 1))
        self.assertFalse((self.folder / "late-mutation").exists())
        self.assertTrue((self.memory / "store.json").exists())

    def test_foreign_header_disappearance_cannot_become_owned_retirement(self):
        self.enable()
        preview, _ = self.cli("purge", instant=1200)
        patch = ("from memory_lib import store_deletion\nold=store_deletion.Deletion.unlink;check=store_deletion.Deletion.check\n"
                 "def unlink(self,path):\n self.armed=path.name=='store.json'\n return old(self,path)\n"
                 "def guard(self):\n check(self)\n if getattr(self,'armed',False):\n  self.armed=False;(self.root/'store.json').unlink()\n"
                 "store_deletion.Deletion.unlink=unlink;store_deletion.Deletion.check=guard")
        value, status = self.yes(preview, patch=patch)
        self.assertEqual((value["outcome"], status), ("failed", 1))
        self.assertTrue((self.memory / "configuration.json").exists())

    def test_final_dangling_root_slot_cannot_be_reported_deleted(self):
        self.enable()
        preview, _ = self.cli("purge", instant=1200)
        patch = ("from pathlib import Path\nfrom memory_lib import base\nimport os,subprocess\nold=Path.rmdir\n"
                 "def rmdir(self):\n old(self)\n if self==base.memory_home():\n"
                 "  target=self.parent/'absent-target'\n"
                 "  if os.name=='nt':subprocess.run(['cmd','/c','mklink','/J',str(self),str(target)],check=True,capture_output=True)\n"
                 "  else:self.symlink_to(target,target_is_directory=True)\nPath.rmdir=rmdir")
        try:
            value, status = self.yes(preview, patch=patch)
            self.assertEqual((value["outcome"], status), ("failed", 1))
            info = self.memory.lstat()
            self.assertTrue(self.memory.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400)
        finally:
            if self.memory.is_symlink():
                self.memory.unlink()
            else:
                try:
                    self.memory.rmdir()
                except FileNotFoundError:
                    pass

    def test_tc095_real_fresh_curation_holder_loses_token_without_sentinel_write(self):
        self.enable()
        held = self.memory / "projects/demo/curation.lock"
        go, done = self.folder / "go", self.folder / "done"
        program = """import json,sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from memory_lib import locks,clock
p,go,done=map(Path,sys.argv[2:5])
lease=locks.Lock(p,'curation',json.loads((p.parents[2]/'store.json').read_bytes())['device']).acquire(clock.now()+2)
print('ready',flush=True)
deadline=time.monotonic()+20
while not go.exists() and time.monotonic()<deadline:time.sleep(.005)
try:
 lease.check();lease.refresh();p.with_name('forbidden-write').write_bytes(b'bad');out='changed'
except locks.LostLock:out='lost-lock'
lease.release()
pending=done.with_name(done.name+'.pending')
pending.write_text(out,encoding='utf-8');pending.replace(done)
"""
        process = subprocess.Popen([sys.executable, "-B", "-c", program, str(fixture.SCRIPTS), str(held), str(go), str(done)],
                                   env=self.environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "ready")
            token = held.read_bytes()
            preview, _ = self.cli("purge", instant=1200)
            self.assertEqual(held.read_bytes(), token)
            patch = ("from memory_lib import locks\nimport time\nold=locks.Lock.acquire\n"
                     "def acquire(self,*a,**kw):\n value=old(self,*a,**kw)\n if kw.get('force') and self.policy.rank==1:\n"
                     "  before=self.path.read_bytes();root=self.path.parents[3];(root/'go').touch();end=time.monotonic()+10\n"
                     "  receipt=''\n  while time.monotonic()<end:\n"
                     "   try:receipt=(root/'done').read_text(encoding='utf-8')\n"
                     "   except (FileNotFoundError,PermissionError):receipt=''\n"
                     "   if receipt:break\n   time.sleep(.005)\n"
                     "  assert receipt=='lost-lock' and self.path.read_bytes()==before;self.check()\n return value\nlocks.Lock.acquire=acquire")
            value, status = self.yes(preview, patch=patch)
            self.assertEqual((value["outcome"], status), ("done", 0))
            self.assertEqual(done.read_text(), "lost-lock")
            self.assertFalse((held.parent / "forbidden-write").exists())
        finally:
            go.touch()
            output, error = process.communicate(timeout=25)
        self.assertEqual((process.returncode, error), (0, ""))

    @unittest.skipUnless(os.name == "nt", "Windows delete-sharing fixture")
    def test_tc095_real_windows_held_header_and_raw_report_files_left_then_retry(self):
        holder = """import ctypes,sys
from ctypes import wintypes as w
k=ctypes.WinDLL('kernel32',use_last_error=True)
k.CreateFileW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,ctypes.c_void_p,w.DWORD,w.DWORD,w.HANDLE]
k.CreateFileW.restype=w.HANDLE;k.CloseHandle.argtypes=[w.HANDLE]
h=k.CreateFileW(sys.argv[1],0x80000000,1,None,3,0x80,None)
if h==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
print('ready',flush=True);sys.stdin.read(1);k.CloseHandle(h)
"""
        for family in ("header", "raw"):
            with self.subTest(family=family):
                self.enable();self.hook("prompt")
                path = self.memory / "store.json" if family == "header" else next((self.memory / "projects/demo/raw").glob("*.jsonl"))
                process = subprocess.Popen([sys.executable, "-B", "-c", holder, str(path)], env=self.environment,
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    self.assertEqual(process.stdout.readline().strip(), "ready")
                    preview, _ = self.cli("purge", instant=1200)
                    started = time.monotonic()
                    value, status = self.yes(preview)
                    self.assertEqual((value["code"], status), ("files-left", 1))
                    self.assertGreaterEqual(time.monotonic() - started, .95)
                    self.assertIn(path.relative_to(self.memory).as_posix(), value["data"]["left"])
                    self.assertTrue(path.exists())
                finally:
                    _, error = process.communicate("x", timeout=10)
                self.assertEqual((process.returncode, error), (0, ""))
                fresh, _ = self.cli("purge", instant=1200)
                value, status = self.yes(fresh)
                self.assertEqual((value["outcome"], status), ("done", 0))
                self.assertFalse(self.memory.exists())


if __name__ == "__main__":
    unittest.main()
