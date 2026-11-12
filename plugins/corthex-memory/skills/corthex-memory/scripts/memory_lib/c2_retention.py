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

The project's curation lease, the store and the phase's deadline are the
worker's: when one of them is lost, replaced or over, the project stops and the
worker hears of it. Anything else is one record family's alone, or step 2's, and
the next family and the next project still run. A lease or read that stays busy
within the phase, the layer lease included, leaves its family quietly for the
next start. Any other error is noted for the failure log under the step
`retention`: a link or a file that the path fence or a family refuses, which
reaches here as a lost lease too, a layer lease that another process took, and a
layer lease file that is a link. The line history's owner check lists the
project's `layer` folder, so without that folder the history is kept and noted
while the run logs and injection logs still expire.

The worker reads the configuration again before its sweep (`worker_runtime`), and
each project's turn begins by reading it once more, so that the project goes by
the retention period set as its turn begins. Step 2 then looks again under the
layer lease, first itself and then at each of the line history's owner checks.
When one of those looks cannot confirm the period, because the user changed it
meanwhile, the configuration is no longer valid or its read stays busy, the
history, the run logs and the injection logs of the project are all kept for
the next start, and the next project's turn reads the period that is set then.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

from . import base, clock, configuration, fence_plan, history_retention, injection_retention, locks, retention
from . import run_log, worker_support


@dataclass(frozen=True)
class Retained:
    raw: object        # retention.retain_project's totals, or None when it failed or stayed busy
    history: object    # history_retention's result, or None when it failed, stayed busy or did not run
    runs: int          # run logs deleted
    injections: int    # injection log lines deleted


def _busy(error):
    """Whether `error` is a lease or read that stayed busy, or a family's failure that came from one."""
    seen = set()
    while error is not None and id(error) not in seen:
        if isinstance(error, locks.LockBusy):
            return True
        seen.add(id(error))
        error = error.__cause__
    return False


def _family(memory, deadline, action):
    """One record family's result, or None once it failed or stayed busy, so that the next family still runs.

    The leases that the worker holds, the store and the phase's deadline are looked at first, and a lost
    lease, the store's replacement or a phase past its deadline is raised to the worker. Anything else
    is the family's alone. One that stayed busy is left quietly for the next start. Any other error is
    noted: a family reports a link or a file that it refuses as a lost lease too (UnsafePath, LostLock),
    which the look above tells from the worker's own.
    """
    try:
        return action()
    except Exception as error:
        memory.check(deadline, memory.held)
        if not _busy(error):
            memory.note(error, step="retention")
        return None


def _settings(memory, deadline):
    """The configuration as it is now, read as the curation worker reads it again under its leases."""
    return memory.configuration(memory.note, deadline=min(deadline, clock.now() + worker_support.OPERATION_SECONDS))


def retain_project(memory, project, owner, deadline, when=None):
    """Every format-2 record of `project` past the retention period, under the caller's curation lease."""
    root = memory.folder / "projects" / base.project_folder_name(project)
    if (owner not in memory.held or owner.path != root / "curation.lock" or
            owner.device != memory.device or owner.policy != locks.POLICIES["curation"]):
        raise locks.LostLock()
    moment = when if when is not None else datetime.now(timezone.utc)
    # The period set as this project's turn begins: an earlier project's turn may have taken long, or found
    # the period changed. The log sweep after the projects goes by the last one read.
    memory.config = _settings(memory, deadline)
    days = memory.config.values["retention"]["days"]
    confirmed = False  # Whether the last look under the layer lease found the period still this one.

    def current(memory_=None, root_=None, context=None):
        # Step 2's first look, and the owner's check (history_retention): the period is still this one.
        nonlocal confirmed
        confirmed = False
        try:
            settings = _settings(memory, deadline)
        except configuration.ConfigurationInvalid:
            raise fence_plan.Stale() from None
        if settings.values["retention"]["days"] != days:
            raise fence_plan.Stale()
        confirmed = True

    def layer():
        with memory.lease(root / "layer.lock", "layer", deadline, "retention"):
            # The raw step may have taken long: nothing under this lease goes by a period that is not confirmed here.
            current()
            history = _family(memory, deadline, lambda: history_retention.retain_history(
                memory, root, deadline, when=moment, days=days, history_precondition=current))
            if not confirmed:
                # Nor by one that a later check of the line history could not confirm.
                return history, 0, 0
            # These two families take the cutoff's moment as a TBL-121 time.
            runs, injections = (_family(memory, deadline, lambda family=family: family(
                memory, root, deadline, when=base.utc_time(moment), days=days)) or 0
                for family in (run_log.expire, injection_retention.expire))
            return history, runs, injections

    # The cutoff is this moment's; future dates are checked against the clock unless `when` fixes it.
    raw = _family(memory, deadline, lambda: retention.retain_project(memory, project, owner, deadline, when,
                                                                      moment=moment))
    history, runs, injections = _family(memory, deadline, layer) or (None, 0, 0)
    return Retained(raw, history, runs, injections)
