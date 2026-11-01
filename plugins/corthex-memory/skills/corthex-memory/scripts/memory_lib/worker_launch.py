"""API-005 detached launch only. Call after releasing the caller's data leases.

The caller supplies its verified store/device and original diagnostic deadline.
The child performs its own store gate; starting it is not a maintenance result.
"""
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

from . import base, locks, store

WORKER = Path(__file__).resolve().parents[4] / "scripts" / "worker.py"
_WINDOWS = os.name == "nt"
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
WINDOWS_FLAGS = (DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP |
                 CREATE_BREAKAWAY_FROM_JOB | BELOW_NORMAL_PRIORITY_CLASS)


def _in_job():
    """A failed query is not evidence of a job. Do not change any job limits."""
    try:
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.argtypes = []
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE,
                                         ctypes.POINTER(wintypes.BOOL)]
        kernel.IsProcessInJob.restype = wintypes.BOOL
        present = wintypes.BOOL()
        succeeded = kernel.IsProcessInJob(kernel.GetCurrentProcess(), None,
                                         ctypes.byref(present))
        return bool(succeeded and present.value)
    except Exception:
        return False


def _fresh(memory, project):
    path = memory.folder / "projects" / base.project_folder_name(project) / "curation.lock"
    memory._path_check(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
            getattr(info, "st_file_attributes", 0) & 0x400):
        raise OSError("unsafe curation lease")
    return (time.time_ns() - info.st_mtime_ns) / 1e9 <= locks.POLICIES["curation"].stale


def launch(memory, project, reason, diagnostic_deadline, logger, *,
           expected_device=None, hook=None, host=None):
    """Return whether Popen started a child; never wait or report child success.

    The diagnostic deadline is never renewed, including the compatibility retry.
    Hooks decide whether their remaining budget permits attempting this launch.
    """
    if getattr(memory, "held", ()):
        return False
    try:
        memory._deadline(diagnostic_deadline)
        if reason not in ("start", "end-of-turn", "end", "skill"):
            raise ValueError("invalid worker reason")
        base.project_folder_name(project)
        if expected_device is not None and not store.DEVICE.fullmatch(expected_device):
            raise ValueError("invalid expected device")
        if not memory.folder.is_absolute():
            raise base.MemoryHomeInvalid()
        if _fresh(memory, project):
            return False
        command = [sys.executable, "-I", str(WORKER), "--reason", reason, "--project", project]
        if expected_device is not None:
            command.extend(("--expect-device", expected_device))
        options = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                   "stderr": subprocess.DEVNULL, "cwd": str(memory.folder),
                   "close_fds": True, "shell": False}
        if _WINDOWS:
            options["creationflags"] = WINDOWS_FLAGS
        else:
            options["start_new_session"] = True
        try:
            subprocess.Popen(command, **options)
        except OSError as error:
            if not (_WINDOWS and getattr(error, "winerror", None) == 5 and _in_job()):
                raise
            options["creationflags"] &= ~CREATE_BREAKAWAY_FROM_JOB
            subprocess.Popen(command, **options)
        return True
    except Exception:
        try:
            logger.failure("worker-start", "trigger", diagnostic_deadline, hook=hook,
                           host=host, project=project, opportunistic=True)
        except Exception:
            pass
        return False
