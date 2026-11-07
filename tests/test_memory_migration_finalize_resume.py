"""Synthetic finalization-only owners; no active user store or host proof."""
import json
from pathlib import Path
import sys
import time
import unittest
from unittest import mock
from _common import ROOT
import test_memory_migration_finalize as fixtures
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import format2, locks, maintenance_journal as journal, maintenance_owner, migration_inventory
from memory_lib import migration_final_headers as catalogs, migration_headers as headers
from memory_lib import migration_finalize_resume as resume

class FinalizeResumeTest(unittest.TestCase):

    def setUp(self):
        self.fx = fixtures.MigrationFinalizeTest()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.root, self.project = (self.fx.root, self.fx.project)

    def own(self):
        return maintenance_owner.acquire_finalization(self.root, release='0.3.0', when='2026-11-05T00:00:00.000Z', deadline=time.monotonic() + 120, verify_quiescence=self.fx.fx.fx.quiet)

    def complete(self, stop=None, after=True):
        with self.fx.fx.fx.own() as owned:
            initialized, intent = self.fx.initialized(owned)
            if stop is None:
                self.fx.publish(initialized)
            else:
                rename = headers._rename
                count = [0]

                def effect(source, target):
                    index = count[0]
                    count[0] += 1
                    if index == stop:
                        if after:
                            rename(source, target)
                        raise OSError('fixture finalization interruption')
                    return rename(source, target)
                with mock.patch.object(headers, '_rename', side_effect=effect):
                    with self.assertRaises(OSError):
                        self.fx.publish(initialized)
            return (initialized.nonce, intent)

    def reopen(self, owned, nonce, **changes):
        checks = dict(verify_supported_lineage=self.fx.fx.lineage, verify_current_privacy=self.fx.privacy)
        checks.update(changes)
        return resume.reopen(owned, nonce, **checks)

    def test_uncertain_backup_completes_only_headers_and_preserves_later_c2_data(self):
        header = self.root / 'store.json'
        (self.root / 'store.json.abcdefgh.tmp').write_bytes(header.read_bytes())
        progress = self.project / 'curation.json'
        (self.project / 'curation.json.abcdefgh.tmp').write_bytes(progress.read_bytes())
        nonce, intent = self.complete(stop=0)
        folder = self.fx.fx.fx.folder(intent)
        value = format2.parse_curation(progress.read_bytes())
        value['applies'] += 1
        progress.write_bytes(format2.curation_bytes(value))
        payload = self.project / 'layer/items/i_0123456789ab.json'
        payload.write_bytes(b'preserve opaque later fixture')
        before = self.fx.fx.fx.project_bytes()
        original = (folder / 'plan.json').read_bytes()
        with self.own() as owned:
            read = owned.inventory._observer.fence.read

            def metadata(path, deadline):
                self.assertNotEqual(path, payload)
                return read(path, deadline)
            with mock.patch.object(owned.inventory._observer.fence, 'read', side_effect=metadata):
                result = self.reopen(owned, nonce)
                result.check()
            self.assertTrue((folder / 'migration-complete.json').exists())
            for name in ('store.json.bak', 'store.json'):
                self.assertNotIn('migrating', format2.parse_store((self.root / name).read_bytes()))
        self.assertEqual(self.fx.fx.fx.project_bytes(), before)
        self.assertEqual((folder / 'plan.json').read_bytes(), original)

    def test_uncertain_primary_never_repeats_a_canonical_rename(self):
        nonce, intent = self.complete(stop=1)
        with self.own() as owned:
            with mock.patch.object(headers, '_rename', side_effect=AssertionError('no repeated final header effect')):
                result = self.reopen(owned, nonce)
                result.check()
        self.assertTrue((self.fx.fx.fx.folder(intent) / 'final-header-000001.done.json').exists())

    def test_existing_completion_preserves_current_c2_data_without_any_republication(self):
        nonce, _ = self.complete()
        progress = self.project / 'curation.json'
        value = format2.parse_curation(progress.read_bytes())
        value['applies'] += 2
        progress.write_bytes(format2.curation_bytes(value))
        before = self.fx.fx.fx.project_bytes()
        with self.own() as owned:
            with mock.patch.object(headers, '_rename', side_effect=AssertionError('no canonical rewrite')), mock.patch.object(headers, '_checkpoint_rename', side_effect=AssertionError('no checkpoint rewrite')):
                result = self.reopen(owned, nonce)
                result.check()
        self.assertEqual(self.fx.fx.fx.project_bytes(), before)

    def test_copied_completed_header_bytes_cannot_supply_the_recorded_stage_identity(self):
        nonce, _ = self.complete(stop=0)
        path = self.root / 'store.json.bak'
        raw = path.read_bytes()
        path.rename(self.root.parent / 'preserved-completed-header')
        path.write_bytes(raw)
        with self.own() as owned:
            with self.assertRaises(resume.InvalidResume):
                self.reopen(owned, nonce)
        self.assertEqual(path.read_bytes(), raw)
        self.assertIn('migrating', json.loads((self.root / 'store.json').read_bytes()))

    def test_named_damaged_final_publications_are_never_recreated_or_recovered(self):
        nonce, intent = self.complete(stop=0)
        path = self.fx.fx.fx.folder(intent) / 'final-header-publications.json'
        path.with_name(path.name + '.bak').write_bytes(path.read_bytes())
        path.write_bytes(b'{}')
        with self.own() as owned:
            with self.assertRaises(resume.InvalidResume):
                self.reopen(owned, nonce)
        self.assertEqual(path.read_bytes(), b'{}')
        self.assertTrue(path.with_name(path.name + '.bak').exists())

    def test_boolean_final_checkpoint_version_is_not_an_integer_protocol(self):
        nonce, intent = self.complete(stop=1, after=False)
        path = self.fx.fx.fx.folder(intent) / 'final-header-000000.done.json'
        value = json.loads(path.read_bytes())
        value['version'] = True
        path.write_bytes(journal._bytes(value))
        with self.own() as owned:
            with self.assertRaises(resume.InvalidResume):
                self.reopen(owned, nonce)
        self.assertIs(json.loads(path.read_bytes())['version'], True)

    def test_original_privacy_exception_is_preserved_and_interval_never_revives(self):
        nonce, _ = self.complete(stop=0)
        original = ValueError('fixture renewed current privacy refusal')

        def privacy(*args):
            raise original
        with self.own() as owned:
            with self.assertRaises(ValueError) as caught:
                self.reopen(owned, nonce, verify_current_privacy=privacy)
            self.assertIs(caught.exception, original)
            with self.assertRaises(locks.LostLock):
                self.reopen(owned, nonce)

    def test_supported_lineage_requires_callable_and_only_none(self):
        nonce, _ = self.complete(stop=0)
        with self.own() as owned:
            with self.assertRaises(TypeError):
                self.reopen(owned, nonce, verify_supported_lineage=None)
            with self.assertRaises(TypeError):
                self.reopen(owned, nonce, verify_supported_lineage=lambda *args: True)
            with self.assertRaises(locks.LostLock):
                owned.check()

    def test_completed_result_still_flushes_and_revokes_on_barrier_failure(self):
        nonce, _ = self.complete()
        original = OSError('fixture finalization directory barrier')
        barrier = journal._Guard.directory_barrier

        def synced(guard, path, **kwargs):
            if Path(path) == self.root:
                raise original
            return barrier(guard, path, **kwargs)
        with self.own() as owned:
            with mock.patch.object(journal._Guard, 'directory_barrier', new=synced):
                with self.assertRaises(OSError) as caught:
                    self.reopen(owned, nonce)
            self.assertIs(caught.exception, original)
            with self.assertRaises(locks.LostLock):
                owned.check()

    def test_manifest_before_first_final_effect_reuses_original_stages_and_intent(self):
        nonce, intent = self.complete(stop=0, after=False)
        folder = self.fx.fx.fx.folder(intent)
        original = (folder / 'plan.json').read_bytes()
        manifest = (folder / 'final-header-publications.json').read_bytes()
        with self.fx.fx.fx.own() as owned:
            with mock.patch.object(fixtures.finalize, 'publish', side_effect=AssertionError('no fresh final publisher')):
                result = self.reopen(owned, nonce)
                result.check()
        self.assertEqual((folder / 'plan.json').read_bytes(), original)
        self.assertEqual((folder / 'final-header-publications.json').read_bytes(), manifest)

    def test_unpublished_final_stage_and_partial_checkpoint_are_preserved_before_retry(self):
        with self.fx.fx.fx.own() as owned:
            initialized, intent = self.fx.initialized(owned)
            write = journal._Guard.write

            def stage(guard, path, data):
                result = write(guard, path, data)
                if Path(path).name == 'final-header-stage-000000.bin':
                    raise OSError('fixture unpublished final stage')
                return result
            with mock.patch.object(journal._Guard, 'write', new=stage):
                with self.assertRaises(OSError):
                    self.fx.publish(initialized)
        folder = self.fx.fx.fx.folder(intent)
        raw = (folder / 'final-header-stage-000000.bin').read_bytes()
        partial = folder / ('checkpoint-' + 'a' * 32 + '.tmp')
        partial.write_bytes(b'{preserve partial fixture')
        with self.fx.fx.fx.own() as owned:
            result = self.reopen(owned, initialized.nonce)
            result.check()
        self.assertEqual([p.read_bytes() for p in folder.glob('final-header-orphan-*.bin')], [raw])
        self.assertEqual(partial.read_bytes(), b'{preserve partial fixture')

    def test_pre_finalization_changed_initialization_cannot_borrow_later_c2_admission(self):
        nonce, _ = self.complete(stop=0, after=False)
        payload = self.project / 'layer/items/i_0123456789ab.json'
        payload.write_bytes(b'preserve unknown pre-final fixture')
        with self.fx.fx.fx.own() as owned:
            with self.assertRaises(resume.InvalidResume):
                self.reopen(owned, nonce)
        self.assertEqual(payload.read_bytes(), b'preserve unknown pre-final fixture')
        for name in ('store.json', 'store.json.bak'):
            self.assertIn('migrating', json.loads((self.root / name).read_bytes()))

    def test_returned_resumed_finalization_failure_revokes_the_original_interval(self):
        nonce, intent = self.complete(stop=0)
        unknown = self.fx.fx.fx.folder(intent) / 'unexpected-after-final-resume'
        with self.own() as owned:
            result = self.reopen(owned, nonce)
            unknown.write_bytes(b'preserve fixture')
            with self.assertRaises(locks.LostLock):
                result.check()
            unknown.unlink()
            with self.assertRaises(locks.LostLock):
                owned.check()
            with self.assertRaises(locks.LostLock):
                self.reopen(owned, nonce)

    def test_recreated_initialization_stage_refuses_finalization(self):
        nonce, intent = self.complete(stop=0)
        folder = self.fx.fx.fx.folder(intent)
        plan = json.loads((folder / 'initialization-publications.json').read_bytes())
        stage = folder / next(effect['stage'] for effect in plan['effects'] if 'target' in effect)
        stage.write_bytes(b'preserve recreated stage')
        with self.own() as owned:
            with self.assertRaises(resume.InvalidResume):
                self.reopen(owned, nonce)
        self.assertEqual(stage.read_bytes(), b'preserve recreated stage')

    def test_archive_directory_cannot_be_rebound_with_the_same_files(self):
        nonce, intent = self.complete(stop=0)
        folder = self.fx.fx.fx.folder(intent)
        displaced = self.root.parent / 'preserved-archive-directory'
        directory = journal._Guard.directory

        def swap(guard, path, **kwargs):
            if path == folder:
                folder.rename(displaced)
                folder.mkdir()
                for entry in displaced.iterdir():
                    entry.rename(folder / entry.name)
            return directory(guard, path, **kwargs)

        with self.own() as owned:
            with mock.patch.object(journal._Guard, 'directory', new=swap):
                with self.assertRaises(locks.LostLock):
                    self.reopen(owned, nonce)
        self.assertTrue(displaced.is_dir())
        self.assertIn('migrating', json.loads((self.root / 'store.json').read_bytes()))

    def test_catalog_requires_named_completed_f2_and_never_invents_a_start(self):
        value = dict(format=2, device='d_0123456789ab', made='2026-11-01T00:00:00.000Z', release='0.3.0')
        complete = format2.store_bytes(value)
        migrating = dict(value, migrating={'from': 1, 'to': 2, 'started': '2026-11-02T00:00:00.000Z'})
        marker = format2.store_bytes(migrating, allow_migrating=True)
        with self.assertRaises(ValueError):
            catalogs.observe({'store.json': marker}, release='0.3.0')
        with self.assertRaises(ValueError):
            catalogs.observe({'store.json': marker, 'store.json.abcdefgh.tmp': complete}, release='0.3.0')
        result = catalogs.observe({'store.json': complete}, release='0.3.0')
        self.assertIsNone(result.started)
        self.assertEqual(dict(result.publications)['store.json'], complete)
        mixed = catalogs.observe({'store.json': marker, 'store.json.bak': complete}, release='0.3.0')
        self.assertEqual(mixed.started, '2026-11-02T00:00:00.000Z')

    def test_catalog_refuses_old_format_foreign_identity_release_and_unknown_names(self):
        value = dict(format=2, device='d_0123456789ab', made='2026-11-01T00:00:00.000Z', release='0.3.0')
        raw = format2.store_bytes(value)
        for other in (dict(value, device='d_abcdefabcdef'), dict(value, release='0.3.1')):
            with self.subTest(other=other):
                with self.assertRaises(ValueError):
                    catalogs.observe({'store.json': raw, 'store.json.bak': format2.store_bytes(other)}, release='0.3.0')
        with self.assertRaises(ValueError):
            catalogs.observe({'store.json': raw, 'store.json.old': raw}, release='0.3.0')
        with self.assertRaises(ValueError):
            catalogs.observe({'store.json': raw, 'store.json.bak': b'{"format":1}'}, release='0.3.0')

    def test_finalization_owner_reads_only_metadata_and_preserves_later_c2_payloads(self):
        self.complete()
        progress = self.project / 'curation.json'
        value = format2.parse_curation(progress.read_bytes())
        value['applies'] += 1
        progress.write_bytes(format2.curation_bytes(value))
        payload = self.project / 'layer/items/i_0123456789ab.json'
        payload.write_bytes(b'preserve opaque later fixture')
        before = self.fx.fx.fx.project_bytes()
        read = migration_inventory._Observer.file
        opened = []

        def observed(observer, name, **kwargs):
            if kwargs.get('read'):
                opened.append(name)
                self.assertNotEqual(observer.root / name, payload)
            return read(observer, name, **kwargs)
        with mock.patch.object(migration_inventory._Observer, 'file', new=observed):
            with self.own() as owned:
                self.assertEqual(owned.mode, 'finalization-only')
                owned.check()
                owned.inventory.check()
                self.assertTrue(any((name.endswith('/curation.json') for name in opened)))
                self.assertEqual([kind for kind, _ in owned.inventory.leases][:3], ['store', 'curation', 'layer'])
        self.assertEqual(self.fx.fx.fx.project_bytes(), before)
        with self.assertRaises(ValueError):
            with self.fx.fx.fx.own():
                self.fail('ordinary admission must refuse completed headers')
if __name__ == '__main__':
    unittest.main()
