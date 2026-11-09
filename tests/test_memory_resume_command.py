"""TASK-096: the resume command (API-019; SPEC-033, SPEC-018) on format-2 stores.

TC-231 and TC-233. The runner parses `resume` but hands it to no handler
before the 0.3.0 activation, which a test checks, so these tests call the
handler as the runner will, after its gates, with the format-2 store binding.
The stops come from real curations and consolidations against the local test
server of the curation worker's tests; no provider is called, and no worker
process starts: the launcher's process start is replaced by a stand-in that
records its command line.
"""
import contextlib
from datetime import timedelta
import json
import sys
import time
import types
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import (clock, commands, curation_triggers, curation_worker, files, format2, resume_command,
                        revision_io, worker_launch)
from test_memory_curator_answers import answer, change, quote
import test_memory_commands as commands_fixture
import test_memory_consolidation_worker as consolidation_fixture
import test_memory_curation_worker as worker_fixture
import test_memory_undo as undo_fixture

DEVICE, LOG, STAMP = worker_fixture.DEVICE, worker_fixture.LOG, worker_fixture.STAMP
REFUSAL, LIMIT, failing = worker_fixture.REFUSAL, worker_fixture.LIMIT, worker_fixture.failing
HOOKS = worker_fixture.HOOKS
SAY = resume_command.SAY
WORKER = [sys.executable, '-I', str(worker_launch.WORKER), '--reason', 'skill', '--project', 'sample',
          '--expect-device', DEVICE]


class ResumeStore:
    """A format-2 project with a recorded turn, and the resume command run as the runner will run it."""
    held = undo_fixture.UndoStore.held

    def setUp(self):
        self.fixture = worker_fixture.CurationWorkerTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.memory = self.fixture.root, self.fixture.memory
        self.server = self.fixture.server

    def command(self, code=None, project='sample', memory=None):
        context = commands.Context('resume', {'folder': str(self.root)}, code, memory or self.memory)
        context.project = types.SimpleNamespace(name=project)
        context.record = {'device': DEVICE}
        value = resume_command.resume(context)
        commands.validate_result(value, 'resume')
        return value

    @contextlib.contextmanager
    def launches(self):
        """The worker's process start replaced: each call's command line, and nothing started."""
        calls = []

        def popen(command, **options):
            calls.append(command)
            return types.SimpleNamespace(pid=0)
        with mock.patch.object(worker_launch.subprocess, 'Popen', side_effect=popen):
            yield calls

    def turn(self, prompt=HOOKS + ', please.'):
        """A recorded turn with its marker, as the end-of-turn hook leaves it (TBL-008)."""
        said, _ = self.fixture.one_turn(prompt)
        self.fixture.mark(said)
        return said

    def stop(self):
        """Three refused curations of one turn, which stop curation for the project (TC-170)."""
        said = self.turn()
        self.server.answers = [REFUSAL]
        self.assertEqual([self.fixture.curate().reason for _ in range(3)], ['failed', 'failed', 'stopped'])
        return said

    def tree(self):
        """Every file of the memory store but the lock files and the logs, as bytes."""
        folder = self.fixture.folder
        return {path.relative_to(folder).as_posix(): path.read_bytes() for path in sorted(folder.rglob('*'))
                if path.is_file() and path.suffix != '.lock' and path.parent.name != 'logs'}

    def trigger(self):
        """What a met trigger at the end of a session decides now (SPEC-010)."""
        settings = self.memory.configuration(self.memory.note, deadline=clock.now() + 10)
        return curation_triggers.decide(self.memory, settings, 'sample', 'end', clock.now() + 10)

    def failure_log(self):
        return [json.loads(line) for path in sorted((self.fixture.folder / 'logs').glob('failures-*.jsonl'))
                for line in path.read_bytes().splitlines()]


class ResumeTest(ResumeStore, unittest.TestCase):
    # TC-231

    def test_tc231_resume_asks_with_the_failures_then_clears_the_stop_and_the_next_trigger_curates(self):
        said = self.stop()
        self.assertEqual(self.trigger(), 'stopped')
        before, progress = self.tree(), self.fixture.progress()
        failed = [{'at': STAMP, 'kind': 'curate', 'error': 'refusal'}] * 3
        data = {'project': 'sample', 'unprocessed': 1, 'failures': failed}
        with self.launches() as calls:
            asked = self.command()
            self.assertEqual((asked['outcome'], asked['code'], asked['data']), ('confirm', 'ok', data))
            self.assertEqual(asked['say'], 'Curation of sample stopped after three failed attempts in a row '
                                           '(refusal). Resuming clears the stop and starts the memory worker for '
                                           'the 1 unprocessed turn.')
            self.assertEqual((self.tree(), calls), (before, []))
            done = self.command(asked['confirm'])
        self.assertEqual((done['outcome'], done['code'], done['data']), ('done', 'ok', data))
        self.assertEqual(done['say'], 'Curation of sample resumed, and the memory worker started for the 1 '
                                      'unprocessed turn.')
        self.assertEqual(calls, [WORKER])
        after = self.fixture.progress()
        expected = dict(progress, failures={'count': 0, 'log': LOG, 'turn': said['turn']})
        del expected['stopped']
        self.assertEqual(after, expected)
        changed = {name for name in set(before) | set(self.tree()) if before.get(name) != self.tree().get(name)}
        self.assertEqual(changed, {'projects/sample/curation.json'})
        self.assertEqual(self.memory.held, [])
        # The next met trigger starts a curator, and the curator sends the turn again.
        self.assertEqual(self.trigger(), 'start')
        self.server.answers = [answer(change(quote(said, HOOKS), kind='decision'))]
        outcome = self.fixture.curate()
        self.assertEqual((outcome.reason, len(self.server.requests)), ('done', 4))
        self.assertEqual(self.fixture.progress()['failures']['count'], 0)

    def test_the_fault_guard_counts_three_new_failures_after_a_resume(self):
        self.stop()
        with self.launches():
            self.command(self.command()['confirm'])
        self.assertEqual([self.fixture.curate().reason for _ in range(3)], ['failed', 'failed', 'stopped'])
        progress = self.fixture.progress()
        self.assertEqual((progress['failures']['count'], progress['stopped']['by']), (3, 'curate'))
        self.assertEqual(len(resume_command.failures(progress)), 3)

    def test_the_failures_are_the_stop_s_own_attempts_newest_first(self):
        self.turn()
        other = worker_fixture.C2Store(self.fixture.folder, expected_device=DEVICE)
        times = [worker_fixture.WHEN + timedelta(minutes=minutes) for minutes in (0, 10, 20)]
        self.server.answers = [REFUSAL]
        # The second run's first request goes stale, as a forget while it waits makes it (TC-174).
        self.server.before[1] = lambda: self.fixture.advance(other)
        runs = []
        for when in times:
            deadline = clock.now() + 300
            with self.memory.lease(self.root / 'curation.lock', 'curation', deadline) as owner:
                outcome = curation_worker.curate(self.memory, 'sample', owner, deadline, when=when)
            runs.append((outcome.reason, [attempt.record['result'] for attempt in outcome.attempts]))
        self.assertEqual(runs, [('failed', ['failed']), ('failed', ['stale', 'failed']), ('stopped', ['failed'])])
        stamps = [when.strftime('%Y-%m-%dT%H:%M:%S.000Z') for when in times]
        progress = self.fixture.progress()
        self.assertEqual([(attempt['at'], attempt['result']) for attempt in progress['recent']],
                         [(stamps[2], 'failed'), (stamps[1], 'failed'), (stamps[1], 'stale'), (stamps[0], 'failed')])
        failed = [{'at': stamp, 'kind': 'curate', 'error': 'refusal'} for stamp in reversed(stamps)]
        with self.launches():
            self.assertEqual(self.command()['data']['failures'], failed)
        # A failed attempt that a valid record keeps without its error shows RuntimeError, as the stop's errors do.
        del progress['recent'][3]['error']
        format2.parse_curation(format2.curation_bytes(progress))
        self.assertEqual(resume_command.failures(progress), failed[:2] + [dict(failed[2], error='RuntimeError')])

    def test_a_stop_by_consolidation_shows_its_failures_and_both_counts_go_back_to_zero(self):
        first = consolidation_fixture.ConsolidationWorkerTest.item(self.fixture, 'preference',
                                                                    'Answer me in Korean')
        second = consolidation_fixture.ConsolidationWorkerTest.item(self.fixture, 'preference',
                                                                     'Korean answers, please')
        self.fixture.layer([first, second])

        def consolidate():
            return consolidation_fixture.ConsolidationWorkerTest.consolidate(self.fixture).reason
        self.server.answers = [failing(400, 'invalid_request_error')]
        self.assertEqual(consolidate(), 'failed')
        # A curation fails between the consolidations: it is not one of the stop's failures, and its count stays.
        self.turn('Name the script hook.py.')
        self.server.answers = [REFUSAL]
        self.assertEqual(self.fixture.curate().reason, 'failed')
        self.server.answers = [failing(400, 'invalid_request_error')]
        self.assertEqual([consolidate(), consolidate()], ['failed', 'stopped'])
        progress = self.fixture.progress()
        self.assertEqual([(attempt['kind'], attempt['result']) for attempt in progress['recent'][:4]],
                         [('consolidate', 'failed'), ('consolidate', 'failed'), ('curate', 'failed'),
                          ('consolidate', 'failed')])
        when = consolidation_fixture.STAMP
        self.assertEqual(progress['stopped'], {'at': when, 'by': 'consolidate', 'errors': ['invalid_request_error']})
        failed = [{'at': when, 'kind': 'consolidate', 'error': 'invalid_request_error'}] * 3
        with self.launches() as calls:
            asked = self.command()
            self.assertEqual(asked['data'], {'project': 'sample', 'unprocessed': 1, 'failures': failed})
            self.assertEqual(asked['say'], 'Curation of sample stopped after three failed consolidations in a row '
                                           '(invalid_request_error). Resuming clears the stop and starts the '
                                           'memory worker for the 1 unprocessed turn.')
            self.command(asked['confirm'])
        after = self.fixture.progress()
        self.assertNotIn('stopped', after)
        self.assertEqual((after['consolidation']['failures'], after['failures']['count']), (0, 0))
        self.assertEqual((after['recent'], after['fence'], after['logs']),
                         (progress['recent'], progress['fence'], progress['logs']))
        self.assertEqual(calls, [WORKER])

    def test_without_unprocessed_turns_no_worker_starts(self):
        self.stop()
        for name in self.fixture.markers():
            (self.root / 'unprocessed' / name).unlink()
        with self.launches() as calls:
            asked = self.command()
            self.assertEqual(asked['data']['unprocessed'], 0)
            self.assertEqual(asked['say'], 'Curation of sample stopped after three failed attempts in a row '
                                           '(refusal). Resuming clears the stop, and the next trigger curates the '
                                           'project.')
            done = self.command(asked['confirm'])
        self.assertEqual((done['outcome'], done['say']), ('done', SAY['resumed'] % 'sample'))
        self.assertEqual(calls, [])
        self.assertNotIn('stopped', self.fixture.progress())

    def test_a_worker_that_does_not_start_leaves_the_stop_cleared_and_is_noted(self):
        self.stop()
        asked = self.command()
        logged = len(self.failure_log())
        with mock.patch.object(worker_launch.subprocess, 'Popen', side_effect=OSError()):
            done = self.command(asked['confirm'])
        self.assertEqual((done['outcome'], done['say']),
                         ('done', SAY['not-started'] % ('sample', '1 unprocessed turn')))
        self.assertNotIn('stopped', self.fixture.progress())
        self.assertEqual([(row['step'], row['error'], row.get('project')) for row in self.failure_log()[logged:]],
                         [('trigger', 'worker-start', 'sample')])

    # TC-233

    def test_tc233_a_code_is_stale_after_two_ten_minute_periods(self):
        self.stop()
        before = self.tree()
        with self.launches() as calls:
            asked = self.command()
            # The current and the previous period are accepted, so a code lasts ten to twenty minutes.
            with mock.patch.object(commands.time, 'time', return_value=time.time() + 1200):
                stale = self.command(asked['confirm'])
                self.assertEqual((stale['outcome'], stale['code'], stale['data']),
                                 ('confirm', 'confirm-stale', asked['data']))
                self.assertEqual(stale['say'], 'The confirmation is stale. Review the current proposal and '
                                               'confirm again.')
                self.assertNotEqual(stale['confirm'], asked['confirm'])
                self.assertEqual((self.tree(), calls), (before, []))
                done = self.command(stale['confirm'])
        self.assertEqual((done['outcome'], done['code']), ('done', 'ok'))
        self.assertEqual(calls, [WORKER])
        self.assertNotIn('stopped', self.fixture.progress())

    def test_tc233_a_new_turn_after_the_preview_leaves_its_code_current(self):
        # The maintainer's decision of 2026-11-09: the person's own answer is recorded as a new turn, so the code
        # covers the stop and its failures, not the unprocessed turns.
        self.stop()
        with self.launches() as calls:
            asked = self.command()
            self.assertEqual(asked['data']['unprocessed'], 1)
            self.turn('Name the script hook.py.')
            done = self.command(asked['confirm'])
        self.assertEqual((done['outcome'], done['code'], done['data']),
                         ('done', 'ok', dict(asked['data'], unprocessed=2)))
        self.assertEqual(done['say'], SAY['started'] % ('sample', '2 unprocessed turns'))
        self.assertEqual(calls, [WORKER])
        self.assertNotIn('stopped', self.fixture.progress())

    def test_tc233_a_code_for_an_earlier_stop_is_stale(self):
        self.stop()
        with self.launches():
            asked = self.command()
            self.assertEqual(self.command(asked['confirm'])['outcome'], 'done')
        # Later curations fail again, and the fault guard stops the project once more.
        self.server.answers = [REFUSAL]
        reasons = []
        for minutes in (10, 20, 30):
            deadline = clock.now() + 300
            with self.memory.lease(self.root / 'curation.lock', 'curation', deadline) as owner:
                when = worker_fixture.WHEN + timedelta(minutes=minutes)
                reasons.append(curation_worker.curate(self.memory, 'sample', owner, deadline, when=when).reason)
        self.assertEqual(reasons, ['failed', 'failed', 'stopped'])
        before = self.tree()
        with self.launches() as calls:
            stale = self.command(asked['confirm'])
            self.assertEqual((stale['outcome'], stale['code']), ('confirm', 'confirm-stale'))
            self.assertNotEqual(stale['data']['failures'], asked['data']['failures'])
            self.assertNotEqual(stale['confirm'], asked['confirm'])
            self.assertEqual((self.tree(), calls), (before, []))
        self.assertIn('stopped', self.fixture.progress())

    def test_a_made_up_code_is_stale_and_changes_nothing(self):
        self.stop()
        before = self.tree()
        for code in ('00000000', 'zzzzzzzz'):
            with self.subTest(code=code):
                value = self.command(code)
                self.assertEqual((value['outcome'], value['code']), ('confirm', 'confirm-stale'))
                self.assertEqual(self.tree(), before)

    # Nothing to resume

    def test_a_project_that_is_not_stopped_has_nothing_to_resume(self):
        self.turn()
        self.server.answers = [REFUSAL]
        self.assertEqual(self.fixture.curate().reason, 'failed')
        before = self.tree()
        for code in (None, '00000000'):
            with self.subTest(code=code), self.launches() as calls:
                value = self.command(code)
                self.assertEqual((value['outcome'], value['code'], value['data'], value['say']),
                                 ('nothing', 'ok', {'project': 'sample', 'unprocessed': 1},
                                  'Curation of sample is not stopped, so there is nothing to resume.'))
                self.assertEqual((self.tree(), calls), (before, []))
        self.assertEqual(self.fixture.progress()['failures']['count'], 1)

    def test_a_project_without_a_folder_or_being_deleted_has_nothing_to_resume(self):
        self.stop()
        value = self.command(project='other')
        self.assertEqual((value['outcome'], value['data'], value['say']),
                         ('nothing', {'project': 'other'}, SAY['nothing'] % 'other'))
        for name in ('layer/deleted.json', 'layer/deleted.json.0123456789abcdef.tmp'):
            with self.subTest(name=name):
                path = self.root / name
                path.write_bytes(b'{}\n')
                before = self.tree()
                value = self.command()
                self.assertEqual((value['outcome'], value['data']), ('nothing', {'project': 'sample'}))
                self.assertEqual(self.tree(), before)
                path.unlink()

    def test_a_record_that_cannot_be_read_has_no_stop_to_clear_and_a_backup_is_restored(self):
        self.stop()
        path = self.root / 'curation.json'
        good = path.read_bytes()
        # The primary damaged, its backup whole: the backup is restored under the leases, with a new epoch.
        path.with_name('curation.json.bak').write_bytes(good)
        path.write_bytes(b'{"logs": ')
        asked = self.command()
        self.assertEqual((asked['outcome'], asked['data']['failures'][0]['error']), ('confirm', 'refusal'))
        restored = format2.parse_curation(path.read_bytes())
        self.assertIn('stopped', restored)
        # Neither copy readable: no stop is known, and the failure is noted.
        path.write_bytes(b'{"logs": ')
        path.with_name('curation.json.bak').write_bytes(b'{"logs": ')
        before, logged = self.tree(), len(self.failure_log())
        value = self.command(asked['confirm'])
        self.assertEqual((value['outcome'], value['data'], value['say']),
                         ('nothing', {'project': 'sample'}, SAY['unreadable'] % 'sample'))
        self.assertEqual(self.tree(), before)
        self.assertEqual([row['step'] for row in self.failure_log()[logged:]], ['skill'])

    # The leases

    def test_resume_waits_for_the_curation_and_the_layer_lease(self):
        self.stop()
        asked = self.command()
        before = self.tree()
        for name, kind in (('curation.lock', 'curation'), ('layer.lock', 'layer')):
            with self.subTest(kind=kind), self.held(name, kind), \
                    mock.patch.object(resume_command, 'WAIT', 0.2), self.launches() as calls:
                started = clock.now()
                value = self.command(asked['confirm'])
                self.assertLess(clock.now() - started, 5)
                self.assertEqual((value['outcome'], value['code']), ('failed', 'lock-busy'))
                self.assertEqual((self.tree(), calls), (before, []))
        self.assertEqual(self.memory.held, [])

    def test_the_stop_is_cleared_under_both_leases_and_the_worker_starts_after_them(self):
        self.stop()
        asked = self.command()
        seen = {}
        update = revision_io.update_progress

        def recorded(memory, root, *args, **kwargs):
            seen['update'] = sorted(lease.path.name for lease in memory.held)
            return update(memory, root, *args, **kwargs)

        def popen(command, **options):
            seen['launch'] = list(self.memory.held)
            return types.SimpleNamespace(pid=0)
        with mock.patch.object(revision_io, 'update_progress', side_effect=recorded), \
                mock.patch.object(worker_launch.subprocess, 'Popen', side_effect=popen):
            self.command(asked['confirm'])
        self.assertEqual(seen, {'update': ['curation.lock', 'layer.lock'], 'launch': []})


class ResumeRunnerTest(unittest.TestCase):
    reset_store, snapshot = commands_fixture.CommandsTest.reset_store, commands_fixture.CommandsTest.snapshot

    def setUp(self):
        commands_fixture.CommandsTest.setUp(self)

    def test_the_runner_answers_resume_as_not_implemented(self):
        before = self.snapshot()
        for argv in (['resume'], ['resume', '--confirm', 'abcdefgh']):
            with self.subTest(argv=argv):
                value, status = commands.run(['--folder', str(self.project)] + argv)
                self.assertEqual((value['command'], value['code'], value['data'], status),
                                 ('resume', 'internal', {'error': 'NotImplementedError'}, 1))
                self.assertIn('not implemented', value['say'])
        after = self.snapshot()
        self.assertEqual({name for name in after if not name.startswith('logs/')},
                         {name for name in before if not name.startswith('logs/')})


if __name__ == '__main__':
    unittest.main()
