"""TBL-007 appends and TBL-008 markers; no hook or directory provisioning.

The caller gates consent/project exclusions and gives its diagnostic deadline.
prepare() redacts once and starts the 50ms lock-wait window. Acquired recording
finishes with an 8MiB tail-read bound, even past a hook deadline. A returned
write is never undone because its marker fails. Hook entry points
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
TAIL_BYTES = 8 * 1024 * 1024
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
    """Validate the recording shape used for turn inference."""
    return _parsed_entry(store.json_document(line), host, session)


def _filled(text, ranges):
    """How many U+FFFD characters a text holds inside its merged forgotten ranges."""
    count = reach = 0
    for start, end in sorted((int(pair[0]), int(pair[1])) for pair in ranges):
        if end > reach:
            count += text.count("\ufffd", max(start, reach), end)
            reach = end
    return count


def _parsed_entry(value, host, session):
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
        if (not isinstance(text, str) or
                not _positive(value.get("turn")) or value["turn"] > value["seq"] or
                value.get("speaker") != ("user" if value["kind"] == "prompt" else "agent") or
                value["kind"] == "prompt" and value["turn"] != value["seq"] or
                "event" in value or "reason" in value):
            raise ValueError("invalid raw turn")
        if "cut" in value and not _positive(value["cut"]):
            raise ValueError("invalid raw cut")
        filled = 0
        if "forgotten" in value:
            ranges = value["forgotten"]
            if not isinstance(ranges, list) or any(
                    not isinstance(pair, list) or len(pair) != 2 or
                    not all(configuration.integer(n) for n in pair) or
                    not 0 <= pair[0] < pair[1] <= len(text) for pair in ranges):
                raise ValueError("invalid forgotten range")
            filled = _filled(text, ranges)
        # A forget fills each character of a range with U+FFFD (TBL-007), whose
        # three UTF-8 bytes can outweigh the character that it replaced. Each
        # filled character counts as one byte, so a fill never takes an entry
        # past the limit that its recording kept.
        if len(text.encode("utf-8")) - 2 * filled > redaction.ENTRY_BYTES:
            raise ValueError("invalid raw turn")
    elif set(value) - required - ({"event"} if value["kind"] == "start" else {"reason"}):
        raise ValueError("invalid raw boundary")
    if "event" in value and (not isinstance(value["event"], str) or value["event"] not in EVENTS):
        raise ValueError("invalid start event")
    if "reason" in value and (not isinstance(value["reason"], str) or not REASON.fullmatch(value["reason"])):
        raise ValueError("invalid end reason")
    return value


def _scan_tail(path, host, session):
    """Read at most 8MiB backwards without changing shared files.

    Empty/new logs begin at one. If the whole file was read without a complete
    positive-seq line, skip/count its damage and begin at one as well. A window
    that does not reach the start cannot infer seq without a complete line.
    Parsed cut-tail sequences still stay reserved when a complete line exists.
    """
    incoming = path.open("rb")
    turn, damaged, highest, complete_seq = None, 0, 0, False
    def parsed(line, complete=True):
        nonlocal turn, damaged, highest, complete_seq
        try:
            value = store.json_document(line)
            if isinstance(value, dict) and _positive(value.get("seq")):
                highest = max(highest, int(value["seq"]))
                complete_seq = complete_seq or complete
            if not complete:
                damaged += bool(line)
                return
            value = _parsed_entry(value, host, session)
        except (ValueError, UnicodeError):
            damaged += 1
            return
        if value["kind"] in ("prompt", "answer") and turn is None:
            turn = value
    with incoming:
        position = incoming.seek(0, os.SEEK_END)
        size = position
        floor = max(0, size - TAIL_BYTES)
        fragments, first = [], True
        while position > floor and turn is None:
            start = max(floor, position - BLOCK)
            incoming.seek(start)
            # Split only the new block. Join accumulated fragments once per
            # line instead of copying and rescanning a growing suffix.
            parts = incoming.read(position - start).split(b"\n")
            position = start
            for line in reversed(parts[1:]):
                if fragments:
                    line = b"".join([line] + list(reversed(fragments)))
                    fragments.clear()
                if first:
                    first = False
                    if line:
                        parsed(line, complete=False)
                else:
                    parsed(line)
                    if turn is not None:
                        break
            fragments.append(parts[0])
        if not position and turn is None:
            pending = b"".join(reversed(fragments))
            if first:
                if pending:
                    parsed(pending, complete=False)
            elif pending:
                parsed(pending)
    if size and not complete_seq:
        return None, None if floor else 0, max(1, damaged)
    return turn, highest, damaged


def _tail(path, host, session, check, report):
    """Apply the same bounded read to primary and recovery candidates.

    Reuse the locked reader's recheck and guarded move. A missing primary and
    backup starts a new log; a backup lost after reading must not reset seq.
    """
    seen = False
    def read(candidate):
        nonlocal seen
        value = _scan_tail(candidate, host, session)
        seen = True
        return value
    try:
        turn, highest, damaged = files.read_record(
            path, lambda value: value, report, holding_lock=True, check=check,
            reader=read)
    except FileNotFoundError:
        if seen:
            raise
        return None, 0
    if damaged:
        report("damaged-line", damaged)
    return turn, highest


class RawLog:
    def __init__(self, memory_store, project, host, session):
        folder = base.project_folder_name(project)
        self.store, self.project = memory_store, project
        # The hooks' format-2 binding (c2_store.HookStore, from release 0.3.0) takes the raw lock and checks the
        # log's paths through its path fence, so that a link inside the store is refused, as C2 refuses it.
        self.fenced = getattr(memory_store, "FENCED_RAW", False) is True
        self.host, self.session, self.log = host, session, log_name(host, session)
        root = self.store.folder / "projects" / folder
        self.path = root / "raw" / (self.log + ".jsonl")
        self.markers = root / "unprocessed"
        self.logger = diagnostics.Diagnostics(memory_store)

    def _marker(self, entry, check, prior=None):
        if entry["turn"] != entry["seq"]:
            suffix = "." + self.log + "." + str(entry["turn"])
            if prior is not None and prior["seq"] == prior["turn"] == entry["turn"]:
                at = prior["at"][:19].replace("-", "").replace(":", "") + "Z"
                if (self.markers / (at + suffix)).exists():
                    return
            for name in os.listdir(self.markers):
                if name.endswith(suffix):
                    return
        at = entry["at"][:19].replace("-", "").replace(":", "") + "Z"
        path = self.markers / (at + "." + self.log + "." + str(entry["turn"]))
        def create():
            check()
            try:
                fd = base.private_open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                return
            os.close(fd)
        files._retry(create)

    def append(self, kind, prepared=None, *, deadline=None, diagnostic_deadline,
               stop_hook_active=False, source=None, reason=None, when=None, notices=None):
        """Record under one raw lease; report only safe metadata after release.

        For text, prepare() starts the post-redaction 50ms lock wait. Boundaries
        start their own wait window. An optional absolute deadline only shortens
        waiting; each lock is attempted once even when that window has passed.
        Once the raw lease is acquired, reads, append and marker finish without
        a time limit; ordinary sharing retries remain bounded to one second.
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
        record_path = self.store.folder / "store.json"
        try:
            first = self.logger._stamp(record_path)
            header = self.store.record(report, deadline=deadline, recording=True)
            stamp = self.logger._stamp(record_path)
            if stamp != first:
                header = self.store.record(report, deadline=deadline, recording=True)
                if self.logger._stamp(record_path) != stamp:
                    raise locks.LostLock()
            if self.fenced:
                lock = self.store._lock(self.path.with_suffix(".lock"), "raw", header["device"])
            else:
                lock = locks.Lock(self.path.with_suffix(".lock"), "raw", header["device"])
            lock.acquire(deadline, at_least_once=True)
        except locks.LockBusy:
            report("lock-busy", None)
            flush()
            return Recorded("lock-busy")
        try:
            def check():
                lock.check()
                if self.fenced:
                    self.store._path_check(self.path)
                    self.store._path_check(self.markers)
                if self.logger._stamp(record_path) != stamp:
                    raise locks.LostLock()
                lock.check()
            prior, highest = _tail(self.path, self.host, self.session, check, report)
            if highest is None:
                outcome = "error"
            else:
                seq = highest + 1
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
                files.append_jsonl(self.path, value, "TBL-007", report, check=check)
                entry = value
                if "turn" in entry:
                    self._marker(entry, check, prior)
        except (OSError, RuntimeError, ValueError) as error:
            outcome = "error"
            report(error, None)
        finally:
            lock.release(report=report)
        flush()
        return Recorded(outcome, entry)
