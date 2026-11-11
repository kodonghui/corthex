"""TASK-064 / TC-334: independent result verdicts and the safe boundary."""

import copy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from _common import ROOT, load_json
from test_memory_api import fits

SCRIPTS = ROOT / "plugins/corthex-memory/skills/corthex-memory/scripts"
sys.path.insert(0, str(SCRIPTS))
from memory_lib import command_result as result
from memory_lib import configuration

API = ROOT / "docs/06-api"
PRIVATE = "private-test-value-must-not-leak"


class CommandResultTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (API / "memory-result.schema.json").read_bytes()
        cls.schema = json.loads(cls.raw)
        cls.examples = load_json(API / "memory-examples.json")
        cls.group = cls.examples["result"]

    def common(self, data=None):
        return {"command": "status", "outcome": "failed", "code": "internal",
                "say": "An error occurred.", "data": {} if data is None else data}

    def assert_fallback(self, candidate, command="status", error="RuntimeError"):
        before = copy.deepcopy(candidate)
        out, status = result.finalize(command, candidate)
        self.assertEqual(status, 1)
        self.assertEqual(out, {"command": command if command in result.COMMANDS else "none",
                              "outcome": "failed", "code": "internal", "say": result.SAY,
                              "data": {"error": error}})
        self.assertEqual(fits(self.schema, out), [])
        self.assertEqual(candidate, before)
        self.assertNotIn(PRIVATE, json.dumps(out))
        return out

    def test_tc334_all_result_examples_keep_independent_verdicts_and_statuses(self):
        self.assertEqual(len(self.group["valid"]), 43)
        self.assertEqual(len(self.group["invalid"]), 14)
        self.assertEqual(result.RESOURCE.read_bytes(), self.raw)
        for name, value in self.group["valid"].items():
            with self.subTest(valid=name):
                self.assertEqual(fits(self.schema, value), [])
                original = copy.deepcopy(value)
                result.validate(value)
                out, status = result.finalize(value["command"], value)
                expected = 2 if value["code"] == "usage" else 0 if value["outcome"] in ("done", "confirm", "nothing") else 1
                self.assertEqual((out, status), (value, expected))
                self.assertEqual(value, original)
                self.assertIsNot(out, value)
                self.assertIsNot(out["data"], value["data"])
                out["data"]["detached-test"] = True
                self.assertEqual(value, original)
        for name, value in self.group["invalid"].items():
            with self.subTest(invalid=name):
                self.assertNotEqual(fits(self.schema, value), [])
                with self.assertRaisesRegex(result.ResultInvalid, "^invalid command result$"):
                    result.validate(value)
                self.assert_fallback(value, value.get("command", "none"))

    def test_tc334_original_off_handler_regressions_are_refused(self):
        for data in ({}, {"project": 17}, {"project": "demo", "unexpected": True}):
            value = {"command": "off", "outcome": "done", "code": "ok",
                     "say": "Completed.", "data": data}
            with self.subTest(data=data):
                self.assertNotEqual(fits(self.schema, value), [])
                self.assert_fallback(value, "off")

    def test_tc334_required_top_types_extra_fields_and_command_binding(self):
        good = self.group["valid"]["status"]
        for field in self.schema["required"]:
            bad = copy.deepcopy(good)
            del bad[field]
            self.assert_fallback(bad)
        for field, replacement in (("command", PRIVATE), ("outcome", []), ("code", True),
                                   ("say", ""), ("say", "x" * 601), ("data", [])):
            bad = copy.deepcopy(good)
            bad[field] = replacement
            self.assert_fallback(bad)
        bad = copy.deepcopy(good)
        bad[PRIVATE] = PRIVATE
        self.assert_fallback(bad)
        self.assert_fallback(good, "off")

    def test_tc334_deep_nested_and_common_data_mismatches(self):
        for name in ("on-done", "status", "open-around", "forget-asks", "purge-files-left"):
            original = self.group["valid"][name]
            def objects(value, path=()):
                if type(value) is dict:
                    if path:
                        yield path
                    for key, child in value.items():
                        yield from objects(child, path + (key,))
                elif type(value) is list:
                    for index, child in enumerate(value):
                        yield from objects(child, path + (index,))
            checked = 0
            for path in objects(original["data"]):
                bad = copy.deepcopy(original)
                target = bad["data"]
                for part in path:
                    target = target[part]
                target[PRIVATE] = PRIVATE
                if fits(self.schema, bad):
                    self.assert_fallback(bad, original["command"])
                    checked += 1
            self.assertGreater(checked, 0, name)
        for field, value in (("words", 17), ("held", "unknown"), ("said", "bad-time")):
            bad = copy.deepcopy(self.group["valid"]["open-around"])
            bad["data"]["items"][0]["quotes"][0][field] = value
            self.assertNotEqual(fits(self.schema, bad), [])
            self.assert_fallback(bad, "open")
        bad = copy.deepcopy(self.group["valid"]["open-around"])
        del bad["data"]["items"][0]["quotes"][0]["entry"]
        self.assert_fallback(bad, "open")
        for data in ({"project": 17}, {"project": "demo\n"}, {"field": ""},
                     {"field": "x" * 201}, {"clash": ["Bad"]}, {"error": PRIVATE + "\n"},
                     {"error": 1}, {PRIVATE: PRIVATE}):
            self.assert_fallback(self.common(data))

    def test_tc334_confirmation_and_outcome_conditions_are_enforced(self):
        ask = self.group["valid"]["retention-asks"]
        for token in (None, "short", "iiiiiiii", "00000000\n"):
            bad = copy.deepcopy(ask)
            if token is None:
                del bad["confirm"]
            else:
                bad["confirm"] = token
            self.assertNotEqual(fits(self.schema, bad), [])
            self.assert_fallback(bad, "retention")
        bad = self.common()
        bad["confirm"] = "00000000"
        self.assert_fallback(bad)
        for code, outcome in (("internal", "done"), ("usage", "failed"), ("ok", "failed")):
            bad = self.common()
            bad.update(code=code, outcome=outcome)
            self.assert_fallback(bad)

    def test_tc334_non_json_nonfinite_and_recursive_values_fail_safely(self):
        for value in (float("nan"), float("inf"), -float("inf"), (), object(), {17: "x"}):
            bad = self.common({"error": value})
            out, status = result.finalize("status", bad)
            self.assertEqual((out["code"], status), ("internal", 1))
            self.assertEqual(fits(self.schema, out), [])
        bad = self.common()
        bad["data"]["cycle"] = bad
        out, status = result.finalize("status", bad)
        self.assertEqual((out["code"], status), ("internal", 1))
        self.assertEqual(fits(self.schema, out), [])

    def test_tc334_supported_keyword_semantics_match_independent_checks(self):
        schemas = [
            ({"$defs": {"n": {"type": "integer", "minimum": 2}}, "$ref": "#/$defs/n", "maximum": 3}, [2, 2.0, 3], [True, 1, 4]),
            ({"enum": [True, 1]}, [True, 1, 1.0], [False, "1"]),
            ({"const": True}, [True], [1, False]),
            ({"type": "array", "minItems": 1, "maxItems": 3, "uniqueItems": True, "items": {"enum": [True, 1]}}, [[True, 1]], [[], [1, 1.0], [True, 1, 1, 1]]),
            ({"type": "object", "propertyNames": {"pattern": "^p$"}, "additionalProperties": {"type": "string", "minLength": 1, "maxLength": 2}}, [{"p": "ok"}], [{"p\n": "x"}, {"p": ""}, {"p": 1}]),
            ({"allOf": [{"type": "integer"}, {"not": {"const": 2}}], "anyOf": [{"const": 1}, {"const": 3}]}, [1, 3], [2, True, 4]),
            ({"if": {"properties": {"x": {"const": True}}}, "then": {"required": ["y"]}, "else": {"not": {"required": ["y"]}}}, [{"x": True, "y": 1}, {"x": False}], [{"x": True}, {"x": False, "y": 1}]),
            ({"type": "null"}, [None], [False, 0]),
        ]
        for schema, valid, invalid in schemas:
            engine = result._Validator(schema)
            for expected, values in ((True, valid), (False, invalid)):
                for value in values:
                    self.assertEqual(not fits(schema, value), expected)
                    self.assertEqual(engine.matches(value), expected)

    def test_tc334_schema_audit_covers_unvisited_branches_shapes_and_refs(self):
        invalid = [
            {"anyOf": [True, {"unsupported": PRIVATE}]},
            {"if": False, "then": {"format": PRIVATE}, "else": True},
            {"$defs": {"unused": {"additionalProperties": {"unknown": True}}}},
            {"$ref": "https://example.invalid/never-contacted"},
            {"$ref": "#/$defs/missing", "$defs": {}},
            {"$defs": {"cycle": {"$ref": "#/$defs/cycle"}}},
            {"$defs": {"a": {"$ref": "#/$defs/b"}, "b": {"$ref": "#/$defs/a"}}},
            {"type": ["string", "null"]}, {"type": "unsupported"}, {"items": []},
            {"properties": []}, {"required": "x"}, {"required": ["x", "x"]},
            {"anyOf": []}, {"allOf": {}}, {"enum": [1, 1.0]}, {"enum": []},
            {"pattern": "["}, {"maximum": True}, {"maxItems": -1}, {"uniqueItems": 1},
        ]
        for schema in invalid:
            with self.subTest(schema=schema), self.assertRaisesRegex(result.SchemaInvalid, "^unusable command result schema$"):
                result._Validator(schema)

    def test_tc334_resource_is_not_cached_and_wrong_schema_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.schema.json"
            path.write_bytes(self.raw)
            with mock.patch.object(result, "RESOURCE", path):
                result.validate(self.group["valid"]["status"])
                path.write_bytes((API / "memory-configuration.schema.json").read_bytes())
                self.assert_fallback(self.group["valid"]["status"])
                path.write_bytes(b'{"type":"object","type":"string"}')
                self.assert_fallback(self.common())
                path.unlink()
                self.assert_fallback(self.common())
        with mock.patch.object(Path, "read_bytes", side_effect=PermissionError(PRIVATE)) as reader:
            self.assert_fallback(self.common())
            self.assertEqual(reader.call_count, 1)

    def test_tc334_configuration_cache_and_all_other_schema_examples_stay_separate(self):
        configuration.schema.cache_clear()
        self.addCleanup(configuration.schema.cache_clear)
        cached = configuration.schema()
        for group, examples in self.examples.items():
            if group in ("description", "result"):
                continue
            for value in examples["valid"].values():
                self.assert_fallback(value)
        result.validate(self.group["valid"]["status"])
        self.assertIs(configuration.schema(), cached)
        configuration.validate(self.examples["configuration"]["valid"]["with-sync"])

    def test_tc334_fallback_does_not_reenter_failed_validator_or_loader(self):
        good = self.group["valid"]["status"]
        for name in ("validate", "_load"):
            with mock.patch.object(result, name, side_effect=RuntimeError(PRIVATE)) as failed:
                self.assert_fallback(good)
                self.assertEqual(failed.call_count, 1)
        for cls, expected in result.ERRORS:
            with mock.patch.object(result, "validate", side_effect=cls(PRIVATE)):
                self.assert_fallback(good, error=expected)

    def test_tc334_hostile_exception_names_messages_and_unknown_command_never_escape(self):
        class Hostile(type):
            def __getattribute__(cls, name):
                if name in ("__name__", "__module__"):
                    raise AssertionError(PRIVATE)
                return super().__getattribute__(name)
        class HiddenError(RuntimeError, metaclass=Hostile):
            pass
        candidate = self.common({"error": PRIVATE})
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            with mock.patch.object(result, "validate", side_effect=HiddenError(PRIVATE)):
                self.assert_fallback(candidate, PRIVATE)
        self.assertEqual((stdout.getvalue(), stderr.getvalue()), ("", ""))
        for command in result.COMMANDS:
            with mock.patch.object(result, "validate", side_effect=RuntimeError(PRIVATE)):
                self.assert_fallback(candidate, command)

    def test_tc334_standalone_library_needs_only_packaged_resource_and_stdlib(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "plugin"
            target.mkdir()
            for path in (Path(result.__file__), result.RESOURCE):
                shutil.copyfile(str(path), str(target / path.name))
            candidate = root / "candidate.json"
            candidate.write_text(json.dumps(self.group["valid"]["status"]), encoding="utf-8")
            program = ("import json,sys;sys.path.insert(0,sys.argv[1]);import command_result;"
                       "out,status=command_result.finalize('status',json.load(open(sys.argv[2])));"
                       "print(json.dumps([out,status],ensure_ascii=True))")
            done = subprocess.run([sys.executable, "-I", "-B", "-c", program, str(target), str(candidate)],
                                  cwd=str(root), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, timeout=20)
            self.assertEqual((done.returncode, done.stderr), (0, b""))
            out, status = json.loads(done.stdout)
            self.assertEqual((out, status), (self.group["valid"]["status"], 0))
            self.assertEqual(fits(self.schema, out), [])


if __name__ == "__main__":
    unittest.main()
