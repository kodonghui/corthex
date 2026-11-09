"""Pure TBL-001/TBL-009 format-2 types, without an availability gate or I/O.

The C1 gate and C1 progress parser stay strict. Migration, leases, recovery,
revision advancement and live activation belong to their separate owners.
"""
import copy
from datetime import datetime
import json
import re

from . import base, configuration, curation, store

_DIGITS = r"[0-9a-hjkmnp-tv-z]{12}"
_RUN = re.compile(r"r_" + _DIGITS + r"\Z")
_CANDIDATE = re.compile(r"c_" + _DIGITS + r"\Z")
_EPOCH = re.compile(r"[0-9a-fA-F]{32}\Z")
_OBJECT = re.compile(r"(?:item:i_|line:s_|pin:i_|candidate:c_|run:r_)" + _DIGITS + r"\Z")
# The curation record's fields in their order (TBL-009), those that it may lack, and those that it always has.
CURATION_FIELDS = tuple("logs applies recent failures consolidation stopped rebuilt fence conflict_after".split())
CURATION_OPTIONAL = ("failures", "stopped", "rebuilt", "conflict_after")
_CURATION_REQUIRED = tuple(name for name in CURATION_FIELDS if name not in CURATION_OPTIONAL)
_ATTEMPT_ORDER = "at kind result error applied dropped reasons state edit_reasons run".split()
# Why a curate attempt dropped an item change (TASK-085) or a line edit (TASK-087), and why a consolidate
# attempt dropped a merge or a line of the last state answer (TASK-089, TASK-090): each counts once, under the
# first check it fails. The record keeps the counts by reason; curator_answers, state_edits and state_rewrite
# use these.
CHANGE_REASONS = ("shape", "limit", "not-in-request", "not-current", "quote", "pasted")
EDIT_REASONS = ("not-in-request", "duplicate", "shape", "limit", "cites", "decision")
MERGE_REASONS = ("shape", "limit", "not-in-request", "not-current", "quote", "speaker")
_REASONS = {("curate", "reasons"): CHANGE_REASONS, ("curate", "edit_reasons"): EDIT_REASONS,
            ("consolidate", "reasons"): MERGE_REASONS, ("consolidate", "edit_reasons"): EDIT_REASONS}


def _document(data):
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError("invalid format-2 record")
    return store.json_document(data)


def _time(value):
    if not isinstance(value, str) or not store.TIME.fullmatch(value):
        raise ValueError("invalid format-2 time")
    datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")


def _id(value, pattern):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError("invalid format-2 ID")


def _reasons(attempt, key, counts):
    """An attempt's drops by reason: known reasons with positive counts; `reasons` sum to `dropped`.

    A curate attempt counts item changes and line edits, a consolidate attempt
    merges and the last state answer's lines; an undo keeps neither.
    """
    reasons = _REASONS.get((attempt["kind"], key))
    if (reasons is None or not isinstance(counts, dict) or not counts or
            any(reason not in reasons or type(count) is not int or count < 1 for reason, count in counts.items())
            or key == "reasons" and sum(counts.values()) != attempt.get("dropped")):
        raise ValueError("invalid format-2 attempt reasons")


def parse_store(data, allow_migrating=False):
    """Decode a format-2 header; maintenance may opt into a 1-to-2 marker.

    This never upgrades the format-1 operational gate or interprets a newer
    format. The returned document retains its original fields and values.
    """
    value = _document(data)
    curation._shape(value, "format device made release", "migrating")
    if not configuration.integer(value["format"]) or value["format"] != 2:
        raise ValueError("invalid format-2 header")
    _id(value["device"], store.DEVICE)
    _time(value["made"])
    if not isinstance(value["release"], str) or not value["release"]:
        raise ValueError("invalid format-2 release")
    value["release"].encode("utf-8")
    if "migrating" in value:
        if allow_migrating is not True:
            raise ValueError("migration requires maintenance reader")
        migration = value["migrating"]
        curation._shape(migration, "from to started")
        for key, expected in (("from", 1), ("to", 2)):
            if not configuration.integer(migration[key]) or migration[key] != expected:
                raise ValueError("invalid format-2 migration")
        _time(migration["started"])
    return value


def _fence(value):
    curation._shape(value, "epoch generation revisions")
    _id(value["epoch"], _EPOCH)
    _revision(value["generation"])
    if not isinstance(value["revisions"], dict):
        raise ValueError("invalid format-2 revisions")
    for key, revision in value["revisions"].items():
        _id(key, _OBJECT)
        _revision(revision)
        if revision > value["generation"]:
            raise ValueError("revision exceeds generation")


def _revision(value):
    # Code-owned identity proofs cannot pass through floating-point rounding.
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("invalid format-2 revision")


def parse_curation(data):
    """Decode C2 progress and its required fence, without filling defaults.

    Existing objects with no revision remain unknown. The pure reader neither
    invents a zero revision nor rotates a recovery epoch.
    """
    value = _document(data)
    curation._shape(value, " ".join(_CURATION_REQUIRED), " ".join(CURATION_OPTIONAL))
    _fence(value["fence"])
    if "conflict_after" in value:
        _id(value["conflict_after"], _CANDIDATE)
    if not isinstance(value["recent"], list):
        raise ValueError("invalid format-2 attempts")
    # Validate the unchanged C1 fields through their existing single parser.
    # Work on a detached value; no global C1 field registry is extended.
    legacy = copy.deepcopy(value)
    legacy.pop("fence")
    legacy.pop("conflict_after", None)
    for attempt in legacy["recent"]:
        curation._shape(attempt, "at kind result", "error applied dropped state run reasons edit_reasons")
        curation._choice(attempt["kind"], {"curate", "consolidate", "undo"})
        if "run" in attempt:
            _id(attempt.pop("run"), _RUN)
        for key in ("reasons", "edit_reasons"):
            if key in attempt:
                _reasons(attempt, key, attempt.pop(key))
        if attempt["kind"] == "undo":
            attempt["kind"] = "curate"
    curation.parse(json.dumps(legacy, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    return value


def _bytes(value, table, parser, **options):
    plain = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    validated = parser(plain, **options)
    ordered = base._ordered(validated, table)
    if table == "TBL-009":
        ordered = {key: ordered[key] for key in CURATION_FIELDS if key in ordered}
        ordered["recent"] = [{key: attempt[key] for key in _ATTEMPT_ORDER if key in attempt}
                             for attempt in ordered["recent"]]
    return (json.dumps(ordered, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")


def store_bytes(value, allow_migrating=False):
    """Canonical UTF-8/LF bytes for a validated header, with no write."""
    return _bytes(value, "TBL-001", parse_store, allow_migrating=allow_migrating)


def curation_bytes(value):
    """Canonical field order for C2; dynamic revision keys sort by name."""
    return _bytes(value, "TBL-009", parse_curation)
