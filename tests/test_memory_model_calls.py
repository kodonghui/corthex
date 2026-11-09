"""TASK-080: token counts (API-009) and OpenAI embeddings (API-010 to API-012) against loopback servers.

TC-126, TC-127 and TC-129, and the TASK-080 parts of TC-122, TC-124, TC-130,
TC-131 and TC-132. No real API is called; every key is a made-up value.
"""
from datetime import datetime, timezone
import inspect
import json
import math
import os
import socket
import struct
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

from _common import ROOT
import test_memory_model_transport as transport_fixture
import test_memory_model_usage as usage_fixture
import test_memory_status as status_fixture
from test_memory_model_client import DOCUMENT, RELEASE
from test_memory_model_stream import SCHEMA, start, block, end
sys.path.insert(0, str(ROOT/'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import (clock, configuration, locks, model_access, model_client, model_count, model_embed,
                        model_request, model_transport, model_usage, status)

KEY = transport_fixture.KEY
OPENAI = 'fixture-private-openai-memory-key-5d2e'
DIMS = 64
CONFIG = {'models': {'dims': DIMS}}
PRICE = configuration.prepare({}, temporary=False).values['prices']['models']['text-embedding-3-small']['input']


def numbers(first=3.0, second=4.0):
    return [first, second] + [0.0] * (DIMS - 2)


def document(*vectors, tokens=11):
    return {'object': 'list', 'model': 'text-embedding-3-small',
            'data': [{'object': 'embedding', 'index': index, 'embedding': vector}
                     for index, vector in enumerate(vectors)],
            'usage': {'prompt_tokens': tokens, 'total_tokens': tokens}}


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


class ModelCallsTest(unittest.TestCase):
    def setUp(self):
        self.transport = transport_fixture.ModelTransportTest(); self.transport.setUp()
        self.addCleanup(self.transport.doCleanups)
        self.usage = usage_fixture.ModelUsageTest(); self.usage.setUp(); self.addCleanup(self.usage.doCleanups)
        self.base = 'http://127.0.0.1:' + str(self.transport.server.server_port)
        self.environment = mock.patch.dict(os.environ, {
            'CORTHEX_MEMORY_ANTHROPIC_API_KEY': KEY, 'CORTHEX_MEMORY_OPENAI_API_KEY': OPENAI,
            'ANTHROPIC_API_KEY': 'general-fixture-key-380f', 'OPENAI_API_KEY': 'general-fixture-key-77a1',
            'CORTHEX_MEMORY_ANTHROPIC_BASE_URL': self.base, 'CORTHEX_MEMORY_OPENAI_BASE_URL': self.base})
        self.environment.start(); self.addCleanup(self.environment.stop)
        self.reply(document(numbers()))

    def reply(self, value, status=200, headers=None, mime='application/json'):
        raw = value if isinstance(value, bytes) else json.dumps(value).encode('utf-8')
        self.transport.reply = lambda handler: self.transport.send(handler, raw, status=status, headers=headers,
                                                                   mime=mime)

    def replies(self, *handlers):
        self.transport.reply = lambda handler: handlers[min(len(self.transport.requests), len(handlers)) - 1](handler)

    def json(self, value, status=200, headers=None):
        raw = value if isinstance(value, bytes) else json.dumps(value).encode('utf-8')
        return lambda handler: self.transport.send(handler, raw, status=status, headers=headers,
                                                   mime='application/json')

    def embed(self, call='embed-items', texts=('Keep the four hooks in one script.',), *, deadline=None,
              check=lambda: None, config=CONFIG, project='sample', **options):
        return model_embed.embed(self.usage.memory, project=project, call=call, texts=list(texts), config=config,
                                 check=check, deadline=clock.now() + 600 if deadline is None else deadline,
                                 **options)

    def count(self, **options):
        arguments = dict(project='sample', instructions='curate-3', source=DOCUMENT, schema=SCHEMA, config={},
                         check=lambda: None)
        arguments.update(options)
        return model_count.count(self.usage.memory, **arguments)

    def rows(self):
        return [json.loads(line) for path in sorted((self.usage.folder/'logs').glob('usage-*.jsonl'))
                for line in path.read_bytes().splitlines()]

    def unpack(self, vector):
        return struct.unpack('<%df' % DIMS, vector)

    # API-009

    def test_tc127_a_count_sends_the_request_body_less_max_tokens_and_stream(self):
        self.reply({'input_tokens': 61234})
        result = self.count()
        self.assertEqual((result.tokens, result.failure, result.logged), (61234, None, 1))
        (path, headers, body), = self.transport.requests
        sent, _ = model_request.build(config={}, instructions='curate-3', source=DOCUMENT, schema=SCHEMA,
                                      credentials=model_access.Credentials.read(), environment=dict(os.environ))
        expected = dict(sent['body']); del expected['max_tokens'], expected['stream']
        self.assertEqual((path, body), ('/v1/messages/count_tokens', expected))
        headers = {name.lower(): value for name, value in headers.items()}
        self.assertEqual((headers['x-api-key'], headers['anthropic-version'], headers['content-type'],
                          headers['user-agent']), (KEY, '2026-10-21', 'application/json', 'corthex-memory/' + RELEASE))
        self.assertNotIn('authorization', headers)
        row, = self.rows()
        self.assertEqual((row['call'], row['model'], row['input'], row['cost'], row['result'], row['instructions'],
                          row['request']), ('count-tokens', 'claude-haiku-5-5', 61234, 0, 'ok', 'curate-3',
                                            'req_fixture'))
        self.assertNotIn('output', row)

    def test_tc127_a_failed_or_late_count_is_not_tried_again(self):
        self.reply({'error': {'type': 'api_error', 'message': 'fixture-count-error-marker'}}, status=500)
        result = self.count()
        self.assertEqual((result.tokens, result.failure.code, result.logged, len(self.transport.requests)),
                         (None, 'api_error', 1, 1))
        def stall(handler):
            time.sleep(1.5)
            self.transport.send(handler, b'{"input_tokens": 5}', mime='application/json')
        self.transport.reply = stall
        result = self.count(deadline=clock.now() + .5)
        self.assertEqual((result.tokens, result.failure.code, len(self.transport.requests)), (None, 'timeout', 2))
        for answer in (b'{"input_tokens": -1}', b'{"tokens": 5}', b'not json', b'{"input_tokens": true}'):
            with self.subTest(answer=answer):
                self.reply(answer)
                self.assertEqual(self.count().failure.code, 'bad-answer')
        self.assertEqual([(r['call'], r['result'], r.get('error')) for r in self.rows()][:2],
                         [('count-tokens', 'failed', 'api_error'), ('count-tokens', 'failed', 'timeout')])
        self.assertNotIn('fixture-count-error-marker', json.dumps(self.rows()))
        # The count's own limit is 60 seconds from its start, whatever the caller's deadline.
        now = clock.now()
        with mock.patch.object(clock, 'now', return_value=now), \
                mock.patch.object(model_transport, 'once', return_value=model_transport._failed('timeout')) as once:
            self.count(deadline=now + 600)
        self.assertEqual(once.call_args.kwargs['deadline'], now + 60)

    # API-010 to API-012

    def test_a_good_vector_comes_back_scaled_to_length_1_for_every_call(self):
        self.reply(document(numbers()), headers={'x-request-id': 'req_openai_fixture'})
        for call in ('embed-prompt', 'embed-items', 'embed-search'):
            with self.subTest(call=call):
                result = self.embed(call)
                self.assertIsNone(result.failure)
                vector, = result.vectors
                self.assertEqual(len(vector), 4 * DIMS)
                values = self.unpack(vector)
                self.assertAlmostEqual(values[0], .6, places=6); self.assertAlmostEqual(values[1], .8, places=6)
                self.assertAlmostEqual(math.fsum(v * v for v in values), 1, places=6)
        path, headers, body = self.transport.requests[-1]
        self.assertEqual((path, body), ('/v1/embeddings', {
            'model': 'text-embedding-3-small', 'input': ['Keep the four hooks in one script.'],
            'dimensions': DIMS, 'encoding_format': 'float'}))
        rows = self.rows()
        self.assertEqual([(r['call'], r['model'], r['input'], r['result'], r['request']) for r in rows],
                         [(call, 'text-embedding-3-small', 11, 'ok', 'req_openai_fixture')
                          for call in ('embed-prompt', 'embed-items', 'embed-search')])
        self.assertEqual({r['cost'] for r in rows}, {11 * PRICE / 1000000})
        # Items keep their order by index, whatever order the answer lists them in.
        self.reply({'data': [{'index': 1, 'embedding': numbers(0, 1)}, {'index': 0, 'embedding': numbers(1, 0)}],
                    'usage': {'prompt_tokens': 7}})
        first, second = self.embed(texts=['one', 'two']).vectors
        self.assertEqual((self.unpack(first)[:2], self.unpack(second)[:2]), ((1, 0), (0, 1)))

    def test_tc126_bad_vectors_give_bad_vector_with_their_usage_lines(self):
        short = json.dumps(document(numbers()[:-1])).encode()
        infinite = json.dumps(document(numbers())).encode().replace(b'3.0', b'1e999', 1)
        zeros = json.dumps(document([0.0] * DIMS)).encode()
        waits = []
        with mock.patch.object(model_client, '_wait', side_effect=lambda pause, *args: waits.append(pause) or True):
            for call in ('embed-prompt', 'embed-search', 'embed-items'):
                for name, raw in (('length', short), ('not finite', infinite), ('zeros', zeros)):
                    with self.subTest(call=call, vector=name):
                        before, requests = len(self.rows()), len(self.transport.requests)
                        self.reply(raw)
                        result = self.embed(call)
                        attempts = 3 if call == 'embed-items' else 1
                        self.assertEqual((result.vectors, result.failure.code, result.attempts, result.logged),
                                         ((), 'bad-vector', attempts, attempts))
                        self.assertEqual(len(self.transport.requests) - requests, attempts)
                        rows = self.rows()[before:]
                        self.assertEqual([(r['call'], r['result'], r['error'], r['input']) for r in rows],
                                         [(call, 'failed', 'bad-vector', 11)] * attempts)
        self.assertEqual(waits, [10, 60] * 3)

    def test_answers_of_another_shape_are_bad_answers(self):
        cases = {'missing data': {'usage': {'prompt_tokens': 3}},
                 'one vector short': document(),
                 'repeated index': {'data': [{'index': 0, 'embedding': numbers()}] * 2},
                 'index out of range': {'data': [{'index': 1, 'embedding': numbers()}]},
                 'not JSON': b'{"data": [',
                 'a NaN constant': json.dumps(document(numbers())).encode().replace(b'3.0', b'NaN', 1)}
        for name, value in cases.items():
            with self.subTest(case=name):
                self.reply(value)
                result = self.embed('embed-search')
                self.assertEqual((result.vectors, result.failure.code), ((), 'bad-answer'))
        self.reply(document(numbers()), mime='text/html')
        self.assertEqual(self.embed('embed-search').failure.code, 'bad-answer')
        # An answer that reflects the key, plainly or escaped, is never used.
        for echo in (OPENAI, '\\u%04x' % ord(OPENAI[0]) + OPENAI[1:]):
            with self.subTest(echo=echo[:6]):
                self.reply(json.dumps(document(numbers())).encode()[:-1] + b', "echo": "' + echo.encode() + b'"}')
                self.assertEqual(self.embed('embed-search').failure.code, 'bad-answer')
        self.reply(b'{"input_tokens": 5, "echo": "' + ('\\u%04x' % ord(KEY[0]) + KEY[1:]).encode() + b'"}')
        self.assertEqual(self.count().failure.code, 'bad-answer')
        self.assertNotIn(OPENAI, json.dumps(self.rows()))

    def test_tc129_openai_errors_are_classed_and_only_passing_ones_tried_again(self):
        marker = 'fixture-openai-error-body-6c3a'
        spent = [{'code': code, 'type': 'requests'} for code in sorted(model_access._QUOTA)]
        cases = [(429, error, 'insufficient_quota', True) for error in spent]
        cases += [(429, {'type': 'insufficient_quota'}, 'insufficient_quota', True),
                  (429, {'type': 'requests', 'code': 'rate_limit_exceeded'}, 'rate_limit_error', False),
                  (500, {'type': 'server_error'}, 'api_error', False),
                  (503, {'type': 'server_error'}, 'overloaded_error', False),
                  (401, {'type': 'invalid_request_error', 'code': 'invalid_api_key'}, 'authentication_error', True)]
        for status, error, code, lasting in cases:
            with self.subTest(status=status, error=error):
                before, requests, waits = len(self.rows()), len(self.transport.requests), []
                self.reply({'error': dict(error, message=marker)}, status=status)
                with mock.patch.object(model_client, '_wait',
                                       side_effect=lambda pause, *args: waits.append(pause) or True):
                    result = self.embed()
                attempts = 1 if lasting else 3
                self.assertEqual((result.failure.code, result.failure.lasting, result.attempts, result.logged),
                                 (code, lasting, attempts, attempts))
                self.assertEqual((len(self.transport.requests) - requests, waits),
                                 (attempts, [] if lasting else [10, 60]))
                self.assertEqual([(r['result'], r['error']) for r in self.rows()[before:]],
                                 [('failed', code)] * attempts)
        self.assertNotIn(marker, json.dumps(self.rows()))

    def test_an_item_embedding_is_tried_again_only_while_its_caller_says_the_texts_may_still_go(self):
        asked, answers = [], [True, False]

        def still():
            asked.append(len(self.transport.requests))
            return answers[len(asked) - 1]
        self.reply({'error': {'type': 'server_error'}}, status=500)
        with mock.patch.object(model_client, '_wait', return_value=True):
            result = self.embed(still=still)
            self.assertEqual((result.failure.code, result.attempts, asked), ('api_error', 2, [1, 2]))
            # A caller that never says no changes nothing; a prompt's embedding asks nothing.
            self.assertEqual(self.embed(still=lambda: True).attempts, 3)
            self.assertEqual(self.embed('embed-prompt', still=mock.Mock(side_effect=AssertionError)).attempts, 1)
        requests = len(self.transport.requests)
        with self.assertRaises(TypeError):
            self.embed(still=True)
        self.assertEqual(len(self.transport.requests), requests)

    def test_retry_after_is_honoured_for_items_only_up_to_300_seconds(self):
        waits = []
        self.replies(self.json({'error': {'type': 'server_error'}}, status=500, headers={'retry-after': '75'}),
                     self.json(document(numbers())))
        with mock.patch.object(model_client, '_wait', side_effect=lambda pause, *args: waits.append(pause) or True):
            self.assertIsNone(self.embed().failure)
        self.assertEqual(waits, [75])
        self.reply({'error': {'type': 'server_error'}}, status=500, headers={'retry-after': '301'})
        with mock.patch.object(model_client, '_wait', side_effect=AssertionError('no wait')):
            self.assertEqual(self.embed().attempts, 1)
        with mock.patch.object(model_client, '_wait', side_effect=AssertionError('no wait')):
            for call in ('embed-prompt', 'embed-search'):
                self.reply({'error': {'type': 'server_error'}}, status=500)
                self.assertEqual(self.embed(call).attempts, 1)

    def test_a_stalled_error_body_keeps_the_openai_status_class(self):
        # The body stalls until the call has given up. The deadline also covers the call's own interpreter
        # starting and sending the request, which took more than 0.5 s on a slow runner (Intel macOS, Python 3.8).
        released = threading.Event(); self.addCleanup(released.set)
        def stall(handler):
            self.transport.send(handler, b'', status=503, headers={'retry-after': '301'}); released.wait(30)
        self.transport.reply = stall
        result = self.embed('embed-search', deadline=clock.now() + 3)
        released.set()
        self.assertEqual((result.failure.code, result.failure.lasting, result.attempts), ('overloaded_error', False, 1))
        self.assertEqual(self.rows()[-1]['error'], 'overloaded_error')

    def test_tc130_refused_and_dropped_openai_connections_are_network(self):
        def dropped(handler):
            handler.close_connection = True
            handler.connection.shutdown(socket.SHUT_RDWR)
        self.transport.reply = dropped
        with mock.patch.object(model_client, '_wait', return_value=True):
            self.assertEqual((self.embed().failure.code, self.embed().attempts), ('network', 3))
            self.assertEqual(self.embed('embed-search').attempts, 1)
            with mock.patch.dict(os.environ, {'CORTHEX_MEMORY_OPENAI_BASE_URL': 'http://127.0.0.1:%d' % free_port(),
                                              'CORTHEX_MEMORY_ANTHROPIC_BASE_URL': 'http://127.0.0.1:%d' % free_port()}):
                requests = len(self.transport.requests)
                for call in ('embed-prompt', 'embed-items', 'embed-search'):
                    with self.subTest(call=call):
                        result = self.embed(call)
                        self.assertEqual((result.failure.code, result.attempts),
                                         ('network', 3 if call == 'embed-items' else 1))
                self.assertEqual((self.count().failure.code, len(self.transport.requests)), ('network', requests))
        self.assertTrue(all(r['error'] == 'network' for r in self.rows()))

    def test_tc130_refused_and_dropped_anthropic_connections_are_network_and_tried_again(self):
        def dropped(handler):
            # The API streams in chunks, so a connection lost midway leaves a chunk unfinished.
            handler.protocol_version = 'HTTP/1.1'
            handler.send_response(200)
            handler.send_header('Content-Type', 'text/event-stream'); handler.send_header('request-id', 'req_fixture')
            handler.send_header('Transfer-Encoding', 'chunked')
            handler.end_headers()
            data = start(usage={'input_tokens': 40000})
            handler.wfile.write(b'%x\r\n%s\r\n' % (len(data), data)); handler.wfile.flush()
            handler.close_connection = True
            handler.connection.shutdown(socket.SHUT_RDWR)
        self.transport.reply = dropped
        waits = []

        def send():
            return model_client.send(self.usage.memory, project='sample', instructions='curate-3', source=DOCUMENT,
                                     schema=SCHEMA, config={}, check=lambda: None)
        with mock.patch.object(model_client, '_wait', side_effect=lambda pause, *args: waits.append(pause) or True):
            lost = send()
            with mock.patch.dict(os.environ, {'CORTHEX_MEMORY_ANTHROPIC_BASE_URL': 'http://127.0.0.1:%d' % free_port()}):
                refused = send()
        self.assertEqual([(result.response.failure.code, result.attempts) for result in (lost, refused)],
                         [('network', 3), ('network', 3)])
        self.assertEqual((len(self.transport.requests), waits), (3, [10, 60, 10, 60]))
        rows = self.rows()
        self.assertEqual([(r['call'], r['result'], r['error']) for r in rows], [('curate', 'failed', 'network')] * 6)
        # The dropped stream's lines keep the input that message_start reported; a refused one has none.
        self.assertEqual([r.get('input', 0) for r in rows], [40000] * 3 + [0] * 3)
        # The curator's requests keep 30 seconds to connect and 10 minutes between two bytes.
        defaults = inspect.signature(model_transport.once).parameters
        self.assertEqual((defaults['connect'].default, defaults['gap'].default), (30, 600))

    def test_tc130_each_call_keeps_its_own_time_limit(self):
        now = clock.now()
        seen = []

        def once(payload, **options):
            seen.append(options['deadline'] - now)
            connects.append(options['connect'])
            return model_transport._failed('timeout', payload.get('provider', 'anthropic'))
        connects = []
        with mock.patch.object(clock, 'now', return_value=now), mock.patch.object(model_transport, 'once', side_effect=once), \
                mock.patch.object(model_client, '_wait', return_value=True):
            self.count(deadline=now + 900)
            self.embed('embed-items', deadline=now + 900)
            self.embed('embed-search', deadline=now + 900)
            self.embed('embed-prompt', deadline=now + .8)
        # API-009 60 s once, API-011 60 s per attempt and tried again, API-012 10 s once, API-010 the hook's deadline.
        self.assertEqual([round(limit, 6) for limit in seen], [60, 60, 60, 60, 10, .8])
        self.assertEqual([round(limit, 6) for limit in connects], [30, 30, 30, 30, 10, .8])

    def test_tc130_late_answers_time_out_and_a_spent_hook_budget_sends_nothing(self):
        def stall(handler):
            time.sleep(1.5)
            self.transport.send(handler, json.dumps(document(numbers())).encode(), mime='application/json')
        self.transport.reply = stall
        # The prompt hook started 0.5 s ago: 0.3 s of its 0.8 s remain.
        begun = time.monotonic()
        result = self.embed('embed-prompt', deadline=clock.now() + .3)
        self.assertLess(time.monotonic() - begun, 1.2)
        self.assertEqual((result.failure.code, result.attempts, result.logged), ('timeout', 1, 1))
        with mock.patch.dict(model_embed.LIMITS, {'embed-search': .3, 'embed-items': .3}), \
                mock.patch.object(model_client, '_wait', return_value=True):
            self.assertEqual(self.embed('embed-search').attempts, 1)
            self.assertEqual((self.embed('embed-items').failure.code, self.embed('embed-items').attempts),
                             ('timeout', 3))
        requests, rows = len(self.transport.requests), len(self.rows())
        result = self.embed('embed-prompt', deadline=clock.now() - .01)
        self.assertEqual((result.failure.code, result.attempts, result.logged), ('timeout', 0, 0))
        self.assertEqual((len(self.transport.requests), len(self.rows())), (requests, rows))

    def test_tc124_every_kind_of_call_and_each_retry_adds_one_usage_line(self):
        self.replies(self.json({'error': {'type': 'overloaded_error'}}, status=529),
                     lambda handler: self.transport.send(handler, start(usage={'input_tokens': 40000}) + block() +
                                                         end(output=3000)))
        with mock.patch.object(model_client, '_wait', return_value=True):
            for instructions, call in (('curate-3', 'curate'), ('merge-2', 'consolidate')):
                self.transport.requests.clear()
                source = DOCUMENT if instructions == 'curate-3' else (
                    '<request kind="merge" instructions="merge-2"><items><item id="i_sample" kind="decision">'
                    'Keep the choice.</item></items></request>')
                self.assertEqual(model_client.send(self.usage.memory, project='sample', instructions=instructions,
                                                   source=source, schema=SCHEMA, config={},
                                                   check=lambda: None).attempts, 2)
            self.transport.requests.clear()
            self.replies(self.json({'error': {'type': 'server_error'}}, status=500), self.json(document(numbers())))
            self.assertEqual(self.embed('embed-items').attempts, 2)
            self.reply(document(numbers(), tokens=9))
            self.embed('embed-prompt'); self.embed('embed-search')
            self.reply({'input_tokens': 777})
            self.count()
        rows = self.rows()
        self.assertEqual([(r['call'], r['result']) for r in rows],
                         [('curate', 'failed'), ('curate', 'ok'), ('consolidate', 'failed'), ('consolidate', 'ok'),
                          ('embed-items', 'failed'), ('embed-items', 'ok'), ('embed-prompt', 'ok'),
                          ('embed-search', 'ok'), ('count-tokens', 'ok')])
        count = rows[-1]
        self.assertEqual((count['input'], count['cost']), (777, 0))
        self.assertEqual([r['cost'] for r in rows[6:8]], [9 * PRICE / 1000000] * 2)
        # The memory status reads these lines and sums the charged calls only, without the free count.
        reader = status_fixture.StatusTest(); reader.setUp(); self.addCleanup(reader.doCleanups)
        reader.write_rows('usage', [dict(row, at='2026-11-02T10:00:00.000Z') for row in rows], '2026-11')
        with mock.patch.object(status, '_now', return_value=datetime(2026, 11, 2, 12, tzinfo=timezone.utc)):
            usage = reader.direct()['data']['usage']
        charged = rows[:-1]
        self.assertEqual([(group['model'], group['calls']) for group in usage['models']],
                         [(model, sum(r['model'] == model for r in charged))
                          for model in sorted({r['model'] for r in charged})])
        self.assertEqual(sum(group['input'] for group in usage['models']),
                         sum(r.get(name, 0) for r in charged for name in ('input', 'cache_write', 'cache_read')))
        self.assertAlmostEqual(usage['cost'], math.fsum(r['cost'] for r in charged))
        self.assertGreater(usage['cost'], 0)

    def test_tc131_openai_requests_carry_only_their_own_key_and_no_identity(self):
        project, marker = 'project-marker-2b6d', 'PRIVATE_PROVIDER_ERROR_MARKER_0c4f'
        self.reply({'error': {'type': 'server_error', 'message': marker}}, status=500)
        launched, real = [], subprocess.Popen

        def popen(arguments, *args, **options):
            launched.append((arguments, dict(options.get('env') or {})))
            return real(arguments, *args, **options)
        with mock.patch.object(model_client, '_wait', return_value=True), \
                mock.patch.object(model_transport.subprocess, 'Popen', side_effect=popen):
            result = self.embed(project=project)
        self.assertEqual((result.attempts, len(self.transport.requests), len(launched)), (3, 3, 3))
        for path, headers, body in self.transport.requests:
            headers = {name.lower(): value for name, value in headers.items()}
            self.assertEqual((path, headers['content-type'], headers['user-agent'], headers['authorization']),
                             ('/v1/embeddings', 'application/json', 'corthex-memory/' + RELEASE, 'Bearer ' + OPENAI))
            self.assertNotIn('x-api-key', headers)
            self.assertEqual(set(body), {'model', 'input', 'dimensions', 'encoding_format'})
            sent = json.dumps([headers, body], ensure_ascii=False)
            for value in (KEY, project, usage_fixture.DEVICE):
                self.assertNotIn(value, sent)
        stored = b''.join(path.read_bytes() for path in sorted(self.usage.folder.rglob('*')) if path.is_file())
        commands = json.dumps(launched)
        for value in (KEY, OPENAI, marker):
            self.assertNotIn(value.encode(), stored); self.assertNotIn(value, commands)

    def test_texts_are_redacted_then_cut_and_an_empty_text_is_never_sent(self):
        secret = 'sk-ant-' + 'a1B2c3D4e5' * 3
        self.embed('embed-search', texts=['Use ' + secret + ' and ' + OPENAI + ' and ' + KEY])
        sent, = self.transport.requests[-1][2]['input']
        self.assertEqual(sent, 'Use [redacted:anthropic-key] and [redacted:memory-key] and [redacted:memory-key]')
        long = '가' * 3000 + 'b'
        self.embed('embed-search', texts=[long])
        sent, = self.transport.requests[-1][2]['input']
        self.assertEqual(sent, '가' * 2730)
        self.assertLessEqual(len(sent.encode('utf-8')), model_embed.TEXT_BYTES)
        for size in (8192, 8193):
            self.embed('embed-search', texts=['x' * size])
            self.assertEqual(self.transport.requests[-1][2]['input'], ['x' * 8192])
        requests = len(self.transport.requests)
        for texts in ([''], ['fine', '']):
            with self.subTest(texts=texts), self.assertRaises(ValueError):
                self.embed(texts=texts)
        self.assertEqual(len(self.transport.requests), requests)

    def test_a_request_holds_at_most_100_texts_and_200000_bytes(self):
        requests = len(self.transport.requests)
        for texts in (['x'] * 101, ['x' * 8192] * 24 + ['x' * 3393], ['one', 'two']):
            with self.subTest(count=len(texts)), self.assertRaises(ValueError):
                self.embed('embed-items' if len(texts) != 2 else 'embed-search', texts=texts)
        self.assertEqual(len(self.transport.requests), requests)
        self.reply(document(*[numbers()] * 100))
        self.assertEqual(len(self.embed(texts=['x'] * 100).vectors), 100)
        self.reply(document(*[numbers()] * 25))
        self.assertEqual(len(self.embed(texts=['x' * 8192] * 24 + ['x' * 3392]).vectors), 25)
        self.assertEqual(model_embed.batches(['a' * 150000, 'b' * 60000, 'c'] + ['d'] * 120),
                         [(0, 1), (1, 101), (101, 123)])
        self.assertEqual(model_embed.batches(['x' * 8192] * 25), [(0, 24), (24, 25)])
        self.assertEqual(model_embed.batches([]), [])

    def test_tc122_only_the_general_keys_set_send_nothing(self):
        launched = []
        with mock.patch.dict(os.environ, {'CORTHEX_MEMORY_ANTHROPIC_API_KEY': '', 'CORTHEX_MEMORY_OPENAI_API_KEY': ''}), \
                mock.patch.object(model_usage.Attempt, 'start', side_effect=AssertionError('no attempt')), \
                mock.patch.object(model_transport.subprocess, 'Popen', side_effect=lambda *a, **k: launched.append(a)):
            for call in ('embed-prompt', 'embed-items', 'embed-search'):
                with self.subTest(call=call), self.assertRaises(model_client.MissingKey):
                    self.embed(call)
            with self.assertRaises(model_client.MissingKey):
                self.count()
        self.assertEqual((self.transport.requests, launched, self.rows()), ([], [], []))

    def test_tc132_openai_test_server_addresses(self):
        seen = []

        def once(payload, **options):
            seen.append(payload['url'])
            return model_transport._failed('network', 'openai')
        for base in ('https://embeddings.example.invalid', 'http://localhost:9', 'http://127.0.0.1:9/',
                     'http://[::1]:9'):
            with self.subTest(base=base), mock.patch.dict(os.environ, {'CORTHEX_MEMORY_OPENAI_BASE_URL': base}), \
                    mock.patch.object(model_transport, 'once', side_effect=once):
                self.embed('embed-search')
                self.assertEqual(seen[-1], base.rstrip('/') + '/v1/embeddings')
        for base in ('http://embeddings.example.invalid', '', 'ftp://127.0.0.1', 'https://user:pass@example.com',
                     'https://example.invalid/?q=1'):
            with self.subTest(base=base), mock.patch.dict(os.environ, {'CORTHEX_MEMORY_OPENAI_BASE_URL': base}), \
                    mock.patch.object(model_transport, 'once', side_effect=AssertionError('no request')):
                with self.assertRaises(ValueError):
                    self.embed('embed-search')
        self.assertEqual(len(seen), 4)

    def test_tls_trust_comes_from_the_environment_for_the_json_calls(self):
        cert, key = self.transport.certificate()
        self.transport.tls(cert, key)
        address = self.base.replace('http://', 'https://')
        with mock.patch.dict(os.environ, {'CORTHEX_MEMORY_OPENAI_BASE_URL': address,
                                          'CORTHEX_MEMORY_ANTHROPIC_BASE_URL': address, 'SSL_CERT_FILE': ''}):
            self.assertEqual(self.embed('embed-search').failure.code, 'network')
            self.assertEqual(self.transport.requests, [])
            with mock.patch.dict(os.environ, {'SSL_CERT_FILE': str(cert)}):
                self.assertIsNone(self.embed('embed-search').failure)
                self.reply({'input_tokens': 3})
                self.assertEqual(self.count().tokens, 3)
        self.assertEqual(len(self.transport.requests), 2)

    def test_a_lost_check_stops_the_call_with_its_own_exception(self):
        original, reached = locks.LostLock(), threading.Event()

        def slow(handler):
            reached.set(); time.sleep(.6)
            self.transport.send(handler, json.dumps(document(numbers())).encode(), mime='application/json')
        self.transport.reply = slow

        def check():
            if reached.is_set():
                raise original
        with self.assertRaises(locks.LostLock) as caught:
            self.embed(check=check)
        self.assertIs(caught.exception, original)
        row, = self.rows()
        self.assertEqual((row['call'], row['result']), ('embed-items', 'failed')); self.assertNotIn('error', row)
        active = [True]

        def lost():
            if not active[0]:
                raise original

        def wait(*args):
            active[0] = False; lost()
        self.reply({'error': {'type': 'server_error'}}, status=500)
        with mock.patch.object(model_client, '_wait', side_effect=wait), self.assertRaises(locks.LostLock):
            self.embed(check=lost)
        with self.assertRaises(TypeError):
            self.embed(check=lambda: True)


if __name__ == '__main__':
    unittest.main()
