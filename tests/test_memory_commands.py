"""TC-073–078: the command contract, using disposable stores and internal handlers."""

import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from _common import ROOT, load_json
from test_memory_api import fits

SCRIPTS = ROOT / "plugins/corthex-memory/skills/corthex-memory/scripts"
sys.path.insert(0, str(SCRIPTS))
from memory_lib import base, command_result, commands, files, locks, store

ARGV = {
    "on": [], "off": [], "status": [], "resume": [], "list": [], "search": ["words"],
    "open": ["i_7f3k2m9q4x1v"], "pin": ["i_7f3k2m9q4x1v"], "unpin": ["i_7f3k2m9q4x1v"],
    "forget": ["i_7f3k2m9q4x1v"], "delete-project": [], "purge": [], "leave-out": [],
    "retention": ["7"], "sync": ["off"], "setup": ["--at", "/workspace/demo"], "repair": [],
}
MARKER = "UNTRUSTED_ARGUMENT_VALUE_12345"


class CommandsTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.root, self.home, self.project = (self.folder / name for name in ("memory", "home", "project"))
        self.project.mkdir()
        self.registry = self.home / ".corthex/projects.json"
        self.registry.parent.mkdir(parents=True)
        self.registry.write_text(json.dumps({"projects": [{"name": "demo", "path": str(self.project)}]}), encoding="utf-8")
        patch = mock.patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home),
                                "CORTHEX_MEMORY_HOME": str(self.root),
                                "CORTHEX_MEMORY_ANTHROPIC_API_KEY": MARKER,
                                "CORTHEX_MEMORY_OPENAI_API_KEY": MARKER})
        patch.start()
        self.addCleanup(patch.stop)
        self.header = store.new_record("0.2.0")
        self.document = {"consent": {"at": self.header["made"], "version": 1},
                         "projects": {"demo": {"enabled": True, "since": self.header["made"]}}}
        self.reset_store()
        api = ROOT / "docs/06-api"
        self.schema = load_json(api / "memory-result.schema.json")
        self.examples = load_json(api / "memory-examples.json")["result"]
        self.data = {
            "on": {"project": "demo"}, "off": {"project": "demo"},
            "status": self.examples["valid"]["status"]["data"], "resume": {"project": "demo"},
            "list": {"project": "demo", "items": [], "more": 0},
            "search": {"project": "demo", "by": "words", "results": []},
            "open": {"project": "demo", "items": []},
            "pin": {"project": "demo", "item": "i_7f3k2m9q4x1v"},
            "unpin": {"project": "demo", "item": "i_7f3k2m9q4x1v"},
            "forget": {"project": "demo", "item": "i_7f3k2m9q4x1v"},
            "delete-project": {"project": "demo", "deleted": {"items": 0, "entries": 0, "pins": 0}, "sync": "off"},
            "purge": {"folder": "~/memory", "projects": [], "deleted": {"items": 0, "entries": 0, "usage": 0}, "sync": "off"},
            "leave-out": {"project": "demo", "folders": [], "kinds": []},
            "retention": {"days": 7, "was": 100}, "sync": {"state": "off"},
            "setup": {"project": "demo"}, "repair": {"device": self.header["device"]},
        }

    def reset_store(self):
        (self.root / "logs").mkdir(parents=True, exist_ok=True)
        files.write_json(self.root / "store.json", self.header, "TBL-001")
        files.write_json(self.root / "configuration.json", self.document, "TBL-002")

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.root.rglob("*") if p.is_file()}

    def invoke(self, command, extra=(), handler=None, registered=True):
        calls = []
        def probe(context):
            calls.append(context)
            return handler(context) if handler else commands.result(command, copy.deepcopy(self.data[command]), "Completed.")
        argv = ["--folder", str(self.project), command] + ARGV[command] + list(extra)
        value, status = commands.run(argv, {command: probe} if registered else None)
        self.assertEqual(fits(self.schema, value), [], value)
        self.assertEqual(status, 2 if value["code"] == "usage" else int(value["outcome"] in ("refused", "failed")))
        self.assertNotIn(MARKER, commands.canonical(value))
        return value, status, calls

    def assert_internal(self, value, status, command="off"):
        self.assertEqual((value, status), (dict(command=command, outcome="failed", code="internal",
                         say=command_result.SAY, data={"error": "RuntimeError"}), 1))

    def test_tc335_builders_raw_handlers_and_common_data_fail_closed(self):
        for built in (True, False):
            for data in ({}, {"project": 7}, {"project": "demo", "extra": MARKER}):
                with self.subTest(builder=built, data=data):
                    def handler(context):
                        return commands.result("off", data, "Completed.") if built else dict(
                            command="off", outcome="done", code="ok", say="Completed.", data=data)
                    value, status, _ = self.invoke("off", handler=handler)
                    self.assert_internal(value, status)
        value, status, _ = self.invoke("off", handler=lambda context:
            commands.common_result("off", "not-enabled", field=7))
        self.assert_internal(value, status)
        logged = max((self.root / "logs").glob("failures-*.jsonl")).read_text().splitlines()
        self.assertEqual(json.loads(logged[-1])["error"], value["data"]["error"])
        raw = dict(command="off", outcome="done", code="ok", say="Completed.", data=self.data["off"])
        for answer, count in (([], 0), (dict(raw, command="on"), 0), (dict(raw, say="한글"), 1)):
            with self.subTest(answer=answer), mock.patch.object(command_result, "validate",
                    wraps=command_result.validate) as check:
                value, status, _ = self.invoke("off", handler=lambda context: answer)
                self.assert_internal(value, status)
                self.assertEqual(check.call_count, count)

    def test_tc335_invalid_preview_cannot_apply_with_its_matching_token(self):
        for bad in ({"days": 0, "was": 100}, {"days": 7, "was": 100, "entries": float("nan")}):
            applied = []
            arguments = {"folder": str(self.project.resolve()), "days": 7}
            token = "00000000" if "entries" in bad else commands.confirmation(
                self.header["device"], "retention", arguments, bad, 2)
            def handler(context):
                return context.confirm(bad, "Review this proposal.", lambda:
                    applied.append(True) or commands.result("retention", self.data["retention"], "Changed."))
            with mock.patch.object(commands.time, "time", return_value=1200):
                value, status, _ = self.invoke("retention", ["--confirm", token], handler)
            self.assertEqual(applied, [])
            self.assert_internal(value, status, "retention")

    def test_tc335_failed_resource_is_not_retried_by_the_runner_fallback(self):
        for built in (True, False):
            for target, error in (("_load", command_result.SchemaInvalid()),
                                  ("validate", RuntimeError(MARKER)), ("validate", ValueError(MARKER))):
                with self.subTest(builder=built, target=target), mock.patch.object(
                        command_result, target, side_effect=error) as check:
                    def handler(context):
                        return commands.result("off", self.data["off"], "Completed.") if built else dict(
                            command="off", outcome="done", code="ok", say="Completed.", data=self.data["off"])
                    value, status, _ = self.invoke("off", handler=handler)
                    self.assert_internal(value, status)
                    check.assert_called_once()

    def test_tc073_examples_keep_valid_and_invalid_schema_verdicts(self):
        for verdict, values in ((True, self.examples["valid"]), (False, self.examples["invalid"])):
            for name, value in values.items():
                with self.subTest(example=name):
                    self.assertEqual(not fits(self.schema, value), verdict)
                    if verdict:
                        commands.validate_result(value, value["command"])
                        encoded = commands.canonical(value)
                        self.assertTrue(encoded.isascii())
                        self.assertEqual(json.loads(encoded), value)

    def test_tc073_internal_dispatch_preserves_each_result_fixture(self):
        for name, value in self.examples["valid"].items():
            if value["command"] != "none":
                with self.subTest(example=name):
                    actual, _, calls = self.invoke(value["command"], handler=lambda context: copy.deepcopy(value))
                    self.assertEqual(actual, value)
                    self.assertEqual(len(calls), 1)
        bad = copy.deepcopy(self.examples["valid"]["list"])
        bad["command"] = "status"
        value, status, _ = self.invoke("list", handler=lambda context: bad)
        self.assert_internal(value, status, "list")

    def test_tc074_usage_and_ascii_output_from_the_real_entry_point(self):
        before = self.snapshot()
        cases = [([], "none"), ([MARKER], "none"), (["status", "--unknown", MARKER], "status"),
                 (["--folder", str(self.project), "status", "--unknown=" + MARKER], "status"),
                 (["status", "--all=" + MARKER], "status"), (["list", "--lim", "2"], "list"),
                 (["retention", "0"], "retention"), (["retention", "3651"], "retention"),
                 (["open"], "open"), (["open", "item", "--around", "2001"], "open"),
                 (["off", "--confirm", MARKER], "off"), (["sync", "now", "--confirm", MARKER], "sync")]
        for argv, command in cases:
            with self.subTest(argv=argv):
                completed = subprocess.run([sys.executable, str(SCRIPTS / "memory.py")] + argv,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
                self.assertEqual((completed.returncode, completed.stderr), (2, b""))
                self.assertTrue(completed.stdout.isascii())
                self.assertEqual(completed.stdout.count(b"\n"), 1)
                self.assertNotIn(MARKER.encode(), completed.stdout)
                value = json.loads(completed.stdout)
                self.assertEqual((value["command"], value["code"]), (command, "usage"))
                self.assertEqual(fits(self.schema, value), [])
        self.assertEqual(self.snapshot(), before)
        for command in ARGV:
            value, status, calls = self.invoke(command, ["--unknown=" + MARKER])
            self.assertEqual((value["command"], value["code"], status, calls), (command, "usage", 2, []))

    def test_tc074_argument_defaults_repetition_and_folder_positions(self):
        self.assertEqual(set(ARGV), set(self.schema["properties"]["command"]["enum"]) - {"none"})
        cases = [("list", [], {"limit": 200}), ("search", ["--words-only"], {"limit": 20, "words_only": True}),
                 ("open", ["second", "--around", "2000"], {"item": ARGV["open"] + ["second"], "around": 2000}),
                 ("forget", ["--with", "one", "--with", "two"], {"with_items": ["one", "two"]}),
                 ("leave-out", ["future", "--kind", "prompt", "--kind", "answer", "--remove"],
                  {"folders": ["future"], "kind": ["prompt", "answer"], "remove": True})]
        for command, extra, expected in cases:
            _, _, calls = self.invoke(command, extra)
            for key, value in expected.items():
                self.assertEqual(calls[0].arguments[key], value)
        for argv in (["--folder", str(self.project), "on"], ["on", "--folder=" + str(self.project)]):
            captured = []
            commands.run(argv, {"on": lambda ctx: captured.append(ctx) or commands.result("on", self.data["on"], "Ready.")})
            self.assertEqual(captured[0].arguments["folder"], str(self.project.resolve()))
        old = Path.cwd()
        try:
            os.chdir(self.project)
            _, _, calls = self.invoke("status")
            raw, _ = commands.run(["status"], {"status": lambda ctx: calls.append(ctx) or commands.result("status", self.data["status"], "Ready.")})
            self.assertEqual(raw["code"], "ok")
            self.assertEqual(calls[-1].arguments["folder"], str(self.project.resolve()))
        finally:
            os.chdir(old)

    def test_tc075_store_and_configuration_applicability_for_every_command(self):
        exceptions = {"no-store": {"on", "purge", "repair"}, "store-newer": {"purge"},
                      "store-damaged": {"purge", "repair"}, "configuration-invalid": {"status", "purge", "repair"}}
        for code, exempt in exceptions.items():
            self.reset_store()
            if code == "store-newer":
                (self.root / "store.json").write_text('{"format":2,"opaque":true}', encoding="utf-8")
            if code == "store-damaged":
                (self.root / "store.json").write_bytes(b"{")
            if code == "configuration-invalid":
                (self.root / "configuration.json").write_text('{"retention":{"days":0}}', encoding="utf-8")
            target = self.folder / "absent" if code == "no-store" else self.root
            before = self.snapshot()
            with mock.patch.dict(os.environ, {"CORTHEX_MEMORY_HOME": str(target)}):
                for command in ARGV:
                    with self.subTest(code=code, command=command):
                        value, _, calls = self.invoke(command)
                        self.assertEqual(value["code"], "ok" if command in exempt else code)
                        self.assertEqual(bool(calls), command in exempt)
                        if command == "status" and code == "no-store":
                            self.assertEqual(value["outcome"], "nothing")
                        if code == "configuration-invalid" and command not in exempt:
                            self.assertEqual(value["data"], {"field": "retention.days"})
                        if command in exempt and code in ("store-newer", "store-damaged"):
                            self.assertIsNone(calls[0].record)
                            self.assertIsNone(calls[0].configuration)
            self.assertEqual(self.snapshot(), before)
            self.assertFalse((self.folder / "absent").exists())

    def test_tc075_invalid_home_is_universal_and_store_precedes_later_gates(self):
        before = self.snapshot()
        with mock.patch.dict(os.environ, {"CORTHEX_MEMORY_HOME": "relative"}), \
                mock.patch.object(store.MemoryStore, "record") as record, mock.patch.object(commands.projects, "locate") as locate:
            for command in ARGV:
                value, _, calls = self.invoke(command)
                self.assertEqual((value["code"], value["data"], calls),
                                 ("configuration-invalid", {"field": "CORTHEX_MEMORY_HOME"}, []))
            record.assert_not_called()
            locate.assert_not_called()
        (self.root / "store.json").write_bytes(b'{"format":2}')
        (self.root / "configuration.json").write_bytes(b"not-json")
        self.registry.unlink()
        value, _, _ = self.invoke("list")
        self.assertEqual(value["code"], "store-newer")
        with mock.patch.object(store.MemoryStore, "configuration", side_effect=store.StoreUnavailable("store-newer")):
            files.write_json(self.root / "store.json", self.header, "TBL-001")
            value, _, _ = self.invoke("list")
            self.assertEqual(value["code"], "store-newer")
        self.assertNotEqual(self.snapshot(), before)

    def test_tc076_project_gate_families_for_every_command(self):
        project_commands = set(ARGV) - {"status", "purge", "retention", "sync", "repair"}
        for scenario in ("missing", "outside", "clash", "disabled"):
            self.reset_store()
            entries = [{"name": "demo", "path": str(self.project)}]
            if scenario == "outside":
                entries = []
            if scenario == "clash":
                entries += [{"name": "other", "path": str(self.project)}]
            self.registry.write_text(json.dumps({"projects": entries}), encoding="utf-8")
            if scenario == "missing":
                self.registry.unlink()
            if scenario == "disabled":
                files.write_json(self.root / "configuration.json", {}, "TBL-002")
            before = self.snapshot()
            for command in ARGV:
                with self.subTest(scenario=scenario, command=command):
                    value, _, calls = self.invoke(command)
                    blocked = command in project_commands and not (scenario == "disabled" and command == "on")
                    code = {"missing": "no-project-list", "outside": "not-in-project", "clash": "not-in-project", "disabled": "not-enabled"}[scenario]
                    self.assertEqual(value["code"], code if blocked else "ok")
                    self.assertEqual(bool(calls), not blocked)
                    if blocked and scenario == "clash":
                        self.assertEqual(value["data"], {"clash": ["demo", "other"]})
                    if command == "off" and scenario == "disabled":
                        self.assertEqual(value["outcome"], "nothing")
            self.assertEqual(self.snapshot(), before)
        no_consent = copy.deepcopy(self.document)
        no_consent.pop("consent")
        files.write_json(self.root / "configuration.json", no_consent, "TBL-002")
        value, _, _ = self.invoke("search")
        self.assertEqual(value["code"], "ok")

    def test_tc077_busy_effect_lock_waits_ten_seconds_without_mutating(self):
        path = self.root / "store.lock"
        path.write_text('{"token":"00000000000000000000000000000000"}', encoding="ascii")
        before = self.snapshot()
        def handler(context):
            with context.lock(path, "store"):
                self.fail("busy lease was acquired")
        started = time.perf_counter()
        value, _, _ = self.invoke("off", handler=handler)
        self.assertEqual(value["code"], "lock-busy")
        self.assertGreaterEqual(time.perf_counter() - started, 10)
        self.assertEqual(self.snapshot(), before)

    def test_tc077_recovery_lock_busy_applies_to_every_reader_without_new_mutations(self):
        with mock.patch.object(locks.Lock, "acquire") as acquire:
            for command in ("status", "list", "search", "open", "setup"):
                value, _, _ = self.invoke(command)
                self.assertEqual(value["code"], "ok")
            acquire.assert_not_called()
        (self.root / "store.json").replace(self.root / "store.json.bak")
        before = self.snapshot()
        with mock.patch.object(locks.Lock, "acquire", side_effect=locks.LockBusy()):
            for command in ARGV:
                value, _, calls = self.invoke(command)
                self.assertEqual((value["code"], calls), ("lock-busy", []))
        self.assertEqual(self.snapshot(), before)
        lease = locks.Lock(self.root / "store.lock", "store", self.header["device"])
        with lease.held(commands.clock.now() + 10):
            before, started = self.snapshot(), time.monotonic()
            completed = subprocess.run([sys.executable, str(SCRIPTS / "memory.py"), "off"],
                                       cwd=str(self.project), stdin=subprocess.DEVNULL,
                                       capture_output=True, timeout=30)
            elapsed = time.monotonic() - started
            self.assertGreaterEqual(elapsed, 10)
            self.assertEqual((completed.returncode, completed.stderr), (1, b""))
            value = json.loads(completed.stdout)
            self.assertEqual((value["command"], value["code"], value["data"]), ("off", "lock-busy", {}))
            self.assertEqual(fits(self.schema, value), [])
            self.assertTrue(completed.stdout.isascii())
            self.assertEqual(completed.stdout.count(b"\n"), 1)
            self.assertEqual(self.snapshot(), before)
            print("COMMAND_RECOVERY_LOCK " + json.dumps({"command": "off", "seconds": round(elapsed, 3),
                                                       "actual_entry": True, "unchanged": True}))

    def test_tc077_unexpected_errors_and_unimplemented_operations_are_safe(self):
        def fail(context):
            raise KeyError(MARKER)
        for command in ARGV:
            value, _, _ = self.invoke(command, handler=fail)
            self.assertEqual((value["code"], value["data"]), ("internal", {"error": "KeyError"}))
            value, _, _ = self.invoke(command, registered=False)
            self.assertEqual((value["code"], value["data"]), ("internal", {"error": "NotImplementedError"}))
            self.assertIn("not implemented", value["say"])
        log = "\n".join(p.read_text(encoding="utf-8") for p in (self.root / "logs").glob("failures-*.jsonl"))
        self.assertNotIn(MARKER, log)
        self.assertEqual({json.loads(line)["error"] for line in log.splitlines()}, {"KeyError", "NotImplementedError"})
        custom = type(MARKER, (ValueError,), {})
        value, _, _ = self.invoke("status", handler=lambda context: (_ for _ in ()).throw(custom(MARKER)))
        self.assertEqual(value["data"], {"error": "ValueError"})
        with mock.patch.object(commands.diagnostics.Diagnostics, "failure", side_effect=RuntimeError(MARKER)):
            value, _, _ = self.invoke("status", handler=fail)
            self.assertEqual(value["data"], {"error": "KeyError"})

    def test_tc078_confirmation_changes_binding_and_accepts_period_boundaries(self):
        applied = []
        preview = {"days": 7, "was": 100, "entries": 3}
        def handler(context):
            return context.confirm(preview, "Review the retention change.",
                                   lambda: applied.append(True) or commands.result("retention", preview, "Changed."))
        with mock.patch.object(commands.time, "time", return_value=1199.999):
            proposal, _, _ = self.invoke("retention", handler=handler)
        token = proposal["confirm"]
        self.assertEqual(applied, [])
        for instant in (1199.999, 1200, 1799.999):
            with mock.patch.object(commands.time, "time", return_value=instant):
                value, _, _ = self.invoke("retention", ["--confirm", token], handler)
                self.assertEqual(value["outcome"], "done")
        with mock.patch.object(commands.time, "time", return_value=1800):
            value, _, _ = self.invoke("retention", ["--confirm", token], handler)
            self.assertEqual(value["code"], "confirm-stale")
            self.assertNotEqual(value["confirm"], token)
        self.assertEqual(len(applied), 3)
        with mock.patch.object(commands.time, "time", return_value=1199.999):
            preview["entries"] += 1
            value, _, _ = self.invoke("retention", ["--confirm", token], handler)
            self.assertEqual((value["code"], value["data"]), ("confirm-stale", preview))
        self.assertEqual(len(applied), 3)

    def test_tc078_all_confirmation_commands_round_trip_without_effects_before_yes(self):
        with mock.patch.dict(ARGV, {"sync": ["on", "https://example.invalid/memory"]}), \
                mock.patch.object(commands.time, "time", return_value=1200):
            for command in ("on", "resume", "forget", "delete-project", "purge", "retention", "sync", "repair"):
                applied = []
                def handler(context):
                    return context.confirm(self.data[command], "Review this proposal.",
                                           lambda: applied.append(True) or commands.result(command, self.data[command], "Changed."))
                proposal, _, _ = self.invoke(command, handler=handler)
                self.assertEqual((proposal["code"], proposal["outcome"], applied), ("ok", "confirm", []))
                done, _, calls = self.invoke(command, ["--confirm", proposal["confirm"]], handler)
                self.assertEqual((done["outcome"], applied), ("done", [True]))
                self.assertNotIn("confirm", calls[0].arguments)
                stale, _, _ = self.invoke(command, ["--confirm", "invalid"], handler)
                self.assertEqual((stale["code"], applied), ("confirm-stale", [True]))

    def test_tc078_missing_store_identity_and_folder_changes_make_confirmation_stale(self):
        def handler(context):
            return context.confirm(self.data["on"], "Review this proposal.",
                                   lambda: commands.result("on", self.data["on"], "Changed."))
        with mock.patch.object(commands.time, "time", return_value=1200):
            with mock.patch.dict(os.environ, {"CORTHEX_MEMORY_HOME": str(self.folder / "absent")}):
                missing, _, _ = self.invoke("on", handler=handler)
            stale, _, _ = self.invoke("on", ["--confirm", missing["confirm"]], handler)
            self.assertEqual(stale["code"], "confirm-stale")
            proposal, _, _ = self.invoke("on", handler=handler)
            child = self.project / "child"
            child.mkdir()
            stale, _, _ = self.invoke("on", ["--folder", str(child), "--confirm", proposal["confirm"]], handler)
            self.assertEqual(stale["code"], "confirm-stale")

    def test_tc073_entry_runs_from_another_folder_and_keeps_one_object(self):
        for target, expected, status in ((self.folder / "missing", "no-store", 0), (self.root, "internal", 1)):
            environment = dict(os.environ, CORTHEX_MEMORY_HOME=str(target))
            completed = subprocess.run([sys.executable, str(SCRIPTS / "memory.py"), "status"], cwd=str(self.project),
                                       env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            self.assertEqual((completed.returncode, completed.stderr), (status, b""))
            self.assertEqual(completed.stdout.count(b"\n"), 1)
            self.assertTrue(completed.stdout.isascii())
            value = json.loads(completed.stdout)
            self.assertEqual((fits(self.schema, value), value["code"]), ([], expected))

    def test_tc077_effect_lock_boundary_and_result_envelope_fail_closed(self):
        path = self.root / "store.lock"
        def effect(context):
            with context.lock(path, "store") as lease:
                lease.check()
            return commands.result("off", self.data["off"], "Changed.")
        before = self.snapshot()
        value, _, _ = self.invoke("off", handler=effect)
        self.assertEqual(value["code"], "ok")
        self.assertEqual(self.snapshot(), before)
        def forbidden(context):
            with context.lock(path, "store", force=True):
                self.fail("force takeover was allowed")
        value, _, _ = self.invoke("off", handler=forbidden)
        self.assertEqual(value["data"], {"error": "ValueError"})
        for change in ({"say": "x" * 601}, {"outcome": "failed"}, {"confirm": "00000000"}):
            bad = commands.result("off", self.data["off"], "Ready.")
            bad.update(change)
            value, _, _ = self.invoke("off", handler=lambda context: bad)
            self.assertEqual(value["code"], "internal")

    def test_tc078_fixed_vector_canonicalization_and_each_bound_field(self):
        # Calculated independently from this literal ASCII payload, not confirmation().
        # ["none","retention",{"days":7},{"days":7,"entries":3,"was":100},2]
        # SHA-256: aec9fedabb3a99b52d6e140cc7f66777a26221551063cb859e50a547fe1a7a0a
        expected = "nv4zxpnv"
        data = {"was": 100, "entries": 3, "days": 7}
        self.assertEqual(commands.confirmation(None, "retention", {"days": 7}, data, 2), expected)
        variants = [("d_0a3c6f9h2k5n", "retention", {"days": 7}, data, 2),
                    (None, "purge", {"days": 7}, data, 2), (None, "retention", {"days": 8}, data, 2),
                    (None, "retention", {"days": 7}, dict(data, entries=4), 2),
                    (None, "retention", {"days": 7}, data, 3)]
        self.assertEqual(len({expected} | {commands.confirmation(*variant) for variant in variants}), 6)
        self.assertEqual(commands.canonical({"z": "한글", "a": [1, True]}), '{"a":[1,true],"z":"\\ud55c\\uae00"}')
        with self.assertRaises(ValueError):
            commands.confirmation(None, "retention", {}, {"bad": float("nan")}, 2)
        with mock.patch.object(sys, "stdout", new_callable=io.StringIO) as out:
            self.assertEqual(commands.main(["unknown"]), 2)
            self.assertEqual(json.loads(out.getvalue())["command"], "none")


if __name__ == "__main__":
    unittest.main()
