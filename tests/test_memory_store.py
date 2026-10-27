"""TC-009–012: strict configuration and store gates, using made-up stores."""

import copy
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from _common import ROOT
from test_memory_api import fits

SCRIPTS = ROOT / "plugins/corthex-memory/skills/corthex-memory/scripts"
sys.path.insert(0, str(SCRIPTS))
from memory_lib import base, configuration, files, locks, store

API = ROOT / "docs/06-api"
AT = "2026-10-27T09:12:03.004Z"


class StoreCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.root = self.folder / "memory"
        environment = mock.patch.dict(os.environ, {
            "HOME": str(self.folder / "home"), "USERPROFILE": str(self.folder / "home"),
            "CORTHEX_HOME": str(self.folder / "profile"), "CORTHEX_MEMORY_HOME": str(self.root),
            "CLAUDE_CODE_REMOTE": "false",
        })
        environment.start()
        self.addCleanup(environment.stop)
        base.private_directory(self.root / "logs")
        self.memory = store.MemoryStore()
        self.header = store.new_record("0.2.0")
        self.header["made"] = AT
        files.write_json(self.root / "store.json", self.header, "TBL-001")
        self.examples = json.loads((API / "memory-examples.json").read_text(encoding="utf-8"))["configuration"]
        self.schema = json.loads((API / "memory-configuration.schema.json").read_text(encoding="utf-8"))

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.root.rglob("*") if p.is_file()}

    def assert_invalid(self, document, field=None):
        with self.assertRaises(configuration.ConfigurationInvalid) as caught:
            configuration.prepare(document)
        self.assertEqual(caught.exception.code, "configuration-invalid")
        self.assertEqual(str(caught.exception), "configuration-invalid")
        if field is not None:
            self.assertEqual(caught.exception.field, field)


class MemoryStoreTest(StoreCase):
    def test_tc009_portable_schema_is_identical_and_unknown_keywords_fail(self):
        self.assertEqual((SCRIPTS / "memory_lib/configuration.schema.json").read_bytes(),
                         (API / "memory-configuration.schema.json").read_bytes())
        configuration.schema.cache_clear()
        altered = copy.deepcopy(self.schema)
        altered["$defs"]["price"]["properties"]["input"]["unimplemented"] = True
        with mock.patch.object(Path, "read_text", return_value=json.dumps(altered)):
            with self.assertRaisesRegex(RuntimeError, "unsupported configuration schema keyword"):
                configuration.schema()
        configuration.schema.cache_clear()
        with self.assertRaisesRegex(RuntimeError, "unsupported configuration reference"):
            configuration.resolve({"$ref": "https://example.invalid/schema"})

    def test_tc009_all_valid_examples_round_trip_under_store_lock(self):
        for name, document in self.examples["valid"].items():
            with self.subTest(example=name):
                self.assertEqual(fits(self.schema, document), [])
                original = copy.deepcopy(document)
                written = self.memory.write_configuration(document, time.monotonic() + 2)
                read = self.memory.configuration(deadline=time.monotonic() + 1)
                self.assertEqual(document, original)
                self.assertEqual(written.document, document)
                self.assertEqual(read.document, document)
                self.assertEqual(read.values, written.values)
                self.assertFalse((self.root / "store.lock").exists())
                self.assertFalse(list(self.root.glob("*.tmp")))
                self.assertFalse(list(self.root.glob("*.bak")))

    def test_tc009_all_invalid_examples_report_the_first_safe_field(self):
        expected = {
            "unknown-field": "retention.<unknown>", "retention-too-long": "retention.days",
            "dims-too-small": "models.dims", "effort": "models.effort",
            "consent-without-version": "consent.version", "time-without-milliseconds": "consent.at",
            "project-name": "projects", "folder-up": "projects.*.left_out.folders[0]",
            "folder-absolute": "projects.*.left_out.folders[0]",
            "folder-backslash": "projects.*.left_out.folders[0]",
            "folder-line-break": "projects.*.left_out.folders[0]", "kind": "projects.*.left_out.kinds[0]",
            "branch-dash": "sync.branch", "sync-without-address": "sync.address",
            "price-without-output": "prices.models.*.output", "price-page-http": "prices.from[0]",
            "threshold-text": "recall.threshold", "temporary-text": "temporary",
        }
        self.assertEqual(set(expected), set(self.examples["invalid"]))
        for name, document in self.examples["invalid"].items():
            with self.subTest(example=name):
                self.assertTrue(fits(self.schema, document))
                self.assert_invalid(document, expected[name])
                before = self.snapshot()
                with self.assertRaises(configuration.ConfigurationInvalid):
                    self.memory.write_configuration(document, time.monotonic() + 2)
                self.assertEqual(self.snapshot(), before)

    def test_tc009_defaults_are_effective_only_and_never_add_consent(self):
        prepared = configuration.prepare({})
        self.assertEqual(prepared.document, {})
        self.assertFalse(prepared.consented())
        self.assertFalse(prepared.enabled("sample"))
        self.assertEqual(prepared.values["projects"], {})
        self.assertEqual(prepared.values["retention"], {"days": 100})
        self.assertEqual(prepared.values["triggers"], {"turns": 10, "minutes": 30})
        self.assertEqual(prepared.values["models"], {"curator": "claude-haiku-5-5", "effort": "xhigh",
                                                  "embedding": "text-embedding-3-small", "dims": 512})
        self.assertEqual(prepared.values["recall"], {"skip": 8})
        self.assertEqual(prepared.values["prices"], self.schema["properties"]["prices"]["default"])
        self.assertNotIn("sync", prepared.values)
        prepared.values["prices"]["models"].clear()
        self.assertTrue(configuration.prepare({}).values["prices"]["models"])
        self.memory.write_configuration({}, time.monotonic() + 2)
        self.assertEqual((self.root / "configuration.json").read_bytes(), b"{}\n")
        self.assert_invalid({"consent": {}}, "consent.at")

    def test_tc009_consent_version_and_project_switch_are_both_required(self):
        document = copy.deepcopy(self.examples["valid"]["tuned"])
        self.assertTrue(configuration.prepare(document).enabled("corthex"))
        self.assertFalse(configuration.prepare(document).enabled("corthex-docs"))
        self.assertFalse(configuration.prepare(document).enabled("unlisted"))
        document["consent"]["version"] = 2
        self.assertFalse(configuration.prepare(document).enabled("corthex"))
        del document["consent"]
        self.assertFalse(configuration.prepare(document).enabled("corthex"))

    def test_tc009_temporary_override_stays_out_of_the_document(self):
        for remote, expected in (("true", True), ("false", False), ("TRUE", False)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_REMOTE": remote}):
                self.assertEqual(configuration.prepare({}).values["temporary"], expected)
                self.assertFalse(configuration.prepare({"temporary": False}).values["temporary"])
        self.assertTrue(configuration.prepare({}, temporary=True).values["temporary"])
        self.assertEqual(configuration.prepare({}, temporary=True).document, {})

    def test_tc009_schema_invalid_primary_never_resurrects_old_consent(self):
        path = self.root / "configuration.json"
        path.write_text('{"consent": {"at": "bad", "version": 1}}', encoding="utf-8")
        path.with_name(path.name + ".bak").write_text(json.dumps(self.examples["valid"]["tuned"]), encoding="utf-8")
        before = self.snapshot()
        with self.assertRaises(configuration.ConfigurationInvalid) as caught:
            self.memory.configuration(deadline=time.monotonic() + 1)
        self.assertEqual(caught.exception.field, "consent.at")
        self.assertEqual(self.snapshot(), before)

    def test_tc009_broken_configuration_json_restores_only_a_valid_backup(self):
        path = self.root / "configuration.json"
        for broken in (b"{", b"\xff", b'{"temporary":false,"temporary":true}', b'{"recall":{"threshold":NaN}}'):
            with self.subTest(kind=broken[:1]):
                path.write_bytes(broken)
                path.with_name(path.name + ".bak").write_bytes(b"{}\n")
                notices = []
                self.assertEqual(self.memory.configuration(lambda *args: notices.append(args), deadline=time.monotonic() + 1).document, {})
                self.assertEqual(notices, [("restored", None)])
                self.assertEqual(path.read_bytes(), b"{}\n")
                path.write_bytes(broken)
                with self.assertRaises(configuration.ConfigurationInvalid):
                    self.memory.configuration(deadline=time.monotonic() + 1)

    def test_tc010_all_numeric_bounds_and_field_types_match_the_schema(self):
        document = configuration.prepare(self.examples["valid"]["with-sync"]).values
        document["recall"]["threshold"] = 0.5
        def walk(value, node, path=()):
            node = configuration.resolve(node)
            yield path, node
            if isinstance(value, dict):
                for key, item in value.items():
                    child = node.get("properties", {}).get(key, node.get("additionalProperties", True))
                    if isinstance(child, dict):
                        yield from walk(item, child, path + (key,))
            if isinstance(value, list) and value and isinstance(node.get("items"), dict):
                yield from walk(value[0], node["items"], path + (0,))
        count = 0
        for path, node in walk(document, self.schema):
            if not path:
                continue
            cases = [(None, False)] if "type" in node else []
            for edge, delta in (("minimum", -1), ("maximum", 1)):
                if edge in node:
                    cases += [(node[edge], True), (node[edge] + delta, False)]
                    count += 1
            for candidate, valid in cases:
                with self.subTest(path=path, candidate=candidate):
                    altered = copy.deepcopy(document)
                    target = altered
                    for key in path[:-1]:
                        target = target[key]
                    target[path[-1]] = candidate
                    self.assertEqual(not fits(self.schema, altered), valid)
                    if valid:
                        configuration.prepare(altered)
                    else:
                        self.assert_invalid(altered)
        self.assertGreaterEqual(count, 20)

    def test_tc010_integer_is_a_finite_json_number_with_no_fraction(self):
        for value in (1, 1.0):
            doc = {"retention": {"days": value}}
            self.assertEqual(fits(self.schema, doc), [])
            self.assertIs(type(configuration.prepare(doc).values["retention"]["days"]), int)
        for value in (True, False, 1.5, float("inf"), float("nan")):
            self.assert_invalid({"retention": {"days": value}}, "retention.days")
            self.assertTrue(fits(self.schema, {"retention": {"days": value}}))
        for value in (True, False, float("inf"), float("nan")):
            self.assert_invalid({"recall": {"threshold": value}}, "recall.threshold")
            self.assertTrue(fits(self.schema, {"recall": {"threshold": value}}))

    def test_tc010_string_length_and_pattern_edges(self):
        project = {"enabled": True, "since": AT}
        good = [({"projects": {"a" * 60: project}}, {"projects": {"a" * 61: project}}),
                ({"models": {"curator": "a" * 64}}, {"models": {"curator": "a" * 65}}),
                ({"sync": {"address": "x" * 2000}}, {"sync": {"address": "x" * 2001}}),
                ({"sync": {"address": "x", "branch": "x" * 100}},
                 {"sync": {"address": "x", "branch": "x" * 101}})]
        for valid, invalid in good:
            configuration.prepare(valid)
            self.assert_invalid(invalid)
        for name in ("", "A", "-a", "a\n", "a\r", "a/.."):
            self.assert_invalid({"projects": {name: project}}, "projects")
        for fragment in ({"consent": {"at": AT + "\n", "version": 1}},
                         {"models": {"curator": "a\n"}}, {"sync": {"address": "x\n"}},
                         {"sync": {"address": "x", "branch": "a\n"}}):
            self.assert_invalid(fragment)
        for path, valid in (("a", True), ("a" * 400, True), ("a" * 401, False), ("a/b", True),
                            ("", False), ("a//b", False), (".", False), ("a/../b", False),
                            ("a/.", False), ("/a", False), ("a\\b", False), ("a:b", False), ("a\n", False)):
            doc = {"projects": {"sample": dict(project, left_out={"folders": [path]})}}
            if valid:
                configuration.prepare(doc)
            else:
                self.assert_invalid(doc)

    def test_tc010_unicode_pattern_edges_agree_with_the_schema(self):
        for folder in ("x\u2028/../y", "x\u2029/.."):
            document = {"projects": {"sample": {"enabled":True,"since":AT,"left_out":{"folders":[folder]}}}}
            self.assertTrue(fits(self.schema,document))
            self.assert_invalid(document,"projects.*.left_out.folders[0]")
        for char in ("\ufeff", "\u001c", "\u0085"):
            document = copy.deepcopy(self.examples["valid"]["own-prices"])
            document["prices"]["from"] = ["https://a"+char+"b"]
            self.assertTrue(fits(self.schema,document))
            self.assert_invalid(document,"prices.from[0]")
        document["prices"]["from"] = ["https://example.invalid/%E2%80%A8"]
        self.assertFalse(fits(self.schema,document))
        configuration.prepare(document)

    def test_tc010_every_pattern_agrees_with_node_ecma_u_for_boundary_values(self):
        executable = next((Path(folder) / ("node.exe" if os.name == "nt" else "node")
                           for folder in os.get_exec_path() if Path(folder).is_absolute()
                           and (Path(folder) / ("node.exe" if os.name == "nt" else "node")).is_file()), None)
        if executable is None:
            self.skipTest("Node.js is not installed in an absolute PATH folder")
        patterns = []
        def visit(value):
            if isinstance(value,dict):
                if "pattern" in value: patterns.append(value["pattern"])
                for child in value.values(): visit(child)
            elif isinstance(value,list):
                for child in value: visit(child)
        visit(self.schema)
        values = ["x\u2028/../y","x\u2029/..","https://a\ufeffb","https://a\u001cb","https://a\u0085b",
                  "folder/sub","a/../b","sample","main","https://example.invalid/%E2%80%A8"]
        expected = [[bool(re.search(pattern.replace("$",r"\Z"),value)) for value in values] for pattern in patterns]
        program = 'let b="";process.stdin.setEncoding("utf8");process.stdin.on("data",x=>b+=x);process.stdin.on("end",()=>{const d=JSON.parse(b);process.stdout.write(JSON.stringify(d.patterns.map(p=>d.values.map(v=>new RegExp(p,"u").test(v)))))});'
        result = subprocess.run([str(executable),"-e",program],input=json.dumps({"patterns":patterns,"values":values}),
                                capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout),expected)

    def test_tc010_array_limits_uniqueness_and_price_requirements(self):
        document = copy.deepcopy(self.examples["valid"]["tuned"])
        left = document["projects"]["corthex"]["left_out"]
        left["folders"] = ["f%d" % n for n in range(50)]
        configuration.prepare(document)
        left["folders"].append("f50")
        self.assert_invalid(document)
        left["folders"] = ["same", "same"]
        self.assert_invalid(document)
        left["folders"] = []
        left["kinds"] = ["prompt", "prompt"]
        self.assert_invalid(document)
        document = copy.deepcopy(self.examples["valid"]["own-prices"])
        document["prices"]["from"] = ["https://example.invalid/" + str(n) for n in range(10)]
        configuration.prepare(document)
        document["prices"]["from"].append("https://example.invalid/extra")
        self.assert_invalid(document)
        document["prices"]["from"] = []
        self.assert_invalid(document)
        document["prices"]["from"] = ["https://" + "a" * 1992]
        configuration.prepare(document)
        document["prices"]["from"][0] += "a"
        self.assert_invalid(document)
        document["prices"]["from"] = ["https://example.invalid/prices"]
        document["prices"]["models"] = {}
        self.assert_invalid(document, "prices.models")

    def test_tc010_error_order_is_deterministic_and_does_not_echo_unknown_keys(self):
        self.assert_invalid({"models": {"dims": 1}, "retention": {"days": 0}}, "retention.days")
        self.assert_invalid({"private-text": True}, "<unknown>")
        self.assert_invalid({"projects": {"sample": {"since": "bad", "enabled": True}}}, "projects.*.since")
        self.assert_invalid({"projects": {1: {}}}, "projects")

    def test_tc011_newer_and_migrating_headers_are_opaque_and_read_nothing_else(self):
        (self.root / "configuration.json").write_bytes(b"made-up private data")
        path = self.root / "store.json"
        path.with_name("store.json.bak").write_bytes(base.json_bytes(self.header, "TBL-001"))
        for record in ({"format": 2}, {"format": 1, "migrating": None},
                       dict(self.header, migrating={"from": 1, "to": 2, "started": AT})):
            path.write_text(json.dumps(record), encoding="utf-8")
            before = self.snapshot()
            read = Path.read_bytes
            accessed = []
            def observed(target):
                accessed.append(target)
                return read(target)
            with mock.patch.object(Path, "read_bytes", observed):
                with self.assertRaises(store.StoreUnavailable) as caught:
                    self.memory.configuration(deadline=time.monotonic() + 1)
            self.assertEqual(caught.exception.code, "store-newer")
            self.assertEqual(accessed, [path])
            self.assertEqual(self.snapshot(), before)

    def test_tc011_missing_and_damaged_records_block_without_a_backup(self):
        path = self.root / "store.json"
        (self.root / "configuration.json").write_bytes(b"{}\n")
        for broken in (None, b"{", b"\xff", b"[]", b'{"format":true}', b'{"format":1}',
                       b'{"format":1,"format":2}'):
            if broken is None:
                path.unlink()
            else:
                path.write_bytes(broken)
            before = self.snapshot()
            read = Path.read_bytes
            accessed = []
            def observed(target):
                accessed.append(target.name)
                return read(target)
            with mock.patch.object(Path, "read_bytes", observed):
                with self.assertRaises(store.StoreUnavailable) as caught:
                    self.memory.configuration(deadline=time.monotonic() + 1)
            self.assertEqual(caught.exception.code, "store-damaged")
            self.assertEqual(accessed, ["store.json", "store.json.bak"])
            self.assertEqual(self.snapshot(), before)

    def test_tc011_a_valid_backup_restores_but_an_opaque_backup_blocks(self):
        path = self.root / "store.json"
        backup = path.with_name("store.json.bak")
        for broken in (None, b"{", b"\xff", b'{"format":1,"device":"bad"}'):
            if path.exists():
                path.unlink()
            if broken is not None:
                path.write_bytes(broken)
            backup.write_bytes(base.json_bytes(self.header, "TBL-001"))
            notices = []
            with mock.patch.object(store.locks,"Lock",wraps=locks.Lock) as lease:
                self.assertEqual(self.memory.record(lambda *args: notices.append(args), deadline=time.monotonic() + 1), self.header)
            self.assertEqual(lease.call_args[0][2],self.header["device"])
            self.assertEqual(notices, [("restored", None)])
            self.assertFalse(backup.exists())
        path.write_bytes(b"{")
        backup.write_bytes(b'{"format":2}')
        before = self.snapshot()
        with self.assertRaises(store.StoreUnavailable) as caught:
            self.memory.record(deadline=time.monotonic() + 1)
        self.assertEqual(caught.exception.code, "store-newer")
        self.assertEqual(self.snapshot(), before)

    def test_tc011_store_record_has_strict_fields_and_valid_factory_ids(self):
        for key, value in (("device", "d_" + "i" * 12), ("made", AT + "\n"), ("release", ""),
                           ("extra", "text"), ("format", 0), ("format", 1.5)):
            record = dict(self.header, **{key: value})
            (self.root / "store.json").write_text(json.dumps(record), encoding="utf-8")
            with self.assertRaises(store.StoreUnavailable) as caught:
                self.memory.record(deadline=time.monotonic() + 1)
            self.assertEqual(caught.exception.code, "store-damaged")
        self.assertRegex(store.new_record("0.2.0")["device"], r"d_[0-9a-hjkmnp-tv-z]{12}\Z")
        with self.assertRaises(ValueError):
            store.new_record(1)

    def test_tc011_operational_read_errors_propagate_without_restoring_or_writing(self):
        for name in ("store.json", "configuration.json"):
            path = self.root / name
            data = base.json_bytes(self.header, "TBL-001") if name == "store.json" else b"{}\n"
            path.write_bytes(data)
            path.with_name(name + ".bak").write_bytes(data)
            for failure in (PermissionError, OSError):
                with self.subTest(record=name, error=failure.__name__):
                    accessed = []
                    before = self.snapshot()
                    original = Path.read_bytes
                    def read(target):
                        accessed.append(target.name)
                        if target == path:
                            raise failure("made-up inaccessible record")
                        return original(target)
                    with mock.patch.object(Path, "read_bytes", read):
                        with self.assertRaises(failure):
                            self.memory.configuration(deadline=time.monotonic() + 2)
                    self.assertNotIn(name + ".bak", accessed)
                    self.assertEqual(self.snapshot(), before)

    def test_tc011_configuration_recovery_rechecks_gate_after_acquiring_lease(self):
        path = self.root / "configuration.json"
        backup = path.with_name(path.name+".bak")
        for header, expected in (({"format":2},store.StoreUnavailable),
                                 (dict(self.header,migrating={}),store.StoreUnavailable),
                                 (dict(self.header,device=base.new_id("d")),locks.LostLock)):
            with self.subTest(header=header.get("format"),exception=expected.__name__):
                if path.exists(): path.unlink()
                (self.root/"store.json").write_bytes(base.json_bytes(self.header,"TBL-001"))
                backup.write_bytes(b"{}\n")
                acquired, late_reads, notices = [], [], []
                acquire, read = locks.Lock.acquire, Path.read_bytes
                def changed(lease,*args,**kwargs):
                    result = acquire(lease,*args,**kwargs)
                    (self.root/"store.json").write_bytes(base.json_bytes(header,"TBL-001"))
                    acquired.append(True)
                    return result
                def observed(target):
                    if acquired and target in (path,backup): late_reads.append(target.name)
                    return read(target)
                with mock.patch.object(locks.Lock,"acquire",changed), mock.patch.object(Path,"read_bytes",observed):
                    with self.assertRaises(expected):
                        self.memory.configuration(lambda *n:notices.append(n),deadline=time.monotonic()+2)
                self.assertEqual(late_reads,[])
                self.assertFalse(path.exists())
                self.assertEqual(backup.read_bytes(),b"{}\n")
                self.assertEqual(notices,[])

    def test_tc011_changed_device_in_header_backup_is_not_restored_under_old_lease(self):
        path = self.root/"configuration.json"
        backup = path.with_name(path.name+".bak")
        backup.write_bytes(b"{}\n")
        header_path = self.root/"store.json"
        header_backup = header_path.with_name("store.json.bak")
        replacement = base.json_bytes(dict(self.header,device=base.new_id("d")),"TBL-001")
        acquire = locks.Lock.acquire
        def changed(lease,*args,**kwargs):
            result = acquire(lease,*args,**kwargs)
            header_path.unlink()
            header_backup.write_bytes(replacement)
            return result
        with mock.patch.object(locks.Lock,"acquire",changed):
            with self.assertRaises(locks.LostLock):
                self.memory.configuration(deadline=time.monotonic()+2)
        self.assertFalse(header_path.exists())
        self.assertFalse(path.exists())
        self.assertEqual(header_backup.read_bytes(),replacement)
        self.assertEqual(backup.read_bytes(),b"{}\n")

    def test_tc011_header_recovery_rechecks_backup_device_after_waiting(self):
        path = self.root/"store.json"
        backup = path.with_name("store.json.bak")
        path.unlink()
        backup.write_bytes(base.json_bytes(self.header,"TBL-001"))
        replacement = base.json_bytes(dict(self.header,device=base.new_id("d")),"TBL-001")
        acquire = locks.Lock.acquire
        def changed(lease,*args,**kwargs):
            result = acquire(lease,*args,**kwargs)
            backup.write_bytes(replacement)
            return result
        with mock.patch.object(locks.Lock,"acquire",changed):
            with self.assertRaises(locks.LostLock):
                self.memory.record(deadline=time.monotonic()+2)
        self.assertFalse(path.exists())
        self.assertEqual(backup.read_bytes(),replacement)

    def test_tc011_restore_needed_runtime_failure_has_a_safe_store_result(self):
        path = self.root / "store.json"
        path.write_bytes(b"{")
        path.with_name("store.json.bak").write_bytes(base.json_bytes(self.header, "TBL-001"))
        before = self.snapshot()
        with mock.patch.object(store.reading, "read_record", side_effect=files.RestoreNeeded()):
            with self.assertRaises(store.StoreUnavailable) as caught:
                self.memory.record(deadline=time.monotonic() + 1)
        self.assertEqual(caught.exception.code, "store-damaged")
        self.assertEqual(self.snapshot(), before)
        path.write_bytes(base.json_bytes(self.header, "TBL-001"))
        path = self.root / "configuration.json"
        path.write_bytes(b"{")
        path.with_name("configuration.json.bak").write_bytes(b"{}\n")
        before = self.snapshot()
        with mock.patch.object(store.reading, "read_record", side_effect=files.RestoreNeeded()):
            with self.assertRaises(configuration.ConfigurationInvalid):
                self.memory.configuration(deadline=time.monotonic() + 1)
        self.assertEqual(self.snapshot(), before)

    def test_tc011_store_and_configuration_sharing_retries_use_the_caller_deadline(self):
        for name in ("store.json", "configuration.json"):
            path = self.root / name
            if name == "configuration.json":
                path.write_bytes(b"{}\n")
            before = self.snapshot()
            original = Path.read_bytes
            def read(target):
                if target == path:
                    raise PermissionError("made-up sharing failure")
                return original(target)
            deadline = time.monotonic() + 0.05
            started = time.perf_counter()
            with mock.patch.object(files, "_WINDOWS", True), \
                    mock.patch.object(Path, "read_bytes", read):
                with self.assertRaises(PermissionError):
                    self.memory.configuration(deadline=deadline)
            self.assertLess(time.perf_counter() - started, 0.3)
            self.assertEqual(self.snapshot(), before)

    def test_tc012_missing_configuration_has_no_consent_or_writes(self):
        before = self.snapshot()
        for _ in range(2):
            result = self.memory.configuration(deadline=time.monotonic() + 1)
            self.assertFalse(result.consented())
            self.assertFalse(result.enabled("sample"))
            self.assertEqual(result.document, {})
            self.assertEqual(result.values["projects"], {})
        self.assertEqual(self.snapshot(), before)
        absent = store.MemoryStore(self.folder / "absent")
        with self.assertRaises(store.StoreUnavailable) as caught:
            absent.configuration(deadline=time.monotonic() + 1)
        self.assertEqual(caught.exception.code, "no-store")
        self.assertFalse(absent.folder.exists())

    def test_tc009_store_lock_blocks_configuration_write(self):
        # A second lease in this process is an order error, so a foreign, fresh
        # record models contention without weakening the process-wide registry.
        path = self.root / "store.lock"
        path.write_text(json.dumps({"pid": 1, "device": self.header["device"], "at": AT,
                                   "token": "0" * 32}), encoding="utf-8")
        before = self.snapshot()
        with self.assertRaises(locks.LockBusy):
            self.memory.write_configuration({}, time.monotonic() + 0.02)
        self.assertEqual(self.snapshot(), before)

    def test_tc009_lost_lease_and_changed_device_fence_the_primary_move(self):
        for change in ("token", "device"):
            with self.subTest(change=change):
                path = self.root / "configuration.json"
                path.write_bytes(b"{}\n")
                original = files._temporary
                def changed(*args, **kwargs):
                    temporary = original(*args, **kwargs)
                    if change == "token":
                        lock_path = self.root / "store.lock"
                        record = json.loads(lock_path.read_text(encoding="utf-8"))
                        record["token"] = "f" * 32
                        lock_path.write_text(json.dumps(record), encoding="utf-8")
                    else:
                        record = dict(self.header, device=base.new_id("d"))
                        (self.root / "store.json").write_bytes(base.json_bytes(record, "TBL-001"))
                    return temporary
                with mock.patch.object(files, "_temporary", changed):
                    with self.assertRaises(locks.LostLock):
                        self.memory.write_configuration({"temporary": True}, time.monotonic() + 2)
                self.assertEqual(path.read_bytes(), b"{}\n")
                self.assertFalse(list(self.root.glob("*.tmp")))
                (self.root / "store.lock").unlink(missing_ok=True)
                (self.root / "store.json").write_bytes(base.json_bytes(self.header, "TBL-001"))

    def test_tc009_move_retries_recheck_the_lease_after_a_sharing_failure(self):
        path = self.root / "configuration.json"
        path.write_bytes(b"{}\n")
        retry, replace = files._retry, files.os.replace
        calls = []
        def sharing(source, target):
            if Path(target) == path:
                calls.append(True)
                lock_path = self.root / "store.lock"
                record = json.loads(lock_path.read_text(encoding="utf-8"))
                record["token"] = "f" * 32
                lock_path.write_text(json.dumps(record), encoding="utf-8")
                raise PermissionError("made-up sharing failure")
            return replace(source, target)
        def retry_once(operation, deadline=None):
            # Exercise Windows' second attempt on every OS, keeping the path
            # implementation native and the production guard inside the retry.
            try:
                return operation()
            except PermissionError:
                return retry(operation)
        with mock.patch.object(files.os, "replace", sharing), mock.patch.object(files, "_retry", retry_once):
            with self.assertRaises(locks.LostLock):
                self.memory.write_configuration({"temporary": True}, time.monotonic() + 2)
        self.assertEqual(len(calls), 1)
        self.assertEqual(path.read_bytes(), b"{}\n")
        self.assertFalse(list(self.root.glob("*.tmp")))


    def test_tc009_configuration_release_failure_is_logged_after_the_write(self):
        rename = locks.os.rename
        def sharing(source, target):
            if Path(source).name == "store.lock":
                raise PermissionError("made-up store cleanup detail")
            return rename(source, target)
        with mock.patch.object(locks.os, "rename", sharing):
            result = self.memory.write_configuration({"temporary":True}, time.monotonic() + 3)
        self.addCleanup((self.root / "store.lock").unlink)
        self.assertEqual(result.document, {"temporary":True})
        self.assertEqual(files.read_json(self.root / "configuration.json"), {"temporary":True})
        failures = [row for path in (self.root / "logs").glob("failures-*.jsonl")
                    for row in files.read_jsonl(path)]
        self.assertEqual([(row["error"], row["step"]) for row in failures],
                         [("PermissionError", "skill")])


if __name__ == "__main__":
    unittest.main()
