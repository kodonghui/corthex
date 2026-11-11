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
to the worker. Any other error of one record family is noted for the failure
log under the step `retention`, and the next family still runs. The line
history's owner check reads the configuration again, so that a retention period
that the user changed meanwhile keeps the history for the next start.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

from . import base, clock, configuration, fence_plan, history_retention, injection_retention, locks, retention
from . import run_log, worker_support


@dataclass(frozen=True)
class Retained:
    raw: dict          # retention.retain_project's totals
    history: object    # history_retention's result, or None when it did not run
    runs: int          # run logs deleted
    injections: int    # injection log lines deleted


def retain_project(memory, project, owner, deadline, when=None):
    """Every format-2 record of `project` past the retention period, under the caller's curation lease."""
    root = memory.folder / "projects" / base.project_folder_name(project)
    if (owner not in memory.held or owner.path != root / "curation.lock" or
            owner.device != memory.device or owner.policy != locks.POLICIES["curation"]):
        raise locks.LostLock()
    moment = when if when is not None else datetime.now(timezone.utc)
    days = memory.config.values["retention"]["days"]
    raw = retention.retain_project(memory, project, owner, deadline, moment)
    history, runs, injections = None, 0, 0
    if memory.fence.check(root / "layer") is None:
        return Retained(raw, history, runs, injections)

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
        try:
            history = history_retention.retain_history(memory, root, deadline, when=moment, days=days,
                                                       history_precondition=current)
        except (locks.LostLock, locks.LockBusy):
            raise
        except Exception as error:
            memory.note(error, step="retention")
        for family in (run_log.expire, injection_retention.expire):
            try:
                # These two families take the cutoff's moment as a TBL-121 time.
                found = family(memory, root, deadline, when=base.utc_time(moment), days=days)
            except (locks.LostLock, locks.LockBusy):
                raise
            except Exception as error:
                memory.note(error, step="retention")
                continue
            if family is run_log.expire:
                runs = found
            else:
                injections = found
    return Retained(raw, history, runs, injections)
