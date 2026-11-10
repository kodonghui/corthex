"""TC-013–014: metadata privacy and real log-lock contention, without hooks."""

import contextlib
import io
import json
import multiprocessing
import os
import secrets
import stat
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from test_memory_api import errors, section, table
from test_memory_store import API, SCRIPTS, StoreCase
from memory_lib import base, configuration, diagnostics, files, locks, store
from memory_lib import clock as memory_clock


def hold_logs(connection, folder, device):
    with contextlib.ExitStack() as stack:
        for name in ("failures", "hooks"):
            lock = locks.Lock(Path(folder) / "logs" / (name + ".lock"), "log", device)
            stack.enter_context(lock.held(memory_clock.now() + 10))
        connection.send(True)
        connection.recv()


QUIET_CALLER = r'''
import sys, time
sys.path.insert(0, sys.argv[1])
from memory_lib.diagnostics import Diagnostics
from memory_lib.store import MemoryStore
from memory_lib import clock as memory_clock
logger = Diagnostics(MemoryStore(sys.argv[2]))
logger.failure(PermissionError("made-up private text"), "record", memory_clock.now() + 0.05)
logger.timing("prompt", "codex", 1, "lock-busy", memory_clock.now() + 0.05)
'''


class MemoryDiagnosticsTest(StoreCase):
    def test_permission_denied_hook_log_does_not_wait_for_a_contended_lease(self):
        with mock.patch.object(locks.Lock, "_create", side_effect=PermissionError("private-fixture")), \
                mock.patch.object(locks.Lock, "acquire", side_effect=AssertionError("permission denial must not wait")):
            self.assertFalse(self.logger.failure("redaction", "record", memory_clock.now()+2,
                             hook="start", host="codex", opportunistic=True))
        self.assertEqual(self.failures(), [])
        self.assertFalse((self.root / "logs/failures.lock").exists())

    def setUp(self):
        super().setUp()
        self.logger = diagnostics.Diagnostics(self.memory)
        self.when = datetime(2026, 10, 28, 1, 2, 3, 456789, timezone(timedelta(hours=9)))
        self.result_schema = json.loads((API / "memory-result.schema.json").read_text(encoding="utf-8"))

    def failures(self):
        paths = list((self.root / "logs").glob("failures-*.jsonl"))
        return [line for path in paths for line in files.read_jsonl(path)]

    def test_tc327_same_metadata_header_change_fences_early_and_late_logs(self):
        path, original = self.root / "store.json", files.append_jsonl
        def metadata(info):
            return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns
        for late in (False, True):
            with self.subTest(late=late):
                path.write_bytes(base.json_bytes(self.header, "TBL-001"))
                logger = diagnostics.Diagnostics(self.memory)
                logger.read_gate(memory_clock.now() + 2)
                before = path.stat()
                def changed(*args, **kwargs):
                    if args[2] == "TBL-004":
                        value = dict(self.header, device=base.new_id("d"))
                        path.write_bytes(base.json_bytes(value, "TBL-001"))
                        os.utime(str(path), ns=(before.st_atime_ns, before.st_mtime_ns))
                        self.assertEqual(metadata(path.stat()), metadata(before))
                    return original(*args, **kwargs)
                with mock.patch.object(files, "append_jsonl", changed):
                    deadline = memory_clock.now() + (-1 if late else 2)
                    result = logger.failure("deadline", "record", deadline,
                                            opportunistic=True, when=self.when)
                self.assertFalse(result)
                self.assertEqual(self.failures(), [])

    def test_tc327_header_fingerprint_keeps_the_callers_sharing_retry_budget(self):
        path, opened = self.root / "store.json", Path.open
        for expired in (False, True):
            with self.subTest(expired=expired):
                calls = []
                def sharing(target, *args, **kwargs):
                    calls.append(target == path)
                    if len(calls) == 1:
                        raise PermissionError("made-up header sharing")
                    return opened(target, *args, **kwargs)
                with mock.patch.object(files, "_WINDOWS", True), \
                        mock.patch.object(Path, "open", sharing):
                    if expired:
                        with self.assertRaises(PermissionError):
                            diagnostics.Diagnostics._stamp(path, memory_clock.now() - 1)
                    else:
                        self.assertIsNotNone(diagnostics.Diagnostics._stamp(path))
                self.assertEqual(calls, [True] if expired else [True, True])

    def test_tc327_fingerprint_crossing_expiry_keeps_ordinary_writes_strict(self):
        now, opened, write = memory_clock.now(), files.private_open, files.os.write
        for opportunistic in (False, True):
            with self.subTest(opportunistic=opportunistic):
                offset, daily_open, written = [0], [False], []
                logger = diagnostics.Diagnostics(self.memory)
                fingerprint = logger._stamp
                def opening(path, *args):
                    fd = opened(path, *args)
                    daily_open[0] = Path(path).suffix == ".jsonl"
                    return fd
                def reading(*args, **kwargs):
                    value = fingerprint(*args, **kwargs)
                    if daily_open[0]:
                        offset[0] = 3
                    return value
                def writing(fd, data):
                    if b'"error"' in data:
                        written.append(memory_clock.now())
                    return write(fd, data)
                with mock.patch.object(memory_clock, "now", side_effect=lambda: now + offset[0]), \
                        mock.patch.object(files, "private_open", opening), \
                        mock.patch.object(logger, "_stamp", reading), \
                        mock.patch.object(files.os, "write", writing):
                    result = logger.failure("deadline", "record", now + 2,
                                            opportunistic=opportunistic, when=self.when)
                self.assertEqual(result, opportunistic)
                self.assertEqual(written, [now + 3] if opportunistic else [])
                self.assertEqual(len(self.failures()), int(opportunistic))

    def test_tc327_lease_lost_inside_fingerprint_fences_early_and_late_logs(self):
        opened = files.private_open
        for late in (False, True):
            with self.subTest(late=late):
                logger = diagnostics.Diagnostics(self.memory)
                logger.read_gate(memory_clock.now() + 2)
                fingerprint = logger._stamp
                daily_open, displaced = [False], [False]
                path = self.root / "logs/failures.lock"
                def opening(target, *args):
                    fd = opened(target, *args)
                    daily_open[0] = daily_open[0] or Path(target).suffix == ".jsonl"
                    return fd
                def reading(*args, **kwargs):
                    value = fingerprint(*args, **kwargs)
                    if daily_open[0] and not displaced[0]:
                        payload = json.loads(path.read_bytes())
                        payload["token"] = "b" * 32
                        path.write_text(json.dumps(payload), encoding="utf-8")
                        displaced[0] = True
                    return value
                try:
                    with mock.patch.object(files, "private_open", opening), \
                            mock.patch.object(logger, "_stamp", reading):
                        deadline = memory_clock.now() + (-1 if late else 2)
                        result = logger.failure("deadline", "record", deadline,
                                                opportunistic=True, when=self.when)
                    self.assertTrue(displaced[0])
                    self.assertFalse(result)
                    self.assertEqual(self.failures(), [])
                    self.assertEqual(json.loads(path.read_bytes())["token"], "b" * 32)
                finally:
                    if displaced[0]:
                        path.unlink()

    def test_tc013_failure_fields_order_schema_date_and_count(self):
        result = self.logger.failure("damaged-line", "record", memory_clock.now() + 2,
                                     hook="prompt", host="codex", project="sample",
                                     log="codex-0123456789abcdef", count=2, when=self.when)
        self.assertTrue(result)
        path = self.root / "logs/failures-2026-10-27.jsonl"
        line = files.read_jsonl(path)[0]
        self.assertEqual(list(line), base.FIELDS["TBL-004"].split())
        self.assertEqual(line["at"], "2026-10-27T16:02:03.456Z")
        self.assertEqual(errors(self.result_schema["$defs"]["failure"], line, self.result_schema), [])
        self.assertNotIn(b"\r", path.read_bytes())
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)

    def test_tc013_timings_use_start_utc_day_and_allow_each_outcome(self):
        for outcome in sorted(diagnostics.OUTCOMES):
            self.assertTrue(self.logger.timing("end-of-turn", "claude-code", 12, outcome,
                                              memory_clock.now() + 2, when=self.when))
        path = self.root / "logs/hooks-2026-10-27.jsonl"
        lines = files.read_jsonl(path)
        self.assertEqual(len(lines), 6)
        for line in lines:
            self.assertEqual(list(line), base.FIELDS["TBL-005"].split())
            self.assertEqual(line["ms"], 12)
            self.assertEqual(line["at"], "2026-10-27T16:02:03.456Z")
        next_day = self.when + timedelta(hours=9)
        self.assertTrue(self.logger.timing("start", "codex", 0, "ok", memory_clock.now() + 2, when=next_day))
        self.assertEqual(len(list(path.parent.glob("hooks-*.jsonl"))), 2)
        self.assertTrue((path.parent / "hooks-2026-10-28.jsonl").exists())
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_the_compaction_brief_hook_writes_its_failure_and_timing_lines(self):
        # TASK-113: the brief hook's lines, from the 0.3.0 activation: the hook `pre-compact` and the step
        # `compaction` (TBL-004, TBL-005), which the status reads through the result schema.
        deadline = memory_clock.now() + 2
        self.assertTrue(self.logger.failure("deadline", "compaction", deadline, hook="pre-compact",
                                            host="claude-code", project="sample", when=self.when))
        self.assertTrue(self.logger.timing("pre-compact", "claude-code", 501, "deadline", deadline, when=self.when))
        failure, = files.read_jsonl(self.root / "logs/failures-2026-10-27.jsonl")
        timing, = files.read_jsonl(self.root / "logs/hooks-2026-10-27.jsonl")
        self.assertEqual((failure["step"], failure["hook"], timing["hook"]), ("compaction", "pre-compact", "pre-compact"))
        self.assertEqual(errors(self.result_schema["$defs"]["failure"], failure, self.result_schema), [])
        # The status's group of these timing lines.
        group = dict(hook=timing["hook"], host=timing["host"], runs=1, median_ms=501, p95_ms=501, last=timing["at"],
                     outcomes={"deadline": 1})
        self.assertEqual(errors(self.result_schema["$defs"]["hook-timing"], group, self.result_schema), [])

    def test_the_compaction_check_hook_writes_its_failure_and_timing_lines(self):
        # TASK-114: the check hook's lines, from the 0.3.0 activation: the hook `post-compact` and the step
        # `compaction`, with the raw log's name for an unreadable old check (TBL-004, TBL-005).
        deadline = memory_clock.now() + 2
        self.assertTrue(self.logger.failure(ValueError("unreadable"), "compaction", deadline, hook="post-compact",
                                            host="claude-code", project="sample", log="claude-code-0123456789abcdef",
                                            when=self.when))
        self.assertTrue(self.logger.timing("post-compact", "claude-code", 51, "lock-busy", deadline, when=self.when))
        failure, = files.read_jsonl(self.root / "logs/failures-2026-10-27.jsonl")
        timing, = files.read_jsonl(self.root / "logs/hooks-2026-10-27.jsonl")
        self.assertEqual((failure["step"], failure["hook"], failure["error"], failure["log"], timing["hook"]),
                         ("compaction", "post-compact", "ValueError", "claude-code-0123456789abcdef", "post-compact"))
        self.assertEqual(errors(self.result_schema["$defs"]["failure"], failure, self.result_schema), [])
        group = dict(hook=timing["hook"], host=timing["host"], runs=1, median_ms=51, p95_ms=51, last=timing["at"],
                     outcomes={"lock-busy": 1})
        self.assertEqual(errors(self.result_schema["$defs"]["hook-timing"], group, self.result_schema), [])

    def diagnostic_transition(self, stage, opportunistic=True):
        for name in ("failures", "hooks"):
            logger = diagnostics.Diagnostics(self.memory)
            now, offset, attempts = memory_clock.now, [0.0], []
            deadline = now() + 2
            read_gate, create = logger.read_gate, locks.Lock._create
            def gated(*args, **kwargs):
                value = read_gate(*args, **kwargs)
                if stage == "gate":
                    offset[0] = 3.0
                return value
            def creating(lock):
                attempts.append(lock.path.name)
                value = create(lock)
                if stage == "acquired":
                    offset[0] = 3.0
                return value
            before = self.snapshot()
            with mock.patch.object(memory_clock, "now", side_effect=lambda: now()+offset[0]), \
                    mock.patch.object(logger, "read_gate", gated), \
                    mock.patch.object(locks.Lock, "_create", creating):
                if name == "failures":
                    result = logger.failure("deadline", "record", deadline, hook="end-of-turn",
                                            host="codex", opportunistic=opportunistic, when=self.when)
                else:
                    result = logger.timing("end-of-turn", "codex", 1, "deadline", deadline,
                                           opportunistic=opportunistic, when=self.when)
            self.assertEqual(result, opportunistic)
            self.assertEqual(attempts, [name+".lock"] if opportunistic else [])
            if opportunistic:
                path = self.root / ("logs/"+name+"-2026-10-27.jsonl")
                rows = files.read_jsonl(path)
                self.assertEqual(rows[-1].get("error", rows[-1].get("outcome")),
                                 "deadline")
            else:
                self.assertEqual(self.snapshot(), before)

    def test_tc321_expiry_during_the_diagnostic_gate_still_attempts_free_locks(self):
        self.diagnostic_transition("gate")

    def test_tc321_acquired_diagnostic_locks_finish_one_line_after_expiry(self):
        self.diagnostic_transition("acquired")

    def test_tc321_ordinary_logger_callers_keep_their_strict_deadline(self):
        self.diagnostic_transition("gate", opportunistic=False)

    def test_tc321_gate_expiry_tries_a_busy_lock_once_without_waiting(self):
        parent, child = multiprocessing.Pipe()
        worker = multiprocessing.Process(target=hold_logs, args=(child, str(self.root), self.header["device"]))
        worker.start()
        try:
            self.assertTrue(parent.poll(10))
            self.assertTrue(parent.recv())
            now, offset, attempts = memory_clock.now, [0.0], []
            deadline, read_gate = now()+2, self.logger.read_gate
            original_try = locks.Lock.try_once
            def gated(*args, **kwargs):
                value = read_gate(*args, **kwargs)
                offset[0] = 3.0
                return value
            def tried(lock, **options):
                attempts.append(lock.path.name)
                return original_try(lock, **options)
            before = self.snapshot()
            with mock.patch.object(memory_clock, "now", side_effect=lambda: now()+offset[0]), \
                    mock.patch.object(self.logger, "read_gate", gated), \
                    mock.patch.object(locks.Lock, "try_once", tried), \
                    mock.patch.object(locks.Lock, "acquire", side_effect=AssertionError("must not wait")):
                self.assertFalse(self.logger.failure("deadline", "record", deadline,
                                                     hook="end-of-turn", opportunistic=True))
            self.assertEqual(attempts, ["failures.lock"])
            self.assertEqual(self.snapshot(), before)
        finally:
            parent.send(True)
            worker.join(10)
            if worker.is_alive():
                worker.terminate()
                worker.join()
            parent.close()
            child.close()
        self.assertEqual(worker.exitcode, 0)

    def test_tc013_never_serializes_error_text_filename_or_generated_key(self):
        marker = "made-up-private-" + secrets.token_hex(16)
        generated_key = "sk-" + secrets.token_hex(24)
        error = PermissionError(13, marker + generated_key, str(self.folder / marker))
        class Unprintable(ValueError):
            def __str__(self):
                raise AssertionError("must not stringify an exception")
        private_class = type(marker, (Exception,), {})
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            for failure in (error, Unprintable(marker), private_class(marker),
                            configuration.ConfigurationInvalid(marker), locks.LockBusy()):
                self.assertTrue(self.logger.failure(failure, "record", memory_clock.now() + 2, when=self.when))
            self.assertTrue(self.logger.timing("prompt", "codex", 1, "error", memory_clock.now() + 2, when=self.when))
        self.assertEqual(out.getvalue() + err.getvalue(), "")
        contents = b"".join(p.read_bytes() for p in self.root.rglob("*") if p.is_file())
        self.assertFalse(marker.encode() in contents)
        self.assertFalse(generated_key.encode() in contents)
        self.assertEqual([line["error"] for line in self.failures()],
                         ["PermissionError", "ValueError", "Exception", "configuration-invalid", "lock-busy"])

    def test_tc013_bad_metadata_is_quiet_and_changes_no_file(self):
        before = self.snapshot()
        for kwargs in ({"error": "private text"}, {"step": "private text"}, {"hook": "prompt\n"},
                       {"host": "unknown"}, {"project": "../sample"}, {"log": "folder/codex-0123456789abcdef"},
                       {"count": 0}, {"count": True}, {"when": datetime(2026, 10, 27)}):
            args = {"error": "deadline", "step": "record", "deadline": memory_clock.now() + 2, "when": self.when}
            args.update(kwargs)
            self.assertFalse(self.logger.failure(**args))
        for kwargs in ({"ms": -1}, {"ms": True}, {"ms": float("inf")}, {"hook": "unknown"},
                       {"host": "unknown"}, {"outcome": "private text"}, {"when": datetime(2026, 10, 27)}):
            args = {"hook": "prompt", "host": "codex", "ms": 1, "outcome": "ok",
                    "deadline": memory_clock.now() + 2, "when": self.when}
            args.update(kwargs)
            self.assertFalse(self.logger.timing(**args))
        self.assertEqual(self.snapshot(), before)

    def test_tc013_codes_and_restore_callbacks_keep_only_allowed_fields(self):
        for code in sorted(diagnostics.CODES):
            self.assertTrue(self.logger.failure(code, "restore", memory_clock.now() + 2, when=self.when))
        path = self.root / "configuration.json"
        path.write_bytes(b"{")
        path.with_name(path.name + ".bak").write_bytes(b"{}\n")
        def report(code, count):
            self.logger.failure(code, "restore", memory_clock.now() + 2, count=count, when=self.when)
        self.assertEqual(self.memory.configuration(report, deadline=memory_clock.now() + 1).document, {})
        self.assertEqual(self.failures()[-1]["error"], "restored")
        self.assertEqual(set(self.failures()[-1]), {"at", "step", "error"})

    def test_tc011_store_gate_codes_are_command_results_and_never_logged(self):
        api = (API / "memory.md").read_text(encoding="utf-8")
        failures = {row[0].strip("`") for row in table(section(api, "### Hooks and the memory worker"))}
        commands = {row[0].strip("`") for row in table(section(api, "### Command results"))}
        self.assertEqual(diagnostics.CODES, failures)
        before = self.snapshot()
        for code in ("store-newer", "store-damaged"):
            self.assertIn(code, commands)
            self.assertIn(code, self.result_schema["$defs"]["any-command-codes"]["enum"])
            self.assertNotIn(code, failures)
            # Even after a store recovers, these codes cannot be retroactively
            # appended, whether given as a string or a structured gate error.
            for error in (code, store.StoreUnavailable(code)):
                self.assertIsNone(diagnostics.error_kind(error))
                self.assertFalse(self.logger.failure(error, "record", memory_clock.now() + 2, when=self.when))
        self.assertEqual(self.snapshot(), before)

    def test_tc011_blocked_store_reads_only_its_record_and_writes_nothing(self):
        path = self.root / "store.json"
        backup = self.root / "store.json.bak"
        (self.root / "configuration.json").write_bytes(b"{}\n")
        (self.root / "logs/failures-2026-10-27.jsonl").write_bytes(b"preexisting failure log\n")
        (self.root / "logs/hooks-2026-10-27.jsonl").write_bytes(b"preexisting timing log\n")
        readable = base.json_bytes(self.header, "TBL-001")
        cases = [(b'{"format":2}', readable, "store-newer"),
                 (b'{"format":1,"migrating":{}}', readable, "store-newer"),
                 (b"{", None, "store-damaged"), (b"{", b"{", "store-damaged"),
                 (None, None, "store-damaged"), (None, b"{", "store-damaged")]
        for broken, saved, code in cases:
            if broken is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(broken)
            if saved is None:
                backup.unlink(missing_ok=True)
            else:
                backup.write_bytes(saved)
            before = self.snapshot()
            read = Path.read_bytes
            accessed = []
            def observed(target):
                self.assertIn(target, (path, backup))
                accessed.append(target)
                return read(target)
            with mock.patch.object(Path, "read_bytes", observed), mock.patch.object(locks.Lock, "acquire") as acquire:
                with self.assertRaises(store.StoreUnavailable) as caught:
                    self.memory.configuration(deadline=memory_clock.now() + 1)
                self.assertEqual(caught.exception.code, code)
                self.assertFalse(self.logger.failure("deadline", "record", memory_clock.now() + 2, when=self.when))
                self.assertFalse(self.logger.timing("prompt", "codex", 1, "error", memory_clock.now() + 2, when=self.when))
                acquire.assert_not_called()
            self.assertTrue(accessed)
            self.assertEqual(accessed[0], path)
            self.assertEqual(self.snapshot(), before)

    def test_tc011_readable_store_backup_is_restored_before_logging_restored(self):
        path = self.root / "store.json"
        backup = self.root / "store.json.bak"
        (self.root / "configuration.json").write_bytes(b"{}\n")
        for broken in (None, b"{"):
            if broken is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(broken)
            backup.write_bytes(base.json_bytes(self.header, "TBL-001"))
            notices = []
            def report(code, count):
                self.assertEqual(self.memory.record(deadline=memory_clock.now() + 1), self.header)
                self.assertFalse(backup.exists())
                notices.append((code, count))
                self.assertTrue(self.logger.failure(code, "restore", memory_clock.now() + 2, when=self.when))
            self.assertEqual(self.memory.configuration(report, deadline=memory_clock.now() + 1).document, {})
            self.assertEqual(notices, [("restored", None)])
            self.assertEqual(self.failures()[-1]["error"], "restored")
        self.assertEqual(len(self.failures()), 2)

    def test_tc013_missing_store_or_logs_never_creates_a_directory(self):
        absent = self.folder / "absent"
        self.assertFalse(diagnostics.Diagnostics(store.MemoryStore(absent)).failure(
            "bad-input", "record", memory_clock.now() + 2, when=self.when))
        self.assertFalse(absent.exists())
        (self.root / "logs").rmdir()
        before = self.snapshot()
        self.assertFalse(self.logger.failure("bad-input", "record", memory_clock.now() + 2, when=self.when))
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.root / "logs").exists())

    def test_tc013_append_errors_are_best_effort(self):
        for error in (PermissionError("made-up"), OSError("made-up"), locks.LostLock()):
            with mock.patch.object(files, "append_jsonl", side_effect=error):
                self.assertFalse(self.logger.failure(error, "record", memory_clock.now() + 2, when=self.when))
        self.assertEqual(self.failures(), [])
        self.assertFalse(list((self.root / "logs").glob("*.lock")))

    def test_tc014_expired_and_nonfinite_deadlines_touch_nothing(self):
        before = self.snapshot()
        for deadline in (memory_clock.now() - 1, float("nan"), float("inf"), True, "text"):
            self.assertFalse(self.logger.failure("deadline", "record", deadline, when=self.when))
            self.assertFalse(self.logger.timing("end", "codex", 1, "deadline", deadline, when=self.when))
        self.assertEqual(self.snapshot(), before)

    def test_tc014_real_process_holds_both_log_locks_and_caller_stays_quiet(self):
        ctx = multiprocessing.get_context("spawn")
        parent, child = ctx.Pipe()
        process = ctx.Process(target=hold_logs, args=(child, str(self.root), self.header["device"]))
        process.start()
        child.close()
        try:
            self.assertTrue(parent.poll(15))
            self.assertTrue(parent.recv())
            before = self.snapshot()
            elapsed = []
            for call in (lambda deadline: self.logger.failure("deadline", "record", deadline, when=self.when),
                         lambda deadline: self.logger.timing("end", "codex", 1, "deadline", deadline, when=self.when)):
                started = memory_clock.now()
                self.assertFalse(call(started + 0.05))
                elapsed.append(memory_clock.now() - started)
            self.assertLess(max(elapsed), 0.25)
            caller = subprocess.run([sys.executable, "-c", QUIET_CALLER, str(SCRIPTS), str(self.root)],
                                    capture_output=True, timeout=15)
            self.assertEqual(caller.returncode, 0)
            self.assertEqual(caller.stdout + caller.stderr, b"")
            self.assertEqual(self.snapshot(), before)
            self.assertEqual(self.failures(), [])
            self.assertFalse(list((self.root / "logs").glob("hooks-*.jsonl")))
        finally:
            if process.is_alive():
                parent.send(True)
                process.join(15)
            if process.is_alive():
                process.terminate()
                process.join(5)
            parent.close()
        self.assertEqual(process.exitcode, 0)

    def test_tc014_missing_daily_log_backup_sharing_retries_use_the_caller_deadline(self):
        path = self.root/"logs/failures-2026-10-27.jsonl"
        backup = path.with_name(path.name+".bak")
        backup.write_bytes(b'{"error":"deadline"}\n')
        before = backup.read_bytes()
        read = Path.read_bytes
        def sharing(target):
            if target == backup: raise PermissionError("made-up backup sharing")
            return read(target)
        started = memory_clock.now()
        with mock.patch.object(files,"_WINDOWS",True), mock.patch.object(Path,"read_bytes",sharing):
            self.assertFalse(self.logger.failure("deadline","record",started+0.05,when=self.when))
        self.assertLess(memory_clock.now()-started,0.3)
        self.assertFalse(path.exists())
        self.assertEqual(backup.read_bytes(),before)

    def test_tc014_deadline_or_device_change_before_append_is_fenced(self):
        original = files.append_jsonl
        def delayed(*args, **kwargs):
            time.sleep(0.03)
            return original(*args, **kwargs)
        with mock.patch.object(files, "append_jsonl", delayed):
            self.assertFalse(self.logger.failure("deadline", "record", memory_clock.now() + 0.02, when=self.when))
        self.assertEqual(self.failures(), [])

        def changed(*args, **kwargs):
            header = dict(self.header, device=base.new_id("d"))
            (self.root / "store.json").write_bytes(base.json_bytes(header, "TBL-001"))
            return original(*args, **kwargs)
        with mock.patch.object(files, "append_jsonl", changed):
            self.assertFalse(self.logger.failure("deadline", "record", memory_clock.now() + 2, when=self.when))
        self.assertEqual(self.failures(), [])

    def test_tc011_store_recovery_precedes_the_log_lease_and_failure_line(self):
        path = self.root / "store.json"
        path.write_bytes(b"{")
        path.with_name("store.json.bak").write_bytes(base.json_bytes(self.header, "TBL-001"))
        original, reads = self.memory.record, []
        def before_lock(*args, **kwargs):
            holding = kwargs.get("holding_lock")
            self.assertEqual(set(locks._active), {holding} if holding is not None else set(),
                             "store recovery was attempted under another lease")
            if holding is not None:
                self.assertEqual(holding.path, self.root / "store.lock")
            reads.append(holding is not None)
            return original(*args, **kwargs)
        with mock.patch.object(self.memory, "record", before_lock):
            self.assertTrue(self.logger.failure("deadline", "record", memory_clock.now() + 2,
                                                when=self.when))
        self.assertIn(False, reads)
        self.assertIn(True, reads)
        self.assertEqual(files.read_json(path), self.header)
        self.assertFalse(path.with_name("store.json.bak").exists())
        self.assertEqual([row["error"] for row in self.failures()], ["deadline"])

    def test_tc013_lease_class_names_and_instances_use_their_fixed_codes(self):
        values = (("LockBusy", "lock-busy"), (locks.LockBusy(), "lock-busy"),
                  ("LostLock", "lost-lock"), (locks.LostLock(), "lost-lock"), ("lost-lock", "lost-lock"))
        for value, expected in values:
            self.assertEqual(diagnostics.error_kind(value), expected)
            self.assertTrue(self.logger.failure(value, "record", memory_clock.now() + 2,
                                                when=self.when))
        self.assertEqual([row["error"] for row in self.failures()],
                         ["lock-busy", "lock-busy", "lost-lock", "lost-lock", "lost-lock"])
        self.assertEqual(diagnostics.error_kind("PermissionError"), "PermissionError")
        self.assertEqual(diagnostics.error_kind(ValueError("made-up")), "ValueError")
        self.assertIsNone(diagnostics.error_kind("LostLock made-up private text"))
        self.assertIsNone(diagnostics.error_kind("unknown-class"))
        # The model calls' codes go to the failure log too (stage 06, TASK-082); `stale` is not a failure.
        self.assertEqual(diagnostics.error_kind("refusal"), "refusal")
        self.assertEqual(diagnostics.error_kind("bad-vector"), "bad-vector")
        self.assertIsNone(diagnostics.error_kind("stale"))

    def test_tc014_timing_release_failure_is_logged_without_discarding_the_timing(self):
        rename = locks.os.rename
        def sharing(source, target):
            if Path(source).name == "hooks.lock":
                raise PermissionError("made-up cleanup detail")
            return rename(source, target)
        with mock.patch.object(locks.os, "rename", sharing):
            self.assertTrue(self.logger.timing("prompt", "codex", 1, "ok",
                                               memory_clock.now() + 3, when=self.when))
        self.addCleanup((self.root / "logs/hooks.lock").unlink)
        self.assertEqual(len(files.read_jsonl(self.root / "logs/hooks-2026-10-27.jsonl")), 1)
        failures = self.failures()
        self.assertEqual([row["error"] for row in failures], ["PermissionError"])
        self.assertEqual((failures[0]["hook"], failures[0]["host"]), ("prompt", "codex"))
        self.assertNotIn(b"made-up cleanup detail", b"".join(p.read_bytes() for p in self.root.rglob("*") if p.is_file()))

    def test_tc014_failure_log_release_does_not_report_itself_recursively(self):
        rename = locks.os.rename
        def sharing(source, target):
            if Path(source).name == "failures.lock":
                raise PermissionError("made-up cleanup detail")
            return rename(source, target)
        with mock.patch.object(locks.os, "rename", sharing), \
                mock.patch.object(self.logger, "failure", wraps=self.logger.failure) as calls:
            self.assertTrue(self.logger.failure("deadline", "record", memory_clock.now() + 3,
                                                when=self.when))
        self.addCleanup((self.root / "logs/failures.lock").unlink)
        self.assertEqual(calls.call_count, 1)
        self.assertEqual([row["error"] for row in self.failures()], ["deadline"])
