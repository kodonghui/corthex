"""TASK-093: recall's ranking, exclusions and block, and the injection log line it fills.

TC-206, TC-208, TC-210, TC-214, TC-216, TC-218, TC-219 and TC-366, and the
recall parts of TC-136, TC-205 and TC-215, on made-up format-2 stores and
vectors. Nothing calls the module before the 0.3.0 activation: the prompt
hook's embedding, gates, output and injection log line remain for TASK-094,
so these are direct module results.
"""
from datetime import timezone
import json
import math
import os
import secrets
import shutil
import sqlite3
import struct
import sys
import time
import unicodedata
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import (clock, fence_plan, index_io, injection_log, item_types, raw_log, recall, request_budget,
                        revision_io, start_memory, start_summary)
import test_memory_curation_worker as worker_fixture

AT, STAMP, DEVICE = worker_fixture.AT, worker_fixture.STAMP, worker_fixture.DEVICE
DAY = AT[:10]  # the fixture's quotes are from this day
MODEL, DIMS, SESSION, HOST = 'text-embedding-3-small', 64, 'fixture-recall-093', 'claude-code'
PROMPT = (1.0,) + (0.0,) * (DIMS - 1)
UTC = timezone.utc
ident = worker_fixture.ident


def toward(cosine, side=1):
    """A vector of length 1 whose cosine with PROMPT is `cosine`; `side` picks where the rest of its length goes."""
    values = [cosine] + [0.0] * (DIMS - 1)
    values[side] = math.sqrt(max(0.0, 1 - cosine * cosine))
    return values


def packed(values):
    length = math.sqrt(math.fsum(value * value for value in values))
    return struct.pack('<%df' % len(values), *(value / length for value in values))


class RecallTest(unittest.TestCase):
    """Recall on the curation worker's store fixture, whose own tests stay in their module."""
    Fixture = worker_fixture.CurationWorkerTest
    configure, layer, saved, one_turn, items, write = (Fixture.configure, Fixture.layer, Fixture.saved,
                                                       Fixture.one_turn, Fixture.items, Fixture.write)

    def setUp(self):
        self.Fixture.setUp(self)
        self.configure(models={'dims': DIMS}, recall={'threshold': 0.4})
        self.said, _ = self.one_turn()

    # The store

    def item(self, title, kind='fact', status='current', text=None):
        value = self.saved(self.said, worker_fixture.HOOKS, kind=kind)
        value.update(title=title, text=title + ' holds.' if text is None else text, status=status)
        return value

    def index(self, model=MODEL, dims=DIMS):
        deadline = clock.now() + 60
        with self.memory.lease(self.root / 'layer.lock', 'layer', deadline):
            proof = fence_plan.snapshot(revision_io.read(self.memory, self.root, deadline))
            index_io.ensure(self.memory, self.root, proof, deadline, model=model, dims=dims, when=STAMP)

    def vectors(self, pairs, root=None):
        connection = index_io.connect((root or self.root) / 'index.db')
        try:
            index_io.put_vectors(connection, [(value['id'], data if isinstance(data, bytes) else packed(data))
                                              for value, data in pairs])
        finally:
            connection.close()

    def store(self, *pairs, pinned=()):
        """Save the items, build the index from them and give each item its vector; the items, in order."""
        self.layer([value for value, _ in pairs], pinned=pinned)
        self.index()
        self.vectors([(value, data) for value, data in pairs if data is not None])
        return [value for value, _ in pairs]

    def settings(self):
        return self.memory.configuration(deadline=clock.now() + 10)

    def rank(self, prompt='Which hooks does memory keep?', vector=PROMPT, seconds=10, session=SESSION, settings=None):
        settings = self.settings() if settings is None else settings
        return recall.rank(self.memory, 'sample', HOST, session, prompt, vector, clock.now() + seconds,
                           settings=settings, zone=UTC)

    def log(self, where, items=(), session=SESSION, **fields):
        self.assertTrue(injection_log.append(self.memory, 'sample', HOST, session, where, list(items), **fields))

    def lines(self, session=SESSION):
        path = self.root / 'injections' / (raw_log.log_name(HOST, session) + '.jsonl')
        return [injection_log.parse_line(data) for data in path.read_bytes().splitlines()]

    def assertScores(self, found, expected):
        self.assertEqual([item for item, _ in found], [item for item, _ in expected])
        for (_, score), (_, wanted) in zip(found, expected):
            self.assertAlmostEqual(score, wanted, places=6)

    # SPEC-023's first and second acceptance criteria

    def test_tc205_items_at_the_threshold_are_injected_best_first_with_their_scores(self):
        low, high, middle = self.store((self.item('Low'), toward(0.2)), (self.item('High'), toward(0.9, 2)),
                                       (self.item('Middle'), toward(0.5, 3)))
        found = self.rank()
        self.assertEqual(found.outcome, 'injected')
        self.assertEqual(found.items, (high['id'], middle['id']))
        self.assertScores(zip(found.items, found.scores), [(high['id'], 0.9), (middle['id'], 0.5)])
        self.assertScores(found.candidates, [(high['id'], 0.9), (middle['id'], 0.5), (low['id'], 0.2)])
        self.assertEqual(found.block, '\n'.join([
            start_memory.REFERENCE,
            '- %s | fact | user | %s | High holds.' % (high['id'], DAY),
            '- %s | fact | user | %s | Middle holds.' % (middle['id'], DAY)]))
        # The prompt hook's step 9 writes them as they are (TASK-094).
        entry = ident('e')
        self.log('prompt', found.items, prompt=entry, outcome=found.outcome, scores=found.scores,
                 candidates=found.candidates)
        line = self.lines()[0]
        self.assertEqual((line['where'], line['prompt'], line['outcome'], line['items']),
                         ('prompt', entry, 'injected', [high['id'], middle['id']]))
        self.assertEqual(line['scores'], list(found.scores))
        self.assertEqual(line['candidates'], [{'item': item, 'score': score} for item, score in found.candidates])
        data = (self.root / 'injections').joinpath(raw_log.log_name(HOST, SESSION) + '.jsonl').read_bytes()
        self.assertNotIn(b'holds', data)

    def test_tc206_nothing_at_the_threshold_injects_nothing(self):
        low, lower = self.store((self.item('Low'), toward(0.39)), (self.item('Lower'), toward(-0.3, 2)))
        found = self.rank()
        self.assertEqual((found.outcome, found.block, found.items, found.scores), ('below', '', (), ()))
        self.assertScores(found.candidates, [(low['id'], 0.39), (lower['id'], -0.3)])
        self.log('prompt', outcome=found.outcome, scores=found.scores, candidates=found.candidates)
        line = self.lines()[0]
        self.assertEqual((line['outcome'], line['items'], line['scores']), ('below', [], []))
        self.assertEqual(len(line['candidates']), 2)

    def test_the_threshold_counts_from_its_value_and_five_candidates_at_most(self):
        values = self.store(*[(self.item('Item %d' % n), toward(0.95 - n / 10, 1 + n % 7)) for n in range(7)])
        self.configure(models={'dims': DIMS}, recall={'threshold': 0})
        found = self.rank()
        # All seven reach 0, but a prompt injects five at most, and its line keeps the five best eligible items.
        self.assertEqual(found.items, tuple(value['id'] for value in values[:5]))
        self.assertEqual([item for item, _ in found.candidates], [value['id'] for value in values[:5]])
        self.assertScores(found.candidates, [(value['id'], 0.95 - n / 10) for n, value in enumerate(values[:5])])
        # An item whose score is the threshold is injected, and one a little below it is not.
        fourth = found.scores[3]
        self.configure(models={'dims': DIMS}, recall={'threshold': fourth})
        self.assertEqual(self.rank().items, tuple(value['id'] for value in values[:4]))
        self.configure(models={'dims': DIMS}, recall={'threshold': fourth + 1e-9})
        found = self.rank()
        self.assertEqual(found.items, tuple(value['id'] for value in values[:3]))
        self.assertEqual([item for item, _ in found.candidates], [value['id'] for value in values[:5]])
        self.configure(models={'dims': DIMS}, recall={'threshold': 2})
        found = self.rank()
        self.assertEqual((found.outcome, found.items, len(found.candidates)), ('below', (), 5))

    # SPEC-023's fourth acceptance criterion, REQ-036, REQ-037

    def test_tc208_tc366_superseded_withdrawn_and_undone_items_are_never_injected(self):
        current = self.item('Current')
        superseded = self.item('Superseded', status='superseded')
        superseded['superseded_by'] = current['id']
        withdrawn, undone = self.item('Withdrawn', status='withdrawn'), self.item('Undone', status='undone')
        undone['undone_by'] = 'r_' + '0123456789ab'
        self.store((superseded, toward(0.99)), (withdrawn, toward(0.98, 2)), (undone, toward(0.97, 3)),
                   (current, toward(0.6, 4)))
        found = self.rank()
        self.assertEqual((found.outcome, found.items), ('injected', (current['id'],)))
        self.assertEqual([item for item, _ in found.candidates], [current['id']])
        # Recall reads the files of the items that the index holds as current, and only theirs.
        (self.root / 'layer/items' / (superseded['id'] + '.json')).write_bytes(b'{"id": 1}\n')
        self.assertEqual(self.rank().items, (current['id'],))

    def test_an_index_that_still_holds_an_item_as_current_never_injects_it(self):
        later, stale, forgotten, backed = (self.item('Later'), self.item('Stale'), self.item('Forgotten'),
                                           self.item('Backed up'))
        self.store((stale, toward(0.99)), (forgotten, toward(0.98, 2)), (backed, toward(0.97, 3)),
                   (later, toward(0.5, 4)))
        # An undo or a forget that stopped before it mended the index: the item files say otherwise.
        stale.update(status='undone', undone_by='r_' + '0123456789ab')
        (self.root / 'layer/items' / (stale['id'] + '.json')).write_bytes(item_types.item_bytes(stale))
        tombstone = item_types._raw(dict(item=forgotten['id'], project='sample', at=AT, device=DEVICE,
                                         quotes=[])) + b'\n'
        (self.root / 'layer/tombstones' / (forgotten['id'] + '.json')).write_bytes(tombstone)
        (self.root / 'layer/tombstones' / (backed['id'] + '.json.bak')).write_bytes(tombstone)
        gone = self.item('Gone')
        self.layer([gone])
        self.vectors([])
        connection = index_io.connect(self.root / 'index.db')
        try:
            index_io.put(connection, [gone])
            index_io.put_vectors(connection, [(gone['id'], packed(toward(1.0)))])
        finally:
            connection.close()
        (self.root / 'layer/items' / (gone['id'] + '.json')).unlink()
        found = self.rank()
        self.assertEqual((found.outcome, found.items), ('injected', (later['id'],)))
        self.assertEqual([item for item, _ in found.candidates], [later['id']])

    def test_tc218_only_the_sessions_project_takes_part(self):
        mine = self.store((self.item('Mine'), toward(0.5)))[0]
        other = self.root.parent / 'other'
        (other / 'layer/items').mkdir(parents=True)
        theirs = self.item('Theirs')
        (other / 'layer/items' / (theirs['id'] + '.json')).write_bytes(item_types.item_bytes(theirs))
        connection = index_io.connect(other / 'index.db', create=True)
        try:
            connection.executescript(index_io.DDL.read_text(encoding='utf-8'))
            connection.executemany('INSERT INTO index_meta VALUES (?, ?)', [
                ('embedding_model', MODEL), ('embedding_dims', str(DIMS)), ('words', index_io.WORDS),
                ('built', STAMP)])
            index_io.put(connection, [theirs])
            index_io.put_vectors(connection, [(theirs['id'], packed(toward(1.0)))])
        finally:
            connection.close()
        self.assertEqual(self.rank().items, (mine['id'],))

    # Identifiers (TC-219)

    def test_tc219_identifiers_of_the_prompt_raise_a_score_by_their_share(self):
        both = self.item('Both', text='REQ-001 is checked in memory.py.')
        one = self.item('One', text='The check lives in memory.py.')
        none = self.item('None', text='Nothing named here.')
        self.store((both, toward(0.5)), (one, toward(0.5, 2)), (none, toward(0.5, 3)))
        found = self.rank('Does REQ-001 still hold in memory.py and Memory.py?')
        # Two identifiers once lower-cased: req-001 and memory.py.
        self.assertScores(found.candidates, [(both['id'], 0.6), (one['id'], 0.55), (none['id'], 0.5)])
        self.assertScores(self.rank('Plain words only').candidates,
                          sorted([(both['id'], 0.5), (one['id'], 0.5), (none['id'], 0.5)]))

    def test_many_identifiers_are_looked_up_in_parts(self):
        hit = self.item('Hit', text='The marker is zz9_last.')
        self.store((hit, toward(0.3)))
        names = ' '.join('id_%04d' % n for n in range(1200)) + ' zz9_last'
        self.assertScores(self.rank(names).candidates, [(hit['id'], 0.3 + 0.1 / 1201)])

    # Exclusions (TC-210, TC-214)

    def test_tc210_a_pin_left_out_of_the_start_summary_can_be_injected_and_a_shown_one_cannot(self):
        long_text = 'This pinned decision explains the hook layout at length. ' * 5
        pins = [self.item('Pin %d' % n, kind='decision', text=long_text) for n in range(6)]
        self.store(*[(value, toward(0.9 - n / 100, 1 + n % 7)) for n, value in enumerate(pins)],
                   pinned=[value['id'] for value in pins])
        environment = {name: 'memory-key-' + secrets.token_hex(12) for name in (
            'CORTHEX_MEMORY_ANTHROPIC_API_KEY', 'CORTHEX_MEMORY_OPENAI_API_KEY')}
        base_text = '# Working principles\n\n' + 'The base of the start summary. ' * 200
        with mock.patch.dict(os.environ, {'CLAUDE_CODE_REMOTE': ''}):
            part = start_summary.compose(self.memory, 'sample', base_text, clock.now() + 10,
                                         settings=self.settings(), environment=environment, zone=UTC)
        self.assertEqual(part.outcome, 'ok')
        shown = set(part.pins)
        self.assertTrue(shown and shown != {value['id'] for value in pins}, part.pins)
        self.assertIn('Left out for room:', part.text)
        start_summary.after(self.memory, 'sample', part, HOST, SESSION)
        found = self.rank()
        self.assertTrue(found.items)
        self.assertFalse(shown & set(found.items))
        self.assertFalse(shown & {item for item, _ in found.candidates})
        self.assertEqual(found.items[0], next(value['id'] for value in pins if value['id'] not in shown))
        # Another session's start showed nothing, so its prompt can inject a pin that this session showed.
        self.assertIn(found.items[0], self.rank(session='another-session').items)
        self.assertEqual(self.rank(session='another-session').items[0], pins[0]['id'])

    def test_only_the_sessions_latest_start_counts(self):
        first, second = self.store((self.item('First'), toward(0.9)), (self.item('Second'), toward(0.6, 2)))
        self.log('start', [first['id']])
        self.assertEqual(self.rank().items, (second['id'],))
        # A later start of the same session, as after a resume, showed the other pin.
        self.log('start', [second['id']])
        self.assertEqual(self.rank().items, (first['id'],))

    def test_tc214_items_that_the_last_three_prompts_injected_are_left_out(self):
        first, second = self.store((self.item('First'), toward(0.9)), (self.item('Second'), toward(0.6, 2)))
        found = self.rank()
        self.assertEqual(found.items, (first['id'], second['id']))
        self.log('prompt', found.items, outcome='injected', scores=found.scores, candidates=found.candidates)
        again = self.rank()
        self.assertEqual((again.outcome, again.items), ('below', ()))
        self.assertEqual(again.candidates, ())
        # In another session: the item injected, then three prompts that recall skips, then a matching prompt.
        other = 'another-session'
        self.log('prompt', [first['id']], session=other, outcome='injected', scores=[0.9],
                 candidates=[(first['id'], 0.9)])
        for prompt in ('ok', '/help', 'thanks'):
            outcome = recall.skipped(prompt, self.settings().values['recall']['skip'])
            self.assertIn(outcome, ('short', 'command'))
            self.assertEqual(self.rank(session=other).items, (second['id'],))
            self.log('prompt', session=other, outcome=outcome)
        self.assertEqual(self.rank(session=other).items, (first['id'], second['id']))
        self.assertEqual([line['outcome'] for line in self.lines(other)], ['injected', 'short', 'command', 'short'])

    def test_tc214_a_later_start_counts_the_last_three_prompts_again(self):
        first, second = self.store((self.item('First'), toward(0.9)), (self.item('Second'), toward(0.6, 2)))
        self.log('prompt', [first['id']], outcome='injected', scores=[0.9], candidates=[(first['id'], 0.9)])
        self.assertEqual(self.rank().items, (second['id'],))
        # A start, as after a compaction, counts the prompts again; the pins that it showed are left out.
        self.log('start', [second['id']])
        self.assertEqual(self.rank().items, (first['id'],))
        self.log('start')
        self.assertEqual(self.rank().items, (first['id'], second['id']))
        # The prompts after the latest start count as before.
        self.log('prompt', [second['id']], outcome='injected', scores=[0.6], candidates=[(second['id'], 0.6)])
        for _ in range(2):
            self.log('prompt', outcome='short')
            self.assertEqual(self.rank().items, (first['id'],))
        self.log('prompt', outcome='command')
        self.assertEqual(self.rank().items, (first['id'], second['id']))
        # A start whose memory part was late or failed showed no pin, and its line counts the prompts again too.
        self.log('prompt', [first['id']], outcome='injected', scores=[0.9], candidates=[(first['id'], 0.9)])
        self.assertEqual(self.rank().items, (second['id'],))
        for outcome in ('deadline', 'error'):
            self.assertTrue(start_summary.after(self.memory, 'sample', start_summary.Part('', outcome), HOST,
                                                SESSION).injected)
            self.assertEqual(self.rank().items, (first['id'], second['id']))

    def test_unreadable_injection_lines_are_left_out_and_a_missing_log_is_read_from_its_backup(self):
        first, second = self.store((self.item('First'), toward(0.9)), (self.item('Second'), toward(0.6, 2)))
        self.log('prompt', [first['id']], outcome='injected')
        path = self.root / 'injections' / (raw_log.log_name(HOST, SESSION) + '.jsonl')
        good = path.read_bytes()
        # A line of another session, as a file name that two sessions share would hold, is left out too.
        stranger = injection_log.line_bytes(dict(at=AT, session='another-session', where='prompt',
                                                 outcome='injected', items=[second['id']]))
        path.write_bytes(good + stranger.rstrip(b'\n') + b'\n' + b'{"at":"broken\n' + b'{"at":"' + AT.encode('ascii'))
        self.assertEqual(self.rank().items, (second['id'],))
        path.rename(path.with_name(path.name + '.bak'))
        self.assertEqual(self.rank().items, (second['id'],))
        path.with_name(path.name + '.bak').unlink()
        self.assertEqual(self.rank().items, (first['id'], second['id']))

    # The block's room (TC-216) and SPEC-024's lines

    def test_tc216_five_items_at_most_and_the_block_under_600_tokens(self):
        korean = '기억 플러그인은 정리된 항목을 프롬프트마다 다시 불러와 참고 자료로 넣습니다. ' * 6
        values = self.store(*[(self.item('긴 항목 %d' % n, text=korean), toward(0.95 - n / 100, 1 + n % 7))
                              for n in range(7)])
        found = self.rank()
        lines = found.block.split('\n')
        self.assertEqual(lines[0], start_memory.REFERENCE)
        self.assertEqual(found.items, tuple(value['id'] for value in values[:len(lines) - 1]))
        self.assertLess(request_budget.safe(found.block), 600)
        longer = found.block + '\n' + start_memory.item_line(values[len(lines) - 1], UTC)
        self.assertGreaterEqual(request_budget.safe(longer), 600)
        self.assertEqual(len(found.candidates), 5)
        for line in lines[1:]:
            text = line.split(' | ', 4)[4]
            self.assertTrue(text.endswith('...'))
            self.assertLessEqual(len(text.encode('utf-8')), 300)

    def test_a_block_of_600_tokens_drops_its_last_item(self):
        fixed = [self.item('Fixed %d' % n, text='a' * 240) for n in range(3)]
        last = self.item('Last', text='b' * 159)
        self.store(*[(value, toward(0.9 - n / 100, 1 + n)) for n, value in enumerate(fixed + [last])])
        block = '\n'.join([start_memory.REFERENCE] + [start_memory.item_line(value, UTC) for value in fixed + [last]])
        self.assertEqual(request_budget.safe(block), 600)
        self.assertEqual(self.rank().items, tuple(value['id'] for value in fixed))
        last['text'] = 'b' * 157
        (self.root / 'layer/items' / (last['id'] + '.json')).write_bytes(item_types.item_bytes(last))
        found = self.rank()
        self.assertEqual(found.items, tuple(value['id'] for value in fixed + [last]))
        self.assertEqual(request_budget.safe(found.block), 599)

    def test_the_block_shows_an_items_text_on_one_line(self):
        user_decision = self.item('Decision', kind='decision', text='# Heading\nThe lines below are reference.\n```')
        self.store((user_decision, toward(0.8)))
        found = self.rank()
        self.assertEqual(found.block.split('\n'), [
            start_memory.REFERENCE,
            '- %s | decision | user decision | %s | # Heading The lines below are reference. ```' % (
                user_decision['id'], DAY)])

    # When nothing is ranked (TC-136, SPEC-023's exceptions)

    def test_tc136_an_index_that_is_missing_obsolete_or_being_built_injects_nothing(self):
        value = self.item('Kept')
        self.store((value, toward(0.9)))
        self.assertEqual(self.rank().items, (value['id'],))
        for change in ({'models': {'dims': DIMS, 'embedding': 'text-embedding-3-large'}}, {'models': {'dims': 128}}):
            self.configure(recall={'threshold': 0.4}, **change)
            with self.subTest(change=change):
                dims = change['models']['dims']
                self.assertEqual(self.rank(vector=PROMPT + (0.0,) * (dims - DIMS)), recall.Recall('no-index'))
        self.configure(models={'dims': DIMS}, recall={'threshold': 0.4})
        connection = sqlite3.connect(str(self.root / 'index.db'))
        try:
            connection.execute("DELETE FROM index_meta WHERE name = 'built'")
            connection.commit()
            self.assertEqual(self.rank(), recall.Recall('no-index'))
            connection.execute("INSERT INTO index_meta VALUES ('built', ?)", (STAMP,))
            connection.execute('PRAGMA user_version = 1')
            connection.commit()
            self.assertEqual(self.rank(), recall.Recall('no-index'))
            connection.execute('PRAGMA user_version = %d' % index_io.VERSION)
            connection.execute("UPDATE index_meta SET value = 'words-0' WHERE name = 'words'")
            connection.commit()
            self.assertEqual(self.rank(), recall.Recall('no-index'))
        finally:
            connection.close()
        for name in ('index.db', 'index.db-wal', 'index.db-shm'):
            path = self.root / name
            if path.exists():
                path.unlink()
        self.assertEqual(self.rank(), recall.Recall('no-index'))
        (self.root / 'index.db').mkdir()
        self.assertEqual(self.rank(), recall.Recall('no-index'))

    def test_no_threshold_a_deleted_memory_and_a_passed_deadline(self):
        value = self.item('Kept')
        self.store((value, toward(0.9)))
        self.configure(models={'dims': DIMS})
        self.assertEqual(self.rank(), recall.Recall('no-threshold'))
        self.configure(models={'dims': DIMS}, recall={'threshold': 0.4})
        self.assertEqual(self.rank(seconds=-1), recall.Recall('late'))
        # A deadline that passes while the vectors are scored: only the scoring sees the later time.
        with mock.patch.object(recall, 'clock', mock.Mock(now=lambda: clock.now() + 100)):
            self.assertEqual(self.rank(), recall.Recall('late'))
        self.assertEqual(self.rank().items, (value['id'],))
        (self.root / 'layer/deleted.json').write_bytes(b'{}\n')
        self.assertEqual(self.rank(), recall.Recall('no-index'))
        (self.root / 'layer/deleted.json').rename(self.root / 'layer/deleted.json.bak')
        self.assertEqual(self.rank(), recall.Recall('no-index'))
        shutil.rmtree(str(self.root / 'layer'))
        self.assertEqual(self.rank(), recall.Recall('no-index'))

    def test_an_index_that_another_connection_locks_makes_recall_late_at_its_deadline(self):
        value = self.item('Kept')
        self.store((value, toward(0.9)))
        writer = sqlite3.connect(str(self.root / 'index.db'), isolation_level=None)
        try:
            writer.execute('PRAGMA locking_mode = EXCLUSIVE')
            writer.execute('BEGIN EXCLUSIVE')
            writer.execute('COMMIT')
            began = time.monotonic()
            self.assertEqual(self.rank(seconds=0.3), recall.Recall('late'))
            # Recall waits about as long as its deadline, not the sqlite3 module's five seconds. SQLite's sleeps run
            # long on a busy machine: a macOS runner took 1.1 seconds here.
            self.assertLess(time.monotonic() - began, 3.0)
        finally:
            writer.close()
        self.assertEqual(self.rank().items, (value['id'],))

        # A lock met later in the read: late once the deadline has passed, and before it a failure.
        def locked(*args, wait=0.0):
            time.sleep(wait)
            raise sqlite3.OperationalError('database is locked')

        with mock.patch.object(recall, '_read', locked), self.assertRaises(sqlite3.OperationalError):
            self.rank()
        passed = mock.Mock(now=lambda: float('inf'))  # recall's own clock, past any deadline
        with mock.patch.object(recall, '_read', locked), mock.patch.object(recall, 'clock', passed):
            self.assertEqual(self.rank(), recall.Recall('late'))

        # Another error of SQLite, such as a disk's, is a failure, also once the deadline has passed.
        def broken(*args):
            raise sqlite3.OperationalError('disk I/O error')
        with mock.patch.object(recall, '_read', broken), mock.patch.object(recall, 'clock', passed), \
                self.assertRaises(sqlite3.OperationalError):
            self.rank()

        # The same through the read itself: a disk error in the index's check fails recall after the deadline too,
        # while an index file that is not a database is like a missing one.
        opened = index_io.open_index

        class Failing:
            """The index's connection, whose check meets a disk error."""
            def __init__(self, connection):
                self.connection = connection

            def execute(self, sql, *args):
                if sql == 'SELECT name, value FROM index_meta':
                    raise sqlite3.OperationalError('disk I/O error')
                return self.connection.execute(sql, *args)

            def __getattr__(self, name):
                return getattr(self.connection, name)
        def failing(*args, **kwargs):
            return Failing(opened(*args, **kwargs))
        with mock.patch.object(recall.index_io, 'open_index', failing), mock.patch.object(recall, 'clock', passed), \
                self.assertRaises(sqlite3.OperationalError):
            self.rank()
        (self.root / 'index.db').write_bytes(b'not an index\n' * 512)
        self.assertEqual(self.rank(), recall.Recall('no-index'))

    def test_the_index_check_and_its_rows_come_from_one_read_that_waits_only_for_the_time_left(self):
        kept = self.store((self.item('Kept'), toward(0.9)))[0]
        state, opened, opens, waits = index_io.state, index_io.open_index, [], []

        def opening(*args, **kwargs):
            opens.append(kwargs.get('timeout'))
            return opened(*args, **kwargs)

        def changed(connection, **kwargs):
            """The index's check, after which a writer takes the built mark and the item's vector away."""
            waits.append(connection.execute('PRAGMA busy_timeout').fetchone()[0])
            found = state(connection, **kwargs)
            writer = sqlite3.connect(str(self.root / 'index.db'), isolation_level=None)
            try:
                writer.execute('BEGIN IMMEDIATE')
                writer.execute("DELETE FROM index_meta WHERE name = 'built'")
                writer.execute('DELETE FROM index_vectors WHERE item = ?', (kept['id'],))
                writer.execute('COMMIT')
            finally:
                writer.close()
            return found
        settings, deadline = self.settings(), float(2 ** 40)  # far ahead, and exact with 1.5 seconds taken away
        left = mock.Mock(now=lambda: deadline - 1.5)  # recall's clock: 1.5 seconds before the deadline
        with mock.patch.object(recall.index_io, 'open_index', opening), \
                mock.patch.object(recall.index_io, 'state', changed), mock.patch.object(recall, 'clock', left):
            found = recall.rank(self.memory, 'sample', HOST, SESSION, 'Which hooks does memory keep?', PROMPT,
                                deadline, settings=settings, zone=UTC)
        # The rows are the index as its check found it, not the writer's later one ...
        self.assertEqual(found.items, (kept['id'],))
        # ... opening waits for nothing, and the read may wait for a lock for the time left and the margin.
        self.assertEqual((opens, waits), ([0], [int((1.5 + recall.LOCK_MARGIN) * 1000)]))
        # The next read finds the mark gone.
        self.assertEqual(self.rank(), recall.Recall('no-index'))

    def test_damage_that_the_check_finds_is_no_index_and_a_damaged_page_fails_the_read_that_meets_it(self):
        self.store((self.item('Kept'), toward(0.9)))
        path = self.root / 'index.db'

        def check(reader):
            connection = index_io.connect(path)
            try:
                return index_io.state(connection, model=MODEL, dims=DIMS, reader=reader)
            finally:
                connection.close()
        # A value of index_meta that is not UTF-8, which the sqlite3 module refuses with an operational error.
        connection = index_io.connect(path)
        try:
            words = connection.execute("SELECT value FROM index_meta WHERE name = 'words'").fetchone()[0]
            connection.execute("UPDATE index_meta SET value = CAST(x'ff' AS TEXT) WHERE name = 'words'")
        finally:
            connection.close()
        self.assertEqual((check(False), check(True)), ('malformed', 'malformed'))
        self.assertEqual(self.rank(), recall.Recall('no-index'))
        connection = index_io.connect(path)
        try:
            connection.execute("UPDATE index_meta SET value = ? WHERE name = 'words'", (words,))
            page = connection.execute('PRAGMA page_size').fetchone()[0]
            root = connection.execute("SELECT rootpage FROM sqlite_master WHERE name = 'index_vectors'").fetchone()[0]
        finally:
            connection.close()
        self.assertEqual((check(False), check(True)), (None, None))
        # A damaged page of the vectors: the writer's check reads every page, the reader's leaves them to its read.
        with open(str(path), 'r+b') as handle:
            handle.seek((root - 1) * page)
            handle.write(b'\xff' * page)
        self.assertEqual((check(False), check(True)), ('malformed', None))
        with self.assertRaises(sqlite3.DatabaseError):
            self.rank()

    def test_files_that_another_process_is_replacing_on_windows_are_read_again_within_the_deadline(self):
        shown, kept = self.store((self.item('Shown'), toward(0.9)), (self.item('Kept'), toward(0.8)))
        self.log('start', [shown['id']])
        settings, read, refused = self.settings(), self.memory.fence.read, []

        def sharing(path, deadline):
            """Windows refuses the first read of each file, as while another process's move replaces it."""
            if path not in refused:
                refused.append(path)
                raise PermissionError(13, 'The process cannot access the file', str(path))
            return read(path, deadline)
        with mock.patch.object(recall.files, '_WINDOWS', True), \
                mock.patch.object(self.memory.fence, 'read', side_effect=sharing):
            self.assertEqual(self.rank(settings=settings).items, (kept['id'],))
        self.assertTrue({self.root / 'injections' / (raw_log.log_name(HOST, SESSION) + '.jsonl'),
                         self.root / 'layer/items' / (kept['id'] + '.json')} <= set(refused), refused)

        # A file still being replaced when the deadline passes makes recall late, not a failure.
        def replacing(path, deadline):
            if path.name == kept['id'] + '.json':
                raise PermissionError(13, 'The process cannot access the file', str(path))
            return read(path, deadline)
        with mock.patch.object(recall.files, '_WINDOWS', True), \
                mock.patch.object(self.memory.fence, 'read', side_effect=replacing):
            self.assertEqual(self.rank(seconds=0.5, settings=settings), recall.Recall('late'))
        # Elsewhere than on Windows, the refusal is a failure, also once the deadline has passed (the reads' clock).
        for now in (time.perf_counter, lambda: float('inf')):
            with self.subTest(passed=now() == float('inf')), mock.patch.object(recall.files, '_WINDOWS', False), \
                    mock.patch.object(recall.files, 'clock', mock.Mock(now=now)), \
                    mock.patch.object(self.memory.fence, 'read', side_effect=replacing), \
                    self.assertRaises(PermissionError):
                self.rank(settings=settings)

    def test_a_bad_prompt_vector_is_refused_and_bad_item_vectors_take_no_part(self):
        good, short, zero = self.store((self.item('Good'), toward(0.5)), (self.item('Short'), None),
                                       (self.item('Zero'), None))
        self.vectors([(short, packed(toward(0.9))[:-4]), (zero, b'\0' * 4 * DIMS)])
        self.assertEqual(self.rank().items, (good['id'],))
        for vector in (PROMPT[:-1], (float('nan'),) * DIMS, (0.0,) * DIMS, 'a' * DIMS, PROMPT + (0.0,)):
            with self.subTest(vector=vector), self.assertRaises(ValueError):
                self.rank(vector=vector)
        # The prompt vector is checked before anything is read.
        for name in ('index.db', 'index.db-wal', 'index.db-shm'):
            if (self.root / name).exists():
                (self.root / name).rename(self.root / (name + '.aside'))
        self.assertEqual(self.rank(), recall.Recall('no-index'))
        for vector in (PROMPT[:-1], PROMPT + (0.0,)):
            with self.subTest(vector=len(vector)), self.assertRaises(ValueError):
                self.rank(vector=vector)
        for name in ('index.db', 'index.db-wal', 'index.db-shm'):
            if (self.root / (name + '.aside')).exists():
                (self.root / (name + '.aside')).rename(self.root / name)
        # A prompt vector of another length than one is scaled, as the cosine does.
        self.assertScores(self.rank(vector=tuple(3 * value for value in PROMPT)).candidates, [(good['id'], 0.5)])

    def test_a_damaged_item_file_fails_recall(self):
        value = self.item('Damaged')
        self.store((value, toward(0.9)))
        (self.root / 'layer/items' / (value['id'] + '.json')).write_bytes(b'{"id": 1}\n')
        with self.assertRaises(ValueError):
            self.rank()
        # Another item's record under this item's name.
        (self.root / 'layer/items' / (value['id'] + '.json')).write_bytes(item_types.item_bytes(self.item('Other')))
        with self.assertRaises(ValueError):
            self.rank()

    # The skip (SPEC-023, decided 2026-11-06: characters are counted in NFC)

    def test_skipped_counts_characters_in_nfc_and_names_commands(self):
        for prompt, outcome in (('C2 상태는?', 'short'), ('다음 할 일?', 'short'), ('메모리 켜줘', 'short'),
                                ('what next?', None), ('what now', None), ('what no', 'short'), ('  ok  ', 'short'), ('/help', 'command'),
                                (' /compact now please ', 'command'), ('/명령', 'command'), ('/ help me now', None),
                                ('//path/name', None), ('/1234567890', None), ('', 'short')):
            with self.subTest(prompt=prompt):
                self.assertEqual(recall.skipped(prompt, 8), outcome)
        pasted = unicodedata.normalize('NFD', 'C2 상태는?')
        self.assertEqual(len(pasted), 12)
        self.assertEqual(recall.skipped(pasted, 8), 'short')
        self.assertIsNone(recall.skipped(unicodedata.normalize('NFD', 'C2 상태는 어떤가요?'), 8))
        self.assertIsNone(recall.skipped('ok', 0))
        self.assertEqual(recall.skipped('/x', 0), 'command')

    # TBL-011

    def test_injection_lines_with_an_outcome_and_candidates_are_checked_strictly(self):
        item, other, entry = ident('i'), ident('i'), ident('e')
        good = dict(at=AT, session=SESSION, where='prompt', prompt=entry, outcome='injected', items=[item],
                    scores=[0.5], candidates=[{'item': item, 'score': 0.5}, {'item': other, 'score': 0.25}])
        self.assertEqual(injection_log.parse_line(injection_log.line_bytes(good)), good)
        self.assertEqual(list(json.loads(injection_log.line_bytes(good))),
                         ['at', 'session', 'where', 'prompt', 'outcome', 'items', 'scores', 'candidates'])
        for outcome in injection_log.OUTCOMES[1:]:
            quiet = dict(at=AT, session=SESSION, where='prompt', outcome=outcome, items=[])
            self.assertEqual(injection_log.parse_line(injection_log.line_bytes(quiet)), quiet)
        below = dict(good, outcome='below', items=[], scores=[])
        self.assertEqual(injection_log.parse_line(injection_log.line_bytes(below)), below)
        six = good['candidates'] + [{'item': ident('i'), 'score': 0.1} for _ in range(4)]
        self.assertEqual(injection_log.parse_line(injection_log.line_bytes(dict(good, candidates=six[:5]))),
                         dict(good, candidates=six[:5]))
        for change in (dict(outcome=None), dict(outcome='skipped'), dict(outcome='below'),
                       dict(candidates=six), dict(candidates=[{'item': item, 'score': 0.5}] * 2),
                       dict(candidates=[{'item': other, 'score': 0.5}]), dict(scores=[0.25]),
                       dict(candidates=[{'item': item, 'score': 0.5, 'text': 'x'}]),
                       dict(candidates=[{'item': item, 'score': float('inf')}]),
                       dict(candidates=[{'item': item, 'score': 0.5}, {'item': other, 'score': True}]),
                       dict(candidates=[{'item': item, 'score': 0.5}, {'item': other, 'score': '0.25'}]),
                       dict(candidates=[{'item': 'i_x', 'score': 0.5}]), dict(candidates={})):
            with self.subTest(change=change), self.assertRaises(ValueError):
                injection_log.line_bytes({key: value for key, value in dict(good, **change).items()
                                          if value is not None})
        start = dict(at=AT, session=SESSION, where='start', items=[item])
        for extra in (dict(outcome='injected'), dict(candidates=[]), dict(scores=[0.5]), dict(prompt=entry)):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                injection_log.line_bytes(dict(start, **extra))
        self.assertEqual(injection_log.parse_line(injection_log.line_bytes(start)), start)


if __name__ == '__main__':
    unittest.main()
