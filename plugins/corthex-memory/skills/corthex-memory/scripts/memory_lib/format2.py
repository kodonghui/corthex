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
_CURATION_ORDER = "logs applies recent failures consolidation stopped rebuilt fence conflict_after".split()


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
    curation._shape(value, "logs applies recent consolidation fence",
                    "failures stopped rebuilt conflict_after")
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
        curation._shape(attempt, "at kind result", "error applied dropped state run")
        curation._choice(attempt["kind"], {"curate", "consolidate", "undo"})
        if "run" in attempt:
            _id(attempt.pop("run"), _RUN)
        if attempt["kind"] == "undo":
            attempt["kind"] = "curate"
    curation.parse(json.dumps(legacy, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    return value


def _bytes(value, table, parser, **options):
    plain = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    validated = parser(plain, **options)
    ordered = base._ordered(validated, table)
    if table == "TBL-009":
        ordered = {key: ordered[key] for key in _CURATION_ORDER if key in ordered}
    return (json.dumps(ordered, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")


def store_bytes(value, allow_migrating=False):
    """Canonical UTF-8/LF bytes for a validated header, with no write."""
    return _bytes(value, "TBL-001", parse_store, allow_migrating=allow_migrating)


def curation_bytes(value):
    """Canonical field order for C2; dynamic revision keys sort by name."""
    return _bytes(value, "TBL-009", parse_curation)
