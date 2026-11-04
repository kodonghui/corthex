"""Partial TASK077 FD/durability proof on fabricated, quiescent C2 stores."""
import contextlib
import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT/'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import clock, fence_plan, files, format2, history_io, locks, revision_io, state_types
from memory_lib.c2_store import C2Store
from test_memory_fence_plan import PROGRESS
from test_memory_item_types import AT, DEVICE
from test_memory_state_types import HISTORY

LINE, RUN = HISTORY['line'], HISTORY['run']


class HistoryIOTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name).resolve()/'memory'
        (self.folder/'logs').mkdir(parents=True)
        self.project = self.folder/'projects/sample'
        (self.project/'layer/tombstones').mkdir(parents=True)
        (self.folder/'store.json').write_bytes(format2.store_bytes(
            {'format':2, 'device':DEVICE, 'made':AT, 'release':'0.2.1'}))
        self.progress = self.project/'curation.json'
        self.progress.write_bytes(format2.curation_bytes(PROGRESS))
        self.path = self.project/'state-history.jsonl'
        self.path.write_bytes(b'')
        self.memory = C2Store(self.folder, expected_device=DEVICE)
        self.deadline = clock.now()+30
        self.blocked = False

    @contextlib.contextmanager
    def held(self, curator=True):
        with contextlib.ExitStack() as stack:
            if curator:
                stack.enter_context(self.memory.lease(self.project/'curation.lock', 'curation', self.deadline))
            stack.enter_context(self.memory.lease(self.project/'layer.lock', 'layer', self.deadline))
            yield

    def reserve(self, targets=None, run=RUN):
        expected = fence_plan.snapshot(format2.parse_curation(self.progress.read_bytes()))
        return revision_io.reserve(self.memory, self.project, expected, targets or ['line:'+LINE], self.deadline, run)

    def values(self, reservation, **changes):
        value = copy.deepcopy(HISTORY)
        value.update(epoch=reservation.progress['fence']['epoch'],
                     generation=reservation.progress['fence']['generation'])
        value.update(changes)
        return [value]

    def precondition(self, reservation, values):
        ownership = revision_io.guard(self.memory, self.project, self.deadline, curator=True)
        expected = tuple((v['epoch'], v['generation'], v['run'], v['line'],
                          state_types.HistoryRecord(state_types.history_record_bytes(v)).sha256) for v in values)
        def check(memory, project, bound, requirements):
            ownership()
            if memory is not self.memory or project != self.project or bound is not reservation or requirements != expected:
                raise ValueError('archive plan mismatch')
            if self.blocked:
                raise fence_plan.Stale()
            ownership()
        return check

    def append(self, reservation, values=None, precondition=None):
        values = self.values(reservation) if values is None else values
        return history_io.append(self.memory, self.project, reservation, values, self.deadline,
                                 archive_precondition=precondition or self.precondition(reservation, values))

    def test_primary_read_is_strict_complete_and_never_uses_backup(self):
        raw = state_types.history_record_bytes(HISTORY)
        backup = self.path.with_name(self.path.name+'.bak')
        backup.write_bytes(raw)
        with self.held(False):
            self.assertEqual(history_io.read(self.memory, self.project, self.deadline), ())
            for damaged in (raw[:-1], raw+b'\n', raw+b'{}\n', raw+b'broken\n'):
                self.path.write_bytes(damaged)
                with self.assertRaises(files.RestoreNeeded):
                    history_io.read(self.memory, self.project, self.deadline)
                self.assertEqual(self.path.read_bytes(), damaged)
            self.path.unlink()
            with self.assertRaises(files.RestoreNeeded):
                history_io.read(self.memory, self.project, self.deadline)
        self.assertFalse(self.path.exists())
        self.assertEqual(backup.read_bytes(), raw)

    def test_read_requires_original_layer_lease_and_does_not_modify_bytes(self):
        raw = state_types.history_record_bytes(HISTORY).replace(b'":', b'": ').replace(b'\n', b'\r\n')
        self.path.write_bytes(raw)
        with self.assertRaises(locks.LostLock):
            history_io.read(self.memory, self.project, self.deadline)
        with self.held(False):
            records = history_io.read(self.memory, self.project, self.deadline)
        self.assertEqual(records[0].raw, raw)
        self.assertEqual(self.path.read_bytes(), raw)

    def test_entire_prior_prefix_and_all_new_records_are_durable_before_receipt(self):
        old = state_types.history_record_bytes(HISTORY)
        self.path.write_bytes(old)
        sync = files._sync
        observed = []
        def synced(fd):
            observed.append(os.fstat(fd).st_size)
            return sync(fd)
        with self.held():
            reservation = self.reserve()
            values = self.values(reservation)
            raw = state_types.history_record_bytes(values[0])
            with mock.patch.object(files, '_sync', side_effect=synced):
                with self.append(reservation, values) as receipt:
                    self.assertTrue(observed and all(size == len(old+raw) for size in observed))
                    self.assertEqual(receipt.hashes, (state_types.HistoryRecord(raw).sha256,))
                    receipt.check()
            self.assertEqual(self.path.read_bytes(), old+raw)
        with self.assertRaises(locks.LostLock):
            receipt.check()

    def test_archive_precondition_is_mandatory_and_plan_bound(self):
        with self.held():
            reservation = self.reserve()
            values = self.values(reservation)
            with self.assertRaises(TypeError):
                with history_io.append(self.memory, self.project, reservation, values, self.deadline):
                    self.fail('missing precondition accepted')
            for invalid in (None, True):
                with self.assertRaises(TypeError):
                    with history_io.append(self.memory, self.project, reservation, values, self.deadline,
                                           archive_precondition=invalid):
                        self.fail('non-callable precondition accepted')
            wrong = self.precondition(reservation, self.values(reservation, why='different plan'))
            with self.assertRaises(ValueError):
                with self.append(reservation, values, wrong):
                    self.fail('another plan accepted')
        self.assertEqual(self.path.read_bytes(), b'')

    def test_archive_initial_rejection_or_unknown_privacy_appends_nothing(self):
        with self.held():
            reservation = self.reserve()
            self.blocked = True
            with self.assertRaises(fence_plan.Stale):
                with self.append(reservation):
                    self.fail('ineligible history accepted')
        self.assertEqual(self.path.read_bytes(), b'')

    def test_precondition_return_values_never_grant_archival_eligibility(self):
        with self.held():
            reservation = self.reserve()
            values = self.values(reservation)
            original = self.precondition(reservation, values)
            for result in (False, True, 0, 'allowed'):
                def check(*args):
                    original(*args)
                    return result
                with self.subTest(result=result), self.assertRaises(TypeError):
                    with self.append(reservation, values, check):
                        self.fail('a returned value authorized archival')
                self.assertEqual(self.path.read_bytes(), b'')

    def test_precondition_false_after_append_never_lends_a_receipt(self):
        refused = [False]
        write = os.write
        def written(fd, data):
            count = write(fd, data)
            refused[0] = True
            return count
        with self.held():
            reservation = self.reserve()
            values = self.values(reservation)
            original = self.precondition(reservation, values)
            def check(*args):
                original(*args)
                return False if refused[0] else None
            with mock.patch.object(os, 'write', side_effect=written):
                with self.assertRaises(history_io.AppendFailed) as caught:
                    with self.append(reservation, values, check):
                        self.fail('post-append refusal yielded a receipt')
            self.assertIsInstance(caught.exception.__cause__, TypeError)
            self.assertTrue(caught.exception.uncertain)
            self.assertEqual(len(state_types.parse_history(self.path.read_bytes())), 1)

    def test_precondition_false_permanently_revokes_a_live_receipt(self):
        result = [None]
        with self.held():
            reservation = self.reserve()
            values = self.values(reservation)
            original = self.precondition(reservation, values)
            def check(*args):
                original(*args)
                return result[0]
            with self.append(reservation, values, check) as receipt:
                result[0] = False
                with self.assertRaises(TypeError):
                    receipt.check()
                result[0] = None
                with self.assertRaises(locks.LostLock):
                    receipt.check()

    def test_archive_drift_immediately_before_append_stops_the_whole_batch(self):
        strict = history_io._strict
        def parsed(data):
            value = strict(data)
            self.blocked = True
            return value
        with self.held():
            reservation = self.reserve()
            with mock.patch.object(history_io, '_strict', side_effect=parsed), mock.patch.object(os, 'write') as write:
                with self.assertRaises(fence_plan.Stale):
                    with self.append(reservation):
                        self.fail('stale source accepted')
                write.assert_not_called()
        self.assertEqual(self.path.read_bytes(), b'')

    def test_archive_drift_permanently_revokes_receipt_without_filtering_records(self):
        with self.held():
            reservation = self.reserve()
            with self.append(reservation) as receipt:
                saved = self.path.read_bytes()
                self.blocked = True
                with self.assertRaises(fence_plan.Stale):
                    receipt.check()
                self.blocked = False
                with self.assertRaises(locks.LostLock):
                    receipt.check()
                self.assertEqual(self.path.read_bytes(), saved)

    def test_other_project_store_or_duck_typed_reservation_is_rejected(self):
        with self.held():
            reservation = self.reserve()
            values = self.values(reservation)
            for memory, project, bound in ((self.memory, self.folder/'projects/other', reservation),
                                            (object(), self.project, reservation),
                                            (self.memory, self.project, mock.Mock())):
                with self.assertRaises(ValueError):
                    with history_io.append(memory, project, bound, values, self.deadline,
                                           archive_precondition=self.precondition(reservation, values)):
                        self.fail('binding mismatch accepted')
        self.assertEqual(self.path.read_bytes(), b'')

    def test_epoch_generation_run_line_and_device_must_match_reserved_proof(self):
        with self.held():
            reservation = self.reserve()
            for changes in ({'epoch':'b'*32}, {'generation':0}, {'run':'r_0123456789ac'},
                            {'line':'s_0123456789ac'}, {'device':'d_0123456789ac'}):
                with self.subTest(changes=changes), self.assertRaises(fence_plan.Stale):
                    with self.append(reservation, self.values(reservation, **changes)):
                        self.fail('unreserved record accepted')
        self.assertEqual(self.path.read_bytes(), b'')

    def test_short_write_is_truncated_and_fsynced_under_original_ownership(self):
        old = state_types.history_record_bytes(HISTORY)
        self.path.write_bytes(old)
        write = os.write
        def partial(fd, data):
            return write(fd, data[:len(data)//2])
        with self.held():
            reservation = self.reserve()
            with mock.patch.object(os, 'write', side_effect=partial):
                with self.assertRaises(history_io.AppendFailed) as caught:
                    with self.append(reservation):
                        self.fail('short append yielded receipt')
            self.assertTrue(caught.exception.rolled_back)
            self.assertFalse(caught.exception.uncertain)
            self.assertEqual(self.path.read_bytes(), old)

    def test_lost_ownership_after_short_write_forbids_even_truncate(self):
        write = os.write
        def partial(fd, data):
            count = write(fd, data[:len(data)//2])
            self.memory.held[-1].token = 'f'*32
            return count
        with self.held():
            reservation = self.reserve()
            with mock.patch.object(os, 'write', side_effect=partial), mock.patch.object(os, 'ftruncate') as truncate:
                with self.assertRaises(history_io.AppendFailed) as caught:
                    with self.append(reservation):
                        self.fail('lost ownership yielded receipt')
                truncate.assert_not_called()
            self.assertTrue(caught.exception.uncertain)
            self.assertNotEqual(self.path.read_bytes(), b'')

    def test_fsync_failure_keeps_unused_complete_rows_and_never_lends_receipt(self):
        with self.held():
            reservation = self.reserve()
            values = self.values(reservation)
            with mock.patch.object(files, '_sync', side_effect=OSError('fixture disk uncertainty')):
                with self.assertRaises(history_io.AppendFailed) as caught:
                    with self.append(reservation, values):
                        self.fail('unconfirmed durability accepted')
            self.assertTrue(caught.exception.uncertain)
            self.assertEqual(len(state_types.parse_history(self.path.read_bytes())), 1)
            # The next call revalidates+fsyncs the entire staged prefix, but
            # neither receipt asserts an actual mutation or restoration right.
            with self.append(reservation, []) as receipt:
                self.assertEqual(receipt.hashes, ())
                receipt.check()

    def test_ownership_loss_before_first_receipt_loan_never_enters_context_body(self):
        original = history_io.DurableHistory.__init__
        for same in (True, False):
            with self.subTest(same=same), self.held():
                reservation = self.reserve()
                replacement = []
                def created(receipt, *args):
                    original(receipt, *args)
                    lease = self.memory.held[-1]
                    lease.release()
                    newer = lease if same else self.memory._lock(self.project/'layer.lock', 'layer', DEVICE)
                    newer.acquire(self.deadline)
                    self.memory.held[-1] = newer
                    replacement.append((lease, newer))
                entered = []
                try:
                    with mock.patch.object(history_io.DurableHistory, '__init__', created):
                        with self.assertRaises(locks.LostLock):
                            with self.append(reservation):
                                entered.append(True)
                    self.assertEqual(entered, [])
                    self.assertTrue(state_types.parse_history(self.path.read_bytes()))
                finally:
                    if replacement:
                        lease, newer = replacement[0]
                        newer.release()
                        self.memory.held[-1] = lease

    def test_exception_after_partial_write_is_uncertain_not_retried_or_silently_repaired(self):
        write = os.write
        error = OSError('fixture exception after partial write')
        def partial(fd, data):
            write(fd, data[:7])
            raise error
        with self.held():
            reservation = self.reserve()
            with mock.patch.object(os, 'write', side_effect=partial) as attempted, \
                    mock.patch.object(os, 'ftruncate') as truncate:
                with self.assertRaises(history_io.AppendFailed) as caught:
                    with self.append(reservation):
                        self.fail('partial exception yielded a receipt')
                attempted.assert_called_once()
                truncate.assert_not_called()
            self.assertIs(caught.exception.__cause__, error)
            self.assertTrue(caught.exception.uncertain)
            self.assertFalse(caught.exception.rolled_back)
            damaged = self.path.read_bytes()
            self.assertEqual(len(damaged), 7)
            with self.assertRaises(files.RestoreNeeded):
                history_io.read(self.memory, self.project, self.deadline)
            self.assertEqual(self.path.read_bytes(), damaged)

    def test_rollback_fsync_uncertainty_never_claims_successful_rollback(self):
        write = os.write
        with self.held():
            reservation = self.reserve()
            with mock.patch.object(os, 'write', side_effect=lambda fd, data: write(fd, data[:1])), \
                    mock.patch.object(files, '_sync', side_effect=OSError('fixture rollback uncertainty')):
                with self.assertRaises(history_io.AppendFailed) as caught:
                    with self.append(reservation):
                        self.fail('uncertain rollback yielded receipt')
            self.assertFalse(caught.exception.rolled_back)
            self.assertTrue(caught.exception.uncertain)

    def test_damaged_or_backup_only_history_is_not_repaired_by_append(self):
        raw = state_types.history_record_bytes(HISTORY)
        backup = self.path.with_name(self.path.name+'.bak')
        backup.write_bytes(raw)
        with self.held():
            reservation = self.reserve()
            self.path.write_bytes(raw[:-1])
            with self.assertRaises(files.RestoreNeeded):
                with self.append(reservation):
                    self.fail('damaged primary accepted')
            self.assertEqual(self.path.read_bytes(), raw[:-1])
            self.path.unlink()
            with self.assertRaises(files.RestoreNeeded):
                with self.append(reservation):
                    self.fail('backup silently restored')
        self.assertFalse(self.path.exists())
        self.assertEqual(backup.read_bytes(), raw)

    def test_same_or_new_layer_lease_never_revives_existing_receipt(self):
        for same in (True, False):
            with self.subTest(same=same), self.held():
                reservation = self.reserve()
                with self.append(reservation) as receipt:
                    lease = self.memory.held[-1]
                    lease.release()
                    replacement = lease if same else self.memory._lock(self.project/'layer.lock', 'layer', DEVICE)
                    replacement.acquire(self.deadline)
                    self.memory.held[-1] = replacement
                    try:
                        with self.assertRaises(locks.LostLock):
                            receipt.check()
                    finally:
                        replacement.release()
                        self.memory.held[-1] = lease

    def test_valid_unrelated_append_preserves_exact_record_links_and_is_fsynced(self):
        with self.held():
            reservation = self.reserve()
            with self.append(reservation) as receipt:
                hashes = receipt.hashes
                extra = state_types.history_record_bytes(dict(HISTORY, line='s_0123456789ac'))
                with self.path.open('ab') as output:
                    output.write(extra)
                with mock.patch.object(files, '_sync', wraps=files._sync) as sync:
                    receipt.check()
                    sync.assert_called_once()
                self.assertEqual(receipt.hashes, hashes)
                self.assertEqual(len(state_types.parse_history(self.path.read_bytes())), 2)

    def test_changed_prefix_or_invalid_suffix_permanently_revokes_receipt(self):
        for suffix in (False, True):
            with self.subTest(suffix=suffix), self.held():
                reservation = self.reserve()
                with self.append(reservation) as receipt:
                    saved = self.path.read_bytes()
                    self.path.write_bytes(saved+b'bad\n' if suffix else saved.replace(b'changed', b'removed', 1))
                    with self.assertRaises((fence_plan.Stale, files.RestoreNeeded)):
                        receipt.check()
                    self.path.write_bytes(saved)
                    with self.assertRaises(locks.LostLock):
                        receipt.check()

    def test_file_replacement_with_identical_bytes_cannot_rebind_open_receipt(self):
        if os.name == 'nt':
            self.skipTest('Windows does not replace this open file; POSIX executes actual path replacement')
        with self.held():
            reservation = self.reserve()
            with self.append(reservation) as receipt:
                replacement = self.path.with_name('replacement')
                replacement.write_bytes(self.path.read_bytes())
                os.replace(str(replacement), str(self.path))
                with self.assertRaises(locks.LostLock):
                    receipt.check()

    def test_project_delete_name_or_backup_blocks_all_history_access(self):
        path = self.project/'layer/deleted.json'
        for target in (path, path.with_name(path.name+'.bak')):
            with self.held():
                reservation = self.reserve()
                target.write_bytes(b'privacy marker')
                try:
                    with self.assertRaises(fence_plan.Stale):
                        history_io.read(self.memory, self.project, self.deadline)
                    with self.assertRaises(fence_plan.Stale):
                        with self.append(reservation):
                            self.fail('deleted project appended')
                finally:
                    target.unlink()

    def test_deadline_and_generation_drift_stop_receipt_reuse(self):
        with self.held():
            reservation = self.reserve()
            with self.append(reservation) as receipt:
                progress = format2.parse_curation(self.progress.read_bytes())
                progress['fence']['generation'] += 1
                self.progress.write_bytes(format2.curation_bytes(progress))
                with self.assertRaises(fence_plan.Stale):
                    receipt.check()
            reservation = self.reserve()
            with mock.patch.object(clock, 'now', return_value=self.deadline+1):
                with self.assertRaises(locks.LockBusy):
                    with self.append(reservation):
                        self.fail('expired deadline accepted')
