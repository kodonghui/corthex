"""TC-390 partial: cold preservation/fault fixtures, not host or power-fail proof."""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time
import unittest
from unittest import mock

from _common import ROOT
import test_memory_migration_inventory as fixtures
sys.path.insert(0,str(ROOT/'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import files,locks,maintenance_identity,maintenance_journal as journal,migration_intent


class MaintenanceJournalTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.MigrationInventoryTest();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root,self.project=self.fixture.root.resolve(),self.fixture.project
        self.active=True;self.failure=locks.LostLock()

    def quiet(self,*args):
        if not self.active:raise self.failure

    def own(self):
        from memory_lib import maintenance_owner
        return maintenance_owner.acquire(self.root,release='0.3.0',when=fixtures.LATER,
            deadline=time.monotonic()+60,verify_quiescence=self.quiet)

    def prepare(self,owned):
        binding=maintenance_identity.bind(self.root)
        return migration_intent.prepare(owned,binding),binding

    def folder(self,intent):
        return self.root/'.maintenance/format-1-to-2'/json.loads(intent.encoded)['nonce']

    def canonical(self):
        return {name:value for name,value in self.fixture.tree().items() if not name.startswith('.maintenance')}

    def test_exact_originals_plan_and_seal_are_outside_recovery_and_canonical_data_unchanged(self):
        before=self.canonical()
        with self.own() as owned:
            intent,binding=self.prepare(owned);prepared=journal.preserve(owned,intent,binding)
            prepared.check();prepared.check_artifacts();folder=self.folder(intent)
            self.assertEqual((folder/'plan.json').read_bytes(),intent.encoded)
            for slot,raw in intent.originals:self.assertEqual((folder/('original-%06d.bin'%slot)).read_bytes(),raw)
            seal=json.loads((folder/'prepared.json').read_bytes())
            self.assertEqual(hashlib.sha256((folder/'prepared.json').read_bytes()).hexdigest(),prepared.seal_sha256)
            self.assertEqual(seal['plan_sha256'],hashlib.sha256(intent.encoded).hexdigest())
            self.assertEqual(seal['source_records']['store.json'],maintenance_identity.capture(self.root/'store.json',entry='file').document())
            self.assertNotIn('prepared.json',seal['files'])
        self.assertEqual(self.canonical(),before)

    def test_raw_payloads_are_not_opened_or_copied(self):
        with self.own() as owned:
            intent,binding=self.prepare(owned);real=owned.inventory._observer.fence.read;opened=[]
            def metadata(path,deadline):
                self.assertNotEqual(path,self.fixture.raw);opened.append(path);return real(path,deadline)
            with mock.patch.object(owned.inventory._observer.fence,'read',side_effect=metadata):
                journal.preserve(owned,intent,binding)
            self.assertTrue(opened)
            self.assertFalse(any(b'private raw bytes' in p.read_bytes() for p in self.folder(intent).iterdir()))

    def test_blob_and_plan_sync_finishes_before_seal_starts(self):
        with self.own() as owned:
            intent,binding=self.prepare(owned);events=[];real=journal._Guard.write;real_sync=files._sync;current=[None]
            def write(guard,path,data):
                current[0]=path.name
                events.append(('before',path.name));real(guard,path,data);events.append(('after',path.name))
            def sync(descriptor):
                if stat.S_ISREG(os.fstat(descriptor).st_mode):events.append(('synced-file',current[0]))
                return real_sync(descriptor)
            with mock.patch.object(journal._Guard,'write',new=write),mock.patch.object(files,'_sync',side_effect=sync):
                journal.preserve(owned,intent,binding)
            boundary=events.index(('before','prepared.json'))
            for slot,_ in intent.originals:
                name='original-%06d.bin'%slot
                self.assertLess(events.index(('synced-file',name)),events.index(('after',name)))
                self.assertLess(events.index(('after',name)),boundary)
            self.assertLess(events.index(('synced-file','plan.json')),boundary)
            self.assertLess(events.index(('after','plan.json')),boundary)

    @unittest.skipIf(os.name=='nt','POSIX private modes')
    def test_new_artifacts_are_private_and_directories_are_synced(self):
        with self.own() as owned:
            intent,binding=self.prepare(owned);kinds=[];real=files._sync
            def sync(descriptor):kinds.append(os.fstat(descriptor).st_mode);real(descriptor)
            old_umask=os.umask(0o777)
            try:
                with mock.patch.object(files,'_sync',side_effect=sync):journal.preserve(owned,intent,binding)
            finally:os.umask(old_umask)
            self.assertTrue(any(stat.S_ISDIR(mode) for mode in kinds))
            self.assertTrue(any(stat.S_ISREG(mode) for mode in kinds))
            folder=self.folder(intent)
            self.assertEqual(stat.S_IMODE(folder.stat().st_mode),0o700)
            self.assertTrue(all(stat.S_IMODE(path.stat().st_mode)==0o600 for path in folder.iterdir()))

    def test_existing_unrelated_auxiliary_content_is_preserved(self):
        path=self.root/'.maintenance/other';path.mkdir(parents=True);(path/'untouched').write_bytes(b'preserve fixture')
        with self.own() as owned:
            intent,binding=self.prepare(owned);journal.preserve(owned,intent,binding)
        self.assertEqual((path/'untouched').read_bytes(),b'preserve fixture')

    def test_preexisting_nonce_is_never_overwritten_or_adopted(self):
        with self.own() as owned:
            intent,binding=self.prepare(owned);journal.preserve(owned,intent,binding)
        before=self.fixture.tree()
        with self.own() as owned:
            with self.assertRaises(locks.LostLock):journal.preserve(owned,intent,maintenance_identity.bind(self.root))
        self.assertEqual(self.fixture.tree(),before)

    def test_non_directory_auxiliary_path_refuses_without_replacing_it(self):
        path=self.root/'.maintenance';path.write_bytes(b'not a directory');before=self.fixture.tree()
        with self.own() as owned:
            intent,binding=self.prepare(owned)
            with self.assertRaises(locks.LostLock):journal.preserve(owned,intent,binding)
        self.assertEqual(self.fixture.tree(),before)

    def test_changed_intent_root_and_original_bytes_refuse_before_any_auxiliary_effect(self):
        with self.own() as owned:
            intent,binding=self.prepare(owned)
            value=json.loads(intent.encoded);value['root']['path_sha256']='0'*64
            changed=migration_intent.parse(fixtures.data(value),intent.originals)
            with self.assertRaises(migration_intent.InvalidIntent):journal.preserve(owned,changed,binding)
            self.assertFalse((self.root/'.maintenance').exists())

    def test_changed_source_after_preparation_is_not_healed_or_archived(self):
        with self.own() as owned:
            intent,binding=self.prepare(owned);path=self.project/'curation.json';path.write_bytes(b'{}')
            with self.assertRaises(locks.LostLock):journal.preserve(owned,intent,binding)
            self.assertEqual(path.read_bytes(),b'{}');self.assertFalse((self.root/'.maintenance').exists())

    def test_short_write_preserves_partial_auxiliary_data_without_a_seal_or_canonical_change(self):
        before=self.canonical()
        with self.own() as owned:
            intent,binding=self.prepare(owned);real=os.write
            def short(descriptor,raw):return real(descriptor,raw[:max(1,len(raw)//2)])
            with mock.patch.object(journal.os,'write',side_effect=short):
                with self.assertRaises(OSError):journal.preserve(owned,intent,binding)
            folder=self.folder(intent);self.assertTrue(any(folder.iterdir()));self.assertFalse((folder/'prepared.json').exists())
        self.assertEqual(self.canonical(),before)

    def test_sync_failure_never_publishes_any_header_and_does_not_delete_partial_data(self):
        before=self.canonical()
        with self.own() as owned:
            intent,binding=self.prepare(owned)
            with mock.patch.object(files,'_sync',side_effect=OSError('fixture sync failure')):
                with self.assertRaises(OSError):journal.preserve(owned,intent,binding)
            self.assertTrue((self.root/'.maintenance').exists())
        self.assertEqual(self.canonical(),before)

    def test_each_regular_file_sync_boundary_can_fail_without_canonical_effects(self):
        before=self.canonical()
        for stop in range(1,6):
            with self.subTest(stop=stop),self.own() as owned:
                intent,binding=self.prepare(owned);seen=[0];real=files._sync
                self.assertEqual(len(intent.originals)+2,5)
                def sync(descriptor):
                    if stat.S_ISREG(os.fstat(descriptor).st_mode):
                        seen[0]+=1
                        if seen[0]==stop:raise OSError('fixture boundary failure')
                    return real(descriptor)
                with mock.patch.object(files,'_sync',side_effect=sync):
                    with self.assertRaises(OSError):journal.preserve(owned,intent,binding)
                self.assertEqual(seen[0],stop)
            self.assertEqual(self.canonical(),before)

    def test_metadata_larger_than_a_chunk_is_preserved_completely(self):
        raw=fixtures.data(dict(fixtures.HEADER,release='fixture-'+('x'*140000)))
        (self.root/'store.json').write_bytes(raw)
        with self.own() as owned:
            intent,binding=self.prepare(owned);sizes=[];real=os.write
            def write(descriptor,data):sizes.append(len(data));return real(descriptor,data)
            with mock.patch.object(journal.os,'write',side_effect=write):journal.preserve(owned,intent,binding)
            self.assertIn(65536,sizes);self.assertLessEqual(max(sizes),65536)
            archived=[path.read_bytes() for path in self.folder(intent).glob('original-*.bin')]
            self.assertIn(raw,archived);self.assertEqual((self.root/'store.json').read_bytes(),raw)

    def test_close_failure_does_not_return_a_prepared_receipt(self):
        before=self.canonical()
        with self.own() as owned:
            intent,binding=self.prepare(owned);real=os.close;real_open=os.open;failed=[False];writers=set()
            def opened(path,flags,*args):
                descriptor=real_open(path,flags,*args)
                if flags & os.O_WRONLY:writers.add(descriptor)
                return descriptor
            def close(descriptor):
                ours=descriptor in writers
                real(descriptor)
                writers.discard(descriptor)
                if ours and not failed[0]:failed[0]=True;raise OSError('fixture close uncertainty')
            with mock.patch.object(journal.os,'open',side_effect=opened),mock.patch.object(journal.os,'close',side_effect=close):
                with self.assertRaises(OSError):journal.preserve(owned,intent,binding)
        self.assertEqual(self.canonical(),before)

    def test_preserved_artifact_changes_revoke_the_receipt_even_after_bytes_are_restored(self):
        with self.own() as owned:
            intent,binding=self.prepare(owned);prepared=journal.preserve(owned,intent,binding)
            path=self.folder(intent)/'plan.json';raw=path.read_bytes();path.write_bytes(b'{}')
            with self.assertRaises(locks.LostLock):prepared.check_artifacts()
            path.write_bytes(raw)
            with self.assertRaises(locks.LostLock):prepared.check_artifacts()

    def test_extra_hardlink_to_preserved_metadata_is_refused_and_removal_cannot_revive(self):
        with self.own() as owned:
            intent,binding=self.prepare(owned);prepared=journal.preserve(owned,intent,binding)
            path=self.folder(intent)/'plan.json';alias=self.root/'extra-link';os.link(str(path),str(alias))
            with self.assertRaises(locks.LostLock):prepared.check_artifacts()
            alias.unlink()
            with self.assertRaises(locks.LostLock):prepared.check_artifacts()

    def test_unknown_extra_artifact_is_not_deleted_or_accepted(self):
        with self.own() as owned:
            intent,binding=self.prepare(owned);prepared=journal.preserve(owned,intent,binding)
            path=self.folder(intent)/'unknown';path.write_bytes(b'preserve this fixture')
            with self.assertRaises(locks.LostLock):prepared.check_artifacts()
            self.assertEqual(path.read_bytes(),b'preserve this fixture')

    def test_closed_original_owner_cannot_validate_preservation(self):
        with self.own() as owned:
            intent,binding=self.prepare(owned);prepared=journal.preserve(owned,intent,binding)
        with self.assertRaises(locks.LostLock):prepared.check_artifacts()

    def test_quiescence_loss_during_write_preserves_the_original_exception_and_stops_effects(self):
        with self.own() as owned:
            intent,binding=self.prepare(owned);real=os.write
            def write(descriptor,raw):
                result=real(descriptor,raw);self.active=False;return result
            with mock.patch.object(journal.os,'write',side_effect=write):
                with self.assertRaises(locks.LostLock) as caught:journal.preserve(owned,intent,binding)
            self.assertIs(caught.exception,self.failure)
            self.assertFalse((self.folder(intent)/'prepared.json').exists())

    def test_original_pid_is_required_and_failure_is_sticky(self):
        with self.own() as owned:
            intent,binding=self.prepare(owned);prepared=journal.preserve(owned,intent,binding)
            with mock.patch.object(journal.os,'getpid',return_value=os.getpid()+1):
                with self.assertRaises(locks.LostLock):prepared.check_artifacts()
            with self.assertRaises(locks.LostLock):prepared.check_artifacts()

    def test_header_change_does_not_turn_artifact_evidence_into_effect_authority(self):
        with self.own() as owned:
            intent,binding=self.prepare(owned);prepared=journal.preserve(owned,intent,binding)
            (self.root/'store.json').write_bytes(dict(intent.headers.publications)['store.json'])
            prepared.check_artifacts()
            with self.assertRaises(locks.LostLock):prepared.check()
            with self.assertRaises(locks.LostLock):prepared.check_artifacts()

    def test_orphan_before_named_fence_is_preserved_when_another_cold_plan_is_prepared(self):
        with self.own() as owned:
            first,binding=self.prepare(owned);journal.preserve(owned,first,binding)
        old={p.name:p.read_bytes() for p in self.folder(first).iterdir()}
        with self.own() as owned:
            second,binding=self.prepare(owned);journal.preserve(owned,second,binding)
        self.assertNotEqual(self.folder(first),self.folder(second))
        self.assertEqual(old,{p.name:p.read_bytes() for p in self.folder(first).iterdir()})
        self.assertEqual(json.loads((self.root/'store.json').read_bytes())['format'],1)


if __name__=='__main__':unittest.main()
