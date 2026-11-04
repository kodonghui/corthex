"""TC-336 direct foundation evidence; retention and actual starts stay later."""
import contextlib
import copy
import json
import multiprocessing
import os
from pathlib import Path
from unittest import mock

from test_memory_store import AT, StoreCase
import test_memory_cleanup as cleanup_tests
from memory_lib import base, cleanup, curation, files, locks, raw_log, raw_rewrite, store, worker_support
from memory_lib import clock


def append_once(connection, folder):
    memory = worker_support.WorkerStore(Path(folder))
    recorded = raw_log.RawLog(memory, "sample", "codex", "fixture").append(
        "prompt", raw_log.prepare("late 가나다"), diagnostic_deadline=clock.now() + 5)
    connection.send((recorded.outcome, recorded.entry))
    connection.close()


class RawRewriteTest(StoreCase):
    def setUp(self):
        super().setUp()
        self.worker = worker_support.WorkerStore()
        self.root = self.worker.folder
        self.project = self.root / "projects" / "sample"
        base.private_directory(self.project / "raw")
        base.private_directory(self.project / "unprocessed")
        self.log = raw_log.log_name("codex", "fixture")
        self.path = self.project / "raw" / (self.log + ".jsonl")
        self.record = self.project / "curation.json"
        self.document = {"logs": {self.log: 6, "codex-0000000000000000": 4}, "applies": 8,
                         "recent": [{"at": AT, "kind": "curate", "result": "ok", "applied": 3,
                                     "dropped": 1, "state": "kept"},
                                    {"at": AT, "kind": "consolidate", "result": "failed", "error": "network"}],
                         "failures": {"count": 2, "log": self.log, "turn": 1},
                         "consolidation": {"last": AT, "due": AT, "failures": 2},
                         "stopped": {"at": AT, "by": "curate", "errors": ["refusal", "PermissionError"]},
                         "rebuilt": AT}
        self.original_record = base.json_bytes(self.document, "TBL-009")
        self.record.write_bytes(self.original_record)
        self.entries = [self.entry(n) for n in (1, 2, 3)]
        self.original = b"".join(self.encoded(e) for e in self.entries)
        self.path.write_bytes(self.original)

    def entry(self, seq):
        return {"id": "e_" + str(seq).zfill(12), "seq": seq, "turn": seq, "at": AT,
                "host": "codex", "session": "fixture", "kind": "prompt", "speaker": "user",
                "text": "entry-%d" % seq}

    @staticmethod
    def encoded(entry):
        return base.json_bytes(entry, "TBL-007", compact=True)

    def rewrite(self, keep, after=None):
        deadline = clock.now() + 30
        with self.worker.lease(self.project / "curation.lock", "curation", deadline) as owner:
            return raw_rewrite.rewrite(self.worker, "sample", owner, self.log, keep, deadline, after)

    def progress(self):
        return curation.parse(self.record.read_bytes())

    def unchanged_metadata(self, expected):
        actual = self.progress()
        actual["logs"] = expected["logs"]
        self.assertEqual(actual, expected)

    @contextlib.contextmanager
    def held_raw(self):
        context = multiprocessing.get_context("spawn")
        connection, child = context.Pipe()
        process = context.Process(target=cleanup_tests.hold, args=(
            child, str(self.path.with_suffix(".lock")), "raw", self.worker.device))
        process.start()
        child.close()
        try:
            self.assertTrue(connection.poll(10))
            self.assertTrue(connection.recv())
            yield connection, process
        finally:
            if process.is_alive():
                try:
                    connection.send("release")
                except (BrokenPipeError, EOFError, OSError):
                    pass
            process.join(10)
            if process.is_alive():
                process.terminate()
                process.join(10)
            connection.close()

    def test_tc336_staged_rewrite_retries_a_transient_raw_holder(self):
        create, attempted = locks.Lock._create, []
        with self.held_raw() as (connection, process):
            def release_after_collision(lease):
                result = create(lease)
                if lease.path == self.path.with_suffix(".lock") and not result and not attempted:
                    attempted.append(True)
                    connection.send("release")
                    process.join(10)
                    self.assertEqual(process.exitcode, 0)
                return result
            # Freeze only the parent clock while the real child hands off;
            # scheduler latency must not decide this retry behaviour check.
            with mock.patch.object(locks.Lock, "_create", release_after_collision), mock.patch.object(
                    clock, "now", return_value=clock.now()):
                result = self.rewrite(lambda entry: entry["seq"] > 1)
        self.assertTrue(attempted)
        self.assertEqual((result.kept, result.removed), (2, 1))
        self.assertEqual(self.path.read_bytes(), b"".join(self.encoded(e) for e in self.entries[1:]))

    def test_tc336_busy_raw_defers_with_phase_time_remaining(self):
        started = clock.now()
        current = [started]
        def now():
            current[0] += 0.001
            return current[0]
        with self.held_raw(), mock.patch.object(clock, "now", side_effect=now), mock.patch.object(
                locks.time, "sleep"):
            with self.assertRaises(locks.LockBusy):
                self.rewrite(lambda entry: entry["seq"] > 1)
        self.assertLess(current[0] - started, 5)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(self.record.read_bytes(), self.original_record)

    def test_tc336_canonical_lease_order_is_process_wide_across_roots(self):
        other = self.folder / "other-memory"
        base.private_directory(other / "logs")
        files.write_json(other / "store.json", self.header, "TBL-001")
        earlier, later = sorted((self.root, other), key=lambda path: path.as_posix().casefold())
        makers = (
            lambda folder: store.MemoryStore(folder)._lock(folder / "store.lock", "store", self.header["device"]),
            lambda folder: worker_support.WorkerStore(folder)._lock(folder / "store.lock", "store", self.header["device"]),
            lambda folder: locks.Lock(folder / "store.lock", "store", self.header["device"]),
        )
        for number, make in enumerate(makers):
            with self.subTest(constructor=number):
                with make(later).held(clock.now() + 5):
                    with self.assertRaises(locks.LockOrderError):
                        with make(earlier).held(clock.now() + 5):
                            pass
                    self.assertFalse((earlier / "store.lock").exists())
                with make(earlier).held(clock.now() + 5):
                    with make(later).held(clock.now() + 5):
                        self.assertTrue((earlier / "store.lock").exists())
                        self.assertTrue((later / "store.lock").exists())

    def test_tc336_canonical_lease_order_preserves_relative_separator_order(self):
        earlier = self.root / "a" / "x.lock"
        later = self.root / "a0" / "y.lock"
        base.private_directory(earlier.parent)
        base.private_directory(later.parent)
        make = lambda path: self.worker._lock(path, "raw", self.header["device"])
        with make(later).held(clock.now() + 5):
            with self.assertRaises(locks.LockOrderError):
                with make(earlier).held(clock.now() + 5):
                    pass
        with make(earlier).held(clock.now() + 5):
            with make(later).held(clock.now() + 5):
                self.assertTrue(earlier.exists())
                self.assertTrue(later.exists())

    def test_tc336_explicit_store_root_is_independent_of_invalid_default(self):
        with mock.patch.dict(os.environ, {"CORTHEX_MEMORY_HOME": "relative"}):
            with self.assertRaises(base.MemoryHomeInvalid):
                store.MemoryStore()
            supplied = store.MemoryStore(self.root)
            supplied.write_configuration({"temporary": True}, clock.now() + 5)
            bound = worker_support.WorkerStore(self.root)
            deadline = clock.now() + 5
            with bound.lease(self.project / "curation.lock", "curation", deadline) as owner:
                result = raw_rewrite.rewrite(bound, "sample", owner, self.log,
                                             lambda entry: entry["seq"] > 1, deadline)
        self.assertEqual((result.kept, result.removed), (2, 1))
        self.assertEqual(self.path.read_bytes(), b"".join(self.encoded(e) for e in self.entries[1:]))

    def test_tc336_nonempty_typed_metadata_round_trips_without_defaults(self):
        self.assertEqual(curation.parse(self.original_record), self.document)
        minimum = {"logs": {}, "applies": 0, "recent": [], "consolidation": {"failures": 0}}
        self.assertEqual(curation.parse(base.json_bytes(minimum, "TBL-009")), minimum)
        self.assertEqual(self.record.read_bytes(), self.original_record)

    def test_tc336_invalid_nested_records_and_unknown_fields_are_rejected(self):
        variants = [("applies", True), ("applies", -1), ("logs", []),
                    ("logs", {"../outside": 1}), ("recent", self.document["recent"] * 6),
                    ("recent", [{"at": AT, "kind": "curate"}]),
                    ("recent", [{"at": AT, "kind": "curate", "result": "ok", "applied": False}]),
                    ("recent", [{"at": AT, "kind": "curate", "result": "ok", "error": "private text"}]),
                    ("consolidation", {"failures": 0, "last": "2026-99-99T00:00:00.000Z"}),
                    ("failures", {"count": 1, "log": self.log, "turn": 0}),
                    ("stopped", {"at": AT, "by": "curate", "errors": "refusal"}),
                    ("rebuilt", AT[:-1]), ("unknown", 1)]
        for field, value in variants:
            with self.subTest(field=field, value=value):
                document = copy.deepcopy(self.document)
                document[field] = value
                with self.assertRaises(ValueError):
                    curation.parse(base.json_bytes(document, "TBL-009"))
        for invalid in (b'{}', b'{"applies":NaN}', b'{"logs":{},"logs":{}}'):
            with self.assertRaises(ValueError):
                curation.parse(invalid)

    def test_tc336_filter_preserves_bytes_fields_and_lowers_progress(self):
        result = self.rewrite(lambda e: e["seq"] == 1)
        self.assertEqual(self.path.read_bytes(), self.encoded(self.entries[0]))
        self.assertEqual((result.kept, result.removed, result.damaged, result.deleted), (1, 2, 0, False))
        self.assertEqual(result.turns, frozenset({1}))
        self.assertEqual(self.progress()["logs"][self.log], 1)
        self.unchanged_metadata(self.document)
        self.assertFalse(list(self.project.rglob("*.bak")))
        self.assertFalse(list(self.project.rglob("*.tmp")))

    def test_tc336_readable_curation_backup_restores_under_matching_leases(self):
        self.record.with_name("curation.json.bak").write_bytes(self.original_record)
        self.record.write_bytes(b"{")
        result = self.rewrite(lambda e: True)
        self.assertEqual(result.kept, 3)
        self.assertEqual(self.progress()["logs"][self.log], 3)
        self.unchanged_metadata(self.document)
        self.assertFalse(self.record.with_name("curation.json.bak").exists())
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_tc336_unrecoverable_progress_never_guesses_or_creates_directories(self):
        for value in (None, b"{", b'{"logs":{}}'):
            with self.subTest(value=value):
                if value is None:
                    self.record.unlink()
                else:
                    self.record.write_bytes(value)
                before = {p.relative_to(self.root) for p in self.root.rglob("*") if p.is_dir()}
                with self.assertRaises((FileNotFoundError, ValueError)):
                    self.rewrite(lambda e: False)
                self.assertEqual(self.path.read_bytes(), self.original)
                self.assertEqual(self.record.exists(), value is not None)
                self.assertEqual(before, {p.relative_to(self.root) for p in self.root.rglob("*") if p.is_dir()})

    def test_tc336_deletion_lowers_to_zero_before_unlink_and_only_then_removes_key(self):
        original, observed = Path.unlink, []
        unowned = self.path.with_name(self.path.name + ".unowned.tmp")
        unowned.write_bytes(b"keep")
        def unlink(path, *args, **kwargs):
            if path == self.path:
                observed.append(self.progress()["logs"][self.log])
                self.assertTrue(path.exists())
            return original(path, *args, **kwargs)
        with mock.patch.object(Path, "unlink", unlink):
            result = self.rewrite(lambda e: False)
        self.assertEqual(observed, [0])
        self.assertTrue(result.deleted)
        self.assertNotIn(self.log, self.progress()["logs"])
        self.assertFalse(self.path.exists())
        self.assertEqual(unowned.read_bytes(), b"keep")

    def test_tc336_interruption_after_progress_before_move_only_recurates(self):
        backup = files._backup
        def stop(path, *args, **kwargs):
            if path == self.path:
                self.assertEqual(self.progress()["logs"][self.log], 1)
                raise RuntimeError("fixture stop")
            return backup(path, *args, **kwargs)
        with mock.patch.object(files, "_backup", stop), self.assertRaises(RuntimeError):
            self.rewrite(lambda e: e["seq"] == 1)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(self.progress()["logs"][self.log], 1)
        self.assertFalse(list(self.project.rglob("*.tmp")))

    def test_tc336_interruption_after_deletion_cannot_count_reused_seq_as_processed(self):
        write, calls = curation.write, []
        def stop(*args, **kwargs):
            calls.append(True)
            if len(calls) == 2:
                self.assertFalse(self.path.exists())
                raise RuntimeError("fixture stop")
            return write(*args, **kwargs)
        with mock.patch.object(curation, "write", stop), self.assertRaises(RuntimeError):
            self.rewrite(lambda e: False)
        self.assertEqual(self.progress()["logs"][self.log], 0)
        added = raw_log.RawLog(self.worker, "sample", "codex", "fixture").append(
            "prompt", raw_log.prepare("new"), diagnostic_deadline=clock.now() + 5)
        self.assertEqual(added.outcome, "ok")
        self.assertEqual(added.entry["seq"], 1)
        self.assertGreater(added.entry["seq"], self.progress()["logs"][self.log])

    def test_tc336_actual_child_append_during_build_is_carried_byte_for_byte(self):
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        process = context.Process(target=append_once, args=(child, str(self.root)))
        received = []
        def keep(entry):
            if not received:
                process.start()
                self.assertTrue(parent.poll(15))
                received.append(parent.recv())
                process.join(15)
                self.assertEqual(process.exitcode, 0)
            return False
        try:
            result = self.rewrite(keep)
            self.assertEqual(received[0][0], "ok")
            self.assertEqual(received[0][1]["seq"], 4)
            self.assertEqual(self.path.read_bytes(), self.encoded(received[0][1]))
            self.assertEqual((result.kept, result.removed, result.deleted), (1, 3, False))
            self.assertEqual(self.progress()["logs"][self.log], 0)
        finally:
            if process.is_alive():
                process.terminate()
                process.join(5)
            parent.close()
            child.close()

    def test_tc336_snapshot_in_the_middle_of_an_append_keeps_its_original_tail(self):
        late = self.encoded(self.entry(4))
        half = len(late) // 2
        self.path.write_bytes(self.original + late[:half])
        finished = []
        def keep(entry):
            if not finished:
                with self.worker.lease(self.path.with_suffix(".lock"), "raw", clock.now() + 5):
                    with self.path.open("ab") as stream:
                        stream.write(late[half:])
                finished.append(True)
            return False
        result = self.rewrite(keep)
        self.assertEqual(self.path.read_bytes(), late)
        self.assertEqual((result.kept, result.damaged, result.deleted), (1, 0, False))

    def test_tc336_changed_prefix_with_identical_stat_is_refused(self):
        info, changed = self.path.stat(), []
        replaced = self.original.replace(b"entry-1", b"alter-1")
        def keep(entry):
            if not changed:
                self.path.write_bytes(replaced)
                os.utime(str(self.path), ns=(info.st_atime_ns, info.st_mtime_ns))
                changed.append(True)
            return True
        with self.assertRaises(locks.LostLock):
            self.rewrite(keep)
        self.assertEqual(self.path.read_bytes(), replaced)
        self.assertEqual(self.record.read_bytes(), self.original_record)

    def test_tc336_same_bytes_atomic_replacement_is_refused(self):
        changed, chunks = [], raw_rewrite._chunks
        def read(*args, **kwargs):
            yield from chunks(*args, **kwargs)
            # Windows forbids replacing an open file. Inject after this first
            # snapshot reader closes, before the final raw-lease verification.
            if not changed and kwargs.get("digest") is not None:
                other = self.path.with_name("external")
                other.write_bytes(self.original)
                os.replace(str(other), str(self.path))
                changed.append(True)
        with mock.patch.object(raw_rewrite, "_chunks", read), self.assertRaises(locks.LostLock):
            self.rewrite(lambda e: True)
        self.assertTrue(changed)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(self.record.read_bytes(), self.original_record)

    def test_tc336_store_replacement_during_temp_flush_stops_before_progress(self):
        sync, changed = files._sync, []
        def replace(fd):
            sync(fd)
            if not changed:
                (self.root / "store.json").write_bytes(base.json_bytes({**self.header, "device": "d_zzzzzzzzzzzz"}, "TBL-001"))
                changed.append(True)
        with mock.patch.object(files, "_sync", replace), self.assertRaises(locks.LostLock):
            self.rewrite(lambda e: True)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(self.record.read_bytes(), self.original_record)

    def _metadata_change_stops_raw_io(self, change, *, backup=False):
        original, opened, now = self.worker.fence.check, Path.open, clock.now
        target = self.path.with_name(self.path.name + ".bak") if backup else self.path
        if backup:
            self.path.rename(target)
        changed, payload_opens, expired = [], [], now() + 100
        def check(path):
            result = original(path)
            if (path == target and not changed and
                    any(lease.policy == locks.POLICIES["raw"] for lease in self.worker.held)):
                changed.append(True)
                if change == "lease":
                    (self.project / "curation.lock").unlink()
                elif change == "store":
                    other = self.root / "external-store"
                    other.write_bytes(base.json_bytes(self.header, "TBL-001"))
                    os.replace(str(other), str(self.root / "store.json"))
            return result
        def open_raw(path, *args, **kwargs):
            if path == target and (changed or backup):
                payload_opens.append(True)
            return opened(path, *args, **kwargs)
        expected = locks.LockBusy if change == "deadline" else locks.LostLock
        with mock.patch.object(self.worker.fence, "check", check), mock.patch.object(
                Path, "open", open_raw), mock.patch.object(
                clock, "now", side_effect=lambda: expired if changed and change == "deadline" else now()):
            with self.assertRaises(expected):
                self.rewrite(lambda entry: True)
        self.assertTrue(changed)
        self.assertEqual(payload_opens, [])
        self.assertEqual(target.read_bytes(), self.original)
        if backup:
            self.assertFalse(self.path.exists())
        self.assertEqual(self.record.read_bytes(), self.original_record)

    def test_tc336_lease_loss_during_raw_metadata_stops_before_raw_io(self):
        self._metadata_change_stops_raw_io("lease")

    def test_tc336_same_bytes_store_swap_during_raw_metadata_stops_before_raw_io(self):
        self._metadata_change_stops_raw_io("store")

    def test_tc336_expiry_during_raw_metadata_stops_before_raw_io(self):
        self._metadata_change_stops_raw_io("deadline")

    def test_tc336_backup_metadata_lease_loss_stops_before_backup_payload(self):
        self._metadata_change_stops_raw_io("lease", backup=True)

    def test_tc336_lease_loss_after_a_raw_chunk_stops_before_next_payload_read(self):
        payload = b"".join(self.encoded(self.entry(n)) for n in range(1, 1001))
        self.assertGreater(len(payload), worker_support.CHUNK)
        self.assertNotEqual(payload[worker_support.CHUNK - 1:worker_support.CHUNK], b"\n")
        self.path.write_bytes(payload)
        opened, reads, lost = Path.open, [], []
        class Incoming:
            def __init__(self, source):
                self.source = source
            def __enter__(self):
                self.source.__enter__()
                return self
            def __exit__(self, *args):
                return self.source.__exit__(*args)
            def __getattr__(self, name):
                return getattr(self.source, name)
            def read(self, size=-1):
                reads.append(size)
                return self.source.read(size)
        def opening(path, *args, **kwargs):
            source = opened(path, *args, **kwargs)
            return Incoming(source) if path == self.path else source
        def keep(entry):
            if not lost:
                (self.project / "curation.lock").unlink()
                lost.append(True)
            return True
        with mock.patch.object(Path, "open", opening), self.assertRaises(locks.LostLock):
            self.rewrite(keep)
        self.assertEqual(len(reads), 1)
        self.assertTrue(lost)
        self.assertEqual(self.path.read_bytes(), payload)
        self.assertEqual(self.record.read_bytes(), self.original_record)

    def test_tc336_path_prefix_cache_preserves_spelling_and_rechecks_root_identity(self):
        fence = self.worker.fence
        target = self.root / "KeepCASE"
        target.write_bytes(b"fixture")
        original, observed = Path.lstat, []
        def lstat(path, *args, **kwargs):
            observed.append(path)
            return original(path, *args, **kwargs)
        with mock.patch.object(Path, "lstat", lstat):
            for _ in range(2):
                self.assertEqual(fence.check(target).st_ino, target.stat().st_ino)
                self.assertEqual(observed[-1], target)
        for path in (self.root.with_name(self.root.name + "-other") / target.name,
                     Path("relative"), self.root / "nested" / ".." / target.name):
            with self.subTest(path=path), self.assertRaises(worker_support.UnsafePath):
                fence.check(path)
        retired = self.folder / "retired-memory"
        self.root.rename(retired)
        self.root.mkdir()
        with self.assertRaises(locks.LostLock):
            fence.check(target)
        self.assertEqual((retired / target.name).read_bytes(), b"fixture")

    def test_tc336_copy_fallback_rechecks_lease_after_open(self):
        opened, original, backup, copying = [], Path.open, files._backup, []
        def backing(path, *args, **kwargs):
            if path == self.path:
                copying.append(True)
            try:
                return backup(path, *args, **kwargs)
            finally:
                if path == self.path:
                    copying.pop()
        def replaced(path, *args, **kwargs):
            if copying and path == self.path and args and args[0] == "rb":
                opened.append(True)
                (self.project / "curation.lock").unlink()
            return original(path, *args, **kwargs)
        with mock.patch.object(files, "_backup", backing), mock.patch.object(files.os, "link", side_effect=OSError), mock.patch.object(Path, "open", replaced), self.assertRaises(locks.LostLock):
            self.rewrite(lambda e: e["seq"] == 1)
        self.assertEqual(len(opened), 1)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(self.progress()["logs"][self.log], 1)

    def test_tc336_expiry_during_last_temporary_path_check_stops_the_write(self):
        original, now = self.worker.fence.check, clock.now
        expired, limit = [], now() + 1
        def check(path):
            result = original(path)
            if path.name.endswith(".tmp"):
                expired.append(True)
            return result
        with mock.patch.object(self.worker.fence, "check", check), mock.patch.object(clock, "now", side_effect=lambda: limit + 100 if expired else now()), self.assertRaises(locks.LockBusy):
            self.rewrite(lambda e: True)
        self.assertTrue(expired)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(self.record.read_bytes(), self.original_record)

    def test_tc336_directory_alias_and_untracked_curation_are_refused(self):
        outside = self.root / "outside"
        self.project.rename(outside)
        cleanup_tests.CleanupTest.alias(self, self.project, outside, directory=True)
        with self.assertRaises(worker_support.UnsafePath):
            self.rewrite(lambda e: False)
        self.assertEqual((outside / "raw" / self.path.name).read_bytes(), self.original)
        deadline = clock.now() + 5
        foreign = locks.Lock(self.root / "foreign.lock", "curation", self.header["device"])
        with self.assertRaises(locks.LostLock):
            raw_rewrite.rewrite(self.worker, "other", foreign, self.log, lambda e: False, deadline)
        self.assertFalse((self.root / "projects" / "other").exists())

    def test_tc336_oversized_line_is_preserved_instead_of_classified_as_damage(self):
        huge = b"x" * (cleanup.LINE_BYTES + 1) + b"\n"
        self.path.write_bytes(huge)
        with self.assertRaises(raw_rewrite.OversizedLine):
            self.rewrite(lambda e: False)
        self.assertEqual(self.path.read_bytes(), huge)
        self.assertEqual(self.record.read_bytes(), self.original_record)

    def test_tc336_missing_raw_restores_backup_and_copy_fallback_remains_durable(self):
        backup = self.path.with_name(self.path.name + ".bak")
        self.path.rename(backup)
        with mock.patch.object(files.os, "link", side_effect=OSError):
            result = self.rewrite(lambda e: e["seq"] == 2)
        self.assertEqual(self.path.read_bytes(), self.encoded(self.entries[1]))
        self.assertEqual(result.kept, 1)
        self.assertFalse(backup.exists())
        self.assertFalse(list(self.project.rglob("*.tmp")))

    def test_tc336_after_callback_still_holds_all_matching_leases(self):
        calls = []
        def after(result, check):
            check()
            calls.append(result)
            self.assertEqual([lease.policy.rank for lease in self.worker.held], [1, 3, 4])
            self.assertFalse(self.path.with_name(self.path.name + ".bak").exists())
        result = self.rewrite(lambda e: True, after)
        self.assertEqual(calls, [result])
        self.assertEqual(self.worker.held, [])

    def test_tc336_failed_delete_keeps_zero_progress_until_a_real_deletion(self):
        unlink = Path.unlink
        def denied(path, *args, **kwargs):
            if path == self.path:
                raise PermissionError("fixture")
            return unlink(path, *args, **kwargs)
        with mock.patch.object(Path, "unlink", denied), mock.patch.object(files, "_WINDOWS", False), self.assertRaises(PermissionError):
            self.rewrite(lambda e: False)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(self.progress()["logs"][self.log], 0)
        self.assertTrue(self.rewrite(lambda e: False).deleted)
        self.assertNotIn(self.log, self.progress()["logs"])

    def test_tc336_bad_lines_are_counted_without_rolling_back_valid_raw_content(self):
        backup = self.path.with_name(self.path.name + ".bak")
        backup.write_bytes(self.encoded(self.entry(9)))
        self.path.write_bytes(b"not-json\n" + self.original + b'{"seq":NaN}\ncut')
        result = self.rewrite(lambda e: True)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual((result.kept, result.damaged), (3, 3))
        self.assertFalse(backup.exists())

    def test_tc336_lost_guard_cannot_flush_buffered_bytes_on_close(self):
        lost, observed = [], []
        def check():
            if lost:
                raise locks.LostLock()
        def chunks():
            yield b"synthetic payload"
            temporary = next(self.path.parent.glob(self.path.name + ".*.tmp"))
            observed.append((temporary, temporary.read_bytes()))
            lost.append(True)
            raise locks.LostLock()
        with self.assertRaises(locks.LostLock):
            files._temporary(self.path, chunks(), True, check, self.worker.fence.check)
        self.assertEqual(observed[0][1], b"synthetic payload")
        self.assertEqual(observed[0][0].read_bytes(), observed[0][1])

    def test_tc336_staging_replacement_after_progress_cannot_be_committed(self):
        for content in (b"foreign staging bytes", b""):
            with self.subTest(content=content):
                self.record.write_bytes(self.original_record)
                write, changed = curation.write, []
                def replaced(*args, **kwargs):
                    write(*args, **kwargs)
                    temporary = next(self.path.parent.glob(self.path.name + ".*.tmp"))
                    other = temporary.with_name("foreign-stage")
                    other.write_bytes(content)
                    os.replace(str(other), str(temporary))
                    changed.append(temporary)
                with mock.patch.object(curation, "write", replaced), self.assertRaises(RuntimeError):
                    self.rewrite(lambda e: e["seq"] == 1)
                self.assertEqual(self.path.read_bytes(), self.original)
                self.assertEqual(self.progress()["logs"][self.log], 1)
                self.assertEqual(changed[0].read_bytes(), content)
                changed[0].unlink()

    def test_tc336_suffix_rejects_an_open_descriptor_for_another_file(self):
        other = self.root / "foreign-stage"
        other.write_bytes(b"untouched")
        opened, added = Path.open, []
        def keep(entry):
            if not added:
                with self.worker.lease(self.path.with_suffix(".lock"), "raw", clock.now() + 5):
                    with self.path.open("ab") as target:
                        target.write(self.encoded(self.entry(4)))
                added.append(True)
            return entry["seq"] == 1
        def opening(path, *args, **kwargs):
            if path.suffix == ".tmp" and args and args[0] == "ab":
                return opened(other, *args, **kwargs)
            return opened(path, *args, **kwargs)
        with mock.patch.object(Path, "open", opening), self.assertRaises(RuntimeError):
            self.rewrite(keep)
        self.assertEqual(other.read_bytes(), b"untouched")
        self.assertEqual(self.path.read_bytes(), self.original + self.encoded(self.entry(4)))
        self.assertEqual(self.progress()["logs"][self.log], 1)

    def test_tc336_staging_truncation_during_backup_cannot_replace_raw(self):
        backup, changed = files._backup, []
        def truncate_after_backup(path, *args, **kwargs):
            result = backup(path, *args, **kwargs)
            if path == self.path:
                temporary = next(self.path.parent.glob(self.path.name + ".*.tmp"))
                before = temporary.stat().st_ino
                temporary.write_bytes(b"")
                self.assertEqual(temporary.stat().st_ino, before)
                changed.append(True)
            return result
        with mock.patch.object(files, "_backup", truncate_after_backup), self.assertRaises(RuntimeError):
            self.rewrite(lambda entry: entry["seq"] == 1)
        self.assertTrue(changed)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(self.progress()["logs"][self.log], 1)

    def test_tc336_staging_change_during_delete_cleanup_keeps_primary(self):
        iterdir, changed = Path.iterdir, []
        def alter_before_cleanup(path):
            if path == self.path.parent:
                candidates = [p for p in iterdir(path) if p.suffix == ".tmp"]
                self.assertEqual(len(candidates), 1)
                candidates[0].write_bytes(b"foreign staging content")
                changed.append(True)
            return iterdir(path)
        with mock.patch.object(Path, "iterdir", alter_before_cleanup), self.assertRaises(RuntimeError):
            self.rewrite(lambda entry: False)
        self.assertTrue(changed)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(self.progress()["logs"][self.log], 0)

    def test_tc336_second_raw_collision_keeps_raw_and_conservative_progress(self):
        write, blocker, entered = curation.write, self.held_raw(), []
        def hold_after_progress(*args, **kwargs):
            write(*args, **kwargs)
            blocker.__enter__()
            entered.append(True)
        try:
            with mock.patch.object(curation, "write", hold_after_progress), self.assertRaises(locks.LockBusy):
                self.rewrite(lambda entry: entry["seq"] == 1)
            self.assertEqual(self.path.read_bytes(), self.original)
            self.assertEqual(self.progress()["logs"][self.log], 1)
            self.unchanged_metadata(self.document)
        finally:
            if entered:
                blocker.__exit__(None, None, None)

    def test_tc336_new_append_between_raw_deletion_and_progress_cleanup_survives(self):
        write, recorded = curation.write, []
        def append_before_cleanup(memory, root, value, deadline):
            if self.log not in value["logs"]:
                result = raw_log.RawLog(self.worker, "sample", "codex", "fixture").append(
                    "prompt", raw_log.prepare("after deletion"), diagnostic_deadline=clock.now() + 5)
                self.assertEqual(result.outcome, "ok")
                recorded.append(result.entry)
            return write(memory, root, value, deadline)
        with mock.patch.object(curation, "write", append_before_cleanup):
            result = self.rewrite(lambda entry: False)
        self.assertTrue(result.deleted)
        self.assertEqual(recorded[0]["seq"], 1)
        self.assertEqual(self.path.read_bytes(), self.encoded(recorded[0]))
        self.assertNotIn(self.log, self.progress()["logs"])
        self.assertEqual(len(list((self.project / "unprocessed").iterdir())), 1)
