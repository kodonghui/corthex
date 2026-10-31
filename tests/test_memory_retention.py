"""TC-337 direct retention evidence; worker/start/status cases stay later."""
from datetime import datetime, timedelta, timezone
import json
import multiprocessing
import os
from pathlib import Path
import time
from unittest import mock

from test_memory_store import AT, StoreCase
import test_memory_cleanup as cleanup_tests
from memory_lib import base, clock, curation, files, locks, raw_log, raw_rewrite, retention, worker_support

NOW = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)


def append_loop(connection, folder, continuously):
    memory = worker_support.WorkerStore(Path(folder))
    log = raw_log.RawLog(memory, "sample", "codex", "retention-fixture")
    connection.send(True)
    acknowledged, skipped, number = [], 0, 0
    while True:
        if continuously:
            if connection.poll() and connection.recv() == "stop":
                connection.send((acknowledged, skipped))
                break
        elif connection.recv() == "stop":
            break
        number += 1
        result = log.append("prompt", raw_log.prepare("ack-%d 가나다" % number),
                            diagnostic_deadline=clock.now() + 3, when=NOW)
        if result.outcome == "ok":
            acknowledged.append(result.entry)
        elif result.outcome == "lock-busy":
            skipped += 1
        else:
            raise AssertionError(result.outcome)
        if continuously:
            time.sleep(.01)
        else:
            connection.send(result.entry)
    connection.close()


def hold_layer(connection, folder, device):
    path = Path(folder) / "projects" / "sample" / "layer.lock"
    with locks.Lock(path, "layer", device).held(clock.now() + 30):
        raw = path.parent / "raw" / (raw_log.log_name("codex", "retention-fixture") + ".jsonl")
        with locks.Lock(raw.with_suffix(".lock"), "raw", device).held(clock.now() + 30):
            entries = [json.loads(line) for line in raw.read_bytes().splitlines()]
            entries[-1]["text"] = "synthetic competing writer"
            raw.write_bytes(b"".join(base.json_bytes(e, "TBL-007", compact=True) for e in entries))
            connection.send(True)
            connection.recv()
    connection.close()


class RetentionTest(StoreCase):
    def setUp(self):
        super().setUp()
        self.worker = worker_support.WorkerStore()
        self.root = self.worker.folder
        self.project = self.root / "projects" / "sample"
        base.private_directory(self.project / "raw")
        base.private_directory(self.project / "unprocessed")
        self.log = raw_log.log_name("codex", "retention-fixture")
        self.path = self.project / "raw" / (self.log + ".jsonl")
        self.record = self.project / "curation.json"
        self.record.write_bytes(base.json_bytes({"logs": {self.log: 20}, "applies": 4,
            "recent": [], "consolidation": {"failures": 0}}, "TBL-009"))

    def entry(self, seq, days):
        return {"id": "e_" + str(seq).zfill(12), "seq": seq, "turn": seq,
                "at": base.utc_time(NOW - timedelta(days=days)), "host": "codex",
                "session": "retention-fixture", "kind": "prompt", "speaker": "user", "text": "fixture-%d" % seq}

    def write(self, entries):
        self.path.write_bytes(b"".join(base.json_bytes(e, "TBL-007", compact=True) for e in entries))

    def read(self):
        return [json.loads(line) for line in self.path.read_bytes().splitlines()]

    def apply(self, seconds=30):
        deadline = clock.now() + seconds
        with self.worker.lease(self.project / "curation.lock", "curation", deadline) as owner:
            return retention.retain_project(self.worker, "sample", owner, deadline, NOW)

    def child(self, target, *args):
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        process = context.Process(target=target, args=(child,) + args)
        process.start()
        child.close()
        self.assertTrue(parent.poll(20))
        self.assertIs(parent.recv(), True)
        return parent, process

    def finish(self, connection, process):
        connection.send("stop")
        process.join(20)
        self.assertFalse(process.is_alive())
        self.assertEqual(process.exitcode, 0)
        connection.close()

    def test_tc337_configured_cutoff_future_and_invalid_calendar_are_preserved(self):
        configuration = {"retention": {"days": 7}, "projects": {"sample": {"enabled": False, "since": AT}}}
        (self.root / "configuration.json").write_bytes(base.json_bytes(configuration, "TBL-002"))
        self.worker = worker_support.WorkerStore(self.root)
        entries = [self.entry(1, 8), self.entry(2, 7), self.entry(3, 6), self.entry(4, -1), self.entry(5, 1)]
        entries[-1]["at"] = "2026-99-99T00:00:00.000Z"
        self.write(entries)
        result = self.apply()
        self.assertEqual(self.read(), entries[1:])
        self.assertEqual((result["removed"], result["kept"], result["future"], result["unreadable_age"]), (1, 4, 1, 1))
        self.assertEqual(curation.parse(self.record.read_bytes())["applies"], 4)
        self.assertFalse(self.worker.held)
        notices = [json.loads(line) for path in (self.root / "logs").glob("failures-*.jsonl")
                   for line in path.read_bytes().splitlines()]
        self.assertEqual([(row["step"], row["error"], row["count"]) for row in notices],
                         [("retention", "future-entry", 1), ("retention", "ValueError", 1)])
        self.assertTrue(all(set(row) == {"at", "step", "error", "count"} for row in notices))

    def test_tc337_only_owned_markers_for_removed_turns_are_deleted(self):
        self.write([self.entry(1, 101), self.entry(2, 99)])
        folder = self.project / "unprocessed"
        removed = folder / ("20260722T120000Z." + self.log + ".1")
        kept = folder / ("20260724T120000Z." + self.log + ".2")
        unknown = [folder / ("20269999T120000Z." + self.log + ".1"), folder / "unowned",
                   folder / ("20260722T120000Z.codex-0000000000000000.1")]
        nonempty = folder / ("20260721T120000Z." + self.log + ".1")
        for path in [removed, kept] + unknown:
            path.write_bytes(b"")
        nonempty.write_bytes(b"unowned bytes")
        result = self.apply()
        self.assertFalse(removed.exists())
        self.assertTrue(kept.exists())
        self.assertTrue(all(path.exists() for path in unknown))
        self.assertEqual(nonempty.read_bytes(), b"unowned bytes")
        self.assertEqual(result["markers"], 1)

    def test_tc337_future_survivor_and_deleted_tail_allow_an_unprocessed_append(self):
        self.write([self.entry(1, -1), self.entry(20, 101)])
        result = self.apply()
        self.assertEqual((result["kept"], result["removed"], result["future"]), (1, 1, 1))
        recorded = raw_log.RawLog(self.worker, "sample", "codex", "retention-fixture").append(
            "prompt", raw_log.prepare("new after removed tail"), diagnostic_deadline=clock.now() + 5, when=NOW)
        self.assertEqual(recorded.outcome, "ok")
        self.assertEqual(recorded.entry["seq"], 2)
        self.assertLess(curation.parse(self.record.read_bytes())["logs"][self.log], recorded.entry["seq"])
        self.assertEqual(self.read()[-1], recorded.entry)

    def test_tc337_backup_damage_and_unrecoverable_progress_keep_their_boundaries(self):
        entries = [self.entry(1, 101), self.entry(2, 99)]
        self.write(entries)
        backup = self.path.with_name(self.path.name + ".bak")
        self.path.replace(backup)
        self.assertEqual(self.apply()["kept"], 1)
        self.assertFalse(backup.exists())
        self.assertEqual(self.read(), entries[1:])
        with self.path.open("ab") as target:
            target.write(b'{"cut":')
        self.assertEqual(self.apply()["damaged"], 1)
        self.assertEqual(self.read(), entries[1:])
        self.record.write_bytes(b"{")
        before = self.path.read_bytes()
        self.assertEqual(self.apply()["skipped"], 1)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.record.read_bytes(), b"{")
        notices = [json.loads(line) for path in (self.root / "logs").glob("failures-*.jsonl")
                   for line in path.read_bytes().splitlines()]
        self.assertIn(("restored", None), [(row["error"], row.get("count")) for row in notices])
        self.assertIn(("damaged-line", 1), [(row["error"], row.get("count")) for row in notices])

    def test_tc337_continuous_process_appends_survive_100_actual_rewrites(self):
        self.write([self.entry(1, 101), self.entry(2, 0)])
        connection, process = self.child(append_loop, str(self.root), True)
        successful = attempts = retention_skips = 0
        limit = time.monotonic() + 120
        try:
            while successful < 100 and attempts < 500 and time.monotonic() < limit:
                result = self.apply()
                self.assertEqual(result["files"] + result["skipped"], 1)
                successful += result["files"]
                retention_skips += result["skipped"]
                attempts += 1
        finally:
            connection.send("stop")
            ready = connection.poll(20)
            if ready:
                acknowledged, skipped = connection.recv()
            process.join(20)
            if process.is_alive():
                process.terminate()
                process.join(10)
            connection.close()
            self.assertTrue(ready)
            self.assertEqual(process.exitcode, 0)
        actual = self.read()
        print("RETENTION_STRESS " + json.dumps({"rewrites": successful, "attempts": attempts,
              "retention_skips": retention_skips, "acknowledged": len(acknowledged), "append_lock_skips": skipped}))
        self.assertEqual(successful, 100)
        self.assertGreater(len(acknowledged), 0)
        self.assertTrue(all(entry in actual for entry in acknowledged))
        self.assertGreaterEqual(skipped, 0)
        self.assertFalse(any(entry.get("text") == "fixture-1" for entry in actual))

    def test_tc337_100_process_appends_between_snapshot_and_delete_decision(self):
        connection, process = self.child(append_loop, str(self.root), False)
        original = raw_rewrite._chunks
        try:
            for _ in range(100):
                self.write([self.entry(1, 101)])
                appended = []
                def chunks(*args, **kwargs):
                    yield from original(*args, **kwargs)
                    if args[1] == self.path and kwargs.get("digest") is not None and not appended:
                        connection.send("append")
                        self.assertTrue(connection.poll(10))
                        appended.append(connection.recv())
                with mock.patch.object(raw_rewrite, "_chunks", chunks):
                    result = self.apply()
                self.assertIsNotNone(appended[0])
                self.assertEqual(self.read(), appended)
                self.assertEqual((result["removed"], result["kept"], result["skipped"]), (1, 1, 0))
                self.assertLess(curation.parse(self.record.read_bytes())["logs"][self.log], appended[0]["seq"])
        finally:
            self.finish(connection, process)

    def test_tc337_synthetic_competing_layer_writer_serializes_and_skips_quietly(self):
        self.write([self.entry(1, 101), self.entry(2, 99)])
        connection, process = self.child(hold_layer, str(self.root), self.worker.device)
        before = self.path.read_bytes()
        try:
            with mock.patch.object(self.worker, "failure") as failure:
                self.assertEqual(self.apply()["skipped"], 1)
                self.assertEqual(self.path.read_bytes(), before)
                failure.assert_not_called()
        finally:
            self.finish(connection, process)
        self.assertEqual(self.apply()["removed"], 1)
        expected = self.entry(2, 99)
        expected["text"] = "synthetic competing writer"
        self.assertEqual(self.read(), [expected])

    def test_tc337_selected_staging_batches_flush_before_the_raw_lease(self):
        entries = [self.entry(n, 1) for n in range(1, 1001)]
        self.write(entries)
        before = self.path.read_bytes()
        original, chunks = files._temporary, []
        def temporary(path, content, *args, **kwargs):
            if path != self.path:
                return original(path, content, *args, **kwargs)
            def measured():
                for chunk in content:
                    raw_held = any(lease.path == self.path.with_suffix(".lock") for lease in self.worker.held)
                    chunks.append((len(chunk), raw_held))
                    yield chunk
            return original(path, measured(), *args, **kwargs)
        with mock.patch.object(files, "_temporary", temporary):
            self.assertEqual(self.apply()["kept"], 1000)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(sum(size for size, _ in chunks), len(before))
        self.assertLessEqual(len(chunks), (len(before) + worker_support.CHUNK - 1) // worker_support.CHUNK)
        self.assertTrue(all(0 < size <= worker_support.CHUNK and not held for size, held in chunks))

    def test_tc337_daily_custom_period_and_exclusive_midnight_boundary(self):
        (self.root / "configuration.json").write_bytes(base.json_bytes({"retention": {"days": 7}}, "TBL-002"))
        self.worker = worker_support.WorkerStore(self.root)
        folder = self.root / "logs"
        old = [folder / "failures-2026-10-23.jsonl", folder / "hooks-2026-10-22.jsonl"]
        current = [folder / "failures-2026-10-24.jsonl", folder / "hooks-2026-10-23.jsonl"]
        for path in old + current:
            path.write_bytes(b"fixture\n")
        midnight = NOW.replace(hour=0)
        self.assertEqual(retention.retain_logs(self.worker, clock.now() + 5, midnight), 2)
        self.assertTrue(all(not path.exists() for path in old))
        self.assertTrue(all(path.exists() for path in current))

    def test_tc337_fresh_raw_and_log_leases_skip_without_diagnostics(self):
        self.write([self.entry(1, 101)])
        before = self.path.read_bytes()
        for kind, path in (("raw", self.path.with_suffix(".lock")), ("log", self.root / "logs" / "failures.lock")):
            connection, process = self.child(cleanup_tests.hold, str(path), kind, self.worker.device)
            try:
                with mock.patch.object(self.worker, "failure") as failure:
                    if kind == "raw":
                        self.assertEqual(self.apply()["skipped"], 1)
                        self.assertEqual(self.path.read_bytes(), before)
                    else:
                        self.assertEqual(retention.retain_logs(self.worker, clock.now() + 5, NOW), 0)
                    failure.assert_not_called()
            finally:
                self.finish(connection, process)

    def test_tc337_marker_hardlink_alias_and_replacement_are_preserved(self):
        self.write([self.entry(1, 101), self.entry(2, 99)])
        folder = self.project / "unprocessed"
        hardlink = folder / ("20260721T120000Z." + self.log + ".1")
        hardlink.write_bytes(b"")
        os.link(str(hardlink), str(folder / "unowned-hardlink"))
        alias = folder / ("20260722T120000Z." + self.log + ".1")
        target = self.root / "synthetic-marker-target"
        base.private_directory(target)
        cleanup_tests.CleanupTest.alias(self, alias, target, directory=True)
        replacement = folder / ("20260723T120000Z." + self.log + ".1")
        replacement.write_bytes(b"")
        original = retention._remove
        def replace(memory, path, info, check):
            if path == replacement:
                other = path.with_name("replacement-bytes")
                other.write_bytes(b"foreign marker")
                other.replace(path)
            return original(memory, path, info, check)
        with mock.patch.object(retention, "_remove", replace):
            self.assertEqual(self.apply()["markers"], 0)
        self.assertTrue(hardlink.exists())
        self.assertTrue(alias.exists())
        self.assertTrue(target.is_dir())
        self.assertEqual(replacement.read_bytes(), b"foreign marker")

    def test_tc337_windows_held_marker_is_retried_after_the_raw_file_is_gone(self):
        if os.name != "nt":
            self.skipTest("Windows held-marker sharing requires Windows")
        import ctypes
        self.write([self.entry(1, 101)])
        marker = self.project / "unprocessed" / ("20260722T120000Z." + self.log + ".1")
        marker.write_bytes(b"")
        create = ctypes.windll.kernel32.CreateFileW
        create.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p,
                           ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
        create.restype = ctypes.c_void_p
        close = ctypes.windll.kernel32.CloseHandle
        close.argtypes = [ctypes.c_void_p]
        handle = create(str(marker), 0x80000000, 1, None, 3, 0, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        try:
            self.assertEqual(self.apply()["skipped"], 1)
            self.assertFalse(self.path.exists())
            self.assertTrue(marker.exists())
            self.assertEqual(curation.parse(self.record.read_bytes())["logs"][self.log], 0)
        finally:
            self.assertTrue(close(handle))
        self.assertEqual(self.apply()["markers"], 1)
        self.assertFalse(marker.exists())
        self.assertFalse(self.path.exists())
        self.assertNotIn(self.log, curation.parse(self.record.read_bytes())["logs"])

    def test_tc337_daily_logs_require_the_whole_utc_day_and_known_families(self):
        folder = self.root / "logs"
        names = ["failures-2026-07-22.jsonl", "failures-2026-07-23.jsonl", "failures-2026-07-24.jsonl",
                 "hooks-2026-10-22.jsonl", "hooks-2026-10-23.jsonl", "hooks-2026-10-24.jsonl",
                 "usage-2020-01-01.jsonl", "failures-2026-99-99.jsonl", "hooks-9999-12-31.jsonl",
                 "failures-2020-01-01.jsonl.bak", "failures-unowned.jsonl"]
        for name in names:
            (folder / name).write_bytes(b"fixture\n")
        owned = [folder / (names[0] + suffix) for suffix in (".bak", ".abcdefgh.tmp", ".bak.ijklmnop.tmp")]
        for path in owned:
            path.write_bytes(b"owned expired bytes")
        unowned = folder / (names[0] + ".unowned.tmp")
        unowned.write_bytes(b"keep unknown artifact")
        linked = folder / "hooks-2020-01-01.jsonl"
        linked.write_bytes(b"keep primary")
        backup = linked.with_name(linked.name + ".bak")
        backup.write_bytes(b"foreign linked bytes")
        os.link(str(backup), str(folder / "foreign-log-hardlink"))
        removed = retention.retain_logs(self.worker, clock.now() + 10, NOW)
        self.assertEqual(removed, 2)
        self.assertFalse((folder / names[0]).exists())
        self.assertFalse((folder / names[3]).exists())
        self.assertTrue(all((folder / name).exists() for i, name in enumerate(names) if i not in (0, 3)))
        self.assertTrue(all(not path.exists() for path in owned))
        self.assertEqual(unowned.read_bytes(), b"keep unknown artifact")
        self.assertEqual(linked.read_bytes(), b"keep primary")
        self.assertEqual(backup.read_bytes(), b"foreign linked bytes")

    def test_tc337_expired_log_with_aliased_backup_keeps_both_paths(self):
        path = self.root / "logs" / "failures-2020-01-01.jsonl"
        path.write_bytes(b"keep alias primary")
        target = self.root / "foreign-log-backup"
        base.private_directory(target)
        protected = target / "keep"
        protected.write_bytes(b"foreign directory bytes")
        alias = path.with_name(path.name + ".bak")
        cleanup_tests.CleanupTest.alias(self, alias, target, directory=True)
        self.assertEqual(retention.retain_logs(self.worker, clock.now() + 5, NOW), 0)
        self.assertEqual(path.read_bytes(), b"keep alias primary")
        self.assertTrue(alias.exists())
        self.assertEqual(protected.read_bytes(), b"foreign directory bytes")

    def test_tc337_expired_log_sidecar_failure_keeps_the_primary_until_retry(self):
        path = self.root / "logs" / "failures-2020-01-01.jsonl"
        backup = path.with_name(path.name + ".bak")
        path.write_bytes(b"expired primary")
        backup.write_bytes(b"expired backup")
        original = retention._remove
        def denied(memory, candidate, info, check):
            if candidate == backup:
                raise PermissionError("synthetic held sidecar")
            return original(memory, candidate, info, check)
        with mock.patch.object(retention, "_remove", denied):
            self.assertEqual(retention.retain_logs(self.worker, clock.now() + 5, NOW), 0)
        self.assertEqual(path.read_bytes(), b"expired primary")
        self.assertEqual(backup.read_bytes(), b"expired backup")
        self.assertEqual(retention.retain_logs(self.worker, clock.now() + 5, NOW), 1)
        self.assertFalse(path.exists())
        self.assertFalse(backup.exists())

    def test_tc337_global_log_phase_refuses_a_held_project_lease(self):
        deadline = clock.now() + 5
        with self.worker.lease(self.project / "curation.lock", "curation", deadline):
            with self.assertRaises(locks.LostLock):
                retention.retain_logs(self.worker, deadline, NOW)

    def test_tc337_daily_replacement_and_store_loss_are_fenced(self):
        path = self.root / "logs" / "failures-2020-01-01.jsonl"
        path.write_bytes(b"old")
        original = retention._remove
        def replace(memory, candidate, before, check):
            replacement = candidate.with_suffix(".replacement")
            replacement.write_bytes(b"foreign")
            replacement.replace(candidate)
            return original(memory, candidate, before, check)
        with mock.patch.object(retention, "_remove", replace):
            self.assertEqual(retention.retain_logs(self.worker, clock.now() + 5, NOW), 0)
        self.assertEqual(path.read_bytes(), b"foreign")
        def lose_store(memory, candidate, before, check):
            header = self.root / "store.json"
            header.write_bytes(header.read_bytes() + b" ")
            return original(memory, candidate, before, check)
        with mock.patch.object(retention, "_remove", lose_store):
            with self.assertRaises(locks.LostLock):
                retention.retain_logs(self.worker, clock.now() + 5, NOW)
        self.assertEqual(path.read_bytes(), b"foreign")

    def test_tc337_expired_deadline_and_untracked_curation_refuse_mutation(self):
        self.write([self.entry(1, 101)])
        before = self.path.read_bytes()
        deadline = clock.now() + 5
        with self.worker.lease(self.project / "curation.lock", "curation", deadline) as owner:
            with self.assertRaises(locks.LockBusy):
                retention.retain_project(self.worker, "sample", owner, clock.now() - 1, NOW)
        untracked = locks.Lock(self.project / "curation.lock", "curation", self.worker.device)
        with untracked.held(deadline):
            with self.assertRaises(locks.LostLock):
                retention.retain_project(self.worker, "sample", untracked, deadline, NOW)
        self.assertEqual(self.path.read_bytes(), before)

    def test_tc337_windows_held_raw_is_retried_on_the_next_helper_invocation(self):
        if os.name != "nt":
            self.skipTest("Windows held-file sharing requires Windows")
        import ctypes
        create = ctypes.windll.kernel32.CreateFileW
        create.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p,
                           ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
        create.restype = ctypes.c_void_p
        close = ctypes.windll.kernel32.CloseHandle
        close.argtypes = [ctypes.c_void_p]
        self.write([self.entry(1, 101), self.entry(2, 99)])
        handle = create(str(self.path), 0x80000000, 1, None, 3, 0, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        before = self.path.read_bytes()
        try:
            self.assertEqual(self.apply()["skipped"], 1)
            self.assertEqual(self.path.read_bytes(), before)
        finally:
            self.assertTrue(close(handle))
        self.assertEqual(self.apply()["removed"], 1)
        self.assertEqual(self.read(), [self.entry(2, 99)])

    def test_tc337_final_progress_write_failure_keeps_reused_seq_unprocessed(self):
        for orphan in (False, True):
            with self.subTest(orphan=orphan):
                if self.path.exists():
                    self.path.unlink()
                document = {"logs": {self.log: 0 if orphan else 20}, "applies": 4,
                            "recent": [], "consolidation": {"failures": 0}}
                self.record.write_bytes(base.json_bytes(document, "TBL-009"))
                marker = self.project / "unprocessed" / ("20260722T120000Z." + self.log + ".1")
                marker.write_bytes(b"")
                if not orphan:
                    self.write([self.entry(1, 101)])
                original = curation.write
                def fail_final(memory, root, value, deadline):
                    if self.log not in value["logs"]:
                        raise OSError("synthetic final progress commit failure")
                    return original(memory, root, value, deadline)
                with mock.patch.object(curation, "write", fail_final):
                    self.assertEqual(self.apply()["skipped"], 1)
                self.assertFalse(self.path.exists())
                self.assertFalse(marker.exists())
                self.assertEqual(curation.parse(self.record.read_bytes())["logs"][self.log], 0)
                self.assertEqual(self.apply()["files"], 0)
                self.assertEqual(curation.parse(self.record.read_bytes())["logs"][self.log], 0)
                result = raw_log.RawLog(self.worker, "sample", "codex", "retention-fixture").append(
                    "prompt", raw_log.prepare("new sequence after interrupted final write"),
                    diagnostic_deadline=clock.now() + 5, when=NOW)
                self.assertEqual(result.outcome, "ok")
                self.assertEqual(result.entry["seq"], 1)
                self.assertLess(curation.parse(self.record.read_bytes())["logs"][self.log], result.entry["seq"])
                self.assertEqual(self.read(), [result.entry])
