"""The undo preview (API-153; SPEC-145; TASK-105, TASK-106): what undoing a run reverses and what it keeps.

Pure functions over one snapshot that `undo_command` reads under the
project's layer lease: the run's complete eligible log and its file's hash, the
curation record's fence, the items, tombstones, physical state lines with their
removal markers, pins, conflict candidates, the primary line history and the
project's other run logs, which name the run of a later change. A plan grants
no authority: the inverse (TASK-107) reads everything again under the curation
and layer leases and applies only a plan whose binding is the one confirmed.

An object that the run changed is reversed only while its code-owned revision
is the one that the run last gave it, its record is what the run left, it holds
nothing that a forget made private and, for a state line that existed before
the run, the exact line-history record of its version before the run's first
change is available, or for a line that the run added, the line history can be
read, since removing it appends its text there first; otherwise it is kept,
with the later run when one is known and one of TBL-121's reasons. Inverses that depend on one another are reversed
or kept together: an item and the items that it replaced, merged or was
replaced by, an item and the pins that moved with it, and state lines whose
places in the run anchor one another. A group is kept too when reversing it
would leave a kept or later object invalid: a pin on, a visible line citing or
an item replaced by an item that would stop being current, the last unless
that item's replacements would end at a current item, as a merge of an item
that had replaced another leaves them; a line placed next to a line that a
later change placed; a restored decision without a current decision; or a
reopened candidate without two current items.
"""
import hashlib
import json
from dataclasses import dataclass, field

from . import start_memory, state_plan

STATUS = ('status', 'superseded_by', 'undone_by')
PIN = ('on', 'at', 'device')
# A candidate that the run recorded closes as settled (TBL-120).
CLOSED = 'settled'
SAY = {
    'nothing': 'Every change of this run is kept, so there is nothing safe to undo; data.kept says why.',
    'still': 'Nothing that this run left needs undoing: each object it changed already is as it was before.',
}


@dataclass(frozen=True)
class Snapshot:
    log: dict              # the run's complete eligible log (TBL-121)
    log_sha256: str        # SHA-256 of its file's bytes
    fence: dict            # the curation record's fence (TBL-009)
    items: dict            # every item by ID that no tombstone names
    forgotten: frozenset   # the items that tombstones name
    private: frozenset     # the item and entry IDs that tombstones make private
    lines: tuple           # the physical state lines (TBL-013), hidden ones too
    removed: tuple         # the removal markers
    pins: tuple            # the pin records, in order
    candidates: tuple      # every conflict candidate (TBL-120)
    history: object        # the primary line history's records (TBL-119), or None when it cannot be read
    logs: tuple = ()       # the project's other readable run logs


@dataclass(frozen=True)
class Plan:
    data: dict                                     # the preview that the confirmation binds
    reversed: frozenset                            # the namespaced objects whose inverse changes something
    items: dict = field(repr=False)                # item -> its status afterwards; a saved item's is undone
    pins: dict = field(repr=False)                 # item -> (pin record or None, list index)
    lines: dict = field(repr=False)                # line -> None to remove it, or the history record to restore
    candidates: dict = field(repr=False)           # candidate -> its status afterwards
    settles: tuple = ()                            # open candidates that settle because an item stops being current


def _record(value, fields):
    return {key: value[key] for key in fields if key in value}


def _grouped(entries, key):
    found = {}
    for entry in entries:
        found.setdefault(entry[key], []).append(entry)
    return found


def _chained(entries, before, after):
    """Whether each entry of one object starts where the one before it ended."""
    return all(entries[index][before] == entries[index - 1][after] for index in range(1, len(entries)))


def _placed(before, after):
    """Whether a line's change, or its inverse, adds, removes or moves it."""
    return (before == []) != (after == []) or bool(before) and list(before[:2]) != list(after[:2])


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


class _Groups:
    """The run's objects joined into groups whose inverses depend on one another."""

    def __init__(self, keys):
        self.parent = {key: key for key in keys}

    def find(self, key):
        while self.parent[key] != key:
            self.parent[key] = self.parent[self.parent[key]]
            key = self.parent[key]
        return key

    def join(self, first, second):
        if first in self.parent and second in self.parent:
            one, other = self.find(first), self.find(second)
            if one != other:
                self.parent[max(one, other)] = min(one, other)

    def members(self, key):
        root = self.find(key)
        return [other for other in sorted(self.parent) if self.find(other) == root]


class _Planner:
    def __init__(self, snapshot):
        self.s = snapshot
        log = snapshot.log
        self.run, self.revisions = log['id'], snapshot.fence['revisions']
        self.epoch = snapshot.fence['epoch'].lower()
        self.last = {}
        for entry in log['revisions']:
            self.last[entry['id']] = max(entry['after'], self.last.get(entry['id'], entry['after']))
        self.first = log['applies'][0]['generation']
        self.saved = set(log['saved'])
        self.statuses = _grouped(log['statuses'], 'item')
        self.pin_entries = _grouped(log['pins'], 'item')
        self.candidate_entries = _grouped(log['conflicts'], 'candidate')
        self.line_entries = _grouped(sorted(log['lines'], key=lambda entry: entry['generation']), 'line')
        self.markers = _grouped(snapshot.removed, 'id')
        self.physical = {line['id']: line for line in snapshot.lines}
        self.pin_records = {pin['item']: (index, pin) for index, pin in enumerate(snapshot.pins)}
        self.candidate_records = {value['id']: value for value in snapshot.candidates}
        self.records = {}
        for record in snapshot.history or ():
            self.records.setdefault(record.sha256, []).append(record)
        self.logs = [value for value in snapshot.logs
                     if value['id'] != self.run and value['epoch'].lower() == self.epoch]
        self.kept, self.targets, self.still, self.needed = {}, {}, set(), []
        self.groups = _Groups(self.last)

    # Later changes

    def _log_of(self, key, revision):
        for value in self.logs:
            for apply in value['applies']:
                if apply['generation'] == revision and key in apply['changes']:
                    return value
        return None

    def _later(self, key, revision=None):
        """The run whose apply gave the object its revision, when that apply came after the run began, else ''."""
        revision = self.revisions.get(key) if revision is None else revision
        if type(revision) is not int or revision <= self.first:
            return ''
        found = self._log_of(key, revision)
        return '' if found is None else found['id']

    def _moved(self, key):
        """(why, by) when the object's revision is not the one that the run last gave it, else None."""
        current, last = self.revisions.get(key), self.last[key]
        if current == last:
            return None
        if type(current) is int and current > last:
            by = self._later(key, current)
            return ('later-run', by) if by else ('later-unlogged-change', '')
        return 'revision-unavailable', ''

    def _placed_later(self, key):
        """Whether a change since the run began placed this line, as far as the run logs show.

        A change that a readable log shows kept the line's part and position is
        not a placement; one that no log shows, as a forget's or one whose log
        was lost, counts as one.
        """
        line, revision = key[len('line:'):], self.revisions.get(key)
        own = {entry['after'] for entry in self.s.log['revisions'] if entry['id'] == key}
        while type(revision) is int and revision > self.first and revision not in own:
            value = self._log_of(key, revision)
            if value is None:
                return True
            changes = [entry for entry in value['lines'] if entry['line'] == line and entry['generation'] == revision]
            if not changes or any(_placed(entry['before'], entry['after']) or not entry['before'] for entry in changes):
                return True
            revision = next(entry['before'] for entry in value['revisions']
                            if entry['id'] == key and entry['after'] == revision)
        return False

    # What the run left, and the inverse of each object

    def _item(self, name, key):
        if name in self.s.forgotten:
            return 'forgotten', ''
        moved = self._moved(key)
        if moved:
            return moved
        entries, value = self.statuses.get(name, []), self.s.items.get(name)
        expected = entries[-1]['after'] if entries else {'status': 'current'}
        if (value is None or _record(value, STATUS) != expected or not _chained(entries, 'before', 'after') or
                name not in self.saved and not entries):
            return 'revision-unavailable', ''
        target = {'status': 'undone'} if name in self.saved else dict(entries[0]['before'])
        self.targets[key] = target
        if target == expected:
            self.still.add(key)
        return None

    def _pin(self, name, key):
        if name in self.s.forgotten:
            return 'forgotten', ''
        moved = self._moved(key)
        if moved:
            return moved
        entries, found = self.pin_entries[name], self.pin_records.get(name)
        current = None if found is None else _record(found[1], PIN)
        if current != entries[-1]['to'] or not _chained(entries, 'from', 'to'):
            return 'revision-unavailable', ''
        self.targets[key] = (entries[0]['from'], entries[0]['place'][0])
        if entries[0]['from'] == current:
            self.still.add(key)
        return None

    def _candidate(self, name, key):
        value = self.candidate_records.get(name)
        if value is not None and self.s.forgotten.intersection(value['items']):
            return 'forgotten', ''
        moved = self._moved(key)
        if moved:
            return moved
        entries = self.candidate_entries[name]
        status = 'absent' if value is None else value['status']
        if value is None or status != entries[-1]['to'] or not _chained(entries, 'from', 'to'):
            return 'revision-unavailable', ''
        target = CLOSED if entries[0]['from'] == 'absent' else entries[0]['from']
        self.targets[key] = target
        if target == status:
            self.still.add(key)
        return None

    def _history(self, name, entry):
        """The exact TBL-119 record of the line's version before the run's first change of it, or None."""
        reference = entry['history']
        if reference is None:
            self.needed.append(['', entry['generation'], name, '', False])
            return None
        epoch, generation, line, sha256 = reference
        found = None
        for record in self.records.get(sha256, ()):
            value = record.value
            if (value['epoch'].lower(), value['generation'], value['line'], value['run'], value['op'],
                    value['device'], [value['part'], value['pos']]) == (
                    epoch.lower(), generation, line, self.run, entry['op'], self.s.log['device'],
                    list(entry['before'][:2])):
                found = record
                break
        self.needed.append([epoch.lower(), generation, line, sha256, found is not None])
        return found

    def _line(self, name, key):
        entries, markers, line = self.line_entries[name], self.markers.get(name, []), self.physical.get(name)
        if (any(marker.get('kind') == 'privacy' for marker in markers) or
                line is not None and self.s.private.intersection(line['cites'])):
            return 'forgotten', ''
        moved = self._moved(key)
        if moved:
            return moved
        restored = [set(marker) >= {'restored_by', 'restored_at'} for marker in markers]
        edits = all(marker.get('kind') == 'edit' for marker in markers)
        last = entries[-1]['after']
        if last == []:
            fits = line is None and len(markers) == 1 and edits and not restored[0]
        else:
            fits = (line is not None and [line['part'], line['pos']] == list(last[:2]) and
                    (not markers or len(markers) == 1 and edits and restored[0]))
        chained = all((entries[index]['before'] == []) == (entries[index - 1]['after'] == []) and
                      list(entries[index]['before'][:2]) == list(entries[index - 1]['after'][:2])
                      for index in range(1, len(entries)))
        if not fits or not chained:
            return 'revision-unavailable', ''
        first = entries[0]
        if first['op'] == 'added':
            self.targets[key] = None
            if line is None:
                # The run removed it again, so it is already absent, as before the run.
                self.still.add(key)
            elif self.s.history is None:
                # Removing it appends its text to the line history first, as `undone`.
                return 'history-unavailable', ''
            return None
        record = self._history(name, first)
        if record is None:
            return 'history-unavailable', ''
        value = record.value
        if self.s.private.intersection(value['cites']):
            return 'forgotten', ''
        self.targets[key] = record
        if line is not None and all(line[field] == value[field] for field in ('part', 'pos', 'text', 'cites')):
            self.still.add(key)
        return None

    # Groups

    def _join(self):
        groups, log = self.groups, self.s.log
        for name, entries in self.statuses.items():
            for entry in entries:
                for side in ('before', 'after'):
                    other = entry[side].get('superseded_by')
                    if other:
                        groups.join('item:' + name, 'item:' + other)
                        groups.join('item:' + name, 'pin:' + other)
        for entry in log['merges']:
            for other in entry['merged']:
                groups.join('item:' + entry['item'], 'item:' + other)
        for name in self.pin_entries:
            groups.join('pin:' + name, 'item:' + name)
        placing = {name for name, entries in self.line_entries.items()
                   if any(_placed(entry['before'], entry['after']) for entry in entries)}
        for name in sorted(placing):
            for entry in self.line_entries[name]:
                if not _placed(entry['before'], entry['after']):
                    continue
                for place in (entry['before'], entry['after']):
                    for neighbour in place[2:]:
                        if neighbour in placing:
                            groups.join('line:' + name, 'line:' + neighbour)

    def _keep(self, key, by):
        for member in self.groups.members(key):
            self.kept.setdefault(member, ('later-dependent-change', by))

    # The world after the inverse

    def _reversed(self):
        return {key for key in self.last if key not in self.kept}

    def _status_after(self, name, reversed_):
        key = 'item:' + name
        if key in reversed_:
            return self.targets[key]
        value = self.s.items.get(name)
        return None if value is None else _record(value, STATUS)

    def _current(self, name, reversed_=frozenset()):
        status = self._status_after(name, reversed_)
        return status is not None and status['status'] == 'current'

    def _replacements(self, name, reversed_):
        """The items that replace the item after the inverse, each the one before's, up to one not superseded."""
        found, status = [], self._status_after(name, reversed_)
        while status is not None and status['status'] == 'superseded':
            name = status.get('superseded_by')
            if not name or name in found:
                break
            found.append(name)
            status = self._status_after(name, reversed_)
        return found

    def _replaced(self, name, reversed_):
        """Whether the item, after the inverse, is superseded and its replacements end at a current item."""
        found = self._replacements(name, reversed_)
        return bool(found) and self._current(found[-1], reversed_)

    def _layout(self, reversed_):
        """The physical lines after the inverse: ID -> (part, pos, cites)."""
        layout = {name: (line['part'], line['pos'], line['cites']) for name, line in self.physical.items()}
        for key in reversed_:
            if key.startswith('line:') and key not in self.still:
                name, record = key[len('line:'):], self.targets[key]
                layout.pop(name, None)
                if record is not None:
                    value = record.value
                    layout[name] = (value['part'], value['pos'], value['cites'])
        return layout

    def _visible(self, line):
        markers = self.markers.get(line['id'], [])
        return not (self.s.private.intersection(line['cites']) or markers and not (
            len(markers) == 1 and markers[0].get('kind') == 'edit' and
            set(markers[0]) >= {'restored_by', 'restored_at'}))

    def _violations(self, reversed_):
        """(group key, by) for each group whose inverse would leave a kept or later object invalid."""
        found = []
        items = {key[len('item:'):] for key in self.last if key.startswith('item:')}
        stopping = {name for name in items if self._current(name) and not self._current(name, reversed_)}
        # A pin that is on afterwards names a current item.
        for name in sorted(set(self.pin_records) | {key[len('pin:'):] for key in self.last if key.startswith('pin:')}):
            pin_key, item_key = 'pin:' + name, 'item:' + name
            if pin_key in reversed_:
                record = self.targets[pin_key][0]
            else:
                found_pin = self.pin_records.get(name)
                record = None if found_pin is None else found_pin[1]
            if record is None or not record['on'] or self._current(name, reversed_):
                continue
            if pin_key in reversed_ and pin_key not in self.still:
                found.append((pin_key, self.kept.get(item_key, ('', ''))[1]))
            elif name in stopping:
                found.append((item_key, self._later(pin_key)))
        # A visible line that stays cites no item that stops being current.
        for name, line in sorted(self.physical.items()):
            key = 'line:' + name
            if key in reversed_ and key not in self.still or not self._visible(line):
                continue
            for item in sorted(stopping.intersection(line['cites'])):
                found.append(('item:' + item, self._later(key)))
        # An item that stays is not replaced by an item that stops being current, unless that item is then
        # replaced in turn, through its replacements, by a current one: a merge of an item that had replaced
        # another leaves that chain, so undoing the undo of the merge leaves it again (SPEC-145).
        for name, value in sorted(self.s.items.items()):
            key = 'item:' + name
            if key in reversed_ and key not in self.still:
                continue
            after = value.get('superseded_by')
            if value['status'] == 'superseded' and after in stopping and not self._replaced(after, reversed_):
                found.append(('item:' + after, self._later(key)))
        # A line whose place the inverse changes is not next to a line that a later change placed.
        layout = self._layout(reversed_)
        before = state_plan._placements(list(self.s.lines))
        after = state_plan._placements([dict(id=name, part=part, pos=pos) for name, (part, pos, _) in layout.items()])
        for key in sorted(reversed_ - self.still):
            if not key.startswith('line:'):
                continue
            name = key[len('line:'):]
            now = list(before[name][:2]) if name in before else []
            later = list(after[name][:2]) if name in after else []
            if not _placed(now, later):
                continue
            root, empty = self.groups.find(key), ('', '', '', '')
            for neighbour in sorted(set(before.get(name, empty)[2:]) | set(after.get(name, empty)[2:])):
                other = 'line:' + neighbour
                if (not neighbour or other in self.groups.parent and self.groups.find(other) == root or
                        other in reversed_ and other not in self.still):
                    continue
                if self._placed_later(other):
                    found.append((key, self._later(other)))
                    break
        # A restored decision cites a decision that is current afterwards.
        for key in sorted(reversed_ - self.still):
            record = self.targets[key] if key.startswith('line:') else None
            if record is None or record.value['part'] != 'decisions':
                continue
            cites = record.value['cites']
            if not any(self._current(item, reversed_) and self.s.items[item]['kind'] == 'decision'
                       for item in cites if item in self.s.items):
                by = next((self.kept['item:' + item][1] for item in sorted(cites)
                           if 'item:' + item in self.kept and self.kept['item:' + item][1]), '')
                found.append((key, by))
        # A reopened candidate names two current items and no other open candidate names the pair.
        for key in sorted(reversed_ - self.still):
            if not key.startswith('candidate:') or self.targets[key] != 'open':
                continue
            name = key[len('candidate:'):]
            pair = self.candidate_records[name]['items']
            others = [value for value in self.s.candidates if value['id'] != name and
                      set(value['items']) == set(pair) and self._candidate_after(value, reversed_) == 'open']
            if others or not all(self._current(item, reversed_) for item in pair):
                found.append((key, ''))
        return found

    def _candidate_after(self, value, reversed_):
        key = 'candidate:' + value['id']
        return self.targets[key] if key in reversed_ else value['status']

    def _settles(self, reversed_):
        stopping = {name for name in self.s.items if self._current(name) and not self._current(name, reversed_)}
        return tuple(value['id'] for value in sorted(self.s.candidates, key=lambda value: value['id'])
                     if 'candidate:' + value['id'] not in reversed_ and value['status'] == 'open' and
                     stopping.intersection(value['items']))

    # The plan

    def plan(self):
        for key in sorted(self.last):
            kind, name = key.split(':', 1)
            kept = getattr(self, '_' + kind)(name, key)
            if kept is not None:
                self.kept[key] = kept
        self._join()
        # A group with an object kept for its own reason is kept whole, naming a later run that one of them names.
        direct = dict(self.kept)
        for key in sorted(direct):
            members = self.groups.members(key)
            by = next((direct[member][1] for member in members if member in direct and direct[member][1]), '')
            for member in members:
                self.kept.setdefault(member, ('later-dependent-change', by))
        while True:
            reversed_ = self._reversed()
            violations = [(key, by) for key, by in self._violations(reversed_) if key not in self.kept]
            if not violations:
                break
            for key, by in violations:
                self._keep(key, by)
        return reversed_

    def binding(self, reversed_, settles):
        """SHA-256 of the canonical snapshot that the confirmation binds (TASK-106).

        It holds the run, its file's hash and the fence's epoch, every object
        that the run changed, kept ones too, and every object that its inverse
        depends on, each with its revision and the metadata that the plan reads
        (status, pin, candidate, place, a digest of the line and its removal and
        privacy markers), and each line-history record that the plan needs with
        its availability. Unrelated progress, notices, usage and history appends
        are not in it.
        """
        keys = set(self.last)
        items = {key[len('item:'):] for key in self.last if key.startswith('item:')}
        keys.update('pin:' + name for name in items)
        keys.update('item:' + name for name, value in self.s.items.items() if value.get('superseded_by') in items)
        # An item that stops being current may leave what it had replaced when its own replacements end at a
        # current item (`_replaced`), so those replacements are read too.
        keys.update('item:' + other for name in items for other in self._replacements(name, reversed_))
        keys.update('line:' + line['id'] for line in self.s.lines if items.intersection(line['cites']))
        for key, record in self.targets.items():
            if key.startswith('line:') and record is not None:
                keys.update('item:' + item for item in record.value['cites'] if item.startswith('i_'))
        # The items that the run's pins and candidates name, and the candidates for the same pairs: a pin that is
        # on afterwards and a reopened candidate need their items current, and no other open candidate for the pair.
        keys.update('item:' + key[len('pin:'):] for key in self.last if key.startswith('pin:'))
        pairs = [set(self.candidate_records[key[len('candidate:'):]]['items']) for key in self.last
                 if key.startswith('candidate:') and key[len('candidate:'):] in self.candidate_records]
        keys.update('item:' + name for pair in pairs for name in pair)
        layouts = (state_plan._placements(list(self.s.lines)), state_plan._placements(
            [dict(id=name, part=part, pos=pos) for name, (part, pos, _) in self._layout(reversed_).items()]))
        for layout in layouts:
            for key in self.last:
                if key.startswith('line:') and key[len('line:'):] in layout:
                    keys.update('line:' + name for name in layout[key[len('line:'):]][2:] if name)
        keys.update('candidate:' + value['id'] for value in self.s.candidates
                    if items.intersection(value['items']) or set(value['items']) in pairs or value['id'] in settles)
        objects = [[key, self.revisions.get(key), self._meta(key)] for key in sorted(keys)]
        document = {'run': self.run, 'file': self.s.log_sha256, 'epoch': self.epoch, 'last': self.s.log['last'],
                    'objects': objects, 'history': sorted(self.needed)}
        return hashlib.sha256(_canonical(document).encode('ascii')).hexdigest()

    def _meta(self, key):
        kind, name = key.split(':', 1)
        if kind == 'item':
            value = self.s.items.get(name)
            return [name in self.s.forgotten, None if value is None else [value['kind'], _record(value, STATUS)]]
        if kind == 'pin':
            found = self.pin_records.get(name)
            return None if found is None else [found[0], _record(found[1], PIN)]
        if kind == 'candidate':
            value = self.candidate_records.get(name)
            return None if value is None else [value['status'], value['items'], value.get('closed', '')]
        markers = sorted([marker.get('kind', ''), 'restored_by' in marker, 'restored_at' in marker]
                         for marker in self.markers.get(name, ()))
        line = self.physical.get(name)
        if line is None:
            return [None, markers]
        digest = hashlib.sha256(_canonical(line).encode('ascii')).hexdigest()
        return [[line['part'], line['pos'], digest, bool(self.s.private.intersection(line['cites']))], markers]


def plan(project, argument, snapshot):
    """The undo preview of the run in `snapshot`, which the caller found eligible, for the run argument as given."""
    planner = _Planner(snapshot)
    reversed_ = planner.plan()
    changing = reversed_ - planner.still
    settles = planner._settles(changing) if changing else ()
    kept = [{'target': key, 'by': by, 'why': why} for key, (why, by) in sorted(planner.kept.items())
            if key not in planner.still]
    data = {'project': project, 'run': argument}
    if not changing:
        data['kept'] = kept
        return Plan(data, frozenset(), {}, {}, {}, {}, ())
    log = snapshot.log
    data['changes'] = {
        'saved': sum('item:' + item in changing for item in set(log['saved'])),
        'statuses': sum('item:' + item in changing for item in planner.statuses),
        'merges': sum('item:' + item in changing for item in {entry['item'] for entry in log['merges']}),
        'lines': sum(key.startswith('line:') for key in changing),
        'pins': sum(key.startswith('pin:') for key in changing),
        'conflicts': sum(key.startswith('candidate:') for key in changing) + len(settles),
    }
    data['kept'] = kept
    reasons = []
    for name in planner.line_entries:
        record = planner.targets.get('line:' + name)
        if 'line:' + name in changing and record is not None:
            why = start_memory.one_line(record.value['why'])
            if why and why not in reasons:
                reasons.append(why)
    if reasons:
        data['reasons'] = reasons
    data['binding'] = planner.binding(reversed_, settles)

    def chosen(prefix):
        return {key[len(prefix):]: planner.targets[key] for key in sorted(changing) if key.startswith(prefix)}
    return Plan(data, frozenset(changing), chosen('item:'), chosen('pin:'), chosen('line:'), chosen('candidate:'),
                settles)


def _plural(count, one, many=None):
    return '%d %s' % (count, one if count == 1 else many or one + 's')


def _list(words):
    return ', '.join(words[:-1]) + ' and ' + words[-1] if len(words) > 1 else words[0]


def say(plan):
    """What the agent tells the user before the yes: what the undo reverses and what stays."""
    data = plan.data
    if not plan.reversed:
        return SAY['nothing'] if data['kept'] else SAY['still']
    changes, words = data['changes'], []
    if changes['saved']:
        words.append('makes %s undone' % _plural(changes['saved'], 'saved item'))
    if changes['statuses']:
        words.append('gives %s back the status it had before the run' % _plural(changes['statuses'], 'item')
                     if changes['statuses'] == 1 else
                     'gives %s back the statuses they had before the run' % _plural(changes['statuses'], 'item'))
    if changes['merges']:
        words.append('reverses %s' % _plural(changes['merges'], 'merge'))
    if changes['lines']:
        words.append('puts %s back as it was' % _plural(changes['lines'], 'state line') if changes['lines'] == 1
                     else 'puts %s back as they were' % _plural(changes['lines'], 'state line'))
    if changes['pins']:
        words.append('moves %s back' % _plural(changes['pins'], 'pin'))
    if changes['conflicts']:
        words.append('closes or reopens %s' % _plural(changes['conflicts'], 'conflict candidate'))
    said = ['Undoing this run, as a new run, %s.' % _list(words)]
    if data['kept']:
        said.append('%s that the run changed %s as %s now; data.kept says why.' % (
            _plural(len(data['kept']), 'object'), 'stays' if len(data['kept']) == 1 else 'stay',
            'it is' if len(data['kept']) == 1 else 'they are'))
    return ' '.join(said)
