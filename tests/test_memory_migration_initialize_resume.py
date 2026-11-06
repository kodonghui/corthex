"""Fresh original-owner initialization resumes on synthetic local stores only."""
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

from _common import ROOT
import test_memory_migration_initialize as fixtures
sys.path.insert(0,str(ROOT/'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import format2,locks,maintenance_identity
from memory_lib import maintenance_journal as journal,migration_headers as headers,migration_initialize as initialize
from memory_lib import migration_initialize_resume as resume


class InitializeResumeTest(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.MigrationInitializeTest();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.root,self.project=self.fx.root,self.fx.project

    def interrupted(self,stop=6,after=True):
        with self.fx.fx.own() as owned:
            fenced,intent=self.fx.fenced(owned);real=headers._rename;seen=[0]
            def rename(source,target):
                index=seen[0];seen[0]+=1
                if index==stop:
                    if after:real(source,target)
                    raise OSError('fixture interrupted initialization')
                return real(source,target)
            with mock.patch.object(headers,'_rename',side_effect=rename):
                with self.assertRaises(OSError):initialize.publish(fenced,verify_c1_lineage=self.fx.lineage)
        return fenced.nonce,intent

    def test_resume_after_progress_primary_keeps_original_round_epochs_and_raw(self):
        before=self.fx.fx.fixture.raw.read_bytes();nonce,intent=self.interrupted()
        folder=self.fx.fx.folder(intent);original=(folder/'plan.json').read_bytes()
        manifest=(folder/'initialization-publications.json').read_bytes()
        with self.fx.fx.own() as owned:
            result=resume.reopen(owned,nonce,verify_c1_lineage=self.fx.lineage);result.check()
            self.assertEqual((self.project/'curation.json').read_bytes(),dict(intent.progress)['sample'])
            self.assertTrue((folder/'initialization-complete.json').exists())
            self.assertIn('migrating',json.loads((self.root/'store.json').read_bytes()))
        self.assertEqual((folder/'plan.json').read_bytes(),original)
        self.assertEqual((folder/'initialization-publications.json').read_bytes(),manifest)
        self.assertEqual(self.fx.fx.fixture.raw.read_bytes(),before)

    def finish(self,nonce):
        with self.fx.fx.own() as owned:
            result=resume.reopen(owned,nonce,verify_c1_lineage=self.fx.lineage);result.check()
            return result

    def test_uncertain_first_directory_is_adopted_only_by_its_recorded_native_id(self):
        nonce,intent=self.interrupted(stop=0,after=True);folder=self.fx.fx.folder(intent)
        self.assertFalse((folder/'initialize-000000.done.json').exists())
        native=maintenance_identity.capture(self.project/'layer')
        self.finish(nonce)
        self.assertEqual(maintenance_identity.capture(self.project/'layer'),native)
        self.assertTrue((folder/'initialize-000000.done.json').exists())

    def test_published_manifest_never_chooses_a_new_round_even_before_first_effect(self):
        nonce,intent=self.interrupted(stop=0,after=False);folder=self.fx.fx.folder(intent)
        manifest=(folder/'initialization-publications.json').read_bytes()
        with mock.patch.object(initialize,'publish',side_effect=AssertionError('no fresh builder after manifest')):self.finish(nonce)
        self.assertEqual((folder/'initialization-publications.json').read_bytes(),manifest)

    def test_entirely_unpublished_orphan_round_and_partial_checkpoint_are_preserved(self):
        with self.fx.fx.own() as owned:
            fenced,intent=self.fx.fenced(owned);real=fenced._prefix._checkpoint
            def checkpoint(name,value):
                if name=='initialization-publications.json':raise OSError('fixture premanifest interruption')
                return real(name,value)
            with mock.patch.object(fenced._prefix,'_checkpoint',side_effect=checkpoint):
                with self.assertRaises(OSError):initialize.publish(fenced,verify_c1_lineage=self.fx.lineage)
        nonce=fenced.nonce;folder=self.fx.fx.folder(intent)
        orphans={p.name:maintenance_identity.capture(p,entry='directory' if p.is_dir() else 'file')
                 for p in folder.iterdir() if p.name.startswith('initialize-')}
        partial=folder/('checkpoint-'+'a'*32+'.tmp');partial.write_bytes(b'{partial fixture')
        self.finish(nonce)
        for name,native in orphans.items():self.assertEqual(maintenance_identity.capture(folder/name,entry=native.document()['entry']),native)
        self.assertEqual(partial.read_bytes(),b'{partial fixture')
        self.assertEqual((self.project/'curation.json').read_bytes(),dict(intent.progress)['sample'])

    def test_copied_published_progress_bytes_do_not_replace_the_recorded_native_identity(self):
        nonce,intent=self.interrupted();path=self.project/'curation.json';raw=path.read_bytes()
        path.rename(self.root.parent/'preserved-copied-progress');path.write_bytes(raw)
        with self.fx.fx.own() as owned:
            with self.assertRaises(resume.InvalidResume):resume.reopen(owned,nonce,verify_c1_lineage=self.fx.lineage)
        self.assertEqual(path.read_bytes(),raw)
        self.assertFalse((self.fx.fx.folder(intent)/'initialization-complete.json').exists())

    def test_unknown_item_content_is_not_read_healed_or_adopted(self):
        nonce,intent=self.interrupted();path=self.project/'layer/items/i_0123456789ab.json';path.write_bytes(b'preserve unknown fixture')
        with self.fx.fx.own() as owned:
            real=owned.inventory._observer.fence.read
            def metadata(candidate,deadline):self.assertNotEqual(candidate,path);return real(candidate,deadline)
            with mock.patch.object(owned.inventory._observer.fence,'read',side_effect=metadata):
                with self.assertRaises(resume.InvalidResume):resume.reopen(owned,nonce,verify_c1_lineage=self.fx.lineage)
        self.assertEqual(path.read_bytes(),b'preserve unknown fixture')

    def test_named_malformed_manifest_is_not_treated_as_absence(self):
        nonce,intent=self.interrupted(stop=0,after=False);folder=self.fx.fx.folder(intent)
        path=folder/'initialization-publications.json';path.write_bytes(b'{}')
        with self.fx.fx.own() as owned:
            with mock.patch.object(initialize,'publish',side_effect=AssertionError('no fresh builder')):
                with self.assertRaises(resume.InvalidResume):resume.reopen(owned,nonce,verify_c1_lineage=self.fx.lineage)
        self.assertEqual(path.read_bytes(),b'{}')

    def test_serialized_round_cannot_supply_a_path(self):
        nonce,intent=self.interrupted(stop=0,after=False);path=self.fx.fx.folder(intent)/'initialization-publications.json'
        value=json.loads(path.read_bytes());value['round']='../../outside';path.write_bytes(journal._bytes(value))
        with self.fx.fx.own() as owned:
            with self.assertRaises(resume.InvalidResume):resume.reopen(owned,nonce,verify_c1_lineage=self.fx.lineage)
        self.assertEqual(json.loads(path.read_bytes())['round'],'../../outside')

    def test_completed_initialization_is_verified_without_any_republication(self):
        nonce,intent=self.interrupted(stop=12,after=True);self.finish(nonce)
        before=(self.fx.fx.folder(intent)/'initialization-complete.json').read_bytes()
        with mock.patch.object(headers,'_rename',side_effect=AssertionError('no repeated canonical effect')),mock.patch.object(headers,'_checkpoint_rename',side_effect=AssertionError('no repeated checkpoint')):
            self.finish(nonce)
        self.assertEqual((self.fx.fx.folder(intent)/'initialization-complete.json').read_bytes(),before)

    def test_any_completed_header_defers_without_overwriting_later_c2_data(self):
        nonce,_=self.interrupted();self.finish(nonce)
        header=self.root/'store.json.bak';value=json.loads(header.read_bytes());value.pop('migrating');header.write_bytes(format2.store_bytes(value))
        state=self.project/'layer/state.json';state.write_bytes(b'preserve later C2 fixture')
        with self.assertRaises(ValueError):
            with self.fx.fx.own():self.fail('completed header must not admit initialization')
        self.assertEqual(state.read_bytes(),b'preserve later C2 fixture')

    def test_original_lineage_exception_is_preserved_and_scope_is_not_revived(self):
        nonce,_=self.interrupted(stop=0,after=True);original=ValueError('fixture renewed lineage refusal')
        def lineage(*args):raise original
        with self.fx.fx.own() as owned:
            with self.assertRaises(ValueError) as caught:resume.reopen(owned,nonce,verify_c1_lineage=lineage)
            self.assertIs(caught.exception,original)
            with self.assertRaises(locks.LostLock):resume.reopen(owned,nonce,verify_c1_lineage=self.fx.lineage)

    def test_renewed_lineage_returns_only_none_and_failure_revokes_the_scope(self):
        nonce,_=self.interrupted(stop=0,after=False)
        with self.fx.fx.own() as owned:
            with self.assertRaises(TypeError):resume.reopen(owned,nonce,verify_c1_lineage=lambda *args:True)
            with self.assertRaises(locks.LostLock):resume.reopen(owned,nonce,verify_c1_lineage=self.fx.lineage)

    def test_uncertain_directory_is_flushed_before_reconstructed_checkpoint(self):
        nonce,intent=self.interrupted(stop=0,after=True);folder=self.fx.fx.folder(intent);events=[]
        barrier=journal._Guard.directory_barrier;rename=headers._checkpoint_rename
        def synced(guard,path,**kwargs):events.append(Path(path));return barrier(guard,path,**kwargs)
        def checkpoint(source,target):
            if Path(target).name=='initialize-000000.done.json':
                for path in (self.root,self.project,self.project/'layer',folder):self.assertIn(path,events)
            return rename(source,target)
        with mock.patch.object(journal._Guard,'directory_barrier',new=synced),mock.patch.object(headers,'_checkpoint_rename',side_effect=checkpoint):self.finish(nonce)

    def test_existing_initialization_must_flush_and_refuses_an_original_barrier_error(self):
        nonce,_=self.interrupted();self.finish(nonce);original=OSError('fixture completed initialization barrier')
        barrier=journal._Guard.directory_barrier
        def synced(guard,path,**kwargs):
            if Path(path)==self.project/'layer':raise original
            return barrier(guard,path,**kwargs)
        with self.fx.fx.own() as owned:
            with mock.patch.object(journal._Guard,'directory_barrier',new=synced):
                with self.assertRaises(OSError) as caught:resume.reopen(owned,nonce,verify_c1_lineage=self.fx.lineage)
            self.assertIs(caught.exception,original)
            with self.assertRaises(locks.LostLock):owned.check()

    def test_returned_initialized_resume_failure_revokes_the_original_owner(self):
        nonce,intent=self.interrupted();unknown=self.fx.fx.folder(intent)/'unexpected-after-resume'
        with self.fx.fx.own() as owned:
            result=resume.reopen(owned,nonce,verify_c1_lineage=self.fx.lineage);unknown.write_bytes(b'preserve fixture')
            with self.assertRaises(locks.LostLock):result.check()
            unknown.unlink()
            with self.assertRaises(locks.LostLock):owned.check()
            with self.assertRaises(locks.LostLock):resume.reopen(owned,nonce,verify_c1_lineage=self.fx.lineage)

    def test_reused_dead_c1_named_header_identity_does_not_reserve_a_future_initialization_node(self):
        nonce,intent=self.interrupted();folder=self.fx.fx.folder(intent)
        historical=json.loads((folder/'prepared.json').read_bytes())['source_records']['store.json']
        current=maintenance_identity.capture(self.project/'curation.json',entry='file');parse=resume._identity
        def reused(value):return current if value==historical else parse(value)
        with mock.patch.object(resume,'_identity',side_effect=reused):
            try:self.finish(nonce)
            except resume.InvalidResume:self.fail('a dead historical named-header ID cannot reserve a future node')

    def test_boolean_checkpoint_version_is_not_an_integer_protocol(self):
        nonce,intent=self.interrupted(stop=1,after=False);path=self.fx.fx.folder(intent)/'initialize-000000.done.json'
        value=json.loads(path.read_bytes());value['version']=True;path.write_bytes(journal._bytes(value))
        with self.fx.fx.own() as owned:
            with self.assertRaises(resume.InvalidResume):resume.reopen(owned,nonce,verify_c1_lineage=self.fx.lineage)


if __name__=='__main__':unittest.main()
