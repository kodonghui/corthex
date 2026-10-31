"""TC-330 maintenance guards; TC-058 still needs the real start worker."""
import json
import multiprocessing
import os
import stat
import subprocess
import time
from pathlib import Path
from unittest import mock

from test_memory_store import AT, StoreCase
from memory_lib import base, cleanup, files, locks, raw_log, store, worker_support
from memory_lib import clock as memory_clock


def hold(connection, path, kind, device):
    with locks.Lock(Path(path), kind, device).held(memory_clock.now() + 10):
        connection.send(True)
        connection.recv()
    connection.close()


class CleanupTest(StoreCase):
    def setUp(self):
        super().setUp()
        self.worker = worker_support.WorkerStore()
        self.now = time.time_ns() // 1000000000 * 1000000000
        frozen = mock.patch.object(cleanup.time, "time_ns", return_value=self.now)
        frozen.start()
        self.addCleanup(frozen.stop)
        self.project = self.root / "projects" / "sample"
        base.private_directory(self.project / "raw")
        self.log = raw_log.log_name("codex", "made-up")
        self.entry = {"id": "e_000000000000", "seq": 1, "at": AT, "host": "codex",
                      "session": "made-up", "kind": "prompt", "speaker": "user", "turn": 1, "text": "fixture"}

    def artifact(self, name, age=661, data=b"fixture"):
        path = self.root / name
        base.private_directory(path.parent)
        path.write_bytes(data)
        when = self.now - age * 1000000000
        os.utime(str(path), ns=(when, when))
        return path

    def project_cleanup(self, seconds=5):
        deadline = memory_clock.now() + seconds
        with self.worker.lease(self.project / "curation.lock", "curation", deadline) as lease:
            return cleanup.clean_project(self.worker, "sample", lease, deadline)

    def raw_pair(self, data):
        primary = self.artifact("projects/sample/raw/" + self.log + ".jsonl", data=data)
        return primary, self.artifact(primary.relative_to(self.root).as_posix() + ".bak")

    def alias(self, link, target, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except OSError:
            if os.name != "nt" or not directory:
                self.skipTest("symbolic links unavailable")
            command = Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe"
            result = subprocess.run([str(command), "/d", "/c", "mklink", "/J", str(link), str(target)],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            if result.returncode:
                self.skipTest("directory aliases unavailable")

    def test_tc330_temp_age_names_and_unsupported_families(self):
        paths = [self.artifact("store.json.%s.tmp" % token, age)
                 for token, age in (("aaaaaaaa", 540), ("bbbbbbbb", 600),
                                    ("cccccccc", 660), ("dddddddd", -60))]
        unknown = [self.artifact(name) for name in ("other.abcdefgh.tmp", "store.json.unowned.tmp",
                   "projects/sample/layer/state.json.abcdefgh.tmp", "curation.json.bak")]
        self.assertEqual(cleanup.clean_store(self.worker, memory_clock.now() + 5), 1)
        self.assertEqual([p.exists() for p in paths], [True, True, False, True])
        self.assertTrue(all(p.exists() for p in unknown))

    def test_tc330_raw_inventory_is_linear_and_still_cleans_all_logs(self):
        raw = self.project / "raw"
        healthy = {raw / (raw_log.log_name("codex", "healthy-%d" % n) + ".jsonl")
                   for n in range(200)}
        for path in healthy:
            self.artifact(path.relative_to(self.root).as_posix(), data=b"")
        for number in range(20):
            name = raw_log.log_name("codex", "made-up-%d" % number)
            self.artifact("projects/sample/raw/" + name + ".jsonl.abcdefgh.tmp")
            self.artifact("projects/sample/raw/" + name + ".jsonl.bak.abcdefgh.tmp")
            self.artifact("projects/sample/raw/" + name + ".lock." + "a" * 32 + ".stale")
        original, scans = Path.iterdir, []
        def inventory(path):
            if path == self.project / "raw":
                scans.append(path)
            return original(path)
        with mock.patch.object(Path, "iterdir", inventory):
            self.project_cleanup(30)
        self.assertLessEqual(len(scans), 2)
        self.assertEqual(set(raw.iterdir()), healthy)

    def test_tc330_only_valid_supported_primary_allows_backup_deletion(self):
        configuration = self.root / "configuration.json"
        for content, expected in ((b"{}", False), (b"{", True), (b'{"unknown":1}', True), (None, True)):
            with self.subTest(content=content):
                if content is None:
                    configuration.unlink()
                else:
                    configuration.write_bytes(content)
                backup = self.artifact("configuration.json.bak")
                cleanup.clean_store(self.worker, memory_clock.now() + 5)
                self.assertEqual(backup.exists(), expected)

    def test_tc330_inaccessible_primary_keeps_backup_without_restoring(self):
        primary = self.artifact("configuration.json", data=b"{}")
        backup = self.artifact("configuration.json.bak", data=b'{"retention":{"days":7}}')
        original = self.worker.fence.read
        def denied(path, deadline):
            if path == primary:
                raise PermissionError("fixture")
            return original(path, deadline)
        with mock.patch.object(self.worker.fence, "read", denied), mock.patch.object(files, "_WINDOWS", False):
            cleanup.clean_store(self.worker, memory_clock.now() + 5)
        self.assertEqual(primary.read_bytes(), b"{}")
        self.assertTrue(backup.exists())

    def test_tc330_raw_backup_requires_every_complete_typed_line(self):
        valid = json.dumps(self.entry).encode() + b"\n"
        for data, remains in ((valid, False), (valid.rstrip(), True), (valid + b"bad\n", True),
                              (b'{"seq":1,"seq":2}\n', True), (b"{}\n", True), (b"\xff\n", True)):
            with self.subTest(data=data[:25]):
                primary, backup = self.raw_pair(data)
                self.project_cleanup()
                self.assertEqual(backup.exists(), remains)
                self.assertEqual(primary.read_bytes(), data)

    def test_tc330_raw_line_ceiling_keeps_damage_but_accepts_large_valid_line(self):
        value = dict(self.entry, text="\x00" * (512 * 1024))
        _, backup = self.raw_pair(json.dumps(value).encode() + b"\n")
        self.project_cleanup()
        self.assertFalse(backup.exists())
        valid = json.dumps(self.entry).encode() + b"\n"
        _, backup = self.raw_pair(b" " * (cleanup.LINE_BYTES - len(valid) + 2) + valid)
        self.project_cleanup()
        self.assertTrue(backup.exists())

    def test_tc330_stale_names_age_and_c1_log_scope(self):
        old = self.artifact("logs/failures.lock." + "a" * 32 + ".stale")
        keep = [self.artifact(name, age) for name, age in (
            ("logs/hooks.lock." + "b" * 32 + ".stale", 600),
            ("logs/usage.lock." + "c" * 32 + ".stale", 661), ("logs/failures.lock.unknown.stale", 661))]
        self.assertEqual(cleanup.clean_logs(self.worker, memory_clock.now() + 5), 1)
        self.assertFalse(old.exists())
        self.assertTrue(all(p.exists() for p in keep))

    def test_tc330_real_foreign_layer_and_raw_writers_keep_artifacts(self):
        for kind, path in (("layer", self.project / "layer.lock"),
                           ("raw", self.project / "raw" / (self.log + ".lock"))):
            with self.subTest(kind=kind):
                candidate = self.artifact("projects/sample/raw/" + self.log + ".jsonl.abcdefgh.tmp")
                parent, child = multiprocessing.Pipe()
                process = multiprocessing.get_context("spawn").Process(
                    target=hold, args=(child, str(path), kind, self.worker.device))
                process.start()
                child.close()
                try:
                    self.assertTrue(parent.poll(10))
                    self.assertTrue(parent.recv())
                    self.project_cleanup()
                    self.assertTrue(candidate.exists())
                finally:
                    if process.is_alive():
                        parent.send(True)
                    process.join(10)
                    if process.is_alive():
                        process.terminate()
                        process.join(5)
                    parent.close()
                self.assertEqual(process.exitcode, 0)

    def test_tc330_candidate_identity_rechecked_before_unlink(self):
        candidate = self.artifact("store.json.abcdefgh.tmp")
        original, seen = self.worker.fence.check, []
        def replace(path):
            if path == candidate:
                seen.append(path)
                if len(seen) == 2:
                    candidate.write_bytes(b"new fixture")
            return original(path)
        with mock.patch.object(self.worker.fence, "check", replace):
            cleanup.clean_store(self.worker, memory_clock.now() + 5)
        self.assertEqual(candidate.read_bytes(), b"new fixture")

    def test_tc330_expected_device_precedes_primary_and_backup_recovery_writes(self):
        for backup_only in (False, True):
            if backup_only:
                (self.root / "store.json").rename(self.root / "store.json.bak")
            before = self.snapshot()
            with self.assertRaises(locks.LostLock):
                worker_support.WorkerStore(expected_device="d_zzzzzzzzzzzz")
            self.assertEqual(self.snapshot(), before)

    def test_tc330_matching_backup_recovers_and_no_directories_are_provisioned(self):
        (self.root / "store.json").rename(self.root / "store.json.bak")
        memory = worker_support.WorkerStore(expected_device=self.header["device"])
        self.assertEqual(memory.device, self.header["device"])
        missing = self.folder / "absent"
        with self.assertRaises(store.StoreUnavailable):
            worker_support.WorkerStore(missing)
        self.assertFalse(missing.exists())

    def test_tc330_opaque_damaged_and_invalid_gates_write_nothing(self):
        path = self.root / "store.json"
        for data in (b'{"format":2}', b'{"format":1,"migrating":{}}', b"{"):
            path.write_bytes(data)
            before = self.snapshot()
            with self.assertRaises(store.StoreUnavailable):
                worker_support.WorkerStore()
            self.assertEqual(self.snapshot(), before)
        path.write_bytes(base.json_bytes(self.header, "TBL-001"))
        self.artifact("configuration.json", data=b'{"unknown":1}')
        before = self.snapshot()
        with self.assertRaises(store.configuration.ConfigurationInvalid):
            worker_support.WorkerStore()
        self.assertEqual(self.snapshot(), before)

    def test_tc330_release_failure_waits_for_outer_lease_and_keeps_phase_step(self):
        original = locks.Lock._release
        def release(lease, deadline):
            if lease.policy == locks.POLICIES["layer"]:
                raise OSError("private-fixture")
            return original(lease, deadline)
        deadline = memory_clock.now() + 5
        with mock.patch.object(locks.Lock, "_release", release):
            with self.worker.lease(self.project / "curation.lock", "curation", deadline, "retention"):
                with self.worker.lease(self.project / "layer.lock", "layer", deadline, "retention"):
                    pass
                self.assertEqual(list((self.root / "logs").iterdir()), [])
        rows = [json.loads(p.read_text(encoding="utf-8")) for p in (self.root / "logs").glob("*.jsonl")]
        self.assertEqual([(r["step"], r["error"]) for r in rows], [("retention", "OSError")])

    def test_tc330_replacement_store_blocks_config_recovery_and_diagnostics(self):
        primary = self.artifact("configuration.json", data=b"{")
        backup = self.artifact("configuration.json.bak", data=b"{}")
        path = self.root / "store.json"
        old = path.stat()
        value = dict(self.header, release="0.2.1")
        path.write_bytes(base.json_bytes(value, "TBL-001"))
        os.utime(str(path), ns=(old.st_atime_ns, old.st_mtime_ns))
        with self.assertRaises(locks.LostLock):
            self.worker.configuration(deadline=memory_clock.now() + 5)
        self.assertFalse(self.worker.failure(ValueError("private-fixture")))
        self.assertEqual(primary.read_bytes(), b"{")
        self.assertTrue(backup.exists())
        self.assertEqual(list((self.root / "logs").iterdir()), [])

    def test_tc330_token_loss_during_fingerprint_stops_unlink(self):
        candidate = self.artifact("store.json.abcdefgh.tmp")
        deadline = memory_clock.now() + 5
        with self.worker.lease(self.root / "store.lock", "store", deadline) as lease:
            original = self.worker.logger._stamp
            def lost(path, deadline=None):
                result = original(path, deadline)
                value = json.loads(lease.path.read_text(encoding="utf-8"))
                value["token"] = "f" * 32
                lease.path.write_text(json.dumps(value), encoding="utf-8")
                return result
            with mock.patch.object(self.worker.logger, "_stamp", lost), self.assertRaises(locks.LostLock):
                cleanup.artifacts(self.worker, self.root / "store.json", (lease,), deadline, store._record)
        self.assertTrue(candidate.exists())

    def test_tc330_alias_candidates_are_preserved(self):
        outside = self.folder / "outside"
        outside.mkdir()
        target = outside / "fixture"
        target.write_bytes(b"outside fixture")
        candidate = self.root / "store.json.abcdefgh.tmp"
        self.alias(candidate, target)
        cleanup.clean_store(self.worker, memory_clock.now() + 5)
        self.assertTrue(candidate.is_symlink())

    def test_tc330_directory_alias_log_parent_is_never_followed(self):
        outside = self.folder / "outside"
        outside.mkdir()
        target = outside / "fixture"
        target.write_bytes(b"outside fixture")
        (self.root / "logs").rename(self.root / "old-logs")
        self.alias(self.root / "logs", outside, True)
        self.assertFalse(self.worker.failure(ValueError("private-fixture")))
        self.assertEqual([p.name for p in outside.iterdir()], ["fixture"])
        self.assertEqual(target.read_bytes(), b"outside fixture")

    def test_tc330_outside_paths_and_invalid_curation_handles_are_refused(self):
        with self.assertRaises(worker_support.UnsafePath):
            self.worker.fence.check(self.folder / "outside")
        path = self.project / "curation.lock"
        deadline = memory_clock.now() + 5
        for acquired in (self.worker.lease(path, "raw", deadline),
                         locks.Lock(path, "curation", self.worker.device).held(deadline)):
            with acquired as lease:
                before = self.snapshot()
                with self.assertRaises(locks.LostLock):
                    cleanup.clean_project(self.worker, "sample", lease, deadline)
                self.assertEqual(self.snapshot(), before)

    def test_tc330_budget_expiring_in_last_target_check_keeps_candidate(self):
        target = self.artifact("store.json.abcdefgh.tmp")
        original, seen, limit = self.worker.fence.check, [], memory_clock.now() + 5
        current = [limit - 1]
        def checked(path):
            if path == target:
                seen.append(path)
                if len(seen) == 2:
                    current[0] = limit
            return original(path)
        with mock.patch.object(self.worker.fence, "check", checked), \
                mock.patch.object(memory_clock, "now", side_effect=lambda: current[0]), self.assertRaises(locks.LockBusy):
            cleanup.clean_store(self.worker, limit)
        self.assertTrue(target.exists())

    def test_tc330_guarded_reader_rechecks_policy_on_windows_retry(self):
        primary = self.artifact("configuration.json", data=b"{}")
        original_check, original_open, reads, checks = self.worker.fence.check, Path.open, [], []
        def policy(path):
            if path == primary:
                checks.append(path)
                if len(checks) > 1:
                    raise worker_support.UnsafePath()
            return original_check(path)
        def denied(path, *args, **kwargs):
            if path == primary:
                reads.append(path)
                raise PermissionError("fixture")
            return original_open(path, *args, **kwargs)
        with mock.patch.object(self.worker.fence, "check", policy), mock.patch.object(Path, "open", denied), \
                mock.patch.object(files, "_WINDOWS", True), self.assertRaises(worker_support.UnsafePath):
            self.worker.configuration(deadline=memory_clock.now() + 5)
        self.assertEqual(len(reads), 1)

    def test_tc330_deadline_lock_order_and_safe_diagnostic_boundary(self):
        before = self.snapshot()
        with self.assertRaises(locks.LockBusy):
            cleanup.clean_store(self.worker, memory_clock.now() - 1)
        self.assertEqual(self.snapshot(), before)
        deadline = memory_clock.now() + 5
        with self.worker.lease(self.project / "curation.lock", "curation", deadline):
            with self.assertRaises(locks.LockOrderError):
                cleanup.clean_store(self.worker, deadline)
            self.assertFalse(self.worker.failure(ValueError("private-fixture")))
        error = type("private-fixture", (ValueError,), {})("private-fixture")
        self.assertTrue(self.worker.failure(error))
        lines = b"".join(p.read_bytes() for p in (self.root / "logs").glob("*.jsonl"))
        self.assertNotIn(b"private-fixture", lines)
        record = json.loads(lines)
        self.assertEqual((record["step"], record["error"]), ("restore", "ValueError"))
