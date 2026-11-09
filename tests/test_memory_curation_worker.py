"""TASK-088: the curation worker on made-up format-2 stores, against a local test server.

TC-118, TC-119, TC-152, TC-153, TC-155, TC-159, TC-160, TC-161, TC-172,
TC-173, TC-174, TC-178, TC-182, TC-183, TC-353 and TC-387, the worker's
parts of TC-146, TC-147, TC-148, TC-150, TC-170, TC-171, TC-358 and TC-359,
and TASK-116's TC-421 (request sizes in the usage log).
Every request goes to a local test server, with keys made up during the run;
no provider is called. The worker is not wired to a hook or command before the
0.3.0 activation.
"""
import contextlib
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import multiprocessing
import os
from pathlib import Path
import random
import re
import secrets
import statistics
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

from _common import ROOT
SCRIPTS = ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'
sys.path.insert(0, str(SCRIPTS))
from memory_lib import (base, clock, curation_worker, fence_plan, format2, index_io, item_types, locks, model_client,
                        model_usage, raw_log, revision_io, run_log, state_types)
from memory_lib.c2_store import C2Store
from test_memory_curator_answers import answer, change, quote
from test_memory_model_stream import block, end, start
import test_memory_curator_document as document_fixture
import test_memory_request_budget as budget

DEVICE = 'd_0123456789ab'
AT = '2026-11-04T03:00:00.000Z'
WHEN = datetime(2026, 11, 8, 9, 0, tzinfo=timezone.utc)
STAMP = '2026-11-08T09:00:00.000Z'
EPOCH = '0123456789abcdef' * 2
SESSION = 'fixture-session-088'
LOG = raw_log.log_name('claude-code', SESSION)
PROXIES = ('HTTPS_PROXY', 'HTTP_PROXY', 'ALL_PROXY', 'https_proxy', 'http_proxy', 'all_proxy')
REFUSAL = start() + end(reason='refusal', output=1)
LIMIT = start() + block(text='{"changes": [') + end(reason='max_tokens')
HOOKS = 'Keep the four hooks in one script'


def ident(prefix):
    return prefix + '_' + ''.join(secrets.choice(base.CROCKFORD) for _ in range(12))


def stream(value):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return start(usage={'input_tokens': 1200, 'output_tokens': 1}) + block(text=text) + end(output=300)


def failing(status, kind):
    def reply(handler):
        Server.send(handler, json.dumps({'error': {'type': kind}}).encode('utf-8'), status, 'application/json')
    return reply


def paused_curator(connection, folder):
    """A worker in another process that does not refresh its lock, as one that is paused does not."""
    locks.POLICIES['curation'] = locks.Policy(1, 3600, 600)
    memory = C2Store(Path(folder), expected_device=DEVICE)
    deadline = clock.now() + 120
    with memory.lease(memory.folder / 'projects/sample/curation.lock', 'curation', deadline) as owner:
        connection.send('held')
        outcome = curation_worker.curate(memory, 'sample', owner, deadline, when=WHEN)
    connection.send((outcome.reason, [attempt.record for attempt in outcome.attempts]))


class Server:
    """A local test server in place of the API: it records each request and answers it by its number.

    `answers` holds the replies by request number, the last one repeating; `reply(number, body)`, when
    set, gives them instead. A reply is an answer value, stream bytes or a function of the handler.
    Token counts fail, so the safe estimate decides alone, unless `counter(body)` gives them.
    """

    def __init__(self):
        self.requests, self.counts, self.answers, self.before, self.reply = [], [], [], {}, None
        self.counter = None
        self.mutex = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))))
                try:
                    if self.path.endswith('/count_tokens'):
                        outer.counts.append(body)
                        if outer.counter is None:
                            failing(500, 'api_error')(self)
                        else:
                            outer.send(self, json.dumps({'input_tokens': outer.counter(body)}).encode('utf-8'),
                                       mime='application/json')
                        return
                    with outer.mutex:
                        number = len(outer.requests)
                        outer.requests.append(({k.lower(): v for k, v in self.headers.items()}, body))
                    if number in outer.before:
                        outer.before[number]()
                    if outer.reply is not None:
                        reply = outer.reply(number, body)
                    else:
                        reply = outer.answers[min(number, len(outer.answers) - 1)]
                    if callable(reply):
                        reply(self)
                    else:
                        outer.send(self, reply if isinstance(reply, bytes) else stream(reply))
                except (OSError, ValueError):
                    pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=.01), daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)

    @staticmethod
    def send(handler, body, status=200, mime='text/event-stream'):
        handler.send_response(status)
        handler.send_header('Content-Type', mime)
        handler.send_header('request-id', 'req_fixture')
        handler.end_headers()
        handler.wfile.write(body)
        handler.wfile.flush()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def content(self, number):
        return self.requests[number][1]['messages'][0]['content']


class Raw:
    """One raw log's entries, numbered as the recorder numbers them."""

    def __init__(self, session=SESSION):
        self.session, self.name = session, raw_log.log_name('claude-code', session)
        self.entries = []
        self.add('start')

    def add(self, kind, text=None, turn=None, at=AT):
        seq = len(self.entries) + 1
        value = dict(id=ident('e'), seq=seq, at=at, host='claude-code', session=self.session, kind=kind)
        if kind in ('prompt', 'answer'):
            value.update(turn=turn or seq, speaker='user' if kind == 'prompt' else 'agent', text=text)
        self.entries.append(value)
        return value

    def turn(self, prompt, reply, at=AT):
        said = self.add('prompt', prompt, at=at)
        return said, self.add('answer', reply, turn=said['seq'], at=at)

    def data(self):
        return b''.join(item_types._raw(value) + b'\n' for value in self.entries)


class CurationWorkerTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name).resolve() / 'memory'
        self.root = self.folder / 'projects' / 'sample'
        for name in ('raw', 'unprocessed', 'notices', 'runs', 'layer/items', 'layer/tombstones'):
            (self.root / name).mkdir(parents=True)
        (self.folder / 'logs').mkdir()
        (self.folder / 'store.json').write_bytes(format2.store_bytes(
            {'format': 2, 'device': DEVICE, 'made': AT, 'release': '0.3.0'}))
        self.configure()
        (self.root / 'curation.json').write_bytes(format2.curation_bytes(
            {'logs': {}, 'applies': 0, 'recent': [], 'consolidation': {'failures': 0},
             'fence': {'epoch': EPOCH, 'generation': 0, 'revisions': {}}}))
        (self.root / 'state-history.jsonl').write_bytes(b'')
        self.layer()
        self.server = Server()
        self.addCleanup(self.server.close)
        values = {name: '' for name in PROXIES}
        values.update(NO_PROXY='localhost,127.0.0.1,::1', no_proxy='localhost,127.0.0.1,::1',
                      CORTHEX_MEMORY_HOME=str(self.folder), CORTHEX_MEMORY_ANTHROPIC_BASE_URL=self.server.url,
                      CORTHEX_MEMORY_ANTHROPIC_API_KEY='memory-key-' + secrets.token_hex(12),
                      CORTHEX_MEMORY_OPENAI_API_KEY='', ANTHROPIC_API_KEY='general-key-' + secrets.token_hex(12),
                      OPENAI_API_KEY='general-key-' + secrets.token_hex(12))
        self.keys = values
        environment = mock.patch.dict(os.environ, values)
        environment.start()
        self.addCleanup(environment.stop)
        self.memory = C2Store(self.folder, expected_device=DEVICE)
        self.raw = Raw()

    # The store

    def configure(self, consent=1, enabled=True, **document):
        value = {'projects': {'sample': {'enabled': enabled, 'since': AT}}}
        if consent is not None:
            value['consent'] = {'at': AT, 'version': consent}
        value.update(document)
        (self.folder / 'configuration.json').write_bytes(json.dumps(value).encode('utf-8'))

    def layer(self, items=(), lines=(), candidates=(), pinned=()):
        layer = self.root / 'layer'
        for value in items:
            (layer / 'items' / (value['id'] + '.json')).write_bytes(item_types.item_bytes(value))
        (layer / 'state.json').write_bytes(state_types.state_bytes({'lines': list(lines)}))
        (layer / 'state-removed.json').write_bytes(state_types.removed_bytes({'removed': []}))
        (layer / 'pins.json').write_bytes(item_types.pins_bytes(
            {'pins': [dict(item=pin, on=True, at=AT, device=DEVICE) for pin in pinned]}))
        (layer / 'conflicts.json').write_bytes(item_types._raw({'candidates': list(candidates)}) + b'\n')
        (layer / 'item-list.txt').write_bytes(item_types.item_list_bytes(list(self.items().values())))

    def write(self):
        (self.root / 'raw' / (self.raw.name + '.jsonl')).write_bytes(self.raw.data())

    def mark(self, said):
        name = '%s.%s.%d' % (said['at'][:19].replace('-', '').replace(':', '') + 'Z', self.raw.name, said['turn'])
        (self.root / 'unprocessed' / name).write_bytes(b'')
        return name

    def saved(self, source, words, kind='decision'):
        start_at = source['text'].index(words)
        cited = dict(entry=source['id'], log=self.raw.name, device=DEVICE, start=start_at,
                     end=start_at + len(words), speaker=source['speaker'], said=source['at'], words=words)
        return dict(id=ident('i'), kind=kind, title='Saved ' + kind, text='A saved ' + kind + '.',
                    quotes=[cited], status='current', saved=AT, device=DEVICE)

    def one_turn(self, prompt=HOOKS + ', please.', reply='One script now serves the hooks.'):
        said, answered = self.raw.turn(prompt, reply)
        self.write()
        return said, answered

    def index(self):
        """The word index of the items, built under the layer lease with the default embedding settings."""
        deadline = clock.now() + 60
        with self.memory.lease(self.root / 'layer.lock', 'layer', deadline):
            proof = fence_plan.snapshot(revision_io.read(self.memory, self.root, deadline))
            index_io.ensure(self.memory, self.root, proof, deadline, model='text-embedding-3-small', dims=512,
                            when=STAMP)

    def sent(self):
        """Each curate request's turns, as (log, seq, part) in the order it carries them."""
        found = []
        for _, body in self.server.requests:
            root = ET.fromstring(body['messages'][0]['content'])
            found.append([(session.get('log'), int(turn.get('seq')), turn.get('part'))
                          for session in root.iter('session') for turn in session.iter('turn')])
        return found

    def advance(self, other, forgotten=None):
        """What a forget does under the layer lease: its tombstone, the item gone and the fence advanced."""
        deadline = clock.now() + 30
        with other.lease(self.root / 'layer.lock', 'layer', deadline):
            target = ident('i') if forgotten is None else forgotten['id']
            if forgotten is not None:
                cited = forgotten['quotes'][0]
                tombstone = dict(item=target, project='sample', at=AT, device=DEVICE,
                                 quotes=[{k: cited[k] for k in ('device', 'entry', 'log', 'start', 'end')}])
                (self.root / 'layer/tombstones' / (target + '.json')).write_bytes(item_types._raw(tombstone) + b'\n')
                (self.root / 'layer/items' / (target + '.json')).unlink()
            progress = revision_io.read(other, self.root, deadline)
            revision_io.reserve(other, self.root, fence_plan.snapshot(progress), ['item:' + target], deadline)

    # What the store holds

    def progress(self):
        return format2.parse_curation((self.root / 'curation.json').read_bytes())

    def items(self):
        return {path.name[:-5]: item_types.parse_item(path.read_bytes())
                for path in (self.root / 'layer/items').glob('*.json')}

    def lines(self):
        return state_types.parse_state((self.root / 'layer/state.json').read_bytes())['lines']

    def notice(self):
        path = self.root / 'notices/curation-failed.json'
        return item_types.parse_notice(path.read_bytes()) if path.exists() else None

    def usage(self):
        return [json.loads(line) for path in sorted((self.folder / 'logs').glob('usage-*.jsonl'))
                for line in path.read_bytes().splitlines()]

    def failures(self):
        return [(value['step'], value['error']) for value in (
            json.loads(line) for path in sorted((self.folder / 'logs').glob('failures-*.jsonl'))
            for line in path.read_bytes().splitlines())]

    def runs(self):
        return sorted(path.name for path in (self.root / 'runs').iterdir())

    def markers(self):
        return sorted(path.name for path in (self.root / 'unprocessed').iterdir())

    def snapshot(self):
        return {path.relative_to(self.root).as_posix(): path.read_bytes()
                for path in sorted(self.root.rglob('*')) if path.is_file()}

    def raw_bytes(self):
        return (self.root / 'raw' / (LOG + '.jsonl')).read_bytes()

    # Running the worker

    def curate(self, seconds=300):
        deadline = clock.now() + seconds
        with self.memory.lease(self.root / 'curation.lock', 'curation', deadline) as owner:
            return curation_worker.curate(self.memory, 'sample', owner, deadline, when=WHEN)

    @contextlib.contextmanager
    def quick(self):
        """Passing failures are tried again at once, not after 10 and 60 seconds."""
        waits = []

        def wait(seconds, deadline, check):
            waits.append(seconds)
            check()
            return True
        with mock.patch.object(model_client, '_wait', side_effect=wait):
            yield waits

    # SPEC-014

    def test_tc159_the_request_names_the_configured_model_and_effort_then_the_defaults(self):
        self.configure(models={'curator': 'claude-sonnet-5-5', 'effort': 'high'})
        said, _ = self.one_turn()
        self.server.answers = [answer(change(quote(said, HOOKS), kind='decision'))]
        self.assertEqual(self.curate().reason, 'done')
        self.configure()
        later, _ = self.one_turn('Name the script hook.py.', 'The script is hook.py now.')
        self.server.answers.append(answer(change(quote(later, 'Name the script hook.py'), kind='decision')))
        self.assertEqual(self.curate().reason, 'done')
        bodies = [body for _, body in self.server.requests]
        self.assertEqual([(b['model'], b['output_config']['effort']) for b in bodies],
                         [('claude-sonnet-5-5', 'high'), ('claude-haiku-5-5', 'xhigh')])
        for body in bodies:
            self.assertEqual((body['max_tokens'], body['stream'], body['thinking']),
                             (64000, True, {'type': 'adaptive'}))
            self.assertFalse({'temperature', 'top_p', 'top_k'} & set(body))
        self.assertEqual(len(self.items()), 2)

    def test_tc160_each_request_carries_the_memory_key_never_another_and_adds_one_usage_line(self):
        said, _ = self.one_turn()
        self.server.answers = [answer(change(quote(said, HOOKS), kind='decision'))]
        self.assertEqual(self.curate().reason, 'done')
        self.one_turn('Name the script hook.py.', 'The script is hook.py now.')
        self.server.answers.append(answer())
        self.assertEqual(self.curate().reason, 'done')
        self.assertEqual(len(self.server.requests), 2)
        for headers, body in self.server.requests:
            self.assertEqual(headers['x-api-key'], self.keys['CORTHEX_MEMORY_ANTHROPIC_API_KEY'])
            for name in ('ANTHROPIC_API_KEY', 'OPENAI_API_KEY'):
                self.assertNotIn(self.keys[name], json.dumps(headers) + json.dumps(body))
        rows = self.usage()
        self.assertEqual([(r['call'], r['project'], r['model'], r['result']) for r in rows],
                         [('curate', 'sample', 'claude-haiku-5-5', 'ok')] * 2)
        self.assertNotIn(self.keys['CORTHEX_MEMORY_ANTHROPIC_API_KEY'], json.dumps(rows))

    # SPEC-018

    def test_tc170_three_failed_attempts_from_one_first_turn_stop_curation(self):
        said, _ = self.one_turn()
        before = self.raw_bytes()
        self.server.answers = [REFUSAL]
        outcomes = [self.curate() for _ in range(3)]
        self.assertEqual([o.reason for o in outcomes], ['failed', 'failed', 'stopped'])
        self.assertEqual([o.attempts[0].record for o in outcomes],
                         [{'at': STAMP, 'kind': 'curate', 'result': 'failed', 'error': 'refusal'}] * 3)
        self.assertEqual([o.attempts[0].first for o in outcomes], [(LOG, said['turn'])] * 3)
        progress = self.progress()
        self.assertEqual(progress['failures'], {'count': 3, 'log': LOG, 'turn': said['turn']})
        self.assertEqual(progress['stopped'], {'at': STAMP, 'by': 'curate', 'errors': ['refusal']})
        self.assertEqual((progress['logs'], progress['applies'], len(progress['recent'])), ({}, 0, 3))
        self.assertEqual(self.notice(), {'at': STAMP, 'kind': 'curation-failed', 'error': 'refusal'})
        self.assertEqual([r['result'] for r in self.usage()], ['refused'] * 3)
        # Until the user resumes the project no request goes out, and nothing changes.
        stored = self.snapshot()
        self.assertEqual(self.curate(), curation_worker.Outcome('stopped', ()))
        self.assertEqual((len(self.server.requests), self.snapshot()), (3, stored))
        self.assertEqual(self.raw_bytes(), before)

    def test_the_stop_names_each_kind_of_error_and_a_success_sets_the_count_to_zero(self):
        said, _ = self.one_turn()
        self.server.answers = [REFUSAL, REFUSAL, answer()]
        self.assertEqual([self.curate().reason for _ in range(3)], ['failed', 'failed', 'done'])
        self.assertEqual(self.progress()['failures'], {'count': 0, 'log': LOG, 'turn': said['turn']})
        later, _ = self.one_turn('Name the script hook.py.', 'The script is hook.py now.')
        self.server.answers += [REFUSAL, LIMIT, failing(401, 'authentication_error')]
        self.assertEqual([self.curate().reason for _ in range(3)], ['failed', 'failed', 'stopped'])
        progress = self.progress()
        self.assertEqual(progress['failures'], {'count': 3, 'log': LOG, 'turn': later['turn']})
        self.assertEqual(progress['stopped']['errors'], ['refusal', 'max-tokens', 'authentication_error'])

    def test_tc171_a_failed_attempt_leaves_its_turns_unprocessed_and_unchanged(self):
        self.one_turn()
        before = self.raw_bytes()
        cases = (('max-tokens', [LIMIT], ['limit']),
                 ('empty-answer', [start() + end()] * 3, ['failed'] * 3),
                 ('bad-answer', [stream({'changes': 'none'})] * 3, ['failed'] * 3))
        for code, replies, results in cases:
            with self.subTest(code=code):
                self.server.answers = self.server.answers[:len(self.server.requests)] + replies
                with self.quick() as waits:
                    outcome = self.curate()
                # The third failed attempt from the same first turn stops curation (TC-170).
                self.assertEqual((outcome.reason, waits), ('stopped' if code == 'bad-answer' else 'failed',
                                                           [] if code == 'max-tokens' else [10, 60]))
                progress = self.progress()
                self.assertEqual(progress['recent'][0],
                                 {'at': STAMP, 'kind': 'curate', 'result': 'failed', 'error': code})
                self.assertEqual((progress['logs'], progress['applies']), ({}, 0))
                self.assertEqual(self.raw_bytes(), before)
                self.assertEqual(self.notice()['error'], code)
                self.assertEqual([r['result'] for r in self.usage()][-len(results):], results)
        self.assertEqual(self.items(), {})
        self.assertEqual(self.progress()['stopped']['errors'], ['max-tokens', 'empty-answer', 'bad-answer'])

    # SPEC-012

    def test_tc173_a_paused_curator_whose_lock_another_takes_over_applies_nothing(self):
        said, _ = self.one_turn()
        go_on, asked = threading.Event(), threading.Event()

        def hold(handler):
            asked.set()
            go_on.wait(60)
            Server.send(handler, stream(answer(change(quote(said, 'one script'), title='The first worker'))))
        self.server.answers = [hold, answer(change(quote(said, HOOKS), kind='decision', title='The second worker'))]
        context = multiprocessing.get_context('spawn')
        parent, child = context.Pipe()
        process = context.Process(target=paused_curator, args=(child, str(self.folder)))
        process.start()
        child.close()
        self.addCleanup(parent.close)

        def stop():
            go_on.set()
            process.join(timeout=30)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        self.addCleanup(stop)
        self.assertTrue(parent.poll(60) and parent.recv() == 'held', 'the first worker took no lock')
        self.assertTrue(asked.wait(60), 'the first worker sent no request')
        # Its lock was last refreshed 11 minutes ago, so another worker takes it over and curates.
        past = time.time() - 660
        os.utime(str(self.root / 'curation.lock'), (past, past))
        second = self.curate()
        go_on.set()
        self.assertTrue(parent.poll(60), 'the first worker did not end')
        self.assertEqual(parent.recv(), ('lost-lock', []))
        self.assertEqual((second.reason, [a.record['result'] for a in second.attempts]), ('done', ['ok']))
        self.assertEqual([value['title'] for value in self.items().values()], ['The second worker'])
        progress = self.progress()
        self.assertEqual((progress['logs'], progress['applies'], len(progress['recent'])), ({LOG: 3}, 1, 1))
        self.assertEqual(len(self.runs()), 1)

    def test_tc174_a_forget_while_a_request_waits_makes_it_stale_and_the_request_is_built_again(self):
        said, _ = self.one_turn('My spare locker phrase stays apart; keep the hooks in one script.',
                                'One script now serves the hooks.')
        forgotten = self.saved(said, 'My spare locker phrase stays apart', kind='reference')
        self.layer([forgotten])
        other = C2Store(self.folder, expected_device=DEVICE)
        self.server.before[0] = lambda: self.advance(other, forgotten)
        self.server.answers = [answer(change(quote(said, 'My spare locker phrase stays apart'), kind='reference')),
                               answer(change(quote(said, 'keep the hooks in one script'), kind='decision'))]
        outcome = self.curate()
        self.assertEqual((outcome.reason, [a.record['result'] for a in outcome.attempts]), ('done', ['stale', 'ok']))
        recent = self.progress()['recent']
        self.assertEqual(recent, [{'at': STAMP, 'kind': 'curate', 'result': 'ok', 'applied': 1, 'dropped': 0,
                                   'state': 'kept', 'run': recent[0]['run']},
                                  {'at': STAMP, 'kind': 'curate', 'result': 'stale'}])
        self.assertIn('locker phrase', self.server.content(0))
        self.assertNotIn('locker phrase', self.server.content(1))
        self.assertIn('[forgotten]', self.server.content(1))
        (value,) = self.items().values()
        self.assertEqual(value['quotes'][0]['words'], 'keep the hooks in one script')
        self.assertNotIn('locker', json.dumps(self.items()) + json.dumps(self.lines()))
        self.assertNotIn('failures', self.progress())

    def test_tc174_a_request_that_fails_after_a_forget_is_not_tried_again(self):
        said, _ = self.one_turn('My spare locker phrase stays apart; keep the hooks in one script.',
                                'One script now serves the hooks.')
        forgotten = self.saved(said, 'My spare locker phrase stays apart', kind='reference')
        self.layer([forgotten])
        other = C2Store(self.folder, expected_device=DEVICE)
        self.server.before[0] = lambda: self.advance(other, forgotten)
        self.server.answers = [failing(529, 'overloaded_error'),
                               answer(change(quote(said, 'keep the hooks in one script'), kind='decision'))]
        with self.quick() as waits:
            outcome = self.curate()
        self.assertEqual((outcome.reason, [a.record['result'] for a in outcome.attempts]), ('done', ['stale', 'ok']))
        # The failed attempt is not tried again with the forgotten words: the next request is built again.
        self.assertEqual((len(self.server.requests), waits), (2, [10]))
        self.assertIn('locker phrase', self.server.content(0))
        self.assertNotIn('locker', self.server.content(1))
        self.assertIn('[forgotten]', self.server.content(1))
        self.assertEqual([(row['call'], row['result']) for row in self.usage()],
                         [('curate', 'failed'), ('curate', 'ok')])
        self.assertNotIn('failures', self.progress())

    def test_a_failed_attempt_is_tried_again_with_the_same_request_while_the_fence_stays(self):
        said, _ = self.one_turn()
        self.server.answers = [failing(529, 'overloaded_error'), answer(change(quote(said, HOOKS), kind='decision'))]
        with self.quick() as waits:
            outcome = self.curate()
        self.assertEqual((outcome.reason, [a.record['result'] for a in outcome.attempts]), ('done', ['ok']))
        self.assertEqual((len(self.server.requests), waits), (2, [10]))
        self.assertEqual(self.server.content(0), self.server.content(1))
        self.assertEqual([row['result'] for row in self.usage()], ['failed', 'ok'])

    def test_tc174_a_forget_while_a_part_waits_sends_no_other_part_built_before_it(self):
        said, paragraphs = self.long_turn()
        forgotten = self.saved(said, paragraphs[0][:20], kind='fact')
        self.layer([forgotten])
        other = C2Store(self.folder, expected_device=DEVICE)
        self.server.before[0] = lambda: self.advance(other, forgotten)
        self.server.answers = [answer()]
        outcome = self.curate()
        self.assertEqual((outcome.reason, [a.record['result'] for a in outcome.attempts]), ('done', ['stale', 'ok']))
        self.assertEqual(outcome.attempts[0].requests, 1)
        parts = [re.search(r' part="(\d+)" parts="(\d+)"', self.server.content(number)).groups()
                 for number in range(len(self.server.requests))]
        # Every part carries the item list: after the forget, only the parts built again go.
        self.assertGreaterEqual(int(parts[0][1]), 3)
        self.assertEqual([int(part) for part, _ in parts], [1] + list(range(1, len(parts))))
        self.assertIn('id="%s"' % forgotten['id'], self.server.content(0))
        for number in range(1, len(parts)):
            self.assertNotIn(forgotten['id'], self.server.content(number))

    def test_tc174_a_forget_while_a_request_is_counted_sends_nothing_built_before_it(self):
        said, _ = self.one_turn('My spare locker phrase stays apart; keep the hooks in one script.',
                                'One script now serves the hooks.')
        for n in range(12):
            self.raw.turn(budget.prose(9000, 300 + n), budget.prose(9000, 400 + n))
        self.write()
        forgotten = self.saved(said, 'My spare locker phrase stays apart', kind='reference')
        self.layer([forgotten])
        other = C2Store(self.folder, expected_device=DEVICE)

        def counter(body):
            if not self.server.counts[1:]:
                self.advance(other, forgotten)
                # Over 99,000, so that the request loses turns and would be counted again.
                return 120000
            return budget.body_rule(body)
        self.server.counter = counter
        self.server.answers = [answer()]
        outcome = self.curate()
        self.assertEqual((outcome.reason, [a.record['result'] for a in outcome.attempts]), ('done', ['stale', 'ok']))
        self.assertEqual(outcome.attempts[0].requests, 0)
        counted = [body['messages'][0]['content'] for body in self.server.counts]
        self.assertIn('locker phrase', counted[0])
        self.assertTrue(len(counted) > 1 and not any('locker' in text for text in counted[1:]))
        self.assertTrue(self.server.requests)
        self.assertFalse([number for number in range(len(self.server.requests))
                          if 'locker' in self.server.content(number)])

    def test_a_project_turned_off_while_a_part_waits_sends_no_later_part(self):
        self.long_turn()
        self.server.before[0] = lambda: self.configure(enabled=False)
        self.server.answers = [answer()]
        outcome = self.curate()
        # The run's conditions are read again before each request: once the project is off, nothing more is sent,
        # and the attempt is stale rather than a failure.
        self.assertEqual((outcome.reason, [a.record['result'] for a in outcome.attempts]), ('disabled', ['stale']))
        self.assertEqual((len(self.server.requests), outcome.attempts[0].requests), (1, 1))
        self.assertRegex(self.server.content(0), r' part="1" parts="\d+"')
        self.assertEqual((self.items(), self.progress()['logs']), ({}, {}))
        self.assertEqual(self.progress()['recent'], [{'at': STAMP, 'kind': 'curate', 'result': 'stale'}])

    def test_consent_withdrawn_before_a_retry_sends_it_no_more(self):
        said, _ = self.one_turn()
        self.server.before[0] = lambda: self.configure(consent=None)
        self.server.answers = [failing(529, 'overloaded_error'), answer(change(quote(said, HOOKS), kind='decision'))]
        with self.quick() as waits:
            outcome = self.curate()
        self.assertEqual((outcome.reason, [a.record['result'] for a in outcome.attempts]), ('consent', ['stale']))
        self.assertEqual((len(self.server.requests), waits), (1, [10]))
        self.assertEqual([(row['call'], row['result']) for row in self.usage()], [('curate', 'failed')])
        self.assertEqual((self.items(), self.progress()['logs']), ({}, {}))
        self.assertNotIn('failures', self.progress())
        self.assertIsNone(self.notice())

    def test_a_project_turned_off_while_a_request_is_counted_counts_and_sends_nothing_more(self):
        self.one_turn()
        for n in range(12):
            self.raw.turn(budget.prose(9000, 300 + n), budget.prose(9000, 400 + n))
        self.write()

        def counter(body):
            if not self.server.counts[1:]:
                self.configure(enabled=False)
                # Over 99,000, so that the request loses turns and would be counted again.
                return 120000
            return budget.body_rule(body)
        self.server.counter = counter
        self.server.answers = [answer()]
        outcome = self.curate()
        self.assertEqual((outcome.reason, [a.record['result'] for a in outcome.attempts]), ('disabled', ['stale']))
        self.assertEqual((len(self.server.counts), self.server.requests, outcome.attempts[0].requests), (1, [], 0))
        self.assertEqual(self.progress()['logs'], {})

    def waiting(self, act):
        """Run `act` each time the run compares the fence once a request has gone, as if while it waited for the
        layer lease before a further attempt."""
        unmoved = curation_worker._unmoved

        def compared(*args):
            if self.server.requests:
                act()
            return unmoved(*args)
        return mock.patch.object(curation_worker, '_unmoved', side_effect=compared)

    def test_consent_withdrawn_while_a_retry_waits_for_the_layer_lease_sends_it_no_more(self):
        said, _ = self.one_turn()
        self.server.answers = [failing(529, 'overloaded_error'), answer(change(quote(said, HOOKS), kind='decision'))]
        with self.quick() as waits, self.waiting(lambda: self.configure(consent=None)):
            outcome = self.curate()
        # The conditions are read again after the wait for the layer lease, right before the retry.
        self.assertEqual((outcome.reason, [a.record['result'] for a in outcome.attempts]), ('consent', ['stale']))
        self.assertEqual((len(self.server.requests), waits), (1, [10]))
        self.assertEqual((self.items(), self.progress()['logs']), ({}, {}))

    def test_consent_withdrawn_before_a_retry_ends_the_run_without_waiting_for_the_layer_lease(self):
        said, _ = self.one_turn()
        self.server.before[0] = lambda: self.configure(consent=None)
        self.server.answers = [failing(529, 'overloaded_error'), answer(change(quote(said, HOOKS), kind='decision'))]

        def busy():
            raise locks.LockBusy()
        with self.quick() as waits, self.waiting(busy):
            outcome = self.curate()
        # Read before that wait as well, so the run ends as `consent`, not `busy`.
        self.assertEqual((outcome.reason, [a.record['result'] for a in outcome.attempts]), ('consent', ['stale']))
        self.assertEqual((len(self.server.requests), waits), (1, [10]))

    def flickering(self):
        """Have the run's conditions read as gone once, at the first reading once a request has gone, and as they
        are at every other reading."""
        gate, gone = curation_worker._gate, []

        def read(*args):
            if self.server.requests and not gone:
                gone.append(True)
                return 'consent', None
            return gate(*args)
        return mock.patch.object(curation_worker, '_gate', side_effect=read)

    def test_a_retry_that_the_conditions_stopped_is_stale_though_they_hold_again_right_after(self):
        said, _ = self.one_turn()
        self.server.answers = [failing(529, 'overloaded_error'), answer(change(quote(said, HOOKS), kind='decision'))]
        with self.quick() as waits, self.flickering():
            outcome = self.curate()
        # The no that kept the retry back makes the attempt stale, not failed, though the next reading says yes.
        self.assertEqual((outcome.reason, [a.record['result'] for a in outcome.attempts]), ('done', ['stale', 'ok']))
        self.assertEqual((len(self.server.requests), waits), (2, [10]))
        self.assertEqual([row['result'] for row in self.usage()], ['failed', 'ok'])
        self.assertNotIn('failures', self.progress())
        self.assertIsNone(self.notice())

    def test_a_request_whose_check_before_a_retry_fails_counts_as_sent(self):
        self.one_turn()
        self.server.answers = [failing(529, 'overloaded_error')]

        def unreadable():
            raise ValueError('unreadable')
        with self.quick() as waits, self.waiting(unreadable):
            outcome = self.curate()
        self.assertEqual((outcome.reason, [a.record['result'] for a in outcome.attempts]), ('failed', ['failed']))
        self.assertEqual(outcome.attempts[0].record['error'], 'ValueError')
        self.assertEqual((len(self.server.requests), waits, outcome.attempts[0].requests), (1, [10], 1))

    def test_tc119_an_applies_count_changed_while_a_request_waits_drops_its_results(self):
        said, _ = self.one_turn()

        def bump():
            value = self.progress()
            value['applies'] += 1
            (self.root / 'curation.json').write_bytes(format2.curation_bytes(value))
        self.server.before[0] = bump
        self.server.answers = [answer(change(quote(said, HOOKS), kind='decision', title='Built before')),
                               answer(change(quote(said, HOOKS), kind='decision', title='Built again'))]
        outcome = self.curate()
        self.assertEqual((outcome.reason, [a.record['result'] for a in outcome.attempts]), ('done', ['stale', 'ok']))
        self.assertEqual([value['title'] for value in self.items().values()], ['Built again'])
        progress = self.progress()
        self.assertEqual((progress['logs'], progress['applies'], len(self.runs())), ({LOG: 3}, 2, 1))

    def test_turns_recorded_while_the_curator_waits_are_curated_before_it_ends(self):
        said, _ = self.one_turn()

        def record():
            later, _ = self.one_turn('Name the script hook.py.', 'The script is hook.py now.')
            self.server.answers.append(answer(change(quote(later, 'Name the script hook.py'), kind='decision')))
        self.server.before[0] = record
        self.server.answers = [answer(change(quote(said, HOOKS), kind='decision'))]
        outcome = self.curate()
        self.assertEqual((outcome.reason, [a.turns for a in outcome.attempts]), ('done', [((LOG, 2),), ((LOG, 4),)]))
        self.assertEqual((self.progress()['logs'], self.progress()['applies'], len(self.items())), ({LOG: 5}, 2, 2))

    def test_three_stale_attempts_in_a_row_end_the_run_and_the_next_goes_on(self):
        said, _ = self.one_turn()
        other = C2Store(self.folder, expected_device=DEVICE)
        for number in range(3):
            self.server.before[number] = lambda: self.advance(other)
        self.server.answers = [answer(change(quote(said, HOOKS), kind='decision'))]
        outcome = self.curate()
        self.assertEqual((outcome.reason, [a.record['result'] for a in outcome.attempts]), ('stale', ['stale'] * 3))
        self.assertEqual((self.items(), self.progress()['logs']), ({}, {}))
        self.assertEqual(self.curate().reason, 'done')
        self.assertEqual((len(self.items()), self.progress()['logs']), (1, {LOG: 3}))

    def test_gates_end_the_run_before_any_request(self):
        self.one_turn()
        stored = self.snapshot()
        cases = (('disabled', lambda: self.configure(enabled=False)), ('consent', lambda: self.configure(consent=None)),
                 ('consent', lambda: self.configure(consent=2)),
                 ('key', lambda: os.environ.update(CORTHEX_MEMORY_ANTHROPIC_API_KEY='')))
        for reason, setting in cases:
            with self.subTest(reason=reason):
                setting()
                self.assertEqual(self.curate(), curation_worker.Outcome(reason, ()))
                self.configure()
        os.environ['CORTHEX_MEMORY_ANTHROPIC_API_KEY'] = self.keys['CORTHEX_MEMORY_ANTHROPIC_API_KEY']
        (self.folder / 'configuration.json').write_bytes(b'{"projects": 3}')
        self.assertEqual(self.curate().reason, 'configuration')
        self.assertEqual((self.server.requests, self.snapshot()), ([], stored))

    def test_a_lost_record_is_made_again_from_the_raw_log_before_curating(self):
        said, _ = self.one_turn()
        (self.root / 'curation.json').unlink()
        self.server.answers = [answer(change(quote(said, HOOKS), kind='decision'))]
        self.assertEqual(self.curate().reason, 'done')
        progress = self.progress()
        self.assertEqual((progress['logs'], progress['rebuilt'], progress['applies']), ({LOG: 3}, STAMP, 1))
        self.assertNotEqual(progress['fence']['epoch'], EPOCH)
        self.assertEqual(item_types.parse_notice((self.root / 'notices/rebuilt.json').read_bytes())['kind'], 'rebuilt')
        self.assertEqual(len(self.items()), 1)

    # What an apply writes

    def test_an_apply_counts_its_turns_logs_its_run_and_replaces_markers(self):
        said, _ = self.one_turn()
        marker = self.mark(said)
        goal = dict(id=ident('s'), part='goal', pos=1, text='Ship the plugin.', cites=[said['id']], at=AT,
                    device=DEVICE)
        self.layer(lines=[goal])
        added = {'part': 'decisions', 'after': '', 'text': 'One script serves the hooks.', 'cites': [], 'changes': [1]}
        self.server.answers = [answer(change(quote(said, HOOKS), kind='decision'),
                                      change(quote(said, 'Keep the five hooks in one script'), kind='decision'),
                                      state={'change': [], 'add': [added],
                                             'remove': [{'line': ident('s'), 'why': 'Not carried.'}]})]
        self.assertEqual(self.markers(), [marker])
        (attempt,) = self.curate().attempts
        self.assertEqual((attempt.dropped, attempt.edits, attempt.held, attempt.requests),
                         ({'quote': 1}, {'not-in-request': 1}, None, 1))
        progress = self.progress()
        record = progress['recent'][0]
        self.assertEqual(record, {'at': STAMP, 'kind': 'curate', 'result': 'ok', 'applied': 1, 'dropped': 1,
                                  'reasons': {'quote': 1}, 'state': 'new',
                                  'edit_reasons': {'not-in-request': 1}, 'run': record['run']})
        self.assertEqual((progress['logs'], progress['applies']), ({LOG: 3}, 1))
        self.assertEqual(self.markers(), [])
        (saved,) = self.items().values()
        self.assertEqual([value['cites'] for value in self.lines() if value['part'] == 'decisions'], [[saved['id']]])
        log = run_log.read(self.root, record['run'])
        self.assertTrue(run_log.eligible(log, progress, DEVICE))
        self.assertEqual((log['turns'], log['saved'], len(log['applies'])), ({LOG: [1, 3]}, [saved['id']], 2))
        text = (self.root / 'runs' / (record['run'] + '.json')).read_text(encoding='utf-8')
        self.assertNotIn('hooks', text)

    def test_tc161_tc178_tc182_the_record_counts_each_dropped_change(self):
        said, _ = self.one_turn('Here is the vendor note:\n<pasted_content id="p1">\nWe decided to drop the cache.\n'
                                '</pasted_content id="p1">\nI decide to keep the cache.', 'The cache stays.')
        self.server.answers = [answer(
            change(quote(said, 'We decided to drop the cache'), kind='decision', title='From the pasted note'),
            change(quote(said, 'I decide to keep the cache'), kind='decision', title='The user decides'),
            change(quote(said, 'I decide to keep the hats'), kind='decision', title='One word off'),
            change(quote(said, 'I decide to keep the cache'), title='T' * 201))]
        (attempt,) = self.curate().attempts
        self.assertEqual(attempt.dropped, {'pasted': 1, 'quote': 1, 'limit': 1})
        record = self.progress()['recent'][0]
        self.assertEqual(record, {'at': STAMP, 'kind': 'curate', 'result': 'ok', 'applied': 1, 'dropped': 3,
                                  'reasons': {'pasted': 1, 'quote': 1, 'limit': 1}, 'state': 'kept',
                                  'run': record['run']})
        (saved,) = self.items().values()
        self.assertEqual((saved['title'], saved['kind'], saved['quotes'][0]['speaker']),
                         ('The user decides', 'decision', 'user'))

    def test_tc172_answers_that_do_not_fit_fail_and_a_change_outside_the_request_is_dropped(self):
        said, _ = self.one_turn()
        other = start() + block(text=json.dumps(answer())) + end(reason='pause_turn')
        good = answer(change(quote(said, HOOKS), action='ADD', kind='DECISION', title='Read in small letters'),
                      change(quote(said, HOOKS), action='replace', targets=[ident('i')], title='Not in the request'))
        self.server.answers = [stream('The hooks stay in one script.')] * 3 + [stream({'changes': []})] * 3 + [good]
        records = []
        with self.quick() as waits:
            for reason in ('failed', 'failed', 'done'):
                outcome = self.curate()
                self.assertEqual(outcome.reason, reason)
                records.extend(outcome.attempts)
        self.one_turn('Name the script hook.py.', 'The script is hook.py now.')
        self.server.answers.extend([other] * 3)
        with self.quick() as more:
            self.assertEqual(self.curate().reason, 'failed')
        # The client tries a bad answer twice more within its attempt; the attempt counts one request.
        self.assertEqual((waits, more, len(self.server.requests)), ([10, 60, 10, 60], [10, 60], 10))
        self.assertEqual([(a.record['result'], a.record.get('error'), a.requests) for a in records],
                         [('failed', 'bad-answer', 1), ('failed', 'bad-answer', 1), ('ok', None, 1)])
        self.assertEqual((records[-1].record['applied'], records[-1].record['reasons'], records[-1].dropped),
                         (1, {'not-in-request': 1}, {'not-in-request': 1}))
        self.assertEqual([(value['title'], value['kind']) for value in self.items().values()],
                         [('Read in small letters', 'decision')])
        recent = self.progress()['recent']
        self.assertEqual((recent[0]['result'], recent[0]['error'], self.progress()['failures']['count']),
                         ('failed', 'bad-answer', 1))
        self.assertEqual([r['result'] for r in self.usage()], ['failed'] * 6 + ['ok'] + ['failed'] * 3)

    def test_tc359_an_answer_that_changes_nothing_writes_no_run_log(self):
        self.one_turn()
        self.server.answers = [answer()]
        (attempt,) = self.curate().attempts
        self.assertEqual(attempt.record, {'at': STAMP, 'kind': 'curate', 'result': 'ok', 'applied': 0, 'dropped': 0,
                                          'state': 'kept'})
        self.assertEqual((self.runs(), self.progress()['logs'], self.progress()['applies']), ([], {LOG: 3}, 1))

    def test_tc353_a_request_carries_an_open_candidate_and_both_of_its_items(self):
        said, _ = self.one_turn()
        first, second = self.saved(said, 'Keep the four hooks'), self.saved(said, 'in one script')
        candidate = dict(id=ident('c'), items=[first['id'], second['id']], at=AT, run=ident('r'), by='curate',
                         status='open')
        self.layer([first, second], candidates=[candidate])
        self.server.answers = [answer()]
        self.assertEqual(self.curate().reason, 'done')
        content = self.server.content(0)
        self.assertIn('<conflict id="%s" items="%s %s"' % (candidate['id'], first['id'], second['id']), content)
        for value in (first, second):
            self.assertIn('<item id="%s"' % value['id'], content)
        self.assertEqual(self.progress()['conflict_after'], candidate['id'])

    def test_tc387_bundles_rotate_whole_across_runs_and_none_starve(self):
        values = budget.items_of(400)
        candidates = [document_fixture.candidate(values[2 * k], values[2 * k + 1], at=budget.minute(k))
                      for k in range(200)]
        gone = document_fixture.item('Withdrawn item', budget.SOURCE, status='withdrawn')
        stale = document_fixture.candidate(values[0], gone, at=budget.minute(500))
        self.layer(values + [gone], candidates=candidates + [stale])
        self.index()
        order, pairs = [c['id'] for c in candidates], {c['id']: set(c['items']) for c in candidates}
        rng, after, seen = random.Random(387), None, set()
        for run in range(4):
            # Each run's turn names other items, so the word ranks change from run to run.
            words = ' and '.join('mark%04d' % n for n in rng.sample(range(400), 6))
            self.one_turn('Please check %s again.' % words, 'Noted.')
            self.server.answers = [answer()]
            self.assertEqual(self.curate().reason, 'done')
            root = ET.fromstring(self.server.content(len(self.server.requests) - 1))
            listed, conflicts = root.find('items'), root.find('conflicts')
            ids = {node.get('id') for node in listed.iter('item')}
            carried = [node.get('id') for node in conflicts.iter('conflict')]
            start = 0 if after is None else order.index(after) + 1
            expected = (order[start:] + order[:start])[:len(carried)]
            with self.subTest(run=run):
                self.assertEqual(listed.get('form'), 'part')
                self.assertEqual(sorted(carried), sorted(expected))
                self.assertEqual(carried, sorted(carried, key=order.index))
                self.assertTrue(all(pairs[c] <= ids for c in carried))
                self.assertEqual(conflicts.get('omitted'), str(200 - len(carried)))
                self.assertGreater(200 - len(carried), 0)
                self.assertNotIn(stale['id'], carried)
                self.assertNotIn(gone['id'], ids)
                self.assertEqual(self.progress()['conflict_after'], expected[-1])
            seen.update(carried)
            after = expected[-1]
        self.assertEqual(seen, set(order))

    def test_tc183_the_record_keeps_the_last_ten_attempts_newest_first(self):
        other = C2Store(self.folder, expected_device=DEVICE)
        plans = ('ok', 'refusal', 'drop', 'stale', 'max-tokens', 'line', 'refusal', 'ok', 'stale', 'ok')
        records = []
        for n, plan in enumerate(plans):
            said, _ = self.one_turn('Turn %02d keeps the hooks in one script.' % n, 'Done.')
            words = 'Turn %02d keeps the hooks' % n
            good = answer(change(quote(said, words), title='Turn %02d' % n))
            line = {'part': 'next', 'after': '', 'text': 'Line %02d.' % n, 'cites': [], 'changes': [1]}
            replies = {'ok': [good], 'refusal': [REFUSAL], 'max-tokens': [LIMIT], 'stale': [answer(), good],
                       'drop': [answer(change(quote(said, words)), change(quote(said, 'Turn %02d keeps no hooks' % n)))],
                       'line': [answer(change(quote(said, words), kind='decision'),
                                       state={'change': [], 'remove': [], 'add': [line]})]}[plan]
            if plan == 'stale':
                self.server.before[len(self.server.requests)] = lambda: self.advance(other)
            self.server.answers.extend(replies)
            records.extend(attempt.record for attempt in self.curate().attempts)
        self.assertEqual(len(records), 12)
        recent = self.progress()['recent']
        self.assertEqual(recent, records[::-1][:10])
        self.assertEqual([(r['result'], r.get('error'), r.get('applied'), r.get('dropped'), r.get('state'))
                          for r in recent],
                         [('ok', None, 1, 0, 'kept'), ('ok', None, 1, 0, 'kept'), ('stale', None, None, None, None),
                          ('ok', None, 1, 0, 'kept'), ('failed', 'refusal', None, None, None),
                          ('ok', None, 1, 0, 'new'), ('failed', 'max-tokens', None, None, None),
                          ('ok', None, 1, 0, 'kept'), ('stale', None, None, None, None),
                          ('ok', None, 1, 1, 'kept')])
        self.assertEqual([r.get('reasons') for r in recent], [None] * 9 + [{'quote': 1}])
        self.assertEqual(self.progress()['failures']['count'], 0)

    # SPEC-015

    def long_turn(self):
        """A turn of 250,000 tokens, which goes in parts, and its paragraphs; the test server counts it."""
        paragraphs = ['문단 %03d ' % n + '가나다라마바사아자차카타파하' * 300 for n in range(38)]
        # An ASCII paragraph among them makes the turn 250,000 tokens by the test server's counting rule.
        head, tail = '\n\n'.join(paragraphs[:10]) + '\n\n', '\n\n' + '\n\n'.join(paragraphs[10:])
        plain = sum(map(str.isascii, head + tail))
        other = -(-3 * (len(head + tail) - plain) // 2)
        filler = budget.prose(3 * (250000 - other - budget.rule('Done.')) - plain, 153)
        said, _ = self.one_turn(head + filler + tail, 'Done.')
        self.assertEqual(budget.rule(said['text']) + budget.rule('Done.'), 250000)
        self.server.counter = budget.body_rule
        return said, paragraphs

    def test_tc153_a_turn_of_250000_tokens_applies_once_every_part_has_succeeded(self):
        said, paragraphs = self.long_turn()
        ended = self.saved(said, paragraphs[0][:20], kind='fact')
        self.layer([ended])
        first, last = paragraphs[1][:30], paragraphs[-1][:30]
        found = []

        def reply(number, body):
            content = body['messages'][0]['content']
            part, parts = (int(n) for n in re.search(r' part="(\d+)" parts="(\d+)"', content).groups())
            found.append((part, parts))
            if failing_part and part == 2:
                return failing(400, 'invalid_request_error')
            if part == 1:
                return answer(change(quote(said, first), title='From the first part'),
                              change(quote(said, paragraphs[0][:20]), action='withdraw', targets=[ended['id']],
                                     title='Withdrawn'))
            if part == parts:
                return answer(change(quote(said, last), title='From the last part'),
                              change(quote(said, first), title='Quoted from another part'),
                              change(quote(said, paragraphs[0][:20]), action='replace', targets=[ended['id']],
                                     title='Replacing an ended item'))
            return answer()
        self.server.reply = reply
        failing_part = True
        outcome = self.curate()
        self.assertEqual((outcome.reason, outcome.attempts[0].requests), ('failed', 2))
        self.assertEqual(outcome.attempts[0].record['error'], 'invalid_request_error')
        self.assertEqual((self.progress()['logs'], self.items()), ({}, {ended['id']: ended}))
        parts = found[0][1]
        self.assertGreaterEqual(parts, 3)
        failing_part = False
        del found[:]
        outcome = self.curate()
        (attempt,) = outcome.attempts
        self.assertEqual(found, [(n, parts) for n in range(1, parts + 1)])
        self.assertEqual((attempt.requests, attempt.dropped), (parts, {'quote': 1, 'not-current': 1}))
        self.assertEqual({value['title']: value['status'] for value in self.items().values()},
                         {'From the first part': 'current', 'From the last part': 'current',
                          ended['title']: 'withdrawn'})
        progress = self.progress()
        self.assertEqual((progress['logs'], progress['applies'], progress['failures']['count']),
                         ({LOG: 3}, parts, 0))
        self.assertEqual((progress['recent'][0]['applied'], progress['recent'][0]['reasons']),
                         (3, {'quote': 1, 'not-current': 1}))
        frames = set()
        for number in range(2, 2 + parts):
            content = self.server.content(number)
            self.assertIn('id="%s"' % ended['id'], content)
            root = ET.fromstring(content)
            frames.add(tuple(ET.tostring(node, encoding='unicode') for node in
                             (root.find('state'), root.find('items'), root.find('conflicts')) if node is not None))
            (turn,) = root.iter('turn')
            self.assertEqual((turn.get('seq'), turn.get('part'), turn.get('parts')),
                             (str(said['seq']), str(number - 1), str(parts)))
            self.assertLess(budget.body_rule(self.server.requests[number][1]), 100000)
        self.assertEqual(len(frames), 1)

    # SPEC-015 through the worker (TASK-084)

    def test_tc152_fifty_turns_go_whole_once_oldest_first_under_100000(self):
        later = '2026-11-04T04:00:00.000Z'
        second = Raw('fixture-session-088-second')
        second.entries[0]['at'] = later
        for raw, number, seed, at in ((self.raw, 30, 0, AT), (second, 20, 2000, later)):
            for n in range(number):
                raw.turn(budget.prose(9000, seed + n), budget.prose(9000, seed + 1000 + n), at=at)
            (self.root / 'raw' / (raw.name + '.jsonl')).write_bytes(raw.data())
        self.assertEqual(sum(budget.rule(value['text']) for raw in (self.raw, second)
                             for value in raw.entries if 'text' in value), 300000)
        self.server.counter = budget.body_rule
        self.server.answers = [answer()]
        outcome = self.curate()
        self.assertEqual(outcome.reason, 'done')
        sent = self.sent()
        expected = [(raw.name, value['seq'], None) for raw in (self.raw, second) for value in raw.entries
                    if value['kind'] == 'prompt']
        self.assertEqual([turn for turns in sent for turn in turns], expected)
        self.assertGreater(len(sent), 2)
        self.assertTrue(all(budget.body_rule(body) < 100000 for _, body in self.server.requests))
        self.assertTrue(any(budget.body_rule(body) > 99000 for body in self.server.counts))
        self.assertEqual(self.progress()['logs'], {self.raw.name: 61, second.name: 41})
        self.assertEqual(self.markers(), [])
        calls = [row['call'] for row in self.usage()]
        self.assertEqual((calls.count('curate'), calls.count('count-tokens')), (len(sent), len(self.server.counts)))

    def test_tc155_a_list_of_60000_in_short_lines_goes_in_part_and_the_turns_are_curated(self):
        values = budget.items_of(450)
        self.assertGreaterEqual(budget.request_budget.safe(budget.curator_document._items(values, 'short')[1]), 60000)
        lines = [document_fixture.line('Ship the first release', [values[5]['id']], 'goal', 1),
                 document_fixture.line('Keep raw logs local', [values[10]['id']], 'decisions', 1),
                 document_fixture.line('Use the shared folder', [values[20]['id'], values[10]['id']], 'decisions', 2)]
        first = document_fixture.candidate(values[40], values[41], at=budget.minute(1))
        second = document_fixture.candidate(values[50], values[51], at=budget.minute(2))
        self.layer(values, lines, [second, first], pinned=[values[30]['id'], values[10]['id']])
        self.index()
        self.raw.turn('Please check mark0100 and mark0300 ' + budget.prose(30000, 155, words=budget.TALK),
                      'Noted mark0200 ' + budget.prose(30000, 156, words=budget.TALK))
        for n in range(5):
            self.raw.turn(budget.prose(30000, 200 + n, words=budget.TALK),
                          budget.prose(30000, 300 + n, words=budget.TALK))
        self.write()
        self.server.counter = budget.body_rule
        self.server.answers = [answer()]
        outcome = self.curate()
        self.assertEqual(outcome.reason, 'done')
        head = [values[n]['id'] for n in (5, 10, 20, 30, 40, 41, 50, 51)]
        for number, (_, body) in enumerate(self.server.requests):
            with self.subTest(request=number):
                root = ET.fromstring(body['messages'][0]['content'])
                listed = root.find('items')
                carried = [node.get('id') for node in listed.iter('item')]
                self.assertEqual((listed.get('form'), carried[:8]), ('part', head))
                self.assertEqual([node.get('id') for node in root.iter('conflict')], [first['id'], second['id']])
                # The list with the state and the candidates, as step 1 measures it, stays within 40,000.
                self.assertLessEqual(budget.request_budget.safe(budget.FIXED + budget.curator_document.curate(
                    lines=lines, items=[value for value in values if value['id'] in carried], form='part',
                    sessions=[], candidates=[first, second])), 40000)
                self.assertLess(budget.body_rule(body), 100000)
                if number == 0:
                    self.assertTrue({values[n]['id'] for n in (100, 200, 300)} <= set(carried[8:]))
        sent = self.sent()
        self.assertGreater(len(sent), 1)
        self.assertEqual([turn for turns in sent for turn in turns],
                         [(LOG, value['seq'], None) for value in self.raw.entries if value['kind'] == 'prompt'])
        progress = self.progress()
        self.assertEqual((progress['logs'], progress['conflict_after']), ({LOG: 13}, second['id']))
        self.assertEqual(progress['consolidation'].get('due'), STAMP)

    # TASK-116: each request's size in its usage lines, and the distribution from the usage logs alone

    def test_tc421_usage_lines_hold_each_request_size_and_the_logs_give_the_distribution(self):
        # A line written before the size fields, in an earlier month's log.
        earlier = dict(at='2026-10-30T10:00:00.000Z', project='sample', call='curate', model='claude-haiku-5-5',
                       instructions='curate-2', input=120000, output=900, total_ms=5000, result='ok', cost=.1,
                       prices='2026-10-25')
        (self.folder / 'logs' / 'usage-2026-10.jsonl').write_bytes(base.json_bytes(earlier, 'TBL-003', compact=True))
        self.server.counter = budget.body_rule
        cached = 1000

        def reply(number, body):
            # The usage reports each request's tokens by the server's counting rule, the first with a cache read.
            tokens, cache = budget.body_rule(body), cached if number == 0 else 0
            usage = {'input_tokens': tokens - cache, 'cache_read_input_tokens': cache, 'output_tokens': 1}
            return start(usage=usage) + block(text=json.dumps(answer())) + end(output=300)
        self.server.reply = reply
        # The request documents as the worker builds them, before redaction, which the estimates read.
        sources, send = [], model_client.send

        def spy(*args, **kwargs):
            sources.append(kwargs['source'])
            return send(*args, **kwargs)
        with mock.patch.object(model_client, 'send', side_effect=spy):
            # Whole turns beside the full list.
            for n in range(3):
                self.raw.turn(budget.prose(2000, 421 + n), budget.prose(2000, 521 + n))
            self.write()
            self.assertEqual(self.curate().reason, 'done')
            # One turn whose count passes 99,000 goes in parts beside the full list.
            self.raw.turn(budget.prose(170000, 621), budget.prose(170000, 622))
            self.write()
            self.assertEqual(self.curate().reason, 'done')
            # Whole turns beside a list that passes 40,000 in full and goes in short lines.
            values = [document_fixture.item('Long item %02d' % n, budget.SOURCE, said=budget.day(n),
                                            text=budget.prose(3000, 700 + n)) for n in range(30)]
            self.layer(values)
            for n in range(2):
                self.raw.turn(budget.prose(2000, 821 + n), budget.prose(2000, 921 + n))
            self.write()
            self.assertEqual(self.curate().reason, 'done')
        self.assertEqual(len(sources), len(self.server.requests))
        forms, expected = [], []
        for (_, body), source in zip(self.server.requests, sources):
            root = ET.fromstring(body['messages'][0]['content'])
            turns = list(root.iter('turn'))
            size = {'turns': len(turns), 'list': root.find('items').get('form'),
                    'estimate': budget.request_budget.estimate('curate-2', budget.SCHEMA, source)}
            if turns[0].get('parts') is not None:
                size['parts'] = int(turns[0].get('parts'))
            forms.append((size['turns'], size.get('parts'), size['list']))
            expected.append((budget.body_rule(body), size))
        parts = forms[1][1]
        self.assertGreaterEqual(parts, 2)
        self.assertEqual(forms, [(3, None, 'full')] + [(1, parts, 'full')] * parts + [(2, None, 'short')])
        rows = [row for row in self.usage() if row['call'] == 'curate']
        self.assertEqual(rows[0], earlier)
        self.assertEqual([(row.get('input', 0) + row.get('cache_read', 0), {key: row[key] for key in
                                                                            ('turns', 'parts', 'list', 'estimate')
                                                                            if key in row}) for row in rows[1:]],
                         expected)
        self.assertEqual(rows[1]['cache_read'], cached)
        # The distribution from the usage logs alone matches the requests that the server saw.
        logs = [path.read_bytes() for path in sorted((self.folder / 'logs').glob('usage-*.jsonl'))]
        found = model_usage.sizes(logs, project='sample')
        tokens = sorted([120000] + [value for value, _ in expected])
        self.assertEqual((found['requests'], found['unreadable'], found['unrecorded']), (len(tokens), 0, 1))
        self.assertEqual((found['median'], found['p95']),
                         (statistics.median(tokens), tokens[math.ceil(len(tokens) * .95) - 1]))
        for limit in (60000, 100000):
            above = [(value, size) for value, size in expected if value > limit]
            with self.subTest(over=limit):
                self.assertEqual(found['over'][limit], {
                    'requests': len(above) + 1, 'share': (len(above) + 1) / len(tokens),
                    'turns': {'parts': sum('parts' in size for _, size in above),
                              'one': sum('parts' not in size and size['turns'] == 1 for _, size in above),
                              'several': sum(size['turns'] > 1 for _, size in above)},
                    'list': {form: sum(size['list'] == form for _, size in above) for form in ('full', 'short', 'part')},
                    'above_estimate': sum(value > size['estimate'] for value, size in above), 'unrecorded': 1})
        self.assertGreater(found['over'][60000]['turns']['parts'], 0)
        self.assertEqual(found['over'][100000]['requests'], 1)


    # What a request may read and carry (review of TASK-088)

    def test_turns_go_oldest_first_across_sessions(self):
        other = Raw(SESSION + '-other')
        text = budget.prose(70000, 88)
        early, _ = self.raw.turn('Early. ' + text, 'Noted.', at='2026-11-04T09:00:00.000Z')
        middle, _ = other.turn('Middle. ' + text, 'Noted.', at='2026-11-04T10:00:00.000Z')
        late, _ = self.raw.turn('Late. ' + text, 'Noted.', at='2026-11-04T11:00:00.000Z')
        self.write()
        (self.root / 'raw' / (other.name + '.jsonl')).write_bytes(other.data())
        self.server.answers = [answer()]
        outcome = self.curate()
        self.assertEqual(outcome.reason, 'done')
        # Two turns fit a request: the oldest two of all, not the first session's two.
        self.assertEqual(self.sent(), [[(LOG, early['turn'], None), (other.name, middle['turn'], None)],
                                       [(LOG, late['turn'], None)]])
        self.assertEqual(self.progress()['logs'], {LOG: 5, other.name: 3})

    def test_a_link_in_the_project_folder_ends_the_run_before_anything_is_sent(self):
        said, _ = self.one_turn()
        value = self.saved(said, HOOKS)
        self.layer(items=[value])
        outside = self.folder.parent / 'outside'
        outside.mkdir()
        self.server.answers = [answer()]
        cases = (('raw log', self.root / 'raw' / (LOG + '.jsonl')),
                 ('item', self.root / 'layer/items' / (value['id'] + '.json')),
                 ('state', self.root / 'layer/state.json'))
        for name, path in cases:
            with self.subTest(file=name):
                target = outside / path.name
                target.write_bytes(path.read_bytes())
                path.unlink()
                try:
                    path.symlink_to(target)
                except OSError:
                    path.write_bytes(target.read_bytes())
                    self.skipTest('file symlinks require host permission')
                try:
                    self.assertEqual(self.curate(), curation_worker.Outcome('lost-lock', ()))
                    self.assertEqual((self.server.requests, self.server.counts), ([], []))
                finally:
                    path.unlink()
                    path.write_bytes(target.read_bytes())
        self.assertEqual(self.curate().reason, 'done')
        self.assertEqual(len(self.server.requests), 1)

    def test_a_project_tombstone_ends_the_run_before_anything_is_read_or_sent(self):
        said, _ = self.one_turn()
        stored = self.snapshot()
        tombstone = item_types._raw({'project': 'sample', 'at': STAMP, 'device': DEVICE}) + b'\n'
        for name in ('deleted.json', 'deleted.json.bak', 'deleted.json.tmp'):
            with self.subTest(name=name):
                path = self.root / 'layer' / name
                path.write_bytes(tombstone)
                self.assertEqual(self.curate(), curation_worker.Outcome('deleted', ()))
                path.unlink()
        self.assertEqual((self.server.requests, self.server.counts, self.snapshot()), ([], [], stored))
        self.server.answers = [answer(change(quote(said, HOOKS), kind='decision'))]
        self.assertEqual(self.curate().reason, 'done')

    def test_a_request_that_fails_after_a_forget_is_stale_not_a_failure(self):
        said, _ = self.one_turn()
        other = C2Store(self.folder, expected_device=DEVICE)
        for number in range(2):
            self.server.before[number] = lambda: self.advance(other)
        bad = start() + block(text='{"changes": 3}') + end()
        self.server.answers = [REFUSAL, bad, answer(change(quote(said, HOOKS), kind='decision'))]
        outcome = self.curate()
        self.assertEqual((outcome.reason, [a.record['result'] for a in outcome.attempts]),
                         ('done', ['stale', 'stale', 'ok']))
        progress = self.progress()
        self.assertEqual(('failures' in progress, self.notice()), (False, None))
        self.assertEqual((progress['logs'], len(self.items())), ({LOG: 3}, 1))
        # Without a forget meanwhile, the same refusal counts.
        self.one_turn('Name the script hook.py.', 'The script is hook.py now.')
        self.server.answers.append(REFUSAL)
        outcome = self.curate()
        self.assertEqual((outcome.reason, outcome.attempts[0].record['error']), ('failed', 'refusal'))
        self.assertEqual(self.progress()['failures']['count'], 1)

    def decision_and_line(self):
        said, _ = self.one_turn()
        added = {'part': 'decisions', 'after': '', 'text': 'One script serves the hooks.', 'cites': [],
                 'changes': [1]}
        self.server.answers = [answer(change(quote(said, HOOKS), kind='decision'),
                                      state={'change': [], 'add': [added], 'remove': []})]

    def test_line_edits_that_fail_after_the_item_changes_keep_the_state_and_count_the_turns(self):
        self.decision_and_line()
        with mock.patch.object(curation_worker.state_edits, 'apply', side_effect=OSError('one-shot')):
            outcome = self.curate()
        (attempt,) = outcome.attempts
        self.assertEqual((outcome.reason, attempt.held, len(self.server.requests)), ('done', 'OSError', 1))
        progress = self.progress()
        record = progress['recent'][0]
        self.assertEqual(record, {'at': STAMP, 'kind': 'curate', 'result': 'ok', 'applied': 1, 'dropped': 0,
                                  'state': 'kept', 'run': record['run']})
        # The decision is saved once, the state is as it was, and the turns count (SPEC-017).
        self.assertEqual((progress['logs'], progress['applies'], len(self.items()), self.lines()),
                         ({LOG: 3}, 1, 1, []))
        self.assertEqual((self.notice(), self.failures()), (None, [('curate', 'OSError')]))

    def test_a_failure_after_the_line_edits_moved_the_fence_is_a_failure_not_stale(self):
        self.decision_and_line()
        real = curation_worker.state_edits.apply

        def published_then_failed(*args, **kwargs):
            real(*args, **kwargs)
            raise OSError('after the state was published')
        with mock.patch.object(curation_worker.state_edits, 'apply', side_effect=published_then_failed):
            outcome = self.curate()
        self.assertEqual((outcome.reason, [a.record['result'] for a in outcome.attempts], len(self.server.requests)),
                         ('failed', ['failed'], 1))
        progress = self.progress()
        self.assertEqual((progress['logs'], progress['failures']['count'], self.notice()['error']), ({}, 1, 'OSError'))
        # What was published stays, and the next run curates the turns again (TBL-009).
        self.assertEqual((len(self.items()), len(self.lines())), (1, 1))

    def test_a_check_that_fails_is_stale_before_the_attempt_publishes_and_a_failure_after(self):
        said, _ = self.one_turn()
        self.server.answers = [answer(change(quote(said, HOOKS), kind='decision'))] * 2
        real, calls = curation_worker.curate_apply.apply, []

        def stale_once(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise fence_plan.Stale()
            return real(*args, **kwargs)
        with mock.patch.object(curation_worker.curate_apply, 'apply', side_effect=stale_once):
            outcome = self.curate()
        self.assertEqual(([a.record['result'] for a in outcome.attempts], len(self.server.requests), len(self.items())),
                         (['stale', 'ok'], 2, 1))
        named, _ = self.one_turn('Name the script hook.py.', 'The script is hook.py now.')
        self.server.answers = self.server.answers[:2] + [answer(change(quote(named, 'Name the script hook.py'),
                                                                       kind='decision'))]
        with mock.patch.object(curation_worker.run_log, 'write', side_effect=fence_plan.Stale()):
            outcome = self.curate()
        self.assertEqual((outcome.reason, [a.record['result'] for a in outcome.attempts], len(self.server.requests)),
                         ('failed', ['failed'], 3))
        self.assertEqual((len(self.items()), self.progress()['failures']['count']), (2, 1))


if __name__ == '__main__':
    unittest.main()
