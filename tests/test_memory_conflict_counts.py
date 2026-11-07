"""TASK-092 conflict showing counts on fabricated format-2 stores (SPEC-143, TBL-010).

No hook or command uses them before the 0.3.0 activation; the starts here are
the reservation a start hook will make once a notice line fits.
"""
import contextlib
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
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import clock, conflict_counts, conflict_types, format2, item_types, locks
from memory_lib.c2_store import C2Store
from test_memory_fence_plan import PROGRESS
from test_memory_item_types import AT, DEVICE

SCRIPTS = ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'
OLDER, NEWER, OTHER = 'c_0123456789ab', 'c_0123456789ac', 'c_0123456789ad'
LATER = '2026-11-04T04:00:00.000Z'


def candidate(identifier, at=AT, status='open', items=('i_0123456789ab', 'i_0123456789ac')):
    value = {'id': identifier, 'items': list(items), 'at': at, 'run': 'r_0123456789ab', 'by': 'curate',
             'status': status}
    if status != 'open':
        value['closed'] = LATER
    return value


class ConflictCountsTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / 'memory'
        (self.root / 'logs').mkdir(parents=True)
        self.project = self.root / 'projects/sample'
        for name in ('layer/items', 'layer/tombstones', 'notices'):
            (self.project / name).mkdir(parents=True, exist_ok=True)
        header = {'format': 2, 'device': DEVICE, 'made': AT, 'release': '0.3.0'}
        (self.root / 'store.json').write_bytes(format2.store_bytes(header))
        (self.project / 'curation.json').write_bytes(format2.curation_bytes(PROGRESS))
        self.memory = C2Store(self.root, expected_device=DEVICE)
        self.deadline = clock.now() + 30
        self.counts = self.project / 'notices' / conflict_counts.NAME
        self.conflicts = {'candidates': []}

    def publish(self, *candidates):
        """What a layer writer publishes in TBL-120 once the counts are initialized."""
        self.conflicts = {'candidates': list(candidates)}
        (self.project / 'layer/conflicts.json').write_bytes(item_types._raw(self.conflicts))

    @contextlib.contextmanager
    def layer(self):
        with self.memory.lease(self.project / 'layer.lock', 'layer', self.deadline):
            yield

    def initialize(self, *ids, conflicts=None):
        with self.layer():
            conflict_counts.initialize(self.memory, self.project, ids,
                                       self.conflicts if conflicts is None else conflicts, self.deadline)

    def read(self):
        return conflict_counts.read(self.memory, self.project, self.deadline)

    def reserve(self, identifier=OLDER, deadline=None):
        return conflict_counts.reserve(self.memory, self.project, identifier,
                                       self.deadline if deadline is None else deadline)

    def start(self):
        """One session start whose line fits: the oldest eligible candidate, reserved."""
        eligible = conflict_counts.eligible(self.conflicts, self.read())
        if not eligible:
            return None
        return eligible[0]['id'], self.reserve(eligible[0]['id'])

    def notices(self):
        return sorted(path.name for path in (self.project / 'notices').iterdir())

    def holder(self):
        """Hold the notice-counter lease in another process, as a concurrent start would."""
        code = ("import sys;sys.path.insert(0,sys.argv[1]);from pathlib import Path;import time;"
                "from memory_lib import locks;lease=locks.Lock(Path(sys.argv[2]),'notice',sys.argv[3]);"
                "lease.acquire(time.monotonic()+5);print('ready',flush=True);sys.stdin.readline();lease.release()")
        child = subprocess.Popen([sys.executable, '-B', '-c', code, str(SCRIPTS),
                                  str(self.project / 'notices' / conflict_counts.LOCK), DEVICE],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True)

        def stop():
            if child.poll() is None:
                child.stdin.write('release\n')
                child.stdin.flush()
                child.wait(timeout=10)
            child.stdin.close()
            child.stdout.close()
        self.addCleanup(stop)
        self.assertEqual(child.stdout.readline().strip(), 'ready')
        return stop

    def test_counts_are_strict_sorted_and_have_no_backup(self):
        value = {'counts': {NEWER: 3, OLDER: 0}}
        data = conflict_counts.counts_bytes(value['counts'])
        self.assertEqual(json.loads(data), {'counts': {OLDER: 0, NEWER: 3}})
        self.assertEqual(conflict_counts.parse_counts(data), {'counts': {OLDER: 0, NEWER: 3}})
        for bad in ({'counts': {OLDER: 4}}, {'counts': {OLDER: -1}}, {'counts': {OLDER: True}},
                    {'counts': {OLDER: '1'}}, {'counts': {OLDER: 1.5}}, {'counts': {'i_0123456789ab': 1}},
                    {'counts': []}, {'counts': {}, 'extra': 1}, {}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                conflict_counts.parse_counts(json.dumps(bad).encode())
        # Like the other records, an integral number reads as an integer.
        self.counts.write_bytes(b'{"counts": {"%s": 1.0}}' % OLDER.encode())
        self.assertEqual(self.read(), {OLDER: 1})
        self.counts.unlink()
        self.publish(candidate(OLDER))
        self.initialize(NEWER)
        self.assertEqual(self.reserve(NEWER), 1)
        self.assertEqual(self.notices(), [conflict_counts.NAME])
        self.assertEqual(self.counts.read_bytes(), conflict_counts.counts_bytes({NEWER: 1}))

    def test_notice_counter_lease_sits_between_layer_and_raw(self):
        self.assertEqual(locks.POLICIES['notice'], locks.Policy(4, None, 10))
        kinds = list(locks.POLICIES)
        self.assertEqual(kinds[kinds.index('layer'):kinds.index('raw') + 1], ['layer', 'notice', 'raw'])
        self.assertEqual([policy.rank for policy in locks.POLICIES.values()], list(range(len(kinds))))
        lock = self.project / 'notices' / conflict_counts.LOCK
        with self.layer(), self.memory.lease(lock, 'notice', self.deadline):
            with self.memory.lease(self.project / 'raw.lock', 'raw', self.deadline):
                pass
        with self.memory.lease(lock, 'notice', self.deadline), self.assertRaises(locks.LockOrderError):
            self.memory.lease(self.project / 'layer.lock', 'layer', self.deadline).__enter__()
        self.assertEqual(self.notices(), [])

    def test_tc350_part_three_starts_show_the_candidate_and_the_fourth_does_not(self):
        self.initialize(OLDER)
        self.assertEqual(self.read(), {OLDER: 0})
        self.publish(candidate(OLDER))
        notice = self.project / 'notices' / ('conflict-' + OLDER + '.json')
        notice.write_bytes(item_types.notice_bytes({'at': AT, 'kind': 'conflict', 'candidate': OLDER, 'shown': 0}))
        self.assertEqual([self.start() for _ in range(3)], [(OLDER, 1), (OLDER, 2), (OLDER, 3)])
        self.assertFalse(notice.exists())
        self.assertIsNone(self.start())
        self.assertIsNone(self.reserve(OLDER))
        self.assertEqual(self.read(), {OLDER: 3})
        self.assertEqual([c['id'] for c in conflict_types.open_candidates(self.conflicts)], [OLDER])
        self.assertEqual(conflict_counts.lost(self.conflicts, self.read()), [])

    def test_the_oldest_eligible_candidate_comes_first(self):
        self.initialize(OLDER, NEWER)
        self.publish(candidate(NEWER, at=LATER, items=('i_0123456789ad', 'i_0123456789ae')), candidate(OLDER))
        self.assertEqual([c['id'] for c in conflict_counts.eligible(self.conflicts, self.read())], [OLDER, NEWER])
        self.assertEqual([self.start() for _ in range(4)], [(OLDER, 1), (OLDER, 2), (OLDER, 3), (NEWER, 1)])
        self.publish(candidate(NEWER, at=LATER, items=('i_0123456789ad', 'i_0123456789ae')),
                     candidate(OLDER, status='settled'))
        self.assertEqual([c['id'] for c in conflict_counts.eligible(self.conflicts, self.read())], [NEWER])

    def test_initialize_needs_the_layer_lease_new_ids_and_never_lowers_a_count(self):
        with self.assertRaises(locks.LostLock):
            conflict_counts.initialize(self.memory, self.project, [OLDER], self.conflicts, self.deadline)
        self.assertFalse(self.counts.exists())
        self.publish(candidate(OLDER))
        for ids in ((), (OLDER,), (NEWER, NEWER), ('c_short',)):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                self.initialize(*ids)
        self.assertFalse(self.counts.exists())
        # A count left by a publication that stopped before TBL-120 stays as it is.
        self.counts.write_bytes(conflict_counts.counts_bytes({NEWER: 2}))
        self.initialize(NEWER, OTHER)
        self.assertEqual(self.read(), {NEWER: 2, OTHER: 0})
        stop = self.holder()
        deadline = clock.now() + 0.3
        with self.memory.lease(self.project / 'layer.lock', 'layer', deadline), self.assertRaises(locks.LockBusy):
            conflict_counts.initialize(self.memory, self.project, ['c_0123456789ae'], self.conflicts, deadline)
        stop()
        self.assertEqual(self.read(), {NEWER: 2, OTHER: 0})

    def test_tc389_lost_damaged_or_restored_counts_never_show_a_candidate_again(self):
        self.initialize(OLDER, NEWER)
        self.publish(candidate(OLDER), candidate(NEWER, at=LATER, items=('i_0123456789ad', 'i_0123456789ae')))
        self.assertEqual([self.reserve(OLDER) for _ in range(3)], [1, 2, 3])
        self.assertEqual(self.reserve(NEWER), 1)
        exhausted = self.counts.read_bytes()
        older = conflict_counts.counts_bytes({OLDER: 0, NEWER: 0})
        cases = {'deleted': None, 'damaged': b'{"counts": {', 'other shape': b'{"counts": []}\n'}
        for name, data in cases.items():
            with self.subTest(name=name):
                if self.counts.exists():
                    self.counts.unlink()
                if data is not None:
                    self.counts.write_bytes(data)
                # An older copy beside it is never restored.
                backup = self.counts.with_name(self.counts.name + '.bak')
                backup.write_bytes(older)
                self.assertIsNone(self.read())
                self.assertEqual(conflict_counts.eligible(self.conflicts, self.read()), [])
                self.assertEqual(conflict_counts.lost(self.conflicts, self.read()), [OLDER, NEWER])
                self.assertIsNone(self.reserve(NEWER))
                self.assertEqual(backup.read_bytes(), older)
                self.assertEqual(self.read(), None)
                backup.unlink()
                self.assertEqual([c['id'] for c in conflict_types.open_candidates(self.conflicts)],
                                 [OLDER, NEWER])
        # A new candidate gets a fresh file; the others stay used up without counts.
        self.initialize(OTHER)
        self.assertEqual(self.read(), {OTHER: 0})
        self.publish(*self.conflicts['candidates'], candidate(OTHER, at=LATER, items=('i_0123456789af', 'i_0123456789ag')))
        self.assertEqual([c['id'] for c in conflict_counts.eligible(self.conflicts, self.read())], [OTHER])
        self.assertEqual(conflict_counts.lost(self.conflicts, self.read()), [OLDER, NEWER])
        # Closing and reopening (as an undo would) or removing a notice keeps the high-water.
        self.counts.write_bytes(exhausted)
        self.publish(candidate(OLDER, status='settled'), candidate(NEWER, at=LATER, items=('i_0123456789ad', 'i_0123456789ae')))
        self.assertEqual(self.read(), {OLDER: 3, NEWER: 1})
        self.publish(candidate(OLDER), candidate(NEWER, at=LATER, items=('i_0123456789ad', 'i_0123456789ae')))
        self.assertEqual([c['id'] for c in conflict_counts.eligible(self.conflicts, self.read())], [NEWER])
        with self.assertRaises(ValueError):
            self.initialize(OLDER)
        self.assertEqual(self.read(), {OLDER: 3, NEWER: 1})

    def test_tc388_failed_reservations_count_nothing_and_concurrent_starts_stop_at_three(self):
        self.initialize(OLDER)
        self.publish(candidate(OLDER))
        self.assertEqual([self.reserve(), self.reserve()], [1, 2])
        before = self.counts.read_bytes()
        # A busy lease until the deadline, a passed deadline and a failed move count nothing.
        stop = self.holder()
        started = time.monotonic()
        self.assertIsNone(self.reserve(deadline=clock.now() + 0.3))
        self.assertLess(time.monotonic() - started, 5)
        stop()
        self.assertIsNone(self.reserve(deadline=clock.now() - 1))
        real = os.replace

        def failing(source, target):
            if Path(target) == self.counts:
                raise OSError('fixture write failure')
            return real(source, target)
        with mock.patch.object(conflict_counts.os, 'replace', side_effect=failing):
            self.assertIsNone(self.reserve())
        self.assertEqual(self.counts.read_bytes(), before)
        self.assertEqual(self.notices(), [conflict_counts.NAME])
        # Concurrent starts around count 2: exactly one reserves the third showing.
        code = ("import sys;sys.path.insert(0,sys.argv[1]);sys.path.insert(0,sys.argv[2]);from pathlib import Path;"
                "from memory_lib import clock, conflict_counts;from memory_lib.c2_store import C2Store;"
                "memory=C2Store(Path(sys.argv[3]),expected_device=sys.argv[4]);print('ready',flush=True);"
                "sys.stdin.readline();"
                "print(conflict_counts.reserve(memory,Path(sys.argv[5]),sys.argv[6],clock.now()+20),flush=True)")
        children = [subprocess.Popen([sys.executable, '-B', '-c', code, str(SCRIPTS), str(ROOT / 'tests'),
                                      str(self.root), DEVICE, str(self.project), OLDER],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True)
                    for _ in range(6)]
        try:
            for child in children:
                self.assertEqual(child.stdout.readline().strip(), 'ready')
            for child in children:
                child.stdin.write('go\n')
                child.stdin.flush()
            answers = sorted(child.stdout.readline().strip() for child in children)
        finally:
            for child in children:
                child.stdin.close()
                child.wait(timeout=30)
                child.stdout.close()
        self.assertEqual(answers, ['3'] + ['None'] * 5)
        self.assertEqual(self.read(), {OLDER: 3})
        self.assertEqual(self.notices(), [conflict_counts.NAME])

    def test_a_stop_after_the_reservation_may_use_up_that_showing(self):
        self.initialize(OLDER)
        self.publish(candidate(OLDER))
        with mock.patch.object(conflict_counts, '_sync_folder', side_effect=OSError('fixture stop')):
            self.assertIsNone(self.reserve())
        self.assertEqual(self.read(), {OLDER: 1})
        self.assertEqual([self.reserve(), self.reserve(), self.reserve()], [2, 3, None])


if __name__ == '__main__':
    unittest.main()
