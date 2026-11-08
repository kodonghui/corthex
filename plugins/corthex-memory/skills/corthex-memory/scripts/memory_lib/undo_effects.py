"""The confirmed undo's inverse (API-153; SPEC-145, SPEC-012, SPEC-017, SPEC-034; TASK-107, TASK-108).

`undo_command` calls `apply` with the plan that it has just checked against the
user's code, under the project's curation lease and then its layer lease. Every
writer of the curated layer, the line history and the curation record's fence
holds the layer lease too, and every curation and consolidation holds the
curation lease, so the snapshot that the plan was read from is still what the
store holds; hooks only append to the raw logs. The inverse is a new run of
kind `undo` that names the run it reverses, and it works in this order:

1. One generation in the curation record's fence (TBL-009) for each object that
   the plan reverses, each open candidate that it settles and the new run,
   published durably before anything else changes, so that a curation or
   consolidation request built before the undo applies nothing and is built
   again (SPEC-012), and so that every earlier confirmation is stale.
2. Each state line that the undo changes or removes, as it is now, appended to
   the line history (TBL-119) as `undone`, durably, so that an undo of this
   undo can put it back without the older run's log.
3. What the undo hides: a removal marker for each line that it removes; then
   the search index rows and the item list without the items that stop being
   current, and only then those items (a saved item undone by the new run, any
   other with the status that it had before the run).
4. What the undo shows: the items that become current again; the pins at their
   places before the run; the candidates (after the items that they name, as
   SPEC-016 orders them): those that the run recorded closed as settled, those
   that it closed open again, and the open candidates that name an item that
   stops being current settled; the state with each line removed, put back or
   restored with its ID; and last the restored lines' markers marked restored.
5. The item list as it ends, one notice for each pin that the undo moves
   (SPEC-034) and the search index rows of the items that became current. The
   index's files go when its rows cannot be written, so that the next curation
   builds it again.
6. The new run's log (TBL-121), with each change's before and after, the
   history records that it appended and what it kept and why, and its attempt
   in the curation record. A log that cannot be written leaves the inverse in
   place and the undo unlisted, as for any run (SPEC-144).

Each file is read back after it is written. A failure stops the inverse where it
is and reports no success, and the inverse is not resumed (TASK-108). Each file
is whole, and the order keeps every reader on the safe side: the start summary
and the requests never show a line that the undo removes, nor a line that it
puts back before its marker says so, nor an item that it makes current beside
one that it makes not current; the item list and the search index never offer
an item whose own file is not current. The moved fence keeps every earlier
request and confirmation from applying, and the reserved objects have revisions
that no log names, so a later undo keeps them and never applies the inverse
twice. A stopped undo has no log, so no undo can use the records that it
appended to the line history, and a forget removes them as it removes any.
"""
import contextlib
import copy
import sqlite3
from pathlib import Path

from . import conflict_plan, curation_worker, fence_plan, files, format2, history_io, index_io, item_io
from . import item_types, revision_io, run_log, state_plan, state_types, undo_plan

SAY = 'The run was undone as a new run.'
# The index's files, its log first, as the forget removes them.
INDEX_FILES = ('index.db-wal', 'index.db-shm', 'index.db-journal', 'index.db')


class Unverified(RuntimeError):
    """A file did not read back as written."""


def _status(value):
    return item_types._ordered(value, undo_plan.STATUS)


def _pin(value):
    return None if value is None else item_types._ordered(value, undo_plan.PIN)


def _items(snapshot, plan, run, at):
    """The changed item records: a saved item undone by this run, any other with its status before the run."""
    saved, changed = set(snapshot.log['saved']), {}
    for name, target in sorted(plan.items.items()):
        value = copy.deepcopy(snapshot.items[name])
        for key in undo_plan.STATUS:
            value.pop(key, None)
        value.update({'status': 'undone', 'undone_by': run} if name in saved else copy.deepcopy(target))
        value['changed'] = at
        changed[name] = item_types.parse_item(item_types.item_bytes(value))
    return changed


def _pins(snapshot, plan):
    """The new pin list and the run log's pin entries: each pin at its place before the run, or gone."""
    pins = []
    for pin in snapshot.pins:
        name = pin['item']
        if name not in plan.pins:
            pins.append(dict(pin))
        elif plan.pins[name][0] is not None:
            pins.append(dict(plan.pins[name][0], item=name))
    present = {pin['item'] for pin in pins}
    for name, (record, place) in sorted(plan.pins.items(), key=lambda pair: (pair[1][1] or 0, pair[0])):
        if record is not None and name not in present:
            pins.insert(min(place or 0, len(pins)), dict(record, item=name))
    before = {pin['item']: (index, pin) for index, pin in enumerate(snapshot.pins)}
    after = {pin['item']: (index, pin) for index, pin in enumerate(pins)}
    entries = []
    for name in sorted(plan.pins):
        old, new = before.get(name, (None, None)), after.get(name, (None, None))
        entries.append({'item': name, 'from': _pin(old[1]), 'to': _pin(new[1]), 'place': [old[0], new[0]]})
    return [item_types._ordered(pin, item_types.PIN_FIELDS) for pin in pins], entries


def _notices(snapshot, plan, items, run, at):
    """One notice for each pin that the undo moves (SPEC-034), named as the pin notices are: pin-<item>.

    A pin that the undo turns on returned to its item. A pin that it turns off
    or removes says so only when no pin that it turns on came from that item,
    as when the undo moves a pin back from the item that replaced its own, or
    went to it, as when it replaces an item again.
    """
    was = {pin['item']: pin['on'] for pin in snapshot.pins}
    on = sorted(name for name, (record, _) in plan.pins.items() if record is not None and record['on'])
    off = sorted(name for name, (record, _) in plan.pins.items()
                 if was.get(name) and (record is None or not record['on']))

    def status(name, after):
        value = items.get(name) if after else None
        return _status(value if value is not None else snapshot.items[name])
    notices = [(name, {'at': at, 'kind': 'pin-restored', 'item': name, 'run': run}) for name in on]
    for name in off:
        if not any(status(other, False).get('superseded_by') == name or
                   status(name, True).get('superseded_by') == other for other in on):
            notices.append((name, {'at': at, 'kind': 'pin-removed', 'item': name, 'run': run}))
    return [(name, item_types.notice_bytes(value)) for name, value in sorted(notices)]


def _candidates(snapshot, plan, at):
    """The new TBL-120 value and the run log's candidate entries."""
    value, entries = {'candidates': copy.deepcopy(list(snapshot.candidates))}, []
    for candidate in value['candidates']:
        target = plan.candidates.get(candidate['id'])
        if target is None and candidate['id'] in plan.settles:
            target = 'settled'
        if target is None or target == candidate['status']:
            continue
        entries.append({'candidate': candidate['id'], 'from': candidate['status'], 'to': target})
        candidate['status'] = target
        if target == 'open':
            candidate.pop('closed', None)
        else:
            candidate['closed'] = at
    return value, entries


def _state(snapshot, plan, run, at, device):
    """The lines and markers after the inverse: (lines, markers first, markers last, archived, ops).

    `archived` holds the lines as they are now that the undo changes or
    removes, whose versions go to the line history; `ops` maps each changed line
    to its run log operation. The first markers add one for each removed line,
    the last also mark each line that comes back with its ID restored.
    """
    lines = [dict(line) for line in snapshot.lines]
    places = {line['id']: index for index, line in enumerate(lines)}
    markers = [dict(marker) for marker in snapshot.removed]
    archived, ops, gone, back = [], {}, set(), set()
    for name, record in sorted(plan.lines.items()):
        index = places.get(name)
        if record is None:
            archived.append(lines[index])
            gone.add(name)
            ops[name] = 'undone'
            continue
        value = record.value
        fields = {key: value[key] for key in ('part', 'pos', 'text', 'cites')}
        if index is None:
            lines.append(dict(fields, id=name, at=at, device=device))
            back.add(name)
            ops[name] = 'added'
            continue
        archived.append(lines[index])
        line = dict(lines[index], **fields)
        if (line['text'], line['cites']) != (lines[index]['text'], lines[index]['cites']):
            line.update(at=at, device=device)
        lines[index] = line
        ops[name] = 'undone'
    lines = [item_types._ordered(line, state_types.LINE_FIELDS) for line in lines if line['id'] not in gone]
    # A removed line's marker takes the place of the restored marker that it may have had.
    first = [state_types.removal_marker(marker['id'], at, device, 'edit') if marker['id'] in gone else marker
             for marker in markers]
    first.extend(state_types.removal_marker(name, at, device, 'edit')
                 for name in sorted(gone - {marker['id'] for marker in markers}))
    last = [dict(marker, restored_by=run, restored_at=at) if marker['id'] in back else marker for marker in first]
    return lines, first, last, archived, ops


def _history(archived, progress, run, at, device):
    """The TBL-119 records of the lines as they are now, appended as `undone` at the reservation's generation."""
    fence = progress['fence']
    return [{'at': at, 'run': run, 'epoch': fence['epoch'], 'generation': fence['generation'], 'line': line['id'],
             'part': line['part'], 'pos': line['pos'], 'op': 'undone', 'text': line['text'], 'cites': line['cites'],
             'why': '', 'device': device} for line in archived]


def _place(placements, name):
    return list(placements[name]) if name in placements else []


def _publish(memory, path, data, durable, deadline, guard):
    item_io._publish(path, data, durable, guard, memory.fence.check, lambda: None)
    if files._retry(lambda: memory.fence.read(path, deadline), deadline) != data:
        raise Unverified()
    guard()


def _index(memory, root, values, guard):
    """Write the changed items' rows of the search index, which is derived data.

    When the rows cannot be written its files go, and the index is built again
    from the items when it is next needed (TASK-082); when even removing them
    fails the failure is noted, since the inverse itself is done.
    """
    guard()
    try:
        try:
            connection = index_io.open_index(memory, root)
        except sqlite3.Error:
            connection = False
        if connection is None:
            return
        if connection:
            try:
                index_io.put(connection, values)
                return
            except sqlite3.Error:
                pass
            finally:
                connection.close()
        for name in INDEX_FILES:
            index_io._regular(memory, root / name)
            files._unlink(root / name, lambda name=name: files._access(guard, memory.fence.check, root / name))
    except (OSError, index_io.IndexUnavailable) as error:
        memory.note(error, step='skill')


def apply(memory, root, plan, snapshot, deadline, *, at, run=None):
    """Apply the plan's inverse as a new undo run; the new run's ID.

    `snapshot` is what the plan was read from, under the leases that the caller
    still holds; `at` is the run's time.
    """
    root = Path(root)
    format2._time(at)
    run = curation_worker._run_id() if run is None else run
    format2._id(run, format2._RUN)
    ownership = history_io._project_check(memory, root, revision_io.guard(memory, root, deadline, curator=True))
    progress = revision_io.read_primary(memory, root, deadline)
    if progress['fence'] != snapshot.fence:
        raise fence_plan.Stale()
    expected = fence_plan.snapshot(progress)
    items = _items(snapshot, plan, run, at)
    pins, pin_entries = _pins(snapshot, plan)
    notices = _notices(snapshot, plan, items, run, at)
    candidates, candidate_entries = _candidates(snapshot, plan, at)
    lines, first, last, archived, ops = _state(snapshot, plan, run, at, memory.device)
    targets = sorted(set(plan.reversed) | {'candidate:' + name for name in plan.settles})
    changed = ({'item:' + name for name in items} | {'pin:' + entry['item'] for entry in pin_entries} |
               {'candidate:' + entry['candidate'] for entry in candidate_entries} | {'line:' + name for name in ops})
    if changed != set(targets):
        raise ValueError('the inverse does not change exactly what the plan reverses')
    named = set(items) | set(plan.pins)

    def guard():
        ownership()
        if any(item_io._private(memory, root, name) for name in named):
            raise fence_plan.Stale()
        ownership()
    guard()
    reservation = revision_io.reserve(memory, root, expected, targets, deadline, run, primary_only=True)

    def check():
        guard()
        reservation.check()
        guard()

    def precondition(bound_memory, bound_root, bound_reservation, required):
        if bound_memory is not memory or bound_root != root or bound_reservation is not reservation:
            raise ValueError('history binding mismatch')
        check()

    values = _history(archived, reservation.progress, run, at, memory.device)
    hashes = {value['line']: state_types.HistoryRecord(state_types.history_record_bytes(value)).sha256
              for value in values}
    history = (history_io.append(memory, root, reservation, values, deadline, archive_precondition=precondition)
               if values else contextlib.nullcontext(None))
    layer = root / 'layer'
    hidden = {name: value for name, value in items.items() if value['status'] != 'current'}
    shown = {name: value for name, value in items.items() if value['status'] == 'current'}
    with history as receipt:
        if receipt is not None:
            receipt.check()
        check()
        # What the undo hides comes first; the derived views leave an item out before its own file does.
        if ops and first != list(snapshot.removed):
            _publish(memory, layer / 'state-removed.json', state_types.removed_bytes({'removed': first}), True,
                     deadline, check)
        if hidden:
            _index(memory, root, [hidden[name] for name in sorted(hidden)], check)
            _publish(memory, layer / 'item-list.txt',
                     item_types.item_list_bytes(list(dict(snapshot.items, **hidden).values())), False, deadline, check)
        for name in sorted(hidden) + sorted(shown):
            _publish(memory, layer / 'items' / (name + '.json'), item_types.item_bytes(items[name]), True, deadline,
                     check)
        if pin_entries:
            _publish(memory, layer / 'pins.json', item_types.pins_bytes({'pins': pins}), True, deadline, check)
        if candidate_entries:
            _publish(memory, layer / 'conflicts.json', conflict_plan.conflicts_bytes(candidates), True, deadline,
                     check)
        if ops:
            if receipt is not None:
                receipt.check()
            _publish(memory, layer / 'state.json', state_types.state_bytes({'lines': lines}), True, deadline, check)
            if last != first:
                _publish(memory, layer / 'state-removed.json', state_types.removed_bytes({'removed': last}), True,
                         deadline, check)
    final = dict(snapshot.items, **items)
    _publish(memory, layer / 'item-list.txt', item_types.item_list_bytes(list(final.values())), False, deadline,
             check)
    for name, data in notices:
        _publish(memory, root / 'notices' / ('pin-' + name + '.json'), data, False, deadline, check)
    if shown:
        _index(memory, root, [shown[name] for name in sorted(shown)], check)
    generation = reservation.progress['fence']['generation']
    before, after = state_plan._placements(list(snapshot.lines)), state_plan._placements(lines)
    epoch = reservation.progress['fence']['epoch']
    effects = {
        'statuses': [{'item': name, 'before': _status(snapshot.items[name]), 'after': _status(value)}
                     for name, value in sorted(items.items())],
        'lines': [{'line': name, 'op': ops[name], 'generation': generation,
                   'history': [epoch, generation, name, hashes[name]] if name in hashes else None,
                   'before': _place(before, name), 'after': _place(after, name)} for name in sorted(ops)],
        'pins': pin_entries, 'conflicts': candidate_entries,
        'kept': [{'id': value['target'], 'by': value['by'], 'why': value['why']} for value in plan.data['kept']],
        'revisions': [{'id': key, 'before': expected['fence']['revisions'].get(key), 'after': generation}
                      for key in targets]}
    try:
        log = run_log.add(run_log.start(run, 'undo', at, memory.device, undoes=snapshot.log['id']),
                          reservation.progress, at, effects)
    except (ValueError, TypeError, LookupError) as error:
        memory.note(error, step='skill')
    else:
        run_log.write(memory, root, log, check)
    fresh = revision_io.read(memory, root, deadline)
    attempt = {'at': at, 'kind': 'undo', 'result': 'ok', 'run': run}
    revision_io.update_progress(memory, root, fence_plan.snapshot(reservation.progress),
                                {'recent': curation_worker._recent(fresh, attempt)}, deadline)
    return run
