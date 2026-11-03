"""TASK-025: repair only the missing/damaged header in disposable stores."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

import test_memory_enablement as fixture


class RepairTest(unittest.TestCase):
    setUp = fixture.EnablementTest.setUp
    cli = fixture.EnablementTest.cli
    enable = fixture.EnablementTest.enable
    hook = fixture.EnablementTest.hook
    snapshot = fixture.EnablementTest.snapshot

    def damaged(self, content=b"broken header"):
        self.enable()
        self.hook("prompt", prompt="repair fixture text")
        (self.memory / "store.json").write_bytes(content)
        return self.cli("repair", instant=1200)[0]

    def yes(self, preview, **options):
        return self.cli("repair", "--confirm", preview["confirm"], instant=options.pop("instant", 1200), **options)

    def test_tc097_missing_header_is_confirmed_then_only_header_changes(self):
        self.enable()
        self.hook("prompt", prompt="repair fixture text")
        header = self.memory / "store.json"
        original = json.loads(header.read_bytes())
        header.unlink()
        before = self.snapshot()
        preview, status = self.cli("repair", instant=1200)
        self.assertEqual((preview["outcome"], preview["code"], status), ("confirm", "ok", 0))
        self.assertEqual(preview["data"], {})
        self.assertEqual(self.snapshot(), before)
        value, status = self.cli("repair", "--confirm", preview["confirm"], instant=1200)
        self.assertEqual((value["outcome"], value["code"], status), ("done", "ok", 0))
        current = json.loads(header.read_bytes())
        self.assertNotEqual(current["device"], original["device"])
        self.assertEqual(value["data"], dict(device=current["device"]))
        after = self.snapshot()
        del after["store.json"]
        self.assertEqual(after, before)

    def test_tc097_damaged_header_keeps_config_consent_sync_and_all_payload(self):
        self.enable()
        self.hook("prompt")
        config = self.memory / "configuration.json"
        document = json.loads(config.read_bytes())
        document["sync"] = dict(address="https://memory.example.test/gateway", branch="main")
        config.write_text(json.dumps(document, indent=4), encoding="utf-8")
        (self.memory / "logs/usage-2020-01.jsonl").write_bytes(b'{"fixture":true}\n')
        (self.memory / "projects/demo/index.db").write_bytes(b"opaque index fixture")
        (self.memory / "store.json").write_bytes(b"broken header")
        before = self.snapshot()
        preview, _ = self.cli("repair", instant=1200)
        self.assertEqual(self.snapshot(), before)
        self.registry.unlink()  # The device command needs no project registry.
        value, status = self.yes(preview)
        self.assertEqual((value["outcome"], status), ("done", 0))
        after = self.snapshot()
        for name in before:
            if name != "store.json":
                self.assertEqual(after[name], before[name], name)
        self.assertEqual(set(after), set(before))
        stable = self.snapshot()
        value, _ = self.cli("repair")
        self.assertEqual(value["outcome"], "nothing")
        self.assertEqual(self.snapshot(), stable)

    def test_stale_expired_and_schema_failure_never_write_or_make_candidate(self):
        preview = self.damaged()
        before = self.snapshot()
        patch = "from memory_lib import store\ndef called(*a,**kw):raise AssertionError()\nstore.new_record=called"
        value, _ = self.cli("repair", "--confirm", "00000000", instant=1200, patch=patch)
        self.assertEqual(value["code"], "confirm-stale")
        value, _ = self.yes(preview, instant=2400, patch=patch)
        self.assertEqual(value["code"], "confirm-stale")
        patch = "from memory_lib import command_result\ndef broken():raise command_result.SchemaInvalid()\ncommand_result._load=broken"
        value, status = self.yes(preview, patch=patch)
        self.assertEqual((value["code"], status), ("internal", 1))
        self.assertEqual(self.snapshot(), before)

    def test_valid_header_invalid_configuration_is_nothing_and_never_reset(self):
        self.enable()
        config = self.memory / "configuration.json"
        config.write_bytes(b'{"consent":false}')
        before = self.snapshot()
        value, status = self.cli("repair", "--confirm", "00000000")
        self.assertEqual((value["outcome"], status), ("nothing", 0))
        self.assertEqual(self.snapshot(), before)

    def test_missing_root_and_config_are_not_provisioned_or_enabled(self):
        value, status = self.cli("repair")
        self.assertEqual((value["outcome"], value["data"], status), ("nothing", {}, 0))
        self.assertFalse(self.memory.exists())
        self.memory.mkdir()
        (self.memory / "sentinel").write_bytes(b"keep")
        preview, _ = self.cli("repair", instant=1200)
        value, status = self.yes(preview)
        self.assertEqual((value["outcome"], status), ("done", 0))
        self.assertEqual({p.name for p in self.memory.iterdir()}, {"store.json", "sentinel"})
        self.hook("prompt")
        self.assertFalse((self.memory / "configuration.json").exists())
        self.assertFalse((self.memory / "projects").exists())

    def test_tc077_supported_backup_restores_old_device_and_one_notice(self):
        self.enable()
        header = self.memory / "store.json"
        original = header.read_bytes()
        header.rename(header.with_name("store.json.bak"))
        value, status = self.cli("repair")
        self.assertEqual((value["outcome"], status), ("nothing", 0))
        self.assertEqual(value["data"]["device"], json.loads(original)["device"])
        self.assertEqual(header.read_bytes(), original)
        rows = [json.loads(line) for p in (self.memory / "logs").glob("failures-*.jsonl") for line in p.read_text().splitlines()]
        self.assertEqual(sum(x["error"] == "restored" for x in rows), 1)

    def test_newer_migrating_and_opaque_backup_refuse_without_payload_reads(self):
        self.enable()
        header = self.memory / "store.json"
        backup = header.with_name("store.json.bak")
        for primary, secondary in ((b'{"format":999}', None), (b'{"format":1,"migrating":{}}', None),
                                   (b'broken', b'{"format":999}')):
            with self.subTest(primary=primary, secondary=secondary):
                header.write_bytes(primary)
                if secondary:
                    backup.write_bytes(secondary)
                before = self.snapshot()
                patch = "from memory_lib import commands\ndef opened(*a,**kw):raise AssertionError()\ncommands._DiagnosticStore.configuration=opened"
                value, status = self.cli("repair", patch=patch)
                self.assertEqual((value["code"], status), ("store-newer", 1))
                self.assertEqual(self.snapshot(), before)

    def test_operational_read_failure_is_internal_and_never_repairable(self):
        preview = self.damaged()
        before = self.snapshot()
        patch = "from memory_lib import commands\ndef denied(*a,**kw):raise PermissionError('private fixture')\ncommands._DiagnosticStore.record=denied"
        value, status = self.yes(preview, patch=patch)
        self.assertEqual((value["code"], status), ("internal", 1))
        self.assertEqual(self.snapshot(), before)
        self.assertNotIn("private fixture", json.dumps(value))

    def test_changed_root_preserves_both_named_folders(self):
        preview = self.damaged()
        patch = ("from memory_lib import store_repair\nold=store_repair.Repair.apply\n"
                 "def apply(self):\n self.root.rename(self.root.with_name('old-memory'));self.root.mkdir();(self.root/'sentinel').write_bytes(b'foreign')\n return old(self)\nstore_repair.Repair.apply=apply")
        value, status = self.yes(preview, patch=patch)
        self.assertEqual((value["outcome"], status), ("failed", 1))
        self.assertEqual((self.memory / "sentinel").read_bytes(), b"foreign")
        self.assertEqual((self.folder / "old-memory/store.json").read_bytes(), b"broken header")

    def test_valid_or_supported_backup_appearing_under_lock_is_preserved(self):
        preview = self.damaged()
        saved = self.folder / "valid-header.json"
        # Use a separate valid fixture header as a foreign-device repair candidate.
        env = {"CORTHEX_MEMORY_HOME": str(self.folder / "other-memory")}
        self.enable(environment=env)
        saved.write_bytes((self.folder / "other-memory/store.json").read_bytes())
        for target in ("store.json", "store.json.bak"):
            with self.subTest(target=target):
                (self.memory / "store.json").write_bytes(b"broken header")
                preview, _ = self.cli("repair", instant=1200)
                patch = ("from memory_lib import locks\nold=locks.Lock.acquire\n"
                         "def acquire(self,*a,**kw):\n value=old(self,*a,**kw)\n"
                         " if self.policy.rank==0:(self.path.parent/'" + target + "').write_bytes((self.path.parent.parent/'valid-header.json').read_bytes())\n"
                         " return value\nlocks.Lock.acquire=acquire")
                value, status = self.yes(preview, patch=patch)
                self.assertEqual((value["outcome"], status), ("nothing", 0))
                self.assertEqual((self.memory / "store.json").read_bytes(), saved.read_bytes())

    def test_last_header_read_replacement_never_overwrites_newer_named_file(self):
        preview = self.damaged()
        patch = ("from memory_lib import store_repair\nold=store_repair.Repair.read\n"
                 "def read(self,path):\n value=old(self,path)\n"
                 " if self.lease is not None and path.name=='store.json':\n"
                 "  p=path.with_name('foreign');p.write_bytes(b'{\"format\":999}');p.replace(path)\n return value\nstore_repair.Repair.read=read")
        value, status = self.yes(preview, patch=patch)
        self.assertEqual((value["outcome"], status), ("failed", 1))
        self.assertEqual((self.memory / "store.json").read_bytes(), b'{"format":999}')

    def test_confirmation_expiring_during_acquisition_returns_fresh_preview(self):
        preview = self.damaged()
        before = self.snapshot()
        patch = ("from memory_lib import commands,locks\nold=locks.Lock.acquire\n"
                 "def acquire(self,*a,**kw):\n value=old(self,*a,**kw);commands.time.time=lambda:2400\n return value\nlocks.Lock.acquire=acquire")
        value, status = self.yes(preview, patch=patch)
        self.assertEqual((value["code"], status), ("confirm-stale", 0))
        self.assertNotEqual(value["confirm"], preview["confirm"])
        self.assertEqual(self.snapshot(), before)

    def test_own_replace_finishes_and_release_notice_is_after_data_lease(self):
        preview = self.damaged()
        patch = ("from memory_lib import locks\nold=locks.Lock.release\n"
                 "def release(self,report=None):\n old(self,report=report)\n"
                 " if self.policy.rank==0 and report:report('PermissionError',None)\nlocks.Lock.release=release")
        value, status = self.yes(preview, patch=patch)
        self.assertEqual((value["outcome"], status), ("done", 0))
        rows = [json.loads(line) for p in (self.memory / "logs").glob("failures-*.jsonl") for line in p.read_text().splitlines()]
        self.assertEqual(sum(x["error"] == "PermissionError" for x in rows), 1)

    def test_tc077_actual_fresh_store_holder_keeps_confirmed_repair_busy(self):
        preview = self.damaged()
        holder = """import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from memory_lib import locks,clock
lease=locks.Lock(Path(sys.argv[2]),'store','d_000000000000').acquire(clock.now()+2)
print('ready',flush=True);sys.stdin.read(1);lease.release()
"""
        process = subprocess.Popen([sys.executable, "-B", "-c", holder, str(fixture.SCRIPTS), str(self.memory / "store.lock")],
                                   env=self.environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "ready")
            token = (self.memory / "store.lock").read_bytes()
            before = self.snapshot()
            started = time.monotonic()
            value, status = self.yes(preview)
            self.assertEqual((value["code"], status), ("lock-busy", 1))
            self.assertGreaterEqual(time.monotonic() - started, 9.8)
            self.assertEqual((self.memory / "store.lock").read_bytes(), token)
            self.assertEqual(self.snapshot(), before)
        finally:
            _, error = process.communicate("x", timeout=10)
        self.assertEqual((process.returncode, error), (0, ""))

    @unittest.skipUnless(os.name == "nt", "Windows header-sharing fixture")
    def test_windows_held_header_move_failure_preserves_original_then_retry(self):
        preview = self.damaged()
        path = self.memory / "store.json"
        config = self.memory / "configuration.json"
        before = (config.read_bytes(), config.stat().st_mtime_ns)
        holder = """import ctypes,sys
from ctypes import wintypes as w
k=ctypes.WinDLL('kernel32',use_last_error=True)
k.CreateFileW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,ctypes.c_void_p,w.DWORD,w.DWORD,w.HANDLE]
k.CreateFileW.restype=w.HANDLE;k.CloseHandle.argtypes=[w.HANDLE]
h=k.CreateFileW(sys.argv[1],0x80000000,1,None,3,0x80,None)
if h==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
print('ready',flush=True);sys.stdin.read(1);k.CloseHandle(h)
"""
        process = subprocess.Popen([sys.executable, "-B", "-c", holder, str(path)], env=self.environment,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "ready")
            started = time.monotonic()
            value, status = self.yes(preview)
            self.assertEqual((value["code"], status), ("internal", 1))
            self.assertGreaterEqual(time.monotonic() - started, .95)
            self.assertEqual(path.read_bytes(), b"broken header")
            self.assertEqual((config.read_bytes(), config.stat().st_mtime_ns), before)
        finally:
            _, error = process.communicate("x", timeout=10)
        self.assertEqual((process.returncode, error), (0, ""))
        preview, _ = self.cli("repair", instant=1200)
        value, status = self.yes(preview)
        self.assertEqual((value["outcome"], status), ("done", 0))
        self.assertEqual((config.read_bytes(), config.stat().st_mtime_ns), before)


if __name__ == "__main__":
    unittest.main()
