"""Internal strict history I/O; no recovery, state writer or activation.

The mandatory archive precondition belongs to the caller's complete original
state/privacy snapshot. It receives this exact store/project/reservation and
immutable (epoch, generation, run, line, record hash) requirements. It must
raise on refusal and return only None on success. This module
proves bytes/durability/ownership, never source eligibility or undo authority.
"""
import contextlib
import hashlib
import os
from pathlib import Path
import stat

from . import fence_plan, files, locks, revision_io, state_types


class AppendFailed(RuntimeError):
    def __init__(self, rolled_back=False):
        super().__init__('history append incomplete or durability unconfirmed')
        self.rolled_back = rolled_back
        self.uncertain = not rolled_back


def _project_check(memory, root, check):
    def guarded():
        check()
        path = root/'layer/deleted.json'
        for candidate in (path, path.with_name(path.name+'.bak')):
            if memory.fence.check(candidate) is not None:
                raise fence_plan.Stale()
        check()
    guarded()
    return guarded


@contextlib.contextmanager
def _opened(memory, root, deadline, check, writable=False):
    path = root/'state-history.jsonl'
    check()
    memory.fence.check(path.with_name(path.name+'.bak'))
    info = memory.fence.check(path)
    if info is None:
        raise files.RestoreNeeded()
    if not stat.S_ISREG(info.st_mode):
        raise locks.LostLock()
    flags = (os.O_RDWR | os.O_APPEND) if writable else os.O_RDONLY
    flags |= getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    try:
        fd = files._retry(lambda: os.open(str(path), flags), deadline)
    except FileNotFoundError:
        raise files.RestoreNeeded() from None
    identity = (info.st_dev, info.st_ino)

    def guard():
        check()
        current, opened = memory.fence.check(path), os.fstat(fd)
        if (current is None or not stat.S_ISREG(opened.st_mode) or
                (current.st_dev, current.st_ino) != identity or
                (opened.st_dev, opened.st_ino) != identity):
            raise locks.LostLock()
        check()

    try:
        guard()
        yield fd, guard
    finally:
        os.close(fd)


def _bytes(fd, check):
    check()
    before = os.fstat(fd)
    os.lseek(fd, 0, os.SEEK_SET)
    chunks = []
    while True:
        check()
        chunk = os.read(fd, 64*1024)
        if not chunk:
            break
        chunks.append(chunk)
    check()
    after = os.fstat(fd)
    data = b''.join(chunks)
    stamp = lambda v: (v.st_size, v.st_mtime_ns, v.st_ctime_ns)
    if stamp(before) != stamp(after) or len(data) != after.st_size:
        raise fence_plan.Stale()
    return data


def _strict(data):
    try:
        return state_types.parse_history(data)
    except (ValueError, UnicodeError):
        raise files.RestoreNeeded() from None


def read(memory, root, deadline):
    """Read one entire primary under its original layer lease; never restore."""
    root = Path(root)
    check = _project_check(memory, root, revision_io.guard(memory, root, deadline))
    with _opened(memory, root, deadline, check) as (fd, guard):
        records = _strict(_bytes(fd, guard))
        guard()
        return records


def _binding(memory, root, reservation, records, deadline, archive_precondition):
    if (type(reservation) is not revision_io.Reservation or reservation._memory is not memory or
            reservation._root != root):
        raise ValueError('history reservation binding mismatch')
    if not callable(archive_precondition):
        raise TypeError('archive precondition required')
    original = revision_io.guard(memory, root, deadline, curator=True)
    progress = reservation.progress
    fence = progress['fence']
    requirements = []
    for record in records:
        value = record.value
        if (value['epoch'] != fence['epoch'] or value['generation'] != fence['generation'] or
                value['device'] != memory.device or
                any(fence['revisions'].get(key) != fence['generation']
                    for key in ('line:'+value['line'], 'run:'+value['run']))):
            raise fence_plan.Stale()
        requirements.append((value['epoch'], value['generation'], value['run'], value['line'], record.sha256))
    requirements = tuple(requirements)

    def check():
        original()
        reservation.check()
        if archive_precondition(memory, root, reservation, requirements) is not None:
            raise TypeError('archive precondition must return only None')
        original()
        reservation.check()

    return _project_check(memory, root, check)


class DurableHistory:
    """FD-scoped proof only; leaving its append context permanently revokes it."""
    def __init__(self, fd, check, data, records):
        self._fd, self._guard, self._live = fd, check, True
        self._size, self._prefix = len(data), hashlib.sha256(data).digest()
        self._hashes = tuple(record.sha256 for record in records)

    @property
    def hashes(self):
        return self._hashes

    def check(self):
        if not self._live:
            raise locks.LostLock()
        try:
            data = _bytes(self._fd, self._guard)
            _strict(data)
            if len(data) < self._size or hashlib.sha256(data[:self._size]).digest() != self._prefix:
                raise fence_plan.Stale()
            self._guard()
            files._sync(self._fd)
            self._guard()
            if _bytes(self._fd, self._guard) != data:
                raise fence_plan.Stale()
            self._size, self._prefix = len(data), hashlib.sha256(data).digest()
        except BaseException:
            self._live = False
            raise


def _short_rollback(fd, before, data, count, check):
    if type(count) is not int or not 0 <= count < len(data):
        return False
    # Never truncate another holder's append, replacement or changed prefix.
    if _bytes(fd, check) != before+data[:count]:
        return False
    check()
    os.ftruncate(fd, len(before))
    check()
    files._sync(fd)
    check()
    return _bytes(fd, check) == before


@contextlib.contextmanager
def append(memory, root, reservation, values, deadline, *, archive_precondition):
    """Append all required records once, then lend a live durability receipt.

    A failure lends no receipt and never authorizes state changes. Complete
    unused staged rows can remain. Recovery and privacy scrubbing are separate.
    """
    records = tuple(state_types.HistoryRecord(state_types.history_record_bytes(value)) for value in values)
    data = b''.join(record.raw for record in records)
    root = Path(root)
    check = _binding(memory, root, reservation, records, deadline, archive_precondition)
    with _opened(memory, root, deadline, check, writable=True) as (fd, guard):
        before = _bytes(fd, guard)
        _strict(before)
        guard()
        try:
            count = os.write(fd, data) if data else 0
            if count != len(data):
                rolled_back = _short_rollback(fd, before, data, count, guard)
                raise AppendFailed(rolled_back)
            guard()
            if _bytes(fd, guard) != before+data:
                raise fence_plan.Stale()
            files._sync(fd)
            guard()
            if _bytes(fd, guard) != before+data:
                raise fence_plan.Stale()
        except AppendFailed:
            raise
        except Exception as error:
            raise AppendFailed() from error
        receipt = DurableHistory(fd, guard, before+data, records)
        try:
            receipt.check()
            yield receipt
        finally:
            receipt._live = False
