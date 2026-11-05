"""Read-only inventory fixtures; none establishes real-host quiescence."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from _common import ROOT

sys.path.insert(0, str(ROOT/'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import history_recovery, locks, migration_inventory, migration_plan

AT = '2026-11-05T00:00:00.000Z'
LATER = '2026-11-05T01:00:00.000Z'
LOG = 'codex-0123456789abcdef'
OTHER = 'claude-code-123456789abcdef0'
HEADER = dict(format=1, device='d_0123456789ab', made=AT, release='0.2.1')
PROGRESS = dict(logs={LOG: 2}, applies=3, recent=[], consolidation=dict(failures=0))


def data(value):
    return json.dumps(value, ensure_ascii=False).encode('utf-8')


class MigrationInventoryTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)/'memory'
        self.root.mkdir()
        (self.root/'store.json').write_bytes(data(HEADER))
        (self.root/'configuration.json').write_bytes(data(dict(projects=dict(
            sample=dict(enabled=True, since=AT)))))
        self.project = self.root/'projects/sample'
        (self.project/'raw').mkdir(parents=True)
        (self.project/'curation.json').write_bytes(data(PROGRESS))
        self.raw = self.project/'raw'/ (LOG+'.jsonl')
        self.raw.write_bytes(b'private raw bytes that the inventory must not open\n')

    def observe(self, **options):
        return migration_inventory.observe(options.pop('folder', self.root), release='0.3.0',
            when=options.pop('when', LATER), deadline=options.pop('deadline', time.monotonic()+30), **options)

    def tree(self):
        return {p.relative_to(self.root).as_posix(): (p.stat().st_mode, p.read_bytes() if p.is_file() else None)
                for p in self.root.rglob('*')}

    def test_tc390_observe_and_check_open_only_metadata_readonly_and_change_nothing(self):
        (self.project/'private-key.txt').write_bytes(b'never open this payload')
        alias = Path(self.temporary.name)/'parent-link'
        if os.name == 'nt':
            command = Path(os.environ['SystemRoot'])/'System32/cmd.exe'
            done = subprocess.run([str(command), '/d', '/c', 'mklink', '/J', str(alias), self.temporary.name],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(done.returncode, 0)
            self.addCleanup(alias.rmdir)
        else:
            alias.symlink_to(self.temporary.name, target_is_directory=True)
            self.addCleanup(alias.unlink)
        before = self.tree()
        opened, real_open = [], os.open
        allowed = {'store.json', 'configuration.json', 'projects/sample/curation.json'}
        def guarded(path, flags, *args, **kwargs):
            relative = Path(path).relative_to(canonical_root).as_posix()
            self.assertIn(relative, allowed)
            self.assertFalse(flags & (os.O_CREAT | os.O_TRUNC | os.O_APPEND | os.O_WRONLY | os.O_RDWR))
            opened.append(relative)
            return real_open(path, flags, *args, **kwargs)
        with mock.patch.object(history_recovery.os, 'open', side_effect=guarded), \
                mock.patch.object(history_recovery.files, '_sync', side_effect=AssertionError('no fsync')), \
                mock.patch.object(locks.Lock, 'acquire', side_effect=AssertionError('no lease')):
            for folder in (self.root, alias/self.root.name):
                canonical_root = folder.resolve()
                value = self.observe(folder=folder)
                value.check()
        self.assertEqual(set(opened), allowed)
        self.assertEqual(self.tree(), before)
        self.assertIn('projects/sample/private-key.txt', value.payloads)

    def test_tc390_union_includes_disabled_missing_reserved_and_orphan_projects_in_path_order(self):
        config = dict(projects={n: dict(enabled=False, since=AT) for n in ('con', 'con-a', 'missing')})
        (self.root/'configuration.json').write_bytes(data(config))
        (self.root/'projects/con_').mkdir()
        value = self.observe()
        self.assertEqual([(p.name, p.exists) for p in value.projects],
            [('con', True), ('con-a', False), ('missing', False), ('sample', True)])
        self.assertEqual([kind for kind, _ in value.leases], ['store']+['curation']*4+['layer']*4+['raw'])
        for kind in ('curation', 'layer', 'raw'):
            paths = [p for k, p in value.leases if k == kind]
            self.assertEqual(paths, sorted(paths))
        self.assertFalse((self.root/'projects/missing').exists())
        self.assertFalse((self.root/'projects/con-a').exists())

    def test_tc390_raw_families_and_progress_only_names_propose_all_raw_leases(self):
        for suffix in ('.jsonl.bak', '.jsonl.a1b2c3_4.tmp', '.lock', '.lock.'+'a'*32+'.stale'):
            (self.project/'raw'/(OTHER+suffix)).write_bytes(b'opaque payload')
        self.raw.unlink()
        value = self.observe()
        self.assertEqual(value.projects[0].raw_logs, tuple(sorted((LOG, OTHER))))
        self.assertEqual([p for k, p in value.leases if k == 'raw'],
            ['projects/sample/raw/'+n+'.lock' for n in sorted((LOG, OTHER))])

    def test_tc390_original_noncanonical_bytes_are_preserved_without_new_epochs(self):
        original = b'  '+data(PROGRESS)+b'\r\n'
        (self.project/'curation.json').write_bytes(original)
        with mock.patch.object(migration_plan.uuid, 'uuid4', side_effect=AssertionError('no new epoch')):
            value = self.observe()
        self.assertEqual(value.projects[0].progress, (('curation.json', original),))
        self.assertEqual(dict(value.headers.original_sha256)['store.json'], hashlib.sha256(data(HEADER)).hexdigest())

    def test_tc390_named_backup_and_recognized_temps_are_bound_without_restoration(self):
        original = (self.root/'store.json').read_bytes()
        (self.root/'store.json').rename(self.root/'store.json.bak')
        (self.root/'store.json.abc123_4.tmp').write_bytes(original)
        (self.project/'curation.json.bak').write_bytes(data(PROGRESS))
        before = self.tree(); value = self.observe()
        self.assertEqual(value.headers.preserve_temps, ('store.json.abc123_4.tmp',))
        self.assertFalse((self.root/'store.json').exists())
        self.assertEqual(self.tree(), before)
        self.assertEqual(len(value.projects[0].progress), 2)

    def test_tc390_configuration_copies_expand_scope_but_never_become_live_configuration(self):
        backup = dict(projects=dict(other=dict(enabled=False, since=AT)))
        (self.root/'configuration.json.bak').write_bytes(data(backup))
        before = self.tree(); value = self.observe()
        self.assertEqual([p.name for p in value.projects], ['other', 'sample'])
        self.assertEqual(self.tree(), before)

    def test_tc390_resume_observes_c2_progress_but_never_initializes_it_again(self):
        fenced = migration_plan.header_fence({'store.json': data(HEADER)}, release='0.3.0', when=AT)
        for name, raw in fenced.publications:
            (self.root/name).write_bytes(raw)
        progress = migration_plan.progress(data(PROGRESS))
        (self.project/'curation.json').write_bytes(progress)
        before = self.tree(); value = self.observe()
        self.assertEqual(value.projects[0].progress, (('curation.json', progress),))
        self.assertEqual(value.headers.publications, fenced.publications)
        self.assertEqual(self.tree(), before)

    def test_tc390_unexplained_c2_progress_is_not_accepted_under_c1_headers(self):
        (self.project/'curation.json').write_bytes(migration_plan.progress(data(PROGRESS)))
        with self.assertRaises(migration_inventory.InvalidInventory):
            self.observe()

    def test_tc390_damage_or_mixed_identity_is_refused_without_trying_a_healthy_backup(self):
        (self.root/'store.json.bak').write_bytes(data(HEADER))
        for raw in (b'{broken', data(dict(HEADER, device='d_123456789abc')), data(dict(HEADER, format=3))):
            (self.root/'store.json').write_bytes(raw)
            before = self.tree()
            with self.subTest(raw=raw), self.assertRaises(migration_inventory.InvalidInventory):
                self.observe()
            self.assertEqual(self.tree(), before)

    def test_tc390_unknown_header_artifact_is_refused_without_opening_its_contents(self):
        (self.root/'store.json.credentials').write_bytes(b'secret')
        with mock.patch.object(history_recovery, '_read', side_effect=AssertionError('no content reads')) as read:
            with self.assertRaises(migration_inventory.InvalidInventory):
                self.observe()
        read.assert_not_called()

    def test_tc390_unknown_raw_name_is_refused_without_opening_it(self):
        (self.project/'raw'/'provider-key.env').write_bytes(b'secret')
        original, opened = history_recovery._read, []
        def guarded(memory, path, *args, **kwargs):
            opened.append(path)
            return original(memory, path, *args, **kwargs)
        with mock.patch.object(history_recovery, '_read', side_effect=guarded):
            with self.assertRaises(migration_inventory.InvalidInventory):
                self.observe()
        self.assertTrue(opened)
        self.assertFalse(any('raw' in path.parts for path in opened))

    def test_tc390_unknown_project_directory_and_wrong_folder_spellings_are_refused(self):
        for name in ('credentials', 'runs/nested'):
            path = self.project/name; path.mkdir(parents=True)
            with self.subTest(name=name), self.assertRaises(migration_inventory.InvalidInventory):
                self.observe()
            path.rmdir()
            if name == 'runs/nested':
                path.parent.rmdir()
        for name in ('con', 'wrong_', 'UPPER'):
            path = self.root/'projects'/name; path.mkdir()
            with self.subTest(name=name), self.assertRaises(migration_inventory.InvalidInventory):
                self.observe()
            path.rmdir()

    def test_tc390_c2_payloads_are_metadata_only_observations_without_restore_authority(self):
        (self.project/'layer/items').mkdir(parents=True)
        (self.project/'layer/items/i_0123456789ab.json').write_bytes(b'opaque unknown item')
        (self.project/'state-history.jsonl').write_bytes(b'opaque unknown history')
        before = self.tree(); value = self.observe()
        self.assertIn('projects/sample/layer/items/i_0123456789ab.json', value.payloads)
        self.assertIn('projects/sample/state-history.jsonl', value.payloads)
        value.check(); self.assertEqual(before, self.tree())

    def test_tc390_known_primary_backup_hardlink_pair_is_accepted_but_extra_alias_refused(self):
        try:
            os.link(str(self.root/'store.json'), str(self.root/'store.json.bak'))
        except OSError:
            self.skipTest('hardlink unavailable')
        self.observe().check()
        os.link(str(self.root/'store.json'), str(self.root/'extra-header-copy'))
        with self.assertRaises(migration_inventory.InvalidInventory):
            self.observe()

    def test_tc390_two_unrelated_payload_paths_cannot_hide_their_alias_count(self):
        try:
            os.link(str(self.raw), str(self.project/'raw'/(OTHER+'.jsonl')))
        except OSError:
            self.skipTest('hardlink unavailable')
        with self.assertRaises(migration_inventory.InvalidInventory):
            self.observe()

    def test_tc390_header_replacement_and_later_put_back_cannot_revive_the_inventory(self):
        value = self.observe()
        path = self.root/'store.json'; old = self.root/'original-header'
        path.rename(old); path.write_bytes(data(HEADER))
        with self.assertRaises(locks.LostLock):
            value.check()
        path.unlink(); old.rename(path)
        with self.assertRaises(locks.LostLock):
            value.check()

    def test_tc390_directory_replacement_with_identical_names_is_detected(self):
        value = self.observe(); folder = self.project/'raw'; saved = self.project/'saved'
        folder.rename(saved); folder.mkdir()
        (folder/self.raw.name).write_bytes((saved/self.raw.name).read_bytes())
        with self.assertRaises(locks.LostLock):
            value.check()

    def test_tc390_original_root_cannot_be_replaced_or_restored_after_revocation(self):
        value = self.observe(); saved = self.root.with_name('saved-memory')
        self.assertEqual(value.folder, self.root.resolve())
        self.root.rename(saved); self.root.mkdir()
        with self.assertRaises(locks.LostLock):
            value.check()
        self.root.rmdir(); saved.rename(self.root)
        with self.assertRaises(locks.LostLock):
            value.check()

    def test_tc390_new_project_or_raw_entry_invalidates_the_original_scope(self):
        for path in (self.root/'projects/new-project', self.project/'raw'/(OTHER+'.jsonl')):
            value = self.observe()
            if path.suffix:
                path.write_bytes(b'new raw')
            else:
                path.mkdir()
            with self.subTest(path=path.name), self.assertRaises(locks.LostLock):
                value.check()
            path.unlink() if path.is_file() else path.rmdir()

    def test_tc390_working_lock_heartbeat_is_not_mistaken_for_token_ownership(self):
        path = self.project/'curation.lock'; path.write_bytes(b'opaque token')
        value = self.observe(); path.write_bytes(b'refreshed opaque token')
        value.check()
        self.assertNotIn('projects/sample/curation.lock', value.payloads)
        path.unlink()
        with self.assertRaises(locks.LostLock):
            value.check()

    def test_tc390_deadline_revocation_cannot_be_reversed_by_a_clock_reset(self):
        value = self.observe(deadline=time.monotonic()+30)
        with mock.patch.object(migration_inventory.clock, 'now', return_value=time.monotonic()+60):
            with self.assertRaises(locks.LockBusy):
                value.check()
        with self.assertRaises(locks.LostLock):
            value.check()

    def test_tc390_requires_existing_explicit_absolute_root_and_finite_deadline(self):
        for folder, deadline in ((Path('relative'), time.monotonic()+30), (self.root/'absent', time.monotonic()+30),
                (self.root, float('nan')), (self.root, float('inf')), (self.root, True)):
            with self.subTest(folder=folder.name, deadline=deadline), self.assertRaises(migration_inventory.InvalidInventory):
                self.observe(folder=folder, deadline=deadline)
        self.assertFalse((self.root/'absent').exists())

    def test_tc390_a_read_race_is_rejected_instead_of_returning_changed_progress(self):
        original = history_recovery.history_io._bytes
        changed = []
        def racing(fd, guard):
            raw = original(fd, guard)
            if raw == data(PROGRESS) and not changed:
                changed.append(True)
                (self.project/'curation.json').write_bytes(raw+b' ')
            return raw
        with mock.patch.object(history_recovery.history_io, '_bytes', side_effect=racing):
            with self.assertRaises(migration_inventory.InvalidInventory):
                self.observe()
        self.assertEqual(changed, [True])

    def test_tc390_actual_fixture_writer_after_observation_changes_scope_without_c2_effects(self):
        code = "import pathlib,sys; print('ready',flush=True); sys.stdin.readline(); p=pathlib.Path(sys.argv[1]); f=p.open('ab'); f.write(b'late C1 turn\\n'); f.close(); print('written',flush=True)"
        child = subprocess.Popen([sys.executable, '-B', '-c', code, str(self.raw)], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), 'ready')
            value = self.observe(); header = (self.root/'store.json').read_bytes()
            child.stdin.write('append\n'); child.stdin.flush()
            self.assertEqual(child.stdout.readline().strip(), 'written')
            child.wait(timeout=10)
            with self.assertRaises(locks.LostLock):
                value.check()
            self.assertEqual((self.root/'store.json').read_bytes(), header)
            self.assertEqual((self.project/'curation.json').read_bytes(), data(PROGRESS))
        finally:
            if child.poll() is None:
                child.kill(); child.wait(timeout=10)
            for stream in (child.stdin, child.stdout, child.stderr):
                stream.close()

    @unittest.skipIf(os.name == 'nt', 'symlink permissions are host-specific')
    def test_tc390_root_project_and_payload_symlinks_are_refused_without_following(self):
        alias = Path(self.temporary.name)/'alias'; alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(migration_inventory.InvalidInventory):
            self.observe(folder=alias)
        alias.unlink()
        link = self.project/'raw'/(OTHER+'.jsonl'); link.symlink_to(self.raw)
        with self.assertRaises(locks.LostLock):
            self.observe()
        link.unlink()
        (self.root/'projects/linked').symlink_to(self.project, target_is_directory=True)
        with self.assertRaises(locks.LostLock):
            self.observe()

    @unittest.skipIf(os.name == 'nt', 'POSIX special-file fixture')
    def test_tc390_fifo_is_refused_without_a_blocking_open(self):
        os.mkfifo(str(self.project/'raw'/(OTHER+'.jsonl')))
        with self.assertRaises(migration_inventory.InvalidInventory):
            self.observe()

    @unittest.skipUnless(os.name == 'nt', 'native Windows junction fixture')
    def test_tc390_windows_root_junction_is_refused_before_resolving_it(self):
        command = Path(os.environ['SystemRoot'])/'System32/cmd.exe'
        alias = Path(self.temporary.name)/'junction'
        done = subprocess.run([str(command), '/d', '/c', 'mklink', '/J', str(alias), str(self.root)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(done.returncode, 0)
        try:
            with self.assertRaises(migration_inventory.InvalidInventory):
                self.observe(folder=alias)
        finally:
            alias.rmdir()


if __name__ == '__main__':
    unittest.main()
