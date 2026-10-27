"""TC-007/318: recovery leases with real processes and caller deadlines."""

import json
import os
import time
import unittest
from pathlib import Path
from unittest import mock

import test_memory_locks as fixtures
from memory_lib import files, locks, reading


def writer(connection, folder, device, take_over=False):
    root = Path(folder)
    path = root / "record.json"
    lock = locks.Lock(root / "record.lock", "raw", device)
    connection.send("ready")
    connection.recv()
    if take_over:
        past = time.time() - 11
        os.utime(str(lock.path), (past, past))
    with lock.held(time.monotonic() + 1):
        if not take_over:
            files.write_json(path, {"seq": 2}, "TBL-007")
        connection.send("held")
        connection.recv()
    connection.send("released")


def waiting_writer(connection, folder, device):
    root = Path(folder)
    lock = locks.Lock(root / "record.lock", "raw", device)
    lock.acquire(time.monotonic() + 1)
    connection.send("ready")
    connection.recv()
    files.write_json(root / "record.json", {"seq": 2}, "TBL-007")
    lock.release()
    connection.send("released")


def recovery_reader(connection, barrier, folder, device):
    root = Path(folder)
    barrier.wait(20)
    lock = locks.Lock(root / "record.lock", "raw", device)
    notices = []
    value = reading.read_json(root / "record.json", lock, time.monotonic() + 1,
                              lambda *notice: notices.append(notice))
    connection.send((value, notices))


class MemoryReadingTest(unittest.TestCase):
    setUp = fixtures.MemoryLocksTest.setUp
    stop_processes = fixtures.MemoryLocksTest.stop_processes
    start = fixtures.MemoryLocksTest.start
    receive = fixtures.MemoryLocksTest.receive

    def prepare(self):
        path = self.folder / "record.json"
        backup = self.folder / "record.json.bak"
        backup.write_bytes(b'{"seq":1}\n')
        return path, backup, locks.Lock(self.folder / "record.lock", "raw", self.device)

    def test_tc318_busy_process_blocks_recovery_until_the_recording_deadline(self):
        path, backup, lease = self.prepare()
        connection, process = self.start(fixtures.holder, str(lease.path), self.device)
        self.assertTrue(self.receive(connection))
        notices = []
        started = time.monotonic()
        with self.assertRaises(locks.LockBusy):
            reading.read_json(path, lease, started + 0.05, lambda *n: notices.append(n))
        elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, 0.045)
        self.assertLess(elapsed, 0.3)
        self.assertFalse(path.exists())
        self.assertEqual(backup.read_bytes(), b'{"seq":1}\n')
        self.assertEqual(notices, [])
        connection.send("check")
        self.assertEqual(self.receive(connection), "changed")
        process.join(10)
        self.assertEqual(process.exitcode, 0)
        # This caller is a start-memory read: its deadline is the 1,000ms row.
        self.assertEqual(reading.read_json(path, lease, time.monotonic() + 1,
                                          lambda *n: notices.append(n)), {"seq": 1})
        self.assertEqual(notices, [("restored", None)])
        self.assertFalse(backup.exists())
        self.assertFalse(lease.path.exists())

    def test_tc318_waiting_read_rechecks_a_real_writer_before_restoring(self):
        path, backup, lease = self.prepare()
        connection, process = self.start(waiting_writer, str(self.folder), self.device)
        self.assertEqual(self.receive(connection), "ready")
        acquire = lease.acquire
        def let_writer_finish(deadline):
            connection.send("write")
            self.assertEqual(self.receive(connection), "released")
            return acquire(deadline)
        notices = []
        with mock.patch.object(lease, "acquire", side_effect=let_writer_finish):
            self.assertEqual(reading.read_json(path, lease, time.monotonic() + 1,
                                              lambda *n: notices.append(n)), {"seq": 2})
        process.join(10)
        self.assertEqual(process.exitcode, 0)
        self.assertEqual(path.read_bytes(), b'{\n  "seq": 2\n}\n')
        self.assertFalse(backup.exists(), "the completed rewrite cleans up its backup")
        self.assertEqual(notices, [])

    def test_tc318_two_real_readers_restore_once_and_both_read_the_primary(self):
        path, backup, lease = self.prepare()
        barrier = self.context.Barrier(3)
        children = [self.start(recovery_reader, barrier, str(self.folder), self.device) for _ in range(2)]
        barrier.wait(20)
        answers = [self.receive(connection) for connection, _ in children]
        for connection, process in children:
            process.join(10)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual([value for value, _ in answers], [{"seq": 1}, {"seq": 1}])
        self.assertEqual(sum(notices.count(("restored", None)) for _, notices in answers), 1)
        self.assertEqual(path.read_bytes(), b'{"seq":1}\n')
        self.assertFalse(backup.exists())
        self.assertFalse(lease.path.exists())

    def test_tc007_a_real_takeover_before_the_move_prevents_restoration(self):
        path, backup, lease = self.prepare()
        connection, process = self.start(writer, str(self.folder), self.device, True)
        self.assertEqual(self.receive(connection), "ready")
        read = Path.read_bytes
        backup_reads = []
        def taken_over(target):
            data = read(target)
            if target == backup:
                backup_reads.append(True)
                if len(backup_reads) == 2:
                    connection.send("take over")
                    self.assertEqual(self.receive(connection), "held")
            return data
        with mock.patch.object(Path, "read_bytes", taken_over):
            with self.assertRaises(locks.LostLock):
                reading.read_json(path, lease, time.monotonic() + 1)
        self.assertFalse(path.exists())
        self.assertEqual(backup.read_bytes(), b'{"seq":1}\n')
        self.assertTrue(lease.path.exists(), "old owner must leave the new lease alone")
        connection.send("release")
        self.assertEqual(self.receive(connection), "released")
        process.join(10)
        self.assertEqual(process.exitcode, 0)

    def test_tc318_jsonl_and_custom_parser_share_the_public_recovery_path(self):
        path, backup, lease = self.prepare()
        self.assertEqual(reading.read_jsonl(path, lease, time.monotonic() + 1), [{"seq": 1}])
        path.unlink()
        backup.write_bytes(b'{"seq":3}\n')
        def parse(data):
            value = json.loads(data)
            return value["seq"]
        self.assertEqual(reading.read_record(path, parse, lease, time.monotonic() + 1), 3)
        self.assertEqual(files.read_record(path, parse), 3)
        with mock.patch.object(lease, "acquire") as acquire:
            self.assertEqual(reading.read_json(path, lease, time.monotonic() + 1), {"seq": 3})
            acquire.assert_not_called()

    def test_tc318_permission_and_expired_deadline_never_move_the_backup(self):
        path, backup, lease = self.prepare()
        with mock.patch.object(files, "read_json", side_effect=PermissionError("made-up")), \
                mock.patch.object(lease, "acquire") as acquire:
            with self.assertRaises(PermissionError):
                reading.read_json(path, lease, time.monotonic() + 1)
            acquire.assert_not_called()
        with self.assertRaises(locks.LockBusy):
            reading.read_json(path, lease, time.monotonic() - 1)
        self.assertFalse(path.exists())
        self.assertEqual(backup.read_bytes(), b'{"seq":1}\n')
        self.assertFalse(lease.path.exists())

    def test_tc318_windows_read_retries_share_the_operation_deadline(self):
        for phase in ("primary", "backup", "locked-primary", "locked-backup", "recheck"):
            with self.subTest(phase=phase):
                path, backup, lease = self.prepare()
                if phase == "primary":
                    path.write_bytes(b'{"seq":2}\n')
                elif path.exists():
                    path.unlink()
                before = {p.name:p.read_bytes() for p in self.folder.iterdir() if p.is_file()}
                counts = {"primary":0, "backup":0}
                original = Path.read_bytes
                def read(target):
                    kind = "primary" if target == path else "backup"
                    counts[kind] += 1
                    blocked = (phase == kind or
                               phase == "locked-" + kind and counts[kind] >= 2 or
                               phase == "recheck" and kind == "primary" and counts[kind] >= 3)
                    if blocked:
                        raise PermissionError("made-up sharing failure")
                    return original(target)
                notices = []
                deadline = time.monotonic() + 0.05
                started = time.perf_counter()
                with mock.patch.object(files, "_WINDOWS", True), \
                        mock.patch.object(Path, "read_bytes", read):
                    with self.assertRaises(PermissionError):
                        reading.read_json(path, lease, deadline, lambda *n:notices.append(n))
                self.assertLess(time.perf_counter() - started, 0.3)
                self.assertEqual({p.name:p.read_bytes() for p in self.folder.iterdir() if p.is_file()}, before)
                self.assertEqual(notices, [])
