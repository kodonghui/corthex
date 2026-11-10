"""TASK076 disk-boundary proof on fabricated, already-migrated stores."""
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
from memory_lib import clock, fence_plan, files, format2, item_io, item_plan, item_types, locks, revision_io, run_log
from memory_lib.c2_store import C2Store
from test_memory_fence_plan import PROGRESS
from test_memory_item_types import AT, DEVICE, ITEM

FIRST, SECOND, THIRD = ITEM['id'], 'i_0123456789ac', 'i_0123456789ad'
CHANGED = '2026-11-05T04:00:00.000Z'


class ItemIOTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / 'memory'
        (self.root / 'logs').mkdir(parents=True)
        self.project = self.root / 'projects/sample'
        for name in ('layer/items', 'layer/tombstones', 'notices'):
            (self.project / name).mkdir(parents=True, exist_ok=True)
        header = {'format': 2, 'device': DEVICE, 'made': AT, 'release': '0.2.1'}
        (self.root / 'store.json').write_bytes(format2.store_bytes(header))
        self.progress_path = self.project / 'curation.json'
        self.progress_path.write_bytes(format2.curation_bytes(PROGRESS))
        self.pins_path = self.project / 'layer/pins.json'
        self.pins_path.write_bytes(item_types.pins_bytes({'pins': []}))
        self.memory = C2Store(self.root, expected_device=DEVICE)
        self.deadline = clock.now() + 30
        self.saved = self.item()
        self.item_path(FIRST).write_bytes(item_types.item_bytes(self.saved))

    def item(self, item=FIRST, **changes):
        value = copy.deepcopy(ITEM)
        value.update(id=item, **changes)
        return value

    def item_path(self, item):
        return self.project / 'layer/items' / (item + '.json')

    def progress(self):
        return format2.parse_curation(self.progress_path.read_bytes())

    def proof(self):
        return fence_plan.snapshot(self.progress())

    @contextlib.contextmanager
    def held(self, curator=False):
        with contextlib.ExitStack() as stack:
            if curator:
                stack.enter_context(self.memory.lease(self.project / 'curation.lock', 'curation', self.deadline))
            stack.enter_context(self.memory.lease(self.project / 'layer.lock', 'layer', self.deadline))
            yield

    def pin(self, item=FIRST, on=True):
        return {'item': item, 'on': on, 'at': AT, 'device': DEVICE}

    def apply(self, additions=(), transitions=(), **kwargs):
        return item_io.apply(self.memory, self.project, self.proof(), additions, transitions,
                             CHANGED, self.deadline, **kwargs)

    def test_add_and_transition_preserve_every_immutable_provenance_field(self):
        self.saved.update(merges=[THIRD], undone_by='r_0123456789ab')
        self.item_path(FIRST).write_bytes(item_types.item_bytes(self.saved))
        with self.held():
            result = self.apply([self.item(SECOND)], [{'id': FIRST, 'status': 'superseded', 'superseded_by': SECOND}])
        after = item_types.parse_item(self.item_path(FIRST).read_bytes())
        self.assertEqual(after, dict(self.saved, status='superseded', superseded_by=SECOND, changed=CHANGED))
        self.assertEqual(item_types.parse_item(self.item_path(SECOND).read_bytes()), self.item(SECOND))
        self.assertEqual(result['published'], ('item:'+SECOND, 'item:'+FIRST, 'item-list'))
        self.assertEqual((self.project/'layer/item-list.txt').read_bytes(), item_types.item_list_bytes([after, self.item(SECOND)]))

    def test_superseded_pin_moves_in_one_document_at_same_time_and_stores_notice(self):
        off = self.pin(THIRD, False)
        self.pins_path.write_bytes(item_types.pins_bytes({'pins': [self.pin(), off]}))
        with self.held(curator=True):
            result = self.apply([self.item(SECOND)], [{'id': FIRST, 'status': 'superseded', 'superseded_by': SECOND}], run_id='r_0123456789ac')
        pins = item_types.parse_pins(self.pins_path.read_bytes())['pins']
        self.assertEqual(pins, [dict(self.pin(), on=False, at=CHANGED), off, dict(self.pin(SECOND), at=CHANGED)])
        self.assertEqual(item_types.parse_notice((self.project/('notices/pin-'+FIRST+'.json')).read_bytes()),
                         {'at': CHANGED, 'kind': 'pin-moved', 'item': FIRST, 'to': SECOND})
        revisions = result['progress']['fence']['revisions']
        self.assertTrue(all(revisions[key] == result['progress']['fence']['generation']
                            for key in ('item:'+FIRST, 'item:'+SECOND, 'pin:'+FIRST, 'pin:'+SECOND, 'run:r_0123456789ac')))

    def test_a_replacement_already_pinned_at_this_time_takes_no_revision_and_logs(self):
        # Its pin keeps its record, so the batch reserves no revision for it and its run log names every one.
        self.item_path(SECOND).write_bytes(item_types.item_bytes(self.item(SECOND)))
        same = dict(self.pin(SECOND), at=CHANGED)
        self.pins_path.write_bytes(item_types.pins_bytes({'pins': [self.pin(), same]}))
        run, transition = 'r_0123456789ac', {'id': FIRST, 'status': 'superseded', 'superseded_by': SECOND}
        # The writer still checks the pin it touched: the replacement deleted after the reservation stops the batch.
        tombstone, original = self.project / 'layer/tombstones' / (SECOND + '.json'), revision_io.reserve

        def reserve(*args):
            value = original(*args)
            tombstone.write_bytes(b'fixture privacy')
            return value
        with self.held(curator=True), mock.patch.object(revision_io, 'reserve', side_effect=reserve):
            with self.assertRaises(item_io.WriteFailed) as caught:
                self.apply(transitions=[transition], run_id=run)
        self.assertIsInstance(caught.exception.__cause__, fence_plan.Stale)
        self.assertEqual(caught.exception.published, ())
        tombstone.unlink()
        before = self.progress()['fence']['revisions']
        with self.held(curator=True):
            result = self.apply(transitions=[transition], run_id=run)
        self.assertEqual(item_types.parse_pins(self.pins_path.read_bytes())['pins'],
                         [dict(self.pin(), on=False, at=CHANGED), same])
        self.assertEqual(item_types.parse_notice((self.project/('notices/pin-'+FIRST+'.json')).read_bytes()),
                         {'at': CHANGED, 'kind': 'pin-moved', 'item': FIRST, 'to': SECOND})
        effects, fence = result['effects'], result['progress']['fence']
        self.assertEqual([value['id'] for value in effects['revisions']], ['item:' + FIRST, 'pin:' + FIRST])
        self.assertEqual(fence['revisions'].get('pin:' + SECOND), before.get('pin:' + SECOND))
        self.assertEqual([entry['item'] for entry in effects['pins']], [FIRST])
        log = run_log.add(run_log.start(run, 'curate', CHANGED, DEVICE), result['progress'], CHANGED, effects)
        self.assertEqual((log['pins'], log['last']), (effects['pins'], fence['generation']))

    def test_withdrawal_drops_pin_and_preserves_unrelated_off_record(self):
        off = self.pin(SECOND, False)
        self.pins_path.write_bytes(item_types.pins_bytes({'pins': [self.pin(), off]}))
        with self.held():
            self.apply(transitions=[{'id': FIRST, 'status': 'withdrawn'}])
        self.assertEqual(item_types.parse_pins(self.pins_path.read_bytes())['pins'], [dict(self.pin(), on=False, at=CHANGED), off])
        self.assertEqual((self.project/'layer/item-list.txt').read_bytes(), b'')
        notice = item_types.parse_notice((self.project/('notices/pin-'+FIRST+'.json')).read_bytes())
        self.assertEqual(notice, {'at': CHANGED, 'kind': 'pin-dropped', 'item': FIRST})

    def test_a_batch_that_changes_nothing_is_refused_before_any_reservation(self):
        # A merge answer that only names disagreements publishes conflicts.json alone (TASK-089), so a batch
        # without item changes is let through to the candidates; with no candidate change either, it is refused.
        (self.project / 'layer/conflicts.json').write_bytes(b'{"candidates":[]}\n')
        before = self.progress_path.read_bytes()
        with self.held(curator=True), self.assertRaisesRegex(ValueError, 'item change required'):
            self.apply(conflicts={'candidates': []}, run_id='r_0123456789ac')
        self.assertEqual(self.progress_path.read_bytes(), before)
        self.assertFalse((self.project / 'layer/item-list.txt').exists())

    def test_saved_item_content_cannot_be_overwritten_through_add_or_status_arguments(self):
        before = self.item_path(FIRST).read_bytes(), self.progress_path.read_bytes()
        with self.held():
            quotes = [dict(self.saved['quotes'][0], words='B🙂')]
            for field, value in [('kind', 'fact'), ('title', 'new'), ('text', 'new'), ('quotes', quotes)]:
                with self.subTest(field=field), self.assertRaises(ValueError):
                    self.apply([self.item(**{field: value})])
                with self.subTest(field=field), self.assertRaises(ValueError):
                    self.apply(transitions=[{'id': FIRST, 'status': 'withdrawn', field: value}])
        self.assertEqual((self.item_path(FIRST).read_bytes(), self.progress_path.read_bytes()), before)

    def test_all_planned_bytes_and_targets_validate_before_reservation(self):
        before = self.progress_path.read_bytes(), self.item_path(FIRST).read_bytes(), self.pins_path.read_bytes()
        with self.held():
            for transitions in ([{'id': FIRST, 'status': 'superseded', 'superseded_by': FIRST}],
                                [{'id': FIRST, 'status': 'superseded', 'superseded_by': SECOND}],
                                [{'id': FIRST, 'status': 'withdrawn'}]*2):
                with self.assertRaises(ValueError):
                    self.apply(transitions=transitions)
            with mock.patch.object(revision_io, 'reserve', side_effect=AssertionError('unexpected reservation')):
                with self.assertRaises(ValueError):
                    self.apply([self.item(SECOND, title='x'*201)])
        self.assertEqual((self.progress_path.read_bytes(), self.item_path(FIRST).read_bytes(), self.pins_path.read_bytes()), before)

    def test_reservation_failure_forbids_all_item_effects(self):
        before = self.item_path(FIRST).read_bytes(), self.progress_path.read_bytes()
        with self.held(), mock.patch.object(revision_io, 'reserve', side_effect=OSError('fixture durability failure')):
            with self.assertRaises(OSError):
                self.apply([self.item(SECOND)])
        self.assertFalse(self.item_path(SECOND).exists())
        self.assertEqual((self.item_path(FIRST).read_bytes(), self.progress_path.read_bytes()), before)

    def test_every_effect_observes_durable_reserved_revisions(self):
        original = item_io._publish
        observed = []
        def publish(*args):
            progress = self.progress()
            observed.append(progress['fence']['revisions']['item:'+SECOND])
            return original(*args)
        with self.held(), mock.patch.object(item_io, '_publish', side_effect=publish):
            self.apply([self.item(SECOND)])
        self.assertEqual(len(observed), 2)
        self.assertTrue(all(value == self.progress()['fence']['generation'] for value in observed))

    def test_unrelated_saved_statuses_round_trip_without_losing_provenance(self):
        values = [self.item(SECOND, status='undone', undone_by='r_0123456789ab', changed=AT),
                  self.item(THIRD, status='withdrawn', changed=AT)]
        for value in values:
            self.item_path(value['id']).write_bytes(item_types.item_bytes(value))
        before = {value['id']: self.item_path(value['id']).read_bytes() for value in values}
        with self.held():
            self.apply(transitions=[{'id': FIRST, 'status': 'withdrawn'}])
        self.assertEqual({key: self.item_path(key).read_bytes() for key in before}, before)

    def test_malformed_or_backup_only_canonical_records_are_never_silently_restored(self):
        for path in (self.item_path(FIRST), self.pins_path):
            original = path.read_bytes()
            backup = path.with_name(path.name+'.bak')
            backup.write_bytes(original)
            for malformed in (True, False):
                if malformed:
                    path.write_bytes(b'{broken')
                else:
                    path.unlink()
                before = self.progress_path.read_bytes()
                with self.held(), self.assertRaises(files.RestoreNeeded):
                    self.apply([self.item(SECOND)])
                self.assertEqual(self.progress_path.read_bytes(), before)
                self.assertEqual(backup.read_bytes(), original)
                self.assertEqual(path.read_bytes() if path.exists() else None, b'{broken' if malformed else None)
                path.write_bytes(original)
            backup.unlink()

    def test_filename_id_mismatch_is_repair_needed_without_mutation(self):
        self.item_path(FIRST).write_bytes(item_types.item_bytes(self.item(SECOND)))
        before = self.progress_path.read_bytes()
        with self.held(), self.assertRaises(files.RestoreNeeded):
            self.apply([self.item(THIRD)])
        self.assertEqual(self.progress_path.read_bytes(), before)

    def test_stale_proof_and_missing_original_layer_or_curation_lease_block_writes(self):
        proof = self.proof()
        with self.assertRaises(locks.LostLock):
            self.apply([self.item(SECOND)])
        with self.held():
            with self.assertRaises(locks.LostLock):
                self.apply([self.item(SECOND)], run_id='r_0123456789ac')
            progress = self.progress()
            progress['fence']['generation'] += 1
            self.progress_path.write_bytes(format2.curation_bytes(progress))
            with self.assertRaises(fence_plan.Stale):
                item_io.apply(self.memory, self.project, proof, [self.item(SECOND)], [], CHANGED, self.deadline)
        self.assertFalse(self.item_path(SECOND).exists())

    def test_privacy_names_and_backups_block_readdition_without_reading_contents(self):
        for name in ('layer/deleted.json', 'layer/deleted.json.bak', 'layer/tombstones/'+SECOND+'.json', 'layer/tombstones/'+SECOND+'.json.bak'):
            path = self.project / name
            path.write_bytes(b'unreadable fixture marker')
            before = self.progress_path.read_bytes()
            with self.held(), self.assertRaises(fence_plan.Stale):
                self.apply([self.item(SECOND)])
            self.assertEqual(self.progress_path.read_bytes(), before)
            self.assertFalse(self.item_path(SECOND).exists())
            path.unlink()

    def test_tombstoned_stale_item_is_absent_from_rebuilt_list_and_not_reread(self):
        self.item_path(SECOND).write_bytes(b'not readable fixture content')
        (self.project/('layer/tombstones/'+SECOND+'.json')).write_bytes(b'privacy')
        with self.held():
            item_io.rebuild_list(self.memory, self.project, self.proof(), self.deadline)
        self.assertEqual((self.project/'layer/item-list.txt').read_bytes(), item_types.item_list_bytes([self.saved]))

    def more_items(self):
        for item in (SECOND, THIRD):
            self.item_path(item).write_bytes(item_types.item_bytes(self.item(item)))

    def test_the_item_listing_checks_once_between_the_items_that_it_reads(self):
        self.more_items()
        record, events = item_io._record, []
        def reading(memory, path, parse, deadline, check):
            value = record(memory, path, parse, deadline, check)
            if path.parent.name == 'items':
                events.append(path.name[:-5])
            return value
        with self.held():
            guard = revision_io.guard(self.memory, self.project, self.deadline)
            def check():
                events.append(None)
                guard()
            with mock.patch.object(item_io, '_record', side_effect=reading):
                listed = item_io._items(self.memory, self.project, self.deadline, check)
        self.assertEqual([value['id'] for value in listed], [FIRST, SECOND, THIRD])
        self.assertEqual(events, [None, None, FIRST, None, SECOND, None, THIRD, None])

    def test_a_lease_lost_while_the_item_listing_reads_stops_before_the_next_item(self):
        self.more_items()
        record, reads = item_io._record, []
        def reading(memory, path, parse, deadline, check):
            value = record(memory, path, parse, deadline, check)
            if path.parent.name == 'items':
                reads.append(path.name[:-5])
                if len(reads) == 2:
                    self.memory.held[0].token = 'f'*32
            return value
        with self.held():
            check = revision_io.guard(self.memory, self.project, self.deadline)
            with mock.patch.object(item_io, '_record', side_effect=reading), self.assertRaises(locks.LostLock):
                item_io._items(self.memory, self.project, self.deadline, check)
        self.assertEqual(reads, [FIRST, SECOND])

    def test_failure_before_publish_preserves_item_but_keeps_reserved_revision(self):
        before = self.progress()['fence']['generation']
        original = files._sync
        def sync(fd):
            if self.progress()['fence']['generation'] > before:
                raise OSError('fixture item fsync failure')
            return original(fd)
        with self.held(), mock.patch.object(files, '_sync', side_effect=sync):
            with self.assertRaises(item_io.WriteFailed) as caught:
                self.apply([self.item(SECOND)])
        self.assertEqual(caught.exception.published, ())
        self.assertEqual(caught.exception.uncertain, ('item:'+SECOND,))
        self.assertFalse(self.item_path(SECOND).exists())
        self.assertGreater(self.progress()['fence']['revisions']['item:'+SECOND], before)

    def test_failure_after_item_publication_reports_actual_prefix_without_rollback(self):
        original = item_io._publish
        def publish(path, *args):
            if path.name == 'item-list.txt':
                raise OSError('fixture list failure')
            return original(path, *args)
        with self.held(), mock.patch.object(item_io, '_publish', side_effect=publish):
            with self.assertRaises(item_io.WriteFailed) as caught:
                self.apply([self.item(SECOND)])
        self.assertEqual(caught.exception.published, ('item:'+SECOND,))
        self.assertEqual(caught.exception.uncertain, ('item-list',))
        self.assertEqual(item_types.parse_item(self.item_path(SECOND).read_bytes()), self.item(SECOND))
        self.assertIn('item:'+SECOND, self.progress()['fence']['revisions'])

    def test_backup_cleanup_failure_is_reported_as_already_published(self):
        original = files._unlink
        target = self.item_path(FIRST)
        def unlink(path, *args):
            if path == target.with_name(target.name+'.bak') and item_types.parse_item(target.read_bytes())['status'] == 'withdrawn':
                raise OSError('fixture cleanup failure')
            return original(path, *args)
        with self.held(), mock.patch.object(files, '_unlink', side_effect=unlink):
            with self.assertRaises(item_io.WriteFailed) as caught:
                self.apply(transitions=[{'id': FIRST, 'status': 'withdrawn'}])
        self.assertEqual(caught.exception.published, ('item:'+FIRST,))
        self.assertEqual(caught.exception.uncertain, ())
        self.assertEqual(item_types.parse_item(target.read_bytes())['status'], 'withdrawn')
        self.assertTrue(target.with_name(target.name+'.bak').exists())

    def test_lost_lease_between_effects_stops_later_files_and_preserves_actual_prefix(self):
        original = item_io._publish
        def checked_publish(*args):
            value = original(*args)
            self.memory.held[0].token = 'f'*32
            return value
        with self.held(), mock.patch.object(item_io, '_publish', side_effect=checked_publish):
            with self.assertRaises(item_io.WriteFailed) as caught:
                self.apply([self.item(SECOND)])
        self.assertIsInstance(caught.exception.__cause__, locks.LostLock)
        self.assertEqual(caught.exception.published, ('item:'+SECOND,))
        self.assertFalse((self.project/'layer/item-list.txt').exists())

    def test_privacy_marker_after_reservation_blocks_the_first_effect(self):
        original = revision_io.reserve
        def reserve(*args):
            value = original(*args)
            (self.project/('layer/tombstones/'+SECOND+'.json')).write_bytes(b'fixture privacy')
            return value
        with self.held(), mock.patch.object(revision_io, 'reserve', side_effect=reserve):
            with self.assertRaises(item_io.WriteFailed) as caught:
                self.apply([self.item(SECOND)])
        self.assertIsInstance(caught.exception.__cause__, fence_plan.Stale)
        self.assertEqual((caught.exception.attempted, caught.exception.published), ((), ()))
        self.assertFalse(self.item_path(SECOND).exists())
        self.assertIn('item:'+SECOND, self.progress()['fence']['revisions'])

    def test_generation_drift_after_first_effect_blocks_later_files(self):
        original = item_io._publish
        def publish(*args):
            value = original(*args)
            progress = self.progress()
            progress['fence']['generation'] += 1
            self.progress_path.write_bytes(format2.curation_bytes(progress))
            return value
        with self.held(), mock.patch.object(item_io, '_publish', side_effect=publish):
            with self.assertRaises(item_io.WriteFailed) as caught:
                self.apply([self.item(SECOND)])
        self.assertIsInstance(caught.exception.__cause__, fence_plan.Stale)
        self.assertEqual(caught.exception.published, ('item:'+SECOND,))
        self.assertFalse((self.project/'layer/item-list.txt').exists())

    def test_expired_deadline_blocks_the_first_object_effect(self):
        original = revision_io.reserve
        with contextlib.ExitStack() as stack:
            stack.enter_context(self.held())
            def reserve(*args):
                value = original(*args)
                stack.enter_context(mock.patch.object(clock, 'now', return_value=self.deadline+1))
                return value
            stack.enter_context(mock.patch.object(revision_io, 'reserve', side_effect=reserve))
            with self.assertRaises(item_io.WriteFailed) as caught:
                self.apply([self.item(SECOND)])
        self.assertIsInstance(caught.exception.__cause__, locks.LockBusy)
        self.assertEqual(caught.exception.published, ())
        self.assertFalse(self.item_path(SECOND).exists())

    def test_list_rebuild_does_not_recreate_a_consumed_pin_notice(self):
        self.pins_path.write_bytes(item_types.pins_bytes({'pins': [self.pin()]}))
        with self.held():
            self.apply(transitions=[{'id': FIRST, 'status': 'withdrawn'}])
            notice = self.project/('notices/pin-'+FIRST+'.json')
            notice.unlink()
            (self.project/'layer/item-list.txt').write_bytes(b'stale fixture')
            item_io.rebuild_list(self.memory, self.project, self.proof(), self.deadline)
        self.assertFalse(notice.exists())
        self.assertEqual((self.project/'layer/item-list.txt').read_bytes(), b'')

    def test_pure_plan_keeps_input_order_off_pins_and_input_objects(self):
        items = [self.item(), self.item(SECOND)]
        pins = {'pins': [self.pin(), self.pin(SECOND)]}
        additions = [self.item(THIRD), self.item('i_0123456789ae')]
        transitions = [{'id': FIRST, 'status': 'superseded', 'superseded_by': THIRD},
                       {'id': SECOND, 'status': 'superseded', 'superseded_by': 'i_0123456789ae'}]
        original = copy.deepcopy((items, pins, additions, transitions))
        plan = item_plan.plan(items, pins, additions, transitions, CHANGED, DEVICE)
        self.assertEqual((items, pins, additions, transitions), original)
        records = item_types.parse_pins(plan['pins'])['pins']
        self.assertEqual([record['item'] for record in records], [FIRST, SECOND, THIRD, 'i_0123456789ae'])

    def test_original_same_or_new_lease_never_revives_a_plan_or_reservation(self):
        for curator in (False, True):
            for same in (False, True):
                for phase in ('plan', 'reserve'):
                    with self.subTest(curator=curator, same=same, phase=phase):
                        for path in (self.item_path(SECOND), self.project/'layer/item-list.txt'):
                            if path.exists():
                                path.unlink()
                        self.progress_path.write_bytes(format2.curation_bytes(PROGRESS))
                        before = self.progress_path.read_bytes(), self.item_path(FIRST).read_bytes(), self.pins_path.read_bytes()
                        with self.held(curator=curator):
                            originals = list(self.memory.held)
                            def change_ownership():
                                for lease in reversed(originals):
                                    lease.release()
                                replacements = []
                                for lease in originals:
                                    kind = 'curation' if lease.path.name == 'curation.lock' else 'layer'
                                    new = lease if same else self.memory._lock(lease.path, kind, DEVICE)
                                    new.acquire(self.deadline)
                                    replacements.append(new)
                                self.memory.held[:] = replacements
                            original = item_plan.plan if phase == 'plan' else revision_io.reserve
                            def operation(*args, **kwargs):
                                change_ownership()
                                return original(*args, **kwargs)
                            try:
                                target = item_plan if phase == 'plan' else revision_io
                                with mock.patch.object(target, 'plan' if phase == 'plan' else 'reserve', side_effect=operation):
                                    with self.assertRaises(locks.LostLock if phase == 'plan' else item_io.WriteFailed) as caught:
                                        self.apply([self.item(SECOND)], run_id='r_0123456789ac' if curator else None)
                                if phase == 'reserve':
                                    self.assertIsInstance(caught.exception.__cause__, locks.LostLock)
                                    self.assertEqual((caught.exception.attempted, caught.exception.published), ((), ()))
                            finally:
                                for lease in reversed(self.memory.held):
                                    lease.release()
                                self.memory.held[:] = originals
                        self.assertFalse(self.item_path(SECOND).exists())
                        self.assertFalse((self.project/'layer/item-list.txt').exists())
                        self.assertEqual(list((self.project/'notices').iterdir()), [])
                        self.assertEqual((self.item_path(FIRST).read_bytes(), self.pins_path.read_bytes()), before[1:])
                        if phase == 'plan':
                            self.assertEqual(self.progress_path.read_bytes(), before[0])
                        else:
                            self.assertIn('item:'+SECOND, self.progress()['fence']['revisions'])

    def test_run_bearing_operation_binds_curator_before_reads_and_through_planning(self):
        with self.held(), mock.patch.object(item_io, '_items') as read:
            with self.assertRaises(locks.LostLock):
                self.apply([self.item(SECOND)], run_id='r_0123456789ac')
            read.assert_not_called()
        original = item_plan.plan
        def plan(*args):
            value = original(*args)
            curator = self.memory.held[0]
            data = json.loads(curator.path.read_bytes())
            data['token'] = 'f'*32 if curator.token != 'f'*32 else 'e'*32
            curator.path.write_bytes(json.dumps(data).encode('utf-8'))
            curator.token = data['token']
            return value
        before = self.progress_path.read_bytes()
        with self.held(curator=True), mock.patch.object(item_plan, 'plan', side_effect=plan):
            with self.assertRaises(locks.LostLock):
                self.apply([self.item(SECOND)], run_id='r_0123456789ac')
        self.assertEqual(self.progress_path.read_bytes(), before)
        self.assertFalse(self.item_path(SECOND).exists())

    def pinned_failure(self, point):
        off = self.pin(THIRD, False)
        original_pins = item_types.pins_bytes({'pins': [self.pin(), off]})
        self.pins_path.write_bytes(original_pins)
        notice = self.project/('notices/pin-'+FIRST+'.json')
        original_notice = item_types.notice_bytes({'at': AT, 'kind': 'pin-dropped', 'item': FIRST})
        notice.write_bytes(original_notice)
        replace, unlink = os.replace, files._unlink
        def move(source, target):
            if Path(target) == (self.pins_path if point == 'pins-before' else notice) and point != 'pins-cleanup':
                raise OSError('fixture publication failure')
            return replace(source, target)
        def cleanup(path, *args):
            if (point == 'pins-cleanup' and path == self.pins_path.with_name('pins.json.bak') and
                    not item_types.parse_pins(self.pins_path.read_bytes())['pins'][0]['on']):
                raise OSError('fixture pins cleanup failure')
            return unlink(path, *args)
        with self.held(), mock.patch.object(os, 'replace', side_effect=move), mock.patch.object(files, '_unlink', side_effect=cleanup):
            with self.assertRaises(item_io.WriteFailed) as caught:
                self.apply([self.item(SECOND)], [{'id': FIRST, 'status': 'superseded', 'superseded_by': SECOND}])
        error = caught.exception
        expected = ['item:'+SECOND, 'item:'+FIRST]
        if point != 'pins-before':
            expected.append('pins')
        if point == 'notice':
            expected.append('item-list')
        self.assertEqual(error.published, tuple(expected))
        self.assertEqual(error.uncertain, ('pins',) if point == 'pins-before' else (('notice:pin-'+FIRST,) if point == 'notice' else ()))
        self.assertEqual(error.attempted, error.published + error.uncertain)
        self.assertEqual(item_types.parse_item(self.item_path(FIRST).read_bytes()), dict(self.saved, status='superseded', superseded_by=SECOND, changed=CHANGED))
        self.assertEqual(item_types.parse_item(self.item_path(SECOND).read_bytes()), self.item(SECOND))
        if point == 'pins-before':
            self.assertEqual(self.pins_path.read_bytes(), original_pins)
        else:
            self.assertEqual(item_types.parse_pins(self.pins_path.read_bytes())['pins'],
                             [dict(self.pin(), on=False, at=CHANGED), off, dict(self.pin(SECOND), at=CHANGED)])
        self.assertEqual(notice.read_bytes(), original_notice)
        self.assertEqual((self.project/'layer/item-list.txt').exists(), point == 'notice')
        self.assertTrue(all(self.progress()['fence']['revisions'][key] == self.progress()['fence']['generation']
                            for key in ('item:'+FIRST, 'item:'+SECOND, 'pin:'+FIRST, 'pin:'+SECOND)))

    def test_pinned_supersede_failure_before_pins_publication_preserves_actual_prefix(self):
        self.pinned_failure('pins-before')

    def test_pinned_supersede_pins_cleanup_failure_preserves_both_actual_pin_records(self):
        self.pinned_failure('pins-cleanup')

    def test_pinned_supersede_notice_failure_keeps_item_pin_and_list_effects(self):
        self.pinned_failure('notice')
