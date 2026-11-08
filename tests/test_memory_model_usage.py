"""TASK-078 isolated credentials/errors/accounting; no HTTP or real conversations."""
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT/'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import base, clock, configuration, enablement, files, format2, locks, model_access, model_usage, redaction
from memory_lib.c2_store import C2Store

AT = '2026-10-25T09:12:03.004Z'
DEVICE = 'd_0123456789ab'
WHEN = datetime(2026, 11, 30, 23, 59, 59, 999000, tzinfo=timezone.utc)
PRICES = {'taken': '2026-10-25', 'from': ['https://example.invalid/prices'],
          'models': {'fixture-model': {'input': 1, 'output': 2, 'cache_write': 3, 'cache_read': .5,
                    'above': {'tokens': 100, 'input': 7, 'output': 9}}}}
SECRET = 'fixture-memory-credential-628f'


class ModelAccessTest(unittest.TestCase):
    def test_authentication_reads_only_the_two_dedicated_variables(self):
        class Environment:
            reads = []
            def get(self, name):
                self.reads.append(name)
                return None
            def __iter__(self):
                raise AssertionError('Authentication may not enumerate host credentials')
        env = Environment()
        credential = model_access.Credentials.read(env)
        self.assertEqual(env.reads, ['CORTHEX_MEMORY_ANTHROPIC_API_KEY', 'CORTHEX_MEMORY_OPENAI_API_KEY'])
        self.assertEqual(credential.presence(), {'anthropic': 'missing', 'openai': 'missing'})
        self.assertIsNone(credential.headers('anthropic'))

    def test_general_keys_never_substitute_and_presence_uses_the_same_boundary(self):
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': SECRET, 'OPENAI_API_KEY': SECRET}, clear=True):
            self.assertEqual(enablement._keys(), {'anthropic': 'missing', 'openai': 'missing'})

    def test_credentials_have_safe_representation_and_provider_specific_headers(self):
        c = model_access.Credentials.read({'CORTHEX_MEMORY_ANTHROPIC_API_KEY': SECRET,
                                           'CORTHEX_MEMORY_OPENAI_API_KEY': 'other-fixture-key'})
        self.assertNotIn(SECRET, repr(c))
        self.assertNotIn('other-fixture-key', str(c))
        self.assertEqual(c.headers('anthropic'), {'x-api-key': SECRET})
        self.assertEqual(c.headers('openai'), {'Authorization': 'Bearer other-fixture-key'})
        self.assertEqual(c.presence(), {'anthropic': 'present', 'openai': 'present'})

    def test_invalid_header_values_never_escape_in_the_error(self):
        for key in (SECRET+'\r\ntext', SECRET+'\x00', SECRET+' secret', SECRET+'한글', 'x'*8193):
            c = model_access.Credentials.read({'CORTHEX_MEMORY_ANTHROPIC_API_KEY': key})
            with self.assertRaises(ValueError) as caught:
                c.headers('anthropic')
            self.assertEqual(str(caught.exception), 'invalid memory credential header')
            self.assertNotIn(SECRET, repr(caught.exception))

    def test_auth_snapshot_survives_environment_changes_and_redaction_stays_broad(self):
        env = {'CORTHEX_MEMORY_ANTHROPIC_API_KEY': SECRET}
        c = model_access.Credentials.read(env)
        env['CORTHEX_MEMORY_ANTHROPIC_API_KEY'] = 'replacement'
        self.assertFalse(c.safe('req_'+SECRET))
        marker = 'fixture-general-token-3998'
        self.assertNotIn(marker, redaction.redact(marker, environment={'OPENAI_API_KEY': marker}).text)

    def test_known_http_contract_has_fixed_kinds_and_lifetimes(self):
        expected = [(400, 'invalid_request_error', True), (401, 'authentication_error', True),
                    (402, 'billing_error', True), (403, 'permission_error', True), (404, 'not_found_error', True),
                    (409, 'conflict_error', False), (413, 'request_too_large', True),
                    (429, 'rate_limit_error', False), (500, 'api_error', False),
                    (504, 'timeout_error', False), (529, 'overloaded_error', False)]
        for status, code, lasting in expected:
            with self.subTest(status=status):
                f = model_access.classify('anthropic', status=status, error_type=SECRET, error_code=SECRET)
                self.assertEqual((f.code, f.lasting, f.status, f.result), (code, lasting, status, 'failed'))
                self.assertNotIn(SECRET, repr(f))
        self.assertEqual(model_access.classify('anthropic', status=500, error_type='timeout_error'),
                         model_access.Failure('timeout_error', False, 500))

    def test_openai_quota_is_lasting_only_for_the_documented_selectors(self):
        for code in ('credit_balance_exhausted', 'organization_spend_limit_exceeded',
                     'project_spend_limit_exceeded', 'organization_usage_limit_exceeded'):
            self.assertEqual(model_access.classify('openai', status=429, error_code=code),
                             model_access.Failure('insufficient_quota', True, 429))
        self.assertTrue(model_access.classify('openai', status=429, error_type='insufficient_quota').lasting)
        self.assertFalse(model_access.classify('openai', status=429, error_code=SECRET).lasting)
        self.assertFalse(model_access.classify('anthropic', status=429, error_code='credit_balance_exhausted').lasting)
        self.assertEqual(model_access.classify('openai', status=503).code, 'overloaded_error')

    def test_unknown_types_are_discarded_and_stream_and_answer_kinds_stay_closed(self):
        for status, code, lasting in ((418, 'invalid_request_error', True), (599, 'api_error', False),
                                      (None, 'api_error', False)):
            self.assertEqual(model_access.classify('anthropic', status=status, error_type=SECRET),
                             model_access.Failure(code, lasting, status))
        for code, lasting, result in (('network', False, 'failed'), ('timeout', False, 'failed'),
                                     ('empty-answer', False, 'failed'), ('bad-answer', False, 'failed'),
                                     ('bad-vector', False, 'failed'), ('refusal', True, 'refused'),
                                     ('max-tokens', True, 'limit')):
            f = model_access.classify('anthropic', reason=code)
            self.assertEqual((f.code, f.lasting, f.result), (code, lasting, result))
        self.assertTrue(model_access.classify('anthropic', error_type='authentication_error').lasting)
        self.assertEqual(model_access.classify('anthropic', error_type='refusal').code, 'api_error')

    def test_invalid_classifier_inputs_use_fixed_errors(self):
        for status in (True, 399, 600, 429.0, '429'):
            with self.assertRaisesRegex(ValueError, '^invalid memory HTTP status$'):
                model_access.classify('openai', status=status)
        with self.assertRaisesRegex(ValueError, '^invalid memory failure reason$'):
            model_access.classify('anthropic', reason=SECRET)


class ModelUsageTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name).resolve()/'memory'
        (self.folder/'logs').mkdir(parents=True)
        (self.folder/'store.json').write_bytes(format2.store_bytes(
            {'format': 2, 'device': DEVICE, 'made': AT, 'release': '0.2.1'}))
        self.memory = C2Store(self.folder, expected_device=DEVICE)
        self.deadline = clock.now()+60
        self.credential = model_access.Credentials.read({'CORTHEX_MEMORY_ANTHROPIC_API_KEY': SECRET})
        self.path = self.folder/'logs/usage-2026-11.jsonl'

    def attempt(self, **changes):
        values = dict(project='sample', call='curate', model='fixture-model', prices=copy.deepcopy(PRICES),
                      credentials=self.credential, instructions='curate-2', when=WHEN)
        values.update(changes)
        return model_usage.Attempt.start(**values)

    def test_configured_example_cost_is_point0055_without_real_provider_prices(self):
        prices = configuration.prepare({}, temporary=False).values['prices']
        a = self.attempt(model='claude-haiku-5-5', prices=prices)
        row = a.line(usage={'input_tokens': 40000, 'output_tokens': 3000})
        self.assertEqual(row['cost'], .0055)
        self.assertEqual(row['prices'], '2026-10-25')

    def test_cache_tokens_choose_strict_above_threshold_without_double_counting(self):
        a = self.attempt()
        counts = {'input_tokens': 80, 'output_tokens': 10, 'cache_creation_input_tokens': 10,
                  'cache_read_input_tokens': 10, 'thinking': SECRET, 'reasoning_tokens': 900}
        row = a.line(usage=counts)
        self.assertAlmostEqual(row['cost'], .000135)
        self.assertEqual((row['input'], row['output'], row['cache_write'], row['cache_read']), (80, 10, 10, 10))
        self.assertAlmostEqual(a.line(usage=dict(counts, cache_creation_input_tokens=11))['cost'], .000688)
        self.assertNotIn('reasoning_tokens', row)
        self.assertNotIn(SECRET, json.dumps(row))

    def test_attempt_freezes_prices_date_and_send_month(self):
        prices = copy.deepcopy(PRICES)
        a = self.attempt(prices=prices)
        prices['taken'] = '2026-12-01'; prices['models']['fixture-model']['input'] = 900
        self.assertTrue(a.record(self.memory, self.deadline, usage={'input_tokens': 10}))
        row = json.loads(self.path.read_bytes())
        self.assertEqual(row['at'], '2026-11-30T23:59:59.999Z')
        self.assertEqual(row['prices'], '2026-10-25')
        self.assertEqual(row['cost'], .00001)
        self.assertFalse((self.folder/'logs/usage-2026-12.jsonl').exists())

    def test_count_tokens_is_free_and_embeddings_use_prompt_tokens_only(self):
        row = self.attempt(call='count-tokens').line(usage={'input_tokens': 200000, 'output_tokens': 500})
        self.assertEqual(row['cost'], 0)
        self.assertEqual(row['input'], 200000)
        self.assertNotIn('output', row)
        for call in ('embed-prompt', 'embed-items', 'embed-search'):
            row = self.attempt(call=call, instructions=None).line(usage={'prompt_tokens': 10, 'total_tokens': 20,
                                                                         'output_tokens_details': {'reasoning_tokens': SECRET}})
            self.assertEqual((row['input'], row['cost']), (10, .00001))
            self.assertNotIn('output', row)

    def test_unknown_model_zero_cost_and_unavailable_usage_are_not_invented(self):
        row = self.attempt(model='unpriced-fixture').line(usage={'input_tokens': 20})
        self.assertEqual(row['cost'], 0)
        self.assertEqual(row['model'], 'unpriced-fixture')
        row = self.attempt().line(failure=model_access.classify('anthropic', reason='network'))
        self.assertNotIn('input', row)
        self.assertNotIn('output', row)
        self.assertEqual((row['result'], row['error'], row['cost']), ('failed', 'network', 0))

    def test_stream_failure_keeps_reported_usage_and_only_safe_failure_kind(self):
        f = model_access.classify('anthropic', status=529, error_type=SECRET)
        row = self.attempt().line(usage={'input_tokens': 5, 'output_tokens': 2}, failure=f, request_id='req_fixture')
        self.assertEqual((row['input'], row['output'], row['error'], row['request']), (5, 2, 'overloaded_error', 'req_fixture'))
        self.assertAlmostEqual(row['cost'], .000009)
        for reason, result in (('refusal', 'refused'), ('max-tokens', 'limit')):
            self.assertEqual(self.attempt().line(failure=model_access.classify('anthropic', reason=reason))['result'], result)

    def test_invalid_and_secret_request_ids_are_omitted_using_original_credentials(self):
        a = self.attempt()
        for request in (SECRET, 'req_'+SECRET, 'body\n'+SECRET, {'text': SECRET}, 'x'*201):
            self.assertNotIn('request', a.line(request_id=request))
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertNotIn('request', a.line(request_id='req_'+SECRET))

    def test_timing_and_counter_types_are_strict(self):
        a = self.attempt()
        with mock.patch.object(clock, 'now', return_value=a._started+.25):
            row = a.line(first_ms=100)
            self.assertEqual(row['total_ms'], 250)
        for n in (True, -1, 1.5, float('nan'), SECRET):
            with self.assertRaises(ValueError):
                a.line(usage={'input_tokens': n})
        with self.assertRaises(ValueError):
            a.line(first_ms=999999)

    def test_record_once_retry_has_its_own_line_and_table_field_order(self):
        a = self.attempt()
        failure = model_access.classify('anthropic', reason='timeout')
        self.assertTrue(a.record(self.memory, self.deadline, failure=failure))
        self.assertFalse(a.record(self.memory, self.deadline))
        b = self.attempt()
        self.assertTrue(b.record(self.memory, self.deadline, usage={'input_tokens': 3, 'output_tokens': 2}, request_id='req_fixture'))
        rows = [json.loads(s) for s in self.path.read_bytes().splitlines()]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['error'], 'timeout')
        self.assertEqual(rows[1]['result'], 'ok')
        expected = 'at project call model instructions input output total_ms result request cost prices'.split()
        self.assertEqual(list(rows[1]), expected)
        for p in self.folder.rglob('*'):
            if p.is_file():self.assertNotIn(SECRET.encode(), p.read_bytes())

    def test_short_append_restores_exact_size_without_fsync(self):
        self.path.write_bytes(b'{"old":true}\n')
        before = self.path.read_bytes(); write = os.write
        def short(fd, data):
            if b'"call":"curate"' in data:
                write(fd, data[:8]); return 8
            return write(fd, data)
        with mock.patch.object(os, 'write', side_effect=short), mock.patch.object(files, '_sync') as sync:
            self.assertFalse(self.attempt().record(self.memory, self.deadline))
        self.assertEqual(self.path.read_bytes(), before)
        sync.assert_not_called()

    def test_cut_tail_gets_lf_and_known_backup_alias_is_allowed(self):
        self.path.write_bytes(b'cut')
        backup = self.path.with_name(self.path.name+'.bak')
        os.link(str(self.path), str(backup))
        self.assertTrue(self.attempt().record(self.memory, self.deadline))
        self.assertTrue(self.path.read_bytes().startswith(b'cut\n{"at":'))
        self.assertEqual(self.path.read_bytes(), backup.read_bytes())

    def test_valid_missing_primary_backup_restores_under_usage_lease(self):
        row = self.attempt().line(usage={'input_tokens': 2})
        backup = self.path.with_name(self.path.name+'.bak')
        backup.write_bytes(base.json_bytes(row, 'TBL-003', compact=True))
        self.assertTrue(self.attempt().record(self.memory, self.deadline))
        self.assertFalse(backup.exists())
        self.assertEqual(len(self.path.read_bytes().splitlines()), 2)

    def test_invalid_backup_is_preserved_without_creating_a_primary(self):
        backup = self.path.with_name(self.path.name+'.bak'); backup.write_bytes(b'{"body":"private"}\n')
        self.assertFalse(self.attempt().record(self.memory, self.deadline))
        self.assertFalse(self.path.exists())
        self.assertEqual(backup.read_bytes(), b'{"body":"private"}\n')

    def test_backup_extra_alias_is_refused_before_restoration(self):
        backup = self.path.with_name(self.path.name+'.bak')
        backup.write_bytes(base.json_bytes(self.attempt().line(), 'TBL-003', compact=True))
        os.link(str(backup), str(self.folder/'unknown-backup-alias'))
        self.assertFalse(self.attempt().record(self.memory, self.deadline))
        self.assertFalse(self.path.exists())
        self.assertTrue(backup.exists())

    def test_usage_parser_rejects_unknown_fields_and_invalid_table_values(self):
        row = self.attempt().line()
        for edits in ({'message': SECRET}, {'reasoning': SECRET}, {'input': True}, {'cost': float('nan')},
                      {'cost': -1}, {'total_ms': -1}, {'prices': '2026-02-30'}, {'call': 'unknown'},
                      {'result': 'stale'}, {'error': SECRET}, {'request': 'req\n'+SECRET}, {'model': 'X invalid'}):
            with self.subTest(fields=list(edits)), self.assertRaises((ValueError, UnicodeError)):
                model_usage.parse(json.dumps(dict(row, **edits)).encode())

    # TASK-116: a curate request's size, and the distribution from the usage logs alone (TC-421)

    def test_tc421_a_curate_line_holds_its_size_after_prices_and_earlier_lines_still_read(self):
        whole = self.attempt(size={'estimate': 81234, 'list': 'short', 'turns': 3})
        part = self.attempt(size={'turns': 1, 'parts': 4, 'list': 'full', 'estimate': 90000})
        earlier = self.attempt()
        for attempt in (whole, part, earlier):
            self.assertTrue(attempt.record(self.memory, self.deadline, usage={'input_tokens': 70000}))
        rows = [model_usage.parse(line) for line in self.path.read_bytes().splitlines()]
        known = 'at project call model instructions input total_ms result cost prices'.split()
        self.assertEqual([list(row) for row in rows],
                         [known + ['estimate', 'list', 'turns'], known + ['estimate', 'list', 'parts', 'turns'], known])
        self.assertEqual([{key: row[key] for key in model_usage.SIZE if key in row} for row in rows],
                         [{'turns': 3, 'list': 'short', 'estimate': 81234},
                          {'turns': 1, 'parts': 4, 'list': 'full', 'estimate': 90000}, {}])

    def test_tc421_a_size_is_whole_valid_and_only_on_a_curate_line(self):
        size = {'turns': 2, 'list': 'full', 'estimate': 5000}
        for changes in ({'call': 'consolidate', 'instructions': 'merge-2'}, {'size': dict(size, list='whole')},
                        {'size': dict(size, list=['full'])}, {'size': dict(size, turns=0)},
                        {'size': dict(size, turns=True)}, {'size': dict(size, estimate=-1)},
                        {'size': dict(size, estimate=1.5)}, {'size': dict(size, parts=4)},
                        {'size': dict(size, turns=1, parts=1)}, {'size': dict(size, text=SECRET)},
                        {'size': {'turns': 2, 'list': 'full'}}, {'size': {'parts': 2}}, {'size': [('turns', 2)]}):
            values = dict({'size': size}, **changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.attempt(**values)
        row = self.attempt(size=size).line()
        for edits in ({'call': 'consolidate'}, {'turns': None}, {'list': 'whole'}, {'parts': 2}):
            line = {key: value for key, value in dict(row, **edits).items() if value is not None}
            with self.subTest(edits=edits), self.assertRaises(ValueError):
                model_usage.parse(json.dumps(line).encode())
        line = {key: value for key, value in row.items() if key not in model_usage.SIZE}
        self.assertEqual(model_usage.parse(json.dumps(line).encode()), line)

    def test_tc421_sizes_give_the_median_p95_shares_and_causes_from_the_logs_alone(self):
        def line(tokens=None, size=None, project='sample', cache=0, **changes):
            values = dict(changes)
            if size is not None:
                values['size'] = size
            attempt = self.attempt(project=project, **values)
            usage = None if tokens is None else {'input_tokens': tokens - cache, 'cache_read_input_tokens': cache}
            return base.json_bytes(attempt.line(usage=usage), 'TBL-003', compact=True)
        whole = {'turns': 4, 'list': 'full', 'estimate': 62000}
        lines = [line(30000, whole), line(61000, dict(whole, estimate=64000)), line(64000, whole, cache=20000),
                 line(98000, {'turns': 1, 'parts': 3, 'list': 'full', 'estimate': 96000}),
                 line(99000, {'turns': 1, 'list': 'short', 'estimate': 99500}),
                 line(100000, {'turns': 2, 'list': 'part', 'estimate': 97000}),
                 line(101000, {'turns': 1, 'parts': 2, 'list': 'part', 'estimate': 96500}),
                 line(130000), line(5000), line(None, whole),
                 line(500000, whole, project='other'), line(400000, call='consolidate', instructions='merge-2'),
                 line(300000, call='embed-items', instructions=None)]
        logs = [b''.join(lines[:5]) + b'\n', b'{"at": damaged\n' + b''.join(lines[5:])]
        found = model_usage.sizes(logs, project='sample')
        tokens = [5000, 30000, 61000, 64000, 98000, 99000, 100000, 101000, 130000]
        self.assertEqual((found['requests'], found['unreadable'], found['unrecorded']), (9, 1, 2))
        self.assertEqual((found['median'], found['p95']), (98000, 130000))
        self.assertEqual(found['over'][60000], {
            'requests': 7, 'share': 7 / 9, 'turns': {'parts': 2, 'one': 1, 'several': 3},
            'list': {'full': 3, 'short': 1, 'part': 2}, 'above_estimate': 4, 'unrecorded': 1})
        self.assertEqual(found['over'][100000], {
            'requests': 2, 'share': 2 / 9, 'turns': {'parts': 1, 'one': 0, 'several': 0},
            'list': {'full': 0, 'short': 0, 'part': 1}, 'above_estimate': 1, 'unrecorded': 1})
        self.assertEqual(sorted(tokens)[8], found['p95'])
        everyone = model_usage.sizes(logs)
        self.assertEqual((everyone['requests'], everyone['median'], everyone['over'][100000]['requests']),
                         (10, 98500, 3))
        self.assertEqual(model_usage.sizes([b'', b'\n'])['median'], None)
        even = model_usage.sizes([line(10) + line(20)])
        self.assertEqual((even['median'], even['p95'], even['over'][60000]['share']), (15, 20, 0))

    def test_concurrent_completion_emits_exactly_one_line(self):
        a = self.attempt(); barrier = threading.Barrier(6); results = []
        def complete():
            barrier.wait(timeout=5)
            results.append(a.record(self.memory, self.deadline))
        children = [threading.Thread(target=complete) for _ in range(6)]
        for child in children:child.start()
        for child in children:child.join(timeout=5)
        self.assertFalse(any(child.is_alive() for child in children))
        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count(False), 5)
        self.assertEqual(len(self.path.read_bytes().splitlines()), 1)

    def test_short_write_lost_lease_preserves_unknown_prefix_without_rollback(self):
        self.path.write_bytes(b'old\n'); write = os.write
        foreign = 'e'*32
        def short(fd, data):
            if b'"call":"curate"' in data:
                write(fd, data[:8])
                lease = self.folder/'logs/usage.lock'; value = json.loads(lease.read_bytes())
                value['token'] = foreign; lease.write_text(json.dumps(value), encoding='utf-8')
                return 8
            return write(fd, data)
        with mock.patch.object(os, 'write', side_effect=short), mock.patch.object(os, 'ftruncate') as rollback:
            self.assertFalse(self.attempt().record(self.memory, self.deadline))
        rollback.assert_not_called()
        self.assertEqual(self.path.read_bytes(), b'old\n{"at":"2')
        self.assertEqual(json.loads((self.folder/'logs/usage.lock').read_bytes())['token'], foreign)

    def test_busy_usage_lease_is_best_effort_and_never_forced(self):
        lock = locks.Lock(self.folder/'logs/usage.lock', 'log', DEVICE).acquire(self.deadline, wait=False)
        try:
            self.assertFalse(self.attempt().record(self.memory, self.deadline))
            lock.check(); self.assertFalse(self.path.exists())
        finally:
            lock.release()

    def test_missing_log_directory_and_expired_deadline_never_provision(self):
        (self.folder/'logs').rmdir()
        self.assertFalse(self.attempt().record(self.memory, self.deadline))
        self.assertFalse((self.folder/'logs').exists())
        self.assertFalse(self.attempt().record(self.memory, clock.now()-1))

    def test_changed_header_and_extra_hardlink_refuse_usage_writes(self):
        self.path.write_bytes(b'')
        alias = self.folder/'unknown'; os.link(str(self.path), str(alias))
        self.assertFalse(self.attempt().record(self.memory, self.deadline))
        self.assertEqual(alias.read_bytes(), b'')
        alias.unlink()
        header = self.folder/'store.json'; original = header.read_bytes()
        header.write_bytes(original.replace(b'0.2.1', b'0.2.2'))
        self.assertFalse(self.attempt().record(self.memory, self.deadline))
        self.assertEqual(self.path.read_bytes(), b'')

    def test_failed_diagnostics_never_change_the_call_result(self):
        a = self.attempt()
        with mock.patch.object(self.memory, 'check', side_effect=PermissionError(SECRET)), \
                mock.patch.object(self.memory, 'note', side_effect=RuntimeError(SECRET)):
            self.assertFalse(a.record(self.memory, self.deadline))
        self.assertFalse(self.path.exists())

    def test_one_shot_attempt_cannot_be_emitted_by_another_pid(self):
        a = self.attempt()
        with mock.patch.object(os, 'getpid', return_value=os.getpid()+1):
            self.assertFalse(a.record(self.memory, self.deadline))
        self.assertTrue(a.record(self.memory, self.deadline))

    def test_literal_credential_in_other_metadata_refuses_the_line(self):
        key = model_access.Credentials.read({'CORTHEX_MEMORY_ANTHROPIC_API_KEY': 'fixture-model'})
        with self.assertRaisesRegex(ValueError, '^unsafe memory usage metadata$'):
            self.attempt(credentials=key)

    def test_windows_retry_rechecks_original_token_before_a_second_open(self):
        opened = base.private_open; calls = []; foreign = 'f'*32
        def denied(path, flags):
            if path == self.path:
                calls.append(path)
                lease = self.folder/'logs/usage.lock'; value = json.loads(lease.read_bytes())
                value['token'] = foreign; lease.write_text(json.dumps(value), encoding='utf-8')
                raise PermissionError('fixture sharing failure')
            return opened(path, flags)
        with mock.patch.object(base, 'private_open', side_effect=denied), \
                mock.patch.object(files, '_WINDOWS', True), mock.patch.object(files.time, 'sleep'):
            self.assertFalse(self.attempt().record(self.memory, self.deadline))
        self.assertEqual(len(calls), 1)
        self.assertFalse(self.path.exists())
        lease = self.folder/'logs/usage.lock'
        self.assertEqual(json.loads(lease.read_bytes())['token'], foreign)

    @unittest.skipIf(os.name == 'nt', 'Windows refuses replacement of this live CRT descriptor')
    def test_live_fd_replacement_is_detected_before_the_append(self):
        opened = base.private_open
        def replace(path, flags):
            fd = opened(path, flags)
            if path == self.path:
                other = path.with_name('replacement'); other.write_bytes(b'preserve\n')
                os.replace(str(other), str(path))
            return fd
        with mock.patch.object(base, 'private_open', side_effect=replace):
            self.assertFalse(self.attempt().record(self.memory, self.deadline))
        self.assertEqual(self.path.read_bytes(), b'preserve\n')
