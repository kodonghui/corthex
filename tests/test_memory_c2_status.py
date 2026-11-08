"""TASK-096: the memory status of C2 (API-018; SPEC-033, SPEC-018) on format-2 stores.

TC-234. Until the 0.3.0 activation the runner hands `status` to the C1
handler, whose store gate refuses a format-2 store, which a test checks, so
these tests call the C2 handler as the runner will, after its gates, with the
format-2 store binding. The curations, the consolidation and the stop are real
ones against the local test server of the curation worker's tests, and the pin
is the pin command's own; no provider is called.
"""
from datetime import datetime, timezone
import json
import sys
import types
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import (c2_status, clock, commands, curation_worker, format2, item_types, locks, pin_command,
                        run_log)
from test_memory_curator_answers import answer, change, quote
import test_memory_commands as commands_fixture
import test_memory_conflicts_command as conflicts_fixture
import test_memory_consolidation_worker as consolidation_fixture
import test_memory_curation_worker as worker_fixture
import test_memory_start_summary as start_fixture

DEVICE, AT, REFUSAL = worker_fixture.DEVICE, worker_fixture.AT, worker_fixture.REFUSAL
# The consolidation of these tests, a later curation's failures, and the status read after them.
MERGED = consolidation_fixture.STAMP
FAILED = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)
NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)
PINNED = '2026-11-12T09:30:00.000Z'
UNPRICED = 'claude-sonnet-5-5'  # a curator model that the default price list does not name
EMPTY = dict(current=0, superseded=0, withdrawn=0, undone=0)


class StatusStore(conflicts_fixture.ConflictsStore):
    """A format-2 project with one recorded turn, and the C2 status read as the runner will read it."""

    def status(self, everything=False, project='sample', when=NOW, memory=None):
        context = commands.Context('status', {'folder': str(self.root), 'all': everything}, None,
                                   memory or self.memory)
        context.project = types.SimpleNamespace(name=project)
        context.record = {'device': DEVICE}
        value = c2_status.status(context, when=when)
        commands.validate_result(value, 'status')
        return value

    def project(self, **options):
        (value,) = self.status(**options)['data']['projects']
        return value

    def failed(self, prompt):
        """Three refused curations of a new turn, at FAILED, which stop curation for the project (TC-170)."""
        said, _ = self.fixture.one_turn(prompt, 'Noted.')
        self.fixture.mark(said)
        self.fixture.server.answers = [REFUSAL]
        reasons = []
        for _ in range(3):
            deadline = clock.now() + 300
            with self.memory.lease(self.root / 'curation.lock', 'curation', deadline) as owner:
                reasons.append(curation_worker.curate(self.memory, 'sample', owner, deadline, when=FAILED).reason)
        self.assertEqual(reasons, ['failed', 'failed', 'stopped'])
        return said

    def pin(self, item, at=PINNED):
        context = commands.Context('pin', {'folder': str(self.root), 'item': item}, None, self.memory)
        context.project = types.SimpleNamespace(name='sample')
        context.record = {'device': DEVICE}
        value = pin_command.pin(context, at=at, base_text=start_fixture.BASE)
        self.assertEqual(value['outcome'], 'done')
        return value


class StatusTest(StatusStore, unittest.TestCase):
    # TC-234

    def test_tc234_curations_a_consolidation_a_stop_and_a_pin_with_an_unpriced_curator(self):
        self.fixture.configure(models={'curator': UNPRICED})
        first = self.curate('Answer me in Korean.', lambda said: answer(change(
            quote(said, 'Answer me in Korean'), kind='preference', title='Korean answers')))
        second = self.curate('Korean answers, please.', lambda said: answer(change(
            quote(said, 'Korean answers, please'), kind='preference', title='Answers in Korean')))
        (older,) = run_log.read(self.root, first)['saved']
        (newer,) = run_log.read(self.root, second)['saved']
        items = self.fixture.items()
        merge = consolidation_fixture.merge([items[older], items[newer]], [(items[newer], 1), (items[older], 1)],
                                            title='Korean', text='The user wants answers in Korean.')
        consolidation_fixture.ConsolidationWorkerTest.answering(self.fixture,
                                                                {'preference': consolidation_fixture.merges(merge)})
        outcome = consolidation_fixture.ConsolidationWorkerTest.consolidate(self.fixture)
        self.assertEqual((outcome.reason, outcome.applied), ('done', True))
        self.fixture.server.reply = None
        # The newest attempt is the consolidation; `curation` is the curate attempt before it, which failed none.
        self.assertEqual(self.fixture.progress()['recent'][0]['kind'], 'consolidate')
        self.assertEqual(self.project()['curation'], {'at': worker_fixture.STAMP, 'result': 'ok'})
        (merged,) = [item for item in self.fixture.items() if item not in (older, newer)]
        self.pin(merged)
        said = self.failed('Name the script hook.py.')
        value = self.status()
        data = value['data']
        progress = self.fixture.progress()
        (consolidated,) = [attempt['run'] for attempt in progress['recent'] if attempt['kind'] == 'consolidate']
        when = FAILED.strftime('%Y-%m-%dT%H:%M:%S.000Z')
        self.assertEqual(data['projects'], [{
            'project': 'sample', 'enabled': True, 'since': AT,
            'curation': {'at': when, 'result': 'failed', 'error': 'refusal', 'failed_in_row': 3},
            'unprocessed': 1, 'oldest': said['at'],
            'stopped': {'at': when, 'by': 'curate', 'errors': ['refusal']},
            'consolidation': {'failures': 0, 'last': MERGED},
            'items': dict(EMPTY, current=1, superseded=2), 'pins': [merged], 'open_conflicts': 0,
            'last_run': {'run': consolidated, 'kind': 'consolidate'}}])
        self.assertEqual(value['say'], 'Curation of sample is stopped after three failed attempts in a row '
                                       '(refusal); resume can start it again.')
        # This month's usage by model: the curator's calls cost 0 and name it as having no price.
        rows = [row for row in self.fixture.usage() if row['call'] != 'count-tokens']
        self.assertEqual(sorted({row['call'] for row in rows}), ['consolidate', 'curate'])
        self.assertEqual(data['usage'], {
            'month': '2026-11', 'cost': 0, 'unpriced': [UNPRICED],
            'models': [{'model': UNPRICED, 'calls': len(rows), 'cost': 0,
                        'input': sum(row.get(k, 0) for row in rows for k in ('input', 'cache_write', 'cache_read')),
                        'output': sum(row.get('output', 0) for row in rows)}]})
        self.assertEqual(len(rows), 6)
        self.assertEqual((data['keys'], data['waits']), ({'anthropic': 'present', 'openai': 'missing'},
                                                         ['openai-key']))
        self.assertEqual((data['store']['format'], data['store']['device'], data['store']['release']),
                         (2, DEVICE, '0.3.0'))
        # No conversation text and no key.
        text = json.dumps(value)
        for words in ('Answer me in Korean', 'Korean answers', 'hook.py', 'Noted', 'answers in Korean',
                      conflicts_fixture.SAID, conflicts_fixture.REPLY):
            self.assertNotIn(words, text)
        keys = [value for name, value in self.fixture.keys.items() if name.endswith('_API_KEY') and value]
        self.assertEqual(len(keys), 3)
        for key in keys:
            self.assertNotIn(key, text)

    def test_a_project_before_its_first_curation_shows_its_turns_and_nothing_else(self):
        self.fixture.mark(self.said)
        # A later turn waits too; the oldest's time stays the first's.
        later, _ = self.fixture.raw.turn('Name the script hook.py.', 'Noted.', at='2026-11-05T03:00:00.000Z')
        self.fixture.write()
        self.fixture.mark(later)
        value = self.status()
        self.assertEqual(value['data']['projects'], [{
            'project': 'sample', 'enabled': True, 'since': AT, 'unprocessed': 2, 'oldest': self.said['at'],
            'consolidation': {'failures': 0}, 'items': EMPTY, 'pins': [], 'open_conflicts': 0}])
        self.assertEqual(value['say'], c2_status.SAY['status'])
        self.assertEqual(value['data']['usage'], {'month': '2026-11', 'models': [], 'cost': 0})

    def test_items_by_status_leave_out_forgotten_items_and_pins_show_current_items_oldest_pin_first(self):
        values = {name: self.item(name) for name in ('one', 'two', 'three', 'old', 'gone', 'undone', 'forgotten')}
        values['old'].update(status='superseded', superseded_by=values['one']['id'])
        values['gone']['status'] = 'withdrawn'
        values['undone'].update(status='undone')
        self.fixture.layer(items=list(values.values()))
        pins = [('two', '2026-11-12T08:00:00.000Z', True), ('one', '2026-11-12T09:00:00.000Z', True),
                ('old', '2026-11-12T07:00:00.000Z', True), ('gone', '2026-11-12T06:00:00.000Z', True),
                ('three', '2026-11-12T05:00:00.000Z', False), ('forgotten', '2026-11-12T04:00:00.000Z', True)]
        (self.root / 'layer/pins.json').write_bytes(item_types.pins_bytes({'pins': [
            {'item': values[name]['id'], 'on': on, 'at': at, 'device': DEVICE} for name, at, on in pins]}))
        # A forget that has written its tombstone and not yet deleted the item's file.
        cited = values['forgotten']['quotes'][0]
        tombstone = dict(item=values['forgotten']['id'], project='sample', at=AT, device=DEVICE,
                         quotes=[{k: cited[k] for k in ('device', 'entry', 'log', 'start', 'end')}])
        (self.root / 'layer/tombstones' / (values['forgotten']['id'] + '.json')).write_bytes(
            item_types._raw(tombstone) + b'\n')
        value = self.project()
        self.assertEqual(value['items'], dict(current=3, superseded=1, withdrawn=1, undone=1))
        self.assertEqual(value['pins'], [values['two']['id'], values['one']['id']])

    def test_open_conflicts_count_the_candidates_that_conflicts_lists(self):
        _, candidate, newer, older = self.pair()
        self.assertEqual(self.project()['open_conflicts'], 1)
        self.assertEqual(len(self.conflicts()['data']['open']), 1)
        # A candidate whose item is no longer current is not listed, until its next writer settles it.
        items = self.fixture.items()
        changed = dict(items[older], status='withdrawn')
        (self.root / 'layer/items' / (older + '.json')).write_bytes(item_types.item_bytes(changed))
        self.assertEqual(self.project()['open_conflicts'], 0)
        self.assertEqual(self.conflicts()['data']['open'], [])

    def test_the_last_run_is_the_newest_run_that_runs_lists(self):
        first = self.curate('Answer me in Korean.', lambda said: answer(change(
            quote(said, 'Answer me in Korean'), kind='preference', title='Korean answers')))
        self.assertEqual(self.project()['last_run'], {'run': first, 'kind': 'curate'})
        # A run past the retention period is not listed, as `runs` leaves it out.
        self.assertNotIn('last_run', self.project(when=datetime(2027, 3, 1, tzinfo=timezone.utc)))

    # What cannot be read, and the projects without a layer

    def test_a_record_that_cannot_be_read_leaves_its_fields_out_and_its_backup_is_read_not_restored(self):
        self.fixture.mark(self.said)
        self.failed('Name the script hook.py.')
        whole = self.project()
        path = self.root / 'curation.json'
        good = path.read_bytes()
        path.with_name('curation.json.bak').write_bytes(good)
        path.write_bytes(b'{"logs": ')
        self.assertEqual(self.project(), whole)
        self.assertEqual(path.read_bytes(), b'{"logs": ')
        path.with_name('curation.json.bak').write_bytes(b'{"logs": ')
        value = self.project()
        for field in ('curation', 'stopped', 'consolidation', 'last_run'):
            self.assertNotIn(field, value)
        self.assertEqual((value['unprocessed'], value['items']), (whole['unprocessed'], whole['items']))
        self.assertEqual(path.read_bytes(), b'{"logs": ')

    def test_a_project_without_a_folder_or_being_deleted_shows_its_configuration_only(self):
        self.fixture.configure(projects={'sample': {'enabled': True, 'since': AT},
                                         'other': {'enabled': False, 'since': AT}})
        self.fixture.mark(self.said)
        values = self.status(everything=True)['data']['projects']
        self.assertEqual([value['project'] for value in values], ['other', 'sample'])
        self.assertEqual(values[0], {'project': 'other', 'enabled': False, 'since': AT, 'unprocessed': 0,
                                     'items': EMPTY, 'pins': []})
        for name in ('layer/deleted.json', 'layer/deleted.json.0123456789abcdef.tmp'):
            with self.subTest(name=name):
                path = self.root / name
                path.write_bytes(b'{}\n')
                self.assertEqual(self.project(), {'project': 'sample', 'enabled': True, 'since': AT,
                                                  'unprocessed': 0, 'items': EMPTY, 'pins': []})
                path.unlink()

    def test_the_folder_s_project_alone_unless_all_and_none_outside_a_project(self):
        self.fixture.configure(projects={'sample': {'enabled': True, 'since': AT},
                                         'other': {'enabled': True, 'since': AT}})
        self.assertEqual([p['project'] for p in self.status()['data']['projects']], ['sample'])
        self.assertEqual([p['project'] for p in self.status(everything=True)['data']['projects']],
                         ['other', 'sample'])
        self.assertEqual(self.status(project='elsewhere')['data']['projects'], [])

    def test_damaged_items_or_pins_raise_and_change_nothing(self):
        value = self.item('Pinned')
        self.fixture.layer(items=[value], pinned=[value['id']])
        before = self.tree()
        for name, damage in (('layer/pins.json', b'{"pins": ['), ('layer/items/%s.json' % value['id'], b'{')):
            with self.subTest(name=name):
                path = self.root / name
                good = path.read_bytes()
                path.write_bytes(damage)
                with self.assertRaises(Exception):
                    self.status()
                path.write_bytes(good)
                self.assertEqual(self.tree(), before)
        self.assertEqual(self.memory.held, [])

    def test_the_status_waits_for_the_project_s_layer_lease(self):
        with self.held('layer.lock', 'layer'), mock.patch.object(c2_status, 'WAIT', 0.2):
            started = clock.now()
            value = self.status()
            self.assertLess(clock.now() - started, 5)
        self.assertEqual((value['outcome'], value['code']), ('failed', 'lock-busy'))
        self.assertEqual(self.memory.held, [])

    def test_the_logs_are_read_as_the_c1_status_reads_them(self):
        day = NOW.strftime('%Y-%m-%d')
        logs = self.fixture.folder / 'logs'
        hooks = [dict(at='2026-11-12T11:00:0%d.000Z' % n, hook='prompt', host='claude-code', ms=ms, outcome='ok')
                 for n, ms in enumerate((40, 10, 30, 20))]
        (logs / ('hooks-%s.jsonl' % day)).write_text(''.join(json.dumps(row) + '\n' for row in hooks))
        failure = dict(at='2026-11-12T11:30:00.000Z', step='curate', project='sample', error='refusal')
        (logs / ('failures-%s.jsonl' % day)).write_text(json.dumps(failure) + '\n')
        (logs / 'usage-2026-11.jsonl').write_text('{"at": \n')
        data = self.status()['data']
        self.assertEqual(data['hooks'], [dict(hook='prompt', host='claude-code', runs=4, median_ms=25, p95_ms=40,
                                              last='2026-11-12T11:00:03.000Z', outcomes={'ok': 4})])
        self.assertIn(failure, data['failures'])
        self.assertEqual(data['unreadable'], ['usage'])
        self.assertNotIn('usage', data)
        self.assertEqual(len(data['projects']), 1)

    def test_a_changed_store_record_stops_the_status(self):
        path = self.fixture.folder / 'store.json'
        good = path.read_bytes()
        reader, usage = c2_status.Reader, c2_status.Reader.usage
        changed = []

        def change_it():
            path.write_bytes(format2.store_bytes({'format': 2, 'device': DEVICE, 'made': AT, 'release': '0.3.1'}))
            changed.append(True)

        def at_the_start(context, when=None):
            value = reader(context, when)
            change_it()
            return value

        def after_the_projects(self, config):
            value = usage(self, config)
            change_it()
            return value
        # Before the projects, each project's read finds the change; after them, the C1 parts' last check does.
        for patch in (mock.patch.object(c2_status, 'Reader', side_effect=at_the_start),
                      mock.patch.object(c2_status.Reader, 'usage', after_the_projects)):
            with self.subTest(patch=patch.attribute):
                path.write_bytes(good)
                memory = worker_fixture.C2Store(self.fixture.folder, expected_device=DEVICE)
                logged = sorted((self.fixture.folder / 'logs').iterdir())
                with patch, self.assertRaises(locks.LostLock):
                    self.status(memory=memory)
                self.assertEqual((memory.held, sorted((self.fixture.folder / 'logs').iterdir())), ([], logged))
        self.assertEqual(changed, [True, True])

    def test_the_store_part_is_the_store_record_as_it_is(self):
        (self.fixture.folder / 'store.json').write_bytes(format2.store_bytes(
            {'format': 2, 'device': DEVICE, 'made': AT, 'release': '0.3.1'}))
        memory = worker_fixture.C2Store(self.fixture.folder, expected_device=DEVICE)
        store = self.status(memory=memory)['data']['store']
        self.assertEqual((store['format'], store['device'], store['release'], 'made' in store),
                         (2, DEVICE, '0.3.1', False))

    def test_a_log_restored_from_its_backup_is_noted_once_the_status_is_read(self):
        path = self.fixture.folder / 'logs' / ('hooks-%s.jsonl' % NOW.strftime('%Y-%m-%d'))
        row = dict(at='2026-11-12T11:00:00.000Z', hook='prompt', host='claude-code', ms=20, outcome='ok')
        path.with_name(path.name + '.bak').write_text(json.dumps(row) + '\n')
        self.assertEqual(self.status()['data']['hooks'][0]['runs'], 1)
        noted = [json.loads(line) for name in sorted((self.fixture.folder / 'logs').glob('failures-*.jsonl'))
                 for line in name.read_bytes().splitlines()]
        self.assertEqual([note['step'] for note in noted], ['restore'])

    def test_a_stop_by_consolidation_is_named_with_its_consolidations(self):
        consolidation = consolidation_fixture.ConsolidationWorkerTest
        self.fixture.layer([consolidation.item(self.fixture, 'preference', 'Answer me in Korean'),
                            consolidation.item(self.fixture, 'preference', 'Korean answers, please')])
        self.fixture.server.answers = [worker_fixture.failing(400, 'invalid_request_error')]
        self.assertEqual([consolidation.consolidate(self.fixture).reason for _ in range(3)],
                         ['failed', 'failed', 'stopped'])
        value = self.status()
        (project,) = value['data']['projects']
        self.assertEqual((project['stopped']['by'], project['consolidation']['failures']), ('consolidate', 3))
        self.assertEqual(value['say'], 'Curation of sample is stopped after three failed consolidations in a row '
                                       '(invalid_request_error); resume can start it again.')


class StatusRunnerTest(unittest.TestCase):
    reset_store, snapshot = commands_fixture.CommandsTest.reset_store, commands_fixture.CommandsTest.snapshot

    def setUp(self):
        commands_fixture.CommandsTest.setUp(self)

    def test_the_runner_keeps_the_c1_status_which_refuses_a_format_2_store(self):
        value, status = commands.run(['--folder', str(self.project), 'status'])
        self.assertEqual((value['outcome'], value['code']), ('done', 'ok'))
        self.assertIn('not active in C1', value['say'])
        (self.root / 'store.json').write_bytes(format2.store_bytes(
            {'format': 2, 'device': DEVICE, 'made': AT, 'release': '0.3.0'}))
        before = self.snapshot()
        value, status = commands.run(['--folder', str(self.project), 'status'])
        self.assertEqual((value['outcome'], value['code'], status), ('refused', 'store-newer', 1))
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
