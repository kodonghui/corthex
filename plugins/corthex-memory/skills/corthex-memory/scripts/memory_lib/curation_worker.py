"""Curate a project's unprocessed turns: API-005 step 2 (SPEC-012, SPEC-014 to SPEC-018, SPEC-144; TASK-088).

Not wired: `scripts/worker.py` calls `curate` under the project's curation
lease from the 0.3.0 activation on. Until then no hook or command reaches this
module, so installed C1 behaviour is unchanged.

Each attempt reads the curation record, the curated layer and the unprocessed
turns under the layer lease, and releases that lease while it counts and sends
its requests, so that a forget can change the layer meanwhile; it takes the
lease again to apply. Its batch is one request of whole turns, oldest first,
or every part of one turn that is too large alone (SPEC-015). The parts'
answers apply together once the last part has succeeded: a quote must lie
within its own part, and a later part cannot change an item that an earlier
part ended.

- A failed attempt leaves its turns unprocessed. It is counted against the
  first unprocessed turn it started from, writes a `curation-failed` notice
  and ends the run; the next trigger tries again. Three in a row from the
  same turn stop curation for the project (SPEC-018). A successful attempt
  sets the count to zero.
- A fence that changed after the request was built, as a forget, an undo or a
  tombstone changes it, makes the attempt stale, whether its requests
  succeeded or failed: nothing applies, nothing counts as a failure, and the
  next attempt builds the request again from the raw log as it now is
  (SPEC-012). Three stale attempts in a row end the run. The fence is
  compared when the layer lease is taken again to apply; after that only the
  attempt itself moves it, so a later error is a failure, never stale, and
  the request is not sent again in the same run.
- When the line edits fail after the item changes were published and before
  they moved the fence, the state stays as it was and the item changes and
  the turns count, as when a required history append fails (SPEC-017); the
  failure log notes the error. A failure after anything else was published
  keeps what was published and leaves the turns unprocessed: the next run
  curates them again and consolidation merges what was saved twice (TBL-009).
- Every file of a request is read through the store's path fence, so that a
  link or junction in the project folder ends the run (`lost-lock`) before
  anything is sent.
- A project tombstone (TBL-017) ends the run before anything is read or sent
  (`deleted`). Only sync makes one, and C2 has no sync to apply it; until a
  release applies its cutoff, no request may carry what it deleted.
- A lost curation lease applies nothing more and ends the run; so does the
  run's deadline, whose last 60 seconds no request starts in.
- The raw logs of a batch are flushed to disk before any quote of them applies
  or any of their entries counts as processed (TBL-009). The item changes and
  then the line edits each add their apply to the run log (TBL-121) before
  the record counts the turns; then each advanced log's markers are replaced
  (TBL-008).

The record's `applied` and `dropped` count the answers' item changes, with
`reasons` giving the dropped ones by reason; its `state` says what the line
edits did, with `edit_reasons` giving the dropped edits by reason. Each
`Attempt` gives the same counts. Each request's usage lines hold its size
without any of its text: its turns, its parts when it carries one part of a
turn, its item list's form and its working estimate (TBL-003; TASK-116).
"""
from collections import Counter
import contextlib
import copy
from dataclasses import dataclass, replace
import json
import os
import secrets
import stat

from . import (base, clock, configuration, curate_apply, curation_rebuild, curator_answers, curator_document,
               diagnostics, fence_plan, files, index_io, item_io, item_types, locks, model_access, model_client,
               model_count, request_budget, request_inputs, revision_io, run_log, state_edits, state_io,
               worker_support)

INSTRUCTIONS = 'curate-2'
FAILURES = 3        # failed attempts in a row from one first turn stop curation (SPEC-018)
STALE = 3           # stale attempts in a row end the run; the next trigger goes on
RECENT = 10         # attempts that the record keeps, newest first (TBL-009)
LAYER_WAIT = 150.0  # longer than a layer lease's 120 seconds without refresh, so a lease left behind is taken over
RESERVE = 60.0      # the last seconds of a run, kept for an apply: no request starts in them
_BREAKS = (OSError, ValueError, TypeError, LookupError, RuntimeError)
_LEASES = (locks.LostLock, locks.LockBusy)


@dataclass(frozen=True)
class Attempt:
    record: dict      # the attempt as the record's `recent` holds it (TBL-009)
    first: tuple      # (log, turn) of the first unprocessed turn that it started from
    turns: tuple      # ((log, turn), ...) that its requests carried, oldest first
    requests: int     # curate requests sent; each part of a turn is one
    dropped: dict     # item changes dropped, by reason (curator_answers.REASONS)
    edits: dict       # line edits dropped, by reason (state_edits.REASONS)
    held: object      # the error that kept the state as it was, or None
    stopped: bool     # whether this attempt stopped curation for the project


@dataclass(frozen=True)
class Outcome:
    # done, failed, stopped, stale, deleted, consent, disabled, key, configuration, lost-lock, busy, deadline
    # or error
    reason: str
    attempts: tuple   # this run's attempts, oldest first


class _Failed(Exception):
    """An attempt that failed for `code`, an error of TBL-009."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


class _Moved(Exception):
    """A forget, an undo or a tombstone moved the fence after the request was built: the attempt is stale, and
    nothing more of it is sent (SPEC-012)."""


def _run_id():
    """A run ID with 60 random bits, as base.new_id makes the other IDs (TBL-121)."""
    bits = secrets.randbits(60)
    return 'r_' + ''.join(base.CROCKFORD[(bits >> shift) & 31] for shift in range(55, -1, -5))


def _code(error):
    """The record's error for an exception: its nearest built-in class (TBL-009)."""
    kind = diagnostics.error_kind(error)
    return kind if kind in diagnostics.EXCEPTIONS.values() else 'RuntimeError'


def _chain(error):
    found = []
    while error is not None and all(error is not seen for seen in found):
        found.append(error)
        error = error.__cause__
    return found


def _left(deadline):
    """Refuse to start a request in the run's last RESERVE seconds."""
    if clock.now() >= deadline - RESERVE:
        raise locks.LockBusy()


def _owned(memory, root, owner):
    if (not any(lease is owner for lease in memory.held) or owner.path != root / 'curation.lock' or
            owner.device != memory.device or owner.policy != locks.POLICIES['curation']):
        raise locks.LostLock()


@contextlib.contextmanager
def _layer(memory, root, deadline):
    with memory.lease(root / 'layer.lock', 'layer', deadline, 'curate',
                      acquire_deadline=min(deadline, clock.now() + LAYER_WAIT)) as lease:
        yield lease


def _unmoved(memory, root, deadline, expected):
    """Whether the fence is still where it was when the request was built, compared under the layer lease.

    Asked before each token count, each request and each further attempt of a request, so that nothing built
    before a forget, an undo or a tombstone is sent after it (SPEC-012).
    """
    with _layer(memory, root, deadline):
        return fence_plan.matches(revision_io.read(memory, root, deadline), expected)


def _gate(memory, project, deadline):
    """API-005 step 2's conditions: (None, the configuration), or (why the run ends, None)."""
    try:
        settings = memory.configuration(memory.note, deadline=min(
            deadline, clock.now() + worker_support.OPERATION_SECONDS))
    except configuration.ConfigurationInvalid:
        return 'configuration', None
    if not settings.consented():
        return 'consent', None
    if not settings.enabled(project):
        return 'disabled', None
    try:
        if model_access.Credentials.read().headers('anthropic') is None:
            return 'key', None
    except ValueError:
        return 'key', None
    return None, settings


def _progress(memory, root, deadline, when):
    """The record; made again from the raw logs when neither it nor its backup parses (TBL-009)."""
    try:
        return revision_io.read(memory, root, deadline)
    except files._RESTORABLE:
        return curation_rebuild.rebuild(memory, root, deadline, when)


def _deleted(memory, root):
    """Whether the project has a tombstone (TBL-017), or a copy of one, in its curated layer."""
    folder = root / 'layer'
    if memory.fence.check(folder) is None:
        return False
    return any(name == 'deleted.json' or name.startswith('deleted.json.') for name in os.listdir(str(folder)))


def _sessions(memory, root, progress, read):
    """(sessions with unprocessed turns, by their first turn; their raw logs' stored entries)."""
    stored, sessions = {}, []
    for log in curation_rebuild._logs(memory, root):
        entries = request_inputs.entries(root, log, read)
        session = curator_document.session(log, entries, progress['logs'].get(log, 0))
        if session['turns']:
            stored[log] = entries
            sessions.append(session)
    sessions.sort(key=lambda s: (min(e['at'] for e in s['turns'][0]['entries']), s['log']))
    return sessions, stored


def _merged(entry):
    """An entry's forgotten ranges as curator_document.entry_text merges them."""
    merged = []
    for start, end in sorted((int(pair[0]), int(pair[1])) for pair in entry.get('forgotten', ())):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def _stored(entry, start, end):
    """The stored range of an entry that [start, end) of its shown text shows."""
    text, segments, used, shown = entry['text'], [], 0, 0
    for low, high in _merged(entry):
        segments.append((shown, shown + low - used, used, low, False))
        shown += low - used
        segments.append((shown, shown + len(curator_document.FORGOTTEN), low, high, True))
        shown += len(curator_document.FORGOTTEN)
        used = high
    segments.append((shown, shown + len(text) - used, used, len(text), False))

    def place(position, side):
        for first, last, low, high, marker in segments:
            if first <= position <= last:
                if not marker:
                    return low + position - first
                if position == first or position != last and side == 'start':
                    return low
                return high
        raise ValueError('invalid shown range')
    return place(start, 'start'), place(end, 'end')


def _confined(entry, start, end):
    """A copy of a stored entry that is forgotten outside [start, end) of its shown text."""
    low, high = _stored(entry, start, end)
    ranges = [[int(pair[0]), int(pair[1])] for pair in entry.get('forgotten', ())]
    if low > 0:
        ranges.append([0, low])
    if high < len(entry['text']):
        ranges.append([high, len(entry['text'])])
    value = dict(entry)
    if ranges:
        value['forgotten'] = ranges
    return value


class _Batch:
    """One attempt's requests and what they carried."""

    def __init__(self, layer, sessions, stored, progress, planned):
        self.planned, self.requests, self.sent_requests = planned, planned.requests, 0
        self.after = {session['log']: progress['logs'].get(session['log'], 0) for session in sessions}
        self.turns = tuple(dict.fromkeys(turn for request in self.requests for turn in request.turns))
        self.stored, self.entries = stored, {}
        for log, turn in self.turns:
            self.entries.setdefault(log, []).extend(
                entry for entry in stored[log] if entry['kind'] in ('prompt', 'answer') and
                entry['seq'] > self.after[log] and int(entry['turn']) == turn)
        self.items, self.lines = list(planned.items.items), [line['id'] for line in layer.lines]

    def sent(self):
        """Everything that the batch carried: what the line edits of all its answers may cite."""
        return curator_answers.sent(items=self.items, logs=list(self.entries.items()), lines=self.lines)

    def part(self, request, ended):
        """What one part carried: its own spans of its entries, and the items as earlier parts left them."""
        whole = self.sent()
        entries = {}
        for entry, start, end in request.spans:
            log, stored = whole.entries[entry]
            entries[entry] = (log, _confined(stored, start, end))
        items = {item: dict(value, status=ended[item]) if item in ended else value
                 for item, value in whole.items.items()}
        return curator_answers.Sent(items, entries, whole.lines)

    def counts(self):
        """Each raw log's new processed count: the end of the entries after the old count that the batch carried."""
        carried = {entry['id'] for entries in self.entries.values() for entry in entries}
        counts = {}
        for log in self.entries:
            count = self.after[log]
            for entry in self.stored[log]:
                if entry['seq'] <= self.after[log]:
                    continue
                if entry['kind'] in ('prompt', 'answer') and entry['id'] not in carried:
                    break
                count = entry['seq']
            counts[log] = count
        return counts


def _check(value, sent, device):
    try:
        return curator_answers.check_curate(value, sent=sent, device=device)
    except ValueError:
        raise _Failed('bad-answer') from None


def _numbers(numbers, offset, count):
    """A line edit's change numbers in the joined answer; a number outside its own answer names none."""
    return [number if isinstance(number, bool) else number + offset if 1 <= number <= count else 0
            for number in numbers]


def _checked(batch, answers, device):
    """The checked changes of all of a batch's answers, as one answer."""
    if batch.requests[0].part is None:
        return _check(answers[0], batch.sent(), device)
    changes, dropped, ended, offset = [], Counter(), {}, 0
    state = {'change': [], 'add': [], 'remove': []}
    for request, value in zip(batch.requests, answers):
        checked = _check(value, batch.part(request, ended), device)
        count = len(value['changes'])
        for change in checked.changes:
            changes.append(replace(change, number=change.number + offset))
            for target in change.targets:
                ended[target] = 'withdrawn' if change.action == 'withdraw' else 'superseded'
        dropped.update(checked.dropped)
        for name in ('change', 'add'):
            state[name].extend(dict(edit, changes=_numbers(edit.get('changes', ()), offset, count))
                               for edit in checked.state[name])
        state['remove'].extend(checked.state['remove'])
        offset += count
    return curator_answers.Checked(tuple(changes), dict(dropped), state)


def _ranker(memory, root, values):
    def rank(text):
        connection = index_io.open_index(memory, root)
        if connection is None:
            raise index_io.IndexUnavailable()
        try:
            if index_io.state(connection, model=values['models']['embedding'], dims=values['models']['dims']):
                raise index_io.IndexUnavailable()
            return [item for item, _ in index_io.search(connection, text)]
        finally:
            connection.close()
    return rank


def _size(planned, request, schema):
    """A request's size for its usage lines (TBL-003; TASK-116), without any of its text."""
    size = {'turns': len(request.turns), 'list': planned.items.form,
            'estimate': request_budget.estimate(INSTRUCTIONS, schema, request.source)}
    if request.part is not None:
        size['parts'] = request.part[1]
    return size


def _ask(memory, project, root, owner, deadline, settings, found, batch):
    """Plan and send a batch's requests without the layer lease; its checked answers.

    `batch` is a list that gets the batch once it is planned, so that a failure can name its turns. Before each
    token count, each request and each further attempt of a request the fence is compared under the layer lease;
    once a forget, an undo or a tombstone has moved it, nothing more is sent and `_Moved` makes the attempt stale.
    """
    layer, sessions, stored, progress = found
    schema, document = curator_answers.schema(), copy.deepcopy(settings.document)
    expected = fence_plan.snapshot(progress)

    def check():
        memory.check(deadline, (owner,))

    def still():
        return _unmoved(memory, root, deadline, expected)

    def count(source):
        _left(deadline)
        if not still():
            raise _Moved()
        return model_count.count(memory, project=project, instructions=INSTRUCTIONS, source=source, schema=schema,
                                 config=document, check=check, deadline=deadline - RESERVE).tokens

    planned = request_budget.plan(layer, sessions, schema=schema, count=count, after=progress.get('conflict_after'),
                                  rank=_ranker(memory, root, settings.values))
    batch.append(_Batch(layer, sessions, stored, progress, planned))
    answers = []
    for request in planned.requests:
        _left(deadline)
        if not still():
            raise _Moved()
        result = model_client.send(memory, project=project, instructions=INSTRUCTIONS, source=request.source,
                                   schema=schema, config=document, check=check, deadline=deadline - RESERVE,
                                   size=_size(planned, request, schema), still=still)
        batch[0].sent_requests += 1
        failure = result.response.failure
        if failure is not None:
            if failure.code == 'timeout' and clock.now() >= deadline - RESERVE:
                raise locks.LockBusy()  # the run's own time ran out, not the request's
            raise _Failed(failure.code)
        try:
            answers.append(json.loads(result.response.text))
        except ValueError:
            raise _Failed('bad-answer') from None
    return _checked(batch[0], answers, memory.device)


def _flush(memory, root, logs, deadline, check):
    """Flush the batch's raw logs to disk; the layer lease keeps every rewrite of them out meanwhile."""
    flags = os.O_RDWR | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    for log in logs:
        path = root / 'raw' / (log + '.jsonl')
        check()
        info = memory.fence.check(path)
        if info is None or not stat.S_ISREG(info.st_mode):
            raise fence_plan.Stale()
        try:
            fd = files._retry(lambda: os.open(str(path), flags), deadline)
        except FileNotFoundError:
            raise fence_plan.Stale() from None
        try:
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                raise fence_plan.Stale()
            files._sync(fd)
        finally:
            os.close(fd)
    check()


def _recent(progress, attempt):
    return [attempt] + list(progress['recent'])[:RECENT - 1]


def _errors(progress, code, count):
    """The kinds of error of the last `count` failed curations, this one included: distinct, oldest first."""
    found = [code]
    for attempt in progress['recent']:
        if len(found) == count:
            break
        if attempt['kind'] == 'curate' and attempt['result'] == 'failed':
            found.append(attempt.get('error', 'RuntimeError'))
    return list(dict.fromkeys(reversed(found)))


def _failure(memory, root, deadline, first, code, at):
    """Record a failed attempt and its notice under both leases: (attempt, whether it stopped curation)."""
    fresh = revision_io.read(memory, root, deadline)
    failure = fresh.get('failures')
    count = (failure['count'] + 1 if failure and failure['count'] and (failure['log'], failure['turn']) == first
             else 1)
    attempt = {'at': at, 'kind': 'curate', 'result': 'failed', 'error': code}
    changes = {'recent': _recent(fresh, attempt), 'failures': {'count': count, 'log': first[0], 'turn': first[1]}}
    if count >= FAILURES:
        changes['stopped'] = {'at': at, 'by': 'curate', 'errors': _errors(fresh, code, count)}
    revision_io.update_progress(memory, root, fence_plan.snapshot(fresh), changes, deadline)
    try:
        files.replace_bytes(root / 'notices' / 'curation-failed.json',
                            item_types.notice_bytes({'at': at, 'kind': 'curation-failed', 'error': code}), True,
                            check=revision_io.guard(memory, root, deadline, curator=True),
                            path_check=memory.fence.check)
    except _LEASES:
        raise
    except _BREAKS as error:
        memory.note(error, step='curate')
    return attempt, count >= FAILURES


def _stale(memory, root, deadline, at):
    fresh = revision_io.read(memory, root, deadline)
    attempt = {'at': at, 'kind': 'curate', 'result': 'stale'}
    revision_io.update_progress(memory, root, fence_plan.snapshot(fresh), {'recent': _recent(fresh, attempt)},
                                deadline)
    return attempt


def _logged(memory, root, log, progress, at, effects, check):
    """Add one apply to the run log and write it; None, with the failure noted, once it cannot be."""
    if log is None:
        return None
    try:
        log = run_log.add(log, progress, at, effects)
    except (ValueError, TypeError, LookupError) as error:
        memory.note(error, step='curate')
        return None
    run_log.write(memory, root, log, check)
    return log


def _kept(memory, root, deadline, result, proof, error):
    """The line edits' outcome when they fail after the item changes were published: the state as it was.

    As when a required history append fails (SPEC-017), the item changes stay
    and the turns count, since building the request again would save the item
    changes twice. That holds only while the line edits have not moved the
    fence; otherwise, or when no item change was published, or a lease was
    lost, the error goes on.
    """
    chain = _chain(error)
    if (result is None or any(isinstance(cause, _LEASES) for cause in chain) or
            not fence_plan.matches(revision_io.read(memory, root, deadline), proof)):
        raise error
    return {'state': 'kept', 'held': _code(chain[-1]), 'dropped': {}, 'lines': (), 'progress': None}


def _apply(memory, root, deadline, batch, checked, expected, at):
    """Apply a batch's checked answers under both leases: (attempt, line edits dropped, held error, counts)."""
    check = revision_io.guard(memory, root, deadline, curator=True)
    _flush(memory, root, list(batch.entries), deadline, check)
    counts, run, latest = batch.counts(), _run_id(), None
    turns = {log: [batch.after[log] + 1, count] for log, count in counts.items()}
    log = run_log.start(run, 'curate', at, memory.device)
    result = curate_apply.apply(memory, root, expected, checked, at, run, deadline)
    if result is not None:
        latest = result['progress']
        log = _logged(memory, root, log, latest, at, dict(result['effects'], turns=turns), check)
    proof = expected if latest is None else fence_plan.snapshot(latest)
    try:
        edits = state_edits.apply(memory, root, proof, checked.state, sent=batch.sent(),
                                  saved=() if result is None else result['saved'], at=at, run=run,
                                  deadline=deadline)
    except _LEASES:
        raise
    except _BREAKS as error:
        edits = _kept(memory, root, deadline, result, proof, error)
    if edits['lines']:
        effects = run_log.lines(edits['lines'])
        if result is None:
            effects['turns'] = turns
        log = _logged(memory, root, log, edits['progress'], at, effects, check)
    if edits['progress'] is not None:
        latest = edits['progress']
    if edits['held'] is not None:
        held = edits['held']
        memory.note(held if held in diagnostics.EXCEPTIONS.values() else 'RuntimeError', step='curate')
    fresh = revision_io.read(memory, root, deadline)
    attempt = {'at': at, 'kind': 'curate', 'result': 'ok', 'applied': len(checked.changes),
               'dropped': sum(checked.dropped.values()), 'state': edits['state']}
    if checked.dropped:
        attempt['reasons'] = dict(checked.dropped)
    if edits['dropped']:
        attempt['edit_reasons'] = dict(edits['dropped'])
    if result is not None or edits['lines']:
        attempt['run'] = run
    logs = dict(fresh['logs'])
    for name, count in counts.items():
        logs[name] = max(count, logs.get(name, 0))
    changes = {'logs': logs, 'applies': fresh['applies'] + len(batch.requests), 'recent': _recent(fresh, attempt)}
    if 'failures' in fresh:
        changes['failures'] = dict(fresh['failures'], count=0)
    if batch.planned.items.after is not None:
        changes['conflict_after'] = batch.planned.items.after
    consolidation = dict(fresh['consolidation'])
    if batch.planned.items.due and consolidation.get('due', at) >= at:
        changes['consolidation'] = dict(consolidation, due=at)
    revision_io.update_progress(memory, root, expected if latest is None else fence_plan.snapshot(latest),
                                changes, deadline)
    return attempt, dict(edits['dropped']), edits['held'], counts


def _markers(memory, root, counts, deadline):
    """Replace the markers of each advanced log; a failure is noted, since markers are made again."""
    for log, count in sorted(counts.items()):
        try:
            curation_rebuild.replace_markers(memory, root, log, count, deadline)
        except _BREAKS as error:
            memory.note(error, step='curate')


def _attempt(memory, project, root, owner, deadline, settings, when):
    """One attempt: None when no turn is unprocessed, 'stopped' when the fault guard has stopped the
    project, 'deleted' when the project has a tombstone."""

    def read(path):
        return memory.fence.read(path, deadline)

    with _layer(memory, root, deadline):
        if _deleted(memory, root):
            return 'deleted'
        progress = _progress(memory, root, deadline, when)
        if 'stopped' in progress:
            return 'stopped'
        sessions, stored = _sessions(memory, root, progress, read)
        if not sessions:
            return None
        first = (sessions[0]['log'], sessions[0]['turns'][0]['seq'])
        at = base.utc_time(when)
        try:
            layer = request_inputs.layer(root, read)
        except _LEASES:
            raise
        except _BREAKS as error:
            memory.note(error, step='curate')
            record, stopped = _failure(memory, root, deadline, first, _code(error), at)
            return Attempt(record, first, (), 0, {}, {}, None, stopped)
    expected, batch, code, moved = fence_plan.snapshot(progress), [], None, False
    try:
        checked = _ask(memory, project, root, owner, deadline, settings, (layer, sessions, stored, progress), batch)
    except _LEASES + (model_client.MissingKey,):
        raise
    except _Moved:
        moved = True
    except _Failed as failed:
        code = failed.code
    except _BREAKS as error:
        memory.note(error, step='curate')
        code = _code(error)
    turns, sent = (batch[0].turns, batch[0].sent_requests) if batch else ((), 0)

    def stale():
        return Attempt(_stale(memory, root, deadline, at), first, turns, sent, {}, {}, None, False)

    def failed(code):
        record, stopped = _failure(memory, root, deadline, first, code, at)
        return Attempt(record, first, turns, sent, {}, {}, None, stopped)

    def unmoved():
        return fence_plan.matches(revision_io.read(memory, root, deadline), expected)

    with _layer(memory, root, deadline):
        # A forget, an undo or a tombstone that moved the fence after the request was built makes the
        # attempt stale, whether its requests succeeded or failed (SPEC-012). From here on only this
        # attempt moves the fence, under the layer lease.
        if moved or not unmoved():
            return stale()
        if code is not None:
            return failed(code)
        try:
            record, edits, held, counts = _apply(memory, root, deadline, batch[0], checked, expected, at)
        except _LEASES:
            raise
        except fence_plan.Stale as error:
            # A check found the layer changed without the fence: built again, unless this attempt has
            # published something, which a second request would save twice.
            if unmoved():
                return stale()
            memory.note(error, step='curate')
            return failed(_code(error))
        except (item_io.WriteFailed, state_io.PublicationFailed) as error:
            chain = _chain(error)
            for cause in chain:
                if isinstance(cause, _LEASES):
                    raise cause
            if any(isinstance(cause, fence_plan.Stale) for cause in chain) and unmoved():
                return stale()
            memory.note(chain[-1], step='curate')
            return failed(_code(chain[-1]))
        except _BREAKS as error:
            memory.note(error, step='curate')
            return failed(_code(error))
        _markers(memory, root, counts, deadline)
    return Attempt(record, first, turns, sent, dict(checked.dropped), edits, held, False)


def curate(memory, project, owner, deadline, *, when=None):
    """Curate until no unprocessed turn is left, under the caller's tracked curation lease.

    `memory` is the format-2 store binding, `owner` the project's curation
    lease that the caller took through `memory.lease` and releases, and
    `deadline` the run's absolute monotonic end; each request also keeps to
    its own limit of 30 minutes. `when` fixes the attempts' time, for tests.
    Returns why the run ended and its attempts.
    """
    root = memory.folder / 'projects' / base.project_folder_name(project)
    attempts, stale = [], 0

    def end(reason):
        return Outcome(reason, tuple(attempts))

    while True:
        try:
            _owned(memory, root, owner)
            memory.check(deadline, (owner,))
            _left(deadline)
            reason, settings = _gate(memory, project, deadline)
            if reason is not None:
                return end(reason)
            attempt = _attempt(memory, project, root, owner, deadline, settings, when)
        except locks.LostLock:
            memory.note(locks.LostLock(), step='curate')
            return end('lost-lock')
        except locks.LockBusy:
            return end('deadline' if clock.now() >= deadline - RESERVE else 'busy')
        except model_client.MissingKey:
            return end('key')
        except _BREAKS as error:
            memory.note(error, step='curate')
            return end('error')
        if attempt is None:
            return end('done')
        if attempt in ('stopped', 'deleted'):
            return end(attempt)
        attempts.append(attempt)
        if attempt.stopped:
            return end('stopped')
        if attempt.record['result'] == 'failed':
            return end('failed')
        stale = stale + 1 if attempt.record['result'] == 'stale' else 0
        if stale >= STALE:
            return end('stale')
