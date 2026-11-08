"""TASK-097: the forget command's preview and confirmation (API-025) on fabricated format-2 stores.

TC-239, TC-240 and the TASK-097 part of TC-393. The runner does not hand
`forget` to the handler before the 0.3.0 activation, so these tests call it as
the runner will, after its gates, with the format-2 store binding. The
confirmed effects arrive with TASK-098; here a stand-in records what the
handler would pass them. A curation in TC-240 runs against the local test
server of the curation worker's tests; no provider is called.
"""
import contextlib
import subprocess
import sys
import types
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import clock, commands, forget_command, forget_plan, item_types, request_inputs, state_types
from test_memory_curator_answers import answer
import test_memory_curation_worker as worker_fixture

AT, DEVICE, EPOCH = worker_fixture.AT, worker_fixture.DEVICE, worker_fixture.EPOCH
OTHER = 'd_zyxwvtsrqpnm'
RUN = 'r_0123456789ab'
SAID = 'Keep the four hooks in one script, and keep the raw logs on this device.'


def ident(prefix, number):
    return '%s_%012d' % (prefix, number)


def line(number, part, text, cites):
    return dict(id=ident('s', number), part=part, pos=number, text=text, cites=list(cites), at=AT, device=DEVICE)


def record(number, cites, why='', generation=1):
    """A TBL-119 record, as the line-history writers append it."""
    return state_types.history_record_bytes(dict(
        at=AT, run=RUN, epoch=EPOCH, generation=generation, line=ident('s', number), part='decisions', pos=1,
        op='changed', text='Earlier text %d.' % number, cites=list(cites), why=why, device=DEVICE))


def candidate(number, first, second):
    return dict(id=ident('c', number), items=[first, second], at=AT, run=RUN, by='curate', status='open')


class ForgetTest(unittest.TestCase):
    def setUp(self):
        self.fixture = worker_fixture.CurationWorkerTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.memory = self.fixture.root, self.fixture.memory
        self.said, self.answered = self.fixture.one_turn(SAID, 'One script now serves the four hooks.')
        self.log = self.fixture.raw.name

    # The store

    def item(self, number, *spans, kind='decision', title=None, status='current', source=None, log=None):
        """An item whose quotes are the given (start, end) ranges of the entry."""
        source = source or self.said
        quotes = [dict(entry=source['id'], log=log or self.log, device=DEVICE, start=start, end=end,
                       speaker=source['speaker'], said=source['at'], words=source['text'][start:end])
                  for start, end in spans]
        return dict(id=ident('i', number), kind=kind, title=title or 'Saved %s %d' % (kind, number),
                    text='A saved %s.' % kind, quotes=quotes, status=status, saved=AT, device=DEVICE)

    def span(self, words, source=None):
        text = (source or self.said)['text']
        start = text.index(words)
        return start, start + len(words)

    def history(self, *records, backup=None):
        (self.root / 'state-history.jsonl').write_bytes(b''.join(records))
        if backup is not None:
            (self.root / 'state-history.jsonl.bak').write_bytes(b''.join(backup))

    def tombstone(self, value):
        stone = dict(item=value['id'], project='sample', at=AT, device=DEVICE,
                     quotes=[{key: quote[key] for key in ('device', 'entry', 'log', 'start', 'end')}
                             for quote in value['quotes']])
        (self.root / 'layer/tombstones' / (value['id'] + '.json')).write_bytes(item_types._raw(stone) + b'\n')

    def tree(self):
        return {path.relative_to(self.root).as_posix(): path.read_bytes()
                for path in sorted(self.root.rglob('*')) if path.is_file() and path.suffix != '.lock'}

    # Running the command

    def command(self, item, *extra, code=None, memory=None):
        arguments = {'folder': str(self.root), 'item': item, 'with_items': list(extra)}
        context = commands.Context('forget', arguments, code, memory or self.memory)
        context.project = types.SimpleNamespace(name='sample')
        context.record = {'device': DEVICE}
        value = forget_command.forget(context)
        commands.validate_result(value, 'forget')
        return value

    @contextlib.contextmanager
    def effects(self):
        """A stand-in for TASK-098's effects that records each call and whether the layer lease was held."""
        calls = []

        def apply(memory, root, plan, deadline):
            leases = [lease.path for lease in memory.held]
            calls.append((plan, leases))
            return commands.result('forget', plan.data, 'Forgotten.')
        with mock.patch.object(forget_command, '_apply', side_effect=apply):
            yield calls

    # TC-239

    def shared_store(self):
        """A pinned decision that two lines cite, with one quote that another item shares and one that it does not."""
        hooks, logs = self.span('Keep the four hooks in one script'), self.span('keep the raw logs on this device')
        decision = self.item(1, hooks, logs)
        shared = self.item(2, self.span('the four hooks'), kind='fact')
        other = self.item(3, self.span('One script now serves', self.answered), kind='fact', source=self.answered)
        lines = [line(1, 'decisions', 'One script serves the four hooks.', [decision['id']]),
                 line(2, 'progress', 'The hook layout was agreed.', [self.said['id']]),
                 line(3, 'goal', 'Ship the plugin.', [other['id']])]
        candidates = [candidate(1, decision['id'], other['id']), candidate(2, shared['id'], other['id'])]
        self.fixture.layer(items=[decision, shared, other], lines=lines, candidates=candidates,
                           pinned=[decision['id']])
        self.history(record(1, [decision['id']], why='Moved.'), record(2, [other['id']], why='Shared with 2.'),
                     record(3, [other['id']]), record(4, [self.answered['id']]))
        return decision, shared, other, lines, (hooks, logs)

    def test_tc239_the_preview_names_what_goes_and_what_stays_and_changes_nothing(self):
        decision, shared, other, lines, (hooks, logs) = self.shared_store()
        before = self.tree()
        value = self.command(decision['id'])
        self.assertEqual((value['outcome'], value['code']), ('confirm', 'ok'))
        self.assertRegex(value['confirm'], r'^[0-9a-hjkmnp-tv-z]{8}$')
        self.assertEqual(value['data'], {
            'project': 'sample', 'item': decision['id'], 'with': [], 'also': [shared['id']],
            'state_lines': [{'line': lines[0]['id'], 'part': 'decisions', 'text': lines[0]['text']},
                            {'line': lines[1]['id'], 'part': 'progress', 'text': lines[1]['text']}],
            'pinned': [decision['id']],
            'raw': [{'entry': self.said['id'], 'log': self.log, 'forgotten': [list(logs)], 'kept': [list(hooks)]}],
            'outside': ['host-transcript', 'providers', 'devices-without-sync'],
            'settled_conflicts': [ident('c', 1)], 'history_records': 2})
        self.assertEqual(value['say'], (
            'Forgetting %s removes it and its search index rows, 2 current state lines and 1 pin. '
            'It fills the quoted words in 1 raw log entry on this device. '
            'Words that %s also quotes stay whole; name that item with --with to forget it too. '
            '1 open conflict candidate is settled. '
            '2 line-history records are removed or cleared of their reason, so undoing an older run may be '
            'partial. Copies in the host transcript, at the model providers and on devices without sync stay.'
            % (decision['id'], shared['id'])))
        self.assertEqual(self.tree(), before)

        both = self.command(decision['id'], shared['id'])
        self.assertEqual(both['data']['with'], [shared['id']])
        self.assertEqual(both['data']['also'], [])
        self.assertEqual(both['data']['raw'], [{'entry': self.said['id'], 'log': self.log,
                                                'forgotten': sorted([list(hooks), list(logs),
                                                                     list(self.span('the four hooks'))]),
                                                'kept': []}])
        self.assertEqual(both['data']['settled_conflicts'], [ident('c', 1), ident('c', 2)])
        self.assertEqual(both['data']['history_records'], 2)
        self.assertIn('Forgetting %s and 1 other item removes them and their search index rows' % decision['id'],
                      both['say'])
        self.assertNotEqual(both['confirm'], value['confirm'])
        self.assertEqual(self.tree(), before)

    def test_ranges_kept_for_an_item_that_stays_are_filled_once_no_item_keeps_them(self):
        hooks = self.span('Keep the four hooks in one script')
        gone, guard, last = self.item(1, hooks), self.item(2, self.span('four hooks'), kind='fact'), \
            self.item(3, self.span('hooks in one'), kind='fact')
        self.fixture.layer(items=[guard, last])
        self.tombstone(gone)
        value = self.command(guard['id'])
        # The earlier tombstone's range still overlaps item 3's quote, and so does item 2's.
        self.assertEqual(value['data']['raw'], [{'entry': self.said['id'], 'log': self.log, 'forgotten': [],
                                                 'kept': [list(self.span('four hooks'))]}])
        self.assertEqual(value['data']['also'], [last['id']])
        value = self.command(guard['id'], last['id'])
        expected = sorted([list(hooks), list(self.span('four hooks')), list(self.span('hooks in one'))])
        self.assertEqual(value['data']['raw'][0]['forgotten'], expected)
        # The request reader hides the same ranges once the forget's tombstones exist (TBL-007).
        self.tombstone(guard)
        self.tombstone(last)
        pending = request_inputs._pending(self.root, self.log)
        self.assertEqual(sorted(list(span) for span in pending[self.said['id']]), expected)

    def test_a_range_already_filled_is_not_filled_again_and_one_beyond_the_text_names_nothing(self):
        logs = self.span('keep the raw logs on this device')
        gone = self.item(1, logs)
        entries = self.fixture.raw.entries
        entries[entries.index(self.said)] = dict(self.said, forgotten=[list(logs)])
        self.fixture.write()
        stay = self.item(2, self.span('Keep the four hooks'), (len(SAID) - 1, len(SAID)))
        # A quote whose range ends past its entry's text, as no quote check would let through.
        stay['quotes'][1].update(end=len(SAID) + 1, words='x.')
        self.fixture.layer(items=[stay])
        self.tombstone(gone)
        value = self.command(stay['id'])
        self.assertEqual(value['data']['raw'], [{'entry': self.said['id'], 'log': self.log,
                                                 'forgotten': [list(self.span('Keep the four hooks'))],
                                                 'kept': []}])

    def test_entries_this_device_does_not_hold_are_not_in_raw_but_their_shared_quotes_are_named(self):
        elsewhere = 'codex-' + 'f' * 16
        source = dict(self.said, id=ident('e', 9))
        away = self.item(1, self.span('the raw logs'), source=source, log=elsewhere)
        away['quotes'][0]['device'] = OTHER
        twin = self.item(2, self.span('raw logs on'), source=source, log=elsewhere, kind='fact')
        self.fixture.layer(items=[away, twin])
        value = self.command(away['id'])
        self.assertEqual((value['data']['raw'], value['data']['also']), ([], [twin['id']]))
        self.assertNotIn('fills the quoted words', value['say'])
        # A log that retention deleted holds nothing either.
        (self.root / 'raw' / (self.log + '.jsonl')).unlink()
        mine = self.item(3, self.span('the raw logs'))
        self.fixture.layer(items=[away, twin, mine])
        self.assertEqual(self.command(mine['id'])['data']['raw'], [])

    def test_hidden_lines_are_not_shown_and_superseded_items_can_be_forgotten(self):
        older = self.item(1, self.span('four hooks'), status='superseded')
        older['superseded_by'] = ident('i', 2)
        newer = self.item(2, self.span('Keep the four hooks in one script'))
        gone = self.item(3, self.span('raw logs'), kind='fact')
        visible = line(1, 'progress', 'The older layout is history.', [older['id']])
        private = line(2, 'progress', 'Also about the raw logs.', [older['id'], gone['id']])
        self.fixture.layer(items=[older, newer], lines=[visible, private])
        self.tombstone(gone)
        value = self.command(older['id'])
        self.assertEqual(value['data']['state_lines'], [{'line': visible['id'], 'part': 'progress',
                                                         'text': visible['text']}])
        self.assertEqual(value['data']['also'], [newer['id']])
        self.assertEqual(value['data']['pinned'], [])
        self.assertEqual(self.command(gone['id'])['code'], 'item-not-found')

    # TC-240

    def test_tc240_a_missing_item_and_a_code_that_a_curation_made_stale(self):
        decision = self.item(1, self.span('Keep the four hooks in one script'), title='Keep the hooks in one script')
        fact = self.item(2, self.span('raw logs'), kind='fact', title='Raw logs stay here')
        self.fixture.layer(items=[decision, fact])
        before = self.tree()
        made_up = ident('i', 9)
        value = self.command(made_up)
        self.assertEqual((value['outcome'], value['code']), ('refused', 'item-not-found'))
        self.assertEqual(value['data']['missing'], [made_up])
        # Both IDs are one character away; a tie keeps the item list's order.
        self.assertEqual([match['item'] for match in value['data']['matches']], [decision['id'], fact['id']])
        self.assertEqual(value['data']['matches'][1], {'item': fact['id'], 'kind': 'fact', 'speaker': 'user',
                                                       'date': AT[:10], 'title': 'Raw logs stay here'})
        typed = self.command(decision['id'], 'Keep the hooks in one scrip')
        self.assertEqual((typed['code'], typed['data']['missing'], typed['data']['matches'][0]['item']),
                         ('item-not-found', ['Keep the hooks in one scrip'], decision['id']))

        with self.effects() as calls:
            first = self.command(decision['id'])
            self.assertEqual(first['data']['state_lines'], [])
            added = {'part': 'decisions', 'after': '', 'text': 'The four hooks stay in one script.',
                     'cites': [decision['id']], 'changes': []}
            self.fixture.server.answers = [answer(state={'change': [], 'add': [added], 'remove': []})]
            (attempt,) = self.fixture.curate().attempts
            self.assertEqual(attempt.requests, 1)
            (new,) = [value for value in self.fixture.lines() if value['cites'] == [decision['id']]]
            stale = self.command(decision['id'], code=first['confirm'])
            self.assertEqual((stale['outcome'], stale['code']), ('confirm', 'confirm-stale'))
            self.assertEqual(stale['data']['state_lines'], [{'line': new['id'], 'part': 'decisions',
                                                             'text': 'The four hooks stay in one script.'}])
            self.assertNotEqual(stale['confirm'], first['confirm'])
            self.assertEqual(calls, [])
            # A code for other arguments is stale too.
            self.assertEqual(self.command(decision['id'], fact['id'], code=stale['confirm'])['code'],
                             'confirm-stale')
            self.assertEqual(calls, [])
            done = self.command(decision['id'], code=stale['confirm'])
        self.assertEqual((done['outcome'], done['code']), ('done', 'ok'))
        ((plan, leases),) = calls
        self.assertEqual(plan.data, stale['data'])
        self.assertEqual(plan.selected, (decision['id'],))
        self.assertEqual(plan.targets, frozenset([decision['id'], self.said['id']]))
        self.assertEqual(leases, [self.root / 'layer.lock'])
        self.assertEqual(self.tree()['layer/items/%s.json' % decision['id']],
                         before['layer/items/%s.json' % decision['id']])

    def test_a_code_for_an_item_forgotten_meanwhile_is_refused_before_any_effect(self):
        value = self.item(1, self.span('four hooks'))
        self.fixture.layer(items=[value])
        code = self.command(value['id'])['confirm']
        self.tombstone(value)
        with self.effects() as calls:
            refused = self.command(value['id'], code=code)
        self.assertEqual((refused['code'], refused['data']['missing'], calls), ('item-not-found', [value['id']], []))

    def test_without_the_effects_a_confirmed_forget_raises_and_changes_nothing(self):
        value = self.item(1, self.span('four hooks'))
        self.fixture.layer(items=[value])
        code = self.command(value['id'])['confirm']
        before = self.tree()
        with self.assertRaises(NotImplementedError):
            self.command(value['id'], code=code)
        self.assertEqual(self.tree(), before)

    # TC-393 (TASK-097's part): the history the forget scrubs

    def test_tc393_part_history_records_count_once_across_copies_and_an_unreadable_primary_is_said(self):
        decision = self.item(1, self.span('four hooks'))
        other = self.item(2, self.span('raw logs'), kind='fact')
        self.fixture.layer(items=[decision, other])
        cited, reason, empty = (record(1, [decision['id']]), record(2, [other['id']], why='Mentions B.'),
                                record(3, [other['id']]))
        only_backup = record(4, [self.said['id']], generation=2)
        self.history(cited, reason, empty, backup=[cited, reason, empty, only_backup])
        value = self.command(decision['id'])
        self.assertEqual(value['data']['history_records'], 3)
        self.assertIn('3 line-history records are removed or cleared of their reason, so undoing an older run '
                      'may be partial.', value['say'])
        # A backup that cannot be read restores nothing, so it adds nothing.
        (self.root / 'state-history.jsonl.bak').write_bytes(b'{"broken"\n')
        self.assertEqual(self.command(decision['id'])['data']['history_records'], 2)
        # An already-empty reason on a record that stays is not counted.
        self.history(empty)
        quiet = self.command(decision['id'])
        self.assertEqual(quiet['data']['history_records'], 0)
        self.assertNotIn('line-history', quiet['say'])
        # A primary that cannot be read is said, and the count is left out rather than guessed.
        (self.root / 'state-history.jsonl').write_bytes(cited + b'{"damaged":')
        damaged = self.command(decision['id'])
        self.assertNotIn('history_records', damaged['data'])
        self.assertIn('The line history cannot be read now, so this forget cannot yet count or verify its '
                      'line-history cleanup.', damaged['say'])
        self.assertEqual((self.root / 'state-history.jsonl').read_bytes(), cited + b'{"damaged":')

    # The command's other answers

    def test_a_project_being_deleted_or_without_a_folder_has_no_item(self):
        value = self.item(1, self.span('four hooks'))
        self.fixture.layer(items=[value])
        (self.root / 'layer/deleted.json').write_bytes(b'{}\n')
        refused = self.command(value['id'], ident('i', 7))
        self.assertEqual((refused['code'], refused['data']['missing'], refused['data']['matches']),
                         ('item-not-found', [value['id'], ident('i', 7)], []))
        (self.root / 'layer/deleted.json').unlink()
        moved = self.root.with_name('elsewhere')
        self.root.rename(moved)
        self.addCleanup(lambda: moved.exists() and moved.rename(self.root))
        refused = self.command(value['id'])
        self.assertEqual((refused['code'], refused['data']['matches']), ('item-not-found', []))
        self.assertFalse(self.root.exists())

    def test_arguments_beyond_the_schema_are_usage_and_a_busy_layer_lease_is_lock_busy(self):
        value = self.item(1, self.span('four hooks'))
        self.fixture.layer(items=[value])
        for item, extra in (('', []), ('i' * 201, []), (value['id'], [''])):
            with self.subTest(item=item[:5], extra=extra):
                self.assertEqual(self.command(item, *extra)['code'], 'usage')
        # Another process holds the project's layer lease, as a curator's apply would.
        code = ("import sys,time;sys.path.insert(0,sys.argv[1]);from pathlib import Path;"
                "from memory_lib import locks;lease=locks.Lock(Path(sys.argv[2]),'layer',sys.argv[3]);"
                "lease.acquire(time.monotonic()+5);print('ready',flush=True);"
                "sys.stdin.readline();lease.release()")
        child = subprocess.Popen([sys.executable, '-B', '-c', code,
                                  str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'),
                                  str(self.root / 'layer.lock'), DEVICE],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), 'ready')
            with mock.patch.object(forget_command, 'WAIT', 0.2):
                started = clock.now()
                busy = self.command(value['id'])
                self.assertLess(clock.now() - started, 5)
            self.assertEqual((busy['outcome'], busy['code']), ('failed', 'lock-busy'))
        finally:
            child.communicate('\n', timeout=30)
        self.assertEqual(child.returncode, 0)
        self.assertEqual(self.command(value['id'])['outcome'], 'confirm')

    def test_the_say_stays_within_the_schema_for_many_items(self):
        spans = [(start, start + 2) for start in range(0, 40, 2)]
        many = [self.item(number, *spans[:20]) for number in range(1, 9)]
        lines = [line(number, 'progress', 'Line %d.' % number, [many[0]['id']]) for number in range(1, 30)]
        self.fixture.layer(items=many, lines=lines, pinned=[value['id'] for value in many],
                           candidates=[candidate(number, many[0]['id'], many[number]['id'])
                                       for number in range(1, 8)])
        self.history(*[record(number, [ident('i', 50)], why='x') for number in range(1, 30)])
        value = self.command(many[0]['id'], *[value['id'] for value in many[1:4]])
        self.assertLessEqual(len(value['say']), 600)
        self.assertIn('Words that %s, %s, %s and 1 more also quote stay whole' % tuple(
            value['id'] for value in many[4:7]), value['say'])


class PlanTest(unittest.TestCase):
    def test_closest_ranks_by_id_or_title_and_keeps_list_order_on_ties(self):
        lines = [{'item': ident('i', number), 'kind': 'fact', 'speaker': 'user', 'date': '2026-11-04',
                  'title': title} for number, title in ((1, 'Ship on Friday'), (2, 'Keep hooks together'),
                                                        (3, 'Ship on Friday'))]
        self.assertEqual([line['item'] for line in forget_plan.closest(lines, ['keep HOOKS'])][0], ident('i', 2))
        self.assertEqual([line['item'] for line in forget_plan.closest(lines, ['ship on friday'], limit=2)],
                         [ident('i', 1), ident('i', 3)])
        self.assertEqual(forget_plan.closest(lines, [ident('i', 3)])[0]['item'], ident('i', 3))
        self.assertEqual(forget_plan.closest([], ['x']), [])

    def test_touching_ranges_do_not_overlap_and_empty_quotes_name_nothing(self):
        entry = {'text': 'abcdefghij'}

        def item(number, *spans):
            return {'id': ident('i', number), 'quotes': [dict(log='claude-code-' + '0' * 16, entry=ident('e', 1),
                                                              start=start, end=end) for start, end in spans]}
        held = {('claude-code-' + '0' * 16, ident('e', 1)): entry}
        gone, touching, empty = item(1, (2, 5)), item(2, (5, 8)), item(3, (3, 3))
        self.assertEqual(forget_plan.shared([gone], [touching, empty]), [])
        (found,) = forget_plan.raw([gone], [touching, empty], [], held)
        self.assertEqual((found['forgotten'], found['kept']), ([[2, 5]], []))
        self.assertEqual(forget_plan.raw([empty], [gone], [], held), [])


if __name__ == '__main__':
    unittest.main()
