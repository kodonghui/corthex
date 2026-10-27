"""Stage 05 file primitives. Callers hold the required locks (TASK-003).

No function creates a parent folder or logs exception text. Readers close files
before restoring. `report(code, count)` hands safe notices to TASK-005's logger;
no logger is installed here. JSONL rewrite callers must carry concurrent appends
over under their file lock, and serialize rewrites under the layer lock.
"""

import json
import os
import tempfile
import time
from pathlib import Path

from .base import json_bytes, private_open


def _retry(operation):
    """Retry a Windows sharing/access failure for at most one second."""
    deadline = time.monotonic() + 1.0
    while True:
        try:
            return operation()
        except PermissionError:
            left = deadline - time.monotonic()
            if os.name != "nt" or left <= 0:
                raise
            time.sleep(min(0.02, left))


def _checked(check, operation):
    if check is not None:
        check()
    return operation()


def _unlink(path, check=None):
    try:
        _retry(lambda: _checked(check, path.unlink))
    except FileNotFoundError:
        pass


def _temporary(path, data, durable):
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            if os.name != "nt":
                os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
            stream.flush()
            if durable:
                os.fsync(stream.fileno())
        return temporary
    except BaseException:
        _unlink(temporary)
        raise


def _backup(path, backup, check=None):
    _unlink(backup, check)
    try:
        _checked(check, lambda: os.link(str(path), str(backup)))
    except OSError:
        # A copied backup becomes visible only after it is complete and durable.
        temporary = _checked(check, lambda: _temporary(backup, path.read_bytes(), True))
        try:
            _retry(lambda: _checked(check, lambda: os.replace(str(temporary), str(backup))))
        finally:
            _unlink(temporary)
    if os.name != "nt":
        _checked(check, lambda: backup.chmod(0o600))


def replace_bytes(path, data, rebuildable=False, check=None):
    """Replace using a same-directory temporary, then backup, move, cleanup.

    A failed replacement preserves the old target and its backup. A process
    stopped after the move leaves the new target and the old backup whole.
    Rebuildable files omit fsync and the backup, as stage 05 specifies. An
    optional caller guard fences shared mutations, including every move retry.
    """
    path = Path(path)
    temporary = _checked(check, lambda: _temporary(path, data, not rebuildable))
    backup = path.with_name(path.name + ".bak")
    try:
        if not rebuildable and path.exists():
            _backup(path, backup, check=check)
        _retry(lambda: _checked(check, lambda: os.replace(str(temporary), str(path))))
        if not rebuildable:
            _unlink(backup, check)
    finally:
        _unlink(temporary)


def write_json(path, record, table, rebuildable=False, check=None):
    replace_bytes(path, json_bytes(record, table), rebuildable, check=check)


def append_jsonl(path, record, table, check=None):
    """Append an already-redacted object with exactly one unbuffered write.

    Caller holds the file lock through the last-byte read and this write. No
    fsync: bytes are handed to the OS, as the append contract requires.
    """
    data = json_bytes(record, table, compact=True)
    fd = _checked(check, lambda: private_open(path, os.O_CREAT | os.O_RDWR | os.O_APPEND))
    try:
        size = os.lseek(fd, 0, os.SEEK_END)
        if size:
            os.lseek(fd, -1, os.SEEK_END)
            if os.read(fd, 1) != b"\n":
                data = b"\n" + data
        if _checked(check, lambda: os.write(fd, data)) != len(data):
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


def _read(path, parse, report):
    path = Path(path)
    try:
        return parse(path.read_bytes())
    except (OSError, ValueError, UnicodeError) as original:
        backup = path.with_name(path.name + ".bak")
        try:
            value = parse(backup.read_bytes())
        except (OSError, ValueError, UnicodeError):
            raise original
        _retry(lambda: os.replace(str(backup), str(path)))
        if report:
            report("restored", None)
        return value


def read_json(path, report=None):
    return _read(path, _object, report)


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


def read_jsonl(path, report=None):
    """Keep complete object lines, skip/count bad lines without guessing.

    Damaged JSONL lines are not a reason to roll the file back to a backup,
    which could discard valid appends. Missing/unreadable files can restore.
    """
    entries, damaged = _read(path, _lines, report)
    if damaged and report:
        report("damaged-line", damaged)
    return entries
