"""Device retention settings for either store format from release 0.3.0; previews never perform maintenance."""
import copy
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import re
import stat

from . import base, cleanup, clock, commands, configuration, enablement, files, locks
from . import raw_rewrite, retention as policy, store
from .worker_support import BoundDiagnostics


def _now():
    return datetime.now(timezone.utc)


@contextmanager
def _configuration(context):
    original = context.record
    memory = enablement.CommandStore(context.memory.folder, getattr(context.memory, "fence", None))
    context.memory = memory
    notes = []
    report = lambda error, count=None: notes.append((error, count))
    try:
        with context.lock(memory.folder / "store.lock", "store", report=report) as owner:
            pinned, accepted, fingerprint = [None], [None], [None]
            def check():
                owner.check()
                if pinned[0] is not None:
                    try:
                        current = enablement._header_stamp(memory, pinned[0])
                    except FileNotFoundError:
                        raise locks.LostLock() from None
                    if fingerprint[0] is not None and current != fingerprint[0]:
                        raise locks.LostLock()
                    fingerprint[0] = current
                owner.check()
            def header(data):
                value = context.header(data)
                if value["device"] != original["device"]:
                    raise locks.LostLock()
                accepted[0] = data
                return value
            try:
                context.record = enablement._read(memory, "store.json", header, check, report)
            except (FileNotFoundError, ValueError, UnicodeError, files.RestoreNeeded):
                raise store.StoreUnavailable("store-damaged") from None
            pinned[0] = accepted[0]
            check()
            try:
                document = enablement._read(memory, "configuration.json", store._configuration, check, report)
            except FileNotFoundError:
                document = {}
            except (ValueError, UnicodeError, files.RestoreNeeded):
                raise configuration.ConfigurationInvalid("$") from None
            context.configuration = configuration.prepare(document)
            yield check, report
    except locks.LostLock:
        notes.clear()
        raise
    finally:
        if context.record and notes:
            try:
                logger = BoundDiagnostics(commands.diagnostic_store(memory, context.record["device"], context.format))
                for error, count in notes:
                    logger.failure(error, "restore", clock.now() + 10, count=count)
            except Exception:
                pass


def _entries(context, days, check, report):
    """Count the worker's age predicate in guarded, unmodified raw snapshots."""
    memory = context.memory
    cutoff = _now() - timedelta(days=days)
    deadline = clock.now() + 10
    original_check = check
    def check():
        if clock.now() >= deadline:
            raise locks.LockBusy()
        original_check()
    folder = memory.folder / "projects"
    check()
    if memory.fence.check(folder) is None:
        return 0
    roots = []
    for path in folder.iterdir():
        check()
        name = path.name[:-1] if path.name.endswith("_") else path.name
        try:
            if base.project_folder_name(name) != path.name:
                continue
        except ValueError:
            continue
        info = memory.fence.check(path)
        if info is not None and stat.S_ISDIR(info.st_mode):
            roots.append(path)
    roots.sort(key=lambda p: str(p / "curation.lock"))
    total = 0
    for root in roots:
        with context.lock(root / "curation.lock", "curation", report=report) as curator:
            with context.lock(root / "layer.lock", "layer", report=report) as layer:
                raw = root / "raw"
                check()
                if memory.fence.check(raw) is None:
                    continue
                names = set()
                for path in raw.iterdir():
                    check()
                    match = re.fullmatch("(" + cleanup.LOG + r")\.jsonl(?:\.bak)?", path.name)
                    if match:
                        names.add(match[1])
                for log in sorted(names):
                    path = raw / (log + ".jsonl")
                    with context.lock(path.with_suffix(".lock"), "raw", report=report) as owner:
                        candidate = path if memory.fence.check(path) is not None else path.with_name(path.name + ".bak")
                        original = memory.fence.check(candidate)
                        if original is None:
                            continue
                        if not stat.S_ISREG(original.st_mode) or original.st_nlink != 1:
                            raise ValueError()
                        stamp = cleanup.stamp(original)
                        def guarded():
                            if clock.now() >= deadline:
                                raise locks.LockBusy()
                            check()
                            for lease in (curator, layer, owner):
                                lease.check()
                            if candidate != path and memory.fence.check(path) is not None:
                                raise locks.LostLock()
                            current = memory.fence.check(candidate)
                            if current is None or cleanup.stamp(current) != stamp or current.st_nlink != 1:
                                raise locks.LostLock()
                            check()
                            for lease in (curator, layer, owner):
                                lease.check()
                        for line, complete in raw_rewrite._lines(raw_rewrite._chunks(memory, candidate, guarded)):
                            if not complete:
                                continue
                            try:
                                entry = raw_rewrite._entry(line, log)
                                expired = policy._time(entry["at"]) < cutoff
                            except (ValueError, UnicodeError):
                                continue
                            total += int(expired)
                        guarded()
    check()
    return total


def retention(context):
    try:
        with _configuration(context) as (check, report):
            before = context.configuration
            days, was = context.arguments["days"], before.values["retention"]["days"]
            data = dict(days=days, was=was)
            if days == was:
                return commands.result("retention", data, "The retention period is already set to this number of days.", "nothing")
            def apply():
                document = copy.deepcopy(before.document)
                document.setdefault("retention", {})["days"] = days
                configuration.prepare(document)
                check()
                files.write_json(context.memory.folder / "configuration.json", document, "TBL-002", check=check,
                                 path_check=context.memory.fence.check)
                return commands.result("retention", data, "The retention period is set. Old entries are removed at the next session start.")
            if days < was:
                return context.confirm(dict(data, entries=_entries(context, days, check, report)),
                                       "Shorter retention deletes these old entries at the next session start. Confirm this change first.", apply)
            return apply()
    except store.StoreUnavailable as error:
        return commands.common_result("retention", error.code)
    except configuration.ConfigurationInvalid as error:
        return commands.common_result("retention", "configuration-invalid", field=error.field)
