"""Direct TBL119 component fixtures; no actual Start/forget/runner proof."""
import contextlib
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0,str(ROOT/'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import base, clock, fence_plan, files, format2, history_retention
from memory_lib import history_recovery, locks, revision_io, state_types
from memory_lib.c2_store import C2Store
from test_memory_fence_plan import PROGRESS
from test_memory_item_types import AT, DEVICE
from test_memory_state_types import HISTORY

NOW = datetime(2026,11,5,12,tzinfo=timezone.utc)


class HistoryRetentionTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name).resolve()/'memory'
        (self.folder/'logs').mkdir(parents=True)
        self.root = self.folder/'projects/sample'
        (self.root/'layer').mkdir(parents=True)
        (self.folder/'store.json').write_bytes(format2.store_bytes(
            {'format':2,'device':DEVICE,'made':AT,'release':'0.2.1'}))
        self.progress = self.root/'curation.json'
        self.progress.write_bytes(format2.curation_bytes(PROGRESS))
        self.path = self.root/'state-history.jsonl'
        self.backup = self.path.with_name(self.path.name+'.bak')
        self.old, self.new = self.history(101), self.history(99)
        self.path.write_bytes(self.old+self.new)
        self.memory = C2Store(self.folder,expected_device=DEVICE)
        self.deadline = clock.now()+60
        self.canonical, self.callback_result = True, None

    def history(self, days, **changes):
        value = copy.deepcopy(HISTORY)
        value.update(at=base.utc_time(NOW-timedelta(days=days)),why='retained reason')
        value.update(changes)
        return state_types.history_record_bytes(value)

    @contextlib.contextmanager
    def held(self, curator=False):
        with contextlib.ExitStack() as stack:
            if curator:
                stack.enter_context(self.memory.lease(self.root/'curation.lock','curation',self.deadline))
            layer = stack.enter_context(self.memory.lease(self.root/'layer.lock','layer',self.deadline))
            yield layer

    def precondition(self):
        original = revision_io.guard(self.memory,self.root,self.deadline)
        control = history_retention._binding(self.progress.read_bytes())
        def check(memory,root,context):
            original()
            if memory is not self.memory or root != self.root or context.control != control:
                raise ValueError('fixture owner binding mismatch')
            if not self.canonical:
                raise fence_plan.Stale()
            self.assertIsInstance(context,history_retention.RetentionContext)
            original()
            return self.callback_result
        return check

    def retain(self, callback=None, days=100, when=NOW):
        return history_retention.retain_history(self.memory,self.root,self.deadline,
            when=when,days=days,history_precondition=callback or self.precondition())

    def artifact(self,name,data=b'orphan',age=601):
        path = self.root/name
        path.write_bytes(data)
        now = 2000000000000000000
        os.utime(path,ns=(now-age*1000000000,now-age*1000000000))
        return path

    def test_fixed_cutoff_equality_future_and_exact_raw_hashes(self):
        equality = self.history(100)
        future = self.history(-1)
        value = json.loads(self.new)
        spaced = json.dumps(value,ensure_ascii=False).encode()+b'\r\n'
        self.path.write_bytes(self.old+equality+spaced+future)
        before = [r.sha256 for r in state_types.parse_history(equality+spaced+future)]
        with self.held():
            result = self.retain()
        self.assertEqual(self.path.read_bytes(),equality+spaced+future)
        self.assertEqual([r.sha256 for r in state_types.parse_history(self.path.read_bytes())],before)
        self.assertEqual(result,{'published':True,'removed':1,'kept':3,'future':1,
                                 'artifacts_removed':1,'cleanup_pending':False})
        self.assertFalse(self.backup.exists())

    def test_configured_seven_days_uses_record_time_not_file_mtime(self):
        self.path.write_bytes(self.history(8)+self.history(7)+self.history(6))
        os.utime(self.path,ns=(1,1))
        with self.held():
            result = self.retain(days=7)
        self.assertEqual(result['removed'],1)
        self.assertEqual(self.path.read_bytes(),self.history(7)+self.history(6))

    def test_all_expired_keeps_a_valid_empty_primary(self):
        self.path.write_bytes(self.old)
        with self.held():
            result = self.retain()
        self.assertTrue(result['published'])
        self.assertEqual(self.path.read_bytes(),b'')
        self.assertEqual(state_types.parse_history(self.path.read_bytes()),())

    def test_no_expiry_preserves_inode_bytes_reasons_and_revision_files(self):
        self.path.write_bytes(self.new)
        before = self.path.stat()
        progress = self.progress.read_bytes()
        with self.held():
            result = self.retain()
        after = self.path.stat()
        self.assertEqual((before.st_dev,before.st_ino,before.st_mtime_ns),
                         (after.st_dev,after.st_ino,after.st_mtime_ns))
        self.assertEqual(self.path.read_bytes(),self.new)
        self.assertEqual(self.progress.read_bytes(),progress)
        self.assertFalse(result['published'])
        self.assertFalse((self.root/'runs').exists())
        self.assertNotIn('retained reason',str(result))

    def test_missing_or_any_damaged_primary_preserves_every_copy(self):
        for value in (None,b'broken\n',self.new[:-1],self.new+b'\n',self.new+b'broken\n'):
            with self.subTest(value=value):
                if value is None:
                    self.path.unlink(missing_ok=True)
                else:
                    self.path.write_bytes(value)
                self.backup.write_bytes(self.new)
                temporary = self.artifact('state-history.jsonl.abcdefgh.tmp',self.old)
                with self.held():
                    with self.assertRaises(files.RestoreNeeded):
                        self.retain()
                self.assertEqual(self.backup.read_bytes(),self.new)
                self.assertEqual(temporary.read_bytes(),self.old)
                self.assertEqual(self.path.read_bytes() if self.path.exists() else None,value)

    def test_layer_only_is_sufficient_and_no_layer_is_refused(self):
        with self.assertRaises(locks.LostLock):
            self.retain()
        with self.held():
            self.assertTrue(self.retain()['published'])

    def test_curator_then_layer_also_works_without_progress_writes(self):
        before = self.progress.read_bytes()
        with self.held(curator=True):
            self.retain()
        self.assertEqual(self.progress.read_bytes(),before)

    def test_noncanonical_owner_and_non_none_callback_are_refused(self):
        before = self.path.read_bytes()
        with self.held():
            self.canonical = False
            with self.assertRaises(fence_plan.Stale):
                self.retain()
            self.canonical = True
            self.callback_result = True
            with self.assertRaises(TypeError):
                self.retain()
        self.assertEqual(self.path.read_bytes(),before)

    def test_mandatory_callback_policy_and_valid_time_before_mutation(self):
        with self.held():
            for days in (True,0,-1,'100',1.5):
                with self.subTest(days=days),self.assertRaises(ValueError):
                    self.retain(days=days)
            with self.assertRaises(ValueError):
                self.retain(when=NOW.replace(tzinfo=None))
            with self.assertRaises(TypeError):
                history_retention.retain_history(self.memory,self.root,self.deadline,
                    when=NOW,days=100,history_precondition=None)
        self.assertEqual(self.path.read_bytes(),self.old+self.new)

    def test_damaged_control_never_restores_its_valid_backup(self):
        before = self.progress.read_bytes()
        self.progress.with_name('curation.json.bak').write_bytes(before)
        self.progress.write_bytes(b'broken')
        with self.held(),self.assertRaises(files.RestoreNeeded):
            history_retention.retain_history(self.memory,self.root,self.deadline,
                when=NOW,days=100,history_precondition=lambda *args:None)
        self.assertEqual(self.progress.read_bytes(),b'broken')
        self.assertEqual(self.path.read_bytes(),self.old+self.new)

    def test_deleted_family_and_original_owner_token_loss_refuse_effects(self):
        with self.held() as layer:
            callback = self.precondition()
            def handoff(*args):
                callback(*args)
                layer.release()
                layer.acquire(self.deadline)
            with self.assertRaises((locks.LostLock,history_retention.RetentionFailed)):
                self.retain(handoff)
        self.assertEqual(self.path.read_bytes(),self.old+self.new)
        (self.root/'layer/deleted.json.abcdefgh.tmp').write_bytes(b'unknown')
        with self.held(),self.assertRaises(fence_plan.Stale):
            self.retain()

    def test_staging_sync_failure_preserves_primary_and_no_false_publication(self):
        before = self.path.read_bytes()
        with self.held(),mock.patch.object(files,'_sync',side_effect=OSError('fixture sync')):
            with self.assertRaises(history_retention.RetentionFailed) as caught:
                self.retain()
        self.assertFalse(caught.exception.published)
        self.assertFalse(caught.exception.publication_uncertain)
        self.assertEqual(self.path.read_bytes(),before)

    def test_stage_drift_cannot_publish(self):
        read = history_recovery._read
        changed = []
        def drift(memory,path,deadline,check,durable=False):
            if path.name.endswith('.tmp') and durable and not changed:
                changed.append(path)
                path.write_bytes(b'synthetic stage drift')
            return read(memory,path,deadline,check,durable)
        with self.held(),mock.patch.object(history_recovery,'_read',side_effect=drift):
            with self.assertRaises(history_retention.RetentionFailed):
                self.retain()
        self.assertTrue(changed)
        self.assertEqual(self.path.read_bytes(),self.old+self.new)

    def test_source_drift_after_staging_cannot_be_rebased(self):
        temporary = files._temporary
        changed = []
        external = self.history(98,why='external')
        def drift(*args,**kwargs):
            result = temporary(*args,**kwargs)
            if not changed:
                changed.append(True)
                self.path.write_bytes(external)
            return result
        with self.held(),mock.patch.object(files,'_temporary',side_effect=drift):
            with self.assertRaises(history_retention.RetentionFailed):
                self.retain()
        self.assertEqual(self.path.read_bytes(),external)

    def test_control_drift_after_staging_cannot_be_rebased(self):
        temporary = files._temporary
        changed = []
        def drift(*args,**kwargs):
            result = temporary(*args,**kwargs)
            if not changed:
                changed.append(True)
                value = copy.deepcopy(PROGRESS)
                value['applies'] += 1
                self.progress.write_bytes(format2.curation_bytes(value))
            return result
        with self.held(),mock.patch.object(files,'_temporary',side_effect=drift):
            with self.assertRaises(history_retention.RetentionFailed):
                self.retain()
        self.assertEqual(self.path.read_bytes(),self.old+self.new)

    def test_replace_uncertainty_reports_no_known_publication_or_rollback(self):
        replace = os.replace
        def uncertain(source,target):
            replace(source,target)
            if Path(target) == self.path:
                raise OSError('fixture uncertain move')
        with self.held(),mock.patch.object(os,'replace',side_effect=uncertain):
            with self.assertRaises(history_retention.RetentionFailed) as caught:
                self.retain()
        self.assertFalse(caught.exception.published)
        self.assertTrue(caught.exception.publication_uncertain)
        self.assertEqual(caught.exception.removed,0)
        self.assertEqual(self.path.read_bytes(),self.new)
        self.assertEqual(self.backup.read_bytes(),self.old+self.new)
        with self.held():
            result = self.retain()
        self.assertFalse(result['published'])
        self.assertFalse(self.backup.exists())
        self.assertEqual(self.path.read_bytes(),self.new)

    def test_published_trim_cleanup_failure_is_retryable_without_restoring_old_rows(self):
        unlink = Path.unlink
        def fail(path,*args,**kwargs):
            if path == self.backup:
                raise OSError('fixture held backup')
            return unlink(path,*args,**kwargs)
        with self.held(),mock.patch.object(Path,'unlink',fail):
            with self.assertRaises(history_retention.RetentionFailed) as caught:
                self.retain()
        self.assertTrue(caught.exception.published)
        self.assertTrue(caught.exception.cleanup_pending)
        self.assertEqual(caught.exception.removed,1)
        self.assertEqual(self.path.read_bytes(),self.new)
        self.assertEqual(self.backup.read_bytes(),self.old+self.new)
        with self.held():
            result = self.retain()
        self.assertFalse(result['published'])
        self.assertEqual(result['artifacts_removed'],1)
        self.assertEqual(self.path.read_bytes(),self.new)

    def test_temp_age_boundaries_unknown_names_and_backup_no_age_requirement(self):
        self.path.write_bytes(self.new)
        old = self.artifact('state-history.jsonl.abcdefgh.tmp')
        old_backup_temp = self.artifact('state-history.jsonl.bak.abcdefgh.tmp')
        exact = self.artifact('state-history.jsonl.abcdefgi.tmp',age=600)
        future = self.artifact('state-history.jsonl.abcdefgj.tmp',age=-1)
        unknown = self.artifact('state-history.jsonl.unowned.tmp',age=999)
        self.backup.write_bytes(b'invalid backup never read as history')
        with self.held(),mock.patch.object(history_retention.time,'time_ns',return_value=2000000000000000000):
            result = self.retain()
        self.assertEqual(result['artifacts_removed'],3)
        self.assertFalse(old.exists())
        self.assertFalse(old_backup_temp.exists())
        self.assertFalse(self.backup.exists())
        self.assertTrue(exact.exists())
        self.assertTrue(future.exists())
        self.assertTrue(unknown.exists())
        self.assertEqual(self.path.read_bytes(),self.new)

    def test_backup_replacement_on_unlink_retry_is_preserved(self):
        self.path.write_bytes(self.new)
        self.backup.write_bytes(self.old)
        unlink = Path.unlink
        calls = []
        replacement = b'synthetic replacement backup'
        def fail(path,*args,**kwargs):
            if path == self.backup and not calls:
                calls.append(True)
                path.write_bytes(replacement)
                raise PermissionError('fixture sharing')
            return unlink(path,*args,**kwargs)
        with self.held(),mock.patch.object(Path,'unlink',fail),mock.patch.object(files,'_WINDOWS',True):
            with self.assertRaises(history_retention.RetentionFailed):
                self.retain()
        self.assertEqual(calls,[True])
        self.assertEqual(self.backup.read_bytes(),replacement)
        self.assertEqual(self.path.read_bytes(),self.new)

    def test_proof_permission_failure_is_permanently_revoked_across_retry(self):
        replace = os.replace
        phase = {'started':False,'failed':False,'after_failure':0}
        def replace_once(source,target):
            if not phase['started']:
                phase['started'] = True
                raise PermissionError('fixture sharing')
            return replace(source,target)
        def retry_three(operation,deadline=None):
            for attempt in range(3):
                try:
                    return operation()
                except PermissionError:
                    if attempt == 2:
                        raise
        with self.held():
            callback = self.precondition()
            def once(*args):
                callback(*args)
                if phase['started']:
                    phase['after_failure'] += 1
                    if not phase['failed']:
                        phase['failed'] = True
                        raise PermissionError('fixture proof unavailable')
            with mock.patch.object(os,'replace',side_effect=replace_once),mock.patch.object(files,'_retry',side_effect=retry_three):
                with self.assertRaises(history_retention.RetentionFailed):
                    self.retain(once)
        self.assertTrue(phase['failed'])
        self.assertEqual(phase['after_failure'],1)
        self.assertEqual(self.path.read_bytes(),self.old+self.new)

    def test_expired_deadline_and_outside_root_make_no_changes(self):
        with self.held():
            self.deadline = clock.now()-1
            with self.assertRaises(locks.LockBusy):
                self.retain()
        self.deadline = clock.now()+60
        with self.held(),self.assertRaises(ValueError):
            history_retention.retain_history(self.memory,self.folder/'outside',self.deadline,
                when=NOW,days=100,history_precondition=lambda *args:None)
        self.assertEqual(self.path.read_bytes(),self.old+self.new)



    def test_real_hardlinked_backup_no_expiry_cleanup_preserves_primary_bytes_and_mtime(self):
        self.path.write_bytes(self.new)
        os.link(self.path,self.backup)
        before = self.path.stat()
        with self.held():
            result = self.retain()
        after = self.path.stat()
        self.assertFalse(result['published'])
        self.assertEqual(result['artifacts_removed'],1)
        self.assertFalse(self.backup.exists())
        self.assertEqual(after.st_nlink,1)
        self.assertEqual((before.st_dev,before.st_ino,before.st_mtime_ns),
                         (after.st_dev,after.st_ino,after.st_mtime_ns))
        self.assertEqual(self.path.read_bytes(),self.new)

    def test_real_hardlinked_backup_can_be_replaced_before_trim(self):
        os.link(self.path,self.backup)
        progress = self.progress.read_bytes()
        with self.held():
            result = self.retain()
        self.assertTrue(result['published'])
        self.assertEqual(result['removed'],1)
        self.assertEqual(self.path.read_bytes(),self.new)
        self.assertEqual(self.path.stat().st_nlink,1)
        self.assertFalse(self.backup.exists())
        self.assertEqual(self.progress.read_bytes(),progress)

    def test_unowned_source_links_refuse_and_unrelated_artifact_alias_is_preserved(self):
        alias = self.folder.parent/'unowned-alias'
        os.link(self.path,alias)
        with self.held(),self.assertRaises(locks.LostLock):
            self.retain()
        self.assertEqual(alias.read_bytes(),self.old+self.new)
        alias.unlink()
        self.path.write_bytes(self.new)
        alias.write_bytes(b'unowned artifact bytes')
        os.link(alias,self.backup)
        with self.held():
            result = self.retain()
        self.assertEqual(result['artifacts_removed'],0)
        self.assertEqual(self.backup.read_bytes(),b'unowned artifact bytes')
        self.assertEqual(alias.read_bytes(),b'unowned artifact bytes')

    def test_own_hardlink_unlink_never_rebaselines_changed_source(self):
        external = self.history(98,why='external source drift')
        for trim in (True,False):
            with self.subTest(trim=trim):
                self.backup.unlink(missing_ok=True)
                self.path.write_bytes(self.old+self.new if trim else self.new)
                os.link(self.path,self.backup)
                if trim:
                    replace = os.replace
                    def mutate(source,target):
                        replace(source,target)
                        if Path(target) == self.backup:
                            self.path.write_bytes(external)
                    patch = mock.patch.object(os,'replace',side_effect=mutate)
                else:
                    unlink = Path.unlink
                    def mutate(path,*args,**kwargs):
                        result = unlink(path,*args,**kwargs)
                        if path == self.backup:
                            self.path.write_bytes(external)
                        return result
                    patch = mock.patch.object(Path,'unlink',mutate)
                with self.held(),patch:
                    with self.assertRaises(history_retention.RetentionFailed) as caught:
                        self.retain()
                self.assertEqual(caught.exception.artifacts_removed,0 if trim else 1)
                self.assertEqual(self.path.read_bytes(),external)

    def test_last_backup_stat_layer_handoff_cannot_move_backup(self):
        import inspect
        check = self.memory.fence.check
        replace = os.replace
        changed, moves = [], []
        with self.held() as layer:
            def handoff(path):
                info = check(path)
                if path == self.backup and not changed and any(f.function == 'backup_fast' for f in inspect.stack()):
                    changed.append(True)
                    layer.release()
                    layer.acquire(self.deadline)
                return info
            def observe(source,target):
                moves.append(Path(target))
                return replace(source,target)
            with mock.patch.object(self.memory.fence,'check',side_effect=handoff),mock.patch.object(os,'replace',side_effect=observe):
                with self.assertRaises(history_retention.RetentionFailed):
                    self.retain()
        self.assertEqual(changed,[True])
        self.assertEqual(moves,[])
        self.assertFalse(self.backup.exists())
        self.assertEqual(self.path.read_bytes(),self.old+self.new)

    @unittest.skipUnless(os.name == 'nt','Windows sharing handle requires Windows')
    def test_real_windows_held_primary_refuses_then_fresh_pass_trims(self):
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,
            ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.CreateFileW(str(self.path),0x80000000,1,None,3,0x80,None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            with self.held(),self.assertRaises(history_retention.RetentionFailed) as caught:
                self.retain()
            self.assertFalse(caught.exception.published)
            self.assertEqual(self.path.read_bytes(),self.old+self.new)
        finally:
            kernel.CloseHandle(handle)
        with self.held():
            self.assertTrue(self.retain()['published'])
        self.assertEqual(self.path.read_bytes(),self.new)
if __name__ == '__main__':
    unittest.main()
