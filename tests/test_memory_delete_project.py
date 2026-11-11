"""TASK-044: delete-project (API-026; SPEC-037) without sync, on fabricated format-2 stores.

TC-245 and TC-246. The runner does not hand `delete-project` to the handler
before the 0.3.0 activation, so these tests call it as the runner will, after
its gates, with the format-2 store binding. The worker of TC-245 runs in
another process against the local test server of the curation worker's tests;
no provider is called.
"""
from collections import Counter
import json
import multiprocessing
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
import types
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import clock, commands, delete_project_command, files, item_types, locks, raw_log
from memory_lib.worker_support import UnsafePath
from test_memory_curator_answers import answer, change, quote
import test_memory_curation_worker as worker_fixture

AT, DEVICE = worker_fixture.AT, worker_fixture.DEVICE
USAGE = b'{"at":"2026-11-08T09:00:00.000Z","model":"claude-haiku-5-5","result":"ok"}\n'


def lock_bytes(token):
    """A lock file as another process holds it (stage 05)."""
    return json.dumps({'pid': 1, 'device': DEVICE, 'at': AT, 'token': token}).encode('utf-8')


class DeleteStore:
    """Two projects of a format-2 store, `sample` and `other`, and the command run as the runner will run it."""

    def setUp(self):
        self.fixture = worker_fixture.CurationWorkerTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.folder, self.root, self.memory = self.fixture.folder, self.fixture.root, self.fixture.memory
        self.other = self.folder / 'projects/other'
        for name in ('raw', 'unprocessed', 'notices', 'runs', 'layer/items', 'layer/tombstones'):
            (self.other / name).mkdir(parents=True)
        other = worker_fixture.Raw('fixture-session-other')
        said, _ = other.turn('Keep the other project apart.', 'It stays apart.')
        (self.other / 'raw' / (other.name + '.jsonl')).write_bytes(other.data())
        kept = self.fixture.saved(said, 'Keep the other project apart')
        (self.other / 'layer/items' / (kept['id'] + '.json')).write_bytes(item_types.item_bytes(kept))
        for name in ('curation.json', 'state-history.jsonl', 'layer/state.json', 'layer/pins.json'):
            (self.other / name).write_bytes((self.root / name).read_bytes())
        (self.other / 'curation.lock').write_bytes(lock_bytes(secrets.token_hex(16)))
        self.configure()
        (self.folder / 'logs/usage-2026-11.jsonl').write_bytes(USAGE)

    def configure(self, **document):
        value = {'consent': {'at': AT, 'version': 1},
                 'projects': {'sample': {'enabled': True, 'since': AT, 'left_out': {'folders': ['tmp'], 'kinds': []}},
                              'other': {'enabled': True, 'since': AT}}}
        value.update(document)
        (self.folder / 'configuration.json').write_bytes(json.dumps(value).encode('utf-8'))

    def configuration(self):
        return json.loads((self.folder / 'configuration.json').read_bytes())

    def tree(self, folder):
        return {path.relative_to(folder).as_posix(): path.read_bytes()
                for path in sorted(folder.rglob('*')) if path.is_file()}

    # The store

    def items(self, *values, tombstoned=()):
        for value in values:
            (self.root / 'layer/items' / (value['id'] + '.json')).write_bytes(item_types.item_bytes(value))
        for value in tombstoned:
            (self.root / 'layer/items' / (value['id'] + '.json')).write_bytes(item_types.item_bytes(value))
            cited = value['quotes'][0]
            stone = dict(item=value['id'], project='sample', at=AT, device=DEVICE,
                         quotes=[{key: cited[key] for key in ('device', 'entry', 'log', 'start', 'end')}])
            (self.root / 'layer/tombstones' / (value['id'] + '.json')).write_bytes(item_types._raw(stone) + b'\n')

    def pins(self, *pins):
        (self.root / 'layer/pins.json').write_bytes(item_types.pins_bytes(
            {'pins': [dict(item=item, on=on, at=AT, device=DEVICE) for item, on in pins]}))

    def stocked(self):
        """Three items, one of them forgotten, two turns in one raw log with a damaged line, and one pin on."""
        said, answered = self.fixture.one_turn()
        first = self.fixture.saved(said, worker_fixture.HOOKS)
        second = self.fixture.saved(answered, 'One script', kind='fact')
        forgotten = self.fixture.saved(said, 'four hooks', kind='fact')
        self.items(first, second, tombstoned=[forgotten])
        self.pins((first['id'], True), (second['id'], False), (forgotten['id'], True))
        log = self.root / 'raw' / (self.fixture.raw.name + '.jsonl')
        log.write_bytes(log.read_bytes() + b'{"damaged\n')
        (self.root / 'notices/curation-failed.json').write_bytes(b'{}\n')
        (self.root / 'index.db').write_bytes(b'SQLite format 3\x00')
        return first, second, said

    # Running the command

    def command(self, code=None, memory=None):
        context = commands.Context('delete-project', {'folder': str(self.root)}, code, memory or self.memory)
        context.project = types.SimpleNamespace(name='sample')
        context.record = {'device': DEVICE}
        context.configuration = (memory or self.memory).configuration(deadline=clock.now() + 10)
        value = delete_project_command.delete_project(context)
        commands.validate_result(value, 'delete-project')
        return value

    def deleted(self):
        """What the deletion leaves: the project's folder gone, memory off for it, the rest as it was."""
        self.assertFalse(self.root.exists())
        self.assertTrue((self.folder / 'projects').is_dir())
        projects = self.configuration()['projects']
        self.assertEqual(projects['sample'], {'enabled': False, 'since': AT,
                                              'left_out': {'folders': ['tmp'], 'kinds': []}})
        self.assertEqual(projects['other'], {'enabled': True, 'since': AT})
        self.assertTrue((self.folder / 'logs/usage-2026-11.jsonl').read_bytes().startswith(USAGE))


class DeleteProjectTest(DeleteStore, unittest.TestCase):
    # TC-245

    def test_tc245_the_preview_counts_what_goes_and_changes_nothing(self):
        self.stocked()
        held = self.root / 'curation.lock'
        held.write_bytes(lock_bytes(secrets.token_hex(16)))
        before, other, settings = self.tree(self.folder), self.tree(self.other), self.configuration()
        value = self.command()
        self.assertEqual((value['outcome'], value['code']), ('confirm', 'ok'))
        self.assertRegex(value['confirm'], r'^[0-9a-hjkmnp-tv-z]{8}$')
        self.assertEqual(value['data'], {'project': 'sample', 'deleted': {'items': 2, 'entries': 3, 'pins': 1},
                                         'sync': 'off'})
        self.assertEqual(value['say'], 'This deletes the memory of sample on this device: 2 items, 3 raw log entries '
                         'and 1 pin, and turns memory off for it. A curation that runs for it now stops and applies '
                         'nothing; the usage log keeps its lines. Sync is off, so other devices keep theirs.')
        self.assertEqual(self.tree(self.folder), before)
        self.assertEqual((self.tree(self.other), self.configuration()), (other, settings))
        # A wrong code changes nothing either, and takes no lease over.
        stale = self.command('00000000')
        self.assertEqual((stale['outcome'], stale['code'], stale['confirm']), ('confirm', 'confirm-stale', value['confirm']))
        self.assertEqual(self.tree(self.folder), before)

    def test_tc245_backups_count_where_their_files_are_missing_and_damaged_records_do_not_stop_the_preview(self):
        first, second, _ = self.stocked()
        pins = self.root / 'layer/pins.json'
        pins.replace(pins.with_name('pins.json.bak'))
        pins.write_bytes(b'{"pins": [')
        item = self.root / 'layer/items' / (second['id'] + '.json')
        item.replace(item.with_name(item.name + '.bak'))
        (self.root / 'layer/items' / (first['id'] + '.json')).write_bytes(b'damaged')
        log = self.root / 'raw' / (self.fixture.raw.name + '.jsonl')
        log.replace(log.with_name(log.name + '.bak'))
        (self.root / 'raw/claude-code-ffffffffffffffff.jsonl').write_bytes(b'not an entry\n')
        value = self.command()
        self.assertEqual(value['data']['deleted'], {'items': 2, 'entries': 3, 'pins': 1})

    def test_tc245_a_record_that_cannot_be_read_or_became_a_link_does_not_stop_the_preview(self):
        self.stocked()
        log = self.root / 'raw' / (self.fixture.raw.name + '.jsonl')
        for path in (log, self.root / 'layer/pins.json'):
            path.with_name(path.name + '.bak').write_bytes(path.read_bytes())
        read = files.fence_read

        def refused(memory, path, deadline):
            if path == log:
                raise PermissionError('held without read sharing')
            if path.name == 'pins.json':
                raise UnsafePath()  # It became a link after the scan.
            return read(memory, path, deadline)
        with mock.patch.object(files, 'fence_read', refused):
            value = self.command()
        # Both are read from their backups.
        self.assertEqual(value['data']['deleted'], {'items': 2, 'entries': 3, 'pins': 1})

    def test_tc245_a_confirmed_deletion_takes_over_a_workers_lease_and_deletes_only_this_projects_memory(self):
        said, _ = self.fixture.one_turn()
        go_on, asked = threading.Event(), threading.Event()

        def hold(handler):
            asked.set()
            go_on.wait(60)
            worker_fixture.Server.send(handler, worker_fixture.stream(
                answer(change(quote(said, 'one script'), title='Saved by the worker'))))
        self.fixture.server.answers = [hold]
        context = multiprocessing.get_context('spawn')
        parent, child = context.Pipe()
        process = context.Process(target=worker_fixture.paused_curator, args=(child, str(self.folder)))
        process.start()
        child.close()
        self.addCleanup(parent.close)

        def stop():
            go_on.set()
            process.join(timeout=30)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        self.addCleanup(stop)
        self.assertTrue(parent.poll(60) and parent.recv() == 'held', 'the worker took no lease')
        self.assertTrue(asked.wait(60), 'the worker sent no request')
        lease = (self.root / 'curation.lock').read_bytes()
        other = self.tree(self.other)
        preview = self.command()
        self.assertEqual((self.root / 'curation.lock').read_bytes(), lease)
        started = time.monotonic()
        value = self.command(preview['confirm'])
        elapsed = time.monotonic() - started
        self.assertEqual((value['outcome'], value['code']), ('done', 'ok'))
        self.assertEqual(value['data'], preview['data'])
        self.assertEqual(value['say'], 'The memory of sample on this device was deleted: 0 items, 3 raw log entries '
                         'and 0 pins. Memory is off for it; the usage log keeps its lines. Sync is off, so other '
                         'devices keep theirs.')
        # The worker's lease, fresh and refreshed every hour, was taken over at once, not after ten minutes.
        self.assertLess(elapsed, delete_project_command.WAIT)
        self.deleted()
        self.assertEqual(self.tree(self.other), other)
        go_on.set()
        self.assertTrue(parent.poll(60), 'the worker did not end')
        self.assertEqual(parent.recv(), ('lost-lock', []))
        process.join(timeout=30)
        self.deleted()
        self.assertEqual(self.tree(self.other), other)

    def test_tc245_the_deletion_takes_over_every_lease_of_the_project_and_none_of_another(self):
        self.stocked()
        log = self.fixture.raw.name
        (self.root / 'injections').mkdir()
        (self.root / 'injections' / (log + '.jsonl')).write_bytes(b'')
        (self.root / 'compaction').mkdir()
        (self.root / 'compaction/codex-0123456789abcdef.json').write_bytes(b'{}\n')
        for path in (self.root / 'curation.lock', self.root / 'layer.lock', self.root / 'notices/conflict-counts.lock',
                     self.root / 'raw' / (log + '.lock')):
            path.write_bytes(lock_bytes(secrets.token_hex(16)))
        taken = []
        acquire = locks.Lock.acquire

        def watched(lease, *args, **kwargs):
            taken.append((lease.path.relative_to(self.folder).as_posix(), kwargs.get('force', False)))
            return acquire(lease, *args, **kwargs)
        preview = self.command()
        with mock.patch.object(locks.Lock, 'acquire', watched):
            value = self.command(preview['confirm'])
        self.assertEqual((value['outcome'], value['code']), ('done', 'ok'))
        self.assertEqual(taken, [('store.lock', False), ('projects/sample/curation.lock', True),
                                 ('projects/sample/layer.lock', True),
                                 ('projects/sample/notices/conflict-counts.lock', True),
                                 ('projects/sample/raw/claude-code-' + log[-16:] + '.lock', True),
                                 ('projects/sample/raw/codex-0123456789abcdef.lock', True)])
        self.deleted()
        self.assertTrue((self.other / 'curation.lock').exists())
        self.assertFalse((self.folder / 'store.lock').exists())

    def test_tc245_the_users_own_answer_leaves_the_code_current(self):
        self.stocked()
        preview = self.command()
        self.fixture.raw.turn('Yes, delete it.', 'Deleting it.')
        self.fixture.write()
        value = self.command(preview['confirm'])
        self.assertEqual((value['outcome'], value['code']), ('done', 'ok'))
        self.assertEqual(value['data']['deleted'], {'items': 2, 'entries': 5, 'pins': 1})
        self.deleted()

    def test_tc245_a_project_without_a_folder_is_turned_off(self):
        for path in sorted(self.root.rglob('*'), reverse=True):
            path.rmdir() if path.is_dir() else path.unlink()
        self.root.rmdir()
        preview = self.command()
        self.assertEqual(preview['data']['deleted'], {'items': 0, 'entries': 0, 'pins': 0})
        value = self.command(preview['confirm'])
        self.assertEqual((value['outcome'], value['code']), ('done', 'ok'))
        self.deleted()

    def test_tc245_sync_settings_are_shown_and_leave_no_project_tombstone(self):
        self.stocked()
        self.configure(sync={'address': 'https://sync.example/memory'})
        preview = self.command()
        self.assertEqual(preview['data']['sync'], 'on')
        self.assertTrue(preview['say'].endswith('The configuration holds sync settings, but no release syncs yet, '
                                                'so a sync remote and other devices keep theirs.'))
        value = self.command(preview['confirm'])
        self.assertEqual((value['outcome'], value['code'], value['data']['sync']), ('done', 'ok', 'on'))
        self.assertFalse(self.root.exists())
        self.assertEqual(self.configuration()['sync'], {'address': 'https://sync.example/memory'})

    def test_each_file_checks_its_own_sessions_lease_and_not_every_sessions(self):
        self.stocked()
        for number in range(40):
            name = 'codex-%016x' % number
            (self.root / 'raw' / (name + '.jsonl')).write_bytes(b'')
            (self.root / 'unprocessed' / (name + '.json')).write_bytes(b'{}\n')
        count = sum(1 for path in self.root.rglob('*') if path.is_file())
        preview = self.command()
        checked = []
        check = locks.Lock.check

        def counted(lease):
            checked.append(lease.path.name)
            return check(lease)
        with mock.patch.object(locks.Lock, 'check', counted):
            value = self.command(preview['confirm'])
        self.assertEqual((value['outcome'], value['code']), ('done', 'ok'))
        self.deleted()
        # Each of the 41 raw log leases is checked a few times, not once or twice for each of the files.
        sessions = Counter(name for name in checked if name.startswith(('claude-code-', 'codex-')))
        self.assertEqual(len(sessions), 41)
        self.assertGreater(count, 90)
        self.assertLessEqual(max(sessions.values()), 12)

    def test_raw_logs_are_read_by_the_answers_own_look_and_under_no_lease(self):
        self.stocked()
        preview = self.command()
        parsed = []
        parse = delete_project_command.curation_rebuild._parse

        def counted(data, log, found):
            parsed.append(log)
            return parse(data, log, found)
        with mock.patch.object(delete_project_command.curation_rebuild, '_parse', counted):
            value = self.command(preview['confirm'])
        self.assertEqual((value['outcome'], value['code']), ('done', 'ok'))
        # Once, for the answer's own look; the code does not cover the entries, so no look under a lease needs them.
        self.assertEqual(parsed, [self.fixture.raw.name])

    def test_the_store_lease_is_held_until_the_last_look(self):
        self.stocked()
        preview = self.command()
        held = []
        remove = delete_project_command._remove_folders

        def watched(*args):
            held.append((self.folder / 'store.lock').exists())
            return remove(*args)
        with mock.patch.object(delete_project_command, '_remove_folders', watched):
            value = self.command(preview['confirm'])
        self.assertEqual((value['outcome'], value['code'], held), ('done', 'ok', [True]))
        self.deleted()
        self.assertFalse((self.folder / 'store.lock').exists())

    def test_a_session_that_writes_before_memory_goes_off_is_taken_over_too(self):
        self.stocked()
        preview = self.command()
        late = 'codex-' + 'e' * 16
        disable = delete_project_command._disable
        taken = []
        acquire = locks.Lock.acquire

        def watched(lease, *args, **kwargs):
            taken.append(lease.path.name)
            return acquire(lease, *args, **kwargs)

        def writing(*args):
            (self.root / 'raw' / (late + '.lock')).write_bytes(lock_bytes(secrets.token_hex(16)))
            (self.root / 'raw' / (late + '.jsonl')).write_bytes(b'')
            return disable(*args)
        with mock.patch.object(delete_project_command, '_disable', writing), \
                mock.patch.object(locks.Lock, 'acquire', watched):
            value = self.command(preview['confirm'])
        self.assertEqual((value['outcome'], value['code']), ('done', 'ok'))
        self.assertIn(late + '.lock', taken)
        self.deleted()

    def test_a_lease_lost_after_memory_went_off_ends_the_deletion_with_files_left(self):
        self.stocked()
        preview = self.command()
        unlink, lost = Path.unlink, []

        def losing(path, *args, **kwargs):
            if not lost and path.parent == self.root / 'layer/items':
                # Another process takes the layer lease over, as one that found it stale would.
                lost.append((self.root / 'layer.lock').read_bytes())
                (self.root / 'layer.lock').write_bytes(lock_bytes(secrets.token_hex(16)))
            return unlink(path, *args, **kwargs)
        with mock.patch.object(Path, 'unlink', losing):
            value = self.command(preview['confirm'])
        self.assertEqual((value['outcome'], value['code']), ('failed', 'files-left'))
        self.assertIn('projects/sample/layer.lock', value['data']['left'])
        self.assertFalse(self.configuration()['projects']['sample']['enabled'])
        self.assertEqual(value['data']['deleted'], preview['data']['deleted'])
        self.assertEqual(value['say'], 'The deletion of the memory of sample on this device stopped before it '
                         'finished. Memory is off for it, and the files in data.left stay: turn memory on for it and '
                         'run delete-project again, or delete them by hand; their paths are inside the memory folder, '
                         'CORTHEX_MEMORY_HOME or else ~/.corthex/corthex-memory.')

    def test_a_deadline_after_memory_went_off_answers_files_left_and_one_before_lock_busy(self):
        self.stocked()
        write = files.write_json

        def late(*args, **kwargs):
            write(*args, **kwargs)
            raise locks.LockBusy()
        preview = self.command()
        with mock.patch.object(files, 'write_json', late):
            value = self.command(preview['confirm'])
        self.assertEqual((value['outcome'], value['code']), ('failed', 'files-left'))
        self.assertTrue(value['say'].startswith('The deletion of the memory of sample on this device stopped'))
        self.assertFalse(self.configuration()['projects']['sample']['enabled'])
        self.assertIn('projects/sample/curation.json', value['data']['left'])
        # Before the configuration is written, memory stays on and the user can run it again.
        self.configure()
        preview = self.command()

        def early(*args, **kwargs):
            raise locks.LockBusy()
        with mock.patch.object(files, 'write_json', early):
            value = self.command(preview['confirm'])
        self.assertEqual((value['outcome'], value['code']), ('failed', 'lock-busy'))
        self.assertTrue(self.configuration()['projects']['sample']['enabled'])

    def test_a_sessions_files_without_a_raw_folder_and_its_markers_go_with_its_lease(self):
        self.stocked()
        marked = 'codex-' + 'a' * 16
        (self.root / 'unprocessed' / ('20261108T090000Z.%s.1' % marked)).write_bytes(b'')
        preview = self.command()
        taken = []
        acquire = locks.Lock.acquire

        def watched(lease, *args, **kwargs):
            taken.append(lease.path.name)
            return acquire(lease, *args, **kwargs)
        with mock.patch.object(locks.Lock, 'acquire', watched):
            value = self.command(preview['confirm'])
        self.assertEqual((value['outcome'], value['code']), ('done', 'ok'))
        # A session that only a marker names has its lease taken over too.
        self.assertIn(marked + '.lock', taken)
        self.deleted()
        # Without a `raw` folder, no process can hold a session's lease, so its other files go all the same.
        self.setUp()
        for name in ('raw', 'unprocessed'):
            for path in (self.root / name).iterdir():
                path.unlink()
            (self.root / name).rmdir()
        (self.root / 'injections').mkdir()
        (self.root / 'injections' / ('codex-' + 'b' * 16 + '.jsonl')).write_bytes(b'')
        (self.root / 'compaction').mkdir()
        (self.root / 'compaction' / ('codex-' + 'b' * 16 + '.json')).write_bytes(b'{}\n')
        preview = self.command()
        value = self.command(preview['confirm'])
        self.assertEqual((value['outcome'], value['code']), ('done', 'ok'))
        self.deleted()

    def test_the_leases_that_nothing_refreshes_are_taken_only_once_memory_is_off(self):
        self.stocked()
        preview = self.command()
        locked = []
        disable = delete_project_command._disable

        def watched(*args):
            locked.append(sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob('*.lock')))
            return disable(*args)
        with mock.patch.object(delete_project_command, '_disable', watched):
            value = self.command(preview['confirm'])
        self.assertEqual((value['outcome'], value['code']), ('done', 'ok'))
        # While memory is still on, a hook can find a raw log or notice counter lease stale after 10 seconds.
        self.assertEqual(locked, [['curation.lock', 'layer.lock']])
        self.deleted()

    def test_a_busy_store_lease_answers_lock_busy_and_changes_nothing(self):
        self.stocked()
        preview = self.command()
        (self.folder / 'store.lock').write_bytes(lock_bytes(secrets.token_hex(16)))
        before = self.tree(self.folder)
        with mock.patch.object(delete_project_command, 'WAIT', .2):
            value = self.command(preview['confirm'])
        self.assertEqual((value['outcome'], value['code']), ('failed', 'lock-busy'))
        self.assertEqual(self.tree(self.folder), before)

    def test_links_are_never_followed_and_stay(self):
        self.stocked()
        outside = Path(self.fixture.folder.parent) / 'outside'
        outside.mkdir()
        (outside / 'kept.txt').write_bytes(b'kept')
        try:
            (self.root / 'raw/linked.jsonl').symlink_to(outside / 'kept.txt')
            (self.root / 'layer/linked').symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('links need a privilege here')
        preview = self.command()
        value = self.command(preview['confirm'])
        self.assertEqual((value['outcome'], value['code']), ('failed', 'files-left'))
        self.assertEqual(value['data']['left'], ['projects/sample/layer/linked', 'projects/sample/raw/linked.jsonl'])
        self.assertEqual((outside / 'kept.txt').read_bytes(), b'kept')
        self.assertEqual(sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob('*')),
                         ['layer', 'layer/linked', 'raw', 'raw/linked.jsonl'])
        self.assertFalse(self.configuration()['projects']['sample']['enabled'])

    def test_a_link_where_the_projects_folder_goes_is_never_followed(self):
        outside = Path(self.fixture.folder.parent) / 'outside'
        self.root.rename(outside)
        try:
            self.root.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('links need a privilege here')
        before = self.tree(outside)
        preview = self.command()
        self.assertEqual(preview['data']['deleted'], {'items': 0, 'entries': 0, 'pins': 0})
        value = self.command(preview['confirm'])
        self.assertEqual((value['outcome'], value['code'], value['data']['left']),
                         ('failed', 'files-left', ['projects/sample']))
        self.assertEqual(self.tree(outside), before)
        self.assertTrue(self.root.is_symlink())

    # TC-246

    def test_tc246_a_file_that_cannot_be_deleted_is_left_and_named(self):
        self.stocked()
        log = self.root / 'raw' / (self.fixture.raw.name + '.jsonl')
        unlink = Path.unlink

        def refused(path, *args, **kwargs):
            if path == log:
                raise PermissionError('held by another program')
            return unlink(path, *args, **kwargs)
        preview = self.command()
        with mock.patch.object(Path, 'unlink', refused):
            value = self.command(preview['confirm'])
        self.assertEqual((value['outcome'], value['code']), ('failed', 'files-left'))
        self.assertEqual(value['data'], dict(preview['data'], left=['projects/sample/raw/' + log.name]))
        self.assertEqual(value['say'], 'Memory is off for sample and the rest of its memory on this device was '
                         'deleted, but the files in data.left could not be, or were written while it ran. Close any '
                         'program that holds them, then delete them by hand; their paths are inside the memory '
                         'folder, CORTHEX_MEMORY_HOME or else ~/.corthex/corthex-memory.')
        self.assertEqual([path.relative_to(self.root).as_posix() for path in sorted(self.root.rglob('*'))],
                         ['raw', 'raw/' + log.name])
        self.assertFalse(self.configuration()['projects']['sample']['enabled'])

    def test_tc246_a_code_after_a_new_item_is_stale_and_deletes_nothing(self):
        first, _, said = self.stocked()
        preview = self.command()
        self.items(self.fixture.saved(said, 'the four hooks', kind='fact'))
        # A curation that holds the project's lease keeps it: nothing is taken over for a stale code.
        (self.root / 'curation.lock').write_bytes(lock_bytes(secrets.token_hex(16)))
        before, settings = self.tree(self.folder), self.configuration()
        value = self.command(preview['confirm'])
        self.assertEqual((value['outcome'], value['code']), ('confirm', 'confirm-stale'))
        self.assertEqual(value['data']['deleted'], {'items': 3, 'entries': 3, 'pins': 1})
        self.assertNotEqual(value['confirm'], preview['confirm'])
        self.assertEqual((self.tree(self.folder), self.configuration()), (before, settings))
        done = self.command(value['confirm'])
        self.assertEqual((done['outcome'], done['code']), ('done', 'ok'))
        self.deleted()

    def test_tc246_an_item_saved_while_the_store_lease_is_awaited_is_stale_and_takes_nothing_over(self):
        _, _, said = self.stocked()
        held = self.root / 'curation.lock'
        held.write_bytes(lock_bytes(secrets.token_hex(16)))
        lease = held.read_bytes()
        preview = self.command()
        acquire = locks.Lock.acquire

        def saving(lock, *args, **kwargs):
            value = acquire(lock, *args, **kwargs)
            if lock.path.name == 'store.lock':
                self.items(self.fixture.saved(said, 'the four hooks', kind='fact'))
            return value
        with mock.patch.object(locks.Lock, 'acquire', saving):
            value = self.command(preview['confirm'])
        self.assertEqual((value['outcome'], value['code']), ('confirm', 'confirm-stale'))
        self.assertEqual(value['data']['deleted']['items'], 3)
        # The curation that holds the project's lease keeps it, since nothing is deleted.
        self.assertEqual(held.read_bytes(), lease)
        self.assertTrue(self.configuration()['projects']['sample']['enabled'])

    def test_tc246_an_item_saved_while_the_leases_are_taken_over_is_stale_and_deletes_nothing(self):
        _, _, said = self.stocked()
        preview = self.command()
        acquire = locks.Lock.acquire

        def saving(lease, *args, **kwargs):
            value = acquire(lease, *args, **kwargs)
            if lease.path.name == 'layer.lock':
                self.items(self.fixture.saved(said, 'the four hooks', kind='fact'))
            return value
        with mock.patch.object(locks.Lock, 'acquire', saving):
            value = self.command(preview['confirm'])
        self.assertEqual((value['outcome'], value['code']), ('confirm', 'confirm-stale'))
        self.assertEqual(value['data']['deleted']['items'], 3)
        self.assertTrue(self.configuration()['projects']['sample']['enabled'])
        self.assertEqual(len(list((self.root / 'layer/items').glob('*.json'))), 4)
        self.assertEqual(sorted(path.name for path in self.root.rglob('*.lock')), [])

    @unittest.skipUnless(os.name == 'nt', 'Windows delete-sharing fixture')
    def test_tc246_a_raw_log_held_open_on_windows_is_left_then_deleted_by_hand(self):
        holder = """import ctypes,sys
from ctypes import wintypes as w
k=ctypes.WinDLL('kernel32',use_last_error=True)
k.CreateFileW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,ctypes.c_void_p,w.DWORD,w.DWORD,w.HANDLE]
k.CreateFileW.restype=w.HANDLE;k.CloseHandle.argtypes=[w.HANDLE]
h=k.CreateFileW(sys.argv[1],0x80000000,1,None,3,0x80,None)
if h==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
print('ready',flush=True);sys.stdin.read(1);k.CloseHandle(h)
"""
        self.stocked()
        log = self.root / 'raw' / (self.fixture.raw.name + '.jsonl')
        process = subprocess.Popen([sys.executable, '-B', '-c', holder, str(log)], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), 'ready')
            preview = self.command()
            started = time.monotonic()
            value = self.command(preview['confirm'])
            self.assertEqual((value['outcome'], value['code']), ('failed', 'files-left'))
            self.assertGreaterEqual(time.monotonic() - started, .95)
            self.assertEqual(value['data']['left'], ['projects/sample/raw/' + log.name])
            self.assertTrue(log.exists())
        finally:
            _, error = process.communicate('x', timeout=10)
        self.assertEqual((process.returncode, error), (0, ''))
        log.unlink()
        (self.root / 'raw').rmdir()
        self.root.rmdir()
        self.deleted()


if __name__ == '__main__':
    unittest.main()
