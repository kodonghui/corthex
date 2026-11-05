"""Original ordered leases with an external maintenance-interval precondition.

No process scan can infer that every old host is closed and cannot restart.
The real interval owner supplies that original check; a fixture callback is not
production verification. No migration/initialization/history authority is made.
"""
import contextlib
from dataclasses import dataclass, field
import os
import stat

from . import clock, files, locks, migration_inventory, store


class CleanupPending(locks.LostLock):
    cleanup_pending = True


@dataclass(frozen=True)
class Ownership:
    inventory: migration_inventory.Inventory
    _verify: object = field(repr=False, compare=False)
    _cleanup: list = field(repr=False, compare=False)

    def check(self):
        self._verify()

    @property
    def cleanup_pending(self):
        return self._cleanup[0]


def _same_inventory(before, after, acquired):
    if (before.folder != after.folder or before.headers != after.headers or
            before.projects != after.projects or before.configuration != after.configuration or
            before.leases != after.leases or before.payloads != after.payloads):
        raise locks.LostLock()
    original, current = before._observer, after._observer
    if original.files != current.files or original.records != current.records or set(original.dirs) != set(current.dirs):
        raise locks.LostLock()
    allowed = {}
    for lease, *_ in acquired:
        relative = lease.path.relative_to(before.folder)
        parent = relative.parent.as_posix()
        allowed.setdefault(parent, set()).add(relative.name)
    for name, (identity, names) in original.dirs.items():
        fresh_identity, fresh_names = current.dirs[name]
        if identity != fresh_identity or set(names) - set(fresh_names) or set(fresh_names) - set(names) - allowed.get(name, set()):
            raise locks.LostLock()


@contextlib.contextmanager
def acquire(folder, *, release, when, deadline, verify_quiescence):
    """Own ordinary leases only after the actual interval owner's verification.

    The original callback takes canonical root and immutable store binding, and
    returns only None on verification. It must prove the complete interval, not
    just absence of locks. This port does not supply a real-host coordinator.
    """
    if not callable(verify_quiescence):
        raise TypeError('original maintenance interval check required')
    store.MemoryStore._deadline(deadline)
    before = migration_inventory.observe(folder, release=release, when=when, deadline=deadline)
    root, fence = before.folder, before._observer.fence
    header = store.json_document(before.headers.publications[0][1])
    binding = header['device'], header['made'], header['release'], header['migrating']['started']
    directories = tuple((name, identity) for name, (identity, _) in before._observer.dirs.items())
    original_root, original_identity = fence.root, fence.identity
    pid, acquired = os.getpid(), []
    revoked, bad_path, closed, cleanup = [False], [False], [False], [False]
    admitted = [None]
    issued, failure = False, [None]

    def paths(path):
        try:
            if bad_path[0] or fence.root != original_root or fence.identity != original_identity:
                raise locks.LostLock()
            for name, identity in directories:
                info = fence.check(root / name)
                if info is None or not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != identity:
                    raise locks.LostLock()
            return fence.check(path)
        except Exception:
            bad_path[0] = True
            raise locks.LostLock() from None

    def check():
        try:
            if (revoked[0] or closed[0] or os.getpid() != pid or
                    admitted[0] is not None and admitted[0].revoked):
                raise locks.LostLock()
            if clock.now() >= deadline:
                raise locks.LockBusy()
            paths(root)
            if verify_quiescence(root, binding) is not None:
                raise TypeError('maintenance interval check must return only None')
            paths(root)
            for lease, token, path, policy, device, lease_pid, identity, original_check in acquired:
                if (lease.token != token or lease.path != path or lease.policy != policy or lease.device != device or
                        lease.pid != lease_pid or lease._path_check is not paths):
                    cleanup[0] = True
                    raise locks.LostLock()
                info = paths(path)
                if (info is None or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                        (info.st_dev, info.st_ino) != identity):
                    cleanup[0] = True
                    raise locks.LostLock()
                original_check()
            paths(root)
            if clock.now() >= deadline:
                raise locks.LockBusy()
        except Exception:
            revoked[0] = True
            raise

    try:
        check()
        for project in before.projects:
            info = paths(root / project.folder / 'raw')
            if not project.exists or info is None or not stat.S_ISDIR(info.st_mode):
                raise files.RestoreNeeded()
        for kind, relative in before.leases:
            check()
            path = root / relative
            info = paths(path)
            if info is not None and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
                raise locks.LostLock()
            lease = locks.Lock(path, kind, header['device'], path_check=paths)
            lease.acquire(deadline, wait=False)
            # Retain the original object and token even if a later check fails.
            acquired.append((lease, lease.token, lease.path, lease.policy, lease.device, lease.pid,
                             None, lease.check))
            info = paths(lease.path)
            acquired[-1] = acquired[-1][:6] + ((info.st_dev, info.st_ino), acquired[-1][-1])
            check()
        after = migration_inventory.observe(root, release=release, when=when, deadline=deadline)
        _same_inventory(before, after, acquired)
        admitted[0] = after._observer
        check()
        ownership = Ownership(after, check, cleanup)
        issued = True
        yield ownership
    except BaseException as error:
        failure[0] = error
        raise
    finally:
        closed[0] = True
        if os.getpid() != pid:
            cleanup[0] = bool(acquired)
        else:
            for lease, token, path, policy, device, lease_pid, _, _ in reversed(acquired):
                # Restoration is only to the original cleanup target/token;
                # it never restores effect authority or adopts a fresh lease.
                lease.path, lease.token, lease.policy = path, token, policy
                lease.device, lease.pid, lease._path_check = device, lease_pid, paths
                try:
                    lease.release(report=lambda error, count: cleanup.__setitem__(0, True))
                except Exception:
                    cleanup[0] = True
            if cleanup[0] and (not issued or failure[0] is None):
                raise CleanupPending() from None
