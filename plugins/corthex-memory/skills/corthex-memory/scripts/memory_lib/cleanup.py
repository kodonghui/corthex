"""C1-owned sidecars only. Retention and directory provisioning live elsewhere."""
import re
import stat
import time

from . import base, clock, configuration, files, locks, raw_log, store, worker_support

AGE_NS = 600 * 1000000000
LINE_BYTES = 8 * 1024 * 1024
LOG = r"(?:claude-code|codex)-[0-9a-f]{16}"


def stamp(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def raw_primary(memory, path, guard):
    pending = bytearray()
    memory.fence.check(path)
    with path.open("rb") as source:
        while True:
            guard()
            memory.fence.check(path)
            chunk = source.read(worker_support.CHUNK)
            if not chunk:
                break
            parts = chunk.split(b"\n")
            for index, part in enumerate(parts):
                if len(pending) + len(part) > LINE_BYTES:
                    raise ValueError("cleanup line too large")
                pending.extend(part)
                if index < len(parts) - 1:
                    guard()
                    value = store.json_document(pending)
                    raw_log._parsed_entry(value, value["host"], value["session"])
                    if raw_log.log_name(value["host"], value["session"]) + ".jsonl" != path.name:
                        raise ValueError("raw file identity differs")
                    pending.clear()
    if pending:
        raise ValueError("incomplete raw line")


def readable(memory, primary, parse, guard, deadline):
    def read():
        guard()
        before = memory.fence.check(primary)
        if before is None or not stat.S_ISREG(before.st_mode):
            return None
        if parse is raw_primary:
            parse(memory, primary, guard)
        else:
            parse(memory.fence.read(primary, deadline))
        guard()
        after = memory.fence.check(primary)
        return stamp(before) if after is not None and stamp(before) == stamp(after) else None
    try:
        return files._retry(read, deadline)
    except (OSError, ValueError, UnicodeError, KeyError, TypeError,
            configuration.ConfigurationInvalid, store.StoreUnavailable):
        return None


def artifacts(memory, primary, leases, deadline, parse=None):
    """parse=None cleans only this known lease's old detached stale files."""
    guard = lambda: memory.check(deadline, leases)
    guard()
    if memory.fence.check(primary.parent) is None:
        return 0
    temporary = re.compile(re.escape(primary.name) + r"(?:\.bak)?\.[a-z0-9_]{8}\.tmp\Z")
    stale = re.compile(re.escape(primary.name) + r"\.[0-9a-f]{32}\.stale\Z")
    count = 0
    for path in primary.parent.iterdir():
        guard()
        backup = parse is not None and path.name == primary.name + ".bak"
        if not (backup or (temporary if parse is not None else stale).fullmatch(path.name)):
            continue
        try:
            before = memory.fence.check(path)
            if before is None or not stat.S_ISREG(before.st_mode):
                continue
            if not backup and time.time_ns() - before.st_mtime_ns <= AGE_NS:
                continue
            valid = readable(memory, primary, parse, guard, deadline) if backup else None
            if backup and valid is None:
                continue
            def check():
                guard()
                current = memory.fence.check(path)
                if current is None or stamp(current) != stamp(before):
                    raise worker_support.UnsafePath()
                if not backup and time.time_ns() - current.st_mtime_ns <= AGE_NS:
                    raise worker_support.UnsafePath()
                if backup:
                    current_primary = memory.fence.check(primary)
                    if current_primary is None or stamp(current_primary) != valid:
                        raise worker_support.UnsafePath()
                for lease in leases:
                    lease.check()
                if clock.now() >= deadline:
                    raise locks.LockBusy()
            def remove():
                check()
                path.unlink()
            try:
                files._retry(remove, deadline)
                count += 1
            except FileNotFoundError:
                pass
        except worker_support.UnsafePath:
            continue
    guard()
    return count


def clean_store(memory, deadline):
    """Run separately, before/after project phases, never under a later lease."""
    with memory.lease(memory.folder / "store.lock", "store", deadline) as lease:
        count = sum(artifacts(memory, memory.folder / name, (lease,), deadline, parse)
                    for name, parse in (("store.json", store._record),
                                        ("configuration.json", store._configuration)))
        return count + artifacts(memory, lease.path, (lease,), deadline)


def clean_project(memory, project, curation, deadline):
    root = memory.folder / "projects" / base.project_folder_name(project)
    if (curation not in memory.held or curation.path != root / "curation.lock" or
            curation.device != memory.device or
            curation.policy != locks.POLICIES["curation"]):
        raise locks.LostLock()
    memory.check(deadline, (curation,))
    count = artifacts(memory, curation.path, (curation,), deadline)
    raw = root / "raw"
    if memory.fence.check(raw) is None:
        return count
    names = set()
    for path in raw.iterdir():
        memory.check(deadline, (curation,))
        memory.fence.check(raw)
        match = re.fullmatch("(" + LOG + r")\.(?:jsonl|lock)(?:\..*)?", path.name)
        if match:
            names.add(match.group(1))
    try:
        with memory.lease(root / "layer.lock", "layer", deadline) as layer:
            count += artifacts(memory, layer.path, (curation, layer), deadline)
            for name in sorted(names):
                try:
                    with memory.lease(raw / (name + ".lock"), "raw", deadline) as lease:
                        held = (curation, layer, lease)
                        count += artifacts(memory, raw / (name + ".jsonl"), held, deadline, raw_primary)
                        count += artifacts(memory, lease.path, held, deadline)
                except locks.LockBusy:
                    memory.check(deadline, (curation, layer))
    except locks.LockBusy:
        memory.check(deadline, (curation,))
    return count


def clean_logs(memory, deadline):
    """Only C1 diagnostic lease sidecars; usage and unsupported backups stay."""
    count = 0
    if memory.fence.check(memory.folder / "logs") is None:
        return count
    for name in ("failures", "hooks"):
        try:
            with memory.lease(memory.folder / "logs" / (name + ".lock"), "log", deadline) as lease:
                count += artifacts(memory, lease.path, (lease,), deadline)
        except locks.LockBusy:
            memory.check(deadline)
    return count
