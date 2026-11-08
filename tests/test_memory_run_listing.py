"""TASK-104: the runs command (API-152) on fabricated format-2 stores.

The runner does not accept `runs` before the 0.3.0 activation, so these tests
call the handler as the runner will, after its gates, with the format-2 store
binding. Run logs are made one apply at a time, as the workers add them, and
the curation record holds the fence that their applies left.
"""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import clock, commands, configuration, format2, item_types, run_listing, run_log
import test_memory_state_edits as edits_fixture
from test_memory_curator_answers import AT, DEVICE, OTHER, Turns, saved
from test_memory_fence_plan import PROGRESS
from test_memory_run_log import progress

EPOCH = PROGRESS['fence']['epoch']
WHEN = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
SHA = 'a' * 64


def ident(prefix, number):
    return '%s_%012d' % (prefix, number)


def at(hours=0, days=0):
    """A TBL-121 time this long before WHEN."""
    moment = WHEN - timedelta(hours=hours, days=days)
    return moment.strftime('%Y-%m-%dT%H:%M:%S.000Z')


def status(item, before, after, by=None):
    after = {'status': after}
    if by is not None:
        after['superseded_by'] = by
    return {'item': item, 'before': {'status': before}, 'after': after}


def line(line_id, op, generation, part='decisions', history=True):
    place = [part, 0, '', '']
    return {'line': line_id, 'op': op, 'generation': generation,
            'history': [EPOCH, generation, line_id, SHA] if history else None,
            'before': [] if op == 'added' else place, 'after': place}


def objects(effects):
    """The namespaced objects that an apply's effects change (TBL-121)."""
    keys = {'item:' + item for item in effects.get('saved', ())}
    keys |= {'item:' + entry['item'] for field in ('statuses', 'merges') for entry in effects.get(field, ())}
    keys |= {'pin:' + entry['item'] for entry in effects.get('pins', ())}
    keys |= {'candidate:' + entry['candidate'] for entry in effects.get('conflicts', ())}
    keys |= {'line:' + entry['line'] for entry in effects.get('lines', ())}
    return keys


class Fabric:
    """Run logs added one apply at a time, and the fence that their applies leave (TBL-009)."""

    def __init__(self):
        self.generation = PROGRESS['fence']['generation']
        self.revisions = dict(PROGRESS['fence']['revisions'])

    def run(self, run, when, *applies, kind='curate', device=DEVICE, undoes='', epoch=None):
        log = run_log.start(run, kind, when, device, undoes)
        for effects in applies:
            log = self.apply(log, when, effects, epoch)
        return log

    def apply(self, log, when, effects, epoch=None):
        self.generation += 1
        generation = self.generation
        effects = effects(generation) if callable(effects) else dict(effects)
        changed = sorted(objects(effects))
        effects['revisions'] = [{'id': key, 'before': self.revisions.get(key), 'after': generation}
                                for key in changed]
        self.revisions.update(dict.fromkeys(changed, generation))
        self.revisions['run:' + log['id']] = generation
        reservation = progress(generation, self.revisions)
        if epoch is not None:
            reservation['fence']['epoch'] = epoch
        return run_log.add(log, reservation, when, effects)

    def progress(self):
        return progress(self.generation, self.revisions)


class RunListingTest(unittest.TestCase):
    def setUp(self):
        self.fixture = edits_fixture.StateEditsTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.project = self.fixture.project
        self.folder = self.project / 'runs'
        self.folder.mkdir()
        self.fabric = Fabric()
        self.turns = Turns()
        self.said = self.turns.say('user', 'Keep the four hooks in one script.')

    def write(self, *logs):
        for log in logs:
            (self.folder / (log['id'] + '.json')).write_bytes(run_log.log_bytes(log))

    def fence(self):
        self.fixture.progress_path.write_bytes(format2.curation_bytes(self.fabric.progress()))

    def record(self, item, title='Saved decision'):
        value = saved('decision', self.said, item=item)
        value['title'] = title
        self.fixture.store(value)
        return value

    def command(self, limit=None, memory=None, project='sample', days=100):
        arguments = {'folder': str(self.fixture.root)}
        if limit is not None:
            arguments['limit'] = limit
        context = commands.Context('runs', arguments, None, memory or self.fixture.memory)
        context.project = types.SimpleNamespace(name=project)
        context.configuration = configuration.prepare({'retention': {'days': days}})
        value = run_listing.runs(context, when=WHEN)
        commands.validate_result(value, 'runs')
        return value

    def tree(self):
        return {path.relative_to(self.fixture.root).as_posix(): path.read_bytes()
                for path in sorted(self.fixture.root.rglob('*')) if path.is_file() and path.suffix != '.lock'
                and not path.relative_to(self.fixture.root).as_posix().startswith('logs/')}

    def link(self, alias, target):
        """A symbolic link, or False where this system does not let the test make one."""
        try:
            os.symlink(str(target), str(alias))
        except (OSError, NotImplementedError):
            return False
        return True

    def listed(self, value):
        return [entry['run'] for entry in value['data']['runs']]

    def make_runs(self):
        """Thirteen eligible runs, oldest first, and logs that must not be listed."""
        fabric, write = self.fabric, self.write
        names = {}
        # Not listed: past retention, first apply only, another epoch, another device.
        expired = fabric.run(ident('r', 90), at(days=101), {'saved': [ident('i', 90)]})
        first = fabric.run(ident('r', 91), at(hours=30), {'saved': [ident('i', 91)]})
        write(expired, first)
        fabric.apply(first, at(hours=30), {'saved': [ident('i', 92)]})  # its log write failed
        other_epoch = fabric.run(ident('r', 93), at(hours=29), {'saved': [ident('i', 93)]}, epoch='f' * 32)
        other_device = fabric.run(ident('r', 94), at(hours=28), {'saved': [ident('i', 94)]}, device=OTHER)
        write(other_epoch, other_device)
        (self.folder / (ident('r', 95) + '.json')).write_bytes(b'{"id": ')
        (self.folder / 'notes.txt').write_bytes(b'kept')
        # Listed, oldest first: one whose only item changed later, eight plain runs and four newer ones.
        names['old'] = fabric.run(ident('r', 1), at(hours=13), {'saved': [ident('i', 1)]})
        plain = [fabric.run(ident('r', 10 + n), at(hours=12 - n), {'saved': [ident('i', 10 + n)]})
                 for n in range(8)]
        names['partial'] = fabric.run(ident('r', 2), at(hours=4), {'saved': [ident('i', 2), ident('i', 3)]})
        names['later'] = fabric.run(ident('r', 3), at(hours=3), {'statuses': [
            status(ident('i', 1), 'current', 'withdrawn'), status(ident('i', 3), 'current', 'withdrawn')]})
        merged, first_item, second_item = ident('i', 40), ident('i', 41), ident('i', 42)
        pin = {'on': True, 'at': AT, 'device': DEVICE}
        names['consolidate'] = fabric.run(
            ident('r', 4), at(hours=2),
            {'saved': [merged], 'merges': [{'item': merged, 'merged': [first_item, second_item]}],
             'statuses': [status(first_item, 'current', 'superseded', merged),
                          status(second_item, 'current', 'superseded', merged)],
             'pins': [{'item': first_item, 'from': pin, 'to': None, 'place': [0, None]},
                      {'item': merged, 'from': None, 'to': pin, 'place': [None, 0]}]},
            lambda generation: {'lines': [line(ident('s', 1), 'recited', generation),
                                          line(ident('s', 2), 'added', generation, history=False)],
                                'conflicts': [{'candidate': ident('c', 1), 'from': 'absent', 'to': 'open'}]},
            lambda generation: {'lines': [line(ident('s', 1), 'changed', generation)]},
            kind='consolidate')
        names['titles'] = fabric.run(ident('r', 5), at(hours=1), {'saved': [ident('i', 50 + n) for n in range(7)]})
        write(names['old'], *plain, names['partial'], names['later'], names['consolidate'], names['titles'])
        # A copy of a listed log under another run's name is not a log of that run.
        shutil.copyfile(str(self.folder / (names['titles']['id'] + '.json')), str(self.folder / (ident('r', 96) + '.json')))
        (self.folder / (names['old']['id'] + '.json.bak')).write_bytes(b'{')
        # A log reached through a link is not read, even when it is whole and current.
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(outside), True)
        linked = fabric.run(ident('r', 97), at(hours=0.5), {'saved': [ident('i', 97)]})
        (outside / 'log.json').write_bytes(run_log.log_bytes(linked))
        self.link(self.folder / (linked['id'] + '.json'), outside / 'log.json')
        # Titles: forgotten, missing, linked, then three that show and one past the three.
        self.record(merged, 'Merged rule')
        (self.project / 'layer/tombstones' / (ident('i', 50) + '.json')).write_bytes(b'{}')
        self.record(ident('i', 50), 'Forgotten')
        (outside / 'item.json').write_bytes(item_types.item_bytes(saved('decision', self.said, item=ident('i', 52))))
        self.link(self.project / 'layer/items' / (ident('i', 52) + '.json'), outside / 'item.json')
        shown = [self.record(ident('i', 53), 'Plan\tB'), self.record(ident('i', 54)), self.record(ident('i', 55))]
        self.record(ident('i', 56), 'Past the three')
        self.fence()
        names['plain'] = plain
        return names, shown

    def test_tc367_recent_complete_runs_newest_first_with_default_and_explicit_limits(self):
        names, shown = self.make_runs()
        newest = [names[key]['id'] for key in ('titles', 'consolidate', 'later', 'partial')]
        newest += [log['id'] for log in reversed(names['plain'])]
        everything = newest + [names['old']['id']]
        self.assertEqual(len(everything), 13)
        value = self.command()
        self.assertEqual((value['outcome'], value['code'], value['say']),
                         ('done', 'ok', 'The 10 newest of 13 complete retained runs.'))
        self.assertEqual((self.listed(value), value['data']['limit'], value['data']['project']),
                         (everything[:10], 10, 'sample'))
        for limit, say in ((1, 'The newest of 13 complete retained runs.'),
                           (12, 'The 12 newest of 13 complete retained runs.'),
                           (13, '13 complete retained runs, newest first.'),
                           (200, '13 complete retained runs, newest first.')):
            with self.subTest(limit=limit):
                value = self.command(limit)
                self.assertEqual((self.listed(value), value['say'], value['data']['limit']),
                                 (everything[:limit], say, limit))
        lines = {entry['run']: entry for entry in self.command(200)['data']['runs']}
        # Each object is counted once, though a line changed in two applies has two entries.
        consolidate = lines[names['consolidate']['id']]
        self.assertEqual(len(names['consolidate']['lines']), 3)
        self.assertEqual((consolidate['kind'], consolidate['at'], consolidate['ended'], consolidate['counts']),
                         ('consolidate', at(hours=2), at(hours=2),
                          dict(saved=1, statuses=2, merges=1, lines=2, pins=2, conflicts=1)))
        self.assertEqual([entry['title'] for entry in consolidate['saved']], ['Merged rule'])
        # At most three titles, in the run's order, from records that survive and are not forgotten.
        titles = lines[names['titles']['id']]
        self.assertEqual(titles['counts'], dict(saved=7, statuses=0, merges=0, lines=0, pins=0, conflicts=0))
        self.assertEqual(titles['saved'], [run_listing.list_line(value) for value in shown])
        self.assertEqual([entry['title'] for entry in titles['saved']], ['Plan B', 'Saved decision', 'Saved decision'])
        self.assertEqual(titles['saved'][0], {'item': ident('i', 53), 'kind': 'decision', 'speaker': 'user',
                                              'date': AT[:10], 'title': 'Plan B'})
        self.assertEqual(lines[names['later']['id']]['counts']['statuses'], 2)
        # A run whose only object changed later has nothing left to undo; one with an object left has.
        self.assertEqual({run: entry['undoable'] for run, entry in lines.items() if not entry['undoable']},
                         {names['old']['id']: False})
        self.assertTrue(lines[names['partial']['id']]['undoable'])

    def test_tc367_a_listed_run_follows_the_example_and_reads_what_the_runner_will_pass(self):
        run = self.fabric.run(ident('r', 1), at(hours=1), {'saved': [ident('i', 1)]})
        self.write(run)
        self.fence()
        self.record(ident('i', 1), 'Curation runs in one detached background process')
        value = self.command()
        self.assertEqual((value['outcome'], value['code'], value['say']),
                         ('done', 'ok', 'One complete retained run, newest first.'))
        self.assertEqual(value['data'], {'project': 'sample', 'limit': 10, 'runs': [{
            'run': run['id'], 'kind': 'curate', 'at': at(hours=1), 'ended': at(hours=1),
            'counts': dict(saved=1, statuses=0, merges=0, lines=0, pins=0, conflicts=0),
            'saved': [{'item': ident('i', 1), 'kind': 'decision', 'speaker': 'user', 'date': AT[:10],
                       'title': 'Curation runs in one detached background process'}],
            'undoable': True}]})

    def test_tc368_no_complete_retained_run_lists_none(self):
        none = {'project': 'sample', 'runs': [], 'limit': 10}
        # No run folder, an empty one, and one with only logs that cannot be listed.
        self.folder.rmdir()
        self.fence()
        cases = [('no folder', lambda: None), ('empty', self.folder.mkdir)]

        def unlisted():
            self.write(self.fabric.run(ident('r', 1), at(days=101), {'saved': [ident('i', 1)]}))
            (self.folder / (ident('r', 2) + '.json')).write_bytes(b'{')
            self.fence()
        cases.append(('unlisted', unlisted))
        for name, prepare in cases:
            with self.subTest(case=name):
                prepare()
                value = self.command()
                self.assertEqual((value['outcome'], value['code'], value['say'], value['data']),
                                 ('nothing', 'ok', 'No complete retained runs.', none))
        # A project without a folder yet, and a project being deleted, list none either.
        value = self.command(project='other')
        self.assertEqual((value['outcome'], value['data']['runs'], value['data']['project']), ('nothing', [], 'other'))
        self.write(self.fabric.run(ident('r', 3), at(hours=1), {'saved': [ident('i', 3)]}))
        self.fence()
        self.assertEqual(len(self.command()['data']['runs']), 1)
        (self.project / 'layer/deleted.json').write_bytes(b'{}')
        value = self.command()
        self.assertEqual((value['outcome'], value['say'], value['data']), ('nothing', 'No complete retained runs.', none))

    def test_an_unreadable_curation_record_lists_no_run_and_restores_nothing(self):
        self.write(self.fabric.run(ident('r', 1), at(hours=1), {'saved': [ident('i', 1)]}))
        self.fence()
        good = self.fixture.progress_path.read_bytes()
        backup = self.fixture.progress_path.with_name('curation.json.bak')
        for name, primary, copy in (('damaged', b'{', None), ('only the backup reads', b'{', good),
                                    ('missing', None, None)):
            with self.subTest(case=name):
                self.fixture.progress_path.unlink()
                if primary is not None:
                    self.fixture.progress_path.write_bytes(primary)
                if copy is not None:
                    backup.write_bytes(copy)
                before = self.tree()
                with mock.patch.object(self.fixture.memory, 'failure') as failure:
                    value = self.command()
                self.assertEqual((value['outcome'], value['code'], value['data']['runs']), ('nothing', 'ok', []))
                self.assertEqual(value['say'], run_listing.SAY['unreadable'])
                self.assertEqual([call.args[1] for call in failure.call_args_list], ['skill'])
                self.assertEqual(self.tree(), before)
                if backup.exists():
                    backup.unlink()
                self.fixture.progress_path.write_bytes(good)
        self.assertEqual(len(self.command()['data']['runs']), 1)

    def test_a_limit_outside_1_to_200_is_a_usage_error(self):
        for limit in (0, 201, -1, True, '3', 2.0):
            with self.subTest(limit=limit):
                value = self.command(limit)
                self.assertEqual((value['outcome'], value['code']), ('refused', 'usage'))

    def test_a_layer_lease_held_elsewhere_answers_lock_busy(self):
        self.write(self.fabric.run(ident('r', 1), at(hours=1), {'saved': [ident('i', 1)]}))
        self.fence()
        # Another process holds the project's layer lease, as a curator's apply would.
        code = ("import sys,time;sys.path.insert(0,sys.argv[1]);from pathlib import Path;"
                "from memory_lib import locks;lease=locks.Lock(Path(sys.argv[2]),'layer',sys.argv[3]);"
                "lease.acquire(time.monotonic()+5);print('ready',flush=True);"
                "sys.stdin.readline();lease.release()")
        child = subprocess.Popen([sys.executable, '-B', '-c', code,
                                  str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'),
                                  str(self.project / 'layer.lock'), DEVICE],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), 'ready')
            with mock.patch.object(run_listing, 'WAIT', 0.2):
                started = clock.now()
                value = self.command()
                self.assertLess(clock.now() - started, 5)
            self.assertEqual((value['outcome'], value['code']), ('failed', 'lock-busy'))
        finally:
            child.communicate('\n', timeout=30)
        self.assertEqual(child.returncode, 0)
        self.assertEqual(len(self.command()['data']['runs']), 1)

    def test_listing_changes_no_file(self):
        self.make_runs()
        before = self.tree()
        for limit in (None, 1, 200):
            self.command(limit)
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.fixture.memory.held, [])

    def test_the_runner_still_answers_usage_for_runs_before_activation(self):
        before = self.tree()
        for argv in (['runs'], ['runs', '--limit', '5'], ['--folder', str(self.fixture.root), 'runs']):
            with self.subTest(argv=argv):
                answer, status = commands.run(argv, handlers={'runs': run_listing.runs})
                self.assertEqual((answer['command'], answer['code'], status), ('none', 'usage', 2))
        self.assertNotIn('runs', commands.COMMANDS)
        self.assertEqual(self.tree(), before)


if __name__ == '__main__':
    unittest.main()
