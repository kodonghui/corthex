"""TASK-103: ID-only run logs (TBL-121) on fabricated format-2 stores.

TC-358, TC-359, TC-360 and TC-382, and the TBL-121 part of SPEC-009's fourth
acceptance criterion through the retention helper. No model is called; the
worker that adds a curation's applies (TASK-088) and the session start that
calls retention are not wired to a hook or command before the 0.3.0 activation.
"""
import contextlib
import copy
import hashlib
import json
import os
import sys
import time
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import curate_apply, curator_answers, files, item_types, locks, revision_io, run_log
from memory_lib import state_edits, state_types
import test_memory_state_edits as edits_fixture
from test_memory_curator_answers import AT, DEVICE, LATER, LOG, answer, change, quote, saved
from test_memory_fence_plan import PROGRESS
from test_memory_state_edits import changed, edits, ident, row

RUN = 'r_0123456789ad'
EPOCH = PROGRESS['fence']['epoch']


def progress(generation, revisions):
    value = copy.deepcopy(PROGRESS)
    value['fence'].update(generation=generation, revisions=dict(revisions))
    return value


def item_apply(generation, items):
    """Synthetic effects of one item apply that saved `items`."""
    return {'saved': list(items),
            'revisions': [{'id': 'item:' + item, 'before': None, 'after': generation} for item in items]}


def logged(run=RUN, *, kind='curate', ended=LATER, generations=(9,), undoes=''):
    """A whole log of synthetic applies, each saving one new item, started when it ended."""
    log = run_log.start(run, kind, ended, DEVICE, undoes)
    revisions = {}
    for generation in generations:
        item = ident('i', str(generation % 10))[:-1] + 'a'
        revisions.update({'run:' + run: generation, 'item:' + item: generation})
        log = run_log.add(log, progress(generation, revisions), ended, item_apply(generation, [item]))
    return log


class RunLogFlowTest(unittest.TestCase):
    """The actual item writer and line publisher, with their applies logged as TASK-088 will log them."""

    def setUp(self):
        self.fixture = edits_fixture.StateEditsTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.project = self.fixture.project
        (self.project / 'runs').mkdir()

    def runs(self):
        return sorted(path.name for path in (self.project / 'runs').iterdir())

    def apply(self, value, items, *, fail_second=False):
        """Check an answer, apply it in its two applies and log each before progress, under the leases."""
        fixture, memory = self.fixture, self.fixture.memory
        sent = curator_answers.sent(items=items, logs=[(LOG, fixture.turns.entries)], lines=fixture.view())
        checked = curator_answers.check_curate(value, sent=sent, device=DEVICE)
        log, written = run_log.start(RUN, 'curate', LATER, DEVICE), []
        with fixture.held():
            check = revision_io.guard(memory, self.project, fixture.deadline, curator=True)
            applied = curate_apply.apply(memory, self.project, fixture.proof(), checked, LATER, RUN, fixture.deadline)
            if applied is not None:
                log = run_log.add(log, applied['progress'], LATER, applied['effects'])
                written.append(run_log.write(memory, self.project, log, check))
            result = state_edits.apply(memory, self.project, fixture.proof(), checked.state, sent=sent,
                                       saved=() if applied is None else applied['saved'], at=LATER, run=RUN,
                                       deadline=fixture.deadline)
            if result['lines']:
                log = run_log.add(log, result['progress'], LATER, run_log.lines(result['lines']))
                with mock.patch.object(files, 'replace_bytes', side_effect=OSError('disk full')) if fail_second \
                        else contextlib.nullcontext():
                    written.append(run_log.write(memory, self.project, log, check))
            notes = list(memory.notes)
        return applied, result, log, written, notes

    def test_tc358_a_run_log_names_ids_statuses_revisions_and_history_and_no_text(self):
        fixture = self.fixture
        marks = {name: name + '-mark-' + os.urandom(4).hex() for name in ('rule', 'other', 'added', 'replaced',
                                                                        'line', 'edited', 'reason', 'said')}
        said = fixture.turns.say('user', 'Keep one script for the hooks, ' + marks['said'] + '.')
        # The rule's ID already has a revision in the fixture's fence.
        rule = dict(saved('decision', said, item='i_0123456789ab'), title=marks['rule'], text=marks['rule'] + '.')
        other = dict(saved('fact', fixture.done), title=marks['other'], text=marks['other'] + '.')
        fixture.store(rule, other)
        earlier = {'id': 'c_0123456789ab', 'items': [rule['id'], other['id']], 'at': AT, 'run': 'r_0123456789ab',
                   'by': 'curate', 'status': 'open'}
        (self.project / 'layer/conflicts.json').write_bytes(json.dumps({'candidates': [earlier]}).encode())
        (self.project / 'layer/pins.json').write_bytes(item_types.pins_bytes(
            {'pins': [{'item': rule['id'], 'on': True, 'at': AT, 'device': DEVICE}]}))
        line = row(ident('s', '1'), 'progress', 0, marks['line'], [fixture.done['id']])
        fixture.write_state(line)
        later = fixture.turns.say('user', 'Use two scripts instead, ' + marks['said'] + ' again.')
        value = answer(
            change(quote(later, 'Use two scripts instead'), title=marks['added'], text=marks['added'] + '.',
                   conflicts=[other['id']]),
            change(quote(later, 'Use two scripts instead'), action='replace', targets=[rule['id']], kind='decision',
                   title=marks['replaced'], text=marks['replaced'] + '.'),
            state=edits(change=[changed(line['id'], marks['edited'], [later['id']], why=marks['reason'])]))
        before = fixture.progress()['fence']
        applied, result, log, written, notes = self.apply(value, [rule, other])
        self.assertEqual((written, notes), ([True, True], []))
        (first, second) = [number for number, _ in applied['saved']]
        added, replacement = [item for _, item in applied['saved']]
        self.assertEqual((first, second), (1, 2))
        g1 = before['generation'] + 1
        g2 = g1 + 1
        stored = run_log.read(self.project, RUN)
        self.assertEqual(stored, log)
        self.assertEqual(self.runs(), [RUN + '.json'])
        self.assertEqual((stored['kind'], stored['at'], stored['ended'], stored['device'], stored['undoes'],
                          stored['epoch'], stored['last']), ('curate', LATER, LATER, DEVICE, '', EPOCH, g2))
        self.assertEqual(stored['saved'], [added, replacement])
        self.assertEqual(stored['statuses'], [{'item': rule['id'], 'before': {'status': 'current'},
                                               'after': {'status': 'superseded', 'superseded_by': replacement}}])
        self.assertEqual(stored['pins'], [
            {'item': rule['id'], 'from': {'on': True, 'at': AT, 'device': DEVICE},
             'to': {'on': False, 'at': LATER, 'device': DEVICE}, 'place': [0, 0]},
            {'item': replacement, 'from': None, 'to': {'on': True, 'at': LATER, 'device': DEVICE}, 'place': [None, 1]}])
        candidates = json.loads((self.project / 'layer/conflicts.json').read_bytes())['candidates']
        self.assertEqual([(value['id'], value['status']) for value in candidates][0], (earlier['id'], 'settled'))
        candidate = candidates[1]['id']
        self.assertEqual(stored['conflicts'], [{'candidate': candidate, 'from': 'absent', 'to': 'open'},
                                               {'candidate': earlier['id'], 'from': 'open', 'to': 'settled'}])
        history = state_types.parse_history((self.project / 'state-history.jsonl').read_bytes())
        (record,) = history
        self.assertEqual(stored['lines'], [{'line': line['id'], 'op': 'changed', 'generation': g2,
                                            'history': [EPOCH, g2, line['id'], record.sha256],
                                            'before': ['progress', 0, '', ''], 'after': ['progress', 0, '', '']}])
        self.assertEqual(record.sha256, hashlib.sha256(record.raw).hexdigest())
        items = sorted('item:' + item for item in (added, replacement, rule['id']))
        first_changes = sorted(items + ['pin:' + rule['id'], 'pin:' + replacement, 'candidate:' + candidate,
                                        'candidate:' + earlier['id']])
        self.assertEqual(stored['applies'], [{'generation': g1, 'at': LATER, 'changes': first_changes},
                                             {'generation': g2, 'at': LATER, 'changes': ['line:' + line['id']]}])
        known = before['revisions']
        self.assertEqual(stored['revisions'], [{'id': key, 'before': known.get(key), 'after': g1} for key in first_changes] +
                         [{'id': 'line:' + line['id'], 'before': known.get('line:' + line['id']), 'after': g2}])
        fence = fixture.progress()['fence']
        self.assertEqual(fence['revisions']['run:' + RUN], g2)
        self.assertTrue(run_log.eligible(stored, fixture.progress(), DEVICE))
        self.assertIn({'id': 'item:' + rule['id'], 'before': 3, 'after': g1}, stored['revisions'])
        self.assertFalse(run_log.eligible(stored, fixture.progress(), 'd_zyxwvtsrqpnm'))
        self.assertEqual(run_log.listed(self.project, fixture.progress(), DEVICE, when=LATER, days=100), [stored])
        data = (self.project / 'runs' / (RUN + '.json')).read_bytes()
        self.assertEqual(data, run_log.log_bytes(stored))
        for name, mark in sorted(marks.items()):
            with self.subTest(text=name):
                self.assertNotIn(mark.encode(), data)
        for words in ('Use two scripts', 'Keep one script', fixture.done['text']):
            self.assertNotIn(words.encode(), data)

    def test_tc359_a_curation_that_changes_nothing_leaves_no_run_log(self):
        rule = self.fixture.decision()
        self.fixture.write_state(row(ident('s', '1'), 'decisions', 0, 'One script serves the hooks.', [rule['id']]))
        applied, result, log, written, notes = self.apply(answer(), [rule])
        self.assertEqual((applied, result['lines'], written, notes, log['applies']), (None, (), [], [], []))
        self.assertEqual(self.runs(), [])
        # A log without an apply cannot even be encoded.
        with self.assertRaises(ValueError):
            run_log.log_bytes(log)

    def test_tc382_a_whole_looking_first_apply_after_a_failed_second_write_is_not_selectable(self):
        fixture = self.fixture
        rule = fixture.decision()
        line = row(ident('s', '1'), 'progress', 0, 'The hook script is written.', [fixture.done['id']])
        fixture.write_state(line)
        later = fixture.turns.say('user', 'Add a Windows check to the hooks.')
        value = answer(change(quote(later, 'Add a Windows check')),
                       state=edits(change=[changed(line['id'], 'The hook script and its Windows check.',
                                                   [later['id']])]))
        applied, result, log, written, notes = self.apply(value, [rule], fail_second=True)
        self.assertEqual(written, [True, False])
        ((error, count, step),) = notes
        self.assertEqual((type(error), count, step), (OSError, None, 'curate'))
        stored = run_log.read(self.project, RUN)
        # The file holds the first apply whole; the run fence has moved on to the second.
        self.assertEqual(len(stored['applies']), 1)
        self.assertEqual(stored['last'] + 1, fixture.progress()['fence']['revisions']['run:' + RUN])
        self.assertFalse(run_log.eligible(stored, fixture.progress(), DEVICE))
        self.assertEqual(run_log.listed(self.project, fixture.progress(), DEVICE, when=LATER, days=100), [])
        # The applies themselves stand: the item is saved and the line changed.
        self.assertEqual(fixture.lines()[line['id']]['text'], 'The hook script and its Windows check.')
        self.assertEqual(fixture.item(applied['saved'][0][1])['status'], 'current')


class RunLogRecordTest(unittest.TestCase):
    def test_a_log_round_trips_and_its_bytes_are_canonical(self):
        log = logged(generations=(9, 11))
        data = run_log.log_bytes(log)
        self.assertEqual(run_log.parse(data), log)
        self.assertEqual(list(json.loads(data)), run_log.FIELDS)
        self.assertEqual(run_log.log_bytes(json.loads(data)), data)
        self.assertTrue(data.endswith(b'}\n'))
        self.assertEqual([entry['generation'] for entry in log['applies']], [9, 11])
        self.assertEqual(log['last'], 11)

    def test_add_takes_its_generation_from_a_reservation_of_this_run(self):
        log = run_log.start(RUN, 'curate', AT, DEVICE)
        item = ident('i', '1')
        effects = item_apply(9, [item])
        for fence in ({'item:' + item: 9}, {'item:' + item: 9, 'run:r_0123456789ab': 9},
                      {'item:' + item: 9, 'run:' + RUN: 8}):
            with self.subTest(fence=fence), self.assertRaises(ValueError):
                run_log.add(log, progress(9, fence), LATER, effects)
        good = progress(9, {'item:' + item: 9, 'run:' + RUN: 9})
        for bad in ({}, {'saved': [item]}, dict(effects, revisions=[dict(effects['revisions'][0], after=8)]),
                    dict(effects, text='x')):
            with self.subTest(effects=bad), self.assertRaises(ValueError):
                run_log.add(log, good, LATER, bad)
        logged_once = run_log.add(log, good, LATER, effects)
        other = progress(10, {'item:' + item: 9, 'run:' + RUN: 10})
        other['fence']['epoch'] = 'f' * 32
        with self.assertRaises(ValueError):
            run_log.add(logged_once, other, LATER, item_apply(10, [ident('i', '2')]))
        # Turns merge into one range per raw log.
        second = ident('i', '2')
        log = run_log.add(logged_once, progress(10, {'item:' + item: 9, 'item:' + second: 10, 'run:' + RUN: 10}),
                          LATER, dict(item_apply(10, [second]), turns={LOG: [5, 9]}))
        log = run_log.add(log, progress(11, {'item:' + item: 9, 'item:' + second: 10, 'item:i_000000000003': 11,
                                             'run:' + RUN: 11}),
                          LATER, dict(item_apply(11, ['i_000000000003']), turns={LOG: [2, 4]}))
        self.assertEqual(log['turns'], {LOG: [2, 9]})

    def test_logs_that_do_not_link_their_applies_or_carry_text_are_refused(self):
        good = logged(generations=(9, 11))
        line = {'line': ident('s', '1'), 'op': 'changed', 'generation': 11, 'history': [EPOCH, 11, ident('s', '1'), 'a' * 64],
                'before': ['progress', 0, '', ''], 'after': ['progress', 1, '', '']}

        def variant(**changes):
            value = copy.deepcopy(good)
            value.update(changes)
            return value
        cases = {
            'unknown field': variant(title='A title'),
            'no apply': variant(applies=[], revisions=[], saved=[]),
            'applies out of order': variant(applies=list(reversed(good['applies']))),
            'last is not the last apply': variant(last=9),
            'ended is not the last apply': variant(ended='2026-11-05T08:30:00.001Z'),
            'started after it ended': variant(at='2026-11-06T00:00:00.000Z'),
            'revision without apply': variant(revisions=good['revisions'][:1]),
            'apply without entry': variant(saved=good['saved'][:1]),
            'line outside its apply': variant(lines=[line]),
            'curate that undoes': variant(undoes=RUN),
            'undo without a run': variant(kind='undo'),
            'text in a list': variant(saved=good['saved'] + ['Some text']),
            'unknown keep reason': variant(kept=[{'id': good['revisions'][0]['id'], 'by': '', 'why': 'because'}]),
            'turn range backwards': variant(turns={LOG: [9, 5]}),
            'float generation': variant(last=11.0),
        }
        for name, value in cases.items():
            with self.subTest(case=name), self.assertRaises((ValueError, TypeError, KeyError)):
                run_log.parse(json.dumps(value).encode())
        with self.assertRaises(ValueError):
            run_log.parse(run_log.log_bytes(good)[:-3])
        undo = logged(kind='undo', undoes='r_0123456789ab')
        self.assertEqual(run_log.parse(run_log.log_bytes(undo))['undoes'], 'r_0123456789ab')

    def test_line_entries_follow_the_publishers_operations(self):
        line = ident('s', '1')
        base = {'line': line, 'op': 'changed', 'generation': 9, 'history': [EPOCH, 9, line, 'a' * 64],
                'before': ['progress', 0, '', ''], 'after': ['progress', 0, '', '']}
        for op, before, after, history, ok in (
                ('added', [], ['next', 0, '', ''], None, True), ('removed', ['next', 0, '', ''], [], base['history'], True),
                ('undone', ['next', 0, '', ''], [], base['history'], True), ('added', ['next', 0, '', ''], ['next', 0, '', ''], None, False),
                ('changed', [], ['next', 0, '', ''], None, False), ('cut', ['next', 0, '', ''], ['next', 0, '', ''], None, False),
                ('changed', ['next', 0, ident('s', '2'), ''], ['next', 1, '', ''], [EPOCH, 8, line, 'a' * 64], False),
                ('changed', ['next', 0, '', ''], ['next', 1, '', ''], ['f' * 32, 9, line, 'a' * 64], False),
                ('changed', ['later', 0, '', ''], ['next', 1, '', ''], None, False)):
            entry = dict(base, op=op, before=before, after=after, history=history)
            value = run_log.start(RUN, 'curate', AT, DEVICE)
            effects = run_log.lines([dict(entry, history=None if history is None else tuple(history),
                                          before_revision=None, after_revision=9)])
            with self.subTest(op=op, before=before, after=after, history=history):
                if ok:
                    self.assertEqual(run_log.add(value, progress(9, {'line:' + line: 9, 'run:' + RUN: 9}), LATER,
                                                 effects)['lines'], [entry])
                else:
                    with self.assertRaises(ValueError):
                        run_log.add(value, progress(9, {'line:' + line: 9, 'run:' + RUN: 9}), LATER, effects)


class RunLogRetentionTest(unittest.TestCase):
    def setUp(self):
        self.fixture = edits_fixture.StateEditsTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.project = self.fixture.project
        self.folder = self.project / 'runs'
        self.folder.mkdir()

    def test_tc360_logs_past_retention_go_by_their_own_time_and_cannot_be_selected(self):
        when = '2026-11-07T12:00:00.000Z'
        old, kept, edge = 'r_0000000000a1', 'r_0000000000a2', 'r_0000000000a3'
        logs = {old: logged(old, ended='2026-07-29T12:00:00.000Z'),      # 101 days before
                kept: logged(kept, ended='2026-07-31T12:00:00.000Z'),     # 99 days before
                edge: logged(edge, ended='2026-07-30T12:00:00.000Z')}     # exactly 100 days: kept
        for run, log in logs.items():
            (self.folder / (run + '.json')).write_bytes(run_log.log_bytes(log))
        (self.folder / (old + '.json.bak')).write_bytes(b'{}')
        (self.folder / (old + '.json.a1b2c3d4.tmp')).write_bytes(b'{')
        damaged_old, damaged_new = 'r_0000000000b1', 'r_0000000000b2'
        for run in (damaged_old, damaged_new):
            (self.folder / (run + '.json')).write_bytes(b'{"id": ')
        stamp = time.mktime(time.strptime('2026-07-01', '%Y-%m-%d'))
        os.utime(str(self.folder / (damaged_old + '.json')), (stamp, stamp))
        (self.folder / 'notes.txt').write_bytes(b'kept')
        # Copies whose log is gone go by their own time; a fresh one and an old one beside a kept log stay.
        orphans = ['r_0000000000c1.json.bak', 'r_0000000000c1.json.e5f6a7b8.tmp', 'r_0000000000c2.json.bak',
                   kept + '.json.bak']
        for name in orphans:
            (self.folder / name).write_bytes(b'{')
        for name in orphans[:2] + orphans[3:]:
            os.utime(str(self.folder / name), (stamp, stamp))
        revisions = {'run:' + run: 9 for run in logs}
        revisions.update({'item:' + log['saved'][0]: 9 for log in logs.values()})
        current = progress(9, revisions)
        listed = run_log.listed(self.project, current, DEVICE, when=when, days=100)
        self.assertEqual(sorted(log['id'] for log in listed), [kept, edge])
        with self.fixture.held():
            removed = run_log.expire(self.fixture.memory, self.project, self.fixture.deadline, when=when, days=100)
        self.assertEqual(removed, 2)
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()),
                         sorted([kept + '.json', edge + '.json', damaged_new + '.json', 'notes.txt'] + orphans[2:]))
        self.assertIsNone(run_log.read(self.project, old))
        with self.fixture.held():
            self.assertEqual(run_log.expire(self.fixture.memory, self.project, self.fixture.deadline, when=when,
                                            days=100), 0)

    def test_a_project_without_run_logs_expires_and_lists_none(self):
        self.folder.rmdir()
        with self.fixture.held():
            self.assertEqual(run_log.expire(self.fixture.memory, self.project, self.fixture.deadline, when=LATER,
                                            days=100), 0)
        self.assertEqual(run_log.listed(self.project, progress(9, {}), DEVICE, when=LATER, days=100), [])
        self.assertFalse(self.folder.exists())

    def test_expiry_needs_the_layer_lease(self):
        with self.assertRaises(locks.LostLock):
            run_log.expire(self.fixture.memory, self.project, self.fixture.deadline, when=LATER, days=100)
        for days in (0, 3651, True, 1.5):
            with self.subTest(days=days), self.fixture.held(), self.assertRaises(ValueError):
                run_log.expire(self.fixture.memory, self.project, self.fixture.deadline, when=LATER, days=days)


if __name__ == '__main__':
    unittest.main()
