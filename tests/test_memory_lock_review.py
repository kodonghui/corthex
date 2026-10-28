"""TC-006–008/318: isolated deterministic lease races and cleanup failures."""

import os
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import test_memory_locks as fixtures
from memory_lib import files, locks, reading
from memory_lib import clock as memory_clock


class MemoryLockReviewTest(unittest.TestCase):
    setUp = fixtures.MemoryLocksTest.setUp
    stop_processes = fixtures.MemoryLocksTest.stop_processes
    start = fixtures.MemoryLocksTest.start
    receive = fixtures.MemoryLocksTest.receive
    new_lock = fixtures.MemoryLocksTest.new_lock
    seed = fixtures.MemoryLocksTest.seed

    def mismatch(self, force):
        path = self.folder / "sample.lock"
        self.seed(path)
        before = locks._snapshot(path)
        replacement = self.new_lock()
        with replacement.held(memory_clock.now() + 2):
            past = time.time() - 11
            os.utime(str(path), (past, past))
            data, stamp = path.read_bytes(), path.stat().st_mtime_ns
            contender = self.new_lock()
            self.assertFalse(contender._detach(before, stale=True, force=force))
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), (data, stamp))
            replacement.check()

    def test_tc006_changed_token_is_preserved_even_when_replacement_is_stale(self):
        self.mismatch(False)

    def test_tc006_force_takeover_still_rejects_a_changed_token(self):
        self.mismatch(True)

    def test_tc007_old_release_rechecks_after_a_real_takeover(self):
        lease = self.new_lock()
        lease.acquire(memory_clock.now() + 2)
        self.addCleanup(lease.release)
        old = locks._snapshot(lease.path)
        past = time.time() - 11
        os.utime(str(lease.path), (past, past))
        connection, process = self.start(fixtures.holder, str(lease.path), self.device)
        self.assertTrue(self.receive(connection))
        data, stamp = lease.path.read_bytes(), lease.path.stat().st_mtime_ns
        snapshot = locks._snapshot
        first = []
        def raced(path):
            if path == lease.path and not first:
                first.append(True)
                return old
            return snapshot(path)
        with mock.patch.object(locks, "_snapshot", raced):
            lease.release()
        self.assertEqual((lease.path.read_bytes(), lease.path.stat().st_mtime_ns), (data, stamp))
        connection.send("check")
        self.assertEqual(self.receive(connection), "changed")
        process.join(10)
        self.assertEqual(process.exitcode, 0)

    def recovery_release(self, persistent):
        path, lease = self.folder / "record.json", self.new_lock()
        backup = path.with_name(path.name + ".bak")
        backup.write_bytes(b'{"seq":1}\n')
        original_read, rename, monotonic = files.read_json, locks.os.rename, memory_clock.now
        offset, attempts, notices = [0], [], []
        def read(*args, **kwargs):
            result = original_read(*args, **kwargs)
            if kwargs.get("holding_lock"):
                offset[0] = 2  # The operation finishes after its acquisition deadline.
            return result
        def sharing(source, target):
            if Path(source) == lease.path:
                attempts.append(True)
                if persistent or len(attempts) == 1:
                    raise PermissionError("made-up release sharing failure")
            return rename(source, target)
        started = time.perf_counter()
        with mock.patch.object(files, "read_json", read), \
                mock.patch.object(locks.os, "rename", sharing), \
                mock.patch.object(locks.clock, "now", side_effect=lambda:monotonic() + offset[0]):
            value = reading.read_json(path, lease, monotonic() + 1, lambda *n:notices.append(n))
        self.assertEqual(value, {"seq":1})
        self.assertEqual(path.read_bytes(), b'{"seq":1}\n')
        self.assertFalse(backup.exists())
        self.assertGreaterEqual(len(attempts), 2)
        self.assertIsNone(lease.token)
        return lease, notices, time.perf_counter() - started

    def test_tc318_release_retries_once_after_the_operation_deadline(self):
        lease, notices, elapsed = self.recovery_release(False)
        self.assertFalse(lease.path.exists())
        self.assertEqual(notices, [("restored", None)])
        self.assertLess(elapsed, 0.5)

    def test_tc318_persistent_release_failure_reports_but_keeps_the_read_value(self):
        lease, notices, elapsed = self.recovery_release(True)
        self.addCleanup(lease.path.unlink)
        self.assertTrue(lease.path.exists())
        self.assertEqual(notices, [("restored", None), ("PermissionError", None)])
        self.assertGreaterEqual(elapsed, 0.9)
        self.assertLess(elapsed, 1.8)

    def test_tc318_expiry_after_acquisition_prevents_the_recovery_move(self):
        path, lease = self.folder / "record.json", self.new_lock()
        backup = path.with_name(path.name + ".bak")
        data = b'{"seq":1}\n'
        backup.write_bytes(data)
        acquire, monotonic = lease.acquire, memory_clock.now
        offset = [0]
        def expire(deadline):
            result = acquire(deadline)
            offset[0] = 2
            return result
        with mock.patch.object(lease, "acquire", expire), \
                mock.patch.object(locks.clock, "now", side_effect=lambda:monotonic() + offset[0]):
            with self.assertRaises(locks.LockBusy):
                reading.read_json(path, lease, monotonic() + 1)
        self.assertFalse(path.exists())
        self.assertEqual(backup.read_bytes(), data)
        self.assertFalse(lease.path.exists())

    def test_tc006_changed_token_gives_up_without_waiting_for_the_deadline(self):
        lease = self.new_lock()
        self.seed(lease.path)
        started = time.perf_counter()
        with mock.patch.object(lease, "_detach", return_value=False):
            with self.assertRaises(locks.LockBusy):
                lease.acquire(memory_clock.now() + 0.4)
        self.assertLess(time.perf_counter() - started, 0.2)

    def test_tc008_pending_acquisition_also_enforces_the_order(self):
        later = self.new_lock("pending.lock", "log")
        entered, finish = threading.Event(), threading.Event()
        answers = []
        def blocked_attempt(*args):
            entered.set()
            finish.wait(2)
            return False
        def wait_later():
            try:
                later.acquire(memory_clock.now() + 2, wait=False)
            except locks.LockBusy:
                answers.append("busy")
        with mock.patch.object(later, "_attempt", blocked_attempt):
            thread = threading.Thread(target=wait_later)
            thread.start()
            try:
                self.assertTrue(entered.wait(1))
                with self.assertRaises(locks.LockOrderError):
                    with self.new_lock("earlier.lock", "store").held(memory_clock.now() + 1):
                        pass
            finally:
                finish.set()
                thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(answers, ["busy"])

    def test_tc006_expiry_is_checked_one_nanosecond_either_side_of_each_limit(self):
        for kind, limit in (("store",120), ("curation",600), ("sync",600),
                            ("layer",120), ("raw",10), ("log",10)):
            with self.subTest(kind=kind):
                lease = self.new_lock(kind + ".lock", kind)
                self.seed(lease.path)
                stamp = lease.path.stat().st_mtime_ns
                for delta in (-1, 1):
                    with mock.patch.object(locks.time, "time_ns", return_value=stamp + limit * 10**9 + delta):
                        if delta < 0:
                            with self.assertRaises(locks.LockBusy):
                                lease.acquire(memory_clock.now() + 1, wait=False)
                        else:
                            with lease.held(memory_clock.now() + 1, wait=False):
                                lease.check()

    def test_tc007_background_refresh_failure_marks_the_lease_lost(self):
        with mock.patch.dict(locks.POLICIES, {"store":locks.Policy(0,0.01,120)}):
            lease = self.new_lock(kind="store")
        with mock.patch.object(lease, "refresh", side_effect=OSError("made-up refresh failure")):
            with lease.held(memory_clock.now() + 2):
                lease._thread.join(1)
                self.assertFalse(lease._thread.is_alive())
                with self.assertRaises(locks.LostLock):
                    lease.check()

    def test_tc008_same_kind_paths_can_be_acquired_in_order(self):
        with self.new_lock("a.lock").held(memory_clock.now() + 1):
            with self.new_lock("b.lock").held(memory_clock.now() + 1) as later:
                later.check()

    def test_tc008_same_kind_paths_are_refused_in_reverse_order(self):
        with self.new_lock("b.lock").held(memory_clock.now() + 1):
            with self.assertRaises(locks.LockOrderError):
                with self.new_lock("a.lock").held(memory_clock.now() + 1):
                    pass

    @unittest.skipUnless(os.name == "nt", "Windows lock path ordering ignores case")
    def test_tc008_windows_same_kind_path_order_ignores_case(self):
        with self.new_lock("a.lock").held(memory_clock.now() + 1):
            with self.new_lock("Z.lock").held(memory_clock.now() + 1):
                pass

    def test_tc008_held_forwards_cleanup_failure_without_hiding_the_body_error(self):
        lease, notices = self.new_lock(), []
        rename = locks.os.rename
        def sharing(source, target):
            if Path(source) == lease.path:
                raise PermissionError("made-up release sharing failure")
            return rename(source, target)
        with mock.patch.object(locks.os, "rename", sharing):
            with self.assertRaises(KeyError):
                with lease.held(memory_clock.now() + 2, report=lambda *n:notices.append(n)):
                    raise KeyError("made-up body failure")
        self.addCleanup(lease.path.unlink)
        self.assertEqual(notices, [("PermissionError", None)])
        self.assertTrue(lease.path.exists())

    def test_tc007_displaced_release_is_quiet_and_preserves_the_new_owner(self):
        lease, notices = self.new_lock(), []
        lease.acquire(memory_clock.now() + 2)
        self.addCleanup(lease.release)
        past = time.time() - 11
        os.utime(str(lease.path), (past, past))
        connection, process = self.start(fixtures.holder, str(lease.path), self.device)
        self.assertTrue(self.receive(connection))
        data = lease.path.read_bytes()
        try:
            lease.release(lambda *n:notices.append(n))
            self.assertEqual(notices, [])
            self.assertEqual(lease.path.read_bytes(), data)
        finally:
            connection.send("check")
            self.assertEqual(self.receive(connection), "changed")
            process.join(10)
        self.assertEqual(process.exitcode, 0)

    @unittest.skipUnless(os.name == "nt", "Windows lock aliases ignore case")
    def test_tc008_windows_same_path_with_another_case_is_an_order_error(self):
        with self.new_lock("A.lock").held(memory_clock.now() + 1):
            with self.assertRaises(locks.LockOrderError):
                with self.new_lock("a.lock").held(memory_clock.now() + 0.05, wait=False):
                    pass

    def test_tc318_public_reader_recovers_a_damaged_primary(self):
        path, lease = self.folder / "record.json", self.new_lock()
        path.write_bytes(b"{")
        backup = path.with_name(path.name + ".bak")
        backup.write_bytes(b'{"seq":1}\n')
        notices = []
        self.assertEqual(reading.read_json(path, lease, memory_clock.now() + 1,
                                          lambda *n:notices.append(n)), {"seq":1})
        self.assertEqual(path.read_bytes(), b'{"seq":1}\n')
        self.assertFalse(backup.exists())
        self.assertFalse(lease.path.exists())
        self.assertEqual(notices, [("restored", None)])
