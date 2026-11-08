"""The undo command (API-153; SPEC-145; TASK-105, TASK-106, TASK-107): its preview, confirmation and inverse.

The command runner does not hand `undo` to this handler before the 0.3.0
activation, so an installed plugin keeps C1 behaviour; until then the tests
call it as the runner will, after its gates, with the format-2 store binding.
Without a code it takes the project's layer lease, waiting for it as long as
the other commands wait for theirs, reads the run's log, the curation record's
fence, the curated layer, the line history and the other run logs, each
through the store's path fence, and returns the preview (`undo_plan`); it
changes nothing. With a code it takes the project's curation lease and then its
layer lease, as the inverse needs (SPEC-145), reads everything again and checks
the code against the fresh preview, whose binding covers the run's file, the
revisions, the objects that the inverse depends on and the line history that
it needs; so any relevant change answers `confirm-stale` with the new preview.
A code that matches hands the plan and the snapshot that it was read from to
the inverse (`undo_effects`), under the same leases, which applies it as a new
run and answers `done` with the new run's ID.
"""
import contextlib
import hashlib

from . import base, clock, commands, conflict_types, curation_worker, files, format2, history_io
from . import history_recovery, item_types, locks, request_inputs, revision_io, run_listing, run_log
from . import state_types, undo_effects, undo_plan, worker_support

# The commands' shared lock wait, within one bound for the whole read.
WAIT, SECONDS = 10.0, 60.0
# A run argument as the result schema holds it.
ARGUMENT = 200
SAY = {
    'missing': ('No complete run of this project within the retention period has this ID, so nothing was '
                'undone; data.runs holds the recent runs.'),
    'unreadable': ('No run can be undone now because the curation record cannot be read. '
                   'The next curation repairs it.'),
}


def _not_found(project, run, runs, say='missing'):
    data = {'project': project, 'run': run, 'runs': list(runs)}
    return commands.result('undo', data, SAY[say], 'refused', 'run-not-found')


def _log(root, run, read):
    """(the run's log, its file's SHA-256), or (None, None) when it cannot be read whole."""
    if not format2._RUN.fullmatch(run):
        return None, None
    try:
        data = read(run_log.path(root, run))
        value = run_log.parse(data)
    except worker_support.UnsafePath:
        return None, None
    except (OSError, ValueError, UnicodeError, TypeError, KeyError):
        return None, None
    if value['id'] != run:
        return None, None
    return value, hashlib.sha256(data).hexdigest()


def _others(root, run, read):
    """The project's other readable run logs, which name the run of a later change."""
    found = []
    for name in run_log._names(root / 'runs'):
        other = name[:-5] if name.endswith('.json') else ''
        if other != run and format2._RUN.fullmatch(other):
            value = run_log.read(root, other, read)
            if value is not None:
                found.append(value)
    return tuple(found)


def snapshot(memory, root, deadline, read, log, sha256, progress):
    """The undo plan's inputs, read under the project's layer lease that the caller holds."""
    forgotten, private = set(), set()
    for name, data in request_inputs._named(root / 'layer/tombstones', read):
        private.update(history_recovery._tombstone(data, name, root.name))
        forgotten.add(name)
    items = {}
    for name, data in request_inputs._named(root / 'layer/items', read):
        if name in forgotten:
            continue
        value = item_types.parse_item(data)
        if value['id'] != name:
            raise ValueError('item file name differs from its ID')
        items[name] = value
    try:
        history = history_io.read(memory, root, deadline)
    except files.RestoreNeeded:
        history = None
    return undo_plan.Snapshot(
        log=log, log_sha256=sha256, fence=progress['fence'], items=items, forgotten=frozenset(forgotten),
        private=frozenset(private),
        lines=tuple(state_types.parse_state(read(root / 'layer/state.json'))['lines']),
        removed=tuple(state_types.parse_removed(read(root / 'layer/state-removed.json'))['removed']),
        pins=tuple(item_types.parse_pins(read(root / 'layer/pins.json'))['pins']),
        candidates=tuple(conflict_types.parse_conflicts(read(root / 'layer/conflicts.json'))['candidates']),
        history=history, logs=_others(root, log['id'], read))


def _apply(memory, root, plan, snap, deadline):
    """The confirmed inverse, under the curation and layer leases that read the plan (TASK-107)."""
    undo = undo_effects.apply(memory, root, plan, snap, deadline, at=base.utc_time())
    data = {'project': plan.data['project'], 'run': plan.data['run'], 'undo': undo,
            'changes': plan.data['changes'], 'kept': plan.data['kept']}
    return commands.result('undo', data, undo_effects.SAY)


def undo(context, *, when=None):
    """API-153 after the runner's gates, with the format-2 store binding as `context.memory`.

    `when` fixes the time that retention counts from, for tests.
    """
    project = context.project.name
    run = context.arguments.get('run')
    if type(run) is not str or not 1 <= len(run) <= ARGUMENT:
        return commands.common_result('undo', 'usage')
    memory = context.memory
    root = memory.folder / 'projects' / base.project_folder_name(project)
    days = context.configuration.values['retention']['days']
    if memory.fence.check(root) is None:
        return _not_found(project, run, [])
    deadline = clock.now() + SECONDS
    try:
        with contextlib.ExitStack() as leases:
            # A code goes on to the inverse, which takes the curation lease before the layer lease (SPEC-145).
            kinds = ('curation', 'layer') if context.supplied is not None else ('layer',)
            for kind in kinds:
                leases.enter_context(memory.lease(root / (kind + '.lock'), kind, deadline, 'skill',
                                                  acquire_deadline=min(deadline, clock.now() + WAIT)))
            if curation_worker._deleted(memory, root):
                return _not_found(project, run, [])
            read = run_listing._reader(memory, deadline)
            try:
                progress = revision_io.read(memory, root, deadline)
            except files._RESTORABLE + (files.RestoreNeeded,) as error:
                memory.note(error, step='skill')
                return _not_found(project, run, [], 'unreadable')
            log, sha256 = _log(root, run, read)
            cutoff = run_log._cutoff(base.utc_time(when), days)[0]
            if not run_log.eligible(log, progress, memory.device) or log['ended'] < cutoff:
                runs, _ = run_listing.listing(memory, root, deadline, progress, read, days=days,
                                              limit=run_listing.DEFAULT, when=when)
                return _not_found(project, run, runs)
            snap = snapshot(memory, root, deadline, read, log, sha256, progress)
            plan = undo_plan.plan(project, run, snap)
            memory.check(deadline, memory.held)
            if not plan.reversed:
                return commands.result('undo', plan.data, undo_plan.say(plan), 'nothing')
            return context.confirm(plan.data, undo_plan.say(plan), lambda: _apply(memory, root, plan, snap, deadline))
    except locks.LockBusy:
        return commands.common_result('undo', 'lock-busy')
