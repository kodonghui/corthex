"""PR #30 regressions: recovery, safe paths, append rollback and whole deletion."""

import errno
import itertools
import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

import test_memory_files as fixtures
from memory_lib import base, files
from memory_lib import clock as memory_clock


class MemoryFileReviewTest(unittest.TestCase):
    setUp = fixtures.MemoryFilesTest.setUp

    def test_tc002_missing_root_stops_without_mkdir_or_a_path_in_the_error(self):
        target = self.folder / "missing/a/b"
        with mock.patch.object(Path, "exists", return_value=False) as exists, mock.patch.object(Path, "mkdir") as mkdir:
            with self.assertRaises(FileNotFoundError) as caught:
                base.private_directory(target)
        self.assertLessEqual(exists.call_count, len(target.parents) + 1)
        mkdir.assert_not_called()
        self.assertIsNone(caught.exception.filename)
        self.assertFalse(str(target) in str(caught.exception))

    def test_tc002_empty_home_is_unset_and_tilde_expands_without_creating_it(self):
        default = self.folder / "home/.corthex/corthex-memory"
        with mock.patch.dict(os.environ):
            os.environ.pop("CORTHEX_MEMORY_HOME", None)
            self.assertEqual(base.memory_home(), default)
            os.environ["CORTHEX_MEMORY_HOME"] = ""
            self.assertEqual(base.memory_home(), default)
            os.environ["CORTHEX_MEMORY_HOME"] = str(Path("~") / "memory")
            self.assertEqual(base.memory_home(), self.folder / "home/memory")
            os.environ["CORTHEX_MEMORY_HOME"] = str(self.store)
            self.assertEqual(base.memory_home(), self.store)
        self.assertFalse(self.store.exists())
        self.assertFalse((self.folder / "home").exists())

    def test_tc002_relative_home_is_a_safe_configuration_error_in_every_cwd(self):
        original = Path.cwd()
        raw = "relative-private-marker"
        try:
            for name in ("one", "two"):
                folder = self.folder / name
                folder.mkdir()
                os.chdir(str(folder))
                with mock.patch.dict(os.environ, {"CORTHEX_MEMORY_HOME": raw}):
                    with self.assertRaises(base.MemoryHomeInvalid) as caught:
                        base.memory_home()
                self.assertEqual(caught.exception.code, "configuration-invalid")
                self.assertEqual(caught.exception.field, "CORTHEX_MEMORY_HOME")
                self.assertFalse(hasattr(caught.exception, "reason"))
                self.assertFalse(raw in str(caught.exception))
                self.assertEqual(list(folder.iterdir()), [])
        finally:
            os.chdir(str(original))
        self.assertFalse(self.store.exists())

    def test_tc004_transient_windows_read_permission_never_restores_old_content(self):
        for reader, old, new, expected in (
                (files.read_json, b'{"release":"old"}\n', b'{"release":"new"}\n', {"release": "new"}),
                (files.read_jsonl, b'{"seq":1}\n', b'{"seq":1}\n{"seq":2}\n', [{"seq": 1}, {"seq": 2}])):
            path = self.folder / "record"
            backup = path.with_name("record.bak")
            path.write_bytes(new)
            backup.write_bytes(old)
            read, attempts = Path.read_bytes, []
            def temporary_error(target):
                attempts.append(target)
                if target == path and len(attempts) == 1:
                    raise PermissionError("made-up sharing failure")
                return read(target)
            report = mock.Mock()
            with mock.patch.object(files, "_WINDOWS", True), mock.patch.object(Path, "read_bytes", temporary_error):
                self.assertEqual(reader(path, report), expected)
            self.assertEqual(attempts, [path, path])
            self.assertEqual(path.read_bytes(), new)
            self.assertEqual(backup.read_bytes(), old)
            report.assert_not_called()

    def test_tc004_permanent_permission_fails_without_even_reading_the_backup(self):
        path, backup = self.folder / "record", self.folder / "record.bak"
        new, old = b'{"release":"new"}\n', b'{"release":"old"}\n'
        path.write_bytes(new)
        backup.write_bytes(old)
        for windows in (False, True):
            for reader in (files.read_json, files.read_jsonl):
                attempts = []
                def denied(target):
                    attempts.append(target)
                    raise PermissionError("made-up sharing failure")
                clock = itertools.count(0, 0.5)
                with mock.patch.object(files, "_WINDOWS", windows), mock.patch.object(Path, "read_bytes", denied), \
                        mock.patch.object(files.clock, "now", side_effect=lambda: next(clock)), \
                        mock.patch.object(files.time, "sleep") as sleep:
                    with self.assertRaises(PermissionError):
                        reader(path)
                self.assertTrue(all(target == path for target in attempts))
                self.assertEqual(len(attempts), 2 if windows else 1)
                self.assertEqual(sleep.call_count, 1 if windows else 0)
                self.assertEqual(path.read_bytes(), new)
                self.assertEqual(backup.read_bytes(), old)

    def test_tc004_other_io_errors_never_trigger_restoration(self):
        path, backup = self.folder / "record", self.folder / "record.bak"
        path.write_bytes(b'{"release":"new"}\n')
        backup.write_bytes(b'{"release":"old"}\n')
        before = (path.read_bytes(), backup.read_bytes())
        for windows in (False, True):
            with mock.patch.object(files, "_WINDOWS", windows), mock.patch.object(Path, "read_bytes", side_effect=OSError(errno.EIO, "made-up I/O error")) as read:
                with self.assertRaises(OSError) as caught:
                    files.read_json(path)
                self.assertEqual(caught.exception.errno, errno.EIO)
                self.assertEqual(read.call_count, 1)
            self.assertEqual((path.read_bytes(), backup.read_bytes()), before)

    def test_tc004_recheck_keeps_a_writer_that_finished_after_backup_read(self):
        path, backup = self.folder / "record", self.folder / "record.bak"
        for original in (None, b"broken"):
            if path.exists():
                path.unlink()
            if original is not None:
                path.write_bytes(original)
            old, new = b'{"release":"old"}\n', b'{"release":"new"}\n'
            backup.write_bytes(old)
            read = Path.read_bytes
            def writer_finished(target):
                if target == backup:
                    path.write_bytes(new)
                return read(target)
            report = mock.Mock()
            with mock.patch.object(Path, "read_bytes", writer_finished), mock.patch.object(files.os, "replace") as move:
                self.assertEqual(files.read_json(path, report, holding_lock=True), {"release": "new"})
                move.assert_not_called()
            self.assertEqual(path.read_bytes(), new)
            self.assertEqual(backup.read_bytes(), old)
            report.assert_not_called()

    def test_tc004_move_retry_rechecks_before_it_can_replace_new_content(self):
        path, backup = self.folder / "record", self.folder / "record.bak"
        old, new = b'{"release":"old"}\n', b'{"release":"new"}\n'
        backup.write_bytes(old)
        def sharing(source, target):
            path.write_bytes(new)
            raise PermissionError("made-up move sharing failure")
        report = mock.Mock()
        with mock.patch.object(files, "_WINDOWS", True), mock.patch.object(files.os, "replace", sharing):
            self.assertEqual(files.read_json(path, report, holding_lock=True), {"release": "new"})
        self.assertEqual(path.read_bytes(), new)
        self.assertEqual(backup.read_bytes(), old)
        report.assert_not_called()

    def test_tc003_short_writes_including_only_missing_lf_roll_back_before_failure(self):
        path = self.folder / "raw.jsonl"
        write = os.write
        for initial in (b"", b'{"seq":1}\n'):
            for length in (0, 5, -1):
                path.write_bytes(initial)
                def short(fd, data):
                    return write(fd, data[:length] if length else b"")
                with mock.patch.object(files.os, "write", short), mock.patch.object(files.os, "ftruncate", wraps=os.ftruncate) as truncate:
                    with self.assertRaises(OSError):
                        files.append_jsonl(path, {"seq": 2}, "TBL-007")
                self.assertEqual(truncate.call_count, 1)
                self.assertEqual(truncate.call_args[0][1], len(initial))
                self.assertEqual(path.read_bytes(), initial)
                files.append_jsonl(path, {"seq": 3}, "TBL-007")
                self.assertEqual([row["seq"] for row in files.read_jsonl(path)], [1, 3] if initial else [3])

    def test_tc317_darwin_full_sync_success_and_supported_fallbacks(self):
        full = types.SimpleNamespace(F_FULLFSYNC=51, fcntl=mock.Mock())
        with mock.patch.object(files.sys, "platform", "darwin"), mock.patch.dict(sys.modules, {"fcntl": full}), \
                mock.patch.object(files.os, "fsync") as sync:
            files._sync(17)
            full.fcntl.assert_called_once_with(17, 51)
            sync.assert_not_called()
        for module in (None, types.SimpleNamespace(),
                       types.SimpleNamespace(F_FULLFSYNC=51, fcntl=mock.Mock(side_effect=OSError("unsupported")))):
            with mock.patch.object(files.sys, "platform", "darwin"), mock.patch.dict(sys.modules, {"fcntl": module}), \
                    mock.patch.object(files.os, "fsync") as sync:
                files._sync(17)
                sync.assert_called_once_with(17)

    def test_tc317_only_durable_temporaries_call_the_sync_helper(self):
        for durable in (True, False):
            with mock.patch.object(files, "_sync") as sync:
                temporary = files._temporary(self.folder / "record", b"whole", durable)
            self.assertEqual(sync.call_count, int(durable))
            self.assertEqual(temporary.read_bytes(), b"whole")
            temporary.unlink()

    def test_tc316_whole_deletion_removes_backups_and_literal_temp_names(self):
        path = self.folder / "record[1].jsonl"
        deleted = [path, path.with_name(path.name + ".bak"), path.with_name(path.name + ".random.tmp")]
        kept = [path.with_name(path.name + ".tmp"), self.folder / "record1.jsonl.random.tmp", self.folder / "other.random.tmp"]
        for target in deleted + kept:
            target.write_bytes(b"made-up")
        files.delete_file(path)
        self.assertTrue(all(not target.exists() for target in deleted))
        self.assertTrue(all(target.exists() for target in kept))
        files.delete_file(path)
        missing = self.folder / "absent/record"
        files.delete_file(missing)
        self.assertFalse(missing.parent.exists())

    def test_tc316_deleting_an_orphan_backup_cannot_resurrect_forgotten_content(self):
        path, backup = self.folder / "record.json", self.folder / "record.json.bak"
        backup.write_bytes(b'{"release":"forgotten"}\n')
        files.delete_file(path)
        with self.assertRaises(FileNotFoundError):
            files.read_json(path)
        self.assertFalse(backup.exists())

    def test_tc316_whole_deletion_retries_windows_sharing_and_keeps_primary_on_failed_cleanup(self):
        path = self.folder / "record"
        backup, temporary = self.folder / "record.bak", self.folder / "record.random.tmp"
        for target in (path, backup, temporary):
            target.write_bytes(b"made-up")
        unlink, attempts = Path.unlink, {}
        def transient(target):
            attempts[target] = attempts.get(target, 0) + 1
            if attempts[target] == 1:
                raise PermissionError("made-up sharing failure")
            return unlink(target)
        with mock.patch.object(files, "_WINDOWS", True), mock.patch.object(Path, "unlink", transient):
            files.delete_file(path)
        self.assertEqual(set(attempts), {path, backup, temporary})
        self.assertTrue(all(count == 2 for count in attempts.values()))
        for target in (path, backup):
            target.write_bytes(b"whole")
        clock = itertools.count(0, 0.5)
        with mock.patch.object(files, "_WINDOWS", True), mock.patch.object(Path, "unlink", side_effect=PermissionError()), \
                mock.patch.object(files.clock, "now", side_effect=lambda: next(clock)), mock.patch.object(files.time, "sleep"):
            with self.assertRaises(PermissionError):
                files.delete_file(path)
        self.assertEqual(path.read_bytes(), b"whole")
        self.assertEqual(backup.read_bytes(), b"whole")
