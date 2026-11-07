"""Stage 05 leases. Call check() immediately before every protected change.

Acquisition order is process-wide, including pending acquisitions. A lease is
not a transaction: callers still need the apply/tombstone fences of stage 05.
The parent directory must already exist. No record text or path is logged.
"""

import contextlib
import json
import math
import os
import re
import secrets
import shutil
import threading
import time
from collections import namedtuple
from pathlib import Path

from .base import private_open, utc_time
from . import clock

Policy = namedtuple("Policy", "rank refresh stale")
# Stage 05 order; C1 never takes the notice-counter lease (TASK-092).
POLICIES = dict(zip(("store", "curation", "sync", "layer", "notice", "raw", "log"),
                    (Policy(0, 30, 120), Policy(1, 60, 600), Policy(2, 60, 600),
                     Policy(3, 30, 120), Policy(4, None, 10), Policy(5, None, 10), Policy(6, None, 10))))
_registry_guard = threading.RLock()
_registry_pid = os.getpid()
_active = {}
Snapshot = namedtuple("Snapshot", "token identity mtime")


def _after_fork():
    global _registry_pid, _registry_guard
    _registry_pid, _registry_guard = os.getpid(), threading.RLock()
    _active.clear()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork)


class LockBusy(RuntimeError):
    def __init__(self):
        super().__init__("lock-busy")


class LostLock(RuntimeError):
    def __init__(self):
        super().__init__("lost-lock")


class LockOrderError(RuntimeError):
    def __init__(self):
        super().__init__("lock order violation")


def _snapshot(path):
    if path.is_symlink():
        raise ValueError("a lock must not be a symlink")
    try:
        with open(path, "rb") as stream:
            data = stream.read(4097)
            stat = os.fstat(stream.fileno())
    except FileNotFoundError:
        return None
    try:
        token = json.loads(data.decode("utf-8"))["token"]
        if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token):
            token = None
    except (ValueError, KeyError, TypeError):
        token = None
    return Snapshot(token, (stat.st_dev, stat.st_ino), stat.st_mtime_ns)


def _touch(fd, mtime=None):
    """Touch the opened file, never a possibly replaced path."""
    mtime = time.time_ns() if mtime is None else mtime
    if os.name != "nt":
        os.utime(fd, ns=(os.fstat(fd).st_atime_ns, mtime))
    else:
        # Python 3.8's os.utime does not accept a Windows descriptor.
        import ctypes
        import msvcrt
        from ctypes import wintypes
        ticks = mtime // 100 + 116444736000000000
        stamp = wintypes.FILETIME(ticks & 0xffffffff, ticks >> 32)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.SetFileTime.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.POINTER(wintypes.FILETIME)]
        kernel.SetFileTime.restype = wintypes.BOOL
        if not kernel.SetFileTime(msvcrt.get_osfhandle(fd), None, None, ctypes.byref(stamp)):
            raise OSError("lock refresh failed")


def _paths(check, *paths):
    if check is not None:
        for path in paths:
            check(path)


def _discard(path, deadline, check=None):
    while True:
        try:
            _paths(check, path)
            path.unlink()
            return
        except FileNotFoundError:
            return
        except PermissionError:
            left = deadline - clock.now()
            if left <= 0:
                raise
            time.sleep(min(0.005, left))


def _restore(source, target, snapshot, check=None):
    """Restore without replacing a lock another contender has already made."""
    try:
        _paths(check, source, target)
        os.link(str(source), str(target))
    except FileExistsError:
        return
    except OSError:
        try:
            _paths(check, target)
            fd = private_open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return
        with os.fdopen(fd, "wb") as output:
            _paths(check, source)
            with source.open("rb") as incoming:
                shutil.copyfileobj(incoming, output)
            output.flush()
            _touch(output.fileno(), snapshot.mtime)


class Lock:
    """Stage 05 lease; its lock path must be inside the memory folder."""

    def __init__(self, path, kind, device, *, path_check=None):
        if kind not in POLICIES or not re.fullmatch(r"d_[0-9a-hjkmnp-tv-z]{12}", device):
            raise ValueError("invalid lock kind or device")
        path = Path(path)
        self._path_check = path_check
        _paths(path_check, path)
        self.path = path.parent.resolve() / path.name
        _paths(path_check, self.path)
        self.policy, self.device = POLICIES[kind], device
        ordering_path = self.path.as_posix()
        self._order = (self.policy.rank, ordering_path.casefold() if os.name == "nt" else ordering_path)
        self.pid, self.token = os.getpid(), None
        self._stop, self._mutex = threading.Event(), threading.RLock()
        self._thread = None

    def _snapshot(self, path=None):
        path = self.path if path is None else path
        _paths(self._path_check, path)
        return _snapshot(path)

    def _reserve(self):
        global _registry_pid
        with _registry_guard:
            if _registry_pid != os.getpid():
                _active.clear()
                _registry_pid = os.getpid()
            if self.pid != os.getpid():
                raise LostLock()
            if self in _active or any(order > self._order or path == self.path
                                      for order, path in _active.values()):
                raise LockOrderError()
            _active[self] = (self._order, self.path)

    def _unreserve(self):
        with _registry_guard:
            _active.pop(self, None)

    def _create(self):
        try:
            _paths(self._path_check, self.path)
            fd = private_open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
        except FileExistsError:
            return False
        with os.fdopen(fd, "wb") as stream:
            record = {"pid": self.pid, "device": self.device, "at": utc_time(), "token": self.token}
            stream.write((json.dumps(record, indent=2) + "\n").encode("utf-8"))
        return True

    def _detach(self, expected, stale, force=False, deadline=None):
        deadline = clock.now() + 1 if deadline is None else deadline
        moved = self.path.with_name(self.path.name + "." + secrets.token_hex(16) + ".stale")
        cleanup = False
        try:
            _paths(self._path_check, self.path, moved)
            os.rename(str(self.path), str(moved))
        except FileNotFoundError:
            return None
        try:
            actual = self._snapshot(moved)
            same = actual and actual.token == expected.token and actual.identity == expected.identity
            if actual and actual.token is None:
                same = same and actual.mtime == expected.mtime
            expired = actual and (time.time_ns() - actual.mtime) / 1e9 > self.policy.stale
            if not same or (stale and not force and not expired):
                if actual:
                    _restore(moved, self.path, actual, check=self._path_check)
                cleanup = True
                return False
            cleanup = True
            return True
        finally:
            if cleanup:
                _discard(moved, deadline, check=self._path_check)

    def _start_heartbeat(self):
        if self.policy.refresh is not None:
            self._thread = threading.Thread(target=self._heartbeat, args=(self._stop,), daemon=True)
            self._thread.start()

    def _attempt(self, deadline, force, finish=False):
        if self._create():
            return True
        previous = self._snapshot()
        if previous and (force or (time.time_ns() - previous.mtime) / 1e9 > self.policy.stale):
            detached = self._detach(previous, stale=True, force=force, deadline=deadline)
            if detached is False:
                raise LockBusy()
            if detached and (finish or clock.now() < deadline):
                return self._create()
        return False

    def acquire(self, deadline, wait=True, force=False, *, at_least_once=False):
        """Acquire by an absolute monotonic deadline; force is for purge/delete.

        wait=False makes one attempt, for workers that leave a busy project.
        A failed token check after a rename gives up immediately.
        Recording opts into at_least_once: expiry limits waiting, not its first
        acquisition attempt. Other callers retain their strict deadline gate.
        """
        if not math.isfinite(deadline):
            raise ValueError("a finite deadline is required")
        self._reserve()
        self.token = secrets.token_hex(16)
        self._stop, self._thread = threading.Event(), None
        try:
            first = True
            while clock.now() < deadline or first and at_least_once:
                first = False
                try:
                    acquired = (self._attempt(deadline, force, finish=True) if at_least_once
                                else self._attempt(deadline, force))
                except PermissionError:
                    acquired = False
                if acquired:
                    self._start_heartbeat()
                    return self
                if not wait:
                    break
                time.sleep(max(0, min(0.005, deadline - clock.now())))
            raise LockBusy()
        except BaseException:
            self.token = None
            self._unreserve()
            raise

    def try_once(self, *, fail_on_permission=False):
        """One exclusive-create attempt; no waiting or stale-lock takeover.

        Used by expired hooks for their best-effort deadline diagnostics.
        Unlike acquire(wait=False), this has no future operation budget.
        Early opportunistic logs may keep permission denial distinct from an
        existing lease, so they do not spend the hook's budget waiting for it.
        """
        self._reserve()
        self.token = secrets.token_hex(16)
        self._stop, self._thread = threading.Event(), None
        try:
            try:
                acquired = self._create()
            except PermissionError:
                if fail_on_permission:
                    raise
                acquired = False
            if not acquired:
                raise LockBusy()
            self._start_heartbeat()
            return self
        except BaseException:
            self.token = None
            self._unreserve()
            raise

    def check(self):
        """Raise lost-lock before a change if this process no longer owns it."""
        if self.pid != os.getpid():
            raise LostLock()
        with self._mutex:
            current = self._snapshot()
            if self._stop.is_set() or not self.token or not current or current.token != self.token:
                raise LostLock()
        return True

    def refresh(self):
        if self.pid != os.getpid():
            raise LostLock()
        with self._mutex:
            self.check()
            try:
                _paths(self._path_check, self.path)
                fd = os.open(str(self.path), os.O_RDWR | getattr(os, "O_BINARY", 0))
            except FileNotFoundError:
                raise LostLock() from None
            try:
                record = json.loads(os.read(fd, 4096).decode("utf-8"))
                if not isinstance(record, dict) or record.get("token") != self.token:
                    raise LostLock()
                _paths(self._path_check, self.path)
                _touch(fd)
            finally:
                os.close(fd)
            self.check()

    def _heartbeat(self, stop):
        while not stop.wait(self.policy.refresh):
            try:
                self.refresh()
            except (OSError, ValueError, LostLock):
                stop.set()

    def _release(self, deadline):
        last = None
        with self._mutex:
            while self.token:
                try:
                    current = self._snapshot()
                    if not current or current.token != self.token:
                        return
                    if self._detach(current, stale=False, deadline=deadline) is not None:
                        return
                except OSError as error:
                    last = error
                left = deadline - clock.now()
                if left <= 0:
                    raise last if last is not None else LockBusy()
                time.sleep(min(0.005, left))

    def release(self, report=None):
        """Retry cleanup for one second; report cleanup failure without raising.

        A leftover lease expires normally. A completed protected operation keeps
        its result even if cleanup fails. Reports contain only the class name.
        Releasing another process's lease is misuse and raises LostLock.
        """
        if self.pid != os.getpid():
            # Do not enter mutexes inherited from vanished parent threads.
            raise LostLock()
        failure = None
        try:
            self._stop.set()
            if self._thread:
                self._thread.join(timeout=1)
            self._release(clock.now() + 1)
        except Exception as error:
            failure = error
        finally:
            self.token = None
            try:
                self._unreserve()
            except Exception as error:
                failure = error
        if failure is not None and report is not None:
            try:
                report(type(failure).__name__, None)
            except Exception:
                pass

    @contextlib.contextmanager
    def held(self, deadline, wait=True, force=False, report=None):
        self.acquire(deadline, wait=wait, force=force)
        try:
            yield self
        finally:
            self.release(report=report)
