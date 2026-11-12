"""TBL-011 retention: the injection log's lines go by their own time once past the retention period (SPEC-009).

The holder of the project's layer lease calls `expire`, as it calls the run
logs' expiry: from release 0.3.0 (TASK-117), a session start's retention of a
format-2 project (`c2_retention`); below 0.3.0 nothing calls it. The hooks append a
session's lines under its raw log file's lock (TASK-091, TASK-094), so a file
is read without that lock, with the leases checked before and after the read
as publishing's reads are, and only a file that changes is read again, with
every check, into a synced temporary file. Only then, under the lock with the
short wait of a raw log's rewrite, are the bytes read checked unchanged, with
the leases checked before that check rather than at each of its steps, so
that the hooks wait briefly; the lines appended meanwhile are carried whole,
and the file is replaced, or deleted when no line is left. A line that cannot
be read, or an unfinished last line that no append completes, goes as in a raw
log's rewrite, and the failure log counts it; a line dated in the future is
kept. A file with nothing to change stays as it is.

Under the same lock a file's backup and temporary copies go, since an append
and recall read a backup only for a missing file; a backup of a missing file
comes back first, as the next append would bring it back, and its lines then
go by their own time. A lock that stays busy waits for the next start; a file
that cannot be read or replaced, as Windows refuses for a file in use, too,
and the failure log notes it.
"""
import hashlib
import itertools
import os
from pathlib import Path
import re
import stat

from . import cleanup, clock, files, injection_log, locks, raw_rewrite, revision_io, run_log, worker_support

NAME = re.compile('(' + cleanup.LOG + r')\.jsonl\Z')
COPY = re.compile('(' + cleanup.LOG + r')\.jsonl(?:\.bak|(?:\.bak)?\.[a-z0-9_]{8}\.tmp)\Z')


def expire(memory, root, deadline, *, when, days):
    """Delete the injection log lines whose own time is past retention; returns how many.

    Nothing is read or deleted through a link: a linked folder raises
    UnsafePath, and a session whose file or copy is a link or a folder is
    left. A lost lease stops it, and what is left waits for the next start.
    """
    root = Path(root)
    check = revision_io.guard(memory, root, deadline)
    cutoff = run_log._cutoff(when, days)[0]
    folder = root / 'injections'
    if memory.fence.check(folder) is None:
        check()
        return 0
    sessions = {}
    for name in run_log._names(folder):
        match = NAME.fullmatch(name) or COPY.fullmatch(name)
        if match:
            sessions.setdefault(match.group(1), []).append(folder / name)
    removed = 0
    for log in sorted(sessions):
        check()
        path = folder / (log + '.jsonl')
        try:
            removed += _expire(memory, root, path, [name for name in sessions[log] if name != path], cutoff, check,
                               deadline)
        except worker_support.UnsafePath:
            continue
        except locks.LockBusy:
            check()   # a passed deadline goes on; a raw log lock that stays busy leaves the session for the next start
        except locks.LostLock:
            raise
        except (OSError, RuntimeError, ValueError, TypeError, OverflowError) as error:
            memory.note(error, step='retention')
    check()
    return removed


def _lease(memory, root, log, deadline):
    return memory.lease(root / 'raw' / (log + '.lock'), 'raw', deadline, 'retention',
                        acquire_deadline=clock.now() + raw_rewrite.RAW_LEASE_WAIT_SECONDS)


def _expire(memory, root, path, copies, cutoff, check, deadline):
    """One session's file and its copies, as listed: the number of its lines that went."""
    log = path.name[:-len('.jsonl')]
    for candidate in [path] + copies:
        info = memory.fence.check(candidate)
        if info is not None and not stat.S_ISREG(info.st_mode):
            raise worker_support.UnsafePath()
    if memory.fence.check(path) is None:
        with _lease(memory, root, log, deadline):
            def fenced(candidate):
                return lambda: files._access(check, memory.fence.check, candidate)

            def probe(candidate):
                for _ in raw_rewrite._lines(raw_rewrite._chunks(memory, candidate, fenced(candidate))):
                    pass
                return True
            backup = path.with_name(path.name + '.bak')
            if memory.fence.check(path) is None and memory.fence.check(backup) is not None:
                files.read_record(path, lambda value: value, memory.note, holding_lock=True,
                                  check=lambda: files._access(check, memory.fence.check, path, backup),
                                  deadline=deadline, reader=probe)
            for candidate in copies:
                files._unlink(candidate, fenced(candidate))
        if memory.fence.check(path) is None:
            return 0
        copies = []
    original = memory.fence.check(path)
    if original is None:
        return 0
    if not stat.S_ISREG(original.st_mode):
        raise worker_support.UnsafePath()
    identity, expected = (original.st_dev, original.st_ino), None

    def unlocked():
        # The deadline before the file's metadata, as a raw log's rewrite checks. The first read, and the check of
        # the bytes read under the lock, write nothing, so at each of their steps only these are checked, and the
        # leases before and after them: a lease lost during the first read stops the pass before the next file is
        # read or anything is written.
        if clock.now() >= deadline:
            raise locks.LockBusy()
        current = memory.fence.check(path)
        if (current is None or (current.st_dev, current.st_ino) != identity or
                expected is not None and cleanup.stamp(current) != expected):
            raise locks.LostLock()

    def guarded():
        unlocked()
        check()   # then the leases, at each step of reading into the temporary file and of every write

    removed = damaged = 0
    tail = b''

    def scan(guard, digest):
        """The kept lines of the bytes that the first read saw, counting the others."""
        nonlocal removed, damaged, tail
        removed = damaged = 0
        tail = b''
        for line, complete in raw_rewrite._lines(raw_rewrite._chunks(memory, path, guard, size=original.st_size,
                                                                      digest=digest)):
            if not complete:
                tail = line
                continue
            try:
                value = injection_log.parse_line(line[:-1])
            except (ValueError, UnicodeError):
                damaged += 1
                continue
            if value['at'] < cutoff:
                removed += 1
            else:
                yield line

    for _ in scan(unlocked, None):
        pass
    rewrite = bool(removed or damaged or tail or original.st_size == 0)
    if not rewrite and not copies:
        return 0
    ready, temporary = [], None
    if rewrite:
        # Only a file that changes is read again, with every check, into the temporary file, without holding its
        # lines.
        again = hashlib.sha256()
        temporary = files._temporary(path, raw_rewrite._batches(scan(guarded, again)), True, check=guarded,
                                     path_check=memory.fence.check, ready=ready.append)
    try:
        if temporary is not None:
            staged = cleanup.stamp(temporary.stat())

        def staged_check():
            ready[0]()
            if cleanup.stamp(temporary.stat()) != staged:
                raise RuntimeError('temporary changed')

        with _lease(memory, root, log, deadline):
            guarded()
            current = memory.fence.check(path)
            if (current is None or (current.st_dev, current.st_ino) != identity or
                    current.st_size < original.st_size):
                raise locks.LostLock()
            expected = cleanup.stamp(current)
            if temporary is not None:
                # The bytes read again are checked unchanged with the first read's checks at each step, since this
                # writes nothing, so that the hooks, which wait for this lock briefly, wait as briefly; the leases are
                # checked before it and at every later step.
                verified = hashlib.sha256()
                for _ in raw_rewrite._chunks(memory, path, unlocked, size=original.st_size, digest=verified):
                    pass
                if verified.digest() != again.digest():
                    raise locks.LostLock()
            for candidate in copies:
                files._unlink(candidate, lambda p=candidate: files._access(guarded, memory.fence.check, p))
            grew = current.st_size > original.st_size
            if temporary is None or not (removed or damaged or tail and not grew or original.st_size == 0):
                return 0   # only copies went, or only a line being appended was unfinished
            if grew:
                # The lines appended meanwhile, and the first read's unfinished last line, go on whole; those that
                # cannot be read are counted, as a raw log's rewrite counts them.
                def carried():
                    nonlocal damaged
                    suffix = raw_rewrite._chunks(memory, path, guarded, start=original.st_size,
                                                 size=current.st_size - original.st_size)
                    for line, complete in raw_rewrite._lines(itertools.chain((tail,), suffix)):
                        try:
                            if not complete:
                                raise ValueError('unfinished injection line')
                            injection_log.parse_line(line[:-1])
                        except (ValueError, UnicodeError):
                            damaged += 1
                        yield line
                batches = raw_rewrite._batches(carried())
                try:
                    with files._retry(lambda: files._checked(staged_check, lambda: temporary.open('ab', buffering=0)),
                                      deadline) as target:
                        info = os.fstat(target.fileno())
                        if not stat.S_ISREG(info.st_mode) or cleanup.stamp(info) != staged:
                            raise RuntimeError('temporary descriptor changed')
                        for chunk in batches:
                            if files._checked(staged_check, lambda: target.write(chunk)) != len(chunk):
                                raise OSError('short carried write')
                            staged = cleanup.stamp(os.fstat(target.fileno()))
                        staged_check()
                        files._sync(target.fileno())
                finally:
                    batches.close()
            elif tail:
                damaged += 1
            staged_check()
            if temporary.stat().st_size == 0:
                files._unlink(path, staged_check)
            else:
                backup = path.with_name(path.name + '.bak')
                files._backup(path, backup, check=guarded, path_check=memory.fence.check)
                files._retry(lambda: files._checked(staged_check, lambda: os.replace(str(temporary), str(path))),
                             deadline)
                expected = None
                files._unlink(backup, lambda: files._access(check, memory.fence.check, backup))
    finally:
        if temporary is not None:
            files._unlink(temporary, lambda: ready[0](check))
    if damaged:
        memory.note('damaged-line', damaged, 'retention')
    return removed
