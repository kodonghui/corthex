"""Bound C1 maintenance reads, leases and metadata-only diagnostics. No provisioning."""
import contextlib
import stat
from pathlib import Path

from . import base, clock, diagnostics, locks, store

OPERATION_SECONDS = 1.0
PHASE_SECONDS = 300.0
CHUNK = 64 * 1024


class UnsafePath(locks.LostLock):
    """A candidate alias is preserved; root replacement is a separate LostLock."""


class PathFence:
    def __init__(self, root):
        if not root.is_absolute():
            raise base.MemoryHomeInvalid()
        self.root = root.resolve()
        self.identity = self._identity(self.root.lstat())

    @staticmethod
    def _identity(info):
        return info.st_dev, info.st_ino

    def check(self, path):
        if self._identity(self.root.lstat()) != self.identity:
            raise locks.LostLock()
        try:
            parts = Path(path).relative_to(self.root).parts
        except ValueError:
            raise UnsafePath() from None
        if ".." in parts:
            raise UnsafePath()
        current, info = self.root, self.root.lstat()
        for index, part in enumerate(parts):
            current = current / part
            try:
                info = current.lstat()
            except FileNotFoundError:
                return None
            if (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400 or
                    index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode)):
                raise UnsafePath()
        return info

    def read(self, path, deadline):
        self.check(path)
        chunks = []
        with path.open("rb") as source:
            while True:
                if clock.now() >= deadline:
                    raise locks.LockBusy()
                self.check(path)
                chunk = source.read(CHUNK)
                if not chunk:
                    break
                chunks.append(chunk)
        self.check(path)
        return b"".join(chunks)


class BoundDiagnostics(diagnostics.Diagnostics):
    def _path_check(self, path):
        self.store.fence.check(path)

    def _reader(self, path, deadline):
        return self.store.fence.read(path, deadline)

    def _lock(self, path, device):
        return self.store._lock(path, "log", device)

    def _stamp(self, path, deadline=None):
        return diagnostics.Diagnostics._stamp(path, deadline, check=self._path_check)

    def _append(self, *args, **kwargs):
        if self.store.held:
            return False
        return super()._append(*args, **kwargs)


class WorkerStore(store.MemoryStore):
    def __init__(self, folder=None, expected_device=None):
        deadline = clock.now() + OPERATION_SECONDS
        super().__init__(folder)
        if not self.folder.exists():
            raise store.StoreUnavailable("no-store")
        if expected_device is not None and not store.DEVICE.fullmatch(expected_device):
            raise ValueError("invalid expected device")
        self.fence = PathFence(self.folder)
        self.folder = self.fence.root
        self.expected, self.pin, self.held, self.notes = expected_device, None, [], []
        self.logger = BoundDiagnostics(self)
        header = self.logger.read_gate(deadline, self.note)
        self.device, self.pin = header["device"], self.logger._ready[1]
        deadline = clock.now() + OPERATION_SECONDS
        self.config = self.configuration(self.note, deadline=deadline)
        self.check(deadline)
        self.flush()

    def _path_check(self, path):
        self.fence.check(path)

    def _lock(self, path, kind, device):
        return locks.Lock(path, kind, device, path_check=self._path_check)

    def _read_record(self, path, parse, deadline, report, **options):
        return super()._read_record(path, parse, deadline, report,
                                   reader=lambda p: self.fence.read(p, deadline), **options)

    def record(self, report=None, *, deadline, **options):
        def policy(value):
            if self.expected is not None and value["device"] != self.expected:
                raise locks.LostLock()
            self.check(deadline)
        return super().record(report, deadline=deadline, precondition=policy, **options)

    def check(self, deadline, leases=()):
        self._deadline(deadline)
        if clock.now() >= deadline:
            raise locks.LockBusy()
        for lease in leases:
            lease.check()
        if self.pin is not None and self.logger._stamp(self.folder / "store.json", deadline) != self.pin:
            raise locks.LostLock()
        for lease in leases:
            lease.check()
        if clock.now() >= deadline:
            raise locks.LockBusy()

    def _guard(self, lock, deadline, recording=False):
        return lambda: self.check(deadline, (lock,))

    @contextlib.contextmanager
    def lease(self, path, kind, deadline, step="restore"):
        self.check(deadline)
        lease = self._lock(path, kind, self.device).acquire(deadline, wait=False)
        self.held.append(lease)
        try:
            self.check(deadline, self.held)
            yield lease
        finally:
            lease.release(report=lambda error, count: self.note(error, count, step))
            self.held.remove(lease)
            self.flush()

    def note(self, error, count=None, step="restore"):
        self.notes.append((error, count, step))

    def failure(self, error, step="restore", count=None):
        return self.logger.failure(error, step, clock.now() + OPERATION_SECONDS, count=count)

    def flush(self):
        if not self.held:
            notes, self.notes = self.notes, []
            for error, count, step in notes:
                self.failure(error, step, count)
