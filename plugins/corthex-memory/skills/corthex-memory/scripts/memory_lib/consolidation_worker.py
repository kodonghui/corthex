"""Consolidate a project: API-005 step 3 (SPEC-019, SPEC-020, SPEC-012, SPEC-018, SPEC-144; TASK-089, TASK-090).

Not wired: `scripts/worker.py` calls `consolidate` after `curation_worker.curate`,
under the same curation lease, from the 0.3.0 activation on. Until then no
hook or command reaches this module, so installed C1 behaviour is unchanged.

A consolidation is due once `consolidation.due` has come (SPEC-015 sets it),
or 7 days after the last consolidation ended or, before the first, after
memory was last turned on for the project (the configuration's `since`).
Unprocessed turns and a curation trigger are not needed. It sends the current
items in groups by kind, in the order of stage 06's kinds, and a kind's items
in parts by time, oldest first: each part is one merge-2 request, sized as
API-009 sizes a curate request, with the open candidates whose two items it
carries. Once every group has succeeded, the last request (state-1) sends the
current state and the item list and asks for a shorter state.

Each request is built under the layer lease from the layer as it then is.
The lease is released while the request is counted and sent, so that a forget
can change the layer meanwhile, and taken again to apply.

- A merge saves a new item that carries its items' quotes, copied with their
  provenance (SPEC-020), and `merges`; its items are superseded by it, a pin
  on one of them moves to it and their open candidates settle, in one item
  batch with the candidates of the disagreements that the answer names
  (TBL-120). Then each state line that cites a merged item cites the item
  that merged it, in a `recited` change (state_rewrite), so that a later
  request that fails leaves no line citing a merged item.
- The last answer rewrites the state (state_rewrite, TASK-090): each earlier
  version goes to TBL-119 first, with the reason `consolidation`.
- A failed request leaves its group, or the state, as it was, and the groups
  before it stay applied. It counts one failed consolidation, writes a
  `consolidation-failed` notice and ends the run, and consolidation stays
  due; three in a row stop the project (`stopped` by `consolidate`,
  SPEC-018). So does a recited change or the last answer's rewrite whose
  required earlier version could not be appended: the state stays as it was.
- A fence that a forget, an undo or a tombstone moved after a request was
  built makes it stale: nothing of it applies, nothing counts as a failure,
  and the request is built again from the layer as it now is; three stale
  requests in a row end the run. The fence is compared when the layer lease
  is taken again to apply; after that only this run moves it.
- A project tombstone (TBL-017), a lost curation lease, a layer lease held
  elsewhere past 150 seconds and the run's last 60 seconds end the run as
  curation's do. A run that ends before the last answer applied leaves what
  it applied, and consolidation stays due.
- Every apply adds itself to the run's log (TBL-121) before the record
  counts it. A consolidation that ends counts zero failures, records its
  time as `last` and removes `due`.

The record's attempt counts the merges applied and dropped, with `reasons`
by reason, says what the last answer did to the state, with `edit_reasons`
for the lines it dropped, and names the run when it applied anything.
"""
from collections import Counter
import contextlib
import copy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json

from . import (base, clock, conflict_plan, conflict_types, curator_answers, curator_document, curation_worker,
               diagnostics, fence_plan, files, item_io, item_types, locks, model_client, model_count, request_budget,
               request_inputs, revision_io, run_log, state_io, state_rewrite)

GROUPS = ('decision', 'preference', 'lesson', 'reference', 'fact')  # stage 06's order of kinds
WEEK = timedelta(days=7)
FAILURES = 3    # failed consolidations in a row stop the project (SPEC-018)
STALE = 3       # stale requests in a row end the run; consolidation stays due
_BREAKS, _LEASES = curation_worker._BREAKS, curation_worker._LEASES
_Failed = curation_worker._Failed


@dataclass(frozen=True)
class Outcome:
    # done, not-due, failed, stopped, stale, deleted, consent, disabled, key, configuration, lost-lock, busy,
    # deadline or error
    reason: str
    attempts: tuple   # the attempts that this run added to the record, oldest first
    requests: int     # merge-2 and state-1 requests sent
    applied: bool     # whether this run applied anything


class _Run:
    """What one consolidation has done so far."""

    def __init__(self, memory, when):
        self.id = curation_worker._run_id()
        self.log = run_log.start(self.id, 'consolidate', base.utc_time(when), memory.device)
        self.done = set()       # items that an applied request carried or saved: not sent again in this run
        self.merged = 0         # merges applied
        self.dropped = Counter()  # merges dropped, by reason (format2.MERGE_REASONS)
        self.edits = {}         # lines of the last answer dropped, by reason (format2.EDIT_REASONS)
        self.requests = 0
        self.applied = False
        self.attempts = []
        self.stale = 0


def _time(value):
    return datetime.strptime(value, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=timezone.utc)


def due(consolidation, since, when=None):
    """Whether a consolidation is due (SPEC-019): `consolidation` is the record's field, `since` the project's."""
    now = base.utc_time(when)
    if 'due' in consolidation and consolidation['due'] <= now:
        return True
    return _time(consolidation.get('last', since)) + WEEK <= _time(now)


@contextlib.contextmanager
def _layer(memory, root, deadline):
    with memory.lease(root / 'layer.lock', 'layer', deadline, 'consolidate',
                      acquire_deadline=min(deadline, clock.now() + curation_worker.LAYER_WAIT)) as lease:
        yield lease


def _read(memory, deadline):
    return lambda path: memory.fence.read(path, deadline)


def _logged(memory, root, log, progress, at, effects, check):
    """Add one apply to the run log and write it; None, with the failure noted, once it cannot be."""
    if log is None:
        return None
    try:
        log = run_log.add(log, progress, at, effects)
    except (ValueError, TypeError, LookupError) as error:
        memory.note(error, step='consolidate')
        return None
    run_log.write(memory, root, log, check)
    return log


def _noted(memory, held):
    """Note the error that kept the state as it was in the failure log; the record's error for it (TBL-009)."""
    code = held if held in diagnostics.EXCEPTIONS.values() else 'RuntimeError'
    memory.note(code, step='consolidate')
    return code


def _record(run, at, result, error=None, state=None):
    """The attempt as the record's `recent` holds it (TBL-009)."""
    attempt = {'at': at, 'kind': 'consolidate', 'result': result}
    if error is not None:
        attempt['error'] = error
    if result == 'ok' or run.applied or run.dropped:
        attempt.update(applied=run.merged, dropped=sum(run.dropped.values()))
        if run.dropped:
            attempt['reasons'] = {reason: run.dropped[reason] for reason in curator_answers.MERGE_REASONS
                                  if run.dropped[reason]}
    if state is not None:
        attempt['state'] = state
    if run.edits:
        attempt['edit_reasons'] = dict(run.edits)
    if run.applied:
        attempt['run'] = run.id
    return attempt


def _errors(progress, code, count):
    """The kinds of error of the last `count` failed consolidations, this one included: distinct, oldest first."""
    found = [code]
    for attempt in progress['recent']:
        if len(found) == count:
            break
        if attempt['kind'] == 'consolidate' and attempt['result'] == 'failed':
            found.append(attempt.get('error', 'RuntimeError'))
    return list(dict.fromkeys(reversed(found)))


def _failure(memory, root, deadline, run, code, at):
    """Record a failed consolidation and its notice under both leases: whether it stopped the project."""
    fresh = revision_io.read(memory, root, deadline)
    consolidation = dict(fresh['consolidation'])
    consolidation['failures'] += 1
    attempt = _record(run, at, 'failed', error=code)
    changes = {'recent': curation_worker._recent(fresh, attempt), 'consolidation': consolidation}
    stopped = consolidation['failures'] >= FAILURES
    if stopped:
        changes['stopped'] = {'at': at, 'by': 'consolidate',
                              'errors': _errors(fresh, code, consolidation['failures'])}
    revision_io.update_progress(memory, root, fence_plan.snapshot(fresh), changes, deadline)
    run.attempts.append(attempt)
    try:
        files.replace_bytes(root / 'notices' / 'consolidation-failed.json',
                            item_types.notice_bytes({'at': at, 'kind': 'consolidation-failed', 'error': code}), True,
                            check=revision_io.guard(memory, root, deadline, curator=True),
                            path_check=memory.fence.check)
    except _LEASES:
        raise
    except _BREAKS as error:
        memory.note(error, step='consolidate')
    return 'stopped' if stopped else 'failed'


def _stale(memory, root, deadline, run, at):
    fresh = revision_io.read(memory, root, deadline)
    attempt = {'at': at, 'kind': 'consolidate', 'result': 'stale'}
    revision_io.update_progress(memory, root, fence_plan.snapshot(fresh),
                                {'recent': curation_worker._recent(fresh, attempt)}, deadline)
    run.attempts.append(attempt)
    run.stale += 1
    return 'stale'


def _send(memory, project, owner, deadline, settings, instructions, source, schema, run):
    """Send one request without the layer lease; its answer, decoded from JSON."""
    def check():
        memory.check(deadline, (owner,))
    curation_worker._left(deadline)
    result = model_client.send(memory, project=project, instructions=instructions, source=source, schema=schema,
                               config=copy.deepcopy(settings.document), check=check,
                               deadline=deadline - curation_worker.RESERVE)
    run.requests += 1
    failure = result.response.failure
    if failure is not None:
        if failure.code == 'timeout' and clock.now() >= deadline - curation_worker.RESERVE:
            raise locks.LockBusy()  # the run's own time ran out, not the request's
        raise _Failed(failure.code)
    try:
        return json.loads(result.response.text)
    except ValueError:
        raise _Failed('bad-answer') from None


def _counter(memory, project, owner, deadline, settings, instructions, schema):
    def count(source):
        curation_worker._left(deadline)
        return model_count.count(memory, project=project, instructions=instructions, source=source, schema=schema,
                                 config=copy.deepcopy(settings.document),
                                 check=lambda: memory.check(deadline, (owner,)),
                                 deadline=deadline - curation_worker.RESERVE).tokens
    return count


def plan_merges(checked, *, items, conflicts, group, at, device, run, make_id=None):
    """The item additions, status changes, run log merges and TBL-120 value for checked merges.

    `items` are the stored item records and `conflicts` the TBL-120 value,
    both read under the layer lease. Each merge saves a new current item with
    a code-made ID, and its items are superseded by it. Every open candidate
    that names an item no longer current settles, and each pair that the
    answer names opens one candidate when both of its items are still current
    and no open candidate names it in either order.
    """
    make_id = base.new_id if make_id is None else make_id
    final = {value['id']: value for value in items}
    additions, transitions, merges = [], [], []
    for merge in checked.merges:
        if any(final.get(item, {}).get('status') != 'current' for item in merge.items):
            raise ValueError('existing current item required')
        item = make_id('i')
        if item in final:
            raise ValueError('code-made ID collision')
        record = curator_answers.merged_record(merge, group=group, item=item, at=at, device=device)
        final[item] = record
        additions.append(record)
        for target in merge.items:
            transitions.append({'id': target, 'status': 'superseded', 'superseded_by': item})
            final[target] = dict(final[target], status='superseded', superseded_by=item)
        merges.append({'item': item, 'merged': list(merge.items)})
    current = {item for item, value in final.items() if value['status'] == 'current'}
    value, settled = conflict_plan.settle(conflicts, current, at)
    value, opened = conflict_plan.record(value, checked.conflicts, final, at=at, run=run, by='consolidate',
                                         make_id=make_id)
    return {'additions': additions, 'transitions': transitions, 'merges': merges, 'conflicts': value,
            'opened': opened, 'settled': settled}


def _recite(memory, root, deadline, run, proof, at, check):
    """Recite the lines that cite merged items: (the latest progress or None, the held error or None).

    The progress is the reservation's when a required earlier version could
    not be appended, so that the caller's next write proves the fence as it is.
    """
    recited = state_rewrite.apply_recite(memory, root, proof, at=at, run=run.id, deadline=deadline)
    if recited['lines']:
        run.applied = True
        run.log = _logged(memory, root, run.log, recited['progress'], at, run_log.lines(recited['lines']), check)
    return recited['progress'], recited['held']


def _apply_merge(memory, root, deadline, run, group, part, checked, expected, at):
    """Apply a part's checked merges and recite their lines under both leases; the held error or None."""
    check = revision_io.guard(memory, root, deadline, curator=True)
    latest = None
    if checked.merges or checked.conflicts:
        guard, _ = item_io._checked(memory, root, expected, deadline, curator=True)
        items = item_io._items(memory, root, deadline, guard)
        conflicts = item_io._record(memory, root / 'layer/conflicts.json', conflict_types.parse_conflicts, deadline,
                                    guard)
        planned = plan_merges(checked, items=items, conflicts=conflicts, group=group, at=at, device=memory.device,
                              run=run.id)
        if planned['additions'] or planned['opened'] or planned['settled']:
            result = item_io.apply(memory, root, expected, planned['additions'], planned['transitions'], at,
                                   deadline, run_id=run.id, conflicts=planned['conflicts'])
            latest = result['progress']
            run.applied = True
            run.log = _logged(memory, root, run.log, latest, at, dict(result['effects'], merges=planned['merges']),
                              check)
            run.done.update(record['id'] for record in planned['additions'])
    run.merged += len(checked.merges)
    run.dropped.update(checked.dropped)
    proof = expected if latest is None else fence_plan.snapshot(latest)
    recited, held = _recite(memory, root, deadline, run, proof, at, check)
    latest = recited or latest
    # The part's merges stay applied even when its lines could not be recited: the request counts.
    fresh = revision_io.read(memory, root, deadline)
    revision_io.update_progress(memory, root, expected if latest is None else fence_plan.snapshot(latest),
                                {'applies': fresh['applies'] + 1}, deadline)
    run.done.update(value['id'] for value in part.items)
    return None if held is None else _noted(memory, held)


def _apply_errors(memory, root, deadline, run, at, unmoved, error):
    """The outcome of an apply that raised: stale while only another writer moved the fence, else failed."""
    if isinstance(error, fence_plan.Stale):
        if unmoved():
            return _stale(memory, root, deadline, run, at)
        memory.note(error, step='consolidate')
        return _failure(memory, root, deadline, run, curation_worker._code(error), at)
    if isinstance(error, (item_io.WriteFailed, state_io.PublicationFailed)):
        chain = curation_worker._chain(error)
        for cause in chain:
            if isinstance(cause, _LEASES):
                raise cause
        if any(isinstance(cause, fence_plan.Stale) for cause in chain) and unmoved():
            return _stale(memory, root, deadline, run, at)
        memory.note(chain[-1], step='consolidate')
        return _failure(memory, root, deadline, run, curation_worker._code(chain[-1]), at)
    memory.note(error, step='consolidate')
    return _failure(memory, root, deadline, run, curation_worker._code(error), at)


def _open(memory, root, deadline, when):
    """Under the layer lease: (None, progress), or why the run ends ('deleted' or 'stopped')."""
    if curation_worker._deleted(memory, root):
        return 'deleted', None
    progress = curation_worker._progress(memory, root, deadline, when)
    if 'stopped' in progress:
        return 'stopped', None
    return None, progress


def _merge(memory, project, root, owner, deadline, settings, when, group, run):
    """One part of a group: None when the group has no part left, else 'ok', 'stale', 'failed', 'stopped' or
    'deleted'."""
    read = _read(memory, deadline)
    with _layer(memory, root, deadline):
        reason, progress = _open(memory, root, deadline, when)
        if reason is not None:
            return reason
        at = base.utc_time(when)
        try:
            layer = request_inputs.layer(root, read)
        except _LEASES:
            raise
        except _BREAKS as error:
            memory.note(error, step='consolidate')
            return _failure(memory, root, deadline, run, curation_worker._code(error), at)
    pending = sorted((value for value in layer.current if value['kind'] == group and value['id'] not in run.done),
                     key=lambda value: (value['saved'], value['id']))
    if len(pending) < 2:
        return None
    expected, code, part, checked = fence_plan.snapshot(progress), None, None, None
    schema = curator_answers.merge_schema()
    try:
        part = request_budget.merge_part(pending, layer.candidates, group=group, schema=schema,
                                         count=_counter(memory, project, owner, deadline, settings, 'merge-2', schema))
        if len(part.items) < 2:
            # Items too large to go two to a request have nothing to merge with.
            run.done.update(value['id'] for value in part.items)
            return 'ok'
        answer = _send(memory, project, owner, deadline, settings, 'merge-2', part.source, schema, run)
        try:
            checked = curator_answers.check_merge(answer, items=part.items, device=memory.device, rules=schema)
        except ValueError:
            raise _Failed('bad-answer') from None
    except _LEASES + (model_client.MissingKey,):
        raise
    except _Failed as failed:
        code = failed.code
    except _BREAKS as error:
        memory.note(error, step='consolidate')
        code = curation_worker._code(error)

    def unmoved():
        return fence_plan.matches(revision_io.read(memory, root, deadline), expected)

    with _layer(memory, root, deadline):
        # A forget, an undo or a tombstone that moved the fence after the request was built makes it stale,
        # whether it succeeded or failed (SPEC-012). From here on only this run moves the fence.
        if not unmoved():
            return _stale(memory, root, deadline, run, at)
        if code is not None:
            return _failure(memory, root, deadline, run, code, at)
        try:
            held = _apply_merge(memory, root, deadline, run, group, part, checked, expected, at)
        except _LEASES:
            raise
        except _BREAKS as error:
            return _apply_errors(memory, root, deadline, run, at, unmoved, error)
        if held is not None:
            return _failure(memory, root, deadline, run, held, at)
    run.stale = 0
    return 'ok'


def _shorten(memory, project, root, owner, deadline, settings, when, run):
    """The last request: 'ok', 'stale', 'failed', 'stopped' or 'deleted'."""
    read = _read(memory, deadline)
    schema = curator_answers.state_schema()
    with _layer(memory, root, deadline):
        reason, progress = _open(memory, root, deadline, when)
        if reason is not None:
            return reason
        at = base.utc_time(when)
        try:
            # Lines that an earlier merge could not recite cite the items that merged them first.
            check = revision_io.guard(memory, root, deadline, curator=True)
            recited, held = _recite(memory, root, deadline, run, fence_plan.snapshot(progress), at, check)
            if held is not None:
                return _failure(memory, root, deadline, run, _noted(memory, held), at)
            if recited is not None:
                progress = recited
            layer = request_inputs.layer(root, read)
        except _LEASES:
            raise
        except _BREAKS as error:
            return _apply_errors(memory, root, deadline, run, at, lambda: False, error)
        expected = fence_plan.snapshot(progress)
        if not layer.lines:
            # No line to shorten: nothing is sent and the consolidation ends.
            return _done(memory, root, deadline, run, at, expected, 'kept')
    code, answer, listed = None, None, None
    try:
        listed = request_budget.state_list(layer, schema)
        source = curator_document.shorten(lines=list(layer.lines), items=list(listed.items), form=listed.form,
                                          candidates=list(listed.candidates), omitted=listed.omitted)
        sent = _send(memory, project, owner, deadline, settings, 'state-1', source, schema, run)
        try:
            answer = curator_answers.decode(sent, schema)
        except ValueError:
            raise _Failed('bad-answer') from None
    except _LEASES + (model_client.MissingKey,):
        raise
    except _Failed as failed:
        code = failed.code
    except _BREAKS as error:
        memory.note(error, step='consolidate')
        code = curation_worker._code(error)

    def unmoved():
        return fence_plan.matches(revision_io.read(memory, root, deadline), expected)

    with _layer(memory, root, deadline):
        if not unmoved():
            return _stale(memory, root, deadline, run, at)
        if code is not None:
            return _failure(memory, root, deadline, run, code, at)
        check = revision_io.guard(memory, root, deadline, curator=True)
        try:
            outcome = state_rewrite.apply_rewrite(memory, root, expected, answer['state'],
                                                  lines=[line['id'] for line in layer.lines],
                                                  listed=[value['id'] for value in listed.items], at=at, run=run.id,
                                                  deadline=deadline)
        except _LEASES:
            raise
        except _BREAKS as error:
            return _apply_errors(memory, root, deadline, run, at, unmoved, error)
        run.edits = dict(outcome['dropped'])
        if outcome['held'] is not None:
            return _failure(memory, root, deadline, run, _noted(memory, outcome['held']), at)
        latest = expected
        if outcome['lines']:
            run.applied = True
            run.log = _logged(memory, root, run.log, outcome['progress'], at, run_log.lines(outcome['lines']), check)
            latest = fence_plan.snapshot(outcome['progress'])
        return _done(memory, root, deadline, run, at, latest, outcome['state'], counted=True)


def _done(memory, root, deadline, run, at, expected, state, counted=False):
    """Record a consolidation that ended, under both leases: no failures, `last`, no `due` (SPEC-019)."""
    fresh = revision_io.read(memory, root, deadline)
    attempt = _record(run, at, 'ok', state=state)
    changes = {'recent': curation_worker._recent(fresh, attempt),
               'consolidation': {'failures': 0, 'last': at}}
    if counted:
        changes['applies'] = fresh['applies'] + 1
    revision_io.update_progress(memory, root, expected, changes, deadline)
    run.attempts.append(attempt)
    return 'ok'


def _gated(memory, root, owner, project, deadline):
    """API-005 step 3's conditions before each request: (None, settings) or (why the run ends, None)."""
    curation_worker._owned(memory, root, owner)
    memory.check(deadline, (owner,))
    curation_worker._left(deadline)
    return curation_worker._gate(memory, project, deadline)


def consolidate(memory, project, owner, deadline, *, when=None):
    """Consolidate the project when it is due, under the caller's tracked curation lease.

    `memory` is the format-2 store binding, `owner` the project's curation
    lease that the caller took through `memory.lease` and releases, and
    `deadline` the run's absolute monotonic end; each request also keeps to
    its own limit of 30 minutes. `when` fixes the run's time, for tests.
    Returns why the run ended, the attempts it recorded, the requests it sent
    and whether it applied anything.
    """
    root = memory.folder / 'projects' / base.project_folder_name(project)
    run = _Run(memory, when)

    def end(reason):
        return Outcome(reason, tuple(run.attempts), run.requests, run.applied)

    try:
        reason, settings = _gated(memory, root, owner, project, deadline)
        if reason is not None:
            return end(reason)
        with _layer(memory, root, deadline):
            reason, progress = _open(memory, root, deadline, when)
            if reason is not None:
                return end(reason)
            if not due(progress['consolidation'], settings.values['projects'][project]['since'], when):
                return end('not-due')
        for group in GROUPS:
            while True:
                reason, settings = _gated(memory, root, owner, project, deadline)
                if reason is not None:
                    return end(reason)
                step = _merge(memory, project, root, owner, deadline, settings, when, group, run)
                if step is None:
                    break
                if step in ('failed', 'stopped', 'deleted'):
                    return end(step)
                if step == 'stale' and run.stale >= STALE:
                    return end('stale')
        while True:
            reason, settings = _gated(memory, root, owner, project, deadline)
            if reason is not None:
                return end(reason)
            step = _shorten(memory, project, root, owner, deadline, settings, when, run)
            if step == 'ok':
                return end('done')
            if step != 'stale':
                return end(step)
            if run.stale >= STALE:
                return end('stale')
    except locks.LostLock:
        memory.note(locks.LostLock(), step='consolidate')
        return end('lost-lock')
    except locks.LockBusy:
        return end('deadline' if clock.now() >= deadline - curation_worker.RESERVE else 'busy')
    except model_client.MissingKey:
        return end('key')
    except _BREAKS as error:
        memory.note(error, step='consolidate')
        return end('error')
