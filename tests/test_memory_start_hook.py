"""TASK-017: actual start-hook subprocesses and owned detached maintenance."""
import contextlib
import csv
import io
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from test_memory_hooks import HookCase
from test_memory_store import AT, SCRIPTS
from test_memory_worker_launch import fixture_child_exit
import test_memory_worker_runtime as runtime_fixture
from test_memory_worker_runtime import CHILD, ENTRY, MARKER
from memory_lib import base, clock, context, files, hooks, start_memory, store, worker_launch


@contextlib.contextmanager
def deny_store_writes(case):
    root = case.root.resolve()
    case.assertEqual(root.parent, case.folder.resolve())
    if os.name == "nt":
        system = Path(os.environ["SystemRoot"]) / "System32"
        case.assertTrue(system.is_absolute())
        result = subprocess.run([str(system / "whoami.exe"), "/user", "/fo", "csv", "/nh"],
                                capture_output=True, check=True, timeout=10)
        sid = next(csv.reader(result.stdout.decode("utf-8", "replace").splitlines()))[-1]
        case.assertTrue(sid.startswith("S-1-") and all(c in "S-0123456789" for c in sid))
        command = [str(system / "icacls.exe"), str(root)]
        try:
            subprocess.run(command + ["/deny", "*" + sid + ":(OI)(CI)(WD,AD,WEA,WA)", "/Q"],
                           capture_output=True, check=True, timeout=10)
            yield
        finally:
            subprocess.run(command + ["/remove:d", "*" + sid, "/Q"],
                           capture_output=True, check=True, timeout=10)
    else:
        directories = [root] + [p for p in root.rglob("*") if p.is_dir()]
        try:
            for path in directories:
                path.chmod(0o500)
            if os.access(root, os.W_OK):
                case.skipTest("This user bypasses the owned read-only directory mode")
            yield
        finally:
            for path in directories:
                path.chmod(0o700)


@contextlib.contextmanager
def owned_worker_exit(case, receipt):
    if os.name == "nt":
        with fixture_child_exit(case, receipt):
            yield
        return
    pid = receipt["events"][-1]["pid"]
    def identity():
        try:
            raw = Path("/proc/%d/stat" % pid).read_text()
        except FileNotFoundError:
            if sys.platform.startswith("linux"):
                return None
            result = subprocess.run(["/bin/ps", "-p", str(pid), "-o", "stat=", "-o", "lstart="],
                                    capture_output=True, check=False, timeout=2,
                                    env=dict(os.environ, LC_ALL="C"))
            value = result.stdout.decode("ascii").strip().split(None, 1)
            return (value[0][0], value[1]) if result.returncode == 0 and len(value) == 2 else None
        fields = raw[raw.rindex(")") + 2:].split()
        return fields[0], fields[19]
    first = identity()
    try:
        yield
    finally:
        until = time.perf_counter() + 15
        while True:
            current = identity()
            if current is None or current[0] == "Z" or first is not None and current[1] != first[1]:
                break  # Exited/reaped, or that exact process exited before PID reuse.
            case.assertLess(time.perf_counter(), until, "Owned POSIX worker did not exit")
            time.sleep(.02)


class StartHookTest(HookCase):
    def text(self, **kwargs):
        result = self.run_hook("start", **kwargs)
        self.assertEqual(len(result.stdout.splitlines()), 1)
        return json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]

    def raw(self, host="claude-code", session="session-fixture"):
        from memory_lib.raw_log import log_name
        path = self.root / "projects/sample/raw" / (log_name(host, session) + ".jsonl")
        return files.read_jsonl(path) if path.exists() else []

    def test_tc053_empty_memory_and_start_boundary_use_the_real_entry(self):
        text = self.text()
        self.assertIn("## Memory\n\n" + start_memory.REFERENCE + "\n\n" + start_memory.NOTHING, text)
        rows = self.raw()
        self.assertEqual([(row["seq"], row["kind"], row["event"]) for row in rows], [(1, "start", "start")])
        self.assertNotIn("text", rows[0])
        self.assertEqual(self.records("hooks")[-1]["outcome"], "ok")

    def test_project_approval_invalid_unicode_keeps_context_and_start_boundaries(self):
        (self.home / ".corthex/profile.json").write_text(json.dumps({"ask_before": ["payments"]}), encoding="utf-8")
        for host, changes in [("claude-code", {}), ("codex", {"CLAUDECODE": "", "PLUGIN_ROOT": str(SCRIPTS.parents[2])})]:
            for number, bad in enumerate(("\ud800", "\udfff")):
                session = host + "-invalid-approval-" + str(number)
                (self.repo / ".corthex/project.json").write_text(json.dumps({"name": "sample", "ask_before": ["deploys" + bad]}), encoding="utf-8")
                text = self.text(payload=dict(self.event("start"), session_id=session), changes=changes)
                self.assertIn("## Working principles", text)
                self.assertIn("- Ask before: payments", text)
                self.assertIn("Project ask_before is invalid", text)
                self.assertIn("## Memory", text)
                self.assertEqual([(row["kind"], row["event"]) for row in self.raw(host, session)], [("start", "start")])
                self.assertEqual(self.records("hooks")[-1]["outcome"], "ok")

    def test_tc066_each_start_source_and_both_host_names_are_preserved(self):
        for host, env in [("claude-code", {}), ("codex", {"CLAUDECODE": "", "PLUGIN_ROOT": str(SCRIPTS.parents[2])})]:
            for source in ("startup", "resume", "clear", "compact", "fork"):
                session = host + "-" + source
                event = dict(self.event("start"), session_id=session, source=source)
                self.text(payload=event, changes=env)
                self.run_hook("prompt", dict(self.event("prompt"), session_id=session), changes=env)
                self.run_hook("end", dict(self.event("end"), session_id=session), changes=env)
                rows = self.raw(host, session)
                self.assertEqual([r["kind"] for r in rows], ["start", "prompt", "end"])
                self.assertEqual(rows[0]["event"], "start" if source == "startup" else source)
                self.assertFalse(any("text" in rows[i] for i in (0, 2)))

    def test_tc032_path_like_session_id_stays_in_the_owned_raw_folder(self):
        self.text(payload=dict(self.event("start"), session_id="../../outside"))
        self.assertEqual(len(self.raw(session="../../outside")), 1)
        self.assertFalse((self.folder / "outside").exists())

    def test_boundary_and_folder_exclusions_still_show_memory(self):
        for choices in ({"kinds": ["boundary"]}, {"folders": ["private"]}):
            self.memory.write_configuration({"consent": {"at": AT, "version": 1},
                "projects": {"sample": {"enabled": True, "since": AT, "left_out": choices}}}, clock.now() + 2)
            private = self.repo / "private"
            private.mkdir(exist_ok=True)
            event = dict(self.event("start"), cwd=str(private)) if "folders" in choices else self.event("start")
            self.assertIn(start_memory.NOTHING, self.text(payload=event))
            self.assertEqual(self.raw(), [])
            self.assertEqual(self.records("hooks")[-1]["outcome"], "left-out")

    def test_tc055_missing_consent_shows_only_the_consent_notice_without_recording(self):
        self.memory.write_configuration({"projects": {"sample": {"enabled": True, "since": AT}}}, clock.now() + 2)
        before = self.snapshot()
        text = self.text()
        self.assertIn("Memory records nothing on this device until the user consents to version 1 of the consent text.", text)
        self.assertIn(start_memory.NOTHING, text)
        self.assertNotIn("CORTHEX_MEMORY_ANTHROPIC_API_KEY", text)
        self.assertEqual(self.snapshot(), before)

    def test_tc055_opaque_or_missing_store_records_are_readonly_and_safe(self):
        record = self.root / "store.json"
        for value, message in [(b'{"format":2}', "the store format is not supported"),
                               (b"broken-private-value", "the store record is damaged"),
                               (None, "the store record is missing")]:
            if value is None:
                record.unlink()
            else:
                record.write_bytes(value)
            before = self.snapshot()
            text = self.text()
            self.assertIn("## Memory\n\nMemory could not be read: " + message + ". The memory status says more.", text)
            self.assertNotIn(start_memory.REFERENCE, text)
            self.assertNotIn("private-value", text)
            self.assertEqual(self.snapshot(), before)

    def test_tc055_relative_home_never_exposes_the_value_or_changes_files(self):
        before = self.snapshot()
        text = self.text(changes={"CORTHEX_MEMORY_HOME": "relative-private-value"})
        self.assertIn("## Memory\n\nMemory could not be read: CORTHEX_MEMORY_HOME is not an absolute path.", text)
        self.assertNotIn("relative-private-value", text)
        self.assertEqual(self.snapshot(), before)

    def test_tc055_configuration_error_names_only_its_sanitized_field(self):
        primary = self.root / "configuration.json"
        primary.write_text('{"retention":{"days":"private-fixture-value"}}', encoding="utf-8")
        before = self.snapshot()
        text = self.text()
        self.assertIn("configuration is invalid at retention.days.", text)
        self.assertNotIn("private-fixture-value", text)
        self.assertNotIn(start_memory.REFERENCE, text)
        self.assertEqual(self.raw(), [])
        self.assertEqual(self.records("hooks"), [])
        self.assertEqual(self.records("failures")[-1]["error"], "configuration-invalid")
        self.assertEqual(primary.read_bytes(), before["configuration.json"][0])

    def test_tc069_composition_errors_keep_base_fixed_notice_and_safe_diagnostics(self):
        for name, error in [("build_summary", "ValueError"), ("consent_notices", "PermissionError")]:
            receipt = self.folder / (name + "-maintenance.jsonl")
            patch = ("from memory_lib import start_memory\ndef fail(*a,**k):\n    raise " + error + "('private-fixture-value')\nstart_memory." + name + "=fail")
            patch += ("\nfrom pathlib import Path\nfrom memory_lib import worker_launch\n"
                      "def captured(memory,project,reason,deadline,logger,**options):\n"
                      "    with Path(" + repr(str(receipt)) + ").open('a',encoding='utf-8') as target:\n"
                      "        target.write(json.dumps({'project':project,'reason':reason,'device':options['expected_device']})+'\\n')\n"
                      "    return False\nworker_launch.launch=captured")
            text = self.text(patch=patch, worker=True)
            self.assertIn("- sample", text)
            self.assertIn("## Memory\n\nMemory could not be read: an internal memory error occurred. The memory status says more.", text)
            self.assertNotIn(start_memory.REFERENCE, text)
            self.assertNotIn("private-fixture-value", text)
            self.assertEqual(self.records("failures")[-1]["error"], error)
            self.assertEqual(self.records("hooks")[-1]["outcome"], "error")
            self.assertTrue(receipt.exists(), "Summary failure skipped required maintenance")
            self.assertEqual([json.loads(line) for line in receipt.read_text().splitlines()],
                             [{"project": "sample", "reason": "start", "device": self.header["device"]}])

    def test_failed_output_never_starts_a_worker_and_keeps_safe_failure(self):
        class Output(io.BytesIO):
            def write(self, value):
                raise BrokenPipeError("private-fixture-value")
        errors = io.StringIO()
        with mock.patch.dict(os.environ, {"CLAUDECODE": "1", "PLUGIN_ROOT": ""}), mock.patch.object(worker_launch, "launch") as launch, mock.patch.object(sys, "stderr", errors):
            hooks.run("start", clock.now(), io.BytesIO(json.dumps(self.event("start")).encode()), Output())
        launch.assert_not_called()
        self.assertEqual(errors.getvalue(), "corthex-memory: BrokenPipeError\n")
        self.assertEqual(self.records("hooks")[-1]["outcome"], "error")
        self.assertEqual(self.records("failures")[-1]["error"], "BrokenPipeError")

    def test_readonly_files_keep_all_four_hooks_quiet_through_acquired_write_retries(self):
        from memory_lib.raw_log import log_name
        raw = self.root / "projects/sample/raw" / (log_name("claude-code", "session-fixture") + ".jsonl")
        raw.write_bytes(b"")
        for kind in ("failures", "hooks"):
            (self.root / "logs" / (kind + "-" + base.utc_time()[:10] + ".jsonl")).write_bytes(b"")
        paths = [path for path in self.root.rglob("*") if path.is_file()]
        try:
            for path in paths:
                path.chmod(0o400)
            if os.name != "nt" and os.access(raw, os.W_OK):
                self.skipTest("This user bypasses the owned read-only file mode")
            before = self.snapshot()
            for hook in hooks.EVENTS:
                self.run_hook(hook)
            self.assertEqual(self.snapshot(), before)
        finally:
            for path in paths:
                path.chmod(0o600)

    def test_tc068_readonly_store_preserves_deadlines_and_exits_without_changes(self):
        from test_memory_hooks import SCRIPT
        # A fresh owned lease prevents a detached child whose work could race
        # the later restoration of this fixture's directory permissions.
        (self.root / "projects/sample/curation.lock").write_bytes(b"fresh fixture")
        wrapper = self.folder / "timed-entry.py"
        metric = self.folder / "entry-observation.json"
        wrapper.write_text("import sys,time\n"
            "deadlines=[]\nwaits=[]\n"
            "def observe(frame,event,arg):\n"
            "    if event!='call': return\n"
            "    name=frame.f_code.co_name\n    source=frame.f_code.co_filename\n    values=frame.f_locals\n"
            "    if source.endswith('diagnostics.py') and name in ('failure','timing'):\n"
            "        value=values.get('deadline')\n        deadlines.append(value if type(value) in (int,float) else None)\n"
            "    if source.endswith('locks.py') and name=='acquire' and values['self'].path.name in ('failures.lock','hooks.lock'):\n"
            "        waits.append({'deadline':values['deadline'],'at':time.perf_counter(),'wait':values['wait']})\n"
            "scope={'__name__':'__main__','__file__':" + repr(str(SCRIPT)) + "}\n"
            "sys.argv=[" + repr(str(SCRIPT)) + ",sys.argv[1]]\n"
            "sys.setprofile(observe)\n"
            "try:\n    exec(compile(open(" + repr(str(SCRIPT)) + ",'rb').read()," + repr(str(SCRIPT)) + ",'exec'),scope)\n"
            "except SystemExit as error:\n    assert error.code==0\n"
            "finally:\n    sys.setprofile(None)\n"
            "seconds=time.perf_counter()-scope['STARTED']\nimport json\n"
            "open(" + repr(str(metric)) + ",'w').write(json.dumps({'started':scope['STARTED'],'seconds':seconds,'diagnostic_deadlines':deadlines,'log_waits':waits}))\n", encoding="utf-8")
        before = self.snapshot()
        with deny_store_writes(self):
            self.assertEqual(store.MemoryStore().record(deadline=clock.now()+1)["device"], self.header["device"])
            # Verify that this process really cannot create the raw lease.
            refused = self.root / "projects/sample/fixture-write-probe"
            with self.assertRaises(PermissionError):
                refused.write_bytes(b"must be denied")
            for hook in hooks.EVENTS:
                result = subprocess.run([sys.executable, str(wrapper), hook],
                    input=json.dumps(self.event(hook)).encode(), env=self.environment(),
                    cwd=str(self.repo), capture_output=True, timeout=15)
                self.assertEqual((result.returncode, result.stderr), (0, b""))
                if hook == "start":
                    self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["hookEventName"], "SessionStart")
                else:
                    self.assertEqual(result.stdout, b"")
                observed = json.loads(metric.read_text())
                deadline = observed["started"] + hooks.SECONDS[hook]
                self.assertTrue(observed["diagnostic_deadlines"], hook)
                self.assertEqual(set(observed["diagnostic_deadlines"]), {deadline}, hook)
                for wait in observed["log_waits"]:
                    self.assertEqual(wait["deadline"], deadline, hook)
                late = [wait for wait in observed["log_waits"] if wait["wait"] and wait["at"] >= deadline]
                self.assertEqual(late, [], hook)
                # Includes imports and observer overhead; named-step budgets
                # are cooperative, not unconditional process-return limits.
                print("READONLY_HOOK " + json.dumps({"hook": hook, "ms": round(observed["seconds"]*1000, 3),
                      "budget_ms": hooks.SECONDS[hook]*1000, "original_deadline_preserved": True,
                      "late_log_waits": len(late), "instrumented": True}), flush=True)
        self.assertEqual(self.snapshot(), before)

    def test_missing_project_folder_does_not_provision_it(self):
        import shutil
        target = self.root / "projects/sample"
        self.assertEqual(target.resolve().parent, (self.root / "projects").resolve())
        shutil.rmtree(target)
        self.assertIn(start_memory.NOTHING, self.text())
        self.assertFalse(target.exists())
        self.assertEqual(self.records("hooks")[-1]["outcome"], "error")

    def test_no_store_or_unregistered_folder_keeps_the_byte_identical_base(self):
        expected = context.build_context(self.repo, self.home)
        self.assertEqual(self.text(changes={"CORTHEX_MEMORY_HOME": str(self.folder / "absent")}), expected)
        other = self.folder / "other"
        other.mkdir()
        self.assertEqual(self.text(payload=dict(self.event("start"), cwd=str(other))), context.build_context(other, self.home))
        output = io.BytesIO()
        event = dict(self.event("start"), cwd=str(other))
        with mock.patch.dict(os.environ, {"CLAUDECODE": "1", "PLUGIN_ROOT": ""}), mock.patch.object(worker_launch, "launch") as launch:
            hooks.run("start", clock.now(), io.BytesIO(json.dumps(event).encode()), output)
        launch.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["hookSpecificOutput"]["additionalContext"], context.build_context(other, self.home))
        self.assertEqual(self.records("hooks"), [])

    def test_disabled_registered_project_is_base_only_but_attempts_worker_after_flush(self):
        self.memory.write_configuration({"projects": {"sample": {"enabled": False, "since": AT}}}, clock.now() + 2)
        output = io.BytesIO()
        events = []
        class Output(io.BytesIO):
            def flush(self):
                events.append("flushed")
        output = Output()
        def launched(memory, project, reason, deadline, logger, **options):
            self.assertEqual(events, ["flushed"])
            self.assertTrue(output.getvalue().endswith(b"\n"))
            self.assertEqual((project, reason, options["expected_device"]), ("sample", "start", self.header["device"]))
            events.append("launched")
        with mock.patch.dict(os.environ, {"CLAUDECODE": "1", "PLUGIN_ROOT": ""}), mock.patch.object(worker_launch, "launch", side_effect=launched):
            hooks.run("start", clock.now(), io.BytesIO(json.dumps(self.event("start")).encode()), output)
        self.assertEqual(events, ["flushed", "launched"])
        self.assertNotIn("## Memory", json.loads(output.getvalue())["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(self.records("hooks"), [])

    def test_output_flush_precedes_worker_and_timing_is_last(self):
        events = []
        class Output(io.BytesIO):
            def flush(self):
                events.append("flushed")
        timing = hooks.Hook.finish
        def finish(frame, outcome):
            events.append("timing")
            return timing(frame, outcome)
        with mock.patch.dict(os.environ, {"CLAUDECODE": "1", "PLUGIN_ROOT": ""}), mock.patch.object(worker_launch, "launch", side_effect=lambda *a, **k: events.append("launched")), mock.patch.object(hooks.Hook, "finish", finish):
            hooks.run("start", clock.now(), io.BytesIO(json.dumps(self.event("start")).encode()), Output())
        self.assertEqual(events, ["flushed", "launched", "timing"])

    def test_memory_deadline_before_or_during_composition_keeps_boundary_and_fixed_line(self):
        for patch in ["find=hooks.projects.find\ndef late(*a,**k):\n    p=find(*a,**k)\n    memory_clock.now=lambda: 1000000000000.0\n    return p\nhooks.projects.find=late",
                      "from memory_lib import start_memory\noriginal=start_memory.build_summary\ndef late(*a,**k):\n    value=original(*a,**k)\n    memory_clock.now=lambda: 1000000000000.0\n    return value\nstart_memory.build_summary=late"]:
            text = self.text(patch=patch)
            self.assertIn("## Memory\n\nMemory could not be read in time.", text)
            self.assertNotIn(start_memory.NOTHING, text)
            self.assertEqual(self.raw()[-1]["kind"], "start")
            self.assertEqual(self.records("hooks")[-1]["outcome"], "deadline")

    def test_tc057_actual_hook_start_failure_logs_once_and_exits_zero(self):
        patch = "from memory_lib import worker_launch\ndef denied(*a,**k):\n    raise OSError('private-fixture-value')\nworker_launch.subprocess.Popen=denied"
        self.assertIn(start_memory.NOTHING, self.text(patch=patch, worker=True))
        rows = self.records("failures")
        self.assertEqual([(r["error"], r["step"]) for r in rows], [("worker-start", "trigger")])
        self.assertNotIn("private-fixture-value", json.dumps(rows))

    def test_tc057_fresh_curation_lease_skips_popen_but_records_the_boundary(self):
        from memory_lib import locks
        lease = locks.Lock(self.root / "projects/sample/curation.lock", "curation", self.header["device"])
        lease.acquire(clock.now() + 2)
        try:
            patch = "from memory_lib import worker_launch\ndef forbidden(*a,**k):\n    raise AssertionError('fresh lease launched a worker')\nworker_launch.subprocess.Popen=forbidden"
            self.assertIn(start_memory.NOTHING, self.text(patch=patch, worker=True))
            self.assertEqual(self.records("failures"), [])
            self.assertEqual([r["kind"] for r in self.raw()], ["start"])
        finally:
            lease.release()

    def test_memory_timeout_still_attempts_worker_with_the_original_diagnostic_deadline(self):
        receipt = self.folder / "diagnostic-deadline.json"
        patch = ("from pathlib import Path\nfrom memory_lib import worker_launch,diagnostics\n"
                 "find=hooks.projects.find\nnow=memory_clock.now\noffset=[0.0]\nmemory_clock.now=lambda:now()+offset[0]\n"
                 "def late(*a,**k):\n    p=find(*a,**k)\n    offset[0]=2.0\n    return p\nhooks.projects.find=late\n"
                 "def denied(*a,**k):\n    raise OSError('private-fixture-value')\nworker_launch.subprocess.Popen=denied\n"
                 "failure=diagnostics.Diagnostics.failure\ndef observed(self,error,step,deadline,**kw):\n"
                 "    if error=='worker-start':\n        Path(" + repr(str(receipt)) + ").write_text(json.dumps({'deadline':deadline,'now':memory_clock.now()}))\n"
                 "    return failure(self,error,step,deadline,**kw)\ndiagnostics.Diagnostics.failure=observed")
        text = self.text(patch=patch, worker=True)
        value = json.loads(receipt.read_text())
        self.assertGreaterEqual(value["now"] - value["deadline"], 1.0)
        self.assertIn("Memory could not be read in time.", text)
        self.assertEqual([r["error"] for r in self.records("failures")], ["worker-start", "deadline"])
        self.assertEqual(self.records("hooks")[-1]["outcome"], "deadline")

    def test_configuration_backup_recovers_before_slow_base_can_skip_start_recording(self):
        primary = self.root / "configuration.json"
        backup = primary.with_name(primary.name + ".bak")
        backup.write_bytes(primary.read_bytes())
        primary.unlink()
        patch = ("from memory_lib import context\noriginal=context.build_context\n"
                 "now=memory_clock.now\noffset=[0.0]\nmemory_clock.now=lambda:now()+offset[0]\n"
                 "def slow(*a,**k):\n    value=original(*a,**k)\n    offset[0]=2.0\n    return value\ncontext.build_context=slow")
        text = self.text(patch=patch)
        self.assertEqual([row["kind"] for row in self.raw()], ["start"])
        self.assertTrue(primary.exists())
        self.assertFalse(backup.exists())
        self.assertIn("## Memory\n\nMemory could not be read in time.", text)
        self.assertEqual(self.records("hooks")[-1]["outcome"], "deadline")

    def test_actual_session_start_runs_all_project_retention_and_cleanup_after_hook_exit(self):
        # Reuse the checked real-worker barrier, retaining the exact Windows
        # child process until it releases the fixture cwd, even on assertion failure.
        from memory_lib.raw_log import log_name
        fixture = runtime_fixture.WorkerRuntimeTest("test_tc331_missing_initial_folder_maintains_disabled_unconsented_keyless_projects")
        fixture.root, fixture.log = self.root, log_name("codex", "worker-runtime-fixture")
        fixture.project("disabled")
        fixture.project("second")
        self.memory.write_configuration({"projects": {"sample": {"enabled": False, "since": AT}}}, clock.now() + 2)
        old = self.root / "configuration.json.oldtmp01.tmp"
        young = self.root / "configuration.json.newtmp01.tmp"
        for path, age in ((old, 660), (young, 540)):
            path.write_bytes(b"owned")
            stamp = time.time() - age
            os.utime(path, (stamp, stamp))
        backup = self.root / "configuration.json.bak"
        backup.write_bytes(b"fixture backup")
        unowned = self.root / "notes.txt.oldtmp01.tmp"
        unknown = self.root / "items.json.oldtmp01.tmp"
        for path in (unowned, unknown):
            path.write_bytes(b"preserve")
        damaged = self.root / "logs" / ("hooks-" + base.utc_time()[:10] + ".jsonl")
        damaged.write_bytes(b'{"unknown":"fixture"}\n')
        damaged_backup = damaged.with_name(damaged.name + ".bak")
        damaged_backup.write_bytes(b"preserve invalid primary's backup")
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
        truncated = self.root / "logs" / ("hooks-" + yesterday + ".jsonl")
        truncated.write_bytes(b"truncated fixture")
        truncated_backup = truncated.with_name(truncated.name + ".bak")
        truncated_backup.write_bytes(b"preserve damaged primary's backup")
        wrapper = self.folder / "real-worker-wrapper.py"
        library = SCRIPTS / "memory_lib"
        wrapper.write_text("REAL_ENTRY=" + repr(str(ENTRY)) + "\nREAL_LIBRARY=__import__('pathlib').Path(" + repr(str(library / "worker_runtime.py")) + ")\nMARKER=" + repr(MARKER) + "\n" + CHILD, encoding="utf-8")
        receipt = self.folder / "launch.json"
        patch = ("from pathlib import Path\nfrom memory_lib import worker_launch\n"
                 "worker_launch.WORKER=Path(" + repr(str(wrapper)) + ")\noriginal=worker_launch.subprocess.Popen\n"
                 "def captured(command,**options):\n    child=original(command,**options)\n"
                 "    Path(" + repr(str(receipt)) + ").write_text(json.dumps({'events':[{'pid':child.pid}]}))\n    return child\nworker_launch.subprocess.Popen=captured")
        with contextlib.ExitStack() as stack:
            try:
                text = self.text(patch=patch, worker=True, changes={"CORTHEX_MEMORY_TEST_TOKEN": MARKER, "PYTHONPATH": str(self.folder / "untrusted")})
            finally:
                if receipt.exists():
                    stack.enter_context(owned_worker_exit(self, json.loads(receipt.read_text())))
                    (self.root / "fixture-go").write_text("go")
            until = time.perf_counter() + 15
            result = self.root / "fixture-finished.json"
            while not result.exists() and time.perf_counter() < until:
                time.sleep(.01)
            self.assertTrue(result.exists(), "Owned real start worker did not finish")
            evidence = json.loads(result.read_text(encoding="utf-8"))
            self.assertTrue(evidence["quiet_exit"] and evidence["isolated"] and evidence["own_library"])
            self.assertNotIn("## Memory", text)
            raw = self.root / "projects/disabled/raw" / (fixture.log + ".jsonl")
            self.assertTrue(raw.exists(), sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*")))
            self.assertEqual([r["seq"] for r in fixture.rows("disabled")], [2])
            self.assertEqual([r["seq"] for r in fixture.rows("second")], [2])
            self.assertFalse(old.exists())
            self.assertFalse(backup.exists())
            self.assertEqual(young.read_bytes(), b"owned")
            for path in (unowned, unknown):
                self.assertEqual(path.read_bytes(), b"preserve")
            self.assertEqual(damaged.read_bytes(), b'{"unknown":"fixture"}\n')
            self.assertTrue(damaged_backup.exists() and truncated_backup.exists())
