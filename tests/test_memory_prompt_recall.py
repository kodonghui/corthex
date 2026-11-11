"""TASK-094: recall for a prompt as the prompt hook runs it for a format-2 store (API-002 steps 5, 7 and 9).

TC-205, TC-207, TC-209, TC-211, TC-212, TC-213, TC-215, TC-217, TC-220 and
TC-405 at the direct boundary, on made-up format-2 stores. Every embedding
request goes to a local test server, with keys made up during the run; no
provider is called. Nothing calls the module before the 0.3.0 activation, so the
hook's own reading of its input, recording, timing line and exit stay C1's until
then.
"""
from datetime import timezone
import json
import os
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
import unicodedata
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import (clock, locks, model_client, model_embed, model_transport, model_usage, prompt_recall, raw_log,
                        recall, request_budget, start_memory)
import test_memory_curation_worker as worker_fixture
import test_memory_recall as recall_fixture

MODEL, DIMS, SESSION, HOST = recall_fixture.MODEL, recall_fixture.DIMS, recall_fixture.SESSION, recall_fixture.HOST
PROMPT, DAY, UTC = recall_fixture.PROMPT, recall_fixture.DAY, timezone.utc
QUESTION = 'Which hooks does memory keep?'
toward, ident = recall_fixture.toward, worker_fixture.ident


class PromptRecallTest(unittest.TestCase):
    """Recall through the prompt's embedding, on the curation worker's store fixture and recall's helpers."""
    Fixture, Ranking = worker_fixture.CurationWorkerTest, recall_fixture.RecallTest
    configure, layer, saved, one_turn, items, write, usage = (
        Fixture.configure, Fixture.layer, Fixture.saved, Fixture.one_turn, Fixture.items, Fixture.write,
        Fixture.usage)
    item, index, vectors, store, settings, lines, quoting = (
        Ranking.item, Ranking.index, Ranking.vectors, Ranking.store, Ranking.settings, Ranking.lines, Ranking.quoting)

    def setUp(self):
        self.Fixture.setUp(self)
        self.keys['CORTHEX_MEMORY_OPENAI_API_KEY'] = 'memory-openai-key-' + secrets.token_hex(12)
        self.keys['CORTHEX_MEMORY_OPENAI_BASE_URL'] = self.server.url
        environment = mock.patch.dict(os.environ, {name: self.keys[name] for name in (
            'CORTHEX_MEMORY_OPENAI_API_KEY', 'CORTHEX_MEMORY_OPENAI_BASE_URL')})
        environment.start()
        self.addCleanup(environment.stop)
        self.configure(models={'dims': DIMS}, recall={'threshold': 0.4})
        self.said, _ = self.one_turn()
        self.answer = list(PROMPT)  # the prompt's vector that the test server gives
        self.server.reply = self.embeddings

    def embeddings(self, number, body):
        document = {'object': 'list', 'model': body['model'], 'usage': {'prompt_tokens': 9},
                    'data': [{'object': 'embedding', 'index': 0, 'embedding': self.answer}]}
        return lambda handler: worker_fixture.Server.send(handler, json.dumps(document).encode('utf-8'),
                                                          mime='application/json')

    def recall(self, prompt=QUESTION, *, seconds=30, embed=30, session=SESSION):
        """Step 5 with the hook's start now; the deadlines are long unless a test asks for the hook's own."""
        started = clock.now()
        with mock.patch.object(prompt_recall, 'EMBED_SECONDS', embed):
            return prompt_recall.recall(self.memory, 'sample', HOST, session, prompt, started, started + seconds,
                                        settings=self.settings(), zone=UTC)

    def log(self, result, entry=None, session=SESSION):
        return prompt_recall.log(self.memory, 'sample', HOST, session, result, entry=entry)

    def three(self):
        """Items whose cosines with the test server's prompt vector are 0.2, 0.9 and 0.5."""
        return self.store((self.item('Low'), toward(0.2)), (self.item('High'), toward(0.9, 2)),
                          (self.item('Middle'), toward(0.5, 3)))

    def raw_files(self):
        return {path.relative_to(self.root).as_posix(): path.read_bytes()
                for path in sorted((self.root / 'raw').rglob('*')) if path.is_file()}

    def assertScores(self, found, expected):
        self.assertEqual([item for item, _ in found], [item for item, _ in expected])
        for (_, score), (_, wanted) in zip(found, expected):
            self.assertAlmostEqual(score, wanted, places=6)

    # SPEC-023's first acceptance criterion through the embedding, and SPEC-024

    def test_tc205_the_prompt_s_vector_injects_the_items_at_the_threshold_and_the_line_names_them(self):
        low, high, middle = self.three()
        result = self.recall()
        self.assertEqual((result.outcome, result.items, result.error), ('injected', (high['id'], middle['id']), None))
        self.assertScores(result.candidates, [(high['id'], 0.9), (middle['id'], 0.5), (low['id'], 0.2)])
        self.assertEqual(result.block, '\n'.join([
            start_memory.REFERENCE,
            '- %s | fact | user | %s | High holds. | reread: %s' % (high['id'], DAY, self.said['id']),
            '- %s | fact | user | %s | Middle holds. | reread: %s' % (middle['id'], DAY, self.said['id'])]))
        # One request, with the configured model and length, the memory key and the prompt alone.
        (headers, body), = self.server.requests
        self.assertEqual(body, {'model': MODEL, 'input': [QUESTION], 'dimensions': DIMS, 'encoding_format': 'float'})
        self.assertEqual(headers['authorization'], 'Bearer ' + self.keys['CORTHEX_MEMORY_OPENAI_API_KEY'])
        usage, = self.usage()
        self.assertEqual((usage['project'], usage['call'], usage['model'], usage['result']),
                         ('sample', 'embed-prompt', MODEL, 'ok'))
        # Step 7 prints the block as the hook's added context, in ASCII.
        printed = prompt_recall.output(result)
        self.assertTrue(printed.endswith(b'\n') and printed.count(b'\n') == 1)
        self.assertEqual(json.loads(printed.decode('ascii')), {'hookSpecificOutput': {
            'hookEventName': 'UserPromptSubmit', 'additionalContext': result.block}})
        # Step 9's line names the prompt's entry, what was shown and the candidates, without any text.
        entry = ident('e')
        self.assertTrue(self.log(result, entry))
        line, = self.lines()
        self.assertEqual((line['where'], line['prompt'], line['outcome'], line['items']),
                         ('prompt', entry, 'injected', [high['id'], middle['id']]))
        self.assertEqual(line['scores'], list(result.scores))
        self.assertEqual(line['candidates'], [{'item': item, 'score': score} for item, score in result.candidates])
        data = (self.root / 'injections' / (raw_log.log_name(HOST, SESSION) + '.jsonl')).read_bytes()
        self.assertNotIn(b'holds', data)
        self.assertNotIn(QUESTION.encode('utf-8'), data)
        # The next prompt of the session leaves out what this one showed (TC-366), and its line keeps the candidate.
        again = self.recall()
        self.assertEqual((again.outcome, again.items), ('below', ()))
        self.assertScores(again.candidates, [(low['id'], 0.2)])
        self.assertTrue(self.log(again, ident('e')))
        line = self.lines()[1]
        self.assertEqual((line['outcome'], line['items'], line['candidates']),
                         ('below', [], [{'item': low['id'], 'score': again.candidates[0][1]}]))

    # SPEC-148: where to read a source again, through the prompt's embedding (TC-405)

    def test_tc405_a_recalled_item_s_line_ends_with_its_entry_and_the_path_in_its_quote(self):
        value, said = self.quoting('Locks', 'the fix in tests/test_memory_locks.py stayed')
        self.store((value, toward(0.9)))
        result = self.recall()
        self.assertEqual(result.outcome, 'injected')
        line = '- %s | fact | user | %s | Locks holds. | reread: %s, tests/test_memory_locks.py' % (value['id'], DAY,
                                                                                                  said['id'])
        self.assertEqual(result.block, '\n'.join([start_memory.REFERENCE, line]))
        printed = json.loads(prompt_recall.output(result))['hookSpecificOutput']['additionalContext']
        self.assertEqual(printed.split('\n')[-1], line)
        self.assertNotIn('stayed', printed)

    def test_tc405_recalled_items_with_long_pointers_lose_them_from_the_last_line_back_and_all_stay(self):
        pairs = []
        for n in range(5):
            words = 'see d/%s.md and e/%s.md' % (chr(97 + n) * 75, chr(102 + n) * 75)
            pairs.append((self.quoting('Item %d %s' % (n, 'w' * 60), words)[0], toward(0.9 - 0.05 * n, n + 1)))
        values = self.store(*pairs)
        result = self.recall()
        self.assertEqual(result.items, tuple(item['id'] for item in values))
        self.assertLess(request_budget.safe(result.block), recall.TOKENS)
        self.assertEqual([' | reread: ' in row for row in result.block.split('\n')[1:]], [True, True, False, False, False])

    def test_the_block_is_printed_in_ascii_and_nothing_is_printed_without_one(self):
        value = self.item('Korean', text='훅은 한 스크립트가 맡습니다.')
        self.store((value, toward(0.8)))
        result = self.recall()
        printed = prompt_recall.output(result)
        printed.decode('ascii')
        self.assertEqual(json.loads(printed)['hookSpecificOutput']['additionalContext'], result.block)
        self.assertIn('훅은 한 스크립트가 맡습니다.', result.block)
        for outcome in ('below', 'short', 'late', 'failed'):
            self.assertEqual(prompt_recall.output(prompt_recall.Result(outcome)), b'')

    # SPEC-023's third acceptance criterion

    def test_tc207_an_embedding_that_answers_after_two_seconds_ends_800_ms_after_the_start(self):
        self.three()
        settings, before = self.settings(), self.raw_files()
        spans, stalls, slow, waits, checks = {}, [], [], [], []
        once = model_transport.once

        def timed(name, call):
            """`call`, noting when it began and ended under `name`."""
            def run(*arguments, **options):
                spans[name] = [clock.now(), None]
                try:
                    return call(*arguments, **options)
                finally:
                    spans[name][1] = clock.now()
            return run

        def at(name, end=0):
            moment = spans.get(name, (None, None))[end]
            return 'never' if moment is None else '%.3f s' % (moment - started)

        def send(*arguments, check, **options):
            """The request, noting when each check of the hook's deadline that it makes began and ended."""
            def checking():
                entry = [clock.now(), None]
                checks.append(entry)
                try:
                    return check()
                finally:
                    entry[1] = clock.now()
            return once(*arguments, check=checking, **options)

        class Wake(threading.Event):
            """The request's wake, noting for each wait with a time limit the limit, when it began and when it woke."""
            def wait(self, timeout=None):
                began = clock.now()
                try:
                    return super().wait(timeout)
                finally:
                    if timeout is not None:
                        waits.append((timeout, began, clock.now()))

        class Threading:
            """The threading module as the transport sees it, with its wake being a `Wake`."""
            Event = Wake

            def __getattr__(self, name):
                return getattr(threading, name)

        def moment(value):
            return 'never' if value is None else '%.3f s' % (value - started)

        def last_wait():
            if not waits:
                return 'it never waited'
            limit, began, woke = waits[-1]
            return 'its last wait asked for %.3f s at %s and woke at %s' % (limit, moment(began), moment(woke))

        def last_check():
            if not checks:
                return 'it never checked the deadline'
            began, ended = checks[-1]
            return 'its last check of the deadline ran from %s to %s' % (moment(began), moment(ended))

        def slowly(number, body):
            time.sleep(2)
            return self.embeddings(number, body)
        # The request has to start within the embedding's 800 ms and reach the server, and recall has to notice its
        # end and take its own steps after it, such as the attempt's usage line, before the hook's deadline, 100 ms
        # later. On busy macOS runners the steps before the request took all of the 800 ms in two of three runs
        # (2026-11-09), and in #187's last run (2026-11-10) the runner woke the request's waits as much as 155 ms
        # late, the last one, asked to end at 0.76 to 0.80 s, at 0.881 to 0.905 s, while its last check of the
        # deadline took 1 ms or less and recall's steps after the last wake 14 to 35 ms, and recall ended at 0.905 to
        # 0.933 s; one runner did so in four tries running. Recall is then late, as stage 06 says, and the case is
        # tried again, up to `tries` times, saying when each step began and ended, how late the request's waits woke
        # and when it last checked the deadline. The server answers each request after two seconds, and each try's
        # prompt names the try, so that a request is counted only for its own try.
        self.server.reply = slowly
        # The hook's deadline (SPEC-008) and the embedding's end (API-010), in seconds after the hook's start.
        tries, hook, embedding = 10, 0.9, 0.8
        for number in range(1, tries + 1):
            prompt = '%s Try %d.' % (QUESTION, number)
            spans.clear()
            waits.clear()
            checks.clear()
            used = len(self.usage())
            mine = lambda: [body for _, body in self.server.requests if body['input'] == [prompt]]
            started = clock.now()
            attempt = model_usage.Attempt
            with mock.patch.object(recall, 'ready', side_effect=timed('look', recall.ready)), \
                    mock.patch.object(model_embed, 'embed', side_effect=timed('embed', model_embed.embed)), \
                    mock.patch.object(attempt, 'start', side_effect=timed('start', attempt.start)), \
                    mock.patch.object(model_transport, 'once', side_effect=timed('send', send)), \
                    mock.patch.object(model_transport, 'threading', Threading()), \
                    mock.patch.object(subprocess.Popen, 'kill', autospec=True,
                                      side_effect=timed('kill', subprocess.Popen.kill)), \
                    mock.patch.object(model_client, '_account', side_effect=timed('account', model_client._account)):
                result = prompt_recall.recall(self.memory, 'sample', HOST, SESSION, prompt, started, started + hook,
                                              settings=settings, zone=UTC)
                elapsed = clock.now() - started
            # The test server records a request as it reads it, which can come just after a request that started at
            # the end of the 800 ms; one that started too late to reach it at all makes a stalled try too.
            until = clock.now() + 1
            while 'send' in spans and not mine() and clock.now() < until:
                time.sleep(0.01)
            late = max([woke - began - limit for limit, began, woke in waits], default=0)
            steps = ('the index look ran from %s to %s, the embedding call from %s to %s, its attempt from %s to %s, '
                     'its request from %s to %s, its waits woke up to %d ms later than asked, %s, %s, its child was '
                     'killed at %s, its usage line was written from %s to %s, and recall ended at %.3f s'
                     % (at('look'), at('look', 1), at('embed'), at('embed', 1), at('start'), at('start', 1),
                        at('send'), at('send', 1), round(late * 1000), last_wait(), last_check(), at('kill'),
                        at('account'), at('account', 1), elapsed))
            # A try is late if recall is late with the hook's `deadline` while the request's last wait was for no
            # later than the request's own end: recall then found the deadline passed when it noticed that end or in
            # its steps after it. A request that waited past its 800 ms is not tried again.
            late_try = (result == prompt_recall.Result('late', error='deadline') and bool(waits) and
                        waits[-1][1] + waits[-1][0] - started <= embedding + 0.02)
            if mine() and not late_try:
                break
            if mine():
                stalls.append("the request reached the test server and ran to its end, but recall then found the "
                              "hook's deadline passed: " + steps)
                print('\nTC-207: ' + stalls[-1], file=sys.stderr)
                # Such a try is the runner's when its late wake alone made it late: had the request's last wait woken
                # when it asked, recall would have ended in time, so its own steps after that wake, such as its checks
                # of the deadline, the attempt's clean-up and its usage line, have to fit in the hook's last 100 ms
                # after the request's end; in #187's late tries they took 14 to 35 ms. The case cannot tell one stall
                # of the runner there from slow code, so it allows one try whose steps needed more and fails at the
                # second.
                limit, began, woke = waits[-1]
                if elapsed - (woke - started) > hook - max(embedding, began + limit - started):
                    slow.append(stalls[-1])
                self.assertLess(len(slow), 2, "recall's own steps after the request's last wake took too long in two "
                                'tries: ' + '; '.join(slow))
                # Recall is late with `deadline`, as stage 06 says for a deadline that passes before recall can rank,
                # with no block, well before the server's answer, and with one usage line for the attempt: an
                # attempt that the check ended has no code, and one that timed out before the check ended recall
                # has `timeout`.
                self.assertEqual(prompt_recall.output(result), b'', stalls[-1])
                self.assertLess(elapsed, 1.5, stalls[-1])
                usages = self.usage()[used:]
                self.assertIn([(usage['call'], usage['result'], usage.get('error')) for usage in usages],
                              [[('embed-prompt', 'failed', None)], [('embed-prompt', 'failed', 'timeout')]],
                              stalls[-1])
                self.assertLess(usages[0]['total_ms'], 1500, stalls[-1])
                continue
            stalls.append('no request reached the test server: ' + steps)
            print('\nTC-207: ' + stalls[-1], file=sys.stderr)
            # Recall is late: when its request started, with `timeout`, or with `deadline` if the hook's own
            # deadline passed too before recall ended; otherwise with `deadline` and no usage line, since no request
            # was counted.
            if 'send' in spans:
                self.assertIn(result, [prompt_recall.Result('late', error=error) for error in ('timeout', 'deadline')],
                              stalls[-1])
            else:
                self.assertEqual((result, self.usage()[used:]), (prompt_recall.Result('late', error='deadline'), []),
                                 stalls[-1])
        else:
            self.fail("TC-207: in %d tries no request both reached the test server and let recall end with "
                      "`timeout` rather than the hook's `deadline`; %s" % (tries, '; '.join(stalls)))
        self.assertEqual((result.outcome, result.block, result.items, result.candidates, result.error),
                         ('late', '', (), (), 'timeout'), steps)
        self.assertLess(elapsed, 1.0, steps)
        self.assertGreaterEqual(elapsed, embedding - 0.01, steps)
        self.assertEqual(prompt_recall.output(result), b'', steps)
        self.assertEqual(len(mine()), 1, steps)
        usages = self.usage()[used:]
        self.assertEqual([(usage['call'], usage['result'], usage.get('error')) for usage in usages],
                         [('embed-prompt', 'failed', 'timeout')], steps)
        self.assertLess(usages[0]['total_ms'], hook * 1000, steps)
        # Recall writes nothing to the raw log, so the recorded prompt stays as it was.
        self.assertEqual(self.raw_files(), before)
        self.assertTrue(self.log(result, ident('e')))
        line, = self.lines()
        self.assertEqual((line['outcome'], line['items']), ('late', []))
        self.assertNotIn('candidates', line)
        self.assertNotIn('scores', line)

    def test_the_request_ends_800_ms_after_the_start_or_at_the_hook_s_deadline_if_that_is_sooner(self):
        self.three()
        embed, deadlines = model_embed.embed, []

        def watched(memory, **options):
            deadlines.append(options['deadline'])
            return embed(memory, **options)
        expected = []
        with mock.patch.object(model_embed, 'embed', side_effect=watched):
            for seconds in (0.9, 30, 0.7):
                started = clock.now()
                expected.append(started + min(seconds, 0.8))
                prompt_recall.recall(self.memory, 'sample', HOST, SESSION, QUESTION, started, started + seconds,
                                     settings=self.settings(), zone=UTC)
        self.assertEqual(deadlines, expected)
        # The hook's deadline passing as the request ends makes recall late, not failed.
        with mock.patch.object(model_embed, 'embed', side_effect=locks.LockBusy()):
            self.assertEqual(self.recall(), prompt_recall.Result('late', error='deadline'))

    # SPEC-023's fifth acceptance criterion, with SPEC-006

    def test_tc209_a_prompt_left_out_of_recording_is_recalled_and_its_line_names_no_entry(self):
        _, high, middle = self.three()
        document = json.loads((self.folder / 'configuration.json').read_bytes())
        document['projects']['sample']['left_out'] = {'kinds': ['prompt']}
        (self.folder / 'configuration.json').write_bytes(json.dumps(document).encode('utf-8'))
        before = self.raw_files()
        result = self.recall()
        self.assertEqual((result.outcome, result.items), ('injected', (high['id'], middle['id'])))
        self.assertTrue(self.log(result))
        line, = self.lines()
        self.assertNotIn('prompt', line)
        self.assertEqual(line['items'], [high['id'], middle['id']])
        self.assertEqual(self.raw_files(), before)

    # SPEC-036's first and second acceptance criteria

    def test_tc211_tc212_a_disabled_project_recalls_and_logs_nothing_until_it_is_on_again(self):
        _, high, middle = self.three()
        index = (self.root / 'index.db').read_bytes()
        layer = {path.name: path.read_bytes() for path in (self.root / 'layer' / 'items').iterdir()}
        self.configure(enabled=False, models={'dims': DIMS}, recall={'threshold': 0.4})
        result = self.recall()
        self.assertEqual(result, prompt_recall.Result(None))
        self.assertFalse(self.log(result, ident('e')))
        self.assertEqual(self.server.requests, [])
        self.assertEqual(self.usage(), [])
        self.assertFalse((self.root / 'injections').exists())
        self.assertEqual({path.name: path.read_bytes() for path in (self.root / 'layer' / 'items').iterdir()}, layer)
        # Turned on again, the index that was there recalls the earlier items.
        self.configure(enabled=True, models={'dims': DIMS}, recall={'threshold': 0.4})
        result = self.recall()
        self.assertEqual((result.outcome, result.items), ('injected', (high['id'], middle['id'])))
        self.assertEqual((self.root / 'index.db').read_bytes(), index)
        self.assertTrue(self.log(result, ident('e')))
        self.assertEqual(self.lines()[0]['items'], [high['id'], middle['id']])

    # When recall does not run

    def test_tc215_without_consent_the_key_a_threshold_a_long_prompt_or_an_index_nothing_is_sent(self):
        self.three()
        cases = []
        self.configure(consent=None, models={'dims': DIMS}, recall={'threshold': 0.4})
        cases.append((None, self.recall()))
        self.configure(models={'dims': DIMS})
        cases.append(('no-threshold', self.recall()))
        self.configure(models={'dims': DIMS}, recall={'threshold': 0.4})
        with mock.patch.dict(os.environ, {'CORTHEX_MEMORY_OPENAI_API_KEY': ''}):
            cases.append(('no-key', self.recall()))
        cases.append(('short', self.recall('  Hi you  ')))
        cases.append(('short', self.recall(unicodedata.normalize('NFD', 'C2 상태는?'))))
        cases.append(('command', self.recall('/memory status, please')))
        connection = sqlite3.connect(str(self.root / 'index.db'))
        try:
            connection.execute("DELETE FROM index_meta WHERE name = 'built'")
            connection.commit()
        finally:
            connection.close()
        cases.append(('no-index', self.recall()))
        (self.root / 'index.db').unlink()
        cases.append(('no-index', self.recall()))
        # With more than one missing, the first in stage 06's order names it: key, threshold, prompt, index.
        self.configure(models={'dims': DIMS})
        with mock.patch.dict(os.environ, {'CORTHEX_MEMORY_OPENAI_API_KEY': ''}):
            cases.append(('no-key', self.recall('Hi')))
        cases.append(('no-threshold', self.recall('Hi')))
        self.configure(models={'dims': DIMS}, recall={'threshold': 0.4})
        cases.append(('short', self.recall('Hi')))
        for number, (outcome, result) in enumerate(cases):
            with self.subTest(number=number, outcome=outcome):
                self.assertEqual(result, prompt_recall.Result(outcome))
        self.assertEqual(self.server.requests, [])
        self.assertEqual(self.usage(), [])
        # The line says why, with no item, score or candidate; without consent there is none.
        for _, result in cases:
            self.log(result, ident('e'))
        lines = self.lines()
        self.assertEqual([line['outcome'] for line in lines], [outcome for outcome, _ in cases if outcome])
        self.assertTrue(all(line['items'] == [] and 'candidates' not in line and 'scores' not in line
                            for line in lines))

    def test_an_index_that_another_connection_holds_past_the_deadline_makes_recall_late(self):
        self.three()
        writer = sqlite3.connect(str(self.root / 'index.db'), isolation_level=None)
        try:
            writer.execute('PRAGMA locking_mode = EXCLUSIVE')
            writer.execute('BEGIN EXCLUSIVE')
            writer.execute('COMMIT')
            started = clock.now()
            result = prompt_recall.recall(self.memory, 'sample', HOST, SESSION, QUESTION, started, started + 0.3,
                                          settings=self.settings(), zone=UTC)
            # Recall waits about as long as its deadline, not the sqlite3 module's five seconds. SQLite's sleeps run
            # long on a busy machine: macOS runners took 1.01 to 1.22 seconds here.
            self.assertLess(clock.now() - started, 3.0)
        finally:
            writer.close()
        self.assertEqual(result, prompt_recall.Result('late', error='deadline'))
        self.assertEqual(self.server.requests, [])
        # SQLite giving up on a lock once the deadline has passed is late too; before it, a failure.

        def locked(*arguments, **options):
            time.sleep(0.35)
            raise sqlite3.OperationalError('database is locked')
        started = clock.now()
        with mock.patch.object(recall.index_io, 'state', side_effect=locked):
            late = prompt_recall.recall(self.memory, 'sample', HOST, SESSION, QUESTION, started, started + 0.3,
                                        settings=self.settings(), zone=UTC)
            failed = self.recall()
        self.assertEqual(late, prompt_recall.Result('late', error='deadline'))
        self.assertEqual((failed.outcome, type(failed.error)), ('failed', sqlite3.OperationalError))
        self.assertEqual(self.server.requests, [])
        # Another SQLite error in the index's check, such as a disk's, is a failure also once the deadline has passed.

        def broken(*arguments, **options):
            time.sleep(0.35)
            raise sqlite3.OperationalError('disk I/O error')
        started = clock.now()
        with mock.patch.object(recall.index_io, 'state', side_effect=broken):
            broke = prompt_recall.recall(self.memory, 'sample', HOST, SESSION, QUESTION, started, started + 0.3,
                                         settings=self.settings(), zone=UTC)
        self.assertEqual((broke.outcome, type(broke.error), str(broke.error)),
                         ('failed', sqlite3.OperationalError, 'disk I/O error'))
        self.assertEqual(self.server.requests, [])

    def test_a_key_that_cannot_be_sent_is_missing(self):
        self.three()
        # A space, a line break and 8,193 characters: the key is set but no request could carry it.
        for number, key in enumerate(('memory-openai-key with-space', 'memory-openai-key\n', 'k' * 8193)):
            with self.subTest(number=number), mock.patch.dict(os.environ, {'CORTHEX_MEMORY_OPENAI_API_KEY': key}):
                self.assertEqual(self.recall(), prompt_recall.Result('no-key'))
        self.assertEqual((self.server.requests, self.usage()), ([], []))

    def test_an_index_lock_that_outlasts_the_embedding_s_time_is_late_before_anything_is_sent(self):
        self.three()
        writer = sqlite3.connect(str(self.root / 'index.db'), isolation_level=None)
        try:
            writer.execute('PRAGMA locking_mode = EXCLUSIVE')
            writer.execute('BEGIN EXCLUSIVE')
            writer.execute('COMMIT')
            started = clock.now()
            # The hook's deadline is far beyond the embedding's 800 ms: a look that waited for it would take 10 s.
            result = prompt_recall.recall(self.memory, 'sample', HOST, SESSION, QUESTION, started, started + 10.0,
                                          settings=self.settings(), zone=UTC)
            elapsed = clock.now() - started
        finally:
            writer.close()
        self.assertEqual(result, prompt_recall.Result('late', error='deadline'))
        self.assertLess(elapsed, 5.0)
        self.assertEqual((self.server.requests, self.usage()), ([], []))

    def test_a_look_at_the_index_that_ends_after_the_embedding_s_time_sends_nothing(self):
        self.three()
        ready = recall.ready

        def slow(*arguments, **options):
            # SQLite's wait for a lock can end later than asked on a busy machine, and find the index released then.
            found = ready(*arguments, **options)
            time.sleep(0.3)
            return found
        started = clock.now()
        with mock.patch.object(prompt_recall, 'EMBED_SECONDS', 0.2), \
                mock.patch.object(recall, 'ready', side_effect=slow):
            result = prompt_recall.recall(self.memory, 'sample', HOST, SESSION, QUESTION, started, started + 30,
                                          settings=self.settings(), zone=UTC)
        self.assertEqual(result, prompt_recall.Result('late', error='deadline'))
        self.assertEqual((self.server.requests, self.usage()), ([], []))

    # Failures

    def test_tc217_a_bad_vector_and_other_failures_inject_nothing_and_name_the_failure(self):
        self.three()
        before = self.raw_files()
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
                result = self.recall()
                self.assertEqual(result, prompt_recall.Result('failed', error=code))
                self.assertEqual(prompt_recall.output(result), b'')
                self.assertTrue(self.log(result, ident('e')))
        self.assertEqual(len(self.server.requests), len(cases))
        self.assertEqual([value['error'] for value in self.usage()], [code for code, _ in cases])
        self.assertEqual([line['outcome'] for line in self.lines()], ['failed'] * len(cases))
        self.assertEqual(self.raw_files(), before)

    def test_tc213_a_deadline_that_passes_while_ranking_or_an_error_injects_nothing(self):
        self.three()
        scores = recall._scores

        def slow(*arguments):
            time.sleep(1.0)
            return scores(*arguments)
        started = clock.now()
        with mock.patch.object(recall, '_scores', side_effect=slow):
            result = prompt_recall.recall(self.memory, 'sample', HOST, SESSION, QUESTION, started, started + 0.9,
                                          settings=self.settings(), zone=UTC)
        self.assertEqual(result, prompt_recall.Result('late', error='deadline'))
        self.assertLess(clock.now() - started, 1.5)
        # A damaged item file, and any other error, make recall fail with that error.
        middle = sorted((self.root / 'layer' / 'items').iterdir())[0]
        middle.write_bytes(b'{"id": "damaged"')
        result = self.recall()
        self.assertEqual((result.outcome, result.block), ('failed', ''))
        self.assertIsInstance(result.error, ValueError)
        with mock.patch.object(recall, 'rank', side_effect=RuntimeError('stand-in')):
            result = self.recall()
        self.assertEqual((result.outcome, type(result.error), str(result.error)), ('failed', RuntimeError, 'stand-in'))
        self.assertTrue(self.log(result, ident('e')))
        self.assertEqual(self.lines()[0]['outcome'], 'failed')

    # What is sent

    def test_tc220_the_request_holds_the_redacted_prompt_alone_cut_to_8192_bytes(self):
        dims = 512
        self.configure(recall={'threshold': 0.4})
        value = self.item('Wide')
        self.layer([value])
        self.index(dims=dims)
        self.vectors([(value, [1.0] + [0.0] * (dims - 1))])
        self.answer = [1.0] + [0.0] * (dims - 1)
        key = self.keys['CORTHEX_MEMORY_OPENAI_API_KEY']
        hidden = 'kept-private-' + secrets.token_hex(8)
        text = ('Which hooks does memory keep? key %s <private>%s</private> ' % (key, hidden) +
                '한글 문장이 이어집니다. ' * 1200)
        self.assertGreater(len(text.encode('utf-8')), 20000)
        prepared = raw_log.prepare(text)
        result = self.recall(prepared.text)
        self.assertEqual(result.outcome, 'injected')
        (headers, body), = self.server.requests
        self.assertEqual(set(body), {'model', 'input', 'dimensions', 'encoding_format'})
        self.assertEqual(body['dimensions'], dims)
        sent, = body['input']
        data = sent.encode('utf-8')
        self.assertLessEqual(len(data), 8192)
        self.assertGreater(len(data), 8192 - 4)
        self.assertTrue(prepared.text.startswith(sent))
        encoded = json.dumps(body, ensure_ascii=False)
        # No key, private span, folder, project name, other turn or item goes with it.
        for secret in (key, hidden, self.keys['OPENAI_API_KEY'], self.keys['CORTHEX_MEMORY_ANTHROPIC_API_KEY'],
                       str(self.folder), 'sample', worker_fixture.HOOKS, 'One script now serves the hooks.',
                       value['text']):
            self.assertNotIn(secret, encoded)
        self.assertNotIn('user', body)


if __name__ == '__main__':
    unittest.main()
