"""Synthetic migration driver paths; fixture checks never prove a real interval."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

from _common import ROOT
import test_memory_migration_inventory as fixtures

sys.path.insert(0, str(ROOT/'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import format2, locks, maintenance_owner, migration_driver as driver, migration_headers, store

NONCE = '0123456789abcdef0123456789abcdef'
OTHER_NONCE = 'fedcba9876543210fedcba9876543210'
FORMAT2 = dict(format=2, device=fixtures.HEADER['device'], made=fixtures.AT, release='0.3.0')
MARKER = {'from': 1, 'to': 2, 'started': fixtures.LATER}


def migrating(**changes):
    return format2.store_bytes(dict(FORMAT2, migrating=dict(MARKER, **changes)), allow_migrating=True)


class MigrationPlanTest(unittest.TestCase):
    """Read-only classification of named headers and recorded phases."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.parent, self.count = Path(temporary.name).resolve(), 0
        self.fresh()

    def fresh(self):
        self.count += 1
        self.root = self.parent/('memory-%d' % self.count)
        self.root.mkdir()

    def headers(self, primary=None, backup=None):
        for name, raw in (('store.json', primary), ('store.json.bak', backup)):
            if raw is not None:
                (self.root/name).write_bytes(raw)

    def record(self, nonce=NONCE, marks=(), **context):
        folder = self.root/'.maintenance/format-1-to-2'/nonce
        folder.mkdir(parents=True)
        context = dict(dict(device=FORMAT2['device'], made=fixtures.AT, release='0.3.0', started=fixtures.LATER), **context)
        (folder/'plan.json').write_bytes(json.dumps(dict(nonce=nonce, context=context)).encode('ascii'))
        for mark in marks:
            (folder/mark).write_bytes(b'{}')
        return folder

    def plan(self):
        return driver.plan(self.root, release='0.3.0')

    def refused(self, code):
        with self.assertRaises(driver.MigrationRefused) as caught:
            self.plan()
        self.assertEqual(caught.exception.code, code)

    def test_tc390_each_named_header_and_record_state_selects_one_path(self):
        c1, done = fixtures.data(fixtures.HEADER), format2.store_bytes(FORMAT2)
        cases = [
            ((c1, None), (), 'fresh'), ((c1, c1), (), 'fresh'), ((None, c1), (), 'fresh'),
            ((c1, migrating()), (), 'headers'), ((migrating(), migrating()), (), 'headers'),
            ((migrating(), migrating()), ('headers-complete.json',), 'initialization'),
            ((migrating(), migrating()), ('headers-complete.json', 'initialization-complete.json'), 'finalization'),
            ((migrating(), migrating()), ('headers-complete.json', 'initialization-complete.json',
                                          'final-header-publications.json'), 'finalization'),
            ((migrating(), done), ('final-header-publications.json',), 'final-headers'),
            ((done, done), ('final-header-publications.json',), 'final-headers'),
            ((done, done), ('final-header-publications.json', 'migration-complete.json'), 'complete'),
        ]
        for (primary, backup), marks, phase in cases:
            with self.subTest(phase=phase, marks=marks):
                self.fresh()
                self.headers(primary, backup)
                if phase != 'fresh':
                    self.record(marks=marks)
                self.record(OTHER_NONCE, ('migration-complete.json',), started='2026-11-04T00:00:00.000Z',
                            made='2026-11-04T00:00:00.000Z')
                result = self.plan()
                self.assertEqual(result.phase, phase)
                self.assertEqual(result.nonce, None if phase == 'fresh' else NONCE)
        self.fresh()
        self.headers(done, done)
        self.assertEqual(self.plan(), driver.Plan('format-2'))
        # A later release finds a completed store complete, never changed.
        self.record(marks=('final-header-publications.json', 'migration-complete.json'))
        self.assertEqual(driver.plan(self.root, release='0.3.1'), driver.Plan('complete', NONCE))
        self.record(OTHER_NONCE, ('final-header-publications.json', 'migration-complete.json'))
        self.assertEqual(self.plan(), driver.Plan('complete'))

    def test_tc390_unproven_or_ambiguous_states_are_refused_before_any_lease(self):
        c1, done = fixtures.data(fixtures.HEADER), format2.store_bytes(FORMAT2)
        with mock.patch.object(maintenance_owner, 'acquire', side_effect=AssertionError('no lease')), \
                mock.patch.object(maintenance_owner, 'acquire_finalization', side_effect=AssertionError('no lease')):
            self.refused('no-store')
            with self.assertRaises(driver.MigrationRefused) as caught:
                driver.plan(Path('relative-memory'), release='0.3.0')
            self.assertEqual(caught.exception.code, 'no-store')
            cases = [
                ((b'{damaged', c1), 'store-damaged'),
                ((fixtures.data(dict(fixtures.HEADER, format=3)), None), 'store-newer'),
                ((c1, done), 'store-damaged'),
                ((c1, fixtures.data(dict(fixtures.HEADER, device='d_ba9876543210'))), 'store-damaged'),
                ((migrating(), migrating(started='2026-11-05T02:00:00.000Z')), 'store-damaged'),
                ((format2.store_bytes(dict(FORMAT2, release='0.3.1', migrating=MARKER), allow_migrating=True), None),
                 'release-changed'),
                ((format2.store_bytes(dict(FORMAT2, release='0.3.1')), format2.store_bytes(FORMAT2)), 'store-damaged'),
                ((migrating(), migrating()), 'migration-record-unavailable'),
            ]
            for (primary, backup), code in cases:
                with self.subTest(code=code):
                    self.fresh()
                    self.headers(primary, backup)
                    self.refused(code)
            folder = self.record(started='2026-11-05T02:00:00.000Z')
            self.refused('migration-record-unavailable')
            (folder/'plan.json').write_bytes(json.dumps(dict(nonce=OTHER_NONCE, context=dict(
                device=FORMAT2['device'], made=fixtures.AT, release='0.3.0', started=fixtures.LATER))).encode('ascii'))
            self.refused('migration-record-unavailable')
            (folder/'plan.json').unlink()
            folder.rmdir()
            self.record()
            self.record(OTHER_NONCE)
            self.refused('migration-record-ambiguous')
            for name in ('store.json', 'store.json.bak'):
                (self.root/name).write_bytes(done)
            for nonce in (NONCE, OTHER_NONCE):
                (self.root/'.maintenance/format-1-to-2'/nonce/'final-header-publications.json').write_bytes(b'{}')
            self.refused('migration-record-ambiguous')
            (self.root/'.maintenance/format-1-to-2'/OTHER_NONCE/'migration-complete.json').write_bytes(b'{}')
            with self.assertRaises(driver.MigrationRefused) as caught:
                driver.plan(self.root, release='0.3.1')
            self.assertEqual(caught.exception.code, 'release-changed')
            self.fresh()
            (self.root/'store.json').write_bytes(c1)
            if os.name != 'nt':
                (self.root/'store.json').rename(self.root/'linked-header')
                (self.root/'store.json').symlink_to(self.root/'linked-header')
                self.refused('store-damaged')

    def test_migrate_requires_three_callable_checks_before_reading(self):
        self.headers(fixtures.data(fixtures.HEADER))
        quiet = lambda *args: None
        for checks in ((None, quiet, quiet), (quiet, None, quiet), (quiet, quiet, None)):
            with self.subTest(checks=checks), self.assertRaises(TypeError):
                driver.migrate(self.root, release='0.3.0', when=fixtures.LATER, deadline=time.monotonic()+30,
                               verify_quiescence=checks[0], verify_c1_lineage=checks[1],
                               verify_current_privacy=checks[2])
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ['store.json'])


class MigrationDriverTest(unittest.TestCase):
    """Actual component chains on a synthetic C1 store."""

    def setUp(self):
        self.fixture = fixtures.MigrationInventoryTest('test_tc390_observe_and_check_open_only_metadata_readonly_and_change_nothing')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root.resolve()
        self.calls = dict(quiescence=0, lineage=0, privacy=0)
        self.owners = []

    def quiet(self, root, binding):
        self.assertEqual(root, self.root)
        self.assertEqual(binding[:3], (fixtures.HEADER['device'], fixtures.AT, '0.3.0'))
        self.calls['quiescence'] += 1

    def lineage(self, root, context, projects):
        self.assertEqual((root, projects), (self.root, ('sample',)))
        self.assertEqual(context['device'], fixtures.HEADER['device'])
        self.calls['lineage'] += 1

    def privacy(self, root, context, projects):
        self.assertEqual((root, projects), (self.root, ('sample',)))
        self.calls['privacy'] += 1

    def migrate(self, **changes):
        checks = dict(verify_quiescence=self.quiet, verify_c1_lineage=self.lineage,
                      verify_current_privacy=self.privacy)
        checks.update(changes)
        return driver.migrate(self.root, release='0.3.0', when=fixtures.LATER,
                              deadline=time.monotonic()+300, **checks)

    def old_client_refused(self):
        with self.assertRaises(store.StoreUnavailable) as caught:
            store.MemoryStore(self.root).record(deadline=time.monotonic()+3)
        self.assertEqual(caught.exception.code, 'store-newer')

    def interrupted(self, target, *, after, checkpoint=False):
        """Stop one run at its first effect on target, before or after it."""
        name = '_checkpoint_rename' if checkpoint else '_rename'
        real = getattr(migration_headers, name)

        def effect(source, destination):
            if Path(destination).relative_to(self.root).as_posix().endswith(target):
                if after:
                    real(source, destination)
                raise OSError('fixture migration interruption')
            return real(source, destination)
        with mock.patch.object(migration_headers, name, side_effect=effect):
            with self.assertRaises(OSError):
                self.owned_run()

    def owned_run(self):
        """Run once and name the ordered owner the driver chose."""
        used = []
        acquire, finalization = maintenance_owner.acquire, maintenance_owner.acquire_finalization

        def watch(kind, function):
            def call(*args, **kwargs):
                used.append(kind)
                return function(*args, **kwargs)
            return call
        with mock.patch.object(maintenance_owner, 'acquire', watch('migration', acquire)), \
                mock.patch.object(maintenance_owner, 'acquire_finalization', watch('finalization', finalization)):
            try:
                return self.migrate()
            finally:
                self.owners.append(tuple(used))

    def test_tc390_fresh_migration_publishes_c2_and_a_repeat_takes_no_lease(self):
        raw = self.fixture.raw.read_bytes()
        result = self.migrate()
        self.assertEqual((result.phase, result.resumed), ('migrated', None))
        for name in ('store.json.bak', 'store.json'):
            self.assertEqual(format2.parse_store((self.root/name).read_bytes()), FORMAT2)
        folder = self.root/'.maintenance/format-1-to-2'/result.nonce
        complete = json.loads((folder/'migration-complete.json').read_bytes())
        self.assertTrue(complete['completed'])
        self.assertEqual(format2.parse_curation((self.fixture.project/'curation.json').read_bytes())['applies'], 3)
        self.assertEqual(self.fixture.raw.read_bytes(), raw)
        self.assertTrue(all(count > 0 for count in self.calls.values()), self.calls)
        self.old_client_refused()
        self.assertEqual(sorted(path.name for path in self.root.rglob('*.lock')), [])
        with mock.patch.object(maintenance_owner, 'acquire', side_effect=AssertionError('no lease')), \
                mock.patch.object(maintenance_owner, 'acquire_finalization', side_effect=AssertionError('no lease')):
            self.assertEqual(self.migrate(), driver.Outcome('complete', result.nonce))

    def test_tc390_each_interrupted_phase_resumes_once_and_old_clients_stay_refused(self):
        raw = self.fixture.raw.read_bytes()
        self.interrupted('store.json', after=True)
        first = driver.plan(self.root, release='0.3.0')
        self.assertEqual(first.phase, 'headers')
        self.old_client_refused()
        steps = [('layer/pins.json', dict(after=True), 'initialization'),
                 ('store.json.bak', dict(after=False), 'finalization'),
                 ('store.json.bak', dict(after=True), 'final-headers'),
                 ('migration-complete.json', dict(after=False, checkpoint=True), 'final-headers')]
        for target, options, phase in steps:
            with self.subTest(target=target, options=options):
                self.interrupted(target, **options)
                current = driver.plan(self.root, release='0.3.0')
                self.assertEqual((current.phase, current.nonce), (phase, first.nonce))
                self.old_client_refused()
                self.assertEqual(self.fixture.raw.read_bytes(), raw)
        result = self.owned_run()
        self.assertEqual(result, driver.Outcome('migrated', first.nonce, 'final-headers'))
        # Completed named headers need the finalization-only owner.
        self.assertEqual(self.owners, [('migration',)] * 4 + [('finalization',)] * 2)
        self.assertEqual(driver.plan(self.root, release='0.3.0'), driver.Plan('complete', first.nonce))
        self.assertEqual(os.listdir(str(self.root/'.maintenance/format-1-to-2')), [first.nonce])
        self.assertEqual(self.fixture.raw.read_bytes(), raw)

    def test_tc390_refused_interval_check_publishes_nothing_and_takes_no_lease(self):
        before = self.fixture.tree()
        failure = locks.LostLock()

        def refuse(root, binding):
            raise failure
        with self.assertRaises(locks.LostLock) as caught:
            self.migrate(verify_quiescence=refuse)
        self.assertIs(caught.exception, failure)
        self.assertEqual(self.fixture.tree(), before)
        self.assertEqual(driver.plan(self.root, release='0.3.0'), driver.Plan('fresh'))


if __name__ == '__main__':
    unittest.main()
