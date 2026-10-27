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

from test_memory_api import errors
from test_memory_store import API, SCRIPTS, StoreCase
from memory_lib import base, configuration, diagnostics, files, locks, store


def hold_logs(connection, folder, device):
    with contextlib.ExitStack() as stack:
        for name in ("failures", "hooks"):
            lock = locks.Lock(Path(folder) / "logs" / (name + ".lock"), "log", device)
            stack.enter_context(lock.held(time.monotonic() + 10))
        connection.send(True)
        connection.recv()


QUIET_CALLER = r'''
import sys, time
sys.path.insert(0, sys.argv[1])
from memory_lib.diagnostics import Diagnostics
from memory_lib.store import MemoryStore
logger = Diagnostics(MemoryStore(sys.argv[2]))
logger.failure(PermissionError("made-up private text"), "record", time.monotonic() + 0.05)
logger.timing("prompt", "codex", 1, "lock-busy", time.monotonic() + 0.05)
'''


class MemoryDiagnosticsTest(StoreCase):
    def setUp(self):
        super().setUp()
        self.logger = diagnostics.Diagnostics(self.memory)
        self.when = datetime(2026, 10, 28, 1, 2, 3, 456789, timezone(timedelta(hours=9)))
        self.result_schema = json.loads((API / "memory-result.schema.json").read_text(encoding="utf-8"))

    def failures(self):
        paths = list((self.root / "logs").glob("failures-*.jsonl"))
        return [line for path in paths for line in files.read_jsonl(path)]

    def test_tc013_failure_fields_order_schema_date_and_count(self):
        result = self.logger.failure("damaged-line", "record", time.monotonic() + 2,
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
                                              time.monotonic() + 2, when=self.when))
        path = self.root / "logs/hooks-2026-10-27.jsonl"
        lines = files.read_jsonl(path)
        self.assertEqual(len(lines), 6)
        for line in lines:
            self.assertEqual(list(line), base.FIELDS["TBL-005"].split())
            self.assertEqual(line["ms"], 12)
            self.assertEqual(line["at"], "2026-10-27T16:02:03.456Z")
        next_day = self.when + timedelta(hours=9)
        self.assertTrue(self.logger.timing("start", "codex", 0, "ok", time.monotonic() + 2, when=next_day))
        self.assertEqual(len(list(path.parent.glob("hooks-*.jsonl"))), 2)
        self.assertTrue((path.parent / "hooks-2026-10-28.jsonl").exists())
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

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
                self.assertTrue(self.logger.failure(failure, "record", time.monotonic() + 2, when=self.when))
            self.assertTrue(self.logger.timing("prompt", "codex", 1, "error", time.monotonic() + 2, when=self.when))
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
            args = {"error": "deadline", "step": "record", "deadline": time.monotonic() + 2, "when": self.when}
            args.update(kwargs)
            self.assertFalse(self.logger.failure(**args))
        for kwargs in ({"ms": -1}, {"ms": True}, {"ms": float("inf")}, {"hook": "unknown"},
                       {"host": "unknown"}, {"outcome": "private text"}, {"when": datetime(2026, 10, 27)}):
            args = {"hook": "prompt", "host": "codex", "ms": 1, "outcome": "ok",
                    "deadline": time.monotonic() + 2, "when": self.when}
            args.update(kwargs)
            self.assertFalse(self.logger.timing(**args))
        self.assertEqual(self.snapshot(), before)

    def test_tc013_codes_and_restore_callbacks_keep_only_allowed_fields(self):
        for code in sorted(diagnostics.CODES):
            self.assertTrue(self.logger.failure(code, "restore", time.monotonic() + 2, when=self.when))
        path = self.root / "configuration.json"
        path.write_bytes(b"{")
        path.with_name(path.name + ".bak").write_bytes(b"{}\n")
        def report(code, count):
            self.logger.failure(code, "restore", time.monotonic() + 2, count=count, when=self.when)
        self.assertEqual(self.memory.configuration(report).document, {})
        self.assertEqual(self.failures()[-1]["error"], "restored")
        self.assertEqual(set(self.failures()[-1]), {"at", "step", "error"})

    def test_tc013_blocked_store_logs_wait_for_the_spec_decision(self):
        # TC-011 requests a failure line, but TBL-001 and stage 06 prohibit any
        # other store I/O here. Keep this subcase blocked pending clarification.
        path = self.root / "store.json"
        for broken in (b'{"format":2}', b'{"format":1,"migrating":{}}', b"{", None):
            if broken is None:
                path.unlink()
            else:
                path.write_bytes(broken)
            before = self.snapshot()
            self.assertFalse(self.logger.failure("store-newer", "record", time.monotonic() + 2, when=self.when))
            self.assertFalse(self.logger.timing("prompt", "codex", 1, "error", time.monotonic() + 2, when=self.when))
            self.assertEqual(self.snapshot(), before)

    def test_tc013_missing_store_or_logs_never_creates_a_directory(self):
        absent = self.folder / "absent"
        self.assertFalse(diagnostics.Diagnostics(store.MemoryStore(absent)).failure(
            "bad-input", "record", time.monotonic() + 2, when=self.when))
        self.assertFalse(absent.exists())
        (self.root / "logs").rmdir()
        before = self.snapshot()
        self.assertFalse(self.logger.failure("bad-input", "record", time.monotonic() + 2, when=self.when))
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.root / "logs").exists())

    def test_tc013_append_errors_are_best_effort(self):
        for error in (PermissionError("made-up"), OSError("made-up"), locks.LostLock()):
            with mock.patch.object(files, "append_jsonl", side_effect=error):
                self.assertFalse(self.logger.failure(error, "record", time.monotonic() + 2, when=self.when))
        self.assertEqual(self.failures(), [])
        self.assertFalse(list((self.root / "logs").glob("*.lock")))

    def test_tc014_expired_and_nonfinite_deadlines_touch_nothing(self):
        before = self.snapshot()
        for deadline in (time.monotonic() - 1, float("nan"), float("inf"), True, "text"):
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
                started = time.monotonic()
                self.assertFalse(call(started + 0.05))
                elapsed.append(time.monotonic() - started)
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

    def test_tc014_deadline_or_device_change_before_append_is_fenced(self):
        original = files.append_jsonl
        def delayed(*args, **kwargs):
            time.sleep(0.03)
            return original(*args, **kwargs)
        with mock.patch.object(files, "append_jsonl", delayed):
            self.assertFalse(self.logger.failure("deadline", "record", time.monotonic() + 0.02, when=self.when))
        self.assertEqual(self.failures(), [])
        def changed(*args, **kwargs):
            header = dict(self.header, device=base.new_id("d"))
            (self.root / "store.json").write_bytes(base.json_bytes(header, "TBL-001"))
            return original(*args, **kwargs)
        with mock.patch.object(files, "append_jsonl", changed):
            self.assertFalse(self.logger.failure("deadline", "record", time.monotonic() + 2, when=self.when))
        self.assertEqual(self.failures(), [])
