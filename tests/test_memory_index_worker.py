"""TASK-082: the memory worker's step 6 keeps the search index and embeds current items.

TC-136, TC-139 and TC-141, and the step's parts of TC-140, on made-up
format-2 stores. Every embedding request goes to a local test server, with keys
made up during the run; no provider is called. Nothing calls the step before
the 0.3.0 activation.
"""
import json
import math
import os
import re
import sqlite3
import struct
import sys
import threading
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import (clock, diagnostics, fence_plan, index_io, index_worker, model_access, model_embed,
                        revision_io)
import test_memory_curation_worker as worker_fixture

STAMP, WHEN = worker_fixture.STAMP, worker_fixture.WHEN
DIMS = 64


def numbers(text, dims=DIMS):
    """The test server's vector for an input: made from its bytes, so each item's can be told apart."""
    return [float(sum(text.encode('utf-8')) % 997 + 1), 1.0] + [0.0] * (dims - 2)


def packed(values):
    length = math.sqrt(math.fsum(n * n for n in values))
    return struct.pack('<%df' % len(values), *(n / length for n in values))


class IndexWorkerTest(unittest.TestCase):
    """Step 6 on the curation worker's store fixture, whose own tests stay in their module."""
    Fixture = worker_fixture.CurationWorkerTest
    configure, layer, write, saved, one_turn, quick = (Fixture.configure, Fixture.layer, Fixture.write,
                                                       Fixture.saved, Fixture.one_turn, Fixture.quick)
    items, usage, failures, snapshot, advance = (Fixture.items, Fixture.usage, Fixture.failures, Fixture.snapshot,
                                                 Fixture.advance)

    def setUp(self):
        self.Fixture.setUp(self)
        self.keys['CORTHEX_MEMORY_OPENAI_API_KEY'] = 'memory-openai-key-' + os.urandom(12).hex()
        self.keys['CORTHEX_MEMORY_OPENAI_BASE_URL'] = self.server.url
        environment = mock.patch.dict(os.environ, {name: self.keys[name] for name in (
            'CORTHEX_MEMORY_OPENAI_API_KEY', 'CORTHEX_MEMORY_OPENAI_BASE_URL')})
        environment.start()
        self.addCleanup(environment.stop)
        self.configure(models={'dims': DIMS})
        self.bad = set()     # request numbers answered with a vector of the wrong length
        self.server.reply = self.embeddings
        self.said, _ = self.one_turn()

    def embeddings(self, number, body):
        values = [numbers(text, body['dimensions']) for text in body['input']]
        if number in self.bad:
            values[0] = values[0][:-1]
        document = {'object': 'list', 'model': body['model'], 'usage': {'prompt_tokens': 7 * len(values)},
                    'data': [{'object': 'embedding', 'index': i, 'embedding': v} for i, v in enumerate(values)]}
        return lambda handler: worker_fixture.Server.send(handler, json.dumps(document).encode('utf-8'),
                                                          mime='application/json')

    def made(self, count, kind='fact'):
        """`count` current items, each with its own words, saved from the fixture's turn."""
        base = self.saved(self.said, worker_fixture.HOOKS, kind=kind)
        return [dict(base, id=worker_fixture.ident('i'), title='Item %d' % n,
                     text='Item number %d keeps the word marker%d.' % (n, n)) for n in range(count)]

    def keep(self, seconds=600):
        deadline = clock.now() + seconds
        with self.memory.lease(self.root / 'curation.lock', 'curation', deadline) as owner:
            return index_worker.keep(self.memory, 'sample', owner, deadline, when=WHEN)

    def tables(self):
        connection = sqlite3.connect(str(self.root / 'index.db'))
        try:
            return {table: sorted(connection.execute('SELECT * FROM ' + table).fetchall())
                    for table in ('index_meta', 'index_items', 'index_vectors', 'index_terms')}
        finally:
            connection.close()

    def vectors(self):
        return dict(self.tables()['index_vectors'])

    def expected(self, items=None):
        """The rows of an index built from the canonical items, as TASK-081 builds them."""
        connection = index_io.connect(self.folder.parent / 'expected.db', create=True)
        try:
            connection.executescript(index_io.DDL.read_text(encoding='utf-8'))
            index_io.put(connection, list((items or self.items()).values()))
            return {table: sorted(connection.execute('SELECT * FROM ' + table).fetchall())
                    for table in ('index_items', 'index_terms')}
        finally:
            connection.close()
            for name in ('expected.db', 'expected.db-wal', 'expected.db-shm'):
                path = self.folder.parent / name
                if path.exists():
                    path.unlink()

    def inputs(self):
        return [body['input'] for _, body in self.server.requests]

    # API-005 step 6, SPEC-016

    def test_tc139_items_without_a_vector_go_in_requests_of_100_and_a_bad_vector_waits_for_a_later_step(self):
        items = self.made(250)
        self.layer(items)
        self.bad = {1, 2, 3}
        with self.quick() as waits:
            outcome = self.keep()
        self.assertEqual((outcome.reason, outcome.rebuilt, outcome.requests, outcome.failed),
                         ('done', 'missing', 3, ('bad-vector',)))
        self.assertEqual(waits, [10, 60])
        # The second request's three attempts all had a bad vector; its 100 items keep none.
        sent = self.inputs()
        self.assertEqual([len(texts) for texts in sent], [100, 100, 100, 100, 50])
        self.assertEqual(sent[1], sent[2])
        ordered = sorted(items, key=lambda item: item['id'])
        failed = {item['id'] for item in ordered[100:200]}
        vectors = self.vectors()
        self.assertEqual(set(vectors), {item['id'] for item in ordered} - failed)
        self.assertEqual(set(outcome.embedded), set(vectors))
        for item, text in zip(ordered[:100] + ordered[200:], sent[0] + sent[4]):
            self.assertEqual(text, index_worker.text(item))
            self.assertEqual(vectors[item['id']], packed(numbers(text)))
        # It is found by words only, and noted once in the failure log.
        missing = ordered[150]
        self.assertEqual(self.search('marker' + missing['text'].split('marker')[1].rstrip('.')), [missing['id']])
        self.assertEqual(self.failures(), [('embed', 'bad-vector')])
        usage = self.usage()
        self.assertEqual([(row['call'], row['result']) for row in usage],
                         [('embed-items', 'ok')] + [('embed-items', 'failed')] * 3 + [('embed-items', 'ok')])
        self.assertEqual({row['model'] for row in usage}, {'text-embedding-3-small'})
        # A later step 6 embeds them, in one request, and changes nothing else.
        self.bad = set()
        before = self.tables()
        later = self.keep()
        self.assertEqual((later.reason, later.rebuilt, later.written, later.removed, later.requests),
                         ('done', None, (), (), 1))
        self.assertEqual(len(self.inputs()[-1]), 100)
        self.assertEqual(set(self.vectors()), {item['id'] for item in items})
        after = self.tables()
        self.assertEqual({k: v for k, v in after.items() if k != 'index_vectors'},
                         {k: v for k, v in before.items() if k != 'index_vectors'})

    def test_tc139_a_request_holds_at_most_200000_bytes(self):
        base = self.saved(self.said, worker_fixture.HOOKS)
        long = [dict(base, id=worker_fixture.ident('i'), text=('%03d' % n) + 'x' * 3990,
                     quotes=[dict(base['quotes'][0])] * 3) for n in range(60)]
        self.layer(long)
        self.assertEqual(self.keep().reason, 'done')
        # Each input has the same length, so a request holds as many as fit in 200,000 bytes.
        size = len(index_worker.text(long[0]).encode('utf-8'))
        fit = model_embed.BATCH_BYTES // size
        self.assertEqual((size, fit), (4104, 48))
        self.assertEqual([len(texts) for texts in self.inputs()], [fit, 60 - fit])
        self.assertEqual(len(self.vectors()), 60)

    def test_tc141_an_input_is_the_kind_text_and_quoted_words_cut_at_a_character_boundary(self):
        said, _ = self.one_turn('Keep the hooks in one script. unquoted-raw-marker-4f1a stays private.',
                                'One script serves the hooks.')
        quoted = self.saved(said, 'Keep the hooks in one script', kind='decision')
        quoted['text'] = 'One script serves the hooks; ' + self.keys['CORTHEX_MEMORY_ANTHROPIC_API_KEY']
        korean = dict(self.saved(self.said, worker_fixture.HOOKS, kind='decision'), id=worker_fixture.ident('i'))
        cited = dict(korean['quotes'][0], words='나' * 666, end=korean['quotes'][0]['start'] + 666)
        korean.update(text='가' * 1333, quotes=[cited] * 14)
        old = dict(self.made(1)[0], status='superseded', superseded_by=quoted['id'])
        self.layer([quoted, korean, old])
        before = self.snapshot()
        self.assertEqual(self.keep().reason, 'done')
        # Only current items are embedded; the superseded one is found by words.
        (headers, body), = self.server.requests
        self.assertEqual(len(body['input']), 2)
        self.assertEqual(set(self.vectors()), {quoted['id'], korean['id']})
        whole = index_worker.text(korean)
        self.assertGreater(len(whole.encode('utf-8')), 30000)
        cut = whole.encode('utf-8')[:8192].decode('utf-8', 'ignore')
        self.assertEqual(len(cut.encode('utf-8')), 8190)
        by_item = dict(zip(sorted([quoted['id'], korean['id']]), body['input']))
        self.assertEqual(by_item[korean['id']], cut)
        self.assertEqual(by_item[quoted['id']],
                         'decision\nOne script serves the hooks; [redacted:memory-key]\nKeep the hooks in one script')
        sent = json.dumps(body, ensure_ascii=False) + json.dumps(headers)
        for value in ('unquoted-raw-marker-4f1a', 'sample', self.keys['CORTHEX_MEMORY_ANTHROPIC_API_KEY'],
                      self.keys['OPENAI_API_KEY'], self.keys['ANTHROPIC_API_KEY']):
            self.assertNotIn(value, sent)
        self.assertEqual(headers['authorization'], 'Bearer ' + self.keys['CORTHEX_MEMORY_OPENAI_API_KEY'])
        self.assertNotIn(self.keys['CORTHEX_MEMORY_OPENAI_API_KEY'], json.dumps(body))
        self.assertEqual((body['model'], body['dimensions'], body['encoding_format']),
                         ('text-embedding-3-small', DIMS, 'float'))
        self.assertNotIn('user', body)
        # The stored items keep all of their text.
        after = self.snapshot()
        for item in (quoted, korean):
            name = 'layer/items/' + item['id'] + '.json'
            self.assertEqual(after[name], before[name])

    # SPEC-023, SPEC-025: an index of another model, vector length or version

    def test_tc136_another_model_vector_length_version_or_splitting_builds_the_index_again(self):
        items = self.made(3)
        self.layer(items)
        self.assertEqual(self.keep().rebuilt, 'missing')

        def again(expected, model='text-embedding-3-small', dims=DIMS):
            count = len(self.server.requests)
            outcome = self.keep()
            self.assertEqual((outcome.reason, outcome.rebuilt, outcome.requests), ('done', expected, 1))
            self.assertEqual(len(self.server.requests), count + 1)
            body = self.server.requests[-1][1]
            self.assertEqual((body['model'], body['dimensions'], len(body['input'])), (model, dims, 3))
            tables = self.tables()
            self.assertEqual(dict(tables['index_meta'])['embedding_model'], model)
            self.assertEqual(dict(tables['index_meta'])['embedding_dims'], str(dims))
            self.assertEqual({item for item, vector in tables['index_vectors'] if len(vector) == 4 * dims},
                             {item['id'] for item in items})
            self.assertEqual({k: tables[k] for k in ('index_items', 'index_terms')}, self.expected())

        self.configure(models={'dims': DIMS, 'embedding': 'text-embedding-3-large'})
        again('embedding', model='text-embedding-3-large')
        self.configure(models={'dims': 128, 'embedding': 'text-embedding-3-large'})
        again('embedding', model='text-embedding-3-large', dims=128)
        self.configure(models={'dims': 128})
        again('embedding', dims=128)
        connection = sqlite3.connect(str(self.root / 'index.db'), isolation_level=None)
        connection.execute('PRAGMA user_version = 1')
        connection.close()
        again('version', dims=128)
        connection = sqlite3.connect(str(self.root / 'index.db'), isolation_level=None)
        connection.execute("UPDATE index_meta SET value = 'words-0' WHERE name = 'words'")
        connection.close()
        again('words', dims=128)
        self.assertEqual([row['call'] for row in self.usage()], ['embed-items'] * 6)

    # TC-140, SPEC-035: forgotten items

    def test_tc140_an_item_forgotten_during_a_request_gets_no_vector_and_its_rows_go(self):
        items = self.made(3)
        self.layer(items)
        forgotten = sorted(items, key=lambda item: item['id'])[1]
        other = worker_fixture.C2Store(self.folder, expected_device=worker_fixture.DEVICE)
        self.server.before[0] = lambda: self.advance(other, forgotten)
        outcome = self.keep()
        self.assertEqual(outcome.reason, 'done')
        self.assertEqual(set(outcome.embedded), {item['id'] for item in items} - {forgotten['id']})
        self.assertNotIn(forgotten['id'], self.vectors())
        # The next step 6 deletes the rows that the forget left, and sends nothing, while a reader keeps the
        # index open, so that closing the step's own connection does not empty the log.
        reader = sqlite3.connect(str(self.root / 'index.db'))
        self.addCleanup(reader.close)
        reader.execute('SELECT count(*) FROM index_items').fetchall()
        later = self.keep()
        self.assertEqual((later.removed, later.requests), ((forgotten['id'],), 0))
        for table, rows in self.tables().items():
            self.assertFalse([row for row in rows if forgotten['id'] in row], table)
        # Neither the file nor its write-ahead log keeps the item's own word.
        word = re.search(r'marker\d+', forgotten['text']).group().encode('utf-8')
        for name in ('index.db', 'index.db-wal'):
            path = self.root / name
            self.assertNotIn(word, path.read_bytes() if path.exists() else b'', name)

    def test_tc140_an_item_whose_forget_stopped_after_its_tombstone_gets_no_vector_and_no_row(self):
        items = self.made(2)
        self.layer(items)
        forgotten = items[0]
        cited = forgotten['quotes'][0]
        tombstone = dict(item=forgotten['id'], project='sample', at=worker_fixture.AT, device=worker_fixture.DEVICE,
                         quotes=[{k: cited[k] for k in ('device', 'entry', 'log', 'start', 'end')}])

        def stopped():
            (self.root / 'layer/tombstones' / (forgotten['id'] + '.json')).write_bytes(
                worker_fixture.item_types._raw(tombstone) + b'\n')
        self.server.before[0] = stopped
        outcome = self.keep()
        self.assertEqual(outcome.embedded, (items[1]['id'],))
        later = self.keep()
        self.assertEqual((later.removed, later.requests), ((forgotten['id'],), 0))
        self.assertTrue((self.root / 'layer/items' / (forgotten['id'] + '.json')).exists())
        for table, rows in self.tables().items():
            self.assertFalse([row for row in rows if forgotten['id'] in row], table)

    def test_an_item_that_changes_stops_being_current_or_goes_during_its_request_gets_no_vector(self):
        items = sorted(self.made(4), key=lambda item: item['id'])
        self.layer(items)

        def change():
            path = self.root / 'layer/items' / (items[0]['id'] + '.json')
            path.write_bytes(worker_fixture.item_types.item_bytes(dict(items[0], text='Other words now.')))
            path = self.root / 'layer/items' / (items[1]['id'] + '.json')
            path.write_bytes(worker_fixture.item_types.item_bytes(dict(items[1], status='withdrawn')))
            (self.root / 'layer/items' / (items[3]['id'] + '.json')).unlink()
        self.server.before[0] = change
        outcome = self.keep()
        self.assertEqual((outcome.reason, outcome.embedded), ('done', (items[2]['id'],)))
        # The changed item's row and vector follow its new words at the next step 6; the withdrawn one has none,
        # and the rows of the one that went are deleted.
        later = self.keep()
        self.assertEqual((later.written, later.removed, later.embedded),
                         ((items[0]['id'], items[1]['id']), (items[3]['id'],), (items[0]['id'],)))
        self.assertEqual(self.server.requests[-1][1]['input'],
                         [index_worker.text(dict(items[0], text='Other words now.'))])

    def test_a_vector_is_written_only_for_an_item_that_the_index_holds(self):
        items = self.made(2)
        self.layer(items)
        with mock.patch.dict(os.environ, {'CORTHEX_MEMORY_OPENAI_API_KEY': ''}):
            self.keep()
        connection = index_io.connect(self.root / 'index.db')
        self.addCleanup(connection.close)
        vector = packed(numbers('x'))
        self.assertEqual(index_io.put_vectors(connection, [(items[0]['id'], vector), ('i_000000000000', vector)]),
                         [items[0]['id']])
        self.assertEqual(connection.execute('SELECT item FROM index_vectors').fetchall(), [(items[0]['id'],)])

    def test_a_request_ends_before_the_runs_last_minute(self):
        self.layer(self.made(1))
        answer = threading.Event()
        self.addCleanup(answer.set)
        self.server.before[0] = lambda: answer.wait(10)
        outcome = self.keep(seconds=index_worker.RESERVE + 4)
        self.assertEqual((outcome.reason, outcome.requests, outcome.failed, outcome.embedded),
                         ('deadline', 1, ('timeout',), ()))
        self.assertEqual(self.failures(), [('embed', 'timeout')])
        self.assertEqual(self.vectors(), {})

    def test_no_request_starts_in_the_runs_last_minute(self):
        self.layer(self.made(2))
        outcome = self.keep(seconds=index_worker.RESERVE - 5)
        self.assertEqual((outcome.reason, outcome.rebuilt, outcome.requests), ('deadline', 'missing', 0))
        self.assertEqual(self.server.requests, [])

    def test_tc140_an_item_forgotten_before_its_request_is_never_sent(self):
        items = self.made(150)
        self.layer(items)
        ordered = sorted(items, key=lambda item: item['id'])
        forgotten = ordered[120]
        other = worker_fixture.C2Store(self.folder, expected_device=worker_fixture.DEVICE)
        self.server.before[0] = lambda: self.advance(other, forgotten)
        outcome = self.keep()
        self.assertEqual((outcome.reason, outcome.requests), ('done', 2))
        first, second = self.inputs()
        self.assertEqual(len(first), 100)
        self.assertEqual(second, [index_worker.text(item) for item in ordered[100:] if item is not forgotten])
        self.assertNotIn(forgotten['text'], json.dumps(self.server.requests))
        self.assertEqual(set(self.vectors()), {item['id'] for item in items} - {forgotten['id']})

    def test_an_index_built_again_with_other_settings_during_a_request_takes_no_vector(self):
        items = self.made(2)
        self.layer(items)
        other = worker_fixture.C2Store(self.folder, expected_device=worker_fixture.DEVICE)

        def rebuild():
            deadline = clock.now() + 30
            with other.lease(self.root / 'layer.lock', 'layer', deadline):
                proof = fence_plan.snapshot(revision_io.read(other, self.root, deadline))
                index_io.rebuild(other, self.root, proof, deadline, model='text-embedding-3-small', dims=128,
                                 when=STAMP)
        self.server.before[0] = rebuild
        outcome = self.keep()
        self.assertEqual((outcome.reason, outcome.requests, outcome.embedded), ('stale', 1, ()))
        self.assertEqual((dict(self.tables()['index_meta'])['embedding_dims'], self.vectors()), ('128', {}))
        self.assertEqual(self.failures(), [])
        # The next step 6 builds it again with the configured length and embeds the items.
        later = self.keep()
        self.assertEqual((later.reason, later.rebuilt, len(later.embedded)), ('done', 'embedding', 2))

    # TASK-108: rows that a stopped writer left

    def test_rows_that_differ_from_the_items_are_written_again_and_a_changed_items_vector_is_made_again(self):
        items = self.made(4)
        self.layer(items)
        self.assertEqual(self.keep().reason, 'done')
        first, second, third, fourth = sorted(items, key=lambda item: item['id'])
        vectors = self.vectors()
        connection = sqlite3.connect(str(self.root / 'index.db'), isolation_level=None)
        # A stopped undo left the row of an item that it made current again as 'undone'; another row's
        # words are out of date, an item has no row and a row has no item.
        connection.execute("UPDATE index_items SET status = 'undone' WHERE item = ?", (first['id'],))
        connection.execute("UPDATE index_terms SET count = count + 1 WHERE item = ? AND term = 'item'",
                           (second['id'],))
        connection.execute('PRAGMA foreign_keys = ON')
        connection.execute('DELETE FROM index_items WHERE item = ?', (third['id'],))
        connection.close()
        stray = dict(fourth, id=worker_fixture.ident('i'))
        index = index_io.connect(self.root / 'index.db')
        index_io.put(index, [stray])
        index.execute('INSERT INTO index_vectors VALUES (?, ?)', (stray['id'], vectors[fourth['id']]))
        index.close()
        outcome = self.keep()
        self.assertEqual((outcome.reason, outcome.rebuilt), ('done', None))
        self.assertEqual(outcome.written, tuple(sorted((first['id'], second['id'], third['id']))))
        self.assertEqual(outcome.removed, (stray['id'],))
        # Only the items without a vector were embedded again: the changed one and the one without a row.
        self.assertEqual(sorted(outcome.embedded), sorted((second['id'], third['id'])))
        tables = self.tables()
        self.assertEqual({k: tables[k] for k in ('index_items', 'index_terms')}, self.expected())
        self.assertEqual(self.vectors(), vectors)

    # The gates

    def test_without_consent_or_for_a_disabled_or_deleted_project_nothing_is_read_or_sent(self):
        self.layer(self.made(2))
        before = self.snapshot()
        for reason, change in (('consent', lambda: self.configure(consent=None, models={'dims': DIMS})),
                               ('disabled', lambda: self.configure(enabled=False, models={'dims': DIMS}))):
            with self.subTest(reason=reason):
                change()
                self.assertEqual(self.keep().reason, reason)
                self.assertEqual(self.snapshot(), before)
        self.configure(models={'dims': DIMS})
        (self.root / 'layer/deleted.json').write_bytes(b'{}\n')
        self.assertEqual(self.keep().reason, 'deleted')
        self.assertFalse((self.root / 'index.db').exists())
        self.assertEqual(self.server.requests, [])

    def test_without_the_openai_memory_key_the_words_are_kept_and_nothing_is_sent(self):
        items = self.made(2)
        self.layer(items)
        with mock.patch.dict(os.environ, {'CORTHEX_MEMORY_OPENAI_API_KEY': ''}):
            outcome = self.keep()
        self.assertEqual((outcome.reason, outcome.rebuilt, outcome.requests), ('key', 'missing', 0))
        self.assertEqual({k: v for k, v in self.tables().items() if k in ('index_items', 'index_terms')},
                         self.expected())
        self.assertEqual((self.vectors(), self.server.requests, self.usage()), ({}, [], []))

    def test_a_lasting_failure_ends_the_step_and_is_noted(self):
        self.layer(self.made(150))
        self.server.reply = lambda number, body: worker_fixture.failing(401, 'authentication_error')
        outcome = self.keep()
        self.assertEqual((outcome.reason, outcome.requests, outcome.failed, outcome.embedded),
                         ('failed', 1, ('authentication_error',), ()))
        self.assertEqual(len(self.server.requests), 1)
        self.assertEqual(self.failures(), [('embed', 'authentication_error')])
        self.assertEqual(self.vectors(), {})

    def test_an_index_that_is_not_a_regular_file_is_refused_and_noted(self):
        self.layer(self.made(1))
        # A folder in its place: the index cannot be used, and nothing is sent.
        (self.root / 'index.db').mkdir()
        outcome = self.keep()
        self.assertEqual((outcome.reason, outcome.requests), ('error', 0))
        self.assertEqual(self.failures(), [('index', 'RuntimeError')])
        (self.root / 'index.db').rmdir()
        # A link, as the curation worker treats a link in the project folder: the lease is not trusted.
        outside = self.root.parent.parent / 'outside.db'
        outside.write_bytes(b'')
        try:
            (self.root / 'index.db').symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest('symbolic links are not available')
        outcome = self.keep()
        self.assertEqual((outcome.reason, outcome.requests), ('lost-lock', 0))
        self.assertEqual(self.failures()[1:], [('index', 'lost-lock')])
        self.assertEqual((outside.read_bytes(), self.server.requests), (b'', []))

    # The failure log's codes

    def test_the_failure_log_takes_every_model_call_code_of_stage_06_but_stale(self):
        api = (ROOT / 'docs/06-api/memory.md').read_text(encoding='utf-8')
        section = api.split('### Model calls', 1)[1].split('\n### ', 1)[0]
        rows = [line.split('|')[1:-1] for line in section.splitlines() if line.startswith('| ')][1:]
        codes = {row[0].strip().strip('`') for row in rows if row[0].strip().startswith('`')}
        types = set(re.findall(r'`([a-z_]+)`', [row for row in rows if 'error types' in row[0]][0][2]))
        self.assertEqual(diagnostics.MODEL, (codes | types) - {'stale', 'lost-lock'})
        self.assertEqual(diagnostics.MODEL, set(model_access._KINDS))

    def search(self, words):
        connection = index_io.connect(self.root / 'index.db')
        try:
            return [item for item, _ in index_io.search(connection, words)]
        finally:
            connection.close()


if __name__ == '__main__':
    unittest.main()
