"""The confirmed forget's effects (API-025; SPEC-035, SPEC-029, SPEC-012, SPEC-007; TASK-098).

`forget_command` calls `apply` under the project's layer lease that read the
preview, which every writer of the curated layer, the line history and the raw
logs' rewrites hold too, so nothing else changes them meanwhile; hooks only
append to the raw logs. The forget never takes or waits for the curation lease.
It works in this order, and reads each effect back before the next one:

1. One generation in the curation record's fence (TBL-009) for each item, pin
   record, state line and conflict candidate that it changes, published
   durably, so that a curation or consolidation built before it applies
   nothing (SPEC-012). The forget reads only the primary curation record and
   never restores it from its backup.
2. A tombstone (TBL-016) for each forgotten item, with the place of each of its
   quotes and none of their words. From then on every reader leaves the item
   out, hides the state lines that cite it or an entry that it quotes, and shows
   its quoted ranges as forgotten (TASK-083), also when the forget stops.
3. Each item's file with its backup and temporary copies; its search index
   rows, deleted under SQLite's secure delete with the write-ahead log
   checkpointed and truncated, or the index's files when the index cannot be
   opened or a reader keeps the log, so that the next curation builds it again;
   its pin record; the open conflict candidates that name it, settled; and the
   item list, written again, without the copies of it that stopped writes
   left, which can hold the item's title.
4. Each state line that cites a forgotten item, an entry that one quotes or an
   ID that an earlier tombstone names, whether the view showed it or hid it,
   with one privacy marker in its place among the removed lines (TBL-013),
   which no undo crosses. The line history archives nothing of them. The
   state's backup and temporary copies that stopped writes left go too, also
   when no current line cites one of those IDs, because they can still hold
   such a line.
5. The quoted ranges that the preview listed for this device's raw logs, filled
   with U+FFFD (`raw_fill`), and no backup or temporary copy of those logs
   left. A log whose file is missing is restored from its backup first, as the
   next append would restore it, and is then filled.
6. The line history (TBL-119): each record that cites an ID that a tombstone
   names goes, and every other record's reason is cleared, in the primary and
   in its backup; the temporary copies that a stopped rewrite left go. When the
   primary is missing or cannot be read, the forget still scrubs its backup and
   removes the temporary copies, which only a maintenance repair may restore
   from, and then raises `HistoryUnverified`, so that it reports no success.

A failure stops the forget where it is and reports no success; the tombstones
keep every reader from showing what it had still to remove.
"""
import os
import re
import sqlite3
import time
from pathlib import Path

from . import base, clock, conflict_plan, conflict_types, fence_plan, files, history_recovery, index_io
from . import item_io, item_types, raw_fill, raw_rewrite, revision_io, state_types

HISTORY = 'state-history.jsonl'
# The temporary copies of the line history and of its backup that a stopped rewrite leaves.
COPIES = re.compile(re.escape(HISTORY) + r'(?:\.bak)?\.[a-z0-9_]{8}\.tmp\Z')
TOMBSTONE_FIELDS = 'item project at device quotes'.split()
PLACE_FIELDS = 'device entry log start end'.split()
INDEX_FILES = ('index.db-wal', 'index.db-shm', 'index.db-journal', 'index.db')
# How long a reader of the search index may hold its write-ahead log before the index goes.
CHECKPOINT_SECONDS = 1.0


class Unverified(RuntimeError):
    """An effect did not read back as written."""


class HistoryUnverified(RuntimeError):
    """The line history's primary is missing or cannot be read, or a copy of it has an unknown name."""


def tombstone(value, project, at, device):
    """TBL-016 bytes for a forgotten item: where each of its quotes is, never its words."""
    data = item_types._bytes(item_types._ordered(
        {'item': value['id'], 'project': project, 'at': at, 'device': device,
         'quotes': [item_types._ordered(quote, PLACE_FIELDS) for quote in value['quotes']]}, TOMBSTONE_FIELDS))
    history_recovery._tombstone(data, value['id'], base.project_folder_name(project))
    return data


def _verify(condition):
    if not condition:
        raise Unverified()


def _tombstones(memory, root, items, project, at, deadline, check):
    folder = root / 'layer/tombstones'
    for value in items:
        path, data = folder / (value['id'] + '.json'), tombstone(value, project, at, memory.device)
        files.replace_bytes(path, data, check=check, path_check=memory.fence.check)
        _verify(files._retry(lambda: memory.fence.read(path, deadline), deadline) == data)
        check()


def _gone(memory, path, deadline, check):
    """Whether no file of the path's family is left: the path, its backup and its temporary copies."""
    check()
    names, _ = history_recovery._names(memory, path.parent, deadline, check)
    return not any(name == path.name or name.startswith(path.name + '.') for name in names)


def _items(memory, root, selected, deadline, check):
    for item in selected:
        path = root / 'layer/items' / (item + '.json')
        files.delete_file(path, lambda: files._access(check, memory.fence.check, path))
        _verify(_gone(memory, path, deadline, check))


def _index(memory, root, selected, deadline, check):
    """Delete the items' search index rows for good, or the index's files; how, or None without an index."""
    check()
    try:
        connection = index_io.open_index(memory, root)
    except sqlite3.Error:
        connection = False
    if connection is None:
        return None
    if connection:
        try:
            emptied = index_io.delete(connection, selected, forget=True)
            limit = min(deadline, clock.now() + CHECKPOINT_SECONDS)
            while not emptied and clock.now() < limit:
                time.sleep(0.02)
                check()
                emptied = connection.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0] == 0
            if emptied:
                marks = ','.join('?' * len(selected))
                left = connection.execute('SELECT count(*) FROM index_items WHERE item IN (%s)' % marks,
                                          list(selected)).fetchone()[0]
                _verify(left == 0)
                return 'rows'
        except sqlite3.Error:
            pass
        finally:
            connection.close()
    # The index cannot be cleaned where it is: its files go, the log first, and the next curation builds it again.
    for name in INDEX_FILES:
        path = root / name
        index_io._regular(memory, path)
        files._unlink(path, lambda path=path: files._access(check, memory.fence.check, path))
    _verify(all(memory.fence.check(root / name) is None for name in INDEX_FILES))
    return 'files'


def _leftovers(memory, folder, name, deadline, check):
    """Remove a record's backup and the temporary copies that stopped writes left, then check that none stays.

    The caller holds the layer lease, which every writer of the record holds,
    and has read the record itself, so each such copy is what a stopped write
    left, and it can hold text that the forget removes.
    """
    pattern = re.compile(re.escape(name) + r'(?:\.bak|(?:\.bak)?\.[a-z0-9_]{8}\.tmp)\Z')
    names, _ = history_recovery._names(memory, folder, deadline, check)
    for found in names:
        if pattern.fullmatch(found):
            path = folder / found
            files._unlink(path, lambda path=path: files._access(check, memory.fence.check, path))
    names, _ = history_recovery._names(memory, folder, deadline, check)
    _verify(not any(pattern.fullmatch(found) for found in names))


def _layer_records(memory, root, selected, at, proof, deadline, check):
    """Remove the items' pin records, settle the open candidates that name them and write the item list again.

    `proof` is the fence that the forget's reservation published.
    """
    path = root / 'layer/pins.json'
    pins = item_io._record(memory, path, item_types.parse_pins, deadline, check)
    kept = [pin for pin in pins['pins'] if pin['item'] not in selected]
    if len(kept) != len(pins['pins']):
        data = item_types.pins_bytes({'pins': kept})
        files.replace_bytes(path, data, check=check, path_check=memory.fence.check)
        _verify(item_io._record(memory, path, item_types.parse_pins, deadline, check)['pins'] == kept)
    path = root / 'layer/conflicts.json'
    conflicts = item_io._record(memory, path, conflict_types.parse_conflicts, deadline, check)
    named = {item for candidate in conflicts['candidates'] for item in candidate['items']}
    value, settled = conflict_plan.settle(conflicts, named - set(selected), at)
    if settled:
        data = conflict_plan.conflicts_bytes(value)
        files.replace_bytes(path, data, check=check, path_check=memory.fence.check)
        after = item_io._record(memory, path, conflict_types.parse_conflicts, deadline, check)
        _verify(not any(candidate['status'] == 'open' and set(selected).intersection(candidate['items'])
                        for candidate in after['candidates']))
    item_io.rebuild_list(memory, root, proof, deadline)
    listed = files._retry(lambda: memory.fence.read(root / 'layer/item-list.txt', deadline), deadline)
    _verify(not any(row.split(b'\t', 1)[0].decode('ascii', 'replace') in selected for row in listed.splitlines()))
    _leftovers(memory, root / 'layer', 'item-list.txt', deadline, check)


def _state(memory, root, lines, at, deadline, check):
    """Remove the lines with one privacy marker each, the markers first."""
    if not lines:
        return
    gone = {line['id'] for line in lines}
    folder = root / 'layer'
    removed = item_io._record(memory, folder / 'state-removed.json', state_types.parse_removed, deadline, check)
    state = item_io._record(memory, folder / 'state.json', state_types.parse_state, deadline, check)
    markers, placed = [], set()
    for marker in removed['removed']:
        if marker['id'] not in gone:
            markers.append(marker)
        elif marker['id'] not in placed:
            # A marker that the line had, restored or not, makes way for the privacy marker.
            markers.append(state_types.removal_marker(marker['id'], at, memory.device, 'privacy'))
            placed.add(marker['id'])
    markers.extend(state_types.removal_marker(line, at, memory.device, 'privacy')
                   for line in sorted(gone - placed))
    kept = [line for line in state['lines'] if line['id'] not in gone]
    for name, data in (('state-removed.json', state_types.removed_bytes({'removed': markers})),
                       ('state.json', state_types.state_bytes({'lines': kept}))):
        files.replace_bytes(folder / name, data, check=check, path_check=memory.fence.check)
        _verify(files._retry(lambda: memory.fence.read(folder / name, deadline), deadline) == data)
    check()


def _raw(memory, root, raw, deadline, wait, check):
    """Fill each log's listed ranges, then read the log back and check that no copy of it is left."""
    logs = {}
    for entry in raw:
        if entry['forgotten']:
            logs.setdefault(entry['log'], {})[entry['entry']] = entry['forgotten']
    for log in sorted(logs):
        check()
        raw_fill.fill(memory, root, log, logs[log], deadline, wait)
        path = root / 'raw' / (log + '.jsonl')
        _verify(not raw_fill._leftovers(path))
        data = files._retry(lambda: memory.fence.read(path, deadline), deadline)
        found = {}
        for line in data.split(b'\n')[:-1]:
            try:
                entry = raw_rewrite._entry(line, log)
            except (ValueError, UnicodeError):
                continue
            found.setdefault(entry['id'], []).append(entry)
        for entry, ranges in logs[log].items():
            _verify(entry in found)
            for value in found[entry]:
                listed = {(int(start), int(end)) for start, end in value.get('forgotten', ())}
                _verify(all((start, end) in listed and value['text'][start:end] == raw_fill.FILL * (end - start)
                            for start, end in ranges))
    check()


def _scrubbed(records, banned):
    """The records that stay, each reason cleared, and the (epoch, generation, line) of each removed or cleared."""
    kept, counted = [], set()
    for record in records:
        value = record.value
        if banned.intersection(value['cites']) or value['why']:
            counted.add((value['epoch'], value['generation'], value['line']))
        if banned.intersection(value['cites']):
            continue
        if value['why']:
            value['why'] = ''
            kept.append(state_types.history_record_bytes(value))
        else:
            kept.append(record.raw)
    return b''.join(kept), counted


def _parsed(memory, path, deadline):
    """The copy's records and bytes, or None when it is missing or cannot be read."""
    try:
        data = files._retry(lambda: memory.fence.read(path, deadline), deadline)
        return state_types.parse_history(data), data
    except files._RESTORABLE:
        return None


def _clean(records, banned):
    return all(not banned.intersection(record.value['cites']) and not record.value['why'] for record in records)


def _history(memory, root, banned, deadline, check):
    """Scrub every copy of the line history; how many records went or lost their reason, each once."""
    path, backup = root / HISTORY, root / (HISTORY + '.bak')
    names, _ = history_recovery._names(memory, root, deadline, check)
    family = [name for name in names if name == HISTORY or name.startswith(HISTORY + '.')]
    unknown = [name for name in family if name not in (path.name, backup.name) and not COPIES.fullmatch(name)]
    for name in family:
        if COPIES.fullmatch(name):
            files._unlink(root / name, lambda name=name: files._access(check, memory.fence.check, root / name))
    primary, copy = _parsed(memory, path, deadline), _parsed(memory, backup, deadline)
    counted = set()
    if copy is not None:
        data, found = _scrubbed(copy[0], banned)
        counted |= found
        if primary is None and data != copy[1]:
            # The backup is what a maintenance repair restores from, so it stays, scrubbed in place.
            ready = []
            temporary = files._temporary(backup, data, True, check=check, path_check=memory.fence.check,
                                         ready=ready.append)
            try:
                files._retry(lambda: files._checked(ready[0], lambda: os.replace(str(temporary), str(backup))),
                             deadline)
            finally:
                files._unlink(temporary, ready[0])
            scrubbed = _parsed(memory, backup, deadline)
            _verify(scrubbed is not None and _clean(scrubbed[0], banned))
    if primary is not None:
        data, found = _scrubbed(primary[0], banned)
        counted |= found
        if data != primary[1]:
            files.replace_bytes(path, data, check=check, path_check=memory.fence.check)
        # With a primary that reads, a backup is what a stopped rewrite left, and it goes.
        files._unlink(backup, lambda: files._access(check, memory.fence.check, backup))
        scrubbed = _parsed(memory, path, deadline)
        _verify(scrubbed is not None and scrubbed[1] == data and _clean(scrubbed[0], banned))
        _verify(memory.fence.check(backup) is None)
    names, _ = history_recovery._names(memory, root, deadline, check)
    _verify(not any(COPIES.fullmatch(name) for name in names))
    if primary is None or unknown:
        raise HistoryUnverified()
    return len(counted)


def apply(memory, root, plan, items, earlier, deadline, wait, at=None):
    """Forget the plan's items, whose records `items` holds, and return how many history records went or were cleared.

    `earlier` holds the IDs that the tombstones already present name. The caller
    holds the project's layer lease, under which it read the plan.
    """
    root = Path(root)
    at = base.utc_time() if at is None else at
    project = plan.data['project']
    ownership = revision_io.guard(memory, root, deadline)
    selected, banned = list(plan.selected), frozenset(plan.targets) | frozenset(earlier)
    if [value['id'] for value in items] != selected:
        raise ValueError('the records do not match the plan')
    state = item_io._record(memory, root / 'layer/state.json', state_types.parse_state, deadline, ownership)
    lines = [line for line in state['lines'] if banned.intersection(line['cites'])]
    pins = item_io._record(memory, root / 'layer/pins.json', item_types.parse_pins, deadline, ownership)
    conflicts = item_io._record(memory, root / 'layer/conflicts.json', conflict_types.parse_conflicts, deadline,
                                ownership)
    candidates = [candidate['id'] for candidate in conflicts['candidates']
                  if candidate['status'] == 'open' and set(selected).intersection(candidate['items'])]
    # The lease kept what the preview showed; a difference means that something wrote without it.
    if (set(candidates) != set(plan.data['settled_conflicts']) or
            not {line['line'] for line in plan.data['state_lines']} <= {line['id'] for line in lines}):
        raise fence_plan.Stale()
    targets = (['item:' + item for item in selected] +
               ['pin:' + pin['item'] for pin in pins['pins'] if pin['item'] in selected] +
               ['line:' + line['id'] for line in lines] + ['candidate:' + candidate for candidate in candidates])
    expected = fence_plan.snapshot(revision_io.read_primary(memory, root, deadline))
    reservation = revision_io.reserve(memory, root, expected, targets, deadline, primary_only=True)

    def check():
        ownership()
        reservation.check()
    _tombstones(memory, root, items, project, at, deadline, check)
    _items(memory, root, selected, deadline, check)
    _index(memory, root, selected, deadline, check)
    _layer_records(memory, root, selected, at, fence_plan.snapshot(reservation.progress), deadline, check)
    _state(memory, root, lines, at, deadline, check)
    # The state's primary was read above, so its backup is what a stopped write left; it and the temporary copies
    # can still hold a line that cited a forgotten ID, also when no current line does.
    _leftovers(memory, root / 'layer', 'state.json', deadline, check)
    _raw(memory, root, plan.data['raw'], deadline, wait, check)
    return _history(memory, root, banned, deadline, check)
