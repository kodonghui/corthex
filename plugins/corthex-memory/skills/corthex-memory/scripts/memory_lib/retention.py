"""C1 retention phases; no provisioning or worker/start integration."""
from datetime import datetime, timedelta, timezone
import re
import stat

from . import base, cleanup, clock, curation, files, locks, raw_rewrite, worker_support

MARKER = re.compile(r"([0-9]{8}T[0-9]{6}Z)\.(" + cleanup.LOG + r")\.([1-9][0-9]*)\Z")


def _time(value):
    # Raw parsing and base.utc_time already enforce the exact UTC wire shape.
    return datetime.fromisoformat(value[:-1] + "+00:00")


def _now(when):
    return _time(base.utc_time(when))


def _totals():
    return dict(files=0, kept=0, removed=0, damaged=0, future=0,
                unreadable_age=0, markers=0, skipped=0)


def _guard(memory, path, original, check):
    def guard():
        check()
        current = memory.fence.check(path)
        if (current is None or cleanup.stamp(current) != cleanup.stamp(original) or
                current.st_nlink != original.st_nlink):
            raise worker_support.UnsafePath()
        check()
    return guard


def _remove(memory, path, original, check):
    files._unlink(path, _guard(memory, path, original, check))


def _inventory(memory, root, check, deadline):
    folder = root / "unprocessed"
    check()
    try:
        if memory.fence.check(folder) is None:
            return {}
    except worker_support.UnsafePath:
        return {}
    inventory, validated = {}, set()
    for path in folder.iterdir():
        if clock.now() >= deadline:
            raise locks.LockBusy()
        match = MARKER.fullmatch(path.name)
        if match is None:
            continue
        try:
            stamp = match.group(1)
            if stamp not in validated:
                datetime(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8]),
                         int(stamp[9:11]), int(stamp[11:13]), int(stamp[13:15]))
                validated.add(stamp)
        except ValueError:
            continue
        inventory.setdefault(match.group(2), []).append((path, int(match.group(3))))
    check()
    return inventory


def _markers(memory, candidates, surviving, check, deadline):
    removed = 0
    for path, turn in candidates:
        if clock.now() >= deadline:
            raise locks.LockBusy()
        if turn in surviving:
            continue
        try:
            check()
            original = memory.fence.check(path)
            if (original is None or not stat.S_ISREG(original.st_mode) or
                    original.st_size != 0 or original.st_nlink != 1):
                continue
            _remove(memory, path, original, check)
            removed += 1
        except (ValueError, worker_support.UnsafePath, FileNotFoundError):
            continue
    return removed


def _orphans(memory, root, log, candidates, deadline):
    """Retry owned markers after a previous raw deletion and failed callback."""
    path = root / "raw" / (log + ".jsonl")
    with memory.lease(root / "layer.lock", "layer", deadline):
        with memory.lease(path.with_suffix(".lock"), "raw", deadline):
            guarded = curation.guard(memory, root, deadline)
            def absent():
                guarded()
                if any(memory.fence.check(p) is not None for p in (path, path.with_name(path.name + ".bak"))):
                    raise locks.LostLock()
                guarded()
            absent()
            progress = curation.read(memory, root, deadline)
            if log not in progress["logs"]:
                return 0
            # Never claim an old count covers seqs in a subsequently recreated file.
            if progress["logs"].get(log, 0):
                absent()
                progress["logs"][log] = 0
                curation.write(memory, root, progress, deadline)
            removed = _markers(memory, candidates, frozenset(), absent, deadline)
            absent()
            progress["logs"].pop(log)
            curation.write(memory, root, progress, deadline)
            return removed


def retain_project(memory, project, owner, deadline, when=None):
    """Apply the configured age rule under the caller's tracked curation lease.

    The future count covers the first snapshots this invocation filters; it is
    not the status command's complete inventory. Concurrent suffix bytes stay
    unfiltered until a later maintenance pass, as required by the rewrite.
    """
    root = memory.folder / "projects" / base.project_folder_name(project)
    if (owner not in memory.held or owner.path != root / "curation.lock" or
            owner.device != memory.device or owner.policy != locks.POLICIES["curation"]):
        raise locks.LostLock()
    check = lambda: memory.check(deadline, memory.held)
    check()
    now = _now(when)
    cutoff = now - timedelta(days=memory.config.values["retention"]["days"])
    totals = _totals()
    folder = root / "raw"
    if memory.fence.check(folder) is None:
        return totals
    markers = _inventory(memory, root, check, deadline)
    names = set(markers)
    for path in folder.iterdir():
        check()
        match = re.fullmatch("(" + cleanup.LOG + r")\.jsonl(?:\.bak)?", path.name)
        if match:
            names.add(match.group(1))
    for log in sorted(names):
        check()
        observed = dict(future=0, unreadable_age=0, markers=0)
        def keep(entry):
            try:
                at = _time(entry["at"])
            except ValueError:
                observed["unreadable_age"] += 1
                return True
            # The cutoff stays fixed, but a live writer may append after it.
            # Only dates still ahead when inspected indicate a future clock.
            if at > now and at > _now(when):
                observed["future"] += 1
            return at >= cutoff
        def after(result, guarded):
            observed["markers"] = _markers(memory, markers.get(log, ()), result.turns, guarded, deadline)
        try:
            path = folder / (log + ".jsonl")
            if all(memory.fence.check(p) is None for p in (path, path.with_name(path.name + ".bak"))):
                totals["markers"] += _orphans(memory, root, log, markers.get(log, ()), deadline)
                continue
            result = raw_rewrite.rewrite(memory, project, owner, log, keep, deadline, after)
        except worker_support.UnsafePath:
            totals["skipped"] += 1
            continue
        except locks.LockBusy:
            check()
            totals["skipped"] += 1
            continue
        except locks.LostLock:
            raise
        except (OSError, RuntimeError, ValueError, TypeError, OverflowError) as error:
            memory.note(error, step="retention")
            totals["skipped"] += 1
            continue
        totals["files"] += 1
        for field in ("kept", "removed", "damaged"):
            totals[field] += getattr(result, field)
        for field, count in observed.items():
            totals[field] += count
        if result.damaged:
            memory.note("damaged-line", result.damaged, "retention")
        if observed["future"]:
            memory.note("future-entry", observed["future"], "retention")
        if observed["unreadable_age"]:
            memory.note(ValueError(), observed["unreadable_age"], "retention")
    check()
    return totals


def retain_logs(memory, deadline, when=None):
    """Delete only wholly expired UTC-day failure/timing files under log leases."""
    if memory.held:
        raise locks.LostLock()
    memory.check(deadline)
    now, removed = _now(when), 0
    folder = memory.folder / "logs"
    if memory.fence.check(folder) is None:
        return removed
    for name, days in (("failures", memory.config.values["retention"]["days"]), ("hooks", 8)):
        cutoff = now - timedelta(days=days)
        try:
            with memory.lease(folder / (name + ".lock"), "log", deadline) as lease:
                check = lambda: memory.check(deadline, (lease,))
                paths, sidecars = list(folder.iterdir()), {}
                pattern = re.escape(name) + r"-[0-9]{4}-[0-9]{2}-[0-9]{2}\.jsonl"
                for path in paths:
                    if clock.now() >= deadline:
                        raise locks.LockBusy()
                    match = re.fullmatch("(" + pattern + r")(?:\.bak|(?:\.bak)?\.[a-z0-9_]{8}\.tmp)", path.name)
                    if match:
                        sidecars.setdefault(match.group(1), []).append(path)
                for path in paths:
                    match = re.fullmatch(re.escape(name) + r"-([0-9]{4}-[0-9]{2}-[0-9]{2})\.jsonl", path.name)
                    if match is None:
                        continue
                    try:
                        day = datetime.strptime(match.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
                        if day >= cutoff or day + timedelta(days=1) > cutoff:
                            continue
                        check()
                        original = memory.fence.check(path)
                        if (original is None or not stat.S_ISREG(original.st_mode) or
                                original.st_nlink != 1):
                            continue
                        primary = _guard(memory, path, original, check)
                        for candidate in sidecars.get(path.name, ()):
                            primary()
                            info = memory.fence.check(candidate)
                            if info is None:
                                continue
                            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                                raise worker_support.UnsafePath()
                            _remove(memory, candidate, info, primary)
                        _remove(memory, path, original, check)
                        removed += 1
                    except (ValueError, worker_support.UnsafePath, FileNotFoundError):
                        continue
                    except OSError as error:
                        memory.note(error, step="retention")
        except locks.LockBusy:
            memory.check(deadline)
    memory.check(deadline)
    return removed
