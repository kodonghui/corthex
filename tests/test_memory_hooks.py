"""TASK-009: real hook subprocesses with disposable stores and host inputs."""

import json
import multiprocessing
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from unittest import mock

from _common import ROOT
from test_memory_diagnostics import hold_logs
from test_memory_store import AT, SCRIPTS, StoreCase
from memory_lib import base, diagnostics, files, hooks, locks, store

PLUGIN = ROOT / "plugins/corthex-memory"
SCRIPT = PLUGIN / "scripts/hook.py"


class HookCase(StoreCase):
    def setUp(self):
        super().setUp()
        self.home = self.folder / "home"
        self.repo = self.folder / "checkout"
        (self.home / ".corthex").mkdir(parents=True)
        (self.repo / ".corthex").mkdir(parents=True)
        (self.repo / ".corthex/project.json").write_text('{"name":"sample"}', encoding="utf-8")
        (self.home / ".corthex/projects.json").write_text(json.dumps({"projects": [
            {"name": "sample", "path": str(self.repo)}]}), encoding="utf-8")
        self.memory.write_configuration({"consent": {"at": AT, "version": 1},
            "projects": {"sample": {"enabled": True, "since": AT}}}, time.monotonic() + 2)

    def event(self, hook):
        return {"hook_event_name": hooks.EVENTS[hook], "session_id": "session-fixture",
                "cwd": str(self.repo), "prompt": "hello", "source": "startup",
                "last_assistant_message": "answer"}

    def environment(self, changes=None):
        env = {key: value for key, value in os.environ.items()
               if not any(part in key.upper() for part in ("TOKEN", "SECRET", "PASSWORD", "API_KEY"))
               and not key.startswith(("CLAUDE", "CODEX", "ANTHROPIC", "PYTHON"))}
        env.update(HOME=str(self.home), USERPROFILE=str(self.home), CORTHEX_MEMORY_HOME=str(self.root),
                   PLUGIN_ROOT="", CLAUDECODE="1", PYTHONDONTWRITEBYTECODE="1")
        env.update(changes or {})
        return env

    def run_hook(self, hook, payload=None, changes=None, patch=None, metadata=None,
                 expected_stderr=b"", expect_start=True):
        payload = self.event(hook) if payload is None else payload
        raw = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        args = [sys.executable, str(SCRIPT), hook]
        if patch is not None or metadata is not None:
            shim = self.folder / "caller.py"
            text = "import json, runpy, sys, time\n"
            text += "sys.path.insert(0, " + repr(str(SCRIPTS)) + ")\n"
            if patch is not None:
                text += "from memory_lib import hooks\n" + patch + "\n"
            text += "sys.argv = [" + repr(str(SCRIPT)) + ", " + repr(hook) + "]\n"
            text += "try:\n    runpy.run_path(" + repr(str(SCRIPT)) + ", run_name='__main__')\nexcept SystemExit as error:\n    assert error.code == 0\n"
            if metadata is not None:
                text += "with open(" + repr(str(metadata)) + ", 'w', encoding='utf-8') as target:\n    json.dump(sorted(sys.modules), target)\n"
            shim.write_text(text, encoding="utf-8")
            args = [sys.executable, str(shim)]
        run = subprocess.run(args, input=raw, env=self.environment(changes), cwd=str(self.repo),
                             capture_output=True, timeout=15)
        self.assertEqual(run.returncode, 0)
        self.assertEqual(run.stderr.replace(b"\r\n", b"\n"), expected_stderr)
        self.assertTrue(all(byte < 128 for byte in run.stdout))
        if hook == "start" and expect_start:
            value = json.loads(run.stdout)
            self.assertEqual(set(value), {"hookSpecificOutput"})
            self.assertEqual(value["hookSpecificOutput"]["hookEventName"], "SessionStart")
            self.assertLessEqual(len(value["hookSpecificOutput"]["additionalContext"].encode("utf-8")), 8000)
        else:
            self.assertEqual(run.stdout, b"")
        return run

    def records(self, name):
        return [row for path in sorted((self.root / "logs").glob(name + "-*.jsonl"))
                for row in files.read_jsonl(path)]


class HookFrameworkTest(HookCase):
    def test_tc033_each_hook_rejects_invalid_utf8_json_event_and_session(self):
        for hook in hooks.EVENTS:
            valid = self.event(hook)
            wrong = dict(valid, hook_event_name="not-the-event")
            long_id = dict(valid, session_id="x" * 201)
            for payload in (b"\xffprivate-fixture", b"{} {}", b"[]", b"null", wrong, long_id,
                            dict(valid, session_id=""), dict(valid, session_id=2)):
                before = len(self.records("failures"))
                self.run_hook(hook, payload)
                rows = self.records("failures")
                self.assertEqual(len(rows), before + 1)
                self.assertEqual(rows[-1]["error"], "bad-input")
            if hook == "prompt":
                self.run_hook(hook, dict(valid, prompt=None))
                self.assertEqual(self.records("failures")[-1]["error"], "bad-input")
            before = len(self.records("failures"))
            self.run_hook(hook, b"\xef\xbb\xbf" + json.dumps(valid).encode("utf-8"))
            self.assertEqual(len(self.records("failures")), before)
        self.assertEqual(self.records("hooks"), [])

    def test_tc033_bad_start_input_uses_process_cwd_for_the_base(self):
        other = self.folder / "other"
        (other / ".corthex").mkdir(parents=True)
        (other / ".corthex/project.json").write_text('{"name":"other"}', encoding="utf-8")
        result = self.run_hook("start", dict(self.event("start"), hook_event_name="Stop", cwd=str(other)))
        text = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("- sample", text)
        self.assertNotIn("- other", text)

    def test_tc034_host_precedence_uses_root_identity_then_flag_then_field_presence(self):
        patch = "hooks.process = lambda frame: 'ok'"
        for hook in hooks.EVENTS:
            cases = [({"PLUGIN_ROOT": str(PLUGIN)}, {}, "codex"),
                     ({"CLAUDECODE": "1"}, {"turn_id": "fixture"}, "claude-code"),
                     ({"CLAUDECODE": ""}, {"turn_id": None, "prompt_id": None}, "codex"),
                     ({"CLAUDECODE": ""}, {"prompt_id": None}, "claude-code"),
                     ({"PLUGIN_ROOT": str(PLUGIN), "CLAUDECODE": "1"}, {}, "codex")]
            for env, fields, expected in cases:
                self.run_hook(hook, dict(self.event(hook), **fields), env, patch)
                self.assertEqual(self.records("hooks")[-1]["host"], expected)
            before = len(self.records("failures"))
            self.run_hook(hook, changes={"CLAUDECODE": "", "PLUGIN_ROOT": ""})
            self.assertEqual(len(self.records("failures")), before + 1)
            self.assertEqual(self.records("failures")[-1]["error"], "unknown-host")

    def test_tc034_root_alias_is_compared_by_directory_identity(self):
        alias = self.folder / "plugin-link"
        try:
            alias.symlink_to(PLUGIN, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("directory symlinks are unavailable on this volume")
        self.run_hook("prompt", changes={"PLUGIN_ROOT": str(alias)}, patch="hooks.process = lambda frame: 'ok'")
        self.assertEqual(self.records("hooks")[-1]["host"], "codex")

    def test_tc011_blocked_headers_precede_input_error_diagnostics_and_configuration(self):
        record = self.root / "store.json"
        accessed = self.folder / "configuration-accessed"
        patch = ("from pathlib import Path\nfrom memory_lib import store\n"
                 "def forbidden(*args, **kwargs):\n    Path(" + repr(str(accessed)) + ").write_text('accessed')\n"
                 "    raise AssertionError('configuration must follow the store gate')\n"
                 "store.MemoryStore.configuration = forbidden")
        for content in (b'{"format":2}', b'{"format":1,"migrating":{}}', b"damaged", None):
            if content is None:
                record.unlink()
            else:
                record.write_bytes(content)
            before = self.snapshot()
            for hook in hooks.EVENTS:
                self.run_hook(hook, patch=patch)
                self.run_hook(hook, b"not json", patch=patch)
                self.run_hook(hook, changes={"CLAUDECODE": ""}, patch=patch)
            self.assertEqual(self.snapshot(), before)
            self.assertFalse(accessed.exists())

    def test_tc011_each_hook_restores_a_readable_header_backup_and_notes_it(self):
        record = self.root / "store.json"
        backup = self.root / "store.json.bak"
        for hook in hooks.EVENTS:
            for content in (None, b"damaged"):
                if content is None:
                    record.unlink()
                else:
                    record.write_bytes(content)
                backup.write_bytes(base.json_bytes(self.header, "TBL-001"))
                before = len(self.records("failures"))
                self.run_hook(hook)
                self.assertEqual(files.read_json(record, "TBL-001"), self.header)
                self.assertEqual(len(self.records("failures")), before + 1)
                self.assertEqual(self.records("failures")[-1]["error"], "restored")

    def test_tc012_valid_input_without_configuration_changes_no_file(self):
        (self.root / "configuration.json").unlink()
        before = self.snapshot()
        for hook in hooks.EVENTS:
            self.run_hook(hook)
        self.assertEqual(self.snapshot(), before)

    def test_tc033_034_failure_only_is_allowed_without_consent(self):
        (self.root / "configuration.json").unlink()
        for hook in hooks.EVENTS:
            self.run_hook(hook, b"not json")
            self.run_hook(hook, changes={"CLAUDECODE": ""})
        self.assertEqual([row["error"] for row in self.records("failures")],
                         [value for _ in hooks.EVENTS for value in ("bad-input", "unknown-host")])
        self.assertEqual(self.records("hooks"), [])

    def test_tc035_outcome_and_exception_paths_keep_the_output_contract(self):
        for hook in hooks.EVENTS:
            for outcome in ("ok", "left-out", "no-answer", "lock-busy", "deadline", "error"):
                self.run_hook(hook, patch="hooks.process = lambda frame: " + repr(outcome))
                self.assertEqual(self.records("hooks")[-1]["outcome"], outcome)
            patch = "def fail(frame):\n    raise RuntimeError('private-fixture-error-text')\nhooks.process = fail"
            self.run_hook(hook, patch=patch)
            self.assertEqual(self.records("failures")[-1]["error"], "RuntimeError")
            self.assertEqual(self.records("hooks")[-1]["outcome"], "error")
        data = b"".join(path.read_bytes() for path in (self.root / "logs").glob("*.jsonl"))
        self.assertNotIn(b"private-fixture-error-text", data)

    def test_tc036_recording_hooks_load_no_network_client_or_sqlite(self):
        for hook in ("prompt", "end-of-turn", "end"):
            metadata = self.folder / "modules.json"
            self.run_hook(hook, metadata=metadata)
            modules = json.loads(metadata.read_text(encoding="utf-8"))
            self.assertFalse(set(modules) & {"socket", "ssl", "http.client", "urllib.request", "sqlite3"})

    def test_tc035_outer_and_base_errors_print_only_one_exception_class(self):
        message = "private-fixture-error-text"
        patch = ("from memory_lib import context\ndef fail(*args):\n"
                 "    raise RuntimeError(" + repr(message) + ")\ncontext.build_context = fail")
        self.run_hook("start", patch=patch, expected_stderr=b"corthex-memory: RuntimeError\n",
                      expect_start=False)
        patch = "def fail(*args):\n    raise RuntimeError(" + repr(message) + ")\nhooks.run = fail"
        for hook in hooks.EVENTS:
            self.run_hook(hook, patch=patch, expected_stderr=b"corthex-memory: RuntimeError\n",
                          expect_start=False)

    def test_tc012_no_store_creates_neither_store_nor_plugin_bytecode(self):
        plugin = self.folder / "plugin-copy"
        shutil.copytree(PLUGIN, plugin, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        missing = self.folder / "absent-memory"
        env = self.environment({"CORTHEX_MEMORY_HOME": str(missing)})
        env.pop("PYTHONDONTWRITEBYTECODE", None)
        result = subprocess.run([sys.executable, str(plugin / "scripts/hook.py"), "prompt"],
                                input=json.dumps(self.event("prompt")).encode(), env=env,
                                cwd=str(self.repo), capture_output=True, timeout=15)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))
        self.assertFalse(missing.exists())
        self.assertEqual(list(plugin.rglob("__pycache__")), [])

    def test_tc321_expired_hook_attempts_free_logs_once_and_skips_busy_logs(self):
        patch = ("def expire(frame):\n    frame.started = time.monotonic() - 2\n"
                 "    frame.deadline = frame.started + hooks.SECONDS[frame.hook]\n    return 'ok'\nhooks.process = expire")
        self.run_hook("prompt", patch=patch)
        self.assertEqual(self.records("failures")[-1]["error"], "deadline")
        self.assertEqual(self.records("hooks")[-1]["outcome"], "deadline")
        self.assertGreaterEqual(self.records("hooks")[-1]["ms"], 2000)
        parent, child = multiprocessing.Pipe()
        worker = multiprocessing.Process(target=hold_logs, args=(child, str(self.root), self.header["device"]))
        worker.start()
        try:
            self.assertTrue(parent.poll(10))
            self.assertTrue(parent.recv())
            before = self.snapshot()
            no_wait = patch + "\ndef reject_wait(seconds):\n    raise AssertionError('expired hook must not wait')\nfrom memory_lib import locks\nlocks.time.sleep = reject_wait"
            self.run_hook("prompt", patch=no_wait)
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

    def test_tc321_late_diagnostic_rechecks_the_cached_store_gate(self):
        patch = ("def change(frame):\n    (frame.memory.folder / 'store.json').write_bytes(b'{\"format\":2}')\n"
                 "    frame.started = time.monotonic() - 2\n    frame.deadline = frame.started + 0.9\n"
                 "    return 'ok'\nhooks.process = change")
        self.run_hook("prompt", patch=patch)
        self.assertEqual(self.records("failures"), [])
        self.assertEqual(self.records("hooks"), [])

    def test_tc321_late_windows_open_gets_one_attempt_and_no_retry_budget(self):
        logger = diagnostics.Diagnostics(self.memory)
        logger.read_gate(time.monotonic() + 2)
        before = self.snapshot()
        with mock.patch.object(files, "_WINDOWS", True), \
                mock.patch.object(files, "private_open", side_effect=PermissionError()) as opening, \
                mock.patch.object(time, "sleep", side_effect=AssertionError("must not wait")):
            self.assertFalse(logger.failure("deadline", "record", time.monotonic() - 1,
                                            hook="prompt", host="codex", opportunistic=True))
            self.assertEqual(opening.call_count, 1)
        self.assertEqual(self.snapshot(), before)
