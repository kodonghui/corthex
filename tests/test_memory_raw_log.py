"""TC-029–032 and TC-319: isolated raw logs, markers and real processes."""

import contextlib
import hashlib
import io
import json
import multiprocessing
import os
import random
import stat
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from test_memory_store import StoreCase
from memory_lib import base, diagnostics, files, locks, raw_log, redaction, store

WHEN = datetime(2026, 10, 27, 9, 12, 3, 456000, timezone.utc)


def killed_writer(connection, folder, ordinal, count, stop):
    memory = store.MemoryStore(folder)
    log = raw_log.RawLog(memory, "sample", "codex", "made-up-session")
    original = files.append_jsonl
    index = 0
    def append(path, value, table, *args, **kwargs):
        if table != "TBL-007":
            return original(path, value, table, *args, **kwargs)
        if index == count - 1 and stop == "before":
            connection.send(("stop", None))
            connection.recv()
        write = files.os.write
        def acknowledged(fd, data):
            written = write(fd, data)
            if written == len(data):
                connection.send(("written", (value["id"], value["seq"])))
                if index == count - 1 and stop == "write":
                    connection.send(("stop", None))
                    connection.recv()
            return written
        with mock.patch.object(files.os, "write", acknowledged):
            return original(path, value, table, *args, **kwargs)
    with mock.patch.object(files, "append_jsonl", append):
        limit = time.monotonic() + 20
        for index in range(count):
            while True:
                result = log.append("prompt", raw_log.prepare("made-up turn %d/%d" % (ordinal, index), {}),
                                    diagnostic_deadline=time.monotonic() + 3)
                if result.entry is not None:
                    break
                if result.outcome not in ("lock-busy", "deadline") or time.monotonic() >= limit:
                    connection.send(("failed", result.outcome))
                    return
        connection.send(("stop", None))
        connection.recv()


def concurrent_writer(connection, folder, count, late_marker=False):
    log = raw_log.RawLog(store.MemoryStore(folder), "sample", "codex", "made-up-session")
    if late_marker:
        def expired(*args):
            raise raw_log.RecordingDeadline()
        log._marker = expired
    connection.send("ready")
    connection.recv()
    written = []
    limit = time.monotonic() + 15
    while len(written) < count and time.monotonic() < limit:
        result = log.append("prompt", raw_log.prepare("made-up concurrent turn", {}),
                            diagnostic_deadline=time.monotonic() + 2)
        if result.entry:
            if result.outcome not in ("ok", "deadline"):
                raise AssertionError("unexpected completed writer outcome")
            written.append((result.entry["id"],result.entry["turn"],result.outcome))
        elif result.outcome not in ("lock-busy", "deadline"):
            raise AssertionError("unexpected writer outcome")
    connection.send(written)


class RawLogTest(StoreCase):
    def setUp(self):
        super().setUp()
        project = self.root / "projects/sample"
        base.private_directory(project / "raw")
        base.private_directory(project / "unprocessed")
        self.log = raw_log.RawLog(self.memory, "sample", "codex", "made-up-session")
        self.context = multiprocessing.get_context("spawn")

    def record(self, kind="prompt", text="made-up text", when=WHEN, **options):
        prepared = raw_log.prepare(text, {}) if kind in ("prompt", "answer") and text is not None else None
        return self.log.append(kind, prepared, diagnostic_deadline=time.monotonic() + 3, when=when, **options)

    def entries(self):
        return files.read_jsonl(self.log.path) if self.log.path.exists() else []

    def markers(self):
        return sorted(self.log.markers.iterdir())

    def failures(self):
        return [row for path in (self.root / "logs").glob("failures-*.jsonl") for row in files.read_jsonl(path)]

    def start(self, target, *arguments):
        parent, child = self.context.Pipe()
        process = self.context.Process(target=target, args=(child,) + arguments)
        process.start()
        child.close()
        def cleanup():
            if process.is_alive():
                process.terminate()
            process.join(10)
            parent.close()
        self.addCleanup(cleanup)
        return parent, process

    def receive(self, connection, seconds=30):
        self.assertTrue(connection.poll(seconds), "recording worker timed out")
        return connection.recv()

    def test_tc030_turns_resubmission_and_boundaries_keep_one_marker_each(self):
        events = [("start", None, {}), ("prompt", "first", {}),
                  ("start", None, {"source":"resume"}), ("answer", "one", {}),
                  ("answer", "two", {"stop_hook_active":True}), ("answer", "own", {}),
                  ("end", None, {"reason":"other"}), ("prompt", "first", {}),
                  ("prompt", "first", {}), ("answer", "three", {})]
        for kind, text, arguments in events:
            result = self.record(kind, text, **arguments)
            self.assertEqual(result.outcome, "ok")
        rows = self.entries()
        self.assertEqual([r["seq"] for r in rows], list(range(1, 11)))
        self.assertEqual([r.get("turn") for r in rows], [None,2,None,2,2,6,None,8,9,9])
        self.assertEqual(len({r["id"] for r in rows}), 10)
        self.assertEqual([int(p.name.rsplit(".", 1)[1]) for p in self.markers()], [2,6,8,9])
        self.assertTrue(all(p.name.startswith("20261027T091203Z.") and p.read_bytes() == b"" for p in self.markers()))
        for row in rows:
            self.assertEqual(list(row), [k for k in base.FIELDS["TBL-007"].split() if k in row])
            self.assertEqual(raw_log._entry(base.json_bytes(row, "TBL-007", compact=True).rstrip(b"\n"), self.log.host, self.log.session), row)

    def test_tc030_answer_without_prompt_and_only_true_active_answer_joins(self):
        self.record("answer", "first")
        self.record("answer", "next", stop_hook_active=True)
        self.record("answer", "other", stop_hook_active="true")
        self.assertEqual([r["turn"] for r in self.entries()], [1,1,3])

    def test_tc030_boundary_metadata_is_allowlisted_and_text_free(self):
        for source, event in (("startup","start"),("resume","resume"),("fork","fork"),
                              ("clear","clear"),("compact","compact"),("unknown",None),({},None)):
            value = self.record("start", None, source=source).entry
            self.assertEqual(value.get("event"), event)
            self.assertFalse({"turn","text","cut","speaker"} & set(value))
        for reason, kept in (("a"*64,True),("a"*65,False),("other\n",False),("../outside",False)):
            value = self.record("end", None, reason=reason).entry
            self.assertEqual("reason" in value, kept)
        self.assertEqual(self.markers(), [])

    def test_tc030_empty_prompt_and_missing_answer_touch_nothing(self):
        before = self.snapshot()
        for text in ("", " \n\t"):
            self.assertIsNone(self.record("prompt", text).entry)
        for text in ("", None):
            self.assertEqual(self.record("answer", text).outcome, "no-answer")
        self.assertEqual(self.snapshot(), before)

    def test_tc029_no_missing_store_or_project_directories_are_provisioned(self):
        before = self.snapshot()
        for folder, error in ((self.folder / "absent", store.StoreUnavailable),
                              (self.root, FileNotFoundError)):
            log = raw_log.RawLog(store.MemoryStore(folder), "unprovisioned", "codex", "made-up-session")
            with self.assertRaises(error):
                log.append("prompt", raw_log.prepare("made-up", {}),
                           diagnostic_deadline=time.monotonic() + 2)
            self.assertFalse((folder / "projects/unprovisioned").exists())
        self.assertFalse((self.folder / "absent").exists())
        self.assertEqual(self.snapshot(), before)

    def test_tc030_redaction_runs_once_before_the_budget_and_writes(self):
        generated = "sk-" + "Z" * 25
        before = self.snapshot()
        original = redaction.redact
        def redact(text, environment):
            self.assertEqual(self.snapshot(), before)
            time.sleep(0.06)
            return original(text, environment)
        with mock.patch.object(redaction, "redact", side_effect=redact) as calls:
            prepared = raw_log.prepare("made-up " + generated, {})
            self.assertGreater(prepared.deadline, time.monotonic())
            result = self.log.append("prompt", prepared, diagnostic_deadline=time.monotonic() + 2, when=WHEN)
        self.assertEqual(calls.call_count, 1)
        self.assertEqual(result.outcome, "ok")
        self.assertTrue(generated.encode() not in self.log.path.read_bytes())
        self.assertIn("[redacted:openai-key]", self.entries()[0]["text"])

    def test_tc030_512k_utf8_cut_and_pre_redaction_size(self):
        text = "한" * (redaction.ENTRY_BYTES // 3 + 20)
        result = self.record(text=text)
        self.assertEqual(result.outcome, "ok")
        self.assertLessEqual(len(result.entry["text"].encode("utf-8")), redaction.ENTRY_BYTES)
        self.assertEqual(result.entry["cut"], len(text.encode("utf-8")))
        self.assertEqual(result.entry["text"], text[:redaction.ENTRY_BYTES // 3])

    def test_tc030_redaction_failure_and_invalid_prepared_records_write_nothing(self):
        before = self.snapshot()
        with mock.patch.object(redaction, "redact", side_effect=RuntimeError("made-up failure")):
            with self.assertRaises(RuntimeError):
                raw_log.prepare("made-up input", {})
        for prepared in (None, "made-up", raw_log.Prepared("a"*(redaction.ENTRY_BYTES+1),None,1),
                         raw_log.Prepared("a",True,1),raw_log.Prepared("a",None,float("nan"))):
            with self.assertRaises(ValueError):
                self.log.append("prompt", prepared, diagnostic_deadline=time.monotonic() + 2)
        self.assertEqual(self.snapshot(), before)

    def test_tc030_existing_marker_keeps_its_oldest_time_and_permissions(self):
        self.record()
        path = self.markers()[0]
        before = path.stat().st_mtime_ns
        self.record("answer", "made-up answer", when=WHEN + timedelta(days=1))
        self.assertEqual(self.markers(), [path])
        self.assertEqual(path.stat().st_mtime_ns, before)
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(self.log.path.stat().st_mode), 0o600)

    def test_tc030_new_turns_and_known_marker_do_not_list_pending_markers(self):
        for turn in range(1, 1001):
            (self.log.markers / ("20261027T091203Z.codex-" + "0"*16 + "." + str(turn))).write_bytes(b"")
        with mock.patch.object(raw_log.os,"listdir",wraps=os.listdir) as listed:
            prompt = self.record()
            joined = self.record("answer")
            orphan = self.record("answer")
        listed.assert_not_called()
        self.assertEqual([r.outcome for r in (prompt,joined,orphan)],["ok"]*3)
        self.assertEqual([r.entry["turn"] for r in (prompt,joined,orphan)],[1,1,3])
        self.assertEqual(len(self.markers()),1002)

    def test_tc030_missing_or_unknown_original_marker_lists_once(self):
        self.record()
        original = self.markers()[0]
        with mock.patch.object(raw_log.os,"listdir",wraps=os.listdir) as listed:
            self.record("answer")
            self.record("answer",stop_hook_active=True)
        self.assertEqual(listed.call_count,1)  # The second answer knows only turn 1.
        original.unlink()
        with mock.patch.object(raw_log.os,"listdir",wraps=os.listdir) as listed:
            result = self.record("answer",stop_hook_active=True)
        self.assertEqual(listed.call_count,1)
        self.assertEqual((result.outcome,result.entry["turn"]),("ok",1))
        self.assertEqual(len(self.markers()),1)

    def test_tc030_exclusive_marker_creation_accepts_an_existing_name(self):
        result = self.record()
        marker = self.markers()[0]
        before = marker.stat().st_mtime_ns
        self.log._marker(result.entry,lambda:None,time.monotonic()+1)
        self.assertEqual(marker.stat().st_mtime_ns,before)

    def test_tc030_fallback_marker_scan_checks_deadline_per_name(self):
        self.record()
        self.markers()[0].unlink()
        prepared = raw_log.prepare("made-up answer",{})
        clock, seen = [time.monotonic()], []
        def names(folder):
            for number in range(1000):
                seen.append(number)
                clock[0] += 0.01
                yield "unrelated."+str(number)
        with mock.patch.object(raw_log.os,"listdir",names), \
                mock.patch.object(raw_log.time,"monotonic",side_effect=lambda:clock[0]):
            result = self.log.append("answer",prepared,diagnostic_deadline=clock[0]+3,when=WHEN)
        self.assertEqual(result.outcome,"deadline")
        self.assertIsNotNone(result.entry)
        self.assertGreater(len(seen),1)
        self.assertLess(len(seen),10)
        self.assertEqual(self.markers(),[])
        self.assertEqual([r["error"] for r in self.failures()],["deadline"])

    def test_tc030_token_lost_during_marker_scan_preserves_the_entry_only(self):
        self.record()
        self.markers()[0].unlink()
        path, listed = self.log.path.with_suffix(".lock"), os.listdir
        taken = []
        def scan(folder):
            if folder == self.log.markers:
                value = json.loads(path.read_bytes())
                value["token"] = "c" * 32
                path.write_text(json.dumps(value),encoding="utf-8")
                taken.append(path.read_bytes())
            return listed(folder)
        prepared = raw_log.prepare("made-up",{})
        prepared = raw_log.Prepared(prepared.text,prepared.cut,time.monotonic()+2)
        with mock.patch.object(raw_log.os,"listdir",scan):
            result = self.log.append("answer",prepared,diagnostic_deadline=time.monotonic()+3,when=WHEN)
        self.assertEqual(result.outcome,"error")
        self.assertEqual(self.entries()[-1],result.entry)
        self.assertEqual(self.markers(),[])
        self.assertEqual(path.read_bytes(),taken[0])
        self.assertEqual([r["error"] for r in self.failures()],["lost-lock"])

    def test_tc030_lost_marker_is_recreated_when_a_turn_gets_another_entry(self):
        self.record()
        self.markers()[0].unlink()
        result = self.record("answer", "made-up continuation")
        self.assertEqual(result.entry["turn"], 1)
        self.assertEqual(len(self.markers()), 1)

    def test_tc029_invalid_turn_rows_still_reserve_their_parsed_sequence(self):
        self.record()
        with self.log.path.open("ab") as output:
            output.write(b'{"seq":999}\n{"cut')
        result = self.record("answer", "made-up answer")
        self.assertEqual(result.entry["seq"], 1000)
        self.assertEqual(result.entry["turn"], 1)
        notices = self.failures()
        self.assertEqual([(r["error"],r.get("count")) for r in notices], [("damaged-line",2)])
        self.assertIn(b'{"cut\n', self.log.path.read_bytes())

    def test_tc029_parseable_unterminated_entry_reserves_sequence_not_turn(self):
        self.record()
        value = dict(self.entries()[0],seq=7,turn=7)
        with self.log.path.open("ab") as output:
            output.write(base.json_bytes(value,"TBL-007",compact=True).rstrip(b"\n"))
        result = self.record("answer")
        self.assertEqual((result.entry["seq"],result.entry["turn"]),(8,1))

    def test_tc029_oversized_forget_rewrite_reserves_sequence_not_turn(self):
        self.record()
        value = dict(self.entries()[0],seq=8,turn=8,text="\ufffd"*redaction.ENTRY_BYTES)
        with self.log.path.open("ab") as output:
            output.write(base.json_bytes(value,"TBL-007",compact=True))
        prepared = raw_log.Prepared("made-up",None,time.monotonic()+3)
        result = self.log.append("answer",prepared,diagnostic_deadline=time.monotonic()+4,when=WHEN)
        self.assertEqual((result.entry["seq"],result.entry["turn"]),(9,1))

    def test_tc029_multiblock_control_character_line_is_read_in_new_blocks(self):
        # JSON escapes expand this legal 512 KiB text to a 3 MiB row. Reducing
        # BLOCK exposes repeated suffix scans without a wall-time assertion.
        value = self.record(text="\x01"*redaction.ENTRY_BYTES).entry
        self.assertIsNotNone(value)
        count = self.log.path.stat().st_size
        self.assertGreater(count,3*1024*1024)
        prepared = raw_log.Prepared("made-up",None,time.monotonic()+10)
        with mock.patch.object(raw_log,"BLOCK",1024):
            result = self.log.append("answer",prepared,diagnostic_deadline=time.monotonic()+11,when=WHEN)
        self.assertEqual((result.outcome,result.entry["seq"],result.entry["turn"]),("ok",2,1))

    def test_tc029_missing_primary_restores_before_assigning_the_next_sequence(self):
        self.record()
        backup = self.log.path.with_name(self.log.path.name + ".bak")
        self.log.path.replace(backup)
        result = self.record("answer", "made-up answer")
        self.assertEqual((result.entry["seq"], result.entry["turn"]), (2,1))
        self.assertFalse(backup.exists())
        self.assertIn("restored", [r["error"] for r in self.failures()])

    def test_tc029_readable_empty_primary_does_not_restore_an_older_backup(self):
        self.record()
        backup = self.log.path.with_name(self.log.path.name + ".bak")
        backup.write_bytes(self.log.path.read_bytes())
        self.log.path.write_bytes(b"")
        result = self.record()
        self.assertEqual(result.entry["seq"], 1)
        self.assertTrue(backup.exists())

    def test_tc029_healthy_large_log_reads_only_its_tail(self):
        self.record()
        line = self.log.path.read_bytes()
        with self.log.path.open("wb") as output:
            for _ in range(1600):
                output.write(b" " * (64*1024) + b"\n")
            output.write(line)
        incoming = Path.open
        sizes = []
        class Reader:
            def __init__(self, stream): self.stream = stream
            def __enter__(self): return self
            def __exit__(self, *args): self.stream.close()
            def seek(self, *args): return self.stream.seek(*args)
            def read(self, count): sizes.append(count); return self.stream.read(count)
        def opened(path, *args, **kwargs):
            stream = incoming(path, *args, **kwargs)
            return Reader(stream) if path == self.log.path and args == ("rb",) else stream
        with mock.patch.object(Path, "open", opened):
            result = self.record("answer", "made-up answer")
        self.assertEqual(result.outcome, "ok")
        self.assertEqual(result.entry["seq"], 2)
        self.assertEqual(sum(sizes), raw_log.BLOCK)

    def test_tc029_short_append_rolls_back_while_the_lease_is_owned(self):
        self.record()
        before, write = self.log.path.read_bytes(), files.os.write
        def short(fd, data):
            if b'"text"' in data:
                return write(fd, data[:len(data)//2])
            return write(fd, data)
        with mock.patch.object(files.os, "write", short):
            result = self.record()
        self.assertEqual(result.outcome, "error")
        self.assertIsNone(result.entry)
        self.assertEqual(self.log.path.read_bytes(), before)
        self.assertEqual(len(self.markers()), 1)

    def test_tc029_token_loss_before_the_file_primitive_changes_nothing(self):
        append = files.append_jsonl
        path = self.log.path.with_suffix(".lock")
        replaced = []
        def takeover(*args, **kwargs):
            if args[2] == "TBL-007":
                value = json.loads(path.read_bytes())
                value["token"] = "a" * 32
                path.write_text(json.dumps(value), encoding="utf-8")
                replaced.append(path.read_bytes())
            return append(*args, **kwargs)
        with mock.patch.object(files,"append_jsonl",takeover):
            result = self.record()
        self.addCleanup(path.unlink)
        self.assertEqual((result.outcome,result.entry),("error",None))
        self.assertFalse(self.log.path.exists())
        self.assertEqual(self.markers(),[])
        self.assertEqual(path.read_bytes(),replaced[0])
        self.assertEqual([r["error"] for r in self.failures()],["lost-lock"])

    def test_tc029_changed_store_device_fences_the_raw_append(self):
        append = files.append_jsonl
        def changed(*args, **kwargs):
            if args[2] == "TBL-007":
                header = dict(self.header,device=base.new_id("d"))
                (self.root/"store.json").write_bytes(base.json_bytes(header,"TBL-001"))
            return append(*args,**kwargs)
        with mock.patch.object(files,"append_jsonl",changed):
            result = self.record()
        self.assertEqual(result.outcome,"error")
        self.assertFalse(self.log.path.exists())
        self.assertEqual(self.markers(),[])

    def test_tc029_short_write_after_takeover_never_truncates_the_new_owner(self):
        self.record()
        write, path = files.os.write, self.log.path.with_suffix(".lock")
        winner = dict(self.entries()[0],id=base.new_id("e"),seq=2,turn=2,text="made-up new owner")
        def short(fd,data):
            if b'"text"' not in data:
                return write(fd,data)
            written = write(fd,data[:len(data)//2])
            payload = json.loads(path.read_bytes());payload["token"]="b"*32
            path.write_text(json.dumps(payload),encoding="utf-8")
            with self.log.path.open("ab") as output:
                output.write(b"\n"+base.json_bytes(winner,"TBL-007",compact=True))
            return written
        with mock.patch.object(files.os,"write",short), mock.patch.object(files.os,"ftruncate",wraps=files.os.ftruncate) as truncate:
            result = self.record()
        self.addCleanup(path.unlink)
        self.assertEqual(result.outcome,"error")
        truncate.assert_not_called()
        self.assertEqual(self.entries()[-1],winner)

    def test_tc029_real_writers_serialize_sequences_under_one_log_lease(self):
        workers = [self.start(concurrent_writer, str(self.root), 12, late) for late in (False,True)]
        for connection, _ in workers: self.assertEqual(self.receive(connection), "ready")
        for connection, _ in workers: connection.send("go")
        written = []
        for connection, process in workers:
            written += self.receive(connection)
            process.join(20)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(len({row[0] for row in written}), 24)
        self.assertEqual([r["seq"] for r in self.entries()], list(range(1,25)))
        self.assertTrue(any(row[2]=="deadline" for row in written))
        self.assertEqual({int(p.name.rsplit(".",1)[1]) for p in self.markers()},
                         {row[1] for row in written if row[2]=="ok"})

    def test_tc029_kill_writers_during_1000_appends_preserves_returned_writes(self):
        acknowledged, rng = set(), random.Random(29)
        cuts = [0] + sorted(rng.sample(range(1, 1000), 9)) + [1000]
        for batch, (start, end) in enumerate(zip(cuts, cuts[1:])):
            connection, process = self.start(killed_writer, str(self.root), batch, end - start,
                                             rng.choice(("before","write","done")))
            while True:
                event, value = self.receive(connection)
                self.assertNotEqual(event, "failed", value)
                if event == "stop": break
                self.assertEqual(event, "written")
                acknowledged.add(value[0])
            process.terminate()
            process.join(10)
            self.assertFalse(process.is_alive())
            rows = self.entries()
            self.assertLessEqual(acknowledged, {r["id"] for r in rows})
            self.assertEqual([r["seq"] for r in rows], list(range(1,len(rows)+1)))
            path = self.log.path.with_suffix(".lock")
            if path.exists():
                past = time.time() - 11
                os.utime(str(path), (past,past))
        self.assertGreaterEqual(len(acknowledged), 990)

    def test_tc031_foreign_lease_expires_the_recording_budget_and_logs_safely(self):
        from test_memory_locks import holder
        connection, process = self.start(holder, str(self.log.path.with_suffix(".lock")), self.header["device"])
        self.assertTrue(self.receive(connection))
        try:
            for kind, hook in (("prompt","prompt"),("answer","end-of-turn"),("end","end")):
                started = time.monotonic()
                result = self.record(kind, None if kind=="end" else "made-up", deadline=started+1)
                elapsed = time.monotonic() - started
                self.assertEqual(result.outcome, "lock-busy")
                self.assertIsNone(result.entry)
                self.assertFalse(self.log.path.exists())
                self.assertEqual(self.markers(), [])
                self.assertLess(elapsed, 0.35)
                self.assertTrue(self.log.logger.timing(hook,"codex",int(elapsed*1000),result.outcome,time.monotonic()+1,when=WHEN))
            self.assertEqual([r["error"] for r in self.failures()], ["lock-busy"]*3)
            self.assertEqual([r["outcome"] for r in files.read_jsonl(self.root / "logs/hooks-2026-10-27.jsonl")], ["lock-busy"]*3)
        finally:
            connection.send("check")
            self.receive(connection)
            process.join(10)

    def test_tc031_caller_deadline_only_shortens_the_recording_budget(self):
        prepared = raw_log.prepare("made-up",{})
        result = self.log.append("prompt",prepared,deadline=time.monotonic()-1,
                                 diagnostic_deadline=time.monotonic()+3,when=WHEN)
        self.assertEqual((result.outcome,result.entry),("lock-busy",None))
        self.assertFalse(self.log.path.exists())
        self.assertEqual(self.markers(),[])

    def test_tc031_store_gate_blocks_raw_and_diagnostic_access(self):
        header = dict(self.header, format=2)
        (self.root / "store.json").write_bytes(base.json_bytes(header,"TBL-001"))
        before = self.snapshot()
        with self.assertRaises(store.StoreUnavailable):
            self.record()
        self.assertEqual(self.snapshot(), before)

    def test_tc031_benchmark_counts_expired_attempts_without_inventing_entries(self):
        import bench_memory_raw_log as bench
        original, calls = raw_log.prepare, [0]
        def delayed(text, environment):
            value = original(text,environment)
            calls[0] += 1
            if calls[0] == 2:
                return raw_log.Prepared(value.text,value.cut,time.monotonic()-1)
            return value
        with mock.patch.object(raw_log,"prepare",delayed):
            row = bench.measure(1,pending_counts=())["cases"][0]
        self.assertEqual(row["outcomes"],{"lock-busy":1})
        self.assertEqual((row["entries"],row["skipped"]),(0,1))

    def test_tc031_benchmark_rejects_premature_timeouts_and_errors(self):
        import bench_memory_raw_log as bench
        original = raw_log.prepare
        def remaining(text, environment):
            value = original(text,environment)
            return raw_log.Prepared(value.text,value.cut,time.monotonic()+5)
        for outcome in ("deadline","lock-busy","error"):
            with self.subTest(outcome=outcome), mock.patch.object(raw_log,"prepare",remaining), \
                    mock.patch.object(raw_log.RawLog,"append",return_value=raw_log.Recorded(outcome)):
                with self.assertRaises(bench.MeasurementFailure):
                    bench.measure(1,pending_counts=())

    def test_tc032_session_names_hash_paths_unicode_and_each_host_independently(self):
        for host in ("codex","claude-code"):
            for session in ("../../outside","made-up/한국어", "same"):
                log = raw_log.RawLog(self.memory,"sample",host,session)
                expected = host + "-" + hashlib.sha256(session.encode()).hexdigest()[:16]
                self.assertEqual(log.log, expected)
                result = log.append("prompt",raw_log.prepare("made-up",{}),diagnostic_deadline=time.monotonic()+2,when=WHEN)
                self.assertEqual(result.entry["session"], session)
                self.assertEqual(log.path.parent, self.root / "projects/sample/raw")
        self.assertFalse((self.folder / "outside").exists())
        for session in ("", "a"*201, 1, None):
            with self.assertRaises(ValueError): raw_log.log_name("codex",session)

    def test_tc319_deadline_after_append_keeps_entry_skips_marker_and_reports_deadline(self):
        prepared = raw_log.prepare("made-up turn",{})
        clock = [time.monotonic()]
        original = files.append_jsonl
        def expire(*args, **kwargs):
            value = original(*args, **kwargs)
            if args[2] == "TBL-007": clock[0] = prepared.deadline + 0.001
            return value
        with mock.patch.object(raw_log.time,"monotonic",side_effect=lambda:clock[0]), \
                mock.patch.object(files,"append_jsonl",expire), \
                mock.patch.object(self.log,"_marker",wraps=self.log._marker) as marker:
            result = self.log.append("prompt",prepared,diagnostic_deadline=clock[0]+5,when=WHEN)
        self.assertEqual(result.outcome,"deadline")
        self.assertEqual(self.entries(),[result.entry])
        marker.assert_not_called()
        self.assertEqual(self.markers(),[])
        self.assertEqual([r["error"] for r in self.failures()],["deadline"])
        self.assertTrue(self.log.logger.timing("prompt","codex",51,result.outcome,time.monotonic()+1,when=WHEN))
        self.assertEqual(files.read_jsonl(self.root / "logs/hooks-2026-10-27.jsonl")[0]["outcome"],"deadline")
        next_entry = self.record("answer","made-up answer").entry
        self.assertEqual((next_entry["seq"],next_entry["turn"]),(2,1))
        self.assertEqual(len(self.markers()),1)

    def test_tc031_expiry_after_acquisition_without_entry_is_lock_busy(self):
        prepared = raw_log.prepare("made-up",{})
        clock, acquire = [time.monotonic()], locks.Lock.acquire
        def acquired(lease,*args,**kwargs):
            result = acquire(lease,*args,**kwargs)
            clock[0] = prepared.deadline + 0.001
            return result
        with mock.patch.object(raw_log.time,"monotonic",side_effect=lambda:clock[0]), \
                mock.patch.object(locks.Lock,"acquire",acquired):
            result = self.log.append("prompt",prepared,diagnostic_deadline=clock[0]+5,when=WHEN)
        self.assertEqual((result.outcome,result.entry),("lock-busy",None))
        self.assertFalse(self.log.path.exists())
        self.assertEqual([r["error"] for r in self.failures()],["lock-busy"])

    def test_tc031_failure_notices_wait_until_the_raw_lease_is_released(self):
        failure = self.log.logger.failure
        observed = []
        def report(*args,**kwargs):
            observed.append(self.log.path.with_suffix(".lock").exists())
            return failure(*args,**kwargs)
        with mock.patch.object(self.log.logger,"failure",report), \
                mock.patch.object(files,"append_jsonl",side_effect=OSError("made-up")):
            result = self.record()
        self.assertEqual(result.outcome,"error")
        self.assertEqual(observed,[False])

    def test_tc031_oserror_after_deadline_splits_by_returned_entry(self):
        for after_append in (False,True):
            with self.subTest(after_append=after_append):
                prepared = raw_log.prepare("made-up",{})
                clock = [time.monotonic()]
                def expired(*args,**kwargs):
                    clock[0] = prepared.deadline+0.001
                    raise OSError("made-up private detail")
                target = self.log if after_append else files
                name = "_marker" if after_append else "append_jsonl"
                # Patch only the raw append; diagnostics use the real writer.
                original = files.append_jsonl
                def writer(*args,**kwargs):
                    return expired() if args[2]=="TBL-007" else original(*args,**kwargs)
                with mock.patch.object(raw_log.time,"monotonic",side_effect=lambda:clock[0]), \
                        mock.patch.object(target,name,expired if after_append else writer):
                    result = self.log.append("prompt",prepared,diagnostic_deadline=clock[0]+3,when=WHEN)
                self.assertEqual(result.outcome,"deadline" if after_append else "lock-busy")
                self.assertEqual(result.entry is not None,after_append)
        self.assertEqual([r["error"] for r in self.failures()],["lock-busy","deadline"])

    def test_tc319_marker_failure_does_not_erase_a_returned_write_or_log_error_text(self):
        with mock.patch.object(self.log,"_marker",side_effect=PermissionError("made-up private detail")):
            result = self.record()
        self.assertEqual(result.outcome,"error")
        self.assertEqual(self.entries(),[result.entry])
        self.assertEqual([r["error"] for r in self.failures()],["PermissionError"])
        self.assertNotIn(b"made-up private detail",b"".join(p.read_bytes() for p in self.root.rglob("*") if p.is_file()))

    def test_tc029_no_library_error_prints_or_imports_network_or_sqlite(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.record()
        self.assertEqual(out.getvalue()+err.getvalue(),"")
        scripts = Path(__file__).resolve().parent.parent / "plugins/corthex-memory/skills/corthex-memory/scripts"
        code = 'import sys;sys.path.insert(0,sys.argv[1]);import memory_lib.raw_log;assert not set(("socket","ssl","http","sqlite3")) & set(sys.modules)'
        result = subprocess.run([sys.executable,"-c",code,str(scripts)],capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr.decode("utf-8","replace"))
