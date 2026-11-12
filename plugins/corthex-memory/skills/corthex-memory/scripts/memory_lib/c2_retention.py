"""SPEC-009 for a format-2 project: the session start's retention, from release 0.3.0 (TASK-117).

The memory worker calls `retain_project` for every project of a format-2
store at a session start, each under the project's tracked curation lease,
which it takes without waiting. Every record goes by its own time, against one
cutoff fixed when the project's turn begins:

1. The raw logs and their unprocessed turn markers (`retention.retain_project`),
   whose progress in the curation record moves through the format-2 record's
   fresh merge (`raw_rewrite.progress_io`). Each raw log takes the layer lease
   for its own rewrite and gives it back.
2. Then, under one layer lease taken without waiting, the line history
   (TBL-119, `history_retention`), the run logs (TBL-121, `run_log.expire`) and
   the injection logs (TBL-011, `injection_retention`).

A busy layer lease leaves the project's step 2 for the next start. A lost lease,
the store's replacement or the phase's deadline stops the project and is raised
to the worker. Any other error of one record family, a link that the path fence
refuses included, is noted for the failure log under the step `retention`, a
lease or read of one family that stays busy within the phase leaves that family
quietly for the next start, and the next family still runs. The line history
needs the project's `layer` folder, which its owner check lists; without that
folder only the run logs and injection logs expire. The worker reads the
configuration again before its sweep (`worker_runtime`), and the line history's
owner check reads it once more, so that a retention period that the user changed
meanwhile keeps the history for the next start.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

from . import base, clock, configuration, fence_plan, history_retention, injection_retention, locks, retention
from . import run_log, worker_support


@dataclass(frozen=True)
class Retained:
    raw: object        # retention.retain_project's totals, or None when it failed or stayed busy
    history: object    # history_retention's result, or None when it did not run, failed or stayed busy
    runs: int          # run logs deleted
    injections: int    # injection log lines deleted


def _family(memory, deadline, action):
    """One record family's result, or None once it failed or stayed busy, so that the next family still runs.

    A lost lease, the store's replacement or the phase's deadline is raised to the worker. Any other
    error, a link that the path fence refuses (UnsafePath, a LostLock) included, is noted, and a lease
    or read that stays busy within the phase is left quietly for the next start.
    """
    try:
        return action()
    except worker_support.UnsafePath as error:
        memory.note(error, step="retention")
    except locks.LostLock:
        raise
    except locks.LockBusy:
        memory.check(deadline, memory.held)  # A phase past its deadline stops here.
    except Exception as error:
        memory.note(error, step="retention")
    return None


def retain_project(memory, project, owner, deadline, when=None):
    """Every format-2 record of `project` past the retention period, under the caller's curation lease."""
    root = memory.folder / "projects" / base.project_folder_name(project)
    if (owner not in memory.held or owner.path != root / "curation.lock" or
            owner.device != memory.device or owner.policy != locks.POLICIES["curation"]):
        raise locks.LostLock()
    moment = when if when is not None else datetime.now(timezone.utc)
    days = memory.config.values["retention"]["days"]
    # The cutoff is this moment's; future dates are checked against the clock unless `when` fixes it.
    raw = _family(memory, deadline, lambda: retention.retain_project(memory, project, owner, deadline, when,
                                                                      moment=moment))
    try:
        layer = memory.fence.check(root / "layer") is not None
    except worker_support.UnsafePath as error:
        memory.note(error, step="retention")
        layer = False

    def current(memory_, root_, context):
        # The owner's check (history_retention): the period that the user set is still this one,
        # read as the curation worker reads the configuration again under its leases.
        try:
            settings = memory.configuration(memory.note, deadline=min(
                deadline, clock.now() + worker_support.OPERATION_SECONDS))
        except configuration.ConfigurationInvalid:
            raise fence_plan.Stale() from None
        if settings.values["retention"]["days"] != days:
            raise fence_plan.Stale()

    with memory.lease(root / "layer.lock", "layer", deadline, "retention"):
        history = None if not layer else _family(memory, deadline, lambda: history_retention.retain_history(
            memory, root, deadline, when=moment, days=days, history_precondition=current))
        # These two families take the cutoff's moment as a TBL-121 time.
        runs, injections = (_family(memory, deadline, lambda family=family: family(
            memory, root, deadline, when=base.utc_time(moment), days=days)) or 0
            for family in (run_log.expire, injection_retention.expire))
    return Retained(raw, history, runs, injections)
