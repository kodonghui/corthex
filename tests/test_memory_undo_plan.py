"""TASK-105 and TASK-106: the undo preview's plan (API-153; SPEC-145) on fabricated projects.

Each world changes its records one apply at a time, as the item writer and the
state publisher do: every apply reserves one generation for the objects that it
changes, line changes append the exact line-history record of the version
before them, and the run logs come from `run_log.add`, which checks their links.
A change outside a logged run, such as a forget's, a pin command's or an apply
whose log failed, only advances the objects' revisions.
"""
import copy
import hashlib
import sys
import unittest

from _common import ROOT
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import run_log, state_plan, state_types, undo_plan
from test_memory_run_log import progress

AT = '2026-11-04T03:00:00.000Z'
DEVICE = 'd_0123456789ab'
EPOCH = '0123456789abcdef' * 2
ENTRY = 'e_0123456789ab'
LOG = 'claude-code-0123456789abcdef'


def ident(prefix, number):
    return '%s_%012d' % (prefix, number)


def item(number, kind='decision'):
    quote = dict(entry=ENTRY, log=LOG, device=DEVICE, start=0, end=4, speaker='user', said=AT, words='Keep')
    return dict(id=ident('i', number), kind=kind, title='Item %d' % number, text='An item.', quotes=[quote],
                status='current', saved=AT, device=DEVICE)


def status(value):
    return {key: value[key] for key in undo_plan.STATUS if key in value}


def objects(effects):
    keys = {'item:' + name for name in effects.get('saved', ())}
    keys |= {'item:' + entry['item'] for field in ('statuses', 'merges') for entry in effects.get(field, ())}
    keys |= {'pin:' + entry['item'] for entry in effects.get('pins', ())}
    keys |= {'candidate:' + entry['candidate'] for entry in effects.get('conflicts', ())}
    keys |= {'line:' + entry['line'] for entry in effects.get('lines', ())}
    return keys


class World:
    """A project's records, its line history and run logs, and the fence that their changes leave."""

    def __init__(self):
        self.generation, self.revisions, self.logs = 0, {}, {}
        self.items, self.lines, self.removed, self.pins, self.candidates = {}, {}, [], [], []
        self.history, self.forgotten, self.private = [], set(), set()
        self.apply_generation = self.apply_run = None

    # Runs and changes

    def run(self, number, *applies, kind='curate', undoes=''):
        log = run_log.start(ident('r', number), kind, AT, DEVICE, undoes)
        for apply in applies:
            log = self.apply(log, apply)
        self.logs[log['id']] = log
        return log

    def apply(self, log, changes):
        """One apply: `changes(world)` changes the records and returns their run log entries."""
        self.generation += 1
        self.apply_generation, self.apply_run = self.generation, log['id']
        effects = {}
        for part in changes(self):
            for field, values in part.items():
                effects.setdefault(field, []).extend(values)
        keys = sorted(objects(effects))
        effects['revisions'] = [{'id': key, 'before': self.revisions.get(key), 'after': self.generation}
                                for key in keys]
        self.revisions.update(dict.fromkeys(keys, self.generation))
        self.revisions['run:' + log['id']] = self.generation
        return run_log.add(log, progress(self.generation, self.revisions), AT, effects)

    def touch(self, *keys):
        """A change that no run log names: the objects take a new generation."""
        self.generation += 1
        self.revisions.update(dict.fromkeys(keys, self.generation))

    def save(self, value):
        self.items[value['id']] = copy.deepcopy(value)
        return {'saved': [value['id']]}

    def status(self, name, value, by=None):
        record = self.items[name]
        before = status(record)
        record['status'] = value
        record.pop('superseded_by', None)
        if by is not None:
            record['superseded_by'] = by
        record['changed'] = AT
        return {'statuses': [{'item': name, 'before': before, 'after': status(record)}]}

    def merge(self, value, *merged):
        value = dict(value, merges=list(merged))
        parts = [self.save(value), {'merges': [{'item': value['id'], 'merged': list(merged)}]}]
        return parts + [self.status(name, 'superseded', value['id']) for name in merged]

    def pin(self, name, on=True):
        found = [index for index, value in enumerate(self.pins) if value['item'] == name]
        record = {'on': on, 'at': AT, 'device': DEVICE}
        if found:
            index = found[0]
            before = {key: self.pins[index][key] for key in ('on', 'at', 'device')}
            self.pins[index] = dict(record, item=name)
            place = [index, index]
        else:
            before = None
            self.pins.append(dict(record, item=name))
            place = [None, len(self.pins) - 1]
        return {'pins': [{'item': name, 'from': before, 'to': record, 'place': place}]}

    def open(self, number, first, second):
        name = ident('c', number)
        self.candidates.append(dict(id=name, items=[first, second], at=AT, run=self.apply_run, by='curate',
                                    status='open'))
        return {'conflicts': [{'candidate': name, 'from': 'absent', 'to': 'open'}]}

    def close(self, name, value='settled'):
        record = next(candidate for candidate in self.candidates if candidate['id'] == name)
        before = record['status']
        record.update(status=value, closed=AT)
        return {'conflicts': [{'candidate': name, 'from': before, 'to': value}]}

    def place(self, name):
        return list(state_plan._placements(list(self.lines.values())).get(name, ()))

    def add(self, number, part='progress', pos=1, cites=(ENTRY,)):
        name = ident('s', number)
        self.lines[name] = dict(id=name, part=part, pos=pos, text='Line %d.' % number, cites=list(cites), at=AT,
                                device=DEVICE)
        return {'lines': [{'line': name, 'op': 'added', 'generation': self.apply_generation, 'history': None,
                           'before': [], 'after': self.place(name)}]}

    def record(self, name, op, why=''):
        """The TBL-119 record of the line's version before this apply changes it."""
        old = self.lines[name]
        record = state_types.HistoryRecord(state_types.history_record_bytes(dict(
            at=AT, run=self.apply_run, epoch=EPOCH, generation=self.apply_generation, line=name, part=old['part'],
            pos=old['pos'], op=op, text=old['text'], cites=old['cites'], why=why, device=DEVICE)))
        self.history.append(record)
        return record

    def change(self, name, op='changed', why='', **fields):
        before, record = self.place(name), self.record(name, op, why)
        self.lines[name].update(fields)
        return {'lines': [{'line': name, 'op': op, 'generation': self.apply_generation,
                           'history': [EPOCH, self.apply_generation, name, record.sha256], 'before': before,
                           'after': self.place(name)}]}

    def remove(self, name, op='removed', why='Not carried.'):
        before, record = self.place(name), self.record(name, op, why)
        del self.lines[name]
        self.removed.append(state_types.removal_marker(name, AT, DEVICE, 'edit'))
        return {'lines': [{'line': name, 'op': op, 'generation': self.apply_generation,
                           'history': [EPOCH, self.apply_generation, name, record.sha256], 'before': before,
                           'after': []}]}

    def forget(self, name):
        """What a forget leaves: a tombstone that makes the item private, and its object's new revision."""
        self.items.pop(name, None)
        self.forgotten.add(name)
        self.private.update({name, ENTRY})
        self.touch('item:' + name)

    # The plan

    def snapshot(self, log):
        data = run_log.log_bytes(log)
        return undo_plan.Snapshot(
            log=log, log_sha256=hashlib.sha256(data).hexdigest(),
            fence=progress(self.generation, self.revisions)['fence'], items=copy.deepcopy(self.items),
            forgotten=frozenset(self.forgotten), private=frozenset(self.private),
            lines=tuple(copy.deepcopy(list(self.lines.values()))), removed=tuple(copy.deepcopy(self.removed)),
            pins=tuple(copy.deepcopy(self.pins)), candidates=tuple(copy.deepcopy(self.candidates)),
            history=tuple(self.history), logs=tuple(value for key, value in self.logs.items() if key != log['id']))

    def plan(self, log, **changes):
        return undo_plan.plan('sample', log['id'], self.snapshot(log))


def kept(plan):
    return {entry['target']: (entry['why'], entry['by']) for entry in plan.data['kept']}


class UndoPlanTest(unittest.TestCase):
    def setUp(self):
        self.world = World()
        self.a, self.b, self.c = item(1), item(2), item(3, 'fact')

    def counts(self, **values):
        found = dict.fromkeys(('saved', 'statuses', 'merges', 'lines', 'pins', 'conflicts'), 0)
        found.update(values)
        return found

    # TC-362 and SPEC-145's second acceptance criterion

    def test_tc362_a_later_replacement_keeps_the_item_and_names_the_later_run(self):
        world = self.world
        first = world.run(1, lambda w: [w.save(self.a)])
        second = world.run(2, lambda w: [w.save(self.b), w.status(self.a['id'], 'superseded', self.b['id'])])
        plan = world.plan(first)
        self.assertEqual(plan.reversed, frozenset())
        self.assertEqual(plan.data, {'project': 'sample', 'run': first['id'], 'kept': [
            {'target': 'item:' + self.a['id'], 'by': second['id'], 'why': 'later-run'}]})
        self.assertEqual(undo_plan.say(plan), undo_plan.SAY['nothing'])
        # The later run itself can be undone: its replacement goes and the item it replaced is current again.
        later = world.plan(second)
        self.assertEqual(later.data['changes'], self.counts(saved=1, statuses=1))
        self.assertEqual(later.items, {self.a['id']: {'status': 'current'}, self.b['id']: {'status': 'undone'}})
        self.assertEqual(later.data['kept'], [])
        self.assertRegex(later.data['binding'], r'\A[0-9a-f]{64}\Z')
        self.assertEqual(undo_plan.say(later), 'Undoing this run, as a new run, makes 1 saved item undone and '
                                               'gives 1 item back the status it had before the run.')

    def test_tc381_a_later_change_that_no_log_names_keeps_the_object_despite_equal_bytes(self):
        world = self.world
        first = world.run(1, lambda w: [w.save(self.a), w.save(self.c)])
        before = copy.deepcopy(world.items)
        world.touch('item:' + self.a['id'])
        self.assertEqual(world.items, before)
        plan = world.plan(first)
        self.assertEqual(kept(plan), {'item:' + self.a['id']: ('later-unlogged-change', '')})
        self.assertEqual(plan.items, {self.c['id']: {'status': 'undone'}})
        self.assertEqual(plan.data['changes'], self.counts(saved=1))

    def test_a_revision_behind_the_run_or_a_record_unlike_the_run_left_is_unavailable(self):
        world = self.world
        first = world.run(1, lambda w: [w.save(self.a), w.save(self.b), w.save(self.c)])
        del world.revisions['item:' + self.a['id']]
        world.items[self.b['id']]['status'] = 'withdrawn'
        plan = world.plan(first)
        self.assertEqual(kept(plan), {'item:' + self.a['id']: ('revision-unavailable', ''),
                                      'item:' + self.b['id']: ('revision-unavailable', '')})
        self.assertEqual(plan.items, {self.c['id']: {'status': 'undone'}})

    def test_a_forgotten_item_stays_forgotten(self):
        world = self.world
        first = world.run(1, lambda w: [w.save(self.a), w.save(self.c)])
        world.forget(self.a['id'])
        plan = world.plan(first)
        self.assertEqual(kept(plan), {'item:' + self.a['id']: ('forgotten', '')})
        self.assertEqual(plan.items, {self.c['id']: {'status': 'undone'}})

    # Merges, replacements and their pins move together

    def test_a_merge_is_reversed_whole_or_kept_whole(self):
        world = self.world
        world.run(1, lambda w: [w.save(self.a), w.save(self.b)])
        merged = dict(item(4), title='Both decisions')
        second = world.run(2, lambda w: w.merge(merged, self.a['id'], self.b['id']), kind='consolidate')
        plan = world.plan(second)
        self.assertEqual(plan.data['changes'], self.counts(saved=1, statuses=2, merges=1))
        self.assertEqual(plan.items, {self.a['id']: {'status': 'current'}, self.b['id']: {'status': 'current'},
                                      merged['id']: {'status': 'undone'}})
        world.touch('item:' + self.b['id'])
        plan = world.plan(second)
        self.assertEqual(plan.reversed, frozenset())
        self.assertEqual(kept(plan), {'item:' + self.a['id']: ('later-dependent-change', ''),
                                      'item:' + self.b['id']: ('later-unlogged-change', ''),
                                      'item:' + merged['id']: ('later-dependent-change', '')})
        # The merge entry groups its items even where their statuses do not name the merged item.
        world = World()
        world.run(1, lambda w: [w.save(self.a), w.save(self.b)])
        third = world.run(3, lambda w: [w.save(dict(merged, merges=[self.a['id'], self.b['id']])),
                                        {'merges': [{'item': merged['id'], 'merged': [self.a['id'], self.b['id']]}]},
                                        w.status(self.a['id'], 'withdrawn'), w.status(self.b['id'], 'withdrawn')],
                          kind='consolidate')
        world.touch('item:' + self.a['id'])
        self.assertEqual(world.plan(third).reversed, frozenset())

    def test_pins_move_back_with_the_items_they_followed(self):
        world = self.world
        world.run(1, lambda w: [w.save(self.a)])
        world.pins.append(dict(item=self.a['id'], on=True, at=AT, device=DEVICE))
        second = world.run(2, lambda w: [w.save(self.b), w.status(self.a['id'], 'superseded', self.b['id']),
                                         w.pin(self.a['id'], False), w.pin(self.b['id'])])
        plan = world.plan(second)
        self.assertEqual(plan.data['changes'], self.counts(saved=1, statuses=1, pins=2))
        self.assertEqual(plan.pins, {self.a['id']: ({'on': True, 'at': AT, 'device': DEVICE}, 0),
                                     self.b['id']: (None, None)})
        # A later unpin of the replacement keeps the replacement, the item it replaced and the pins with them.
        world.touch('pin:' + self.b['id'])
        plan = world.plan(second)
        self.assertEqual(plan.reversed, frozenset())
        self.assertEqual(set(kept(plan)), {'item:' + self.a['id'], 'item:' + self.b['id'], 'pin:' + self.a['id'],
                                           'pin:' + self.b['id']})
        # A pin that the run gave an item that it saved stays with the item.
        world = World()
        third = world.run(3, lambda w: [w.save(self.c), w.pin(self.c['id'])])
        world.touch('item:' + self.c['id'])
        self.assertEqual(kept(world.plan(third)), {'item:' + self.c['id']: ('later-unlogged-change', ''),
                                                   'pin:' + self.c['id']: ('later-dependent-change', '')})

    def test_an_item_that_a_later_change_replaced_with_the_run_s_item_keeps_that_item(self):
        world = self.world
        world.run(1, lambda w: [w.save(self.a)])
        second = world.run(2, lambda w: [w.save(self.b)])
        third = world.run(3, lambda w: [w.status(self.a['id'], 'superseded', self.b['id'])])
        plan = world.plan(second)
        self.assertEqual(plan.data['kept'], [{'target': 'item:' + self.b['id'], 'by': third['id'],
                                              'why': 'later-dependent-change'}])

    # TC-383: dependent later pins and lines keep their group; independent groups are reversed

    def test_tc383_a_later_pin_or_decision_line_keeps_the_item_and_its_group(self):
        world = self.world
        first = world.run(1, lambda w: [w.save(self.a), w.save(self.c)])
        world.pins.append(dict(item=self.a['id'], on=True, at=AT, device=DEVICE))
        world.touch('pin:' + self.a['id'])
        plan = world.plan(first)
        self.assertEqual(kept(plan), {'item:' + self.a['id']: ('later-dependent-change', '')})
        self.assertEqual(plan.items, {self.c['id']: {'status': 'undone'}})
        world.pins.clear()
        world.touch('pin:' + self.a['id'])
        second = world.run(2, lambda w: [w.add(1, 'decisions', 1, [self.a['id']])])
        plan = world.plan(first)
        self.assertEqual(kept(plan), {'item:' + self.a['id']: ('later-dependent-change', second['id'])})
        self.assertEqual(plan.items, {self.c['id']: {'status': 'undone'}})

    def test_tc383_a_later_insertion_next_to_an_added_line_keeps_its_order_group(self):
        world = self.world
        world.lines[ident('s', 9)] = dict(id=ident('s', 9), part='progress', pos=1, text='Old.', cites=[ENTRY],
                                          at=AT, device=DEVICE)
        first = world.run(1, lambda w: [w.add(1, pos=2), w.add(2, pos=3), w.save(self.c)])
        second = world.run(2, lambda w: [w.add(3, pos=4)])
        plan = world.plan(first)
        self.assertEqual(kept(plan), {'line:' + ident('s', 1): ('later-dependent-change', second['id']),
                                      'line:' + ident('s', 2): ('later-dependent-change', second['id'])})
        self.assertEqual(plan.items, {self.c['id']: {'status': 'undone'}})
        # A later change of a neighbour's text alone, which its run log shows, places nothing.
        world = World()
        world.lines[ident('s', 9)] = dict(id=ident('s', 9), part='progress', pos=1, text='Old.', cites=[ENTRY],
                                          at=AT, device=DEVICE)
        first = world.run(1, lambda w: [w.add(1, pos=2), w.save(self.c)])
        world.run(2, lambda w: [w.change(ident('s', 9), text='Old, reworded.')])
        plan = world.plan(first)
        self.assertEqual(plan.lines, {ident('s', 1): None})
        self.assertEqual(plan.data['changes'], self.counts(saved=1, lines=1))
        # The same change with no log naming it counts as a placement.
        world.touch('line:' + ident('s', 9))
        self.assertEqual(kept(world.plan(first)), {'line:' + ident('s', 1): ('later-dependent-change', '')})

    # TC-385, TC-392 and TC-380: line history

    def test_tc385_an_ordinary_removed_line_comes_back_and_a_privacy_marker_never_does(self):
        world = self.world
        world.lines[ident('s', 1)] = dict(id=ident('s', 1), part='progress', pos=1, text='Was here.',
                                          cites=[ENTRY], at=AT, device=DEVICE)
        first = world.run(1, lambda w: [w.remove(ident('s', 1), why='Done now.')])
        plan = world.plan(first)
        record = plan.lines[ident('s', 1)]
        self.assertEqual((record.value['text'], record.value['op']), ('Was here.', 'removed'))
        self.assertEqual((plan.data['changes'], plan.data['reasons']), (self.counts(lines=1), ['Done now.']))
        world.removed[0]['kind'] = 'privacy'
        plan = world.plan(first)
        self.assertEqual(kept(plan), {'line:' + ident('s', 1): ('forgotten', '')})
        # A version that cites what a forget made private is not restored either.
        world.removed[0]['kind'] = 'edit'
        world.private.add(ENTRY)
        self.assertEqual(kept(world.plan(first)), {'line:' + ident('s', 1): ('forgotten', '')})

    def test_tc392_a_missing_history_record_keeps_its_line_and_independent_changes_go(self):
        world = self.world
        world.lines[ident('s', 1)] = dict(id=ident('s', 1), part='progress', pos=1, text='Before.', cites=[ENTRY],
                                          at=AT, device=DEVICE)
        first = world.run(1, lambda w: [w.change(ident('s', 1), text='After.', why='Reworded.'), w.save(self.c)])
        self.assertEqual(world.plan(first).data['changes'], self.counts(saved=1, lines=1))
        world.history.clear()
        plan = world.plan(first)
        self.assertEqual(kept(plan), {'line:' + ident('s', 1): ('history-unavailable', '')})
        self.assertEqual((plan.items, plan.data['changes']), ({self.c['id']: {'status': 'undone'}},
                                                               self.counts(saved=1)))
        self.assertNotIn('reasons', plan.data)
        # A primary history that cannot be read is no better.
        snapshot = world.snapshot(first)
        unread = undo_plan.plan('sample', first['id'], undo_plan.Snapshot(**dict(vars(snapshot), history=None)))
        self.assertEqual(kept(unread), kept(plan))
        # A kept line that cites an item which the undo would make undone keeps that item too.
        world = World()
        world.lines[ident('s', 1)] = dict(id=ident('s', 1), part='progress', pos=1, text='Before.', cites=[ENTRY],
                                          at=AT, device=DEVICE)
        first = world.run(1, lambda w: [w.save(self.a), w.save(self.c),
                                        w.change(ident('s', 1), text='After.', cites=[self.a['id']])])
        world.history.clear()
        self.assertEqual(kept(world.plan(first)), {'line:' + ident('s', 1): ('history-unavailable', ''),
                                                   'item:' + self.a['id']: ('later-dependent-change', '')})

    def test_a_line_that_the_run_added_goes_only_with_a_readable_history(self):
        # Removing it appends its text to the line history first, as `undone`, so a history that cannot be read
        # keeps it, and the item that it cites with it; an empty history that can be read is enough.
        world = self.world
        first = world.run(1, lambda w: [w.save(self.a), w.save(self.c), w.add(1, cites=[self.a['id']])])
        self.assertEqual(world.plan(first).data['changes'], self.counts(saved=2, lines=1))
        snapshot = world.snapshot(first)
        unread = undo_plan.plan('sample', first['id'], undo_plan.Snapshot(**dict(vars(snapshot), history=None)))
        self.assertEqual(kept(unread), {'line:' + ident('s', 1): ('history-unavailable', ''),
                                        'item:' + self.a['id']: ('later-dependent-change', '')})
        self.assertEqual((unread.items, unread.lines, unread.data['changes']),
                         ({self.c['id']: {'status': 'undone'}}, {}, self.counts(saved=1)))

    def test_a_line_that_the_run_added_and_removed_again_is_already_as_before(self):
        world = self.world
        name = ident('s', 1)
        first = world.run(1, lambda w: [w.save(self.a), w.add(1, cites=[self.a['id']])],
                          lambda w: [w.remove(name)])
        for snapshot in (world.snapshot(first), undo_plan.Snapshot(**dict(vars(world.snapshot(first)),
                                                                           history=None))):
            plan = undo_plan.plan('sample', first['id'], snapshot)
            self.assertEqual((plan.reversed, plan.lines, plan.data['changes'], plan.data['kept']),
                             (frozenset({'item:' + self.a['id']}), {}, self.counts(saved=1), []))

    def test_tc380_only_the_linked_record_before_the_first_change_restores_a_line(self):
        world = self.world
        name = ident('s', 1)
        world.lines[name] = dict(id=name, part='progress', pos=1, text='Version 0.', cites=[ENTRY], at=AT,
                                 device=DEVICE)
        first = world.run(1, lambda w: [w.change(name, text='Version 1.')],
                          lambda w: [w.change(name, text='Version 2.')], kind='consolidate')
        # An unused staged record of the first apply, never linked by the log, comes first in the history.
        orphan = state_types.HistoryRecord(state_types.history_record_bytes(dict(
            at=AT, run=first['id'], epoch=EPOCH, generation=first['applies'][0]['generation'], line=name,
            part='progress', pos=1, op='changed', text='Staged, never applied.', cites=[ENTRY], why='',
            device=DEVICE)))
        world.history.insert(0, orphan)
        plan = world.plan(first)
        self.assertEqual(plan.lines[name].value['text'], 'Version 0.')
        self.assertEqual(plan.data['changes'], self.counts(lines=1))
        # A link to a record of another line restores nothing.
        world = World()
        for number in (1, 2):
            world.lines[ident('s', number)] = dict(id=ident('s', number), part='progress', pos=number,
                                                   text='Version 0.', cites=[ENTRY], at=AT, device=DEVICE)
        first = world.run(1, lambda w: [w.change(ident('s', 1), text='Version 1.'),
                                        w.change(ident('s', 2), text='Version 1.')])
        one, two = first['lines']
        one['history'][3], two['history'][3] = two['history'][3], one['history'][3]
        self.assertEqual(kept(world.plan(first)), {'line:' + ident('s', 1): ('history-unavailable', ''),
                                                   'line:' + ident('s', 2): ('history-unavailable', '')})

    def test_a_restored_decision_needs_a_current_decision(self):
        world = self.world
        name = ident('s', 1)
        world.run(1, lambda w: [w.save(self.a)])
        world.lines[name] = dict(id=name, part='decisions', pos=1, text='Decided.', cites=[self.a['id']], at=AT,
                                 device=DEVICE)
        second = world.run(2, lambda w: [w.save(self.b), w.status(self.a['id'], 'superseded', self.b['id']),
                                         w.change(name, text='Decided again.', cites=[self.b['id']])])
        self.assertEqual(world.plan(second).data['changes'], self.counts(saved=1, statuses=1, lines=1))
        third = world.run(3, lambda w: [w.save(item(5)), w.status(self.b['id'], 'superseded', ident('i', 5))])
        plan = world.plan(second)
        self.assertEqual(plan.reversed, frozenset())
        self.assertEqual(kept(plan), {'item:' + self.a['id']: ('later-dependent-change', third['id']),
                                      'item:' + self.b['id']: ('later-run', third['id']),
                                      'line:' + name: ('later-dependent-change', third['id'])})

    # Candidates

    def test_candidates_close_reopen_or_settle_with_their_items(self):
        world = self.world
        world.run(1, lambda w: [w.save(self.a), w.save(self.b)])
        second = world.run(2, lambda w: [w.save(self.c), w.open(1, self.c['id'], self.a['id'])])
        plan = world.plan(second)
        self.assertEqual((plan.candidates, plan.settles), ({ident('c', 1): 'settled'}, ()))
        # An open candidate that a later run recorded settles when the undo makes one of its items undone.
        world.run(3, lambda w: [w.open(2, self.b['id'], self.c['id'])])
        plan = world.plan(second)
        self.assertEqual((plan.settles, plan.data['changes']), ((ident('c', 2),), self.counts(saved=1, conflicts=2)))
        # A candidate that a run closed reopens only while both of its items are current afterwards.
        world = World()
        world.run(1, lambda w: [w.save(self.a), w.save(self.b), w.open(1, self.a['id'], self.b['id'])])
        replacement = item(4)
        fourth = world.run(4, lambda w: [w.save(replacement), w.status(self.a['id'], 'superseded', ident('i', 4)),
                                         w.close(ident('c', 1))])
        plan = world.plan(fourth)
        self.assertEqual(plan.candidates, {ident('c', 1): 'open'})
        world.run(5, lambda w: [w.status(self.b['id'], 'withdrawn')])
        plan = world.plan(fourth)
        self.assertEqual(kept(plan), {'candidate:' + ident('c', 1): ('later-dependent-change', '')})
        self.assertEqual(plan.items, {self.a['id']: {'status': 'current'}, ident('i', 4): {'status': 'undone'}})

    # TASK-106: the binding

    def test_the_binding_moves_with_relevant_drift_only(self):
        world = self.world
        name = ident('s', 1)
        world.lines[name] = dict(id=name, part='progress', pos=1, text='Before.', cites=[ENTRY], at=AT,
                                 device=DEVICE)
        first = world.run(1, lambda w: [w.save(self.a), w.save(self.c), w.change(name, text='After.')])
        world.touch('item:' + self.a['id'])
        plan = world.plan(first)
        binding = plan.data['binding']
        self.assertEqual(world.plan(first).data, plan.data)
        # Unrelated objects, other runs and their history appends leave it as it was.
        unrelated = World()
        unrelated.__dict__.update(copy.deepcopy(world.__dict__))
        unrelated.run(2, lambda w: [w.save(item(7, 'fact'))])
        unrelated.lines[ident('s', 8)] = dict(id=ident('s', 8), part='next', pos=1, text='Elsewhere.',
                                              cites=[ENTRY], at=AT, device=DEVICE)
        unrelated.run(3, lambda w: [w.change(ident('s', 8), text='Elsewhere, reworded.')])
        self.assertEqual(unrelated.plan(first).data, plan.data)
        # The kept item changing again keeps the same reason and counts but moves the binding.
        world.touch('item:' + self.a['id'])
        again = world.plan(first)
        self.assertEqual({key: value for key, value in again.data.items() if key != 'binding'},
                         {key: value for key, value in plan.data.items() if key != 'binding'})
        self.assertNotEqual(again.data['binding'], binding)
        # So does a record that changed without a new revision.
        for record, field, value in ((world.items[self.a['id']], 'status', 'withdrawn'),
                                     (world.lines[name], 'text', 'After, edited.')):
            old = record[field]
            record[field] = value
            self.assertNotEqual(world.plan(first).data['binding'], again.data['binding'])
            record[field] = old
        self.assertEqual(world.plan(first).data['binding'], again.data['binding'])
        # So does the run's file, and the history that the plan needs.
        snapshot = world.snapshot(first)
        other_file = undo_plan.plan('sample', first['id'], undo_plan.Snapshot(**dict(vars(snapshot),
                                                                                   log_sha256='0' * 64)))
        self.assertNotEqual(other_file.data['binding'], again.data['binding'])
        world.history.clear()
        self.assertNotEqual(world.plan(first).data['binding'], again.data['binding'])

    def test_the_binding_holds_the_items_that_the_run_s_pins_and_candidates_name(self):
        def moves(world, log, key):
            """Whether a new revision of `key` alone, which changes nothing else in the preview, moves the binding."""
            before = world.plan(log).data
            world.touch(key)
            after = world.plan(log).data
            self.assertEqual({field: value for field, value in after.items() if field != 'binding'},
                             {field: value for field, value in before.items() if field != 'binding'})
            return after['binding'] != before['binding']

        # A candidate that the run closed reopens only while both of its items are current, also the one that the run
        # did not change.
        world = World()
        world.run(1, lambda w: [w.save(self.a), w.save(self.b), w.open(1, self.a['id'], self.b['id'])])
        fourth = world.run(4, lambda w: [w.save(item(4)), w.status(self.a['id'], 'superseded', ident('i', 4)),
                                         w.close(ident('c', 1))])
        self.assertEqual(world.plan(fourth).candidates, {ident('c', 1): 'open'})
        self.assertTrue(moves(world, fourth, 'item:' + self.b['id']))
        # A run that changed neither item of the candidate that it closed, and the other open candidate for the pair
        # that keeps it closed.
        world = World()
        world.run(1, lambda w: [w.save(self.a), w.save(self.b), w.open(1, self.a['id'], self.b['id'])])
        second = world.run(2, lambda w: [w.save(self.c), w.close(ident('c', 1))])
        self.assertEqual(world.plan(second).candidates, {ident('c', 1): 'open'})
        for name in (self.a['id'], self.b['id']):
            self.assertTrue(moves(world, second, 'item:' + name))
        world.run(3, lambda w: [w.open(2, self.b['id'], self.a['id'])])
        self.assertEqual(kept(world.plan(second)), {'candidate:' + ident('c', 1): ('later-dependent-change', '')})
        self.assertTrue(moves(world, second, 'candidate:' + ident('c', 2)))
        # A pin that is on afterwards names a current item, which the run did not change.
        world = World()
        world.run(1, lambda w: [w.save(self.a), w.pin(self.a['id'])])
        third = world.run(3, lambda w: [w.pin(self.a['id'], on=False)])
        self.assertEqual(world.plan(third).data['changes'], self.counts(pins=1))
        self.assertTrue(moves(world, third, 'item:' + self.a['id']))
        # An item that nothing of the run names leaves it as it was.
        world.run(4, lambda w: [w.save(self.b)])
        self.assertFalse(moves(world, third, 'item:' + self.b['id']))

    def test_a_run_whose_changes_are_already_undone_by_its_own_later_applies_needs_nothing(self):
        world = self.world
        world.run(1, lambda w: [w.save(self.a), w.save(self.b)])
        second = world.run(2, lambda w: [w.open(1, self.a['id'], self.b['id'])],
                           lambda w: [w.close(ident('c', 1))], kind='consolidate')
        plan = world.plan(second)
        self.assertEqual((plan.reversed, plan.data['kept']), (frozenset(), []))
        self.assertEqual(undo_plan.say(plan), undo_plan.SAY['still'])
        third = world.run(3, lambda w: [w.status(self.a['id'], 'withdrawn')],
                          lambda w: [w.status(self.a['id'], 'current')], kind='consolidate')
        plan = world.plan(third)
        self.assertEqual((plan.reversed, plan.data['kept']), (frozenset(), []))

    def test_an_undo_run_is_planned_like_any_other(self):
        world = self.world
        name = ident('s', 1)
        first = world.run(1, lambda w: [w.save(self.a), w.add(1)])
        undone = world.run(2, lambda w: [w.status(self.a['id'], 'undone'), w.remove(name, op='undone', why='')],
                           kind='undo', undoes=first['id'])
        world.items[self.a['id']]['undone_by'] = undone['id']
        undone['statuses'][0]['after']['undone_by'] = undone['id']
        plan = world.plan(undone)
        self.assertEqual(plan.items, {self.a['id']: {'status': 'current'}})
        self.assertEqual(plan.lines[name].value['op'], 'undone')
        self.assertEqual(plan.data['changes'], self.counts(statuses=1, lines=1))

    def test_the_say_stays_within_the_schema(self):
        world = self.world
        names = [ident('s', number) for number in range(1, 4)]
        for number, name in enumerate(names, 1):
            world.lines[name] = dict(id=name, part='progress', pos=number, text='Line.', cites=[ENTRY], at=AT,
                                     device=DEVICE)
        world.run(1, lambda w: [w.save(self.a)])
        world.pins.append(dict(item=self.a['id'], on=True, at=AT, device=DEVICE))
        second = world.run(2, lambda w: [w.save(self.b), w.save(self.c), w.status(self.a['id'], 'superseded',
                                                                                     self.b['id']),
                                         w.pin(self.a['id'], False), w.pin(self.b['id']),
                                         w.open(1, self.c['id'], self.b['id'])] +
                           [w.change(name, text='Changed.', why='x' * 200) for name in names])
        world.touch('line:' + names[0])
        plan = world.plan(second)
        said = undo_plan.say(plan)
        self.assertTrue(said.isascii() and len(said) <= 600, said)
        self.assertIn('1 object that the run changed stays as it is now', said)


if __name__ == '__main__':
    unittest.main()
