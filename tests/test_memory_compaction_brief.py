"""TASK-113: the compaction brief hook's text (API-155; SPEC-146) on made-up format-2 stores.

TC-407 to TC-410 at `compaction_brief.compose` and `output`. Nothing calls the
module before the 0.3.0 activation, so these are direct module results: the
hook's input, its exit code, its timing line and its failure log lines remain
for the activation. The input's `trigger`, `manual` or `auto`, is handled alike
and never read, so the module takes no trigger.
"""
from pathlib import Path
import sys
import time
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import clock, compaction_brief, item_types, locks, start_summary, state_types
import test_memory_curation_worker as worker_fixture
import test_memory_start_summary as start_fixture

AT, DEVICE = worker_fixture.AT, worker_fixture.DEVICE
line = start_fixture.line
BRIEF = '\n'.join(compaction_brief.BRIEF)


class CompactionBriefTest(unittest.TestCase):
    """The brief on the start summary's store fixture, whose own tests stay in their module."""
    Fixture = worker_fixture.CurationWorkerTest
    configure, layer, saved, one_turn = Fixture.configure, Fixture.layer, Fixture.saved, Fixture.one_turn
    items, write = Fixture.items, Fixture.write
    setUp, item = start_fixture.StartSummaryTest.setUp, start_fixture.StartSummaryTest.item

    def compose(self, host='claude-code', seconds=5):
        settings = self.memory.configuration(deadline=clock.now() + 10)
        return compaction_brief.compose(self.memory, 'sample', host, clock.now() + seconds, settings=settings)

    def brief(self, *rows):
        """The text that the hook prints: the brief, and the state lines after its last line."""
        return '\n'.join((BRIEF,) + rows) + '\n' if rows else '\n'.join(compaction_brief.BRIEF[:-1]) + '\n'

    def files(self):
        return {path.relative_to(self.folder).as_posix(): path.read_bytes()
                for path in sorted(self.folder.rglob('*')) if path.is_file()}

    # SPEC-146#1

    def test_tc407_the_brief_then_the_goal_and_three_next_actions_as_plain_text(self):
        rule = self.item('Keep one script')
        lines = [line('goal', 1, 'Ship the compaction hooks.', [rule['id']]),
                 line('decisions', 1, 'One script serves the hooks.', [rule['id']]),
                 line('progress', 1, 'The brief is written.', [rule['id']]),
                 line('blockers', 1, 'Dead end: Printing JSON makes the host read hook JSON.', [rule['id']]),
                 line('next', 3, 'Tag the release.', [rule['id']]),
                 line('next', 1, 'Write the tests.', [rule['id'], self.said['id']]),
                 line('next', 2, 'Done when: the hook check passes on Windows.', [rule['id']])]
        self.layer([rule], lines)
        result = self.compose()
        self.assertEqual((result.outcome, result.error), ('ok', None))
        # The goal first, then the next actions in their order, with the done condition under its own label; the
        # other parts, which the session start shows again after the compaction, are not repeated.
        self.assertEqual(result.text, self.brief('- Goal: Ship the compaction hooks.',
                                                 '- Next action: Write the tests.',
                                                 '- Done when: the hook check passes on Windows.',
                                                 '- Next action: Tag the release.'))
        data = compaction_brief.output(result)
        self.assertEqual(data, result.text.encode('utf-8'))
        self.assertTrue(data.startswith(b'Write the summary as a handoff brief'))
        self.assertNotIn(b'\r', data)
        self.assertLess(len(result.text), 10000)
        for value in (rule['id'], self.said['id']):
            self.assertNotIn(value, result.text)

    def test_the_brief_is_brief_1_of_stage_06(self):
        self.assertEqual(len(compaction_brief.BRIEF), 10)
        self.assertEqual(compaction_brief.BRIEF[6], '6. Remaining plan: next steps in order and the very next action, '
                         'then a line that starts with "Done when:" and gives the condition for done.')
        self.assertEqual(compaction_brief.BRIEF[-1], 'Current memory state (do not restate; correct it only if the '
                         'conversation contradicts it):')
        stage = (ROOT / 'docs/06-api/memory.md').read_text(encoding='utf-8')
        self.assertIn('```text\n' + BRIEF + '\n```', stage)
        # The brief and the state's room, with their line breaks, stay under 10,000 characters, Claude Code's limit
        # for one hook's output (SPEC-146), also counted in UTF-16 code units as the host may count them.
        self.assertLess(len(BRIEF.encode('utf-16-le')) // 2 + 1 + 2 * compaction_brief.STATE_CHARACTERS, 10000)

    def test_lines_show_on_one_line_as_the_start_summary_shows_them_and_text_outside_ascii_whole(self):
        rule = self.item('Keep one script')
        lines = [line('goal', 1, '압축 뒤에도  목표를\t지킨다.', [rule['id']]),
                 line('next', 1, 'Done when:', [rule['id']]),
                 line('next', 2, 'Done when:   검사가 통과한다.', [rule['id']]),
                 line('next', 3, 'done when: a marker in small letters stays a next action.', [rule['id']])]
        self.layer([rule], lines)
        result = self.compose()
        self.assertEqual(result.text, self.brief('- Goal: 압축 뒤에도 목표를 지킨다.', '- Done when:',
                                                 '- Done when: 검사가 통과한다.',
                                                 '- Next action: done when: a marker in small letters stays a next '
                                                 'action.'))
        self.assertEqual(compaction_brief.output(result).decode('utf-8'), result.text)

    # SPEC-146#2

    def test_tc408_whole_lines_under_1500_characters_the_goals_first(self):
        rule = self.item('Keep one script')
        goals = [line('goal', n, 'Goal %d %s' % (n, 'g' * 290), [rule['id']]) for n in (1, 2)]
        actions = [line('next', 1, 'Done when: %s' % ('d' * 290), [rule['id']])]
        actions += [line('next', n, 'Step %d %s' % (n, 's' * 290), [rule['id']]) for n in range(2, 10)]
        self.layer([rule], actions + goals)
        self.assertGreaterEqual(sum(len(value['text']) for value in goals + actions), 3000)
        result = self.compose()
        self.assertEqual(result.outcome, 'ok')
        rows = result.text.split('\n')[len(compaction_brief.BRIEF):-1]
        # Whole lines, the goals first, the done condition under its own label, and the next actions left out from
        # the last one back: with its line break each goal takes 306 characters, the done condition 304 and each
        # step 313, so the second step is the last that fits under 1,500.
        self.assertEqual(rows, ['- Goal: Goal 1 ' + 'g' * 290, '- Goal: Goal 2 ' + 'g' * 290,
                                '- Done when: ' + 'd' * 290, '- Next action: Step 2 ' + 's' * 290])
        self.assertEqual(sum(len(row) + 1 for row in rows), 1229)

    def test_goals_that_do_not_fit_go_from_the_last_one_back_after_every_next_action(self):
        rule = self.item('Keep one script')
        # Lines that do not fit are left out from the last next action back (SPEC-146, API-155 step 4): every next
        # action goes before a goal does, the done condition too, also where it would fit once a goal has gone.
        goals = [line('goal', n, 'Goal %d %s' % (n, 'g' * 590), [rule['id']]) for n in (1, 2, 3)]
        self.layer([rule], goals + [line('next', 1, 'Done when: the tests pass.', [rule['id']])])
        result = self.compose()
        self.assertEqual(result.text, self.brief('- Goal: Goal 1 ' + 'g' * 590, '- Goal: Goal 2 ' + 'g' * 590))

    def test_a_line_that_does_not_fit_alone_leaves_the_brief_without_its_last_line(self):
        rule = self.item('Keep one script')
        # With its label and line break, a goal of 1,491 characters takes 1,500, which is not under 1,500.
        self.layer([rule], [line('goal', 1, 'g' * 1491, [rule['id']])])
        self.assertEqual(self.compose().text, self.brief())
        # One of 1,490 takes 1,499 and goes whole, and a next action that does not fit after it is left out.
        self.layer([rule], [line('goal', 1, 'g' * 1490, [rule['id']]), line('next', 1, 'A step.', [rule['id']])])
        self.assertEqual(self.compose().text, self.brief('- Goal: ' + 'g' * 1490))

    def test_every_line_counts_with_its_line_break(self):
        rule = self.item('Keep one script')
        # A goal of 742 characters takes 751 with its label and line break; a second of 740 takes 749, 1,500 in all,
        # which is not under 1,500, and one of 739 takes 748, 1,499 in all.
        for size, shown in ((740, False), (739, True)):
            first, second = line('goal', 1, 'g' * 742, [rule['id']]), line('goal', 2, 'h' * size, [rule['id']])
            self.layer([rule], [first, second])
            rows = ('- Goal: ' + 'g' * 742,) + (('- Goal: ' + 'h' * size,) if shown else ())
            self.assertEqual(self.compose().text, self.brief(*rows), size)

    def test_without_a_goal_or_next_action_the_brief_alone_without_its_last_line(self):
        rule = self.item('Keep one script')
        self.layer([rule], [line('decisions', 1, 'One script serves the hooks.', [rule['id']]),
                            line('blockers', 1, 'Dead end: polling.', [rule['id']])])
        self.assertEqual(self.compose().text, self.brief())
        # A project whose memory was deleted, or without a layer, has no state.
        self.layer([rule], [line('goal', 1, 'A goal.', [rule['id']])])
        (self.root / 'layer/deleted.json').write_bytes(b'{}\n')
        self.assertEqual(self.compose().text, self.brief())
        for path in sorted((self.root / 'layer').rglob('*'), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        (self.root / 'layer').rmdir()
        self.assertEqual(self.compose().outcome, 'ok')
        self.assertEqual(self.compose().text, self.brief())

    def test_the_brief_reads_no_item_file_so_a_damaged_decision_item_does_not_stop_it(self):
        rule = self.item('Keep one script')
        self.layer([rule], [line('goal', 1, 'A goal.', [rule['id']]),
                            line('decisions', 1, 'One script serves the hooks.', [rule['id']]),
                            line('next', 1, 'A step.', [rule['id']])])
        (self.root / 'layer/items' / (rule['id'] + '.json')).write_bytes(b'{"id": ')
        read, folders = start_summary._read, []

        def reading(memory, path, deadline):
            folders.append(Path(path).parent.name)
            return read(memory, path, deadline)
        with mock.patch.object(start_summary, '_read', side_effect=reading):
            result = self.compose()
        self.assertEqual(result.outcome, 'ok')
        self.assertEqual(result.text, self.brief('- Goal: A goal.', '- Next action: A step.'))
        self.assertIn('layer', folders)
        self.assertNotIn('items', folders)
        # Such a view gives no reader of items; the start summary, which shows the decision, reads the item, and
        # cannot.
        self.assertIsNone(start_summary.layer_view(self.memory, self.root, clock.now() + 5, decisions=False).current)
        with self.assertRaises(ValueError):
            start_summary.layer_view(self.memory, self.root, clock.now() + 5)

    def test_lines_that_the_validity_view_leaves_out_are_not_given(self):
        kept, forgotten = self.item('Kept'), self.item('Forgotten')
        private = line('goal', 1, 'Quotes forgotten words.', [forgotten['quotes'][0]['entry']])
        removed = line('next', 1, 'Removed by an edit.', [kept['id']])
        shown = line('next', 2, 'Kept.', [kept['id']])
        self.layer([kept, forgotten], [private, removed, shown])
        tombstone = dict(item=forgotten['id'], project='sample', at=AT, device=DEVICE, quotes=[
            {k: forgotten['quotes'][0][k] for k in ('device', 'entry', 'log', 'start', 'end')}])
        (self.root / 'layer/tombstones' / (forgotten['id'] + '.json')).write_bytes(item_types._raw(tombstone))
        (self.root / 'layer/state-removed.json').write_bytes(state_types.removed_bytes({'removed': [
            dict(id=removed['id'], at=AT, device=DEVICE, kind='edit')]}))
        self.assertEqual(self.compose().text, self.brief('- Next action: Kept.'))

    # SPEC-146#3, SPEC-146#4

    def test_tc409_nothing_in_codex_for_a_project_not_enabled_or_without_consent(self):
        rule = self.item('Keep one script')
        self.layer([rule], [line('goal', 1, 'A goal.', [rule['id']])])
        self.assertEqual(self.compose(host='codex'), compaction_brief.Result(None))
        # Consent to another version of its text is no consent to the one in use.
        for options in (dict(enabled=False), dict(consent=None), dict(consent=2)):
            self.configure(**options)
            result = self.compose()
            self.assertEqual(result, compaction_brief.Result(None), options)
            self.assertEqual(compaction_brief.output(result), b'')

    def test_tc409_a_state_that_cannot_be_read_gives_error_and_prints_nothing(self):
        rule = self.item('Keep one script')
        self.layer([rule], [line('goal', 1, 'A goal.', [rule['id']])])
        (self.root / 'layer/state.json').write_bytes(b'{"lines": [')
        result = self.compose()
        self.assertEqual((result.outcome, result.text), ('error', ''))
        self.assertIsInstance(result.error, ValueError)
        self.assertEqual(compaction_brief.output(result), b'')
        # So does a store that another one replaced since the hook found it.
        self.layer([rule], [line('goal', 1, 'A goal.', [rule['id']])])
        settings, pin = self.memory.configuration(deadline=clock.now() + 10), self.memory.pin
        self.memory.pin = 'another store'
        try:
            result = compaction_brief.compose(self.memory, 'sample', 'claude-code', clock.now() + 5, settings=settings)
        finally:
            self.memory.pin = pin
        self.assertEqual((result.outcome, type(result.error)), ('error', locks.LostLock))
        # And a configuration that cannot tell whether the project is enabled.
        class Unreadable:
            def enabled(self, project):
                raise ValueError('unreadable configuration')
        result = compaction_brief.compose(self.memory, 'sample', 'claude-code', clock.now() + 5, settings=Unreadable())
        self.assertEqual((result.outcome, result.text, type(result.error)), ('error', '', ValueError))

    def test_tc409_a_brief_that_passes_its_500_ms_gives_deadline_and_prints_nothing(self):
        rule = self.item('Keep one script')
        self.layer([rule], [line('goal', 1, 'A goal.', [rule['id']])])
        view = start_summary.layer_view

        def slow(*args, **kwargs):
            value = view(*args, **kwargs)
            time.sleep(0.6)
            return value
        started = time.monotonic()
        with mock.patch.object(start_summary, 'layer_view', side_effect=slow):
            result = self.compose(seconds=0.5)
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(result, compaction_brief.Result('deadline', error='deadline'))
        self.assertEqual(compaction_brief.output(result), b'')
        # A deadline that has passed before the brief begins gives it too.
        self.assertEqual(self.compose(seconds=0).outcome, 'deadline')

    # SPEC-146#5

    def test_tc410_the_brief_writes_nothing(self):
        rule = self.item('Keep one script')
        self.layer([rule], [line('goal', 1, 'A goal.', [rule['id']]), line('next', 1, 'A step.', [rule['id']])])
        before = self.files()
        for host in ('claude-code', 'codex'):
            self.compose(host=host)
        (self.root / 'layer/state.json').write_bytes(b'{"lines": [')
        before['projects/sample/layer/state.json'] = b'{"lines": ['
        self.assertEqual(self.compose().outcome, 'error')
        self.assertEqual(self.files(), before)


if __name__ == '__main__':
    unittest.main()
