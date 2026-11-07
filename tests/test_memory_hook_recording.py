"""Recording hooks run as real subprocesses against disposable project stores."""

import copy
import json
import multiprocessing
import os
import string
import tempfile
import time
from pathlib import Path

from test_memory_hooks import HookCase
from test_memory_store import AT
from test_memory_redaction import ORDINARY, key_block, luhn, random_text, resident_numbers, secret_examples
from test_memory_locks import holder
from test_memory_diagnostics import hold_logs
from memory_lib import base, files, hooks, raw_log
from memory_lib import clock as memory_clock


class HookRecordingTest(HookCase):
    def run_functional(self,*args,**kwargs):
        return self.run_hook(*args,**kwargs)

    @staticmethod
    def crossing_diagnostic_gate():
        return ("from memory_lib import diagnostics,clock\ngate=diagnostics.Diagnostics.read_gate\n"
                "now=clock.now\noffset=[0.0]\nclock.now=lambda:now()+offset[0]\ncalls=[0]\n"
                "def crossing(self,deadline,*args,**kwargs):\n    calls[0]+=1\n"
                "    if calls[0]==2:\n        offset[0]+=max(0,deadline-clock.now())+0.02\n"
                "    return gate(self,deadline,*args,**kwargs)\ndiagnostics.Diagnostics.read_gate=crossing\n")

    def test_tc326_small_cut_nul_or_damaged_first_line_does_not_stop_real_hooks(self):
        for name, data in (("cut", b'{"seq":1,"text":"cut'), ("nul", b"\0" * 180),
                           ("damaged", b"broken\n")):
            with self.subTest(kind=name):
                prompt = dict(self.event("prompt"), session_id="small-damaged-" + name)
                answer = dict(self.event("end-of-turn"), session_id=prompt["session_id"])
                log = raw_log.RawLog(self.memory, "sample", "claude-code", prompt["session_id"])
                log.path.write_bytes(data)
                before = len(self.records("failures"))
                self.run_hook("prompt", prompt)
                self.run_hook("end-of-turn", answer)
                rows = files.read_jsonl(log.path)
                self.assertEqual([(row["seq"], row["turn"], row["kind"]) for row in rows],
                                 [(1, 1, "prompt"), (2, 1, "answer")])
                prefix = data if data.endswith(b"\n") else data + b"\n"
                self.assertTrue(log.path.read_bytes().startswith(prefix + b'{"id":'))
                failures = self.records("failures")[before:]
                self.assertEqual([(row["error"], row.get("count")) for row in failures], [("damaged-line", 1)])
                self.assertEqual([(row["hook"], row["outcome"]) for row in self.records("hooks")[-2:]],
                                 [("prompt", "ok"), ("end-of-turn", "ok")])
                self.assertEqual(len(list(log.markers.glob("*." + log.log + ".*"))), 1)

    def test_tc323_expired_recording_wait_reclaims_a_stale_raw_lease(self):
        log = raw_log.RawLog(self.memory, "sample", "claude-code", self.event("prompt")["session_id"])
        path = log.path.with_suffix(".lock")
        from memory_lib import locks
        path.write_text(json.dumps({"pid": os.getpid(), "device": self.header["device"], "at": AT,
                                    "token": locks.secrets.token_hex(16)}), encoding="utf-8")
        past = time.time() - 20
        os.utime(str(path), (past, past))
        patch = ("from memory_lib import raw_log\nprepare=raw_log.prepare\n"
                 "def expired(*args,**kwargs):\n    value=prepare(*args,**kwargs)\n"
                 "    return raw_log.Prepared(value.text,value.cut,memory_clock.now()-1)\nraw_log.prepare=expired")
        self.run_hook("prompt", patch=patch)
        self.assertEqual([(row["seq"], row["kind"]) for row in self.raw()], [(1, "prompt")])
        self.assertEqual(len(self.markers()), 1)
        self.assertFalse(path.exists())
        self.assertEqual(self.records("failures"), [])
        self.outcome("ok")

    def test_tc046_exception_diagnostic_survives_crossing_its_deadline_in_read_gate(self):
        patch = self.crossing_diagnostic_gate() + ("from memory_lib import raw_log\n"
                 "def fail(*args,**kwargs):\n    raise OSError('private-error-fixture')\nraw_log.RawLog.append=fail")
        self.run_hook("end-of-turn", patch=patch)
        self.assertEqual(self.raw(), [])
        self.assertEqual([row["error"] for row in self.records("failures")], ["OSError"])
        self.outcome("error")
        self.assertGreaterEqual(self.records("hooks")[-1]["ms"], 300)

    def test_tc046_missing_folder_diagnostic_survives_crossing_deadline_without_timing(self):
        folder = self.root / "projects/sample/raw"
        folder.rmdir()
        self.run_hook("end-of-turn", patch=self.crossing_diagnostic_gate())
        self.assertFalse(folder.exists())
        self.assertEqual(self.raw(), [])
        self.assertEqual(self.markers(), [])
        self.assertEqual([row["error"] for row in self.records("failures")], ["FileNotFoundError"])
        self.assertEqual(self.records("hooks"), [])

    def test_tc010_configuration_restore_notice_survives_late_diagnostic_read_gate(self):
        path = self.root / "configuration.json"
        backup = path.with_name("configuration.json.bak")
        path.replace(backup)
        self.run_hook("end-of-turn", patch=self.crossing_diagnostic_gate())
        self.assertTrue(path.exists())
        self.assertFalse(backup.exists())
        self.assertEqual([row["error"] for row in self.records("failures")], ["restored"])
        self.assertEqual(len(self.raw()), 1)
        self.outcome("ok")
        self.assertGreaterEqual(self.records("hooks")[-1]["ms"], 300)

    def late_recording(self, phase):
        counter = self.folder / "late-redaction-count"
        patch = ("from pathlib import Path\nfrom memory_lib import clock, projects, redaction\n"
                 "now = clock.now\noffset = [0.0]\nclock.now = lambda: now()+offset[0]\n"
                 "find = projects.find\n"
                 "def delayed_find(*args):\n    result = find(*args)\n"
                 + ("    offset[0] = 1.2\n" if phase=="before-process" else "") +
                 "    return result\nprojects.find = delayed_find\n"
                 "process = hooks.process\nlimit = [None]\n"
                 "def delayed_process(frame):\n    limit[0] = frame.deadline\n"
                 + ("    offset[0] = 1.2\n" if phase=="before-redaction" else "") +
                 "    return process(frame)\nhooks.process = delayed_process\n"
                 "redact = redaction.redact\n"
                 "def counted(*args, **kwargs):\n    assert clock.now() >= limit[0]\n"
                 "    path = Path("+repr(str(counter))+")\n"
                 "    count = int(path.read_text()) if path.exists() else 0\n"
                 "    path.write_text(str(count+1))\n    result = redact(*args, **kwargs)\n"
                 "    offset[0] += 0.05\n    return result\nredaction.redact = counted")
        for index,hook in enumerate(("prompt","end-of-turn","end"),1):
            self.run_hook(hook,patch=patch)
            self.assertEqual(len(self.raw()),index)
            self.assertEqual(int(counter.read_text()),min(index,2))
            self.assertEqual(len(self.markers()),1)
            self.outcome("ok")
            self.assertGreaterEqual(self.records("hooks")[-1]["ms"],1250 if hook!="end" else 1200)
        self.assertEqual([r["kind"] for r in self.raw()],["prompt","answer","end"])
        self.assertEqual(self.records("failures"),[])

    def test_tc325_arrival_after_the_hook_deadline_still_calls_process(self):
        self.late_recording("before-process")

    def test_tc325_arrival_after_the_hook_deadline_still_redacts_and_records(self):
        self.late_recording("before-redaction")

    def test_tc031_restore_lock_busy_before_raw_lease_reports_contention(self):
        patch = ("from memory_lib import raw_log, locks\noriginal = raw_log.RawLog.__init__\n"
                 "def initialize(log, *args):\n    original(log, *args)\n    record = log.store.record\n"
                 "    def busy(*args, **kwargs):\n        log.store.record = record\n        raise locks.LockBusy()\n"
                 "    log.store.record = busy\nraw_log.RawLog.__init__ = initialize")
        self.run_functional("prompt",patch=patch)
        self.assertEqual(self.raw(),[])
        self.assertEqual(self.records("failures")[-1]["error"],"lock-busy")
        self.outcome("lock-busy")

    def test_tc031_lost_header_fence_before_raw_lease_reports_lost_lock(self):
        patch = ("from memory_lib import raw_log, locks\noriginal = raw_log.RawLog.__init__\n"
                 "def initialize(log, *args):\n    original(log, *args)\n    record = log.store.record\n"
                 "    def lost(*args, **kwargs):\n        log.store.record = record\n        raise locks.LostLock()\n"
                 "    log.store.record = lost\nraw_log.RawLog.__init__ = initialize")
        self.run_functional("end-of-turn",patch=patch)
        self.assertEqual(self.raw(),[])
        self.assertEqual(self.records("failures")[-1]["error"],"lost-lock")
        self.outcome("error")

    def test_tc011_header_blocked_before_raw_lease_stops_before_diagnostics(self):
        for content in (b'{"format":2}',b'broken'):
            for hook in ("prompt","end-of-turn","end"):
                (self.root / "store.json").write_bytes(base.json_bytes(self.header,"TBL-001"))
                backup = self.root / "store.json.bak"
                if backup.exists():
                    backup.unlink()
                before = self.snapshot()
                before.pop("store.json")
                patch = ("from memory_lib import raw_log, diagnostics\noriginal = raw_log.RawLog.__init__\n"
                         "def initialize(log, *args):\n    original(log, *args)\n"
                         "    (log.store.folder / 'store.json').write_bytes("+repr(content)+")\n"
                         "    def forbidden(*args, **kwargs):\n        raise AssertionError('blocked store diagnostics')\n"
                         "    diagnostics.Diagnostics.failure = forbidden\n    diagnostics.Diagnostics.timing = forbidden\n"
                         "raw_log.RawLog.__init__ = initialize")
                self.run_functional(hook,patch=patch)
                after = self.snapshot()
                after.pop("store.json")
                self.assertEqual(after,before)

    def test_tc046_missing_raw_folder_logs_only_the_class_without_timing(self):
        folder = self.root / "projects/sample/raw"
        folder.rmdir()
        for hook in ("prompt","end-of-turn","end"):
            self.run_functional(hook)
        self.assertFalse(folder.exists())
        self.assertEqual(self.raw(),[])
        self.assertEqual(self.markers(),[])
        self.assertEqual(self.records("hooks"),[])
        self.assertEqual([row["error"] for row in self.records("failures")],["FileNotFoundError"]*3)

    def test_tc046_missing_marker_folder_keeps_entries_and_logs_only_the_class(self):
        folder = self.root / "projects/sample/unprocessed"
        folder.rmdir()
        for hook in ("prompt","end-of-turn"):
            self.run_functional(hook)
        self.assertFalse(folder.exists())
        self.assertEqual([row["seq"] for row in self.raw()],[1,2])
        self.assertEqual(self.records("hooks"),[])
        self.assertEqual([row["error"] for row in self.records("failures")],["FileNotFoundError"]*2)

    def test_tc046_marker_folder_lost_during_creation_keeps_append_without_timing(self):
        patch = ("from pathlib import Path\nfrom memory_lib import base, clock\n"
                 "opened, now = base.private_open, clock.now\noffset = [0.0]\n"
                 "clock.now = lambda: now() + offset[0]\n"
                 "def missing(path, *args, **kwargs):\n    folder = Path(path).parent\n"
                 "    if folder.name == 'unprocessed':\n        folder.rmdir()\n        offset[0] = 1.0\n"
                 "    return opened(path, *args, **kwargs)\nbase.private_open = missing")
        self.run_hook("prompt",patch=patch)
        self.assertEqual(len(self.raw()),1)
        self.assertEqual(self.markers(),[])
        self.assertEqual(self.records("hooks"),[])
        self.assertEqual([row["error"] for row in self.records("failures")],["FileNotFoundError"])

    def raw(self):
        return [row for path in sorted((self.root / "projects").glob("*/raw/*.jsonl"))
                for row in files.read_jsonl(path)]

    def markers(self):
        return list((self.root / "projects").glob("*/unprocessed/*"))

    def configure(self, **changes):
        document = copy.deepcopy(self.memory.configuration(deadline=memory_clock.now() + 2).document)
        for key, value in changes.items():
            if value is None:
                document.pop(key, None)
            else:
                document[key] = value
        self.memory.write_configuration(document, memory_clock.now() + 2)

    def exclude(self, kinds=(), folders=()):
        document = copy.deepcopy(self.memory.configuration(deadline=memory_clock.now() + 2).document)
        document["projects"]["sample"]["left_out"] = {"kinds": list(kinds), "folders": list(folders)}
        self.memory.write_configuration(document, memory_clock.now() + 2)

    def outcome(self, expected):
        self.assertEqual(self.records("hooks")[-1]["outcome"], expected)

    def test_tc037_prompt_entry_and_timing(self):
        self.run_functional("prompt")
        row, = self.raw()
        self.assertEqual((row["kind"], row["speaker"], row["text"], row["seq"], row["turn"]),
                         ("prompt", "user", "hello", 1, 1))
        self.assertEqual(len(self.markers()), 1)
        self.outcome("ok")

    def test_tc038_one_mebibyte_korean_prompt_is_cut_on_a_character(self):
        text = "가" * ((1024 * 1024) // 3) + "x"
        self.assertEqual(len(text.encode("utf-8")), 1024 * 1024)
        self.run_functional("prompt", dict(self.event("prompt"), prompt=text))
        row, = self.raw()
        self.assertTrue(row["text"] == text.encode("utf-8")[:512 * 1024].decode("utf-8", "ignore"))
        self.assertEqual(row["cut"], len(text.encode("utf-8")))

    def test_tc039_whitespace_prompt_has_no_entry_or_marker(self):
        self.run_functional("prompt", dict(self.event("prompt"), prompt=" \t\r\n  "))
        self.assertEqual(self.raw(), [])
        self.assertEqual(self.markers(), [])
        self.outcome("ok")

    def test_tc040_host_prefixes_and_prompt_exclusion(self):
        for prefix in hooks.HOST_PROMPTS:
            self.run_functional("prompt", dict(self.event("prompt"), prompt=" \n\t" + prefix + "fixture"))
            self.assertEqual(self.raw(), [])
            self.outcome("left-out")
        text = "A user quote contains " + hooks.HOST_PROMPTS[0]
        self.run_functional("prompt", dict(self.event("prompt"), prompt=text))
        self.assertEqual(len(self.raw()), 1)
        self.outcome("ok")
        self.exclude(kinds=["prompt"])
        self.run_functional("prompt")
        self.assertEqual(len(self.raw()), 1)
        self.outcome("left-out")

    def test_tc040_actual_agent_message_is_left_out_and_inline_quote_is_kept(self):
        marker = "AGENT_ONLY_FIXTURE_141421"
        message = '<agent-message from="fixture-agent">\n' + marker + '\n</agent-message>'
        self.run_functional("prompt", dict(self.event("prompt"), prompt=" \n\t" + message))
        self.assertEqual(self.raw(), [])
        self.outcome("left-out")
        self.assertFalse(any(marker.encode() in p.read_bytes() for p in self.root.rglob("*") if p.is_file()))
        quoted = "A user quote contains " + message
        self.run_functional("prompt", dict(self.event("prompt"), prompt=quoted))
        self.assertEqual(self.raw()[0]["text"], quoted)
        self.outcome("ok")

    def test_tc041_redaction_failure_has_no_entry_or_error_text(self):
        patch = ("from memory_lib import redaction\ndef fail(*args):\n"
                 "    raise RuntimeError('private-redaction-error-fixture')\nredaction.redact = fail")
        self.run_functional("prompt", patch=patch)
        self.assertEqual(self.raw(), [])
        self.assertEqual(self.records("failures")[-1]["error"], "redaction")
        self.outcome("error")
        self.assertFalse(any(b"private-redaction-error-fixture" in p.read_bytes()
                             for p in self.root.rglob("*") if p.is_file()))

    def test_tc042_deadline_before_redaction_still_records(self):
        patch = ("from memory_lib import projects\noriginal = projects.find\n"
                 "def slow(*args):\n    time.sleep(0.92)\n    return original(*args)\nprojects.find = slow")
        self.run_hook("prompt", patch=patch)
        self.assertEqual(len(self.raw()), 1)
        self.assertEqual(self.records("failures"), [])
        self.assertGreaterEqual(self.records("hooks")[-1]["ms"], 900)
        self.outcome("ok")

    def test_tc012_consent_enabling_and_missing_store_gate_all_four_hooks(self):
        self.configure(consent=None)
        before = self.snapshot()
        for hook in hooks.EVENTS:
            self.run_functional(hook)
        self.assertEqual(self.snapshot(), before)
        self.configure(consent={"at": AT, "version": 1}, projects={"sample": {"enabled": False, "since": AT}})
        before = self.snapshot()
        for hook in hooks.EVENTS:
            self.run_functional(hook)
        self.assertEqual(self.snapshot(), before)
        missing = self.folder / "not-provisioned"
        for hook in hooks.EVENTS:
            self.run_functional(hook, changes={"CORTHEX_MEMORY_HOME": str(missing)})
        self.assertFalse(missing.exists())
        self.assertEqual(self.snapshot(), before)

    def test_tc043_only_the_final_answer_is_recorded_and_transcript_is_not_read(self):
        marker = "private-tool-transcript-fixture"
        transcript = self.folder / "transcript.jsonl"
        transcript.write_text(marker)
        touched = self.folder / "transcript-was-read"
        patch = ("from pathlib import Path\noriginal_open = Path.open\ndef guarded(path, *args, **kwargs):\n"
                 "    if str(path) == " + repr(str(transcript)) + ":\n"
                 "        Path(" + repr(str(touched)) + ").write_text('read')\n"
                 "        raise AssertionError('transcript must not be read')\n"
                 "    return original_open(path, *args, **kwargs)\nPath.open = guarded")
        self.run_functional("prompt")
        answer = "한국어 최종 답변입니다."
        event = dict(self.event("end-of-turn"), last_assistant_message=answer,
                     transcript_path=str(transcript), tool_inputs=marker, tool_outputs=marker)
        self.run_functional("end-of-turn", event, patch=patch)
        self.assertEqual([r["kind"] for r in self.raw()], ["prompt", "answer"])
        self.assertTrue(self.raw()[-1]["text"] == answer)
        self.assertFalse(touched.exists())
        self.assertFalse(any(marker.encode() in p.read_bytes() for p in self.root.rglob("*") if p.is_file()))
        self.outcome("ok")

    def test_tc044_missing_empty_and_nonstring_answers_have_no_entry(self):
        variants = [None, "", 5, False, [], {}]
        event = self.event("end-of-turn")
        event.pop("last_assistant_message")
        self.run_functional("end-of-turn", event)
        for value in variants:
            self.run_functional("end-of-turn", dict(self.event("end-of-turn"), last_assistant_message=value))
        self.assertEqual(self.raw(), [])
        self.assertTrue(all(r["outcome"] == "no-answer" for r in self.records("hooks")))

    def test_tc045_prompt_exclusion_does_not_exclude_answers(self):
        self.exclude(kinds=["prompt"])
        self.run_functional("prompt")
        self.run_functional("end-of-turn")
        row, = self.raw()
        self.assertEqual((row["kind"], row["turn"]), ("answer", 1))
        self.exclude(kinds=["answer"])
        self.run_functional("end-of-turn")
        self.assertEqual(len(self.raw()), 1)
        self.outcome("left-out")

    def test_tc046_answer_error_exits_quietly_and_records_only_safe_metadata(self):
        patch = ("from memory_lib import raw_log\ndef fail(*args, **kwargs):\n"
                 "    raise OSError('private-answer-error-fixture')\nraw_log.RawLog.append = fail")
        self.run_functional("end-of-turn", patch=patch)
        self.assertEqual(self.raw(), [])
        self.outcome("error")
        self.assertEqual(self.records("failures")[-1]["error"], "OSError")

    def test_tc047_deadline_after_redaction_preserves_the_entry(self):
        patch = ("from memory_lib import raw_log\noriginal_process = hooks.process\n"
                 "def controlled(frame):\n    original_prepare = raw_log.prepare\n"
                 "    def after(text):\n        prepared = original_prepare(text)\n"
                 "        frame.deadline = memory_clock.now() - 0.001\n"
                 "        frame.started = frame.deadline - hooks.SECONDS[frame.hook]\n"
                 "        return prepared\n    raw_log.prepare = after\n    return original_process(frame)\n"
                 "hooks.process = controlled")
        text = "a" * (512 * 1024)
        self.run_hook("end-of-turn", dict(self.event("end-of-turn"), last_assistant_message=text), patch=patch)
        row, = self.raw()
        self.assertTrue(row["text"] == text)
        self.assertEqual(self.records("failures"), [])
        self.outcome("ok")

    def test_tc048_end_reasons_and_boundary_exclusion(self):
        for reason in ("other", "logout", "x" * 65):
            self.run_functional("end", dict(self.event("end"), reason=reason))
        rows = self.raw()
        self.assertEqual([r.get("reason") for r in rows], ["other", "logout", None])
        self.assertTrue(all(r["kind"] == "end" and not {"text", "turn", "speaker"} & set(r) for r in rows))
        self.assertEqual(self.markers(), [])
        self.exclude(kinds=["boundary"])
        self.run_functional("end")
        self.assertEqual(len(self.raw()), 3)
        self.outcome("left-out")

    def test_tc049_end_normal_late_and_error_paths(self):
        self.run_hook("end")
        self.assertLess(self.records("hooks")[-1]["ms"], 500)
        patch = ("from memory_lib import projects\noriginal = projects.find\n"
                 "def slow(*args):\n    time.sleep(0.52)\n    return original(*args)\nprojects.find = slow")
        self.run_hook("end", patch=patch)
        self.assertEqual(len(self.raw()), 2)
        self.outcome("ok")
        self.assertEqual(self.records("failures"), [])
        patch = ("from memory_lib import raw_log\ndef fail(*args, **kwargs):\n"
                 "    raise OSError('private-end-error-fixture')\nraw_log.RawLog.append = fail")
        self.run_hook("end", patch=patch)
        self.assertEqual(len(self.raw()), 2)
        self.outcome("error")

    def test_tc030_entry_turns_continuation_and_resubmission_through_hooks(self):
        self.run_functional("prompt")
        self.run_functional("end-of-turn")
        self.run_functional("end-of-turn", dict(self.event("end-of-turn"), stop_hook_active=True))
        self.run_functional("end-of-turn")
        self.run_functional("prompt")
        self.assertEqual([(r["seq"], r["turn"]) for r in self.raw()], [(1, 1), (2, 1), (3, 1), (4, 4), (5, 5)])
        self.assertEqual(len(self.markers()), 3)

    def test_tc031_all_recording_hooks_skip_a_foreign_raw_lease(self):
        log = raw_log.RawLog(self.memory, "sample", "claude-code", self.event("prompt")["session_id"])
        parent, child = multiprocessing.Pipe()
        worker = multiprocessing.Process(target=holder, args=(child, str(log.path.with_suffix(".lock")), self.header["device"]))
        worker.start()
        try:
            self.assertTrue(parent.poll(10))
            self.assertTrue(parent.recv())
            for hook in ("prompt", "end-of-turn", "end"):
                self.run_hook(hook)
                self.assertEqual(self.records("failures")[-1]["error"], "lock-busy")
                self.outcome("lock-busy")
            self.assertEqual(self.raw(), [])
            self.assertEqual(self.markers(), [])
        finally:
            parent.send(True)
            worker.join(10)
            if worker.is_alive():
                worker.terminate()
                worker.join()
            parent.close()
            child.close()
        self.assertEqual(worker.exitcode, 0)

    def test_tc032_session_path_is_hashed_for_all_recording_entry_points(self):
        session = "../../outside"
        for hook in ("prompt", "end-of-turn", "end"):
            self.run_functional(hook, dict(self.event(hook), session_id=session))
        name = raw_log.log_name("claude-code", session)
        paths = list((self.root / "projects").glob("*/raw/*.jsonl"))
        self.assertEqual([p.name for p in paths], [name + ".jsonl"])
        self.assertEqual(len(self.raw()), 3)
        self.assertFalse((self.folder / "outside").exists())

    def test_tc322_late_marker_finishes_after_the_lock_wait_window(self):
        patch = ("from memory_lib import raw_log\noriginal = raw_log.RawLog._marker\n"
                 "def late(self, entry, check, prior=None):\n"
                 "    time.sleep(0.055)\n    return original(self, entry, check, prior)\nraw_log.RawLog._marker = late")
        self.run_hook("prompt", patch=patch)
        self.assertEqual(len(self.raw()), 1)
        self.assertEqual(len(self.markers()), 1)
        self.assertEqual(self.records("failures"), [])
        self.outcome("ok")

    def test_tc322_acquired_recording_finishes_past_each_whole_hook_deadline(self):
        patch = ("from memory_lib import locks, raw_log\nacquire = locks.Lock.acquire\n"
                 "def slow(lease, *args, **kwargs):\n    result = acquire(lease, *args, **kwargs)\n"
                 "    if lease.policy == locks.POLICIES['raw']:\n        time.sleep(1.01)\n"
                 "    return result\nlocks.Lock.acquire = slow\nappend = raw_log.RawLog.append\n"
                 "def checked(*args, **kwargs):\n    result = append(*args, **kwargs)\n"
                 "    assert result.outcome == 'ok' and result.entry is not None\n"
                 "    return result\nraw_log.RawLog.append = checked")
        for index,hook in enumerate(("prompt","end-of-turn","end"),1):
            self.run_hook(hook,patch=patch)
            self.assertEqual(len(self.raw()),index)
            self.assertEqual(len(self.markers()),1)
            self.outcome("ok")
            self.assertEqual(self.records("failures"),[])

    def test_tc323_hook_attempts_a_free_lock_after_the_wait_has_expired(self):
        patch = ("from memory_lib import raw_log\nprepare = raw_log.prepare\n"
                 "def expired(*args, **kwargs):\n    value = prepare(*args, **kwargs)\n"
                 "    return raw_log.Prepared(value.text, value.cut, memory_clock.now()-1)\n"
                 "raw_log.prepare = expired")
        recovery = ("initialize = raw_log.RawLog.__init__\n"
                    "def missing(log, *args):\n    initialize(log, *args)\n"
                    "    path = log.store.folder / 'store.json'\n"
                    "    path.replace(path.with_name('store.json.bak'))\n"
                    "raw_log.RawLog.__init__ = missing")
        for count,extra in enumerate(("",recovery),1):
            self.run_hook("prompt",patch=patch+"\n"+extra)
            self.assertEqual(len(self.raw()),count)
            self.assertEqual(len(self.markers()),count)
            self.outcome("ok")
        self.assertEqual([r["error"] for r in self.records("failures")],["restored"])

    def test_tc322_hook_finishes_acquired_store_recovery_then_attempts_raw_once(self):
        patch = ("from memory_lib import locks, raw_log\nacquire = locks.Lock.acquire\n"
                 "def slow(lease, *args, **kwargs):\n    result = acquire(lease, *args, **kwargs)\n"
                 "    if lease.policy == locks.POLICIES['store']:\n        time.sleep(1.01)\n"
                 "    return result\nlocks.Lock.acquire = slow\ninitialize = raw_log.RawLog.__init__\n"
                 "def missing(log, *args):\n    initialize(log, *args)\n"
                 "    path = log.store.folder / 'store.json'\n"
                 "    path.replace(path.with_name('store.json.bak'))\n"
                 "raw_log.RawLog.__init__ = missing")
        self.run_hook("prompt",patch=patch)
        self.assertEqual(len(self.raw()),1)
        self.assertEqual(len(self.markers()),1)
        self.outcome("ok")

    def test_tc049_benchmark_keeps_the_late_end_boundary(self):
        import bench_memory_hooks as bench
        with tempfile.TemporaryDirectory() as folder:
            state = bench.fixture(Path(folder),1,bench.SCRIPT)
            elapsed,outcome,entries = bench.attempt(state,"end","slow-end",0)
        self.assertGreaterEqual(elapsed,500)
        self.assertEqual(outcome,"ok")
        self.assertEqual(entries,1)

    def test_tc324_hook_does_not_append_without_a_complete_tail_sequence(self):
        log = raw_log.RawLog(self.memory,"sample","claude-code",self.event("prompt")["session_id"])
        before = b"x"*(8*1024*1024+1)
        log.path.write_bytes(before)
        self.run_hook("prompt")
        self.assertTrue(log.path.read_bytes()==before)
        self.assertEqual(self.markers(),[])
        self.assertEqual(self.records("failures")[-1]["error"],"damaged-line")
        self.outcome("error")

    def test_tc324_hook_answer_with_sequence_but_no_turn_is_an_orphan(self):
        self.run_hook("prompt")
        first, = self.raw()
        boundary = dict(first,kind="end",seq=700)
        for key in ("text","speaker","turn"): boundary.pop(key)
        line = base.json_bytes(boundary,"TBL-007",compact=True)
        log = raw_log.RawLog(self.memory,"sample","claude-code",first["session"])
        with log.path.open("ab") as output:
            output.write(line*(raw_log.TAIL_BYTES//len(line)+2))
        self.run_hook("end-of-turn",dict(self.event("end-of-turn"),stop_hook_active=True))
        last = self.raw()[-1]
        self.assertEqual((last["kind"],last["seq"],last["turn"]),("answer",701,701))
        self.assertEqual(len(self.markers()),2)

    def test_tc046_late_io_failure_keeps_its_code_and_error_timing(self):
        patch = ("from memory_lib import raw_log, clock\nnow = clock.now\noffset = [0.0]\n"
                 "clock.now = lambda: now()+offset[0]\n"
                 "def fail(*args, **kwargs):\n    offset[0] = 1.0\n"
                 "    raise OSError('private-late-error-fixture')\nraw_log.RawLog.append = fail")
        self.run_hook("end-of-turn",patch=patch)
        self.assertEqual(self.raw(),[])
        self.assertEqual([r["error"] for r in self.records("failures")],["OSError"])
        self.outcome("error")

    def test_tc031_late_restore_contention_keeps_lock_busy_timing(self):
        patch = ("from memory_lib import raw_log, locks, clock\nnow = clock.now\noffset = [0.0]\n"
                 "clock.now = lambda: now()+offset[0]\n"
                 "def busy(*args, **kwargs):\n    offset[0] = 1.0\n"
                 "    raise locks.LockBusy()\nraw_log.RawLog.append = busy")
        self.run_hook("end-of-turn",patch=patch)
        self.assertEqual(self.raw(),[])
        self.assertEqual([r["error"] for r in self.records("failures")],["lock-busy"])
        self.outcome("lock-busy")

    def test_tc014_busy_diagnostic_leases_leave_logs_empty(self):
        parent, child = multiprocessing.Pipe()
        worker = multiprocessing.Process(target=hold_logs, args=(child, str(self.root), self.header["device"]))
        worker.start()
        try:
            self.assertTrue(parent.poll(10))
            self.assertTrue(parent.recv())
            patch = ("from memory_lib import redaction\ndef fail(*args, **kwargs):\n"
                     "    raise RuntimeError('private-held-log-fixture')\nredaction.redact = fail")
            self.run_hook("prompt",patch=patch)
            self.assertEqual(self.records("hooks"), [])
            self.assertEqual(self.records("failures"), [])
            self.assertEqual(self.raw(), [])
        finally:
            parent.send(True)
            worker.join(10)
            if worker.is_alive():
                worker.terminate()
                worker.join()
            parent.close()
            child.close()
        self.assertEqual(worker.exitcode, 0)

    def test_tc015_deepest_enabled_project_receives_the_prompt(self):
        nested = self.repo / "nested"
        inside = nested / "inside"
        inside.mkdir(parents=True)
        for name in ("raw", "unprocessed"):
            base.private_directory(self.root / "projects" / base.project_folder_name("nested") / name)
        self.configure(projects={name: {"enabled": True, "since": AT} for name in ("sample", "nested")})
        (self.home / ".corthex/projects.json").write_text(json.dumps({"projects": [
            {"name": "sample", "path": str(self.repo)}, {"name": "nested", "path": str(nested)}]}))
        parent = self.root / "projects" / base.project_folder_name("sample")
        before = {str(p.relative_to(parent)):p.read_bytes() for p in parent.rglob("*") if p.is_file()}
        self.run_functional("prompt", dict(self.event("prompt"), cwd=str(inside)))
        paths = list((self.root / "projects").glob("*/raw/*.jsonl"))
        self.assertEqual([p.parent.parent.name for p in paths], [base.project_folder_name("nested")])
        self.assertEqual({str(p.relative_to(parent)):p.read_bytes() for p in parent.rglob("*") if p.is_file()},before)

    def test_tc017_unregistered_folder_changes_no_memory_file(self):
        outside = self.folder / "unregistered"
        outside.mkdir()
        before = self.snapshot()
        self.run_functional("prompt", dict(self.event("prompt"), cwd=str(outside)))
        self.assertEqual(self.snapshot(), before)

    def test_tc018_directory_case_follows_the_current_volume(self):
        alternate = self.repo.with_name(self.repo.name.upper())
        same = alternate.exists() and os.path.samefile(alternate, self.repo)
        if not alternate.exists():
            alternate.mkdir()
        self.run_functional("prompt", dict(self.event("prompt"), cwd=str(alternate)))
        self.assertEqual(len(self.raw()), int(same))

    def test_tc019_missing_unreadable_and_clashing_project_lists_have_safe_codes(self):
        registry = self.home / ".corthex/projects.json"
        registry.unlink()
        self.run_functional("prompt")
        self.assertEqual(self.records("failures")[-1]["error"], "no-project-list")
        patch = ("from pathlib import Path\noriginal_read = Path.read_bytes\ndef denied(path):\n"
                 "    if str(path) == " + repr(str(registry)) + ":\n        raise PermissionError('fixture')\n"
                 "    return original_read(path)\nPath.read_bytes = denied")
        self.run_functional("prompt", patch=patch)
        self.assertEqual(self.records("failures")[-1]["error"], "no-project-list")
        registry.write_text(json.dumps({"projects": [{"name": name, "path": str(self.repo)} for name in ("sample", "other")]}))
        self.run_functional("prompt")
        self.assertEqual(self.records("failures")[-1]["error"], "project-clash")
        self.assertEqual(self.records("hooks"), [])
        self.assertEqual(self.raw(), [])

    def test_tc020_missing_deleted_and_linked_cwd(self):
        event = self.event("prompt")
        event.pop("cwd")
        self.run_functional("prompt", event)
        self.assertEqual(len(self.raw()), 1)
        deleted = self.folder / "deleted"
        deleted.mkdir()
        deleted.rmdir()
        self.run_functional("prompt", dict(event, cwd=str(deleted)))
        self.assertEqual(len(self.raw()), 1)
        link = self.folder / "linked"
        try:
            link.symlink_to(self.repo, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("directory symlinks are unavailable on this volume")
        self.run_functional("prompt", dict(event, cwd=str(link)))
        self.assertEqual(len(self.raw()), 2)

    def test_tc022_024_private_spans_never_reach_the_raw_log(self):
        secret = random_text(32)
        for source, expected in (("<private>my address</private> hi", "[redacted:private] hi"),
                                 ("<PRIVATE>a</Private> b", "[redacted:private] b"),
                                 ("a <private> b c", "a [redacted:private]"),
                                 ("x<PRIVATE>" + secret + "</private>y", "x[redacted:private]y"),
                                 ("x<private>" + secret, "x[redacted:private]")):
            self.run_functional("prompt", dict(self.event("prompt"), prompt=source))
            self.assertTrue(self.raw()[-1]["text"] == expected)
        self.assertFalse(any(secret.encode() in p.read_bytes() for p in self.root.rglob("*") if p.is_file()))

    def test_tc023_known_key_formats_and_private_keys_are_redacted_through_the_hook(self):
        examples = secret_examples()
        text = "\n".join(value for _, value in examples)
        expected = "\n".join("[redacted:" + kind + "]" for kind, _ in examples)
        for hook,field in (("prompt","prompt"),("end-of-turn","last_assistant_message")):
            self.run_functional(hook,dict(self.event(hook),**{field:text}))
            self.assertTrue(self.raw()[-1]["text"] == expected)
        for name in ("PRIVATE KEY", "RSA PRIVATE KEY", "EC PRIVATE KEY", "ENCRYPTED PRIVATE KEY"):
            for closed in (True, False):
                text = key_block(name,random_text(96),closed)
                for hook,field in (("prompt","prompt"),("end-of-turn","last_assistant_message")):
                    self.run_functional(hook,dict(self.event(hook),**{field:text}))
                    self.assertTrue(self.raw()[-1]["text"] == "[redacted:private-key]")
        stored = b"".join(p.read_bytes() for p in self.root.rglob("*") if p.is_file())
        self.assertTrue(all(value.encode() not in stored for _, value in examples))

    def test_tc395_397_korean_names_and_personal_numbers_are_redacted_through_the_hook(self):
        value, card, resident = "k" + random_text(15), luhn("4" + random_text(14, string.digits)), resident_numbers()[0]
        text = ("비밀번호: " + value + " 그리고 password: " + value + "\nAPI 키는 " + value + "\n카드 " + card +
                "\n주민번호 " + resident + "\n" + "\n".join(ORDINARY))
        expected = ("비밀번호: [redacted:assigned-secret] 그리고 password: [redacted:assigned-secret]\n"
                    "API 키는 [redacted:assigned-secret]\n카드 [redacted:card-number]\n"
                    "주민번호 [redacted:resident-number]\n" + "\n".join(ORDINARY))
        for hook, field in (("prompt", "prompt"), ("end-of-turn", "last_assistant_message")):
            self.run_functional(hook, dict(self.event(hook), **{field: text}))
            self.assertTrue(self.raw()[-1]["text"] == expected)
        stored = b"".join(p.read_bytes() for p in self.root.rglob("*") if p.is_file())
        self.assertTrue(all(secret.encode() not in stored for secret in (value, card, resident)))

    def test_tc025_memory_and_environment_values_are_masked(self):
        first, second, environment, short = random_text(32), random_text(32), random_text(16), random_text(8)
        changes = {"CORTHEX_MEMORY_ANTHROPIC_API_KEY": first, "CORTHEX_MEMORY_OPENAI_API_KEY": second,
                   "DEPLOY_TOKEN": environment, "SHORT_KEY": short}
        self.run_functional("prompt", dict(self.event("prompt"), prompt=" ".join((first, second, environment, short))), changes)
        self.assertTrue(self.raw()[-1]["text"] == "[redacted:memory-key] [redacted:memory-key] [redacted:environment] "+short)

    def test_tc026_numeric_lookalikes_url_credentials_and_authorization(self):
        value = random_text(24)
        source = "max_tokens: 64000\ntoken = 5\nhttps://fixture:" + value + "@example.invalid/x\nAuthorization: Bearer " + value
        expected = "max_tokens: 64000\ntoken = 5\nhttps://[redacted:url-credentials]@example.invalid/x\nAuthorization: [redacted:authorization]"
        self.run_functional("prompt", dict(self.event("prompt"), prompt=source))
        self.assertTrue(self.raw()[-1]["text"] == expected)

    def test_tc021_excluded_folder_and_its_descendants_apply_to_all_recording_kinds(self):
        excluded = self.repo / "left-out"
        inside = excluded / "inside"
        inside.mkdir(parents=True)
        sibling = self.repo / "left-out-other"
        sibling.mkdir()
        self.exclude(folders=["left-out"])
        for hook in ("prompt", "end-of-turn", "end"):
            self.run_functional(hook, dict(self.event(hook), cwd=str(inside)))
            self.outcome("left-out")
        self.assertEqual(self.raw(), [])
        self.run_functional("prompt", dict(self.event("prompt"), cwd=str(sibling)))
        self.assertEqual(len(self.raw()), 1)

    def test_tc040_041_redaction_runs_once_and_prompt_exclusion_follows_it(self):
        counter = self.folder / "redaction-count"
        patch = ("from pathlib import Path\nfrom memory_lib import redaction\noriginal = redaction.redact\n"
                 "def counted(*args, **kwargs):\n    path = Path(" + repr(str(counter)) + ")\n"
                 "    number = int(path.read_text()) if path.exists() else 0\n"
                 "    path.write_text(str(number+1))\n    return original(*args, **kwargs)\nredaction.redact = counted")
        for hook in ("prompt", "end-of-turn"):
            self.run_functional(hook, patch=patch)
        self.assertEqual(counter.read_text(), "2")
        self.exclude(kinds=["prompt"])
        self.run_functional("prompt", patch=patch)
        self.assertEqual(counter.read_text(), "3")
        self.outcome("left-out")
        self.exclude(kinds=["answer"])
        self.run_functional("end-of-turn", patch=patch)
        self.assertEqual(counter.read_text(), "3")

    def test_tc048_recording_never_starts_a_worker_or_emits_recall(self):
        self.configure(triggers={"turns": 1, "minutes": 1})
        self.run_functional("prompt")
        patch = ("import subprocess\ndef forbidden(*args, **kwargs):\n"
                 "    raise AssertionError('recording must not start a process')\nsubprocess.Popen = forbidden")
        for hook in ("end-of-turn", "end"):
            self.run_functional(hook, changes={"CORTHEX_MEMORY_ANTHROPIC_API_KEY": random_text(32)}, patch=patch)
            self.outcome("ok")
