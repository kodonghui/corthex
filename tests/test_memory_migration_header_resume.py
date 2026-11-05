"""Renewed interval fixtures; no production quiescence or initialization proof."""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

from _common import ROOT
import test_memory_migration_headers as fixtures
sys.path.insert(0,str(ROOT/'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import format2,locks,maintenance_identity,maintenance_journal as journal
from memory_lib import migration_header_resume as resume,migration_headers as headers


class HeaderResumeTest(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.MigrationHeadersTest();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.root=self.fx.root

    def interrupted(self,index=1,after=False):
        with self.fx.own() as owned:
            prepared,intent=self.fx.prepared(owned);real=headers._rename;count=[0]
            def rename(source,target):
                current=count[0];count[0]+=1
                if current==index:
                    if after:real(source,target)
                    raise OSError('fixture interruption')
                return real(source,target)
            with mock.patch.object(headers,'_rename',side_effect=rename):
                with self.assertRaises(OSError):headers.publish(prepared,intent)
        return prepared.nonce,intent

    def finish(self,nonce):
        with self.fx.own() as owned:
            result=resume.reopen(owned,nonce);result.check()
            self.assertEqual(json.loads((self.root/'store.json').read_bytes())['format'],2)
            self.assertIn('migrating',json.loads((self.root/'store.json').read_bytes()))
            self.assertEqual((self.root/'store.json').read_bytes(),(self.root/'store.json.bak').read_bytes())
            return result

    def test_resume_before_primary_reuses_exact_native_stage_and_fixed_plan(self):
        before=self.fx.project_bytes();nonce,intent=self.interrupted()
        path=self.fx.folder(intent);original=(path/'plan.json').read_bytes()
        stage=maintenance_identity.capture(path/'header-stage-000001.bin',entry='file')
        self.finish(nonce)
        self.assertEqual(maintenance_identity.capture(self.root/'store.json',entry='file'),stage)
        self.assertEqual((path/'plan.json').read_bytes(),original)
        self.assertEqual(self.fx.project_bytes(),before)

    def test_uncertain_backup_publication_reconstructs_only_the_missing_checkpoint(self):
        nonce,intent=self.interrupted(index=0,after=True);folder=self.fx.folder(intent)
        self.assertFalse((folder/'header-000000.done.json').exists())
        self.finish(nonce)
        self.assertTrue((folder/'header-000000.done.json').exists())
        self.assertTrue((folder/'headers-complete.json').exists())

    def test_uncertain_primary_publication_does_not_repeat_any_canonical_rename(self):
        nonce,intent=self.interrupted(index=1,after=True)
        with mock.patch.object(headers,'_rename',side_effect=AssertionError('no repeated effect')):self.finish(nonce)

    def test_a_completed_header_fence_can_be_checked_by_a_new_owner_without_rewriting(self):
        nonce,_=self.interrupted();self.finish(nonce)
        with mock.patch.object(headers,'_rename',side_effect=AssertionError('no rename')),mock.patch.object(headers,'_checkpoint_rename',side_effect=AssertionError('no checkpoint rewrite')):
            self.finish(nonce)

    def test_no_named_migrating_header_refuses_an_orphan_even_with_a_complete_plan(self):
        nonce,_=self.interrupted(index=0)
        before=self.fx.project_bytes()
        with self.fx.own() as owned:
            with self.assertRaises(resume.InvalidResume):resume.reopen(owned,nonce)
        self.assertEqual(self.fx.project_bytes(),before)
        self.assertFalse((self.root/'store.json.bak').exists())

    def test_current_completed_header_refuses_admission_before_any_reinitialization(self):
        nonce,intent=self.interrupted();self.finish(nonce)
        value=json.loads((self.root/'store.json').read_bytes());value.pop('migrating')
        (self.root/'store.json').write_bytes(format2.store_bytes(value));before=self.fx.project_bytes()
        with self.assertRaises(ValueError):
            with self.fx.own():self.fail('completed-header interval must not admit')
        self.assertEqual(self.fx.project_bytes(),before)

    def test_postinitialization_progress_is_preserved_and_deferred_to_its_owner(self):
        nonce,intent=self.interrupted();self.finish(nonce)
        converted=dict(intent.progress)['sample'];(self.fx.fixture.project/'curation.json').write_bytes(converted)
        with self.fx.own() as owned:
            with self.assertRaises(resume.InvalidResume):resume.reopen(owned,nonce)
        self.assertEqual((self.fx.fixture.project/'curation.json').read_bytes(),converted)

    def test_copied_migrating_header_cannot_claim_the_original_stage_identity(self):
        nonce,_=self.interrupted();path=self.root/'store.json.bak';raw=path.read_bytes()
        path.rename(self.root/'saved-header');path.write_bytes(raw)
        with self.fx.own() as owned:
            with self.assertRaises(resume.InvalidResume):resume.reopen(owned,nonce)
        self.assertEqual(path.read_bytes(),raw)
        self.assertEqual(json.loads((self.root/'store.json').read_bytes())['format'],1)

    def test_changed_primary_checkpoint_is_not_restored_from_any_sidecar(self):
        nonce,intent=self.interrupted();path=self.fx.folder(intent)/'header-000000.done.json'
        original=path.read_bytes();path.write_bytes(b'{}')
        (path.with_name(path.name+'.bak')).write_bytes(original)
        with self.fx.own() as owned:
            with self.assertRaises(resume.InvalidResume):resume.reopen(owned,nonce)
        self.assertEqual(path.read_bytes(),b'{}')
        self.assertTrue(path.with_name(path.name+'.bak').exists())

    def test_boolean_checkpoint_version_is_not_accepted_as_integer_one(self):
        nonce,intent=self.interrupted();path=self.fx.folder(intent)/'header-000000.done.json'
        value=json.loads(path.read_bytes());value['version']=True;path.write_bytes(journal._bytes(value))
        with self.fx.own() as owned:
            with self.assertRaises(resume.InvalidResume):resume.reopen(owned,nonce)

    def test_partial_unpublished_checkpoint_staging_stays_preserved(self):
        nonce,intent=self.interrupted(index=0,after=True);path=self.fx.folder(intent)/('checkpoint-'+'a'*32+'.tmp')
        path.write_bytes(b'{partial fixture')
        self.finish(nonce);self.assertEqual(path.read_bytes(),b'{partial fixture')

    def test_unknown_auxiliary_file_is_preserved_and_original_scope_stays_revoked(self):
        nonce,intent=self.interrupted();path=self.fx.folder(intent)/'unknown';path.write_bytes(b'preserve fixture')
        with self.fx.own() as owned:
            with self.assertRaises(resume.InvalidResume):resume.reopen(owned,nonce)
            path.unlink()
            with self.assertRaises(locks.LostLock):resume.reopen(owned,nonce)

    def test_replaced_root_or_foreign_nonce_cannot_rebind_sealed_originals(self):
        nonce,intent=self.interrupted();folder=self.fx.folder(intent);value=json.loads((folder/'plan.json').read_bytes())
        value['root']['path_sha256']='0'*64;(folder/'plan.json').write_bytes(journal._bytes(value))
        with self.fx.own() as owned:
            with self.assertRaises(resume.InvalidResume):resume.reopen(owned,nonce)
        self.assertEqual(json.loads((self.root/'store.json').read_bytes())['format'],1)

    def test_new_raw_scope_is_owned_afresh_and_no_raw_text_is_read_or_rewritten(self):
        nonce,_=self.interrupted();raw=self.fx.fixture.project/'raw/codex-fedcba9876543210.jsonl';raw.write_bytes(b'new local fixture')
        before=self.fx.project_bytes()
        with self.fx.own() as owned:
            self.assertIn(('raw','projects/sample/raw/codex-fedcba9876543210.lock'),owned.inventory.leases)
            original=owned.inventory._observer.fence.read
            def metadata(path,deadline):
                self.assertNotEqual(path,raw);self.assertNotEqual(path,self.fx.fixture.raw)
                return original(path,deadline)
            with mock.patch.object(owned.inventory._observer.fence,'read',side_effect=metadata):resume.reopen(owned,nonce)
        self.assertEqual(self.fx.project_bytes(),before)

    def test_original_owner_exception_is_not_reclassified_as_a_codec_failure(self):
        nonce,_=self.interrupted();original=ValueError('fixture original interval refusal')
        with self.fx.own() as owned:
            with mock.patch.object(type(owned),'check',side_effect=original):
                with self.assertRaises(ValueError) as caught:resume.reopen(owned,nonce)
            self.assertIs(caught.exception,original)


if __name__=='__main__':unittest.main()
