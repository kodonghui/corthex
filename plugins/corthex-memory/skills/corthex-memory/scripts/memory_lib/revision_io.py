"""Internal C2 layer reservations and fresh progress merges; no activation.

Callers own leases and pass Reservation.check before each effect. A reservation
is durable before it is returned and is never rolled back after a failed effect.
Metadata recovery publishes a fresh epoch before exposing any restored proof.
"""
import copy
import os
from pathlib import Path

from . import files, format2, locks, fence_plan
from .c2_store import C2Store


def guard(memory, root, deadline, curator=False):
    if not isinstance(memory, C2Store):
        raise TypeError('format-2 binding required')
    root = Path(root)
    if root.parent != memory.folder / 'projects':
        raise ValueError('invalid project root')
    required = [('layer', 'layer.lock')]
    if curator:
        required.append(('curation', 'curation.lock'))
    bound = []
    for kind, name in required:
        candidates = [lease for lease in memory.held if isinstance(lease, locks.Lock) and
                      lease.path == root / name and lease.policy == locks.POLICIES[kind] and
                      lease.device == memory.device]
        if len(candidates) != 1 or not candidates[0].token:
            raise locks.LostLock()
        bound.append((candidates[0], candidates[0].token))

    def check():
        for lease, token in bound:
            if not any(current is lease for current in memory.held) or lease.token != token:
                raise locks.LostLock()
        memory.check(deadline, memory.held)
        memory.fence.check(root / 'curation.json')
        memory.fence.check(root / 'curation.json.bak')
        memory.check(deadline, memory.held)

    check()
    return check


def _read(memory, path, deadline):
    return format2.parse_curation(files._retry(lambda: memory.fence.read(path, deadline), deadline))


def _publish_recovery(memory, root, value, deadline, check, recheck=True):
    path = root / 'curation.json'
    ready = []
    temporary = files._temporary(path, format2.curation_bytes(value), True, check=check,
                                 path_check=memory.fence.check, ready=ready.append)
    published = []

    def move():
        check()
        if recheck:
            try:
                return _read(memory, path, deadline)
            except files._RESTORABLE:
                pass
        files._access(check, memory.fence.check, path, temporary)
        ready[0]()
        os.replace(str(temporary), str(path))
        published.append(True)
        return value

    try:
        result = files._retry(move, deadline)
        if published:
            # The only good backup stays untouched until the new-epoch primary
            # is visible. A cleanup failure can never expose its old proof.
            files._unlink(path.with_name(path.name + '.bak'), check)
            memory.note('restored')
        return result
    finally:
        if not published:
            files._unlink(temporary, ready[0])


def read(memory, root, deadline):
    root = Path(root)
    check = guard(memory, root, deadline)
    path = root / 'curation.json'
    try:
        return _read(memory, path, deadline)
    except files._RESTORABLE as original:
        try:
            value = _read(memory, path.with_name(path.name + '.bak'), deadline)
        except files._RESTORABLE:
            raise original
        # A layer-only forget must never restore progress or acquire the
        # earlier curation lease while a curator waits for its API answer.
        if not any(x.path == root / 'curation.lock' for x in memory.held):
            raise files.RestoreNeeded() from None
        check = guard(memory, root, deadline, curator=True)
        return _publish_recovery(memory, root, fence_plan.rotate(value), deadline, check)


def rebuild(memory, root, value, deadline):
    """Publish reconstructed progress only when neither current copy parses."""
    root = Path(root)
    check = guard(memory, root, deadline, curator=True)
    for path in (root / 'curation.json', root / 'curation.json.bak'):
        try:
            _read(memory, path, deadline)
        except files._RESTORABLE:
            continue
        raise ValueError('readable progress must not be rebuilt')
    return _publish_recovery(memory, root, fence_plan.rotate(value), deadline, check, recheck=False)


class Reservation:
    def __init__(self, memory, root, value, deadline, check):
        self._memory, self._root, self._deadline, self._guard = memory, root, deadline, check
        self._value = copy.deepcopy(value)
        self._proof = fence_plan.snapshot(value)

    @property
    def progress(self):
        return copy.deepcopy(self._value)

    def check(self):
        self._guard()
        if not fence_plan.matches(read(self._memory, self._root, self._deadline), self._proof):
            raise fence_plan.Stale()
        self._guard()


def reserve(memory, root, expected, targets, deadline, run_id=None):
    """Reserve affected keys; run-bearing applies also require curation ownership."""
    root = Path(root)
    check = guard(memory, root, deadline, curator=run_id is not None)
    fresh = read(memory, root, deadline)
    value = fence_plan.advance(fresh, expected, targets, run_id)
    files.replace_bytes(root / 'curation.json', format2.curation_bytes(value),
                        check=check, path_check=memory.fence.check)
    reservation = Reservation(memory, root, value, deadline, check)
    reservation.check()
    return reservation


def update_progress(memory, root, expected, changes, deadline):
    """Merge intended progress fields into fresh metadata, preserving its fence."""
    root = Path(root)
    check = guard(memory, root, deadline, curator=True)
    fresh = read(memory, root, deadline)
    if not fence_plan.matches(fresh, expected):
        raise fence_plan.Stale()
    if not isinstance(changes, dict) or 'fence' in changes:
        raise ValueError('progress merge must preserve the fence')
    value = copy.deepcopy(fresh)
    value.update(copy.deepcopy(changes))
    data = format2.curation_bytes(value)
    if value['applies'] < fresh['applies']:
        raise ValueError('applies must not go backwards')
    files.replace_bytes(root / 'curation.json', data, check=check, path_check=memory.fence.check)
    check()
    return value
