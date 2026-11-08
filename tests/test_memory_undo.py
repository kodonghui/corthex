"""TASK-105 and TASK-106: the undo command's preview and confirmation (API-153) on format-2 stores.

TC-369, TC-370, TC-372 and the handler's part of TC-362 and TC-392. The runner
does not hand `undo` to the handler before the 0.3.0 activation, so these tests
call it as the runner will, after its gates, with the format-2 store binding.
The runs come from real curations against the local test server of the
curation worker's tests; no provider is called. The confirmed inverse
(TASK-107) has its own tests in test_memory_undo_effects; here a stand-in
records what the handler passes it and the leases that it holds.
"""
import contextlib
import json
import subprocess
import sys
import types
import unittest
from datetime import timedelta
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import clock, commands, configuration, fence_plan, revision_io, run_listing, run_log, undo_command
from memory_lib import undo_plan
from test_memory_curator_answers import answer, change, quote
import test_memory_curation_worker as worker_fixture
from test_memory_state_edits import added, changed, edits

DEVICE, WHEN = worker_fixture.DEVICE, worker_fixture.WHEN
OTHER = 'd_zyxwvtsrqpnm'
HOOKS = 'Keep the four hooks in one script'
SAID = HOOKS + ', and keep the raw logs on this device.'
COUNTS = dict.fromkeys(('saved', 'statuses', 'merges', 'lines', 'pins', 'conflicts'), 0)


class UndoStore:
    """A format-2 project whose runs come from real curations, and the undo command run as the runner will run it."""

    def setUp(self):
        self.fixture = worker_fixture.CurationWorkerTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.memory = self.fixture.root, self.fixture.memory

    def curate(self, prompt, build):
        """One curation of a new turn whose answer `build(said)` makes; the run that it logged."""
        said, _ = self.fixture.one_turn(prompt, 'Noted.')
        self.fixture.server.answers = [build(said)]
        (attempt,) = self.fixture.curate().attempts
        self.assertEqual((attempt.record['result'], attempt.record['dropped']), ('ok', 0))
        return attempt.record['run']

    def first_run(self):
        """A curation that saves one decision and adds one decisions line that cites it."""
        run = self.curate(SAID, lambda said: answer(
            change(quote(said, HOOKS), kind='decision', title='One script'),
            state=edits(add=[added('decisions', 'One script serves the hooks.', changes=[1])])))
        log = run_log.read(self.root, run)
        (item,), (line,) = log['saved'], [entry['line'] for entry in log['lines']]
        return run, item, line

    def touch(self, *keys):
        """A change that no run log names, as a forget's or an apply's whose log write failed: new revisions."""
        deadline = clock.now() + 30
        with self.memory.lease(self.root / 'layer.lock', 'layer', deadline):
            progress = revision_io.read(self.memory, self.root, deadline)
            revision_io.reserve(self.memory, self.root, fence_plan.snapshot(progress), list(keys), deadline)

    def command(self, run, code=None, memory=None, project='sample', days=100, when=WHEN, arguments=None):
        arguments = {'folder': str(self.root), 'run': run} if arguments is None else arguments
        context = commands.Context('undo', arguments, code, memory or self.memory)
        context.project = types.SimpleNamespace(name=project)
        context.record = {'device': DEVICE}
        context.configuration = configuration.prepare({'retention': {'days': days}})
        value = undo_command.undo(context, when=when)
        commands.validate_result(value, 'undo')
        return value

    def listing(self, days=100, when=WHEN):
        context = commands.Context('runs', {'folder': str(self.root)}, None, self.memory)
        context.project = types.SimpleNamespace(name='sample')
        context.configuration = configuration.prepare({'retention': {'days': days}})
        return run_listing.runs(context, when=when)['data']['runs']

    @contextlib.contextmanager
    def inverse(self):
        """A stand-in for the inverse that records each plan and the leases held when it is called."""
        calls = []

        def apply(memory, root, plan, snap, deadline):
            self.assertEqual(snap.log['id'], plan.data['run'])
            calls.append((plan, [lease.path.name for lease in memory.held]))
            return commands.result('undo', dict(plan.data, undo='r_' + '0' * 12), 'Undone.')
        with mock.patch.object(undo_command, '_apply', side_effect=apply):
            yield calls

    @contextlib.contextmanager
    def held(self, name, kind):
        """Another process holding one of the project's leases, as a curation or an apply would."""
        code = ("import sys,time;sys.path.insert(0,sys.argv[1]);from pathlib import Path;"
                "from memory_lib import locks;lease=locks.Lock(Path(sys.argv[2]),sys.argv[3],sys.argv[4]);"
                "lease.acquire(time.monotonic()+5);print('ready',flush=True);"
                "sys.stdin.readline();lease.release()")
        child = subprocess.Popen([sys.executable, '-B', '-c', code,
                                  str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'),
                                  str(self.root / name), kind, DEVICE],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), 'ready')
            with mock.patch.object(undo_command, 'WAIT', 0.2):
                yield
        finally:
            child.communicate('\n', timeout=30)
        self.assertEqual(child.returncode, 0)


class UndoTest(UndoStore, unittest.TestCase):
    # TC-369

    def test_tc369_the_preview_changes_nothing_and_only_its_own_code_goes_on(self):
        run, item, line = self.first_run()
        before = self.fixture.snapshot()
        with self.inverse() as calls:
            preview = self.command(run)
            self.assertEqual((preview['outcome'], preview['code']), ('confirm', 'ok'))
            self.assertEqual({key: value for key, value in preview['data'].items() if key != 'binding'},
                             {'project': 'sample', 'run': run, 'changes': dict(COUNTS, saved=1, lines=1),
                              'kept': []})
            self.assertEqual(preview['say'], 'Undoing this run, as a new run, makes 1 saved item undone and puts '
                                             '1 state line back as it was.')
            # Saying no sends no code; asking again shows the same preview with the same code.
            again = self.command(run)
            self.assertEqual((again['data'], again['confirm']), (preview['data'], preview['confirm']))
            # A code of another preview, or of this preview for another argument, is stale and applies nothing.
            for code, run_argument in (('0' * 8, run), (preview['confirm'], run.upper())):
                with self.subTest(code=code, run=run_argument):
                    stale = self.command(run_argument, code=code)
                    self.assertNotEqual(stale['outcome'], 'done')
                    if run_argument == run:
                        self.assertEqual((stale['outcome'], stale['code'], stale['data']),
                                         ('confirm', 'confirm-stale', preview['data']))
            self.assertEqual((calls, self.fixture.snapshot(), self.memory.held), ([], before, []))
            done = self.command(run, code=preview['confirm'])
        self.assertEqual((done['outcome'], done['say']), ('done', 'Undone.'))
        ((plan, leases),) = calls
        # The inverse goes on under the curation lease and then the layer lease, with the plan that was shown.
        self.assertEqual(leases, ['curation.lock', 'layer.lock'])
        self.assertEqual((plan.reversed, plan.items, plan.lines, plan.data),
                         ({'item:' + item, 'line:' + line}, {item: {'status': 'undone'}}, {line: None},
                          preview['data']))
        self.assertEqual((self.fixture.snapshot(), self.memory.held), (before, []))

    # TC-370

    def test_tc370_a_run_that_cannot_be_undone_is_not_found_and_the_recent_runs_are_listed(self):
        run, _, _ = self.first_run()
        recent = self.listing()
        self.assertEqual([value['run'] for value in recent], [run])
        path = run_log.path(self.root, run)
        good, log = path.read_bytes(), run_log.read(self.root, run)

        def rewrite(**fields):
            path.write_bytes(run_log.log_bytes(dict(log, **fields)))
        cases = [
            ('unknown', 'r_' + 'z' * 12, None, recent),
            ('not an ID', '../runs/' + run, None, recent),
            ('upper case', run.upper(), None, recent),
            ('another device', run, lambda: rewrite(device=OTHER), []),
            ('another epoch', run, lambda: rewrite(epoch='f' * 32), []),
            ('damaged', run, lambda: path.write_bytes(b'{'), []),
            ('past retention', run, None, []),
        ]
        for name, argument, prepare, runs in cases:
            with self.subTest(case=name):
                if prepare is not None:
                    prepare()
                when = WHEN + timedelta(days=101) if name == 'past retention' else WHEN
                before = self.fixture.snapshot()
                with self.inverse() as calls:
                    for code in (None, 'ABCDEFGH'):
                        value = self.command(argument, code=code, when=when)
                        self.assertEqual((value['outcome'], value['code'], value['say']),
                                         ('refused', 'run-not-found', undo_command.SAY['missing']))
                        self.assertEqual(value['data'], {'project': 'sample', 'run': argument, 'runs': runs})
                self.assertEqual((calls, self.fixture.snapshot(), self.memory.held), ([], before, []))
                path.write_bytes(good)
        self.assertEqual(self.command(run)['outcome'], 'confirm')
        # A later apply of the run whose log write failed leaves a whole file that no longer ends the run.
        self.touch('run:' + run)
        value = self.command(run)
        self.assertEqual((value['code'], value['data']['runs']), ('run-not-found', []))

    def test_a_project_without_a_folder_being_deleted_or_with_an_unreadable_record_has_no_run(self):
        run, _, _ = self.first_run()
        value = self.command(run, project='other')
        self.assertEqual((value['code'], value['data']), ('run-not-found', {'project': 'other', 'run': run,
                                                                          'runs': []}))
        progress = self.root / 'curation.json'
        good = progress.read_bytes()
        progress.write_bytes(b'{')
        before = self.fixture.snapshot()
        with mock.patch.object(self.memory, 'failure') as failure:
            value = self.command(run)
        self.assertEqual((value['code'], value['say'], value['data']['runs']),
                         ('run-not-found', undo_command.SAY['unreadable'], []))
        self.assertEqual([call.args[1] for call in failure.call_args_list], ['skill'])
        self.assertEqual(self.fixture.snapshot(), before)
        progress.write_bytes(good)
        (self.root / 'layer/deleted.json').write_bytes(b'{}')
        value = self.command(run)
        self.assertEqual((value['code'], value['say'], value['data']['runs']),
                         ('run-not-found', undo_command.SAY['missing'], []))

    # TC-362

    def test_tc362_a_run_whose_every_change_is_kept_answers_nothing_and_names_the_later_run(self):
        first = self.curate(SAID, lambda said: answer(change(quote(said, HOOKS), title='Hooks')))
        (item,) = run_log.read(self.root, first)['saved']
        second = self.curate('Use two scripts for the hooks.', lambda said: answer(
            change(quote(said, 'Use two scripts'), action='replace', targets=[item], title='Two scripts')))
        before = self.fixture.snapshot()
        with self.inverse() as calls:
            for code in (None, 'ABCDEFGH'):
                value = self.command(first, code=code)
                self.assertEqual((value['outcome'], value['code'], value['say']),
                                 ('nothing', 'ok', undo_plan.SAY['nothing']))
                self.assertEqual(value['data'], {'project': 'sample', 'run': first, 'kept': [
                    {'target': 'item:' + item, 'by': second, 'why': 'later-run'}]})
        self.assertEqual((calls, self.fixture.snapshot()), ([], before))
        # The later run is listed and can be undone: the item comes back and its replacement is undone.
        self.assertEqual({value['run']: value['undoable'] for value in self.listing()}, {second: True, first: False})
        preview = self.command(second)
        self.assertEqual(preview['data']['changes'], dict(COUNTS, saved=1, statuses=1))

    def test_a_forgotten_item_and_a_line_that_cites_it_stay_forgotten(self):
        run, item, line = self.first_run()
        other = worker_fixture.C2Store(self.fixture.folder, expected_device=DEVICE)
        self.fixture.advance(other, self.fixture.items()[item])
        value = self.command(run)
        self.assertEqual((value['outcome'], value['data']['kept']), ('nothing', [
            {'target': 'item:' + item, 'by': '', 'why': 'forgotten'},
            {'target': 'line:' + line, 'by': '', 'why': 'forgotten'}]))

    def test_a_replaced_decision_and_the_line_that_its_replacement_made_stale_are_both_kept(self):
        run, item, line = self.first_run()
        later = self.curate('Use two scripts for the hooks.', lambda said: answer(
            change(quote(said, 'Use two scripts for the hooks'), action='replace', targets=[item], kind='decision',
                   title='Two scripts')))
        value = self.command(run)
        self.assertEqual((value['outcome'], value['data']['kept']), ('nothing', [
            {'target': 'item:' + item, 'by': later, 'why': 'later-run'},
            {'target': 'line:' + line, 'by': later, 'why': 'later-run'}]))

    # TC-372

    def test_tc372_a_code_goes_stale_when_what_the_undo_depends_on_changes_and_only_then(self):
        # A fact and a progress line that cites it; a replaced decision would also make its line stale.
        run = self.curate(SAID, lambda said: answer(
            change(quote(said, HOOKS), title='Hooks'),
            state=edits(add=[added('progress', 'The hooks share one script.', changes=[1])])))
        log = run_log.read(self.root, run)
        (item,), (line,) = log['saved'], [entry['line'] for entry in log['lines']]
        preview = self.command(run)
        self.assertEqual(preview['data']['changes'], dict(COUNTS, saved=1, lines=1))
        # A later curation that saves an unrelated fact changes nothing that this undo reads.
        self.curate('The tests run on three systems.', lambda said: answer(
            change(quote(said, 'The tests run on three systems'), title='Three systems')))
        with self.inverse() as calls:
            self.assertEqual(self.command(run, code=preview['confirm'])['outcome'], 'done')
        self.assertEqual(len(calls), 1)
        # The binding holds the run log file's bytes, beyond the fields that the plan reads.
        path = run_log.path(self.root, run)
        good = path.read_bytes()
        path.write_bytes(run_log.log_bytes(dict(log, turns={name: [1, 1] for name in log['turns']})))
        rewritten = self.command(run, code=preview['confirm'])
        self.assertEqual(rewritten['code'], 'confirm-stale')
        self.assertEqual({key: value for key, value in rewritten['data'].items() if key != 'binding'},
                         {key: value for key, value in preview['data'].items() if key != 'binding'})
        path.write_bytes(good)
        # A later replacement of the saved fact keeps it, so the code is stale and the new preview says why.
        third = self.curate('Use two scripts for the hooks.', lambda said: answer(
            change(quote(said, 'Use two scripts for the hooks'), action='replace', targets=[item],
                   title='Two scripts')))
        with self.inverse() as calls:
            stale = self.command(run, code=preview['confirm'])
            self.assertEqual((stale['outcome'], stale['code']), ('confirm', 'confirm-stale'))
            self.assertEqual(stale['data']['kept'], [{'target': 'item:' + item, 'by': third, 'why': 'later-run'}])
            self.assertEqual(stale['data']['changes'], dict(COUNTS, lines=1))
            self.assertNotEqual(stale['data']['binding'], preview['data']['binding'])
            self.assertEqual(calls, [])
            done = self.command(run, code=stale['confirm'])
        self.assertEqual(done['outcome'], 'done')
        ((plan, _),) = calls
        self.assertEqual((plan.reversed, plan.lines), ({'line:' + line}, {line: None}))
        # The kept item changing again, where no log names the change, keeps the counts and reasons but not the code.
        self.touch('item:' + item)
        first = self.command(run)
        self.touch('item:' + item)
        again = self.command(run, code=first['confirm'])
        self.assertEqual(again['code'], 'confirm-stale')
        self.assertEqual(first['data']['kept'], [{'target': 'item:' + item, 'by': '', 'why': 'later-unlogged-change'}])
        self.assertEqual({key: value for key, value in again['data'].items() if key != 'binding'},
                         {key: value for key, value in first['data'].items() if key != 'binding'})

    # TC-392 at the handler: a line whose version before the run cannot be read is kept

    def test_tc392_a_changed_line_needs_its_history_and_a_damaged_history_keeps_it(self):
        run, item, line = self.first_run()
        second = self.curate('The script is hook.py now.', lambda said: answer(
            change(quote(said, 'The script is hook.py now'), title='Script name'),
            state=edits(change=[changed(line, 'One script, hook.py, serves the hooks.', [item],
                                        why='Named the script.')])))
        preview = self.command(second)
        self.assertEqual((preview['data']['changes'], preview['data']['kept'], preview['data']['reasons']),
                         (dict(COUNTS, saved=1, lines=1), [], ['Named the script.']))
        history = self.root / 'state-history.jsonl'
        good = history.read_bytes()
        history.write_bytes(good[:-5])
        with self.inverse() as calls:
            stale = self.command(second, code=preview['confirm'])
        self.assertEqual((stale['code'], stale['data']['kept'], stale['data']['changes']),
                         ('confirm-stale', [{'target': 'line:' + line, 'by': '', 'why': 'history-unavailable'}],
                          dict(COUNTS, saved=1)))
        self.assertNotIn('reasons', stale['data'])
        self.assertEqual(calls, [])
        history.write_bytes(good)
        self.assertEqual(self.command(second)['data'], preview['data'])

    # Locks and arguments

    def test_a_preview_needs_only_the_layer_lease_and_a_busy_lease_answers_lock_busy(self):
        run, _, _ = self.first_run()
        preview = self.command(run)
        with self.inverse() as calls:
            # A curation holds the curation lease: the preview still reads, but the inverse cannot go on.
            with self.held('curation.lock', 'curation'):
                self.assertEqual(self.command(run)['data'], preview['data'])
                started = clock.now()
                busy = self.command(run, code=preview['confirm'])
                self.assertLess(clock.now() - started, 5)
            self.assertEqual((busy['outcome'], busy['code']), ('failed', 'lock-busy'))
            # An apply holds the layer lease: neither reads.
            with self.held('layer.lock', 'layer'):
                for code in (None, preview['confirm']):
                    busy = self.command(run, code=code)
                    self.assertEqual((busy['outcome'], busy['code']), ('failed', 'lock-busy'))
            self.assertEqual(calls, [])
        self.assertEqual(self.memory.held, [])

    def test_a_run_argument_outside_the_schema_is_usage(self):
        for arguments in ({'folder': str(self.root)}, {'folder': str(self.root), 'run': ''},
                          {'folder': str(self.root), 'run': 'r' * 201}, {'folder': str(self.root), 'run': 7}):
            with self.subTest(arguments=str(arguments)[-20:]):
                value = self.command(None, arguments=arguments)
                self.assertEqual((value['outcome'], value['code']), ('refused', 'usage'))

    def test_the_examples_say_what_the_handler_says_and_name_targets_as_the_run_log_does(self):
        valid = json.loads((ROOT / 'docs/06-api/memory-examples.json').read_text(encoding='utf-8'))['result']['valid']
        self.assertEqual(valid['undo-not-found']['say'], undo_command.SAY['missing'])
        self.assertEqual(valid['undo-keeps-later']['say'], undo_plan.SAY['nothing'])
        for entry in valid['undo-keeps-later']['data']['kept']:
            self.assertRegex(entry['target'], r'\A(item|pin|candidate|line):[a-z]_[0-9a-z]{12}\Z')
        asks = valid['undo-asks']
        plan = undo_plan.Plan(asks['data'], frozenset({'item:i_7f3k2m9q4x1v'}), {}, {}, {}, {})
        self.assertEqual(undo_plan.say(plan), asks['say'])
        run, _, _ = self.first_run()
        self.assertEqual(self.command(run, code='0' * 8)['say'], valid['undo-confirm-stale']['say'])

    def test_the_runner_still_answers_usage_for_undo_before_activation(self):
        before = self.fixture.snapshot()
        for argv in (['undo'], ['undo', '--run', 'r_0123456789ab'],
                     ['--folder', str(self.root), 'undo', 'r_0123456789ab']):
            with self.subTest(argv=argv):
                value, status = commands.run(argv, handlers={'undo': undo_command.undo})
                self.assertEqual((value['command'], value['code'], status), ('none', 'usage', 2))
        self.assertNotIn('undo', commands.COMMANDS)
        self.assertIn('undo', commands.ASKS)
        self.assertEqual(self.fixture.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
