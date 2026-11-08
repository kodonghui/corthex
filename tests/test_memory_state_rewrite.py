"""TASK-089 and TASK-090: the consolidation's changes to the current state, without a store.

The pure parts of TC-187, TC-190 and TC-342: recited lines after a merge, and
the last answer's kept, changed, added, removed, dropped, stale and cut lines.
No model is called; the worker that applies them is not wired to a hook or
command before the 0.3.0 activation.
"""
import sys
import unittest

from _common import ROOT
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import state_rewrite, state_types
from test_memory_curator_answers import AT, DEVICE, LATER, Turns, saved
from test_memory_state_edits import ident, maker, row

PARTS = state_types.PARTS
SECRET = ident('i', '7')


def line(keeps, text, cites, changes=()):
    """A line of a state-1 answer; `keeps` is '' for an added line."""
    return {'keeps': keeps, 'text': text, 'cites': list(cites), 'changes': list(changes)}


class StateRewriteTest(unittest.TestCase):
    def setUp(self):
        turns = Turns()
        self.said = turns.say('user', 'Keep the four hooks in one script.')
        self.done = turns.say('agent', 'One script now serves the four hooks.')
        self.rule = saved('decision', self.said)
        self.fact = saved('fact', self.done)
        self.items = {value['id']: value for value in (self.rule, self.fact)}

    def rewrite(self, lines, request=None, removed=(), make=None, **parts):
        answer = {part: list(parts.get(part, ())) for part in PARTS}
        return state_rewrite.rewrite(answer, state={'lines': list(lines)}, removed={'removed': list(removed)},
                                     items=self.items, private=frozenset([SECRET]),
                                     lines=[value['id'] for value in lines] if request is None else request,
                                     listed=list(self.items), at=LATER, device=DEVICE,
                                     make_id=make or maker(ident('s', '9')))

    def operations(self, planned):
        return [(value['id'], value['op'], value['why']) for value in planned.proposal['operations']]

    def test_kept_lines_keep_their_ids_and_left_out_lines_are_removed(self):
        rule, fact, new = self.rule['id'], self.fact['id'], ident('s', '9')
        goal = row(ident('s', '1'), 'goal', 0, 'Ship the plugin.', [fact])
        cited = row(ident('s', '2'), 'decisions', 0, 'One script.', [rule])
        step = row(ident('s', '3'), 'progress', 0, 'Half done.', [fact])
        moved = row(ident('s', '4'), 'progress', 1, 'Test the hooks.', [fact])
        planned = self.rewrite([goal, cited, step, moved],
                               goal=[line(goal['id'], goal['text'], [fact])],
                               decisions=[line(cited['id'], 'One script serves the four hooks.', [rule, rule])],
                               next=[line(moved['id'], moved['text'], [fact]), line('', 'Ship it.', [fact])])
        # A line whose text and citations stay keeps its time, even in another part; a changed one takes the run's.
        self.assertEqual(planned.proposal['state']['lines'],
                         [goal, dict(cited, text='One script serves the four hooks.', at=LATER),
                          dict(moved, part='next', pos=0), row(new, 'next', 1, 'Ship it.', [fact], at=LATER)])
        self.assertEqual(self.operations(planned), [(cited['id'], 'changed', 'consolidation'),
                                                    (moved['id'], 'changed', 'position'), (new, 'added', ''),
                                                    (step['id'], 'removed', 'consolidation')])
        self.assertEqual((planned.added, planned.removed, planned.cut, planned.cut_adds, planned.stale,
                          planned.dropped), ((new,), (step['id'],), (), 0, (), {}))

    def test_tc190_a_dropped_line_counts_once_and_keeps_the_line_it_names(self):
        fact = self.fact['id']
        one = row(ident('s', '1'), 'progress', 0, 'Step one.', [fact])
        two = row(ident('s', '2'), 'progress', 1, 'Step two.', [fact])
        hidden = row(ident('s', '3'), 'blockers', 0, 'A private blocker.', [SECRET])
        planned = self.rewrite(
            [one, two, hidden], request=[one['id'], two['id']],
            progress=[line(hidden['id'], 'Shown again.', [fact]),  # not-in-request: hidden for privacy
                      line(ident('s', '8'), 'No such line.', [fact]),  # not-in-request
                      line(one['id'], 'Step one, first.', [fact]),  # duplicate
                      line(one['id'], 'Step one, again.', [fact]),  # duplicate
                      line(two['id'], 'Two\nlines.', [fact])],  # shape
            next=[line('', ' ', [fact]),  # shape
                  line('', 'Cites an item that the request did not list.', [ident('i', '6')]),  # cites
                  line('', 'Cites an entry that no line of the request cites.', [self.said['id']]),  # cites
                  line('', 'Names an item change.', [fact], changes=[1]),  # cites
                  line('', 'Cites nothing.', [])],  # cites
            decisions=[line('', 'A decision line without a decision item.', [fact])])  # decision
        self.assertEqual(planned.dropped, {'not-in-request': 2, 'duplicate': 2, 'shape': 2, 'cites': 4,
                                           'decision': 1})
        # Every line stays as it was: nothing to publish.
        self.assertEqual((planned.proposal, planned.added, planned.removed), (None, (), ()))

    def test_a_decision_line_without_a_current_decision_goes_as_stale_and_a_private_line_stays(self):
        old = saved('decision', self.said, status='superseded')
        old.update(superseded_by=self.rule['id'], changed=LATER)
        self.items[old['id']] = old
        stale = row(ident('s', '1'), 'decisions', 0, 'Tabs.', [old['id']])
        kept = row(ident('s', '2'), 'decisions', 1, 'One script.', [self.rule['id']])
        private = row(ident('s', '3'), 'goal', 0, 'A private goal.', [SECRET])
        # The request carries only the visible line; five empty parts keep it too.
        for parts in ({'decisions': [line(kept['id'], kept['text'], [self.rule['id']])]}, {}):
            with self.subTest(parts=sorted(parts)):
                planned = self.rewrite([stale, kept, private], request=[kept['id']], **parts)
                self.assertEqual(planned.proposal['state']['lines'], [private, kept])
                self.assertEqual(self.operations(planned), [(stale['id'], 'stale', 'stale')])
                self.assertEqual((planned.stale, planned.removed), ((stale['id'],), ()))

    def test_five_empty_parts_keep_the_state(self):
        value = row(ident('s', '1'), 'progress', 0, 'Half done.', [self.fact['id']])
        planned = self.rewrite([value])
        self.assertEqual((planned.proposal, planned.dropped, planned.added, planned.removed, planned.cut),
                         (None, {}, (), (), ()))

    def test_lines_that_stay_are_cut_first_then_changed_then_added_ones(self):
        fact = self.fact['id']
        same = row(ident('s', '1'), 'progress', 0, 'u' * 1000, [fact])
        changed = row(ident('s', '2'), 'next', 0, 'c' * 1000, [fact])
        planned = self.rewrite([same, changed], progress=[line(same['id'], same['text'], [fact])],
                               next=[line(changed['id'], 'd' * 1000, [fact]), line('', 'a' * 1000, [fact])])
        new = ident('s', '9')
        self.assertEqual(self.operations(planned), [(changed['id'], 'changed', 'consolidation'), (new, 'added', ''),
                                                    (same['id'], 'cut', 'cut')])
        self.assertEqual((planned.cut, planned.cut_adds, planned.added), ((same['id'],), 0, (new,)))
        # An added line that is cut leaves no history.
        added = [ident('s', digit) for digit in '678']
        planned = self.rewrite([], next=[line('', text * 1000, [fact]) for text in 'abc'], make=maker(*added))
        self.assertEqual(self.operations(planned), [(added[0], 'added', ''), (added[1], 'added', '')])
        self.assertEqual((planned.cut, planned.cut_adds, planned.added), ((), 1, tuple(added[:2])))
        self.assertLess(sum(len(value['text']) for value in planned.proposal['state']['lines']), 3000)

    def test_a_code_made_id_that_a_line_or_a_removal_marker_holds_is_refused(self):
        value = row(ident('s', '1'), 'progress', 0, 'Half done.', [self.fact['id']])
        marker = state_types.removal_marker(ident('s', '5'), AT, DEVICE, 'edit')
        for taken in (value['id'], marker['id']):
            with self.subTest(taken=taken), self.assertRaisesRegex(ValueError, 'collision'):
                self.rewrite([value], removed=[marker], make=maker(taken),
                             next=[line('', 'Ship it.', [self.fact['id']])])

    def test_tc187_recite_follows_merges_and_leaves_hidden_lines(self):
        first, second = (saved('fact', source, status='superseded') for source in (self.done, self.said))
        merged = saved('fact', self.done)
        merged['merges'] = [first['id'], second['id']]
        for value in (first, second):
            value.update(superseded_by=merged['id'], changed=LATER)
        items = dict(self.items, **{value['id']: value for value in (first, second, merged)})
        both = row(ident('s', '1'), 'progress', 0, 'Both.', [first['id'], second['id']])
        other = row(ident('s', '2'), 'progress', 1, 'The rule.', [self.rule['id']])
        hidden = row(ident('s', '3'), 'blockers', 0, 'A private blocker.', [first['id'], SECRET])

        def recite(*lines):
            return state_rewrite.recite(state={'lines': list(lines)}, removed={'removed': []}, items=items,
                                        private=frozenset([SECRET]), at=LATER, device=DEVICE)
        result = recite(both, other, hidden)
        # Two merged items that one line cites become one citation of the item that merged them.
        self.assertEqual(result['state']['lines'], [dict(both, cites=[merged['id']], at=LATER), other, hidden])
        self.assertEqual(result['operations'], [{'id': both['id'], 'op': 'recited', 'why': 'recited'}])
        self.assertIsNone(recite(other, hidden))


if __name__ == '__main__':
    unittest.main()
