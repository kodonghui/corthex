"""Internal publication foundation fixtures; no curator or inverse authority."""
import contextlib
import copy
import json
import inspect
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT/'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import clock, fence_plan, files, format2, history_io, history_recovery, item_types, locks, revision_io, state_io, state_plan, state_types
from memory_lib.c2_store import C2Store
from test_memory_fence_plan import PROGRESS
from test_memory_item_types import AT, DEVICE, ITEM
from test_memory_state_types import HISTORY, LINE

SECOND, THIRD, RUN = 's_0123456789ac', 's_0123456789ad', 'r_0123456789ab'


def line(**changes):
    value = copy.deepcopy(LINE)
    value.update(changes)
    return value


def proposal(lines, *operations):
    return {'state':{'lines':lines}, 'operations':list(operations)}


def operation(line_id=LINE['id'], op='changed', why='reason'):
    return {'id':line_id, 'op':op, 'why':why}


class StatePlanTest(unittest.TestCase):
    def plan(self, old, after, removed=()):
        return state_plan.plan({'lines':old}, {'removed':list(removed)}, after, AT, DEVICE)

    def test_change_add_and_addition_caused_cut_derive_every_persisted_prior_row(self):
        original = [line(), line(id=SECOND, text='cut this existing row', pos=2)]
        after = proposal([line(text='changed'), line(id=THIRD, text='new', pos=3)],
                         operation(), operation(SECOND, 'cut', 'cap'), operation(THIRD, 'added', ''))
        plan = self.plan(original, after)
        values = plan.history(PROGRESS, RUN, AT, DEVICE)
        self.assertEqual({v['line'] for v in values}, {LINE['id'], SECOND})
        self.assertEqual({v['line']:v['text'] for v in values}, {v['id']:v['text'] for v in original})
        self.assertEqual(plan.targets, ('line:'+LINE['id'], 'line:'+SECOND, 'line:'+THIRD))
        self.assertEqual(state_types.parse_removed(plan.removed)['removed'],
                         [state_types.removal_marker(SECOND, AT, DEVICE, 'edit')])
        self.assertEqual({v['line']:v['op'] for v in values}, {LINE['id']:'changed', SECOND:'cut'})

    def test_omitted_extra_duplicate_and_wrong_physical_descriptors_are_rejected(self):
        after = proposal([line(text='changed')], operation())
        invalid = [proposal(after['state']['lines']), proposal(after['state']['lines'], operation(), operation()),
                   proposal([], operation()), proposal([line()], operation()),
                   proposal([line(text='changed')], operation(op='stale'))]
        for candidate in invalid:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                self.plan([line()], candidate)

    def test_position_history_and_anchor_metadata_preserve_untouched_rows(self):
        original = [line(), line(id=SECOND, pos=2), line(id=THIRD, pos=3)]
        after = proposal([line(), line(id=SECOND, pos=4), line(id=THIRD, pos=3)],
                         operation(SECOND, 'changed', 'position'))
        plan = self.plan(original, after)
        effect = plan.effects[0]
        self.assertEqual(effect.before_place, ('decisions',2,LINE['id'],THIRD))
        self.assertEqual(effect.after_place, ('decisions',4,THIRD,''))
        self.assertEqual(plan.targets, ('line:'+SECOND,))
        self.assertEqual(plan.history(PROGRESS, RUN, AT, DEVICE)[0]['pos'], 2)
        self.assertEqual(state_types.parse_state(plan.state)['lines'][0], original[0])
        for why, changes in [('other', {}), ('position', {'at':'2026-11-04T00:00:00.000Z'})]:
            candidate = proposal([line(pos=4, **changes)], operation(why=why))
            with self.assertRaisesRegex(ValueError, 'position-only changes preserve content and time'):
                self.plan([line()], candidate)

    def test_position_only_inverse_keeps_undone_history_instead_of_normal_renumbering(self):
        plan = self.plan([line(pos=5)], proposal([line(pos=1)], operation(op='undone', why='undone')))
        record = plan.history(PROGRESS, RUN, AT, DEVICE)[0]
        self.assertEqual((record['op'], record['why'], record['pos']), ('undone','undone',5))
        restored = state_types.parse_state(plan.state)['lines'][0]
        self.assertEqual((restored['text'], restored['cites'], restored['at']),
                         (LINE['text'], LINE['cites'], LINE['at']))

    def test_ordinary_publication_never_reintroduces_any_previously_removed_id(self):
        for extra in ({}, {'kind':'privacy'}, {'kind':'edit'},
                      {'kind':'edit','restored_by':RUN,'restored_at':AT}):
            marker = dict(id=LINE['id'], at=AT, device=DEVICE, **extra)
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.plan([], proposal([line()], operation(op='added', why='')), [marker])

    def test_privacy_unknown_and_unrestored_markers_cannot_archive_existing_content(self):
        for extra in ({}, {'kind':'privacy'}, {'kind':'edit'}, {'kind':'edit','restored_by':RUN}):
            marker = dict(id=LINE['id'], at=AT, device=DEVICE, **extra)
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.plan([line()], proposal([], operation(op='removed')), [marker])

    def test_existing_verified_edit_restoration_can_change_and_new_removal_clears_restore_fields(self):
        prior = dict(id=LINE['id'], at=AT, device=DEVICE, kind='edit', restored_by=RUN, restored_at=AT)
        unrelated = dict(id=SECOND, at=AT, device=DEVICE)
        self.plan([line()], proposal([line(text='changed')], operation()), [prior, unrelated])
        plan = self.plan([line()], proposal([], operation(op='removed')), [prior, unrelated])
        self.assertEqual(state_types.parse_removed(plan.removed)['removed'],
                         [state_types.removal_marker(LINE['id'], AT, DEVICE, 'edit'), unrelated])

    def test_plan_is_detached_and_true_noop_including_array_order_does_not_rewrite(self):
        original = [line(), line(id=SECOND, pos=2)]
        empty = self.plan(original, proposal(list(reversed(original))))
        self.assertEqual((empty.state, empty.removed, empty.effects, empty.targets), (None,None,(),()))
        candidate = proposal([line(text='changed'), original[1]], operation())
        plan = self.plan(original, candidate)
        candidate['state']['lines'][0]['text'] = 'mutated proposal'
        original[0]['text'] = 'mutated original'
        self.assertEqual(state_types.parse_state(plan.state)['lines'][0]['text'], 'changed')
        self.assertEqual(plan.history(PROGRESS, RUN, AT, DEVICE)[0]['text'], LINE['text'])

    def test_pure_add_needs_no_previous_history_and_stale_recited_descriptors_preserve_prior_versions(self):
        plan = self.plan([], proposal([line()], operation(op='added', why='')))
        self.assertEqual(plan.history(PROGRESS, RUN, AT, DEVICE), ())
        for op, after in [('stale', []), ('recited', [line(cites=['i_0123456789ac'])]),
                          ('undone', [line(text='inverse replacement')])]:
            plan = self.plan([line()], proposal(after, operation(op=op)))
            self.assertEqual(plan.history(PROGRESS, RUN, AT, DEVICE)[0]['op'], op)


class _StateFixture:
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name).resolve()/'memory'
        (self.folder/'logs').mkdir(parents=True)
        self.project = self.folder/'projects/sample'
        (self.project/'layer/tombstones').mkdir(parents=True)
        (self.folder/'store.json').write_bytes(format2.store_bytes(
            {'format':2, 'device':DEVICE, 'made':AT, 'release':'0.2.1'}))
        self.path = self.project/'curation.json'
        self.good = format2.curation_bytes(PROGRESS)
        self.path.write_bytes(self.good)
        self.backup = self.path.with_name(self.path.name+'.bak')
        self.history = self.project/'state-history.jsonl'
        self.history.write_bytes(b'')
        self.memory = C2Store(self.folder, expected_device=DEVICE)
        self.deadline = clock.now()+40

    @contextlib.contextmanager
    def held(self):
        with self.memory.lease(self.project/'curation.lock', 'curation', self.deadline):
            with self.memory.lease(self.project/'layer.lock', 'layer', self.deadline):
                yield

    def reserve(self):
        return revision_io.reserve(self.memory, self.project, fence_plan.snapshot(PROGRESS),
                                   ['line:'+LINE['id']], self.deadline, RUN, primary_only=True)


class StrictStateReservationTest(_StateFixture, unittest.TestCase):
    def test_strict_initial_reserve_refuses_missing_or_damaged_primary_without_restoring_backup(self):
        for damaged in (None, b'broken'):
            self.backup.write_bytes(self.good)
            if damaged is None:
                self.path.unlink()
            else:
                self.path.write_bytes(damaged)
            with self.held(), self.assertRaises(files.RestoreNeeded):
                self.reserve()
            self.assertEqual(self.path.read_bytes() if self.path.exists() else None, damaged)
            self.assertEqual(self.backup.read_bytes(), self.good)

    def test_strict_reservation_lifetime_never_promotes_a_later_good_backup(self):
        with self.held():
            reservation = self.reserve()
            self.assertIs(reservation.primary_only, True)
            current = self.path.read_bytes()
            self.backup.write_bytes(current)
            for damaged in (b'broken', None):
                if damaged is None:
                    self.path.unlink()
                else:
                    self.path.write_bytes(damaged)
                with self.assertRaises(files.RestoreNeeded):
                    reservation.check()
                self.assertEqual(self.path.read_bytes() if self.path.exists() else None, damaged)
                self.assertEqual(self.backup.read_bytes(), current)

    def test_indirect_history_binding_and_live_receipt_keep_the_same_strict_policy(self):
        with self.held():
            reservation = self.reserve()
            plan = state_plan.plan({'lines':[line()]}, {'removed':[]},
                                   proposal([line(text='changed')], operation()), AT, DEVICE)
            values = plan.history(reservation.progress, RUN, AT, DEVICE)
            self.backup.write_bytes(self.path.read_bytes())
            with history_io.append(self.memory, self.project, reservation, values, self.deadline,
                                   archive_precondition=lambda *args: None) as receipt:
                self.path.write_bytes(b'broken')
                with self.assertRaises(files.RestoreNeeded):
                    receipt.check()
                self.assertEqual(self.path.read_bytes(), b'broken')
            self.history.write_bytes(b'')
            with self.assertRaises(files.RestoreNeeded):
                with history_io.append(self.memory, self.project, reservation, values, self.deadline,
                                       archive_precondition=lambda *args: None):
                    self.fail('damaged strict control yielded history authority')
            self.assertEqual(self.history.read_bytes(), b'')

    def test_default_reservation_recovery_rotates_epoch_and_invalidates_its_old_proof(self):
        with self.held():
            reservation = revision_io.reserve(self.memory, self.project, fence_plan.snapshot(PROGRESS),
                                               ['line:'+LINE['id']], self.deadline, RUN)
            self.assertIs(reservation.primary_only, False)
            prior = reservation.progress
            self.backup.write_bytes(self.path.read_bytes())
            self.path.write_bytes(b'broken')
            with self.assertRaises(fence_plan.Stale):
                reservation.check()
            recovered = format2.parse_curation(self.path.read_bytes())
            self.assertNotEqual(recovered['fence']['epoch'], prior['fence']['epoch'])
            self.assertEqual((recovered['fence']['generation'], recovered['fence']['revisions']), (0,{}))
            self.assertFalse(self.backup.exists())
            self.assertEqual(reservation.progress, prior)


class StatePublicationTest(_StateFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        (self.project/'layer/items').mkdir()
        self.item = self.project/'layer/items'/(ITEM['id']+'.json')
        self.item.write_bytes(item_types.item_bytes(ITEM))
        self.state = self.project/'layer/state.json'
        self.marker = self.project/'layer/state-removed.json'
        self.state.write_bytes(state_types.state_bytes({'lines':[line(), line(id=SECOND, pos=2, text='earlier second row')]}))
        self.marker.write_bytes(state_types.removed_bytes({'removed':[]}))
        self.initial = self.state.read_bytes(), self.marker.read_bytes()
        self.deadline = clock.now()+120

    def precondition(self):
        original = revision_io.guard(self.memory, self.project, self.deadline, curator=True)
        sources = tuple(sorted((('state',state_io._sha(self.state.read_bytes())),
                                ('removed',state_io._sha(self.marker.read_bytes())))))
        def check(memory, root, binding):
            original()
            if memory is not self.memory or root != self.project or binding.original_sources != sources:
                raise ValueError('fixture original state context mismatch')
            self.assertIsInstance(binding.facts, tuple)
            original()
        return check

    def change(self):
        return proposal([line(text='changed'), line(id=THIRD, pos=3, text='added')],
                        operation(), operation(SECOND,'removed','ordinary edit'), operation(THIRD,'added',''))

    def apply(self, candidate=None, callback=None):
        expected = fence_plan.snapshot(format2.parse_curation(self.path.read_bytes()))
        return state_io.apply(self.memory, self.project, expected, self.change() if candidate is None else candidate,
                              AT, self.deadline, RUN, state_precondition=self.precondition() if callback is None else callback)

    def test_complete_required_history_is_durable_before_marker_then_state_publication(self):
        replace, sync = os.replace, files._sync
        observed, durable = [], []
        history_identity = self.history.stat().st_dev, self.history.stat().st_ino
        def synced(fd):
            info = os.fstat(fd)
            if (info.st_dev,info.st_ino) == history_identity:
                durable.append(info.st_size)
            return sync(fd)
        def replacing(source, target):
            target = Path(target)
            if target in (self.state,self.marker):
                records = state_types.parse_history(self.history.read_bytes())
                self.assertEqual({record.value['line'] for record in records}, {LINE['id'],SECOND})
                self.assertTrue(durable and durable[-1] == self.history.stat().st_size)
                if target == self.marker:
                    self.assertEqual(self.state.read_bytes(), self.initial[0])
                observed.append(target.name)
            return replace(source,target)
        with self.held(), mock.patch.object(os,'replace',side_effect=replacing), mock.patch.object(files,'_sync',side_effect=synced):
            result = self.apply()
        self.assertEqual(observed, ['state-removed.json','state.json'])
        self.assertEqual(result['published'], ('removed','state'))
        self.assertFalse(result['cleanup_pending'])
        self.assertEqual({value['line'] for value in result['lines'] if value['history']}, {LINE['id'],SECOND})
        self.assertNotIn(LINE['text'], json.dumps(result,ensure_ascii=False))
        self.assertFalse(list((self.project/'layer').glob('state*.bak')))
        self.assertFalse(list((self.project/'layer').glob('state*.tmp')))

    def test_short_write_write_then_error_and_fsync_uncertainty_keep_both_state_files_and_adds_unchanged(self):
        real_write, real_sync = os.write, files._sync
        for mode in ('short','write-error','fsync'):
            with self.subTest(mode=mode):
                self.history.write_bytes(b'')
                identity = self.history.stat().st_dev,self.history.stat().st_ino
                def matches(fd):
                    info = os.fstat(fd)
                    return (info.st_dev,info.st_ino) == identity
                def writing(fd,data):
                    if matches(fd) and mode != 'fsync':
                        count = real_write(fd,data[:max(1,len(data)//2)])
                        if mode == 'write-error':
                            raise OSError('injected after real history prefix')
                        return count
                    return real_write(fd,data)
                def syncing(fd):
                    if matches(fd) and mode == 'fsync':
                        raise OSError('injected history durability uncertainty')
                    return real_sync(fd)
                with self.held(), mock.patch.object(os,'write',side_effect=writing), mock.patch.object(files,'_sync',side_effect=syncing):
                    with self.assertRaises(state_io.PublicationFailed) as caught:
                        self.apply()
                self.assertEqual((self.state.read_bytes(),self.marker.read_bytes()), self.initial)
                self.assertEqual(caught.exception.published, ())
                self.assertEqual(caught.exception.attempted, ())
                self.assertIsNotNone(caught.exception.progress)

    def test_invalid_history_suffix_never_restores_backup_or_publishes_any_state(self):
        damaged = state_types.history_record_bytes(HISTORY)+b'broken'
        self.history.write_bytes(damaged)
        backup = self.history.with_name(self.history.name+'.bak')
        backup.write_bytes(b'')
        with self.held(), self.assertRaises(state_io.PublicationFailed):
            self.apply()
        self.assertEqual((self.state.read_bytes(),self.marker.read_bytes()), self.initial)
        self.assertEqual(self.history.read_bytes(), damaged)
        self.assertEqual(backup.read_bytes(), b'')

    def test_pure_add_does_not_open_missing_or_damaged_unrelated_history(self):
        for data in (None,b'broken'):
            with self.subTest(data=data):
                self.state.write_bytes(state_types.state_bytes({'lines':[]}))
                if data is None:
                    self.history.unlink()
                else:
                    self.history.write_bytes(data)
                candidate = proposal([line()], operation(op='added',why=''))
                with self.held(), mock.patch.object(history_io,'append',side_effect=AssertionError('pure add opened history')):
                    result = self.apply(candidate)
                self.assertEqual(result['published'], ('state',))
                self.assertIsNone(result['lines'][0]['history'])
                self.assertEqual(self.history.read_bytes() if self.history.exists() else None, data)

    def test_true_noop_has_no_reservation_append_or_file_rewrite(self):
        current = state_types.parse_state(self.state.read_bytes())
        with self.held(), mock.patch.object(revision_io,'reserve') as reserve, mock.patch.object(history_io,'append') as append, mock.patch.object(os,'replace') as replace:
            result = self.apply(proposal(current['lines']))
        reserve.assert_not_called()
        append.assert_not_called()
        replace.assert_not_called()
        self.assertIsNone(result['progress'])
        self.assertEqual(result['published'], ())
        self.assertEqual((self.state.read_bytes(),self.marker.read_bytes()), self.initial)

    def test_initial_and_postappend_non_none_preconditions_cannot_authorize_state_changes(self):
        with self.held(), self.assertRaises(TypeError):
            self.apply(callback=lambda *args: False)
        with self.held():
            checked = self.precondition()
            def late(memory,root,binding):
                checked(memory,root,binding)
                return False if self.history.stat().st_size else None
            with self.assertRaises(state_io.PublicationFailed):
                self.apply(callback=late)
        self.assertEqual((self.state.read_bytes(),self.marker.read_bytes()), self.initial)

    def test_marker_publication_then_state_failure_reports_exact_prefix_and_retains_backup(self):
        replace = os.replace
        def replacing(source,target):
            if Path(target) == self.state:
                raise fence_plan.Stale()
            return replace(source,target)
        with self.held(), mock.patch.object(os,'replace',side_effect=replacing):
            with self.assertRaises(state_io.PublicationFailed) as caught:
                self.apply()
        self.assertEqual(caught.exception.published, ('removed',))
        self.assertEqual(caught.exception.uncertain, ('state',))
        self.assertTrue(caught.exception.cleanup_pending)
        self.assertEqual(self.state.read_bytes(), self.initial[0])
        self.assertEqual(state_types.parse_removed(self.marker.read_bytes())['removed'][0]['id'], SECOND)
        self.assertEqual(self.state.with_name('state.json.bak').read_bytes(), self.initial[0])

    def test_postpublication_backup_cleanup_failure_stops_before_next_canonical_file(self):
        unlink = Path.unlink
        backup = self.marker.with_name(self.marker.name+'.bak')
        attempted = []
        def unlinking(path,*args,**kwargs):
            if Path(path) == backup:
                attempted.append(Path(path))
                raise PermissionError('held marker backup')
            return unlink(path,*args,**kwargs)
        with self.held(), mock.patch.object(Path,'unlink',new=unlinking):
            with self.assertRaises(state_io.PublicationFailed) as caught:
                self.apply()
        self.assertTrue(attempted)
        self.assertEqual(caught.exception.published, ('removed',))
        self.assertTrue(backup.exists())
        self.assertEqual(self.state.read_bytes(), self.initial[0])

    def late_handoff(self, mutation, target=None):
        target = self.state if target is None else target
        read, fired = state_io._read, []
        def reading(memory,path,deadline,ownership,durable=False):
            result = read(memory,path,deadline,ownership,durable)
            frame = inspect.currentframe().f_back
            while frame is not None and frame.f_code.co_name != 'source_check':
                frame = frame.f_back
            attempt = None if frame is None else frame.f_back
            if (not fired and Path(path) == self.marker and frame is not None and
                    attempt.f_code.co_name == 'attempt' and attempt.f_locals.get('path') == target):
                fired.append(True)
                mutation(attempt.f_locals['temporary'])
            return result
        with self.held(), mock.patch.object(state_io,'_read',side_effect=reading):
            with self.assertRaises(state_io.PublicationFailed) as caught:
                self.apply()
        self.assertEqual(fired, [True])
        self.assertNotIn('removed' if target == self.marker else 'state', caught.exception.published)
        self.assertEqual(self.state.read_bytes(), self.initial[0])
        return caught.exception

    def test_item_status_drift_during_final_source_read_blocks_state_publication(self):
        def mutate(_):
            value = copy.deepcopy(ITEM)
            value.update(status='withdrawn',changed=AT)
            self.item.write_bytes(item_types.item_bytes(value))
        self.late_handoff(mutate)

    def test_project_deletion_fact_drift_during_final_source_read_blocks_state_publication(self):
        self.late_handoff(lambda _: (self.project/'layer/deleted.json.bak').write_bytes(b'private deletion fact'))

    def test_same_inode_staging_mutation_during_final_source_read_is_never_published(self):
        def mutate(temporary):
            data = temporary.read_bytes()
            self.assertIn(b'changed', data)
            temporary.write_bytes(data.replace(b'changed', b'altered'))
        self.late_handoff(mutate)

    def test_history_truncation_during_final_source_read_blocks_both_canonical_files(self):
        self.late_handoff(lambda _: self.history.write_bytes(b''), self.marker)
        self.assertEqual((self.state.read_bytes(),self.marker.read_bytes()), self.initial)

    def test_history_loss_after_marker_publication_keeps_the_known_prefix_without_state_publication(self):
        error = self.late_handoff(lambda _: self.history.write_bytes(b''))
        self.assertEqual(error.published,('removed',))
        self.assertNotEqual(self.marker.read_bytes(),self.initial[1])

    def test_tombstone_fact_arriving_during_final_source_read_blocks_both_canonical_files(self):
        def mutate(_):
            value = {'item':ITEM['id'],'project':'sample','at':AT,'device':DEVICE,
                     'quotes':[{key:quote[key] for key in ('device','entry','log','start','end')} for quote in ITEM['quotes']]}
            (self.project/'layer/tombstones'/(ITEM['id']+'.json')).write_bytes(item_types._raw(value))
        self.late_handoff(mutate, self.marker)
        self.assertEqual((self.state.read_bytes(),self.marker.read_bytes()), self.initial)

    def more_items(self):
        names = [ITEM['id']]
        for item in ('i_0123456789ac','i_0123456789ad'):
            value = copy.deepcopy(ITEM)
            value['id'] = item
            (self.project/'layer/items'/(item+'.json')).write_bytes(item_types.item_bytes(value))
            names.append(item)
        return [name+'.json' for name in names]

    def test_publication_checks_the_leases_once_after_each_item_file_that_it_reads_again(self):
        # A tombstone of another item, which no line cites, is read in each pass too.
        tombstone = {'item':'i_0123456789ae','project':'sample','at':AT,'device':DEVICE,
                     'quotes':[{key:quote[key] for key in ('device','entry','log','start','end')} for quote in ITEM['quotes']]}
        (self.project/'layer/tombstones/i_0123456789ae.json').write_bytes(item_types._raw(tombstone))
        items = self.more_items()
        names, events, listings, started = items+['i_0123456789ae.json'], [], [], []
        read, project_check, listing = state_io._read, history_io._project_check, history_recovery._names
        facts_check = state_io._facts_check
        def reading(memory,path,deadline,check,durable=False):
            result = read(memory,path,deadline,check,durable)
            if Path(path).parent.name in ('items','tombstones'):
                events.append(Path(path).name)
            return result
        def checking(memory,root,check):
            guarded = project_check(memory,root,check)
            def logged():
                events.append(None)
                guarded()
            return logged
        def naming(memory,folder,*args,**kwargs):
            start = len(events)
            try:
                return listing(memory,folder,*args,**kwargs)
            finally:
                listings.append((Path(folder).name,start,len(events)))
        def passing(*args,**kwargs):
            started.append(len(events))
            return facts_check(*args,**kwargs)
        with self.held(), mock.patch.object(state_io,'_read',side_effect=reading), \
                mock.patch.object(history_io,'_project_check',side_effect=checking), \
                mock.patch.object(history_recovery,'_names',side_effect=naming), \
                mock.patch.object(state_io,'_facts_check',side_effect=passing):
            self.apply()
        reads = [index for index,event in enumerate(events) if event is not None]
        passes = len(reads)//len(names)
        self.assertGreaterEqual(passes, 3)
        self.assertEqual([events[index] for index in reads], names*passes)
        # Each file that a pass reads lies between two checks of the leases,
        # the first of each pass and the last included.
        self.assertIsNone(events[reads[0]-1])
        for before, after in zip(reads, reads[1:]):
            self.assertGreater(after-before, 1)
        self.assertIsNone(events[reads[-1]+1])
        # No check repeats around the steps of one read, in any pass, the
        # catalogue included. The catalogue's first file follows the items'
        # listing with no check between them, and the tombstones' listing, with
        # its own checks, comes between its last item and its first tombstone,
        # one check before it and none after it. Each full pass's first file
        # follows that pass's first check, and within each pass one check comes
        # between two files.
        firsts, last, first = reads[::len(names)], reads[len(items)-1], reads[len(items)]
        listed = [end for name,_,end in listings if name == 'items' and end <= firsts[0]]
        self.assertEqual(events[listed[-1]:firsts[0]], [])
        between = [(start,end) for name,start,end in listings if name == 'tombstones' and last < start and end <= first]
        self.assertEqual(len(between), 1)
        self.assertEqual(events[last+1:between[0][0]], [None])
        self.assertEqual(events[between[0][1]:first], [])
        for index in firsts[1:]:
            self.assertEqual(events[max(start for start in started if start < index):index], [None])
        for before, after in zip(reads, reads[1:]):
            if after != first and after not in firsts:
                self.assertEqual(events[before+1:after], [None])

    def test_a_lease_lost_while_publication_reads_an_item_file_again_stops_before_the_next(self):
        names, reads = self.more_items(), []
        read = state_io._read
        def reading(memory,path,deadline,check,durable=False):
            result = read(memory,path,deadline,check,durable)
            if Path(path).parent.name == 'items':
                reads.append(Path(path).name)
                if len(reads) == len(names)+2:
                    self.memory.held[1].token = 'f'*32
            return result
        with self.held(), mock.patch.object(state_io,'_read',side_effect=reading):
            with self.assertRaises(locks.LostLock):
                self.apply()
        self.assertEqual(reads, names+names[:2])
        self.assertEqual((self.state.read_bytes(),self.marker.read_bytes()), self.initial)
        self.assertEqual(self.path.read_bytes(), self.good)

    def test_a_lease_lost_during_an_item_read_that_fails_is_what_publication_reports(self):
        names, reads = self.more_items(), []
        read = state_io._read
        def reading(memory,path,deadline,check,durable=False):
            if Path(path).parent.name == 'items':
                reads.append(Path(path).name)
                if len(reads) == len(names)+2:
                    # The file changed as the lease was lost, during its read.
                    self.memory.held[1].token = 'f'*32
                    raise fence_plan.Stale()
            return read(memory,path,deadline,check,durable)
        with self.held(), mock.patch.object(state_io,'_read',side_effect=reading):
            with self.assertRaises(locks.LostLock) as caught:
                self.apply()
        self.assertIsInstance(caught.exception.__context__, fence_plan.Stale)
        self.assertEqual(reads, names+names[:2])
        self.assertEqual((self.state.read_bytes(),self.marker.read_bytes()), self.initial)
        self.assertEqual(self.path.read_bytes(), self.good)

    def test_caller_expected_mutation_cannot_change_returned_before_revision_proof(self):
        with self.held():
            expected = fence_plan.snapshot(format2.parse_curation(self.path.read_bytes()))
            prior = expected['fence']['revisions'].get('line:'+LINE['id'])
            checked, mutated = self.precondition(), []
            def changing(memory,root,binding):
                checked(memory,root,binding)
                if binding.reservation is not None and not mutated:
                    expected['fence']['revisions']['line:'+LINE['id']] = 999
                    mutated.append(True)
            result = state_io.apply(self.memory,self.project,expected,self.change(),AT,self.deadline,RUN,
                                    state_precondition=changing)
        self.assertEqual(mutated,[True])
        effect = next(value for value in result['lines'] if value['line'] == LINE['id'])
        self.assertEqual(effect['before_revision'], prior)

    def ownership_handoff(self, phase):
        for kind in ('curation-token','joint','layer'):
            for same in ((None,) if kind == 'curation-token' else (True,False)):
                with self.subTest(phase=phase,kind=kind,same=same):
                    case = StatePublicationTest('test_true_noop_has_no_reservation_append_or_file_rewrite')
                    case.setUp()
                    self.addCleanup(case.doCleanups)
                    with case.held():
                        checked, replacements, fired = case.precondition(), [], []
                        def changing(memory,root,binding):
                            checked(memory,root,binding)
                            eligible = (binding.reservation is None if phase == 'pre-reserve' else
                                        bool(binding.published) if phase == 'after-marker' else
                                        binding.reservation is not None and case.history.stat().st_size > 0)
                            if eligible and not fired:
                                fired.append(True)
                                if kind == 'curation-token':
                                    path = case.project/'curation.lock'
                                    value = json.loads(path.read_text(encoding='utf-8'))
                                    value['token'] = 'f'*32 if value['token'] != 'f'*32 else 'a'*32
                                    path.write_bytes(item_types._raw(value))
                                else:
                                    indexes = (0,1) if kind == 'joint' else (1,)
                                    originals = {index:case.memory.held[index] for index in indexes}
                                    for index in reversed(indexes):
                                        originals[index].release()
                                    for index in indexes:
                                        policy = 'curation' if index == 0 else 'layer'
                                        lease = originals[index]
                                        newer = lease if same else case.memory._lock(case.project/(policy+'.lock'),policy,DEVICE)
                                        newer.acquire(case.deadline)
                                        case.memory.held[index] = newer
                                        replacements.append((index,lease,newer))
                        try:
                            with self.assertRaises((locks.LostLock,state_io.PublicationFailed)) as caught:
                                case.apply(callback=changing)
                            self.assertEqual(fired,[True])
                            self.assertNotIsInstance(getattr(caught.exception,'__cause__',None),locks.LockOrderError)
                            self.assertEqual(case.state.read_bytes(),case.initial[0])
                            expected = ('removed',) if phase == 'after-marker' else ()
                            self.assertEqual(getattr(caught.exception,'published',()),expected)
                            if phase != 'after-marker':
                                self.assertEqual(case.marker.read_bytes(),case.initial[1])
                        finally:
                            for index,lease,newer in reversed(replacements):
                                newer.release()
                                case.memory.held[index] = lease

    def test_original_curator_and_layer_loss_before_reserve_cannot_revive(self):
        self.ownership_handoff('pre-reserve')

    def test_original_curator_and_layer_loss_before_publication_cannot_revive(self):
        self.ownership_handoff('pre-publish')

    def test_original_curator_and_layer_loss_after_marker_preserves_exact_prefix(self):
        self.ownership_handoff('after-marker')

    def test_second_stage_verification_failure_cleans_owned_temp_and_retains_original_error(self):
        read, fired = state_io._read, []
        failure = OSError('injected after durable staging before additional verification')
        def reading(memory,path,deadline,ownership,durable=False):
            if durable and Path(path).name.endswith('.tmp') and not fired:
                fired.append(True)
                raise failure
            return read(memory,path,deadline,ownership,durable)
        with self.held(), mock.patch.object(state_io,'_read',side_effect=reading):
            with self.assertRaises(state_io.PublicationFailed) as caught:
                self.apply()
        self.assertEqual(fired,[True])
        self.assertIs(caught.exception.__cause__,failure)
        self.assertEqual((self.state.read_bytes(),self.marker.read_bytes()),self.initial)
        self.assertFalse(list((self.project/'layer').glob('state*.tmp')))

    def test_closed_append_context_cannot_lend_authority_to_state_publication(self):
        append = history_io.append
        @contextlib.contextmanager
        def closed(*args,**kwargs):
            with append(*args,**kwargs) as receipt:
                pass
            yield receipt
        with self.held(), mock.patch.object(history_io,'append',closed):
            with self.assertRaises(state_io.PublicationFailed):
                self.apply()
        self.assertEqual((self.state.read_bytes(),self.marker.read_bytes()),self.initial)

    def test_valid_unrelated_history_suffix_preserves_individual_owned_record_links(self):
        create = history_io.DurableHistory.__init__
        def created(receipt,*args):
            create(receipt,*args)
            with self.history.open('ab') as output:
                output.write(state_types.history_record_bytes(HISTORY))
        with self.held(), mock.patch.object(history_io.DurableHistory,'__init__',created):
            result = self.apply()
        self.assertEqual(result['published'],('removed','state'))
        records = state_types.parse_history(self.history.read_bytes())
        self.assertEqual(len(records),3)
        self.assertEqual({effect['history'][3] for effect in result['lines'] if effect['history']},
                         {record.sha256 for record in records[:2]})

    def test_uncertain_state_replacement_reports_unknown_effect_and_keeps_recovery_bytes(self):
        replace, effects = os.replace, []
        def replacing(source,target):
            result = replace(source,target)
            if Path(target) == self.state:
                effects.append(True)
                raise OSError('injected uncertainty after actual state replacement')
            return result
        with self.held(), mock.patch.object(os,'replace',side_effect=replacing):
            with self.assertRaises(state_io.PublicationFailed) as caught:
                self.apply()
        self.assertEqual(effects,[True])
        self.assertEqual(caught.exception.published,('removed',))
        self.assertEqual(caught.exception.uncertain,('state',))
        self.assertNotEqual(self.state.read_bytes(),self.initial[0])
        self.assertEqual(self.state.with_name('state.json.bak').read_bytes(),self.initial[0])

    def test_privacy_sidecopy_during_cleanup_read_preserves_original_backup(self):
        read, fired = state_io._read, []
        def reading(memory,path,deadline,ownership,durable=False):
            result = read(memory,path,deadline,ownership,durable)
            frame = inspect.currentframe().f_back
            while frame is not None and frame.f_code.co_name != 'source_check':
                frame = frame.f_back
            parent = None if frame is None else frame.f_back
            if (not fired and Path(path) == self.marker and parent is not None and parent.f_code.co_name == 'cleanup_guard'):
                fired.append(True)
                (self.project/'layer/tombstones'/(ITEM['id']+'.json.bak')).write_bytes(b'unresolved fact copy')
            return result
        with self.held(), mock.patch.object(state_io,'_read',side_effect=reading):
            with self.assertRaises(state_io.PublicationFailed) as caught:
                self.apply()
        self.assertEqual(fired,[True])
        self.assertEqual(caught.exception.published,('removed',))
        self.assertTrue(self.marker.with_name(self.marker.name+'.bak').exists())
        self.assertEqual(self.state.read_bytes(),self.initial[0])

    def test_permission_failure_in_receipt_binding_or_late_pin_cannot_revive_on_retry(self):
        for mode in ('binding','history'):
            with self.subTest(mode=mode):
                case = StatePublicationTest('test_true_noop_has_no_reservation_append_or_file_rewrite')
                case.setUp()
                self.addCleanup(case.doCleanups)
                create, read, retry = history_io.DurableHistory.__init__, state_io._read, files._retry
                failure, fired, attempts = PermissionError('injected temporary proof refusal'), [], []
                def at_attempt():
                    frame = inspect.currentframe().f_back
                    while frame is not None:
                        if frame.f_code.co_name == 'attempt' and Path(frame.f_code.co_filename).name == 'state_io.py':
                            return True
                        frame = frame.f_back
                    return False
                def created(receipt,*args):
                    create(receipt,*args)
                    original = receipt._guard
                    def guard():
                        if mode == 'binding' and not fired and at_attempt():
                            fired.append(True)
                            raise failure
                        return original()
                    receipt._guard = guard
                def reading(memory,path,deadline,ownership,durable=False):
                    if mode == 'history' and Path(path) == case.history and durable and not fired:
                        fired.append(True)
                        raise failure
                    return read(memory,path,deadline,ownership,durable)
                def one_retry(function,deadline=None):
                    if (function.__name__ == 'attempt' and Path(function.__code__.co_filename).name == 'state_io.py'):
                        attempts.append(True)
                        try:
                            return function()
                        except PermissionError:
                            # Controlled bounded retry of the exact publication
                            # boundary; all original guards/deadlines still run.
                            attempts.append(True)
                            return function()
                    return retry(function,deadline)
                with case.held(), mock.patch.object(history_io.DurableHistory,'__init__',created), \
                        mock.patch.object(state_io,'_read',side_effect=reading), mock.patch.object(files,'_retry',side_effect=one_retry):
                    with self.assertRaises(state_io.PublicationFailed) as caught:
                        case.apply()
                self.assertEqual(fired,[True])
                self.assertEqual(attempts,[True,True])
                self.assertEqual(caught.exception.published,())
                self.assertIs(caught.exception.__cause__,failure)
                self.assertEqual((case.state.read_bytes(),case.marker.read_bytes()),case.initial)

    def test_raw_expiry_does_not_invalidate_ordinary_old_citations(self):
        raw = self.project/'raw'
        raw.mkdir()
        expired = raw/'expired.jsonl'
        expired.write_bytes(b'old raw')
        with self.held():
            checked, removed = self.precondition(), []
            def expiring(memory,root,binding):
                checked(memory,root,binding)
                if binding.reservation is not None and not removed:
                    expired.unlink()
                    removed.append(True)
            result = self.apply(callback=expiring)
        self.assertEqual(removed, [True])
        self.assertEqual(result['published'], ('removed','state'))


if __name__ == '__main__':
    unittest.main()
