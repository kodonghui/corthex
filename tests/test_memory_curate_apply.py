"""TASK-086: checked curate-2 changes and conflict candidates applied to fabricated format-2 stores.

TC-163 to TC-165, TC-346 to TC-348 and TC-391, and the TASK-086 parts of
TC-177, TC-182 and TC-351. No model is called; the worker that will apply an
answer (TASK-088) is not wired to a hook or command before the 0.3.0 activation.
"""
import contextlib
import copy
from dataclasses import replace as dataclass_replace
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import (base, clock, conflict_counts, conflict_plan, conflict_types, curate_apply, curator_answers,
                        fence_plan, format2, item_io, item_types, locks, revision_io)
from memory_lib.c2_store import C2Store
from test_memory_fence_plan import PROGRESS
import test_memory_curator_answers as answers
from test_memory_curator_answers import AT, DEVICE, LATER, LOG, answer, change, quote, saved

RUN, NEXT = 'r_0123456789ac', 'r_0123456789ad'
LAST = '2026-11-06T09:00:00.000Z'


def ids(prefix, count=8):
    return iter(prefix + '_' + digit * 12 for digit in base.CROCKFORD[:count])


def candidate(identifier, items, status='open', run=RUN):
    value = {'id': identifier, 'items': list(items), 'at': LATER, 'run': run, 'by': 'curate', 'status': status}
    if status != 'open':
        value['closed'] = LAST
    return value


class CurateApplyTest(unittest.TestCase):
    def setUp(self):
        self.turns = answers.Turns()
        self.make_store()

    def make_store(self, *items):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / 'memory'
        (self.root / 'logs').mkdir(parents=True)
        self.project = self.root / 'projects/sample'
        for name in ('layer/items', 'layer/tombstones', 'notices'):
            (self.project / name).mkdir(parents=True, exist_ok=True)
        header = {'format': 2, 'device': DEVICE, 'made': AT, 'release': '0.3.0'}
        (self.root / 'store.json').write_bytes(format2.store_bytes(header))
        self.progress_path = self.project / 'curation.json'
        self.progress_path.write_bytes(format2.curation_bytes(PROGRESS))
        (self.project / 'layer/pins.json').write_bytes(item_types.pins_bytes({'pins': []}))
        # As the migration writes it (TASK-074).
        self.conflicts_path = self.project / 'layer/conflicts.json'
        self.conflicts_path.write_bytes(b'{"candidates":[]}\n')
        self.memory = C2Store(self.root, expected_device=DEVICE)
        self.deadline = clock.now() + 30
        self.store(*items)

    def store(self, *records):
        for value in records:
            self.path(value['id']).write_bytes(item_types.item_bytes(value))
        stored = [item_types.parse_item(path.read_bytes()) for path in (self.project / 'layer/items').glob('*.json')]
        (self.project / 'layer/item-list.txt').write_bytes(item_types.item_list_bytes(stored))

    def path(self, item):
        return self.project / 'layer/items' / (item + '.json')

    def item(self, item):
        return item_types.parse_item(self.path(item).read_bytes())

    def listed(self):
        return [line.split('\t')[0] for line in
                (self.project / 'layer/item-list.txt').read_text(encoding='utf-8').splitlines()]

    def conflicts(self):
        return conflict_types.parse_conflicts(self.conflicts_path.read_bytes())

    def candidates(self):
        return self.conflicts()['candidates']

    def counts(self):
        return conflict_counts.read(self.memory, self.project, self.deadline)

    def fence(self):
        return format2.parse_curation(self.progress_path.read_bytes())['fence']

    def proof(self):
        return fence_plan.snapshot(format2.parse_curation(self.progress_path.read_bytes()))

    def snapshot(self):
        """Every file of the project, to show that nothing changed."""
        return {str(path.relative_to(self.project)): path.read_bytes()
                for path in sorted(self.project.rglob('*')) if path.is_file()}

    def checked(self, value, items):
        sent = curator_answers.sent(items=items, logs=[(LOG, self.turns.entries)])
        return curator_answers.check_curate(value, sent=sent, device=DEVICE)

    @contextlib.contextmanager
    def held(self, curation=True):
        with contextlib.ExitStack() as stack:
            if curation:
                stack.enter_context(self.memory.lease(self.project / 'curation.lock', 'curation', self.deadline))
            stack.enter_context(self.memory.lease(self.project / 'layer.lock', 'layer', self.deadline))
            yield

    def apply(self, checked, run=RUN, at=LATER, expected=None, curation=True):
        with self.held(curation):
            return curate_apply.apply(self.memory, self.project, self.proof() if expected is None else expected,
                                      checked, at, run, self.deadline)

    def run_answer(self, value, items, **kwargs):
        checked = self.checked(value, items)
        return checked, self.apply(checked, **kwargs)

    def test_tc163_the_user_corrects_the_agent(self):
        stated = self.turns.say('agent', 'The cache is on by default.')
        correction = self.turns.say('user', 'That is wrong: the cache is off by default.')
        statement = saved('fact', stated, 'The cache is on by default')
        self.store(statement)
        _, result = self.run_answer(answer(change(quote(correction, 'the cache is off by default'), action='replace',
                                                  targets=[statement['id']], title='The cache is off')), [statement])
        ((number, new),) = result['saved']
        self.assertEqual(number, 1)
        added = self.item(new)
        self.assertEqual((added['status'], added['quotes'][0]['speaker'], added['saved'], added['device']),
                         ('current', 'user', LATER, DEVICE))
        self.assertEqual(self.item(statement['id']),
                         dict(statement, status='superseded', superseded_by=new, changed=LATER))
        self.assertEqual(self.listed(), [new])
        self.assertEqual(result['published'], ('item:' + new, 'item:' + statement['id'], 'item-list'))
        self.assertEqual((self.candidates(), result['opened'], result['settled']), ([], (), ()))
        self.assertIsNone(self.counts())

    def test_tc164_the_agent_cannot_take_back_a_user_decision(self):
        said = self.turns.say('user', 'We release on Friday.')
        later = self.turns.say('agent', 'The Friday release no longer holds; we release on Monday.')
        decision = saved('decision', said, 'We release on Friday')
        self.store(decision)
        before = self.path(decision['id']).read_bytes()
        withdraw = change(quote(later, 'The Friday release no longer holds'), action='withdraw',
                          targets=[decision['id']], kind='decision', title='No Friday release',
                          text='The Friday release no longer holds.')
        replace = change(quote(later, 'we release on Monday'), action='replace', targets=[decision['id']],
                         kind='fact', title='A Monday release', text='The agent says the release is on Monday.')
        checked, result = self.run_answer(answer(withdraw, replace), [decision])
        self.assertEqual([(c.action, c.kept) for c in checked.changes], [('add', (decision['id'],))] * 2)
        self.assertEqual(self.path(decision['id']).read_bytes(), before)
        self.assertEqual([number for number, _ in result['saved']], [1, 2])
        for (_, new), proposed in zip(result['saved'], (withdraw, replace)):
            value = self.item(new)
            self.assertEqual((value['kind'], value['title'], value['text'], value['status']),
                             (proposed['kind'], proposed['title'], proposed['text'], 'current'))
            self.assertEqual([(q['speaker'], q['words']) for q in value['quotes']],
                             [('agent', q['words']) for q in proposed['quotes']])
        self.assertEqual(sorted(self.listed()), sorted([decision['id']] + [new for _, new in result['saved']]))

    def test_tc165_a_speaker_takes_back_their_own_item(self):
        said = self.turns.say('user', 'Use tabs in the files.')
        stated = self.turns.say('agent', 'The files use spaces.')
        back = self.turns.say('user', 'Drop the tabs rule; I take it back.')
        own = self.turns.say('agent', 'I was wrong about spaces; I take that back.')
        decision = saved('decision', said, 'Use tabs')
        statement = saved('fact', stated, 'The files use spaces')
        self.store(decision, statement)
        _, result = self.run_answer(answer(
            change(quote(back, 'I take it back'), action='withdraw', targets=[decision['id']]),
            change(quote(own, 'I take that back'), action='withdraw', targets=[statement['id']])),
            [decision, statement])
        self.assertEqual(result['saved'], ())
        for value in (decision, statement):
            self.assertEqual(self.item(value['id']), dict(value, status='withdrawn', changed=LATER))
        self.assertEqual(self.listed(), [])
        self.assertEqual(self.candidates(), [])

    def test_tc346_a_new_user_decision_naming_a_current_user_decision(self):
        first = self.turns.say('user', 'Keep the logs for 30 days.')
        second = self.turns.say('user', 'Keep the logs for 90 days from now on.')
        decision = saved('decision', first, 'Keep the logs for 30 days')
        self.store(decision)
        _, result = self.run_answer(answer(change(quote(second, 'Keep the logs for 90 days'), kind='decision',
                                                  conflicts=[decision['id']])), [decision])
        ((_, new),) = result['saved']
        self.assertEqual([self.item(i)['status'] for i in (new, decision['id'])], ['current'] * 2)
        self.assertEqual([self.item(i)['quotes'][0]['speaker'] for i in (new, decision['id'])], ['user'] * 2)
        (opened,) = self.candidates()
        self.assertEqual(opened, candidate(result['opened'][0], [new, decision['id']]))
        self.assertEqual(self.conflicts_path.read_bytes(), conflict_plan.conflicts_bytes({'candidates': [opened]}))
        self.assertEqual(self.counts(), {opened['id']: 0})
        self.assertEqual(result['published'], ('item:' + new, 'conflicts', 'item-list'))
        fence = self.fence()
        for key in ('item:' + new, 'candidate:' + opened['id'], 'run:' + RUN):
            self.assertEqual(fence['revisions'][key], fence['generation'])

    def test_tc347_invalid_conflict_references_record_no_candidate(self):
        said = self.turns.say('user', 'Ship on Friday; the old plan said Monday.')
        target = saved('decision', said, 'the old plan said Monday')
        unsent = saved('fact', said, 'Ship on Friday')
        self.store(target, unsent)
        made = 'i_' + 'z' * 12
        value = answer(change(quote(said, 'Ship on Friday'), action='replace', targets=[target['id']],
                              kind='decision', conflicts=[target['id'], unsent['id'], made, answers.ident('i')]))
        checked = self.checked(value, [target])
        self.assertEqual(checked.changes[0].conflicts, ())
        before = self.conflicts_path.read_bytes()
        with mock.patch.object(base, 'new_id', side_effect=lambda prefix: made):
            result = self.apply(checked)
        self.assertEqual(result['saved'], ((1, made),))
        self.assertEqual(self.item(target['id'])['superseded_by'], made)
        self.assertEqual((self.conflicts_path.read_bytes(), result['opened'], self.counts()), (before, (), None))
        # The writer does not rely on those checks alone: the same change's targets and the item itself never pair.
        forced = dataclass_replace(checked.changes[0], conflicts=(target['id'], made))
        planned = curate_apply.plan(curator_answers.Checked((forced,), {}, checked.state),
                                    items=[target, unsent], conflicts={'candidates': []}, at=LAST, device=DEVICE,
                                    run=NEXT, make_id=lambda prefix: made)
        self.assertEqual((planned['opened'], planned['conflicts']), ([], {'candidates': []}))

    def test_tc348_a_refused_speaker_replacement_still_surfaces(self):
        said = self.turns.say('user', 'Write the docs in English first.')
        stated = self.turns.say('agent', 'English first no longer holds; the docs start in Korean.')
        decision = saved('decision', said, 'Write the docs in English first')
        self.store(decision)
        before = self.path(decision['id']).read_bytes()
        checked, result = self.run_answer(answer(change(quote(stated, 'the docs start in Korean'), action='replace',
                                                        targets=[decision['id']], kind='decision')), [decision])
        self.assertEqual((checked.changes[0].action, checked.changes[0].kept), ('add', (decision['id'],)))
        ((_, new),) = result['saved']
        self.assertEqual(self.path(decision['id']).read_bytes(), before)
        self.assertEqual((self.item(new)['status'], self.item(new)['quotes'][0]['speaker']), ('current', 'agent'))
        self.assertEqual(self.candidates(), [candidate(result['opened'][0], [new, decision['id']])])
        self.assertEqual(self.counts(), {result['opened'][0]: 0})

    def test_tc391_a_pair_is_recorded_once(self):
        said = self.turns.say('user', 'One pair of items.')
        older = saved('fact', said, 'One pair')
        newer = dict(saved('fact', said, 'of items'), saved=LATER)
        items = {value['id']: value for value in (older, newer)}
        kept = copy.deepcopy(items)
        made = ids('c')
        both, back = (older['id'], newer['id']), (newer['id'], older['id'])
        value, added = conflict_plan.record({'candidates': []}, [both, back, both], items, at=LAST, run=RUN,
                                            by='curate', make_id=lambda prefix: next(made))
        self.assertEqual(len(added), 1)
        self.assertEqual(value['candidates'][0]['items'], list(back))
        again, more = conflict_plan.record(value, [back, both], items, at=LAST, run=NEXT, by='consolidate',
                                           make_id=lambda prefix: next(made))
        self.assertEqual((again, more), (value, []))
        self.assertEqual(items, kept)
        # A settled pair is no longer open, so it may be recorded again.
        closed, settled = conflict_plan.settle(value, {older['id']}, LAST)
        self.assertEqual(settled, added)
        reopened, fresh = conflict_plan.record(closed, [both], items, at=LAST, run=NEXT, by='curate',
                                               make_id=lambda prefix: next(made))
        self.assertEqual([c['status'] for c in reopened['candidates']], ['settled', 'open'])
        self.assertEqual(len(fresh), 1)
        # Equal times put the lower ID first.
        tied = dict(saved('fact', said, 'items'), saved=LATER)
        pair = sorted((newer['id'], tied['id']))
        value, _ = conflict_plan.record({'candidates': []}, [tuple(reversed(pair))], {v['id']: v for v in (newer, tied)},
                                        at=LAST, run=RUN, by='curate', make_id=lambda prefix: next(made))
        self.assertEqual(value['candidates'][0]['items'], pair)
        # Through the writer: a kept target named again among the conflicts makes one candidate only.
        stated = self.turns.say('agent', 'One pair of items is too many.')
        self.store(older)
        checked = self.checked(answer(change(quote(stated, 'is too many'), action='withdraw',
                                             targets=[older['id']])), [older])
        doubled = dataclass_replace(checked.changes[0], conflicts=(older['id'], older['id']))
        before = self.path(older['id']).read_bytes()
        result = self.apply(curator_answers.Checked((doubled,), {}, checked.state))
        self.assertEqual(len(result['opened']), 1)
        self.assertEqual(len(self.candidates()), 1)
        self.assertEqual(self.path(older['id']).read_bytes(), before)

    def test_tc351_part_a_later_user_choice_settles_the_candidate(self):
        first = self.turns.say('user', 'Keep the logs for 30 days.')
        second = self.turns.say('user', 'Keep the logs for 90 days.')
        third = self.turns.say('user', 'Actually keep them for 60 days.')
        decision = saved('decision', first, 'Keep the logs for 30 days')
        self.store(decision)
        _, result = self.run_answer(answer(change(quote(second, 'Keep the logs for 90 days'), kind='decision',
                                                  conflicts=[decision['id']])), [decision])
        ((_, newer),) = result['saved']
        (opened,) = result['opened']
        self.assertEqual([c['id'] for c in conflict_counts.eligible(self.conflicts(), self.counts())], [opened])
        items = [self.item(decision['id']), self.item(newer)]
        _, later = self.run_answer(answer(change(quote(third, 'keep them for 60 days'), action='replace',
                                                 targets=[newer], kind='decision')), items, run=NEXT, at=LAST)
        self.assertEqual((later['settled'], later['opened']), ((opened,), ()))
        self.assertEqual(self.candidates(), [candidate(opened, [newer, decision['id']], status='settled')])
        self.assertEqual(self.counts(), {opened: 0})
        self.assertEqual(conflict_counts.eligible(self.conflicts(), self.counts()), [])
        self.assertEqual(self.item(decision['id'])['status'], 'current')
        fence = self.fence()
        self.assertEqual(fence['revisions']['candidate:' + opened], fence['generation'])

    def test_open_candidates_that_name_an_item_no_longer_current_are_settled(self):
        # As after a stop between the item files and conflicts.json: an open candidate names a superseded item.
        said = self.turns.say('user', 'Three items here.')
        first = saved('fact', said, 'Three')
        gone = dict(saved('fact', said, 'items'), status='superseded', superseded_by=first['id'], changed=AT)
        other = saved('fact', said, 'here')
        left = candidate('c_0123456789ab', [first['id'], gone['id']])
        alive = candidate('c_0123456789ac', [first['id'], other['id']])
        self.store(first, gone, other)
        self.conflicts_path.write_bytes(conflict_plan.conflicts_bytes({'candidates': [left, alive]}))
        _, result = self.run_answer(answer(change(quote(said, 'Three items'))), [first, other])
        self.assertEqual(result['settled'], (left['id'],))
        self.assertEqual(self.candidates(), [dict(left, status='settled', closed=LATER), alive])

    def test_the_writer_publishes_only_retained_closed_and_new_open_candidates(self):
        first, second, third = (answers.ident('i') for _ in range(3))
        opened = candidate('c_0123456789ab', [first, second])
        old = candidate('c_0123456789ac', [first, third], status='dismissed')
        before = {'candidates': [opened, old]}
        new = candidate('c_0123456789ad', [first, third])
        data, added, closed = conflict_plan.changes(
            before, {'candidates': [dict(opened, status='settled', closed=LAST), old, new]}, {first, third})
        self.assertEqual((added, closed), (['c_0123456789ad'], ['c_0123456789ab']))
        self.assertEqual(json.loads(data)['candidates'][2], new)
        self.assertEqual(conflict_plan.changes(before, before, {first, second})[1:], ([], []))
        current = {first, second, third}
        for after in ({'candidates': [opened]},
                      {'candidates': [old, opened]},
                      {'candidates': [dict(opened, items=[second, first]), old]},
                      {'candidates': [opened, dict(old, status='open', closed=None)]},
                      {'candidates': [opened, dict(old, status='settled')]},
                      {'candidates': [opened, old, dict(new, status='settled', closed=LAST)]}):
            after = {'candidates': [{k: v for k, v in c.items() if v is not None} for c in after['candidates']]}
            with self.subTest(after=after), self.assertRaises(ValueError):
                conflict_plan.changes(before, after, current)
        with self.assertRaises(ValueError):
            conflict_plan.changes(before, before, {first, third})
        # The item writer refuses such a value before it counts or reserves anything.
        said = self.turns.say('user', 'A fact.')
        fact = saved('fact', said, 'A fact')
        self.store(fact)
        self.conflicts_path.write_bytes(conflict_plan.conflicts_bytes(before))
        files = self.snapshot()
        with self.held(), self.assertRaises(ValueError):
            item_io.apply(self.memory, self.project, self.proof(), [], [{'id': fact['id'], 'status': 'withdrawn'}],
                          LATER, self.deadline, run_id=RUN, conflicts={'candidates': [opened]})
        self.assertEqual(self.snapshot(), files)

    def test_new_candidates_are_counted_before_any_reservation_and_a_failed_count_applies_nothing(self):
        first = self.turns.say('user', 'Keep the logs for 30 days.')
        second = self.turns.say('user', 'Keep the logs for 90 days.')
        decision = saved('decision', first, 'Keep the logs for 30 days')
        self.store(decision)
        checked = self.checked(answer(change(quote(second, 'Keep the logs for 90 days'), kind='decision',
                                             conflicts=[decision['id']])), [decision])
        files = self.snapshot()
        with mock.patch.object(conflict_counts, '_write', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.apply(checked)
        self.assertEqual(self.snapshot(), files)
        seen = []
        reserve, publish = revision_io.reserve, item_io._publish

        def reserving(*args, **kwargs):
            seen.append(('reserve', self.counts()))
            return reserve(*args, **kwargs)

        def publishing(path, *args):
            seen.append((path.name, self.counts()))
            return publish(path, *args)

        with mock.patch.object(revision_io, 'reserve', reserving), mock.patch.object(item_io, '_publish', publishing):
            result = self.apply(checked)
        counted = {result['opened'][0]: 0}
        new = result['saved'][0][1]
        self.assertEqual(seen, [('reserve', counted), (new + '.json', counted), ('conflicts.json', counted),
                                ('item-list.txt', counted)])

    def test_a_stale_proof_a_missing_curation_lease_or_no_change_applies_nothing(self):
        said = self.turns.say('user', 'A fact to keep.')
        fact = saved('fact', said, 'A fact')
        self.store(fact)
        checked = self.checked(answer(change(quote(said, 'A fact to keep'), conflicts=[fact['id']])), [fact])
        files = self.snapshot()
        with self.assertRaises(locks.LostLock):
            self.apply(checked, curation=False)
        self.assertEqual(self.snapshot(), files)
        self.assertIsNone(self.apply(self.checked(answer(), [fact])))
        expected = self.proof()
        moved = copy.deepcopy(PROGRESS)
        moved['fence']['generation'] += 1
        self.progress_path.write_bytes(format2.curation_bytes(moved))
        files = self.snapshot()
        with self.assertRaises(fence_plan.Stale):
            self.apply(checked, expected=expected)
        self.assertEqual(self.snapshot(), files)
        with self.assertRaises(ValueError):
            self.apply(checked, run='r_bad', expected=expected)
        self.assertEqual(self.snapshot(), files)

    def test_code_made_ids_never_reuse_a_stored_one(self):
        said = self.turns.say('user', 'A fact to keep.')
        fact = saved('fact', said, 'A fact')
        checked = self.checked(answer(change(quote(said, 'A fact to keep'), conflicts=[fact['id']])), [fact])
        with self.assertRaises(ValueError):
            curate_apply.plan(checked, items=[fact], conflicts={'candidates': []}, at=LATER, device=DEVICE,
                              run=RUN, make_id=lambda prefix: fact['id'])
        taken = candidate('c_0123456789ab', [fact['id'], 'i_0123456789ab'], status='settled')
        made = iter(['i_0123456789ac', 'c_0123456789ab'])
        with self.assertRaises(ValueError):
            curate_apply.plan(checked, items=[fact], conflicts={'candidates': [taken]}, at=LATER, device=DEVICE,
                              run=RUN, make_id=lambda prefix: next(made))

    def test_tc177_part_stage_06_curate_examples_apply(self):
        examples = json.loads((answers.API / 'memory-examples.json').read_text(encoding='utf-8'))['curate']['valid']
        self.turns.say('user', "Let's keep the four hooks in one script.", entry='e_5h2j8n3p0r6t')
        self.turns.say('agent', 'Done: one script now serves the four hooks, by name.', entry='e_8m1k4r7t2w5y')
        korean = self.turns.say('user', 'Answer me in Korean from now on.', entry='e_6b9e2h5k8n1r')
        self.turns.say('user', '노션 표는 모두 데이터베이스로 만들어 주세요.', entry='e_3d6g9k2n5q8t')
        preference, decision = 'i_5c8e1h4j7m0p', 'i_7f3k2m9q4x1v'
        items = [saved('preference', korean, 'Answer me in Korean', item=preference),
                 saved('decision', korean, 'Korean', item=decision)]
        for name, value in sorted(examples.items()):
            with self.subTest(example=name):
                self.make_store(*items)
                files = self.snapshot()
                _, result = self.run_answer(value, items)
                if not value['changes']:
                    # Its line edits are TASK-087's.
                    self.assertIsNone(result)
                    self.assertEqual(self.snapshot(), files)
                    continue
                self.assertEqual([number for number, _ in result['saved']], [1])
                new = result['saved'][0][1]
                proposed = value['changes'][0]
                saved_item = self.item(new)
                self.assertEqual((saved_item['kind'], saved_item['title'], saved_item['text']),
                                 (proposed['kind'], proposed['title'], proposed['text']))
                statuses = {item: self.item(item).get('superseded_by', self.item(item)['status'])
                            for item in (preference, decision)}
                pairs = [c['items'] for c in self.candidates()]
                if name == 'replace-a-preference':
                    self.assertEqual(statuses, {preference: new, decision: 'current'})
                else:
                    self.assertEqual(statuses, {preference: 'current', decision: 'current'})
                self.assertEqual(pairs, [[new, decision]] if name == 'possible-disagreement' else [])

    def test_tc182_part_changes_at_the_item_limits_are_applied(self):
        said = self.turns.say('user', 'a' * 2100 + ' ' + '가' * 700)
        marks = self.turns.say('user', '"' * 2000 + ' end')
        at_limit = [change(quote(said, 'a' * 10), title='t' * 200), change(quote(said, 'a' * 10), text='x' * 4000),
                    change(*[quote(said, 'a' * n) for n in range(1, 21)]), change(quote(said, 'a' * 2000)),
                    change(quote(said, '가' * 666)),
                    change(*[quote(marks, '"' * 1405)] * 20, title='t' * 200, text='x' * 4000)]
        checked, result = self.run_answer(answer(*at_limit), [])
        self.assertEqual(checked.dropped, {})
        self.assertEqual([number for number, _ in result['saved']], list(range(1, len(at_limit) + 1)))
        self.assertTrue(all(self.item(item)['status'] == 'current' for _, item in result['saved']))
        self.assertEqual(len(self.path(result['saved'][-1][1]).read_bytes()), 65526)
        self.assertEqual(sorted(self.listed()), sorted(item for _, item in result['saved']))


if __name__ == '__main__':
    unittest.main()
