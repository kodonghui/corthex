"""TASK-074 migrate command (API-154) on synthetic stores.

The user's yes stands for the maintenance interval here; no real host is
updated or closed. The runner still refuses migrate before the 0.3.0
activation, so these tests call the handler as the runner would.
"""
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest import mock

from _common import ROOT
import test_memory_migration_inventory as fixtures

sys.path.insert(0, str(ROOT/'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import commands, format2, migration_command, migration_headers, store

FORMAT2 = dict(format=2, device=fixtures.HEADER['device'], made=fixtures.AT, release='0.3.0')


class MigrateCommandTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.MigrationInventoryTest('test_tc390_observe_and_check_open_only_metadata_readonly_and_change_nothing')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root.resolve()
        self.release = '0.3.0'
        patcher = mock.patch.object(migration_command, 'release', side_effect=lambda: self.release)
        patcher.start()
        self.addCleanup(patcher.stop)

    def command(self, confirm=None):
        """Call the handler after the runner's store gate, as the runner would."""
        memory = store.MemoryStore(self.root)
        context = commands.Context('migrate', {'folder': str(self.root)}, confirm, memory)
        try:
            context.record = memory.record(deadline=time.monotonic()+10)
        except store.StoreUnavailable as error:
            self.assertIn(error.code, ('store-newer',))
            context.store_error = error.code
        value = migration_command.migrate(context)
        commands.validate_result(value, 'migrate')
        return value

    def old_client_refused(self):
        with self.assertRaises(store.StoreUnavailable) as caught:
            store.MemoryStore(self.root).record(deadline=time.monotonic()+3)
        self.assertEqual(caught.exception.code, 'store-newer')

    def writer(self):
        """Hold one raw lease in another process, as a live C1 session would."""
        code = ("import sys,time;sys.path.insert(0,sys.argv[1]);from pathlib import Path;"
                "from memory_lib import locks;lease=locks.Lock(Path(sys.argv[2]),'raw',sys.argv[3]);"
                "lease.acquire(time.monotonic()+5);print('ready',flush=True);"
                "sys.stdin.readline();lease.release()")
        child = subprocess.Popen([sys.executable, '-B', '-c', code,
            str(ROOT/'plugins/corthex-memory/skills/corthex-memory/scripts'),
            str(self.fixture.project/'raw'/(fixtures.LOG+'.lock')), fixtures.HEADER['device']],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)

        def stop():
            if child.poll() is None:
                child.stdin.write('release\n')
                child.stdin.flush()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=10)
            for stream in (child.stdin, child.stdout, child.stderr):
                stream.close()
        self.addCleanup(stop)
        self.assertEqual(child.stdout.readline().strip(), 'ready')
        return stop

    def test_tc390_preview_changes_nothing_and_the_yes_migrates_once(self):
        before, raw = self.fixture.tree(), self.fixture.raw.read_bytes()
        preview = self.command()
        self.assertEqual((preview['outcome'], preview['code']), ('confirm', 'ok'))
        self.assertEqual({key: preview['data'][key] for key in ('phase', 'release', 'projects')},
                         dict(phase='fresh', release='0.3.0', projects=['sample']))
        self.assertRegex(preview['data']['binding'], r'\A[0-9a-f]{64}\Z')
        self.assertIn('both Claude Code and Codex', preview['say'])
        self.assertEqual(self.fixture.tree(), before)
        done = self.command(preview['confirm'])
        self.assertEqual((done['outcome'], done['code']), ('done', 'ok'))
        self.assertEqual(done['data'], dict(phase='migrated', release='0.3.0', projects=['sample']))
        for name in ('store.json', 'store.json.bak'):
            self.assertEqual(format2.parse_store((self.root/name).read_bytes()), FORMAT2)
        self.assertEqual(self.fixture.raw.read_bytes(), raw)
        self.old_client_refused()
        again = self.command()
        self.assertEqual((again['outcome'], again['data']), ('nothing', dict(phase='complete', release='0.3.0')))
        self.assertEqual(self.command(preview['confirm'])['outcome'], 'nothing')

    def test_tc390_the_code_binds_the_reviewed_configuration_and_a_change_stops_the_run(self):
        preview = self.command()
        configuration = self.root/'configuration.json'
        original = configuration.read_bytes()
        changed = json.loads(original)
        changed['projects']['sample']['enabled'] = False
        configuration.write_bytes(fixtures.data(changed))
        stale = self.command(preview['confirm'])
        self.assertEqual((stale['outcome'], stale['code']), ('confirm', 'confirm-stale'))
        self.assertNotEqual(stale['data']['binding'], preview['data']['binding'])
        self.assertFalse((self.root/'.maintenance').exists())
        configuration.write_bytes(original)
        preview = self.command()
        rename = migration_headers._rename

        def effect(source, target):
            # The reviewed configuration changes once initialization has begun.
            if Path(target).name == 'pins.json':
                configuration.write_bytes(fixtures.data(changed))
            return rename(source, target)
        with mock.patch.object(migration_headers, '_rename', side_effect=effect):
            stopped = self.command(preview['confirm'])
        self.assertEqual((stopped['outcome'], stopped['code']), ('failed', 'migration-stopped'))
        self.assertEqual(stopped['data'], dict(phase='initialization', release='0.3.0', reason='store-changed'))
        self.old_client_refused()
        # Reviewing the changed configuration cannot resume: the records keep the original.
        resume = self.command()
        self.assertEqual((resume['outcome'], resume['data']['phase']), ('confirm', 'initialization'))
        self.assertIn('stopped part way', resume['say'])
        again = self.command(resume['confirm'])
        self.assertEqual(again['data'], stopped['data'])
        self.old_client_refused()
        # Undoing the change lets the confirmed resume finish.
        configuration.write_bytes(original)
        resume = self.command()
        done = self.command(resume['confirm'])
        self.assertEqual(done['data'], dict(phase='migrated', resumed='initialization', release='0.3.0',
                                            projects=['sample']))
        self.assertEqual(format2.parse_store((self.root/'store.json').read_bytes()), FORMAT2)
        self.assertEqual(configuration.read_bytes(), original)

    def test_tc390_unsupported_releases_and_a_live_lease_change_no_header(self):
        header = self.root/'store.json'
        header.write_bytes(fixtures.data(dict(fixtures.HEADER, release='0.1.0')))
        blocked = self.command()
        self.assertEqual((blocked['outcome'], blocked['code'], blocked['data']),
                         ('refused', 'migration-blocked', dict(reason='unsupported-release')))
        header.write_bytes(fixtures.data(fixtures.HEADER))
        self.release = '0.2.1'
        self.assertEqual(self.command()['data'], dict(reason='unsupported-release'))
        self.release = '0.3.0'
        before = self.fixture.tree()
        preview = self.command()
        stop = self.writer()
        busy = self.command(preview['confirm'])
        stop()
        self.assertEqual((busy['outcome'], busy['code']), ('failed', 'lock-busy'))
        self.assertEqual(self.fixture.tree(), before)
        self.assertEqual(self.command()['data']['phase'], 'fresh')

    def test_tc390_runner_still_answers_usage_for_migrate_before_activation(self):
        before = self.fixture.tree()
        for argv in (['migrate'], ['--folder', str(self.root), 'migrate'], ['migrate', '--confirm', 'abcdefgh']):
            with self.subTest(argv=argv):
                answer, status = commands.run(argv, handlers={'migrate': migration_command.migrate})
                self.assertEqual((answer['command'], answer['code'], status), ('none', 'usage', 2))
        self.assertNotIn('migrate', commands.COMMANDS)
        self.assertEqual(self.fixture.tree(), before)


if __name__ == '__main__':
    unittest.main()
