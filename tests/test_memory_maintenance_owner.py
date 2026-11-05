"""Ordered-owner components; a fixture callback is no real-host verification."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import unittest
from unittest import mock

from _common import ROOT
import test_memory_migration_inventory as fixtures

sys.path.insert(0, str(ROOT/'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import files, locks, maintenance_owner


class MaintenanceOwnerTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.MigrationInventoryTest('test_tc390_raw_families_and_progress_only_names_propose_all_raw_leases')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.project = self.fixture.root, self.fixture.project
        self.valid, self.checks = True, 0

    def quiet(self, root, binding):
        self.assertEqual(root, self.root.resolve())
        self.assertEqual(binding, (fixtures.HEADER['device'], fixtures.AT, '0.3.0', fixtures.LATER))
        self.checks += 1
        if not self.valid:
            raise locks.LostLock()

    def own(self, **options):
        return maintenance_owner.acquire(self.root, release='0.3.0', when=fixtures.LATER,
            deadline=options.pop('deadline', time.monotonic()+30),
            verify_quiescence=options.pop('verify_quiescence', self.quiet), **options)

    def writer(self):
        code = ("import sys,time;sys.path.insert(0,sys.argv[1]);from pathlib import Path;"
                "from memory_lib import locks;lease=locks.Lock(Path(sys.argv[2]),'raw',sys.argv[3]);"
                "lease.acquire(time.monotonic()+5);print('ready',flush=True);"
                "sys.stdin.readline();lease.check();lease.release();print('released',flush=True)")
        child = subprocess.Popen([sys.executable, '-B', '-c', code,
            str(ROOT/'plugins/corthex-memory/skills/corthex-memory/scripts'),
            str(self.project/'raw'/(fixtures.LOG+'.lock')), fixtures.HEADER['device']],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        def stop():
            if child.poll() is None:
                child.stdin.write('release\n'); child.stdin.flush()
                try:child.wait(timeout=10)
                except subprocess.TimeoutExpired:child.kill(); child.wait(timeout=10)
            for stream in (child.stdin, child.stdout, child.stderr):stream.close()
        self.addCleanup(stop)
        self.assertEqual(child.stdout.readline().strip(), 'ready')
        return child, stop

    def test_ordered_owner_holds_every_original_lease_and_changes_only_working_files(self):
        before = self.fixture.tree()
        with self.own() as owned:
            self.assertEqual([k for k, _ in owned.inventory.leases], ['store', 'curation', 'layer', 'raw'])
            for _, relative in owned.inventory.leases:
                self.assertTrue((self.root/relative).is_file())
            owned.check()
            self.assertFalse(owned.cleanup_pending)
        self.assertEqual(before, self.fixture.tree())
        self.assertGreater(self.checks, 4)
        with self.assertRaises(locks.LostLock):
            owned.check()

    def test_external_verification_is_required_and_only_none_can_succeed(self):
        before = self.fixture.tree()
        for callback in (None, True, False, lambda *a:True, lambda *a:False, lambda *a:0):
            with self.subTest(callback=type(callback).__name__), self.assertRaises(TypeError):
                with self.own(verify_quiescence=callback):
                    self.fail('unsupported maintenance admission')
            self.assertEqual(before, self.fixture.tree())

    def test_missing_project_or_raw_folder_is_never_provisioned(self):
        config = self.root/'configuration.json'
        original = config.read_bytes()
        config.write_bytes(fixtures.data(dict(projects=dict(missing=dict(enabled=True, since=fixtures.AT)))))
        before = self.fixture.tree()
        with self.assertRaises(files.RestoreNeeded):
            with self.own():self.fail('missing project admitted')
        self.assertEqual(before, self.fixture.tree())
        config.write_bytes(original)
        self.fixture.raw.unlink(); (self.project/'raw').rmdir()
        before = self.fixture.tree()
        with self.assertRaises(files.RestoreNeeded):
            with self.own():self.fail('missing raw folder admitted')
        self.assertEqual(before, self.fixture.tree())

    def test_quiescence_loss_is_sticky_but_safe_original_locks_are_released(self):
        before = self.fixture.tree()
        with self.own() as owned:
            self.valid = False
            with self.assertRaises(locks.LostLock):owned.check()
            self.valid = True
            with self.assertRaises(locks.LostLock):owned.check()
        self.assertFalse(owned.cleanup_pending)
        self.assertEqual(before, self.fixture.tree())

    def test_observed_inventory_failure_cannot_be_hidden_by_restoring_bytes(self):
        path = self.project/'curation.json'; original = path.read_bytes()
        with self.own() as owned:
            path.write_bytes(fixtures.data(dict(fixtures.PROGRESS, applies=4)))
            with self.assertRaises(locks.LostLock):owned.inventory.check()
            path.write_bytes(original)
            with self.assertRaises(locks.LostLock):owned.check()

    def test_non_none_quiescence_after_admission_cannot_be_reenabled(self):
        result = [None]
        def verify(root, binding):
            self.quiet(root, binding)
            return result[0]
        with self.own(verify_quiescence=verify) as owned:
            result[0] = True
            with self.assertRaises(TypeError):owned.check()
            result[0] = None
            with self.assertRaises(locks.LostLock):owned.check()

    def test_resume_binding_preserves_the_original_migration_start(self):
        proposal = fixtures.migration_plan.header_fence({'store.json':fixtures.data(fixtures.HEADER)},
            release='0.3.0', when=fixtures.AT)
        for name, raw in proposal.publications:(self.root/name).write_bytes(raw)
        before = self.fixture.tree()
        def verify(root, binding):
            self.assertEqual(root, self.root.resolve())
            self.assertEqual(binding, (fixtures.HEADER['device'], fixtures.AT, '0.3.0', fixtures.AT))
        with self.own(verify_quiescence=verify) as owned:owned.check()
        self.assertEqual(before, self.fixture.tree())

    def test_busy_actual_writer_lease_is_never_forced_or_overwritten(self):
        child, _ = self.writer(); before = self.fixture.tree()
        with self.assertRaises(locks.LockBusy):
            with self.own():self.fail('fresh writer lease admitted')
        self.assertEqual(child.poll(), None)
        self.assertEqual(before, self.fixture.tree())

    def test_controlled_writer_supervisor_refuses_active_or_restartable_interval(self):
        child, stop = self.writer(); restart_blocked = [False]
        def verify(root, binding):
            self.quiet(root, binding)
            if child.poll() is None or not restart_blocked[0]:raise locks.LostLock()
        before = self.fixture.tree()
        with self.assertRaises(locks.LostLock):
            with self.own(verify_quiescence=verify):self.fail('active fixture writer admitted')
        self.assertEqual(before, self.fixture.tree())
        stop()
        with self.assertRaises(locks.LostLock):
            with self.own(verify_quiescence=verify):self.fail('restartable fixture interval admitted')
        restart_blocked[0] = True
        with self.own(verify_quiescence=verify) as owned:owned.check()

    def test_all_project_leases_are_sorted_by_actual_folder_path(self):
        for name in ('con_', 'con-a'):
            folder = self.root/'projects'/name; (folder/'raw').mkdir(parents=True)
            (folder/'curation.json').write_bytes(fixtures.data(fixtures.PROGRESS))
        acquired = []; original = locks.Lock.acquire
        def record(lease, *args, **kwargs):
            acquired.append(lease.path.relative_to(self.root.resolve()).as_posix())
            return original(lease, *args, **kwargs)
        with mock.patch.object(locks.Lock, 'acquire', record):
            with self.own() as owned:
                self.assertEqual(acquired, [p for _, p in owned.inventory.leases])
                self.assertEqual(len(acquired), 10)

    def test_unexplained_working_artifact_during_acquisition_refuses_admission(self):
        original = locks.Lock.acquire; inserted = []
        path = self.project/'unexpected.lock'
        def racing(lease, *args, **kwargs):
            result = original(lease, *args, **kwargs)
            if lease.path.name == 'store.lock' and not inserted:
                inserted.append(True); path.write_bytes(b'unexplained working artifact')
            return result
        with mock.patch.object(locks.Lock, 'acquire', racing):
            with self.assertRaises(locks.LostLock):
                with self.own():self.fail('unexplained artifact admitted')
        self.assertEqual(path.read_bytes(), b'unexplained working artifact')

    def test_a_failure_immediately_after_acquire_still_tracks_original_cleanup(self):
        original = locks.Lock.acquire; moved = []
        saved = self.root.with_name('interrupted-root')
        def racing(lease, *args, **kwargs):
            result = original(lease, *args, **kwargs)
            if lease.path.name == 'store.lock' and not moved:
                moved.append(True); self.root.rename(saved); self.root.mkdir()
            return result
        with mock.patch.object(locks.Lock, 'acquire', racing):
            with self.assertRaises(maintenance_owner.CleanupPending):
                with self.own():self.fail('replaced root admitted')
        self.root.rmdir(); saved.rename(self.root)
        self.assertTrue((self.root/'store.lock').exists())

    def test_cleanup_does_not_require_a_live_effect_deadline(self):
        deadline = time.monotonic()+30
        context = self.own(deadline=deadline); owned = context.__enter__()
        before = {p:raw for p, raw in self.fixture.tree().items() if not p.endswith('.lock')}
        with mock.patch.object(maintenance_owner.clock, 'now', return_value=deadline+1):
            with self.assertRaises(locks.LockBusy):owned.check()
            context.__exit__(None, None, None)
        self.assertFalse(owned.cleanup_pending)
        self.assertEqual(before, self.fixture.tree())

    def test_new_raw_scope_during_acquisition_is_preserved_and_refused(self):
        original = locks.Lock.acquire; inserted = []
        path = self.project/'raw'/(fixtures.OTHER+'.jsonl')
        def racing(lease, *args, **kwargs):
            result = original(lease, *args, **kwargs)
            if lease.path.name == 'store.lock' and not inserted:
                inserted.append(True); path.write_bytes(b'new C1 data')
            return result
        with mock.patch.object(locks.Lock, 'acquire', racing):
            with self.assertRaises(locks.LostLock):
                with self.own():self.fail('changed raw scope admitted')
        self.assertEqual(path.read_bytes(), b'new C1 data')
        self.assertFalse(list(self.root.rglob('*.lock')))

    def test_progress_change_during_acquisition_is_never_rolled_back(self):
        original = locks.Lock.acquire; inserted = []
        path = self.project/'curation.json'
        new = fixtures.data(dict(fixtures.PROGRESS, applies=4))
        def racing(lease, *args, **kwargs):
            result = original(lease, *args, **kwargs)
            if lease.path.name == 'store.lock' and not inserted:
                inserted.append(True); path.write_bytes(new)
            return result
        with mock.patch.object(locks.Lock, 'acquire', racing):
            with self.assertRaises(locks.LostLock):
                with self.own():self.fail('changed original progress admitted')
        self.assertEqual(path.read_bytes(), new)
        self.assertFalse(list(self.root.rglob('*.lock')))

    def test_old_expired_lease_uses_normal_stale_policy_without_force(self):
        path = self.project/'curation.lock'
        path.write_text(json.dumps(dict(pid=999999, device=fixtures.HEADER['device'], at=fixtures.AT, token='a'*32)), encoding='utf-8')
        os.utime(str(path), (time.time()-700, time.time()-700))
        original = locks.Lock._detach; calls = []
        def record(lease, *args, **kwargs):
            calls.append(dict(kwargs)); self.assertFalse(kwargs.get('force', False))
            return original(lease, *args, **kwargs)
        with mock.patch.object(locks.Lock, '_detach', record):
            with self.own() as owned:owned.check()
        self.assertTrue(any(c.get('stale') for c in calls))
        self.assertFalse(path.exists())

    def test_foreign_token_is_never_deleted_during_cleanup(self):
        path = self.project/'curation.lock'
        with self.own() as owned:
            value = json.loads(path.read_text(encoding='utf-8')); value['token'] = 'f'*32
            path.write_text(json.dumps(value), encoding='utf-8')
            with self.assertRaises(locks.LostLock):owned.check()
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['token'], 'f'*32)
        self.assertFalse((self.root/'store.lock').exists())

    def test_original_path_replacement_revokes_effects_and_reports_pending_cleanup(self):
        class PublicationFailure(RuntimeError):pass
        saved = self.root.with_name('saved-root')
        with self.assertRaises(PublicationFailure):
            with self.own() as owned:
                self.root.rename(saved); self.root.mkdir()
                with self.assertRaises(locks.LostLock):owned.check()
                raise PublicationFailure('fixed fixture failure')
        self.assertTrue(owned.cleanup_pending)
        self.root.rmdir(); saved.rename(self.root)
        with self.assertRaises(locks.LostLock):owned.check()

    def test_equal_token_copy_at_another_inode_never_keeps_effect_authority(self):
        path = self.project/'curation.lock'
        with self.assertRaises(maintenance_owner.CleanupPending):
            with self.own() as owned:
                saved = self.project/'saved-lock'
                original = path.read_bytes(); path.rename(saved); path.write_bytes(original)
                with self.assertRaises(locks.LostLock):owned.check()
                path.unlink(); saved.rename(path)
                with self.assertRaises(locks.LostLock):owned.check()
        self.assertTrue(owned.cleanup_pending)

    def test_extra_hardlink_revokes_effects_even_after_alias_removal(self):
        path = self.project/'curation.lock'; alias = self.root/'extra-lease-alias'
        with self.assertRaises(maintenance_owner.CleanupPending):
            with self.own() as owned:
                try:os.link(str(path), str(alias))
                except OSError:self.skipTest('hardlink unavailable')
                with self.assertRaises(locks.LostLock):owned.check()
                alias.unlink()
                with self.assertRaises(locks.LostLock):owned.check()
        self.assertTrue(owned.cleanup_pending)

    @unittest.skipIf(os.name == 'nt', 'POSIX fork ownership fixture')
    def test_forked_child_cannot_check_or_release_the_parent_scope(self):
        context = self.own(); owned = context.__enter__()
        read_fd, write_fd = os.pipe(); child = os.fork()
        if child == 0:
            os.close(read_fd)
            try:
                try:owned.check(); result = b'0'
                except locks.LostLock:result = b'1'
                context.__exit__(None, None, None)
                result += b'1' if owned.cleanup_pending else b'0'
                os.write(write_fd, result)
                os._exit(0)
            except BaseException:os._exit(2)
        os.close(write_fd)
        try:
            deadline = time.monotonic()+10
            while True:
                finished, status = os.waitpid(child, os.WNOHANG)
                if finished:break
                if time.monotonic() >= deadline:
                    os.kill(child, signal.SIGKILL); os.waitpid(child, 0)
                    self.fail('fixture child exceeded its deadline')
                time.sleep(0.01)
            self.assertEqual(status, 0)
            self.assertEqual(os.read(read_fd, 8), b'11')
            owned.check()
            self.assertTrue((self.root/'store.lock').exists())
        finally:
            os.close(read_fd)
            context.__exit__(None, None, None)
        self.assertFalse((self.root/'store.lock').exists())


if __name__ == '__main__':unittest.main()
