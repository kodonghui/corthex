"""TC-390 partial: Immutable intent fixtures; no real host coordination or durable journal."""
import copy
import json
import sys
import time
import unittest
from unittest import mock

from _common import ROOT
import test_memory_migration_inventory as fixtures
sys.path.insert(0, str(ROOT/'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import maintenance_identity, maintenance_owner, migration_intent as intent, migration_plan


class MigrationIntentTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.MigrationInventoryTest()
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.root, self.project = self.fixture.root, self.fixture.project

    def own(self):
        return maintenance_owner.acquire(self.root, release='0.3.0', when=fixtures.LATER,
            deadline=time.monotonic()+30, verify_quiescence=lambda *args: None)

    def prepare(self):
        with self.own() as owned:
            return intent.prepare(owned, maintenance_identity.bind(self.root))

    def test_roundtrip_regenerates_exact_proposals_and_fixed_epochs(self):
        planned = self.prepare()
        for _ in range(3):
            restored = intent.parse(planned.encoded, planned.originals)
            self.assertEqual(restored, planned)
        value = json.loads(planned.encoded)
        self.assertEqual(json.loads(planned.progress[0][1])['fence']['epoch'], value['projects'][0]['epoch'])
        self.assertEqual(tuple(name for name, _ in planned.headers.publications), ('store.json.bak', 'store.json'))
        self.assertEqual(set(json.loads(planned.headers.publications[0][1])['migrating']), {'from', 'to', 'started'})

    def test_original_whitespace_backup_and_temporary_bytes_are_preserved(self):
        original = b' \r\n'+fixtures.data(fixtures.PROGRESS)+b'\r\n'
        for suffix in ('', '.bak', '.abcdef_1.tmp'):
            (self.project/('curation.json'+suffix)).write_bytes(original)
        planned = self.prepare()
        self.assertEqual(sum(raw == original for _, raw in planned.originals), 3)
        self.assertNotIn(b'private raw bytes', planned.encoded)

    def test_preparation_changes_no_files_and_does_not_read_raw_payloads(self):
        before = self.fixture.tree()
        real_read = fixtures.history_recovery._read
        def metadata_only(store, path, *args):
            self.assertNotEqual(path, self.fixture.raw)
            return real_read(store, path, *args)
        with mock.patch.object(fixtures.history_recovery, '_read', side_effect=metadata_only): self.prepare()
        self.assertEqual(self.fixture.tree(), before)
        self.assertFalse((self.root/'.maintenance').exists())

    def test_new_cold_plans_get_independent_nonce_and_epoch(self):
        first, second = self.prepare(), self.prepare()
        a, b = json.loads(first.encoded), json.loads(second.encoded)
        self.assertNotEqual(a['nonce'], b['nonce'])
        self.assertNotEqual(a['projects'][0]['epoch'], b['projects'][0]['epoch'])

    def test_non_primary_progress_uses_named_backup_but_never_lone_temp(self):
        primary = self.project/'curation.json'
        primary.rename(self.project/'curation.json.bak')
        self.prepare()
        (self.project/'curation.json.bak').rename(self.project/'curation.json.abcdef_1.tmp')
        with self.assertRaises(intent.InvalidIntent): self.prepare()

    def test_missing_progress_is_not_proof_of_initialization(self):
        (self.project/'curation.json').unlink()
        with self.assertRaises(intent.InvalidIntent): self.prepare()

    def test_existing_migration_cannot_create_a_new_cold_intent(self):
        plan = migration_plan.header_fence({'store.json': fixtures.data(fixtures.HEADER)},
            release='0.3.0', when=fixtures.LATER)
        for name, raw in plan.publications: (self.root/name).write_bytes(raw)
        with self.assertRaises(intent.InvalidIntent): self.prepare()

    def test_root_binding_must_be_the_owned_original_directory(self):
        with self.own() as owned:
            for binding in (maintenance_identity.bind(self.project),
                            maintenance_identity.bind(self.root/'store.json', entry='file')):
                with self.assertRaises(intent.InvalidIntent): intent.prepare(owned, binding)

    def test_any_exact_original_or_hash_change_refuses(self):
        planned = self.prepare()
        originals = list(planned.originals); slot, raw = originals[0]; originals[0] = (slot, raw+b' ')
        with self.assertRaises(intent.InvalidIntent): intent.parse(planned.encoded, originals)
        value = json.loads(planned.encoded); value['sources'][0]['sha256'] = '0'*64
        with self.assertRaises(intent.InvalidIntent): intent.parse(fixtures.data(value), planned.originals)

    def test_unknown_path_fields_and_escaping_names_are_not_opened(self):
        planned = self.prepare(); value = json.loads(planned.encoded)
        for change in [dict(name='../configuration.json'), dict(project='../escape'), dict(path='/private'),
                       dict(family='raw'), dict(name='configuration.json.unknown')]:
            modified = copy.deepcopy(value); modified['sources'][0].update(change)
            with self.subTest(change=change), self.assertRaises(intent.InvalidIntent):
                intent.parse(fixtures.data(modified), planned.originals)

    def test_changed_epoch_context_or_proposal_hash_refuses(self):
        planned = self.prepare(); value = json.loads(planned.encoded)
        changes = [lambda v: v['projects'][0].update(epoch='f'*32),
                   lambda v: v['projects'][0].update(source=True),
                   lambda v: v['projects'][0].update(sha256='0'*64),
                   lambda v: v['context'].update(device='d_123456789abc'),
                   lambda v: v.update(header_sha256='0'*64)]
        for change in changes:
            modified = copy.deepcopy(value); change(modified)
            with self.assertRaises(intent.InvalidIntent): intent.parse(fixtures.data(modified), planned.originals)

    def test_catalog_order_duplicates_and_original_slot_types_are_strict(self):
        planned = self.prepare(); value = json.loads(planned.encoded)
        for sources in [list(reversed(value['sources'])), value['sources']+value['sources'][:1]]:
            modified = dict(value, sources=sources)
            with self.assertRaises(intent.InvalidIntent): intent.parse(fixtures.data(modified), planned.originals)
        for originals in [planned.originals+((999, None),), ((False, planned.originals[0][1]),)+planned.originals[1:]]:
            with self.assertRaises(intent.InvalidIntent): intent.parse(planned.encoded, originals)

    def test_old_owner_cannot_prepare_after_its_context_has_closed(self):
        with self.own() as owned: binding = maintenance_identity.bind(self.root)
        with self.assertRaises(fixtures.locks.LostLock): intent.prepare(owned, binding)

    def test_pinned_epoch_extension_keeps_default_fresh_and_rejects_bad_ids(self):
        raw = fixtures.data(fixtures.PROGRESS)
        self.assertNotEqual(migration_plan.progress(raw), migration_plan.progress(raw))
        self.assertEqual(migration_plan.progress(raw, epoch='a'*32), migration_plan.progress(raw, epoch='a'*32))
        for epoch in (True, '', 'a'*31, 'g'*32):
            with self.assertRaises(ValueError): migration_plan.progress(raw, epoch=epoch)

    def test_inventory_changes_before_preparation_revoke_ownership(self):
        with self.own() as owned:
            binding = maintenance_identity.bind(self.root)
            (self.project/'curation.json').write_bytes(fixtures.data(dict(fixtures.PROGRESS, applies=4)))
            with self.assertRaises(fixtures.locks.LostLock): intent.prepare(owned, binding)

    def test_multiple_projects_keep_independent_fixed_epochs(self):
        other = self.root/'projects/other'; (other/'raw').mkdir(parents=True)
        (other/'curation.json').write_bytes(fixtures.data(fixtures.PROGRESS))
        planned = self.prepare(); value = json.loads(planned.encoded)
        self.assertEqual([item['name'] for item in value['projects']], ['other', 'sample'])
        self.assertEqual(len({item['epoch'] for item in value['projects']}), 2)
        self.assertEqual(intent.parse(planned.encoded, planned.originals), planned)

    def test_mutable_original_buffers_are_detached(self):
        planned = self.prepare(); buffers = [(slot, bytearray(raw)) for slot, raw in planned.originals]
        restored = intent.parse(planned.encoded, buffers)
        for _, raw in buffers: raw[:] = b'changed'
        self.assertEqual(restored, planned)

    def test_non_none_verification_result_is_refused(self):
        with self.own() as owned:
            with mock.patch.object(maintenance_owner.Ownership, 'check', return_value=True):
                with self.assertRaises(TypeError): intent.prepare(owned, maintenance_identity.bind(self.root))

    def test_private_plan_metadata_does_not_reveal_original_bytes_in_repr(self):
        planned = self.prepare()
        self.assertEqual(repr(planned), 'Intent()')
        self.assertNotIn(str(self.root).encode(), planned.encoded)


if __name__ == '__main__': unittest.main()
