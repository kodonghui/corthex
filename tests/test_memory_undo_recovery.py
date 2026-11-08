"""TASK-108: an undo undone from its own log, and an inverse that stops (API-153; SPEC-145, SPEC-012).

TC-364 undoes the undo of a consolidation and of a curation: the first run's
statuses with their links, its pins, candidate transitions and lines come back
from the undo's own log and line history records, and a candidate that comes
back open keeps its showing count (TBL-010). The consolidation is undone again
after the older run's log and history records have expired (TC-386). A
candidate that a later run closed after the undo stays as that run left it.
TC-423 checks the store as the inverse leaves it before each of its writes,
and stops the inverse at five of them to show that a stop leaves just that.
The runner does not hand `undo` to the handler before the 0.3.0 activation, so
these tests call it as the runner will, after its gates, with the format-2
store binding.
"""
import contextlib
import copy
import sqlite3
import sys
import types
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import (clock, conflict_counts, conflict_types, format2, item_types, run_log, state_types,
                        undo_effects)
from test_memory_curator_answers import answer, change, quote
import test_memory_curation_worker as worker_fixture
from test_memory_state_edits import added, changed, edits, removal
from test_memory_undo import COUNTS, DEVICE, HOOKS, SAID, UndoStore
import test_memory_undo_effects as effects

# The first undo of TC-386, then the undo of an undo; retention then counts from EXPIRY.
STAMP = effects.STAMP
FIRST, AGAIN, EXPIRY = '2026-12-01T09:00:00.000Z', '2026-12-20T09:00:00.000Z', '2027-01-01T00:00:00.000Z'
# TC-423's undo takes this ID in place of a random one, so that its stops can be compared byte for byte.
RUN = 'r_' + 'd' * 12


class MergeUndoneAgainTest(effects.MergeStore, unittest.TestCase):
    """TC-364 and TC-386 on a consolidation that merged two items, moved a pin and settled a candidate."""

    def left(self, merge):
        """What the store holds of the merge's objects: statuses, pins, candidates, the line and the item list."""
        return {'statuses': {name: undo_effects._status(value) for name, value in self.items().items()},
                'pins': self.pins(), 'candidates': self.candidates(), 'listed': self.listed(),
                'line': {key: self.state()[merge.line['id']][key] for key in ('part', 'pos', 'text', 'cites')}}

    def test_tc364_tc386_an_undone_merge_undone_again_without_its_older_log_is_back_as_the_merge_left_it(self):
        merge = self.merged_run()
        left = self.left(merge)
        undo = self.undo(merge.run, stamp=FIRST)
        self.assertNotEqual(self.left(merge), left)
        # Retention passes the merge's own time but not the undo's: the merge's log goes, and so do the line
        # history records that it appended, which are older than the undo's.
        deadline = clock.now() + 30
        with self.memory.lease(self.root / 'layer.lock', 'layer', deadline):
            self.assertEqual(run_log.expire(self.memory, self.root, deadline, when=EXPIRY, days=40), 1)
        history = self.root / 'state-history.jsonl'
        rows = history.read_bytes().splitlines(keepends=True)
        history.write_bytes(b''.join(row for row in rows if b'"run":"' + merge.run.encode() + b'"' not in row))
        self.assertEqual([value['run'] for value in self.listing()], [undo])
        self.assertEqual({record['run'] for record in self.history()}, {undo})
        # Undo the undo: the merge's changes come back from the undo's own log and history records.
        preview = self.command(undo)
        self.assertEqual((preview['data']['changes'], preview['data']['kept']),
                         (dict(COUNTS, statuses=3, lines=1, pins=2, conflicts=1), []))
        again = self.undo(undo, stamp=AGAIN)
        # The statuses with their links, the pins at their places, the line and the item list are as the merge
        # left them; the candidate is closed again, now by this undo.
        self.assertEqual(self.left(merge), dict(left, candidates=[dict(left['candidates'][0], closed=AGAIN)]))
        merged = merge.merged['id']
        notice = item_types.parse_notice((self.root / 'notices' / ('pin-' + merged + '.json')).read_bytes())
        self.assertEqual(notice, {'at': AGAIN, 'kind': 'pin-restored', 'item': merged, 'run': again})
        log = run_log.read(self.root, again)
        self.assertEqual((log['undoes'], log['conflicts'], [(entry['line'], entry['op']) for entry in log['lines']]),
                         (undo, [{'candidate': merge.candidate['id'], 'from': 'open', 'to': 'settled'}],
                          [(merge.line['id'], 'undone')]))
        self.assertEqual(sorted((entry['item'], entry['before']['status'], entry['after']['status'])
                                for entry in log['statuses']),
                         sorted([(merge.first['id'], 'current', 'superseded'),
                                 (merge.second['id'], 'current', 'superseded'), (merged, 'undone', 'current')]))


class UndoneAgainTest(effects.Inverse, UndoStore, unittest.TestCase):
    """TC-364 on curations: a candidate that comes back open, its showing count, and a later closure."""

    def test_tc364_a_candidate_that_the_undo_settled_opens_again_and_keeps_its_showing_count(self):
        run, item, line = self.first_run()
        saved, original = self.fixture.items()[item], self.state()[line]
        self.curate('Send the raw logs to the server.', lambda said: answer(
            change(quote(said, 'Send the raw logs to the server'), kind='decision', title='Server logs',
                   conflicts=[item])))
        (candidate,) = self.candidates()
        deadline = clock.now() + 30
        self.assertEqual([conflict_counts.reserve(self.memory, self.root, candidate['id'], deadline)
                          for _ in range(2)], [1, 2])
        counts = (self.root / 'notices' / conflict_counts.NAME).read_bytes()
        undo = self.undo(run)
        self.assertEqual(self.candidates(), [dict(candidate, status='settled', closed=STAMP)])
        again = self.undo(undo, stamp=AGAIN)
        items = self.fixture.items()
        self.assertEqual(items[item], dict(saved, changed=AGAIN))
        restored = self.state()[line]
        self.assertEqual({key: restored[key] for key in ('id', 'part', 'pos', 'text', 'cites')},
                         {key: original[key] for key in ('id', 'part', 'pos', 'text', 'cites')})
        self.assertEqual(self.view(items), [line])
        # The candidate is open again as it was, and its two showings stay counted: it can be shown once more.
        self.assertEqual(self.candidates(), [candidate])
        self.assertEqual((self.root / 'notices' / conflict_counts.NAME).read_bytes(), counts)
        conflicts = conflict_types.parse_conflicts((self.root / 'layer/conflicts.json').read_bytes())
        # A deadline of its own: the two undos above can outlast the first one on a slow runner.
        self.assertEqual([value['id'] for value in conflict_counts.eligible(
            conflicts, conflict_counts.read(self.memory, self.root, clock.now() + 30))], [candidate['id']])
        self.assertEqual(run_log.read(self.root, again)['conflicts'],
                         [{'candidate': candidate['id'], 'from': 'settled', 'to': 'open'}])

    def test_a_candidate_that_a_later_run_closed_after_the_undo_stays_as_that_run_left_it(self):
        first = self.curate(SAID, lambda said: answer(
            change(quote(said, HOOKS), kind='decision', title='One script')))
        (item,) = run_log.read(self.root, first)['saved']
        later = self.curate('Send the raw logs to the server.', lambda said: answer(
            change(quote(said, 'Send the raw logs to the server'), kind='decision', title='Server logs',
                   conflicts=[item])))
        (other,) = run_log.read(self.root, later)['saved']
        (candidate,) = self.candidates()
        run = self.curate('Use two scripts for the hooks.', lambda said: answer(
            change(quote(said, 'Use two scripts'), action='replace', targets=[item], kind='decision',
                   title='Two scripts')))
        (replacement,) = run_log.read(self.root, run)['saved']
        self.assertEqual(self.candidates()[0]['status'], 'settled')
        undo = self.undo(run)
        self.assertEqual(self.candidates()[0]['status'], 'open')
        closing = self.curate('Keep the raw logs here after all.', lambda said: answer(
            change(quote(said, 'Keep the raw logs here after all'), action='replace', targets=[other],
                   kind='decision', title='Logs stay')))
        closed = self.candidates()
        self.assertEqual(closed[0]['status'], 'settled')
        again = self.undo(undo, stamp=AGAIN)
        items = self.fixture.items()
        self.assertEqual((items[item]['status'], items[item]['superseded_by'], items[replacement]['status']),
                         ('superseded', replacement, 'current'))
        self.assertEqual(self.candidates(), closed)
        self.assertEqual(run_log.read(self.root, again)['kept'],
                         [{'id': 'candidate:' + candidate['id'], 'by': closing, 'why': 'later-run'}])


class Stop(Exception):
    """A stop before one of the inverse's writes, as a crash, a full disk or a lost lease makes one."""


class StoppedInverseTest(effects.Inverse, UndoStore, unittest.TestCase):
    """TC-423: the inverse stopped before each of its writes."""
    forget = effects.UndoEffectsTest.forget

    def scenario(self):
        """A run that replaced a pinned decision that a candidate names, and removed, changed and added lines."""
        said, _ = self.fixture.one_turn(SAID, 'Noted.')
        first = self.fixture.saved(said, HOOKS)
        other = self.fixture.saved(said, 'keep the raw logs on this device')
        candidate = {'id': worker_fixture.ident('c'), 'items': [other['id'], first['id']], 'at': worker_fixture.AT,
                     'run': 'r_0123456789ab', 'by': 'curate', 'status': 'open'}
        done = dict(id='s_' + 'a' * 12, part='progress', pos=0, text='The hooks are written.', cites=[first['id']],
                    at=worker_fixture.AT, device=DEVICE)
        decided = dict(done, id='s_' + 'b' * 12, part='decisions', text='One script serves the hooks.')
        self.fixture.layer([first, other], lines=[done, decided], candidates=[candidate], pinned=[first['id']])
        (self.root / 'notices' / conflict_counts.NAME).write_bytes(conflict_counts.counts_bytes({candidate['id']: 2}))
        run = self.curate('Use two scripts for the hooks.', lambda said: answer(
            change(quote(said, 'Use two scripts'), action='replace', targets=[first['id']], kind='decision',
                   title='Two scripts'),
            state=edits(change=[changed(decided['id'], 'Two scripts serve the hooks.', changes=[1], why='Split.')],
                        add=[added('progress', 'The split is planned.', changes=[1])],
                        remove=[removal(done['id'], why='Done.')])))
        (replacement,) = run_log.read(self.root, run)['saved']
        (planned,) = set(self.state()) - {decided['id']}
        self.fixture.index()
        return types.SimpleNamespace(run=run, first=first['id'], replacement=replacement, candidate=candidate['id'],
                                     done=done['id'], decided=decided['id'], planned=planned)

    def files(self):
        """The project's files, without the lease files that a stop releases."""
        return {path.relative_to(self.root).as_posix(): path.read_bytes() for path in sorted(self.root.rglob('*'))
                if path.is_file() and path.suffix != '.lock'}

    def kept(self):
        """The project's files and the raw log's entries, to put back between stops."""
        return self.files(), copy.deepcopy(self.fixture.raw)

    def put_back(self, kept):
        files, raw = kept
        for path in sorted(self.root.rglob('*'), reverse=True):
            if path.is_file() and path.relative_to(self.root).as_posix() not in files:
                path.unlink()
        for name, data in files.items():
            path = self.root / name
            if not path.exists() or path.read_bytes() != data:
                path.write_bytes(data)
        self.fixture.raw = copy.deepcopy(raw)

    @contextlib.contextmanager
    def stopped(self, at=None, states=None):
        """The inverse's writes in order, by name; with `at`, Stop takes the place of that write.

        The undo takes RUN as its ID. `states` gets the project's files as each write found them.
        """
        writes, root = [], self.root

        def wrap(name, function):
            def call(*args, **kwargs):
                if len(writes) == at:
                    raise Stop()
                if states is not None:
                    states.append(self.files())
                writes.append(name(*args) if callable(name) else name)
                return function(*args, **kwargs)
            return call
        with mock.patch.object(undo_effects.curation_worker, '_run_id', return_value=RUN), \
                mock.patch.object(undo_effects.revision_io, 'reserve',
                               wrap('reserve', undo_effects.revision_io.reserve)), \
                mock.patch.object(undo_effects.history_io, 'append', wrap('history', undo_effects.history_io.append)), \
                mock.patch.object(undo_effects, '_publish', wrap(lambda memory, path, *rest: path.relative_to(
                    root).as_posix(), undo_effects._publish)), \
                mock.patch.object(undo_effects, '_index', wrap('index', undo_effects._index)), \
                mock.patch.object(undo_effects.run_log, 'write', wrap('log', undo_effects.run_log.write)), \
                mock.patch.object(undo_effects.revision_io, 'update_progress',
                                  wrap('attempt', undo_effects.revision_io.update_progress)):
            yield writes

    def lines(self, items):
        """The lines that the start summary and the requests show, by ID: (text, citations)."""
        state = state_types.parse_state((self.root / 'layer/state.json').read_bytes())
        removed = state_types.parse_removed((self.root / 'layer/state-removed.json').read_bytes())
        return {line['id']: (line['text'], tuple(line['cites']))
                for line in state_types.validity_view(state, removed, items, set())['lines']}

    def offered(self):
        """The items that the item list and the search index offer as current."""
        listed = {line.split('\t')[0] for line in self.listed().splitlines()}
        connection = sqlite3.connect(str(self.root / 'index.db'))
        try:
            indexed = {item for (item,) in connection.execute(
                "SELECT item FROM index_items WHERE status = 'current'")}
        finally:
            connection.close()
        return listed, indexed

    def whole(self):
        """Every file of the project reads whole, each as its own reader reads it."""
        root = self.root
        for path in (root / 'layer/items').glob('*.json'):
            item_types.parse_item(path.read_bytes())
        item_types.parse_pins((root / 'layer/pins.json').read_bytes())
        conflict_types.parse_conflicts((root / 'layer/conflicts.json').read_bytes())
        state_types.parse_state((root / 'layer/state.json').read_bytes())
        state_types.parse_removed((root / 'layer/state-removed.json').read_bytes())
        state_types.parse_history((root / 'state-history.jsonl').read_bytes())
        format2.parse_curation((root / 'curation.json').read_bytes())
        for path in (root / 'runs').glob('*.json'):
            run_log.parse(path.read_bytes())
        for path in (root / 'notices').glob('*.json'):
            if path.name == conflict_counts.NAME:
                conflict_counts.parse_counts(path.read_bytes())
            else:
                item_types.parse_notice(path.read_bytes())
        for line in self.listed().splitlines():
            self.assertEqual(len(line.split('\t')), 5)

    def left_safe(self, s, writes, stop, preview, fence):
        """The store before `writes[stop]`: whole files that readers can use, and an undo never applied twice."""
        self.whole()
        items = self.fixture.items()
        current = {name for name, value in items.items() if value['status'] == 'current'}
        # Never the replaced decision beside its replacement, and the item list and the search index never offer
        # an item whose own file is not current.
        self.assertFalse({s.first, s.replacement} <= current)
        for offered in self.offered():
            self.assertLessEqual(offered, current)
        # Each line shown is as it was before the undo or as the undo leaves it, and the line that the undo
        # removes is hidden from its first change of the layer on.
        lines = self.lines(items)
        for name, value in lines.items():
            self.assertIn(value, s.allowed[name])
        if stop > 2:
            self.assertNotIn(s.planned, lines)
        self.assertEqual(s.done in lines, stop > writes.index('layer/state-removed.json', 3))
        # The stopped undo is never applied twice: its reservation keeps every object of the run, and it has no
        # log, so it is not listed and nothing uses the line history records that it appended.
        runs = {key[len('run:'):] for key in self.fixture.progress()['fence']['revisions']
                if key.startswith('run:') and key not in fence}
        after = self.command(s.run)
        if stop == 0:
            self.assertEqual((runs, after['outcome'], after['data']), (set(), 'confirm', preview['data']))
        elif 'log' in writes[:stop]:
            # Only the attempt was left: the undo is whole, listed and can itself be undone.
            self.assertEqual((runs, after['outcome'], {(value['by'], value['why']) for value in after['data']['kept']}),
                             ({RUN}, 'nothing', {(RUN, 'later-run')}))
            self.assertIn(RUN, {value['run'] for value in self.listing()})
            self.assertEqual(self.command(RUN)['outcome'], 'confirm')
        else:
            self.assertEqual((runs, after['outcome']), ({RUN}, 'nothing'))
            self.assertEqual({value['why'] for value in after['data']['kept']}, {'later-unlogged-change'})
            self.assertNotIn(RUN, {value['run'] for value in self.listing()})
            self.assertEqual(self.command(RUN)['code'], 'run-not-found')
            self.assertEqual({record['run'] for record in self.history()} - {s.run}, {RUN} if stop > 1 else set())

    def test_tc423_a_stop_before_any_write_leaves_a_whole_safe_store_that_the_next_curation_uses(self):
        s = self.scenario()
        kept = self.kept()
        fence = self.fixture.progress()['fence']['revisions']
        before = self.lines(self.fixture.items())
        # The whole inverse, in order: what it hides, then what it shows, then the derived records and the log.
        preview = self.command(s.run)
        states = []
        with self.stopped(states=states) as writes:
            self.undo(s.run)
        self.assertEqual(writes, [
            'reserve', 'history', 'layer/state-removed.json', 'index', 'layer/item-list.txt',
            'layer/items/' + s.replacement + '.json', 'layer/items/' + s.first + '.json', 'layer/pins.json',
            'layer/conflicts.json', 'layer/state.json', 'layer/state-removed.json', 'layer/item-list.txt',
            'notices/pin-' + s.first + '.json', 'index', 'log', 'attempt'])
        items = self.fixture.items()
        after = self.lines(items)
        self.assertEqual(set(after), {s.done, s.decided})
        # The item list and the search index then offer just the current items, the decision among them.
        current = {name for name, value in items.items() if value['status'] == 'current'}
        self.assertIn(s.first, current)
        self.assertEqual(self.offered(), (current, current))
        s.allowed = {}
        for view in (before, after):
            for name, value in view.items():
                s.allowed.setdefault(name, set()).add(value)
        # What the store holds before each write is what a stop there leaves.
        for stop, state in enumerate(states):
            with self.subTest(stop=writes[stop]):
                self.put_back((state, kept[1]))
                self.left_safe(s, writes, stop, preview, fence)
        # A stop before any write, after the line history records, between hiding the replacement and showing
        # the decision, before the log and before the attempt: it leaves just what came before it, without leases.
        stops = [0, 2, writes.index('layer/items/' + s.first + '.json'), writes.index('log'), writes.index('attempt')]
        for stop in stops:
            with self.subTest(stopped=writes[stop]):
                self.put_back(kept)
                with self.stopped(stop) as done, self.at(), self.assertRaises(Stop):
                    self.command(s.run, code=preview['confirm'])
                self.assertEqual((done, self.memory.held), (writes[:stop], []))
                self.assertEqual(self.files(), states[stop])
                if stop == 2:
                    # The line history records that it appended go with a forget of the item that they cite.
                    appended = [record for record in self.history() if record['run'] == RUN]
                    self.assertEqual(sorted(record['line'] for record in appended), sorted([s.decided, s.planned]))
                    self.assertTrue(all(s.replacement in record['cites'] for record in appended))
                    self.forget(s.replacement)
                    history = self.history()
                    self.assertEqual([record for record in history if s.replacement in record['cites']], [])
                    self.assertFalse({'Two scripts serve the hooks.', 'The split is planned.'} &
                                     {record['text'] for record in history})
                elif 0 < stop < writes.index('attempt'):
                    # The next curation works on what the stop left and puts the derived records right.
                    self.curate('Record the release.', lambda said: answer(
                        change(quote(said, 'Record the release'), title='Release')))
                    items = self.fixture.items()
                    current = {name for name, value in items.items() if value['status'] == 'current'}
                    self.assertEqual(self.offered()[0], current)
                    self.assertTrue(all(set(value['items']) <= current for value in self.candidates()
                                        if value['status'] == 'open'))

if __name__ == '__main__':
    unittest.main()
