"""API-005 C1 phases only; no provisioning, model calls, sync or result report."""
import os
import stat

from . import base, cleanup, clock, locks, retention, worker_support

REASONS = {"start", "end-of-turn", "end", "skill"}


def _deadline():
    return clock.now() + worker_support.PHASE_SECONDS


def _root(memory, project, deadline):
    memory.check(deadline)
    path = memory.folder / "projects" / base.project_folder_name(project)
    info = memory.fence.check(path)
    return path if info is not None and stat.S_ISDIR(info.st_mode) else None


def _projects(memory):
    """Inventory existing canonical project folders, without a data lease."""
    deadline = _deadline()
    memory.check(deadline)
    folder = memory.folder / "projects"
    if memory.fence.check(folder) is None:
        return []
    names = []
    paths = sorted(folder.iterdir(), key=lambda p: (p / "curation.lock").as_posix().lower() if os.name == "nt" else (p / "curation.lock").as_posix())
    for path in paths:
        memory.check(deadline)
        name = path.name[:-1] if path.name.endswith("_") else path.name
        try:
            if base.project_folder_name(name) == path.name and _root(memory, name, deadline) is not None:
                names.append(name)
        except (ValueError, worker_support.UnsafePath):
            continue
    memory.check(deadline)
    return names


def _phase(memory, action, step, project=None):
    deadline = _deadline()
    try:
        memory.check(deadline)
        if project is None:
            action(memory, deadline)
        else:
            try:
                root = _root(memory, project, deadline)
            except worker_support.UnsafePath:
                memory.check(deadline)
                return
            if root is None:
                return
            with memory.lease(root / "curation.lock", "curation", deadline, step) as owner:
                action(memory, project, owner, deadline)
        memory.check(deadline)
    except locks.LockBusy:
        # A busy lease skips this phase; an expired phase stops the worker.
        memory.check(deadline)
    except locks.LostLock:
        raise
    except Exception as error:
        memory.note(error, step=step)
        memory.check(deadline)
    finally:
        memory.flush()


def run(project, reason, expected_device=None, folder=None):
    """Run due C1 work quietly. Returning is not a maintenance success signal."""
    memory, step = None, "restore"
    try:
        base.project_folder_name(project)
        if reason not in REASONS:
            return
        memory = worker_support.WorkerStore(folder, expected_device)
        deadline = _deadline()
        root = _root(memory, project, deadline)
        if root is not None:
            with memory.lease(root / "curation.lock", "curation", deadline):
                memory.check(deadline, memory.held)
        elif reason != "start":
            return
        if reason != "start":
            return
        # The initial lease is gone before either all-project sweep begins.
        step = "retention"
        for name in _projects(memory):
            _phase(memory, retention.retain_project, step, name)
        _phase(memory, retention.retain_logs, step)
        step = "restore"
        _phase(memory, cleanup.clean_store, step)
        for name in _projects(memory):
            _phase(memory, cleanup.clean_project, step, name)
        _phase(memory, cleanup.clean_logs, step)
    except locks.LockBusy:
        pass
    except Exception as error:
        if memory is not None:
            memory.failure(error, step)
