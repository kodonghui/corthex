"""TASK-098: the confirmed forget's effects (API-025; SPEC-035, SPEC-029, SPEC-012) on fabricated format-2 stores.

TC-235, TC-236, TC-237, TC-343, TC-393 and, with TASK-082's vectors, TC-140. The runner does not hand `forget`
to the handler before the 0.3.0 activation, so these tests call it as the
runner will, after its gates, with the format-2 store binding and the code that
its preview gave; a forget that fails raises, and the runner reports the
error's built-in class as `internal` (`diagnostics.error_kind`). A curation in
TC-237 runs against the local test server of the curation worker's tests; no
provider is called.
"""
import json
import os
import sqlite3
import struct
import subprocess
import sys
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import (clock, diagnostics, files, forget_effects, format2, history_recovery, index_io, item_types,
                        raw_log, state_types)
from memory_lib.c2_store import C2Store
from test_memory_curator_answers import answer, change, quote
from test_memory_forget import AT, DEVICE, EPOCH, RUN, ForgetStore, candidate, ident, line

PRIVATE = 'Remember that the locker phrase is zebra orchid, and the hooks stay in one script.'
SECRET = 'the locker phrase is zebra orchid'
HOOKS = 'the hooks stay in one script'
WORDS = (b'zebra', b'orchid')


def record(number, cites, text='Earlier text.', why='', generation=1, line_number=None):
    """A TBL-119 record, as the line-history writers append it."""
    return state_types.history_record_bytes(dict(
        at=AT, run=RUN, epoch=EPOCH, generation=generation, line=ident('s', line_number or number),
        part='decisions', pos=1, op='changed', text=text, cites=list(cites), why=why, device=DEVICE))


class ForgetEffectsTest(ForgetStore, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.private, _ = self.fixture.raw.turn(PRIVATE, 'Noted, and the hooks stay together.')
        self.fixture.write()

    def forget(self, item, *extra, memory=None):
        """The preview, then the forget confirmed with its code."""
        preview = self.command(item, *extra, memory=memory)
        self.assertEqual((preview['outcome'], preview['code']), ('confirm', 'ok'))
        return preview, self.command(item, *extra, code=preview['confirm'], memory=memory)

    def store_bytes(self):
        """Every file of the memory store, as bytes."""
        return {path.relative_to(self.fixture.folder).as_posix(): path.read_bytes()
                for path in sorted(self.fixture.folder.rglob('*')) if path.is_file()}

    def holding(self, words=WORDS):
        return sorted(name for name, data in self.store_bytes().items() if any(word in data for word in words))

    def entry(self, entry_id, log=None):
        path = self.root / 'raw' / ((log or self.log) + '.jsonl')
        (value,) = [json.loads(row) for row in path.read_bytes().splitlines() if json.loads(row)['id'] == entry_id]
        return value

    def removed(self):
        return state_types.parse_removed((self.root / 'layer/state-removed.json').read_bytes())['removed']

    def private_store(self):
        """The item to forget, one that shares its entry and one elsewhere, with lines, pins, candidates and history."""
        gone = self.item(1, self.span(SECRET, self.private), kind='reference', title='Zebra orchid phrase',
                         source=self.private)
        stay = self.item(2, self.span(HOOKS, self.private), source=self.private)
        other = self.item(3, self.span('four hooks'), kind='fact')
        lines = [line(1, 'progress', 'The zebra orchid phrase stays private.', [gone['id']]),
                 line(2, 'progress', 'Talked about the locker.', [self.private['id']]),
                 line(3, 'decisions', 'The hooks stay in one script.', [stay['id']])]
        self.fixture.layer(items=[gone, stay, other], lines=lines, pinned=[gone['id'], stay['id']],
                           candidates=[candidate(1, gone['id'], stay['id']), candidate(2, stay['id'], other['id'])])
        self.fixture.index()
        records = [record(1, [gone['id']], text='Earlier zebra orchid line.'),
                   record(2, [stay['id']], why='Moved since zebra orchid came up.'),
                   record(3, [stay['id']]),
                   # A staged record, which no state publication used.
                   record(4, [self.private['id']], text='Staged zebra line.', generation=7)]
        self.history(*records, backup=records + [record(5, [gone['id']], text='Older zebra line.')])
        (self.root / 'state-history.jsonl.abcd1234.tmp').write_bytes(records[0])
        return gone, stay, other, lines, records

    # TC-235

    def test_tc235_a_confirmed_forget_removes_what_the_preview_named_and_leaves_a_tombstone(self):
        gone, stay, other, lines, records = self.private_store()
        before = format2.parse_curation((self.root / 'curation.json').read_bytes())['fence']
        self.assertIn('projects/sample/layer/items/%s.json' % gone['id'], self.holding())
        preview, done = self.forget(gone['id'])
        self.assertEqual((done['outcome'], done['code']), ('done', 'ok'))
        self.assertEqual(done['data'], dict(preview['data'], history_records=4))
        self.assertEqual(preview['data']['history_records'], 4)
        self.assertEqual(done['say'], (
            'Forgot %s, with its search index rows, 2 current state lines and 1 pin. '
            'The quoted words in 1 raw log entry on this device are filled. '
            '1 open conflict candidate is settled. '
            '4 line-history records were removed or cleared of their reason. '
            'Copies in the host transcript, at the model providers and on devices without sync stay.'
            % gone['id']))
        # No file of the store holds a word of the forgotten text: not the raw log, the items, the item list,
        # the search index, the state, the line history nor a copy of one.
        self.assertEqual(self.holding(), [])

        stone = (self.root / 'layer/tombstones' / (gone['id'] + '.json')).read_bytes()
        value = json.loads(stone)
        self.assertEqual(list(value), ['item', 'project', 'at', 'device', 'quotes'])
        self.assertEqual((value['item'], value['project'], value['device']), (gone['id'], 'sample', DEVICE))
        self.assertEqual(value['quotes'], [{'device': DEVICE, 'entry': self.private['id'], 'log': self.log,
                                            'start': gone['quotes'][0]['start'], 'end': gone['quotes'][0]['end']}])
        self.assertEqual(history_recovery._tombstone(stone, gone['id'], 'sample'),
                         {gone['id'], self.private['id']})

        self.assertEqual(sorted(self.fixture.items()), sorted([stay['id'], other['id']]))
        listed = (self.root / 'layer/item-list.txt').read_text(encoding='utf-8')
        self.assertNotIn(gone['id'], listed)
        self.assertIn(stay['id'], listed)
        connection = sqlite3.connect(str(self.root / 'index.db'))
        try:
            self.assertEqual(sorted(row[0] for row in connection.execute('SELECT item FROM index_items')),
                             sorted([stay['id'], other['id']]))
        finally:
            connection.close()
        pins = item_types.parse_pins((self.root / 'layer/pins.json').read_bytes())['pins']
        self.assertEqual([pin['item'] for pin in pins], [stay['id']])
        candidates = json.loads((self.root / 'layer/conflicts.json').read_bytes())['candidates']
        self.assertEqual([(value['id'], value['status']) for value in candidates],
                         [(ident('c', 1), 'settled'), (ident('c', 2), 'open')])

        self.assertEqual(self.fixture.lines(), [lines[2]])
        self.assertEqual([(marker['id'], marker['kind']) for marker in self.removed()],
                         [(lines[0]['id'], 'privacy'), (lines[1]['id'], 'privacy')])
        entry = self.entry(self.private['id'])
        start, end = self.span(SECRET, self.private)
        self.assertEqual(entry['forgotten'], [[start, end]])
        self.assertEqual(entry['text'], PRIVATE[:start] + '�' * (end - start) + PRIVATE[end:])
        self.assertEqual(entry['text'][stay['quotes'][0]['start']:stay['quotes'][0]['end']], HOOKS)

        cleared = json.loads(records[1])
        cleared['why'] = ''
        self.assertEqual((self.root / 'state-history.jsonl').read_bytes(),
                         state_types.history_record_bytes(cleared) + records[2])
        self.assertEqual(sorted(path.name for path in self.root.iterdir() if path.name.startswith('state-history')),
                         ['state-history.jsonl'])

        fence = format2.parse_curation((self.root / 'curation.json').read_bytes())['fence']
        generation = before['generation'] + 1
        self.assertEqual((fence['epoch'], fence['generation']), (before['epoch'], generation))
        self.assertEqual({key for key, value in fence['revisions'].items() if value == generation},
                         {'item:' + gone['id'], 'pin:' + gone['id'], 'line:' + lines[0]['id'],
                          'line:' + lines[1]['id'], 'candidate:' + ident('c', 1)})
        # The item is gone: a second forget names nothing.
        self.assertEqual(self.command(gone['id'])['code'], 'item-not-found')

    def test_the_forget_never_takes_or_waits_for_the_curation_lease(self):
        gone = self.item(1, self.span(SECRET, self.private), source=self.private)
        self.fixture.layer(items=[gone])
        code = ("import sys,time;sys.path.insert(0,sys.argv[1]);from pathlib import Path;"
                "from memory_lib import locks;lease=locks.Lock(Path(sys.argv[2]),'curation',sys.argv[3]);"
                "lease.acquire(time.monotonic()+5);print('ready',flush=True);"
                "sys.stdin.readline();lease.release()")
        child = subprocess.Popen([sys.executable, '-B', '-c', code,
                                  str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'),
                                  str(self.root / 'curation.lock'), DEVICE],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), 'ready')
            started = clock.now()
            _, done = self.forget(gone['id'])
            self.assertLess(clock.now() - started, 5)
        finally:
            child.communicate('\n', timeout=30)
        self.assertEqual((child.returncode, done['code']), (0, 'ok'))
        self.assertEqual(self.holding(), [])

    def test_a_raw_log_whose_file_is_missing_is_read_from_its_backup_then_restored_and_filled(self):
        gone = self.item(1, self.span(SECRET, self.private), source=self.private)
        stay = self.item(2, self.span(HOOKS, self.private), source=self.private)
        self.fixture.layer(items=[gone, stay])
        path = self.root / 'raw' / (self.log + '.jsonl')
        backup = path.with_name(path.name + '.bak')
        os.replace(str(path), str(backup))
        preview = self.command(gone['id'])
        self.assertEqual(preview['data']['raw'], [{'entry': self.private['id'], 'log': self.log,
                                                   'forgotten': [list(self.span(SECRET, self.private))],
                                                   'kept': []}])
        # The preview restores nothing.
        self.assertEqual((path.exists(), backup.exists()), (False, True))
        done = self.command(gone['id'], code=preview['confirm'])
        self.assertEqual((done['code'], done['data']['raw']), ('ok', preview['data']['raw']))
        self.assertFalse(backup.exists())
        entry = self.entry(self.private['id'])
        start, end = self.span(SECRET, self.private)
        self.assertEqual((entry['forgotten'], entry['text'][start:end]), ([[start, end]], '�' * (end - start)))
        self.assertEqual(self.holding(), [])

    def stale_copies(self, cited):
        """A forget while the state and the item list have the backup and temporary copies that stopped writes left."""
        gone = self.item(1, self.span(SECRET, self.private), kind='reference', title='Zebra orchid phrase',
                         source=self.private)
        stay = self.item(2, self.span(HOOKS, self.private), source=self.private)
        private = line(1, 'progress', 'The zebra orchid phrase stays private.', [gone['id']])
        kept = line(2, 'decisions', 'The hooks stay in one script.', [stay['id']])
        self.fixture.layer(items=[gone, stay], lines=[private, kept] if cited else [kept])
        layer = self.root / 'layer'
        state = state_types.state_bytes({'lines': [private, kept]})
        copies = {'state.json.bak': state, 'state.json.abcd1234.tmp': state, 'state.json.bak.efgh_678.tmp': state,
                  'item-list.txt.ijkl9012.tmp': (layer / 'item-list.txt').read_bytes()}
        for name, data in copies.items():
            (layer / name).write_bytes(data)
        self.assertEqual(self.holding(), sorted(
            ['projects/sample/layer/' + name for name in list(copies) + ['item-list.txt', 'items/%s.json' % gone['id']]]
            + ['projects/sample/layer/state.json'] * cited + ['projects/sample/raw/%s.jsonl' % self.log]))
        _, done = self.forget(gone['id'])
        self.assertEqual(done['code'], 'ok')
        self.assertFalse(any((layer / name).exists() for name in copies))
        self.assertEqual(self.fixture.lines(), [kept])
        self.assertEqual(self.holding(), [])

    def test_copies_of_the_state_and_the_item_list_that_a_stopped_write_left_go(self):
        self.stale_copies(cited=True)

    def test_copies_of_the_state_go_also_when_no_current_line_cites_the_item(self):
        # The copies alone hold the line that cited the item, which a curation removed before it stopped.
        self.stale_copies(cited=False)

    def copy_stays(self, name, source):
        """A forget whose removal of one leftover copy does nothing stops before it reports success."""
        gone = self.item(1, self.span(SECRET, self.private), source=self.private)
        self.fixture.layer(items=[gone])
        copy = self.root / name
        copy.write_bytes((self.root / source).read_bytes())
        preview = self.command(gone['id'])
        unlink = files._unlink

        def keep(path, check=None):
            if path != copy:
                unlink(path, check)
        with mock.patch.object(files, '_unlink', keep):
            with self.assertRaises(forget_effects.Unverified):
                self.command(gone['id'], code=preview['confirm'])
        self.assertTrue(copy.exists())
        self.assertTrue((self.root / 'layer/tombstones' / (gone['id'] + '.json')).exists())

    def test_a_copy_of_the_state_that_stays_stops_the_forget(self):
        self.copy_stays('layer/state.json.abcd1234.tmp', 'layer/state.json')

    def test_a_copy_of_a_raw_log_that_stays_stops_the_forget(self):
        self.copy_stays('raw/%s.jsonl.abcd1234.tmp' % self.log, 'raw/%s.jsonl' % self.log)

    # TC-236

    def test_tc236_a_sentence_that_a_staying_item_quotes_stays_until_that_item_goes_too(self):
        first = self.item(1, self.span(SECRET, self.private), source=self.private)
        second = self.item(2, self.span('locker phrase', self.private), kind='fact', source=self.private)
        self.fixture.layer(items=[first, second])
        preview, done = self.forget(first['id'])
        self.assertEqual(done['code'], 'ok')
        self.assertEqual(done['data']['raw'], [{'entry': self.private['id'], 'log': self.log, 'forgotten': [],
                                                'kept': [list(self.span(SECRET, self.private))]}])
        entry = self.entry(self.private['id'])
        self.assertEqual((entry['text'], 'forgotten' in entry), (PRIVATE, False))
        (kept,) = self.fixture.items().values()
        place = kept['quotes'][0]
        self.assertEqual(entry['text'][place['start']:place['end']], place['words'])
        self.assertIn('Words that %s also quotes stay whole.' % second['id'], done['say'])
        # Forgetting the other item fills both ranges, the first one from its tombstone.
        preview, done = self.forget(second['id'])
        self.assertEqual(done['code'], 'ok')
        entry = self.entry(self.private['id'])
        start, end = self.span(SECRET, self.private)
        self.assertEqual(entry['forgotten'], sorted([[start, end], list(self.span('locker phrase', self.private))]))
        self.assertEqual(entry['text'][start:end], '�' * (end - start))
        self.assertEqual(self.holding(), [])

    def test_items_named_with_with_go_together_and_their_shared_ranges_are_filled(self):
        first = self.item(1, self.span(SECRET, self.private), source=self.private)
        second = self.item(2, self.span('locker phrase', self.private), kind='fact', source=self.private)
        third = self.item(3, self.span('four hooks'), kind='fact')
        self.fixture.layer(items=[first, second, third], pinned=[second['id']])
        preview, done = self.forget(first['id'], second['id'])
        self.assertEqual((done['code'], done['data']['with'], done['data']['also']), ('ok', [second['id']], []))
        self.assertTrue(done['say'].startswith('Forgot %s and 1 other item, with their search index rows and 1 pin.'
                                               % first['id']))
        self.assertEqual(sorted(path.name for path in (self.root / 'layer/tombstones').iterdir()),
                         [first['id'] + '.json', second['id'] + '.json'])
        self.assertEqual(list(self.fixture.items()), [third['id']])
        entry = self.entry(self.private['id'])
        self.assertEqual(entry['forgotten'], sorted([list(self.span(SECRET, self.private)),
                                                     list(self.span('locker phrase', self.private))]))
        self.assertEqual(self.holding(), [])

    def test_lines_and_records_that_an_earlier_tombstone_names_go_with_a_later_forget(self):
        earlier = self.item(1, self.span('four hooks'), kind='fact')
        gone = self.item(2, self.span(SECRET, self.private), source=self.private)
        restored = dict(line(2, 'progress', 'A line that an undo restored.', [gone['id']]))
        hidden = line(1, 'progress', 'Hidden since its item was forgotten.', [earlier['id']])
        self.fixture.layer(items=[gone], lines=[hidden, restored])
        (self.root / 'layer/state-removed.json').write_bytes(state_types.removed_bytes({'removed': [
            {'id': restored['id'], 'at': AT, 'device': DEVICE, 'kind': 'edit', 'restored_by': RUN,
             'restored_at': AT}]}))
        self.tombstone(earlier)
        self.history(record(1, [earlier['id']]), record(2, [self.said['id']]), record(3, [ident('i', 9)]))
        preview, done = self.forget(gone['id'])
        self.assertEqual(preview['data']['state_lines'], [{'line': restored['id'], 'part': 'progress',
                                                           'text': restored['text']}])
        self.assertEqual((done['code'], done['data']['history_records']), ('ok', 2))
        self.assertEqual(self.fixture.lines(), [])
        self.assertEqual(self.removed(), [
            {'id': restored['id'], 'at': self.removed()[0]['at'], 'device': DEVICE, 'kind': 'privacy'},
            {'id': hidden['id'], 'at': self.removed()[0]['at'], 'device': DEVICE, 'kind': 'privacy'}])
        self.assertEqual((self.root / 'state-history.jsonl').read_bytes(), record(3, [ident('i', 9)]))

    # TC-237

    def test_tc237_a_forget_while_a_curate_request_waits_leaves_no_trace_of_the_text(self):
        gone = self.item(1, self.span(SECRET, self.private), kind='reference', source=self.private)
        self.fixture.layer(items=[gone])
        other = C2Store(self.fixture.folder, expected_device=DEVICE)
        results = []

        def forget():
            preview = self.command(gone['id'], memory=other)
            results.append(self.command(gone['id'], code=preview['confirm'], memory=other))
        self.fixture.server.before[0] = forget
        self.fixture.server.answers = [
            answer(change(quote(self.private, SECRET), kind='reference', title='The zebra phrase')),
            answer(change(quote(self.private, HOOKS), kind='decision', title='Hooks together'))]
        outcome = self.fixture.curate()
        self.assertEqual([result['code'] for result in results], ['ok'])
        self.assertEqual([attempt.record['result'] for attempt in outcome.attempts], ['stale', 'ok'])
        self.assertIn('zebra orchid', self.fixture.server.content(0))
        self.assertNotIn('zebra', self.fixture.server.content(1))
        self.assertIn('[forgotten]', self.fixture.server.content(1))
        (value,) = self.fixture.items().values()
        self.assertEqual((value['title'], value['quotes'][0]['words']), ('Hooks together', HOOKS))
        self.assertEqual(self.holding(), [])

    # TC-343

    def test_tc343_history_records_and_staged_records_that_cite_the_item_go_and_nothing_is_archived(self):
        gone = self.item(1, self.span(SECRET, self.private), source=self.private)
        current = line(1, 'decisions', 'The zebra orchid phrase is current.', [gone['id']])
        self.fixture.layer(items=[gone], lines=[current])
        older = record(1, [gone['id']], text='The zebra orchid phrase, before.')
        staged = record(1, [gone['id']], text='A staged zebra text.', generation=9)
        self.history(older, staged, record(2, [self.said['id']], why='Kept.'))
        preview, done = self.forget(gone['id'])
        self.assertEqual((done['code'], done['data']['history_records']), ('ok', 3))
        self.assertEqual((self.root / 'state-history.jsonl').read_bytes(), record(2, [self.said['id']]))
        self.assertEqual(self.fixture.lines(), [])
        self.assertEqual([(marker['id'], marker['kind']) for marker in self.removed()],
                         [(current['id'], 'privacy')])
        self.assertEqual(self.holding(), [])

    # TC-393

    def test_tc393_a_damaged_history_fails_the_forget_after_its_other_effects_and_its_backup_is_scrubbed(self):
        kept = self.item(1, self.span(HOOKS, self.private), source=self.private)
        gone = self.item(2, self.span(SECRET, self.private), kind='reference', source=self.private)
        self.fixture.layer(items=[kept, gone])
        # B's words only in the reason of a record whose citations name A.
        about_a = record(1, [kept['id']], text='A, as it was.', why='Changed after the zebra orchid talk.')
        about_b = record(2, [gone['id']], text='The zebra orchid line.')
        (self.root / 'state-history.jsonl').write_bytes(about_a + b'{"damaged":')
        (self.root / 'state-history.jsonl.bak').write_bytes(about_a + about_b)
        preview = self.command(gone['id'])
        self.assertNotIn('history_records', preview['data'])
        with self.assertRaises(forget_effects.HistoryUnverified) as failed:
            self.command(gone['id'], code=preview['confirm'])
        self.assertEqual(diagnostics.error_kind(failed.exception), 'RuntimeError')
        # Everything else went, and the backup holds A's record with its reason cleared.
        self.assertTrue((self.root / 'layer/tombstones' / (gone['id'] + '.json')).exists())
        self.assertEqual(list(self.fixture.items()), [kept['id']])
        cleared = json.loads(about_a)
        cleared['why'] = ''
        self.assertEqual((self.root / 'state-history.jsonl.bak').read_bytes(),
                         state_types.history_record_bytes(cleared))
        self.assertEqual(self.holding(), ['projects/sample/state-history.jsonl'])
        # The repair that restores the backup brings neither B's record nor its words back.
        deadline = clock.now() + 30
        with self.memory.lease(self.root / 'curation.lock', 'curation', deadline):
            with self.memory.lease(self.root / 'layer.lock', 'layer', deadline):
                outcome = history_recovery.recover(self.memory, self.root, deadline,
                                                   maintenance_precondition=lambda *values: None)
        self.assertTrue(outcome['published'])
        self.assertEqual((self.root / 'state-history.jsonl').read_bytes(), state_types.history_record_bytes(cleared))
        self.assertEqual(self.holding(), [])

    def test_a_healthy_history_with_a_reason_about_b_loses_the_reason_and_keeps_a(self):
        kept = self.item(1, self.span(HOOKS, self.private), source=self.private)
        gone = self.item(2, self.span(SECRET, self.private), source=self.private)
        self.fixture.layer(items=[kept, gone])
        about_a = record(1, [kept['id']], text='A, as it was.', why='Changed after the zebra orchid talk.')
        self.history(about_a, backup=[about_a])
        _, done = self.forget(gone['id'])
        self.assertEqual((done['code'], done['data']['history_records']), ('ok', 1))
        value = json.loads((self.root / 'state-history.jsonl').read_bytes())
        self.assertEqual((value['text'], value['cites'], value['why']), ('A, as it was.', [kept['id']], ''))
        self.assertFalse((self.root / 'state-history.jsonl.bak').exists())

    def test_a_copy_of_the_history_with_an_unknown_name_fails_the_forget_after_the_scrub(self):
        gone = self.item(1, self.span(SECRET, self.private), source=self.private)
        self.fixture.layer(items=[gone])
        self.history(record(1, [gone['id']], text='The zebra line.'))
        (self.root / 'state-history.jsonl.old').write_bytes(b'unknown\n')
        preview = self.command(gone['id'])
        with self.assertRaises(forget_effects.HistoryUnverified):
            self.command(gone['id'], code=preview['confirm'])
        self.assertEqual((self.root / 'state-history.jsonl').read_bytes(), b'')
        self.assertEqual(self.holding(), [])

    # The search index

    def test_tc140_no_row_of_a_forgotten_or_deleted_item_is_left_in_the_four_tables(self):
        gone, stay, other, _, _ = self.private_store()
        # Each item has its vector, as step 6 of the memory worker writes it (TASK-082).
        vector = struct.pack('<512f', *([1.0] + [0.0] * 511))
        connection = index_io.connect(self.root / 'index.db')
        try:
            self.assertEqual(index_io.put_vectors(connection, [(item['id'], vector) for item in (gone, stay, other)]),
                             [gone['id'], stay['id'], other['id']])
        finally:
            connection.close()
        self.forget(gone['id'])
        connection = index_io.connect(self.root / 'index.db')
        try:
            index_io.delete(connection, [other['id']])
            tables = {table: connection.execute('SELECT * FROM ' + table).fetchall()
                      for table in ('index_meta', 'index_items', 'index_vectors', 'index_terms')}
        finally:
            connection.close()
        self.assertEqual({table: sum(gone['id'] in row or other['id'] in row for row in rows)
                          for table, rows in tables.items()}, dict.fromkeys(tables, 0))
        self.assertEqual([row[0] for row in tables['index_items']], [stay['id']])
        self.assertEqual(tables['index_vectors'], [(stay['id'], vector)])
        self.assertEqual(self.holding(), [])

    def test_an_index_that_cannot_be_read_goes_and_its_rows_with_it(self):
        gone = self.item(1, self.span(SECRET, self.private), source=self.private)
        self.fixture.layer(items=[gone])
        (self.root / 'index.db').write_bytes(b'not a database, zebra orchid\n' * 10)
        _, done = self.forget(gone['id'])
        self.assertEqual(done['code'], 'ok')
        self.assertFalse(any(path.name.startswith('index.db') for path in self.root.iterdir()))
        self.assertEqual(self.holding(), [])

    def test_an_index_whose_log_a_reader_keeps_goes_where_the_system_lets_it(self):
        gone = self.item(1, self.span(SECRET, self.private), source=self.private)
        stay = self.item(2, self.span(HOOKS, self.private), source=self.private)
        self.fixture.layer(items=[gone, stay])
        self.fixture.index()
        reader = sqlite3.connect(str(self.root / 'index.db'), isolation_level=None)
        self.addCleanup(reader.close)
        reader.execute('BEGIN')
        self.assertEqual(reader.execute('SELECT count(*) FROM index_items').fetchone()[0], 2)
        with mock.patch.object(forget_effects, 'CHECKPOINT_SECONDS', 0.1):
            preview = self.command(gone['id'])
            if os.name == 'nt':
                # Windows keeps a file that a reader holds open, so the forget fails after its tombstone.
                with self.assertRaises(PermissionError):
                    self.command(gone['id'], code=preview['confirm'])
                self.assertTrue((self.root / 'layer/tombstones' / (gone['id'] + '.json')).exists())
                return
            done = self.command(gone['id'], code=preview['confirm'])
        self.assertEqual(done['code'], 'ok')
        self.assertFalse(any(path.name.startswith('index.db') for path in self.root.iterdir()))
        self.assertEqual(self.holding(), [])


class TombstoneTest(unittest.TestCase):
    def test_a_tombstone_holds_the_places_of_the_quotes_and_none_of_their_words(self):
        quote = dict(entry=ident('e', 1), log=raw_log.log_name('claude-code', 'x'), device=DEVICE, start=4.0, end=9,
                     speaker='user', said=AT, words='zebra')
        value = dict(id=ident('i', 1), quotes=[quote])
        data = forget_effects.tombstone(value, 'sample', AT, DEVICE)
        self.assertNotIn(b'zebra', data)
        self.assertEqual(json.loads(data), {'item': ident('i', 1), 'project': 'sample', 'at': AT, 'device': DEVICE,
                                            'quotes': [{'device': DEVICE, 'entry': ident('e', 1),
                                                        'log': quote['log'], 'start': 4.0, 'end': 9}]})
        with self.assertRaises(ValueError):
            forget_effects.tombstone(dict(value, quotes=[]), 'sample', AT, DEVICE)


if __name__ == '__main__':
    unittest.main()
