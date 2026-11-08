"""TASK-070: the conflicts command (API-151; SPEC-143) on format-2 stores, and the candidates that settle without it.

TC-351, TC-352, TC-354 and TC-355. The runner does not accept `conflicts`
before the 0.3.0 activation, so these tests call the handler as the runner
will, after its gates, with the format-2 store binding. The runs come from real
curations against the local test server of the curation worker's tests, and the
forget and the undo are the commands' own, confirmed with their codes; no
provider is called. The start summary is the module that the session start
hook will call (TASK-091).
"""
import json
import os
import secrets
import sys
import types
import unittest
from datetime import timezone
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import (clock, commands, conflict_counts, conflicts_command, fence_plan, files, item_types,
                        run_listing, run_log, start_summary, worker_support)
from test_memory_curator_answers import answer, change, quote
import test_memory_curation_worker as worker_fixture
import test_memory_forget as forget_fixture
import test_memory_start_summary as start_fixture
import test_memory_undo as undo_fixture
import test_memory_undo_effects as inverse_fixture

AT, DEVICE, WHEN, STAMP = worker_fixture.AT, worker_fixture.DEVICE, worker_fixture.WHEN, worker_fixture.STAMP
LATER = '2026-11-05T03:00:00.000Z'
DISMISSED = '2026-11-08T11:00:00.000Z'
RUN = 'r_0123456789ab'
SAID = 'Keep the four hooks in one script, and keep the raw logs on this device.'
REPLY = 'One script now serves the four hooks, and the raw logs stay here.'


def ident(prefix, number):
    return '%s_%012d' % (prefix, number)


def candidate(number, newer, older, at=AT, status='open'):
    value = dict(id=ident('c', number), items=[newer['id'], older['id']], at=at, run=RUN, by='curate',
                 status=status)
    if status != 'open':
        value['closed'] = LATER
    return value


class ConflictsStore:
    """A format-2 project with one recorded turn, and the conflicts command run as the runner will run it."""
    curate = undo_fixture.UndoStore.curate
    undo_command = undo_fixture.UndoStore.command
    held = undo_fixture.UndoStore.held
    forget_command = forget_fixture.ForgetStore.command
    undo = inverse_fixture.Inverse.undo
    at = inverse_fixture.Inverse.at

    def setUp(self):
        remote = mock.patch.dict(os.environ, {'CLAUDE_CODE_REMOTE': ''})
        remote.start()
        self.addCleanup(remote.stop)
        self.fixture = worker_fixture.CurationWorkerTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.memory = self.fixture.root, self.fixture.memory
        self.said, self.answered = self.fixture.one_turn(SAID, REPLY)
        self.environment = {name: 'memory-key-' + secrets.token_hex(12) for name in (
            'CORTHEX_MEMORY_ANTHROPIC_API_KEY', 'CORTHEX_MEMORY_OPENAI_API_KEY')}

    # The store

    def item(self, title, words='the four hooks', kind='decision', source=None, **fields):
        value = self.fixture.saved(source or self.said, words, kind=kind)
        value.update(title=title, text=title + '.', **fields)
        return value

    def candidates(self):
        return item_types._document((self.root / 'layer/conflicts.json').read_bytes())['candidates']

    def counts(self):
        path = self.root / 'notices' / conflict_counts.NAME
        return json.loads(path.read_bytes())['counts'] if path.exists() else None

    def tree(self):
        """Every file of the memory store but the lock files, as bytes."""
        return {path.relative_to(self.fixture.folder).as_posix(): path.read_bytes()
                for path in sorted(self.fixture.folder.rglob('*')) if path.is_file() and path.suffix != '.lock'}

    def link(self, alias, target):
        """A symbolic link, or False where this system does not let the test make one."""
        try:
            os.symlink(str(target), str(alias))
        except (OSError, NotImplementedError):
            return False
        return True

    def line(self, value, *items):
        """The conflict line (data-conflicts) of a candidate with its two items' records."""
        return {'candidate': value['id'], 'items': [run_listing.list_line(item) for item in items], 'at': value['at']}

    def pair(self):
        """Two curations: a decision, then a later one that the curator says may disagree with it."""
        first = self.curate('Keep the logs for 30 days.', lambda said: answer(change(
            quote(said, 'Keep the logs for 30 days'), kind='decision', title='Logs for 30 days')))
        (older,) = run_log.read(self.root, first)['saved']
        second = self.curate('Keep the logs for 90 days.', lambda said: answer(change(
            quote(said, 'Keep the logs for 90 days'), kind='decision', title='Logs for 90 days', conflicts=[older])))
        (newer,) = run_log.read(self.root, second)['saved']
        (value,) = self.candidates()
        # The newer item comes first by the time it was saved, then by ID; both runs here save at one time.
        self.assertEqual((value['items'], value['status'], value['run']), (sorted([newer, older]), 'open', second))
        self.assertEqual(self.counts(), {value['id']: 0})
        return (first, second), value, newer, older

    # Running

    def conflicts(self, dismiss=None, *, project='sample', arguments=None, memory=None):
        if arguments is None:
            arguments = {'folder': str(self.root)}
            if dismiss is not None:
                arguments['dismiss'] = dismiss
        context = commands.Context('conflicts', arguments, None, memory or self.memory)
        context.project = types.SimpleNamespace(name=project)
        context.record = {'device': DEVICE}
        value = conflicts_command.conflicts(context, at=DISMISSED)
        commands.validate_result(value, 'conflicts')
        return value

    def start(self):
        """A session start's conflict notices and the candidate it reserved a showing of, then its step 7."""
        settings = self.memory.configuration(deadline=clock.now() + 10)
        part = start_summary.compose(self.memory, 'sample', start_fixture.BASE, clock.now() + 5, settings=settings,
                                     environment=self.environment, now=WHEN, zone=timezone.utc)
        self.assertEqual(part.outcome, 'ok')
        start_summary.after(self.memory, 'sample', part, 'claude-code', start_fixture.SESSION, when=WHEN)
        return [row for row in part.text.splitlines() if 'may disagree' in row], part.reserved

    def forget(self, item):
        """The forget command's preview, then its yes; the result of the yes."""
        preview = self.forget_command(item)
        self.assertEqual((preview['outcome'], preview['code']), ('confirm', 'ok'))
        done = self.forget_command(item, code=preview['confirm'])
        self.assertEqual((done['outcome'], done['code']), ('done', 'ok'))
        return preview, done

    command = undo_command


class ConflictsTest(ConflictsStore, unittest.TestCase):
    # TC-354

    def test_tc354_with_no_open_candidate_the_list_is_empty_and_nothing_changes(self):
        newer, older, other = self.item('Newer'), self.item('Older'), self.item('Other')
        self.fixture.layer(items=[newer, older, other], candidates=[
            candidate(1, newer, older, status='settled'), candidate(2, other, older, status='dismissed')])
        before = self.tree()
        value = self.conflicts()
        self.assertEqual((value['outcome'], value['code'], value['say']),
                         ('nothing', 'ok', conflicts_command.SAY['none']))
        self.assertEqual(value['data'], {'project': 'sample', 'open': []})
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.memory.held, [])

    def test_a_project_without_a_folder_or_candidates_or_being_deleted_has_none(self):
        newer, older = self.item('Newer'), self.item('Older')
        value = candidate(1, newer, older)
        self.fixture.layer(items=[newer, older], candidates=[value])
        nothing = ('nothing', 'ok', conflicts_command.SAY['none'])
        refused = ('refused', 'conflict-not-found', conflicts_command.SAY['missing'])
        for name, path in (('no folder', None), ('no candidates file', 'layer/conflicts.json'),
                           ('being deleted', 'layer/deleted.json')):
            with self.subTest(name):
                project = 'missing' if path is None else 'sample'
                if path == 'layer/conflicts.json':
                    (self.root / path).unlink()
                elif path is not None:
                    # A deletion that stopped may have left any file of the layer: none is read.
                    (self.root / 'layer/conflicts.json').write_bytes(b'{"candidates": [')
                    (self.root / path).write_bytes(b'{}\n')
                before = self.tree()
                listing, dismissal = self.conflicts(project=project), self.conflicts(value['id'], project=project)
                self.assertEqual((listing['outcome'], listing['code'], listing['say']), nothing)
                self.assertEqual(listing['data'], {'project': project, 'open': []})
                self.assertEqual((dismissal['outcome'], dismissal['code'], dismissal['say']), refused)
                self.assertEqual(dismissal['data'], {'project': project, 'open': [], 'candidate': value['id']})
                self.assertEqual(self.tree(), before)

    def test_a_candidates_file_that_cannot_be_read_is_an_error_and_restores_nothing(self):
        newer, older = self.item('Newer'), self.item('Older')
        self.fixture.layer(items=[newer, older], candidates=[candidate(1, newer, older)])
        path = self.root / 'layer/conflicts.json'
        backup = path.with_name(path.name + '.bak')
        backup.write_bytes(path.read_bytes())
        for name, damage, error in (('damaged with a backup', b'{"candidates": [', files.RestoreNeeded),
                                    ('missing with a backup', None, files.RestoreNeeded),
                                    ('damaged', b'{"candidates": [', ValueError)):
            with self.subTest(name):
                if name == 'damaged':
                    backup.unlink()
                if damage is None:
                    path.unlink()
                else:
                    path.write_bytes(damage)
                before = self.tree()
                for dismiss in (None, ident('c', 1)):
                    with self.assertRaises(error):
                        self.conflicts(dismiss)
                self.assertEqual(self.tree(), before)
                self.assertEqual(self.memory.held, [])
        outside = self.fixture.folder.parent / 'conflicts.json'
        outside.write_bytes(item_types._raw({'candidates': [candidate(1, newer, older)]}))
        path.unlink()
        if self.link(path, outside):
            before = self.tree()
            for dismiss in (None, ident('c', 1)):
                with self.assertRaises(worker_support.UnsafePath):
                    self.conflicts(dismiss)
            self.assertEqual((self.tree(), outside.read_bytes()),
                             (before, item_types._raw({'candidates': [candidate(1, newer, older)]})))

    # The list

    def test_open_candidates_are_listed_oldest_first_with_both_items_as_the_item_list_shows_them(self):
        first, second = self.item('First decision'), self.item('Second fact', kind='fact')
        third = self.item('Third, from the reply', words='the raw logs stay here', source=self.answered)
        fourth = self.item('Fourth preference', kind='preference')
        withdrawn, forgotten = self.item('Withdrawn', status='withdrawn'), self.item('Forgotten')
        damaged, renamed = self.item('Damaged'), self.item('Named for another item')
        missing, linked = self.item('Missing'), self.item('Reached through a link')
        latest = candidate(1, first, second, at=LATER)
        tied = [candidate(3, third, fourth), candidate(2, second, third)]
        left_out = [candidate(4, first, withdrawn), candidate(5, first, forgotten), candidate(6, second, damaged),
                    candidate(7, third, renamed), candidate(8, fourth, missing), candidate(10, second, linked),
                    candidate(9, first, fourth, status='settled')]
        self.fixture.layer(items=[first, second, third, fourth, withdrawn, forgotten, damaged, renamed, linked],
                           candidates=[latest] + tied + left_out)
        record = self.root / 'layer/items' / (linked['id'] + '.json')
        outside = self.fixture.folder.parent / record.name
        outside.write_bytes(record.read_bytes())
        record.unlink()
        if not self.link(record, outside):
            record.write_bytes(b'')  # a record that cannot be read is left out the same way
        forget_fixture.ForgetStore.tombstone(self, forgotten)
        (self.root / 'layer/items' / (damaged['id'] + '.json')).write_bytes(b'{"id": ')
        (self.root / 'layer/items' / (renamed['id'] + '.json')).write_bytes(
            item_types.item_bytes(dict(renamed, id=missing['id'])))
        (self.root / 'notices' / conflict_counts.NAME).write_bytes(conflict_counts.counts_bytes(
            {value['id']: 3 for value in [latest] + tied}))
        before = self.tree()
        value = self.conflicts()
        self.assertEqual((value['outcome'], value['code'], value['say']),
                         ('done', 'ok', conflicts_command.SAY['some'] % 3))
        self.assertEqual(value['data'], {'project': 'sample', 'open': [
            self.line(tied[1], second, third), self.line(tied[0], third, fourth), self.line(latest, first, second)]})
        self.assertEqual(value['data']['open'][0]['items'][1], {
            'item': third['id'], 'kind': 'decision', 'speaker': 'agent', 'date': AT[:10],
            'title': 'Third, from the reply'})
        # Listing shows no notice, so no showing is counted and nothing else changes.
        self.assertEqual(self.tree(), before)

    def test_one_open_candidate_says_so(self):
        newer, older = self.item('Newer'), self.item('Older')
        value = candidate(1, newer, older)
        self.fixture.layer(items=[newer, older], candidates=[value])
        listing = self.conflicts()
        self.assertEqual((listing['outcome'], listing['code'], listing['say']),
                         ('done', 'ok', conflicts_command.SAY['one']))
        self.assertEqual(listing['data']['open'], [self.line(value, newer, older)])

    # TC-352

    def test_tc352_a_dismissal_closes_only_its_candidate_and_leaves_both_items_alone(self):
        newer, older = self.item('Logs stay 90 days'), self.item('Logs stay 30 days')
        first, second = self.item('One script'), self.item('Two scripts')
        dismissed, kept = candidate(1, newer, older), candidate(2, first, second, at=LATER)
        self.fixture.layer(items=[newer, older, first, second], candidates=[dismissed, kept],
                           lines=[start_fixture.line('decisions', 1, 'Logs stay 90 days.', [newer['id']])],
                           pinned=[older['id']])
        (self.root / 'notices' / conflict_counts.NAME).write_bytes(conflict_counts.counts_bytes(
            {dismissed['id']: 0, kept['id']: 3}))
        before, progress = self.tree(), self.fixture.progress()
        value = self.conflicts(dismissed['id'])
        self.assertEqual((value['outcome'], value['code'], value['say']),
                         ('done', 'ok', conflicts_command.SAY['dismissed']))
        self.assertEqual(value['data'], {'project': 'sample', 'open': [self.line(kept, first, second)],
                                         'dismissed': dismissed['id']})
        self.assertEqual(self.candidates(), [dict(dismissed, status='dismissed', closed=DISMISSED), kept])
        after = self.tree()
        # Only the candidates and the curation record's fence changed: no item, pin, line, list, run or count.
        self.assertEqual(sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name)),
                         ['projects/sample/curation.json', 'projects/sample/layer/conflicts.json'])
        fence = self.fixture.progress()['fence']
        self.assertEqual(fence['generation'], progress['fence']['generation'] + 1)
        self.assertEqual(fence['revisions'], dict(progress['fence']['revisions'],
                                                  **{'candidate:' + dismissed['id']: fence['generation']}))
        # A curator request, a confirmation or an undo planned before it goes stale.
        self.assertFalse(fence_plan.matches(self.fixture.progress(), fence_plan.snapshot(progress)))
        self.assertEqual(self.memory.held, [])
        # The next start names no candidate, the list holds the other one, and the dismissal is not repeated.
        self.assertEqual(self.start(), ([], None))
        self.assertEqual(self.counts(), {dismissed['id']: 0, kept['id']: 3})
        self.assertEqual(self.conflicts()['data']['open'], [self.line(kept, first, second)])
        again = self.conflicts(dismissed['id'])
        self.assertEqual((again['outcome'], again['code']), ('refused', 'conflict-not-found'))
        self.assertEqual(self.candidates()[0]['closed'], DISMISSED)

    def test_a_dismissal_stays_when_the_run_that_opened_the_candidate_is_undone(self):
        (_, second), value, newer, older = self.pair()
        self.assertEqual(self.conflicts(value['id'])['data']['dismissed'], value['id'])
        preview = self.command(second)
        self.assertIn({'target': 'candidate:' + value['id'], 'by': '', 'why': 'later-unlogged-change'},
                      preview['data']['kept'])
        self.undo(second)
        self.assertEqual(self.candidates(), [dict(value, status='dismissed', closed=DISMISSED)])
        self.assertNotEqual(self.fixture.items()[newer]['status'], 'current')
        self.assertEqual(self.conflicts()['data']['open'], [])

    # TC-355

    def test_tc355_an_unknown_other_project_or_closed_candidate_is_not_found_and_nothing_changes(self):
        first, second, third = self.item('First'), self.item('Second'), self.item('Third')
        withdrawn = self.item('Withdrawn', status='withdrawn')
        listed = candidate(1, first, second)
        others = [candidate(2, first, third, status='settled'), candidate(3, second, third, status='dismissed'),
                  candidate(4, third, withdrawn)]
        self.fixture.layer(items=[first, second, third, withdrawn], candidates=[listed] + others)
        elsewhere = self.fixture.folder / 'projects/other/layer'
        elsewhere.mkdir(parents=True)
        (elsewhere / 'conflicts.json').write_bytes(item_types._raw({'candidates': [candidate(5, first, second)]}))
        before = self.tree()
        for name in [value['id'] for value in others] + [ident('c', 5), ident('c', 6), first['id'], 'x' * 200]:
            with self.subTest(name=name):
                value = self.conflicts(name)
                self.assertEqual((value['outcome'], value['code'], value['say']),
                                 ('refused', 'conflict-not-found', conflicts_command.SAY['missing']))
                self.assertEqual(value['data'], {'project': 'sample', 'open': [self.line(listed, first, second)],
                                                 'candidate': name})
        self.assertEqual(self.tree(), before)

    def test_an_argument_outside_the_schema_is_usage(self):
        before = self.tree()
        for name in ('', 'c' * 201, 7, ['c_000000000001']):
            with self.subTest(name=name):
                value = self.conflicts(arguments={'folder': str(self.root), 'dismiss': name})
                self.assertEqual((value['outcome'], value['code'], value['data']), ('refused', 'usage', {}))
        self.assertEqual(self.tree(), before)

    def test_only_the_layer_lease_is_waited_for_and_a_busy_one_answers_lock_busy(self):
        newer, older = self.item('Newer'), self.item('Older')
        value = candidate(1, newer, older)
        self.fixture.layer(items=[newer, older], candidates=[value])
        before = self.tree()
        with mock.patch.object(conflicts_command, 'WAIT', 0.2):
            with self.held('layer.lock', 'layer'):
                for dismiss in (None, value['id']):
                    started = clock.now()
                    busy = self.conflicts(dismiss)
                    self.assertLess(clock.now() - started, 5)
                    self.assertEqual((busy['outcome'], busy['code']), ('failed', 'lock-busy'))
            self.assertEqual(self.tree(), before)
            # A curation holds the curation lease: the list and the dismissal go on, and its request goes stale.
            with self.held('curation.lock', 'curation'):
                self.assertEqual(self.conflicts()['data']['open'], [self.line(value, newer, older)])
                self.assertEqual(self.conflicts(value['id'])['code'], 'ok')
        self.assertEqual(self.candidates(), [dict(value, status='dismissed', closed=DISMISSED)])
        self.assertEqual(self.memory.held, [])

    # TC-351 and the other ways that a candidate settles

    def test_tc351_a_later_user_choice_settles_the_candidate_and_no_later_notice_names_it(self):
        _, value, newer, older = self.pair()
        items = self.fixture.items()
        self.assertEqual(self.conflicts()['data']['open'], [self.line(value, *(items[i] for i in value['items']))])
        notices, reserved = self.start()
        self.assertEqual((len(notices), reserved), (1, value['id']))
        self.assertIn('%s ("%s") and %s ("%s")' % tuple(
            part for i in value['items'] for part in (i, items[i]['title'])), notices[0])
        later = self.curate('Actually keep them for 60 days.', lambda said: answer(change(
            quote(said, 'keep them for 60 days'), action='replace', targets=[newer], kind='decision',
            title='Logs for 60 days')))
        self.assertEqual(run_log.read(self.root, later)['conflicts'],
                         [{'candidate': value['id'], 'from': 'open', 'to': 'settled'}])
        self.assertEqual(self.candidates(), [dict(value, status='settled', closed=STAMP)])
        self.assertEqual((self.fixture.items()[newer]['status'], self.fixture.items()[older]['status']),
                         ('superseded', 'current'))
        self.assertEqual(self.start(), ([], None))
        self.assertEqual(self.counts(), {value['id']: 1})
        listing, dismissal = self.conflicts(), self.conflicts(value['id'])
        self.assertEqual((listing['outcome'], listing['data']['open']), ('nothing', []))
        self.assertEqual(dismissal['code'], 'conflict-not-found')

    def test_a_forget_of_either_item_settles_the_candidate_and_no_later_notice_names_it(self):
        _, value, newer, older = self.pair()
        preview, done = self.forget(older)
        self.assertEqual((preview['data']['settled_conflicts'], done['data']['settled_conflicts']),
                         ([value['id']], [value['id']]))
        (settled,) = self.candidates()
        self.assertEqual((settled['status'], self.fixture.items()[newer]['status']), ('settled', 'current'))
        self.assertEqual(self.start(), ([], None))
        self.assertEqual(self.conflicts()['data']['open'], [])

    def test_an_undo_of_the_run_that_saved_either_item_settles_the_candidate(self):
        (first, _), value, newer, older = self.pair()
        self.undo(first)
        self.assertEqual(self.candidates(), [dict(value, status='settled', closed=inverse_fixture.STAMP)])
        self.assertEqual(self.fixture.items()[newer]['status'], 'current')
        self.assertEqual(self.start(), ([], None))
        self.assertEqual(self.conflicts()['data']['open'], [])

    # The contract

    def test_the_examples_say_what_the_handler_says(self):
        valid = json.loads((ROOT / 'docs/06-api/memory-examples.json').read_text(encoding='utf-8'))['result']['valid']
        for name, key in (('conflicts-none', 'none'), ('conflicts-open', 'one'), ('conflicts-dismissed', 'dismissed'),
                          ('conflict-not-found', 'missing')):
            with self.subTest(name):
                self.assertEqual(valid[name]['say'], conflicts_command.SAY[key])

    def test_the_runner_still_answers_usage_for_conflicts_before_activation(self):
        newer, older = self.item('Newer'), self.item('Older')
        value = candidate(1, newer, older)
        self.fixture.layer(items=[newer, older], candidates=[value])
        before = self.tree()
        for argv in (['conflicts'], ['conflicts', '--dismiss', value['id']],
                     ['--folder', str(self.root), 'conflicts']):
            with self.subTest(argv=argv):
                result, status = commands.run(argv, handlers={'conflicts': conflicts_command.conflicts})
                self.assertEqual((result['command'], result['code'], status), ('none', 'usage', 2))
        self.assertNotIn('conflicts', commands.COMMANDS)
        self.assertNotIn('conflicts', commands.ASKS)
        self.assertEqual(self.tree(), before)


if __name__ == '__main__':
    unittest.main()
