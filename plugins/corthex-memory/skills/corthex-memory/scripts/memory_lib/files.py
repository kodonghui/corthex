"""Stage 05 file primitives. Callers hold the required locks (TASK-003).

No function creates a parent folder or logs exception text. Readers close files
before restoring. `report(code, count)` hands safe notices to TASK-005's logger;
no logger is installed here. JSONL rewrite callers must carry concurrent appends
over under their file lock, and serialize rewrites under the layer lock.
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

from .base import json_bytes, private_open
from . import clock, locks

_WINDOWS = os.name == "nt"
_RESTORABLE = (FileNotFoundError, ValueError, UnicodeError)


class RestoreNeeded(RuntimeError):
    """A readable backup requires the caller to take the record's write lock."""

    def __init__(self):
        super().__init__("backup restoration requires the record lock")


def _retry(operation, deadline=None):
    """Retry a Windows sharing failure until the caller or one-second limit."""
    limit = clock.now() + 1.0
    deadline = limit if deadline is None else min(deadline, limit)
    while True:
        try:
            return operation()
        except PermissionError:
            left = deadline - clock.now()
            if not _WINDOWS or left <= 0:
                raise
            time.sleep(min(0.02, left))


def fence_read(memory, path, deadline):
    """A file's bytes through the store's fence, without a lease.

    A file that another process is replacing on Windows is read again, for up
    to `_retry`'s second and not past the deadline, and a deadline that passes
    meanwhile is `LockBusy`, as when the read itself finds it passed. Elsewhere
    a refused read is an error, also after the deadline.
    """
    try:
        return _retry(lambda: memory.fence.read(path, deadline), deadline)
    except PermissionError:
        if _WINDOWS and clock.now() >= deadline:
            raise locks.LockBusy() from None
        raise


def _checked(check, operation):
    if check is not None:
        check()
    return operation()


def _unlink(path, check=None):
    try:
        _retry(lambda: _checked(check, path.unlink))
    except FileNotFoundError:
        pass


def delete_file(path, check=None):
    """Delete a whole file and its backup/temps while its caller holds its lock.

    Remove recovery artifacts first so a failed cleanup keeps the original.
    Match temp names literally, even when the file name has glob characters.
    Each Windows sharing failure uses the same one-second retry as moves.
    """
    path = Path(path)
    _unlink(path.with_name(path.name + ".bak"), check)
    try:
        siblings = _retry(lambda: list(path.parent.iterdir()))
    except FileNotFoundError:
        siblings = []
    for sibling in siblings:
        if (sibling.name.startswith(path.name + ".") and sibling.name.endswith(".tmp")
                and len(sibling.name) >= len(path.name) + 5):
            _unlink(sibling, check)
    _unlink(path, check)


def _sync(fd):
    if sys.platform == "darwin":
        try:
            import fcntl
            fcntl.fcntl(fd, fcntl.F_FULLFSYNC)
            return
        except (ImportError, AttributeError, OSError):
            pass
    os.fsync(fd)


def _access(check, path_check, *paths):
    if check is not None:
        check()
    if path_check is not None:
        for path in paths:
            path_check(path)
        if check is not None:
            check()


def _temporary(path, data, durable, check=None, path_check=None, ready=None):
    _access(check, path_check, path)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    temporary = Path(name)
    def guard(policy=check):
        _access(policy, path_check, temporary)
        info = temporary.lstat()
        if (info.st_dev, info.st_ino) != identity:
            raise RuntimeError("temporary identity changed")
    identity = (os.fstat(fd).st_dev, os.fstat(fd).st_ino)
    try:
        with os.fdopen(fd, "wb", buffering=0) as stream:
            if os.name != "nt":
                guard()
                os.fchmod(stream.fileno(), 0o600)
            chunks = iter((data,)) if isinstance(data, (bytes, bytearray, memoryview)) else iter(data)
            try:
                for chunk in chunks:
                    guard()
                    if stream.write(chunk) != len(chunk):
                        raise OSError("short temporary write")
            finally:
                if hasattr(chunks, "close"):
                    chunks.close()
            guard()
            stream.flush()
            if durable:
                guard()
                _sync(stream.fileno())
        guard()
        if ready is not None:
            ready(guard)
        return temporary
    except BaseException:
        _unlink(temporary, guard if path_check is not None else None)
        raise


def _backup(path, backup, check=None, path_check=None):
    guard = lambda: _access(check, path_check, path, backup)
    _unlink(backup, guard)
    try:
        _checked(guard, lambda: os.link(str(path), str(backup)))
    except OSError:
        # A copied backup becomes visible only after it is complete and durable.
        def chunks():
            guard()
            with _retry(lambda: _checked(guard, lambda: path.open("rb"))) as source:
                while True:
                    guard()
                    chunk = source.read(64 * 1024)
                    if not chunk:
                        break
                    yield chunk
        ready = []
        temporary = _temporary(backup, chunks(), True, check=guard, path_check=path_check, ready=ready.append)
        try:
            _retry(lambda: _checked(ready[0], lambda: os.replace(str(temporary), str(backup))))
        finally:
            _unlink(temporary, None if path_check is None else ready[0])
    if os.name != "nt":
        _checked(guard, lambda: backup.chmod(0o600))


def replace_bytes(path, data, rebuildable=False, check=None, *, path_check=None):
    """Replace using a same-directory temporary, then backup, move, cleanup.

    A failed replacement preserves the old target and its backup. A process
    stopped after the move leaves the new target and the old backup whole.
    Rebuildable files omit fsync and the backup, as stage 05 specifies.
    """
    path = Path(path)
    ready = []
    temporary = _temporary(path, data, not rebuildable, check=check, path_check=path_check, ready=ready.append)
    backup = path.with_name(path.name + ".bak")
    def guard():
        _access(check, path_check, path, backup)
        ready[0]()
    try:
        if not rebuildable and path.exists():
            _backup(path, backup, check=check, path_check=path_check)
        _retry(lambda: _checked(guard, lambda: os.replace(str(temporary), str(path))))
        if not rebuildable:
            _unlink(backup, lambda: _access(check, path_check, backup))
    finally:
        _unlink(temporary, None if path_check is None else ready[0])


def write_json(path, record, table, rebuildable=False, check=None, *, path_check=None):
    replace_bytes(path, json_bytes(record, table), rebuildable, check=check, path_check=path_check)


def append_jsonl(path, record, table, report=None, check=None, deadline=None, *, reader=None):
    """Append an already-redacted object with exactly one unbuffered write.

    Caller holds the file lock through recovery, the size/last-byte read, write
    and any rollback. A missing primary with a readable backup is restored
    before opening for append. A short write truncates to the prior fstat size
    before failing; this is correct only while that caller keeps the record
    lock. No fsync: bytes are handed to the OS, as the append contract requires.
    Optional check fences shared mutations; deadline caps recovery/open retries.
    """
    data = json_bytes(record, table, compact=True)
    path = Path(path)
    if not path.exists() and path.with_name(path.name + ".bak").exists():
        read_jsonl(path, report, holding_lock=True, check=check, deadline=deadline, reader=reader)
    fd = _retry(lambda: _checked(check, lambda: private_open(path, os.O_CREAT | os.O_RDWR | os.O_APPEND)), deadline)
    try:
        size = os.fstat(fd).st_size
        if size:
            os.lseek(fd, -1, os.SEEK_END)
            if os.read(fd, 1) != b"\n":
                data = b"\n" + data
        if _checked(check, lambda: os.write(fd, data)) != len(data):
            _checked(check, lambda: os.ftruncate(fd, size))
            raise OSError("short append")
    finally:
        os.close(fd)


def _invalid_constant(value):
    raise ValueError("non-finite JSON number")


def _object(data):
    value = json.loads(data.decode("utf-8"), parse_constant=_invalid_constant)
    if not isinstance(value, dict):
        raise ValueError("a record must be an object")
    return value


def _read(path, parse, report, holding_lock=False, check=None, deadline=None, reader=None):
    path = Path(path)
    read = (lambda candidate: candidate.read_bytes()) if reader is None else reader
    try:
        return parse(_retry(lambda: read(path), deadline))
    except _RESTORABLE as original:
        backup = path.with_name(path.name + ".bak")
        try:
            value = parse(_retry(lambda: read(backup), deadline))
        except _RESTORABLE:
            raise original
        if not holding_lock:
            raise RestoreNeeded() from None
        def restore():
            # A writer may have finished after the first read. Recheck before
            # each move attempt, including after a Windows sharing failure.
            try:
                return parse(_retry(lambda: read(path), deadline))
            except _RESTORABLE:
                try:
                    if check is not None:
                        check()
                    os.replace(str(backup), str(path))
                except FileNotFoundError:
                    return parse(_retry(lambda: read(path), deadline))
                if report:
                    report("restored", None)
                return value
        return _retry(restore, deadline)


def read_record(path, parse, report=None, holding_lock=False, check=None, deadline=None,
                *, reader=None):
    """Read with a pure parser; only a caller holding the lock may restore.

    The default reader supplies bytes. A bounded reader may instead supply
    parsed input, but must close the file before returning so moves work on
    Windows. A parser rejects invalid input with ValueError/UnicodeError. Policy
    refusals use a different exception so they never restore older contents.
    check, when supplied, fences each restoration move by current ownership.
    deadline caps all Windows read/recovery retries at the caller's deadline.
    """
    return _read(path, parse, report, holding_lock, check, deadline, reader)


def read_json(path, report=None, holding_lock=False, check=None, deadline=None):
    """Read an object; restore only while the caller holds this record's lock.

    An unlocked reader raises RestoreNeeded for a readable backup and changes
    nothing. Only pass holding_lock=True while holding that record's write lock.
    """
    return read_record(path, _object, report, holding_lock, check, deadline)


def _lines(data):
    entries, damaged = [], 0
    lines = data.split(b"\n")
    tail = lines.pop()
    for line in lines:
        try:
            entries.append(_object(line))
        except (ValueError, UnicodeError):
            damaged += 1
    if tail:
        damaged += 1
    return entries, damaged


def read_jsonl(path, report=None, holding_lock=False, check=None, deadline=None, *, reader=None):
    """Keep complete object lines, skip/count bad lines without guessing.

    Damaged JSONL lines are not a reason to roll the file back to a backup,
    which could discard valid appends. Only pass holding_lock=True while the
    caller holds this record's write lock; a missing file can then restore.
    Without that lock a readable backup raises RestoreNeeded without moving
    files. Permission and other I/O errors never roll back to older content.
    """
    entries, damaged = read_record(path, _lines, report, holding_lock, check, deadline, reader=reader)
    if damaged and report:
        report("damaged-line", damaged)
    return entries
