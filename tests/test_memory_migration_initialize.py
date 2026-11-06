"""Supported-C1 callback fixtures, not actual host/lineage or activation proof."""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

from _common import ROOT
import test_memory_migration_headers as fixtures
sys.path.insert(0,str(ROOT/'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import format2,item_types,locks,maintenance_identity,state_types
from memory_lib import migration_headers as headers,migration_initialize as initialize


class MigrationInitializeTest(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.MigrationHeadersTest();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.root,self.project=self.fx.root,self.fx.fixture.project

    def fenced(self,owned):
        prepared,intent=self.fx.prepared(owned)
        return headers.publish(prepared,intent),intent

    def lineage(self,root,context,projects):
        self.assertEqual(root,self.root)
        self.assertEqual((context['device'],context['release']),('d_0123456789ab','0.3.0'))
        self.assertEqual(projects,('sample',))

    def test_actual_initialization_preserves_raw_progress_and_records_protocol_only_after_effects(self):
        raw=self.fx.fixture.raw.read_bytes()
        with self.fx.own() as owned:
            fenced,intent=self.fenced(owned);result=initialize.publish(fenced,verify_c1_lineage=self.lineage);result.check()
            self.assertEqual((self.project/'curation.json').read_bytes(),dict(intent.progress)['sample'])
            self.assertEqual((self.project/'curation.json.bak').read_bytes(),dict(intent.progress)['sample'])
            self.assertEqual(state_types.parse_state((self.project/'layer/state.json').read_bytes()),{'lines':[]})
            self.assertEqual(state_types.parse_removed((self.project/'layer/state-removed.json').read_bytes()),{'removed':[]})
            self.assertEqual(item_types.parse_pins((self.project/'layer/pins.json').read_bytes()),{'pins':[]})
            self.assertEqual((self.project/'layer/item-list.txt').read_bytes(),b'')
            self.assertEqual((self.project/'state-history.jsonl').read_bytes(),b'')
            self.assertEqual(json.loads((self.project/'layer/conflicts.json').read_bytes()),{'candidates':[]})
            complete=json.loads((self.fx.folder(intent)/'initialization-complete.json').read_bytes())
            self.assertEqual((complete['writer_protocol'],complete['lifecycle_protocol']),(1,1))
            self.assertTrue(complete['initialized'])
            self.assertEqual(complete['projects'][0]['epoch'],format2.parse_curation(dict(intent.progress)['sample'])['fence']['epoch'])
            self.assertIn('migrating',json.loads((self.root/'store.json').read_bytes()))
        self.assertEqual(self.fx.fixture.raw.read_bytes(),raw)

    def test_progress_backup_hardlink_and_recognized_temp_are_preserved_before_fixed_epoch_publication(self):
        original=(self.project/'curation.json').read_bytes()
        os.link(str(self.project/'curation.json'),str(self.project/'curation.json.bak'))
        temporary=self.project/'curation.json.abcdefgh.tmp';temporary.write_bytes(original)
        with self.fx.own() as owned:
            fenced,intent=self.fenced(owned);initialize.publish(fenced,verify_c1_lineage=self.lineage)
            self.assertFalse(temporary.exists())
            copies=list(self.fx.folder(intent).glob('initialize-original-*.bin'))
            self.assertEqual([p.read_bytes() for p in copies],[original])
            self.assertEqual((self.project/'curation.json').stat().st_nlink,1)
            self.assertEqual((self.project/'curation.json.bak').stat().st_nlink,1)
            value=format2.parse_curation((self.project/'curation.json').read_bytes())
            self.assertEqual(value['logs'],{'codex-0123456789abcdef':2})
            self.assertEqual(value['applies'],3)

    def test_all_native_stage_identities_are_durable_before_first_project_effect(self):
        with self.fx.own() as owned:
            fenced,intent=self.fenced(owned);real=headers._rename;seen=[]
            def rename(source,target):
                record=json.loads((self.fx.folder(intent)/'initialization-publications.json').read_bytes())
                effect=record['effects'][len(seen)]
                kind='directory' if 'directory' in effect else 'file'
                self.assertEqual(maintenance_identity.capture(Path(source),entry=kind).document(),effect['identity'])
                expected=effect.get('directory',effect.get('target'))
                self.assertEqual(Path(target),self.root/expected)
                seen.append(expected);return real(source,target)
            with mock.patch.object(headers,'_rename',side_effect=rename):initialize.publish(fenced,verify_c1_lineage=self.lineage)
            self.assertEqual(seen[:3],['projects/sample/layer','projects/sample/layer/items','projects/sample/layer/tombstones'])
            self.assertLess(seen.index('projects/sample/curation.json.bak'),seen.index('projects/sample/curation.json'))

    def test_original_lineage_must_be_callable_and_return_only_none(self):
        with self.fx.own() as owned:
            fenced,intent=self.fenced(owned);before=self.fx.project_bytes()
            with self.assertRaises(TypeError):initialize.publish(fenced,verify_c1_lineage=None)
            with self.assertRaises(TypeError):initialize.publish(fenced,verify_c1_lineage=lambda *args:True)
            self.assertEqual(self.fx.project_bytes(),before)
            self.assertFalse((self.fx.folder(intent)/'initialization-publications.json').exists())
            with self.assertRaises(locks.LostLock):fenced.check()

    def test_even_valid_empty_unknown_c2_history_backup_refuses_without_initializing(self):
        path=self.project/'state-history.jsonl.bak';path.write_bytes(b'')
        with self.fx.own() as owned:
            fenced,intent=self.fenced(owned);before=self.fx.project_bytes()
            with self.assertRaises(initialize.InvalidInitialization):initialize.publish(fenced,verify_c1_lineage=self.lineage)
            self.assertEqual(self.fx.project_bytes(),before)
            self.assertFalse((self.fx.folder(intent)/'initialization-publications.json').exists())
        self.assertTrue(path.exists())

    def test_directory_rename_that_publishes_then_raises_is_preserved_as_uncertain(self):
        with self.fx.own() as owned:
            fenced,intent=self.fenced(owned);real=headers._rename;before=(self.project/'curation.json').read_bytes()
            def uncertain(source,target):real(source,target);raise OSError('fixture project directory uncertainty')
            with mock.patch.object(headers,'_rename',side_effect=uncertain):
                with self.assertRaises(OSError) as caught:initialize.publish(fenced,verify_c1_lineage=self.lineage)
            self.assertEqual(caught.exception.migration_uncertain,'projects/sample/layer')
            self.assertTrue((self.project/'layer').is_dir())
            self.assertEqual((self.project/'curation.json').read_bytes(),before)
            self.assertFalse((self.fx.folder(intent)/'initialization-complete.json').exists())

    def test_original_lineage_failure_after_first_effect_keeps_its_exception_and_stops(self):
        with self.fx.own() as owned:
            fenced,intent=self.fenced(owned);active=[True];original=RuntimeError('fixture original C1 lineage loss');real=headers._rename;seen=[]
            def lineage(*args):
                if not active[0]:raise original
            def rename(source,target):
                value=real(source,target);seen.append(target);active[0]=False;return value
            with mock.patch.object(headers,'_rename',side_effect=rename):
                with self.assertRaises(RuntimeError) as caught:initialize.publish(fenced,verify_c1_lineage=lineage)
            self.assertIs(caught.exception,original);self.assertEqual(len(seen),1)
            self.assertFalse((self.fx.folder(intent)/'initialization-complete.json').exists())

    def test_source_change_inside_last_lineage_callback_is_checked_before_any_project_write(self):
        with self.fx.own() as owned:
            fenced,intent=self.fenced(owned)
            def lineage(*args):self.fx.fixture.raw.write_bytes(b'changed fixture raw')
            with mock.patch.object(headers,'_rename',side_effect=AssertionError('source gate bypassed')) as effect:
                with self.assertRaises(locks.LostLock):initialize.publish(fenced,verify_c1_lineage=lineage)
            effect.assert_not_called()
            self.assertFalse((self.fx.folder(intent)/'initialization-publications.json').exists())

    def test_raw_content_is_not_opened_or_copied_during_initialization(self):
        with self.fx.own() as owned:
            fenced,intent=self.fenced(owned);real=owned.inventory._observer.fence.read
            def metadata(path,deadline):
                self.assertNotEqual(path,self.fx.fixture.raw);return real(path,deadline)
            with mock.patch.object(owned.inventory._observer.fence,'read',side_effect=metadata):initialize.publish(fenced,verify_c1_lineage=self.lineage)
            self.assertFalse(any(b'private raw bytes' in p.read_bytes() for p in self.fx.folder(intent).iterdir() if p.is_file()))

    def test_missing_complete_record_never_undoes_or_blesses_already_published_initial_data(self):
        with self.fx.own() as owned:
            fenced,intent=self.fenced(owned);prefix=fenced._prefix;real=prefix._checkpoint
            def checkpoint(name,value):
                if name=='initialization-complete.json':raise OSError('fixture completion failure')
                return real(name,value)
            with mock.patch.object(prefix,'_checkpoint',side_effect=checkpoint):
                with self.assertRaises(OSError):initialize.publish(fenced,verify_c1_lineage=self.lineage)
            self.assertEqual((self.project/'curation.json').read_bytes(),dict(intent.progress)['sample'])
            self.assertTrue((self.project/'layer/state.json').exists())
            self.assertFalse((self.fx.folder(intent)/'initialization-complete.json').exists())
            self.assertIn('migrating',json.loads((self.root/'store.json').read_bytes()))

    def test_old_header_fence_cannot_replay_initialization_after_it_is_consumed(self):
        with self.fx.own() as owned:
            fenced,intent=self.fenced(owned);initialize.publish(fenced,verify_c1_lineage=self.lineage)
            before=self.fx.project_bytes()
            with self.assertRaises(initialize.InvalidInitialization):initialize.publish(fenced,verify_c1_lineage=self.lineage)
            self.assertEqual(self.fx.project_bytes(),before)


    def test_returned_initialized_check_failure_revokes_original_interval(self):
        with self.fx.own() as owned:
            fenced,intent=self.fenced(owned);result=initialize.publish(fenced,verify_c1_lineage=self.lineage)
            unknown=self.fx.folder(intent)/'unexpected-after-initialize';unknown.write_bytes(b'preserve fixture')
            with self.assertRaises(locks.LostLock):result.check()
            unknown.unlink()
            with self.assertRaises(locks.LostLock):owned.check()


if __name__=='__main__':unittest.main()
