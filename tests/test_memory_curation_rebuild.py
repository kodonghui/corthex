"""TASK-034: a lost curation record made again from quotes and citations (unwired).

The TASK-034 part of TC-148 on a made-up format-2 store, under the leases the
worker (TASK-088) will hold. No hook, worker or model call is involved.
"""
import contextlib
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from _common import ROOT
SCRIPTS = ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'
sys.path.insert(0, str(SCRIPTS))
from memory_lib import base, clock, curation_rebuild, curation_triggers, format2, item_types, locks
from memory_lib import raw_log, state_types
from memory_lib.c2_store import C2Store
from test_memory_fence_plan import PROGRESS

DEVICE = 'd_0123456789ab'
AT = '2026-11-04T13:00:00.000Z'
WHEN = datetime(2026, 11, 7, 12, 30, tzinfo=timezone.utc)
SESSIONS = {name: 'fixture-session-034-' + name for name in 'ABCD'}
LOGS = {name: raw_log.log_name('codex', session) for name, session in SESSIONS.items()}
# Another process, as a recording hook would be, holds a raw lease for a moment.
HOLDER = '''import sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from memory_lib import clock, locks
lock = locks.Lock(Path(sys.argv[2]), "raw", sys.argv[3]).acquire(clock.now() + 5)
Path(sys.argv[4]).write_bytes(b"")
time.sleep(0.25)
lock.release()
'''


def ident(prefix):
    return prefix + '_' + ''.join(secrets.choice(base.CROCKFORD) for _ in range(12))


def entry(name, seq, kind, turn=None, minute=0):
    value = dict(id=ident('e'), seq=seq, at='2026-11-07T10:%02d:00.000Z' % minute, host='codex',
                 session=SESSIONS[name], kind=kind)
    if kind in ('prompt', 'answer'):
        value.update(turn=turn or seq, speaker='user' if kind == 'prompt' else 'agent', text='Turn %d words' % seq)
    return value


def item(source, name, status='current'):
    quote = dict(entry=source['id'], log=LOGS[name], device=DEVICE, start=0, end=4, speaker=source['speaker'],
                 said=source['at'], words=source['text'][:4])
    return dict(id=ident('i'), kind='decision', title='A decision', text='A decision.', quotes=[quote],
                status=status, saved=AT, device=DEVICE)


def line(cites, part='decisions', pos=1):
    return dict(id=ident('s'), part=part, pos=pos, text='A line', cites=list(cites), at=AT, device=DEVICE)


class RebuildTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name).resolve() / 'memory'
        (self.folder / 'logs').mkdir(parents=True)
        self.root = self.folder / 'projects' / 'sample'
        for name in ('raw', 'unprocessed', 'notices', 'layer/items', 'layer/tombstones'):
            (self.root / name).mkdir(parents=True)
        (self.folder / 'store.json').write_bytes(format2.store_bytes(
            {'format': 2, 'device': DEVICE, 'made': AT, 'release': '0.2.1'}))
        self.memory = C2Store(self.folder, expected_device=DEVICE)
        self.deadline = clock.now() + 30
        self.layer([], [])

    @contextlib.contextmanager
    def held(self, curator=True, layer=True):
        with contextlib.ExitStack() as stack:
            if curator:
                stack.enter_context(self.memory.lease(self.root / 'curation.lock', 'curation', self.deadline))
            if layer:
                stack.enter_context(self.memory.lease(self.root / 'layer.lock', 'layer', self.deadline))
            yield

    def record(self, name, entries, tail=b''):
        data = b''.join(item_types._raw(value) + b'\n' for value in entries) + tail
        (self.root / 'raw' / (LOGS[name] + '.jsonl')).write_bytes(data)

    def layer(self, items, lines, forgotten=()):
        for value in items:
            (self.root / 'layer/items' / (value['id'] + '.json')).write_bytes(item_types.item_bytes(value))
        for value in forgotten:
            tombstone = dict(item=value['id'], project='sample', at=AT, device=DEVICE,
                             quotes=[{k: value['quotes'][0][k] for k in ('device', 'entry', 'log', 'start', 'end')}])
            (self.root / 'layer/tombstones' / (value['id'] + '.json')).write_bytes(
                (json.dumps(tombstone) + '\n').encode('utf-8'))
        layer = self.root / 'layer'
        (layer / 'state.json').write_bytes(state_types.state_bytes({'lines': list(lines)}))
        (layer / 'state-removed.json').write_bytes(state_types.removed_bytes({'removed': []}))
        (layer / 'pins.json').write_bytes(item_types.pins_bytes({'pins': []}))
        (layer / 'conflicts.json').write_bytes(b'{"candidates": []}\n')
        (layer / 'item-list.txt').write_bytes(item_types.item_list_bytes(list(items)))

    def markers(self):
        return sorted(path.name for path in (self.root / 'unprocessed').iterdir())

    def mark(self, name, turn, minute):
        path = self.root / 'unprocessed' / ('20261107T10%02d00Z.%s.%d' % (minute, LOGS[name], turn))
        path.write_bytes(b'')
        return path.name

    def fixture(self):
        a = [entry('A', 1, 'start'), entry('A', 2, 'prompt', minute=2), entry('A', 3, 'answer', 2, 3),
             entry('A', 4, 'prompt', minute=4), entry('A', 5, 'answer', 4, 5), entry('A', 6, 'prompt', minute=6),
             entry('A', 7, 'answer', 6, 7), entry('A', 8, 'prompt', minute=8)]
        b = [entry('B', 1, 'prompt', minute=11), entry('B', 2, 'answer', 1, 12), entry('B', 3, 'end', minute=13)]
        c = [entry('C', 1, 'prompt', minute=21)]
        # A damaged complete line and an unfinished last line are not entries.
        self.record('A', a[:4] + a[4:], tail=b'')
        raw = self.root / 'raw' / (LOGS['A'] + '.jsonl')
        lines = raw.read_bytes().split(b'\n')
        lines.insert(3, b'{"seq": 99, "damaged": true}')
        raw.write_bytes(b'\n'.join(lines) + b'{"unfinished')
        self.record('B', b)
        self.record('C', c)
        kept = item(a[2], 'A')
        older = item(b[0], 'B', status='superseded')
        older['superseded_by'] = kept['id']
        gone = item(a[6], 'A')
        self.layer([kept, older, gone], [line([a[4]['id'], kept['id']]), line([kept['id']], 'progress', 2)],
                   forgotten=[gone])
        return a, b, c

    def test_tc148_a_lost_record_is_made_again_from_the_newest_quoted_or_cited_entry(self):
        a, b, c = self.fixture()
        stale = self.mark('A', 2, 2)
        kept = self.mark('A', 6, 6)
        moved = self.mark('B', 1, 11)
        foreign = ['notes.txt', '20261107T100100Z.%s.3' % LOGS['D']]
        for name in foreign:
            (self.root / 'unprocessed' / name).write_bytes(b'')
        (self.root / 'curation.json.bak').write_bytes(b'{"stopped": {"damaged')
        with self.held():
            value = curation_rebuild.rebuild(self.memory, self.root, self.deadline, now=WHEN)
        stored = format2.parse_curation((self.root / 'curation.json').read_bytes())
        self.assertEqual(stored, value)
        # A: an item quotes seq 3 and a line cites seq 5, while the forgotten item's seq 7 does
        # not count; B: the prompt is quoted, so its answer in the same turn stays unprocessed.
        self.assertEqual(value['logs'], {LOGS['A']: 5, LOGS['B']: 1})
        self.assertEqual((value['applies'], value['recent'], value['consolidation']), (0, [], {'failures': 0}))
        self.assertEqual(value['rebuilt'], '2026-11-07T12:30:00.000Z')
        self.assertNotIn('stopped', value)
        self.assertNotIn('failures', value)
        self.assertRegex(value['fence']['epoch'], r'\A[0-9a-f]{32}\Z')
        self.assertNotEqual(value['fence']['epoch'], '0' * 32)
        self.assertEqual((value['fence']['generation'], value['fence']['revisions']), (0, {}))
        self.assertFalse((self.root / 'curation.json.bak').exists())
        notice = item_types.parse_notice((self.root / 'notices' / 'rebuilt.json').read_bytes())
        self.assertEqual(notice, {'at': value['rebuilt'], 'kind': 'rebuilt'})
        expected = {kept, '20261107T100800Z.%s.8' % LOGS['A'], '20261107T101200Z.%s.1' % LOGS['B'],
                    '20261107T102100Z.%s.1' % LOGS['C']} | set(foreign)
        self.assertEqual(set(self.markers()), expected)
        self.assertNotIn(stale, expected)
        self.assertNotIn(moved, expected)
        # The triggers count what the record left unprocessed.
        self.assertEqual(curation_triggers.scan(self.memory, self.root).count, 5)
        self.assertEqual(json.loads((self.root / 'curation.json').read_bytes())['fence']['epoch'], value['fence']['epoch'])

    def test_a_record_or_backup_that_parses_is_never_made_again(self):
        self.fixture()
        before = self.markers()
        for primary, backup in ((format2.curation_bytes(PROGRESS), None),
                                (b'{damaged', format2.curation_bytes(PROGRESS))):
            with self.subTest(primary=primary[:9]):
                (self.root / 'curation.json').write_bytes(primary)
                if backup is not None:
                    (self.root / 'curation.json.bak').write_bytes(backup)
                with self.held(), self.assertRaises(ValueError):
                    curation_rebuild.rebuild(self.memory, self.root, self.deadline, now=WHEN)
                self.assertEqual((self.root / 'curation.json').read_bytes(), primary)
                self.assertFalse((self.root / 'notices' / 'rebuilt.json').exists())
                self.assertEqual(self.markers(), before)

    def test_only_the_holder_of_the_curation_and_layer_leases_makes_it_again(self):
        self.fixture()
        for curator, layer in ((False, False), (False, True), (True, False)):
            with self.subTest(curator=curator, layer=layer), self.held(curator, layer):
                with self.assertRaises(locks.LostLock):
                    curation_rebuild.rebuild(self.memory, self.root, self.deadline, now=WHEN)
        self.assertFalse((self.root / 'curation.json').exists())
        self.assertEqual(self.markers(), [])

    def test_markers_after_an_apply_name_each_unprocessed_turn_by_its_oldest_entry(self):
        a, _, _ = self.fixture()
        with self.held():
            self.assertEqual(curation_rebuild.replace_markers(self.memory, self.root, LOGS['A'], 7, self.deadline),
                             (1, 0))
            self.assertEqual(self.markers(), ['20261107T100800Z.%s.8' % LOGS['A']])
            # An answer appended while the curator ran keeps its turn's marker and name.
            raw = self.root / 'raw' / (LOGS['A'] + '.jsonl')
            data = raw.read_bytes()
            raw.write_bytes(data[:data.rfind(b'\n') + 1] + item_types._raw(entry('A', 9, 'answer', 8, 9)) + b'\n')
            self.assertEqual(curation_rebuild.replace_markers(self.memory, self.root, LOGS['A'], 7, self.deadline),
                             (0, 0))
            self.assertEqual(curation_rebuild.replace_markers(self.memory, self.root, LOGS['A'], 8, self.deadline),
                             (1, 1))
            self.assertEqual(self.markers(), ['20261107T100900Z.%s.8' % LOGS['A']])
            # A file named like a marker that is not empty, or with an impossible time, is not the plugin's.
            (self.root / 'unprocessed' / ('20261107T100200Z.%s.2' % LOGS['A'])).write_bytes(b'x')
            (self.root / 'unprocessed' / ('20261131T100300Z.%s.3' % LOGS['A'])).write_bytes(b'')
            self.assertEqual(curation_rebuild.replace_markers(self.memory, self.root, LOGS['A'], 9, self.deadline),
                             (0, 1))
            self.assertEqual(self.markers(), ['20261107T100200Z.%s.2' % LOGS['A'], '20261131T100300Z.%s.3' % LOGS['A']])

    def test_lines_appended_before_the_raw_lease_are_read_under_it(self):
        self.fixture()
        raw = self.root / 'raw' / (LOGS['C'] + '.jsonl')
        late = entry('C', 2, 'answer', 1, 22)
        real = self.memory.lease

        @contextlib.contextmanager
        def lease(path, kind, deadline, *args, **options):
            if kind == 'raw':
                with raw.open('ab') as target:
                    target.write(item_types._raw(late) + b'\n' + item_types._raw(entry('C', 3, 'prompt', minute=23)) + b'\n')
            with real(path, kind, deadline, *args, **options) as owner:
                yield owner
        with self.held(), mock.patch.object(self.memory, 'lease', lease):
            self.assertEqual(curation_rebuild.replace_markers(self.memory, self.root, LOGS['C'], 1, self.deadline),
                             (2, 0))
        self.assertEqual(self.markers(), ['20261107T102200Z.%s.1' % LOGS['C'], '20261107T102300Z.%s.3' % LOGS['C']])

    def test_a_hook_holding_the_raw_lease_is_waited_for_and_a_rewritten_log_is_refused(self):
        self.fixture()
        raw = self.root / 'raw' / (LOGS['B'] + '.jsonl')
        ready = self.folder.parent / 'holder-ready'
        holder = subprocess.Popen([sys.executable, '-c', HOLDER, str(SCRIPTS), str(raw.with_suffix('.lock')),
                                   DEVICE, str(ready)])
        self.addCleanup(holder.wait, 10)
        limit = time.monotonic() + 10
        while not ready.exists():
            self.assertIsNone(holder.poll())
            self.assertLess(time.monotonic(), limit)
            time.sleep(0.005)
        with self.held():
            started = time.perf_counter()
            self.assertEqual(curation_rebuild.replace_markers(self.memory, self.root, LOGS['B'], 1, self.deadline),
                             (1, 0))
            self.assertGreater(time.perf_counter() - started, 0.05)
            self.assertEqual(holder.wait(10), 0)
            real = self.memory.lease

            @contextlib.contextmanager
            def shrink(path, kind, deadline, *args, **options):
                raw.write_bytes(raw.read_bytes()[:10])
                with real(path, kind, deadline, *args, **options) as owner:
                    yield owner
            with mock.patch.object(self.memory, 'lease', shrink), self.assertRaises(locks.LostLock):
                curation_rebuild.replace_markers(self.memory, self.root, LOGS['B'], 0, self.deadline)


if __name__ == '__main__':
    unittest.main()
