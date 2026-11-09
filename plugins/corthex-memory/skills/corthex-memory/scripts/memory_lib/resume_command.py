"""The resume command (API-019; SPEC-033, SPEC-018; TASK-096).

The command runner parses `resume` but hands it to no handler before the 0.3.0
activation, so it answers it as not implemented, as in C1, and an installed
plugin keeps C1 behaviour; until then the tests call this handler as the runner
will, after its gates, with the format-2 store binding.

It takes the project's curation lease and then its layer lease, the curation
record's writers' leases (TBL-009), waiting for each as long as the other
commands wait for theirs, and reads under them, through the store's path
fence, the curation record and the project's unprocessed turns, counted from
the markers' names as the triggers count them (TBL-008). Its reading of the
record, as the record's writers read it, restores a damaged primary from a
whole backup with a new epoch, whether or not the project is stopped; beyond
that, a project that the fault guard has not stopped has nothing to resume,
and for a stopped project, without a code it changes nothing: it shows the
failed attempts that the stop came from, newest first, and the unprocessed
turns. With a code that matches
what it has just read under the same leases, it clears the stop: the record
loses `stopped`, and the count of failed attempts from one first turn and the
count of failed consolidations in a row go back to zero, as a success sets
them, so that the fault guard counts three new failures before it stops the
project again (SPEC-018). Every other field of the record, its fence included,
stays as it is, and no item, line, pin, candidate, notice or run changes. The
code covers the project, the stop and the failed attempts that it shows, not
the unprocessed turns, as the maintainer decided on 2026-11-09: the person's
own answer is recorded as a new turn, so a new turn leaves the code current,
and the result counts the turns that wait then. Another stop or other failed
attempts, or two ten-minute periods, make the code stale (`confirm-stale`),
with the new data and a new code.

Once the leases are released, when turns wait, it starts the memory worker
with `--reason skill` (API-005), unless a fresh curation lease shows that a
worker runs; otherwise the next met trigger curates the project (SPEC-010). A
start that fails is noted in the failure log as `worker-start`, and the next
trigger tries again.

A project without a folder, or whose memory is being deleted, has nothing to
resume, nor has a project whose curation record cannot be read: the memory
worker makes the record again, without the stop (TBL-009).
"""
import contextlib

from . import base, clock, commands, curation_triggers, curation_worker, fence_plan, files, locks, revision_io
from . import worker_launch

# The commands' shared lock wait, within one bound for the whole command.
WAIT, SECONDS = 10.0, 60.0
SAY = {
    'stopped': 'Curation of %s stopped after three failed %s in a row (%s)',
    # The code leaves the count out, so a turn recorded before the answer, such as the answer itself, starts the
    # worker even when none waited at the preview.
    'ask': (' Resuming clears the stop and, if turns wait by then, starts the memory worker for them; otherwise '
            'the next trigger curates the project.'),
    'ask-turns': ' Resuming clears the stop and starts the memory worker for the %s.',
    'resumed': 'Curation of %s resumed; the next trigger curates the project.',
    'started': 'Curation of %s resumed, and the memory worker started for the %s.',
    'not-started': ('Curation of %s resumed; the memory worker did not start now, so the next trigger curates '
                    'the %s.'),
    'nothing': 'Curation of %s is not stopped, so there is nothing to resume.',
    'unreadable': ('The curation record of %s cannot be read, so there is no stop to clear; the memory worker '
                   'makes the record again.'),
}
WHAT = {'curate': 'attempts', 'consolidate': 'consolidations'}


def failures(progress):
    """The failed attempts that the stop came from, newest first, as `data.failures` holds them.

    They are the newest failed attempts of the stop's kind in the record's
    recent attempts, as many as its count of failures in a row, as the stop
    took its errors from them.
    """
    kind = progress['stopped']['by']
    if kind == 'curate':
        count = progress['failures']['count'] if 'failures' in progress else 0
    else:
        count = progress['consolidation']['failures']
    found = []
    for attempt in progress['recent']:
        if len(found) >= count:
            break
        if attempt['kind'] == kind and attempt['result'] == 'failed':
            found.append({'at': attempt['at'], 'kind': kind, 'error': attempt.get('error', 'RuntimeError')})
    return found


def cleared(progress):
    """The record's changed fields once the stop is cleared: both counts of failures in a row at zero."""
    changes = {'consolidation': dict(progress['consolidation'], failures=0)}
    if 'failures' in progress:
        changes['failures'] = dict(progress['failures'], count=0)
    return changes


def _turns(count):
    return '%d unprocessed turn%s' % (count, '' if count == 1 else 's')


def stopped_said(project, stopped):
    """The stop (SPEC-018) as the status and resume name it: what failed three times in a row, and the errors."""
    return SAY['stopped'] % (project, WHAT[stopped['by']], ', '.join(stopped['errors']) or 'RuntimeError')


def _ask(project, progress, unprocessed):
    say = stopped_said(project, progress['stopped']) + '.'
    return say + (SAY['ask-turns'] % _turns(unprocessed) if unprocessed else SAY['ask'])


def resume(context):
    """API-019 after the runner's gates, with the format-2 store binding as `context.memory`."""
    project = context.project.name
    memory = context.memory
    root = memory.folder / 'projects' / base.project_folder_name(project)
    data = {'project': project}

    def nothing(say):
        return commands.result('resume', data, say % project, 'nothing')
    if memory.fence.check(root) is None:
        return nothing(SAY['nothing'])
    deadline = clock.now() + SECONDS
    applied = []
    try:
        with contextlib.ExitStack() as leases:
            for kind in ('curation', 'layer'):
                leases.enter_context(memory.lease(root / (kind + '.lock'), kind, deadline, 'skill',
                                                  acquire_deadline=min(deadline, clock.now() + WAIT)))
            if curation_worker._deleted(memory, root):
                return nothing(SAY['nothing'])
            try:
                progress = revision_io.read(memory, root, deadline)
            except files._RESTORABLE + (files.RestoreNeeded,) as error:
                memory.note(error, step='skill')
                return nothing(SAY['unreadable'])
            data['unprocessed'] = curation_triggers.scan(memory, root).count
            memory.check(deadline, memory.held)
            if 'stopped' not in progress:
                return nothing(SAY['nothing'])
            data['failures'] = failures(progress)

            def apply():
                revision_io.update_progress(memory, root, fence_plan.snapshot(progress), cleared(progress),
                                            deadline, removed=('stopped',))
                applied.append(True)
            # The code leaves out the unprocessed turns, which the person's own answer adds to.
            bound = {'project': project, 'stopped': progress['stopped'], 'failures': data['failures']}
            answer = context.confirm(data, _ask(project, progress, data['unprocessed']), apply, bound=bound)
            if not applied:
                return answer
    except locks.LockBusy:
        return commands.common_result('resume', 'lock-busy')
    if not data['unprocessed']:
        return commands.result('resume', data, SAY['resumed'] % project)
    # After the leases: the launcher starts no worker while this process holds a lease of the store.
    started = worker_launch.launch(memory, project, 'skill', clock.now() + 10, memory.logger,
                                   expected_device=memory.device)
    say = SAY['started' if started else 'not-started'] % (project, _turns(data['unprocessed']))
    return commands.result('resume', data, say)
