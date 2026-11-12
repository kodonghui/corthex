"""API-005: the memory worker's phases; no provisioning, sync or result report.

Below release 0.3.0, and for a format-1 store, only C1's phases run: the
initial project's curation lease, and at a session start retention and clean-up
of every project. From release 0.3.0 (TASK-117) the worker finds the kind of
store first, as the command runner and the hooks do. A format-2 store gets the
format-2 binding (`c2_store.C2Store`) and, under the initial project's lease,
curation, consolidation and the search index (steps 2, 3 and 6) within one run
of `RUN_SECONDS`, curation looking again after steps 3 and 6 for turns marked
meanwhile; a step that ends with a lost lease while the worker's own lease and
the store still hold, as for a link that the path fence refuses, ends that run
only. At a session start the configuration is read again, and every project's
retention then covers its line history, run logs and injection logs too
(`c2_retention`); a read that stays busy, or a configuration that is no longer
valid, leaves the sweep for the next start, since the sweep must not go by a
period that it could not read. A store that a migration holds, of a newer
format or damaged ends the worker without a write.
"""
import os
import stat

from . import activation, base, cleanup, clock, locks, retention, worker_support

REASONS = {"start", "end-of-turn", "end", "skill"}
# Steps 2, 3 and 6 of a format-2 project share one run under its curation lease, whose heartbeat keeps it
# while a request is out: an operational choice, as the phases' 300 seconds are. Each request also keeps to
# its own 30-minute limit, and a step starts no request in the run's last 60 seconds.
RUN_SECONDS = 3600.0


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


def _kind(folder):
    """From release 0.3.0: the kind of store at `folder`, or None for none or below 0.3.0 (activation)."""
    if not activation.c2():
        return None
    from . import files, store
    folder = store.MemoryStore(folder).folder
    if not folder.exists():
        return None  # The worker's own gate then ends it, as below 0.3.0.
    fence = worker_support.PathFence(folder)
    deadline = clock.now() + worker_support.OPERATION_SECONDS
    return activation.store_kind(fence.root, lambda path: files._retry(lambda: fence.read(path, deadline), deadline))


def _ended(memory, step):
    """After a step ended with a lost lease: "lost" when the worker's own lease or the store is gone, else "stop".

    A step ends so, too, for a link or a file that the path fence or the step refuses (UnsafePath, LostLock)
    and for a lease that it took itself and lost. The worker's own lease and the store then still hold,
    so only the initial project's run ends, and a session start still sweeps. Only this look tells the
    two apart, since the steps report both as a lost lease.
    """
    try:
        memory.check(clock.now() + worker_support.OPERATION_SECONDS, memory.held)
    except (locks.LostLock, locks.LockBusy):
        return "lost"
    except Exception as error:
        # The store record could not be looked at: the worker ends, as when the record is replaced.
        memory.note(error, step=step)
        return "lost"
    return "stop"


def _step(memory, step, action, project, owner, deadline):
    """One step of a format-2 run: its outcome, None after an error that it noted, or "stop" or "lost"."""
    try:
        outcome = action(memory, project, owner, deadline)
    except locks.LostLock as error:
        memory.note(error, step=step)
        return _ended(memory, step)
    except locks.LockBusy:
        try:
            memory.check(deadline, memory.held)
        except locks.LockBusy:
            return "stop"  # The run's time is over, as a returned `deadline` says.
        except locks.LostLock as error:
            memory.note(error, step=step)
            return "lost"
        return None
    except Exception as error:
        memory.note(error, step=step)
        return None
    if outcome.reason == "lost-lock":
        return _ended(memory, step)
    if outcome.reason == "deadline":
        return "stop"
    return outcome


def _curated(memory, project, owner):
    """Steps 2, 3 and 6 of a format-2 project within one run; False when a lost lease or store stops the worker.

    Each step notes its own failures, a lost lease included, and ends with its reason. A step that ends
    with a lost lease while the worker's own lease and the store still hold met a link or a file that
    it refuses, or lost a lease that it took itself: the run ends there and the worker goes on, as when
    the run's time is over. A trigger that
    finds this run's lease fresh starts no worker (SPEC-012), so once a curation that left nothing
    behind is followed by steps 3 and 6, curation looks again for turns marked meanwhile, and steps 3
    and 6 follow each curation that applied something, until one finds nothing or the run ends.
    """
    from . import consolidation_worker, curation_worker, index_worker
    deadline = clock.now() + RUN_SECONDS
    first = True
    while True:
        curated = _step(memory, "curate", curation_worker.curate, project, owner, deadline)
        if curated in ("lost", "stop"):
            return curated != "lost"
        if not first and (curated is None or not curated.attempts):
            return True
        for step, action in (("consolidate", consolidation_worker.consolidate), ("embed", index_worker.keep)):
            outcome = _step(memory, step, action, project, owner, deadline)
            if outcome in ("lost", "stop"):
                return outcome != "lost"
        if curated is None or curated.reason != "done":
            return True
        first = False


def run(project, reason, expected_device=None, folder=None):
    """Run due work quietly. Returning is not a maintenance success signal."""
    memory, step = None, "restore"
    try:
        base.project_folder_name(project)
        if reason not in REASONS:
            return
        kind = _kind(folder)
        if kind not in (None, activation.FORMAT_1, activation.FORMAT_2):
            return  # A store that a migration holds, of a newer format or damaged.
        if kind == activation.FORMAT_2:
            from . import c2_retention, c2_store
            memory, retain = c2_store.C2Store(folder, expected_device), c2_retention.retain_project
        else:
            memory, retain = worker_support.WorkerStore(folder, expected_device), retention.retain_project
        deadline = _deadline()
        root = _root(memory, project, deadline)
        if root is not None:
            with memory.lease(root / "curation.lock", "curation", deadline) as owner:
                memory.check(deadline, memory.held)
                if kind == activation.FORMAT_2 and not _curated(memory, project, owner):
                    return
        elif reason != "start":
            return
        if reason != "start":
            return
        # The initial lease is gone before either all-project sweep begins.
        step = "retention"
        if kind == activation.FORMAT_2:
            # Its run may have lasted up to RUN_SECONDS: the sweep goes by the period that the user set now.
            memory.config = memory.configuration(memory.note, deadline=clock.now() + worker_support.OPERATION_SECONDS)
        for name in _projects(memory):
            _phase(memory, retain, step, name)
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
