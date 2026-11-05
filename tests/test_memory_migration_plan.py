"""TASK-074 pure proposal evidence; no operational quiescence or migration."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

from _common import ROOT

sys.path.insert(0, str(ROOT/'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import base, curation, format2, migration_plan, store

AT = '2026-11-05T00:00:00.000Z'
LATER = '2026-11-05T01:00:00.000Z'
HEADER = dict(format=1, device='d_0123456789ab', made=AT, release='0.2.1')
PROGRESS = dict(logs={'codex-0123456789abcdef': 4}, applies=3,
    recent=[dict(at=AT, kind='curate', result='failed', error='network')],
    consolidation=dict(failures=1, last=AT, due=LATER),
    failures=dict(count=1, log='codex-0123456789abcdef', turn=2),
    stopped=dict(at=AT, by='curate', errors=['network']), rebuilt=AT)


def data(value):
    return json.dumps(value, ensure_ascii=False).encode('utf-8')


def plan(headers=None, **options):
    return migration_plan.header_fence({'store.json': data(HEADER)} if headers is None else headers,
        release=options.get('release', '0.3.0'), when=options.get('when', LATER))


class MigrationPlanTest(unittest.TestCase):
    def test_tc390_backup_is_fenced_before_primary_and_both_keep_identity(self):
        proposal = plan()
        self.assertEqual(tuple(n for n, _ in proposal.publications), ('store.json.bak', 'store.json'))
        self.assertEqual(proposal.publications[0][1], proposal.publications[1][1])
        value = format2.parse_store(proposal.publications[0][1], allow_migrating=True)
        self.assertEqual((value['device'], value['made']), (HEADER['device'], HEADER['made']))
        self.assertEqual(value['migrating'], dict(to=2, **{'from': 1}, started=LATER))
        self.assertEqual(value['release'], '0.3.0')

    def test_tc390_original_bytes_and_hashes_remain_exact(self):
        original = b'  '+data(HEADER)+b'\r\n'
        proposal = plan({'store.json': original})
        self.assertEqual(proposal.originals, (('store.json', original),))
        self.assertEqual(proposal.original_sha256, (('store.json', hashlib.sha256(original).hexdigest()),))

    def test_tc390_input_mutation_cannot_change_a_prepared_proposal(self):
        raw = bytearray(data(HEADER)); inputs = {'store.json': raw}
        proposal = plan(inputs); expected = copy.deepcopy(proposal)
        raw[:] = b'{}'; inputs.clear()
        self.assertEqual(proposal, expected)

    def test_tc390_catalog_permutation_is_deterministic(self):
        headers = {'store.json': data(HEADER), 'store.json.bak': data(HEADER),
                   'store.json.abc123_4.tmp': data(HEADER)}
        self.assertEqual(plan(headers), plan(dict(reversed(list(headers.items())))))

    def test_tc390_named_backup_can_supply_an_absent_primary(self):
        proposal = plan({'store.json.bak': data(HEADER)})
        self.assertEqual(proposal.original_sha256[0][0], 'store.json.bak')
        self.assertEqual(len(proposal.publications), 2)

    def test_tc390_temps_alone_never_supply_a_store_identity(self):
        for headers in ({}, {'store.json.abc123_4.tmp': data(HEADER)}):
            with self.subTest(headers=headers), self.assertRaises(ValueError):
                plan(headers)

    def test_tc390_recognized_temps_are_bound_for_preservation_not_promoted(self):
        headers = {'store.json': data(HEADER), 'store.json.abc123_4.tmp': data(HEADER),
                   'store.json.bak.1234_ab0.tmp': data(HEADER)}
        proposal = plan(headers)
        self.assertEqual(set(proposal.preserve_temps), set(headers)-{'store.json'})
        self.assertEqual(set(dict(proposal.originals)), set(headers))

    def test_tc390_unknown_or_escaping_artifact_names_are_refused(self):
        for name in ('../store.json.bak', 'store.json.tmp', 'store.json.abcdefghi.tmp',
                     'store.json.ABC123_4.tmp', 'store.json.bak.old', 1):
            headers = {'store.json': data(HEADER), name: data(HEADER)}
            with self.subTest(name=name), self.assertRaises(ValueError):
                plan(headers)

    def test_tc390_a_valid_backup_never_hides_damage_in_an_observed_header(self):
        for name in ('store.json', 'store.json.abc123_4.tmp'):
            headers = {'store.json.bak': data(HEADER), name: b'{damaged'}
            with self.subTest(name=name), self.assertRaises(ValueError):
                plan(headers)

    def test_tc390_json_duplicates_unknown_fields_and_opaque_versions_are_refused(self):
        malformed = [b'{"format":1,"format":1}', data(dict(HEADER, unknown=True)),
                     data(dict(HEADER, format=True)), data(dict(HEADER, format=3)),
                     data(dict(HEADER, format=2)), data([HEADER]), data(dict(HEADER, release=''))]
        for raw in malformed:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                plan({'store.json': raw})

    def test_tc390_every_header_must_have_the_same_device_and_creation_time(self):
        for change in (dict(device='d_123456789abc'), dict(made=LATER)):
            with self.subTest(change=change), self.assertRaises(ValueError):
                plan({'store.json': data(HEADER), 'store.json.bak': data(dict(HEADER, **change))})

    def test_tc390_resume_keeps_the_existing_marker_instead_of_using_new_time(self):
        first = plan(); fenced = dict(first.publications)['store.json.bak']
        resumed = plan({'store.json': data(HEADER), 'store.json.bak': fenced}, when='2026-11-06T00:00:00.000Z')
        self.assertEqual(resumed.publications, first.publications)

    def test_tc390_resuming_two_already_fenced_headers_is_idempotent(self):
        first = plan()
        self.assertEqual(plan(dict(first.publications)).publications, first.publications)

    def test_tc390_temporary_header_cannot_establish_a_resume_context(self):
        fenced = dict(plan().publications)['store.json']
        with self.assertRaises(ValueError):
            plan({'store.json': data(HEADER), 'store.json.abc123_4.tmp': fenced})

    def test_tc390_observed_temporary_context_must_match_named_fences(self):
        fenced = dict(plan().publications)['store.json']
        other = format2.parse_store(fenced, allow_migrating=True)
        other['migrating']['started'] = AT
        with self.assertRaises(ValueError):
            plan({'store.json': fenced, 'store.json.abc123_4.tmp': data(other)})

    def test_tc390_conflicting_resume_contexts_cannot_be_combined(self):
        first = dict(plan().publications)['store.json']
        altered = format2.parse_store(first, allow_migrating=True)
        for change in (dict(started=AT), dict(to=3)):
            bad = copy.deepcopy(altered); bad['migrating'].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                plan({'store.json': first, 'store.json.bak': data(bad)})
        with self.assertRaises(ValueError):
            plan({'store.json': first}, release='different-release')

    def test_tc390_completed_format2_store_is_not_a_fresh_c1_migration(self):
        value = format2.parse_store(dict(plan().publications)['store.json'], allow_migrating=True)
        value.pop('migrating')
        with self.assertRaises(ValueError):
            plan({'store.json': data(value)})

    def test_tc390_invalid_creation_and_start_dates_are_refused_before_publication(self):
        with self.assertRaises(ValueError):
            plan({'store.json': data(dict(HEADER, made='2026-02-30T00:00:00.000Z'))})
        with self.assertRaises(ValueError):
            plan(when='2026-02-30T00:00:00.000Z')

    def test_tc390_old_client_refuses_after_fence_even_if_primary_is_lost(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); memory = store.MemoryStore(root)
            (root/'store.json').write_bytes(data(HEADER))
            (root/'store.json.bak').write_bytes(data(HEADER))
            proposal = plan({'store.json': data(HEADER), 'store.json.bak': data(HEADER)})
            # Old writers must already be quiescent: the first fence alone is
            # deliberately not called safe to write C2 data.
            name, raw = proposal.publications[0]; (root/name).write_bytes(raw)
            self.assertEqual(memory.record(deadline=time.monotonic()+2)['format'], 1)
            name, raw = proposal.publications[1]; (root/name).write_bytes(raw)
            for condition in ('healthy', 'missing', 'damaged'):
                if condition == 'missing':(root/'store.json').unlink()
                if condition == 'damaged':(root/'store.json').write_bytes(b'{damaged')
                before = {p.name:p.read_bytes() for p in root.iterdir()}
                with self.subTest(condition=condition), self.assertRaises(store.StoreUnavailable) as caught:
                    memory.record(deadline=time.monotonic()+2)
                self.assertEqual(caught.exception.code, 'store-newer')
                self.assertEqual({p.name:p.read_bytes() for p in root.iterdir()}, before)

    def test_tc390_primary_only_fencing_counterexample_reopens_old_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); memory = store.MemoryStore(root)
            (root/'store.json.bak').write_bytes(data(HEADER))
            (root/'store.json').write_bytes(b'{damaged')
            self.assertEqual(memory.record(deadline=time.monotonic()+2)['format'], 1)
            self.assertEqual(store._record((root/'store.json').read_bytes()), HEADER)

    def test_tc116_upgrade_preserves_every_c1_progress_field_without_old_identity_proof(self):
        raw = data(PROGRESS); upgraded = format2.parse_curation(migration_plan.progress(raw))
        fence = upgraded.pop('fence')
        self.assertEqual(upgraded, PROGRESS)
        self.assertEqual(curation.parse(raw), PROGRESS)
        self.assertEqual(fence['generation'], 0); self.assertEqual(fence['revisions'], {})
        self.assertRegex(fence['epoch'], r'^[0-9a-f]{32}$')

    def test_tc116_absence_proposes_fresh_empty_control_not_historical_zero_revisions(self):
        first = format2.parse_curation(migration_plan.progress(None))
        second = format2.parse_curation(migration_plan.progress(None))
        self.assertEqual(first['logs'], {}); self.assertEqual(first['applies'], 0)
        self.assertNotEqual(first['fence']['epoch'], second['fence']['epoch'])
        self.assertEqual(first['fence']['revisions'], {})

    def test_tc116_malformed_c1_or_existing_c2_cannot_be_treated_as_empty(self):
        newer = format2.parse_curation(migration_plan.progress(data(PROGRESS)))
        for raw in (b'{damaged', b'{}', data(newer), data(dict(PROGRESS, unknown=1)), 1, True, []):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                migration_plan.progress(raw)

    def test_tc116_nonce_is_generated_in_code_and_validated(self):
        with mock.patch.object(migration_plan.uuid, 'uuid4', return_value=type('Nonce', (), {'hex':'invalid'})()):
            with self.assertRaises(ValueError):
                migration_plan.progress(None)

    def test_tc390_planning_neither_reads_nor_writes_files(self):
        with mock.patch('builtins.open', side_effect=AssertionError('unexpected I/O')):
            proposal = plan(); progress = migration_plan.progress(data(PROGRESS))
        self.assertEqual(len(proposal.publications), 2)
        self.assertEqual(format2.parse_curation(progress)['applies'], 3)
