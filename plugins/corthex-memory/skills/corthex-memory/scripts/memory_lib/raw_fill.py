"""Fill forgotten raw text under the project's layer lease (TBL-007; SPEC-035; SPEC-007; TASK-098).

A forget replaces each character of a quoted range of a raw log entry with
U+FFFD, so that the text keeps its length and the entry's other quotes keep
their positions, and lists the range in the entry's `forgotten`. `fill` rewrites
one raw log as retention does (`raw_rewrite.rewrite`): it builds the new file
from a snapshot without the raw lock, then holds the lock only to check that the
snapshot is still the start of the file, to carry the bytes appended meanwhile
unchanged and to move the new file over the old one, which stays as a backup
until the move is done. Every other byte stays as it was, damaged and unfinished
lines too, because a forget repairs nothing: no entry goes, every `seq` stays
and the curation record is left alone. The caller holds the project's layer
lease, as a forget does for all of its effects; the fill never takes or waits
for the curation lease. A backup or temporary file of the log that an earlier
rewrite left when it stopped can still hold the text, so the fill removes them
under the raw lock, also when every range is filled already.
"""
import contextlib
import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from . import base, cleanup, clock, configuration, files, locks, raw_log, raw_rewrite

FILL = "�"


@dataclass(frozen=True)
class Filled:
    entries: frozenset  # IDs of the entries whose line the fill rewrote
    ranges: int         # ranges added to their `forgotten` lists


def _wanted(ranges):
    """Entry ID -> its sorted distinct (start, end) ranges; ValueError for any other shape."""
    if not isinstance(ranges, dict):
        raise ValueError("ranges map entry IDs to their ranges")
    wanted = {}
    for entry, pairs in ranges.items():
        if not isinstance(entry, str) or not raw_log.ENTRY_ID.fullmatch(entry) or not isinstance(pairs, (list, tuple)):
            raise ValueError("invalid entry ranges")
        found = set()
        for pair in pairs:
            if (not isinstance(pair, (list, tuple)) or len(pair) != 2 or
                    not all(configuration.integer(n) for n in pair) or not 0 <= pair[0] < pair[1]):
                raise ValueError("invalid forgotten range")
            found.add((int(pair[0]), int(pair[1])))
        if found:
            wanted[entry] = sorted(found)
    return wanted


def _filled(entry, ranges, log):
    """The entry's line with the ranges filled and listed, and how many it added; None when nothing changes.

    Every listed range is filled again, so a line whose listed text is not
    U+FFFD any more is rewritten too.
    """
    text = entry.get("text")
    if not isinstance(text, str) or any(end > len(text) for _, end in ranges):
        raise ValueError("a forgotten range does not fit its entry")
    listed = {(int(start), int(end)) for start, end in entry.get("forgotten", ())}
    every = sorted(listed.union(ranges))
    characters = list(text)
    for start, end in every:
        characters[start:end] = FILL * (end - start)
    value = dict(entry, text="".join(characters), forgotten=[list(pair) for pair in every])
    if value["text"] == text and len(every) == len(listed):
        return None
    data = base.json_bytes(value, "TBL-007", compact=True)
    raw_rewrite._entry(data, log)
    return data, len(every) - len(listed)


def _leftovers(path, keep=None):
    """The log's backup and temporary files, which only a stopped rewrite leaves while its layer lease is held."""
    pattern = re.compile(re.escape(path.name) + r"(?:\.bak|(?:\.bak)?\.[a-z0-9_]{8}\.tmp)\Z")
    try:
        names = files._retry(lambda: list(path.parent.iterdir()))
    except FileNotFoundError:
        return []
    return [candidate for candidate in names if candidate != keep and pattern.fullmatch(candidate.name)]


def fill(memory, root, log, ranges, deadline, wait=raw_rewrite.RAW_LEASE_WAIT_SECONDS):
    """Fill the ranges, entry ID -> [start, end] pairs, of one raw log of the project at `root`.

    The caller holds the project's layer lease. An entry that no complete line
    of the log holds, as in a log that retention deleted, has nothing to fill
    and is left out of the result. A range that does not fit its entry's text,
    or one named for a session boundary, raises ValueError before anything
    changes, and a line longer than 8 MiB stops the fill as it stops retention
    (`raw_rewrite.OversizedLine`). The raw lock is waited for at most `wait`
    seconds, after a first attempt.
    """
    root = Path(root)
    if not any(lease.path == root / "layer.lock" and lease.policy == locks.POLICIES["layer"] and
               lease.device == memory.device for lease in memory.held):
        raise locks.LostLock()
    if not isinstance(log, str) or not re.fullmatch(cleanup.LOG, log):
        raise ValueError("invalid raw log")
    if not configuration.number(wait) or not 0 <= wait:
        raise ValueError("invalid raw wait")
    wanted = _wanted(ranges)
    path = root / "raw" / (log + ".jsonl")
    basic = lambda: memory.check(deadline, memory.held)
    basic()

    def lease(raw):
        raw.enter_context(memory.lease(path.with_suffix(".lock"), "raw", deadline,
                                       acquire_deadline=clock.now() + wait))

    def remove(left):
        for candidate in left:
            files._unlink(candidate, lambda p=candidate: files._access(basic, memory.fence.check, p))

    # JSONL damage never restores an older backup; only a missing file can.
    if memory.fence.check(path) is None:
        with contextlib.ExitStack() as raw:
            lease(raw)

            def probe(candidate):
                guard = lambda: files._access(basic, memory.fence.check, candidate)
                for _ in raw_rewrite._lines(raw_rewrite._chunks(memory, candidate, guard)):
                    pass
                return True
            try:
                files.read_record(path, lambda value: value, memory.note, holding_lock=True,
                                  check=lambda: files._access(basic, memory.fence.check, path,
                                                              path.with_name(path.name + ".bak")),
                                  deadline=deadline, reader=probe)
            except FileNotFoundError:
                remove(_leftovers(path))
                return Filled(frozenset(), 0)
    original = memory.fence.check(path)
    if original is None or not stat.S_ISREG(original.st_mode):
        raise locks.LostLock()
    identity = (original.st_dev, original.st_ino)
    expected = None

    def check():
        # The deadline before the metadata, then the leases and the store
        # record after the metadata and before the caller's file access.
        if clock.now() >= deadline:
            raise locks.LockBusy()
        current = memory.fence.check(path)
        if (current is None or (current.st_dev, current.st_ino) != identity or
                expected is not None and cleanup.stamp(current) != expected):
            raise locks.LostLock()
        basic()
    prefix, changed, added = hashlib.sha256(), set(), 0

    def content():
        nonlocal added
        for line, complete in raw_rewrite._lines(raw_rewrite._chunks(memory, path, check, size=original.st_size,
                                                                     digest=prefix)):
            entry = None
            if complete:
                try:
                    entry = raw_rewrite._entry(line, log)
                except (ValueError, UnicodeError):
                    pass
            if entry is not None and entry["id"] in wanted:
                found = _filled(entry, wanted[entry["id"]], log)
                if found is not None:
                    line = found[0]
                    changed.add(entry["id"])
                    added += found[1]
            yield line
        check()
    temporary, ready = None, []
    stream = raw_rewrite._batches(content())
    try:
        # The snapshot and its durability belong outside raw, as for retention.
        temporary = files._temporary(path, stream, True, check=check, path_check=memory.fence.check,
                                     ready=ready.append)
        check()
        staged = cleanup.stamp(temporary.stat())

        def staged_check():
            ready[0]()
            if cleanup.stamp(temporary.stat()) != staged:
                raise RuntimeError("temporary changed")
        with contextlib.ExitStack() as raw:
            if changed:
                lease(raw)
                current = memory.fence.check(path)
                if current is None or current.st_size < original.st_size:
                    raise locks.LostLock()
                expected = cleanup.stamp(current)
                verified = hashlib.sha256()
                for _ in raw_rewrite._chunks(memory, path, check, size=original.st_size, digest=verified):
                    pass
                if verified.digest() != prefix.digest():
                    raise locks.LostLock()
                if current.st_size > original.st_size:
                    # The bytes appended while the new file was built, carried
                    # unchanged; a line that the snapshot cut ends in them.
                    batches = raw_rewrite._batches(raw_rewrite._chunks(
                        memory, path, check, start=original.st_size, size=current.st_size - original.st_size))
                    try:
                        staged_check()
                        with files._retry(lambda: files._checked(staged_check, lambda: temporary.open("ab", buffering=0)),
                                          deadline) as target:
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
                    finally:
                        batches.close()
                check()
                staged_check()
                backup = path.with_name(path.name + ".bak")
                files._backup(path, backup, check=check, path_check=memory.fence.check)
                files._retry(lambda: files._checked(staged_check, lambda: os.replace(str(temporary), str(path))),
                             deadline)
                expected = None
                files._unlink(backup, lambda: files._access(basic, memory.fence.check, backup))
            left = _leftovers(path, temporary)
            if left and not changed:
                lease(raw)
            remove(left)
        return Filled(frozenset(changed), added)
    finally:
        stream.close()
        if temporary is not None:
            files._unlink(temporary, lambda: ready[0](basic))
