"""TASK-040: the search command (API-021 with API-012; SPEC-025, SPEC-004).

TC-221, TC-224, TC-225 and TC-226, and the search parts of TC-136, TC-222 and
TC-366, at the handler's boundary, on made-up format-2 stores. Every embedding
request goes to a local test server, with keys made up during the run; no
provider is called. The runner hands `search` to no handler before the 0.3.0
activation (test_memory_item_commands checks it), so these are the handler's
own results, called as the runner will call it.
"""
import json
import os
import secrets
import sqlite3
import struct
import sys
import types
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import clock, commands, files, index_io, item_types, run_listing, search_command
import test_memory_curation_worker as worker_fixture
import test_memory_item_commands as item_fixture
import test_memory_recall as recall_fixture

AT, DEVICE = worker_fixture.AT, worker_fixture.DEVICE
MODEL, DIMS, PROMPT = recall_fixture.MODEL, recall_fixture.DIMS, recall_fixture.PROMPT
toward, ident = recall_fixture.toward, worker_fixture.ident
EXAMPLES = item_fixture.EXAMPLES
ASIDE = [0.0] * (DIMS - 1) + [1.0]  # a request's vector whose cosine with every item's below is 0


class SearchCommandTest(unittest.TestCase):
    Fixture, Ranking, Items = worker_fixture.CurationWorkerTest, recall_fixture.RecallTest, item_fixture.ItemCommandsTest
    configure, layer, saved, one_turn, items, write, snapshot, usage, failures = (
        Fixture.configure, Fixture.layer, Fixture.saved, Fixture.one_turn, Fixture.items, Fixture.write,
        Fixture.snapshot, Fixture.usage, Fixture.failures)
    item, index, vectors, store = Ranking.item, Ranking.index, Ranking.vectors, Ranking.store
    tombstone, held = Items.tombstone, Items.held

    def setUp(self):
        self.Fixture.setUp(self)
        self.keys['CORTHEX_MEMORY_OPENAI_API_KEY'] = 'memory-openai-key-' + secrets.token_hex(12)
        self.keys['CORTHEX_MEMORY_OPENAI_BASE_URL'] = self.server.url
        environment = mock.patch.dict(os.environ, {name: self.keys[name] for name in (
            'CORTHEX_MEMORY_OPENAI_API_KEY', 'CORTHEX_MEMORY_OPENAI_BASE_URL')})
        environment.start()
        self.addCleanup(environment.stop)
        self.configure(models={'dims': DIMS})
        self.said, _ = self.one_turn()
        self.answer = list(PROMPT)  # the request's vector that the test server gives
        self.server.reply = self.embeddings

    def embeddings(self, number, body):
        document = {'object': 'list', 'model': body['model'], 'usage': {'prompt_tokens': 7},
                    'data': [{'object': 'embedding', 'index': 0, 'embedding': self.answer}]}
        return lambda handler: worker_fixture.Server.send(handler, json.dumps(document).encode('utf-8'),
                                                          mime='application/json')

    def search(self, words, project='sample', **arguments):
        arguments = dict({'words': words, 'limit': 20, 'words_only': False, 'kind': None}, **arguments)
        context = commands.Context('search', dict(arguments, folder=str(self.root)), None, self.memory)
        context.project = types.SimpleNamespace(name=project)
        context.record = {'device': DEVICE}
        context.configuration = self.memory.configuration(deadline=clock.now() + 10)
        value = search_command.search(context)
        commands.validate_result(value, 'search')
        return value

    def result(self, value):
        return dict(run_listing.list_line(value), status=value['status'])

    def ranked(self, words):
        """BM25 by words over the project's index, as index_io gives it."""
        connection = index_io.connect(self.root / 'index.db')
        try:
            return [item for item, _ in index_io.search(connection, words)]
        finally:
            connection.close()

    def four(self):
        """Items whose words and vectors rank them differently for 'raw logs device'."""
        values = [self.item('Raw logs stay on the device', text='Raw logs stay on this device.'),
                  self.item('Logs of hooks', text='Hook logs rotate daily.'),
                  self.item('Curation runs detached', text='One background process curates.'),
                  self.item('The device keeps its raw logs and raw entries', kind='decision',
                            text='Raw logs, raw entries and the device.')]
        cosines = (0.3, 0.9, 0.6, -0.2)
        return self.store(*[(value, toward(cosine, 1 + number % 3))
                            for number, (value, cosine) in enumerate(zip(values, cosines))]), cosines

    # SPEC-025's second acceptance criterion: by words without the key or consent (TC-221)

    def test_tc221_without_the_key_or_consent_or_with_words_only_it_searches_by_words_and_sends_nothing(self):
        values, _ = self.four()
        expected = [self.result(value) for value in values if value['id'] in self.ranked('raw logs device')]
        expected.sort(key=lambda line: self.ranked('raw logs device').index(line['item']))
        self.assertEqual(len(expected), 3)
        cases = [('no-key', "since CORTHEX_MEMORY_OPENAI_API_KEY is missing"),
                 ('no-consent', 'since memory has no consent to send search requests'),
                 ('asked', 'as asked')]
        for reason, why in cases:
            with self.subTest(reason=reason):
                arguments = {}
                if reason == 'no-key':
                    patch = mock.patch.dict(os.environ, {'CORTHEX_MEMORY_OPENAI_API_KEY': ''})
                elif reason == 'no-consent':
                    self.configure(consent=None, models={'dims': DIMS})
                    patch = mock.patch.dict(os.environ, {})
                else:
                    self.configure(models={'dims': DIMS})
                    arguments['words_only'] = True
                    patch = mock.patch.dict(os.environ, {})
                with patch:
                    found = self.search('raw logs device', **arguments)
                self.assertEqual((found['outcome'], found['code']), ('done', 'ok'))
                self.assertEqual(found['data'], {'project': 'sample', 'by': 'words', 'reason': reason,
                                                 'results': expected})
                self.assertEqual(found['say'], 'Searched by words only, %s; 3 items found.' % why)
        self.assertEqual((self.server.requests, self.usage()), ([], []))

    def test_without_the_key_the_reason_is_no_key_even_without_an_index(self):
        self.four()
        (self.root / 'index.db').unlink()
        with mock.patch.dict(os.environ, {'CORTHEX_MEMORY_OPENAI_API_KEY': ''}):
            found = self.search('raw logs device')
        self.assertEqual((found['data']['by'], found['data']['reason'], len(found['data']['results'])),
                         ('words', 'no-key', 3))
        self.assertEqual(self.server.requests, [])

    def test_the_example_says_what_the_search_says(self):
        example = EXAMPLES['search-by-words']
        values = []
        for line in example['data']['results']:
            value = self.item(line['title'], kind=line['kind'], status=line['status'])
            value['id'] = line['item']
            values.append(value)
        self.store(*[(value, None) for value in values])
        with mock.patch.dict(os.environ, {'CORTHEX_MEMORY_OPENAI_API_KEY': ''}):
            found = self.search('raw logs')
        self.assertEqual(found['say'], example['say'])
        self.assertEqual(sorted(line['item'] for line in found['data']['results']),
                         sorted(line['item'] for line in example['data']['results']))

    # By words and by meaning (TC-224)

    def test_tc224_by_words_and_meaning_each_item_scores_the_sum_of_its_two_reciprocal_ranks(self):
        values, cosines = self.four()
        by_words = self.ranked('raw logs device')
        by_meaning = [value['id'] for value, cosine in sorted(zip(values, cosines), key=lambda pair: -pair[1])
                      if cosine > 0]
        scores = {}
        for ranking in (by_words, by_meaning):
            for rank, item in enumerate(ranking, 1):
                scores[item] = scores.get(item, 0) + 1 / (60 + rank)
        expected = sorted(scores, key=lambda item: (-scores[item], item))
        self.assertEqual(len(expected), 4)
        found = self.search('raw logs device')
        self.assertEqual((found['outcome'], found['data']['by']), ('done', 'both'))
        self.assertNotIn('reason', found['data'])
        self.assertEqual([line['item'] for line in found['data']['results']], expected)
        self.assertEqual(found['data']['results'], [self.result(next(v for v in values if v['id'] == item))
                                                    for item in expected])
        self.assertEqual(found['say'], 'Searched by words and meaning; 4 items found.')
        # One request, with the configured model and vector length, and its usage line.
        self.assertEqual(len(self.server.requests), 1)
        headers, body = self.server.requests[0]
        self.assertEqual((body['model'], body['dimensions'], body['input']), (MODEL, DIMS, ['raw logs device']))
        self.assertEqual(headers['authorization'], 'Bearer ' + self.keys['CORTHEX_MEMORY_OPENAI_API_KEY'])
        usage = self.usage()
        self.assertEqual([(line['call'], line['project'], line['input']) for line in usage],
                         [('embed-search', 'sample', 7)])
        # Words that no item has, and a request whose vector is aside from every item's: ok, with no results.
        self.answer = ASIDE
        none = self.search('zebra quartz')
        self.assertEqual((none['outcome'], none['code'], none['data']['by'], none['data']['results']),
                         ('nothing', 'ok', 'both', []))
        self.assertEqual(none['say'], 'Searched by words and meaning; no item found.')
        # The limit keeps the best, and --kind ranks only that kind's items.
        self.answer = list(PROMPT)
        self.assertEqual([line['item'] for line in self.search('raw logs device', limit=2)['data']['results']],
                         expected[:2])
        decision = self.search('raw logs device', kind='decision')
        self.assertEqual([line['item'] for line in decision['data']['results']], [values[3]['id']])
        self.assertEqual(decision['say'], 'Searched by words and meaning; 1 item found.')

    def test_fused_adds_one_over_60_plus_each_rank_and_breaks_ties_by_id(self):
        # a: 1/61 + 1/64, b: 2/62, c: 1/63 + 1/61, d: 1/64 + 1/63; a smaller constant would put a before b.
        self.assertEqual(search_command.fused(['a', 'b', 'c', 'd'], ['c', 'b', 'd', 'a']), ['c', 'b', 'a', 'd'])
        self.assertEqual(search_command.fused(['b'], ['a']), ['a', 'b'])
        self.assertEqual(search_command.fused(['b', 'a'], []), ['b', 'a'])

    def test_with_a_kind_both_rankings_hold_only_items_of_that_kind(self):
        values, _ = self.four()
        connection = index_io.connect(self.root / 'index.db')
        try:
            ranked = search_command._rank(connection, 'raw logs device', PROMPT, 'decision', DIMS,
                                          {value['id'] for value in values}, clock.now() + 10)
        finally:
            connection.close()
        self.assertEqual(ranked, ([values[3]['id']], []))

    def test_vectors_of_another_length_zero_or_not_finite_count_for_no_meaning(self):
        values, _ = self.four()
        connection = sqlite3.connect(str(self.root / 'index.db'), isolation_level=None)
        try:
            for value, data in ((values[0], struct.pack('<%df' % DIMS, *[float('nan')] * DIMS)),
                                (values[1], b'\x00' * 4), (values[2], struct.pack('<%df' % DIMS, *[0.0] * DIMS))):
                connection.execute('UPDATE index_vectors SET vector = ? WHERE item = ?', (data, value['id']))
        finally:
            connection.close()
        # The decision keeps its vector, whose cosine is below 0: the meaning ranks nothing.
        found = self.search('raw logs device')
        self.assertEqual(found['data']['by'], 'both')
        self.assertEqual([line['item'] for line in found['data']['results']], self.ranked('raw logs device'))

    def test_a_damaged_page_that_the_index_check_does_not_read_searches_by_words_from_the_items(self):
        self.four()
        expected = self.ranked('raw logs device')
        connection = sqlite3.connect(str(self.root / 'index.db'), isolation_level=None)
        try:
            connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            size = connection.execute('PRAGMA page_size').fetchone()[0]
            pages = [row[0] for row in connection.execute(
                "SELECT rootpage FROM sqlite_master WHERE tbl_name = 'index_terms' AND rootpage > 0")]
        finally:
            connection.close()
        with open(str(self.root / 'index.db'), 'r+b') as stream:
            for page in pages:
                stream.seek((page - 1) * size)
                stream.write(b'\xff' * size)
        found = self.search('raw logs device')
        self.assertEqual((found['data']['by'], found['data']['reason']), ('words', 'index-not-ready'))
        self.assertEqual([line['item'] for line in found['data']['results']], expected)

    def test_tc222_tc366_items_of_every_status_are_found_and_marked(self):
        current = self.item('Current hooks plan')
        values = [current] + [self.item('%s hooks plan' % status.title(), status=status)
                              for status in ('superseded', 'withdrawn', 'undone')]
        self.store(*[(value, toward(0.5 + number / 10)) for number, value in enumerate(values)])
        found = self.search('hooks plan')
        self.assertEqual(sorted((line['item'], line['status']) for line in found['data']['results']),
                         sorted((value['id'], value['status']) for value in values))
        withdrawn = self.search('withdrawn hooks', words_only=True)
        self.assertEqual(withdrawn['data']['results'][0], self.result(values[2]))

    # A failed embedding (TC-225) and the redacted request (TC-226)

    def test_tc225_a_failed_embedding_searches_by_words_and_the_failure_log_notes_it(self):
        values, _ = self.four()
        words = [line for line in self.ranked('raw logs device')]
        cases = [('bad-vector', lambda: setattr(self, 'answer', list(PROMPT)[:-1])),
                 ('bad-vector', lambda: setattr(self, 'answer', [0.0] * DIMS)),
                 ('bad-answer', lambda: setattr(self.server, 'reply', lambda number, body: lambda handler:
                                                worker_fixture.Server.send(handler, b'not json',
                                                                           mime='application/json'))),
                 ('api_error', lambda: setattr(self.server, 'reply', lambda number, body:
                                               worker_fixture.failing(500, 'api_error'))),
                 ('authentication_error', lambda: setattr(self.server, 'reply', lambda number, body:
                                                          worker_fixture.failing(401, 'authentication_error')))]
        for code, arrange in cases:
            with self.subTest(code=code):
                self.server.reply = self.embeddings
                arrange()
                found = self.search('raw logs device')
                self.assertEqual((found['data']['by'], found['data']['reason']), ('words', 'embedding-failed'))
                self.assertEqual([line['item'] for line in found['data']['results']], words)
                self.assertEqual(found['say'], "Searched by words only, since the search request's embedding "
                                               "failed; 3 items found.")
        # One attempt each, with no retry, each with its usage line, and the failure log notes each code.
        self.assertEqual(len(self.server.requests), len(cases))
        self.assertEqual([line['error'] for line in self.usage()], [code for code, _ in cases])
        self.assertEqual(self.failures(), [('embed', code) for code, _ in cases])

    def test_a_failed_embedding_is_logged_even_when_the_lease_is_then_busy(self):
        self.four()
        self.answer = list(PROMPT)[:-1]
        with mock.patch.object(search_command, 'WAIT', 0.2), self.held('layer.lock', 'layer'):
            value = self.search('raw logs device')
        self.assertEqual((value['code'], value['outcome']), ('lock-busy', 'failed'))
        self.assertEqual(self.failures(), [('embed', 'bad-vector')])

    def test_a_request_that_redaction_refuses_is_not_sent_and_searches_by_words(self):
        self.four()
        with mock.patch.object(search_command.model_embed, 'prepare', side_effect=ValueError('unsafe')):
            found = self.search('raw logs device')
        self.assertEqual((found['data']['by'], found['data']['reason']), ('words', 'embedding-failed'))
        self.assertEqual((self.server.requests, self.usage()), ([], []))
        self.assertEqual(self.failures(), [('embed', 'ValueError')])

    def test_tc226_the_search_request_is_redacted_and_holds_nothing_else(self):
        values, _ = self.four()
        made_up = 'sk-ant-' + secrets.token_hex(16)
        words = 'raw logs device <private>my street address</private> with ' + made_up + ' and ' + \
            self.keys['CORTHEX_MEMORY_OPENAI_API_KEY']
        found = self.search(words)
        self.assertEqual(found['data']['by'], 'both')
        headers, body = self.server.requests[0]
        self.assertEqual(set(body), {'model', 'input', 'dimensions', 'encoding_format'})
        self.assertEqual(body['input'], ['raw logs device [redacted:private] with [redacted:anthropic-key] and '
                                         '[redacted:memory-key]'])
        sent = json.dumps(body)
        for secret in (made_up, 'my street address', self.keys['CORTHEX_MEMORY_OPENAI_API_KEY'],
                       self.keys['CORTHEX_MEMORY_ANTHROPIC_API_KEY']):
            self.assertNotIn(secret, sent)
        raw = (self.root / 'raw' / (self.raw.name + '.jsonl')).read_text(encoding='utf-8')
        for value in values:
            self.assertNotIn(value['title'], sent)
            self.assertNotIn(value['text'], sent)
        self.assertNotIn(self.said['text'], sent)
        self.assertIn(self.said['text'], raw)

    # The index (TC-136's search part)

    def test_tc136_an_index_that_cannot_give_vectors_searches_by_words_and_sends_nothing(self):
        values, _ = self.four()
        expected = self.ranked('raw logs device')
        cases = [('another model', lambda: self.configure(models={'dims': DIMS, 'embedding': 'text-embedding-3-large'})),
                 ('another length', lambda: self.configure(models={'dims': 128})),
                 ('being built', lambda: self.meta("DELETE FROM index_meta WHERE name = 'built'")),
                 ('another word splitting', lambda: self.meta("UPDATE index_meta SET value = 'words-0' "
                                                             "WHERE name = 'words'")),
                 ('another version', lambda: self.meta('PRAGMA user_version = 1')),
                 ('damaged', lambda: (self.root / 'index.db').write_bytes(b'not an index')),
                 ('missing', lambda: (self.root / 'index.db').unlink())]
        for name, arrange in cases:
            with self.subTest(index=name):
                self.configure(models={'dims': DIMS})
                self.index()
                self.vectors([(value, toward(0.5)) for value in values])
                arrange()
                before = self.snapshot()
                found = self.search('raw logs device')
                self.assertEqual((found['data']['by'], found['data']['reason']), ('words', 'index-not-ready'))
                self.assertEqual([line['item'] for line in found['data']['results']], expected)
                self.assertEqual(found['say'], 'Searched by words only, since the search index has no vectors '
                                               'of the configured model yet; 3 items found.')
                self.assertEqual(self.snapshot(), before)
        self.assertEqual((self.server.requests, self.usage()), ([], []))

    def meta(self, statement):
        connection = sqlite3.connect(str(self.root / 'index.db'), isolation_level=None)
        try:
            connection.execute(statement)
        finally:
            connection.close()

    def test_an_index_rebuilt_while_the_request_waits_searches_by_words(self):
        values, _ = self.four()
        expected = self.ranked('raw logs device')

        def gone(number, body):
            (self.root / 'index.db').unlink()
            return self.embeddings(number, body)
        self.server.reply = gone
        found = self.search('raw logs device')
        self.assertEqual((found['data']['by'], found['data']['reason']), ('words', 'index-not-ready'))
        self.assertEqual([line['item'] for line in found['data']['results']], expected)
        self.assertEqual(len(self.server.requests), 1)

    def test_rows_of_forgotten_items_and_of_items_without_a_file_are_left_out(self):
        values, cosines = self.four()
        # The index still holds both rows: a stopped forget's tombstone, and an item whose file went.
        self.tombstone(values[0], backup=True)
        (self.root / 'layer/items' / (values[2]['id'] + '.json')).unlink()
        found = self.search('raw logs device')
        by_words = [item for item in self.ranked('raw logs device') if item in (values[1]['id'], values[3]['id'])]
        by_meaning = [values[1]['id']]  # values[3] has a negative cosine
        scores = {}
        for ranking in (by_words, by_meaning):
            for rank, item in enumerate(ranking, 1):
                scores[item] = scores.get(item, 0) + 1 / (60 + rank)
        self.assertEqual([line['item'] for line in found['data']['results']],
                         sorted(scores, key=lambda item: (-scores[item], item)))
        words = self.search('raw logs device', words_only=True)
        self.assertEqual([line['item'] for line in words['data']['results']], by_words)

    def test_an_item_file_that_cannot_be_read_raises(self):
        values, _ = self.four()
        path = self.root / 'layer/items' / (values[3]['id'] + '.json')
        path.write_bytes(b'{')
        with self.assertRaises(files.RestoreNeeded):
            self.search('raw logs device', words_only=True)
        # A file that holds another item.
        path.write_bytes(item_types.item_bytes(values[1]))
        with self.assertRaises(files.RestoreNeeded):
            self.search('raw logs device', words_only=True)

    def test_each_result_is_what_its_file_says_when_its_index_row_is_older(self):
        values, _ = self.four()
        # The decision's file now says fact, which its index row does not know until step 6 writes it again.
        (self.root / 'layer/items' / (values[3]['id'] + '.json')).write_bytes(
            item_types.item_bytes(dict(values[3], kind='fact', title='Now a fact')))
        decisions = self.search('raw logs device', kind='decision', words_only=True)
        self.assertEqual((decisions['outcome'], decisions['data']['results']), ('nothing', []))
        found = self.search('raw logs device', words_only=True)
        line = next(line for line in found['data']['results'] if line['item'] == values[3]['id'])
        self.assertEqual((line['kind'], line['title']), ('fact', 'Now a fact'))

    def test_a_project_without_a_folder_or_being_deleted_finds_nothing_and_sends_nothing(self):
        self.four()
        other = self.search('raw logs device', project='other')
        self.assertEqual((other['outcome'], other['data']), ('nothing', {
            'project': 'other', 'by': 'words', 'reason': 'index-not-ready', 'results': []}))
        (self.root / 'layer/deleted.json').write_bytes(b'{}\n')
        before = self.snapshot()
        deleted = self.search('raw logs device')
        self.assertEqual((deleted['outcome'], deleted['data']['results'], deleted['data']['reason']),
                         ('nothing', [], 'index-not-ready'))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.server.requests, [])

    def test_search_arguments_outside_the_schema_are_usage(self):
        for arguments in ({'words': ''}, {'words': '  \n'}, {'words': 7}, {'kind': 'note'}, {'limit': 0},
                          {'limit': True}, {'words_only': 'yes'}):
            with self.subTest(arguments=arguments):
                values = dict({'words': 'raw logs', 'limit': 20, 'words_only': False, 'kind': None}, **arguments)
                context = commands.Context('search', values, None, self.memory)
                context.project = types.SimpleNamespace(name='sample')
                context.configuration = self.memory.configuration(deadline=clock.now() + 10)
                value = search_command.search(context)
                self.assertEqual((value['outcome'], value['code']), ('refused', 'usage'))
        self.assertEqual(self.server.requests, [])

    def test_a_layer_lease_held_past_the_wait_is_lock_busy(self):
        self.four()
        before = self.snapshot()
        with mock.patch.object(search_command, 'WAIT', 0.2), self.held('layer.lock', 'layer'):
            started = clock.now()
            value = self.search('raw logs device', words_only=True)
            self.assertEqual((value['code'], value['outcome']), ('lock-busy', 'failed'))
            self.assertLess(clock.now() - started, 5)
        with self.held('curation.lock', 'curation'):
            self.assertEqual(self.search('raw logs device', words_only=True)['code'], 'ok')
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.memory.held, [])


if __name__ == '__main__':
    unittest.main()
