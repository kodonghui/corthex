"""Durable conflict showing counts: TBL-010's conflict-counts.json (SPEC-143).

A device-local high-water from 0 to 3 for each candidate ID, kept outside the
curated layer under its own notice-counter lease, which a layer writer takes
after the layer lease and a session start takes alone. The file has no backup
and is never restored: when it is missing, damaged or unreadable, or names no
count for a candidate, that candidate counts as shown three times. A lost
write or an older copy can therefore never show a candidate again, and
closing, reopening or removing an individual notice never lowers a count.
From release 0.3.0 the start hook reaches it through the start summary, and
the item changes through `item_io`, for a format-2 store.
"""
import json
import os
from pathlib import Path

from . import configuration, conflict_types, curation, files, format2, item_types, locks, revision_io

NAME = 'conflict-counts.json'
LOCK = 'conflict-counts.lock'
TIMES = 3


def parse_counts(data):
    """Strictly read conflict-counts.json: {"counts": {candidate ID: 0 to 3}}."""
    value = item_types._document(data)
    curation._shape(value, 'counts')
    if not isinstance(value['counts'], dict):
        raise ValueError('invalid conflict counts')
    for candidate, shown in value['counts'].items():
        format2._id(candidate, format2._CANDIDATE)
        if not configuration.integer(shown) or not 0 <= shown <= TIMES:
            raise ValueError('invalid conflict count')
    return value


def counts_bytes(counts):
    value = {'counts': {candidate: counts[candidate] for candidate in sorted(counts)}}
    data = (json.dumps(value, ensure_ascii=True, allow_nan=False, indent=2) + '\n').encode('ascii')
    parse_counts(data)
    return data


def _paths(root):
    folder = Path(root) / 'notices'
    return folder / NAME, folder / LOCK


def read(memory, root, deadline):
    """The counts by candidate ID; None when the file is missing, damaged or unreadable.

    The file is read as it is: no backup is consulted or restored.
    """
    path = _paths(root)[0]
    try:
        data = files._retry(lambda: memory.fence.read(path, deadline), deadline)
    except FileNotFoundError:
        return None
    try:
        return {candidate: int(count) for candidate, count in parse_counts(data)['counts'].items()}
    except (ValueError, UnicodeError):
        return None


def shown(counts, candidate):
    """How often a candidate was shown; without a proven count, three times."""
    if counts is None:
        return TIMES
    return counts.get(candidate, TIMES)


def eligible(conflicts, counts):
    """Open candidates shown fewer than three times, oldest first; conflicts still lists the rest."""
    return [candidate for candidate in conflict_types.open_candidates(conflicts)
            if shown(counts, candidate['id']) < TIMES]


def lost(conflicts, counts):
    """Open candidates that count as shown three times only because no count proves otherwise."""
    return [candidate['id'] for candidate in conflict_types.open_candidates(conflicts)
            if counts is None or candidate['id'] not in counts]


def _sync_folder(memory, folder, check):
    if os.name == 'nt':
        # On Windows the file's own flush also commits its directory entry.
        return
    check()
    expected = memory.fence.check(folder)
    descriptor = os.open(str(folder), os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0))
    try:
        opened = os.fstat(descriptor)
        if expected is None or (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino):
            raise locks.LostLock()
        files._sync(descriptor)
    finally:
        os.close(descriptor)
    check()


def _write(memory, root, counts, check):
    """Replace the file durably: a synced temporary, one move, then the synced folder."""
    path = _paths(root)[0]
    ready = []
    temporary = files._temporary(path, counts_bytes(counts), True, check=check, path_check=memory.fence.check,
                                 ready=ready.append)

    def move():
        files._access(check, memory.fence.check, path)
        ready[0]()
        os.replace(str(temporary), str(path))

    try:
        files._retry(move)
    finally:
        files._unlink(temporary, ready[0])
    _sync_folder(memory, path.parent, check)


def initialize(memory, root, candidates, conflicts, deadline):
    """Durably count zero for new candidate IDs before a layer writer publishes them.

    The caller holds the project's layer lease and passes the TBL-120 value it
    read under it. An ID that value already lists was published before and
    may have been shown, so it is refused instead of counted from zero again;
    an existing count is never lowered. A missing or damaged file is replaced
    by one that holds only the counts proven now.
    """
    root = Path(root)
    check_layer = revision_io.guard(memory, root, deadline)
    new = list(candidates)
    for candidate in new:
        format2._id(candidate, format2._CANDIDATE)
    published = {candidate['id'] for candidate in conflict_types.parse_conflicts(item_types._raw(conflicts))['candidates']}
    if not new or len(set(new)) != len(new) or published.intersection(new):
        raise ValueError('new conflict candidates required')
    lock = _paths(root)[1]
    with memory.lease(lock, 'notice', deadline, acquire_deadline=deadline):
        def check():
            check_layer()
            memory.check(deadline, memory.held)

        check()
        counts = read(memory, root, deadline)
        updated = dict(counts or {})
        for candidate in new:
            updated.setdefault(candidate, 0)
        if updated != counts:
            _write(memory, root, updated, check)
        check()


def reserve(memory, root, candidate, deadline):
    """Reserve one showing of a candidate whose notice line fits; the new count, or None.

    Only the notice-counter lease is taken. The count is read again under it
    and written, one higher, durably before this returns; the caller shows the
    line only then. A busy or lost lease, a passed deadline, or a failed read
    or write returns None, as does a candidate already shown three times. It
    counts nothing when it comes before the move of the new file; after the
    move, while the folder is synced, it uses up that showing, as a stop after
    the move but before the output does. The third showing also removes the
    candidate's individual notice, when there is one; its count stays.
    """
    format2._id(candidate, format2._CANDIDATE)
    root = Path(root)
    path, lock = _paths(root)
    try:
        with memory.lease(lock, 'notice', deadline, acquire_deadline=deadline):
            def check():
                memory.check(deadline, memory.held)

            check()
            counts = read(memory, root, deadline)
            count = shown(counts, candidate)
            if count >= TIMES:
                return None
            count += 1
            _write(memory, root, dict(counts, **{candidate: count}), check)
            if count == TIMES:
                notice = path.with_name('conflict-' + candidate + '.json')
                try:
                    files._unlink(notice, lambda: files._access(check, memory.fence.check, notice))
                except (OSError, locks.LostLock, locks.LockBusy):
                    pass  # The count already rules the notice out.
            return count
    except (locks.LockBusy, locks.LostLock, OSError, RuntimeError, ValueError):
        return None
