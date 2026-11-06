"""Synthetic original-owner finalization gates, never real host lineage proof."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

from _common import ROOT
import test_memory_migration_initialize as fixtures
sys.path.insert(0,str(ROOT/'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import format2,locks,maintenance_identity
from memory_lib import migration_headers as headers,migration_initialize as initialize,migration_finalize as finalize


class MigrationFinalizeTest(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.MigrationInitializeTest();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.root,self.project=self.fx.root,self.fx.project

    def initialized(self,owned):
        fenced,intent=self.fx.fenced(owned)
        return initialize.publish(fenced,verify_c1_lineage=self.fx.lineage),intent

    def privacy(self,root,context,projects):self.fx.lineage(root,context,projects)

    def publish(self,value,**changes):
        checks=dict(verify_c1_lineage=self.fx.lineage,verify_current_privacy=self.privacy);checks.update(changes)
        return finalize.publish(value,**checks)

    def test_backup_then_primary_complete_preserves_all_project_bytes_and_epochs(self):
        raw=self.fx.fx.fixture.raw.read_bytes()
        with self.fx.fx.own() as owned:
            value,intent=self.initialized(owned);before=self.fx.fx.project_bytes();real=headers._rename;seen=[]
            def rename(source,target):
                plan=json.loads((self.fx.fx.folder(intent)/'final-header-publications.json').read_bytes())
                effect=plan['effects'][len(seen)]
                self.assertEqual(maintenance_identity.capture(Path(source),entry='file').document(),effect['identity'])
                self.assertEqual(effect['target'],Path(target).name)
                self.assertEqual(plan['initialization_sha256'],value.checkpoint_sha256)
                self.assertNotEqual(plan['effects'][0]['identity'],plan['effects'][1]['identity'])
                seen.append(effect['target']);return real(source,target)
            with mock.patch.object(headers,'_rename',side_effect=rename):result=self.publish(value)
            result.check();self.assertEqual(seen,['store.json.bak','store.json'])
            self.assertEqual(self.fx.fx.project_bytes(),before)
            for name in seen:self.assertNotIn('migrating',format2.parse_store((self.root/name).read_bytes()))
            complete=json.loads((self.fx.fx.folder(intent)/'migration-complete.json').read_bytes())
            self.assertEqual((complete['completed'],complete['writer_protocol'],complete['lifecycle_protocol']),(True,1,1))
            self.assertEqual(complete['initialization_sha256'],value.checkpoint_sha256)
        self.assertEqual(self.fx.fx.fixture.raw.read_bytes(),raw)

    def test_a_fenced_header_is_not_an_initialized_capability(self):
        with self.fx.fx.own() as owned:
            fenced,intent=self.fx.fenced(owned)
            with self.assertRaises(TypeError):self.publish(fenced)
            self.assertFalse((self.fx.fx.folder(intent)/'final-header-publications.json').exists())

    def test_changed_completion_pointer_cannot_supply_initialization(self):
        with self.fx.fx.own() as owned:
            value,intent=self.initialized(owned)
            with self.assertRaises(finalize.InvalidFinalization):self.publish(replace(value,checkpoint_sha256='0'*64))
            self.assertFalse((self.fx.fx.folder(intent)/'final-header-publications.json').exists())
            with self.assertRaises(locks.LostLock):value.check()

    def test_current_privacy_requires_callable_and_only_none(self):
        with self.fx.fx.own() as owned:
            value,intent=self.initialized(owned)
            with self.assertRaises(TypeError):self.publish(value,verify_current_privacy=None)
            with self.assertRaises(TypeError):self.publish(value,verify_current_privacy=lambda *args:True)
            self.assertFalse((self.fx.fx.folder(intent)/'final-header-publications.json').exists())
            with self.assertRaises(locks.LostLock):value.check()

    def test_original_privacy_exception_retains_identity_and_repeated_use_refuses(self):
        original=ValueError('fixture original current privacy refusal')
        def privacy(*args):raise original
        with self.fx.fx.own() as owned:
            value,intent=self.initialized(owned)
            with self.assertRaises(ValueError) as caught:self.publish(value,verify_current_privacy=privacy)
            self.assertIs(caught.exception,original)
            self.assertFalse((self.fx.fx.folder(intent)/'final-header-publications.json').exists())
            with self.assertRaises(locks.LostLock):self.publish(value)

    def test_last_privacy_callback_source_change_prevents_any_final_header_write(self):
        with self.fx.fx.own() as owned:
            value,intent=self.initialized(owned);state=self.project/'layer/state.json';source=state.read_bytes();changed=[False]
            def privacy(*args):
                if not changed[0]:state.write_bytes(source+b' ');changed[0]=True
            with self.assertRaises(locks.LostLock):self.publish(value,verify_current_privacy=privacy)
            self.assertEqual(state.read_bytes(),source+b' ')
            self.assertFalse((self.fx.fx.folder(intent)/'final-header-stage-000000.bin').exists())
            self.assertIn('migrating',json.loads((self.root/'store.json.bak').read_bytes()))

    def test_backup_publication_then_exception_preserves_the_completed_header(self):
        with self.fx.fx.own() as owned:
            value,intent=self.initialized(owned);before=self.fx.fx.project_bytes();real=headers._rename
            def rename(source,target):real(source,target);raise OSError('fixture completed backup uncertainty')
            with mock.patch.object(headers,'_rename',side_effect=rename):
                with self.assertRaises(OSError) as caught:self.publish(value)
            self.assertEqual(caught.exception.migration_uncertain,'store.json.bak')
            self.assertNotIn('migrating',json.loads((self.root/'store.json.bak').read_bytes()))
            self.assertIn('migrating',json.loads((self.root/'store.json').read_bytes()))
            self.assertEqual(self.fx.fx.project_bytes(),before)
            self.assertFalse((self.fx.fx.folder(intent)/'migration-complete.json').exists())
        with self.assertRaises(ValueError):
            with self.fx.fx.own():self.fail('completed header must defer to finalization-only owner')

    def test_missing_backup_checkpoint_preserves_verified_effect_without_clearing_primary(self):
        with self.fx.fx.own() as owned:
            value,intent=self.initialized(owned);real=value._prefix._checkpoint
            def checkpoint(name,body):
                if name=='final-header-000000.done.json':raise OSError('fixture completed backup checkpoint')
                return real(name,body)
            with mock.patch.object(value._prefix,'_checkpoint',side_effect=checkpoint):
                with self.assertRaises(OSError) as caught:self.publish(value)
            self.assertIsNone(caught.exception.migration_uncertain)
            self.assertEqual(caught.exception.migration_published[-1],'store.json.bak')
            self.assertNotIn('migrating',json.loads((self.root/'store.json.bak').read_bytes()))
            self.assertIn('migrating',json.loads((self.root/'store.json').read_bytes()))
            self.assertFalse((self.fx.fx.folder(intent)/'final-header-000000.done.json').exists())

    def test_failure_after_both_headers_never_grants_completion_or_reinitialization(self):
        with self.fx.fx.own() as owned:
            value,intent=self.initialized(owned);real=value._prefix._checkpoint;before=self.fx.fx.project_bytes()
            def checkpoint(name,body):
                if name=='migration-complete.json':raise OSError('fixture final completion uncertainty')
                return real(name,body)
            with mock.patch.object(value._prefix,'_checkpoint',side_effect=checkpoint):
                with self.assertRaises(OSError):self.publish(value)
            for name in ('store.json.bak','store.json'):self.assertNotIn('migrating',json.loads((self.root/name).read_bytes()))
            self.assertFalse((self.fx.fx.folder(intent)/'migration-complete.json').exists())
            self.assertEqual(self.fx.fx.project_bytes(),before)
            with self.assertRaises(locks.LostLock):self.publish(value)


    def test_returned_finalized_check_failure_revokes_the_original_interval(self):
        with self.fx.fx.own() as owned:
            value,intent=self.initialized(owned);result=self.publish(value)
            unknown=self.fx.fx.folder(intent)/'unexpected-after-finalize';unknown.write_bytes(b'preserve fixture')
            with self.assertRaises(locks.LostLock):result.check()
            unknown.unlink()
            with self.assertRaises(locks.LostLock):owned.check()


if __name__=='__main__':unittest.main()
