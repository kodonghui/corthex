"""TASK-087: curate-2 line edits of the current state on fabricated format-2 stores.

TC-166 to TC-169 and TC-339 to TC-341, and the TASK-087 parts of TC-177 and
TC-378. No model is called; the worker that will apply an answer (TASK-088)
is not wired to a hook or command before the 0.3.0 activation.
"""
import contextlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import (clock, curate_apply, curator_answers, fence_plan, files, format2, history_io, item_types,
                        locks, request_inputs, state_edits, state_io, state_types)
from memory_lib.c2_store import C2Store
from test_memory_fence_plan import PROGRESS
import test_memory_curator_answers as answers
from test_memory_curator_answers import AT, DEVICE, LATER, LOG, answer, change, quote, saved

RUN = 'r_0123456789ac'


def ident(prefix, digit):
    return prefix + '_' + digit * 12


def row(line, part, pos, text, cites, at=AT):
    return {'id': line, 'part': part, 'pos': pos, 'text': text, 'cites': list(cites), 'at': at, 'device': DEVICE}


def edits(change=(), add=(), remove=()):
    return {'change': list(change), 'add': list(add), 'remove': list(remove)}


def changed(line, text, cites=(), changes=(), why='A reason.'):
    return {'line': line, 'text': text, 'cites': list(cites), 'changes': list(changes), 'why': why}


def added(part, text, cites=(), changes=(), after=''):
    return {'part': part, 'after': after, 'text': text, 'cites': list(cites), 'changes': list(changes)}


def removal(line, why='A reason.'):
    return {'line': line, 'why': why}


def maker(*identifiers):
    values = iter(identifiers)

    def make(prefix):
        if prefix != 's':
            raise AssertionError(prefix)
        return next(values)
    return make


class StateEditsTest(unittest.TestCase):
    def setUp(self):
        self.turns = answers.Turns()
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
        (self.project / 'layer/conflicts.json').write_bytes(b'{"candidates":[]}\n')
        self.state_path = self.project / 'layer/state.json'
        self.removed_path = self.project / 'layer/state-removed.json'
        self.history_path = self.project / 'state-history.jsonl'
        self.history_path.write_bytes(b'')
        self.write_state()
        self.store()
        self.memory = C2Store(self.root, expected_device=DEVICE)
        self.deadline = clock.now() + 60
        self.said = self.turns.say('user', 'Keep the four hooks in one script.')
        self.done = self.turns.say('agent', 'One script now serves the four hooks.')

    def store(self, *records):
        for value in records:
            (self.project / 'layer/items' / (value['id'] + '.json')).write_bytes(item_types.item_bytes(value))
        stored = [item_types.parse_item(path.read_bytes()) for path in (self.project / 'layer/items').glob('*.json')]
        (self.project / 'layer/item-list.txt').write_bytes(item_types.item_list_bytes(stored))

    def item(self, item):
        return item_types.parse_item((self.project / 'layer/items' / (item + '.json')).read_bytes())

    def write_state(self, *lines, removed=()):
        self.state_path.write_bytes(state_types.state_bytes({'lines': list(lines)}))
        self.removed_path.write_bytes(state_types.removed_bytes({'removed': list(removed)}))

    def lines(self):
        return {value['id']: value for value in state_types.parse_state(self.state_path.read_bytes())['lines']}

    def order(self, part):
        return [value['id'] for value in sorted((v for v in self.lines().values() if v['part'] == part),
                                                key=lambda v: (v['pos'], v['id']))]

    def history(self):
        return [record.value for record in state_types.parse_history(self.history_path.read_bytes())]

    def progress(self):
        return format2.parse_curation(self.progress_path.read_bytes())

    def proof(self):
        return fence_plan.snapshot(self.progress())

    def view(self):
        return [value['id'] for value in request_inputs.layer(self.project).lines]

    def snapshot(self):
        return {path.relative_to(self.project).as_posix(): path.read_bytes()
                for path in sorted(self.project.rglob('*')) if path.is_file()}

    @contextlib.contextmanager
    def held(self):
        with self.memory.lease(self.project / 'curation.lock', 'curation', self.deadline):
            with self.memory.lease(self.project / 'layer.lock', 'layer', self.deadline):
                yield

    def curate(self, value, items, *, lines=None, make_id=None, at=LATER, run=RUN, expected=None):
        """Check an answer against what its request carried, then apply its item changes and line edits."""
        request = self.view() if lines is None else lines
        sent = curator_answers.sent(items=items, logs=[(LOG, self.turns.entries)], lines=request)
        checked = curator_answers.check_curate(value, sent=sent, device=DEVICE)
        with self.held():
            applied = curate_apply.apply(self.memory, self.project, self.proof(), checked, at, run, self.deadline)
            if applied is not None:
                self.assertEqual(fence_plan.snapshot(applied['progress']), self.proof())
            result = state_edits.apply(self.memory, self.project, self.proof() if expected is None else expected,
                                       checked.state, sent=sent, saved=() if applied is None else applied['saved'],
                                       at=at, run=run, deadline=self.deadline, make_id=make_id)
        return checked, applied, result

    def decision(self, source=None, item=None):
        value = saved('decision', self.said if source is None else source, item=item)
        self.store(value)
        return value

    def test_tc339_one_changed_and_one_added_line_leave_the_others_as_they_were(self):
        rule = self.decision()
        first, last, new = ident('s', 'z'), ident('s', '0'), ident('s', 'm')
        goal = row(ident('s', '1'), 'goal', 0, 'Ship the C2 curator.', [self.said['id']])
        held = row(ident('s', '2'), 'decisions', 0, 'One script serves the four hooks.', [rule['id']])
        written = row(first, 'progress', 1, 'The hook script is written.', [self.done['id']])
        running = row(last, 'progress', 2, 'The Linux checks are running.', [self.done['id']])
        step = row(ident('s', '3'), 'next', 0, 'Test the hooks on Windows.', [self.done['id']])
        self.write_state(goal, held, written, running, step)
        later = self.turns.say('agent', 'The Linux checks pass; Windows comes next.')
        _, applied, result = self.curate(answer(state=edits(
            change=[changed(step['id'], 'Test the hooks on Windows and macOS.', [later['id']], why='macOS joined.')],
            add=[added('progress', 'The Linux checks pass.', [later['id']], after=first)])), [rule],
            make_id=maker(new))
        self.assertIsNone(applied)
        self.assertEqual((result['state'], result['held'], result['dropped'], result['added']),
                         ('new', None, {}, (new,)))
        lines = self.lines()
        for unnamed in (goal, held, written):
            self.assertEqual(lines[unnamed['id']], unnamed)
        # The add needs room between positions 1 and 2: the next line moves, keeping its text, citations and time.
        self.assertEqual(lines[last], dict(running, pos=3))
        self.assertEqual(lines[new], row(new, 'progress', 2, 'The Linux checks pass.', [later['id']], at=LATER))
        self.assertEqual(lines[step['id']], dict(step, text='Test the hooks on Windows and macOS.',
                                                  cites=[later['id']], at=LATER))
        self.assertEqual(self.order('progress'), [first, new, last])
        generation = PROGRESS['fence']['generation'] + 1
        self.assertEqual([(r['line'], r['op'], r['why'], r['part'], r['pos'], r['text'], r['cites'], r['generation'],
                           r['run']) for r in self.history()],
                         [(last, 'changed', 'position', 'progress', 2, running['text'], running['cites'], generation,
                           RUN),
                          (step['id'], 'changed', 'macOS joined.', 'next', 0, step['text'], step['cites'], generation,
                           RUN)])
        revisions = self.progress()['fence']['revisions']
        self.assertEqual({key: value for key, value in revisions.items() if key.startswith('line:')},
                         {'line:' + line: generation for line in (last, step['id'], new)})
        self.assertEqual(revisions['run:' + RUN], generation)
        self.assertEqual(json.loads(self.removed_path.read_bytes()), {'removed': []})

    def test_tc340_an_answer_without_line_edits_keeps_the_state_byte_for_byte(self):
        rule = self.decision()
        self.write_state(row(ident('s', '1'), 'decisions', 0, 'One script serves the hooks.', [rule['id']]),
                         row(ident('s', '2'), 'blockers', 0, 'Windows CI is slow.', [self.done['id']]))
        files = self.snapshot()
        _, applied, result = self.curate(answer(), [rule])
        self.assertIsNone(applied)
        self.assertEqual(result, {'state': 'kept', 'held': None, 'dropped': {}, 'added': (), 'cut': (), 'stale': (),
                                  'lines': (), 'progress': None})
        self.assertEqual(self.snapshot(), files)

    def test_tc341_unknown_and_twice_named_lines_are_dropped_and_counted(self):
        rule = self.decision()
        kept = row(ident('s', '1'), 'progress', 0, 'The hook script is written.', [self.done['id']])
        other = row(ident('s', '2'), 'progress', 1, 'Not in the request.', [self.done['id']])
        self.write_state(kept, other)
        files = self.snapshot()
        foreign = ident('s', 'f')
        checked, _, result = self.curate(answer(state=edits(
            change=[changed(foreign, 'A line nobody sent.', [self.done['id']]),
                    changed(kept['id'], 'Changed once.', [self.done['id']]),
                    changed(other['id'], 'Changed, but not sent.', [self.done['id']])],
            remove=[removal(kept['id'])])), [rule], lines=[kept['id']])
        self.assertEqual(result['dropped'], {'not-in-request': 2, 'duplicate': 2})
        self.assertEqual(result['state'], 'kept')
        self.assertEqual(self.snapshot(), files)

    def test_tc166_a_line_that_cites_nothing_known_is_not_written(self):
        rule = self.decision()
        line = row(ident('s', '1'), 'progress', 0, 'The hook script is written.', [self.done['id']])
        self.write_state(line)
        unsent = saved('fact', self.done)
        self.store(unsent)
        files = self.snapshot()
        _, _, result = self.curate(answer(state=edits(
            add=[added('progress', 'Cites nothing.'),
                 added('progress', 'Cites an item the request did not carry.', [unsent['id']]),
                 added('progress', 'Cites an unknown entry.', [ident('e', '7')]),
                 added('progress', 'Cites a change the answer does not have.', changes=[1]),
                 added('progress', 'Cites change number 0.', changes=[0])],
            change=[changed(line['id'], 'Now cites nothing.')])), [rule])
        self.assertEqual(result['dropped'], {'cites': 6})
        self.assertEqual(self.lines(), {line['id']: line})
        self.assertEqual(self.snapshot(), files)

    def test_tc167_a_decision_in_force_needs_a_current_decision_item(self):
        tabs = self.turns.say('user', 'Use tabs in the files.')
        cache = self.turns.say('user', 'Keep the cache on.')
        first, second = self.decision(tabs), self.decision(cache)
        unnamed = row(ident('s', '1'), 'decisions', 0, 'The files use tabs.', [first['id']])
        named = row(ident('s', '2'), 'decisions', 1, 'The cache stays on.', [second['id']])
        progress = row(ident('s', '3'), 'progress', 0, 'Tabs are applied.', [first['id']])
        self.write_state(unnamed, named, progress)
        spaces = self.turns.say('user', 'Use spaces instead of tabs.')
        off = self.turns.say('user', 'Turn the cache off.')
        _, applied, result = self.curate(answer(
            change(quote(spaces, 'Use spaces instead of tabs.'), action='replace', targets=[first['id']],
                   kind='decision', title='Use spaces'),
            change(quote(off, 'Turn the cache off.'), action='replace', targets=[second['id']], kind='decision',
                   title='Cache off'),
            state=edits(change=[changed(named['id'], 'The cache stays on, still.', [first['id']])],
                        add=[added('decisions', 'Tabs again.', [second['id']]),
                             added('decisions', 'Spaces, not tabs.', changes=[1])])),
            [first, second], make_id=maker(ident('s', '9')))
        (_, spaces_item), _ = applied['saved']
        self.assertEqual([self.item(i)['status'] for i in (first['id'], second['id'])], ['superseded'] * 2)
        self.assertEqual(result['dropped'], {'decision': 2})
        self.assertEqual(result['stale'], (unnamed['id'], named['id']))
        # A progress line may still cite the superseded item.
        self.assertEqual(sorted(self.lines()), sorted([progress['id'], ident('s', '9')]))
        self.assertEqual(self.lines()[ident('s', '9')]['cites'], [spaces_item])
        self.assertEqual(self.view(), [ident('s', '9'), progress['id']])
        self.assertEqual([(r['line'], r['op'], r['why'], r['text']) for r in self.history()],
                         [(unnamed['id'], 'stale', 'stale', unnamed['text']),
                          (named['id'], 'stale', 'stale', named['text'])])
        markers = json.loads(self.removed_path.read_bytes())['removed']
        self.assertEqual([(m['id'], m['kind'], m['at']) for m in markers],
                         [(unnamed['id'], 'edit', LATER), (named['id'], 'edit', LATER)])

    def test_tc168_edits_of_5000_bytes_are_cut_below_3000_in_whole_lines(self):
        rule = self.decision()
        cite = [self.done['id']]
        goal = row(ident('s', '0'), 'goal', 0, 'g' * 60, [self.said['id']])
        held = row(ident('s', '1'), 'decisions', 0, 'd' * 60, [rule['id']])
        progress = [row('s_' + '2' * 11 + str(n), 'progress', n, str(n) * 300, cite) for n in range(6)]
        blockers = [row('s_' + '3' * 11 + str(n), 'blockers', n, 'b' * 200, cite) for n in range(2)]
        steps = [row('s_' + '4' * 11 + str(n), 'next', n, 'n' * 150, cite) for n in range(4)]
        before = [goal, held] + progress + blockers + steps
        self.write_state(*before)
        self.assertEqual(sum(len(v['text'].encode()) for v in before), 2920)
        new = (ident('s', 'x'), ident('s', 'y'))
        _, _, result = self.curate(answer(state=edits(
            change=[changed(progress[0]['id'], 'p' * 880, cite)],
            add=[added('progress', 'x' * 900, cite, after=progress[2]['id']), added('next', 'y' * 600, cite)])),
            [rule], make_id=maker(*new))
        lines = self.lines()
        self.assertLess(sum(len(v['text'].encode()) for v in lines.values()), 3000)
        # One line from the end of each part in turn, next actions first; the answer's own lines go last.
        order = [steps[3], blockers[1], progress[5], held, goal, steps[2], blockers[0], progress[4], steps[1],
                 progress[3], steps[0]]
        self.assertEqual(result['cut'], tuple(v['id'] for v in order))
        self.assertEqual((result['state'], result['added'], result['stale']), ('cut', new, ()))
        self.assertEqual(sorted(lines), sorted([progress[0]['id'], progress[1]['id'], progress[2]['id']] + list(new)))
        self.assertEqual(lines[progress[0]['id']]['text'], 'p' * 880)
        self.assertEqual(self.order('progress'), [progress[0]['id'], progress[1]['id'], progress[2]['id'], new[0]])
        records = {r['line']: r for r in self.history()}
        self.assertEqual({line: (r['op'], r['why']) for line, r in records.items()},
                         dict({v['id']: ('cut', 'cut') for v in order},
                              **{progress[0]['id']: ('changed', 'A reason.')}))
        for value in order:
            self.assertEqual((records[value['id']]['text'], records[value['id']]['cites']), (value['text'],
                                                                                           value['cites']))
        self.assertEqual(self.progress()['consolidation'], {'failures': 0, 'due': LATER})
        self.assertEqual(fence_plan.snapshot(result['progress']), self.proof())

    def test_cut_falls_on_the_answers_own_lines_only_after_every_other_line(self):
        rule = self.decision()
        cite = [self.done['id']]
        old = row(ident('s', '1'), 'progress', 0, 'o' * 100, cite)
        named = row(ident('s', '2'), 'next', 0, 'c' * 100, cite)
        self.write_state(old, named)
        new = (ident('s', 'x'), ident('s', 'y'))
        _, _, result = self.curate(answer(state=edits(
            change=[changed(named['id'], 'c' * 1500, cite)],
            add=[added('progress', 'x' * 1000, cite), added('blockers', 'y' * 1000, cite)])), [rule],
            make_id=maker(*new))
        # The unnamed line goes, then the changed one; the two adds then fit.
        self.assertEqual((result['cut'], result['added']), ((old['id'], named['id']), new))
        self.assertEqual(sorted(self.lines()), sorted(new))
        self.assertEqual([(r['line'], r['op'], r['text']) for r in self.history()],
                         [(old['id'], 'cut', old['text']), (named['id'], 'cut', named['text'])])
        # When the answer's own lines alone pass the limit, every other line goes first, and the add
        # that is cut then leaves no record.
        self.assertEqual(self.progress()['consolidation']['due'], LATER)
        new = (ident('s', 'v'), ident('s', 'w'))
        _, _, result = self.curate(answer(state=edits(
            add=[added('next', 'v' * 1600, cite), added('next', 'w' * 1600, cite)])), [rule], make_id=maker(*new),
            at='2026-11-06T00:00:00.000Z')
        self.assertEqual((result['state'], result['cut'], result['added']),
                         ('cut', (ident('s', 'y'), ident('s', 'x')), new[:1]))
        self.assertEqual(list(self.lines()), [new[0]])
        self.assertEqual([(r['line'], r['op']) for r in self.history()][2:],
                         [(ident('s', 'x'), 'cut'), (ident('s', 'y'), 'cut')])
        # Consolidation was already due from the earlier cut, and stays due from then.
        self.assertEqual(self.progress()['consolidation']['due'], LATER)

    def test_tc169_an_unnamed_blocker_citing_an_earlier_entry_stays(self):
        rule = self.decision()
        earlier = 'e_' + '5' * 12
        blocker = row(ident('s', '1'), 'blockers', 0, 'Windows CI is slow.', [earlier], at='2026-10-30T01:00:00.000Z')
        line = row(ident('s', '2'), 'progress', 0, 'The hook script is written.', [self.done['id']])
        self.write_state(blocker, line)
        self.assertNotIn(earlier, [entry['id'] for entry in self.turns.entries])
        _, _, result = self.curate(answer(state=edits(
            change=[changed(line['id'], 'The hook script is tested.', [self.done['id'], earlier])])), [rule])
        self.assertEqual((result['state'], result['dropped']), ('new', {}))
        self.assertEqual(self.lines()[blocker['id']], blocker)
        # An entry that the request's state already cites can be cited without its text.
        self.assertEqual(self.lines()[line['id']]['cites'], [self.done['id'], earlier])

    def test_tc177_part_stage_06_curate_examples_edit_the_state(self):
        examples = json.loads((answers.API / 'memory-examples.json').read_text(encoding='utf-8'))['curate']['valid']
        preference, decision = 'i_5c8e1h4j7m0p', 'i_7f3k2m9q4x1v'
        line = row('s_4n8q2v6x0z3b', 'progress', 0, 'Write the hook script.', ['e_5h2j8n3p0r6t'])
        new = [ident('s', digit) for digit in 'abc']
        for name, value in sorted(examples.items()):
            with self.subTest(example=name):
                self.setUp()
                self.turns.say('user', "Let's keep the four hooks in one script.", entry='e_5h2j8n3p0r6t')
                self.turns.say('agent', 'Done: one script now serves the four hooks, by name.', entry='e_8m1k4r7t2w5y')
                korean = self.turns.say('user', 'Answer me in Korean from now on.', entry='e_6b9e2h5k8n1r')
                self.turns.say('user', '노션 표는 모두 데이터베이스로 만들어 주세요.', entry='e_3d6g9k2n5q8t')
                items = [saved('preference', korean, 'Answer me in Korean', item=preference),
                         saved('decision', korean, 'Korean', item=decision)]
                self.store(*items)
                self.write_state(line)
                _, applied, result = self.curate(value, items, make_id=maker(*new))
                self.assertEqual(result['dropped'], {})
                lines = self.lines()
                if name in ('add-a-decision', 'possible-disagreement'):
                    item = applied['saved'][0][1]
                    self.assertEqual({(v['part'], v['text'], tuple(v['cites'])) for i, v in lines.items() if i in new},
                                     {('decisions', 'One script serves the four hooks.', (item,)),
                                      ('progress', 'The hook script is written.', ('e_8m1k4r7t2w5y', item)),
                                      ('next', 'Test the four hooks on Windows.', ('e_8m1k4r7t2w5y',))})
                    self.assertEqual(lines[line['id']], line)
                    self.assertEqual(self.history(), [])
                elif name == 'remove-a-line':
                    self.assertEqual(lines, {})
                    self.assertEqual([(r['op'], r['why'], r['text']) for r in self.history()],
                                     [('removed', 'The user finished this work.', line['text'])])
                elif name == 'change-one-line':
                    self.assertEqual(lines[line['id']], dict(line, text='The hook checks now pass.',
                                                             cites=['e_8m1k4r7t2w5y'], at=LATER))
                    self.assertEqual([(r['op'], r['why'], r['text']) for r in self.history()],
                                     [('changed', 'The new turn completes this work.', line['text'])])
                else:
                    self.assertEqual((result['state'], lines), ('kept', {line['id']: line}))

    def test_tc378_part_a_failed_history_append_keeps_the_state_and_the_item_changes(self):
        tabs = self.turns.say('user', 'Use tabs in the files.')
        rule = self.decision(tabs)
        stale = row(ident('s', '1'), 'decisions', 0, 'The files use tabs.', [rule['id']])
        line = row(ident('s', '2'), 'progress', 0, 'Tabs are applied.', [rule['id']])
        self.write_state(stale, line)
        state_files = self.state_path.read_bytes(), self.removed_path.read_bytes()
        spaces = self.turns.say('user', 'Use spaces instead of tabs.')
        value = answer(change(quote(spaces, 'Use spaces instead of tabs.'), action='replace', targets=[rule['id']],
                              kind='decision', title='Use spaces'),
                       state=edits(add=[added('progress', 'Spaces are next.', changes=[1])]))
        real = os.write
        history = self.history_path.stat().st_ino

        def failing(fd, data):
            if os.fstat(fd).st_ino == history:
                raise OSError(28, 'No space left on device')
            return real(fd, data)
        with mock.patch.object(os, 'write', side_effect=failing):
            _, applied, result = self.curate(value, [rule], make_id=maker(ident('s', '9')))
        self.assertEqual((result['state'], result['held'], result['added']), ('kept', 'AppendFailed', ()))
        self.assertEqual(self.item(rule['id'])['superseded_by'], applied['saved'][0][1])
        self.assertEqual((self.state_path.read_bytes(), self.removed_path.read_bytes()), state_files)
        self.assertEqual(self.history_path.read_bytes(), b'')
        # The valid view leaves the stale decision out; the progress line stays.
        self.assertEqual(self.view(), [line['id']])
        self.assertEqual(fence_plan.snapshot(result['progress']), self.proof())
        # The next answer, with no line edits, removes the stale line.
        _, applied, result = self.curate(answer(), [self.item(applied['saved'][0][1])])
        self.assertIsNone(applied)
        self.assertEqual((result['state'], result['stale']), ('new', (stale['id'],)))
        self.assertEqual([(r['line'], r['op']) for r in self.history()], [(stale['id'], 'stale')])
        self.assertEqual(sorted(self.lines()), [line['id']])

    def test_a_pure_add_needs_no_history_and_applies_with_damaged_history(self):
        rule = self.decision()
        line = row(ident('s', '1'), 'progress', 0, 'The hook script is written.', [self.done['id']])
        self.write_state(line)
        self.history_path.write_bytes(b'{"damaged"')
        _, _, result = self.curate(answer(state=edits(add=[added('progress', 'Tests pass.', [self.done['id']],
                                                                 after=line['id'])])),
                                   [rule], make_id=maker(ident('s', '9')))
        self.assertEqual((result['state'], result['added']), ('new', (ident('s', '9'),)))
        self.assertEqual(self.order('progress'), [line['id'], ident('s', '9')])
        self.assertEqual(self.history_path.read_bytes(), b'{"damaged"')
        # A change needs the earlier text in history, so the damaged file keeps the state.
        files = self.state_path.read_bytes()
        _, _, result = self.curate(answer(state=edits(change=[changed(line['id'], 'Tested.', [self.done['id']])])),
                                   [rule])
        self.assertEqual((result['state'], result['held']), ('kept', 'RestoreNeeded'))
        self.assertEqual(self.state_path.read_bytes(), files)

    def test_edits_that_do_not_fit_are_dropped_and_adds_find_their_place(self):
        rule = self.decision()
        cite = [self.done['id']]
        a = row(ident('s', '1'), 'progress', 0, 'First.', cite)
        b = row(ident('s', '2'), 'progress', 5, 'Second.', cite)
        c = row(ident('s', '3'), 'next', 0, 'A next step.', cite)
        self.write_state(a, b, c)
        new = [ident('s', digit) for digit in 'tvwxyz']
        _, _, result = self.curate(answer(state=edits(
            change=[changed(a['id'], 'Two\nlines.', cite), changed(b['id'], '   ', cite),
                    changed(c['id'], 'A reason too long.', cite, why='w' * 201)],
            remove=[removal(c['id'], why='가' * 67)],
            add=[added('progress', 'At the start.', cite), added('progress', 'Also at the start.', cite),
                 added('progress', 'After the first.', cite, after=a['id']),
                 added('progress', 'After a line of another part.', cite, after=c['id']),
                 added('progress', 'After an unknown line.', cite, after=ident('s', 'f')),
                 added('next', 'Before the next step.', cite), added('goal', 'Two lines.', cite)])),
            [rule], make_id=maker(*new))
        self.assertEqual(result['dropped'], {'duplicate': 2, 'shape': 3})
        self.assertEqual(self.order('progress'), [new[0], new[1], a['id'], new[2], b['id'], new[3], new[4]])
        self.assertEqual(self.order('next'), [new[5], c['id']])
        positions = {line: value['pos'] for line, value in self.lines().items()}
        # Room comes from free positions: no existing line moves.
        self.assertEqual((positions[a['id']], positions[b['id']], positions[c['id']]), (0, 5, 0))
        self.assertEqual(self.history(), [])

    def test_reasons_are_checked_in_bytes_and_a_change_to_the_same_text_is_no_edit(self):
        rule = self.decision()
        cite = [self.done['id']]
        a = row(ident('s', '1'), 'progress', 0, 'First.', cite)
        b = row(ident('s', '2'), 'progress', 1, 'Second.', cite)
        c = row(ident('s', '3'), 'next', 0, 'Third.', cite)
        self.write_state(a, b, c)
        _, _, result = self.curate(answer(state=edits(
            change=[changed(a['id'], 'First, changed.', cite, why='가' * 66 + 'ab'),
                    changed(b['id'], 'Second.', cite, why='no change')],
            remove=[removal(c['id'], why='가' * 67)])), [rule])
        self.assertEqual(result['dropped'], {'limit': 1})
        self.assertEqual(self.lines()[a['id']]['text'], 'First, changed.')
        self.assertEqual(self.lines()[b['id']], b)
        self.assertEqual([(r['line'], r['why']) for r in self.history()], [(a['id'], '가' * 66 + 'ab')])

    def test_lines_hidden_for_their_owners_are_left_alone(self):
        rule = self.decision()
        gone = saved('fact', self.done)
        tombstone = {'item': gone['id'], 'project': 'sample', 'at': AT, 'device': DEVICE,
                     'quotes': [{key: gone['quotes'][0][key] for key in ('device', 'entry', 'log', 'start', 'end')}]}
        (self.project / 'layer/tombstones' / (gone['id'] + '.json')).write_bytes(
            json.dumps(tombstone).encode('utf-8'))
        private = row(ident('s', '1'), 'progress', 1, 'Cites a forgotten item.', [gone['id']])
        residue = row(ident('s', '2'), 'progress', 2, 'Already removed.', [self.done['id']])
        visible = row(ident('s', '3'), 'progress', 1, 'Visible.', [self.said['id']])
        marker = {'id': residue['id'], 'at': AT, 'device': DEVICE, 'kind': 'edit'}
        self.write_state(private, residue, visible, removed=[marker])
        self.assertEqual(self.view(), [visible['id']])
        new = ident('s', '9')
        _, _, result = self.curate(answer(state=edits(
            change=[changed(private['id'], 'x', [self.said['id']]), changed(residue['id'], 'y', [self.said['id']])],
            add=[added('progress', 'After the forgotten one.', [self.said['id']], after=private['id'])])),
            [rule], lines=[visible['id'], private['id'], residue['id']], make_id=maker(new))
        self.assertEqual(result['dropped'], {'not-in-request': 2})
        lines = self.lines()
        self.assertEqual((lines[private['id']], lines[residue['id']], lines[visible['id']]),
                         (private, residue, visible))
        self.assertEqual(lines[new]['pos'], 2)
        self.assertEqual(json.loads(self.removed_path.read_bytes())['removed'], [marker])
        self.assertEqual(self.history(), [])

    def test_code_made_line_ids_never_reuse_a_present_or_removed_line(self):
        rule = self.decision()
        line = row(ident('s', '1'), 'progress', 0, 'The hook script is written.', [self.done['id']])
        marker = {'id': ident('s', '8'), 'at': AT, 'device': DEVICE, 'kind': 'edit'}
        self.write_state(line, removed=[marker])
        files = self.snapshot()
        for reused in (line['id'], marker['id']):
            with self.subTest(reused=reused), self.assertRaisesRegex(ValueError, 'code-made ID collision'):
                self.curate(answer(state=edits(add=[added('next', 'New.', [self.done['id']])])), [rule],
                            make_id=maker(reused))
        self.assertEqual(self.snapshot(), files)

    def test_a_stale_proof_or_a_lost_lease_applies_nothing(self):
        rule = self.decision()
        line = row(ident('s', '1'), 'progress', 0, 'The hook script is written.', [self.done['id']])
        self.write_state(line)
        files = self.snapshot()
        value = answer(state=edits(change=[changed(line['id'], 'Changed.', [self.done['id']])]))
        stale = fence_plan.snapshot(dict(PROGRESS, applies=PROGRESS['applies'] + 1))
        with self.assertRaises(fence_plan.Stale):
            self.curate(value, [rule], expected=stale)
        self.assertEqual(self.snapshot(), files)
        sent = curator_answers.sent(items=[rule], logs=[(LOG, self.turns.entries)], lines=[line['id']])
        checked = curator_answers.check_curate(value, sent=sent, device=DEVICE)
        with self.memory.lease(self.project / 'layer.lock', 'layer', self.deadline), self.assertRaises(locks.LostLock):
            state_edits.apply(self.memory, self.project, self.proof(), checked.state, sent=sent, saved=(), at=LATER,
                              run=RUN, deadline=self.deadline)
        self.assertEqual(self.snapshot(), files)

    def test_items_changed_after_the_plan_refuse_the_publication(self):
        rule = self.decision()
        line = row(ident('s', '1'), 'progress', 0, 'The hook script is written.', [self.done['id']])
        self.write_state(line)
        files = self.snapshot()
        value = answer(state=edits(change=[changed(line['id'], 'Changed.', [self.done['id']])]))
        real = state_io.apply

        def drifting(*args, **kwargs):
            # An item file changes after the plan read it and before the publisher's catalogue.
            self.store(dict(rule, title='Edited elsewhere'))
            return real(*args, **kwargs)
        # The publisher's first check finds it before anything is reserved or appended.
        with mock.patch.object(state_io, 'apply', side_effect=drifting), self.assertRaises(fence_plan.Stale):
            self.curate(value, [rule])
        self.assertEqual(self.progress(), PROGRESS)
        self.assertEqual((self.state_path.read_bytes(), self.history_path.read_bytes()),
                         (files['layer/state.json'], b''))

    def plan(self, value, lines, items=(), request=None, saved=(), removed=()):
        sent = curator_answers.sent(items=items, logs=[(LOG, self.turns.entries)],
                                    lines=[v['id'] for v in lines] if request is None else request)
        return state_edits.plan(value, state={'lines': list(lines)}, removed={'removed': list(removed)},
                                items={v['id']: v for v in items}, private=frozenset(), sent=sent, saved=saved,
                                at=LATER, device=DEVICE, make_id=maker(ident('s', '9')))

    def test_the_text_of_the_lines_stays_strictly_below_3000_bytes(self):
        cite = [self.done['id']]
        for size, cut in ((2999, ()), (3000, (ident('s', '2'),))):
            with self.subTest(size=size):
                lines = [row(ident('s', '1'), 'goal', 0, 'g' * 1000, cite),
                         row(ident('s', '2'), 'next', 0, 'n' * (size - 1000), cite)]
                planned = self.plan(edits(), lines)
                self.assertEqual(planned.cut, cut)
                self.assertEqual([o['op'] for o in (planned.proposal or {'operations': []})['operations']],
                                 ['cut'] * len(cut))
        # A state that a merge left over the limit is cut with no line edit.
        lines = [row(ident('s', '1'), 'goal', 0, 'g' * 3001, cite)]
        self.assertEqual(self.plan(edits(), lines).cut, (ident('s', '1'),))

    def test_a_stale_line_outside_the_request_is_still_removed(self):
        tabs = self.turns.say('user', 'Use tabs in the files.')
        rule = saved('decision', tabs, status='superseded')
        rule['superseded_by'], rule['changed'] = 'i_' + '9' * 12, LATER
        stale = row(ident('s', '1'), 'decisions', 0, 'Tabs.', [rule['id']])
        kept = row(ident('s', '2'), 'progress', 0, 'Kept.', [self.done['id']])
        planned = self.plan(edits(change=[changed(stale['id'], 'Named, but not sent.', [self.done['id']])]),
                            [stale, kept], items=[rule], request=[kept['id']])
        self.assertEqual((planned.stale, planned.dropped), ((stale['id'],), {'not-in-request': 1}))
        self.assertEqual(planned.proposal['operations'], [{'id': stale['id'], 'op': 'stale', 'why': 'stale'}])

    def test_only_a_failure_before_any_publication_holds_the_state(self):
        def failure(error, attempted=()):
            try:
                raise state_io.PublicationFailed(attempted, (), None, True) from error
            except state_io.PublicationFailed as raised:
                return raised

        def chained(error, cause):
            error.__cause__ = cause
            return error
        held = state_edits._held
        self.assertEqual(held(failure(history_io.AppendFailed())), 'AppendFailed')
        self.assertEqual(held(failure(chained(history_io.AppendFailed(), OSError(28, 'full')))), 'AppendFailed')
        self.assertEqual(held(failure(files.RestoreNeeded())), 'RestoreNeeded')
        self.assertEqual(held(failure(PermissionError(13, 'denied'))), 'PermissionError')
        for error in (chained(history_io.AppendFailed(), fence_plan.Stale()), locks.LostLock(), fence_plan.Stale(),
                      ValueError('state history binding mismatch')):
            with self.subTest(error=error):
                self.assertIsNone(held(failure(error)))
        self.assertIsNone(held(failure(history_io.AppendFailed(), attempted=('removed',))))

    def test_positions_keep_existing_lines_while_the_order_allows(self):
        positions = state_edits._positions
        self.assertEqual(positions(['n1', 'n2'], {}), {'n1': 0, 'n2': 1})
        self.assertEqual(positions(['n1', 'n2', 'a'], {'a': 5}), {'n1': 3, 'n2': 4, 'a': 5})
        self.assertEqual(positions(['a', 'n', 'b'], {'a': 1, 'b': 2}), {'a': 1, 'n': 2, 'b': 3})
        self.assertEqual(positions(['a', 'n', 'b'], {'a': 1, 'b': 4}), {'a': 1, 'n': 2, 'b': 4})
        # Equal positions sort by ID; a kept tie needs the later line to have the larger ID.
        self.assertEqual(positions(['s_b', 's_a'], {'s_b': 1, 's_a': 2}), {'s_b': 1, 's_a': 2})
        self.assertEqual(positions(['s_a', 's_b'], {'s_a': 1, 's_b': 1}), {'s_a': 1, 's_b': 1})
        self.assertEqual(positions(['s_b', 's_a'], {'s_b': 1, 's_a': 1}), {'s_b': 1, 's_a': 2})


if __name__ == '__main__':
    unittest.main()
