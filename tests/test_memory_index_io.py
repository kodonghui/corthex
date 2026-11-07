"""TASK-081 search index on fabricated, already-migrated stores: words-1, BM25 and rebuilds.

No hook or command uses the index yet; vectors are fixture rows until TASK-082.
"""
import copy
import math
import os
from pathlib import Path
import sqlite3
import struct
import sys
import tempfile
import unittest
import unicodedata

from _common import ROOT
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import index_io, item_types, locks, worker_support
import test_memory_item_io as fixtures

MODEL, DIMS, WHEN = 'text-embedding-3-small', 512, '2026-11-07T06:00:00.000Z'


def item(identifier, kind, title, text, quoted, status='current', speaker='user'):
    quote = dict(fixtures.ITEM['quotes'][0], words=quoted, speaker=speaker, end=1 + len(quoted))
    return dict(copy.deepcopy(fixtures.ITEM), id=identifier, kind=kind, title=title, text=text,
                quotes=[quote], status=status)


# Made-up items with known words: A has 7 (raw 3, logs 2, keep, fact), B 5 and C 8.
A = item('i_0123456789aa', 'fact', 'raw logs', 'keep raw logs', 'raw')
B = item('i_0123456789bb', 'fact', 'memory', 'memory store', 'store', status='withdrawn', speaker='agent')
C = item('i_0123456789cc', 'lesson', '메모리', '메모리 저장', '저장 raw')


def rows(connection):
    """Every row of the three item tables, by table."""
    return {table: sorted(connection.execute('SELECT * FROM ' + table).fetchall())
            for table in ('index_items', 'index_vectors', 'index_terms')}


class WordsTest(unittest.TestCase):
    def test_tc137_stage_06_examples(self):
        self.assertEqual(index_io.words('Keep raw logs in memory.py'),
                         ['memory.py', 'keep', 'raw', 'logs', 'in', 'memory', 'py'])
        self.assertEqual(index_io.words('메모리 저장'), ['메모', '모리', '저장'])

    def test_tc137_identifiers_and_runs_at_their_edges(self):
        cases = {
            'x': ['x'], 'a.': ['a'], 'a1': ['a1', 'a1'], 'end.': ['end'],
            'a' * 99 + '1': ['a' * 99 + '1'] * 2, 'a' * 100 + '1': [], 'b' * 101: [], 'b' * 100: ['b' * 100],
            'memory.py.': ['memory.py', 'memory', 'py'], 'src/app/': ['src/app', 'src', 'app'],
            'REQ-001-': ['req-001', 'req', '001'], 'src/app/.-': ['src/app', 'src', 'app'],
            'getItem': ['getitem', 'getitem'], 'Keep': ['keep'], 'well-known': ['well', 'known'],
            '_x .env': ['_x', '.env', 'x', 'env'], '123-456': ['123', '456'], 'REQ-001을 getItem은': ['req-001', 'getitem', 'req', '001', '을', 'getitem', '은'],
            'CAFÉ Mémoire x1é': ['café', 'mémoire', 'x1é'],
            '저': ['저'], '메모리': ['메모', '모리'], '저 2026년 日本語です': ['저', '2026', '년', '日本', '本語', '語で', 'です'],
            'the a of': ['the', 'a', 'of'],
        }
        for text, expected in cases.items():
            with self.subTest(text=text[:20]):
                self.assertEqual(index_io.words(text), expected)

    def test_nfc_lower_case_and_combining_marks_stay_in_their_run(self):
        self.assertEqual(index_io.words('Café CAFÉ'), ['café', 'café'])
        self.assertEqual(index_io.words('İstanbul हिन्दी'), ['i̇stanbul', 'हिन्दी'])
        self.assertEqual(index_io.words(' ́x Ⅻ ²'), ['x'])
        self.assertEqual(index_io.words(unicodedata.normalize('NFD', '메모리')), ['메모', '모리'])
        with self.assertRaises(TypeError):
            index_io.words(b'raw')

    def test_an_items_words_come_from_its_kind_title_text_and_quotes(self):
        self.assertEqual(index_io.item_words(A), ['fact', 'raw', 'logs', 'keep', 'raw', 'logs', 'raw'])
        self.assertEqual(len(index_io.item_words(B)), 5)
        self.assertEqual(index_io.item_words(C), ['lesson', '메모', '모리', '메모', '모리', '저장', '저장', 'raw'])


class IndexTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name).resolve()
        self.path = self.folder / 'index.db'

    def made(self, items=(A, B, C)):
        connection = index_io.connect(self.path, create=True)
        self.addCleanup(connection.close)
        connection.executescript(index_io.DDL.read_text(encoding='utf-8'))
        index_io.put(connection, list(items))
        return connection

    def test_tc135_the_packaged_ddl_is_stage_05s_and_makes_its_schema(self):
        self.assertEqual(index_io.DDL.read_bytes(), (ROOT / 'docs/05-erd/memory-index.sql').read_bytes())
        other = sqlite3.connect(str(self.folder / 'stage.db'), isolation_level=None)
        self.addCleanup(other.close)
        other.executescript((ROOT / 'docs/05-erd/memory-index.sql').read_text(encoding='utf-8'))
        connection = self.made()
        for each in (other, connection):
            self.assertEqual(index_io._schema(each), index_io.schema())
            self.assertEqual(each.execute('PRAGMA user_version').fetchone(), (2,))
            self.assertEqual(each.execute('PRAGMA journal_mode').fetchone(), ('wal',))
        # Four tables, two named indexes and four automatic ones for the keys.
        self.assertEqual(len(index_io.schema()), 10)
        self.assertEqual(connection.execute('PRAGMA foreign_keys').fetchone(), (1,))
        self.assertEqual(connection.execute('PRAGMA secure_delete').fetchone(), (1,))

    def test_tc138_bm25_matches_the_example_computed_by_hand(self):
        connection = self.made()
        average = (7 + 5 + 8) / 3

        def part(weight, count, length):
            return weight * count * 2.2 / (count + 1.2 * (0.25 + 0.75 * length / average))
        raw, memory = math.log(1 + 1.5 / 2.5), math.log(1 + 2.5 / 1.5)
        expected = [(B['id'], part(memory, 2, 5)), (A['id'], part(raw, 3, 7)), (C['id'], part(raw, 1, 8))]
        for query in ('raw memory', 'Memory RAW raw', 'raw memory nothing-else-here'):
            with self.subTest(query=query):
                found = index_io.search(connection, query)
                self.assertEqual([key for key, _ in found], [key for key, _ in expected])
                for (_, score), (_, value) in zip(found, expected):
                    self.assertAlmostEqual(score, value, places=12)
        self.assertAlmostEqual(index_io.search(connection, '메모리')[0][1], 2 * part(memory, 2, 8), places=12)
        self.assertEqual(index_io.search(connection, 'raw memory', limit=1), expected[:1])
        self.assertEqual(index_io.search(connection, 'absent'), [])
        self.assertEqual(index_io.search(connection, '...'), [])
        self.assertEqual(rows(connection)['index_items'], sorted([
            (A['id'], 'fact', 'current', 'user', A['quotes'][0]['said'], 7),
            (B['id'], 'fact', 'withdrawn', 'agent', B['quotes'][0]['said'], 5),
            (C['id'], 'lesson', 'current', 'user', C['quotes'][0]['said'], 8)]))
        self.assertIn(('raw', A['id'], 3), rows(connection)['index_terms'])

    def test_put_keeps_the_vector_of_a_status_change_and_refuses_bad_rows_whole(self):
        connection = self.made()
        vector = struct.pack('<2f', 0.6, 0.8)
        connection.execute('INSERT INTO index_vectors VALUES (?, ?)', (A['id'], vector))
        index_io.put(connection, [dict(A, status='superseded', superseded_by=B['id'])])
        self.assertEqual(connection.execute('SELECT status FROM index_items WHERE item = ?', (A['id'],)).fetchone(),
                         ('superseded',))
        self.assertEqual(rows(connection)['index_vectors'], [(A['id'], vector)])
        before = rows(connection)
        with self.assertRaises(sqlite3.IntegrityError):
            index_io.put(connection, [dict(A, status='current'), dict(B, status='unknown')])
        self.assertEqual(rows(connection), before)

    def test_tc140_deleting_items_clears_every_index_table_and_a_forget_empties_the_log(self):
        marker = item('i_0123456789dd', 'fact', 'forgotten-marker-7c1d title', 'private words 7c1d', 'quoted 7c1d')
        connection = self.made((A, B, C, marker))
        for key in (A['id'], marker['id']):
            connection.execute('INSERT INTO index_vectors VALUES (?, ?)', (key, struct.pack('<2f', 1, 0)))
        index_io.delete(connection, [A['id']])
        self.assertTrue(index_io.delete(connection, [marker['id']], forget=True))
        found = rows(connection)
        for table, values in found.items():
            with self.subTest(table=table):
                self.assertFalse([row for row in values if A['id'] in row or marker['id'] in row])
        self.assertEqual({row[0] for row in found['index_items']}, {B['id'], C['id']})
        self.assertEqual(index_io.search(connection, 'raw')[0][0], C['id'])
        self.assertEqual(os.path.getsize(str(self.path) + '-wal'), 0)
        self.assertNotIn(b'7c1d', self.path.read_bytes())

    def test_a_reader_never_creates_an_index(self):
        with self.assertRaises(sqlite3.OperationalError):
            index_io.connect(self.path)
        self.assertFalse(self.path.exists())


class RebuildTest(unittest.TestCase):
    def setUp(self):
        # The TASK-076 store fixture: a format-2 store with one saved item and the layer lease.
        self.fixture = fixtures.ItemIOTest('test_add_and_transition_preserve_every_immutable_provenance_field')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.memory, self.project, self.deadline = self.fixture.memory, self.fixture.project, self.fixture.deadline
        for value in (A, B, C):
            self.fixture.item_path(value['id']).write_bytes(item_types.item_bytes(value))
        self.index = self.project / 'index.db'

    def held(self):
        return self.fixture.held()

    def proof(self):
        return self.fixture.proof()

    def ensure(self, model=MODEL, dims=DIMS):
        with self.held():
            return index_io.ensure(self.memory, self.project, self.proof(), self.deadline,
                                   model=model, dims=dims, when=WHEN)

    def opened(self):
        connection = index_io.open_index(self.memory, self.project)
        self.addCleanup(connection.close)
        return connection

    def expected(self):
        canonical = [item_types.parse_item(path.read_bytes())
                     for path in sorted((self.project / 'layer/items').glob('*.json'))]
        other = index_io.connect(self.project.parent / 'expected.db', create=True)
        self.addCleanup(other.close)
        other.executescript(index_io.DDL.read_text(encoding='utf-8'))
        index_io.put(other, canonical)
        return rows(other)

    def test_missing_malformed_and_obsolete_indexes_rebuild_from_canonical_items(self):
        self.assertIsNone(index_io.open_index(self.memory, self.project))
        self.assertEqual(self.ensure(), 'missing')
        expected = self.expected()

        def changed(statement):
            connection = index_io.connect(self.index)
            try:
                connection.execute(statement)
            finally:
                connection.close()
        cases = [('malformed', lambda: self.index.write_bytes(b'not an index')),
                 ('malformed', lambda: self.index.write_bytes(self.index.read_bytes()[:100])),
                 ('version', lambda: changed('PRAGMA user_version = 1')),
                 ('schema', lambda: changed('CREATE TABLE extra (x)')),
                 ('schema', lambda: changed('DROP INDEX index_terms_item')),
                 ('words', lambda: changed("UPDATE index_meta SET value = 'words-0' WHERE name = 'words'")),
                 ('malformed', lambda: changed("DELETE FROM index_meta WHERE name = 'words'")),
                 ('building', lambda: changed("DELETE FROM index_meta WHERE name = 'built'")),
                 ('embedding', lambda: changed("UPDATE index_meta SET value = 'other' WHERE name = 'embedding_model'")),
                 ('embedding', lambda: changed("UPDATE index_meta SET value = '256' WHERE name = 'embedding_dims'"))]
        for reason, damage in cases:
            with self.subTest(reason=reason):
                damage()
                (self.project / 'index.db-wal').write_bytes(b'stale log of another index')
                self.assertEqual(self.ensure(), reason)
                connection = self.opened()
                self.assertIsNone(index_io.state(connection, model=MODEL, dims=DIMS))
                self.assertEqual(rows(connection), expected)
                self.assertEqual(dict(connection.execute('SELECT * FROM index_meta').fetchall()),
                                 dict(embedding_model=MODEL, embedding_dims=str(DIMS), words='words-1', built=WHEN))
                connection.close()
        before = self.index.stat()
        self.assertIsNone(self.ensure())
        self.assertEqual((self.index.stat().st_ino, self.index.stat().st_mtime_ns), (before.st_ino, before.st_mtime_ns))
        self.assertEqual(self.ensure(dims=256), 'embedding')

    def test_a_damaged_table_page_is_malformed_and_rebuilt(self):
        self.assertEqual(self.ensure(), 'missing')
        expected = self.expected()
        for table in ('index_terms', 'index_items'):
            with self.subTest(table=table):
                connection = self.opened()
                size = connection.execute('PRAGMA page_size').fetchone()[0]
                page = connection.execute('SELECT rootpage FROM sqlite_master WHERE name = ?', (table,)).fetchone()[0]
                connection.close()
                data = bytearray(self.index.read_bytes())
                data[(page - 1) * size:page * size] = bytes(size)
                self.index.write_bytes(bytes(data))
                connection = self.opened()
                # The schema and index_meta still read; only the table's own page is damaged.
                self.assertEqual(index_io._schema(connection), index_io.schema())
                with self.assertRaises(sqlite3.DatabaseError):
                    index_io.search(connection, 'raw')
                self.assertEqual(index_io.state(connection, model=MODEL, dims=DIMS), 'malformed')
                connection.close()
                self.assertEqual(self.ensure(), 'malformed')
                connection = self.opened()
                self.assertIsNone(index_io.state(connection, model=MODEL, dims=DIMS))
                self.assertEqual(rows(connection), expected)
                connection.close()

    def test_a_rebuild_leaves_out_forgotten_items_and_needs_the_layer_lease(self):
        (self.project / 'layer/tombstones' / (C['id'] + '.json')).write_bytes(b'{}\n')
        self.assertEqual(self.ensure(), 'missing')
        self.assertEqual({row[0] for row in rows(self.opened())['index_items']}, {A['id'], B['id'], fixtures.FIRST})
        self.index.write_bytes(b'not an index')
        with self.assertRaises(locks.LostLock):
            index_io.rebuild(self.memory, self.project, self.proof(), self.deadline, model=MODEL, dims=DIMS, when=WHEN)
        self.assertEqual(self.index.read_bytes(), b'not an index')

    @unittest.skipIf(os.name == 'nt', 'symbolic links need privileges on Windows')
    def test_a_linked_index_file_is_refused_and_kept(self):
        target = self.project.parent / 'elsewhere.db'
        target.write_bytes(b'kept')
        for name in ('index.db', 'index.db-wal'):
            with self.subTest(name=name):
                link = self.project / name
                link.symlink_to(target)
                with self.assertRaises(worker_support.UnsafePath):
                    index_io.open_index(self.memory, self.project)
                with self.assertRaises(worker_support.UnsafePath):
                    self.ensure()
                self.assertTrue(link.is_symlink())
                link.unlink()
        self.assertEqual(target.read_bytes(), b'kept')
        self.index.mkdir()
        with self.assertRaises(index_io.IndexUnavailable):
            self.ensure()
        self.assertTrue(self.index.is_dir())


if __name__ == '__main__':
    unittest.main()
