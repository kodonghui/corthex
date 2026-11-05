"""Header-only real filesystem fixtures; no real host activation or restart grant."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock

from _common import ROOT
import test_memory_migration_inventory as fixtures
sys.path.insert(0,str(ROOT/'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import files,locks,maintenance_identity,maintenance_journal as journal
from memory_lib import maintenance_owner,migration_headers as headers,migration_intent,store


class MigrationHeadersTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.MigrationInventoryTest();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root.resolve();self.active=True;self.failure=locks.LostLock()

    def quiet(self,*args):
        if not self.active:raise self.failure

    def own(self):
        return maintenance_owner.acquire(self.root,release='0.3.0',when=fixtures.LATER,
            deadline=time.monotonic()+120,verify_quiescence=self.quiet)

    def prepared(self,owned):
        native=maintenance_identity.bind(self.root);intent=migration_intent.prepare(owned,native)
        return journal.preserve(owned,intent,native),intent

    def folder(self,intent):return self.root/'.maintenance/format-1-to-2'/json.loads(intent.encoded)['nonce']

    def project_bytes(self):
        return {p.relative_to(self.root).as_posix():p.read_bytes() for p in (self.root/'projects').rglob('*')
                if p.is_file() and not p.name.endswith('.lock')}

    def test_backup_primary_and_exact_checkpoints_precede_any_project_change(self):
        before=self.project_bytes()
        with self.own() as owned:
            prepared,intent=self.prepared(owned);result=headers.publish(prepared,intent);result.check()
            self.assertEqual(result.nonce,prepared.nonce)
            folder=self.folder(intent);previous=prepared.seal_sha256
            for name in ('header-publications.json','header-000000.done.json','header-000001.done.json','headers-complete.json'):
                raw=(folder/name).read_bytes();value=json.loads(raw)
                self.assertEqual(value['previous'],previous);previous=hashlib.sha256(raw).hexdigest()
            self.assertEqual(result.checkpoint_sha256,previous)
            self.assertEqual((self.root/'store.json').read_bytes(),dict(intent.headers.publications)['store.json'])
            self.assertEqual((self.root/'store.json.bak').read_bytes(),(self.root/'store.json').read_bytes())
        self.assertEqual(self.project_bytes(),before)

    def test_real_rename_order_uses_durable_native_stage_ids_from_the_original_record(self):
        with self.own() as owned:
            prepared,intent=self.prepared(owned);real=os.replace;seen=[]
            def replace(source,target):
                record=json.loads((self.folder(intent)/'header-publications.json').read_bytes())
                expected=record['effects'][len(seen)];native=maintenance_identity.capture(Path(source),entry='file')
                self.assertEqual(expected['identity'],native.document())
                self.assertEqual(expected['sha256'],hashlib.sha256(Path(source).read_bytes()).hexdigest())
                seen.append(Path(target).name);return real(source,target)
            with mock.patch.object(headers,'_rename',side_effect=replace):headers.publish(prepared,intent)
            self.assertEqual(seen,['store.json.bak','store.json'])

    def test_header_temporaries_move_outside_recovery_without_losing_original_bytes(self):
        name='store.json.abcdefgh.tmp';raw=(self.root/'store.json').read_bytes();(self.root/name).write_bytes(raw)
        with self.own() as owned:
            prepared,intent=self.prepared(owned);headers.publish(prepared,intent)
            self.assertFalse((self.root/name).exists())
            self.assertEqual((self.folder(intent)/'header-original-000000.bin').read_bytes(),raw)
            effects=json.loads((self.folder(intent)/'header-publications.json').read_bytes())['effects']
            self.assertEqual(effects[0]['temporary'],name)

    def test_actual_c1_recovery_cannot_reopen_with_a_missing_or_damaged_primary(self):
        (self.root/'store.json.abcdefgh.tmp').write_bytes((self.root/'store.json').read_bytes())
        with self.own() as owned:
            prepared,intent=self.prepared(owned);headers.publish(prepared,intent)
        for condition in ('valid','missing','damaged'):
            with self.subTest(condition=condition),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary)/'memory';shutil.copytree(self.root,root)
                primary=root/'store.json'
                if condition=='missing':primary.unlink()
                elif condition=='damaged':primary.write_bytes(b'{damaged')
                with self.assertRaises(store.StoreUnavailable) as caught:store.MemoryStore(root).record(deadline=time.monotonic()+3)
                self.assertEqual(caught.exception.code,'store-newer')

    def test_original_named_header_hardlink_pair_allows_only_its_own_decrement(self):
        os.link(str(self.root/'store.json'),str(self.root/'store.json.bak'))
        with self.own() as owned:
            prepared,intent=self.prepared(owned);result=headers.publish(prepared,intent);result.check()
            self.assertEqual((self.root/'store.json').stat().st_nlink,1)
            self.assertEqual((self.root/'store.json.bak').stat().st_nlink,1)

    def test_before_each_rename_failure_leaves_only_the_reported_prefix_and_no_project_effect(self):
        before=self.project_bytes()
        for stop in (0,1):
            with self.subTest(stop=stop):
                if stop:self.setUp()
                with self.own() as owned:
                    prepared,intent=self.prepared(owned);real=os.replace;seen=[]
                    def replace(source,target):
                        if len(seen)==stop:raise OSError('fixture boundary')
                        value=real(source,target);seen.append(Path(target).name);return value
                    with mock.patch.object(headers,'_rename',side_effect=replace):
                        with self.assertRaises(OSError) as caught:headers.publish(prepared,intent)
                    self.assertEqual(caught.exception.migration_published,tuple(seen))
                    self.assertEqual(caught.exception.migration_uncertain,('store.json.bak','store.json')[stop])
                    self.assertFalse((self.folder(intent)/'headers-complete.json').exists())
                self.assertEqual(self.project_bytes(),before)

    def test_rename_that_publishes_then_raises_is_uncertain_and_never_rolled_back(self):
        with self.own() as owned:
            prepared,intent=self.prepared(owned);real=os.replace
            def uncertain(source,target):real(source,target);raise OSError('fixture uncertainty')
            with mock.patch.object(headers,'_rename',side_effect=uncertain):
                with self.assertRaises(OSError) as caught:headers.publish(prepared,intent)
            self.assertEqual(caught.exception.migration_published,())
            self.assertEqual(caught.exception.migration_uncertain,'store.json.bak')
            self.assertEqual(json.loads((self.root/'store.json.bak').read_bytes())['format'],2)
            self.assertEqual(json.loads((self.root/'store.json').read_bytes())['format'],1)
            self.assertTrue(caught.exception.cleanup_pending)

    def test_new_stage_sync_failure_never_begins_header_replacement(self):
        with self.own() as owned:
            prepared,intent=self.prepared(owned);before=(self.root/'store.json').read_bytes()
            with mock.patch.object(files,'_sync',side_effect=OSError('fixture sync')),mock.patch.object(headers,'_rename') as effect:
                with self.assertRaises(OSError):headers.publish(prepared,intent)
            effect.assert_not_called();self.assertEqual((self.root/'store.json').read_bytes(),before)

    def test_missing_final_checkpoint_does_not_undo_the_already_fenced_headers(self):
        with self.own() as owned:
            prepared,intent=self.prepared(owned);real=journal._Guard.write
            def write(guard,path,data):
                if json.loads(data).get('headers_complete') is True:raise OSError('fixture checkpoint failure')
                return real(guard,path,data)
            with mock.patch.object(journal._Guard,'write',new=write):
                with self.assertRaises(OSError) as caught:headers.publish(prepared,intent)
            self.assertEqual(caught.exception.migration_published,('store.json.bak','store.json'))
            self.assertIsNone(caught.exception.migration_uncertain)
            self.assertTrue(all(json.loads((self.root/name).read_bytes())['format']==2 for name in ('store.json','store.json.bak')))

    def test_closed_original_owner_cannot_fence_a_preserved_plan(self):
        with self.own() as owned:prepared,intent=self.prepared(owned)
        with self.assertRaises(locks.LostLock):headers.publish(prepared,intent)
        self.assertFalse((self.root/'store.json.bak').exists())

    def test_quiescence_loss_after_first_rename_preserves_original_exception(self):
        with self.own() as owned:
            prepared,intent=self.prepared(owned);real=os.replace
            def replace(source,target):result=real(source,target);self.active=False;return result
            with mock.patch.object(headers,'_rename',side_effect=replace):
                with self.assertRaises(locks.LostLock) as caught:headers.publish(prepared,intent)
            self.assertIs(caught.exception,self.failure)
            self.assertEqual(json.loads((self.root/'store.json').read_bytes())['format'],1)

    def test_unrelated_raw_mutation_after_first_effect_stops_further_header_publication(self):
        with self.own() as owned:
            prepared,intent=self.prepared(owned);real=os.replace
            def replace(source,target):
                value=real(source,target);self.fixture.raw.write_bytes(b'changed fixture');return value
            with mock.patch.object(headers,'_rename',side_effect=replace):
                with self.assertRaises(locks.LostLock):headers.publish(prepared,intent)
            self.assertEqual(json.loads((self.root/'store.json').read_bytes())['format'],1)

    def test_exact_prefix_failure_is_sticky_even_after_expected_bytes_return(self):
        with self.own() as owned:
            prepared,intent=self.prepared(owned);result=headers.publish(prepared,intent)
            path=self.root/'store.json';raw=path.read_bytes();path.write_bytes(b'{}')
            with self.assertRaises(locks.LostLock):result.check()
            path.write_bytes(raw)
            with self.assertRaises(locks.LostLock):result.check()

    def test_a_second_cold_publish_does_not_reuse_the_old_receipt_or_erase_effects(self):
        with self.own() as owned:
            prepared,intent=self.prepared(owned);headers.publish(prepared,intent)
            before=(self.root/'store.json').read_bytes()
            with self.assertRaises(locks.LostLock):headers.publish(prepared,intent)
            self.assertEqual((self.root/'store.json').read_bytes(),before)

    def test_final_owner_callback_cannot_hide_a_changed_destination_before_rename(self):
        with self.own() as owned:
            prepared,intent=self.prepared(owned);real=headers._Prefix._replace
            artifacts=journal._Guard.artifacts;armed=[False];seen=[0]
            def before(prefix,*args):armed[0]=True;return real(prefix,*args)
            def checked(guard):
                artifacts(guard)
                if armed[0]:
                    seen[0]+=1
                    if seen[0]==2:(self.root/'store.json').write_bytes(b'changed by final callback fixture')
            with mock.patch.object(headers._Prefix,'_replace',new=before),mock.patch.object(journal._Guard,'artifacts',new=checked),mock.patch.object(headers,'_rename',side_effect=AssertionError('unsafe rename after callback drift')) as effect:
                with self.assertRaises(locks.LostLock):headers.publish(prepared,intent)
            effect.assert_not_called()
            self.assertEqual((self.root/'store.json').read_bytes(),b'changed by final callback fixture')

    def test_short_checkpoint_stage_write_leaves_no_truncated_named_primary(self):
        with self.own() as owned:
            prepared,intent=self.prepared(owned);real_write=journal._Guard.write;real_os_write=os.write;checkpoint=[False]
            def write(guard,path,data):
                checkpoint[0]=path.name.startswith('checkpoint-')
                return real_write(guard,path,data)
            def short(descriptor,data):
                return real_os_write(descriptor,data[:max(1,len(data)//2)] if checkpoint[0] else data)
            with mock.patch.object(journal._Guard,'write',new=write),mock.patch.object(headers.os,'write',side_effect=short):
                with self.assertRaises(OSError):headers.publish(prepared,intent)
            self.assertFalse((self.folder(intent)/'header-publications.json').exists())
            self.assertTrue(list(self.folder(intent).glob('checkpoint-*.tmp')))
            self.assertEqual(json.loads((self.root/'store.json').read_bytes())['format'],1)

    def test_uncertain_checkpoint_rename_preserves_auxiliary_record_without_canonical_effects(self):
        with self.own() as owned:
            prepared,intent=self.prepared(owned);real=os.replace
            def uncertain(source,target):real(source,target);raise OSError('fixture auxiliary rename uncertainty')
            with mock.patch.object(headers,'_checkpoint_rename',side_effect=uncertain),mock.patch.object(headers,'_rename') as effect:
                with self.assertRaises(OSError):headers.publish(prepared,intent)
            effect.assert_not_called()
            self.assertTrue((self.folder(intent)/'header-publications.json').is_file())
            self.assertEqual(json.loads((self.root/'store.json').read_bytes())['format'],1)
        with self.own() as owned:
            another,new_intent=self.prepared(owned)
            self.assertNotEqual(another.nonce,prepared.nonce)
            self.assertTrue((self.folder(intent)/'header-publications.json').is_file())


if __name__=='__main__':unittest.main()
