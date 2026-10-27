"""Best-effort, metadata-only daily logs. Never stringify an exception.

Callers gate memory work on consent and the enabled project, and pass the hook's
start time for timings. This module neither creates the store nor provisions its
logs directory. A blocked store produces no diagnostic write (TBL-001).
"""

import builtins
import math
import re
import time

from . import base, configuration, files, locks, projects, store

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


class Diagnostics:
    def __init__(self, memory_store):
        self.store = memory_store

    @staticmethod
    def _stamp(path):
        try:
            info = path.stat()
        except FileNotFoundError:
            return None
        return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns

    def _append(self, name, table, record, deadline):
        try:
            if (not configuration.number(deadline) or not math.isfinite(deadline) or
                    time.monotonic() >= deadline):
                return False
            record_path = self.store.folder / "store.json"
            first = self._stamp(record_path)
            before = self.store.record(deadline=deadline)
            stamp = self._stamp(record_path)
            if first != stamp:
                # Recovery or a concurrent rewrite changed the header. Validate
                # its new identity while no log lease is held.
                before = self.store.record(deadline=deadline)
                if self._stamp(record_path) != stamp:
                    return False
            folder = self.store.folder / "logs"
            lock = locks.Lock(folder / (name + ".lock"), "log", before["device"])
            def report_release(error, count):
                self.failure(error, "record", deadline, hook=record.get("hook"),
                             host=record.get("host"))
            with lock.held(deadline, report=report_release if name != "failures" else None):
                def guard():
                    if time.monotonic() >= deadline:
                        raise locks.LockBusy()
                    lock.check()
                    # Never read or restore the header under a log lease.
                    if self._stamp(record_path) != stamp:
                        raise locks.LostLock()
                guard()
                path = folder / (name + "-" + record["at"][:10] + ".jsonl")
                files.append_jsonl(path, record, table, check=guard, deadline=deadline)
            return True
        except (OSError, RuntimeError, ValueError, TypeError, OverflowError):
            # The caller's hook stays quiet and continues even if logging fails.
            return False

    def failure(self, error, step, deadline, hook=None, host=None, project=None,
                log=None, count=None, when=None):
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
        return self._append("failures", "TBL-004", record, deadline)

    def timing(self, hook, host, ms, outcome, deadline, when=None):
        if not choice(hook, HOOKS) or not choice(host, HOSTS) or not choice(outcome, OUTCOMES):
            return False
        if not configuration.integer(ms) or ms < 0:
            return False
        try:
            record = {"at": base.utc_time(when), "hook": hook, "host": host,
                      "ms": int(ms), "outcome": outcome}
        except (ValueError, TypeError, AttributeError, OverflowError):
            return False
        return self._append("hooks", "TBL-005", record, deadline)
