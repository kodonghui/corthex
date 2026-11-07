"""C1 status: real command/hook entries over disposable metadata stores."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
from unittest import mock

import test_memory_hooks as fixture
import test_memory_api as api_fixture
from _common import ROOT, load_json
from memory_lib import clock, commands, files, locks, raw_log, status

TEXT = "PRIVATE_STATUS_CONVERSATION_MARKER"
KEY = "PRIVATE_STATUS_KEY_MARKER"


class StatusTest(fixture.HookCase):
    def setUp(self):
        super().setUp()
        self.result_schema = load_json(ROOT / "docs/06-api/memory-result.schema.json")

    def cli(self, *extra, changes=None):
        values = {"CORTHEX_MEMORY_ANTHROPIC_BASE_URL": "", "CORTHEX_MEMORY_OPENAI_BASE_URL": ""}
        values.update(changes or {})
        run = subprocess.run([sys.executable, str(fixture.SCRIPTS / "memory.py"),
                              "--folder", str(self.repo), "status"] + list(extra),
                             cwd=self.repo, env=self.environment(values), capture_output=True, timeout=20)
        self.assertEqual(run.stderr, b"")
        self.assertTrue(run.stdout.isascii())
        self.assertEqual(run.stdout.count(b"\n"), 1)
        value = json.loads(run.stdout)
        self.assertEqual(api_fixture.fits(self.result_schema, value), [])
        return value, run

    def direct(self, *extra):
        value, code = commands.run(["--folder", str(self.repo), "status"] + list(extra))
        self.assertEqual(api_fixture.fits(self.result_schema, value), [])
        self.assertEqual(code, int(value["outcome"] in ("failed", "refused")))
        return value

    def write_rows(self, family, rows, day=None):
        day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = self.root / "logs" / (family + "-" + day + ".jsonl")
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        return path

    def test_tc086_reports_100_real_prompt_hook_timings(self):
        for _ in range(100):
            self.run_hook("prompt")
        rows = self.records("hooks")
        self.assertEqual(len(rows), 100)
        before = self.snapshot()
        value, run = self.cli()
        self.assertEqual((run.returncode, value["code"]), (0, "ok"))
        actual = value["data"]["hooks"]
        values = sorted(row["ms"] for row in rows)
        median = int(Decimal(str(statistics.median(values))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        self.assertEqual(actual, [dict(hook="prompt", host="claude-code", runs=100,
                                      median_ms=median, p95_ms=values[94],
                                      last=max(row["at"] for row in rows), outcomes={"ok": 100})])
        self.assertEqual(value["data"]["projects"][0]["unprocessed"], 100)
        self.assertEqual(self.snapshot(), before)

    def test_tc087_real_recorded_text_and_dedicated_keys_stay_private(self):
        changes = {"CORTHEX_MEMORY_ANTHROPIC_API_KEY": KEY, "CORTHEX_MEMORY_OPENAI_API_KEY": KEY}
        self.run_hook("prompt", dict(self.event("prompt"), prompt=TEXT), changes)
        self.run_hook("end-of-turn", dict(self.event("end-of-turn"), last_assistant_message=TEXT), changes)
        before = self.snapshot()
        value, run = self.cli(changes=changes)
        self.assertEqual((run.returncode, value["code"]), (0, "ok"))
        self.assertEqual(value["data"]["keys"], {"anthropic": "present", "openai": "present"})
        self.assertNotIn(TEXT.encode(), run.stdout + run.stderr)
        self.assertNotIn(KEY.encode(), run.stdout + run.stderr)
        self.assertEqual(value["data"]["projects"][0]["unprocessed"], 1)
        self.assertEqual(self.snapshot(), before)

    def test_tc088_actual_no_answer_lock_skip_unreadable_failures_and_zero_usage(self):
        self.run_hook("end-of-turn", dict(self.event("end-of-turn"), last_assistant_message=""))
        log = raw_log.RawLog(self.memory, "sample", "claude-code", self.event("prompt")["session_id"])
        with locks.Lock(log.path.with_suffix(".lock"), "raw", self.header["device"]).held(clock.now() + 2):
            self.run_hook("prompt")
        # A directory at the log path produces an actual OS read error on each OS.
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        failures = self.root / "logs" / ("failures-" + day + ".jsonl")
        self.assertTrue(failures.is_file())
        failures.unlink()
        failures.mkdir()
        before = self.snapshot()
        value, run = self.cli()
        self.assertEqual((run.returncode, value["code"]), (0, "ok"))
        outcomes = {row["hook"]: row["outcomes"] for row in value["data"]["hooks"]}
        self.assertEqual(outcomes["end-of-turn"]["no-answer"], 1)
        self.assertEqual(outcomes["prompt"]["lock-busy"], 1)
        self.assertEqual(value["data"]["unreadable"], ["failures"])
        self.assertEqual(value["data"]["usage"], dict(month=day[:7], models=[], cost=0))
        self.assertEqual(self.snapshot(), before)

    def test_metadata_defaults_optional_project_lookup_and_all_projects(self):
        value, run = self.cli(changes={"OPENAI_API_KEY": KEY, "ANTHROPIC_API_KEY": KEY})
        self.assertEqual((run.returncode, value["code"]), (0, "ok"))
        self.assertEqual(value["data"]["keys"], {"anthropic": "missing", "openai": "missing"})
        document = dict(consent={"at": self.header["made"], "version": 1},
                        projects={"sample": {"enabled": True, "since": self.header["made"]},
                                  "disabled": {"enabled": False, "since": self.header["made"]}})
        self.memory.write_configuration(document, clock.now() + 2)
        value, _ = self.cli("--all")
        self.assertEqual([(p["project"], p["enabled"]) for p in value["data"]["projects"]],
                         [("disabled", False), ("sample", True)])
        self.assertEqual(self.direct("--folder", str(self.folder))["data"]["projects"], [])

    def test_invalid_configuration_is_reported_without_trusting_partial_values(self):
        files.write_json(self.root / "configuration.json", {"projects": {"sample": KEY}}, "TBL-002")
        before = self.snapshot()
        value, run = self.cli()
        self.assertEqual((run.returncode, value["code"]), (0, "ok"))
        self.assertFalse(value["data"]["configuration"]["valid"])
        self.assertNotIn("given", value["data"]["consent"])
        self.assertEqual(value["data"]["projects"], [])
        self.assertNotIn(KEY.encode(), run.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_no_store_and_future_header_keep_the_common_gates_read_only(self):
        before = self.snapshot()
        value, run = self.cli(changes={"CORTHEX_MEMORY_HOME": str(self.folder / "absent")})
        self.assertEqual((run.returncode, value["code"]), (0, "no-store"))
        self.assertFalse((self.folder / "absent").exists())
        self.assertEqual(self.snapshot(), before)
        header = dict(self.header, format=999)
        files.write_json(self.root / "store.json", header, "TBL-001")
        before = self.snapshot()
        value, run = self.cli()
        self.assertEqual((run.returncode, value["code"]), (1, "store-newer"))
        self.assertEqual(self.snapshot(), before)

    def test_home_is_masked_by_ancestor_identity(self):
        with mock.patch.object(Path, "home", return_value=self.folder):
            self.assertEqual(status._folder_name(self.root), "~/memory")
        prefix = self.folder / "memory-more"
        prefix.mkdir()
        with mock.patch.object(Path, "home", return_value=self.root):
            self.assertEqual(status._folder_name(prefix), str(prefix))

    def test_metadata_aggregate_uses_utc_boundaries_and_integer_percentiles(self):
        now = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
        lower = now - timedelta(days=7)
        stamp = lambda value: value.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        rows = [dict(at=stamp(lower), hook="prompt", host="codex", ms=n, outcome="ok")
                for n in (0, 1, 2, 3)]
        rows += [dict(rows[0], at=stamp(lower - timedelta(seconds=1)), ms=999),
                 dict(rows[0], at=stamp(now + timedelta(seconds=1)), ms=999)]
        self.write_rows("hooks", rows, lower.strftime("%Y-%m-%d"))
        failure_rows = [dict(at=stamp(now - timedelta(seconds=n)), step="record", error="OSError", text=TEXT)
                        for n in range(25)]
        self.write_rows("failures", failure_rows, now.strftime("%Y-%m-%d"))
        with mock.patch.object(status, "_now", return_value=now):
            data = self.direct()["data"]
        self.assertEqual(data["hooks"][0], dict(hook="prompt", host="codex", runs=4,
                                              median_ms=2, p95_ms=3, last=stamp(lower), outcomes={"ok": 4}))
        self.assertEqual(len(data["failures"]), 20)
        self.assertEqual(data["failures"][0]["at"], stamp(now))
        self.assertNotIn(TEXT, commands.canonical(data))

    def test_usage_aggregates_recorded_cost_and_excludes_count_tokens(self):
        now = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
        row = dict(at="2026-11-02T10:00:00.000Z", model="fixture-model", call="curate",
                   input=10, output=5, cache_write=2, cache_read=3, cost=0.1, result="ok", prices="2000-01-01")
        self.write_rows("usage", [row, dict(row, input=20, output=0, cost=0.2, result="failed"),
                                  dict(row, call="count-tokens", cost=9, input=900)], "2026-11")
        with mock.patch.object(status, "_now", return_value=now):
            usage = self.direct()["data"]["usage"]
        self.assertEqual(usage["models"], [dict(model="fixture-model", calls=2, input=40, output=5,
                                               cost=usage["cost"])])
        self.assertAlmostEqual(usage["cost"], 0.3)

    def test_tc128_a_401_shows_its_key_as_rejected_until_a_later_call_of_that_api(self):
        now = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
        refused = dict(at="2026-11-02T10:00:00.000Z", model="fixture-model", call="curate", input=0, output=0,
                       cost=0, result="failed", error="authentication_error", prices="2000-01-01")
        embedded = dict(refused, at="2026-11-02T09:00:00.000Z", call="embed-items", result="ok")
        del embedded["error"]
        keys = {"CORTHEX_MEMORY_ANTHROPIC_API_KEY": KEY, "CORTHEX_MEMORY_OPENAI_API_KEY": KEY}

        def states(rows, environment=keys):
            self.write_rows("usage", rows, "2026-11")
            with mock.patch.object(status, "_now", return_value=now), mock.patch.dict(os.environ, environment):
                data = self.direct()["data"]
            self.assertNotIn(KEY, commands.canonical(data))
            return data["keys"], data["waits"]

        self.assertEqual(states([embedded, refused])[0], dict(anthropic="rejected", openai="present"))
        # A later call of the same API, even a free token count, clears it.
        counted = dict(refused, at="2026-11-02T11:00:00.000Z", call="count-tokens", result="ok")
        del counted["error"]
        self.assertEqual(states([refused, counted, embedded])[0], dict(anthropic="present", openai="present"))
        # File order breaks a tie in time, and another failure kind is not a rejection.
        self.assertEqual(states([counted, dict(refused, at=counted["at"])])[0]["anthropic"], "rejected")
        self.assertEqual(states([dict(refused, error="overloaded_error")])[0]["anthropic"], "present")
        # An OpenAI 401 marks only its own key; without the key it is missing and recall waits.
        openai = dict(embedded, result="failed", error="authentication_error")
        self.assertEqual(states([openai])[0], dict(anthropic="present", openai="rejected"))
        found, waits = states([refused, openai], dict(keys, CORTHEX_MEMORY_ANTHROPIC_API_KEY=""))
        self.assertEqual(found, dict(anthropic="missing", openai="rejected"))
        self.assertIn("anthropic-key", waits)
        self.assertNotIn("openai-key", waits)

    def test_unreadable_usage_is_omitted_while_other_parts_survive(self):
        day = datetime.now(timezone.utc).strftime("%Y-%m")
        self.write_rows("usage", [dict(at=self.header["made"], model="fixture-model", call="curate",
                                       input=True, output=0, cost=0, result="ok")], day)
        value, run = self.cli()
        self.assertEqual((run.returncode, value["code"]), (0, "ok"))
        self.assertNotIn("usage", value["data"])
        self.assertEqual(value["data"]["unreadable"], ["usage"])
        self.assertIn("store", value["data"])

    def test_log_backup_recovery_and_busy_boundary(self):
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        path = self.write_rows("usage", [], month)
        backup = path.with_name(path.name + ".bak")
        path.rename(backup)
        value, run = self.cli()
        self.assertEqual((run.returncode, value["code"]), (0, "ok"))
        self.assertTrue(path.exists())
        self.assertFalse(backup.exists())
        self.assertTrue(any(row["step"] == "restore" and row["error"] == "restored"
                            for row in self.records("failures")))
        with mock.patch.object(status.reading, "read_record", side_effect=locks.LockBusy()):
            self.assertEqual(self.direct()["code"], "lock-busy")

    def test_restore_notice_never_writes_after_the_store_identity_changes(self):
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        path = self.write_rows("usage", [], month)
        path.rename(path.with_name(path.name + ".bak"))
        original, after = status.Reader.usage, {}

        def replace(reader, config):
            result = original(reader, config)
            files.write_json(self.root / "store.json", dict(self.header, device=fixture.base.new_id("d")), "TBL-001")
            after.update(self.snapshot())
            return result

        with mock.patch.object(status.Reader, "usage", replace):
            value = self.direct()
        self.assertEqual(value["code"], "internal")
        self.assertEqual(self.snapshot(), after)
        self.assertEqual(self.records("failures"), [])

    def test_populated_c2_layer_never_reports_invented_zero_inventory(self):
        layer = self.root / "projects/sample/layer/items"
        layer.mkdir(parents=True)
        (layer / "synthetic.json").write_text("{}", encoding="utf-8")
        value, run = self.cli()
        self.assertEqual((run.returncode, value["code"]), (1, "internal"))
        self.assertNotIn("projects", value["data"])

    def test_tc089_native_read_only_directory_and_test_server_names(self):
        changes = {"CORTHEX_MEMORY_ANTHROPIC_BASE_URL": "https://localhost:9443/private-" + TEXT,
                   "CORTHEX_MEMORY_OPENAI_BASE_URL": "http://127.0.0.1:9444/private-" + TEXT}
        ordinary, ordinary_run = self.cli(changes=changes)
        self.assertEqual(ordinary_run.returncode, 0)
        self.assertTrue(ordinary["data"]["store"]["writable"])
        before = self.snapshot()
        if os.name != "nt":
            original = self.root.stat().st_mode
            try:
                self.root.chmod(0o555)
                value, run = self.cli(changes=changes)
            finally:
                self.root.chmod(original)
        else:
            self.assertEqual(self.root.resolve().parent, self.folder.resolve())
            environment = {key: value for key, value in self.environment(changes).items()
                           if key.upper() != "PSMODULEPATH"}
            shadow = self.repo / "powershell.exe"
            shadow.write_bytes(b"current-directory stand-in must never execute")
            path_key = next(key for key in environment if key.upper() == "PATH")
            environment[path_key] = os.pathsep.join((".", str(self.repo), environment[path_key]))
            excluded, shell = {Path.cwd().resolve(), self.repo.resolve()}, None
            for directory in environment[path_key].split(os.pathsep):
                directory = Path(directory.strip('"'))
                if not directory.is_absolute():
                    continue
                program = (directory / "powershell.exe").resolve()
                if program.parent not in excluded and program.is_file():
                    shell = str(program)
                    break
            self.assertTrue(shell and Path(shell).is_absolute())
            self.assertNotEqual(Path(shell), shadow.resolve())
            environment.update(STATUS_FIXTURE_ROOT=str(self.root), STATUS_FIXTURE_PYTHON=sys.executable,
                               STATUS_FIXTURE_ENTRY=str(fixture.SCRIPTS / "memory.py"),
                               STATUS_FIXTURE_PROJECT=str(self.repo))
            script = r'''$ErrorActionPreference = 'Stop'
$path = $env:STATUS_FIXTURE_ROOT
$original = Get-Acl -LiteralPath $path
$restricted = Get-Acl -LiteralPath $path
$sid = [System.Security.Principal.SecurityIdentifier]::new('S-1-1-0')
$rule = [System.Security.AccessControl.FileSystemAccessRule]::new($sid, [System.Security.AccessControl.FileSystemRights]6, [System.Security.AccessControl.AccessControlType]::Deny)
$restricted.AddAccessRule($rule)
try {
    Set-Acl -LiteralPath $path -AclObject $restricted
    & $env:STATUS_FIXTURE_PYTHON $env:STATUS_FIXTURE_ENTRY --folder $env:STATUS_FIXTURE_PROJECT status
    $code = $LASTEXITCODE
} finally {
    Set-Acl -LiteralPath $path -AclObject $original
}
exit $code
'''
            run = subprocess.run([shell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
                                 cwd=self.repo, env=environment, capture_output=True, timeout=30)
            self.assertEqual(run.stderr, b"")
            value = json.loads(run.stdout)
            self.assertEqual(api_fixture.fits(self.result_schema, value), [])
        self.assertEqual((run.returncode, value["code"]), (0, "ok"))
        self.assertFalse(value["data"]["store"]["writable"])
        self.assertEqual(value["data"]["test_servers"], ["anthropic", "openai"])
        self.assertNotIn(TEXT.encode(), run.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_schema_failure_precedes_reader_backup_recovery(self):
        path = self.root / "store.json"
        path.rename(path.with_name("store.json.bak"))
        context = commands.Context("status", {"folder": str(self.repo), "all": False},
                                   None, self.memory, record=self.header)
        before = self.snapshot()
        error = status.command_result.SchemaInvalid()
        error.args = (KEY,)
        original = status.BoundDiagnostics.read_gate
        with mock.patch.object(status.BoundDiagnostics, "read_gate", autospec=True,
                               side_effect=original) as gate, \
                mock.patch.object(status.command_result, "_load", side_effect=error):
            with self.assertRaises(status.command_result.SchemaInvalid):
                status.Reader(context)
        self.assertEqual(gate.call_count, 0)
        self.assertIs(context.memory, self.memory)
        self.assertEqual(self.snapshot(), before)

    def test_schema_failure_actual_entry_is_single_safe_internal_result(self):
        program = """import runpy, sys
sys.path.insert(0, sys.argv[1])
from memory_lib import command_result
def broken():
    error = command_result.SchemaInvalid()
    error.args = (\"PRIVATE_STATUS_KEY_MARKER\",)
    raise error
command_result._load = broken
entry, folder = sys.argv[2:]
sys.argv = [entry, \"--folder\", folder, \"status\"]
runpy.run_path(entry, run_name=\"__main__\")
"""
        run = subprocess.run([sys.executable, "-c", program, str(fixture.SCRIPTS),
                              str(fixture.SCRIPTS / "memory.py"), str(self.repo)],
                             cwd=self.repo, env=self.environment(), capture_output=True, timeout=20)
        self.assertEqual((run.returncode, run.stderr), (1, b""))
        self.assertTrue(run.stdout.isascii())
        self.assertEqual(run.stdout.count(b"\n"), 1)
        value = json.loads(run.stdout)
        self.assertEqual(api_fixture.fits(self.result_schema, value), [])
        self.assertEqual((value["outcome"], value["code"], value["data"]),
                         ("failed", "internal", {"error": "RuntimeError"}))
        self.assertNotIn(KEY.encode(), run.stdout + run.stderr)
        self.assertNotIn(KEY, commands.canonical(self.records("failures")))

    def test_invalid_test_servers_are_not_reported_or_echoed(self):
        for endpoint in ("http://example.com/" + TEXT, "https://localhost:99999/" + TEXT, "bad-" + TEXT):
            value, run = self.cli(changes={"CORTHEX_MEMORY_OPENAI_BASE_URL": endpoint})
            self.assertEqual((run.returncode, value["code"]), (0, "ok"))
            self.assertEqual(value["data"]["test_servers"], [])
            self.assertNotIn(TEXT.encode(), run.stdout)
