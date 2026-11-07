"""SPEC-010 curation triggers for the end-of-turn and session end hooks (API-003, API-004).

Not wired: no hook calls this module until the C2 hooks are connected, so
installed C1 behaviour is unchanged. A hook calls `start` after it recorded its
entry and released the raw lease. The check lists the project's `unprocessed/`
folder and reads the curation record (TBL-009) without a lease; it opens no raw
log and writes nothing (TBL-008). A met trigger starts the memory worker through
`worker_launch`, which also skips a fresh curation lock. A missing or damaged
record meets no trigger; the next worker makes it again (`curation_rebuild`).
"""
from collections import namedtuple
from datetime import datetime, timezone
import os

from . import base, clock, files, format2, locks, model_access, retention, worker_launch

HOOKS = ('end-of-turn', 'end')
Markers = namedtuple('Markers', 'count oldest')


def scan(memory, root):
    """Unprocessed turns and the oldest time, from the markers' names alone.

    Several markers of one turn count once, at their oldest time; a name that
    is not a marker or holds an impossible time is left out, as the memory
    status does (SPEC-033).
    """
    folder = root / 'unprocessed'
    if memory.fence.check(folder) is None:
        return Markers(0, None)
    turns = {}
    with os.scandir(str(folder)) as found:
        for entry in found:
            match = retention.MARKER.fullmatch(entry.name)
            if match is None or not entry.is_file(follow_symlinks=False):
                continue
            try:
                at = datetime.strptime(match.group(1), '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            key = (match.group(2), int(match.group(3)))
            turns[key] = min(at, turns.get(key, at))
    return Markers(len(turns), min(turns.values()) if turns else None)


def met(hook, markers, now, triggers, temporary):
    """SPEC-010: `triggers.turns` turns (one on a temporary device) or the oldest
    older than `triggers.minutes` at the end of a turn; any turn at the end of a session."""
    if hook not in HOOKS:
        raise ValueError('invalid trigger hook')
    if not markers.count:
        return False
    if hook == 'end':
        return True
    turns = 1 if temporary else triggers['turns']
    return markers.count >= turns or (now - markers.oldest).total_seconds() > triggers['minutes'] * 60


def _progress(memory, root, deadline):
    """The primary record, else its backup, read without a lease; None when neither parses.

    Only the worker restores a backup or makes the record again, under its leases.
    """
    path = root / 'curation.json'
    for candidate in (path, path.with_name(path.name + '.bak')):
        try:
            return format2.parse_curation(memory.fence.read(candidate, deadline))
        except files._RESTORABLE:
            continue
    return None


def decide(memory, configuration, project, hook, deadline, *, now=None, environment=None):
    """'start' when the hook should start the worker, otherwise why it should not.

    The reasons are `consent`, `disabled`, `key`, `not-met`, `record` (no
    readable curation record), `stopped` (the fault guard, SPEC-018) and `fresh`
    (a curation lock refreshed within 10 minutes, SPEC-012). The cheap checks
    come first, and the record is read only for a met trigger.
    """
    if hook not in HOOKS:
        raise ValueError('invalid trigger hook')
    if not configuration.consented():
        return 'consent'
    if not configuration.enabled(project):
        return 'disabled'
    if model_access.Credentials.read(environment).presence()['anthropic'] != 'present':
        return 'key'
    root = memory.folder / 'projects' / base.project_folder_name(project)
    markers = scan(memory, root)
    now = datetime.now(timezone.utc) if now is None else now
    values = configuration.values
    if not met(hook, markers, now, values['triggers'], values['temporary']):
        return 'not-met'
    progress = _progress(memory, root, deadline)
    if progress is None:
        return 'record'
    if 'stopped' in progress:
        return 'stopped'
    if worker_launch._fresh(memory, project):
        return 'fresh'
    return 'start'


def start(memory, configuration, project, hook, deadline, logger, *, host=None, now=None, environment=None):
    """Check the trigger and start the worker with `--reason <hook>` within the hook's deadline.

    Returns `deadline` when the deadline passed before the check or before the
    start, which are then skipped; `started`; `not-started` when the launch
    failed, which the failure log notes as `worker-start`, or found the lock
    fresh; or the reason of `decide`. An error propagates to the hook, whose
    timing says `error`; the next trigger tries again.
    """
    if clock.now() >= deadline:
        return 'deadline'
    try:
        reason = decide(memory, configuration, project, hook, deadline, now=now, environment=environment)
    except locks.LockBusy:
        return 'deadline'  # The record's read found the deadline passed.
    if reason != 'start':
        return reason
    if clock.now() >= deadline:
        return 'deadline'
    started = worker_launch.launch(memory, project, hook, deadline, logger,
                                   expected_device=memory.device, hook=hook, host=host)
    return 'started' if started else 'not-started'
