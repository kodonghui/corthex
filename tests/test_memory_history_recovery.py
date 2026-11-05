"""Conditional repair fixtures; no actual maintenance/deletion authority."""
import contextlib
import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0,str(ROOT/'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import clock, fence_plan, files, format2, history_recovery, locks, revision_io, state_types
from memory_lib.c2_store import C2Store
from memory_lib.item_types import _raw
from test_memory_fence_plan import PROGRESS
from test_memory_item_types import AT, DEVICE, ITEM
from test_memory_state_types import HISTORY

SECOND, ENTRY = 'i_0123456789ac', 'e_0123456789ac'


class HistoryRecoveryTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name).resolve()/'memory'
        (self.folder/'logs').mkdir(parents=True)
        self.project = self.folder/'projects/sample'
        self.tombstones = self.project/'layer/tombstones'
        self.tombstones.mkdir(parents=True)
        (self.folder/'store.json').write_bytes(format2.store_bytes(
            {'format':2,'device':DEVICE,'made':AT,'release':'0.2.1'}))
        self.progress = self.project/'curation.json'
        self.progress.write_bytes(format2.curation_bytes(PROGRESS))
        self.marker = self.project/'layer/state-removed.json'
        self.marker.write_bytes(state_types.removed_bytes({'removed':[]}))
        self.path = self.project/'state-history.jsonl'
        self.backup = self.path.with_name(self.path.name+'.bak')
        self.path.write_bytes(b'broken\n')
        self.good = state_types.history_record_bytes(HISTORY)
        self.backup.write_bytes(self.good)
        self.memory = C2Store(self.folder,expected_device=DEVICE)
        self.deadline = clock.now()+60
        self.deleting, self.callback_result = False, None

    @contextlib.contextmanager
    def held(self, curator=True):
        with contextlib.ExitStack() as stack:
            if curator:
                stack.enter_context(self.memory.lease(self.project/'curation.lock','curation',self.deadline))
            stack.enter_context(self.memory.lease(self.project/'layer.lock','layer',self.deadline))
            yield

    def precondition(self):
        original = revision_io.guard(self.memory,self.project,self.deadline,curator=True)
        value = format2.parse_curation(self.progress.read_bytes())
        fence = value['fence']
        expected = value['applies'],fence['epoch'],fence['generation'],tuple(sorted(fence['revisions'].items()))
        def check(memory,root,binding):
            original()
            if memory is not self.memory or root != self.project or binding != expected:
                raise ValueError('fixture maintenance context mismatch')
            if self.deleting:
                raise fence_plan.Stale()
            original()
            return self.callback_result
        return check

    def recover(self, callback=None):
        return history_recovery.recover(self.memory,self.project,self.deadline,
                                         maintenance_precondition=callback or self.precondition())

    def tombstone(self, **changes):
        value = {'item':SECOND,'project':'sample','at':AT,'device':DEVICE,
                 'quotes':[{'device':DEVICE,'entry':ENTRY,'log':ITEM['quotes'][0]['log'],'start':0,'end':1}]}
        value.update(changes)
        return value

    def fact(self, value=None):
        target = self.tombstones/(SECOND+'.json')
        target.write_bytes(_raw(self.tombstone() if value is None else value))
        return target

    def history(self, **changes):
        value = copy.deepcopy(HISTORY)
        value.update(changes)
        return state_types.history_record_bytes(value)

    def test_healthy_primary_wins_without_claiming_privacy_scrub_or_touching_backup(self):
        self.path.write_bytes(self.good)
        self.backup.write_bytes(b'damaged backup')
        self.marker.write_bytes(b'unknown facts')
        with self.held():
            result = self.recover()
        self.assertEqual(result,{'published':False,'cleanup_pending':False,'removed':0,'reasons_cleared':0})
        self.assertEqual(self.path.read_bytes(),self.good)
        self.assertEqual(self.backup.read_bytes(),b'damaged backup')

    def test_fixed_policy_removes_item_and_entry_cites_and_clears_every_remaining_reason(self):
        self.fact()
        unchanged = self.history(why='').replace(b'\n',b'\r\n')
        self.backup.write_bytes(self.history(why='B content')+self.history(cites=[SECOND])+
                               self.history(cites=[ENTRY])+unchanged)
        self.marker.write_bytes(state_types.removed_bytes({'removed':[
            {'id':HISTORY['line'],'at':AT,'device':DEVICE,'kind':'privacy'}]}))
        with self.held():
            result = self.recover()
        records = state_types.parse_history(self.path.read_bytes())
        self.assertEqual(result,{'published':True,'cleanup_pending':False,'removed':2,'reasons_cleared':1})
        self.assertEqual(len(records),2)
        self.assertTrue(all(record.value['why']=='' for record in records))
        self.assertEqual(records[0].value['text'],HISTORY['text'])
        self.assertEqual(records[0].value['cites'],HISTORY['cites'])
        self.assertEqual(records[1].raw,unchanged)
        self.assertEqual(state_types.parse_removed(self.marker.read_bytes())['removed'][0]['kind'],'privacy')
        self.assertFalse(self.backup.exists())

    def test_missing_primary_and_empty_history_are_valid_only_with_complete_owner_facts(self):
        self.path.unlink()
        self.backup.write_bytes(b'')
        with self.held():
            result = self.recover()
        self.assertTrue(result['published'])
        self.assertEqual(self.path.read_bytes(),b'')

    def test_empty_cites_are_not_rejected_by_recovery_or_given_undo_authority(self):
        self.backup.write_bytes(self.history(cites=[],why='remove reason'))
        with self.held():
            self.recover()
        self.assertEqual(state_types.parse_history(self.path.read_bytes())[0].value['cites'],[])

    def test_maintenance_callback_is_required_none_only_and_bound_to_original_context(self):
        with self.held():
            with self.assertRaises(TypeError):
                history_recovery.recover(self.memory,self.project,self.deadline)
            for callback in (None,True,lambda *args:False,lambda *args:True):
                with self.subTest(callback=callback),self.assertRaises(TypeError):
                    history_recovery.recover(self.memory,self.project,self.deadline,maintenance_precondition=callback)
            with self.assertRaises(ValueError):
                self.recover(lambda *args: (_ for _ in ()).throw(ValueError('other context')))
        self.assertEqual(self.path.read_bytes(),b'broken\n')
        self.assertEqual(self.backup.read_bytes(),self.good)

    def test_absent_project_tombstone_never_overrides_owner_deletion_refusal(self):
        self.deleting = True
        self.assertFalse((self.project/'layer/deleted.json').exists())
        with self.held():
            with self.assertRaises(fence_plan.Stale):
                self.recover()
        self.assertEqual(self.path.read_bytes(),b'broken\n')
        self.assertEqual(self.backup.read_bytes(),self.good)

    def test_layer_only_forget_never_implicitly_acquires_curator_for_repair(self):
        with self.held(False):
            with self.assertRaises(locks.LostLock):
                history_recovery.recover(self.memory,self.project,self.deadline,maintenance_precondition=lambda *args:None)
            self.assertFalse((self.project/'curation.lock').exists())
        self.assertEqual(self.path.read_bytes(),b'broken\n')

    def test_malformed_incomplete_or_other_project_tombstones_postpone_without_changes(self):
        variants = [self.tombstone(item=ITEM['id']),self.tombstone(project='other'),self.tombstone(at='bad'),
                    self.tombstone(device='bad'),self.tombstone(quotes=[]),self.tombstone(quotes=[{}])]
        for field,value in [('start',True),('start',-1),('end',-1),('log','codex-0123456789abcdef.json'),('entry','bad')]:
            bad = self.tombstone()
            bad['quotes'][0][field] = value
            variants.append(bad)
        with self.held():
            for value in variants:
                self.fact(value)
                with self.subTest(value=value),self.assertRaises(files.RestoreNeeded):
                    self.recover()
                self.assertEqual(self.path.read_bytes(),b'broken\n')
                self.assertEqual(self.backup.read_bytes(),self.good)

    def test_unknown_duplicate_missing_or_damaged_removed_facts_postpone(self):
        marker = {'id':HISTORY['line'],'at':AT,'device':DEVICE}
        values = [_raw({'removed':[marker]}),_raw({'removed':[dict(marker,kind='edit')]*2}),b'broken']
        with self.held():
            for data in values:
                self.marker.write_bytes(data)
                with self.assertRaises(files.RestoreNeeded):
                    self.recover()
            self.marker.unlink()
            with self.assertRaises(files.RestoreNeeded):
                self.recover()
        self.assertEqual(self.path.read_bytes(),b'broken\n')
        self.assertEqual(self.backup.read_bytes(),self.good)

    def test_fact_backups_temps_and_unpublished_artifacts_are_never_silently_chosen(self):
        paths = [self.tombstones/(SECOND+'.json.bak'),self.tombstones/(SECOND+'.json.nonce.tmp'),
                 self.marker.with_name(self.marker.name+'.bak'),self.marker.with_name(self.marker.name+'.nonce.tmp')]
        with self.held():
            for path in paths:
                path.write_bytes(b'potential privacy facts')
                try:
                    with self.subTest(path=path.name),self.assertRaises(files.RestoreNeeded):
                        self.recover()
                finally:
                    path.unlink()
        self.assertEqual(self.path.read_bytes(),b'broken\n')

    def test_project_delete_names_and_backups_block_even_with_unreadable_content(self):
        marker = self.project/'layer/deleted.json'
        with self.held():
            for path in (marker,marker.with_name(marker.name+'.bak')):
                path.write_bytes(b'not JSON')
                try:
                    with self.assertRaises(fence_plan.Stale):
                        self.recover()
                finally:
                    path.unlink()
        self.assertEqual(self.backup.read_bytes(),self.good)

    def test_strict_backup_rejects_valid_looking_prefix_and_ignores_staged_sources(self):
        with self.held():
            for data in (self.good[:-1],self.good+b'\n',self.good+b'bad\n'):
                self.backup.write_bytes(data)
                with self.assertRaises(files.RestoreNeeded):
                    self.recover()
                self.assertEqual(self.backup.read_bytes(),data)
            self.backup.unlink()
            orphan = self.path.with_name(self.path.name+'.orphan.tmp')
            orphan.write_bytes(self.good)
            with self.assertRaises(files.RestoreNeeded):
                self.recover()
            self.assertEqual(orphan.read_bytes(),self.good)
        self.assertEqual(self.path.read_bytes(),b'broken\n')

    def test_stage_fsync_failure_preserves_the_only_good_backup(self):
        with self.held(),mock.patch.object(files,'_sync',side_effect=OSError('fixture fsync uncertainty')):
            with self.assertRaises(history_recovery.RecoveryFailed) as caught:
                self.recover()
        self.assertFalse(caught.exception.published)
        self.assertFalse(caught.exception.publication_uncertain)
        self.assertEqual(self.path.read_bytes(),b'broken\n')
        self.assertEqual(self.backup.read_bytes(),self.good)

    def test_new_healthy_primary_after_preparation_wins_and_is_never_overwritten(self):
        temporary = files._temporary
        latest = self.history(why='healthy new primary')
        def prepared(*args,**kwargs):
            result = temporary(*args,**kwargs)
            self.path.write_bytes(latest)
            return result
        with self.held(),mock.patch.object(files,'_temporary',side_effect=prepared):
            result = self.recover()
        self.assertFalse(result['published'])
        self.assertEqual((result['removed'],result['reasons_cleared']),(0,0))
        self.assertEqual(self.path.read_bytes(),latest)
        self.assertEqual(self.backup.read_bytes(),self.good)
        self.assertFalse(list(self.project.glob('state-history.jsonl.*.tmp')))

    def test_each_retry_rechecks_primary_and_preserves_uncertain_publication(self):
        replace = os.replace
        latest = self.history(why='new primary during retry')
        attempts = []
        def move(source,target):
            if Path(target) == self.path:
                attempts.append(True)
                self.path.write_bytes(latest)
                raise PermissionError('fixture sharing response')
            return replace(source,target)
        with self.held(),mock.patch.object(files,'_WINDOWS',True),mock.patch.object(os,'replace',side_effect=move):
            with self.assertRaises(history_recovery.RecoveryFailed) as caught:
                self.recover()
        self.assertEqual(len(attempts),1)
        self.assertFalse(caught.exception.published)
        self.assertTrue(caught.exception.publication_uncertain)
        self.assertEqual(self.path.read_bytes(),latest)
        self.assertEqual(self.backup.read_bytes(),self.good)

    def test_backup_cleanup_failure_reports_published_data_and_pending_cleanup(self):
        unlink = files._unlink
        def failed(path,*args):
            if path == self.backup:
                raise OSError('fixture backup cleanup failure')
            return unlink(path,*args)
        with self.held(),mock.patch.object(files,'_unlink',side_effect=failed):
            with self.assertRaises(history_recovery.RecoveryFailed) as caught:
                self.recover()
        self.assertTrue(caught.exception.published)
        self.assertTrue(caught.exception.cleanup_pending)
        self.assertFalse(caught.exception.publication_uncertain)
        self.assertEqual(caught.exception.reasons_cleared,1)
        self.assertEqual(state_types.parse_history(self.path.read_bytes())[0].value['why'],'')
        self.assertEqual(self.backup.read_bytes(),self.good)

    def test_postpublication_verification_failure_keeps_the_backup(self):
        replace = os.replace
        def moved(source,target):
            result = replace(source,target)
            if Path(target) == self.path:
                self.path.write_bytes(b'changed after publication\n')
            return result
        with self.held(),mock.patch.object(os,'replace',side_effect=moved):
            with self.assertRaises(history_recovery.RecoveryFailed) as caught:
                self.recover()
        self.assertTrue(caught.exception.published)
        self.assertTrue(caught.exception.cleanup_pending)
        self.assertEqual(self.backup.read_bytes(),self.good)

    def test_same_or_new_lease_after_stage_cannot_authorize_recovery_or_cleanup(self):
        temporary = files._temporary
        for same in (True,False):
            replacements = []
            def prepared(*args,**kwargs):
                result = temporary(*args,**kwargs)
                old = self.memory.held[-1]
                old.release()
                new = old if same else self.memory._lock(self.project/'layer.lock','layer',DEVICE)
                new.acquire(self.deadline)
                self.memory.held[-1] = new
                replacements.append((old,new))
                return result
            with self.subTest(same=same),self.held():
                try:
                    with mock.patch.object(files,'_temporary',side_effect=prepared):
                        with self.assertRaises(history_recovery.RecoveryFailed) as caught:
                            self.recover()
                    self.assertFalse(caught.exception.published)
                    self.assertEqual(self.path.read_bytes(),b'broken\n')
                    self.assertEqual(self.backup.read_bytes(),self.good)
                finally:
                    if replacements:
                        old,new = replacements[0]
                        new.release()
                        self.memory.held[-1] = old

    def test_privacy_fact_drift_after_stage_blocks_publication(self):
        temporary = files._temporary
        def prepared(*args,**kwargs):
            result = temporary(*args,**kwargs)
            self.fact()
            return result
        with self.held(),mock.patch.object(files,'_temporary',side_effect=prepared):
            with self.assertRaises(history_recovery.RecoveryFailed) as caught:
                self.recover()
        self.assertIsInstance(caught.exception.__cause__,fence_plan.Stale)
        self.assertFalse(caught.exception.published)
        self.assertEqual(self.path.read_bytes(),b'broken\n')
        self.assertEqual(self.backup.read_bytes(),self.good)

    def test_changed_damaged_primary_is_not_overwritten_with_an_old_backup(self):
        temporary = files._temporary
        def prepared(*args,**kwargs):
            result = temporary(*args,**kwargs)
            self.path.write_bytes(b'new incomplete primary')
            return result
        with self.held(),mock.patch.object(files,'_temporary',side_effect=prepared):
            with self.assertRaises(history_recovery.RecoveryFailed):
                self.recover()
        self.assertEqual(self.path.read_bytes(),b'new incomplete primary')
        self.assertEqual(self.backup.read_bytes(),self.good)

    def test_changed_backup_identity_is_not_deleted_or_used(self):
        temporary = files._temporary
        def prepared(*args,**kwargs):
            result = temporary(*args,**kwargs)
            replacement = self.project/'new-backup'
            replacement.write_bytes(self.good)
            os.replace(str(replacement),str(self.backup))
            return result
        with self.held(),mock.patch.object(files,'_temporary',side_effect=prepared):
            with self.assertRaises(history_recovery.RecoveryFailed) as caught:
                self.recover()
        self.assertFalse(caught.exception.published)
        self.assertEqual(self.path.read_bytes(),b'broken\n')
        self.assertEqual(self.backup.read_bytes(),self.good)

    def test_late_non_none_maintenance_result_cannot_authorize_the_move(self):
        temporary = files._temporary
        def prepared(*args,**kwargs):
            result = temporary(*args,**kwargs)
            self.callback_result = False
            return result
        with self.held(),mock.patch.object(files,'_temporary',side_effect=prepared):
            with self.assertRaises(history_recovery.RecoveryFailed) as caught:
                self.recover()
        self.assertIsInstance(caught.exception.__cause__,TypeError)
        self.assertFalse(caught.exception.published)
        self.assertEqual(self.path.read_bytes(),b'broken\n')

    def test_unsafe_backup_alias_is_never_read(self):
        if os.name == 'nt':
            self.skipTest('POSIX symlink fixture')
        target = self.folder/'outside-history'
        target.write_bytes(self.good)
        self.backup.unlink()
        self.backup.symlink_to(target)
        with self.held():
            with self.assertRaises(locks.LostLock):
                self.recover()
        self.assertEqual(target.read_bytes(),self.good)

    def test_same_inode_stage_truncation_or_growth_never_replaces_primary(self):
        temporary = files._temporary
        for damaged in (b'',self.good+b'bad suffix\n'):
            def prepared(*args,**kwargs):
                result = temporary(*args,**kwargs)
                before = result.stat()
                result.write_bytes(damaged)
                self.assertEqual(result.stat().st_ino,before.st_ino)
                return result
            with self.subTest(damaged=damaged),self.held(),mock.patch.object(files,'_temporary',side_effect=prepared):
                with self.assertRaises(history_recovery.RecoveryFailed) as caught:
                    self.recover()
                self.assertFalse(caught.exception.published)
                self.assertFalse(caught.exception.publication_uncertain)
                self.assertEqual(self.path.read_bytes(),b'broken\n')
                self.assertEqual(self.backup.read_bytes(),self.good)

    def test_healthy_primary_appearing_during_final_source_check_is_preserved(self):
        read = history_recovery._read
        calls, latest = [], self.history(why='healthy during source validation')
        def checked(memory,path,*args,**kwargs):
            value = read(memory,path,*args,**kwargs)
            if path == self.backup:
                calls.append(True)
                if len(calls) == 2:
                    self.path.write_bytes(latest)
            return value
        with self.held(),mock.patch.object(history_recovery,'_read',side_effect=checked):
            result = self.recover()
        self.assertFalse(result['published'])
        self.assertEqual(self.path.read_bytes(),latest)
        self.assertEqual(self.backup.read_bytes(),self.good)

    def test_cleanup_retry_checks_primary_and_exact_backup_before_unlink(self):
        unlink = Path.unlink
        for change_backup in (True,False):
            self.path.write_bytes(b'broken\n')
            self.backup.write_bytes(self.good)
            attempts = []
            def removing(path,*args,**kwargs):
                if path == self.backup and not attempts:
                    attempts.append(True)
                    if change_backup:
                        replacement = self.project/'replacement-backup'
                        replacement.write_bytes(self.good)
                        os.replace(str(replacement),str(self.backup))
                    else:
                        self.path.write_bytes(b'damaged before cleanup retry')
                    raise PermissionError('fixture cleanup sharing failure')
                return unlink(path,*args,**kwargs)
            with self.subTest(change_backup=change_backup),self.held(),mock.patch.object(files,'_WINDOWS',True), \
                    mock.patch.object(Path,'unlink',removing):
                with self.assertRaises(history_recovery.RecoveryFailed) as caught:
                    self.recover()
                self.assertTrue(caught.exception.published)
                self.assertTrue(caught.exception.cleanup_pending)
                self.assertEqual(len(attempts),1)
                self.assertEqual(self.backup.read_bytes(),self.good)
                if not change_backup:
                    self.assertEqual(self.path.read_bytes(),b'damaged before cleanup retry')

    def test_refusing_context_never_restores_missing_or_damaged_control(self):
        valid = self.progress.read_bytes()
        backup = self.progress.with_name(self.progress.name+'.bak')
        with self.held():
            for damaged in (None,b'broken control'):
                backup.write_bytes(valid)
                if damaged is None:
                    self.progress.unlink()
                else:
                    self.progress.write_bytes(damaged)
                refusal = mock.Mock(side_effect=ValueError('non-deletion context refused'))
                with self.subTest(damaged=damaged),self.assertRaises(files.RestoreNeeded):
                    history_recovery.recover(self.memory,self.project,self.deadline,maintenance_precondition=refusal)
                refusal.assert_not_called()
                self.assertEqual(backup.read_bytes(),valid)
                if damaged is None:
                    self.assertFalse(self.progress.exists())
                else:
                    self.assertEqual(self.progress.read_bytes(),damaged)
                self.progress.write_bytes(valid)
        self.assertEqual(self.path.read_bytes(),b'broken\n')

    def test_prepublication_stage_fsync_failure_never_replaces_primary(self):
        sync, calls = files._sync, []
        def flushed(fd):
            calls.append(True)
            if len(calls) == 2:
                raise OSError('fixture prepublication stage sync failure')
            return sync(fd)
        with self.held(),mock.patch.object(files,'_sync',side_effect=flushed):
            with self.assertRaises(history_recovery.RecoveryFailed) as caught:
                self.recover()
        self.assertFalse(caught.exception.published)
        self.assertFalse(caught.exception.publication_uncertain)
        self.assertEqual(self.path.read_bytes(),b'broken\n')
        self.assertEqual(self.backup.read_bytes(),self.good)

    def test_fd_and_path_time_fields_are_compared_with_their_own_observation_kind(self):
        fstat = os.fstat
        class DescriptorInfo:
            def __init__(self,info):
                self.info = info
            def __getattr__(self,name):
                value = getattr(self.info,name)
                return value+1000000 if name == 'st_ctime_ns' else value
        with self.held(),mock.patch.object(os,'fstat',side_effect=lambda fd:DescriptorInfo(fstat(fd))):
            result = self.recover()
        self.assertTrue(result['published'])
        self.assertFalse(result['cleanup_pending'])
        self.assertFalse(self.backup.exists())
        self.assertEqual(state_types.parse_history(self.path.read_bytes())[0].value['why'],'')

    def test_backup_changed_during_stage_sync_never_reaches_primary(self):
        sync, calls = files._sync, []
        replacement = self.history(why='new backup after source check')
        def flushed(fd):
            sync(fd)
            calls.append(True)
            if len(calls) == 2:
                self.backup.write_bytes(replacement)
        with self.held(),mock.patch.object(files,'_sync',side_effect=flushed):
            with self.assertRaises(history_recovery.RecoveryFailed) as caught:
                self.recover()
        self.assertFalse(caught.exception.published)
        self.assertFalse(caught.exception.publication_uncertain)
        self.assertEqual(self.path.read_bytes(),b'broken\n')
        self.assertEqual(self.backup.read_bytes(),replacement)

    def test_stage_changed_during_final_primary_read_is_not_published(self):
        primary, calls = history_recovery._primary, []
        def latest(*args,**kwargs):
            value = primary(*args,**kwargs)
            calls.append(True)
            if len(calls) == 2:
                staged = list(self.project.glob('state-history.jsonl.*.tmp'))
                self.assertEqual(len(staged),1)
                staged[0].write_bytes(b'')
            return value
        with self.held(),mock.patch.object(history_recovery,'_primary',side_effect=latest):
            with self.assertRaises(history_recovery.RecoveryFailed) as caught:
                self.recover()
        self.assertFalse(caught.exception.published)
        self.assertFalse(caught.exception.publication_uncertain)
        self.assertEqual(self.path.read_bytes(),b'broken\n')
        self.assertEqual(self.backup.read_bytes(),self.good)

    def test_privacy_fact_added_during_final_primary_read_prevents_publication(self):
        primary, calls = history_recovery._primary, []
        def latest(*args,**kwargs):
            value = primary(*args,**kwargs)
            calls.append(True)
            if len(calls) == 2:
                self.fact()
            return value
        with self.held(),mock.patch.object(history_recovery,'_primary',side_effect=latest):
            with self.assertRaises(history_recovery.RecoveryFailed) as caught:
                self.recover()
        self.assertFalse(caught.exception.published)
        self.assertFalse(caught.exception.publication_uncertain)
        self.assertEqual(self.path.read_bytes(),b'broken\n')
        self.assertEqual(self.backup.read_bytes(),self.good)

    def test_privacy_sidecopy_during_cleanup_read_keeps_original_backup(self):
        read, calls = history_recovery._read, []
        def checked(memory,path,*args,**kwargs):
            value = read(memory,path,*args,**kwargs)
            if path == self.path:
                calls.append(True)
                if len(calls) == 4:
                    self.marker.with_name(self.marker.name+'.bak').write_bytes(self.marker.read_bytes())
            return value
        with self.held(),mock.patch.object(history_recovery,'_read',side_effect=checked):
            with self.assertRaises(history_recovery.RecoveryFailed) as caught:
                self.recover()
        self.assertTrue(caught.exception.published)
        self.assertTrue(caught.exception.cleanup_pending)
        self.assertEqual(self.backup.read_bytes(),self.good)
        self.assertEqual(state_types.parse_history(self.path.read_bytes())[0].value['why'],'')
