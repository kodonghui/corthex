"""TASK-107: the confirmed undo's inverse (API-153; SPEC-145, SPEC-012, SPEC-017, SPEC-034) on format-2 stores.

TC-369's yes, SPEC-145's first, second, third and fifth acceptance criteria and
SPEC-012's fifth. The runner does not hand `undo` to the handler before the
0.3.0 activation, so these tests call it as the runner will, after its gates,
with the format-2 store binding. The runs come from real curations and
consolidations against the local test server of the workers' tests; no provider
is called.
"""
import contextlib
import hashlib
import json
import sqlite3
import sys
import types
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

from _common import ROOT
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import (clock, commands, fence_plan, forget_command, format2, item_types, revision_io, run_log,
                        state_plan, state_types, undo_command, undo_effects, undo_plan)
from test_memory_curator_answers import answer, change, quote
import test_memory_consolidation_worker as merge_fixture
import test_memory_curation_worker as worker_fixture
from test_memory_state_edits import added, changed, edits, removal
from test_memory_undo import COUNTS, DEVICE, HOOKS, SAID, UndoStore

STAMP = '2026-11-08T10:00:00.000Z'


class Inverse:
    """What the undo leaves, read from the store."""

    @contextlib.contextmanager
    def at(self, stamp=STAMP):
        with mock.patch.object(undo_command.base, 'utc_time', return_value=stamp):
            yield

    def undo(self, run, stamp=STAMP):
        """The preview and the yes; the result of the yes."""
        preview = self.command(run)
        self.assertEqual((preview['outcome'], preview['code']), ('confirm', 'ok'))
        with self.at(stamp):
            done = self.command(run, code=preview['confirm'])
        self.assertEqual((done['outcome'], done['code'], done['say']), ('done', 'ok', undo_effects.SAY))
        self.assertEqual(done['data'], {'project': 'sample', 'run': run, 'undo': done['data']['undo'],
                                        'changes': preview['data']['changes'], 'kept': preview['data']['kept']})
        self.assertEqual(self.memory.held, [])
        return done['data']['undo']

    def state(self):
        return {line['id']: line for line in
                state_types.parse_state((self.root / 'layer/state.json').read_bytes())['lines']}

    def removed(self):
        return state_types.parse_removed((self.root / 'layer/state-removed.json').read_bytes())['removed']

    def history(self):
        return [record.value for record in
                state_types.parse_history((self.root / 'state-history.jsonl').read_bytes())]

    def pins(self):
        return item_types.parse_pins((self.root / 'layer/pins.json').read_bytes())['pins']

    def candidates(self):
        return item_types._document((self.root / 'layer/conflicts.json').read_bytes())['candidates']

    def listed(self):
        return (self.root / 'layer/item-list.txt').read_text(encoding='utf-8')

    def view(self, items):
        """The lines that the start summary and the requests show (TBL-013's validity view)."""
        state = state_types.parse_state((self.root / 'layer/state.json').read_bytes())
        removed = state_types.parse_removed((self.root / 'layer/state-removed.json').read_bytes())
        return [line['id'] for line in state_types.validity_view(state, removed, items, set())['lines']]

    def recorded(self, before, after):
        """The fence's generation for `after` and the revisions it moved from `before`."""
        return {key: value for key, value in after['fence']['revisions'].items()
                if before['fence']['revisions'].get(key) != value}


class UndoEffectsTest(Inverse, UndoStore, unittest.TestCase):
    # TC-369: the yes applies a new undo run

    def test_tc369_the_yes_applies_the_inverse_as_a_new_undo_run(self):
        run, item, line = self.first_run()
        saved, old = self.fixture.items()[item], self.state()[line]
        progress = self.fixture.progress()
        code = self.command(run)['confirm']
        undo = self.undo(run)
        self.assertNotEqual(undo, run)
        self.assertEqual(self.fixture.items()[item], dict(saved, status='undone', undone_by=undo, changed=STAMP))
        self.assertEqual((self.state(), self.removed()),
                         ({}, [{'id': line, 'at': STAMP, 'device': DEVICE, 'kind': 'edit'}]))
        # The line's text as the run left it goes to the line history first, for an undo of this undo.
        record = self.history()[-1]
        after = self.fixture.progress()
        generation = after['fence']['generation']
        self.assertEqual(record, {'at': STAMP, 'run': undo, 'epoch': after['fence']['epoch'],
                                  'generation': generation, 'line': line, 'part': old['part'], 'pos': old['pos'],
                                  'op': 'undone', 'text': old['text'], 'cites': old['cites'], 'why': '',
                                  'device': DEVICE})
        # One generation for each reversed object and the new run.
        self.assertEqual(generation, progress['fence']['generation'] + 1)
        self.assertEqual(self.recorded(progress, after), {'item:' + item: generation, 'line:' + line: generation,
                                                          'run:' + undo: generation})
        self.assertEqual(after['recent'][0], {'at': STAMP, 'kind': 'undo', 'result': 'ok', 'run': undo})
        self.assertEqual((after['logs'], after['applies']), (progress['logs'], progress['applies']))
        log = run_log.read(self.root, undo)
        place = state_plan._placements([old])[line]
        sha = hashlib.sha256(state_types.history_record_bytes(record)).hexdigest()
        self.assertEqual(log, dict(
            log, kind='undo', undoes=run, at=STAMP, ended=STAMP, device=DEVICE, turns={}, saved=[], merges=[],
            statuses=[{'item': item, 'before': {'status': 'current'}, 'after': {'status': 'undone', 'undone_by': undo}}],
            lines=[{'line': line, 'op': 'undone', 'generation': generation,
                    'history': [after['fence']['epoch'], generation, line, sha], 'before': list(place), 'after': []}],
            pins=[], conflicts=[], kept=[],
            applies=[{'generation': generation, 'at': STAMP, 'changes': sorted(['item:' + item, 'line:' + line])}]))
        self.assertNotIn(item, self.listed())
        # The undo is listed and can itself be undone; the run is not undoable any more.
        self.assertEqual({value['run']: value['undoable'] for value in self.listing()}, {undo: True, run: False})
        # A second yes with the same code changes nothing more: the run's changes are now the undo's.
        before = self.fixture.snapshot()
        again = self.command(run, code=code)
        self.assertEqual((again['outcome'], again['data']['kept']), ('nothing', [
            {'target': 'item:' + item, 'by': undo, 'why': 'later-run'},
            {'target': 'line:' + line, 'by': undo, 'why': 'later-run'}]))
        self.assertEqual(self.fixture.snapshot(), before)

    # SPEC-145's first acceptance criterion

    def test_a_replaced_decision_comes_back_and_its_line_gets_its_earlier_text(self):
        run, first, line = self.first_run()
        original = self.state()[line]
        second = self.curate('Use two scripts for the hooks.', lambda said: answer(
            change(quote(said, 'Use two scripts for the hooks'), action='replace', targets=[first], kind='decision',
                   title='Two scripts'),
            state=edits(change=[changed(line, 'Two scripts serve the hooks.', changes=[1], why='Split the script.')])))
        (replacement,) = run_log.read(self.root, second)['saved']
        self.assertEqual(self.fixture.items()[first]['superseded_by'], replacement)
        changed_line = self.state()[line]
        progress = self.fixture.progress()
        undo = self.undo(second)
        items = self.fixture.items()
        # The turns that the run curated stay processed.
        self.assertEqual((self.fixture.progress()['logs'], self.fixture.progress()['applies']),
                         (progress['logs'], progress['applies']))
        self.assertEqual((items[first]['status'], items[replacement]['status']), ('current', 'undone'))
        self.assertNotIn('superseded_by', items[first])
        self.assertEqual(items[replacement]['undone_by'], undo)
        # The line has its text, citations and place before the run, and keeps its ID.
        restored = self.state()[line]
        self.assertEqual({key: restored[key] for key in ('id', 'part', 'pos', 'text', 'cites')},
                         {key: original[key] for key in ('id', 'part', 'pos', 'text', 'cites')})
        self.assertEqual((restored['at'], restored['device']), (STAMP, DEVICE))
        self.assertEqual(self.removed(), [])
        # The text that the undo replaced is in the line history, as undone.
        self.assertEqual({key: self.history()[-1][key] for key in ('run', 'line', 'op', 'text', 'cites')},
                         {'run': undo, 'line': line, 'op': 'undone', 'text': changed_line['text'],
                          'cites': changed_line['cites']})
        # The replacement is never shown: the item list and the state that the summary shows leave it out.
        self.assertNotIn(replacement, self.listed())
        self.assertIn(first, self.listed())
        self.assertEqual(self.view(items), [line])
        log = run_log.read(self.root, undo)
        self.assertEqual(sorted((entry['item'], entry['before']['status'], entry['after']['status'])
                                for entry in log['statuses']),
                         sorted([(first, 'superseded', 'current'), (replacement, 'current', 'undone')]))
        self.assertEqual([(entry['line'], entry['op']) for entry in log['lines']], [(line, 'undone')])

    def test_a_line_that_the_run_removed_comes_back_with_its_id(self):
        run, item, line = self.first_run()
        original = self.state()[line]
        second = self.curate('Drop the hook line.', lambda said: answer(
            change(quote(said, 'Drop the hook line'), title='Dropped'),
            state=edits(remove=[removal(line, why='Not needed.')])))
        self.assertEqual((self.state(), [marker['id'] for marker in self.removed()]), ({}, [line]))
        undo = self.undo(second)
        restored = self.state()[line]
        self.assertEqual({key: restored[key] for key in ('id', 'part', 'pos', 'text', 'cites')},
                         {key: original[key] for key in ('id', 'part', 'pos', 'text', 'cites')})
        (marker,) = self.removed()
        self.assertEqual((marker['kind'], marker['restored_by'], marker['restored_at']), ('edit', undo, STAMP))
        self.assertEqual(self.view(self.fixture.items()), [line])
        (entry,) = run_log.read(self.root, undo)['lines']
        self.assertEqual((entry['op'], entry['history'], entry['before']), ('added', None, []))

    def test_a_line_that_the_run_moved_to_make_room_goes_back_to_its_place(self):
        said, _ = self.fixture.one_turn()
        fact = self.fixture.saved(said, HOOKS, kind='fact')
        # The second line has the smallest ID, so a line put after the first pushes it on by one place.
        first = dict(id='s_' + 'z' * 12, part='progress', pos=0, text='The hooks are written.', cites=[fact['id']],
                     at=worker_fixture.AT, device=DEVICE)
        second = dict(first, id='s_' + '0' * 12, pos=1, text='The tests pass.')
        self.fixture.layer([fact], lines=[first, second])
        run = self.curate('Record the release.', lambda said: answer(
            change(quote(said, 'Record the release'), title='Release'),
            state=edits(add=[added('progress', 'The release is recorded.', changes=[1], after=first['id'])])))
        (new,) = set(self.state()) - {first['id'], second['id']}
        self.assertEqual((self.state()[new]['pos'], self.state()[second['id']]['pos']), (1, 2))
        undo = self.undo(run)
        self.assertEqual(self.state(), {first['id']: first, second['id']: second})
        log = run_log.read(self.root, undo)
        self.assertEqual(sorted((entry['line'], entry['op'], entry['before'][:2], entry['after'][:2])
                                for entry in log['lines']),
                         sorted([(new, 'undone', ['progress', 1], []),
                                 (second['id'], 'undone', ['progress', 2], ['progress', 1])]))

    def test_an_open_candidate_that_names_an_item_that_stops_being_current_settles(self):
        run, item, _ = self.first_run()
        later = self.curate('Send the raw logs to the server.', lambda said: answer(
            change(quote(said, 'Send the raw logs to the server'), kind='decision', title='Server logs',
                   conflicts=[item])))
        (candidate,) = self.candidates()
        self.assertEqual((candidate['status'], candidate['run']), ('open', later))
        preview = self.command(run)
        self.assertEqual(preview['data']['changes'], dict(COUNTS, saved=1, lines=1, conflicts=1))
        undo = self.undo(run)
        self.assertEqual(self.candidates(), [dict(candidate, status='settled', closed=STAMP)])
        log = run_log.read(self.root, undo)
        self.assertEqual(log['conflicts'], [{'candidate': candidate['id'], 'from': 'open', 'to': 'settled'}])
        revisions = {entry['id']: entry['after'] for entry in log['revisions']}
        self.assertEqual(revisions['candidate:' + candidate['id']], log['last'])

    # SPEC-145's second and fifth acceptance criteria

    def test_tc362_an_item_that_a_later_run_replaced_stays_and_the_rest_is_undone(self):
        run = self.curate(SAID, lambda said: answer(
            change(quote(said, HOOKS), title='Hooks'),
            change(quote(said, 'keep the raw logs on this device'), title='Raw logs')))
        hooks, logs = run_log.read(self.root, run)['saved']
        later = self.curate('Use two scripts for the hooks.', lambda said: answer(
            change(quote(said, 'Use two scripts'), action='replace', targets=[hooks], title='Two scripts')))
        (replacement,) = run_log.read(self.root, later)['saved']
        undo = self.undo(run)
        items = self.fixture.items()
        self.assertEqual((items[hooks]['status'], items[hooks]['superseded_by']), ('superseded', replacement))
        self.assertEqual((items[logs]['status'], items[replacement]['status']), ('undone', 'current'))
        self.assertEqual(run_log.read(self.root, undo)['kept'],
                         [{'id': 'item:' + hooks, 'by': later, 'why': 'later-run'}])

    def forget(self, item):
        """The forget command (TASK-097, TASK-098), previewed and confirmed."""
        def command(code=None):
            context = commands.Context('forget', {'folder': str(self.root), 'item': item, 'with_items': []}, code,
                                       self.memory)
            context.project = types.SimpleNamespace(name='sample')
            context.record = {'device': DEVICE}
            return forget_command.forget(context)
        preview = command()
        self.assertEqual(command(preview['confirm'])['outcome'], 'done')

    def test_tc365_a_forgotten_item_and_its_line_stay_forgotten_and_the_rest_is_undone(self):
        secret = 'my spare locker phrase'
        run = self.curate('Keep the hooks in one script; ' + secret + ' stays apart.', lambda said: answer(
            change(quote(said, 'Keep the hooks in one script'), title='Hooks'),
            change(quote(said, secret), title='Locker'),
            state=edits(add=[added('progress', 'The hooks share one script.', changes=[1]),
                             added('blockers', 'The locker phrase stays apart.', changes=[2])])))
        hooks, locker = run_log.read(self.root, run)['saved']
        lines = {line['cites'][0]: line['id'] for line in self.state().values()}
        self.forget(locker)
        preview = self.command(run)
        self.assertEqual(preview['data']['kept'], [{'target': 'item:' + locker, 'by': '', 'why': 'forgotten'},
                                                   {'target': 'line:' + lines[locker], 'by': '', 'why': 'forgotten'}])
        undo = self.undo(run)
        items = self.fixture.items()
        self.assertEqual((items[hooks]['status'], set(items)), ('undone', {hooks}))
        self.assertTrue((self.root / 'layer/tombstones' / (locker + '.json')).exists())
        # Neither line is shown: the forgotten one stays behind its privacy marker, the other is undone.
        self.assertEqual(self.state(), {})
        self.assertEqual({marker['id']: marker['kind'] for marker in self.removed()},
                         {lines[locker]: 'privacy', lines[hooks]: 'edit'})
        # No word of the forgotten item comes back anywhere in the layer, the history or the run logs.
        found = [name for name, data in self.fixture.snapshot().items()
                 if not name.startswith('raw/') and secret.encode('utf-8') in data]
        self.assertEqual(found, [])
        self.assertEqual(run_log.read(self.root, undo)['kept'], [
            {'id': 'item:' + locker, 'by': '', 'why': 'forgotten'},
            {'id': 'line:' + lines[locker], 'by': '', 'why': 'forgotten'}])

    def test_tc381_an_item_changed_where_no_log_names_it_stays_and_the_rest_is_undone(self):
        run = self.curate(SAID, lambda said: answer(
            change(quote(said, HOOKS), title='Hooks'),
            change(quote(said, 'keep the raw logs on this device'), title='Raw logs')))
        hooks, logs = run_log.read(self.root, run)['saved']
        before = self.fixture.items()[hooks]
        self.touch('item:' + hooks)
        undo = self.undo(run)
        items = self.fixture.items()
        # Its record is byte for byte what the run left, yet its revision is not: it stays.
        self.assertEqual((items[hooks], items[logs]['status']), (before, 'undone'))
        self.assertEqual(run_log.read(self.root, undo)['kept'],
                         [{'id': 'item:' + hooks, 'by': '', 'why': 'later-unlogged-change'}])

    def test_tc383_an_item_that_a_later_line_cites_stays_with_its_group(self):
        run = self.curate(SAID, lambda said: answer(
            change(quote(said, HOOKS), kind='decision', title='Hooks'),
            change(quote(said, 'keep the raw logs on this device'), title='Raw logs')))
        hooks, logs = run_log.read(self.root, run)['saved']
        later = self.curate('Write the decision down.', lambda said: answer(
            change(quote(said, 'Write the decision down'), title='Written'),
            state=edits(add=[added('decisions', 'One script serves the hooks.', cites=[hooks])])))
        (line,) = self.state()
        undo = self.undo(run)
        items = self.fixture.items()
        self.assertEqual((items[hooks]['status'], items[logs]['status']), ('current', 'undone'))
        self.assertEqual(self.view(items), [line])
        self.assertEqual(run_log.read(self.root, undo)['kept'],
                         [{'id': 'item:' + hooks, 'by': later, 'why': 'later-dependent-change'}])

    def test_tc383_lines_that_a_later_line_was_put_after_stay_with_the_item_they_cite(self):
        run = self.curate(SAID, lambda said: answer(
            change(quote(said, HOOKS), title='Hooks'),
            change(quote(said, 'keep the raw logs on this device'), title='Raw logs'),
            state=edits(add=[added('progress', 'The hooks share one script.', changes=[1]),
                             added('progress', 'The script has its tests.', changes=[1])])))
        hooks, logs = run_log.read(self.root, run)['saved']
        first, second = sorted(self.state(), key=lambda name: self.state()[name]['pos'])
        later = self.curate('Record the release.', lambda said: answer(
            change(quote(said, 'Record the release'), title='Release'),
            state=edits(add=[added('progress', 'The release is recorded.', changes=[1], after=second)])))
        lines = self.state()
        undo = self.undo(run)
        items = self.fixture.items()
        self.assertEqual((items[hooks]['status'], items[logs]['status']), ('current', 'undone'))
        self.assertEqual(self.state(), lines)
        # The lines stay because the later line is placed after them; the item stays because they cite it.
        self.assertEqual(run_log.read(self.root, undo)['kept'], sorted([
            {'id': 'item:' + hooks, 'by': '', 'why': 'later-dependent-change'},
            {'id': 'line:' + first, 'by': later, 'why': 'later-dependent-change'},
            {'id': 'line:' + second, 'by': later, 'why': 'later-dependent-change'}], key=lambda entry: entry['id']))

    def test_tc392_a_line_whose_history_record_is_missing_stays_and_an_independent_item_is_undone(self):
        run, decision, line = self.first_run()
        second = self.curate('The script is hook.py now.', lambda said: answer(
            change(quote(said, 'The script is hook.py now'), title='Script name'),
            state=edits(change=[changed(line, 'One script, hook.py, serves the hooks.', [decision],
                                        why='Named the script.')])))
        (fact,) = run_log.read(self.root, second)['saved']
        reworded = self.state()[line]
        # Remove the one record of the line's version before the second run.
        history = self.root / 'state-history.jsonl'
        kept = [row for row in history.read_bytes().splitlines(keepends=True) if b'"run":"' + second.encode() not in row]
        history.write_bytes(b''.join(kept))
        undo = self.undo(second)
        self.assertEqual((self.fixture.items()[fact]['status'], self.state()[line]), ('undone', reworded))
        self.assertEqual(run_log.read(self.root, undo)['kept'],
                         [{'id': 'line:' + line, 'by': '', 'why': 'history-unavailable'}])

    def test_tc371_a_busy_curation_answers_lock_busy_and_the_retry_applies(self):
        run, item, _ = self.first_run()
        preview = self.command(run)
        before = self.fixture.snapshot()
        with self.held('curation.lock', 'curation'):
            busy = self.command(run, code=preview['confirm'])
        self.assertEqual((busy['outcome'], busy['code']), ('failed', 'lock-busy'))
        self.assertEqual(self.fixture.snapshot(), before)
        again = self.command(run)
        self.assertEqual(again['data'], preview['data'])
        with self.at():
            done = self.command(run, code=again['confirm'])
        self.assertEqual(done['outcome'], 'done')
        self.assertEqual(self.fixture.items()[item]['undone_by'], done['data']['undo'])

    # SPEC-012's fifth acceptance criterion

    def test_a_request_built_before_an_undo_is_stale_and_built_again(self):
        run, item, _ = self.first_run()
        said, _ = self.fixture.one_turn('Name the script hook.py.', 'The script is hook.py now.')

        def undo_meanwhile():
            # In operation the undo waits for the curation lease, so it meets a waiting request only after
            # that curator's lease was taken over; here it borrows the curator's lease to come in between.
            deadline = clock.now() + 30
            with self.memory.lease(self.root / 'layer.lock', 'layer', deadline):
                snap, plan = self.plan(run, deadline)
                undo_effects.apply(self.memory, self.root, plan, snap, deadline, at=STAMP)
        # The server numbers every request of the store's life; the first run's request was the first.
        server = self.fixture.server
        number = len(server.requests)
        server.before[number] = undo_meanwhile
        server.answers = [None] * number + [
            answer(change(quote(said, 'Name the script hook.py'), title='Built before')),
            answer(change(quote(said, 'Name the script hook.py'), title='Built again'))]
        outcome = self.fixture.curate()
        self.assertEqual([attempt.record['result'] for attempt in outcome.attempts], ['stale', 'ok'])
        titles = sorted(value['title'] for value in self.fixture.items().values())
        self.assertEqual(titles, ['Built again', 'One script'])
        self.assertEqual(self.fixture.items()[item]['status'], 'undone')

    def plan(self, run, deadline):
        read = undo_command.run_listing._reader(self.memory, deadline)
        progress = revision_io.read(self.memory, self.root, deadline)
        log, sha256 = undo_command._log(self.root, run, read)
        snap = undo_command.snapshot(self.memory, self.root, deadline, read, log, sha256, progress)
        return snap, undo_plan.plan('sample', run, snap)

    # Derived records

    def test_the_search_index_rows_take_the_new_statuses(self):
        run, item, _ = self.first_run()
        self.fixture.index()
        undo = self.undo(run)
        self.assertEqual(self.rows(), [(item, 'undone')])
        # Undone again, the item is current again and so is its row.
        self.undo(undo, stamp='2026-11-08T11:00:00.000Z')
        self.assertEqual(self.rows(), [(item, 'current')])

    def rows(self):
        connection = sqlite3.connect(str(self.root / 'index.db'))
        try:
            return connection.execute('SELECT item, status FROM index_items').fetchall()
        finally:
            connection.close()

    def test_an_undo_can_be_undone_from_its_own_log_and_puts_the_run_back(self):
        run, item, line = self.first_run()
        saved, original = self.fixture.items()[item], self.state()[line]
        undo = self.undo(run)
        preview = self.command(undo)
        self.assertEqual((preview['data']['changes'], preview['data']['kept']),
                         (dict(COUNTS, statuses=1, lines=1), []))
        again = self.undo(undo, stamp='2026-11-08T11:00:00.000Z')
        items = self.fixture.items()
        self.assertEqual(items[item], dict(saved, changed='2026-11-08T11:00:00.000Z'))
        restored = self.state()[line]
        self.assertEqual({key: restored[key] for key in ('id', 'part', 'pos', 'text', 'cites')},
                         {key: original[key] for key in ('id', 'part', 'pos', 'text', 'cites')})
        self.assertEqual(self.view(items), [line])
        log = run_log.read(self.root, again)
        self.assertEqual((log['undoes'], [(entry['line'], entry['op']) for entry in log['lines']]),
                         (undo, [(line, 'added')]))

    # Failures

    def test_an_inverse_that_no_longer_fits_the_store_stops_before_it_reserves(self):
        run, item, _ = self.first_run()
        deadline = clock.now() + 60

        @contextlib.contextmanager
        def leases():
            with self.memory.lease(self.root / 'curation.lock', 'curation', deadline):
                with self.memory.lease(self.root / 'layer.lock', 'layer', deadline):
                    yield
        with leases():
            snap, plan = self.plan(run, deadline)
        before = self.fixture.snapshot()
        # A plan that names an object which its inverse would not change.
        wrong = undo_plan.Plan(plan.data, plan.reversed | {'item:i_' + '0' * 12}, plan.items, plan.pins, plan.lines,
                               plan.candidates, plan.settles)
        with leases(), self.assertRaises(ValueError):
            undo_effects.apply(self.memory, self.root, wrong, snap, deadline, at=STAMP)
        self.assertEqual(self.fixture.snapshot(), before)
        # One of its items made private since, as a tombstone makes it.
        with leases(), mock.patch.object(undo_effects.item_io, '_private', side_effect=lambda memory, root, name:
                                         name == item), self.assertRaises(fence_plan.Stale):
            undo_effects.apply(self.memory, self.root, plan, snap, deadline, at=STAMP)
        self.assertEqual(self.fixture.snapshot(), before)
        # A fence that moved since the plan was read, as every later write moves it.
        self.touch('item:i_' + '0' * 12)
        moved = self.fixture.snapshot()
        with leases(), self.assertRaises(fence_plan.Stale):
            undo_effects.apply(self.memory, self.root, plan, snap, deadline, at=STAMP)
        self.assertEqual((self.fixture.snapshot(), self.memory.held), (moved, []))

    def test_a_file_that_does_not_read_back_stops_the_inverse_there(self):
        run, item, _ = self.first_run()
        preview = self.command(run)
        before = self.fixture.snapshot()
        read, reads = undo_effects.files._retry, []

        def misread(function, deadline):
            # The first file that the inverse reads back, the line's removal marker, reads back other than written.
            reads.append(function)
            data = read(function, deadline)
            return b'' if len(reads) == 1 else data
        with mock.patch.object(undo_effects, 'files', mock.Mock(wraps=undo_effects.files, _retry=misread)), \
                self.at(), self.assertRaises(undo_effects.Unverified):
            self.command(run, code=preview['confirm'])
        after = self.fixture.snapshot()
        # The fence moved and the line's text went to the line history; the marker was written and read back
        # wrong, so nothing after it was written: the line is hidden and the item is still current.
        self.assertEqual({name for name in after if after[name] != before.get(name)},
                         {'curation.json', 'state-history.jsonl', 'layer/state-removed.json'})
        self.assertEqual(self.fixture.items()[item]['status'], 'current')
        self.assertEqual(self.view(self.fixture.items()), [])

    def test_the_done_example_answers_as_the_yes_does(self):
        valid = json.loads((ROOT / 'docs/06-api/memory-examples.json').read_text(encoding='utf-8'))['result']['valid']
        done = valid['undo-done']
        self.assertEqual((done['outcome'], done['code'], done['say']), ('done', 'ok', undo_effects.SAY))
        self.assertEqual(sorted(done['data']), ['changes', 'kept', 'project', 'run', 'undo'])

    def test_an_inverse_that_fails_reports_no_success_and_only_the_fence_has_moved(self):
        run, item, line = self.first_run()
        preview = self.command(run)
        before = self.fixture.snapshot()
        progress = self.fixture.progress()
        with mock.patch.object(undo_effects.history_io, 'append', side_effect=OSError('disk full')):
            with self.at(), self.assertRaises(OSError):
                self.command(run, code=preview['confirm'])
        after = self.fixture.snapshot()
        self.assertEqual({name for name in after if after[name] != before.get(name)}, {'curation.json'})
        self.assertEqual(self.fixture.progress()['fence']['generation'], progress['fence']['generation'] + 1)
        # The reservation stays, as every reservation does (TBL-009): the earlier code applies nothing, and the
        # run's objects now have revisions that no log names, so a stopped inverse is never applied twice.
        again = self.command(run, code=preview['confirm'])
        self.assertEqual((again['outcome'], again['data']['kept']), ('nothing', [
            {'target': 'item:' + item, 'by': '', 'why': 'later-unlogged-change'},
            {'target': 'line:' + line, 'by': '', 'why': 'later-unlogged-change'}]))
        self.assertEqual((self.fixture.snapshot(), self.memory.held), (after, []))


class MergeStore(Inverse):
    """A consolidation that merges two items, moving a pin, settling a candidate and changing a line twice."""
    setUp = merge_fixture.ConsolidationWorkerTest.setUp
    configure = merge_fixture.ConsolidationWorkerTest.configure
    layer = merge_fixture.ConsolidationWorkerTest.layer
    write = merge_fixture.ConsolidationWorkerTest.write
    saved = merge_fixture.ConsolidationWorkerTest.saved
    items = merge_fixture.ConsolidationWorkerTest.items
    item = merge_fixture.ConsolidationWorkerTest.item
    answering = merge_fixture.ConsolidationWorkerTest.answering
    consolidate = merge_fixture.ConsolidationWorkerTest.consolidate
    new_items = merge_fixture.ConsolidationWorkerTest.new_items
    command = UndoStore.command
    listing = UndoStore.listing

    @property
    def fixture(self):
        return self

    def snapshot(self):
        return worker_fixture.CurationWorkerTest.snapshot(self)

    def progress(self):
        return format2.parse_curation((self.root / 'curation.json').read_bytes())

    def merged_run(self):
        """The merge's run, its items and candidate, and the line and pins as they were before it."""
        first = self.item('decision', 'Keep raw logs on the device')
        second = self.item('decision', 'Raw logs stay on this device', saved=merge_fixture.LATER)
        other = self.item('decision', 'Send raw logs to the server', saved=merge_fixture.LATER)
        candidate = {'id': merge_fixture.ident('c'), 'items': [other['id'], first['id']], 'at': worker_fixture.AT,
                     'run': 'r_0123456789ab', 'by': 'curate', 'status': 'open'}
        line = merge_fixture.row('decisions', 0, 'Raw logs stay on the device.', [first])
        self.layer([first, second, other], lines=[line], candidates=[candidate], pinned=[first['id']])
        pins = self.pins()
        # The merge cites the merged item in the line; the last answer then rewords it: two versions in one run.
        groups = merge_fixture.merges(merge_fixture.merge([first, second], [(first, 1), (second, 1)],
                                                          title='Raw logs'))

        def reply(number, body):
            if ET.fromstring(body['messages'][0]['content']).get('kind') == 'merge':
                return groups
            (made,) = self.new_items(first, second, other)
            return merge_fixture.shorter(decisions=[merge_fixture.keeps(
                line, text='Raw logs never leave the device.', cites=[made])])
        self.server.reply = reply
        self.assertEqual(self.consolidate().reason, 'done')
        (merged,) = self.new_items(first, second, other)
        self.assertEqual({key: self.state()[line['id']][key] for key in ('text', 'cites')},
                         {'text': 'Raw logs never leave the device.', 'cites': [merged['id']]})
        run = self.progress()['recent'][0]['run']
        self.assertEqual(sorted(entry['op'] for entry in run_log.read(self.root, run)['lines']),
                         ['changed', 'recited'])
        return types.SimpleNamespace(run=run, first=first, second=second, other=other, merged=merged,
                                     candidate=candidate, line=line, pins=pins)


class UndoMergeTest(MergeStore, unittest.TestCase):
    """SPEC-145's third acceptance criterion, with a pin and a candidate that the merge moved."""

    def test_a_merge_undone_makes_both_items_current_and_moves_the_pin_and_candidate_back(self):
        merge = self.merged_run()
        run, first, second, merged = merge.run, merge.first, merge.second, merge.merged
        candidate, line, pins = merge.candidate, merge.line, merge.pins
        preview = self.command(run)
        self.assertEqual(preview['data']['changes'], dict(COUNTS, saved=1, statuses=2, merges=1, lines=1, pins=2,
                                                          conflicts=1))
        undo = self.undo(run)
        # The line has its version before the run, never the one between the two applies.
        self.assertEqual({key: self.state()[line['id']][key] for key in ('part', 'pos', 'text', 'cites')},
                         {key: line[key] for key in ('part', 'pos', 'text', 'cites')})
        items = self.items()
        self.assertEqual({name: items[name]['status'] for name in (first['id'], second['id'], merged['id'])},
                         {first['id']: 'current', second['id']: 'current', merged['id']: 'undone'})
        self.assertEqual(items[merged['id']]['merges'], [first['id'], second['id']])
        self.assertEqual(self.pins(), pins)
        self.assertEqual(self.candidates(), [candidate])
        notice = item_types.parse_notice((self.root / 'notices' / ('pin-' + first['id'] + '.json')).read_bytes())
        self.assertEqual(notice, {'at': STAMP, 'kind': 'pin-restored', 'item': first['id'], 'run': undo})
        self.assertFalse((self.root / 'notices' / ('pin-' + merged['id'] + '.json')).exists())
        listed = self.listed()
        self.assertNotIn(merged['id'], listed)
        self.assertIn(first['id'], listed)
        log = run_log.read(self.root, undo)
        self.assertEqual(log['conflicts'], [{'candidate': candidate['id'], 'from': 'settled', 'to': 'open'}])
        self.assertEqual(sorted((entry['item'], entry['from'], entry['to'], entry['place']) for entry in log['pins']),
                         sorted([(first['id'], {'on': False, 'at': merge_fixture.STAMP, 'device': DEVICE},
                                  {'on': True, 'at': worker_fixture.AT, 'device': DEVICE}, [0, 0]),
                                 (merged['id'], {'on': True, 'at': merge_fixture.STAMP, 'device': DEVICE},
                                  None, [1, None])]))


if __name__ == '__main__':
    unittest.main()
