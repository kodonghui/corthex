"""Best-effort, metadata-only daily logs. Never stringify an exception.

Callers gate memory work on consent and the enabled project, and pass the hook's
start time for timings. This module neither creates the store nor provisions its
logs directory. A blocked store produces no diagnostic write (TBL-001).
"""

import builtins
import hashlib
import math
import os
import re
from contextlib import contextmanager

from . import base, configuration, files, locks, projects, store
from . import clock

HOOKS = {"start", "prompt", "end-of-turn", "end"}
HOSTS = {"claude-code", "codex"}
STEPS = {"record", "recall", "summary", "trigger", "curate", "consolidate", "embed",
         "sync", "retention", "index", "restore", "skill"}
OUTCOMES = {"ok", "left-out", "no-answer", "lock-busy", "deadline", "error"}
CODES = {"bad-input", "unknown-host", "no-project-list", "project-clash", "lock-busy",
         "deadline", "damaged-line", "future-entry", "restored", "redaction", "worker-start",
         "configuration-invalid"}
EXCEPTIONS = {value: name for name, value in vars(builtins).items()
              if isinstance(value, type) and issubclass(value, Exception) and value.__name__ == name}
PROJECT = re.compile(r"[a-z0-9][a-z0-9-]{0,59}\Z")
LOG = re.compile(r"(?:claude-code|codex)-[0-9a-f]{16}\Z")


def error_kind(error):
    if isinstance(error, str):
        if error == "lost-lock":
            return error
        if error in ("LockBusy", "LostLock"):
            return {"LockBusy": "lock-busy", "LostLock": "lost-lock"}[error]
        return error if error in CODES or error in EXCEPTIONS.values() else None
    if isinstance(error, configuration.ConfigurationInvalid):
        return "configuration-invalid"
    if isinstance(error, locks.LockBusy):
        return "lock-busy"
    if isinstance(error, locks.LostLock):
        return "lost-lock"

    if isinstance(error, projects.ProjectError):
        return error.code if choice(error.code, CODES) else None
    if isinstance(error, store.StoreUnavailable):
        # Store gate codes are returned by commands, never failure-log entries.
        return None
    if isinstance(error, Exception):
        # A custom class name can itself contain private text. Use its nearest
        # built-in base class, never its name, args, filename, or provider text.
        return next((EXCEPTIONS[cls] for cls in type(error).__mro__ if cls in EXCEPTIONS), None)
    return None


def choice(value, allowed):
    return isinstance(value, str) and value in allowed


@contextmanager
def _log_lease(lock, deadline, opportunistic, report):
    if opportunistic:
        # A hook may cross its deadline during the header read or this create.
        # Try once before any optional waiting, never reclaiming a late lock.
        try:
            lock.try_once()
        except locks.LockBusy:
            if clock.now() >= deadline:
                raise
            lock.acquire(deadline)
    else:
        lock.acquire(deadline)
    try:
        yield
    finally:
        lock.release(report=report)


class Diagnostics:
    def __init__(self, memory_store):
        self.store = memory_store
        self._ready = None

    @staticmethod
    def _stamp(path, deadline=None):
        # Same-size in-place writes can retain all four stat fields. Bind the
        # snapshot to the header bytes too, using the same open file's identity.
        # This never parses/restores a record or acquires another lock.
        def read():
            with path.open("rb") as source:
                info = os.fstat(source.fileno())
                digest = hashlib.sha256()
                for chunk in iter(lambda: source.read(8192), b""):
                    digest.update(chunk)
            return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, digest.digest()
        try:
            return files._retry(read, deadline)
        except FileNotFoundError:
            return None

    def read_gate(self, deadline, report=None):
        """Cache a stable, readable header for a later one-attempt deadline log."""
        self._ready = None
        path = self.store.folder / "store.json"
        first = self._stamp(path, deadline)
        header = self.store.record(report, deadline=deadline)
        stamp = self._stamp(path, deadline)
        if first != stamp:
            header = self.store.record(report, deadline=deadline)
            if self._stamp(path, deadline) != stamp:
                raise locks.LostLock()
        self._ready = header["device"], stamp
        return header

    def _late_append(self, name, table, record, deadline):
        # No new budget: recovery/opening get the expired retry deadline.
        if self._ready is None:
            return False
        device, stamp = self._ready
        header = self.store.folder / "store.json"
        folder = self.store.folder / "logs"
        path = folder / (name + "-" + record["at"][:10] + ".jsonl")
        if self._stamp(header, deadline) != stamp:
            return False
        lock = locks.Lock(folder / (name + ".lock"), "log", device)
        lock.try_once()
        try:
            def guard():
                lock.check()
                if self._stamp(header, deadline) != stamp:
                    raise locks.LostLock()
                lock.check()
            guard()
            files.append_jsonl(path, record, table, check=guard, deadline=deadline)
            return True
        finally:
            lock.release()

    def _append(self, name, table, record, deadline, opportunistic=False):
        try:
            if not configuration.number(deadline) or not math.isfinite(deadline):
                return False
            if clock.now() >= deadline:
                return self._late_append(name, table, record, deadline) if opportunistic else False
            record_path = self.store.folder / "store.json"
            before = self.read_gate(deadline)
            stamp = self._ready[1]
            folder = self.store.folder / "logs"
            lock = locks.Lock(folder / (name + ".lock"), "log", before["device"])
            def report_release(error, count):
                self.failure(error, "record", deadline, hook=record.get("hook"),
                             host=record.get("host"), opportunistic=opportunistic)
            with _log_lease(lock, deadline, opportunistic,
                            report_release if name != "failures" else None):
                def guard():
                    if not opportunistic and clock.now() >= deadline:
                        raise locks.LockBusy()
                    lock.check()
                    # Fingerprint only: never parse/restore the header or take
                    # its earlier store lock while holding a log lease.
                    if self._stamp(record_path, deadline) != stamp:
                        raise locks.LostLock()
                    lock.check()
                    if not opportunistic and clock.now() >= deadline:
                        raise locks.LockBusy()
                guard()
                path = folder / (name + "-" + record["at"][:10] + ".jsonl")
                files.append_jsonl(path, record, table, check=guard, deadline=deadline)
            return True
        except (OSError, RuntimeError, ValueError, TypeError, OverflowError):
            # The caller's hook stays quiet and continues even if logging fails.
            return False

    def failure(self, error, step, deadline, hook=None, host=None, project=None,
                log=None, count=None, when=None, opportunistic=False):
        kind = error_kind(error)
        if not kind or not choice(step, STEPS):
            return False
        if hook is not None and not choice(hook, HOOKS) or host is not None and not choice(host, HOSTS):
            return False
        if project is not None and (not isinstance(project, str) or not PROJECT.fullmatch(project)):
            return False
        if log is not None and (not isinstance(log, str) or not LOG.fullmatch(log)):
            return False
        if count is not None and (not configuration.integer(count) or count < 1):
            return False
        try:
            record = {"at": base.utc_time(when), "step": step, "error": kind}
        except (ValueError, TypeError, AttributeError, OverflowError):
            return False
        record.update({key: value for key, value in (("hook", hook), ("host", host),
                      ("project", project), ("log", log), ("count", int(count) if count is not None else None))
                       if value is not None})
        return self._append("failures", "TBL-004", record, deadline, opportunistic)

    def timing(self, hook, host, ms, outcome, deadline, when=None, opportunistic=False):
        if not choice(hook, HOOKS) or not choice(host, HOSTS) or not choice(outcome, OUTCOMES):
            return False
        if not configuration.integer(ms) or ms < 0:
            return False
        try:
            record = {"at": base.utc_time(when), "hook": hook, "host": host,
                      "ms": int(ms), "outcome": outcome}
        except (ValueError, TypeError, AttributeError, OverflowError):
            return False
        return self._append("hooks", "TBL-005", record, deadline, opportunistic)
