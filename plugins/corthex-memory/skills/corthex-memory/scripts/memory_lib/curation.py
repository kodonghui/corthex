"""Typed TBL-009 progress. C1 refuses lost progress; reconstruction belongs to C2."""
from datetime import datetime

from . import base, configuration, diagnostics, files, locks, store

ERRORS = set(diagnostics.EXCEPTIONS.values()) | set((
    "refusal max-tokens empty-answer bad-answer bad-vector timeout network stale lost-lock "
    "insufficient_quota invalid_request_error authentication_error billing_error permission_error "
    "not_found_error conflict_error request_too_large rate_limit_error api_error timeout_error overloaded_error").split())


def _shape(value, required, optional=""):
    if not isinstance(value, dict) or not set(required.split()) <= set(value) <= set((required + " " + optional).split()):
        raise ValueError("invalid curation record")


def _count(value, minimum=0):
    if not configuration.integer(value) or value < minimum:
        raise ValueError("invalid curation count")


def _time(value):
    if not isinstance(value, str) or not store.TIME.fullmatch(value):
        raise ValueError("invalid curation time")
    datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")


def _choice(value, choices):
    if not isinstance(value, str) or value not in choices:
        raise ValueError("invalid curation value")


def parse(data):
    value = store.json_document(data)
    _shape(value, "logs applies recent consolidation", "failures stopped rebuilt")
    if not isinstance(value["logs"], dict):
        raise ValueError("invalid curation logs")
    for name, count in value["logs"].items():
        if not diagnostics.LOG.fullmatch(name):
            raise ValueError("invalid curation log")
        _count(count)
    _count(value["applies"])
    if not isinstance(value["recent"], list) or len(value["recent"]) > 10:
        raise ValueError("invalid curation attempts")
    for attempt in value["recent"]:
        _shape(attempt, "at kind result", "error applied dropped state")
        _time(attempt["at"])
        _choice(attempt["kind"], {"curate", "consolidate"})
        _choice(attempt["result"], {"ok", "failed", "stale"})
        for key in ("applied", "dropped"):
            if key in attempt:
                _count(attempt[key])
        if "state" in attempt:
            _choice(attempt["state"], {"new", "kept", "cut"})
        if "error" in attempt:
            _choice(attempt["error"], ERRORS)
    consolidation = value["consolidation"]
    _shape(consolidation, "failures", "last due")
    _count(consolidation["failures"])
    for key in ("last", "due"):
        if key in consolidation:
            _time(consolidation[key])
    if "failures" in value:
        failure = value["failures"]
        _shape(failure, "count log turn")
        _count(failure["count"])
        _count(failure["turn"], 1)
        if not isinstance(failure["log"], str) or not diagnostics.LOG.fullmatch(failure["log"]):
            raise ValueError("invalid curation log")
    if "stopped" in value:
        stop = value["stopped"]
        _shape(stop, "at by errors")
        _time(stop["at"])
        _choice(stop["by"], {"curate", "consolidate"})
        if not isinstance(stop["errors"], list):
            raise ValueError("invalid curation errors")
        for error in stop["errors"]:
            _choice(error, ERRORS)
    if "rebuilt" in value:
        _time(value["rebuilt"])
    return value


def guard(memory, root, deadline):
    for kind, name in (("curation", "curation.lock"), ("layer", "layer.lock")):
        if not any(lease.path == root / name and lease.policy == locks.POLICIES[kind] and
                   lease.device == memory.device for lease in memory.held):
            raise locks.LostLock()
    return lambda: memory.check(deadline, memory.held)


def read(memory, root, deadline):
    check = guard(memory, root, deadline)
    path = root / "curation.json"
    def paths():
        check()
        memory.fence.check(path)
        memory.fence.check(path.with_name(path.name + ".bak"))
        check()
    paths()
    return files.read_record(path, parse, memory.note, holding_lock=True, check=paths,
                             deadline=deadline, reader=lambda p: memory.fence.read(p, deadline))


def write(memory, root, value, deadline):
    parse(base.json_bytes(value, "TBL-009"))
    files.write_json(root / "curation.json", value, "TBL-009", check=guard(memory, root, deadline),
                     path_check=memory.fence.check)
