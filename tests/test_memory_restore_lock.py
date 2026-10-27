"""TC-004: restoration requires the caller's record lock, never an unlocked move."""

import os
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import test_memory_files as fixtures
from memory_lib import files


class MemoryRestoreLockTest(unittest.TestCase):
    setUp = fixtures.MemoryFilesTest.setUp

    @contextmanager
    def record_lock(self, path):
        # TASK-003 supplies the production lock later. This fixture uses an
        # actual exclusive create and keeps it through each writer operation.
        lock = path.with_name(path.name + ".lock")
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            yield
        finally:
            os.close(fd)
            lock.unlink()

    def variants(self):
        return (
            (files.read_json, None, b'{"release":"old"}\n', {"release": "old"}),
            (files.read_json, b"broken", b'{"release":"old"}\n', {"release": "old"}),
            (files.read_json, b"\xff", b'{"release":"old"}\n', {"release": "old"}),
            (files.read_jsonl, None, b'{"seq":1}\n', [{"seq": 1}]),
        )

    def prepare(self, original, saved):
        path, backup = self.folder / "record", self.folder / "record.bak"
        if path.exists():
            path.unlink()
        if original is not None:
            path.write_bytes(original)
        backup.write_bytes(saved)
        return path, backup

    def test_tc004_unlocked_read_needs_restore_without_changing_any_bytes(self):
        for reader, original, saved, _ in self.variants():
            with self.subTest(reader=reader.__name__, original=original):
                path, backup = self.prepare(original, saved)
                report = mock.Mock()
                with mock.patch.object(files.os, "replace") as move:
                    with self.assertRaises(files.RestoreNeeded) as caught:
                        reader(path, report)
                move.assert_not_called()
                report.assert_not_called()
                self.assertEqual(str(caught.exception), "backup restoration requires the record lock")
                self.assertNotIn(str(path), str(caught.exception))
                self.assertIsNone(getattr(caught.exception, "filename", None))
                self.assertEqual(path.read_bytes() if path.exists() else None, original)
                self.assertEqual(backup.read_bytes(), saved)

    def test_tc004_locked_read_restores_and_reports_once(self):
        for reader, original, saved, expected in self.variants():
            with self.subTest(reader=reader.__name__, original=original):
                path, backup = self.prepare(original, saved)
                report = mock.Mock()
                with self.record_lock(path):
                    self.assertEqual(reader(path, report, holding_lock=True), expected)
                self.assertEqual(path.read_bytes(), saved)
                self.assertFalse(backup.exists())
                report.assert_called_once_with("restored", None)
                self.assertEqual(reader(path), expected)

    def test_tc004_disappearing_backup_rereads_the_primary_after_a_failed_move(self):
        for reader, saved, current, expected in (
                (files.read_json, b'{"release":"old"}\n', b'{"release":"new"}\n', {"release": "new"}),
                (files.read_jsonl, b'{"seq":1}\n', b'{"seq":1}\n{"seq":2}\n', [{"seq": 1}, {"seq": 2}])):
            path, backup = self.prepare(None, saved)
            read, attempts = Path.read_bytes, []
            def reading(target):
                attempts.append(target)
                return read(target)
            def already_restored(source, target):
                backup.unlink()
                path.write_bytes(current)
                raise FileNotFoundError("backup already moved")
            report = mock.Mock()
            with self.record_lock(path), mock.patch.object(Path, "read_bytes", reading), \
                    mock.patch.object(files.os, "replace", side_effect=already_restored) as move:
                self.assertEqual(reader(path, report, holding_lock=True), expected)
            self.assertEqual(attempts, [path, backup, path, path])
            move.assert_called_once()
            report.assert_not_called()
            self.assertEqual(path.read_bytes(), current)

    def test_tc004_unlocked_reader_cannot_overwrite_an_acknowledged_append(self):
        path, backup = self.prepare(None, b'{"seq":1}\n')
        replace = os.replace
        writer_active = False
        acknowledged = []
        def append():
            with self.record_lock(path):
                files.append_jsonl(path, {"seq": 2}, "TBL-007")
            acknowledged.append(2)
        def at_the_former_reader_move(source, target):
            nonlocal writer_active
            # Replay the reported interleaving at the reader's old final move:
            # finish an append under its lock before allowing that move. An
            # unlocked reader must never reach this point with the new guard.
            if not writer_active:
                writer_active = True
                append()
            return replace(source, target)
        with mock.patch.object(files.os, "replace", side_effect=at_the_former_reader_move) as move:
            with self.assertRaises(files.RestoreNeeded):
                files.read_jsonl(path)
            move.assert_not_called()
        self.assertFalse(writer_active)
        self.assertFalse(path.exists())
        self.assertEqual(backup.read_bytes(), b'{"seq":1}\n')
        append()
        self.assertEqual(acknowledged, [2])
        self.assertEqual(files.read_jsonl(path), [{"seq": 1}, {"seq": 2}])
        self.assertFalse(backup.exists())

    def test_tc004_append_restores_before_its_only_write(self):
        path, backup = self.prepare(None, b'{"seq":1}\n')
        report = mock.Mock()
        with self.record_lock(path), mock.patch.object(files.os, "write", wraps=os.write) as write:
            files.append_jsonl(path, {"seq": 2}, "TBL-007", report)
        write.assert_called_once()
        report.assert_called_once_with("restored", None)
        self.assertFalse(backup.exists())
        self.assertEqual(path.read_bytes(), b'{"seq":1}\n{"seq":2}\n')

    def test_tc004_append_does_not_create_a_primary_when_backup_read_fails(self):
        path, backup = self.prepare(None, b'{"seq":1}\n')
        read = Path.read_bytes
        def denied(target):
            if target == backup:
                raise PermissionError("made-up read failure")
            return read(target)
        with self.record_lock(path), mock.patch.object(files, "_WINDOWS", False), \
                mock.patch.object(Path, "read_bytes", denied), mock.patch.object(files.os, "write") as write:
            with self.assertRaises(PermissionError):
                files.append_jsonl(path, {"seq": 2}, "TBL-007")
        write.assert_not_called()
        self.assertFalse(path.exists())
        self.assertEqual(backup.read_bytes(), b'{"seq":1}\n')
