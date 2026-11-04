"""Partial TASK-075 proof; no lease, disk publication or whole-case claim."""
import copy
from pathlib import Path
import sys
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import fence_plan

PROGRESS = {'logs': {'codex-0123456789abcdef': 8}, 'applies': 2,
            'recent': [{'at': '2026-11-04T13:00:00.000Z', 'kind': 'curate', 'result': 'ok'}],
            'consolidation': {'failures': 0},
            'fence': {'epoch': '0123456789abcdef' * 2, 'generation': 8,
                      'revisions': {'item:i_0123456789ab': 3, 'run:r_0123456789ab': 8}}}


class FencePlanTest(unittest.TestCase):
    def test_empty_no_run_reservation_is_rejected(self):
        with self.assertRaises(ValueError):
            fence_plan.advance(PROGRESS, fence_plan.snapshot(PROGRESS), [])

    def test_snapshot_excludes_progress_and_is_detached(self):
        original = copy.deepcopy(PROGRESS)
        proof = fence_plan.snapshot(PROGRESS)
        self.assertEqual(set(proof), {'applies', 'fence'})
        proof['fence']['revisions'].clear()
        self.assertEqual(PROGRESS, original)

    def test_advance_reserves_objects_and_run_without_changing_fresh_progress(self):
        original = copy.deepcopy(PROGRESS)
        value = fence_plan.advance(PROGRESS, fence_plan.snapshot(PROGRESS),
                                   ['line:s_0123456789ab', 'pin:i_0123456789ab'], 'r_0123456789ac')
        self.assertEqual(value['fence']['generation'], 9)
        self.assertEqual(value['fence']['revisions']['run:r_0123456789ac'], 9)
        self.assertEqual(value['fence']['revisions']['line:s_0123456789ab'], 9)
        self.assertEqual(value['fence']['revisions']['pin:i_0123456789ab'], 9)
        self.assertEqual(value['fence']['revisions']['item:i_0123456789ab'], 3)
        self.assertEqual(value['fence']['revisions']['run:r_0123456789ab'], 8)
        self.assertEqual({k: v for k, v in value.items() if k != 'fence'},
                         {k: v for k, v in original.items() if k != 'fence'})
        self.assertEqual(PROGRESS, original)

    def test_missing_revision_stays_absent_until_it_is_explicitly_reserved(self):
        proof = fence_plan.snapshot(PROGRESS)
        self.assertNotIn('line:s_0123456789ab', proof['fence']['revisions'])
        value = fence_plan.advance(PROGRESS, proof, [], 'r_0123456789ac')
        self.assertNotIn('line:s_0123456789ab', value['fence']['revisions'])

    def test_fresh_progress_only_changes_are_preserved_without_staling(self):
        proof = fence_plan.snapshot(PROGRESS)
        fresh = copy.deepcopy(PROGRESS)
        fresh['logs']['codex-0123456789abcdef'] = 9
        fresh['recent'].append({'at': '2026-11-05T00:00:00.000Z', 'kind': 'curate', 'result': 'failed'})
        fresh['failures'] = {'count': 1, 'log': 'codex-0123456789abcdef', 'turn': 4}
        fresh['consolidation']['failures'] = 2
        fresh['conflict_after'] = 'c_0123456789ab'
        original = copy.deepcopy(fresh)
        value = fence_plan.advance(fresh, proof, ['item:i_0123456789ab'], 'r_0123456789ac')
        self.assertEqual({k: v for k, v in value.items() if k != 'fence'},
                         {k: v for k, v in original.items() if k != 'fence'})
        self.assertEqual(fresh, original)

    def test_any_prior_apply_or_epoch_or_revision_change_stales_a_request(self):
        proof = fence_plan.snapshot(PROGRESS)
        for field in ('applies', 'epoch', 'generation', 'revision'):
            value = copy.deepcopy(PROGRESS)
            if field == 'applies':
                value['applies'] += 1
            elif field == 'epoch':
                value['fence']['epoch'] = 'a' * 32
            elif field == 'generation':
                value['fence']['generation'] += 1
            else:
                value['fence']['revisions']['item:i_0123456789ab'] += 1
            with self.subTest(field=field), self.assertRaises(fence_plan.Stale):
                fence_plan.advance(value, proof, [], 'r_0123456789ac')

    def test_two_reservations_invalidate_the_first_snapshot_even_without_other_changes(self):
        first = fence_plan.advance(PROGRESS, fence_plan.snapshot(PROGRESS),
                                   ['item:i_0123456789ab'], 'r_0123456789ac')
        second = fence_plan.advance(first, fence_plan.snapshot(first),
                                    ['item:i_0123456789ab'], 'r_0123456789ac')
        self.assertEqual(second['fence']['generation'], 10)
        self.assertFalse(fence_plan.matches(second, fence_plan.snapshot(PROGRESS)))

    def test_invalid_control_types_and_namespaces_are_rejected(self):
        proof = fence_plan.snapshot(PROGRESS)
        for bad in (True, 8.0):
            invalid = copy.deepcopy(proof)
            invalid['fence']['generation'] = bad
            self.assertFalse(fence_plan.matches(PROGRESS, invalid))
        for target in ('item:s_0123456789ab', 'run:r_0123456789aI', 'raw:e_0123456789ab'):
            with self.subTest(target=target), self.assertRaises(ValueError):
                fence_plan.advance(PROGRESS, proof, [target], 'r_0123456789ac')

    def test_recovery_rotates_epoch_and_keeps_old_requests_invalid(self):
        with mock.patch.object(fence_plan.uuid, 'uuid4', return_value=mock.Mock(hex='a' * 32)):
            recovered = fence_plan.rotate(PROGRESS)
        self.assertEqual(recovered['fence'], {'epoch': 'a' * 32, 'generation': 0, 'revisions': {}})
        self.assertFalse(fence_plan.matches(recovered, fence_plan.snapshot(PROGRESS)))
        for epoch in (PROGRESS['fence']['epoch'], PROGRESS['fence']['epoch'].upper()):
            with self.subTest(epoch=epoch), \
                 mock.patch.object(fence_plan.uuid, 'uuid4', return_value=mock.Mock(hex=epoch)), \
                 self.assertRaises(ValueError):
                fence_plan.rotate(PROGRESS)
        with self.assertRaises(TypeError):
            fence_plan.rotate(recovered, PROGRESS['fence']['epoch'])

    def test_plans_do_no_file_io(self):
        with mock.patch('builtins.open', side_effect=AssertionError('unexpected I/O')), \
             mock.patch.object(Path, 'read_bytes', side_effect=AssertionError('unexpected I/O')), \
             mock.patch.object(Path, 'write_bytes', side_effect=AssertionError('unexpected I/O')):
            fence_plan.advance(PROGRESS, fence_plan.snapshot(PROGRESS), [], 'r_0123456789ac')
            fence_plan.rotate(PROGRESS)
