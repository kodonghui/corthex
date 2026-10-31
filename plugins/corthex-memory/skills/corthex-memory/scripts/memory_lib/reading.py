"""Unlocked reads with recovery under the record's matching write lease.

The caller supplies the absolute monotonic deadline of its stage 06 operation;
there is no extra recovery timeout. Healthy reads take no lease. This adapter
does not create directories, choose a device identity or map command errors.
Recovery raises LockOrderError if the caller holds a later lock. Hooks attempt
recovery with no other lease held. Release uses its separate one-second retry
and reports cleanup failures without replacing the read result.
"""


from . import files, locks
from . import clock


def _recover(read, path, lock, deadline, report, before_locked=None,
             finish_recovery=False, **options):
    operation_deadline = None if finish_recovery else deadline
    try:
        return read(path, report=report, deadline=operation_deadline, **options)
    except files.RestoreNeeded:
        pass
    if finish_recovery:
        lock.acquire(deadline, at_least_once=True)
    else:
        lock.acquire(deadline)
    try:
        def check():
            if not finish_recovery and clock.now() >= deadline:
                raise locks.LockBusy()
            lock.check()
            if before_locked is not None:
                before_locked()
                lock.check()
        check()
        return read(path, report=report, holding_lock=True, check=check,
                      deadline=operation_deadline, **options)
    finally:
        lock.release(report=report)


def read_record(path, parse, lock, deadline, report=None, check=None, *, finish_recovery=False,
                reader=None):
    """Recheck and recover with a pure parser while holding the matching lease.

    deadline is required: recording uses its 50ms post-redaction lock wait,
    start memory its 1,000ms deadline, and other callers their own operation's
    deadline (05 Locks, 06 Deadlines). A busy lease fails without moving files.
    Optional check revalidates caller state after acquisition and before moves.
    Recording alone opts into finish_recovery: attempt even after expiry and
    finish acquired recovery with the ordinary one-second sharing retry.
    """
    return _recover(files.read_record, path, lock, deadline, report, before_locked=check,
                    finish_recovery=finish_recovery, parse=parse, reader=reader)


def read_json(path, lock, deadline, report=None, check=None):
    """Read an object, acquiring its caller-supplied lease only for recovery."""
    return _recover(files.read_json, path, lock, deadline, report, before_locked=check)


def read_jsonl(path, lock, deadline, report=None, check=None):
    """Read complete JSONL entries with the same bounded recovery attempt."""
    return _recover(files.read_jsonl, path, lock, deadline, report, before_locked=check)
