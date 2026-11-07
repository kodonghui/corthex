"""TASK-085: checks of curate-2 answers, quotes and speakers, and copied quotes.

TC-161, TC-162, TC-175, TC-176, TC-178 to TC-181 and the TASK-085 parts of
TC-172, TC-177 and TC-182, on synthetic entries and items. No model is called.
"""
import builtins
import copy
from dataclasses import replace as dataclass_replace
import json
from pathlib import Path
import secrets
import sys
import unicodedata
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT/'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import base, curator_answers, item_types, raw_log
import test_memory_item_io as item_io_fixture

API = ROOT/'docs/06-api'
AT = '2026-11-04T03:00:00.000Z'
LATER = '2026-11-05T08:30:00.000Z'
DEVICE = 'd_0123456789ab'
OTHER = 'd_zyxwvtsrqpnm'
HOST, SESSION = 'claude-code', 'fixture-session-085'
LOG = raw_log.log_name(HOST, SESSION)
EMPTY = {'change': [], 'add': [], 'remove': []}
REPLACEMENT = chr(0xFFFD)


def ident(prefix):
    return prefix + '_' + ''.join(secrets.choice(base.CROCKFORD) for _ in range(12))


class Turns:
    """Stored TBL-007 entries of one raw log, numbered as the recorder numbers them."""

    def __init__(self):
        self.entries, self.seq = [], 1

    def say(self, speaker, text, entry=None, at=AT, **extra):
        self.seq += 1
        turn = self.seq if speaker == 'user' else max(e['turn'] for e in self.entries) if self.entries else self.seq
        value = dict(id=entry or ident('e'), seq=self.seq, at=at, host=HOST, session=SESSION,
                     kind='prompt' if speaker == 'user' else 'answer', turn=turn, speaker=speaker, text=text)
        value.update(extra)
        raw_log._parsed_entry(value, HOST, SESSION)
        self.entries.append(value)
        return value


def saved(kind, source, words=None, status='current', item=None, device=DEVICE, log=LOG):
    words = source['text'] if words is None else words
    start = source['text'].index(words)
    quote = dict(entry=source['id'], log=log, device=device, start=start, end=start + len(words),
                 speaker=source['speaker'], said=source['at'], words=words)
    return dict(id=item or ident('i'), kind=kind, title='Saved ' + kind, text='A saved ' + kind + '.',
                quotes=[quote], status=status, saved=AT, device=device)


def quote(source, words):
    return {'entry': source['id'], 'words': words}


def change(*quotes, action='add', targets=(), kind='fact', title='A title', text='A text.', conflicts=()):
    return dict(action=action, targets=list(targets), kind=kind, quotes=list(quotes), title=title, text=text,
                conflicts=list(conflicts))


def answer(*changes, state=None):
    return {'changes': list(changes), 'state': copy.deepcopy(EMPTY if state is None else state)}


class CuratorAnswersTest(unittest.TestCase):
    def store(self):
        """A fabricated format-2 store with the item writer of TASK-076; it holds no raw log."""
        fixture = item_io_fixture.ItemIOTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.assertFalse((fixture.project/'raw').exists())
        return fixture

    def saved_by_writer(self, records):
        store = self.store()
        with store.held(curator=True):
            store.apply(records, run_id='r_0123456789ab')
        return [item_types.parse_item(store.item_path(v['id']).read_bytes()) for v in records]

    def check(self, value, turns, items=()):
        sent = curator_answers.sent(items=items, logs=[(LOG, turns.entries)])
        return curator_answers.check_curate(value, sent=sent, device=DEVICE)

    def test_tc161_a_quote_one_word_off_is_dropped_and_counted(self):
        turns = Turns()
        said = turns.say('user', 'We will ship the plugin on Friday after the checks pass.')
        result = self.check(answer(change(quote(said, 'We will ship the plugin on Monday after the checks pass.')),
                                   change(quote(said, 'We will ship the plugin on Friday'))), turns)
        self.assertEqual(result.dropped, {'quote': 1})
        self.assertEqual([c.number for c in result.changes], [2])
        kept = result.changes[0].quotes[0]
        self.assertEqual((kept['start'], kept['end'], kept['words']), (0, 33, 'We will ship the plugin on Friday'))

    def test_tc162_a_decision_quoted_from_the_agent_is_the_agents(self):
        turns = Turns()
        turns.say('user', 'How should the hooks be laid out?')
        proposal = turns.say('agent', 'I will keep the four hooks in one script.', at=LATER)
        result = self.check(answer(change(quote(proposal, 'keep the four hooks in one script'), kind='decision')),
                            turns)
        (decision,) = result.changes
        self.assertEqual((decision.kind, decision.speaker, result.dropped), ('decision', 'agent', {}))
        self.assertEqual(decision.quotes[0], dict(entry=proposal['id'], log=LOG, device=DEVICE, start=7, end=40,
                                                  speaker='agent', said=LATER,
                                                  words='keep the four hooks in one script'))
        record = curator_answers.item_record(decision, item=ident('i'), at=LATER, device=DEVICE)
        (stored,) = self.saved_by_writer([record])
        self.assertEqual((stored['kind'], stored['status'], stored['quotes'], stored['device']),
                         ('decision', 'current', list(decision.quotes), DEVICE))

    def test_tc172_capitals_missing_fields_and_a_target_outside_the_request(self):
        turns = Turns()
        said = turns.say('user', 'Keep the raw logs on this device.')
        older = saved('decision', said)
        good = change(quote(said, 'Keep the raw logs on this device.'), action='ADD', kind='DECISION')
        outside = change(quote(said, 'Keep the raw logs'), action='replace', targets=[ident('i')])
        result = self.check(answer(good, outside, change(quote(said, 'raw logs'))), turns, [older])
        self.assertEqual([(c.number, c.action, c.kind) for c in result.changes],
                         [(1, 'add', 'decision'), (3, 'add', 'fact')])
        self.assertEqual(result.dropped, {'not-in-request': 1})
        for broken in ({'changes': []}, answer(dict(good, conflicts=None)),
                       answer({k: v for k, v in good.items() if k != 'conflicts'}),
                       answer(dict(good, reason='x')), answer(dict(good, action='delete')), ['changes']):
            with self.subTest(broken=broken), self.assertRaises(ValueError):
                self.check(broken, turns, [older])

    def test_tc175_a_merged_item_keeps_a_quote_whose_entry_is_gone(self):
        turns = Turns()
        first = saved('preference', turns.say('user', 'Answer me in Korean.'))
        second = saved('preference', turns.say('user', 'Korean answers, please.'), log=raw_log.log_name(HOST, 'gone'))
        picks = [{'item': second['id'], 'number': 1}, {'item': first['id'], 'number': 1}]
        # Retention deleted both raw logs: nothing may be read while the quotes are copied.
        with mock.patch.object(Path, 'read_bytes', side_effect=AssertionError('read')), \
                mock.patch.object(builtins, 'open', side_effect=AssertionError('open')):
            copied = curator_answers.copied_quotes([first, second], picks)
        self.assertEqual(copied, [second['quotes'][0], first['quotes'][0]])
        store = self.store()
        merged = dict(id=ident('i'), kind='preference', title='Answers in Korean', text='The user wants Korean.',
                      quotes=copied, status='current', merges=[first['id'], second['id']], saved=LATER, device=DEVICE)
        with store.held(curator=True):
            store.apply([first, second], run_id='r_0123456789ab')
            store.apply([merged], [{'id': first['id'], 'status': 'superseded', 'superseded_by': merged['id']},
                                   {'id': second['id'], 'status': 'superseded', 'superseded_by': merged['id']}],
                        run_id='r_0123456789ac')
        stored = item_types.parse_item(store.item_path(merged['id']).read_bytes())
        self.assertEqual(stored['quotes'], [second['quotes'][0], first['quotes'][0]])
        copied[0]['words'] = 'changed'
        self.assertEqual(second['quotes'][0]['words'], 'Korean answers, please.')
        for picks in ([], [{'item': first['id'], 'number': 2}], [{'item': first['id'], 'number': 0}],
                      [{'item': first['id'], 'number': True}], [{'item': ident('i'), 'number': 1}],
                      [{'item': first['id'], 'number': 1, 'words': 'x'}], [{'item': first['id'], 'number': 1}] * 21):
            with self.subTest(picks=picks), self.assertRaises(ValueError):
                curator_answers.copied_quotes([first, second], picks)

    def test_tc176_an_item_from_another_device_is_kept_as_it_came(self):
        turns = Turns()
        foreign = saved('lesson', turns.say('user', 'Tables in Notion are databases.'), device=OTHER,
                        log=raw_log.log_name('codex', 'another-device'))
        # This device holds none of the item's entries: the store has no raw log at all.
        (stored,) = self.saved_by_writer([foreign])
        self.assertEqual(stored, foreign)
        with mock.patch.object(Path, 'read_bytes', side_effect=AssertionError('read')):
            copied = curator_answers.copied_quotes([foreign], [{'item': foreign['id'], 'number': 1}])
        self.assertEqual(copied, foreign['quotes'])
        self.assertEqual((copied[0]['device'], copied[0]['log']), (OTHER, foreign['quotes'][0]['log']))

    def test_tc177_stage_06_curate_examples(self):
        examples = json.loads((API/'memory-examples.json').read_text(encoding='utf-8'))['curate']
        self.assertEqual(curator_answers.SCHEMA.read_bytes(), (API/examples['schema']).read_bytes())
        turns = Turns()
        turns.say('user', "Let's keep the four hooks in one script.", entry='e_5h2j8n3p0r6t')
        turns.say('agent', 'Done: one script now serves the four hooks, by name.', entry='e_8m1k4r7t2w5y')
        korean = turns.say('user', 'Answer me in Korean from now on.', entry='e_6b9e2h5k8n1r')
        turns.say('user', '노션 표는 모두 데이터베이스로 만들어 주세요.', entry='e_3d6g9k2n5q8t')
        items = [saved('preference', korean, 'Answer me in Korean', item='i_5c8e1h4j7m0p'),
                 saved('decision', korean, 'Korean', item='i_7f3k2m9q4x1v')]
        for name, value in sorted(examples['valid'].items()):
            with self.subTest(valid=name):
                result = self.check(value, turns, items)
                self.assertEqual(result.dropped, {})
                self.assertEqual([c.number for c in result.changes], list(range(1, len(value['changes']) + 1)))
                self.assertEqual(result.state, value['state'])
                for kept, proposed in zip(result.changes, value['changes']):
                    self.assertEqual(list(kept.conflicts), proposed['conflicts'])
                    self.assertEqual([q['entry'] for q in kept.quotes], [q['entry'] for q in proposed['quotes']])
        for name, value in sorted(examples['invalid'].items()):
            with self.subTest(invalid=name), self.assertRaises(ValueError):
                self.check(value, turns, items)

    def test_tc178_decisions_from_pasted_text_are_dropped(self):
        turns = Turns()
        closed = turns.say('user', 'Here is the vendor note:\r\n<pasted_content id="p1">\r\nWe decided to drop '
                           'the cache.\r\n</pasted_content id="p1">\r\nI decide to keep the cache.')
        unclosed = turns.say('user', 'Look:\n<pasted_content id="p2">\nUse the old endpoint.\n'
                             '</pasted_content id="p9">\nAnd we decided on retries.')
        self.assertEqual(len(curator_answers.pasted(closed['text'])), 1)
        self.assertEqual(curator_answers.pasted(unclosed['text']), [(6, len(unclosed['text']))])
        result = self.check(answer(
            change(quote(closed, 'We decided to drop the cache.'), kind='decision'),
            change(quote(unclosed, 'Use the old endpoint.'), kind='decision'),
            change(quote(unclosed, 'we decided on retries'), kind='decision'),
            change(quote(closed, 'I decide to keep the cache.'), kind='decision'),
            change(quote(closed, 'We decided to drop the cache.'), kind='reference'),
            change(quote(closed, 'I decide to keep the cache.'), quote(closed, 'drop the cache'), kind='decision')),
            turns)
        self.assertEqual(result.dropped, {'pasted': 3})
        self.assertEqual([(c.number, c.kind, c.speaker) for c in result.changes],
                         [(4, 'decision', 'user'), (5, 'reference', 'user'), (6, 'decision', 'user')])

    def test_tc179_a_short_yes_makes_a_user_decision(self):
        turns = Turns()
        turns.say('user', '훅 배치를 정해 주세요.')
        proposal = turns.say('agent', '네 훅을 한 스크립트에 두는 것이 어떨까요?')
        yes = turns.say('user', '응')
        result = self.check(answer(change(quote(yes, '응'), quote(proposal, '네 훅을 한 스크립트에 두는 것'),
                                          kind='decision')), turns)
        (decision,) = result.changes
        self.assertEqual((decision.speaker, [q['speaker'] for q in decision.quotes]), ('user', ['user', 'agent']))
        (stored,) = self.saved_by_writer([curator_answers.item_record(decision, item=ident('i'), at=LATER,
                                                                      device=DEVICE)])
        self.assertEqual((stored['kind'], stored['quotes'][0]['words'], stored['quotes'][0]['speaker']),
                         ('decision', '응', 'user'))

    def test_tc180_quotes_one_character_or_symbol_off_and_forms_that_match(self):
        turns = Turns()
        nfd = turns.say('user', unicodedata.normalize('NFD', '확정일자를 받았습니다. 다음은 전입신고!'))
        lines = turns.say('user', 'First line.\r\nSecond   line,\t\tthird.')
        result = self.check(answer(
            change(quote(nfd, '확정일자를 받았습니다. 다음은 전입신고?')),
            change(quote(nfd, '확정일자를 받았음니다')),
            change(quote(lines, 'First line. ')),
            change(quote(lines, 'First line;')),
            change(quote(nfd, '확정일자를 받았습니다. 다음은 전입신고!')),
            change(quote(lines, 'First line.\nSecond line, third.')),
            change(quote(lines, ' Second line,  third. '))), turns)
        self.assertEqual(result.dropped, {'quote': 3})
        self.assertEqual([c.number for c in result.changes], [3, 5, 6, 7])
        spans = [(c.quotes[0]['start'], c.quotes[0]['end'], c.quotes[0]['words']) for c in result.changes]
        self.assertEqual(spans[0], (0, 11, 'First line.'))
        self.assertEqual(spans[1][:2], (0, len(nfd['text'])))
        self.assertEqual(unicodedata.normalize('NFC', spans[1][2]), '확정일자를 받았습니다. 다음은 전입신고!')
        self.assertEqual(spans[2], (0, len(lines['text']), lines['text']))
        self.assertEqual(spans[3], (13, len(lines['text']), lines['text'][13:]))

    def test_tc181_quotes_of_forgotten_text_are_dropped(self):
        turns = Turns()
        said = turns.say('user', 'keep ' + REPLACEMENT * 4 + ' here and there', forgotten=[[5, 9]])
        result = self.check(answer(change(quote(said, 'keep [forgotten] here')),
                                   change(quote(said, REPLACEMENT * 2)),
                                   change(quote(said, 'keep ' + REPLACEMENT)),
                                   change(quote(said, 'here and there'))), turns)
        self.assertEqual(result.dropped, {'quote': 3})
        (kept,) = result.changes
        self.assertEqual(kept.quotes[0]['words'], 'here and there')
        for value in result.changes:
            self.assertFalse(any(REPLACEMENT in q['words'] or '[forgotten]' in q['words'] for q in value.quotes))

    def test_tc182_item_limits_drop_past_a_limit_and_keep_at_it(self):
        turns = Turns()
        said = turns.say('user', 'a' * 2100 + ' ' + '가' * 700)
        at_limit = [change(quote(said, 'a' * 10), title='t' * 200), change(quote(said, 'a' * 10), text='x' * 4000),
                    change(*[quote(said, 'a' * n) for n in range(1, 21)]), change(quote(said, 'a' * 2000)),
                    change(quote(said, '가' * 666))]
        past = [change(quote(said, 'a' * 10), title='t' * 201), change(quote(said, 'a' * 10), title='two\nlines'),
                change(quote(said, 'a' * 10), title='가' * 67), change(quote(said, 'a' * 10), text='x' * 4001),
                change(*[quote(said, 'a' * n) for n in range(1, 22)]), change(quote(said, 'a' * 2001)),
                change(quote(said, '가' * 667))]
        # Each quoted '"' takes two bytes in the item file: 20 such quotes of 1,405 fill it to 65,526 bytes.
        marks = turns.say('user', '"' * 2000 + ' end')
        at_limit.append(change(*[quote(marks, '"' * 1405)] * 20, title='t' * 200, text='x' * 4000))
        past.append(change(*[quote(marks, '"' * 1406)] * 20, title='t' * 200, text='x' * 4000))
        result = self.check(answer(*(at_limit + past)), turns)
        self.assertEqual(result.dropped, {'limit': len(past)})
        self.assertEqual([c.number for c in result.changes], list(range(1, len(at_limit) + 1)))
        self.assertEqual(len(result.changes[2].quotes), 20)
        records = [curator_answers.item_record(c, item=ident('i'), at=LATER, device=DEVICE) for c in result.changes]
        self.assertEqual(self.saved_by_writer(records), records)
        self.assertEqual(len(item_types.item_bytes(records[-1])), 65526)

    def test_speaker_rules_keep_the_users_items(self):
        turns = Turns()
        user = turns.say('user', 'Use tabs in the generated files.')
        agent = turns.say('agent', 'The generated files use spaces; tabs no longer hold.')
        correction = turns.say('user', 'No, the agent is wrong: the files use tabs.')
        users = [saved('decision', user, 'Use tabs') for _ in range(3)]
        agents = [saved('fact', agent, 'The generated files use spaces') for _ in range(2)]
        result = self.check(answer(
            change(quote(correction, 'the files use tabs'), action='replace', targets=[agents[0]['id']]),
            change(quote(agent, 'tabs no longer hold'), action='withdraw', targets=[users[0]['id']], kind='decision'),
            change(quote(agent, 'use spaces'), action='replace', targets=[users[1]['id'], agents[1]['id']]),
            change(quote(agent, 'The generated files use spaces'), action='withdraw', targets=[agents[1]['id']]),
            change(quote(correction, 'use tabs'), action='replace', targets=[users[2]['id']], kind='decision'),
            change(quote(user, 'Use tabs'), action='withdraw', targets=[agents[0]['id']])),
            turns, users + agents)
        self.assertEqual([(c.number, c.action, c.targets, c.kept) for c in result.changes], [
            (1, 'replace', (agents[0]['id'],), ()),
            (2, 'add', (), (users[0]['id'],)),
            (3, 'add', (), (users[1]['id'], agents[1]['id'])),
            (4, 'withdraw', (agents[1]['id'],), ()),
            (5, 'replace', (users[2]['id'],), ())])
        # The first change superseded agents[0], so the last one names an item no longer current.
        self.assertEqual(result.dropped, {'not-current': 1})

    def test_targets_order_and_conflicts(self):
        turns = Turns()
        said = turns.say('user', 'Keep one script for the hooks and two workers.')
        first, second, third = (saved('fact', said, 'Keep one script') for _ in range(3))
        old = saved('fact', said, 'two workers', status='superseded')
        old['superseded_by'] = first['id']
        other = Turns()
        elsewhere = other.say('user', 'Not in this request.')
        words = quote(said, 'one script')
        result = self.check(answer(
            change(words, action='replace', targets=[first['id']]),
            change(words, action='withdraw', targets=[first['id']]),
            change(words, conflicts=[first['id'], second['id'], ident('i'), second['id'], third['id']],
                   action='replace', targets=[third['id']]),
            change(words, targets=[second['id']]),
            change(words, action='replace'),
            change(words, action='withdraw', targets=[second['id'], third['id']]),
            change(words, action='replace', targets=[second['id'], second['id']]),
            change(words, action='replace', targets=[old['id']]),
            change(quote(elsewhere, 'Not in this request.')),
            change(words, conflicts=[second['id']])), turns, [first, second, third, old])
        self.assertEqual(result.dropped, {'not-current': 2, 'shape': 4, 'not-in-request': 1})
        self.assertEqual([(c.number, c.conflicts) for c in result.changes],
                         [(1, ()), (3, (second['id'],)), (10, (second['id'],))])

    def test_item_records_come_from_checked_adds_and_replacements(self):
        turns = Turns()
        said = turns.say('agent', 'The cache stays off.')
        target = saved('fact', said)
        result = self.check(answer(change(quote(said, 'The cache stays off.'), action='withdraw',
                                          targets=[target['id']])), turns, [target])
        (withdrawal,) = result.changes
        with self.assertRaises(ValueError):
            curator_answers.item_record(withdrawal, item=ident('i'), at=LATER, device=DEVICE)
        large = curator_answers.Change(1, 'add', (), (), 'fact', 'Large', 'x' * 4000,
                                       tuple(dict(withdrawal.quotes[0], words='"' * 20, end=20) for _ in range(20)), ())
        record = curator_answers.item_record(large, item=ident('i'), at=LATER, device=DEVICE)
        self.assertEqual(record['status'], 'current')
        with self.assertRaises(ValueError):
            curator_answers.item_record(dataclass_replace(large, text='"' * 2000, quotes=tuple(
                dict(q, words='"' * 1700, end=1700) for q in large.quotes)), item=ident('i'), at=LATER, device=DEVICE)

    def test_request_entries_are_turns_and_items_are_saved_records(self):
        turns = Turns()
        said = turns.say('user', 'One request.')
        start = dict(id=ident('e'), seq=1, at=AT, host=HOST, session=SESSION, kind='start')
        item = saved('fact', said)
        for logs, items in (([(LOG, [start])], []), ([(LOG, [said, said])], []), ([(LOG, [said])], [item, item]),
                            ([(LOG, [said])], [dict(item, status='gone')])):
            with self.subTest(logs=logs, items=len(items)), self.assertRaises(ValueError):
                curator_answers.sent(items=items, logs=logs)
        with self.assertRaises(ValueError):
            curator_answers.check_curate(answer(), sent=curator_answers.sent(items=[], logs=[]), device='d_bad')


if __name__ == '__main__':
    unittest.main()
