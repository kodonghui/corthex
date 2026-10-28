"""TBL-007 appends and TBL-008 markers; no hook or directory provisioning.

The caller gates consent/project exclusions and gives its diagnostic deadline.
prepare() redacts once and starts the separate 50ms recording budget. A returned
write is never undone because its marker is late or fails. Hook entry points
later use Recorded.outcome for their timing line and always exit quietly.
"""

import hashlib
import math
import os
import re
from dataclasses import dataclass

from . import base, configuration, diagnostics, files, locks, redaction, store
from . import clock

RECORD_SECONDS = 0.05
BLOCK = 64 * 1024
HOSTS = {"claude-code", "codex"}
KINDS = {"prompt", "answer", "start", "end"}
EVENTS = {"start", "resume", "clear", "compact", "fork"}
REASON = re.compile(r"[a-z0-9_-]{1,64}\Z")
ENTRY_ID = re.compile(r"e_[0-9a-hjkmnp-tv-z]{12}\Z")


@dataclass(frozen=True)
class Prepared:
    text: str
    cut: object
    deadline: float


@dataclass(frozen=True)
class Recorded:
    outcome: str
    entry: object = None


class RecordingDeadline(RuntimeError):
    pass


def prepare(text, environment=None):
    """Redact once; callers can reuse the returned text for later recall."""
    value = redaction.redact(text, environment)
    return Prepared(value.text, value.cut, clock.now() + RECORD_SECONDS)


def log_name(host, session):
    if not isinstance(host, str) or host not in HOSTS:
        raise ValueError("invalid recording host")
    if not isinstance(session, str) or not 1 <= len(session) <= 200:
        raise ValueError("invalid recording session")
    return host + "-" + hashlib.sha256(session.encode("utf-8")).hexdigest()[:16]


def _deadline(value):
    if not configuration.number(value) or not math.isfinite(value):
        raise ValueError("a finite recording deadline is required")


def _positive(value):
    return configuration.integer(value) and value >= 1


def _entry(line, host, session):
    """Validate complete stored entries, including rows rewritten by a forget."""
    value = store.json_document(line)
    required = {"id", "seq", "at", "host", "session", "kind"}
    if not isinstance(value, dict) or not required <= set(value) <= set(base.FIELDS["TBL-007"].split()):
        raise ValueError("invalid raw entry")
    if (not isinstance(value["id"], str) or not ENTRY_ID.fullmatch(value["id"]) or
            not _positive(value["seq"]) or value["host"] != host or value["session"] != session or
            not isinstance(value["at"], str) or not store.TIME.fullmatch(value["at"]) or
            not isinstance(value["kind"], str) or value["kind"] not in KINDS):
        raise ValueError("invalid raw entry")
    if value["kind"] in ("prompt", "answer"):
        text = value.get("text")
        if (not isinstance(text, str) or len(text.encode("utf-8")) > redaction.ENTRY_BYTES or
                not _positive(value.get("turn")) or value["turn"] > value["seq"] or
                value.get("speaker") != ("user" if value["kind"] == "prompt" else "agent") or
                value["kind"] == "prompt" and value["turn"] != value["seq"] or
                "event" in value or "reason" in value):
            raise ValueError("invalid raw turn")
        if "cut" in value and not _positive(value["cut"]):
            raise ValueError("invalid raw cut")
        if "forgotten" in value:
            ranges = value["forgotten"]
            if not isinstance(ranges, list) or any(
                    not isinstance(pair, list) or len(pair) != 2 or
                    not all(configuration.integer(n) for n in pair) or
                    not 0 <= pair[0] < pair[1] <= len(text) for pair in ranges):
                raise ValueError("invalid forgotten range")
    elif set(value) - required - ({"event"} if value["kind"] == "start" else {"reason"}):
        raise ValueError("invalid raw boundary")
    if "event" in value and (not isinstance(value["event"], str) or value["event"] not in EVENTS):
        raise ValueError("invalid start event")
    if "reason" in value and (not isinstance(value["reason"], str) or not REASON.fullmatch(value["reason"])):
        raise ValueError("invalid end reason")
    return value


def _tail(path, host, session, check, deadline, report):
    """Read backwards in blocks; ignore cut tails and stop after the turn head."""
    check()
    try:
        incoming = files._retry(lambda: path.open("rb"), deadline)
    except FileNotFoundError:
        if not path.with_name(path.name + ".bak").exists():
            return None, None
        # Recovery is rare; the existing strict JSONL reader validates the
        # backup. Healthy appends never read/parse the whole raw log.
        files.read_jsonl(path, report, holding_lock=True, check=check, deadline=deadline)
        return _tail(path, host, session, check, deadline, report)
    last, turn, damaged = None, None, 0
    def parsed(line):
        nonlocal last, turn, damaged
        check()
        try:
            value = _entry(line, host, session)
        except (ValueError, UnicodeError):
            damaged += 1
            return
        if last is None:
            last = value
        if value["kind"] in ("prompt", "answer") and turn is None:
            turn = value
    with incoming:
        position = incoming.seek(0, os.SEEK_END)
        pending, first = b"", True
        while position and turn is None:
            check()
            start = max(0, position - BLOCK)
            incoming.seek(start)
            parts = (incoming.read(position - start) + pending).split(b"\n")
            pending, position = parts[0], start
            for line in reversed(parts[1:]):
                if first:
                    first = False
                    damaged += bool(line)
                else:
                    parsed(line)
                    if turn is not None:
                        break
        if not position and turn is None:
            if first:
                damaged += bool(pending)
            elif pending:
                parsed(pending)
    if damaged:
        report("damaged-line", damaged)
    return last, turn


class RawLog:
    def __init__(self, memory_store, project, host, session):
        folder = base.project_folder_name(project)
        self.store, self.project = memory_store, project
        self.host, self.session, self.log = host, session, log_name(host, session)
        root = self.store.folder / "projects" / folder
        self.path = root / "raw" / (self.log + ".jsonl")
        self.markers = root / "unprocessed"
        self.logger = diagnostics.Diagnostics(memory_store)

    def _marker(self, entry, check, deadline):
        pattern = re.compile(r"[0-9]{8}T[0-9]{6}Z\." + re.escape(self.log) + r"\." + str(entry["turn"]) + r"\Z")
        check()
        for path in self.markers.iterdir():
            # Listing is read-only: check the clock without reopening the
            # lease/header for every pending turn. Mutation still uses check.
            if clock.now() >= deadline:
                raise RecordingDeadline()
            if pattern.fullmatch(path.name):
                check()
                return
        at = entry["at"][:19].replace("-", "").replace(":", "") + "Z"
        path = self.markers / (at + "." + self.log + "." + str(entry["turn"]))
        def create():
            check()
            fd = base.private_open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
        files._retry(create, deadline)

    def append(self, kind, prepared=None, *, deadline=None, diagnostic_deadline,
               stop_hook_active=False, source=None, reason=None, when=None, notices=None):
        """Record under one raw lease; report only safe metadata after release.

        For text, pass prepare()'s result, retaining its post-redaction deadline.
        Boundaries use their own 50ms budget. A supplied absolute deadline can
        only shorten either budget, retaining a caller's earlier hook deadline.
        The diagnostic deadline belongs to the whole hook, never a new retry.
        A supplied notice list defers logging to the caller after release; it
        retains FileNotFoundError's kind for the hook's missing-folder policy.
        """
        if not isinstance(kind, str) or kind not in KINDS:
            raise ValueError("invalid recording kind")
        _deadline(diagnostic_deadline)
        caller_deadline = deadline
        if caller_deadline is not None:
            _deadline(caller_deadline)
        if kind in ("prompt", "answer"):
            if kind == "answer" and prepared is None:
                return Recorded("no-answer")
            if not isinstance(prepared, Prepared) or not isinstance(prepared.text, str):
                raise ValueError("prepared text is required")
            if len(prepared.text.encode("utf-8")) > redaction.ENTRY_BYTES or prepared.cut is not None and not _positive(prepared.cut):
                raise ValueError("invalid prepared text")
            deadline = prepared.deadline
            if not prepared.text or kind == "prompt" and not prepared.text.strip():
                return Recorded("no-answer" if kind == "answer" else "ok")
        elif prepared is not None:
            raise ValueError("a boundary has no text")
        else:
            deadline = clock.now() + RECORD_SECONDS
        if caller_deadline is not None:
            deadline = min(deadline, caller_deadline)
        _deadline(deadline)
        at = base.utc_time(when)
        pending, entry, outcome = [] if notices is None else notices, None, "ok"
        def report(error, count):
            pending.append((error, count))
        def flush():
            if notices is not None:
                return
            hook = {"answer": "end-of-turn"}.get(kind, kind)
            for error, count in pending:
                self.logger.failure(error, "record", diagnostic_deadline, hook=hook,
                                    host=self.host, project=self.project, log=self.log, count=count)
        if clock.now() >= deadline:
            report("lock-busy", None)
            flush()
            return Recorded("lock-busy")
        record_path = self.store.folder / "store.json"
        first = self.logger._stamp(record_path)
        header = self.store.record(report, deadline=deadline)
        stamp = self.logger._stamp(record_path)
        if stamp != first:
            header = self.store.record(report, deadline=deadline)
            if self.logger._stamp(record_path) != stamp:
                raise locks.LostLock()
        lock = locks.Lock(self.path.with_suffix(".lock"), "raw", header["device"])
        try:
            lock.acquire(deadline)
        except locks.LockBusy:
            report("lock-busy", None)
            flush()
            return Recorded("lock-busy")
        try:
            def check():
                if clock.now() >= deadline:
                    raise RecordingDeadline()
                lock.check()
                if self.logger._stamp(record_path) != stamp:
                    raise locks.LostLock()
            last, prior = _tail(self.path, self.host, self.session, check, deadline, report)
            seq = int(last["seq"]) + 1 if last is not None else 1
            value = {"id": base.new_id("e"), "seq": seq, "at": at,
                     "host": self.host, "session": self.session, "kind": kind}
            if kind in ("prompt", "answer"):
                turn = seq
                if kind == "answer" and prior is not None and (prior["kind"] == "prompt" or stop_hook_active is True):
                    turn = int(prior["turn"])
                value.update(turn=turn, speaker="user" if kind == "prompt" else "agent", text=prepared.text)
                if prepared.cut is not None:
                    value["cut"] = int(prepared.cut)
            elif kind == "start":
                event = "start" if source == "startup" else source
                if isinstance(event, str) and event in EVENTS:
                    value["event"] = event
            elif isinstance(reason, str) and REASON.fullmatch(reason):
                value["reason"] = reason
            files.append_jsonl(self.path, value, "TBL-007", report, check=check, deadline=deadline)
            entry = value
            check()
            if "turn" in entry:
                self._marker(entry, check, deadline)
        except RecordingDeadline:
            outcome = "deadline"
            report("deadline", None)
        except (OSError, RuntimeError, ValueError) as error:
            outcome = "deadline" if isinstance(error, OSError) and clock.now() >= deadline else "error"
            report(error if notices is not None and isinstance(error,FileNotFoundError)
                   else "deadline" if outcome == "deadline" else error, None)
        finally:
            lock.release(report=report)
        flush()
        return Recorded(outcome, entry)
