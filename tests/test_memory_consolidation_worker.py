"""TASK-089 and TASK-090: consolidation on made-up format-2 stores, against a local test server.

TC-184 to TC-187, TC-190 to TC-195, TC-197, TC-342, TC-349 and TC-394, and
the worker's parts of TC-188, TC-189 and TC-196. Every request goes to a local
test server, with keys made up during the run; no provider is called. The
worker is not wired to a hook or command before the 0.3.0 activation.
"""
from datetime import datetime, timedelta, timezone
import json
import os
import secrets
import sys
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

from _common import ROOT
SCRIPTS = ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'
sys.path.insert(0, str(SCRIPTS))
from memory_lib import (clock, consolidation_worker, curator_answers, curator_document, fence_plan, format2,
                        history_io, item_io, item_types, request_budget, revision_io, run_log, state_rewrite,
                        state_types)
from memory_lib.c2_store import C2Store
import test_memory_curation_worker as fixture
from test_memory_curator_answers import answer as curate_answer
from test_memory_model_stream import end, start
from test_memory_request_budget import rule as counting_rule

DEVICE, AT, LOG = fixture.DEVICE, fixture.AT, fixture.LOG
LATER = '2026-11-05T08:30:00.000Z'
WHEN = datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc)  # 8 days after memory was turned on (AT)
STAMP = '2026-11-12T09:00:00.000Z'
PARTS = state_types.PARTS
REFUSAL, LIMIT, ident, failing = fixture.REFUSAL, fixture.LIMIT, fixture.ident, fixture.failing


def merge(items, picks, title='A merged item', text='The merged items say the same.'):
    return {'items': [value['id'] for value in items],
            'quotes': [{'item': value['id'], 'number': number} for value, number in picks], 'title': title,
            'text': text}


def merges(*values, conflicts=()):
    return {'merges': list(values), 'conflicts': [{'items': [value['id'] for value in pair]} for pair in conflicts]}


def shorter(**parts):
    value = {part: [] for part in PARTS}
    value.update(parts)
    return {'state': value}


def _ids(values):
    return [value if isinstance(value, str) else value['id'] for value in values]


def keeps(line, text=None, cites=None):
    return {'keeps': line['id'], 'text': line['text'] if text is None else text,
            'cites': _ids(line['cites'] if cites is None else cites), 'changes': []}


def added(text, cites):
    return {'keeps': '', 'text': text, 'cites': _ids(cites), 'changes': []}


def row(part, pos, text, cites, line=None):
    return dict(id=line or ident('s'), part=part, pos=pos, text=text, cites=_ids(cites), at=AT, device=DEVICE)


class ConsolidationWorkerTest(unittest.TestCase):
    # The store and the local test server of the curation worker's tests (TASK-088).
    setUp = fixture.CurationWorkerTest.setUp
    configure = fixture.CurationWorkerTest.configure
    layer = fixture.CurationWorkerTest.layer
    write = fixture.CurationWorkerTest.write
    saved = fixture.CurationWorkerTest.saved
    advance = fixture.CurationWorkerTest.advance
    progress = fixture.CurationWorkerTest.progress
    items = fixture.CurationWorkerTest.items
    usage = fixture.CurationWorkerTest.usage
    failures = fixture.CurationWorkerTest.failures
    runs = fixture.CurationWorkerTest.runs
    snapshot = fixture.CurationWorkerTest.snapshot
    quick = fixture.CurationWorkerTest.quick

    def item(self, kind, words, speaker='user', saved=AT, title=None, write=True):
        """A current item whose deciding quote is a new turn of the raw log, said by `speaker`."""
        said, answered = self.raw.turn(words + '.' if speaker == 'user' else 'Go on.',
                                       words + '.' if speaker == 'agent' else 'Noted.')
        if write:
            self.write()
        value = self.saved(said if speaker == 'user' else answered, words, kind=kind)
        value.update(saved=saved, title=title or words)
        return value

    def state(self):
        return {line['id']: line for line in
                state_types.parse_state((self.root / 'layer/state.json').read_bytes())['lines']}

    def history(self):
        return [record.value for record in
                state_types.parse_history((self.root / 'state-history.jsonl').read_bytes())]

    def candidates(self):
        return json.loads((self.root / 'layer/conflicts.json').read_bytes())['candidates']

    def notice(self):
        path = self.root / 'notices/consolidation-failed.json'
        return item_types.parse_notice(path.read_bytes()) if path.exists() else None

    def consolidate(self, seconds=300, when=WHEN):
        deadline = clock.now() + seconds
        with self.memory.lease(self.root / 'curation.lock', 'curation', deadline) as owner:
            return consolidation_worker.consolidate(self.memory, 'sample', owner, deadline, when=when)

    def answering(self, groups=None, last=None):
        """Answer each merge request by its group, and the last request with `last`; both default to no change."""
        groups = dict(groups or {})

        def reply(number, body):
            root = ET.fromstring(body['messages'][0]['content'])
            if root.get('kind') == 'merge':
                value = groups.get(root.get('group'), merges())
                if isinstance(value, list):
                    value = value.pop(0) if len(value) > 1 else value[0]
                return value
            return shorter() if last is None else last
        self.server.reply = reply

    def sent(self):
        """Each request as (kind, group, the IDs of the items it carries in order)."""
        found = []
        for _, body in self.server.requests:
            root = ET.fromstring(body['messages'][0]['content'])
            found.append((root.get('kind'), root.get('group'), [value.get('id') for value in root.iter('item')]))
        return found

    def new_items(self, *known):
        return [value for item, value in self.items().items() if item not in {value['id'] for value in known}]

    # SPEC-019: merges

    def test_tc184_two_items_that_say_the_same_become_one_current_item(self):
        first = self.item('preference', 'Answer me in Korean')
        second = self.item('preference', 'Korean answers, please', saved=LATER)
        fact = self.item('fact', 'The repository is public')
        self.layer([first, second, fact])
        self.answering({'preference': merges(merge([first, second], [(second, 1), (first, 1)],
                                                   title='Answers in Korean', text='The user wants Korean answers.'))})
        outcome = self.consolidate()
        self.assertEqual((outcome.reason, outcome.requests, outcome.applied), ('done', 1, True))
        # A kind with one item sends nothing, and an empty state needs no last request.
        self.assertEqual(self.sent(), [('merge', 'preference', [first['id'], second['id']])])
        (new,) = self.new_items(first, second, fact)
        self.assertEqual(new, {'id': new['id'], 'kind': 'preference', 'title': 'Answers in Korean',
                               'text': 'The user wants Korean answers.',
                               'quotes': [second['quotes'][0], first['quotes'][0]], 'status': 'current',
                               'merges': [first['id'], second['id']], 'saved': STAMP, 'device': DEVICE})
        items = self.items()
        for value in (first, second):
            self.assertEqual(items[value['id']], dict(value, status='superseded', superseded_by=new['id'],
                                                      changed=STAMP))
        self.assertEqual(items[fact['id']], fact)
        progress = self.progress()
        record = progress['recent'][0]
        self.assertEqual(record, {'at': STAMP, 'kind': 'consolidate', 'result': 'ok', 'applied': 1, 'dropped': 0,
                                  'state': 'kept', 'run': record['run']})
        self.assertEqual(outcome.attempts, (record,))
        self.assertEqual((progress['consolidation'], progress['applies']), ({'failures': 0, 'last': STAMP}, 1))
        log = run_log.read(self.root, record['run'])
        self.assertEqual((log['kind'], log['saved'], log['merges']),
                         ('consolidate', [new['id']], [{'item': new['id'], 'merged': [first['id'], second['id']]}]))
        self.assertEqual(sorted(entry['item'] for entry in log['statuses']), sorted([first['id'], second['id']]))
        listed = (self.root / 'layer/item-list.txt').read_text(encoding='utf-8')
        self.assertIn(new['id'], listed)
        self.assertNotIn(first['id'], listed)
        self.assertEqual([(row['call'], row['instructions'], row['result']) for row in self.usage()],
                         [('consolidate', 'merge-2', 'ok')])
        # A week later nothing is due; the next consolidation is due 7 days after this one.
        self.assertEqual(self.consolidate(when=WHEN + timedelta(days=6)).reason, 'not-due')
        self.assertEqual(len(self.server.requests), 1)

    def test_tc175_a_merge_keeps_a_quote_whose_raw_log_is_gone(self):
        first = self.item('fact', 'The repository is public')
        second = self.item('fact', 'Anyone can read the repository', saved=LATER)
        self.layer([first, second])
        # Retention deleted the raw log that holds both quotes; a merge reads no raw log.
        (self.root / 'raw' / (self.raw.name + '.jsonl')).unlink()
        self.answering({'fact': merges(merge([first, second], [(second, 1), (first, 1)], title='Public'))})
        self.assertEqual(self.consolidate().reason, 'done')
        (new,) = self.new_items(first, second)
        self.assertEqual((new['merges'], new['quotes']),
                         ([first['id'], second['id']], [second['quotes'][0], first['quotes'][0]]))

    def test_tc185_tc194_the_record_counts_each_dropped_merge_by_reason(self):
        users = [self.item('decision', 'Keep the hooks in one script'),
                 self.item('decision', 'One script for the hooks', saved=LATER)]
        agent = self.item('decision', 'The hooks share one script', speaker='agent')
        self.layer(users + [agent])
        first, second = users
        self.answering({'decision': merges(
            merge([first, agent], [(agent, 1), (first, 1)], title='The agent first'),  # speaker (TC-194)
            merge([first, second], [(first, 2)], title='No second quote'),  # quote (TC-185)
            merge([first], [(first, 1)], title='One item'),  # shape
            merge([first, {'id': ident('i')}], [(first, 1)], title='Not sent'),  # not-in-request
            merge([first, second], [(second, 1)], title='T' * 201),  # limit
            merge([second, first], [(second, 1), (first, 1), (second, 1)], title='One script'),
            merge([first, agent], [(first, 1), (agent, 1)], title='Merged already'))})  # not-current
        outcome = self.consolidate()
        self.assertEqual(outcome.reason, 'done')
        record = self.progress()['recent'][0]
        self.assertEqual(record, {'at': STAMP, 'kind': 'consolidate', 'result': 'ok', 'applied': 1, 'dropped': 6,
                                  'reasons': {'shape': 1, 'limit': 1, 'not-in-request': 1, 'not-current': 1,
                                              'quote': 1, 'speaker': 1},
                                  'state': 'kept', 'run': record['run']})
        (new,) = self.new_items(first, second, agent)
        # The quote that both picks name is kept once; the user's decision stays the user's (TC-194).
        self.assertEqual((new['title'], new['quotes']), ('One script', [second['quotes'][0], first['quotes'][0]]))
        self.assertEqual(new['quotes'][0]['speaker'], 'user')
        self.assertEqual(self.items()[agent['id']], agent)

    def test_tc194_a_merge_that_puts_the_agents_quote_first_is_dropped(self):
        user = self.item('decision', 'Keep raw logs on the device')
        agent = self.item('decision', 'Raw logs stay on this device', speaker='agent', saved=LATER)
        other = self.item('decision', 'The raw logs never leave the device', speaker='agent', saved=LATER)
        self.layer([user, agent, other])
        self.answering({'decision': merges(merge([user, agent], [(agent, 1), (user, 1)]),
                                           merge([agent, other], [(other, 1), (agent, 1)], title='Agents'))})
        self.assertEqual(self.consolidate().reason, 'done')
        record = self.progress()['recent'][0]
        self.assertEqual((record['applied'], record['reasons']), (1, {'speaker': 1}))
        items = self.items()
        self.assertEqual(items[user['id']], user)
        (new,) = self.new_items(user, agent, other)
        self.assertEqual((new['merges'], new['quotes'][0]['speaker']), ([agent['id'], other['id']], 'agent'))

    def test_tc349_a_disagreement_opens_one_candidate_and_merges_none(self):
        keep = self.item('decision', 'Keep raw logs on the device')
        send = self.item('decision', 'Send raw logs to the server', saved=LATER)
        first = self.item('decision', 'Use tabs in the files')
        second = self.item('decision', 'Tabs in every file', saved=LATER)
        self.layer([keep, send, first, second])
        self.answering({'decision': merges(merge([first, second], [(first, 1), (second, 1)], title='Tabs'),
                                           conflicts=[(keep, send), (send, keep), (keep, keep), (keep, first)])})
        self.assertEqual(self.consolidate().reason, 'done')
        items = self.items()
        self.assertEqual((items[keep['id']], items[send['id']]), (keep, send))
        record = self.progress()['recent'][0]
        (candidate,) = self.candidates()
        # The newer item comes first; a pair with an item that the same answer merged is not recorded.
        self.assertEqual(candidate, {'id': candidate['id'], 'items': [send['id'], keep['id']], 'at': STAMP,
                                     'run': record['run'], 'by': 'consolidate', 'status': 'open'})
        log = run_log.read(self.root, record['run'])
        self.assertEqual(log['conflicts'], [{'candidate': candidate['id'], 'from': 'absent', 'to': 'open'}])

    def test_an_answer_that_only_names_a_disagreement_publishes_the_candidate_alone(self):
        keep = self.item('decision', 'Keep raw logs on the device')
        send = self.item('decision', 'Send raw logs to the server', saved=LATER)
        self.layer([keep, send])
        before = (self.root / 'layer/item-list.txt').read_bytes()
        self.answering({'decision': merges(conflicts=[(keep, send)])})
        outcome = self.consolidate()
        self.assertEqual((outcome.reason, outcome.applied), ('done', True))
        record = self.progress()['recent'][0]
        self.assertEqual(record, {'at': STAMP, 'kind': 'consolidate', 'result': 'ok', 'applied': 0, 'dropped': 0,
                                  'state': 'kept', 'run': record['run']})
        self.assertEqual(len(self.candidates()), 1)
        self.assertEqual(((self.root / 'layer/item-list.txt').read_bytes(), self.items()),
                         (before, {keep['id']: keep, send['id']: send}))
        log = run_log.read(self.root, record['run'])
        self.assertEqual((log['saved'], log['statuses'], log['merges'], len(log['conflicts'])), ([], [], [], 1))
        # The same pair named again opens nothing more.
        self.answering({'decision': merges(conflicts=[(send, keep)])})
        self.assertEqual(self.consolidate(when=WHEN + timedelta(days=8)).reason, 'done')
        self.assertEqual(len(self.candidates()), 1)
        self.assertNotIn('run', self.progress()['recent'][0])

    def test_a_merge_settles_the_candidates_of_its_items_and_moves_their_pin(self):
        first = self.item('decision', 'Keep raw logs on the device')
        second = self.item('decision', 'Raw logs stay on this device', saved=LATER)
        other = self.item('decision', 'Send raw logs to the server', saved=LATER)
        candidate = {'id': ident('c'), 'items': [other['id'], first['id']], 'at': AT, 'run': 'r_0123456789ab',
                     'by': 'curate', 'status': 'open'}
        self.layer([first, second, other], candidates=[candidate], pinned=[first['id']])
        self.answering({'decision': merges(merge([first, second], [(first, 1), (second, 1)], title='Raw logs'))})
        self.assertEqual(self.consolidate().reason, 'done')
        (new,) = self.new_items(first, second, other)
        self.assertEqual(self.candidates(), [dict(candidate, status='settled', closed=STAMP)])
        pins = item_types.parse_pins((self.root / 'layer/pins.json').read_bytes())['pins']
        self.assertEqual({pin['item']: pin['on'] for pin in pins}, {first['id']: False, new['id']: True})
        notice = item_types.parse_notice((self.root / 'notices' / ('pin-' + first['id'] + '.json')).read_bytes())
        self.assertEqual(notice, {'at': STAMP, 'kind': 'pin-moved', 'item': first['id'], 'to': new['id']})

    def test_groups_go_in_stage_06_order_and_a_kind_in_parts_by_time(self):
        values = [self.item(kind, kind + ' ' + str(number), saved='2026-11-0%dT03:00:00.000Z' % (5 - number))
                  for kind in ('fact', 'reference', 'lesson', 'preference', 'decision') for number in range(4)]
        self.layer(values)
        self.answering()
        real = request_budget.FILL
        # Each request holds two items at most, so a kind of four goes in two parts, oldest first.
        with mock.patch.object(request_budget, 'FILL', 1), \
                mock.patch.object(request_budget, '_size', side_effect=lambda queue, *a, **k: (
                    queue[:2], queue[2:], None, 0)):
            outcome = self.consolidate()
        self.assertEqual(request_budget.FILL, real)
        self.assertEqual((outcome.reason, outcome.requests), ('done', 10))
        by_kind = {}
        for value in values:
            by_kind.setdefault(value['kind'], []).append(value['id'])
        expected = []
        for kind in consolidation_worker.GROUPS:
            oldest = list(reversed(by_kind[kind]))
            expected += [('merge', kind, oldest[:2]), ('merge', kind, oldest[2:])]
        self.assertEqual(self.sent(), expected)
        self.assertEqual(self.progress()['applies'], 10)

    # SPEC-019: the current state

    def test_tc186_a_decision_line_that_cites_an_item_of_the_first_group_stays(self):
        first = self.item('decision', 'Keep the hooks in one script')
        second = self.item('decision', 'One script for the hooks', saved=LATER)
        facts = [self.item('fact', 'The repository is public'), self.item('fact', 'The repository is on GitHub')]
        line = row('decisions', 0, 'The hooks share one script.', [first])
        self.layer([first, second] + facts, lines=[line])
        self.answering({'decision': merges(merge([first, second], [(first, 1), (second, 1)], title='One script'))},
                       last=shorter())
        outcome = self.consolidate()
        self.assertEqual((outcome.reason, [kind for kind, _, _ in self.sent()]),
                         ('done', ['merge', 'merge', 'state']))
        (new,) = self.new_items(first, second, *facts)
        # The merge recited the line; the last answer kept the state as it was.
        self.assertEqual(self.state(), {line['id']: dict(line, cites=[new['id']], at=STAMP)})
        self.assertEqual([(r['line'], r['op'], r['why']) for r in self.history()],
                         [(line['id'], 'recited', 'recited')])
        record = self.progress()['recent'][0]
        self.assertEqual((record['state'], record['applied']), ('kept', 1))
        self.assertEqual(self.progress()['applies'], 3)
        # The last request carried the recited line and the merged item.
        root = ET.fromstring(self.server.requests[-1][1]['messages'][0]['content'])
        self.assertEqual([(value.get('id'), value.get('cites')) for value in root.iter('line')],
                         [(line['id'], new['id'])])
        self.assertIn(new['id'], [value.get('id') for value in root.iter('item')])

    def test_tc187_when_the_second_group_fails_the_line_cites_the_merged_item(self):
        first = self.item('decision', 'Keep the hooks in one script')
        second = self.item('decision', 'One script for the hooks', saved=LATER)
        facts = [self.item('fact', 'The repository is public'), self.item('fact', 'The repository is on GitHub')]
        line = row('decisions', 0, 'The hooks share one script.', [first])
        self.layer([first, second] + facts, lines=[line])
        self.answering({'decision': merges(merge([first, second], [(first, 1), (second, 1)], title='One script')),
                        'fact': REFUSAL})
        outcome = self.consolidate()
        self.assertEqual((outcome.reason, [kind for kind, _, _ in self.sent()]), ('failed', ['merge', 'merge']))
        (new,) = self.new_items(first, second, *facts)
        self.assertEqual(self.state()[line['id']]['cites'], [new['id']])
        progress = self.progress()
        record = progress['recent'][0]
        self.assertEqual(record, {'at': STAMP, 'kind': 'consolidate', 'result': 'failed', 'error': 'refusal',
                                  'applied': 1, 'dropped': 0, 'run': record['run']})
        # The first group stays applied, and consolidation stays due.
        self.assertEqual((progress['consolidation'], progress['applies']), ({'failures': 1}, 1))
        self.assertTrue(consolidation_worker.due(progress['consolidation'], AT, WHEN))
        self.assertEqual(self.notice(), {'at': STAMP, 'kind': 'consolidation-failed', 'error': 'refusal'})
        # The next curation does not drop the line for its citation.
        said, _ = self.raw.turn('Name the script hook.py.', 'The script is hook.py now.')
        self.write()
        self.server.reply = None
        self.server.answers = [curate_answer()]
        deadline = clock.now() + 300
        with self.memory.lease(self.root / 'curation.lock', 'curation', deadline) as owner:
            curated = fixture.curation_worker.curate(self.memory, 'sample', owner, deadline,
                                                     when=WHEN + timedelta(hours=1))
        self.assertEqual(curated.reason, 'done')
        self.assertEqual(self.state()[line['id']]['cites'], [new['id']])

    def test_tc191_a_line_that_cites_only_a_raw_entry_is_not_dropped_for_it(self):
        value = self.item('decision', 'Keep raw logs on the device')
        entry = value['quotes'][0]['entry']
        other = self.raw.entries[-1]['id']
        step = row('progress', 0, 'The raw log reader is half done.', [entry])
        self.layer([value], lines=[step])
        self.answering(last=shorter(progress=[keeps(step, text='The raw log reader is done.')],
                                    next=[added('Read the other log.', [other]),
                                          added('Ship the reader.', [entry])]))
        self.assertEqual(self.consolidate().reason, 'done')
        lines = self.state()
        self.assertEqual(lines[step['id']], dict(step, text='The raw log reader is done.', at=STAMP))
        (new,) = [line for key, line in lines.items() if key != step['id']]
        self.assertEqual((new['part'], new['text'], new['cites']), ('next', 'Ship the reader.', [entry]))
        # An entry that the request's state does not cite is not the line's to cite.
        record = self.progress()['recent'][0]
        self.assertEqual((record['state'], record['edit_reasons']), ('new', {'cites': 1}))

    def test_tc342_the_earlier_text_of_each_change_goes_to_history_first(self):
        first = self.item('decision', 'Keep the hooks in one script')
        second = self.item('decision', 'One script for the hooks', saved=LATER)
        goal = row('goal', 0, 'Ship the plugin.', [first])
        cited = row('decisions', 0, 'The hooks share one script.', [first])
        step = row('progress', 0, 'The hook script is written.', [second])
        self.layer([first, second], lines=[goal, cited, step])
        self.answering({'decision': merges(merge([first, second], [(first, 1), (second, 1)], title='One script'))},
                       last=None)
        state_answer = {}

        def last(number, body):
            root = ET.fromstring(body['messages'][0]['content'])
            if root.get('kind') == 'merge':
                return merges(merge([first, second], [(first, 1), (second, 1)], title='One script'))
            (new,) = [value.get('id') for value in root.iter('item')]
            state_answer['new'] = new
            # The goal is reworded, the decision kept as it is and the step left out.
            return shorter(goal=[keeps(goal, text='Ship corthex-memory.', cites=[new])],
                           decisions=[keeps(cited, cites=[new])])
        self.server.reply = last
        self.assertEqual(self.consolidate().reason, 'done')
        new = state_answer['new']
        lines = self.state()
        self.assertEqual(sorted(lines), sorted([goal['id'], cited['id']]))
        self.assertEqual(lines[goal['id']], dict(goal, text='Ship corthex-memory.', cites=[new], at=STAMP))
        self.assertEqual(lines[cited['id']], dict(cited, cites=[new], at=STAMP))
        history = self.history()
        summary = [(r['line'], r['op'], r['why'], r['text'], r['cites']) for r in history]
        # The merge recites the three lines in one apply, then the last answer changes one and removes one.
        self.assertEqual(sorted(summary[:3]), sorted([(cited['id'], 'recited', 'recited', cited['text'], [first['id']]),
                                                      (goal['id'], 'recited', 'recited', goal['text'], [first['id']]),
                                                      (step['id'], 'recited', 'recited', step['text'],
                                                       [second['id']])]))
        # Within one apply the publisher appends the records in line ID order, and the IDs are made up per run.
        self.assertEqual(sorted(summary[3:]), sorted([(goal['id'], 'changed', 'consolidation', goal['text'], [new]),
                                                      (step['id'], 'removed', 'consolidation', step['text'], [new])]))
        self.assertEqual(len({r['generation'] for r in history[:3]} | {r['generation'] for r in history[3:]}), 2)
        record = self.progress()['recent'][0]
        self.assertEqual(record['state'], 'new')
        log = run_log.read(self.root, record['run'])
        self.assertEqual(len(log['applies']), 3)
        # Each line entry links the history record of its own apply.
        generations = [entry['generation'] for entry in log['applies']]
        linked = {(entry['line'], entry['generation']): entry['history'] for entry in log['lines']}
        for record_value in history:
            reference = linked[(record_value['line'], record_value['generation'])]
            self.assertEqual(reference[1:3], [record_value['generation'], record_value['line']])
            self.assertIn(record_value['generation'], generations[1:])

    def test_a_last_answer_over_the_limit_is_cut_and_does_not_make_consolidation_due(self):
        value = self.item('decision', 'Keep raw logs on the device')
        lines = [row('progress', number, 'Step %d: %s.' % (number, 'x' * 600), [value]) for number in range(4)]
        self.layer([value], lines=lines)
        self.answering(last=shorter(progress=[keeps(line) for line in lines] + [added('y' * 900, [value])]))
        self.assertEqual(self.consolidate().reason, 'done')
        progress = self.progress()
        record = progress['recent'][0]
        self.assertEqual(record['state'], 'cut')
        self.assertEqual(progress['consolidation'], {'failures': 0, 'last': STAMP})
        self.assertLess(sum(len(line['text'].encode('utf-8')) for line in self.state().values()), 3000)

    def test_an_empty_last_answer_keeps_the_state_and_counts_its_request(self):
        value = self.item('decision', 'Keep raw logs on the device')
        line = row('decisions', 0, 'Raw logs stay here.', [value])
        self.layer([value], lines=[line])
        before = self.snapshot()['layer/state.json']
        self.answering(last=shorter())
        outcome = self.consolidate()
        self.assertEqual((outcome.reason, outcome.requests, outcome.applied), ('done', 1, False))
        self.assertEqual(self.snapshot()['layer/state.json'], before)
        progress = self.progress()
        self.assertEqual(progress['recent'][0], {'at': STAMP, 'kind': 'consolidate', 'result': 'ok', 'applied': 0,
                                                 'dropped': 0, 'state': 'kept'})
        self.assertEqual((progress['applies'], self.runs()), (1, []))

    # SPEC-019: when it runs, and what it sends

    def test_tc188_consolidation_is_due_a_week_after_the_last_or_when_made_due(self):
        due = consolidation_worker.due
        week = datetime(2026, 11, 11, 3, 0, tzinfo=timezone.utc)
        self.assertTrue(due({'failures': 0}, AT, week))
        self.assertFalse(due({'failures': 0}, AT, week - timedelta(milliseconds=1)))
        self.assertFalse(due({'failures': 0, 'last': LATER}, AT, week))
        self.assertTrue(due({'failures': 0, 'last': LATER}, AT, week + timedelta(days=2)))
        self.assertTrue(due({'failures': 0, 'last': LATER, 'due': '2026-11-06T00:00:00.000Z'}, AT,
                            datetime(2026, 11, 6, tzinfo=timezone.utc)))
        self.assertFalse(due({'failures': 0, 'last': LATER, 'due': '2026-11-06T00:00:00.001Z'}, AT,
                             datetime(2026, 11, 6, tzinfo=timezone.utc)))
        # Not due: nothing is read, sent or written.
        value = self.item('decision', 'Keep raw logs on the device')
        self.layer([value, self.item('decision', 'Raw logs stay here', saved=LATER)],
                   lines=[row('decisions', 0, 'Raw logs stay here.', [value])])
        stored = self.snapshot()
        self.assertEqual(self.consolidate(when=week - timedelta(hours=1)),
                         consolidation_worker.Outcome('not-due', (), 0, False))
        self.assertEqual((self.server.requests, self.server.counts, self.snapshot()), ([], [], stored))
        # Made due by a cut of curation (SPEC-015), it runs, with no unprocessed turns needed.
        progress = self.progress()
        progress['consolidation']['due'] = '2026-11-06T00:00:00.000Z'
        (self.root / 'curation.json').write_bytes(format2.curation_bytes(progress))
        self.answering()
        outcome = self.consolidate(when=datetime(2026, 11, 6, 1, 0, tzinfo=timezone.utc))
        self.assertEqual((outcome.reason, outcome.requests), ('done', 2))
        self.assertEqual(self.progress()['consolidation'], {'failures': 0, 'last': '2026-11-06T01:00:00.000Z'})

    def test_tc189_gates_end_the_run_before_any_request_and_consolidation_stays_due(self):
        values = [self.item('decision', 'Keep raw logs on the device'),
                  self.item('decision', 'Raw logs stay here', saved=LATER)]
        self.layer(values)
        stored = self.snapshot()
        cases = (('disabled', lambda: self.configure(enabled=False)), ('consent', lambda: self.configure(consent=None)),
                 ('key', lambda: os.environ.update(CORTHEX_MEMORY_ANTHROPIC_API_KEY='')),
                 ('configuration', lambda: (self.folder / 'configuration.json').write_bytes(b'{"projects": 3}')))
        for reason, setting in cases:
            with self.subTest(reason=reason):
                setting()
                self.assertEqual(self.consolidate(), consolidation_worker.Outcome(reason, (), 0, False))
                self.configure()
                os.environ['CORTHEX_MEMORY_ANTHROPIC_API_KEY'] = self.keys['CORTHEX_MEMORY_ANTHROPIC_API_KEY']
        progress = self.progress()
        progress['stopped'] = {'at': AT, 'by': 'curate', 'errors': ['refusal']}
        (self.root / 'curation.json').write_bytes(format2.curation_bytes(progress))
        self.assertEqual(self.consolidate().reason, 'stopped')
        tombstone = item_types._raw({'project': 'sample', 'at': AT, 'device': DEVICE}) + b'\n'
        (self.root / 'layer/deleted.json').write_bytes(tombstone)
        self.assertEqual(self.consolidate().reason, 'deleted')
        (self.root / 'layer/deleted.json').unlink()
        self.assertEqual((self.server.requests, self.server.counts), ([], []))
        del progress['stopped']
        (self.root / 'curation.json').write_bytes(format2.curation_bytes(progress))
        self.assertEqual(self.snapshot(), stored)
        # The next run that meets none of them consolidates.
        self.answering()
        self.assertEqual(self.consolidate().reason, 'done')
        self.assertEqual(self.progress()['consolidation'], {'failures': 0, 'last': STAMP})

    def test_tc190_the_last_request_carries_every_item_that_the_state_cites(self):
        kinds = ('decision', 'preference', 'lesson', 'reference', 'fact')
        values = [self.item(kinds[number % 5], 'Item %d said' % number, title='Item %04d ' % number + 'y' * 190,
                            saved='2026-11-0%dT%02d:00:00.000Z' % (1 + number % 4, number % 24), write=False)
                  for number in range(1300)]
        # The oldest items are cited and pinned, so that a list of the newest would leave them out.
        cited = [values[0], values[4], values[8]]
        pinned = values[12]
        lines = [row('progress', number, 'Line %d.' % number, [value]) for number, value in enumerate(cited)]
        self.layer(values, lines=lines, pinned=[pinned['id']])
        short = curator_document._items(values, 'short')[1]
        self.assertGreater(min(request_budget.safe(short), counting_rule(short)), 100000)
        self.answering()
        self.assertEqual(self.consolidate().reason, 'done')
        self.assertEqual([kind for kind, _, _ in self.sent()], ['merge'] * 5 + ['state'])
        body = self.server.requests[-1][1]
        root = ET.fromstring(body['messages'][0]['content'])
        self.assertEqual((root.get('kind'), root.find('items').get('form')), ('state', 'part'))
        carried = [value.get('id') for value in root.iter('item')]
        self.assertLess(len(carried), len(values))
        self.assertLessEqual({value['id'] for value in cited + [pinned]}, set(carried))
        self.assertLess(request_budget.safe(body['messages'][0]['content']), 100000)

    def test_tc197_tc394_a_consolidation_sends_current_items_of_one_kind_and_nothing_private(self):
        marker = 'marker-' + secrets.token_hex(8)
        values, hidden = [], []
        kinds = ('decision', 'preference', 'lesson', 'reference', 'fact')
        for number in range(500):
            kind = kinds[number % 5] if number < 400 else 'fact'
            # The facts are long enough that their kind goes in parts.
            values.append(self.item(kind, 'Item %d: %s' % (number, 'detail ' * (250 if kind == 'fact' else 40)),
                                    saved='2026-11-%02dT%02d:00:00.000Z' % (1 + number % 4, number % 24),
                                    title='Item %d' % number, write=False))
        source = self.raw.entries[-1]
        for status in ('superseded', 'withdrawn'):
            value = self.saved(source, source['text'][:5], kind='fact')
            value.update(title=status + ' ' + marker, status=status)
            if status == 'superseded':
                value['superseded_by'] = values[0]['id']
            hidden.append(value)
        forgotten = self.saved(source, source['text'][:5], kind='fact')
        forgotten['title'] = 'forgotten ' + marker
        hidden.append(forgotten)
        line = row('progress', 0, 'Item zero is current.', [values[0]])
        self.layer(values + hidden, lines=[line])
        quote = forgotten['quotes'][0]
        (self.root / 'layer/tombstones' / (forgotten['id'] + '.json')).write_bytes(item_types._raw(
            {'item': forgotten['id'], 'project': 'sample', 'at': AT, 'device': DEVICE,
             'quotes': [{k: quote[k] for k in ('device', 'entry', 'log', 'start', 'end')}]}) + b'\n')
        # Marked text in the raw log, the history, the run logs, the notices and another project.
        self.raw.turn('Unquoted ' + marker, 'Also unquoted ' + marker)
        self.write()
        (self.root / 'state-history.jsonl').write_bytes(b'')
        (self.root / 'runs' / 'r_0123456789ab.json').write_text('{"marker": "%s"}' % marker, encoding='utf-8')
        (self.root / 'notices' / 'rebuilt.json').write_text('{"marker": "%s"}' % marker, encoding='utf-8')
        another = self.folder / 'projects' / 'another' / 'layer' / 'items'
        another.mkdir(parents=True)
        (another / (ident('i') + '.json')).write_text('{"title": "%s"}' % marker, encoding='utf-8')
        progress = self.progress()
        progress['fence'].update(generation=7, revisions={'item:' + values[1]['id']: 7})
        (self.root / 'curation.json').write_bytes(format2.curation_bytes(progress))
        self.answering()
        outcome = self.consolidate()
        self.assertEqual(outcome.reason, 'done')
        sent = self.sent()
        self.assertEqual(sent[-1][0], 'state')
        merged = [request for request in sent if request[0] == 'merge']
        current = {value['id']: value for value in values}
        kinds_sent, every = [], []
        for _, group, carried in merged:
            kinds_sent.append(group)
            self.assertTrue(all(current[item]['kind'] == group for item in carried))
            times = [(current[item]['saved'], item) for item in carried]
            self.assertEqual(times, sorted(times))
            every += carried
        self.assertEqual(sorted(every), sorted(current))
        self.assertEqual(kinds_sent, sorted(kinds_sent, key=consolidation_worker.GROUPS.index))
        self.assertGreater(kinds_sent.count('fact'), 1)
        for headers, body in self.server.requests:
            text = json.dumps(body, ensure_ascii=False)
            self.assertLess(request_budget.safe(body['messages'][0]['content']), 100000)
            for value in (marker, 'Unquoted', 'r_0123456789ab', '"revisions"', self.keys[
                    'CORTHEX_MEMORY_ANTHROPIC_API_KEY'], self.keys['ANTHROPIC_API_KEY']):
                self.assertNotIn(value, text)
            for value in hidden:
                self.assertNotIn(value['id'], text)
        root = ET.fromstring(self.server.requests[0][1]['messages'][0]['content'])
        self.assertEqual((root.get('kind'), root.get('instructions')), ('merge', 'merge-2'))
        first = next(iter(root.iter('item')))
        self.assertEqual([quote.get('n') for quote in first.iter('quote')], ['1'])
        # Each request adds one usage line, and each count of a large part one more.
        rows = self.usage()
        self.assertEqual([row['instructions'] for row in rows if row['call'] == 'consolidate'],
                         ['merge-2'] * len(merged) + ['state-1'])
        self.assertEqual(len([row for row in rows if row['call'] == 'count-tokens']), len(self.server.counts))

    # SPEC-018 and SPEC-012

    def test_tc192_tc196_an_unusable_answer_changes_nothing_of_its_group_or_the_state(self):
        first = self.item('decision', 'Keep raw logs on the device')
        second = self.item('decision', 'Raw logs stay here', saved=LATER)
        facts = [self.item('fact', 'The repository is public'), self.item('fact', 'The repository is on GitHub')]
        line = row('decisions', 0, 'Raw logs stay here.', [first])
        self.layer([first, second] + facts, lines=[line])
        state_before = self.snapshot()['layer/state.json']
        empty = start() + end()
        cases = (('refusal', REFUSAL), ('max-tokens', LIMIT), ('empty-answer', empty),
                 ('bad-answer', fixture.stream({'merges': 'none'})))
        for code, reply in cases:
            with self.subTest(group=code):
                self.layer([first, second] + facts, lines=[line])
                for name in ('consolidation-failed.json',):
                    path = self.root / 'notices' / name
                    if path.exists():
                        path.unlink()
                progress = self.progress()
                progress['consolidation'] = {'failures': 0}
                (self.root / 'curation.json').write_bytes(format2.curation_bytes(progress))
                for value in self.new_items(first, second, *facts):
                    (self.root / 'layer/items' / (value['id'] + '.json')).unlink()
                self.answering({'decision': merges(merge([first, second], [(first, 1), (second, 1)])),
                                'fact': reply})
                with self.quick():
                    outcome = self.consolidate()
                self.assertEqual(outcome.reason, 'failed')
                record = self.progress()['recent'][0]
                self.assertEqual((record['result'], record['error'], record['applied']), ('failed', code, 1))
                self.assertEqual({value['id']: value['status'] for value in facts},
                                 {key: self.items()[key]['status'] for key in (facts[0]['id'], facts[1]['id'])})
                self.assertEqual(self.progress()['consolidation'], {'failures': 1})
                self.assertEqual(self.notice(), {'at': STAMP, 'kind': 'consolidation-failed', 'error': code})
        for code, reply in cases:
            with self.subTest(state=code):
                self.layer([first, second] + facts, lines=[line])
                for value in self.new_items(first, second, *facts):
                    (self.root / 'layer/items' / (value['id'] + '.json')).unlink()
                progress = self.progress()
                progress['consolidation'] = {'failures': 0}
                (self.root / 'curation.json').write_bytes(format2.curation_bytes(progress))
                bad = fixture.stream({'state': 'none'}) if code == 'bad-answer' else reply
                self.answering(last=bad)
                with self.quick():
                    outcome = self.consolidate()
                self.assertEqual(outcome.reason, 'failed')
                self.assertEqual(self.snapshot()['layer/state.json'], state_before)
                self.assertEqual((self.progress()['recent'][0]['error'], self.progress()['consolidation']),
                                 (code, {'failures': 1}))

    def test_tc192_three_failed_consolidations_in_a_row_stop_the_project(self):
        values = [self.item('decision', 'Keep raw logs on the device'),
                  self.item('decision', 'Raw logs stay here', saved=LATER)]
        self.layer(values)
        self.answering({'decision': [REFUSAL, LIMIT, failing(401, 'authentication_error')]})
        outcomes = [self.consolidate() for _ in range(3)]
        self.assertEqual([o.reason for o in outcomes], ['failed', 'failed', 'stopped'])
        progress = self.progress()
        self.assertEqual(progress['consolidation'], {'failures': 3})
        self.assertEqual(progress['stopped'], {'at': STAMP, 'by': 'consolidate',
                                               'errors': ['refusal', 'max-tokens', 'authentication_error']})
        self.assertEqual([o.attempts[0]['error'] for o in outcomes],
                         ['refusal', 'max-tokens', 'authentication_error'])
        self.assertEqual(self.items(), {value['id']: value for value in values})
        stored = self.snapshot()
        self.assertEqual(self.consolidate(), consolidation_worker.Outcome('stopped', (), 0, False))
        self.assertEqual((len(self.server.requests), self.snapshot()), (3, stored))

    def test_a_success_sets_the_failures_to_zero(self):
        values = [self.item('decision', 'Keep raw logs on the device'),
                  self.item('decision', 'Raw logs stay here', saved=LATER)]
        self.layer(values)
        self.answering({'decision': [REFUSAL, merges()]})
        self.assertEqual([self.consolidate().reason for _ in range(2)], ['failed', 'done'])
        self.assertEqual(self.progress()['consolidation'], {'failures': 0, 'last': STAMP})

    def test_tc193_a_forget_while_a_merge_request_waits_makes_it_stale(self):
        first = self.item('decision', 'Keep raw logs on the device')
        second = self.item('decision', 'Raw logs stay here', saved=LATER)
        third = self.item('decision', 'The raw logs never leave', saved='2026-11-06T08:30:00.000Z')
        self.layer([first, second, third])
        other = C2Store(self.folder, expected_device=DEVICE)
        self.server.before[0] = lambda: self.advance(other, third)
        self.answering({'decision': [merges(merge([first, third], [(first, 1), (third, 1)], title='Built before')),
                                     merges(merge([first, second], [(first, 1), (second, 1)], title='Built again'))]})
        outcome = self.consolidate()
        self.assertEqual((outcome.reason, [a['result'] for a in outcome.attempts]), ('done', ['stale', 'ok']))
        self.assertEqual(self.sent(), [('merge', 'decision', [first['id'], second['id'], third['id']]),
                                       ('merge', 'decision', [first['id'], second['id']])])
        (new,) = self.new_items(first, second)
        self.assertEqual(new['title'], 'Built again')
        self.assertNotIn(third['id'], self.items())
        self.assertEqual(self.progress()['recent'][1], {'at': STAMP, 'kind': 'consolidate', 'result': 'stale'})
        self.assertEqual(self.progress()['consolidation'], {'failures': 0, 'last': STAMP})

    def test_tc193_a_merge_request_that_fails_after_a_forget_is_not_tried_again(self):
        first = self.item('decision', 'Keep raw logs on the device')
        second = self.item('decision', 'Raw logs stay here', saved=LATER)
        third = self.item('decision', 'The raw logs never leave', saved='2026-11-06T08:30:00.000Z')
        self.layer([first, second, third])
        other = C2Store(self.folder, expected_device=DEVICE)
        self.server.before[0] = lambda: self.advance(other, third)
        self.answering({'decision': merges(merge([first, second], [(first, 1), (second, 1)], title='Built again'))})
        merging = self.server.reply
        self.server.reply = lambda number, body: failing(529, 'overloaded_error') if number == 0 else merging(number,
                                                                                                             body)
        with self.quick() as waits:
            outcome = self.consolidate()
        self.assertEqual((outcome.reason, [a['result'] for a in outcome.attempts]), ('done', ['stale', 'ok']))
        # The failed request is not tried again with the forgotten item: the next one is built again without it.
        self.assertEqual(self.sent(), [('merge', 'decision', [first['id'], second['id'], third['id']]),
                                       ('merge', 'decision', [first['id'], second['id']])])
        self.assertEqual((waits, outcome.requests), ([10], 2))
        (new,) = self.new_items(first, second)
        self.assertEqual(new['title'], 'Built again')
        self.assertEqual(self.progress()['consolidation'], {'failures': 0, 'last': STAMP})

    def test_tc193_a_forget_while_a_merge_request_is_counted_sends_nothing_built_before_it(self):
        first = self.item('decision', 'Keep raw logs on the device')
        second = self.item('decision', 'Raw logs stay here', saved=LATER)
        third = self.item('decision', 'The raw logs never leave', saved='2026-11-06T08:30:00.000Z')
        self.layer([first, second, third])
        other = C2Store(self.folder, expected_device=DEVICE)

        def counter(body):
            if not self.server.counts[1:]:
                self.advance(other, first)
                # Just over 99,000, so that the part loses only its newest item and would be counted again.
                return 99050
            return 1000
        self.server.counter = counter
        self.answering({'decision': merges(merge([second, third], [(second, 1), (third, 1)], title='Built again'))})
        with mock.patch.object(request_budget, 'UNCOUNTED', 0):
            outcome = self.consolidate()
        self.assertEqual((outcome.reason, [a['result'] for a in outcome.attempts]), ('done', ['stale', 'ok']))
        counted = [body['messages'][0]['content'] for body in self.server.counts]
        self.assertIn(first['id'], counted[0])
        self.assertTrue(len(counted) > 1 and not any(first['id'] in text for text in counted[1:]))
        self.assertEqual(self.sent(), [('merge', 'decision', [second['id'], third['id']])])
        (new,) = self.new_items(second, third)
        self.assertEqual(new['title'], 'Built again')

    def test_tc193_a_forget_after_a_merge_request_is_built_sends_nothing_of_it(self):
        first = self.item('decision', 'Keep raw logs on the device')
        second = self.item('decision', 'Raw logs stay here', saved=LATER)
        third = self.item('decision', 'The raw logs never leave', saved='2026-11-06T08:30:00.000Z')
        self.layer([first, second, third])
        other = C2Store(self.folder, expected_device=DEVICE)
        planned, forgot = request_budget.merge_part, []

        def plan(*args, **kwargs):
            part = planned(*args, **kwargs)
            if not forgot:
                forgot.append(third['id'])
                self.advance(other, third)
            return part
        self.answering({'decision': merges(merge([first, second], [(first, 1), (second, 1)], title='Built again'))})
        with mock.patch.object(request_budget, 'merge_part', side_effect=plan):
            outcome = self.consolidate()
        self.assertEqual((outcome.reason, [a['result'] for a in outcome.attempts]), ('done', ['stale', 'ok']))
        self.assertEqual((self.sent(), outcome.requests), ([('merge', 'decision', [first['id'], second['id']])], 1))
        (new,) = self.new_items(first, second)
        self.assertEqual(new['title'], 'Built again')

    def test_tc193_a_fence_moved_after_the_last_request_is_built_sends_nothing_of_it(self):
        value = self.item('decision', 'Keep raw logs on the device')
        line = row('decisions', 0, 'Raw logs stay here.', [value])
        self.layer([value], lines=[line])
        other = C2Store(self.folder, expected_device=DEVICE)
        built, moved = curator_document.shorten, []

        def shorten(**kwargs):
            source = built(**kwargs)
            if not moved:
                moved.append(True)
                self.advance(other)
            return source
        self.answering(last=shorter(decisions=[keeps(line, text='Raw logs stay on the device.')]))
        with mock.patch.object(curator_document, 'shorten', side_effect=shorten):
            outcome = self.consolidate()
        self.assertEqual((outcome.reason, [a['result'] for a in outcome.attempts]), ('done', ['stale', 'ok']))
        self.assertEqual(([kind for kind, _, _ in self.sent()], outcome.requests), (['state'], 1))
        self.assertEqual(self.state(), {line['id']: dict(line, text='Raw logs stay on the device.', at=STAMP)})

    def test_tc193_a_fence_moved_while_the_last_request_waits_makes_it_stale(self):
        value = self.item('decision', 'Keep raw logs on the device')
        line = row('decisions', 0, 'Raw logs stay here.', [value])
        self.layer([value], lines=[line])
        other = C2Store(self.folder, expected_device=DEVICE)
        self.server.before[0] = lambda: self.advance(other)
        self.answering(last=shorter(decisions=[keeps(line, text='Raw logs stay on the device.')]))
        outcome = self.consolidate()
        self.assertEqual((outcome.reason, [a['result'] for a in outcome.attempts]), ('done', ['stale', 'ok']))
        # The answer to the request built before the fence moved applied nothing; the one built again applied.
        self.assertEqual([kind for kind, _, _ in self.sent()], ['state', 'state'])
        self.assertEqual(self.state(), {line['id']: dict(line, text='Raw logs stay on the device.', at=STAMP)})
        self.assertEqual([(r['line'], r['op'], r['why']) for r in self.history()],
                         [(line['id'], 'changed', 'consolidation')])
        self.assertEqual(self.progress()['consolidation'], {'failures': 0, 'last': STAMP})

    def test_three_stale_requests_end_the_run_and_consolidation_stays_due(self):
        values = [self.item('decision', 'Keep raw logs on the device'),
                  self.item('decision', 'Raw logs stay here', saved=LATER)]
        self.layer(values)
        other = C2Store(self.folder, expected_device=DEVICE)
        for number in range(3):
            self.server.before[number] = lambda: self.advance(other)
        self.answering({'decision': merges(merge(values, [(values[0], 1), (values[1], 1)]))})
        outcome = self.consolidate()
        self.assertEqual((outcome.reason, [a['result'] for a in outcome.attempts]), ('stale', ['stale'] * 3))
        self.assertEqual((self.items(), self.progress()['consolidation']),
                         ({value['id']: value for value in values}, {'failures': 0}))

    def test_tc193_a_lost_lock_while_the_last_request_waits_applies_nothing_more(self):
        value = self.item('decision', 'Keep raw logs on the device')
        line = row('decisions', 0, 'Raw logs stay here.', [value])
        self.layer([value], lines=[line])
        before = self.snapshot()

        def take_over():
            # Another worker took the curation lock over: the lock file holds its token.
            record = json.loads((self.root / 'curation.lock').read_bytes())
            record['token'] = secrets.token_hex(16)
            (self.root / 'curation.lock').write_bytes(json.dumps(record).encode('utf-8'))
        self.server.before[0] = take_over
        self.answering(last=shorter(decisions=[keeps(line, text='Raw logs stay on the device.')]))
        outcome = self.consolidate()
        self.assertEqual((outcome.reason, outcome.attempts, outcome.applied), ('lost-lock', (), False))
        after = self.snapshot()
        after.pop('curation.lock', None)
        before.pop('curation.lock', None)
        self.assertEqual(after, before)
        # The usage line could not be appended without the lock either.
        self.assertIn(('consolidate', 'lost-lock'), self.failures())

    def test_a_history_append_that_fails_keeps_the_state_and_counts_a_failure(self):
        value = self.item('decision', 'Keep raw logs on the device')
        line = row('decisions', 0, 'Raw logs stay here.', [value])
        self.layer([value], lines=[line])
        before = self.snapshot()['layer/state.json']
        self.answering(last=shorter(decisions=[keeps(line, text='Raw logs stay on the device.')]))
        with mock.patch.object(history_io, 'append', side_effect=history_io.AppendFailed()):
            outcome = self.consolidate()
        self.assertEqual(outcome.reason, 'failed')
        self.assertEqual(self.snapshot()['layer/state.json'], before)
        progress = self.progress()
        self.assertEqual((progress['recent'][0]['error'], progress['consolidation']), ('RuntimeError', {'failures': 1}))
        self.assertIn(('consolidate', 'RuntimeError'), self.failures())


class MergeChecksTest(unittest.TestCase):
    """Pure parts of TASK-089 and TASK-090 that need no store."""

    def test_tc195_stage_06_merge_and_state_examples(self):
        api = ROOT / 'docs/06-api'
        examples = json.loads((api / 'memory-examples.json').read_text(encoding='utf-8'))
        self.assertEqual(curator_answers.MERGE_SCHEMA.read_bytes(), (api / examples['merge']['schema']).read_bytes())
        self.assertEqual(curator_answers.STATE_SCHEMA.read_bytes(), (api / examples['state']['schema']).read_bytes())
        quote = dict(entry='e_5h2j8n3p0r6t', log=LOG, device=DEVICE, start=0, end=5, speaker='user', said=AT,
                     words='Korea')

        def item(identifier, kind='preference'):
            return dict(id=identifier, kind=kind, title='Saved', text='A saved item.', quotes=[dict(quote)],
                        status='current', saved=AT, device=DEVICE)
        for name, value in sorted(examples['merge']['valid'].items()):
            with self.subTest(valid=name):
                named = sorted({i for merge_value in value['merges'] for i in merge_value['items']} |
                               {i for conflict in value['conflicts'] for i in conflict['items']})
                kind = 'decision' if name == 'possible-disagreement' else 'preference'
                checked = curator_answers.check_merge(value, items=[item(i, kind) for i in named], device=DEVICE)
                self.assertEqual((len(checked.merges), checked.dropped, len(checked.conflicts)),
                                 (len(value['merges']), {}, len(value['conflicts'])))
        for name, value in sorted(examples['merge']['invalid'].items()):
            with self.subTest(invalid=name), self.assertRaises(ValueError):
                curator_answers.check_merge(value, items=[item('i_5c8e1h4j7m0p')], device=DEVICE)
        schema = curator_answers.state_schema()
        for name, value in sorted(examples['state']['valid'].items()):
            with self.subTest(valid=name):
                self.assertEqual(curator_answers.decode(value, schema), value)
        for name, value in sorted(examples['state']['invalid'].items()):
            with self.subTest(invalid=name), self.assertRaises(ValueError):
                curator_answers.decode(value, schema)
        # Only the line text, cites and changes are shared with a curate add.
        curate = curator_answers.schema()['$defs']
        line = schema['$defs']['line']['properties']
        add = curate['add']['properties'] if 'add' in curate else None
        if add is not None:
            for name in ('text', 'cites', 'changes'):
                self.assertEqual(line[name], add[name])
            self.assertNotIn('keeps', add)
            self.assertNotIn('part', line)

    def test_a_merge_request_holds_current_items_of_one_kind(self):
        quote = dict(entry='e_5h2j8n3p0r6t', log=LOG, device=DEVICE, start=0, end=5, speaker='user', said=AT,
                     words='Korea')
        value = dict(id=ident('i'), kind='fact', title='Saved', text='A saved item.', quotes=[quote],
                     status='current', saved=AT, device=DEVICE)
        for items in ([value, dict(value, id=ident('i'), kind='lesson')], [value, value],
                      [value, dict(value, id=ident('i'), status='withdrawn')]):
            with self.subTest(items=[(i['kind'], i['status']) for i in items]), self.assertRaises(ValueError):
                curator_answers.check_merge(merges(), items=items, device=DEVICE)
        with self.assertRaises(ValueError):
            curator_answers.check_merge(merges(), items=[value], device='d_bad')

    def test_an_item_file_over_64_kb_drops_its_merge(self):
        words = 'w' * 2000
        quote = dict(entry='e_5h2j8n3p0r6t', log=LOG, device=DEVICE, start=0, end=2000, speaker='user', said=AT,
                     words=words)
        values = [dict(id=ident('i'), kind='fact', title='Saved', text='t' * 4000,
                       quotes=[dict(quote, entry=ident('e')) for _ in range(20)], status='current', saved=AT,
                       device=DEVICE) for _ in range(2)]
        picks = [(values[0], n) for n in range(1, 21)]
        fits = curator_answers.check_merge(merges(merge(values, picks, text='t' * 4000)), items=values,
                                           device=DEVICE)
        self.assertEqual((len(fits.merges), fits.dropped), (1, {}))
        # Each quote's 2,000 bytes take twice as many in the item file, where JSON escapes them.
        quoted = [dict(value, quotes=[dict(q, words='"' * 2000) for q in value['quotes']]) for value in values]
        large = curator_answers.check_merge(merges(merge(quoted, [(quoted[0], n) for n in range(1, 21)],
                                                         text='t' * 4000)), items=quoted, device=DEVICE)
        self.assertEqual((large.merges, large.dropped), ((), {'limit': 1}))

    def test_merged_by_follows_merges_but_never_a_replacement(self):
        def item(identifier, status='current', by=None, merged=()):
            value = {'id': identifier, 'kind': 'fact', 'status': status}
            if by:
                value['superseded_by'] = by
            if merged:
                value['merges'] = list(merged)
            return value
        a, b, c, d, e = (ident('i') for _ in range(5))
        items = {a: item(a, 'superseded', b), b: item(b, 'superseded', c, [a]), c: item(c, merged=[b]),
                 d: item(d, 'superseded', e), e: item(e)}
        self.assertEqual(state_rewrite.merged_by(items), {a: c, b: c})
        items[c] = item(c, 'withdrawn', merged=[b])
        self.assertEqual(state_rewrite.merged_by(items), {})


if __name__ == '__main__':
    unittest.main()
