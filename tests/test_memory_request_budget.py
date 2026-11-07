"""TASK-084: the sizes of curate requests (API-009; SPEC-015, SPEC-143).

TC-157, TC-154 and TC-353, and the TASK-084 parts of TC-152, TC-153, TC-155
and TC-387, on synthetic records. Counts come from a local test server with a
key made up for the run, or from a counting function with the server's fixed
rule; no real API is called.
"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import random
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

from _common import ROOT
import test_memory_model_transport as transport_fixture
import test_memory_model_usage as usage_fixture
from test_memory_curator_document import AT, DEVICE, HOST, LATER, LOG, candidate, entry, item, line
sys.path.insert(0, str(ROOT/'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import (curator_answers, curator_document, index_io, item_types, model_access, model_count,
                        model_prompts, model_request, raw_log, request_budget, request_inputs, state_types)

SCHEMA = curator_answers.schema()
FIXED = model_prompts.PROMPTS['curate-2'] + json.dumps(SCHEMA, ensure_ascii=False)
BASE = request_budget.fixed('curate-2', SCHEMA)
KEY = transport_fixture.KEY
CREDENTIALS = model_access.Credentials.read({'CORTHEX_MEMORY_ANTHROPIC_API_KEY': KEY})
OTHER = raw_log.log_name(HOST, 'fixture-session-084')
WORDS = ('river', 'stone', 'lantern', 'harbor', 'meadow', 'signal', 'copper', 'window', 'garden', 'thread',
         'anchor', 'valley', 'ember', 'quiet', 'orbit', 'canvas')
# Words of turns that no item holds, so that only the items a turn names rank.
TALK = ('please', 'check', 'again', 'after', 'lunch', 'thanks', 'later', 'today')
# One user-perceived character each: syllables, emoji with a modifier or joiners, a flag, a heart and a
# keycap with variation selectors, a combining mark, conjoining jamo, a tag sequence and the forgotten marker.
CLUSTERS = ('가', '나', '한', '글', 'a', ' ', '\U0001F44D\U0001F3FD',
            '\U0001F468‍\U0001F469‍\U0001F467‍\U0001F466', '\U0001F1F0\U0001F1F7', '❤️',
            'é', '각', '1️⃣',
            '\U0001F3F4\U000E0067\U000E0062\U000E0065\U000E006E\U000E0067\U000E007F', '[forgotten]')


def rule(text):
    """The test server's fixed count: ASCII characters / 3 and 1.5 per other character, rounded up."""
    plain = sum(map(str.isascii, text))
    return -(-plain // 3) + -(-3 * (len(text) - plain) // 2)


def sent(source):
    """The body that a request document is counted and sent with."""
    return model_request.build(config={}, instructions='curate-2', source=source, schema=SCHEMA,
                               credentials=CREDENTIALS, environment={})[0]['body']


def body_rule(body):
    return rule(body['system'] + body['messages'][0]['content'] +
                json.dumps(body['output_config']['format']['schema'], ensure_ascii=False))


class Counter:
    """A counting function with the server's rule, after any answers given first (None: counting fails)."""

    def __init__(self, *answers):
        self.answers, self.calls, self.turns = list(answers), [], []

    def __call__(self, source):
        value = self.answers.pop(0) if self.answers else rule(FIXED + source)
        self.calls.append(value)
        self.turns.append(source.count('<turn '))
        return value


def prose(size, seed, words=WORDS, paragraph=600):
    """ASCII text of `size` characters: whole words in paragraphs of about `paragraph` characters,
    padded with spaces at the end."""
    rng = random.Random(seed)
    out, length, since = [], 0, 0
    while True:
        word = rng.choice(words)
        if not out:
            piece = word
        elif since >= paragraph:
            piece, since = '\n\n' + word, 0
        else:
            piece = ' ' + word
        if length + len(piece) > size:
            return ''.join(out) + ' ' * (size - length)
        out.append(piece)
        length += len(piece)
        since += len(piece)


def day(n):
    return (datetime(2025, 1, 1, 3, tzinfo=timezone.utc) + timedelta(days=n)).strftime('%Y-%m-%dT%H:%M:%S.000Z')


def minute(n):
    return (datetime(2026, 11, 5, 8, tzinfo=timezone.utc) + timedelta(minutes=n)).strftime('%Y-%m-%dT%H:%M:%S.000Z')


SOURCE = entry(2, 'prompt', 'Keep the raw logs on this device.')


def items_of(count, size=180, seed=0):
    """Current items with titles of `size` characters, item n saying `markNNNN` and said on day n."""
    found = []
    for n in range(count):
        head = 'Item %04d mark%04d ' % (n, n)
        found.append(item(head + prose(size - len(head), seed * 100000 + n, paragraph=10 ** 9), SOURCE,
                          said=day(n)))
    return found


def session(turns, log=LOG):
    """A raw log's unprocessed turns, [(prompt, answer)]; an answer None leaves the prompt alone."""
    entries, seq = [entry(1, 'start', event='start')], 1
    for prompt, answer in turns:
        seq += 1
        first = seq
        entries.append(entry(first, 'prompt', prompt, turn=first))
        if answer is not None:
            seq += 1
            entries.append(entry(seq, 'answer', answer, turn=first))
    return curator_document.session(log, entries)


def keys(sessions):
    return [(value['log'], turn['seq']) for value in sessions for turn in value['turns']]


def left(sessions, done):
    """The sessions without the turns that a request carried."""
    return [dict(value, turns=[turn for turn in value['turns'] if (value['log'], turn['seq']) not in done])
            for value in sessions]


def rotation(candidates, after, places):
    """Open candidates in time and ID order, starting after the place of `after` (SPEC-143)."""
    order = sorted(candidates, key=lambda c: (c['at'], c['id']))
    if after is None:
        return order
    start = next((index for index, c in enumerate(order) if (c['at'], c['id']) > places[after]), len(order))
    return order[start:] + order[:start]


class RequestBudgetTest(unittest.TestCase):
    def layer(self, items=(), lines=(), pinned=(), candidates=()):
        """The layer that request_inputs reads after these records are written to a project folder."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)/'sample'
        for name in ('layer/items', 'layer/tombstones'):
            (root/name).mkdir(parents=True)
        for value in items:
            (root/'layer/items'/(value['id'] + '.json')).write_bytes(item_types.item_bytes(value))
        (root/'layer/state.json').write_bytes(state_types.state_bytes({'lines': list(lines)}))
        (root/'layer/state-removed.json').write_bytes(state_types.removed_bytes({'removed': []}))
        (root/'layer/pins.json').write_bytes(item_types.pins_bytes(
            {'pins': [dict(item=pin, on=True, at=AT, device=DEVICE) for pin in pinned]}))
        (root/'layer/conflicts.json').write_bytes((json.dumps({'candidates': list(candidates)}) + '\n').encode())
        return request_inputs.layer(root)

    def index(self, items):
        """A search index of the items, ranking by words as the hooks' index does."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        connection = index_io.connect(Path(temporary.name)/'index.db', create=True)
        self.addCleanup(connection.close)
        connection.executescript(index_io.DDL.read_text(encoding='utf-8'))
        index_io.put(connection, items)
        return connection

    def listed(self, layer, listed, sessions=()):
        return curator_document.curate(lines=list(layer.lines), items=list(listed.items), form=listed.form,
                                       sessions=list(sessions), candidates=list(listed.candidates),
                                       omitted=listed.omitted)

    def assert_whole(self, request, sessions):
        """The request carries its turns whole, in order, under 100,000 tokens by the rule."""
        root = ET.fromstring(request.source)
        texts = {value['id']: value['text'] for s in sessions for turn in s['turns'] for value in turn['entries']}
        shown = [(node.get('id'), node.text or '') for node in root.iter('entry')]
        self.assertEqual(shown, [(key, texts[key]) for key, _ in shown])
        self.assertTrue(all(node.get('part') is None for node in root.iter('turn')))
        self.assertLess(body_rule(sent(request.source)), 100000)

    # Estimates and the request document

    def test_estimates_count_ascii_bytes_and_other_characters(self):
        cases = [('', 0, 0), ('a', 1, 1), ('abcd', 2, 1), ('abcde', 3, 2), ('가', 2, 1), ('가a', 3, 2),
                 ('\U0001F44D\U0001F3FD', 4, 2), ('é', 3, 2), ('\ud800', 2, 1), ('<&>"', 2, 1)]
        for text, safe, working in cases:
            with self.subTest(text=text):
                self.assertEqual((request_budget.safe(text), request_budget.working(text)), (safe, working))
        self.assertEqual(request_budget._safe(BASE), request_budget.safe(FIXED))

    def test_composed_counts_match_the_built_documents(self):
        prompt = entry(2, 'prompt', 'Keep <raw> & "local" logs')
        first, second = item('Raw <logs> & "local"', prompt), item('Shared & folder', prompt, kind='preference')
        lines = [line('State & <line> "one"', [first['id']]), line('Next', [second['id']], 'next', 1)]
        known = candidate(first, second)
        full = session([('Keep <raw> & "local" logs', 'Agreed: <keep> & go'), ('Second & third', None)])
        started = curator_document.session(OTHER, [entry(1, 'start', event='start')])
        ended = curator_document.session(OTHER, [entry(1, 'start', event='start'), entry(2, 'prompt', 'Ends', turn=2),
                                                 entry(3, 'end', event='end')])
        for form in curator_document.FORMS:
            _, items_text = curator_document._items([first, second], form)
            conflicts_text = curator_document._conflicts([known], 2, {first['id'], second['id']})
            frame = request_budget._Frame(BASE, lines, request_budget._pair(items_text),
                                          request_budget._pair(conflicts_text))
            for sessions in ([], [started], [full], [full, started, ended]):
                with self.subTest(form=form, sessions=len(sessions)):
                    turns = request_budget._turns_pair([
                        (value, [request_budget._pair(curator_document._turn(turn, set())) for turn in value['turns']])
                        for value in sessions])
                    built = curator_document.curate(lines=lines, items=[first, second], form=form, sessions=sessions,
                                                    candidates=[known], omitted=2)
                    self.assertEqual(frame.pair(turns), request_budget._add(BASE, request_budget._pair(built)))
            listed = request_budget.ItemList(form, (first, second), (known,), 2, None, form != 'full')
            turn = full['turns'][0]
            pieces = [(0, 'Keep <raw>'), (0, ' & "local" logs'), (1, 'Agreed: <keep> & go')]
            built = request_budget._part_source(types.SimpleNamespace(lines=lines), listed, full, turn, pieces, 3, 7)
            self.assertEqual(request_budget._Part(frame, full, turn, 7).pair(3, pieces),
                             request_budget._add(BASE, request_budget._pair(built)))
            self.assertEqual([node.text for node in ET.fromstring(built).iter('entry')],
                             ['Keep <raw> & "local" logs', 'Agreed: <keep> & go'])

    def test_cuts_never_split_a_character_a_line_end_or_the_forgotten_marker(self):
        inside = [('é', 1), ('a‍b', 1), ('a‍b', 2), ('❤️', 1), ('1️⃣', 2),
                  ('\U0001F44D\U0001F3FD', 1), ('\U0001F3F4\U000E0067\U000E007F', 1),
                  ('\U0001F3F4\U000E0067\U000E007F', 2), ('가', 1), ('각', 2),
                  ('ᄀힰ', 1), ('a\r\nb', 2), ('\U0001F1F0\U0001F1F7', 1),
                  ('\U0001F1F0\U0001F1F7\U0001F1F0\U0001F1F7', 3), ('x[forgotten]y', 2), ('x[forgotten]y', 11),
                  # Conjuncts: a virama joins the next letter, also past a mark or a joiner; Khmer's coeng too.
                  ('क्ष', 1), ('क्ष', 2), ('क्\u0951ष', 3), ('क्\u200dष', 3), ('ក្ក', 2), ('a\u200cb', 1),
                  # A leading jamo joins a leading jamo or a syllable; a prepended sign joins what follows it;
                  # Thai and Lao AM, the halfwidth sound marks and the Kirat Rai vowel signs join like marks.
                  ('ᄀ가', 1), ('ᄀᄀ', 1), ('ꥠ각', 1), ('\u0600\u0661', 1), ('\u0600 ', 1), ('\U000110BDa', 1),
                  ('ก\u0e33', 1), ('ກ\u0eb3', 1), ('ｶ\uff9e', 1), ('\U00016D43\U00016D63', 1)]
        for text, index in inside:
            with self.subTest(text=text, index=index):
                self.assertFalse(request_budget._boundary(text, index))
        between = [('ab', 0), ('ab', 1), ('ab', 2), ('a\nb', 2), ('a\r\nb', 1), ('a\r\nb', 3), ('가나', 1),
                   ('\U0001F1F0\U0001F1F7\U0001F1F0\U0001F1F7', 2), ('x[forgotten]y', 1), ('x[forgotten]y', 12),
                   ('क्षक्ष', 3), ('कष', 1), ('क्\u200cष', 3), ('क्' + '\u0951' * 30 + 'ष', 32),
                   ('가ᄀ', 1), ('ᄀa', 1), ('a\u0600', 1), ('\u0e33ก', 1)]
        for text, index in between:
            with self.subTest(text=text, index=index):
                self.assertTrue(request_budget._boundary(text, index))
        self.assertEqual(request_budget._cut('ab\U0001F44D\U0001F3FDcd', lambda prefix: len(prefix) <= 3), 2)
        self.assertEqual(request_budget._cut('abc', lambda prefix: not prefix), 0)
        text = 'aa\n\nbb\ncc\n\ndd'
        for limit, size in ((12, 11), (9, 4), (3, 3), (1, 1)):
            with self.subTest(limit=limit):
                self.assertEqual(request_budget._shorter(text, lambda prefix: len(prefix) <= limit), size)

    def test_pieces_cut_at_paragraphs_then_lines_then_characters(self):
        paragraphs = prose(120000, 1)
        lines = '\n'.join(prose(1500, 100 + n, paragraph=10 ** 9) for n in range(150))
        flat = prose(300000, 3, paragraph=10 ** 9)
        entries = [entry(1, 'start', event='start'), entry(2, 'prompt', paragraphs, turn=2),
                   entry(3, 'answer', lines, turn=2), entry(4, 'answer', flat, turn=2)]
        value = curator_document.session(LOG, entries)
        turn = value['turns'][0]
        frame = request_budget._Frame(BASE, [], request_budget._pair('<items form="full"/>'),
                                      request_budget._pair('<conflicts omitted="0"/>'))
        part = request_budget._Part(frame, value, turn, request_budget.PROVISIONAL)
        pieces = part.pieces(request_budget.PROVISIONAL)

        def fits(index, text):
            return request_budget._safe(part.pair(request_budget.PROVISIONAL, [(index, text)])) <= 90000
        self.assertTrue(all(fits(index, text) for index, text in pieces))
        found = {}
        for index, text in pieces:
            found.setdefault(index, []).append(text)
        self.assertEqual([''.join(found[index]) for index in range(3)], [paragraphs, lines, flat])
        self.assertEqual(len(found[0]), paragraphs.count('\n\n') + 1)
        self.assertTrue(all(text.endswith('\n\n') and text.count('\n') == 2 for text in found[0][:-1]))
        self.assertEqual(len(found[1]), 150)
        self.assertTrue(all(text.endswith('\n') and text.count('\n') == 1 for text in found[1][:-1]))
        self.assertEqual(len(found[2]), 2)
        head = found[2][0]
        self.assertFalse(fits(2, flat[:len(head) + 1]))

    # The item list (step 1)

    def test_the_list_goes_full_up_to_40000_then_in_short_lines(self):
        values = [item('Long item %02d' % n, SOURCE, said=day(n), text=prose(3000, n)) for n in range(23)]

        def measured(current):
            return request_budget.safe(FIXED + curator_document.curate(lines=[], items=list(current.current),
                                                                       form='full', sessions=[]))
        pad = item('Pad item', SOURCE, said=day(40), text='x')
        need = 40000 - measured(self.layer(values + [pad]))
        self.assertTrue(0 < need < 1999)
        pad['text'] = 'x' + 'y' * (2 * need)
        exact = self.layer(values + [pad])
        self.assertEqual(measured(exact), 40000)
        listed = request_budget.choose(exact, BASE, ranked=lambda: self.fail('ranked for a whole list'))
        self.assertEqual((listed.form, listed.items, listed.candidates, listed.omitted, listed.after, listed.due),
                         ('full', exact.current, (), 0, None, False))
        pad['text'] += 'yy'
        above = self.layer(values + [pad])
        self.assertEqual(measured(above), 40001)
        listed = request_budget.choose(above, BASE, ranked=lambda: self.fail('ranked for a whole list'))
        self.assertEqual((listed.form, listed.items, listed.omitted, listed.due), ('short', above.current, 0, True))
        self.assertLessEqual(request_budget.safe(FIXED + self.listed(above, listed)), 40000)

    def test_tc353_a_carried_candidate_brings_both_current_items(self):
        values = items_of(3)
        known = candidate(values[0], values[2])
        result = request_budget.plan(self.layer(values, candidates=[known]), [session([('Keep it local', 'Yes')])],
                                     schema=SCHEMA, count=Counter())
        root = ET.fromstring(result.requests[0].source)
        self.assertEqual((result.items.form, result.items.after), ('full', known['id']))
        self.assertEqual([(node.get('id'), node.get('items')) for node in root.iter('conflict')],
                         [(known['id'], values[0]['id'] + ' ' + values[2]['id'])])
        self.assertEqual(root.find('conflicts').get('omitted'), '0')
        self.assertLessEqual({values[0]['id'], values[2]['id']}, {node.get('id') for node in root.iter('item')})
        # In a partial list the pair still travels whole.
        many = items_of(450)
        known = candidate(many[3], many[4])
        current = self.layer(many, candidates=[known])
        listed = request_budget.choose(current, BASE, ranked=lambda: [])
        self.assertEqual((listed.form, [c['id'] for c in listed.candidates], listed.omitted, listed.after),
                         ('part', [known['id']], 0, known['id']))
        self.assertEqual([value['id'] for value in listed.items], [many[3]['id'], many[4]['id']])

    def test_a_whole_list_records_the_last_bundle_in_rotation(self):
        values = items_of(6)
        bundles = [candidate(values[2 * k], values[2 * k + 1], at=minute(k)) for k in range(3)]
        closed = dict(bundles[1], status='settled', closed=LATER)
        for after, records, expected in ((None, bundles, 2), (bundles[0]['id'], bundles, 0),
                                         (bundles[1]['id'], [bundles[0], closed, bundles[2]], 0)):
            with self.subTest(after=after):
                current = self.layer(values, candidates=records)
                listed = request_budget.choose(current, BASE, after=after)
                self.assertEqual((listed.form, listed.omitted, listed.after), ('full', 0, bundles[expected]['id']))

    def test_tc155_a_list_of_60000_in_short_lines_goes_in_part_and_the_turns_are_curated(self):
        values = items_of(450)
        old = item('An older decision', SOURCE, status='superseded')
        old['superseded_by'] = values[0]['id']
        self.assertGreaterEqual(request_budget.safe(curator_document._items(values, 'short')[1]), 60000)
        lines = [line('Ship the first release', [values[5]['id']], 'goal', 1),
                 line('Keep raw logs local', [values[10]['id'], old['id']], 'decisions', 1),
                 line('Use the shared folder', [values[20]['id'], values[10]['id']], 'decisions', 2)]
        pinned = [values[30]['id'], values[10]['id']]
        first, second = candidate(values[40], values[41], at=minute(1)), candidate(values[50], values[51], at=minute(2))
        current = self.layer(values + [old], lines, pinned, [second, first])
        connection = self.index(values + [old])
        asked = []

        def rank(text):
            asked.append(text)
            return [found for found, _ in index_io.search(connection, text)]
        turns = [('Please check mark0100 and mark0300 ' + prose(30000, 155, words=TALK),
                  'Noted mark0200 ' + prose(30000, 156, words=TALK))]
        turns += [(prose(30000, 200 + n, words=TALK), prose(30000, 300 + n, words=TALK)) for n in range(5)]
        sessions = [session(turns)]
        expected = keys(sessions)
        head = [values[n]['id'] for n in (5, 10, 20, 30, 40, 41, 50, 51)]
        carried, after, rounds = [], None, 0
        while any(value['turns'] for value in sessions):
            result = request_budget.plan(current, sessions, schema=SCHEMA, count=Counter(), after=after, rank=rank)
            listed, (request,) = result.items, result.requests
            rounds += 1
            self.assertEqual((listed.form, listed.due, listed.omitted), ('part', True, 0))
            chosen = [value['id'] for value in listed.items]
            ranked = [found for found, _ in index_io.search(connection, asked[-1]) if found not in head]
            self.assertEqual(chosen, head + ranked)
            if rounds == 1:
                self.assertEqual(set(ranked), {values[n]['id'] for n in (100, 200, 300)})
            self.assertLessEqual(request_budget.safe(FIXED + self.listed(current, listed)), 40000)
            self.assertEqual([c['id'] for c in listed.candidates], [first['id'], second['id']])
            self.assert_whole(request, sessions)
            carried.extend(request.turns)
            after = listed.after
            sessions = left(sessions, set(request.turns))
        self.assertEqual(carried, expected)
        self.assertGreater(rounds, 1)

    def test_a_partial_list_fills_by_rank_up_to_40000(self):
        values = items_of(450)
        current = self.layer(values)
        ranking = [value['id'] for value in reversed(values)][::2] + [value['id'] for value in values][::2]
        listed = request_budget.choose(current, BASE, ranked=lambda: ranking)
        chosen = [value['id'] for value in listed.items]
        self.assertEqual(chosen, ranking[:len(chosen)])
        self.assertLessEqual(request_budget.safe(FIXED + self.listed(current, listed)), 40000)
        more = request_budget.ItemList('part', listed.items + (current.items[ranking[len(chosen)]],), (), 0, None, True)
        self.assertGreater(request_budget.safe(FIXED + self.listed(current, more)), 40000)

    def test_tc387_bundles_rotate_whole_with_an_omitted_count_and_none_starve(self):
        values = items_of(400)
        candidates = [candidate(values[2 * k], values[2 * k + 1], at=minute(k)) for k in range(200)]
        gone = item('Withdrawn item', SOURCE, status='withdrawn')
        stale = candidate(values[0], gone, at=minute(500))
        current = self.layer(values + [gone], candidates=candidates + [stale])
        self.assertEqual(len(current.candidates), 200)
        rng, after, seen, firsts = random.Random(387), None, set(), []
        for round_ in range(4):
            order = [value['id'] for value in values]
            rng.shuffle(order)
            listed = request_budget.choose(current, BASE, after=after, ranked=lambda: order)
            ids = {value['id'] for value in listed.items}
            carried = [c['id'] for c in listed.candidates]
            with self.subTest(round=round_):
                self.assertEqual(listed.form, 'part')
                self.assertTrue(all(set(c['items']) <= ids for c in listed.candidates))
                self.assertEqual(listed.omitted, 200 - len(carried))
                self.assertGreater(listed.omitted, 0)
                expected = [c['id'] for c in rotation(current.candidates, after, current.places)][:len(carried)]
                self.assertEqual(sorted(carried), sorted(expected))
                self.assertEqual(carried, sorted(carried, key=lambda c: current.places[c]))
                self.assertEqual(listed.after, expected[-1])
                built = self.listed(current, listed)
                self.assertLessEqual(request_budget.safe(FIXED + built), 40000)
                root = ET.fromstring(built)
                self.assertEqual(root.find('conflicts').get('omitted'), str(listed.omitted))
                self.assertEqual([node.get('id') for node in root.iter('conflict')], carried)
                self.assertNotIn(stale['id'], carried)
            seen.update(carried)
            firsts.append(expected[0])
            after = listed.after
        self.assertEqual(seen, {c['id'] for c in candidates})
        self.assertEqual(firsts[0], candidates[0]['id'])
        # A rotation goes on after a candidate that has closed since.
        settled = dict(next(c for c in candidates if c['id'] == after), status='settled', closed=LATER)
        changed = self.layer(values + [gone], candidates=[settled if c['id'] == after else c for c in candidates])
        listed = request_budget.choose(changed, BASE, after=after, ranked=lambda: [])
        carried = [c['id'] for c in listed.candidates]
        following = [c['id'] for c in rotation(changed.candidates, after, changed.places)]
        self.assertEqual(sorted(carried), sorted(following[:len(carried)]))
        self.assertEqual(listed.after, following[len(carried) - 1])
        self.assertNotIn(after, carried + following)

    def test_newest_items_fill_the_list_when_the_index_cannot_be_read(self):
        values = items_of(450)
        current = self.layer(values)
        turns = [(prose(15000, 400 + n, words=TALK), prose(15000, 500 + n, words=TALK)) for n in range(10)]
        sessions = [session(turns)]
        newest = [value['id'] for value in current.current]
        self.assertEqual(newest[0], values[-1]['id'])
        for error in (index_io.IndexUnavailable(), sqlite3.DatabaseError('file is not a database'), OSError('gone')):
            asked = []

            def rank(text, error=error):
                asked.append(text)
                raise error
            with self.subTest(error=type(error).__name__):
                result = request_budget.plan(current, sessions, schema=SCHEMA, count=Counter(), rank=rank)
                chosen = [value['id'] for value in result.items.items]
                self.assertEqual(chosen, newest[:len(chosen)])
                self.assertGreater(len(chosen), 100)
                text, = asked
                every = '\n'.join(value['text'] for turn in sessions[0]['turns'] for value in turn['entries'])
                self.assertTrue(every.startswith(text))
                self.assertLess(len(text), len(every))
                self.assertLessEqual(request_budget.working(text), 57000 + 20)

        def broken(text):
            raise ValueError('not an index failure')
        with self.assertRaises(ValueError):
            request_budget.plan(current, sessions, schema=SCHEMA, count=Counter(), rank=broken)

    # Turns, counts and parts (steps 2 to 6)

    def test_tc153_a_turn_of_250000_tokens_goes_in_parts_with_the_same_state_and_list(self):
        values = items_of(3)
        known = candidate(values[0], values[1])
        current = self.layer(values, [line('Raw logs stay local', [values[0]['id']])], [values[2]['id']], [known])
        big = session([(prose(375000, 1), prose(375000, 2))])
        self.assertEqual(sum(rule(value['text']) for value in big['turns'][0]['entries']), 250000)
        counter = Counter()
        result = request_budget.plan(current, [big], schema=SCHEMA, count=counter)
        parts = len(result.requests)
        self.assertGreaterEqual(parts, 3)
        frames, texts, spans = set(), {}, {}
        for number, request in enumerate(result.requests, 1):
            with self.subTest(part=number):
                self.assertEqual((request.part, request.turns), ((number, parts), ((LOG, big['turns'][0]['seq']),)))
                for entry, start, end in request.spans:
                    spans.setdefault(entry, []).append((start, end))
                self.assertLess(body_rule(sent(request.source)), 100000)
                root = ET.fromstring(request.source)
                frames.add(tuple(ET.tostring(root.find(tag), encoding='unicode') for tag in ('state', 'items',
                                                                                           'conflicts')))
                turn, = root.iter('turn')
                self.assertEqual((turn.get('seq'), turn.get('part'), turn.get('parts')),
                                 (str(big['turns'][0]['seq']), str(number), str(parts)))
                for node in turn.iter('entry'):
                    texts.setdefault(node.get('id'), []).append(node.text or '')
        self.assertEqual(len(frames), 1)
        self.assertIn(values[0]['id'], next(iter(frames))[1])
        originals = big['turns'][0]['entries']
        self.assertEqual(list(texts), [value['id'] for value in originals])
        for value in originals:
            pieces = texts[value['id']]
            self.assertEqual(''.join(pieces), value['text'])
            # Each part ends at a paragraph break of the entry it cuts.
            self.assertTrue(all(piece.endswith('\n\n') for piece in pieces[:-1]))
            # The worker confines each part's quotes to its spans, which name the same pieces in order.
            self.assertEqual([value['text'][start:end] for start, end in spans[value['id']]], pieces)
            ends = [0] + [end for _, end in spans[value['id']]]
            self.assertEqual([start for start, _ in spans[value['id']]], ends[:-1])
            self.assertEqual(ends[-1], len(value['text']))
        self.assertEqual(sum(request.counts for request in result.requests), len(counter.calls))

    def test_tc154_a_line_of_500_kb_is_cut_only_between_characters(self):
        rng = random.Random(154)
        clusters, size = [], 0
        while size < 500 * 1024:
            value = rng.choice(CLUSTERS)
            clusters.append(value)
            size += len(value.encode('utf-8'))
        text = ''.join(clusters)
        self.assertNotIn('\n', text)
        self.assertLess(len(text.encode('utf-8')), 512 * 1024)
        bounds, offset = {0}, 0
        for value in clusters:
            offset += len(value)
            bounds.add(offset)
        line_turn = session([(text, 'Noted.')])
        result = request_budget.plan(self.layer(), [line_turn], schema=SCHEMA, count=Counter())
        parts = len(result.requests)
        self.assertGreaterEqual(parts, 3)
        pieces, cuts = [], []
        for number, request in enumerate(result.requests, 1):
            with self.subTest(part=number):
                self.assertEqual(request.part, (number, parts))
                self.assertLess(body_rule(sent(request.source)), 100000)
                root = ET.fromstring(request.source)
                prompt = [node.text or '' for node in root.iter('entry')
                          if node.get('id') == line_turn['turns'][0]['entries'][0]['id']]
                if prompt:
                    pieces.append(prompt[0])
                    cuts.append(sum(map(len, pieces)))
        self.assertEqual(''.join(pieces), text)
        self.assertTrue(set(cuts) <= bounds, sorted(set(cuts) - bounds)[:5])

    def test_clusters_stay_whole_across_parts(self):
        # Devanagari KSSA and Khmer KA with a subscript KA: three code points each, one character to a reader;
        # a leading jamo before a syllable, and the Arabic number sign before a digit: two each.
        for cluster in ('क्ष', 'ក្ក', 'ᄀ가', '\u0600\u0661'):
            with self.subTest(cluster=cluster):
                text = cluster * (150000 // len(cluster))
                result = request_budget.plan(self.layer(), [session([(text, None)])], schema=SCHEMA,
                                             count=lambda source: None)
                pieces = [''.join(node.text or '' for node in ET.fromstring(request.source).iter('entry'))
                          for request in result.requests]
                self.assertGreaterEqual(len(pieces), 3)
                self.assertEqual(''.join(pieces), text)
                self.assertEqual([len(piece) % len(cluster) for piece in pieces], [0] * len(pieces))

    def test_a_count_far_above_the_working_estimate_cuts_the_same_share(self):
        # A counter that reads every character as 1.04 tokens, twice the safe estimate's rate for ASCII.
        def dense(source):
            return -(-len(FIXED + source) * 104 // 100)
        empty = request_budget.working(FIXED + curator_document.curate(lines=[], items=[], form='full', sessions=[]))

        def infeasible(count, sessions):
            excess = count - 99000
            return self.estimate((sessions, len(sessions['turns'])), 'working') - excess - -(-excess // 10) <= empty
        many = session([(prose(2500, 50 + n), prose(2500, 90 + n)) for n in range(30)])
        calls = []

        def count(source):
            calls.append((source.count('<turn '), dense(source)))
            return calls[-1][1]
        request, = request_budget.plan(self.layer(), [many], schema=SCHEMA, count=count).requests
        # Lower by the excess and a tenth more, no request would be left; by their share of the count, 15 turns.
        self.assertTrue(infeasible(calls[0][1], many))
        self.assertEqual([turns for turns, _ in calls], [30, 15])
        self.assertEqual((len(request.turns), request.counted, request.counts), (15, calls[-1][1], 2))
        self.assertLessEqual(request.counted, 99000)

        # One turn of 160,000 characters: it no longer goes whole and uncounted after one count of 173,058.
        text = prose(160000, 7)
        big = session([(text, None)])
        calls.clear()
        result = request_budget.plan(self.layer(), [big], schema=SCHEMA, count=count)
        self.assertEqual([request.part for request in result.requests], [(1, 2), (2, 2)])
        self.assertEqual(calls[0], (1, 173058))
        first, second = result.requests
        self.assertEqual((first.counted, first.counts), (calls[-1][1], 2))
        self.assertLessEqual(first.counted, 99000)
        self.assertEqual((second.counted, second.counts), (None, 0))
        self.assertLessEqual(second.safe, 60000)
        self.assertTrue(all(dense(request.source) < 99000 for request in result.requests))
        shown = [''.join(node.text or '' for node in ET.fromstring(request.source).iter('entry'))
                 for request in result.requests]
        self.assertEqual(''.join(shown), text)

    def test_a_single_turn_goes_in_parts_when_the_count_or_the_fallback_cannot_take_it_whole(self):
        # 300,000 ASCII characters: the working estimate fits the fill, the safe one passes 90,000.
        big = session([(prose(150000, 7), prose(150000, 8))])
        for answers in ((None,), (120000, 120000, 120000)):
            with self.subTest(answers=answers):
                counter = Counter(*answers)
                result = request_budget.plan(self.layer(), [big], schema=SCHEMA, count=counter)
                self.assertGreaterEqual(len(result.requests), 2)
                self.assertTrue(all(request.part is not None for request in result.requests))
                self.assertTrue(all(body_rule(sent(request.source)) < 100000 for request in result.requests))
        # A turn that only fails as a whole goes as one request, shown whole.
        middle = session([(prose(100000, 9), prose(100000, 10))])
        counter = Counter(None)
        request, = request_budget.plan(self.layer(), [middle], schema=SCHEMA, count=counter).requests
        self.assertEqual((request.part, request.spans), (None, None))
        self.assertEqual((request.counted, request.counts), (counter.calls[-1], 1))
        self.assertEqual(request.source, curator_document.curate(lines=[], items=[], form='full', sessions=[middle]))
        self.assert_whole(request, [middle])

    def estimate(self, turns, kind):
        sessions = [dict(turns[0], turns=turns[0]['turns'][:turns[1]])]
        return getattr(request_budget, kind)(FIXED + curator_document.curate(lines=[], items=[], form='full',
                                                                            sessions=sessions))

    def test_turns_fill_while_the_working_estimate_stays_under_97000(self):
        current = self.layer()
        texts = [(prose(30000, 600 + n), prose(30000, 700 + n)) for n in range(6)]
        need = 97000 - self.estimate((session(texts + [('x', None)]), 7), 'working')
        self.assertTrue(0 < need < 30000)
        for extra, kept in ((0, 6), (-4, 7)):
            with self.subTest(extra=extra):
                value = session(texts + [('x' + 'y' * (4 * need + extra), None), ('tail', 'end')])
                self.assertEqual(self.estimate((value, 7), 'working'), 97000 + extra // 4)
                request, = request_budget.plan(current, [value], schema=SCHEMA, count=Counter(50000)).requests
                self.assertEqual((len(request.turns), request.counted), (kept, 50000))

    def test_the_fallback_fills_up_to_exactly_90000(self):
        current = self.layer()
        texts = [(prose(7000, 800 + n), prose(7000, 900 + n)) for n in range(12)]
        need = 90000 - self.estimate((session(texts + [('x', None)]), 13), 'safe')
        self.assertTrue(0 < need < 10000)
        for extra, kept in ((0, 13), (2, 12)):
            with self.subTest(extra=extra):
                value = session(texts + [('x' + 'y' * (2 * need + extra), None), ('tail', 'end')])
                self.assertEqual(self.estimate((value, 13), 'safe'), 90000 + extra // 2)
                counter = Counter(None)
                request, = request_budget.plan(current, [value], schema=SCHEMA, count=counter).requests
                self.assertEqual((len(request.turns), request.counted, request.counts, counter.calls),
                                 (kept, None, 1, [None]))

    def test_a_count_over_99000_drops_turns_by_the_excess_and_a_tenth_more(self):
        value = session([(prose(7000, 1000 + n), prose(7000, 1100 + n)) for n in range(20)])
        excess = self.estimate((value, 20), 'working') - self.estimate((value, 19), 'working')
        self.assertGreater(excess, 3000)
        counter = Counter(99000 + excess, 50000)
        request, = request_budget.plan(self.layer(), [value], schema=SCHEMA, count=counter).requests
        # Lower by the excess alone, 19 turns would do; a tenth more leaves 18.
        self.assertEqual((len(request.turns), request.counted, request.counts), (18, 50000, 2))
        self.assertEqual(counter.calls, [99000 + excess, 50000])

    def test_after_three_high_counts_the_fallback_refills_from_every_turn(self):
        value = session([(prose(7000, 1200 + n), prose(7000, 1300 + n)) for n in range(20)])
        working = {k: self.estimate((value, k), 'working') for k in (11, 12, 20)}
        fallback = max(k for k in range(1, 21) if self.estimate((value, k), 'safe') <= 90000)
        # The first excess leaves 11 turns, still counted; the next two leave 10, fewer than the fallback takes.
        excess = next(e for e in range(1, 60000) if working[11] <= working[20] - e - -(-e // 10) < working[12])
        counter = Counter(99000 + excess, 99001, 99001)
        request, = request_budget.plan(self.layer(), [value], schema=SCHEMA, count=counter).requests
        self.assertEqual((counter.turns, fallback), ([20, 11, 10], 12))
        self.assertEqual((request.turns, request.counted, request.counts), (tuple(keys([value])[:12]), None, 3))
        # A failed count refills the same way.
        counter = Counter(None)
        request, = request_budget.plan(self.layer(), [value], schema=SCHEMA, count=counter).requests
        self.assertEqual((counter.turns, len(request.turns), request.counts), ([20], 12, 1))

    def test_a_turn_counted_too_large_alone_goes_in_parts_even_within_the_fallback(self):
        value = session([(prose(85000, 11), prose(85000, 12))])
        self.assertLessEqual(self.estimate((value, 1), 'safe'), 90000)
        # Counted alone, the turn passes 99,000; counted again in pieces, it still does. The first part,
        # lower by the excess and a tenth more, is counted a third time, though its safe estimate is under 60,000.
        counter = Counter(120000, 120000)
        result = request_budget.plan(self.layer(), [value], schema=SCHEMA, count=counter)
        self.assertEqual(counter.turns, [1, 1, 1])
        self.assertLessEqual(result.requests[0].safe, 60000)
        self.assertEqual((result.requests[0].counted, result.requests[0].counts), (counter.calls[-1], 2))
        self.assertGreaterEqual(len(result.requests), 2)
        self.assertEqual([request.part for request in result.requests],
                         [(n, len(result.requests)) for n in range(1, len(result.requests) + 1)])

    def test_small_requests_go_uncounted_and_plan_refuses_bad_inputs(self):
        current = self.layer()
        sessions = [session([('Keep raw logs local', 'Agreed'), ('And the index too', None)], log=OTHER)]
        counter = Counter()
        request, = request_budget.plan(current, sessions, schema=SCHEMA, count=counter).requests
        self.assertEqual((request.turns, request.counted, request.counts, counter.calls),
                         (tuple(keys(sessions)), None, 0, []))
        self.assertEqual((request.safe, request.working),
                         (request_budget.safe(request.source), request_budget.working(request.source)))
        with self.assertRaises(ValueError):
            request_budget.plan(current, sessions, schema=SCHEMA, count=counter, instructions='merge-2')
        with self.assertRaises(TypeError):
            request_budget.plan(current, sessions, schema=SCHEMA, count=None)
        with self.assertRaises(TypeError):
            request_budget.plan(current, sessions, schema=SCHEMA, count=counter, rank='index')
        with self.assertRaises(ValueError):
            request_budget.plan(current, left(sessions, set(keys(sessions))), schema=SCHEMA, count=counter)
        with self.assertRaises(ValueError):
            request_budget.plan(current, sessions, schema=SCHEMA, count=counter, after='i_0000')


class CountedRequestTest(unittest.TestCase):
    """Counts from a local test server through model_count, which logs each one."""

    def setUp(self):
        self.transport = transport_fixture.ModelTransportTest()
        self.transport.setUp()
        self.addCleanup(self.transport.doCleanups)
        self.usage = usage_fixture.ModelUsageTest()
        self.usage.setUp()
        self.addCleanup(self.usage.doCleanups)
        environment = mock.patch.dict(os.environ, {
            'CORTHEX_MEMORY_ANTHROPIC_API_KEY': KEY,
            'CORTHEX_MEMORY_ANTHROPIC_BASE_URL': 'http://127.0.0.1:' + str(self.transport.server.server_port)})
        environment.start()
        self.addCleanup(environment.stop)
        self.script, self.answered = [], []
        self.transport.reply = self.answer
        self.empty = RequestBudgetTest.layer(self)

    def answer(self, handler):
        body = self.transport.requests[-1][2]
        value = self.script.pop(0) if self.script else body_rule(body)
        self.answered.append(value)
        if value == 'fail':
            raw, status = json.dumps({'type': 'error', 'error': {'type': 'api_error', 'message': 'x'}}), 500
        else:
            raw, status = json.dumps({'input_tokens': value}), 200
        self.transport.send(handler, raw.encode('utf-8'), status=status, mime='application/json')

    def count(self, source):
        return model_count.count(self.usage.memory, project='sample', instructions='curate-2', source=source,
                                 schema=SCHEMA, config={}, check=lambda: None).tokens

    def rows(self):
        return [json.loads(line) for path in sorted((self.usage.folder/'logs').glob('usage-*.jsonl'))
                for line in path.read_bytes().splitlines()]

    def plan(self, sessions):
        request, = request_budget.plan(self.empty, sessions, schema=SCHEMA, count=self.count).requests
        return request

    def test_tc157_counts_only_above_60000_and_falls_back_to_90000(self):
        def single(size):
            return [session([('a' * size, 'ok')])]

        def measured(sessions):
            return request_budget.safe(FIXED + curator_document.curate(lines=[], items=[], form='full',
                                                                       sessions=sessions))
        need = 60000 - measured(single(1000))
        exact, above = single(1000 + 2 * need), single(1002 + 2 * need)
        self.assertEqual((measured(exact), measured(above)), (60000, 60001))
        request = self.plan(exact)
        self.assertEqual((request.counted, request.counts, len(self.transport.requests)), (None, 0, 0))
        request = self.plan(above)
        self.assertEqual(len(self.transport.requests), 1)
        self.assertEqual((request.counted, request.counts), (self.answered[-1], 1))

        many = [session([(prose(7000, n), prose(7000, 100 + n)) for n in range(20)])]
        whole = keys(many)
        fallback = max(k for k in range(1, 21) if measured([dict(many[0], turns=many[0]['turns'][:k])]) <= 90000)
        self.assertLess(fallback, 18)
        self.script = [99000]
        request = self.plan(many)
        self.assertEqual((list(request.turns), request.counted, request.counts), (whole, 99000, 1))

        before = len(self.transport.requests)
        self.script = [99001, 99001, 99001]
        request = self.plan(many)
        counted = [body['messages'][0]['content'].count('<turn ') for _, _, body in self.transport.requests[before:]]
        self.assertEqual(counted, [20, 19, 18])
        self.assertEqual((list(request.turns), request.counted, request.counts), (whole[:fallback], None, 3))
        self.assertLessEqual(measured([dict(many[0], turns=many[0]['turns'][:fallback])]), 90000)

        before = len(self.transport.requests)
        self.script = ['fail']
        request = self.plan(many)
        self.assertEqual(len(self.transport.requests) - before, 1)
        self.assertEqual((list(request.turns), request.counted, request.counts), (whole[:fallback], None, 1))

        rows = self.rows()
        self.assertEqual(len(rows), len(self.transport.requests))
        self.assertTrue(all((row['call'], row['cost'], row['instructions']) == ('count-tokens', 0, 'curate-2')
                            for row in rows))
        self.assertEqual([(row['result'], row.get('error')) for row in rows].count(('failed', 'api_error')), 1)

    def test_tc152_fifty_turns_go_whole_once_oldest_first_under_100000(self):
        first = session([(prose(9000, n), prose(9000, 1000 + n)) for n in range(30)])
        second = session([(prose(9000, 2000 + n), prose(9000, 3000 + n)) for n in range(20)], log=OTHER)
        sessions = [first, second]
        self.assertEqual(sum(rule(value['text']) for s in sessions for turn in s['turns']
                             for value in turn['entries']), 300000)
        expected, carried, requests = keys(sessions), [], []
        while any(value['turns'] for value in sessions):
            request = self.plan([value for value in sessions if value['turns']])
            RequestBudgetTest.assert_whole(self, request, sessions)
            requests.append(request)
            carried.extend(request.turns)
            sessions = left(sessions, set(request.turns))
        self.assertEqual(carried, expected)
        self.assertGreater(len(requests), 2)
        self.assertTrue(any(value > 99000 for value in self.answered))
        self.assertEqual(sum(request.counts for request in requests), len(self.transport.requests))


if __name__ == '__main__':
    unittest.main()
