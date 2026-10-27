"""TC-006–008: real processes, isolated homes and generated lease nonces."""

import contextlib
import json
import multiprocessing
import os
import stat
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from _common import ROOT

SCRIPTS = ROOT / "plugins/corthex-memory/skills/corthex-memory/scripts"
sys.path.insert(0, str(SCRIPTS))
from memory_lib import base, locks


def racer(connection, barrier, folder, device):
    for number in range(100):
        barrier.wait(20)
        lock = locks.Lock(Path(folder) / (str(number) + ".lock"), "raw", device)
        acquired = False
        try:
            lock.acquire(time.monotonic() + 2, wait=False)
            acquired = True
        except locks.LockBusy:
            pass
        barrier.wait(20)
        owned = False
        if acquired:
            try:
                owned = lock.check()
            except locks.LostLock:
                pass
        connection.send((acquired, owned, os.getpid()))
        connection.recv()
        lock.release()
        connection.send(True)


def holder(connection, path, device, heartbeat=False):
    if heartbeat:
        locks.POLICIES["store"] = locks.Policy(0, 0.02, 0.2)
    lock = locks.Lock(path, "store" if heartbeat else "raw", device)
    lock.acquire(time.monotonic() + 2)
    connection.send(True)
    command = connection.recv()
    try:
        if command == "refresh":
            lock.refresh()
        else:
            lock.check()
            Path(path).with_suffix(".changed").write_bytes(b"made-up change")
        connection.send("changed")
    except locks.LostLock:
        connection.send("lost-lock")
    finally:
        lock.release()


def forked_holder(connection, inherited, path, device):
    try:
        inherited.release()
    except locks.LostLock:
        with locks.Lock(path, "store", device).held(time.monotonic() + 2):
            connection.send(True)
    else:
        connection.send(False)


class MemoryLocksTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.environment = mock.patch.dict(os.environ, {
            "HOME": str(self.folder / "home"), "USERPROFILE": str(self.folder / "home"),
            "CORTHEX_HOME": str(self.folder / "profile"),
            "CORTHEX_MEMORY_HOME": str(self.folder / "memory"),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.device = base.new_id("d")
        self.context = multiprocessing.get_context("spawn")
        self.processes = []
        self.addCleanup(self.stop_processes)

    def stop_processes(self):
        for process in self.processes:
            process.join(timeout=2)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)

    def start(self, target, *args):
        parent, child = self.context.Pipe()
        process = self.context.Process(target=target, args=(child,) + args)
        process.start()
        child.close()
        self.processes.append(process)
        self.addCleanup(parent.close)
        return parent, process

    def receive(self, connection):
        self.assertTrue(connection.poll(20), "child process did not respond")
        return connection.recv()

    def new_lock(self, name="sample.lock", kind="raw"):
        return locks.Lock(self.folder / name, kind, self.device)

    def seed(self, path):
        record = {"pid": os.getpid(), "device": self.device, "at": base.utc_time(),
                  "token": locks.secrets.token_hex(16)}
        path.write_text(json.dumps(record), encoding="utf-8")
        if os.name != "nt":
            path.chmod(0o600)
        past = time.time() - 11
        os.utime(str(path), (past, past))

    def test_tc006_two_processes_race_for_one_stale_lock_100_times(self):
        barrier = self.context.Barrier(3)
        connections = [self.start(racer, barrier, str(self.folder), self.device)[0] for _ in range(2)]
        for number in range(100):
            with self.subTest(round=number):
                path = self.folder / (str(number) + ".lock")
                self.seed(path)
                barrier.wait(20)
                barrier.wait(20)
                answers = [self.receive(c) for c in connections]
                self.assertEqual(sum(a[0] for a in answers), 1)
                self.assertEqual(sum(a[1] for a in answers), 1)
                winner = next(a for a in answers if a[1])
                record = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(record["pid"], winner[2])
                self.assertRegex(record["token"], r"^[0-9a-f]{32}$")
                for connection in connections:
                    connection.send("release")
                for connection in connections:
                    self.assertTrue(self.receive(connection))
                self.assertFalse(path.exists())
        for process in self.processes:
            process.join(10)
            self.assertEqual(process.exitcode, 0)

    def test_tc006_a_wrong_token_after_rename_restores_without_clobbering(self):
        path = self.folder / "sample.lock"
        self.seed(path)
        before = locks._snapshot(path)
        # A contender's observed stale owner has already been replaced.
        replacement = self.new_lock()
        replacement.acquire(time.monotonic() + 2)
        self.addCleanup(replacement.release)
        data = path.read_bytes()
        contender = self.new_lock()
        self.assertFalse(contender._detach(before, stale=True))
        self.assertEqual(path.read_bytes(), data)
        replacement.check()
        with mock.patch.object(locks.os, "link", side_effect=OSError("no hard links")):
            self.assertFalse(contender._detach(before, stale=True))
        self.assertEqual(path.read_bytes(), data)
        replacement.check()

    def test_tc006_restore_never_overwrites_a_newer_contender(self):
        path = self.folder / "sample.lock"
        self.seed(path)
        moved = self.folder / "owned.stale"
        path.rename(moved)
        snapshot = locks._snapshot(moved)
        replacement = self.new_lock()
        with replacement.held(time.monotonic() + 2):
            data = path.read_bytes()
            for use_copy in (False, True):
                patch = mock.patch.object(locks.os, "link", side_effect=OSError("no hard links")) if use_copy else contextlib.nullcontext()
                with patch:
                    locks._restore(moved, path, snapshot)
                self.assertEqual(path.read_bytes(), data)
                replacement.check()

    def test_tc006_refresh_after_a_stale_observation_is_preserved(self):
        path = self.folder / "sample.lock"
        self.seed(path)
        before = locks._snapshot(path)
        os.utime(str(path), None)
        contender = self.new_lock()
        self.assertFalse(contender._detach(before, stale=True))
        self.assertTrue(path.exists())
        self.assertTrue(locks._snapshot(path).token == before.token)

    def test_tc007_paused_holder_does_not_change_or_remove_the_new_lease(self):
        path = self.folder / "sample.lock"
        connection, process = self.start(holder, str(path), self.device)
        self.assertTrue(self.receive(connection))
        past = time.time() - 11
        os.utime(str(path), (past, past))
        replacement = self.new_lock()
        with replacement.held(time.monotonic() + 2):
            connection.send("change")
            self.assertEqual(self.receive(connection), "lost-lock")
            process.join(10)
            self.assertEqual(process.exitcode, 0)
            replacement.check()
            self.assertFalse(path.with_suffix(".changed").exists())

    def test_tc007_heartbeat_touches_only_mtime_and_lost_refresh_stops(self):
        path = self.folder / "sample.lock"
        connection, process = self.start(holder, str(path), self.device, True)
        self.assertTrue(self.receive(connection))
        data, before = path.read_bytes(), path.stat().st_mtime_ns
        limit = time.monotonic() + 2
        while path.stat().st_mtime_ns <= before and time.monotonic() < limit:
            time.sleep(0.01)
        self.assertGreater(path.stat().st_mtime_ns, before)
        self.assertEqual(path.read_bytes(), data)
        replacement = self.new_lock(kind="store")
        with replacement.held(time.monotonic() + 2, force=True):
            data, before = path.read_bytes(), path.stat().st_mtime_ns
            connection.send("refresh")
            self.assertEqual(self.receive(connection), "lost-lock")
            process.join(10)
            self.assertEqual(process.exitcode, 0)
            self.assertEqual(path.read_bytes(), data)
            self.assertEqual(path.stat().st_mtime_ns, before)
            replacement.check()

    def test_tc008_busy_deadline_and_nonblocking_attempt(self):
        path = self.folder / "sample.lock"
        connection, process = self.start(holder, str(path), self.device)
        self.assertTrue(self.receive(connection))
        started = time.monotonic()
        with self.assertRaises(locks.LockBusy) as error:
            self.new_lock().acquire(started + 0.05)
        elapsed = time.monotonic() - started
        self.assertEqual(str(error.exception), "lock-busy")
        self.assertGreaterEqual(elapsed, 0.045)
        self.assertLess(elapsed, 0.25)
        with self.assertRaises(locks.LockBusy):
            self.new_lock().acquire(time.monotonic() + 2, wait=False)
        connection.send("change")
        self.assertEqual(self.receive(connection), "changed")
        process.join(10)
        self.assertEqual(process.exitcode, 0)

    def test_tc008_process_wide_order_and_context_release(self):
        held = []
        try:
            for kind in locks.POLICIES:
                lock = self.new_lock(kind + ".lock", kind)
                lock.acquire(time.monotonic() + 2)
                held.append(lock)
            for kind in list(locks.POLICIES)[:-1]:
                path = self.folder / (kind + "-earlier.lock")
                with self.assertRaises(locks.LockOrderError):
                    locks.Lock(path, kind, self.device).acquire(time.monotonic() + 2)
                self.assertFalse(path.exists())
            answers = []
            def earlier_thread():
                try:
                    self.new_lock("thread.lock", "store").acquire(time.monotonic() + 2)
                except locks.LockOrderError:
                    answers.append(True)
            thread = threading.Thread(target=earlier_thread)
            thread.start()
            thread.join(2)
            self.assertEqual(answers, [True])
        finally:
            for lock in reversed(held):
                lock.release()
        lock = self.new_lock()
        with self.assertRaises(ValueError):
            with lock.held(time.monotonic() + 2):
                raise ValueError("made-up failure")
        self.assertFalse(lock.path.exists())

    def test_tc008_missing_store_bad_deadlines_and_partial_stale_lock(self):
        missing = Path(os.environ["CORTHEX_MEMORY_HOME"])
        with self.assertRaises(FileNotFoundError):
            locks.Lock(missing / "store.lock", "store", self.device).acquire(time.monotonic() + 2)
        self.assertFalse(missing.exists())
        for deadline in (float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                self.new_lock().acquire(deadline)
        with self.assertRaises(locks.LockBusy):
            self.new_lock().acquire(time.monotonic() - 1)
        path = self.folder / "partial.lock"
        path.write_bytes(b"{")
        past = time.time() - 11
        os.utime(str(path), (past, past))
        with self.new_lock("partial.lock").held(time.monotonic() + 2) as lock:
            lock.check()
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        if os.name != "nt":
            target, link = self.folder / "ordinary.txt", self.folder / "linked.lock"
            target.write_bytes(b"made-up unrelated content")
            link.symlink_to(target)
            with self.assertRaises(ValueError):
                self.new_lock(link.name).acquire(time.monotonic() + 2)
            self.assertEqual(target.read_bytes(), b"made-up unrelated content")

    def test_tc006_all_six_expiry_limits_follow_the_contract(self):
        for kind, limit in (("store", 120), ("curation", 600), ("sync", 600),
                            ("layer", 120), ("raw", 10), ("log", 10)):
            with self.subTest(kind=kind):
                path = self.folder / (kind + ".lock")
                self.seed(path)
                fresh = time.time() - limit + 1
                os.utime(str(path), (fresh, fresh))
                with self.assertRaises(locks.LockBusy):
                    self.new_lock(path.name, kind).acquire(time.monotonic() + 2, wait=False)
                expired = time.time() - limit - 1
                os.utime(str(path), (expired, expired))
                with self.new_lock(path.name, kind).held(time.monotonic() + 2) as lock:
                    lock.check()
                    stop = mock.Mock()
                    stop.wait.return_value = True
                    lock._heartbeat(stop)
                    refresh = None if kind in ("raw", "log") else 60 if kind in ("curation", "sync") else 30
                    stop.wait.assert_called_once_with(refresh)

    @unittest.skipUnless(hasattr(os, "fork"), "fork inheritance applies only on POSIX")
    def test_tc008_forked_child_has_its_own_order_and_cannot_release_parent(self):
        lock = self.new_lock("parent.lock", "log")
        with lock.held(time.monotonic() + 5):
            self.context = multiprocessing.get_context("fork")
            connection, process = self.start(forked_holder, lock, str(self.folder / "child.lock"), self.device)
            self.assertTrue(self.receive(connection))
            process.join(10)
            self.assertEqual(process.exitcode, 0)
            lock.check()

if __name__ == "__main__":
    unittest.main()
