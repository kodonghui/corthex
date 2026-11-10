"""TASK-115: decisions, withdrawals and exact numbers across compaction boundaries, stage 1 without a model.

TC-419 at the direct boundaries, on made-up format-2 stores. A made-up
conversation of 10 user decisions, 3 of them withdrawn later, and 10 exact
numbers crosses one, three and five compaction boundaries. Each prompt goes
through recall as the prompt hook will run it (API-002 steps 5 and 9) and its
turn is recorded in the session's raw log; the curation worker curates the
turns with answers that a local test server gives from a script, and the memory
worker's step 6 embeds the new items (API-005). A boundary is what the session
start hook does after a compaction (SPEC-005, SPEC-021): a `compact` entry in
the raw log, the start summary and its line in the injection log.

Right before each boundary the user asks about the last number said, and right
after it about the same number first, so that the item that recall injected
just before the compaction has to come back (SPEC-023, as the maintainer changed
it on 2026-11-10); then about each decision and each other number said so far.
After each boundary the start summary and recall must show every decision in
force and each number as it was said, and nothing of a withdrawn decision. The
test counts what the compaction research measures: the decisions that survive,
the withdrawn decisions that come back, and the numbers lost or changed.

The embeddings and the curator's answers come from a script, so this checks
what the code keeps, shows and leaves out across the boundaries, not what a
model writes or what a host's compaction keeps: stage 2, with real curator
calls and Claude Code compactions, is TASK-100's TC-420. Every request goes to
the local test server, with keys made up during the run; no provider is called.
Nothing is wired to a hook before the 0.3.0 activation.
"""
from collections import namedtuple
from datetime import timezone
import json
import os
import re
import secrets
import sys
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import clock, curation_worker, index_worker, injection_log, prompt_recall, raw_log, start_summary
import test_memory_curation_worker as worker_fixture
from test_memory_curator_answers import answer, change, quote

DAY = worker_fixture.AT[:10]  # every entry of the made-up conversation is from this day
DIMS = 64
HOST, SESSION = 'claude-code', worker_fixture.SESSION
UTC = timezone.utc
BASE = '# Working principles\n\nThe base of the start summary.'

# A decision: the one topic word that only it and the questions about it hold, the user's prompt, the deciding
# words, the item's text, its state line and a question about it.
Decision = namedtuple('Decision', 'topic prompt words text line ask')
DECISIONS = (
    Decision('hooks', 'Keep the four hooks in one script.', 'Keep the four hooks in one script',
             'The four hooks stay in one script.', 'The four hooks stay in one script.',
             'How are the hooks laid out?'),
    Decision('json', 'Store each item as its own json file.', 'Store each item as its own json file',
             'Each item is stored as its own json file.', 'Each item has its own json file.',
             'Do items still go in json files?'),
    Decision('sqlite', 'Use sqlite for the search index.', 'Use sqlite for the search index',
             'The search index uses sqlite.', 'The search index is kept in sqlite.',
             'Is the search index still on sqlite?'),
    Decision('english', 'Write the docs in english first, with Korean pairs.',
             'Write the docs in english first, with Korean pairs', 'Docs are written in english first, with Korean pairs.',
             'Docs come in english first, then in Korean.', 'Do the docs start in english?'),
    Decision('tags', 'Name the release tags plugin--vX.Y.Z.', 'Name the release tags plugin--vX.Y.Z',
             'Release tags are named plugin--vX.Y.Z.', 'Release tags follow plugin--vX.Y.Z.',
             'How do we name the tags?'),
    Decision('worker', 'Run curation in a background worker.', 'Run curation in a background worker',
             'Curation runs in a background worker.', 'A background worker runs curation.',
             'Does curation run in a worker?'),
    Decision('keys', 'Keep the memory keys in the environment only.', 'Keep the memory keys in the environment only',
             'The memory keys live only in the environment.', 'Memory keys stay in the environment.',
             'Where do the memory keys live?'),
    Decision('conflicts', 'Show conflicts in the start summary.', 'Show conflicts in the start summary',
             'Conflicts are shown in the start summary.', 'The start summary shows conflicts.',
             'Do we show conflicts at the start?'),
    Decision('squash', 'Never squash; use merge commits only.', 'Never squash; use merge commits only',
             'Pull requests use merge commits and never squash.', 'Merge commits only, never squash.',
             'Do we squash pull requests?'),
    Decision('deletion', 'Ask me before any deletion.', 'Ask me before any deletion',
             'Ask the user before any deletion.', 'Every deletion waits for the user.',
             'Can you go ahead with a deletion?'),
)
# A number: its topic word, the user's prompt, the quoted words, the item's text, the part and text of its state
# line, a question, and the number as it was said, which the item and the line hold.
Number = namedtuple('Number', 'topic prompt words text part line ask said')
NUMBERS = (
    Number('port', 'Use port 8443 for the local server.', 'Use port 8443 for the local server',
           'The local server uses port 8443.', 'progress', 'The local server listens on port 8443.',
           'Which port does the local server use?', '8443'),
    Number('threshold', 'Set the recall threshold to 0.42, please.', 'Set the recall threshold to 0.42',
           'The recall threshold is 0.42.', 'progress', 'The recall threshold is set to 0.42.',
           'What is the recall threshold now?', '0.42'),
    Number('budget', 'Our monthly budget is $37.50 for model calls.', 'Our monthly budget is $37.50 for model calls',
           'The monthly budget for model calls is $37.50.', 'progress',
           'Model calls stay within the budget of $37.50 a month.', 'How much is the monthly budget?', '$37.50'),
    Number('launch', 'The launch date is 2026-12-01.', 'The launch date is 2026-12-01',
           'The launch is on 2026-12-01.', 'next', 'Prepare the launch for 2026-12-01.', 'When is the launch?',
           '2026-12-01'),
    Number('candidate', 'Call the candidate build v0.3.0-rc.2.', 'Call the candidate build v0.3.0-rc.2',
           'The candidate build is v0.3.0-rc.2.', 'progress', 'The candidate build v0.3.0-rc.2 is being checked.',
           'What is the candidate build called?', 'v0.3.0-rc.2'),
    Number('제한', '프롬프트 훅의 제한 시간은 1.5초로 하죠.', '프롬프트 훅의 제한 시간은 1.5초로 하죠',
           '프롬프트 훅의 제한 시간은 1.5초입니다.', 'progress', '프롬프트 훅은 제한 시간 1.5초 안에 끝납니다.',
           '프롬프트 훅의 제한 시간은 얼마였죠?', '1.5초'),
    Number('rotate', 'Rotate the raw log at 1,048,576 bytes.', 'Rotate the raw log at 1,048,576 bytes',
           'Rotate the raw log at 1,048,576 bytes.', 'progress', 'Rotate each raw log at 1,048,576 bytes.',
           'When do we rotate the raw log?', '1,048,576 bytes'),
    Number('polling', 'Polling the lock every 250 ms hung on Windows, so stop that.',
           'Polling the lock every 250 ms hung on Windows', 'Polling the lock every 250 ms hung on Windows.',
           'blockers', 'Dead end: polling the lock every 250 ms hung on Windows.',
           'What went wrong with polling the lock?', '250 ms'),
    Number('percentile', 'We are done when the prompt hook stays under 900 ms at the 95th percentile.',
           'done when the prompt hook stays under 900 ms at the 95th percentile',
           'The prompt hook must stay under 900 ms at the 95th percentile.', 'next',
           'Done when: the prompt hook stays under 900 ms at the 95th percentile.',
           'Which percentile goal finishes the work?', '900 ms'),
    Number('retention', 'Retention keeps raw logs for 30 days.', 'Retention keeps raw logs for 30 days',
           'Retention keeps raw logs for 30 days.', 'progress', 'Retention keeps the raw logs for 30 days.',
           'How long does retention keep raw logs?', '30 days'),
)
# A withdrawal: the decision that the user takes back, the prompt and words, and whether the curator's answer also
# removes the decision's line, which the code removes as stale otherwise (SPEC-017).
Withdrawal = namedtuple('Withdrawal', 'decision prompt words remove')
WITHDRAWALS = (
    Withdrawal('d2', 'Forget what I said about sqlite; we will pick the index store later.',
               'Forget what I said about sqlite', True),
    Withdrawal('d5', 'I take back the background worker decision.', 'I take back the background worker decision',
               False),
    Withdrawal('d7', 'Drop the conflicts decision, I no longer want that.', 'Drop the conflicts decision', False),
)
# The conversation: each decision, number and withdrawal by its place, every withdrawal later than its decision.
ORDER = ('d0', 'd1', 'd2', 'n0', 'n1', 'd3', 'n2', 'n3', 'd4', 'd5', 'n4', 'w0', 'n5', 'd6', 'd7', 'n6', 'w1',
         'd8', 'n7', 'n8', 'd9', 'w2', 'n9')
TOPICS = tuple(value.topic for value in DECISIONS + NUMBERS)
LABELS = {'progress': 'Work in progress', 'next': 'Next action', 'blockers': 'Blocker'}
MARKERS = ('Dead end', 'Done when')


def said(name):
    """The decision, number or withdrawal that a name of ORDER gives."""
    return {'d': DECISIONS, 'n': NUMBERS, 'w': WITHDRAWALS}[name[0]][int(name[1:])]


def vector(text):
    """The test server's embedding of a text: 1 in the place of each topic word that it holds, and a little more."""
    words = set(re.findall(r'\w+', text.lower()))
    return [1.0 if topic in words else 0.0 for topic in TOPICS] + [0.0] * (DIMS - len(TOPICS) - 1) + [0.1]


def segments(boundaries):
    """ORDER cut into one part for each boundary, as even as they come, the first parts the longer."""
    size, more = divmod(len(ORDER), boundaries)
    found, start = [], 0
    for number in range(boundaries):
        end = start + size + (number < more)
        found.append(ORDER[start:end])
        start = end
    return found


def shown_line(value, item):
    """A number's state line as the start summary shows it (SPEC-021, REQ-228)."""
    label, text = LABELS[value.part], value.line
    for marker in MARKERS:
        if text.startswith(marker + ': '):
            label, text = marker, text[len(marker) + 2:]
    return '- %s: %s (%s)' % (label, text, item)


class ScriptTest(unittest.TestCase):
    """The made-up conversation holds what TC-419 asks for, each topic word in its own texts only."""

    def test_the_conversation_has_10_decisions_3_withdrawals_and_10_numbers(self):
        self.assertEqual(sorted(ORDER), sorted(['d%d' % n for n in range(10)] + ['n%d' % n for n in range(10)] +
                                               ['w%d' % n for n in range(3)]))
        for number, withdrawal in enumerate(WITHDRAWALS):
            self.assertLess(ORDER.index(withdrawal.decision), ORDER.index('w%d' % number))
        for boundaries in (3, 5):
            for number, withdrawal in enumerate(WITHDRAWALS):
                place = {name: index for index, part in enumerate(segments(boundaries)) for name in part}
                with self.subTest(boundaries=boundaries, withdrawal=number):
                    self.assertLess(place[withdrawal.decision], place['w%d' % number])  # it crosses a boundary
        self.assertEqual(len(set(TOPICS)), 20)
        for name in ORDER:
            value = said(name)
            texts = (value.prompt, value.words) if name[0] == 'w' else (value.prompt, value.words, value.text,
                                                                         value.ask)
            own = {said(value.decision).topic} if name[0] == 'w' else {value.topic}
            for text in texts:
                with self.subTest(text=text):
                    self.assertIn(value.words, value.prompt)
                    found = {topic for topic, place in zip(TOPICS, vector(text)) if place}
                    self.assertEqual(found, own)
            if name[0] == 'n':
                for text in (value.prompt, value.text, value.line):
                    self.assertIn(value.said, text)
                self.assertNotIn(value.said, value.ask)


class SurvivalTest(unittest.TestCase):
    """The conversation on the curation worker's store fixture, whose own tests stay in their module."""
    Fixture = worker_fixture.CurationWorkerTest
    configure, layer, write, items, lines = (Fixture.configure, Fixture.layer, Fixture.write, Fixture.items,
                                             Fixture.lines)

    def setUp(self):
        self.Fixture.setUp(self)
        self.keys['CORTHEX_MEMORY_OPENAI_API_KEY'] = 'memory-openai-key-' + secrets.token_hex(12)
        self.keys['CORTHEX_MEMORY_OPENAI_BASE_URL'] = self.server.url
        environment = mock.patch.dict(os.environ, {name: self.keys[name] for name in (
            'CORTHEX_MEMORY_OPENAI_API_KEY', 'CORTHEX_MEMORY_OPENAI_BASE_URL', )})
        environment.start()
        self.addCleanup(environment.stop)
        self.configure(models={'dims': DIMS}, recall={'threshold': 0.4})
        self.server.reply = self.reply
        self.answers = []      # the curator's answers, in the order of the curate requests
        self.entry_of = {}     # the prompt entry of each name of ORDER
        self.item_of = {}      # the item of each decision and number, once curated
        self.withdrawn = set()  # the withdrawn decisions' items, once curated
        self.injected = []     # every item that recall injected, with the withdrawn items at the time

    def reply(self, number, body):
        """The test server: embeddings for the index worker and recall, and the script's next curator answer."""
        if 'input' in body:
            values = [vector(text) for text in body['input']]
            document = {'object': 'list', 'model': body['model'], 'usage': {'prompt_tokens': 9 * len(values)},
                        'data': [{'object': 'embedding', 'index': n, 'embedding': v} for n, v in enumerate(values)]}
            return lambda handler: worker_fixture.Server.send(handler, json.dumps(document).encode('utf-8'),
                                                              mime='application/json')
        return self.answers.pop(0)

    def settings(self):
        return self.memory.configuration(deadline=clock.now() + 10)

    # The hooks' steps, at their module boundaries

    def prompt(self, text, reply):
        """A user's prompt as the prompt hook will handle it: recorded, recalled for, and its injection log line."""
        entry, _ = self.raw.turn(text, reply)
        self.write()
        started = clock.now()
        with mock.patch.object(prompt_recall, 'EMBED_SECONDS', 30):
            found = prompt_recall.recall(self.memory, 'sample', HOST, SESSION, text, started, started + 30,
                                         settings=self.settings(), zone=UTC)
        self.assertIn(found.outcome, ('injected', 'below', 'no-index'), found.error)
        self.assertTrue(prompt_recall.log(self.memory, 'sample', HOST, SESSION, found, entry=entry['id']))
        self.injected.append((found.items, frozenset(self.withdrawn)))
        return entry, found

    def ask(self, name):
        """The user's question about a decision or a number: what recall injected for it."""
        return self.prompt(said(name).ask, 'Answered from what memory gave.')[1]

    def start(self, event=None):
        """What the session start hook does: the raw log's boundary entry, the start summary and its line.

        The raw log of the fixture starts with the session's `start` entry.
        """
        if event is not None:
            self.raw.add(event)
            self.write()
        environment = {name: self.keys[name] for name in (
            'CORTHEX_MEMORY_ANTHROPIC_API_KEY', 'CORTHEX_MEMORY_OPENAI_API_KEY')}
        with mock.patch.dict(os.environ, {'CLAUDE_CODE_REMOTE': ''}):
            part = start_summary.compose(self.memory, 'sample', BASE, clock.now() + 30, settings=self.settings(),
                                         environment=environment, now=worker_fixture.WHEN, zone=UTC)
        self.assertEqual(part.outcome, 'ok', part.error)
        self.assertTrue(start_summary.after(self.memory, 'sample', part, HOST, SESSION).injected)
        return part.text

    def curate(self, chunk):
        """One curation of the chunk's turns with the script's answer, then step 6 for the new items."""
        last = {}
        for line in sorted(self.lines(), key=lambda value: (value['pos'], value['id'])):
            last[line['part']] = line['id']
        changes, added, removed = [], [], []
        for name in chunk:
            value, entry = said(name), self.raw_entry(name)
            if name[0] == 'w':
                target = self.item_of[value.decision]
                changes.append(change(quote(entry, value.words), action='withdraw', targets=[target],
                                      kind='decision', title='Taken back', text='The user takes it back.'))
                if value.remove:
                    (line,) = [line['id'] for line in self.lines() if target in line['cites']]
                    removed.append({'line': line, 'why': 'The user took it back.'})
                continue
            kind, part = ('decision', 'decisions') if name[0] == 'd' else ('fact', value.part)
            changes.append(change(quote(entry, value.words), kind=kind, title=value.text[:60], text=value.text))
            added.append({'part': part, 'after': last.get(part, ''), 'text': value.line, 'cites': [],
                          'changes': [len(changes)]})
        self.answers.append(answer(*changes, state={'change': [], 'add': added, 'remove': removed}))
        deadline = clock.now() + 300
        with self.memory.lease(self.root / 'curation.lock', 'curation', deadline) as owner:
            outcome = curation_worker.curate(self.memory, 'sample', owner, deadline, when=worker_fixture.WHEN)
            self.assertEqual(outcome.reason, 'done')
            (attempt,) = outcome.attempts
            self.assertEqual((attempt.record['result'], attempt.record['applied'], attempt.dropped, attempt.edits),
                             ('ok', len(changes), {}, {}))
            self.assertEqual(index_worker.keep(self.memory, 'sample', owner, deadline, when=worker_fixture.WHEN).reason,
                             'done')
        self.assertEqual(self.answers, [])
        items = self.items()
        for name in chunk:
            if name[0] == 'w':
                target = self.item_of[said(name).decision]
                self.assertEqual(items[target]['status'], 'withdrawn')
                self.withdrawn.add(target)
                continue
            (item,) = [value['id'] for value in items.values()
                       if value['quotes'][0]['entry'] == self.entry_of[name]]
            self.item_of[name] = item
        for name in chunk:
            if name[0] != 'w':
                self.assertEqual([line['text'] for line in self.lines() if self.item_of[name] in line['cites']],
                                 [said(name).line])

    def raw_entry(self, name):
        (entry,) = [value for value in self.raw.entries if value['id'] == self.entry_of[name]]
        return entry

    # The conversation

    def converse(self, boundaries):
        """The conversation across the boundaries; the counts after each boundary."""
        self.assertEqual(self.start().split('\n\n')[-1], 'Memory holds nothing for this project yet.')
        counts, done = [], []
        for part in segments(boundaries):
            chunk = []
            for name in part:
                if name[0] == 'w' and said(name).decision in chunk:
                    self.curate(chunk)  # the decision that it takes back is curated before the withdrawal is
                    chunk = []
                entry, _ = self.prompt(said(name).prompt, 'Noted.')
                self.entry_of[name] = entry['id']
                chunk.append(name)
            self.curate(chunk)
            done.extend(part)
            # The user asks about the last number said, and recall injects it, just before the compaction.
            last = [name for name in done if name[0] == 'n'][-1]
            self.assertEqual(self.ask(last).items, (self.item_of[last],))
            summary = self.start('compact')
            counts.append(self.counted(summary, done, last))
        return counts

    def counted(self, summary, done, first):
        """What the start summary and recall show after a boundary, counted as research E1 counts it.

        The number asked just before the boundary is asked first; then each
        decision and each other number said so far.
        """
        withdrawn = {said(name).decision for name in done if name[0] == 'w'}
        asked = [first] + [name for name in done if name[0] == 'd'] + [
            name for name in done if name[0] == 'n' and name != first]
        blocks = {name: self.ask(name).block for name in asked}
        rows, everything = summary.splitlines(), '\n'.join([summary] + list(blocks.values()))
        count = {'decisions': 0, 'withdrawn': len(withdrawn), 'revived': 0, 'numbers': 0, 'lost': 0, 'changed': 0}
        for name in done:
            if name[0] == 'w':
                continue
            value, item = said(name), self.item_of[name]
            if name in withdrawn:
                count['revived'] += any(text in everything for text in (item, value.text, value.line))
                continue
            kind, speaker = ('decision', 'user decision') if name[0] == 'd' else ('fact', 'user')
            expected = [('- Decision in force: %s (%s)' % (value.line, item) if name[0] == 'd'
                         else shown_line(value, item), rows),
                        ('- %s | %s | %s | %s | %s' % (item, kind, speaker, DAY, value.text),
                         blocks[name].splitlines())]
            places = [(wanted, [row for row in found if item in row]) for wanted, found in expected]
            kept = all(wanted in found for wanted, found in places)
            if name[0] == 'd':
                count['decisions'] += kept
            elif kept:
                count['numbers'] += all(value.said in wanted for wanted, _ in places)
            elif any(not found for _, found in places):
                count['lost'] += 1
            else:
                count['changed'] += 1
        return count

    def expected(self, boundaries):
        """The counts that survival gives after each boundary: everything said so far, nothing withdrawn back."""
        counts, done = [], []
        for part in segments(boundaries):
            done.extend(part)
            withdrawn = {said(name).decision for name in done if name[0] == 'w'}
            counts.append({'decisions': len([n for n in done if n[0] == 'd' and n not in withdrawn]),
                           'withdrawn': len(withdrawn), 'revived': 0,
                           'numbers': len([n for n in done if n[0] == 'n']), 'lost': 0, 'changed': 0})
        return counts

    def survive(self, boundaries):
        counts = self.converse(boundaries)
        self.assertEqual(counts, self.expected(boundaries))
        self.assertEqual(counts[-1], {'decisions': 7, 'withdrawn': 3, 'revived': 0, 'numbers': 10, 'lost': 0,
                                      'changed': 0})
        # A withdrawn decision is never injected once its withdrawal is curated, by any prompt.
        for items, withdrawn in self.injected:
            self.assertFalse(set(items) & withdrawn)
        # Its item stays, withdrawn, and its line went: as the answer said for the first, as stale for the others.
        items = self.items()
        for withdrawal in WITHDRAWALS:
            item = self.item_of[withdrawal.decision]
            self.assertEqual(items[item]['status'], 'withdrawn')
            self.assertFalse([line for line in self.lines() if item in line['cites']])
        # The raw log holds a boundary for each compaction, and the injection log a start line for each start.
        self.assertEqual([entry['kind'] for entry in self.raw.entries if entry['kind'] not in ('prompt', 'answer')],
                         ['start'] + ['compact'] * boundaries)
        path = self.root / 'injections' / (raw_log.log_name(HOST, SESSION) + '.jsonl')
        lines = [injection_log.parse_line(data) for data in path.read_bytes().splitlines()]
        self.assertEqual([line['where'] for line in lines].count('start'), 1 + boundaries)
        self.assertEqual([line['where'] for line in lines].count('prompt'), len(self.injected))

    def test_tc419_across_one_compaction(self):
        self.survive(1)

    def test_tc419_across_three_compactions(self):
        self.survive(3)

    def test_tc419_across_five_compactions(self):
        self.survive(5)


if __name__ == '__main__':
    unittest.main()
