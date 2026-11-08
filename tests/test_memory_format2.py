"""TASK-073: pure TC-116/TC-390 type evidence, never live migration."""
import copy
import json
import sys
from pathlib import Path
import unittest
from unittest import mock

from _common import ROOT

SCRIPTS = ROOT / "plugins/corthex-memory/skills/corthex-memory/scripts"
sys.path.insert(0, str(SCRIPTS))
from memory_lib import base, curation, format2, store

AT = "2026-11-04T13:00:00.000Z"
HEADER = {"format": 2, "device": "d_0123456789ab", "made": AT, "release": "0.3.0"}
PROGRESS = {"logs": {"codex-0123456789abcdef": 8}, "applies": 2, "recent": [],
            "consolidation": {"failures": 0},
            "fence": {"epoch": "0123456789abcdef" * 2, "generation": 8,
                      "revisions": {"item:i_0123456789ab": 3, "run:r_0123456789ab": 8}}}


def data(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


class Format2Test(unittest.TestCase):
    def test_tc116_header_fields_are_strict_and_times_are_real_dates(self):
        for key, bad in (("format", 1), ("format", 3), ("format", True),
                         ("format", 2.5), ("device", "i_0123456789ab"),
                         ("device", "d_0123456789aI"), ("release", ""),
                         ("release", None), ("made", "2026-02-30T00:00:00.000Z"),
                         ("made", "2026-11-04T00:00:00Z"), ("unknown", 0)):
            value = copy.deepcopy(HEADER)
            value[key] = bad
            with self.subTest(key=key, bad=bad), self.assertRaises(ValueError):
                format2.parse_store(data(value))

    def test_tc116_headers_and_progress_round_trip_without_mutating_input(self):
        for value, encode, parse in ((HEADER, format2.store_bytes, format2.parse_store),
                                      (PROGRESS, format2.curation_bytes, format2.parse_curation)):
            original = copy.deepcopy(value)
            first = encode(value)
            self.assertEqual(parse(first), original)
            self.assertEqual(first, encode(dict(reversed(list(value.items())))))
            self.assertEqual(value, original)
            self.assertTrue(first.endswith(b"\n"))

    def test_tc116_revision_namespace_types_and_generation_are_strict(self):
        for field, bad in (("epoch", "g" * 32), ("epoch", "0" * 31),
                           ("generation", True), ("generation", 1.0), ("generation", -1),
                           ("revisions", []), ("unknown", 0)):
            value = copy.deepcopy(PROGRESS)
            value["fence"][field] = bad
            with self.subTest(field=field, bad=bad), self.assertRaises(ValueError):
                format2.parse_curation(data(value))
        for key, revision in (("item:s_0123456789ab", 1), ("pin:p_0123456789ab", 1),
                              ("run:r_0123456789aI", 1), ("line:s_0123456789ab\n", 1),
                              ("item:i_0123456789ab", True), ("item:i_0123456789ab", 1.0),
                              ("item:i_0123456789ab", 9),
                              ("candidate:c_0123456789ab", -1)):
            value = copy.deepcopy(PROGRESS)
            value["fence"]["revisions"] = {key: revision}
            with self.subTest(key=key, revision=revision), self.assertRaises(ValueError):
                format2.parse_curation(data(value))

    def test_tc116_absent_revisions_are_unknown_and_never_default_to_zero(self):
        value = copy.deepcopy(PROGRESS)
        value["fence"]["revisions"] = {}
        self.assertEqual(format2.parse_curation(data(value))["fence"]["revisions"], {})
        value.pop("fence")
        with self.assertRaises(ValueError):
            format2.parse_curation(data(value))

    def test_tc116_every_documented_object_namespace_round_trips(self):
        value = copy.deepcopy(PROGRESS)
        value["fence"]["revisions"] = {
            "candidate:c_0123456789ab": 1, "run:r_0123456789ab": 8,
            "line:s_0123456789ab": 3, "pin:i_0123456789ab": 4,
            "item:i_0123456789ab": 0,
        }
        encoded = format2.curation_bytes(value)
        self.assertEqual(format2.parse_curation(encoded), value)
        self.assertEqual(list(json.loads(encoded)["fence"]["revisions"]),
                         sorted(value["fence"]["revisions"]))

    def test_tc116_undo_attempts_and_candidate_cursor_preserve_c2_fields(self):
        value = copy.deepcopy(PROGRESS)
        value["recent"] = [{"at": AT, "kind": "undo", "result": "ok", "run": "r_0123456789ab"}]
        value["conflict_after"] = "c_0123456789ab"
        self.assertEqual(format2.parse_curation(format2.curation_bytes(value)), value)
        for key in ("run", "extra"):
            invalid = copy.deepcopy(value)
            invalid["recent"][0][key] = "c_0123456789ab"
            with self.subTest(key=key), self.assertRaises(ValueError):
                format2.parse_curation(data(invalid))

    def test_tc116_curate_attempts_keep_their_drops_by_reason(self):
        value = copy.deepcopy(PROGRESS)
        attempt = {"at": AT, "kind": "curate", "result": "ok", "applied": 1, "dropped": 3, "state": "kept",
                   "run": "r_0123456789ab", "edit_reasons": {"cites": 1, "not-in-request": 2},
                   "reasons": {"quote": 2, "pasted": 1}}
        value["recent"] = [attempt, {"at": AT, "kind": "curate", "result": "ok", "applied": 0, "dropped": 2}]
        encoded = format2.curation_bytes(value)
        self.assertEqual(format2.parse_curation(encoded), value)
        self.assertEqual(list(json.loads(encoded)["recent"][0]),
                         ["at", "kind", "result", "applied", "dropped", "reasons", "state", "edit_reasons", "run"])
        for key, bad in (("reasons", {"quote": 2}), ("reasons", {"quote": 2, "pasted": 1, "shape": 0}),
                         ("reasons", {"speaker": 3}), ("reasons", {"quote": 2.0, "pasted": 1}),
                         ("reasons", {"quote": True, "pasted": 2}), ("reasons", {}),
                         ("reasons", [["quote", 3]]), ("edit_reasons", {"quote": 1}),
                         ("edit_reasons", {"cites": 0}), ("edit_reasons", {})):
            invalid = copy.deepcopy(value)
            invalid["recent"][0][key] = bad
            with self.subTest(key=key, bad=bad), self.assertRaises(ValueError):
                format2.parse_curation(data(invalid))
        untotalled = copy.deepcopy(value)
        del untotalled["recent"][0]["dropped"]
        with self.assertRaises(ValueError):
            format2.parse_curation(data(untotalled))
        for kind in ("consolidate", "undo"):
            other = copy.deepcopy(PROGRESS)
            other["recent"] = [{"at": AT, "kind": kind, "result": "ok", "applied": 1, "dropped": 1}]
            self.assertEqual(format2.parse_curation(data(other)), other)
            for key, counts in (("reasons", {"quote": 1}), ("edit_reasons", {"cites": 1})):
                other["recent"][0][key] = counts
                with self.subTest(kind=kind, key=key), self.assertRaises(ValueError):
                    format2.parse_curation(data(other))
                del other["recent"][0][key]

    def test_tc116_duplicate_fields_nonfinite_and_wrong_json_types_fail(self):
        self.assertEqual(format2.parse_store(data(HEADER)), HEADER)
        self.assertEqual(format2.parse_curation(data(PROGRESS)), PROGRESS)
        duplicates = ((format2.parse_store, data(HEADER)[:-1] + b', "format": 2}'),
                      (format2.parse_curation, data(PROGRESS)[:-1] + b', "applies": 2}'),
                      (format2.parse_curation, data(PROGRESS).replace(
                          b'"generation": 8', b'"generation": 8, "generation": 8', 1)))
        for parser, bad in duplicates:
            with self.subTest(parser=parser.__name__, bad=bad), self.assertRaises(ValueError):
                parser(bad)
        for bad in (b'[]', b'null', b'{"x":NaN}', b'{"x":Infinity}', b'\xff'):
            for parser in (format2.parse_store, format2.parse_curation):
                with self.subTest(bad=bad, parser=parser.__name__), self.assertRaises(ValueError):
                    parser(bad)

    def test_tc116_existing_progress_validation_is_not_bypassed(self):
        at_limit = copy.deepcopy(PROGRESS)
        at_limit["recent"] = [{"at": AT, "kind": "curate", "result": "ok"} for _ in range(10)]
        self.assertEqual(format2.parse_curation(data(at_limit)), at_limit)
        for field, bad in (("logs", {"wrong-log": 1}), ("applies", True),
                           ("consolidation", {"failures": -1}),
                           ("recent", [{"at": AT, "kind": "curate", "result": "ok"} for _ in range(11)]),
                           ("rebuilt", "2026-02-30T00:00:00.000Z"), ("unknown", "x")):
            value = copy.deepcopy(PROGRESS)
            value[field] = bad
            with self.subTest(field=field), self.assertRaises(ValueError):
                format2.parse_curation(data(value))

    def test_tc390_c1_operational_gates_stay_closed_to_c2(self):
        with self.assertRaises(store.StoreUnavailable) as caught:
            store._record(format2.store_bytes(HEADER))
        self.assertEqual(caught.exception.code, "store-newer")
        with self.assertRaises(ValueError):
            curation.parse(format2.curation_bytes(PROGRESS))
        self.assertNotIn("fence", base.FIELDS["TBL-009"].split())

    def test_tc390_migration_marker_requires_explicit_typed_maintenance_read(self):
        value = copy.deepcopy(HEADER)
        value["migrating"] = {"from": 1, "to": 2, "started": AT}
        with self.assertRaises(ValueError):
            format2.parse_store(data(value))
        self.assertEqual(format2.parse_store(format2.store_bytes(value, True), True), value)
        for field, bad in (("from", True), ("from", 2), ("to", 3), ("extra", 0),
                           ("started", "2026-02-30T00:00:00.000Z")):
            invalid = copy.deepcopy(value)
            invalid["migrating"][field] = bad
            with self.subTest(field=field), self.assertRaises(ValueError):
                format2.parse_store(data(invalid), True)

    def test_tc390_readers_do_no_file_or_directory_io(self):
        with mock.patch("builtins.open", side_effect=AssertionError("unexpected I/O")), \
             mock.patch.object(Path, "read_bytes", side_effect=AssertionError("unexpected I/O")), \
             mock.patch.object(Path, "mkdir", side_effect=AssertionError("unexpected I/O")):
            self.assertEqual(format2.parse_store(data(HEADER)), HEADER)
            self.assertEqual(format2.parse_curation(data(PROGRESS)), PROGRESS)


if __name__ == "__main__":
    unittest.main()
