"""Guarded raw rewrites, without retention policy, provisioning or worker starts."""
import contextlib
import hashlib
import itertools
import os
import re
import stat
from dataclasses import dataclass

from . import base, cleanup, clock, curation, files, locks, raw_log, store, worker_support

RAW_LEASE_WAIT_SECONDS = 0.05


class OversizedLine(RuntimeError):
    """Preserve an unsupported line; it is not safely disposable damage."""


@dataclass(frozen=True)
class Rewritten:
    kept: int
    removed: int
    damaged: int
    turns: frozenset
    deleted: bool


def _chunks(memory, path, check, start=0, size=None, digest=None):
    """Read under a guard that fences this path, then checks current authority."""
    with files._retry(lambda: files._checked(check, lambda: path.open("rb"))) as source:
        info = os.fstat(source.fileno())
        named = memory.fence.check(path)
        if (named is None or not stat.S_ISREG(info.st_mode) or
                (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)):
            raise locks.LostLock()
        left = info.st_size - start if size is None else size
        source.seek(start)
        while left:
            check()
            chunk = source.read(min(left, worker_support.CHUNK))
            if not chunk:
                raise locks.LostLock()
            left -= len(chunk)
            if digest is not None:
                digest.update(chunk)
            yield chunk
    check()


def _lines(chunks):
    pending = bytearray()
    for chunk in chunks:
        parts = chunk.split(b"\n")
        for index, part in enumerate(parts):
            if len(pending) + len(part) > cleanup.LINE_BYTES:
                raise OversizedLine()
            pending.extend(part)
            if index < len(parts) - 1:
                yield bytes(pending) + b"\n", True
                pending.clear()
    if pending:
        yield bytes(pending), False


def _entry(line, log):
    value = store.json_document(line)
    if not isinstance(value, dict):
        raise ValueError("invalid raw entry")
    raw_log._parsed_entry(value, value.get("host"), value.get("session"))
    if raw_log.log_name(value["host"], value["session"]) != log:
        raise ValueError("raw file identity differs")
    return value


def _batches(chunks):
    """Batch pure selected bytes, without acquiring a recording lease."""
    pending = bytearray()
    try:
        for chunk in chunks:
            if not chunk:
                if pending:
                    yield bytes(pending)
                    pending.clear()
                continue
            view = memoryview(chunk)
            for offset in range(0, len(view), worker_support.CHUNK):
                pending.extend(view[offset:offset + worker_support.CHUNK])
                if len(pending) >= worker_support.CHUNK:
                    yield bytes(pending[:worker_support.CHUNK])
                    del pending[:worker_support.CHUNK]
        if pending:
            yield bytes(pending)
    finally:
        chunks.close()


def rewrite(memory, project, owner, log, keep, deadline, after=None):
    """Filter the first snapshot; carry every later byte unchanged under raw.

    after(result, check), when supplied by the later retention policy, runs
    before the raw lease is released so its marker updates cannot race appends.
    It must use check immediately before each mutation. No diagnostic is flushed
    while a data lease is held. Unrecoverable curation never creates progress.
    """
    root = memory.folder / "projects" / base.project_folder_name(project)
    if (owner not in memory.held or owner.path != root / "curation.lock" or
            owner.device != memory.device or owner.policy != locks.POLICIES["curation"]):
        raise locks.LostLock()
    if not isinstance(log, str) or not re.fullmatch(cleanup.LOG, log):
        raise ValueError("invalid raw log")
    path = root / "raw" / (log + ".jsonl")
    with contextlib.ExitStack() as stack:
        stack.enter_context(memory.lease(root / "layer.lock", "layer", deadline))
        basic = curation.guard(memory, root, deadline)
        progress = curation.read(memory, root, deadline)
        # JSONL damage never restores an older backup. Only a missing file can.
        if memory.fence.check(path) is None:
            with memory.lease(path.with_suffix(".lock"), "raw", deadline):
                def probe(candidate):
                    guard = lambda: files._access(basic, memory.fence.check, candidate)
                    for _ in _lines(_chunks(memory, candidate, guard)):
                        pass
                    return True
                files.read_record(path, lambda value: value, memory.note, holding_lock=True,
                                  check=lambda: files._access(basic, memory.fence.check, path, path.with_name(path.name + ".bak")),
                                  deadline=deadline, reader=probe)
        original = memory.fence.check(path)
        if original is None or not stat.S_ISREG(original.st_mode):
            raise locks.LostLock()
        identity = (original.st_dev, original.st_ino)
        expected = None
        def check():
            # Validate the deadline before metadata, then all leases/store
            # after metadata and before the caller's payload I/O.
            if clock.now() >= deadline:
                raise locks.LockBusy()
            current = memory.fence.check(path)
            if (current is None or (current.st_dev, current.st_ino) != identity or
                    expected is not None and cleanup.stamp(current) != expected):
                raise locks.LostLock()
            basic()
        prefix, turns = hashlib.sha256(), set()
        kept = removed = damaged = highest = 0
        tail = b""
        def content():
            nonlocal kept, removed, damaged, highest, tail
            for line, complete in _lines(_chunks(memory, path, check, size=original.st_size, digest=prefix)):
                if not complete:
                    tail = line
                    continue
                try:
                    entry = _entry(line, log)
                except (ValueError, UnicodeError):
                    damaged += 1
                    continue
                selected = keep(entry)
                if type(selected) is not bool:
                    raise ValueError("a rewrite predicate must return a boolean")
                if selected:
                    kept += 1
                    highest = max(highest, entry["seq"])
                    if "turn" in entry:
                        turns.add(entry["turn"])
                    yield line
                else:
                    removed += 1
            check()
        temporary = None
        ready = []
        stream = _batches(content())
        try:
            # The snapshot and its durability belong outside raw. A start
            # worker must not block a prompt's 50ms wait with these writes.
            temporary = files._temporary(path, stream, True, check=check, path_check=memory.fence.check, ready=ready.append)
            check()
            staged = cleanup.stamp(temporary.stat())
            def staged_check():
                ready[0]()
                if cleanup.stamp(temporary.stat()) != staged:
                    raise RuntimeError("temporary changed")
            lowered = min(progress["logs"].get(log, 0), highest)
            remaining_wait = RAW_LEASE_WAIT_SECONDS
            def acquire(raw):
                nonlocal expected, remaining_wait
                began = clock.now()
                wait_until = began + remaining_wait if remaining_wait > 0 else None
                raw.enter_context(memory.lease(path.with_suffix(".lock"), "raw", deadline,
                                               acquire_deadline=wait_until))
                remaining_wait = max(0, remaining_wait - (clock.now() - began))
                current = memory.fence.check(path)
                if current is None or current.st_size < original.st_size:
                    raise locks.LostLock()
                expected = cleanup.stamp(current)
                verified = hashlib.sha256()
                for _ in _chunks(memory, path, check, size=original.st_size, digest=verified):
                    pass
                if verified.digest() != prefix.digest():
                    raise locks.LostLock()
                return current
            with contextlib.ExitStack() as raw:
                current = acquire(raw)
                if (progress["logs"].get(log, 0) != lowered or
                        kept == 0 and log not in progress["logs"]):
                    # Verify first, then release raw for the durable progress
                    # write. A stop after lowering merely recurates entries.
                    raw.close()
                    expected = None
                    staged_check()
                    progress["logs"][log] = lowered
                    curation.write(memory, root, progress, deadline)
                    staged_check()
                    current = acquire(raw)
                # A completed concurrent tail is carried, never age-filtered.
                # Otherwise the snapshot's incomplete last line is removed.
                grew = current.st_size > original.st_size
                changed = bool(removed or damaged or tail and not grew or original.st_size == 0)
                if grew:
                    # Only the bytes appended during preparation need a final
                    # durable carry under raw. Keep the original atomic suffix
                    # rule: an active writer cannot starve retention forever.
                    suffix = _chunks(memory, path, check, start=original.st_size,
                                     size=current.st_size - original.st_size)
                    def later():
                        nonlocal kept, damaged
                        for line, complete in _lines(itertools.chain((tail,), suffix)):
                            try:
                                if not complete:
                                    raise ValueError("incomplete raw line")
                                entry = _entry(line, log)
                                kept += 1
                                if "turn" in entry:
                                    turns.add(entry["turn"])
                            except (ValueError, UnicodeError):
                                damaged += 1
                            yield line
                    batches = _batches(later())
                    try:
                        if changed:
                            staged_check()
                            with files._retry(lambda: files._checked(staged_check, lambda: temporary.open("ab", buffering=0)), deadline) as target:
                                info = os.fstat(target.fileno())
                                if not stat.S_ISREG(info.st_mode) or cleanup.stamp(info) != staged:
                                    raise RuntimeError("temporary descriptor changed")
                                staged_check()
                                for chunk in batches:
                                    if files._checked(staged_check, lambda: target.write(chunk)) != len(chunk):
                                        raise OSError("short suffix write")
                                    staged = cleanup.stamp(os.fstat(target.fileno()))
                                staged_check()
                                files._sync(target.fileno())
                            staged_check()
                        else:
                            for _ in batches:
                                pass
                    finally:
                        batches.close()
                elif tail:
                    damaged += 1
                check()
                staged_check()
                deleted = changed and temporary.stat().st_size == 0
                if deleted:
                    pattern = re.compile(re.escape(path.name) + r"(?:\.bak|(?:\.bak)?\.[a-z0-9_]{8}\.tmp)\Z")
                    for candidate in path.parent.iterdir():
                        if candidate != temporary and pattern.fullmatch(candidate.name):
                            files._unlink(candidate, lambda p=candidate: files._access(ready[0], memory.fence.check, p))
                    files._unlink(path, staged_check)
                    expected = None
                elif changed:
                    backup = path.with_name(path.name + ".bak")
                    files._backup(path, backup, check=check, path_check=memory.fence.check)
                    files._retry(lambda: files._checked(staged_check, lambda: os.replace(str(temporary), str(path))), deadline)
                    expected = None
                    files._unlink(backup, lambda: files._access(basic, memory.fence.check, backup))
                result = Rewritten(kept, removed, damaged, frozenset(turns), deleted)
                if after is not None:
                    after(result, basic)
            if deleted:
                progress["logs"].pop(log, None)
                curation.write(memory, root, progress, deadline)
            return result
        finally:
            stream.close()
            if temporary is not None:
                files._unlink(temporary, lambda: ready[0](basic))
