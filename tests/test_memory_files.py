"""TC-001–005: C1 representation and crash-safe files, in isolated stores."""

import json
import os
import random
import re
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from _common import ROOT

SCRIPTS = ROOT / "plugins/corthex-memory/skills/corthex-memory/scripts"
sys.path.insert(0, str(SCRIPTS))
from memory_lib import base, files

AT = "2026-10-27T09:12:03.004Z"
WORKER = r'''
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from memory_lib import files
path = Path(sys.argv[2])
mode = sys.argv[3]
if mode == "append":
    for seq in range(1, 1001):
        files.append_jsonl(path, {"seq": seq, "text": "made-up text " * 200}, "TBL-007")
        print(seq, flush=True)
else:
    name = {"temporary": "_temporary", "backup": "_backup", "move": None}[mode]
    if name:
        original = getattr(files, name)
        def stopped(*args, **kwargs):
            original(*args, **kwargs)
            os._exit(23)
        setattr(files, name, stopped)
    else:
        original = files.os.replace
        def stopped(source, target):
            original(source, target)
            if Path(target) == path:
                os._exit(23)
        files.os.replace = stopped
    files.write_json(path, {"format": 1, "release": "new"}, "TBL-001")
'''


class MemoryFilesTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.store = self.folder / "memory"
        self.environment = mock.patch.dict(os.environ, {
            "HOME": str(self.folder / "home"), "USERPROFILE": str(self.folder / "home"),
            "CORTHEX_HOME": str(self.folder / "profile"),
            "CORTHEX_MEMORY_HOME": str(self.store),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def report(self, code, count):
        record = {"at": AT, "step": "restore" if code == "restored" else "record", "error": code}
        if count is not None:
            record["count"] = count
        files.append_jsonl(self.folder / "failures.jsonl", record, "TBL-004")

    def run_worker(self, path, mode):
        return subprocess.run([sys.executable, "-c", WORKER, str(SCRIPTS), str(path), mode],
                              capture_output=True, timeout=15)

    def test_tc001_ids_have_four_prefixes_and_no_repeat_in_100000_each(self):
        for prefix in ("d", "e", "i", "s"):
            with self.subTest(prefix=prefix):
                ids = {base.new_id(prefix) for _ in range(100000)}
                self.assertEqual(len(ids), 100000)
                self.assertTrue(all(re.fullmatch(prefix + r"_[0-9a-hjkmnp-tv-z]{12}", i) for i in ids))
        for bits, suffix in ((0, "0" * 12), ((1 << 60) - 1, "z" * 12)):
            with mock.patch.object(base.secrets, "randbits", return_value=bits):
                self.assertEqual(base.new_id("i"), "i_" + suffix)
        with self.assertRaises(ValueError):
            base.new_id("x")

    def test_tc001_times_use_utc_milliseconds_and_utc_dates(self):
        value = datetime(2026, 10, 28, 1, 2, 3, 456789, timezone(timedelta(hours=9)))
        self.assertEqual(base.utc_time(value), "2026-10-27T16:02:03.456Z")
        self.assertEqual(base.utc_date(value), "2026-10-27")
        self.assertRegex(base.utc_time(), r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z\Z")
        with self.assertRaises(ValueError):
            base.utc_time(datetime(2026, 10, 27))

    def test_tc001_each_c1_record_round_trips_in_table_order(self):
        examples = json.loads((ROOT / "docs/06-api/memory-examples.json").read_text(encoding="utf-8"))
        records = {
            "TBL-001": {"format": 1, "device": base.new_id("d"), "made": AT, "release": "0.2.0"},
            "TBL-002": examples["configuration"]["valid"]["tuned"],
            "TBL-004": {"at": AT, "step": "record", "hook": "prompt", "host": "codex",
                        "project": "sample", "error": "damaged-line", "log": "codex-0123456789abcdef", "count": 2},
            "TBL-005": {"at": AT, "hook": "prompt", "host": "codex", "ms": 1, "outcome": "ok"},
            "TBL-007": {"id": base.new_id("e"), "seq": 1, "turn": 1, "at": AT, "host": "codex",
                        "session": "made-up", "kind": "prompt", "speaker": "user", "text": "가나다 🙂\nnext"},
            "TBL-009": {"logs": {}, "applies": 0, "recent": [], "consolidation": {"failures": 0}},
        }
        doc = (ROOT / "docs/05-erd/memory.md").read_text(encoding="utf-8")
        for table, record in records.items():
            with self.subTest(table=table):
                section = re.search(r"^### [^\n]+\(" + table + r"\)\n(.*?)(?=^### |\Z)",
                                    doc, re.M | re.S).group(1)
                fields = re.findall(r"^\| `([^`]+)` \|", section, re.M)
                encoded = base.json_bytes(record, table)
                # Reversing insertion order recursively must not change the bytes.
                def reverse(value):
                    if isinstance(value, dict):
                        return {key: reverse(value[key]) for key in reversed(list(value))}
                    if isinstance(value, list):
                        return [reverse(item) for item in value]
                    return value
                self.assertEqual(encoded, base.json_bytes(reverse(record), table))
                self.assertEqual(list(json.loads(encoded)), [key for key in fields if key in record])
                path = self.folder / (table + ".json")
                files.write_json(path, record, table)
                self.assertEqual(files.read_json(path), record)
                self.assertEqual(path.read_bytes(), encoded)
                self.assertTrue(encoded.endswith(b"\n"))
                self.assertNotIn(b"\r", encoded)
                self.assertFalse(encoded.startswith(b"\xef\xbb\xbf"))
        self.assertIn("가나다 🙂".encode("utf-8"), base.json_bytes(records["TBL-007"], "TBL-007"))
        marker = self.folder / "20261027T091203Z.codex-0123456789abcdef.1"
        files.replace_bytes(marker, b"", rebuildable=True)
        self.assertEqual(marker.read_bytes(), b"")

    def test_tc001_configuration_fixtures_and_nested_order(self):
        examples = json.loads((ROOT / "docs/06-api/memory-examples.json").read_text(encoding="utf-8"))
        for name, value in examples["configuration"]["valid"].items():
            with self.subTest(name=name):
                self.assertEqual(json.loads(base.json_bytes(value, "TBL-002")), value)
        data = {"projects": {"z": {"since": AT, "enabled": True}, "a": {"since": AT, "enabled": False}},
                "consent": {"version": 1, "at": AT}}
        encoded = json.loads(base.json_bytes(data, "TBL-002"))
        self.assertEqual(list(encoded), ["consent", "projects"])
        self.assertEqual(list(encoded["consent"]), ["at", "version"])
        self.assertEqual(list(encoded["projects"]), ["a", "z"])
        self.assertEqual(list(encoded["projects"]["z"]), ["enabled", "since"])
        with self.assertRaises(ValueError):
            base.json_bytes({"ms": float("nan")}, "TBL-005")

    def test_tc002_home_resolution_and_imports_create_nothing(self):
        self.assertEqual(base.memory_home(), self.store)
        self.assertFalse(self.store.exists())
        with mock.patch.dict(os.environ):
            del os.environ["CORTHEX_MEMORY_HOME"]
            self.assertEqual(base.memory_home(), self.folder / "home/.corthex/corthex-memory")
        for operation in (lambda: files.append_jsonl(self.store / "absent.jsonl", {}, "TBL-007"),
                          lambda: files.write_json(self.store / "absent.json", {}, "TBL-001")):
            with self.assertRaises(FileNotFoundError):
                operation()
        self.assertFalse(self.store.exists())
        code = "import sys; sys.path.insert(0,sys.argv[1]); from memory_lib import base, files; base.memory_home()"
        subprocess.run([sys.executable, "-c", code, str(SCRIPTS)], check=True, timeout=10)
        self.assertFalse(self.store.exists())
        self.assertFalse((self.folder / "home").exists())

    def test_tc002_reserved_folders_are_named_the_same_on_every_os(self):
        names = ["con", "prn", "aux", "nul"] + [p + str(n) for p in ("com", "lpt") for n in range(10)]
        for name in names:
            self.assertEqual(base.project_folder_name(name), name + "_")
            base.private_directory(self.folder / base.project_folder_name(name))
        if os.name == "nt":
            # Inspect only our temporary child's DACL, without exposing any SID.
            # Python 3.13's special mkdir(0700) creates a protected DACL instead.
            import ctypes
            from ctypes import wintypes
            security = ctypes.WinDLL("advapi32", use_last_error=True)
            security.GetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p,
                                                  wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
            security.GetSecurityDescriptorControl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.WORD),
                                                              ctypes.POINTER(wintypes.DWORD)]
            needed = wintypes.DWORD()
            child = str(self.folder / "con_")
            security.GetFileSecurityW(child, 4, None, 0, ctypes.byref(needed))
            self.assertGreater(needed.value, 0)
            descriptor = ctypes.create_string_buffer(needed.value)
            self.assertTrue(security.GetFileSecurityW(child, 4, descriptor, needed.value, ctypes.byref(needed)))
            control, revision = wintypes.WORD(), wintypes.DWORD()
            self.assertTrue(security.GetSecurityDescriptorControl(descriptor, ctypes.byref(control), ctypes.byref(revision)))
            self.assertEqual(control.value & 0x1000, 0, "the child must inherit its parent DACL")
        for name in ("sample", "con-1", "com10", "lpt10", "a--b", "x-"):
            self.assertEqual(base.project_folder_name(name), name)
        for name in ("", "CON", "../sample", "a/b", "a_b", "-x", "x" * 61, "x\n"):
            with self.assertRaises(ValueError):
                base.project_folder_name(name)

    @unittest.skipIf(os.name == "nt", "Windows inherits the parent folder's permissions")
    def test_tc002_private_modes_ignore_the_umask(self):
        previous = os.umask(0)
        self.addCleanup(os.umask, previous)
        nested = base.private_directory(self.store / "projects/sample/raw")
        target = nested / "sample.jsonl"
        files.append_jsonl(target, {"seq": 1}, "TBL-007")
        files.write_json(nested / "store.json", {"format": 1}, "TBL-001")
        for path in [self.store] + list(self.store.rglob("*")):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700 if path.is_dir() else 0o600)

    def test_tc003_cut_and_damaged_lines_are_counted_without_text_in_the_notice(self):
        path = self.folder / "raw.jsonl"
        files.append_jsonl(path, {"seq": 1, "text": "whole"}, "TBL-007")
        with path.open("ab") as stream:
            stream.write(b'{"seq":2,"text":"cut')
        self.assertEqual(files.read_jsonl(path, self.report), [{"seq": 1, "text": "whole"}])
        with mock.patch.object(files.os, "write", wraps=os.write) as write:
            with mock.patch.object(files.os, "fsync") as sync:
                files.append_jsonl(path, {"seq": 3, "text": "new"}, "TBL-007")
        self.assertEqual(write.call_count, 1)
        self.assertTrue(write.call_args[0][1].startswith(b"\n"))
        sync.assert_not_called()
        self.assertEqual([r["seq"] for r in files.read_jsonl(path)], [1, 3])
        failure = files.read_jsonl(self.folder / "failures.jsonl")
        self.assertEqual(failure, [{"at": AT, "step": "record", "error": "damaged-line", "count": 1}])
        self.assertNotIn("cut", json.dumps(failure))
        self.assertNotIn(str(path), json.dumps(failure))

    def test_tc003_bad_interior_utf8_non_objects_nonfinite_and_unterminated_lines(self):
        path = self.folder / "raw.jsonl"
        path.write_bytes(b'{"seq":1}\ninvalid\n\xff\n[]\n{"x":NaN}\n{"seq":2}\n{"seq":3}')
        notices = []
        self.assertEqual(files.read_jsonl(path, lambda *n: notices.append(n)), [{"seq": 1}, {"seq": 2}])
        self.assertEqual(notices, [("damaged-line", 5)])

    def test_tc003_short_append_is_not_reported_as_success(self):
        path = self.folder / "raw.jsonl"
        write = os.write
        def short(fd, data):
            return write(fd, data[:5])
        with mock.patch.object(files.os, "write", side_effect=short) as operation:
            with self.assertRaises(OSError):
                files.append_jsonl(path, {"seq": 1}, "TBL-007")
        self.assertEqual(operation.call_count, 1)
        notices = []
        self.assertEqual(files.read_jsonl(path, lambda *n: notices.append(n)), [])
        self.assertEqual(notices, [("damaged-line", 1)])
        files.append_jsonl(path, {"seq": 2}, "TBL-007")
        self.assertEqual(files.read_jsonl(path), [{"seq": 2}])

    def test_tc003_killed_writers_keep_every_acknowledged_append(self):
        for stop in random.Random(27).sample(range(1, 1000), 4):
            with self.subTest(stop=stop):
                path = self.folder / ("raw-" + str(stop) + ".jsonl")
                process = subprocess.Popen([sys.executable, "-c", WORKER, str(SCRIPTS), str(path), "append"],
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    acknowledged = [int(process.stdout.readline()) for _ in range(stop)]
                    process.kill()
                    rest, error = process.communicate(timeout=10)
                    self.assertEqual(error, "")
                    acknowledged += [int(line) for line in rest.splitlines()]
                    entries = files.read_jsonl(path)
                    self.assertTrue(set(acknowledged).issubset({entry["seq"] for entry in entries}))
                    files.append_jsonl(path, {"seq": 1001}, "TBL-007")
                    self.assertEqual(files.read_jsonl(path)[-1], {"seq": 1001})
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.communicate(timeout=10)

    def test_tc004_stops_after_temporary_backup_and_move_leave_whole_content(self):
        old, new = {"format": 1, "release": "old"}, {"format": 1, "release": "new"}
        for step in ("temporary", "backup", "move"):
            with self.subTest(step=step):
                folder = base.private_directory(self.folder / step)
                path = folder / "store.json"
                files.write_json(path, old, "TBL-001")
                result = self.run_worker(path, step)
                self.assertEqual(result.returncode, 23, result.stderr.decode("utf-8", "replace"))
                self.assertEqual(files.read_json(path), new if step == "move" else old)
                backup = path.with_name(path.name + ".bak")
                if os.name != "nt":
                    for created in folder.iterdir():
                        self.assertEqual(stat.S_IMODE(created.stat().st_mode), 0o600)
                if step != "temporary":
                    self.assertEqual(files.read_json(backup), old)
                if step == "backup":
                    path.unlink()
                    self.assertEqual(files.read_json(path, self.report), old)
                    self.assertFalse(backup.exists())
                    self.assertEqual(files.read_jsonl(self.folder / "failures.jsonl")[-1]["error"], "restored")

    def test_tc004_invalid_primary_restores_readable_backup_and_bad_backup_fails(self):
        path = self.folder / "store.json"
        backup = self.folder / "store.json.bak"
        path.write_bytes(b"broken")
        backup.write_bytes(base.json_bytes({"format": 1}, "TBL-001"))
        self.assertEqual(files.read_json(path, self.report), {"format": 1})
        self.assertEqual(files.read_json(path), {"format": 1})
        self.assertFalse(backup.exists())
        path.write_bytes(b"broken")
        backup.write_bytes(b"also broken")
        with self.assertRaises(ValueError):
            files.read_json(path)
        self.assertEqual(path.read_bytes(), b"broken")

    def test_tc004_jsonl_restore_does_not_roll_back_readable_appends(self):
        path, backup = self.folder / "raw.jsonl", self.folder / "raw.jsonl.bak"
        backup.write_bytes(b'{"seq":1}\n')
        notices = []
        self.assertEqual(files.read_jsonl(path, lambda *n: notices.append(n)), [{"seq": 1}])
        self.assertEqual(notices, [("restored", None)])
        backup.write_bytes(b'{"seq":0}\n')
        files.append_jsonl(path, {"seq": 2}, "TBL-007")
        self.assertEqual([x["seq"] for x in files.read_jsonl(path)], [1, 2])
        self.assertTrue(backup.exists())

    def test_tc004_copy_fallback_and_rebuildable_files(self):
        path = self.folder / "store.json"
        files.write_json(path, {"format": 1}, "TBL-001")
        with mock.patch.object(files.os, "link", side_effect=OSError("no hard links")):
            with mock.patch.object(files.os, "replace", wraps=os.replace) as move:
                files.write_json(path, {"format": 2}, "TBL-001")
        self.assertEqual(files.read_json(path), {"format": 2})
        self.assertTrue(any(str(args[0][1]).endswith(".bak") for args in move.call_args_list))
        with mock.patch.object(files.os, "fsync") as sync, mock.patch.object(files, "_backup") as backup:
            files.write_json(path, {"format": 3}, "TBL-001", rebuildable=True)
        sync.assert_not_called()
        backup.assert_not_called()
        self.assertEqual(list(self.folder.glob("*.tmp")), [])

    def test_tc004_flush_or_move_failure_preserves_old_content(self):
        path = self.folder / "store.json"
        files.write_json(path, {"format": 1}, "TBL-001")
        for operation in ("fsync", "replace"):
            with self.subTest(operation=operation):
                with mock.patch.object(files.os, operation, side_effect=OSError("made-up failure")):
                    with self.assertRaises(OSError):
                        files.write_json(path, {"format": 2}, "TBL-001")
                self.assertEqual(files.read_json(path), {"format": 1})
                self.assertEqual(list(self.folder.glob("*.tmp")), [])

    @unittest.skipUnless(os.name == "nt", "Windows sharing violation requires Windows")
    def test_tc005_windows_open_target_retries_one_second_then_keeps_old_file(self):
        path = self.folder / "store.json"
        files.write_json(path, {"format": 1}, "TBL-001")
        holder = r'''
import ctypes, sys
from ctypes import wintypes
k = ctypes.WinDLL("kernel32", use_last_error=True)
k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                         wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
k.CreateFileW.restype = wintypes.HANDLE
k.CloseHandle.argtypes = [wintypes.HANDLE]
handle = k.CreateFileW(sys.argv[1], 0x80000000, 1, None, 3, 0x80, None)
if handle == ctypes.c_void_p(-1).value:
    raise ctypes.WinError(ctypes.get_last_error())
print("ready", flush=True)
sys.stdin.read(1)
k.CloseHandle(handle)
'''
        process = subprocess.Popen([sys.executable, "-c", holder, str(path)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "ready")
            started = time.monotonic()
            with self.assertRaises(PermissionError):
                files.write_json(path, {"format": 2}, "TBL-001")
            elapsed = time.monotonic() - started
            self.assertGreaterEqual(elapsed, 0.95)
            self.assertLess(elapsed, 3.0)
            self.assertEqual(files.read_json(path), {"format": 1})
            self.assertEqual(list(self.folder.glob("*.tmp")), [])
        finally:
            process.communicate("x", timeout=10)


if __name__ == "__main__":
    unittest.main()
