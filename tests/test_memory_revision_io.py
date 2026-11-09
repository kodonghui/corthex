"""Internal format-2 protocol on made-up disk stores, without live activation."""
import contextlib
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import clock, files, format2, locks, revision_io, store, worker_support
from memory_lib import fence_plan
from memory_lib.c2_store import C2Store
from test_memory_fence_plan import PROGRESS


class RevisionIOTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / 'memory'
        (self.root / 'logs').mkdir(parents=True)
        self.project = self.root / 'projects' / 'sample'
        self.project.mkdir(parents=True)
        self.path = self.project / 'curation.json'
        self.backup = self.project / 'curation.json.bak'
        self.header = {'format': 2, 'device': 'd_0123456789ab',
                       'made': '2026-11-04T13:00:00.000Z', 'release': '0.2.1'}
        (self.root / 'store.json').write_bytes(format2.store_bytes(self.header))
        self.path.write_bytes(format2.curation_bytes(PROGRESS))
        self.memory = C2Store(self.root, expected_device=self.header['device'])
        self.deadline = clock.now() + 10

    @contextlib.contextmanager
    def held(self, curator=False):
        with contextlib.ExitStack() as stack:
            if curator:
                stack.enter_context(self.memory.lease(self.project / 'curation.lock', 'curation', self.deadline))
            stack.enter_context(self.memory.lease(self.project / 'layer.lock', 'layer', self.deadline))
            yield

    def value(self):
        return format2.parse_curation(self.path.read_bytes())

    def damaged_with_backup(self):
        self.backup.write_bytes(self.path.read_bytes())
        self.path.write_bytes(b'{damaged fixture')

    def test_internal_binding_does_not_widen_c1_or_accept_incomplete_header_fences(self):
        with self.assertRaises(store.StoreUnavailable) as caught:
            worker_support.WorkerStore(self.root)
        self.assertEqual(caught.exception.code, 'store-newer')
        (self.root / 'store.json.bak').write_bytes(format2.store_bytes(self.header).replace(b'"format": 2', b'"format": 1'))
        with self.assertRaises(store.StoreUnavailable):
            C2Store(self.root)

    def test_wrong_device_and_foreign_root_are_rejected(self):
        with self.assertRaises(locks.LostLock):
            C2Store(self.root, expected_device='d_0123456789ac')
        with self.held(), self.assertRaises(ValueError):
            revision_io.read(self.memory, self.root / 'logs', self.deadline)

    def test_opaque_primary_policy_never_restores_an_older_readable_backup(self):
        backup = format2.store_bytes(self.header)
        backup_path = self.root / 'store.json.bak'
        header_path = self.root / 'store.json'
        cases = [(dict(self.header, format=1), 'store-damaged'),
                 (dict(self.header, format=1.0), 'store-damaged'),
                 (dict(self.header, format=3), 'store-newer'),
                 (dict(self.header, format=3.0), 'store-newer')]
        for marker in (None, {}, 'fixture', {'from': 1, 'to': 2, 'started': self.header['made']}):
            cases.append((dict(self.header, migrating=marker), 'store-migrating'))
        cases += [({'migrating': None}, 'store-migrating')]
        cases += [(dict(self.header, format=v, migrating={}), 'store-migrating') for v in (0, True, 1.5)]
        for header, code in cases:
            with self.subTest(header=header):
                primary = json.dumps(header).encode('utf-8')
                header_path.write_bytes(primary)
                backup_path.write_bytes(backup)
                with self.assertRaises(store.StoreUnavailable) as caught:
                    C2Store(self.root)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual((header_path.read_bytes(), backup_path.read_bytes()), (primary, backup))

    def test_reservation_never_revives_after_new_or_reused_lease_acquisition(self):
        with self.held(curator=True):
            original_leases = list(self.memory.held)
            reservation = revision_io.reserve(self.memory, self.project, fence_plan.snapshot(PROGRESS),
                                               ['item:i_0123456789ab'], self.deadline,
                                               run_id='r_0123456789ac')
            before = self.path.read_bytes()
        with self.held(curator=True), self.assertRaises(locks.LostLock):
            reservation.check()
        with contextlib.ExitStack() as stack:
            for lease in original_leases:
                stack.enter_context(lease.held(self.deadline))
                self.memory.held.append(lease)
            try:
                with self.assertRaises(locks.LostLock):
                    reservation.check()
            finally:
                self.memory.held.clear()
        self.assertEqual(self.path.read_bytes(), before)

    def test_malformed_header_envelopes_recover_a_valid_format2_backup(self):
        header_path = self.root / 'store.json'
        backup_path = self.root / 'store.json.bak'
        backup = format2.store_bytes(self.header)
        bad_headers = [None, [], ['migrating'], 'migrating', True, 42, {}]
        bad_headers += [dict(self.header, format=v) for v in (0, -1, True, 1.5)]
        for header in bad_headers:
            with self.subTest(header=header):
                header_path.write_bytes(json.dumps(header).encode('utf-8'))
                backup_path.write_bytes(backup)
                memory = C2Store(self.root)
                self.assertEqual(memory.device, self.header['device'])
                self.assertEqual(header_path.read_bytes(), backup)
                self.assertFalse(backup_path.exists())
        primary = json.dumps(dict(self.header, format=2.0)).encode('utf-8')
        header_path.write_bytes(primary)
        backup_path.write_bytes(backup)
        self.assertEqual(C2Store(self.root).device, self.header['device'])
        self.assertEqual((header_path.read_bytes(), backup_path.read_bytes()), (primary, backup))

    def test_token_apply_or_revision_drift_before_reserve_never_changes_metadata_or_effects(self):
        for changed in ('token', 'applies', 'revision'):
            with self.subTest(changed=changed):
                self.path.write_bytes(format2.curation_bytes(PROGRESS))
                with self.held(curator=True):
                    proof = fence_plan.snapshot(PROGRESS)
                    if changed == 'token':
                        lease_path = self.project / 'curation.lock'
                        old_lease = lease_path.read_bytes()
                        value = json.loads(old_lease)
                        value['token'] = 'f' * 32 if value['token'] != 'f' * 32 else 'e' * 32
                        lease_path.write_bytes(json.dumps(value).encode('utf-8'))
                    else:
                        value = copy.deepcopy(PROGRESS)
                        if changed == 'applies':
                            value['applies'] += 1
                        else:
                            value['fence']['revisions']['item:i_0123456789ab'] += 1
                        self.path.write_bytes(format2.curation_bytes(value))
                    before = self.path.read_bytes()
                    effect = mock.Mock()
                    try:
                        with self.assertRaises(locks.LostLock if changed == 'token' else fence_plan.Stale):
                            reservation = revision_io.reserve(self.memory, self.project, proof,
                                                               ['item:i_0123456789ab'], self.deadline,
                                                               run_id='r_0123456789ac')
                            reservation.check()
                            effect()
                        effect.assert_not_called()
                        self.assertEqual(self.path.read_bytes(), before)
                    finally:
                        if changed == 'token':
                            lease_path.write_bytes(old_lease)

    def test_missing_or_wrong_kind_or_wrong_device_leases_do_not_write(self):
        before = self.path.read_bytes()
        with self.assertRaises(locks.LostLock):
            revision_io.reserve(self.memory, self.project, fence_plan.snapshot(PROGRESS),
                                ['item:i_0123456789ab'], self.deadline)
        for kind, device in (('curation', self.memory.device), ('layer', 'd_0123456789ac')):
            lock = locks.Lock(self.project / 'layer.lock', kind, device)
            with lock.held(self.deadline):
                self.memory.held.append(lock)
                try:
                    with self.assertRaises(locks.LostLock):
                        revision_io.reserve(self.memory, self.project, fence_plan.snapshot(PROGRESS),
                                            ['item:i_0123456789ab'], self.deadline)
                finally:
                    self.memory.held.remove(lock)
        self.assertEqual(self.path.read_bytes(), before)

    def test_layer_only_reservation_preserves_all_fresh_progress(self):
        proof = fence_plan.snapshot(PROGRESS)
        fresh = copy.deepcopy(PROGRESS)
        fresh['logs']['codex-0123456789abcdef'] += 1
        fresh['consolidation']['failures'] = 3
        fresh['recent'].append({'at': self.header['made'], 'kind': 'curate', 'result': 'failed'})
        self.path.write_bytes(format2.curation_bytes(fresh))
        with self.held():
            reservation = revision_io.reserve(self.memory, self.project, proof,
                                               ['item:i_0123456789ab'], self.deadline)
            reservation.check()
        actual = self.value()
        self.assertEqual({k: v for k, v in actual.items() if k != 'fence'},
                         {k: v for k, v in fresh.items() if k != 'fence'})
        self.assertEqual(actual['fence']['generation'], 9)
        self.assertEqual(actual['fence']['revisions']['item:i_0123456789ab'], 9)
        self.assertNotIn('line:s_0123456789ab', actual['fence']['revisions'])
        self.assertFalse(self.backup.exists())

    def test_run_reservation_requires_curation_and_is_durable_before_an_effect(self):
        proof = fence_plan.snapshot(PROGRESS)
        before = self.path.read_bytes()
        with self.held(), self.assertRaises(locks.LostLock):
            revision_io.reserve(self.memory, self.project, proof, ['item:i_0123456789ab'],
                                self.deadline, run_id='r_0123456789ac')
        self.assertEqual(self.path.read_bytes(), before)
        events = []
        original_sync = files._sync

        def sync(fd):
            original_sync(fd)
            events.append('durable')

        with self.held(curator=True), mock.patch.object(files, '_sync', side_effect=sync):
            reservation = revision_io.reserve(self.memory, self.project, proof,
                                               ['item:i_0123456789ab'], self.deadline,
                                               run_id='r_0123456789ac')
            reservation.check()
            events.append('effect')
        self.assertEqual(events, ['durable', 'effect'])
        self.assertEqual(self.value()['fence']['revisions']['run:r_0123456789ac'], 9)

    def test_fsync_failure_forbids_effect_and_preserves_original(self):
        before = self.path.read_bytes()
        effect = mock.Mock()
        with self.held(), mock.patch.object(files, '_sync', side_effect=OSError('fixture')):
            with self.assertRaises(OSError):
                reservation = revision_io.reserve(self.memory, self.project, fence_plan.snapshot(PROGRESS),
                                                   ['item:i_0123456789ab'], self.deadline)
                reservation.check()
                effect()
        effect.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)

    def test_failed_effect_does_not_roll_back_a_reserved_revision_and_aba_stays_stale(self):
        proof = fence_plan.snapshot(PROGRESS)
        effect = self.project / 'made-up-effect'
        effect.write_bytes(b'A')
        with self.held():
            first = revision_io.reserve(self.memory, self.project, proof,
                                         ['item:i_0123456789ab'], self.deadline)
            first.check()
            effect.write_bytes(b'B')
            with self.assertRaises(OSError):
                raise OSError('fixture unlogged effect failure')
            second = revision_io.reserve(self.memory, self.project, fence_plan.snapshot(self.value()),
                                          ['item:i_0123456789ab'], self.deadline)
            second.check()
            effect.write_bytes(b'A')
            with self.assertRaises(fence_plan.Stale):
                first.check()
        self.assertEqual(effect.read_bytes(), b'A')
        self.assertEqual(self.value()['fence']['generation'], 10)
        self.assertFalse(fence_plan.matches(self.value(), proof))

    def test_lost_layer_or_curation_or_pinned_header_stops_later_effects(self):
        for changed in ('layer.lock', 'curation.lock', 'store.json'):
            with self.subTest(changed=changed):
                self.path.write_bytes(format2.curation_bytes(PROGRESS))
                (self.root / 'store.json').write_bytes(format2.store_bytes(self.header))
                self.memory = C2Store(self.root)
                with self.held(curator=True):
                    reservation = revision_io.reserve(self.memory, self.project, fence_plan.snapshot(PROGRESS),
                                                       ['item:i_0123456789ab'], self.deadline,
                                                       run_id='r_0123456789ac')
                    path = self.root / changed if changed == 'store.json' else self.project / changed
                    old = path.read_bytes()
                    if changed == 'store.json':
                        path.write_bytes(old.replace(b'0', b'1', 1))
                    else:
                        lease_record = json.loads(old)
                        lease_record['token'] = 'f' * 32 if lease_record['token'] != 'f' * 32 else 'e' * 32
                        path.write_bytes(json.dumps(lease_record).encode('utf-8'))
                    with self.assertRaises(locks.LostLock):
                        reservation.check()
                    path.write_bytes(old)

    def test_layer_only_reader_never_restores_or_acquires_curation(self):
        self.damaged_with_backup()
        before, backup = self.path.read_bytes(), self.backup.read_bytes()
        with self.held(), self.assertRaises(files.RestoreNeeded):
            revision_io.read(self.memory, self.project, self.deadline)
        self.assertEqual((self.path.read_bytes(), self.backup.read_bytes()), (before, backup))
        self.assertFalse((self.project / 'curation.lock').exists())

    def test_recovery_durably_changes_epoch_before_replacing_damaged_primary(self):
        self.damaged_with_backup()
        old_proof = fence_plan.snapshot(PROGRESS)
        run = self.project / 'runs' / 'r_0123456789ab.json'
        run.parent.mkdir()
        run.write_bytes(b'made-up retained old-epoch run')
        events = []
        original_sync, original_replace = files._sync, os.replace

        def sync(fd):
            original_sync(fd)
            events.append('durable')

        def replace(source, target):
            if Path(target) == self.path:
                value = format2.parse_curation(Path(source).read_bytes())
                self.assertNotEqual(value['fence']['epoch'], old_proof['fence']['epoch'])
                self.assertEqual(events, ['durable'])
                self.assertEqual(self.backup.read_bytes(), format2.curation_bytes(PROGRESS))
                events.append('publish-new-epoch')
            return original_replace(source, target)

        with self.held(curator=True), mock.patch.object(files, '_sync', side_effect=sync), \
                mock.patch.object(os, 'replace', side_effect=replace):
            value = revision_io.read(self.memory, self.project, self.deadline)
        self.assertEqual(events, ['durable', 'publish-new-epoch'])
        self.assertFalse(fence_plan.matches(value, old_proof))
        self.assertEqual(value['fence']['revisions'], {})
        self.assertEqual(run.read_bytes(), b'made-up retained old-epoch run')
        self.assertFalse(self.backup.exists())

    def test_interruption_before_or_after_recovery_publication_never_restores_old_proof(self):
        for point in ('before', 'after', 'cleanup'):
            with self.subTest(point=point):
                self.path.write_bytes(format2.curation_bytes(PROGRESS))
                self.damaged_with_backup()
                original_replace, original_unlink = os.replace, files._unlink

                def replace(source, target):
                    if Path(target) == self.path:
                        if point == 'before':
                            raise OSError('fixture before publication')
                        original_replace(source, target)
                        if point == 'after':
                            raise OSError('fixture after publication')
                        return
                    return original_replace(source, target)

                def unlink(path, check=None):
                    if point == 'cleanup' and Path(path) == self.backup:
                        raise OSError('fixture cleanup failure')
                    return original_unlink(path, check)

                with self.held(curator=True), mock.patch.object(os, 'replace', side_effect=replace), \
                        mock.patch.object(files, '_unlink', side_effect=unlink), self.assertRaises(OSError):
                    revision_io.read(self.memory, self.project, self.deadline)
                self.assertTrue(self.backup.exists())
                reopened = C2Store(self.root)
                self.memory = reopened
                with self.held(curator=True):
                    value = revision_io.read(self.memory, self.project, self.deadline)
                self.assertFalse(fence_plan.matches(value, fence_plan.snapshot(PROGRESS)))

    def test_permission_error_never_rolls_back_to_backup(self):
        self.damaged_with_backup()
        before, backup = self.path.read_bytes(), self.backup.read_bytes()
        with self.held(curator=True), mock.patch.object(revision_io, '_read', side_effect=PermissionError()), \
                self.assertRaises(PermissionError):
            revision_io.read(self.memory, self.project, self.deadline)
        self.assertEqual((self.path.read_bytes(), self.backup.read_bytes()), (before, backup))

    def test_recovery_fsync_failure_preserves_the_only_good_copy_for_retry(self):
        self.damaged_with_backup()
        before, backup = self.path.read_bytes(), self.backup.read_bytes()
        with self.held(curator=True), mock.patch.object(files, '_sync', side_effect=OSError('fixture fsync')), \
                self.assertRaises(OSError):
            revision_io.read(self.memory, self.project, self.deadline)
        self.assertEqual((self.path.read_bytes(), self.backup.read_bytes()), (before, backup))
        with self.held(curator=True):
            value = revision_io.read(self.memory, self.project, self.deadline)
        self.assertFalse(fence_plan.matches(value, fence_plan.snapshot(PROGRESS)))

    def test_a_fresh_valid_primary_wins_the_second_read_before_recovery_move(self):
        self.damaged_with_backup()
        fresh = fence_plan.rotate(PROGRESS)
        fresh['logs']['codex-0123456789abcdef'] += 1
        primary = format2.curation_bytes(fresh)
        backup = self.backup.read_bytes()
        original = files._temporary

        def temporary(*args, **kwargs):
            result = original(*args, **kwargs)
            # A controlled competing publication at the explicit recheck seam.
            self.path.write_bytes(primary)
            return result

        with self.held(curator=True), mock.patch.object(files, '_temporary', side_effect=temporary):
            value = revision_io.read(self.memory, self.project, self.deadline)
        self.assertEqual(value, fresh)
        self.assertEqual((self.path.read_bytes(), self.backup.read_bytes()), (primary, backup))
        self.assertEqual(list(self.project.glob('curation.json.*.tmp')), [])

    def test_progress_cannot_decrease_applies(self):
        before = self.path.read_bytes()
        with self.held(curator=True), self.assertRaises(ValueError):
            revision_io.update_progress(self.memory, self.project, fence_plan.snapshot(PROGRESS),
                                        {'applies': 1}, self.deadline)
        self.assertEqual(self.path.read_bytes(), before)

    def test_rebuild_rotates_epoch_and_refuses_any_readable_copy(self):
        with self.held(curator=True), self.assertRaises(ValueError):
            revision_io.rebuild(self.memory, self.project, PROGRESS, self.deadline)
        self.path.write_bytes(b'{fixture damage')
        with self.held(curator=True):
            value = revision_io.rebuild(self.memory, self.project, PROGRESS, self.deadline)
        self.assertFalse(fence_plan.matches(value, fence_plan.snapshot(PROGRESS)))
        self.assertEqual(value['logs'], PROGRESS['logs'])

    def test_progress_merge_requires_both_leases_and_preserves_latest_fence(self):
        with self.held(), self.assertRaises(locks.LostLock):
            revision_io.update_progress(self.memory, self.project, fence_plan.snapshot(PROGRESS),
                                        {'applies': 3}, self.deadline)
        with self.held(curator=True):
            revision_io.reserve(self.memory, self.project, fence_plan.snapshot(PROGRESS),
                                ['item:i_0123456789ab'], self.deadline)
            fresh = self.value()
            with self.assertRaises(fence_plan.Stale):
                revision_io.update_progress(self.memory, self.project, fence_plan.snapshot(PROGRESS),
                                            {'applies': 3}, self.deadline)
            value = revision_io.update_progress(self.memory, self.project, fence_plan.snapshot(fresh),
                                                {'applies': 3}, self.deadline)
            self.assertEqual(value['fence'], fresh['fence'])
            self.assertEqual(value['logs'], fresh['logs'])
            with self.assertRaises(ValueError):
                revision_io.update_progress(self.memory, self.project, fence_plan.snapshot(value),
                                            {'fence': PROGRESS['fence']}, self.deadline)

    def test_progress_merge_removes_the_named_fields_and_keeps_the_record_valid(self):
        stopped = {'at': '2026-11-04T13:00:00.000Z', 'by': 'curate', 'errors': ['refusal']}
        failures = {'count': 3, 'log': 'codex-0123456789abcdef', 'turn': 9}
        self.path.write_bytes(format2.curation_bytes(dict(PROGRESS, stopped=stopped, failures=failures)))
        with self.held(curator=True):
            fresh = self.value()
            before = self.path.read_bytes()
            # A required field cannot go, a name is not a list of names, and a field is changed or removed.
            for removed, changes in ((('fence',), {}), (('logs',), {}), (('consolidation',), {}),
                                     ('stopped', {}), (('stopped',), {'stopped': stopped})):
                with self.subTest(removed=removed), self.assertRaises(ValueError):
                    revision_io.update_progress(self.memory, self.project, fence_plan.snapshot(fresh), changes,
                                                self.deadline, removed=removed)
                self.assertEqual(self.path.read_bytes(), before)
            # Names that are not text are refused too, before anything is read.
            for removed in ([['stopped']], (None,)):
                with self.subTest(removed=removed), self.assertRaises(ValueError):
                    revision_io.update_progress(self.memory, self.project, fence_plan.snapshot(fresh), {},
                                                self.deadline, removed=removed)
            value = revision_io.update_progress(self.memory, self.project, fence_plan.snapshot(fresh),
                                                {'failures': dict(failures, count=0)}, self.deadline,
                                                removed=('stopped', 'rebuilt'))
        expected = dict(PROGRESS, failures=dict(failures, count=0))
        self.assertEqual((value, self.value()), (expected, expected))

    def test_a_refused_progress_merge_does_not_restore_a_damaged_record(self):
        stopped = {'at': '2026-11-04T13:00:00.000Z', 'by': 'curate', 'errors': ['refusal']}
        self.path.write_bytes(format2.curation_bytes(dict(PROGRESS, stopped=stopped)))
        fresh = self.value()
        self.damaged_with_backup()
        damaged, backup = self.path.read_bytes(), self.backup.read_bytes()
        with self.held(curator=True):
            # A field both changed and removed, the fence changed or removed, or a field that the record always
            # has removed: each is refused before the record is read.
            for changes, removed in (({'stopped': stopped}, ('stopped',)), ({'fence': fresh['fence']}, ('stopped',)),
                                     ({}, ('fence',)), ({}, ('applies',)), ({}, ('logs', 'stopped'))):
                with self.subTest(changes=sorted(changes), removed=removed), self.assertRaises(ValueError):
                    revision_io.update_progress(self.memory, self.project, fence_plan.snapshot(fresh), changes,
                                                self.deadline, removed=removed)
                self.assertEqual((self.path.read_bytes(), self.backup.read_bytes()), (damaged, backup))
